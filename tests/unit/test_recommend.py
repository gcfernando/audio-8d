# Developed by ::> Gehan Fernando
"""Checks the style suggestions: genre reading, mixing genres, and plain reasons."""

import re
from dataclasses import replace

import pytest

from src.core.genres import display_name, family_of, read_genres, split_genres
from src.core.presets import PRESETS, Preset
from src.core.style_guide import GUIDES, closest_built_in, guide_for, same_sound
from src.recommend import (
    AFFINITY,
    MOODS,
    PAIRS,
    SongFacts,
    batch_suggestion,
    recommend,
)

# ------------------------------------------------------------ reading genres


@pytest.mark.parametrize(
    ("tag", "names"),
    [
        ("Rock; Electronic", ["rock", "electronic"]),
        ("Hip-Hop/Rap", ["hip hop rap"]),
        ("R&B/Soul", ["r and b", "soul"]),
        ("Drum & Bass", ["drum and bass"]),
        ("Rock & Pop", ["rock", "pop"]),
        ("Singer/Songwriter", ["singer songwriter"]),
        ("(17)", ["rock"]),
        ("(17)Rock", ["rock"]),
        ("13", ["pop"]),
        ("Pop, pop,POP", ["pop"]),
        ("", []),
        (None, []),
    ],
)
def test_genre_tags_are_split_and_cleaned(tag, names) -> None:
    assert split_genres(tag) == names


@pytest.mark.parametrize(
    ("genre", "family"),
    [
        ("Hip-Hop", ["hiphop"]),
        ("hip hop", ["hiphop"]),
        ("HipHop", ["hiphop"]),
        ("lo-fi", ["chill"]),
        ("LoFi", ["chill"]),
        ("EDM", ["dance"]),
        ("Swedish Death Metal", ["metal"]),
        ("folk metal", ["metal", "acoustic"]),
        ("Post-Rock", ["cinematic"]),
        ("Other", []),
        ("Unknown", []),
        ("Music", []),
    ],
)
def test_spelling_variations_reach_the_same_family(genre, family) -> None:
    assert family_of(genre) == family


def test_genre_names_are_shown_the_way_people_write_them() -> None:
    assert read_genres("hip-hop; r&b; edm; lo-fi").names == (
        "Hip-Hop",
        "R&B",
        "EDM",
        "Lo-Fi",
    )
    assert display_name("drum and bass") == "Drum & Bass"


def test_the_first_genre_counts_most_and_weights_add_up() -> None:
    reading = read_genres("Rock; Electronic")
    weights = dict(reading.families)

    assert weights["rock"] > weights["dance"]
    assert sum(weights.values()) == pytest.approx(1.0)
    assert not read_genres("Other; Unknown").known


# ------------------------------------------------------------ single genres


@pytest.mark.parametrize(
    ("genre", "style"),
    [
        ("Rock", "strong"),
        ("Heavy Metal", "strong"),
        ("House", "groove"),
        ("Hip-Hop", "groove"),
        ("Pop", "studio"),
        ("Folk", "smooth"),
        ("Country", "smooth"),
        ("Classical", "gentle"),
        ("Jazz", "gentle"),
        ("Ambient", "sky"),
        ("Soundtrack", "spacious"),
        ("Podcast", "voice"),
        ("Reggae", "groove"),
    ],
)
def test_a_known_genre_gets_the_style_built_for_it(genre, style) -> None:
    found = recommend(SongFacts(genre=genre))

    assert found.primary.style == style
    assert found.confidence in ("high", "medium")
    assert found.safe_to_accept
    assert found.basis == f"Genre tag: {read_genres(genre).names[0]}"


def test_every_suggested_style_really_exists() -> None:
    for row in AFFINITY.values():
        assert set(row) <= set(PRESETS)
    for bonus, _why in PAIRS.values():
        assert set(bonus) <= set(PRESETS)
    assert set(GUIDES) == set(PRESETS)


# ------------------------------------------------------------ several genres


def test_rock_and_electronic_meet_on_big_movement() -> None:
    found = recommend(SongFacts(genre="Rock; Electronic"))

    assert found.primary.style == "strong"
    assert "electronic drops" in found.primary.reason
    assert found.genres == ("Rock", "Electronic")


def test_lo_fi_hip_hop_is_chill_not_club() -> None:
    # Hip-hop alone would be Groove; with lo-fi the relationship wins
    assert recommend(SongFacts(genre="Hip-Hop")).primary.style == "groove"
    found = recommend(SongFacts(genre="Lo-Fi; Hip-Hop"))

    assert found.primary.style == "smooth"
    assert "laid-back" in found.primary.reason
    assert "groove" in [alt.style for alt in found.alternatives]


@pytest.mark.parametrize(
    ("genre", "style"),
    [
        ("Pop; Rock", "studio"),
        ("Dance; Pop", "groove"),
        ("Soundtrack; Classical", "spacious"),
        ("Jazz; Hip-Hop", "smooth"),
        ("Folk; Electronic", "smooth"),
    ],
)
def test_genre_pairs_follow_their_musical_relationship(genre, style) -> None:
    assert recommend(SongFacts(genre=genre)).primary.style == style


def test_the_order_of_genres_matters_but_never_randomly() -> None:
    first = recommend(SongFacts(genre="Metal; Classical"))
    again = recommend(SongFacts(genre="Metal; Classical"))

    assert first == again
    assert first.primary.style == "strong"


# ------------------------------------------------------------ little known


@pytest.mark.parametrize("genre", [None, "", "Other", "Unknown; Misc", "(12)"])
def test_no_or_too_broad_genre_gives_the_safe_balanced_style(genre) -> None:
    found = recommend(SongFacts(genre=genre))

    assert found.primary.style == "studio"
    assert found.confidence == "low"
    assert found.safe_to_accept
    assert "unsure" in found.primary.reason


def test_the_title_and_the_recording_help_when_there_is_no_genre() -> None:
    podcast = recommend(SongFacts(title="Episode 12 - Interview", duration=3000))
    ringtone = recommend(SongFacts(title="Ringtone", duration=25))
    memo = recommend(SongFacts(channels=1, sample_rate=16000, duration=200))

    assert podcast.primary.style == "voice"
    assert "name and recording suggest talking" in podcast.basis
    assert ringtone.primary.style == "whirlwind"
    assert memo.primary.style == "voice"


def test_a_described_mood_stands_in_for_a_missing_genre() -> None:
    for mood, (words, _family) in MOODS.items():
        found = recommend(SongFacts(mood=mood))
        assert found.confidence != "low", mood
        assert words.lower() in found.basis
    assert recommend(SongFacts(mood="talk")).primary.style == "voice"
    assert recommend(SongFacts(mood="loud")).primary.style == "strong"


# ------------------------------------------------------------ the answer


def test_alternatives_never_repeat_the_same_sound() -> None:
    for genre in ("Pop", "Rock", "Jazz", None):
        found = recommend(SongFacts(genre=genre))
        shown = [found.primary, *found.alternatives]
        for index, one in enumerate(shown):
            for other in shown[index + 1 :]:
                assert not same_sound(
                    PRESETS[one.style].config, PRESETS[other.style].config
                )
        assert len(found.alternatives) <= 2


def test_reasons_are_plain_words_without_numbers_or_settings() -> None:
    for genre in ("Rock", "Lo-Fi; Hip-Hop", "Podcast", None):
        found = recommend(SongFacts(genre=genre))
        for suggestion in (found.primary, *found.alternatives):
            # '3D' and '8D' are the product's own words, not settings
            words = re.sub(r"[38]D\b", "", suggestion.reason)
            assert not re.search(r"\d|LUFS|kbps|intensity|ambience", words)


def test_your_own_style_takes_part_through_the_style_it_sounds_like() -> None:
    calm = Preset(
        "Night Drive",
        "calm songs for late nights",
        replace(PRESETS["smooth"].config, intensity=0.72),
        custom=True,
    )
    styles = {**PRESETS, "Night Drive": calm}
    found = recommend(SongFacts(genre="Folk"), styles)

    assert closest_built_in(calm.config) == "smooth"
    assert found.primary.style == "smooth"
    assert "Night Drive" in [alt.style for alt in found.alternatives]
    own = next(a for a in found.alternatives if a.style == "Night Drive")
    assert own.reason.startswith("Your own style, moving much like Smooth")
    assert guide_for(calm).best_for.startswith("Moves most like Smooth")


# ------------------------------------------------------------ a whole list


def test_one_default_for_a_list_that_mostly_agrees() -> None:
    songs = [recommend(SongFacts(genre="House")) for _ in range(8)]
    songs += [recommend(SongFacts(genre="Folk")) for _ in range(2)]
    batch = batch_suggestion(songs)

    assert batch.style == "groove"
    assert batch.reason == "The best match for 8 of 10 songs."
    assert not batch.varied


def test_a_varied_list_keeps_the_balanced_default() -> None:
    genres = ["House", "Folk", "Jazz", "Rock", "Ambient", "Podcast", "Soundtrack"]
    batch = batch_suggestion([recommend(SongFacts(genre=g)) for g in genres])

    assert batch.style == "studio"
    assert batch.varied
    assert "varied" in batch.reason


def test_a_list_with_no_genres_says_so() -> None:
    batch = batch_suggestion([recommend(SongFacts()) for _ in range(3)])

    assert batch.style == "studio"
    assert batch.known == 0
    assert "No genre information" in batch.reason
    assert batch_suggestion([]).total == 0
