# Developed by ::> Gehan Fernando
"""The main window, part: the sound: the default style, Customize, Reset to default."""

from collections.abc import Sequence
from pathlib import Path

from .app_base import (
    AppBase,
)
from .gui_customize import CustomizeDialog
from .gui_model import gui_words, reset_songs, typed_loudness
from .gui_style_chooser import StyleChooser
from .gui_widgets import problem_of
from .library import UNREADABLE


class SoundMixin(AppBase):
    """Choosing the default style, customizing songs, and resetting them."""

    # Made the first time each is opened, then reused (see gui_modal)
    chooser: StyleChooser | None = None
    customize: CustomizeDialog | None = None

    def open_style_chooser(self) -> None:
        """'Change style': choose the style every non-custom song uses."""
        if self.chooser is None:
            self.chooser = StyleChooser(self)  # type: ignore[arg-type]
        self.chooser.open(self.settings.style, self.choose_style)

    def open_customize(self, songs: Sequence[Path]) -> None:
        """'Customize…': these songs (or, with none, the default sound)."""
        readable = [
            song
            for song in songs
            if (track := self.library.get(song)) is not None
            and track.state != UNREADABLE
        ]
        if songs and not readable:
            self.toast("That file can't be read, so it can't be customized", "error")
            return
        if self.busy:
            self.toast("Please wait until the songs are created", "error")
            return
        if self.customize is None:
            self.customize = CustomizeDialog(self)  # type: ignore[arg-type]
        self.customize.open(readable)

    def edit_style(self, name: str) -> None:
        """'Edit' on Your styles: change a saved style's sound and name in Customize."""
        if self.busy:
            self.toast("Please wait until the songs are created", "error")
            return
        if name not in self.presets or not self.presets[name].custom:
            self.toast("Only your own styles can be edited", "error")
            return
        if self.customize is None:
            self.customize = CustomizeDialog(self)  # type: ignore[arg-type]
        self.customize.open_style(name)

    def settings_changed(self, message: str | None = None) -> None:
        """Songs' or the default's settings changed: refresh what shows them."""
        self.live("styles_step").refresh()
        self.sync_controls()
        self._refresh_preview_words()
        if message:
            self.toast(message, "ok")

    def reset_to_default(self, songs: Sequence[Path]) -> None:
        """'Reset to default': songs lose every setting of their own."""
        count = reset_songs(self.settings, songs)
        if not count:
            self.toast("Those songs already follow the defaults")
            return
        self.settings_changed(
            f"{self._songs_word(count)} follow the default settings again"
        )

    def set_speakers(self, on: bool) -> None:
        """'Safe for speakers too' for the default."""
        self.settings.speakers = on
        self.sync_controls()

    def change_sound(self, **knobs: object) -> None:
        """A default sound or output setting changed (Output step)."""
        self.settings.change(**knobs)
        self.sync_controls()
        self._refresh_preview_words()

    def reset_output(self) -> None:
        """The Output step's file settings go back to the recommended ones."""
        self.settings.reset_output()
        self.sync_controls()
        self.toast("Output settings are back to the recommended ones", "ok")

    def set_custom_loudness(self, text: str) -> str | None:
        """The custom loudness box on the Output step."""
        problem = problem_of(lambda: typed_loudness(text))
        if problem:
            # A refused level is never stored, the same as for one song
            return gui_words(problem) + "."
        self.settings.custom_loudness_text = text
        self.refresh_status()
        self._refresh_preview_words()
        return None
