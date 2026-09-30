# Developed by ::> Gehan Fernando
"""Listening to the song: its beat, its loudest part, its stems, the finished file."""

from .quality import QualityReport, check_output
from .sections import Section, find_loudest_section, loudest_section
from .stems import (
    STEM_RATE,
    clear_stems_cache,
    demucs_available,
    demucs_hint,
    separate_vocals,
)
from .tempo import detect_bpm, rotation_for_tempo

# The names the rest of Audio8D (and your own code) import from here
__all__ = [
    "STEM_RATE",
    "QualityReport",
    "Section",
    "check_output",
    "clear_stems_cache",
    "demucs_available",
    "demucs_hint",
    "detect_bpm",
    "find_loudest_section",
    "loudest_section",
    "rotation_for_tempo",
    "separate_vocals",
]
