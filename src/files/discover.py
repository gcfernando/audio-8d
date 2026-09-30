# Developed by ::> Gehan Fernando
"""Finds the songs inside a folder for batch conversion."""

import re
from pathlib import Path

from ..core.errors import InputValidationError
from .paths import SUFFIX_8D

# Everything FFmpeg can decode that people actually keep music in
AUDIO_EXTENSIONS = frozenset(
    {
        ".mp3",
        ".flac",
        ".wav",
        ".m4a",
        ".aac",
        ".ogg",
        ".oga",
        ".opus",
        ".wma",
        ".aif",
        ".aiff",
        ".alac",
        ".ape",
        ".wv",
        ".mka",
        ".mp4",
        ".webm",
    }
)

# Files Audio8D made or set aside itself, which must never be converted again
_OWN_MARKERS = (SUFFIX_8D, " (8D preview)", " (A-B compare)")
_KEPT_ORIGINAL = re.compile(r" \(original(?: \d+)?\)$")


def is_own_output(path: Path) -> bool:
    """True for '<song> (8D).mp3', originals kept aside, and other Audio8D files."""
    return path.stem.endswith(_OWN_MARKERS) or bool(_KEPT_ORIGINAL.search(path.stem))


def find_songs(folder: Path, *, recursive: bool = False) -> list[Path]:
    """Every song in folder (and its sub-folders if asked), sorted by name."""
    root = folder.expanduser()
    if not root.is_dir():
        raise InputValidationError(f"Input folder does not exist: {folder}")
    pattern = "**/*" if recursive else "*"
    songs = [
        path
        for path in root.glob(pattern)
        if path.is_file()
        and path.suffix.lower() in AUDIO_EXTENSIONS
        and not path.name.startswith(".")
        and not is_own_output(path)
    ]
    return sorted(songs, key=lambda path: str(path).lower())
