# Developed by ::> Gehan Fernando
"""The window's status bar: overall progress, what is happening, and the settings.

What is happening always shows in full (wrapping if it must); the settings
summary on the right gives way, shortened with '…' or left out.
"""

import tkinter as tk
import tkinter.font as tkfont

import customtkinter as ctk

from .gui_widgets import ACCENT, SURFACE, TEXT_DIM, fit_width, font, set_changed


class StatusBar(ctk.CTkFrame):  # pylint: disable=too-many-ancestors
    """Progress on the left, the current message, and the settings summary."""

    def __init__(self, master: tk.Misc) -> None:
        """Draw the strip; show_summary() fills the right-hand side."""
        super().__init__(
            master, height=48, corner_radius=0, fg_color=SURFACE, border_width=0
        )
        # The summary's column is the one that gives up room, never the message's
        self.grid_columnconfigure(3, weight=1)
        self.overall = ctk.CTkProgressBar(
            self, width=200, height=8, progress_color=ACCENT
        )
        self.overall.set(0)
        self.overall.grid(row=0, column=0, padx=(24, 12), pady=18)
        self.text = ctk.CTkLabel(
            self, text="Ready.", font=font(13), anchor="w", justify="left"
        )
        self.text.grid(row=0, column=1, sticky="w")
        # Wider than the whole strip (very rare), it wraps instead of being cut
        fit_width(self.text, self, 260)
        self.summary = ctk.CTkLabel(
            self, text="", font=font(12), text_color=TEXT_DIM, anchor="e"
        )
        self.summary.grid(row=0, column=3, sticky="ew", padx=(16, 24))
        self.words = ""
        self.summary.bind("<Configure>", lambda _e: self._fit(), add="+")

    def show_summary(self, words: str) -> None:
        """Show the settings summary, as much of it as fits."""
        self.words = words
        self._fit()

    def _fit(self) -> None:
        """Shorten the summary with '…' to the room it has (or leave it out)."""
        label = self.summary
        words = self.words
        width = label.winfo_width()
        if width <= 1:
            # Not laid out yet: the first size change fits it
            set_changed(label, text=words)
            return
        room = width - 8
        if room <= 8:
            # No room left beside the message; the sidebar says the same
            words = ""
        else:
            # The label's own drawn font, so the measure matches what is shown
            # pylint: disable-next=protected-access
            drawn = tkfont.Font(self, font=label._label.cget("font"))
            while words and drawn.measure(words) > room:
                words = words[:-2].rstrip() + "…"
        set_changed(label, text=words)
