# Developed by ::> Gehan Fernando
"""Every `audio8d` command shown in README.md must be one the command line accepts.

The guide's examples are part of the product: if an option is renamed or removed,
this test fails and names the example that no longer works.
"""

import re
import shlex
from pathlib import Path

import pytest

from src.core.errors import InputValidationError
from src.options import create_parser
from src.per_song import parse_line

README = Path(__file__).resolve().parents[2] / "README.md"
# Code blocks of commands (powershell) and of --per-song files (text)
_BLOCK = re.compile(r"```(powershell|text)\n(.*?)```", re.DOTALL)


def _commands() -> list[str]:
    """Every line in a command block that starts with `audio8d`."""
    found = []
    for kind, body in _BLOCK.findall(README.read_text(encoding="utf-8")):
        if kind != "powershell":
            continue
        for line in body.splitlines():
            command = line.split("  #", 1)[0].strip()
            if command.startswith("audio8d ") or command == "audio8d":
                found.append(command)
    return found


def _inline_commands() -> list[str]:
    """Commands written inside the text, e.g. `audio8d "My Song.mp3" --preview 20`."""
    text = README.read_text(encoding="utf-8")
    return [c for c in re.findall(r"`(audio8d [^`]+)`", text) if "PATH" not in c]


def _words(command: str) -> list[str]:
    """The command's arguments, as the terminal would pass them."""
    # posix=False keeps Windows backslashes; the quotes are then taken off
    return [word.strip('"') for word in shlex.split(command, posix=False)[1:]]


def test_the_guide_shows_commands_for_every_common_task() -> None:
    shown = " ".join(_commands())
    for option in ("--style", "--format", "--loudness", "--movement", "--preview",
                   "--per-song", "--addon-status", "--install-addon",
                   "--uninstall-addon", "--help", "--check"):  # fmt: skip
        assert option in shown, option


@pytest.mark.parametrize("command", sorted(set(_commands() + _inline_commands())))
def test_every_command_in_the_guide_is_accepted(command: str) -> None:
    parser = create_parser()
    parser.raise_errors = True  # type: ignore[attr-defined]
    words = _words(command)
    if any(word in ("--help", "--version", "--list-styles") for word in words):
        # These print and stop; argparse must still know them
        assert any(word in parser.format_help() for word in words)
        return
    try:
        parser.parse_args(words)
    except InputValidationError as exc:
        pytest.fail(f"README command no longer works: {command}\n{exc}")


def test_every_per_song_line_in_the_guide_is_accepted() -> None:
    lines = []
    for kind, body in _BLOCK.findall(README.read_text(encoding="utf-8")):
        if kind == "text" and "--" in body and "Created in" not in body:
            lines += [line for line in body.splitlines() if line.strip()]
    assert lines
    for number, line in enumerate(lines, start=1):
        parse_line(line, number)
