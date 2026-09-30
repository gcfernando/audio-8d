# Developed by ::> Gehan Fernando
"""Splits a song into vocals and music with Demucs, so the singer can stay central.

Demucs is a free AI model from Meta that separates voices from instruments.
It is large (it brings PyTorch), so it is an optional add-on that runs in a
Python of its own (see addons.py): even the standalone exe can use it.

The split takes a minute or two per song on a normal computer, so the
results are kept in the cache and reused for the same song.
"""

import hashlib
import os
import shutil
import tempfile
import threading
from pathlib import Path

from ..addons import singer_status
from ..core.errors import ConversionError, DependencyError
from ..core.locations import cache_dir
from ..ffmpeg import FFmpegToolchain, ffmpeg_prefix, run_capture
from ..ffmpeg.runner import run_tool

MODEL = "htdemucs"


def demucs_available() -> bool:
    """True when a working Python with Demucs and PyTorch was found and checked."""
    return singer_status().ready


def demucs_hint() -> str:
    """Why the add-on can't be used yet and what to do, in plain words."""
    status = singer_status()
    return f"{status.summary()} {status.fix()}"


def _song_key(song: Path) -> str:
    """Changes whenever the song file itself changes."""
    stat = song.stat()
    identity = f"{song.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{MODEL}"
    return hashlib.sha1(identity.encode("utf-8")).hexdigest()[:20]


def separate_vocals(
    toolchain: FFmpegToolchain,
    song: Path,
    *,
    cancel: threading.Event | None = None,
) -> tuple[Path, Path]:
    """(vocals.wav, music.wav) for the whole song, from the cache when possible.

    Setting cancel stops FFmpeg or Demucs part-way and raises ConversionError.
    """
    status = singer_status()
    if not status.ready or status.python.path is None:
        raise DependencyError(
            "Keeping vocals in the centre needs the singer add-on (Demucs). "
            f"{status.summary()} {status.fix()}"
        )
    folder = cache_dir() / "stems" / _song_key(song)
    vocals, music = folder / "vocals.wav", folder / "no_vocals.wav"
    if vocals.is_file() and music.is_file():
        return vocals, music

    try:
        folder.mkdir(parents=True, exist_ok=True)
        # Each job works in a folder of its own, so two jobs on one song never clash
        work = Path(tempfile.mkdtemp(prefix="work-", dir=folder))
    except OSError as exc:
        raise ConversionError(f"Could not save the separated vocals: {exc}") from exc
    try:
        # Demucs reads a plain WAV most reliably, whatever the song's own format
        source = work / "song.wav"
        run_capture(
            [
                *ffmpeg_prefix(toolchain.ffmpeg),
                "-y",
                "-i",
                str(song),
                "-map",
                "0:a:0",
                "-ac",
                "2",
                "-ar",
                "44100",
                "-c:a",
                "pcm_f32le",
                str(source),
            ],
            error_type=ConversionError,
            cancel=cancel,
        )
        result = run_tool(
            [
                str(status.python.path),
                "-m",
                "demucs.separate",
                "-n",
                MODEL,
                "--two-stems",
                "vocals",
                "--float32",
                "-o",
                str(work),
                "--filename",
                "{stem}.{ext}",
                str(source),
            ],
            cancel=cancel,
        )
        if result.returncode != 0:
            raise ConversionError(
                "Demucs could not split the vocals: "
                + (result.stderr.strip().splitlines() or ["unknown error"])[-1]
            )
        _publish(work / MODEL, vocals, music)
    except OSError as exc:
        raise ConversionError(f"Could not save the separated vocals: {exc}") from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return vocals, music


def _publish(made: Path, vocals: Path, music: Path) -> None:
    """Move the finished stems into the cache, each in one atomic step."""
    try:
        # Music first: the cache counts only once vocals.wav is there as well
        os.replace(made / "no_vocals.wav", music)
        os.replace(made / "vocals.wav", vocals)
    except OSError:
        # Another job on the same song may have published (and be reading) its own
        if not (vocals.is_file() and music.is_file()):
            raise
