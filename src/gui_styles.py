# Developed by ::> Gehan Fernando
"""Step 2 of the window: choose how the songs sound, and review each song.

The page shows only the style every song uses by default, with Change style
(the style chooser dialog) and Customize default sound. Below it, a simple
song list answers what people ask: which song, what it will sound like,
whether it follows the defaults or is custom, and Preview or Customize it.
Customizing happens in its own dialog, so the page never grows into a form.
"""

import tkinter as tk
from pathlib import Path
from typing import TYPE_CHECKING

import customtkinter as ctk

from .core.style_guide import guide_for
from .gui_model import (
    GuiSettings,
    is_custom,
)
from .gui_table import Column, SongTable
from .gui_widgets import (
    INK,
    SEARCH_WIDTH,
    TOOL_HEIGHT,
    TOOL_WIDTH,
    Card,
    Notice,
    Page,
    Section,
    button,
    clear_children,
    entry,
    flow,
    font,
    hint,
    icon_text,
)
from .library import READY, UNREADABLE, Track, ViewOptions

if TYPE_CHECKING:
    from .gui_app import Audio8DApp

# The Actions column holds two words; a click on the left half previews
PREVIEW_HALF = 0.5


# A page keeps a reference to every control it updates when the settings change
class StylesStep(Page):  # pylint: disable=too-many-instance-attributes
    """Step 2: the default style, then the songs with Preview and Customize."""

    COLUMNS = (
        Column("name", "Song", 260, stretch=True),
        Column("sound", "Sound", 150),
        Column("settings", "Settings", 100),
        Column("actions", "Actions", 250),
    )

    def __init__(self, master: tk.Misc, app: "Audio8DApp") -> None:
        """Build the page."""
        super().__init__(
            master,
            "Step 2 of 4",
            "Choose how it sounds",
            "Every song uses the default settings unless you customize it. Preview "
            "any song before creating: nothing is saved while you listen.",
        )
        self.app = app
        self.view = ViewOptions()
        # True when songs changed while the page was hidden; it catches up when shown
        self.stale = False
        # The suggestion last shown, so the card is only rebuilt when it changes
        self._suggested: tuple[str, str] | None = None
        self._build_default()
        self._build_songs()
        self.footer(
            4,
            lambda: app.show_page("songs"),
            "Next: output",
            lambda: app.show_page("output"),
        )

    # ------------------------------------------------------------ the default

    def _build_default(self) -> None:
        """'Sound style: Studio, what it sounds like, [Change style]'."""
        card = Card(self, "Sound style")
        self.add(card, 2)
        body = card.body
        body.grid_columnconfigure(0, weight=1)
        self.default_name = ctk.CTkLabel(
            body, text="", font=font(20, "bold"), anchor="w"
        )
        self.default_name.grid(row=0, column=0, sticky="w")
        self.default_purpose = hint(body, "", INK, margin=330, size=13)
        self.default_purpose.grid(row=1, column=0, sticky="ew")
        self.default_changed = hint(body, "", margin=330)
        self.default_changed.grid(row=2, column=0, sticky="ew")
        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=0, column=1, rowspan=3, sticky="ne", padx=(12, 0))
        self.change = button(
            actions,
            "sound",
            "Change style…",
            self.app.open_style_chooser,
            kind="primary",
            width=180,
            tooltip="Choose how every song sounds, unless you customized it",
        )
        self.change.pack(anchor="e")
        button(
            actions,
            "settings",
            "Customize default…",
            lambda: self.app.open_customize([]),
            kind="quiet",
            width=180,
            height=TOOL_HEIGHT,
            tooltip="Movement, speed, space and more, for every song that isn't "
            "customized",
        ).pack(anchor="e", pady=(6, 0))
        self.suggestion_area = ctk.CTkFrame(body, fg_color="transparent", height=1)
        self.suggestion_area.grid(row=3, column=0, columnspan=2, sticky="ew")
        self.suggestion_area.grid_columnconfigure(0, weight=1)

    def show_default(self) -> None:
        """Bring the default style card up to date."""
        app = self.app
        settings = app.settings
        preset = app.presets.get(settings.style)
        if preset is None:
            return
        self.default_name.configure(text=preset.label)
        self.default_purpose.configure(text=guide_for(preset).purpose)
        self.default_changed.configure(
            text="Customized by you (Customize default… to change or undo it)."
            if settings.differs_from(preset)
            else ""
        )
        self._show_suggestion()

    def _show_suggestion(self) -> None:
        """A one-click suggestion, only when Audio8D is fairly sure of it."""
        app = self.app
        batch = app.batch_suggestion()
        key = (batch.style, app.settings.style) if batch else None
        if self._suggested == key and key is not None:
            return
        self._suggested = key
        clear_children(self.suggestion_area)
        if batch is None or batch.known == 0 or batch.style == app.settings.style:
            return
        label = app.label(batch.style)
        Notice(
            self.suggestion_area,
            "info",
            f"Suggested for these songs: {label}. {batch.reason}",
            (f"Use {label}", lambda: app.choose_style(batch.style)),
        ).grid(row=0, column=0, sticky="ew", pady=(12, 0))

    # ------------------------------------------------------------ the songs

    def _build_songs(self) -> None:
        """The song list with Preview, Customize and Reset to default."""
        card = Card(self, "Your songs")
        self.add(card, 3)
        body = card.body
        tools = ctk.CTkFrame(body, fg_color="transparent")
        tools.grid(row=0, column=0, sticky="ew")
        tools.grid_columnconfigure(1, weight=1)
        self.selection_text = ctk.CTkLabel(
            tools, text="", font=font(12, "bold"), anchor="w", width=150
        )
        self.selection_text.grid(row=0, column=0, sticky="w")
        self.search = entry(tools, "Search songs, artists, albums…", SEARCH_WIDTH)
        self.search.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.search.bind("<KeyRelease>", lambda _e: self._search())
        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="w", pady=(10, 8))
        self.preview = button(
            actions,
            "headphones",
            "Preview",
            self._preview,
            kind="primary",
            width=TOOL_WIDTH,
            height=TOOL_HEIGHT,
            tooltip="Listen to a short part of the selected song (Ctrl+P); nothing "
            "is saved",
        )
        self.compare = button(
            actions,
            "compare",
            "Compare A/B",
            self._compare,
            width=TOOL_WIDTH,
            height=TOOL_HEIGHT,
            tooltip="Hear the same part of the selected song twice: the original, "
            "then in 8D; nothing is saved",
        )
        self.customize = button(
            actions,
            "settings",
            "Customize…",
            self._customize,
            width=TOOL_WIDTH,
            height=TOOL_HEIGHT,
            tooltip="Change the sound of the selected song(s) only (Enter)",
        )
        self.reset = button(
            actions,
            "clear",
            "Reset to default",
            self._reset,
            width=TOOL_WIDTH,
            height=TOOL_HEIGHT,
            tooltip="The selected songs lose their own settings and follow the "
            "defaults again",
        )
        self.suggested = button(
            actions,
            "wand",
            "Use suggested styles",
            self._use_suggested,
            kind="quiet",
            width=TOOL_WIDTH,
            height=TOOL_HEIGHT,
            tooltip="Give songs the style that suits their genre (where Audio8D is "
            "sure)",
        )
        # The buttons wrap onto a second line in a narrow window
        flow(
            actions,
            (self.preview, self.compare, self.customize, self.reset, self.suggested),
        )
        body.grid_columnconfigure(0, weight=1)
        self.table = SongTable(
            body,
            self.COLUMNS,
            height=14,
            on_select=self.show_selection,
            on_sort=self._sort_by,
            on_activate=lambda iid: self.app.open_customize([Path(iid)]),
            label="Your songs",
        )
        self.table.grid(row=2, column=0, sticky="nsew")
        self.table.tree.bind("<ButtonRelease-1>", self._clicked, add=True)
        self.table.tree.bind("<space>", lambda _e: (self._preview(), "break")[1])
        self.counts = hint(body, "", margin=40)
        self.counts.grid(row=3, column=0, sticky="ew", pady=(8, 0))

    def _search(self) -> None:
        """Show only the songs that match the search words."""
        self.view.query = self.search.get()
        self.refresh()

    def _sort_by(self, column: str) -> None:
        """A column heading was clicked: sort by it (again: reverse)."""
        key = {"name": "name", "sound": "style"}.get(column)
        if key is None:
            return
        if self.view.sort == key:
            self.view.descending = not self.view.descending
        else:
            self.view.sort, self.view.descending = key, False
        self.refresh()

    def _clicked(self, event: tk.Event) -> None:
        """A click on a row's 'Preview · Customize' does what it says."""
        tree = self.table.tree
        if tree.identify_region(event.x, event.y) != "cell":
            return
        column = tree.identify_column(event.x)
        iid = tree.identify_row(event.y)
        if column != f"#{len(self.COLUMNS)}" or not iid or iid.startswith("group:"):
            return
        box = tree.bbox(iid, column)
        if not box:
            return
        left, _top, width, _height = box
        song = Path(iid)
        if event.x - left < width * PREVIEW_HALF:
            self.app.preview_song(song)
        else:
            self.app.open_customize([song])

    def selected_songs(self) -> list[Path]:
        """The songs selected in the table."""
        return [Path(iid) for iid in self.table.selected()]

    def focused_song(self) -> Path | None:
        """The song the keyboard or last click is on (for Preview)."""
        focus = self.table.focused()
        return Path(focus) if focus else None

    def _preview(self) -> None:
        """Preview (or stop) the selected song."""
        song = self.focused_song()
        if song is None:
            self.app.toast("Select a song to preview")
            return
        self.app.preview_song(song)

    def _compare(self) -> None:
        """Play (or stop) the original and the 8D sound of the selected song."""
        song = self.focused_song()
        if song is None:
            self.app.toast("Select a song to compare")
            return
        self.app.preview_song(song, "compare")

    def _customize(self) -> None:
        """Customize the selected songs."""
        songs = self.selected_songs()
        if songs:
            self.app.open_customize(songs)

    def _reset(self) -> None:
        """The selected songs follow the defaults again."""
        self.app.reset_to_default(self.selected_songs())

    def _use_suggested(self) -> None:
        """Suggested styles for the selected songs, or for all when none is selected."""
        self.app.apply_suggestions(self.selected_songs() or None)

    def show_selection(self) -> None:
        """The toolbar follows the selection: what Preview, Customize, Reset will do."""
        chosen = self.selected_songs()
        total = len(self.app.library)
        count = len(chosen)
        self.selection_text.configure(
            text=f"{count} of {total} selected" if total else "No songs yet"
        )
        focus = self.focused_song()
        track = self.app.library.get(focus) if focus else None
        can_preview = track is not None and track.state != UNREADABLE
        words = self.app.preview_words(focus) if focus else "▶ Preview"
        self.preview.configure(
            text=f"  {words.split(' ', 1)[1]}",
            state="normal" if can_preview else "disabled",
        )
        words = self.app.preview_words(focus, "compare") if focus else "⇄ Compare A/B"
        self.compare.configure(
            text=f"  {words.split(' ', 1)[1]}",
            state="normal" if can_preview else "disabled",
        )
        self.customize.configure(
            **icon_text(
                "settings",
                "Customize…" if count <= 1 else f"Customize {count} songs…",
            ),
            state="normal" if count else "disabled",
        )
        custom = any(is_custom(self.app.settings, song) for song in chosen)
        self.reset.configure(state="normal" if custom else "disabled")
        self.suggested.configure(state="normal" if total else "disabled")

    # ------------------------------------------------------------ rows

    def values(self, track: Track) -> list[str]:
        """What one song's row shows: name, sound, Default/Custom, actions."""
        app = self.app
        if track.state == UNREADABLE:
            return [track.name, "—", "—", "Can't be read: skipped"]
        style = app.settings.song_styles.get(track.song, app.settings.style)
        custom = is_custom(app.settings, track.song)
        preview = app.preview_words(track.song)
        return [
            track.name,
            app.label(style),
            "Custom" if custom else "Default",
            f"{preview}     ✎ Customize",
        ]

    def tags(self, track: Track) -> list[str]:
        """How one song's row looks (custom in bold; problems in red)."""
        if track.state == UNREADABLE:
            return ["problem"]
        tags = []
        if is_custom(self.app.settings, track.song):
            tags.append("own")
        if track.state != READY:
            tags.append("muted")
        return tags

    def refresh(self) -> None:
        """Rebuild the table and counts (later, if the page is hidden)."""
        app = self.app
        # Filling a big table nobody can see stalled the window; do it when shown
        if app.current != "styles_step":
            self.stale = True
            return
        self.stale = False
        groups = app.library.view(
            self.view, app.settings.song_styles, app.settings.style, app.label
        )
        self.table.show(
            [
                (
                    group.title,
                    [(str(t.song), self.values(t), self.tags(t)) for t in group.tracks],
                )
                for group in groups
            ]
        )
        shown = sum(len(group.tracks) for group in groups)
        total = len(app.library)
        custom = sum(1 for t in app.library.tracks if is_custom(app.settings, t.song))
        if not total:
            text = "Add songs on step 1 to see them here."
        else:
            text = (
                f"{total - custom} song{'s' if total - custom != 1 else ''} use the "
                f"default settings; {custom} {'is' if custom == 1 else 'are'} "
                "custom. Double-click a song (or press Enter) to customize it; "
                "Space previews it."
            )
            if shown != total:
                text += f" Showing {shown} of {total}."
        self.counts.configure(text=text)
        self.show_selection()

    def catch_up(self) -> None:
        """The page is being shown: rebuild it if songs changed meanwhile."""
        if self.stale:
            self.refresh()

    def update_track(self, track: Track) -> None:
        """One song changed (details read, preview state): refresh its row."""
        self.table.update_row(str(track.song), self.values(track), self.tags(track))

    def warm_sections(self) -> list[Section]:
        """Nothing on this page is folded any more."""
        return []

    def show(self, _settings: GuiSettings) -> None:
        """Make the page match the settings."""
        self.show_default()
        self.show_selection()
