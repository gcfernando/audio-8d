# Developed by ::> Gehan Fernando
"""Friendly, colourful terminal output for the `audio8d` command."""

import ctypes
import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO

from .analysis import QualityReport
from .batch import BatchOutcome, BatchReport
from .core.parsing import format_time
from .core.presets import PRESETS, RECOMMENDED_PRESET, Preset
from .core.settings import EffectConfig
from .core.types import AudioStreamInfo, Trim
from .files import describe_removal, removal_summary
from .pipeline import (
    STAGE_CHECK,
    STAGE_RENDER,
    STAGE_SAVE,
    STAGE_STEMS,
    ConversionResult,
    LoudnessPlan,
)

# Average bitrate LAME usually lands on for each --quality value from 0 to 9
_VBR_KBPS = (245, 225, 190, 175, 165, 130, 115, 100, 85, 65)

# The studio preset is what every "best:" hint in the panel points to
BEST = PRESETS[RECOMMENDED_PRESET].config

# ANSI colour codes; 38;5;141 is a soft violet from the 256-colour palette
_ANSI = {
    "bold": "1",
    "dim": "2",
    "cyan": "96",
    "pink": "95",
    "green": "92",
    "yellow": "93",
    "red": "91",
    "violet": "38;5;141",
}

_PATH_WORDS = {
    "circle": "circles your head",
    "arc": "swings left-right in front",
    "figure8": "loops around each ear",
    "wander": "drifts freely around you",
}


def _enable_windows_ansi(stream: TextIO) -> bool:
    """Switch on colour codes in the classic Windows console; harmless elsewhere."""
    if os.name != "nt":
        return True
    try:
        # msvcrt only exists on Windows, so it is imported once we know we are there
        import msvcrt  # pylint: disable=import-outside-toplevel

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = msvcrt.get_osfhandle(stream.fileno())
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        # 0x0004 is ENABLE_VIRTUAL_TERMINAL_PROCESSING, which turns colour codes on
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except (AttributeError, OSError, ValueError):
        return False


class Painter:
    """Writes to one stream, adding colour and box lines only where they will render."""

    def __init__(self, stream: TextIO) -> None:
        """Decide once whether this stream can show colours and box lines."""
        self.stream = stream
        # A real terminal can redraw a line in place, so progress bars can move
        self.live = hasattr(stream, "isatty") and stream.isatty()
        # Respect NO_COLOR, the common way people ask tools for plain text
        self.color = (
            self.live and "NO_COLOR" not in os.environ and _enable_windows_ansi(stream)
        )
        self.fancy = self._can_encode("╭─╮│╰╯·━")

    def _can_encode(self, sample: str) -> bool:
        """True when the stream's encoding can show these characters."""
        try:
            sample.encode(getattr(self.stream, "encoding", None) or "ascii")
        except (UnicodeEncodeError, LookupError):
            return False
        return True

    def paint(self, text: str, *styles: str) -> str:
        """Wrap text in colour codes when colour is on."""
        if not self.color or not styles:
            return text
        codes = ";".join(_ANSI[style] for style in styles)
        return f"\033[{codes}m{text}\033[0m"

    def line(self, text: str = "") -> None:
        """Print one line and flush so it appears before FFmpeg starts working."""
        print(text, file=self.stream, flush=True)

    def redraw(self, text: str) -> None:
        """Replace the current line (for progress bars) without a new line."""
        clear = "\033[K" if self.color else ""
        print(f"\r{text}{clear}", end="", file=self.stream, flush=True)

    def rule(self, width: int = 52) -> None:
        """A thin divider line."""
        self.line(self.paint("  " + ("─" if self.fancy else "-") * width, "dim"))


# ----------------------------------------------------------------- plain words


def describe_movement(intensity: float) -> str:
    """Plain-word label for --intensity, in the same words as --movement."""
    if intensity == 0:
        return "off, stays in the middle"
    if intensity < 0.72:
        return "gentle"
    if intensity < 0.88:
        return "balanced"
    return "strong"


def describe_room(ambience: float) -> str:
    """Plain-word label for --ambience, in the same words as --space."""
    if ambience == 0:
        return "no room sound at all"
    if ambience < 0.18:
        return "dry"
    if ambience < 0.35:
        return "natural"
    return "spacious"


def describe_quality(
    quality: int, bitrate: int | None = None, output_format: str = "mp3"
) -> str:
    """Plain-word label for the output format and its quality setting."""
    if output_format == "flac":
        return "FLAC 24-bit  (lossless, nothing lost)"
    if output_format == "wav":
        return "WAV 24-bit  (lossless, big files)"
    if output_format in {"m4a", "opus"}:
        name = "AAC (M4A)" if output_format == "m4a" else "Opus"
        default = 256 if output_format == "m4a" else 192
        return (
            f"{name} {bitrate or default} kbps  (sounds like the original to most ears)"
        )
    if bitrate:
        kind = "the maximum MP3 allows" if bitrate == 320 else "constant"
        return f"{bitrate} kbps CBR  ({kind})"
    if quality <= 1:
        verdict = "best"
    elif quality <= 3:
        verdict = "excellent"
    elif quality <= 6:
        verdict = "good"
    else:
        verdict = "small file"
    return f"V{quality}  (~{_VBR_KBPS[quality]} kbps, {verdict})"


def describe_ceiling(ceiling: float) -> str:
    """Limiter ceiling as both the raw value and dBFS."""
    return f"{ceiling:.2f}  ({20 * math.log10(ceiling):+.1f} dBFS)"


def describe_loudness(target: float | None) -> str:
    """Loudness target in words."""
    if target is None:
        return "off  (natural level, usually quieter than the original)"
    if round(target) == -14:
        return f"{target:g} LUFS  (Match music apps: Spotify, YouTube and Tidal use it)"
    if round(target) == -16:
        return f"{target:g} LUFS  (what Apple Music uses)"
    return f"{target:g} LUFS"


def describe_sound(config: EffectConfig) -> str:
    """The engine, path and direction in a few words."""
    if config.engine != "3d":
        return "left-right panning (speaker-friendly)"
    turn = "" if config.path == "arc" else f", {config.direction}"
    return f"3D, {_PATH_WORDS[config.path]}{turn}"


def describe_bass(bass_hz: float) -> str:
    """Where the bass sits."""
    if not bass_hz:
        return "moves with everything else"
    return f"stays in the middle below {bass_hz:g} Hz"


def describe_spin(config: EffectConfig) -> str:
    """How fast it goes round, including speed curves and beat sync."""
    if config.speed_curve:
        values = [value for _, value in config.speed_curve]
        return f"changes over time, {min(values):g}-{max(values):g} s per circle"
    if config.bpm:
        return f"whole bars at {config.bpm:g} BPM (near {config.rotation_seconds:g} s)"
    if config.beat_sync:
        return f"whole bars of the beat (near {config.rotation_seconds:g} s)"
    return f"{config.rotation_seconds:g} s per full circle"


def extras(config: EffectConfig, trim: Trim | None = None) -> list[str]:
    """Short notes for the switches that are on."""
    notes = []
    if config.elevation:
        notes.append(f"rises overhead ({config.elevation:.2f})")
    if config.vocals == "center":
        notes.append("singer kept in the middle")
    if config.intensity_curve:
        notes.append("movement changes over time")
    if config.fade_seconds:
        notes.append(f"eases in/out over {config.fade_seconds:g} s")
    if trim is not None and trim.is_set:
        start = format_time(trim.start or 0)
        end = format_time(trim.end) if trim.end is not None else "end"
        notes.append(f"only {start} to {end}")
    return notes


# A heads-up, and the setting changes that follow its advice
Advice = tuple[str, dict[str, object]]


def advice_items(config: EffectConfig) -> list[Advice]:  # pylint: disable=too-many-branches
    """Plain-word warnings for settings that may not sound their best, with fixes."""
    notes: list[Advice] = []

    def add(text: str, **fix: object) -> None:
        notes.append((text, fix))

    if not config.speed_curve and config.rotation_seconds < 5:
        add("A spin this fast can make people dizzy. Most people like 6 to 10 s.",
            rotation_seconds=8.0)  # fmt: skip
    elif not config.speed_curve and config.rotation_seconds > 20:
        add("A spin this slow is hard to notice. Most people like 6 to 10 s.",
            rotation_seconds=8.0)  # fmt: skip
    # Front's gentle 0.40 sway is on purpose; only far weaker movement is advised
    if 0 < config.intensity < 0.35:
        add("The movement is gentle and may be hard to hear. Try --intensity 0.8",
            intensity=0.8, intensity_curve=())  # fmt: skip
    elif config.intensity > 0.95 and config.engine == "pan":
        add("One ear goes almost silent at times, which can tire your ears. Try 0.8",
            intensity=0.8)  # fmt: skip
    if config.ambience > 0.6:
        add("This much room sound can make voices blurry. Try --ambience 0.25",
            ambience=0.25)  # fmt: skip
    if config.output_format == "mp3":
        if config.bitrate is None and config.quality >= 6:
            add("Lower quality: you may hear swishy sounds. Best is --bitrate 320",
                bitrate=320)  # fmt: skip
        elif config.bitrate is not None and config.bitrate < 192:
            add("Low bitrate: you may hear swishy sounds. Best is --bitrate 320",
                bitrate=320)  # fmt: skip
    best_roof = BEST.limiter_ceiling
    if config.limiter_ceiling > 0.95:
        add(f"Peaks this high may crackle on some phones. Best is {best_roof}",
            limiter_ceiling=best_roof)  # fmt: skip
    elif config.limiter_ceiling < 0.5:
        add(f"A peak roof this low makes the song very quiet. Best is {best_roof}",
            limiter_ceiling=best_roof)  # fmt: skip
    if config.match_loudness:
        pass
    elif config.loudness_target is None:
        add("Your 8D song will be quieter than normal music. "
            "Add --loudness -14 to fix it.", loudness_target=-14.0)  # fmt: skip
    elif config.loudness_target > -9:
        add("That is very loud; music apps will turn it down anyway. Best is -14",
            loudness_target=-14.0)  # fmt: skip
    elif config.loudness_target < -20:
        add("Quieter than music apps (-23 is for TV and radio). Best for music is -14",
            loudness_target=-14.0)  # fmt: skip
    if config.engine == "3d" and config.bass_hz == 0:
        add("Moving bass can feel unsteady. --bass 120 keeps it in the middle.",
            bass_hz=120.0)  # fmt: skip
    return notes


def advice(config: EffectConfig) -> list[str]:
    """The heads-ups alone, as the terminal prints them."""
    return [text for text, _fix in advice_items(config)]


def describe_source(info: AudioStreamInfo) -> str:
    """What the file is, e.g. 'MP3, 320 kbps, 48 kHz, stereo (already compressed)'."""
    parts = [info.codec_name.upper().replace("PCM_", "WAV/PCM ")]
    if info.bit_rate and not info.is_lossless:
        parts.append(f"{round(info.bit_rate / 1000)} kbps")
    if info.sample_rate:
        parts.append(f"{info.sample_rate / 1000:g} kHz")
    parts.append(
        {1: "mono", 2: "stereo"}.get(info.channels, f"{info.channels} channels")
    )
    if info.duration_seconds:
        parts.append(format_time(info.duration_seconds))
    kind = "lossless, perfect source" if info.is_lossless else "already compressed"
    return ", ".join(parts) + f"  ({kind})"


def source_notes(info: AudioStreamInfo, config: EffectConfig) -> list[str]:
    """Plain-word facts about this particular file and how Audio8D treats it."""
    notes = []
    if info.is_lossless:
        if config.is_lossless:
            notes.append("Perfect source and lossless output: nothing is lost at all.")
        else:
            notes.append(
                "Perfect source: the final encode is the only step that loses anything."
            )
    else:
        notes.append("Already compressed, so a little detail is gone for good.")
        if config.output_format == "mp3" and config.bitrate != 320:
            notes.append(
                "For this kind of file, --bitrate 320 (or --style studio) matters most."
            )
    if info.sample_rate and info.sample_rate > 48000 and not config.is_lossless:
        notes.append(
            f"{config.output_format.upper()} stores at most 48 kHz, so this "
            f"{info.sample_rate / 1000:g} kHz file is carefully resampled."
        )
    if info.channels == 1:
        notes.append(
            "Mono file: it is copied to both ears first, then the 8D movement starts."
        )
    elif info.channels > 2:
        notes.append("Surround file: it is folded down to left and right first.")
    if info.has_cover_art:
        if config.output_format in {"mp3", "flac", "m4a"}:
            notes.append("The album art is copied into the new file.")
        else:
            notes.append(
                f"{config.output_format.upper()} files can't hold album art, "
                "so it is left out."
            )
    return notes


# ------------------------------------------------------------------- the panel


def _banner(painter: Painter, version: str) -> None:
    """The title box at the top of every screen."""
    title = f"  Audio8D {version}  ·  developed by Gehan Fernando  "
    corners = (
        ("╭", "─", "╮", "│", "╰", "╯")
        if painter.fancy
        else ("+", "-", "+", "|", "+", "+")
    )
    if not painter.fancy:
        title = title.replace("·", "-")
    top_left, across, top_right, side, bottom_left, bottom_right = corners
    painter.line(painter.paint(top_left + across * len(title) + top_right, "violet"))
    painter.line(
        painter.paint(side, "violet")
        + painter.paint(title, "bold", "cyan")
        + painter.paint(side, "violet")
    )
    painter.line(
        painter.paint(bottom_left + across * len(title) + bottom_right, "violet")
    )


def _loudness_setting(config: EffectConfig) -> str:
    """The loudness row of the settings panel, e.g. 'Match music apps (-14 LUFS)'."""
    if config.match_loudness:
        how = "exactly" if config.exact_loudness else "dynamics kept"
        return f"Keep original loudness ({how})"
    if config.loudness_target is None:
        return "off (no change)"
    how = "exactly" if config.exact_loudness else "dynamics kept"
    if config.loudness_target == -14.0:
        return f"Match music apps (-14 LUFS, {how})"
    return f"{config.loudness_target:g} LUFS ({how})"


def _best_note(painter: Painter, is_best: bool, best_text: str) -> str:
    """Green '(best)' for the recommended value, otherwise a hint naming the best."""
    if is_best:
        return painter.paint("  (best)", "green")
    return painter.paint(f"  best: {best_text}", "dim")


def _quality_is_best(config: EffectConfig) -> bool:
    """320 kbps MP3, or any lossless format, is the best a format can do."""
    return config.is_lossless or config.bitrate == BEST.bitrate


def show_settings(  # pylint: disable=too-many-locals,too-many-arguments
    painter: Painter,
    *,
    version: str,
    song_in: Path,
    song_out: Path,
    preset: str | None,
    config: EffectConfig,
    banner: bool = True,
    source: AudioStreamInfo | None = None,
    trim: Trim | None = None,
    presets: Mapping[str, Preset] | None = None,
) -> None:
    """Print the banner and every setting in plain words, marking the best values."""
    known = presets or PRESETS
    # The guided mode has already shown the title box, so it can ask us to skip it
    if banner:
        _banner(painter, version)

    def row(label: str, value: str, note: str = "", color: str = "cyan") -> None:
        """One neat line: grey label, coloured value, then the best-value note."""
        label_text = painter.paint(f"{label:<11}", "dim")
        painter.line(
            f"  {label_text}{painter.paint(f'{value:<46}', color)}{note}".rstrip()
        )

    row("Song in", str(song_in), color="bold")
    row("Song out", str(song_out), color="bold")
    if source is not None:
        row("Source", describe_source(source), color="bold")
    if preset and preset in known:
        style = f"{preset}  -  {known[preset].summary}"
        row(
            "Style",
            style,
            _best_note(painter, preset == RECOMMENDED_PRESET, RECOMMENDED_PRESET),
            "pink",
        )
    else:
        row("Style", "your own settings", color="pink")
    painter.rule()
    row(
        "Sound",
        describe_sound(config),
        _best_note(painter, config.engine == "3d", "3D"),
    )
    row(
        "Speed",
        describe_spin(config),
        _best_note(
            painter,
            not config.speed_curve and config.rotation_seconds == BEST.rotation_seconds,
            "8 s",
        ),
    )
    row(
        "Movement",
        f"{config.intensity:.2f}  ({describe_movement(config.intensity)})",
        _best_note(
            painter, config.intensity == BEST.intensity, f"{BEST.intensity:.2f}"
        ),
    )
    row(
        "Bass",
        describe_bass(config.bass_hz),
        _best_note(painter, config.bass_hz == BEST.bass_hz, f"{BEST.bass_hz:g} Hz"),
    )
    row(
        "Space",
        f"{config.ambience:.2f}  ({describe_room(config.ambience)})",
        _best_note(painter, config.ambience == BEST.ambience, f"{BEST.ambience:.2f}"),
    )
    row(
        "Peak limit",
        describe_ceiling(config.limiter_ceiling),
        _best_note(
            painter,
            config.limiter_ceiling == BEST.limiter_ceiling or config.is_lossless,
            f"{BEST.limiter_ceiling:.2f}",
        ),
    )
    row(
        "Quality",
        describe_quality(config.quality, config.bitrate, config.output_format),
        _best_note(painter, _quality_is_best(config), f"{BEST.bitrate} kbps"),
    )
    row(
        "Loudness",
        _loudness_setting(config),
        _best_note(
            painter,
            (config.loudness_target == BEST.loudness_target or config.match_loudness)
            and config.exact_loudness == BEST.exact_loudness,
            "match music apps",
        ),
    )
    more = extras(config, trim)
    if more:
        row("Extras", ", ".join(more))

    facts = source_notes(source, config) if source is not None else []
    if facts:
        painter.line()
        painter.line("  " + painter.paint("Good to know:", "bold", "cyan"))
        for fact in facts:
            painter.line("   " + painter.paint("- " + fact, "cyan"))

    notes = advice(config)
    if notes:
        painter.line()
        painter.line("  " + painter.paint("Heads-up:", "bold", "yellow"))
        for note in notes:
            painter.line("   " + painter.paint("- " + note, "yellow"))
    painter.line()


# ---------------------------------------------------------------- progress bars


def _bar(painter: Painter, share: float, width: int = 26) -> str:
    """A text bar like '━━━━━━━━━━' in two colours (or '#####.....' on old consoles)."""
    filled = int(round(share * width))
    # Thin lines stay separate when several finished bars sit on top of each other
    full, empty = ("━", "━") if painter.fancy else ("#", ".")
    return painter.paint(full * filled, "cyan") + painter.paint(
        empty * (width - filled), "dim"
    )


class ProgressBar:
    """One moving bar per stage in a terminal; plain stage lines anywhere else."""

    _LABELS = {
        STAGE_STEMS: "Splitting vocals (AI, may take a few minutes)",
        STAGE_RENDER: "Making your 8D song",
        STAGE_SAVE: "Saving the file",
        STAGE_CHECK: "Checking the result",
    }

    def __init__(self, painter: Painter) -> None:
        """Nothing is drawn until the first update."""
        self.painter = painter
        self.stage: str | None = None
        self.shown = -1

    def update(self, stage: str, share: float) -> None:
        """Move the bar; a new stage finishes the previous line first."""
        if stage != self.stage:
            self.finish()
            self.stage = stage
            self.shown = -1
            if not self.painter.live:
                self.painter.line(
                    "  "
                    + self.painter.paint(
                        self._LABELS.get(stage, stage) + "...", "yellow"
                    )
                )
        percent = int(share * 100)
        if self.painter.live and percent != self.shown:
            self.shown = percent
            label = self._LABELS.get(stage, stage)
            self.painter.redraw(
                f"  {_bar(self.painter, share)} {percent:>3}%  "
                + self.painter.paint(label, "yellow")
            )

    def finish(self) -> None:
        """End the current bar's line."""
        if self.stage is not None and self.painter.live:
            self.painter.line()
        self.stage = None


class BatchBar:
    """The overall bar for many songs, redrawn under each finished song's line."""

    def __init__(self, painter: Painter, count: int) -> None:
        """Remember how many songs there are."""
        self.painter = painter
        self.count = count
        self.finished = 0
        self.share = 0.0

    def draw(self, share: float | None = None) -> None:
        """Redraw the overall bar."""
        if share is not None:
            self.share = share
        if not self.painter.live:
            return
        self.painter.redraw(
            f"  {_bar(self.painter, self.share)} {int(self.share * 100):>3}%  "
            + self.painter.paint(
                f"{self.finished} of {self.count} songs done", "yellow"
            )
        )

    def song_line(self, text: str) -> None:
        """Print a finished song's line above the bar, then redraw the bar."""
        self.finished += 1
        if self.painter.live:
            self.painter.redraw(text)
            self.painter.line()
        else:
            self.painter.line(text)
        self.draw()

    def close(self) -> None:
        """Leave the bar's line."""
        if self.painter.live:
            self.painter.line()


# ------------------------------------------------------------------ afterwards


def _size_of(path: Path) -> str:
    """'4.2 MB', or 'size unknown'."""
    try:
        return f"{path.stat().st_size / 1_048_576:.1f} MB"
    except OSError:
        return "size unknown"


def show_done(painter: Painter, song_out: Path, seconds: float) -> None:
    """Celebrate a finished conversion with the time taken and the file size."""
    painter.line(
        "  "
        + painter.paint(f"Created in {seconds:.1f} s", "bold", "green")
        + painter.paint(f"  ->  {song_out}  ({_size_of(song_out)})", "green")
    )


def show_listen(painter: Painter) -> None:
    """The last, happy line."""
    painter.line(painter.paint("  Put on your headphones and press play!", "green"))


def show_beat(painter: Painter, result: ConversionResult) -> None:
    """Explain the beat sync: the tempo found and the spin it chose."""
    if result.bpm is None:
        if result.config.beat_sync:
            painter.line(
                painter.paint(
                    "  Beat: no clear beat found, so the spin kept its own speed.",
                    "dim",
                )
            )
        return
    painter.line(
        "  "
        + painter.paint("Beat:", "bold", "green")
        + painter.paint(
            f" {result.bpm:g} BPM, so one circle = {result.beats_per_turn} beats"
            f" ({result.config.rotation_seconds:.1f} s)",
            "green",
        )
    )


# Further than this from the target is worth telling the user about
_TARGET_MISS_LU = 0.5


def show_loudness(
    painter: Painter, plan: LoudnessPlan, report: QualityReport | None = None
) -> None:
    """Explain the loudness pass: what was measured, what changed, where it landed.

    With the after-check's report the landing is the file's measured loudness;
    without it only the aim is known, since the limiter can pull the song lower.
    """
    measured = plan.measured
    direction = "up" if plan.gain_db >= 0 else "down"
    reused = " (remembered)" if plan.cached else ""
    landing = (
        f"{report.integrated_lufs:.1f} LUFS (checked)"
        if report is not None
        else f"aims for {plan.expected_lufs:.1f} LUFS"
    )
    painter.line(
        "  "
        + painter.paint("Loudness:", "bold", "green")
        + painter.paint(
            f" measured {measured.integrated_lufs:.1f} LUFS{reused}, turned {direction}"
            f" {abs(plan.gain_db):.1f} dB  ->  {landing}",
            "green",
        )
    )
    if plan.silent:
        # Silence has no loudness to reach, so there is nothing more to explain
        return
    if plan.held_back:
        painter.line(
            painter.paint(
                f"  Kept below {plan.target_lufs:g} so the loudest moments are not "
                "squashed. (--exact-loudness would force it.)",
                "dim",
            )
        )
    elif report is not None and (
        report.integrated_lufs < plan.target_lufs - _TARGET_MISS_LU
    ):
        painter.line(
            painter.paint(
                "  Holding the loudest peaks down left it "
                f"{plan.target_lufs - report.integrated_lufs:.1f} LU under "
                f"{plan.target_lufs:g}; a quieter target keeps more punch.",
                "yellow",
            )
        )
    elif plan.exact and report is None:
        painter.line(
            painter.paint(
                "  The loudest peaks are shaved to get there; heavy shaving can "
                "leave it a little quieter.",
                "dim",
            )
        )
    elif plan.exact:
        painter.line(
            painter.paint("  The loudest peaks were shaved lightly to reach it.", "dim")
        )


def show_quality(painter: Painter, report: QualityReport) -> None:
    """The after-check: loudness, peaks and mono safety of the finished file."""
    mono = (
        f"mono-safe (correlation {report.correlation:+.2f})"
        if report.mono_safe
        else f"weak in mono (correlation {report.correlation:+.2f})"
    )
    painter.line(
        "  "
        + painter.paint("Check:", "bold", "green")
        + painter.paint(
            f" {report.integrated_lufs:.1f} LUFS, peaks {report.true_peak_db:.1f} dBTP,"
            f" range {report.range_lu:.1f} LU, {mono}",
            "green",
        )
    )
    if not report.peak_safe:
        painter.line(
            painter.paint(
                "  Peaks touch the top; lower --limiter-ceiling to 0.84 to be safe.",
                "yellow",
            )
        )
    if not report.mono_safe:
        painter.line(
            painter.paint(
                "  On a single phone speaker parts may sound thin. "
                "--speakers makes a safer version.",
                "yellow",
            )
        )


def show_removed(painter: Painter, original: Path, where: str) -> None:
    """Say where the original song went."""
    painter.line(
        painter.paint(f"  Original {original.name} {describe_removal(where)}.", "dim")
    )


def show_result(painter: Painter, result: ConversionResult, seconds: float) -> None:
    """Everything after one conversion: done, beat, loudness, check, removal."""
    show_done(painter, result.output, seconds)
    show_beat(painter, result)
    if result.loudness is not None:
        show_loudness(painter, result.loudness, result.quality)
    if result.quality is not None:
        show_quality(painter, result.quality)


def show_tip(painter: Painter, style: str = RECOMMENDED_PRESET) -> None:
    """Point first-time users at the other styles and the preview."""
    painter.line()
    painter.line(
        "  "
        + painter.paint("Tip:", "bold", "yellow")
        + " this used the "
        + painter.paint(style, "bold", "pink")
        + " style. Listen first with "
        + painter.paint("--preview", "bold")
        + painter.paint("   (every style: --list-styles)", "dim")
    )


def show_fix(painter: Painter, fix: str) -> None:
    """Tell the user, in plain words, how to solve the error they just hit."""
    painter.line("  " + painter.paint("What to do:", "bold", "yellow") + " " + fix)


# --------------------------------------------------------------------- batches


def show_batch_plan(
    painter: Painter, count: int, jobs: int, output_dir: Path | None, replace: bool
) -> None:
    """Say what is about to happen to the whole folder."""
    where = f"in {output_dir}" if output_dir else "next to each original"
    painter.line(
        "  "
        + painter.paint(f"{count} songs", "bold", "cyan")
        + painter.paint(f", {min(jobs, count)} at a time, saved {where}.", "cyan")
    )
    if replace:
        painter.line(
            painter.paint(
                "  Each original goes to the Recycle Bin after its 8D copy is saved "
                "(on a USB stick it stays, renamed '<song> (original)').",
                "yellow",
            )
        )
    painter.line()


def batch_line(painter: Painter, number: int, total: int, outcome: BatchOutcome) -> str:
    """One finished song's line: a green tick and its size, or a red cross."""
    result, error, item = outcome.result, outcome.error, outcome.item
    seconds = outcome.seconds
    tick, cross = ("✓", "✗") if painter.fancy else ("OK", "X")
    counter = painter.paint(f"[{number:>{len(str(total))}}/{total}]", "dim")
    if result is not None:
        extra = f"  {result.quality.integrated_lufs:.1f} LUFS" if result.quality else ""
        return (
            f"  {counter} "
            + painter.paint(tick, "bold", "green")
            + f"  {result.output.name}"
            + painter.paint(
                f"  ({_size_of(result.output)}, {seconds:.1f} s{extra})", "dim"
            )
        )
    return (
        f"  {counter} "
        + painter.paint(cross, "bold", "red")
        + f"  {item.source.name}  "
        + painter.paint(str(error), "red")
    )


def show_batch_summary(painter: Painter, report: BatchReport) -> None:
    """The totals at the end of a batch."""
    converted = report.converted
    failed = report.failed
    seconds = report.seconds
    painter.line()
    painter.line(
        "  "
        + painter.paint(f"Done: {len(converted)} created", "bold", "green")
        + (painter.paint(f", {len(failed)} failed", "bold", "red") if failed else "")
        + painter.paint(f" in {format_time(seconds)} ({seconds:.1f} s).", "green")
    )
    places = [result.original_removed_to for result in report.results]
    for line in removal_summary([place for place in places if place]):
        painter.line(painter.paint(f"  {line}", "dim"))


# ------------------------------------------------------------------ the menus


def show_presets(
    painter: Painter, version: str, presets: Mapping[str, Preset] | None = None
) -> None:
    """Print every preset with its exact values, recommended one first."""
    _banner(painter, version)
    painter.line(
        painter.paint(
            "  Sound styles - use one with:  audio8d song.mp3 --style NAME", "bold"
        )
    )
    painter.line()
    header = f"  {'NAME':<12}{'SPEED':>6}{'MOVE':>6}{'SPACE':>6}  {'ENGINE':<9}GOOD FOR"
    painter.line(painter.paint(header, "dim"))
    for name, preset in (presets or PRESETS).items():
        cfg = preset.config
        label = f"{name} *" if name == RECOMMENDED_PRESET else name
        sound = ("3D " if cfg.engine == "3d" else "pan ") + {
            "circle": "O",
            "arc": "(",
            "figure8": "8",
            "wander": "~",
        }[cfg.path]
        spin = "beat" if cfg.beat_sync else f"{cfg.rotation_seconds:g}s"
        numbers = f"{spin:>6}{cfg.intensity:>6.2f}{cfg.ambience:>6.2f}  {sound:<9}"
        color = "pink" if name == RECOMMENDED_PRESET else "cyan"
        summary = preset.summary + ("  (yours)" if preset.custom else "")
        painter.line(
            f"  {painter.paint(f'{label:<12}', 'bold', color)}{numbers}{summary}"
        )
    painter.line()
    painter.line(
        painter.paint(
            "  * recommended. A style is only the sound: every style is saved as MP3 "
            "320 kbps at music-app loudness unless you add --format or --loudness.",
            "dim",
        )
    )
    painter.line(
        painter.paint(
            "  Any setting you add (e.g. --movement strong) changes the style. Older "
            "names lossless, streaming and hifi still work and also set the output.",
            "dim",
        )
    )
    painter.line(
        painter.paint(
            "  Paths: O circle, ( front arc, 8 figure-8, ~ wander. "
            "Save your own with --save-style NAME.",
            "dim",
        )
    )


def show_welcome(painter: Painter, version: str) -> None:
    """First screen of the guided mode."""
    _banner(painter, version)
    painter.line(
        "  "
        + painter.paint("Welcome! Let's make your music fly around your head.", "bold")
    )
    painter.line(
        "  Just answer a few quick questions. Press Enter for the best answer. "
        "You can't break anything."
    )
    painter.line()


def show_step(painter: Painter, number: int, total: int, title: str, hint: str) -> None:
    """Heading for one step of the guided mode."""
    painter.line(
        "  " + painter.paint(f"Step {number} of {total} - {title}", "bold", "cyan")
    )
    painter.line("  " + painter.paint(hint, "dim"))


def show_style_menu(
    painter: Painter, presets: Mapping[str, Preset] | None = None
) -> list[str]:
    """Numbered list of styles, best first; returns the names in menu order."""
    known = presets or PRESETS
    names = list(known)
    for number, name in enumerate(names, start=1):
        badge = (
            painter.paint("  BEST ", "bold", "green")
            if name == RECOMMENDED_PRESET
            else "       "
        )
        label = painter.paint(
            f"{name:<10}", "bold", "pink" if name == RECOMMENDED_PRESET else "cyan"
        )
        number_text = painter.paint(f"{number:>2}", "bold")
        painter.line(f"  {number_text}  {label}{badge}{known[name].summary}")
    return names


def show_choices(painter: Painter, choices: list[tuple[str, str]]) -> None:
    """A short numbered list of (label, explanation) pairs, the first is default."""
    for number, (label, explanation) in enumerate(choices, start=1):
        default = painter.paint("  (Enter)", "green") if number == 1 else ""
        painter.line(
            f"   {painter.paint(str(number), 'bold')}  "
            f"{painter.paint(label, 'bold', 'cyan')}{default}  "
            + painter.paint(explanation, "dim")
        )


def show_song_list(painter: Painter, songs: list[Path], folder: Path) -> None:
    """Numbered list of the songs found in a folder."""
    painter.line(
        "  " + painter.paint(f"Found {len(songs)} songs in {folder}:", "bold", "cyan")
    )
    width = len(str(len(songs)))
    for number, song in enumerate(songs, start=1):
        try:
            name = str(song.relative_to(folder))
        except ValueError:
            name = song.name
        painter.line(f"   {painter.paint(f'{number:>{width}}', 'bold')}  {name}")


def show_problem(painter: Painter, text: str) -> None:
    """A gentle, non-scary message when an answer can't be used."""
    painter.line("  " + painter.paint(text, "yellow"))
