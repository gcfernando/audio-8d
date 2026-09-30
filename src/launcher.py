# Developed by ::> Gehan Fernando
"""Opens Audio8D in Windows Terminal instead of the old Command Prompt window.

Double-clicking `__main__.py` (or dropping a song on it) makes Windows open
the classic console window, which draws colours and progress bars poorly.
When that happens and Windows Terminal is installed, Audio8D starts itself
again in a Windows Terminal tab and quietly closes the old window.

It never moves a session you started yourself: if you typed the command in
PowerShell, Command Prompt or VS Code, it stays exactly where it is.
"""

import ctypes
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from .core.locations import is_packaged

# Set this to any value to never switch windows (tests set it too)
DISABLE_VARIABLE = "AUDIO8D_NO_WT"

# Programs whose windows people type commands into; never leave one of them
_SHELLS = frozenset(
    {
        "cmd.exe",
        "powershell.exe",
        "pwsh.exe",
        "bash.exe",
        "wsl.exe",
        "code.exe",
        "far.exe",
        "tcc.exe",
        "nu.exe",
        "conemu64.exe",
        "conemuc64.exe",
    }
)


def _console_process_names() -> list[str]:
    """The .exe names of every process attached to our console window."""
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    ids = (ctypes.c_uint32 * 64)()
    count = kernel32.GetConsoleProcessList(ids, 64)
    names = []
    for pid in ids[: min(count, 64)]:
        # PROCESS_QUERY_LIMITED_INFORMATION is allowed even for other users' tools
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            continue
        try:
            buffer = ctypes.create_unicode_buffer(1024)
            size = ctypes.c_uint32(len(buffer))
            if kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)
            ):
                names.append(Path(buffer.value).name.lower())
        finally:
            kernel32.CloseHandle(handle)
    return names


def is_own_console_window() -> bool:
    """True when this console window was opened just for us (e.g. a double-click)."""
    try:
        names = _console_process_names()
    except (AttributeError, OSError):
        return False
    return bool(names) and not any(name in _SHELLS for name in names)


def should_relaunch() -> bool:
    """True on Windows, outside Windows Terminal, in a window opened just for us."""
    return (
        os.name == "nt"
        and DISABLE_VARIABLE not in os.environ
        # Windows Terminal sets WT_SESSION in every tab it opens
        and "WT_SESSION" not in os.environ
        and "TERM_PROGRAM" not in os.environ
        and sys.stdin is not None
        and sys.stdin.isatty()
        and shutil.which("wt.exe") is not None
        and is_own_console_window()
    )


def _start_command(arguments: Sequence[str]) -> list[str]:
    """How to start this same Audio8D again, with the same arguments."""
    # Windows Terminal treats a lone ';' as "next command", so escape it in names
    escaped = [arg.replace(";", r"\;") for arg in arguments]
    # The standalone exe is its own program; there is no Python to call
    if is_packaged():
        return [sys.executable, *escaped]
    main_file = Path(__file__).resolve().with_name("__main__.py")
    python = sys.executable
    # pythonw has no console, so always use the console python next to it
    if python.lower().endswith("pythonw.exe"):
        python = python[: -len("pythonw.exe")] + "python.exe"
    return [python, str(main_file), *escaped]


def relaunch_in_windows_terminal(arguments: Sequence[str]) -> bool:
    """Reopen in a Windows Terminal tab; True when that worked and we should exit."""
    if not should_relaunch():
        return False
    command = [
        "wt.exe",
        "-w",
        "new",
        "new-tab",
        "--title",
        "Audio8D",
        "--startingDirectory",
        os.getcwd(),
        *_start_command(arguments),
    ]
    try:
        environment = {**os.environ, DISABLE_VARIABLE: "1"}
        subprocess.Popen(command, env=environment, close_fds=True)  # pylint: disable=consider-using-with
    except OSError:
        return False
    return True
