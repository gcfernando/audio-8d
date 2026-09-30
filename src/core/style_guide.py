# Developed by ::> Gehan Fernando
"""What each style is for, in words anyone can follow (no audio terms needed).

Every style gets a short purpose, what it is best for, and what to expect.
Built-in styles are described by hand; your own styles are described by the
built-in style they sound closest to, measured from their real settings.
"""

import math
from dataclasses import dataclass

from .presets import PRESETS, RECOMMENDED_PRESET, Preset
from .settings import EffectConfig


@dataclass(frozen=True, slots=True)
class StyleGuide:
    """The plain-word description of one style."""

    purpose: str
    best_for: str
    expect: str
    # True when the style is a safe pick for almost any music
    safe: bool = False


GUIDES: dict[str, StyleGuide] = {
    "studio": StyleGuide(
        "Balanced movement that works well with most music.",
        "Most music, mixed playlists, or when you are unsure.",
        "The music circles your head at a comfortable pace with a touch of room.",
        safe=True,
    ),
    "gentle": StyleGuide(
        "Subtle, faithful movement that stays out of the way.",
        "Acoustic, folk and singer-songwriter music.",
        "Soft movement with a natural room sound; the recording stays in charge.",
        safe=True,
    ),
    "front": StyleGuide(
        "The music never goes behind you: it sways in front, like a pair of speakers.",
        "Jazz, classical and live recordings, long listening, or if circling "
        "distracts you.",
        "The band stays ahead of you with the singer in the middle; nothing goes "
        "behind your head.",
        safe=True,
    ),
    "classic": StyleGuide(
        "Audio8D's earlier 3D sound: like Studio, a touch stronger and roomier.",
        "Anyone who liked earlier versions of Audio8D.",
        "Noticeable circling with a little more room sound than Studio.",
        safe=True,
    ),
    "groove": StyleGuide(
        "Loops around each ear in time with the beat.",
        "Dance, electronic, hip-hop and pop.",
        "Lively figure-8 movement that follows the rhythm.",
    ),
    "smooth": StyleGuide(
        "Slow, relaxed movement.",
        "Lo-fi, chill and background music.",
        "A calm, unhurried circle; easy to listen to for hours.",
        safe=True,
    ),
    "strong": StyleGuide(
        "Big, obvious movement with more room.",
        "Rock, metal and EDM with big drops.",
        "Wide, dramatic movement; can tire the ears on long albums.",
    ),
    "spacious": StyleGuide(
        "Wide and airy, like a large room.",
        "Film scores, ambient music and slow ballads.",
        "Plenty of room sound around a steady circle.",
    ),
    "sky": StyleGuide(
        "Drifts up over your head and back down.",
        "Ambient, chill-out and meditation music.",
        "Floating, dreamy movement that also rises above you.",
    ),
    "voice": StyleGuide(
        "For speech: a slow sweep in front of you with no room sound.",
        "Podcasts, audiobooks and spoken word.",
        "Voices stay clear and close; the movement is subtle.",
        safe=True,
    ),
    "whirlwind": StyleGuide(
        "A very fast spin: fun for a moment, but it may feel dizzying.",
        "Short clips and ringtones.",
        "Rapid circling around your head.",
    ),
    "speakers": StyleGuide(
        "Gentle left-right movement that also works without headphones.",
        "Speakers and car stereos.",
        "Softer movement that sounds right on any speaker.",
        safe=True,
    ),
    "retro": StyleGuide(
        "The old left-right 'ping-pong' sound of the first Audio8D.",
        "Nostalgia and short clips.",
        "Simple left-right panning; the bass moves too, so it is not for long "
        "listening.",
    ),
}


def sound_traits(config: EffectConfig) -> tuple[float, ...]:
    """How a style moves, as numbers that can be compared between styles."""
    return (
        config.intensity,
        # Spin speed compared on a log scale: 4 s vs 8 s is as big as 8 s vs 16 s
        math.log2(config.rotation_seconds) / 2,
        config.ambience,
        1.0 if config.beat_sync else 0.0,
        config.elevation,
        {"circle": 0.0, "figure8": 0.5, "wander": 0.7, "arc": 1.0}[config.path],
        1.0 if config.engine == "pan" else 0.0,
    )


def sound_distance(first: EffectConfig, second: EffectConfig) -> float:
    """0 for styles that move the same way; bigger the more they differ."""
    return math.dist(sound_traits(first), sound_traits(second))


def closest_built_in(config: EffectConfig) -> str:
    """The built-in style that moves most like config."""
    # Ties go to the earlier style in the list, so the answer never wobbles
    return min(GUIDES, key=lambda name: sound_distance(config, PRESETS[name].config))


def same_sound(first: EffectConfig, second: EffectConfig) -> bool:
    """True when two configs move identically (they may still save different files)."""
    return sound_distance(first, second) < 1e-9


def guide_for(preset: Preset) -> StyleGuide:
    """The description of any style, built-in or your own."""
    if not preset.custom and preset.name in GUIDES:
        return GUIDES[preset.name]
    twin = closest_built_in(preset.config)
    twin_guide = GUIDES[twin]
    purpose = preset.summary.strip() or "Your own style."
    if not purpose.endswith((".", "!", "?")):
        purpose += "."
    suits = twin_guide.best_for[:1].lower() + twin_guide.best_for[1:]
    return StyleGuide(
        purpose=purpose,
        best_for=f"Moves most like {PRESETS[twin].label}: {suits}",
        expect=twin_guide.expect,
    )


def is_recommended(preset: Preset) -> bool:
    """True for the style Audio8D recommends when nothing else is known."""
    return not preset.custom and preset.name == RECOMMENDED_PRESET
