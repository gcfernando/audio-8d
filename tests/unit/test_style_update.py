# Developed by ::> Gehan Fernando
"""Changing a saved style in place: new values, a new name, or both, kept for good.

Every change is checked by the same rules as a new style, and a change that
fails a check leaves the styles file exactly as it was.
"""

# pytest hands fixtures to tests by name, which pylint sees as shadowing
# pylint: disable=redefined-outer-name

import dataclasses
from pathlib import Path

import pytest

from src.core.errors import InputValidationError
from src.core.presets import PRESETS, STANDARD_OUTPUT
from src.core.settings import OUTPUT_FIELDS
from src.core.user_presets import (
    all_presets,
    load_user_presets,
    parse_toml,
    save_user_preset,
    update_user_preset,
)
from src.style_creator import style_check

STUDIO = PRESETS["studio"].config


@pytest.fixture
def styles(tmp_path: Path) -> Path:
    """A styles file with three saved styles, the middle one based on groove."""
    file = tmp_path / "presets.toml"
    save_user_preset("First", STUDIO, path=file)
    save_user_preset(
        "Sunset Drive",
        dataclasses.replace(PRESETS["groove"].config, ambience=0.3),
        based_on="groove",
        summary="Evening drives",
        path=file,
    )
    save_user_preset("Last", STUDIO, path=file)
    return file


def _tables(file: Path) -> dict:
    """The styles file, read back as tables."""
    return parse_toml(file.read_text(encoding="utf-8"))


def test_an_update_keeps_name_base_and_place(styles: Path) -> None:
    config = dataclasses.replace(PRESETS["groove"].config, intensity=0.6)

    name = update_user_preset("sunset drive", config, path=styles)

    assert name == "Sunset Drive"
    tables = _tables(styles)
    assert list(tables) == ["First", "Sunset Drive", "Last"]
    saved = tables["Sunset Drive"]
    assert saved["based_on"] == "groove" and saved["summary"] == "Evening drives"
    assert saved["intensity"] == 0.6
    # The earlier ambience change is gone: the style is exactly the new values
    assert "ambience" not in saved
    # A restart reads the new values
    assert load_user_presets(styles)["Sunset Drive"].config.intensity == 0.6


def test_an_update_can_rename_in_the_same_step(styles: Path) -> None:
    config = dataclasses.replace(PRESETS["groove"].config, rotation_seconds=12.0)

    name = update_user_preset(
        "Sunset Drive", config, new_name="night drive", summary="  Late  ", path=styles
    )

    assert name == "Night Drive"
    assert list(_tables(styles)) == ["First", "Night Drive", "Last"]
    reloaded = all_presets(styles)
    assert "Sunset Drive" not in reloaded
    assert reloaded["Night Drive"].config.rotation_seconds == 12.0
    assert reloaded["Night Drive"].summary == "Late"


def test_a_style_can_keep_its_own_name_in_another_case(styles: Path) -> None:
    assert update_user_preset("First", STUDIO, new_name="first", path=styles) == (
        "First"
    )


def test_other_characters_join_words_as_for_new_styles(styles: Path) -> None:
    # The same rule as a new style: symbols only join the words
    assert update_user_preset("First", STUDIO, new_name="Bad/Name!", path=styles) == (
        "BadName"
    )


def test_an_empty_description_removes_it(styles: Path) -> None:
    update_user_preset("Sunset Drive", STUDIO, summary="", path=styles)
    assert "summary" not in _tables(styles)["Sunset Drive"]


def test_file_settings_are_never_stored(styles: Path) -> None:
    config = dataclasses.replace(
        STUDIO,
        output_format="flac",
        loudness_target=None,
        limiter_ceiling=0.89,
        quality=5,
        bitrate=None,
        exact_loudness=True,
        intensity=0.7,
    )
    update_user_preset("First", config, path=styles)

    saved = _tables(styles)["First"]
    assert not set(saved) & set(OUTPUT_FIELDS)
    loaded = load_user_presets(styles)["First"].config
    assert {key: getattr(loaded, key) for key in STANDARD_OUTPUT} == STANDARD_OUTPUT


@pytest.mark.parametrize(
    ("kwargs", "words"),
    [
        ({"new_name": "   "}, "Type a name"),
        ({"new_name": "last"}, "already have"),
        ({"new_name": "L A S T"}, "already have"),
        ({"new_name": "Studio"}, "built-in"),
        ({"new_name": "hifi"}, "built-in"),
        ({"new_name": "9 Lives"}, "start with a letter"),
        ({"new_name": "!!/?"}, "Type a name"),
        ({"new_name": "Very Long " * 6}, "too long"),
        ({"summary": "x" * 200}, "too long"),
    ],
)
def test_a_failed_check_leaves_the_file_untouched(
    styles: Path, kwargs: dict, words: str
) -> None:
    before = styles.read_bytes()

    with pytest.raises(InputValidationError, match=words):
        update_user_preset("First", STUDIO, path=styles, **kwargs)
    assert styles.read_bytes() == before


def test_invalid_settings_leave_the_file_untouched(styles: Path) -> None:
    before = styles.read_bytes()
    # dataclasses.replace never checks, so the values reach the save unchecked
    broken = dataclasses.replace(STUDIO, intensity=2.0)

    with pytest.raises(InputValidationError, match="intensity"):
        update_user_preset("First", broken, path=styles)
    assert styles.read_bytes() == before


@pytest.mark.parametrize("name", ["Nobody", "studio", "Front"])
def test_only_saved_styles_can_be_changed(styles: Path, name: str) -> None:
    before = styles.read_bytes()

    with pytest.raises(InputValidationError, match="no saved style"):
        update_user_preset(name, STUDIO, path=styles)
    assert styles.read_bytes() == before


def test_an_older_based_on_name_is_kept(tmp_path: Path) -> None:
    file = tmp_path / "presets.toml"
    file.write_text('[Old]\nbased_on = "hifi"\nintensity = 0.7\n', encoding="utf-8")

    update_user_preset("Old", dataclasses.replace(STUDIO, intensity=0.9), path=file)

    saved = _tables(file)["Old"]
    assert saved["based_on"] == "hifi"
    assert load_user_presets(file)["Old"].config.intensity == 0.9


# ------------------------------------------------------------------ quality check


def test_file_settings_never_raise_style_advice() -> None:
    config = dataclasses.replace(
        STUDIO,
        output_format="mp3",
        bitrate=96,
        loudness_target=None,
        limiter_ceiling=0.99,
    )
    notes = style_check(config, "why")

    assert not notes


def test_the_front_style_passes_the_quality_check() -> None:
    notes = style_check(PRESETS["front"].config, "Stays in front")
    assert [note for note in notes if note.level != "tip"] == []


def test_really_weak_movement_is_still_advised() -> None:
    notes = style_check(dataclasses.replace(STUDIO, intensity=0.2), "why")
    assert [note.fix.get("intensity") for note in notes] == [0.8]
