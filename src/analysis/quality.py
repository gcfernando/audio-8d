# Developed by ::> Gehan Fernando
"""Checks the finished file: loudness, true peak, and how it holds up in mono."""

import math
import re
import threading
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

# BS.1770's K-weighting, so the correlation hears the song as the loudness meter does
_K_WEIGHTING = (
    "aformat=sample_fmts=dblp,"
    "highshelf=f=1681.974:g=3.99984:t=q:w=0.7071752,"
    "highpass=f=38.13547:poles=2:t=q:w=0.500327"
)
# astats prints one RMS level per channel: left, right, then left + right
_RMS_LINE = re.compile(r"Parsed_astats_\d+ @ [^\]]+\] RMS level dB: (-?inf|-?[\d.]+)")


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


def correlation_from_levels(left_db: float, right_db: float, sum_db: float) -> float:
    """Left/right correlation from the RMS levels of left, right and left + right.

    Power(L + R) = PL + PR + 2C, so C / sqrt(PL * PR) is the true correlation,
    whatever the balance and however much of the song cancels in mono.
    """
    left, right, both = (10 ** (level / 10) for level in (left_db, right_db, sum_db))
    if left <= 0.0 or right <= 0.0:
        # Silence can't cancel; one silent ear has nothing to cancel against
        return 1.0 if left == right else 0.0
    shared = (both - left - right) / 2.0
    return max(-1.0, min(1.0, shared / math.sqrt(left * right)))


def check_output(
    toolchain: FFmpegToolchain, path: Path, *, cancel: threading.Event | None = None
) -> QualityReport:
    """Measure the finished file's loudness, and how alike its two ears are.

    Setting cancel stops the measurement and raises ConversionError.
    """
    result = run_capture(
        [
            *ffmpeg_prefix(toolchain.ffmpeg, log="info"),
            "-i",
            str(path),
            "-filter_complex",
            "[0:a:0]asplit[a][b];"
            "[a]ebur128=peak=true:framelog=verbose[sa];"
            f"[b]{_K_WEIGHTING},pan=3c|c0=c0|c1=c1|c2=c0+c1,"
            "astats=measure_perchannel=RMS_level:measure_overall=none[sb]",
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
        cancel=cancel,
    )
    summaries = ebur128_summaries(result.stderr)
    levels = [float(value) for value in _RMS_LINE.findall(result.stderr)]
    if not summaries or len(levels) != 3:
        raise ConversionError("FFmpeg did not report a loudness measurement")
    stereo = parse_ebur128_summary(summaries[0])
    return QualityReport(
        integrated_lufs=stereo.integrated_lufs,
        true_peak_db=stereo.true_peak_db,
        range_lu=stereo.range_lu,
        correlation=correlation_from_levels(*levels),
    )
