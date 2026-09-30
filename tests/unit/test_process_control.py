# Developed by ::> Gehan Fernando
"""Programs Audio8D starts can always be stopped: by cancel, Ctrl+C or closing."""

import queue
import sys
import threading
import time
from pathlib import Path

import pytest

from src import batch
from src.analysis import stems
from src.batch import BatchItem, run_batch
from src.core.errors import ConversionError
from src.core.presets import PRESETS
from src.ffmpeg import runner
from src.ffmpeg.runner import kill_all_processes, live_processes, run_binary, run_tool

SLEEPER = [sys.executable, "-c", "import time; time.sleep(30)"]


def _wait_for(check, seconds: float = 10.0) -> None:
    """Wait until check() is true, failing the test when it never gets there."""
    end = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < end, "timed out waiting"
        time.sleep(0.02)


def test_a_quiet_tool_is_stopped_soon_after_cancel() -> None:
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    started = time.monotonic()

    with pytest.raises(ConversionError, match="cancelled"):
        run_tool(SLEEPER, cancel=cancel)

    assert time.monotonic() - started < 5
    assert live_processes() == 0


def test_a_cancelled_decode_never_starts() -> None:
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(ConversionError, match="cancelled"):
        run_binary(SLEEPER, error_type=ConversionError, cancel=cancel)
    assert live_processes() == 0


def test_a_tool_that_hangs_still_times_out() -> None:
    with pytest.raises(runner.subprocess.TimeoutExpired):
        run_tool(SLEEPER, timeout=0.3)
    assert live_processes() == 0


def test_output_is_still_collected_in_full() -> None:
    script = "import sys; print('x' * 200000); print('done', file=sys.stderr)"
    result = run_tool([sys.executable, "-c", script], cancel=threading.Event())

    assert result.returncode == 0
    assert len(result.stdout.strip()) == 200000
    assert result.stderr.strip() == "done"


def test_closing_the_window_kills_every_running_tool() -> None:
    results: list[int] = []
    workers = [
        threading.Thread(target=lambda: results.append(run_tool(SLEEPER).returncode))
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    _wait_for(lambda: live_processes() == 2)

    assert kill_all_processes() == 2
    for worker in workers:
        worker.join(timeout=10)
    assert len(results) == 2 and all(code != 0 for code in results)
    assert live_processes() == 0
    assert kill_all_processes() == 0


def test_ffmpeg_that_prints_nothing_still_notices_cancel() -> None:
    cancel = threading.Event()
    silent: queue.Queue[str | None] = queue.Queue()
    process = runner.start_process(SLEEPER)
    threading.Timer(0.3, cancel.set).start()
    started = time.monotonic()
    try:
        runner._follow(  # pylint: disable=protected-access
            process, silent, 10.0, None, cancel
        )
    finally:
        runner.forget_process(process)

    assert time.monotonic() - started < 5
    assert process.poll() is not None


def test_ctrl_c_in_a_batch_stops_the_other_songs_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[str] = []

    def fake_convert(source: Path, *_args, cancel=None, **_kwargs):
        started.append(source.name)
        if source.name == "a":
            raise KeyboardInterrupt
        # A long song that only stops when told to
        assert cancel is not None and cancel.wait(20)
        raise ConversionError("Conversion cancelled by user")

    monkeypatch.setattr(batch, "convert", fake_convert)
    items = [BatchItem(Path(name), Path(f"{name}.mp3")) for name in "abcdef"]
    begin = time.monotonic()

    with pytest.raises(KeyboardInterrupt):
        run_batch(items, PRESETS["studio"].config, jobs=2)

    assert time.monotonic() - begin < 10
    # Songs still waiting were never started
    assert len(started) <= 3


def test_two_jobs_on_one_song_work_in_separate_folders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    song = tmp_path / "song.mp3"
    song.write_bytes(b"song")
    folders: list[Path] = []

    class Ready:  # pylint: disable=too-few-public-methods
        """Stands in for a ready add-on status."""

        ready = True
        python = type("Python", (), {"path": Path(sys.executable)})()

    def fake_capture(command, **_kwargs):
        Path(command[-1]).write_bytes(b"wav")

    def fake_demucs(command, **_kwargs):
        work = Path(command[command.index("-o") + 1])
        folders.append(work)
        made = work / stems.MODEL
        made.mkdir()
        for name in ("vocals.wav", "no_vocals.wav"):
            (made / name).write_bytes(name.encode())
        return runner.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(stems, "singer_status", Ready)
    monkeypatch.setattr(stems, "run_capture", fake_capture)
    monkeypatch.setattr(stems, "run_tool", fake_demucs)
    monkeypatch.setattr(stems, "ffmpeg_prefix", lambda ffmpeg: [str(ffmpeg)])
    toolchain = type("Tools", (), {"ffmpeg": Path("ffmpeg")})()

    vocals, music = stems.separate_vocals(toolchain, song)  # type: ignore[arg-type]
    # A second job that finds nothing cached yet makes its own copy safely
    vocals.unlink()
    again = stems.separate_vocals(toolchain, song)  # type: ignore[arg-type]

    assert again == (vocals, music)
    assert vocals.read_bytes() == b"vocals.wav"
    assert music.read_bytes() == b"no_vocals.wav"
    assert len(set(folders)) == 2
    assert not any(folder.exists() for folder in folders)


def test_a_stopped_split_leaves_no_work_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    song = tmp_path / "song.mp3"
    song.write_bytes(b"song")

    class Ready:  # pylint: disable=too-few-public-methods
        """Stands in for a ready add-on status."""

        ready = True
        python = type("Python", (), {"path": Path(sys.executable)})()

    def cancelled(*_args, **_kwargs):
        raise ConversionError("Conversion cancelled by user")

    monkeypatch.setattr(stems, "singer_status", Ready)
    monkeypatch.setattr(stems, "run_capture", cancelled)
    monkeypatch.setattr(stems, "ffmpeg_prefix", lambda ffmpeg: [str(ffmpeg)])
    toolchain = type("Tools", (), {"ffmpeg": Path("ffmpeg")})()

    with pytest.raises(ConversionError, match="cancelled"):
        stems.separate_vocals(toolchain, song)  # type: ignore[arg-type]
    folder = stems.cache_dir() / "stems"
    assert not list(folder.rglob("work-*"))
