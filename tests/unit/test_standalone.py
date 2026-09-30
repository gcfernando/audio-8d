# Developed by ::> Gehan Fernando
"""Checks every way of starting Audio8D without installing it."""

import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
ROOT = SRC.parent

# Every way a person might start Audio8D without ever running `pip install`
WAYS_TO_START = [
    pytest.param(["__main__.py"], SRC, id="inside src: python __main__.py"),
    pytest.param(["."], SRC, id="inside src: python ."),
    pytest.param(["cli.py"], SRC, id="inside src: python cli.py"),
    pytest.param(["src"], ROOT, id="inside 8D: python src"),
    pytest.param(
        [str(Path("src") / "__main__.py")], ROOT, id="inside 8D: python src/__main__.py"
    ),
    pytest.param(
        [str(Path("src") / "cli.py")], ROOT, id="inside 8D: python src/cli.py"
    ),
    pytest.param(["-m", "src"], ROOT, id="inside 8D: python -m src"),
    pytest.param([str(SRC)], ROOT.anchor, id="anywhere: python <full path to src>"),
]


@pytest.mark.parametrize(("start", "folder"), WAYS_TO_START)
def test_runs_without_installing(start: list[str], folder: Path) -> None:
    # -S hides site-packages, so an installed copy can't make this pass by accident
    result = subprocess.run(
        [sys.executable, "-S", *start, "--help"],
        cwd=folder,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "usage: audio8d" in result.stdout
