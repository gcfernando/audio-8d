# Developed by ::> Gehan Fernando
"""The command line's --per-song file: settings of their own for some songs.

One song per line: the song (a file name, a path, or a pattern such as
*.flac), then the same options you would type after `audio8d`:

    # song               its own settings
    "Rain Study.mp3"     --style smooth --format flac
    "Storm Wall.flac"    --vocals center --loudness match
    *.wav                --format flac
    "Intro.wav"          --default
    "Live.mp3"           --no-speakers --cover --start off

Every line that matches a song applies, top to bottom, so later lines win.
The opposite switches (--no-speakers, --cover, --title-tag, --no-beat-sync,
--start off...) undo what the command line or an earlier line gave a song.
--default is 'Reset to default': it drops what earlier lines gave that song.
The settings are combined by song_settings, exactly like the window's.
"""

import argparse
import fnmatch
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from .core.errors import InputValidationError
from .options import SETTING_OFF, create_parser, typed_changes
from .song_settings import SPEAKERS

# The options that describe one song; everything else belongs to the whole run
SONG_OPTIONS = {
    "preset",
    "default",
    "movement",
    "speed",
    "space",
    "rotation_seconds",
    "intensity",
    "ambience",
    "engine",
    "path",
    "direction",
    "bass",
    "elevation",
    "fade",
    "speed_curve",
    "intensity_curve",
    "beat_sync",
    "bpm",
    "vocals",
    "speakers",
    "format",
    "quality",
    "bitrate",
    "loudness",
    "exact_loudness",
    "limiter_ceiling",
    "start",
    "end",
    "no_cover",
    "keep_title",
}


@dataclass(frozen=True, slots=True)
class SongRule:
    """One line of the file: which songs, and their own settings."""

    pattern: str
    line: int
    style: str | None = None
    changes: dict[str, object] = field(default_factory=dict)
    # Where the file was, so relative paths in it are read from there
    folder: Path = Path()
    # --default: the song follows the defaults again (earlier lines are undone)
    reset: bool = False

    def matches(self, song: Path) -> bool:
        """True for a song this line names (by path, name, bare name or pattern)."""
        wanted = self.pattern.strip()
        if any(sep in wanted for sep in ("/", "\\")):
            target = Path(wanted).expanduser()
            if not target.is_absolute():
                target = self.folder / target
            return _same(target, song)
        name = song.name.lower()
        wanted = wanted.lower()
        return (
            name == wanted
            or song.stem.lower() == wanted
            or fnmatch.fnmatch(name, wanted)
        )


def _same(one: Path, other: Path) -> bool:
    """True when two paths name the same file (letter case ignored on Windows)."""
    try:
        return one.resolve() == other.resolve()
    except OSError:
        return one == other


def _changes(args: argparse.Namespace) -> dict[str, object]:
    """The settings one line gives its songs, in song_settings' names."""
    changes = typed_changes(args)
    if args.speakers is not None:
        changes[SPEAKERS] = args.speakers
    # 'off' gives the song no start (or end), whatever the whole run has
    if args.start is not None:
        changes["trim_start"] = None if args.start == SETTING_OFF else args.start
    if args.end is not None:
        changes["trim_end"] = None if args.end == SETTING_OFF else args.end
    if args.no_cover is not None:
        changes["keep_cover"] = not args.no_cover
    if args.keep_title is not None:
        changes["tag_title"] = not args.keep_title
    return changes


def parse_line(text: str, number: int, folder: Path = Path()) -> SongRule | None:
    """One line of the file (None for a blank line or a comment)."""
    stripped = text.strip()
    if not stripped or stripped.startswith("#"):
        return None
    try:
        # posix=False keeps Windows backslashes; the quotes are taken off below
        parts = shlex.split(stripped, posix=False)
        words = [word.strip('"').strip("'") for word in parts]
    except ValueError as exc:
        raise InputValidationError(f"Line {number}: {exc}") from None
    song, options = words[0], words[1:]
    if not options:
        raise InputValidationError(
            f"Line {number}: '{song}' has no settings after it, e.g. --style smooth "
            "(or --default)"
        )
    parser = create_parser()
    parser.raise_errors = True  # type: ignore[attr-defined]
    try:
        args = parser.parse_args(options)
        blank = parser.parse_args([])
    except InputValidationError as exc:
        raise InputValidationError(f"Line {number} ('{song}'): {exc}") from None
    except SystemExit:
        # --help or --version asked argparse to stop the whole program
        raise InputValidationError(
            f"Line {number} ('{song}'): only song settings can go here"
        ) from None
    given = {
        name
        for name, value in vars(args).items()
        if value != getattr(blank, name, None)
    }
    extra = sorted(given - SONG_OPTIONS)
    if extra:
        words = ", ".join("--" + name.replace("_", "-") for name in extra)
        raise InputValidationError(
            f"Line {number} ('{song}'): {words} can't be set for one song; put it "
            "on the command line for the whole run"
        )
    if args.default and len(given) > 1:
        raise InputValidationError(
            f"Line {number} ('{song}'): --default means 'use the defaults', so it "
            "goes on a line of its own"
        )
    try:
        changes = _changes(args)
    except InputValidationError as exc:
        raise InputValidationError(f"Line {number} ('{song}'): {exc}") from None
    return SongRule(song, number, args.preset, changes, folder, reset=args.default)


def read_rules(path: Path) -> list[SongRule]:
    """Every line of a --per-song file (raises with the line number on a mistake)."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise InputValidationError(f"Cannot read the per-song file {path}") from exc
    rules = []
    for number, line in enumerate(text.splitlines(), start=1):
        rule = parse_line(line, number, path.resolve().parent)
        if rule is not None:
            rules.append(rule)
    if not rules:
        raise InputValidationError(f"The per-song file {path} has no song lines")
    return rules


def rules_for(song: Path, rules: list[SongRule]) -> list[SongRule]:
    """The lines that apply to one song, in file order."""
    return [rule for rule in rules if rule.matches(song)]


def merged(rules: list[SongRule]) -> tuple[str | None, dict[str, object]]:
    """(its own style, its own settings) from every matching line; later lines win."""
    style: str | None = None
    changes: dict[str, object] = {}
    for rule in rules:
        if rule.reset:
            style, changes = None, {}
            continue
        style = rule.style or style
        changes.update(rule.changes)
    return style, changes
