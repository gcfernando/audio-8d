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
from .library import (
    READY,
    UNREADABLE,
    Track,
    change_default,
    forget_missing_styles,
)
from .recommend import BatchSuggestion


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
            self.toast("Please wait until the conversion finishes", "error")
            return
        added = []
        skipped = 0
        for path in paths:
            try:
                if path.is_dir():
                    found = [
                        (song, path)
                        for song in find_songs(path, recursive=self.settings.recursive)
                    ]
                    if not found:
                        self.toast(f"No songs found in {path.name}", "error")
                elif path.suffix.lower() in AUDIO_EXTENSIONS and not is_own_output(
                    path
                ):
                    found = [(path, None)]
                else:
                    found, skipped = [], skipped + 1
            except OSError as exc:
                LOG.warning("Could not look inside %s: %s", path, exc)
                self.toast(f"{path.name} can't be opened", "error")
                continue
            for song, folder in found:
                track = self.library.add(song, folder)
                if track is not None:
                    added.append(track)
        if added:
            self.toast(f"Added {len(added)} song{'s' if len(added) != 1 else ''}", "ok")
            self._read(added)
        elif skipped:
            self.toast("Those files aren't music (or were made by Audio8D)", "error")
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
            self.toast("Please wait until the conversion finishes", "error")
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
            self.toast(f"Removed {len(removed)} song{'s' if len(removed) != 1 else ''}")

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
