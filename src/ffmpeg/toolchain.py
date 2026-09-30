# Developed by ::> Gehan Fernando
"""Locates FFmpeg/FFprobe and checks the build has what the effect needs.

Where each tool comes from, in order:

1. a path chosen in the window's Settings (``set_preferred_paths``);
2. the copy bundled with Audio8D (inside the package, or vendor/ffmpeg in the
   source code; see core.locations.tools_dir);
3. the PATH;
4. the usual install folders (winget, Chocolatey, Scoop, Homebrew, /usr/bin…).

A chosen path always wins, even when it is wrong, so a mistake is reported
instead of being silently replaced by another copy.
"""

import logging
import os
import re
import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ..core.errors import DependencyError
from ..core.locations import tools_dir
from ..effects.graph import GRAPH_FILTERS
from .runner import run_capture, run_tool

# The filters every conversion uses; loudness adds its meter on top
REQUIRED_FILTERS = GRAPH_FILTERS
REQUIRED_ENCODER = "libmp3lame"
LOG = logging.getLogger(__name__)

# The bundled ffmpeg and ffprobe win over anything on PATH
BUNDLED_DIR = tools_dir()
TOOLS = ("ffmpeg", "ffprobe")
# How long `-version` may take before a tool counts as not working
VERSION_TIMEOUT = 20.0

# Where each tool came from, in the words the Settings page shows
SOURCE_WORDS = {
    "configured": "Chosen by you",
    "bundled": "Found automatically (included with Audio8D)",
    "path": "Found automatically (on the system PATH)",
    "common": "Found automatically (a usual install folder)",
    "missing": "Not found",
}

# Paths chosen in Settings; None means "find it automatically"
_preferred: dict[str, Path | None] = {"ffmpeg": None, "ffprobe": None}


def set_preferred_paths(ffmpeg: Path | None, ffprobe: Path | None) -> None:
    """Use these tools from now on (None: find that one automatically)."""
    _preferred["ffmpeg"] = ffmpeg
    _preferred["ffprobe"] = ffprobe
    LOG.debug("Preferred tools: ffmpeg=%s ffprobe=%s", ffmpeg, ffprobe)


def preferred_key() -> tuple[str, str]:
    """A value that changes whenever the chosen paths change (for caches)."""
    return str(_preferred["ffmpeg"] or ""), str(_preferred["ffprobe"] or "")


def _executable_name(name: str) -> str:
    """'ffmpeg.exe' on Windows, 'ffmpeg' elsewhere."""
    return f"{name}.exe" if os.name == "nt" else name


def _usable(path: Path) -> bool:
    """True for an existing file this process may run."""
    return path.is_file() and os.access(path, os.X_OK)


def _common_folders() -> list[Path]:
    """The usual places FFmpeg ends up, built from this computer's own folders."""
    folders: list[Path] = []
    if os.name == "nt":
        env = os.environ
        for base in (env.get("ProgramFiles"), env.get("ProgramFiles(x86)")):
            if base:
                folders.append(Path(base) / "ffmpeg" / "bin")
        if env.get("LOCALAPPDATA"):
            folders.append(Path(env["LOCALAPPDATA"]) / "Microsoft" / "WinGet" / "Links")
        if env.get("ChocolateyInstall"):
            folders.append(Path(env["ChocolateyInstall"]) / "bin")
        if env.get("USERPROFILE"):
            folders.append(Path(env["USERPROFILE"]) / "scoop" / "shims")
        if env.get("SystemDrive"):
            folders.append(Path(env["SystemDrive"] + "\\") / "ffmpeg" / "bin")
    else:
        folders += [
            Path("/opt/homebrew/bin"),
            Path("/usr/local/bin"),
            Path("/usr/bin"),
            Path("/snap/bin"),
        ]
    return folders


@dataclass(frozen=True, slots=True)
class ToolLocation:
    """Where one tool was found (path None when it wasn't), and how."""

    name: str
    path: Path | None
    source: str

    @property
    def source_words(self) -> str:
        """'Chosen by you', 'Found automatically (…)' or 'Not found'."""
        return SOURCE_WORDS[self.source]


def locate(name: str) -> ToolLocation:
    """Find one tool: the chosen path, then bundled, PATH and usual folders."""
    chosen = _preferred.get(name)
    if chosen is not None:
        return ToolLocation(name, Path(chosen).expanduser(), "configured")
    bundled = BUNDLED_DIR / _executable_name(name)
    if _usable(bundled):
        return ToolLocation(name, bundled, "bundled")
    on_path = shutil.which(name)
    if on_path:
        return ToolLocation(name, Path(on_path), "path")
    for folder in _common_folders():
        candidate = folder / _executable_name(name)
        if _usable(candidate):
            return ToolLocation(name, candidate, "common")
    return ToolLocation(name, None, "missing")


@dataclass(frozen=True, slots=True)
class ToolCheck:
    """What running a tool with -version showed."""

    name: str
    path: Path | None
    ok: bool
    # e.g. '7.1-essentials_build-www.gyan.dev' (empty when it didn't run)
    version: str = ""
    # A plain-word problem and its fix, when ok is False
    problem: str = ""


_VERSION_LINE = re.compile(r"^(ffmpeg|ffprobe) version (\S+)")


# One plain answer per way a tool can fail
def check_tool(  # pylint: disable=too-many-return-statements
    name: str, path: Path | None
) -> ToolCheck:
    """Run `<tool> -version` and say whether it is really that tool, and working."""
    if path is None:
        return ToolCheck(
            name,
            None,
            False,
            problem=f"{name} was not found. Choose {_executable_name(name)} with "
            "Browse, or install FFmpeg.",
        )
    if not path.exists():
        return ToolCheck(
            name,
            path,
            False,
            problem=f"There is no file at {path}. Choose {_executable_name(name)} "
            "with Browse.",
        )
    if path.is_dir():
        return ToolCheck(
            name,
            path,
            False,
            problem=f"{path} is a folder. Choose the {_executable_name(name)} file "
            "inside it.",
        )
    try:
        result = run_tool([str(path), "-version"], timeout=VERSION_TIMEOUT)
    except subprocess.TimeoutExpired:
        return ToolCheck(
            name,
            path,
            False,
            problem=f"{path.name} did not answer within {VERSION_TIMEOUT:g} seconds.",
        )
    except OSError as exc:
        LOG.warning("Could not start %s: %s", path, exc)
        return ToolCheck(
            name,
            path,
            False,
            problem=f"{path.name} can't be started. Make sure it is the real "
            f"{_executable_name(name)} from an FFmpeg download.",
        )
    first = (result.stdout or "").strip().splitlines()[:1]
    match = _VERSION_LINE.match(first[0]) if first else None
    if result.returncode != 0 or match is None:
        return ToolCheck(
            name,
            path,
            False,
            problem=f"{path.name} did not answer like {name} does. Choose the real "
            f"{_executable_name(name)}.",
        )
    if match.group(1) != name:
        return ToolCheck(
            name,
            path,
            False,
            version=match.group(2),
            problem=f"That file is {match.group(1)}, not {name}. Choose "
            f"{_executable_name(name)} here.",
        )
    return ToolCheck(name, path, True, version=match.group(2))


@dataclass(frozen=True, slots=True)
class FFmpegToolchain:
    """Absolute paths to the ffmpeg and ffprobe executables."""

    ffmpeg: Path
    ffprobe: Path

    @classmethod
    def discover(cls) -> "FFmpegToolchain":
        """Find both tools (Settings, bundled, PATH, usual folders) or say why not."""
        found = {name: locate(name) for name in TOOLS}
        for location in found.values():
            path = location.path
            if location.source == "configured" and (path is None or not _usable(path)):
                raise DependencyError(
                    f"The {location.name} chosen in Settings can't be used: "
                    f"{location.path}. Choose it again in Settings, or switch back "
                    "to finding it automatically."
                )
        missing = [name for name, location in found.items() if location.path is None]
        if missing:
            raise DependencyError(
                "Missing required executable(s): "
                + ", ".join(missing)
                + f". Put ffmpeg and ffprobe in {BUNDLED_DIR}, choose them in "
                "Settings, or install FFmpeg and add it to PATH."
            )
        ffmpeg, ffprobe = (found[name].path for name in TOOLS)
        assert ffmpeg is not None and ffprobe is not None
        toolchain = cls(ffmpeg=ffmpeg.resolve(), ffprobe=ffprobe.resolve())
        LOG.debug("Using %s and %s", toolchain.ffmpeg, toolchain.ffprobe)
        return toolchain

    def validate_capabilities(
        self, extra_filters: Iterable[str] = (), encoder: str = REQUIRED_ENCODER
    ) -> None:
        """Fail early if this FFmpeg build lacks a filter or the chosen encoder."""
        filters_output = run_capture(
            [str(self.ffmpeg), "-hide_banner", "-filters"],
            error_type=DependencyError,
        ).stdout
        encoders_output = run_capture(
            [str(self.ffmpeg), "-hide_banner", "-encoders"],
            error_type=DependencyError,
        ).stdout

        missing_filters = sorted(
            name
            for name in REQUIRED_FILTERS | set(extra_filters)
            if not _has_filter(filters_output, name)
        )
        if missing_filters:
            raise DependencyError(
                "This FFmpeg build is missing required audio filter(s): "
                + ", ".join(missing_filters)
            )

        if not _has_audio_encoder(encoders_output, encoder):
            raise DependencyError(
                f"This FFmpeg build does not include the {encoder} encoder."
            )


def _has_filter(filters_output: str, name: str) -> bool:
    """Look for a filter row in the output of `ffmpeg -filters`."""
    # Rows start with flag columns such as 'TSC' or '...', then the filter name
    return (
        re.search(rf"(?m)^\s*[TSC\.]+\s+{re.escape(name)}\s+", filters_output)
        is not None
    )


def _has_audio_encoder(encoders_output: str, name: str) -> bool:
    """Look for an audio encoder row in the output of `ffmpeg -encoders`."""
    # Audio encoder rows start with 'A' followed by five more flag characters
    return (
        re.search(rf"(?m)^\s*A.....\s+{re.escape(name)}\s+", encoders_output)
        is not None
    )


def missing_features(toolchain: FFmpegToolchain) -> str | None:
    """None when this FFmpeg can make every format, or what it lacks."""
    try:
        toolchain.validate_capabilities(extra_filters={"ebur128"})
    except DependencyError as exc:
        return str(exc)
    return None
