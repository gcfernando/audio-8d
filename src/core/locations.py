# Developed by ::> Gehan Fernando
"""Where Audio8D finds its own files, and where it keeps your styles, cache and log."""

import os
import platform
import sys
from pathlib import Path

# Tests (and people who want a portable setup) can point everything somewhere else
HOME_OVERRIDE = "AUDIO8D_HOME"


def is_packaged() -> bool:
    """True inside the standalone Audio8D.exe built with PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """The folder Audio8D runs from: next to Audio8D.exe, or the project folder."""
    if is_packaged():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def platform_tag() -> str:
    """This system and processor as package names spell them, e.g. 'linux-x86_64'."""
    system = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    machine = platform.machine().lower()
    # Windows says AMD64, macOS arm64, Linux x86_64 or aarch64: one name for each kind
    machine = {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64"}.get(
        machine, machine
    )
    return f"{system}-{machine}"


def _bundled_candidates() -> list[Path]:
    """Where a bundled ffmpeg and ffprobe may be, most specific first."""
    if is_packaged():
        # Beside the program, then in its bundled files (_internal, macOS Frameworks)
        inside = getattr(sys, "_MEIPASS", None)
        return [app_dir(), *([Path(inside)] if inside else [])]
    root = app_dir()
    # The copy kept for this system in vendor, then the older bin layout
    return [root / "vendor" / "ffmpeg" / platform_tag(), root / "bin"]


def tools_dir() -> Path:
    """The folder with the bundled ffmpeg and ffprobe for this system, if any."""
    ffmpeg = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    candidates = _bundled_candidates()
    return next((c for c in candidates if (c / ffmpeg).is_file()), candidates[0])


# The one and only guide; 'Open the full guide' always opens it in the browser
GUIDE_URL = "https://github.com/gcfernando/audio-8d/blob/main/README.md"


def config_dir() -> Path:
    """%APPDATA%\\Audio8D on Windows, ~/Library/... on macOS, ~/.config/... else."""
    override = os.environ.get(HOME_OVERRIDE)
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "Audio8D"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Audio8D"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "audio8d"


def cache_dir() -> Path:
    """A folder for measurements that are safe to delete at any time."""
    override = os.environ.get(HOME_OVERRIDE)
    if override:
        return Path(override) / "cache"
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Audio8D" / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "Audio8D"
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "audio8d"


def addon_dir() -> Path:
    """The add-on's own private Python environment, removed again by Uninstall."""
    override = os.environ.get(HOME_OVERRIDE)
    if override:
        return Path(override) / "addon"
    if os.name == "nt":
        return cache_dir().parent / "addon"
    if sys.platform == "darwin":
        return config_dir() / "addon"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "audio8d" / "addon"


def presets_file() -> Path:
    """The TOML file that holds styles saved with --save-style."""
    return config_dir() / "presets.toml"


def log_file() -> Path:
    """The technical log: %LOCALAPPDATA%\\Audio8D\\logs on Windows."""
    override = os.environ.get(HOME_OVERRIDE)
    if override:
        return Path(override) / "logs" / "audio8d.log"
    if os.name == "nt":
        return cache_dir().parent / "logs" / "audio8d.log"
    return config_dir() / "logs" / "audio8d.log"
