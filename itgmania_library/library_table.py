"""The song table: the Treeview, its columns and sorting, and selection.

LibraryTable (proposal 0009 Step 6) owns the Treeview, the column order,
widths and sort keys, the row insertion, and the selection. It does not
touch the stores, the paths, or the status line (except through the count
label, which it owns): it reads the rows to display from the filter, and
the Distribution Panel receives them through the show_rows push.

Tests: tests/test_library_table.py.
"""

from __future__ import annotations

import time
try:
    from tkinter import ttk
except ImportError:
    ttk = None

from itgmania_library import row_tints
from itgmania_library.library_constants import (
    COLUMN_GROUPS,
    DEFAULT_VISIBLE_COLUMNS,
    HEADERS,
    NUMERIC_COLUMNS,
)
from itgmania_library.library_format import (
    bpm_sort_key,
    difficulty_sort_key,
    format_duration,
    grade_sort_key,
    number,
)
from itgmania_library.library_geometry import scale_pixels
from itgmania_library.library_stores import _valid_column_width

# How long one batch of table-row inserts may run before yielding to the event
# loop (see _insert_batch): long enough to fill quickly, short enough that the
# window stays responsive while a big library streams in.
ROW_INSERT_BUDGET_SECONDS = 0.012

# Above this many rows out of place, a reorder goes through one
# set_children call instead of per-item tree.index/tree.move (PR #271
# Lane A, finding 2): both calls cost time proportional to the item's
# position, so a full re-sort is O(n^2) — 5.2 s at 20,000 rows against
# 0.39 s for the rebuild — while set_children reorders 42,375 rows in
# 28.7 ms. A handful of displaced rows still move one by one.
SET_CHILDREN_MOVE_THRESHOLD = 50


def _chart_key(row):
    """The chart key that identifies a row across refreshes (Proposal 0019,
    D3): the scores join key plus the chart description, which is what
    distinguishes two Edit charts of the same type and difficulty in one
    song. The loader builds fresh row dicts on every refresh, so identity
    cannot be id(row). The engine does not guarantee this key is unique
    (Song::AddSteps appends without dedup, and two Edits can share a
    description), so a key that collides inside one song is never matched
    — the diff re-inserts that song's rows as a block instead (see
    _apply_diff)."""

    return (row.get("Course path", ""), row.get("Type", ""),
            row.get("Difficulty", ""), row.get("Chart", ""))


def _display_tuple(row, selected=False):
    """The (values, tags) a row is shown with: the 40 display values and
    the difficulty/selection tags. One shared helper for the insert path
    and the in-place update path, so the two cannot drift — on tags as
    well as values, so a sync that changes difficulty or selection state
    cannot leave the tint behind (Proposal 0019, Revision 1)."""

    values = []
    for col in HEADERS:
        value = row.get(col, "")
        if col == "Time" and value != "":
            value = format_duration(value)
        elif isinstance(value, float):
            value = f"{value:g}"
        values.append(value)
    return tuple(values), row_tints.row_tags(row, selected)


def _default_column_width(column):
    """The default width of a column, in canonical 100% units."""
    if column in ("Title", "Subtitle", "Artist", "Pack"):
        return 130
    if column in ("Type", "Difficulty", "Meter", "Time", "BPM", "Score",
                  "Grade", "Best %", "Plays", "Jumps", "Holds", "Rolls",
                  "Mines", "Hands", "Lifts", "W1", "W2", "W3", "W4", "W5",
                  "Miss"):
        return 76
    if column == "Last played":
        return 105
    if column == "Chart":
        return 150
    return 92


class LibraryTable:
    """The Treeview, its columns and sorting, and selection.

    parent: the table frame, for the Treeview.
    filter: the LibraryFilter component, for filter_rows,
        library_rows, and the change notification the table
        subscribes to (see below).
    dpi_scale: the display scale factor.
    column_visibility, group_visibility: shared objects; the View menu
        binds them, and the table mutates them in place (it never
        rebinds them).
    saved_layout: the initial column order, widths, and sort keys, read
        from settings at build — a dict with the "column_order",
        "column_widths", and "sort_keys" settings values.
    count_label: the label showing the row count.
    save_settings: callable, invoked when the sort, the columns, or the
        layout change.
    show_rows: a callable the table invokes with the visible rows after
        each refresh, so the Distribution Panel keeps receiving its push.
    on_open_row: a callable the table invokes with the focused row when
        the user double-clicks a cell or presses Enter on it, so the app
        can open that row's song page. None (the default) means the
        gestures do nothing; the focused row is the one opened, never
        selection()[0], so a multi-selection is left untouched.

    The table owns its sort and column state — _sort_keys, _column_order,
    and _column_widths are not inputs, because sort_by rebinds _sort_keys
    and reset_column_layout rebinds _column_order, so a shared input
    would go stale in the app after a sort click or a reset. It exposes
    layout_state(), which _save_settings reads (it reads the actual
    widths back from tree.column), so the app never holds a stale copy.
    The table reads the rows through the filter (library_rows()),
    which is the single holder of the rows inside the UI (option C,
    PR #168 review): a load sets the filter's rows, a sync re-scores
    them in place, and the table displays what the filter returns.

    The table subscribes its own refresh_table to the filter's change
    notification: subscribe it once, after construction, with
    filter.subscribe(table.refresh_table).
    """

    def __init__(self, parent, filter, dpi_scale, column_visibility,
                 group_visibility, saved_layout, count_label, save_settings,
                 show_rows, on_open_row=None):
        self._parent = parent
        self._filter = filter
        self._dpi_scale = dpi_scale
        self.column_visibility = column_visibility
        self.group_visibility = group_visibility
        self.count_label = count_label
        self._save_settings = save_settings
        self._show_rows = show_rows
        self._on_open_row = on_open_row
        # The render state refresh_table and _insert_batch keep between
        # batches. The rows themselves live in the filter (option C):
        # the table reads them through filter.library_rows().
        self._render_generation = 0
        self._tree_item_rows = {}
        # The diff's state (Proposal 0019): the chart keys in tree order,
        # and the display tuple each item was last shown with. All three
        # maps are maintained together by the table's own insert, delete,
        # and move paths — nothing else mutates the tree.
        self._tree_item_order = []
        self._tree_item_display = {}
        self._dragged_column = None
        self._drag_start_x = None
        self._tree_tint = None
        self._parse_seed(saved_layout)
        self._default_column_widths = {
            column: _default_column_width(column) for column in HEADERS}
        self._build_tree()

    def _parse_seed(self, saved_layout):
        """Build the column order, widths, and sort keys from the saved layout.

        The saved order keeps only columns that still exist, in order,
        with the rest appended; Time, BPM, and Subtitle are placed beside
        their neighbours when the saved order predates them (the same
        placement the app applied when it owned this state).
        """
        saved_order = saved_layout.get("column_order", [])
        if not isinstance(saved_order, list):
            saved_order = []
        valid_order = []
        for column in saved_order:
            if column in HEADERS and column not in valid_order:
                valid_order.append(column)
        self._column_order = valid_order + [
            column for column in HEADERS if column not in valid_order]
        if "Time" not in valid_order:
            self._column_order.remove("Time")
            meter_index = self._column_order.index("Meter")
            self._column_order.insert(meter_index + 1, "Time")
        if "BPM" not in valid_order:
            self._column_order.remove("BPM")
            time_index = self._column_order.index("Time")
            self._column_order.insert(time_index + 1, "BPM")
        if "Subtitle" not in valid_order:
            # A saved order from before Subtitle existed appends it at the
            # far right; put it beside Title instead, like Time/BPM above.
            self._column_order.remove("Subtitle")
            title_index = self._column_order.index("Title")
            self._column_order.insert(title_index + 1, "Subtitle")
        saved_widths = saved_layout.get("column_widths", {})
        if not isinstance(saved_widths, dict):
            saved_widths = {}
        self._column_widths = {
            column: _valid_column_width(saved_widths.get(column), column)
            for column in HEADERS
        }
        self._sort_keys = []
        saved_sort_keys = saved_layout.get("sort_keys", [])
        if isinstance(saved_sort_keys, list):
            for item in saved_sort_keys:
                if (isinstance(item, list) and len(item) == 2
                        and item[0] in HEADERS
                        and isinstance(item[1], bool)
                        and item[0] not in {col for col, _ in self._sort_keys}):
                    self._sort_keys.append((item[0], item[1]))
        if not self._sort_keys:
            self._sort_keys = [("Pack", False)]

    def _build_tree(self):
        """Create the Treeview in the parent frame, with its scrollbars,
        headings, bindings, and tint helper."""
        self.tree = ttk.Treeview(self._parent, columns=HEADERS,
                                 show="headings", selectmode="extended")
        for col in HEADERS:
            self.tree.heading(col, text=col,
                              command=lambda c=col: self.sort_by(c))
            width = self._column_widths[col] or self._default_column_widths[col]
            # Canonical widths (saved or default), scaled to this display.
            self.tree.column(col, width=scale_pixels(width, self._dpi_scale),
                             minwidth=scale_pixels(55, self._dpi_scale),
                             stretch=False, anchor="w" if col in
                             ("Title", "Subtitle", "Artist", "Pack", "Chart")
                             else "center")
        vs = ttk.Scrollbar(self._parent, orient="vertical",
                           command=self.tree.yview)
        hs = ttk.Scrollbar(self._parent, orient="horizontal",
                           command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        self._parent.grid_rowconfigure(0, weight=1)
        self._parent.grid_columnconfigure(0, weight=1)
        self.tree.bind("<ButtonPress-1>", self._column_drag_start, add="+")
        self.tree.bind("<ButtonRelease-1>", self._column_drag_end, add="+")
        self.tree.bind("<ButtonRelease-1>", self._shift_sort_click, add="+")
        self.tree.bind("<ButtonRelease-1>", self._save_settings, add="+")
        self.tree.bind("<Control-a>", self._select_all_rows, add="+")
        self.tree.bind("<Control-A>", self._select_all_rows, add="+")
        self.tree.bind("<Double-Button-1>", self._open_focused_row, add="+")
        self.tree.bind("<Return>", self._open_focused_row_key, add="+")
        visible_columns = [column for column in self._column_order
                           if self.column_visibility[column].get()]
        if visible_columns:
            self.tree.configure(displaycolumns=visible_columns)
        self._update_sort_headings()
        row_tints.configure_tree_tags(self.tree)
        self._tree_tint = row_tints.SelectedRowTint(self.tree)
        self.tree.bind("<<TreeviewSelect>>", self._tree_tint.on_select, add="+")
        self._sync_group_checks()

    def layout_state(self):
        """The layout _save_settings persists: the column order, the widths
        read back from the tree in canonical units, and the sort keys.

        The table owns _sort_keys, _column_order, and _column_widths (sort_by
        and reset_column_layout rebind them), so the app reads the state
        from here instead of holding a copy that would go stale.
        """
        return {
            "column_order": list(self._column_order),
            "column_widths": {
                column: scale_pixels(self.tree.column(column, "width"),
                                     1.0 / self._dpi_scale)
                for column in HEADERS
            },
            "sort_keys": [[column, descending]
                          for column, descending in self._sort_keys],
        }

    def column_visibility_changed(self, changed_column):
        visible = [column for column in self._column_order if self.column_visibility[column].get()]
        if not visible:
            self.column_visibility[changed_column].set(True)
            return
        self._sync_group_checks()
        self.tree.configure(displaycolumns=visible)
        self._save_settings()

    def _sync_group_checks(self):
        for group, variable in self.group_visibility.items():
            variable.set(all(self.column_visibility[column].get() for column in COLUMN_GROUPS[group]))

    def group_visibility_changed(self, group):
        """Show or hide every column of a group at once, then redraw and save a single time."""
        show = self.group_visibility[group].get()
        previous = {column: self.column_visibility[column].get() for column in COLUMN_GROUPS[group]}
        for column in previous:
            self.column_visibility[column].set(show)
        visible = [column for column in self._column_order if self.column_visibility[column].get()]
        if not visible:
            # Same rule as a single column: at least one column must stay on, so the click is undone.
            for column, was_visible in previous.items():
                self.column_visibility[column].set(was_visible)
            self._sync_group_checks()
            return
        self._sync_group_checks()
        self.tree.configure(displaycolumns=visible)
        self._save_settings()

    def reset_column_layout(self):
        self._column_order = list(HEADERS)
        for column, variable in self.column_visibility.items():
            variable.set(column in DEFAULT_VISIBLE_COLUMNS)
        self._sync_group_checks()
        for column, width in self._default_column_widths.items():
            self.tree.column(column, width=scale_pixels(width, self._dpi_scale))
        visible = [column for column in self._column_order if self.column_visibility[column].get()]
        self.tree.configure(displaycolumns=visible)
        self._save_settings()

    def _column_drag_start(self, event):
        if self.tree.identify_region(event.x, event.y) == "heading":
            column = self._displayed_column_at(event.x, event.y)
            self._dragged_column = column
            self._drag_start_x = event.x
        else:
            self._dragged_column = None
            self._drag_start_x = None

    def _column_drag_end(self, event):
        source = self._dragged_column
        start_x = self._drag_start_x
        self._dragged_column = None
        self._drag_start_x = None
        if source is None or start_x is None or abs(event.x - start_x) < 5:
            return
        target = self._displayed_column_at(event.x, event.y)
        if target is None or target == source:
            return
        visible = [column for column in self._column_order if self.column_visibility[column].get()]
        target_index = visible.index(target)
        bounds = self._displayed_column_bounds(target_index)
        insert_after = bounds is not None and event.x >= (bounds[0] + bounds[1]) / 2
        self._column_order.remove(source)
        insert_at = self._column_order.index(target) + int(insert_after)
        self._column_order.insert(insert_at, source)
        visible = [column for column in self._column_order if self.column_visibility[column].get()]
        self.tree.configure(displaycolumns=visible)
        self._save_settings()
        return "break"

    def _displayed_column_at(self, x, y):
        if self.tree.identify_region(x, y) != "heading":
            return None
        display_id = self.tree.identify_column(x)
        try:
            index = int(display_id[1:]) - 1
            visible = [column for column in self._column_order
                       if self.column_visibility[column].get()]
            return visible[index] if 0 <= index < len(visible) else None
        except (ValueError, IndexError):
            return None

    def _displayed_column_bounds(self, index):
        display_id = f"#{index + 1}"
        matches = [x for x in range(self.tree.winfo_width())
                   if self.tree.identify_column(x) == display_id]
        return (matches[0], matches[-1] + 1) if matches else None

    def _open_focused_row(self, event):
        """Double-click on a chart row: open the focused row's song page.

        Only a cell opens the page — a heading, the empty space below the
        rows, and the separators do not. The focused row is the one opened,
        never selection()[0]: with a multi-selection, the double-click
        opens the focused row's song and leaves the selection untouched.
        """
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        self._invoke_open_row()

    def _open_focused_row_key(self, _event=None):
        """Enter on a focused row: open that row's song page.

        The focused row is the criterion, not the mouse position — the
        pointer may be anywhere when Enter is pressed.
        """
        self._invoke_open_row()

    def _invoke_open_row(self):
        """Call on_open_row with the focused row, if there is one."""
        if self._on_open_row is None:
            return
        focused = self.tree.focus()
        row = self._tree_item_rows.get(focused) if focused else None
        if row is not None:
            self._on_open_row(row)

    def _select_all_rows(self, _event=None):
        """Ctrl+A in the table (issue #36): select every displayed row.

        The tree's contents are the filtered set, so selecting all of
        get_children() selects exactly what is shown. The selection
        event then updates the selected-row tint like any other
        selection change. Bound on the tree, not the root, so Ctrl+A
        in the search box or a path entry keeps its text meaning."""
        self.tree.selection_set(self.tree.get_children())

    def _shift_sort_click(self, event):
        if not event.state & 0x0001 or self.tree.identify_region(event.x, event.y) != "heading":
            return
        column = self._displayed_column_at(event.x, event.y)
        if column is not None:
            self.sort_by(column, additive=True)
            return "break"

    def sort_by(self, column, additive=False):
        keys = list(self._sort_keys)
        existing_index = next((index for index, (name, _) in enumerate(keys) if name == column), None)
        if additive:
            if existing_index is None:
                keys.append((column, False))
            else:
                name, descending = keys[existing_index]
                keys[existing_index] = (name, not descending)
        else:
            if existing_index == 0:
                name, descending = keys[0]
                keys[0] = (name, not descending)
            else:
                keys = [(column, False)]
        self._sort_keys = keys
        self.refresh_table(preserve_selection=True)
        self._save_settings()

    def _update_sort_headings(self):
        priorities = {
            column: (index, descending)
            for index, (column, descending) in enumerate(self._sort_keys, 1)}
        for column in HEADERS:
            if column in priorities:
                index, descending = priorities[column]
                marker = "↓" if descending else "↑"
                heading = f"{column} {marker}{index}"
            else:
                heading = column
            self.tree.heading(column, text=heading)

    def refresh_table(self, preserve_selection=False):
        # Selection is carried by chart key, not by item id (Proposal
        # 0019, step 3): the loader builds fresh row dicts on a load, so
        # id(row) cannot survive a refresh that replaces the list.
        selected_keys = set()
        if preserve_selection:
            selected_keys = {
                _chart_key(row) for item in self.tree.selection()
                if (row := self._tree_item_rows.get(item)) is not None
            }
        self._render_generation += 1
        generation = self._render_generation
        self._update_sort_headings()
        visible = self._filter.filter_rows()
        for column, descending in reversed(self._sort_keys):
            present = [row for row in visible if row.get(column) not in (None, "")]
            missing = [row for row in visible if row.get(column) in (None, "")]
            if column in NUMERIC_COLUMNS:
                present.sort(key=lambda row: number(str(row.get(column))), reverse=descending)
            elif column == "Difficulty":
                present.sort(
                    key=lambda row: difficulty_sort_key(row.get(column, "")),
                    reverse=descending)
            elif column == "BPM":
                present.sort(key=bpm_sort_key, reverse=descending)
            elif column == "Grade":
                present.sort(
                    key=lambda row: grade_sort_key(row.get(column, "")),
                    reverse=descending)
            else:
                present.sort(
                    key=lambda row: str(row.get(column, "")).casefold(),
                    reverse=descending)
            visible = present + missing
        if not self._tree_item_rows:
            # The tree starts empty (first load, or the last refresh
            # emptied it): a full insert, streaming in through the
            # existing batched inserter. The selection bridges by key
            # back to the row ids the inserter keeps.
            selected_rows = {
                id(row) for row in visible
                if _chart_key(row) in selected_keys
            }
            self._tree_tint.reset()
            self._insert_batch(visible, 0, generation, selected_rows)
        else:
            self._apply_diff(visible, generation, selected_keys)
        self._show_rows(visible)

    def _apply_diff(self, visible, generation, selected_keys):
        """Make the tree show `visible` by changing only what differs
        from what is already showing (Proposal 0019, step 2).

        Deletes and in-place value updates run synchronously here — they
        are cheap Tcl calls. Inserts and moves run in time-boxed batches
        through _apply_diff_batch, reusing _insert_batch's shape. The
        count label and the tint reset land when the last batch does."""

        new_keys = set()
        new_by_key = {}
        colliding_songs = set()
        for row in visible:
            key = _chart_key(row)
            if key in new_keys:
                # Two rows share one key in this song: never guess which
                # is which — the song's rows are re-inserted as a block.
                colliding_songs.add(key[0])
            new_keys.add(key)
            new_by_key.setdefault(key, row)
        # A key the current tree holds twice is a collision too: the
        # previous refresh re-inserted that song as a block, so both of
        # its items share the key, and neither may be matched.
        seen_keys = set()
        for row in self._tree_item_rows.values():
            key = _chart_key(row)
            if key in seen_keys:
                colliding_songs.add(key[0])
            seen_keys.add(key)
        selected_items = set(self.tree.selection())
        for item, row in list(self._tree_item_rows.items()):
            key = _chart_key(row)
            if key[0] in colliding_songs or key not in new_keys:
                self.tree.delete(item)
                del self._tree_item_rows[item]
                del self._tree_item_display[item]
                self._tree_item_order.remove(key)
                selected_items.discard(item)
        # Selection first, so the tags the update below writes already
        # agree with the selection the tree shows.
        for item, row in self._tree_item_rows.items():
            key = _chart_key(row)
            if key in selected_keys and item not in selected_items:
                self.tree.selection_add(item)
                selected_items.add(item)
                self._tree_tint.note_selected(item)
            elif key not in selected_keys and item in selected_items:
                self.tree.selection_remove(item)
                selected_items.discard(item)
        # A content change is detected from the saved display tuple,
        # never by comparing row dicts: merge_scores re-derives score
        # fields in place, so on a sync the old and new dicts are the
        # same objects and a dict comparison would see no change. The
        # surviving item also takes the new row dict: on a load the
        # filter's rows are fresh dicts, and the song page and the
        # course builder read their row back through _tree_item_rows.
        # The saved tuple does not know about the white tag on_select
        # writes directly onto the tree item (PR #271 Lane A, finding
        # 1): an unchanged refresh would leave a stale selected_row tag
        # behind, so force a rewrite of every item the tint tracker or
        # the selection touches, even when its saved tuple matches.
        forced = set(self._tree_tint.items) | selected_items
        for item, row in list(self._tree_item_rows.items()):
            key = _chart_key(row)
            row = new_by_key[key]
            self._tree_item_rows[item] = row
            shown = _display_tuple(row, key in selected_keys)
            if shown != self._tree_item_display.get(item) or item in forced:
                self.tree.item(item, values=shown[0], tags=shown[1])
                self._tree_item_display[item] = shown
        key_to_item = {
            _chart_key(row): item
            for item, row in self._tree_item_rows.items()
        }
        # The reorder plan (PR #271 Lane A, finding 2): per-item
        # tree.index/tree.move is O(n^2), so a large reorder goes through
        # one set_children call instead. Displaced counts the surviving
        # rows out of place against the order they should appear in. The
        # walk also needs to know whether there is anything to place at
        # all, so a refresh with nothing to insert or move does not show
        # a "Loading …" progress count (the owner's smoke check).
        survivor_keys = {_chart_key(row)
                         for row in self._tree_item_rows.values()}
        target_order = [_chart_key(row) for row in visible
                        if _chart_key(row) in survivor_keys]
        displaced = sum(1 for a, b in zip(self._tree_item_order,
                                          target_order) if a != b)
        inserts_pending = any(_chart_key(row) not in survivor_keys
                              for row in visible)
        large_reorder = displaced > SET_CHILDREN_MOVE_THRESHOLD
        show_progress = inserts_pending or displaced > 0
        placed = [] if large_reorder else None
        self._apply_diff_batch(visible, 0, generation, selected_keys,
                               key_to_item, selected_items,
                               colliding_songs, large_reorder, placed,
                               show_progress)

    def _apply_diff_batch(self, visible, start, generation, selected_keys,
                          key_to_item, selected_items, colliding_songs,
                          large_reorder, placed, show_progress):
        """Insert the new rows and move the reordered ones, in time-boxed
        batches under the same deadline and rescheduling as _insert_batch.
        Deletes and in-place updates already ran synchronously in
        _apply_diff, so this walk only places rows: for each position in
        `visible` order it leaves the item that is already there, moves
        the item that belongs there, or inserts a fresh one. The order
        list is the table's own record of the tree order, so the
        already-there check is a list lookup, not a tree call; tree.index
        is only asked when a row actually has to move. On a large reorder
        the walk skips the per-item moves and collects the items in
        visible order instead, and the last batch reorders the whole
        level with one set_children call."""

        if generation != self._render_generation:
            return
        deadline = time.perf_counter() + ROW_INSERT_BUDGET_SECONDS
        index = start
        while index < len(visible):
            row = visible[index]
            key = _chart_key(row)
            if key[0] in colliding_songs or key not in key_to_item:
                values, tags = _display_tuple(row, key in selected_keys)
                item = self.tree.insert("", index, values=values, tags=tags)
                self._tree_item_rows[item] = row
                self._tree_item_order.insert(index, key)
                self._tree_item_display[item] = (values, tags)
                if key not in colliding_songs:
                    key_to_item[key] = item
                # Selection is carried by exact item, never expanded
                # across a colliding key (Greptile P1 #2, PR #271 Lane B):
                # a block re-insert destroys the selected item's identity,
                # and positional matching is forbidden, so the selection
                # drops for that key instead of landing on every row that
                # shares it. A unique key keeps its item through a sort
                # or sync, so the one-row choice survives there.
                if key in selected_keys and key[0] not in colliding_songs:
                    self.tree.selection_add(item)
                    selected_items.add(item)
                    self._tree_tint.note_selected(item)
                if large_reorder:
                    placed.append(item)
            elif (index >= len(self._tree_item_order)
                    or self._tree_item_order[index] != key):
                item = key_to_item[key]
                if large_reorder:
                    placed.append(item)
                else:
                    current = self.tree.index(item)
                    self.tree.move(item, "", index)
                    self._tree_item_order.pop(current)
                    self._tree_item_order.insert(index, key)
            elif large_reorder:
                placed.append(key_to_item[key])
            index += 1
            if time.perf_counter() >= deadline:
                break
        if index < len(visible):
            if show_progress:
                self.count_label.set(f"Loading {index:,} of {len(visible):,} charts…")
            self._parent.after(1, lambda: self._apply_diff_batch(
                visible, index, generation, selected_keys, key_to_item,
                selected_items, colliding_songs, large_reorder, placed,
                show_progress))
        else:
            if large_reorder:
                self.tree.set_children("", *placed)
                self._tree_item_order = [_chart_key(row) for row in visible]
            self._set_final_count(visible)
            self._tree_tint.reset(selected_items)

    def _set_final_count(self, rows):
        """The count label's settled text, once a refresh has landed."""
        total = len(self._filter.library_rows())
        count_text = f"{len(rows):,} charts shown · {total:,} total"
        hint = self._filter.search_hint()
        if hint:
            count_text += f" — {hint}"
        self.count_label.set(count_text)

    def _insert_batch(self, rows, start, generation, selected_rows=None):
        if generation != self._render_generation:
            return
        selected_rows = selected_rows or set()
        # Insert for a short time budget rather than a fixed count: fast
        # machines finish in fewer, fuller batches; slow ones stay responsive.
        # At least one row always goes in, so the loop cannot stall.
        deadline = time.perf_counter() + ROW_INSERT_BUDGET_SECONDS
        stop = start
        while stop < len(rows):
            row = rows[stop]
            keep_selected = id(row) in selected_rows
            values, tags = _display_tuple(row, keep_selected)
            item = self.tree.insert("", "end", values=values, tags=tags)
            self._tree_item_rows[item] = row
            self._tree_item_order.append(_chart_key(row))
            self._tree_item_display[item] = (values, tags)
            if keep_selected:
                self.tree.selection_add(item)
                self._tree_tint.note_selected(item)
            stop += 1
            if time.perf_counter() >= deadline:
                break
        if stop < len(rows):
            self.count_label.set(f"Loading {stop:,} of {len(rows):,} charts…")
            self._parent.after(1, lambda: self._insert_batch(rows, stop, generation, selected_rows))
        else:
            # The count label is set by _insert_batch: a progress count while rows
            # are still streaming in, the final totals once the last batch lands.
            self._set_final_count(rows)

    def selected_rows(self):
        """The chart rows currently selected in the main table (for the course builder)."""
        return [row for item in self.tree.selection()
                if (row := self._tree_item_rows.get(item)) is not None]

    def library_rows(self):
        """Every chart row in the loaded library (for the course builder's ambiguity check).

        Read through the filter, which is the single holder of the rows
        inside the UI (option C): there is no second copy to keep in step.
        """
        return self._filter.library_rows()
