# Developed by ::> Gehan Fernando
"""Removes an original song after its 8D copy is safely finished.

On Windows the file goes to the Recycle Bin, so a change of heart is one
right-click -> Restore away; elsewhere it goes to the desktop's Trash. An
original is never deleted for good: where no bin can take it (USB sticks and
network drives have none), it stays in its folder as '<song> (original)'.
"""

import ctypes
import os
import shutil
import sys
import time
import urllib.parse
from pathlib import Path

from ..core.errors import ConversionError

# SHFileOperationW flags: allow undo (Recycle Bin), no dialogs, progress or error UI
_FO_DELETE = 0x0003
_FOF_SILENT = 0x0004
_FOF_NOCONFIRMATION = 0x0010
_FOF_ALLOWUNDO = 0x0040
_FOF_NOERRORUI = 0x0400
# Only fixed disks have a Recycle Bin; elsewhere Windows deletes for good, silently
_DRIVE_FIXED = 3

# What remove_original reports: moved to a bin, or kept under a new name
RECYCLE_BIN = "Recycle Bin"
TRASH = "Trash"
_KEPT = "kept as "


class _ShFileOpStruct(ctypes.Structure):  # pylint: disable=too-few-public-methods
    """SHFILEOPSTRUCTW from shellapi.h."""

    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", ctypes.c_int),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


def _windows_recycle(path: Path) -> bool:
    """Send one file to the Windows Recycle Bin; True if it worked."""
    operation = _ShFileOpStruct(
        hwnd=None,
        wFunc=_FO_DELETE,
        # The list of names ends with an extra NUL character
        pFrom=str(path) + "\0",
        pTo=None,
        fFlags=_FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_SILENT | _FOF_NOERRORUI,
    )
    result = ctypes.windll.shell32.SHFileOperationW(  # type: ignore[attr-defined]
        ctypes.byref(operation)
    )
    return result == 0 and not operation.fAnyOperationsAborted and not path.exists()


def _has_recycle_bin(path: Path) -> bool:
    """True when the file's drive keeps deleted files in a Recycle Bin."""
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    return kernel32.GetDriveTypeW(path.anchor) == _DRIVE_FIXED


def _keep_aside(path: Path) -> Path:
    """Rename the original to '<song> (original)' so its name is free again."""
    target = path.with_name(f"{path.stem} (original){path.suffix}")
    number = 2
    while target.exists():
        target = path.with_name(f"{path.stem} (original {number}){path.suffix}")
        number += 1
    path.rename(target)
    return target


def _unix_trash(path: Path) -> bool:
    """Move a file to ~/.Trash (macOS) or the freedesktop Trash (Linux)."""
    if sys.platform == "darwin":
        target_dir = Path.home() / ".Trash"
        if not target_dir.is_dir():
            return False
        target = target_dir / path.name
        if target.exists():
            target = target_dir / f"{path.stem} {time.time_ns()}{path.suffix}"
        shutil.move(str(path), str(target))
        return True
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    trash = Path(data_home) / "Trash"
    files, info = trash / "files", trash / "info"
    files.mkdir(parents=True, exist_ok=True)
    info.mkdir(parents=True, exist_ok=True)
    name = path.name
    if (files / name).exists():
        name = f"{path.stem}.{time.time_ns()}{path.suffix}"
    (info / f"{name}.trashinfo").write_text(
        "[Trash Info]\n"
        f"Path={urllib.parse.quote(str(path))}\n"
        f"DeletionDate={time.strftime('%Y-%m-%dT%H:%M:%S')}\n",
        encoding="utf-8",
    )
    shutil.move(str(path), str(files / name))
    return True


def remove_original(path: Path) -> str:
    """Move the file out of the way safely; returns where it went (see describe)."""
    try:
        if os.name == "nt":
            if _has_recycle_bin(path) and _windows_recycle(path):
                return RECYCLE_BIN
        elif _unix_trash(path):
            return TRASH
        return _KEPT + _keep_aside(path).name
    except OSError as exc:
        raise ConversionError(
            f"Could not remove the original song {path}: {exc}"
        ) from exc


def describe_removal(where: str) -> str:
    """remove_original's answer in words, e.g. 'moved to the Recycle Bin'."""
    if where.startswith(_KEPT):
        return f"kept in its folder as '{where[len(_KEPT) :]}' (no Recycle Bin there)"
    return f"moved to the {where}"


def removal_summary(places: list[str]) -> list[str]:
    """One line per outcome for many songs, e.g. '3 originals moved to the Trash.'"""
    lines = []
    for bin_name in (RECYCLE_BIN, TRASH):
        moved = places.count(bin_name)
        if moved:
            plural = "s" if moved != 1 else ""
            lines.append(f"{moved} original{plural} moved to the {bin_name}.")
    kept = sum(1 for place in places if place.startswith(_KEPT))
    if kept:
        plural, their = ("s", "their") if kept != 1 else ("", "its")
        lines.append(
            f"{kept} original{plural} kept in {their} folder as '<song> (original)' "
            "(no Recycle Bin there)."
        )
    return lines
