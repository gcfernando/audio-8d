# Developed by ::> Gehan Fernando
"""What the preview tests share: a manager with a fake renderer, and draining it."""

import queue
import time
from collections.abc import Callable
from pathlib import Path

from src.previews import PreviewManager


def make_manager(
    tmp_path: Path, render: Callable[..., object]
) -> tuple[PreviewManager, queue.Queue]:
    """A preview manager that renders with `render` and reports to a queue."""
    events: queue.Queue = queue.Queue()
    made = PreviewManager(
        events.put, folder=tmp_path / "previews" / "run", render=render,
        make_compare=render,
    )  # fmt: skip
    made.folder.mkdir(parents=True, exist_ok=True)
    return made, events


def drain(manager: PreviewManager, events: queue.Queue, seconds: float = 5.0):
    """Hand every event to the manager until work stops; returns them."""
    seen = []
    end = time.time() + seconds
    while time.time() < end:
        try:
            event = events.get(timeout=0.05)
        except queue.Empty:
            if not manager.busy:
                break
            continue
        seen.append((event, manager.handle(event)))
    return seen
