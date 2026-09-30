# Developed by ::> Gehan Fernando
"""The singer add-on's private folder: installing, repairing and uninstalling it.

Nothing is downloaded and pip never runs: the commands Audio8D would run are
recorded by a stand-in that makes (or refuses to make) the folder instead.
"""

# pytest hands fixtures to tests by name, which pylint sees as shadowing
# pylint: disable=redefined-outer-name

import os
import stat
import sys
import threading
from pathlib import Path

import pytest

from src import addons, cli
from src.addons import AddonStatus, PackageCheck, PythonCheck
from src.core.locations import addon_dir


def _status(ready: bool, source: str = "addon", python_ok: bool = True) -> AddonStatus:
    """A made-up add-on check: every package there, or Demucs missing."""
    python = PythonCheck(Path(sys.executable), python_ok, source, "3.12.1")
    if not python_ok:
        return AddonStatus(python)
    packages = tuple(
        PackageCheck(package, ready, problem="" if ready else "not installed")
        for package in addons.SINGER_PACKAGES
    )
    return AddonStatus(python, packages)


class FakeTools:
    """Stands in for `python -m venv` and `pip install`, and for the status check."""

    def __init__(self) -> None:
        """Every step works until told otherwise."""
        self.commands: list[list[str]] = []
        self.venv_works = True
        self.pip_works = True
        self.pip_cancels = False
        self.pip_interrupts = False

    def run(self, command, on_line=None, cancel=None):
        """Record the command and pretend to run it."""
        self.commands.append(list(command))
        if on_line is not None:
            on_line(f"running {Path(command[0]).name}")
        if command[1:3] == ["-m", "venv"]:
            if not self.venv_works:
                # A failed venv can leave a half-made folder behind
                Path(command[3]).mkdir(parents=True, exist_ok=True)
                return False, "Error: venv failed"
            python = addons.addon_python(Path(command[3]))
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("fake python", encoding="utf-8")
            return True, ""
        if self.pip_interrupts:
            raise KeyboardInterrupt
        if self.pip_cancels or (cancel is not None and cancel.is_set()):
            return False, "Stopped before it finished."
        if not self.pip_works:
            return False, "ERROR: Could not install demucs"
        (addons.addon_python().parent / "demucs.marker").write_text("x", "utf-8")
        return True, "Successfully installed demucs"

    @staticmethod
    def check(_python=None) -> AddonStatus:
        """Ready only when the fake pip really 'installed' Demucs into the folder."""
        marker = addons.addon_python().parent / "demucs.marker"
        if addon_dir().exists():
            return _status(marker.exists())
        return _status(False, source="running")

    @property
    def pips(self) -> list[list[str]]:
        """Only the pip commands."""
        return [c for c in self.commands if "pip" in c]


@pytest.fixture
def tools(monkeypatch: pytest.MonkeyPatch) -> FakeTools:
    """Replace every program the add-on would run."""
    fake = FakeTools()
    monkeypatch.setattr(addons, "_run_streamed", fake.run)
    monkeypatch.setattr(addons, "check_singer", fake.check)
    # An old pip: no dry-run plan, so nothing else is ever started
    monkeypatch.setattr(addons, "_pip_version", lambda _python, _cancel: (0, 0))
    return fake


BASE = Path(sys.executable)


# ------------------------------------------------------------------ where it lives


def test_the_add_on_lives_in_audio8d_home(_private_home: Path) -> None:
    assert addon_dir() == _private_home / "addon"
    python = addons.addon_python()
    assert python.is_relative_to(addon_dir())
    assert python.name == ("python.exe" if os.name == "nt" else "python")
    assert addons.addon_python(Path("X")) == Path("X") / python.relative_to(addon_dir())


def test_the_add_on_is_described_in_four_plain_parts() -> None:
    titles = [title for title, _text in addons.ADDON_INFO]
    assert titles == ["What it does", "Benefits", "Changes to your computer", "Removal"]
    assert all(text.strip() for _title, text in addons.ADDON_INFO)


# ------------------------------------------------------------------ status


def test_its_own_folder_is_checked_before_any_other_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked: list[Path] = []

    def check_python(path, source="configured"):
        checked.append(path)
        return PythonCheck(path, True, source, "3.12.1")

    monkeypatch.setattr(addons, "check_python", check_python)
    monkeypatch.setattr(addons, "check_packages", lambda _p: _status(True).packages)
    monkeypatch.setattr(
        addons, "find_python", lambda _p=None: pytest.fail("looked elsewhere")
    )
    addons.addon_python().parent.mkdir(parents=True)

    status = addons.check_singer()
    assert checked == [addons.addon_python()]
    assert status.ready and status.private and status.python.source == "addon"
    assert status.words == "Installed"


def test_without_its_folder_a_python_of_your_own_is_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mine = PythonCheck(Path(sys.executable), True, "path", "3.12.1")
    monkeypatch.setattr(addons, "find_python", lambda _p=None: mine)
    monkeypatch.setattr(addons, "check_packages", lambda _p: _status(True).packages)

    status = addons.check_singer()
    assert status.ready and not status.private and status.python.source == "path"


def test_status_words_summary_and_fix_agree() -> None:
    ready = _status(True)
    assert ready.words == "Installed" and "can be used" in ready.summary()
    assert "--vocals center" in ready.fix()

    broken_own = _status(False, source="addon")
    assert broken_own.words == "Needs repair"
    assert "damaged" in broken_own.summary() and "demucs" in broken_own.summary()
    assert "--repair-addon" in broken_own.fix()

    # Its own Python gone: still Audio8D's copy, so repair (never "install Python")
    no_python = _status(False, source="addon", python_ok=False)
    assert no_python.words == "Needs repair" and "Python" in no_python.summary()
    assert "--repair-addon" in no_python.fix()

    absent = _status(False, source="running")
    # The badge says the state; the sentence adds what it means, without repeating it
    assert absent.words == "Not installed"
    assert "works fully without it" in absent.summary()
    assert "--install-addon" in absent.fix()

    no_python_at_all = _status(False, source="missing", python_ok=False)
    assert no_python_at_all.words == "Not installed"
    assert "python.org" in no_python_at_all.fix()


# ------------------------------------------------------------------ install


def test_installing_makes_the_folder_then_installs_into_it(tools: FakeTools) -> None:
    lines: list[str] = []
    worked, tail = addons.install_addon(BASE, lines.append)

    assert worked and "Successfully installed" in tail
    venv, pip = tools.commands
    assert venv == [str(BASE), "-m", "venv", str(addon_dir())]
    # pip runs in the private Python, never the one that made the folder
    assert pip[0] == str(addons.addon_python()) and pip[1:4] == ["-m", "pip", "install"]
    assert any("Making the add-on folder" in line for line in lines)
    assert addons.check_singer().ready


def test_installing_again_changes_nothing(tools: FakeTools) -> None:
    assert addons.install_addon(BASE)[0]
    before = len(tools.commands)

    worked, message = addons.install_addon(BASE)
    assert worked and "already installed" in message
    assert len(tools.commands) == before


def test_a_failed_venv_leaves_no_folder(tools: FakeTools) -> None:
    tools.venv_works = False
    worked, tail = addons.install_addon(BASE)

    assert not worked and "venv failed" in tail
    assert not addon_dir().exists()
    assert not tools.pips


def test_a_failed_install_leaves_no_half_made_folder(tools: FakeTools) -> None:
    tools.pip_works = False
    worked, tail = addons.install_addon(BASE)

    assert not worked and "Could not install" in tail
    assert not addon_dir().exists()
    # The next try starts clean and works
    tools.pip_works = True
    assert addons.install_addon(BASE)[0] and addons.check_singer().ready


def test_a_stopped_install_leaves_no_half_made_folder(tools: FakeTools) -> None:
    del tools
    cancel = threading.Event()
    cancel.set()
    worked, tail = addons.install_addon(BASE, cancel=cancel)

    assert not worked and "Stopped" in tail
    assert not addon_dir().exists()


def test_ctrl_c_during_install_leaves_no_half_made_folder(
    tools: FakeTools, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools.pip_interrupts = True
    monkeypatch.setattr(cli.addons, "find_python", lambda _p=None: _status(True).python)

    assert cli.main(["--install-addon"]) == 1
    assert not addon_dir().exists()


def test_a_real_command_can_be_stopped_part_way() -> None:
    script = (
        "import time\n"
        "for i in range(200):\n"
        "    print(i, flush=True)\n"
        "    time.sleep(0.05)"
    )
    cancel = threading.Event()
    lines: list[str] = []

    def on_line(line: str) -> None:
        lines.append(line)
        if len(lines) == 2:
            cancel.set()

    worked, tail = addons._run_streamed(  # pylint: disable=protected-access
        [sys.executable, "-c", script], on_line, cancel
    )
    assert not worked and tail == "Stopped before it finished."
    assert lines == ["0", "1"]


def test_a_program_that_cannot_start_is_explained(tmp_path: Path) -> None:
    worked, tail = addons._run_streamed(  # pylint: disable=protected-access
        [str(tmp_path / "missing.exe"), "-m", "pip"]
    )
    assert not worked and "could not be started" in tail


# ------------------------------------------------------------------ uninstall


def test_uninstalling_removes_the_whole_folder(tools: FakeTools) -> None:
    del tools
    assert addons.install_addon(BASE)[0]
    # Windows marks some files read-only; they must go too
    locked = addon_dir() / "locked.pyd"
    locked.write_text("x", encoding="utf-8")
    locked.chmod(stat.S_IREAD)

    worked, message = addons.uninstall_addon()
    assert worked and "removed" in message
    assert not addon_dir().exists()
    assert not addons.check_singer().ready


def test_uninstalling_when_not_installed_is_a_quiet_success(tools: FakeTools) -> None:
    worked, message = addons.uninstall_addon()

    assert worked and "nothing was changed" in message
    assert not addon_dir().exists()
    assert not tools.commands


def test_uninstall_never_touches_your_own_python(
    monkeypatch: pytest.MonkeyPatch, tools: FakeTools
) -> None:
    del tools
    monkeypatch.setattr(addons, "check_singer", lambda _p=None: _status(True, "path"))
    monkeypatch.setattr(
        addons, "_remove_folder", lambda _f: pytest.fail("removed something")
    )

    worked, message = addons.uninstall_addon()
    assert not worked
    assert "pip uninstall demucs" in message and str(sys.executable) in message


def test_a_folder_in_use_is_explained(
    monkeypatch: pytest.MonkeyPatch, tools: FakeTools
) -> None:
    assert addons.install_addon(BASE)[0]
    del tools

    def refuse(*_args, **_kwargs):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(addons, "_delete_entry", refuse)
    worked, message = addons.uninstall_addon()
    assert not worked and "in use or protected" in message


def test_removing_a_missing_folder_is_fine(tmp_path: Path) -> None:
    assert addons._remove_folder(tmp_path / "gone") is None  # pylint: disable=protected-access


# ------------------------------------------------------------------ repair


def test_repair_starts_from_scratch(tools: FakeTools) -> None:
    assert addons.install_addon(BASE)[0]
    leftover = addon_dir() / "leftover.txt"
    leftover.write_text("old", encoding="utf-8")

    worked, _tail = addons.repair_addon(BASE)
    assert worked and addons.check_singer().ready
    assert not leftover.exists()
    assert len([c for c in tools.commands if "venv" in c]) == 2


def test_repair_stops_when_the_folder_cannot_be_removed(
    monkeypatch: pytest.MonkeyPatch, tools: FakeTools
) -> None:
    monkeypatch.setattr(addons, "_remove_folder", lambda _f, *_a, **_k: "in use")

    assert addons.repair_addon(BASE) == (False, "in use")
    assert not tools.commands


# ------------------------------------------------------------------ command line


def test_addon_status_exit_code_says_whether_it_is_installed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli.addons, "check_singer", lambda _p=None: _status(True))
    assert cli.main(["--addon-status"]) == 0
    monkeypatch.setattr(
        cli.addons, "check_singer", lambda _p=None: _status(False, "running")
    )
    assert cli.main(["--addon-status"]) == 1
    assert "--install-addon" in capsys.readouterr().out


def test_install_addon_from_the_command_line(
    monkeypatch: pytest.MonkeyPatch,
    tools: FakeTools,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli.addons, "find_python", lambda _p=None: _status(True).python)

    assert cli.main(["--install-addon"]) == 0
    assert addons.check_singer().ready
    installs = len(tools.commands)
    # Already installed: nothing is run again
    assert cli.main(["--install-addon"]) == 0
    assert len(tools.commands) == installs
    assert "already installed" in capsys.readouterr().out
    # Repair always runs, even when installed
    assert cli.main(["--repair-addon"]) == 0
    assert len(tools.commands) > installs


def test_a_failed_command_line_install_shows_what_happened(
    monkeypatch: pytest.MonkeyPatch,
    tools: FakeTools,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tools.pip_works = False
    monkeypatch.setattr(cli.addons, "find_python", lambda _p=None: _status(True).python)

    assert cli.main(["--install-addon"]) == 1
    out = capsys.readouterr().out
    assert "Could not install demucs" in out
    assert not addon_dir().exists()


def test_uninstall_addon_from_the_command_line(
    tools: FakeTools, capsys: pytest.CaptureFixture[str]
) -> None:
    assert addons.install_addon(BASE)[0]
    del tools
    assert cli.main(["--uninstall-addon"]) == 0
    assert not addon_dir().exists()
    # Again: nothing to do, still a success
    assert cli.main(["--uninstall-addon"]) == 0
    assert "nothing was changed" in capsys.readouterr().out
