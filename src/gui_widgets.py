# Developed by ::> Gehan Fernando
"""The building blocks of the Audio8D window: the design system and its controls.

One restrained palette (light and dark), one type scale and one set of
controls. Every control:

* says what it does in a short line that is always visible;
* keeps deeper explanations behind a "Learn more" link that the keyboard can
  open too (a tooltip never holds the only copy of anything);
* can be reached with Tab and used with Space, Enter or the arrow keys, and
  shows a clear focus ring while it has the keyboard focus.
"""

__all__ = ["open_path"]

import os
import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

import customtkinter as ctk

from .core.errors import Audio8DError
from .opener import open_path

# CustomTkinter's own scrollbar drawing, kept so the quicker version can call it
_SCROLLBAR_DRAW = ctk.CTkScrollbar._draw  # pylint: disable=protected-access


def _draw_scrollbar_without_flush(
    self: ctk.CTkScrollbar, no_color_updates: bool = False
) -> None:
    """Draw a scrollbar without forcing the whole window to lay itself out first."""
    # CustomTkinter 5.2 forces a full layout pass on every redraw; Tk redraws anyway
    _skip_flush(self)
    _SCROLLBAR_DRAW(self, no_color_updates)


def _no_flush() -> None:
    """Stands in for update_idletasks on a scrollbar's canvas."""


def _skip_flush(widget: tk.Misc) -> None:
    """Make a widget's drawing canvas skip its layout pass (if it has one)."""
    canvas = getattr(widget, "_canvas", None)
    if canvas is not None:
        canvas.update_idletasks = _no_flush


# pylint: disable-next=protected-access
ctk.CTkScrollbar._draw = _draw_scrollbar_without_flush  # type: ignore[method-assign]

# The drop-down list does the same whenever it is redrawn, e.g. greyed out
_OPTIONMENU_DRAW = ctk.CTkOptionMenu._draw  # pylint: disable=protected-access


def _draw_optionmenu_without_flush(
    self: ctk.CTkOptionMenu, no_color_updates: bool = False
) -> None:
    """Draw a drop-down list without a full layout pass of the whole window."""
    _skip_flush(self)
    _OPTIONMENU_DRAW(self, no_color_updates)


# pylint: disable-next=protected-access
ctk.CTkOptionMenu._draw = _draw_optionmenu_without_flush  # type: ignore[method-assign]


def _recolor_every_widget(tracker: type) -> None:
    """Tell every widget about a theme change, even if some go away meanwhile."""
    dark = tracker.appearance_mode == 1  # type: ignore[attr-defined]
    mode = "Dark" if dark else "Light"
    # A copy, as widgets destroyed mid-way made CustomTkinter skip their neighbours
    for callback in list(tracker.callback_list):  # type: ignore[attr-defined]
        try:
            callback(mode)
        except Exception:  # pylint: disable=broad-exception-caught
            # A widget destroyed meanwhile has nothing left to recolour
            continue


# Only where the tracker still keeps its list the way CustomTkinter 5.2 and 6.0 do
if isinstance(getattr(ctk.AppearanceModeTracker, "callback_list", None), list):
    _TRACKER = ctk.AppearanceModeTracker
    _TRACKER.update_callbacks = classmethod(_recolor_every_widget)  # type: ignore


# CustomTkinter re-grids hidden widgets on a size change; these patches keep them hidden
_CtkBase = ctk.CTkFrame.__mro__[1]  # CustomTkinter's CTkBaseClass
_BASE_GRID = _CtkBase.grid


def _grid_remembered(self: tk.Misc, **kwargs: object) -> object:
    """grid(), remembering the placement so a bare grid() can restore all of it."""
    if kwargs:
        self.audio8d_grid = kwargs  # type: ignore[attr-defined]
    else:
        kwargs = getattr(self, "audio8d_grid", {})
    return _BASE_GRID(self, **kwargs)


def _grid_remove_tracked(self: tk.Misc) -> None:
    """grid_remove() that CustomTkinter's rescaling respects."""
    # pylint: disable-next=protected-access
    self._last_geometry_manager_call = None  # type: ignore[attr-defined]
    tk.Grid.grid_remove(self)  # type: ignore[arg-type]


_CtkBase.grid = _grid_remembered  # type: ignore[method-assign]
_CtkBase.grid_remove = _grid_remove_tracked  # type: ignore[method-assign]


# ------------------------------------------------------------------ design tokens

# (light, dark) colour pairs; every text colour passes WCAG AA on its surface
BACKGROUND = ("#F3F5F8", "#111318")
SURFACE = ("#FFFFFF", "#191C22")
SURFACE_ALT = ("#F6F7F9", "#20242B")
SIDEBAR = ("#FFFFFF", "#15181D")
BORDER = ("#D8DDE4", "#2F343D")
BORDER_STRONG = ("#AEB6C2", "#4A515D")
INK = ("#111827", "#E8EBF0")
TEXT_DIM = ("#4B5563", "#A7AFBB")
TEXT_DISABLED = ("#9AA3AF", "#626A76")
ACCENT = ("#1D5FD1", "#2F6BE0")
ACCENT_HOVER = ("#174DAB", "#2458C2")
ACCENT_TEXT = ("#1A56C0", "#8AB4FF")
ACCENT_SOFT = ("#E8F0FE", "#1B2A44")
ACCENT_SOFT_HOVER = ("#D2E1FC", "#243A5E")
FOCUS = ("#0B57D0", "#A8C7FA")
# The ring around a blue button: dark on light mode, light on dark mode
FOCUS_ON_ACCENT = ("#0A1F4D", "#FFFFFF")
WHITE = ("#FFFFFF", "#FFFFFF")
SUCCESS = ("#126B33", "#4ADE80")
SUCCESS_SOFT = ("#E7F6EC", "#15291D")
WARNING = ("#9A5B06", "#FBBF24")
WARNING_SOFT = ("#FEF6E4", "#2E2512")
DANGER = ("#B42318", "#F97066")
DANGER_FILL = ("#B42318", "#C0392B")
DANGER_HOVER = ("#912018", "#A93226")
DANGER_SOFT = ("#FDECEA", "#34191A")
# A grey tag behind neutral badges such as 'Optional'
NEUTRAL_SOFT = ("#E5E8EE", "#2A2F38")
# A filled button while it can't be used: grey, never a dim blue or red
DISABLED_FILL = ("#E1E5EB", "#2A2F38")
# Hover hints: dark in both themes, so they stand apart from the page
TOOLTIP_FILL = ("#1F2937", "#2B303A")
TOOLTIP_TEXT = ("#F8FAFC", "#F8FAFC")
# Kept for older callers: the sidebar used to be its own colour
SURFACE_SIDEBAR = SIDEBAR

# One corner radius for controls; panels inside a card and cards are rounder
RADIUS = 8
PANEL_RADIUS = 10
CARD_RADIUS = 12
# Card actions and dialog buttons; toolbars, rows and inline buttons use TOOL_HEIGHT
CONTROL_HEIGHT = 36
# A toolbar button, as in 'Your songs' on steps 1 and 2
TOOL_WIDTH = 190
TOOL_HEIGHT = 32
# The one big pair of buttons: Create and Stop on step 4
HERO_HEIGHT = 44
# Every song list's search box
SEARCH_WIDTH = 240

# Windows 11/10 icon-font glyphs, with plain characters for everyone else
_GLYPHS = {
    "songs": ("\ue8d6", "♪"),
    "sound": ("\ue9e9", "≋"),
    "output": ("\ue74e", "⤓"),
    "review": ("\ue768", "▶"),
    "styles": ("\ue771", "✎"),
    "settings": ("\ue713", "⚙"),
    "add": ("\ue710", "+"),
    "folder": ("\ue8b7", "▤"),
    "open": ("\ued25", "↗"),
    "play": ("\ue768", "▶"),
    "pause": ("\ue769", "❚❚"),
    "stop": ("\ue71a", "■"),
    "replay": ("\ue72c", "↻"),
    "preview": ("\ue7f6", "♫"),
    "compare": ("\ue8ab", "⇄"),
    "remove": ("\ue711", "✕"),
    "delete": ("\ue74d", "✕"),
    "check": ("\ue73e", "✓"),
    "error": ("\uea39", "!"),
    "warning": ("\ue7ba", "!"),
    "info": ("\ue946", "i"),
    "drop": ("\ue898", "⇧"),
    "save": ("\ue74e", "⤓"),
    "clear": ("\ue894", "⌫"),
    "music": ("\ue8d6", "♪"),
    "star": ("\ue734", "★"),
    "guide": ("\ue82d", "?"),
    "next": ("\ue72a", "→"),
    "back": ("\ue72b", "←"),
    "down": ("\ue70d", "▾"),
    "up": ("\ue70e", "▴"),
    "search": ("\ue721", "⌕"),
    "wand": ("\ue945", "✦"),
    "copy": ("\ue8c8", "⧉"),
    "test": ("\ue9d5", "✓"),
    "headphones": ("\ue7f6", "♫"),
}


# One shared font per size and weight: a font per widget left garbage that stalled Tk
_FONTS: dict[tuple[int, str], ctk.CTkFont] = {}


def font(size: int = 13, weight: Literal["normal", "bold"] = "normal") -> ctk.CTkFont:
    """The window's text font (shared; widgets never change it)."""
    key = (size, weight)
    if key not in _FONTS:
        _FONTS[key] = ctk.CTkFont(family="Segoe UI", size=size, weight=weight)
    return _FONTS[key]


def shade(color: tuple[str, str]) -> str:
    """The half of a (light, dark) colour pair that the current theme uses."""
    return color[1] if ctk.get_appearance_mode() == "Dark" else color[0]


class Icons:
    """Finds the icon font once and hands out glyphs, fonts and images."""

    family: str | None = None
    font_file: Path | None = None
    _cache: dict[tuple, "ctk.CTkImage | None"] = {}

    @classmethod
    def setup(cls) -> None:
        """Look for the icon font (call after the Tk root exists)."""
        # Images and fonts belong to one window; a new window needs fresh ones
        cls._cache = {}
        _FONTS.clear()
        try:
            families = set(tkfont.families())
        except tk.TclError:
            families = set()
        cls.family = next(
            (f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in families),
            None,
        )
        fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for name in ("SegoeIcons.ttf", "segmdl2.ttf"):
            if (fonts / name).is_file():
                cls.font_file = fonts / name
                break

    @classmethod
    def glyph(cls, name: str) -> str:
        """The character for an icon."""
        fluent, plain = _GLYPHS[name]
        return fluent if cls.family else plain

    @classmethod
    def font(cls, size: int = 16) -> ctk.CTkFont:
        """The font the glyphs are drawn with."""
        return ctk.CTkFont(family=cls.family or "Segoe UI Symbol", size=size)

    @classmethod
    def image(
        cls, name: str, size: int = 16, color: tuple[str, str] = INK
    ) -> "ctk.CTkImage | None":
        """The icon as a crisp image for buttons (None where it can't be drawn)."""
        key = (name, size, color)
        if key not in cls._cache:
            cls._cache[key] = cls._draw(name, size, color)
        return cls._cache[key]

    @classmethod
    def _draw(
        cls, name: str, size: int, color: tuple[str, str]
    ) -> "ctk.CTkImage | None":
        """Render one glyph four times larger, then let CTk scale it down."""
        if cls.font_file is None:
            return None
        try:
            from PIL import (  # pylint: disable=import-outside-toplevel
                Image,
                ImageDraw,
                ImageFont,
            )
        except ImportError:
            return None
        scale = 4
        glyph_font = ImageFont.truetype(str(cls.font_file), size * scale)

        def draw(fill: str) -> "Image.Image":
            canvas = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
            ImageDraw.Draw(canvas).text(
                (size * scale / 2, size * scale / 2),
                _GLYPHS[name][0],
                font=glyph_font,
                fill=fill,
                anchor="mm",
            )
            return canvas

        return ctk.CTkImage(
            light_image=draw(color[0]), dark_image=draw(color[1]), size=(size, size)
        )


def icon_text(
    name: str, text: str, size: int = 16, color: tuple[str, str] = INK
) -> dict:
    """Button options for an icon followed by text (an image when possible)."""
    image = Icons.image(name, size, color)
    if image is None:
        return {"text": f"{_GLYPHS[name][1]}  {text}" if text else _GLYPHS[name][1]}
    return {
        "text": f"  {text}" if text else "",
        "image": image,
        "compound": "left",
    }


# ------------------------------------------------------------------ keyboard


def _take_focus(widget: tk.Misc) -> None:
    """Let Tab stop on a CustomTkinter widget (they don't by themselves)."""
    try:
        widget.tk.call(str(widget), "configure", "-takefocus", 1)
    except tk.TclError:
        pass


# Whether the keyboard (not a click) moved last: only keyboard users see the ring
_KEYBOARD = {"on": False, "hooked": False}


def keyboard_in_use(on: bool | None = None) -> bool:
    """Whether the keyboard is how the user moves around (set it with on)."""
    if on is not None:
        _KEYBOARD["on"] = on
    return _KEYBOARD["on"]


def _hook_input_mode(widget: tk.Misc) -> None:
    """Watch Tab and clicks once for the whole window."""
    if _KEYBOARD["hooked"]:
        return
    _KEYBOARD["hooked"] = True
    # CustomTkinter widgets refuse bind_all, so it is done on plain Tk
    for key in ("<Tab>", "<Shift-Tab>", "<ISO_Left_Tab>"):
        tk.Misc.bind_all(widget, key, lambda _e: keyboard_in_use(True), "+")
    tk.Misc.bind_all(widget, "<ButtonPress>", lambda _e: keyboard_in_use(False), "+")


def keyboard(
    widget: tk.Misc,
    activate: Callable[[], None] | None,
    ring: Callable[[bool], None],
    keys: dict[str, Callable[[], None]] | None = None,
) -> None:
    """Make widget reachable with Tab, usable with Space/Enter, and ringed on focus.

    ring(True) draws the focus ring and ring(False) removes it; keys adds more
    keys (e.g. arrows) with what each one does.
    """
    _take_focus(widget)
    _hook_input_mode(widget)
    # Tk's own bind: the keys and focus belong to the widget's outer frame
    tk.Misc.bind(widget, "<FocusIn>", lambda _e: ring(keyboard_in_use()), "+")
    tk.Misc.bind(widget, "<FocusOut>", lambda _e: ring(False), "+")
    if activate is not None:
        for key in ("<space>", "<Return>", "<KP_Enter>"):
            tk.Misc.bind(widget, key, lambda _e: (activate(), "break")[1], "+")
    for key, action in (keys or {}).items():
        tk.Misc.bind(widget, key, lambda _e, act=action: (act(), "break")[1], "+")
    # Clicking also gives keyboard focus, so Tab carries on from there
    try:
        widget.bind("<Button-1>", lambda _e: widget.focus_set(), add=True)
    except NotImplementedError:
        # Segmented buttons refuse bindings; their inner buttons take the click
        pass


def _button_ring(widget: ctk.CTkButton, kind: str) -> Callable[[bool], None]:
    """The focus ring of a button: a thicker border in the focus colour."""
    normal = (widget.cget("border_width"), widget.cget("border_color"))
    color = FOCUS_ON_ACCENT if kind in ("primary", "danger") else FOCUS

    def ring(on: bool) -> None:
        try:
            if on:
                widget.configure(border_width=2, border_color=color)
            else:
                widget.configure(border_width=normal[0], border_color=normal[1])
        except tk.TclError:
            pass

    return ring


def accessible_button(widget: ctk.CTkButton, kind: str = "outline") -> ctk.CTkButton:
    """Any CTkButton, made usable from the keyboard with a visible focus ring."""

    def press() -> None:
        if str(widget.cget("state")) != "disabled":
            widget.invoke()

    keyboard(widget, press, _button_ring(widget, kind))
    return widget


class Button(ctk.CTkButton):
    """A CTkButton whose filled looks turn grey while disabled (not dim blue)."""

    def __init__(self, *args: object, kind: str = "outline", **kwargs: object):
        """kind is the look from button()."""
        self.kind = kind
        self._fill = kwargs.get("fg_color")
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    def configure(self, require_redraw: bool = False, **kwargs: object) -> None:
        """Grey filled buttons when disabled; back to their colour when enabled."""
        if "state" in kwargs and self.kind in ("primary", "danger"):
            off = kwargs["state"] == "disabled"
            kwargs.setdefault("fg_color", DISABLED_FILL if off else self._fill)
        super().configure(require_redraw, **kwargs)  # type: ignore[arg-type]


def button(
    master: tk.Misc,
    icon: str,
    text: str,
    command: Callable[[], None],
    *,
    kind: str = "outline",
    width: int = 140,
    height: int = CONTROL_HEIGHT,
    tooltip: str = "",
) -> ctk.CTkButton:
    """A button in one look: 'primary', 'accent', 'outline', 'quiet' or 'danger'.

    'accent' is a lighter commit action (blue outline) for places where many
    buttons repeat, e.g. one per style card, and a filled one would shout.
    """
    looks = {
        "primary": (ACCENT, ACCENT_HOVER, WHITE, 0, BORDER_STRONG),
        "accent": (ACCENT_SOFT, ACCENT_SOFT_HOVER, ACCENT_TEXT, 1, ACCENT),
        "outline": (SURFACE, ACCENT_SOFT, INK, 1, BORDER_STRONG),
        "quiet": ("transparent", ACCENT_SOFT, ACCENT_TEXT, 0, BORDER_STRONG),
        "danger": (DANGER_FILL, DANGER_HOVER, WHITE, 0, BORDER_STRONG),
    }
    fill, hover, ink, border, edge = looks[kind]
    widget = Button(
        master,
        kind=kind,
        **(icon_text(icon, text, 16, ink) if icon else {"text": text}),
        font=font(13, "bold" if kind in ("primary", "accent", "danger") else "normal"),
        width=width,
        height=height,
        corner_radius=RADIUS,
        fg_color=fill,
        hover_color=hover,
        border_width=border,
        border_color=edge,
        text_color=ink,
        text_color_disabled=TEXT_DISABLED,
        command=command,
    )
    accessible_button(widget, kind)
    if tooltip:
        Tooltip(widget, tooltip)
    return widget


# ------------------------------------------------------------------ helpers


def problem_of(fn: Callable[[], object]) -> str | None:
    """Run a check; return its error message, or None."""
    try:
        fn()
    except Audio8DError as exc:
        return str(exc)
    return None


def set_changed(widget: tk.Misc, **options: object) -> None:
    """Configure only the options that really change: every redraw costs time."""
    changed = {}
    for key, value in options.items():
        try:
            same = widget.cget(key) == value
        except (tk.TclError, ValueError):
            same = False
        if not same:
            changed[key] = value
    if changed:
        widget.configure(**changed)


def clear_children(frame: tk.Misc) -> None:
    """Remove everything inside a frame."""
    for child in frame.winfo_children():
        child.destroy()


class Tooltip:  # pylint: disable=too-few-public-methods
    """A short extra hint on hover or keyboard focus (never the only copy of it)."""

    def __init__(self, widget: tk.Misc, text: str | Callable[[], str]) -> None:
        """Attach to widget; text may be a function for hints that change."""
        self.widget = widget
        self.text = text
        self.window: tk.Toplevel | None = None
        self.pending: str | None = None
        try:
            widget.bind("<Enter>", self._schedule, add=True)
            widget.bind("<Leave>", self._hide, add=True)
            widget.bind("<ButtonPress>", self._hide, add=True)
            widget.bind("<FocusIn>", self._schedule, add=True)
            widget.bind("<FocusOut>", self._hide, add=True)
        except NotImplementedError:
            # Segmented buttons refuse bindings; their row's label has the tooltip
            pass

    def _schedule(self, _event: object = None) -> None:
        """Show after a short pause, so moving across doesn't flash hints."""
        self._cancel()
        self.pending = self.widget.after(450, self._show)

    def _cancel(self) -> None:
        """Forget a hint that was about to appear."""
        if self.pending is not None:
            try:
                self.widget.after_cancel(self.pending)
            except tk.TclError:
                pass
            self.pending = None

    def _show(self) -> None:
        """Draw the hint just below the widget."""
        self.pending = None
        text = self.text() if callable(self.text) else self.text
        if not text or not self.widget.winfo_exists() or self.window is not None:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry(f"+{x}+{y}")
        self.window.attributes("-topmost", True)
        tk.Label(
            self.window,
            text=text,
            justify="left",
            wraplength=380,
            background=shade(TOOLTIP_FILL),
            foreground=shade(TOOLTIP_TEXT),
            padx=10,
            pady=7,
            font=("Segoe UI", 9),
        ).pack()

    def _hide(self, _event: object = None) -> None:
        """Remove the hint."""
        self._cancel()
        if self.window is not None:
            self.window.destroy()
            self.window = None


def hint(
    master: tk.Misc,
    text: str,
    color: tuple[str, str] = TEXT_DIM,
    margin: int = 0,
    size: int = 12,
    wrap: int | None = None,
) -> ctk.CTkLabel:
    """A small grey explanation line that wraps to the width it is given.

    With wrap, it wraps at that fixed width instead: needed inside anything whose
    own width comes from its content, or the two would keep resizing each other.
    """
    label = ctk.CTkLabel(
        master,
        text=text,
        font=font(size),
        text_color=color,
        anchor="w",
        justify="left",
        wraplength=wrap or 600,
    )
    if wrap is None:
        fit_width(label, master, margin)
    return label


def fit_width(label: ctk.CTkLabel, master: tk.Misc, margin: int) -> None:
    """Keep a label's text wrapped inside master, whatever the window size or scale."""
    # One resize handler per parent, which forgets labels that have been destroyed
    fitted: list[tuple[ctk.CTkLabel, int]] | None = getattr(
        master, "audio8d_fitted", None
    )
    if fitted is None:
        # Kept on the parent itself, so the list goes when the parent does
        fitted = []
        master.audio8d_fitted = fitted  # type: ignore[attr-defined]

        def resize(event: tk.Event) -> None:
            fitted[:] = [(lbl, gap) for lbl, gap in fitted if lbl.winfo_exists()]
            for lbl, gap in fitted:
                # Events report real pixels, while wraplength is in unscaled units
                scale = lbl._get_widget_scaling()  # pylint: disable=protected-access
                wrap = max(160, int(event.width / scale) - gap)
                # Every re-wrap costs a layout pass, so small wobbles are ignored
                if abs(wrap - getattr(lbl, "audio8d_wrap", 0)) >= 6:
                    lbl.audio8d_wrap = wrap  # type: ignore[attr-defined]
                    lbl.configure(wraplength=wrap)

        master.bind("<Configure>", resize, add=True)
    else:
        # Parents that swap their labels often would otherwise pile up old ones
        fitted[:] = [(lbl, gap) for lbl, gap in fitted if lbl.winfo_exists()]
    fitted.append((label, margin))


def flow(
    container: ctk.CTkFrame,
    parts: Sequence[tk.Widget],
    gap: int = 12,
    line_gap: int = 8,
) -> None:
    """Lay parts out left to right in container, starting a new line when one won't fit.

    The room is the width of container's parent, less the same padding on both sides.
    """
    shown: list[tuple[int, int]] = []
    # One frame per line, so a wide part on one line never pushes another line apart
    lines: list[ctk.CTkFrame] = []

    def lay_out(room: float) -> None:
        # Widths are real pixels, while the gap is in unscaled units
        space = gap * container._get_widget_scaling()  # pylint: disable=protected-access
        places: list[tuple[int, int]] = []
        row = column = 0
        used = 0.0
        for part in parts:
            width = part.winfo_reqwidth()
            if column and used + space + width > room:
                row, column, used = row + 1, 0, 0.0
            used += (space if column else 0) + width
            places.append((row, column))
            column += 1
        # Every move costs a layout pass, so only a real change is applied
        if places == shown:
            return
        shown[:] = places
        needed = places[-1][0] + 1 if places else 0
        while len(lines) < needed:
            line = ctk.CTkFrame(container, fg_color="transparent", width=0, height=0)
            line.grid(row=len(lines), column=0, sticky="w", pady=(line_gap, 0))
            lines.append(line)
        lines[0].grid_configure(pady=0)
        for index, line in enumerate(lines):
            if index < needed:
                line.grid()
            else:
                line.grid_remove()
        for part, (row, column) in zip(parts, places, strict=True):
            part.grid(
                in_=lines[row],
                row=0,
                column=column,
                sticky="w",
                padx=(gap if column else 0, 0),
            )
            # The line frames came later, so the parts are lifted back above them
            part.lift()

    def refit(_event: object = None) -> None:
        parent = container.master
        if parent.winfo_width() > 1:
            lay_out(parent.winfo_width() - 2 * container.winfo_x())

    lay_out(float("inf"))
    container.master.bind("<Configure>", refit, add=True)
    # The parts grow too, e.g. when the size setting changes
    container.bind("<Configure>", refit, add=True)


class Badge(ctk.CTkLabel):
    """A small rounded tag such as 'Recommended' or 'Your style'.

    Badges always carry words, so no state is told by colour alone.
    """

    _LOOKS = {
        "accent": (ACCENT_SOFT, ACCENT_TEXT),
        "success": (SUCCESS_SOFT, SUCCESS),
        "warning": (WARNING_SOFT, WARNING),
        "danger": (DANGER_SOFT, DANGER),
        "neutral": (NEUTRAL_SOFT, INK),
    }

    def __init__(self, master: tk.Misc, text: str, kind: str = "accent") -> None:
        """Draw the tag."""
        fill, ink = self._LOOKS[kind]
        super().__init__(
            master,
            text=f" {text} ",
            font=font(11, "bold"),
            fg_color=fill,
            text_color=ink,
            corner_radius=6,
            height=22,
        )

    def show(self, text: str, kind: str = "accent") -> None:
        """Change the words and the look."""
        fill, ink = self._LOOKS[kind]
        set_changed(self, text=f" {text} ", fg_color=fill, text_color=ink)


# A dependency's state as a badge: its words, symbol and look (never colour alone)
STATUS_LOOKS = {
    "ready": ("✓", "success"),
    "missing": ("✗", "danger"),
    "invalid": ("✗", "danger"),
    "optional": ("○", "neutral"),
    "unavailable": ("○", "warning"),
    "checking": ("…", "neutral"),
}


class StatusBadge(Badge):
    """A badge for a dependency: '✓ Ready', '✗ Missing', '○ Optional'…"""

    def __init__(
        self, master: tk.Misc, state: str = "checking", words: str = ""
    ) -> None:
        """Draw it in the look of the state."""
        mark, kind = STATUS_LOOKS[state]
        super().__init__(master, f"{mark} {words or state.title()}", kind)

    def set_state(self, state: str, words: str) -> None:
        """Show another state."""
        mark, kind = STATUS_LOOKS[state]
        self.show(f"{mark} {words}", kind)


class Card(ctk.CTkFrame):
    """A rounded panel with an optional title and subtitle; content goes in .body."""

    def __init__(self, master: tk.Misc, title: str = "", subtitle: str = "") -> None:
        """Draw the panel."""
        super().__init__(
            master,
            fg_color=SURFACE,
            corner_radius=CARD_RADIUS,
            border_width=1,
            border_color=BORDER,
        )
        self.grid_columnconfigure(0, weight=1)
        row = 0
        self.title_label: ctk.CTkLabel | None = None
        if title:
            self.title_label = ctk.CTkLabel(
                self, text=title, font=font(15, "bold"), anchor="w"
            )
            self.title_label.grid(row=row, column=0, sticky="ew", padx=20, pady=(16, 0))
            row += 1
        if subtitle:
            hint(self, subtitle, margin=40).grid(
                row=row, column=0, sticky="ew", padx=20, pady=(2, 0)
            )
            row += 1
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=row, column=0, sticky="nsew", padx=20, pady=(12, 18))
        self.body.grid_columnconfigure(0, weight=1)


class Section(Card):
    """A card whose body folds away: used for advanced and optional settings."""

    def __init__(
        self,
        master: tk.Misc,
        title: str,
        subtitle: str,
        open_: bool = False,
        build: Callable[[ctk.CTkFrame], None] | None = None,
    ):
        """Draw the header with a show/hide button.

        With build, the content is only made the first time the section opens,
        which keeps the window quick to start.
        """
        super().__init__(master, "", "")
        self.builder = build
        self.built = build is None
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(14, 0))
        header.grid_columnconfigure(0, weight=1)
        self.title_label = ctk.CTkLabel(
            header, text=title, font=font(15, "bold"), anchor="w"
        )
        self.title_label.grid(row=0, column=0, sticky="w")
        self.subtitle_label = hint(header, subtitle, margin=160)
        self.subtitle_label.grid(row=1, column=0, sticky="ew")
        self.toggle_button = ctk.CTkButton(
            header,
            width=120,
            height=TOOL_HEIGHT,
            corner_radius=RADIUS,
            fg_color=SURFACE,
            hover_color=ACCENT_SOFT,
            border_width=1,
            border_color=BORDER_STRONG,
            text_color=INK,
            font=font(12),
            command=self.toggle,
        )
        self.toggle_button.grid(row=0, column=1, rowspan=2, padx=(10, 0))
        accessible_button(self.toggle_button)
        self.opened = open_
        self._apply()

    def toggle(self) -> None:
        """Show or hide the content."""
        self.opened = not self.opened
        self._apply()

    def open(self) -> None:
        """Show the content."""
        if not self.opened:
            self.toggle()

    def _apply(self) -> None:
        """Match the body and the button to the state."""
        if self.opened and not self.built:
            self.built = True
            assert self.builder is not None
            self.builder(self.body)
        if self.opened:
            # The full call, as CustomTkinter replays the last grid() on a size change
            self.body.grid(row=1, column=0, sticky="nsew", padx=20, pady=(12, 18))
            self.toggle_button.configure(**icon_text("up", "Hide", 12))
        else:
            self.body.grid_remove()
            self.toggle_button.configure(**icon_text("down", "Show", 12))
        if not self.opened:
            self.grid_rowconfigure(1, minsize=14)


def entry(master: tk.Misc, placeholder: str = "", width: int = 260) -> ctk.CTkEntry:
    """A text box in the window's look, with a focus ring."""
    box = ctk.CTkEntry(
        master,
        placeholder_text=placeholder,
        width=width,
        height=CONTROL_HEIGHT - 4,
        font=font(12),
        corner_radius=RADIUS,
        border_width=1,
        border_color=BORDER_STRONG,
        fg_color=SURFACE_ALT,
        text_color=INK,
        placeholder_text_color=TEXT_DIM,
    )
    box.audio8d_problem = False  # type: ignore[attr-defined]
    # The focus ring: a thicker border in the focus colour (red while it's wrong)
    box.bind("<FocusIn>", lambda _e: _entry_edge(box, True), add=True)
    box.bind("<FocusOut>", lambda _e: _entry_edge(box, False), add=True)
    return box


def _entry_edge(box: ctk.CTkEntry, focused: bool) -> None:
    """Draw a text box's border for its focus and whether its text can be used."""
    problem = getattr(box, "audio8d_problem", False)
    color = DANGER if problem else (FOCUS if focused else BORDER_STRONG)
    try:
        set_changed(box, border_width=2 if focused else 1, border_color=color)
    except tk.TclError:
        pass


def mark_entry(box: ctk.CTkEntry, problem: bool) -> None:
    """Show a text box as wrong (red border) or fine, keeping its focus ring."""
    box.audio8d_problem = problem  # type: ignore[attr-defined]
    _entry_edge(box, box.focus_get() is box._entry)  # pylint: disable=protected-access


class Notice(ctk.CTkFrame):
    """A coloured message line in the page: problem, warning, success or info.

    Each kind has its own icon and, where it helps, a button that fixes it.
    """

    _LOOKS = {
        "error": ("error", DANGER, DANGER_SOFT),
        "warning": ("warning", WARNING, WARNING_SOFT),
        "success": ("check", SUCCESS, SUCCESS_SOFT),
        "info": ("info", ACCENT_TEXT, ACCENT_SOFT),
    }

    def __init__(
        self,
        master: tk.Misc,
        kind: str,
        text: str,
        action: tuple[str, Callable[[], None]] | None = None,
        wrap: int | None = None,
    ) -> None:
        """Draw the line, with an optional (button text, what it does)."""
        icon, color, fill = self._LOOKS[kind]
        super().__init__(master, fg_color=fill, corner_radius=RADIUS)
        self.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            self, text=Icons.glyph(icon), font=Icons.font(15), text_color=color
        ).grid(row=0, column=0, padx=(14, 10), pady=10, sticky="n")
        self.message = ctk.CTkLabel(
            self,
            text=text,
            font=font(13),
            text_color=INK,
            anchor="w",
            justify="left",
            wraplength=wrap or 640,
        )
        self.message.grid(row=0, column=1, sticky="ew", pady=10)
        if wrap is None:
            fit_width(self.message, self, 190 if action else 70)
        if action:
            words, command = action
            button(self, "", words, command, width=110, height=TOOL_HEIGHT).grid(
                row=0, column=2, padx=12, pady=6
            )


# ------------------------------------------------------------------ pages


class Page(ctk.CTkScrollableFrame):
    """A scrolling page with a step label, a title and one short explanation."""

    def __init__(self, master: tk.Misc, step: str, title: str, subtitle: str) -> None:
        """Draw the heading; content goes in rows 2 and below."""
        super().__init__(
            master,
            fg_color="transparent",
            scrollbar_button_color=BORDER_STRONG,
            scrollbar_button_hover_color=TEXT_DIM,
        )
        self.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=28, pady=(22, 14))
        if step:
            ctk.CTkLabel(
                head,
                text=step.upper(),
                font=font(12, "bold"),
                text_color=ACCENT_TEXT,
                anchor="w",
            ).pack(anchor="w")
        ctk.CTkLabel(
            head, text=title, font=font(24, "bold"), text_color=INK, anchor="w"
        ).pack(anchor="w")
        hint(head, subtitle, size=13).pack(anchor="w", fill="x")

    def reveal(self, part: str) -> None:
        """Scroll to a named part of the page (pages that have parts say which)."""

    def add(self, widget: tk.Widget, row: int, pady: tuple[int, int] = (0, 16)) -> None:
        """Place a card on the page."""
        widget.grid(row=row, column=0, sticky="ew", padx=28, pady=pady)

    def footer(
        self,
        row: int,
        back: Callable[[], None] | None,
        text: str,
        forward: Callable[[], None] | None,
    ) -> ctk.CTkFrame:
        """The Back / Next buttons at the bottom of a step."""
        strip = ctk.CTkFrame(self, fg_color="transparent")
        strip.grid(row=row, column=0, sticky="ew", padx=28, pady=(4, 28))
        if back is not None:
            button(strip, "back", "Back", back, width=110).pack(side="left")
        if forward is not None:
            button(strip, "next", text, forward, kind="primary", width=260).pack(
                side="right"
            )
        return strip
