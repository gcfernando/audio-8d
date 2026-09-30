# Developed by ::> Gehan Fernando
"""Real progress for installing, repairing and uninstalling the singer add-on.

Percentages only ever come from something measured: files and bytes pip
reports, or files removed out of files counted. A stage with no measurable
total (making the folder, resolving, pip's install step) is reported as
unmeasured, so the window shows a busy bar instead of an invented number.
"""

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass

# What each step of an install or uninstall is called, in the words people see
STAGE_FOLDER = "Making the add-on folder"
STAGE_PLAN = "Checking what to download"
STAGE_DOWNLOAD = "Downloading packages"
STAGE_INSTALL = "Installing packages"
STAGE_CHECK = "Checking the add-on"
STAGE_CLEANUP = "Cleaning up"
STAGE_REMOVE = "Removing add-on"
STAGE_REMOVE_OLD = "Removing the old add-on"
DONE_INSTALL = "Installed successfully"
DONE_UNINSTALL = "Uninstalled successfully"
FAILED_INSTALL = "Install failed"
FAILED_UNINSTALL = "Uninstall failed"
STOPPED = "Stopped"

# Where each install step ends, as a share of the whole install
FOLDER_DONE = 0.05
PLAN_DONE = 0.10
DOWNLOAD_DONE = 0.85
INSTALL_DONE = 0.95
# A repair spends this share removing the old folder before installing again
REPAIR_REMOVE = 0.10
# Smaller moves than this are not worth an update (the window redraws each one)
_MIN_STEP = 0.005

# pip learnt --dry-run --report in 22.2 and --progress-bar raw in 24.1
PIP_REPORT = (22, 2)
PIP_RAW = (24, 1)
# Resolving Demucs and PyTorch reads package details from the internet
PLAN_TIMEOUT = 600.0


@dataclass(frozen=True, slots=True)
class AddonProgress:
    """One progress report from installing, repairing or uninstalling the add-on.

    overall is the real share of the whole job done, 0.0 to 1.0, or None while
    the current stage has no measurable total (show a busy bar, not a number).
    last is the share known to be done so far, so a busy stage can still show
    it; overall never goes below it. finished marks the final report: 1.0 with
    a success stage only when the job really worked, otherwise failed is True.
    Reports may arrive on a helper thread.
    """

    stage: str
    overall: float | None
    detail: str = ""
    last: float = 0.0
    finished: bool = False
    failed: bool = False

    @property
    def percent(self) -> int | None:
        """The whole percentage done, or None for a stage that can't be measured."""
        return None if self.overall is None else int(self.overall * 100)

    def words(self) -> str:
        """'Downloading packages — 42%', or only the stage while it is unmeasured."""
        if self.failed:
            return f"{self.stage} (stopped at {int(self.last * 100)}%)"
        if self.percent is None:
            return self.stage
        return f"{self.stage} — {self.percent}%"


AddonProgressCallback = Callable[[AddonProgress], None]


class Tracker:
    """Turns each stage's own share into overall progress that never goes back."""

    def __init__(
        self,
        callback: AddonProgressCallback | None,
        start: float = 0.0,
        span: float = 1.0,
        root: "Tracker | None" = None,
    ) -> None:
        """Report to callback, mapping this part's 0-1 onto start..start+span."""
        self.callback = callback
        self.start, self.span = start, span
        self.root = root or self
        self.best = 0.0
        self.sent: AddonProgress | None = None
        self.lock = threading.Lock()

    def part(self, start: float, span: float) -> "Tracker":
        """A tracker for one piece of this job (a repair's removal, say)."""
        return Tracker(
            self.callback,
            self.start + start * self.span,
            span * self.span,
            self.root,
        )

    def step(
        self, stage: str, share: float | None, detail: str = "", force: bool = False
    ) -> None:
        """Report a stage; share is this part's own 0-1, or None when unmeasurable."""
        overall = None
        if share is not None:
            overall = self.start + self.span * max(0.0, min(1.0, share))
        self.root.send(stage, overall, detail, force)

    def send(self, stage: str, overall: float | None, detail: str, force: bool) -> None:
        """Pass one report on, keeping it monotonic and skipping tiny moves."""
        if self.callback is None:
            return
        with self.lock:
            if overall is not None:
                # Only a finished success may show 100%
                overall = min(max(overall, self.best), 0.99)
                self.best = overall
            report = AddonProgress(stage, overall, detail, self.best)
            before = self.sent
            if not force and before is not None and before.stage == stage:
                both_busy = overall is None and before.overall is None
                small = (
                    overall is not None
                    and before.overall is not None
                    and overall - before.overall < _MIN_STEP
                )
                if both_busy or small:
                    return
            self.sent = report
        self.callback(report)

    def finish(self, stage: str, ok: bool, detail: str = "") -> None:
        """The final report: 100% for a real success, else where it stopped."""
        root = self.root
        if root.callback is None:
            return
        with root.lock:
            if ok:
                root.best = 1.0
            report = AddonProgress(
                stage,
                1.0 if ok else root.best,
                detail,
                root.best,
                finished=True,
                failed=not ok,
            )
            root.sent = report
        root.callback(report)


_DOWNLOADING = re.compile(r"^\s*Downloading (\S+)")
_CACHED = re.compile(r"^\s*Using cached (\S+)")
RAW_PROGRESS = re.compile(r"^\s*Progress (\d+) of (\d+)\s*$")
_INSTALLING = re.compile(r"^\s*Installing collected packages: (.+)$")
_INSTALLED = re.compile(r"^\s*Successfully installed ")


def _file_name(location: str) -> str:
    """The file name at the end of a URL or path, without any #hash part."""
    return location.split("#", 1)[0].rstrip("/").rsplit("/", 1)[-1]


class PipWatcher:  # pylint: disable=too-few-public-methods
    """Reads pip's output and turns it into real download and install progress.

    With the number of files known beforehand, downloading counts finished
    files plus the bytes of the current one; without it, it stays unmeasured.
    """

    def __init__(self, tracker: Tracker, planned: int | None) -> None:
        """Nothing downloaded yet; planned is how many files pip will fetch."""
        self.tracker = tracker
        self.planned = planned
        self.done = 0
        self.current = ""
        self.current_share = 0.0

    def _download_share(self) -> float | None:
        """The share of the download stage done, or None when the total is unknown."""
        if self.planned is None:
            return None
        if self.planned == 0:
            return 1.0
        return min(1.0, (self.done + self.current_share) / self.planned)

    def _report_download(self, force: bool) -> None:
        """Report the download stage, mapped between its start and end."""
        share = self._download_share()
        overall = None
        if share is not None:
            overall = PLAN_DONE + (DOWNLOAD_DONE - PLAN_DONE) * share
        detail = self.current
        if self.planned and self.current:
            number = min(self.planned, self.done + 1)
            detail = f"{self.current} ({number} of {self.planned})"
        elif self.planned:
            detail = f"{min(self.done, self.planned)} of {self.planned} files"
        self.tracker.step(STAGE_DOWNLOAD, overall, detail, force)

    def _finish_file(self) -> None:
        """The file being downloaded is complete."""
        if self.current:
            self.done += 1
            self.current, self.current_share = "", 0.0

    def feed(self, line: str) -> None:
        """Read one line pip printed."""
        raw = RAW_PROGRESS.match(line)
        if raw is not None:
            current, total = int(raw.group(1)), int(raw.group(2))
            if self.current and total > 0:
                self.current_share = min(1.0, current / total)
                self._report_download(False)
            return
        for pattern, cached in ((_DOWNLOADING, False), (_CACHED, True)):
            found = pattern.match(line)
            if found is None:
                continue
            name = _file_name(found.group(1))
            # Package details fetched while resolving are not package files
            if name.endswith(".metadata"):
                return
            self._finish_file()
            self.current = name
            if cached:
                self.current_share = 1.0
                self._report_download(True)
                self._finish_file()
            else:
                self._report_download(True)
            return
        installing = _INSTALLING.match(line)
        if installing is not None:
            self._finish_file()
            if self.planned is not None:
                self.done = self.planned
            count = len(installing.group(1).split(","))
            if self.planned is not None:
                self._report_download(True)
            # pip doesn't say how far through installing it is, so this is unmeasured
            self.tracker.step(STAGE_INSTALL, None, f"{count} packages", force=True)
        elif _INSTALLED.match(line):
            self.tracker.step(STAGE_INSTALL, INSTALL_DONE, force=True)
