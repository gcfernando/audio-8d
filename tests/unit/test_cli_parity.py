# Developed by ::> Gehan Fernando
"""The command line and the window agree: styles, words, per-song resets, Customize."""

# pytest hands fixtures to tests by name, which pylint sees as shadowing
# pylint: disable=redefined-outer-name

import copy
import dataclasses
from pathlib import Path
from typing import Any

import pytest

from src import cli, gui_model
from src.core.errors import InputValidationError
from src.core.presets import (
    LEGACY_STYLES,
    PRESETS,
    RECOMMENDED_PRESET,
    STANDARD_OUTPUT,
    legacy_config,
    output_of,
    with_standard_output,
)
from src.core.sound_levels import MOVEMENT
from src.core.user_presets import all_presets
from src.gui_model import Changes, GuiSettings
from src.per_song import merged, parse_line, read_rules
from src.pipeline import ConversionResult

STYLES = dict(PRESETS)


@pytest.fixture(autouse=True)
def _pretend_songs_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Made-up song names are fine."""
    monkeypatch.setattr(cli, "resolve_input", lambda path: path)
    monkeypatch.setattr(cli, "_peek_source", lambda path: None)


def _args(*options: str):
    return cli.create_parser().parse_args(["a.mp3", *options])


def _config(*options: str):
    return cli.resolve_config(_args(*options))


# ------------------------------------------------------------------ styles


def test_the_default_style_is_studio_saved_the_standard_way() -> None:
    assert RECOMMENDED_PRESET == "studio"
    assert _config() == with_standard_output(PRESETS["studio"].config)
    assert cli.plan_from_args(_args()).preset == "studio"
    assert output_of(_config()) == STANDARD_OUTPUT


@pytest.mark.parametrize("name", list(PRESETS))
def test_a_style_only_changes_the_sound(name: str) -> None:
    config = _config("--style", name)

    assert output_of(config) == STANDARD_OUTPUT
    assert config == PRESETS[name].config
    # --preset is the same option under its old name
    assert _config("--preset", name) == config


@pytest.mark.parametrize("name", list(LEGACY_STYLES))
def test_older_style_names_keep_their_old_meaning(name: str) -> None:
    sound, output = LEGACY_STYLES[name]
    config = _config("--style", name.upper())

    assert config == legacy_config(name)
    for key, value in output.items():
        assert getattr(config, key) == value
    # Everything the old name didn't pin down comes from the style it was based on
    for key in ("rotation_seconds", "intensity", "ambience", "path", "engine"):
        if key not in output:
            assert getattr(config, key) == getattr(PRESETS[sound].config, key)


def test_the_legacy_output_is_exactly_as_before() -> None:
    assert _config("--style", "lossless").output_format == "flac"
    assert _config("--style", "lossless").limiter_ceiling == 0.89
    assert _config("--style", "streaming").exact_loudness is True
    hifi = _config("--style", "hifi")
    assert hifi.match_loudness and hifi.loudness_target is None
    # hifi keeps the gentler sound it always had, even though Gentle moved on
    assert (hifi.intensity, hifi.ambience) == (0.75, 0.20)
    assert hifi.rotation_seconds == PRESETS["gentle"].config.rotation_seconds


def test_typed_output_still_wins_over_a_legacy_style() -> None:
    config = _config("--style", "lossless", "--format", "wav")
    assert config.output_format == "wav" and config.limiter_ceiling == 0.89


def test_older_names_work_but_are_not_listed_as_styles(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        cli.create_parser().parse_args(["--list-styles"])
    listed = capsys.readouterr().out.lower()
    assert "studio" in listed and "groove" in listed
    # Only the one footnote that says the old names still work mentions them
    for name in LEGACY_STYLES:
        assert listed.count(name) == 1, name


def test_an_unknown_style_is_a_usage_error() -> None:
    with pytest.raises(SystemExit):
        _args("--style", "nope")


def test_movement_gentle_is_intensity_065() -> None:
    assert _config("--movement", "gentle") == _config("--intensity", "0.65")
    assert _config("--movement", "gentle").intensity == MOVEMENT.value_for("gentle")


def test_a_saved_style_keeps_only_the_sound(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = cli.main(
        [
            "--save-style",
            "my mix",
            "--style",
            "smooth",
            "--movement",
            "strong",
            "--format",
            "flac",
            "--loudness",
            "match",
        ]
    )
    assert code == 0
    assert "Saved your style 'My Mix'" in capsys.readouterr().err
    saved = all_presets()["My Mix"].config
    assert saved.intensity == 0.95
    assert saved.rotation_seconds == PRESETS["smooth"].config.rotation_seconds
    assert output_of(saved) == STANDARD_OUTPUT
    # And using it later gives the same sound
    assert _config("--style", "MY MIX") == saved


# ------------------------------------------------------------------ per song --default


def test_a_default_line_resets_the_song(tmp_path: Path) -> None:
    rules = tmp_path / "songs.txt"
    rules.write_text(
        "*.mp3        --style groove --format flac\n"
        '"Intro.mp3"  --default\n'
        "*.mp3        --speed slow\n",
        encoding="utf-8",
    )
    read = read_rules(rules)
    assert [rule.reset for rule in read] == [False, True, False]

    intro = [rule for rule in read if rule.matches(Path("Intro.mp3"))]
    assert merged(intro) == (None, {"rotation_seconds": 12.0})
    other = [rule for rule in read if rule.matches(Path("Other.mp3"))]
    assert merged(other) == (
        "groove",
        {"output_format": "flac", "rotation_seconds": 12.0},
    )
    assert merged(intro[:2]) == (None, {})


def test_default_goes_on_a_line_of_its_own() -> None:
    with pytest.raises(InputValidationError, match="line of its own"):
        parse_line('"Intro.mp3" --default --style groove', 7)


def test_a_reset_song_is_made_with_the_runs_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}

    def fake_convert(**kwargs: Any) -> ConversionResult:
        seen.update(kwargs)
        return ConversionResult(
            None,  # type: ignore[arg-type]
            kwargs["output_path"],
            kwargs["config"],
        )

    monkeypatch.setattr(cli, "convert", fake_convert)
    rules = tmp_path / "songs.txt"
    rules.write_text(
        "Intro.mp3  --style groove --speakers\nIntro.mp3  --default\n", "utf-8"
    )

    code = cli.main(["Intro.mp3", "--style", "smooth", "--per-song", str(rules)])
    assert code == 0
    assert seen["config"] == _config("--style", "smooth")


# ------------------------------------------------------------ window = command line


def test_the_window_starts_where_the_command_line_does() -> None:
    assert gui_model.config_for(GuiSettings()) == _config()


@pytest.mark.parametrize("name", ["groove", "sky", "speakers", "retro"])
def test_choosing_a_style_in_the_window_matches_style_on_the_command_line(
    name: str,
) -> None:
    settings = GuiSettings()
    settings.apply_style(PRESETS[name])
    assert gui_model.config_for(settings) == _config("--style", name)


def test_choosing_a_style_in_the_window_keeps_the_output_choices() -> None:
    settings = GuiSettings()
    settings.change(output_format="flac", bitrate=192, loudness_target=-16.0)
    settings.apply_style(PRESETS["strong"])

    config = gui_model.config_for(settings)
    assert (config.output_format, config.bitrate, config.loudness_target) == (
        "flac",
        192,
        -16.0,
    )
    assert config.intensity == PRESETS["strong"].config.intensity
    assert config == _config(
        "--style", "strong", "--format", "flac", "--bitrate", "192", "--loudness", "-16"
    )


def test_a_movement_word_in_the_window_matches_the_command_line() -> None:
    settings = GuiSettings()
    settings.change(intensity=MOVEMENT.value_for("Gentle"))
    assert gui_model.config_for(settings) == _config("--movement", "gentle")


# ------------------------------------------------------------------ Customize


A, B, C = Path("a.mp3"), Path("b.mp3"), Path("c.mp3")


def _snapshot(settings: GuiSettings) -> GuiSettings:
    return copy.deepcopy(settings)


def test_nothing_changed_is_falsy() -> None:
    assert not Changes()
    assert Changes(style="groove")
    assert Changes(sound={"intensity": 0.5})
    assert Changes(texts={"bpm_text": "120"})
    assert Changes(files={"keep_cover": False})


def test_a_draft_never_changes_the_real_settings() -> None:
    settings = GuiSettings()
    gui_model.set_sound_settings(settings, [A], STYLES, intensity=0.5)
    before = _snapshot(settings)
    changes = Changes(
        style="groove",
        sound={"ambience": 0.4},
        texts={"bpm_text": "120"},
        files={"output_format": "flac", "keep_cover": False},
    )

    for songs in ([], [A], [A, B]):
        trial = gui_model.draft(settings, songs, STYLES, changes)
        assert trial is not settings
        assert settings == before  # Cancel: nothing happened
    trial = gui_model.draft(settings, [A], STYLES, changes)
    assert trial.song_styles[A] == "groove" and trial.song_sound[A]["ambience"] == 0.4
    assert A not in settings.song_styles


def test_customize_applies_what_the_draft_showed() -> None:
    settings = GuiSettings()
    changes = Changes(style="groove", files={"output_format": "flac"})
    trial = gui_model.draft(settings, [A], STYLES, changes)

    gui_model.customize(settings, [A], STYLES, changes)
    assert settings == trial
    assert gui_model.is_custom(settings, A) and not gui_model.is_custom(settings, B)
    config = gui_model.song_config(settings, A, STYLES)
    assert config.path == "figure8" and config.output_format == "flac"


def test_customizing_the_defaults_touches_no_song() -> None:
    settings = GuiSettings()
    gui_model.set_file_settings(settings, [A], output_format="wav")

    gui_model.customize(
        settings,
        [],
        STYLES,
        Changes(style="smooth", sound={"speakers": True}, files={"keep_cover": False}),
    )
    assert settings.style == "smooth" and settings.speakers
    assert settings.keep_cover is False
    assert settings.song_files == {A: {"output_format": "wav"}}
    assert gui_model.song_config(settings, A, STYLES).output_format == "wav"


def test_a_bulk_edit_only_changes_what_was_touched() -> None:
    settings = GuiSettings()
    gui_model.set_sound_settings(settings, [A], STYLES, intensity=0.5)
    gui_model.set_sound_settings(settings, [B], STYLES, ambience=0.4)
    gui_model.set_file_settings(settings, [A], output_format="flac")
    gui_model.set_file_settings(settings, [B], bitrate=192)

    gui_model.customize(
        settings,
        [A, B, C],
        STYLES,
        Changes(sound={"elevation": 0.3}, files={"keep_cover": False}),
    )
    assert settings.song_sound[A] == {"intensity": 0.5, "elevation": 0.3}
    assert settings.song_sound[B] == {"ambience": 0.4, "elevation": 0.3}
    assert settings.song_sound[C] == {"elevation": 0.3}
    assert settings.song_files[A] == {"output_format": "flac", "keep_cover": False}
    assert settings.song_files[B] == {"bitrate": 192, "keep_cover": False}
    assert settings.song_files[C] == {"keep_cover": False}
    assert not settings.song_styles


def test_a_value_equal_to_the_default_is_no_setting_of_its_own() -> None:
    settings = GuiSettings()
    studio = PRESETS["studio"].config
    gui_model.customize(
        settings,
        [A],
        STYLES,
        Changes(
            style=settings.style,
            sound={"intensity": studio.intensity},
            files={"output_format": "mp3"},
        ),
    )
    assert not gui_model.is_custom(settings, A)


def test_choosing_the_default_style_for_a_song_follows_the_default_again() -> None:
    settings = GuiSettings()
    gui_model.customize(settings, [A], STYLES, Changes(style="groove"))
    assert settings.song_styles == {A: "groove"}
    gui_model.customize(settings, [A], STYLES, Changes(style="studio"))
    assert not settings.song_styles


@pytest.mark.parametrize(
    ("songs", "changes"),
    [
        ([A], Changes(sound={"intensity": 5.0})),
        ([], Changes(sound={"intensity": 5.0})),
        ([A, B], Changes(texts={"bpm_text": "fast"})),
        ([], Changes(texts={"bpm_text": "fast"})),
        ([A], Changes(texts={"speed_curve_text": "0=nonsense"})),
        ([A], Changes(style="no such style")),
        ([], Changes(style="no such style")),
        ([A], Changes(files={"trim_start": "1:00", "trim_end": "0:30"})),
        ([], Changes(files={"trim_start": "1:00", "trim_end": "0:30"})),
    ],
)
def test_an_unusable_value_changes_nothing(songs, changes: Changes) -> None:
    settings = GuiSettings()
    gui_model.set_sound_settings(settings, [A], STYLES, intensity=0.5)
    before = _snapshot(settings)

    with pytest.raises(InputValidationError):
        gui_model.customize(settings, songs, STYLES, changes)
    assert settings == before


def test_reset_to_default_forgets_everything_a_song_had() -> None:
    settings = GuiSettings()
    gui_model.customize(
        settings,
        [A, B],
        STYLES,
        Changes(style="groove", sound={"ambience": 0.4}, files={"bitrate": 192}),
    )
    gui_model.set_file_settings(settings, [C], keep_cover=False)
    default_a = gui_model.song_config(GuiSettings(), A, STYLES)

    assert gui_model.reset_songs(settings, [A, B, Path("never.mp3")]) == 2
    for song in (A, B):
        assert not gui_model.is_custom(settings, song)
        assert gui_model.song_config(settings, song, STYLES) == default_a
    # Other songs keep theirs
    assert gui_model.is_custom(settings, C)
    assert gui_model.reset_songs(settings, [A]) == 0


def test_a_songs_own_style_is_sound_only() -> None:
    settings = GuiSettings()
    settings.change(output_format="flac")
    gui_model.customize(settings, [A], STYLES, Changes(style="sky"))

    config = gui_model.song_config(settings, A, STYLES)
    assert config.output_format == "flac"
    assert dataclasses.replace(config, **output_of(PRESETS["sky"].config)) == (
        PRESETS["sky"].config
    )
