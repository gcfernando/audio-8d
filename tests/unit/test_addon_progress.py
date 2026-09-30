# Developed by ::> Gehan Fernando
"""Add-on install, repair and uninstall report real progress, never invented numbers.

Nothing is downloaded: pip's output is replayed by a stand-in, line by line.
"""

# pytest hands fixtures to tests by name, which pylint sees as shadowing
# pylint: disable=redefined-outer-name,protected-access

import json
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from src import addons, cli
from src.addon_progress import (
    DOWNLOAD_DONE,
    PLAN_DONE,
    PipWatcher,
    Tracker,
)
from src.addons import AddonProgress, AddonStatus, PackageCheck, PythonCheck
from src.core.locations import addon_dir

BASE = Path(sys.executable)

# What pip 25 prints for a small install with --progress-bar raw
PIP_OUTPUT = [
    "Collecting demucs",
    "  Downloading demucs-4.0.1.tar.gz.metadata (3 kB)",
    "  Downloading demucs-4.0.1-py3-none-any.whl (1.2 MB)",
    "Progress 0 of 1200000",
    "Progress 600000 of 1200000",
    "Progress 1200000 of 1200000",
    "Collecting torch",
    "  Downloading torch-2.4.0-cp312-cp312-win_amd64.whl (200.0 MB)",
    "Progress 0 of 200000000",
    "Progress 50000000 of 200000000",
    "Progress 150000000 of 200000000",
    "Progress 200000000 of 200000000",
    "Collecting numpy",
    "  Using cached numpy-2.1.0-cp312-cp312-win_amd64.whl (12.6 MB)",
    "Installing collected packages: numpy, torch, demucs",
    "Successfully installed demucs-4.0.1 numpy-2.1.0 torch-2.4.0",
]


def _status(ready: bool) -> AddonStatus:
    """A made-up add-on check: every package there, or Demucs missing."""
    python = PythonCheck(BASE, True, "addon", "3.12.1")
    return AddonStatus(
        python,
        tuple(
            PackageCheck(package, ready, problem="" if ready else "not installed")
            for package in addons.SINGER_PACKAGES
        ),
    )


class FakePip:
    """Stands in for venv and pip, replaying real-looking pip output."""

    def __init__(self) -> None:
        """Every step works and three files are planned, until told otherwise."""
        self.commands: list[list[str]] = []
        self.lines = list(PIP_OUTPUT)
        self.pip_works = True
        self.ready_after = True
        self.stop_at: str | None = None
        self.venv_works = True
        self.interrupt = False

    def run(self, command, on_line=None, cancel=None):
        """Make the folder for venv; for pip, print each line and 'install'."""
        self.commands.append(list(command))
        if command[1:3] == ["-m", "venv"]:
            if not self.venv_works:
                return False, "Error: venv could not be made"
            python = addons.addon_python(Path(command[3]))
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("fake python", encoding="utf-8")
            return True, ""
        if self.interrupt:
            raise KeyboardInterrupt
        for line in self.lines:
            if cancel is not None and cancel.is_set():
                return False, "Stopped before it finished."
            if on_line is not None:
                on_line(line)
            if self.stop_at is not None and self.stop_at in line and cancel:
                cancel.set()
        if cancel is not None and cancel.is_set():
            return False, "Stopped before it finished."
        if not self.pip_works:
            return False, "ERROR: Could not install torch"
        if self.ready_after:
            (addons.addon_python().parent / "demucs.marker").write_text("x", "utf-8")
        return True, "Successfully installed demucs"

    @staticmethod
    def check(_python=None) -> AddonStatus:
        """Ready only when the fake pip really 'installed' Demucs into the folder."""
        marker = addons.addon_python().parent / "demucs.marker"
        return _status(addon_dir().exists() and marker.exists())


@pytest.fixture
def pip(monkeypatch: pytest.MonkeyPatch) -> FakePip:
    """Replace every program the add-on would run; pip is new enough for plans."""
    fake = FakePip()
    monkeypatch.setattr(addons, "_run_streamed", fake.run)
    monkeypatch.setattr(addons, "check_singer", fake.check)
    monkeypatch.setattr(addons, "_pip_version", lambda _python, _cancel: (25, 0))
    monkeypatch.setattr(addons, "_planned_files", lambda _python, _cancel: 3)
    return fake


def _record() -> tuple[list[AddonProgress], Callable[[AddonProgress], None]]:
    """A list that collects every report, and the callback that fills it."""
    reports: list[AddonProgress] = []
    return reports, reports.append


def _assert_monotonic(reports: list[AddonProgress]) -> None:
    """The known share never goes back, and a number never falls below it."""
    lasts = [report.last for report in reports]
    assert lasts == sorted(lasts)
    for report in reports:
        if report.overall is not None:
            assert report.overall == pytest.approx(report.last)


def _assert_only_final_is_complete(reports: list[AddonProgress]) -> None:
    """Only the last report may be finished, and none before it reaches 100%."""
    assert reports[-1].finished
    assert not any(report.finished for report in reports[:-1])
    assert all((report.overall or 0.0) < 1.0 for report in reports[:-1])


# ------------------------------------------------------------------ install


def test_a_successful_install_counts_up_to_100(pip: FakePip) -> None:
    reports, record = _record()
    lines: list[str] = []

    worked, _tail = addons.install_addon(BASE, lines.append, on_progress=record)

    assert worked and addons.check_singer().ready
    _assert_monotonic(reports)
    _assert_only_final_is_complete(reports)
    final = reports[-1]
    assert (final.stage, final.overall, final.failed) == (
        addons.DONE_INSTALL,
        1.0,
        False,
    )
    assert final.words() == "Installed successfully — 100%"
    stages = [report.stage for report in reports]
    for stage in (
        addons.STAGE_FOLDER,
        addons.STAGE_PLAN,
        addons.STAGE_DOWNLOAD,
        addons.STAGE_INSTALL,
        addons.STAGE_CHECK,
    ):
        assert stage in stages
    # pip was asked for exact byte counts, which never reach the visible lines
    assert "--progress-bar" in pip.commands[-1]
    assert not any(line.startswith("Progress ") for line in lines)


@pytest.mark.usefixtures("pip")
def test_download_progress_comes_from_files_and_bytes() -> None:
    reports, record = _record()
    addons.install_addon(BASE, on_progress=record)

    downloads = [
        report
        for report in reports
        if report.stage == addons.STAGE_DOWNLOAD and report.overall is not None
    ]
    shares = [round(report.overall or 0.0, 4) for report in downloads]
    span = DOWNLOAD_DONE - PLAN_DONE
    # Half of the first of three files, then a quarter of the second, and so on
    assert round(PLAN_DONE + span * (0.5 / 3), 4) in shares
    assert round(PLAN_DONE + span * (1.25 / 3), 4) in shares
    assert round(PLAN_DONE + span * (1.75 / 3), 4) in shares
    assert any("torch-2.4.0" in report.detail for report in downloads)
    assert any("(2 of 3)" in report.detail for report in downloads)
    # Resolving details (.metadata) never count as a downloaded file
    assert not any(".metadata" in report.detail for report in downloads)


def test_stages_without_a_total_are_reported_as_unmeasured(pip: FakePip) -> None:
    del pip
    reports, record = _record()
    addons.install_addon(BASE, on_progress=record)

    busy = {report.stage for report in reports if report.overall is None}
    assert {addons.STAGE_FOLDER, addons.STAGE_PLAN, addons.STAGE_INSTALL} <= busy
    installing = next(
        r for r in reports if r.stage == addons.STAGE_INSTALL and r.overall is None
    )
    # The share already done is kept while pip installs
    assert installing.last == pytest.approx(DOWNLOAD_DONE)
    assert installing.percent is None and installing.words() == "Installing packages"


def test_without_a_plan_downloading_stays_unmeasured(
    pip: FakePip, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(addons, "_planned_files", lambda _python, _cancel: None)
    reports, record = _record()

    assert addons.install_addon(BASE, on_progress=record)[0]
    downloads = [r for r in reports if r.stage == addons.STAGE_DOWNLOAD]
    assert downloads and all(report.overall is None for report in downloads)
    assert reports[-1].overall == 1.0
    del pip


def test_an_old_pip_is_never_asked_for_a_plan_or_raw_bytes(
    pip: FakePip, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(addons, "_pip_version", lambda _python, _cancel: (21, 2))
    monkeypatch.setattr(
        addons, "_planned_files", lambda *_a: pytest.fail("planned with old pip")
    )

    assert addons.install_addon(BASE)[0]
    assert "--progress-bar" not in pip.commands[-1]


def test_a_failed_install_never_shows_100(pip: FakePip) -> None:
    pip.pip_works = False
    reports, record = _record()

    worked, tail = addons.install_addon(BASE, on_progress=record)

    assert not worked and "Could not install" in tail
    assert not addon_dir().exists()
    _assert_monotonic(reports)
    _assert_only_final_is_complete(reports)
    final = reports[-1]
    assert final.failed and final.stage == addons.FAILED_INSTALL
    assert final.overall is not None and final.overall < 1.0
    assert "stopped at" in final.words()


def test_a_failed_venv_never_shows_100(pip: FakePip) -> None:
    pip.venv_works = False
    reports, record = _record()

    worked, _tail = addons.install_addon(BASE, on_progress=record)

    assert not worked and not addon_dir().exists()
    _assert_only_final_is_complete(reports)
    assert reports[-1].failed and reports[-1].last < addons.PLAN_DONE


def test_ctrl_c_during_an_install_ends_failed_not_100(pip: FakePip) -> None:
    pip.interrupt = True
    reports, record = _record()

    with pytest.raises(KeyboardInterrupt):
        addons.install_addon(BASE, on_progress=record)

    assert not addon_dir().exists()
    assert reports[-1].finished and reports[-1].failed
    assert all(report.overall != 1.0 for report in reports)


def test_installed_packages_that_fail_the_check_are_not_a_success(
    pip: FakePip,
) -> None:
    pip.ready_after = False
    reports, record = _record()

    worked, tail = addons.install_addon(BASE, on_progress=record)

    assert not worked and "The packages installed, but" in tail
    assert reports[-1].failed and reports[-1].overall != 1.0
    assert not addon_dir().exists()


def test_a_cancelled_install_stops_without_100(pip: FakePip) -> None:
    pip.stop_at = "Progress 50000000"
    cancel = threading.Event()
    reports, record = _record()

    worked, tail = addons.install_addon(BASE, cancel=cancel, on_progress=record)

    assert not worked and "Stopped" in tail
    assert not addon_dir().exists()
    _assert_only_final_is_complete(reports)
    assert reports[-1].stage == addons.STOPPED and reports[-1].failed
    assert reports[-1].last < DOWNLOAD_DONE


def test_an_installed_add_on_reports_done_at_once(pip: FakePip) -> None:
    assert addons.install_addon(BASE)[0]
    before = len(pip.commands)
    reports, record = _record()

    worked, message = addons.install_addon(BASE, on_progress=record)

    assert worked and "already installed" in message
    assert len(pip.commands) == before
    assert len(reports) == 1 and reports[0].finished and reports[0].overall == 1.0


def test_a_partly_installed_add_on_is_finished_off(pip: FakePip) -> None:
    # The folder is there but Demucs isn't, so only pip runs
    addons.addon_python().parent.mkdir(parents=True)
    addons.addon_python().write_text("fake python", encoding="utf-8")
    reports, record = _record()

    assert addons.install_addon(BASE, on_progress=record)[0]
    assert not any("venv" in command for command in pip.commands)
    assert addons.STAGE_FOLDER not in {report.stage for report in reports}
    assert reports[-1].overall == 1.0
    _assert_monotonic(reports)


@pytest.mark.usefixtures("pip")
def test_a_repair_removes_then_installs_in_one_rising_bar() -> None:
    assert addons.install_addon(BASE)[0]
    for number in range(20):
        (addon_dir() / f"old{number}.txt").write_text("x", encoding="utf-8")
    reports, record = _record()

    assert addons.repair_addon(BASE, on_progress=record)[0]
    _assert_monotonic(reports)
    _assert_only_final_is_complete(reports)
    removing = [r for r in reports if r.stage == addons.STAGE_REMOVE_OLD]
    assert removing and all(
        (r.overall or 0.0) <= addons.REPAIR_REMOVE for r in removing
    )
    assert reports[-1].stage == addons.DONE_INSTALL and reports[-1].overall == 1.0


def test_a_repair_that_cannot_remove_the_old_folder_never_shows_100(
    pip: FakePip, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert addons.install_addon(BASE)[0]
    before = len(pip.commands)

    def locked(_path: str, _is_dir: bool) -> None:
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(addons, "_delete_entry", locked)
    reports, record = _record()

    worked, _message = addons.repair_addon(BASE, on_progress=record)

    assert not worked
    # Nothing is installed over a folder that couldn't be emptied
    assert len(pip.commands) == before
    assert reports[-1].failed and all(r.overall != 1.0 for r in reports)


# ------------------------------------------------------------------ uninstall


def _installed_folder(files: int) -> Path:
    """A fake add-on folder with some files, one of them read-only."""
    folder = addon_dir()
    (folder / "Lib" / "site-packages").mkdir(parents=True)
    for number in range(files):
        (folder / "Lib" / "site-packages" / f"f{number}.py").write_text("x", "utf-8")
    locked = folder / "locked.pyd"
    locked.write_text("x", encoding="utf-8")
    locked.chmod(0o444)
    return folder


def test_uninstall_counts_files_and_reaches_100(pip: FakePip) -> None:
    del pip
    folder = _installed_folder(300)
    reports, record = _record()

    worked, message = addons.uninstall_addon(on_progress=record)

    assert worked and "removed" in message and not folder.exists()
    _assert_monotonic(reports)
    _assert_only_final_is_complete(reports)
    assert reports[0].overall is None and reports[0].detail == "Counting files"
    measured = [r for r in reports if r.stage == addons.STAGE_REMOVE and r.overall]
    # Updates are thinned out, but many real steps are shown
    assert 20 < len(measured) <= 210
    assert reports[-1].words() == "Uninstalled successfully — 100%"


def test_a_file_in_use_fails_the_uninstall_without_100(
    pip: FakePip, monkeypatch: pytest.MonkeyPatch
) -> None:
    del pip
    _installed_folder(10)
    original = addons._delete_entry
    count = [0]

    def sometimes(path: str, is_dir: bool) -> None:
        count[0] += 1
        if count[0] == 5:
            raise PermissionError(13, "Access is denied")
        original(path, is_dir)

    monkeypatch.setattr(addons, "_delete_entry", sometimes)
    reports, record = _record()

    worked, message = addons.uninstall_addon(on_progress=record)

    assert not worked and "in use or protected" in message
    assert reports[-1].failed and reports[-1].stage == addons.FAILED_UNINSTALL
    assert all(report.overall != 1.0 for report in reports)


def test_a_cancelled_uninstall_says_it_stopped(pip: FakePip) -> None:
    del pip
    _installed_folder(50)
    cancel = threading.Event()
    reports: list[AddonProgress] = []

    def record(report: AddonProgress) -> None:
        reports.append(report)
        if (report.overall or 0.0) > 0.3:
            cancel.set()

    worked, message = addons.uninstall_addon(on_progress=record, cancel=cancel)

    assert not worked and "Stopped" in message
    assert reports[-1].stage == addons.STOPPED and reports[-1].overall != 1.0


def test_uninstalling_nothing_is_a_quiet_100(pip: FakePip) -> None:
    del pip
    reports, record = _record()

    assert addons.uninstall_addon(on_progress=record)[0]
    assert len(reports) == 1 and reports[0].overall == 1.0


# ------------------------------------------------------------------ the pieces


def test_the_tracker_never_goes_back_and_keeps_100_for_success() -> None:
    reports, record = _record()
    tracker = Tracker(record)

    tracker.step("A", 0.4)
    tracker.step("A", 0.2)
    tracker.step("B", None)
    tracker.step("B", 1.0)
    tracker.finish("Done", ok=True)

    # The step back to 0.2 changes nothing, so it isn't even reported
    assert [r.overall for r in reports] == [0.4, None, 0.99, 1.0]
    assert reports[1].last == 0.4


def test_tiny_moves_are_not_reported() -> None:
    reports, record = _record()
    tracker = Tracker(record)
    for number in range(1000):
        tracker.step("Removing add-on", number / 1000)

    assert len(reports) <= 201


def test_pip_lines_are_read_as_files_and_bytes() -> None:
    reports, record = _record()
    watcher = PipWatcher(Tracker(record), planned=2)

    for line in (
        "  Downloading a-1.0.tar.gz.metadata (3 kB)",
        "  Downloading https://example.org/packages/a-1.0-py3-none-any.whl (2 MB)",
        "Progress 1000 of 2000",
        "  Using cached b-2.0-py3-none-any.whl (1 MB)",
    ):
        watcher.feed(line)

    measured = [r for r in reports if r.overall is not None]
    span = DOWNLOAD_DONE - PLAN_DONE
    assert measured[0].detail == "a-1.0-py3-none-any.whl (1 of 2)"
    assert measured[1].overall == pytest.approx(PLAN_DONE + span * 0.25)
    assert measured[-1].overall == pytest.approx(DOWNLOAD_DONE)


def test_the_plan_is_read_from_pips_report(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []
    report = {"install": [{"download_info": {"url": "x"}}] * 17}

    def fake_run(command, **_kwargs):
        seen.append(command)
        return addons.subprocess.CompletedProcess(command, 0, json.dumps(report), "")

    monkeypatch.setattr(addons, "run_tool", fake_run)
    assert addons._planned_files(BASE, None) == 17
    assert "--dry-run" in seen[0] and "--report" in seen[0]

    monkeypatch.setattr(
        addons,
        "run_tool",
        lambda command, **_k: addons.subprocess.CompletedProcess(command, 1, "", "no"),
    )
    assert addons._planned_files(BASE, None) is None


def test_the_pip_version_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        addons,
        "run_tool",
        lambda command, **_k: addons.subprocess.CompletedProcess(
            command, 0, "pip 25.0.1 from C:\\x (python 3.12)\n", ""
        ),
    )
    assert addons._pip_version(BASE, None) == (25, 0)

    def broken(*_args, **_kwargs):
        raise OSError("missing")

    monkeypatch.setattr(addons, "run_tool", broken)
    assert addons._pip_version(BASE, None) == (0, 0)


# ------------------------------------------------------------------ command line


def test_the_command_line_prints_progress_sparingly(
    pip: FakePip,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del pip
    monkeypatch.setattr(cli.addons, "find_python", lambda _p=None: _status(True).python)

    assert cli.main(["--install-addon"]) == 0
    out = capsys.readouterr().out
    assert "Downloading packages — " in out
    assert "Installed successfully — 100%" in out
    assert out.count("Installing packages\n") + out.count("Installing packages  ") == 1
    assert "Progress " not in out

    assert cli.main(["--uninstall-addon"]) == 0
    assert "Uninstalled successfully — 100%" in capsys.readouterr().out


def test_a_failed_install_on_the_command_line_never_prints_100(
    pip: FakePip,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pip.pip_works = False
    monkeypatch.setattr(cli.addons, "find_python", lambda _p=None: _status(True).python)

    assert cli.main(["--install-addon"]) != 0
    captured = capsys.readouterr()
    assert "100%" not in captured.out + captured.err
    assert "stopped at" in captured.out + captured.err
