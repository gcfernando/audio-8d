# Developed by ::> Gehan Fernando
"""Exceptions that Audio8D raises for problems a user can understand and fix."""


# One family of errors, so the window and the terminal can catch every one at once
class Audio8DError(RuntimeError):
    """Base class for every error that is safe to show to an end user."""


class DependencyError(Audio8DError):
    """FFmpeg, FFprobe, or one of the features we rely on is not available."""


class InputValidationError(Audio8DError):
    """A path or effect setting was rejected before any audio was processed."""


class ConversionError(Audio8DError):
    """FFmpeg started but could not produce the finished file (or was stopped)."""
