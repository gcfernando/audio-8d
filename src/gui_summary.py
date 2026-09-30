# Developed by ::> Gehan Fernando
"""The window's plain-word summaries: what will happen, each song's plan, the status.

Everything here reads a GuiSettings and describes it; nothing is changed.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path

from .core.errors import InputValidationError
from .core.parsing import format_time, parse_keyframes
from .core.presets import PRESETS, Preset
from .core.settings import EffectConfig
from .core.types import AudioStreamInfo
from .gui_model import (
    GuiSettings,
    config_for,
    destination_for,
    is_custom,
    items_for,
    name_style_for,
    singer_songs,
    song_config,
)


def style_label(name: str, styles: Mapping[str, Preset] | None = None) -> str:
    """How a style's name is shown: Studio, Streaming, or yours as you saved it."""
    preset = (styles or PRESETS).get(name) or PRESETS.get(name)
    return preset.label if preset else name


# What each file type means for sound, size and where it plays
FORMAT_WORDS = {
    "mp3": "plays on every phone, car and app; small files",
    "flac": "lossless: nothing is lost; about 3 times bigger than MP3; plays on "
    "most devices",
    "wav": "lossless and very big; no album picture; plays almost everywhere",
    "m4a": "great on iPhone and iTunes; small files",
    "opus": "the smallest files for the quality; some older players can't open it",
}


def file_words(config: EffectConfig) -> str:
    """'MP3, 320 kbps (the best MP3 can be)' - the file type and quality in words."""
    kind = config.output_format
    if kind in ("flac", "wav"):
        return f"{kind.upper()} (lossless)"
    if kind == "mp3":
        if config.bitrate:
            best = " (the best MP3 can be)" if config.bitrate == 320 else ""
            return f"MP3, {config.bitrate} kbps{best}"
        return f"MP3, variable quality V{config.quality}"
    default = 256 if kind == "m4a" else 192
    return (
        f"{'M4A (AAC)' if kind == 'm4a' else 'Opus'}, {config.bitrate or default} kbps"
    )


def loudness_words(config: EffectConfig) -> str:
    """How loud the new songs will be, in words."""
    if config.match_loudness:
        return "Each song keeps its own loudness"
    if config.loudness_target is None:
        return "Natural level (no loudness change; often quieter)"
    names = {
        -14: "like Spotify and YouTube",
        -16: "like Apple Music",
        -23: "TV and radio",
    }
    name = names.get(round(config.loudness_target))
    exact = ", exactly" if config.exact_loudness else ""
    return f"{config.loudness_target:g} LUFS" + (f" ({name}{exact})" if name else "")


def _count(count: int, one: str, many: str) -> str:
    """'1 song has' / '3 songs have' style wording."""
    return f"{count} {one if count == 1 else many}"


def _tally(names: Sequence[str]) -> str:
    """'Studio x3, Smooth x1' - how often each name appears, most first."""
    counts: dict[str, int] = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    return ", ".join(
        f"{name} x{number}"
        for name, number in sorted(counts.items(), key=lambda kv: -kv[1])
    )


def quality_words(config: EffectConfig) -> str:
    """'MP3, High quality' - the output format and quality in plain words."""
    kind = config.output_format
    if kind in ("flac", "wav"):
        return f"{kind.upper()}, lossless"
    names = {320: "High", 192: "Medium", 128: "Small"}
    name = names.get(config.bitrate or 0)
    label = {"m4a": "M4A", "opus": "Opus"}.get(kind, "MP3")
    if name:
        return f"{label}, {name} quality"
    return file_words(config)


def plain_loudness(config: EffectConfig) -> str:
    """'Match music apps' - the loudness choice as the Output step names it."""
    if config.match_loudness:
        return "Keep original loudness"
    if config.loudness_target is None:
        return "No change (often quieter than other music)"
    if config.loudness_target == -14.0:
        return "Match music apps"
    return loudness_words(config)


def _naming(settings: GuiSettings, config: EffectConfig | None) -> str:
    """How the new files will be named, in words."""
    extension = config.extension if config else ".mp3"
    return {
        "8d": f"'<song name> (8D){extension}'",
        "original": f"The song's own name ('<song name>{extension}')",
        "custom": f"'{settings.custom_name.strip()}'"
        if settings.custom_name.strip()
        else "A name of your own (not typed yet)",
    }[settings.name_style if settings.originals == "keep" else name_style_for(settings)]


def plan_summary(
    settings: GuiSettings,
    songs: Sequence[tuple[Path, Path | None]],
    styles: Mapping[str, Preset] | None = None,
    skipped: int = 0,
) -> list[tuple[str, str]]:
    """(label, plain words): a short summary of what Create will do, no more."""
    known = styles or PRESETS
    count = len(songs)
    rows = [
        (
            "Songs",
            (_count(count, "song", "songs") if count else "None yet")
            + (f" ({skipped} that can't be read will be skipped)" if skipped else ""),
        )
    ]
    custom = [s for s, _f in songs if is_custom(settings, s)]
    preset = known.get(settings.style)
    changed = preset is not None and settings.differs_from(preset)
    sound = style_label(settings.style, known) + (" (customized)" if changed else "")
    if custom:
        sound += f"; {_count(len(custom), 'song has', 'songs have')} custom settings"
    rows.append(("Sound", sound))
    try:
        config: EffectConfig | None = config_for(settings)
    except InputValidationError:
        config = None
    if config is not None:
        rows.append(("Output", quality_words(config)))
        rows.append(("Loudness", plain_loudness(config)))
    destination = destination_for(settings)
    rows.append(
        ("Folder", str(destination) if destination else "Next to each original song")
    )
    rows.append(("File names", _naming(settings, config)))
    if settings.originals != "keep":
        rows.append(("Original songs", "Moved to the Recycle Bin once each is saved"))
    singers = singer_songs(settings, songs, styles)
    if singers:
        rows.append(
            (
                "Singer in the middle",
                f"{_count(len(singers), 'song', 'songs')} (uses the add-on; a minute "
                "or two more per song)",
            )
        )
    return rows


def file_short(
    settings: GuiSettings, song: Path, styles: Mapping[str, Preset] | None = None
) -> str:
    """'FLAC, -14 LUFS' - a song's file type and loudness in a few words."""
    try:
        config = song_config(settings, song, styles)
    except InputValidationError:
        return "needs fixing"
    if config.match_loudness:
        level = "own loudness"
    elif config.loudness_target is None:
        level = "natural level"
    else:
        level = f"{config.loudness_target:g} LUFS"
    kind = config.output_format.upper()
    if config.output_format == "mp3" and config.bitrate:
        kind += f" {config.bitrate}"
    return f"{kind}, {level}"


def song_plan(
    settings: GuiSettings,
    songs: Sequence[tuple[Path, Path | None]],
    styles: Mapping[str, Preset] | None = None,
) -> list[tuple[Path, str, str, str]]:
    """(song, style, file, new file) for every song, exactly as it will be made."""
    try:
        items = items_for(settings, songs, styles)
    except InputValidationError:
        return []
    plan = []
    for item in items:
        style = style_label(
            settings.song_styles.get(item.source, settings.style), styles
        )
        label = style + (" (custom)" if is_custom(settings, item.source) else "")
        files = file_short(settings, item.source, styles)
        plan.append((item.source, label, files, str(item.output)))
    return plan


def describe(settings: GuiSettings) -> str:
    """One line summing up the choices, for the status bar."""
    config = config_for(settings)
    parts = [
        "3D" if config.engine == "3d" else "panning",
        config.path,
        "beat sync"
        if config.beat_sync or config.bpm
        else f"{config.rotation_seconds:g} s",
        config.output_format.upper(),
    ]
    if config.match_loudness:
        parts.append("original loudness")
    elif config.loudness_target is not None:
        parts.append(f"{config.loudness_target:g} LUFS")
    if settings.speakers:
        parts.append("speaker-safe")
    custom = len(
        set(settings.song_styles) | set(settings.song_sound) | set(settings.song_files)
    )
    if custom:
        parts.append(f"{custom} custom song{'s' if custom != 1 else ''}")
    return " · ".join(parts)


def describe_curve(text: str, unit: str) -> str:
    """'10 s from 0:00, 6 s from 1:00' - a typed curve read back in words."""
    frames = parse_keyframes(text)
    return ", then ".join(
        f"{value:g}{unit} at {format_time(time)}" for time, value in frames
    )


# Below this, an MP3 or AAC file has already lost detail the 8D version can't bring back
LOW_BITRATE = 192_000
# Below this, a recording (a phone or voice memo) has no high notes to move around
LOW_SAMPLE_RATE = 32_000


def source_notes(songs: Sequence[tuple[str, AudioStreamInfo]]) -> list[str]:
    """Heads-ups about the song files themselves, since they decide the best result."""

    def some(names: list[str], one: str, many: str) -> str:
        examples = ", ".join(names[:2]) + (" and others" if len(names) > 2 else "")
        return (one if len(names) == 1 else f"{len(names)} {many}") + f" ({examples})"

    notes = []
    low = [
        name
        for name, info in songs
        if not info.is_lossless and info.bit_rate and info.bit_rate < LOW_BITRATE
    ]
    if low:
        notes.append(
            some(low, "1 song is a low-quality file", "songs are low-quality files")
            + ", under 192 kbps. The 8D version can't sound better than the file you "
            "give it: use a better copy (FLAC, WAV or a 320 kbps MP3) if you have one."
        )
    thin = [
        name
        for name, info in songs
        if info.sample_rate and info.sample_rate < LOW_SAMPLE_RATE
    ]
    if thin:
        notes.append(
            some(
                thin,
                "1 song is a low-detail recording",
                "songs are low-detail recordings",
            )
            + ", like a phone or voice memo. Audio8D raises it so the 3D effect works, "
            "but it can't add the missing high notes."
        )
    return notes
