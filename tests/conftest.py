# Developed by ::> Gehan Fernando
"""Shared pytest fixtures."""

# Fixtures that use other fixtures name them as arguments; that is how pytest works
# pylint: disable=redefined-outer-name

import subprocess
from pathlib import Path

import pytest

from src import DependencyError, addons
from src.ffmpeg import FFmpegToolchain


@pytest.fixture(autouse=True)
def _private_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    """Keep saved styles and the cache away from the real user folders."""
    home = tmp_path_factory.mktemp("audio8d-home")
    monkeypatch.setenv("AUDIO8D_HOME", str(home))
    # Never open Windows Terminal windows while testing
    monkeypatch.setenv("AUDIO8D_NO_WT", "1")
    return home


@pytest.fixture(autouse=True)
def _fresh_addon_state() -> None:
    """Every test starts without a chosen Python or a remembered add-on check."""
    addons.set_preferred_python(None)
    addons.forget_status()


def find_toolchain() -> FFmpegToolchain | None:
    """The same FFmpeg Audio8D itself would use, or None if there is none."""
    try:
        return FFmpegToolchain.discover()
    except DependencyError:
        return None


def _synthesize(path: Path, *lavfi_args: str) -> Path:
    """Render a short test signal with FFmpeg's built-in generators."""
    toolchain = find_toolchain()
    assert toolchain is not None
    subprocess.run(
        [
            str(toolchain.ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *lavfi_args,
            str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture
def bass_heavy_song(tmp_path: Path) -> Path:
    """Ten seconds of a hot 50 Hz bass line over quieter noise, peaking near 0 dBFS."""
    return _synthesize(
        tmp_path / "bass.wav",
        "-f", "lavfi", "-i", "sine=frequency=50:duration=10:sample_rate=44100",
        "-f", "lavfi", "-i", "anoisesrc=color=pink:duration=10:amplitude=0.2:seed=3",
        "-filter_complex",
        "[0]volume=0.8[b];[b][1]amix=inputs=2:normalize=0,"
        "aformat=channel_layouts=stereo",
    )  # fmt: skip


@pytest.fixture
def stereo_tone(tmp_path: Path) -> Path:
    """Three seconds of a tagged stereo MP3 (440 Hz left, 660 Hz right)."""
    return _synthesize(
        tmp_path / "tone.mp3",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=660:duration=3",
        "-filter_complex", "[0][1]amerge=inputs=2",
        "-metadata", "title=Test Tone",
        "-c:a", "libmp3lame", "-q:a", "2",
    )  # fmt: skip


@pytest.fixture
def tone_with_cover(tmp_path: Path, stereo_tone: Path) -> Path:
    """The stereo tone with a small red album-art picture attached."""
    picture = _synthesize(
        tmp_path / "cover.png",
        "-f", "lavfi", "-i", "color=c=red:s=64x64:d=1", "-frames:v", "1",
    )  # fmt: skip
    return _synthesize(
        tmp_path / "covered.mp3",
        "-i", str(stereo_tone), "-i", str(picture),
        "-map", "0:a", "-map", "1:v", "-c:a", "copy", "-c:v", "mjpeg",
        "-disposition:v", "attached_pic", "-id3v2_version", "3",
    )  # fmt: skip


@pytest.fixture
def click_track(tmp_path: Path) -> Path:
    """Twenty seconds of a kick drum at exactly 120 BPM."""
    return _synthesize(
        tmp_path / "clicks.wav",
        "-f", "lavfi", "-i",
        "aevalsrc='0.8*sin(2*PI*60*t)*exp(-30*mod(t,0.5))':s=44100:d=20",
        "-ac", "2",
    )  # fmt: skip


@pytest.fixture
def mono_wav(tmp_path: Path) -> Path:
    """Two seconds of a mono WAV to make sure upmixing to stereo works."""
    return _synthesize(
        tmp_path / "mono.wav", "-f", "lavfi", "-i", "sine=frequency=220:duration=2"
    )


@pytest.fixture
def dynamic_song(tmp_path: Path) -> Path:
    """Twenty seconds of pink noise that swells and fades, so it has real dynamics."""
    return _synthesize(
        tmp_path / "dynamic.wav",
        "-f", "lavfi", "-i", "anoisesrc=color=pink:duration=20:amplitude=0.3:seed=8",
        "-af", "volume='0.3+0.7*abs(sin(2*PI*t/10))':eval=frame", "-ac", "2",
    )  # fmt: skip
