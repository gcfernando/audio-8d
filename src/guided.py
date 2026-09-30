# Developed by ::> Gehan Fernando
"""The questions the step-by-step helper asks, one small function per question."""

from pathlib import Path

from . import display
from .core.errors import InputValidationError
from .core.parsing import parse_selection
from .core.presets import RECOMMENDED_PRESET, Preset
from .core.user_presets import find_style
from .files import find_songs


def clean_typed_path(answer: str) -> str:
    """Strip the quotes, spaces and '& ' that drag-and-drop or 'Copy as path' add."""
    cleaned = answer.strip()
    # PowerShell puts '& ' in front of a dragged-in path that contains spaces
    if cleaned.startswith("& "):
        cleaned = cleaned[2:]
    return cleaned.strip().strip("\"'").strip()


# The helper asks four questions and shows "Step N of 4" on each
STEPS = 4


def ask_for_music(painter: display.Painter) -> Path | None:
    """Keep asking until we get a real file or folder, or the user presses Enter."""
    display.show_step(
        painter,
        1,
        STEPS,
        "Which song or folder?",
        "Drag ONE song or a whole FOLDER of songs into this window, press Enter.",
    )
    while True:
        answer = clean_typed_path(input("  Song or folder: "))
        # Enter on its own means the user changed their mind
        if not answer:
            return None
        chosen = Path(answer).expanduser()
        if chosen.is_file() or chosen.is_dir():
            return chosen
        display.show_problem(
            painter,
            "I can't find that. Try dragging it in (or press Enter to stop).",
        )


def ask_which_songs(painter: display.Painter, folder: Path) -> list[Path] | None:
    """Show the songs in the folder and let the user pick some or all."""
    songs = find_songs(folder)
    # A folder that only holds album folders: look inside them too
    if not songs:
        songs = find_songs(folder, recursive=True)
    if not songs:
        display.show_problem(painter, "That folder has no songs in it.")
        return None
    painter.line()
    display.show_song_list(painter, songs, folder)
    painter.line(
        "  "
        + painter.paint(
            "Which ones? Press Enter for ALL, or type numbers like 1,3,5-7.", "dim"
        )
    )
    while True:
        answer = input("  Songs [all]: ")
        try:
            return [songs[index] for index in parse_selection(answer, len(songs))]
        except InputValidationError as exc:
            display.show_problem(painter, str(exc))


def ask_for_style(painter: display.Painter, presets: dict[str, Preset]) -> str:
    """Numbered style menu; pressing Enter picks the best one."""
    painter.line()
    display.show_step(
        painter,
        2,
        STEPS,
        "Which style?",
        f"Just press Enter for the BEST one ({RECOMMENDED_PRESET}).",
    )
    names = display.show_style_menu(painter, presets)
    while True:
        answer = input("  Style [1]: ").strip()
        if not answer:
            return names[0]
        if answer.isdigit() and 1 <= int(answer) <= len(names):
            return names[int(answer) - 1]
        # A style can also be typed by name, however it's written ('party mix')
        typed = find_style(answer, presets)
        if typed:
            return typed
        display.show_problem(
            painter, f"Please type a number from 1 to {len(names)}, or press Enter."
        )


def ask_for_destination(painter: display.Painter) -> Path | None:
    """Next to the originals (Enter), or a folder the user drags in."""
    painter.line()
    display.show_step(
        painter,
        3,
        STEPS,
        "Where should the 8D songs go?",
        "Press Enter to save them next to the originals, or drag a FOLDER in.",
    )
    while True:
        answer = clean_typed_path(input("  Save in [next to originals]: "))
        if not answer:
            return None
        folder = Path(answer).expanduser()
        if folder.is_file():
            display.show_problem(painter, "That is a file. Please drag in a folder.")
            continue
        return folder


def ask_about_originals(painter: display.Painter) -> tuple[bool, str]:
    """Keep the originals, or replace them (and choose the new name)."""
    painter.line()
    display.show_step(
        painter,
        4,
        STEPS,
        "What about the original songs?",
        "Replaced originals go to the Recycle Bin (or stay, renamed, on a USB stick).",
    )
    display.show_choices(
        painter,
        [
            ("Keep them", "the 8D song is saved as '<song> (8D)'"),
            ("Replace them", "the 8D song takes the ORIGINAL name"),
            ("Replace them, keep '(8D)'", "the 8D song is named '<song> (8D)'"),
        ],
    )
    # The answer is (replace the originals?, how the new file is named)
    while True:
        answer = input("  Choice [1]: ").strip()
        if answer in {"", "1"}:
            return False, "8d"
        if answer == "2":
            return True, "original"
        if answer == "3":
            return True, "8d"
        display.show_problem(painter, "Please type 1, 2 or 3, or press Enter.")
