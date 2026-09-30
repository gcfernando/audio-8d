# Developed by ::> Gehan Fernando
"""The limiter's ceiling holds on every sample that reaches the encoder."""

import subprocess
from array import array

import pytest

from src.core.errors import DependencyError
from src.core.settings import EffectConfig
from src.effects.graph import finish_stages, limiter_stage
from src.ffmpeg import FFmpegToolchain

_RATE = 44100
# Seeded pink noise, pushed 20 dB into the limiter: it overshot by 0.28 dB before
_HOT_NOISE = f"anoisesrc=d=2:c=pink:r={_RATE}:a=0.5:seed=11"


def _toolchain() -> FFmpegToolchain:
    """The real FFmpeg, or skip the test when there is none."""
    try:
        return FFmpegToolchain.discover()
    except DependencyError as exc:
        raise pytest.skip.Exception("FFmpeg is not available") from exc


def test_the_oversampled_limiter_ends_with_a_guard_at_the_real_rate() -> None:
    ceiling = EffectConfig(output_format="flac").limiter_ceiling
    stage = limiter_stage(ceiling, _RATE)
    main = stage.split(",")[1]

    assert main.startswith(f"alimiter=limit={ceiling:.4f}:")
    assert stage == (
        f"aresample=88200:filter_size=64,{main},aresample=44100:filter_size=64,{main}"
    )


@pytest.mark.parametrize("ceiling", [1.0, 0.89])
def test_no_sample_goes_over_the_ceiling_even_when_driven_hard(ceiling: float) -> None:
    ffmpeg = _toolchain().ffmpeg
    config = EffectConfig(output_format="wav", limiter_ceiling=ceiling)
    chain = finish_stages(config, 20.0, False, sample_rate=_RATE, lossless=True)
    result = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "error",
         "-f", "lavfi", "-i", _HOT_NOISE,
         "-af", f"aformat=sample_fmts=fltp:channel_layouts=stereo,{chain}",
         "-f", "f32le", "-c:a", "pcm_f32le", "-"],
        capture_output=True, check=True,
    )  # fmt: skip
    samples = array("f", result.stdout)

    # Coming back down from 2x lifted peaks past the ceiling, clipping them at 1.0
    assert len(samples) == 2 * 2 * _RATE
    assert max(map(abs, samples)) <= ceiling + 1e-6
