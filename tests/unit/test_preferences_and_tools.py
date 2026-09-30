# Developed by ::> Gehan Fernando
"""Checks the saved preferences, the FFmpeg/FFprobe settings, logs and playback."""

# pylint: disable=protected-access

import json
import logging
import os
import shutil
import sys
from pathlib import Path

import pytest

from src.core.errors import DependencyError
from src.core.locations import tools_dir
from src.core.preferences import (
    Preferences,
    load_preferences,
    preferences_file,
    save_preferences,
)
from src.ffmpeg import toolchain
from src.ffmpeg.toolchain import (
    FFmpegToolchain,
    check_tool,
    locate,
    preferred_key,
    set_preferred_paths,
)
from src.logs import delete_log_files, log_files, start_log_file
from src.player import PAUSED, PLAYING, STOPPED, Player

BUNDLED = tools_dir()
EXE = ".exe" if os.name == "nt" else ""
needs_ffmpeg = pytest.mark.skipif(
    not (BUNDLED / f"ffmpeg{EXE}").is_file(), reason="no bundled FFmpeg"
)


@pytest.fixture(autouse=True)
def _automatic_tools():
    """Every test starts (and ends) with automatic tool finding."""
    set_preferred_paths(None, None)
    yield
    set_preferred_paths(None, None)


# ------------------------------------------------------------ preferences


def test_missing_preferences_mean_the_defaults() -> None:
    preferences, problem = load_preferences()

    assert preferences == Preferences()
    assert problem is None
    assert preferences.tools() == (None, None)


def test_preferences_are_saved_and_read_back(tmp_path: Path) -> None:
    chosen = tmp_path / "Tools ünï cödé" / f"ffmpeg{EXE}"
    saved = Preferences(
        ffmpeg_path=str(chosen), theme="Light", scale=1.25, verbose=True
    )

    file = save_preferences(saved)
    loaded, problem = load_preferences()

    assert file == preferences_file() and problem is None
    assert loaded == saved
    assert loaded.tools() == (chosen, None)
    assert json.loads(file.read_text(encoding="utf-8"))["format_version"] == 1


def test_a_damaged_preferences_file_falls_back_to_the_defaults() -> None:
    preferences_file().parent.mkdir(parents=True, exist_ok=True)
    preferences_file().write_text("{ not json", encoding="utf-8")

    preferences, problem = load_preferences()

    assert preferences == Preferences()
    assert problem is not None and "damaged" in problem


def test_unusable_values_are_ignored_one_by_one() -> None:
    preferences_file().parent.mkdir(parents=True, exist_ok=True)
    preferences_file().write_text(
        json.dumps({"theme": "Purple", "scale": 3, "verbose": True, "extra": 1}),
        encoding="utf-8",
    )

    preferences, problem = load_preferences()

    assert problem is None
    assert preferences.theme == "System" and preferences.scale == 1.0
    assert preferences.verbose is True


# ------------------------------------------------------------ finding tools


@needs_ffmpeg
def test_tools_are_found_automatically_and_say_how() -> None:
    found = locate("ffmpeg")

    assert found.source == "bundled"
    assert found.source_words == "Found automatically (included with Audio8D)"
    check = check_tool("ffmpeg", found.path)
    assert check.ok and check.version


def test_the_usual_install_folders_are_searched_last(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(toolchain, "BUNDLED_DIR", tmp_path / "none")
    monkeypatch.setattr(toolchain.shutil, "which", lambda _name: None)
    folder = tmp_path / "usual"
    folder.mkdir()
    fake = folder / f"ffprobe{EXE}"
    fake.write_bytes(b"")
    fake.chmod(0o755)
    monkeypatch.setattr(toolchain, "_common_folders", lambda: [folder])

    found = locate("ffprobe")
    assert found.path == fake and found.source == "common"
    assert locate("ffmpeg").source == "missing"


def test_a_chosen_path_always_wins_and_changes_the_cache_key(tmp_path: Path) -> None:
    before = preferred_key()
    chosen = tmp_path / f"ffmpeg{EXE}"

    set_preferred_paths(chosen, None)

    assert locate("ffmpeg").path == chosen
    assert locate("ffmpeg").source == "configured"
    assert locate("ffmpeg").source_words == "Chosen by you"
    assert preferred_key() != before


def test_a_wrong_chosen_path_is_reported_not_replaced(tmp_path: Path) -> None:
    set_preferred_paths(tmp_path / "missing" / f"ffmpeg{EXE}", None)

    with pytest.raises(DependencyError, match="chosen in Settings can't be used"):
        FFmpegToolchain.discover()


def test_checking_explains_every_kind_of_wrong_file(tmp_path: Path) -> None:
    assert "was not found" in check_tool("ffmpeg", None).problem
    assert "There is no file" in check_tool("ffmpeg", tmp_path / "x.exe").problem
    assert "is a folder" in check_tool("ffmpeg", tmp_path).problem
    # A real program that isn't FFmpeg
    other = check_tool("ffmpeg", Path(sys.executable))
    assert not other.ok and "did not answer like ffmpeg" in other.problem


@needs_ffmpeg
def test_the_other_tool_by_mistake_is_named() -> None:
    check = check_tool("ffmpeg", BUNDLED / f"ffprobe{EXE}")

    assert not check.ok
    assert check.problem.startswith("That file is ffprobe, not ffmpeg")


@needs_ffmpeg
def test_tools_in_folders_with_spaces_and_any_letters_work(tmp_path: Path) -> None:
    folder = tmp_path / "My Tools ünï cödé 音楽"
    folder.mkdir()
    for name in ("ffmpeg", "ffprobe"):
        try:
            os.link(BUNDLED / f"{name}{EXE}", folder / f"{name}{EXE}")
        except OSError:
            shutil.copy2(BUNDLED / f"{name}{EXE}", folder / f"{name}{EXE}")
    set_preferred_paths(folder / f"ffmpeg{EXE}", folder / f"ffprobe{EXE}")

    found = FFmpegToolchain.discover()

    assert found.ffmpeg.parent.name == "My Tools ünï cödé 音楽"
    assert check_tool("ffprobe", found.ffprobe).ok
    found.validate_capabilities()


# ------------------------------------------------------------ logs


def test_saved_logs_can_be_deleted_while_the_log_is_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = logging.getLogger()
    # A log file opened by an earlier test lives in that test's own folder
    others = [h for h in root.handlers if getattr(h, "audio8d_file", False)]
    monkeypatch.setattr(root, "handlers", [h for h in root.handlers if h not in others])
    path = start_log_file()
    assert path is not None
    logging.getLogger("audio8d.test").warning("a line to save")
    assert path in log_files()

    deleted, failed = delete_log_files()

    assert deleted >= 1 and not failed
    # Logging carries on in a fresh file
    logging.getLogger("audio8d.test").warning("after deleting")
    assert "after deleting" in path.read_text(encoding="utf-8")
    for handler in root.handlers:
        if getattr(handler, "audio8d_file", False):
            handler.close()


# ------------------------------------------------------------ playback


@pytest.mark.skipif(os.name != "nt", reason="built-in playback is Windows-only")
def test_the_player_plays_pauses_resumes_and_stops(stereo_tone: Path) -> None:
    player = Player(muted=True)
    player.load(stereo_tone)
    assert player.built_in
    player.play(from_start=True)
    assert player.state() == PLAYING
    player.pause()
    assert player.state() == PAUSED
    player.resume()
    assert player.state() == PLAYING
    _done, length = player.position()
    assert 2.5 < length < 3.5
    player.stop()
    assert player.state() == STOPPED
    player.close()
    # Once closed, the file is free to delete
    stereo_tone.unlink()
