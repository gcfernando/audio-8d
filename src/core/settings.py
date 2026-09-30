# Developed by ::> Gehan Fernando
"""User-facing knobs for the 8D effect and the encoder."""

from dataclasses import dataclass, replace

from .errors import InputValidationError

# The constant bitrates that make sense for music; 320 is the highest MP3 allows
BITRATES = (128, 160, 192, 224, 256, 320)

# Output formats, each with the file extension it is saved under
FORMAT_EXTENSIONS = {
    "mp3": ".mp3",
    "flac": ".flac",
    "wav": ".wav",
    "m4a": ".m4a",
    "opus": ".opus",
}
LOSSLESS_FORMATS = frozenset({"flac", "wav"})

# "3d" places the sound around your head; "pan" is plain left-right volume panning
ENGINES = ("3d", "pan")
# How the sound travels: a full circle, a front arc, loops around each ear, or drifting
PATHS = ("circle", "arc", "figure8", "wander")
DIRECTIONS = ("clockwise", "counterclockwise")
# "move" spins the whole song; "center" keeps the singer near the middle (stems)
VOCAL_MODES = ("move", "center")

# The settings that decide how the file is saved rather than how the music sounds
OUTPUT_FIELDS = (
    "output_format",
    "bitrate",
    "quality",
    "loudness_target",
    "match_loudness",
    "exact_loudness",
    "limiter_ceiling",
)

# A time and a value, e.g. (60.0, 6.0) = "at 1:00, spin once every 6 seconds"
Keyframes = tuple[tuple[float, float], ...]


def _check_keyframes(
    name: str, frames: Keyframes, low: float, high: float, unit: str
) -> None:
    """Keyframes must be in time order and every value inside the allowed range."""
    times = [time for time, _ in frames]
    if any(time < 0 for time in times) or times != sorted(times):
        raise InputValidationError(
            f"{name} times must start at 0 or later and go forwards"
        )
    if any(not low <= value <= high for _, value in frames):
        raise InputValidationError(
            f"{name} values must be between {low:g} and {high:g}{unit}"
        )


@dataclass(frozen=True, slots=True)
class EffectConfig:  # pylint: disable=too-many-instance-attributes
    """Everything that shapes how the finished track sounds."""

    rotation_seconds: float = 8.0
    intensity: float = 0.85
    ambience: float = 0.30
    limiter_ceiling: float = 0.95
    # LAME's variable quality scale (0 best, 9 smallest); MP3 only
    quality: int = 2
    # None keeps the natural level; a LUFS value (e.g. -14) matches streaming loudness
    loudness_target: float | None = None
    # None uses the variable quality scale; a kbps value locks a constant bitrate
    bitrate: int | None = None
    # True hits the loudness target even if the limiter must shave the loudest peaks
    exact_loudness: bool = False
    engine: str = "3d"
    # Everything below this frequency stays in the middle; 0 lets the bass move too
    bass_hz: float = 120.0
    path: str = "circle"
    direction: str = "clockwise"
    # 0 stays at ear level; higher values let the sound drift up over your head
    elevation: float = 0.0
    # The movement grows in over this many seconds and settles back at the end
    fade_seconds: float = 3.0
    # Optional changes over time; empty means "use rotation_seconds / intensity"
    speed_curve: Keyframes = ()
    intensity_curve: Keyframes = ()
    # Snap one full circle to a whole number of bars of the song's detected beat
    beat_sync: bool = False
    # A known tempo skips detection (and switches beat sync on)
    bpm: float | None = None
    vocals: str = "move"
    output_format: str = "mp3"
    # Match the original song's own loudness instead of a fixed target
    match_loudness: bool = False

    @property
    def wants_loudness(self) -> bool:
        """True when a measured loudness change is part of the conversion."""
        return self.loudness_target is not None or self.match_loudness

    @property
    def extension(self) -> str:
        """File extension for the chosen output format, e.g. '.mp3'."""
        return FORMAT_EXTENSIONS[self.output_format]

    @property
    def is_lossless(self) -> bool:
        """True for FLAC and WAV, which keep every detail of the 8D mix."""
        return self.output_format in LOSSLESS_FORMATS

    def validate(self) -> None:  # pylint: disable=too-many-branches
        """Raise InputValidationError if any value is outside its safe range."""
        if not 2.0 <= self.rotation_seconds <= 100.0:
            raise InputValidationError(
                "rotation_seconds must be between 2.0 and 100.0 seconds"
            )

        if not 0.0 <= self.intensity <= 1.0:
            raise InputValidationError("intensity must be between 0.0 and 1.0")

        if not 0.0 <= self.ambience <= 1.0:
            raise InputValidationError("ambience must be between 0.0 and 1.0")

        # 0.0625 is the lowest ceiling alimiter accepts (about -24 dBFS)
        if not 0.0625 <= self.limiter_ceiling <= 1.0:
            raise InputValidationError("limiter_ceiling must be between 0.0625 and 1.0")

        if not 0 <= self.quality <= 9:
            raise InputValidationError("quality must be an integer from 0 to 9")

        # -30 is whisper-quiet and -5 is louder than any real master
        if (
            self.loudness_target is not None
            and not -30.0 <= self.loudness_target <= -5.0
        ):
            raise InputValidationError(
                "loudness_target must be between -30 and -5 LUFS"
            )

        if self.bitrate is not None and self.bitrate not in BITRATES:
            raise InputValidationError(
                "bitrate must be one of " + ", ".join(map(str, BITRATES)) + " kbps"
            )

        choices = (
            ("engine", self.engine, ENGINES),
            ("path", self.path, PATHS),
            ("direction", self.direction, DIRECTIONS),
            ("vocals", self.vocals, VOCAL_MODES),
            ("output_format", self.output_format, tuple(FORMAT_EXTENSIONS)),
        )
        for name, value, allowed in choices:
            if value not in allowed:
                raise InputValidationError(
                    f"{name} must be one of: {', '.join(allowed)}"
                )

        # 0 switches the split off; above 250 Hz the kick drum's punch would freeze
        if self.bass_hz != 0 and not 40.0 <= self.bass_hz <= 250.0:
            raise InputValidationError("bass_hz must be 0 (off) or between 40 and 250")

        if not 0.0 <= self.elevation <= 1.0:
            raise InputValidationError("elevation must be between 0.0 and 1.0")

        if not 0.0 <= self.fade_seconds <= 30.0:
            raise InputValidationError("fade_seconds must be between 0 and 30 seconds")

        if self.bpm is not None and not 40.0 <= self.bpm <= 240.0:
            raise InputValidationError("bpm must be between 40 and 240")

        _check_keyframes("speed_curve", self.speed_curve, 2.0, 100.0, " seconds")
        _check_keyframes("intensity_curve", self.intensity_curve, 0.0, 1.0, "")


# Speakers blend both channels in the room, so deep 3D cues turn into odd colouring
SPEAKER_MAX_INTENSITY = 0.6


def speaker_safe(config: EffectConfig) -> EffectConfig:
    """A version of config that also sounds right on speakers and car stereos."""
    return replace(
        config,
        engine="pan",
        intensity=min(config.intensity, SPEAKER_MAX_INTENSITY),
        intensity_curve=tuple(
            (time, min(value, SPEAKER_MAX_INTENSITY))
            for time, value in config.intensity_curve
        ),
        elevation=0.0,
        bass_hz=config.bass_hz or 120.0,
    )
