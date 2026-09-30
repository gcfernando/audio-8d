# Developed by ::> Gehan Fernando
"""Checks exporting styles to files and importing them, with every check first."""

# pytest hands fixtures to tests by name, which pylint sees as shadowing
# pylint: disable=redefined-outer-name

import copy
import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from src import PRESETS, EffectConfig, InputValidationError
from src.core import style_files
from src.core.style_files import (
    MAX_FILE_BYTES,
    export_style,
    import_style,
    read_style_file,
)
from src.core.user_presets import load_user_presets, save_user_preset

# A style is only the sound, so a shared style carries no file settings
_WILD = dataclasses.replace(
    PRESETS["groove"].config,
    intensity=0.95,
    elevation=0.4,
    speed_curve=((0.0, 10.0), (60.0, 6.0)),
    bpm=128.0,
)


@pytest.fixture
def styles(tmp_path: Path) -> Path:
    """A styles file holding one saved style, PartyMix."""
    file = tmp_path / "presets.toml"
    save_user_preset(
        "PartyMix", _WILD, based_on="groove", summary="big party", path=file
    )
    return file


@pytest.fixture
def exported(styles: Path, tmp_path: Path) -> Path:
    """PartyMix, exported to a style file."""
    return export_style(load_user_presets(styles)["PartyMix"], tmp_path / "party")


def _document(exported: Path) -> dict[str, Any]:
    return json.loads(exported.read_text(encoding="utf-8"))


def _write(tmp_path: Path, document: Any) -> Path:
    file = tmp_path / "edited.json"
    file.write_text(json.dumps(document), encoding="utf-8")
    return file


def test_the_schema_covers_every_setting() -> None:
    fields = {field.name for field in dataclasses.fields(EffectConfig)}
    assert set(style_files._SCHEMA) == fields  # pylint: disable=protected-access


def test_an_exported_style_comes_back_exactly(exported: Path, styles: Path) -> None:
    document = _document(exported)
    assert exported.suffix == ".json"
    assert document["format"] == "audio8d-style"
    assert document["version"] == 1
    assert document["name"] == "PartyMix"
    assert document["description"] == "big party"
    # Every setting is written out, not just the changes
    assert len(document["settings"]) == len(dataclasses.fields(EffectConfig))

    style = read_style_file(exported)
    assert style.config == _WILD
    assert style.name == "PartyMix" and style.summary == "big party"

    # Imported under a name of the user's own choosing, converted to PascalCase
    assert import_style(exported, "party copy", styles=styles) == "Party Copy"
    loaded = load_user_presets(styles)
    assert loaded["Party Copy"].config == _WILD
    assert loaded["Party Copy"].summary == "big party"
    assert loaded["PartyMix"].config == _WILD


@pytest.mark.parametrize("clash", ["PartyMix", "party mix", "PARTYMIX"])
def test_an_import_never_replaces_a_style_with_the_same_name(
    exported: Path, styles: Path, clash: str
) -> None:
    before = styles.read_text(encoding="utf-8")

    with pytest.raises(InputValidationError, match="already have a style"):
        import_style(exported, clash, styles=styles)
    assert styles.read_text(encoding="utf-8") == before


@pytest.mark.parametrize(
    ("name", "reason"),
    [("", "Type a name"), ("studio", "built-in"), ("9lives", "start with a letter")],
)
def test_the_chosen_import_name_follows_the_naming_rules(
    exported: Path, styles: Path, name: str, reason: str
) -> None:
    before = styles.read_text(encoding="utf-8")
    with pytest.raises(InputValidationError, match=reason):
        import_style(exported, name, styles=styles)
    assert styles.read_text(encoding="utf-8") == before


def _edit(document: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    """A copy with one property set ('settings.intensity') or removed (DELETE)."""
    edited = copy.deepcopy(document)
    *parents, key = path.split(".")
    table = edited
    for parent in parents:
        table = table[parent]
    if value is _DELETE:
        del table[key]
    else:
        table[key] = value
    return edited


_DELETE = object()


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        ("format", "something-else", "not an Audio8D style file"),
        ("format", _DELETE, "missing 'format'"),
        ("version", _DELETE, "missing 'version'"),
        ("version", 2, "made by a newer Audio8D"),
        ("version", 0, "not a valid version"),
        ("version", True, "not a valid version"),
        ("version", "1", "not a valid version"),
        ("name", _DELETE, "missing 'name'"),
        ("name", "   ", "'name' must be some text"),
        ("name", 7, "'name' must be some text"),
        ("name", "x" * 101, "longer than 100"),
        ("description", 5, "'description' must be text"),
        ("description", "x" * 121, "longer than 120"),
        ("settings", _DELETE, "missing 'settings'"),
        ("settings", [], "'settings' must be a JSON object"),
        ("extra", 1, "unknown property 'extra'"),
        ("settings.intensity", _DELETE, "'settings' is missing 'intensity'"),
        ("settings.wobble", 1, "unknown property 'wobble'"),
        ("settings.intensity", "big", "must be a number"),
        ("settings.intensity", True, "must be a number"),
        ("settings.intensity", None, "can't be empty"),
        ("settings.intensity", 2.5, "intensity must be between"),
        ("settings.rotation_seconds", 0.5, "rotation_seconds must be between"),
        ("settings.quality", 1.5, "must be a whole number"),
        ("settings.bitrate", 999, "must be one of"),
        ("settings.bitrate", "320", "must be a whole number"),
        ("settings.beat_sync", 1, "must be true or false"),
        ("settings.engine", "4d", "must be one of 3d, pan"),
        ("settings.output_format", "ogg", "must be one of"),
        ("settings.path", 3, "must be text"),
        ("settings.speed_curve", "0=8", "list of"),
        ("settings.speed_curve", [[0, 8, 9]], "pairs of numbers"),
        ("settings.speed_curve", [[0, "fast"]], "pairs of numbers"),
        ("settings.speed_curve", [[0, 8]] * 101, "more than 100 points"),
        ("settings.intensity_curve", [[0, 5]], "between"),
    ],
)
def test_every_part_of_an_imported_file_is_checked(
    exported: Path, styles: Path, path: str, value: Any, reason: str
) -> None:
    broken = _write(exported.parent, _edit(_document(exported), path, value))
    before = styles.read_text(encoding="utf-8")

    with pytest.raises(InputValidationError, match=reason) as error:
        import_style(broken, "Fresh", styles=styles)
    assert "can't be imported" in str(error.value)
    # Nothing is ever partly imported
    assert styles.read_text(encoding="utf-8") == before


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (b"", "empty"),
        (b"   \n", "empty"),
        (b"\xff\xfe\x00\x81 not text", "not a text file"),
        (b'{"format": "audio8d-style",', "not valid JSON"),
        (b"[1, 2, 3]", "expected a JSON object"),
        (b'{"format": "a", "format": "b"}', "appears twice"),
        (b'{"version": NaN}', "not a number a style can use"),
    ],
)
def test_corrupted_files_are_refused(
    tmp_path: Path, styles: Path, content: bytes, reason: str
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_bytes(content)
    before = styles.read_text(encoding="utf-8")

    with pytest.raises(InputValidationError, match=reason):
        import_style(broken, "Fresh", styles=styles)
    assert styles.read_text(encoding="utf-8") == before


def test_huge_and_missing_files_are_refused(tmp_path: Path) -> None:
    huge = tmp_path / "huge.json"
    huge.write_bytes(b" " * (MAX_FILE_BYTES + 1))
    with pytest.raises(InputValidationError, match="far too big"):
        read_style_file(huge)
    with pytest.raises(InputValidationError, match="does not exist"):
        read_style_file(tmp_path / "nowhere.json")


def test_a_failed_import_never_creates_a_styles_file(
    exported: Path, tmp_path: Path
) -> None:
    fresh = tmp_path / "new" / "presets.toml"
    broken = _write(tmp_path, _edit(_document(exported), "settings.engine", "4d"))

    with pytest.raises(InputValidationError):
        import_style(broken, "Fresh", styles=fresh)
    assert not fresh.exists()

    assert import_style(exported, "Fresh", styles=fresh) == "Fresh"
    assert load_user_presets(fresh)["Fresh"].config == _WILD


def test_exporting_writes_the_whole_file_or_nothing(
    styles: Path, tmp_path: Path
) -> None:
    style = load_user_presets(styles)["PartyMix"]
    target = export_style(style, tmp_path / "out.json")

    assert target == tmp_path / "out.json"
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "out.json",
        "presets.toml",
    ]
    with pytest.raises(InputValidationError, match="Cannot write"):
        export_style(style, tmp_path / "missing folder" / "out.json")
