# Developed by ::> Gehan Fernando
"""The end-to-end conversion: validate, probe, analyse, measure, render, publish."""

import dataclasses
import functools
import logging
import math
import re
import shutil
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import cache
from .analysis import (
    STEM_RATE,
    QualityReport,
    check_output,
    detect_bpm,
    loudest_section,
    rotation_for_tempo,
    separate_vocals,
)
from .core.errors import ConversionError, InputValidationError
from .core.settings import LOSSLESS_FORMATS, EffectConfig
from .core.types import AudioStreamInfo, Trim
from .effects import (
    GraphInputs,
    Source,
    build_finish_graph,
    build_graph,
    build_measure_graph,
    loudness_gain_db,
    output_sample_rate,
    to_stereo,
    write_controls,
    write_room,
)
from .ffmpeg import (
    ENCODERS,
    FFmpegToolchain,
    InputFile,
    LoudnessMeasurement,
    build_encode_command,
    build_measure_command,
    build_mix_command,
    measure_loudness,
    parse_ebur128_summary,
    preferred_key,
    probe_audio,
    run_capture,
    run_ffmpeg,
)
from .files import (
    commit_output,
    create_temporary_output,
    remove_original,
    resolve_input,
    resolve_output,
    same_file,
)

LOG = logging.getLogger(__name__)

# How much the singer still moves when vocals are kept in the centre
VOCAL_MOVEMENT = 0.3
# The steps a conversion goes through, as shown by the progress bar
STAGE_STEMS = "Splitting vocals"
STAGE_RENDER = "Making your 8D song"
STAGE_SAVE = "Saving the file"
STAGE_CHECK = "Checking the result"

# Called with a stage name and the share of that stage that is done (0.0 to 1.0)
StageProgress = Callable[[str, float], None]


@dataclass(frozen=True, slots=True)
class LoudnessPlan:
    """What the loudness pass measured and the one volume change chosen from it."""

    measured: LoudnessMeasurement
    gain_db: float
    target_lufs: float
    exact: bool
    # True when the measurement came from the cache instead of a new pass
    cached: bool = False

    @property
    def silent(self) -> bool:
        """True for silence, which ebur128 reports as -70 LUFS and stays silent."""
        return self.measured.integrated_lufs <= -70.0

    @property
    def expected_lufs(self) -> float:
        """Where the volume change aims; the limiter can still pull the song lower."""
        if self.silent:
            return self.measured.integrated_lufs
        return (
            self.target_lufs
            if self.exact
            else self.measured.integrated_lufs + self.gain_db
        )

    @property
    def held_back(self) -> bool:
        """True when the song stays below target to protect its loudest peaks."""
        return (
            not self.exact
            and not self.silent
            and self.expected_lufs < self.target_lufs - 0.05
        )

    def limits_peaks(self, ceiling: float) -> bool:
        """True when the limiter will have short peaks to catch after the gain."""
        return self.exact or (
            self.measured.true_peak_db + self.gain_db > 20 * math.log10(ceiling)
        )


@dataclass(frozen=True, slots=True)
class ConvertOptions:
    """How one conversion treats the file, beyond how it sounds."""

    trim: Trim | None = None
    # Copy the album art into the new file (MP3, FLAC and M4A can hold it)
    keep_cover: bool = True
    # Add " (8D)" to the title tag, so music apps list it as its own track
    tag_title: bool = True
    title_suffix: str = " (8D)"
    # Measure the finished file (loudness, peaks, mono) after saving it
    check: bool = True
    # Move the original aside (Recycle Bin, or renamed) once the new one is saved
    replace_original: bool = False
    # Start time in the trimmed song, so a preview moves exactly as the full song does
    timeline_start: float = 0.0
    # Format whose sound this copies while saved as another (a WAV preview of an MP3)
    render_as: str | None = None


@dataclass(frozen=True, slots=True)
class ConversionResult:  # pylint: disable=too-many-instance-attributes
    """Everything worth reporting about one finished conversion."""

    source: AudioStreamInfo
    output: Path
    config: EffectConfig
    loudness: LoudnessPlan | None = None
    quality: QualityReport | None = None
    bpm: float | None = None
    beats_per_turn: int = 0
    # Where the original went when replace_original was on (see describe_removal)
    original_removed_to: str | None = None
    # Something worth telling the user although the song itself was saved
    warning: str | None = None


@functools.lru_cache(maxsize=16)
def _checked_toolchain(
    extra: frozenset[str], encoder: str, _tools: tuple[str, str]
) -> FFmpegToolchain:
    """Find FFmpeg and check its abilities once per run, not once per song.

    _tools is the paths chosen in Settings, so choosing others checks again.
    """
    toolchain = FFmpegToolchain.discover()
    toolchain.validate_capabilities(extra_filters=extra, encoder=encoder)
    return toolchain


def stages_for(options: "ConvertOptions") -> list[str]:
    """The progress stages one conversion reports, in order (for overall bars)."""
    return [STAGE_RENDER, STAGE_SAVE] + ([STAGE_CHECK] if options.check else [])


def toolchain_for(config: EffectConfig, *, validate: bool = True) -> FFmpegToolchain:
    """The FFmpeg to use for this config, checked when validate is True."""
    if not validate:
        return FFmpegToolchain.discover()
    extra = frozenset({"ebur128"} if config.wants_loudness else set())
    return _checked_toolchain(extra, ENCODERS[config.output_format], preferred_key())


_TIME = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")


def _decoded_duration(
    toolchain: FFmpegToolchain, song: Path, cancel: threading.Event | None = None
) -> float:
    """Play the file into nothing to learn its length when the file won't say."""
    result = run_capture(
        [str(toolchain.ffmpeg), "-hide_banner", "-nostdin", "-i", str(song),
         "-map", "0:a:0", "-f", "null", "-"],
        error_type=InputValidationError,
        cancel=cancel,
    )  # fmt: skip
    matches = _TIME.findall(result.stderr)
    if not matches:
        raise InputValidationError(
            "The input file does not contain a usable audio stream"
        )
    hours, minutes, seconds = matches[-1]
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _song_length(
    toolchain: FFmpegToolchain,
    song: Path,
    info: AudioStreamInfo,
    trim: Trim | None,
    cancel: threading.Event | None = None,
) -> float:
    """Seconds of audio that will be converted, after any trim."""
    total = info.duration_seconds
    if total is None:
        total = _decoded_duration(toolchain, song, cancel)
    length = trim.length(total) if trim else total
    if length is None or length <= 0.05:
        raise InputValidationError("The chosen start and end leave no sound to convert")
    return length


def _sync_to_beat(
    toolchain: FFmpegToolchain,
    song: Path,
    info: AudioStreamInfo,
    config: EffectConfig,
    cancel: threading.Event | None = None,
) -> tuple[EffectConfig, float | None, int]:
    """Snap the spin to whole bars of the song's tempo, if beat sync is on."""
    if not config.beat_sync and config.bpm is None:
        return config, None, 0
    bpm = config.bpm or detect_bpm(
        toolchain, song, info.duration_seconds, cancel=cancel
    )
    if bpm is None:
        # The panel and the window say this in plain words; the log keeps a record
        LOG.info("No clear beat found, so the spin keeps its own speed")
        return config, None, 0
    seconds, beats = rotation_for_tempo(bpm, config.rotation_seconds)
    return dataclasses.replace(config, rotation_seconds=seconds), bpm, beats


def _title_for(
    info: AudioStreamInfo, song: Path, options: ConvertOptions
) -> str | None:
    """The new title tag, e.g. 'My Song (8D)', or None to keep the original."""
    if not options.tag_title:
        return None
    base = info.title or song.stem
    return base if base.endswith(options.title_suffix) else base + options.title_suffix


def _log_source(
    song: Path, info: AudioStreamInfo, sound_format: str, sample_rate: int
) -> None:
    """Record what the source analysis found and how the song will be made."""
    depth = f"{info.bits_per_sample}-bit" if info.bits_per_sample else "no fixed depth"
    rate = info.sample_rate or 0
    LOG.info(
        "Source %s: %s, %s kbps, %d Hz, %s, %d ch (%s), %s; making %s at %d Hz%s",
        song.name,
        info.codec_name,
        round(info.bit_rate / 1000) if info.bit_rate else "?",
        rate,
        depth,
        info.channels,
        info.channel_layout or "unknown layout",
        "lossless" if info.is_lossless else "already compressed",
        sound_format,
        sample_rate,
        "" if sample_rate == rate else " (resampled once)",
    )


class _Job:  # pylint: disable=too-many-instance-attributes
    """One conversion's working state, so each step stays short and readable."""

    def __init__(
        self,
        song: Path,
        config: EffectConfig,
        *,
        options: ConvertOptions,
        toolchain: FFmpegToolchain,
        progress: StageProgress,
        cancel: threading.Event | None,
    ) -> None:
        """Probe the song and work out the rate and length used everywhere."""
        self.song = song
        self.options = options
        self.toolchain = toolchain
        self.progress = progress
        self.cancel = cancel
        self.info = probe_audio(toolchain, song, cancel=cancel)
        self.length = _song_length(toolchain, song, self.info, options.trim, cancel)
        self.config, self.bpm, self.beats = _sync_to_beat(
            toolchain, song, self.info, config, cancel
        )
        # A preview saved as WAV still sounds like the format it stands in for
        sound_format = options.render_as or self.config.output_format
        self.lossless = sound_format in LOSSLESS_FORMATS
        self.sample_rate = output_sample_rate(sound_format, self.info.sample_rate)
        _log_source(song, self.info, sound_format, self.sample_rate)
        self.inputs: list[InputFile] = [InputFile(song, options.trim)]
        self.graph_inputs = GraphInputs(sources=())

    def prepare(self, scratch: Path) -> None:
        """Split stems if asked, then write the gain streams and the room."""
        sources: list[tuple[int, float]] = []
        if self.config.vocals == "center":
            self.progress(STAGE_STEMS, 0.0)
            vocals, music = separate_vocals(
                self.toolchain, self.song, cancel=self.cancel
            )
            self.progress(STAGE_STEMS, 1.0)
            for stem, scale in ((vocals, VOCAL_MOVEMENT), (music, 1.0)):
                self.inputs.append(InputFile(stem, self.options.trim))
                sources.append((len(self.inputs) - 1, scale))
        else:
            sources.append((0, 1.0))

        graph_sources = []
        for number, (audio_input, scale) in enumerate(sources):
            controls = write_controls(
                scratch,
                f"s{number}",
                self.config,
                self.length,
                intensity_scale=scale,
                start=self.options.timeline_start,
            )
            first = len(self.inputs)
            self.inputs += [InputFile(path) for path in controls]
            graph_sources.append(
                Source(
                    audio_input,
                    tuple(range(first, first + len(controls))),
                    # Only the original song can be mono; the singer's stems are stereo
                    mono=audio_input == 0 and self.info.channels == 1,
                    # The stems come at Demucs's own rate, whatever the song's is
                    rate=None if audio_input == 0 else STEM_RATE,
                )
            )
        room = None
        if self.config.ambience > 0:
            self.inputs.append(
                InputFile(
                    write_room(
                        scratch / "room.wav", self.config.ambience, self.sample_rate
                    )
                )
            )
            room = len(self.inputs) - 1
        self.graph_inputs = GraphInputs(tuple(graph_sources), room)

    def _source_loudness(self, stop: threading.Event) -> float:
        """The original song's own integrated loudness (for 'same as the original')."""
        # Made stereo the same way as the 8D mix, so both are measured alike
        stereo = to_stereo(self.info.channels == 1)
        graph = (
            f"[0:a:0]{stereo}aformat=channel_layouts=stereo,"
            "ebur128=peak=true:framelog=verbose[out]"
        )
        measured = measure_loudness(
            build_measure_command(self.toolchain.ffmpeg, self.inputs[:1], graph),
            cancel=stop,
        )
        return measured.integrated_lufs

    def _plan(
        self, measured: LoudnessMeasurement, target: float, cached: bool
    ) -> LoudnessPlan:
        """The one volume change that brings the measured mix to the target."""
        gain = loudness_gain_db(
            measured.integrated_lufs,
            measured.true_peak_db,
            target,
            self.config.limiter_ceiling,
            exact=self.config.exact_loudness,
        )
        return LoudnessPlan(
            measured=measured,
            gain_db=gain,
            target_lufs=target,
            exact=self.config.exact_loudness,
            cached=cached,
        )

    def run(  # pylint: disable=too-many-locals
        self, temporary_file: Path, scratch: Path
    ) -> LoudnessPlan | None:
        """Make the song: one pass, or a mix pass plus a quick save pass.

        With a loudness goal the mix is measured first. For fast encoders the 3D
        mix is made only once: it goes to a lossless float file while being
        measured, and a light second pass sets the volume, limits and saves it.
        A remembered measurement, or no loudness goal, needs just one pass.
        """
        if not self.config.wants_loudness:
            self._encode(temporary_file, self._graph(None), self.length)
            self.progress(STAGE_SAVE, 1.0)
            return None

        # The original's loudness is measured on its own thread, alongside the mix
        source: dict[str, float | BaseException] = {}
        worker = None
        # Set when the mix fails or is stopped, so the side measurement stops too
        stop = threading.Event()
        if self.config.match_loudness:

            def measure_source() -> None:
                try:
                    source["lufs"] = self._source_loudness(stop)
                except BaseException as exc:  # pylint: disable=broad-exception-caught
                    source["error"] = exc

            worker = threading.Thread(target=measure_source, daemon=True)
            worker.start()
        try:
            measured, remembered, mix_file = self._measure_mix(scratch)
        except BaseException:
            # Never leave FFmpeg measuring the original after the job has failed
            stop.set()
            if worker is not None:
                worker.join()
            raise

        target = self.config.loudness_target
        if worker is not None:
            self._wait_for(worker, stop)
            if "error" in source:
                raise source["error"]  # type: ignore[misc]
            lufs = float(source["lufs"])  # type: ignore[arg-type]
            # A silent original has no loudness to match; keep the natural level
            target = lufs if lufs > -70.0 else measured.integrated_lufs
        assert target is not None
        plan = self._plan(measured, target, cached=remembered)
        margin = plan.limits_peaks(self.config.limiter_ceiling)
        if mix_file is None:
            # The mix step is done (measured, or remembered); only saving remains
            self.progress(STAGE_RENDER, 1.0)
            graph = self._graph(plan, margin)
            self._encode(temporary_file, graph, self.length, stage=STAGE_SAVE)
            self.progress(STAGE_SAVE, 1.0)
        else:
            self._save_mix(temporary_file, mix_file, plan, margin)
        return plan

    def _measure_mix(
        self, scratch: Path
    ) -> tuple[LoudnessMeasurement, bool, Path | None]:
        """The mix's loudness: remembered, or measured (saved too for fast encoders)."""
        stems = self.config.vocals == "center"
        key = cache.measurement_key(
            self.song,
            self.config,
            self.options.trim,
            self.sample_rate,
            self.options.timeline_start,
        )
        # Stems come from an AI model, so their measurement is never remembered
        measured = None if stems else cache.get(key)
        remembered = measured is not None
        mix_file = None
        if measured is None:
            graph = build_measure_graph(
                self.config,
                self.graph_inputs,
                sample_rate=self.sample_rate,
                source_rate=self.info.sample_rate,
            )
            # Slow LAME is fastest with the mix remade while encoding; others mix once
            if self.config.output_format == "mp3":
                measured = measure_loudness(
                    build_measure_command(self.toolchain.ffmpeg, self.inputs, graph),
                    duration=self.length,
                    on_progress=lambda share: self.progress(STAGE_RENDER, share),
                    cancel=self.cancel,
                )
            else:
                mix_file = scratch / "mix.wav"
                measured = self._render_mix(graph, mix_file)
            if not stems:
                cache.put(key, measured)
        return measured, remembered, mix_file

    def _wait_for(self, worker: threading.Thread, stop: threading.Event) -> None:
        """Wait for the side measurement, passing on a Stop from the user."""
        while worker.is_alive():
            if self.cancel is not None and self.cancel.is_set():
                stop.set()
            worker.join(0.1)

    def _graph(self, plan: LoudnessPlan | None, margin: bool | None = None) -> str:
        """The one-pass graph: the full mix, the volume change and the limiter."""
        return build_graph(
            self.config,
            self.graph_inputs,
            sample_rate=self.sample_rate,
            source_rate=self.info.sample_rate,
            gain_db=plan.gain_db if plan else None,
            peak_margin=margin,
            lossless=self.lossless,
        )

    def _render_mix(self, graph: str, mix_file: Path) -> LoudnessMeasurement:
        """Pass 1: make the 3D mix into a float WAV and measure it on the way."""
        result = run_ffmpeg(
            build_mix_command(self.toolchain.ffmpeg, self.inputs, graph, mix_file),
            duration=self.length,
            on_progress=lambda share: self.progress(STAGE_RENDER, share),
            cancel=self.cancel,
        )
        _raise_if_failed(result.returncode, result.stderr)
        return parse_ebur128_summary(result.stderr)

    def _save_mix(
        self, temporary_file: Path, mix_file: Path, plan: LoudnessPlan, margin: bool
    ) -> None:
        """Pass 2: the finished mix, turned to the target, limited and saved."""
        # Input 0 stays the original song, only for its tags and album picture
        inputs = [InputFile(self.song, self.options.trim), InputFile(mix_file)]
        graph = build_finish_graph(
            self.config,
            1,
            plan.gain_db,
            margin,
            sample_rate=self.sample_rate,
            lossless=self.lossless,
        )
        self._encode(temporary_file, graph, self.length, inputs, STAGE_SAVE)

    def _encode(
        self,
        temporary_file: Path,
        graph: str,
        duration: float,
        inputs: list[InputFile] | None = None,
        stage: str = STAGE_RENDER,
    ) -> None:
        """Run an encode and confirm it actually produced audio."""
        command = build_encode_command(
            self.toolchain.ffmpeg,
            inputs or self.inputs,
            temporary_file,
            filter_graph=graph,
            config=self.config,
            sample_rate=self.sample_rate,
            cover_art=self.options.keep_cover and self.info.has_cover_art,
            title=_title_for(self.info, self.song, self.options),
            tags_on_stream=self.info.tags_on_stream,
        )
        result = run_ffmpeg(
            command,
            duration=duration,
            on_progress=lambda share: self.progress(stage, share),
            cancel=self.cancel,
        )
        _raise_if_failed(result.returncode, result.stderr)
        if not temporary_file.is_file() or temporary_file.stat().st_size <= 0:
            raise ConversionError(
                "FFmpeg reported success but did not create a valid output file"
            )


def _raise_if_failed(returncode: int, log: str) -> None:
    """Turn a failed FFmpeg run into a ConversionError with its last words."""
    if returncode != 0:
        # Windows reports FFmpeg's negative error codes as large unsigned numbers
        if returncode >= 2**31:
            returncode -= 2**32
        details = (
            log.strip()[-2000:] or "FFmpeg returned no additional error information"
        )
        raise ConversionError(
            f"FFmpeg conversion failed with exit code {returncode}: {details}"
        )


def _no_progress(_stage: str, _share: float) -> None:
    """Default progress callback: stay quiet."""


def convert(  # pylint: disable=too-many-arguments,too-many-locals,too-many-branches,too-many-statements
    input_path: Path,
    output_path: Path,
    config: EffectConfig,
    *,
    overwrite: bool = False,
    validate_toolchain: bool = True,
    options: ConvertOptions | None = None,
    on_loudness: Callable[[LoudnessPlan], None] | None = None,
    on_progress: StageProgress | None = None,
    cancel: threading.Event | None = None,
) -> ConversionResult:
    """Turn one audio file into an 8D stereo file and report how it went."""
    config.validate()
    options = options or ConvertOptions()
    progress = on_progress or _no_progress

    toolchain = toolchain_for(config, validate=validate_toolchain)
    input_file = resolve_input(input_path)
    # Writing over the original is allowed only when it is being replaced anyway
    in_place = same_file(input_file, output_path)
    if in_place and not options.replace_original:
        raise InputValidationError("Input and output paths must be different")
    output_file = resolve_output(
        output_path, overwrite=overwrite or in_place, extension=config.extension
    )

    job = _Job(
        input_file,
        config,
        options=options,
        toolchain=toolchain,
        progress=progress,
        cancel=cancel,
    )
    temporary_file = create_temporary_output(output_file)
    try:
        scratch = Path(tempfile.mkdtemp(prefix="audio8d-"))
    except OSError as exc:
        raise ConversionError(f"I/O error during conversion: {exc}") from exc
    keep_temporary = False
    removed_to = None
    warning = None
    LOG.info(
        "Converting %s -> %s [codec=%s, channels=%d, sample_rate=%s]",
        input_file,
        output_file,
        job.info.codec_name,
        job.info.channels,
        job.info.sample_rate or "unknown",
    )

    try:
        job.prepare(scratch)
        plan = job.run(temporary_file, scratch)
        if plan is not None:
            LOG.info(
                "Loudness: measured %.1f LUFS / %.1f dBFS peak, target %.1f, "
                "applied %+.2f dB",
                plan.measured.integrated_lufs,
                plan.measured.true_peak_db,
                plan.target_lufs,
                plan.gain_db,
            )
            if on_loudness is not None:
                on_loudness(plan)

        if in_place:
            # The new file is complete, so the original can go before taking its name
            removed_to = remove_original(input_file)
            keep_temporary = True
            try:
                commit_output(temporary_file, output_file, overwrite=False)
            except ConversionError as exc:
                raise ConversionError(
                    f"{exc}. Your new song is safe at: {temporary_file}"
                ) from exc
            keep_temporary = False
        else:
            commit_output(temporary_file, output_file, overwrite=overwrite)
            if options.replace_original:
                try:
                    removed_to = remove_original(input_file)
                except ConversionError as exc:
                    # The 8D song is saved, so a stuck original is only worth a warning
                    LOG.warning("%s", exc)
                    warning = (
                        f"{exc}. Your 8D song was saved; the original is still there."
                    )
    except KeyboardInterrupt as exc:
        raise ConversionError("Conversion cancelled by user") from exc
    except OSError as exc:
        raise ConversionError(f"I/O error during conversion: {exc}") from exc
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        # Always sweep the scratch file, unless it is now the only copy of the song
        if keep_temporary:
            LOG.error("Your new song is safe at: %s", temporary_file)
        else:
            try:
                temporary_file.unlink(missing_ok=True)
            except OSError:
                LOG.warning("Could not remove temporary file: %s", temporary_file)

    quality = None
    if options.check:
        progress(STAGE_CHECK, 0.0)
        try:
            quality = check_output(toolchain, output_file, cancel=cancel)
        except ConversionError as exc:
            LOG.warning("Could not check the finished file: %s", exc)
        progress(STAGE_CHECK, 1.0)

    LOG.info("Conversion completed: %s", output_file)
    return ConversionResult(
        source=job.info,
        output=output_file,
        config=job.config,
        loudness=plan,
        quality=quality,
        bpm=job.bpm,
        beats_per_turn=job.beats,
        original_removed_to=removed_to,
        warning=warning,
    )


def preview_output_for(input_path: Path, extension: str) -> Path:
    """'song (8D preview).mp3' next to the song."""
    return input_path.with_name(f"{input_path.stem} (8D preview){extension}")


def compare_output_for(input_path: Path) -> Path:
    """'song (A-B compare).mp3' next to the song."""
    return input_path.with_name(f"{input_path.stem} (A-B compare).mp3")


def _preview_window(trim: Trim | None, seconds: float, start: float) -> Trim:
    """The preview's stretch: seconds from start, kept inside the song's own trim."""
    end = start + seconds
    if trim is not None and trim.end is not None:
        end = min(end, trim.end)
    return Trim(start, max(end, start + 0.1))


def _preview_target(config: EffectConfig, lift_db: float | None) -> EffectConfig:
    """Aim the preview as loud as that stretch will be in the finished song.

    A fixed target is met by the whole song, so its loudest part lands above it;
    the preview goes up by that same lift. 'Same as the original' already
    follows the section, and no target means no change.
    """
    if lift_db is None or config.loudness_target is None or config.match_loudness:
        return config
    target = max(-30.0, min(-5.0, config.loudness_target + lift_db))
    return dataclasses.replace(config, loudness_target=round(target, 2))


def preview(  # pylint: disable=too-many-arguments,too-many-locals
    input_path: Path,
    output_path: Path,
    config: EffectConfig,
    *,
    seconds: float = 30.0,
    start: float | None = None,
    overwrite: bool = True,
    on_progress: StageProgress | None = None,
    cancel: threading.Event | None = None,
    trim: Trim | None = None,
    render_as: str | None = None,
) -> ConversionResult:
    """Render a short 8D sample from the loudest part of the song (the chorus).

    It is made exactly like the finished song at that moment: trim is the
    song's own start and end (the chorus is looked for only inside it), and
    render_as is the real output format when the sample is saved as WAV. Only
    the length, the shorter ease-in and the file type differ.
    """
    config.validate()
    toolchain = toolchain_for(config)
    song = resolve_input(input_path)
    lift = None
    if start is None:
        # A cancelled preview stops here too, not after scanning the whole song
        info = probe_audio(toolchain, song, cancel=cancel)
        found = loudest_section(
            toolchain,
            song,
            seconds,
            info.duration_seconds,
            window=trim,
            cancel=cancel,
        )
        start, lift = found.start, found.lift_db
    # A short sample needs a short fade, or it would never reach full movement
    short = dataclasses.replace(config, fade_seconds=min(config.fade_seconds, 1.5))
    song_start = (trim.start if trim else None) or 0.0
    return convert(
        song,
        output_path,
        _preview_target(short, lift),
        overwrite=overwrite,
        options=ConvertOptions(
            trim=_preview_window(trim, seconds, start),
            title_suffix=" (8D preview)",
            check=False,
            timeline_start=max(0.0, start - song_start),
            render_as=render_as,
        ),
        on_progress=on_progress,
        cancel=cancel,
    )


def compare(  # pylint: disable=too-many-arguments,too-many-locals
    input_path: Path,
    output_path: Path,
    config: EffectConfig,
    *,
    seconds: float = 15.0,
    overwrite: bool = True,
    on_progress: StageProgress | None = None,
    cancel: threading.Event | None = None,
    trim: Trim | None = None,
) -> Path:
    """One file that plays the original (A), a short pause, then the 8D version (B).

    Both halves come from the same loudest part (inside the song's own trim,
    if given) and are matched to the same loudness, so the only difference you
    hear is the 8D effect itself.
    """
    toolchain = toolchain_for(dataclasses.replace(config, output_format="wav"))
    song = resolve_input(input_path)
    info = probe_audio(toolchain, song, cancel=cancel)
    start = loudest_section(
        toolchain, song, seconds, info.duration_seconds, window=trim, cancel=cancel
    ).start
    output = resolve_output(output_path, overwrite=overwrite, extension=".mp3")
    scratch = Path(tempfile.mkdtemp(prefix="audio8d-ab-"))
    # Written under a hidden name first, so a stopped compare leaves nothing behind
    temporary = create_temporary_output(output)
    target = -16.0
    try:
        effect = scratch / "b.wav"
        preview(
            song,
            effect,
            dataclasses.replace(
                config, output_format="wav", loudness_target=target, exact_loudness=True
            ),
            seconds=seconds,
            start=start,
            on_progress=on_progress,
            cancel=cancel,
            trim=trim,
            # B ends up in an MP3, so it keeps MP3's peak margin
            render_as="mp3",
        )
        original = measure_loudness(
            build_measure_command(
                toolchain.ffmpeg,
                [InputFile(song, Trim(start, start + seconds))],
                "[0:a:0]aformat=channel_layouts=stereo,"
                "ebur128=peak=true:framelog=verbose[out]",
            ),
            cancel=cancel,
        )
        gain = loudness_gain_db(
            original.integrated_lufs, original.true_peak_db, target, 0.89, exact=True
        )
        rate = output_sample_rate("wav", info.sample_rate)
        graph = (
            f"[0:a:0]aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"aresample={rate},volume={gain:.2f}dB,{_ab_limiter()},"
            "afade=t=in:d=0.3,afade=t=out:st="
            f"{max(0.0, seconds - 0.5):.2f}:d=0.5[a];"
            f"[1:a]aformat=sample_fmts=fltp:channel_layouts=stereo,aresample={rate}[b];"
            f"anullsrc=r={rate}:cl=stereo,atrim=duration=1.2[gap];"
            "[a][gap][b]concat=n=3:v=0:a=1,aresample=44100[out]"
        )
        command = [
            str(toolchain.ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "error",
            "-y", "-ss", f"{start:.3f}", "-t", f"{seconds:.3f}", "-i", str(song),
            "-i", str(effect), "-filter_complex", graph, "-map", "[out]",
            "-map_metadata", "0:s:a:0" if info.tags_on_stream else "0",
            "-c:a", "libmp3lame", "-b:a", "320k",
            "-metadata", f"title={info.title or song.stem} (A = original, B = 8D)",
            str(temporary),
        ]  # fmt: skip
        result = run_ffmpeg(command, duration=None, cancel=cancel)
        _raise_if_failed(result.returncode, result.stderr)
        commit_output(temporary, output, overwrite=True)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            # A file still held open elsewhere must not hide the real outcome
            LOG.warning("Could not remove temporary file: %s", temporary)
    return output


def _ab_limiter() -> str:
    """A gentle limiter so the loudness-matched original never clips."""
    return "alimiter=limit=0.89:attack=5:release=50:level=false:latency=true"
