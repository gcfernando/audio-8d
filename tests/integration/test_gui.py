# Developed by ::> Gehan Fernando
"""Drives the real Audio8D window: songs, styles, previews, output and creating."""

# pytest hands fixtures to tests by name, which pylint sees as shadowing
# pylint: disable=redefined-outer-name
# These tests drive the window's own parts, some of them private
# pylint: disable=protected-access

import importlib.util
import os
import shutil
import time
from pathlib import Path

import pytest
from gui_helpers import copies, customize, pump, read, tagged, texts

from src.gui_model import song_config

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("customtkinter") is None,
    reason="the window needs CustomTkinter (pip install customtkinter)",
)


# ------------------------------------------------------------ start and songs


def test_window_starts_on_step_one_with_the_best_style(app) -> None:
    assert app.current == "songs"
    assert app.settings.style == "studio"
    for key in ("songs", "styles_step", "output", "review", "styles", "settings"):
        app.show_page(key)
        app.update()
        assert app.current == key
    # Old page names still lead somewhere sensible
    app.show_page("sound")
    assert app.current == "styles_step"


def test_adding_songs_reads_their_tags_in_the_background(
    app, stereo_tone: Path, tmp_path: Path
) -> None:
    song = tagged(
        stereo_tone,
        tmp_path / "Band" / "Anchor.mp3",
        genre="Rock; Electronic",
        artist="Iron Tide",
        album="Deep",
    )
    read(app, [song, song.with_name("notes.txt")])

    track = app.library.tracks[0]
    assert [t.song for t in app.library.tracks] == [song]
    assert track.length_text == "0:03"
    assert track.genre == "Rock, Electronic" and track.artist == "Iron Tide"
    row = app.pages["songs"].table.tree.item(str(song), "values")
    assert list(row) == ["Anchor", "Iron Tide", "Deep", "Rock, Electronic", "0:03",
                         "MP3", "Ready"]  # fmt: skip
    app.add_paths([song])
    assert len(app.library) == 1
    assert app.nav["songs"].status.cget("text") == "✓ 1 song"


def test_a_song_that_cant_be_read_is_explained_and_skipped(app, tmp_path: Path) -> None:
    broken = tmp_path / "broken.mp3"
    broken.write_bytes(b"this is not music")
    read(app, [broken])

    track = app.library.tracks[0]
    assert track.state == "unreadable"
    assert track.problem == "not music, or damaged"
    assert app.convertible_count() == 0
    assert any("can be read as music" in p for _page, p in app.find_problems())


# ------------------------------------------------------------ styles


def test_suggestions_come_from_each_songs_genres(
    app, stereo_tone: Path, tmp_path: Path
) -> None:
    songs = [
        tagged(stereo_tone, tmp_path / "a.mp3", genre="Rock; Electronic"),
        tagged(stereo_tone, tmp_path / "b.mp3", genre="Lo-Fi; Hip-Hop"),
        tagged(stereo_tone, tmp_path / "c.mp3"),
    ]
    read(app, songs)
    step = app.pages["styles_step"]
    app.show_page("styles_step")

    suggested = {
        t.name: app.library.suggestion(t).primary.style for t in app.library.tracks
    }
    # c has no tags; at 3 seconds long it counts as a short clip
    assert suggested == {"a": "strong", "b": "smooth", "c": "whirlwind"}
    # The list only says what matters: song, sound, Default or Custom, actions
    row = step.table.tree.item(str(songs[1]), "values")
    assert list(row[:3]) == ["b", "Studio", "Default"]
    assert "Preview" in row[3] and "Customize" in row[3]
    assert "unsure" not in " ".join(str(v) for v in row)

    # Suggestions are used only where Audio8D is sure; nothing else changes
    app.apply_suggestions()
    assert app.settings.song_styles[songs[1]] == "smooth"
    assert step.table.tree.item(str(songs[1]), "values")[1:3] == ("Smooth", "Custom")


def test_one_default_and_bulk_exceptions_for_many_songs(
    app, stereo_tone: Path, tmp_path: Path
) -> None:
    songs = [shutil.copy(stereo_tone, tmp_path / f"s{n}.mp3") for n in range(6)]
    read(app, map(Path, songs))
    step = app.pages["styles_step"]
    app.show_page("styles_step")
    paths = [Path(s) for s in songs]

    # Four songs at once, in one clearly labelled dialog
    step.table.select([str(p) for p in paths[:4]])
    step.show_selection()
    assert "4 of 6 selected" in step.selection_text.cget("text")
    assert "Customize 4 songs" in step.customize.cget("text")
    step._customize()
    assert app.customize.heading.cget("text") == "Customize 4 songs"
    app.customize._style_picked("groove")
    app.customize.apply()
    assert all(app.settings.song_styles[p] == "groove" for p in paths[:4])
    assert step.table.tree.item(str(paths[0]), "values")[1:3] == ("Groove", "Custom")
    assert step.table.tree.item(str(paths[5]), "values")[1:3] == ("Studio", "Default")

    # A new default keeps the exceptions; songs that had it simply follow it
    customize(app, [paths[4]], "voice")
    app.choose_style("groove")
    assert app.settings.style == "groove"
    assert app.settings.song_styles == {paths[4]: "voice"}

    # Reset to default: the song follows the defaults again
    step.table.select([str(paths[4])])
    step.show_selection()
    assert str(step.reset.cget("state")) == "normal"
    step._reset()
    assert app.settings.song_styles == {}
    assert step.table.tree.item(str(paths[4]), "values")[2] == "Default"


def test_cancel_changes_nothing_and_apply_changes_only_that_song(
    app, stereo_tone: Path, tmp_path: Path
) -> None:
    first, second = copies(app, stereo_tone, tmp_path, "first.mp3", "second.mp3")
    app.show_page("styles_step")
    app.open_customize([first])
    dialog = app.customize
    assert dialog.heading.cget("text") == "Customize “first”"
    dialog.tune(intensity=0.95, bass_hz=0.0)
    dialog.cancel()
    assert not app.settings.song_sound and not app.settings.song_styles

    app.open_customize([first])
    dialog.levels["movement"].set(0.95)
    dialog.tune(intensity=0.95)
    assert dialog.badge.cget("text").strip() == "Custom"
    dialog.apply()
    assert app.settings.song_sound == {first: {"intensity": 0.95}}
    assert second not in app.settings.song_sound
    # Songs added after a change of default follow the new default
    app.choose_style("smooth")
    (third,) = copies(app, stereo_tone, tmp_path, "third.mp3")
    assert app.pages["styles_step"].table.tree.item(str(third), "values")[1] == "Smooth"


def test_the_style_chooser_applies_only_on_apply(app, stereo_tone: Path) -> None:
    read(app, [stereo_tone])
    app.show_page("styles_step")
    app.open_style_chooser()
    chooser = app.chooser
    assert chooser.is_open and chooser.selected == "studio"
    assert "In use" in chooser.cards["studio"].marks.cget("text")
    chooser.select("smooth")
    assert "Selected" in chooser.cards["smooth"].marks.cget("text")
    chooser.cancel()
    assert app.settings.style == "studio"

    app.open_style_chooser()
    chooser._step(1)  # the arrow keys move the selection too
    assert chooser.selected == "gentle"
    chooser.pick_and_apply("smooth")
    assert app.settings.style == "smooth" and not chooser.is_open
    step = app.pages["styles_step"]
    assert step.default_name.cget("text") == "Smooth"


def test_style_choice_reaches_the_real_conversion_of_each_song(
    app, stereo_tone: Path, tmp_path: Path
) -> None:
    first, second = copies(app, stereo_tone, tmp_path, "first.mp3", "second.mp3")
    customize(app, [second], "voice")
    app.change_sound(output_format="flac")
    app.set_destination(str(tmp_path / "out"))
    app.run_convert()
    pump(app, lambda: not app.busy)

    items = {item.source: item for item in app.run_items}
    assert items[first].config is None  # the default (Studio, saved as FLAC)
    assert items[second].config.path == "arc"  # Voice's own movement
    assert items[second].config.output_format == "flac"  # but the shared FLAC file
    assert (tmp_path / "out" / "first (8D).flac").is_file()
    assert (tmp_path / "out" / "second (8D).flac").is_file()
    assert {row[3] for row in app.run_results.values()} == {"done"}
    assert "All done: 2 songs made" in " ".join(texts(app.pages["review"].result_note))


# ------------------------------------------------------------ previews


def test_every_song_can_be_previewed_on_its_own(
    app, dynamic_song: Path, tmp_path: Path
) -> None:
    other = tmp_path / "other" / "dynamic.wav"
    other.parent.mkdir()
    shutil.copy(dynamic_song, other)
    read(app, [dynamic_song, other])
    app.set_preview_seconds(10)
    customize(app, [other], "voice")
    step = app.pages["styles_step"]
    app.show_page("styles_step")

    # The second song (same name, other folder), not the first
    step.table.select([str(other)], str(other))
    step.show_selection()
    assert step.focused_song() == other
    step._preview()
    assert "Preparing" in step.preview.cget("text")
    pump(app, lambda: app.previews.status_of(other).state in ("ready", "failed"))

    status = app.previews.status_of(other)
    assert status.state == "ready", status.problem
    assert app.player_song == other
    assert app.preview_words(other) == "■ Stop"
    # Never next to the music: previews live in a private temporary folder
    assert status.file is not None and status.file.parent == app.previews.folder
    assert app.previews.status_of(dynamic_song).state == "idle"
    # It was made with the second song's own style
    config = song_config(app.settings, other, app.presets)
    assert app.previews.is_current(other, config, 10)

    app.preview_song(dynamic_song)
    pump(app, lambda: app.previews.status_of(dynamic_song).state == "ready")
    first_file = app.previews.status_of(dynamic_song).file
    assert first_file != status.file
    assert app.player_song == dynamic_song
    app.preview_song(dynamic_song)  # pressing it again is Stop
    assert app.player_song is None
    assert app.preview_words(dynamic_song) == "▶ Preview"


def test_switching_songs_quickly_never_mixes_up_previews(
    app, dynamic_song: Path, tmp_path: Path
) -> None:
    copies = []
    for number in range(3):
        copy = tmp_path / f"song {number}.wav"
        shutil.copy(dynamic_song, copy)
        copies.append(copy)
    read(app, copies)
    app.set_preview_seconds(10)

    for song in copies:  # asked for one after another, faster than they finish
        app.preview_song(song)
        app.update()
    pump(app, lambda: not app.previews.busy)

    last = app.previews.status_of(copies[-1])
    assert last.state == "ready"
    assert app.player_song == copies[-1]
    assert all(app.previews.status_of(s).state == "idle" for s in copies[:-1])


def test_a_changed_style_replaces_the_old_preview_file(app, dynamic_song: Path) -> None:
    read(app, [dynamic_song])
    app.set_preview_seconds(10)
    app.preview_song(dynamic_song)
    pump(app, lambda: app.previews.status_of(dynamic_song).state == "ready")
    old = app.previews.status_of(dynamic_song).file
    app.stop_playing()

    customize(app, [dynamic_song], "strong")
    app.preview_song(dynamic_song)
    pump(app, lambda: app.previews.status_of(dynamic_song).state == "ready")
    new = app.previews.status_of(dynamic_song).file
    # The out-of-date preview is deleted as soon as a new one replaces it
    assert new != old and old is not None and not old.exists()
    app.stop_playing()


def test_stopping_a_preview_is_not_reported_as_an_error(
    app, dynamic_song: Path, monkeypatch
) -> None:
    shown: list[str] = []
    monkeypatch.setattr("src.gui_app.Dialog.ask", lambda self: shown.append("x"))
    read(app, [dynamic_song])
    app.set_preview_seconds(60)
    app.preview_song(dynamic_song)
    app.update()
    app.stop()
    pump(app, lambda: not app.previews.busy, 30)

    assert not shown
    assert app.previews.status_of(dynamic_song).state == "idle"


def test_a_missing_song_preview_fails_with_plain_words(
    app, stereo_tone: Path, tmp_path: Path
) -> None:
    song = tmp_path / "gone.mp3"
    shutil.copy(stereo_tone, song)
    read(app, [song])
    song.unlink()
    app.preview_song(song)
    pump(app, lambda: app.previews.status_of(song).state == "failed", 30)

    problem = app.previews.status_of(song).problem
    assert "What to do" in problem and "Traceback" not in problem


# ------------------------------------------------------------ output and checks


def test_start_is_blocked_until_the_setup_is_valid(app, stereo_tone: Path) -> None:
    review = app.pages["review"]
    read(app, [stereo_tone])
    app.settings.speed_curve_text = "nonsense"
    app.sync_controls()
    app.run_convert()
    assert not app.busy
    assert app.current == "review"
    assert str(review.start.cget("state")) == "disabled"
    app.settings.speed_curve_text = ""
    app.set_destination("relative folder")
    app.show_page("review")
    assert any("complete folder" in text for _p, text in app.find_problems())
    app.set_destination("")
    app.show_page("review")
    assert str(review.start.cget("state")) == "normal"


def test_output_controls_show_only_what_applies(app, stereo_tone: Path) -> None:
    output = app.pages["output"]
    app.show_page("output")
    # Plain words first: format, quality and loudness, for every song
    assert output.format.menu.get() == "MP3 — works everywhere"
    assert output.quality.buttons.get() == "High"
    assert output.loudness.buttons.get() == "Match music apps"
    assert output.scope_mode.buttons.get() == "All songs"
    output.advanced.open()  # its controls are made when it first opens
    app.change_sound(output_format="flac")
    app.update()
    assert not output.quality.winfo_ismapped()
    # Only what applies is shown: FLAC has no bitrate
    assert not output.more.bitrate.winfo_ismapped()
    app.change_sound(output_format="opus")
    # High means the best a format needs, not always 320
    assert app.settings.sound.bitrate == 192
    app.change_sound(output_format="mp3", bitrate=None)
    app.show_page("output")
    app.update()
    assert output.more.quality.winfo_ismapped()
    output._loudness("advanced")
    app.update()
    assert output.more_loudness.winfo_ismapped()
    output._more_loudness(None)
    app.update()
    assert not output.more.exact.winfo_ismapped()
    output._more_loudness("custom")
    app.update()
    assert output.custom_loud.winfo_ismapped()
    assert app.set_custom_loudness("-50") is not None
    assert app.set_custom_loudness("-16") is None
    output._loudness("match")
    assert app.settings.sound.match_loudness is True
    # 'Same name as the original' needs a folder; a custom name needs one song
    read(app, [stereo_tone])
    app.show_page("output")
    assert "needs a folder" in output.naming.help.cget("text")
    app.set_name_style("original")
    assert "overwrite it" in output.naming.help.cget("text")
    app.set_name_style("8d")


def test_what_will_happen_is_summed_up_before_starting(app, stereo_tone: Path) -> None:
    read(app, [stereo_tone])
    customize(app, [stereo_tone], "voice")
    app.show_page("review")
    review = app.pages["review"]
    text = " ".join(texts(review.summary))

    for words in ("1 song", "Studio; 1 song has custom settings", "MP3, High quality",
                  "Match music apps", "Next to each original song"):  # fmt: skip
        assert words in text, words
    assert review.start.cget("text").strip() == "Create 1 song"


def test_a_failing_song_shows_the_reason_and_can_be_retried(
    app, stereo_tone: Path, tmp_path: Path
) -> None:
    good = tmp_path / "good.mp3"
    shutil.copy(stereo_tone, good)
    read(app, [good])
    app.set_destination(str(tmp_path / "out"))
    good.write_bytes(b"broken after it was read")
    app.run_convert()
    pump(app, lambda: not app.busy)

    style, status, result, kind = app.run_results[good]
    assert kind == "problem" and status == "Problem"
    assert "What to do" in result
    assert str(app.pages["review"].retry.cget("state")) == "normal"
    shutil.copy(stereo_tone, good)
    app.retry_failed()
    pump(app, lambda: not app.busy)
    assert app.run_results[good][3] == "done"
    del style


def test_stop_keeps_the_window_usable(app, dynamic_song: Path, tmp_path: Path) -> None:
    read(app, [dynamic_song])
    app.set_destination(str(tmp_path / "out"))
    app.run_convert()
    app.stop()
    pump(app, lambda: not app.busy, 60)

    assert not app.busy
    assert "Stopped" in app.status_text.cget("text")
    assert str(app.pages["review"].start.cget("state")) == "normal"


def test_replacing_the_originals_from_the_window(
    app, stereo_tone: Path, monkeypatch
) -> None:
    removed: list[Path] = []

    def fake_remove(path: Path) -> str:
        removed.append(path)
        path.unlink()
        return "Recycle Bin"

    monkeypatch.setattr("src.pipeline.remove_original", fake_remove)
    monkeypatch.setattr("src.gui_app.Dialog.ask", lambda self: "yes")
    read(app, [stereo_tone])
    app.set_originals("replace")
    app.run_convert()
    pump(app, lambda: not app.busy)

    assert removed == [stereo_tone]
    assert stereo_tone.is_file()  # now the 8D version, under the original name
    assert "original moved to the Recycle Bin" in app.run_results[stereo_tone][2]


def test_a_second_run_skips_songs_that_already_have_an_8d_file(
    app, stereo_tone: Path, tmp_path: Path
) -> None:
    read(app, [stereo_tone])
    app.set_destination(str(tmp_path / "out"))
    app.run_convert()
    pump(app, lambda: not app.busy)
    app.run_convert()
    pump(app, lambda: not app.busy)

    assert app.run_results[stereo_tone][3] == "skipped"
    assert "Nothing new to create" in " ".join(texts(app.pages["review"].result_note))


# ------------------------------------------------------------ big batches


def test_three_hundred_songs_stay_quick_and_every_one_is_reported(
    app, stereo_tone: Path, tmp_path: Path
) -> None:
    folder = tmp_path / "library"
    folder.mkdir()
    for number in range(300):
        target = folder / f"song {number:03}.mp3"
        if number % 10 == 0:
            target.write_bytes(b"not music")  # every tenth song is broken
        else:
            try:
                os.link(stereo_tone, target)
            except OSError:
                shutil.copy(stereo_tone, target)
    slowest = 0.0
    app.add_paths([folder])
    end = time.time() + 120
    while (
        app.scans_waiting or any(t.state == "reading" for t in app.library.tracks)
    ) and time.time() < end:
        started = time.perf_counter()
        app.update()
        slowest = max(slowest, time.perf_counter() - started)
        time.sleep(0.01)
    pump(app, lambda: False, 1)

    assert len(app.library) == 300
    assert sum(1 for t in app.library.tracks if t.state == "unreadable") == 30
    assert slowest < 2.0, f"the window froze for {slowest:.2f} s"
    step = app.pages["styles_step"]
    started = time.perf_counter()
    app.show_page("styles_step")
    step.table.select_all()
    app.update_idletasks()
    # Showing 300 songs, all selected, stays quick
    assert time.perf_counter() - started < 3.0
    assert len(step.selected_songs()) == 300
    started = time.perf_counter()
    step._customize()
    app.customize._style_picked("smooth")
    app.customize.apply()
    # So does customizing all of them at once
    assert time.perf_counter() - started < 3.0
    # The readable songs get it; songs that can't be read are left out
    assert len(app.settings.song_styles) == 270

    # The broken tenth converts to a clear problem each; nothing stops the rest
    app.settings.jobs = 8
    app.set_destination(str(tmp_path / "out"))
    readable = app.convertible_count()
    assert readable == 270
    monkey_items = [t.song for t in app.library.tracks if t.state == "ready"][:0]
    del monkey_items


def test_long_lists_convert_and_summarise_every_problem(app, tmp_path: Path) -> None:
    songs = []
    for number in range(60):
        song = tmp_path / f"broken {number:02}.mp3"
        song.write_bytes(b"not music")
        songs.append(song)
    app.add_paths(songs)
    # Pretend they were readable, so the conversion itself meets the problem
    for track in app.library.tracks:
        track.state = "ready"
    app.set_destination(str(tmp_path / "out"))
    app.run_convert()
    pump(app, lambda: not app.busy, 120)

    assert len(app.run_results) == 60
    assert {row[3] for row in app.run_results.values()} == {"problem"}
    review = app.pages["review"]
    review.only_problems.set(True)
    review.show_results()
    assert len(review.results.row_ids()) == 60
    review._copy_problems()
    assert app.clipboard_get().count("\n") == 59
    assert "0 made, 60 couldn't be made" in " ".join(texts(review.result_note))
    review.only_problems.set(False)
