# Developed by ::> Gehan Fernando
"""Real conversions through FFmpeg, from test tones to finished 8D files."""

import json
import math
import subprocess
import sys
import threading
from array import array
from dataclasses import replace
from pathlib import Path

import pytest

from src import (
    PRESETS,
    ConversionError,
    ConvertOptions,
    DependencyError,
    EffectConfig,
    InputValidationError,
    Trim,
    compare,
    convert,
    preview,
)
from src.batch import BatchItem, run_batch
from src.core.presets import legacy_config, with_format
from src.ffmpeg.toolchain import BUNDLED_DIR, FFmpegToolchain
from src.pipeline import stages_for

# The same discovery the app itself uses, so both find the same FFmpeg
try:
    TOOLCHAIN: FFmpegToolchain | None = FFmpegToolchain.discover()
except DependencyError:
    TOOLCHAIN = None

# These tests drive real FFmpeg binaries, so skip cleanly on machines without them
pytestmark = pytest.mark.skipif(TOOLCHAIN is None, reason="ffmpeg/ffprobe not found")

# Quick settings for tests that are not about loudness
FAST = EffectConfig(ambience=0.2)


def _probe(path: Path) -> dict:
    """Return FFprobe's view of the finished file."""
    assert TOOLCHAIN is not None
    result = subprocess.run(
        [
            str(TOOLCHAIN.ffprobe), "-v", "error",
            "-show_entries",
            "stream=codec_type,codec_name,channels,sample_rate"
            ":stream_disposition=attached_pic:format=duration:format_tags=title"
            ":stream_tags=title",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return json.loads(result.stdout)


def _samples(
    path: Path, seconds: float | None = None
) -> tuple[list[float], list[float]]:
    """Left and right channels as floats at 8 kHz (plenty for level checks)."""
    assert TOOLCHAIN is not None
    limit = ["-t", str(seconds)] if seconds else []
    raw = subprocess.run(
        [str(TOOLCHAIN.ffmpeg), "-v", "error", "-i", str(path), *limit,
         "-ac", "2", "-ar", "8000", "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    data = array("f")
    data.frombytes(raw)
    return list(data[0::2]), list(data[1::2])


def _leftover_scratch_files(folder: Path) -> list[Path]:
    """Hidden half-finished files that a clean run must never leave behind."""
    return list(folder.glob(".*.partial.*"))


def test_stereo_source_becomes_tagged_stereo_mp3(
    stereo_tone: Path, tmp_path: Path
) -> None:
    output = tmp_path / "out" / "tone_8d.mp3"

    result = convert(stereo_tone, output, FAST)

    assert result.source.channels == 2
    assert result.quality is not None
    probed = _probe(output)
    assert probed["streams"][0]["codec_name"] == "mp3"
    assert probed["streams"][0]["channels"] == 2
    assert probed["format"]["tags"]["title"] == "Test Tone (8D)"
    assert not _leftover_scratch_files(output.parent)


def test_title_can_be_kept_as_it_was(stereo_tone: Path, tmp_path: Path) -> None:
    output = tmp_path / "kept.mp3"
    convert(stereo_tone, output, FAST, options=ConvertOptions(tag_title=False))

    assert _probe(output)["format"]["tags"]["title"] == "Test Tone"


def test_mono_source_is_upmixed_to_stereo(mono_wav: Path, tmp_path: Path) -> None:
    output = tmp_path / "mono_8d.mp3"

    result = convert(mono_wav, output, EffectConfig(ambience=0.0, quality=0))

    assert result.source.channels == 1
    assert _probe(output)["streams"][0]["channels"] == 2


def test_existing_output_is_protected_until_overwrite(
    stereo_tone: Path, tmp_path: Path
) -> None:
    output = tmp_path / "tone_8d.mp3"
    output.write_bytes(b"keep me")

    with pytest.raises(InputValidationError):
        convert(stereo_tone, output, FAST)
    assert output.read_bytes() == b"keep me"

    convert(stereo_tone, output, FAST, overwrite=True)
    assert output.read_bytes() != b"keep me"
    assert not _leftover_scratch_files(tmp_path)


def test_non_audio_input_is_rejected(tmp_path: Path) -> None:
    junk = tmp_path / "notes.txt"
    junk.write_text("definitely not audio")

    with pytest.raises(InputValidationError):
        convert(junk, tmp_path / "out.mp3", FAST)


@pytest.mark.parametrize(
    ("fmt", "codec", "rate"),
    [("flac", "flac", "44100"), ("wav", "pcm_s24le", "44100"),
     ("m4a", "aac", "44100"), ("opus", "opus", "48000")],
)  # fmt: skip
def test_every_output_format(
    stereo_tone: Path, tmp_path: Path, fmt: str, codec: str, rate: str
) -> None:
    output = tmp_path / f"tone.{fmt}"
    convert(stereo_tone, output, replace(FAST, output_format=fmt))

    stream = _probe(output)["streams"][0]
    assert stream["codec_name"] == codec
    assert stream["sample_rate"] == rate
    assert stream["channels"] == 2


@pytest.mark.parametrize("fmt", ["mp3", "flac", "m4a"])
def test_album_art_is_kept(tone_with_cover: Path, tmp_path: Path, fmt: str) -> None:
    output = tmp_path / f"out.{fmt}"
    result = convert(tone_with_cover, output, replace(FAST, output_format=fmt))

    assert result.source.has_cover_art
    pictures = [s for s in _probe(output)["streams"] if s["codec_type"] == "video"]
    assert pictures and pictures[0]["disposition"]["attached_pic"] == 1


def test_album_art_can_be_left_out(tone_with_cover: Path, tmp_path: Path) -> None:
    output = tmp_path / "bare.mp3"
    convert(tone_with_cover, output, FAST, options=ConvertOptions(keep_cover=False))

    assert all(s["codec_type"] == "audio" for s in _probe(output)["streams"])


def test_trim_keeps_only_the_chosen_part(dynamic_song: Path, tmp_path: Path) -> None:
    output = tmp_path / "part.wav"
    convert(
        dynamic_song,
        output,
        replace(FAST, output_format="wav"),
        options=ConvertOptions(trim=Trim(5.0, 12.5)),
    )

    assert float(_probe(output)["format"]["duration"]) == pytest.approx(7.5, abs=0.05)


def _rms(values: list[float]) -> float:
    """Root-mean-square level of some samples."""
    return math.sqrt(sum(v * v for v in values) / max(1, len(values)))


def test_3d_movement_really_moves_between_the_ears(
    dynamic_song: Path, tmp_path: Path
) -> None:
    output = tmp_path / "moving.wav"
    config = EffectConfig(
        rotation_seconds=8.0, intensity=1.0, ambience=0.0, fade_seconds=0,
        output_format="wav",
    )  # fmt: skip
    convert(dynamic_song, output, config)
    left, right = _samples(output)

    # At 2 s the sound is at the right ear, at 6 s at the left (8 s per circle)
    def balance(second: float) -> float:
        start, end = int((second - 0.25) * 8000), int((second + 0.25) * 8000)
        return 20 * math.log10(_rms(right[start:end]) / _rms(left[start:end]))

    # Pink noise is mostly low notes, which move less than the highs do
    assert balance(2.0) > 2.0
    assert balance(6.0) < -2.0


def test_zero_movement_leaves_left_and_right_alike(
    stereo_tone: Path, tmp_path: Path
) -> None:
    output = tmp_path / "still.wav"
    config = EffectConfig(intensity=0.0, ambience=0.0, output_format="wav")
    convert(stereo_tone, output, config)
    left, right = _samples(output)

    # The balance between the ears never changes when nothing moves
    def balance(second: float) -> float:
        start, end = int(second * 8000), int((second + 0.5) * 8000)
        return _rms(right[start:end]) / _rms(left[start:end])

    assert balance(0.5) == pytest.approx(balance(2.0), rel=0.02)


def test_bass_stays_in_the_middle(tmp_path: Path) -> None:
    assert TOOLCHAIN is not None
    bass = tmp_path / "bass.wav"
    subprocess.run(
        [str(TOOLCHAIN.ffmpeg), "-v", "error", "-f", "lavfi", "-i",
         "sine=frequency=50:duration=8", "-ac", "2", str(bass)],
        check=True,
    )  # fmt: skip
    output = tmp_path / "bass_8d.wav"
    convert(
        bass, output, EffectConfig(intensity=1.0, ambience=0.0, output_format="wav")
    )
    left, right = _samples(output)
    middle = slice(8000, 7 * 8000)

    assert _rms(left[middle]) == pytest.approx(_rms(right[middle]), rel=0.05)


def test_beat_sync_finds_the_tempo(click_track: Path, tmp_path: Path) -> None:
    result = convert(click_track, tmp_path / "beat.mp3", replace(FAST, beat_sync=True))

    assert result.bpm == pytest.approx(120, abs=1.5)
    assert result.config.rotation_seconds == pytest.approx(8.0, abs=0.1)
    assert result.beats_per_turn == 16


def test_replace_puts_the_8d_song_in_place_of_the_original(
    stereo_tone: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    removed: list[Path] = []

    def fake_remove(path: Path) -> str:
        """Delete for real, but without touching the Recycle Bin in tests."""
        removed.append(path)
        path.unlink()
        return "deleted"

    monkeypatch.setattr("src.pipeline.remove_original", fake_remove)
    before = stereo_tone.read_bytes()

    result = convert(
        stereo_tone, stereo_tone, FAST, options=ConvertOptions(replace_original=True)
    )

    assert removed == [stereo_tone]
    assert result.original_removed_to == "deleted"
    assert stereo_tone.read_bytes() != before
    assert _probe(stereo_tone)["format"]["tags"]["title"] == "Test Tone (8D)"
    assert not _leftover_scratch_files(stereo_tone.parent)


def test_writing_over_the_original_needs_replace(stereo_tone: Path) -> None:
    with pytest.raises(InputValidationError):
        convert(stereo_tone, stereo_tone, FAST)


def test_preview_and_compare(dynamic_song: Path, tmp_path: Path) -> None:
    short = preview(dynamic_song, tmp_path / "p.mp3", FAST, seconds=6.0)
    both = compare(dynamic_song, tmp_path / "ab.mp3", FAST, seconds=5.0)

    assert float(_probe(short.output)["format"]["duration"]) == pytest.approx(
        6, abs=0.2
    )
    # Original, a 1.2 s pause, then the 8D version
    assert float(_probe(both)["format"]["duration"]) == pytest.approx(11.2, abs=0.2)


def test_batch_converts_a_whole_list(
    stereo_tone: Path, mono_wav: Path, tmp_path: Path
) -> None:
    out = tmp_path / "8D"
    items = [
        BatchItem(stereo_tone, out / "tone (8D).mp3"),
        BatchItem(mono_wav, out / "mono (8D).mp3"),
        BatchItem(tmp_path / "missing.mp3", out / "missing (8D).mp3"),
    ]
    report = run_batch(items, FAST, jobs=2)

    assert len(report.converted) == 2
    assert len(report.failed) == 1
    assert (out / "tone (8D).mp3").is_file()


def test_bundled_binaries_win_over_path() -> None:
    bundled = BUNDLED_DIR / "ffmpeg.exe"
    if not bundled.is_file():
        pytest.skip("no ffmpeg.exe kept in 8D/vendor/ffmpeg for this system")
    assert BUNDLED_DIR.parent.name == "ffmpeg" and BUNDLED_DIR.name == "windows-x86_64"

    assert TOOLCHAIN is not None
    assert TOOLCHAIN.ffmpeg == bundled.resolve()
    assert TOOLCHAIN.ffprobe == (BUNDLED_DIR / "ffprobe.exe").resolve()
    TOOLCHAIN.validate_capabilities()


def test_standalone_run_from_src_converts_a_song(stereo_tone: Path) -> None:
    src = Path(__file__).resolve().parents[2] / "src"
    # Not installed, started from inside src, and only the song name given
    result = subprocess.run(
        [sys.executable, "-S", ".", str(stereo_tone)],
        cwd=src,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    output = stereo_tone.with_name("tone (8D).mp3")
    assert _probe(output)["streams"][0]["channels"] == 2


def _loudness(path: Path) -> tuple[float, float]:
    """Integrated loudness (LUFS) and true peak (dBFS) measured by FFmpeg's ebur128."""
    assert TOOLCHAIN is not None
    result = subprocess.run(
        [str(TOOLCHAIN.ffmpeg), "-hide_banner", "-nostats", "-i", str(path),
         "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    summary = result.stderr[result.stderr.rindex("Summary:") :]
    integrated = float(summary.split("I:")[1].split("LUFS")[0])
    peak = float(summary.split("Peak:")[1].split("dBFS")[0])
    return integrated, peak


def test_studio_preset_hits_streaming_loudness(
    stereo_tone: Path, tmp_path: Path
) -> None:
    output = tmp_path / "tone_studio.mp3"
    result = convert(stereo_tone, output, PRESETS["studio"].config)

    integrated, peak = _loudness(output)
    # Within 1.5 LU of -14 LUFS, with peaks under the ceiling plus a little MP3 slack
    assert -15.5 <= integrated <= -12.5
    assert peak <= -0.3
    assert result.quality is not None
    assert result.quality.integrated_lufs == pytest.approx(integrated, abs=0.2)


def _loudness_range(path: Path) -> float:
    """Loudness range (LRA) in LU, which only changes if the dynamics are squashed."""
    assert TOOLCHAIN is not None
    result = subprocess.run(
        [str(TOOLCHAIN.ffmpeg), "-hide_banner", "-nostats", "-i", str(path),
         "-af", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    summary = result.stderr[result.stderr.rindex("Summary:") :]
    return float(summary.split("LRA:")[1].split("LU")[0])


def test_studio_changes_volume_but_never_the_dynamics(
    dynamic_song: Path, tmp_path: Path
) -> None:
    song = dynamic_song
    studio = PRESETS["studio"].config
    loud = tmp_path / "studio.mp3"
    natural = tmp_path / "natural.mp3"
    plans = []

    convert(song, loud, studio, on_loudness=plans.append)
    convert(song, natural, replace(studio, loudness_target=None))

    assert plans and plans[0].gain_db != 0
    assert _loudness_range(loud) == pytest.approx(_loudness_range(natural), abs=0.3)
    integrated, peak = _loudness(loud)
    assert integrated == pytest.approx(plans[0].expected_lufs, abs=0.6)
    assert peak <= -0.9


@pytest.mark.parametrize("output_format", ["mp3", "flac", "opus"])
@pytest.mark.parametrize("name", sorted(PRESETS))
def test_every_style_reaches_the_target_without_clipping(
    name: str, output_format: str, dynamic_song: Path, tmp_path: Path
) -> None:
    output = tmp_path / f"{name}.{output_format}"
    config = with_format(PRESETS[name].config, output_format)
    convert(dynamic_song, output, config)

    integrated, peak = _loudness(output)
    # -14 LUFS within 1.5 LU, and true peaks under -1 dBTP plus a little MP3 slack
    assert -15.5 <= integrated <= -12.5, name
    if output_format == "flac":
        # Lossless files keep sample peaks under -1 dBFS; true peaks never clip
        assert peak <= -0.5, name
    else:
        # Lossy files keep the -1 dBTP headroom (plus a little decoder slack)
        assert peak <= -0.9, name


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_every_style_keeps_a_hot_bass_line_from_clipping(
    name: str, bass_heavy_song: Path, tmp_path: Path
) -> None:
    output = tmp_path / f"{name}.mp3"
    convert(bass_heavy_song, output, PRESETS[name].config)

    _integrated, peak = _loudness(output)
    assert peak <= -0.9, name


def test_second_run_reuses_the_loudness_measurement(
    stereo_tone: Path, tmp_path: Path
) -> None:
    studio = PRESETS["studio"].config
    first = convert(stereo_tone, tmp_path / "a.mp3", studio)
    second = convert(stereo_tone, tmp_path / "b.mp3", replace(studio, bitrate=256))

    assert first.loudness is not None and not first.loudness.cached
    assert second.loudness is not None and second.loudness.cached
    assert second.loudness.measured == first.loudness.measured


def test_loudness_can_match_the_original_song(
    dynamic_song: Path, tmp_path: Path
) -> None:
    stages: set[str] = set()
    result = convert(
        dynamic_song,
        tmp_path / "hifi.flac",
        legacy_config("hifi"),
        on_progress=lambda stage, share: stages.add(stage),
    )
    original, _ = _loudness(dynamic_song)

    assert result.loudness is not None
    assert result.loudness.target_lufs == pytest.approx(original, abs=0.1)
    assert result.quality is not None
    assert result.quality.integrated_lufs == pytest.approx(original, abs=1.0)
    # One heavy mix pass, then a light save pass
    assert {"Making your 8D song", "Saving the file"} <= stages
    # Lossless output keeps the original's sample rate
    source_rate = _probe(dynamic_song)["streams"][0]["sample_rate"]
    assert _probe(tmp_path / "hifi.flac")["streams"][0]["sample_rate"] == source_rate


@pytest.mark.parametrize("name", ["song.mp3", "song.flac"])
def test_progress_stages_never_go_backwards(
    stereo_tone: Path, tmp_path: Path, name: str
) -> None:
    order = stages_for(ConvertOptions())
    seen: list[int] = []
    studio = replace(PRESETS["studio"].config, output_format=name.split(".")[1])
    for attempt in ("first", "remembered"):
        seen.clear()
        convert(
            stereo_tone,
            tmp_path / f"{attempt} {name}",
            studio,
            on_progress=lambda stage, share: seen.append(order.index(stage)),
        )
        assert seen == sorted(seen), attempt
        assert set(seen) == set(range(len(order))), attempt


def test_a_stopped_compare_leaves_nothing_behind(
    dynamic_song: Path, tmp_path: Path
) -> None:
    stop = threading.Event()
    stop.set()
    output = tmp_path / "dynamic (A-B compare).mp3"

    with pytest.raises(ConversionError):
        compare(dynamic_song, output, PRESETS["studio"].config, cancel=stop)
    assert not list(tmp_path.glob("*compare*"))
    assert not list(tmp_path.glob(".*partial*"))


def test_low_sample_rate_songs_are_lifted_so_the_3d_bands_fit(tmp_path: Path) -> None:
    assert TOOLCHAIN is not None
    phone = tmp_path / "phone.wav"
    subprocess.run(
        [str(TOOLCHAIN.ffmpeg), "-v", "error", "-f", "lavfi", "-i",
         "sine=f=440:r=8000:d=4", "-ac", "2", "-c:a", "pcm_u8", str(phone)],
        check=True,
    )  # fmt: skip

    result = convert(phone, tmp_path / "phone.flac", legacy_config("lossless"))

    stream = _probe(result.output)["streams"][0]
    assert stream["sample_rate"] == "48000" and stream["channels"] == 2
    assert result.quality is not None and result.quality.true_peak_db < 0
