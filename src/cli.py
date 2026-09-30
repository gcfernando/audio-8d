# Developed by ::> Gehan Fernando
"""The `audio8d` command-line tool."""

import argparse
import dataclasses
import logging
import runpy
import sys
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

if __name__ == "__main__" and not __package__:
    # `python cli.py` without installing: __main__.py sets up the package and runs it
    runpy.run_path(str(Path(__file__).with_name("__main__.py")), run_name="__main__")

# pylint: disable=wrong-import-position
from . import __version__, addons, display, guided, hints, launcher
from .batch import (
    BatchItem,
    BatchOutcome,
    default_jobs,
    progress_tracker,
    run_batch,
)
from .core.errors import Audio8DError, DependencyError, InputValidationError
from .core.locations import presets_file
from .core.preferences import load_preferences
from .core.presets import LEGACY_STYLES, RECOMMENDED_PRESET, Preset
from .core.settings import (
    EffectConfig,
)
from .core.types import AudioStreamInfo, Trim
from .core.user_presets import save_user_preset
from .display_health import show_addon, show_health
from .ffmpeg import FFmpegToolchain, probe_audio, set_preferred_paths
from .files import (
    default_output_for,
    find_songs,
    resolve_input,
)
from .health import check_environment
from .logs import start_log_file
from .opener import open_path as open_in_player
from .options import (
    create_parser,
    known_presets,
    resolve_config,
    used_only_defaults,
)
from .per_song import SongRule, merged, read_rules, rules_for
from .pipeline import (
    ConvertOptions,
    compare,
    convert,
    preview,
    stages_for,
)
from .player import PLAYING, Player, PlayerError
from .previews import make_preview, temporary_folder
from .song_settings import needs_singer, song_convert_options, song_effect

# pylint: enable=wrong-import-position

LOG = logging.getLogger("audio8d")

# The helper's path cleaner, kept under its old name for existing callers
_clean_typed_path = guided.clean_typed_path


def configure_logging(verbose: bool) -> None:
    """Short messages normally; timestamps and pipeline details with --verbose."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
        if verbose
        else "%(levelname)s %(name)s: %(message)s",
        # The windowed exe has no console to print to
        handlers=None if sys.stderr is not None else [logging.NullHandler()],
    )
    if not verbose:
        # The panel already says what the pipeline is doing; the log file still gets it
        quiet = convert.__module__
        for handler in logging.getLogger().handlers:
            if not getattr(handler, "audio8d_quiet", False) and not getattr(
                handler, "audio8d_file", False
            ):
                handler.addFilter(
                    lambda record: (
                        record.levelno >= logging.WARNING or record.name != quiet
                    )
                )
                handler.audio8d_quiet = True  # type: ignore[attr-defined]
    start_log_file()


def _explain(painter: display.Painter, error: Audio8DError) -> None:
    """Known problems get a one-line message and a plain fix, never a traceback."""
    LOG.error("%s", error)
    fix = hints.fix_for(error)
    if fix:
        display.show_fix(painter, fix)


def use_saved_tools() -> None:
    """Use the FFmpeg, FFprobe and Python chosen in the window's Settings, if any."""
    preferences, _problem = load_preferences()
    set_preferred_paths(*preferences.tools())
    addons.set_preferred_python(preferences.python())


def use_typed_tools(args: argparse.Namespace) -> None:
    """--ffmpeg, --ffprobe and --python win over Settings, for this run only."""
    if args.ffmpeg is not None or args.ffprobe is not None:
        preferences, _problem = load_preferences()
        saved = preferences.tools()
        set_preferred_paths(args.ffmpeg or saved[0], args.ffprobe or saved[1])
    if args.python is not None:
        addons.set_preferred_python(args.python)


def _peek_source(input_path: Path) -> AudioStreamInfo | None:
    """Read the song's details for the panel; convert() reports any problem later."""
    try:
        return probe_audio(FFmpegToolchain.discover(), resolve_input(input_path))
    except Audio8DError:
        return None


@dataclasses.dataclass(frozen=True, slots=True)
class Plan:  # pylint: disable=too-many-instance-attributes
    """Everything decided before any work starts, shared by all the run modes."""

    config: EffectConfig
    preset: str | None
    options: ConvertOptions
    overwrite: bool = False
    output_dir: Path | None = None
    name_style: str = "8d"
    jobs: int = 1
    recursive: bool = False
    play: bool = False
    show_tip: bool = False
    presets: dict[str, Preset] = dataclasses.field(default_factory=dict)
    # The default before 'Safe for speakers too', and whether that is on
    default: EffectConfig | None = None
    speakers: bool = False
    # Lines of the --per-song file
    rules: tuple[SongRule, ...] = ()


def song_setup(song: Path, plan: Plan) -> tuple[EffectConfig, ConvertOptions]:
    """One song's settings: the run's, plus its own lines from --per-song."""
    matching = rules_for(song, list(plan.rules))
    if not matching:
        return plan.config, plan.options
    style, changes = merged(matching)
    if style in LEGACY_STYLES:
        # An older style name brings its old file settings; the line's own still win
        style, extra = LEGACY_STYLES[style]
        changes = {**extra, **changes}
    lines = ", ".join(str(rule.line) for rule in matching)
    try:
        config = song_effect(
            plan.default or plan.config,
            default_speakers=plan.speakers,
            style=plan.presets[style].config if style else None,
            changes=changes,
        )
        options = song_convert_options(plan.options, changes) or plan.options
    except Audio8DError as exc:
        raise InputValidationError(
            f"The per-song settings for {song.name} (line {lines}) can't be used: {exc}"
        ) from None
    return config, options


def _output_for(
    song: Path,
    plan: Plan,
    relative_to: Path | None = None,
    config: EffectConfig | None = None,
) -> Path:
    """Where one song's 8D copy is saved (its own file type decides the ending)."""
    return default_output_for(
        song,
        (config or plan.config).extension,
        output_dir=plan.output_dir,
        name_style=plan.name_style,
        relative_to=relative_to,
    )


def check_singer(configs: Sequence[tuple[str, EffectConfig]]) -> None:
    """Refuse to start when songs need the singer add-on and it isn't ready.

    Audio8D never quietly makes those songs without it: that would sound different
    from what was asked for.
    """
    wanted = [name for name, config in configs if needs_singer(config)]
    if not wanted:
        return
    status = addons.singer_status()
    if status.ready:
        return
    names = ", ".join(wanted[:3]) + (" and others" if len(wanted) > 3 else "")
    raise DependencyError(
        f"Keeping the singer in the middle needs the singer add-on (for {names}). "
        f"{status.summary()} {status.fix()}"
    )


def run_single(
    input_path: Path, output_path: Path, plan: Plan, *, banner: bool = True
) -> int:
    """Show the settings, convert one file, and turn known problems into exit code 1."""
    painter = display.Painter(sys.stderr)

    # A missing or empty song is the most common slip, so say so before the whole panel
    try:
        resolve_input(input_path)
        config, options = song_setup(input_path, plan)
        check_singer([(input_path.name, config)])
    except Audio8DError as exc:
        _explain(painter, exc)
        return 1

    display.show_settings(
        painter,
        version=__version__,
        song_in=input_path,
        song_out=output_path,
        preset=plan.preset,
        config=config,
        banner=banner,
        source=_peek_source(input_path),
        trim=options.trim,
        presets=plan.presets or None,
    )
    if config != plan.config or options != plan.options:
        painter.line(
            painter.paint("  This song has settings of its own (--per-song).", "cyan")
        )

    progress_bar = display.ProgressBar(painter)
    started = time.perf_counter()
    try:
        result = convert(
            input_path=input_path,
            output_path=output_path,
            config=config,
            overwrite=plan.overwrite,
            options=options,
            on_progress=progress_bar.update,
        )
    except Audio8DError as exc:
        progress_bar.finish()
        _explain(painter, exc)
        return 1
    progress_bar.finish()

    display.show_result(painter, result, time.perf_counter() - started)
    if result.original_removed_to:
        display.show_removed(painter, input_path, result.original_removed_to)
    display.show_listen(painter)
    if plan.show_tip:
        display.show_tip(painter)
    if plan.play:
        open_in_player(result.output)
    return 0


def _split_existing(
    found: list[Path], plan: Plan, folder: Path
) -> tuple[list[BatchItem], list[Path]]:
    """Songs still to make, and 8D copies that already exist (skipped)."""
    items: list[BatchItem] = []
    skipped: list[Path] = []
    for song in found:
        config, options = song_setup(song, plan)
        output = _output_for(song, plan, relative_to=folder, config=config)
        replacing_itself = plan.options.replace_original and output == song
        if output.exists() and not plan.overwrite and not replacing_itself:
            skipped.append(output)
        else:
            items.append(
                BatchItem(
                    song,
                    output,
                    config if config != plan.config else None,
                    options if options != plan.options else None,
                )
            )
    return items, skipped


def _batch_display(
    painter: display.Painter, plan: Plan, count: int
) -> tuple[
    display.BatchBar,
    Callable[[int, str, float], None],
    Callable[[int, BatchOutcome], None],
]:
    """The overall bar plus the two callbacks that keep it up to date."""
    stages = stages_for(plan.options)
    update, overall = progress_tracker(count, stages)
    progress_bar = display.BatchBar(painter, count)
    progress_bar.draw(0.0)

    def on_progress(index: int, stage: str, share: float) -> None:
        """Fold one song's progress into the overall bar."""
        update(index, stage, share)
        progress_bar.draw(overall())

    def on_done(_index: int, outcome: BatchOutcome) -> None:
        """Print the finished song's line above the bar."""
        number = progress_bar.finished + 1
        progress_bar.song_line(display.batch_line(painter, number, count, outcome))

    return progress_bar, on_progress, on_done


def run_folder(  # pylint: disable=too-many-locals
    folder: Path, plan: Plan, *, banner: bool = True, songs: list[Path] | None = None
) -> int:
    """Convert every song in a folder, several at once, then show the totals."""
    painter = display.Painter(sys.stderr)
    try:
        found = (
            songs if songs is not None else find_songs(folder, recursive=plan.recursive)
        )
        if not found:
            raise InputValidationError(f"No songs found in {folder}")
        items, skipped = _split_existing(found, plan, folder)
        check_singer([(item.source.name, item.config or plan.config) for item in items])
    except Audio8DError as exc:
        _explain(painter, exc)
        return 1

    display.show_settings(
        painter,
        version=__version__,
        song_in=folder,
        song_out=plan.output_dir or Path("next to each original"),
        preset=plan.preset,
        config=plan.config,
        banner=banner,
        trim=plan.options.trim,
        presets=plan.presets or None,
    )
    own = sum(1 for item in items if item.config or item.options)
    if own:
        painter.line(
            painter.paint(
                f"  {own} song{' uses' if own == 1 else 's use'} settings of their "
                "own from the per-song file.",
                "cyan",
            )
        )
    for rule in plan.rules:
        if not any(rule.matches(song) for song in found):
            painter.line(
                painter.paint(
                    f"  Per-song line {rule.line} ('{rule.pattern}') matched no song.",
                    "yellow",
                )
            )
    for path in skipped:
        painter.line(painter.paint(f"  Skipped (already made): {path.name}", "dim"))
    if not items:
        painter.line(
            painter.paint(
                "  Nothing new to create. Add --overwrite to make them again.", "yellow"
            )
        )
        return 0
    display.show_batch_plan(
        painter, len(items), plan.jobs, plan.output_dir, plan.options.replace_original
    )

    progress_bar, on_progress, on_done = _batch_display(painter, plan, len(items))
    cancel = threading.Event()
    try:
        report = run_batch(
            items,
            plan.config,
            options=plan.options,
            overwrite=plan.overwrite,
            jobs=plan.jobs,
            on_progress=on_progress,
            on_done=on_done,
            cancel=cancel,
        )
    except KeyboardInterrupt:
        cancel.set()
        progress_bar.close()
        painter.line(
            painter.paint("  Stopped. Songs already finished are kept.", "yellow")
        )
        return 1
    progress_bar.close()
    display.show_batch_summary(painter, report)
    for outcome in report.failed:
        assert outcome.error is not None
        fix = hints.fix_for(outcome.error)
        if fix:
            painter.line(painter.paint(f"  {outcome.item.source.name}: ", "dim") + fix)
    if report.converted:
        display.show_listen(painter)
    if plan.play and report.converted:
        open_in_player(report.converted[0].result.output)  # type: ignore[union-attr]
    return 1 if report.failed else 0


def _listen(painter: display.Painter, file: Path, seconds: float) -> None:
    """Play a temporary sample and wait until it ends, Enter is pressed or Ctrl+C."""
    player = Player()
    try:
        player.load(file)
        player.play(from_start=True)
    except PlayerError as exc:
        LOG.warning("Could not play %s: %s", file.name, exc)
        return
    if not player.built_in:
        # Another program is playing it; give it the sample's length to finish
        painter.line(painter.paint("  Playing in your music player...", "cyan"))
        _wait(lambda: False, seconds + 5)
        return
    painter.line(painter.paint("  Playing... press Enter (or Ctrl+C) to stop.", "cyan"))
    try:
        _wait(lambda: player.state() != PLAYING, seconds + 5)
    except KeyboardInterrupt:
        pass
    finally:
        player.close()


def _wait(done: Callable[[], bool], longest: float) -> None:
    """Wait until done() is true, Enter is pressed, or longest seconds have gone."""
    pressed = threading.Event()
    if sys.stdin is not None and sys.stdin.isatty():

        def read() -> None:
            try:
                sys.stdin.readline()
            except (OSError, ValueError):
                return
            pressed.set()

        threading.Thread(target=read, name="wait-enter", daemon=True).start()
    ends = time.monotonic() + longest
    # A short grace period lets the player report that it has started
    time.sleep(0.3)
    while not pressed.is_set() and not done() and time.monotonic() < ends:
        time.sleep(0.2)


def run_preview(
    input_path: Path, plan: Plan, seconds: float, output: Path | None, kind: str
) -> int:
    """Listen to a short sample (or A/B file); it is kept only when OUTPUT is given.

    Without an OUTPUT the sample is made in a private temporary folder, played,
    and deleted afterwards whatever happens; nothing is written near your music.
    """
    painter = display.Painter(sys.stderr)
    progress_bar = display.ProgressBar(painter)
    try:
        resolve_input(input_path)
        config, _options = song_setup(input_path, plan)
        check_singer([(input_path.name, config)])
        display.show_settings(
            painter,
            version=__version__,
            song_in=input_path,
            song_out=output or Path("a temporary file, deleted afterwards"),
            preset=plan.preset,
            config=config,
            source=_peek_source(input_path),
            presets=plan.presets or None,
        )
        what = (
            "the ORIGINAL (A), a short pause, then the 8D version (B), same loudness"
            if kind == "compare"
            else f"{seconds:g} s from the loudest part"
        )
        painter.line(painter.paint(f"  Preview: {what}.", "cyan"))
        started = time.perf_counter()
        if output is not None:
            # An OUTPUT file was asked for, so this sample is kept on purpose
            if kind == "compare":
                compare(input_path, output, config, on_progress=progress_bar.update)
            else:
                preview(
                    input_path,
                    output,
                    config,
                    seconds=seconds,
                    on_progress=progress_bar.update,
                )
            progress_bar.finish()
            display.show_done(painter, output, time.perf_counter() - started)
            if plan.play:
                open_in_player(output)
            return 0
        with temporary_folder() as folder:
            file = make_preview(
                input_path,
                folder,
                config,
                seconds=seconds,
                kind=kind,
                on_progress=progress_bar.update,
            )
            progress_bar.finish()
            _listen(painter, file, seconds if kind == "preview" else 40.0)
        painter.line(
            painter.paint(
                "  Done. The preview was deleted; run without --preview to create "
                "the song.",
                "dim",
            )
        )
    except Audio8DError as exc:
        progress_bar.finish()
        _explain(painter, exc)
        return 1
    except KeyboardInterrupt:
        progress_bar.finish()
        painter.line(painter.paint("  Stopped. Nothing was kept.", "yellow"))
        return 1
    return 0


def _save_preset(args: argparse.Namespace, config: EffectConfig) -> int:
    """Save the typed settings as a named style and say where."""
    painter = display.Painter(sys.stderr)
    try:
        # Names become PascalCase ('party mix' -> 'PartyMix'), and never replace one
        name = save_user_preset(
            args.save_preset,
            config,
            based_on=args.preset or RECOMMENDED_PRESET,
            summary=f"your style, based on {args.preset or RECOMMENDED_PRESET}",
        )
    except Audio8DError as exc:
        _explain(painter, exc)
        return 1
    painter.line(
        "  "
        + painter.paint(f"Saved your style '{name}'", "bold", "green")
        + painter.paint(f" in {presets_file()}", "green")
    )
    painter.line(f'  Use it with: audio8d "My Song.mp3" --style "{name}"')
    return 0


def plan_from_args(args: argparse.Namespace) -> Plan:
    """Turn the parsed command line into a Plan (may raise InputValidationError)."""
    presets = known_presets()
    config = resolve_config(args, presets)
    config.validate()
    rules = tuple(read_rules(args.per_song)) if args.per_song is not None else ()
    only_defaults = used_only_defaults(args)
    replace = bool(args.replace)
    # Replacing usually means "put the 8D song where the old one was"
    name_style = args.name or ("original" if replace else "8d")
    trim = (
        Trim(args.start, args.end)
        if args.start is not None or args.end is not None
        else None
    )
    if (
        trim
        and trim.start is not None
        and trim.end is not None
        and trim.end <= trim.start
    ):
        raise InputValidationError("The chosen start and end leave no sound to convert")
    return Plan(
        config=config,
        # Typing no style is the same as choosing the recommended one, so say so
        preset=args.preset or RECOMMENDED_PRESET,
        options=ConvertOptions(
            trim=trim,
            keep_cover=not args.no_cover,
            tag_title=not args.keep_title,
            check=not args.no_check,
            replace_original=replace,
        ),
        overwrite=args.overwrite,
        output_dir=args.output_dir,
        name_style=name_style,
        jobs=args.jobs or default_jobs(),
        recursive=args.recursive,
        play=args.play,
        show_tip=only_defaults and not rules,
        presets=presets,
        default=resolve_config(args, presets, with_speakers=False),
        speakers=bool(args.speakers),
        rules=rules,
    )


def run_check(verbose: bool) -> int:
    """--check: run every dependency and say what is ready and what to fix."""
    painter = display.Painter(sys.stdout)
    painter.line(painter.paint("  Checking... (each tool is run once)", "dim"))
    report = check_environment()
    show_health(painter, report, verbose)
    return 0 if report.ok else 1


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


def _run_addon(args: argparse.Namespace) -> int | None:
    """--addon-status, --install-addon, --repair-addon or --uninstall-addon."""
    if args.addon_status:
        return run_addon_status()
    if args.install_addon or args.repair_addon:
        return run_install_addon(repair=args.repair_addon)
    if args.uninstall_addon:
        return run_uninstall_addon()
    return None


def _run_interactive() -> int:
    """Walk a first-time user through four questions, e.g. after double-clicking."""
    configure_logging(verbose=False)
    painter = display.Painter(sys.stdout)
    display.show_welcome(painter, __version__)
    presets = known_presets()

    try:
        chosen = guided.ask_for_music(painter)
        if chosen is None:
            painter.line("  Nothing given, nothing to do.")
            code = 2
        else:
            songs = (
                guided.ask_which_songs(painter, chosen) if chosen.is_dir() else [chosen]
            )
            if not songs:
                code = 2
            else:
                style = guided.ask_for_style(painter, presets)
                destination = guided.ask_for_destination(painter)
                replace, name_style = guided.ask_about_originals(painter)
                painter.line()
                plan = Plan(
                    config=presets[style].config,
                    preset=style,
                    options=ConvertOptions(replace_original=replace),
                    output_dir=destination,
                    name_style=name_style,
                    jobs=default_jobs(),
                    presets=presets,
                )
                if chosen.is_dir():
                    code = run_folder(chosen, plan, banner=False, songs=songs)
                else:
                    code = run_single(
                        chosen, _output_for(chosen, plan), plan, banner=False
                    )
        # Keep a double-clicked window open long enough to read the result
        input("\nPress Enter to close...")
    except (EOFError, KeyboardInterrupt):
        print()
        return 1

    return code


def _should_ask_interactively(argv: Sequence[str] | None) -> bool:
    """True only for a real person with no arguments, never for scripts or pipes."""
    return (
        argv is None
        and len(sys.argv) <= 1
        and sys.stdin.isatty()
        and sys.stdout.isatty()
    )


def _parse(
    parser: argparse.ArgumentParser, argv: Sequence[str] | None
) -> tuple[argparse.Namespace, list[Path]]:
    """The typed options, plus every song given when opening the window."""
    # The window takes any number of songs (e.g. several dropped on Audio8D.pyw)
    args, extra = parser.parse_known_args(argv)
    if not args.gui or any(word.startswith("-") for word in extra):
        return parser.parse_args(argv), []
    given = [args.input, args.output, *map(Path, extra)]
    return args, [song for song in given if song is not None]


def _convert(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """Convert (or preview, or compare) the song or folder on the command line."""
    painter = display.Painter(sys.stderr)
    try:
        plan = plan_from_args(args)
    except Audio8DError as exc:
        _explain(painter, exc)
        return 1
    if args.save_preset:
        code = _save_preset(args, plan.config)
        if code or args.input is None:
            return code
    if args.input is None:
        parser.error("the following arguments are required: input")
    if args.input.is_dir():
        if args.output is not None:
            parser.error("with a folder, choose where to save with --output-dir")
        if args.preview is not None or args.compare:
            parser.error("--preview and --compare work on one song, not a folder")
        return run_folder(args.input, plan)
    if args.compare:
        return run_preview(args.input, plan, 15.0, args.output, "compare")
    if args.preview is not None:
        return run_preview(args.input, plan, args.preview, args.output, "preview")
    output = args.output if args.output is not None else _output_for(args.input, plan)
    return run_single(args.input, output, plan)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, run the chosen mode, and return the process exit code."""
    # A double-clicked window opens in the old console; move to Windows Terminal
    if argv is None and launcher.relaunch_in_windows_terminal(sys.argv[1:]):
        return 0
    use_saved_tools()
    if _should_ask_interactively(argv):
        return _run_interactive()

    parser = create_parser()
    args, songs = _parse(parser, argv)
    configure_logging(args.verbose)
    use_typed_tools(args)
    addon = _run_addon(args)
    if addon is not None:
        return addon
    if args.check:
        return run_check(args.verbose)
    if args.gui:
        from .gui import run_gui  # pylint: disable=import-outside-toplevel

        return run_gui(songs)
    return _convert(parser, args)


__all__ = ["create_parser", "default_output_for", "main", "resolve_config"]
