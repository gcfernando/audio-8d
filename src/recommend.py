# Developed by ::> Gehan Fernando
"""Suggests a style for each song from what the file itself says about it.

The suggestion is built from plain data, not a chain of if-statements:

* AFFINITY says how well each built-in style suits each kind of music. The
  numbers follow what the styles really do: Groove follows the beat, Strong
  moves the most, Smooth is slow and dry, Sky and Spacious add room, Voice
  keeps speech in front of you (see core/style_guide.py).
* A song tagged with several genres gets a weighted blend of their rows, so
  'Rock; Electronic' lands on the style both kinds of music share.
* PAIRS adds the musical relationship between two genres on top, for mixes
  whose sum says less than the whole ('lo-fi' + 'hip-hop' is chill, not club).
* Titles, album names, the length and the recording itself help a little
  when there is no genre tag, and a described mood ("calm", "talking") can
  stand in for a missing tag.

Your own styles take part too: each one scores like the built-in style it
moves most like, a little lower, so it shows up as an alternative. The result
is deterministic (same input, same answer) and knows nothing about widgets.
"""

import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .core.genres import family_label, read_genres
from .core.presets import PRESETS, RECOMMENDED_PRESET, Preset
from .core.style_guide import GUIDES, closest_built_in, same_sound, sound_distance
from .core.types import AudioStreamInfo

# How well each style suits each kind of music (1.0 = made for it)
AFFINITY: dict[str, dict[str, float]] = {
    "dance": {"groove": 1.0, "strong": 0.75, "studio": 0.5, "classic": 0.45},
    "hiphop": {"groove": 1.0, "studio": 0.6, "strong": 0.5, "smooth": 0.35},
    "rnb": {"groove": 0.85, "studio": 0.8, "smooth": 0.6},
    "pop": {"studio": 1.0, "groove": 0.8, "classic": 0.6, "strong": 0.45},
    "rock": {"strong": 1.0, "studio": 0.7, "classic": 0.6},
    "metal": {"strong": 1.0, "classic": 0.55, "studio": 0.5},
    "acoustic": {"smooth": 1.0, "gentle": 0.8, "studio": 0.55},
    "chill": {"smooth": 1.0, "sky": 0.75, "spacious": 0.55},
    "ambient": {"sky": 1.0, "spacious": 0.9, "smooth": 0.6},
    "cinematic": {"spacious": 1.0, "sky": 0.7, "gentle": 0.55},
    "classical": {"gentle": 1.0, "spacious": 0.8, "smooth": 0.6},
    "jazz": {"gentle": 1.0, "smooth": 0.85, "studio": 0.5},
    "latin": {"groove": 1.0, "studio": 0.65, "smooth": 0.45},
    "vocal": {"gentle": 0.9, "smooth": 0.85, "studio": 0.6},
    "speech": {"voice": 1.0, "smooth": 0.35},
    # Not genres: a very short clip, and music played on speakers
    "short": {"whirlwind": 1.0, "strong": 0.5},
    "speakers": {"speakers": 1.0},
    # Nothing is known: the balanced, safe choices
    "unknown": {"studio": 1.0, "classic": 0.6, "smooth": 0.5},
}

# Two kinds of music together can suit a style more than either does alone
PAIRS: dict[frozenset[str], tuple[dict[str, float], str]] = {
    frozenset({"rock", "dance"}): (
        {"strong": 0.3},
        "guitars and electronic drops both suit big, obvious movement",
    ),
    frozenset({"metal", "dance"}): (
        {"strong": 0.3},
        "heavy guitars and electronic drops both suit big movement",
    ),
    frozenset({"pop", "dance"}): (
        {"groove": 0.25},
        "dance-pop is built on the beat, so movement that follows it fits best",
    ),
    frozenset({"pop", "rock"}): (
        {"studio": 0.25},
        "pop-rock sits between the two, so the balanced style fits best",
    ),
    frozenset({"hiphop", "rnb"}): (
        {"groove": 0.2},
        "both are driven by the groove of the beat",
    ),
    frozenset({"chill", "hiphop"}): (
        {"smooth": 0.35},
        "lo-fi hip-hop is laid-back, so slow movement suits it better than club styles",
    ),
    frozenset({"jazz", "hiphop"}): (
        {"smooth": 0.25},
        "jazzy hip-hop is relaxed, so slow movement suits it",
    ),
    frozenset({"jazz", "rnb"}): (
        {"smooth": 0.2, "gentle": 0.1},
        "soulful jazz needs gentle movement that keeps the details",
    ),
    frozenset({"acoustic", "pop"}): (
        {"studio": 0.15, "smooth": 0.1},
        "acoustic pop suits calm, balanced movement",
    ),
    frozenset({"acoustic", "dance"}): (
        {"smooth": 0.2, "sky": 0.15},
        "folk with electronics works best with gentle, floating movement",
    ),
    frozenset({"acoustic", "rock"}): (
        {"studio": 0.2, "smooth": 0.1},
        "folk-rock suits balanced movement that keeps the guitars clear",
    ),
    frozenset({"ambient", "dance"}): (
        {"sky": 0.2, "spacious": 0.2},
        "ambient electronic music is about space, not the beat",
    ),
    frozenset({"chill", "dance"}): (
        {"smooth": 0.15, "sky": 0.15},
        "chilled electronic music suits slow, airy movement",
    ),
    frozenset({"classical", "cinematic"}): (
        {"spacious": 0.25},
        "orchestral film music suits a wide, roomy sound",
    ),
    frozenset({"rock", "cinematic"}): (
        {"spacious": 0.3},
        "post-rock builds slowly and suits a wide, roomy sound",
    ),
    frozenset({"metal", "classical"}): (
        {"spacious": 0.2, "strong": 0.1},
        "symphonic metal needs both power and space",
    ),
    frozenset({"latin", "pop"}): (
        {"groove": 0.2},
        "Latin pop is danceable, so movement that follows the beat fits",
    ),
}

# Words in a title or album name that hint at the kind of recording
_KEYWORDS = (
    (r"\b(podcast|episode|ep\.? ?\d+|chapter|audiobook|interview|lecture|sermon)\b",
     "speech"),
    (r"\b(remix|club mix|extended mix|radio edit|dub mix|vip mix)\b", "dance"),
    (r"\b(acoustic|unplugged)\b", "acoustic"),
    (r"\b(lo-?fi|chillhop|study beats)\b", "chill"),
    (r"\b(ambient|sleep|meditation|rain sounds|white noise)\b", "ambient"),
    (r"\b(soundtrack|ost|original score|main theme)\b", "cinematic"),
    (r"\b(symphony|concerto|sonata|nocturne|op\. ?\d+|bwv ?\d+)\b", "classical"),
    (r"\bringtone\b", "short"),
)  # fmt: skip

# Answers to "What does it sound like?": (the words on the button, kind of music)
MOODS: dict[str, tuple[str, str]] = {
    "beat": ("Strong beat", "dance"),
    "loud": ("Loud & powerful", "rock"),
    "calm": ("Calm / acoustic", "acoustic"),
    "space": ("Dreamy / spacious", "ambient"),
    "talk": ("Talking", "speech"),
}

# Below this many seconds a file is a clip or a ringtone, not a song
SHORT_CLIP = 60.0
# A mono recording this thin is almost always a voice memo or a phone call
_THIN_RATE = 32_000
# The first, strongest source of information counts most
_GENRE_SHARE = 1.0
_HINT_SHARE = 0.45
_MOOD_SHARE = 1.0
# The winner is clear when it scores this many times the runner-up
_CLEAR_LEAD = 1.25
# How far below its built-in twin one of your own styles scores
_OWN_STYLE_FACTOR = 0.92
# Your style must move roughly like its twin to share its scores at all
_OWN_STYLE_REACH = 0.6


@dataclass(frozen=True, slots=True)
class SongFacts:
    """Everything a suggestion may use about one song (all of it optional)."""

    genre: str | None = None
    title: str | None = None
    album: str | None = None
    duration: float | None = None
    channels: int | None = None
    sample_rate: int | None = None
    # A kind of music chosen by the user ("calm", "talk"…), see MOODS
    mood: str | None = None

    @classmethod
    def from_info(
        cls, info: AudioStreamInfo | None, name: str = "", mood: str | None = None
    ) -> "SongFacts":
        """The facts a probe found (or just the file name when it hasn't run)."""
        if info is None:
            return cls(title=name or None, mood=mood)
        return cls(
            genre=info.genre,
            title=info.title or name or None,
            album=info.album,
            duration=info.duration_seconds,
            channels=info.channels,
            sample_rate=info.sample_rate,
            mood=mood,
        )


@dataclass(frozen=True, slots=True)
class Suggestion:
    """One suggested style and why it fits."""

    style: str
    score: float
    reason: str


@dataclass(frozen=True, slots=True)
class Recommendation:
    """The suggested style for a song, some alternatives, and how sure we are."""

    primary: Suggestion
    alternatives: tuple[Suggestion, ...]
    # "high" (clear winner), "medium" (close alternatives) or "low" (little known)
    confidence: str
    # What the suggestion is based on, e.g. "Genre tags: Rock, Electronic"
    basis: str
    # The genres read from the tag, as people write them
    genres: tuple[str, ...] = ()
    # (kind of music, share) behind the scores, for the advanced details
    families: tuple[tuple[str, float], ...] = ()
    scores: tuple[tuple[str, float], ...] = field(default=())

    @property
    def safe_to_accept(self) -> bool:
        """True when the suggestion can be used as it is, with nothing else to set."""
        return self.confidence in ("high", "medium") or (
            self.primary.style == RECOMMENDED_PRESET
        )

    @property
    def headline(self) -> str:
        """A short verdict for the interface."""
        return {
            "high": "Good match: safe to use as it is.",
            "medium": "Good match. The alternatives are close; preview to compare.",
            "low": "Not much is known about this music, so a balanced, safe style "
            "is suggested.",
        }[self.confidence]


def _hint_families(facts: SongFacts) -> list[str]:
    """Kinds of music that the title, album name or recording hint at."""
    words = " ".join(filter(None, (facts.title, facts.album))).lower()
    found = [
        family for pattern, family in _KEYWORDS if re.search(pattern, words) and family
    ]
    if facts.duration is not None and 0 < facts.duration < SHORT_CLIP:
        found.append("short")
    if (
        facts.channels == 1
        and facts.sample_rate is not None
        and facts.sample_rate < _THIN_RATE
    ):
        found.append("speech")
    return list(dict.fromkeys(found))


# Each source of information (tag, mood, name, recording) adds its own share
def _weights(  # pylint: disable=too-many-locals
    facts: SongFacts,
) -> tuple[dict[str, float], str, tuple[str, ...]]:
    """(kind of music -> share, what it is based on, genre names) for one song."""
    reading = read_genres(facts.genre)
    weights: dict[str, float] = {}
    basis: list[str] = []

    def add(family: str, share: float) -> None:
        weights[family] = weights.get(family, 0.0) + share

    if facts.mood in MOODS:
        add(MOODS[facts.mood][1], _MOOD_SHARE)
        basis.append(f"you described it as '{MOODS[facts.mood][0].lower()}'")
    genre_share = _GENRE_SHARE * (0.5 if facts.mood in MOODS else 1.0)
    for family, share in reading.families:
        add(family, share * genre_share)
    if reading.known:
        label = "Genre tag" if len(reading.names) == 1 else "Genre tags"
        basis.insert(0, f"{label}: {', '.join(reading.names)}")
    elif reading.names:
        basis.insert(0, f"Genre tag '{', '.join(reading.names)}' is too general")
    hints = _hint_families(facts)
    # Hints only lead when nothing better is known; otherwise they nudge
    hint_share = _HINT_SHARE if weights else 1.0 / max(1, len(hints))
    for family in hints:
        add(family, hint_share)
    if hints:
        basis.append(
            "the name and recording suggest "
            + ", ".join(family_label(family) for family in hints)
        )
    if not weights:
        weights["unknown"] = 1.0
        if not reading.names:
            basis.insert(0, "No genre tag in the file")
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()}, "; ".join(basis), reading.names


def _built_in_scores(  # pylint: disable=too-many-locals
    weights: Mapping[str, float],
) -> tuple[dict[str, float], str, frozenset[str]]:
    """Every built-in style's score, the relationship that shaped it, and its styles.

    The relationship is the strongest pair of kinds of music found (if any); its
    styles are the ones that pair favours.
    """
    scores: dict[str, float] = {}
    for family, share in weights.items():
        for style, fit in AFFINITY.get(family, {}).items():
            scores[style] = scores.get(style, 0.0) + share * fit
    note, favoured = "", frozenset[str]()
    present = sorted(weights, key=lambda f: -weights[f])
    best_bonus = 0.0
    for index, first in enumerate(present):
        for second in present[index + 1 :]:
            pair = PAIRS.get(frozenset({first, second}))
            if pair is None:
                continue
            bonus, why = pair
            # A pair counts as much as its weaker half is present
            strength = 2 * min(weights[first], weights[second])
            for style, extra in bonus.items():
                scores[style] = scores.get(style, 0.0) + extra * strength
            if strength > best_bonus:
                best_bonus, note, favoured = strength, why, frozenset(bonus)
    return scores, note, favoured


def _lower_first(text: str) -> str:
    """'Slow, relaxed…' -> 'slow, relaxed…', to follow a colon."""
    return text[:1].lower() + text[1:]


def _reason(
    style: Preset, weights: Mapping[str, float], pair_note: str, primary: bool
) -> str:
    """Why a style fits, in one plain sentence."""
    guide = GUIDES.get(style.name) if not style.custom else None
    purpose = guide.purpose if guide else (style.summary.strip() or "your own style")
    purpose = _lower_first(purpose.rstrip(".")) + "."
    if style.custom:
        twin = PRESETS[closest_built_in(style.config)].label
        return f"Your own style, moving much like {twin}: {purpose}"
    families = [
        family
        for family in sorted(weights, key=lambda f: -weights[f])
        if family != "unknown"
    ]
    if primary and pair_note:
        return f"{pair_note[:1].upper()}{pair_note[1:]}."
    if not families:
        return f"A balanced choice when you are unsure: {purpose}"
    if families[0] == "short":
        return "Short clips suit a fast, playful spin."
    kinds = " and ".join(family_label(family) for family in families[:2])
    return f"{'Suits' if primary else 'Also suits'} {kinds}: {purpose}"


def recommend(  # pylint: disable=too-many-locals
    facts: SongFacts,
    styles: Mapping[str, Preset] | None = None,
    *,
    alternatives: int = 2,
) -> Recommendation:
    """The best style for one song, up to `alternatives` others, and why."""
    known = dict(styles or PRESETS)
    weights, basis, genres = _weights(facts)
    built_in, pair_note, favoured = _built_in_scores(weights)
    scores: dict[str, float] = {
        name: built_in.get(name, 0.0) for name in known if not known[name].custom
    }
    # Your styles score like the built-in style they move most like, a bit lower
    for name, preset in known.items():
        if not preset.custom:
            continue
        twin = closest_built_in(preset.config)
        distance = sound_distance(preset.config, PRESETS[twin].config)
        if distance <= _OWN_STYLE_REACH:
            closeness = 1.0 - distance / (2 * _OWN_STYLE_REACH)
            scores[name] = built_in.get(twin, 0.0) * _OWN_STYLE_FACTOR * closeness
    order = list(known)
    ranked = sorted(
        (name for name in scores if scores[name] > 0),
        key=lambda name: (-round(scores[name], 6), order.index(name)),
    )
    if not ranked:
        ranked = [RECOMMENDED_PRESET]
        scores[RECOMMENDED_PRESET] = 1.0
    # Styles that move identically (Studio, Streaming, Lossless) count once
    picked: list[str] = []
    for name in ranked:
        if not any(same_sound(known[name].config, known[p].config) for p in picked):
            picked.append(name)
    top = picked[0]
    first = scores[top]
    second = scores[picked[1]] if len(picked) > 1 else 0.0
    if set(weights) == {"unknown"}:
        confidence = "low"
    elif first >= _CLEAR_LEAD * second:
        confidence = "high"
    else:
        confidence = "medium"
    suggestions = [
        Suggestion(
            name,
            round(scores[name], 3),
            _reason(
                known[name],
                weights,
                pair_note if name in favoured else "",
                primary=index == 0,
            ),
        )
        for index, name in enumerate(picked[: 1 + alternatives])
    ]
    return Recommendation(
        primary=suggestions[0],
        alternatives=tuple(suggestions[1:]),
        confidence=confidence,
        basis=basis[:1].upper() + basis[1:],
        genres=genres,
        families=tuple(
            (family_label(family), round(share, 3))
            for family, share in sorted(weights.items(), key=lambda kv: -kv[1])
        ),
        scores=tuple((name, round(scores[name], 3)) for name in picked),
    )


# A default must suit at least this share of the (weighted) songs
_MAJORITY = 0.4
# How much a song's suggestion counts when choosing one style for a whole list
_CONFIDENCE_VOTE = {"high": 1.0, "medium": 0.7, "low": 0.25}


@dataclass(frozen=True, slots=True)
class BatchSuggestion:
    """The best single style for a whole list, and how many songs it suits."""

    style: str
    fits: int
    total: int
    known: int
    # True when the songs are too varied for one style to suit most of them
    varied: bool = False

    @property
    def reason(self) -> str:
        """'The best match for 180 of 300 songs', in plain words."""
        if not self.known:
            return (
                "No genre information was found, so the balanced default is suggested."
            )
        if self.varied:
            return (
                "Your songs are varied, so a balanced default fits best. Press "
                "'Use suggested styles' below to give each song its own match."
            )
        return (
            f"The best match for {self.fits} of {self.total} "
            f"song{'s' if self.total != 1 else ''}."
        )


def batch_suggestion(recommendations: Sequence[Recommendation]) -> BatchSuggestion:
    """The one style that suits most of the songs (ties go to Studio, then order)."""
    votes: defaultdict[str, float] = defaultdict(float)
    fits: Counter[str] = Counter()
    known = 0
    for rec in recommendations:
        votes[rec.primary.style] += _CONFIDENCE_VOTE[rec.confidence]
        fits[rec.primary.style] += 1
        if rec.confidence != "low":
            known += 1
    if not votes:
        return BatchSuggestion(RECOMMENDED_PRESET, 0, 0, 0)
    best = max(
        votes,
        key=lambda name: (round(votes[name], 6), name == RECOMMENDED_PRESET),
    )
    # One style only makes a good default when it suits a good share of the list
    if votes[best] < _MAJORITY * sum(votes.values()):
        return BatchSuggestion(
            RECOMMENDED_PRESET,
            fits[RECOMMENDED_PRESET],
            len(recommendations),
            known,
            varied=True,
        )
    return BatchSuggestion(best, fits[best], len(recommendations), known)
