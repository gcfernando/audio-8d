# Developed by ::> Gehan Fernando
"""Finds a song's tempo, so one full circle can last a whole number of bars.

FFmpeg decodes up to 90 seconds into two small envelopes (the kick range and
the hi-hat range) at 100 values a second. Every jump in loudness is an
onset; the onset pattern is then compared with itself shifted by every
possible beat length (autocorrelation), and the best-matching shift, with a
gentle preference for everyday tempos, is the beat.
"""

import math
import sys
import threading
from array import array
from pathlib import Path

from ..core.errors import ConversionError
from ..ffmpeg import FFmpegToolchain, ffmpeg_prefix, run_binary

_RATE = 11025
_HOP = 110  # 100.2 envelope values per second
_FRAMES_PER_SECOND = _RATE / _HOP
_ANALYSE_SECONDS = 90.0
_MIN_BPM, _MAX_BPM = 60.0, 200.0
# Tempos are reported in this range; half/double tempo is the same pulse
_FOLD_LOW, _FOLD_HIGH = 70.0, 180.0
# Beat strength at the best lag: noise and ambience measured under 0.07, songs 0.18+
_MIN_CONFIDENCE = 0.1


def _decode_bands(
    toolchain: FFmpegToolchain,
    song: Path,
    start: float,
    seconds: float,
    cancel: threading.Event | None = None,
) -> array:
    """16-bit samples, interleaved: [low band, high band] per frame."""
    raw = run_binary(
        [
            *ffmpeg_prefix(toolchain.ffmpeg),
            "-ss",
            f"{start:.2f}",
            "-t",
            f"{seconds:.2f}",
            "-i",
            str(song),
            "-filter_complex",
            "[0:a:0]pan=mono|c0=0.5*c0+0.5*c1,asplit[a][b];"
            "[a]lowpass=f=150[l];[b]highpass=f=3000[h];"
            f"[l][h]amerge=inputs=2,aresample={_RATE}[out]",
            "-map",
            "[out]",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-",
        ],
        error_type=ConversionError,
        cancel=cancel,
    )
    data = array("h")
    data.frombytes(raw[: len(raw) - len(raw) % 2])
    if sys.byteorder != "little":
        data.byteswap()
    return data


def onset_strength(samples: array) -> list[float]:
    """How sharply the sound gets louder at each step (kick and hi-hat combined)."""
    novelty: list[float] = []
    previous = [0.0, 0.0]
    frame = 2 * _HOP
    for offset in range(0, len(samples) - frame + 1, frame):
        chunk = samples[offset : offset + frame]
        value = 0.0
        for band in (0, 1):
            part = chunk[band::2]
            energy = math.log1p(sum(x * x for x in part) / len(part))
            value += max(0.0, energy - previous[band])
            previous[band] = energy
        novelty.append(value)
    # Remove the average so steady loud passages don't look like beats
    mean = sum(novelty) / len(novelty) if novelty else 0.0
    return [value - mean for value in novelty]


def tempo_from_onsets(novelty: list[float]) -> float | None:
    """The best beat length in the onset pattern, as beats per minute."""
    shortest = int(_FRAMES_PER_SECOND * 60 / _MAX_BPM)
    longest = int(_FRAMES_PER_SECOND * 60 / _MIN_BPM) + 1
    if len(novelty) < longest * 4:
        return None
    scores = {}
    for lag in range(shortest, longest + 1):
        total = sum(a * b for a, b in zip(novelty, novelty[lag:], strict=False))
        bpm = 60 * _FRAMES_PER_SECOND / lag
        # A soft preference for tempos near 120, one octave wide
        prior = math.exp(-0.5 * (math.log2(bpm / 120.0) / 1.0) ** 2)
        scores[lag] = total / (len(novelty) - lag) * prior
    best = max(scores, key=lambda lag: scores[lag])
    energy = sum(value * value for value in novelty) / len(novelty)
    if scores[best] <= 0 or energy <= 0:
        return None
    # A regular beat repeats strongly; noise only ever matches itself by chance
    strength = sum(a * b for a, b in zip(novelty, novelty[best:], strict=False))
    if strength / (len(novelty) - best) / energy < _MIN_CONFIDENCE:
        return None
    # A parabola through the peak and its neighbours finds it between whole lags
    left, right = scores.get(best - 1), scores.get(best + 1)
    shift = 0.0
    if left is not None and right is not None:
        curve = left - 2 * scores[best] + right
        if curve < 0:
            shift = 0.5 * (left - right) / curve
    bpm = 60 * _FRAMES_PER_SECOND / (best + shift)
    while bpm < _FOLD_LOW:
        bpm *= 2
    while bpm > _FOLD_HIGH:
        bpm /= 2
    return round(bpm, 1)


def detect_bpm(
    toolchain: FFmpegToolchain,
    song: Path,
    duration: float | None,
    *,
    cancel: threading.Event | None = None,
) -> float | None:
    """The song's tempo, or None when it has no clear beat (speech, ambient)."""
    total = duration or _ANALYSE_SECONDS
    # Skip the intro when there is enough song, since intros often have no drums
    start = min(30.0, max(0.0, total - _ANALYSE_SECONDS))
    samples = _decode_bands(
        toolchain, song, start, min(_ANALYSE_SECONDS, total), cancel
    )
    return tempo_from_onsets(onset_strength(samples))


def rotation_for_tempo(bpm: float, wanted_seconds: float) -> tuple[float, int]:
    """The whole number of beats per circle closest to wanted_seconds.

    Returns (seconds per circle, beats per circle); circles are 1/2, 1, 2, 4 or
    8 bars of 4 beats, kept inside the allowed 2-100 second range.
    """
    beat = 60.0 / bpm
    options = [
        (beats * beat, beats)
        for beats in (2, 4, 8, 16, 32)
        if 2.0 <= beats * beat <= 100.0
    ]
    if not options:
        return wanted_seconds, 0
    return min(options, key=lambda option: abs(math.log(option[0] / wanted_seconds)))
