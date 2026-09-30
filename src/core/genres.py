# Developed by ::> Gehan Fernando
"""Turns the genre tags songs really carry into a few well-known kinds of music.

Genre tags are messy: 'Hip-Hop', 'hip hop' and 'HipHop' mean the same thing,
old MP3s store numbers like '(17)', and one tag often holds several genres
('Rock; Electronic', 'Pop/Funk', 'folk metal'). Everything here is plain data
plus small, deterministic functions, so the style suggestions built on it can
be tested and extended without touching any window code.
"""

import re
from dataclasses import dataclass

# ------------------------------------------------------------------ families


@dataclass(frozen=True, slots=True)
class Family:
    """A kind of music people recognise, with the tag spellings that mean it."""

    key: str
    label: str
    aliases: tuple[str, ...]


# Aliases are written already normalised: lower case, '&' as 'and', no hyphens
FAMILIES: tuple[Family, ...] = (
    Family(
        "dance",
        "dance and electronic",
        (
            "electronic", "electronica", "edm", "dance", "house", "deep house",
            "tech house", "progressive house", "techno", "trance", "psytrance",
            "dubstep", "drum and bass", "dnb", "d and b", "jungle", "breakbeat",
            "electro", "disco", "nu disco", "club", "garage", "uk garage",
            "hardstyle", "big room", "future bass", "eurodance", "euro techno",
            "synthwave", "retrowave", "idm", "rave", "acid", "bass", "dance music",
            "electronic dance music", "techno industrial",
        ),
    ),
    Family(
        "hiphop",
        "hip-hop and rap",
        (
            "hip hop", "hiphop", "rap", "trap", "drill", "grime", "boom bap",
            "gangsta", "gangsta rap", "christian rap", "hip hop rap", "rap hip hop",
        ),
    ),
    Family(
        "rnb",
        "R&B, soul and funk",
        (
            "r and b", "rnb", "rhythm and blues", "soul", "neo soul", "funk",
            "motown", "contemporary r and b", "new jack swing",
        ),
    ),
    Family(
        "pop",
        "pop",
        (
            "pop", "dance pop", "electropop", "synthpop", "synth pop", "k pop",
            "kpop", "j pop", "jpop", "c pop", "teen pop", "indie pop", "top 40",
            "new wave", "pop folk", "instrumental pop", "oldies", "retro",
            "schlager", "musical", "showtunes", "cabaret", "children's",
            "childrens", "kids", "latin pop",
        ),
    ),
    Family(
        "rock",
        "rock",
        (
            "rock", "hard rock", "alternative", "alternative rock", "alt rock",
            "alternrock", "indie", "indie rock", "punk", "pop punk", "punk rock",
            "grunge", "garage rock", "classic rock", "psychedelic",
            "psychedelic rock", "psychadelic", "prog rock", "progressive rock",
            "emo", "britpop", "rock and roll", "rockabilly", "southern rock",
            "instrumental rock", "acid punk", "surf rock", "gothic", "darkwave",
        ),
    ),
    Family(
        "metal",
        "metal",
        (
            "metal", "heavy metal", "death metal", "black metal", "thrash metal",
            "metalcore", "nu metal", "doom metal", "power metal", "hardcore",
            "industrial", "deathcore", "djent", "noise",
        ),
    ),
    Family(
        "acoustic",
        "acoustic, folk and country",
        (
            "acoustic", "folk", "singer songwriter", "country", "bluegrass",
            "americana", "blues", "indie folk", "unplugged", "folk rock",
            "celtic", "native american", "ethnic", "tribal", "polka",
        ),
    ),
    Family(
        "chill",
        "lo-fi and chill",
        (
            "lo fi", "lofi", "chill", "chillout", "chill out", "chillhop",
            "downtempo", "trip hop", "lounge", "easy listening", "bossa nova",
            "chillwave", "lo fi hip hop",
        ),
    ),
    Family(
        "ambient",
        "ambient and relaxing",
        (
            "ambient", "new age", "drone", "meditation", "meditative",
            "relaxation", "relaxing", "sleep", "nature", "nature sounds",
            "healing", "spa", "dark ambient", "space", "dream", "lullaby",
            "study",
        ),
    ),
    Family(
        "cinematic",
        "film and atmospheric",
        (
            "soundtrack", "score", "film score", "cinematic", "orchestral",
            "epic", "trailer", "game", "video game", "video game music", "vgm",
            "post rock", "shoegaze", "dream pop", "anime", "film",
        ),
    ),
    Family(
        "classical",
        "classical",
        (
            "classical", "baroque", "romantic", "opera", "choral", "chamber",
            "chamber music", "symphony", "symphonic", "piano", "contemporary classical",
            "early music", "minimalism",
        ),
    ),
    Family(
        "jazz",
        "jazz",
        (
            "jazz", "smooth jazz", "bebop", "swing", "big band", "fusion",
            "jazz fusion", "vocal jazz", "acid jazz", "jazz and funk", "jazz funk",
            "latin jazz",
        ),
    ),
    Family(
        "latin",
        "reggae, Latin and Afro",
        (
            "reggae", "dub", "ska", "dancehall", "reggaeton", "afrobeat",
            "afrobeats", "latin", "salsa", "bachata", "cumbia", "samba", "dembow",
            "amapiano", "kizomba", "merengue", "tropical",
        ),
    ),
    Family(
        "vocal",
        "vocal and gospel",
        (
            "vocal", "a cappella", "acappella", "choir", "gospel", "worship",
            "christian", "ballad", "ballads",
        ),
    ),
    Family(
        "speech",
        "talking",
        (
            "podcast", "audiobook", "audio book", "spoken word", "spoken", "speech",
            "talk", "comedy", "stand up", "news", "lecture", "poetry", "sermon",
            "interview", "educational", "language", "radio drama", "audio drama",
            "books and spoken", "pranks",
        ),
    ),
)  # fmt: skip

FAMILY_BY_KEY = {family.key: family for family in FAMILIES}
_ALIASES = {alias: family.key for family in FAMILIES for alias in family.aliases}

# Tags that say nothing about how the music sounds
BROAD = frozenset(
    {
        "other", "unknown", "misc", "miscellaneous", "various", "general",
        "music", "none", "genre", "default", "n a", "na", "world", "instrumental",
        "sound clip", "cult", "unclassifiable", "mixed", "all", "songs",
    }
)  # fmt: skip

# A word inside an unknown tag that still tells the family ('swedish death metal')
_WORD_FAMILIES = (
    ("metal", "metal"),
    ("core", "metal"),
    ("punk", "rock"),
    ("rock", "rock"),
    ("house", "dance"),
    ("techno", "dance"),
    ("trance", "dance"),
    ("step", "dance"),
    ("edm", "dance"),
    ("electro", "dance"),
    ("disco", "dance"),
    ("hop", "hiphop"),
    ("rap", "hiphop"),
    ("jazz", "jazz"),
    ("folk", "acoustic"),
    ("country", "acoustic"),
    ("acoustic", "acoustic"),
    ("blues", "acoustic"),
    ("soul", "rnb"),
    ("funk", "rnb"),
    ("pop", "pop"),
    ("ambient", "ambient"),
    ("chill", "chill"),
    ("classical", "classical"),
    ("orchestra", "cinematic"),
    ("soundtrack", "cinematic"),
    ("reggae", "latin"),
    ("latin", "latin"),
    ("gospel", "vocal"),
    ("podcast", "speech"),
)

# ID3v1's numbered genres, still found in old MP3s as '(17)' or '17'
ID3V1_GENRES = (
    "Blues", "Classic Rock", "Country", "Dance", "Disco", "Funk", "Grunge",
    "Hip-Hop", "Jazz", "Metal", "New Age", "Oldies", "Other", "Pop", "R&B", "Rap",
    "Reggae", "Rock", "Techno", "Industrial", "Alternative", "Ska", "Death Metal",
    "Pranks", "Soundtrack", "Euro-Techno", "Ambient", "Trip-Hop", "Vocal",
    "Jazz+Funk", "Fusion", "Trance", "Classical", "Instrumental", "Acid", "House",
    "Game", "Sound Clip", "Gospel", "Noise", "AlternRock", "Bass", "Soul", "Punk",
    "Space", "Meditative", "Instrumental Pop", "Instrumental Rock", "Ethnic",
    "Gothic", "Darkwave", "Techno-Industrial", "Electronic", "Pop-Folk",
    "Eurodance", "Dream", "Southern Rock", "Comedy", "Cult", "Gangsta", "Top 40",
    "Christian Rap", "Pop/Funk", "Jungle", "Native American", "Cabaret",
    "New Wave", "Psychadelic", "Rave", "Showtunes", "Trailer", "Lo-Fi", "Tribal",
    "Acid Punk", "Acid Jazz", "Polka", "Retro", "Musical", "Rock & Roll",
    "Hard Rock",
)  # fmt: skip

# Genres whose own name holds a separator, kept whole before splitting
_JOINED = (
    ("singer/songwriter", "singer songwriter"),
    ("singer-songwriter", "singer songwriter"),
    ("hip-hop/rap", "hip hop rap"),
    ("rap/hip-hop", "rap hip hop"),
    ("rhythm & blues", "rhythm and blues"),
    ("r&b", "r and b"),
    ("d&b", "d and b"),
    ("drum & bass", "drum and bass"),
    ("drum'n'bass", "drum and bass"),
    ("drum n bass", "drum and bass"),
    ("rock & roll", "rock and roll"),
    ("rock 'n' roll", "rock and roll"),
    ("rock n roll", "rock and roll"),
    ("jazz+funk", "jazz and funk"),
    ("books & spoken", "books and spoken"),
)
_SPLIT = re.compile(r"[;/,|\\\x00]+|\s+&\s+|\s+\+\s+")
_ID3_NUMBER = re.compile(r"\((\d{1,3})\)|^(\d{1,3})$")


def _clean(text: str) -> str:
    """'Hip-Hop ' -> 'hip hop': lower case, '&' as 'and', single spaces."""
    text = text.lower().replace("&", " and ").replace("_", " ")
    text = re.sub(r"[-.:!?\"()\[\]{}*]+", " ", text)
    return " ".join(text.split())


def _expand_numbers(text: str) -> str:
    """'(17)' or '17' -> 'Rock'; '(17)Rock' keeps just one Rock."""

    def name(match: re.Match[str]) -> str:
        number = int(match.group(1) or match.group(2))
        return f";{ID3V1_GENRES[number]};" if number < len(ID3V1_GENRES) else ";"

    return _ID3_NUMBER.sub(name, text.strip())


def split_genres(tag: str | None) -> list[str]:
    """Every genre named in a tag, cleaned and in order, without repeats."""
    if not tag:
        return []
    text = _expand_numbers(tag).lower()
    for joined, kept in _JOINED:
        text = text.replace(joined, kept)
    found: list[str] = []
    for part in _SPLIT.split(text):
        cleaned = _clean(part)
        if cleaned and cleaned not in found:
            found.append(cleaned)
    return found


def family_of(genre: str) -> list[str]:
    """The family (or families, for 'folk metal') one cleaned genre belongs to.

    The last word of an unknown compound decides most ('folk metal' is metal
    first, folk second), so the list is ordered from strongest to weakest.
    """
    cleaned = _clean(genre)
    if not cleaned or cleaned in BROAD:
        return []
    key = _ALIASES.get(cleaned) or _ALIASES.get(cleaned.replace(" ", ""))
    if key:
        return [key]
    found: list[tuple[int, str]] = []
    for word, family in _WORD_FAMILIES:
        position = cleaned.rfind(word)
        if position >= 0 and family not in (f for _p, f in found):
            found.append((position, family))
    return [family for _position, family in sorted(found, reverse=True)]


@dataclass(frozen=True, slots=True)
class GenreReading:
    """What a genre tag says: the names it holds and the families they mean."""

    names: tuple[str, ...]
    # (family key, weight) from strongest to weakest; weights add up to 1
    families: tuple[tuple[str, float], ...]

    @property
    def known(self) -> bool:
        """True when at least one genre could be recognised."""
        return bool(self.families)


# The first genre in a tag is usually the main one; later ones count a bit less
_ORDER_WEIGHTS = (1.0, 0.8, 0.65, 0.55, 0.5)
# The second family inside one compound genre ('folk' in 'folk metal')
_COMPOUND_WEIGHT = 0.6


def read_genres(tag: str | None) -> GenreReading:
    """Read a whole genre tag into weighted families (deterministic)."""
    names = split_genres(tag)
    weights: dict[str, float] = {}
    for index, name in enumerate(names):
        base = _ORDER_WEIGHTS[min(index, len(_ORDER_WEIGHTS) - 1)]
        for position, family in enumerate(family_of(name)):
            weight = base * (1.0 if position == 0 else _COMPOUND_WEIGHT)
            weights[family] = max(weights.get(family, 0.0), weight)
    total = sum(weights.values())
    families = tuple(
        (family, weight / total)
        for family, weight in sorted(weights.items(), key=lambda kv: -kv[1])
    )
    return GenreReading(tuple(display_name(name) for name in names), families)


# Names that plain title case would get wrong
_DISPLAY = {
    "r and b": "R&B",
    "d and b": "D&B",
    "drum and bass": "Drum & Bass",
    "rock and roll": "Rock & Roll",
    "rhythm and blues": "Rhythm & Blues",
    "hip hop": "Hip-Hop",
    "hip hop rap": "Hip-Hop/Rap",
    "rap hip hop": "Rap/Hip-Hop",
    "lo fi": "Lo-Fi",
    "lo fi hip hop": "Lo-Fi Hip-Hop",
    "lofi": "Lo-Fi",
    "k pop": "K-Pop",
    "j pop": "J-Pop",
    "c pop": "C-Pop",
    "uk garage": "UK Garage",
    "singer songwriter": "Singer-Songwriter",
    "jazz and funk": "Jazz & Funk",
    "books and spoken": "Books & Spoken",
    "a cappella": "A Cappella",
    "nu metal": "Nu Metal",
}
_UPPER = frozenset({"edm", "idm", "dnb", "vgm", "uk"})


def display_name(genre: str) -> str:
    """A cleaned genre as people write it: 'hip hop' -> 'Hip-Hop', 'edm' -> 'EDM'."""
    if genre in _DISPLAY:
        return _DISPLAY[genre]
    return " ".join(
        word.upper() if word in _UPPER else word[:1].upper() + word[1:]
        for word in genre.split()
    )


def family_label(key: str) -> str:
    """The plain name of a family, e.g. 'rock' or 'dance and electronic'."""
    family = FAMILY_BY_KEY.get(key)
    return family.label if family else key
