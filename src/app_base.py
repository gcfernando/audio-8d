# Developed by ::> Gehan Fernando
"""What every part of the main window shares: its state and a few constants.

Audio8DApp is split by topic into mixins (songs, styles, sound, output,
setup, previews, converting). Each one inherits AppBase, which declares the
window's state and the handful of methods the parts call on each other, so
every part is checked by the type checker and pylint on its own.
"""

import abc
import logging
import queue
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import customtkinter as ctk

from . import hints
from .batch import BatchItem
from .core.preferences import Preferences
from .core.presets import Preset
from .core.settings import EffectConfig
from .core.types import AudioStreamInfo
from .gui_model import GuiSettings
from .health import HealthReport
from .library import Library
from .pipeline import STAGE_CHECK, STAGE_RENDER, STAGE_SAVE, STAGE_STEMS
from .player import Player
from .previews import PreviewManager
from .recommend import BatchSuggestion

LOG = logging.getLogger("src.gui_app" if __package__ == "src" else "audio8d.gui_app")
# How often the window frees cyclic garbage itself (see Audio8DApp.__init__)
GC_INTERVAL_MS = 3000
# Songs read at once when a big folder is added
READERS = 4
# The busiest the summaries may refresh while songs are being read
REFRESH_SECONDS = 0.4
# Pages are prepared in the background only after this long without input
WARM_IDLE_SECONDS = 1.0

_STAGE_WORDS = {
    STAGE_STEMS: "Splitting vocals",
    STAGE_RENDER: "Making the 3D mix",
    STAGE_SAVE: "Saving the file",
    STAGE_CHECK: "Checking the result",
}


def read_problem(error: BaseException) -> str:
    """Why a song couldn't be read, in a few plain words."""
    message = str(error)
    if "does not contain a usable audio stream" in message:
        return "there is no sound in it"
    if "took longer" in message:
        return "its drive is too slow or not connected"
    if any(clue in message for clue in ("Permission denied", "Access is denied")):
        return "Audio8D isn't allowed to open it"
    if "does not exist" in message or "No such file" in message:
        return "the file is no longer there"
    if message.startswith(("Command failed", "FFprobe returned")):
        return "not music, or damaged"
    return hints.short_message(error)


# The window's shared interface: each method here is one its parts call on another
class AppBase(ctk.CTk, abc.ABC):  # pylint: disable=too-many-public-methods
    """The main window's state, declared once for all of its parts."""

    # Settings, styles and songs
    preferences: Preferences
    styles_problem: str | None
    presets: dict[str, Preset]
    settings: GuiSettings
    library: Library
    # Helper threads report here; the window applies it on its own thread
    events: "queue.Queue[tuple]"
    # Previews and playing
    previews: PreviewManager
    player: Player
    player_song: Path | None
    preview_wanted: tuple[Path, str] | None
    trials: dict[Path, tuple[str, str]]
    _was_playing: bool
    # Converting
    cancel: threading.Event
    busy: bool
    started: float
    overall_share: float
    run_results: dict[Path, tuple[str, str, str, str]]
    run_outputs: dict[Path, Path]
    run_items: list[BatchItem]
    run_stages: list[str]
    # Reading song details
    read_generation: int
    _probe_cache: dict[tuple[str, int, int], AudioStreamInfo]
    _dirty: bool
    _read_progress: bool
    _last_refresh: float
    # Tools and the system check
    tools_problem: str | None
    tool_checks: dict
    health: HealthReport | None
    health_checking: bool
    addon_cancel: threading.Event
    # Pages and the frame around them
    current: str | None
    content: ctk.CTkFrame
    pages: Any
    makers: dict[str, Callable]
    status_text: ctk.CTkLabel
    settings_text: ctk.CTkLabel
    overall: ctk.CTkProgressBar
    log_handler: logging.Handler
    _log_waiting: list[str]
    nav: dict[str, Any]
    toast_slot: tuple
    # Pages are prepared in the background while nobody is using the window
    _warm: list[str]
    _last_input: float

    # The parts call these on each other; Audio8DApp has the real ones

    @abc.abstractmethod
    def label(self, name: str) -> str:
        """How a style's name is shown."""
        raise NotImplementedError

    @abc.abstractmethod
    def name_for_label(self, label: str) -> str | None:
        """The style whose shown name this is."""
        raise NotImplementedError

    @staticmethod
    @abc.abstractmethod
    def _songs_word(count: int) -> str:
        """'1 song' or '3 songs'."""
        raise NotImplementedError

    @abc.abstractmethod
    def toast(self, text: str, kind: str = "info") -> None:
        """A short message in the corner."""
        raise NotImplementedError

    @abc.abstractmethod
    def songs(self, readable_only: bool = True) -> list[tuple[Path, Path | None]]:
        """(song, folder) of the songs to convert."""
        raise NotImplementedError

    @abc.abstractmethod
    def live(self, key: str) -> Any:
        """A page to update, if it has been made."""
        raise NotImplementedError

    @abc.abstractmethod
    def show_page(self, key: str, focus: str | None = None) -> None:
        """Bring one page to the front."""
        raise NotImplementedError

    @abc.abstractmethod
    def refresh_nav(self) -> None:
        """The sidebar: which page is open, and how each step stands."""
        raise NotImplementedError

    @abc.abstractmethod
    def sync_controls(self) -> None:
        """Make every page show the current settings."""
        raise NotImplementedError

    @abc.abstractmethod
    def refresh_lists(self) -> None:
        """Rebuild both song tables."""
        raise NotImplementedError

    @abc.abstractmethod
    def refresh_status(self) -> None:
        """Update the settings summary in the status bar."""
        raise NotImplementedError

    @abc.abstractmethod
    def focus_song(self) -> Path | None:
        """The song a preview is for."""
        raise NotImplementedError

    @abc.abstractmethod
    def preview_words(self, song: Path) -> str:
        """The words on a song's preview button."""
        raise NotImplementedError

    @abc.abstractmethod
    def preview_state(self, song: Path) -> tuple[str, float]:
        """What a song's preview is doing."""
        raise NotImplementedError

    @abc.abstractmethod
    def preview_song(self, song: Path) -> None:
        """Preview, cancel or stop one song."""
        raise NotImplementedError

    @abc.abstractmethod
    def try_config(self, song: Path, config: EffectConfig, label: str) -> None:
        """Preview settings that are not applied."""
        raise NotImplementedError

    @abc.abstractmethod
    def trial_words(self) -> tuple[str, bool]:
        """What is being tried right now."""
        raise NotImplementedError

    @abc.abstractmethod
    def change_sound(self, **knobs: object) -> None:
        """A default sound or output setting changed."""
        raise NotImplementedError

    @abc.abstractmethod
    def choose_style(self, name: str) -> None:
        """A new default style."""
        raise NotImplementedError

    @abc.abstractmethod
    def settings_changed(self, message: str | None = None) -> None:
        """Settings changed: refresh what shows them."""
        raise NotImplementedError

    @abc.abstractmethod
    def open_customize(self, songs: Sequence[Path]) -> None:
        """Open the Customize dialog."""
        raise NotImplementedError

    @abc.abstractmethod
    def batch_suggestion(self) -> BatchSuggestion | None:
        """The best default style for the list."""
        raise NotImplementedError

    @abc.abstractmethod
    def _reading_count(self) -> int:
        """How many songs are still waiting to be read."""
        raise NotImplementedError

    @abc.abstractmethod
    def _load_styles(self) -> dict[str, Preset]:
        """Built-in styles plus the saved ones."""
        raise NotImplementedError

    @abc.abstractmethod
    def _read(self, tracks: list) -> None:
        """Read the new songs' details on helper threads."""
        raise NotImplementedError

    @abc.abstractmethod
    def stop_reading(self) -> None:
        """Stop reading song details."""
        raise NotImplementedError

    @abc.abstractmethod
    def stop_playing(self) -> None:
        """Stop the preview that is playing."""
        raise NotImplementedError

    @abc.abstractmethod
    def _preview_changed(self, song: Path) -> None:
        """One song's preview changed: refresh what shows it."""
        raise NotImplementedError

    @abc.abstractmethod
    def _refresh_preview_words(self) -> None:
        """Refresh the preview column after a change."""
        raise NotImplementedError

    @abc.abstractmethod
    def singer_ready(self) -> bool:
        """True when the last check found the singer add-on ready."""
        raise NotImplementedError
