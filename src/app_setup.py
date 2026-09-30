# Developed by ::> Gehan Fernando
"""The main window, part: settings: the system check, the add-on, tools and looks."""

import logging
import threading
import tkinter as tk
import webbrowser
from pathlib import Path

import customtkinter as ctk

from . import addons
from .app_base import (
    LOG,
    AppBase,
)
from .core.errors import Audio8DError
from .core.preferences import save_preferences
from .ffmpeg import (
    check_tool,
    locate,
    set_preferred_paths,
)
from .gui_dialogs import (
    Dialog,
)
from .gui_model import apply_output_defaults, gui_words, output_defaults
from .health import HealthReport, addon_items, check_environment
from .library import (
    READY,
    UNREADABLE,
)


class SetupMixin(AppBase):
    """Settings: the system check, the add-on, tools and looks."""

    def singer_changed(self) -> None:
        """The singer add-on's state changed: update every switch for it."""
        dialog = getattr(self, "customize", None)
        if dialog is not None and dialog.is_open:
            dialog.refresh()
        self.refresh_nav()

    def singer_ready(self) -> bool:
        """True when the last check found the singer add-on ready (never blocks)."""
        status = addons.known_status()
        return status is not None and status.ready

    def check_health(self, startup: bool = False) -> None:
        """Run every dependency once, on a helper thread (results come as events)."""
        if self.health_checking:
            return
        self.health_checking = True
        self._show_health()
        python = self.preferences.python()

        def work() -> None:
            report = check_environment(window=True, python=python)
            self.events.put(("health", report, startup))

        threading.Thread(target=work, name="health-check", daemon=True).start()

    def _show_health(self) -> None:
        """Bring the Settings page's system check and add-on card up to date."""
        page = self.live("settings")
        page.health.show(self.health, self.health_checking)
        page.addon.show(
            self.health.addon if self.health else None, self.health_checking
        )

    def _health_done(self, report: HealthReport, startup: bool) -> None:
        """The system check finished (on the window's thread)."""
        was_blocked = bool(self.tools_problem)
        self.health = report
        self.health_checking = False
        if report.addon is not None:
            addons.remember_status(report.addon)
        tools = [item for item in report.blocking if item.key in ("ffmpeg", "ffprobe")]
        self.tools_problem = (
            "FFmpeg or FFprobe isn't working: "
            + " ".join(f"{item.name}: {item.summary}" for item in tools)
            if tools
            else None
        )
        self._show_health()
        self.singer_changed()
        if tools and startup:
            # Nothing can be converted without them, so the fix is shown at once
            self.show_page("settings", focus="health")
            self.toast("Audio8D needs FFmpeg and FFprobe: see Settings", "error")
        elif not tools and was_blocked:
            self.toast("Everything required is ready now", "ok")
            waiting = [
                t for t in self.library.tracks if t.state not in (READY, UNREADABLE)
            ]
            if waiting:
                self._read(waiting)
        elif not startup:
            self.toast(
                "Everything required is ready"
                if report.ok
                else "Some required tools still need fixing",
                "ok" if report.ok else "error",
            )
        self.refresh_nav()

    def check_addon(self) -> None:
        """Check only Python and the singer add-on again (e.g. after installing)."""
        self.addon_checking(True)
        python = self.preferences.python()

        def work() -> None:
            status = addons.check_singer(python)
            self.events.put(("addon", status, None))

        threading.Thread(target=work, name="addon-check", daemon=True).start()

    def addon_checking(self, on: bool) -> None:
        """Show the add-on card as being checked (or not)."""
        page = self.live("settings")
        page.addon.show(  # type: ignore[attr-defined]
            self.health.addon if self.health else None, on
        )

    def _addon_checked(self, status: addons.AddonStatus, note: str | None) -> None:
        """A fresh add-on status: remember it and show it everywhere."""
        addons.remember_status(status)
        if self.health is not None:
            kept = tuple(
                item
                for item in self.health.items
                if item.key not in ("python", "singer")
            )
            self.health = HealthReport(kept + tuple(addon_items(status)), status)
        page = self.live("settings")
        page.health.show(self.health, self.health_checking)
        page.addon.show(status)
        self.singer_changed()
        self.toast(
            note
            or (
                "The add-on is installed: switch it on in Customize for a song"
                if status.ready
                else status.summary()
            ),
            "ok" if status.ready else "info",
        )

    def use_python(self, path: Path | None) -> None:
        """Use and remember this Python for the add-on (None: find one)."""
        self.preferences.python_path = str(path) if path else ""
        addons.set_preferred_python(path)
        self._save_preferences()
        self.check_addon()

    def install_addon(self) -> None:
        """Install the singer add-on into Audio8D's own folder, after asking."""
        status = addons.known_status()
        if status is None or not status.python.ok or status.python.path is None:
            self.toast("A working Python is needed to install the add-on", "error")
            return
        if not Dialog.confirm(
            self,
            "Install the add-on?",
            "Audio8D will download Demucs and PyTorch (about 1 GB) into its own "
            f"add-on folder:\n{addons.addon_dir()}\n\nIt uses Python "
            f"{status.python.version} to set it up, needs an internet connection and "
            "takes a few minutes. Nothing else on your computer is changed, and "
            "Uninstall removes it again.",
            "Install",
            icon="add",
        ):
            return
        self._addon_work("install", status.python.path)

    def repair_addon(self) -> None:
        """Remove and reinstall Audio8D's copy of the add-on, after asking."""
        if not Dialog.confirm(
            self,
            "Repair the add-on?",
            "The add-on folder is deleted and installed again from scratch (about "
            "1 GB is downloaded).",
            "Repair",
            icon="replay",
        ):
            return
        self.addon_checking(True)
        python = self.preferences.python()

        def find() -> None:
            found = addons.find_python(python)
            self.events.put(("addon-base", found))

        threading.Thread(target=find, name="addon-base", daemon=True).start()

    def _addon_base(self, found: addons.PythonCheck) -> None:
        """The Python for a repair was found (or not)."""
        if not found.ok or found.path is None:
            self.check_addon()
            self.toast(f"Repair needs a working Python: {found.problem}", "error")
            return
        self._addon_work("repair", found.path)

    def uninstall_addon(self) -> None:
        """Delete Audio8D's copy of the add-on, after asking."""
        if not Dialog.confirm(
            self,
            "Uninstall the add-on?",
            f"The add-on folder will be deleted:\n{addons.addon_dir()}\n\nAudio8D "
            "keeps working. Songs set to 'Keep the singer in the middle' can't be "
            "created until you install it again or switch that off.",
            "Uninstall",
            icon="delete",
        ):
            return
        self._addon_work("uninstall", None)

    def stop_addon_work(self) -> None:
        """Stop an installation or repair (nothing half-made is kept)."""
        self.addon_cancel.set()

    def _addon_work(self, kind: str, python: Path | None) -> None:
        """Install, repair or uninstall on a helper thread; results come as events."""
        # Asked twice (e.g. two clicks while a question was open): one job at a time
        settings_page = self.pages.get("settings")
        if settings_page is not None and settings_page.addon.installing:
            return
        self.addon_cancel.clear()
        self.live("settings").addon.work_started(kind)  # type: ignore[attr-defined]

        def line(text: str) -> None:
            self.events.put(("addon-line", text))

        def progress(report: addons.AddonProgress) -> None:
            # Reports come from helper threads; the window shows them on its own
            self.events.put(("addon-progress", report))

        def work() -> None:
            try:
                if kind == "uninstall":
                    worked, message = addons.uninstall_addon(
                        progress, self.addon_cancel
                    )
                elif python is None:
                    worked, message = False, "No Python was found to install with."
                elif kind == "repair":
                    worked, message = addons.repair_addon(
                        python,
                        line,
                        self.addon_cancel,
                        progress,
                    )
                else:
                    worked, message = addons.install_addon(
                        python,
                        line,
                        self.addon_cancel,
                        progress,
                    )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                LOG.exception("The add-on %s failed unexpectedly", kind)
                worked, message = False, f"Unexpected problem: {exc}"
            status = addons.check_singer(self.preferences.python())
            self.events.put(("addon-installed", kind, worked, message, status))

        threading.Thread(target=work, name=f"addon-{kind}", daemon=True).start()

    def _addon_done(self, event: tuple) -> None:
        """An installation, repair or removal finished (the add-on was re-checked)."""
        _, kind, worked, message, status = event
        self.live("settings").addon.work_finished(worked, message)
        if worked:
            note = {
                "install": "The add-on is installed",
                "repair": "The add-on was repaired",
                "uninstall": "The add-on was removed; Audio8D works as before",
            }[kind]
        else:
            note = "That didn't work; see the add-on card in Settings for why"
        self._addon_checked(
            status, note if status.ready or kind == "uninstall" else None
        )
        if not worked:
            self.toast(note, "error")

    def open_link(self, url: str) -> None:
        """Open a web page in the normal browser without ever freezing the window."""

        def work() -> None:
            try:
                opened = webbrowser.open(url)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                LOG.warning("Could not open %s: %s", url, exc)
                opened = False
            if not opened:
                self.events.put(("link-failed", url))

        threading.Thread(target=work, name="open-link", daemon=True).start()
        self.toast("Opening in your browser…")

    def _link_failed(self, url: str) -> None:
        """The browser couldn't be started: show the address to copy instead."""
        try:
            self.clipboard_clear()
            self.clipboard_append(url)
            copied = "The address has been copied, so you can paste it"
        except tk.TclError as exc:
            LOG.warning("Could not copy %s: %s", url, exc)
            copied = "You can type this address"
        Dialog(
            self,
            "The browser didn't open",
            f"Audio8D couldn't start your web browser. {copied} into any "
            f"browser:\n\n{url}",
            [("OK", "ok")],
            icon="info",
        )

    def _use_remembered_defaults(self) -> None:
        """Start from the style and output defaults saved at the last session."""
        preferences = self.preferences
        if preferences.default_style in self.presets:
            self.settings.apply_style(self.presets[preferences.default_style])
        self.settings.preview_seconds = preferences.preview_seconds
        ignored = apply_output_defaults(self.settings, preferences.output)
        if ignored:
            LOG.info("Remembered output defaults not used: %s", ", ".join(ignored))
        self._remembered = self._defaults_now()
        self._remember_job: str | None = None

    def _defaults_now(self) -> tuple[str, int, dict[str, object]]:
        """The defaults worth remembering, exactly as they would be saved."""
        settings = self.settings
        return settings.style, settings.preview_seconds, output_defaults(settings)

    def remember_defaults(self) -> None:
        """Save the defaults a moment after they change (a slider moves many times)."""
        if getattr(self, "_remember_job", None):
            self.after_cancel(self._remember_job)  # type: ignore[arg-type]
        self._remember_job = self.after(800, self._save_defaults)

    def _save_defaults(self) -> None:
        """Write the defaults to the settings file, only when they really changed."""
        self._remember_job = None
        now = self._defaults_now()
        if now == self._remembered:
            return
        style, seconds, output = now
        self.preferences.default_style = style
        self.preferences.preview_seconds = seconds
        self.preferences.output = output
        self._remembered = now
        self._save_preferences()

    def set_verbose(self, on: bool, save: bool = True) -> None:
        """'Show technical details': everything, or just the important lines."""
        self.settings.verbose = on
        self.log_handler.setLevel(logging.DEBUG if on else logging.INFO)
        logging.getLogger().setLevel(logging.DEBUG if on else logging.INFO)
        if save:
            self.preferences.verbose = on
            self._save_preferences()

    def _save_preferences(self) -> None:
        """Remember the Settings page's choices."""
        try:
            save_preferences(self.preferences)
        except Audio8DError as exc:
            LOG.warning("%s", exc)
            self.toast("Your settings couldn't be saved", "error")

    def set_theme(self, theme: object) -> None:
        """Light, dark, or like Windows."""
        ctk.set_appearance_mode(str(theme))
        self.preferences.theme = str(theme)
        if "settings" in getattr(self, "pages", {}):
            self.live("settings").mode.set(str(theme))  # type: ignore[attr-defined]
        self._save_preferences()
        self.after(50, self._repaint_tables)

    def set_scale(self, scale: object) -> None:
        """Everything bigger or smaller."""
        ctk.set_widget_scaling(float(scale))  # type: ignore[arg-type]
        self.preferences.scale = float(scale)  # type: ignore[arg-type]
        if "settings" in getattr(self, "pages", {}):
            self.live("settings").scale.set(float(scale))  # type: ignore[attr-defined]
        self._save_preferences()
        self.after(50, self._repaint_tables)

    def _repaint_tables(self) -> None:
        """Tk's tables don't follow CustomTkinter's theme by themselves."""
        self.live("songs").table.paint()  # type: ignore[attr-defined]
        self.live("styles_step").table.paint()  # type: ignore[attr-defined]
        self.live("review").results.paint()  # type: ignore[attr-defined]
        plan = getattr(self.live("review"), "plan_table", None)
        if plan is not None:
            plan.paint()

    def check_tools(self) -> None:
        """Test the FFmpeg and FFprobe in use, in the background."""
        paths = {name: locate(name).path for name in ("ffmpeg", "ffprobe")}

        def work() -> None:
            results = {name: check_tool(name, path) for name, path in paths.items()}
            self.events.put(("tools-tested", results, None, True))

        threading.Thread(target=work, name="tool-check", daemon=True).start()

    def save_tool_paths(self, ffmpeg: Path | None, ffprobe: Path | None) -> None:
        """Use and remember these tools (None: find that one automatically)."""
        self.preferences.ffmpeg_path = str(ffmpeg) if ffmpeg else ""
        self.preferences.ffprobe_path = str(ffprobe) if ffprobe else ""
        set_preferred_paths(ffmpeg, ffprobe)
        self._save_preferences()
        self.toast("FFmpeg settings saved", "ok")
        # Songs that couldn't be read for want of FFmpeg are read again now
        waiting = [t for t in self.library.tracks if t.state not in (READY, UNREADABLE)]
        if waiting:
            self._read(waiting)

    def _tools_tested(self, results: dict, then: object, in_use: bool) -> None:
        """A tool test finished; only the tools in use count for the steps."""
        self.live("settings").tested(results, then)  # type: ignore[attr-defined]
        if in_use:
            self.tools_in_use(results)

    def _tools_missing(self, event: tuple) -> None:
        """Songs couldn't be read for want of FFmpeg or FFprobe."""
        self.tools_problem = gui_words(event[1])
        self.status_text.configure(text="FFmpeg is needed to read the songs.")
        self.toast("FFmpeg or FFprobe is missing: open Settings", "error")
        self.refresh_nav()

    def tools_in_use(self, results: dict) -> None:
        """Remember how the tools in use did, for the steps to show any problem."""
        bad = [check.problem for check in results.values() if not check.ok]
        self.tools_problem = (
            "FFmpeg or FFprobe isn't working: " + " ".join(bad) if bad else None
        )
        self.tool_checks = results
        self.refresh_nav()
