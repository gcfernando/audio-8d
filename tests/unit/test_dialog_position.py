# Developed by ::> Gehan Fernando
"""Where a popup goes: the middle of its parent window, wherever that window is.

The window tests open every real popup over a normal, moved, resized and
maximized window; these check the arithmetic on its own, without a screen.
"""

import pytest

from src.gui_dialogs import _centre_target


class _Parent:
    """A window with a known inner area on the screen."""

    def __init__(self, x: int, y: int, width: int, height: int) -> None:
        self.box = (x, y, width, height)

    def winfo_rootx(self) -> int:
        """Left edge of the inner area."""
        return self.box[0]

    def winfo_rooty(self) -> int:
        """Top edge of the inner area."""
        return self.box[1]

    def winfo_width(self) -> int:
        """Width of the inner area."""
        return self.box[2]

    def winfo_height(self) -> int:
        """Height of the inner area."""
        return self.box[3]


@pytest.mark.parametrize(
    ("parent", "size", "expected"),
    [
        # A normal window
        ((100, 50, 800, 600), (200, 100), (400, 300)),
        # Maximized on the main screen
        ((0, 0, 2560, 1400), (900, 700), (830, 350)),
        # On a monitor left of the main one (negative screen coordinates)
        ((-1920, 120, 1600, 900), (400, 300), (-1320, 420)),
        # On a monitor above the main one
        ((200, -1080, 1200, 800), (600, 400), (500, -880)),
        # A popup bigger than the window still shares its centre
        ((300, 200, 600, 400), (800, 600), (200, 100)),
    ],
)
def test_a_popup_is_centred_on_its_parents_inner_area(
    parent: tuple[int, int, int, int],
    size: tuple[int, int],
    expected: tuple[int, int],
) -> None:
    x, y = _centre_target(_Parent(*parent), *size)  # type: ignore[arg-type]

    assert (x, y) == expected
    # The popup's centre is the window's centre, to the pixel
    assert x + size[0] // 2 == pytest.approx(parent[0] + parent[2] // 2, abs=1)
    assert y + size[1] // 2 == pytest.approx(parent[1] + parent[3] // 2, abs=1)
