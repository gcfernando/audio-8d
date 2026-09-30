# Developed by ::> Gehan Fernando
"""Ready-made sound styles, so nobody has to guess numbers.

A style decides only how the music moves and sounds. How the file is saved
(its format, quality and loudness) is chosen separately, so every style
starts from the same recommended output settings below.
"""

from dataclasses import dataclass, replace

from .settings import OUTPUT_FIELDS, EffectConfig


@dataclass(frozen=True, slots=True)
class Preset:
    """A named combination of settings with a one-line description."""

    name: str
    summary: str
    config: EffectConfig
    # True for styles the user saved with --save-style
    custom: bool = False

    @property
    def label(self) -> str:
        """The name people see: built-in styles capitalised (Studio), yours as saved."""
        return self.name if self.custom else self.name[:1].upper() + self.name[1:]


# The recommended way to save: best MP3 quality, music-app loudness, MP3-safe peaks
STANDARD_OUTPUT: dict[str, object] = {
    "output_format": "mp3",
    "bitrate": 320,
    "quality": 0,
    "loudness_target": -14.0,
    "match_loudness": False,
    "exact_loudness": False,
    "limiter_ceiling": 0.84,
}


# The peak limit that suits each kind of file: lossy encoders overshoot a little
LOSSY_LIMIT = 0.84
LOSSLESS_LIMIT = 0.89
# The High, Medium and Small quality of each lossy format, in kbps
QUALITY_TIERS = {
    "mp3": (320, 192, 128),
    "m4a": (256, 192, 128),
    "opus": (192, 160, 128),
}


def with_format(config: EffectConfig, output_format: str) -> EffectConfig:
    """Another file format, keeping the same quality tier and a peak limit that fits.

    'High' stays 'High' (MP3 320, M4A 256, Opus 192 kbps), and the peak limit
    follows the format unless it was set to something else on purpose.
    """
    changes: dict[str, object] = {"output_format": output_format}
    # FLAC and WAV have no tiers; the bitrate they keep is read as MP3's
    old_tiers = QUALITY_TIERS.get(config.output_format, QUALITY_TIERS["mp3"])
    new_tiers = QUALITY_TIERS.get(output_format)
    if new_tiers and config.bitrate in old_tiers:
        changes["bitrate"] = new_tiers[old_tiers.index(config.bitrate)]
    if config.limiter_ceiling in (LOSSY_LIMIT, LOSSLESS_LIMIT):
        lossless = output_format in ("flac", "wav")
        changes["limiter_ceiling"] = LOSSLESS_LIMIT if lossless else LOSSY_LIMIT
    return replace(config, **changes)  # type: ignore[arg-type]


def with_standard_output(config: EffectConfig) -> EffectConfig:
    """A style's sound, saved the recommended way."""
    return replace(config, **STANDARD_OUTPUT)  # type: ignore[arg-type]


def output_of(config: EffectConfig) -> dict[str, object]:
    """Only the file settings of a config (format, quality, loudness, peak limit)."""
    return {name: getattr(config, name) for name in OUTPUT_FIELDS}


def _style(**sound: object) -> EffectConfig:
    """A sound style: the given sound settings with the standard output."""
    return with_standard_output(EffectConfig(**sound))  # type: ignore[arg-type]


# Shown in this order by --list-styles; studio first because it is the one to pick
_ALL_PRESETS = (
    Preset(
        name="studio",
        summary="Balanced 3D movement that suits almost any song",
        config=_style(rotation_seconds=8.0, intensity=0.80, ambience=0.25),
    ),
    Preset(
        name="gentle",
        summary="Subtle, faithful movement with a natural room sound",
        config=_style(rotation_seconds=8.0, intensity=0.65, ambience=0.25),
    ),
    Preset(
        name="front",
        summary="Stays in front of you like a pair of speakers, swaying gently",
        # The arc never goes behind; 0.40 depth is about the ±30° of stereo speakers
        config=_style(rotation_seconds=16.0, intensity=0.40, ambience=0.25, path="arc"),
    ),
    Preset(
        name="classic",
        summary="Audio8D's earlier 3D sound: like studio, a touch stronger and roomier",
        config=_style(),
    ),
    Preset(
        name="groove",
        summary="Loops around each ear in time with the beat: dance, pop, hip-hop",
        config=_style(
            rotation_seconds=12.0,
            intensity=0.85,
            ambience=0.25,
            path="figure8",
            beat_sync=True,
        ),
    ),
    Preset(
        name="smooth",
        summary="Slow and relaxed: lo-fi, acoustic, background",
        config=_style(rotation_seconds=12.0, intensity=0.75, ambience=0.20),
    ),
    Preset(
        name="strong",
        summary="Big, obvious movement: pop, EDM, '8D video' feel",
        config=_style(rotation_seconds=8.0, intensity=0.95, ambience=0.35),
    ),
    Preset(
        name="spacious",
        summary="Roomy and atmospheric: ambient, cinematic, slow",
        config=_style(rotation_seconds=10.0, intensity=0.80, ambience=0.45),
    ),
    Preset(
        name="sky",
        summary="Drifts up over your head and back: chill, ambient",
        config=_style(
            rotation_seconds=12.0,
            intensity=0.80,
            ambience=0.45,
            elevation=0.7,
            path="wander",
        ),
    ),
    Preset(
        name="voice",
        summary="Gentle and dry: podcasts, audiobooks, meditation",
        config=_style(rotation_seconds=16.0, intensity=0.60, ambience=0.0, path="arc"),
    ),
    Preset(
        name="whirlwind",
        summary="Very fast spin: short clips and ringtones; may feel dizzying",
        config=_style(rotation_seconds=3.0, intensity=0.95, ambience=0.25),
    ),
    Preset(
        name="speakers",
        summary="Safe for speakers and car stereos, not just headphones",
        config=_style(engine="pan", intensity=0.55, ambience=0.20),
    ),
    Preset(
        name="retro",
        summary="The first Audio8D's left-right ping-pong; the bass moves too",
        config=_style(engine="pan", bass_hz=0.0, fade_seconds=0.0),
    ),
)

PRESETS: dict[str, Preset] = {preset.name: preset for preset in _ALL_PRESETS}
RECOMMENDED_PRESET = "studio"

# Older names that mixed a sound with a way of saving; still accepted, never listed
LEGACY_STYLES: dict[str, tuple[str, dict[str, object]]] = {
    "streaming": ("studio", {"exact_loudness": True}),
    "lossless": ("studio", {"output_format": "flac", "limiter_ceiling": 0.89}),
    "hifi": (
        "gentle",
        {
            "output_format": "flac",
            "limiter_ceiling": 0.89,
            "loudness_target": None,
            "match_loudness": True,
            "intensity": 0.75,
            "ambience": 0.20,
        },
    ),
}


def legacy_config(name: str) -> EffectConfig:
    """What an older style name meant: its sound, saved the way it used to be."""
    sound, output = LEGACY_STYLES[name]
    return replace(PRESETS[sound].config, **output)  # type: ignore[arg-type]
