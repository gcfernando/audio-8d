# Developed by ::> Gehan Fernando
"""The command line can do what the window does: every feature added for parity."""

import json
from pathlib import Path
from typing import Any

import pytest

from src import AudioStreamInfo, cli, cli_manage
from src.batch import BatchOutcome, BatchReport, unique_outputs
from src.core.presets import PRESETS
from src.core.user_presets import load_user_presets
from src.per_song import parse_line
from src.pipeline import ConversionResult
from src.song_settings import SPEAKERS

_SOURCE = AudioStreamInfo("mp3", 2, 44100, 180.0)


def _recorder(seen: dict[str, Any]):
    """A stand-in for convert() that remembers its arguments and 'succeeds'."""

    def fake_convert(**kwargs: Any) -> ConversionResult:
        seen.update(kwargs)
        return ConversionResult(_SOURCE, Path(kwargs["output_path"]), kwargs["config"])

    return fake_convert


@pytest.fixture(autouse=True)
def _pretend_songs_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Made-up song names are fine, and nothing is probed."""
    monkeypatch.setattr(cli, "resolve_input", lambda path: path)
    monkeypatch.setattr(cli, "_peek_source", lambda path: None)


def _fake_batch(seen: dict[str, Any]):
    """A stand-in for run_batch that 'converts' every item it is given."""

    def fake_run_batch(items, config, **kwargs):
        seen["items"] = items
        seen.update(kwargs)
        report = BatchReport()
        for item in items:
            report.outcomes.append(
                BatchOutcome(item, ConversionResult(_SOURCE, item.output, config))
            )
        return report

    return fake_run_batch


def _songs(folder: Path, *names: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"audio")
    return folder


def _config(*options: str):
    return cli.resolve_config(cli.create_parser().parse_args(["a.mp3", *options]))


# ------------------------------------------------ A: songs that share a new name


def test_replace_never_overwrites_another_song_of_the_same_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "run_batch", _fake_batch(seen))
    folder = _songs(tmp_path / "Music", "a.mp3", "a.flac")

    assert cli.main([str(folder), "--replace", "--overwrite"]) == 0
    # a.flac would be saved as a.mp3, over the original a.mp3, so it is numbered
    pairs = {item.source.name: item.output.name for item in seen["items"]}
    assert pairs == {"a.mp3": "a.mp3", "a.flac": "a (2).mp3"}
    assert "' (2)', ' (3)'... is added" in capsys.readouterr().err


def test_songs_sharing_a_new_name_are_numbered_like_in_the_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "run_batch", _fake_batch(seen))
    folder = _songs(tmp_path / "Music", "a.mp3", "a.flac")

    assert cli.main([str(folder)]) == 0
    items = seen["items"]
    assert sorted(item.output.name for item in items) == [
        "a (8D) (2).mp3",
        "a (8D).mp3",
    ]
    # The same names the window gives the same songs
    assert [item.output for item in items] == [
        item.output for item in unique_outputs(list(items))
    ]


def test_dry_run_shows_the_numbered_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "run_batch", lambda *_a, **_k: pytest.fail("ran"))
    folder = _songs(tmp_path / "Music", "a.mp3", "a.flac")

    assert cli.main([str(folder), "--replace", "--overwrite", "--dry-run"]) == 0
    shown = capsys.readouterr().err
    assert str(folder / "a (2).mp3") in shown
    assert "Skipped" not in shown


def test_a_warning_after_a_made_song_is_shown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def converted_with_a_warning(**kwargs: Any) -> ConversionResult:
        return ConversionResult(
            _SOURCE,
            Path(kwargs["output_path"]),
            kwargs["config"],
            warning="The original could not be moved to the Recycle Bin",
        )

    monkeypatch.setattr(cli, "convert", converted_with_a_warning)

    assert cli.main(["a.mp3"]) == 0
    assert "could not be moved" in capsys.readouterr().err


# ----------------------------------------------- B: switching a style's setting off


def test_beat_sync_and_exact_loudness_can_be_switched_off() -> None:
    groove = PRESETS["groove"].config
    assert groove.beat_sync is True

    assert _config("--style", "groove", "--no-beat-sync").beat_sync is False
    assert _config("--exact-loudness", "--no-exact-loudness").exact_loudness is False
    # Not typing either keeps the style's own choice
    assert _config("--style", "groove").beat_sync is True


def test_curves_and_tempo_can_be_cleared_with_off() -> None:
    assert _config("--speed-curve", "0=10, 1:00=6", "--speed-curve", "off") == (
        _config()
    )
    assert _config("--intensity-curve", "none").intensity_curve == ()
    assert _config("--bpm", "120").bpm == 120
    assert _config("--bpm", "off").bpm is None


def test_a_bad_tempo_is_a_usage_error() -> None:
    with pytest.raises(SystemExit):
        cli.create_parser().parse_args(["a.mp3", "--bpm", "fast"])


# ---------------------------------------------------- C: per-song opposites


def test_a_per_song_line_can_undo_every_switch() -> None:
    rule = parse_line(
        '"Live.mp3" --no-speakers --cover --title-tag --start off --end off', 1
    )

    assert rule is not None
    assert rule.changes == {
        SPEAKERS: False,
        "keep_cover": True,
        "tag_title": True,
        "trim_start": None,
        "trim_end": None,
    }


def test_a_per_song_line_undoes_the_runs_speakers_cover_and_trim(
    tmp_path: Path,
) -> None:
    rules = tmp_path / "songs.txt"
    rules.write_text('"a.mp3" --no-speakers --cover --start off\n', encoding="utf-8")
    plan = cli.plan_from_args(
        cli.create_parser().parse_args(
            [
                "a.mp3",
                "--speakers",
                "--no-cover",
                "--start",
                "0:30",
                "--end",
                "2:00",
                "--per-song",
                str(rules),
            ]
        )
    )

    config, options = cli.song_setup(Path("a.mp3"), plan)
    assert config == plan.default
    assert options.keep_cover is True
    assert options.trim is not None
    assert (options.trim.start, options.trim.end) == (None, 120.0)
    # Other songs keep the run's settings
    assert cli.song_setup(Path("b.mp3"), plan) == (plan.config, plan.options)


def test_start_off_on_the_command_line_means_no_start() -> None:
    plan = cli.plan_from_args(
        cli.create_parser().parse_args(["a.mp3", "--start", "off", "--end", "off"])
    )
    assert plan.options.trim is None


# --------------------------------------------------------- D: previews and trim


def test_a_preview_comes_from_the_part_that_is_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}

    def fake_make_preview(_song, _folder, _config, **kwargs):
        seen.update(kwargs)
        return tmp_path / "sample.wav"

    monkeypatch.setattr(cli, "make_preview", fake_make_preview)
    monkeypatch.setattr(cli, "_listen", lambda *_args: None)

    assert (
        cli.main(["a.mp3", "--preview", "20", "--start", "1:00", "--end", "2:00"]) == 0
    )
    assert seen["seconds"] == 20
    assert (seen["trim"].start, seen["trim"].end) == (60.0, 120.0)


def test_a_kept_compare_file_also_uses_the_trim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "compare", lambda *_args, **kwargs: seen.update(kwargs))
    monkeypatch.setattr(cli.display, "show_done", lambda *_args: None)

    assert cli.main(["a.mp3", "ab.mp3", "--compare", "--start", "0:10"]) == 0
    assert seen["trim"].start == 10.0


# --------------------------------------------------- I: preview length is checked


@pytest.mark.parametrize("seconds", ["0", "4", "121", "-5", "long"])
def test_a_preview_length_out_of_range_is_a_usage_error(seconds: str) -> None:
    with pytest.raises(SystemExit):
        cli.create_parser().parse_args(["a.mp3", "--preview", seconds])


# --------------------------------------------------- E: several songs and folders


def test_several_songs_and_folders_are_made_together(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "run_batch", _fake_batch(seen))
    folder = _songs(tmp_path / "Music", "c.mp3")
    loose = _songs(tmp_path / "Loose", "a.mp3", "b.flac")

    code = cli.main([str(loose / "a.mp3"), str(loose / "b.flac"), str(folder)])

    assert code == 0
    assert sorted(item.output.name for item in seen["items"]) == [
        "a (8D).mp3",
        "b (8D).mp3",
        "c (8D).mp3",
    ]


def test_a_song_and_a_folder_are_both_songs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "run_batch", _fake_batch(seen))
    folder = _songs(tmp_path / "Music", "c.mp3")
    song = _songs(tmp_path / "Loose", "a.mp3") / "a.mp3"

    assert cli.main([str(song), str(folder)]) == 0
    assert len(seen["items"]) == 2


def test_two_paths_are_still_song_and_output(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "convert", _recorder(seen))

    assert cli.main(["in.mp3", "out.flac"]) == 0
    assert seen["output_path"] == Path("out.flac")


def test_several_songs_cant_be_previewed_at_once(tmp_path: Path) -> None:
    loose = _songs(tmp_path / "Loose", "a.mp3", "b.mp3", "c.mp3")
    with pytest.raises(SystemExit):
        cli.main(
            [
                str(loose / "a.mp3"),
                str(loose / "b.mp3"),
                str(loose / "c.mp3"),
                "--preview",
            ]
        )


# ------------------------------------------------- J: a song already made is skipped


def test_a_single_song_already_made_is_skipped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "convert", lambda **_: pytest.fail("should not convert"))
    song = _songs(tmp_path, "a.mp3", "a (8D).mp3") / "a.mp3"

    assert cli.main([str(song)]) == 0
    assert "Skipped (already made): a (8D).mp3" in capsys.readouterr().err


def test_overwrite_makes_it_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "convert", _recorder(seen))
    song = _songs(tmp_path, "a.mp3", "a (8D).mp3") / "a.mp3"

    assert cli.main([str(song), "--overwrite"]) == 0
    assert seen["overwrite"] is True


# --------------------------------------------------------------- K: --dry-run


def test_dry_run_shows_the_plan_and_makes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "convert", lambda **_: pytest.fail("should not convert"))

    assert cli.main(["a.mp3", "--dry-run"]) == 0
    shown = capsys.readouterr().err
    assert "Dry run" in shown and "a (8D).mp3" in shown


def test_dry_run_on_a_folder_lists_every_song(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "run_batch", lambda *_a, **_k: pytest.fail("ran"))
    folder = _songs(tmp_path / "Music", "a.mp3", "b.flac")

    assert cli.main([str(folder), "--dry-run", "--format", "flac"]) == 0
    shown = capsys.readouterr().err
    assert "a (8D).flac" in shown and "b (8D).flac" in shown


def test_dry_run_and_preview_dont_mix() -> None:
    with pytest.raises(SystemExit):
        cli.main(["a.mp3", "--dry-run", "--preview"])


# --------------------------------------------------------------- H: --suggest


def test_suggest_names_a_style_for_each_song(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "convert", lambda **_: pytest.fail("should not convert"))
    folder = _songs(tmp_path / "Music", "a.mp3", "b.mp3")

    assert cli.main([str(folder), "--suggest"]) == 0
    shown = capsys.readouterr().out
    assert "a.mp3:" in shown and "b.mp3:" in shown
    assert "For all of them:" in shown and "--style" in shown


# ------------------------------------------------ F and G: your saved styles


def _save(*options: str) -> int:
    return cli.main(["--intensity", "0.9", *options])


def test_saved_styles_can_be_managed_like_in_the_window(tmp_path: Path) -> None:
    assert _save("--save-style", "party mix", "--style-description", "for parties") == 0
    saved = load_user_presets()
    assert saved["Party Mix"].summary == "for parties"

    assert cli.main(["--rename-style", "partymix", "Dance"]) == 0
    assert cli.main(["--duplicate-style", "dance", "Dance Copy"]) == 0
    assert set(load_user_presets()) == {"Dance", "Dance Copy"}

    file = tmp_path / "dance.json"
    assert cli.main(["--export-style", "Dance", str(file)]) == 0
    assert json.loads(file.read_text(encoding="utf-8"))["name"] == "Dance"
    assert cli.main(["--delete-style", "Dance"]) == 0
    assert set(load_user_presets()) == {"Dance Copy"}
    assert cli.main(["--import-style", str(file)]) == 0
    assert cli.main(["--import-style", str(file), "Dance Again"]) == 0
    assert set(load_user_presets()) == {"Dance Copy", "Dance", "Dance Again"}


def test_update_style_starts_from_that_style() -> None:
    assert (
        cli.main(["--style", "smooth", "--ambience", "0.3", "--save-style", "Mine"])
        == 0
    )

    assert cli.main(["--update-style", "mine", "--intensity", "0.7"]) == 0
    mine = load_user_presets()["Mine"].config
    # The saved ambience is kept: only the typed movement changed
    assert (mine.intensity, mine.ambience) == (0.7, 0.3)
    assert mine.path == PRESETS["smooth"].config.path


@pytest.mark.parametrize(
    ("command", "why"),
    [
        (["--rename-style", "studio", "Mine"], "'studio' is a built-in style"),
        (["--update-style", "studio"], "'studio' is a built-in style"),
        (["--delete-style", "Nothing"], "no saved style called 'Nothing'"),
        (["--duplicate-style", "Nothing", "Copy"], "no saved style called 'Nothing'"),
        (["--export-style", "Nothing", "x.json"], "no style called 'Nothing'"),
    ],
)
def test_unknown_and_built_in_styles_are_explained(
    command: list[str], why: str, caplog: pytest.LogCaptureFixture
) -> None:
    assert cli.main(command) == 1
    assert why in caplog.text


def test_style_names_follow_the_windows_rules(caplog: pytest.LogCaptureFixture) -> None:
    assert _save("--save-style", "Mine") == 0
    assert _save("--save-style", "Other") == 0

    assert cli.main(["--rename-style", "Other", "MINE"]) == 1
    assert "already have a style called 'Mine'" in caplog.text
    assert cli.main(["--rename-style", "Other", "Studio"]) == 1
    assert "is a built-in style" in caplog.text


def test_a_style_that_doesnt_move_is_not_saved(
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert cli.main(["--intensity", "0", "--save-style", "Still"]) == 1
    assert "doesn't move the music" in caplog.text
    assert "Still" not in load_user_presets()


def test_a_style_never_keeps_the_speakers_switch() -> None:
    assert _save("--speakers", "--save-style", "Loud") == 0
    assert load_user_presets()["Loud"].config == _config("--intensity", "0.9")


def test_style_description_needs_a_save() -> None:
    with pytest.raises(SystemExit):
        cli.main(["--style-description", "words"])


# ------------------------------------------------ L: cache, logs and --check


def test_clear_cache_forgets_measurements_and_singer_splits(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cache = cli_manage.cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "loudness.json").write_text("{}", encoding="utf-8")

    assert cli.main(["--clear-cache"]) == 0
    assert not (cache / "loudness.json").exists()
    assert "cleared" in capsys.readouterr().out


def test_delete_logs_deletes_the_saved_logs(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--delete-logs"]) == 0
    assert "log file" in capsys.readouterr().out
