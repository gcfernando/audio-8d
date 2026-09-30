# Developed by ::> Gehan Fernando
"""Where the sound is at every moment: its angle, how far out, and how high."""

import math
from collections.abc import Iterator
from dataclasses import dataclass

from ..core.settings import EffectConfig, Keyframes

TWO_PI = 2.0 * math.pi


@dataclass(frozen=True, slots=True)
class Position:
    """One point on the path.

    azimuth: radians, 0 = straight ahead, +pi/2 = right ear, pi = behind you
    intensity: 0 = everything in the middle, 1 = the full 3D movement
    height: 0 = ear level, 1 = as high over your head as it goes
    """

    azimuth: float
    intensity: float
    height: float


def interpolate(frames: Keyframes, time: float) -> float:
    """Straight lines between keyframes, holding the first and last values."""
    if time <= frames[0][0]:
        return frames[0][1]
    for (t0, v0), (t1, v1) in zip(frames, frames[1:], strict=False):
        if time <= t1:
            if t1 == t0:
                return v1
            return v0 + (v1 - v0) * (time - t0) / (t1 - t0)
    return frames[-1][1]


def _smoothstep(x: float) -> float:
    """0 -> 1 with gentle ends, so the fade never starts or stops with a jolt."""
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


def fade_factor(time: float, fade: float, duration: float | None) -> float:
    """How much of the movement is switched on: grows in, then settles at the end."""
    if fade <= 0:
        return 1.0
    factor = _smoothstep(time / fade)
    if duration is not None:
        factor *= _smoothstep((duration - time) / fade)
    return factor


def path_azimuth(path: str, phase: float) -> float:
    """Turn the running phase (one turn = 2 pi) into a direction for each path."""
    if path == "arc":
        # Swings left and right through the front, like a slow pendulum
        return (math.pi / 2.0) * math.sin(phase)
    if path == "figure8":
        # Front -> right -> behind -> right -> front, then the same round the left ear
        return math.pi * math.sin(phase)
    if path == "wander":
        # Mostly forwards, with slow drifts that never repeat exactly
        return (
            phase
            + 1.2 * math.sin(0.37 * phase + 1.1)
            + 0.6 * math.sin(0.83 * phase + 0.3)
        )
    return phase


def _turn_seconds(config: EffectConfig, time: float) -> float:
    """Seconds per full turn at this moment of the song."""
    if config.speed_curve:
        return interpolate(config.speed_curve, time)
    return config.rotation_seconds


def phase_at(config: EffectConfig, start: float, rate: float) -> float:
    """The running phase a full render has reached `start` seconds into the song.

    It adds the speed step by step exactly as trajectory() does, so a render
    that begins part-way picks the movement up where the full song has it.
    """
    phase = 0.0
    step = 1.0 / rate
    # A hair of slack stops 12.3 s * 200 landing one sample short in floating point
    whole = int(start * rate + 1e-9)
    for index in range(whole):
        phase += TWO_PI * step / _turn_seconds(config, index * step)
    # A start between two samples gets the last part-step too
    rest = start - whole * step
    if rest > 0:
        phase += TWO_PI * rest / _turn_seconds(config, whole * step)
    return phase


def trajectory(  # pylint: disable=too-many-arguments
    config: EffectConfig,
    *,
    rate: float,
    duration: float,
    total: float | None = None,
    intensity_scale: float = 1.0,
    start: float = 0.0,
) -> Iterator[Position]:
    """Positions sampled `rate` times a second for `duration` seconds.

    `total` is where the render really ends, so the movement can settle before
    it; the extra samples after it just keep the last position. `start` is the
    song time the render begins at (a preview of the chorus, say): the curves,
    the turning and the height follow song time, while the ease-in and ease-out
    stay on the render's own clock.
    """
    direction = 1.0 if config.direction == "clockwise" else -1.0
    phase = phase_at(config, start, rate) if start > 0 else 0.0
    step = 1.0 / rate
    for index in range(int(math.ceil(duration * rate)) + 1):
        time = index * step
        song_time = start + time
        seconds = _turn_seconds(config, song_time)
        amount = (
            interpolate(config.intensity_curve, song_time)
            if config.intensity_curve
            else config.intensity
        )
        amount *= fade_factor(time, config.fade_seconds, total) * intensity_scale
        # Rises over your head and back down once every two turns
        height = config.elevation * 0.5 * (1.0 - math.cos(phase / 2.0))
        yield Position(
            azimuth=direction * path_azimuth(config.path, phase),
            intensity=min(1.0, max(0.0, amount)),
            height=height,
        )
        # Adding the speed one step at a time handles any speed curve exactly
        phase += TWO_PI * step / seconds
