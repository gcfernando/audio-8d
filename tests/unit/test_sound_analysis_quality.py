# Developed by ::> Gehan Fernando
"""Checks the mono-compatibility figure and the loudness cache key."""

import math
import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest

from src import EffectConfig, cache
from src.analysis import quality
from src.analysis.quality import check_output, correlation_from_levels
from src.core.types import Trim
from src.ffmpeg import FFmpegToolchain

_VENDOR = Path(__file__).resolve().parents[2] / "vendor/ffmpeg/windows-x86_64"


def _db(power: float) -> float:
    """A power as the RMS level astats prints for it."""
    return -math.inf if power == 0 else 10 * math.log10(power)


def _levels(rho: float, right_gain: float) -> tuple[float, float, float]:
    """Levels of L, R and L + R for unit-power L and R = gain * (rho-correlated)."""
    left, right = 1.0, right_gain**2
    both = left + right + 2 * rho * right_gain
    return _db(left), _db(right), _db(both)


@pytest.mark.parametrize("rho", [1.0, 0.8, 0.3, 0.0, -0.5, -1.0])
@pytest.mark.parametrize("right_gain", [1.0, 0.5, 0.25])
def test_correlation_is_exact_whatever_the_balance(
    rho: float, right_gain: float
) -> None:
    # The old stereo-vs-mono estimate read rho=1 at quarter level as +0.49
    got = correlation_from_levels(*_levels(rho, right_gain))
    assert got == pytest.approx(rho, abs=1e-9)


def test_correlation_of_silence_and_one_silent_ear() -> None:
    assert correlation_from_levels(-math.inf, -math.inf, -math.inf) == 1.0
    assert correlation_from_levels(-20.0, -math.inf, -20.0) == 0.0


_ASTATS_LOG = """\
[Parsed_ebur128_1 @ 0000] Summary:

  Integrated loudness:
    I:         -14.2 LUFS
    Threshold: -24.6 LUFS

  Loudness range:
    LRA:         5.1 LU
    Threshold: -34.7 LUFS
    LRA low:   -18.0 LUFS
    LRA high:  -12.9 LUFS

  True peak:
    Peak:       -1.6 dBFS
[Parsed_astats_4 @ 0000] Channel: 1
[Parsed_astats_4 @ 0000] RMS level dB: -16.253008
[Parsed_astats_4 @ 0000] Channel: 2
[Parsed_astats_4 @ 0000] RMS level dB: -16.252998
[Parsed_astats_4 @ 0000] Channel: 3
[Parsed_astats_4 @ 0000] RMS level dB: -14.210978
"""


def test_check_output_reads_the_meter_and_the_levels(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, "", _ASTATS_LOG)

    monkeypatch.setattr(quality, "run_capture", fake_run)
    tools = FFmpegToolchain(tmp_path / "ffmpeg", tmp_path / "ffprobe")
    report = check_output(tools, tmp_path / "song.flac")
    assert (report.integrated_lufs, report.true_peak_db) == (-14.2, -1.6)
    assert report.range_lu == 5.1
    # These levels come from a song that cancels in mono 60% of the time
    assert report.correlation == pytest.approx(-0.2, abs=0.001)
    assert not report.mono_safe


@pytest.mark.skipif(
    not (_VENDOR / "ffmpeg.exe").is_file(), reason="needs the bundled FFmpeg"
)
def test_partly_cancelling_song_is_not_called_mono_safe(tmp_path: Path) -> None:
    ffmpeg = _VENDOR / "ffmpeg.exe"
    song = tmp_path / "flip.wav"
    # Right is the left flipped for 60% of every second: true correlation -0.2
    subprocess.run(
        [
            str(ffmpeg),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "aevalsrc='0.3*sin(2*PI*997*t)|"
            "if(lt(mod(t,1),0.6),-1,1)*0.3*sin(2*PI*997*t)':s=48000:d=5",
            str(song),
        ],
        check=True,
    )
    tools = FFmpegToolchain(ffmpeg, _VENDOR / "ffprobe.exe")
    report = check_output(tools, song, cancel=threading.Event())
    # The gated mono-loudness estimate called this +0.79 and mono-safe
    assert report.correlation == pytest.approx(-0.2, abs=0.02)
    assert not report.mono_safe


def test_cache_key_follows_the_preview_timeline(tmp_path: Path) -> None:
    song = tmp_path / "song.mp3"
    song.write_bytes(b"one")
    config = EffectConfig(loudness_target=-14.0, intensity_curve=((0, 0.2), (30, 1)))
    window = Trim(20.0, 30.0)
    base = cache.measurement_key(song, config, window, 44100)
    # The same window at another point of the curves is a different mix
    assert cache.measurement_key(song, config, window, 44100, 20.0) != base
    assert cache.measurement_key(song, config, window, 44100, 5.0) != (
        cache.measurement_key(song, config, window, 44100, 20.0)
    )
    # A full song starts its timeline at 0, so old measurements keep their key
    assert cache.measurement_key(song, config, window, 44100, 0.0) == base
