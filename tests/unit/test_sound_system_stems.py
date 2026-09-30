# Developed by ::> Gehan Fernando
"""The singer's stems join the mix at the song's own rate, resampled with care."""

# pylint: disable=protected-access

from pathlib import Path

import pytest

from src import pipeline
from src.analysis import STEM_RATE
from src.core.settings import EffectConfig
from src.core.types import AudioStreamInfo
from src.effects import GraphInputs, Source, build_graph

_STEMS = GraphInputs(
    (Source(1, (3, 4), rate=STEM_RATE), Source(2, (5, 6), rate=STEM_RATE)),
    room_input=7,
)


def _entry(audio_input: int, resample: str) -> str:
    """How a source's first filters read, with the given resample step."""
    return (
        f"[{audio_input}:a]aformat=sample_fmts=fltp:channel_layouts=stereo"
        f"{resample},highpass=f=5"
    )


@pytest.mark.parametrize("song_rate", [48000, 96000])
def test_stems_of_a_higher_rate_song_get_the_careful_resampler(song_rate: int) -> None:
    graph = build_graph(
        EffectConfig(), _STEMS, sample_rate=song_rate, source_rate=song_rate
    )

    # Without it FFmpeg quietly added its own plainer resampler further on
    for stem in (1, 2):
        assert _entry(stem, f",aresample={song_rate}:filter_size=64") in graph


def test_stems_at_the_songs_own_rate_are_left_alone() -> None:
    graph = build_graph(EffectConfig(), _STEMS, sample_rate=44100, source_rate=44100)

    assert _entry(1, "") in graph and _entry(2, "") in graph


def test_the_song_itself_is_built_exactly_as_before() -> None:
    plain = GraphInputs((Source(0, (1, 2)),), room_input=3)
    named = GraphInputs((Source(0, (1, 2), rate=None),), room_input=3)

    assert build_graph(
        EffectConfig(), plain, sample_rate=48000, source_rate=48000
    ) == build_graph(EffectConfig(), named, sample_rate=48000, source_rate=48000)


def _job(config: EffectConfig) -> pipeline._Job:
    """A conversion job for a 48 kHz song, without probing any real file."""
    job = object.__new__(pipeline._Job)
    job.song = Path("song.flac")
    job.config = config
    job.options = pipeline.ConvertOptions()
    job.toolchain = None  # type: ignore[assignment]
    job.progress = lambda _stage, _share: None
    job.cancel = None
    job.info = AudioStreamInfo(
        codec_name="flac", sample_rate=48000, channels=2, duration_seconds=3.0
    )
    job.length = 3.0
    job.sample_rate = 48000
    job.inputs = [pipeline.InputFile(job.song)]
    return job


def test_the_job_tells_the_graph_the_stems_own_rate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stems = (tmp_path / "vocals.wav", tmp_path / "no_vocals.wav")
    monkeypatch.setattr(pipeline, "separate_vocals", lambda *_a, **_k: stems)
    job = _job(EffectConfig(vocals="center", ambience=0))
    job.prepare(tmp_path)
    alone = _job(EffectConfig(ambience=0))
    alone.prepare(tmp_path)

    assert [source.rate for source in job.graph_inputs.sources] == [STEM_RATE] * 2
    assert alone.graph_inputs.sources[0].rate is None
