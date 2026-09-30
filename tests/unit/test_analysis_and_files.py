# Developed by ::> Gehan Fernando
"""Checks tempo maths, loudest-section search, the cache, folders, batches, launcher."""

import math
import os
import random
import threading
from array import array
from pathlib import Path

import pytest

from src import EffectConfig, InputValidationError, cache, launcher
from src.analysis.quality import QualityReport, correlation_from_loudness
from src.analysis.sections import loudest_start, short_term_loudness
from src.analysis.tempo import onset_strength, rotation_for_tempo, tempo_from_onsets
from src.batch import BatchItem, progress_tracker, run_batch
from src.core.errors import ConversionError
from src.core.types import AudioStreamInfo, Trim
from src.ffmpeg import LoudnessMeasurement
from src.files import (
    default_output_for,
    describe_removal,
    find_songs,
    format_for_extension,
    is_own_output,
    output_name,
    removal_summary,
    remove_original,
    resolve_output,
    trash,
)
from src.pipeline import ConversionResult

# ------------------------------------------------------------------- tempo


def _onsets(bpm: float, seconds: float = 30.0) -> list[float]:
    """An onset pattern with one sharp hit per beat, at 100.2 values a second."""
    rate = 11025 / 110
    beat = rate * 60 / bpm
    count = int(seconds * rate)
    values = [0.0] * count
    position = 0.0
    while position < count:
        values[int(position)] = 1.0
        position += beat
    mean = sum(values) / count
    return [value - mean for value in values]


@pytest.mark.parametrize("bpm", [80, 100, 120, 128, 150])
def test_tempo_is_found_from_onsets(bpm: float) -> None:
    assert tempo_from_onsets(_onsets(bpm)) == pytest.approx(bpm, abs=1.5)


def test_no_beat_means_no_tempo() -> None:
    assert tempo_from_onsets([0.0] * 50) is None


def test_random_onsets_are_not_mistaken_for_a_beat() -> None:
    # Noise or ambient music always matches itself a little somewhere; that's no beat
    noise = random.Random(7)
    values = [noise.random() for _ in range(3000)]
    mean = sum(values) / len(values)

    assert tempo_from_onsets([value - mean for value in values]) is None


def test_onsets_are_louder_steps() -> None:
    samples = array("h", [0, 0] * 220 + [10000, 10000] * 220)

    novelty = onset_strength(samples)
    assert novelty.index(max(novelty)) == 2


def test_rotation_snaps_to_whole_bars() -> None:
    assert rotation_for_tempo(120, 8.0) == (8.0, 16)
    seconds, beats = rotation_for_tempo(90, 8.0)
    assert (seconds, beats) == (pytest.approx(10.667, abs=0.01), 16)
    assert rotation_for_tempo(60, 3.0) == (4.0, 4)


# ----------------------------------------------------------------- sections


def test_loudest_window_is_found() -> None:
    log = "\n".join(
        f"[Parsed_ebur128_0 @ x] t: {t / 10:.1f}  TARGET:-23 LUFS  M: -20 S: "
        + ("-8.0" if 600 <= t < 900 else "-20.0")
        + " I: -18 LUFS"
        for t in range(1, 1500)
    )
    points = short_term_loudness(log)

    assert len(points) == 1499
    assert loudest_start(points, 30.0) == pytest.approx(57.0, abs=1.0)
    assert loudest_start([], 30.0) == 0.0


# ------------------------------------------------------------------ quality


def test_correlation_from_stereo_and_mono_loudness() -> None:
    fold = 10 * math.log10(2)
    assert correlation_from_loudness(-14.0, -14.0 - fold) == pytest.approx(1.0)
    assert correlation_from_loudness(-14.0, -14.0 - 2 * fold) == pytest.approx(0.0)
    assert correlation_from_loudness(-14.0, -40.0) == pytest.approx(-1.0, abs=0.02)
    report = QualityReport(-14.0, -1.0, 6.0, 0.5)
    assert report.mono_safe and report.peak_safe


# -------------------------------------------------------------------- cache


def test_cache_remembers_until_the_song_changes(tmp_path: Path) -> None:
    song = tmp_path / "song.mp3"
    song.write_bytes(b"one")
    config = EffectConfig(loudness_target=-14.0)
    key = cache.measurement_key(song, config, None, 44100)
    measured = LoudnessMeasurement(-12.0, 1.0, 6.0)
    cache.put(key, measured)

    assert cache.get(key) == measured
    # Settings after the measurement don't matter; ones before it do
    assert cache.measurement_key(song, EffectConfig(bitrate=320), None, 44100) == key
    assert cache.measurement_key(song, EffectConfig(intensity=0.5), None, 44100) != key
    assert cache.measurement_key(song, config, Trim(1.0, 2.0), 44100) != key
    song.write_bytes(b"changed")
    assert cache.measurement_key(song, config, None, 44100) != key
    assert cache.get(None) is None


# -------------------------------------------------------------------- files


def test_output_names() -> None:
    assert output_name(Path("a/song.flac"), ".mp3") == "song (8D).mp3"
    assert output_name(Path("a/song.flac"), ".mp3", "original") == "song.mp3"
    assert default_output_for(Path("a/b/song.mp3"), ".flac") == Path(
        "a/b/song (8D).flac"
    )
    assert default_output_for(
        Path("M/Rock/s.mp3"), ".mp3", output_dir=Path("O"), relative_to=Path("M")
    ) == Path("O/Rock/s (8D).mp3")
    assert format_for_extension(Path("x.OPUS")) == "opus"
    assert format_for_extension(Path("x.ogg")) is None


def test_resolve_output_checks_the_extension(tmp_path: Path) -> None:
    with pytest.raises(InputValidationError, match="must use the .flac"):
        resolve_output(tmp_path / "x.mp3", overwrite=False, extension=".flac")
    assert resolve_output(tmp_path / "x.flac", overwrite=False, extension=".flac")


def test_find_songs_skips_own_files_and_other_files(tmp_path: Path) -> None:
    for name in ("b.mp3", "A.flac", "a (8D).mp3", "a (8D preview).mp3", ".x.mp3",
                 "notes.txt", "sub/c.wav"):  # fmt: skip
        (tmp_path / name).parent.mkdir(exist_ok=True)
        (tmp_path / name).write_bytes(b"x")

    assert [p.name for p in find_songs(tmp_path)] == ["A.flac", "b.mp3"]
    assert len(find_songs(tmp_path, recursive=True)) == 3
    assert is_own_output(Path("x (A-B compare).mp3"))
    with pytest.raises(InputValidationError):
        find_songs(tmp_path / "missing")


@pytest.mark.skipif(os.name != "nt", reason="the Windows Recycle Bin")
def test_an_original_goes_to_the_recycle_bin_when_its_drive_has_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    song = tmp_path / "old.mp3"
    song.write_bytes(b"x")
    # Stand in for the real bin, so the tests never fill yours
    monkeypatch.setattr(trash, "_has_recycle_bin", lambda _path: True)
    monkeypatch.setattr(trash, "_windows_recycle", lambda path: path.unlink() is None)

    where = remove_original(song)

    assert not song.exists()
    assert describe_removal(where) == "moved to the Recycle Bin"


@pytest.mark.parametrize("bin_works", [False, True])
def test_an_original_is_never_deleted_for_good(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bin_works: bool
) -> None:
    song = tmp_path / "old.mp3"
    song.write_bytes(b"precious")
    (tmp_path / "old (original).mp3").write_bytes(b"from an earlier replace")
    # A USB stick has no bin; a bin can also refuse. Either way the song must survive
    monkeypatch.setattr(trash, "_has_recycle_bin", lambda _path: bin_works)
    monkeypatch.setattr(trash, "_windows_recycle", lambda _path: False)
    monkeypatch.setattr(trash, "_unix_trash", lambda _path: False)

    where = remove_original(song)

    assert not song.exists()
    assert (tmp_path / "old (original 2).mp3").read_bytes() == b"precious"
    assert "kept in its folder as 'old (original 2).mp3'" in describe_removal(where)
    assert is_own_output(tmp_path / "old (original 2).mp3")


def test_many_removals_are_summed_up_in_words() -> None:
    places = ["Recycle Bin", "Recycle Bin", "kept as a (original).mp3"]

    assert removal_summary(places) == [
        "2 originals moved to the Recycle Bin.",
        "1 original kept in its folder as '<song> (original)' (no Recycle Bin there).",
    ]


# -------------------------------------------------------------------- batch


def test_batch_keeps_going_after_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_convert(source, output, config, **_):  # type: ignore[no-untyped-def]
        if source.name == "bad.mp3":
            raise ConversionError("broken song")
        return ConversionResult(AudioStreamInfo("mp3", 2, 44100, 1.0), output, config)

    monkeypatch.setattr("src.batch.convert", fake_convert)
    items = [
        BatchItem(Path(f"{n}.mp3"), Path(f"{n} (8D).mp3")) for n in ("a", "bad", "c")
    ]
    finished: list[int] = []

    report = run_batch(
        items, EffectConfig(), jobs=2, on_done=lambda index, _: finished.append(index)
    )

    assert len(report.converted) == 2
    assert [o.item.source.name for o in report.failed] == ["bad.mp3"]
    assert [r.output.name for r in report.results] == ["a (8D).mp3", "c (8D).mp3"]
    assert sorted(finished) == [0, 1, 2]


def test_batch_uses_each_songs_own_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    used: dict[str, EffectConfig] = {}

    def fake_convert(source, output, config, **_):  # type: ignore[no-untyped-def]
        used[source.name] = config
        return ConversionResult(AudioStreamInfo("mp3", 2, 44100, 1.0), output, config)

    monkeypatch.setattr("src.batch.convert", fake_convert)
    own = EffectConfig(intensity=0.5, output_format="flac")
    items = [
        BatchItem(Path("a.mp3"), Path("a (8D).mp3")),
        BatchItem(Path("b.mp3"), Path("b (8D).flac"), own),
    ]

    run_batch(items, EffectConfig(), jobs=2)
    assert used == {"a.mp3": EffectConfig(), "b.mp3": own}


def test_batch_stops_when_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.batch.convert", lambda *a, **k: pytest.fail("ran"))
    cancel = threading.Event()
    cancel.set()

    report = run_batch([BatchItem(Path("a"), Path("b"))], EffectConfig(), cancel=cancel)
    assert not report.converted and not report.failed


def test_overall_progress_averages_every_song() -> None:
    update, overall = progress_tracker(2, ["measure", "render"])
    update(0, "measure", 1.0)
    update(0, "render", 1.0)
    update(1, "render", 0.5)

    assert overall() == pytest.approx(0.625)


# ----------------------------------------------------------------- launcher


def test_launcher_never_moves_a_session_you_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(launcher.DISABLE_VARIABLE, raising=False)
    monkeypatch.setattr(launcher.os, "name", "nt")
    monkeypatch.setattr(launcher.shutil, "which", lambda _name: "wt.exe")
    monkeypatch.setattr(launcher.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.delenv("TERM_PROGRAM", raising=False)

    monkeypatch.setattr(
        launcher, "_console_process_names", lambda: ["py.exe", "python.exe"]
    )
    assert launcher.should_relaunch() is True
    monkeypatch.setattr(
        launcher, "_console_process_names", lambda: ["powershell.exe", "python.exe"]
    )
    assert launcher.should_relaunch() is False
    monkeypatch.setenv("WT_SESSION", "x")
    assert launcher.should_relaunch() is False


def test_launcher_is_off_when_disabled() -> None:
    # conftest sets AUDIO8D_NO_WT for every test
    assert os.environ.get(launcher.DISABLE_VARIABLE)
    assert launcher.relaunch_in_windows_terminal([]) is False


def test_launcher_passes_the_same_arguments() -> None:
    # pylint: disable-next=protected-access
    command = launcher._start_command(["My;Song.mp3", "--preset", "studio"])

    assert command[1].endswith("__main__.py")
    assert command[2:] == [r"My\;Song.mp3", "--preset", "studio"]
