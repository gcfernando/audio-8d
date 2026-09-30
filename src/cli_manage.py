# Developed by ::> Gehan Fernando
"""The command line's housekeeping: saved styles, the add-on, cache and logs.

These do what the window's Your styles and Settings pages do, with the same
checks and the same rules for names, so a style made either way is the same.
"""

import argparse
import logging
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from . import addons, display, hints
from .analysis.stems import clear_stems_cache
from .core.errors import Audio8DError, InputValidationError
from .core.locations import cache_dir, presets_file
from .core.presets import RECOMMENDED_PRESET
from .core.settings import EffectConfig
from .core.style_files import export_style, import_style, read_style_file
from .core.user_presets import (
    delete_user_preset,
    duplicate_user_preset,
    find_style,
    pascal_case,
    rename_user_preset,
    save_user_preset,
    update_user_preset,
)
from .display_health import show_addon
from .logs import delete_log_files
from .options import known_presets
from .style_creator import style_check

LOG = logging.getLogger("audio8d")


def explain(painter: display.Painter, error: Audio8DError) -> None:
    """Known problems get a one-line message and a plain fix, never a traceback."""
    LOG.error("%s", error)
    fix = hints.fix_for(error)
    if fix:
        display.show_fix(painter, fix)


def check_style_options(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    """Usage mistakes with the saved-style options, before anything is done."""
    if args.import_style and len(args.import_style) > 2:
        parser.error("--import-style takes a FILE and, if you like, a NAME")
    if args.save_preset and args.update_style:
        parser.error("use --save-style or --update-style, not both")
    if args.style_description is not None and not (
        args.save_preset or args.update_style
    ):
        parser.error("--style-description goes with --save-style or --update-style")
    if args.update_style and args.preset is None:
        # Updating a style starts from that style, not from the default one
        try:
            args.preset = saved_style(args.update_style)
        except Audio8DError:
            # update_style() explains an unknown name when it gets there
            pass


def _style_checked(
    painter: display.Painter, config: EffectConfig, summary: str
) -> bool:
    """The window's quality check for a saved style: errors stop, warnings are shown."""
    notes = style_check(config, summary)
    for note in notes:
        if note.level == "error":
            LOG.error("The style was not saved: %s", note.text)
            return False
    for note in notes:
        if note.level == "warning":
            painter.line(painter.paint(f"  Heads-up: {note.text}", "yellow"))
    return True


def save_style(args: argparse.Namespace, config: EffectConfig) -> int:
    """--save-style: save the typed sound settings as a new style and say where."""
    painter = display.Painter(sys.stderr)
    based_on = args.preset or RECOMMENDED_PRESET
    summary = (
        args.style_description
        if args.style_description is not None
        else f"your style, based on {based_on}"
    )
    try:
        if not _style_checked(painter, config, summary):
            return 1
        # Names become PascalCase ('party mix' -> 'PartyMix'), and never replace one
        name = save_user_preset(
            args.save_preset, config, based_on=based_on, summary=summary
        )
    except Audio8DError as exc:
        explain(painter, exc)
        return 1
    painter.line(
        "  "
        + painter.paint(f"Saved your style '{name}'", "bold", "green")
        + painter.paint(f" in {presets_file()}", "green")
    )
    painter.line(f'  Use it with: audio8d "My Song.mp3" --style "{name}"')
    return 0


def saved_style(name: str) -> str:
    """The stored name of one of your saved styles, or a plain reason why not."""
    known = known_presets()
    found = find_style(name, known)
    if found is not None and not known[found].custom:
        raise InputValidationError(
            f"'{found}' is a built-in style, and only your own saved styles can be "
            f"changed. Save a copy first: --style {found} --save-style NEW_NAME"
        )
    if found is None:
        raise InputValidationError(
            f"There is no saved style called '{name}'; see them all with --list-styles"
        )
    return found


def update_style(args: argparse.Namespace, config: EffectConfig) -> int:
    """--update-style: save the sound settings into one of your saved styles."""
    painter = display.Painter(sys.stderr)
    try:
        name = saved_style(args.update_style)
        summary = args.style_description
        kept = known_presets()[name].summary if summary is None else summary
        if not _style_checked(painter, config, kept):
            return 1
        name = update_user_preset(name, config, summary=summary)
    except Audio8DError as exc:
        explain(painter, exc)
        return 1
    painter.line("  " + painter.paint(f"Saved your style '{name}'", "bold", "green"))
    return 0


def _style_action(args: argparse.Namespace) -> str | None:
    """Rename, copy, delete, export or import a style; what was done, or None."""
    if args.rename_style:
        old, new = args.rename_style
        old = saved_style(old)
        return f"Renamed '{old}' to '{rename_user_preset(old, new)}'"
    if args.duplicate_style:
        old, new = args.duplicate_style
        old = saved_style(old)
        return f"Made '{duplicate_user_preset(old, new)}', a copy of '{old}'"
    if args.delete_style:
        name = saved_style(args.delete_style)
        delete_user_preset(name)
        return f"Deleted your style '{name}' (songs already made are not touched)"
    if args.export_style:
        name, file = args.export_style
        known = known_presets()
        found = find_style(name, known)
        if found is None:
            raise InputValidationError(
                f"There is no style called '{name}'; see them all with --list-styles"
            )
        return f"Exported '{found}' to {export_style(known[found], Path(file))}"
    if args.import_style:
        file = Path(args.import_style[0])
        # The file is checked in full first; its own name is used unless one is typed
        style = read_style_file(file)
        if len(args.import_style) > 1:
            wanted = args.import_style[1]
        else:
            wanted = pascal_case(style.name)
            taken = find_style(wanted, known_presets())
            if taken is not None:
                raise InputValidationError(
                    f"There is already a style called '{taken}'; give the imported "
                    f'one a name of its own: --import-style "{file}" "{wanted} 2"'
                )
        return f"Imported '{import_style(file, wanted)}' from {file.name}"
    return None


def run_style_action(args: argparse.Namespace) -> int | None:
    """Rename, copy, delete, export or import a saved style, then stop."""
    painter = display.Painter(sys.stderr)
    try:
        done = _style_action(args)
    except Audio8DError as exc:
        explain(painter, exc)
        return 1
    if done is None:
        return None
    painter.line("  " + painter.paint(done, "bold", "green"))
    return 0


def run_clear_cache() -> int:
    """--clear-cache: forget remembered loudness measurements and singer splits."""
    painter = display.Painter(sys.stdout)
    failed = []
    try:
        (cache_dir() / "loudness.json").unlink(missing_ok=True)
    except OSError:
        failed.append("the remembered loudness measurements")
    try:
        clear_stems_cache()
    except OSError:
        failed.append("the remembered singer splits")
    if failed:
        painter.line(
            painter.paint(
                f"  Could not delete {' or '.join(failed)} in {cache_dir()}; close "
                "Audio8D's window and try again.",
                "red",
            )
        )
        return 1
    painter.line(
        painter.paint(
            "  Remembered measurements and singer splits cleared; they are made "
            "again when needed.",
            "green",
        )
    )
    return 0


def run_delete_logs() -> int:
    """--delete-logs: delete the saved technical log files."""
    painter = display.Painter(sys.stdout)
    deleted, failed = delete_log_files()
    if failed:
        painter.line(
            painter.paint(
                f"  Could not delete {', '.join(str(path) for path in failed)}; it "
                "may be open in another program.",
                "red",
            )
        )
        return 1
    painter.line(
        painter.paint(
            f"  Deleted {deleted} log file{'s' if deleted != 1 else ''}."
            if deleted
            else "  There were no saved log files to delete.",
            "green",
        )
    )
    return 0


def run_addon_status() -> int:
    """--addon-status: is the singer add-on installed? (exit code 0 = installed)."""
    painter = display.Painter(sys.stdout)
    painter.line(painter.paint("  Checking the singer add-on...", "dim"))
    status = addons.singer_status(refresh=True)
    show_addon(painter, status)
    return 0 if status.ready else 1


def _addon_python(painter: display.Painter) -> Path | None:
    """The Python that builds the add-on's folder, or None after saying why not."""
    found = addons.find_python(addons.preferred_python())
    if found.ok and found.path is not None:
        return found.path
    painter.line(painter.paint(f"  {found.problem}", "red"))
    display.show_fix(painter, addons.AddonStatus(found).fix())
    return None


def _addon_progress(
    painter: display.Painter,
) -> Callable[[addons.AddonProgress], None]:
    """Print add-on progress as it changes: every 5%, or when the stage changes."""
    # The last stage printed and its 5% step (-1 while unmeasured)
    shown: list[tuple[str, int]] = [("", -1)]
    lock = threading.Lock()

    def show(progress: addons.AddonProgress) -> None:
        """Print one report, unless it only moves a little within the same stage."""
        percent = progress.percent
        step = -1 if percent is None else percent // 5
        with lock:
            stage, before = shown[0]
            if stage == progress.stage and step <= before and not progress.finished:
                return
            shown[0] = (progress.stage, step)
        detail = f"  {progress.detail}" if progress.detail else ""
        colour = "red" if progress.failed else "green" if progress.finished else "cyan"
        painter.line("  " + painter.paint(progress.words(), colour) + detail)

    return show


def run_install_addon(repair: bool = False) -> int:
    """--install-addon / --repair-addon: set up the add-on's folder, then check it."""
    painter = display.Painter(sys.stdout)
    status = addons.singer_status(refresh=True)
    if status.ready and not repair:
        painter.line(
            painter.paint("  The add-on is already installed; nothing to do.", "green")
        )
        show_addon(painter, status)
        return 0
    python = _addon_python(painter)
    if python is None:
        return 1
    painter.line(
        "  "
        + painter.paint(
            "Repairing the singer add-on" if repair else "Installing the singer add-on",
            "bold",
            "cyan",
        )
        + f" into {addons.addon_dir()}"
    )
    painter.line(
        painter.paint(
            "  About 1 GB is downloaded; this takes a few minutes. Ctrl+C stops it.",
            "dim",
        )
    )
    cancel = threading.Event()
    job = addons.repair_addon if repair else addons.install_addon
    try:
        worked, tail = job(
            python,
            lambda line: painter.line(painter.paint(f"    {line}", "dim")),
            cancel,
            on_progress=_addon_progress(painter),
        )
    except KeyboardInterrupt:
        cancel.set()
        painter.line(painter.paint("  Stopped. Nothing half-made was kept.", "yellow"))
        return 1
    # A finished install has just checked the add-on, so that answer is reused
    status = addons.singer_status()
    if worked and status.ready:
        show_addon(painter, status)
        return 0
    painter.line(painter.paint("  The add-on is not ready: " + status.summary(), "red"))
    if not worked:
        painter.line(painter.paint("  What happened:", "dim"))
        for line in tail.splitlines()[-8:]:
            painter.line(painter.paint(f"    {line}", "dim"))
    display.show_fix(painter, status.fix())
    return 1


def run_uninstall_addon() -> int:
    """--uninstall-addon: delete the add-on's own folder (Audio8D keeps working)."""
    painter = display.Painter(sys.stdout)
    worked, message = addons.uninstall_addon(on_progress=_addon_progress(painter))
    painter.line(painter.paint(f"  {message}", "green" if worked else "red"))
    if worked:
        painter.line(
            "  Audio8D works as before; only 'Keep the singer in the middle' "
            "(--vocals center) needs the add-on."
        )
    return 0 if worked else 1


def run_setup_task(args: argparse.Namespace) -> int | None:
    """The add-on options, --clear-cache or --delete-logs; None when none was typed."""
    if args.clear_cache:
        return run_clear_cache()
    if args.delete_logs:
        return run_delete_logs()
    if args.addon_status:
        return run_addon_status()
    if args.install_addon or args.repair_addon:
        return run_install_addon(repair=args.repair_addon)
    if args.uninstall_addon:
        return run_uninstall_addon()
    return None
