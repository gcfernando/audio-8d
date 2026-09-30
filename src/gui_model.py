# Developed by ::> Gehan Fernando
"""Everything the Audio8D window decides, kept apart from the widgets.

The window only reads and writes a GuiSettings. Turning that into the same
EffectConfig, ConvertOptions and output paths the command line uses, checking
it, and explaining it in plain words all happen here, where it can be tested
without a screen. Nothing here converts audio: that stays in pipeline/batch.
"""

import dataclasses
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import display
from .batch import MAX_JOBS, BatchItem, default_jobs
from .core.errors import InputValidationError
from .core.parsing import (
    format_keyframes,
    parse_keyframes,
    typed_loudness,
    typed_number,
)
from .core.presets import (
    PRESETS,
    QUALITY_TIERS,
    RECOMMENDED_PRESET,
    STANDARD_OUTPUT,
    Preset,
    with_format,
)
from .core.settings import FORMAT_EXTENSIONS, EffectConfig, speaker_safe
from .core.types import Trim
from .files import default_output_for
from .pipeline import ConvertOptions
from .song_settings import (
    FILE_KEYS,
    FILE_OPTIONS,
    OUTPUT_FIELDS,
    SOUND_KEYS,
    SPEAKERS,
    check_keys,
    needs_singer,
    parse_trim,
    song_convert_options,
    song_effect,
    with_output,
)

BITRATE_CHOICES = ("Auto", "128", "160", "192", "224", "256", "320")
# The window's words for the output choices (the values are what the file gets)
FORMAT_CHOICES = {
    "MP3 — works everywhere": "mp3",
    "FLAC — lossless quality": "flac",
    "WAV — uncompressed": "wav",
    "M4A — small, high-quality files": "m4a",
    "Opus — efficient modern format": "opus",
}
# High, Medium and Small by format; MP3's are the ones shown for most songs
QUALITY_CHOICES = {"High": 320, "Medium": 192, "Small": 128}


def quality_choices(output_format: str) -> dict[str, int]:
    """High / Medium / Small for one format, in kbps."""
    tiers = QUALITY_TIERS.get(output_format, QUALITY_TIERS["mp3"])
    return dict(zip(("High", "Medium", "Small"), tiers, strict=True))


LOUDNESS_MAIN = {
    "Match music apps": -14.0,
    "Keep original loudness": "match",
    "Advanced…": "advanced",
}
LOUDNESS_MORE = {
    "Apple Music (-16)": -16.0,
    "TV & radio (-23)": -23.0,
    "No change": None,
    "Custom…": "custom",
}
ORIGINAL_CHOICES = ("keep", "replace", "replace-8d")

# The command line's words for things, and the window's words for the same things
_GUI_WORDS = (
    (
        r"set it up \(audio8d --install-addon, then audio8d --check\)",
        "install it in Settings (Add-on, 'Install add-on')",
    ),
    (r"audio8d --install-addon", "'Install add-on' in Settings"),
    (r"audio8d --repair-addon", "'Repair' in Settings (Add-on)"),
    (
        r"--rotation-seconds (-?[0-9]+(?:\.[0-9]+)?)",
        r"Speed \1 s (Customize, Advanced)",
    ),
    (r"--intensity (-?[0-9]+(?:\.[0-9]+)?)", r"Movement \1 (Customize, Advanced)"),
    (r"--ambience (-?[0-9]+(?:\.[0-9]+)?)", r"Space \1 (Customize, Advanced)"),
    (r"--bitrate 320", "Quality: High (Output)"),
    (
        r"--bitrate (-?[0-9]+(?:\.[0-9]+)?)",
        r"Bitrate \1 (Output, More output options)",
    ),
    (
        r"--limiter-ceiling (-?[0-9]+(?:\.[0-9]+)?)",
        r"Peak limit \1 (Output, More output options)",
    ),
    (r"--loudness -14", "Loudness: Match music apps (Output)"),
    (r"--loudness match", "Loudness: Keep original loudness (Output)"),
    (r"--loudness (-?[0-9]+(?:\.[0-9]+)?|off)", r"Loudness \1 (Output, Advanced…)"),
    (r"--bass 120", "'Keep bass centered' (Customize)"),
    (r"--(?:style|preset) studio", "the Studio style (Change style, step 2)"),
    (r"--speakers", "'Safe for speakers too' (Customize, Advanced)"),
    (
        r"--quality (-?[0-9]+(?:\.[0-9]+)?)",
        r"MP3 quality \1 (Output, More output options)",
    ),
    (r"--overwrite", "'If the 8D file exists: Replace it' (Output)"),
    (r"--vocals center", "'Keep the singer in the middle' (Customize)"),
    (r"--recursive", "'Include songs in sub-folders' (Add music step)"),
    (r"--format", "the output format (Output)"),
    (r"--start", "the part-of-song times (Output, More output options)"),
    (r"--end", "the part-of-song times (Output, More output options)"),
    (r"--verbose", "'Show technical details' (Settings)"),
    (r"with --save-style", "on the Your styles page"),
    (r"--elevation (-?[0-9]+(?:\.[0-9]+)?)", r"Height \1 (Customize, Advanced)"),
    (r"--fade (-?[0-9]+(?:\.[0-9]+)?)", r"Ease in and out \1 s (Customize, Advanced)"),
    (r"--bpm (-?[0-9]+(?:\.[0-9]+)?)", r"Tempo \1 (Customize, Advanced)"),
    (r'--speed-curve ("[^"]*")', r"\1 in 'Speed over time' (Customize, Advanced)"),
    (
        r'--intensity-curve ("[^"]*")',
        r"\1 in 'Movement over time' (Customize, Advanced)",
    ),
    (r"see --list-styles for where it is", "its place is shown on Your styles"),
    (
        r"type audio8d alone and drag the folder in",
        "drag the folder onto the window",
    ),
    (
        r"type audio8d alone, press Enter, drag the song in",
        "drag the song onto the window",
    ),
    # The curve checks name their settings the programmer's way
    (r"\bspeed_curve\b", "Speed over time"),
    (r"\bintensity_curve\b", "Movement over time"),
)

# The per-song names the pages use, kept importable from here
__all__ = [
    "FILE_KEYS",
    "FILE_OPTIONS",
    "OUTPUT_FIELDS",
    "SOUND_KEYS",
    "SPEAKERS",
    "with_output",
]


def gui_words(text: str) -> str:
    """Rewrite a command-line hint so it names the window's controls instead."""
    for pattern, replacement in _GUI_WORDS:
        text = re.sub(pattern, replacement, text)
    return text


@dataclass
class GuiSettings:  # pylint: disable=too-many-instance-attributes
    """Every choice on the window's pages, starting from a style."""

    style: str = RECOMMENDED_PRESET
    # The sound knobs (from the style) and the Output step's file settings
    sound: EffectConfig = field(
        default_factory=lambda: PRESETS[RECOMMENDED_PRESET].config
    )
    speakers: bool = False
    # Typed values, kept as text until the conversion so mistakes can be shown
    speed_curve_text: str = ""
    intensity_curve_text: str = ""
    bpm_text: str = ""
    custom_loudness_text: str = "-14"
    loudness_is_custom: bool = False
    # Songs page
    recursive: bool = True
    # Output page
    destination: str = ""
    originals: str = "keep"
    name_style: str = "8d"
    custom_name: str = ""
    overwrite: bool = False
    keep_cover: bool = True
    tag_title: bool = True
    check: bool = True
    trim_start: str = ""
    trim_end: str = ""
    jobs: int = field(default_factory=default_jobs)
    play_when_done: bool = False
    preview_seconds: int = 30
    # Settings page
    verbose: bool = False
    # Songs that use a style of their own instead of the one for all songs
    song_styles: dict[Path, str] = field(default_factory=dict)
    # Songs with file settings of their own: song -> {FILE_KEYS name: value}
    song_files: dict[Path, dict[str, object]] = field(default_factory=dict)
    # Songs with sound settings of their own: song -> {SOUND_KEYS name: value}
    song_sound: dict[Path, dict[str, object]] = field(default_factory=dict)

    def apply_style(self, preset: Preset) -> None:
        """Take every sound knob from a style; the Output step's choices stay."""
        self.style = preset.name
        self.sound = with_output(preset.config, self.sound)
        self.speed_curve_text = format_keyframes(preset.config.speed_curve)
        self.intensity_curve_text = format_keyframes(preset.config.intensity_curve)
        self.bpm_text = f"{preset.config.bpm:g}" if preset.config.bpm else ""

    def change(self, **knobs: object) -> None:
        """Change some sound or output knobs, keeping the rest."""
        knobs = dict(knobs)
        output_format = knobs.pop("output_format", None)
        if output_format is not None and output_format != self.sound.output_format:
            self.sound = with_format(self.sound, str(output_format))
        self.sound = dataclasses.replace(self.sound, **knobs)

    def reset_output(self) -> None:
        """The Output step's file settings go back to the recommended ones."""
        self.sound = dataclasses.replace(self.sound, **STANDARD_OUTPUT)
        self.loudness_is_custom = False

    def differs_from(self, preset: Preset) -> bool:
        """True when the sound knobs no longer match the chosen style exactly."""
        try:
            config = config_for(self, with_speakers=False)
        except InputValidationError:
            return True
        return with_output(config, preset.config) != preset.config or self.speakers


def config_for(settings: GuiSettings, *, with_speakers: bool = True) -> EffectConfig:
    """The exact EffectConfig the conversion will use (raises if something's wrong)."""
    config = settings.sound
    try:
        speed = (
            parse_keyframes(settings.speed_curve_text)
            if settings.speed_curve_text.strip()
            else ()
        )
        amount = (
            parse_keyframes(settings.intensity_curve_text)
            if settings.intensity_curve_text.strip()
            else ()
        )
    except InputValidationError as exc:
        raise InputValidationError(f"Changes over time: {exc}") from None
    bpm = typed_number(settings.bpm_text, "The tempo (BPM)", 40, 240)
    config = dataclasses.replace(
        config, speed_curve=speed, intensity_curve=amount, bpm=bpm
    )
    if settings.loudness_is_custom:
        target = typed_loudness(settings.custom_loudness_text)
        config = dataclasses.replace(
            config, loudness_target=target, match_loudness=False
        )
    if with_speakers and settings.speakers:
        config = speaker_safe(config)
    config.validate()
    return config


def trim_for(settings: GuiSettings) -> Trim | None:
    """The chosen part of the song, or None for all of it."""
    return parse_trim(settings.trim_start, settings.trim_end)


def options_for(settings: GuiSettings) -> ConvertOptions:
    """What happens to the files, beyond the sound."""
    return ConvertOptions(
        trim=trim_for(settings),
        keep_cover=settings.keep_cover,
        tag_title=settings.tag_title,
        check=settings.check,
        replace_original=settings.originals != "keep",
    )


def destination_for(settings: GuiSettings) -> Path | None:
    """The chosen output folder, or None for 'next to each original'."""
    text = settings.destination.strip()
    return Path(text).expanduser() if text else None


def name_style_for(settings: GuiSettings) -> str:
    """'8d' or 'original' for the new file names (replacing implies original)."""
    if settings.originals == "replace":
        return "original"
    if settings.originals == "replace-8d":
        return "8d"
    return "original" if settings.name_style == "original" else "8d"


def style_for(
    settings: GuiSettings, song: Path, styles: Mapping[str, Preset]
) -> Preset | None:
    """The song's own style, or None when it uses the style for all songs."""
    name = settings.song_styles.get(song)
    return styles.get(name) if name else None


def song_config(
    settings: GuiSettings, song: Path, styles: Mapping[str, Preset] | None = None
) -> EffectConfig:
    """The exact settings one song gets (preview and conversion use the same).

    A song with its own style gets that style's sound exactly as saved; the file
    type, quality and loudness are the Output step's defaults. On top of that
    come the song's own sound and file settings (both from Customize).
    """
    return _song_config(
        settings, song, styles, config_for(settings, with_speakers=False)
    )


def _own_changes(settings: GuiSettings, song: Path) -> dict[str, object]:
    """A song's own sound settings plus its own file type, quality and loudness."""
    files = settings.song_files.get(song, {})
    return {
        **settings.song_sound.get(song, {}),
        **{key: value for key, value in files.items() if key in OUTPUT_FIELDS},
    }


def _song_config(
    settings: GuiSettings,
    song: Path,
    styles: Mapping[str, Preset] | None,
    default: EffectConfig,
) -> EffectConfig:
    """song_config with the default (before speakers) already worked out."""
    own = style_for(settings, song, styles or {})
    return song_effect(
        default,
        default_speakers=settings.speakers,
        style=own.config if own else None,
        changes=_own_changes(settings, song),
    )


def has_own_sound(settings: GuiSettings, song: Path) -> bool:
    """True when a song has sound settings of its own (from Customize)."""
    return bool(settings.song_sound.get(song))


def _base_sound(
    settings: GuiSettings, song: Path, styles: Mapping[str, Preset] | None
) -> tuple[EffectConfig, bool]:
    """A song's sound before its own changes: (settings, 'safe for speakers')."""
    own = style_for(settings, song, styles or {})
    default = config_for(settings, with_speakers=False)
    config = song_effect(default, style=own.config if own else None)
    return config, settings.speakers and own is None


def sound_of(
    settings: GuiSettings, song: Path | None, styles: Mapping[str, Preset] | None
) -> tuple[EffectConfig, bool]:
    """What the fine-tuning controls show: (sound settings, 'safe for speakers').

    None means the default style's; a song shows its own, speakers switch apart.
    """
    if song is None:
        return settings.sound, settings.speakers
    base, speakers = _base_sound(settings, song, styles)
    own = dict(settings.song_sound.get(song, {}))
    speakers = bool(own.pop(SPEAKERS, speakers))
    return dataclasses.replace(base, **own), speakers  # type: ignore[arg-type]


def set_sound_settings(
    settings: GuiSettings,
    songs: Sequence[Path],
    styles: Mapping[str, Preset] | None = None,
    **values: object,
) -> int:
    """Give songs these sound settings; values equal to their base are dropped.

    Returns how many of the songs now have sound settings of their own.
    """
    check_keys(values, SOUND_KEYS, "sound")
    for song in songs:
        own = {**settings.song_sound.get(song, {}), **values}
        base, speakers = _base_sound(settings, song, styles)
        # A value that equals what the song would get anyway is no exception
        own = {
            key: value
            for key, value in own.items()
            if value != (speakers if key == SPEAKERS else getattr(base, key))
        }
        if own:
            # Checked now, so a wrong value is refused instead of stored
            song_effect(base, changes=own)
            settings.song_sound[song] = own
        else:
            settings.song_sound.pop(song, None)
    return sum(1 for song in songs if song in settings.song_sound)


def typed_sound(key: str, text: str) -> dict[str, object]:
    """A typed tempo or curve ('bpm_text'…) as sound settings, or raise why not."""
    text = text.strip()
    if key == "bpm_text":
        bpm = typed_number(text, "The tempo (BPM)", 40, 240)
        return {"bpm": bpm, "beat_sync": True} if bpm else {"bpm": None}
    field_name = key.removesuffix("_text")
    try:
        return {field_name: parse_keyframes(text) if text else ()}
    except InputValidationError as exc:
        raise InputValidationError(f"Changes over time: {exc}") from None


def reset_sound_settings(settings: GuiSettings, songs: Sequence[Path]) -> int:
    """Songs lose their own sound settings; returns how many had some."""
    return sum(1 for song in songs if settings.song_sound.pop(song, None) is not None)


def singer_songs(
    settings: GuiSettings,
    songs: Sequence[tuple[Path, Path | None]],
    styles: Mapping[str, Preset] | None = None,
) -> list[Path]:
    """The songs that keep the singer in the middle (they need the add-on)."""
    try:
        default = config_for(settings, with_speakers=False)
    except InputValidationError:
        return []
    found = []
    for song, _folder in songs:
        try:
            if needs_singer(_song_config(settings, song, styles, default)):
                found.append(song)
        except InputValidationError:
            continue
    return found


def file_value(settings: GuiSettings, song: Path | None, key: str) -> object:
    """One file setting of a song (its own, or the default); None song: default."""
    own = settings.song_files.get(song, {}) if song is not None else {}
    if key in own:
        return own[key]
    if key in OUTPUT_FIELDS:
        try:
            if song is not None and own:
                # A song's own format also moves its quality tier and peak limit
                return getattr(song_config(settings, song), key)
            return getattr(config_for(settings), key)
        except InputValidationError:
            return getattr(settings.sound, key)
    return getattr(settings, key)


# The Output step's defaults that are remembered between runs (never per song)
REMEMBERED_OUTPUT = (
    *OUTPUT_FIELDS,
    "keep_cover",
    "tag_title",
    "destination",
    "name_style",
)


def output_defaults(settings: GuiSettings) -> dict[str, object]:
    """The output defaults to remember, as plain values (song overrides never)."""
    saved: dict[str, object] = {
        key: getattr(settings.sound, key) for key in OUTPUT_FIELDS
    }
    for key in REMEMBERED_OUTPUT[len(OUTPUT_FIELDS) :]:
        saved[key] = getattr(settings, key)
    # A custom name only fits the one song it was typed for
    if saved["name_style"] == "custom":
        saved["name_style"] = "8d"
    if settings.loudness_is_custom:
        try:
            level = typed_number(settings.custom_loudness_text, "The loudness", -30, -5)
        except InputValidationError:
            level = None
        if level is not None:
            saved["loudness_target"], saved["match_loudness"] = level, False
    return saved


def _usable_default(settings: GuiSettings, key: str, value: object) -> bool:
    """True when a remembered output default can still be used as it is."""
    if key in OUTPUT_FIELDS:
        try:
            dataclasses.replace(settings.sound, **{key: value}).validate()
        except (InputValidationError, TypeError):
            return False
        return True
    if key == "destination":
        return isinstance(value, str) and destination_problem(value) is None
    if key == "name_style":
        return value in ("8d", "original")
    return isinstance(value, bool)


def apply_output_defaults(
    settings: GuiSettings, saved: Mapping[str, object]
) -> list[str]:
    """Take remembered output defaults; returns the names that couldn't be used."""
    ignored = []
    for key, value in saved.items():
        if key not in REMEMBERED_OUTPUT or not _usable_default(settings, key, value):
            ignored.append(key)
        elif key in OUTPUT_FIELDS:
            settings.sound = dataclasses.replace(settings.sound, **{key: value})
        else:
            setattr(settings, key, value)
    return ignored


def has_own_files(settings: GuiSettings, song: Path) -> bool:
    """True when a song has file settings of its own."""
    return bool(settings.song_files.get(song))


def set_file_settings(
    settings: GuiSettings, songs: Sequence[Path], **values: object
) -> int:
    """Give songs these file settings; values equal to the defaults are dropped.

    Returns how many songs now have file settings of their own.
    """
    unknown = set(values) - set(FILE_KEYS)
    if unknown:
        raise ValueError(f"Not a file setting: {', '.join(sorted(unknown))}")
    for song in songs:
        own = dict(settings.song_files.get(song, {}))
        own.update(values)
        # A value that equals the default is no exception: it follows the default
        own = {k: v for k, v in own.items() if v != file_value(settings, None, k)}
        if own:
            settings.song_files[song] = own
        else:
            settings.song_files.pop(song, None)
    return sum(1 for song in songs if song in settings.song_files)


def reset_file_settings(settings: GuiSettings, songs: Sequence[Path]) -> int:
    """Songs go back to the default file settings; returns how many had their own."""
    return sum(1 for song in songs if settings.song_files.pop(song, None) is not None)


def is_custom(settings: GuiSettings, song: Path) -> bool:
    """True when a song has any setting of its own (style, sound or output)."""
    return (
        song in settings.song_styles
        or bool(settings.song_sound.get(song))
        or bool(settings.song_files.get(song))
    )


def reset_songs(settings: GuiSettings, songs: Sequence[Path]) -> int:
    """'Reset to default': songs lose all their own settings; returns how many had."""
    count = 0
    for song in songs:
        had = is_custom(settings, song)
        settings.song_styles.pop(song, None)
        settings.song_sound.pop(song, None)
        settings.song_files.pop(song, None)
        count += had
    return count


@dataclass
class Changes:
    """What a Customize dialog changed, kept apart until Apply.

    style is a style name (for songs: the default style means 'follow the
    default'); sound holds SOUND_KEYS values; texts holds typed tempo and
    curves ('bpm_text'…); files holds FILE_KEYS values. Only what was really
    touched is listed, so a bulk edit never overwrites other settings.
    """

    style: str | None = None
    sound: dict[str, object] = field(default_factory=dict)
    texts: dict[str, str] = field(default_factory=dict)
    files: dict[str, object] = field(default_factory=dict)

    def __bool__(self) -> bool:
        """True when anything was changed."""
        return bool(self.style or self.sound or self.texts or self.files)


def customize(
    settings: GuiSettings,
    songs: Sequence[Path],
    styles: Mapping[str, Preset],
    changes: Changes,
) -> None:
    """Apply a Customize dialog's changes: to these songs, or (no songs) the defaults.

    Raises InputValidationError, changing nothing, when a value can't be used.
    """
    trial = draft(settings, songs, styles, changes)
    # Checked on a copy first, so a bad value leaves the real settings untouched
    config_for(trial)
    options_for(trial)
    for song in songs:
        song_config(trial, song, styles)
        song_options(trial, song)
    for name in dataclasses.fields(settings):
        setattr(settings, name.name, getattr(trial, name.name))


def _customize(
    settings: GuiSettings,
    songs: Sequence[Path],
    styles: Mapping[str, Preset],
    changes: Changes,
) -> None:
    """customize() without the safety copy."""
    if changes.style is not None and changes.style not in styles:
        raise InputValidationError(f"There is no style called '{changes.style}'")
    if not songs:
        _customize_default(settings, styles, changes)
        return
    if changes.style is not None:
        for song in songs:
            if changes.style == settings.style:
                settings.song_styles.pop(song, None)
            else:
                settings.song_styles[song] = changes.style
    sound = dict(changes.sound)
    for key, text in changes.texts.items():
        sound.update(typed_sound(key, text))
    if sound:
        set_sound_settings(settings, songs, styles, **sound)
    if changes.files:
        set_file_settings(settings, songs, **changes.files)


def _customize_default(
    settings: GuiSettings, styles: Mapping[str, Preset], changes: Changes
) -> None:
    """The default for every song that isn't customized takes the changes."""
    if changes.style is not None and changes.style != settings.style:
        settings.apply_style(styles[changes.style])
        settings.speakers = False
    sound = dict(changes.sound)
    if SPEAKERS in sound:
        settings.speakers = bool(sound.pop(SPEAKERS))
    output = {k: v for k, v in changes.files.items() if k in OUTPUT_FIELDS}
    if sound or output:
        settings.change(**sound, **output)
    for key, value in changes.files.items():
        if key not in OUTPUT_FIELDS:
            setattr(settings, key, value)
    for key, text in changes.texts.items():
        setattr(settings, key, text)


def draft(
    settings: GuiSettings,
    songs: Sequence[Path],
    styles: Mapping[str, Preset],
    changes: Changes,
) -> GuiSettings:
    """A copy of the settings with the changes in, for showing and previewing them."""
    copy = dataclasses.replace(
        settings,
        song_styles=dict(settings.song_styles),
        song_sound={k: dict(v) for k, v in settings.song_sound.items()},
        song_files={k: dict(v) for k, v in settings.song_files.items()},
    )
    _customize(copy, songs, styles, changes)
    return copy


def song_options(settings: GuiSettings, song: Path) -> ConvertOptions | None:
    """The song's own file treatment (art, title, part), or None for the defaults."""
    own = dict(settings.song_files.get(song, {}))
    if not any(key in own for key in FILE_OPTIONS):
        return None
    # A song's own start or end pairs with the default's other half
    if "trim_start" in own or "trim_end" in own:
        own.setdefault("trim_start", settings.trim_start)
        own.setdefault("trim_end", settings.trim_end)
    return song_convert_options(options_for(settings), own)


def items_for(
    settings: GuiSettings,
    songs: Sequence[tuple[Path, Path | None]],
    styles: Mapping[str, Preset] | None = None,
) -> list[BatchItem]:
    """(song, folder it was added from) pairs -> songs, output paths and settings.

    Songs that would land on the same file name get ' (2)', ' (3)'… added.
    """
    return unique_outputs(_plain_items(settings, songs, styles))


def _plain_items(
    settings: GuiSettings,
    songs: Sequence[tuple[Path, Path | None]],
    styles: Mapping[str, Preset] | None = None,
) -> list[BatchItem]:
    """items_for, before clashing names are made unique."""
    shared = config_for(settings)
    default = config_for(settings, with_speakers=False)
    output_dir = destination_for(settings)

    def own(song: Path) -> EffectConfig | None:
        """A song's own settings (style, sound or file), or None for the shared."""
        if song not in settings.song_styles and not _own_changes(settings, song):
            return None
        return _song_config(settings, song, styles, default)

    def extension(song: Path) -> str:
        """The ending the song's file gets, from its (own) file type."""
        config = own(song)
        return (config or shared).extension

    if (
        settings.name_style == "custom"
        and len(songs) == 1
        and settings.originals == "keep"
    ):
        song = songs[0][0]
        name = settings.custom_name.strip()
        stem = (
            name[: -len(Path(name).suffix)]
            if Path(name).suffix.lower() in FORMAT_EXTENSIONS.values()
            else name
        )
        folder = output_dir or song.parent
        return [
            BatchItem(
                song,
                folder / f"{stem}{extension(song)}",
                own(song),
                song_options(settings, song),
            )
        ]
    return [
        BatchItem(
            song,
            default_output_for(
                song,
                extension(song),
                output_dir=output_dir,
                name_style=name_style_for(settings),
                relative_to=folder,
            ),
            own(song),
            song_options(settings, song),
        )
        for song, folder in songs
    ]


def _same_key(path: Path) -> str:
    """How Windows compares file names: letter case doesn't matter."""
    return os.path.normcase(str(path))


def unique_outputs(items: list[BatchItem]) -> list[BatchItem]:
    """Songs that would be saved under one name get ' (2)', ' (3)'… instead.

    Two songs called 'Intro' from different folders, saved into one folder,
    would otherwise overwrite each other or fail half-way.
    """
    taken: set[str] = set()
    result = []
    for item in items:
        output, number = item.output, 2
        while _same_key(output) in taken:
            output = item.output.with_name(
                f"{item.output.stem} ({number}){item.output.suffix}"
            )
            number += 1
        taken.add(_same_key(output))
        result.append(
            item if output == item.output else dataclasses.replace(item, output=output)
        )
    return result


def name_clashes(
    settings: GuiSettings, songs: Sequence[tuple[Path, Path | None]]
) -> int:
    """How many songs share a new file name with an earlier song."""
    try:
        plain = _plain_items(settings, songs)
    except InputValidationError:
        return 0
    return len(plain) - len({_same_key(item.output) for item in plain})


# Windows' classic limit for a whole path; longer ones confuse many programs
MAX_PATH = 259


def long_paths(items: Sequence[BatchItem]) -> list[BatchItem]:
    """New files whose full path is longer than older Windows programs can open."""
    return [item for item in items if len(str(item.output)) > MAX_PATH]


# One plain answer per way a folder can be unusable
def destination_problem(  # pylint: disable=too-many-return-statements
    text: str,
) -> str | None:
    """Why the chosen 'Save in' folder can't be used, in plain words, or None.

    A folder that doesn't exist yet is fine (it is made), as long as the drive
    is there and the nearest existing folder can be written to.
    """
    if not text.strip():
        return None
    folder = Path(text.strip()).expanduser()
    if not folder.is_absolute():
        return (
            "Choose a complete folder, such as C:\\Music\\8D. Browse picks one for you."
        )
    if folder.anchor and not Path(folder.anchor).exists():
        return (
            f"The drive {folder.anchor} isn't available. Plug it in, or choose "
            "another folder."
        )
    if folder.exists() and not folder.is_dir():
        return "The 'Save in' place is a file, not a folder."
    existing = folder
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    if existing.exists() and not existing.is_dir():
        return f"{existing} is a file, so no folder can be made inside it."
    if existing.exists() and not os.access(existing, os.W_OK):
        return (
            f"Audio8D isn't allowed to save in {existing}. Choose another folder, "
            "such as your Music folder."
        )
    return None


def can_write(folder: Path) -> str | None:
    """Really try to write in a folder (or its nearest existing parent).

    os.access can't see every Windows permission, so right before converting a
    tiny test file is made and removed. Returns a plain-word problem, or None.
    """
    existing = folder
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    try:
        with tempfile.NamedTemporaryFile(dir=existing, prefix=".audio8d-check-"):
            pass
    except OSError:
        return (
            f"Audio8D isn't allowed to save in {existing}. Choose another folder, "
            "such as your Music folder."
        )
    return None


_BAD_NAME = re.compile(r'[<>:"/\\|?*]')


def name_problem(name: str) -> str | None:
    """Why a typed file name can't be used on Windows, or None."""
    if _BAD_NAME.search(name):
        return "File names can't contain  < > : \" / \\ | ? *"
    return None


def _missing_styles(
    settings: GuiSettings,
    songs: Sequence[tuple[Path, Path | None]],
    styles: Mapping[str, Preset] | None,
) -> list[tuple[str, str]]:
    """Songs whose own style no longer exists (deleted, or its file is broken)."""
    known = styles if styles is not None else PRESETS
    return [
        (
            "sound",
            f"'{song.stem}' uses the style '{name}', which no longer exists. "
            "Choose another style for it.",
        )
        for song, _folder in songs
        if (name := settings.song_styles.get(song)) and name not in known
    ]


def problems(
    settings: GuiSettings,
    songs: Sequence[tuple[Path, Path | None]],
    styles: Mapping[str, Preset] | None = None,
) -> list[tuple[str, str]]:
    """(page, plain-word reason) for everything that stops a conversion starting."""
    found: list[tuple[str, str]] = []
    if not songs:
        found.append(("songs", "Add at least one song or folder first."))
    found += _missing_styles(settings, songs, styles)
    try:
        config_for(settings)
    except InputValidationError as exc:
        page = (
            "output"
            if "loudness" in str(exc).lower() or "bitrate" in str(exc)
            else "sound"
        )
        found.append((page, gui_words(str(exc))))
    try:
        trim_for(settings)
    except InputValidationError as exc:
        found.append(("output", f"Trim: {exc}. Write times like 90 or 1:30."))
    if (
        settings.destination.strip() == ""
        and settings.name_style == "original"
        and settings.originals == "keep"
    ):
        found.append(
            (
                "output",
                "Keeping the original name next to the original would overwrite it. "
                "Choose a 'Save in' folder, or pick 'Replace them'.",
            )
        )
    where = destination_problem(settings.destination)
    if where:
        found.append(("output", where))
    if settings.name_style == "custom":
        name = settings.custom_name.strip()
        if len(songs) != 1:
            found.append(
                ("output", "A custom file name only works with exactly one song.")
            )
        elif not name:
            found.append(
                ("output", "Type the custom file name, or choose another naming.")
            )
        elif name_problem(name):
            found.append(("output", name_problem(name) or ""))
    found += _song_file_problems(settings, songs, styles)
    if not 1 <= settings.jobs <= MAX_JOBS:
        found.append(("output", f"Songs at once must be between 1 and {MAX_JOBS}."))
    if settings.originals not in ORIGINAL_CHOICES:
        found.append(("output", "Choose what happens to the originals."))
    return found


def _song_file_problems(
    settings: GuiSettings,
    songs: Sequence[tuple[Path, Path | None]],
    styles: Mapping[str, Preset] | None,
) -> list[tuple[str, str]]:
    """Songs whose own sound or file settings can't be used, each named."""
    found: list[tuple[str, str]] = []
    for song, _folder in songs:
        if not settings.song_files.get(song) and not settings.song_sound.get(song):
            continue
        try:
            song_config(settings, song, styles)
            song_options(settings, song)
        except InputValidationError as exc:
            page = "output" if settings.song_files.get(song) else "sound"
            found.append(
                (page, f"'{song.stem}' has settings that can't be used: {exc}.")
            )
    return found


def warnings(settings: GuiSettings, singers: int = 0) -> list[str]:
    """Plain-word heads-ups (the same advice the terminal gives), in window words.

    singers is how many songs keep the singer in the middle.
    """
    try:
        config = config_for(settings)
    except InputValidationError:
        return []
    notes = [gui_words(note) for note in display.advice(config)]
    if settings.originals != "keep":
        notes.append(
            "The original songs will be moved to the Recycle Bin after their 8D "
            "versions are saved (or renamed '<song> (original)' where there is none)."
        )
    if settings.overwrite:
        notes.append("8D files that already exist will be replaced.")
    if singers:
        notes.append(
            f"Keeping the singer in the middle ({singers} "
            f"song{'s' if singers != 1 else ''}) takes a minute or two per song."
        )
    return notes
