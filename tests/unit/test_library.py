# Developed by ::> Gehan Fernando
"""Checks the song list behind the window: styles for many songs at once."""

import time
from pathlib import Path

import pytest

from src import library
from src.core.presets import PRESETS
from src.core.types import AudioStreamInfo
from src.library import (
    READY,
    UNREADABLE,
    Library,
    ViewOptions,
    assign,
    change_default,
    counts,
    follows_default,
    forget_missing_styles,
    reset,
    style_of,
)


def _info(genre: str | None, artist: str = "", album: str = "") -> AudioStreamInfo:
    """What reading a song file might find."""
    return AudioStreamInfo(
        "mp3", 2, 44100, 200.0, 320_000, genre=genre, artist=artist or None,
        album=album or None,
    )  # fmt: skip


def _library(*songs: tuple[str, str | None]) -> Library:
    """A list of read songs: (name, genre) pairs."""
    made = Library()
    for name, genre in songs:
        track = made.add(Path(f"music/{name}.mp3"))
        assert track is not None
        track.info, track.state = _info(genre, artist=f"{name} band"), READY
    return made


def _names(groups) -> list[str]:
    """Song names in the order a view shows them."""
    return [track.name for group in groups for track in group.tracks]


# ------------------------------------------------------------ default and own


def test_every_song_follows_the_default_until_given_its_own() -> None:
    overrides: dict[Path, str] = {}
    song = Path("a.mp3")

    assert style_of(overrides, "studio", song) == "studio"
    assert follows_default(overrides, song)
    assert assign(overrides, "studio", [song], "groove") == 1
    assert style_of(overrides, "studio", song) == "groove"
    assert not follows_default(overrides, song)


def test_giving_a_song_the_default_style_removes_its_override() -> None:
    overrides = {Path("a.mp3"): "groove"}

    assert assign(overrides, "studio", [Path("a.mp3")], "studio") == 1
    assert not overrides
    # Nothing changes the second time
    assert assign(overrides, "studio", [Path("a.mp3")], "studio") == 0


def test_changing_the_default_keeps_other_songs_own_styles() -> None:
    overrides = {Path("a.mp3"): "groove", Path("b.mp3"): "voice"}

    folded = change_default(overrides, "groove")

    # a now simply follows the new default; b keeps its own style
    assert folded == 1
    assert overrides == {Path("b.mp3"): "voice"}
    assert style_of(overrides, "groove", Path("a.mp3")) == "groove"
    assert style_of(overrides, "groove", Path("c.mp3")) == "groove"


def test_resetting_songs_brings_them_back_to_the_default() -> None:
    overrides = {Path("a.mp3"): "groove", Path("b.mp3"): "voice"}

    assert reset(overrides, [Path("a.mp3"), Path("x.mp3")]) == 1
    assert overrides == {Path("b.mp3"): "voice"}
    assert reset(overrides, list(overrides)) == 1
    assert not overrides


def test_a_deleted_style_sends_its_songs_back_to_the_default() -> None:
    overrides = {Path("a.mp3"): "Gone", Path("b.mp3"): "voice"}

    assert forget_missing_styles(overrides, PRESETS) == [Path("a.mp3")]
    assert overrides == {Path("b.mp3"): "voice"}


def test_bulk_assignment_changes_hundreds_of_songs_in_one_action() -> None:
    songs = [Path(f"s{n}.mp3") for n in range(300)]
    overrides: dict[Path, str] = {}

    assert assign(overrides, "studio", songs[:120], "groove") == 120
    assert assign(overrides, "studio", songs[100:150], "voice") == 50
    assert sum(1 for s in songs if overrides.get(s) == "groove") == 100
    assert sum(1 for s in songs if overrides.get(s) == "voice") == 50


# ------------------------------------------------------------ the list


def test_songs_are_added_once_and_removed_cleanly() -> None:
    made = Library()
    first = made.add(Path("a.mp3"), Path("music"))

    assert first is not None and first.folder == Path("music")
    assert made.add(Path("a.mp3")) is None
    assert Path("a.mp3") in made and len(made) == 1
    assert made.remove([Path("a.mp3"), Path("nope.mp3")]) == [first]
    assert len(made) == 0


def test_suggested_styles_are_used_only_where_they_are_sure() -> None:
    made = _library(("Anchor", "Rock"), ("Night", "House"), ("Demo", None))
    made.tracks.append(library.Track(Path("music/broken.mp3"), state=UNREADABLE))
    overrides: dict[Path, str] = {}

    changed, unsure = made.apply_suggestions(overrides, "studio")

    assert changed == 2 and unsure == 1
    assert overrides == {
        Path("music/Anchor.mp3"): "strong",
        Path("music/Night.mp3"): "groove",
    }
    # Only the selected songs, when some are given
    overrides.clear()
    night = made.get(Path("music/Night.mp3"))
    assert night is not None
    only = [night]
    assert made.apply_suggestions(overrides, "studio", only) == (1, 0)
    assert overrides == {Path("music/Night.mp3"): "groove"}


def test_a_suggestion_that_equals_the_default_leaves_the_song_following_it() -> None:
    made = _library(("Anchor", "Rock"))
    overrides: dict[Path, str] = {}

    made.apply_suggestions(overrides, "strong")

    assert not overrides


def test_suggestions_are_worked_out_once_per_song(monkeypatch) -> None:
    made = _library(("Anchor", "Rock"), ("Night", "House"))
    calls: list[str] = []
    real = library.recommend

    def counting(facts, styles):
        calls.append(facts.genre)
        return real(facts, styles)

    monkeypatch.setattr(library, "recommend", counting)
    for _ in range(5):
        for track in made.tracks:
            made.suggestion(track)
    assert len(calls) == 2
    # A described mood or new styles do count as a change
    made.tracks[0].mood = "calm"
    made.suggestion(made.tracks[0])
    made.use_styles(PRESETS)
    made.suggestion(made.tracks[1])
    assert len(calls) == 4


def test_filters_show_the_songs_that_differ_from_the_default() -> None:
    made = _library(("Anchor", "Rock"), ("Night", "House"), ("Demo", None))
    made.tracks.append(library.Track(Path("music/broken.mp3"), state=UNREADABLE))
    overrides = {Path("music/Anchor.mp3"): "strong"}

    def shown(which: str) -> list[str]:
        return _names(made.view(ViewOptions(filter=which), overrides, "studio"))

    assert shown("all") == ["Anchor", "Night", "Demo", "broken"]
    assert shown("own") == ["Anchor"]
    assert shown("default") == ["Night", "Demo", "broken"]
    # Night is House, suggested Groove, but still on Studio
    assert shown("suggestion") == ["Night"]
    assert shown("no-genre") == ["Demo"]
    assert shown("problems") == ["broken"]


def test_search_sort_and_group() -> None:
    made = _library(("Anchor", "Rock"), ("Night", "House"), ("Blue", "Jazz"))
    made.tracks[1].info = _info("House", artist="Neon", album="Drive")

    search = made.view(ViewOptions(query="neon"), {}, "studio")
    assert _names(search) == ["Night"]
    by_name = made.view(ViewOptions(sort="name"), {}, "studio")
    assert _names(by_name) == ["Anchor", "Blue", "Night"]
    backwards = made.view(ViewOptions(sort="name", descending=True), {}, "studio")
    assert _names(backwards) == ["Night", "Blue", "Anchor"]
    groups = made.view(
        ViewOptions(group="suggested"), {}, "studio", lambda n: PRESETS[n].label
    )
    assert [(g.title, _names([g])) for g in groups] == [
        ("Gentle", ["Blue"]),
        ("Groove", ["Night"]),
        ("Strong", ["Anchor"]),
    ]
    styles = made.view(
        ViewOptions(group="style"),
        {Path("music/Anchor.mp3"): "strong"},
        "studio",
        lambda n: PRESETS[n].label,
    )
    assert [g.title for g in styles] == ["Strong", "Studio (the default)"]


def test_songs_without_information_are_grouped_last() -> None:
    made = _library(("Demo", None), ("Anchor", "Rock"))

    groups = made.view(ViewOptions(group="genre"), {}, "studio")

    assert [g.title for g in groups] == ["Rock", "No genre information"]


def test_counts_for_the_status_lines() -> None:
    made = _library(("Anchor", "Rock"), ("Night", "House"))
    made.add(Path("music/new.mp3"))

    assert counts(made.tracks, {Path("music/Anchor.mp3"): "strong"}) == {
        "total": 3,
        "own": 1,
        "default": 2,
        "reading": 1,
        "unreadable": 0,
    }


@pytest.mark.parametrize("size", [300, 1000])
def test_big_lists_stay_quick(size: int) -> None:
    genres = ["Rock", "House", "Folk", "Jazz", None, "Hip-Hop; Lo-Fi", "Podcast"]
    made = _library(*((f"song {n:04}", genres[n % len(genres)]) for n in range(size)))
    overrides: dict[Path, str] = {}

    started = time.perf_counter()
    made.apply_suggestions(overrides, "studio")
    for group in ("none", "genre", "suggested", "style"):
        made.view(ViewOptions(group=group, sort="style"), overrides, "studio")
    batch = made.batch_suggestion()
    seconds = time.perf_counter() - started

    assert seconds < 3.0, seconds
    assert len(overrides) > size / 2
    assert batch.total == size
