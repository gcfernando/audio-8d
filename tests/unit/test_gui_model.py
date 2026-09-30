# Developed by ::> Gehan Fernando
"""Checks the window's decisions: settings to jobs, validation and plain words."""

import dataclasses
import os
import re
from pathlib import Path

import pytest

from src import PRESETS, InputValidationError
from src.cli import _output_for, create_parser, plan_from_args
from src.core.types import AudioStreamInfo
from src.gui_model import (
    GuiSettings,
    can_write,
    config_for,
    destination_problem,
    file_value,
    gui_words,
    has_own_files,
    items_for,
    long_paths,
    name_clashes,
    options_for,
    problems,
    reset_file_settings,
    reset_sound_settings,
    set_file_settings,
    set_sound_settings,
    singer_songs,
    song_config,
    typed_sound,
    warnings,
    with_output,
)
from src.gui_summary import (
    describe,
    describe_curve,
    file_short,
    plan_summary,
    song_plan,
    source_notes,
    style_label,
)
from src.style_creator import (
    MUSIC_CHOICES,
    StyleAnswers,
    guided_config,
    improve_answers,
    improved,
    style_check,
    style_summary,
    suggested_answers,
    suggested_description,
    suggested_name,
)

_SONG = [(Path("music/a.mp3"), None)]


def _settings(style: str = "studio") -> GuiSettings:
    """Settings as the window starts: the chosen style applied."""
    settings = GuiSettings()
    settings.apply_style(PRESETS[style])
    return settings


def test_the_window_starts_with_the_best_style() -> None:
    settings = GuiSettings()
    settings.apply_style(PRESETS["studio"])

    assert config_for(settings) == PRESETS["studio"].config
    assert not settings.differs_from(PRESETS["studio"])
    assert not problems(settings, _SONG)


def test_every_style_is_usable_from_the_window() -> None:
    for name in PRESETS:
        assert config_for(_settings(name)) == PRESETS[name].config


def test_typed_curves_bpm_and_loudness_reach_the_config() -> None:
    settings = _settings()
    settings.speed_curve_text = "0=10, 1:00=6"
    settings.intensity_curve_text = "0=0.5, 1:00=0.9"
    settings.bpm_text = "128"
    settings.loudness_is_custom = True
    settings.custom_loudness_text = "-16"
    config = config_for(settings)

    assert config.speed_curve == ((0.0, 10.0), (60.0, 6.0))
    assert config.intensity_curve == ((0.0, 0.5), (60.0, 0.9))
    assert config.bpm == 128
    assert config.loudness_target == -16
    assert settings.differs_from(PRESETS["studio"])


@pytest.mark.parametrize(
    ("field", "text"),
    [
        ("speed_curve_text", "fast"),
        ("intensity_curve_text", "0=2"),
        ("bpm_text", "500"),
        ("bpm_text", "abc"),
    ],
)
def test_bad_typed_values_are_caught_before_converting(field: str, text: str) -> None:
    settings = _settings()
    setattr(settings, field, text)

    with pytest.raises(InputValidationError):
        config_for(settings)
    assert problems(settings, _SONG)


def test_custom_loudness_must_be_in_range() -> None:
    settings = _settings()
    settings.loudness_is_custom = True
    settings.custom_loudness_text = "-40"

    assert any("loudness" in text.lower() for _, text in problems(settings, _SONG))


def test_speakers_switch_uses_the_same_rules_as_the_command_line() -> None:
    settings = _settings("strong")
    settings.speakers = True
    config = config_for(settings)

    assert config.engine == "pan"
    assert config.intensity <= 0.6


def test_output_paths_match_the_command_line() -> None:
    settings = _settings()
    folder = Path("Music")
    songs = [(folder / "Rock" / "b.flac", folder)]
    settings.destination = "Out"

    assert items_for(settings, songs)[0].output == Path("Out/Rock/b (8D).mp3")
    settings.destination = ""
    settings.originals = "replace"
    assert items_for(settings, songs)[0].output == folder / "Rock" / "b.mp3"
    settings.originals = "replace-8d"
    assert items_for(settings, songs)[0].output == folder / "Rock" / "b (8D).mp3"
    assert options_for(settings).replace_original is True


def test_custom_name_only_for_one_song() -> None:
    settings = _settings()
    settings.change(output_format="flac")
    settings.name_style = "custom"
    settings.custom_name = "My version.mp3"

    assert items_for(settings, _SONG)[0].output == Path("music/My version.flac")
    two = _SONG + [(Path("music/b.mp3"), None)]
    assert any("one song" in text for _, text in problems(settings, two))
    settings.custom_name = "bad:name"
    assert any("can't contain" in text for _, text in problems(settings, _SONG))


def test_original_name_next_to_the_original_is_refused(tmp_path: Path) -> None:
    settings = _settings()
    settings.name_style = "original"

    assert any("overwrite" in text for _, text in problems(settings, _SONG))
    settings.destination = str(tmp_path / "Elsewhere")
    assert not problems(settings, _SONG)


def test_trim_and_nothing_to_convert_are_explained() -> None:
    settings = _settings()
    settings.trim_start, settings.trim_end = "2:00", "1:00"

    found = problems(settings, [])
    pages = {page for page, _ in found}
    assert {"songs", "output"} <= pages
    settings.trim_start, settings.trim_end = "1:00", "1:30"
    trim = options_for(settings).trim
    assert trim is not None and (trim.start, trim.end) == (60, 90)


def test_warnings_use_the_windows_words() -> None:
    settings = _settings("whirlwind")
    settings.originals = "replace"
    notes = " ".join(warnings(settings))

    assert "dizzy" in notes
    assert "Recycle Bin" in notes
    assert "--" not in notes


def test_gui_words_replace_command_line_flags() -> None:
    assert gui_words("Try --intensity 0.8") == "Try Movement 0.8 (Customize, Advanced)"
    assert "Match music apps (Output)" in gui_words("Add --loudness -14 to fix it.")
    assert "--" not in gui_words("add --overwrite to replace it")


def test_a_curve_out_of_range_names_its_box() -> None:
    settings = GuiSettings(intensity_curve_text="0=0.5, 1:00=1.5")

    found = problems(settings, [(Path("a.mp3"), None)])

    assert found == [("sound", "Movement over time values must be between 0 and 1")]


def test_the_plan_describes_everything_in_words() -> None:
    settings = _settings()
    rows = dict(plan_summary(settings, _SONG, PRESETS))

    # A short summary before creating: it sums up, it doesn't list every setting
    labels = ["Songs", "Sound", "Output", "Loudness", "Folder", "File names"]
    assert list(rows) == labels
    assert rows["Songs"] == "1 song"
    assert rows["Sound"] == "Studio"
    assert rows["Output"] == "MP3, High quality"
    assert rows["Loudness"] == "Match music apps"
    assert rows["Folder"] == "Next to each original song"
    assert describe(settings).startswith("3D · circle · 8 s · MP3 · -14 LUFS")
    assert describe_curve("0=10, 1:00=6", " s") == "10 s at 0:00, then 6 s at 1:00"


# README checklist rows: a window change, then the terminal words that must match it
_PARITY = [
    ("spin", lambda s: s.change(rotation_seconds=12.0), ["--rotation-seconds", "12"]),
    ("movement", lambda s: s.change(intensity=0.6), ["--intensity", "0.6"]),
    ("room", lambda s: s.change(ambience=0.1), ["--ambience", "0.1"]),
    ("engine", lambda s: s.change(engine="pan"), ["--engine", "pan"]),
    ("path", lambda s: s.change(path="figure8"), ["--path", "figure8"]),
    (
        "direction",
        lambda s: s.change(direction="counterclockwise"),
        ["--direction", "counterclockwise"],
    ),
    ("bass off", lambda s: s.change(bass_hz=0.0), ["--bass", "off"]),
    ("bass below", lambda s: s.change(bass_hz=200.0), ["--bass", "200"]),
    ("height", lambda s: s.change(elevation=0.5), ["--elevation", "0.5"]),
    ("ease", lambda s: s.change(fade_seconds=0.0), ["--fade", "0"]),
    (
        "speed curve",
        lambda s: setattr(s, "speed_curve_text", "0=10, 1:00=6"),
        ["--speed-curve", "0=10, 1:00=6"],
    ),
    (
        "movement curve",
        lambda s: setattr(s, "intensity_curve_text", "0=0.5, 1:00=0.9"),
        ["--intensity-curve", "0=0.5, 1:00=0.9"],
    ),
    ("beat", lambda s: s.change(beat_sync=True), ["--beat-sync"]),
    (
        "tempo",
        lambda s: (s.change(beat_sync=True), setattr(s, "bpm_text", "128")),
        ["--beat-sync", "--bpm", "128"],
    ),
    ("singer", lambda s: s.change(vocals="center"), ["--vocals", "center"]),
    ("speakers", lambda s: setattr(s, "speakers", True), ["--speakers"]),
    ("file type", lambda s: s.change(output_format="flac"), ["--format", "flac"]),
    ("bitrate", lambda s: s.change(bitrate=192), ["--bitrate", "192"]),
    (
        "mp3 quality",
        lambda s: s.change(bitrate=None, quality=4),
        ["--bitrate", "auto", "--quality", "4"],
    ),
    (
        "apple loudness",
        lambda s: s.change(loudness_target=-16.0),
        ["--loudness", "-16"],
    ),
    (
        "same as original",
        lambda s: s.change(match_loudness=True, loudness_target=None),
        ["--loudness", "match"],
    ),
    ("natural", lambda s: s.change(loudness_target=None), ["--loudness", "off"]),
    (
        "custom loudness",
        lambda s: (
            setattr(s, "loudness_is_custom", True),
            setattr(s, "custom_loudness_text", "-12"),
        ),
        ["--loudness", "-12"],
    ),
    ("exact", lambda s: s.change(exact_loudness=True), ["--exact-loudness"]),
    (
        "peak roof",
        lambda s: s.change(limiter_ceiling=0.9),
        ["--limiter-ceiling", "0.9"],
    ),
    (
        "trim",
        lambda s: (setattr(s, "trim_start", "1:00"), setattr(s, "trim_end", "1:30")),
        ["--start", "1:00", "--end", "1:30"],
    ),
    ("folder", lambda s: setattr(s, "destination", "Out"), ["--output-dir", "Out"]),
    (
        "same name elsewhere",
        lambda s: (
            setattr(s, "destination", "Out"),
            setattr(s, "name_style", "original"),
        ),
        ["--output-dir", "Out", "--name", "original"],
    ),
    ("replace", lambda s: setattr(s, "originals", "replace"), ["--replace"]),
    (
        "replace keep 8d",
        lambda s: setattr(s, "originals", "replace-8d"),
        ["--replace", "--name", "8d"],
    ),
    ("overwrite", lambda s: setattr(s, "overwrite", True), ["--overwrite"]),
    ("no cover", lambda s: setattr(s, "keep_cover", False), ["--no-cover"]),
    ("keep title", lambda s: setattr(s, "tag_title", False), ["--keep-title"]),
    ("no check", lambda s: setattr(s, "check", False), ["--no-check"]),
    ("jobs", lambda s: setattr(s, "jobs", 3), ["--jobs", "3"]),
]


@pytest.mark.parametrize(
    ("window", "words"),
    [row[1:] for row in _PARITY],
    ids=[row[0] for row in _PARITY],
)
def test_every_window_control_matches_its_terminal_option(window, words) -> None:
    settings = _settings()
    settings.recursive = False
    window(settings)
    plan = plan_from_args(
        create_parser().parse_args(["music", "--preset", "studio", *words])
    )
    song = Path("music/Rock/b.flac")

    assert config_for(settings) == plan.config
    assert options_for(settings) == plan.options
    assert items_for(settings, [(song, Path("music"))])[0].output == _output_for(
        song, plan, Path("music")
    )
    assert settings.overwrite == plan.overwrite
    if "--jobs" in words:
        assert settings.jobs == plan.jobs


def test_no_hint_shows_terminal_words_in_the_window() -> None:
    # pylint: disable-next=import-outside-toplevel,protected-access
    from src.hints import _ANYWHERE_FIXES, _FIXES

    for _, fix in _FIXES + _ANYWHERE_FIXES:
        shown = gui_words(fix)
        assert not re.search(r"--[a-z]|audio8d |python -", shown), shown


# ------------------------------------------------------ styles per song

_TWO = [(Path("music/a.mp3"), None), (Path("music/b.mp3"), None)]


def test_one_style_for_every_song_is_still_the_default() -> None:
    settings = _settings("studio")
    items = items_for(settings, _TWO, PRESETS)

    assert [item.config for item in items] == [None, None]
    assert [item.output.name for item in items] == ["a (8D).mp3", "b (8D).mp3"]
    assert dict(plan_summary(settings, _TWO, PRESETS))["Sound"] == "Studio"
    assert "custom" not in describe(settings)


def test_a_song_can_have_a_style_of_its_own() -> None:
    settings = _settings("studio")
    settings.song_styles[Path("music/b.mp3")] = "groove"
    items = items_for(settings, _TWO, PRESETS)

    assert items[0].config is None
    # Its own style's sound, with the file settings chosen for every song
    assert items[1].config is not None
    assert items[1].config.path == "figure8" and items[1].config.beat_sync
    assert items[1].config.output_format == "mp3"
    assert items[1].config.loudness_target == config_for(settings).loudness_target
    assert items[1].output.name == "b (8D).mp3"
    assert song_config(settings, Path("music/b.mp3"), PRESETS) == items[1].config
    assert song_config(settings, Path("music/a.mp3"), PRESETS) == config_for(settings)
    assert dict(plan_summary(settings, _TWO, PRESETS))["Sound"] == (
        "Studio; 1 song has custom settings"
    )
    assert "1 custom song" in describe(settings)
    assert not problems(settings, _TWO, PRESETS)


def test_a_song_whose_style_is_gone_must_be_fixed_first() -> None:
    settings = _settings("studio")
    settings.song_styles[Path("music/b.mp3")] = "Deleted"

    found = problems(settings, _TWO, PRESETS)
    assert found == [
        (
            "sound",
            "'b' uses the style 'Deleted', which no longer exists. "
            "Choose another style for it.",
        )
    ]


def test_many_own_styles_are_summed_up_briefly() -> None:
    songs = [(Path(f"s{n}.mp3"), None) for n in range(5)]
    settings = _settings("studio")
    for song, _folder in songs[:3]:
        settings.song_styles[song] = "voice"
    for song, _folder in songs[3:]:
        settings.song_styles[song] = "groove"

    line = dict(plan_summary(settings, songs, PRESETS))["Sound"]
    assert line == "Studio; 5 songs have custom settings"


def test_built_in_style_names_are_shown_capitalised() -> None:
    assert PRESETS["studio"].label == "Studio"
    assert PRESETS["gentle"].label == "Gentle"
    assert style_label("studio") == "Studio"
    assert style_label("unknown") == "unknown"
    # Only what people see changes; the names they type stay the same
    assert "studio" in PRESETS and "Studio" not in PRESETS
    rows = dict(plan_summary(_settings("gentle"), _SONG, PRESETS))
    assert rows["Sound"] == "Gentle"
    assert gui_words("Try --style studio") == (
        "Try the Studio style (Change style, step 2)"
    )


# ------------------------------------------------------ creating a style


@pytest.mark.parametrize("music", list(MUSIC_CHOICES.values()))
def test_every_kind_of_music_makes_a_good_complete_style(music: str) -> None:
    answers = suggested_answers(music)
    config = guided_config(answers)

    config.validate()
    assert not style_check(config, suggested_description(answers))
    assert config.intensity > 0
    assert suggested_name(answers, []).endswith("Mix")


def test_the_answers_turn_into_the_right_settings() -> None:
    config = guided_config(
        StyleAnswers(music="calm", movement="strong", speed="beat", room="spacious")
    )

    # The same values as the Customize choices and --movement/--speed/--space
    assert config.intensity == 0.95 and config.beat_sync
    assert config.ambience == 0.45
    # A style is only the sound: it is always saved the standard way
    assert config.output_format == "mp3" and config.loudness_target == -14.0
    speakers = guided_config(StyleAnswers(place="speakers", movement="strong"))
    assert speakers.engine == "pan" and speakers.intensity <= 0.6


def test_a_suggested_name_is_always_free() -> None:
    answers = suggested_answers("calm")

    assert suggested_name(answers, []) == "Calm Mix"
    # Taken names count however they're written: CalmMix is Calm Mix
    assert suggested_name(answers, ["CalmMix", "calm mix 2"]) == "Calm Mix 3"


def test_the_quality_check_finds_weak_styles_and_can_fix_them() -> None:
    config = dataclasses.replace(
        PRESETS["studio"].config, intensity=0.0, ambience=0.9, loudness_target=None
    )
    notes = style_check(config, "")

    # A style is only the sound: its loudness is chosen on Output, never advised here
    assert [note.level for note in notes] == ["error", "warning", "tip"]
    assert "no 8D effect" in notes[0].text
    better = improved(config, notes)
    assert better.intensity == 0.8 and better.ambience == 0.25
    assert [note.level for note in style_check(better, "why")] == []


def test_improving_answers_follows_the_advice() -> None:
    answers = StyleAnswers(speed="fast", room="spacious")
    config = dataclasses.replace(guided_config(answers), rotation_seconds=3.0)
    notes = style_check(config, "x")

    assert improve_answers(answers, notes).speed == "normal"
    assert not style_check(guided_config(improve_answers(answers, notes)), "x")


def test_a_style_summary_is_plain_words() -> None:
    text = style_summary(guided_config(suggested_answers("talk")))

    assert "front" in text and "dry" in text
    # Only the sound: speed, movement and space, never the file
    assert text.count("\n") == 3 and "Loudness" not in text


def test_the_song_files_themselves_get_honest_heads_ups() -> None:
    good = AudioStreamInfo("flac", 2, 44100, 60.0, 900_000)
    best_mp3 = AudioStreamInfo("mp3", 2, 44100, 60.0, 320_000)
    small = AudioStreamInfo("mp3", 2, 44100, 60.0, 128_000)
    memo = AudioStreamInfo("aac", 1, 16000, 30.0, 64_000)

    assert not source_notes([("A", good), ("B", best_mp3)])
    notes = source_notes([("Small", small), ("Memo", memo), ("A", good)])
    assert len(notes) == 2
    low, thin = notes[0], notes[1]
    assert low.startswith("2 songs are low-quality files (Small, Memo)")
    assert "use a better copy" in low
    assert thin.startswith("1 song is a low-detail recording (Memo)")
    many = source_notes([(f"S{n}", small) for n in range(4)])[0]
    assert "(S0, S1 and others)" in many


# ------------------------------------------------------ output settings


def test_output_settings_apply_to_every_song_whatever_its_style() -> None:
    settings = _settings("studio")
    settings.change(output_format="flac", loudness_target=None, match_loudness=True)
    settings.song_styles[Path("music/b.mp3")] = "voice"

    own = song_config(settings, Path("music/b.mp3"), PRESETS)
    assert own.output_format == "flac" and own.match_loudness
    assert own.path == "arc"  # the Voice style's own sound
    assert with_output(PRESETS["voice"].config, config_for(settings)) == own


def test_choosing_a_style_never_changes_the_output() -> None:
    settings = _settings("studio")
    settings.change(output_format="m4a")
    # The quality tier and a fitting peak limit follow the new format
    assert settings.sound.bitrate == 256 and settings.sound.limiter_ceiling == 0.84
    settings.apply_style(PRESETS["groove"])
    assert settings.sound.output_format == "m4a"
    assert settings.sound.path == "figure8"
    settings.change(output_format="flac")
    assert settings.sound.limiter_ceiling == 0.89
    settings.reset_output()
    assert settings.sound.output_format == "mp3" and settings.sound.bitrate == 320


def test_songs_that_would_share_a_name_get_their_own() -> None:
    settings = _settings()
    settings.destination = str(Path.cwd() / "Out")
    songs = [(Path("a/Intro.mp3"), None), (Path("b/Intro.mp3"), None),
             (Path("c/intro.mp3"), None)]  # fmt: skip

    names = [item.output.name for item in items_for(settings, songs)]

    assert names == ["Intro (8D).mp3", "Intro (8D) (2).mp3", "intro (8D) (3).mp3"]
    assert name_clashes(settings, songs) == 2
    settings.destination = ""
    assert name_clashes(settings, songs) == 0


def test_a_new_file_never_takes_another_songs_name(tmp_path: Path) -> None:
    settings = _settings()
    settings.name_style, settings.originals = "original", "replace"
    flac, mp3 = tmp_path / "a.flac", tmp_path / "a.mp3"
    songs = [(flac, None), (mp3, None)]

    items = items_for(settings, songs)

    # a.flac would become a.mp3, which is the other song: it gets its own name
    assert [(i.source, i.output.name) for i in items] == [
        (flac, "a (2).mp3"),
        (mp3, "a.mp3"),
    ]
    assert name_clashes(settings, songs) == 1


def _problem(text: str) -> str:
    problem = destination_problem(text)
    assert problem is not None, text
    return problem


def test_the_save_folder_is_checked_before_converting(tmp_path: Path) -> None:
    assert destination_problem("") is None
    assert "complete folder" in _problem("relative\folder")
    assert destination_problem(str(tmp_path / "new" / "deeper")) is None
    file = tmp_path / "file.txt"
    file.write_text("x", encoding="utf-8")
    assert "is a file" in _problem(str(file))
    assert "is a file" in _problem(str(file / "inside"))
    if os.name == "nt":
        missing = next(
            f"{letter}:\\"
            for letter in "QRSTUVWXYZ"
            if not Path(f"{letter}:\\").exists()
        )
        assert "isn't available" in _problem(missing + "Music")
    assert can_write(tmp_path / "not yet made") is None
    assert not list(tmp_path.glob(".audio8d-check-*"))


def test_very_long_paths_are_pointed_out() -> None:
    settings = _settings()
    settings.destination = "C:\\" + "\\".join(["folder" * 5] * 8)
    items = items_for(settings, [(Path("a.mp3"), None)])

    assert long_paths(items) == items


# ------------------------------------------------------ file settings per song


def test_each_song_can_have_its_own_file_type_and_loudness() -> None:
    settings = _settings("studio")
    songs = [(Path("music/a.mp3"), None), (Path("music/b.mp3"), None)]
    b = Path("music/b.mp3")

    own = set_file_settings(
        settings, [b], output_format="flac", loudness_target=None, match_loudness=True
    )
    assert own == 1
    items = items_for(settings, songs)

    assert items[0].config is None and items[0].output.name == "a (8D).mp3"
    assert items[1].output.name == "b (8D).flac"
    own_config = items[1].config
    assert own_config is not None
    assert own_config.output_format == "flac" and own_config.match_loudness
    # Its sound is still the default style's
    assert own_config.path == config_for(settings).path
    assert song_config(settings, b) == items[1].config
    assert file_short(settings, b) == "FLAC, own loudness"
    rows = dict(plan_summary(settings, songs))
    assert rows["Sound"] == "Studio; 1 song has custom settings"


def test_file_settings_equal_to_the_defaults_simply_follow_them() -> None:
    settings = _settings("studio")
    song = Path("a.mp3")

    assert set_file_settings(settings, [song], output_format="mp3") == 0
    assert not has_own_files(settings, song)
    set_file_settings(settings, [song], output_format="m4a")
    set_file_settings(settings, [song], output_format="mp3")
    assert not settings.song_files


def test_a_song_can_have_its_own_art_title_and_part() -> None:
    settings = _settings("studio")
    song = Path("a.mp3")
    set_file_settings(settings, [song], keep_cover=False, tag_title=False,
                      trim_start="0:10", trim_end="0:40")  # fmt: skip

    options = items_for(settings, [(song, None)])[0].options
    assert options is not None
    assert not options.keep_cover and not options.tag_title
    assert options.trim is not None
    assert (options.trim.start, options.trim.end) == (10.0, 40.0)
    # Other songs keep the defaults
    assert items_for(settings, [(Path("b.mp3"), None)])[0].options is None
    assert file_value(settings, Path("b.mp3"), "keep_cover") is True


def test_a_songs_unusable_file_settings_are_named() -> None:
    settings = _settings("studio")
    song = Path("music/Night Drive.mp3")
    set_file_settings(settings, [song], trim_start="later")

    found = problems(settings, [(song, None)])
    assert found and found[0][0] == "output"
    assert "'Night Drive' has settings that can't be used" in found[0][1]
    assert reset_file_settings(settings, [song]) == 1
    assert not problems(settings, [(song, None)])


def test_the_plan_lists_every_song_as_it_will_be_made() -> None:
    settings = _settings("studio")
    songs = [(Path("music/a.mp3"), None), (Path("music/b.mp3"), None)]
    settings.song_styles[Path("music/a.mp3")] = "groove"
    set_file_settings(settings, [Path("music/b.mp3")], output_format="wav")

    plan = song_plan(settings, songs, PRESETS)
    assert plan[0][1:3] == ("Groove (custom)", "MP3 320, -14 LUFS")
    assert plan[1][1:3] == ("Studio (custom)", "WAV, -14 LUFS")
    assert plan[1][3].endswith("b (8D).wav")


def test_unknown_file_settings_are_refused() -> None:
    with pytest.raises(ValueError, match="Not a file setting"):
        set_file_settings(_settings(), [Path("a.mp3")], intensity=0.5)


def test_each_song_can_have_a_sound_of_its_own() -> None:
    settings = _settings("studio")
    a, b = Path("music/a.mp3"), Path("music/b.mp3")
    own = set_sound_settings(settings, [a], intensity=0.5, vocals="center")

    assert own == 1
    assert song_config(settings, a).intensity == 0.5
    assert song_config(settings, a).vocals == "center"
    # The other song is untouched, and so is the default
    assert song_config(settings, b).intensity == PRESETS["studio"].config.intensity
    assert song_config(settings, b).vocals == "move"
    assert settings.sound.intensity == PRESETS["studio"].config.intensity
    assert singer_songs(settings, [(a, None), (b, None)]) == [a]
    items = items_for(settings, [(a, None), (b, None)])
    assert items[0].config is not None and items[0].config.intensity == 0.5
    assert items[1].config is None


def test_a_songs_sound_equal_to_its_style_is_no_exception() -> None:
    settings = _settings("studio")
    song = Path("a.mp3")
    set_sound_settings(settings, [song], intensity=0.5)
    set_sound_settings(settings, [song], intensity=PRESETS["studio"].config.intensity)
    assert not settings.song_sound

    # A song with its own style is compared with that style
    styled = Path("b.mp3")
    settings.song_styles[styled] = "smooth"
    set_sound_settings(
        settings, [styled], PRESETS, intensity=PRESETS["smooth"].config.intensity
    )
    assert styled not in settings.song_sound


def test_a_songs_sound_can_be_reset_and_bad_values_refused() -> None:
    settings = _settings("studio")
    song = Path("a.mp3")
    set_sound_settings(settings, [song], engine="pan", speakers=True)
    assert song_config(settings, song).engine == "pan"
    assert reset_sound_settings(settings, [song]) == 1
    assert song_config(settings, song).engine == "3d"
    with pytest.raises(InputValidationError):
        set_sound_settings(settings, [song], intensity=4.0)
    with pytest.raises(ValueError):
        set_sound_settings(settings, [song], output_format="flac")
    assert not settings.song_sound


def test_typed_tempos_and_curves_become_song_settings() -> None:
    assert typed_sound("bpm_text", "128") == {"bpm": 128.0, "beat_sync": True}
    assert typed_sound("bpm_text", "") == {"bpm": None}
    assert typed_sound("speed_curve_text", "0=10, 1:00=6") == {
        "speed_curve": ((0.0, 10.0), (60.0, 6.0))
    }
    with pytest.raises(InputValidationError):
        typed_sound("bpm_text", "fast")
    with pytest.raises(InputValidationError, match="Changes over time"):
        typed_sound("intensity_curve_text", "later=0.5")


def test_the_plan_names_fine_tuned_and_singer_songs() -> None:
    settings = _settings("studio")
    songs = [(Path("a.mp3"), None), (Path("b.mp3"), None)]
    set_sound_settings(settings, [Path("a.mp3")], vocals="center")
    rows = dict(plan_summary(settings, songs))

    assert rows["Sound"] == "Studio; 1 song has custom settings"
    assert "uses the add-on" in rows["Singer in the middle"]
    assert "(custom)" in song_plan(settings, songs)[0][1]
    assert "1 custom song" in describe(settings)
    assert any("singer" in note for note in warnings(settings, 1))
