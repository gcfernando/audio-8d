# Developed by ::> Gehan Fernando
"""The optional singer add-on: its status, installing, repairing and uninstalling it.

'Keep the singer in the middle' runs Demucs, an AI model that splits the voice
from the music. Demucs brings PyTorch (about 1 GB), so it is not part of
Audio8D. Installing makes a private Python environment in Audio8D's own data
folder (see locations.addon_dir) from a Python already on the computer, and
installs Demucs there; nothing else on the computer changes, and Uninstall
simply deletes that folder. A Demucs you installed yourself into a Python of
your own is also found and used, but Audio8D never removes it. The window and
the command line both use this module, so they always agree.
"""

import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

# AddonProgress and STAGE_INSTALL are only passed on, for the window and tests
from .addon_progress import (  # noqa: F401  # pylint: disable=unused-import
    DONE_INSTALL,
    DONE_UNINSTALL,
    FAILED_INSTALL,
    FAILED_UNINSTALL,
    FOLDER_DONE,
    PIP_RAW,
    PIP_REPORT,
    PLAN_DONE,
    PLAN_TIMEOUT,
    RAW_PROGRESS,
    REPAIR_REMOVE,
    STAGE_CHECK,
    STAGE_CLEANUP,
    STAGE_DOWNLOAD,
    STAGE_FOLDER,
    STAGE_INSTALL,
    STAGE_PLAN,
    STAGE_REMOVE,
    STAGE_REMOVE_OLD,
    STOPPED,
    AddonProgress,
    AddonProgressCallback,
    PipWatcher,
    Tracker,
)
from .core.errors import ConversionError
from .core.locations import addon_dir, is_packaged
from .ffmpeg.runner import owned, run_tool, start_process, stop_process

LOG = logging.getLogger(__name__)

# Demucs and PyTorch support these Python versions and newer
MIN_PYTHON = (3, 10)
# How long `python -c ...` may take before that Python counts as not working
PYTHON_TIMEOUT = 20.0
# Importing PyTorch for the first time can take a minute on a slow disk
IMPORT_TIMEOUT = 240.0

# What `where` means in PythonCheck.source, in the words the window shows
PYTHON_SOURCES = {
    "addon": "Audio8D's own add-on folder",
    "configured": "Chosen by you",
    "running": "The Python running Audio8D",
    "launcher": "Found automatically (the py launcher)",
    "path": "Found automatically (on the system PATH)",
    "missing": "Not found",
}


@dataclass(frozen=True, slots=True)
class Package:
    """One package the add-on needs: what to import, what to install, and why."""

    module: str
    dist: str
    purpose: str


# The add-on's packages; demucs.separate is what Audio8D actually runs
SINGER_PACKAGES = (
    Package("demucs.separate", "demucs", "the AI model that separates the voice"),
    Package("torch", "torch", "PyTorch, the engine Demucs runs on"),
    Package("numpy", "numpy", "number crunching Demucs 4.1 needs but doesn't install"),
)
# What `pip install` is given; pip brings everything else Demucs needs
INSTALL_SPEC = ("demucs", "numpy")


# What the add-on is, in plain words; the window, --addon-status and the guide agree
ADDON_INFO = (
    (
        "What it does",
        "Adds 'Keep the singer in the middle': an AI model (Demucs) separates the "
        "voice from the music, so only the music moves around you.",
    ),
    (
        "Benefits",
        "Songs with vocals keep a clear, steady voice in front of you while the "
        "band circles your head. Everything else in Audio8D works without it.",
    ),
    (
        "Changes to your computer",
        "Downloads about 1 GB (Demucs and PyTorch) into Audio8D's own add-on "
        "folder, using a Python already on your computer. Nothing else is changed.",
    ),
    (
        "Removal",
        "Uninstall deletes that folder again. Audio8D keeps working; only the "
        "singer option goes away.",
    ),
)


@dataclass(frozen=True, slots=True)
class PythonCheck:
    """What running a Python showed: its version, or why it can't be used."""

    path: Path | None
    ok: bool
    source: str = "missing"
    version: str = ""
    problem: str = ""
    # The raw output, for 'Technical details'
    detail: str = ""

    @property
    def source_words(self) -> str:
        """'Chosen by you', 'Found automatically (…)' or 'Not found'."""
        return PYTHON_SOURCES.get(self.source, self.source)


@dataclass(frozen=True, slots=True)
class PackageCheck:
    """Whether one package can be imported by the chosen Python."""

    package: Package
    ok: bool
    version: str = ""
    problem: str = ""
    detail: str = ""


@dataclass(frozen=True, slots=True)
class AddonStatus:
    """Everything known about the singer add-on after one check."""

    python: PythonCheck
    packages: tuple[PackageCheck, ...] = ()

    @property
    def ready(self) -> bool:
        """True when 'Keep the singer in the middle' can be used right now."""
        return (
            self.python.ok
            and bool(self.packages)
            and all(check.ok for check in self.packages)
        )

    @property
    def private(self) -> bool:
        """True when this is the copy Audio8D installed (and so can uninstall)."""
        return self.python.source == "addon"

    @property
    def missing(self) -> list[PackageCheck]:
        """The packages that are not installed or can't be loaded."""
        return [check for check in self.packages if not check.ok]

    @property
    def state(self) -> str:
        """'ready', 'no-python', 'not-installed' (none yet) or 'partial'."""
        if not self.python.ok:
            return "no-python"
        if self.ready:
            return "ready"
        # Common packages like numpy may already be there; Demucs itself decides
        demucs = self.packages[0] if self.packages else None
        if demucs is None or demucs.problem == "not installed":
            return "not-installed"
        return "partial"

    @property
    def words(self) -> str:
        """'Installed', 'Not installed' or 'Needs repair', for the status badge."""
        if self.ready:
            return "Installed"
        if self.private or self.state == "partial":
            return "Needs repair"
        return "Not installed"

    def summary(self) -> str:
        """One plain sentence about the add-on."""
        if self.ready:
            return "Installed: 'Keep the singer in the middle' can be used."
        if self.private:
            names = ", ".join(check.package.dist for check in self.missing) or "Python"
            return f"The add-on folder is damaged ({names} can't be used): repair it."
        if not self.python.ok:
            return f"Not installed. Installing needs Python. {self.python.problem}"
        names = ", ".join(check.package.dist for check in self.missing)
        if self.state == "not-installed":
            return "Audio8D works fully without it; install it only if you want it."
        return f"Only partly installed: {names} can't be used."

    def fix(self) -> str:
        """The next thing to do, in plain words."""
        if self.ready:
            return (
                "Switch on 'Keep the singer in the middle' in Customize (step 2), "
                "or use --vocals center."
            )
        if self.private:
            return "Repair it in Settings (Add-on), or run: audio8d --repair-addon"
        if not self.python.ok:
            return (
                f"Install Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer from "
                "python.org (tick 'Add python.exe to PATH'), then check again. Or "
                "choose a python.exe you already have."
            )
        return (
            "Install it in Settings (Add-on, 'Install add-on'), or run: "
            "audio8d --install-addon"
        )


def quote_command(command: Sequence[str]) -> str:
    """A command as it would be typed, with quotes around parts that need them."""
    return " ".join(f'"{part}"' if " " in part else part for part in command)


def install_command(python: Path) -> list[str]:
    """The pip command that installs the add-on's packages into this Python."""
    return [
        str(python),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        *INSTALL_SPEC,
    ]


def addon_python(folder: Path | None = None) -> Path:
    """The python inside the add-on's private folder (it may not exist yet)."""
    base = folder or addon_dir()
    return base / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


# ------------------------------------------------------------------ Python

# Asks a Python for its version and where it really lives, as JSON
_ASK_PYTHON = (
    "import json, sys; print(json.dumps({'version': list(sys.version_info[:3]), "
    "'executable': sys.executable}))"
)


def _run_python(command: list[str]) -> PythonCheck:
    """Run a Python (or the py launcher) and judge its answer."""
    path = Path(command[0])
    try:
        result = run_tool([*command, "-c", _ASK_PYTHON], timeout=PYTHON_TIMEOUT)
    except subprocess.TimeoutExpired:
        return PythonCheck(
            path,
            False,
            problem=f"{path.name} did not answer within {PYTHON_TIMEOUT:g} seconds.",
        )
    except OSError as exc:
        return PythonCheck(
            path,
            False,
            problem=f"{path.name} can't be started.",
            detail=str(exc),
        )
    output = f"{result.stdout}\n{result.stderr}".strip()
    if result.returncode != 0:
        # Windows ships python.exe shortcuts that only open the Microsoft Store
        if "Microsoft Store" in output or result.returncode == 9009:
            problem = (
                f"{path} is Windows' shortcut to the Microsoft Store, not a "
                "real Python."
            )
        else:
            problem = f"{path.name} started but stopped with an error."
        return PythonCheck(path, False, problem=problem, detail=output)
    try:
        info = json.loads(result.stdout.strip().splitlines()[-1])
        version = tuple(int(part) for part in info["version"])
        executable = Path(info["executable"])
    except (ValueError, KeyError, IndexError, TypeError):
        return PythonCheck(
            path,
            False,
            problem=f"{path.name} did not answer like Python does.",
            detail=output,
        )
    words = ".".join(map(str, version))
    if version[:2] < MIN_PYTHON:
        return PythonCheck(
            executable,
            False,
            version=words,
            problem=f"Python {words} is too old; the add-on needs "
            f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer.",
            detail=output,
        )
    return PythonCheck(executable, True, version=words, detail=output)


def check_python(path: Path | None, source: str = "configured") -> PythonCheck:
    """Run one Python and say whether the add-on can use it (never by file alone)."""
    if path is None:
        return PythonCheck(None, False, problem="No Python was found on this computer.")
    if not path.exists():
        return PythonCheck(path, False, source, problem=f"There is no file at {path}.")
    if path.is_dir():
        return PythonCheck(
            path,
            False,
            source,
            problem=f"{path} is a folder. Choose the python.exe inside it.",
        )
    found = _run_python([str(path)])
    return _with_source(found, source)


def _with_source(check: PythonCheck, source: str) -> PythonCheck:
    """The same check, labelled with where the Python came from."""
    return PythonCheck(
        check.path, check.ok, source, check.version, check.problem, check.detail
    )


def _automatic_candidates() -> list[tuple[list[str], str]]:
    """Commands that may start a Python, most likely first."""
    found: list[tuple[list[str], str]] = []
    # The standalone exe is not a Python, so it is never offered
    if not is_packaged():
        found.append(([sys.executable], "running"))
    launcher = shutil.which("py")
    if launcher:
        found.append(([launcher, "-3"], "launcher"))
    for name in ("python", "python3"):
        on_path = shutil.which(name)
        if on_path:
            found.append(([on_path], "path"))
    return found


def find_python(configured: Path | None = None) -> PythonCheck:
    """The Python the add-on uses: the chosen one, or the first working one found.

    A chosen path always wins, even when it is wrong, so a mistake is reported
    instead of quietly using a different Python.
    """
    if configured is not None:
        return check_python(configured, "configured")
    first_problem: PythonCheck | None = None
    seen: set[str] = set()
    for command, source in _automatic_candidates():
        key = command[0].lower()
        if key in seen:
            continue
        seen.add(key)
        found = _with_source(_run_python(command), source)
        if found.ok:
            return found
        first_problem = first_problem or found
    if first_problem is not None:
        return PythonCheck(
            first_problem.path,
            False,
            "missing",
            first_problem.version,
            "No working Python was found. " + first_problem.problem,
            first_problem.detail,
        )
    return PythonCheck(None, False, problem="No Python was found on this computer.")


# ------------------------------------------------------------------ packages

# Imports each module and answers in JSON after a marker, as packages may print too
_ASK_PACKAGES = """
import importlib, importlib.metadata as meta, json, sys
answer = {}
for pair in sys.argv[1:]:
    module, dist = pair.split("=")
    try:
        importlib.import_module(module)
        try:
            version = meta.version(dist)
        except meta.PackageNotFoundError:
            version = ""
        answer[module] = {"ok": True, "version": version}
    except ModuleNotFoundError as exc:
        # Only the package itself missing means "not installed"; else it's broken
        own = exc.name is not None and module.startswith(exc.name)
        answer[module] = {"ok": False, "missing": own, "error": str(exc)}
    except Exception as exc:
        answer[module] = {"ok": False, "missing": False,
                          "error": type(exc).__name__ + ": " + str(exc)}
print("AUDIO8D-PACKAGES " + json.dumps(answer))
"""


def check_packages(
    python: Path, packages: Sequence[Package] = SINGER_PACKAGES
) -> tuple[PackageCheck, ...]:
    """Import every package in that Python, the only reliable test that it works."""
    pairs = [f"{p.module}={p.dist}" for p in packages]
    try:
        result = run_tool(
            [str(python), "-c", _ASK_PACKAGES, *pairs], timeout=IMPORT_TIMEOUT
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return tuple(
            PackageCheck(p, False, problem="couldn't be checked", detail=str(exc))
            for p in packages
        )
    answer: dict = {}
    for line in result.stdout.splitlines():
        if line.startswith("AUDIO8D-PACKAGES "):
            try:
                answer = json.loads(line.split(" ", 1)[1])
            except ValueError:
                answer = {}
    checks = []
    for package in packages:
        found = answer.get(package.module)
        if found is None:
            checks.append(
                PackageCheck(
                    package,
                    False,
                    problem="couldn't be checked",
                    detail=(result.stderr or result.stdout).strip()[-2000:],
                )
            )
        elif found.get("ok"):
            checks.append(PackageCheck(package, True, version=found.get("version", "")))
        elif found.get("missing"):
            checks.append(
                PackageCheck(
                    package, False, problem="not installed", detail=found["error"]
                )
            )
        else:
            checks.append(
                PackageCheck(
                    package,
                    False,
                    problem="installed but can't be loaded"
                    + _needs(found.get("error", "")),
                    detail=found.get("error", ""),
                )
            )
    return tuple(checks)


def _needs(error: str) -> str:
    """' (it needs numpy)' when the import failed for want of another package."""
    if error.startswith("No module named "):
        return f" (it needs {error.split(' ', 3)[-1].strip(chr(39))})"
    return ""


def _pip_version(python: Path, cancel: threading.Event | None) -> tuple[int, int]:
    """The (major, minor) version of pip in this Python; (0, 0) when unknown."""
    try:
        result = run_tool(
            [str(python), "-m", "pip", "--version"],
            timeout=PYTHON_TIMEOUT,
            cancel=cancel,
        )
    except (OSError, subprocess.TimeoutExpired, ConversionError):
        return (0, 0)
    found = re.match(r"\s*pip (\d+)\.(\d+)", result.stdout)
    return (int(found.group(1)), int(found.group(2))) if found else (0, 0)


def _planned_files(python: Path, cancel: threading.Event | None) -> int | None:
    """How many package files pip will fetch, from a dry run; None when unknown."""
    command = [
        *install_command(python)[:4],
        "--dry-run",
        "--quiet",
        "--report",
        "-",
        *install_command(python)[4:],
    ]
    try:
        result = run_tool(command, timeout=PLAN_TIMEOUT, cancel=cancel)
        report = json.loads(result.stdout)
        return len(report["install"])
    except (OSError, subprocess.TimeoutExpired, ConversionError) as exc:
        LOG.info("Could not plan the add-on download: %s", exc)
    except (ValueError, KeyError, TypeError) as exc:
        LOG.info("pip gave no usable install report: %s", exc)
    return None


def _run_streamed(
    command: list[str],
    on_line: Callable[[str], None] | None = None,
    cancel: threading.Event | None = None,
) -> tuple[bool, str]:
    """Run a command, passing each line it prints to on_line; stoppable with cancel.

    Returns (worked, the last lines it printed). Ctrl+C stops the command too.
    """
    LOG.info("Running: %s", quote_command(command))
    try:
        process = start_process(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return False, f"{Path(command[0]).name} could not be started: {exc}"
    tail: list[str] = []

    def read() -> None:
        """Keep the last lines and pass each on, until the command stops or ends."""
        assert process.stdout is not None
        try:
            for raw in process.stdout:
                line = raw.rstrip()
                # Once stopped, the rest is only drained so the command can exit
                if not line or (cancel is not None and cancel.is_set()):
                    continue
                # Byte counts would push the useful last words out of the tail
                if not RAW_PROGRESS.match(line):
                    tail[:] = (tail + [line])[-30:]
                if on_line is not None:
                    on_line(line)
        except (OSError, ValueError):
            # The pipe closed because the command was stopped
            pass

    # Output is read on its own thread, so a quiet pip can still be stopped at once
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        # owned() kills pip on Ctrl+C, so it never keeps installing on its own
        with owned(process):
            while True:
                if cancel is not None and cancel.is_set():
                    stop_process(process)
                    return False, "Stopped before it finished."
                try:
                    process.wait(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    continue
    finally:
        reader.join(timeout=5)
    text = "\n".join(tail)
    if process.returncode != 0 and "No module named pip" in text:
        text += (
            "\nThis Python has no pip. Run  python -m ensurepip --upgrade  once, "
            "then install again."
        )
    return process.returncode == 0, text


def install_packages(
    python: Path,
    on_line: Callable[[str], None] | None = None,
    cancel: threading.Event | None = None,
    raw_progress: bool = False,
) -> tuple[bool, str]:
    """pip-install the add-on's packages into this Python.

    raw_progress asks pip (24.1 or newer) for exact byte counts while downloading.
    """
    command = install_command(python)
    if raw_progress:
        command = [*command[:4], "--progress-bar", "raw", *command[4:]]
    return _run_streamed(command, on_line, cancel)


def _measured_install(
    python: Path,
    on_line: Callable[[str], None] | None,
    cancel: threading.Event | None,
    tracker: Tracker,
) -> tuple[bool, str]:
    """pip-install with real progress: plan the download, then follow pip's output."""
    version = _pip_version(python, cancel)
    planned = None
    if version >= PIP_REPORT:
        # Resolving has no known total, so it shows as busy until it's done
        tracker.step(STAGE_PLAN, None, force=True)
        planned = _planned_files(python, cancel)
    if planned is not None:
        tracker.step(STAGE_PLAN, PLAN_DONE, f"{planned} files to fetch", force=True)
    watcher = PipWatcher(tracker, planned)
    tracker.step(STAGE_DOWNLOAD, None if planned is None else PLAN_DONE, force=True)

    def watch(line: str) -> None:
        """Measure progress from each line, and show the lines people can read."""
        watcher.feed(line)
        if on_line is not None and not RAW_PROGRESS.match(line):
            on_line(line)

    return install_packages(python, watch, cancel, raw_progress=version >= PIP_RAW)


def _delete_entry(path: str, is_dir: bool) -> None:
    """Delete one file or empty folder, making a read-only one writable first."""
    remove = os.rmdir if is_dir else os.unlink
    try:
        remove(path)
    except PermissionError:
        # Windows marks some files read-only; make them writable and try once more
        os.chmod(path, stat.S_IWRITE)
        remove(path)


def _entries(folder: Path) -> list[tuple[str, bool]]:
    """Every file and folder inside folder, deepest first, then folder itself."""
    found: list[tuple[str, bool]] = []
    for here, folders, files in os.walk(folder, topdown=False):
        found += [(os.path.join(here, name), False) for name in files]
        # A link to a folder is removed as a link, never followed
        found += [
            (os.path.join(here, name), False)
            for name in folders
            if os.path.islink(os.path.join(here, name))
        ]
        found.append((here, True))
    return found


def _remove_folder(
    folder: Path,
    tracker: Tracker | None = None,
    cancel: threading.Event | None = None,
    stage: str = STAGE_REMOVE,
) -> str | None:
    """Delete a folder completely; None when it worked, else the reason in words.

    Files are counted first, so removal reports real 'n of total' progress.
    """
    if not folder.exists():
        return None
    if tracker is not None:
        tracker.step(stage, None, "Counting files", force=True)
    entries = _entries(folder)
    total = len(entries)
    for number, (path, is_dir) in enumerate(entries, start=1):
        if cancel is not None and cancel.is_set():
            return (
                "Stopped before it finished; part of the add-on was already "
                "removed. Uninstall or repair it again to finish."
            )
        try:
            _delete_entry(path, is_dir)
        except FileNotFoundError:
            pass
        except OSError as exc:
            LOG.warning("Could not remove %s: %s", path, exc)
            return (
                f"Some files in {folder} are in use or protected "
                f"({exc.strerror or exc}). Close anything using the add-on (or "
                "restart the computer) and try again."
            )
        if tracker is not None:
            tracker.step(stage, number / total, f"{number} of {total} files")
    return None


def install_addon(
    base: Path,
    on_line: Callable[[str], None] | None = None,
    cancel: threading.Event | None = None,
    on_progress: AddonProgressCallback | None = None,
) -> tuple[bool, str]:
    """Install the add-on into Audio8D's private folder, using the Python at base.

    Installing again when it is ready changes nothing. A failed or stopped
    install leaves no half-made folder behind. It only counts as installed once
    the add-on's own check passes. Returns (worked, what happened); on_progress
    gets AddonProgress reports along the way.
    """
    return _install(base, on_line, cancel, Tracker(on_progress))


def _install(
    base: Path,
    on_line: Callable[[str], None] | None,
    cancel: threading.Event | None,
    tracker: Tracker,
) -> tuple[bool, str]:
    """install_addon's work, reporting to a tracker a repair can share."""
    folder = addon_dir()
    forget_status()
    if folder.exists() and check_singer().ready:
        tracker.finish(DONE_INSTALL, ok=True, detail="It was already installed")
        return True, "The add-on is already installed; nothing was changed."
    fresh = not folder.exists()
    # Only a finished, checked install counts; anything else removes a new folder
    installed = False
    status: AddonStatus | None = None
    tail = ""
    try:
        if fresh:
            folder.parent.mkdir(parents=True, exist_ok=True)
            if on_line is not None:
                on_line(f"Making the add-on folder {folder}")
            # venv doesn't say how far it has got, so this step is unmeasured
            tracker.step(STAGE_FOLDER, None, str(folder), force=True)
            worked, tail = _run_streamed(
                [str(base), "-m", "venv", str(folder)], on_line, cancel
            )
            if not worked:
                tail = tail or "Python could not make the add-on folder."
                return False, tail
            tracker.step(STAGE_FOLDER, FOLDER_DONE, force=True)
        worked, tail = _measured_install(addon_python(folder), on_line, cancel, tracker)
        if worked:
            tracker.step(STAGE_CHECK, None, force=True)
            status = check_singer()
            installed = status.ready
            if not installed:
                tail = f"{tail}\nThe packages installed, but {status.summary()}"
    finally:
        # Failed, stopped or Ctrl+C: nothing half-installed is left behind
        if fresh and not installed and folder.exists():
            tracker.step(STAGE_CLEANUP, None, force=True)
            _remove_folder(folder)
        forget_status()
        if installed and status is not None:
            remember_status(status)
            tracker.finish(DONE_INSTALL, ok=True)
        else:
            stopped = cancel is not None and cancel.is_set()
            tracker.finish(STOPPED if stopped else FAILED_INSTALL, ok=False)
    return installed, tail


def uninstall_addon(
    on_progress: AddonProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> tuple[bool, str]:
    """Remove the add-on Audio8D installed; returns (worked, what happened).

    Uninstalling when it isn't installed changes nothing and counts as done.
    A Demucs you installed into your own Python is never touched.
    """
    tracker = Tracker(on_progress)
    folder = addon_dir()
    forget_status()
    if not folder.exists():
        status = check_singer()
        if status.ready:
            python = status.python.path
            tracker.finish(FAILED_UNINSTALL, ok=False, detail="Not Audio8D's copy")
            return False, (
                f"This copy of the add-on is in your own Python ({python}), which "
                "Audio8D didn't install, so it is left alone. To remove it yourself, "
                f'run: "{python}" -m pip uninstall demucs'
            )
        tracker.finish(DONE_UNINSTALL, ok=True, detail="There was nothing to remove")
        return True, "The add-on isn't installed; nothing was changed."
    problem = _remove_folder(folder, tracker, cancel)
    forget_status()
    if problem is None and folder.exists():
        problem = f"{folder} could not be removed completely. Try again."
    if problem:
        stopped = cancel is not None and cancel.is_set()
        tracker.finish(STOPPED if stopped else FAILED_UNINSTALL, ok=False)
        return False, problem
    tracker.finish(DONE_UNINSTALL, ok=True)
    return True, f"The add-on was removed ({folder} was deleted)."


def repair_addon(
    base: Path,
    on_line: Callable[[str], None] | None = None,
    cancel: threading.Event | None = None,
    on_progress: AddonProgressCallback | None = None,
) -> tuple[bool, str]:
    """Remove Audio8D's copy of the add-on and install it again from scratch."""
    tracker = Tracker(on_progress)
    problem = _remove_folder(
        addon_dir(), tracker.part(0.0, REPAIR_REMOVE), cancel, STAGE_REMOVE_OLD
    )
    if problem:
        stopped = cancel is not None and cancel.is_set()
        tracker.finish(STOPPED if stopped else FAILED_INSTALL, ok=False)
        return False, problem
    return _install(base, on_line, cancel, tracker.part(REPAIR_REMOVE, 0.9))


# ------------------------------------------------------------------ status

# The Python chosen in Settings (or with --python); None finds one automatically
_chosen: dict[str, Path | None] = {"python": None}
_status: dict[str, AddonStatus | None] = {"singer": None}
_lock = threading.Lock()


def set_preferred_python(path: Path | None) -> None:
    """Use this Python for the add-on from now on (None: find one automatically)."""
    with _lock:
        if _chosen["python"] != path:
            _chosen["python"] = path
            _status["singer"] = None


def preferred_python() -> Path | None:
    """The Python chosen in Settings or with --python, if any."""
    return _chosen["python"]


def check_singer(python: Path | None = None) -> AddonStatus:
    """The add-on's status: Audio8D's own copy first, else a Python of your own."""
    if addon_dir().exists():
        found = _with_source(check_python(addon_python()), "addon")
        if not found.ok or found.path is None:
            return AddonStatus(found)
        return AddonStatus(found, check_packages(found.path))
    found = find_python(python if python is not None else preferred_python())
    if not found.ok or found.path is None:
        return AddonStatus(found)
    return AddonStatus(found, check_packages(found.path))


def singer_status(refresh: bool = False) -> AddonStatus:
    """The add-on's status: remembered after the first check, unless refresh."""
    with _lock:
        known = _status["singer"]
    if known is not None and not refresh:
        return known
    status = check_singer()
    remember_status(status)
    return status


def remember_status(status: AddonStatus) -> None:
    """Keep a status checked elsewhere (e.g. by the window's start-up check)."""
    with _lock:
        _status["singer"] = status
    LOG.debug("Singer add-on: %s", status.summary())


def forget_status() -> None:
    """Check again next time (after installing, or choosing another Python)."""
    with _lock:
        _status["singer"] = None


def known_status() -> AddonStatus | None:
    """The last status, without checking (None when nothing was checked yet)."""
    with _lock:
        return _status["singer"]


def singer_python() -> Path | None:
    """The Python that runs Demucs, when the add-on is ready."""
    status = singer_status()
    return status.python.path if status.ready else None
