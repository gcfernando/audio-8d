# Developed by ::> Gehan Fernando
"""The main window, part: the song list and each song's style."""

import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog

from .app_base import (
    LOG,
    READERS,
    AppBase,
    read_problem,
)
from .core.errors import Audio8DError
from .core.presets import RECOMMENDED_PRESET
from .ffmpeg import (
    FFmpegToolchain,
    probe_audio,
)
from .files import AUDIO_EXTENSIONS, find_songs, is_own_output
from .gui_dialogs import Dialog
from .gui_model import is_custom
from .library import (
    READY,
    UNREADABLE,
    Track,
    change_default,
    forget_missing_styles,
)
from .recommend import BatchSuggestion

# The status bar while added folders are looked through
LOOKING = "Looking for songs…"
# What was found at one added path: (path, is it a folder, its songs or None)
Looked = tuple[Path, bool, list[tuple[Path, Path | None]] | None]


class LibraryMixin(AppBase):
    """Steps 1 and 2: adding, reading and removing songs, and their styles."""

    def set_recursive(self, on: bool) -> None:
        """'Include songs in sub-folders' (applies to folders added from now on)."""
        self.settings.recursive = on

    def ask_files(self) -> None:
        """Add songs from a file dialog."""
        patterns = " ".join(f"*{ext}" for ext in sorted(AUDIO_EXTENSIONS))
        chosen = filedialog.askopenfilenames(
            title="Choose songs", filetypes=[("Music", patterns), ("All files", "*.*")]
        )
        self.add_paths([Path(name) for name in chosen])

    def ask_folder(self) -> None:
        """Add a folder of songs."""
        chosen = filedialog.askdirectory(title="Choose a folder of songs")
        if chosen:
            self.add_paths([Path(chosen)])

    def add_paths(self, paths: list[Path]) -> None:
        """Add dropped or chosen files; folders add every song inside them."""
        if self.busy:
            self.toast("Please wait until the songs are created", "error")
            return
        recursive = self.settings.recursive
        if not self.scans_waiting and not any(path.is_dir() for path in paths):
            self._add_found(_look_inside(paths, recursive))
            return
        # A big or network folder takes a while to walk, so a helper thread does it
        self.scans_waiting += 1
        self.status_text.configure(text=LOOKING)
        previous = self._scan_thread

        def work() -> None:
            try:
                found = _look_inside(paths, recursive)
            except Exception:  # pylint: disable=broad-exception-caught
                # The window must still hear back, or it would wait forever
                LOG.exception("Could not look for songs")
                found = [(path, False, None) for path in paths]
            # Songs are listed in the order they were added, however long each took
            if previous is not None:
                previous.join()
            self.events.put(("songs-found", found))

        self._scan_thread = threading.Thread(
            target=work, name="find-songs", daemon=True
        )
        self._scan_thread.start()

    def _songs_found(self, event: tuple) -> None:
        """A helper thread finished looking inside the added folders."""
        self.scans_waiting -= 1
        if self.busy:
            self.toast("Please wait until the songs are created", "error")
            return
        self._add_found(event[1])

    def _add_found(self, looked: list[Looked]) -> None:
        """Put the songs found on the list and explain anything that was left out."""
        added = []
        skipped = 0
        for path, folder_added, found in looked:
            if found is None:
                self.toast(f"{path.name} can't be opened", "error")
                continue
            if not found:
                if folder_added:
                    self.toast(f"No songs found in {path.name}", "error")
                else:
                    skipped += 1
            for song, folder in found:
                track = self.library.add(song, folder)
                if track is not None:
                    added.append(track)
        if added:
            self.toast(f"Added {len(added)} song{'s' if len(added) != 1 else ''}", "ok")
            self._read(added)
        elif skipped:
            self.toast("Those files aren't music (or were made by Audio8D)", "error")
        if (
            not added
            and not self.scans_waiting
            and self.status_text.cget("text") == LOOKING
        ):
            self.status_text.configure(text="Ready.")
        self.refresh_lists()
        self.sync_controls()

    def _read(self, tracks: list) -> None:
        """Read the new songs' details (tags, length) on helper threads."""
        generation = self.read_generation
        self.status_text.configure(text=f"Reading {len(tracks)} songs…")

        def one(toolchain: FFmpegToolchain, track: Track) -> None:
            if self.read_generation != generation:
                return
            song = track.song
            try:
                stat = song.stat()
                key = (str(song), stat.st_size, stat.st_mtime_ns)
                info = self._probe_cache.get(key)
                if info is None:
                    info = probe_audio(toolchain, song)
                    self._probe_cache[key] = info
            except (Audio8DError, OSError) as exc:
                LOG.info("Could not read %s: %s", song, exc)
                self.events.put(("unreadable", generation, song, read_problem(exc)))
                return
            except Exception:  # pylint: disable=broad-exception-caught
                # One strange file must not stop the others from being read
                LOG.exception("Could not read %s", song)
                self.events.put(("unreadable", generation, song, "unexpected error"))
                return
            self.events.put(("probed", generation, song, info))

        def work() -> None:
            try:
                toolchain = FFmpegToolchain.discover()
            except Audio8DError as exc:
                self.events.put(("tools-missing", str(exc)))
                return
            with ThreadPoolExecutor(READERS, thread_name_prefix="read") as pool:
                list(pool.map(lambda track: one(toolchain, track), tracks))
            self.events.put(("read-done", generation))

        threading.Thread(target=work, name="read-songs", daemon=True).start()

    def _song_read(self, event: tuple) -> None:
        """One song's details were read (or it couldn't be read)."""
        kind, generation, song, payload = event
        track = self.library.get(song)
        if generation != self.read_generation or track is None:
            return
        if kind == "probed":
            track.info, track.state = payload, READY
        else:
            track.state, track.problem = UNREADABLE, payload
        # Only the song's own rows now; counts and summaries once per tick
        self.live("songs").update_track(track)
        self.live("styles_step").update_track(track)
        self._dirty = True
        self._read_progress = True

    def _reading_done(self, event: tuple) -> None:
        """Every song of one batch has been read."""
        if event[1] == self.read_generation and not self.busy:
            self.status_text.configure(text="Ready.")
            self.overall.set(0)
        self._dirty = True

    def stop_reading(self) -> None:
        """Stop reading song details; songs not read yet stay on the list."""
        self.read_generation += 1
        waiting = [t for t in self.library.tracks if t.state not in (READY, UNREADABLE)]
        for track in waiting:
            # Converting reads the file anyway; only the suggestion knows less
            track.state = READY
            self.live("songs").update_track(track)  # type: ignore[attr-defined]
        self._dirty = True
        self._read_progress = True
        if waiting:
            self.status_text.configure(text="Stopped reading song details.")
            self.overall.set(0)
            self.toast(
                f"Stopped: {len(waiting)} songs were not read (they can still be "
                "converted)"
            )

    def remove_songs(self, songs: Sequence[Path]) -> None:
        """Take songs off the list (never while converting)."""
        if self.busy:
            self.toast("Please wait until the songs are created", "error")
            return
        for song in songs:
            self.settings.song_styles.pop(song, None)
            self.settings.song_files.pop(song, None)
            self.settings.song_sound.pop(song, None)
            self.previews.forget(song)
            self.trials.pop(song, None)
            if self.player_song == song:
                self.stop_playing()
        removed = self.library.remove(songs)
        self.refresh_lists()
        self.sync_controls()
        if removed:
            self.toast(f"Removed {self._songs_word(len(removed))}", "ok")

    def ask_clear_songs(self) -> None:
        """'Clear list': empty it, asking first when songs have their own settings."""
        if self.busy or not self.library.tracks:
            return
        count = len(self.library.tracks)
        own = sum(1 for t in self.library.tracks if is_custom(self.settings, t.song))
        if own and not Dialog.confirm(
            self,
            "Clear the list?",
            f"{self._songs_word(own)} on the list"
            + (" have their own" if own != 1 else " has its own")
            + " style or settings, which will be forgotten. Your files are not "
            "touched.",
            "Clear list",
            icon="delete",
        ):
            return
        # A conversion may have started while the question was open
        if self.busy:
            return
        self.clear_songs()
        self.toast(f"Cleared {self._songs_word(count)}", "ok")

    def clear_songs(self) -> None:
        """Empty the list."""
        if self.busy:
            return
        self.read_generation += 1
        self.previews.cancel()
        for track in self.library.tracks:
            self.previews.forget(track.song)
        self.player.close()
        self.player_song = None
        self.library.clear()
        self.settings.song_styles.clear()
        self.settings.song_files.clear()
        self.settings.song_sound.clear()
        self.trials.clear()
        self.refresh_lists()
        self.sync_controls()

    def choose_style(self, name: str) -> None:
        """A new default style for every song that isn't customized."""
        if name not in self.presets:
            return
        self.settings.apply_style(self.presets[name])
        self.settings.speakers = False
        folded = change_default(self.settings.song_styles, name)
        extra = (
            f"; {folded} song{'s' if folded != 1 else ''} that had it now simply "
            "follow the default"
            if folded
            else ""
        )
        self.settings_changed(f"Default style: {self.label(name)}{extra}")

    def apply_suggestions(self, songs: Sequence[Path] | None = None) -> None:
        """Songs (or all) get their suggested style, where the suggestion is sure."""
        tracks = (
            [t for t in (self.library.get(s) for s in songs) if t is not None]
            if songs is not None
            else None
        )
        changed, unsure = self.library.apply_suggestions(
            self.settings.song_styles, self.settings.style, tracks
        )
        text = f"Suggested styles used: {self._songs_word(changed)} changed"
        if unsure:
            text += f"; {unsure} without genre information kept their style"
        self.settings_changed(text)

    def batch_suggestion(self) -> BatchSuggestion | None:
        """The best default style for the list (None with no readable songs)."""
        if not any(t.state == READY for t in self.library.tracks):
            return None
        return self.library.batch_suggestion()

    def reload_styles(
        self, select: str | None = None, renamed: tuple[str, str] | None = None
    ) -> int:
        """Saved styles changed: rebuild the lists and menus.

        renamed is (old name, new name) after a rename, so songs keep their style.
        Returns how many songs went back to the default because their style is gone.
        """
        self.presets = self._load_styles()
        self.library.use_styles(self.presets)
        own = self.settings.song_styles
        if renamed:
            old, new = renamed
            for song, name in own.items():
                if name == old:
                    own[song] = new
            if self.settings.style == old:
                self.settings.style = new
        gone = forget_missing_styles(own, self.presets)
        self.live("styles").refresh()
        if select:
            self.settings.style = select
        elif self.settings.style not in self.presets:
            self.settings.apply_style(self.presets[RECOMMENDED_PRESET])
        self.refresh_lists()
        self.sync_controls()
        return len(gone)


def _look_inside(paths: Sequence[Path], recursive: bool) -> list[Looked]:
    """(path, is it a folder, its songs as (song, folder)) per path; None: can't open.

    Folders hold every song inside them, a song holds itself, and anything else
    holds nothing.
    """
    looked: list[Looked] = []
    for path in paths:
        folder = False
        try:
            folder = path.is_dir()
            if folder:
                found: list[tuple[Path, Path | None]] = [
                    (song, path) for song in find_songs(path, recursive=recursive)
                ]
            elif path.suffix.lower() in AUDIO_EXTENSIONS and not is_own_output(path):
                found = [(path, None)]
            else:
                found = []
        except (OSError, Audio8DError) as exc:
            LOG.warning("Could not look inside %s: %s", path, exc)
            looked.append((path, folder, None))
            continue
        looked.append((path, folder, found))
    return looked
