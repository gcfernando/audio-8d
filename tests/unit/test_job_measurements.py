# Developed by ::> Gehan Fernando
"""The side measurements of a conversion: the original's loudness and the A/B file."""

# pylint: disable=protected-access

import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src import pipeline
from src.analysis.sections import Section
from src.core.settings import EffectConfig
from src.core.types import AudioStreamInfo
from src.ffmpeg import InputFile, LoudnessMeasurement

# A loudness reading that every fake measurement returns
LEVEL = LoudnessMeasurement(-20.0, -3.0, 5.0)


def _fake_job(channels: int, **extra) -> Any:
    """Just enough of a _Job for the methods under test (typed loosely on purpose)."""
    return SimpleNamespace(
        info=AudioStreamInfo("flac", channels, 44100, 30.0),
        toolchain=SimpleNamespace(ffmpeg=Path("ffmpeg")),
        inputs=[InputFile(Path("song.flac"))],
        **extra,
    )


@pytest.mark.parametrize("channels", [1, 2])
def test_the_original_is_made_stereo_like_the_mix_before_measuring(
    monkeypatch: pytest.MonkeyPatch, channels: int
) -> None:
    graphs: list[str] = []
    monkeypatch.setattr(
        pipeline,
        "build_measure_command",
        lambda _ff, _inputs, graph: graphs.append(graph),
    )
    monkeypatch.setattr(pipeline, "measure_loudness", lambda *_a, **_k: LEVEL)

    lufs = pipeline._Job._source_loudness(_fake_job(channels), threading.Event())

    assert lufs == -20.0
    # A mono song is measured at the same full level the 8D mix gives it
    assert graphs[0].startswith("[0:a:0]" + pipeline.to_stereo(channels == 1))
    assert ("pan=stereo" in graphs[0]) is (channels == 1)


def test_a_failed_mix_stops_and_waits_for_the_original_measurement(
    tmp_path: Path,
) -> None:
    seen: dict[str, bool] = {}

    def slow_source(stop: threading.Event) -> float:
        # Stands in for FFmpeg measuring the original until it is told to stop
        seen["stopped"] = stop.wait(10.0)
        return -20.0

    def broken_mix(_scratch: Path):
        raise RuntimeError("mix failed")

    job = _fake_job(
        2,
        config=SimpleNamespace(wants_loudness=True, match_loudness=True),
        _source_loudness=slow_source,
        _measure_mix=broken_mix,
    )

    with pytest.raises(RuntimeError, match="mix failed"):
        pipeline._Job.run(job, tmp_path / "out.mp3", tmp_path)

    # run() only returns once the side measurement has been stopped and finished
    assert seen == {"stopped": True}


def test_a_stop_from_the_user_reaches_the_original_measurement() -> None:
    cancel, stop = threading.Event(), threading.Event()
    worker = threading.Thread(target=lambda: stop.wait(10.0), daemon=True)
    worker.start()
    cancel.set()

    pipeline._Job._wait_for(_fake_job(2, cancel=cancel), worker, stop)

    assert stop.is_set() and not worker.is_alive()


@pytest.mark.parametrize(("on_stream", "source"), [(True, "0:s:a:0"), (False, "0")])
def test_the_ab_file_keeps_mp3_margin_and_the_songs_tags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, on_stream: bool, source: str
) -> None:
    info = AudioStreamInfo("opus", 2, 48000, 60.0, tags_on_stream=on_stream)
    previews: list[dict] = []
    commands: list[list[str]] = []
    monkeypatch.setattr(
        pipeline, "toolchain_for", lambda _config: _fake_job(2).toolchain
    )
    monkeypatch.setattr(pipeline, "resolve_input", lambda path: path)
    monkeypatch.setattr(pipeline, "probe_audio", lambda *_a, **_k: info)
    monkeypatch.setattr(
        pipeline, "loudest_section", lambda *_a, **_k: Section(5.0, 0.0)
    )
    monkeypatch.setattr(pipeline, "preview", lambda *_a, **k: previews.append(k))
    monkeypatch.setattr(pipeline, "measure_loudness", lambda *_a, **_k: LEVEL)
    monkeypatch.setattr(pipeline, "commit_output", lambda *_a, **_k: None)

    def fake_ffmpeg(command, **_kwargs):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(pipeline, "run_ffmpeg", fake_ffmpeg)

    pipeline.compare(Path("song.opus"), tmp_path / "ab.mp3", EffectConfig())

    # B is saved inside an MP3, so it is limited with MP3's peak margin
    assert previews[0]["render_as"] == "mp3"
    command = commands[0]
    assert command[command.index("-map_metadata") + 1] == source
