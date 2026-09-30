# Developed by ::> Gehan Fernando
"""Checks the terminal panel, the best-value markers and the heads-up warnings."""

import io
from pathlib import Path

from src import PRESETS, AudioStreamInfo, ConversionError, EffectConfig, display
from src.analysis import QualityReport
from src.batch import BatchItem, BatchOutcome, BatchReport
from src.core.presets import legacy_config
from src.ffmpeg import LoudnessMeasurement
from src.pipeline import ConversionResult, LoudnessPlan


# Old consoles can't draw box lines, so the panel must fall back to plain ASCII
class _AsciiConsole(io.StringIO):
    """A fake old-style console that can only show plain ASCII."""

    encoding = "ascii"


def test_plain_ascii_consoles_get_a_safe_fallback() -> None:
    stream = _AsciiConsole()
    display.show_presets(display.Painter(stream), "9.9.9")

    shown = stream.getvalue()
    shown.encode("ascii")
    assert "+---" in shown
    assert "\033" not in shown


def test_colour_is_off_when_not_a_terminal() -> None:
    assert display.Painter(io.StringIO()).color is False


def test_settings_are_described_in_plain_words() -> None:
    assert display.describe_movement(0) == "off, stays in the middle"
    # The same words as the Movement and Space choices (--movement, --space)
    assert display.describe_movement(0.65) == "gentle"
    assert display.describe_movement(0.85) == "balanced"
    assert display.describe_movement(0.95) == "strong"
    assert display.describe_room(0) == "no room sound at all"
    assert display.describe_room(0.1) == "dry"
    assert display.describe_room(0.3) == "natural"
    assert display.describe_room(0.45) == "spacious"
    assert display.describe_quality(0).startswith("V0  (~245 kbps, best")
    assert display.describe_ceiling(0.89) == "0.89  (-1.0 dBFS)"
    assert "Spotify" in display.describe_loudness(-14)
    assert "Apple" in display.describe_loudness(-16)
    assert display.describe_loudness(None).startswith("off")


def test_settings_panel_lists_every_knob() -> None:
    stream = io.StringIO()
    display.show_settings(
        display.Painter(stream),
        version="1.0.0",
        song_in=Path("in.mp3"),
        song_out=Path("out.mp3"),
        preset="studio",
        config=PRESETS["studio"].config,
    )
    shown = stream.getvalue()

    labels = (
        "Song in",
        "Song out",
        "Style",
        "Speed",
        "Movement",
        "Space",
        "Peak limit",
        "Quality",
    )
    for label in (*labels, "Loudness"):
        assert label in shown
    assert "Gehan Fernando" in shown


def test_custom_settings_are_labelled_as_such() -> None:
    stream = io.StringIO()
    display.show_settings(
        display.Painter(stream),
        version="1.0.0",
        song_in=Path("in.mp3"),
        song_out=Path("out.mp3"),
        preset=None,
        config=EffectConfig(intensity=0.5),
    )

    assert "your own settings" in stream.getvalue()


def _panel(preset: str | None, config: EffectConfig) -> str:
    """Everything the settings panel prints for these settings, as plain text."""
    stream = io.StringIO()
    display.show_settings(
        display.Painter(stream),
        version="1.0.0",
        song_in=Path("in.mp3"),
        song_out=Path("out.mp3"),
        preset=preset,
        config=config,
    )
    return stream.getvalue()


def test_studio_values_are_all_marked_best() -> None:
    shown = _panel("studio", PRESETS["studio"].config)

    # Style, sound, spin, movement, bass, room, roof, quality and loudness
    assert shown.count("(best)") == 9
    assert "Heads-up" not in shown


def test_other_values_show_what_the_best_would_be() -> None:
    shown = _panel("classic", EffectConfig())

    assert "best: 0.80" in shown
    assert "best: 0" in shown
    assert "best: match music apps" in shown


def test_risky_values_get_a_heads_up_with_a_fix() -> None:
    notes = display.advice(
        EffectConfig(
            rotation_seconds=3,
            intensity=1.0,
            ambience=0.9,
            limiter_ceiling=1.0,
            quality=9,
            loudness_target=-6,
            engine="pan",
        )
    )
    joined = " ".join(notes)

    assert len(notes) == 6
    for words in (
        "dizzy",
        "tire your ears",
        "blurry",
        "swishy",
        "crackle",
        "very loud",
    ):
        assert words in joined


def test_best_settings_need_no_heads_up() -> None:
    assert not display.advice(PRESETS["studio"].config)


def test_style_menu_puts_the_best_first() -> None:
    stream = io.StringIO()
    names = display.show_style_menu(display.Painter(stream))

    assert names[0] == "studio"
    assert "BEST" in stream.getvalue().splitlines()[0]


_MP3 = AudioStreamInfo("mp3", 2, 48000, 292.4, 320000)
_HI_RES_FLAC = AudioStreamInfo("flac", 2, 96000, 200.0, 2_900_000)


def test_sources_are_described_in_plain_words() -> None:
    assert (
        display.describe_source(_MP3)
        == "MP3, 320 kbps, 48 kHz, stereo, 4:52  (already compressed)"
    )
    assert (
        display.describe_source(_HI_RES_FLAC)
        == "FLAC, 96 kHz, stereo, 3:20  (lossless, perfect source)"
    )


def test_lossy_sources_get_honest_advice() -> None:
    notes = " ".join(display.source_notes(_MP3, EffectConfig()))

    assert "Already compressed" in notes
    assert "--bitrate 320" in notes


def test_hi_res_sources_are_explained() -> None:
    notes = " ".join(display.source_notes(_HI_RES_FLAC, PRESETS["studio"].config))

    assert "Perfect source" in notes
    assert "96 kHz file is carefully resampled" in notes


def _plan(gain: float, exact: bool) -> LoudnessPlan:
    """A loudness plan for the Annie Lennox song measured during testing."""
    return LoudnessPlan(LoudnessMeasurement(-27.4, -11.5, 8.7), gain, -14.0, exact)


def test_loudness_report_explains_a_held_back_song() -> None:
    stream = io.StringIO()
    display.show_loudness(display.Painter(stream), _plan(9.99, exact=False))
    shown = stream.getvalue()

    assert "measured -27.4 LUFS, turned up 10.0 dB  ->  about -17.4 LUFS" in shown
    assert "not squashed" in shown


def test_loudness_report_for_exact_mode() -> None:
    stream = io.StringIO()
    display.show_loudness(display.Painter(stream), _plan(13.4, exact=True))

    assert "about -14.0 LUFS" in stream.getvalue()
    assert "shaved lightly" in stream.getvalue()


def test_panel_shows_the_source_and_good_to_know_facts() -> None:
    stream = io.StringIO()
    display.show_settings(
        display.Painter(stream),
        version="1.0.0",
        song_in=Path("in.mp3"),
        song_out=Path("out.mp3"),
        preset="studio",
        config=PRESETS["studio"].config,
        source=_MP3,
    )
    shown = stream.getvalue()

    assert "Source" in shown and "already compressed" in shown
    assert "Good to know" in shown
    assert "320 kbps CBR" in shown


def test_new_rows_describe_the_3d_sound() -> None:
    shown = _panel(
        None,
        EffectConfig(path="figure8", elevation=0.5, bass_hz=0, output_format="flac"),
    )

    assert "3D, loops around each ear, clockwise" in shown
    assert "moves with everything else" in shown
    assert "rises overhead" in shown
    assert "FLAC 24-bit" in shown
    assert "--bass 120" in shown


def test_lossless_output_is_marked_best_quality() -> None:
    quality_row = _panel(None, EffectConfig(output_format="wav")).split("Quality")[1]

    assert "(best)" in quality_row.splitlines()[0]


def test_progress_bar_prints_stage_lines_when_not_a_terminal() -> None:
    stream = io.StringIO()
    meter = display.ProgressBar(display.Painter(stream))
    for share in (0.0, 0.5, 1.0):
        meter.update("Making your 8D song", share)
    meter.finish()

    assert stream.getvalue().count("Making your 8D song") == 1


def test_quality_report_flags_problems() -> None:
    stream = io.StringIO()
    report = QualityReport(
        integrated_lufs=-14.0, true_peak_db=0.0, range_lu=6.0, correlation=-0.2
    )
    display.show_quality(display.Painter(stream), report)
    shown = stream.getvalue()

    assert "weak in mono" in shown
    assert "--speakers" in shown
    assert "--limiter-ceiling" in shown


def test_batch_summary_counts_songs() -> None:
    stream = io.StringIO()
    painter = display.Painter(stream)
    item = BatchItem(Path("a.mp3"), Path("a (8D).mp3"))
    done = ConversionResult(
        _MP3, Path("a (8D).mp3"), EffectConfig(), original_removed_to="Recycle Bin"
    )
    report = BatchReport(
        outcomes=[
            BatchOutcome(item, done),
            BatchOutcome(item, error=ConversionError("boom")),
        ],
        seconds=12.0,
    )
    display.show_batch_summary(painter, report)
    shown = stream.getvalue()

    assert "Done: 1 created, 1 failed" in shown
    assert "1 original moved to the Recycle Bin." in shown
    assert "boom" in display.batch_line(painter, 2, 2, report.outcomes[1])


def test_every_style_can_be_shown_and_advised() -> None:
    for name, preset in PRESETS.items():
        shown = _panel(name, preset.config)
        assert "Loudness" in shown
        display.advice(preset.config)
    assert "Keep original loudness" in _panel("hifi", legacy_config("hifi"))
    assert "Match music apps" in _panel("studio", PRESETS["studio"].config)
