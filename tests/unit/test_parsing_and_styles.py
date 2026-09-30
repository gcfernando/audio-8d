# Developed by ::> Gehan Fernando
"""Checks times, keyframes, song picking, saved styles and speaker safety."""

import dataclasses
from pathlib import Path

import pytest

from src import PRESETS, EffectConfig, InputValidationError
from src.core.parsing import (
    format_keyframes,
    format_time,
    parse_keyframes,
    parse_selection,
    parse_time,
)
from src.core.presets import with_standard_output
from src.core.settings import speaker_safe
from src.core.user_presets import (
    all_presets,
    check_style_name,
    delete_user_preset,
    dump_toml,
    duplicate_user_preset,
    find_style,
    load_user_presets,
    parse_toml,
    pascal_case,
    rename_user_preset,
    save_user_preset,
)


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("90", 90.0), ("1:30", 90.0), ("1:02:03", 3723.0), ("0:05.5", 5.5)],
)
def test_times_are_read_like_a_music_player(text: str, seconds: float) -> None:
    assert parse_time(text) == seconds


@pytest.mark.parametrize("text", ["", "abc", "1:75", "-5", "1:2:3:4"])
def test_bad_times_are_refused(text: str) -> None:
    with pytest.raises(InputValidationError):
        parse_time(text)


def test_times_are_shown_like_a_music_player() -> None:
    assert format_time(90) == "1:30"
    assert format_time(3723) == "1:02:03"


def test_keyframes_round_trip() -> None:
    frames = parse_keyframes("0=10, 1:00=6; 2:30=10")

    assert frames == ((0.0, 10.0), (60.0, 6.0), (150.0, 10.0))
    assert parse_keyframes(format_keyframes(frames)) == frames


@pytest.mark.parametrize(
    ("text", "saved"),
    [
        ("0=8, 0:10.6=4", "0:00=8, 0:10.6=4"),
        ("1:05.25=6", "1:05.25=6"),
        ("59.999=3", "0:59.999=3"),
        ("1:02:03.5=2", "1:02:03.5=2"),
    ],
)
def test_keyframes_keep_parts_of_a_second(text: str, saved: str) -> None:
    frames = parse_keyframes(text)

    assert format_keyframes(frames) == saved
    assert parse_keyframes(format_keyframes(frames)) == frames
    # Shown times are still whole seconds, like a music player
    assert format_time(10.6) == "0:11"


def test_a_saved_style_keeps_fractional_curve_times(tmp_path: Path) -> None:
    frames = parse_keyframes("0=8, 0:10.6=4")
    config = dataclasses.replace(PRESETS["studio"].config, speed_curve=frames)
    file = tmp_path / "presets.toml"

    save_user_preset("Curvy", config, based_on="studio", path=file)

    assert load_user_presets(file)["Curvy"].config.speed_curve == frames


@pytest.mark.parametrize("text", ["fast", "1:00", "0=abc", " , "])
def test_bad_keyframes_are_refused(text: str) -> None:
    with pytest.raises(InputValidationError):
        parse_keyframes(text)


def test_keyframes_must_go_forwards_and_stay_in_range() -> None:
    with pytest.raises(InputValidationError):
        EffectConfig(speed_curve=((60.0, 8.0), (0.0, 8.0))).validate()
    with pytest.raises(InputValidationError):
        EffectConfig(intensity_curve=((0.0, 1.5),)).validate()


def test_song_selection() -> None:
    assert parse_selection("", 4) == [0, 1, 2, 3]
    assert parse_selection("all", 4) == [0, 1, 2, 3]
    assert parse_selection("1,3-4", 4) == [0, 2, 3]
    assert parse_selection("2 2 1", 4) == [0, 1]
    for bad in ("0", "5", "2-1", "x"):
        with pytest.raises(InputValidationError):
            parse_selection(bad, 4)


def test_toml_subset_round_trips() -> None:
    tables = {"mine": {"based_on": "studio", "intensity": 0.9, "beat_sync": True}}
    text = dump_toml(tables)

    assert parse_toml(text) == tables
    assert parse_toml('[a]\nsummary = "has # inside" # comment\n') == {
        "a": {"summary": "has # inside"}
    }
    with pytest.raises(InputValidationError):
        parse_toml("key = 1\n")


def test_saved_style_only_stores_differences(tmp_path: Path) -> None:
    file = tmp_path / "presets.toml"
    config = PRESETS["studio"].config.__class__(
        **{
            **{
                name: getattr(PRESETS["studio"].config, name)
                for name in PRESETS["studio"].config.__dataclass_fields__
            },
            "intensity": 0.95,
            "speed_curve": ((0.0, 10.0), (60.0, 6.0)),
            "loudness_target": None,
        }
    )
    name = save_user_preset(
        "party", config, based_on="studio", summary="loud", path=file
    )
    text = file.read_text(encoding="utf-8")

    assert "intensity = 0.95" in text
    # A style is only the sound: the file settings are never stored in it
    assert "loudness_target" not in text
    assert "bitrate" not in text
    assert name == "Party"
    loaded = load_user_presets(file)["Party"]
    # The sound comes back exactly; the file is saved the recommended way
    assert loaded.config == with_standard_output(config)
    assert loaded.custom and loaded.summary == "loud"


def test_saved_styles_join_the_built_in_ones() -> None:
    save_user_preset("chill_2", EffectConfig(ambience=0.5))
    presets = all_presets()

    assert list(presets)[: len(PRESETS)] == list(PRESETS)
    assert presets["Chill2"].config.ambience == 0.5


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("studio", "built-in"),
        ("STUDIO", "built-in"),
        ("", "Type a name"),
        ("  --  ", "Type a name"),
        ("2fast", "start with a letter"),
        ("x" * 41, "too long"),
    ],
)
def test_bad_style_names_are_refused(name: str, reason: str, tmp_path: Path) -> None:
    file = tmp_path / "p.toml"
    with pytest.raises(InputValidationError, match=reason):
        save_user_preset(name, EffectConfig(), path=file)
    assert not file.exists()


@pytest.mark.parametrize(
    ("typed", "saved"),
    [
        ("Customer Order", "Customer Order"),
        ("CustomerOrder", "CustomerOrder"),
        ("customerOrder", "CustomerOrder"),
        ("customer Order", "Customer Order"),
        ("customer_order", "CustomerOrder"),
        ("customer-order", "CustomerOrder"),
        ("customer order", "Customer Order"),
        ("UserProfileService", "UserProfileService"),
        ("party mix 2", "Party Mix 2"),
        ("Example Custom Name", "Example Custom Name"),
        ("  example   custom	name ", "Example Custom Name"),
        ("ExampleCustomName", "ExampleCustomName"),
    ],
)
def test_style_names_become_pascal_case(typed: str, saved: str) -> None:
    assert pascal_case(typed) == saved
    assert check_style_name(typed, []) == saved


def test_a_style_name_is_never_used_twice(tmp_path: Path) -> None:
    file = tmp_path / "p.toml"
    save_user_preset("PartyMix", EffectConfig(intensity=0.9), path=file)
    before = file.read_text(encoding="utf-8")

    for clash in ("PartyMix", "party mix", "PARTYMIX", "party-mix"):
        with pytest.raises(InputValidationError, match="already have a style"):
            save_user_preset(clash, EffectConfig(intensity=0.5), path=file)
    # Nothing was replaced, merged or renamed
    assert file.read_text(encoding="utf-8") == before


def test_styles_can_be_renamed_and_duplicated_under_free_names(
    tmp_path: Path,
) -> None:
    file = tmp_path / "p.toml"
    save_user_preset("PartyMix", EffectConfig(intensity=0.9), path=file)
    save_user_preset("NightDrive", EffectConfig(intensity=0.6), path=file)

    assert rename_user_preset("partymix", "big party", path=file) == "Big Party"
    # A new letter case of its own name is fine; another style's name is not
    assert rename_user_preset("Big Party", "BIG-party", path=file) == "BigParty"
    with pytest.raises(InputValidationError, match="already have a style"):
        rename_user_preset("BigParty", "night drive", path=file)
    assert duplicate_user_preset("NightDrive", "night drive 2", path=file) == (
        "Night Drive 2"
    )
    with pytest.raises(InputValidationError, match="already have a style"):
        duplicate_user_preset("NightDrive", "BigParty", path=file)
    with pytest.raises(InputValidationError, match="no saved style"):
        rename_user_preset("Missing", "Other", path=file)

    styles = load_user_presets(file)
    assert list(styles) == ["BigParty", "NightDrive", "Night Drive 2"]
    assert styles["Night Drive 2"].config == styles["NightDrive"].config


def test_a_name_with_spaces_is_stored_safely_and_found_however_typed(
    tmp_path: Path,
) -> None:
    file = tmp_path / "p.toml"
    name = save_user_preset(
        "example custom name", EffectConfig(ambience=0.4), path=file
    )

    assert name == "Example Custom Name"
    assert '["Example Custom Name"]' in file.read_text(encoding="utf-8")
    styles = load_user_presets(file)
    assert styles["Example Custom Name"].config.ambience == 0.4
    for typed in ("example custom name", "ExampleCustomName", "EXAMPLE-custom name"):
        assert find_style(typed, styles) == "Example Custom Name"
    # Joined or spaced, it's the same name, so it can't be saved twice
    with pytest.raises(InputValidationError, match="already have a style"):
        save_user_preset("ExampleCustomName", EffectConfig(), path=file)


def test_styles_saved_before_pascal_case_names_still_load(tmp_path: Path) -> None:
    file = tmp_path / "p.toml"
    file.write_text('[party-mix]\nbased_on = "groove"\n', encoding="utf-8")

    styles = load_user_presets(file)
    assert styles["party-mix"].config == PRESETS["groove"].config
    assert find_style("PARTY-MIX", styles) == "party-mix"
    # Its old name still counts as taken, whatever way it's written
    with pytest.raises(InputValidationError, match="already have a style"):
        save_user_preset("party mix", EffectConfig(), path=file)
    assert rename_user_preset("party-mix", "PartyMix", path=file) == "PartyMix"


def test_a_description_stays_on_one_line(tmp_path: Path) -> None:
    file = tmp_path / "p.toml"
    save_user_preset("Lines", EffectConfig(), summary="one\nline\n[evil]", path=file)

    assert load_user_presets(file)["Lines"].summary == "one line [evil]"
    with pytest.raises(InputValidationError, match="too long"):
        save_user_preset("Long", EffectConfig(), summary="x" * 200, path=file)


def test_broken_style_file_is_explained(tmp_path: Path) -> None:
    file = tmp_path / "presets.toml"
    file.write_text('[mine]\nbased_on = "nope"\n', encoding="utf-8")
    with pytest.raises(InputValidationError, match="does not exist"):
        load_user_presets(file)
    file.write_text("[mine]\nwobble = 3\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="unknown setting"):
        load_user_presets(file)


def test_speaker_safe_softens_any_style() -> None:
    safe = speaker_safe(
        EffectConfig(
            intensity=0.95, elevation=0.8, bass_hz=0, intensity_curve=((0, 1.0),)
        )
    )

    assert safe.engine == "pan"
    assert safe.intensity == 0.6
    assert safe.intensity_curve == ((0, 0.6),)
    assert safe.elevation == 0.0
    assert safe.bass_hz == 120.0


def test_every_built_in_style_is_valid() -> None:
    for preset in PRESETS.values():
        preset.config.validate()
    assert "lossless" not in PRESETS
    assert PRESETS["groove"].config.beat_sync is True
    assert PRESETS["retro"].config.engine == "pan"


def test_saving_styles_never_leaves_a_half_written_file(tmp_path: Path) -> None:
    file = tmp_path / "presets.toml"
    save_user_preset("first", PRESETS["studio"].config, based_on="studio", path=file)
    save_user_preset("second", PRESETS["groove"].config, based_on="groove", path=file)
    assert delete_user_preset("first", path=file)
    assert not delete_user_preset("first", path=file)

    assert list(tmp_path.iterdir()) == [file]
    assert list(load_user_presets(file)) == ["Second"]
