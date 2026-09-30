# Developed by ::> Gehan Fernando
"""A song's own settings on top of the defaults: rules the window and CLI share."""

import pytest

from src import EffectConfig, InputValidationError
from src.core.presets import PRESETS
from src.core.types import Trim
from src.pipeline import ConvertOptions
from src.song_settings import (
    SPEAKERS,
    needs_singer,
    parse_trim,
    singer_songs,
    song_convert_options,
    song_effect,
)

DEFAULT = PRESETS["studio"].config
SMOOTH = PRESETS["smooth"].config


def test_a_song_without_changes_gets_the_default() -> None:
    assert song_effect(DEFAULT) == DEFAULT


def test_an_own_style_keeps_its_sound_and_the_default_file() -> None:
    config = song_effect(DEFAULT, style=SMOOTH)

    assert config.intensity == SMOOTH.intensity
    assert config.rotation_seconds == SMOOTH.rotation_seconds
    assert config.output_format == DEFAULT.output_format
    assert config.loudness_target == DEFAULT.loudness_target


def test_own_changes_apply_to_sound_and_file() -> None:
    config = song_effect(
        DEFAULT,
        changes={"intensity": 0.5, "vocals": "center", "output_format": "flac"},
    )
    assert (config.intensity, config.vocals, config.output_format) == (
        0.5,
        "center",
        "flac",
    )
    assert needs_singer(config) and not needs_singer(DEFAULT)
    assert singer_songs([("a", config), ("b", DEFAULT)]) == ["a"]


def test_speakers_follow_the_default_only_for_default_songs() -> None:
    safe = song_effect(DEFAULT, default_speakers=True)
    assert safe.engine == "pan"
    # A song with its own style is made exactly as that style says
    assert song_effect(DEFAULT, default_speakers=True, style=SMOOTH).engine == "3d"
    # ...unless it has the switch of its own
    own = song_effect(DEFAULT, default_speakers=True, changes={SPEAKERS: False})
    assert own.engine == "3d"
    assert song_effect(DEFAULT, changes={SPEAKERS: True}).engine == "pan"


def test_unusable_or_unknown_settings_are_refused() -> None:
    with pytest.raises(InputValidationError):
        song_effect(DEFAULT, changes={"intensity": 3.0})
    with pytest.raises(ValueError, match="Not a song setting"):
        song_effect(DEFAULT, changes={"colour": "red"})


def test_trims_accept_text_and_seconds() -> None:
    assert parse_trim("1:00", 90) == Trim(60.0, 90.0)
    assert parse_trim("", None) is None
    assert parse_trim(None, "0:30") == Trim(None, 30.0)
    with pytest.raises(InputValidationError, match="no sound"):
        parse_trim("1:00", "0:30")


def test_a_songs_file_treatment() -> None:
    default = ConvertOptions(trim=None, keep_cover=True, tag_title=True)

    assert song_convert_options(default, {"intensity": 0.4}) is None
    own = song_convert_options(
        default, {"keep_cover": False, "trim_start": "0:10", "trim_end": 40}
    )
    assert own is not None
    assert not own.keep_cover and own.tag_title and own.trim == Trim(10.0, 40.0)


def test_every_song_is_validated() -> None:
    config = song_effect(EffectConfig(), changes={"bitrate": 320})
    assert config.bitrate == 320
