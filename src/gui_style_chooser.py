# Developed by ::> Gehan Fernando
"""'Choose sound style': compact style cards, one selected, then Apply or Cancel.

Clicking a card (or moving with the arrow keys) only selects it; nothing is
changed until Apply. Preview plays the selected song with a style without
applying it. The dialog is made once and reused, so it opens instantly.
"""

import tkinter as tk
from collections.abc import Callable
from typing import TYPE_CHECKING

import customtkinter as ctk

from .core.presets import Preset
from .core.style_guide import guide_for, is_recommended
from .gui_modal import Modal
from .gui_widgets import (
    ACCENT,
    ACCENT_TEXT,
    BORDER,
    CONTROL_HEIGHT,
    INK,
    PANEL_RADIUS,
    SUCCESS,
    SURFACE,
    TEXT_DIM,
    TOOL_HEIGHT,
    button,
    hint,
    shade,
)

if TYPE_CHECKING:
    from .gui_app import Audio8DApp

# Cards are laid out in this many columns
COLUMNS = 2


class _StyleCard(ctk.CTkFrame):
    """One style: its name, what it sounds like, what it's good for, Preview, Apply."""

    def __init__(self, master: tk.Misc, chooser: "StyleChooser", preset: Preset):
        """Draw the card; clicking anywhere on it selects it."""
        super().__init__(
            master, fg_color=SURFACE, corner_radius=PANEL_RADIUS, border_width=1,
            border_color=BORDER,
        )  # fmt: skip
        self.preset = preset
        self.chooser = chooser
        # What the card shows now, so opening the dialog redraws only what changed
        self.shown: tuple[bool, bool] | None = None
        guide = guide_for(preset)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        # Plain Tk: one window per widget, not two, so opening and re-theming is quicker
        back = shade(SURFACE)
        head = tk.Frame(self, bg=back)
        head.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 0))
        self.name = self._label(head, preset.label, 15, INK, "bold")
        self.name.pack(side="left")
        extra = "Recommended" if is_recommended(preset) else ""
        extra = "Your style" if preset.custom else extra
        if extra:
            self._label(head, extra, 11, ACCENT_TEXT, "bold").pack(
                side="left", padx=(8, 0)
            )
        # Words, not only colour, say which card is selected and which is in use
        self.marks = self._label(head, "", 11, SUCCESS, "bold")
        self.marks.pack(side="right")
        self.purpose = self._label(self, guide.purpose, 13, INK, wrap=330)
        self.purpose.grid(row=1, column=0, sticky="ew", padx=14, pady=(4, 0))
        self.good = self._label(
            self, f"Good for: {guide.best_for}", 12, TEXT_DIM, wrap=330
        )
        self.good.grid(row=2, column=0, sticky="new", padx=14, pady=(2, 0))
        actions = tk.Frame(self, bg=back)
        actions.grid(row=3, column=0, sticky="w", padx=10, pady=(8, 12))
        self.preview = button(
            actions,
            "headphones",
            "Preview",
            lambda: chooser.preview(preset),
            width=120,
            height=TOOL_HEIGHT,
            tooltip="Listen to the selected song with this style; nothing is changed",
        )
        self.preview.pack(side="left", padx=(0, 6))
        button(
            actions,
            "check",
            "Apply",
            lambda: chooser.pick_and_apply(preset.name),
            kind="accent",
            width=100,
            height=TOOL_HEIGHT,
            tooltip="Use this style for every song that follows the default",
        ).pack(side="left")
        # The words wrap to the card's own width, whatever the size setting
        self.bind("<Configure>", self._wrap, add=True)
        # Clicking anywhere on the card selects it (its frames and its words)
        for frame in (self, head):
            frame.bind("<Button-1>", lambda _e: chooser.select(preset.name))
        for label in (self.name, self.purpose, self.good, self.marks):
            label.bind("<Button-1>", lambda _e: chooser.select(preset.name))

    def _wrap(self, event: tk.Event) -> None:
        """Wrap the description lines inside the card's padding."""
        room = max(120, event.width - round(32 * self._get_widget_scaling()))
        for label in (self.purpose, self.good):
            if int(label.cget("wraplength")) != room:
                label.configure(wraplength=room)

    @staticmethod
    def _label(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        master: tk.Misc,
        text: str,
        size: int,
        color: tuple[str, str],
        weight: str = "normal",
        wrap: int = 0,
    ) -> tk.Label:
        """A plain Tk label in the card's colours and the window's font."""
        scale = ctk.ScalingTracker.get_widget_scaling(master)
        return tk.Label(
            master,
            text=text,
            font=("Segoe UI", -round(size * scale), weight),
            fg=shade(color),
            bg=shade(SURFACE),
            anchor="w",
            justify="left",
            wraplength=round(wrap * scale),
        )

    def mark(self, selected: bool, current: bool) -> None:
        """Show whether this card is selected and whether it is the style in use."""
        if self.shown == (selected, current):
            return
        self.shown = (selected, current)
        self.configure(
            border_color=ACCENT if selected else BORDER,
            border_width=3 if selected else 1,
        )
        words = [w for w, on in (("● Selected", selected), ("✓ In use", current)) if on]
        self.marks.configure(
            text="   ".join(words), fg=shade(ACCENT_TEXT if selected else SUCCESS)
        )


class StyleChooser(Modal):
    """Choose the default style from compact cards; Apply or Cancel."""

    def __init__(self, app: "Audio8DApp") -> None:
        """Made once; open() shows it."""
        super().__init__(app, "Choose sound style", (900, 700))
        self.app = app
        self.cards: dict[str, _StyleCard] = {}
        self.built_for: tuple = ()
        self.selected = ""
        self.current = ""
        self.on_apply: Callable[[str], None] = lambda _name: None
        self.note = hint(self.footer, "", margin=420)
        self.note.grid(row=0, column=0, sticky="ew")
        self.stop_preview = button(
            self.footer,
            "stop",
            "Stop",
            app.stop_playing,
            width=90,
            height=CONTROL_HEIGHT,
        )
        self.cancel_button = button(
            self.footer, "", "Cancel", self.cancel, width=110, height=CONTROL_HEIGHT
        )
        self.cancel_button.grid(row=0, column=2, padx=(8, 0))
        self.apply_button = button(
            self.footer, "check", "Apply", self.apply, kind="primary", width=130,
            height=CONTROL_HEIGHT,
        )  # fmt: skip
        self.apply_button.grid(row=0, column=3, padx=(8, 0))
        for key in ("<Left>", "<Up>"):
            self.bind(key, lambda _e: self._step(-1 if _e.keysym == "Left" else -2))
        for key in ("<Right>", "<Down>"):
            self.bind(key, lambda _e: self._step(1 if _e.keysym == "Right" else 2))

    def build_cards(self) -> None:
        """One card per style; remade only when the styles themselves changed."""
        # The theme and size are part of it: the cards' plain labels hold colours
        wanted = (
            ctk.get_appearance_mode(),
            ctk.ScalingTracker.get_widget_scaling(self),
            *(
                (name, preset.summary, preset.custom)
                for name, preset in self.app.presets.items()
            ),
        )
        if wanted == self.built_for:
            return
        self.built_for = wanted
        for card in self.cards.values():
            card.destroy()
        self.cards.clear()
        for column in range(COLUMNS):
            self.body.grid_columnconfigure(column, weight=1, uniform="cards")
        for index, preset in enumerate(self.app.presets.values()):
            card = _StyleCard(self.body, self, preset)
            card.grid(
                row=index // COLUMNS,
                column=index % COLUMNS,
                sticky="nsew",
                padx=6,
                pady=6,
            )
            self.cards[preset.name] = card

    def open(self, current: str, on_apply: Callable[[str], None]) -> None:
        """Show the dialog with the style in use selected."""
        self.build_cards()
        self.current = self.selected = current
        self.on_apply = on_apply
        self.subheading.configure(
            text="How your songs will sound. Pick a card, listen with Preview, then "
            "press Apply. Studio is a safe choice for most music."
        )
        self.show_preview()
        self._mark()
        self.show_modal(self.apply_button)

    def select(self, name: str) -> None:
        """Highlight one card (nothing is changed yet)."""
        self.selected = name
        self._mark()

    def _mark(self) -> None:
        """Every card shows whether it is selected and whether it is in use."""
        for name, card in self.cards.items():
            card.mark(name == self.selected, name == self.current)
        label = self.app.label(self.selected) if self.selected else ""
        self.apply_button.configure(
            state="normal" if self.selected else "disabled",
            text=f"  Apply {label}" if label else "  Apply",
        )

    def _step(self, move: int) -> None:
        """Arrow keys move the selection between the cards."""
        names = list(self.cards)
        if not names:
            return
        index = names.index(self.selected) if self.selected in names else 0
        self.select(names[max(0, min(len(names) - 1, index + move))])
        card = self.cards[self.selected]
        # Keep the selected card on screen while moving through them
        canvas = self.body._parent_canvas  # pylint: disable=protected-access
        top = canvas.bbox("all")[3] or 1
        canvas.yview_moveto(max(0.0, (card.winfo_y() - 20) / top))

    def pick_and_apply(self, name: str) -> None:
        """A card's own Apply: select it and apply at once."""
        self.select(name)
        self.apply()

    def apply(self) -> None:
        """Use the selected style, then close."""
        name = self.selected
        self.hide()
        if name:
            self.on_apply(name)

    def preview(self, preset: Preset) -> None:
        """Listen to the selected song with a style, without applying it."""
        self.select(preset.name)
        self.app.try_style(preset.config, preset.name)
        self.show_preview()

    def show_preview(self) -> None:
        """The footer says what is being previewed, with Stop while it plays."""
        text, playing = self.app.trial_words()
        self.note.configure(
            text=text or "Selecting a card changes nothing until you press Apply.",
            text_color=INK if text else TEXT_DIM,
        )
        if playing:
            self.stop_preview.grid(row=0, column=1, padx=(8, 0))
        else:
            self.stop_preview.grid_remove()
