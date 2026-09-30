# Developed by ::> Gehan Fernando
"""The terminal's system check (audio8d --check) and add-on status (--addon-status)."""

import textwrap

from .addons import ADDON_INFO, AddonStatus
from .core.locations import addon_dir
from .display import Painter, show_fix
from .health import HealthReport

# How each state is marked: a symbol (and a plain one), then colour on top
_HEALTH_LOOKS = {
    "ready": ("✓", "+", "green"),
    "missing": ("✗", "x", "red"),
    "invalid": ("✗", "x", "red"),
    "optional": ("○", "-", "yellow"),
    "unavailable": ("○", "-", "yellow"),
}


def show_health(painter: Painter, report: HealthReport, verbose: bool = False) -> None:
    """The dependency check as a table: required things first, then optional ones."""
    painter.line()
    painter.line("  " + painter.paint("Audio8D system check", "bold", "cyan"))
    painter.rule()
    for required in (True, False):
        items = [item for item in report.items if item.required == required]
        if not items:
            continue
        title = "Required" if required else "Optional (Audio8D works without these)"
        painter.line("  " + painter.paint(title, "bold"))
        for item in items:
            mark, plain, color = _HEALTH_LOOKS[item.state]
            symbol = mark if painter.fancy else plain
            status = painter.paint(f"{symbol} {item.state_words:<22}", color, "bold")
            painter.line(f"   {status} {item.name:<16} {item.summary}")
            if item.purpose:
                painter.line(painter.paint(f"{'':29}Used to {item.purpose}.", "dim"))
            if item.fix and not item.ok:
                painter.line(f"{'':29}{painter.paint('Fix:', 'yellow')} {item.fix}")
            if verbose and item.detail:
                for detail in item.detail.splitlines():
                    painter.line(painter.paint(f"{'':29}{detail}", "dim"))
        painter.line()
    painter.rule()
    if report.ok:
        painter.line(
            "  "
            + painter.paint("Everything required is ready.", "bold", "green")
            + (
                " The singer add-on is ready too."
                if report.singer_ready
                else " Optional add-ons can be set up any time."
            )
        )
    else:
        painter.line(
            "  "
            + painter.paint("Audio8D can't create songs yet: ", "bold", "red")
            + ", ".join(item.name for item in report.blocking)
            + " must be fixed first."
        )
    if not verbose:
        painter.line(painter.paint("  Add --verbose for the technical details.", "dim"))


def show_addon(painter: Painter, status: AddonStatus) -> None:
    """The singer add-on: installed or not, what it is, and what to do next."""
    color = "green" if status.ready else "yellow"
    painter.line()
    painter.line(
        "  "
        + painter.paint("Singer add-on: ", "bold", "cyan")
        + painter.paint(status.words, "bold", color)
    )
    painter.line(f"  {status.summary()}")
    if status.private:
        painter.line(painter.paint(f"  Location: {addon_dir()}", "dim"))
    elif status.ready and status.python.path is not None:
        painter.line(
            painter.paint(f"  In your own Python: {status.python.path}", "dim")
        )
    painter.line()
    for title, text in ADDON_INFO:
        painter.line("  " + painter.paint(title, "bold"))
        for line in textwrap.wrap(text, 74):
            painter.line(f"    {line}")
    painter.line()
    if status.ready:
        painter.line(
            "  Use it with --vocals center. Remove it with: audio8d --uninstall-addon"
        )
    else:
        show_fix(painter, status.fix())
