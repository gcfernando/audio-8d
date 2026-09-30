# Developed by ::> Gehan Fernando
"""Output scope (All songs / One song) edge cases, and editing your own styles."""

# pytest hands fixtures to tests by name, which pylint sees as shadowing
# pylint: disable=redefined-outer-name
# These tests drive the window's own parts, some of them private
# pylint: disable=protected-access

import copy
import dataclasses
import importlib.util
import logging
from pathlib import Path

import pytest
from gui_helpers import copies, customize, read, texts

from src.core.locations import presets_file
from src.core.preferences import load_preferences
from src.core.presets import PRESETS
from src.core.user_presets import all_presets, delete_user_preset, save_user_preset
from src.gui_model import song_config

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("customtkinter") is None,
    reason="the window needs CustomTkinter (pip install customtkinter)",
)


@pytest.fixture
def output(app):
    """The Output page, shown, with More output options open."""
    page = app.pages["output"]
    app.show_page("output")
    page.advanced.open()
    page._scope_picked(None)
    app.update()
    yield page
    page._scope_picked(None)


def _shown(field) -> str:
    """The option a ChoiceField shows as chosen."""
    return field.buttons.get()


def _label(field, value) -> str:
    """The words a field shows for a value."""
    return next(shown for shown, option in field.options.items() if option == value)


def _snapshot(app):
    return copy.deepcopy(app.settings)


# ------------------------------------------------------------------ scope


def test_one_song_is_greyed_out_until_there_is_a_song(app, output, stereo_tone):
    one = output.scope_mode.buttons._buttons_dict["One song"]
    assert str(one.cget("state")) == "disabled"
    assert output.song is None and _shown(output.scope_mode) == "All songs"

    copies(app, stereo_tone, stereo_tone.parent, "only.mp3")
    output.show(app.settings)
    assert str(one.cget("state")) == "normal"


def test_the_keyboard_never_picks_one_song_without_songs(app, output) -> None:
    before = _snapshot(app)
    # Arrow keys step through the options; a greyed-out one must be skipped
    output.scope_mode._step(1)
    app.update()
    assert output.song is None
    assert app.settings == before


def test_removing_the_chosen_song_goes_back_to_all_songs(
    app, output, stereo_tone: Path, tmp_path: Path
) -> None:
    first, second = copies(app, stereo_tone, tmp_path, "first.mp3", "second.mp3")
    output._scope_picked(first)
    output.set_values(output_format="flac")
    assert output.song == first

    app.remove_songs([first])
    app.update()
    assert output.song is None
    assert _shown(output.scope_mode) == "All songs"
    assert not output.scope_song.winfo_ismapped()
    assert output.advanced.subtitle_label.cget("text").startswith("For all songs.")
    assert first not in app.settings.song_files
    # The other song is still offered for One song
    output._mode_picked("one")
    assert output.song == second


def test_one_song_starts_at_the_song_chosen_on_step_2(
    app, output, stereo_tone: Path, tmp_path: Path
) -> None:
    first, second = copies(app, stereo_tone, tmp_path, "first.mp3", "second.mp3")
    step = app.pages["styles_step"]
    for song in (second, first, second):
        app.show_page("styles_step")
        app.update()
        step.table.select([str(song)], str(song))
        app.show_page("output")
        output._mode_picked("one")
        assert output.song == song
        assert f"“{song.stem}” only" in output.scope.cget("text")
        output._mode_picked("all")
        assert output.song is None


def test_switching_scope_never_changes_a_setting(
    app, output, stereo_tone: Path, tmp_path: Path
) -> None:
    first, second = copies(app, stereo_tone, tmp_path, "first.mp3", "second.mp3")
    output._scope_picked(first)
    output.set_values(output_format="m4a")
    output._scope_picked(None)
    before = _snapshot(app)

    for target in (first, None, second, first, None):
        if target is None:
            output._mode_picked("all")
        else:
            output._scope_picked(target)
        app.update()
        assert app.settings == before
    # Opening and closing More output options writes nothing either
    output.advanced.toggle()
    output.advanced.toggle()
    assert app.settings == before


def test_every_control_shows_the_scope_being_edited(
    app, output, stereo_tone: Path, tmp_path: Path
) -> None:
    first, _second = copies(app, stereo_tone, tmp_path, "first.mp3", "second.mp3")
    more = output.more
    assert more is not None
    # All songs: FLAC, part of the song from 0:03
    output.set_values(output_format="flac")
    assert output.typed_time("0:03", "trim_start") is None
    # One song: MP3 Small, Apple Music loudness, part from 0:10, no title tag
    output._scope_picked(first)
    output.set_values(output_format="mp3", bitrate=128)
    output.set_values(match_loudness=False, loudness_target=-16.0)
    assert output.typed_time("0:10", "trim_start") is None
    more.title_tag.on_change(False)
    app.update()

    def check_all() -> None:
        output._scope_picked(None)
        app.update()
        assert output.format.menu.get() == _label(output.format, "flac")
        assert not output.quality.winfo_ismapped()
        assert not more.bitrate.winfo_ismapped()
        assert _shown(output.loudness) == _label(output.loudness, -14.0)
        assert more.start.entry.get() == "0:03"
        assert more.title_tag.get() is True

    def check_one() -> None:
        output._scope_picked(first)
        app.update()
        assert output.format.menu.get() == _label(output.format, "mp3")
        assert _shown(output.quality) == _label(output.quality, 128)
        assert _shown(more.bitrate) == "128"
        assert _shown(output.loudness) == _label(output.loudness, "advanced")
        assert _shown(output.more_loudness) == _label(output.more_loudness, -16.0)
        assert more.start.entry.get() == "0:10"
        assert more.title_tag.get() is False

    for check in (check_all, check_one, check_all, check_one):
        check()


def test_the_custom_level_box_shows_the_scope_being_edited(
    app, output, stereo_tone: Path, tmp_path: Path
) -> None:
    first, _second = copies(app, stereo_tone, tmp_path, "first.mp3", "second.mp3")
    # All songs: a custom level of -18
    output._loudness("advanced")
    output.custom_loud.set("-18")
    output._more_loudness("custom")
    assert app.settings.loudness_is_custom
    assert app.settings.custom_loudness_text == "-18"
    # One song: a custom level of -20
    output._scope_picked(first)
    assert output._custom_loudness("-20") is None
    assert output.custom_loud.entry.get() == "-20"

    output._scope_picked(None)
    app.update()
    assert output.custom_loud.winfo_ismapped()
    # The box must show the defaults' -18 again, not the song's -20
    assert output.custom_loud.entry.get() == "-18"


# ------------------------------------------------------------------ validation


@pytest.mark.parametrize("scope", ["all", "one"])
@pytest.mark.parametrize("typed", ["-50", "abc", "-4"])
def test_a_bad_custom_level_is_refused_in_both_scopes(
    app, output, stereo_tone: Path, tmp_path: Path, scope: str, typed: str
) -> None:
    first, _second = copies(app, stereo_tone, tmp_path, "first.mp3", "second.mp3")
    if scope == "one":
        output._scope_picked(first)
    before = _snapshot(app)

    assert output._custom_loudness(typed)
    assert app.settings.sound == before.sound
    assert app.settings.song_files == before.song_files
    # A refused level is never stored for later either
    assert app.settings.custom_loudness_text == before.custom_loudness_text


@pytest.mark.parametrize("scope", ["all", "one"])
def test_a_bad_time_is_refused_in_both_scopes(
    app, output, stereo_tone: Path, tmp_path: Path, scope: str
) -> None:
    first, _second = copies(app, stereo_tone, tmp_path, "first.mp3", "second.mp3")
    if scope == "one":
        output._scope_picked(first)
    before = _snapshot(app)

    for key in ("trim_start", "trim_end"):
        assert output.typed_time("soon", key)
        assert output.typed_time("1:99:99:99", key)
    assert app.settings == before


# ------------------------------------------------------------------ editing styles


@pytest.fixture
def mine(app, monkeypatch):
    """One saved style of your own, 'Mine Edit', removed again afterwards."""
    base = PRESETS["studio"].config
    save_user_preset(
        "Mine Edit", dataclasses.replace(base, intensity=0.6), based_on="studio"
    )
    save_user_preset("Taken Name", base, based_on="studio")
    app.reload_styles()
    monkeypatch.setattr("src.gui_style_save.Dialog.ask", lambda self: "as-is")
    yield "Mine Edit"
    if app.customize is not None and app.customize.is_open:
        app.customize.cancel()
    for name in ("Mine Edit", "Mine Renamed", "Taken Name"):
        delete_user_preset(name)
    app.choose_style("studio")
    app.reload_styles()


def _state(dialog) -> str:
    return str(dialog.apply_button.cget("state"))


@pytest.mark.parametrize(
    ("typed", "why"),
    [
        ("", "Type a name"),
        ("   ", "Type a name"),
        ("studio", "built-in"),
        ("HiFi", "built-in"),
        ("lossless", "built-in"),
        ("taken name", "already have"),
        ("Aa " * 20, "too long"),
        ("9 Lives", "start with a letter"),
    ],
)
def test_a_name_that_cant_be_used_blocks_save_changes(
    app, mine: str, typed: str, why: str
) -> None:
    app.edit_style(mine)
    dialog = app.customize
    before = presets_file().read_text(encoding="utf-8")
    dialog.tune(intensity=0.9)
    dialog.name_field.set(typed)
    problem = dialog._name_typed(typed) or ""

    assert why.lower() in problem.lower()
    assert _state(dialog) == "disabled"
    assert "Can't save" in dialog.note.cget("text")
    # Even if Save were pressed, nothing is written and the dialog stays open
    dialog.apply()
    assert dialog.is_open
    assert presets_file().read_text(encoding="utf-8") == before


def test_built_in_and_unknown_styles_open_nothing(app) -> None:
    for name in ("studio", "front", "hifi", "No Such Style"):
        app.edit_style(name)
        assert app.customize is None or not app.customize.is_open


def test_a_failed_quality_check_leaves_the_file_as_it_was(
    app, mine: str, monkeypatch
) -> None:
    class Note:  # pylint: disable=too-few-public-methods
        """A made-up quality-check error."""

        level, text = "error", "made up problem for the test"

    monkeypatch.setattr("src.gui_style_save.style_check", lambda *_a: [Note()])
    app.edit_style(mine)
    dialog = app.customize
    before = presets_file().read_text(encoding="utf-8")
    dialog.tune(intensity=0.9)
    dialog.apply()

    assert dialog.is_open and "made up problem" in dialog.note.cget("text")
    assert presets_file().read_text(encoding="utf-8") == before
    assert app.presets[mine].config.intensity == 0.6


def test_go_back_on_a_warning_saves_nothing(app, mine: str, monkeypatch) -> None:
    class Note:  # pylint: disable=too-few-public-methods
        """A made-up quality-check warning."""

        level, text = "warning", "made up warning"

    monkeypatch.setattr("src.gui_style_save.style_check", lambda *_a: [Note()])
    monkeypatch.setattr("src.gui_style_save.Dialog.ask", lambda self: "no")
    app.edit_style(mine)
    dialog = app.customize
    before = presets_file().read_text(encoding="utf-8")
    dialog.tune(intensity=0.9)
    dialog.apply()

    assert dialog.is_open
    assert presets_file().read_text(encoding="utf-8") == before


def test_the_speakers_switch_and_output_never_reach_the_style(app, mine: str) -> None:
    app.set_speakers(True)
    app.set_default_output(
        output_format="flac", match_loudness=True, loudness_target=None, bitrate=None
    )
    app.edit_style(mine)
    dialog = app.customize
    dialog.tune(intensity=0.9)
    dialog.apply()
    assert not dialog.is_open

    saved = all_presets()[mine].config
    assert saved.engine == "3d" and saved.intensity == 0.9
    assert saved.output_format == "mp3" and saved.loudness_target == -14.0
    text = presets_file().read_text(encoding="utf-8")
    section = text.split("Mine Edit", 1)[1].split("[", 1)[0]
    for word in ("output_format", "match_loudness", "loudness_target", "bitrate",
                 "limiter_ceiling", "engine", "speakers"):  # fmt: skip
        assert word not in section, word
    # The window's own choices are untouched
    assert app.settings.speakers and app.settings.sound.output_format == "flac"


def test_an_unusable_output_setting_never_blocks_saving_a_style(app, mine: str) -> None:
    # A custom level typed wrong on the Output step is not part of any style
    app.settings.loudness_is_custom = True
    app.set_custom_loudness("abc")
    try:
        app.edit_style(mine)
        dialog = app.customize
        dialog.tune(intensity=0.9)
        dialog.apply()
        assert not dialog.is_open, dialog.note.cget("text")
        assert all_presets()[mine].config.intensity == 0.9
    finally:
        app.settings.loudness_is_custom = False
        app.set_custom_loudness("-14")


def test_cancel_forgets_the_edit_and_customize_is_normal_again(app, mine: str) -> None:
    before = presets_file().read_text(encoding="utf-8")
    app.edit_style(mine)
    dialog = app.customize
    dialog.tune(intensity=0.9)
    dialog.name_field.set("Mine Renamed")
    dialog.cancel()
    assert presets_file().read_text(encoding="utf-8") == before
    assert mine in app.presets

    app.open_customize([])
    app.update()
    assert dialog.style.winfo_ismapped()
    assert not dialog.name_field.winfo_ismapped()
    assert "Save" not in dialog.apply_button.cget("text")
    dialog.cancel()


def test_an_edit_and_rename_survive_a_restart(app, mine: str) -> None:
    app.choose_style(mine)
    app.edit_style(mine)
    dialog = app.customize
    dialog.tune(intensity=0.9, ambience=0.3)
    dialog.name_field.set("mine renamed")
    dialog._name_typed("mine renamed")
    dialog.apply()
    assert not dialog.is_open
    # The window shows the new name and values at once
    assert app.settings.style == "Mine Renamed" and mine not in app.presets
    assert app.settings.sound.intensity == 0.9

    app._save_defaults()
    # What a fresh start reads back
    fresh = all_presets()
    assert mine not in fresh
    assert fresh["Mine Renamed"].config.intensity == 0.9
    assert fresh["Mine Renamed"].config.ambience == 0.3
    assert load_preferences()[0].default_style == "Mine Renamed"


def test_closing_the_window_saves_defaults_changed_a_moment_ago(
    app, output, monkeypatch
) -> None:
    output.set_values(output_format="flac")
    assert getattr(app, "_remember_job", None), "the save should still be waiting"
    # Close without really destroying the shared test window
    monkeypatch.setattr(app, "destroy", lambda: None)
    monkeypatch.setattr(app.player, "close", lambda: None)
    monkeypatch.setattr(app.previews, "close", lambda: None)
    monkeypatch.setattr("src.gui_app.kill_all_processes", lambda: 0)
    handler = app.log_handler
    try:
        app.close()
    finally:
        logging.getLogger().addHandler(handler)
        app.addon_cancel.clear()

    assert load_preferences()[0].output.get("output_format") == "flac"


def test_a_saved_style_is_edited_renamed_and_saved_in_place(
    app, stereo_tone: Path, monkeypatch
) -> None:
    base = PRESETS["studio"].config
    save_user_preset("Calm Edit", dataclasses.replace(base, intensity=0.6),
                     based_on="studio")  # fmt: skip
    save_user_preset("Other Style", base, based_on="studio")
    app.reload_styles()
    read(app, [stereo_tone])
    customize(app, [stereo_tone], "Calm Edit")
    monkeypatch.setattr("src.gui_style_save.Dialog.ask", lambda self: "as-is")
    try:
        # Built-in styles stay read-only
        app.edit_style("studio")
        assert app.customize is None or not app.customize.is_open

        app.edit_style("Calm Edit")
        dialog = app.customize
        assert dialog is not None
        assert dialog.name_field.entry.get() == "Calm Edit"
        assert not dialog.style.winfo_ismapped()
        assert str(dialog.apply_button.cget("state")) == "disabled"
        before = presets_file().read_text(encoding="utf-8")

        # The existing name checks refuse a taken name before anything is saved
        dialog.name_field.set("other style")
        assert "already have" in (dialog._name_typed("other style") or "")
        assert str(dialog.apply_button.cget("state")) == "disabled"
        # The existing quality check refuses a style with no movement at all
        dialog.name_field.set("Calm Edit")
        dialog.tune(intensity=0.0)
        dialog.apply()
        assert "Can't save" in dialog.note.cget("text") and dialog.is_open
        assert presets_file().read_text(encoding="utf-8") == before

        # Changed and renamed, then saved back to the same style
        dialog.tune(intensity=0.9)
        dialog.name_field.set("calm evening")
        dialog._name_typed("calm evening")
        assert str(dialog.apply_button.cget("state")) == "normal"
        dialog.apply()
        assert not dialog.is_open
        assert "Calm Edit" not in app.presets
        assert app.presets["Calm Evening"].config.intensity == 0.9
        # A song using it follows at once, and the lists show the new name
        assert app.settings.song_styles[stereo_tone] == "Calm Evening"
        assert song_config(app.settings, stereo_tone, app.presets).intensity == 0.9
        app.show_page("styles")
        assert any("Calm Evening" in t for t in texts(app.pages["styles"].saved.body))
        # What a restart reads back from the styles file
        assert all_presets()["Calm Evening"].config.intensity == 0.9
        assert "Calm Edit" not in all_presets()
    finally:
        for name in ("Calm Edit", "Calm Evening", "Other Style"):
            delete_user_preset(name)
        app.choose_style("studio")
        app.reload_styles()


def test_editing_the_default_style_reaches_every_default_song(app, monkeypatch) -> None:
    base = PRESETS["studio"].config
    save_user_preset("Calm Default", dataclasses.replace(base, intensity=0.6),
                     based_on="studio")  # fmt: skip
    app.reload_styles()
    app.choose_style("Calm Default")
    monkeypatch.setattr("src.gui_style_save.Dialog.ask", lambda self: "as-is")
    try:
        app.edit_style("Calm Default")
        dialog = app.customize
        assert dialog is not None
        dialog.tune(intensity=0.8)
        dialog.apply()
        assert app.settings.style == "Calm Default"
        assert app.settings.sound.intensity == 0.8
        # What a restart reads back: the file, then the remembered default
        assert all_presets()["Calm Default"].config.intensity == 0.8
        app._save_defaults()
        assert load_preferences()[0].default_style == "Calm Default"
    finally:
        delete_user_preset("Calm Default")
        app.choose_style("studio")
        app.reload_styles()
