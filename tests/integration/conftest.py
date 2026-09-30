# Developed by ::> Gehan Fernando
"""The one real Audio8D window the window tests share."""

# pytest hands fixtures to tests by name, which pylint sees as shadowing
# pylint: disable=redefined-outer-name

import pytest
from gui_helpers import pump


@pytest.fixture(scope="session")
def window(tmp_path_factory: pytest.TempPathFactory):
    """One real window for every test (Tk dislikes many in one process)."""
    tk = pytest.importorskip("tkinter")
    from src.gui_app import Audio8DApp  # pylint: disable=import-outside-toplevel
    from src.player import Player  # pylint: disable=import-outside-toplevel

    # Made before any test's private home exists, so it gets one of its own
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("AUDIO8D_HOME", str(tmp_path_factory.mktemp("window-home")))
        patch.setenv("AUDIO8D_NO_WT", "1")
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

    pump(window, lambda: not window.busy and not window.scans_waiting, 30)
    assert not window.busy, "the previous test left songs being created"
    assert not window.scans_waiting, "the previous test left folders being read"
    # A dialog left open by a test would hold the keyboard and mouse
    for dialog in (window.chooser, window.customize):
        if dialog is not None and dialog.is_open:
            dialog.cancel()
    window.clear_songs()
    window.settings = GuiSettings()
    window.settings.apply_style(window.presets["studio"])
    window.run_results.clear()
    window.run_outputs.clear()
    # Step 3 remembers what was open and which song it edits; start afresh
    output = window.pages.get("output")
    if output is not None:
        # pylint: disable=protected-access
        if output._folder_job is not None:
            output.after_cancel(output._folder_job)
            output._folder_job = None
        output.wants_folder = False
        output.show_more_loudness = False
        output.song = None
    window.sync_controls()
    window.show_page("songs")
    window.update()
    return window
