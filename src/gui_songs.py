# Developed by ::> Gehan Fernando
"""Step 1 of the window: add songs and see what was found in each file."""

import tkinter as tk
from pathlib import Path
from typing import TYPE_CHECKING

import customtkinter as ctk

from .gui_fields import (
    SwitchField,
)
from .gui_table import Column, SongTable
from .gui_widgets import (
    ACCENT,
    ACCENT_TEXT,
    BORDER,
    SURFACE,
    TEXT_DIM,
    Card,
    Icons,
    Page,
    button,
    entry,
    font,
    hint,
)
from .library import READY, UNREADABLE, Track

if TYPE_CHECKING:
    from .gui_app import Audio8DApp


class SongsPage(Page):
    """Step 1: drop or pick songs, and see what was found in each file."""

    COLUMNS = (
        Column("name", "Song", 260, stretch=True),
        Column("artist", "Artist", 150),
        Column("album", "Album", 150),
        Column("genre", "Genre", 140),
        Column("length", "Length", 70, "e"),
        Column("type", "Type", 64, "center"),
        Column("status", "Status", 240),
    )

    def __init__(self, master: tk.Misc, app: "Audio8DApp") -> None:
        """Build the page."""
        super().__init__(
            master,
            "Step 1 of 4",
            "Add music",
            "Add the songs you want in 8D. Nothing is made until you press Create "
            "on the last step.",
        )
        self.app = app
        drop = ctk.CTkFrame(
            self,
            fg_color=SURFACE,
            corner_radius=12,
            border_width=2,
            border_color=BORDER,
        )
        self.add(drop, 2)
        drop.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            drop, text=Icons.glyph("drop"), font=Icons.font(30), text_color=ACCENT_TEXT
        ).grid(row=0, column=0, rowspan=3, padx=(24, 16), pady=20)
        ctk.CTkLabel(
            drop, text="Drop songs or folders here", font=font(16, "bold"), anchor="w"
        ).grid(row=0, column=1, sticky="sw", pady=(18, 0))
        hint(
            drop,
            "MP3, FLAC, WAV, M4A, OGG, Opus, WMA, AIFF and the sound of videos. "
            "FLAC or WAV give the best result.",
            margin=470,
        ).grid(row=1, column=1, sticky="new")
        self.recursive = SwitchField(
            drop,
            "Include songs in sub-folders",
            "",
            app.set_recursive,
        )
        self.recursive.help.grid_remove()
        self.recursive.grid(row=2, column=1, sticky="w", pady=(2, 14))
        buttons = ctk.CTkFrame(drop, fg_color="transparent")
        buttons.grid(row=0, column=2, rowspan=3, padx=20)
        button(
            buttons,
            "add",
            "Add songs",
            app.ask_files,
            kind="primary",
            tooltip="Choose one or more song files (Ctrl+O)",
        ).pack(side="left", padx=4)
        button(
            buttons,
            "folder",
            "Add folder",
            app.ask_folder,
            tooltip="Add every song in a folder (Ctrl+Shift+O)",
        ).pack(side="left", padx=4)

        songs = Card(self, "Your songs")
        self.add(songs, 3)
        body = songs.body
        top = ctk.CTkFrame(body, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        top.grid_columnconfigure(0, weight=1)
        self.summary = ctk.CTkLabel(top, text="", font=font(13), anchor="w")
        self.summary.grid(row=0, column=0, sticky="w")
        self.search = entry(top, "Search songs, artists, albums…", 260)
        self.search.grid(row=0, column=1, padx=(8, 0))
        self.search.bind("<KeyRelease>", lambda _e: self.refresh())
        self.remove = button(
            top,
            "remove",
            "Remove selected",
            self._remove_selected,
            width=170,
            tooltip="Take the selected songs off the list (Delete). Files are "
            "not touched.",
        )
        self.remove.grid(row=0, column=2, padx=(8, 0))
        button(
            top,
            "clear",
            "Clear list",
            app.clear_songs,
            width=120,
            tooltip="Take every song off the list. Files are not touched.",
        ).grid(row=0, column=3, padx=(8, 0))
        self.reading = ctk.CTkFrame(body, fg_color="transparent")
        self.reading.grid_columnconfigure(1, weight=1)
        self.reading_bar = ctk.CTkProgressBar(
            self.reading, height=8, progress_color=ACCENT
        )
        self.reading_bar.grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.reading_text = ctk.CTkLabel(
            self.reading, text="", font=font(12), text_color=TEXT_DIM, anchor="w"
        )
        self.reading_text.grid(row=0, column=1, sticky="w")
        button(
            self.reading,
            "stop",
            "Stop reading",
            app.stop_reading,
            width=140,
            height=28,
            tooltip="Stop reading song details (Esc). Songs not read yet can still "
            "be converted; they just get the balanced default suggestion.",
        ).grid(row=0, column=2, padx=(8, 0))
        self.table = SongTable(
            body,
            self.COLUMNS,
            height=14,
            on_select=self._selection_changed,
            label="Songs on the list",
        )
        self.table.grid(row=2, column=0, sticky="nsew")
        self.table.tree.bind("<Delete>", lambda _e: self._remove_selected())
        self.empty = hint(
            body,
            "No songs yet. Drag songs or folders onto this window, or press Add "
            "songs. Audio8D reads each file's tags (artist, album, genre) to suggest "
            "a style on the next step.",
        )
        self.empty.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.footer(4, None, "Next: choose sound", lambda: app.show_page("styles_step"))
        self.recursive.set(app.settings.recursive)
        self._selection_changed()

    def _selection_changed(self) -> None:
        """Remove is only possible with something selected."""
        count = len(self.table.selected())
        self.remove.configure(state="normal" if count else "disabled")

    def _remove_selected(self) -> None:
        """Take the selected songs off the list."""
        chosen = [Path(iid) for iid in self.table.selected()]
        if chosen:
            self.app.remove_songs(chosen)

    @staticmethod
    def values(track: Track) -> list[str]:
        """What one song's row shows."""
        status = {
            READY: "Ready",
            UNREADABLE: f"Can't be read: {track.problem or 'not music'}",
        }.get(track.state, "Reading…")
        return [
            track.name,
            track.artist,
            track.album,
            track.genre,
            track.length_text,
            track.kind,
            status,
        ]

    @staticmethod
    def tags(track: Track) -> list[str]:
        """How one song's row looks."""
        if track.state == UNREADABLE:
            return ["problem"]
        return ["muted"] if track.state != READY else []

    def refresh(self) -> None:
        """Rebuild the table and the counts."""
        library = self.app.library
        words = self.search.get().casefold().split()
        rows = [
            (str(track.song), self.values(track), self.tags(track))
            for track in library.tracks
            if all(
                word
                in f"{track.name} {track.artist} {track.album} {track.genre}".casefold()
                for word in words
            )
        ]
        self.table.show([("", rows)])
        self.show_counts()
        if library.tracks:
            self.empty.grid_remove()
        else:
            self.empty.grid()
        self._selection_changed()

    def update_track(self, track: Track) -> None:
        """One song's details arrived."""
        self.table.update_row(str(track.song), self.values(track), self.tags(track))

    def show_counts(self) -> None:
        """The summary line and the reading progress."""
        tracks = self.app.library.tracks
        total = len(tracks)
        reading = sum(1 for t in tracks if t.state not in (READY, UNREADABLE))
        bad = sum(1 for t in tracks if t.state == UNREADABLE)
        if not total:
            text = "The list is empty."
        else:
            text = f"{total} song{'s' if total != 1 else ''} on the list"
            if bad:
                text += f"  ·  {bad} can't be read and will be skipped"
        self.summary.configure(text=text)
        if reading:
            done = total - reading
            self.reading_bar.set(done / total)
            self.reading_text.configure(text=f"Reading song details… {done} of {total}")
            self.reading.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        else:
            self.reading.grid_remove()
