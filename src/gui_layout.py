# Developed by ::> Gehan Fernando
"""A layout self-check for the window: no control may overlap another or spill out.

Used by the tests (and handy while designing pages): it measures every visible
button, switch, slider, entry, menu and label on a page and reports any control
that overlaps something else, or anything that reaches past the window's edge.
"""

import tkinter as tk

import customtkinter as ctk

# The controls a person clicks or types into
_CONTROLS = (
    ctk.CTkButton,
    ctk.CTkSegmentedButton,
    ctk.CTkSwitch,
    ctk.CTkSlider,
    ctk.CTkEntry,
    ctk.CTkOptionMenu,
    ctk.CTkCheckBox,
    ctk.CTkRadioButton,
)

Box = tuple[int, int, int, int]


def _controls(widget: tk.Misc, labels: bool = False) -> list[tk.Misc]:
    """Every visible control (and, if asked, text label) inside widget."""
    found: list[tk.Misc] = []
    for child in widget.winfo_children():
        if not child.winfo_ismapped():
            continue
        if isinstance(child, _CONTROLS):
            found.append(child)
            # Its own inner buttons belong to it, so they are not checked separately
            continue
        if labels and isinstance(child, ctk.CTkLabel):
            found.append(child)
            continue
        found.extend(_controls(child, labels))
    return found


def _buttons(widgets: list[tk.Misc]) -> list[tk.Misc]:
    """The buttons and switches among widgets, and each option of a choice row."""
    found: list[tk.Misc] = []
    for widget in widgets:
        if isinstance(widget, ctk.CTkSegmentedButton):
            found.extend(getattr(widget, "_buttons_dict", {}).values())
        elif isinstance(widget, (ctk.CTkButton, ctk.CTkSwitch)):
            found.append(widget)
    return found


def _cut_short(button: tk.Misc) -> bool:
    """True when a button's words are drawn narrower than they need."""
    words = getattr(button, "_text_label", None)
    if words is None or not words.winfo_ismapped():
        return False
    return 1 < words.winfo_width() < words.winfo_reqwidth() - 1


def _box(widget: tk.Misc) -> Box:
    """The widget's rectangle on screen: left, top, right, bottom."""
    left, top = widget.winfo_rootx(), widget.winfo_rooty()
    return left, top, left + widget.winfo_width(), top + widget.winfo_height()


def _overlap(a: Box, b: Box) -> bool:
    """True when two rectangles share any area (touching edges is fine)."""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _name(widget: tk.Misc) -> str:
    """A readable name for a control in a report."""
    text = ""
    try:
        text = str(widget.cget("text")).strip()
    except (tk.TclError, ValueError, AttributeError):
        pass
    return (
        f"{widget.__class__.__name__}('{text[:30]}')"
        if text
        else widget.__class__.__name__
    )


def layout_problems(window: tk.Misc, page: tk.Misc) -> list[str]:
    """Plain-word descriptions of every overlap or overflow on a page."""
    window.update_idletasks()
    widgets = _controls(page, labels=True)
    boxes = [
        (_name(w), _box(w), isinstance(w, _CONTROLS))
        for w in widgets
        if w.winfo_width() > 1
    ]
    right_edge = window.winfo_rootx() + window.winfo_width()
    problems = [
        f"{name} reaches past the window's right edge"
        for name, box, _ in boxes
        if box[2] > right_edge + 1
    ]
    # A control wider than the space its row leaves it is cut off, not moved
    problems += [
        f"{_name(w)} is cut off on the right"
        for w in widgets
        if isinstance(w, _CONTROLS)
        and w.winfo_width() > 1
        and _box(w)[2] > _box(w.master)[2] + 1
    ]
    # A button, switch or choice option given less room than its words need
    problems += [
        f"{_name(part)} is squeezed, cutting its words"
        for part in _buttons(widgets)
        if _cut_short(part)
    ]
    for index, (name, box, control) in enumerate(boxes):
        for other_name, other, other_control in boxes[index + 1 :]:
            # A control may not touch anything; two plain labels may sit close
            if (control or other_control) and _overlap(box, other):
                problems.append(f"{name} overlaps {other_name}")
    return problems
