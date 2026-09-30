# Developed by ::> Gehan Fernando
"""Checks batch fault isolation, the stems cache trim, probe rates, output claims."""

import json
import os
import threading
import time
from pathlib import Path

import pytest

from src import EffectConfig, pipeline
from src.analysis import stems
from src.batch import BatchItem, run_batch, unique_outputs
from src.core.errors import ConversionError
from src.core.types import AudioStreamInfo
from src.effects import output_sample_rate
from src.ffmpeg import parse_probe_output
from src.files import claim_outputs
from src.pipeline import ConversionResult, ConvertOptions

_SOURCE = AudioStreamInfo("mp3", 2, 44100, 1.0)

# -------------------------------------------------------------------- batch


def test_batch_turns_an_unexpected_error_into_one_failed_song(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_convert(source, output, config, **_):  # type: ignore[no-untyped-def]
        if source.name == "bad.mp3":
            raise ValueError("a bug, not a user problem")
        return ConversionResult(_SOURCE, output, config)

    monkeypatch.setattr("src.batch.convert", fake_convert)
    items = [
        BatchItem(Path(f"{n}.mp3"), Path(f"{n} (8D).mp3")) for n in ("a", "bad", "c")
    ]

    report = run_batch(items, EffectConfig(), jobs=2)

    assert [o.item.source.name for o in report.converted] == ["a.mp3", "c.mp3"]
    [failed] = report.failed
    assert isinstance(failed.error, ConversionError)
    assert "a bug" not in str(failed.error)


# ---------------------------------------------------------------- pipeline


class _FakeJob:
    """Stands in for pipeline._Job: writes a tiny 'song' and nothing else."""

    def __init__(self, _song: Path, config: EffectConfig, **_: object) -> None:
        self.info = _SOURCE
        self.config = config
        self.bpm = None
        self.beats = 0

    def prepare(self, _scratch: Path) -> None:
        """Nothing to prepare."""

    def run(self, temporary_file: Path, _scratch: Path) -> None:
        """Write the 'finished' song."""
        temporary_file.write_bytes(b"8d")


@pytest.fixture(name="fake_engine")
def _fake_engine(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    seen: dict[str, object] = {}
    monkeypatch.setattr(pipeline, "toolchain_for", lambda *a, **k: object())
    monkeypatch.setattr(pipeline, "_Job", _FakeJob)

    def fake_check(_toolchain, _path, *, cancel=None):  # type: ignore[no-untyped-def]
        seen["cancel"] = cancel
        raise ConversionError("cancelled")

    monkeypatch.setattr(pipeline, "check_output", fake_check)
    return seen


def test_a_stuck_original_is_a_warning_not_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_engine: dict[str, object]
) -> None:
    del fake_engine
    song = tmp_path / "a.mp3"
    song.write_bytes(b"song")

    def fail_removal(path: Path) -> str:
        raise ConversionError(f"Could not remove the original song {path}: busy")

    monkeypatch.setattr(pipeline, "remove_original", fail_removal)
    result = pipeline.convert(
        song,
        tmp_path / "a (8D).mp3",
        EffectConfig(),
        options=ConvertOptions(replace_original=True),
    )

    assert (tmp_path / "a (8D).mp3").read_bytes() == b"8d"
    assert result.original_removed_to is None
    assert result.warning is not None and "Could not remove" in result.warning


def test_the_final_check_can_be_stopped(
    tmp_path: Path, fake_engine: dict[str, object]
) -> None:
    song = tmp_path / "a.mp3"
    song.write_bytes(b"song")
    cancel = threading.Event()

    result = pipeline.convert(
        song, tmp_path / "a (8D).mp3", EffectConfig(), cancel=cancel
    )

    # A stopped check is skipped; the saved song still counts as done
    assert fake_engine["cancel"] is cancel
    assert result.quality is None and result.warning is None


# ------------------------------------------------------------------- probe


def test_probe_treats_a_zero_sample_rate_as_unknown() -> None:
    payload = {"streams": [{"channels": 2, "sample_rate": "0"}], "format": {}}
    info = parse_probe_output(json.dumps(payload))

    assert info.sample_rate is None
    assert output_sample_rate("flac", info.sample_rate) == 44100
    assert output_sample_rate("mp3", info.sample_rate) == 44100


# -------------------------------------------------------------- stems cache


def _song_folder(root: Path, name: str, size: int, used: float) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "vocals.wav").write_bytes(b"v" * size)
    os.utime(folder, (used, used))
    return folder


def test_stems_cache_drops_the_least_recently_used_songs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "stems"
    monkeypatch.setattr(stems, "_stems_root", lambda: root)
    monkeypatch.setattr(stems, "STEMS_CACHE_LIMIT", 200)
    now = time.time()
    oldest = _song_folder(root, "oldest", 100, now - 300)
    older = _song_folder(root, "older", 100, now - 200)
    newest = _song_folder(root, "newest", 100, now - 100)
    # The song just split is the oldest by date, yet must be kept
    current = _song_folder(root, "current", 50, now - 400)

    stems._prune(current)  # pylint: disable=protected-access

    assert not oldest.exists()
    assert not older.exists()
    assert newest.exists() and current.exists()


def test_stems_cache_sweeps_stale_work_but_spares_running_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "stems"
    monkeypatch.setattr(stems, "_stems_root", lambda: root)
    monkeypatch.setattr(stems, "STEMS_CACHE_LIMIT", 0)
    now = time.time()
    stale_song = _song_folder(root, "stale", 10, now)
    stale = stale_song / "work-old"
    stale.mkdir()
    long_ago = now - 2 * stems.STALE_WORK_SECONDS
    os.utime(stale, (long_ago, long_ago))
    running_song = _song_folder(root, "running", 10, now - 500)
    (running_song / "work-new").mkdir()
    current = _song_folder(root, "current", 10, now)

    stems._prune(current)  # pylint: disable=protected-access

    assert not stale.exists()
    assert running_song.exists()


def test_clearing_the_stems_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "stems"
    monkeypatch.setattr(stems, "_stems_root", lambda: root)
    stems.clear_stems_cache()
    _song_folder(root, "song", 10, time.time())

    stems.clear_stems_cache()

    assert not root.exists()


# ------------------------------------------------------------ output claims


def test_two_songs_making_the_same_file_keep_only_the_first(tmp_path: Path) -> None:
    mp3, flac = tmp_path / "a.mp3", tmp_path / "a.flac"
    output = tmp_path / "a (8D).mp3"

    safe, skipped = claim_outputs([(mp3, output), (flac, output)])

    assert safe == [(mp3, output)]
    assert [source for source, _ in skipped] == [flac]
    assert "a.mp3" in skipped[0][1]


@pytest.mark.skipif(os.name != "nt", reason="letter case matters outside Windows")
def test_outputs_differing_only_in_case_are_the_same_file(tmp_path: Path) -> None:
    first, second = tmp_path / "x.mp3", tmp_path / "y.mp3"

    safe, skipped = claim_outputs(
        [(first, tmp_path / "Song (8D).mp3"), (second, tmp_path / "SONG (8d).MP3")]
    )

    assert [source for source, _ in safe] == [first]
    assert [source for source, _ in skipped] == [second]


def test_an_output_never_overwrites_another_song_of_the_run(tmp_path: Path) -> None:
    flac, mp3 = tmp_path / "a.flac", tmp_path / "a.mp3"

    # Keeping the original name: a.flac would become a.mp3, which is a song too
    safe, skipped = claim_outputs([(flac, mp3), (mp3, mp3)])

    assert safe == [(mp3, mp3)]
    assert [source for source, _ in skipped] == [flac]
    assert "overwrite another song" in skipped[0][1]


# ------------------------------------------------------------ unique names


def test_songs_sharing_a_name_are_numbered(tmp_path: Path) -> None:
    output = tmp_path / "out" / "Intro (8D).mp3"
    items = [BatchItem(tmp_path / folder / "Intro.mp3", output) for folder in "abc"]

    names = [item.output.name for item in unique_outputs(items)]

    assert names == ["Intro (8D).mp3", "Intro (8D) (2).mp3", "Intro (8D) (3).mp3"]


@pytest.mark.skipif(os.name != "nt", reason="letter case matters outside Windows")
def test_names_differing_only_in_case_are_numbered(tmp_path: Path) -> None:
    items = [
        BatchItem(tmp_path / "x.mp3", tmp_path / "Song (8D).mp3"),
        BatchItem(tmp_path / "y.mp3", tmp_path / "SONG (8d).MP3"),
    ]

    names = [item.output.name for item in unique_outputs(items)]

    assert names == ["Song (8D).mp3", "SONG (8d) (2).MP3"]


def test_numbering_never_lands_on_another_song(tmp_path: Path) -> None:
    flac, mp3, other = tmp_path / "a.flac", tmp_path / "a.mp3", tmp_path / "a (2).mp3"

    # Keeping the original name: a.flac would become a.mp3, which is a song too
    items = unique_outputs(
        [BatchItem(flac, mp3), BatchItem(mp3, mp3), BatchItem(other, other)]
    )

    assert [item.output.name for item in items] == ["a (3).mp3", "a.mp3", "a (2).mp3"]


def test_unclashing_items_are_returned_unchanged(tmp_path: Path) -> None:
    items = [BatchItem(tmp_path / "a.mp3", tmp_path / "a (8D).mp3")]

    assert unique_outputs(items)[0] is items[0]
