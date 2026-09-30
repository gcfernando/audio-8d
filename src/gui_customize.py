# Developed by ::> Gehan Fernando
"""The Customize dialog: one song's (or several songs', or the default) sound.

It shows a few meaningful choices first (style, movement, speed, space, and
two optional switches); the precise values sit folded under Advanced, and a
song's own file settings under 'Save this song differently'. Every change is
kept in a draft (gui_model.Changes) until Apply, so Cancel changes nothing,
and a change to several songs touches only what was really changed.
"""

from pathlib import Path
from typing import TYPE_CHECKING

import customtkinter as ctk

from .core.errors import Audio8DError
from .core.parsing import format_keyframes, typed_time_problem
from .core.settings import EffectConfig
from .core.sound_levels import LEVELS, SoundLevel
from .core.user_presets import update_user_preset
from .gui_dialogs import Toast
from .gui_fields import (
    ChoiceField,
    EntryField,
    MenuField,
    SliderField,
    SwitchField,
    trim_fields,
)
from .gui_modal import Modal
from .gui_model import (
    FORMAT_CHOICES,
    QUALITY_CHOICES,
    SPEAKERS,
    Changes,
    GuiSettings,
    config_for,
    customize,
    draft,
    file_value,
    gui_words,
    is_custom,
    quality_choices,
    reset_songs,
    song_config,
    sound_of,
    typed_sound,
)
from .gui_style_save import check_name, checked_style
from .gui_widgets import (
    DANGER,
    INK,
    SUCCESS,
    TEXT_DIM,
    Badge,
    Section,
    button,
    font,
    hint,
    problem_of,
    set_changed,
)

if TYPE_CHECKING:
    from .gui_app import Audio8DApp

SPIN_HELP = "Seconds for one full circle. 8 is the classic 8D speed."
HEIGHT_HELP = "Lets the sound float up over your head. 0 stays at ear level."
SINGER_READY = (
    "An AI model keeps the voice clear in the middle while the music moves. Adds "
    "a minute or two per song."
)
SINGER_MISSING = "Needs the optional add-on (Settings, Add-on), which isn't installed."
# The simple loudness choices for one song; others are set on the Output step
SONG_LOUDNESS = {
    "Match music apps": -14.0,
    "Keep original loudness": "match",
    "No change": None,
}


# A holder of controls: show() is its one job, so it has few methods by design
class AdvancedSound:  # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """The precise sound values, made the first time Advanced is opened."""

    def __init__(self, body: ctk.CTkFrame, owner: "CustomizeDialog") -> None:
        """Make every control inside the section's body."""
        self.movement = SliderField(
            body,
            "Movement amount",
            "How far round your head the music travels, from 0 to 1.",
            (0, 1, 20),
            lambda v: f"{v:.2f}",
            lambda v: owner.tune(intensity=round(v, 2)),
        )
        self.spin = SliderField(
            body,
            "Seconds per circle",
            SPIN_HELP,
            (2, 100, 196),
            lambda v: f"{v:g} s",
            lambda v: owner.tune(rotation_seconds=round(v * 2) / 2),
            more="Below 5 seconds can make people dizzy; above 20 seconds the "
            "movement is hard to notice.",
        )
        self.room = SliderField(
            body,
            "Room amount",
            "How much natural room sound is added, from 0 (dry) to 1.",
            (0, 1, 20),
            lambda v: f"{v:.2f}",
            lambda v: owner.tune(ambience=round(v, 2)),
        )
        self.engine = ChoiceField(
            body,
            "Sound engine",
            "3D places the music around you; panning only moves it left and right.",
            {"3D around you": "3d", "Left-right panning": "pan"},
            lambda v: owner.tune(engine=v),
        )
        self.path = ChoiceField(
            body,
            "Path",
            "The route the sound takes around you.",
            {
                "Circle": "circle",
                "Front arc": "arc",
                "Figure-8": "figure8",
                "Wander": "wander",
            },
            lambda v: owner.tune(path=v),
        )
        self.direction = ChoiceField(
            body,
            "Direction",
            "Which way it turns.",
            {"Clockwise": "clockwise", "Counter-clockwise": "counterclockwise"},
            lambda v: owner.tune(direction=v),
        )
        self.bass = SliderField(
            body,
            "Bass centered below",
            "With 'Keep bass centered' on: sounds below this pitch stay in the "
            "middle. 120 Hz suits most music.",
            (40, 250, 21),
            lambda v: f"{v:.0f} Hz",
            lambda v: owner.tune(bass_hz=float(round(v / 10) * 10)),
        )
        self.height = SliderField(
            body,
            "Height",
            HEIGHT_HELP,
            (0, 1, 20),
            lambda v: f"{v:.2f}",
            lambda v: owner.tune(elevation=round(v, 2)),
        )
        self.fade = SliderField(
            body,
            "Ease in and out",
            "The movement grows in at the start and settles at the end. 3 s is "
            "recommended; 0 turns it off.",
            (0, 30, 60),
            lambda v: f"{v:g} s",
            lambda v: owner.tune(fade_seconds=round(v * 2) / 2),
        )
        self.beat = SwitchField(
            body,
            "Spin in time with the beat",
            "Makes one circle last whole bars of the song. Great for dance and pop.",
            lambda on: owner.tune(beat_sync=on),
        )
        self.bpm = EntryField(
            body,
            "Tempo (optional)",
            "Leave empty to let Audio8D find the tempo.",
            "e.g. 128",
            lambda text: owner.typed("bpm_text", text),
            width=120,
        )
        self.speed_curve = EntryField(
            body,
            "Speed over time",
            "Optional: change the spin during the song, e.g. 0=10, 1:00=6.",
            "e.g. 0=10, 1:00=6, 2:30=10",
            lambda text: owner.typed("speed_curve_text", text),
            width=300,
        )
        self.amount_curve = EntryField(
            body,
            "Movement over time",
            "Optional: change how far it moves during the song, e.g. 0=0.5, 1:00=0.95.",
            "e.g. 0=0.5, 1:00=0.95",
            lambda text: owner.typed("intensity_curve_text", text),
            width=300,
        )
        self.speakers = SwitchField(
            body,
            "Safe for speakers too",
            "Gentler left-right movement that also sounds right on speakers and in "
            "cars.",
            lambda on: owner.tune(**{SPEAKERS: on}),
        )
        widgets = (
            self.movement,
            self.spin,
            self.room,
            self.engine,
            self.path,
            self.direction,
            self.bass,
            self.height,
            self.fade,
            self.beat,
            self.bpm,
            self.speed_curve,
            self.amount_curve,
            self.speakers,
        )
        for row, widget in enumerate(widgets):
            widget.grid(row=row, column=0, sticky="ew", pady=3)

    def show(self, cfg: EffectConfig, speakers: bool, texts: tuple[str, ...]) -> None:
        """Put one set of sound values into the controls."""
        self.movement.set(cfg.intensity)
        self.spin.set(cfg.rotation_seconds)
        self.room.set(cfg.ambience)
        self.engine.set(cfg.engine)
        self.path.set(cfg.path)
        self.direction.set(cfg.direction)
        self.bass.set(cfg.bass_hz or 120.0)
        self.bass.enable(bool(cfg.bass_hz))
        self.height.set(cfg.elevation)
        self.fade.set(cfg.fade_seconds)
        self.beat.set(cfg.beat_sync)
        self.speakers.set(speakers)
        for field, text in zip(
            (self.bpm, self.speed_curve, self.amount_curve), texts, strict=True
        ):
            # Never overwrite a box while someone is typing in it
            focused = str(field.focus_get() or "").startswith(str(field.entry))
            if field.entry.get() != text and not focused:
                field.set(text)
        speed_curve = bool(texts[1].strip())
        self.spin.enable(not speed_curve)
        self.spin.explain(
            "'Speed over time' is in charge of the speed now."
            if speed_curve
            else SPIN_HELP
        )
        self.movement.enable(not texts[2].strip())
        panning = cfg.engine == "pan" or speakers
        self.height.enable(not panning)
        self.height.explain(
            "Height needs the 3D engine (not panning or 'Safe for speakers')."
            if panning
            else HEIGHT_HELP
        )
        self.engine.enable(not speakers)


# A holder of controls: show() is its one job, so it has few methods by design
class SongOutput:  # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """A song's own file settings, made the first time that part is opened."""

    def __init__(self, body: ctk.CTkFrame, owner: "CustomizeDialog") -> None:
        """Make the controls inside the section's body."""
        self.format = MenuField(
            body,
            "Output format",
            "",
            FORMAT_CHOICES,  # type: ignore[arg-type]
            lambda v: owner.file(output_format=v),
        )
        self.quality = ChoiceField(
            body,
            "Quality",
            "High keeps the most detail. Exact bitrates: Output, More output options.",
            QUALITY_CHOICES,  # type: ignore[arg-type]
            lambda v: owner.file(bitrate=v),
        )
        self.loudness = ChoiceField(
            body,
            "Loudness",
            "",
            SONG_LOUDNESS,  # type: ignore[arg-type]
            owner.song_loudness,
        )
        self.start, self.end = trim_fields(body, owner.trim)
        self.cover = SwitchField(
            body,
            "Keep the album picture",
            "Copies the cover art into the new file.",
            lambda on: owner.file(keep_cover=on),
        )
        self.title = SwitchField(
            body,
            "Add ' (8D)' to the song title",
            "So your music app lists the 8D version as its own track.",
            lambda on: owner.file(tag_title=on),
        )
        widgets = (
            self.format,
            self.quality,
            self.loudness,
            self.start,
            self.end,
            self.cover,
            self.title,
        )
        for row, widget in enumerate(widgets):
            widget.grid(row=row, column=0, sticky="ew", pady=3)

    def show(self, settings: GuiSettings, song: Path) -> None:
        """Put the song's file settings into the controls."""
        kind = str(file_value(settings, song, "output_format"))
        self.format.set(kind)
        lossless = kind in ("flac", "wav")
        if not lossless:
            self.quality.options = quality_choices(kind)  # type: ignore[assignment]
        self.quality.set(file_value(settings, song, "bitrate"))
        self.quality.enable(not lossless)
        self.quality.explain(
            f"{kind.upper()} is lossless, so there is no quality to choose."
            if lossless
            else "High keeps the most detail. Exact bitrates: Output, More output "
            "options."
        )
        match = bool(file_value(settings, song, "match_loudness"))
        target = file_value(settings, song, "loudness_target")
        chosen = "match" if match else target
        self.loudness.set(chosen)
        words: dict[object, str] = {
            "match": "Each new song is as loud as its original.",
            None: "No change: 8D songs are often quieter than your other music.",
            -14.0: "About as loud as Spotify and YouTube (-14 LUFS).",
        }
        self.loudness.explain(words.get(chosen, f"Set elsewhere: {target} LUFS."))
        for field, key in ((self.start, "trim_start"), (self.end, "trim_end")):
            text = str(file_value(settings, song, key))
            focused = str(field.focus_get() or "").startswith(str(field.entry))
            if field.entry.get() != text and not focused:
                field.set(text)
        can_cover = kind in {"mp3", "flac", "m4a"}
        self.cover.set(bool(file_value(settings, song, "keep_cover")) and can_cover)
        self.cover.enable(can_cover)
        self.title.set(bool(file_value(settings, song, "tag_title")))


# The dialog keeps a reference to every control it updates
class CustomizeDialog(Modal):  # pylint: disable=too-many-instance-attributes
    """Customize the sound of one song, several songs, or the default."""

    def __init__(self, app: "Audio8DApp") -> None:
        """Made once and reused; open() fills it for the songs chosen."""
        super().__init__(app, "Customize", (880, 760))
        self.app = app
        self.songs: list[Path] = []
        self.changes = Changes()
        # The saved style being edited, and its sound as the starting point
        self.style_name: str | None = None
        self.base: GuiSettings | None = None
        self.advanced: AdvancedSound | None = None
        self.output: SongOutput | None = None
        self._build_body()
        self._build_footer()

    # ------------------------------------------------------------ building

    def _build_body(self) -> None:
        """The simple choices first, then the folded parts."""
        body = self.body
        top = ctk.CTkFrame(body, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        top.grid_columnconfigure(1, weight=1)
        self.badge = Badge(top, "Default", "neutral")
        self.badge.grid(row=0, column=0, sticky="w")
        self.scope = hint(top, "", INK, margin=200, size=13)
        self.scope.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        self.name_field = EntryField(
            top,
            "Name",
            "Renaming keeps every song that uses this style on it.",
            "e.g. Sunset Drive",
            self._name_typed,
            width=260,
        )
        self.name_field.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.name_field.grid_remove()
        ctk.CTkLabel(body, text="Sound", font=font(15, "bold"), anchor="w").grid(
            row=1, column=0, sticky="ew", padx=16, pady=(10, 0)
        )
        self.style = MenuField(
            body,
            "Style",
            "The ready-made sound the choices below start from.",
            {},
            self._style_picked,
        )
        self.style.grid(row=2, column=0, sticky="ew", padx=6, pady=3)
        self.levels: dict[str, ChoiceField] = {}
        for row, level in enumerate(LEVELS, start=3):
            field = ChoiceField(
                body,
                level.label,
                level.help,
                dict(level.choices),  # type: ignore[arg-type]
                lambda value, lv=level: self.tune(**{lv.field: value}),
            )
            field.grid(row=row, column=0, sticky="ew", padx=6, pady=3)
            self.levels[level.key] = field
        ctk.CTkLabel(body, text="Optional", font=font(15, "bold"), anchor="w").grid(
            row=6, column=0, sticky="ew", padx=16, pady=(12, 0)
        )
        self.bass_on = SwitchField(
            body,
            "Keep bass centered",
            "Recommended: the beat stays solid in the middle, like a studio mix.",
            lambda on: self.tune(bass_hz=120.0 if on else 0.0),
        )
        self.bass_on.grid(row=7, column=0, sticky="ew", padx=6, pady=3)
        self.singer = SwitchField(
            body,
            "Keep the singer in the middle (add-on)",
            SINGER_MISSING,
            lambda on: self.tune(vocals="center" if on else "move"),
        )
        self.singer.grid(row=8, column=0, sticky="ew", padx=6, pady=3)
        self.singer_setup = button(
            self.singer,
            "guide",
            "About the add-on…",
            self._open_addon,
            kind="quiet",
            width=190,
            height=28,
        )
        self.singer_setup.grid(row=3, column=0, sticky="w", padx=(50, 0), pady=(0, 4))
        self.output_part = Section(
            body,
            "Save this song differently",
            "Its own file type, quality, loudness or part of the song. Usually the "
            "Output step's settings are right for every song.",
            build=self._fill_output,
        )
        self.output_part.grid(row=9, column=0, sticky="ew", padx=6, pady=(12, 0))
        self.advanced_part = Section(
            body,
            "Advanced",
            "The exact values behind the choices above, plus path, height, beat "
            "sync and more. You never need these.",
            build=self._fill_advanced,
        )
        self.advanced_part.grid(row=10, column=0, sticky="ew", padx=6, pady=(12, 12))

    def _build_footer(self) -> None:
        """Preview on the left; Reset to default, Cancel and Apply on the right."""
        footer = self.footer
        self.preview_button = button(
            footer,
            "headphones",
            "Preview",
            self._preview,
            width=170,
            height=34,
            tooltip="Listen with these changes before applying them; nothing is kept",
        )
        self.preview_button.grid(row=0, column=0, sticky="w")
        # A fixed wrap: the footer's width follows its buttons, not the text
        self.note = hint(footer, "", wrap=self.size[0] - 60)
        self.note.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        self.reset_button = button(
            footer,
            "clear",
            "Reset to default",
            self._reset,
            width=180,
            height=34,
            tooltip="Remove this song's own settings: it follows the defaults again",
        )
        self.reset_button.grid(row=0, column=1, padx=(8, 0))
        button(footer, "", "Cancel", self.cancel, width=110, height=34).grid(
            row=0, column=2, padx=(8, 0)
        )
        self.apply_button = button(
            footer, "check", "Apply", self.apply, kind="primary", width=130, height=34
        )
        self.apply_button.grid(row=0, column=3, padx=(8, 0))
        self.apply_text = str(self.apply_button.cget("text"))

    def _fill_advanced(self, body: ctk.CTkFrame) -> None:
        """Make the precise controls (the first time Advanced opens)."""
        self.advanced = AdvancedSound(body, self)
        self.refresh()

    def _fill_output(self, body: ctk.CTkFrame) -> None:
        """Make the song's file controls (the first time that part opens)."""
        self.output = SongOutput(body, self)
        self.refresh()

    # ------------------------------------------------------------ opening

    def open(self, songs: list[Path]) -> None:
        """Customize these songs (none: the default for every song)."""
        self._leave_style_mode()
        self.songs = list(songs)
        self.changes = Changes()
        count = len(self.songs)
        if count == 1:
            title = f"Customize “{self.songs[0].stem}”"
        elif count:
            title = f"Customize {count} songs"
        else:
            title = "Customize the default sound"
        self.title(title)
        self.heading.configure(text=title)
        self.subheading.configure(text=self._scope_words())
        # A song's own file settings only make sense for songs
        if self.songs:
            self.output_part.grid()
            self.reset_button.grid()
        else:
            self.output_part.grid_remove()
            self.reset_button.grid_remove()
        self.body._parent_canvas.yview_moveto(0)  # pylint: disable=protected-access
        self.refresh()
        self.show_preview()
        self.show_modal(self.style.menu)

    def open_style(self, name: str) -> None:
        """Edit one of your saved styles: its sound and its name, saved back to it."""
        app = self.app
        self.songs = []
        self.changes = Changes()
        self.style_name = name
        base = draft(app.settings, [], app.presets, Changes())
        base.apply_style(app.presets[name])
        # A style is only the sound: the Output step's choices never block saving it
        base.speakers = False
        base.loudness_is_custom = False
        self.base = base
        title = f"Edit your style “{name}”"
        self.title(title)
        self.heading.configure(text=title)
        self.subheading.configure(
            text="Change the sound or the name, then Save changes. Songs that use "
            "this style get the new sound."
        )
        self.name_field.set(name)
        self.name_field.explain("Renaming keeps every song that uses this style on it.")
        self.name_field.grid()
        self.style.grid_remove()
        self.output_part.grid_remove()
        self.reset_button.grid_remove()
        self.apply_button.configure(
            text=self.apply_text.replace("Apply", "Save changes")
        )
        self.body._parent_canvas.yview_moveto(0)  # pylint: disable=protected-access
        self.refresh()
        self.show_preview()
        self.show_modal(self.name_field.entry)

    def _leave_style_mode(self) -> None:
        """Back to customizing songs or the default after editing a style."""
        if self.style_name is None:
            return
        self.style_name = None
        self.base = None
        self.name_field.grid_remove()
        self.style.grid()
        self.apply_button.configure(text=self.apply_text)

    def _new_name(self) -> tuple[str | None, str | None]:
        """(the style's name after saving, None) or (None, why the typed name fails)."""
        return check_name(self.app, self.name_field.entry.get(), self.style_name)

    def _name_typed(self, _text: str) -> str | None:
        """The name box changed: say why it can't be used, or what it becomes."""
        name, problem = self._new_name()
        if name is not None and name != self.style_name:
            self.name_field.explain(f"It will be saved as {name}.", SUCCESS)
        self._show_state(self._safe_draft(), None)
        return problem

    def _scope_words(self) -> str:
        """Exactly which songs Apply changes, in one line."""
        count = len(self.songs)
        if not count:
            return (
                "Editing defaults for all songs. Songs you customized keep their own "
                "settings."
            )
        if count == 1:
            return "Editing only this song. Every other song keeps its settings."
        names = ", ".join(song.stem for song in self.songs[:3])
        more = f" and {count - 3} more" if count > 3 else ""
        return (
            f"Editing {count} songs ({names}{more}). Only what you change here is "
            "applied to all of them; the rest of each song's settings stay."
        )

    # ------------------------------------------------------------ changing

    def _draft(self) -> GuiSettings:
        """The settings as they would be after Apply (never the real ones)."""
        base = self.base or self.app.settings
        return draft(base, self.songs, self.app.presets, self.changes)

    def _style_picked(self, name: object) -> None:
        """Another style: the choices below start again from its sound."""
        self.changes.style = str(name)
        self.changes.sound.clear()
        self.changes.texts.clear()
        self.refresh()

    def tune(self, **knobs: object) -> None:
        """A sound choice changed (kept in the draft until Apply)."""
        self.changes.sound.update(knobs)
        self.refresh()

    def typed(self, key: str, text: str) -> str | None:
        """A typed tempo or curve; returns why it can't be used, or None."""
        problem = problem_of(lambda: typed_sound(key, text))
        before = self.changes.texts.get(key)
        self.changes.texts[key] = text
        # Values out of range only show up once the settings are put together
        problem = problem or problem_of(self._check_draft)
        if problem:
            if before is None:
                self.changes.texts.pop(key, None)
            else:
                self.changes.texts[key] = before
            return gui_words(problem)
        self.refresh()
        return None

    def _check_draft(self) -> None:
        """Raise when the draft can't be used for every song it covers."""
        shown = self._draft()
        config_for(shown)
        for song in self.songs:
            song_config(shown, song, self.app.presets)

    def file(self, **values: object) -> None:
        """One of the song's own file settings changed."""
        self.changes.files.update(values)
        self.refresh()

    def song_loudness(self, value: object) -> None:
        """The song's own loudness."""
        if value == "match":
            self.file(match_loudness=True, loudness_target=None)
        else:
            self.file(match_loudness=False, loudness_target=value)

    def trim(self, key: str, text: str) -> str | None:
        """A trim time for the song; returns why it can't be used, or None."""
        problem = typed_time_problem(text)
        if problem:
            return problem
        self.changes.files[key] = text
        self.refresh()
        return None

    # ------------------------------------------------------------ showing

    def refresh(self) -> None:
        """Show the draft: every control, the badge, and whether Apply can work."""
        app = self.app
        try:
            shown = self._draft()
            song = self.songs[0] if self.songs else None
            cfg, speakers = sound_of(shown, song, app.presets)
            problem = None
        except Audio8DError as exc:
            shown, cfg, speakers = app.settings, app.settings.sound, False
            song = self.songs[0] if self.songs else None
            problem = gui_words(str(exc))
        self._show_style(shown)
        for level in LEVELS:
            self._show_level(level, getattr(cfg, level.field))
        self.bass_on.set(bool(cfg.bass_hz))
        ready = app.singer_ready()
        self.singer.set(cfg.vocals == "center")
        # A song that already has it on can always switch it off again
        self.singer.enable(ready or cfg.vocals == "center")
        self.singer.explain(SINGER_READY if ready else SINGER_MISSING)
        if ready:
            self.singer_setup.grid_remove()
        else:
            self.singer_setup.grid()
        if self.advanced is not None:
            self.advanced.show(cfg, speakers, self._texts(shown, cfg, song))
        if self.output is not None and song is not None:
            self.output.show(shown, song)
        self._show_state(shown, problem)

    def _show_style(self, shown: GuiSettings) -> None:
        """The style list, with the default style marked for songs."""
        app = self.app
        default = shown.style
        options = {
            preset.label
            + (" (default)" if self.songs and name == default else ""): name
            for name, preset in app.presets.items()
        }
        self.style.set_options(options)  # type: ignore[arg-type]
        style = shown.song_styles.get(self.songs[0], default) if self.songs else default
        self.style.set(style)

    def _show_level(self, level: SoundLevel, value: float) -> None:
        """One friendly choice; an in-between value is said in words."""
        field = self.levels[level.key]
        field.set(value)
        word = level.word_for(value)
        if word is None:
            field.explain(
                f"{level.help} This style uses its own value, {level.between(value)} "
                "(exact value under Advanced).",
                TEXT_DIM,
            )
        else:
            field.explain(level.help)

    @staticmethod
    def _texts(
        shown: GuiSettings, cfg: EffectConfig, song: Path | None
    ) -> tuple[str, ...]:
        """The typed tempo and curves as the Advanced boxes show them."""
        if song is None:
            return (shown.bpm_text, shown.speed_curve_text, shown.intensity_curve_text)
        return (
            f"{cfg.bpm:g}" if cfg.bpm else "",
            format_keyframes(cfg.speed_curve),
            format_keyframes(cfg.intensity_curve),
        )

    def _show_state(self, shown: GuiSettings, problem: str | None) -> None:
        """Default or Custom, what Apply will do, and any problem."""
        if self.style_name is not None:
            self._show_style_state(problem)
            return
        if self.songs:
            custom = any(is_custom(shown, song) for song in self.songs)
            was = any(is_custom(self.app.settings, song) for song in self.songs)
            self.badge.show(
                "Custom" if custom else "Default", "accent" if custom else "neutral"
            )
            set_changed(
                self.scope,
                text="This song has its own settings."
                if custom and len(self.songs) == 1
                else "Has its own settings."
                if custom
                else "Follows the default settings.",
            )
            set_changed(self.reset_button, state="normal" if was else "disabled")
        else:
            self.badge.show("Defaults for all songs", "neutral")
            set_changed(self.scope, text="Every song that isn't customized uses these.")
        if problem:
            set_changed(
                self.note, text=f"Can't apply yet: {problem}", text_color=DANGER
            )
            set_changed(self.apply_button, state="disabled")
            return
        set_changed(self.apply_button, state="normal" if self.changes else "disabled")
        text, _playing = self.app.trial_words()
        if text:
            set_changed(self.note, text=text, text_color=INK)
        elif self.changes:
            set_changed(
                self.note,
                text="Changed, not applied yet. Apply keeps it; Cancel forgets it.",
                text_color=SUCCESS,
            )
        else:
            set_changed(
                self.note,
                text="Nothing changed yet. Preview lets you listen first.",
                text_color=TEXT_DIM,
            )

    def _show_style_state(self, problem: str | None) -> None:
        """Editing a saved style: whether Save changes can work, and why not."""
        self.badge.show("Your style", "accent")
        set_changed(self.scope, text="Save changes updates this saved style.")
        name, name_problem = self._new_name()
        renamed = name is not None and name != self.style_name
        problem = problem or name_problem
        if problem:
            set_changed(self.note, text=f"Can't save yet: {problem}", text_color=DANGER)
            set_changed(self.apply_button, state="disabled")
            return
        changed = bool(self.changes) or renamed
        set_changed(self.apply_button, state="normal" if changed else "disabled")
        text, _playing = self.app.trial_words()
        set_changed(
            self.note,
            text=text
            or (
                "Changed, not saved yet. Cancel keeps the style as it was."
                if changed
                else "Nothing changed yet. Preview lets you listen first."
            ),
            text_color=INK if text else SUCCESS if changed else TEXT_DIM,
        )

    def _save_style(self) -> None:
        """Save the edited sound (and any new name) back to the same style."""
        old = self.style_name
        assert old is not None
        name, problem = self._new_name()
        config = None
        try:
            # The speakers switch is a separate choice, never part of a style
            config = config_for(self._draft(), with_speakers=False)
        except Audio8DError as exc:
            problem = problem or gui_words(str(exc))
        if name is None or config is None or problem:
            set_changed(self.note, text=f"Can't save: {problem}", text_color=DANGER)
            return

        def complain(why: str) -> None:
            set_changed(self.note, text=f"Can't save: {why}", text_color=DANGER)

        summary = self.app.presets[old].summary
        checked = checked_style(self.app, config, summary, complain)
        if checked is None:
            return
        app = self.app
        # The default follows the edit when it was using this style unchanged
        follows = app.settings.style == old and not app.settings.differs_from(
            app.presets[old]
        )
        try:
            saved = update_user_preset(
                old, checked, new_name=name if name != old else None
            )
        except Audio8DError as exc:
            complain(gui_words(str(exc)))
            return
        self.hide()
        app.reload_styles(renamed=(old, saved) if saved != old else None)
        if follows:
            app.settings.apply_style(app.presets[saved])
            app.settings_changed()
        Toast(app, f"Saved your style '{saved}'", "ok")

    def show_preview(self) -> None:
        """The Preview button follows the preview: Preview, Preparing… or Stop."""
        song = self._preview_song()
        if song is None:
            set_changed(self.preview_button, state="disabled")
            return
        set_changed(
            self.preview_button,
            state="normal",
            # The button has its own headphones icon, so the words' symbol goes
            text="  " + self.app.preview_words(song).split(" ", 1)[1],
        )
        self._show_state(self._safe_draft(), None)

    def _safe_draft(self) -> GuiSettings:
        """The draft, or the real settings while the draft has a problem."""
        try:
            return self._draft()
        except Audio8DError:
            return self.app.settings

    # ------------------------------------------------------------ actions

    def _preview_song(self) -> Path | None:
        """The song the preview plays: the first being customized, else the chosen."""
        if self.style_name is not None:
            return self.app.focus_song()
        return self.songs[0] if self.songs else self.app.focus_song()

    def _preview(self) -> None:
        """Listen to the draft (Preview), or stop it (Preparing… / Stop)."""
        song = self._preview_song()
        if song is None:
            return
        state, _share = self.app.preview_state(song)
        if state in ("making", "playing"):
            self.app.preview_song(song)
            return
        try:
            if self.style_name is not None:
                # Heard with the Output step's file settings, like Change style
                sound = config_for(self._draft(), with_speakers=False)
                self.app.try_style(sound, self.style_name)
                self.show_preview()
                return
            config = self._draft_config(song)
        except Audio8DError as exc:
            set_changed(self.note, text=gui_words(str(exc)), text_color=DANGER)
            return
        self.app.try_config(song, config, "your changes")
        self.show_preview()

    def _draft_config(self, song: Path) -> EffectConfig:
        """Exactly what the song would be made with after Apply."""
        return song_config(self._draft(), song, self.app.presets)

    def _reset(self) -> None:
        """'Reset to default': the songs lose their own settings, then close."""
        count = reset_songs(self.app.settings, self.songs)
        self.hide()
        self.app.settings_changed(
            f"“{self.songs[0].stem}” follows the defaults again"
            if len(self.songs) == 1
            else f"{count} songs follow the defaults again"
        )

    def _open_addon(self) -> None:
        """Close (changing nothing) and show the add-on in Settings."""
        self.cancel()
        self.app.show_page("settings", focus="singer")

    def apply(self) -> None:
        """Keep the changes for exactly these songs (or the default), then close."""
        if self.style_name is not None:
            self._save_style()
            return
        if not self.changes:
            self.hide()
            return
        try:
            customize(self.app.settings, self.songs, self.app.presets, self.changes)
        except Audio8DError as exc:
            set_changed(
                self.note, text=f"Can't apply: {gui_words(str(exc))}", text_color=DANGER
            )
            return
        self.hide()
        count = len(self.songs)
        self.app.settings_changed(
            "Default sound changed"
            if not count
            else f"“{self.songs[0].stem}” now has custom settings"
            if count == 1
            else f"{count} songs customized"
        )

    def hide(self) -> None:
        """Close; a preview of changes that were not applied stops too."""
        song = self._preview_song()
        if song is not None and song in self.app.trials:
            state, _share = self.app.preview_state(song)
            if state in ("making", "playing"):
                self.app.preview_song(song)
        super().hide()
