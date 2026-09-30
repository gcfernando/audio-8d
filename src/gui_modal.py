# Developed by ::> Gehan Fernando
"""A reusable modal window: built once, then only shown and hidden.

Building CustomTkinter widgets is the slow part of any dialog, so the style
chooser and the Customize dialog are made once and reused: opening one again
is instant and never makes the window slower over time. While one is open it
holds the keyboard and mouse (Tab stays inside it), Esc cancels and Enter
applies.
"""

import tkinter as tk

import customtkinter as ctk

from .gui_dialogs import grab_when_shown, show_centered, use_app_icon
from .gui_widgets import BORDER, SURFACE, SURFACE_ALT, font, hint


class Modal(ctk.CTkToplevel):
    """A dialog with a title, a scrolling body and a fixed footer for its buttons."""

    def __init__(
        self, master: ctk.CTk, title: str, size: tuple[int, int] = (860, 680)
    ) -> None:
        """Make the frame of the dialog; subclasses fill .body and .footer."""
        super().__init__(master)
        self.withdraw()
        self.app_window = master
        self.title(title)
        self.configure(fg_color=SURFACE)
        use_app_icon(self)
        # CustomTkinter sets its own icon on new windows after 200 ms; ours goes back
        self.after(250, lambda: use_app_icon(self))
        self.transient(master)
        self.minsize(640, 460)
        self.size = size
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.heading = ctk.CTkLabel(
            self, text=title, font=font(20, "bold"), anchor="w", justify="left"
        )
        self.heading.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 0))
        # A fixed wrap: fitting to the toplevel would react to every child's resize
        self.subheading = hint(self, "", size=13, wrap=size[0] - 60)
        self.subheading.grid(row=1, column=0, sticky="ew", padx=24, pady=(2, 10))
        self.body = ctk.CTkScrollableFrame(
            self, fg_color=SURFACE_ALT, corner_radius=10, border_width=1,
            border_color=BORDER,
        )  # fmt: skip
        self.body.grid(row=2, column=0, sticky="nsew", padx=20)
        self.body.grid_columnconfigure(0, weight=1)
        self.footer = ctk.CTkFrame(self, fg_color="transparent")
        self.footer.grid(row=3, column=0, sticky="ew", padx=20, pady=16)
        self.footer.grid_columnconfigure(0, weight=1)
        self.is_open = False
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", lambda _e: self.cancel())
        self.bind("<Return>", self._enter)
        self.bind("<KP_Enter>", self._enter)

    def _enter(self, event: tk.Event) -> str | None:
        """Enter applies, except inside a text box, where it only ends the typing."""
        if isinstance(event.widget, tk.Entry):
            return None
        self.apply()
        return "break"

    def show_modal(self, first_focus: tk.Misc | None = None) -> None:
        """Show the dialog over the main window and take the keyboard and mouse."""
        width, height = self.size
        self.geometry(f"{width}x{height}")
        # The size is scaled with the display, so the centre is worked out in pixels
        show_centered(
            self,
            self.app_window,
            self._apply_window_scaling(width),
            self._apply_window_scaling(height),
        )
        self.lift()
        self.is_open = True
        grab_when_shown(self)
        self.focus_force()
        if first_focus is not None:
            self.after(60, first_focus.focus_set)

    def hide(self) -> None:
        """Put the dialog away (it is kept, so the next opening is instant)."""
        self.is_open = False
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.withdraw()
        self.app_window.focus_force()

    def apply(self) -> None:
        """Enter or the Apply button: subclasses do their work, then hide()."""
        self.hide()

    def cancel(self) -> None:
        """Esc, Cancel or the close button: nothing is changed."""
        self.hide()
