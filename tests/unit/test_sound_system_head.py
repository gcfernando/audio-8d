# Developed by ::> Gehan Fernando
"""The 3D engine's ear gap stays true to a real head at every output rate."""

import pytest

from src.core.settings import EffectConfig
from src.effects import GraphInputs, Source, build_graph
from src.effects.graph import timing_rate
from src.effects.head import MAX_ITD_SECONDS, widest_itd

# Every rate the 3D mix can be made at, including 32 and 64 kHz sources kept as-is
_RATES = (32000, 44100, 48000, 64000, 88200, 96000, 176400, 192000)


@pytest.mark.parametrize("sample_rate", _RATES)
def test_the_widest_ear_gap_is_close_to_a_real_heads(sample_rate: int) -> None:
    low = timing_rate(sample_rate)

    # 32 kHz once ran the taps at 8 kHz, which gave a 0.875 ms gap (0.66 ms is real)
    assert widest_itd(low) <= 0.7e-3
    assert widest_itd(low) == pytest.approx(MAX_ITD_SECONDS, rel=0.15)
    assert sample_rate % low == 0


def test_common_rates_still_run_the_timing_band_at_a_quarter() -> None:
    assert timing_rate(44100) == 11025
    assert timing_rate(48000) == 12000
    assert timing_rate(96000) == 24000


def test_a_32khz_song_keeps_its_timing_band_at_the_full_rate() -> None:
    inputs = GraphInputs((Source(0, (1, 2)),))
    graph = build_graph(
        EffectConfig(ambience=0), inputs, sample_rate=32000, source_rate=32000
    )

    assert "aresample=8000" not in graph
    # Three samples between taps at 32 kHz: the last tap lands at 21 samples
    assert "adelay=delays=21S" in graph
