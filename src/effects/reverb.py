# Developed by ::> Gehan Fernando
"""A small, natural-sounding room made from scratch and played by FFmpeg's afir.

The room is an impulse response: a pre-delay, a handful of early reflections,
then a smooth tail that dies away and gets duller as it does, like a real
room where soft furnishings swallow the high notes first. Each ear gets a
differently seeded tail, which makes the reverb wide and enveloping.
"""

import math
import random
from dataclasses import dataclass
from pathlib import Path

from .wavfile import write_float_wav

# Fixed seeds, so the same settings always make exactly the same room
_SEEDS = (8, 88)


@dataclass(frozen=True, slots=True)
class Room:
    """The size of the room, worked out from the --ambience setting."""

    decay_seconds: float
    pre_delay_seconds: float
    wet_gain: float


def room_for(ambience: float) -> Room:
    """Bigger ambience = a longer, louder tail; 0.25 is a subtle, modest room."""
    return Room(
        # RT60 from 0.5 s (small room) up to 2.2 s (hall)
        decay_seconds=0.5 + 1.7 * ambience,
        # A little gap before the room answers keeps vocals clear
        pre_delay_seconds=0.012 + 0.018 * ambience,
        # From about -20 dB (0.25) to -10 dB (1.0) under the dry sound
        wet_gain=0.32 * ambience**0.85,
    )


def impulse_response(  # pylint: disable=too-many-locals
    room: Room, sample_rate: int, seed: int
) -> list[float]:
    """One ear's impulse response, scaled to unit energy."""
    rng = random.Random(seed)
    length = int(sample_rate * (room.pre_delay_seconds + room.decay_seconds * 1.1))
    samples = [0.0] * length
    start = int(room.pre_delay_seconds * sample_rate)

    # Early reflections: sparse bounces off nearby walls in the first 70 ms
    for index in range(8):
        delay = start + int(sample_rate * rng.uniform(0.004, 0.070))
        if delay < length:
            strength = 0.55 * (0.82**index)
            samples[delay] += strength if rng.random() < 0.5 else -strength

    # Late tail: decaying noise, low-passed more and more as it fades
    tail_start = start + int(0.012 * sample_rate)
    smoothed = 0.0
    decay_rate = 6.91 / room.decay_seconds  # ln(1000): -60 dB after decay_seconds
    for index in range(tail_start, length):
        seconds = (index - tail_start) / sample_rate
        # Cut-off glides from about 9 kHz down to about 1.5 kHz as the tail fades
        cutoff = 1500.0 + 7500.0 * math.exp(-seconds * 3.0 / room.decay_seconds)
        smoothing = 1.0 - math.exp(-2.0 * math.pi * cutoff / sample_rate)
        smoothed += smoothing * (rng.uniform(-1.0, 1.0) - smoothed)
        # A 15 ms fade-in blends the tail smoothly into the early reflections
        onset = min(1.0, seconds / 0.015)
        samples[index] += smoothed * math.exp(-decay_rate * seconds) * onset

    energy = math.sqrt(sum(value * value for value in samples)) or 1.0
    return [value / energy for value in samples]


def write_room(path: Path, ambience: float, sample_rate: int) -> Path:
    """Save a stereo impulse response for this ambience as a float WAV."""
    room = room_for(ambience)
    left, right = (impulse_response(room, sample_rate, seed) for seed in _SEEDS)
    interleaved = [value for pair in zip(left, right, strict=True) for value in pair]
    return write_float_wav(path, interleaved, channels=2, rate=sample_rate)
