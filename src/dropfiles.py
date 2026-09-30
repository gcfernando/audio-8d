# Developed by ::> Gehan Fernando
"""Windows drag-and-drop for any Tk window (Tk has none of its own)."""

import ctypes
import logging
import os
import queue
from collections.abc import Callable
from pathlib import Path
from tkinter import Tk

LOG = logging.getLogger(__name__)

# How often the window collects dropped files (milliseconds)
_COLLECT_MS = 100


def enable_file_drop(window: Tk, on_drop: Callable[[list[Path]], None]) -> bool:
    """Let files be dragged from File Explorer onto the window (Windows only).

    Tk has no drag-and-drop of its own, so this listens for the WM_DROPFILES
    message the way any Windows program does. Returns False where unsupported.
    """
    if os.name != "nt":
        return False
    try:
        from ctypes import wintypes  # pylint: disable=import-outside-toplevel

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
        lresult = ctypes.c_ssize_t
        wndproc = ctypes.WINFUNCTYPE(
            lresult, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )
        user32.GetParent.restype = wintypes.HWND
        user32.SetWindowLongPtrW.restype = ctypes.c_void_p
        user32.SetWindowLongPtrW.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        user32.CallWindowProcW.restype = lresult
        user32.CallWindowProcW.argtypes = [
            ctypes.c_void_p,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        shell32.DragQueryFileW.argtypes = [
            ctypes.c_void_p,
            wintypes.UINT,
            ctypes.c_wchar_p,
            wintypes.UINT,
        ]
        shell32.DragFinish.argtypes = [ctypes.c_void_p]

        window.update_idletasks()
        hwnd = user32.GetParent(window.winfo_id())
        wm_dropfiles = 0x0233
        # Calling Tk from inside its own message loop kills Python, so just queue here
        dropped: queue.SimpleQueue[list[Path]] = queue.SimpleQueue()

        def handler(handle: int, message: int, wparam: int, lparam: int) -> int:
            """Collect the dropped paths, then let Tk handle everything else."""
            if message == wm_dropfiles:
                # An error here would vanish inside Windows, so log it and move on
                try:
                    count = shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                    paths = []
                    for index in range(count):
                        length = shell32.DragQueryFileW(wparam, index, None, 0)
                        buffer = ctypes.create_unicode_buffer(length + 1)
                        shell32.DragQueryFileW(wparam, index, buffer, length + 1)
                        paths.append(Path(buffer.value))
                    dropped.put(paths)
                except Exception:  # pylint: disable=broad-exception-caught
                    LOG.exception("Could not read the dropped files")
                finally:
                    shell32.DragFinish(wparam)
                return 0
            return user32.CallWindowProcW(old, handle, message, wparam, lparam)

        callback = wndproc(handler)
        old = user32.SetWindowLongPtrW(hwnd, -4, ctypes.cast(callback, ctypes.c_void_p))
        if not old:
            # Without the window's own handler every other message would be lost
            LOG.warning("Drag-and-drop is off: the window could not be hooked")
            return False
        # Keep the callback alive with the window, or Windows would call freed code
        window._audio8d_drop = callback  # type: ignore[attr-defined]  # pylint: disable=protected-access
        shell32.DragAcceptFiles(hwnd, True)

        def collect() -> None:
            """Hand queued drops to the app, from Tk's normal event context."""
            window.after(_COLLECT_MS, collect)
            while not dropped.empty():
                on_drop(dropped.get())

        window.after(_COLLECT_MS, collect)
        LOG.info("Drag-and-drop is on")
        return True
    except (AttributeError, OSError) as exc:
        LOG.warning("Drag-and-drop is off: %s", exc)
        return False
