# Developed by ::> Gehan Fernando
"""Converts many songs at once, a few at a time, and keeps score."""

import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from .core.errors import Audio8DError
from .core.settings import EffectConfig
from .pipeline import ConversionResult, ConvertOptions, convert


@dataclass(frozen=True, slots=True)
class BatchItem:
    """One song, where its 8D copy goes, and its own settings if it has them."""

    source: Path
    output: Path
    # None: the song uses the settings every other song uses
    config: EffectConfig | None = None
    # None: the song's file is treated like every other song's (art, title, trim)
    options: ConvertOptions | None = None


@dataclass(slots=True)
class BatchOutcome:
    """How one song went: a result, or the error that stopped it."""

    item: BatchItem
    result: ConversionResult | None = None
    error: Audio8DError | None = None
    seconds: float = 0.0


@dataclass(slots=True)
class BatchReport:
    """Every song's outcome, in the order they were listed."""

    outcomes: list[BatchOutcome] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def converted(self) -> list[BatchOutcome]:
        """Songs that finished."""
        return [outcome for outcome in self.outcomes if outcome.result is not None]

    @property
    def results(self) -> list[ConversionResult]:
        """The finished songs' results, in list order."""
        return [outcome.result for outcome in self.outcomes if outcome.result]

    @property
    def failed(self) -> list[BatchOutcome]:
        """Songs that stopped with an error."""
        return [outcome for outcome in self.outcomes if outcome.error is not None]


# More songs at once than this only makes FFmpeg processes fight over the CPU
MAX_JOBS = 16


def default_jobs() -> int:
    """How many songs to make at once: half the CPU cores, between 1 and 4."""
    return max(1, min(4, (os.cpu_count() or 2) // 2))


# (song number, stage, share of that stage done) for each running song
ItemProgress = Callable[[int, str, float], None]


def run_batch(  # pylint: disable=too-many-arguments,too-many-locals
    items: list[BatchItem],
    config: EffectConfig,
    *,
    options: ConvertOptions | None = None,
    overwrite: bool = False,
    jobs: int = 1,
    on_progress: ItemProgress | None = None,
    on_done: Callable[[int, BatchOutcome], None] | None = None,
    cancel: threading.Event | None = None,
) -> BatchReport:
    """Convert every item, `jobs` at a time; one failure never stops the rest."""
    report = BatchReport(outcomes=[BatchOutcome(item) for item in items])
    started = time.perf_counter()
    lock = threading.Lock()
    # Ctrl+C needs a switch to flip even when the caller didn't pass one
    stop = cancel if cancel is not None else threading.Event()

    def work(index: int) -> BatchOutcome:
        """Convert one song and record how it went."""
        outcome = report.outcomes[index]
        if stop.is_set():
            return outcome

        def progress(stage: str, share: float) -> None:
            """Pass this song's progress on, tagged with its number."""
            if on_progress is not None:
                with lock:
                    on_progress(index, stage, share)

        begin = time.perf_counter()
        try:
            outcome.result = convert(
                outcome.item.source,
                outcome.item.output,
                outcome.item.config or config,
                overwrite=overwrite,
                options=outcome.item.options or options,
                on_progress=progress,
                cancel=stop,
            )
        except Audio8DError as exc:
            outcome.error = exc
        outcome.seconds = time.perf_counter() - begin
        return outcome

    pool = ThreadPoolExecutor(  # pylint: disable=consider-using-with
        max_workers=max(1, jobs)
    )
    try:
        futures = {pool.submit(work, index): index for index in range(len(items))}
        for future in as_completed(futures):
            outcome = future.result()
            if on_done is not None and (outcome.result or outcome.error):
                with lock:
                    on_done(futures[future], outcome)
    except BaseException:
        # Ctrl+C or a failure here: stop the running songs and skip the waiting ones
        stop.set()
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    pool.shutdown(wait=True)

    report.seconds = time.perf_counter() - started
    return report


def progress_tracker(
    count: int, stages_per_song: list[str]
) -> tuple[Callable[[int, str, float], None], Callable[[], float]]:
    """Combine every song's stage progress into one share for an overall bar."""
    done = [[0.0] * len(stages_per_song) for _ in range(count)]

    def update(index: int, stage: str, share: float) -> None:
        """Record one song's progress in one stage."""
        if stage in stages_per_song:
            position = stages_per_song.index(stage)
            done[index][position] = max(done[index][position], share)

    def overall() -> float:
        """The share of all the work that is done, 0.0 to 1.0."""
        if not count:
            return 1.0
        return sum(sum(song) / len(song) for song in done) / count

    return update, overall
