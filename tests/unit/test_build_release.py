# Developed by ::> Gehan Fernando
"""The release build's own logic: names, the ZIP's modes and links, and its checks.

The full build (PyInstaller, FFmpeg, the unpacked test run) is exercised by
running packaging/build_release.py itself on each system.
"""

import importlib.util
import os
import stat
import sys
import zipfile
from pathlib import Path

import pytest

from src import __version__
from src.core.locations import platform_tag

_SPEC = importlib.util.spec_from_file_location(
    "build_release",
    Path(__file__).resolve().parents[2] / "packaging" / "build_release.py",
)
assert _SPEC is not None and _SPEC.loader is not None
build_release = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_release)


def test_the_package_name_carries_version_system_and_processor() -> None:
    assert build_release.project_version() == __version__
    name = build_release.package_name("1.0.0", "linux-x86_64")
    assert name == "Audio8D-1.0.0-linux-x86_64.zip"
    # The same names the application itself uses
    assert build_release.platform_tag() == platform_tag()


def test_every_system_has_run_instructions_in_its_package() -> None:
    assert set(build_release.HOW_TO_RUN) == {"windows", "linux", "macos"}


def _package(tmp_path: Path) -> Path:
    """A tiny stand-in for a built package."""
    folder = tmp_path / "Audio8D"
    (folder / "_internal").mkdir(parents=True)
    program = folder / "audio8d-cli"
    program.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    program.chmod(0o755)
    (folder / "Audio8D.exe").write_bytes(b"MZ")
    (folder / "README.md").write_text("guide", encoding="utf-8")
    return folder


def test_the_zip_keeps_programs_executable_and_text_files_plain(tmp_path: Path) -> None:
    archive = tmp_path / "bin" / "package.zip"
    build_release.write_zip(_package(tmp_path), archive)

    with zipfile.ZipFile(archive) as bundle:
        modes = {i.filename: i.external_attr >> 16 for i in bundle.infolist()}
    # Everything sits under one top folder, so unzipping never scatters files
    assert all(name.startswith("Audio8D") for name in modes)
    assert stat.S_IMODE(modes["Audio8D/Audio8D.exe"]) == 0o755
    assert stat.S_IMODE(modes["Audio8D/README.md"]) == 0o644
    if sys.platform != "win32":
        assert stat.S_IMODE(modes["Audio8D/audio8d-cli"]) == 0o755

    unpacked = build_release.extract(archive, tmp_path / "with spaces here")
    assert (unpacked / "README.md").read_text(encoding="utf-8") == "guide"
    if sys.platform != "win32":
        assert os.access(unpacked / "audio8d-cli", os.X_OK)


def test_links_inside_a_mac_app_survive_the_zip(tmp_path: Path) -> None:
    folder = _package(tmp_path)
    try:
        os.symlink("_internal", folder / "Frameworks")
    except OSError:
        pytest.skip("this account can't make symbolic links")
    archive = tmp_path / "package.zip"
    build_release.write_zip(folder, archive)

    with zipfile.ZipFile(archive) as bundle:
        link = bundle.getinfo("Audio8D/Frameworks")
        assert stat.S_ISLNK(link.external_attr >> 16)
        assert bundle.read(link) == b"_internal"
    unpacked = build_release.extract(archive, tmp_path / "out")
    assert (unpacked / "Frameworks").is_symlink()


def test_developer_files_are_refused(tmp_path: Path) -> None:
    folder = _package(tmp_path)
    (folder / ".venv").mkdir()
    (folder / ".venv" / "pyvenv.cfg").write_text("x", encoding="utf-8")
    archive = tmp_path / "package.zip"
    build_release.write_zip(folder, archive)

    with pytest.raises(build_release.BuildError, match="developer files"):
        build_release.check_contents(archive)


def test_a_clean_package_passes_the_content_check(tmp_path: Path) -> None:
    archive = tmp_path / "package.zip"
    build_release.write_zip(_package(tmp_path), archive)
    build_release.check_contents(archive)


def test_the_user_environment_has_no_python(tmp_path: Path) -> None:
    env = build_release.user_environment(tmp_path)
    assert env["AUDIO8D_HOME"] == str(tmp_path)
    assert not any(key.upper().startswith("PYTHON") for key in env)
    assert "python" not in env["PATH"].lower()
