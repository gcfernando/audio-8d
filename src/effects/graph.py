# Developed by ::> Gehan Fernando
"""Builds the FFmpeg -filter_complex graph that makes the 8D mix.

For each source (the song, or its vocal and music stems):

  song -> mid (L+R) -> crossover -> bass .............................. middle
                                  -> timing band -> 9 delay taps -+
                                  -> presence / height / air -----+-> x gains -> L R
       -> side (L-R), bass removed ....................... kept, a little, as is
       -> mid ............................................ room reverb (afir)

The gains come from a second input: a 200 Hz float WAV written by
control.py, upsampled smoothly to the audio rate. Everything is then mixed,
turned to the loudness target, and caught by a limiter.
"""

from dataclasses import dataclass

from ..core.settings import EffectConfig
from .head import (
    BAND_SPLITS_HZ,
    DELAY_TAPS,
    MAX_ITD_SECONDS,
    tap_spacing_samples,
    widest_itd,
)
from .levels import EXACT_MODE_MARGIN_DB
from .reverb import room_for

# How much of the song's original left/right difference is kept, unmoved
SIDE_KEEP = 0.25
# Without a loudness goal, room for the near ear's briefly brighter peaks
NATURAL_HEADROOM_DB = 3.0
# The side signal never carries bass, which would only muddy the middle
_SIDE_HIGHPASS_HZ = 120.0
# The reverb skips the low end so the room never booms
_ROOM_HIGHPASS_HZ = 180.0
# Removes a source's DC offset and inaudible rumble, which only waste headroom
SUBSONIC_HZ = 5.0
# How far the taps' widest ear gap may miss a real head's before a finer rate is used
_ITD_TOLERANCE = 0.15

# Every filter the graph can use; checked against the FFmpeg build up front
GRAPH_FILTERS = frozenset(
    {
        "aformat",
        "aresample",
        "asplit",
        "pan",
        "acrossover",
        "adelay",
        "amerge",
        "amultiply",
        "highpass",
        "amix",
        "afir",
        "volume",
        "alimiter",
    }
)


@dataclass(frozen=True, slots=True)
class Source:
    """One audio input and the inputs carrying its movement gains."""

    audio_input: int
    # Two for the 3D engine (delay taps, bands), one for plain panning
    control_inputs: tuple[int, ...]
    # A one-channel song, which is copied to both ears at its full level
    mono: bool = False
    # Its own sample rate when it differs from the song's (the singer's stems)
    rate: int | None = None


@dataclass(frozen=True, slots=True)
class GraphInputs:
    """Which FFmpeg input (-i) holds what."""

    sources: tuple[Source, ...]
    # The reverb's impulse response, or None when ambience is 0
    room_input: int | None = None


def to_stereo(mono: bool) -> str:
    """Filters that make a mono song stereo at full level ('' for everything else)."""
    # FFmpeg's own upmix lowers each side by 3 dB; players copy mono at full level
    return "pan=stereo|c0=c0|c1=c0," if mono else ""


def _mono_mid(label: str) -> str:
    """Fold stereo to its middle (the part both speakers share)."""
    return f"[{label}]pan=mono|c0=0.5*c0+0.5*c1"


def _ear_sum(first: int, count: int) -> str:
    """'c0+c1+...' for one ear's block of channels."""
    return "+".join(f"c{channel}" for channel in range(first, first + count))


def timing_rate(sample_rate: int) -> int:
    """The lower rate the timing band runs at; it only holds sound below 1.2 kHz."""
    for divisor in (4, 2):
        low = sample_rate // divisor
        # Whole-sample taps at 8 or 16 kHz would stretch the ear gap to 0.875 ms
        itd_error = abs(widest_itd(low) / MAX_ITD_SECONDS - 1.0)
        if sample_rate % divisor == 0 and low >= 8000 and itd_error <= _ITD_TOLERANCE:
            return low
    return sample_rate


def _weighted_stack(prefix: str, name: str, inputs: list[str], gains: str) -> str:
    """Copy the pieces once per ear, multiply by the gains, sum each ear."""
    count = len(inputs)
    return (
        "".join(f"[{label}]" for label in inputs)
        + f"amerge=inputs={count},asplit=2[{prefix}{name}0][{prefix}{name}1];"
        + f"[{prefix}{name}0][{prefix}{name}1]amerge=inputs=2[{prefix}{name}s];"
        + f"[{prefix}{name}s][{gains}]amultiply,"
        + f"pan=stereo|c0={_ear_sum(0, count)}|c1={_ear_sum(count, count)}"
    )


def _spatial_3d(
    prefix: str, config: EffectConfig, sample_rate: int, gains: tuple[str, str]
) -> list[str]:
    """Split into bands, delay the timing band, then weight every piece per ear."""
    splits = ([int(config.bass_hz)] if config.bass_hz else []) + list(BAND_SPLITS_HZ)
    bands = ([f"{prefix}bass"] if config.bass_hz else []) + [
        f"{prefix}{name}" for name in ("low", "presence", "height", "air")
    ]
    low_rate = timing_rate(sample_rate)
    spacing = tap_spacing_samples(low_rate)
    taps = [f"{prefix}tap{index}" for index in range(DELAY_TAPS)]
    lines = [
        _mono_mid(f"{prefix}in")
        + f",acrossover=split={' '.join(map(str, splits))}:order=4th"
        + "".join(f"[{band}]" for band in bands),
        f"[{prefix}low]aresample={low_rate},"
        f"aformat=sample_fmts=fltp:sample_rates={low_rate}:channel_layouts=mono,"
        f"asplit={DELAY_TAPS}" + "".join(f"[{tap}]" for tap in taps),
    ]
    delayed = [taps[0]]
    for index in range(1, DELAY_TAPS):
        lines.append(
            f"[{taps[index]}]adelay=delays={index * spacing}S:all=1[{prefix}d{index}]"
        )
        delayed.append(f"{prefix}d{index}")
    low_gains, high_gains = gains
    lines += [
        _weighted_stack(prefix, "lo", delayed, low_gains)
        + f",aresample={sample_rate}[{prefix}lowmoved]",
        _weighted_stack(
            prefix,
            "hi",
            [f"{prefix}presence", f"{prefix}height", f"{prefix}air"],
            high_gains,
        )
        + f"[{prefix}highmoved]",
        # The quarter-rate trip rounds the length up; the high bands keep it exact
        f"[{prefix}highmoved][{prefix}lowmoved]amix=inputs=2:normalize=0:"
        f"duration=first[{prefix}moved]",
    ]
    return lines


def _spatial_pan(prefix: str, config: EffectConfig, control: str) -> list[str]:
    """Plain panning: one gain per ear on everything above the bass."""
    if config.bass_hz:
        first = (
            _mono_mid(f"{prefix}in")
            + f",acrossover=split={int(config.bass_hz)}:order=4th"
            + f"[{prefix}bass][{prefix}high]"
        )
    else:
        first = _mono_mid(f"{prefix}in") + f"[{prefix}high]"
    return [
        first,
        f"[{prefix}high]asplit=2[{prefix}h0][{prefix}h1]",
        f"[{prefix}h0][{prefix}h1]amerge=inputs=2[{prefix}stack]",
        f"[{prefix}stack][{control}]amultiply,pan=stereo|c0=c0|c1=c1[{prefix}moved]",
    ]


def _unmoved(prefix: str, config: EffectConfig) -> list[str]:
    """The centred bass plus a little of the song's own width, both left in place."""
    lines = [
        f"[{prefix}side]pan=mono|c0=0.5*c0-0.5*c1,"
        f"highpass=f={_SIDE_HIGHPASS_HZ:g}:poles=2[{prefix}width]"
    ]
    if config.bass_hz:
        lines.append(
            f"[{prefix}bass][{prefix}width]amerge=inputs=2,"
            f"pan=stereo|c0=c0+{SIDE_KEEP}*c1|c1=c0-{SIDE_KEEP}*c1[{prefix}still]"
        )
    else:
        lines.append(
            f"[{prefix}width]pan=stereo|c0={SIDE_KEEP}*c0|c1=-{SIDE_KEEP}*c0"
            f"[{prefix}still]"
        )
    return lines


def _source_lines(
    index: int,
    source: Source,
    config: EffectConfig,
    *,
    sample_rate: int,
    source_rate: int | None,
    with_room: bool,
) -> list[str]:
    """Everything one source goes through, ending in [sNmoved] and [sNstill]."""
    prefix = f"s{index}"
    rate = source.rate or source_rate
    resample = f",aresample={sample_rate}:filter_size=64" if rate != sample_rate else ""
    outputs = [f"{prefix}in", f"{prefix}side"] + (
        [f"{prefix}room"] if with_room else []
    )
    # 64-bit maths keeps the very low corner exact at high sample rates too
    subsonic = f",highpass=f={SUBSONIC_HZ:g}:poles=2:precision=f64"
    lines = [
        f"[{source.audio_input}:a]{to_stereo(source.mono)}"
        "aformat=sample_fmts=fltp:channel_layouts=stereo"
        f"{resample}{subsonic},asplit={len(outputs)}"
        + "".join(f"[{name}]" for name in outputs),
    ]
    if config.engine == "3d":
        low, high = source.control_inputs
        lines += [
            f"[{low}:a]aformat=sample_fmts=fltp,"
            f"aresample={timing_rate(sample_rate)}[{prefix}g0]",
            f"[{high}:a]aformat=sample_fmts=fltp,aresample={sample_rate}[{prefix}g1]",
        ]
        lines += _spatial_3d(
            prefix, config, sample_rate, (f"{prefix}g0", f"{prefix}g1")
        )
    else:
        lines.append(
            f"[{source.control_inputs[0]}:a]aformat=sample_fmts=fltp,"
            f"aresample={sample_rate}[{prefix}g0]"
        )
        lines += _spatial_pan(prefix, config, f"{prefix}g0")
    lines += _unmoved(prefix, config)
    return lines


def _room_lines(count: int, room_input: int, ambience: float) -> list[str]:
    """One shared room: the middle of every source, played through the reverb."""
    feeds = "".join(f"[s{index}room]" for index in range(count))
    joined = f"{feeds}amix=inputs={count}:normalize=0," if count > 1 else feeds
    wet = room_for(ambience).wet_gain
    return [
        f"{joined}pan=mono|c0=0.5*c0+0.5*c1,"
        f"highpass=f={_ROOM_HIGHPASS_HZ:g}:poles=2,pan=stereo|c0=c0|c1=c0[dry_room]",
        f"[dry_room][{room_input}:a]afir=irnorm=-1:irgain=1,volume={wet:.4f}[room]",
    ]


def _mix(
    config: EffectConfig, inputs: GraphInputs, sample_rate: int, source_rate: int | None
) -> list[str]:
    """Every source's lines, the room, and the final mix as [mix]."""
    with_room = inputs.room_input is not None and config.ambience > 0
    lines: list[str] = []
    parts: list[str] = []
    for index, source in enumerate(inputs.sources):
        lines += _source_lines(
            index,
            source,
            config,
            sample_rate=sample_rate,
            source_rate=source_rate,
            with_room=with_room,
        )
        parts += [f"[s{index}moved]", f"[s{index}still]"]
    if with_room:
        assert inputs.room_input is not None
        lines += _room_lines(len(inputs.sources), inputs.room_input, config.ambience)
        parts.append("[room]")
    lines.append(
        "".join(parts) + f"amix=inputs={len(parts)}:normalize=0:duration=first[mix]"
    )
    return lines


# Limiting at 2x catches peaks between samples; 4x gained only 0.1 dB for 20% more time
_TRUE_PEAK_FACTOR = 2
_TRUE_PEAK_RATE = 192000


def limiter_stage(ceiling: float, sample_rate: int) -> str:
    """Brick-wall limiter so movement and reverb peaks never clip the encoder."""
    limiter = (
        f"alimiter=limit={ceiling:.4f}:attack=5:release=50:level=false:latency=true"
    )
    factor = max(1, min(_TRUE_PEAK_FACTOR, _TRUE_PEAK_RATE // sample_rate))
    if factor == 1:
        return limiter
    fast = sample_rate * factor
    # Coming back down lifts a few peaks ~0.5 dB, so a last pass holds the ceiling
    return (
        f"aresample={fast}:filter_size=64,{limiter},"
        f"aresample={sample_rate}:filter_size=64,{limiter}"
    )


def finish_stages(
    config: EffectConfig,
    gain_db: float | None,
    peak_margin: bool | None = None,
    *,
    sample_rate: int,
    lossless: bool | None = None,
) -> str:
    """The loudness change and the limiter that end every mix, as one filter chain.

    peak_margin lowers the limiter's roof by 1 dB, for when it will be working:
    lossy encoders overshoot limited peaks a little. None means 'exact mode only'.
    lossless says whether the margin is skipped; None asks the config's format,
    and a preview saved as WAV passes the real format's answer instead.
    """
    stages = []
    ceiling = config.limiter_ceiling
    if gain_db is not None:
        # One exact volume change, measured beforehand, reaches the loudness target
        stages.append(f"volume={gain_db:.2f}dB")
        margin = config.exact_loudness if peak_margin is None else peak_margin
    else:
        # Nothing was measured, so leave headroom and assume the limiter will work
        stages.append(f"volume=-{NATURAL_HEADROOM_DB:g}dB")
        margin = True
    if lossless is None:
        lossless = config.is_lossless
    if margin and not lossless:
        # Lower the roof by the margin, but never below alimiter's 0.0625 minimum
        ceiling = max(0.0625, ceiling * 10 ** (-EXACT_MODE_MARGIN_DB / 20))
    # The limiter goes last so it guards exactly what reaches the encoder
    stages.append(limiter_stage(ceiling, sample_rate))
    return ",".join(stages)


def build_graph(
    config: EffectConfig,
    inputs: GraphInputs,
    *,
    sample_rate: int,
    source_rate: int | None = None,
    gain_db: float | None = None,
    peak_margin: bool | None = None,
    lossless: bool | None = None,
) -> str:
    """The -filter_complex text for a one-pass encode; its output label is [out]."""
    config.validate()
    lines = _mix(config, inputs, sample_rate, source_rate)
    finish = finish_stages(
        config, gain_db, peak_margin, sample_rate=sample_rate, lossless=lossless
    )
    lines.append(f"[mix]{finish}[out]")
    return ";".join(lines)


def build_finish_graph(
    config: EffectConfig,
    mix_input: int,
    gain_db: float | None,
    peak_margin: bool | None = None,
    *,
    sample_rate: int,
    lossless: bool | None = None,
) -> str:
    """The second pass: the already-made mix (a float WAV), turned up and limited."""
    finish = finish_stages(
        config, gain_db, peak_margin, sample_rate=sample_rate, lossless=lossless
    )
    return f"[{mix_input}:a]aformat=sample_fmts=fltp,{finish}[out]"


def build_measure_graph(
    config: EffectConfig,
    inputs: GraphInputs,
    *,
    sample_rate: int,
    source_rate: int | None = None,
) -> str:
    """The same mix with an EBU R128 meter at the end instead of the limiter."""
    config.validate()
    lines = _mix(config, inputs, sample_rate, source_rate)
    # framelog=verbose hides the per-frame lines, so only the final summary is printed
    lines.append("[mix]ebur128=peak=true:framelog=verbose[out]")
    return ";".join(lines)
