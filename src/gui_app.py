# Developed by ::> Gehan Fernando
"""The Audio8D desktop window, built with CustomTkinter.

A guided workflow in four steps - 1 Add music, 2 Choose sound, 3 Output,
4 Create - plus Your styles and Settings. The window only draws and
forwards clicks: settings live in gui_model.GuiSettings, the song list and
bulk styles in library, suggestions in recommend, previews in previews and
the conversion in pipeline/batch (the same code the command line uses).
Slow work runs on helper threads and reports back through one queue, so the
window never freezes, whether the list holds 3 songs or 3,000.
"""

import gc
import logging
import queue
import threading
import time
import tkinter as tk
import traceback
from collections.abc import Callable, Sequence
from pathlib import Path
from types import TracebackType
from typing import Any

import customtkinter as ctk

from . import __author__, __version__, addons, hints
from .app_base import (
    GC_INTERVAL_MS,
    LOG,
    REFRESH_SECONDS,
    WARM_IDLE_SECONDS,
    AppBase,
)
from .app_convert import ConvertMixin
from .app_library import LibraryMixin
from .app_output import OutputMixin
from .app_previews import PreviewMixin
from .app_setup import SetupMixin
from .app_sound import SoundMixin
from .batch import BatchItem
from .core.errors import Audio8DError
from .core.parsing import format_time
from .core.preferences import load_preferences
from .core.presets import PRESETS, RECOMMENDED_PRESET, Preset
from .core.types import AudioStreamInfo
from .core.user_presets import all_presets
from .dropfiles import enable_file_drop
from .ffmpeg import (
    set_preferred_paths,
)
from .ffmpeg.runner import kill_all_processes
from .gui_customize import CustomizeDialog
from .gui_dialogs import (
    Dialog,
    ErrorDialog,
    Toast,
    use_app_icon,
)
from .gui_model import (
    GuiSettings,
    config_for,
    destination_for,
    gui_words,
    is_custom,
)
from .gui_mystyles import YourStylesPage
from .gui_output import OutputPage
from .gui_review import ConvertPage
from .gui_settings import SettingsPage
from .gui_songs import SongsPage
from .gui_style_chooser import StyleChooser
from .gui_styles import StylesStep
from .gui_summary import (
    describe,
    style_label,
)
from .gui_widgets import (
    ACCENT,
    ACCENT_SOFT,
    ACCENT_TEXT,
    BACKGROUND,
    BORDER,
    DANGER,
    FOCUS,
    INK,
    SIDEBAR,
    SUCCESS,
    SURFACE,
    TEXT_DIM,
    Icons,
    Section,
    Tooltip,
    font,
    keyboard,
    open_path,
)
from .health import HealthReport
from .library import (
    READY,
    UNREADABLE,
    Library,
)
from .player import PLAYING, Player
from .previews import (
    PreviewManager,
)

# Sidebar pages: (key, title, tooltip)
NAV = (
    ("songs", "1  Add music", "Step 1: choose the songs (Ctrl+1)"),
    ("styles_step", "2  Choose sound", "Step 2: style, preview, customize (Ctrl+2)"),
    ("output", "3  Output", "Step 3: where and how to save (Ctrl+3)"),
    ("review", "4  Create", "Step 4: create the 8D songs (Ctrl+4)"),
    (None, "", ""),
    ("styles", "Your styles", "Create and share your own styles (Ctrl+5)"),
    ("settings", "Settings", "FFmpeg, appearance and logs (Ctrl+6)"),
)
_NAV_ICONS = {
    "songs": "songs",
    "styles_step": "sound",
    "output": "output",
    "review": "review",
    "styles": "styles",
    "settings": "settings",
}


class _QueueLog(logging.Handler):
    """Sends log lines to the window's event queue (safe from any thread)."""

    def __init__(self, events: queue.Queue) -> None:
        """Remember the queue."""
        super().__init__()
        self.events = events
        self.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"
            )
        )

    def emit(self, record: logging.LogRecord) -> None:
        """Queue one formatted line."""
        self.events.put(("log", self.format(record)))


class _NotBuilt:
    """Stands in for a page that hasn't been made yet: every update is skipped."""

    def __getattr__(self, _name: str) -> "_NotBuilt":
        return self

    def __call__(self, *_args: object, **_kwargs: object) -> None:
        return None


_NOT_BUILT = _NotBuilt()


class _Pages(dict):
    """The window's pages, each made the first time it is needed.

    Making all six at start-up took seconds; now only the first page is made
    then, and each other page when it is first opened.
    """

    def __init__(self, app: "Audio8DApp", makers: dict[str, Callable]) -> None:
        """makers: page key -> the page class."""
        super().__init__()
        self.app = app
        self.makers = makers

    def __missing__(self, key: str) -> ctk.CTkScrollableFrame:
        page = self.makers[key](self.app.content, self.app)
        self[key] = page
        self.app.page_made(key, page)
        return page


class NavItem(ctk.CTkFrame):
    """One sidebar entry: an icon, a title, and a line saying how that step is."""

    def __init__(
        self, master: tk.Misc, key: str, title: str, tip: str, go: Callable[[], None]
    ) -> None:
        """Draw the entry; click, Space or Enter opens its page."""
        super().__init__(
            master,
            fg_color="transparent",
            corner_radius=8,
            border_width=0,
            cursor="hand2",
        )
        self.chosen = False
        self.grid_columnconfigure(2, weight=1)
        # The keyboard focus bar on the left (CustomTkinter clips a border's corners)
        self.focus_bar = ctk.CTkFrame(
            self, width=4, corner_radius=2, fg_color=FOCUS, height=40
        )
        self.focus_bar.grid(
            row=0, column=0, rowspan=2, sticky="ns", padx=(4, 0), pady=6
        )
        self.focus_bar.grid_remove()
        self.icon = ctk.CTkLabel(
            self,
            text=Icons.glyph(_NAV_ICONS[key]),
            font=Icons.font(18),
            text_color=TEXT_DIM,
            width=30,
        )
        self.icon.grid(row=0, column=1, rowspan=2, padx=(6, 6), pady=6)
        self.title = ctk.CTkLabel(
            self, text=title, font=font(14), anchor="w", text_color=INK
        )
        self.title.grid(row=0, column=2, sticky="ew", pady=(6, 0))
        self.status = ctk.CTkLabel(
            self, text="", font=font(11), anchor="w", text_color=TEXT_DIM
        )
        self.status.grid(row=1, column=2, sticky="ew", pady=(0, 6))
        # CTk hints add as bool on frames and as str on labels; both mean "+"
        self.bind("<Button-1>", lambda _e: go(), add=True)
        for label in (self.icon, self.title, self.status):
            label.bind("<Button-1>", lambda _e: go(), add="+")
        keyboard(self, go, self._ring)
        Tooltip(self, tip)

    def _ring(self, on: bool) -> None:
        """Show the keyboard focus: the bar on the left and a light highlight."""
        if on:
            self.focus_bar.grid()
            self.configure(fg_color=ACCENT_SOFT)
        else:
            self.focus_bar.grid_remove()
            self.configure(fg_color=ACCENT_SOFT if self.chosen else "transparent")

    def show(self, chosen: bool, status: str, done: bool, problem: bool) -> None:
        """Highlight the current page; say how its step stands."""
        self.chosen = chosen
        self.configure(fg_color=ACCENT_SOFT if chosen else "transparent")
        self.title.configure(
            font=font(14, "bold" if chosen else "normal"),
            text_color=ACCENT_TEXT if chosen else INK,
        )
        self.icon.configure(text_color=ACCENT_TEXT if chosen else TEXT_DIM)
        mark = "✓ " if done else ("! " if problem else "")
        self.status.configure(
            text=f"{mark}{status}",
            text_color=DANGER if problem else (SUCCESS if done else TEXT_DIM),
        )
        if status:
            self.status.grid()
        else:
            self.status.grid_remove()


# The window's state is set up here, in one place, for all of its parts
class Audio8DApp(  # pylint: disable=too-many-instance-attributes
    LibraryMixin,
    SoundMixin,
    OutputMixin,
    SetupMixin,
    PreviewMixin,
    ConvertMixin,
    AppBase,
):
    """The main window: steps in the sidebar, pages, a status bar, the work threads."""

    def __init__(self, songs: Sequence[Path] = ()) -> None:
        """Build everything and show step 1."""
        self.preferences, preferences_problem = load_preferences()
        ctk.set_appearance_mode(self.preferences.theme)
        ctk.set_widget_scaling(self.preferences.scale)
        set_preferred_paths(*self.preferences.tools())
        addons.set_preferred_python(self.preferences.python())
        super().__init__()
        Icons.setup()
        self.title(f"Audio8D {__version__} - 3D music for headphones")
        use_app_icon(self)
        self.geometry("1320x880")
        self.minsize(1100, 720)
        self.configure(fg_color=BACKGROUND)
        self._make_state()
        self._build_window()
        self._start_background(songs, preferences_problem)

    def _make_state(self) -> None:
        """Everything the window keeps track of, before any widget is made."""
        # Set by _load_styles when the saved-styles file can't be read
        self.styles_problem: str | None = None
        self.presets: dict[str, Preset] = self._load_styles()
        self.settings = GuiSettings()
        self.settings.apply_style(self.presets[RECOMMENDED_PRESET])
        self._use_remembered_defaults()
        self.library = Library()
        self.library.use_styles(self.presets)
        self.events: queue.Queue[tuple] = queue.Queue()
        self.previews = PreviewManager(self.events.put)
        self.player = Player()
        self.player_song: Path | None = None
        # The preview asked for last; it plays by itself once it is ready
        self.preview_wanted: tuple[Path, str] | None = None
        # song -> (fingerprint, style label) of a style being tried, not applied
        self.trials: dict[Path, tuple[str, str]] = {}
        self.cancel = threading.Event()
        self.busy = False
        self.started = 0.0
        self.overall_share = 0.0
        self.current: str | None = None
        self.untagged_mood: str | None = None
        self._undo: list[tuple[dict[Path, str], str]] = []
        # Reading song details: which batch is current, and what was read before
        self.read_generation = 0
        self._probe_cache: dict[tuple[str, int, int], AudioStreamInfo] = {}
        self.tools_problem: str | None = None
        # The last system check (None until the first one finishes)
        self.health: HealthReport | None = None
        self.health_checking = False
        self.addon_cancel = threading.Event()
        # The last conversion: song -> (style, status, result, kind), and outputs
        self.run_results: dict[Path, tuple[str, str, str, str]] = {}
        self.run_outputs: dict[Path, Path] = {}
        self.run_items: list[BatchItem] = []
        self.run_stages: list[str] = []
        self._was_playing = False
        self._dirty = False
        self._read_progress = False
        self._last_refresh = 0.0
        # Log lines kept until the log view exists (the newest few thousand)
        self._log_waiting = []
        self.tool_checks = {}
        self.log_handler = _QueueLog(self.events)
        logging.getLogger().addHandler(self.log_handler)
        self.set_verbose(self.preferences.verbose, save=False)

    def _build_window(self) -> None:
        """The sidebar, the page area and the status bar; step 1 is shown."""
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self._build_status()
        self.makers = {
            "songs": SongsPage,
            "styles_step": StylesStep,
            "output": OutputPage,
            "review": ConvertPage,
            "styles": YourStylesPage,
            "settings": SettingsPage,
        }
        self.pages = _Pages(self, self.makers)
        self._bind_keys()
        self.show_page("songs")
        self.sync_controls()
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _start_background(
        self, songs: Sequence[Path], preferences_problem: str | None
    ) -> None:
        """File drops, start-up messages and checks, and the timers."""
        # Hooked now rather than on a timer, so a drop in the first seconds still counts
        enable_file_drop(self, self.add_paths)
        if self.styles_problem:
            self.after(
                600,
                lambda: self.toast(
                    "Your saved styles couldn't be read: see Your styles", "error"
                ),
            )
        if preferences_problem:
            self.after(900, lambda: self.toast(preferences_problem, "error"))
        if songs:
            self.after(300, lambda: self.add_paths(list(songs)))
        self.after(400, self.check_tools)
        # Every dependency is run once at start-up, on a helper thread
        self.after(450, lambda: self.check_health(startup=True))
        # Other pages are made while nobody is using the window (see _warm_up)
        self._last_input = time.perf_counter()
        tk.Misc.bind_all(self, "<KeyPress>", self._touched, "+")
        tk.Misc.bind_all(self, "<ButtonPress>", self._touched, "+")
        self._warm = ["styles_step", "output", "review", "settings", "styles"]
        self.after(1500, self._warm_up)
        self.after(2500, self._warm_dialogs)
        self.after(80, self._poll)
        # Tk objects freed on a helper thread block it on Tcl, so only collect here
        gc.disable()
        self.after(GC_INTERVAL_MS, self._collect_garbage)

    def _touched(self, _event: object = None) -> None:
        """The user pressed a key or clicked: warming up waits."""
        self._last_input = time.perf_counter()

    def _warm_up(self) -> None:
        """Prepare one more page (and its folded parts), but only while idle.

        A CustomTkinter page is slow the first time it is drawn, so each page is
        made and drawn once off-screen while nobody is using the window. Visiting
        it or opening its folded parts later is then quick.
        """
        if not self._warm or not self.winfo_exists():
            return
        idle = time.perf_counter() - self._last_input > WARM_IDLE_SECONDS
        if not idle or self.busy or self._reading_count():
            self.after(700, self._warm_up)
            return
        key = self._warm[0]
        if key == self.current:
            # A page on screen can't be prepared out of sight; come back later
            self._warm.append(self._warm.pop(0))
            self.after(1500, self._warm_up)
            return
        self._warm.pop(0)
        page = self.pages[key]
        # First drawn in place, underneath the page on screen…
        page.grid(row=0, column=0, sticky="nsew")
        page._parent_frame.lower()  # pylint: disable=protected-access
        self.after(400, lambda: self._warm_off_screen(key))

    def _warm_off_screen(self, key: str) -> None:
        """…then moved out of sight, where its folded parts are opened once."""
        page = self.pages[key]
        if key == self.current or time.perf_counter() - self._last_input < 0.4:
            # Shown (or asked for) meanwhile: leave it be
            self.after(250, self._warm_up)
            return
        page.grid_forget()
        width, height = self.content.winfo_width(), self.content.winfo_height()
        tk.Place.place_configure(
            page._parent_frame,  # pylint: disable=protected-access
            in_=self.content,
            x=-width - 50,
            y=0,
            width=width,
            height=height,
        )
        sections = [
            section
            for section in getattr(page, "warm_sections", list)()
            if not section.opened
        ]
        self.after(120, lambda: self._warm_sections(key, sections))

    def _warm_sections(self, key: str, sections: list[Section]) -> None:
        """Open each folded part off-screen once, then put the page away."""
        page_frame = self.pages[key]._parent_frame  # pylint: disable=protected-access
        if sections and key != self.current and page_frame.winfo_manager() == "place":
            section = sections.pop(0)
            section.toggle()

            def close() -> None:
                if section.opened:
                    section.toggle()
                self._warm_sections(key, sections)

            self.after(300, close)
            return
        frame = self.pages[key]._parent_frame  # pylint: disable=protected-access
        if key != self.current and frame.winfo_manager() == "place":
            tk.Place.place_forget(frame)
        self.after(250, self._warm_up)

    def _warm_dialogs(self) -> None:
        """Make the style chooser and Customize dialog out of sight while idle.

        They are then only shown when asked for, so they open at once.
        """
        if not self.winfo_exists():
            return
        idle = time.perf_counter() - self._last_input > WARM_IDLE_SECONDS
        if not idle or self.busy or self._reading_count():
            self.after(700, self._warm_dialogs)
            return
        if self.chooser is None:
            self.chooser = StyleChooser(self)
            self.chooser.build_cards()
            self.after(400, self._warm_dialogs)
        elif self.customize is None:
            self.customize = CustomizeDialog(self)

    def _collect_garbage(self) -> None:
        """Free cyclic garbage on the window's own thread, a few times a minute."""
        gc.collect()
        self.after(GC_INTERVAL_MS, self._collect_garbage)

    def destroy(self) -> None:
        """Close the window and hand garbage collection back to Python."""
        gc.enable()
        # Timers still waiting would fire into a closed window and print Tcl errors
        try:
            for job in self.tk.call("after", "info"):
                self.tk.call("after", "cancel", job)
        except tk.TclError:
            pass
        super().destroy()

    # ------------------------------------------------------------ building

    def _load_styles(self) -> dict[str, Preset]:
        """Built-in and saved styles; a broken styles file only loses your own."""
        try:
            styles = all_presets()
        except Audio8DError as exc:
            LOG.warning("Saved styles could not be read: %s", exc)
            self.styles_problem = gui_words(str(exc))
            return dict(PRESETS)
        self.styles_problem = None
        return styles

    def _build_sidebar(self) -> None:
        """Logo, the four steps, the extra pages, and the version at the bottom."""
        strip = ctk.CTkFrame(
            self, width=250, corner_radius=0, fg_color=SIDEBAR, border_width=0
        )
        strip.grid(row=0, column=0, rowspan=2, sticky="nsw")
        strip.grid_propagate(False)
        strip.grid_columnconfigure(0, weight=1)
        strip.grid_rowconfigure(len(NAV) + 1, weight=1)
        ctk.CTkFrame(self, width=1, fg_color=BORDER, corner_radius=0).grid(
            row=0, column=0, rowspan=2, sticky="nse"
        )
        logo = ctk.CTkFrame(strip, fg_color="transparent")
        logo.grid(row=0, column=0, sticky="ew", padx=20, pady=(24, 20))
        ctk.CTkLabel(
            logo,
            text=Icons.glyph("headphones"),
            font=Icons.font(26),
            text_color=ACCENT_TEXT,
        ).pack(side="left")
        words = ctk.CTkFrame(logo, fg_color="transparent")
        words.pack(side="left", padx=10)
        ctk.CTkLabel(words, text="Audio8D", font=font(20, "bold"), anchor="w").pack(
            anchor="w"
        )
        ctk.CTkLabel(
            words, text="3D music for headphones", font=font(11), text_color=TEXT_DIM
        ).pack(anchor="w")
        self.nav: dict[str, NavItem] = {}
        for row, (key, text, tip) in enumerate(NAV, start=1):
            if key is None:
                ctk.CTkFrame(strip, height=1, fg_color=BORDER).grid(
                    row=row, column=0, sticky="ew", padx=24, pady=10
                )
                continue
            item = NavItem(strip, key, text, tip, lambda k=key: self.show_page(k))
            item.grid(row=row, column=0, sticky="ew", padx=12, pady=2)
            self.nav[key] = item
        ctk.CTkLabel(
            strip,
            text=f"v{__version__}\nDeveloped by {__author__}",
            font=font(11),
            text_color=TEXT_DIM,
            justify="left",
        ).grid(row=len(NAV) + 2, column=0, sticky="sw", padx=22, pady=20)

    def _build_status(self) -> None:
        """The bottom strip: what's happening, its progress, the chosen settings."""
        status = ctk.CTkFrame(
            self, height=48, corner_radius=0, fg_color=SURFACE, border_width=0
        )
        status.grid(row=1, column=1, sticky="ew")
        status.grid_columnconfigure(1, weight=1)
        self.overall = ctk.CTkProgressBar(
            status, width=200, height=8, progress_color=ACCENT
        )
        self.overall.set(0)
        self.overall.grid(row=0, column=0, padx=(24, 12), pady=18)
        self.status_text = ctk.CTkLabel(
            status, text="Ready.", font=font(13), anchor="w"
        )
        self.status_text.grid(row=0, column=1, sticky="ew")
        self.settings_text = ctk.CTkLabel(
            status, text="", font=font(12), text_color=TEXT_DIM, anchor="e"
        )
        self.settings_text.grid(row=0, column=3, sticky="e", padx=24)
        # Short notices take the summary's place for a moment (see Toast)
        self.toast_slot = (status, self.settings_text)

    def _bind_keys(self) -> None:
        """Keyboard shortcuts for the common actions."""
        self.bind("<Control-o>", lambda _e: self.ask_files())
        self.bind("<Control-O>", lambda _e: self.ask_folder())
        self.bind("<Control-Return>", lambda _e: self.run_convert())
        self.bind("<Control-p>", lambda _e: self.preview_focused())
        self.bind("<Control-f>", lambda _e: self._focus_search())
        self.bind("<Escape>", lambda _e: self.stop())
        for number, key in enumerate(
            ("songs", "styles_step", "output", "review", "styles", "settings"),
            start=1,
        ):
            self.bind(
                f"<Control-Key-{number}>", lambda _e, key=key: self.show_page(key)
            )

    def _focus_search(self) -> None:
        """Ctrl+F: the search box of the page on screen."""
        page = self.pages.get(self.current or "")
        box = getattr(page, "search", None)
        if box is not None:
            box.focus_set()

    def report_callback_exception(
        self,
        exc: type[BaseException],
        val: BaseException,
        tb: TracebackType | None,
    ) -> None:
        """A surprise inside a button or event: log it and explain, never go silent."""
        LOG.error("Unexpected problem in the window", exc_info=(exc, val, tb))
        self._show_error(val)

    def close(self) -> None:
        """Closing the window mid-conversion: ask first, then stop cleanly."""
        if self.busy:
            if not Dialog.confirm(
                self,
                "Stop and close?",
                "Songs are still being created. Songs that are finished are kept; "
                "the song being made is cleaned up.",
                "Stop and close",
                "Keep working",
            ):
                return
            self.cancel.set()
        settings_page = self.pages.get("settings")
        if settings_page is not None and settings_page.addon.installing:
            if not Dialog.confirm(
                self,
                "Stop the add-on and close?",
                "The add-on is still being installed or removed. Closing stops it; "
                "nothing half-made is kept.",
                "Stop and close",
                "Keep working",
            ):
                return
        self.addon_cancel.set()
        # Defaults changed a moment ago are saved now, not lost with the window
        if getattr(self, "_remember_job", None):
            self.after_cancel(self._remember_job)  # type: ignore[arg-type]
            self._save_defaults()
        self.read_generation += 1
        self.player.close()
        self.previews.close()
        # Any FFmpeg, pip or Demucs still running is stopped, never left behind
        kill_all_processes()
        logging.getLogger().removeHandler(self.log_handler)
        self.destroy()

    # ------------------------------------------------------------ small helpers

    def label(self, name: str) -> str:
        """How a style's name is shown."""
        return style_label(name, self.presets)

    def name_for_label(self, label: str) -> str | None:
        """The style whose shown name is label."""
        return next((n for n, p in self.presets.items() if p.label == label), None)

    @staticmethod
    def _songs_word(count: int) -> str:
        """'1 song', '12 songs'."""
        return f"{count} song{'s' if count != 1 else ''}"

    def toast(self, text: str, kind: str = "info") -> None:
        """A short notice in the status bar."""
        Toast(self, text, kind)

    def open_file(self, path: Path) -> None:
        """Open a file or folder with the usual app."""
        open_path(path)

    def songs(self, readable_only: bool = True) -> list[tuple[Path, Path | None]]:
        """(song, folder) of the songs to convert (unreadable ones left out)."""
        return [
            (track.song, track.folder)
            for track in self.library.tracks
            if not readable_only or track.state != UNREADABLE
        ]

    # ------------------------------------------------------------ pages

    def live(self, key: str) -> Any:
        """A page to update, if it has been made; otherwise updates are skipped."""
        return self.pages.get(key, _NOT_BUILT)

    def page_made(self, key: str, page: ctk.CTkScrollableFrame) -> None:
        """A page was just made: bring it up to date with everything so far."""
        if key == "songs":
            page.refresh()  # type: ignore[attr-defined]
        elif key == "styles_step":
            page.refresh()  # type: ignore[attr-defined]
            page.show(self.settings)  # type: ignore[attr-defined]
        elif key == "review":
            page.write_log(self._log_waiting)  # type: ignore[attr-defined]
            self._log_waiting = []
        elif key == "settings":
            if self.tool_checks:
                page.tested(self.tool_checks, None)  # type: ignore[attr-defined]
            page.health.show(  # type: ignore[attr-defined]
                self.health, self.health_checking
            )
            page.addon.show(  # type: ignore[attr-defined]
                self.health.addon if self.health else None, self.health_checking
            )

    # ------------------------------------------------------------ navigation

    def show_page(self, key: str, focus: str | None = None) -> None:
        """Bring one page to the front and highlight its sidebar entry.

        focus names a part of the page to scroll to and open (e.g. "singer").
        """
        key = {"sound": "styles_step"}.get(key, key)
        # Anything shown on screen pauses the background preparation
        self._last_input = time.perf_counter()
        # Scrolling pages live inside an outer frame, so show/hide beats tkraise
        if self.current is not None and self.current != key:
            self.pages[self.current].grid_forget()
        page = self.pages[key]
        frame = page._parent_frame  # pylint: disable=protected-access
        if frame.winfo_manager() == "place":
            # It was being prepared out of sight: bring it back first
            tk.Place.place_forget(frame)
        page.grid(row=0, column=0, sticky="nsew")
        frame.lift()
        self.current = key
        if key == "styles_step":
            page.catch_up()  # type: ignore[attr-defined]
        if key in ("review", "output"):
            self.pages[key].show(self.settings)  # type: ignore[attr-defined]
        if focus:
            target = self.pages[key]
            self.after(60, lambda: target.reveal(focus))  # type: ignore[attr-defined]
        self.refresh_nav()

    def refresh_nav(self) -> None:
        """The sidebar: which page is open, and how each step stands."""
        tracks = self.library.tracks
        count = len(tracks)
        own = sum(1 for t in tracks if is_custom(self.settings, t.song))
        found = self.find_problems() if count else []
        output_problem = any(page == "output" for page, _t in found)
        try:
            kind = config_for(self.settings).output_format.upper()
        except Audio8DError:
            kind = "?"
        destination = destination_for(self.settings)
        states = {
            "songs": (
                f"{count} song{'s' if count != 1 else ''}"
                if count
                else "Nothing added yet",
                bool(count),
                False,
            ),
            "styles_step": (
                f"{self.label(self.settings.style)}"
                + (f" · {own} custom" if own else " for all"),
                bool(count),
                any(page in ("sound", "styles_step") for page, _t in found),
            ),
            "output": (
                f"{kind} · {destination.name if destination else 'next to originals'}",
                bool(count) and not output_problem,
                output_problem,
            ),
            "review": (
                "Creating…"
                if self.busy
                else (f"{len(found)} to fix" if found else ("Ready" if count else "")),
                False,
                bool(found),
            ),
            "styles": ("", False, False),
            "settings": (
                "FFmpeg problem" if self.tools_problem else "",
                False,
                bool(self.tools_problem),
            ),
        }
        for key, item in self.nav.items():
            status, done, problem = states[key]
            item.show(key == self.current, status, done, problem)

    def sync_controls(self) -> None:
        """Make every page show the current settings."""
        self.live("songs").recursive.set(  # type: ignore[attr-defined]
            self.settings.recursive
        )
        self.live("styles_step").show(self.settings)  # type: ignore[attr-defined]
        if self.current == "output":
            self.live("output").show(self.settings)  # type: ignore[attr-defined]
        if self.current == "review":
            self.live("review").show(self.settings)  # type: ignore[attr-defined]
        self.refresh_status()

    def refresh_lists(self) -> None:
        """Rebuild both song tables (after songs or styles change)."""
        self.live("songs").refresh()  # type: ignore[attr-defined]
        self.live("styles_step").refresh()  # type: ignore[attr-defined]

    def refresh_status(self) -> None:
        """Update the settings summary on the right of the status bar."""
        try:
            text = describe(self.settings)
        except Audio8DError:
            text = "some settings need fixing (see step 4)"
        destination = destination_for(self.settings)
        text += f"  →  {destination.name}" if destination else "  →  next to originals"
        self.settings_text.configure(text=text)
        self.refresh_nav()
        self.remember_defaults()

    # ------------------------------------------------------------ the song list

    # ------------------------------------------------------------ styles

    # ------------------------------------------------------------ song sound

    # ------------------------------------------------------------ output

    # ------------------------------------------------------------ system check

    # ------------------------------------------------------------ settings

    # ------------------------------------------------------------ previews

    # ------------------------------------------------------------ checks

    # ------------------------------------------------------------ converting

    # ------------------------------------------------------------ logs

    # ------------------------------------------------------------ events

    # One place that turns every kind of helper-thread news into window changes
    def _poll(self) -> None:  # pylint: disable=too-many-branches
        """Apply what the helper threads reported."""
        lines: list[str] = []
        try:
            for _ in range(2000):
                event = self.events.get_nowait()
                if event[0] == "log":
                    lines.append(event[1])
                else:
                    self._handle(event)
        except queue.Empty:
            pass
        except tk.TclError:
            return
        if lines:
            if "review" in self.pages:
                self.pages["review"].write_log(lines)  # type: ignore[attr-defined]
            else:
                self._log_waiting = (self._log_waiting + lines)[-3000:]
        if self.busy:
            elapsed = time.perf_counter() - self.started
            text = self.status_text.cget("text").split("  (")[0]
            self.status_text.configure(text=f"{text}  ({format_time(elapsed)})")
        playing = self.player.state() == PLAYING
        if self.player_song is not None and self._was_playing and not playing:
            # The preview reached its end: its button says Preview again
            song, self.player_song = self.player_song, None
            self.player.close()
            self.status_text.configure(text="Preview finished. Nothing was saved.")
            self._preview_changed(song)
        self._was_playing = playing
        reading = self._reading_count() if self._read_progress else 0
        if self._read_progress:
            # One progress update per tick, however many songs were read in it
            self._read_progress = False
            total = len(self.library)
            if reading and not self.busy:
                self.status_text.configure(
                    text=f"Reading song details… {total - reading} of {total}"
                )
                self.overall.set((total - reading) / total)
            self.live("songs").show_counts()  # type: ignore[attr-defined]
        # Summaries wait until reading ends; rebuilding them meanwhile stutters
        if (
            self._dirty
            and not reading
            and not self._reading_count()
            and time.perf_counter() - self._last_refresh > REFRESH_SECONDS
        ):
            self._dirty = False
            self._last_refresh = time.perf_counter()
            self.live("styles_step").refresh()
            self.live("styles_step").show_default()
            self.refresh_nav()
        self.after(80, self._poll)

    def _reading_count(self) -> int:
        """How many songs are still waiting to be read."""
        return sum(1 for t in self.library.tracks if t.state not in (READY, UNREADABLE))

    def _handle(self, event: tuple) -> None:
        """One event from a helper thread, handed to the part that knows it."""
        handlers: dict[str, Callable[[tuple], None]] = {
            "probed": self._song_read,
            "unreadable": self._song_read,
            "read-done": self._reading_done,
            "tools-missing": self._tools_missing,
            "health": lambda e: self._health_done(e[1], e[2]),
            "addon": lambda e: self._addon_checked(e[1], e[2]),
            "addon-line": lambda e: self.live("settings").addon.work_line(e[1]),
            "addon-progress": lambda e: self.live("settings").addon.work_progress(e[1]),
            "addon-installed": self._addon_done,
            "addon-base": lambda e: self._addon_base(e[1]),
            "link-failed": lambda e: self._link_failed(e[1]),
            "tools-tested": lambda e: self._tools_tested(e[1], e[2]),
            "preview": self._preview_event,
            "row": self._conversion_row,
            "done": self._conversion_done,
            "toast": lambda e: self.toast(e[1], e[2]),
            "error": lambda e: self._show_error(e[1]),
            "report": lambda e: self._show_report(e[1]),
            "finished": self._conversion_finished,
        }
        handlers[event[0]](event)

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

    def _tools_missing(self, event: tuple) -> None:
        """Songs couldn't be read for want of FFmpeg or FFprobe."""
        self.tools_problem = gui_words(event[1])
        self.status_text.configure(text="FFmpeg is needed to read the songs.")
        self.toast("FFmpeg or FFprobe is missing: open Settings", "error")
        self.refresh_nav()

    def _show_error(self, error: BaseException) -> None:
        """A problem from the work thread: a plain headline, the fix, the details."""
        fix = hints.fix_for(error) if isinstance(error, Audio8DError) else None
        LOG.error("%s", error)
        message = gui_words(hints.headline(error))
        if fix:
            message += f"\n\nWhat to do: {gui_words(fix)}"
        details = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )
        ErrorDialog(self, message, f"{type(error).__name__}: {error}\n\n{details}")


def launch(songs: Sequence[Path] = ()) -> int:
    """Open the window and wait until it is closed."""
    app = Audio8DApp(songs)
    app.mainloop()
    return 0


__all__ = ["Audio8DApp", "launch"]
