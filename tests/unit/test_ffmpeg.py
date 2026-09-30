# Developed by ::> Gehan Fernando
"""Checks how Audio8D finds FFmpeg, builds its command and reads song details."""

import json
import os
from pathlib import Path

import pytest

from src import ConversionError, DependencyError, EffectConfig, InputValidationError
from src.core.types import Trim
from src.ffmpeg import (
    InputFile,
    build_encode_command,
    parse_ebur128_summary,
    parse_probe_output,
    toolchain,
)
from src.ffmpeg.commands import encoder_arguments
from src.ffmpeg.runner import _progress_value, run_ffmpeg
from src.ffmpeg.toolchain import FFmpegToolchain, _has_audio_encoder, _has_filter


# The exact command matters: one wrong flag changes the sound or breaks the file
def test_encode_command_is_exact() -> None:
    command = build_encode_command(
        Path("ffmpeg"),
        [InputFile(Path("in.wav")), InputFile(Path("gains.wav"))],
        Path("out.mp3"),
        filter_graph="[0:a]anull[out]",
        config=EffectConfig(quality=2),
        sample_rate=44100,
    )

    assert command == [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
        "-i", "in.wav", "-i", "gains.wav",
        "-filter_complex", "[0:a]anull[out]", "-map", "[out]",
        "-map_metadata", "0",
        "-c:a", "libmp3lame", "-q:a", "2",
        "-id3v2_version", "3", "-write_id3v1", "1",
        "-ar", "44100", "-ac", "2",
        "-n", "out.mp3",
    ]  # fmt: skip


def test_cover_title_and_trim_are_added() -> None:
    command = build_encode_command(
        Path("ffmpeg"),
        [InputFile(Path("in.flac"), Trim(60.0, 90.0))],
        Path("out.flac"),
        filter_graph="x",
        config=EffectConfig(output_format="flac"),
        sample_rate=96000,
        cover_art=True,
        title="Song (8D)",
    )
    text = " ".join(command)

    assert "-ss 60.000 -t 30.000 -i in.flac" in text
    assert "-map 0:v:0 -c:v copy -disposition:v:0 attached_pic" in text
    assert "-metadata title=Song (8D)" in text
    assert "-c:a flac" in text and "-bits_per_raw_sample 24" in text


@pytest.mark.parametrize(
    ("fmt", "expected"),
    [
        ("m4a", ["-c:a", "aac", "-b:a", "256k"]),
        ("opus", ["-c:a", "libopus", "-b:a", "192k"]),
        ("wav", ["-c:a", "pcm_s24le"]),
    ],
)
def test_each_format_gets_its_encoder(fmt: str, expected: list[str]) -> None:
    arguments = encoder_arguments(EffectConfig(output_format=fmt))

    assert arguments[: len(expected)] == expected


def test_opus_and_wav_never_get_album_art() -> None:
    for fmt in ("opus", "wav"):
        command = build_encode_command(
            Path("ffmpeg"),
            [InputFile(Path("in.mp3"))],
            Path(f"out.{fmt}"),
            filter_graph="x",
            config=EffectConfig(output_format=fmt),
            sample_rate=48000,
            cover_art=True,
        )
        assert "0:v:0" not in command


def test_probe_parses_a_normal_stream() -> None:
    payload = {
        "streams": [{"codec_name": "flac", "channels": 2, "sample_rate": "48000"}],
        "format": {"duration": "12.5"},
    }
    info = parse_probe_output(json.dumps(payload))

    assert info.codec_name == "flac"
    assert info.channels == 2
    assert info.sample_rate == 48000
    assert info.duration_seconds == 12.5


def test_probe_tolerates_unknown_duration_and_rate() -> None:
    payload = {"streams": [{"channels": 1}], "format": {"duration": "N/A"}}
    info = parse_probe_output(json.dumps(payload))

    assert info.codec_name == "unknown"
    assert info.sample_rate is None
    assert info.duration_seconds is None


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        json.dumps({"streams": []}),
        json.dumps({"streams": [{"codec_name": "mp3"}]}),
        json.dumps({"streams": [{"channels": 0}]}),
        json.dumps({"streams": [{"channels": "two"}]}),
    ],
)
def test_probe_rejects_unusable_output(raw: str) -> None:
    with pytest.raises(InputValidationError):
        parse_probe_output(raw)


def test_capability_regexes_match_real_ffmpeg_listings() -> None:
    filters = (
        " TSC apulsator         A->A       Audio pulsator.\n"
        " ... aecho             A->A       Add echoing to the audio.\n"
    )
    encoders = " A....D libmp3lame           libmp3lame MP3 (MPEG audio layer 3)\n"

    assert _has_filter(filters, "apulsator")
    assert _has_filter(filters, "aecho")
    assert not _has_filter(filters, "alimiter")
    assert _has_audio_encoder(encoders, "libmp3lame")
    assert not _has_audio_encoder(encoders, "libshine")


def _fake_binary(folder: Path, name: str) -> Path:
    """An empty, executable stand-in for ffmpeg or ffprobe."""
    path = folder / (f"{name}.exe" if os.name == "nt" else name)
    path.write_bytes(b"")
    path.chmod(0o755)
    return path


def test_discover_prefers_bundled_binaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(toolchain, "BUNDLED_DIR", tmp_path)
    ffmpeg = _fake_binary(tmp_path, "ffmpeg")
    ffprobe = _fake_binary(tmp_path, "ffprobe")

    found = FFmpegToolchain.discover()

    assert found.ffmpeg == ffmpeg.resolve()
    assert found.ffprobe == ffprobe.resolve()


def test_discover_explains_what_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(toolchain, "BUNDLED_DIR", tmp_path)
    monkeypatch.setattr(toolchain.shutil, "which", lambda _name: None)
    monkeypatch.setattr(toolchain, "_common_folders", list)
    _fake_binary(tmp_path, "ffmpeg")

    with pytest.raises(DependencyError, match="ffprobe"):
        FFmpegToolchain.discover()


def test_top_quality_encodes_use_lames_careful_mode() -> None:
    cbr = encoder_arguments(EffectConfig(quality=0, bitrate=320))
    vbr = encoder_arguments(EffectConfig(quality=0))

    assert cbr[cbr.index("-b:a") + 1] == "320k"
    assert "-q:a" not in cbr
    assert cbr[cbr.index("-compression_level") + 1] == "2"
    assert vbr[vbr.index("-q:a") + 1] == "0"
    assert "-compression_level" in vbr


def test_meter_summary_is_read_correctly() -> None:
    log = """[Parsed_ebur128_3 @ 0000] t: 1.0 M: -30.0 S: -30.0 I: -99.0 LUFS
[Parsed_ebur128_3 @ 0000] Summary:

  Integrated loudness:
    I:         -27.4 LUFS
    Threshold: -37.9 LUFS

  Loudness range:
    LRA:         8.7 LU

  True peak:
    Peak:      -11.5 dBFS
"""
    measured = parse_ebur128_summary(log)

    assert measured.integrated_lufs == -27.4
    assert measured.true_peak_db == -11.5
    assert measured.range_lu == 8.7


def test_meter_summary_handles_silence() -> None:
    log = "Summary:\n    I:  -70.0 LUFS\n    LRA:  0.0 LU\n    Peak:  -inf dBFS\n"

    assert parse_ebur128_summary(log).true_peak_db == float("-inf")


def test_missing_meter_summary_is_a_conversion_error() -> None:
    with pytest.raises(ConversionError):
        parse_ebur128_summary("no summary here")


def test_probe_reads_the_source_bitrate() -> None:
    payload = {
        "streams": [
            {
                "codec_name": "mp3",
                "channels": 2,
                "sample_rate": "48000",
                "bit_rate": "320000",
            }
        ],
        "format": {"duration": "292.4"},
    }
    info = parse_probe_output(json.dumps(payload))

    assert info.bit_rate == 320000
    assert info.is_lossless is False


def test_probe_falls_back_to_the_file_bitrate() -> None:
    payload = {
        "streams": [{"codec_name": "flac", "channels": 2}],
        "format": {"bit_rate": "1411000"},
    }
    info = parse_probe_output(json.dumps(payload))

    assert info.bit_rate == 1411000
    assert info.is_lossless is True


def test_probe_finds_album_art_and_the_title() -> None:
    info = parse_probe_output(
        json.dumps(
            {
                "streams": [
                    {"codec_type": "audio", "codec_name": "mp3", "channels": 2,
                     "sample_rate": "44100"},
                    {"codec_type": "video", "codec_name": "mjpeg",
                     "disposition": {"attached_pic": 1}},
                ],
                "format": {"duration": "10.0", "tags": {"TITLE": "My Song"}},
            }
        )
    )  # fmt: skip

    assert info.has_cover_art is True
    assert info.title == "My Song"


def test_probe_reads_the_sources_depth_format_and_layout() -> None:
    info = parse_probe_output(
        json.dumps(
            {
                "streams": [{"codec_name": "flac", "channels": 2,
                             "sample_rate": "96000", "bits_per_raw_sample": "24",
                             "sample_fmt": "s32", "channel_layout": "stereo"}],
                "format": {"duration": "10.0", "tags": {"ARTIST": "Band"}},
            }
        )
    )  # fmt: skip

    assert info.bits_per_sample == 24
    assert info.sample_format == "s32"
    assert info.channel_layout == "stereo"
    # Tags on the file itself are read from there
    assert info.tags_on_stream is False and info.artist == "Band"


def test_probe_sees_that_ogg_files_keep_their_tags_on_the_stream() -> None:
    info = parse_probe_output(
        json.dumps(
            {
                "streams": [{"codec_name": "opus", "channels": 2,
                             "sample_rate": "48000",
                             "tags": {"ARTIST": "Band", "TITLE": "Song"}}],
                "format": {"duration": "10.0", "format_name": "ogg"},
            }
        )
    )  # fmt: skip

    assert info.tags_on_stream is True
    assert info.artist == "Band" and info.title == "Song"
    # Lossy sources decode to float: they have no stored bit depth
    assert info.bits_per_sample is None


def test_tags_are_copied_from_where_the_source_keeps_them() -> None:
    def metadata_source(on_stream: bool) -> str:
        command = build_encode_command(
            Path("ffmpeg"),
            [InputFile(Path("in.opus"))],
            Path("out.mp3"),
            filter_graph="x",
            config=EffectConfig(),
            sample_rate=48000,
            title="Song (8D)",
            tags_on_stream=on_stream,
        )
        return command[command.index("-map_metadata") + 1]

    assert metadata_source(False) == "0"
    assert metadata_source(True) == "0:s:a:0"


def test_progress_lines_become_shares() -> None:
    assert _progress_value("out_time_us=5000000", 10.0) == 0.5
    assert _progress_value("out_time_ms=20000000", 10.0) == 1.0
    assert _progress_value("progress=continue", 10.0) is None
    assert _progress_value("out_time_us=N/A", 10.0) is None


def test_a_tool_that_cannot_start_gives_a_plain_error(tmp_path: Path) -> None:
    missing = tmp_path / "ffmpeg.exe"

    with pytest.raises(ConversionError, match="Failed to start"):
        run_ffmpeg(
            [str(missing), "-version"], duration=1.0, on_progress=lambda _s: None
        )
