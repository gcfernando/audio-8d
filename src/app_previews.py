# Developed by ::> Gehan Fernando
"""The main window, part: previews: a short, temporary listen before creating.

A preview has three states the user sees: Preview (nothing playing), Preparing…
(the sample is being made; pressing it again cancels) and Stop (it is playing).
Only one preview is made at a time; the files live in a private temporary
folder (see previews.py) and are deleted when no longer needed.
"""

from pathlib import Path

from .app_base import (
    LOG,
    AppBase,
)
from .core.errors import Audio8DError
from .core.settings import EffectConfig
from .core.types import Trim
from .gui_model import (
    GuiSettings,
    config_for,
    gui_words,
    song_config,
    song_options,
    trim_for,
    with_output,
)
from .gui_widgets import (
    open_path,
)
from .library import (
    UNREADABLE,
)
from .player import PLAYING, PlayerError
from .previews import (
    FAILED,
    MAKING,
    fingerprint,
)


def song_trim(settings: GuiSettings, song: Path) -> Trim | None:
    """The part of one song that is made (its own, or the default's)."""
    try:
        own = song_options(settings, song)
        return own.trim if own is not None else trim_for(settings)
    except Audio8DError:
        # An unusable time is reported where it is typed; a preview uses the whole song
        return None


# What a song's preview is doing, in the words its button and row show
IDLE_WORDS = "▶ Preview"
COMPARE_WORDS = "⇄ Compare A/B"
STOP_WORDS = "■ Stop"


class PreviewMixin(AppBase):
    """Previews: making, playing, stopping, and trying a style without applying it."""

    def set_preview_seconds(self, seconds: object) -> None:
        """How long previews are (Settings)."""
        self.settings.preview_seconds = int(seconds)  # type: ignore[arg-type]
        self._refresh_preview_words()

    def focus_song(self) -> Path | None:
        """The song a preview is for: the one selected on step 2, else the first."""
        page = self.pages.get("styles_step")
        chosen = page.focused_song() if page is not None else None
        if chosen is not None:
            return chosen
        readable = [t for t in self.library.tracks if t.state != UNREADABLE]
        return readable[0].song if readable else None

    def preview_state(self, song: Path) -> tuple[str, float]:
        """('idle' | 'making' | 'playing' | 'failed', share made) for one song."""
        status = self.previews.status_of(song)
        if status.state == MAKING and self.previews.making == song:
            return "making", status.share
        if self.player_song == song and self.player.state() == PLAYING:
            return "playing", 1.0
        if status.state == FAILED:
            return "failed", 0.0
        return "idle", 0.0

    def preview_words(self, song: Path, kind: str = "preview") -> str:
        """The words on a song's preview (or A/B compare) button and in its row."""
        state, share = self.preview_state(song)
        if self.previews.status_of(song).kind != kind:
            # The other kind of listen is under way: this button starts its own
            state = "idle"
        if state == "making":
            return f"◌ Preparing… {share:.0%}"
        if state == "playing":
            return STOP_WORDS
        if state == "failed":
            return "▶ Try again"
        return IDLE_WORDS if kind == "preview" else COMPARE_WORDS

    def preview_song(self, song: Path, kind: str = "preview") -> None:
        """Preview, Preparing… (cancels) or Stop, as the song's state calls for.

        kind "compare" makes an A/B file instead: the original, then the 8D sound.
        """
        state, _share = self.preview_state(song)
        same_kind = self.previews.status_of(song).kind == kind
        if state == "making" and same_kind:
            self.previews.cancel()
            self.preview_wanted = None
            self._preview_changed(song)
            return
        if state == "playing" and same_kind:
            self.stop_playing()
            return
        if self.busy:
            self.toast("Please wait until the songs are created", "error")
            return
        track = self.library.get(song)
        if track is None or track.state == UNREADABLE:
            self.toast("That file can't be read, so it can't be previewed", "error")
            return
        try:
            config = song_config(self.settings, song, self.presets)
        except Audio8DError as exc:
            self.toast(f"Fix the settings first: {gui_words(str(exc))}", "error")
            return
        self.trials.pop(song, None)
        self._start_preview(song, config, kind)

    @staticmethod
    def _listen_words(kind: str) -> str:
        """'a preview' or 'an A/B comparison', for the status bar."""
        return "an A/B comparison" if kind == "compare" else "a preview"

    def _start_preview(
        self, song: Path, config: EffectConfig, kind: str = "preview"
    ) -> None:
        """Ask for one song's sample (made once, then cached) and play it when ready."""
        if self.tools_problem:
            self.toast("FFmpeg isn't working: fix it in Settings first", "error")
            return
        if config.vocals == "center" and not self.singer_ready():
            self.toast(
                "This song keeps the singer in the middle, which needs the add-on "
                "(Settings, Add-on)",
                "error",
            )
            return
        previous = self.previews.making
        if self.player_song is not None:
            # A new preview replaces the one playing
            self.stop_playing()
        self.preview_wanted = (song, kind)
        self.previews.start(
            song,
            config,
            float(self.settings.preview_seconds),
            kind,
            trim=song_trim(self.settings, song),
        )
        for changed in {previous, song} - {None}:
            self._preview_changed(changed)  # type: ignore[arg-type]
        self.status_text.configure(
            text=f"Preparing {self._listen_words(kind)} of {song.stem}…"
        )

    def try_config(self, song: Path, config: EffectConfig, label: str) -> None:
        """Preview a song with settings that are not applied (a style or a draft)."""
        if self.busy:
            self.toast("Please wait until the songs are created", "error")
            return
        self._start_preview(song, config)
        key = fingerprint(
            song,
            config,
            float(self.settings.preview_seconds),
            "preview",
            song_trim(self.settings, song),
        )
        self.trials[song] = (key, label)

    def try_style(self, config: EffectConfig, name: str | None = None) -> None:
        """Preview the chosen song with a style, without giving it that style."""
        song = self.focus_song()
        if song is None:
            self.toast("Add a song first (step 1), then preview", "error")
            return
        try:
            shared = config_for(self.settings)
        except Audio8DError as exc:
            self.toast(f"Fix the settings first: {gui_words(str(exc))}", "error")
            return
        self.try_config(
            song, with_output(config, shared), self.label(name) if name else "it"
        )

    def trial_words(self) -> tuple[str, bool]:
        """(what is being tried right now, whether it is playing) for the dialogs."""
        for song, (key, label) in self.trials.items():
            status = self.previews.status_of(song)
            if status.key != key:
                continue
            state, share = self.preview_state(song)
            if state == "making":
                return f"Preparing {label} on “{song.stem}”… {share:.0%}", False
            if state == "playing":
                return f"Playing {label} on “{song.stem}”. Nothing is changed.", True
            if state == "failed":
                return f"The preview failed: {status.problem}", False
        return "", False

    def _preview_changed(self, song: Path) -> None:
        """Refresh everything that shows one song's preview."""
        track = self.library.get(song)
        page = self.live("styles_step")
        if track is not None:
            page.update_track(track)
        page.show_selection()
        for key in ("chooser", "customize"):
            dialog = getattr(self, key, None)
            if dialog is not None and dialog.is_open:
                dialog.show_preview()

    def _refresh_preview_words(self) -> None:
        """Settings changed: the rows show the right preview state again."""
        page = self.live("styles_step")
        for song in list(self.previews.status):
            track = self.library.get(song)
            if track is not None:
                page.update_track(track)
        page.show_selection()

    def _play(self, song: Path, file: Path) -> None:
        """Play a finished preview inside the window (or in the music player)."""
        try:
            if self.player.file != file:
                self.player.load(file)
            self.player_song = song
            self.player.play(from_start=True)
        except PlayerError as exc:
            LOG.warning("Could not play %s: %s", file, exc)
            open_path(file)
        self._preview_changed(song)

    def stop_playing(self) -> None:
        """Stop the preview that is playing and let go of its file."""
        song = self.player_song
        self.player.close()
        self.player_song = None
        if song is not None:
            self.status_text.configure(text="Preview stopped. Nothing was saved.")
            self._preview_changed(song)

    def _preview_event(self, event: tuple) -> None:
        """A preview progressed, finished, failed or was cancelled."""
        if not self.previews.handle(event):
            return
        _kind, _number, song, what, payload = event
        listen = self._listen_words(self.previews.status_of(song).kind)
        if what == "ready" and self.preview_wanted is not None:
            if self.preview_wanted[0] == song:
                self.preview_wanted = None
                self.status_text.configure(
                    text=f"Playing {listen} of {song.stem}."
                    if listen == "a preview"
                    else f"Playing {listen} of {song.stem}: the original first, "
                    "then the 8D sound."
                )
                self._play(song, payload)
                return
        if what == "failed":
            self.preview_wanted = None
            self.status_text.configure(text=f"The preview of {song.stem} failed.")
            self.toast(f"The preview failed: {payload}", "error")
        elif what == "cancelled":
            self.status_text.configure(text="Preview cancelled.")
        elif what == "progress":
            self.status_text.configure(
                text=f"Preparing {listen} of {song.stem}… {float(payload):.0%}"
            )
        self._preview_changed(song)

    def preview_focused(self) -> None:
        """Ctrl+P: preview (or stop) the song selected on step 2."""
        song = self.focus_song()
        if song is not None:
            self.preview_song(song)
