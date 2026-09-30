# Developed by ::> Gehan Fernando
"""Your own styles, saved in a small TOML file and used like the built-in ones."""

import dataclasses
import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .errors import InputValidationError
from .locations import presets_file
from .parsing import format_keyframes, parse_keyframes
from .presets import LEGACY_STYLES, PRESETS, Preset, with_standard_output
from .settings import EffectConfig

# One PascalCase word, like Sunset or PartyMix; a later word may also be a number
_PART = r"(?:[A-Z][a-z0-9]*)+"
# New names are PascalCase words, joined or kept apart by single spaces
_PASCAL = re.compile(rf"^{_PART}(?: (?:{_PART}|[0-9]+))*$")
MAX_NAME_LENGTH = 40
# Styles saved before PascalCase names still load, so nobody loses one
_STORED_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,39}$")
# Table names TOML accepts without quotes; any other name is written in quotes
_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
# A word is a run of capitals, a capitalised word, or a run of digits
_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")
_FIELDS = {field.name: field for field in dataclasses.fields(EffectConfig)}
# Settings that may be switched off with the word "off" instead of a number
_OPTIONAL = {"loudness_target", "bitrate", "bpm"}
_CURVES = {"speed_curve", "intensity_curve"}
_HEADER = (
    "# Audio8D custom styles. Save new ones with --save-style NAME.\n"
    "# Any setting left out comes from the style named in based_on.\n"
    "# A style is only the sound: file type and loudness are chosen separately.\n"
)

Table = dict[str, dict[str, Any]]


def pascal_case(text: str) -> str:
    """'party mix' -> 'Party Mix', 'party_mix' or 'partyMix' -> 'PartyMix'.

    Spaces stay (one between words); everything else that isn't a letter or a
    number joins the words, and every word starts with a capital.
    """
    parts = (
        "".join(word[:1].upper() + word[1:].lower() for word in _WORD.findall(part))
        for part in text.split()
    )
    return " ".join(part for part in parts if part)


def name_key(name: str) -> str:
    """What makes two names the same: 'Party Mix', 'party-mix' and 'PARTYMIX' match."""
    return pascal_case(name).replace(" ", "").lower()


def find_style(name: str, styles: dict[str, Preset]) -> str | None:
    """The stored name of a style, however it was typed ('party mix', 'PartyMix')."""
    wanted = name_key(name)
    return next((key for key in styles if name_key(key) == wanted), None)


def check_style_name(
    text: str, taken: Iterable[str], *, keep: str | None = None
) -> str:
    """Turn a typed name into a valid new PascalCase name, or say exactly why not.

    taken holds the names already in use; keep is the style being renamed, which
    may keep its own name (in another letter case).
    """
    name = pascal_case(text)
    if not name:
        raise InputValidationError("Type a name for the style, e.g. Sunset Drive")
    if not name[0].isalpha():
        raise InputValidationError(
            f"Style names start with a letter ('{name}' starts with a number)"
        )
    if not _PASCAL.match(name):
        raise InputValidationError(
            f"'{name}' isn't a PascalCase name; use words that each start with a "
            "capital, like Sunset Drive"
        )
    if len(name) > MAX_NAME_LENGTH:
        raise InputValidationError(
            f"'{name}' is too long: style names have at most {MAX_NAME_LENGTH} "
            "letters, numbers and spaces"
        )
    if name_key(name) in {name_key(builtin) for builtin in [*PRESETS, *LEGACY_STYLES]}:
        raise InputValidationError(
            f"'{name}' is a built-in style; pick another name for your own style"
        )
    # Party Mix, PartyMix and an older party-mix are one name, so only one can exist
    others = {name_key(other) for other in taken if other != keep}
    if name_key(name) in others:
        raise InputValidationError(
            f"You already have a style called '{name}'; pick another name"
        )
    return name


def _parse_value(text: str, line_number: int) -> Any:
    """One TOML value: a "string", true/false, or a number."""
    if text.startswith('"'):
        if len(text) < 2 or not text.endswith('"'):
            raise InputValidationError(f"presets.toml line {line_number}: missing '\"'")
        return text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if text in {"true", "false"}:
        return text == "true"
    try:
        return int(text) if re.fullmatch(r"[+-]?\d+", text) else float(text)
    except ValueError:
        raise InputValidationError(
            f"presets.toml line {line_number}: '{text}' is not a value"
        ) from None


def _strip_comment(line: str) -> str:
    """Drop a trailing # comment, leaving any # inside a "string" alone."""
    in_string = False
    for index, char in enumerate(line):
        if char == '"' and (index == 0 or line[index - 1] != "\\"):
            in_string = not in_string
        elif char == "#" and not in_string:
            return line[:index]
    return line


def parse_toml(text: str) -> Table:
    """The small part of TOML this file needs: [tables] of key = value lines."""
    tables: Table = {}
    current: dict[str, Any] | None = None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            name = line[1:-1].strip().strip('"')
            current = tables.setdefault(name, {})
            continue
        key, equals, value = line.partition("=")
        if not equals or current is None:
            raise InputValidationError(
                f"presets.toml line {number}: expected [name] or key = value"
            )
        current[key.strip()] = _parse_value(value.strip(), number)
    return tables


def _format_value(value: Any) -> str:
    """The reverse of _parse_value."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return f"{value:g}" if isinstance(value, float) else str(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def dump_toml(tables: Table) -> str:
    """Write tables back out, one [name] block per style."""
    blocks = []
    for name, values in tables.items():
        lines = [f"[{name}]" if _BARE_KEY.match(name) else f'["{name}"]']
        lines += [f"{key} = {_format_value(value)}" for key, value in values.items()]
        blocks.append("\n".join(lines))
    return _HEADER + "\n" + "\n\n".join(blocks) + "\n"


def _config_from(name: str, values: dict[str, Any]) -> EffectConfig:
    """Build a style's settings on top of the style it is based on."""
    base_name = str(values.get("based_on", "classic"))
    # Styles based on an older name (lossless, hifi…) keep that name's sound
    base_name = LEGACY_STYLES.get(base_name, (base_name, {}))[0]
    if base_name not in PRESETS:
        raise InputValidationError(
            f"style '{name}' is based on '{base_name}', which does not exist"
        )
    overrides: dict[str, Any] = {}
    for key, value in values.items():
        if key in {"based_on", "summary"}:
            continue
        if key not in _FIELDS:
            raise InputValidationError(f"style '{name}' has an unknown setting '{key}'")
        if key in _OPTIONAL and value == "off":
            overrides[key] = None
        elif key in _CURVES:
            overrides[key] = parse_keyframes(str(value)) if value else ()
        else:
            overrides[key] = value
    try:
        config = dataclasses.replace(PRESETS[base_name].config, **overrides)
    except TypeError as exc:
        raise InputValidationError(f"style '{name}': {exc}") from exc
    config.validate()
    # File settings from older style files are ignored: output is chosen apart
    return with_standard_output(config)


def load_user_presets(path: Path | None = None) -> dict[str, Preset]:
    """Every saved style, or none if the file does not exist yet."""
    file = path or presets_file()
    try:
        text = file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise InputValidationError(f"Cannot read your styles file {file}") from exc
    presets = {}
    builtin = {name_key(key) for key in PRESETS}
    for name, values in parse_toml(text).items():
        if name_key(name) in builtin:
            continue
        if not _STORED_NAME.match(name):
            raise InputValidationError(
                f"style '{name}' has a name Audio8D can't use; give it a name made "
                "of letters and numbers"
            )
        presets[name] = Preset(
            name=name,
            summary=str(values.get("summary", "your own style")),
            config=_config_from(name, values),
            custom=True,
        )
    return presets


def all_presets(path: Path | None = None) -> dict[str, Preset]:
    """Built-in styles first, then your own."""
    return {**PRESETS, **load_user_presets(path)}


def _differences(config: EffectConfig, base: EffectConfig) -> dict[str, Any]:
    """Only the settings that differ from the base style, ready for TOML."""
    changed: dict[str, Any] = {}
    for key in _FIELDS:
        value = getattr(config, key)
        if value == getattr(base, key):
            continue
        if value is None:
            changed[key] = "off"
        elif key in _CURVES:
            changed[key] = format_keyframes(value)
        else:
            changed[key] = value
    return changed


def _read_styles(file: Path) -> dict[str, dict[str, Any]]:
    """The styles file's tables, or none yet; a read problem is explained."""
    try:
        return parse_toml(file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise InputValidationError(f"Cannot read your styles file {file}") from exc


def _write_styles(file: Path, tables: dict[str, dict[str, Any]]) -> None:
    """Save the styles file whole: written aside, then swapped in one step."""
    # A crash half-way must never cost every saved style; the name is per process
    partial = file.with_name(f"{file.name}.{os.getpid()}.tmp")
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        partial.write_text(dump_toml(tables), encoding="utf-8")
        os.replace(partial, file)
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise InputValidationError(f"Cannot save your styles file {file}") from exc


MAX_SUMMARY_LENGTH = 120


def clean_summary(text: str) -> str:
    """A description on one line (a line break would break the styles file)."""
    summary = " ".join(text.split())
    if len(summary) > MAX_SUMMARY_LENGTH:
        raise InputValidationError(
            f"The description is too long: at most {MAX_SUMMARY_LENGTH} characters"
        )
    return summary


def save_user_preset(
    name: str,
    config: EffectConfig,
    *,
    based_on: str = "classic",
    summary: str = "",
    path: Path | None = None,
) -> str:
    """Save a new style and return its name; an existing style is never replaced.

    The name is turned into PascalCase first ('party mix' -> 'PartyMix').
    """
    file = path or presets_file()
    tables = _read_styles(file)
    final = check_style_name(name, tables)
    base = LEGACY_STYLES.get(based_on, (based_on, {}))[0]
    base = base if base in PRESETS else "classic"
    config.validate()
    # Only the sound is a style's; how the file is saved is chosen separately
    config = with_standard_output(config)
    values: dict[str, Any] = {"based_on": base}
    described = clean_summary(summary)
    if described:
        values["summary"] = described
    values.update(_differences(config, PRESETS[base].config))
    tables[final] = values
    _write_styles(file, tables)
    return final


def _stored(name: str, tables: Table) -> str:
    """The saved style's own key, or a clear error if there is no such style."""
    for key in tables:
        if name_key(key) == name_key(name):
            return key
    raise InputValidationError(f"There is no saved style called '{name}'")


def rename_user_preset(name: str, new_name: str, *, path: Path | None = None) -> str:
    """Give a saved style a new, unused name and return it."""
    file = path or presets_file()
    tables = _read_styles(file)
    old = _stored(name, tables)
    final = check_style_name(new_name, tables, keep=old)
    # Keep the styles in the same order, only the name changes
    renamed = {final if key == old else key: values for key, values in tables.items()}
    _write_styles(file, renamed)
    return final


def update_user_preset(
    name: str,
    config: EffectConfig,
    *,
    new_name: str | None = None,
    summary: str | None = None,
    path: Path | None = None,
) -> str:
    """Save new settings into an existing style, optionally renaming it too.

    The style keeps its place in the file and the style it is based on. summary
    None keeps the description, and an empty one removes it. Everything is
    checked before writing, so a problem leaves the file exactly as it was.
    Returns the style's (possibly new) name.
    """
    file = path or presets_file()
    tables = _read_styles(file)
    # Built-in styles are never in the file, so they can't be changed here
    old = _stored(name, tables)
    final = old if new_name is None else check_style_name(new_name, tables, keep=old)
    stored = tables[old]
    based_on = str(stored.get("based_on", "classic"))
    base = LEGACY_STYLES.get(based_on, (based_on, {}))[0]
    if base not in PRESETS:
        raise InputValidationError(
            f"style '{old}' is based on '{based_on}', which does not exist"
        )
    described = (
        str(stored.get("summary", "")) if summary is None else clean_summary(summary)
    )
    config.validate()
    # Only the sound is a style's; how the file is saved is chosen separately
    config = with_standard_output(config)
    values: dict[str, Any] = {"based_on": based_on}
    if described:
        values["summary"] = described
    values.update(_differences(config, PRESETS[base].config))
    # The same place in the file, under the (possibly new) name
    updated = {
        final if key == old else key: values if key == old else table
        for key, table in tables.items()
    }
    _write_styles(file, updated)
    return final


def duplicate_user_preset(name: str, new_name: str, *, path: Path | None = None) -> str:
    """Copy a saved style under a new, unused name and return it."""
    file = path or presets_file()
    tables = _read_styles(file)
    old = _stored(name, tables)
    final = check_style_name(new_name, tables)
    tables[final] = dict(tables[old])
    _write_styles(file, tables)
    return final


def delete_user_preset(name: str, *, path: Path | None = None) -> bool:
    """Remove one saved style; True if it was there."""
    file = path or presets_file()
    tables = _read_styles(file)
    try:
        del tables[_stored(name, tables)]
    except InputValidationError:
        return False
    _write_styles(file, tables)
    return True
