# Developed by ::> Gehan Fernando
"""The window's own preferences (tools, look, defaults), kept in a small JSON file.

The file sits next to your saved styles (see core/locations.py). A missing
file simply means the defaults; a damaged one is explained and replaced with
the defaults on the next save, so it can never stop Audio8D from starting.
"""

import dataclasses
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import InputValidationError
from .locations import config_dir

LOG = logging.getLogger(__name__)

# Bumped when the file's layout changes; older files are read and upgraded
FORMAT_VERSION = 1
THEMES = ("System", "Light", "Dark")
SCALES = (0.9, 1.0, 1.1, 1.25)
PREVIEW_LENGTHS = (15, 30, 45, 60)


@dataclass
class Preferences:
    """Everything the Settings page remembers between runs."""

    # An empty path means "find it automatically"
    ffmpeg_path: str = ""
    ffprobe_path: str = ""
    # The Python that runs the singer add-on; empty finds one automatically
    python_path: str = ""
    theme: str = "System"
    scale: float = 1.0
    verbose: bool = False
    # The default style and the Output step's defaults, remembered between runs
    default_style: str = ""
    preview_seconds: int = 30
    output: dict[str, Any] = field(default_factory=dict)

    def tools(self) -> tuple[Path | None, Path | None]:
        """The chosen ffmpeg and ffprobe, or None for automatic."""
        return (
            Path(self.ffmpeg_path) if self.ffmpeg_path.strip() else None,
            Path(self.ffprobe_path) if self.ffprobe_path.strip() else None,
        )

    def python(self) -> Path | None:
        """The chosen Python for the add-on, or None for automatic."""
        return Path(self.python_path) if self.python_path.strip() else None


def preferences_file() -> Path:
    """settings.json in Audio8D's settings folder."""
    return config_dir() / "settings.json"


def _checked(values: dict[str, Any]) -> tuple[Preferences, list[str]]:
    """Preferences from raw values; anything unusable falls back to its default."""
    defaults = Preferences()
    kept: dict[str, Any] = {}
    ignored: list[str] = []
    for item in dataclasses.fields(Preferences):
        if item.name not in values:
            continue
        value = values[item.name]
        default = getattr(defaults, item.name)
        if isinstance(default, bool):
            ok = isinstance(value, bool)
        elif isinstance(default, dict):
            ok = isinstance(value, dict)
        elif isinstance(default, int):
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif isinstance(default, float):
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
            value = float(value) if ok else value
        else:
            ok = isinstance(value, str)
        if item.name == "theme":
            ok = ok and value in THEMES
        if item.name == "scale":
            ok = ok and value in SCALES
        if item.name == "preview_seconds":
            ok = ok and value in PREVIEW_LENGTHS
        if ok:
            kept[item.name] = value
        else:
            ignored.append(item.name)
    return Preferences(**kept), ignored


def load_preferences(path: Path | None = None) -> tuple[Preferences, str | None]:
    """(the saved preferences, None) or (the defaults, why the file was not used)."""
    file = path or preferences_file()
    try:
        raw = file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Preferences(), None
    except OSError as exc:
        LOG.warning("Could not read %s: %s", file, exc)
        return Preferences(), f"Your settings file can't be read ({file})."
    try:
        data = json.loads(raw)
    except ValueError:
        LOG.warning("Settings file %s is damaged; using the defaults", file)
        return Preferences(), (
            "Your settings file was damaged, so the defaults are used. Saving any "
            "setting writes a fresh file."
        )
    if not isinstance(data, dict):
        return Preferences(), "Your settings file has an unexpected layout."
    # Version 0 (no number) is the same layout, so it upgrades without changes
    preferences, ignored = _checked(data)
    if ignored:
        LOG.warning("Ignored unusable settings in %s: %s", file, ", ".join(ignored))
    return preferences, None


def save_preferences(preferences: Preferences, path: Path | None = None) -> Path:
    """Write the preferences whole: aside first, then swapped in one step."""
    file = path or preferences_file()
    data = {"format_version": FORMAT_VERSION, **dataclasses.asdict(preferences)}
    # Each process writes aside under its own name, so two windows never collide
    partial = file.with_name(f"{file.name}.{os.getpid()}.tmp")
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        partial.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(partial, file)
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise InputValidationError(f"Cannot save your settings file {file}") from exc
    return file
