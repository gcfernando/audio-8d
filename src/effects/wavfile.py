# Developed by ::> Gehan Fernando
"""Writes 32-bit float WAV files: the movement gains and the reverb's room."""

import struct
import sys
from array import array
from collections.abc import Iterable
from pathlib import Path

# WAVE_FORMAT_IEEE_FLOAT, which FFmpeg reads without any conversion
_FLOAT_FORMAT = 3


def write_float_wav(
    path: Path, samples: Iterable[float], *, channels: int, rate: int
) -> Path:
    """Save interleaved samples (frame by frame, channel by channel) as a WAV."""
    data = array("f", samples)
    if len(data) % channels:
        raise ValueError("sample count must be a whole number of frames")
    # WAV is little-endian on every computer
    if sys.byteorder != "little":
        data.byteswap()
    payload = data.tobytes()
    block = channels * 4
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(payload))
        + b"WAVE"
        + b"fmt "
        + struct.pack(
            "<IHHIIHH", 16, _FLOAT_FORMAT, channels, rate, rate * block, block, 32
        )
        + b"data"
        + struct.pack("<I", len(payload))
    )
    with path.open("wb") as file:
        file.write(header)
        file.write(payload)
    return path
