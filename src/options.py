# Developed by ::> Gehan Fernando
"""Every option the `audio8d` command understands, and how they become settings."""

import argparse
import dataclasses
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NoReturn

from . import __version__, display, hints
from .batch import MAX_JOBS, default_jobs
from .core.errors import Audio8DError, InputValidationError
from .core.locations import GUIDE_URL
from .core.parsing import parse_keyframes, parse_time
from .core.presets import (
    LEGACY_STYLES,
    PRESETS,
    RECOMMENDED_PRESET,
    Preset,
    legacy_config,
    with_format,
    with_standard_output,
)
from .core.settings import (
    BITRATES,
    DIRECTIONS,
    ENGINES,
    FORMAT_EXTENSIONS,
    PATHS,
    VOCAL_MODES,
    EffectConfig,
    speaker_safe,
)
from .core.sound_levels import LEVELS, MOVEMENT, SPACE, SPEED, SoundLevel
from .core.user_presets import all_presets, find_style
from .files import NAME_STYLES, format_for_extension

LOG = logging.getLogger("audio8d")

# What `--loudness off` turns into, so it can switch off a preset's loudness target
LOUDNESS_OFF = "off"
# What `--loudness match` turns into: the same loudness as the original
LOUDNESS_MATCH = "match"
# --bitrate auto: no constant bitrate, so MP3 uses its variable --quality
BITRATE_AUTO = "auto"
# What `--bpm off`, `--start off` and `--end off` turn into: clear the value
SETTING_OFF = "off"
# The words that clear a setting a style (or an earlier per-song line) gave
_OFF_WORDS = {"off", "none"}
# How long a --preview may be, in seconds
PREVIEW_SECONDS = (5.0, 120.0)

_BEST = PRESETS[RECOMMENDED_PRESET].config


def _columns(rows: Sequence[tuple[str, str]], width: int) -> str:
    """Line up commands and their explanations in two neat columns for --help."""
    # A long command widens its column rather than running into its explanation
    width = max(width, *(len(left) + 2 for left, _right in rows))
    return "\n".join(f"  {left:<{width}}{right}" for left, right in rows)


_QUICK_START = "\n".join(
    [
        "Turn any song (or a whole folder) into 3D / 8D music that moves around "
        "your head.",
        "Use headphones!",
        "",
        "QUICK START - just copy one of these:",
        _columns(
            [
                ('audio8d "My Song.mp3"', 'makes "My Song (8D).mp3" (Studio style)'),
                ('audio8d "My Song.mp3" --preview', "listen first; nothing is kept"),
                ('audio8d "My Song.mp3" --style smooth', "choose another style"),
                (r'audio8d "C:\Music"', "every song in the folder"),
                ("audio8d", "step-by-step helper that asks you questions"),
                ("audio8d --gui", "a window with buttons instead of typing"),
                ("audio8d --list-styles", "show every style"),
            ],
            width=41,
        ),
        "",
        "DEFAULTS (used when you type nothing else):",
        _columns(
            [
                (f"--style {RECOMMENDED_PRESET}", "balanced movement for most music"),
                ("--format mp3 --bitrate 320", "MP3 at the highest quality"),
                (
                    f"--loudness {_BEST.loudness_target:g}",
                    "as loud as music apps (Spotify, YouTube)",
                ),
            ],
            width=28,
        ),
    ]
)

_EXAMPLE_SONG = 'audio8d "My Song.mp3"'
_EXAMPLES = "\n".join(
    [
        "MORE EXAMPLES:",
        _columns(
            [
                (f"{_EXAMPLE_SONG} --format flac", "FLAC, nothing lost"),
                (f"{_EXAMPLE_SONG} --style groove", "moves in time with the beat"),
                (
                    f"{_EXAMPLE_SONG} --movement gentle --speed slow",
                    "softer, slower movement",
                ),
                (f"{_EXAMPLE_SONG} --path figure8 --elevation 0.5", "loops and rises"),
                (f"{_EXAMPLE_SONG} --compare --play", "hear original, then 8D"),
                (
                    r'audio8d "C:\Music" --output-dir "D:\8D" --jobs 4',
                    "a folder, 4 at a time",
                ),
                (
                    r'audio8d "C:\Music" --replace',
                    "replace each song (old one to Recycle Bin)",
                ),
                (
                    f'{_EXAMPLE_SONG} --speed-curve "0=10, 1:00=6, 2:30=10"',
                    "faster in the chorus",
                ),
                (
                    r'audio8d "C:\Music" --per-song songs.txt',
                    "some songs with settings of their own",
                ),
                (
                    r'audio8d "a.mp3" "b.flac" "C:\Music"',
                    "several songs and folders at once",
                ),
                (r'audio8d "C:\Music" --dry-run', "see what would be made first"),
                (r'audio8d "C:\Music" --suggest', "which style suits each song?"),
                (
                    'audio8d --rename-style "Party Mix" Dance',
                    "also --duplicate, --delete, --export, --import-style",
                ),
                ("audio8d --check", "is everything installed and working?"),
                ("audio8d --addon-status", "is the optional singer add-on installed?"),
                ("audio8d --install-addon", "install it; --uninstall-addon removes it"),
            ],
            width=52,
        ),
        "",
        "Developed by Gehan Fernando. Full guide: " + GUIDE_URL,
    ]
)


def _bitrate_value(text: str) -> int | str:
    """Accept one of the constant bitrates, or 'auto' to use the MP3 quality."""
    word = text.strip().lower()
    if word == BITRATE_AUTO:
        return BITRATE_AUTO
    if word.isdigit() and int(word) in BITRATES:
        return int(word)
    raise argparse.ArgumentTypeError(f"use {', '.join(map(str, BITRATES))} or 'auto'")


def _jobs_value(text: str) -> int:
    """How many songs at once: a whole number from 1 to MAX_JOBS."""
    if text.strip().isdigit() and 1 <= int(text) <= MAX_JOBS:
        return int(text)
    raise argparse.ArgumentTypeError(f"use a whole number from 1 to {MAX_JOBS}")


def _loudness_value(text: str) -> float | str:
    """Accept a LUFS number like -14, or the words 'off' or 'match'."""
    word = text.strip().lower()
    if word in {"off", "none"}:
        return LOUDNESS_OFF
    if word in {"match", "original", "same"}:
        return LOUDNESS_MATCH
    try:
        return float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "use a number like -14, 'match' or 'off'"
        ) from None


def _bass_value(text: str) -> float:
    """A split frequency in Hz, or 'off' (0) to let the bass move too."""
    if text.strip().lower() in {"off", "none", "0"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        raise argparse.ArgumentTypeError("use a number like 120, or 'off'") from None


def _time_value(text: str) -> float | str:
    """A time like 90 or 1:30, or 'off' for no start (or end) at all."""
    if text.strip().lower() in _OFF_WORDS:
        return SETTING_OFF
    try:
        return parse_time(text)
    except InputValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _curve_value(text: str) -> tuple[tuple[float, float], ...]:
    """TIME=VALUE pairs, e.g. '0=10, 1:00=6', or 'off' for no curve."""
    if text.strip().lower() in _OFF_WORDS:
        return ()
    try:
        return parse_keyframes(text)
    except InputValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _bpm_value(text: str) -> float | str:
    """A tempo like 128, or 'off' to let Audio8D find the tempo itself."""
    if text.strip().lower() in _OFF_WORDS:
        return SETTING_OFF
    try:
        return float(text)
    except ValueError:
        raise argparse.ArgumentTypeError("use a number like 128, or 'off'") from None


def _preview_seconds(text: str) -> float:
    """How long a preview lasts: a number of seconds within PREVIEW_SECONDS."""
    low, high = PREVIEW_SECONDS
    try:
        seconds = float(text)
    except ValueError:
        seconds = -1.0
    if not low <= seconds <= high:
        raise argparse.ArgumentTypeError(
            f"use a number of seconds from {low:g} to {high:g}, e.g. 30"
        )
    return seconds


def _preset_name(text: str) -> str:
    """A style that exists: built-in, or saved with --save-style."""
    known = known_presets()
    # Letter case doesn't matter: studio, Studio and STUDIO are the same style
    name = find_style(text, known)
    if name is None and text.strip().lower() in LEGACY_STYLES:
        # Older names (lossless, streaming, hifi) keep working exactly as before
        name = text.strip().lower()
    if name is None:
        raise argparse.ArgumentTypeError(
            f"invalid choice: '{text}' (choose from {', '.join(known)})"
        )
    return name


def known_presets() -> dict[str, Preset]:
    """Built-in styles plus your own; a broken styles file only loses your own."""
    try:
        return all_presets()
    except Audio8DError as exc:
        LOG.warning(
            "Your styles file has a problem, so only built-in styles work: %s", exc
        )
        return dict(PRESETS)


class _ListPresetsAction(argparse.Action):
    """Print the preset table and stop, the same way --help does."""

    def __init__(
        self, option_strings: Sequence[str], dest: str, **kwargs: object
    ) -> None:
        """Take no value, like --help, so `audio8d --list-presets` works on its own."""
        super().__init__(
            option_strings,
            dest,
            nargs=0,
            default=argparse.SUPPRESS,
            help=str(kwargs.get("help")),
        )

    def __call__(self, parser: argparse.ArgumentParser, *_: object) -> None:
        """Show the style table, then stop before argparse asks for a song."""
        display.show_presets(display.Painter(sys.stdout), __version__, known_presets())
        parser.exit()


class _FriendlyParser(argparse.ArgumentParser):
    """An argument parser that explains typing mistakes in plain words."""

    # A per-song file line is parsed too; its mistakes are raised, not printed
    raise_errors = False

    def error(self, message: str) -> NoReturn:
        """Keep argparse's usual message, then add a plain fix and a working example."""
        if self.raise_errors:
            raise InputValidationError(message)
        painter = display.Painter(sys.stderr)
        # The full usage lists every option; one short line keeps the fix visible
        painter.line(
            f"usage: {self.prog} [options] SONG_OR_FOLDER [OUTPUT]"
            "   (all options: audio8d --help)"
        )
        painter.line(f"{self.prog}: error: {message}")
        display.show_fix(painter, hints.usage_fix_for(message))
        painter.line(
            "  "
            + painter.paint("Example:", "bold")
            + f' audio8d "My Song.mp3" --style {RECOMMENDED_PRESET}'
        )
        self.exit(2)


def _add_sound_options(parser: argparse.ArgumentParser) -> None:
    """--style and every knob that changes how the song sounds."""
    group = parser.add_argument_group("how it sounds")
    group.add_argument(
        "--style",
        dest="preset",
        type=_preset_name,
        metavar="NAME",
        help="how it sounds: a style from --list-styles, or one you saved "
        f"(default {RECOMMENDED_PRESET})",
    )
    # The older name keeps working in scripts, without cluttering --help
    group.add_argument(
        "--preset", dest="preset", type=_preset_name, help=argparse.SUPPRESS
    )
    for level in LEVELS:
        words = "|".join(word.lower() for word in level.choices)
        group.add_argument(
            f"--{level.key}",
            type=_level_value(level),
            metavar=words,
            help=level.help[:1].lower()
            + level.help[1:].rstrip(".")
            + ": "
            + ", ".join(f"{w.lower()} = {v:g}" for w, v in level.choices.items())
            + f" (exact value: --{_EXACT[level.key]})",
        )
    # Knobs default to None, so "not typed" differs from "typed the default value"
    group.add_argument(
        "--rotation-seconds",
        type=float,
        metavar="2..100",
        help="exact speed: seconds for one full circle "
        f"(default {_BEST.rotation_seconds:g})",
    )
    group.add_argument(
        "--intensity",
        type=float,
        metavar="0..1",
        help="exact movement: how far it moves around your head "
        f"(default {_BEST.intensity})",
    )
    group.add_argument(
        "--ambience",
        type=float,
        metavar="0..1",
        help=f"exact space: how much room sound, 0 = none (default {_BEST.ambience})",
    )
    group.add_argument(
        "--engine",
        choices=ENGINES,
        help="3d = real 3D around your head (recommended); pan = simple left-right",
    )
    group.add_argument(
        "--path",
        choices=PATHS,
        help="the route it takes: circle (normal), arc (front only), "
        "figure8 (around each ear), wander",
    )
    group.add_argument("--direction", choices=DIRECTIONS, help="which way it turns")
    group.add_argument(
        "--bass",
        type=_bass_value,
        metavar="HZ",
        help="keep everything below this in the MIDDLE; off lets the bass move "
        f"(default {_BEST.bass_hz:g})",
    )
    group.add_argument(
        "--elevation",
        type=float,
        metavar="0..1",
        help="let the sound drift UP over your head (normal 0)",
    )
    group.add_argument(
        "--fade",
        type=float,
        metavar="SECONDS",
        help="ease the movement in at the start and out at the end "
        f"(default {_BEST.fade_seconds:g})",
    )
    group.add_argument(
        "--speed-curve",
        type=_curve_value,
        metavar='"T=S,..."',
        help='change the spin over time, e.g. "0=10, 1:00=6, 2:30=10"; off = '
        "the same speed all the way through",
    )
    group.add_argument(
        "--intensity-curve",
        type=_curve_value,
        metavar='"T=A,..."',
        help='change the movement over time, e.g. "0=0.6, 1:00=0.95"; off = '
        "the same movement all the way through",
    )
    group.add_argument(
        "--beat-sync",
        action="store_const",
        const=True,
        help="find the song's tempo and make one circle last whole bars",
    )
    group.add_argument(
        "--no-beat-sync",
        dest="beat_sync",
        action="store_const",
        const=False,
        help="switch beat sync off, even when the style has it on",
    )
    group.add_argument(
        "--bpm",
        type=_bpm_value,
        metavar="TEMPO",
        help="the song's tempo if you know it (switches beat sync on); off = let "
        "Audio8D find it",
    )
    group.add_argument(
        "--vocals",
        choices=VOCAL_MODES,
        help="center keeps the SINGER in the middle (needs the optional singer "
        "add-on: see --addon-status and --install-addon)",
    )
    # Both switches default to None, so a per-song line can turn either way
    group.add_argument(
        "--speakers",
        action="store_const",
        const=True,
        help="make it sound right on speakers and car stereos too",
    )
    group.add_argument(
        "--no-speakers",
        dest="speakers",
        action="store_const",
        const=False,
        help="made for headphones only (normal); in a --per-song file it undoes "
        "--speakers for that song",
    )


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    """Format, quality, loudness, and where the new files go."""
    group = parser.add_argument_group("output (how the file is saved)")
    group.add_argument(
        "--format",
        choices=list(FORMAT_EXTENSIONS),
        help="mp3 (default, works everywhere), flac (lossless), wav (uncompressed), "
        "m4a (small, good quality), opus (efficient modern format)",
    )
    group.add_argument(
        "--quality",
        type=int,
        choices=range(10),
        metavar="0..9",
        help="MP3 size-based quality when --bitrate auto: 0 = best, 9 = smallest "
        f"(default {_BEST.quality})",
    )
    group.add_argument(
        "--bitrate",
        type=_bitrate_value,
        metavar="KBPS",
        help="exact quality of mp3/m4a/opus in kbps (128, 160, 192, 224, 256, 320) "
        "or 'auto'; normally High is used: MP3 320, M4A 256, Opus 192",
    )
    group.add_argument(
        "--loudness",
        type=_loudness_value,
        metavar="LEVEL",
        help="how loud: -14 = Match music apps (default), match = Keep original "
        "loudness, off = no change; also -16 = Apple Music, -23 = TV and radio",
    )
    group.add_argument(
        "--exact-loudness",
        action="store_const",
        const=True,
        help="shave the loudest peaks to get as close to the --loudness target as "
        "possible; very loud or punchy songs can still land a little under it",
    )
    group.add_argument(
        "--no-exact-loudness",
        dest="exact_loudness",
        action="store_const",
        const=False,
        help="never limit peaks just to reach the --loudness target",
    )
    group.add_argument(
        "--limiter-ceiling",
        type=float,
        metavar="0.0625..1",
        help="the loudest a peak may get, stops crackles "
        f"(default {_BEST.limiter_ceiling})",
    )
    group.add_argument(
        "--output-dir",
        type=Path,
        metavar="FOLDER",
        help="save the new songs in this folder (normal: next to each original)",
    )
    group.add_argument(
        "--name",
        choices=NAME_STYLES,
        help="8d = '<song> (8D).mp3' (normal); original = keep the song's own name",
    )
    group.add_argument(
        "--replace",
        action="store_true",
        help="after each 8D song is saved, move its ORIGINAL to the Recycle Bin, or "
        "rename it '<song> (original)' where there is none (the new file takes the "
        "original name unless --name 8d)",
    )
    group.add_argument(
        "--overwrite",
        action="store_true",
        help="allow replacing a file that already has the output name",
    )
    group.add_argument(
        "--start",
        type=_time_value,
        metavar="TIME",
        help="begin here, e.g. 1:30 (off = from the very start)",
    )
    group.add_argument(
        "--end",
        type=_time_value,
        metavar="TIME",
        help="stop here, e.g. 2:00 (off = to the very end)",
    )
    # Each pair defaults to None, so a per-song line can turn either way
    group.add_argument(
        "--no-cover",
        action="store_const",
        const=True,
        help="don't copy the album art",
    )
    group.add_argument(
        "--cover",
        dest="no_cover",
        action="store_const",
        const=False,
        help="copy the album art (normal); in a --per-song file it undoes --no-cover",
    )
    group.add_argument(
        "--keep-title",
        action="store_const",
        const=True,
        help="don't add ' (8D)' to the song's title tag",
    )
    group.add_argument(
        "--title-tag",
        dest="keep_title",
        action="store_const",
        const=False,
        help="add ' (8D)' to the song's title tag (normal); in a --per-song file it "
        "undoes --keep-title",
    )
    group.add_argument(
        "--no-check",
        action="store_true",
        help="skip measuring the finished file (loudness, peaks, mono)",
    )


def _add_extra_options(parser: argparse.ArgumentParser) -> None:
    """Folders, previews, styles and the other switches."""
    group = parser.add_argument_group("more")
    group.add_argument(
        "--recursive",
        action="store_true",
        help="with a folder: include songs in its sub-folders too",
    )
    group.add_argument(
        "--jobs",
        type=_jobs_value,
        metavar="N",
        help=f"with a folder: make N songs at once (normal {default_jobs()})",
    )
    group.add_argument(
        "--preview",
        type=_preview_seconds,
        nargs="?",
        const=30.0,
        metavar="SECONDS",
        help="listen to a short sample from the loudest part (5 to 120 s, default "
        "30); it is played and then deleted, unless you give an OUTPUT file to keep "
        "it",
    )
    group.add_argument(
        "--compare",
        action="store_true",
        help="listen to the original (A), then 8D (B), at the same loudness; "
        "deleted afterwards unless you give an OUTPUT file",
    )
    group.add_argument(
        "--play", action="store_true", help="open the new file in your music player"
    )
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="show the settings and where each new song would be saved, then stop "
        "without making anything",
    )
    group.add_argument(
        "--suggest",
        action="store_true",
        help="suggest the style that suits each song best (from its tags), then "
        "stop without making anything",
    )
    group.add_argument(
        "--save-style",
        dest="save_preset",
        metavar="NAME",
        help="save these sound settings as your own style (use it with --style NAME)",
    )
    group.add_argument("--save-preset", dest="save_preset", help=argparse.SUPPRESS)
    _add_style_options(group)
    group.add_argument(
        "--gui", action="store_true", help="open the Audio8D window instead"
    )
    group.add_argument(
        "--verbose",
        action="store_true",
        help="show extra technical details, useful when something goes wrong",
    )
    group.add_argument(
        "--list-styles",
        action=_ListPresetsAction,
        help="show every style with its exact values, then stop",
    )
    group.add_argument(
        "--list-presets", action=_ListPresetsAction, help=argparse.SUPPRESS
    )
    group.add_argument(
        "--version",
        action="version",
        version=f"audio8d {__version__} - developed by Gehan Fernando",
        help="show the version number and who made it",
    )


def _add_style_options(group: argparse._ArgumentGroup) -> None:
    """Looking after your saved styles, like the window's Your styles page."""
    group.add_argument(
        "--style-description",
        metavar="TEXT",
        help="a few words about the style you save with --save-style or --update-style",
    )
    group.add_argument(
        "--update-style",
        metavar="NAME",
        help="save these sound settings into your saved style NAME (it starts from "
        "that style unless you add --style)",
    )
    group.add_argument(
        "--rename-style",
        nargs=2,
        metavar=("NAME", "NEW_NAME"),
        help="give one of your saved styles a new name, then stop",
    )
    group.add_argument(
        "--duplicate-style",
        nargs=2,
        metavar=("NAME", "NEW_NAME"),
        help="copy one of your saved styles under a new name, then stop",
    )
    group.add_argument(
        "--delete-style",
        metavar="NAME",
        help="delete one of your saved styles (songs already made are not "
        "touched), then stop",
    )
    group.add_argument(
        "--export-style",
        nargs=2,
        metavar=("NAME", "FILE"),
        help="save a style to a file, to keep or share, then stop",
    )
    group.add_argument(
        "--import-style",
        nargs="+",
        metavar=("FILE", "NAME"),
        help="add a style from a file exported by Audio8D, optionally under a new "
        "NAME, then stop",
    )


def _add_setup_options(parser: argparse.ArgumentParser) -> None:
    """Checking and choosing the tools, and the optional singer add-on."""
    group = parser.add_argument_group("setup and checks")
    group.add_argument(
        "--check",
        action="store_true",
        help="check FFmpeg, FFprobe, Python and the singer add-on (each is run, "
        "not just looked for), say what to fix, then stop",
    )
    group.add_argument(
        "--clear-cache",
        action="store_true",
        help="forget the remembered loudness measurements and singer splits (they "
        "are made again when needed), then stop",
    )
    group.add_argument(
        "--delete-logs",
        action="store_true",
        help="delete the saved technical log files, then stop",
    )
    group.add_argument(
        "--ffmpeg",
        type=Path,
        metavar="PATH",
        help="use this ffmpeg for this run (normal: the one chosen in the window's "
        "Settings, or found automatically)",
    )
    group.add_argument(
        "--ffprobe",
        type=Path,
        metavar="PATH",
        help="use this ffprobe for this run",
    )
    group.add_argument(
        "--python",
        type=Path,
        metavar="PATH",
        help="the Python that runs the singer add-on (normal: the one chosen in "
        "Settings, or found automatically)",
    )
    group.add_argument(
        "--addon-status",
        action="store_true",
        help="say whether the optional singer add-on is installed, then stop",
    )
    group.add_argument(
        "--install-addon",
        action="store_true",
        help="install the singer add-on (Demucs, about 1 GB) into Audio8D's own "
        "add-on folder, using the Python found (or --python), then stop",
    )
    group.add_argument(
        "--repair-addon",
        action="store_true",
        help="remove the add-on's folder and install it again, then stop",
    )
    group.add_argument(
        "--uninstall-addon",
        action="store_true",
        help="remove the add-on's folder (Audio8D keeps working without it), then stop",
    )
    group.add_argument(
        "--per-song",
        type=Path,
        metavar="FILE",
        help="a text file giving some songs settings of their own, one song per "
        'line, e.g.  "Rain Study.mp3" --style smooth --format flac  '
        "(--default on a line resets that song to the defaults)",
    )
    group.add_argument(
        "--default",
        action="store_true",
        help=argparse.SUPPRESS,
    )


def create_parser() -> argparse.ArgumentParser:
    """Build the argument parser; kept separate so tests can poke at it."""
    parser = _FriendlyParser(
        prog="audio8d",
        description=_QUICK_START,
        epilog=_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "input",
        type=Path,
        nargs="?",
        help="the song (mp3, flac, wav, ...) or a FOLDER of songs",
    )
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        help="where to save the 8D song when there is one song (leave out: "
        "'<song> (8D).mp3')",
    )
    parser.add_argument(
        "more",
        type=Path,
        nargs="*",
        metavar="MORE",
        help="more songs or folders, made together like a folder (with just two, "
        "the second is a song only when it is a folder or --output-dir is given)",
    )
    _add_sound_options(parser)
    _add_output_options(parser)
    _add_extra_options(parser)
    _add_setup_options(parser)
    return parser


# The typed knobs and the EffectConfig field each one sets
_KNOBS = {
    "rotation_seconds": "rotation_seconds",
    "intensity": "intensity",
    "ambience": "ambience",
    "limiter_ceiling": "limiter_ceiling",
    "quality": "quality",
    "bitrate": "bitrate",
    "exact_loudness": "exact_loudness",
    "engine": "engine",
    "path": "path",
    "direction": "direction",
    "bass": "bass_hz",
    "elevation": "elevation",
    "fade": "fade_seconds",
    "speed_curve": "speed_curve",
    "intensity_curve": "intensity_curve",
    "beat_sync": "beat_sync",
    "bpm": "bpm",
    "vocals": "vocals",
    "format": "output_format",
}


# Each friendly word option and the exact option that sets the same value
_EXACT = {"movement": "intensity", "speed": "rotation-seconds", "space": "ambience"}


def _level_value(level: SoundLevel) -> Callable[[str], float]:
    """An argparse type for one friendly option, e.g. --movement gentle."""

    def parse(text: str) -> float:
        try:
            return level.value_for(text)
        except InputValidationError as exc:
            raise argparse.ArgumentTypeError(str(exc)) from None

    return parse


def typed_changes(args: argparse.Namespace) -> dict[str, object]:
    """The EffectConfig settings typed on the command line (or a per-song line)."""
    overrides: dict[str, object] = {
        field: getattr(args, option)
        for option, field in _KNOBS.items()
        if getattr(args, option, None) is not None
    }
    for level in (MOVEMENT, SPEED, SPACE):
        value = getattr(args, level.key, None)
        if value is None:
            continue
        if level.field in overrides:
            raise InputValidationError(
                f"Use --{level.key} or --{_EXACT[level.key]}, not both"
            )
        overrides[level.field] = value
    if overrides.get("bitrate") == BITRATE_AUTO:
        overrides["bitrate"] = None
    if overrides.get("bpm") == SETTING_OFF:
        overrides["bpm"] = None
    if args.loudness is not None:
        overrides["loudness_target"] = (
            None if args.loudness in (LOUDNESS_OFF, LOUDNESS_MATCH) else args.loudness
        )
        overrides["match_loudness"] = args.loudness == LOUDNESS_MATCH
    return overrides


def resolve_config(
    args: argparse.Namespace,
    presets: dict[str, Preset] | None = None,
    *,
    with_speakers: bool = True,
) -> EffectConfig:
    """Start from the chosen preset (or the defaults), then apply any typed knobs."""
    known = presets if presets is not None else known_presets()
    base = style_config(args.preset or RECOMMENDED_PRESET, known)

    overrides = typed_changes(args)
    # An output name like "song.flac" chooses the format when --format doesn't
    output = getattr(args, "output", None)
    if args.format is None and output is not None:
        inferred = format_for_extension(output)
        if inferred is not None:
            overrides["output_format"] = inferred

    output_format = overrides.pop("output_format", None)
    if output_format is not None:
        # The typed --bitrate and --limiter-ceiling still win over these
        base = with_format(base, str(output_format))
    config = dataclasses.replace(base, **overrides)
    if with_speakers and args.speakers:
        config = speaker_safe(config)
    return config


def style_config(name: str, known: dict[str, Preset]) -> EffectConfig:
    """A style's sound with the standard output (older names keep their old output)."""
    if name in LEGACY_STYLES:
        return legacy_config(name)
    if name not in known:
        raise InputValidationError(
            f"There is no style called '{name}'. Choose from: {', '.join(known)}"
        )
    # A style only decides the sound; the file is saved the recommended way
    return with_standard_output(known[name].config)


def used_only_defaults(args: argparse.Namespace) -> bool:
    """True when the user typed no style and no sound knobs at all."""
    typed = [getattr(args, option) for option in _KNOBS] + [
        args.preset,
        args.loudness,
        *(getattr(args, level.key) for level in LEVELS),
    ]
    return all(value is None for value in typed) and not args.speakers
