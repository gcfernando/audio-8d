# Developed by ::> Gehan Fernando
"""Drives the real window: it keeps responding and tells the truth about each run."""

# pytest hands fixtures to tests by name, which pylint sees as shadowing
# pylint: disable=redefined-outer-name
# These tests drive the window's own parts, some of them private
# pylint: disable=protected-access

import importlib.util
from pathlib import Path

import pytest
from gui_helpers import pump, read

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("customtkinter") is None,
    reason="the window needs CustomTkinter (pip install customtkinter)",
)


# ------------------------------------------------------------ staying responsive


def test_a_failing_event_never_stops_the_window(app, monkeypatch) -> None:
    shown: list[BaseException] = []
    heard: list[str] = []
    monkeypatch.setattr(app, "_show_error", shown.append)
    monkeypatch.setattr(app, "toast", lambda text, kind="info": heard.append(text))
    # A toast without its words makes its handler fail
    app.events.put(("toast",))
    app.events.put(("toast", "still listening", "info"))
    pump(app, lambda: bool(heard), 5)

    assert heard == ["still listening"]
    assert len(shown) == 1 and isinstance(shown[0], IndexError)


def test_esc_asks_before_stopping_and_leaves_text_boxes_alone(app, monkeypatch) -> None:
    from types import SimpleNamespace  # pylint: disable=import-outside-toplevel

    from src.gui_dialogs import Dialog  # pylint: disable=import-outside-toplevel

    answers: list[bool] = []
    monkeypatch.setattr(Dialog, "confirm", lambda *_a, **_k: answers.pop(0))
    search = app.pages["styles_step"].search._entry
    app.busy = True
    try:
        app._escape(SimpleNamespace(widget=search))
        assert not app.cancel.is_set()
        answers.append(False)
        app._escape(SimpleNamespace(widget=app))
        assert not app.cancel.is_set() and not answers
        answers.append(True)
        app._escape(SimpleNamespace(widget=app))
        assert app.cancel.is_set()
    finally:
        app.busy = False
        app.cancel.clear()


def test_the_end_of_a_run_is_told_truthfully(app, tmp_path: Path) -> None:
    made, left = tmp_path / "made.mp3", tmp_path / "left.mp3"
    review = app.pages["review"]

    # Stop pressed just after the last song finished stopped nothing
    app.run_results = {made: ("Studio", "Done", "Saved", "done")}
    app.run_cut, app.busy = False, True
    app.cancel.set()
    app._conversion_finished(("finished",))
    assert not app.status_text.cget("text").startswith("Stopped")

    # A run that failed half-way leaves the rest ready to try again
    app.run_results = {
        made: ("Studio", "Done", "Saved", "done"),
        left: ("Studio", "Waiting", "", "waiting"),
    }
    app.busy = True
    app.cancel.clear()
    app._conversion_finished(("finished",))
    assert app.run_results[left][3] == "problem"
    assert str(review.retry.cget("state")) == "normal"
    app.run_results.clear()


def test_compare_plays_the_original_then_the_8d_sound(
    app, stereo_tone: Path, monkeypatch
) -> None:
    started: list[tuple] = []
    monkeypatch.setattr(
        app.previews, "start", lambda *args, **kwargs: started.append(args)
    )
    read(app, [stereo_tone])
    step = app.pages["styles_step"]
    app.show_page("styles_step")
    step.show_selection()
    assert str(step.compare.cget("state")) == "disabled"

    step.table.select([str(stereo_tone)], str(stereo_tone))
    step.show_selection()
    assert str(step.compare.cget("state")) == "normal"
    step._compare()
    assert started and started[-1][0] == stereo_tone and started[-1][3] == "compare"
    assert app.preview_wanted == (stereo_tone, "compare")
    app.preview_wanted = None


def test_output_sliders_reach_what_the_command_line_allows(app) -> None:
    # pylint: disable-next=import-outside-toplevel
    from src.batch import MAX_JOBS
    from src.gui_output import ceiling_for  # pylint: disable=import-outside-toplevel

    output = app.pages["output"]
    app.show_page("output")
    output.running.open()
    output.advanced.open()
    assert output.run_controls is not None and output.more is not None
    assert output.run_controls.jobs.high == MAX_JOBS
    assert ceiling_for(output.more.ceiling.low) == 0.0625
    # The recommended peak limits stay exactly reachable
    assert ceiling_for(-1.5) == 0.84 and ceiling_for(-1.0) == 0.89


def test_the_folder_box_is_checked_once_typing_pauses(app, tmp_path: Path) -> None:
    output = app.pages["output"]
    app.show_page("output")
    output.folder.delete(0, "end")
    output.folder.insert(0, str(tmp_path / "8D"))
    output._folder_typed()
    assert app.settings.destination == ""

    pump(app, lambda: app.settings.destination != "", 3)
    assert app.settings.destination == str(tmp_path / "8D")
    app.set_destination("")


def test_wrapped_labels_are_forgotten_with_their_parent(app) -> None:
    ctk = pytest.importorskip("customtkinter")
    from src.gui_widgets import hint  # pylint: disable=import-outside-toplevel

    frame = ctk.CTkFrame(app)
    for _ in range(5):
        hint(frame, "gone again").destroy()
    hint(frame, "kept")

    assert len(frame.audio8d_fitted) == 1
    frame.destroy()


def test_a_new_file_is_never_written_over_another_song(
    app, tmp_path: Path, monkeypatch
) -> None:
    # pylint: disable-next=import-outside-toplevel
    from src import app_convert
    from src.batch import BatchItem  # pylint: disable=import-outside-toplevel

    first, second = tmp_path / "a.flac", tmp_path / "a.mp3"
    # Even if the naming ever slipped, a.flac may not be saved over a.mp3
    monkeypatch.setattr(
        app_convert,
        "items_for",
        lambda *_a: [BatchItem(first, second), BatchItem(second, second)],
    )
    todo = app._songs_to_make(None)

    assert [item.source for item in todo] == [second]
    assert app.run_results[first][3] == "problem"
    assert "overwrite another song" in app.run_results[first][2]
    app.run_results.clear()


def test_a_saved_song_with_a_note_says_so(app, tmp_path: Path) -> None:
    # pylint: disable-next=import-outside-toplevel
    from types import SimpleNamespace

    from src.batch import (  # pylint: disable=import-outside-toplevel
        BatchItem,
        BatchOutcome,
    )

    song = tmp_path / "a.mp3"
    result = SimpleNamespace(
        output=tmp_path / "a (8D).mp3",
        quality=None,
        bpm=None,
        original_removed_to=None,
        warning="the original could not be moved",
    )
    app.run_results = {song: ("Studio", "Working", "", "working")}
    outcome = BatchOutcome(BatchItem(song, result.output), result)  # type: ignore[arg-type]
    app._song_done(0, outcome)

    assert app.run_results[song][3] == "done"
    assert "the original could not be moved" in app.run_results[song][2]
    app.run_results.clear()
    app.run_outputs.clear()


def test_clear_list_asks_before_forgetting_own_settings(
    app, stereo_tone: Path, monkeypatch
) -> None:
    from src.gui_dialogs import Dialog  # pylint: disable=import-outside-toplevel

    songs = app.pages["songs"]
    assert str(songs.clear.cget("state")) == "disabled"
    read(app, [stereo_tone])
    assert str(songs.clear.cget("state")) == "normal"
    app.settings.song_styles[stereo_tone] = "smooth"
    answers = [False]
    monkeypatch.setattr(Dialog, "confirm", lambda *_a, **_k: answers.pop(0))

    app.ask_clear_songs()
    assert len(app.library) == 1 and not answers
    answers.append(True)
    app.ask_clear_songs()
    assert len(app.library) == 0
    assert str(songs.clear.cget("state")) == "disabled"
