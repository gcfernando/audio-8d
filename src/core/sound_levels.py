# Developed by ::> Gehan Fernando
"""Friendly sound choices (Movement, Speed, Space) and the exact values behind them.

The window and the command line both offer these words instead of raw numbers:
each word always means the same value, and the numbers stay available for
anyone who wants them (Advanced in the window, --intensity and friends).
"""

from dataclasses import dataclass

from .errors import InputValidationError


@dataclass(frozen=True, slots=True)
class SoundLevel:
    """One friendly setting: its name, the value each word stands for, and why."""

    key: str
    label: str
    field: str
    choices: dict[str, float]
    help: str

    def word_for(self, value: float) -> str | None:
        """The word whose value this is exactly, or None for an in-between value."""
        for word, number in self.choices.items():
            if abs(number - value) < 1e-9:
                return word
        return None

    def value_for(self, word: str) -> float:
        """The exact value a word stands for (letter case doesn't matter)."""
        for name, number in self.choices.items():
            if name.lower() == word.strip().lower():
                return number
        raise InputValidationError(
            f"{self.label} must be one of: {', '.join(w.lower() for w in self.choices)}"
        )

    def between(self, value: float) -> str:
        """'between Gentle and Balanced' for a value the words don't cover exactly."""
        ordered = sorted(self.choices.items(), key=lambda item: item[1])
        lower = [word for word, number in ordered if number < value]
        upper = [word for word, number in ordered if number > value]
        if lower and upper:
            return f"between {lower[-1]} and {upper[0]}"
        return f"beyond {(lower or upper)[-1 if lower else 0]}"


# 0.80 / 8 s / 0.25 is Studio; the other words sit a clear, comfortable step either side
MOVEMENT = SoundLevel(
    "movement",
    "Movement",
    "intensity",
    {"Gentle": 0.65, "Balanced": 0.80, "Strong": 0.95},
    "How far the music travels around your head.",
)
SPEED = SoundLevel(
    "speed",
    "Speed",
    "rotation_seconds",
    {"Slow": 12.0, "Normal": 8.0, "Fast": 5.0},
    "How quickly the music goes once around you.",
)
# Dry keeps a hint of room, which helps the sound feel outside your head
SPACE = SoundLevel(
    "space",
    "Space",
    "ambience",
    {"Dry": 0.10, "Natural": 0.25, "Spacious": 0.45},
    "How big the room around the music sounds.",
)
LEVELS = (MOVEMENT, SPEED, SPACE)
