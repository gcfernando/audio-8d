# Developed by ::> Gehan Fernando
"""The Audio8D window: `audio8d --gui` (or the `audio8d-gui` command).

The window is built with CustomTkinter (gui_app.py), with Pillow for the icons:
python -m pip install customtkinter pillow. This module only checks that
CustomTkinter is there (drag-and-drop lives in dropfiles.py).
"""

import importlib.util
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from tkinter import Tk

from .dropfiles import enable_file_drop
from .logs import start_log_file

INSTALL_HINT = "python -m pip install customtkinter pillow"
LOG = logging.getLogger(__name__)


def customtkinter_available() -> bool:
    """True when the CustomTkinter package is installed for this Python."""
    return importlib.util.find_spec("customtkinter") is not None


def _tell(message: str) -> None:
    """Show a message in the terminal and, when there is no terminal, in a box."""
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    # Started without a terminal (Audio8D.exe, audio8d-gui): use a small box
    if sys.stderr is None or not sys.stderr.isatty():
        try:
            from tkinter import messagebox  # pylint: disable=import-outside-toplevel

            root = Tk()
            root.withdraw()
            messagebox.showerror("Audio8D", message)
            root.destroy()
        except Exception:  # pylint: disable=broad-exception-caught
            LOG.exception("Could not show a message box")


def run_gui(songs: Sequence[Path] = ()) -> int:
    """Open the window (with any songs or folders already listed) until it closes."""
    log = start_log_file()
    if not customtkinter_available():
        _tell(
            "The Audio8D window needs the CustomTkinter package.\n\n"
            f"Install it once with:\n    {INSTALL_HINT}\n\n"
            "Everything else (the terminal app) works without it."
        )
        return 1
    try:
        from .gui_app import launch  # pylint: disable=import-outside-toplevel

        return launch(songs)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        # Nothing may vanish silently: log the details and say what happened
        LOG.exception("The window could not start")
        where = f"\n\nTechnical details are in:\n{log}" if log else ""
        _tell(f"Audio8D could not open its window.\n\n{exc}{where}")
        return 1


def main() -> int:
    """Entry point for the `audio8d-gui` command installed by pip."""
    return run_gui()


__all__ = ["customtkinter_available", "enable_file_drop", "main", "run_gui"]
