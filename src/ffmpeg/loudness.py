# Developed by ::> Gehan Fernando
"""Measures loudness with FFmpeg's EBU R128 meter before the real encode."""

import re
import threading
from dataclasses import dataclass

from ..core.errors import ConversionError
from .runner import ProgressCallback, run_ffmpeg

# FFmpeg prints -inf for silence, so accept that as well as ordinary numbers
_NUMBER = r"(-?inf|-?\d+(?:\.\d+)?)"


@dataclass(frozen=True, slots=True)
class LoudnessMeasurement:
    """How loud the 8D mix is before any volume change."""

    integrated_lufs: float
    true_peak_db: float
    range_lu: float


def _summary_value(summary: str, label: str, unit: str) -> float:
    """One number from a summary, e.g. the value after 'I:' ending in 'LUFS'."""
    match = re.search(rf"{label}:\s+{_NUMBER}\s+{unit}", summary)
    if match is None:
        raise ConversionError(f"FFmpeg's loudness summary is missing '{label}'")
    return float(match.group(1))


def ebur128_summaries(log: str) -> list[str]:
    """Every 'Summary:' block in an FFmpeg log, in the order they were printed."""
    parts = log.split("Summary:")[1:]
    return ["Summary:" + part for part in parts]


def parse_ebur128_summary(log: str) -> LoudnessMeasurement:
    """Pull integrated loudness, true peak and loudness range out of FFmpeg's log."""
    start = log.rfind("Summary:")
    if start < 0:
        raise ConversionError("FFmpeg did not report a loudness measurement")
    summary = log[start:]
    return LoudnessMeasurement(
        integrated_lufs=_summary_value(summary, "I", "LUFS"),
        true_peak_db=_summary_value(summary, "Peak", "dBFS"),
        range_lu=_summary_value(summary, "LRA", "LU"),
    )


def measure_loudness(
    command: list[str],
    *,
    duration: float | None = None,
    on_progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> LoudnessMeasurement:
    """Run a measure command (commands.build_measure_command) and read the meter."""
    result = run_ffmpeg(
        command, duration=duration, on_progress=on_progress, cancel=cancel
    )
    if result.returncode != 0:
        details = result.stderr.strip()[-2000:] or "unknown error"
        raise ConversionError(
            f"Command failed with exit code {result.returncode}: {details}"
        )
    return parse_ebur128_summary(result.stderr)
