# Developed by ::> Gehan Fernando
"""Sample rates and the single volume change that reaches a loudness target."""

import math

# The only sample rates the MP3 format can store
MP3_SAMPLE_RATES = frozenset(
    {8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000}
)

# ebur128 reports pure silence as -70 LUFS, so anything at or below it gets no gain
SILENCE_LUFS = -70.0

# Extra headroom in exact-loudness mode, since lossy decoding overshoots limited peaks
EXACT_MODE_MARGIN_DB = 1.0

# How much of the movement's own short peaks the limiter may trim (dynamics stay)
PEAK_ALLOWANCE_DB = 5.0

# Lossless files keep the source rate, up to this (higher is only wasted space)
_MAX_LOSSLESS_RATE = 192000

# The head model splits at 5 and 10 kHz, which only fit in audio of 32 kHz and up
MIN_PROCESSING_RATE = 32000


def _lifted_rate(source_rate: int) -> int:
    """A low source rate raised to the normal rate of its own family."""
    # Whole-number ratios keep the upsampling clean: 22.05 -> 44.1, 8/16/24 -> 48 kHz
    return 44100 if 44100 % source_rate == 0 else 48000


def mp3_sample_rate_for(source_rate: int | None) -> int:
    """Keep the source rate if MP3 can store it, else pick the closest family."""
    if source_rate is None:
        return 44100
    if source_rate < MIN_PROCESSING_RATE:
        return _lifted_rate(source_rate)
    if source_rate in MP3_SAMPLE_RATES:
        return source_rate
    # 88.2 and 176.4 kHz divide cleanly into 44.1 kHz; other hi-res rates land on 48 kHz
    if source_rate > 48000:
        return 44100 if source_rate % 44100 == 0 else 48000
    return 44100


def output_sample_rate(output_format: str, source_rate: int | None) -> int:
    """The rate the 8D mix is made at, which is also the rate that gets saved."""
    if output_format == "opus":
        # Opus always works at 48 kHz inside, whatever it is given
        return 48000
    if output_format in {"flac", "wav"}:
        if source_rate is None:
            return 44100
        if source_rate > _MAX_LOSSLESS_RATE:
            return 96000 if source_rate % 44100 else 88200
        if source_rate < MIN_PROCESSING_RATE:
            return _lifted_rate(source_rate)
        return source_rate
    # MP3 and AAC share the same sensible rates
    return mp3_sample_rate_for(source_rate)


def loudness_gain_db(
    measured_lufs: float,
    measured_peak_db: float,
    target_lufs: float,
    ceiling: float,
    *,
    exact: bool,
) -> float:
    """The one volume change that brings the 8D mix to its loudness target."""
    if measured_lufs <= SILENCE_LUFS:
        return 0.0
    gain = target_lufs - measured_lufs
    if exact:
        return gain
    # Stop at the allowance, so the limiter only ever trims the movement's peaks
    headroom = 20.0 * math.log10(ceiling) - measured_peak_db + PEAK_ALLOWANCE_DB
    return min(gain, headroom)
