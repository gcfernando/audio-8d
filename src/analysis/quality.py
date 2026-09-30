# Developed by ::> Gehan Fernando
"""Checks the finished file: loudness, true peak, and how it holds up in mono."""

import math
from dataclasses import dataclass
from pathlib import Path

from ..core.errors import ConversionError
from ..ffmpeg import (
    FFmpegToolchain,
    ebur128_summaries,
    ffmpeg_prefix,
    parse_ebur128_summary,
    run_capture,
)

# Perfectly matching left and right lose exactly this much when folded to mono
_MONO_FOLD_DB = 10 * math.log10(2)


@dataclass(frozen=True, slots=True)
class QualityReport:
    """What the finished file measures, and whether any of it is a worry."""

    integrated_lufs: float
    true_peak_db: float
    range_lu: float
    # How alike the two ears are: +1 identical, 0 unrelated, below 0 fighting
    correlation: float

    @property
    def mono_safe(self) -> bool:
        """True when a phone speaker or mono Bluetooth box plays it properly."""
        return self.correlation >= 0.0

    @property
    def peak_safe(self) -> bool:
        """True when no peak reaches digital full scale (no crackle)."""
        return self.true_peak_db < -0.1


def correlation_from_loudness(stereo_lufs: float, mono_lufs: float) -> float:
    """Estimate left/right correlation from stereo vs mono-fold loudness.

    Stereo loudness adds both ears' power; mono (L+R)/2 has power
    (P + P + 2C) / 4. So C / P = 2 * mono / stereo - 1 in plain power terms.
    """
    ratio = 10 ** ((mono_lufs - stereo_lufs + _MONO_FOLD_DB) / 10)
    return max(-1.0, min(1.0, 2.0 * ratio - 1.0))


def check_output(toolchain: FFmpegToolchain, path: Path) -> QualityReport:
    """Measure the finished file once in stereo and once folded to mono."""
    result = run_capture(
        [
            *ffmpeg_prefix(toolchain.ffmpeg, log="info"),
            "-i",
            str(path),
            "-filter_complex",
            "[0:a:0]asplit[a][b];"
            "[a]ebur128=peak=true:framelog=verbose[sa];"
            "[b]pan=mono|c0=0.5*c0+0.5*c1,ebur128=framelog=verbose[sb]",
            "-map",
            "[sa]",
            "-f",
            "null",
            "-",
            "-map",
            "[sb]",
            "-f",
            "null",
            "-",
        ],
        error_type=ConversionError,
    )
    summaries = ebur128_summaries(result.stderr)
    stereo_text = next((s for s in summaries if "Peak:" in s), None)
    mono_text = next((s for s in summaries if "Peak:" not in s), None)
    if stereo_text is None or mono_text is None:
        raise ConversionError("FFmpeg did not report a loudness measurement")
    stereo = parse_ebur128_summary(stereo_text)
    mono_lufs = float(mono_text.split("I:")[1].split("LUFS")[0])
    return QualityReport(
        integrated_lufs=stereo.integrated_lufs,
        true_peak_db=stereo.true_peak_db,
        range_lu=stereo.range_lu,
        correlation=correlation_from_loudness(stereo.integrated_lufs, mono_lufs),
    )
