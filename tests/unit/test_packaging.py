# Developed by ::> Gehan Fernando
"""Checks the standalone-exe behaviour: paths, bundled tools, the log and startup."""

# pytest hands fixtures to tests by name, which pylint sees as shadowing
# pylint: disable=redefined-outer-name

import logging
import sys
import threading
from pathlib import Path

import pytest

from src import addons, gui, launcher, logs
from src.analysis import stems
from src.core import locations


@pytest.fixture
def packaged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Pretend to be Audio8D.exe sitting in tmp_path."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Audio8D.exe"))
    return tmp_path


def test_the_project_folder_is_home_during_development() -> None:
    root = Path(__file__).resolve().parents[2]

    assert not locations.is_packaged()
    assert locations.app_dir() == root
    # This system's copy in vendor/ffmpeg (or, without one, that folder anyway)
    assert locations.tools_dir() in (
        root / "vendor" / "ffmpeg" / locations.platform_tag(),
        root / "bin",
    )
    assert locations.GUIDE_URL.endswith("/8D/README.md")


def test_the_windows_ffmpeg_is_kept_in_vendor_not_bin() -> None:
    root = Path(__file__).resolve().parents[2]
    kept = root / "vendor" / "ffmpeg" / "windows-x86_64"
    assert (kept / "ffmpeg.exe").is_file() and (kept / "ffprobe.exe").is_file()
    # bin is only for the release ZIPs
    assert not (root / "bin" / "ffmpeg.exe").exists()


def test_the_exe_finds_everything_next_to_itself(packaged: Path) -> None:
    assert locations.is_packaged()
    assert locations.app_dir() == packaged
    assert locations.tools_dir() == packaged


def test_the_package_finds_ffmpeg_in_its_bundled_files(
    packaged: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # PyInstaller puts bundled files in _internal (Frameworks on macOS)
    inside = tmp_path / "_internal"
    inside.mkdir()
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    (inside / name).write_bytes(b"x")
    monkeypatch.setattr(sys, "_MEIPASS", str(inside), raising=False)
    assert locations.tools_dir() == inside
    # A copy beside the program still wins (people may replace FFmpeg there)
    (packaged / name).write_bytes(b"x")
    assert locations.tools_dir() == packaged


@pytest.mark.parametrize(
    ("platform", "machine", "tag"),
    [
        ("win32", "AMD64", "windows-x86_64"),
        ("linux", "x86_64", "linux-x86_64"),
        ("linux", "aarch64", "linux-arm64"),
        ("darwin", "arm64", "macos-arm64"),
        ("darwin", "x86_64", "macos-x86_64"),
    ],
)
def test_each_system_has_one_package_name(
    monkeypatch: pytest.MonkeyPatch, platform: str, machine: str, tag: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(locations.platform, "machine", lambda: machine)
    assert locations.platform_tag() == tag


def test_the_exe_restarts_itself_in_windows_terminal(packaged: Path) -> None:
    assert launcher._start_command(["a;b.mp3"]) == [  # pylint: disable=protected-access
        str(packaged / "Audio8D.exe"),
        r"a\;b.mp3",
    ]


@pytest.mark.usefixtures("packaged")
def test_the_exe_never_runs_the_add_on_with_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The exe is not a Python, so without one on the computer the add-on waits
    monkeypatch.setattr(addons.shutil, "which", lambda _name: None)
    addons.set_preferred_python(None)
    status = addons.singer_status(refresh=True)

    assert status.python.path is None and not status.ready
    assert not stems.demucs_available()
    assert "Install Python" in stems.demucs_hint()
    addons.forget_status()


# The helper thread below crashes on purpose, and pytest reports that as well
@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_the_log_file_is_started_once(monkeypatch: pytest.MonkeyPatch) -> None:
    root = logging.getLogger()
    # Start as if no log had been opened yet in this process
    monkeypatch.setattr(root, "handlers", [])
    before = list(root.handlers)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    try:
        first = logs.start_log_file()
        second = logs.start_log_file()
        logging.getLogger("audio8d.test").warning("written to the log")

        def crash() -> None:
            raise ValueError("a helper thread broke")

        helper = threading.Thread(target=crash, name="helper")
        helper.start()
        helper.join()
        for handler in root.handlers:
            handler.flush()

        assert first is not None
        text = first.read_text(encoding="utf-8")
        assert first == second == locations.log_file()
        assert "written to the log" in text
        assert "Unexpected error in helper" in text and "a helper thread broke" in text
    finally:
        for handler in set(root.handlers) - set(before):
            root.removeHandler(handler)
            handler.close()


def test_an_unwritable_log_folder_never_stops_the_app(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    monkeypatch.setattr(logs, "log_file", lambda: blocker / "logs" / "audio8d.log")
    # Start as if no log had been opened yet in this process
    monkeypatch.setattr(logging.getLogger(), "handlers", [])

    assert logs.start_log_file() is None
    assert not logging.getLogger().handlers


def test_a_window_that_cannot_start_explains_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    told: list[str] = []
    monkeypatch.setattr(gui, "_tell", told.append)
    monkeypatch.setattr(gui, "start_log_file", lambda: Path("audio8d.log"))

    def broken(_songs: object) -> int:
        raise RuntimeError("no display")

    monkeypatch.setattr("src.gui_app.launch", broken)

    assert gui.run_gui() == 1
    assert "could not open its window" in told[0] and "audio8d.log" in told[0]
