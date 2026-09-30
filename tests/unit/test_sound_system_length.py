# Developed by ::> Gehan Fernando
"""The 8D song is exactly as long as the part of the song it was made from."""

import subprocess
from pathlib import Path

import pytest

from src.core.errors import DependencyError
from src.core.settings import EffectConfig
from src.effects import GraphInputs, Source, build_graph, write_controls, write_room
from src.ffmpeg import FFmpegToolchain
from src.ffmpeg.commands import InputFile, build_encode_command

_RATE = 44100


def _ffmpeg() -> Path:
    """The real FFmpeg, or skip the test when there is none."""
    try:
        return FFmpegToolchain.discover().ffmpeg
    except DependencyError as exc:
        raise pytest.skip.Exception("FFmpeg is not available") from exc


def test_the_timing_band_never_decides_how_long_the_mix_is() -> None:
    graph = build_graph(EffectConfig(), GraphInputs((Source(0, (1, 2)),)),
                        sample_rate=_RATE, source_rate=_RATE)  # fmt: skip

    # The quarter-rate band is padded to whole quarter samples, so it goes second
    assert "[s0highmoved][s0lowmoved]amix=inputs=2:normalize=0:duration=first" in (
        graph
    )


@pytest.mark.parametrize("engine", ["3d", "pan"])
@pytest.mark.parametrize("frames", [44101, 44102, 44103])
def test_every_sample_count_comes_out_unchanged(
    tmp_path: Path, engine: str, frames: int
) -> None:
    ffmpeg = _ffmpeg()
    song = tmp_path / "song.wav"
    subprocess.run(
        [str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "error",
         "-f", "lavfi", "-i", f"anoisesrc=r={_RATE}:c=pink:a=0.2:seed=3",
         "-af", f"atrim=end_sample={frames}", "-ac", "2", "-c:a", "pcm_f32le",
         str(song)],
        check=True,
    )  # fmt: skip
    config = EffectConfig(engine=engine, output_format="wav")
    controls = write_controls(tmp_path, "s0", config, frames / _RATE)
    room = write_room(tmp_path / "room.wav", config.ambience, _RATE)
    inputs = [InputFile(song), *map(InputFile, controls), InputFile(room)]
    sources = GraphInputs((Source(0, (1, 2)[: len(controls)]),), room_input=3)
    if engine == "pan":
        sources = GraphInputs((Source(0, (1,)),), room_input=2)
    graph = build_graph(config, sources, sample_rate=_RATE, source_rate=_RATE)
    out = tmp_path / "out.wav"
    subprocess.run(
        build_encode_command(ffmpeg, inputs, out, filter_graph=graph,
                             config=config, sample_rate=_RATE),
        check=True,
    )  # fmt: skip
    decoded = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "error",
         "-i", str(out), "-f", "s32le", "-c:a", "pcm_s32le", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip

    # A length that is not a multiple of four once gained up to three samples
    assert len(decoded) // 8 == frames
