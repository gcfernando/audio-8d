# Developed by ::> Gehan Fernando
"""The technical log file, and hooks that record any crash before it is lost."""

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .core.locations import log_file

LOG = logging.getLogger("audio8d")

_FORMAT = "%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s"


def start_log_file() -> Path | None:
    """Write DEBUG and up to the log file; None when the file can't be opened."""
    root = logging.getLogger()
    for handler in root.handlers:
        if getattr(handler, "audio8d_file", False):
            return Path(handler.baseFilename)  # type: ignore[attr-defined]
    path = log_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path, maxBytes=1_000_000, backupCount=2, encoding="utf-8", delay=True
        )
    except OSError:
        # A read-only or missing profile folder must never stop the app itself
        return None
    handler.audio8d_file = True  # type: ignore[attr-defined]
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
    if root.level > logging.INFO:
        root.setLevel(logging.INFO)
    _catch_crashes()
    return path


def _catch_crashes() -> None:
    """Log errors nobody caught, on the main thread and on helper threads."""
    # Each hook passes the error on, so other tools' hooks keep working too
    if not getattr(sys.excepthook, "audio8d", False):
        previous = sys.excepthook

        def on_crash(kind, error, trace) -> None:  # type: ignore[no-untyped-def]
            if not issubclass(kind, KeyboardInterrupt):
                LOG.critical("Unexpected error", exc_info=(kind, error, trace))
            previous(kind, error, trace)

        on_crash.audio8d = True  # type: ignore[attr-defined]
        sys.excepthook = on_crash

    if not getattr(threading.excepthook, "audio8d", False):
        previous_thread_hook = threading.excepthook

        def on_thread_crash(args: threading.ExceptHookArgs) -> None:
            where = args.thread.name if args.thread else "a helper thread"
            LOG.critical("Unexpected error in %s", where, exc_info=args.exc_value)
            previous_thread_hook(args)

        on_thread_crash.audio8d = True  # type: ignore[attr-defined]
        threading.excepthook = on_thread_crash


def log_files() -> list[Path]:
    """The saved log and its older, rotated copies (only those that exist)."""
    path = log_file()
    candidates = [path] + [path.with_name(f"{path.name}.{n}") for n in (1, 2, 3)]
    return [candidate for candidate in candidates if candidate.is_file()]


def delete_log_files() -> tuple[int, list[Path]]:
    """Delete the saved logs; (how many were deleted, the ones that couldn't be).

    The open log is closed first (Windows won't delete an open file); the next
    log line simply starts a fresh file.
    """
    handlers = [
        handler
        for handler in logging.getLogger().handlers
        if getattr(handler, "audio8d_file", False)
    ]
    deleted, failed = 0, []
    for handler in handlers:
        handler.acquire()
    try:
        for handler in handlers:
            stream = getattr(handler, "stream", None)
            if stream is not None:
                stream.close()
                handler.stream = None  # type: ignore[attr-defined]
        for path in log_files():
            try:
                path.unlink()
                deleted += 1
            except OSError:
                failed.append(path)
    finally:
        for handler in handlers:
            handler.release()
    if deleted:
        LOG.info("Saved log files deleted by the user")
    return deleted, failed
