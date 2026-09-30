# Developed by ::> Gehan Fernando
"""The system check: every dependency's state, what blocks converting, and fixes."""

import sys
from pathlib import Path

import pytest

from src import health
from src.addons import SINGER_PACKAGES, AddonStatus, PackageCheck, PythonCheck
from src.ffmpeg import ToolCheck, ToolLocation


def _tools(monkeypatch: pytest.MonkeyPatch, **states: str) -> None:
    """Pretend ffmpeg/ffprobe are 'ok', 'missing' or 'broken'."""

    def locate(name: str) -> ToolLocation:
        if states.get(name) == "missing":
            return ToolLocation(name, None, "missing")
        return ToolLocation(name, Path(f"C:/tools/{name}.exe"), "configured")

    def check(name: str, path: Path | None) -> ToolCheck:
        state = states.get(name, "ok")
        if state == "ok":
            return ToolCheck(name, path, True, version="7.1")
        if state == "missing":
            return ToolCheck(name, None, False, problem=f"{name} was not found. Fix.")
        return ToolCheck(name, path, False, problem=f"{name}.exe can't be started.")

    monkeypatch.setattr(health, "locate", locate)
    monkeypatch.setattr(health, "check_tool", check)
    monkeypatch.setattr(health, "missing_features", lambda _toolchain: None)


def _item(report: health.HealthReport, key: str) -> health.Dependency:
    """One dependency of a report, which must be there."""
    item = report.get(key)
    assert item is not None, key
    return item


def _addon(*oks: bool, python_ok: bool = True, configured: bool = False):
    python = PythonCheck(
        Path(sys.executable) if python_ok or configured else None,
        python_ok,
        "configured" if configured else "running",
        "3.12.1" if python_ok else "",
        "" if python_ok else "No Python was found on this computer.",
    )
    packages = tuple(
        PackageCheck(p, ok, problem="" if ok else "not installed")
        for p, ok in zip(SINGER_PACKAGES, oks, strict=False)
    )
    return AddonStatus(python, packages if python_ok else ())


def test_everything_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    _tools(monkeypatch)
    monkeypatch.setattr(
        health, "check_singer", lambda _p=None: _addon(True, *[True] * 3)
    )
    report = health.check_environment(window=True)

    assert report.ok and report.singer_ready and report.problem() is None
    assert all(item.state == health.READY for item in report.items)
    assert _item(report, "ffmpeg").required and not _item(report, "singer").required


def test_missing_and_broken_tools_block_converting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _tools(monkeypatch, ffmpeg="missing", ffprobe="broken")
    report = health.check_environment(addon=False)

    assert not report.ok
    assert _item(report, "ffmpeg").state == health.MISSING
    assert _item(report, "ffprobe").state == health.INVALID
    assert [item.key for item in report.blocking] == ["ffmpeg", "ffprobe"]
    assert (
        "FFmpeg" in str(report.problem()) and "--ffmpeg" in _item(report, "ffmpeg").fix
    )


def test_a_build_without_the_needed_features_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _tools(monkeypatch)
    monkeypatch.setattr(health, "missing_features", lambda _t: "no ebur128 filter")
    report = health.check_environment(addon=False)

    assert _item(report, "ffmpeg").state == health.INVALID
    assert _item(report, "ffmpeg").detail == "no ebur128 filter"


def test_the_optional_add_on_never_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    _tools(monkeypatch)
    for status, python_state, singer_state in (
        (_addon(python_ok=False), health.OPTIONAL, health.UNAVAILABLE),
        (
            _addon(python_ok=False, configured=True),
            health.INVALID,
            health.UNAVAILABLE,
        ),
        (_addon(False, False, True), health.READY, health.OPTIONAL),
        (_addon(True, False, True), health.READY, health.INVALID),
    ):
        monkeypatch.setattr(health, "check_singer", lambda _p=None, s=status: s)
        report = health.check_environment()
        assert report.ok and not report.singer_ready
        assert _item(report, "python").state == python_state
        assert _item(report, "singer").state == singer_state
        assert _item(report, "singer").fix


def test_window_packages_are_required_only_for_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(health.importlib.util, "find_spec", lambda _name: None)

    assert health.check_window_packages(True).state == health.MISSING
    assert health.check_window_packages(False).state == health.OPTIONAL
    assert "customtkinter" in health.check_window_packages(True).fix


def test_every_state_has_words() -> None:
    for state in (
        health.READY,
        health.MISSING,
        health.INVALID,
        health.OPTIONAL,
        health.UNAVAILABLE,
    ):
        item = health.Dependency("x", "X", False, state, "summary")
        assert item.state_words == health.STATE_WORDS[state]
        assert item.ok == (state == health.READY)
