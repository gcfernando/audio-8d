# Developed by ::> Gehan Fernando
"""The `audio8d` command-line tool."""

import argparse
import dataclasses
import logging
import os
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
    unique_outputs,
)
from .cli_manage import (
    check_style_options,
    run_setup_task,
    run_style_action,
    save_style,
    update_style,
)
from .cli_manage import explain as _explain
from .core.errors import Audio8DError, DependencyError, InputValidationError
from .core.locations import log_file
from .core.preferences import load_preferences
from .core.presets import LEGACY_STYLES, RECOMMENDED_PRESET, Preset
from .core.settings import (
    EffectConfig,
)
from .core.types import AudioStreamInfo, Trim
from .display_health import show_health
from .ffmpeg import FFmpegToolchain, probe_audio, set_preferred_paths
from .files import (
    claim_outputs,
    default_output_for,
    find_songs,
    resolve_input,
    same_file,
)
from .health import check_environment
from .logs import start_log_file
from .opener import open_path as open_in_player
from .options import (
    SETTING_OFF,
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
from .recommend import SongFacts, batch_suggestion, recommend
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
    # --dry-run: show what would be made, then stop before making anything
    dry_run: bool = False


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
    # Like a folder (and the window), an 8D song that is already made is skipped
    replacing_itself = plan.options.replace_original and same_file(
        output_path, input_path
    )
    if output_path.exists() and not plan.overwrite and not replacing_itself:
        painter.line(
            painter.paint(f"  Skipped (already made): {output_path.name}", "dim")
        )
        painter.line(
            painter.paint(
                "  Nothing new to create. Add --overwrite to make it again.", "yellow"
            )
        )
        return 0

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
    if plan.dry_run:
        _show_dry_run(painter, [(input_path, output_path)])
        return 0

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
    if result.warning:
        painter.line(painter.paint(f"  {result.warning}", "yellow"))
    if result.original_removed_to:
        display.show_removed(painter, input_path, result.original_removed_to)
    display.show_listen(painter)
    if plan.show_tip:
        display.show_tip(painter)
    if plan.play:
        open_in_player(result.output)
    return 0


def _split_existing(
    found: Sequence[tuple[Path, Path | None]], plan: Plan
) -> tuple[list[BatchItem], list[Path], list[tuple[Path, str]], int]:
    """Songs still to make, 8D copies already made, clashes, and how many renamed.

    found holds (song, the folder it was found in, or None for a song given
    on its own). Songs that would share a new file name get ' (2)', ' (3)'…
    exactly as in the window; no song is ever written over another of the run.
    """
    planned: list[BatchItem] = []
    for song, folder in found:
        config, options = song_setup(song, plan)
        planned.append(
            BatchItem(
                song,
                _output_for(song, plan, relative_to=folder, config=config),
                config if config != plan.config else None,
                options if options != plan.options else None,
            )
        )
    named = unique_outputs(planned)
    renamed = sum(1 for old, new in zip(planned, named, strict=True) if old != new)
    # A safety net: after numbering nothing should clash, but a clash is never made
    safe, clashes = claim_outputs((item.source, item.output) for item in named)
    # A set keeps the lookup quick for folders with thousands of songs
    safe = set(safe)
    items: list[BatchItem] = []
    skipped: list[Path] = []
    for item in named:
        if (item.source, item.output) not in safe:
            continue
        # A song replaced in place is never 'already made'
        in_place = plan.options.replace_original and same_file(item.output, item.source)
        if item.output.exists() and not plan.overwrite and not in_place:
            skipped.append(item.output)
        else:
            items.append(item)
    return items, skipped, clashes, renamed


def _show_dry_run(painter: display.Painter, pairs: Sequence[tuple[Path, Path]]) -> None:
    """--dry-run: each song and where its 8D copy would be saved, then stop."""
    painter.line("  " + painter.paint("Dry run: nothing is made.", "bold", "cyan"))
    for song, output in pairs:
        painter.line(f"  {song.name}" + painter.paint(f"  ->  {output}", "cyan"))
    painter.line(
        painter.paint("  Run the same command without --dry-run to make them.", "dim")
    )


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


def run_folder(
    folder: Path, plan: Plan, *, banner: bool = True, songs: list[Path] | None = None
) -> int:
    """Convert every song in a folder, several at once, then show the totals."""
    try:
        found = (
            songs if songs is not None else find_songs(folder, recursive=plan.recursive)
        )
        if not found:
            raise InputValidationError(f"No songs found in {folder}")
    except Audio8DError as exc:
        _explain(display.Painter(sys.stderr), exc)
        return 1
    return _run_songs(folder, [(song, folder) for song in found], plan, banner=banner)


def collect_songs(
    paths: Sequence[Path], recursive: bool
) -> list[tuple[Path, Path | None]]:
    """Every song named on the command line: (song, the folder it was found in).

    A song given on its own has no folder. A song named twice is made once.
    """
    found: list[tuple[Path, Path | None]] = []
    seen: set[str] = set()
    for path in paths:
        if path.is_dir():
            songs = find_songs(path, recursive=recursive)
            if not songs:
                raise InputValidationError(f"No songs found in {path}")
            pairs: list[tuple[Path, Path | None]] = [(song, path) for song in songs]
        else:
            resolve_input(path)
            pairs = [(path, None)]
        for song, folder in pairs:
            key = os.path.normcase(os.path.abspath(song))
            if key not in seen:
                seen.add(key)
                found.append((song, folder))
    return found


def run_many(paths: Sequence[Path], plan: Plan) -> int:
    """Convert several songs and folders together, like one folder."""
    try:
        found = collect_songs(paths, plan.recursive)
    except Audio8DError as exc:
        _explain(display.Painter(sys.stderr), exc)
        return 1
    count = len(found)
    label = Path(f"{count} song{'s' if count != 1 else ''} from {len(paths)} places")
    return _run_songs(label, found, plan)


def _run_songs(  # pylint: disable=too-many-locals,too-many-branches
    label: Path,
    found: Sequence[tuple[Path, Path | None]],
    plan: Plan,
    *,
    banner: bool = True,
) -> int:
    """Convert a list of songs, several at once, then show the totals."""
    painter = display.Painter(sys.stderr)
    try:
        items, skipped, clashes, renamed = _split_existing(found, plan)
        check_singer([(item.source.name, item.config or plan.config) for item in items])
    except Audio8DError as exc:
        _explain(painter, exc)
        return 1

    display.show_settings(
        painter,
        version=__version__,
        song_in=label,
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
        if not any(rule.matches(song) for song, _folder in found):
            painter.line(
                painter.paint(
                    f"  Per-song line {rule.line} ('{rule.pattern}') matched no song.",
                    "yellow",
                )
            )
    for path in skipped:
        painter.line(painter.paint(f"  Skipped (already made): {path.name}", "dim"))
    for song, why in clashes:
        painter.line(painter.paint(f"  Skipped {song.name}: {why}.", "yellow"))
    if renamed:
        painter.line(
            painter.paint(
                f"  {renamed} song{'s' if renamed != 1 else ''} would get the same "
                "file name as another song, so ' (2)', ' (3)'... is added to keep "
                "every file.",
                "yellow",
            )
        )
    if not items:
        # --overwrite only helps songs already made, never songs that clash
        again = " Add --overwrite to make them again." if skipped else ""
        painter.line(painter.paint(f"  Nothing new to create.{again}", "yellow"))
        return 0
    display.show_batch_plan(
        painter, len(items), plan.jobs, plan.output_dir, plan.options.replace_original
    )
    if plan.dry_run:
        _show_dry_run(painter, [(item.source, item.output) for item in items])
        return 0

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
    for outcome in report.converted:
        # The song was made; something around it (e.g. the original) needs a look
        if outcome.result is not None and outcome.result.warning:
            painter.line(
                painter.paint(f"  {outcome.item.source.name}: ", "dim")
                + painter.paint(outcome.result.warning, "yellow")
            )
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
        config, options = song_setup(input_path, plan)
        check_singer([(input_path.name, config)])
        display.show_settings(
            painter,
            version=__version__,
            song_in=input_path,
            song_out=output or Path("a temporary file, deleted afterwards"),
            preset=plan.preset,
            config=config,
            source=_peek_source(input_path),
            trim=options.trim,
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
            # Saved to OUTPUT on purpose; cut from the trimmed song, as in the window
            if kind == "compare":
                compare(
                    input_path,
                    output,
                    config,
                    on_progress=progress_bar.update,
                    trim=options.trim,
                )
            else:
                preview(
                    input_path,
                    output,
                    config,
                    seconds=seconds,
                    on_progress=progress_bar.update,
                    trim=options.trim,
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
                trim=options.trim,
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


def run_suggest(paths: Sequence[Path], plan: Plan) -> int:
    """--suggest: the style that suits each song, from its tags, like the window."""
    painter = display.Painter(sys.stdout)
    try:
        found = collect_songs(paths, plan.recursive)
    except Audio8DError as exc:
        _explain(display.Painter(sys.stderr), exc)
        return 1
    painter.line(painter.paint("  Reading the songs' tags...", "dim"))
    recommendations = []
    for song, _folder in found:
        facts = SongFacts.from_info(_peek_source(song), song.stem)
        suggestion = recommend(facts, plan.presets)
        recommendations.append(suggestion)
        painter.line(
            f"  {song.name}: "
            + painter.paint(suggestion.primary.style, "bold", "pink")
            + painter.paint(f"  {suggestion.primary.reason}", "dim")
        )
    if len(recommendations) > 1:
        best = batch_suggestion(recommendations)
        painter.line()
        painter.line(
            "  For all of them: "
            + painter.paint(best.style, "bold", "pink")
            + painter.paint(f"  {best.reason}", "dim")
        )
        style = best.style
    else:
        style = recommendations[0].primary.style
    painter.line(f"  Use it with: --style {style}")
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
    start = None if args.start == SETTING_OFF else args.start
    end = None if args.end == SETTING_OFF else args.end
    trim = Trim(start, end) if start is not None or end is not None else None
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
        dry_run=args.dry_run,
    )


def run_check(verbose: bool) -> int:
    """--check: run every dependency and say what is ready and what to fix."""
    painter = display.Painter(sys.stdout)
    painter.line(painter.paint("  Checking... (each tool is run once)", "dim"))
    report = check_environment()
    show_health(painter, report, verbose)
    painter.line(painter.paint(f"  Log file: {log_file()}", "dim"))
    return 0 if report.ok else 1


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
    given = [args.input, args.output, *args.more, *map(Path, extra)]
    return args, [song for song in given if song is not None]


def _songs_given(args: argparse.Namespace) -> list[Path]:
    """Every song and folder typed, when there are several; [] for just one.

    Two paths stay SONG OUTPUT, as always, unless the second is a folder that
    exists, or it exists and --output-dir says where the new songs go.
    """
    paths = [args.input, args.output, *args.more]
    if args.more:
        return paths
    second = args.output
    if second is None or not second.exists():
        return []
    if args.input.is_dir() or second.is_dir() or args.output_dir is not None:
        return paths
    return []


def _convert(  # pylint: disable=too-many-return-statements,too-many-branches
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> int:
    """Convert (or preview, or compare) the songs or folders on the command line."""
    painter = display.Painter(sys.stderr)
    check_style_options(parser, args)
    done = run_style_action(args)
    if done is not None:
        return done
    several = _songs_given(args)
    if several:
        # The second path is a song here, so its ending never chooses the format
        args.output = None
    try:
        plan = plan_from_args(args)
    except Audio8DError as exc:
        _explain(painter, exc)
        return 1
    if args.save_preset or args.update_style:
        # 'Safe for speakers too' is chosen apart, never saved inside a style
        config = plan.default or plan.config
        code = (save_style if args.save_preset else update_style)(args, config)
        if code or args.input is None:
            return code
    if args.input is None:
        parser.error("the following arguments are required: input")
    if args.dry_run and (args.preview is not None or args.compare):
        parser.error("--dry-run shows what would be made; leave out --preview")
    if args.suggest:
        return run_suggest(several or [args.input], plan)
    if several:
        if args.preview is not None or args.compare:
            parser.error("--preview and --compare work on one song at a time")
        return run_many(several, plan)
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
    task = run_setup_task(args)
    if task is not None:
        return task
    if args.check:
        return run_check(args.verbose)
    if args.gui:
        from .gui import run_gui  # pylint: disable=import-outside-toplevel

        return run_gui(songs)
    return _convert(parser, args)


__all__ = ["create_parser", "default_output_for", "main", "resolve_config"]
