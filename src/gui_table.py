# Developed by ::> Gehan Fernando
"""A fast song table for the window, built on Tk's own Treeview.

A Treeview draws only the rows on screen, so hundreds of songs stay quick
(one CustomTkinter frame per song would not). It gives multi-selection with
Shift and Ctrl, the arrow keys, and sortable column headings for free. Group
headings ("Rock · 12 songs") are rows too: selecting one selects its songs.
"""

import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from tkinter import ttk
from typing import Literal

import customtkinter as ctk

from .gui_widgets import (
    ACCENT,
    ACCENT_SOFT,
    ACCENT_TEXT,
    BORDER,
    DANGER,
    FOCUS,
    INK,
    SURFACE,
    SURFACE_ALT,
    TEXT_DIM,
    shade,
)

GROUP_PREFIX = "group:"


def style_tables(root: tk.Misc) -> tuple[str, int]:
    """Give Tk's table (ttk.Treeview) the window's colours; returns its font."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    bg, ink, dim = shade(SURFACE), shade(INK), shade(TEXT_DIM)
    head, line = shade(SURFACE_ALT), shade(BORDER)
    chosen, chosen_ink = shade(ACCENT_SOFT), shade(INK)
    scaling = ctk.ScalingTracker.get_widget_scaling(root)
    row_height = int(30 * scaling)
    size = max(9, round(10 * scaling))
    style.configure(
        "Audio8D.Treeview",
        background=bg,
        fieldbackground=bg,
        foreground=ink,
        bordercolor=line,
        lightcolor=line,
        darkcolor=line,
        rowheight=row_height,
        font=("Segoe UI", size),
        borderwidth=1,
        relief="flat",
    )
    style.map(
        "Audio8D.Treeview",
        background=[("selected", "focus", shade(ACCENT)), ("selected", chosen)],
        foreground=[("selected", "focus", "#FFFFFF"), ("selected", chosen_ink)],
    )
    style.configure(
        "Audio8D.Treeview.Heading",
        background=head,
        foreground=dim,
        bordercolor=line,
        lightcolor=head,
        darkcolor=head,
        relief="flat",
        font=("Segoe UI", size, "bold"),
        padding=(8, int(6 * scaling)),
    )
    style.map(
        "Audio8D.Treeview.Heading",
        background=[("active", shade(ACCENT_SOFT))],
    )
    style.layout("Audio8D.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    return ("Segoe UI", size)


@dataclass(frozen=True, slots=True)
class Column:
    """One column: its key, heading, width in pixels, and alignment.

    least is the narrowest it may get in a narrow window (0: it shrinks like
    the others), for a column whose words matter more than the rest.
    """

    key: str
    heading: str
    width: int
    anchor: Literal["w", "center", "e"] = "w"
    stretch: bool = False
    least: int = 0


# One table row: (row id, the values in column order, tags such as 'own')
Row = tuple[str, Sequence[str], Sequence[str]]


class SongTable(ctk.CTkFrame):
    """A scrolling table of songs with groups, selection and sortable headings."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        master: tk.Misc,
        columns: Sequence[Column],
        *,
        height: int = 12,
        on_select: Callable[[], None] | None = None,
        on_sort: Callable[[str], None] | None = None,
        on_activate: Callable[[str], None] | None = None,
        label: str = "Songs",
    ) -> None:
        """on_select runs when the selection changes; on_sort gets a column key."""
        super().__init__(
            master,
            fg_color=SURFACE,
            corner_radius=8,
            border_width=1,
            border_color=BORDER,
        )
        self.columns = list(columns)
        self.on_select = on_select
        self.on_activate = on_activate
        self.label = label
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        style_tables(self)
        self.tree = ttk.Treeview(
            self,
            columns=[column.key for column in self.columns],
            show="headings",
            height=height,
            selectmode="extended",
            style="Audio8D.Treeview",
        )
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(2, 0), pady=2)
        scale = ctk.ScalingTracker.get_widget_scaling(self)
        for column in self.columns:
            self.tree.heading(
                column.key,
                text=column.heading,
                anchor=column.anchor,
                command=(lambda key=column.key: on_sort(key)) if on_sort else "",
            )
            self.tree.column(
                column.key,
                width=int(column.width * scale),
                minwidth=int(60 * scale),
                anchor=column.anchor,
                # Widths are shared out by _fit_columns, never by Tk itself
                stretch=False,
            )
        scrollbar = ctk.CTkScrollbar(self, command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 2), pady=4)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.paint()
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        self.tree.bind("<Control-a>", self._select_all_key)
        self.tree.bind("<Control-A>", self._select_all_key)
        self.tree.bind("<Double-1>", self._activated)
        self.tree.bind("<Return>", self._activated)
        # The page scrolls too; over the table, the wheel scrolls only the table
        self.tree.bind("<MouseWheel>", self._wheel)
        self.tree.bind("<FocusIn>", lambda _e: self._focus_ring(True), add="+")
        self.tree.bind("<FocusOut>", lambda _e: self._focus_ring(False), add="+")
        self.tree.bind("<Configure>", self._fit_columns, add="+")
        self._fitted_to = 0
        self._groups: dict[str, list[str]] = {}
        self._quiet = False

    # ------------------------------------------------------------ looks

    def _fit_columns(self, event: tk.Event) -> None:
        """Share the table's width out: spare room to the wide columns, a lack to all.

        Tk would otherwise take a lack only from the stretching columns, which
        squeezed the song names to a few letters in a narrow window.
        """
        room = event.width - 4
        if room <= 0 or room == self._fitted_to:
            return
        self._fitted_to = room
        scale = ctk.ScalingTracker.get_widget_scaling(self)
        wanted = [column.width * scale for column in self.columns]
        total = sum(wanted)
        stretching = sum(1 for column in self.columns if column.stretch)
        if room >= total and stretching:
            extra = (room - total) / stretching
            widths = [
                width + (extra if column.stretch else 0)
                for width, column in zip(wanted, self.columns, strict=True)
            ]
        else:
            widths = self._shrunk(wanted, room, scale)
        for column, width in zip(self.columns, widths, strict=True):
            self.tree.column(column.key, width=max(int(60 * scale), int(width)))

    def _shrunk(self, wanted: list[float], room: float, scale: float) -> list[float]:
        """Widths that fit room: each column keeps its least, the rest share alike."""
        least = [column.least * scale for column in self.columns]
        kept = [
            w * room / sum(wanted) < low for w, low in zip(wanted, least, strict=True)
        ]
        left = room - sum(low for low, keep in zip(least, kept, strict=True) if keep)
        others = sum(w for w, keep in zip(wanted, kept, strict=True) if not keep) or 1
        return [
            low if keep else w * max(left, 0) / others
            for w, low, keep in zip(wanted, least, kept, strict=True)
        ]

    def paint(self) -> None:
        """Apply the current theme's colours (call again after a theme change)."""
        family, size = style_tables(self)
        self.tree.tag_configure("group", background=shade(SURFACE_ALT))
        self.tree.tag_configure("group", foreground=shade(ACCENT_TEXT))
        self.tree.tag_configure("problem", foreground=shade(DANGER))
        self.tree.tag_configure("muted", foreground=shade(TEXT_DIM))
        self.tree.tag_configure("current", background=shade(ACCENT_SOFT))
        # A song with its own settings stands out in bold (its row also says Custom)
        self.tree.tag_configure("own", font=(family, size, "bold"))

    def _focus_ring(self, on: bool) -> None:
        """A focus-coloured border while the keyboard is in the table."""
        try:
            self.configure(
                border_color=FOCUS if on else BORDER, border_width=2 if on else 1
            )
        except tk.TclError:
            pass

    def _wheel(self, event: tk.Event) -> str:
        """Scroll the table itself, never the page behind it."""
        self.tree.yview_scroll(
            int(-event.delta / 120) or (-1 if event.delta > 0 else 1), "units"
        )
        return "break"

    # ------------------------------------------------------------ content

    def show(self, groups: Sequence[tuple[str, Sequence[Row]]]) -> None:
        """Replace every row, keeping the selection and focus where they still exist.

        A group with a title gets a heading row; an untitled group lists its rows
        straight away.
        """
        chosen = set(self.selected())
        focus = self.tree.focus()
        top = self.tree.yview()[0]
        self._quiet = True
        self.tree.delete(*self.tree.get_children())
        self._groups = {}
        for title, rows in groups:
            if title:
                gid = f"{GROUP_PREFIX}{title}"
                count = len(rows)
                words = f"{count} song{'s' if count != 1 else ''}"
                values = [title, words] + [""] * (len(self.columns) - 2)
                self.tree.insert("", "end", iid=gid, values=values, tags=("group",))
                self._groups[gid] = [row[0] for row in rows]
            for iid, values, tags in rows:
                self.tree.insert(
                    "", "end", iid=iid, values=list(values), tags=tuple(tags)
                )
        keep = [iid for iid in chosen if self.tree.exists(iid)]
        if keep:
            self.tree.selection_set(keep)
        if focus and self.tree.exists(focus):
            self.tree.focus(focus)
        self.tree.yview_moveto(top)
        self._quiet = False

    def update_row(self, iid: str, values: Sequence[str], tags: Sequence[str]) -> None:
        """Refresh one row in place (nothing happens if it isn't shown)."""
        if self.tree.exists(iid):
            self.tree.item(iid, values=list(values), tags=tuple(tags))

    def row_ids(self) -> list[str]:
        """Every song row shown, top to bottom (group headings left out)."""
        return [
            iid for iid in self.tree.get_children() if not iid.startswith(GROUP_PREFIX)
        ]

    # ------------------------------------------------------------ selection

    def selected(self) -> list[str]:
        """The selected songs' row ids (group headings stand for their songs)."""
        found: list[str] = []
        for iid in self.tree.selection():
            if iid.startswith(GROUP_PREFIX):
                found += [
                    song for song in self._groups.get(iid, []) if song not in found
                ]
            elif iid not in found:
                found.append(iid)
        return found

    def focused(self) -> str | None:
        """The row the keyboard (or the last click) is on, if it is a song."""
        focus = self.tree.focus()
        if focus and not focus.startswith(GROUP_PREFIX) and self.tree.exists(focus):
            return focus
        chosen = self.selected()
        return chosen[0] if chosen else None

    def select(self, iids: Sequence[str], focus: str | None = None) -> None:
        """Select these rows (and move the keyboard focus to one of them)."""
        keep = [iid for iid in iids if self.tree.exists(iid)]
        self.tree.selection_set(keep)
        target = (
            focus if focus and self.tree.exists(focus) else (keep[0] if keep else "")
        )
        if target:
            self.tree.focus(target)
            self.tree.see(target)

    def select_all(self) -> None:
        """Select every song shown."""
        self.tree.selection_set(self.row_ids())
        self._selected()

    def clear_selection(self) -> None:
        """Select nothing."""
        self.tree.selection_set([])

    def _select_all_key(self, _event: tk.Event) -> str:
        """Ctrl+A in the table."""
        self.select_all()
        return "break"

    def _selected(self, _event: object = None) -> None:
        """A group heading selects its songs; then tell the page."""
        if self._quiet:
            return
        groups = [iid for iid in self.tree.selection() if iid.startswith(GROUP_PREFIX)]
        if groups:
            self._quiet = True
            focus = self.tree.focus()
            self.tree.selection_set(self.selected())
            if focus in groups and self._groups.get(focus):
                self.tree.focus(self._groups[focus][0])
            self._quiet = False
        if self.on_select is not None:
            self.on_select()

    def _activated(self, _event: tk.Event) -> str | None:
        """Double-click or Enter on a song."""
        iid = self.focused()
        if iid and self.on_activate is not None:
            self.on_activate(iid)
            return "break"
        return None
