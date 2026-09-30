# Developed by ::> Gehan Fernando
"""Turns what people type (times, keyframe lists) into numbers."""

from .errors import InputValidationError
from .settings import Keyframes


def parse_time(text: str) -> float:
    """Seconds from '90', '1:30', '1:02:03' or '1:30.5'."""
    cleaned = text.strip()
    parts = cleaned.split(":")
    if not cleaned or len(parts) > 3:
        raise InputValidationError(f"'{text}' is not a time like 90 or 1:30")
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        raise InputValidationError(f"'{text}' is not a time like 90 or 1:30") from None
    # Minutes and seconds after the first part must stay below 60, as on a clock
    if any(number < 0 for number in numbers) or any(n >= 60 for n in numbers[1:]):
        raise InputValidationError(f"'{text}' is not a time like 90 or 1:30")
    seconds = 0.0
    # 1:02:03 is ((1 * 60) + 2) * 60 + 3 seconds
    for number in numbers:
        seconds = seconds * 60 + number
    return seconds


def format_time(seconds: float) -> str:
    """'1:30' style text for a number of seconds, the way music players show it."""
    whole = int(round(seconds))
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def parse_keyframes(text: str) -> Keyframes:
    """'0=10, 1:00=6, 2:30=10' -> ((0, 10), (60, 6), (150, 10))."""
    frames = []
    # People write both 0=10, 1:00=6 and 0=10; 1:00=6, so both separators work
    for item in text.replace(";", ",").split(","):
        if not item.strip():
            continue
        time_text, separator, value_text = item.partition("=")
        if not separator:
            raise InputValidationError(
                f"'{item.strip()}' needs the form TIME=VALUE, e.g. 1:00=6"
            )
        try:
            value = float(value_text)
        except ValueError:
            raise InputValidationError(
                f"'{value_text.strip()}' in '{item.strip()}' is not a number"
            ) from None
        frames.append((parse_time(time_text), value))
    if not frames:
        raise InputValidationError("give at least one TIME=VALUE pair, e.g. 0=8")
    return tuple(frames)


def format_exact_time(seconds: float) -> str:
    """Like format_time, but parts of a second are kept: 10.6 -> '0:10.6'."""
    # Whole milliseconds are plenty, and avoid float noise like 10.600000001
    millis = round(seconds * 1000)
    whole, fraction = divmod(millis, 1000)
    text = format_time(whole)
    return f"{text}.{fraction:03d}".rstrip("0") if fraction else text


def format_keyframes(frames: Keyframes) -> str:
    """The reverse of parse_keyframes, used when saving a preset."""
    return ", ".join(f"{format_exact_time(time)}={value:g}" for time, value in frames)


def parse_selection(text: str, count: int) -> list[int]:
    """'all', '1,3,5-7' -> zero-based indexes, in the order the list shows them."""
    cleaned = text.strip().lower()
    # Enter on its own, or any common word for "everything", picks every song
    if cleaned in {"", "all", "a", "*"}:
        return list(range(count))
    chosen: set[int] = set()
    for item in cleaned.replace(" ", ",").split(","):
        if not item:
            continue
        first, dash, last = item.partition("-")
        try:
            start = int(first)
            end = int(last) if dash else start
        except ValueError:
            raise InputValidationError(
                f"'{item}' is not a number or a range like 3-5"
            ) from None
        if not 1 <= start <= end <= count:
            raise InputValidationError(f"'{item}' is outside 1 to {count}")
        chosen.update(range(start - 1, end))
    return sorted(chosen)


def typed_number(text: str, what: str, low: float, high: float) -> float | None:
    """A typed number in a range, or None when the box is empty."""
    if not text.strip():
        return None
    try:
        value = float(text.strip().replace(",", "."))
    except ValueError:
        raise InputValidationError(f"{what} must be a number") from None
    if not low <= value <= high:
        raise InputValidationError(f"{what} must be between {low:g} and {high:g}")
    return value


def typed_loudness(text: str) -> float:
    """A typed loudness level in LUFS, from -30 to -5 (raises with the fix)."""
    target = typed_number(text, "The loudness", -30, -5)
    if target is None:
        raise InputValidationError("Type a loudness between -30 and -5, e.g. -14")
    return target


def typed_time_problem(text: str) -> str | None:
    """Why a typed 'only part' time can't be used, or None (empty means none)."""
    if not text.strip():
        return None
    try:
        parse_time(text)
    except InputValidationError:
        return "Write a time like 90 (seconds) or 1:30 (minutes:seconds)."
    return None
