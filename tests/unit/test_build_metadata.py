# Developed by ::> Gehan Fernando
"""The release's recorded details agree: the .exe version and the bundled versions."""

import re
from pathlib import Path

from src import __version__

ROOT = Path(__file__).resolve().parents[2]


def test_the_windows_version_details_match_the_app_version() -> None:
    text = (ROOT / "packaging" / "version.txt").read_text(encoding="utf-8")
    numbers = tuple(int(part) for part in __version__.split("."))
    # Windows keeps four numbers; the missing ones are zero
    four = str((numbers + (0, 0, 0, 0))[:4])
    assert f"filevers={four}" in text
    assert f"prodvers={four}" in text
    assert f'StringStruct("FileVersion", "{__version__}")' in text
    assert f'StringStruct("ProductVersion", "{__version__}")' in text


def test_the_notices_name_the_versions_the_build_installs() -> None:
    pins = dict(
        line.split("==")
        for line in (ROOT / "packaging" / "requirements-build.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line and not line.startswith("#")
    )
    notices = (ROOT / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")
    listed = {
        name.lower(): version.strip()
        for name, version in re.findall(
            r"^\| \*\*([\w-]+)\*\*[^|]*\| ([^|]+)\|", notices, re.MULTILINE
        )
    }
    assert pins == {name: listed[name] for name in pins}
