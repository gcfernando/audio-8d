# Developed by ::> Gehan Fernando
"""Words that must never be cut: the status message and a result's measured facts."""

# pytest hands fixtures to tests by name, which pylint sees as shadowing
# pylint: disable=redefined-outer-name
# These tests look inside the window's own parts, some of them private
# pylint: disable=protected-access

import importlib.util
import tkinter.font as tkfont
from pathlib import Path

import pytest
from gui_helpers import pump

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("customtkinter") is None,
    reason="the window needs CustomTkinter (pip install customtkinter)",
)

LONG_STATUS = (
    "Playing Compare A/B of Midnight Arcade (extended mix): the original first, "
    "then the 8D sound"
)


def _drawn_font(label) -> tkfont.Font:
    """The font a CustomTkinter label really draws with."""
    return tkfont.Font(label, font=label._label.cget("font"))


@pytest.mark.parametrize("scale", [1.0, 1.25])
def test_the_status_message_is_never_hidden_by_the_summary(app, scale) -> None:
    ctk = pytest.importorskip("customtkinter")
    ctk.set_widget_scaling(scale)
    try:
        app.geometry("1100x720")
        app.status_text.configure(text=LONG_STATUS)
        app.refresh_status()
        pump(app, lambda: False, 0.5)
        words = app.status_text._label
        # The whole message is drawn (wrapping is fine, cutting is not)
        assert words.winfo_width() >= words.winfo_reqwidth() - 1
        summary = app.settings_text
        drawn = _drawn_font(summary).measure(summary.cget("text"))
        assert drawn <= summary.winfo_width()
        # Shortened with '…', left out for lack of room, or whole: never cut
        shown = summary.cget("text")
        assert shown in ("", app.status_bar.words) or shown.endswith("…")
    finally:
        ctk.set_widget_scaling(1.0)
        app.geometry("1320x880")
        app.status_text.configure(text="Ready.")
        app.refresh_status()


@pytest.mark.parametrize("scale", [1.0, 1.25])
def test_a_result_keeps_its_loudness_and_tempo_in_view(app, scale) -> None:
    ctk = pytest.importorskip("customtkinter")
    review = app.pages["review"]
    song = Path("C:/Music/Midnight Arcade (extended club mix, remastered).mp3")
    result = "-14.0 LUFS  ·  120.2 BPM"
    app.run_results[song] = ("Studio", "Done", f"{result}  ·  saved as x.mp3", "done")
    ctk.set_widget_scaling(scale)
    try:
        app.geometry("1100x720")
        app.show_page("review")
        review.show_results()
        pump(app, lambda: False, 0.5)
        tree = review.results.tree
        room = tree.column("result", "width")
        # Tk draws a cell with a few pixels of padding on each side
        assert _drawn_tree_width(tree, result) + 12 <= room
    finally:
        ctk.set_widget_scaling(1.0)
        app.geometry("1320x880")
        app.run_results.clear()
        review.show_results()


def _drawn_tree_width(tree, text: str) -> int:
    """How wide text is in the table's own font."""
    style = tree.winfo_toplevel().tk.call(
        "ttk::style", "lookup", "Audio8D.Treeview", "-font"
    )
    return tkfont.Font(tree, font=style).measure(text)
