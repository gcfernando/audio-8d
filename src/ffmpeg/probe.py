# Developed by ::> Gehan Fernando
"""Reads source-stream metadata through FFprobe's JSON output."""

import json
import threading
from pathlib import Path
from typing import Any

from ..core.errors import InputValidationError
from ..core.types import AudioStreamInfo
from .runner import run_capture
from .toolchain import FFmpegToolchain

# The tags worth reading: the title for the new file, the rest to suggest a style
_TAGS = "title,genre,artist,album_artist,album"
# Reading a file's details takes well under a second; a stuck network drive doesn't
PROBE_TIMEOUT = 60.0


def _tag(tags: dict[str, Any], name: str) -> str | None:
    """A tag by name, whatever letter case the file used for it."""
    for key, value in tags.items():
        if key.lower() == name and str(value).strip():
            return str(value).strip()
    return None


def _optional_number(value: Any, kind: type) -> Any:
    """int/float from FFprobe text, or None for missing and 'N/A' values."""
    if value in (None, "", "N/A"):
        return None
    return kind(value)


def _tags_of(
    container: dict[str, Any], stream: dict[str, Any]
) -> tuple[dict[str, Any], bool]:
    """All the source's tags, and whether they live on the audio stream."""
    file_tags = container.get("tags") or {}
    stream_tags = stream.get("tags") or {}
    # Ogg files (Opus, Vorbis, Ogg FLAC) keep every tag on the audio stream
    ogg = "ogg" in str(container.get("format_name") or "").split(",")
    return {**file_tags, **stream_tags}, ogg or (bool(stream_tags) and not file_tags)


def _has_cover(streams: list[dict[str, Any]]) -> bool:
    """Whether the file carries album art as an attached picture."""
    return any(
        s.get("codec_type") == "video"
        and (s.get("disposition") or {}).get("attached_pic") == 1
        for s in streams
    )


def parse_probe_output(raw_json: str) -> AudioStreamInfo:
    """Turn FFprobe JSON into an AudioStreamInfo or reject unusable input."""
    try:
        payload: dict[str, Any] = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise InputValidationError("FFprobe returned malformed JSON") from exc

    streams = payload.get("streams") or []
    # Older callers only asked for audio streams, so a missing type means audio
    audio = [s for s in streams if s.get("codec_type", "audio") == "audio"]
    if not audio:
        raise InputValidationError(
            "The input file does not contain a usable audio stream"
        )

    stream = audio[0]
    container = payload.get("format") or {}
    tags, on_stream = _tags_of(container, stream)

    try:
        channels = int(stream["channels"])
        sample_rate = _optional_number(stream.get("sample_rate"), int)
        # Raw streams and some live captures report "N/A" instead of a length
        duration = _optional_number(container.get("duration"), float)
        codec_name = str(stream.get("codec_name") or "unknown")
        # Some containers only store the whole file's bitrate, so fall back to that
        bit_rate = _optional_number(
            stream.get("bit_rate") or container.get("bit_rate"), int
        )
        # Lossless files say their real depth; lossy ones decode to float (no depth)
        bits = _optional_number(
            stream.get("bits_per_raw_sample") or stream.get("bits_per_sample"), int
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InputValidationError(
            "FFprobe returned incomplete or invalid audio metadata"
        ) from exc

    if channels < 1:
        raise InputValidationError("The input audio reports an invalid channel count")

    return AudioStreamInfo(
        codec_name=codec_name,
        channels=channels,
        # Some broken files report a rate of 0, which means the same as no rate
        sample_rate=sample_rate if sample_rate and sample_rate > 0 else None,
        duration_seconds=duration,
        bit_rate=bit_rate,
        title=_tag(tags, "title"),
        has_cover_art=_has_cover(streams),
        genre=_tag(tags, "genre"),
        artist=_tag(tags, "artist") or _tag(tags, "album_artist"),
        album=_tag(tags, "album"),
        bits_per_sample=bits or None,
        sample_format=str(stream.get("sample_fmt") or "") or None,
        channel_layout=str(stream.get("channel_layout") or "") or None,
        tags_on_stream=on_stream,
    )


def probe_audio(
    toolchain: FFmpegToolchain,
    input_file: Path,
    *,
    cancel: threading.Event | None = None,
) -> AudioStreamInfo:
    """Inspect the first audio stream of input_file, and whether it has album art."""
    result = run_capture(
        [
            str(toolchain.ffprobe),
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,channels,sample_rate,bit_rate,"
            "bits_per_raw_sample,bits_per_sample,sample_fmt,channel_layout"
            ":stream_disposition=attached_pic"
            f":stream_tags={_TAGS}:format=format_name,duration,bit_rate"
            f":format_tags={_TAGS}",
            "-of",
            "json",
            str(input_file),
        ],
        error_type=InputValidationError,
        timeout=PROBE_TIMEOUT,
        cancel=cancel,
    )
    return parse_probe_output(result.stdout)
