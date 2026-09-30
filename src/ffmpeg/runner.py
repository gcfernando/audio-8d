# Developed by ::> Gehan Fernando
"""Runs external tools safely and turns failures into Audio8D errors.

Every program started here is kept in a list of live processes until it ends,
so closing the window (or Ctrl+C) can stop them all with kill_all_processes()
instead of leaving FFmpeg or Demucs running in the background.
"""

import os
import queue
import subprocess
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar

from ..core.errors import Audio8DError, ConversionError

ErrorT = TypeVar("ErrorT", bound=Audio8DError)

# Stops a black console flashing up for every FFmpeg run when the window is used
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

# How often a running tool checks whether it was asked to stop, in seconds
POLL_SECONDS = 0.25
CANCELLED = "Conversion cancelled by user"

# Called with the share of the work done so far, from 0.0 to 1.0
ProgressCallback = Callable[[float], None]

_live: set[subprocess.Popen] = set()
_live_lock = threading.Lock()


def start_process(command: Sequence[str], **options: Any) -> subprocess.Popen:
    """Start a program without a shell and remember it until forget_process."""
    options.setdefault("stdin", subprocess.DEVNULL)
    options.setdefault("creationflags", NO_WINDOW)
    # shell=False means a song's file name can never be run as a shell command
    process = subprocess.Popen(  # pylint: disable=consider-using-with
        list(command), shell=False, **options
    )
    with _live_lock:
        _live.add(process)
    return process


def forget_process(process: subprocess.Popen) -> None:
    """The program has ended (or been stopped), so stop tracking it."""
    with _live_lock:
        _live.discard(process)


def stop_process(process: subprocess.Popen) -> None:
    """Kill a program and wait for it, ignoring one that has already gone."""
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


@contextmanager
def owned(process: subprocess.Popen) -> Iterator[subprocess.Popen]:
    """Track a started program until the block ends; any error or Ctrl+C kills it."""
    try:
        yield process
    except BaseException:
        # Cancel, a timeout or Ctrl+C: never leave the tool running on its own
        stop_process(process)
        raise
    finally:
        forget_process(process)


def live_processes() -> int:
    """How many programs started here are still being tracked."""
    with _live_lock:
        return len(_live)


def kill_all_processes() -> int:
    """Kill every program still running; returns how many were stopped.

    The window calls this when it closes, so nothing keeps working unseen.
    """
    with _live_lock:
        running = list(_live)
    stopped = 0
    for process in running:
        if process.poll() is not None:
            continue
        try:
            process.kill()
            stopped += 1
        except OSError:
            # It ended between the check and the kill, which is just as good
            pass
    return stopped


def _check_cancel(cancel: threading.Event | None) -> None:
    """Raise the usual 'cancelled' error once the stop switch is on."""
    if cancel is not None and cancel.is_set():
        raise ConversionError(CANCELLED)


def _communicate(  # pylint: disable=too-many-arguments
    command: Sequence[str],
    *,
    text: bool,
    keep_stdout: bool = True,
    timeout: float | None = None,
    cancel: threading.Event | None = None,
) -> subprocess.CompletedProcess:
    """Run a tool to the end and collect its output, stoppable with cancel.

    Raises OSError when it can't start, TimeoutExpired when it runs too long,
    and ConversionError when cancel is set while it runs.
    """
    _check_cancel(cancel)
    wording: dict[str, Any] = (
        {"text": True, "encoding": "utf-8", "errors": "replace"} if text else {}
    )
    process = start_process(
        command,
        stdout=subprocess.PIPE if keep_stdout else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        **wording,
    )
    deadline = None if timeout is None else time.monotonic() + timeout
    with owned(process):
        while True:
            wait = POLL_SECONDS
            if deadline is not None:
                wait = max(0.0, min(wait, deadline - time.monotonic()))
            try:
                # Asking again after a timeout never loses output, so poll in steps
                stdout, stderr = process.communicate(timeout=wait)
                break
            except subprocess.TimeoutExpired as step:
                _check_cancel(cancel)
                if deadline is not None and time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(
                        list(command), timeout or 0.0
                    ) from step
    empty = "" if text else b""
    return subprocess.CompletedProcess(
        list(command), process.returncode, stdout or empty, stderr or empty
    )


def run_tool(
    command: Sequence[str],
    *,
    keep_stdout: bool = True,
    timeout: float | None = None,
    cancel: threading.Event | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a tool without a shell and return its text output, whatever its exit code.

    With a timeout, a tool that hangs is stopped and TimeoutExpired is raised;
    with cancel, setting it stops the tool and raises ConversionError.
    """
    return _communicate(
        command, text=True, keep_stdout=keep_stdout, timeout=timeout, cancel=cancel
    )


def run_capture(
    command: Sequence[str],
    *,
    error_type: type[ErrorT],
    timeout: float | None = None,
    cancel: threading.Event | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command without a shell and return its captured text output."""
    try:
        result = run_tool(command, timeout=timeout, cancel=cancel)
    except OSError as exc:
        raise error_type(f"Failed to start {command[0]!r}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise error_type(
            f"{Path(command[0]).name} took longer than {timeout:g} seconds and was "
            "stopped"
        ) from exc

    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise error_type(
            f"Command failed with exit code {result.returncode}: {details}"
        )

    return result


def run_binary(
    command: Sequence[str],
    *,
    error_type: type[ErrorT],
    cancel: threading.Event | None = None,
) -> bytes:
    """Run a tool and return its raw stdout bytes (for decoded audio samples)."""
    try:
        result = _communicate(command, text=False, cancel=cancel)
    except OSError as exc:
        raise error_type(f"Failed to start {command[0]!r}: {exc}") from exc
    if result.returncode != 0:
        details = result.stderr.decode("utf-8", "replace").strip() or "unknown error"
        raise error_type(
            f"Command failed with exit code {result.returncode}: {details}"
        )
    return result.stdout


def _progress_value(line: str, duration: float) -> float | None:
    """The share done, from one `-progress` line such as 'out_time_us=1234567'."""
    key, _, value = line.strip().partition("=")
    if key not in {"out_time_us", "out_time_ms"} or not value.lstrip("-").isdigit():
        return None
    # Despite its name, out_time_ms is in microseconds too
    seconds = int(value) / 1_000_000
    return max(0.0, min(1.0, seconds / duration))


def _pump(stream: Any, sink: Callable[[Any], None]) -> threading.Thread:
    """Read a pipe to its end on a helper thread, handing on each line."""

    def read() -> None:
        """Pass every line on, then None once the pipe closes."""
        try:
            for line in stream:
                sink(line)
        except (OSError, ValueError):
            # The pipe was closed under us because the tool was stopped
            pass
        finally:
            sink(None)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    return reader


def _follow(
    process: subprocess.Popen,
    lines: "queue.Queue[str | None]",
    duration: float | None,
    on_progress: ProgressCallback | None,
    cancel: threading.Event | None,
) -> None:
    """Report progress lines until FFmpeg ends, stopping it once cancel is set."""
    while True:
        # Waiting in short steps notices cancel even when FFmpeg goes quiet
        if cancel is not None and cancel.is_set():
            stop_process(process)
            return
        try:
            line = lines.get(timeout=POLL_SECONDS)
        except queue.Empty:
            continue
        if line is None:
            return
        if on_progress is not None and duration:
            share = _progress_value(line, duration)
            if share is not None:
                on_progress(share)


def run_ffmpeg(
    command: Sequence[str],
    *,
    duration: float | None,
    on_progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run FFmpeg, reporting progress as it goes; the command gets -progress added.

    Returns the finished process (stdout is empty; stderr holds FFmpeg's log).
    """
    if on_progress is None and cancel is None:
        try:
            return run_tool(command, keep_stdout=False)
        except OSError as exc:
            raise ConversionError(f"Failed to start {command[0]!r}: {exc}") from exc

    _check_cancel(cancel)
    # -progress writes "key=value" lines to stdout, which we read as they arrive
    full = [command[0], "-progress", "pipe:1", "-nostats", *command[1:]]
    try:
        process = start_process(
            full,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise ConversionError(f"Failed to start {command[0]!r}: {exc}") from exc
    # Both pipes are read on helper threads, so a chatty FFmpeg never fills one
    log: list[str] = []
    lines: queue.Queue[str | None] = queue.Queue()
    readers = [
        _pump(process.stderr, lambda line: log.append(line) if line else None),
        _pump(process.stdout, lines.put),
    ]
    try:
        with owned(process):
            _follow(process, lines, duration, on_progress, cancel)
            process.wait()
    finally:
        for reader in readers:
            reader.join(timeout=5)
    _check_cancel(cancel)
    if on_progress is not None and process.returncode == 0:
        on_progress(1.0)
    return subprocess.CompletedProcess(full, process.returncode, "", "".join(log))
