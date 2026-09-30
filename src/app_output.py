# Developed by ::> Gehan Fernando
"""The main window, part: step 3: where the songs go and each song's file."""

from collections.abc import Sequence
from pathlib import Path

from .app_base import (
    AppBase,
)
from .gui_model import (
    OUTPUT_FIELDS,
    name_problem,
    recent_destination_problem,
    reset_file_settings,
    set_file_settings,
)
from .gui_summary import (
    song_plan,
)


class OutputMixin(AppBase):
    """Step 3: where the songs go and each song's file."""

    def set_originals(self, value: object) -> None:
        """Keep or replace the originals."""
        self.settings.originals = str(value)
        self.sync_controls()

    def set_name_style(self, value: object) -> None:
        """How the new files are named."""
        self.settings.name_style = str(value)
        self.sync_controls()

    def set_custom_name(self, text: str) -> str | None:
        """The custom file name box."""
        self.settings.custom_name = text
        self.refresh_status()
        return name_problem(text)

    def set_overwrite(self, value: object) -> None:
        """Skip songs whose 8D file exists, or replace those files."""
        self.settings.overwrite = bool(value)
        self.sync_controls()

    def set_destination(self, text: str, refresh_only: bool = False) -> None:
        """The 'Save in' folder ('' for next to each original)."""
        self.settings.destination = text
        if refresh_only:
            self.refresh_status()
            self.live("output").show(self.settings)  # type: ignore[attr-defined]
        else:
            self.sync_controls()

    def destination_problem(self) -> str | None:
        """Why the chosen folder can't be used, or None."""
        return recent_destination_problem(self.settings.destination)

    def set_default_output(self, **values: object) -> None:
        """Output defaults for every song that has no output settings of its own."""
        knobs = {key: value for key, value in values.items() if key in OUTPUT_FIELDS}
        if knobs:
            self.change_sound(**knobs)
        for key, value in values.items():
            if key not in OUTPUT_FIELDS:
                self.set_flag(key, value)

    def set_song_output(self, song: Path, **values: object) -> None:
        """One song's own output settings (values equal to the defaults are dropped)."""
        set_file_settings(self.settings, [song], **values)
        self._files_changed()

    def reset_song_files(self, songs: Sequence[Path]) -> None:
        """Songs go back to the default file settings."""
        count = reset_file_settings(self.settings, songs)
        self._files_changed()
        self.toast(f"{self._songs_word(count)} back to the default file settings", "ok")

    def _files_changed(self) -> None:
        """Songs' file settings changed: refresh what shows them."""
        self.live("output").show(self.settings)  # type: ignore[attr-defined]
        self.live("styles_step").refresh()  # type: ignore[attr-defined]
        self.refresh_status()
        self._refresh_preview_words()

    def song_plan(self) -> list[tuple[Path, str, str, str]]:
        """Each song's style, file settings and new file, for the Review step."""
        return song_plan(self.settings, self.songs(), self.presets)

    def set_flag(self, key: str, value: object) -> None:
        """A simple Output option (album art, title tag, check, jobs, play)."""
        setattr(self.settings, key, value)
        self.refresh_status()
        if self.current == "output":
            self.live("output").show(self.settings)  # type: ignore[attr-defined]
