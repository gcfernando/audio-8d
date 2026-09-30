# Developed by ::> Gehan Fernando
"""A preview sounds like the finished song at that moment; only length and file differ.

The movement is picked up at song time, the real format's sample rate and
peak margin are used though the preview is saved as WAV, the song's own trim
is respected, and the preview's loudness follows where that stretch will sit.
"""

# pytest hands fixtures to tests by name, which pylint sees as shadowing
# pylint: disable=redefined-outer-name,protected-access

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from preview_helpers import drain, make_manager

from src import pipeline, previews
from src.analysis import sections
from src.analysis.sections import Section, loudest_section, section_lift_db
from src.core.errors import DependencyError
from src.core.settings import EffectConfig
from src.core.types import AudioStreamInfo, Trim
from src.effects.control import control_streams
from src.effects.graph import finish_stages
from src.effects.motion import trajectory
from src.ffmpeg import FFmpegToolchain
from src.previews import fingerprint, preview_config

# A style that uses everything that changes over time
MOVING = EffectConfig(
    path="figure8",
    elevation=0.8,
    speed_curve=((0.0, 10.0), (20.0, 4.0), (40.0, 8.0)),
    intensity_curve=((0.0, 0.3), (30.0, 1.0)),
    fade_seconds=1.5,
)


def _toolchain() -> FFmpegToolchain:
    """The real FFmpeg, or skip the test when there is none."""
    try:
        return FFmpegToolchain.discover()
    except DependencyError as exc:
        raise pytest.skip.Exception("FFmpeg is not available") from exc


# ------------------------------------------------------------------ movement


@pytest.mark.parametrize("start", [12.3, 25.0, 0.0])
def test_a_late_start_moves_exactly_like_the_full_song(start: float) -> None:
    rate = 200
    full = list(trajectory(MOVING, rate=rate, duration=45.0, total=45.0))
    part = list(trajectory(MOVING, rate=rate, duration=10.0, total=10.0, start=start))
    offset = round(start * rate)

    # Past the preview's own ease-in, every position matches the full song
    for index in range(400, 1600, 37):
        whole, piece = full[offset + index], part[index]
        assert piece.azimuth == pytest.approx(whole.azimuth, abs=1e-9)
        assert piece.height == pytest.approx(whole.height, abs=1e-9)
        assert piece.intensity == pytest.approx(whole.intensity, abs=1e-9)


def test_the_ease_in_stays_on_the_previews_own_clock() -> None:
    part = list(trajectory(MOVING, rate=200, duration=10.0, total=10.0, start=20.0))

    # The movement grows in from nothing at the preview's start and settles at its end
    assert part[0].intensity == 0.0
    assert part[2000].intensity == 0.0
    assert part[400].intensity > 0.5


def test_a_start_between_samples_is_still_followed() -> None:
    fine = list(trajectory(MOVING, rate=1000, duration=20.0))
    part = list(trajectory(MOVING, rate=200, duration=2.0, start=12.3456))
    # Phase is added in 5 ms steps, so a finer path agrees to well under a degree
    assert part[300].azimuth == pytest.approx(fine[12346 + 1500].azimuth, abs=0.02)


def test_the_gain_streams_follow_the_song_timeline() -> None:
    steady = replace(MOVING, fade_seconds=0.0)
    full = control_streams(steady, 30.0)
    part = control_streams(steady, 5.0, start=10.0)

    for (channels, whole), (_same, piece) in zip(full, part, strict=True):
        begin = 10 * 200 * channels
        assert list(piece[: 200 * channels]) == pytest.approx(
            list(whole[begin : begin + 200 * channels]), abs=1e-6
        )


# ------------------------------------------------------------------ format


def _ceiling(stages: str) -> float:
    """The limiter's roof in a finish chain."""
    return float(stages.split("alimiter=limit=")[1].split(":")[0])


def test_a_wav_preview_keeps_the_lossy_peak_margin() -> None:
    wav = replace(EffectConfig(output_format="wav"), exact_loudness=True)
    as_mp3 = finish_stages(wav, -3.0, True, sample_rate=44100, lossless=False)
    as_flac = finish_stages(wav, -3.0, True, sample_rate=44100, lossless=True)
    plain = finish_stages(wav, -3.0, True, sample_rate=44100)

    assert _ceiling(as_mp3) < _ceiling(as_flac) == _ceiling(plain)


class _Recorder:  # pylint: disable=too-few-public-methods
    """Wraps a graph builder, noting the sample rate and margin it was given."""

    def __init__(self, builder) -> None:
        """Nothing recorded yet."""
        self.builder = builder
        self.calls: list[dict] = []

    def __call__(self, *args, **kwargs):
        """Record the call and build the real graph."""
        self.calls.append(kwargs)
        return self.builder(*args, **kwargs)


@pytest.mark.parametrize(
    ("real", "lossless", "rate"),
    [("mp3", False, 44100), ("flac", True, 44100), ("opus", False, 48000)],
)
def test_the_preview_is_made_as_the_real_format(
    stereo_tone: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    real: str,
    lossless: bool,
    rate: int,
) -> None:
    _toolchain()
    finish = _Recorder(pipeline.build_finish_graph)
    monkeypatch.setattr(pipeline, "build_finish_graph", finish)
    config = EffectConfig(
        output_format=real, loudness_target=-14.0, exact_loudness=True
    )

    out = tmp_path / "preview.wav"
    pipeline.preview(
        stereo_tone, out, preview_config(config), seconds=2.0, render_as=real
    )

    assert out.is_file()
    assert finish.calls[-1]["lossless"] is lossless
    assert finish.calls[-1]["sample_rate"] == rate


# ------------------------------------------------------------------ trim and loudness


class _FakeSong:  # pylint: disable=too-few-public-methods
    """Stands in for the pipeline around preview(): records what it is asked."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, section: Section) -> None:
        """Answer every section search with section."""
        self.windows: list[Trim | None] = []
        self.converts: list[tuple[EffectConfig, pipeline.ConvertOptions]] = []
        info = AudioStreamInfo("mp3", 2, 44100, 240.0)
        monkeypatch.setattr(pipeline, "toolchain_for", lambda _config: None)
        monkeypatch.setattr(pipeline, "resolve_input", lambda path: path)
        monkeypatch.setattr(pipeline, "probe_audio", lambda *_a, **_k: info)

        def search(*_args, window=None, **_kwargs):
            self.windows.append(window)
            return section

        def convert(_song, _out, config, *, options, **_kwargs):
            self.converts.append((config, options))

        monkeypatch.setattr(pipeline, "loudest_section", search)
        monkeypatch.setattr(pipeline, "convert", convert)


def test_the_songs_own_trim_is_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeSong(monkeypatch, Section(100.0, 0.0))
    trim = Trim(30.0, 120.0)

    pipeline.preview(Path("song.mp3"), Path("p.wav"), MOVING, seconds=30, trim=trim)

    assert fake.windows == [trim]
    _config, options = fake.converts[0]
    # The section can't run past the song's end, and moves at its own song time
    assert options.trim == Trim(100.0, 120.0)
    assert options.timeline_start == pytest.approx(70.0)
    assert options.check is False


def test_without_a_trim_the_timeline_is_the_songs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeSong(monkeypatch, Section(42.0, None))
    pipeline.preview(Path("song.mp3"), Path("p.wav"), MOVING, seconds=30)

    _config, options = fake.converts[0]
    assert options.trim == Trim(42.0, 72.0) and options.timeline_start == 42.0
    assert options.render_as is None


def test_a_fixed_target_is_raised_by_the_sections_lift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeSong(monkeypatch, Section(60.0, 2.5))
    config = EffectConfig(loudness_target=-14.0)
    pipeline.preview(Path("song.mp3"), Path("p.wav"), config, seconds=30)

    sent, _options = fake.converts[0]
    assert sent.loudness_target == pytest.approx(-11.5)


def test_matching_the_original_and_no_target_are_left_alone() -> None:
    matched = EffectConfig(match_loudness=True)
    assert pipeline._preview_target(matched, 3.0) == matched
    natural = EffectConfig()
    assert pipeline._preview_target(natural, 3.0) == natural
    loud = EffectConfig(loudness_target=-6.0)
    assert pipeline._preview_target(loud, 4.0).loudness_target == -5.0
    assert pipeline._preview_target(loud, None) == loud


def test_the_lift_is_the_sections_loudness_above_the_whole() -> None:
    quiet = [(0.1 * n, -30.0) for n in range(1, 301)]
    loud = [(30.0 + 0.1 * n, -20.0) for n in range(1, 101)]
    lift = section_lift_db(quiet + loud, 30.0, 10.0)

    assert lift is not None and 4.0 < lift < 10.0
    assert section_lift_db([(0.1, -120.0)], 0.0, 1.0) is None


def test_the_loudest_part_is_found_only_inside_the_trim(tmp_path: Path) -> None:
    toolchain = _toolchain()
    song = tmp_path / "loud-then-quiet.wav"
    # Loud for 6 s, then quiet with a small bump at 12-15 s
    subprocess.run(
        [
            str(toolchain.ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i",
            "aevalsrc='sin(2*PI*440*t)*"
            "(if(lt(t,6),0.8,0.05)+if(between(t,12,15),0.2,0))':s=22050:d=20",
            str(song),
        ],
        check=True,
    )  # fmt: skip

    everywhere = loudest_section(toolchain, song, 3.0, 20.0)
    inside = loudest_section(toolchain, song, 3.0, 20.0, window=Trim(8.0, 20.0))

    assert everywhere.start < 4.0
    assert 8.0 <= inside.start <= 17.0
    assert inside.start == pytest.approx(10.0, abs=2.5)
    assert inside.lift_db is not None and inside.lift_db > 0
    assert sections.find_loudest_section(toolchain, song, 3.0, 20.0) < 4.0


# ------------------------------------------------------------------ the window


def test_the_fingerprint_changes_with_format_and_trim(tmp_path: Path) -> None:
    song = tmp_path / "song.mp3"
    song.write_bytes(b"song")
    base = fingerprint(song, MOVING, 30, "preview")

    assert base != fingerprint(
        song, replace(MOVING, output_format="flac"), 30, "preview"
    )
    assert base != fingerprint(song, MOVING, 30, "preview", Trim(5.0, None))
    assert base == fingerprint(song, MOVING, 30, "preview", None)


class _Render:  # pylint: disable=too-few-public-methods
    """Records what the preview manager asks the pipeline for."""

    def __init__(self) -> None:
        """Nothing asked yet."""
        self.calls: list[tuple[EffectConfig, dict]] = []

    def __call__(self, song, output, config, **kwargs):
        """Write a stand-in preview."""
        self.calls.append((config, kwargs))
        output.write_bytes(Path(song).read_bytes())


def test_the_manager_passes_the_real_format_and_trim(tmp_path: Path) -> None:
    song = tmp_path / "song.mp3"
    song.write_bytes(b"song")
    render = _Render()
    manager, events = make_manager(tmp_path, render)
    config = replace(MOVING, output_format="opus")
    trim = Trim(10.0, 100.0)

    manager.start(song, config, 30, trim=trim)
    drain(manager, events)

    sent, kwargs = render.calls[0]
    assert sent.output_format == "wav"
    assert kwargs["render_as"] == "opus" and kwargs["trim"] == trim
    assert manager.is_current(song, config, 30, trim=trim)
    assert not manager.is_current(song, config, 30)
    # A different format is a different preview
    assert not manager.is_current(
        song, replace(config, output_format="mp3"), 30, trim=trim
    )
    manager.close()


def test_make_preview_passes_them_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    render = _Render()
    monkeypatch.setattr(previews, "preview", render)
    song = tmp_path / "song.mp3"
    song.write_bytes(b"song")

    made = previews.make_preview(
        song, tmp_path, replace(MOVING, output_format="mp3"), trim=Trim(1.0, 9.0)
    )

    assert made.suffix == ".wav" and made.is_file()
    assert render.calls[0][1]["render_as"] == "mp3"
    assert render.calls[0][1]["trim"] == Trim(1.0, 9.0)
