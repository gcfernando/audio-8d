# Developed by ::> Gehan Fernando
"""The window's small extra windows: questions, name boxes and passing messages."""

import os
import tkinter as tk
from collections.abc import Callable
from pathlib import Path

import customtkinter as ctk

from .gui_widgets import (
    ACCENT_TEXT,
    BORDER_STRONG,
    DANGER,
    INK,
    RADIUS,
    SUCCESS,
    SURFACE,
    SURFACE_ALT,
    WARNING,
    Icons,
    button,
    entry,
    font,
)

# The title bar and taskbar icon of every Audio8D window (also the exe's icon)
APP_ICON = Path(__file__).resolve().parent / "assets" / "audio8d.ico"


def use_app_icon(window: tk.Wm) -> None:
    """Show Audio8D's own icon in a window's title bar, where Windows allows it."""
    if os.name == "nt" and APP_ICON.is_file():
        try:
            window.iconbitmap(str(APP_ICON))
        except tk.TclError:
            pass


# How far a popup's inner area sits inside its frame, per display scaling, once seen
_DECORATION: dict[float, tuple[int, int]] = {}


def _scaling(parent: tk.Misc) -> float:
    """The display scaling of the monitor parent is on (frames differ per scaling)."""
    try:
        return float(parent.tk.call("tk", "scaling"))
    except tk.TclError:
        return 1.0


def _centre_target(parent: tk.Misc, width: int, height: int) -> tuple[int, int]:
    """Where a width x height inner area goes to sit in the middle of parent's."""
    # Tk reports the inner area correctly even when the window is maximized
    x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
    return x, y


def _move_frame(window: ctk.CTkToplevel, x: int, y: int, parent: tk.Misc) -> None:
    """Move a popup so its inner area starts at x, y (its title bar stays on screen)."""
    left_edge, title_bar = _DECORATION.get(_scaling(parent), (0, 0))
    # The parent's own title bar is the highest a popup's may go (monitor tops vary)
    highest = min(parent.winfo_rooty() - title_bar, 0)
    # Only the position: CustomTkinter would rescale a size given here
    tk.Wm.wm_geometry(window, f"+{x - left_edge}+{max(highest, y - title_bar)}")


def _set_alpha(window: ctk.CTkToplevel, alpha: float) -> None:
    """See-through while being placed, solid once in place (where Tk allows it)."""
    try:
        window.attributes("-alpha", alpha)
    except tk.TclError:
        pass


def show_centered(
    window: ctk.CTkToplevel, parent: tk.Misc, width: int, height: int
) -> None:
    """Show a popup with its inner area centred over parent's, wherever parent is now.

    width and height are the popup's expected size in pixels. The first popup
    at a display scaling is shown see-through, measured and moved once more,
    which teaches the size of the title bar and borders; later ones are placed
    straight away, without waiting for the rest of the window to redraw.
    """
    parent.update_idletasks()
    scaling = _scaling(parent)
    known = scaling in _DECORATION
    _move_frame(window, *_centre_target(parent, width, height), parent)
    _set_alpha(window, 0.0)
    window.deiconify()
    window.update_idletasks()
    if not known:
        window.update()
        # Where it really landed tells the size of the decorations at this scaling
        frame = tk.Wm.wm_geometry(window).split("+", 1)[1]
        frame_x, frame_y = (int(part) for part in frame.split("+"))
        _DECORATION[scaling] = (
            window.winfo_rootx() - frame_x,
            window.winfo_rooty() - frame_y,
        )
        target = _centre_target(parent, window.winfo_width(), window.winfo_height())
        if target != (window.winfo_rootx(), window.winfo_rooty()):
            _move_frame(window, *target, parent)
            window.update_idletasks()
    _set_alpha(window, 1.0)


def grab_when_shown(window: tk.Toplevel, tries: int = 20) -> None:
    """Make a popup modal as soon as Windows has put it on screen."""
    if not window.winfo_exists():
        return
    try:
        window.grab_set()
    except tk.TclError:
        # Not on screen yet, or another window still holds the grab for a moment
        if tries > 0:
            window.after(50, lambda: grab_when_shown(window, tries - 1))


class Dialog(ctk.CTkToplevel):
    """A small modal window, kept for decisions that can't be undone."""

    def __init__(
        self,
        master: ctk.CTk,
        title: str,
        message: str,
        buttons: list[tuple[str, str]],
        icon: str = "info",
        color: tuple[str, str] = ACCENT_TEXT,
    ) -> None:
        """buttons: (text, key) pairs; the pressed key ends up in self.result."""
        super().__init__(master)
        # Hidden until it has been placed over the main window (see _center)
        self.withdraw()
        self.title(title)
        self.configure(fg_color=SURFACE)
        use_app_icon(self)
        # CustomTkinter puts its own icon on new windows after 200 ms; ours goes back on
        self.after(250, lambda: use_app_icon(self))
        self.result: str | None = None
        self.resizable(False, False)
        self.transient(master)
        self.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            self, text=Icons.glyph(icon), font=Icons.font(30), text_color=color
        ).grid(row=0, column=0, rowspan=2, padx=(24, 12), pady=24, sticky="n")
        ctk.CTkLabel(self, text=title, font=font(16, "bold"), anchor="w").grid(
            row=0, column=1, sticky="w", padx=(0, 24), pady=(24, 4)
        )
        ctk.CTkLabel(
            self,
            text=message,
            font=font(13),
            justify="left",
            anchor="w",
            wraplength=460,
        ).grid(row=1, column=1, sticky="w", padx=(0, 24))
        self.actions = ctk.CTkFrame(self, fg_color="transparent")
        self.actions.grid(row=2, column=0, columnspan=2, sticky="e", padx=24, pady=20)
        # Each button by its key, so a subclass can switch one off
        self.buttons: dict[str, ctk.CTkButton] = {}
        for index, (text, key) in enumerate(buttons):
            primary = index == len(buttons) - 1
            self.buttons[key] = button(
                self.actions,
                "",
                text,
                lambda key=key: self.close(key),
                kind="primary" if primary else "outline",
                width=120,
            )
            self.buttons[key].pack(side="left", padx=(8, 0))
        self.bind("<Escape>", lambda _e: self.close(None))
        self.protocol("WM_DELETE_WINDOW", lambda: self.close(None))
        self.after(50, self._center)

    def _center(self) -> None:
        """Sit in the middle of the main window, and put the focus on a button."""
        self.update_idletasks()
        show_centered(self, self.master, self.winfo_reqwidth(), self.winfo_reqheight())
        self.lift()
        grab_when_shown(self)
        self.focus_force()
        # The safest choice (the first button) gets the focus
        if self.buttons:
            next(iter(self.buttons.values())).focus_set()

    def close(self, key: str | None) -> None:
        """Remember the answer and close."""
        self.result = key
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    def ask(self) -> str | None:
        """Wait until a button is pressed and return its key."""
        self.master.wait_window(self)
        return self.result

    @classmethod
    def confirm(  # pylint: disable=too-many-arguments
        cls,
        master: ctk.CTk,
        title: str,
        message: str,
        yes: str,
        no: str = "Cancel",
        icon: str = "warning",
    ) -> bool:
        """Ask before something that can't easily be undone; True means go ahead."""
        color = WARNING if icon == "warning" else ACCENT_TEXT
        answer = cls(master, title, message, [(no, "no"), (yes, "yes")], icon, color)
        return answer.ask() == "yes"


class NameDialog(Dialog):
    """Asks for a style name, checking it as you type; OK only works when it's valid."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        master: ctk.CTk,
        title: str,
        message: str,
        initial: str,
        check: Callable[[str], tuple[str | None, str | None]],
        ok_text: str = "OK",
    ) -> None:
        """check(text) returns (the name it will get, None) or (None, why not)."""
        super().__init__(master, title, message, [("Cancel", "no"), (ok_text, "ok")])
        self.check_name = check
        self.value: str | None = None
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.grid(row=2, column=1, sticky="ew", padx=(0, 24), pady=(14, 0))
        self.entry = entry(box, "", 320)
        self.entry.grid(row=0, column=0, sticky="w")
        self.entry.insert(0, initial)
        self.note = ctk.CTkLabel(
            box, text="", font=font(12), anchor="w", justify="left", wraplength=440
        )
        self.note.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.actions.grid(row=3, column=0, columnspan=2, sticky="e", padx=24, pady=20)
        self.entry.bind("<KeyRelease>", lambda _e: self.check())
        self.entry.bind("<Return>", lambda _e: self._accept())
        self.check()
        self.after(120, self.entry.focus_set)

    def check(self) -> bool:
        """Show what the name will be, or why it can't be used."""
        name, problem = self.check_name(self.entry.get())
        ok = self.buttons["ok"]
        if problem or not name:
            self.value = None
            self.entry.configure(border_color=DANGER)
            self.note.configure(text=problem or "", text_color=DANGER)
            ok.configure(state="disabled")
            return False
        self.value = name
        self.entry.configure(border_color=BORDER_STRONG)
        self.note.configure(text=f"It will be saved as {name}", text_color=SUCCESS)
        ok.configure(state="normal")
        return True

    def _accept(self) -> None:
        """Enter works like OK, but only for a valid name."""
        if self.check():
            self.close("ok")

    def ask(self) -> str | None:
        """The valid name that was accepted, or None for Cancel."""
        return self.value if super().ask() == "ok" else None


class ErrorDialog(Dialog):
    """A problem in plain words; the technical details wait under 'Show details'."""

    def __init__(self, master: ctk.CTk, message: str, details: str) -> None:
        """message is what people read; details is for whoever helps them."""
        super().__init__(
            master,
            "Something went wrong",
            message,
            [("Copy details", "copy"), ("OK", "ok")],
            icon="error",
            color=DANGER,
        )
        self.details = details.strip() or "No technical details were recorded."
        self.buttons["copy"].configure(command=self._copy)
        self.toggle = button(
            self, "down", "Show details", self._toggle, kind="quiet", width=150
        )
        self.toggle.grid(row=2, column=1, sticky="w", pady=(10, 0))
        self.box = ctk.CTkTextbox(
            self, width=520, height=160, font=("Consolas", 11), wrap="word",
            fg_color=SURFACE_ALT, text_color=INK,  # type: ignore[arg-type]
        )  # fmt: skip
        self.box.insert("1.0", self.details)
        self.box.configure(state="disabled")
        self.actions.grid(row=4, column=0, columnspan=2, sticky="e", padx=24, pady=20)
        self.shown = False

    def _toggle(self) -> None:
        """Show or hide the technical details."""
        self.shown = not self.shown
        if self.shown:
            self.box.grid(row=3, column=0, columnspan=2, sticky="ew", padx=24)
            self.toggle.configure(text="  Hide details")
        else:
            self.box.grid_remove()
            self.toggle.configure(text="  Show details")

    def _copy(self) -> None:
        """Put the details on the clipboard, e.g. to send them to someone helping."""
        self.clipboard_clear()
        self.clipboard_append(self.details)
        self.buttons["copy"].configure(text="Copied")


class Toast(ctk.CTkFrame):
    """A short message in the status bar that goes away by itself."""

    def __init__(self, master: ctk.CTk, text: str, kind: str = "info") -> None:
        """Show text for a few seconds without covering any control."""
        color = {"info": ACCENT_TEXT, "ok": SUCCESS, "error": DANGER}[kind]
        icon = {"info": "info", "ok": "check", "error": "error"}[kind]
        # The app lends its status-bar summary cell; floating would cover buttons
        slot = getattr(master, "toast_slot", None)
        super().__init__(
            slot[0] if slot else master,
            fg_color=SURFACE_ALT,
            corner_radius=RADIUS,
            border_width=1,
            border_color=color,
        )
        ctk.CTkLabel(
            self, text=Icons.glyph(icon), font=Icons.font(15), text_color=color
        ).pack(side="left", padx=(12, 8), pady=4)
        ctk.CTkLabel(self, text=text, font=font(13), text_color=INK).pack(
            side="left", padx=(0, 14), pady=4
        )
        self.slot = slot
        if slot:
            area, hidden = slot
            for other in area.winfo_children():
                if isinstance(other, Toast) and other is not self:
                    other.destroy()
            hidden.grid_remove()
            self.grid(row=0, column=3, sticky="e", padx=(8, 20))
        else:
            self.place(relx=1.0, rely=1.0, x=-24, y=-24, anchor="se")
        self.after(4500, self.destroy)

    def destroy(self) -> None:
        """Hand the status-bar cell back to what it normally shows."""
        try:
            if self.slot and self.winfo_exists():
                area, hidden = self.slot
                others = [
                    w
                    for w in area.winfo_children()
                    if isinstance(w, Toast) and w is not self
                ]
                if not others:
                    hidden.grid()
        except tk.TclError:  # the window itself is closing
            pass
        super().destroy()


# ------------------------------------------------------------------ tables
