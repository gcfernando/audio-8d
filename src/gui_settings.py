# Developed by ::> Gehan Fernando
"""The Settings page: the system check, FFmpeg, the singer add-on, looks and logs.

FFmpeg and FFprobe are found automatically (bundled copy, PATH, usual install
folders) unless you choose them yourself. Test runs both with -version on a
helper thread and shows their versions; nothing is saved until both work.
"""

import logging
import os
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog
from typing import TYPE_CHECKING

import customtkinter as ctk

from . import __author__, __version__
from .analysis import clear_stems_cache
from .core.locations import GUIDE_URL, cache_dir, is_packaged, log_file
from .core.preferences import SCALES, THEMES, preferences_file
from .ffmpeg import ToolCheck, check_tool, locate
from .gui_dialogs import (
    Dialog,
    Toast,
)
from .gui_fields import (
    ChoiceField,
    SwitchField,
    browse_button,
)
from .gui_health import AddonCard, HealthCard
from .gui_widgets import (
    DANGER,
    SUCCESS,
    TEXT_DIM,
    WARNING,
    Badge,
    Card,
    Notice,
    Page,
    button,
    entry,
    flow,
    font,
    hint,
    open_path,
)

if TYPE_CHECKING:
    from .gui_app import Audio8DApp

LOG = logging.getLogger(__name__)

# How to reach the terminal app from here, for the About text
HELP_COMMAND = (
    "audio8d-cli.exe --help"
    if is_packaged()
    else "audio8d --help  (or python src\\__main__.py --help)"
)
_EXE = ".exe" if os.name == "nt" else ""


class ToolRow(ctk.CTkFrame):
    """One tool: where it is, how it was found, whether it works, and Browse."""

    def __init__(self, master: tk.Misc, page: "SettingsPage", name: str) -> None:
        """Build the row for ffmpeg or ffprobe."""
        super().__init__(master, fg_color="transparent")
        self.page = page
        self.name = name
        self.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            self,
            text="FFmpeg" if name == "ffmpeg" else "FFprobe",
            font=font(13, "bold"),
            width=90,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.path = entry(self, f"Found automatically ({name}{_EXE})", 420)
        self.path.grid(row=0, column=1, sticky="ew", padx=(6, 8))
        self.path.bind("<KeyRelease>", lambda _e: page.paths_edited())
        browse_button(self, self._browse, f"Choose {name}{_EXE}").grid(row=0, column=2)
        self.badge = Badge(self, "Not tested", "neutral")
        self.badge.grid(row=0, column=3, padx=(8, 0))
        self.source = hint(self, "", margin=140)
        self.source.grid(row=1, column=1, columnspan=3, sticky="ew", padx=(6, 0))
        self.result = hint(self, "", margin=140)
        self.result.grid(row=2, column=1, columnspan=3, sticky="ew", padx=(6, 0))

    def _browse(self) -> None:
        """Choose the tool's file."""
        chosen = filedialog.askopenfilename(
            title=f"Choose {self.name}{_EXE}",
            filetypes=[("Programs", f"*{_EXE}")] if _EXE else [("All files", "*")],
        )
        if chosen:
            self.path.delete(0, "end")
            self.path.insert(0, str(Path(chosen)))
            self.page.paths_edited()

    def typed(self) -> Path | None:
        """The path in the box, or None for automatic."""
        text = self.path.get().strip().strip('"')
        return Path(text).expanduser() if text else None

    def show_source(self, chosen: Path | None, saved: Path | None) -> None:
        """Say where the tool comes from: chosen by you, or found automatically."""
        if chosen is not None:
            pending = "" if chosen == saved else "  (not saved yet: press Save)"
            self.source.configure(text=f"Chosen by you{pending}", text_color=TEXT_DIM)
            return
        found = locate(self.name) if saved is None else None
        if found is not None and found.path is not None:
            self.source.configure(
                text=f"{found.source_words}: {found.path}", text_color=TEXT_DIM
            )
        else:
            self.source.configure(
                text="Not found automatically. Choose it with Browse.",
                text_color=WARNING,
            )

    def show_check(self, check: ToolCheck | None) -> None:
        """Show the result of a test."""
        if check is None:
            self.badge.show("Testing…", "neutral")
            self.result.configure(text="")
            return
        if check.ok:
            self.badge.show("Working", "success")
            self.result.configure(
                text=f"Version {check.version}  ·  {check.path}", text_color=SUCCESS
            )
        else:
            self.badge.show("Problem", "danger")
            self.result.configure(text=check.problem, text_color=DANGER)


class SettingsPage(Page):
    """FFmpeg and FFprobe, appearance, logs and saved data, and about."""

    def __init__(self, master: tk.Misc, app: "Audio8DApp") -> None:
        """Build the page."""
        super().__init__(
            master,
            "",
            "Settings",
            "What Audio8D depends on and whether it works, the optional singer "
            "add-on, how the window looks, and your logs. Saved in "
            f"{preferences_file().name} in your Audio8D settings folder.",
        )
        self.app = app
        self.checks: dict[str, ToolCheck] = {}
        self.health = HealthCard(self, app)
        self.add(self.health, 2)
        self._build_tools()
        self.addon = AddonCard(self, app)
        self.add(self.addon, 4)
        self._build_look()
        self._build_logs()
        self._build_about()

    # ------------------------------------------------------------ tools

    def _build_tools(self) -> None:
        """FFmpeg and FFprobe: automatic or chosen, tested, and saved."""
        card = self.tools = Card(
            self,
            "FFmpeg and FFprobe (required)",
            "Audio8D needs these two free programs to read and make songs. They are "
            "found automatically; choose them yourself only if you want a different "
            "copy.",
        )
        self.add(card, 3)
        body = card.body
        self.status = ctk.CTkFrame(body, fg_color="transparent", height=1)
        self.status.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.status.grid_columnconfigure(0, weight=1)
        self.rows = {name: ToolRow(body, self, name) for name in ("ffmpeg", "ffprobe")}
        self.rows["ffmpeg"].grid(row=1, column=0, sticky="ew", pady=4)
        self.rows["ffprobe"].grid(row=2, column=0, sticky="ew", pady=4)
        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="w", pady=(10, 0))
        test = button(
            actions,
            "test",
            "Test",
            self.test,
            width=110,
            tooltip="Run both tools and show their versions",
        )
        self.save = button(
            actions,
            "save",
            "Save and use",
            self.save_paths,
            kind="primary",
            width=160,
            tooltip="Test both tools, then use and remember them",
        )
        automatic = button(
            actions,
            "replay",
            "Find automatically",
            self.use_automatic,
            width=190,
            tooltip="Forget the chosen paths and find the tools automatically again",
        )
        flow(actions, (test, self.save, automatic))
        paths = self.app.preferences.tools()
        for name, path in zip(("ffmpeg", "ffprobe"), paths, strict=True):
            if path is not None:
                self.rows[name].path.insert(0, str(path))
        self.paths_edited()

    def paths_edited(self) -> None:
        """A path was typed or browsed: say what is used now (nothing saved yet)."""
        saved: dict[str, Path | None] = dict(
            zip(("ffmpeg", "ffprobe"), self.app.preferences.tools(), strict=True)
        )
        for name, row in self.rows.items():
            row.show_source(row.typed(), saved[name])

    def show_tool_status(self, problem: str | None) -> None:
        """The line at the top: all good, or what's wrong and how to fix it."""
        for child in self.status.winfo_children():
            child.destroy()
        if problem:
            Notice(self.status, "error", problem).grid(row=0, column=0, sticky="ew")
        elif self.checks:
            versions = ", ".join(
                f"{'FFmpeg' if n == 'ffmpeg' else 'FFprobe'} {c.version}"
                for n, c in self.checks.items()
            )
            Notice(self.status, "success", f"Both tools work ({versions}).").grid(
                row=0, column=0, sticky="ew"
            )

    def test(
        self, then: Callable[[bool], None] | None = None, in_use: bool = False
    ) -> None:
        """Run both tools on a helper thread and show what they say.

        in_use says the tested tools are the ones in use; a plain Test of typed,
        unsaved paths only changes this card.
        """
        paths = {
            name: (row.typed() if row.typed() is not None else locate(name).path)
            for name, row in self.rows.items()
        }
        for row in self.rows.values():
            row.show_check(None)

        def work() -> None:
            results = {name: check_tool(name, path) for name, path in paths.items()}
            self.app.events.put(("tools-tested", results, then, in_use))

        threading.Thread(target=work, name="tool-check", daemon=True).start()

    def tested(self, results: dict[str, ToolCheck], then: object) -> None:
        """The test finished (called on the window's thread)."""
        self.checks = results
        for name, check in results.items():
            self.rows[name].show_check(check)
        bad = [check.problem for check in results.values() if not check.ok]
        self.show_tool_status(" ".join(bad) if bad else None)
        if callable(then):
            then(not bad)

    def save_paths(self) -> None:
        """Test both tools; save and use them only if both work."""

        def done(ok: bool) -> None:
            if not ok:
                Toast(self.app, "Not saved: fix the tool problems first", "error")
                return
            self.app.save_tool_paths(
                self.rows["ffmpeg"].typed(), self.rows["ffprobe"].typed()
            )
            self.app.tools_in_use(self.checks)
            self.paths_edited()

        self.test(done)

    def use_automatic(self) -> None:
        """Forget chosen paths, then test what is found automatically."""
        for row in self.rows.values():
            row.path.delete(0, "end")
        self.app.save_tool_paths(None, None)
        self.paths_edited()
        self.test(in_use=True)

    # ------------------------------------------------------------ look

    def _build_look(self) -> None:
        """Theme and size, remembered for next time."""
        look = Card(self, "Appearance")
        self.add(look, 5)
        self.mode = ChoiceField(
            look.body,
            "Theme",
            "System follows your Windows light or dark setting.",
            {theme: theme for theme in THEMES},
            self.app.set_theme,
        )
        self.mode.set(self.app.preferences.theme)
        self.mode.grid(row=0, column=0, sticky="ew", pady=3)
        self.scale = ChoiceField(
            look.body,
            "Size",
            "Makes all text and controls bigger or smaller (on top of Windows' "
            "own display scaling).",
            {f"{round(value * 100)}%": value for value in SCALES},
            self.app.set_scale,  # type: ignore[arg-type]
        )
        self.scale.set(self.app.preferences.scale)
        self.scale.grid(row=1, column=0, sticky="ew", pady=3)
        self.preview_length = ChoiceField(
            look.body,
            "Preview length",
            "How long a preview plays, taken from the loudest part of the song. "
            "Shorter previews are ready sooner.",
            {"15 s": 15, "30 s": 30, "45 s": 45, "60 s": 60},
            self.app.set_preview_seconds,
        )
        self.preview_length.set(self.app.settings.preview_seconds)
        self.preview_length.grid(row=2, column=0, sticky="ew", pady=3)

    # ------------------------------------------------------------ logs

    def _build_logs(self) -> None:
        """Technical details, the log files, and remembered data."""
        card = Card(
            self,
            "Logs and saved data",
            f"The technical log is kept in {log_file().parent}. It helps when "
            "asking for help and contains no audio.",
        )
        self.add(card, 6)
        body = card.body
        self.verbose = SwitchField(
            body,
            "Show technical details",
            "Writes every step into the log (Create step, Technical details). "
            "Handy when asking for help.",
            self.app.set_verbose,
        )
        self.verbose.set(self.app.preferences.verbose)
        self.verbose.grid(row=0, column=0, sticky="ew", pady=3)
        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="w", pady=(8, 0))
        parts = [button(actions, "open", "Open log folder", self._open_logs, width=180)]
        parts.append(
            button(
                actions,
                "delete",
                "Delete saved log files",
                self._delete_logs,
                width=230,
                tooltip="Deletes the log files on disk after asking. The "
                "log view is cleared with Clear log view on the Create step.",
            )
        )
        parts.append(
            button(
                actions,
                "clear",
                "Clear remembered data",
                self._clear_cache,
                width=290,
                tooltip="Deletes the remembered loudness measurements and vocal "
                f"splits in {cache_dir()} after asking. They are made again when "
                "needed.",
            )
        )
        flow(actions, parts)

    def reveal(self, part: str) -> None:
        """Scroll to a part of the page ('health', 'tools' or 'singer')."""
        card = {
            "health": self.health,
            "tools": self.tools,
            "singer": self.addon,
        }.get(part)
        if card is None:
            return
        self.update_idletasks()
        canvas = self._parent_canvas
        top = canvas.bbox("all")[3] or 1
        # Already the position within the page, whatever it is scrolled to
        y = card.winfo_rooty() - self.winfo_rooty()
        canvas.yview_moveto(max(0.0, (y - 20) / top))

    def _open_logs(self) -> None:
        """Show the folder with the technical log."""
        folder = log_file().parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            Toast(self.app, "The log folder can't be created", "error")
            return
        open_path(folder)

    def _delete_logs(self) -> None:
        """Delete the saved log files, after asking."""
        answer = Dialog(
            self.app,
            "Delete the saved log files?",
            "The technical log files on disk will be deleted. They only help when "
            "asking for help; your songs, styles and settings are not touched. A "
            "fresh log starts straight away.",
            [("Cancel", "no"), ("Delete log files", "yes")],
            icon="delete",
            color=DANGER,
        ).ask()
        if answer == "yes":
            self.app.delete_saved_logs()

    def _clear_cache(self) -> None:
        """Delete the remembered measurements and vocal splits, after asking."""
        if self.app.busy:
            Toast(self.app, "Please wait until the songs are created", "error")
            return
        answer = Dialog(
            self.app,
            "Clear the remembered data?",
            "The remembered loudness measurements and the vocal splits made by "
            "the singer add-on will be deleted. They are made again when needed, "
            "so the next songs take a little longer. Your songs, styles and "
            "settings are not touched.",
            [("Cancel", "no"), ("Clear data", "yes")],
            icon="delete",
            color=DANGER,
        ).ask()
        # A conversion may have started while the question was open
        if answer != "yes" or self.app.busy:
            return
        events = self.app.events

        def work() -> None:
            # Vocal splits can be large, so they are deleted off the window's thread
            try:
                (cache_dir() / "loudness.json").unlink(missing_ok=True)
                clear_stems_cache()
            except OSError as exc:
                LOG.warning("Could not clear the remembered data: %s", exc)
                events.put(
                    (
                        "toast",
                        "Some remembered data couldn't be cleared; try again later",
                        "error",
                    )
                )
                return
            events.put(("toast", "Remembered data cleared", "ok"))

        threading.Thread(target=work, name="clear-cache", daemon=True).start()

    # ------------------------------------------------------------ about

    def _build_about(self) -> None:
        """Version, author and the guide."""
        about = Card(self, "About")
        self.add(about, 7, (0, 28))
        ctk.CTkLabel(
            about.body, text=f"Audio8D {__version__}", font=font(18, "bold"), anchor="w"
        ).grid(row=0, column=0, sticky="w")
        hint(
            about.body,
            f"Developed by {__author__}. 3D music for headphones, powered by FFmpeg. "
            f"Everything here can also be done from a terminal: {HELP_COMMAND}",
        ).grid(row=1, column=0, sticky="w", pady=(2, 10))
        button(
            about.body,
            "guide",
            "Open the full guide",
            lambda: self.app.open_link(GUIDE_URL),
            kind="primary",
            width=220,
            tooltip=f"Opens the guide in your browser: {GUIDE_URL}",
        ).grid(row=2, column=0, sticky="w")
