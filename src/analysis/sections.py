# Developed by ::> Gehan Fernando
"""Finds the loudest stretch of a song: usually the chorus, the best preview."""

import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from ..core.errors import ConversionError
from ..core.types import Trim
from ..ffmpeg import FFmpegToolchain, ffmpeg_prefix, run_capture

# ebur128 logs a line every 100 ms: "t: 12.3  TARGET:-23 LUFS  M: -14.2 S: -15.0 ..."
_LINE = re.compile(r"t:\s*([\d.]+).*?\bS:\s*(-?[\d.]+|-inf)")
_MOMENTARY = re.compile(r"t:\s*([\d.]+).*?\bM:\s*(-?[\d.]+|-inf)")


def short_term_loudness(log: str) -> list[tuple[float, float]]:
    """(time, short-term LUFS) pairs from an ebur128 log with framelog=info."""
    points = []
    for match in _LINE.finditer(log):
        value = match.group(2)
        points.append(
            (float(match.group(1)), -120.0 if value == "-inf" else float(value))
        )
    return points


def loudest_start(points: list[tuple[float, float]], length: float) -> float:
    """Where a window of `length` seconds has the most energy."""
    if not points:
        return 0.0
    powers = [(time, 10 ** (lufs / 10)) for time, lufs in points]
    best_time, best_total = 0.0, -1.0
    total = 0.0
    first = 0
    for index, (time, power) in enumerate(powers):
        total += power
        while powers[first][0] < time - length:
            total -= powers[first][1]
            first += 1
        if index and total > best_total:
            best_total = total
            best_time = powers[first][0]
    # The short-term meter looks 3 s back, so start the preview a little earlier
    return max(0.0, best_time - 3.0)


def momentary_loudness(log: str) -> list[tuple[float, float]]:
    """(time, momentary LUFS) pairs: one 400 ms block ending at each time."""
    points = []
    for match in _MOMENTARY.finditer(log):
        value = match.group(2)
        points.append(
            (float(match.group(1)), -120.0 if value == "-inf" else float(value))
        )
    return points


def gated_loudness(values: list[float]) -> float | None:
    """Integrated loudness of momentary blocks, gated the way EBU R128 does it."""
    # Blocks under -70 LUFS are silence and never count
    powers = [10 ** (value / 10) for value in values if value > -70.0]
    if not powers:
        return None
    # Then anything 10 LU below the average is dropped, so quiet gaps don't count
    relative = 10 * math.log10(sum(powers) / len(powers)) - 10.0
    kept = [power for power in powers if 10 * math.log10(power) > relative]
    return 10 * math.log10(sum(kept) / len(kept))


def section_lift_db(
    points: list[tuple[float, float]], start: float, length: float
) -> float | None:
    """How much louder start..start+length is than everything measured, in dB."""
    whole = gated_loudness([value for _time, value in points])
    # A block ending at t covers the 400 ms before it, so it must end inside
    inside = [value for time, value in points if start + 0.4 <= time <= start + length]
    part = gated_loudness(inside)
    if whole is None or part is None:
        return None
    return part - whole


@dataclass(frozen=True, slots=True)
class Section:
    """The loudest stretch found, and how much louder it is than the whole scan."""

    start: float
    # Section loudness minus the scanned part's; None when either is silent
    lift_db: float | None = None


def loudest_section(  # pylint: disable=too-many-arguments
    toolchain: FFmpegToolchain,
    song: Path,
    length: float,
    duration: float | None,
    *,
    window: Trim | None = None,
    cancel: threading.Event | None = None,
) -> Section:
    """The loudest `length`-second stretch, searched only inside window if given.

    One scan gives both the start and the lift, so the lift costs nothing extra.
    """
    first = (window.start if window else None) or 0.0
    last = window.end if window and window.end is not None else duration
    if last is not None and duration is not None:
        last = min(last, duration)
    if last is not None and last - first <= length:
        return Section(first, 0.0)
    span = [] if last is None else ["-t", f"{last - first:.3f}"]
    result = run_capture(
        [
            *ffmpeg_prefix(toolchain.ffmpeg, log="info"),
            "-ss",
            f"{first:.3f}",
            *span,
            "-i",
            str(song),
            "-map",
            "0:a:0",
            "-af",
            "aresample=22050,ebur128=framelog=info",
            "-f",
            "null",
            "-",
        ],
        error_type=ConversionError,
        cancel=cancel,
    )
    start = loudest_start(short_term_loudness(result.stderr), length)
    if last is not None:
        start = min(start, max(0.0, last - first - length))
    lift = section_lift_db(momentary_loudness(result.stderr), start, length)
    return Section(first + start, lift)


def find_loudest_section(
    toolchain: FFmpegToolchain,
    song: Path,
    length: float,
    duration: float | None,
    *,
    cancel: threading.Event | None = None,
) -> float:
    """Start time (seconds) of the loudest `length`-second stretch of the song.

    Setting cancel stops the full-song scan part-way (ConversionError).
    """
    return loudest_section(toolchain, song, length, duration, cancel=cancel).start
