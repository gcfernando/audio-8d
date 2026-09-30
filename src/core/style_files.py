# Developed by ::> Gehan Fernando
"""Export a saved style to a file, and read one back, checking every part first.

A style file is JSON:

    {
      "format": "audio8d-style",
      "version": 1,
      "name": "PartyMix",
      "description": "big figure-8 for parties",
      "settings": { every EffectConfig setting, nothing left out }
    }

Every setting is written out, so the style comes back exactly the same whatever
the built-in styles look like by then. Reading a file checks all of it before
anything is saved: nothing is ever half imported.
"""

import dataclasses
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import InputValidationError
from .presets import Preset
from .settings import (
    BITRATES,
    DIRECTIONS,
    ENGINES,
    FORMAT_EXTENSIONS,
    PATHS,
    VOCAL_MODES,
    EffectConfig,
)
from .user_presets import MAX_SUMMARY_LENGTH, clean_summary, save_user_preset

FORMAT = "audio8d-style"
VERSION = 1
FILE_SUFFIX = ".json"
# A real style file is well under 2 KB; anything this big is not one
MAX_FILE_BYTES = 64 * 1024
MAX_CURVE_POINTS = 100
_MAX_NAME_TEXT = 100

_REQUIRED = ("format", "version", "name", "settings")
_OPTIONAL = ("description",)

# What each setting must be; kept next to EffectConfig by a test
_NUMBER, _INTEGER, _SWITCH, _CURVE = "number", "whole number", "true or false", "curve"
_SCHEMA: dict[str, tuple[str, bool, tuple[Any, ...] | None]] = {
    # name: (kind, may be null, allowed values)
    "rotation_seconds": (_NUMBER, False, None),
    "intensity": (_NUMBER, False, None),
    "ambience": (_NUMBER, False, None),
    "limiter_ceiling": (_NUMBER, False, None),
    "quality": (_INTEGER, False, None),
    "loudness_target": (_NUMBER, True, None),
    "bitrate": (_INTEGER, True, BITRATES),
    "exact_loudness": (_SWITCH, False, None),
    "engine": ("text", False, ENGINES),
    "bass_hz": (_NUMBER, False, None),
    "path": ("text", False, PATHS),
    "direction": ("text", False, DIRECTIONS),
    "elevation": (_NUMBER, False, None),
    "fade_seconds": (_NUMBER, False, None),
    "speed_curve": (_CURVE, False, None),
    "intensity_curve": (_CURVE, False, None),
    "beat_sync": (_SWITCH, False, None),
    "bpm": (_NUMBER, True, None),
    "vocals": ("text", False, VOCAL_MODES),
    "output_format": ("text", False, tuple(FORMAT_EXTENSIONS)),
    "match_loudness": (_SWITCH, False, None),
}


@dataclass(frozen=True, slots=True)
class StyleFile:
    """A style read from a file and fully checked, ready to be saved."""

    name: str
    summary: str
    config: EffectConfig


def _problem(text: str) -> InputValidationError:
    """Every import problem starts the same way, so the window can explain it."""
    return InputValidationError(f"This style file can't be imported: {text}")


def export_style(preset: Preset, path: Path) -> Path:
    """Write one style to a file (written aside first, then swapped in)."""
    settings: dict[str, Any] = {}
    for key in _SCHEMA:
        value = getattr(preset.config, key)
        settings[key] = (
            [list(point) for point in value] if key.endswith("_curve") else value
        )
    document = {
        "format": FORMAT,
        "version": VERSION,
        "name": preset.name,
        "description": preset.summary,
        "settings": settings,
    }
    # A name typed without an ending still gets .json, so it opens as a style file
    target = path if path.suffix else path.with_suffix(FILE_SUFFIX)
    partial = target.with_name(f"{target.name}.tmp")
    try:
        partial.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        os.replace(partial, target)
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise InputValidationError(f"Cannot write the style file {target}") from exc
    return target


def _no_repeats(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """JSON allows a key twice; a style file must not, or one value would be lost."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _problem(f"'{key}' appears twice")
        result[key] = value
    return result


def _not_a_number(text: str) -> float:
    """NaN and Infinity are JavaScript words, not numbers a style can use."""
    raise _problem(f"'{text}' is not a number a style can use")


def _read_json(path: Path) -> Any:
    """The file's JSON, after checking it is small, readable UTF-8 text."""
    try:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise _problem(
                f"it is {size // 1024} KB, far too big for a style file "
                f"(at most {MAX_FILE_BYTES // 1024} KB)"
            )
        data = path.read_bytes()
    except FileNotFoundError:
        raise _problem(f"{path} does not exist") from None
    except OSError as exc:
        raise _problem(f"{path} can't be read ({exc.strerror or exc})") from None
    try:
        # Notepad may add an invisible mark at the start; utf-8-sig skips it
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise _problem("it is not a text file") from None
    if not text.strip():
        raise _problem("the file is empty")
    try:
        return json.loads(
            text, object_pairs_hook=_no_repeats, parse_constant=_not_a_number
        )
    except json.JSONDecodeError as exc:
        raise _problem(
            f"it is not valid JSON (line {exc.lineno}, column {exc.colno}: {exc.msg})"
        ) from None


def _check_keys(
    table: dict[str, Any], required: tuple[str, ...], allowed: set[str], where: str
) -> None:
    """Every required property is there, and nothing unknown is."""
    for key in required:
        if key not in table:
            raise _problem(f"{where} is missing '{key}'")
    for key in table:
        if key not in allowed:
            raise _problem(f"{where} has an unknown property '{key}'")


def _is_number(value: Any) -> bool:
    """A real, finite number (true and false are not numbers here)."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _setting(key: str, value: Any) -> Any:
    """One setting, checked against its kind and allowed values."""
    kind, nullable, allowed = _SCHEMA[key]
    where = f"setting '{key}'"
    if value is None:
        if nullable:
            return None
        raise _problem(f"{where} can't be empty (null)")
    if kind == _NUMBER:
        if not _is_number(value):
            raise _problem(f"{where} must be a number, not {json.dumps(value)}")
        return float(value)
    if kind == _INTEGER:
        if not isinstance(value, int) or isinstance(value, bool):
            raise _problem(f"{where} must be a whole number, not {json.dumps(value)}")
    elif kind == _SWITCH:
        if not isinstance(value, bool):
            raise _problem(f"{where} must be true or false, not {json.dumps(value)}")
    elif kind == _CURVE:
        return _curve(where, value)
    elif not isinstance(value, str):
        raise _problem(f"{where} must be text, not {json.dumps(value)}")
    if allowed is not None and value not in allowed:
        choices = ", ".join(str(choice) for choice in allowed)
        raise _problem(f"{where} is {json.dumps(value)}; it must be one of {choices}")
    return value


def _curve(where: str, value: Any) -> tuple[tuple[float, float], ...]:
    """A list of [time, value] pairs."""
    if not isinstance(value, list):
        raise _problem(f"{where} must be a list of [time, value] pairs")
    if len(value) > MAX_CURVE_POINTS:
        raise _problem(f"{where} has more than {MAX_CURVE_POINTS} points")
    points = []
    for point in value:
        if (
            not isinstance(point, list)
            or len(point) != 2
            or not all(_is_number(part) for part in point)
        ):
            raise _problem(
                f"{where} must be a list of [time, value] pairs of numbers, "
                f"not {json.dumps(point)}"
            )
        points.append((float(point[0]), float(point[1])))
    return tuple(points)


def read_style_file(path: Path) -> StyleFile:
    """Read and check a style file completely; raise with the exact reason if not."""
    document = _read_json(path)
    if not isinstance(document, dict):
        raise _problem("it does not hold a style (expected a JSON object)")
    _check_keys(document, _REQUIRED, set(_REQUIRED + _OPTIONAL), "the file")
    if document["format"] != FORMAT:
        raise _problem(
            f"it is not an Audio8D style file (format '{document['format']}')"
        )
    version = document["version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise _problem(f"its version {json.dumps(version)} is not a valid version")
    # A newer file may hold settings this version doesn't know, so it is refused
    if version > VERSION:
        raise _problem(
            f"it was made by a newer Audio8D (style file version {version}); this "
            f"version reads version {VERSION}"
        )
    name = document["name"]
    if not isinstance(name, str) or not name.strip():
        raise _problem("its 'name' must be some text")
    if len(name) > _MAX_NAME_TEXT:
        raise _problem(f"its 'name' is longer than {_MAX_NAME_TEXT} characters")
    summary = document.get("description", "")
    if not isinstance(summary, str):
        raise _problem("its 'description' must be text")
    try:
        summary = clean_summary(summary)
    except InputValidationError:
        raise _problem(
            f"its 'description' is longer than {MAX_SUMMARY_LENGTH} characters"
        ) from None
    settings = document["settings"]
    if not isinstance(settings, dict):
        raise _problem("its 'settings' must be a JSON object")
    _check_keys(settings, tuple(_SCHEMA), set(_SCHEMA), "'settings'")
    # Every setting is checked on its own first, then the whole style together
    values = {key: _setting(key, settings[key]) for key in _SCHEMA}
    config = dataclasses.replace(EffectConfig(), **values)
    try:
        config.validate()
    except InputValidationError as exc:
        raise _problem(str(exc)) from None
    return StyleFile(name=name.strip(), summary=summary, config=config)


def import_style(path: Path, name: str, *, styles: Path | None = None) -> str:
    """Check the file and the chosen name completely, then save; return the name."""
    # The file is checked in full before the name, and nothing is saved until both pass
    style = read_style_file(path)
    return save_user_preset(name, style.config, summary=style.summary, path=styles)
