# Developed by ::> Gehan Fernando
"""Checks that song and output paths are validated before any work starts."""

import os
from pathlib import Path

import pytest

from src import InputValidationError
from src.files import resolve_input, resolve_output, same_file
from src.files.paths import _LONG_PREFIX as LONG_PREFIX


def test_missing_input_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(InputValidationError, match="does not exist"):
        resolve_input(tmp_path / "missing.mp3")


def test_empty_input_is_rejected(tmp_path: Path) -> None:
    empty = tmp_path / "empty.mp3"
    empty.touch()

    with pytest.raises(InputValidationError, match="empty"):
        resolve_input(empty)


def test_directory_input_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(InputValidationError, match="not a regular file"):
        resolve_input(tmp_path)


def test_valid_input_resolves_to_absolute_path(tmp_path: Path) -> None:
    song = tmp_path / "song.mp3"
    song.write_bytes(b"audio")

    assert resolve_input(song) == song.resolve()


def test_output_must_be_mp3(tmp_path: Path) -> None:
    with pytest.raises(InputValidationError):
        resolve_output(tmp_path / "result.wav", overwrite=False)


def test_output_extension_check_ignores_case(tmp_path: Path) -> None:
    assert resolve_output(tmp_path / "RESULT.MP3", overwrite=False).name == "RESULT.MP3"


def test_missing_output_folders_are_created(tmp_path: Path) -> None:
    output = resolve_output(tmp_path / "a" / "b" / "song.mp3", overwrite=False)

    assert output.parent.is_dir()


def test_existing_output_needs_overwrite_flag(tmp_path: Path) -> None:
    existing = tmp_path / "song_8d.mp3"
    existing.write_bytes(b"old")

    with pytest.raises(InputValidationError, match="--overwrite"):
        resolve_output(existing, overwrite=False)

    assert resolve_output(existing, overwrite=True) == existing.resolve()


def test_output_that_is_a_folder_is_rejected(tmp_path: Path) -> None:
    folder = tmp_path / "trap.mp3"
    folder.mkdir()

    with pytest.raises(InputValidationError, match="not a regular file"):
        resolve_output(folder, overwrite=True)


def test_the_same_file_is_recognised_however_it_is_written(tmp_path: Path) -> None:
    file_path = tmp_path / "song.mp3"
    file_path.write_bytes(b"audio")

    # Windows file names ignore letter case, so these are the same file
    assert same_file(file_path, tmp_path / "SONG.MP3") == (os.name == "nt")
    assert same_file(file_path, file_path.resolve())
    assert not same_file(file_path, tmp_path / "song (8D).mp3")


def _long_form(monkeypatch: pytest.MonkeyPatch, prefix: str) -> None:
    """Make every resolve() answer the way Windows sometimes does."""
    real = Path.resolve
    monkeypatch.setattr(
        Path, "resolve", lambda self, strict=False: Path(prefix + str(real(self)))
    )


@pytest.mark.skipif(os.name != "nt", reason="the long-path form is a Windows thing")
def test_the_windows_long_path_form_is_turned_back_into_a_plain_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    song = tmp_path / "song.mp3"
    song.write_bytes(b"x")
    plain = song.resolve()
    _long_form(monkeypatch, LONG_PREFIX)

    assert resolve_input(song) == plain
    assert resolve_output(tmp_path / "out.mp3", overwrite=False) == (
        plain.with_name("out.mp3")
    )
    # One side in the long form must still count as the same file
    assert same_file(song, plain)
