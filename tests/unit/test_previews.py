# Developed by ::> Gehan Fernando
"""Checks per-song previews: every song its own file, and old results ignored."""

# pytest hands fixtures to tests by name, which pylint sees as shadowing
# pylint: disable=redefined-outer-name

import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from preview_helpers import drain, make_manager

from src import previews as preview_module
from src.core.errors import InputValidationError
from src.core.presets import PRESETS
from src.previews import (
    FAILED,
    IDLE,
    MAKING,
    READY,
    PreviewManager,
    explain,
    fingerprint,
    preview_config,
    sweep_old_folders,
)

STUDIO = PRESETS["studio"].config
GROOVE = PRESETS["groove"].config


class FakeRender:  # pylint: disable=too-few-public-methods
    """Stands in for the pipeline: writes a file, or waits, or fails, on request."""

    def __init__(self) -> None:
        """Nothing made yet."""
        self.calls: list[tuple[Path, Path, object]] = []
        self.release = threading.Event()
        self.release.set()
        self.fail: Exception | None = None

    def __call__(self, song, output, config, *, on_progress, cancel, **_extra):
        """Make a 'preview' of song at output."""
        self.calls.append((song, output, config))
        on_progress("render", 0.5)
        while not self.release.wait(0.01):
            if cancel.is_set():
                raise InputValidationError("Conversion cancelled by user")
        if self.fail is not None:
            raise self.fail
        output.write_bytes(song.read_bytes())


@pytest.fixture
def songs(tmp_path: Path) -> list[Path]:
    """Two songs with the same name in different folders, and a third."""
    made = []
    for folder, name in (("a", "Intro"), ("b", "Intro"), ("a", "Outro")):
        path = tmp_path / folder / f"{name}.mp3"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(f"{folder}/{name}".encode())
        made.append(path)
    return made


@pytest.fixture
def manager(tmp_path: Path):
    """A preview manager with a fake renderer and its event queue."""
    render = FakeRender()
    made, events = make_manager(tmp_path, render)
    yield made, events, render
    made.close()


def test_a_fingerprint_changes_with_the_song_and_its_settings(songs) -> None:
    base = fingerprint(songs[0], STUDIO, 30, "preview")

    assert base == fingerprint(songs[0], STUDIO, 30, "preview")
    assert base != fingerprint(songs[1], STUDIO, 30, "preview")
    assert base != fingerprint(songs[0], GROOVE, 30, "preview")
    assert base != fingerprint(songs[0], STUDIO, 15, "preview")
    assert base != fingerprint(songs[0], STUDIO, 30, "compare")
    # Editing the song file makes old previews stale too
    songs[0].write_bytes(b"changed song")
    os.utime(songs[0], ns=(1, 1))
    assert base != fingerprint(songs[0], STUDIO, 30, "preview")


def test_a_preview_keeps_the_songs_sound_and_plays_as_wav() -> None:
    made = preview_config(GROOVE)

    assert made.output_format == "wav"
    assert replace(made, output_format="mp3") == GROOVE


def test_every_song_gets_its_own_preview_file(manager, songs) -> None:
    previews, events, render = manager
    for song in songs:
        previews.start(song, STUDIO, 30)
        drain(previews, events)

    files = [previews.status_of(song).file for song in songs]
    assert all(previews.status_of(song).state == READY for song in songs)
    assert len({str(file) for file in files}) == 3
    # Two songs both called Intro never share (or overwrite) a preview
    assert files[0].read_bytes() == b"a/Intro"
    assert files[1].read_bytes() == b"b/Intro"
    assert all(file.parent == previews.folder for file in files)
    assert [call[0] for call in render.calls] == songs


def test_an_unchanged_request_is_instant_and_a_changed_one_is_remade(
    manager, songs
) -> None:
    previews, events, render = manager
    previews.start(songs[0], STUDIO, 30)
    drain(previews, events)

    assert previews.start(songs[0], STUDIO, 30) is None
    assert len(render.calls) == 1
    assert previews.is_current(songs[0], STUDIO, 30)
    assert not previews.is_current(songs[0], GROOVE, 30)
    previews.start(songs[0], GROOVE, 30)
    drain(previews, events)
    assert len(render.calls) == 2
    assert previews.is_current(songs[0], GROOVE, 30)


def test_switching_songs_cancels_and_ignores_the_old_preview(manager, songs) -> None:
    previews, events, render = manager
    render.release.clear()
    first = previews.start(songs[0], STUDIO, 30)
    time.sleep(0.1)
    second = previews.start(songs[1], STUDIO, 30)
    render.release.set()
    seen = drain(previews, events)

    assert first != second
    # Whatever the first request still reported was ignored
    late = [ok for (event, ok) in seen if event[1] == first and event[3] != "progress"]
    assert late and not any(late)
    assert previews.status_of(songs[0]).state == IDLE
    assert previews.status_of(songs[1]).state == READY
    assert previews.status_of(songs[1]).file.read_bytes() == b"b/Intro"


def test_cancelling_leaves_nothing_behind(manager, songs) -> None:
    previews, events, render = manager
    render.release.clear()
    previews.start(songs[0], STUDIO, 30)
    time.sleep(0.05)
    assert previews.status_of(songs[0]).state == MAKING
    previews.cancel()
    render.release.set()
    drain(previews, events)

    assert previews.status_of(songs[0]).state == IDLE
    assert not previews.busy
    assert not list(previews.folder.iterdir())


def test_a_failure_is_explained_in_plain_words(manager, songs) -> None:
    previews, events, render = manager
    render.fail = InputValidationError(
        "Input file does not exist or cannot be accessed: x.mp3"
    )
    previews.start(songs[2], STUDIO, 30)
    drain(previews, events)
    status = previews.status_of(songs[2])

    assert status.state == FAILED
    assert "What to do: check the name and folder" in status.problem
    assert "Traceback" not in status.problem
    assert "unexpected" in explain(RuntimeError("boom"))


def test_a_missing_song_fails_safely_with_the_real_pipeline(tmp_path: Path) -> None:
    events: queue.Queue = queue.Queue()
    previews = PreviewManager(events.put, folder=tmp_path / "run")
    previews.folder.mkdir(parents=True, exist_ok=True)
    try:
        previews.start(tmp_path / "gone.mp3", STUDIO, 10)
        drain(previews, events, 30)
        status = previews.status_of(tmp_path / "gone.mp3")
        assert status.state == FAILED
        assert "does not exist" in status.problem
    finally:
        previews.close()


def test_forgetting_a_song_and_closing_clean_up(manager, songs) -> None:
    previews, events, _render = manager
    previews.start(songs[0], STUDIO, 30)
    drain(previews, events)
    previews.forget(songs[0])

    assert previews.status_of(songs[0]).state == IDLE
    previews.close()
    assert not previews.folder.exists()


def test_old_preview_folders_are_swept_away(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Whether pid 1 exists depends on the system, so no owner counts as running
    monkeypatch.setattr(preview_module, "_pid_running", lambda _pid: False)
    root = tmp_path / "Audio8D previews"
    old, current = root / "run-1-1", root / "run-2-2"
    for folder in (old, current):
        folder.mkdir(parents=True)
        (folder / "x.wav").write_bytes(b"x")
    past = time.time() - 3 * 24 * 3600
    os.utime(old, (past, past))
    os.utime(current, (past, past))

    assert sweep_old_folders(root, keep=current) == 1
    assert not old.exists() and current.exists()


def test_an_open_windows_old_previews_are_kept(tmp_path: Path) -> None:
    root = tmp_path / "Audio8D previews"
    ours = root / f"run-{os.getpid()}-1"
    ours.mkdir(parents=True)
    past = time.time() - 3 * 24 * 3600
    os.utime(ours, (past, past))

    assert sweep_old_folders(root) == 0
    assert ours.exists()


def test_only_running_processes_count_as_running() -> None:
    # pylint: disable=protected-access
    with subprocess.Popen([sys.executable, "-c", "pass"]) as child:
        child.wait()
    assert not preview_module._pid_running(child.pid)
    assert preview_module._pid_running(os.getpid())
    assert not preview_module._pid_running(0)
    assert not preview_module._owner_running(Path("not-a-run-folder"))


def test_previews_of_a_run_that_has_ended_are_swept_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ended = tmp_path / "run-4242-1"
    open_window = tmp_path / "run-4343-1"
    for folder in (ended, open_window):
        folder.mkdir()
        (folder / "a.wav").write_bytes(b"x")
    # 4242 has closed (or was killed); 4343 is a window that is still open
    monkeypatch.setattr(preview_module, "_pid_running", lambda pid: pid == 4343)

    assert preview_module.sweep_old_folders(tmp_path) == 1
    assert not ended.exists() and open_window.exists()
