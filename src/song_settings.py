# Developed by ::> Gehan Fernando
"""How one song's own settings combine with the settings every other song gets.

A song starts from the default style (as fine-tuned), or from a style of its
own. On top of that it may have changes of its own: to its sound (fine-tuning,
'Keep the singer in the middle', 'Safe for speakers too') and to its file
(type, quality, loudness, album art, title, which part to keep). The window's
song settings and the command line's --per-song file both go through here, so
a song is made exactly the same way whichever one you use.
"""

import dataclasses
from collections.abc import Iterable, Mapping

from .core.errors import InputValidationError
from .core.parsing import parse_time
from .core.presets import with_format
from .core.settings import OUTPUT_FIELDS, EffectConfig, speaker_safe
from .core.types import Trim
from .pipeline import ConvertOptions

# What a file may have of its own besides OUTPUT_FIELDS: its art, title and part
FILE_OPTIONS = ("keep_cover", "tag_title", "trim_start", "trim_end")
FILE_KEYS = OUTPUT_FIELDS + FILE_OPTIONS
# 'speakers' is a switch rather than a setting: it turns speaker_safe() on
SPEAKERS = "speakers"
SOUND_KEYS = (
    *(
        item.name
        for item in dataclasses.fields(EffectConfig)
        if item.name not in OUTPUT_FIELDS
    ),
    SPEAKERS,
)


def with_output(sound: EffectConfig, output: EffectConfig) -> EffectConfig:
    """A style's sound with the file and loudness settings of another config."""
    return dataclasses.replace(
        sound, **{name: getattr(output, name) for name in OUTPUT_FIELDS}
    )


def check_keys(values: Iterable[str], allowed: Iterable[str], what: str) -> None:
    """Refuse a setting name that doesn't belong here (a programming slip)."""
    unknown = set(values) - set(allowed)
    if unknown:
        raise ValueError(f"Not a {what} setting: {', '.join(sorted(unknown))}")


def song_effect(
    default: EffectConfig,
    *,
    default_speakers: bool = False,
    style: EffectConfig | None = None,
    changes: Mapping[str, object] | None = None,
) -> EffectConfig:
    """The exact EffectConfig one song is made with.

    default is the default style with its fine-tuning and file settings, before
    'Safe for speakers too'. A song with a style of its own gets that style's
    sound as saved, with the default file settings. changes are the song's own
    sound and file settings (SOUND_KEYS and OUTPUT_FIELDS names).
    """
    own = dict(changes or {})
    check_keys(own, (*SOUND_KEYS, *FILE_KEYS), "song")
    config = with_output(style, default) if style is not None else default
    sound = {k: v for k, v in own.items() if k in SOUND_KEYS and k != SPEAKERS}
    if sound:
        config = dataclasses.replace(config, **sound)  # type: ignore[arg-type]
    # Songs with a style of their own follow it exactly, speaker setting included
    speakers = own.get(SPEAKERS, default_speakers and style is None)
    if speakers:
        config = speaker_safe(config)
    files = {k: v for k, v in own.items() if k in OUTPUT_FIELDS}
    if "output_format" in files:
        # A new format keeps its quality tier and gets a peak limit that fits it
        config = with_format(config, str(files.pop("output_format")))
    if files:
        config = dataclasses.replace(config, **files)  # type: ignore[arg-type]
    config.validate()
    return config


def parse_trim(start: object, end: object) -> Trim | None:
    """A start and end (text like '1:30', seconds, or None) -> the part to keep."""

    def seconds(value: object) -> float | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        return parse_time(str(value))

    first, last = seconds(start), seconds(end)
    if first is None and last is None:
        return None
    if first is not None and last is not None and last <= first:
        raise InputValidationError("The chosen start and end leave no sound to convert")
    return Trim(first, last)


def song_convert_options(
    default: ConvertOptions, changes: Mapping[str, object] | None
) -> ConvertOptions | None:
    """The song's own file treatment, or None when it uses the default one."""
    own = {k: v for k, v in (changes or {}).items() if k in FILE_OPTIONS}
    if not own:
        return None
    trim = default.trim
    if "trim_start" in own or "trim_end" in own:
        start = own.get("trim_start", default.trim.start if default.trim else None)
        end = own.get("trim_end", default.trim.end if default.trim else None)
        trim = parse_trim(start, end)
    return dataclasses.replace(
        default,
        keep_cover=bool(own.get("keep_cover", default.keep_cover)),
        tag_title=bool(own.get("tag_title", default.tag_title)),
        trim=trim,
    )


def needs_singer(config: EffectConfig) -> bool:
    """True when this song keeps the singer in the middle (the add-on is needed)."""
    return config.vocals == "center"


def singer_songs(configs: Iterable[tuple[str, EffectConfig]]) -> list[str]:
    """The names of the songs that need the singer add-on."""
    return [name for name, config in configs if needs_singer(config)]
