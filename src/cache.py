# Developed by ::> Gehan Fernando
"""Remembers loudness measurements, so re-making a song skips the measuring pass.

A measurement depends on the song file and on every setting that shapes the
mix before the volume change. Anything after it (bitrate, format, limiter,
loudness target) can change freely and the measurement still holds.
"""

import dataclasses
import hashlib
import json
import logging
import os
import threading
from pathlib import Path

from .core.locations import cache_dir
from .core.settings import EffectConfig
from .core.types import Trim
from .ffmpeg import LoudnessMeasurement

LOG = logging.getLogger(__name__)

# Bump when the effect's sound changes, so old measurements are never reused
_ENGINE_VERSION = "2.1"
_MAX_ENTRIES = 500
# Settings that come after the measurement, so they never change it
_AFTER_MEASURE = {
    "limiter_ceiling",
    "quality",
    "loudness_target",
    "bitrate",
    "exact_loudness",
    "match_loudness",
}
_LOCK = threading.Lock()


def _file() -> Path:
    """The cache file (safe to delete at any time)."""
    return cache_dir() / "loudness.json"


def measurement_key(
    song: Path,
    config: EffectConfig,
    trim: Trim | None,
    sample_rate: int,
    timeline_start: float = 0.0,
) -> str | None:
    """A fingerprint of everything the measurement depends on.

    timeline_start is where a preview sits in the song's movement and curves.
    """
    try:
        stat = song.stat()
    except OSError:
        return None
    mix = {
        key: value
        for key, value in dataclasses.asdict(config).items()
        if key not in _AFTER_MEASURE
    }
    # FLAC and WAV skip the MP3 resampling, which changes the rate but not the key
    mix.pop("output_format", None)
    identity = json.dumps(
        [
            _ENGINE_VERSION,
            str(song.resolve()),
            stat.st_size,
            stat.st_mtime_ns,
            mix,
            [trim.start, trim.end] if trim else None,
            sample_rate,
            # Only added when set, so every full-song measurement stays remembered
            *([timeline_start] if timeline_start else []),
        ],
        sort_keys=True,
        default=str,
    )
    return hashlib.sha1(identity.encode("utf-8")).hexdigest()


def _load() -> dict[str, dict[str, float]]:
    """The whole cache, or an empty one if it is missing or damaged."""
    try:
        data = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def get(key: str | None) -> LoudnessMeasurement | None:
    """A remembered measurement, if there is one."""
    if key is None:
        return None
    with _LOCK:
        entry = _load().get(key)
    try:
        return LoudnessMeasurement(**entry) if entry else None
    except TypeError:
        return None


def put(key: str | None, measurement: LoudnessMeasurement) -> None:
    """Remember a measurement; a failure to save only means measuring again later."""
    if key is None:
        return
    with _LOCK:
        data = _load()
        data.pop(key, None)
        data[key] = dataclasses.asdict(measurement)
        # Dicts keep insertion order, so the oldest entries are dropped first
        while len(data) > _MAX_ENTRIES:
            data.pop(next(iter(data)))
        target = _file()
        # Write aside and swap in, so a crash never leaves a half-written cache
        partial = target.with_name(f"{target.name}.{os.getpid()}.tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            partial.write_text(json.dumps(data), encoding="utf-8")
            os.replace(partial, target)
        except OSError as exc:
            LOG.debug("Could not save the loudness cache: %s", exc)
            partial.unlink(missing_ok=True)
