# Developed by ::> Gehan Fernando
"""Movement, Speed and Space: the words, the exact values, and the command line."""

from dataclasses import replace
from pathlib import Path

import pytest

from src import cli
from src.core.errors import InputValidationError
from src.core.presets import PRESETS, RECOMMENDED_PRESET
from src.core.sound_levels import LEVELS, MOVEMENT, SPACE, SPEED
from src.per_song import parse_line

STUDIO = PRESETS[RECOMMENDED_PRESET].config


@pytest.fixture(autouse=True)
def _pretend_songs_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Made-up song names are fine; nothing is ever converted."""
    monkeypatch.setattr(cli, "resolve_input", lambda path: path)
    monkeypatch.setattr(cli, "_peek_source", lambda path: None)
    monkeypatch.setattr(
        cli, "convert", lambda **_kwargs: pytest.fail("nothing should convert")
    )


def _config(*options: str):
    return cli.resolve_config(cli.create_parser().parse_args(["a.mp3", *options]))


def test_every_level_names_the_setting_it_changes() -> None:
    assert [level.key for level in LEVELS] == ["movement", "speed", "space"]
    assert [level.field for level in LEVELS] == [
        "intensity",
        "rotation_seconds",
        "ambience",
    ]
    for level in LEVELS:
        assert len(level.choices) == 3
        assert hasattr(STUDIO, level.field)


def test_the_middle_words_are_exactly_studio() -> None:
    assert MOVEMENT.word_for(STUDIO.intensity) == "Balanced"
    assert SPEED.word_for(STUDIO.rotation_seconds) == "Normal"
    assert SPACE.word_for(STUDIO.ambience) == "Natural"


@pytest.mark.parametrize(
    ("level", "word", "value"),
    [
        (MOVEMENT, "Gentle", 0.65),
        (MOVEMENT, "Balanced", 0.80),
        (MOVEMENT, "Strong", 0.95),
        (SPEED, "Slow", 12.0),
        (SPEED, "Normal", 8.0),
        (SPEED, "Fast", 5.0),
        (SPACE, "Dry", 0.10),
        (SPACE, "Natural", 0.25),
        (SPACE, "Spacious", 0.45),
    ],
)
def test_each_word_is_one_exact_value_both_ways(level, word, value) -> None:
    assert level.value_for(word) == value
    assert level.value_for(f"  {word.upper()} ") == value
    assert level.word_for(value) == word
    # Tiny floating-point noise still finds the word
    assert level.word_for(value + 1e-12) == word


def test_an_in_between_value_has_no_word_but_is_described() -> None:
    assert MOVEMENT.word_for(0.7) is None
    assert MOVEMENT.between(0.7) == "between Gentle and Balanced"
    # Speed's words are not in value order, yet 'between' still sorts them
    assert SPEED.between(10.0) == "between Normal and Slow"
    assert SPEED.between(6.0) == "between Fast and Normal"
    assert SPEED.between(20.0) == "beyond Slow"
    assert SPEED.between(3.0) == "beyond Fast"
    assert SPACE.between(0.0) == "beyond Dry"


def test_an_unknown_word_is_refused_with_the_choices() -> None:
    with pytest.raises(InputValidationError, match="gentle, balanced, strong"):
        MOVEMENT.value_for("wild")


def test_every_word_value_is_a_valid_setting() -> None:
    for level in LEVELS:
        for value in level.choices.values():
            config = replace(STUDIO, **{level.field: value})  # type: ignore[arg-type]
            config.validate()


# ------------------------------------------------------------------ command line


@pytest.mark.parametrize(
    ("friendly", "exact"),
    [
        (["--movement", "gentle"], ["--intensity", "0.65"]),
        (["--movement", "STRONG"], ["--intensity", "0.95"]),
        (["--speed", "slow"], ["--rotation-seconds", "12"]),
        (["--speed", "fast"], ["--rotation-seconds", "5"]),
        (["--space", "dry"], ["--ambience", "0.1"]),
        (["--space", "spacious"], ["--ambience", "0.45"]),
    ],
)
def test_a_word_on_the_command_line_equals_its_exact_value(friendly, exact) -> None:
    assert _config(*friendly) == _config(*exact)
    assert _config("--style", "groove", *friendly) == _config(
        "--style", "groove", *exact
    )


def test_words_change_only_their_own_setting() -> None:
    config = _config("--movement", "gentle", "--speed", "slow", "--space", "dry")
    assert (config.intensity, config.rotation_seconds, config.ambience) == (
        0.65,
        12.0,
        0.10,
    )
    assert config.path == STUDIO.path and config.bass_hz == STUDIO.bass_hz
    assert config.output_format == STUDIO.output_format


@pytest.mark.parametrize(
    "both",
    [
        ["--movement", "gentle", "--intensity", "0.5"],
        ["--speed", "slow", "--rotation-seconds", "9"],
        ["--space", "dry", "--ambience", "0.3"],
    ],
)
def test_a_word_and_an_exact_value_for_the_same_setting_is_refused(
    both: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(InputValidationError, match="not both"):
        _config(*both)
    assert cli.main(["a.mp3", *both]) == 1
    assert "not both" in caplog.text


def test_a_word_with_an_exact_value_for_another_setting_is_fine() -> None:
    config = _config("--movement", "gentle", "--ambience", "0.3")
    assert config.intensity == 0.65 and config.ambience == 0.3


def test_an_unknown_word_on_the_command_line_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as stopped:
        cli.create_parser().parse_args(["a.mp3", "--movement", "wild"])
    assert stopped.value.code == 2
    assert "gentle, balanced, strong" in capsys.readouterr().err


def test_a_per_song_line_takes_words_and_refuses_both(tmp_path: Path) -> None:
    rule = parse_line('"Rain.mp3" --movement gentle --space spacious', 3, tmp_path)
    assert rule is not None
    assert rule.changes == {"intensity": 0.65, "ambience": 0.45}

    with pytest.raises(InputValidationError, match=r"Line 4 .*not both"):
        parse_line('"Rain.mp3" --speed slow --rotation-seconds 9', 4, tmp_path)


def test_typing_a_word_counts_as_choosing_something() -> None:
    args = cli.create_parser().parse_args(["a.mp3", "--speed", "slow"])
    assert not cli.used_only_defaults(args)
    assert cli.used_only_defaults(cli.create_parser().parse_args(["a.mp3"]))
