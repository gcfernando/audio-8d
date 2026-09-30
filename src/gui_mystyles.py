# Developed by ::> Gehan Fernando
"""The 'Your styles' page: create, save, rename, share and delete your own styles.

The guided creator asks a few plain questions and turns the answers into
settings (style_creator.guided_config); every saved style then appears in
the style chooser next to the built-in ones, with a description of what it suits.
"""

import dataclasses
import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from typing import TYPE_CHECKING

import customtkinter as ctk

from . import hints
from .core.errors import Audio8DError
from .core.locations import presets_file
from .core.presets import Preset
from .core.settings import EffectConfig
from .core.style_files import FILE_SUFFIX as STYLE_FILE_SUFFIX
from .core.style_files import export_style, import_style, read_style_file
from .core.user_presets import (
    delete_user_preset,
    duplicate_user_preset,
    pascal_case,
    rename_user_preset,
    save_user_preset,
)
from .gui_dialogs import (
    Dialog,
    NameDialog,
    Toast,
)
from .gui_fields import (
    ChoiceField,
    EntryField,
)
from .gui_model import (
    config_for,
    gui_words,
)
from .gui_style_save import check_name, checked_style, taken_names
from .gui_widgets import (
    ACCENT_TEXT,
    DANGER,
    PANEL_RADIUS,
    SUCCESS,
    SURFACE_ALT,
    TEXT_DIM,
    TOOL_HEIGHT,
    WARNING,
    Card,
    Icons,
    Page,
    button,
    fit_width,
    flow,
    font,
    hint,
    mark_entry,
)
from .style_creator import (
    MOVEMENT_CHOICES,
    MUSIC_CHOICES,
    PLACE_CHOICES,
    ROOM_CHOICES,
    SPEED_CHOICES,
    StyleNote,
    guided_config,
    improve_answers,
    style_check,
    style_summary,
    suggested_answers,
    suggested_description,
    suggested_name,
)

if TYPE_CHECKING:
    from .gui_app import Audio8DApp


# How a style name should look, shown under every name box
NAME_HELP = (
    "Words that each start with a capital, with or without spaces: Sunset Drive or "
    "SunsetDrive. Type it any way you like: 'sunset drive' becomes Sunset Drive."
)
_LEVEL_COLOURS = {"error": DANGER, "warning": WARNING, "tip": TEXT_DIM}


# A page keeps a reference to every control it updates when the settings change
class YourStylesPage(Page):  # pylint: disable=too-many-instance-attributes
    """Create, save, rename, share and manage your own styles."""

    def __init__(self, master: tk.Misc, app: "Audio8DApp") -> None:
        """Build the page."""
        super().__init__(
            master,
            "",
            "Your styles",
            "Make a style of your own by answering a few questions. It then appears "
            "in Change style and Customize, like the built-in ones. Styles stay on "
            "this computer; export one to share it.",
        )
        self.app = app
        self.answers = suggested_answers("mixed")
        # Set once the name or description is typed, so suggestions stop replacing it
        self.name_typed = False
        self.summary_typed = False
        self.suggested = ("", "")
        self.notes: list[StyleNote] = []
        self._build_creator()

        save = Card(
            self,
            "Or save your current sound",
            "Saves the default sound as you customized it on step 2 as a style of "
            "its own (the file type and loudness are not part of a style).",
        )
        self.add(save, 3)
        self.name = EntryField(
            save.body,
            "Name",
            NAME_HELP,
            "e.g. Party Mix",
            lambda text: self._name_typed(self.name, text),
            width=260,
        )
        self.name.grid(row=0, column=0, sticky="ew", pady=4)
        self.summary = EntryField(
            save.body,
            "Description",
            "Optional: a few words to remind you what it's for.",
            "e.g. big figure-8 for parties",
            lambda _t: None,
            width=420,
        )
        self.summary.grid(row=1, column=0, sticky="ew", pady=4)
        button(
            save.body, "save", "Save style", self._save, kind="primary", width=150
        ).grid(row=2, column=0, sticky="w", pady=(10, 0))

        self.saved = Card(self, "Saved styles", f"Stored in {presets_file()}")
        self.add(self.saved, 4, (0, 28))
        self.refresh()

    # ------------------------------------------------------------ the creator

    def _build_creator(self) -> None:
        """The guided 'Create your own style' card."""
        card = Card(
            self,
            "Create your own style",
            "Answer a few questions; Audio8D turns them into settings, checks them "
            "and suggests a name. A style is only the sound; the file type and "
            "loudness are chosen on the Output step.",
        )
        self.add(card, 2)
        body = card.body
        self.q_music = ChoiceField(
            body,
            "Music",
            "What will you listen to? Strong beat: dance, pop, hip-hop. Calm: chill, "
            "acoustic, lo-fi. Big and loud: rock, EDM, film music. Talking: podcasts, "
            "audiobooks. Picking one fills in good answers below.",
            MUSIC_CHOICES,  # type: ignore[arg-type]
            self._music_picked,
        )
        self.q_movement = ChoiceField(
            body,
            "Movement",
            "How far the music travels around your head. Gentle is relaxing; "
            "Balanced suits most music (recommended); Strong goes right into each ear.",
            MOVEMENT_CHOICES,  # type: ignore[arg-type]
            lambda value: self._answer(movement=str(value)),
        )
        self.q_speed = ChoiceField(
            body,
            "Speed",
            "How quickly it goes around you. Slow: once every 12 s. Normal: every "
            "8 s (recommended). Fast: every 5 s. With the beat: follows the song.",
            SPEED_CHOICES,  # type: ignore[arg-type]
            lambda value: self._answer(speed=str(value)),
        )
        self.q_room = ChoiceField(
            body,
            "Space",
            "How big the room sounds. Dry is best for talking. Natural makes music "
            "feel around you (recommended). Spacious can blur voices.",
            ROOM_CHOICES,  # type: ignore[arg-type]
            lambda value: self._answer(room=str(value)),
        )
        self.q_place = ChoiceField(
            body,
            "Listen on",
            "3D sound is made for headphones. 'Speakers or a car too' makes a "
            "gentler version that sounds right everywhere.",
            PLACE_CHOICES,  # type: ignore[arg-type]
            lambda value: self._answer(place=str(value)),
        )
        self.new_name = EntryField(
            body,
            "Name",
            NAME_HELP,
            "e.g. Sunset Drive",
            self._new_name_typed,
            width=260,
        )
        self.new_summary = EntryField(
            body,
            "Description",
            "A few words so you remember what it's for. One is written for you; "
            "change it if you like.",
            "e.g. calm songs for late nights",
            self._new_summary_typed,
            width=460,
        )
        fields = (
            self.q_music,
            self.q_movement,
            self.q_speed,
            self.q_room,
            self.q_place,
            self.new_name,
            self.new_summary,
        )
        for row, widget in enumerate(fields):
            widget.grid(row=row, column=0, sticky="ew", pady=5)
        # Untinted like every other card; its heading sets the result apart
        result = ctk.CTkFrame(body, fg_color="transparent")
        result.grid(row=len(fields), column=0, sticky="ew", pady=(10, 4))
        result.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(result, text="Your style", font=font(13, "bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=6
        )
        self.result = ctk.CTkLabel(
            result, text="", font=font(12), anchor="w", justify="left"
        )
        self.result.grid(row=1, column=0, sticky="ew", padx=6, pady=(2, 0))
        self.checks = ctk.CTkFrame(body, fg_color="transparent")
        self.checks.grid(row=len(fields) + 1, column=0, sticky="ew")
        self.checks.grid_columnconfigure(0, weight=1)
        strip = ctk.CTkFrame(body, fg_color="transparent")
        strip.grid(row=len(fields) + 2, column=0, sticky="ew", pady=(10, 0))
        strip.grid_columnconfigure(1, weight=1)
        self.improve = button(
            strip,
            "check",
            "Improve it for me",
            self._improve,
            width=200,
            tooltip="Change the answers the quality check points out",
        )
        self.improve.grid(row=0, column=0, sticky="w")
        button(
            strip,
            "preview",
            "Try it",
            lambda: self.app.try_style(guided_config(self.answers)),
            width=130,
            tooltip="Preview the song selected on step 2 with this style; nothing "
            "is changed",
        ).grid(row=0, column=2, padx=8)
        button(
            strip, "save", "Save style", self._create, kind="primary", width=160
        ).grid(row=0, column=3)
        self._show_answers()

    def _music_picked(self, value: object) -> None:
        """A kind of music was picked: fill in good answers for it."""
        self.answers = suggested_answers(str(value))
        self._show_answers()

    def _answer(self, **answer: str) -> None:
        """One answer changed."""
        self.answers = dataclasses.replace(self.answers, **answer)
        self._show_creator()

    def _show_answers(self) -> None:
        """Show every answer, then what they make."""
        answers = self.answers
        for field, value in (
            (self.q_music, answers.music),
            (self.q_movement, answers.movement),
            (self.q_speed, answers.speed),
            (self.q_room, answers.room),
            (self.q_place, answers.place),
        ):
            field.set(value)
        self._show_creator()

    def _show_creator(self) -> None:
        """Refresh the suggested name and description, the summary and the check."""
        config = guided_config(self.answers)
        name = suggested_name(self.answers, self.taken())
        summary = suggested_description(self.answers)
        if not self.name_typed and self.new_name.entry.get() in ("", self.suggested[0]):
            self.new_name.set(name)
            self._name_typed(self.new_name, name)
        if not self.summary_typed:
            self.new_summary.set(summary)
        self.suggested = (name, summary)
        self.result.configure(text=style_summary(config))
        self.notes = style_check(config, self.new_summary.entry.get())
        for child in self.checks.winfo_children():
            child.destroy()
        if not self.notes:
            self.notes_line(
                "check", "Quality check: this style looks good.", SUCCESS, 0
            )
        for row, note in enumerate(self.notes):
            icon = {"error": "error", "warning": "warning"}.get(note.level, "info")
            self.notes_line(icon, note.text, _LEVEL_COLOURS[note.level], row)
        if any(note.fix for note in self.notes):
            self.improve.grid()
        else:
            self.improve.grid_remove()

    def notes_line(
        self, icon: str, text: str, colour: tuple[str, str], row: int
    ) -> None:
        """One line of the quality check."""
        line = ctk.CTkFrame(self.checks, fg_color="transparent")
        line.grid(row=row, column=0, sticky="ew", pady=2)
        line.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            line, text=Icons.glyph(icon), font=Icons.font(14), text_color=colour
        ).grid(row=0, column=0, padx=(0, 8))
        message = ctk.CTkLabel(
            line, text=text, font=font(12), text_color=colour, anchor="w",
            justify="left", wraplength=640,
        )  # fmt: skip
        message.grid(row=0, column=1, sticky="ew")
        fit_width(message, line, 40)

    def _new_name_typed(self, text: str) -> str | None:
        """The creator's name box."""
        self.name_typed = bool(text.strip()) and text != self.suggested[0]
        return self._name_typed(self.new_name, text)

    def _new_summary_typed(self, text: str) -> None:
        """The creator's description box (any text is fine, even none)."""
        self.summary_typed = text != self.suggested[1]
        self._show_creator()

    def _improve(self) -> None:
        """Follow the quality check's advice."""
        self.answers = improve_answers(self.answers, self.notes)
        self._show_answers()
        Toast(self.app, "Improved: the answers now follow the advice", "ok")

    def _create(self) -> None:
        """Save the style the answers make."""
        config = guided_config(self.answers)
        if self._store(self.new_name, config, self.new_summary.entry.get()):
            self.name_typed = self.summary_typed = False
            self.new_name.set("")
            self._show_creator()

    # ------------------------------------------------------------ saving

    def taken(self) -> list[str]:
        """The names of your saved styles."""
        return taken_names(self.app)

    def check_name(
        self, text: str, keep: str | None = None
    ) -> tuple[str | None, str | None]:
        """(the name it will get, None), or (None, why it can't be used)."""
        return check_name(self.app, text, keep)

    def _name_typed(self, field: EntryField, text: str) -> str | None:
        """A name box changed: say what it becomes, or why it can't be used."""
        if not text.strip():
            field.explain(NAME_HELP)
            return None
        name, problem = self.check_name(text)
        if name:
            field.explain(f"It will be saved as {name}.", SUCCESS)
        return problem

    def _save(self) -> None:
        """Save the current settings under the typed name."""
        try:
            config = config_for(self.app.settings)
        except Audio8DError as exc:
            self.name.explain(f"Fix the settings first: {gui_words(str(exc))}.", DANGER)
            return
        if self._store(self.name, config, self.summary.entry.get()):
            self.name.set("")
            self.summary.set("")
            self.name.explain(NAME_HELP)

    def _store(self, field: EntryField, config: EffectConfig, summary: str) -> bool:
        """Check a new style fully, offer to improve it, then save it."""
        name, problem = self.check_name(field.entry.get())
        if name is None:
            mark_entry(field.entry, True)
            field.explain(problem or "Type a name first.", DANGER)
            return False
        checked = checked_style(
            self.app, config, summary, lambda why: field.explain(why, DANGER)
        )
        if checked is None:
            return False
        config = checked
        try:
            saved = save_user_preset(
                name, config, based_on=self.app.settings.style, summary=summary
            )
        except Audio8DError as exc:
            field.explain(gui_words(str(exc)) + ".", DANGER)
            return False
        field.explain(
            f"Saved '{saved}'. It's now in Change style with the others.", SUCCESS
        )
        self.app.reload_styles(select=saved)
        Toast(self.app, f"Saved your style '{saved}'", "ok")
        return True

    # ------------------------------------------------------------ saved styles

    def refresh(self) -> None:
        """List the saved styles, each with what can be done with it."""
        body = self.saved.body
        for child in body.winfo_children():
            child.destroy()
        if self.app.styles_problem:
            problem = ctk.CTkLabel(
                body,
                text=f"Your saved styles can't be shown, because the styles file has "
                f"a mistake: {self.app.styles_problem}. Fix that line in "
                f"{presets_file()} (any text editor), or delete the file to start "
                "again. Built-in styles still work.",
                font=font(13),
                text_color=DANGER,
                anchor="w",
                justify="left",
                wraplength=700,
            )
            problem.grid(row=0, column=0, sticky="ew")
            fit_width(problem, body, 10)
            return
        top = ctk.CTkFrame(body, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        top.grid_columnconfigure(0, weight=1)
        mine = [p for p in self.app.presets.values() if p.custom]
        hint(
            top,
            f"{len(mine)} saved style{'s' if len(mine) != 1 else ''}."
            if mine
            else "No saved styles yet. Create one above, or import a style file.",
            margin=260,
        ).grid(row=0, column=0, sticky="ew")
        button(
            top,
            "open",
            "Import a style…",
            self._import,
            width=190,
            height=TOOL_HEIGHT,
            tooltip="Add a style from a file exported by Audio8D",
        ).grid(row=0, column=1, padx=(10, 0))
        for index, preset in enumerate(mine, start=1):
            self._saved_row(body, index, preset)

    def _saved_row(self, body: ctk.CTkFrame, index: int, preset: Preset) -> None:
        """One saved style: its name and description, then its buttons."""
        row = ctk.CTkFrame(body, fg_color=SURFACE_ALT, corner_radius=PANEL_RADIUS)
        row.grid(row=index, column=0, sticky="ew", pady=3)
        row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            row, text=Icons.glyph("star"), font=Icons.font(14), text_color=ACCENT_TEXT
        ).grid(row=0, column=0, padx=12, pady=(10, 0))
        title = ctk.CTkLabel(
            row,
            text=f"{preset.name}  ·  {preset.summary}",
            font=font(13),
            anchor="w",
            justify="left",
            wraplength=640,
        )
        title.grid(row=0, column=1, sticky="ew", pady=(10, 0), padx=(0, 12))
        fit_width(title, row, 60)
        actions = ctk.CTkFrame(row, fg_color="transparent")
        # Under the star as well, and on two lines when even that is too narrow
        actions.grid(row=1, column=0, columnspan=2, sticky="w", padx=12, pady=(6, 10))
        name = preset.name
        parts = [
            button(
                actions, icon, text, command, kind=kind, width=80, height=TOOL_HEIGHT
            )
            for icon, text, command, kind in (
                # Repeated on every row, so the lighter commit look, not a filled one
                ("check", "Use", lambda: self._use(name), "accent"),
                ("styles", "Edit…", lambda: self.app.edit_style(name), "outline"),
                ("save", "Rename…", lambda: self._rename(name), "outline"),
                ("add", "Duplicate…", lambda: self._duplicate(name), "outline"),
                ("open", "Export…", lambda: self._export(name), "outline"),
                ("delete", "Delete", lambda: self._delete(name), "outline"),
            )
        ]
        flow(actions, parts, gap=4, line_gap=4)

    def _failed(self, title: str, error: Audio8DError) -> None:
        """Explain a style operation that couldn't be done; nothing was changed."""
        fix = hints.fix_for(error)
        message = gui_words(str(error)) + "."
        if fix:
            message += f"\n\nWhat to do: {gui_words(fix)}"
        Dialog(
            self.app,
            title,
            message + "\n\nNothing was changed.",
            [("OK", "ok")],
            icon="error",
            color=DANGER,
        ).ask()

    def _free_name(self, stem: str) -> str:
        """stem, or stem2, stem3… whichever is not taken yet."""
        name, number = pascal_case(stem), 2
        while self.check_name(name)[1]:
            name, number = f"{pascal_case(stem)} {number}", number + 1
        return name

    def _rename(self, name: str) -> None:
        """Give a saved style a new name; songs that use it keep it."""
        new = NameDialog(
            self.app,
            "Rename this style",
            f"Choose a new name for '{name}'. Songs that use it keep using it.",
            name,
            lambda text: self.check_name(text, keep=name),
            "Rename",
        ).ask()
        if not new or new == name:
            return
        try:
            renamed = rename_user_preset(name, new)
        except Audio8DError as exc:
            self._failed("Can't rename this style", exc)
            return
        self.app.reload_styles(renamed=(name, renamed))
        Toast(self.app, f"Renamed '{name}' to '{renamed}'", "ok")

    def _duplicate(self, name: str) -> None:
        """Copy a saved style under a new name."""
        new = NameDialog(
            self.app,
            "Duplicate this style",
            f"The copy of '{name}' needs a name of its own.",
            self._free_name(f"{name} Copy"),
            self.check_name,
            "Duplicate",
        ).ask()
        if not new:
            return
        try:
            copy = duplicate_user_preset(name, new)
        except Audio8DError as exc:
            self._failed("Can't duplicate this style", exc)
            return
        self.app.reload_styles()
        Toast(self.app, f"Made '{copy}', a copy of '{name}'", "ok")

    def _use(self, name: str) -> None:
        """'Use': make a saved style the default, then show step 2."""
        self.app.choose_style(name)
        self.app.show_page("styles_step")

    def _export(self, name: str) -> None:
        """Save a style to a file, to keep or share."""
        chosen = filedialog.asksaveasfilename(
            title="Export a style",
            initialfile=f"{name}{STYLE_FILE_SUFFIX}",
            defaultextension=STYLE_FILE_SUFFIX,
            filetypes=[("Audio8D style", f"*{STYLE_FILE_SUFFIX}")],
        )
        if not chosen:
            return
        try:
            target = export_style(self.app.presets[name], Path(chosen))
        except Audio8DError as exc:
            self._failed("Can't export this style", exc)
            return
        Toast(self.app, f"Exported '{name}' to {target.name}", "ok")

    def _import(self) -> None:
        """Add a style from a file, after checking all of it and its new name."""
        chosen = filedialog.askopenfilename(
            title="Import a style",
            filetypes=[
                ("Audio8D style", f"*{STYLE_FILE_SUFFIX}"),
                ("All files", "*.*"),
            ],
        )
        if not chosen:
            return
        path = Path(chosen)
        try:
            style = read_style_file(path)
        except Audio8DError as exc:
            self._failed("Can't import this style", exc)
            return
        description = f" ({style.summary})" if style.summary else ""
        new = NameDialog(
            self.app,
            "Import a style",
            f"'{style.name}'{description} passed every check. Choose its name: it "
            "can't be the name of a style you already have.",
            pascal_case(style.name),
            self.check_name,
            "Import",
        ).ask()
        if not new:
            return
        try:
            imported = import_style(path, new)
        except Audio8DError as exc:
            self._failed("Can't import this style", exc)
            return
        self.app.reload_styles()
        Toast(self.app, f"Imported '{imported}'", "ok")

    def _delete(self, name: str) -> None:
        """Delete a saved style after asking."""
        answer = Dialog(
            self.app,
            "Delete this style?",
            f"'{name}' will be removed from your saved styles. Songs you made with it "
            "are not touched; songs on the list that use it go back to the style for "
            "all songs.",
            [("Cancel", "no"), ("Delete", "yes")],
            icon="delete",
            color=DANGER,
        ).ask()
        if answer == "yes":
            delete_user_preset(name)
            moved = self.app.reload_styles()
            songs = f"{moved} song{'s' if moved != 1 else ''}"
            extra = f"; {songs} now use the style for all songs" if moved else ""
            Toast(self.app, f"Deleted '{name}'{extra}", "ok")
