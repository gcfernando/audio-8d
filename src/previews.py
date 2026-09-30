# Developed by ::> Gehan Fernando
"""Makes short previews of any song on the list, one song at a time, safely.

Each preview belongs to exactly one song and one set of settings:

* its file name is a fingerprint of the song (path, size, date) and every
  setting that shapes the sound, so two songs (or two styles for one song) can
  never share or overwrite a preview, and an unchanged request is instant;
* every request gets a number; asking for another song cancels the one being
  made, and anything the cancelled one reports afterwards is ignored, so the
  preview shown always matches the song that is selected;
* previews live in a private temporary folder for this run, never next to your
  music; only the newest few are kept, a song's out-of-date preview is deleted
  as soon as a new one replaces it, everything goes when the window closes,
  and folders left by a crash are swept away on the next start.

The preview is made by the same pipeline as the real conversion (same style,
movement, room, loudness and limiter), from the loudest part of the song, with
a shorter ease-in and saved as lossless WAV so it can play inside the window.
Nothing here touches widgets; the window passes events back to its own thread.
"""

import dataclasses
import hashlib
import json
import logging
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import hints
from .core.errors import Audio8DError
from .core.settings import EffectConfig
from .core.types import Trim
from .pipeline import compare, preview

LOG = logging.getLogger(__name__)

IDLE, MAKING, READY, FAILED = "idle", "making", "ready", "failed"
_ROOT_NAME = "Audio8D previews"
# Folders from earlier runs older than this are removed at start-up
STALE_AFTER_SECONDS = 6 * 3600
# Finished previews kept for instant replays; older ones are deleted
MAX_KEPT = 4

# (kind, request number, song, payload) sent back to the window
Post = Callable[[tuple], None]


def preview_config(config: EffectConfig) -> EffectConfig:
    """The settings a preview is made with: the song's own, saved as WAV."""
    return dataclasses.replace(config, output_format="wav")


def fingerprint(
    song: Path,
    config: EffectConfig,
    seconds: float,
    kind: str,
    trim: Trim | None = None,
) -> str:
    """A name that changes whenever the song file or any sound setting changes.

    config is the song's real settings, output format included, since a WAV
    preview of an MP3 song sounds like the MP3; trim is the song's own trim.
    """
    try:
        stat = song.stat()
        identity = [str(song.resolve()), stat.st_size, stat.st_mtime_ns]
    except OSError:
        identity = [str(song), None, None]
    cut = None if trim is None else [trim.start, trim.end]
    text = json.dumps(
        [kind, identity, dataclasses.asdict(config), float(seconds), cut], default=str
    )
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:20]


@dataclass
class PreviewStatus:
    """Where one song's preview is: idle, making (with progress), ready or failed."""

    song: Path
    state: str = IDLE
    share: float = 0.0
    file: Path | None = None
    # Plain-word problem and fix, when failed
    problem: str = ""
    # The fingerprint of the settings it was (or is being) made with
    key: str = ""
    kind: str = "preview"


def _session_folder() -> Path:
    """A fresh folder for this run's previews."""
    root = Path(tempfile.gettempdir()) / _ROOT_NAME
    folder = root / f"run-{os.getpid()}-{time.time_ns()}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


@contextmanager
def temporary_folder() -> Iterator[Path]:
    """A private preview folder that is deleted afterwards, whatever happens."""
    folder = _session_folder()
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _pid_running(pid: int) -> bool:
    """True when a process with this id is running now."""
    if pid <= 0 or pid == os.getpid():
        return pid > 0
    if os.name == "nt":
        return _windows_pid_running(pid)
    try:
        os.kill(pid, 0)
    except PermissionError:
        # It exists, it just belongs to someone else
        return True
    except OSError:
        return False
    return True


def _windows_pid_running(pid: int) -> bool:
    """Windows' own answer to whether a process id is still running."""
    # pylint: disable-next=import-outside-toplevel
    import ctypes

    # WinDLL only exists on Windows, which the caller has already checked
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore
    query_limited, still_active, access_denied = 0x1000, 259, 5
    handle = kernel.OpenProcess(query_limited, False, pid)
    if not handle:
        # Access denied means it exists but is protected; anything else, it's gone
        return ctypes.get_last_error() == access_denied  # type: ignore[attr-defined]
    try:
        code = ctypes.c_ulong()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == still_active
    finally:
        kernel.CloseHandle(handle)


def _run_pid(folder: Path) -> int | None:
    """The process number in a 'run-<pid>-<time>' folder name, if it has one."""
    parts = folder.name.split("-")
    if len(parts) < 3 or parts[0] != "run" or not parts[1].isdigit():
        return None
    return int(parts[1])


def _owner_running(folder: Path) -> bool:
    """True when the run that made this 'run-<pid>-<time>' folder is still open."""
    pid = _run_pid(folder)
    return pid is not None and _pid_running(pid)


def sweep_old_folders(root: Path | None = None, keep: Path | None = None) -> int:
    """Delete preview folders from earlier runs; returns how many went."""
    base = root or Path(tempfile.gettempdir()) / _ROOT_NAME
    removed = 0
    if not base.is_dir():
        return 0
    now = time.time()
    for folder in base.iterdir():
        if folder == keep or not folder.is_dir():
            continue
        # Another window that is still open keeps its previews, however old
        if _owner_running(folder):
            continue
        try:
            old = now - folder.stat().st_mtime > STALE_AFTER_SECONDS
        except OSError:
            continue
        # A run that has ended (closed, or killed) has no use for its previews
        if old or _run_pid(folder) is not None:
            shutil.rmtree(folder, ignore_errors=True)
            removed += not folder.exists()
    return removed


def explain(error: BaseException) -> str:
    """A failure in plain words with what to do, never a raw stack or FFmpeg log."""
    message = hints.short_message(error)
    if isinstance(error, Audio8DError):
        fix = hints.fix_for(error)
        if fix:
            message += f" What to do: {fix}"
    else:
        message = "Something unexpected went wrong; the details are in the log."
    return message


def _delete(file: Path) -> None:
    """Remove one preview file; one still open in a player goes when the run ends."""
    try:
        file.unlink(missing_ok=True)
    except OSError as exc:
        LOG.debug("Preview %s is still in use: %s", file.name, exc)


def make_preview(  # pylint: disable=too-many-arguments
    song: Path,
    folder: Path,
    config: EffectConfig,
    *,
    seconds: float = 30.0,
    kind: str = "preview",
    on_progress: Callable[[str, float], None] | None = None,
    cancel: threading.Event | None = None,
    trim: Trim | None = None,
) -> Path:
    """Make one preview (or A/B file) inside a temporary folder and return it.

    The command line uses this directly; the window goes through PreviewManager.
    trim is the song's own start and end. A failed or stopped preview leaves
    no file behind.
    """
    key = fingerprint(song, config, seconds, kind, trim)
    file = folder / (f"{key}.wav" if kind == "preview" else f"{key}.mp3")
    try:
        if kind == "preview":
            preview(
                song,
                file,
                preview_config(config),
                seconds=seconds,
                on_progress=on_progress,
                cancel=cancel,
                trim=trim,
                render_as=config.output_format,
            )
        else:
            compare(
                song, file, config, on_progress=on_progress, cancel=cancel, trim=trim
            )
    except BaseException:
        _delete(file)
        raise
    return file


class PreviewManager:
    """Keeps every song's preview status and makes one preview at a time."""

    def __init__(
        self,
        post: Post,
        folder: Path | None = None,
        render: Callable[..., object] = preview,
        make_compare: Callable[..., object] = compare,
    ) -> None:
        """post(event) hands progress back to the window (from any thread)."""
        self.post = post
        self.folder = folder or _session_folder()
        self._render = render
        self._compare = make_compare
        self.status: dict[Path, PreviewStatus] = {}
        self._counter = 0
        # (request number, song, cancel switch) of the preview being made
        self._active: tuple[int, Path, threading.Event] | None = None
        self._lock = threading.Lock()
        sweep_old_folders(self.folder.parent, keep=self.folder)

    # ------------------------------------------------------------ asking

    @property
    def busy(self) -> bool:
        """True while a preview is being made."""
        return self._active is not None

    @property
    def making(self) -> Path | None:
        """The song whose preview is being made, if any."""
        return self._active[1] if self._active else None

    def status_of(self, song: Path) -> PreviewStatus:
        """The song's preview status (idle when it has none)."""
        return self.status.get(song) or PreviewStatus(song)

    def is_current(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        song: Path,
        config: EffectConfig,
        seconds: float,
        kind: str = "preview",
        trim: Trim | None = None,
    ) -> bool:
        """True when the song's ready preview was made with exactly these settings."""
        found = self.status.get(song)
        return (
            found is not None
            and found.state == READY
            and found.kind == kind
            and found.key == fingerprint(song, config, seconds, kind, trim)
            and found.file is not None
            and found.file.is_file()
        )

    # ------------------------------------------------------------ making

    def start(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        song: Path,
        config: EffectConfig,
        seconds: float,
        kind: str = "preview",
        trim: Trim | None = None,
    ) -> int | None:
        """Make a preview (or A/B file) of one song; None when it is already ready.

        config is the song's real settings and trim its own start and end.
        Anything still being made for another request is cancelled first.
        """
        key = fingerprint(song, config, seconds, kind, trim)
        file = self.folder / (f"{key}.wav" if kind == "preview" else f"{key}.mp3")
        self.cancel()
        old = self.status.get(song)
        if old is not None and old.file is not None and old.file != file:
            # This song's older preview is out of date now, so it goes at once
            _delete(old.file)
        if file.is_file():
            self.status[song] = PreviewStatus(
                song, READY, 1.0, file, key=key, kind=kind
            )
            self.post(("preview", 0, song, "ready", file))
            return None
        with self._lock:
            self._counter += 1
            number = self._counter
            cancel = threading.Event()
            self._active = (number, song, cancel)
        self.status[song] = PreviewStatus(song, MAKING, 0.0, key=key, kind=kind)
        threading.Thread(
            target=self._work,
            args=(number, song, config, seconds, kind, file, cancel, trim),
            name=f"preview-{number}",
            daemon=True,
        ).start()
        return number

    def _work(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        number: int,
        song: Path,
        config: EffectConfig,
        seconds: float,
        kind: str,
        file: Path,
        cancel: threading.Event,
        trim: Trim | None = None,
    ) -> None:
        """Make the file on a helper thread and report back."""

        def progress(_stage: str, share: float) -> None:
            self.post(("preview", number, song, "progress", share))

        try:
            if kind == "preview":
                # Saved as WAV to play in the window, but made as the real format
                self._render(
                    song,
                    file,
                    preview_config(config),
                    seconds=seconds,
                    on_progress=progress,
                    cancel=cancel,
                    trim=trim,
                    render_as=config.output_format,
                )
            else:
                self._compare(
                    song, file, config, on_progress=progress, cancel=cancel, trim=trim
                )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            if cancel.is_set():
                self.post(("preview", number, song, "cancelled", None))
            else:
                if not isinstance(exc, Audio8DError):
                    LOG.exception("Preview of %s failed unexpectedly", song)
                else:
                    LOG.warning("Preview of %s failed: %s", song, exc)
                self.post(("preview", number, song, "failed", explain(exc)))
            self._delete_unclaimed(number, song, file)
            return
        if cancel.is_set():
            self._delete_unclaimed(number, song, file)
            self.post(("preview", number, song, "cancelled", None))
            return
        self.post(("preview", number, song, "ready", file))

    def _delete_unclaimed(self, number: int, song: Path, file: Path) -> None:
        """Delete a stopped request's file, unless a newer request now owns it.

        The same song and settings always give the same file name, so a late
        cancelled request must never remove the preview a newer one just made.
        """
        active = self._active
        found = self.status.get(song)
        if found is not None and found.key == file.stem:
            newer = active is not None and active[0] != number and active[1] == song
            if newer or found.state == READY:
                return
        _delete(file)

    def handle(self, event: tuple) -> bool:
        """Apply one reported event; False when it belongs to an old request."""
        _kind, number, song, what, payload = event
        active = self._active
        # Instant (already made) answers carry number 0 and are always current
        if number and (active is None or active[0] != number):
            return False
        status = self.status.setdefault(song, PreviewStatus(song))
        if what == "progress":
            status.state, status.share = MAKING, float(payload)
        elif what == "ready":
            status.state, status.share, status.file = READY, 1.0, payload
            status.problem = ""
            self._keep_newest(song)
        elif what == "failed":
            status.state, status.problem, status.file = FAILED, str(payload), None
        elif what == "cancelled":
            status.state, status.share = IDLE, 0.0
        if what in ("ready", "failed", "cancelled") and number:
            self._active = None
        return True

    def cancel(self) -> None:
        """Stop the preview being made (its status goes back to idle)."""
        with self._lock:
            active, self._active = self._active, None
        if active is not None:
            active[2].set()
            found = self.status.get(active[1])
            if found is not None and found.state == MAKING:
                found.state, found.share = IDLE, 0.0

    def _keep_newest(self, newest: Path) -> None:
        """Delete finished previews beyond the newest few (newest last in status)."""
        # Moving the newest to the end keeps status in least-recently-made order
        self.status[newest] = self.status.pop(newest)
        ready = [s for s in self.status.values() if s.state == READY and s.file]
        for old in ready[: max(0, len(ready) - MAX_KEPT)]:
            if old.file is not None:
                _delete(old.file)
            self.status.pop(old.song, None)

    def forget(self, song: Path) -> None:
        """A song left the list: drop its status and delete its preview."""
        if self.making == song:
            self.cancel()
        found = self.status.pop(song, None)
        if found is not None and found.file is not None:
            _delete(found.file)

    def close(self) -> None:
        """Cancel any work and delete this run's previews."""
        self.cancel()
        shutil.rmtree(self.folder, ignore_errors=True)
