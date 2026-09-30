# Developed by ::> Gehan Fernando
"""The command line's --per-song file: reading lines, matching songs, merging."""

from pathlib import Path

import pytest

from src import InputValidationError
from src.per_song import merged, parse_line, read_rules, rules_for
from src.song_settings import SPEAKERS


def test_a_line_names_a_song_and_its_own_settings() -> None:
    rule = parse_line('"Rain Study.mp3"  --preset smooth --format flac', 3)

    assert rule is not None and rule.line == 3
    assert rule.pattern == "Rain Study.mp3" and rule.style == "smooth"
    assert rule.changes == {"output_format": "flac"}


def test_every_song_setting_can_be_given() -> None:
    rule = parse_line(
        "song.mp3 --vocals center --loudness match --speakers --start 0:10 "
        '--end 1:00 --no-cover --keep-title --speed-curve "0=10, 1:00=6"',
        1,
    )
    assert rule is not None
    changes = rule.changes
    assert changes["vocals"] == "center"
    assert changes["match_loudness"] is True and changes["loudness_target"] is None
    assert changes[SPEAKERS] is True
    assert (changes["trim_start"], changes["trim_end"]) == (10.0, 60.0)
    assert changes["keep_cover"] is False and changes["tag_title"] is False
    assert changes["speed_curve"] == ((0.0, 10.0), (60.0, 6.0))


def test_blank_lines_and_comments_are_skipped() -> None:
    assert parse_line("", 1) is None
    assert parse_line("   # a note", 2) is None


@pytest.mark.parametrize(
    ("line", "words"),
    [
        ("song.mp3", "has no settings"),
        ("song.mp3 --jobs 4", "--jobs can't be set for one song"),
        ("song.mp3 --output-dir D:\\8D", "--output-dir can't be set"),
        ("song.mp3 --preset nosuchstyle", "Line 7"),
        ("song.mp3 --intensity loud", "Line 7"),
        ("song.mp3 --help", "only song settings"),
        ('"unfinished.mp3 --preset studio', "Line 7"),
    ],
)
def test_mistakes_name_the_line(line: str, words: str) -> None:
    with pytest.raises(InputValidationError, match=words):
        parse_line(line, 7)


def test_songs_match_by_name_bare_name_pattern_or_path(tmp_path: Path) -> None:
    song = tmp_path / "Music" / "Rain Study.mp3"
    for pattern in ("Rain Study.mp3", "rain study", "rain*", "*.MP3"):
        rule = parse_line(f'"{pattern}" --intensity 0.5', 1, tmp_path)
        assert rule is not None and rule.matches(song), pattern
    by_path = parse_line('"Music\\Rain Study.mp3" --intensity 0.5', 1, tmp_path)
    assert by_path is not None and by_path.matches(song)
    other = parse_line('"Storm Wall.flac" --intensity 0.5', 1, tmp_path)
    assert other is not None and not other.matches(song)


def test_later_lines_win(tmp_path: Path) -> None:
    file = tmp_path / "songs.txt"
    file.write_text(
        "# every FLAC becomes WAV, and one song is smooth\n"
        "*.flac  --format wav --intensity 0.6\n"
        '"Storm Wall.flac"  --preset smooth --intensity 0.9\n',
        encoding="utf-8",
    )
    rules = read_rules(file)
    style, changes = merged(rules_for(Path("x/Storm Wall.flac"), rules))

    assert style == "smooth"
    assert changes == {"output_format": "wav", "intensity": 0.9}
    assert merged(rules_for(Path("x/Other.mp3"), rules)) == (None, {})


def test_an_empty_or_missing_file_is_explained(tmp_path: Path) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_text("# nothing yet\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="no song lines"):
        read_rules(empty)
    with pytest.raises(InputValidationError, match="Cannot read"):
        read_rules(tmp_path / "missing.txt")
