# Developed by ::> Gehan Fernando
"""The window's settings controls: sliders, choices, switches and text boxes.

Each one shows its name, the control and a short explanation that is always
visible, with a "Learn more" link for the longer story.
"""

import tkinter as tk
from collections.abc import Callable

import customtkinter as ctk

from .gui_widgets import (
    ACCENT,
    ACCENT_HOVER,
    ACCENT_SOFT,
    ACCENT_TEXT,
    CONTROL_HEIGHT,
    DANGER,
    FOCUS,
    INK,
    RADIUS,
    SURFACE,
    SURFACE_ALT,
    TEXT_DIM,
    TEXT_DISABLED,
    TOOL_HEIGHT,
    TOOL_WIDTH,
    WHITE,
    Tooltip,
    accessible_button,
    button,
    entry,
    font,
    hint,
    keyboard,
    mark_entry,
    set_changed,
)


class Field(ctk.CTkFrame):
    """One setting: name on the left, control in the middle, explanation below.

    The explanation line is always visible. `more` adds a "Learn more" link
    that shows a longer explanation in place (with the mouse or the keyboard).
    """

    def __init__(
        self,
        master: tk.Misc,
        label: str,
        help_text: str,
        tooltip: str = "",
        more: str = "",
        wrap: int | None = None,
    ):
        """Lay out the name and the explanation; subclasses add the control."""
        # No border until focused: a bordered frame per setting slowed every page
        super().__init__(
            master, fg_color="transparent", border_width=0, corner_radius=0
        )
        self.grid_columnconfigure(1, weight=1)
        self.label = ctk.CTkLabel(
            self, text=label, font=font(13), width=160, anchor="w"
        )
        self.label.grid(row=0, column=0, sticky="w", padx=(6, 0), pady=(4, 0))
        # The explanation sits under the control, right of the 160-wide name column
        self.help_text = help_text
        self.help = hint(self, help_text, margin=200, wrap=wrap)
        self.help.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(1, 4))
        self.tooltip = tooltip
        self.more: LearnMore | None = None
        if more:
            self.more = LearnMore(self, more)
            self.more.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(0, 4))

    def ring(self, on: bool) -> None:
        """Show or hide the focus ring around the whole setting."""
        try:
            self.configure(
                border_width=2 if on else 0,
                corner_radius=RADIUS if on else 0,
                border_color=FOCUS,
            )
        except tk.TclError:
            pass

    def explain(self, text: str, color: tuple[str, str] = TEXT_DIM) -> None:
        """Change the explanation line (e.g. to a warning)."""
        set_changed(self.help, text=text, text_color=color)


def _surface_of(widget: tk.Misc) -> tuple[str, str] | str:
    """The colour behind a widget, so an 'invisible' border really is invisible."""
    current: tk.Misc | None = widget
    while current is not None:
        try:
            color = current.cget("fg_color")
        except (tk.TclError, ValueError, AttributeError):
            color = None
        if color and color != "transparent":
            return color
        current = current.master
    return SURFACE


class LearnMore(ctk.CTkFrame):
    """'Learn more': a link that opens a longer explanation right below it."""

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        title: str = "Learn more",
        wrap: int | None = None,
    ) -> None:
        """Closed at first."""
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self.title = title
        self.link = ctk.CTkButton(
            self,
            text=f"{title} ▸",
            font=font(12),
            fg_color="transparent",
            hover_color=ACCENT_SOFT,
            text_color=ACCENT_TEXT,
            anchor="w",
            width=10,
            height=24,
            corner_radius=6,
            command=self.toggle,
        )
        self.link.grid(row=0, column=0, sticky="w")
        accessible_button(self.link, "quiet")
        self.text = hint(self, text, margin=220, wrap=wrap)
        self.opened = False

    def toggle(self) -> None:
        """Open or close the explanation."""
        self.opened = not self.opened
        if self.opened:
            self.text.grid(row=1, column=0, sticky="ew", padx=(8, 0))
        else:
            self.text.grid_remove()
        arrow = "▾" if self.opened else "▸"
        self.link.configure(text=f"{self.title} {arrow}")


class SliderField(Field):
    """A slider with its value shown on the right and a note under it."""

    def __init__(
        self,
        master: tk.Misc,
        label: str,
        help_text: str,
        scale: tuple[float, float, int],
        fmt: Callable[[float], str],
        on_change: Callable[[float], None],
        tooltip: str = "",
        more: str = "",
    ) -> None:
        """scale is (lowest, highest, number of steps); call set() to show a value."""
        super().__init__(master, label, help_text, tooltip, more)
        low, high, steps = scale
        self.fmt = fmt
        self.on_change = on_change
        self.quiet = False
        self.low, self.high, self.steps = low, high, steps
        self.slider = ctk.CTkSlider(
            self,
            # CTkSlider takes floats (0.5 to 1.0 here), though its type hints say int
            from_=low,  # pyright: ignore[reportArgumentType]
            to=high,  # pyright: ignore[reportArgumentType]
            number_of_steps=steps,
            command=self._moved,
            button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            progress_color=ACCENT,
        )
        self.slider.grid(row=0, column=1, sticky="ew", padx=10, pady=(4, 0))
        self.value = ctk.CTkLabel(
            self, text="", font=font(12, "bold"), width=80, anchor="e"
        )
        self.value.grid(row=0, column=2, sticky="e", padx=(0, 6), pady=(4, 0))
        step = (high - low) / steps
        keyboard(
            self.slider,
            None,
            self.ring,
            {
                "<Left>": lambda: self._nudge(-step),
                "<Down>": lambda: self._nudge(-step),
                "<Right>": lambda: self._nudge(step),
                "<Up>": lambda: self._nudge(step),
                "<Home>": lambda: self._nudge(low - high),
                "<End>": lambda: self._nudge(high - low),
            },
        )
        if tooltip:
            Tooltip(self.slider, tooltip)

    def _nudge(self, amount: float) -> None:
        """Move the slider from the keyboard, one step at a time."""
        if str(self.slider.cget("state")) == "disabled":
            return
        value = min(self.high, max(self.low, self.slider.get() + amount))
        self.slider.set(value)
        self._moved(self.slider.get())

    def _moved(self, value: float) -> None:
        """Show the new value and pass it on (unless we set it ourselves)."""
        self.value.configure(text=self.fmt(value))
        if not self.quiet:
            self.on_change(value)

    def set(self, value: float) -> None:
        """Show a value without treating it as the user's change."""
        self.quiet = True
        self.slider.set(value)
        self.value.configure(text=self.fmt(value))
        self.quiet = False

    def enable(self, on: bool) -> None:
        """Grey the slider out, or bring it back."""
        self.slider.configure(
            state="normal" if on else "disabled",
            button_color=ACCENT if on else TEXT_DISABLED,
            progress_color=ACCENT if on else TEXT_DISABLED,
        )
        self.value.configure(text_color=INK if on else TEXT_DISABLED)


class ChoiceField(Field):
    """A row of named options, e.g. Path: Circle | Arc | Figure-8.

    One Tab stop for the whole row; the arrow keys move between the options.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        master: tk.Misc,
        label: str,
        help_text: str,
        options: dict[str, object],
        on_change: Callable[[object], None],
        tooltip: str = "",
        more: str = "",
        wrap: int | None = None,
        *,
        width: int | None = None,
    ) -> None:
        """options maps shown text -> value.

        The row sits at the left, at least width wide, shared equally by the
        options, which grow for longer words. By default each option is at
        least half a toolbar button wide, so the words decide the size.
        """
        super().__init__(master, label, help_text, tooltip, more, wrap)
        self.options = options
        self.on_change = on_change
        self.buttons = ctk.CTkSegmentedButton(
            self,
            values=list(options),
            command=lambda shown: self.on_change(self.options[shown]),
            selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            unselected_color=SURFACE_ALT,
            unselected_hover_color=ACCENT_SOFT,
            fg_color=SURFACE_ALT,
            text_color=INK,
            text_color_disabled=TEXT_DISABLED,
            font=font(12),
            height=TOOL_HEIGHT,
        )
        self.buttons.grid(
            row=0, column=1, columnspan=2, sticky="w", padx=(10, 6), pady=(4, 0)
        )
        if width is None:
            width = TOOL_WIDTH // 2 * len(options)
        # The row takes its size from its options, so each one gets its share
        for inner in self._choice_buttons().values():
            inner.configure(width=width // len(options))
        self._paint()
        keyboard(
            self.buttons,
            None,
            self.ring,
            {
                "<Left>": lambda: self._step(-1),
                "<Up>": lambda: self._step(-1),
                "<Right>": lambda: self._step(1),
                "<Down>": lambda: self._step(1),
            },
        )
        for inner in self._choice_buttons().values():
            inner.bind("<Button-1>", lambda _e: self.buttons.focus_set(), add=True)
        if tooltip:
            Tooltip(self.label, tooltip)
        # In a narrow window the options move under the name instead of being cut
        self._stacked = False
        self.bind("<Configure>", self._fit, add=True)

    def _fit(self, event: tk.Event) -> None:
        """Put the options under the name when they don't fit beside it."""
        scale = self._get_widget_scaling()
        room = event.width - self.label.winfo_reqwidth() - 22 * scale
        self._stack(self.buttons.winfo_reqwidth() > room)

    def _stack(self, stacked: bool) -> None:
        """Options beside the name (False) or on a line of their own below it."""
        if stacked == self._stacked:
            return
        self._stacked = stacked
        below = 1 if stacked else 0
        column, span = (0, 3) if stacked else (1, 2)
        self.label.grid(
            row=0, column=0, columnspan=span if stacked else 1, sticky="w",
            padx=(6, 0), pady=(4, 0),
        )  # fmt: skip
        self.buttons.grid(
            row=below, column=column, columnspan=span, sticky="w",
            padx=(6, 6) if stacked else (10, 6), pady=(4, 0),
        )  # fmt: skip
        indent = (6, 0) if stacked else (0, 0)
        parts: list[tuple[ctk.CTkBaseClass, dict[str, object]]] = [
            (self.help, {"row": 1 + below, "pady": (1, 4)})
        ]
        if self.more is not None:
            parts.append((self.more, {"row": 2 + below, "pady": (0, 4)}))
        for part, place in parts:
            place.update(column=column, columnspan=span, sticky="ew", padx=indent)
            if part.winfo_manager() == "grid":
                part.grid(**place)
            else:
                # Hidden on purpose: only where it would come back is changed
                part.audio8d_grid = place  # type: ignore[attr-defined]

    def _choice_buttons(self) -> dict[str, ctk.CTkButton]:
        """The row's own button per option (empty if CustomTkinter hides them)."""
        return getattr(self.buttons, "_buttons_dict", {})

    def _paint(self) -> None:
        """Selected text white on the accent; others in the normal ink."""
        chosen = self.buttons.get()
        # Only buttons whose colour really changes are redrawn: redraws are slow
        if getattr(self, "_painted", None) == chosen:
            return
        self._painted = chosen
        for shown, inner in self._choice_buttons().items():
            inner.configure(text_color=WHITE if shown == chosen else INK)

    def _step(self, direction: int) -> None:
        """Pick the next or previous option from the keyboard."""
        # CustomTkinter 5.2 can't cget a choice row's state, so it is read directly
        if getattr(self.buttons, "_state", "normal") == "disabled":
            return
        # Greyed-out options are skipped, as a click can't choose them either
        inner = self._choice_buttons()
        shown = [
            s
            for s in self.options
            if s not in inner or inner[s].cget("state") != "disabled"
        ]
        current = self.buttons.get()
        if not shown:
            return
        index = shown.index(current) if current in shown else 0
        chosen = shown[(index + direction) % len(shown)]
        if chosen == current:
            return
        self.buttons.set(chosen)
        self._paint()
        self.on_change(self.options[chosen])

    def set(self, value: object) -> None:
        """Select the option whose value is `value` (none, for any other value)."""
        # A value between the options: no option is shown as chosen
        wanted = next((s for s, option in self.options.items() if option == value), "")
        # Selecting again redraws every segment, so it only happens on a change
        if self.buttons.get() != wanted:
            self.buttons.set(wanted)
        self._paint()

    def enable(self, on: bool) -> None:
        """Grey the whole choice out, or bring it back."""
        self.buttons.configure(state="normal" if on else "disabled")

    def enable_option(self, value: object, on: bool) -> None:
        """Grey out one option (the others stay usable)."""
        for shown, option in self.options.items():
            inner = self._choice_buttons().get(shown)
            if option == value and inner is not None:
                inner.configure(state="normal" if on else "disabled")


class SwitchField(ctk.CTkFrame):
    """An on/off switch with its explanation under it."""

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        help_text: str,
        on_change: Callable[[bool], None],
        tooltip: str = "",
        more: str = "",
    ) -> None:
        """Build the switch."""
        # No border until focused: a bordered frame per setting slowed every page
        super().__init__(
            master, fg_color="transparent", border_width=0, corner_radius=0
        )
        self.on_change = on_change
        self.quiet = False
        self.switch = ctk.CTkSwitch(
            self,
            text=text,
            command=self._flipped,
            progress_color=ACCENT,
            font=font(13),
            text_color=INK,
            text_color_disabled=TEXT_DISABLED,
        )
        self.switch.grid(row=0, column=0, sticky="w", padx=6, pady=(4, 0))
        self.grid_columnconfigure(0, weight=1)
        # Indented under the switch's label, so it lines up with the text
        self.help_text = help_text
        self.help = hint(self, help_text, margin=70)
        self.help.grid(row=1, column=0, sticky="ew", padx=(56, 6), pady=(0, 4))
        if more:
            LearnMore(self, more).grid(
                row=2, column=0, sticky="ew", padx=(52, 6), pady=(0, 4)
            )
        keyboard(self.switch, self.switch.toggle, self.ring)
        if tooltip:
            Tooltip(self.switch, tooltip)

    def ring(self, on: bool) -> None:
        """Show or hide the focus ring."""
        try:
            self.configure(
                border_width=2 if on else 0,
                corner_radius=RADIUS if on else 0,
                border_color=FOCUS,
            )
        except tk.TclError:
            pass

    def _flipped(self) -> None:
        """Pass the new state on (unless we set it ourselves)."""
        if not self.quiet:
            self.on_change(bool(self.switch.get()))

    def set(self, on: bool) -> None:
        """Show a state without treating it as the user's change."""
        if bool(self.switch.get()) != on:
            self.quiet = True
            state = self.switch.cget("state")
            self.switch.configure(state="normal")
            self.switch.toggle()
            self.switch.configure(state=state)
            self.quiet = False

    def get(self) -> bool:
        """The current state."""
        return bool(self.switch.get())

    def enable(self, on: bool, why: str = "") -> None:
        """Grey the switch out (with the reason under it), or bring it back."""
        self.switch.configure(state="normal" if on else "disabled")
        if why:
            self.help.configure(text=why)

    def explain(self, text: str, color: tuple[str, str] = TEXT_DIM) -> None:
        """Change the explanation line."""
        set_changed(self.help, text=text, text_color=color)


class ChoiceMenu(ctk.CTkOptionMenu):
    """A drop-down list of choices; Space, Enter or Down opens it from the keyboard."""

    def __init__(
        self,
        master: tk.Misc,
        values: list[str],
        on_change: Callable[[str], None],
        width: int = 280,
    ) -> None:
        """values are the words shown; on_change gets the one picked."""
        super().__init__(
            master,
            values=values,
            width=width,
            height=CONTROL_HEIGHT - 4,
            font=font(12),
            dropdown_font=font(12),
            dynamic_resizing=False,
            corner_radius=RADIUS,
            fg_color=SURFACE_ALT,
            button_color=SURFACE_ALT,
            button_hover_color=ACCENT_SOFT,
            text_color=INK,
            text_color_disabled=TEXT_DISABLED,
            dropdown_fg_color=SURFACE,
            dropdown_text_color=INK,
            dropdown_hover_color=ACCENT_SOFT,
            command=on_change,
        )

        def ring(on: bool) -> None:
            try:
                self.configure(button_color=FOCUS if on else SURFACE_ALT)
            except tk.TclError:
                pass

        keyboard(
            self,
            self._open,
            ring,
            {"<Down>": self._open, "<Alt-Down>": self._open},
        )

    def _open(self) -> None:
        """Open the list (the keyboard can then move through it)."""
        if str(self.cget("state")) != "disabled":
            self._open_dropdown_menu()

    def destroy(self) -> None:
        """Let go of the drop-down list completely."""
        dropdown = self._dropdown_menu
        super().destroy()
        # CustomTkinter 5.2 forgets this, so a later Size change would hit a closed list
        # pylint: disable-next=protected-access
        ctk.ScalingTracker.remove_widget(dropdown._set_scaling, dropdown)


class EntryField(Field):
    """A text box checked as you type: red border and a reason when it's wrong."""

    def __init__(
        self,
        master: tk.Misc,
        label: str,
        help_text: str,
        placeholder: str,
        on_change: Callable[[str], str | None],
        width: int = 260,
        tooltip: str = "",
        more: str = "",
    ) -> None:
        """on_change stores the text and returns an error message, or None."""
        super().__init__(master, label, help_text, tooltip, more)
        self.on_change = on_change
        self.entry = entry(self, placeholder, width)
        self.entry.grid(row=0, column=1, sticky="w", padx=10, pady=(4, 0))
        self.entry.bind("<KeyRelease>", lambda _e: self.check())
        self.entry.bind("<FocusOut>", lambda _e: self.check(), add=True)
        self.ok = True
        if tooltip:
            Tooltip(self.entry, tooltip)

    def check(self) -> bool:
        """Store the text; show the reason in red if it can't be used."""
        # A mistake that has been put right must not leave its red line behind
        self.explain(self.help_text)
        problem = self.on_change(self.entry.get())
        self.ok = not problem
        if problem:
            mark_entry(self.entry, True)
            self.explain(problem, DANGER)
            return False
        mark_entry(self.entry, False)
        return True

    def set(self, text: str) -> None:
        """Put text in the box (without checking)."""
        self.entry.delete(0, "end")
        if text:
            self.entry.insert(0, text)

    def enable(self, on: bool) -> None:
        """Grey the box out, or bring it back."""
        self.entry.configure(state="normal" if on else "disabled")


def browse_button(
    master: tk.Misc, command: Callable[[], None], tooltip: str = ""
) -> ctk.CTkButton:
    """'Browse…' beside a path box, the same size wherever something is picked."""
    return button(
        master,
        "folder",
        "Browse…",
        command,
        width=110,
        height=TOOL_HEIGHT,
        tooltip=tooltip,
    )


def trim_fields(
    master: tk.Misc, on_change: Callable[[str, str], str | None]
) -> tuple["EntryField", "EntryField"]:
    """'Use only part: from' and 'to' boxes; on_change gets (key, text)."""
    start = EntryField(
        master,
        "Use only part: from",
        "Leave both empty to keep the whole song.",
        "e.g. 1:00",
        lambda text: on_change("trim_start", text),
        width=140,
    )
    end = EntryField(
        master,
        "Use only part: to",
        "Handy for ringtones. Write times like 90 (seconds) or 1:30.",
        "e.g. 1:30",
        lambda text: on_change("trim_end", text),
        width=140,
    )
    return start, end


class MenuField(Field):
    """A named drop-down list, for choices with longer words (styles, file types)."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        master: tk.Misc,
        label: str,
        help_text: str,
        options: dict[str, object],
        on_change: Callable[[object], None],
        width: int = 320,
    ) -> None:
        """options maps shown text -> value."""
        super().__init__(master, label, help_text)
        self.options = dict(options)
        self.menu = ChoiceMenu(
            self,
            list(self.options),
            lambda shown: on_change(self.options[shown]),
            width,
        )
        self.menu.grid(row=0, column=1, sticky="w", padx=10, pady=(4, 0))

    def set_options(self, options: dict[str, object]) -> None:
        """Offer other choices (e.g. after a style was saved)."""
        if options != self.options:
            self.options = dict(options)
            self.menu.configure(values=list(self.options))

    def set(self, value: object) -> None:
        """Show the option whose value is `value`."""
        for shown, option in self.options.items():
            if option == value:
                self.menu.set(shown)
                return

    def enable(self, on: bool) -> None:
        """Grey the list out, or bring it back."""
        self.menu.configure(state="normal" if on else "disabled")
