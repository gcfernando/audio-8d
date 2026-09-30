# Developed by ::> Gehan Fernando
"""Every option the window also has: it exists, parses, and matches the window."""

import argparse

import pytest

from src import gui_model
from src.batch import MAX_JOBS
from src.core.presets import PRESETS
from src.core.settings import BITRATES, FORMAT_EXTENSIONS
from src.options import LOUDNESS_MATCH, create_parser

# (typed after a song, the setting it sets, the value it gets)
_PARSES = [
    (["--no-beat-sync"], "beat_sync", False),
    (["--no-exact-loudness"], "exact_loudness", False),
    (["--speed-curve", "off"], "speed_curve", ()),
    (["--intensity-curve", "none"], "intensity_curve", ()),
    (["--bpm", "off"], "bpm", "off"),
    (["--speakers"], "speakers", True),
    (["--no-speakers"], "speakers", False),
    (["--no-cover"], "no_cover", True),
    (["--cover"], "no_cover", False),
    (["--keep-title"], "keep_title", True),
    (["--title-tag"], "keep_title", False),
    (["--start", "off"], "start", "off"),
    (["--end", "none"], "end", "off"),
    (["--preview", "45"], "preview", 45.0),
    (["--dry-run"], "dry_run", True),
    (["--suggest"], "suggest", True),
    (["--style-description", "for parties"], "style_description", "for parties"),
    (["--update-style", "Mine"], "update_style", "Mine"),
    (["--rename-style", "Mine", "Yours"], "rename_style", ["Mine", "Yours"]),
    (["--duplicate-style", "Mine", "Copy"], "duplicate_style", ["Mine", "Copy"]),
    (["--delete-style", "Mine"], "delete_style", "Mine"),
    (["--export-style", "Mine", "m.json"], "export_style", ["Mine", "m.json"]),
    (["--import-style", "m.json"], "import_style", ["m.json"]),
    (["--import-style", "m.json", "New"], "import_style", ["m.json", "New"]),
    (["--clear-cache"], "clear_cache", True),
    (["--delete-logs"], "delete_logs", True),
]


def _parse(*words: str) -> argparse.Namespace:
    return create_parser().parse_args(["a.mp3", *words])


@pytest.mark.parametrize(("words", "dest", "value"), _PARSES)
def test_every_new_option_exists_and_parses(words: list[str], dest: str, value) -> None:
    assert getattr(_parse(*words), dest) == value


@pytest.mark.parametrize(("_words", "dest", "_value"), _PARSES)
def test_not_typing_an_option_leaves_it_unset(_words, dest: str, _value) -> None:
    # None (or False) means "not typed", so a style's own value is kept
    assert getattr(_parse(), dest) in (None, False)


def test_several_songs_can_be_typed() -> None:
    args = _parse("b.flac", "Music")
    assert [str(path) for path in (args.input, args.output, *args.more)] == [
        "a.mp3",
        "b.flac",
        "Music",
    ]


def test_the_formats_are_the_windows_formats() -> None:
    window = set(gui_model.FORMAT_CHOICES.values())
    assert window == set(FORMAT_EXTENSIONS)
    for name in window:
        assert _parse("--format", name).format == name
    with pytest.raises(SystemExit):
        _parse("--format", "ogg")


def test_the_bitrates_are_the_windows_bitrates() -> None:
    window = {int(b) for b in gui_model.BITRATE_CHOICES if b != "Auto"}
    assert window == set(BITRATES)
    for bitrate in BITRATES:
        assert _parse("--bitrate", str(bitrate)).bitrate == bitrate
    assert _parse("--bitrate", "auto").bitrate == "auto"


def test_every_loudness_the_window_offers_can_be_typed() -> None:
    offered = {**gui_model.LOUDNESS_MAIN, **gui_model.LOUDNESS_MORE}
    for value in offered.values():
        if value in ("advanced", "custom"):
            continue
        typed = "off" if value is None else str(value)
        parsed = _parse("--loudness", typed).loudness
        assert parsed == (LOUDNESS_MATCH if value == "match" else value or "off")


def test_every_built_in_style_can_be_typed() -> None:
    for name in PRESETS:
        assert _parse("--style", name.upper()).preset == name


def test_songs_at_once_has_the_windows_limit() -> None:
    assert _parse("--jobs", str(MAX_JOBS)).jobs == MAX_JOBS
    with pytest.raises(SystemExit):
        _parse("--jobs", str(MAX_JOBS + 1))


def test_the_window_offers_no_preview_length_the_command_line_refuses() -> None:
    for seconds in (15, 30, 45, 60):
        assert _parse("--preview", str(seconds)).preview == seconds
