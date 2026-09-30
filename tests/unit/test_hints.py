# Developed by ::> Gehan Fernando
"""Checks that every error and typing mistake comes with a plain fix."""

import pytest

from src import (
    Audio8DError,
    ConversionError,
    DependencyError,
    EffectConfig,
    InputValidationError,
    hints,
)


# Each known error, and a word its plain-English fix must contain
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (DependencyError("Missing required executable(s): ffmpeg"), "ZIP again"),
        (
            ConversionError(
                "FFmpeg conversion failed with exit code 8: Error applying option "
                "'irnorm' to filter 'afir': Option not found"
            ),
            "older than version 7",
        ),
        (
            DependencyError("Command failed with exit code 1: boom"),
            "FFmpeg would not run",
        ),
        (
            InputValidationError(
                "Input file does not exist or cannot be accessed: a.mp3"
            ),
            "drag",
        ),
        (
            InputValidationError("Command failed with exit code 1: bad data"),
            "doesn't look like music",
        ),
        (InputValidationError("Output already exists: a.mp3"), "--overwrite"),
        (InputValidationError("Output file must use the .mp3 extension"), ".mp3"),
        (ConversionError("Conversion cancelled by user"), "Nothing was left behind"),
        (ConversionError("I/O error during conversion: disk full"), "free space"),
    ],
)
def test_every_common_error_has_a_plain_fix(error: Audio8DError, expected: str) -> None:
    fix = hints.fix_for(error)

    assert fix is not None and expected in fix


@pytest.mark.parametrize(
    "bad",
    [
        EffectConfig(rotation_seconds=1),
        EffectConfig(intensity=2),
        EffectConfig(ambience=-1),
        EffectConfig(limiter_ceiling=2),
        EffectConfig(quality=12),
        EffectConfig(loudness_target=0),
        EffectConfig(bitrate=999),
    ],
)
def test_every_out_of_range_knob_points_to_the_best_value(bad: EffectConfig) -> None:
    with pytest.raises(InputValidationError) as error_info:
        bad.validate()

    fix = hints.fix_for(error_info.value)
    assert fix is not None and "(best)" in fix


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("the following arguments are required: input", "you forgot the song"),
        ("argument --quality: invalid choice: '11'", "0 to 9"),
        ("argument --preset: invalid choice: 'x'", "studio"),
        ("argument --bitrate: invalid choice: 999", "320"),
        ("argument --loudness: use a number like -14, 'match' or 'off'", "match"),
        ("argument --jobs: use a whole number from 1 to 16", "1 to 16"),
        ("unrecognized arguments: Song.mp3", "quotes"),
        ("something new", "--help"),
    ],
)
def test_typing_mistakes_have_a_plain_fix(message: str, expected: str) -> None:
    assert expected in hints.usage_fix_for(message)


def test_a_locked_folder_gets_a_plain_fix() -> None:
    error = ConversionError(
        "FFmpeg conversion failed with exit code 1: Error opening output files: "
        "Permission denied"
    )

    fix = hints.fix_for(error)
    assert fix is not None
    assert "isn't allowed to write there" in fix


@pytest.mark.parametrize(
    ("log", "shown"),
    [
        (
            "FFmpeg conversion failed with exit code -13: [out#0/mp3 @ 00F1] Error "
            r"opening output C:\Music\.a.partial.mp3."
            "\n"
            "Error opening output files: Permission denied",
            "FFmpeg stopped: Error opening output files: Permission denied",
        ),
        (
            "Command failed with exit code 1: [mp3 @ 0x1] Failed to find two "
            "consecutive MPEG audio frames.\n"
            r"C:\Music\notes.mp3: Invalid data found when processing input",
            "FFmpeg stopped: Invalid data found when processing input",
        ),
        (r"Input file is empty: C:\a.mp3", r"Input file is empty: C:\a.mp3"),
    ],
)
def test_ffmpeg_logs_are_shortened_to_their_reason(log: str, shown: str) -> None:
    assert hints.short_message(ConversionError(log)) == shown


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ConversionError("FFmpeg conversion failed with exit code 1: boom"),
         "FFmpeg couldn't process this song."),
        (DependencyError("Missing required executable(s): ffmpeg"),
         "A program Audio8D needs isn't working."),
        (RuntimeError("a surprise"), "Something unexpected went wrong."),
    ],
)  # fmt: skip
def test_people_see_a_plain_headline_first(error: BaseException, expected: str) -> None:
    shown = hints.headline(error)

    assert shown.startswith(expected)
    assert "exit code" not in shown and "Traceback" not in shown
