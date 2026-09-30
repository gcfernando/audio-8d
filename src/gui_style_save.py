# Developed by ::> Gehan Fernando
"""The checks every saved style goes through, shared by Your styles and Edit.

A style's name must pass check_style_name and its sound the quality check
(errors stop the save; warnings ask 'Save as it is' or 'Improve and save').
"""

from collections.abc import Callable
from typing import TYPE_CHECKING

from .core.errors import Audio8DError
from .core.settings import EffectConfig
from .core.user_presets import check_style_name
from .gui_dialogs import Dialog
from .gui_model import gui_words
from .gui_widgets import WARNING
from .style_creator import improved, style_check

if TYPE_CHECKING:
    from .gui_app import Audio8DApp


def taken_names(app: "Audio8DApp") -> list[str]:
    """The names of your saved styles."""
    return [preset.name for preset in app.presets.values() if preset.custom]


def check_name(
    app: "Audio8DApp", text: str, keep: str | None = None
) -> tuple[str | None, str | None]:
    """(the name a style will get, None), or (None, why it can't be used)."""
    try:
        return check_style_name(text, taken_names(app), keep=keep), None
    except Audio8DError as exc:
        return None, gui_words(str(exc)) + "."


def checked_style(
    app: "Audio8DApp",
    config: EffectConfig,
    summary: str,
    complain: Callable[[str], None],
) -> EffectConfig | None:
    """The quality check every save goes through: errors stop, warnings ask."""
    notes = style_check(config, summary)
    errors = [note for note in notes if note.level == "error"]
    if errors:
        complain(errors[0].text)
        return None
    warnings_ = [note for note in notes if note.level == "warning"]
    if not warnings_:
        return config
    answer = Dialog(
        app,
        "Save it as it is?",
        "The quality check found something that may not sound its best:\n\n"
        + "\n".join(f"•  {note.text}" for note in warnings_)
        + "\n\nImprove and save follows the advice for you.",
        [
            ("Go back", "no"),
            ("Save as it is", "as-is"),
            ("Improve and save", "improve"),
        ],
        icon="warning",
        color=WARNING,
    ).ask()
    if answer == "improve":
        return improved(config, warnings_)
    return config if answer == "as-is" else None
