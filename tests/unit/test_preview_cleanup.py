# Developed by ::> Gehan Fernando
"""Previews never leave files behind: not near your music, not after a failure,
and not once a newer preview of the same song replaces them."""

# pytest hands fixtures to tests by name, which pylint sees as shadowing
# pylint: disable=redefined-outer-name

import threading
import time
from pathlib import Path

import pytest
from preview_helpers import drain, make_manager

from src import cli, previews
from src.core.errors import ConversionError, InputValidationError
from src.core.presets import PRESETS
from src.previews import (
    MAX_KEPT,
    READY,
    make_preview,
    temporary_folder,
)

STUDIO = PRESETS["studio"].config
GROOVE = PRESETS["groove"].config


class Render:  # pylint: disable=too-few-public-methods
    """Stands in for the pipeline; each call can be held back or made to fail."""

    def __init__(self) -> None:
        """Every call writes its file at once unless told otherwise."""
        self.calls: list[Path] = []
        self.hold: dict[int, threading.Event] = {}
        self.fail_after_hold: set[int] = set()
        self.fail: Exception | None = None

    def __call__(self, song, output, config, **kwargs):
        """Write a 'preview', or half of one and then fail."""
        del config
        number = len(self.calls)
        self.calls.append(output)
        progress = kwargs.get("on_progress")
        if progress is not None:
            progress("render", 0.5)
        if number in self.hold:
            # Like FFmpeg, which may take a moment to notice it was cancelled
            self.hold[number].wait(5)
            if number in self.fail_after_hold:
                raise InputValidationError("Conversion cancelled by user")
        if self.fail is not None:
            output.write_bytes(b"half")
            raise self.fail
        output.write_bytes(Path(song).read_bytes())
        return output


@pytest.fixture
def songs(tmp_path: Path) -> list[Path]:
    """Seven small 'songs' in a music folder."""
    music = tmp_path / "music"
    music.mkdir()
    made = []
    for number in range(7):
        song = music / f"song{number}.mp3"
        song.write_bytes(f"song {number}".encode())
        made.append(song)
    return made


@pytest.fixture
def manager(tmp_path: Path):
    """A preview manager with a fake renderer and its event queue."""
    render = Render()
    made, events = make_manager(tmp_path, render)
    yield made, events, render
    made.close()


def _files(folder: Path) -> list[Path]:
    return sorted(folder.iterdir())


# ------------------------------------------------------------------ make_preview


def test_a_preview_is_made_only_inside_the_given_folder(
    monkeypatch: pytest.MonkeyPatch, songs: list[Path], tmp_path: Path
) -> None:
    render = Render()
    monkeypatch.setattr(previews, "preview", render)
    folder = tmp_path / "private"
    folder.mkdir()

    file = make_preview(songs[0], folder, GROOVE, seconds=10)
    assert file.parent == folder and file.suffix == ".wav"
    assert file.read_bytes() == b"song 0"
    assert sorted(p.name for p in songs[0].parent.iterdir()) == sorted(
        s.name for s in songs
    )


def test_a_failed_preview_leaves_no_file(
    monkeypatch: pytest.MonkeyPatch, songs: list[Path], tmp_path: Path
) -> None:
    render = Render()
    render.fail = ConversionError("FFmpeg stopped")
    monkeypatch.setattr(previews, "preview", render)

    with pytest.raises(ConversionError):
        make_preview(songs[0], tmp_path, STUDIO)
    assert not render.calls[0].exists()


def test_a_stopped_preview_leaves_no_file(
    monkeypatch: pytest.MonkeyPatch, songs: list[Path], tmp_path: Path
) -> None:
    render = Render()
    render.fail = KeyboardInterrupt()  # type: ignore[assignment]
    monkeypatch.setattr(previews, "compare", render)

    with pytest.raises(KeyboardInterrupt):
        make_preview(songs[0], tmp_path, STUDIO, kind="compare")
    assert render.calls[0].suffix == ".mp3" and not render.calls[0].exists()


def test_the_temporary_folder_goes_whatever_happens() -> None:
    with temporary_folder() as folder:
        (folder / "x.wav").write_bytes(b"x")
        kept = folder
    assert not kept.exists()

    with pytest.raises(RuntimeError), temporary_folder() as folder:
        (folder / "y.wav").write_bytes(b"y")
        kept = folder
        raise RuntimeError("boom")
    assert not kept.exists()


# ------------------------------------------------------------------ the command line


@pytest.fixture
def cli_preview(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """--preview with a fake pipeline and player; returns (render, played, folder)."""
    render = Render()
    played: list[tuple[Path, bool]] = []
    folder = tmp_path / "temp-run"

    def session() -> Path:
        folder.mkdir()
        return folder

    def listen(_painter, file, _seconds):
        played.append((file, file.is_file()))

    monkeypatch.setattr(cli, "resolve_input", lambda path: path)
    monkeypatch.setattr(cli, "_peek_source", lambda path: None)
    monkeypatch.setattr(previews, "_session_folder", session)
    monkeypatch.setattr(previews, "preview", render)
    monkeypatch.setattr(previews, "compare", render)
    monkeypatch.setattr(cli, "preview", render)
    monkeypatch.setattr(cli, "compare", render)
    monkeypatch.setattr(cli, "_listen", listen)
    return render, played, folder


def test_preview_plays_a_temporary_file_and_deletes_it(
    cli_preview, songs: list[Path]
) -> None:
    render, played, folder = cli_preview
    before = _files(songs[0].parent)

    assert cli.main([str(songs[0]), "--preview", "12"]) == 0
    file, existed = played[0]
    assert existed and file.parent == folder
    assert not file.exists() and not folder.exists()
    # Nothing was written next to the music
    assert _files(songs[0].parent) == before
    assert render.calls == [file]


def test_compare_is_temporary_too(cli_preview, songs: list[Path]) -> None:
    _render, played, folder = cli_preview

    assert cli.main([str(songs[0]), "--compare"]) == 0
    assert played[0][1] and played[0][0].suffix == ".mp3"
    assert not folder.exists()


def test_a_failed_preview_cleans_up_and_says_why(
    cli_preview, songs: list[Path]
) -> None:
    render, played, folder = cli_preview
    render.fail = ConversionError("FFmpeg stopped")
    before = _files(songs[0].parent)

    assert cli.main([str(songs[0]), "--preview"]) == 1
    assert not played and not folder.exists()
    assert _files(songs[0].parent) == before


def test_stopping_while_it_plays_still_cleans_up(
    cli_preview, songs: list[Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _render, _played, folder = cli_preview

    def interrupted(*_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_listen", interrupted)
    assert cli.main([str(songs[0]), "--preview"]) == 1
    assert not folder.exists()


def test_an_output_file_keeps_the_preview(
    cli_preview, songs: list[Path], tmp_path: Path
) -> None:
    render, played, folder = cli_preview
    kept = tmp_path / "kept.wav"

    assert cli.main([str(songs[0]), str(kept), "--preview", "10"]) == 0
    assert kept.read_bytes() == b"song 0"
    assert render.calls == [kept]
    assert not played and not folder.exists()


# ------------------------------------------------------------ the window's manager


def test_a_songs_superseded_preview_is_deleted_at_once(manager, songs) -> None:
    previews_, events, _render = manager
    previews_.start(songs[0], STUDIO, 30)
    drain(previews_, events)
    first = previews_.status_of(songs[0]).file
    assert first is not None and first.is_file()

    previews_.start(songs[0], GROOVE, 30)
    assert not first.exists()
    drain(previews_, events)
    second = previews_.status_of(songs[0]).file
    assert second is not None and second != first and second.is_file()
    assert _files(previews_.folder) == [second]


def test_only_the_newest_few_previews_are_kept(manager, songs) -> None:
    previews_, events, _render = manager
    made = []
    for song in songs[: MAX_KEPT + 2]:
        previews_.start(song, STUDIO, 30)
        drain(previews_, events)
        made.append(previews_.status_of(song).file)

    kept = [file for file in made if file.exists()]
    assert kept == made[-MAX_KEPT:]
    assert len(_files(previews_.folder)) == MAX_KEPT
    # The oldest songs are back to 'no preview' and would be made again
    assert previews_.status_of(songs[0]).state != READY
    assert previews_.start(songs[0], STUDIO, 30) is not None
    drain(previews_, events)
    assert len(_files(previews_.folder)) == MAX_KEPT


def test_replaying_a_kept_preview_keeps_it_among_the_newest(manager, songs) -> None:
    previews_, events, render = manager
    for song in songs[:MAX_KEPT]:
        previews_.start(song, STUDIO, 30)
        drain(previews_, events)
    # Asking for the oldest again is instant and makes it the newest
    assert previews_.start(songs[0], STUDIO, 30) is None
    drain(previews_, events)
    previews_.start(songs[MAX_KEPT], STUDIO, 30)
    drain(previews_, events)

    assert len(render.calls) == MAX_KEPT + 1
    assert previews_.status_of(songs[0]).state == READY
    assert previews_.status_of(songs[1]).state != READY


def test_forgetting_a_song_deletes_its_preview(manager, songs) -> None:
    previews_, events, _render = manager
    previews_.start(songs[0], STUDIO, 30)
    previews_.start(songs[1], STUDIO, 30)
    drain(previews_, events)
    file = previews_.status_of(songs[1]).file

    previews_.forget(songs[1])
    assert file is not None and not file.exists()
    previews_.forget(songs[1])  # twice is harmless
    previews_.forget(songs[5])  # never previewed


def test_forgetting_the_song_being_made_stops_it(manager, songs) -> None:
    previews_, events, render = manager
    render.hold[0] = threading.Event()
    render.fail_after_hold.add(0)
    previews_.start(songs[0], STUDIO, 30)
    time.sleep(0.05)

    previews_.forget(songs[0])
    assert not previews_.busy
    render.hold[0].set()
    drain(previews_, events)
    time.sleep(0.1)
    assert _files(previews_.folder) == []


def test_a_cancelled_request_never_deletes_a_newer_identical_preview(
    manager, songs
) -> None:
    previews_, events, render = manager
    # The first request for song 0 is slow to notice it was cancelled
    render.hold[0] = threading.Event()
    render.fail_after_hold.add(0)
    previews_.start(songs[0], STUDIO, 30)
    time.sleep(0.05)
    previews_.start(songs[1], STUDIO, 30)  # cancels the first
    previews_.start(songs[0], STUDIO, 30)  # same song, same settings again
    drain(previews_, events)
    status = previews_.status_of(songs[0])
    assert status.state == READY and status.file is not None

    # Now the first, cancelled request finally gives up
    render.hold[0].set()
    time.sleep(0.3)
    while not events.empty():
        previews_.handle(events.get())
    assert status.file.is_file()
    assert previews_.is_current(songs[0], STUDIO, 30)
