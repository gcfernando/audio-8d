# Developed by ::> Gehan Fernando
"""Safe handling of input paths, output publishing, folders and old files."""

from .atomic import commit_output, create_temporary_output
from .discover import AUDIO_EXTENSIONS, find_songs, is_own_output
from .paths import (
    NAME_STYLES,
    default_output_for,
    format_for_extension,
    output_name,
    resolve_input,
    resolve_output,
    same_file,
)
from .trash import describe_removal, removal_summary, remove_original

# The names the rest of Audio8D (and your own code) import from here
__all__ = [
    "AUDIO_EXTENSIONS",
    "NAME_STYLES",
    "commit_output",
    "create_temporary_output",
    "default_output_for",
    "describe_removal",
    "find_songs",
    "format_for_extension",
    "is_own_output",
    "output_name",
    "removal_summary",
    "remove_original",
    "resolve_input",
    "resolve_output",
    "same_file",
]
