# Developed by ::> Gehan Fernando
"""One check of everything Audio8D depends on, shared by the window and `--check`.

Each dependency is run, never just looked for: FFmpeg and FFprobe must answer
`-version` (and FFmpeg must have the filters Audio8D uses), Python must run
and be new enough, and every add-on package must import. The result says, in
plain words, what is ready, what is missing, what is broken and what to do.
"""

import importlib.util
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .addons import AddonStatus, check_singer
from .ffmpeg import FFmpegToolchain, check_tool, locate, missing_features

READY = "ready"
MISSING = "missing"
INVALID = "invalid"
OPTIONAL = "optional"
UNAVAILABLE = "unavailable"

# The status words shown next to each dependency (never colour alone)
STATE_WORDS = {
    READY: "Ready",
    MISSING: "Missing",
    INVALID: "Invalid",
    OPTIONAL: "Optional, not set up",
    UNAVAILABLE: "Unavailable",
}


@dataclass(frozen=True, slots=True)
class Dependency:  # pylint: disable=too-many-instance-attributes
    """One thing Audio8D depends on, and how it stands."""

    key: str
    name: str
    required: bool
    state: str
    summary: str
    # What it is used to do, e.g. 'make every 8D song'
    purpose: str = ""
    fix: str = ""
    version: str = ""
    path: Path | None = None
    # Raw output or error, for 'Technical details' (never the main message)
    detail: str = ""

    @property
    def ok(self) -> bool:
        """True when it can be used right now."""
        return self.state == READY

    @property
    def state_words(self) -> str:
        """'Ready', 'Missing', 'Invalid', 'Optional, not set up' or 'Unavailable'."""
        return STATE_WORDS[self.state]


@dataclass(frozen=True, slots=True)
class HealthReport:
    """Every dependency after one check."""

    items: tuple[Dependency, ...]
    addon: AddonStatus | None = field(default=None, compare=False)

    def get(self, key: str) -> Dependency | None:
        """One dependency by its key ('ffmpeg', 'ffprobe', 'python', 'singer'…)."""
        return next((item for item in self.items if item.key == key), None)

    @property
    def blocking(self) -> list[Dependency]:
        """Required dependencies that are not ready: converting can't start."""
        return [item for item in self.items if item.required and not item.ok]

    @property
    def ok(self) -> bool:
        """True when everything required is ready (optional add-ons may be missing)."""
        return not self.blocking

    @property
    def singer_ready(self) -> bool:
        """True when 'Keep the singer in the middle' can be used."""
        return self.addon is not None and self.addon.ready

    def problem(self) -> str | None:
        """One sentence naming what stops converting, or None."""
        if not self.blocking:
            return None
        return " ".join(f"{item.name}: {item.summary}" for item in self.blocking)


_TOOL_PURPOSE = {
    "ffmpeg": "make every 8D song",
    "ffprobe": "read each song's details",
}


def check_tools() -> list[Dependency]:
    """FFmpeg and FFprobe: found, started with -version, and FFmpeg's features."""
    found: list[Dependency] = []
    paths: dict[str, Path | None] = {}
    for name in ("ffmpeg", "ffprobe"):
        location = locate(name)
        check = check_tool(name, location.path)
        title = "FFmpeg" if name == "ffmpeg" else "FFprobe"
        paths[name] = check.path if check.ok else None
        if check.ok:
            found.append(
                Dependency(
                    name,
                    title,
                    True,
                    READY,
                    f"Working, version {check.version}.",
                    _TOOL_PURPOSE[name],
                    version=check.version,
                    path=check.path,
                    detail=f"{location.source_words}: {check.path}",
                )
            )
            continue
        state = MISSING if location.path is None else INVALID
        found.append(
            Dependency(
                name,
                title,
                True,
                state,
                check.problem.split(". ", maxsplit=1)[0].rstrip(".") + ".",
                _TOOL_PURPOSE[name],
                fix="Open Settings and choose it with Browse, or press 'Find "
                "automatically'. From a terminal: --ffmpeg / --ffprobe PATH.",
                path=location.path,
                detail=check.problem,
            )
        )
    ffmpeg, ffprobe = paths["ffmpeg"], paths["ffprobe"]
    if ffmpeg is not None and ffprobe is not None:
        lacking = missing_features(FFmpegToolchain(ffmpeg, ffprobe))
        if lacking:
            found[0] = Dependency(
                "ffmpeg",
                "FFmpeg",
                True,
                INVALID,
                "This FFmpeg build lacks features Audio8D needs.",
                _TOOL_PURPOSE["ffmpeg"],
                fix="Use a full FFmpeg 7 or newer, such as the one inside the Audio8D "
                "package.",
                version=found[0].version,
                path=ffmpeg,
                detail=lacking,
            )
    return found


def check_window_packages(required: bool) -> Dependency:
    """customtkinter and Pillow, which only the window needs."""
    missing = [
        name
        for name, module in (("customtkinter", "customtkinter"), ("Pillow", "PIL"))
        if importlib.util.find_spec(module) is None
    ]
    if not missing:
        return Dependency(
            "window",
            "Window packages",
            required,
            READY,
            "customtkinter and Pillow are installed.",
            "draw the Audio8D window",
        )
    return Dependency(
        "window",
        "Window packages",
        required,
        MISSING if required else OPTIONAL,
        f"Not installed: {', '.join(missing)}.",
        "draw the Audio8D window (the terminal app doesn't need them)",
        fix="python -m pip install customtkinter pillow",
    )


def addon_items(status: AddonStatus) -> list[Dependency]:
    """The Python and the singer add-on's packages, as two dependencies."""
    python = status.python
    if python.ok:
        python_item = Dependency(
            "python",
            "Python",
            False,
            READY,
            f"Python {python.version} works.",
            "run the singer add-on",
            version=python.version,
            path=python.path,
            detail=f"{python.source_words}: {python.path}",
        )
    else:
        python_item = Dependency(
            "python",
            "Python",
            False,
            INVALID if python.source == "configured" and python.path else OPTIONAL,
            python.problem,
            "run the singer add-on (only the add-on needs it)",
            fix=status.fix(),
            path=python.path,
            detail=python.detail,
        )
    names = ", ".join(check.package.dist for check in status.missing)
    if status.ready:
        state, summary = READY, "Installed: the singer can stay in the middle."
    elif status.private:
        state, summary = INVALID, status.summary()
    elif status.state == "no-python":
        state, summary = UNAVAILABLE, "Needs a working Python first."
    elif status.state == "not-installed":
        state, summary = OPTIONAL, "Not installed (Audio8D works fully without it)."
    else:
        state, summary = INVALID, f"Partly installed; can't use: {names}."
    details = "\n".join(
        f"{check.package.dist}: "
        + (f"ready {check.version}".strip() if check.ok else check.problem)
        + (f" ({check.detail})" if check.detail and not check.ok else "")
        for check in status.packages
    )
    singer = Dependency(
        "singer",
        "Singer add-on",
        False,
        state,
        summary,
        "keep the singer in the middle, song by song",
        fix="" if status.ready else status.fix(),
        detail=details,
    )
    return [python_item, singer]


def check_environment(
    *,
    window: bool = False,
    addon: bool = True,
    python: Path | None = None,
    on_step: Callable[[str], None] | None = None,
) -> HealthReport:
    """Check everything; window=True when the window itself needs its packages."""
    step = on_step or (lambda _text: None)
    step("Checking FFmpeg and FFprobe...")
    items = check_tools()
    items.append(check_window_packages(required=window))
    status = None
    if addon:
        step("Checking Python and the singer add-on...")
        status = check_singer(python)
        items += addon_items(status)
    return HealthReport(tuple(items), status)
