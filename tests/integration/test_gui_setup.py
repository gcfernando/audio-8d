# Developed by ::> Gehan Fernando
"""Drives the real window: settings, your styles, the add-on and per-song settings."""

# pytest hands fixtures to tests by name, which pylint sees as shadowing
# pylint: disable=redefined-outer-name
# These tests drive the window's own parts, some of them private
# pylint: disable=protected-access

import gc
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest
from gui_helpers import copies, customize, pump, read, texts

from src import EffectConfig
from src.core.locations import presets_file
from src.core.preferences import load_preferences
from src.core.user_presets import (
    delete_user_preset,
    rename_user_preset,
    save_user_preset,
)
from src.gui_model import song_config

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("customtkinter") is None,
    reason="the window needs CustomTkinter (pip install customtkinter)",
)


# ------------------------------------------------------------ logs and settings


def test_clear_logs_empties_the_view_but_keeps_the_saved_log(app) -> None:
    import logging  # pylint: disable=import-outside-toplevel

    review = app.pages["review"]
    logging.getLogger("audio8d.test").warning("a line for the log view")
    pump(app, lambda: "a line for the log view" in review.log_text(), 5)
    assert "a line for the log view" in review.log_text()

    app.clear_log_view()
    assert review.log_text() == ""
    assert review.log_lines == 0


def test_the_log_view_keeps_only_recent_lines(app) -> None:
    review = app.pages["review"]
    app.clear_log_view()
    review.write_log([f"line {n}" for n in range(review.MAX_LOG_LINES + 500)])

    text = review.log_text().splitlines()
    assert len(text) <= review.MAX_LOG_LINES
    assert text[-1] == f"line {review.MAX_LOG_LINES + 499}"
    app.clear_log_view()


def test_ffmpeg_paths_are_tested_before_they_are_saved(app, tmp_path: Path) -> None:
    settings = app.pages["settings"]
    row = settings.rows["ffmpeg"]
    row.path.insert(0, str(tmp_path / "nowhere" / "ffmpeg.exe"))
    # The start-up check comes first, so it is never mistaken for this one
    pump(app, lambda: bool(app.tool_checks), 30)
    settings.checks = {}
    settings.save_paths()
    pump(app, lambda: bool(settings.checks), 30)
    pump(app, lambda: False, 0.5)

    assert not settings.checks["ffmpeg"].ok
    assert load_preferences()[0].ffmpeg_path == ""
    assert "There is no file" in row.result.cget("text")
    # A path that was only typed, never saved, doesn't block converting
    assert app.tools_problem is None
    settings.checks = {}
    settings.test()
    pump(app, lambda: bool(settings.checks), 30)
    assert not settings.checks["ffmpeg"].ok and app.tools_problem is None

    row.path.delete(0, "end")
    settings.checks = {}
    settings.use_automatic()
    pump(app, lambda: bool(settings.checks), 30)
    assert all(check.ok for check in settings.checks.values())
    assert app.tools_problem is None


def test_theme_and_size_are_remembered(app) -> None:
    app.set_theme("Light")
    app.set_scale(1.1)
    saved = json.loads(
        (Path(os.environ["AUDIO8D_HOME"]) / "settings.json").read_text("utf-8")
    )
    assert saved["theme"] == "Light" and saved["scale"] == 1.1
    app.set_scale(1.0)
    app.set_theme("System")


def test_buttons_work_from_the_keyboard_with_a_visible_focus(app) -> None:
    import tkinter as tk  # pylint: disable=import-outside-toplevel

    # pylint: disable-next=import-outside-toplevel
    from src.gui_widgets import (
        FOCUS_ON_ACCENT,
        keyboard_in_use,  # pylint: disable=import-outside-toplevel
    )

    page = app.pages["review"]
    app.show_page("review")
    button = page.start
    # Clicking shows no ring; moving with the keyboard does
    keyboard_in_use(False)
    button.event_generate("<FocusIn>")
    app.update()
    assert button.cget("border_width") == 0
    button.event_generate("<FocusOut>")
    keyboard_in_use(True)
    # Tab stops on CustomTkinter buttons (they don't by themselves)
    assert button.tk.call(str(button), "cget", "-takefocus") == "1"
    button.event_generate("<FocusIn>")
    app.update()
    assert button.cget("border_width") == 2
    assert button.cget("border_color") == FOCUS_ON_ACCENT
    button.event_generate("<FocusOut>")
    app.update()
    assert button.cget("border_width") == 0

    # Synthetic keys go to the OS-focused window, so the bindings are checked here
    for key in ("<space>", "<Return>"):
        assert tk.Misc.bind(button, key)
    output = app.pages["output"]
    for key in ("<Left>", "<Right>"):
        assert tk.Misc.bind(output.loudness.buttons, key)
    output.loudness._step(1)
    assert app.settings.sound.match_loudness is True
    output.loudness._step(-1)
    assert app.settings.sound.loudness_target == -14.0
    assert not app.settings.sound.match_loudness


# ------------------------------------------------------------ your styles


def test_saving_and_deleting_a_style(app, monkeypatch) -> None:
    styles = app.pages["styles"]
    styles.name.set("qa style")
    styles.summary.set("made by the tests")
    styles._save()
    assert "Qa Style" in app.presets and app.presets["Qa Style"].custom
    # It joins the style chooser and the Customize dialog's style list
    app.open_style_chooser()
    assert "Qa Style" in app.chooser.cards
    app.chooser.cancel()
    app.open_customize([])
    assert "Qa Style" in app.customize.style.options.values()
    app.customize.cancel()

    before = presets_file().read_text(encoding="utf-8")
    styles.name.set("QA-style")
    styles._save()
    assert "already have a style" in styles.name.help.cget("text")
    assert presets_file().read_text(encoding="utf-8") == before

    monkeypatch.setattr("src.gui_mystyles.Dialog.ask", lambda self: "yes")
    styles._delete("Qa Style")
    assert "Qa Style" not in app.presets


def test_your_styles_join_the_lists_and_follow_renames(app, stereo_tone: Path) -> None:
    styles = app.pages["styles"]
    styles._music_picked("calm")
    styles.new_name.set("night drive")
    styles._new_name_typed("night drive")
    styles._create()
    try:
        assert app.presets["Night Drive"].custom
        assert app.settings.style == "Night Drive"

        read(app, [stereo_tone])
        customize(app, [stereo_tone], "Night Drive")
        app.choose_style("studio")
        app.choose_style("Night Drive")
        new = rename_user_preset("Night Drive", "drive at night")
        app.reload_styles(renamed=("Night Drive", new))
        assert app.settings.style == "Drive At Night"

        app.choose_style("studio")
        customize(app, [stereo_tone], "Drive At Night")
        delete_user_preset("Drive At Night")
        assert app.reload_styles() == 1
        assert not app.settings.song_styles
    finally:
        delete_user_preset("Night Drive")
        delete_user_preset("Drive At Night")
        app.reload_styles()


def test_the_style_creator_guides_checks_and_improves(app, monkeypatch) -> None:
    styles = app.pages["styles"]
    styles._music_picked("talk")
    assert styles.answers.room == "dry" and styles.answers.movement == "gentle"
    assert styles.new_name.entry.get() == "Voice Mix"
    assert "looks good" in " ".join(texts(styles.checks))
    # A style is only the sound: no questions about the file type or loudness
    assert not hasattr(styles, "q_file") and not hasattr(styles, "q_level")

    styles.new_name.set("studio")
    styles._create()
    assert "built-in" in styles.new_name.help.cget("text")

    styles._answer(speed="fast", movement="strong")
    styles.new_name.set("Quick Talk")
    monkeypatch.setattr("src.gui_mystyles.Dialog.ask", lambda self: "improve")
    styles._create()
    try:
        saved = app.presets["Quick Talk"].config
        assert saved.rotation_seconds == 5.0 and saved.intensity == 0.95
        assert saved.loudness_target == -14.0  # saved the standard way
    finally:
        delete_user_preset("Quick Talk")
        app.reload_styles()
        styles._music_picked("mixed")


def test_the_name_dialog_only_accepts_a_free_valid_name(app) -> None:
    from src.gui_dialogs import NameDialog  # pylint: disable=import-outside-toplevel

    save_user_preset("PartyMix", EffectConfig())
    app.reload_styles()
    try:
        styles = app.pages["styles"]
        dialog = NameDialog(app, "Name", "Pick one", "party mix", styles.check_name)
        app.update()
        assert str(dialog.buttons["ok"].cget("state")) == "disabled"
        dialog.entry.delete(0, "end")
        dialog.entry.insert(0, "new one")
        assert dialog.check()
        assert dialog.value == "New One"
        dialog.close("no")
    finally:
        delete_user_preset("PartyMix")
        app.reload_styles()


def test_rename_duplicate_export_and_import_in_the_window(
    app, monkeypatch, tmp_path: Path
) -> None:
    save_user_preset("PartyMix", EffectConfig(intensity=0.95), summary="loud")
    app.reload_styles()
    styles = app.pages["styles"]
    shared = tmp_path / "PartyMix.json"
    shown: list[str] = []
    monkeypatch.setattr(
        "src.gui_mystyles.filedialog.asksaveasfilename", lambda **_: str(shared)
    )
    monkeypatch.setattr(
        "src.gui_mystyles.filedialog.askopenfilename", lambda **_: str(shared)
    )
    monkeypatch.setattr(
        "src.gui_mystyles.Dialog.ask", lambda self: shown.append(self.title())
    )
    try:
        styles._export("PartyMix")
        assert json.loads(shared.read_text(encoding="utf-8"))["name"] == "PartyMix"
        monkeypatch.setattr("src.gui_mystyles.NameDialog.ask", lambda self: "PartyCopy")
        styles._import()
        assert app.presets["PartyCopy"].config == app.presets["PartyMix"].config
        monkeypatch.setattr("src.gui_mystyles.NameDialog.ask", lambda self: "PartyTwo")
        styles._duplicate("PartyMix")
        monkeypatch.setattr(
            "src.gui_mystyles.NameDialog.ask", lambda self: "PartyThree"
        )
        styles._rename("PartyTwo")
        assert "PartyThree" in app.presets and "PartyTwo" not in app.presets
        before = presets_file().read_text(encoding="utf-8")
        shared.write_text('{"format": "audio8d-style"}', encoding="utf-8")
        styles._import()
        assert shown == ["Can't import this style"]
        assert presets_file().read_text(encoding="utf-8") == before
    finally:
        for name in ("PartyMix", "PartyCopy", "PartyThree"):
            delete_user_preset(name)
        app.reload_styles()


def test_a_broken_styles_file_is_explained_not_hidden(app) -> None:
    presets_file().parent.mkdir(parents=True, exist_ok=True)
    presets_file().write_text("[mine]\nintensity = lots\n", encoding="utf-8")
    try:
        app.presets = app._load_styles()
        app.pages["styles"].refresh()
        texts = [
            w.cget("text") for w in app.pages["styles"].saved.body.winfo_children()
        ]
        assert "studio" in app.presets
        assert any("line 2" in text and "Fix that line" in text for text in texts)
    finally:
        presets_file().unlink()
        app.presets = app._load_styles()
        app.pages["styles"].refresh()
    assert app.styles_problem is None


# ------------------------------------------------------------ the window itself


def _open_everything(app) -> None:
    """Every folded section open and every optional box showing."""
    for page in app.pages.values():
        for child in page.winfo_children():
            if child.__class__.__name__ == "Section" and not child.opened:
                child.toggle()
    app.change_sound(beat_sync=True)
    app.pages["output"]._more_loudness("custom")
    app.set_name_style("custom")
    app.pages["output"].wants_folder = True
    save_user_preset("LayoutCheck", EffectConfig(), summary="x" * 110)
    app.reload_styles()
    if app.library.tracks:
        customize(app, [app.library.tracks[0].song], "LayoutCheck")
    app.sync_controls()


@pytest.mark.parametrize("scale", [1.0, 1.25])
def test_no_control_ever_overlaps_or_spills_out(
    app, stereo_tone: Path, scale: float
) -> None:
    ctk = pytest.importorskip("customtkinter")
    # pylint: disable-next=import-outside-toplevel
    from src.gui_layout import layout_problems

    read(app, [stereo_tone])
    step = app.pages["styles_step"]
    step.table.select([str(stereo_tone)], str(stereo_tone))
    step.show_selection()
    _open_everything(app)
    ctk.set_widget_scaling(scale)
    try:
        for size in ("1100x720", "1600x1000"):
            app.geometry(size)
            for key in app.pages:
                app.show_page(key)
                # Wrapped text settles over a few layout passes, as on screen
                pump(app, lambda: False, 0.4)
                assert layout_problems(app, app.pages[key]) == [], (scale, size, key)
    finally:
        ctk.set_widget_scaling(1.0)
        app.geometry("1320x880")
        delete_user_preset("LayoutCheck")
        app.pages["styles"]._music_picked("mixed")
        app.reload_styles()


def test_notices_sit_in_the_status_bar_not_over_buttons(app) -> None:
    from src.gui_dialogs import Toast  # pylint: disable=import-outside-toplevel

    area, summary = app.toast_slot
    Toast(app, "first")
    latest = Toast(app, "second", "ok")
    app.update()
    shown = [w for w in area.winfo_children() if isinstance(w, Toast)]
    assert shown == [latest] and latest.winfo_ismapped()
    assert not summary.winfo_ismapped()
    latest.destroy()
    app.update()
    assert summary.winfo_ismapped()


def test_garbage_is_only_collected_on_the_window_thread(app) -> None:
    assert not gc.isenabled()
    app._collect_garbage()
    assert not gc.isenabled()


@pytest.mark.skipif(os.name != "nt", reason="drag-and-drop from File Explorer")
def test_songs_dropped_from_file_explorer_are_added(app, stereo_tone: Path) -> None:
    import ctypes  # pylint: disable=import-outside-toplevel
    from ctypes import wintypes  # pylint: disable=import-outside-toplevel

    kernel32, user32 = ctypes.windll.kernel32, ctypes.windll.user32
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.GetParent.restype = wintypes.HWND
    user32.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        ctypes.c_void_p,
        wintypes.LPARAM,
    ]
    names = (str(stereo_tone) + "\0\0").encode("utf-16-le")
    header = ctypes.sizeof(wintypes.DWORD) * 5
    block = kernel32.GlobalAlloc(0x0042, header + len(names))
    memory = kernel32.GlobalLock(block)
    ctypes.memmove(memory, (wintypes.DWORD * 5)(header, 0, 0, 0, 1), header)
    ctypes.memmove(memory + header, names, len(names))
    kernel32.GlobalUnlock(block)

    user32.PostMessageW(user32.GetParent(app.winfo_id()), 0x0233, block, 0)
    pump(app, lambda: bool(app.library.tracks), 10)

    assert [t.song for t in app.library.tracks] == [stereo_tone]


def test_message_windows_keep_the_audio8d_icon(app, monkeypatch) -> None:
    from src.gui_dialogs import Dialog  # pylint: disable=import-outside-toplevel

    opened = time.perf_counter()
    applied: list[float] = []
    monkeypatch.setattr(
        "src.gui_dialogs.use_app_icon",
        lambda _window: applied.append(time.perf_counter() - opened),
    )
    dialog = Dialog(app, "Test", "A message", [("OK", "ok")])
    pump(app, lambda: False, 0.5)

    assert any(when >= 0.2 for when in applied)
    dialog.close("ok")


def test_the_full_guide_always_opens_online(app, monkeypatch) -> None:
    from src import app_setup  # pylint: disable=import-outside-toplevel

    opened: list[str] = []
    # A browser that opens reports True, as webbrowser.open does
    monkeypatch.setattr(
        app_setup.webbrowser, "open", lambda url: opened.append(url) or True
    )
    app.open_link(app_setup_url())
    pump(app, lambda: bool(opened), 20)
    assert opened == ["https://github.com/gcfernando/audio-8d/blob/main/README.md"]

    # A browser that can't start never freezes the window: the address is copied
    shown: list[str] = []
    monkeypatch.setattr(app_setup.webbrowser, "open", lambda _url: False)
    monkeypatch.setattr("src.app_setup.Dialog.__init__", _record_dialog(shown))
    app.open_link(app_setup_url())
    pump(app, lambda: bool(shown), 20)
    assert shown == ["The browser didn't open"]
    assert app.clipboard_get() == app_setup_url()


def app_setup_url() -> str:
    """The guide's address, as the About card opens it."""
    from src.core.locations import GUIDE_URL  # pylint: disable=import-outside-toplevel

    return GUIDE_URL


def _record_dialog(shown: list[str]):
    """A Dialog stand-in that only remembers its title."""

    def record(self, _master, title, *_args, **_kwargs) -> None:
        del self
        shown.append(title)

    return record


def test_a_corrected_box_loses_its_red_message(app, stereo_tone: Path) -> None:
    read(app, [stereo_tone])
    app.open_customize([stereo_tone])
    dialog = app.customize
    dialog.advanced_part.open()  # the Advanced controls are made when it opens
    assert dialog.advanced is not None
    field = dialog.advanced.amount_curve
    field.set("0=0.5, 1:00=1.5")
    field.check()
    assert "between 0 and 1" in field.help.cget("text")
    field.set("")
    field.check()
    assert field.help.cget("text") == field.help_text
    dialog.cancel()


def test_the_review_warns_about_low_quality_song_files(app, stereo_tone: Path) -> None:
    # pylint: disable-next=import-outside-toplevel
    from src.core.types import AudioStreamInfo

    read(app, [stereo_tone])
    app.library.tracks[0].info = AudioStreamInfo("mp3", 2, 44100, 3.0, 96_000)
    app.show_page("review")

    notes = " ".join(texts(app.pages["review"].notes))
    assert "1 song is a low-quality file (tone)" in notes
    assert "Everything is ready" in notes


def test_scrollbars_no_longer_force_a_layout_pass(app) -> None:
    import customtkinter as ctk  # pylint: disable=import-outside-toplevel

    from src import gui_widgets  # pylint: disable=import-outside-toplevel

    assert ctk.CTkScrollbar._draw is gui_widgets._draw_scrollbar_without_flush
    page = app.pages["styles_step"]
    app.show_page("styles_step")
    page._parent_canvas.yview_moveto(0.5)
    app.update()
    assert page._scrollbar._canvas.update_idletasks is gui_widgets._no_flush
    assert page._parent_canvas.yview()[0] > 0


# ------------------------------------------------------------ file settings per song


def test_one_song_is_saved_differently_from_customize(
    app, stereo_tone: Path, tmp_path: Path
) -> None:
    first, second = copies(app, stereo_tone, tmp_path, "first.mp3", "second.mp3")
    output = app.pages["output"]
    app.show_page("output")
    # The Output step starts on All songs
    assert output.scope_mode.buttons.get() == "All songs"

    app.open_customize([second])
    dialog = app.customize
    dialog.output_part.open()
    assert dialog.output is not None
    dialog.file(output_format="flac")
    dialog.song_loudness("match")
    dialog.apply()
    assert app.settings.song_files[second] == {
        "output_format": "flac",
        "loudness_target": None,
        "match_loudness": True,
    }
    assert first not in app.settings.song_files

    app.set_destination(str(tmp_path / "out"))
    app.run_convert()
    pump(app, lambda: not app.busy)
    assert (tmp_path / "out" / "first (8D).mp3").is_file()
    assert (tmp_path / "out" / "second (8D).flac").is_file()

    # Reset to default: back to the defaults
    app.reset_to_default([second])
    assert not app.settings.song_files


def test_the_review_lists_what_happens_to_each_song(app, stereo_tone: Path) -> None:
    read(app, [stereo_tone])
    app.open_customize([stereo_tone])
    app.customize.file(output_format="wav")
    app.customize.apply()
    app.show_page("review")
    review = app.pages["review"]
    review.plan.open()
    app.update()

    row = review.plan_table.tree.item(str(stereo_tone), "values")
    assert row[1] == "Studio (custom)" and row[2] == "WAV, -14 LUFS"
    assert row[3].endswith("tone (8D).wav")
    assert "1 song has custom settings" in " ".join(texts(review.summary))
    # 'What will happen' is shown only here, not on the Output step
    assert not hasattr(app.pages["output"], "summary")


# ------------------------------------------------------------ speed


_FRESH_WINDOW = """
import logging, sys, time
sys.path.insert(0, sys.argv[1])
from src.gui_app import _NOT_BUILT, Audio8DApp
app = Audio8DApp()
app._warm = []
assert set(app.pages) == {"songs"}, set(app.pages)
assert app.live("review") is _NOT_BUILT
app.live("review").write_log(["skipped quietly"])
logging.getLogger("audio8d.test").warning("kept until the log exists")
end = time.time() + 0.5
while time.time() < end:
    app.update()
assert any("kept until" in line for line in app._log_waiting)
app.show_page("review")
assert "kept until the log exists" in app.pages["review"].log_text()
app.close()
print("ok")
"""


def test_pages_are_made_when_first_needed_and_updates_wait_for_them() -> None:
    import subprocess  # pylint: disable=import-outside-toplevel

    # A window of its own, in its own process (Tk dislikes two in one)
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", _FRESH_WINDOW, str(root)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if "TclError" in result.stderr and "display" in result.stderr:
        pytest.skip("no display")
    assert result.stdout.strip().endswith("ok"), result.stderr[-2000:]


def test_background_preparation_never_hides_a_page(app) -> None:
    app._warm = ["output"]
    app._last_input = 0.0
    app._warm_up()  # the Output page is now being prepared out of sight
    app.show_page("output")
    pump(app, lambda: False, 1.5)

    frame = app.pages["output"]._parent_frame
    assert frame.winfo_manager() == "grid" and frame.winfo_ismapped()
    app.show_page("songs")


# ------------------------------------------------------------ the singer add-on


def _addon_status(state: str, private: bool = False):
    """A made-up add-on check: 'no-python', 'not-installed', 'partial' or 'ready'."""
    # pylint: disable-next=import-outside-toplevel
    from src.addons import SINGER_PACKAGES, AddonStatus, PackageCheck, PythonCheck

    python = PythonCheck(
        Path(sys.executable) if state != "no-python" else None,
        state != "no-python",
        "addon" if private else "running",
        "3.12.1",
        "No Python was found on this computer." if state == "no-python" else "",
    )
    if state == "no-python":
        return AddonStatus(python)
    oks = {"ready": (True, True, True), "partial": (True, False, True)}.get(
        state, (False, False, True)
    )
    return AddonStatus(
        python,
        tuple(
            PackageCheck(package, ok, problem="" if ok else "not installed")
            for package, ok in zip(SINGER_PACKAGES, oks, strict=True)
        ),
    )


def test_the_add_on_explains_itself_and_shows_its_state(app, monkeypatch) -> None:
    app.show_page("settings", focus="singer")
    card = app.pages["settings"].addon
    text = " ".join(texts(card))
    # What it is, why, what changes and how to remove it, before any install
    for words in ("What it does", "Benefits", "Changes to your computer", "Removal"):
        assert words in text

    app._addon_checked(_addon_status("no-python"), "checked")
    text = " ".join(texts(card))
    assert "Not installed" in text and "python.org" in text
    assert str(card.install.cget("state")) == "disabled"

    app._addon_checked(_addon_status("not-installed"), "checked")
    assert card.install.winfo_manager() == "pack"
    assert str(card.install.cget("state")) == "normal"
    assert card.uninstall.winfo_manager() == ""

    app._addon_checked(_addon_status("partial"), "checked")
    assert "Needs repair" in card.badge.cget("text")

    # Audio8D's own copy can be uninstalled and repaired
    app._addon_checked(_addon_status("ready", private=True), "checked")
    assert "Installed" in card.badge.cget("text")
    assert card.uninstall.winfo_manager() == "pack"
    assert card.repair.winfo_manager() == "pack"
    assert card.install.winfo_manager() == ""
    assert app.singer_ready()

    # A copy in someone's own Python is used but never removed by Audio8D
    app._addon_checked(_addon_status("ready"), "checked")
    assert card.uninstall.winfo_manager() == ""
    assert "won't uninstall it" in card.where.cget("text")

    # Uninstall asks first, then runs away from the window's thread
    monkeypatch.setattr("src.app_setup.Dialog.confirm", lambda *a, **k: True)
    removed: list[bool] = []
    monkeypatch.setattr(
        "src.app_setup.addons.uninstall_addon",
        lambda *_a: (removed.append(True), (True, "The add-on was removed"))[1],
    )
    monkeypatch.setattr(
        "src.app_setup.addons.check_singer",
        lambda *_a: _addon_status("not-installed"),
    )
    app.uninstall_addon()
    pump(app, lambda: not card.installing, 10)
    assert removed == [True]
    assert "Not installed" in card.badge.cget("text")
    assert card.progress_text.cget("text").startswith("Uninstalled successfully — 100%")


def _fake_install(reports, outcome: str):
    """An install that sends the given progress reports, then works, fails or stops."""
    # pylint: disable-next=import-outside-toplevel
    from src.addons import AddonProgress

    def install(_python, _line=None, _cancel=None, on_progress=None):
        assert on_progress is not None
        for stage, overall in reports:
            on_progress(AddonProgress(stage, overall, last=overall or 0.0))
            time.sleep(0.05)
        messages = {
            "worked": "",
            "failed": "Could not download torch",
            "stopped": "Stopped before it finished.",
        }
        return outcome == "worked", messages[outcome]

    return install


@pytest.mark.parametrize("outcome", ["worked", "failed", "stopped"])
def test_the_addon_card_shows_real_progress_and_only_100_percent_on_success(
    app, monkeypatch, outcome: str
) -> None:
    worked = outcome == "worked"
    card = app.pages["settings"].addon
    app.show_page("settings")
    reports = [
        ("Making the add-on folder", None),
        ("Downloading packages", 0.42),
        ("Downloading packages", 0.30),
        ("Installing packages", None),
    ]
    monkeypatch.setattr(
        "src.app_setup.addons.install_addon", _fake_install(reports, outcome)
    )
    ready = _addon_status("ready", private=True)
    monkeypatch.setattr(
        "src.app_setup.addons.check_singer",
        lambda *_a: ready if worked else _addon_status("not-installed"),
    )
    shown: list[tuple[str, str, float]] = []
    original = card.work_progress

    def watch(report) -> None:
        original(report)
        shown.append((card.progress.cget("mode"), card.progress_text.cget("text"),
                      card.progress.get()))  # fmt: skip

    monkeypatch.setattr(card, "work_progress", watch)
    app._addon_work("install", Path(sys.executable))
    pump(app, lambda: not card.installing, 10)

    # Unmeasured steps get a busy bar with no number; measured ones a percentage
    assert shown[0][0] == "indeterminate" and "%" not in shown[0][1]
    assert shown[1][:2] == ("determinate", "Downloading packages — 42%")
    # A smaller report never moves the bar back
    assert shown[2][2] == pytest.approx(0.42, abs=0.01)
    assert shown[2][1] == "Downloading packages — 42%"
    assert all("100%" not in text for _mode, text, _share in shown)
    final = card.progress_text.cget("text")
    if worked:
        assert final.startswith("Installed successfully — 100%")
        assert card.progress.get() == pytest.approx(1.0)
    else:
        assert "100%" not in final and "stopped at 42%" in final
        if outcome == "stopped":
            assert final.startswith("Stopped. Nothing half-installed was kept.")
        assert card.progress.get() == pytest.approx(0.42, abs=0.01)


def test_the_singer_is_switched_on_for_one_song_only(
    app, stereo_tone: Path, tmp_path: Path
) -> None:
    first, _second = copies(app, stereo_tone, tmp_path, "first.mp3", "second.mp3")
    app._addon_checked(_addon_status("not-installed"), "checked")
    app.open_customize([first])
    dialog = app.customize
    assert str(dialog.singer.switch.cget("state")) == "disabled"
    assert "isn't installed" in dialog.singer.help.cget("text")
    dialog.cancel()

    app._addon_checked(_addon_status("ready"), "checked")
    customize(app, [first], vocals="center")
    assert app.settings.song_sound == {first: {"vocals": "center"}}
    songs = app.songs()
    assert not any("singer" in text for _p, text in app.find_problems())
    # Without the add-on those songs can't start, and the reason is named
    app._addon_checked(_addon_status("not-installed"), "checked")
    found = [text for _p, text in app.find_problems() if "singer" in text]
    assert found and "1 song keep" in found[0]
    app.preview_song(first)
    assert app.previews.making is None
    app.reset_to_default([first])
    assert not app.settings.song_sound and len(songs) == 2


def test_customizing_the_default_changes_every_song_that_is_not_custom(
    app, stereo_tone: Path, tmp_path: Path
) -> None:
    first, second = copies(app, stereo_tone, tmp_path, "one.mp3", "two.mp3")
    customize(app, [first], intensity=0.5)
    app.open_customize([])
    dialog = app.customize
    assert dialog.heading.cget("text") == "Customize the default sound"
    assert "Editing defaults for all songs" in dialog.subheading.cget("text")
    dialog.levels["movement"].set(0.95)
    dialog.tune(intensity=0.95)
    dialog.advanced_part.open()
    assert dialog.advanced is not None
    dialog.advanced.speed_curve.set("0=10, 0:30=6")
    dialog.advanced.speed_curve.check()
    dialog.apply()

    assert app.settings.sound.intensity == 0.95
    assert app.settings.speed_curve_text == "0=10, 0:30=6"
    # The customized song keeps its own movement; the other follows the default
    assert song_config(app.settings, first, app.presets).intensity == 0.5
    assert song_config(app.settings, second, app.presets).intensity == 0.95
    step = app.pages["styles_step"]
    assert "Customized by you" in step.default_changed.cget("text")


def test_a_missing_ffmpeg_at_start_opens_settings_and_blocks(
    app, stereo_tone: Path
) -> None:
    # pylint: disable-next=import-outside-toplevel
    from src.health import MISSING, READY, Dependency, HealthReport

    read(app, [stereo_tone])
    missing = HealthReport(
        (
            Dependency("ffmpeg", "FFmpeg", True, MISSING, "ffmpeg was not found."),
            Dependency("ffprobe", "FFprobe", True, READY, "Working."),
        )
    )
    app._health_done(missing, startup=True)

    assert app.current == "settings"
    assert app.tools_problem and "FFmpeg" in app.tools_problem
    assert any(page == "settings" for page, _t in app.find_problems())
    text = " ".join(texts(app.pages["settings"].health))
    assert "Missing" in text and "can't create songs yet" in text and "Fix it" in text
    app.preview_song(stereo_tone)
    assert app.previews.making is None

    ready = HealthReport(
        (
            Dependency("ffmpeg", "FFmpeg", True, READY, "Working."),
            Dependency("ffprobe", "FFprobe", True, READY, "Working."),
        )
    )
    app._health_done(ready, startup=False)
    assert app.tools_problem is None
    assert not any(page == "settings" for page, _t in app.find_problems())


def test_the_system_check_runs_every_tool(app) -> None:
    app.check_health()
    pump(app, lambda: not app.health_checking, 120)
    app.show_page("settings")
    text = " ".join(texts(app.pages["settings"].health))

    assert app.health is not None and app.health.ok
    for name in ("FFmpeg", "FFprobe", "Python", "Singer add-on", "Required"):
        assert name in text
    assert "Last checked" in text


def _centre(widget) -> tuple[float, float]:
    """The middle of a window's inner area, on the screen."""
    return (
        widget.winfo_rootx() + widget.winfo_width() / 2,
        widget.winfo_rooty() + widget.winfo_height() / 2,
    )


def _popups(app):
    """Open every kind of popup in turn; yields (name, popup) while it is open."""
    # pylint: disable-next=import-outside-toplevel
    from src.core.errors import ConversionError
    from src.gui_dialogs import (  # pylint: disable=import-outside-toplevel
        Dialog,
        NameDialog,
    )

    app.open_style_chooser()
    yield "style chooser", app.chooser
    app.chooser.cancel()
    app.open_customize([])
    yield "customize", app.customize
    app.customize.cancel()
    question = Dialog(app, "A question", "Sure?", [("Cancel", "no"), ("OK", "ok")])
    yield "question", question
    question.close("no")
    app._show_error(ConversionError("FFmpeg conversion failed with exit code 1: x"))
    error = [w for w in app.winfo_children() if type(w).__name__ == "ErrorDialog"][-1]
    yield "error", error
    error.close("ok")
    name = NameDialog(app, "Name", "Pick one", "party", lambda text: (text, None))
    yield "name", name
    name.close("no")


# Normal, moved, smaller than Customize, at negative x (a left monitor), maximized
@pytest.mark.parametrize(
    "where",
    ["1320x880+40+40", "1500x950+300+160", "1100x720+600+260", "1320x880+-400+60",
     "zoomed"],
)  # fmt: skip
def test_every_popup_opens_centred_over_the_window(app, where: str) -> None:
    if where == "zoomed":
        app.state("zoomed")
    else:
        app.geometry(where)
    pump(app, lambda: False, 0.8)
    try:
        for name, popup in _popups(app):
            pump(app, lambda: False, 0.4)
            # Measured from the window's own place and size, never the screen's
            assert _centre(popup) == pytest.approx(_centre(app), abs=2), name
    finally:
        app.state("normal")
        app.geometry("1320x880")


def test_output_can_be_set_for_all_songs_or_one_song(
    app, stereo_tone: Path, tmp_path: Path
) -> None:
    first, second = copies(app, stereo_tone, tmp_path, "first.mp3", "second.mp3")
    page = app.pages["output"]
    app.show_page("output")
    page.advanced.open()
    # Two plain buttons, no list: All songs is where it starts
    assert page.scope_mode.buttons.get() == "All songs"
    assert not page.scope_song.winfo_ismapped()
    assert "every song" in page.scope.cget("text")
    assert page.advanced.subtitle_label.cget("text").startswith("For all songs.")

    page.set_values(output_format="flac")
    formats = {song_config(app.settings, s, app.presets).output_format
               for s in (first, second)}  # fmt: skip
    assert formats == {"flac"}

    # One song starts at the song chosen on step 2, and switching writes nothing
    step = app.pages["styles_step"]
    app.show_page("styles_step")
    app.update()
    step.table.select([str(second)], str(second))
    app.show_page("output")
    before = (dict(app.settings.song_files), app.settings.sound)
    page._mode_picked("one")
    app.update()
    assert page.song == second and page.scope_song.winfo_ismapped()
    assert (dict(app.settings.song_files), app.settings.sound) == before
    page._scope_picked(first)
    assert "“first” only" in page.scope.cget("text")
    assert page.advanced.subtitle_label.cget("text").startswith("For “first” only.")
    # Both parts of the card follow the one scope
    page.set_values(output_format="m4a")
    page.more.title_tag.on_change(False)
    assert app.settings.song_files[first] == {
        "output_format": "m4a",
        "tag_title": False,
    }
    # The same checks refuse bad values for one song as for all songs
    assert page.typed_time("soon", "trim_start") is not None
    assert page._custom_loudness("-50") is not None
    assert (
        first not in app.settings.song_files
        or "trim_start" not in (app.settings.song_files[first])
    )
    page._mode_picked("all")
    assert page.typed_time("soon", "trim_start") is not None
    assert app.set_custom_loudness("-50") is not None
    page.set_values(output_format="opus")
    assert song_config(app.settings, first, app.presets).output_format == "m4a"
    assert song_config(app.settings, second, app.presets).output_format == "opus"
    assert app.pages["styles_step"].values(app.library.get(first))[2] == "Custom"

    page._scope_picked(first)
    assert page.scope_badge.cget("text").strip() == "Custom"
    assert "Reset to default" in page.scope_reset.cget("text")
    page._reset_scope()
    assert song_config(app.settings, first, app.presets).output_format == "opus"
    assert not app.settings.song_files
    # For All songs the same button goes back to the recommended output
    page._mode_picked("all")
    assert "Reset to recommended" in page.scope_reset.cget("text")
    page._reset_scope()
    assert app.settings.sound.output_format == "mp3"
