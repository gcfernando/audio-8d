# Developed by ::> Gehan Fernando
"""Checks the 3D engine: paths, the head model, the gain streams, room and graph."""

import math
import struct
from pathlib import Path

import pytest

from src import EffectConfig, InputValidationError
from src.effects import (
    GraphInputs,
    Source,
    build_graph,
    build_measure_graph,
    loudness_gain_db,
    mp3_sample_rate_for,
    output_sample_rate,
    write_controls,
    write_room,
)
from src.effects.control import CONTROL_RATE, control_streams
from src.effects.head import (
    DELAY_TAPS,
    MAX_ITD_SECONDS,
    binaural_gains,
    head_shadow,
    pan_gains,
    tap_spacing_samples,
)
from src.effects.levels import PEAK_ALLOWANCE_DB
from src.effects.motion import (
    Position,
    fade_factor,
    interpolate,
    path_azimuth,
    trajectory,
)
from src.effects.reverb import impulse_response, room_for

_ONE = GraphInputs(sources=(Source(0, (1, 2)),), room_input=3)


# ------------------------------------------------------------------ motion


def test_circle_goes_all_the_way_round_in_one_rotation() -> None:
    config = EffectConfig(rotation_seconds=4.0, fade_seconds=0)
    points = list(trajectory(config, rate=100, duration=4.0))

    assert points[0].azimuth == pytest.approx(0.0)
    assert points[100].azimuth == pytest.approx(math.pi / 2, abs=1e-6)
    assert points[400].azimuth == pytest.approx(2 * math.pi, abs=1e-6)


def test_counterclockwise_turns_the_other_way() -> None:
    config = EffectConfig(rotation_seconds=4.0, direction="counterclockwise")
    point = list(trajectory(config, rate=100, duration=1.0))[100]

    assert point.azimuth == pytest.approx(-math.pi / 2, abs=1e-6)


def test_arc_stays_in_front_and_figure8_reaches_behind() -> None:
    arc = [path_azimuth("arc", phase / 10) for phase in range(63)]
    figure8 = [path_azimuth("figure8", phase / 10) for phase in range(63)]

    assert max(abs(angle) for angle in arc) <= math.pi / 2 + 1e-9
    assert max(figure8) == pytest.approx(math.pi, abs=0.01)
    assert min(figure8) == pytest.approx(-math.pi, abs=0.01)


def test_speed_curve_changes_how_fast_it_spins() -> None:
    config = EffectConfig(speed_curve=((0.0, 10.0), (10.0, 10.0), (10.0, 2.0)))
    points = list(trajectory(config, rate=100, duration=12.0))
    slow = points[500].azimuth - points[400].azimuth
    fast = points[1150].azimuth - points[1050].azimuth

    assert fast == pytest.approx(5 * slow, rel=0.01)


def test_interpolate_holds_the_ends_and_draws_straight_lines() -> None:
    frames = ((10.0, 0.2), (20.0, 1.0))

    assert interpolate(frames, 0.0) == 0.2
    assert interpolate(frames, 15.0) == pytest.approx(0.6)
    assert interpolate(frames, 99.0) == 1.0


def test_movement_fades_in_and_out() -> None:
    assert fade_factor(0.0, 3.0, 60.0) == 0.0
    assert fade_factor(1.5, 3.0, 60.0) == pytest.approx(0.5)
    assert fade_factor(30.0, 3.0, 60.0) == 1.0
    assert fade_factor(60.0, 3.0, 60.0) == 0.0
    assert fade_factor(0.0, 0.0, 60.0) == 1.0


def test_elevation_rises_over_two_turns() -> None:
    config = EffectConfig(rotation_seconds=4.0, elevation=0.8, fade_seconds=0)
    points = list(trajectory(config, rate=10, duration=8.0))

    assert points[0].height == 0.0
    assert points[40].height == pytest.approx(0.8)
    assert points[80].height == pytest.approx(0.0, abs=1e-9)


# -------------------------------------------------------------- head model


def test_itd_stays_within_a_real_head() -> None:
    assert 0.6e-3 < MAX_ITD_SECONDS < 0.7e-3
    assert tap_spacing_samples(11025) * (DELAY_TAPS - 1) <= 8


def test_sound_on_the_right_reaches_the_right_ear_first_and_louder() -> None:
    low, high = binaural_gains(Position(math.pi / 2, 1.0, 0.0))
    left_taps, right_taps = low[:DELAY_TAPS], low[DELAY_TAPS:]

    # Right ear first and a bit louder even for low notes; left ear via the last tap
    assert right_taps[0] > 1.0 and right_taps[1:] == [0.0] * (DELAY_TAPS - 1)
    assert 0.0 < left_taps[-1] < 1.0 and left_taps[:-1] == [0.0] * (DELAY_TAPS - 1)
    # Every band is louder in the right ear
    assert all(right > left for left, right in zip(high[:3], high[3:], strict=True))


def test_front_is_centred_and_power_never_changes() -> None:
    low, high = binaural_gains(Position(0.0, 1.0, 0.0))

    assert low[0] == low[DELAY_TAPS] == 1.0
    assert high[:3] == pytest.approx(high[3:])
    # In front (no rear dulling) the two ears' total power stays the same
    for azimuth in (0.3, 1.2, -1.0, -1.5):
        _, bands = binaural_gains(Position(azimuth, 1.0, 0.0))
        presence_power = (bands[0] ** 2 + bands[3] ** 2) / 2
        assert presence_power == pytest.approx(1.0, abs=0.01)


def test_behind_you_sounds_duller() -> None:
    _, front = binaural_gains(Position(0.0, 1.0, 0.0))
    _, behind = binaural_gains(Position(math.pi, 1.0, 0.0))

    assert behind[2] < front[2] * 0.6


def test_zero_intensity_is_plain_stereo() -> None:
    low, high = binaural_gains(Position(1.0, 0.0, 0.0))

    assert low[0] == low[DELAY_TAPS] == 1.0
    assert high == pytest.approx([1.0] * 6)


def test_head_shadow_is_strongest_opposite_the_ear() -> None:
    assert head_shadow(1.0) > 1.0 > head_shadow(-1.0)


def test_pan_gains_keep_the_middle_at_full_volume() -> None:
    assert pan_gains(Position(0.0, 1.0, 0.0)) == pytest.approx([1.0, 1.0])
    left, right = pan_gains(Position(math.pi / 2, 1.0, 0.0))
    assert left == pytest.approx(0.0, abs=1e-9)
    assert right == pytest.approx(math.sqrt(2))


# ------------------------------------------------------------ gain streams


def test_control_streams_have_the_right_shape() -> None:
    three_d = control_streams(EffectConfig(), 1.0)
    panned = control_streams(EffectConfig(engine="pan"), 1.0)

    assert [channels for channels, _ in three_d] == [16, 6]
    assert [channels for channels, _ in panned] == [2]
    frames = len(three_d[0][1]) // 16
    # The stream runs two seconds past the song, so it never ends first
    assert frames >= 3 * CONTROL_RATE


def _wav_header(path: Path) -> tuple[int, int, int, int]:
    """(format, channels, rate, bits) from a WAV file's header."""
    data = path.read_bytes()
    return struct.unpack("<HHIIHH", data[20:36])[0:3] + (
        struct.unpack("<H", data[34:36])[0],
    )


def test_gain_streams_are_float_wavs(tmp_path: Path) -> None:
    paths = write_controls(tmp_path, "s0", EffectConfig(), 1.0)

    assert [_wav_header(path) for path in paths] == [
        (3, 16, CONTROL_RATE, 32),
        (3, 6, CONTROL_RATE, 32),
    ]


# ------------------------------------------------------------------- room


def test_bigger_ambience_means_a_longer_louder_room() -> None:
    small, large = room_for(0.1), room_for(0.9)

    assert large.decay_seconds > small.decay_seconds
    assert large.wet_gain > small.wet_gain


def test_room_is_repeatable_and_normalised(tmp_path: Path) -> None:
    room = room_for(0.3)
    first = impulse_response(room, 8000, seed=8)

    assert first == impulse_response(room, 8000, seed=8)
    assert sum(value * value for value in first) == pytest.approx(1.0)
    assert _wav_header(write_room(tmp_path / "room.wav", 0.3, 8000))[1] == 2


# ------------------------------------------------------------------ graph


def test_graph_keeps_the_bass_in_the_middle_and_ends_in_a_limiter() -> None:
    graph = build_graph(EffectConfig(), _ONE, sample_rate=44100, source_rate=44100)

    assert "acrossover=split=120 1200 5000 10000" in graph
    assert "[s0bass][s0width]amerge" in graph
    assert "afir" in graph
    # The limiter runs at twice the rate so peaks between samples are caught too
    assert "aresample=88200:filter_size=64,alimiter=limit=" in graph
    assert graph.endswith("latency=true,aresample=44100:filter_size=64[out]")
    # Only that last step changes the rate: a 44.1 kHz song is never resampled first
    assert graph.count("aresample=44100:filter_size=64") == 1


def test_graph_resamples_only_when_needed_and_runs_timing_at_a_quarter() -> None:
    graph = build_graph(EffectConfig(), _ONE, sample_rate=48000, source_rate=96000)

    assert "aresample=48000:filter_size=64" in graph
    assert "aresample=12000" in graph


@pytest.mark.parametrize("engine", ["3d", "pan"])
def test_every_source_loses_dc_and_rumble_before_anything_else(engine: str) -> None:
    inputs = GraphInputs((Source(1, (3, 4)), Source(2, (5, 6))), room_input=7)
    if engine == "pan":
        inputs = GraphInputs((Source(1, (3,)), Source(2, (5,))), room_input=7)
    graph = build_graph(
        EffectConfig(engine=engine), inputs, sample_rate=44100, source_rate=44100
    )
    subsonic = "highpass=f=5:poles=2:precision=f64"
    # Once per source, before the song is split into its mid, side and room paths
    assert graph.count(subsonic) == 2
    assert (
        f"[1:a]aformat=sample_fmts=fltp:channel_layouts=stereo,{subsonic},asplit"
        in (graph)
    )


def test_a_mono_song_reaches_both_ears_at_its_full_level() -> None:
    mono = GraphInputs((Source(0, (1, 2), mono=True),), room_input=3)
    stereo = build_graph(EffectConfig(), _ONE, sample_rate=44100, source_rate=44100)
    graph = build_graph(EffectConfig(), mono, sample_rate=44100, source_rate=44100)

    # Copied to both sides, not FFmpeg's 3 dB lower automatic upmix
    assert "[0:a]pan=stereo|c0=c0|c1=c0,aformat=sample_fmts=fltp" in graph
    assert "[0:a]pan=" not in stereo


def test_bass_off_and_pan_engine_graphs() -> None:
    no_bass = build_graph(
        EffectConfig(bass_hz=0), _ONE, sample_rate=44100, source_rate=44100
    )
    panned = build_graph(
        EffectConfig(engine="pan", ambience=0),
        GraphInputs((Source(0, (1,)),)),
        sample_rate=44100,
        source_rate=44100,
    )

    assert "acrossover=split=1200 5000 10000" in no_bass
    assert "adelay" not in panned and "afir" not in panned


def test_two_sources_share_one_room() -> None:
    inputs = GraphInputs((Source(1, (3, 4)), Source(2, (5, 6))), room_input=7)
    graph = build_graph(EffectConfig(), inputs, sample_rate=44100, source_rate=44100)

    assert "[s0room][s1room]amix=inputs=2" in graph
    assert "[1:a]" in graph and "[2:a]" in graph


def test_loudness_gain_and_exact_margin_reach_the_graph() -> None:
    graph = build_graph(
        EffectConfig(exact_loudness=True, limiter_ceiling=0.84),
        _ONE,
        sample_rate=44100,
        gain_db=3.25,
    )
    measure = build_measure_graph(EffectConfig(), _ONE, sample_rate=44100)

    assert "volume=3.25dB" in graph
    assert "alimiter=limit=0.7487" in graph
    assert measure.endswith("ebur128=peak=true:framelog=verbose[out]")


def test_invalid_settings_never_build_a_graph() -> None:
    with pytest.raises(InputValidationError):
        build_graph(EffectConfig(path="spiral"), _ONE, sample_rate=44100)


# ----------------------------------------------------------------- levels


def test_output_rates_suit_each_format() -> None:
    assert mp3_sample_rate_for(96000) == 48000
    assert mp3_sample_rate_for(88200) == 44100
    assert output_sample_rate("opus", 44100) == 48000
    assert output_sample_rate("flac", 96000) == 96000
    assert output_sample_rate("wav", None) == 44100
    assert output_sample_rate("m4a", 32000) == 32000
    # Low-rate audio is lifted so the 5 and 10 kHz head bands fit
    assert output_sample_rate("m4a", 22050) == 44100
    assert output_sample_rate("mp3", 8000) == 48000
    assert output_sample_rate("flac", 16000) == 48000
    assert output_sample_rate("wav", 11025) == 44100


def test_loudness_gain_lets_the_limiter_catch_only_the_movement_peaks() -> None:
    # A loud master whose 8D mix peaks at +3 dBFS still reaches -14 LUFS
    assert loudness_gain_db(-12.0, 3.0, -14.0, 0.84, exact=False) == -2.0
    # A mix with far higher peaks is held back, never squashed
    held = loudness_gain_db(-20.0, 0.0, -14.0, 0.84, exact=False)
    assert held == pytest.approx(20 * math.log10(0.84) + PEAK_ALLOWANCE_DB)
    assert loudness_gain_db(-20.0, 0.0, -14.0, 0.84, exact=True) == 6.0
    assert loudness_gain_db(-70.0, -80.0, -14.0, 0.84, exact=True) == 0.0
