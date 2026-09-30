# Developed by ::> Gehan Fernando
"""Checks the loudness report never claims a level the file doesn't have."""

import io
from pathlib import Path

from src import AudioStreamInfo, EffectConfig, display
from src.analysis import QualityReport
from src.ffmpeg import LoudnessMeasurement
from src.pipeline import ConversionResult, LoudnessPlan

# A hot master measured during testing: -5.4 LUFS with peaks at full scale
_HOT = LoudnessMeasurement(-5.4, 0.0, 3.0)


def _shown(plan: LoudnessPlan, report: QualityReport | None) -> str:
    stream = io.StringIO()
    display.show_loudness(display.Painter(stream), plan, report)
    return stream.getvalue()


def test_exact_mode_reports_the_checked_level_not_the_target() -> None:
    plan = LoudnessPlan(_HOT, -3.6, -9.0, exact=True)
    # Opus measured -11.1 LUFS after the limiter, though the plan aimed at -9
    shown = _shown(plan, QualityReport(-11.1, -1.6, 3.0, 0.9))

    assert "->  -11.1 LUFS (checked)" in shown
    assert "-9.0 LUFS" not in shown
    assert "2.1 LU under -9" in shown
    assert "shaved lightly" not in shown


def test_a_level_within_half_a_lu_counts_as_reached() -> None:
    plan = LoudnessPlan(_HOT, -3.6, -9.0, exact=True)
    shown = _shown(plan, QualityReport(-9.3, -1.6, 3.0, 0.9))

    assert "-9.3 LUFS (checked)" in shown
    assert "shaved lightly to reach it" in shown
    assert "under" not in shown


def test_without_the_check_the_report_only_states_the_aim() -> None:
    shown = _shown(LoudnessPlan(_HOT, -3.6, -9.0, exact=True), None)

    assert "aims for -9.0 LUFS" in shown
    assert "(checked)" not in shown
    assert "reach it" not in shown


def test_limiting_that_misses_the_target_is_said_in_normal_mode_too() -> None:
    plan = LoudnessPlan(LoudnessMeasurement(-16.2, -1.1, 6.0), 2.2, -14.0, False)
    shown = _shown(plan, QualityReport(-15.2, -2.4, 6.0, 0.9))

    assert "-15.2 LUFS (checked)" in shown
    assert "1.2 LU under -14" in shown


def test_silence_is_not_called_held_back() -> None:
    plan = LoudnessPlan(LoudnessMeasurement(-70.0, -120.0, 0.0), 0.0, -14.0, False)

    assert plan.silent and not plan.held_back
    shown = _shown(plan, QualityReport(-70.0, -120.0, 0.0, 1.0))
    assert "Kept below" not in shown and "under" not in shown


def test_show_result_passes_the_check_to_the_loudness_line(tmp_path: Path) -> None:
    song = tmp_path / "song (8D).opus"
    song.write_bytes(b"x" * 2048)
    result = ConversionResult(
        source=AudioStreamInfo("flac", 2, 44100, 30.0),
        output=song,
        config=EffectConfig(loudness_target=-9.0, exact_loudness=True),
        loudness=LoudnessPlan(_HOT, -3.6, -9.0, exact=True),
        quality=QualityReport(-11.1, -1.6, 3.0, 0.9),
    )
    stream = io.StringIO()
    display.show_result(display.Painter(stream), result, 2.0)

    assert "->  -11.1 LUFS (checked)" in stream.getvalue()
