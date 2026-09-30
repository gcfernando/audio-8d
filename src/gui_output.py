# Developed by ::> Gehan Fernando
"""Step 3 of the window: where the new songs go and how they are saved.

Where the files go is chosen once for every song. How they are saved (format,
quality, loudness and More options) is edited for All songs or for One song,
picked with two buttons at the top of that card; both parts follow that one
choice. A song's own choices are kept apart from the defaults (gui_model's
per-song file settings, shared with Customize and the command line's
--per-song file).
"""

import dataclasses
import math
import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from typing import TYPE_CHECKING

import customtkinter as ctk

from .batch import MAX_JOBS
from .core.errors import Audio8DError
from .core.parsing import typed_loudness, typed_time_problem
from .gui_fields import (
    ChoiceField,
    EntryField,
    MenuField,
    SliderField,
    SwitchField,
    browse_button,
    trim_fields,
)
from .gui_model import (
    BITRATE_CHOICES,
    FORMAT_CHOICES,
    LOUDNESS_MAIN,
    LOUDNESS_MORE,
    QUALITY_CHOICES,
    GuiSettings,
    file_value,
    gui_words,
    has_own_files,
    quality_choices,
)
from .gui_summary import FORMAT_WORDS, loudness_words
from .gui_widgets import (
    DANGER,
    INK,
    SUCCESS,
    TEXT_DIM,
    TOOL_HEIGHT,
    TOOL_WIDTH,
    WARNING,
    Badge,
    Card,
    Page,
    Section,
    button,
    entry,
    font,
    hint,
)
from .library import UNREADABLE

if TYPE_CHECKING:
    from .gui_app import Audio8DApp

# How long typing in the folder box must pause before the folder is checked
FOLDER_PAUSE_MS = 300

# The two scopes of 'How the songs are saved' and 'More output options'
SCOPES = {"All songs": "all", "One song": "one"}


# What More output options holds; the scope is said before it
MORE_WORDS = (
    "Bitrate, loudness precision, peak limit, album picture, title and using only part "
    "of the song. The recommended values suit almost everyone."
)


def peak_words(ceiling: float) -> str:
    """A peak limit in decibels below the maximum, e.g. 0.84 -> '-1.5 dB'."""
    return f"{20 * math.log10(max(ceiling, 1e-6)):.1f} dB"


# The lowest peak limit FFmpeg's limiter takes, as on the command line (-24 dB)
LOWEST_CEILING = 0.0625


def ceiling_for(decibels: float) -> float:
    """The peak limit saved for a slider position in dB, e.g. -1.5 -> 0.84."""
    # Two decimals keep the recommended limits exactly 0.84 and 0.89
    return max(LOWEST_CEILING, round(10 ** (decibels / 20), 2))


class MoreFileControls:  # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """'More output options', made the first time that part opens."""

    def __init__(self, body: ctk.CTkFrame, owner: "OutputPage") -> None:
        """Make the controls inside the part's body."""
        self.bitrate = ChoiceField(
            body,
            "Bitrate (kbps)",
            "",
            {name: (None if name == "Auto" else int(name)) for name in BITRATE_CHOICES},
            lambda v: owner.set_values(bitrate=v),
        )
        self.quality = SliderField(
            body,
            "MP3 variable quality",
            "Used when the bitrate is Auto. 0 is best (about 245 kbps); 9 is "
            "the smallest.",
            (0, 9, 9),
            lambda v: f"V{v:.0f}",
            lambda v: owner.set_values(quality=int(round(v))),
        )
        self.exact = SwitchField(
            body,
            "Get as close to the loudness as possible",
            "",
            lambda on: owner.set_values(exact_loudness=on),
            more="Off keeps every peak, so a very dynamic song may stay a little "
            "below the chosen loudness. On shaves the loudest peaks to get as close "
            "to it as possible; very loud or punchy songs can still land a little "
            "under it.",
        )
        self.ceiling = SliderField(
            body,
            "Peak limit",
            "Keeps the loudest moments from crackling. Recommended: -1.5 dB (MP3, "
            "M4A, Opus), -1.0 dB (FLAC, WAV).",
            # Half-decibel steps from -24 dB, the lowest the command line allows
            (-24.0, 0.0, 48),
            lambda v: peak_words(ceiling_for(v)),
            lambda v: owner.set_values(limiter_ceiling=ceiling_for(v)),
        )
        self.cover = SwitchField(
            body,
            "Keep the album picture",
            "Copies the cover art into the new file.",
            lambda on: owner.set_values(keep_cover=on),
        )
        self.title_tag = SwitchField(
            body,
            "Add ' (8D)' to the song title",
            "So your music app lists the 8D version as its own track.",
            lambda on: owner.set_values(tag_title=on),
        )
        self.start, self.end = trim_fields(
            body, lambda key, text: owner.typed_time(text, key)
        )
        widgets = (
            self.bitrate,
            self.quality,
            self.exact,
            self.ceiling,
            self.cover,
            self.title_tag,
            self.start,
            self.end,
        )
        for row, widget in enumerate(widgets):
            widget.grid(row=row, column=0, sticky="ew", pady=3)

    def show(self, settings: GuiSettings, owner: "OutputPage") -> None:
        """Bitrate, loudness precision, peak limit, album art, title and trimming."""
        value = owner.value
        kind = str(value("output_format"))
        lossless = kind in {"flac", "wav"}
        wants_level = (
            bool(value("match_loudness")) or value("loudness_target") is not None
        )
        wants_level = wants_level or (
            owner.song is None and settings.loudness_is_custom
        )
        # Only what applies to this file type and loudness is shown
        if lossless:
            self.bitrate.grid_remove()
        else:
            self.bitrate.grid()
            self.bitrate.set(value("bitrate"))
            self.bitrate.explain(
                "Quality above picks this for you. Higher keeps more detail and "
                "makes bigger files; Auto lets the file size follow the music."
            )
        if kind == "mp3" and value("bitrate") is None:
            self.quality.grid()
        else:
            self.quality.grid_remove()
        self.quality.set(float(value("quality")))  # type: ignore[arg-type]
        if wants_level:
            self.exact.grid()
        else:
            self.exact.grid_remove()
        self.exact.set(bool(value("exact_loudness")))
        self.exact.explain(
            "Off (recommended): a very dynamic song may end a little quieter "
            "instead of squeezing its loudest moments."
        )
        ceiling = float(value("limiter_ceiling"))  # type: ignore[arg-type]
        self.ceiling.set(20 * math.log10(max(LOWEST_CEILING, ceiling)))
        can_cover = kind in {"mp3", "flac", "m4a"}
        self.cover.set(bool(value("keep_cover")) and can_cover)
        self.cover.enable(can_cover)
        self.cover.explain(
            "Copies the cover art into the new file."
            if can_cover
            else f"{kind.upper()} files can't hold an album picture."
        )
        self.title_tag.set(bool(value("tag_title")))
        for field, key in ((self.start, "trim_start"), (self.end, "trim_end")):
            text_now = str(value(key))
            focused = str(owner.focus_get() or "").startswith(str(field.entry))
            if field.entry.get() != text_now and not focused:
                field.set(text_now)


class RunControls:  # pylint: disable=too-few-public-methods
    """'While creating', made the first time that part opens."""

    def __init__(self, body: ctk.CTkFrame, owner: "OutputPage") -> None:
        """Make the controls inside the part's body."""
        app = owner.app
        self.checking = SwitchField(
            body,
            "Check each finished song",
            "Measures loudness and peaks and shows the result. Recommended on.",
            lambda on: app.set_flag("check", on),
        )
        self.jobs = SliderField(
            body,
            "Songs at once",
            "More is faster on computers with many cores. A good value for this "
            "computer is already set.",
            (1, MAX_JOBS, MAX_JOBS - 1),
            lambda v: f"{v:.0f}",
            lambda v: app.set_flag("jobs", int(round(v))),
        )
        self.play = SwitchField(
            body,
            "Play the first song when finished",
            "Opens the first new song in your music player.",
            lambda on: app.set_flag("play_when_done", on),
        )
        for row, widget in enumerate((self.checking, self.jobs, self.play)):
            widget.grid(row=row, column=0, sticky="ew", pady=3)


# A page keeps a reference to every control it updates when the settings change
class OutputPage(Page):  # pylint: disable=too-many-instance-attributes
    """Step 3: where the new songs go and how they are saved (for every song)."""

    def __init__(self, master: tk.Misc, app: "Audio8DApp") -> None:
        """Build the page."""
        super().__init__(
            master,
            "Step 3 of 4",
            "Output",
            "Where the new songs are saved and what kind of file they are. The "
            "recommended choices are already selected; you can leave them.",
        )
        self.app = app
        self.wants_folder = False
        # The folder box's pending check, while someone is still typing
        self._folder_job: str | None = None
        # The song whose output is being edited; None edits the defaults for all
        self.song: Path | None = None
        # True while the other loudness levels are shown
        self.show_more_loudness = False
        # Folded parts, made the first time they open
        self.more: MoreFileControls | None = None
        self.run_controls: RunControls | None = None
        self._build_where()
        self._build_file()
        self.running = Section(
            self,
            "While creating",
            "Checking each finished song, how many are made at once, and playing "
            "the first one when done.",
            build=self._fill_running,
        )
        self.add(self.running, 5)
        self.footer(
            6,
            lambda: app.show_page("styles_step"),
            "Next: create",
            lambda: app.show_page("review"),
        )

    # ------------------------------------------------------------ where

    def _build_where(self) -> None:
        """Where the new songs go, their names, and what happens to the originals."""
        app = self.app
        where = Card(
            self,
            "Where the new files go (all songs)",
            "Chosen once for every song. Audio8D always makes new files; your "
            "originals stay unless you choose to replace them.",
        )
        self.add(where, 2)
        body = where.body
        self.save_in = ChoiceField(
            body,
            "Save them",
            "",
            {"Next to each original": "next", "In one folder I choose": "folder"},
            self._place,
        )
        self.folder_row = ctk.CTkFrame(body, fg_color="transparent")
        self.folder_row.grid_columnconfigure(0, weight=1)
        self.folder = entry(self.folder_row, "Choose a folder…", 300)
        self.folder.grid(row=0, column=0, sticky="ew", padx=(176, 10))
        self.folder.bind("<KeyRelease>", lambda _e: self._folder_typed())
        browse_button(self.folder_row, self._browse).grid(row=0, column=1)
        self.folder_note = hint(self.folder_row, "", margin=200)
        self.folder_note.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(176, 0))
        self.naming = ChoiceField(
            body,
            "File names",
            "",
            {
                "'Song (8D)'": "8d",
                "Same as the original": "original",
                "Custom…": "custom",
            },
            app.set_name_style,
        )
        self.custom_name = EntryField(
            body,
            "Custom name",
            "Only for a single song. The right ending (.mp3, .flac…) is added.",
            "e.g. My Song 8D version",
            app.set_custom_name,
            width=300,
        )
        self.overwrite = ChoiceField(
            body,
            "If the 8D file exists",
            "",
            {"Skip that song": False, "Replace it": True},
            app.set_overwrite,
        )
        self.originals = ChoiceField(
            body,
            "Original songs",
            "",
            {
                "Keep them": "keep",
                "Replace them": "replace",
                "Replace, keep '(8D)'": "replace-8d",
            },
            app.set_originals,
            more="'Replace them' saves the 8D song under the original's name and "
            "moves the original to the Recycle Bin, so you can restore it. Drives "
            "without a Recycle Bin (USB sticks) keep it as '<song> (original)'. "
            "'Replace, keep (8D)' moves the original away but names the new file "
            "'<song> (8D)'.",
        )
        for row, widget in enumerate(
            (
                self.save_in,
                self.folder_row,
                self.naming,
                self.custom_name,
                self.overwrite,
                self.originals,
            )
        ):
            widget.grid(row=row, column=0, sticky="ew", pady=3)

    # ------------------------------------------------------------ the file

    def _build_file(self) -> None:
        """Format, quality and loudness in plain words; the rest folded away."""
        # Laid out like 'Your songs' on step 2: no tinted panels, rows at the left
        self.file_card = Card(self, "How the songs are saved")
        self.add(self.file_card, 3)
        body = self.file_card.body
        self.scope_mode = ChoiceField(
            body,
            "Settings for",
            "",
            SCOPES,  # type: ignore[arg-type]
            self._mode_picked,
        )
        self.scope_mode.help.grid_remove()
        self.scope_mode.set("all")
        self.scope_mode.grid(row=0, column=0, sticky="ew", pady=3)
        self.scope_song = MenuField(body, "Song", "", {}, self._scope_picked, width=340)
        self.scope_song.help.grid_remove()
        self.scope_song.grid(row=1, column=0, sticky="ew", pady=3)
        line = ctk.CTkFrame(body, fg_color="transparent")
        line.grid(row=2, column=0, sticky="ew", pady=(10, 8))
        line.grid_columnconfigure(3, weight=1)
        self.scope_badge = Badge(line, "All songs", "neutral")
        self.scope_badge.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.scope = hint(line, "", INK, margin=640)
        self.scope.configure(font=font(12, "bold"))
        self.scope.grid(row=0, column=1, sticky="w")
        self.scope_reset = button(
            line,
            "clear",
            "Reset",
            self._reset_scope,
            width=TOOL_WIDTH,
            height=TOOL_HEIGHT,
        )
        self.scope_reset.grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.format = MenuField(
            body,
            "Output format",
            "",
            FORMAT_CHOICES,  # type: ignore[arg-type]
            lambda v: self.set_values(output_format=v),
        )
        self.quality = ChoiceField(
            body,
            "Quality",
            "",
            QUALITY_CHOICES,  # type: ignore[arg-type]
            lambda v: self.set_values(bitrate=v),
        )
        self.loudness = ChoiceField(
            body,
            "Loudness",
            "",
            LOUDNESS_MAIN,  # type: ignore[arg-type]
            self._loudness,
            more="Music apps play every song at about the same loudness (-14 LUFS, "
            "a measure of how loud music feels). 'Keep original loudness' leaves "
            "each song as loud as it was. Loudness is measured, never guessed, and "
            "peaks are protected.",
        )
        self.more_loudness = ChoiceField(
            body,
            "Other level",
            "Other ways to set the loudness.",
            LOUDNESS_MORE,  # type: ignore[arg-type]
            self._more_loudness,
        )
        self.custom_loud = EntryField(
            body,
            "Custom level",
            "In LUFS, from -30 (quiet) to -5 (very loud). -14 is the music-app level.",
            "-14",
            self._custom_loudness,
            width=100,
        )
        for row, widget in enumerate(
            (
                self.format,
                self.quality,
                self.loudness,
                self.more_loudness,
                self.custom_loud,
            ),
            start=3,  # below the scope choice, the song and the scope line
        ):
            widget.grid(row=row, column=0, sticky="ew", pady=3)
        # Inside the same card, so the choice above plainly covers it too
        self.advanced = Section(
            body,
            "More output options",
            MORE_WORDS,
            build=self._fill_advanced,
        )
        self.advanced.grid(row=8, column=0, sticky="ew", pady=(14, 0))

    def warm_sections(self) -> list[Section]:
        """The folded parts worth drawing once in the background."""
        return [self.advanced, self.running]

    def _fill_advanced(self, body: ctk.CTkFrame) -> None:
        """The advanced output options (made when opened)."""
        self.more = MoreFileControls(body, self)
        self.show(self.app.settings)

    def _fill_running(self, body: ctk.CTkFrame) -> None:
        """Checking, speed and playing when done (made when opened)."""
        self.run_controls = RunControls(body, self)
        self.show(self.app.settings)

    # ------------------------------------------------------------ changing

    def value(self, key: str) -> object:
        """One output setting as it applies now: the chosen song's, or the default."""
        return file_value(self.app.settings, self.song, key)

    def set_values(self, **values: object) -> None:
        """Store output settings for the chosen song, or as the defaults for all."""
        if self.song is None:
            self.app.set_default_output(**values)
        else:
            self.app.set_song_output(self.song, **values)

    def _songs(self) -> dict[str, Path]:
        """Every readable song by the name the Song list shows."""
        songs: dict[str, Path] = {}
        for track in self.app.library.tracks:
            if track.state == UNREADABLE:
                continue
            name = track.name
            # Two songs with one name (from two folders) stay apart in the list
            if name in songs:
                name = f"{name}  ({track.song.parent.name})"
            songs[name] = track.song
        return songs

    def _mode_picked(self, mode: object) -> None:
        """'All songs' edits the defaults; 'One song' starts at the chosen song."""
        if mode == "all":
            self._scope_picked(None)
            return
        songs = list(self._songs().values())
        focused = self.app.focus_song()
        self._scope_picked(focused if focused in songs else next(iter(songs), None))

    def _scope_picked(self, song: object) -> None:
        """Edit the defaults for all songs (None), or one song's own output."""
        self.song = song if isinstance(song, Path) else None
        self.show_more_loudness = False
        self.show(self.app.settings)

    def _reset_scope(self) -> None:
        """All songs: back to the recommended output. One song: follow the defaults."""
        if self.song is None:
            self.app.reset_output()
        else:
            self.app.reset_song_files([self.song])

    def typed_time(self, text: str, key: str) -> str | None:
        """A trim box changed: store it, and complain if it isn't a time."""
        problem = typed_time_problem(text)
        if problem:
            return problem
        if str(self.value(key)) != text:
            self.set_values(**{key: text})
        return None

    def _loudness(self, value: object) -> None:
        """Match music apps, keep the original loudness, or show the other levels."""
        if value == "advanced":
            self.show_more_loudness = True
            self.show(self.app.settings)
            return
        self.show_more_loudness = False
        if self.song is None:
            self.app.settings.loudness_is_custom = False
        if value == "match":
            self.set_values(match_loudness=True, loudness_target=None)
        else:
            self.set_values(match_loudness=False, loudness_target=value)

    def _more_loudness(self, value: object) -> None:
        """Apple Music, TV and radio, no change, or a level of your own."""
        self.show_more_loudness = True
        if value != "custom":
            if self.song is None:
                self.app.settings.loudness_is_custom = False
            self.set_values(match_loudness=False, loudness_target=value)
            return
        if self.song is None:
            settings = self.app.settings
            settings.loudness_is_custom = True
            settings.change(match_loudness=False)
            self.app.set_custom_loudness(self.custom_loud.entry.get() or "-14")
            self.app.sync_controls()
            return
        self._custom_loudness(self.custom_loud.entry.get() or "-14")

    def _custom_loudness(self, text: str) -> str | None:
        """The custom level box, for the defaults or the chosen song."""
        if self.song is None:
            return self.app.set_custom_loudness(text)
        try:
            level = typed_loudness(text)
        except Audio8DError as exc:
            return gui_words(str(exc)) + "."
        self.set_values(match_loudness=False, loudness_target=level)
        return None

    # ------------------------------------------------------------ showing

    def show(self, settings: GuiSettings) -> None:
        """Make every control match the settings, and show or hide what applies."""
        self._show_where(settings)
        self._show_scope(settings)
        self._show_file(settings)
        if self.more is not None:
            self.more.show(settings, self)
        if self.run_controls is not None:
            self.run_controls.checking.set(settings.check)
            self.run_controls.jobs.set(settings.jobs)
            self.run_controls.play.set(settings.play_when_done)

    def _show_scope(self, settings: GuiSettings) -> None:
        """The two scope buttons, the song, and one line saying whose output changes."""
        songs = self._songs()
        if self.song not in songs.values():
            self.song = None
        self.scope_mode.set("all" if self.song is None else "one")
        self.scope_mode.enable_option("one", bool(songs))
        if self.song is None:
            self.scope_song.grid_remove()
            self.scope_badge.show("All songs", "neutral")
            self.scope.configure(
                text="Changes here apply to every song without its own output settings."
                if songs
                else "Changes here apply to every song. Add songs to set one "
                "differently."
            )
            self.scope_reset.configure(text="  Reset to recommended", state="normal")
            scope_words = "For all songs. "
        else:
            self.scope_song.set_options(songs)  # type: ignore[arg-type]
            self.scope_song.set(self.song)
            self.scope_song.grid()
            own = has_own_files(settings, self.song)
            self.scope_badge.show(
                "Custom" if own else "Default", "accent" if own else "neutral"
            )
            self.scope.configure(
                text=f"Changes here apply to “{self.song.stem}” only."
                + (
                    " It has its own output settings."
                    if own
                    else " It follows All songs."
                )
            )
            self.scope_reset.configure(
                text="  Reset to default", state="normal" if own else "disabled"
            )
            scope_words = f"For “{self.song.stem}” only. "
        self.advanced.subtitle_label.configure(  # type: ignore[union-attr]
            text=scope_words + MORE_WORDS
        )

    def _show_file(self, settings: GuiSettings) -> None:
        """The format, quality and loudness choices."""
        value = self.value
        sound = settings.sound
        kind = str(value("output_format"))
        self.format.set(kind)
        self.format.explain(f"{kind.upper()}: {FORMAT_WORDS[kind]}.")
        lossless = kind in {"flac", "wav"}
        if lossless:
            self.quality.grid_remove()
        else:
            self.quality.grid()
            # High, Medium and Small mean different kbps for MP3, M4A and Opus
            tiers = quality_choices(kind)
            self.quality.options = tiers  # type: ignore[assignment]
            bitrate = value("bitrate")
            self.quality.set(bitrate)
            self.quality.explain(
                "High keeps the most detail; Small makes the smallest files ("
                + ", ".join(f"{name} {kbps}" for name, kbps in tiers.items())
                + " kbps)."
                if bitrate in tiers.values()
                else "Set under More output options: "
                + (f"{bitrate} kbps." if bitrate else "Auto (variable quality).")
            )
        match = bool(value("match_loudness"))
        target = value("loudness_target")
        # Only the defaults keep a typed custom level; a song stores the number
        typed = settings.loudness_is_custom if self.song is None else False
        simple = not typed and (match or target == -14.0)
        if simple and not self.show_more_loudness:
            self.loudness.set("match" if match else target)
            self.more_loudness.grid_remove()
            self.custom_loud.grid_remove()
        else:
            self.loudness.set("advanced")
            self.more_loudness.grid()
            custom = typed or target not in LOUDNESS_MORE.values()
            self.more_loudness.set(
                "custom" if custom and not match else (None if match else target)
            )
            if custom and not match:
                self._show_custom_level(settings, target)
            else:
                self.custom_loud.grid_remove()
        shown = dataclasses.replace(
            sound,
            match_loudness=match,
            loudness_target=target,  # type: ignore[arg-type]
        )
        self.loudness.explain(
            "Each new song is as loud as its original."
            if match
            else "Recommended: your 8D songs play as loud as the rest of your music "
            "(about -14 LUFS, like Spotify and YouTube)."
            if target == -14.0 and not typed
            else f"Now: {loudness_words(shown)}."
        )

    def _show_custom_level(self, settings: GuiSettings, target: object) -> None:
        """The custom level box, showing the level of the scope being edited."""
        self.custom_loud.grid()
        if self.song is None:
            level = settings.custom_loudness_text
        else:
            level = "" if target is None else f"{float(str(target)):g}"
        focused = str(self.focus_get() or "").startswith(str(self.custom_loud.entry))
        if self.custom_loud.entry.get() != level and not focused:
            self.custom_loud.set(level)

    def _place(self, value: object) -> None:
        """Next to the originals, or in a chosen folder."""
        self.wants_folder = value == "folder"
        if not self.wants_folder:
            self.app.set_destination("")
            return
        if self.folder.get().strip():
            self.app.set_destination(self.folder.get().strip())
        else:
            self.app.sync_controls()
            self._browse()

    def _folder_typed(self) -> None:
        """The folder box was edited by hand: checked once typing pauses."""
        # Checking a folder can be slow (a sleeping network drive), so not per key
        if self._folder_job is not None:
            self.after_cancel(self._folder_job)
        self._folder_job = self.after(FOLDER_PAUSE_MS, self._folder_settled)

    def _folder_settled(self) -> None:
        """Typing in the folder box paused: use what it says now."""
        self._folder_job = None
        self.app.set_destination(self.folder.get().strip(), refresh_only=True)

    def _browse(self) -> None:
        """Pick the output folder."""
        chosen = filedialog.askdirectory(title="Where should the 8D songs go?")
        if chosen:
            self.folder.delete(0, "end")
            self.folder.insert(0, str(Path(chosen)))
            self.wants_folder = True
            self.app.set_destination(str(Path(chosen)))

    def _show_where(self, settings: GuiSettings) -> None:
        """The 'Where the new files go' card."""
        app = self.app
        in_folder = bool(settings.destination) or self.wants_folder
        self.save_in.set("folder" if in_folder else "next")
        if in_folder:
            self.folder_row.grid()
            if self.folder.get().strip() != settings.destination and (
                self.focus_get() is None
                or not str(self.focus_get()).startswith(str(self.folder))
            ):
                self.folder.delete(0, "end")
                if settings.destination:
                    self.folder.insert(0, settings.destination)
        else:
            self.folder_row.grid_remove()
        problem = app.destination_problem()
        if in_folder and not settings.destination.strip():
            self.folder_note.configure(
                text="Choose the folder with Browse, or type its full path.",
                text_color=WARNING,
            )
        elif problem:
            self.folder_note.configure(text=problem, text_color=DANGER)
        elif settings.destination.strip():
            exists = Path(settings.destination).expanduser().is_dir()
            self.folder_note.configure(
                text="Folder found." if exists else "This folder will be created.",
                text_color=SUCCESS,
            )
        self.save_in.explain(
            "The 8D song is saved beside each original song."
            if not in_folder
            else "Every 8D song goes into this folder; songs added from a folder "
            "keep their sub-folders."
        )
        replacing = settings.originals != "keep"
        one_song = len(app.library) == 1
        self.naming.set(settings.name_style)
        self.naming.enable(not replacing)
        self.naming.enable_option("original", in_folder and not replacing)
        self.naming.enable_option("custom", one_song and not replacing)
        if replacing:
            why = "Set by 'Original songs' below while the originals are replaced."
        elif settings.name_style == "original" and not in_folder:
            why = (
                "The same name next to the original would overwrite it: choose a "
                "folder above, or pick 'Song (8D)'."
            )
        else:
            why = (
                "'Song (8D)' (recommended) sits beside the original without a clash."
                + ("" if in_folder else " 'Same as the original' needs a folder.")
                + ("" if one_song else " A custom name works with one song only.")
            )
        self.naming.explain(why, DANGER if "overwrite it" in why else TEXT_DIM)
        if settings.name_style == "custom" and not replacing:
            self.custom_name.grid()
        else:
            self.custom_name.grid_remove()
        self.overwrite.set(settings.overwrite)
        self.overwrite.explain(
            "Songs that already have an 8D file are made again and the old file is "
            "replaced."
            if settings.overwrite
            else "Recommended: songs that already have an 8D file are left alone, so "
            "running again only makes what's missing."
        )
        self.originals.set(settings.originals)
        self.originals.explain(
            "Recommended: your original songs are not touched."
            if not replacing
            else "Each original is moved to the Recycle Bin after its 8D version "
            "is safely saved. An 8D song can't be turned back into the normal one.",
            TEXT_DIM if not replacing else WARNING,
        )
