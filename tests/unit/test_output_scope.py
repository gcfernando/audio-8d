# Developed by ::> Gehan Fernando
"""Output settings: defaults for all songs, one song's own overrides, and reset.

The window's Output step, its Customize dialog and the command line's
--per-song file all use the same rule: a song follows the defaults unless it
has a value of its own, and 'Reset to default' removes only its own values.
"""

from pathlib import Path

from src import cli
from src.app_previews import song_trim
from src.core.preferences import Preferences, load_preferences, save_preferences
from src.core.types import Trim
from src.gui_model import (
    REMEMBERED_OUTPUT,
    GuiSettings,
    apply_output_defaults,
    file_value,
    output_defaults,
    reset_file_settings,
    set_file_settings,
    song_config,
)
from src.options import create_parser
from src.per_song import parse_line

A, B, C = Path("music/a.mp3"), Path("music/b.mp3"), Path("music/c.mp3")


def _format(settings: GuiSettings, song: Path) -> str:
    return song_config(settings, song).output_format


def test_songs_without_their_own_output_follow_every_change_of_the_defaults() -> None:
    settings = GuiSettings()
    settings.change(output_format="flac")

    assert _format(settings, A) == _format(settings, B) == "flac"
    # A song added later simply follows the defaults as they are now
    assert _format(settings, C) == "flac"


def test_one_song_can_be_saved_differently_without_touching_the_others() -> None:
    settings = GuiSettings()
    set_file_settings(settings, [A], output_format="m4a", keep_cover=False)

    assert _format(settings, A) == "m4a"
    assert _format(settings, B) == "mp3"
    assert file_value(settings, B, "keep_cover") is True
    assert settings.song_files == {A: {"output_format": "m4a", "keep_cover": False}}


def test_changing_the_defaults_never_overwrites_a_songs_own_output() -> None:
    settings = GuiSettings()
    set_file_settings(settings, [A], output_format="m4a")
    settings.change(output_format="opus")

    assert _format(settings, A) == "m4a"
    assert _format(settings, B) == "opus"
    # The song's own format keeps its own quality tier (M4A High is 256 kbps)
    assert file_value(settings, A, "bitrate") == 256


def test_a_value_equal_to_the_default_is_not_stored_as_an_override() -> None:
    settings = GuiSettings()
    set_file_settings(settings, [A], output_format="mp3", limiter_ceiling=0.84)

    assert A not in settings.song_files


def test_reset_to_default_removes_only_that_songs_own_output() -> None:
    settings = GuiSettings()
    set_file_settings(settings, [A], output_format="wav")
    set_file_settings(settings, [B], output_format="flac")
    settings.song_sound[A] = {"intensity": 0.5}

    assert reset_file_settings(settings, [A]) == 1
    assert _format(settings, A) == "mp3"
    assert _format(settings, B) == "flac"
    # Only the output override goes; the song's own sound stays
    assert settings.song_sound == {A: {"intensity": 0.5}}


def test_remembered_defaults_come_back_and_never_carry_a_songs_override(
    tmp_path: Path,
) -> None:
    settings = GuiSettings()
    settings.change(output_format="flac", loudness_target=None, match_loudness=True)
    set_file_settings(settings, [A], output_format="m4a")
    saved = output_defaults(settings)
    file = tmp_path / "settings.json"
    save_preferences(Preferences(output=saved, default_style="smooth"), file)

    loaded, problem = load_preferences(file)
    fresh = GuiSettings()
    assert problem is None and not apply_output_defaults(fresh, loaded.output)
    assert fresh.sound.output_format == "flac" and fresh.sound.match_loudness
    assert fresh.sound.limiter_ceiling == 0.89
    # Overrides belong to songs of one session and are never saved as defaults
    assert "m4a" not in str(saved) and not fresh.song_files
    assert loaded.default_style == "smooth"


def test_unusable_remembered_defaults_are_ignored_not_fatal() -> None:
    fresh = GuiSettings()
    ignored = apply_output_defaults(
        fresh,
        {"bitrate": 999, "originals": "replace", "destination": "not/absolute",
         "output_format": "wav"},
    )  # fmt: skip

    assert sorted(ignored) == ["bitrate", "destination", "originals"]
    assert fresh.sound.output_format == "wav" and fresh.originals == "keep"


def test_the_command_line_uses_the_same_default_and_override_rule(
    tmp_path: Path,
) -> None:
    rules_file = tmp_path / "songs.txt"
    rules_file.write_text('"a.mp3" --format m4a\n"b.mp3" --format wav\n', "utf-8")
    args = create_parser().parse_args(
        ["music", "--format", "opus", "--per-song", str(rules_file)]
    )
    plan = cli.plan_from_args(args)

    def cli_format(song: Path) -> str:
        return cli.song_setup(song, plan)[0].output_format

    # The run's --format is the default; a per-song line overrides one song
    assert cli_format(A) == "m4a" and cli_format(B) == "wav" and cli_format(C) == "opus"
    # The same choices in the window give the same files
    settings = GuiSettings()
    settings.change(output_format="opus")
    set_file_settings(settings, [A], output_format="m4a")
    set_file_settings(settings, [B], output_format="wav")
    for song in (A, B, C):
        assert _format(settings, song) == cli_format(song)


def test_the_command_lines_reset_is_a_default_line() -> None:
    rule = parse_line('"a.mp3" --default', 1)

    assert rule is not None and rule.reset


def test_a_preview_uses_the_part_of_the_song_that_will_be_made() -> None:
    settings = GuiSettings(trim_start="0:10")
    set_file_settings(settings, [A], trim_start="1:00", trim_end="2:00")

    assert song_trim(settings, B) == Trim(10.0, None)
    assert song_trim(settings, A) == Trim(60.0, 120.0)


def _cli_setup(tmp_path: Path, lines: str, *options: str):
    """(config, options) the command line gives song A with these --per-song lines."""
    rules_file = tmp_path / "songs.txt"
    rules_file.write_text(lines, "utf-8")
    args = create_parser().parse_args(
        ["music", *options, "--per-song", str(rules_file)]
    )
    return cli.song_setup(A, cli.plan_from_args(args))


def test_a_default_line_on_the_command_line_resets_a_songs_output(
    tmp_path: Path,
) -> None:
    config, _options = _cli_setup(
        tmp_path, '"a.mp3" --format m4a\n"a.mp3" --default\n', "--format", "opus"
    )
    assert config.output_format == "opus"


def test_a_songs_own_format_keeps_its_quality_tier_on_the_command_line(
    tmp_path: Path,
) -> None:
    config, _options = _cli_setup(
        tmp_path, '"a.mp3" --format m4a\n', "--format", "opus"
    )
    settings = GuiSettings()
    settings.change(output_format="opus")
    set_file_settings(settings, [A], output_format="m4a")

    assert config.bitrate == file_value(settings, A, "bitrate") == 256


def test_remembered_defaults_hold_only_output_default_keys() -> None:
    settings = GuiSettings()
    set_file_settings(settings, [A], output_format="m4a", trim_start="0:30")
    saved = output_defaults(settings)

    assert set(saved) <= set(REMEMBERED_OUTPUT)
    assert "originals" not in saved and "overwrite" not in saved
    assert saved["output_format"] == "mp3"
