# Developed by ::> Gehan Fernando
"""The one real Audio8D window the window tests share."""

# pytest hands fixtures to tests by name, which pylint sees as shadowing
# pylint: disable=redefined-outer-name

import pytest
from gui_helpers import pump


@pytest.fixture(scope="session")
def window():
    """One real window for every test (Tk dislikes many in one process)."""
    tk = pytest.importorskip("tkinter")
    from src.gui_app import Audio8DApp  # pylint: disable=import-outside-toplevel
    from src.player import Player  # pylint: disable=import-outside-toplevel

    try:
        made = Audio8DApp()
    except tk.TclError as exc:  # no screen, e.g. on a server
        pytest.skip(f"no display: {exc}")
    # Previews play silently while testing
    made.player = Player(muted=True)
    # Nothing is prepared in the background, so pages look as they do at first
    made._warm = []  # pylint: disable=protected-access
    made._warm_dialogs = lambda: None  # pylint: disable=protected-access
    made.update()
    yield made
    made.cancel.set()
    made.previews.close()
    made.player.close()
    made.destroy()


@pytest.fixture
def app(window):
    """The shared window, back to a fresh start: no songs, the best style."""
    from src.gui_model import GuiSettings  # pylint: disable=import-outside-toplevel

    pump(window, lambda: not window.busy, 30)
    # A dialog left open by a test would hold the keyboard and mouse
    for dialog in (window.chooser, window.customize):
        if dialog is not None and dialog.is_open:
            dialog.cancel()
    window.clear_songs()
    window.settings = GuiSettings()
    window.settings.apply_style(window.presets["studio"])
    window.run_results.clear()
    window.run_outputs.clear()
    window.sync_controls()
    window.show_page("songs")
    window.update()
    return window
