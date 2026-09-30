# Developed by ::> Gehan Fernando
"""The Settings page's system check and the singer add-on's step-by-step setup.

The system check shows every dependency with a status in words (Ready,
Missing, Invalid, Optional, Unavailable), what it is for and what to do.
The add-on card explains what the optional add-on does, what it changes and
how to remove it, shows whether it is installed, and installs, repairs or
uninstalls it (the work itself is in addons.py, shared with the terminal).
"""

import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from typing import TYPE_CHECKING

import customtkinter as ctk

from .addons import (
    ADDON_INFO,
    DONE_INSTALL,
    DONE_UNINSTALL,
    MIN_PYTHON,
    AddonProgress,
    AddonStatus,
)
from .core.locations import addon_dir
from .gui_fields import (
    LearnMore,
    browse_button,
)
from .gui_widgets import (
    DANGER,
    INK,
    PANEL_RADIUS,
    SUCCESS,
    SURFACE_ALT,
    TEXT_DIM,
    TOOL_HEIGHT,
    WARNING,
    Badge,
    Card,
    Notice,
    StatusBadge,
    button,
    clear_children,
    entry,
    font,
    hint,
)
from .health import STATE_WORDS, HealthReport

if TYPE_CHECKING:
    from .gui_app import Audio8DApp

PYTHON_DOWNLOAD = "https://www.python.org/downloads/"
# Which part of Settings fixes each dependency
_FIX_PART = {
    "ffmpeg": "tools",
    "ffprobe": "tools",
    "python": "singer",
    "singer": "singer",
}


class HealthCard(Card):
    """Every dependency with its status, why it matters and what to do."""

    def __init__(self, master: tk.Misc, app: "Audio8DApp") -> None:
        """Draw the card; show() fills it in."""
        super().__init__(
            master,
            "System check",
            "Audio8D runs each tool it depends on to be sure it really works. Required "
            "ones must be ready before creating; optional ones only add features.",
        )
        self.app = app
        body = self.body
        body.grid_columnconfigure(0, weight=1)
        self.summary = ctk.CTkFrame(body, fg_color="transparent", height=1)
        self.summary.grid(row=0, column=0, sticky="ew")
        self.summary.grid_columnconfigure(0, weight=1)
        self.rows = ctk.CTkFrame(body, fg_color="transparent")
        self.rows.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.rows.grid_columnconfigure(2, weight=1)
        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        self.again = button(
            actions,
            "replay",
            "Check everything again",
            app.check_health,
            width=240,
            tooltip="Run every tool again, e.g. after installing something yourself",
        )
        self.again.pack(side="left")
        self.when = hint(actions, "", wrap=420)
        self.when.pack(side="left", padx=12)
        self.details = ctk.CTkFrame(body, fg_color="transparent", height=1)
        self.details.grid(row=3, column=0, sticky="ew")
        self.details.grid_columnconfigure(0, weight=1)
        self.show(None, checking=True)

    def show(self, report: HealthReport | None, checking: bool = False) -> None:
        """Show the latest check (None while the first one is running)."""
        clear_children(self.summary)
        clear_children(self.rows)
        clear_children(self.details)
        self.again.configure(state="disabled" if checking else "normal")
        if report is None:
            Notice(
                self.summary,
                "info",
                "Checking FFmpeg, FFprobe, Python and the singer add-on…",
            ).grid(row=0, column=0, sticky="ew")
            self.when.configure(text="")
            return
        if report.ok:
            text = "Everything Audio8D needs is ready." + (
                " The optional singer add-on is ready too."
                if report.singer_ready
                else " Optional add-ons can be set up below whenever you like."
            )
            Notice(self.summary, "success", text).grid(row=0, column=0, sticky="ew")
        else:
            names = " and ".join(item.name for item in report.blocking)
            Notice(
                self.summary,
                "error",
                f"Audio8D can't create songs yet: {names} must be fixed first. Adding "
                "songs and choosing styles still works; see the red lines below.",
            ).grid(row=0, column=0, sticky="ew")
        for row, item in enumerate(report.items):
            StatusBadge(self.rows, item.state, item.state_words).grid(
                row=row, column=0, sticky="nw", padx=(0, 10), pady=6
            )
            name = ctk.CTkFrame(self.rows, fg_color="transparent")
            name.grid(row=row, column=1, sticky="nw", pady=6)
            ctk.CTkLabel(name, text=item.name, font=font(13, "bold"), anchor="w").pack(
                anchor="w"
            )
            Badge(
                name,
                "Required" if item.required else "Optional",
                "accent" if item.required else "neutral",
            ).pack(anchor="w", pady=(2, 0))
            words = ctk.CTkFrame(self.rows, fg_color="transparent")
            words.grid(row=row, column=2, sticky="ew", padx=(12, 0), pady=6)
            words.grid_columnconfigure(0, weight=1)
            hint(words, item.summary, INK, margin=40, size=13).grid(
                row=0, column=0, sticky="ew"
            )
            hint(words, f"Used to {item.purpose}.", margin=40).grid(
                row=1, column=0, sticky="ew"
            )
            if item.fix and not item.ok:
                hint(
                    words,
                    f"What to do: {item.fix}",
                    DANGER if item.required else WARNING,
                    margin=40,
                ).grid(row=2, column=0, sticky="ew")
            part = _FIX_PART.get(item.key)
            if part and not item.ok:
                button(
                    self.rows,
                    "next",
                    "Fix it" if item.required else "Set it up",
                    lambda p=part: self.app.live("settings").reveal(p),
                    width=120,
                    height=TOOL_HEIGHT,
                ).grid(row=row, column=3, sticky="ne", padx=(8, 0), pady=6)
        technical = "\n".join(
            f"{item.name}: {STATE_WORDS[item.state]}. {item.detail}".strip()
            for item in report.items
        )
        LearnMore(self.details, technical, "Technical details").grid(
            row=0, column=0, sticky="ew", pady=(6, 0)
        )
        self.when.configure(
            text="Checking again…"
            if checking
            else f"Last checked at {time.strftime('%H:%M:%S')}."
        )


class _PythonRow(ctk.CTkFrame):
    """The Python used to install the add-on: found automatically, or chosen."""

    def __init__(self, master: tk.Misc, app: "Audio8DApp") -> None:
        """A path box with Browse, 'Use this Python' and 'Find automatically'."""
        # Untinted like the rest of the card; its bold heading sets it apart
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self, text="Python used to install it", font=font(13, "bold"), anchor="w"
        ).grid(row=0, column=0, sticky="ew")
        self.state = hint(self, "", margin=40)
        self.state.grid(row=1, column=0, sticky="ew")
        line = ctk.CTkFrame(self, fg_color="transparent")
        line.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        line.grid_columnconfigure(0, weight=1)
        self.path = entry(line, "Found automatically (python.exe)", 360)
        self.path.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        browse_button(line, self._browse).grid(row=0, column=1)
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="w", pady=(6, 0))
        button(
            actions,
            "check",
            "Use this Python",
            self._use_typed,
            width=170,
            height=TOOL_HEIGHT,
            tooltip="Run the Python in the box and use it to install the add-on",
        ).pack(side="left", padx=(0, 8))
        button(
            actions,
            "replay",
            "Find automatically",
            lambda: app.use_python(None),
            width=190,
            height=TOOL_HEIGHT,
        ).pack(side="left", padx=(0, 8))
        self.download = button(
            actions,
            "open",
            "Download Python",
            lambda: app.open_link(PYTHON_DOWNLOAD),
            kind="quiet",
            width=190,
            height=TOOL_HEIGHT,
        )

    def show(self, status: AddonStatus) -> None:
        """Whether a Python to install with was found, and how to get one if not."""
        chosen = self.app.preferences.python()
        if self.path.get().strip() != str(chosen or ""):
            self.path.delete(0, "end")
            if chosen is not None:
                self.path.insert(0, str(chosen))
        python = status.python
        if python.ok:
            self.state.configure(
                text=f"Python {python.version} will be used "
                f"({python.source_words}: {python.path}).",
                text_color=TEXT_DIM,
            )
            self.download.pack_forget()
            return
        self.state.configure(
            text=f"{python.problem} Installing needs Python "
            f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer (64-bit): get it from "
            "python.org, tick 'Add python.exe to PATH' in its installer, then press "
            "'Find automatically'.",
            text_color=WARNING,
        )
        self.download.pack(side="left")

    def _browse(self) -> None:
        """Choose python.exe, then check and use it."""
        chosen = filedialog.askopenfilename(
            title="Choose python.exe",
            filetypes=[("Python", "python*.exe"), ("Programs", "*.exe")],
        )
        if chosen:
            self.path.delete(0, "end")
            self.path.insert(0, str(Path(chosen)))
            self._use_typed()

    def _use_typed(self) -> None:
        """Check the Python in the box and use it (empty: find one automatically)."""
        text = self.path.get().strip().strip('"')
        self.app.use_python(Path(text).expanduser() if text else None)


# The card shows and hides a fixed set of parts rather than rebuilding them
class AddonCard(Card):  # pylint: disable=too-many-instance-attributes
    """The optional singer add-on: what it is, whether it's installed, and actions."""

    def __init__(self, master: tk.Misc, app: "Audio8DApp") -> None:
        """Draw the explanation, the status line and every action; show() picks."""
        super().__init__(
            master,
            "Add-on: Keep the singer in the middle (optional)",
            "Audio8D works fully without it. Read what it does before installing.",
        )
        self.app = app
        # What is running: "", "install", "repair" or "uninstall"
        self.working = ""
        body = self.body
        body.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(body, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(1, weight=1)
        self.badge = StatusBadge(top)
        self.badge.grid(row=0, column=0, sticky="w")
        self.summary = hint(top, "", INK, margin=260, size=13)
        self.summary.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        info = ctk.CTkFrame(body, fg_color="transparent")
        info.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        for column in range(2):
            info.grid_columnconfigure(column, weight=1, uniform="addon")
        for index, (title, text) in enumerate(ADDON_INFO):
            box = ctk.CTkFrame(info, fg_color=SURFACE_ALT, corner_radius=PANEL_RADIUS)
            box.grid(row=index // 2, column=index % 2, sticky="nsew", padx=4, pady=4)
            box.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(box, text=title, font=font(13, "bold"), anchor="w").grid(
                row=0, column=0, sticky="ew", padx=12, pady=(10, 0)
            )
            # Wrapped to the box, which takes half the card whatever the window size
            hint(box, text, INK, margin=24).grid(
                row=1, column=0, sticky="ew", padx=12, pady=(2, 10)
            )
        self.python_row = _PythonRow(body, app)
        self.python_row.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.where = hint(body, "", margin=40)
        self.where.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.where.grid_remove()
        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=4, column=0, sticky="w", pady=(10, 0))
        self.install = button(
            actions,
            "add",
            "Install add-on",
            app.install_addon,
            kind="primary",
            width=190,
            tooltip="Asks first; downloads about 1 GB into Audio8D's add-on folder",
        )
        self.repair = button(
            actions,
            "replay",
            "Repair (reinstall)",
            app.repair_addon,
            width=200,
            tooltip="Deletes the add-on folder and installs it again from scratch",
        )
        self.uninstall = button(
            actions,
            "delete",
            "Uninstall add-on",
            app.uninstall_addon,
            width=200,
            tooltip="Asks first, then deletes the add-on folder",
        )
        self.stop = button(
            actions,
            "stop",
            "Stop",
            app.stop_addon_work,
            kind="danger",
            width=110,
            tooltip="Stops the installation; nothing half-made is kept",
        )
        self.again = button(
            actions,
            "replay",
            "Check again",
            app.check_addon,
            width=150,
            tooltip="Look again, e.g. after installing Python",
        )
        self.buttons = (self.install, self.repair, self.uninstall, self.stop)
        self.progress = ctk.CTkProgressBar(body, mode="indeterminate", height=8)
        self.progress_running = False
        # The largest share of the work reported so far (the bar never goes back)
        self.done_share = 0.0
        self.progress_text = hint(body, "", margin=40)
        self.log_toggle = LearnMore(body, "", "Show details")
        self.show(None, checking=True)

    @property
    def installing(self) -> bool:
        """True while an installation, repair or removal is running."""
        return bool(self.working)

    def show(self, status: AddonStatus | None, checking: bool = False) -> None:
        """Show the latest status and the actions that fit it."""
        for part in (*self.buttons, self.again):
            part.pack_forget()
        if self.working:
            self.stop.pack(side="left", padx=(0, 8))
            if self.working == "uninstall":
                self.stop.pack_forget()
            return
        if status is None or checking:
            self.badge.set_state("checking", "Checking…")
            self.summary.configure(text="Looking for the add-on…")
            self.python_row.grid_remove()
            self._show_where("")
            return
        if status.ready:
            self.badge.set_state("ready", "Installed")
        elif status.private or status.state == "partial":
            self.badge.set_state("invalid", "Needs repair")
        else:
            self.badge.set_state("optional", "Not installed")
        self.summary.configure(text=status.summary())
        self._show_actions(status)

    def _show_where(self, text: str) -> None:
        """The line about where the add-on lives, hidden when empty."""
        self.where.configure(text=text)
        if text:
            self.where.grid()
        else:
            self.where.grid_remove()

    def _show_actions(self, status: AddonStatus) -> None:
        """Install when missing; Uninstall and Repair for Audio8D's own copy."""
        own = status.ready and not status.private
        if status.private:
            self.python_row.grid_remove()
            self._show_where(
                f"Installed in {addon_dir()}. Use it: Customize a song on step 2 "
                "and switch on 'Keep the singer in the middle'."
                if status.ready
                else f"The add-on folder {addon_dir()} is incomplete. Repair installs "
                "it again; Uninstall removes it."
            )
            if status.ready:
                self.uninstall.pack(side="left", padx=(0, 8))
                self.repair.pack(side="left", padx=(0, 8))
            else:
                self.repair.pack(side="left", padx=(0, 8))
                self.uninstall.pack(side="left", padx=(0, 8))
        elif own:
            self.python_row.grid_remove()
            self._show_where(
                f"Found in your own Python ({status.python.path}). Audio8D didn't "
                "install this copy, so it won't uninstall it; remove it with: "
                f'"{status.python.path}" -m pip uninstall demucs'
            )
        else:
            self.python_row.grid()
            self.python_row.show(status)
            self._show_where("")
            self.install.pack(side="left", padx=(0, 8))
            self.install.configure(state="normal" if status.python.ok else "disabled")
        self.again.pack(side="left", padx=(0, 8))

    def work_started(self, kind: str) -> None:
        """An installation, repair or removal began: progress, its output and Stop."""
        self.working = kind
        self.done_share = 0.0
        self.show(None)
        self.badge.set_state(
            "checking", "Removing…" if kind == "uninstall" else "Installing…"
        )
        self.summary.configure(
            text="Removing the add-on folder…"
            if kind == "uninstall"
            else "Downloading and installing (about 1 GB, a few minutes). You can keep "
            "using Audio8D."
        )
        self.python_row.grid_remove()
        self.log_toggle.text.configure(text="")
        self.progress.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        self._busy(True)
        self.progress_text.configure(text="Starting…", text_color=TEXT_DIM)
        self.progress_text.grid(row=6, column=0, sticky="ew", pady=(4, 0))
        self.log_toggle.grid(row=7, column=0, sticky="ew")

    def _busy(self, on: bool) -> None:
        """A moving bar while a step can't be measured, a filling one when it can."""
        if on and self.progress.cget("mode") != "indeterminate":
            self.progress.configure(mode="indeterminate")
            self.progress.start()
        elif not on and self.progress.cget("mode") != "determinate":
            self.progress.stop()
            self.progress.configure(mode="determinate")
        elif on and not self.progress_running:
            self.progress.start()
        self.progress_running = on

    def work_progress(self, report: AddonProgress) -> None:
        """A measured step of the work: the bar only ever moves forward."""
        if not self.working or report.finished:
            return
        if report.overall is None:
            self._busy(True)
        else:
            self._busy(False)
            self.done_share = max(self.done_share, report.overall)
            self.progress.set(self.done_share)
        # The number shown always matches the bar
        words = report.stage
        if report.overall is not None:
            words = f"{words} — {int(self.done_share * 100)}%"
        if report.detail:
            words = f"{words} · {report.detail}"
        self.progress_text.configure(text=words[:140], text_color=TEXT_DIM)

    def work_line(self, line: str) -> None:
        """One line of pip's (or venv's) output, kept under Show details."""
        shown = self.log_toggle.text.cget("text")
        lines = (shown.splitlines() + [line])[-60:]
        self.log_toggle.text.configure(text="\n".join(lines))

    def work_finished(self, ok: bool, message: str) -> None:
        """It finished (the add-on was already checked again)."""
        kind, self.working = self.working, ""
        self._busy(False)
        if ok:
            # 100% is shown only here, after the work really succeeded
            self.progress.set(1.0)
            done = DONE_UNINSTALL if kind == "uninstall" else DONE_INSTALL
            text = f"{done} — 100%"
            # A short note ("nothing was changed") is worth adding; pip's output isn't
            if message and "\n" not in message and len(message) < 160:
                text = f"{text}. {message}"
            self.progress_text.configure(text=text[:300], text_color=SUCCESS)
        else:
            self.progress.set(self.done_share)
            stopped = f" (stopped at {int(self.done_share * 100)}%)"
            self.progress_text.configure(
                text=_friendly_failure(message) + stopped, text_color=DANGER
            )
            if message:
                self.work_line(message.splitlines()[-1])


def _friendly_failure(message: str) -> str:
    """What went wrong with the add-on, in plain words (details stay in the log)."""
    text = message.lower()
    if "stopped" in text:
        return "Stopped. Nothing half-installed was kept."
    if "in use or protected" in text or "your own python" in text:
        return message
    if "no module named pip" in text or "ensurepip" in text:
        return (
            "That Python can't install packages (it has no pip). Choose another "
            "Python, or reinstall Python from python.org."
        )
    if "permission" in text or "access is denied" in text:
        return (
            "Audio8D wasn't allowed to write the add-on folder. Close other copies "
            "of Audio8D and try again."
        )
    return (
        "The installation didn't finish. Check the internet connection and try "
        "again; 'Show details' has pip's own words."
    )
