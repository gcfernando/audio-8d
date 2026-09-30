# Developed by ::> Gehan Fernando
"""Audio8D: turn any audio file into an 8D-style headphone MP3."""

from .core.errors import (
    Audio8DError,
    ConversionError,
    DependencyError,
    InputValidationError,
)
from .core.presets import PRESETS, RECOMMENDED_PRESET, Preset
from .core.settings import EffectConfig
from .core.types import AudioStreamInfo, Trim
from .pipeline import ConversionResult, ConvertOptions, compare, convert, preview

__author__ = "Gehan Fernando"
# Must match `version` in pyproject.toml; test_presets.py checks that they agree
__version__ = "1.0.0"

# The names the rest of Audio8D (and your own code) import from here
__all__ = [
    "PRESETS",
    "RECOMMENDED_PRESET",
    "Audio8DError",
    "AudioStreamInfo",
    "ConversionError",
    "ConversionResult",
    "ConvertOptions",
    "DependencyError",
    "EffectConfig",
    "InputValidationError",
    "Preset",
    "Trim",
    "compare",
    "convert",
    "preview",
]
