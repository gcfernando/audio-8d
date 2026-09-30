# Developed by ::> Gehan Fernando
"""Assembles the exact ffmpeg argument lists used for measuring and encoding."""

from dataclasses import dataclass
from pathlib import Path

from ..core.settings import EffectConfig
from ..core.types import Trim

# Formats whose files can hold album art next to the sound
COVER_FORMATS = frozenset({"mp3", "flac", "m4a"})

# The encoder each output format uses; toolchain.py checks the build has it
ENCODERS = {
    "mp3": "libmp3lame",
    "m4a": "aac",
    "opus": "libopus",
    "flac": "flac",
    "wav": "pcm_s24le",
}

# Bitrates used when none is chosen: transparent for AAC and Opus
_DEFAULT_KBPS = {"m4a": 256, "opus": 192}


@dataclass(frozen=True, slots=True)
class InputFile:
    """One -i input, optionally trimmed to part of the song."""

    path: Path
    trim: Trim | None = None


def ffmpeg_prefix(ffmpeg: Path, *, log: str = "error") -> list[str]:
    """The start of every FFmpeg command: quiet, no banner, never reads the keyboard.

    log="info" keeps the meters' summaries (ebur128) while hiding progress lines.
    """
    prefix = [str(ffmpeg), "-hide_banner", "-nostdin"]
    return prefix + (["-nostats"] if log == "info" else ["-loglevel", log])


def _input_arguments(inputs: list[InputFile]) -> list[str]:
    """-ss / -t before each -i, so only the chosen part is ever decoded."""
    arguments: list[str] = []
    for item in inputs:
        if item.trim is not None and item.trim.start:
            arguments += ["-ss", f"{item.trim.start:.3f}"]
        if item.trim is not None and item.trim.end is not None:
            length = item.trim.end - (item.trim.start or 0.0)
            arguments += ["-t", f"{max(0.0, length):.3f}"]
        arguments += ["-i", str(item.path)]
    return arguments


def _mp3_quality_arguments(quality: int, bitrate: int | None) -> list[str]:
    """A constant bitrate when one is set, otherwise LAME's variable quality scale."""
    arguments = ["-b:a", f"{bitrate}k"] if bitrate else ["-q:a", str(quality)]
    # LAME's recommended careful mode; -q 0 is twice as slow for no audible gain
    if bitrate or quality == 0:
        arguments += ["-compression_level", "2"]
    return arguments


def encoder_arguments(config: EffectConfig) -> list[str]:
    """Codec and quality options for the chosen output format."""
    fmt = config.output_format
    codec = ["-c:a", ENCODERS[fmt]]
    if fmt == "mp3":
        # ID3v2.3 plus a v1 tag is what car stereos and older players read best
        return [
            *codec,
            *_mp3_quality_arguments(config.quality, config.bitrate),
            "-id3v2_version",
            "3",
            "-write_id3v1",
            "1",
        ]
    if fmt == "m4a":
        kbps = config.bitrate or _DEFAULT_KBPS[fmt]
        # faststart puts the index first, so players can start straight away
        return [*codec, "-b:a", f"{kbps}k", "-movflags", "+faststart"]
    if fmt == "opus":
        kbps = config.bitrate or _DEFAULT_KBPS[fmt]
        return [*codec, "-b:a", f"{kbps}k", "-vbr", "on", "-compression_level", "10"]
    if fmt == "flac":
        # 24-bit keeps the quiet reverb tail and fades perfectly smooth
        return [
            *codec,
            "-compression_level",
            "8",
            "-sample_fmt",
            "s32",
            "-bits_per_raw_sample",
            "24",
        ]
    return codec


def build_encode_command(  # pylint: disable=too-many-arguments
    ffmpeg: Path,
    inputs: list[InputFile],
    output_file: Path,
    *,
    filter_graph: str,
    config: EffectConfig,
    sample_rate: int,
    cover_art: bool = False,
    title: str | None = None,
    tags_on_stream: bool = False,
) -> list[str]:
    """The argv that renders the song through the graph into output_file.

    Input 0 is always the original song, so its tags and album art are copied;
    tags_on_stream reads them from its audio stream (Ogg files keep them there).
    """
    command = [
        str(ffmpeg),
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        *_input_arguments(inputs),
        "-filter_complex",
        filter_graph,
        "-map",
        "[out]",
    ]
    if cover_art and config.output_format in COVER_FORMATS:
        # Copy the picture untouched and mark it as the cover, not as a video
        command += ["-map", "0:v:0", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
    # Carry over title, artist, album and friends from wherever the source keeps them
    command += ["-map_metadata", "0:s:a:0" if tags_on_stream else "0"]
    if title:
        command += ["-metadata", f"title={title}"]
    command += [
        *encoder_arguments(config),
        "-ar",
        str(sample_rate),
        "-ac",
        "2",
        # Never let ffmpeg overwrite anything; publishing is handled by files.atomic
        "-n",
        str(output_file),
    ]
    return command


def build_measure_command(
    ffmpeg: Path, inputs: list[InputFile], filter_graph: str
) -> list[str]:
    """Play the song through the graph into nothing, logging the meter's summary."""
    return [
        str(ffmpeg),
        "-hide_banner",
        "-nostdin",
        # The meter's summary is logged at info level, so -loglevel error hides it
        "-loglevel",
        "info",
        *_input_arguments(inputs),
        "-filter_complex",
        filter_graph,
        "-map",
        "[out]",
        "-f",
        "null",
        "-",
    ]


def build_mix_command(
    ffmpeg: Path, inputs: list[InputFile], filter_graph: str, mix_file: Path
) -> list[str]:
    """Render the mix once into a 32-bit float WAV while its meter logs a summary.

    Float keeps every detail and every peak above 0 dBFS, so the second pass can
    turn it up or down and limit it without any loss.
    """
    return [
        str(ffmpeg),
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "info",
        *_input_arguments(inputs),
        "-filter_complex",
        filter_graph,
        "-map",
        "[out]",
        "-c:a",
        "pcm_f32le",
        "-y",
        str(mix_file),
    ]
