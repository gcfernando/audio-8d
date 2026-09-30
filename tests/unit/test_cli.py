# Developed by ::> Gehan Fernando
"""Checks the audio8d command: options, styles, folders, messages and guided mode."""

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from src import (
    PRESETS,
    AudioStreamInfo,
    ConversionError,
    InputValidationError,
    cli,
)
from src.batch import BatchOutcome, BatchReport
from src.files import resolve_input as real_resolve_input
from src.pipeline import ConversionResult

_SOURCE = AudioStreamInfo("mp3", 2, 44100, 180.0)


@pytest.fixture(autouse=True)
def _pretend_songs_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let tests use made-up song names without real files on disk."""
    monkeypatch.setattr(cli, "resolve_input", lambda path: path)
    monkeypatch.setattr(cli, "_peek_source", lambda path: None)


def _recorder(seen: dict[str, Any]):
    """A stand-in for convert() that remembers its arguments and 'succeeds'."""

    def fake_convert(**kwargs: Any) -> ConversionResult:
        seen.update(kwargs)
        return ConversionResult(
            source=_SOURCE,
            output=Path(str(kwargs["output_path"])),
            config=kwargs["config"],
        )

    return fake_convert


def test_no_knobs_means_the_studio_style_saved_the_standard_way() -> None:
    args = cli.create_parser().parse_args(["in.mp3", "out.mp3"])

    # The same default as the window: Studio, MP3 High quality, music-app loudness
    assert cli.resolve_config(args) == PRESETS["studio"].config
    assert args.overwrite is False


def test_quality_outside_range_is_a_usage_error() -> None:
    with pytest.raises(SystemExit):
        cli.create_parser().parse_args(["in.mp3", "out.mp3", "--quality", "10"])


def test_main_passes_options_through(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "convert", _recorder(seen))
    code = cli.main(
        ["a.wav", "b.mp3", "--intensity", "0.5", "--quality", "0", "--overwrite"]
    )

    assert code == 0
    assert seen["input_path"] == Path("a.wav")
    assert seen["overwrite"] is True
    assert seen["config"] == dataclasses.replace(
        PRESETS["studio"].config, intensity=0.5, quality=0
    )


def test_main_returns_1_on_known_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_convert(**_: object) -> None:
        """Fail the way a broken encode would."""
        raise ConversionError("boom")

    monkeypatch.setattr(cli, "convert", failing_convert)

    assert cli.main(["a.wav", "b.mp3"]) == 1


def test_default_output_sits_next_to_the_input() -> None:
    assert cli.default_output_for(Path("music/song.flac")) == Path(
        "music/song (8D).mp3"
    )


def test_output_name_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "convert", _recorder(seen))

    assert cli.main(["song.wav"]) == 0
    assert seen["output_path"] == Path("song (8D).mp3")


def test_format_changes_the_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "convert", _recorder(seen))

    assert cli.main(["song.wav", "--format", "flac"]) == 0
    assert seen["output_path"] == Path("song (8D).flac")


def test_output_extension_picks_the_format() -> None:
    args = cli.create_parser().parse_args(["in.mp3", "out.m4a"])

    assert cli.resolve_config(args).output_format == "m4a"


def test_output_dir_and_original_name(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "convert", _recorder(seen))

    assert cli.main(["music/a.mp3", "--output-dir", "out", "--name", "original"]) == 0
    assert seen["output_path"] == Path("out/a.mp3")


def test_replace_keeps_the_original_name_and_asks_to_remove_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "convert", _recorder(seen))

    assert cli.main(["music/a.mp3", "--replace"]) == 0
    assert seen["output_path"] == Path("music/a.mp3")
    assert seen["options"].replace_original is True


def test_replace_can_keep_the_8d_name(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "convert", _recorder(seen))

    assert cli.main(["music/a.mp3", "--replace", "--name", "8d"]) == 0
    assert seen["output_path"] == Path("music/a (8D).mp3")


def test_trim_and_file_switches_reach_the_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "convert", _recorder(seen))

    cli.main(
        ["a.mp3", "--start", "1:00", "--end", "1:30", "--no-cover", "--keep-title"]
    )
    options = seen["options"]
    assert options.trim.start == 60 and options.trim.end == 90
    assert options.keep_cover is False
    assert options.tag_title is False


def test_end_before_start_is_explained(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["a.mp3", "--start", "2:00", "--end", "1:00"]) == 1
    assert "What to do:" in capsys.readouterr().err


def test_new_sound_knobs_are_applied() -> None:
    args = cli.create_parser().parse_args(
        [
            "a.mp3",
            "--path", "figure8",
            "--direction", "counterclockwise",
            "--bass", "off",
            "--elevation", "0.5",
            "--fade", "0",
            "--speed-curve", "0=10, 1:00=6",
            "--bpm", "128",
            "--engine", "pan",
        ]
    )  # fmt: skip
    config = cli.resolve_config(args)

    assert config.path == "figure8"
    assert config.direction == "counterclockwise"
    assert config.bass_hz == 0
    assert config.elevation == 0.5
    assert config.fade_seconds == 0
    assert config.speed_curve == ((0.0, 10.0), (60.0, 6.0))
    assert config.bpm == 128
    assert config.engine == "pan"


def test_speakers_makes_any_style_speaker_safe() -> None:
    args = cli.create_parser().parse_args(["a.mp3", "--preset", "strong", "--speakers"])
    config = cli.resolve_config(args)

    assert config.engine == "pan"
    assert config.intensity <= 0.6


def test_bad_curve_is_a_usage_error() -> None:
    with pytest.raises(SystemExit):
        cli.create_parser().parse_args(["a.mp3", "--speed-curve", "fast"])


@pytest.mark.parametrize(
    "typed",
    [
        r"C:\Music\My Song.mp3",
        r'"C:\Music\My Song.mp3"',
        r"'C:\Music\My Song.mp3'",
        r'  "C:\Music\My Song.mp3"  ',
        r"& 'C:\Music\My Song.mp3'",
    ],
)
def test_dragged_or_pasted_paths_are_cleaned(typed: str) -> None:
    # pylint: disable-next=protected-access
    assert cli._clean_typed_path(typed) == r"C:\Music\My Song.mp3"


# ------------------------------------------------------------------ folders


def _music_folder(tmp_path: Path) -> Path:
    """A folder with three songs, one in a sub-folder, and an old 8D copy."""
    folder = tmp_path / "Music"
    (folder / "Rock").mkdir(parents=True)
    for name in ("a.mp3", "b.flac", "Rock/c.wav", "a (8D).mp3", "notes.txt"):
        (folder / name).write_bytes(b"audio")
    return folder


def _fake_batch(seen: dict[str, Any]):
    """A stand-in for run_batch that 'converts' every item."""

    def fake_run_batch(items, config, **kwargs):
        seen["items"] = items
        seen["config"] = config
        seen.update(kwargs)
        report = BatchReport()
        for item in items:
            report.outcomes.append(
                BatchOutcome(item, ConversionResult(_SOURCE, item.output, config))
            )
        return report

    return fake_run_batch


def test_a_folder_converts_every_song(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "run_batch", _fake_batch(seen))
    folder = _music_folder(tmp_path)

    assert cli.main([str(folder), "--jobs", "2"]) == 0
    items = seen["items"]
    # a (8D).mp3 is skipped as already made; its own 8D copy is never re-converted
    assert [item.source.name for item in items] == ["b.flac"]
    assert seen["jobs"] == 2
    assert "Skipped (already made): a (8D).mp3" in capsys.readouterr().err


def test_recursive_folder_with_output_dir_mirrors_sub_folders(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "run_batch", _fake_batch(seen))
    folder = _music_folder(tmp_path)
    out = tmp_path / "8D"

    assert cli.main([str(folder), "--recursive", "--output-dir", str(out)]) == 0
    outputs = {item.output for item in seen["items"]}
    assert outputs == {
        out / "Rock" / "c (8D).mp3",
        out / "a (8D).mp3",
        out / "b (8D).mp3",
    }


def test_folder_replace_takes_the_original_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "run_batch", _fake_batch(seen))
    folder = _music_folder(tmp_path)

    assert cli.main([str(folder), "--replace"]) == 0
    pairs = {item.source.name: item.output.name for item in seen["items"]}
    assert pairs == {"a.mp3": "a.mp3", "b.flac": "b.mp3"}
    assert seen["options"].replace_original is True


def test_empty_folder_is_explained(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main([str(tmp_path)]) == 1
    assert "What to do:" in capsys.readouterr().err


def test_folder_with_output_file_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        cli.main([str(_music_folder(tmp_path)), "out.mp3"])


# -------------------------------------------------------------- the guided mode


def _pretend_double_click(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> None:
    """Act like a real person in a terminal who types these answers in order."""
    monkeypatch.setattr(cli.sys, "argv", ["audio8d"])
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: True, raising=False)
    replies = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(replies))


def _song(tmp_path: Path) -> Path:
    """A tiny real file to stand in for a song."""
    song = tmp_path / "song.mp3"
    song.write_bytes(b"audio")
    return song


def test_double_click_asks_four_questions_and_converts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "convert", _recorder(seen))
    song = _song(tmp_path)
    # Dragged-in path, then Enter for style, destination, originals, and to close
    _pretend_double_click(monkeypatch, [f'"{song}"', "", "", "", ""])

    assert cli.main() == 0
    assert seen["input_path"] == song
    assert seen["output_path"] == tmp_path / "song (8D).mp3"
    assert seen["config"] == PRESETS["studio"].config
    assert seen["options"].replace_original is False


def test_guided_mode_can_save_elsewhere_and_replace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "convert", _recorder(seen))
    song = _song(tmp_path)
    out = tmp_path / "8D songs"
    _pretend_double_click(monkeypatch, [str(song), "", str(out), "2", ""])

    assert cli.main() == 0
    assert seen["output_path"] == out / "song.mp3"
    assert seen["options"].replace_original is True


def test_guided_mode_asks_again_for_a_missing_song(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "convert", _recorder(seen))
    song = _song(tmp_path)
    _pretend_double_click(
        monkeypatch, [str(tmp_path / "nope.mp3"), str(song), "", "", "", ""]
    )

    assert cli.main() == 0
    assert "I can't find that" in capsys.readouterr().out
    assert seen["input_path"] == song


def test_guided_mode_with_a_folder_lets_you_pick_songs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "run_batch", _fake_batch(seen))
    folder = _music_folder(tmp_path)
    # Songs are listed a.mp3, b.flac; "9" is refused, then "2" picks b.flac
    _pretend_double_click(monkeypatch, [str(folder), "9", "2", "", "", "", ""])

    assert cli.main() == 0
    shown = capsys.readouterr().out
    assert "Found 2 songs" in shown
    assert "is outside 1 to 2" in shown
    assert [item.source.name for item in seen["items"]] == ["b.flac"]


@pytest.mark.parametrize(
    ("answer", "style"), [("", "studio"), ("6", "smooth"), ("voice", "voice")]
)
def test_guided_mode_style_menu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, answer: str, style: str
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "convert", _recorder(seen))
    _pretend_double_click(monkeypatch, [str(_song(tmp_path)), answer, "", "", ""])

    assert cli.main() == 0
    assert seen["config"] == PRESETS[style].config


def test_guided_mode_explains_a_bad_style_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "convert", _recorder({}))
    _pretend_double_click(monkeypatch, [str(_song(tmp_path)), "99", "", "", "", ""])

    assert cli.main() == 0
    assert f"Please type a number from 1 to {len(PRESETS)}" in capsys.readouterr().out


def test_double_click_with_no_answer_does_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "convert", lambda **_: pytest.fail("should not convert"))
    _pretend_double_click(monkeypatch, ["", ""])

    assert cli.main() == 2


def test_scripts_without_arguments_still_get_a_usage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.sys, "argv", ["audio8d"])
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)

    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    assert exit_info.value.code == 2


# ------------------------------------------------------------------ styles


def test_preset_supplies_every_value() -> None:
    args = cli.create_parser().parse_args(["in.mp3", "--preset", "studio"])

    assert cli.resolve_config(args) == PRESETS["studio"].config


def test_typed_knobs_override_the_preset() -> None:
    args = cli.create_parser().parse_args(
        ["in.mp3", "--preset", "studio", "--intensity", "0.6", "--loudness", "off"]
    )
    config = cli.resolve_config(args)

    assert config.intensity == 0.6
    assert config.loudness_target is None
    assert config.quality == PRESETS["studio"].config.quality


def test_loudness_accepts_numbers_and_rejects_words() -> None:
    parser = cli.create_parser()
    args = parser.parse_args(["a.mp3", "--loudness", "-16"])

    assert cli.resolve_config(args).loudness_target == -16
    with pytest.raises(SystemExit):
        parser.parse_args(["a.mp3", "--loudness", "loud"])


def test_unknown_preset_is_a_usage_error() -> None:
    with pytest.raises(SystemExit):
        cli.create_parser().parse_args(["a.mp3", "--preset", "banana"])


def test_saved_style_can_be_used_by_name(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert (
        cli.main(["--preset", "studio", "--intensity", "0.9", "--save-preset", "mine"])
        == 0
    )
    # The name is saved in PascalCase, and letter case doesn't matter when using it
    assert "Saved your style 'Mine'" in capsys.readouterr().err

    args = cli.create_parser().parse_args(["a.mp3", "--preset", "mine"])
    assert args.preset == "Mine"
    config = cli.resolve_config(args)
    assert config.intensity == 0.9
    assert config.bitrate == PRESETS["studio"].config.bitrate
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "convert", _recorder(seen))
    assert cli.main(["a.mp3", "--preset", "mine"]) == 0

    # Saving under a name that's taken is refused, and the style is left alone
    assert (
        cli.main(["--preset", "studio", "--intensity", "0.5", "--save-preset", "MINE"])
        == 1
    )
    assert "already have a style called 'Mine'" in caplog.text
    assert cli.resolve_config(args).intensity == 0.9


def test_list_presets_prints_every_style_without_a_song(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--list-presets"])

    assert exit_info.value.code == 0
    shown = capsys.readouterr().out
    for name in PRESETS:
        assert name in shown
    assert "Gehan Fernando" in shown


def test_version_names_the_author(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--version"])

    assert "Gehan Fernando" in capsys.readouterr().out


def test_settings_panel_and_tip_are_shown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "convert", _recorder({}))

    assert cli.main(["song.wav"]) == 0
    shown = capsys.readouterr().err
    assert "8 s per full circle" in shown
    assert "studio" in shown
    assert "Created in" in shown
    assert "--preview" in shown


def test_tip_is_hidden_once_a_preset_is_chosen(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "convert", _recorder({}))

    cli.main(["song.wav", "--preset", "smooth"])
    assert "Tip:" not in capsys.readouterr().err


def test_typing_mistakes_get_a_plain_fix_and_an_example(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["song.mp3", "--quality", "11"])

    assert exit_info.value.code == 2
    shown = capsys.readouterr().err
    assert "invalid choice" in shown
    assert "What to do:" in shown
    assert "Example:" in shown


def test_errors_during_conversion_get_a_plain_fix(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(**_: object) -> None:
        """Fail the way an already-existing output would."""
        raise InputValidationError(
            "Output already exists: x.mp3. Use --overwrite to replace it."
        )

    monkeypatch.setattr(cli, "convert", refuse)

    assert cli.main(["song.mp3"]) == 1
    assert "What to do: add --overwrite" in capsys.readouterr().err


def test_help_shows_the_best_values(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--help"])

    shown = capsys.readouterr().out
    assert "QUICK START" in shown
    assert "DEFAULTS" in shown
    assert "--style studio" in shown
    # Older names still work but are left out of the help
    assert "--preset" not in shown and "--list-presets" not in shown
    assert "--output-dir" in shown
    assert "Gehan Fernando" in shown


def test_missing_song_is_explained_before_the_settings_panel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(cli, "resolve_input", real_resolve_input)
    monkeypatch.setattr(cli, "convert", lambda **_: pytest.fail("should not convert"))

    assert cli.main([str(tmp_path / "My Sonng.mp3")]) == 1
    shown = capsys.readouterr().err
    assert "Input file does not exist" in caplog.text
    assert "What to do:" in shown
    assert "Speed" not in shown


def test_bitrate_and_exact_loudness_can_be_typed() -> None:
    args = cli.create_parser().parse_args(
        ["a.mp3", "--bitrate", "320", "--exact-loudness"]
    )
    config = cli.resolve_config(args)

    assert config.bitrate == 320
    assert config.exact_loudness is True


def test_unknown_bitrate_is_a_usage_error() -> None:
    with pytest.raises(SystemExit):
        cli.create_parser().parse_args(["a.mp3", "--bitrate", "999"])


def test_preview_and_compare_modes_call_their_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_preview(song, output, config, **kwargs):
        seen["preview"] = (song, output, kwargs["seconds"])
        return ConversionResult(_SOURCE, output, config)

    def fake_compare(song, output, _config, **_):
        seen["compare"] = (song, output)
        return output

    monkeypatch.setattr(cli, "preview", fake_preview)
    monkeypatch.setattr(cli, "compare", fake_compare)

    # An OUTPUT given on purpose keeps the sample there
    assert cli.main(["a.mp3", "keep.wav", "--preview", "20"]) == 0
    assert seen["preview"] == (Path("a.mp3"), Path("keep.wav"), 20.0)
    assert cli.main(["a.mp3", "ab.mp3", "--compare"]) == 0
    assert seen["compare"] == (Path("a.mp3"), Path("ab.mp3"))


def test_loudness_can_match_the_original() -> None:
    args = cli.create_parser().parse_args(
        ["a.mp3", "--preset", "studio", "--loudness", "match"]
    )
    config = cli.resolve_config(args)

    assert config.match_loudness is True
    assert config.loudness_target is None
    args = cli.create_parser().parse_args(
        ["a.mp3", "--preset", "hifi", "--loudness", "-14"]
    )
    config = cli.resolve_config(args)
    assert config.match_loudness is False
    assert config.loudness_target == -14


def test_the_window_opens_with_every_song_it_was_given(monkeypatch) -> None:
    opened: list[list[Path]] = []
    monkeypatch.setattr("src.gui.run_gui", lambda songs: opened.append(songs) or 0)

    # Several songs dropped onto Audio8D.pyw arrive as plain arguments
    assert cli.main(["--gui", "a.mp3", "b.flac", "c.wav"]) == 0
    assert cli.main(["--gui"]) == 0
    assert opened == [[Path("a.mp3"), Path("b.flac"), Path("c.wav")], []]
    with pytest.raises(SystemExit):
        cli.main(["--gui", "a.mp3", "--no-such-option"])


def test_bitrate_auto_hands_mp3_back_to_its_quality() -> None:
    args = cli.create_parser().parse_args(
        ["a.mp3", "--preset", "studio", "--bitrate", "auto", "--quality", "0"]
    )

    config = cli.resolve_config(args)
    assert config.bitrate is None and config.quality == 0


@pytest.mark.parametrize("jobs", ["0", "17", "two"])
def test_songs_at_once_has_the_same_limits_as_the_window(jobs: str) -> None:
    with pytest.raises(SystemExit):
        cli.create_parser().parse_args(["music", "--jobs", jobs])


# ------------------------------------------------------------ checks and per song


def _ready_report(ok: bool = True):
    """A made-up system check: everything ready, or FFmpeg missing."""
    # pylint: disable-next=import-outside-toplevel
    from src.health import MISSING, READY, Dependency, HealthReport

    return HealthReport(
        (
            Dependency(
                "ffmpeg",
                "FFmpeg",
                True,
                READY if ok else MISSING,
                "Working." if ok else "ffmpeg was not found.",
                "make every 8D song",
                fix="" if ok else "Choose it with --ffmpeg PATH.",
            ),
            Dependency("singer", "Singer add-on", False, READY, "Ready.", "sing"),
        )
    )


def test_check_says_what_is_ready_and_what_to_fix(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "check_environment", _ready_report)
    assert cli.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "Required" in out and "Optional" in out and "Everything required" in out

    monkeypatch.setattr(cli, "check_environment", lambda: _ready_report(False))
    assert cli.main(["--check"]) == 1
    out = capsys.readouterr().out
    assert "Missing" in out and "--ffmpeg PATH" in out
    assert "can't create songs yet" in out


def test_typed_tool_paths_are_used_for_this_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    chosen: list[object] = []
    monkeypatch.setattr(cli, "set_preferred_paths", lambda *paths: chosen.extend(paths))
    monkeypatch.setattr(cli, "check_environment", _ready_report)
    python = tmp_path / "python.exe"

    assert (
        cli.main(["--check", "--ffmpeg", "C:/ff/ffmpeg.exe", "--python", str(python)])
        == 0
    )
    assert chosen[-2] == Path("C:/ff/ffmpeg.exe")
    assert cli.addons.preferred_python() == python


def test_install_addon_needs_a_working_python(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # pylint: disable-next=import-outside-toplevel
    from src.addons import PythonCheck

    monkeypatch.setattr(
        cli.addons,
        "find_python",
        lambda _p=None: PythonCheck(None, False, problem="No Python was found."),
    )
    assert cli.main(["--install-addon"]) == 1
    assert "python.org" in capsys.readouterr().out


def test_songs_get_their_own_settings_from_a_per_song_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "run_batch", _fake_batch(seen))
    folder = _music_folder(tmp_path)
    rules = tmp_path / "songs.txt"
    rules.write_text(
        '"b.flac"  --preset smooth --format flac --loudness match\n'
        "*.wav     --intensity 0.5 --start 0:10\n",
        encoding="utf-8",
    )

    code = cli.main(
        [str(folder), "--recursive", "--per-song", str(rules), "--output-dir", "o"]
    )
    assert code == 0
    items = {item.source.name: item for item in seen["items"]}
    flac = items["b.flac"]
    assert flac.output.suffix == ".flac"
    assert flac.config is not None and flac.config.match_loudness
    assert flac.config.intensity == PRESETS["smooth"].config.intensity
    wav = items["c.wav"]
    assert wav.config is not None and wav.config.intensity == 0.5
    assert wav.options is not None and wav.options.trim.start == 10.0
    # A song without a line keeps the run's own settings
    assert items["a.mp3"].config is None and items["a.mp3"].options is None


def test_songs_needing_the_singer_add_on_never_quietly_skip_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    # pylint: disable-next=import-outside-toplevel
    from src.addons import AddonStatus, PythonCheck

    monkeypatch.setattr(
        cli.addons,
        "singer_status",
        lambda refresh=False: AddonStatus(
            PythonCheck(None, False, problem="No Python was found.")
        ),
    )
    ran: dict[str, Any] = {}
    monkeypatch.setattr(cli, "convert", _recorder(ran))
    rules = tmp_path / "songs.txt"
    rules.write_text("song.wav --vocals center\n", encoding="utf-8")

    assert cli.main(["song.wav", "--per-song", str(rules)]) == 1
    assert not ran
    assert "needs the singer add-on (for song.wav)" in caplog.text
    assert "--install-addon" in capsys.readouterr().err
    assert cli.main(["other.wav", "--per-song", str(rules)]) == 0
