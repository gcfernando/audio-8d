# Developed by ::> Gehan Fernando
"""The song list behind the window: search, filter, sort, group and bulk styles.

Everything a big batch needs lives here, apart from the widgets, so 300 songs
cost the same thinking as 10 and every rule can be tested without a screen:

* every song follows the default style unless it has a style of its own
  (an "override"); there is never a third state;
* giving a song the default style simply removes its override;
* style suggestions are worked out once per song (and again only when the
  song's details, its described mood or the list of styles change).
"""

from collections.abc import Callable, Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .core.genres import read_genres
from .core.parsing import format_time
from .core.presets import PRESETS, Preset
from .core.types import AudioStreamInfo
from .recommend import (
    BatchSuggestion,
    Recommendation,
    SongFacts,
    batch_suggestion,
    recommend,
)

# Where a song stands: still being read, ready to convert, or unreadable
READING, READY, UNREADABLE = "reading", "ready", "unreadable"


@dataclass(eq=False)
class Track:
    """One song on the list and what is known about it."""

    song: Path
    # The folder it was added from (None for a single file)
    folder: Path | None = None
    info: AudioStreamInfo | None = None
    state: str = READING
    # Why it can't be used, in plain words (for unreadable songs)
    problem: str = ""
    # What the user said the music sounds like, when the file has no genre
    mood: str | None = None

    @property
    def name(self) -> str:
        """The song's file name without its extension."""
        return self.song.stem

    @property
    def kind(self) -> str:
        """'MP3', 'FLAC'… from the file name."""
        return self.song.suffix.lstrip(".").upper() or "?"

    @property
    def genre(self) -> str:
        """The genres the file names, as people write them ('' when none)."""
        return ", ".join(read_genres(self.info.genre if self.info else None).names)

    @property
    def artist(self) -> str:
        """The artist tag, or ''."""
        return (self.info.artist or "") if self.info else ""

    @property
    def album(self) -> str:
        """The album tag, or ''."""
        return (self.info.album or "") if self.info else ""

    @property
    def seconds(self) -> float | None:
        """Length in seconds, when known."""
        return self.info.duration_seconds if self.info else None

    @property
    def length_text(self) -> str:
        """'3:25', '…' while reading, '!' when unreadable."""
        if self.state == UNREADABLE:
            return "!"
        if self.state == READING:
            return "…"
        return format_time(self.seconds) if self.seconds else "?"

    @property
    def where(self) -> str:
        """The folder shown for it: relative to the folder it came from."""
        if self.folder is not None:
            try:
                return str(self.song.parent.relative_to(self.folder.parent))
            except ValueError:
                pass
        return self.song.parent.name

    @property
    def facts(self) -> SongFacts:
        """What the style suggestion may use."""
        return SongFacts.from_info(self.info, self.name, self.mood)


# ---------------------------------------------------------------- style rules


def style_of(overrides: Mapping[Path, str], default: str, song: Path) -> str:
    """The style a song will be made with: its own, or the default."""
    return overrides.get(song, default)


def follows_default(overrides: Mapping[Path, str], song: Path) -> bool:
    """True when the song simply uses the default style."""
    return song not in overrides


def assign(
    overrides: MutableMapping[Path, str],
    default: str,
    songs: Iterable[Path],
    style: str,
) -> int:
    """Give every song one style; the default style means 'follow the default'.

    Returns how many songs changed.
    """
    changed = 0
    for song in songs:
        before = overrides.get(song)
        if style == default:
            overrides.pop(song, None)
        else:
            overrides[song] = style
        changed += overrides.get(song) != before
    return changed


def reset(overrides: MutableMapping[Path, str], songs: Iterable[Path]) -> int:
    """Songs go back to the default style; returns how many had their own."""
    count = 0
    for song in songs:
        if overrides.pop(song, None) is not None:
            count += 1
    return count


def change_default(overrides: MutableMapping[Path, str], new_default: str) -> int:
    """After the default changes, songs whose own style equals it simply follow it.

    Every other song keeps its own style. Returns how many songs were folded in.
    """
    same = [song for song, style in overrides.items() if style == new_default]
    for song in same:
        del overrides[song]
    return len(same)


def forget_missing_styles(
    overrides: MutableMapping[Path, str], styles: Mapping[str, Preset]
) -> list[Path]:
    """Songs whose own style was deleted go back to the default; returns them."""
    gone = [song for song, style in overrides.items() if style not in styles]
    for song in gone:
        del overrides[song]
    return gone


# ------------------------------------------------------------- the song list

FILTERS = {
    "all": "All songs",
    "own": "Only songs that differ from the default",
    "default": "Only songs that follow the default",
    "suggestion": "Only songs whose suggested style isn't used",
    "no-genre": "Only songs with no genre information",
    "problems": "Only songs that can't be read",
}
SORTS = {
    "list": "List order",
    "name": "Song name",
    "artist": "Artist",
    "album": "Album",
    "genre": "Genre",
    "style": "Style",
    "suggested": "Suggested style",
    "length": "Length",
    "type": "File type",
}
GROUPS = {
    "none": "No grouping",
    "genre": "Genre",
    "suggested": "Suggested style",
    "style": "Style",
    "album": "Album",
    "artist": "Artist",
    "type": "File type",
    "folder": "Folder",
}


@dataclass
class Group:
    """A titled run of songs in the list (one untitled group when not grouping)."""

    title: str
    tracks: list[Track] = field(default_factory=list)


@dataclass
class ViewOptions:
    """How the list is shown: search words, filter, sort order and grouping."""

    query: str = ""
    filter: str = "all"
    sort: str = "list"
    descending: bool = False
    group: str = "none"


class Library:
    """Every song on the list, and the style suggestions worked out for them."""

    def __init__(self) -> None:
        """An empty list."""
        self.tracks: list[Track] = []
        self._by_song: dict[Path, Track] = {}
        # (song, mood, styles version) -> suggestion; kept until something changes
        self._suggestions: dict[tuple, Recommendation] = {}
        self._styles: Mapping[str, Preset] = PRESETS
        self._styles_version = 0

    def __len__(self) -> int:
        """How many songs are on the list."""
        return len(self.tracks)

    def __contains__(self, song: object) -> bool:
        """True when the song is already on the list."""
        return song in self._by_song

    def get(self, song: Path) -> Track | None:
        """The song's track, if it is on the list."""
        return self._by_song.get(song)

    def add(self, song: Path, folder: Path | None = None) -> Track | None:
        """Add a song (None when it is already there)."""
        if song in self._by_song:
            return None
        track = Track(song, folder)
        self.tracks.append(track)
        self._by_song[song] = track
        return track

    def remove(self, songs: Iterable[Path]) -> list[Track]:
        """Take songs off the list; returns the tracks removed."""
        gone = {song for song in songs if song in self._by_song}
        removed = [track for track in self.tracks if track.song in gone]
        self.tracks = [track for track in self.tracks if track.song not in gone]
        for song in gone:
            del self._by_song[song]
        self._suggestions = {
            key: value for key, value in self._suggestions.items() if key[0] not in gone
        }
        return removed

    def clear(self) -> None:
        """Empty the list."""
        self.tracks.clear()
        self._by_song.clear()
        self._suggestions.clear()

    # -------------------------------------------------------- suggestions

    def use_styles(self, styles: Mapping[str, Preset]) -> None:
        """The list of styles changed (saved, renamed or deleted ones)."""
        self._styles = styles
        self._styles_version += 1
        self._suggestions.clear()

    def suggestion(self, track: Track) -> Recommendation:
        """The style suggested for a song, worked out once and then remembered."""
        key = (track.song, track.mood, track.state, self._styles_version)
        found = self._suggestions.get(key)
        if found is None:
            found = recommend(track.facts, self._styles)
            self._suggestions[key] = found
        return found

    def batch_suggestion(
        self, tracks: Sequence[Track] | None = None
    ) -> BatchSuggestion:
        """The one style that suits most of the (given) songs."""
        chosen = self.tracks if tracks is None else tracks
        return batch_suggestion(
            [self.suggestion(track) for track in chosen if track.state != UNREADABLE]
        )

    def apply_suggestions(
        self,
        overrides: MutableMapping[Path, str],
        default: str,
        tracks: Iterable[Track] | None = None,
    ) -> tuple[int, int]:
        """Give songs their suggested style; (changed, left alone as too unsure).

        Songs the suggestion knows little about keep what they have, rather than
        being moved to a guess.
        """
        changed = unsure = 0
        for track in self.tracks if tracks is None else tracks:
            if track.state == UNREADABLE:
                continue
            found = self.suggestion(track)
            if found.confidence == "low":
                unsure += 1
                continue
            changed += assign(overrides, default, [track.song], found.primary.style)
        return changed, unsure

    # -------------------------------------------------------- the view

    def view(
        self,
        options: ViewOptions,
        overrides: Mapping[Path, str],
        default: str,
        label: Callable[[str], str] = str,
    ) -> list[Group]:
        """The songs to show, filtered, sorted and grouped as asked."""
        words = options.query.casefold().split()
        shown = [
            track
            for track in self.tracks
            if self._keeps(track, options.filter, overrides, default)
            and all(word in self._search_text(track) for word in words)
        ]
        if options.sort != "list":
            key = self._sort_key(options.sort, overrides, default, label)
            shown.sort(key=key, reverse=options.descending)
        elif options.descending:
            shown.reverse()
        if options.group == "none":
            return [Group("", shown)]
        groups: dict[str, Group] = {}
        for track in shown:
            title = self._group_title(track, options.group, overrides, default, label)
            groups.setdefault(title, Group(title)).tracks.append(track)
        # Groups in name order, with the 'no information' group last
        return sorted(
            groups.values(), key=lambda g: (g.title.startswith("No "), g.title.lower())
        )

    def _search_text(self, track: Track) -> str:
        """Everything a search can match for one song."""
        return " ".join(
            (track.name, track.artist, track.album, track.genre, track.kind)
        ).casefold()

    def _keeps(
        self, track: Track, which: str, overrides: Mapping[Path, str], default: str
    ) -> bool:
        """True when a song passes the chosen filter."""
        if which == "own":
            return not follows_default(overrides, track.song)
        if which == "default":
            return follows_default(overrides, track.song)
        if which == "suggestion":
            return (
                track.state == READY
                and self.suggestion(track).confidence != "low"
                and self.suggestion(track).primary.style
                != style_of(overrides, default, track.song)
            )
        if which == "no-genre":
            return (
                track.state == READY
                and not read_genres(track.info.genre if track.info else None).known
            )
        if which == "problems":
            return track.state == UNREADABLE
        return True

    def _sort_key(
        self,
        sort: str,
        overrides: Mapping[Path, str],
        default: str,
        label: Callable[[str], str],
    ) -> Callable[[Track], tuple]:
        """How to order songs for one sort choice (empty values go last)."""

        def text(value: str) -> tuple[bool, str]:
            return (not value, value.casefold())

        keys: dict[str, Callable[[Track], tuple]] = {
            "name": lambda t: text(t.name),
            "artist": lambda t: (*text(t.artist), t.name.casefold()),
            "album": lambda t: (*text(t.album), t.name.casefold()),
            "genre": lambda t: (*text(t.genre), t.name.casefold()),
            "style": lambda t: (
                label(style_of(overrides, default, t.song)).casefold(),
                t.name.casefold(),
            ),
            "suggested": lambda t: (
                label(self.suggestion(t).primary.style).casefold(),
                t.name.casefold(),
            ),
            "length": lambda t: (t.seconds is None, t.seconds or 0.0),
            "type": lambda t: (t.kind, t.name.casefold()),
        }
        return keys.get(sort, lambda t: text(t.name))

    # One heading rule per way of grouping
    def _group_title(  # pylint: disable=too-many-return-statements
        self,
        track: Track,
        group: str,
        overrides: Mapping[Path, str],
        default: str,
        label: Callable[[str], str],
    ) -> str:
        """The heading a song is listed under."""
        if group == "genre":
            names = read_genres(track.info.genre if track.info else None).names
            return names[0] if names else "No genre information"
        if group == "suggested":
            return label(self.suggestion(track).primary.style)
        if group == "style":
            own = not follows_default(overrides, track.song)
            name = label(style_of(overrides, default, track.song))
            return name if own else f"{name} (the default)"
        if group == "album":
            return track.album or "No album name"
        if group == "artist":
            return track.artist or "No artist name"
        if group == "type":
            return track.kind
        if group == "folder":
            return track.where or "No folder"
        return ""


def counts(tracks: Sequence[Track], overrides: Mapping[Path, str]) -> dict[str, int]:
    """How many songs there are, follow the default, have their own style, fail."""
    own = sum(1 for track in tracks if track.song in overrides)
    return {
        "total": len(tracks),
        "own": own,
        "default": len(tracks) - own,
        "reading": sum(1 for track in tracks if track.state == READING),
        "unreadable": sum(1 for track in tracks if track.state == UNREADABLE),
    }
