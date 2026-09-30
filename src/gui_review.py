# Developed by ::> Gehan Fernando
"""Step 4 of the window: a short summary, anything to fix, Create, the results."""

import tkinter as tk
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

import customtkinter as ctk

from .gui_fields import (
    SwitchField,
)
from .gui_model import (
    GuiSettings,
)
from .gui_table import Column, SongTable
from .gui_widgets import (
    ACCENT,
    BORDER,
    DANGER,
    HERO_HEIGHT,
    INK,
    SURFACE_ALT,
    TEXT_DIM,
    TOOL_HEIGHT,
    TOOL_WIDTH,
    WHITE,
    Card,
    Notice,
    Page,
    Section,
    button,
    clear_children,
    fit_width,
    flow,
    font,
    hint,
    icon_text,
)

if TYPE_CHECKING:
    from .gui_app import Audio8DApp


def show_summary(body: ctk.CTkFrame, app: "Audio8DApp") -> None:
    """Fill a card with the short summary, one plain line per choice."""
    rows = app.summary_rows()
    # Redrawn only when something changed: rebuilding it costs drawing time
    if getattr(body, "audio8d_rows", None) == rows:
        return
    body.audio8d_rows = rows  # type: ignore[attr-defined]
    clear_children(body)
    body.grid_columnconfigure(0, weight=0)
    body.grid_columnconfigure(1, weight=1)
    for row, (label, value) in enumerate(rows):
        ctk.CTkLabel(
            body, text=label, font=font(13), text_color=TEXT_DIM, width=150, anchor="w"
        ).grid(row=row, column=0, sticky="nw", pady=2)
        text = ctk.CTkLabel(
            body, text=value, font=font(13), anchor="w", justify="left", wraplength=640
        )
        text.grid(row=row, column=1, sticky="ew", pady=2)
        fit_width(text, body, 170)


# A page keeps a reference to every control it updates while songs convert
class ConvertPage(Page):  # pylint: disable=too-many-instance-attributes
    """Step 4: the summary, anything to fix, then creating and the results."""

    COLUMNS = (
        Column("name", "Song", 260, stretch=True),
        Column("style", "Style", 120),
        Column("status", "Status", 150),
        # The loudness and tempo come first in it, so they need this much room
        Column("result", "Result", 330, stretch=True, least=260),
    )

    def __init__(self, master: tk.Misc, app: "Audio8DApp") -> None:
        """Build the page."""
        super().__init__(
            master,
            "Step 4 of 4",
            "Create",
            "Check the summary, then create your 8D songs. You can stop at any time; "
            "finished songs are kept.",
        )
        self.app = app
        self.summary = Card(
            self,
            "Summary",
            "What Create will do. Nothing has been made yet.",
        )
        self.add(self.summary, 2)
        self.plan = Section(
            self,
            "Every song in detail",
            "Each song's sound, file and exactly where its new file will be saved.",
            build=self._fill_plan,
        )
        self.add(self.plan, 3, (0, 16))
        self.notes = ctk.CTkFrame(self, fg_color="transparent", height=1)
        self.add(self.notes, 4, (0, 8))
        self.notes.grid_columnconfigure(0, weight=1)
        # Made the first time 'Each song' opens
        self.plan_table: SongTable | None = None
        # The notes last drawn, so they are only rebuilt when they change
        self._notes_shown: tuple[list, list] | None = None
        # The newest log lines; drawn into the view only while it can be seen
        self.log_buffer: deque[str] = deque(maxlen=self.MAX_LOG_LINES)
        self.log_stale = False
        self._build_run()
        self._build_log()

    def _build_run(self) -> None:
        """Start and Stop, the progress, and the results table."""
        app = self.app
        run = Card(self, "Create your 8D songs")
        self.add(run, 5)
        body = run.body
        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=0, column=0, sticky="ew")
        actions.grid_columnconfigure(2, weight=1)
        self.start = button(
            actions,
            "play",
            "Create songs",
            app.run_convert,
            kind="primary",
            width=280,
            height=HERO_HEIGHT,
            tooltip="Make the 8D version of every song and save it (Ctrl+Enter)",
        )
        self.start.grid(row=0, column=0)
        self.stop = button(
            actions,
            "stop",
            "Stop",
            app.stop,
            kind="danger",
            width=110,
            height=HERO_HEIGHT,
            tooltip="Stop after the current step; finished songs are kept (Esc)",
        )
        self.stop.grid(row=0, column=1, padx=8)
        # Under the buttons, so it has the card's width even at a large size
        self.start_note = hint(actions, "", margin=40)
        self.start_note.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        progress = ctk.CTkFrame(body, fg_color="transparent")
        progress.grid(row=1, column=0, sticky="ew", pady=(14, 6))
        progress.grid_columnconfigure(1, weight=1)
        self.run_bar = ctk.CTkProgressBar(progress, height=10, progress_color=ACCENT)
        self.run_bar.set(0)
        self.run_bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.progress_text = ctk.CTkLabel(
            progress, text="Nothing created yet.", font=font(13), anchor="w"
        )
        self.progress_text.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.result_note = ctk.CTkFrame(body, fg_color="transparent", height=1)
        self.result_note.grid(row=2, column=0, sticky="ew")
        self.result_note.grid_columnconfigure(0, weight=1)
        tools = ctk.CTkFrame(body, fg_color="transparent")
        tools.grid(row=3, column=0, sticky="ew", pady=(6, 6))
        self.only_problems = SwitchField(
            tools, "Show only songs with a problem", "", lambda _on: self.show_results()
        )
        self.only_problems.help.grid_remove()
        self.only_problems.grid(row=0, column=0, sticky="w")
        actions = ctk.CTkFrame(tools, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.play_song = button(
            actions,
            "play",
            "Play",
            self._play_selected,
            width=TOOL_WIDTH,
            height=TOOL_HEIGHT,
        )
        self.open_folder = button(
            actions,
            "open",
            "Open folder",
            self._open_folder,
            width=TOOL_WIDTH,
            height=TOOL_HEIGHT,
            tooltip="Open the folder of the selected (or first) new song",
        )
        self.copy = button(
            actions,
            "copy",
            "Copy problem list",
            self._copy_problems,
            width=TOOL_WIDTH,
            height=TOOL_HEIGHT,
        )
        self.retry = button(
            actions,
            "replay",
            "Try failed songs again",
            app.retry_failed,
            width=TOOL_WIDTH,
            height=TOOL_HEIGHT,
        )
        # A toolbar like 'Your songs': it wraps onto a second line when narrow
        flow(actions, (self.play_song, self.open_folder, self.copy, self.retry))
        self.results = SongTable(
            body,
            self.COLUMNS,
            height=10,
            on_activate=lambda _iid: self._play_selected(),
            label="Results",
        )
        self.results.grid(row=4, column=0, sticky="ew")

    def _build_log(self) -> None:
        """The technical log, folded away."""
        app = self.app
        self.details = Section(
            self,
            "Technical details (log)",
            "What Audio8D is doing behind the scenes. Useful when asking for help.",
        )
        self.add(self.details, 6, (0, 28))
        log_body = self.details.body
        log_tools = ctk.CTkFrame(log_body, fg_color="transparent")
        log_tools.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        log_tools.grid_columnconfigure(2, weight=1)
        button(
            log_tools,
            "clear",
            "Clear log view",
            app.clear_log_view,
            width=130,
            height=TOOL_HEIGHT,
            tooltip="Empty this view. Saved log files are kept "
            "(delete those in Settings).",
        ).grid(row=0, column=0)
        self.autoscroll = SwitchField(
            log_tools, "Follow new lines", "", lambda _on: None
        )
        self.autoscroll.help.grid_remove()
        self.autoscroll.set(True)
        self.autoscroll.grid(row=0, column=1, padx=(10, 0))
        hint(
            log_tools,
            "Clear log view empties this view only; your saved log files are "
            "kept (Settings, Logs and saved data).",
            margin=460,
        ).grid(row=0, column=2, sticky="ew", padx=(10, 0))
        self.log = ctk.CTkTextbox(
            log_body,
            height=200,
            font=("Consolas", 11),
            wrap="none",
            fg_color=SURFACE_ALT,
            # CTk takes a (light, dark) pair here, though its hint says str
            text_color=INK,  # type: ignore[arg-type]
            border_width=1,
            border_color=BORDER,
        )
        self.log.grid(row=1, column=0, sticky="ew")
        self.log.configure(state="disabled")
        self.details.toggle_button.configure(command=self._toggle_details)

    # ------------------------------------------------------------ the log

    MAX_LOG_LINES = 3000

    @property
    def log_lines(self) -> int:
        """How many lines the log holds (the newest MAX_LOG_LINES at most)."""
        return len(self.log_buffer)

    def write_log(self, lines: list[str]) -> None:
        """Keep new lines; they are drawn only while the log can be seen."""
        if not lines:
            return
        self.log_buffer.extend(lines)
        # A long log redrawn out of sight made the whole window stall
        if self._log_visible():
            self._draw_log(lines)
        else:
            self.log_stale = True

    def _log_visible(self) -> bool:
        """True while the log is unfolded on the page on screen."""
        return self.details.opened and self.winfo_ismapped()

    def _draw_log(self, lines: list[str]) -> None:
        """Add lines to the text box; old lines drop off past the limit."""
        text = self.log._textbox  # pylint: disable=protected-access
        text.configure(state="normal")
        text.insert("end", "\n".join(lines) + "\n")
        drawn = int(text.index("end-1c").split(".", maxsplit=1)[0]) - 1
        extra = drawn - self.MAX_LOG_LINES
        if extra > 0:
            text.delete("1.0", f"{extra + 1}.0")
        text.configure(state="disabled")
        if self.autoscroll.get():
            text.see("end")

    def sync_log(self) -> None:
        """Draw the kept lines once the log comes into view."""
        if not self.log_stale or not self._log_visible():
            return
        self.log_stale = False
        text = self.log._textbox  # pylint: disable=protected-access
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.configure(state="disabled")
        self._draw_log(list(self.log_buffer))

    def _toggle_details(self) -> None:
        """Fold or unfold the log, drawing it when it opens."""
        self.details.toggle()
        self.sync_log()

    def clear_log(self) -> None:
        """Empty the log view (the log file is not touched)."""
        self.log_buffer.clear()
        self.log_stale = False
        text = self.log._textbox  # pylint: disable=protected-access
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.configure(state="disabled")

    def log_text(self) -> str:
        """Everything the log holds, drawn or not."""
        return "\n".join(self.log_buffer).strip()

    # ------------------------------------------------------------ the plan

    PLAN_COLUMNS = (
        Column("name", "Song", 200, stretch=True),
        Column("style", "Style", 130),
        Column("file", "File type and loudness", 190),
        Column("saved", "Saved as", 360, stretch=True),
    )

    def warm_sections(self) -> list[Section]:
        """The folded parts worth drawing once in the background."""
        return [self.plan, self.details]

    def _fill_plan(self, body: ctk.CTkFrame) -> None:
        """The per-song table (made the first time it is opened)."""
        self.plan_table = SongTable(
            body, self.PLAN_COLUMNS, height=8, label="What happens to each song"
        )
        self.plan_table.grid(row=0, column=0, sticky="ew")
        self._show_plan()

    def _show_plan(self) -> None:
        """Every song's style, file and new file name."""
        if self.plan_table is None:
            return
        rows = [
            (str(song), [song.stem, style, files, saved], [])
            for song, style, files, saved in self.app.song_plan()
        ]
        self.plan_table.show([("", rows)])

    def show(
        self, _settings: GuiSettings, found: list[tuple[str, str]] | None = None
    ) -> None:
        """Rebuild the plan, the problems and the warnings.

        found is what find_problems() just said, when the caller already asked.
        """
        app = self.app
        show_summary(self.summary.body, app)
        self._show_plan()
        if found is None:
            found = app.find_problems()
        heads_ups = app.heads_ups()
        self._show_notes(found, heads_ups)
        self._show_start(found)
        self.sync_log()

    def _show_notes(self, found: list[tuple[str, str]], heads_ups: list[str]) -> None:
        """The red and yellow notes, rebuilt only when they changed."""
        app = self.app
        if self._notes_shown == (found, heads_ups):
            return
        self._notes_shown = (found, heads_ups)
        clear_children(self.notes)
        row = 0
        pages = {
            "songs": "step 1",
            "sound": "step 2",
            "styles_step": "step 2",
            "output": "Output",
            "settings": "Settings",
        }
        for page, text in found:
            Notice(
                self.notes,
                "error",
                text,
                (f"Go to {pages.get(page, page)}", lambda p=page: app.show_page(p)),
            ).grid(row=row, column=0, sticky="ew", pady=3)
            row += 1
        for text in heads_ups:
            Notice(self.notes, "warning", text).grid(
                row=row, column=0, sticky="ew", pady=3
            )
            row += 1
        if not found:
            Notice(
                self.notes,
                "success",
                "Everything is ready. Press Create when you are.",
            ).grid(row=row, column=0, sticky="ew", pady=3)

    def _show_start(self, found: list[tuple[str, str]]) -> None:
        """Start, Stop and the line beside them."""
        app = self.app
        self.set_busy(app.busy)
        count = app.convertible_count()
        self.start.configure(
            **icon_text(
                "play",
                f"Create {count} song{'s' if count != 1 else ''}"
                if count
                else "Create songs",
                16,
                WHITE,
            ),
        )
        if found:
            self.start.configure(state="disabled")
            self.start_note.configure(
                text="Fix the red items above first.", text_color=DANGER
            )
        elif not app.busy:
            self.start_note.configure(
                text="Tip: preview any song on step 2 before creating.",
                text_color=TEXT_DIM,
            )
        self.show_results()

    def set_busy(self, busy: bool) -> None:
        """Start and Stop follow whether something is running."""
        self.start.configure(state="disabled" if busy else "normal")
        self.stop.configure(state="normal" if busy else "disabled")
        if busy:
            self.start_note.configure(
                text="Creating… You can keep using the window.", text_color=TEXT_DIM
            )

    # ------------------------------------------------------------ results

    def show_results(self) -> None:
        """The results table (all songs of the last run, or only problems)."""
        app = self.app
        rows = []
        only = self.only_problems.get()
        for song, (style, status, result, kind) in app.run_results.items():
            if only and kind != "problem":
                continue
            rows.append((str(song), [song.stem, style, status, result], [kind]))
        self.results.show([("", rows)])
        failed = sum(1 for *_x, kind in app.run_results.values() if kind == "problem")
        made = any(k in ("done", "skipped") for *_x, k in app.run_results.values())
        self.retry.configure(state="normal" if failed and not app.busy else "disabled")
        self.copy.configure(state="normal" if failed else "disabled")
        self.open_folder.configure(state="normal" if made else "disabled")
        self.play_song.configure(state="normal" if made else "disabled")

    def update_result(self, song: Path) -> None:
        """One song's line changed."""
        style, status, result, kind = self.app.run_results[song]
        if self.only_problems.get() and kind != "problem":
            return
        if self.results.tree.exists(str(song)):
            self.results.update_row(
                str(song), [song.stem, style, status, result], [kind]
            )
        else:
            self.show_results()

    def show_finished(self, kind: str, text: str) -> None:
        """The note under the progress bar once a run is over."""
        clear_children(self.result_note)
        Notice(self.result_note, kind, text).grid(
            row=0, column=0, sticky="ew", pady=(4, 0)
        )

    def _chosen_output(self) -> Path | None:
        """The new file of the selected (or first finished) song."""
        songs = [Path(iid) for iid in self.results.selected()] or list(
            self.app.run_outputs
        )
        for song in songs:
            output = self.app.run_outputs.get(song)
            if output is not None:
                return output
        return None

    def _play_selected(self) -> None:
        """Play the selected new song in the usual music player."""
        output = self._chosen_output()
        if output is not None:
            self.app.open_file(output)

    def _open_folder(self) -> None:
        """Open the folder of the selected new song."""
        output = self._chosen_output()
        if output is not None:
            self.app.open_file(output.parent)

    def _copy_problems(self) -> None:
        """Put every failed song, its folder and the reason on the clipboard."""
        lines = [
            f"{song}\t{result}"
            for song, (_s, _st, result, kind) in self.app.run_results.items()
            if kind == "problem"
        ]
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        self.app.toast(
            f"Copied {len(lines)} problem{'s' if len(lines) != 1 else ''}", "ok"
        )
