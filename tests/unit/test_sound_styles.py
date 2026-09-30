# Developed by ::> Gehan Fernando
"""Every built-in sound style: present, valid, safe, and the same everywhere.

The window, the command line, previews and final files all read a style from
the one table in core/presets.py; these tests pin the values an audio review
settled on, so a change to any of them is a deliberate one.
"""

import dataclasses
from pathlib import Path

import pytest

from src import cli, gui_model
from src.core.presets import PRESETS, STANDARD_OUTPUT, output_of
from src.core.settings import LOSSLESS_FORMATS
from src.core.style_guide import GUIDES
from src.effects.graph import GraphInputs, Source, build_graph
from src.effects.levels import output_sample_rate
from src.gui_model import GuiSettings, song_config
from src.previews import preview_config

STYLE_NAMES = sorted(PRESETS)

# (seconds per turn, movement, room) each built-in style was reviewed at
REVIEWED = {
    "studio": (8.0, 0.80, 0.25),
    "gentle": (8.0, 0.65, 0.25),
    "front": (16.0, 0.40, 0.25),
    "classic": (8.0, 0.85, 0.30),
    "groove": (12.0, 0.85, 0.25),
    "smooth": (12.0, 0.75, 0.20),
    "strong": (8.0, 0.95, 0.35),
    "spacious": (10.0, 0.80, 0.45),
    "sky": (12.0, 0.80, 0.45),
    "voice": (16.0, 0.60, 0.0),
    "whirlwind": (3.0, 0.95, 0.25),
    "speakers": (8.0, 0.55, 0.20),
    "retro": (8.0, 0.85, 0.30),
}

_INPUTS = GraphInputs(sources=(Source(0, (1, 2)),), room_input=3)


def test_every_reviewed_style_exists_and_nothing_else_is_built_in() -> None:
    assert set(PRESETS) == set(REVIEWED)
    # Each one has a plain-word description for the style chooser
    assert set(GUIDES) == set(PRESETS)


@pytest.mark.parametrize("name", STYLE_NAMES)
def test_each_style_has_its_reviewed_values(name: str) -> None:
    config = PRESETS[name].config
    reviewed = (config.rotation_seconds, config.intensity, config.ambience)
    assert reviewed == pytest.approx(REVIEWED[name])


@pytest.mark.parametrize("name", STYLE_NAMES)
def test_each_style_is_valid_and_within_safe_limits(name: str) -> None:
    config = PRESETS[name].config
    config.validate()
    # Never the full-strength movement or a wash of room that blurs the song
    assert 0.4 <= config.intensity <= 0.95
    assert 0.0 <= config.ambience <= 0.5
    # Faster than 3 s a turn is dizzying; slower than 16 s barely moves
    assert 3.0 <= config.rotation_seconds <= 16.0
    # Every style is saved the standard way: -14 LUFS and peaks under -1 dBTP
    assert output_of(config) == STANDARD_OUTPUT
    assert config.loudness_target == -14.0


@pytest.mark.parametrize("name", STYLE_NAMES)
def test_each_styles_other_settings_are_safe(name: str) -> None:
    config = PRESETS[name].config
    assert config.engine in ("3d", "pan")
    assert config.path in ("circle", "figure8", "wander", "arc")
    # Bass stays in the middle below 80-200 Hz; only Retro lets it move (0)
    assert config.bass_hz == 0 or 80 <= config.bass_hz <= 200
    assert (config.bass_hz == 0) == (name == "retro")
    assert 0.0 <= config.elevation <= 0.8
    assert 0.0 <= config.fade_seconds <= 4.0


@pytest.mark.parametrize("name", STYLE_NAMES)
def test_each_style_builds_the_same_processing_every_time(name: str) -> None:
    config = PRESETS[name].config
    first = build_graph(config, _INPUTS, sample_rate=44100, source_rate=44100)
    again = build_graph(
        dataclasses.replace(config), _INPUTS, sample_rate=44100, source_rate=44100
    )
    assert first == again
    # The final stage always limits the peaks
    assert "alimiter" in first


@pytest.mark.parametrize("name", STYLE_NAMES)
def test_the_window_and_the_command_line_make_the_same_style(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "resolve_input", lambda path: path)
    monkeypatch.setattr(cli, "_peek_source", lambda path: None)
    settings = GuiSettings()
    settings.apply_style(PRESETS[name])
    args = cli.create_parser().parse_args(["a.mp3", "--style", name])

    assert gui_model.config_for(settings) == cli.resolve_config(args)


@pytest.mark.parametrize("name", STYLE_NAMES)
@pytest.mark.parametrize("output_format", ["mp3", "flac", "opus"])
def test_a_preview_uses_the_final_files_sound_and_only_differs_in_format(
    name: str, output_format: str
) -> None:
    final = PRESETS[name].config
    final = dataclasses.replace(final, output_format=output_format)
    preview = preview_config(final)

    assert preview.output_format == "wav"
    assert dataclasses.replace(preview, output_format=output_format) == final
    # Rendered as the real format, the WAV preview gets the final file's processing
    rate = output_sample_rate(output_format, 44100)
    lossless = output_format in LOSSLESS_FORMATS
    as_final = build_graph(final, _INPUTS, sample_rate=rate, source_rate=44100)
    as_preview = build_graph(
        preview, _INPUTS, sample_rate=rate, source_rate=44100, lossless=lossless
    )
    assert as_preview == as_final


@pytest.mark.parametrize("name", STYLE_NAMES)
def test_one_songs_style_is_the_same_in_the_window_and_on_the_command_line(
    name: str, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(cli, "resolve_input", lambda path: path)
    monkeypatch.setattr(cli, "_peek_source", lambda path: None)
    song = Path("music/a.mp3")
    rules = tmp_path / "songs.txt"
    rules.write_text(f'"a.mp3" --style {name}\n', "utf-8")
    args = cli.create_parser().parse_args(["music", "--per-song", str(rules)])
    settings = GuiSettings()
    settings.song_styles[song] = name

    command_line = cli.song_setup(song, cli.plan_from_args(args))[0]
    assert song_config(settings, song, PRESETS) == command_line


def test_front_never_goes_behind_the_head_and_keeps_the_bass_centred() -> None:
    front = PRESETS["front"].config
    assert front.path == "arc" and front.engine == "3d"
    assert front.bass_hz > 0 and front.elevation == 0
    # The shallowest music style: gentler than Gentle, Voice and Speakers
    others = [c.config.intensity for n, c in PRESETS.items() if n != "front"]
    assert front.intensity < min(others)
