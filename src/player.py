# Developed by ::> Gehan Fernando
"""Plays a preview inside the window, with play, pause, resume and stop.

On Windows the built-in Media Control Interface (winmm) plays WAV and MP3
files with no extra packages. Elsewhere, or if it fails, the file is handed
to the computer's own music player instead (no pause/stop from the window).
All calls happen on the window's own thread.
"""

import ctypes
import itertools
import logging
import os
from pathlib import Path

from .opener import open_path

LOG = logging.getLogger(__name__)

STOPPED, PLAYING, PAUSED = "stopped", "playing", "paused"
_ALIASES = itertools.count(1)


class PlayerError(RuntimeError):
    """The file could not be played inside the window."""


class Player:
    """One loaded file at a time, controlled from the window."""

    def __init__(self, muted: bool = False) -> None:
        """Ready, with nothing loaded (muted plays silently, for automatic checks)."""
        self.muted = muted
        self.file: Path | None = None
        self._alias: str | None = None
        self._winmm = ctypes.windll.winmm if os.name == "nt" else None
        # Without MCI the song opens in the music player and can't be paused here
        self.built_in = self._winmm is not None

    def _send(self, command: str) -> str:
        """Send one MCI command; raise PlayerError with its reason on failure."""
        buffer = ctypes.create_unicode_buffer(256)
        code = self._winmm.mciSendStringW(command, buffer, 256, 0)
        if code:
            reason = ctypes.create_unicode_buffer(256)
            self._winmm.mciGetErrorStringW(code, reason, 256)
            raise PlayerError(reason.value or f"MCI error {code}")
        return buffer.value

    def load(self, file: Path) -> None:
        """Get a file ready to play (any file loaded before is closed)."""
        self.close()
        self.file = file
        self.built_in = self._winmm is not None
        if not self.built_in:
            return
        alias = f"audio8d{next(_ALIASES)}"
        try:
            # Quoted, so folders with spaces or any language's letters work
            self._send(f'open "{file}" type mpegvideo alias {alias}')
            self._send(f"set {alias} time format milliseconds")
            if self.muted:
                self._send(f"setaudio {alias} volume to 0")
        except PlayerError as exc:
            LOG.warning("Built-in playback unavailable for %s: %s", file, exc)
            self.built_in = False
            return
        self._alias = alias

    def play(self, from_start: bool = False) -> None:
        """Start (or restart) playing the loaded file."""
        if self.file is None:
            return
        if self._alias is None:
            open_path(self.file)
            return
        start = " from 0" if from_start else ""
        self._send(f"play {self._alias}{start}")

    def pause(self) -> None:
        """Pause, keeping the place."""
        if self._alias is not None and self.state() == PLAYING:
            self._send(f"pause {self._alias}")

    def resume(self) -> None:
        """Carry on from where it was paused."""
        if self._alias is not None and self.state() == PAUSED:
            self._send(f"resume {self._alias}")

    def stop(self) -> None:
        """Stop and go back to the start."""
        if self._alias is not None:
            try:
                self._send(f"stop {self._alias}")
                self._send(f"seek {self._alias} to start")
            except PlayerError as exc:
                LOG.debug("Stopping playback: %s", exc)

    def state(self) -> str:
        """'playing', 'paused' or 'stopped'."""
        if self._alias is None:
            return STOPPED
        try:
            mode = self._send(f"status {self._alias} mode")
        except PlayerError:
            return STOPPED
        return mode if mode in (PLAYING, PAUSED) else STOPPED

    def position(self) -> tuple[float, float]:
        """(seconds played, seconds long), or (0, 0) when unknown."""
        if self._alias is None:
            return 0.0, 0.0
        try:
            where = int(self._send(f"status {self._alias} position") or 0)
            length = int(self._send(f"status {self._alias} length") or 0)
        except (PlayerError, ValueError):
            return 0.0, 0.0
        return where / 1000, length / 1000

    def close(self) -> None:
        """Stop and let go of the file (so it can be deleted)."""
        if self._alias is not None:
            try:
                self._send(f"close {self._alias}")
            except PlayerError as exc:
                LOG.debug("Closing playback: %s", exc)
        self._alias = None
        self.file = None
