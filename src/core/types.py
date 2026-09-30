# Developed by ::> Gehan Fernando
"""Plain data types passed between the Audio8D layers."""

from dataclasses import dataclass

# Codecs that store sound perfectly, so the final encode is the only lossy step
LOSSLESS_CODECS = frozenset(
    {
        "flac",
        "alac",
        "wavpack",
        "ape",
        "tta",
        "truehd",
        "mlp",
        "shorten",
        "mp4als",
        "tak",
    }
)


@dataclass(frozen=True, slots=True)
class AudioStreamInfo:  # pylint: disable=too-many-instance-attributes
    """What FFprobe told us about the first audio stream in the source file."""

    codec_name: str
    channels: int
    sample_rate: int | None
    duration_seconds: float | None
    # Bits per second of the source stream, when the file says so
    bit_rate: int | None = None
    # The song's own title tag, if it has one
    title: str | None = None
    # True when the file carries album art (an attached picture)
    has_cover_art: bool = False
    # The file's own tags, used to suggest a style (None when the file has none)
    genre: str | None = None
    artist: str | None = None
    album: str | None = None
    # The stored bit depth of a lossless source (lossy sources have none)
    bits_per_sample: int | None = None
    # FFmpeg's sample format (s16, s32, fltp…) and channel layout, when known
    sample_format: str | None = None
    channel_layout: str | None = None
    # True when the tags sit on the audio stream (Ogg: Opus, Vorbis), not the file
    tags_on_stream: bool = False

    @property
    def is_lossless(self) -> bool:
        """True for FLAC, ALAC, WAV/AIFF (PCM) and the other perfect-copy formats."""
        return self.codec_name in LOSSLESS_CODECS or self.codec_name.startswith("pcm_")


@dataclass(frozen=True, slots=True)
class Trim:
    """The part of the song to keep; None means from the start / to the end."""

    start: float | None = None
    end: float | None = None

    @property
    def is_set(self) -> bool:
        """True when either end was given."""
        return self.start is not None or self.end is not None

    def length(self, total: float | None) -> float | None:
        """Seconds that remain after trimming a song lasting `total` seconds."""
        start = self.start or 0.0
        end = self.end if self.end is not None else total
        if end is None:
            return None
        if total is not None:
            end = min(end, total)
        return max(0.0, end - start)
