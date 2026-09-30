# Developed by ::> Gehan Fernando
"""'Create your own style': plain questions turned into checked, named settings.

The window's Your styles page asks a few questions (what music, how much
movement, how fast, how much room); this module turns the answers into an
EffectConfig, suggests a name and a description, and checks the result before
it is saved. A style is only the sound, so nothing here asks about the file.
"""

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass, field

from . import display
from .core.presets import PRESETS, with_standard_output
from .core.settings import EffectConfig, speaker_safe
from .core.sound_levels import MOVEMENT, SPACE, SPEED
from .core.user_presets import name_key

# Each question's choices: the words people see -> the answer kept
MUSIC_CHOICES = {
    "Strong beat": "beat",
    "Calm": "calm",
    "Big and loud": "big",
    "Talking": "talk",
    "A bit of everything": "mixed",
}
# The same words (and values) as the Customize dialog and --movement, --speed, --space
MOVEMENT_CHOICES = {word: word.lower() for word in MOVEMENT.choices}
SPEED_CHOICES = {
    **{word: word.lower() for word in SPEED.choices},
    "With the beat": "beat",
}
ROOM_CHOICES = {word: word.lower() for word in SPACE.choices}
PLACE_CHOICES = {"Headphones": "headphones", "Speakers or a car too": "speakers"}

# The built-in style each kind of music starts from (it brings the right path)
_BASE_STYLE = {
    "beat": "groove",
    "calm": "smooth",
    "big": "strong",
    "talk": "voice",
    "mixed": "studio",
}
_MOVEMENT = {word.lower(): value for word, value in MOVEMENT.choices.items()}
_SPEED = {word.lower(): value for word, value in SPEED.choices.items()} | {"beat": 8.0}
_ROOM = {word.lower(): value for word, value in SPACE.choices.items()}
# Kept short, so a style name built from it stays readable
_MUSIC_WORD = {
    "beat": "Beat",
    "calm": "Calm",
    "big": "Big",
    "talk": "Voice",
    "mixed": "Everyday",
}


@dataclass
class StyleAnswers:  # pylint: disable=too-many-instance-attributes
    """The answers to 'Create your own style', each one a key from its choices."""

    music: str = "mixed"
    movement: str = "balanced"
    speed: str = "normal"
    room: str = "natural"
    place: str = "headphones"


def suggested_answers(music: str) -> StyleAnswers:
    """Good answers for a kind of music, so a beginner can simply press Save."""
    answers = {
        "beat": StyleAnswers("beat", "strong", "beat", "natural"),
        "calm": StyleAnswers("calm", "gentle", "slow", "natural"),
        "big": StyleAnswers("big", "strong", "normal", "natural"),
        "talk": StyleAnswers("talk", "gentle", "slow", "dry"),
    }
    return answers.get(music, StyleAnswers())


def guided_config(answers: StyleAnswers) -> EffectConfig:
    """The exact settings a set of answers stands for (always valid)."""
    base = PRESETS[_BASE_STYLE.get(answers.music, "studio")].config
    config = dataclasses.replace(
        base,
        intensity=_MOVEMENT.get(answers.movement, 0.8),
        rotation_seconds=_SPEED.get(answers.speed, 8.0),
        beat_sync=answers.speed == "beat",
        bpm=None,
        speed_curve=(),
        intensity_curve=(),
        ambience=_ROOM.get(answers.room, 0.25),
        vocals="move",
    )
    if answers.place == "speakers":
        config = speaker_safe(config)
    config = with_standard_output(config)
    config.validate()
    return config


def suggested_description(answers: StyleAnswers) -> str:
    """A one-line description built from the answers, e.g. for the Description box."""
    music = {
        "beat": "Music with a strong beat",
        "calm": "Calm music",
        "big": "Big, loud music",
        "talk": "Talking",
    }.get(answers.music, "All kinds of music")
    movement = answers.movement if answers.movement in _MOVEMENT else "balanced"
    speed = {
        "slow": "slow spin",
        "fast": "fast spin",
        "beat": "spins with the beat",
    }.get(answers.speed, "normal spin")
    room = {"dry": "a dry room", "spacious": "a spacious room"}.get(
        answers.room, "a natural room"
    )
    extras = ", safe for speakers" if answers.place == "speakers" else ""
    return f"{music}: {movement} movement, {speed}, {room}{extras}"


def suggested_name(answers: StyleAnswers, taken: Sequence[str]) -> str:
    """A free name built from the answers: Calm Mix, or Calm Mix 2 if that's taken."""
    stem = _MUSIC_WORD.get(answers.music, "My") + " Mix"
    # Compared the way style names are, so CalmMix and Calm Mix count as the same
    used = {name_key(name) for name in [*taken, *PRESETS]}
    name, number = stem, 2
    while name_key(name) in used:
        name, number = f"{stem} {number}", number + 1
    return name


@dataclass(frozen=True)
class StyleNote:
    """One line of the quality check: its level, what it says, and a fix if any."""

    level: str  # "error" stops saving, "warning" can be fixed, "tip" is a hint
    text: str
    fix: dict[str, object] = field(default_factory=dict)


def style_check(config: EffectConfig, summary: str) -> list[StyleNote]:
    """Everything that would make a saved style weak, most important first."""
    notes: list[StyleNote] = []
    moving = config.intensity > 0 or any(v > 0 for _t, v in config.intensity_curve)
    if not moving:
        notes.append(
            StyleNote(
                "error",
                "This style doesn't move the music at all, so there would be no 8D "
                "effect. Choose some movement.",
                {"intensity": 0.8, "intensity_curve": ()},
            )
        )
    # A style is only the sound, so file settings never raise advice about it
    for text, fix in display.advice_items(with_standard_output(config)):
        # The first sentence says what's weak; "Improve it for me" does the fixing
        notes.append(StyleNote("warning", text.split(". ")[0].rstrip(".") + ".", fix))
    if not summary.strip():
        notes.append(
            StyleNote(
                "tip", "Add a few words to the description so you remember its use."
            )
        )
    return notes


def improved(config: EffectConfig, notes: Sequence[StyleNote]) -> EffectConfig:
    """The settings with every suggested fix applied."""
    changes: dict[str, object] = {}
    for note in notes:
        changes.update(note.fix)
    return dataclasses.replace(config, **changes) if changes else config


def improve_answers(answers: StyleAnswers, notes: Sequence[StyleNote]) -> StyleAnswers:
    """The answers that follow the quality check's advice."""
    better = dataclasses.replace(answers)
    for note in notes:
        if "intensity" in note.fix:
            better.movement = "balanced"
        if "rotation_seconds" in note.fix:
            better.speed = "normal"
        if "ambience" in note.fix:
            better.room = "natural"
    return better


def style_summary(config: EffectConfig) -> str:
    """What a style does, in plain words, one part per line."""
    return "\n".join(
        [
            f"Sound: {display.describe_sound(config)}",
            f"Speed: {display.describe_spin(config)}",
            f"Movement: {config.intensity:.2f} "
            f"({display.describe_movement(config.intensity)})",
            f"Space: {config.ambience:.2f} ({display.describe_room(config.ambience)})",
        ]
    )
