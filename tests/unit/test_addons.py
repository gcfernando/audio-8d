# Developed by ::> Gehan Fernando
"""Finding and checking Python and the singer add-on's packages, and installing them."""

import subprocess
import sys
from pathlib import Path

import pytest

from src import addons
from src.addons import AddonStatus, Package, PackageCheck, PythonCheck


def _answer(returncode: int, stdout: str = "", stderr: str = ""):
    """A fake run_tool that answers like a finished process."""

    def run(command, **_kwargs):
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)

    return run


def test_the_running_python_is_run_and_accepted() -> None:
    found = addons.check_python(Path(sys.executable))

    assert found.ok and found.problem == ""
    assert found.version.startswith(f"{sys.version_info[0]}.{sys.version_info[1]}")
    assert found.path is not None and found.path.exists()


def test_missing_folder_and_unrunnable_pythons_are_explained(tmp_path: Path) -> None:
    assert "No Python" in addons.check_python(None).problem
    missing = addons.check_python(tmp_path / "python.exe")
    assert not missing.ok and "There is no file" in missing.problem
    folder = addons.check_python(tmp_path)
    assert not folder.ok and "is a folder" in folder.problem
    # A file that exists but isn't a program at all can't be started
    fake = tmp_path / "python.exe"
    fake.write_text("not a program", encoding="utf-8")
    broken = addons.check_python(fake)
    assert not broken.ok and broken.problem


def test_the_microsoft_store_shortcut_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        addons,
        "run_tool",
        _answer(
            9009,
            stderr="Python was not found; run without arguments to "
            "install from the Microsoft Store",
        ),  # fmt: skip
    )
    alias = Path(sys.executable)
    found = addons.check_python(alias)

    assert not found.ok and "Microsoft Store" in found.problem
    assert "Microsoft Store" in found.detail


def test_a_python_that_is_too_old_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    old = '{"version": [3, 8, 10], "executable": "C:\\\\Python38\\\\python.exe"}'
    monkeypatch.setattr(addons, "run_tool", _answer(0, stdout=old))

    found = addons.check_python(Path(sys.executable))
    assert not found.ok and found.version == "3.8.10"
    assert "too old" in found.problem and "3.10" in found.problem


def test_an_answer_that_is_not_python_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(addons, "run_tool", _answer(0, stdout="hello"))
    assert (
        "did not answer like Python"
        in addons.check_python(Path(sys.executable)).problem
    )


def test_a_hanging_python_is_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    def hang(command, **_kwargs):
        raise subprocess.TimeoutExpired(command, 20)

    monkeypatch.setattr(addons, "run_tool", hang)
    assert "did not answer within" in addons.check_python(Path(sys.executable)).problem


def test_a_chosen_python_wins_even_when_it_is_wrong(tmp_path: Path) -> None:
    found = addons.find_python(tmp_path / "nothing.exe")

    assert not found.ok and found.source == "configured"


def test_automatic_search_skips_pythons_that_do_not_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = PythonCheck(Path("C:/WindowsApps/python.exe"), False, problem="alias")
    good = PythonCheck(Path(sys.executable), True, version="3.12.1")
    monkeypatch.setattr(
        addons,
        "_automatic_candidates",
        lambda: [(["C:/WindowsApps/python.exe"], "path"), ([sys.executable], "path")],
    )
    monkeypatch.setattr(
        addons, "_run_python", lambda command: bad if "Apps" in command[0] else good
    )
    found = addons.find_python()
    assert found.ok and found.path == Path(sys.executable) and found.source == "path"

    monkeypatch.setattr(addons, "_run_python", lambda _command: bad)
    none = addons.find_python()
    assert not none.ok and "No working Python" in none.problem

    monkeypatch.setattr(addons, "_automatic_candidates", list)
    assert "No Python was found" in addons.find_python().problem


def test_packages_are_imported_not_just_looked_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A package that is there but needs another package that is missing
    broken = tmp_path / "halfway_pkg"
    broken.mkdir()
    (broken / "__init__.py").write_text(
        "import audio8d_missing_dependency\n", encoding="utf-8"
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    checks = addons.check_packages(
        Path(sys.executable),
        (
            Package("json", "json", "reads JSON"),
            Package("audio8d_not_a_package", "audio8d_not_a_package", "nothing"),
            Package("halfway_pkg", "halfway_pkg", "breaks when loaded"),
        ),
    )
    ready, absent, half = checks

    assert ready.ok
    assert not absent.ok and absent.problem == "not installed"
    assert not half.ok and half.problem.startswith("installed but can't be loaded")
    assert "audio8d_missing_dependency" in half.problem


def _status(*oks: bool, python_ok: bool = True) -> AddonStatus:
    python = PythonCheck(Path(sys.executable), python_ok, "running", "3.12.1")
    packages = tuple(
        PackageCheck(package, ok, problem="" if ok else "not installed")
        for package, ok in zip(addons.SINGER_PACKAGES, oks, strict=False)
    )
    return AddonStatus(python, packages)


def test_the_add_on_state_is_read_from_its_checks() -> None:
    assert _status(True, True, True).ready
    assert _status(True, True, True).state == "ready"
    assert _status(False, False, True).state == "not-installed"
    # Demucs itself there but a helper missing: partly installed
    assert _status(True, False, True).state == "partial"
    assert _status(python_ok=False).state == "no-python"
    assert "--install-addon" in _status(False, False, False).fix()
    assert "python.org" in _status(python_ok=False).fix()


def test_installing_streams_every_line_of_pip(monkeypatch: pytest.MonkeyPatch) -> None:
    script = "print('Collecting demucs'); print('Successfully installed demucs')"
    monkeypatch.setattr(
        addons, "install_command", lambda _p: [sys.executable, "-c", script]
    )
    lines: list[str] = []
    worked, tail = addons.install_packages(Path(sys.executable), lines.append)

    assert worked
    assert lines == ["Collecting demucs", "Successfully installed demucs"]
    assert "Successfully installed" in tail


def test_a_python_without_pip_gets_the_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    script = "import sys; print('No module named pip'); sys.exit(1)"
    monkeypatch.setattr(
        addons, "install_command", lambda _p: [sys.executable, "-c", script]
    )
    worked, tail = addons.install_packages(Path(sys.executable))

    assert not worked and "ensurepip" in tail


def test_the_install_command_uses_the_chosen_python() -> None:
    command = addons.install_command(Path("C:/Python 3/python.exe"))

    assert command[:4] == [str(Path("C:/Python 3/python.exe")), "-m", "pip", "install"]
    assert "demucs" in command
    assert addons.quote_command(command).startswith('"C:')


def test_the_status_is_remembered_until_something_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def check(_python=None):
        calls.append(1)
        return _status(True, True, True)

    monkeypatch.setattr(addons, "check_singer", check)
    addons.forget_status()
    assert addons.singer_status().ready and addons.singer_status().ready
    assert len(calls) == 1
    # Choosing another Python means checking again
    addons.set_preferred_python(Path("C:/Other/python.exe"))
    assert addons.known_status() is None
    addons.singer_status()
    assert len(calls) == 2
    assert addons.singer_python() == Path(sys.executable)
