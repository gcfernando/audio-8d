# Developed by ::> Gehan Fernando
"""Writes the movement as a stream of gains that FFmpeg multiplies the song by."""

from array import array
from pathlib import Path

from ..core.settings import EffectConfig
from .head import DELAY_TAPS, HIGH_BANDS, binaural_gains, pan_gains
from .motion import trajectory
from .wavfile import write_float_wav

# 200 gains a second: every 5 ms, far finer than the ear can follow a moving sound
CONTROL_RATE = 200
# The stream runs a little past the song so it can never end first
_SPARE_SECONDS = 2.0


def control_streams(
    config: EffectConfig,
    duration: float,
    *,
    intensity_scale: float = 1.0,
    start: float = 0.0,
) -> list[tuple[int, array]]:
    """Every gain stream as (channels, frame-after-frame samples).

    start is the song time the render begins at, so the movement matches the
    full song there (see motion.trajectory).

    The 3D engine has two: the delay-tap weights and the band gains.
    Plain panning has one: a left and a right gain.
    """
    positions = trajectory(
        config,
        rate=CONTROL_RATE,
        duration=duration + _SPARE_SECONDS,
        total=duration,
        intensity_scale=intensity_scale,
        start=start,
    )
    # Compact float arrays: a long song has millions of gains, too many for lists
    if config.engine != "3d":
        flat = array("f")
        for position in positions:
            flat.extend(pan_gains(position))
        return [(2, flat)]
    low, high = array("f"), array("f")
    for position in positions:
        taps, bands = binaural_gains(position)
        low.extend(taps)
        high.extend(bands)
    return [(2 * DELAY_TAPS, low), (2 * len(HIGH_BANDS), high)]


def write_controls(
    folder: Path,
    stem: str,
    config: EffectConfig,
    duration: float,
    *,
    intensity_scale: float = 1.0,
    start: float = 0.0,
) -> list[Path]:
    """Save each gain stream as a float WAV in folder and return their paths."""
    paths = []
    streams = control_streams(
        config, duration, intensity_scale=intensity_scale, start=start
    )
    for index, (channels, samples) in enumerate(streams):
        paths.append(
            write_float_wav(
                folder / f"{stem}-gains{index}.wav",
                samples,
                channels=channels,
                rate=CONTROL_RATE,
            )
        )
    return paths
