# Developed by ::> Gehan Fernando
"""Checks that finished songs appear all at once and never replace files by surprise."""

import os
from pathlib import Path

import pytest

from src import InputValidationError
from src.files import commit_output, create_temporary_output


def _scratch(tmp_path: Path, payload: bytes = b"new") -> Path:
    """A small stand-in for the temporary file FFmpeg would have written."""
    temp = tmp_path / ".song.partial.mp3"
    temp.write_bytes(payload)
    return temp


def test_temporary_name_is_hidden_unique_and_beside_output(tmp_path: Path) -> None:
    output = tmp_path / "song.mp3"
    first = create_temporary_output(output)
    second = create_temporary_output(output)

    assert first.parent == output.parent
    assert first.name.startswith(".song.")
    assert first.name.endswith(".partial.mp3")
    assert first != second


def test_commit_publishes_file_and_removes_scratch(tmp_path: Path) -> None:
    temp = _scratch(tmp_path)
    output = tmp_path / "song.mp3"

    commit_output(temp, output, overwrite=False)

    assert output.read_bytes() == b"new"
    assert not temp.exists()


def test_commit_never_clobbers_a_file_that_appeared_mid_encode(tmp_path: Path) -> None:
    temp = _scratch(tmp_path)
    output = tmp_path / "song.mp3"
    output.write_bytes(b"precious")

    with pytest.raises(InputValidationError, match="appeared"):
        commit_output(temp, output, overwrite=False)

    assert output.read_bytes() == b"precious"


def test_commit_with_overwrite_replaces_existing(tmp_path: Path) -> None:
    temp = _scratch(tmp_path)
    output = tmp_path / "song.mp3"
    output.write_bytes(b"old")

    commit_output(temp, output, overwrite=True)

    assert output.read_bytes() == b"new"
    assert not temp.exists()


@pytest.mark.skipif(os.name != "nt", reason="rename fallback is Windows-only")
def test_commit_falls_back_when_hard_links_are_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Simulate an exFAT/FAT32 drive where os.link is not supported
    def no_links(*_: object) -> None:
        """Behave like a drive that cannot make hard links."""
        raise OSError("hard links not supported")

    monkeypatch.setattr(os, "link", no_links)
    temp = _scratch(tmp_path)
    output = tmp_path / "song.mp3"

    commit_output(temp, output, overwrite=False)

    assert output.read_bytes() == b"new"
    assert not temp.exists()
