# Developed by ::> Gehan Fernando
"""The main window, part: step 4: checking, creating the songs, the results."""

import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from . import addons, hints
from .app_base import (
    _STAGE_WORDS,
    LOG,
    AppBase,
)
from .batch import BatchItem, BatchOutcome, BatchReport, progress_tracker, run_batch
from .core.errors import Audio8DError
from .core.parsing import format_time
from .ffmpeg import (
    FFmpegToolchain,
)
from .files import describe_removal
from .gui_dialogs import (
    Dialog,
)
from .gui_model import (
    can_write,
    config_for,
    destination_for,
    gui_words,
    items_for,
    long_paths,
    name_clashes,
    options_for,
    problems,
    singer_songs,
    warnings,
)
from .gui_summary import (
    plan_summary,
    source_notes,
)
from .gui_widgets import (
    open_path,
)
from .library import (
    READY,
    UNREADABLE,
)
from .logs import delete_log_files
from .pipeline import stages_for


class ConvertMixin(AppBase):
    """Step 4: checking, converting and showing the results."""

    def find_problems(self) -> list[tuple[str, str]]:
        """(page, plain words) for everything that stops a conversion."""
        songs = self.songs()
        found = problems(self.settings, songs, self.presets)
        if not songs and self.library.tracks:
            found = [("songs", "None of the songs on the list can be read as music.")]
        if self.tools_problem:
            found.append(("settings", self.tools_problem))
        found += self._singer_problems(songs)
        return found

    def _singer_problems(
        self, songs: Sequence[tuple[Path, Path | None]]
    ) -> list[tuple[str, str]]:
        """Songs that keep the singer in the middle while the add-on isn't ready."""
        if self.singer_ready():
            return []
        wanted = singer_songs(self.settings, songs, self.presets)
        if not wanted:
            return []
        count = self._songs_word(len(wanted))
        status = addons.known_status()
        if status is None:
            why = "the singer add-on is still being checked; try again in a moment."
        else:
            why = f"the singer add-on isn't ready ({status.summary()})"
        return [
            (
                "settings",
                f"{count} keep the singer in the middle, but {why} Install it in "
                "Settings (Add-on), or switch it off for those songs in Customize.",
            )
        ]

    def heads_ups(self) -> list[str]:
        """Warnings worth reading before converting (nothing that stops it)."""
        notes = warnings(
            self.settings, len(singer_songs(self.settings, self.songs(), self.presets))
        )
        read = [(t.name, t.info) for t in self.library.tracks if t.info is not None]
        notes += source_notes(read)
        bad = [t for t in self.library.tracks if t.state == UNREADABLE]
        if bad:
            names = ", ".join(t.name for t in bad[:3]) + (
                " and others" if len(bad) > 3 else ""
            )
            notes.append(
                f"{len(bad)} song{'s' if len(bad) != 1 else ''} can't be read and "
                f"will be skipped ({names})."
            )
        reading = sum(
            1 for t in self.library.tracks if t.state not in (READY, UNREADABLE)
        )
        if reading:
            notes.append(f"{reading} songs are still being read; you can start anyway.")
        clashes = name_clashes(self.settings, self.songs())
        if clashes:
            notes.append(
                f"{clashes} song{'s' if clashes != 1 else ''} would get the same file "
                "name as another song, so ' (2)', ' (3)'… is added to keep every file."
            )
        try:
            long = long_paths(items_for(self.settings, self.songs(), self.presets))
        except Audio8DError:
            long = []
        if long:
            notes.append(
                f"{len(long)} new file{'s' if len(long) != 1 else ''} will have a very "
                "long path (over 260 characters); some older programs can't open "
                "those. Choose a shorter folder to avoid it."
            )
        return notes

    def summary_rows(self) -> list[tuple[str, str]]:
        """The short summary shown before creating."""
        skipped = sum(1 for t in self.library.tracks if t.state == UNREADABLE)
        return plan_summary(self.settings, self.songs(), self.presets, skipped)

    def convertible_count(self) -> int:
        """How many songs Create would make."""
        return len(self.songs())

    def _ready(self) -> bool:
        """Check everything first; if something's wrong, show step 4's list."""
        found = self.find_problems()
        destination = destination_for(self.settings)
        if not found and destination is not None:
            problem = can_write(destination)
            if problem:
                found = [("output", problem)]
        if not found:
            try:
                FFmpegToolchain.discover()
            except Audio8DError as exc:
                found = [("settings", gui_words(str(exc)))]
        if found:
            self.show_page("review")
            if found[0][0] in ("output", "settings"):
                self.toast(found[0][1][:90], "error")
            else:
                self.toast("Please fix the red items first", "error")
            return False
        return True

    def _songs_to_make(self, only: Sequence[Path] | None) -> list[BatchItem]:
        """The songs to make now; ones whose 8D file exists are marked skipped."""
        settings = self.settings
        songs = self.songs()
        if only is not None:
            wanted = set(only)
            songs = [pair for pair in songs if pair[0] in wanted]
        self.run_results = {}
        self.run_outputs = {}
        todo = []
        for item in items_for(settings, songs, self.presets):
            style = self.label(settings.song_styles.get(item.source, settings.style))
            # Replacing an original with a same-named 8D file is not a clash
            exists = item.output.exists() and not (
                settings.originals == "replace" and item.output == item.source
            )
            if exists and not settings.overwrite:
                self.run_results[item.source] = (
                    style,
                    "Skipped",
                    f"{item.output.name} already exists, so it was kept",
                    "skipped",
                )
                self.run_outputs[item.source] = item.output
            else:
                self.run_results[item.source] = (style, "Waiting", "", "waiting")
                todo.append(item)
        return todo

    def run_convert(self, only: Sequence[Path] | None = None) -> None:
        """Create every song on the list (or just `only`)."""
        if self.busy or not self._ready():
            return
        settings = self.settings
        if settings.originals != "keep":
            if not Dialog.confirm(
                self,
                "Replace the original songs?",
                "After each 8D song is safely saved, its original will be moved to the "
                "Recycle Bin (you can restore it from there). On drives with no "
                "Recycle Bin, such as USB sticks, it stays in its folder, renamed "
                "'<song> (original)'. An 8D song can't be turned back into the "
                "normal song.",
                "Replace them",
            ):
                return
        todo = self._songs_to_make(only)
        page = self.pages["review"]
        self.show_page("review")
        for child in page.result_note.winfo_children():  # type: ignore[attr-defined]
            child.destroy()
        page.show_results()  # type: ignore[attr-defined]
        if not todo:
            page.show_finished(  # type: ignore[attr-defined]
                "info",
                "Nothing new to create: every song already has an 8D version. "
                "Choose 'If the 8D file exists: Replace it' on step 3, Output, to "
                "make them again.",
            )
            return
        self.previews.cancel()
        self.stop_playing()
        config = config_for(settings)
        options = options_for(settings)
        stages = stages_for(options)
        update, overall = progress_tracker(len(todo), stages)
        self.run_items = todo
        self.run_stages = stages

        def work() -> None:
            def progress(index: int, stage: str, share: float) -> None:
                update(index, stage, share)
                self.events.put(("row", index, stage, share, overall()))

            report = run_batch(
                todo,
                config,
                options=options,
                overwrite=settings.overwrite,
                jobs=settings.jobs,
                on_progress=progress,
                on_done=lambda index, outcome: self.events.put(
                    ("done", index, outcome)
                ),
                cancel=self.cancel,
            )
            self.events.put(("report", report))

        label = f"Creating {len(todo)} song{'s' if len(todo) != 1 else ''}…"
        self._start(label, work)

    def retry_failed(self) -> None:
        """Create only the songs that failed last time."""
        failed = [song for song, row in self.run_results.items() if row[3] == "problem"]
        if failed:
            self.run_convert(only=failed)

    def _start(self, label: str, work: Callable[[], None]) -> None:
        """Run work on a helper thread; the window keeps responding."""
        self.busy = True
        self.cancel.clear()
        self.started = time.perf_counter()
        self.overall_share = 0.0
        self.overall.set(0)
        self.status_text.configure(text=label)
        self.live("review").set_busy(True)  # type: ignore[attr-defined]
        self.live("review").run_bar.set(0)  # type: ignore[attr-defined]
        self.refresh_nav()

        def target() -> None:
            try:
                work()
            except Audio8DError as exc:
                # Stopping on purpose isn't a problem; the status bar says "Stopped"
                if not self.cancel.is_set():
                    self.events.put(("error", exc))
            except Exception as exc:  # pylint: disable=broad-exception-caught
                # Never let a surprise take the window down; show it instead
                LOG.exception("Unexpected problem")
                self.events.put(("error", exc))
            finally:
                self.events.put(("finished",))

        threading.Thread(target=target, name="convert", daemon=True).start()

    def stop(self) -> None:
        """Stop creating (after the current step), reading, or a preview."""
        if self.busy:
            self.cancel.set()
            self.status_text.configure(text="Stopping after the current step…")
        elif self._reading_count():
            self.stop_reading()
        elif self.previews.busy:
            song = self.previews.making
            self.previews.cancel()
            self.preview_wanted = None
            if song is not None:
                self._preview_changed(song)
            self.status_text.configure(text="Preview cancelled.")

    def _progress_line(self) -> str:
        """'37 of 300 done · 2 problems · about 4 min left'."""
        rows = self.run_results.values()
        total = sum(1 for row in rows if row[3] != "skipped")
        done = sum(1 for row in rows if row[3] in ("done", "problem"))
        failed = sum(1 for row in rows if row[3] == "problem")
        text = f"{done} of {total} done"
        working = [s for s, row in self.run_results.items() if row[3] == "working"]
        if self.busy and working:
            # The song being made now, so it is plain that work is going on
            more = f" (+{len(working) - 1} more)" if len(working) > 1 else ""
            text += f"  ·  now: {working[0].stem}{more}"
        if failed:
            text += f"  ·  {failed} problem{'s' if failed != 1 else ''}"
        elapsed = time.perf_counter() - self.started
        share = self.overall_share
        if self.busy and 0.03 < share < 1.0 and elapsed > 5:
            left = elapsed / share * (1 - share)
            text += f"  ·  about {format_time(left)} left"
        return text

    def _song_done(self, index: int, outcome: BatchOutcome) -> None:
        """One song finished: its line in the results says how."""
        item = outcome.item
        style = self.run_results.get(item.source, ("", "", "", ""))[0]
        result = outcome.result
        if result is None:
            error = outcome.error
            fix = gui_words(hints.fix_for(error) or "") if error else ""
            LOG.error("%s failed: %s", item.source.name, error)
            words = gui_words(hints.short_message(error)) if error else "Stopped"
            self.run_results[item.source] = (
                style,
                "Problem",
                words + (f" What to do: {fix}" if fix else ""),
                "problem",
            )
        else:
            parts = [f"Saved as {result.output.name}"]
            if result.quality:
                parts.append(f"{result.quality.integrated_lufs:.1f} LUFS")
            if result.bpm:
                parts.append(f"{result.bpm:g} BPM")
            if result.original_removed_to:
                parts.append(f"original {describe_removal(result.original_removed_to)}")
            self.run_results[item.source] = (style, "Done", "  ·  ".join(parts), "done")
            self.run_outputs[item.source] = result.output
        del index
        self.live("review").update_result(item.source)  # type: ignore[attr-defined]

    def _show_report(self, report: BatchReport) -> None:
        """The note under the progress bar after converting a list."""
        converted = len(report.converted)
        failed = len(report.failed)
        page = self.pages["review"]
        seconds = format_time(report.seconds)
        if self.cancel.is_set():
            waiting = [s for s, r in self.run_results.items() if r[3] == "waiting"]
            for song in waiting:
                style = self.run_results[song][0]
                self.run_results[song] = (
                    style,
                    "Not made",
                    "Stopped before this song",
                    "stopped",
                )
            page.show_results()  # type: ignore[attr-defined]
            page.show_finished(  # type: ignore[attr-defined]
                "info",
                f"Stopped. {converted} song{'s were' if converted != 1 else ' was'} "
                "made and kept; the song being made was cleaned up.",
            )
            return
        if failed:
            page.show_finished(  # type: ignore[attr-defined]
                "warning",
                f"{converted} made, {failed} couldn't be made (in {seconds}). The "
                "problems are listed below with what to do; 'Convert failed songs "
                "again' retries only those.",
            )
        else:
            page.show_finished(  # type: ignore[attr-defined]
                "success",
                f"All done: {converted} song{'s' if converted != 1 else ''} made in "
                f"{seconds}. Put on your headphones and press Play.",
            )
        self.status_text.configure(
            text=f"Done: {converted} made, {failed} failed, in {seconds}."
        )
        if converted and self.settings.play_when_done:
            open_path(report.results[0].output)

    def clear_log_view(self) -> None:
        """'Clear Logs': empty the log view (saved log files are kept)."""
        self.live("review").clear_log()  # type: ignore[attr-defined]
        self.toast("Log view cleared (saved log files are kept)")

    def delete_saved_logs(self) -> None:
        """Delete the saved log files (asked for on the Settings page)."""
        deleted, failed = delete_log_files()
        if failed:
            self.toast(f"{len(failed)} log file(s) couldn't be deleted", "error")
        else:
            self.toast(
                f"Deleted {deleted} saved log file{'s' if deleted != 1 else ''}", "ok"
            )

    def _conversion_row(self, event: tuple) -> None:
        """One song moved on a step: its row and the overall bar."""
        _, index, stage, share, overall = event
        if index < len(self.run_items):
            song = self.run_items[index].source
            style = self.run_results.get(song, ("",))[0]
            stages = self.run_stages
            step = stages.index(stage) if stage in stages else 0
            shown, percent = stage, int(share * 100)
            # A finished step shows the next one at 0 %, so the row never looks stuck
            if share >= 1.0 and step + 1 < len(stages):
                shown, percent = stages[step + 1], 0
            self.run_results[song] = (
                style,
                f"{_STAGE_WORDS.get(shown, shown)} {percent}%",
                "",
                "working",
            )
            self.live("review").update_result(song)
        self.overall_share = overall
        self.overall.set(overall)
        page = self.pages["review"]
        page.run_bar.set(overall)
        page.progress_text.configure(text=self._progress_line())

    def _conversion_done(self, event: tuple) -> None:
        """One song finished (made, skipped or failed)."""
        self._song_done(event[1], event[2])
        self.live("review").progress_text.configure(text=self._progress_line())

    def _conversion_finished(self, _event: tuple) -> None:
        """The whole conversion ended, finished or stopped."""
        self.busy = False
        self.overall.set(1.0)
        page = self.pages["review"]
        page.set_busy(False)
        if self.cancel.is_set():
            self.status_text.configure(text="Stopped. Finished songs are kept.")
        elif not self.status_text.cget("text").startswith("Done"):
            self.status_text.configure(text="Done.")
        page.show(self.settings)
        page.progress_text.configure(text=self._progress_line())
        self.refresh_nav()
