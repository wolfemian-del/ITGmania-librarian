"""Tests for the song table component (proposal 0009 Step 6).

Headless: the table is built on fake Tk objects (the Treeview and
scrollbars are Mocks, patched in), so these run without a display. The
live table tests (selection only — the Ctrl+A test) stay in
tests/test_library_librarian.py — the windows-ui job runs exactly two
test files, and a new file would need a workflow edit only the owner can
make; the drag and sort-click tests are headless in this file.
"""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from itgmania_library.library_constants import HEADERS, TAP_FIELDS
from itgmania_library.library_geometry import scale_pixels
from itgmania_library.library_sources import merge_scores
from itgmania_library.library_stores import SettingsStore
from itgmania_library import library_table as table_module
from itgmania_library import row_tints
from itgmania_library import library_librarian as app
from itgmania_library.library_filter import LibraryFilter
from itgmania_library.library_table import LibraryTable


class _ValueVar:
    """A minimal value-carrying stand-in for a Tk variable: get/set over a
    stored string, so tests can preset a value and observe the result."""

    def __init__(self, value, on_set=None):
        self.value = value
        self.on_set = on_set
        self._traces = []

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        if self.on_set is not None:
            self.on_set()
        for callback in self._traces:
            callback()

    def trace_add(self, mode, callback):
        """Record a write-trace callback, like tk.Variable.trace_add; set() fires it."""
        self._traces.append(callback)
        return f"trace-{len(self._traces)}"


class FakeVariable:
    """A BooleanVar stand-in: get/set over a stored bool."""

    def __init__(self, value=False):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def make_filter(rows=()):
    """A real LibraryFilter on _ValueVars, holding the given rows."""
    search_var = _ValueVar("")
    filt = LibraryFilter(
        search_var, _ValueVar("All packs"), _ValueVar("All types"),
        _ValueVar("All difficulties"), _ValueVar(False),
        Mock(), Mock(), Mock(), Mock(), Mock())
    filt.set_rows(list(rows))
    return filt


def make_table(column_order=None, column_widths=None, sort_keys=None,
               visible_columns=None, column_visibility=None,
               group_visibility=None, rows=(), show_rows=None,
               save_settings=None, count_label=None, dpi_scale=1.0,
               on_open_row=None, tree=None):
    """A real LibraryTable on fake Tk objects, plus the Mock tree it built.

    The Treeview and scrollbars are patched to Mocks (the table creates
    them in __init__), so no display is needed; the filter is real, so
    refresh_table reads the rows it returns. The filter's rows are set
    before the table subscribes, so the setup itself does not refresh.
    column_visibility
    and group_visibility default to fresh FakeVariable dicts, or pass
    the app's shared dicts (the save tests do, so _save_settings reads
    the same objects the table mutates). Pass a tree to build the table
    on it instead of a Mock — the diff tests pass a FakeTreeview, which
    keeps the tree's state the way a real Treeview does.
    """
    parent = Mock()
    if tree is None:
        tree = Mock()
        tree.get_children.return_value = []
        tree.column.return_value = 100
    if column_visibility is None:
        column_visibility = {
            col: FakeVariable(True if visible_columns is None
                              else col in visible_columns)
            for col in app.HEADERS}
    if group_visibility is None:
        group_visibility = {group: FakeVariable()
                            for group in app.COLUMN_GROUPS}
    filt = make_filter(rows)
    seed = {
        "column_order": list(column_order) if column_order is not None else list(app.HEADERS),
        "column_widths": dict(column_widths) if column_widths is not None else {},
        "sort_keys": [list(item) for item in sort_keys] if sort_keys is not None else [],
    }
    # The table calls only ttk.Treeview and ttk.Scrollbar, so a stand-in with just
    # those needs no Tkinter. Anything else a future table change asks of ttk
    # raises AttributeError here, as real ttk would without a display.
    fake_ttk = SimpleNamespace(Treeview=Mock(return_value=tree),
                               Scrollbar=Mock(return_value=Mock()))
    with patch.object(table_module, "ttk", fake_ttk):
        table = LibraryTable(
            parent, filt, dpi_scale, column_visibility, group_visibility,
            seed, count_label if count_label is not None else Mock(),
            save_settings if save_settings is not None else Mock(),
            show_rows if show_rows is not None else Mock(),
            on_open_row=on_open_row)
    # The app subscribes the table's filter-change refresh to the
    # filter once the table exists; the filter's rows were set before
    # that, so the setup itself does not refresh.
    filt.subscribe(table.refresh_on_filter_change)
    return table, tree


def rows_for(*specs):
    """Chart rows from (Pack, Type, Difficulty) specs, for filter tests."""
    return [{"Pack": pack, "Type": type_, "Difficulty": difficulty,
             "Title": "Song", "Grade": ""}
            for pack, type_, difficulty in specs]


class FakeTreeview:
    """A minimal in-memory Treeview: items in order, values/tags, selection.

    The diff tests need a tree that actually keeps state — a Mock returns
    the same item for every insert and forgets deletes — so this fake
    models the parts LibraryTable uses: insert/delete/move/index/item,
    get_children, and the selection set. Everything else is a no-op.
    """

    def __init__(self):
        self._items = {}
        self._order = []
        self._selection = set()
        self._focus = ""
        self._counter = 0
        # How the table reordered rows: a test reads these to pin the
        # move arm (per-item moves for a small reorder, one set_children
        # for a large one) and the insert arm (at-index for a small
        # placement, at "end" for a large one). move_calls records
        # (item, index) so a test can pin that a fallback reattach moves
        # to "end" only, never to an index.
        self.move_calls = []
        self.set_children_calls = []
        self.insert_calls = []
        self.detach_calls = []
        self.delete_calls = []
        self.index_calls = []

    def insert(self, parent, index, values=(), tags=()):
        item = f"item{self._counter}"
        self._counter += 1
        self._items[item] = {"values": tuple(values), "tags": tuple(tags)}
        self.insert_calls.append(index)
        if index == "end" or index >= len(self._order):
            self._order.append(item)
        else:
            self._order.insert(index, item)
        return item

    def delete(self, *items):
        for item in items:
            self._items.pop(item, None)
            self.delete_calls.append(item)
            if item in self._order:
                self._order.remove(item)
            self._selection.discard(item)
            if item == self._focus:
                self._focus = ""

    def detach(self, item):
        """Remove the item from display but keep it, like the real
        Treeview: its values and tags stay addressable by id, and it
        keeps no place in the children list. Detaching a selected row
        drops it from the selection, as the probe establishes."""
        self.detach_calls.append(item)
        if item in self._order:
            self._order.remove(item)
        self._selection.discard(item)

    def move(self, item, parent, index):
        # A move reattaches a detached item (Proposal 0021, §6): it has
        # no place in the children list to remove first.
        self.move_calls.append((item, index))
        if item in self._order:
            self._order.remove(item)
        if index == "end" or index >= len(self._order):
            self._order.append(item)
        else:
            self._order.insert(index, item)

    def set_children(self, parent, *items):
        """Reorder the level in one call, like the real Treeview: items
        omitted from the list are detached, not destroyed, so they keep
        their values and tags — but detachment drops their selection,
        as the probe establishes, so an omitted item that was selected
        does not come back selected if a later set_children reattaches
        it (CoPilot review, PR #283 Revision 1)."""
        self.set_children_calls.append(tuple(items))
        for item in self._order:
            if item not in items:
                self._selection.discard(item)
        self._order = list(items)

    def index(self, item):
        # A detached item has no visible position: the real Treeview
        # returns a misleading 0, not an error (Proposal 0021, §6) —
        # returning 0 here is what lets the fake catch a move branch
        # that pops the wrong key for a detached item.
        self.index_calls.append(item)
        return self._order.index(item) if item in self._order else 0

    def get_children(self, item=None):
        return tuple(self._order)

    def item(self, item, option=None, **kwargs):
        if option is not None:
            if option == "values":
                return self._items[item]["values"]
            return self._items[item]["tags"]
        if kwargs:
            if "values" in kwargs:
                self._items[item]["values"] = tuple(kwargs["values"])
            if "tags" in kwargs:
                self._items[item]["tags"] = tuple(kwargs["tags"])
        return dict(self._items[item])

    def selection(self):
        return tuple(item for item in self._order if item in self._selection)

    def selection_add(self, *items):
        self._selection.update(items)

    def selection_remove(self, *items):
        self._selection.difference_update(items)

    def selection_set(self, items):
        self._selection = set(items)

    def exists(self, item):
        return item in self._items

    def focus(self, item=None):
        # With an item, set the focus (as the table's detach step does
        # when it relocates focus); without one, return the focused
        # item, "" when none is focused.
        if item is None:
            return self._focus
        self._focus = item
        return self._focus

    # The constructor and the column/heading helpers call these; they do
    # nothing here.
    def heading(self, *args, **kwargs):
        pass

    def column(self, *args, **kwargs):
        return 100

    def configure(self, *args, **kwargs):
        pass

    def grid(self, *args, **kwargs):
        pass

    def bind(self, *args, **kwargs):
        pass

    def tag_configure(self, *args, **kwargs):
        pass

    def identify_region(self, *args, **kwargs):
        return "cell"

    def identify_column(self, *args, **kwargs):
        return "#1"

    def winfo_width(self):
        return 300

    def yview(self, *args, **kwargs):
        pass

    def xview(self, *args, **kwargs):
        pass

    # Test helpers: the visible contents, row for row and in order.
    def shown_rows(self, table):
        return [table._tree_item_rows[item] for item in self._order]

    def shown_values(self):
        return [self._items[item]["values"] for item in self._order]


def make_diff_table(rows=(), sort_keys=None):
    """A real LibraryTable on a FakeTreeview, so the diff tests can read
    the tree's actual contents after a refresh."""
    return make_table(rows=rows, sort_keys=sort_keys, tree=FakeTreeview())


def diff_rows(*specs):
    """Chart rows from (Course path, Type, Difficulty, Chart) specs, for
    the diff tests. Pack and Title come from the path, so the default
    Pack sort orders them by pack."""
    rows = []
    for path, type_, difficulty, chart in specs:
        pack, title = path.split("/", 1)
        rows.append({"Course path": path, "Type": type_,
                     "Difficulty": difficulty, "Chart": chart,
                     "Pack": pack, "Title": title, "Grade": "",
                     "Time": 60, "Meter": 10})
    return rows


class OpenRowBindingTests(unittest.TestCase):
    """The double-click and Enter bindings open the focused row's song page
    (Proposal 0011, stage 3): only a cell opens it, the focused row is the
    one opened, and a multi-selection is left untouched."""

    ROW = {"Title": "One", "Course path": "P/One"}

    @staticmethod
    def make_table(on_open_row=None):
        table, tree = make_table(on_open_row=on_open_row)
        table._tree_item_rows = {"item1": OpenRowBindingTests.ROW}
        tree.focus.return_value = "item1"
        return table, tree

    @staticmethod
    def event(region="cell"):
        event = Mock()
        event.x = 5
        event.y = 5
        return event

    def test_double_click_on_a_cell_opens_the_focused_row(self):
        opened = Mock()
        table, tree = self.make_table(on_open_row=opened)
        tree.identify_region.return_value = "cell"

        table._open_focused_row(self.event())

        opened.assert_called_once_with(self.ROW)

    def test_double_click_on_a_heading_opens_nothing(self):
        opened = Mock()
        table, tree = self.make_table(on_open_row=opened)
        tree.identify_region.return_value = "heading"

        table._open_focused_row(self.event())

        opened.assert_not_called()

    def test_double_click_on_empty_space_opens_nothing(self):
        opened = Mock()
        table, tree = self.make_table(on_open_row=opened)
        tree.identify_region.return_value = "nothing"

        table._open_focused_row(self.event())

        opened.assert_not_called()

    def test_enter_opens_the_focused_row_whatever_the_mouse_is_over(self):
        opened = Mock()
        table, tree = self.make_table(on_open_row=opened)
        tree.identify_region.return_value = "heading"

        table._open_focused_row_key(self.event())

        opened.assert_called_once_with(self.ROW)

    def test_no_focused_row_opens_nothing(self):
        opened = Mock()
        table, tree = self.make_table(on_open_row=opened)
        tree.identify_region.return_value = "cell"
        tree.focus.return_value = ""

        table._open_focused_row(self.event())
        table._open_focused_row_key(self.event())

        opened.assert_not_called()

    def test_no_callback_means_the_gestures_do_nothing(self):
        table, tree = self.make_table(on_open_row=None)
        tree.identify_region.return_value = "cell"

        table._open_focused_row(self.event())
        table._open_focused_row_key(self.event())

    def test_enter_leaves_the_selection_untouched(self):
        opened = Mock()
        table, tree = self.make_table(on_open_row=opened)
        tree.selection.return_value = ("item1", "item2")

        table._open_focused_row_key(self.event())

        opened.assert_called_once_with(self.ROW)
        tree.selection_set.assert_not_called()
        tree.selection_add.assert_not_called()
        tree.selection_remove.assert_not_called()


if __name__ == "__main__":
    unittest.main()
class ColumnGroupTests(unittest.TestCase):
    @staticmethod
    def make_table(visible_columns):
        table, tree = make_table(visible_columns=visible_columns)
        # The table's construction configures the tree (scrollbars, display
        # columns); these tests pin only the calls the gesture makes.
        tree.reset_mock()
        return table

    @staticmethod
    def shown(table):
        return {col for col, var in table.column_visibility.items() if var.get()}

    def test_every_column_is_in_exactly_one_group(self):
        grouped = [column for columns in app.COLUMN_GROUPS.values() for column in columns]
        self.assertEqual(sorted(grouped), sorted(app.HEADERS))

    def test_groups_are_listed_in_menu_order(self):
        self.assertEqual(list(app.COLUMN_GROUPS),
                         ["Song & chart", "Score", "Tap judgments", "Chart counts", "Tech counts"])

    def test_default_columns_are_song_and_chart_plus_score(self):
        # Issue #49: Subtitle is the one exception — in "Song & chart" but
        # hidden by default, while its group-mates default to shown.
        expected = {*app.COLUMN_GROUPS["Song & chart"], *app.COLUMN_GROUPS["Score"]} - {"Subtitle"}
        self.assertEqual(set(app.DEFAULT_VISIBLE_COLUMNS), expected)
        self.assertNotIn("Subtitle", app.DEFAULT_VISIBLE_COLUMNS)
        self.assertIn("Subtitle", app.COLUMN_GROUPS["Song & chart"])
        self.assertTrue({"Title", "Artist", "Pack"} <= set(app.DEFAULT_VISIBLE_COLUMNS))

    def test_group_check_is_on_only_when_the_whole_group_is_shown(self):
        table = self.make_table(app.DEFAULT_VISIBLE_COLUMNS)
        self.assertTrue(table.group_visibility["Score"].get())
        self.assertFalse(table.group_visibility["Tap judgments"].get())
        table.column_visibility["Grade"].set(False)
        table.column_visibility_changed("Grade")
        self.assertFalse(table.group_visibility["Score"].get())

    def test_group_switch_shows_then_hides_a_whole_group_with_one_save(self):
        table = self.make_table(app.DEFAULT_VISIBLE_COLUMNS)
        table.group_visibility["Tap judgments"].set(True)  # what Tk does before calling the command
        table.group_visibility_changed("Tap judgments")
        self.assertTrue(set(TAP_FIELDS) <= self.shown(table))
        table.tree.configure.assert_called_once()
        table._save_settings.assert_called_once()

        table.group_visibility["Tap judgments"].set(False)
        table.group_visibility_changed("Tap judgments")
        self.assertFalse(set(TAP_FIELDS) & self.shown(table))
        self.assertEqual(set(table.tree.configure.call_args.kwargs["displaycolumns"]),
                         set(app.DEFAULT_VISIBLE_COLUMNS))

    def test_group_switch_cannot_hide_the_last_visible_columns(self):
        table = self.make_table(app.COLUMN_GROUPS["Score"])
        table.group_visibility["Score"].set(False)
        table.group_visibility_changed("Score")
        self.assertEqual(self.shown(table), set(app.COLUMN_GROUPS["Score"]))
        self.assertTrue(table.group_visibility["Score"].get())
        table.tree.configure.assert_not_called()
        table._save_settings.assert_not_called()

    def test_reset_column_layout_restores_the_default_columns(self):
        table = self.make_table(app.HEADERS)
        table._column_order = list(reversed(app.HEADERS))
        table.reset_column_layout()
        self.assertEqual(self.shown(table), set(app.DEFAULT_VISIBLE_COLUMNS))
        self.assertEqual(table.layout_state()["column_order"], list(app.HEADERS))
        self.assertEqual(table.tree.configure.call_args.kwargs["displaycolumns"],
                         [col for col in app.HEADERS if col in app.DEFAULT_VISIBLE_COLUMNS])
        # The widths go back to defaults too (GLM, PR #168 review): a
        # reset that restored the order but left the widths dragged
        # would pass the assertions above.
        table.tree.column.assert_any_call(
            "Title", width=scale_pixels(130, 1.0))
        self.assertFalse(table.group_visibility["Tech counts"].get())
        # "Song & chart" reads unchecked after a reset: Subtitle belongs to
        # the group but starts hidden (issue #49), so the group is never
        # fully shown by default.
        self.assertFalse(table.group_visibility["Song & chart"].get())


class ColumnDragTests(unittest.TestCase):
    """Column drag reorder and the displayed-column helpers: which column a
    heading position names, the screen span of a displayed column, and the
    drag that reorders the columns and saves."""

    COLUMNS = ["Title", "Artist", "Pack"]

    @staticmethod
    def make_table():
        table, tree = make_table(column_order=list(ColumnDragTests.COLUMNS))
        table._column_order = list(ColumnDragTests.COLUMNS)
        tree.identify_region.return_value = "heading"
        # Each displayed column owns a 100px span: #1 is 0-99, #2 is
        # 100-199, #3 is 200-299.
        tree.identify_column.side_effect = (
            lambda x: "#1" if x < 100 else ("#2" if x < 200 else "#3"))
        tree.winfo_width.return_value = 300
        # The table's construction configures the tree; these tests pin
        # only the calls the drag makes.
        tree.reset_mock()
        return table

    @staticmethod
    def event(x, y=10):
        event = Mock()
        event.x = x
        event.y = y
        return event

    def test_displayed_column_at_returns_the_visible_column(self):
        table = self.make_table()
        self.assertEqual(table._displayed_column_at(150, 10), "Artist")

    def test_displayed_column_at_returns_none_outside_the_heading(self):
        table = self.make_table()
        table.tree.identify_region.return_value = "cell"
        self.assertIsNone(table._displayed_column_at(150, 10))

    def test_displayed_column_at_returns_none_for_an_unknown_column_id(self):
        table = self.make_table()
        table.tree.identify_column.side_effect = None
        table.tree.identify_column.return_value = "abc"
        self.assertIsNone(table._displayed_column_at(150, 10))

    def test_displayed_column_at_returns_none_when_the_index_is_out_of_range(self):
        table = self.make_table()
        table.tree.identify_column.side_effect = None
        table.tree.identify_column.return_value = "#9"
        self.assertIsNone(table._displayed_column_at(150, 10))

    def test_displayed_column_bounds_span_the_columns_screen_range(self):
        table = self.make_table()
        self.assertEqual(table._displayed_column_bounds(0), (0, 100))
        self.assertEqual(table._displayed_column_bounds(1), (100, 200))
        self.assertEqual(table._displayed_column_bounds(2), (200, 300))

    def test_displayed_column_bounds_returns_none_with_no_match(self):
        table = self.make_table()
        table.tree.identify_column.side_effect = None
        table.tree.identify_column.return_value = "#9"
        self.assertIsNone(table._displayed_column_bounds(0))

    def test_drag_start_records_the_column_and_position(self):
        table = self.make_table()

        table._column_drag_start(self.event(50))

        self.assertEqual(table._dragged_column, "Title")
        self.assertEqual(table._drag_start_x, 50)

    def test_drag_start_outside_the_heading_clears_the_drag(self):
        table = self.make_table()
        table.tree.identify_region.return_value = "cell"

        table._column_drag_start(self.event(50))

        self.assertIsNone(table._dragged_column)
        self.assertIsNone(table._drag_start_x)

    def test_drag_end_without_a_drag_does_nothing(self):
        table = self.make_table()

        result = table._column_drag_end(self.event(250))

        self.assertIsNone(result)
        table.tree.configure.assert_not_called()
        table._save_settings.assert_not_called()

    def test_drag_end_below_the_movement_threshold_does_nothing(self):
        table = self.make_table()
        table._dragged_column = "Title"
        table._drag_start_x = 50

        result = table._column_drag_end(self.event(53))

        self.assertIsNone(result)
        self.assertEqual(table.layout_state()["column_order"], self.COLUMNS)
        table._save_settings.assert_not_called()

    def test_drag_end_on_the_same_column_does_nothing(self):
        table = self.make_table()
        table._dragged_column = "Title"
        table._drag_start_x = 50

        result = table._column_drag_end(self.event(55))

        self.assertIsNone(result)
        self.assertEqual(table.layout_state()["column_order"], self.COLUMNS)
        table._save_settings.assert_not_called()

    def test_drag_end_on_no_column_does_nothing(self):
        table = self.make_table()
        table._dragged_column = "Title"
        table._drag_start_x = 50
        table.tree.identify_column.side_effect = None
        table.tree.identify_column.return_value = "#9"

        result = table._column_drag_end(self.event(250))

        self.assertIsNone(result)
        self.assertEqual(table.layout_state()["column_order"], self.COLUMNS)
        table._save_settings.assert_not_called()

    def test_drag_right_past_the_midpoint_moves_the_column_after_its_target(self):
        table = self.make_table()
        table._dragged_column = "Title"
        table._drag_start_x = 50

        result = table._column_drag_end(self.event(250))

        self.assertEqual(result, "break")
        self.assertEqual(table.layout_state()["column_order"], ["Artist", "Pack", "Title"])
        table.tree.configure.assert_called_once_with(
            displaycolumns=["Artist", "Pack", "Title"])
        table._save_settings.assert_called_once()

    def test_drag_right_before_the_midpoint_moves_the_column_before_its_target(self):
        table = self.make_table()
        table._dragged_column = "Title"
        table._drag_start_x = 50

        result = table._column_drag_end(self.event(210))

        self.assertEqual(result, "break")
        self.assertEqual(table.layout_state()["column_order"], ["Artist", "Title", "Pack"])
        table.tree.configure.assert_called_once_with(
            displaycolumns=["Artist", "Title", "Pack"])
        table._save_settings.assert_called_once()

    def test_drag_left_moves_the_column_before_its_target(self):
        table = self.make_table()
        table._dragged_column = "Pack"
        table._drag_start_x = 250

        result = table._column_drag_end(self.event(50))

        self.assertEqual(result, "break")
        self.assertEqual(table.layout_state()["column_order"], ["Title", "Pack", "Artist"])
        table.tree.configure.assert_called_once_with(
            displaycolumns=["Title", "Pack", "Artist"])
        table._save_settings.assert_called_once()


class RowTintTests(unittest.TestCase):
    # The tag rule, the tag setup, and the selection bookkeeping themselves are
    # tested in test_row_tints.py; this class keeps the table-side wiring honest.
    def test_insert_batch_tags_rows_by_difficulty_and_selection(self):
        rows = [
            {"Title": "Song A", "Difficulty": "Challenge", "Time": 120},
            {"Title": "Song B", "Difficulty": "Hard", "Time": 90},
            {"Title": "Song C", "Difficulty": "CustomUnknown", "Time": 60},
        ]
        table, tree = make_table(rows=rows)
        tree.insert.side_effect = ["item0", "item1", "item2"]
        table._render_generation = 1
        # Song B is pre-selected
        table._insert_batch(rows, 0, 1, selected_rows={id(rows[1])})

        self.assertEqual(tree.insert.call_count, 3)
        # Song A: unselected Challenge
        args0, kwargs0 = tree.insert.call_args_list[0]
        self.assertEqual(kwargs0.get("tags"), ("diff_Challenge",))
        # Song B: selected Hard has selected_row tag
        args1, kwargs1 = tree.insert.call_args_list[1]
        self.assertEqual(kwargs1.get("tags"), ("diff_Hard", "selected_row"))
        # Song C: a difficulty name that is not in the theme gets the gray unknown tag
        args2, kwargs2 = tree.insert.call_args_list[2]
        self.assertEqual(kwargs2.get("tags"), (row_tints.UNKNOWN_DIFFICULTY_TAG,))
        # Only the pre-selected row is remembered as selected
        self.assertEqual(table._tree_tint.items, {"item1"})
        tree.selection_add.assert_called_once_with("item1")


class SelectedRowsForCourseTests(unittest.TestCase):
    def test_selected_rows_for_course_returns_rows_in_selection_order_and_skips_unknown_ids(self):
        # The one seam between the table and the course builder: the dialog's queue is
        # fed from here, so a break here would open the dialog empty.
        rows = {"item1": {"Title": "A"}, "item2": {"Title": "B"}}
        table, tree = make_table()
        tree.selection.return_value = ["item2", "gone", "item1"]
        table._tree_item_rows = rows

        self.assertEqual(table.selected_rows(), [rows["item2"], rows["item1"]])


class LibraryRowsForCourseTests(unittest.TestCase):
    def test_library_rows_for_course_returns_the_loaded_rows(self):
        # The course builder's save-time ambiguity check compares its queue against
        # this list, so it must be the app's current rows, not a snapshot copy.
        # The table reads them through the filter (option C, PR #168 review):
        # the filter is the single holder, so the table's rows are the
        # filter's rows.
        rows = [{"Title": "A"}, {"Title": "B"}]
        table, _tree = make_table()
        table._filter.set_rows(rows)

        self.assertIs(table.library_rows(), rows)


class InsertBatchProgressTests(unittest.TestCase):
    """_insert_batch fills the table in time-boxed batches, and the count
    label tells the truth while it does (startup polish)."""

    @staticmethod
    def make_instance(row_count=3):
        rows = [{"Title": f"Song {i}", "Difficulty": "Hard", "Time": 60} for i in range(row_count)]
        table, tree = make_table(rows=rows)
        tree.insert.side_effect = [f"item{i}" for i in range(row_count)]
        table._render_generation = 1
        return table, rows

    def test_a_zero_budget_inserts_one_row_and_reports_progress(self):
        table, rows = self.make_instance()
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 0):
            table._insert_batch(rows, 0, 1)
        self.assertEqual(table.tree.insert.call_count, 1)
        table.count_label.set.assert_called_once_with("Loading 1 of 3 charts…")
        table._parent.after.assert_called_once()
        # The scheduled continuation finishes the job and sets the final totals.
        continuation = table._parent.after.call_args.args[1]
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            continuation()
        self.assertEqual(table.tree.insert.call_count, 3)
        table.count_label.set.assert_called_with("3 charts shown · 3 total")

    def test_a_generous_budget_inserts_everything_in_one_batch(self):
        table, rows = self.make_instance()
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._insert_batch(rows, 0, 1)
        self.assertEqual(table.tree.insert.call_count, 3)
        table.count_label.set.assert_called_once_with("3 charts shown · 3 total")
        table._parent.after.assert_not_called()

    def test_non_finite_time_values_insert_as_blank_instead_of_crashing(self):
        # Issue #123: a snapshot row whose Time is "nan" or "1e999" used to
        # raise inside _insert_batch; now the cell is blank and the batch lands.
        table, _rows = self.make_instance()
        rows = [
            {"Title": "Song A", "Difficulty": "Hard", "Time": "nan"},
            {"Title": "Song B", "Difficulty": "Hard", "Time": "1e999"},
            {"Title": "Song C", "Difficulty": "Hard", "Time": 120},
        ]
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._insert_batch(rows, 0, 1)
        self.assertEqual(table.tree.insert.call_count, 3)
        time_index = list(app.HEADERS).index("Time")
        inserted = [kwargs["values"][time_index]
                    for _args, kwargs in table.tree.insert.call_args_list]
        self.assertEqual(inserted, ["", "", "2:00"])

    def test_count_line_names_an_unreadable_filter_value(self):
        table, rows = self.make_instance()
        table._filter.search_var.set("meter:abc")
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._insert_batch(rows, 0, 1)
        table.count_label.set.assert_called_once_with(
            "3 charts shown · 3 total — Can't read the value in meter:abc")

    def test_count_line_names_an_unreadable_grade_value(self):
        table, rows = self.make_instance()
        table._filter.search_var.set("grade:banana")
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._insert_batch(rows, 0, 1)
        table.count_label.set.assert_called_once_with(
            "3 charts shown · 3 total — Can't read the value in grade:banana")

    def test_count_line_stays_plain_for_a_readable_filter(self):
        table, rows = self.make_instance()
        table._filter.search_var.set("meter:11")
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._insert_batch(rows, 0, 1)
        table.count_label.set.assert_called_once_with("3 charts shown · 3 total")


class RefreshDeliversRowsTests(unittest.TestCase):
    """refresh_table delivers the filtered rows to the table and the panel:
    the wiring a load (and later set_rows) must preserve, so a forgotten
    refresh leaves the table visibly empty instead of silently stale."""

    @staticmethod
    def make_table():
        rows = [
            {"Title": "Song A", "Pack": "Pack1", "Type": "dance-single",
             "Difficulty": "Hard", "Grade": "AAA", "Meter": 10, "Time": 60},
            {"Title": "Song B", "Pack": "Pack2", "Type": "dance-double",
             "Difficulty": "Challenge", "Grade": "", "Meter": 12,
             "Time": 90},
        ]
        show_rows = Mock()
        table, tree = make_table(rows=rows, show_rows=show_rows)
        tree.insert.side_effect = ["item0", "item1"]
        return table, tree, rows, show_rows

    def test_refresh_table_inserts_the_rows_and_pushes_them_to_the_panel(self):
        table, tree, rows, show_rows = self.make_table()
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()

        self.assertEqual(tree.insert.call_count, 2)
        title_index = list(app.HEADERS).index("Title")
        inserted = [kwargs["values"][title_index]
                    for _args, kwargs in tree.insert.call_args_list]
        self.assertEqual(inserted, ["Song A", "Song B"])
        show_rows.assert_called_once_with(rows)
        table.count_label.set.assert_called_once_with(
            "2 charts shown · 2 total")


class RebindingHazardTests(unittest.TestCase):
    """The sort/column rebinding hazard (proposal 0009, Claude's review):
    sort_by rebinds self._sort_keys and reset_column_layout rebinds
    self._column_order, so the state _save_settings persists must be the
    table's own state after the gesture — a shared-input design would go
    stale here. These pins say what reaches disk."""

    @staticmethod
    def make_save_table(settings_path):
        """A bare app whose _save_settings reads a real table's layout_state."""
        instance = object.__new__(app.LibraryApp)
        instance.settings_path = settings_path
        instance.cache_var = Mock(get=Mock(return_value="/cache"))
        instance.stats_var = Mock(get=Mock(return_value="/stats.xml"))
        instance.column_visibility = {
            col: Mock(get=Mock(return_value=True)) for col in app.HEADERS}
        instance.show_distribution_panel = Mock(
            get=Mock(return_value=False))
        instance.distribution_metric = Mock(get=Mock(return_value="Meter"))
        instance.pack_var = Mock(get=Mock(return_value="All packs"))
        instance.type_var = Mock(get=Mock(return_value="All types"))
        instance.diff_var = Mock(get=Mock(return_value="All difficulties"))
        instance.course_geometry = None
        instance.advanced_search_geometry = None
        instance.song_page_geometry = None
        instance._settings_store = SettingsStore(settings_path)
        instance._settings_store.load()
        instance.status = Mock()
        group_visibility = {group: FakeVariable()
                            for group in app.COLUMN_GROUPS}
        table, _tree = make_table(
            column_visibility=instance.column_visibility,
            group_visibility=group_visibility,
            save_settings=instance._save_settings)
        instance._table = table
        return instance, table

    @staticmethod
    def saved(settings_path):
        return json.loads(settings_path.read_text(encoding="utf-8"))

    def test_sort_by_a_new_column_persists_the_new_sort(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            instance, table = self.make_save_table(settings_path)
            table.refresh_table = Mock()

            table.sort_by("Title")

            table.refresh_table.assert_called_once_with(
                preserve_selection=True, changed_keys=set())
            self.assertEqual(self.saved(settings_path)["sort_keys"],
                             [["Title", False]])

    def test_sort_by_the_current_first_column_toggles_and_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            instance, table = self.make_save_table(settings_path)
            table._sort_keys = [("Title", False)]
            table.refresh_table = Mock()

            table.sort_by("Title")

            self.assertEqual(self.saved(settings_path)["sort_keys"],
                             [["Title", True]])

    def test_reset_column_layout_persists_the_restored_order(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            instance, table = self.make_save_table(settings_path)
            table._column_order = list(reversed(app.HEADERS))

            table.reset_column_layout()

            self.assertEqual(self.saved(settings_path)["column_order"],
                             list(app.HEADERS))


class TableWiringGuardTests(unittest.TestCase):
    """The Step 6 wiring guard: a load (the filter's set_rows inside a
    batch) refreshes exactly once, at the batch exit; the sort clicks
    and the column drag land on the table; and refresh_table reaches
    the panel's show_rows with the filtered rows. The layout_state pin
    lives in RebindingHazardTests; the unfiltered show_rows pin lives
    in RefreshDeliversRowsTests."""

    def test_a_load_refreshes_exactly_once_at_the_batch_exit(self):
        # Option C (PR #168 review): there is no table set_rows any more —
        # the load hands the rows to the filter inside its batch, and the
        # batch exit is the one refresh for the whole load.
        rows = rows_for(("Pack1", "dance-single", "Hard"))
        show_rows = Mock()
        table, tree = make_table(rows=rows, show_rows=show_rows)
        tree.reset_mock()
        show_rows.reset_mock()

        with table._filter.batch():
            table._filter.set_rows(rows)
            # No refresh while the batch is open.
            show_rows.assert_not_called()

        # The batch exit refreshes once for the whole load.
        show_rows.assert_called_once_with(rows)
        self.assertEqual(tree.insert.call_count, 1)

    def test_heading_commands_sort_via_the_table(self):
        table, tree = make_table()
        # The Title heading was built with a command; the sort-heading
        # rewrite that follows has none, so take the one with a command.
        title_command = None
        for call in tree.heading.call_args_list:
            args, kwargs = call
            if args and args[0] == "Title" and kwargs.get("command") is not None:
                title_command = kwargs["command"]
        self.assertIsNotNone(title_command)
        table.refresh_table = Mock()

        title_command()

        self.assertEqual(table.layout_state()["sort_keys"], [["Title", False]])
        table.refresh_table.assert_called_once_with(
            preserve_selection=True, changed_keys=set())

    def test_tree_bindings_land_on_the_table(self):
        table, tree = make_table()
        bound = {}
        for call in tree.bind.call_args_list:
            args, _kwargs = call
            bound.setdefault(args[0], []).append(args[1])
        # The drag, the shift-click sort, the save-on-release, and Ctrl+A
        # are the table's own methods (bound-method equality compares
        # __func__ and __self__, so this is an identity check).
        self.assertIn(table._column_drag_start, bound["<ButtonPress-1>"])
        self.assertIn(table._column_drag_end, bound["<ButtonRelease-1>"])
        self.assertIn(table._shift_sort_click, bound["<ButtonRelease-1>"])
        self.assertIn(table._save_settings, bound["<ButtonRelease-1>"])
        self.assertIn(table._select_all_rows, bound["<Control-a>"])
        self.assertIn(table._select_all_rows, bound["<Control-A>"])
        self.assertIn(table._tree_tint.on_select, bound["<<TreeviewSelect>>"])

    def test_refresh_table_pushes_the_filtered_rows_to_the_panel(self):
        rows = rows_for(("Pack1", "dance-single", "Hard"),
                        ("Pack2", "dance-single", "Hard"))
        show_rows = Mock()
        table, tree = make_table(rows=rows, show_rows=show_rows)
        table._filter.pack_var.set("Pack2")
        # The pack pick refreshes through the subscription; reset the
        # count so the explicit refresh below is the one pinned.
        show_rows.reset_mock()
        tree.reset_mock()
        tree.selection.return_value = ()
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()
        show_rows.assert_called_once_with([rows[1]])
        # Nothing changed since the pack pick's refresh, so the diff
        # inserts and deletes nothing (Proposal 0019): the panel still
        # gets its push, but the tree is left alone.
        tree.insert.assert_not_called()
        tree.delete.assert_not_called()


class LayoutStateTests(unittest.TestCase):
    """layout_state() reports the table's own sort/column state in
    canonical 100% units, which is what _save_settings persists."""

    def test_layout_state_reports_widths_in_canonical_units(self):
        # Issue #51: the table reads physical pixels back from the tree;
        # at 150% a 195 px column is stored as 130, so it comes back the
        # same at any scale.
        table, tree = make_table(dpi_scale=1.5)
        tree.column.return_value = 195
        state = table.layout_state()
        self.assertTrue(state["column_widths"])
        self.assertEqual(set(state["column_widths"].values()), {130})
        self.assertEqual(state["column_order"], list(app.HEADERS))
        self.assertEqual(state["sort_keys"], [["Pack", False]])

    def test_layout_state_reports_the_rebound_state_after_a_sort(self):
        # The rebinding hazard's other half: layout_state reads the
        # table's own sort_keys after sort_by rebinds them, not a copy
        # taken at construction.
        table, _tree = make_table()
        table.refresh_table = Mock()
        table.sort_by("Title")
        self.assertEqual(table.layout_state()["sort_keys"],
                         [["Title", False]])


class SavedLayoutSeedTests(unittest.TestCase):
    """The saved-layout seed (_parse_seed) through the table's constructor
    (GLM, PR #168 review): the sort keys and widths had no headless pin,
    so a seed parser that ignored them would stay green."""

    def test_valid_sort_keys_round_trip_through_the_seed(self):
        table, _tree = make_table(
            sort_keys=[["Title", True], ["Meter", False]])
        self.assertEqual(table.layout_state()["sort_keys"],
                         [["Title", True], ["Meter", False]])

    def test_invalid_and_duplicate_sort_keys_are_dropped(self):
        table, _tree = make_table(sort_keys=[
            ["Bogus", True], ["Title", "yes"], ["Title", False],
            ["Title", True], ["Meter", False]])
        self.assertEqual(table.layout_state()["sort_keys"],
                         [["Title", False], ["Meter", False]])

    def test_no_valid_sort_key_falls_back_to_the_default(self):
        table, _tree = make_table(
            sort_keys=[["Bogus", True], ["Title", "yes"]])
        self.assertEqual(table.layout_state()["sort_keys"], [["Pack", False]])

    def test_saved_widths_apply_and_unknown_columns_are_ignored(self):
        table, _tree = make_table(
            column_widths={"Title": 999, "Bogus": 50})
        self.assertEqual(table._column_widths["Title"], 999)
        self.assertNotIn("Bogus", table._column_widths)

    def test_non_list_seed_values_fall_back_to_defaults(self):
        table, _tree = make_table(column_order="x", column_widths=[],
                                  sort_keys="x")
        self.assertEqual(table.layout_state()["column_order"], list(app.HEADERS))
        self.assertEqual(table.layout_state()["sort_keys"], [["Pack", False]])
        self.assertIsNone(table._column_widths["Title"])


class ShiftSortClickTests(unittest.TestCase):
    """_shift_sort_click adds a second sort key on Shift-click (ChatGPT-6,
    PR #168 review): the bindings guard only pins that the handler is
    bound, not what it does."""

    COLUMNS = ["Title", "Artist", "Pack"]

    @staticmethod
    def make_table():
        table, tree = make_table(
            column_order=list(ShiftSortClickTests.COLUMNS))
        table._column_order = list(ShiftSortClickTests.COLUMNS)
        tree.identify_region.return_value = "heading"
        tree.identify_column.side_effect = (
            lambda x: "#1" if x < 100 else ("#2" if x < 200 else "#3"))
        tree.winfo_width.return_value = 300
        tree.reset_mock()
        return table

    @staticmethod
    def event(x, shift=True):
        event = Mock()
        event.x = x
        event.y = 10
        event.state = 0x0001 if shift else 0
        return event

    def test_shift_click_adds_a_second_sort_key(self):
        table = self.make_table()
        table.refresh_table = Mock()

        table._shift_sort_click(self.event(150))

        self.assertEqual(table.layout_state()["sort_keys"],
                         [["Pack", False], ["Artist", False]])
        table._save_settings.assert_called_once()

    def test_shift_click_on_an_existing_key_toggles_its_direction(self):
        table = self.make_table()
        table.refresh_table = Mock()
        table._shift_sort_click(self.event(150))

        table._shift_sort_click(self.event(150))

        self.assertEqual(table.layout_state()["sort_keys"],
                         [["Pack", False], ["Artist", True]])

    def test_a_click_without_shift_does_nothing(self):
        table = self.make_table()
        table.refresh_table = Mock()

        table._shift_sort_click(self.event(150, shift=False))

        self.assertEqual(table.layout_state()["sort_keys"], [["Pack", False]])
        table.refresh_table.assert_not_called()


class DiffUnchangedTests(unittest.TestCase):
    """A refresh whose rows are unchanged inserts and deletes nothing
    (Proposal 0019, §6)."""

    @staticmethod
    def make_loaded_table(rows):
        table, tree = make_diff_table(rows=rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()
        return table, tree

    def test_unchanged_refresh_keeps_the_same_items_in_the_same_order(self):
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""))
        table, tree = self.make_loaded_table(rows)
        before = list(tree._order)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()

        self.assertEqual(tree._order, before)
        self.assertEqual(tree.shown_rows(table), rows)
        table.count_label.set.assert_called_with("2 charts shown · 2 total")

    def test_unchanged_refresh_with_fresh_dicts_keeps_the_items(self):
        # A load brings fresh row dicts with the same keys: the diff
        # matches by key, so the items survive even though id(row) changed.
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""))
        table, tree = self.make_loaded_table(rows)
        before = list(tree._order)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.set_rows([dict(row) for row in rows])

        self.assertEqual(tree._order, before)
        self.assertEqual(tree.shown_rows(table),
                         table._filter.library_rows())

    def test_unchanged_refresh_with_zero_budget_shows_no_loading_text(self):
        # The owner's smoke check: a reload with nothing to insert or
        # move flickered the count label through "Loading …"
        # intermediates. The walk still visits every position, but the
        # label stays on the settled count.
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""))
        table, tree = self.make_loaded_table(rows)
        table.count_label.set.reset_mock()

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 0):
            table.refresh_table()
        continuation = table._parent.after.call_args.args[1]
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            continuation()

        shown = [c.args[0] for c in table.count_label.set.call_args_list]
        self.assertTrue(all(not text.startswith("Loading") for text in shown),
                        shown)
        self.assertEqual(shown[-1], "2 charts shown · 2 total")


class DiffChangeTests(unittest.TestCase):
    """A changed row updates in place, a new row inserts at its sorted
    position, and a deleted row is removed (Proposal 0019, §6)."""

    def test_changed_row_updates_in_place_without_a_new_item(self):
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""))
        table, tree = make_diff_table(rows=rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()
        before = list(tree._order)
        rows[0]["Grade"] = "AAA"

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()

        self.assertEqual(tree._order, before)
        grade_index = list(app.HEADERS).index("Grade")
        self.assertEqual(tree._items[before[0]]["values"][grade_index],
                         "AAA")

    def test_new_row_inserts_at_its_sorted_position(self):
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("C/3", "dance-single", "Hard", ""))
        table, tree = make_diff_table(rows=rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()
        before = list(tree._order)
        new_rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                             ("B/2", "dance-single", "Hard", ""),
                             ("C/3", "dance-single", "Hard", ""))

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.set_rows(new_rows)

        self.assertEqual(tree.shown_rows(table), new_rows)
        self.assertEqual(tree._order[0], before[0])
        self.assertEqual(tree._order[2], before[1])
        self.assertEqual(len(tree._items), 3)

    def test_deleted_row_is_removed_and_survivors_keep_their_items(self):
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""),
                         ("C/3", "dance-single", "Hard", ""))
        table, tree = make_diff_table(rows=rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()
        before = list(tree._order)
        new_rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                             ("C/3", "dance-single", "Hard", ""))

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.set_rows(new_rows)

        self.assertEqual(tree.shown_rows(table), new_rows)
        self.assertEqual(tree._order, [before[0], before[2]])
        self.assertEqual(len(tree._items), 2)

    def test_second_unchanged_refresh_rewrites_nothing(self):
        # The saved display tuple is what keeps a later refresh from
        # rewriting an item it already rewrote: without the save, every
        # refresh would rewrite every changed row again.
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""))
        table, tree = make_diff_table(rows=rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()
        rows[0]["Grade"] = "AAA"
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()
        rewrites = []
        original_item = tree.item

        def counting_item(item, option=None, **kwargs):
            if kwargs:
                rewrites.append(item)
            return original_item(item, option, **kwargs)

        tree.item = counting_item

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()

        self.assertEqual(rewrites, [])

    def test_colliding_key_reinserts_the_song_as_a_block(self):
        # Two Edit charts of one song share one key (same description):
        # the diff never guesses which is which — both rows are deleted
        # and re-inserted, and the other song's item survives.
        rows = diff_rows(("A/1", "dance-single", "Edit", "My edit"),
                         ("A/1", "dance-single", "Edit", "My edit"),
                         ("B/2", "dance-single", "Hard", ""))
        table, tree = make_diff_table(rows=rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()
        before = list(tree._order)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()

        self.assertEqual(tree._order[2], before[2])
        self.assertNotEqual(tree._order[0], before[0])
        self.assertNotEqual(tree._order[1], before[1])
        self.assertEqual(tree.shown_rows(table), rows)

    def test_edits_with_different_descriptions_are_distinct_rows(self):
        # The Chart component of the key is what keeps two Edits of one
        # song apart: an unchanged refresh leaves both items alone.
        rows = diff_rows(("A/1", "dance-single", "Edit", "First"),
                         ("A/1", "dance-single", "Edit", "Second"),
                         ("B/2", "dance-single", "Hard", ""))
        table, tree = make_diff_table(rows=rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()
        before = list(tree._order)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()

        self.assertEqual(tree._order, before)
        self.assertEqual(tree.shown_rows(table), rows)

    def test_tree_side_collision_reinserts_even_when_visible_does_not_collide(self):
        # GLM pin-hole 1: the tree holds a colliding key from the
        # previous refresh, but the new visible set does not collide —
        # one Edit left the library. The tree-side collision is still
        # detected, and the song's rows are re-inserted as a block.
        rows = diff_rows(("A/1", "dance-single", "Edit", "My edit"),
                         ("A/1", "dance-single", "Edit", "My edit"),
                         ("B/2", "dance-single", "Hard", ""))
        table, tree = make_diff_table(rows=rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()
        before = list(tree._order)
        new_rows = diff_rows(("A/1", "dance-single", "Edit", "My edit"),
                             ("B/2", "dance-single", "Hard", ""))

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.set_rows(new_rows)

        self.assertEqual(tree._order[1], before[2])
        self.assertNotIn(tree._order[0], before)
        self.assertEqual(tree.shown_rows(table), new_rows)
        self.assertEqual(len(tree._items), 2)


class DiffSortTests(unittest.TestCase):
    """A re-sort moves rows without re-inserting them (Proposal 0019, §6,
    subject to Q2)."""

    def test_resort_moves_rows_without_reinserting(self):
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""),
                         ("C/3", "dance-single", "Hard", ""))
        table, tree = make_diff_table(rows=rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()
        before = list(tree._order)
        self.assertEqual(tree.shown_rows(table), rows)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.sort_by("Pack")  # toggles Pack to descending

        self.assertEqual(set(tree._order), set(before))
        self.assertEqual(len(tree._items), 3)
        self.assertEqual(tree.shown_rows(table),
                         [rows[2], rows[1], rows[0]])
        table.count_label.set.assert_called_with("3 charts shown · 3 total")


class DiffSetChildrenTests(unittest.TestCase):
    """A large reorder goes through one set_children call, a small one
    through per-item moves (PR #271 Lane A, finding 2: per-item
    tree.index/tree.move is O(n^2))."""

    @staticmethod
    def make_loaded_table(rows):
        table, tree = make_diff_table(rows=rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()
        return table, tree

    @staticmethod
    def many_rows(count):
        return diff_rows(*[(f"P{i:02d}/1", "dance-single", "Hard", "")
                           for i in range(count)])

    def test_large_reorder_uses_one_set_children_call(self):
        rows = self.many_rows(60)
        table, tree = self.make_loaded_table(rows)
        before = list(tree._order)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.sort_by("Pack")  # toggles Pack to descending

        self.assertEqual(len(tree.set_children_calls), 1)
        self.assertEqual(tree.set_children_calls[0], tuple(tree._order))
        self.assertEqual(tree.move_calls, [])
        self.assertEqual(set(tree._order), set(before))
        self.assertEqual(tree.shown_rows(table), list(reversed(rows)))

    def test_small_reorder_uses_per_item_moves(self):
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""),
                         ("C/3", "dance-single", "Hard", ""))
        table, tree = self.make_loaded_table(rows)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.sort_by("Pack")  # toggles Pack to descending

        self.assertEqual(tree.set_children_calls, [])
        self.assertEqual(len(tree.move_calls), 2)
        self.assertEqual(tree.shown_rows(table),
                         [rows[2], rows[1], rows[0]])

    def test_large_reorder_keeps_values_tags_and_selection(self):
        rows = self.many_rows(60)
        table, tree = self.make_loaded_table(rows)
        kept = tree._order[10]
        tree.selection_add(kept)
        # The fake does not fire <<TreeviewSelect>>: drive the tint
        # handler the way the event would, so the tag is on the item
        # before the sort, as a real click would leave it.
        table._tree_tint.on_select()
        before_values = tree._items[kept]["values"]
        before_tags = tree._items[kept]["tags"]
        self.assertIn(row_tints.SELECTED_ROW_TAG, before_tags)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.sort_by("Pack")  # toggles Pack to descending

        self.assertEqual(tree.selection(), (kept,))
        self.assertEqual(tree._items[kept]["values"], before_values)
        self.assertEqual(tree._items[kept]["tags"], before_tags)
        self.assertEqual(tree.shown_rows(table), list(reversed(rows)))

    def test_large_reorder_with_a_new_row_inserts_and_reorders(self):
        rows = self.many_rows(60)
        table, tree = self.make_loaded_table(rows)
        new_rows = rows + diff_rows(("P29/2", "dance-single", "Hard", ""))
        expected = sorted(new_rows, key=lambda row: row["Pack"],
                          reverse=True)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.set_rows(new_rows)
            table.sort_by("Pack")  # toggles Pack to descending

        self.assertEqual(len(tree.set_children_calls), 1)
        self.assertEqual(len(tree._items), 61)
        self.assertEqual(tree.shown_rows(table), expected)


class DiffLargePlacementTests(unittest.TestCase):
    """A large placement — many inserts, no displaced survivor — goes
    through one set_children call with new rows appended at "end"
    (PR #271 Revision 2: the §6 widen inserts 31,591 rows while
    displacing no survivor, and insert-at-index is O(position) in Tk).
    A narrow rebuilds the order list in one pass instead of removing
    each deleted key from it (the §6 narrow spent 10 s on list.remove).
    """

    @staticmethod
    def make_loaded_table(rows):
        table, tree = make_diff_table(rows=rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()
        return table, tree

    @staticmethod
    def many_rows(count):
        return diff_rows(*[(f"P{i:02d}/1", "dance-single", "Hard", "")
                           for i in range(count)])

    def test_widen_uses_one_set_children_and_appends_inserts(self):
        rows = self.many_rows(70)
        table, tree = self.make_loaded_table(rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.set_rows(rows[:10])
        self.assertEqual(tree.shown_rows(table), rows[:10])
        sets_before = len(tree.set_children_calls)
        moves_before = len(tree.move_calls)
        inserts_before = len(tree.insert_calls)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.set_rows(rows)

        self.assertEqual(len(tree.set_children_calls), sets_before + 1)
        self.assertEqual(
            tree.set_children_calls[-1], tuple(tree._order))
        self.assertEqual(len(tree.move_calls), moves_before)
        widen_inserts = tree.insert_calls[inserts_before:]
        self.assertEqual(len(widen_inserts), 60)
        self.assertTrue(all(index == "end" for index in widen_inserts))
        self.assertEqual(tree.shown_rows(table), rows)
        self.assertEqual(table._tree_item_order,
                         [table_module._chart_key(row) for row in rows])

    def test_narrow_rebuilds_the_order_list(self):
        rows = self.many_rows(70)
        table, tree = self.make_loaded_table(rows)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.set_rows(rows[:10])

        self.assertEqual(tree.shown_rows(table), rows[:10])
        self.assertEqual(table._tree_item_order,
                         [table_module._chart_key(row)
                          for row in rows[:10]])
        self.assertEqual(len(table._tree_item_rows), 10)

    def test_small_widen_inserts_at_index_without_set_children(self):
        rows = self.many_rows(10)
        table, tree = self.make_loaded_table(rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.set_rows(rows[:9])
        self.assertEqual(tree.shown_rows(table), rows[:9])
        sets_before = len(tree.set_children_calls)
        inserts_before = len(tree.insert_calls)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.set_rows(rows)

        self.assertEqual(len(tree.set_children_calls), sets_before)
        widen_inserts = tree.insert_calls[inserts_before:]
        self.assertEqual(len(widen_inserts), 1)
        self.assertEqual(widen_inserts[0], 9)
        self.assertEqual(tree.shown_rows(table), rows)


class DiffKeyCacheTests(unittest.TestCase):
    """The chart key is built once per row dict per refresh (PR #271
    Revision 3: the §6 profile showed _chart_key called twelve times
    per row — 508,500 calls for 42,375 rows on a Title click, a fifth
    of the click). The tests count the tuple builds, not the _chart_key
    calls: the calls still happen (a dozen per row), but all after the
    first are cache hits."""

    @staticmethod
    def count_builds():
        calls = []
        real = table_module._chart_key_tuple

        def counting(row):
            calls.append(1)
            return real(row)

        return calls, counting

    def test_no_change_refresh_builds_each_key_once(self):
        rows = diff_rows(("P00/1", "dance-single", "Hard", ""),
                         ("P01/1", "dance-single", "Hard", ""),
                         ("P02/1", "dance-single", "Hard", ""),
                         ("P03/1", "dance-single", "Hard", ""),
                         ("P04/1", "dance-single", "Hard", ""))
        table, tree = make_diff_table(rows=rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()
        calls, counting = self.count_builds()
        with patch.object(table_module, "_chart_key_tuple", counting):
            with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
                table.refresh_table()
        # Without the cache the same refresh builds the tuple twelve
        # times per row (once per call site); with it, once per dict.
        self.assertEqual(len(calls), len(rows))

    def test_full_insert_builds_each_key_once(self):
        rows = diff_rows(("P00/1", "dance-single", "Hard", ""),
                         ("P01/1", "dance-single", "Hard", ""),
                         ("P02/1", "dance-single", "Hard", ""),
                         ("P03/1", "dance-single", "Hard", ""),
                         ("P04/1", "dance-single", "Hard", ""))
        table, tree = make_diff_table(rows=rows)
        calls, counting = self.count_builds()
        with patch.object(table_module, "_chart_key_tuple", counting):
            with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
                table.refresh_table()
        self.assertEqual(len(calls), len(rows))
        self.assertEqual(tree.shown_rows(table), rows)


class DiffSelectionTests(unittest.TestCase):
    """Selection is preserved by key across a diff (Proposal 0019, §6)."""

    @staticmethod
    def make_loaded_table(rows):
        table, tree = make_diff_table(rows=rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()
        return table, tree

    def test_selection_survives_a_diff_by_key(self):
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""))
        table, tree = self.make_loaded_table(rows)
        tree.selection_add(tree._order[0])

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table(preserve_selection=True)

        self.assertEqual(tree.selection(), (tree._order[0],))
        self.assertIn(row_tints.SELECTED_ROW_TAG,
                      tree._items[tree._order[0]]["tags"])
        self.assertEqual(table._tree_tint.items, {tree._order[0]})

    def test_selection_survives_fresh_row_dicts_by_key(self):
        # A load replaces the row dicts: the old id(row) carry would drop
        # the selection, but the key carry keeps it. The filter's rows are
        # swapped directly here so no refresh runs before the pinned one.
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""))
        table, tree = self.make_loaded_table(rows)
        tree.selection_add(tree._order[0])
        table._filter._rows = [dict(row) for row in rows]

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table(preserve_selection=True)

        self.assertEqual(tree.selection(), (tree._order[0],))

    def test_a_load_clears_the_selection(self):
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""))
        table, tree = self.make_loaded_table(rows)
        tree.selection_add(tree._order[0])

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()

        self.assertEqual(tree.selection(), ())
        self.assertNotIn(row_tints.SELECTED_ROW_TAG,
                         tree._items[tree._order[0]]["tags"])
        self.assertEqual(table._tree_tint.items, set())

    def test_selecting_one_duplicate_key_row_drops_it_on_a_sort(self):
        # Greptile P1 #2, PR #271 Lane B: two Edit charts of one song
        # share one key. Selecting just one of them and sorting must
        # not expand the selection to both rows — the block re-insert
        # destroys the selected item's identity, so the selection drops.
        rows = diff_rows(("A/1", "dance-single", "Edit", "My edit"),
                         ("A/1", "dance-single", "Edit", "My edit"),
                         ("B/2", "dance-single", "Hard", ""))
        table, tree = self.make_loaded_table(rows)
        tree.selection_add(tree._order[0])

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.sort_by("Pack")  # toggles Pack to descending

        self.assertEqual(tree.selection(), ())
        self.assertEqual(table._tree_tint.items, set())
        # Greptile P2 (retrigger): the tag must agree with the
        # selection — neither duplicate keeps the white tag.
        for item in tree._order:
            self.assertNotIn(row_tints.SELECTED_ROW_TAG,
                             tree._items[item]["tags"])
        # The sort itself still lands: B first, then the two Edits.
        self.assertEqual(tree.shown_rows(table),
                         [rows[2], rows[0], rows[1]])

    def test_selection_survives_a_fresh_insert(self):
        # GLM pin-hole 2: a new row inserts while another row is
        # selected — the selection stays on its item.
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("C/3", "dance-single", "Hard", ""))
        table, tree = self.make_loaded_table(rows)
        tree.selection_add(tree._order[0])
        new_rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                             ("B/2", "dance-single", "Hard", ""),
                             ("C/3", "dance-single", "Hard", ""))
        # Swap the filter's rows directly so no refresh runs before
        # the pinned one.
        table._filter._rows = new_rows

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table(preserve_selection=True)

        self.assertEqual(tree.selection(), (tree._order[0],))
        self.assertEqual(tree.shown_rows(table), new_rows)

    def test_empty_tree_with_preserved_selection_inserts_the_rows(self):
        # GLM pin-hole 3: the first refresh on an empty tree with
        # preserve_selection bridges by key back to the inserted rows.
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""))
        table, tree = make_diff_table(rows=rows)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table(preserve_selection=True)

        self.assertEqual(tree.shown_rows(table), rows)
        self.assertEqual(tree.selection(), ())
        table.count_label.set.assert_called_with("2 charts shown · 2 total")


class DiffTagTests(unittest.TestCase):
    """A refresh that clears the selection also clears the white
    selected-row tag (PR #271 Lane A, finding 1; issue #273). The saved
    display tuple does not know about the tag on_select writes directly
    onto the tree item, so without the forced rewrite an unchanged
    refresh would leave the row white."""

    @staticmethod
    def make_loaded_table(rows):
        table, tree = make_diff_table(rows=rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()
        return table, tree

    def test_refresh_without_preserved_selection_clears_the_white_tag(self):
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""))
        table, tree = self.make_loaded_table(rows)
        tree.selection_add(tree._order[0])
        # The fake does not fire <<TreeviewSelect>>, so drive the tint
        # handler the way the event would: the tag lands on the tree
        # item, and the tracker remembers it.
        table._tree_tint.on_select()
        self.assertIn(row_tints.SELECTED_ROW_TAG,
                      tree._items[tree._order[0]]["tags"])

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()

        self.assertEqual(tree.selection(), ())
        for item in tree._order:
            self.assertNotIn(row_tints.SELECTED_ROW_TAG,
                             tree._items[item]["tags"])
        self.assertEqual(table._tree_tint.items, set())

    def test_empty_set_refresh_clears_the_white_tag_after_deselect(self):
        # Lane D pin 1 (and Claude's Lane A finding 3): the forced
        # rewrite is what removes a stale white tag when nothing
        # changed. A row selected, then deselected without the event
        # firing, still carries the tag and the tracker still holds
        # it — an empty-set refresh must clear the tag, asserted by
        # the actual tags and not by a call count.
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""))
        table, tree = self.make_loaded_table(rows)
        tree.selection_add(tree._order[0])
        table._tree_tint.on_select()
        self.assertIn(row_tints.SELECTED_ROW_TAG,
                      tree._items[tree._order[0]]["tags"])
        # Deselect without the event firing: the tag stays on the item
        # and the tracker still holds it, as after a filter edit.
        tree.selection_remove(tree._order[0])

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table(preserve_selection=True,
                                changed_keys=set())

        self.assertNotIn(row_tints.SELECTED_ROW_TAG,
                         tree._items[tree._order[0]]["tags"])


class DiffFilterTests(unittest.TestCase):
    """A filter narrowing keeps the surviving items (Proposal 0019, §6)
    and detaches the hidden ones instead of deleting them (Proposal
    0021): the hidden rows stay owned and addressable, invisible."""

    def test_filter_narrowing_keeps_the_surviving_items(self):
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""),
                         ("C/3", "dance-single", "Hard", ""))
        table, tree = make_diff_table(rows=rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()
        before = list(tree._order)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.pack_var.set("B")

        self.assertEqual(tree.shown_rows(table), [rows[1]])
        self.assertEqual(tree._order, [before[1]])
        # The hidden rows are detached, not deleted: still owned, still
        # addressable by id, but out of the children list.
        self.assertEqual(len(tree._items), 3)
        self.assertEqual(table._tree_item_detached,
                         {before[0], before[2]})
        self.assertEqual(len(table._tree_item_rows), 3)
        table.count_label.set.assert_called_with("1 charts shown · 3 total")


class DiffSyncTests(unittest.TestCase):
    """A sync re-scores cells in place through the real sync path
    (Proposal 0019, §6): merge_scores mutates the shown rows in place,
    then _on_library_changed issues the preserve-selection refresh. The
    diff must detect the change from its saved display tuples, not from
    the row dicts — the old and new dicts are the same objects."""

    def test_sync_rescores_cells_in_place(self):
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""))
        table, tree = make_diff_table(rows=rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()
        before = list(tree._order)
        scores = {("a/1", "dance-single", "hard"): {
            "PercentDP": 0.95, "Grade": "Tier02", "Score": 1000000,
            "plays": 3, "last_played": "2026-01-01", "MaxCombo": 500}}
        merge_scores(rows, scores)
        instance = object.__new__(app.LibraryApp)
        instance._table = table
        instance._filter = table._filter
        instance.course_builder = None
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            instance._on_library_changed(rows, preserve_selection=True)

        # Same items, none re-inserted — but the first row's cells show
        # the new score.
        self.assertEqual(tree._order, before)
        grade_index = list(app.HEADERS).index("Grade")
        best_index = list(app.HEADERS).index("Best %")
        values = tree._items[before[0]]["values"]
        self.assertEqual(values[grade_index], "★★★")
        self.assertEqual(values[best_index], "95")
        self.assertEqual(tree._items[before[1]]["values"][grade_index], "")


class DiffChangedKeysTests(unittest.TestCase):
    """A refresh rebuilds display tuples only for rows the loader says
    changed (Proposal 0022, §6): the table trusts the changed-keys
    input instead of detecting changes itself by rebuilding every
    tuple. None means unknown (rebuild all); an empty set means
    nothing changed; a set rebuilds only its keys, plus the forced
    set (the #273 tag fix)."""

    @staticmethod
    def make_loaded_table(rows):
        table, tree = make_diff_table(rows=rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()
        return table, tree

    @staticmethod
    def _counting_display_tuple(calls):
        real = table_module._display_tuple

        def counting(row, selected=False):
            calls.append(1)
            return real(row, selected)

        return counting

    @staticmethod
    def _blank_score_fields(rows):
        """Give fixture rows the blank score fields a parse writes for
        an unscored chart: without them the merge counts the blanking
        itself as a change (a missing field reads as None, the blank
        writes "" — except Plays, which the merge always numbers to
        0.0)."""
        for row in rows:
            row.update({"Score": "", "Best %": "", "Plays": 0.0,
                        "Last played": "", "Max combo": ""})
            for field in TAP_FIELDS:
                row[field] = ""

    def test_none_rebuilds_all_tuples(self):
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""))
        table, tree = self.make_loaded_table(rows)
        calls = []
        with patch.object(table_module, "_display_tuple",
                         self._counting_display_tuple(calls)):
            with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
                table.refresh_table()
        self.assertEqual(len(calls), 2)

    def test_empty_set_rebuilds_no_tuples_except_forced(self):
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""))
        table, tree = self.make_loaded_table(rows)
        tree.selection_add(tree._order[0])
        calls = []
        with patch.object(table_module, "_display_tuple",
                         self._counting_display_tuple(calls)):
            with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
                table.refresh_table(preserve_selection=True,
                                    changed_keys=set())
        # Only the selected row — the forced rewrite — is rebuilt.
        self.assertEqual(len(calls), 1)
        self.assertEqual(table._tree_tint.items, {tree._order[0]})

    def test_set_with_one_key_rebuilds_only_that_row(self):
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""))
        table, tree = self.make_loaded_table(rows)
        # Both titles change in place, as a sync re-scores in place;
        # only the first row's key is reported changed.
        rows[0]["Title"] = "New A"
        rows[1]["Title"] = "New B"
        key = table_module._chart_key(rows[0])
        calls = []
        with patch.object(table_module, "_display_tuple",
                         self._counting_display_tuple(calls)):
            with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
                table.refresh_table(changed_keys={key})
        self.assertEqual(len(calls), 1)
        title_index = list(app.HEADERS).index("Title")
        self.assertEqual(
            tree._items[tree._order[0]]["values"][title_index], "New A")
        # The other row keeps its old cells: it was not reported.
        self.assertEqual(
            tree._items[tree._order[1]]["values"][title_index], "2")

    def test_sort_rebuilds_no_tuples(self):
        rows = diff_rows(("B/2", "dance-single", "Hard", ""),
                         ("A/1", "dance-single", "Hard", ""))
        table, tree = self.make_loaded_table(rows)
        # The table defaults to Pack ascending, so B loads after A.
        self.assertEqual(tree.shown_rows(table), [rows[1], rows[0]])
        before = list(tree._order)
        calls = []
        with patch.object(table_module, "_display_tuple",
                         self._counting_display_tuple(calls)):
            table.sort_by("Pack")  # toggles Pack to descending
        self.assertEqual(len(calls), 0)
        # The sort itself still lands: B first now.
        self.assertNotEqual(tree._order, before)
        self.assertEqual(tree.shown_rows(table), [rows[0], rows[1]])

    def test_sync_updates_only_the_changed_cells(self):
        # The changed set flows from merge_scores to the table through
        # the loader path (§6): only the changed row's tuple is rebuilt.
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""))
        self._blank_score_fields(rows)
        table, tree = self.make_loaded_table(rows)
        before = list(tree._order)
        scores = {("a/1", "dance-single", "hard"): {
            "PercentDP": 0.95, "Grade": "Tier02", "Score": 1000000,
            "plays": 3, "last_played": "2026-01-01", "MaxCombo": 500}}
        changed, changed_keys = merge_scores(rows, scores)
        self.assertEqual(changed, 1)
        self.assertEqual(changed_keys,
                         {table_module._chart_key(rows[0])})
        instance = object.__new__(app.LibraryApp)
        instance._table = table
        instance._filter = table._filter
        instance.course_builder = None
        calls = []
        with patch.object(table_module, "_display_tuple",
                         self._counting_display_tuple(calls)):
            with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
                instance._on_library_changed(
                    rows, preserve_selection=True, changed_keys=changed_keys)
        self.assertEqual(len(calls), 1)
        self.assertEqual(tree._order, before)
        grade_index = list(app.HEADERS).index("Grade")
        best_index = list(app.HEADERS).index("Best %")
        values = tree._items[before[0]]["values"]
        self.assertEqual(values[grade_index], "★★★")
        self.assertEqual(values[best_index], "95")
        self.assertEqual(tree._items[before[1]]["values"][grade_index], "")

    def test_two_changed_rows_sharing_a_key_count_two_with_a_one_key_set(self):
        # Greptile P2 on PR #275: two changed rows can share one chart
        # key, so the count is not len() of the set — and the set the
        # merge reports is the key the table's diff uses.
        rows = diff_rows(("A/1", "dance-single", "Edit", "My edit"),
                         ("A/1", "dance-single", "Edit", "My edit"),
                         ("B/2", "dance-single", "Hard", ""))
        self._blank_score_fields(rows)
        table, tree = self.make_loaded_table(rows)
        scores = {("a/1", "dance-single", "edit", "my edit"): {
            "PercentDP": 0.9, "Grade": "Tier03", "Score": 900000,
            "plays": 2, "last_played": "2026-01-02", "MaxCombo": 400}}
        changed, changed_keys = merge_scores(rows, scores)
        self.assertEqual(changed, 2)
        self.assertEqual(len(changed_keys), 1)
        self.assertEqual(changed_keys,
                         {table_module._chart_key(rows[0])})
        # Both cells update through the sync path: the colliding song
        # is re-inserted as a block, so both items take new tuples.
        instance = object.__new__(app.LibraryApp)
        instance._table = table
        instance._filter = table._filter
        instance.course_builder = None
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            instance._on_library_changed(
                rows, preserve_selection=True, changed_keys=changed_keys)
        best_index = list(app.HEADERS).index("Best %")
        bests = [tree._items[item]["values"][best_index]
                 for item in tree._order]
        self.assertEqual(bests.count("90"), 2)
        self.assertIn("", bests)

    def test_reload_through_the_subscription_rebuilds_changed_cells(self):
        # Greptile P1 on PR #275: a reload refreshes only through the
        # subscription, so the subscription must carry None (fresh
        # dicts, unchanged keys, new values) instead of the empty set.
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""))
        table, tree = self.make_loaded_table(rows)
        before = list(tree._order)
        new_rows = [dict(row) for row in rows]
        new_rows[0]["Title"] = "Renamed"
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.set_rows(new_rows)
        # Same items, none re-inserted — but the first row's cells show
        # the new title.
        self.assertEqual(tree._order, before)
        title_index = list(app.HEADERS).index("Title")
        self.assertEqual(
            tree._items[before[0]]["values"][title_index], "Renamed")
        self.assertEqual(
            tree._items[before[1]]["values"][title_index], "2")

    def test_filter_edit_through_the_subscription_rebuilds_nothing(self):
        # The other side of the subscription: a filter edit changes
        # visibility, not data, so no tuple is rebuilt — a title
        # mutated in place without the loader saying so stays hidden
        # until a refresh that reports it.
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""))
        table, tree = self.make_loaded_table(rows)
        rows[0]["Title"] = "Mutated"
        calls = []
        with patch.object(table_module, "_display_tuple",
                         self._counting_display_tuple(calls)):
            table._filter.pack_var.set("All packs")
        self.assertEqual(len(calls), 0)
        title_index = list(app.HEADERS).index("Title")
        self.assertEqual(
            tree._items[tree._order[0]]["values"][title_index], "1")


class DiffGenerationTests(unittest.TestCase):
    """A superseded generation inserts nothing, and a zero budget batches
    the diff the way _insert_batch batches a full insert (Proposal 0019,
    §6)."""

    @staticmethod
    def make_loaded_table(rows):
        table, tree = make_diff_table(rows=rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()
        return table, tree

    def test_superseded_batch_inserts_nothing(self):
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("C/3", "dance-single", "Hard", ""))
        table, tree = self.make_loaded_table(rows)
        new_rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                             ("B/2", "dance-single", "Hard", ""),
                             ("C/3", "dance-single", "Hard", ""))
        # A zero budget: the diff's first batch places one row and
        # schedules a continuation.
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 0):
            table._filter.set_rows(new_rows)
        continuation = table._parent.after.call_args.args[1]
        # A newer refresh supersedes it and finishes the diff itself.
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table.refresh_table()
        self.assertEqual(tree.shown_rows(table), new_rows)
        before = list(tree._order)

        continuation()

        self.assertEqual(tree._order, before)
        self.assertEqual(tree.shown_rows(table), new_rows)

    def test_zero_budget_batches_the_diff_and_the_continuation_finishes_it(self):
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("C/3", "dance-single", "Hard", ""))
        table, tree = self.make_loaded_table(rows)
        new_rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                             ("B/2", "dance-single", "Hard", ""),
                             ("C/3", "dance-single", "Hard", ""))
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 0):
            table._filter.set_rows(new_rows)
        table.count_label.set.assert_called_with("Loading 1 of 3 charts…")
        continuation = table._parent.after.call_args.args[1]

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            continuation()

        self.assertEqual(tree.shown_rows(table), new_rows)
        table.count_label.set.assert_called_with("3 charts shown · 3 total")

    def test_move_across_a_batch_boundary_finishes_the_reorder(self):
        # GLM pin-hole 4: a re-sort with a zero budget places one row
        # and schedules a continuation; the continuation finishes the
        # reorder without losing or duplicating a row.
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Hard", ""),
                         ("C/3", "dance-single", "Hard", ""))
        table, tree = self.make_loaded_table(rows)
        before = list(tree._order)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 0):
            table.sort_by("Pack")  # toggles Pack to descending
        continuation = table._parent.after.call_args.args[1]

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            continuation()

        self.assertEqual(set(tree._order), set(before))
        self.assertEqual(len(tree._items), 3)
        self.assertEqual(tree.shown_rows(table),
                         [rows[2], rows[1], rows[0]])
        table.count_label.set.assert_called_with("3 charts shown · 3 total")


class DiffEquivalenceTests(unittest.TestCase):
    """The tree contents after a diffed refresh equal the tree contents
    after a rebuild, row for row and in order (Proposal 0019, §6)."""

    def test_diffed_refresh_matches_a_rebuild_row_for_row(self):
        old_rows = diff_rows(
            ("A/1", "dance-single", "Hard", ""),
            ("A/1", "dance-single", "Challenge", ""),
            ("B/2", "dance-double", "Hard", ""),
            ("B/2", "dance-single", "Medium", ""),
            ("C/3", "dance-single", "Easy", ""),
            ("C/3", "dance-single", "Hard", ""))
        # One changed (a score lands), one new (sorts into the middle),
        # one deleted.
        new_rows = diff_rows(
            ("A/1", "dance-single", "Hard", ""),
            ("A/1", "dance-single", "Challenge", ""),
            ("B/2", "dance-double", "Hard", ""),
            ("B/2", "dance-single", "Hard", ""),
            ("B/2", "dance-single", "Medium", ""),
            ("C/3", "dance-single", "Easy", ""))
        new_rows[1]["Grade"] = "AAA"
        # The diffed table: load the old rows, then the new ones.
        table_a, tree_a = make_diff_table(rows=old_rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table_a.refresh_table()
            table_a._filter.set_rows(new_rows)
        # The rebuilt table: a fresh table on the new rows.
        table_b, tree_b = make_diff_table(rows=new_rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table_b.refresh_table()

        self.assertEqual(tree_a.shown_rows(table_a),
                         tree_b.shown_rows(table_b))
        self.assertEqual(tree_a.shown_values(), tree_b.shown_values())

def detach_spec_rows(count, easy_indices=()):
    """Chart rows P000.. in Pack order, Easy at the given indices and
    Hard elsewhere — a deterministic fixture for the detach tests,
    where the narrow is always to Easy. The packs are zero-padded to
    three digits so the Pack sort orders them numerically even past
    99 rows."""
    specs = []
    for i in range(count):
        difficulty = "Easy" if i in easy_indices else "Hard"
        specs.append((f"P{i:03d}/1", "dance-single", difficulty, ""))
    return diff_rows(*specs)


def load_detach_table(rows):
    """Load `rows` into a fresh diff table with a budget that runs the
    whole walk in one batch, so the table starts settled."""
    table, tree = make_diff_table(rows=rows)
    with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
        table.refresh_table()
    return table, tree


def assert_detach_invariants(test, table, tree):
    """The §4.1 invariants, after a refresh has settled: the owned
    maps agree, the detached set is a subset of the owned items, the
    tree's children are exactly the visible owned items, the order
    list holds the visible keys in tree order, and the selection and
    the tint agree on visible items only. Only valid on fixtures with
    no colliding songs, where one key maps to one item."""
    test.assertEqual(set(table._tree_item_rows),
                     set(table._tree_item_display))
    test.assertTrue(table._tree_item_detached
                    <= set(table._tree_item_rows))
    test.assertEqual(set(tree.get_children()),
                     set(table._tree_item_rows) - table._tree_item_detached)
    test.assertEqual(table._tree_item_order,
                     [table_module._chart_key(row)
                      for row in tree.shown_rows(table)])
    test.assertTrue(set(tree.selection()) <= set(tree.get_children()))
    test.assertEqual(table._tree_tint.items, set(tree.selection()))


class DetachFakeTests(unittest.TestCase):
    """The FakeTreeview models detach and reattach the way the real
    Treeview does (Proposal 0021, §6): detach removes the item from
    display but keeps it addressable, move reattaches it, and index()
    of a detached item is a misleading 0."""

    def test_detach_keeps_values_tags_and_addressability(self):
        tree = FakeTreeview()
        item = tree.insert("", "end", values=("a",), tags=("diff_Hard",))
        tree.detach(item)
        self.assertEqual(tree.get_children(), ())
        self.assertTrue(tree.exists(item))
        self.assertEqual(tree.item(item, "values"), ("a",))
        self.assertEqual(tree.item(item, "tags"), ("diff_Hard",))

    def test_detach_drops_the_item_from_the_selection(self):
        tree = FakeTreeview()
        item = tree.insert("", "end", values=("a",))
        tree.selection_add(item)
        tree.detach(item)
        self.assertEqual(tree.selection(), ())
        # The drop is permanent, not just hidden while detached:
        # reattaching the item must not bring the selection back.
        tree.move(item, "", 0)
        self.assertEqual(tree.selection(), ())

    def test_move_reattaches_a_detached_item(self):
        tree = FakeTreeview()
        first = tree.insert("", "end", values=("a",))
        second = tree.insert("", "end", values=("b",))
        tree.detach(first)
        tree.move(first, "", 0)
        self.assertEqual(tree.get_children(), (first, second))
        tree.detach(first)
        tree.move(first, "", "end")
        self.assertEqual(tree.get_children(), (second, first))

    def test_index_of_a_detached_item_is_zero(self):
        tree = FakeTreeview()
        first = tree.insert("", "end", values=("a",))
        middle = tree.insert("", "end", values=("b",))
        last = tree.insert("", "end", values=("c",))
        tree.detach(middle)
        self.assertEqual(tree.index(middle), 0)
        self.assertEqual(tree.index(last), 1)

    def test_set_children_reattaches_and_detaches(self):
        tree = FakeTreeview()
        first = tree.insert("", "end", values=("a",))
        second = tree.insert("", "end", values=("b",))
        tree.detach(first)
        tree.set_children("", second, first)
        self.assertEqual(tree.get_children(), (second, first))
        tree.set_children("", first)
        self.assertEqual(tree.get_children(), (first,))
        self.assertTrue(tree.exists(second))
        self.assertEqual(tree.index(second), 0)

    def test_set_children_omission_drops_selection_permanently(self):
        # CoPilot review, PR #283 Revision 1: omitting an item from
        # set_children detaches it in real Tk, and detachment drops
        # its selection — so a later set_children that reattaches it
        # must not bring the selection back.
        tree = FakeTreeview()
        first = tree.insert("", "end", values=("a",))
        second = tree.insert("", "end", values=("b",))
        tree.selection_add(second)
        tree.set_children("", first)
        self.assertEqual(tree.selection(), ())
        tree.set_children("", first, second)
        self.assertEqual(tree.selection(), ())

    def test_focus_setter_getter_and_delete_clearing(self):
        tree = FakeTreeview()
        first = tree.insert("", "end", values=("a",))
        second = tree.insert("", "end", values=("b",))
        self.assertEqual(tree.focus(), "")
        tree.focus(first)
        self.assertEqual(tree.focus(), first)
        tree.delete(first)
        self.assertEqual(tree.focus(), "")


class DetachDifferentialTests(unittest.TestCase):
    """A filter toggle round trip detaches and reattaches the same
    items (Proposal 0021, §6): same item ids, same order, same
    values and tags — no insert runs on the widen."""

    def test_filter_toggle_round_trip_keeps_identity_order_and_values(self):
        rows = detach_spec_rows(6, easy_indices={1, 3, 5})
        table, tree = load_detach_table(rows)
        before_items = list(tree._order)
        before_values = tree.shown_values()

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")
        self.assertEqual(tree.shown_rows(table),
                         [rows[1], rows[3], rows[5]])
        self.assertEqual(table._tree_item_detached,
                         {before_items[0], before_items[2],
                          before_items[4]})
        inserts = len(tree.insert_calls)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("All difficulties")

        self.assertEqual(tree._order, before_items)
        self.assertEqual(tree.shown_values(), before_values)
        self.assertEqual(table._tree_item_detached, set())
        self.assertEqual(len(tree.insert_calls), inserts)
        assert_detach_invariants(self, table, tree)

    def test_changed_filter_value_in_between(self):
        rows = detach_spec_rows(6, easy_indices={1, 3, 5})
        table, tree = load_detach_table(rows)
        before_items = list(tree._order)
        inserts = len(tree.insert_calls)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Hard")
        self.assertEqual(tree.shown_rows(table),
                         [rows[0], rows[2], rows[4]])
        self.assertEqual(table._tree_item_detached,
                         {before_items[1], before_items[3],
                          before_items[5]})
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("All difficulties")

        self.assertEqual(tree._order, before_items)
        self.assertEqual(table._tree_item_detached, set())
        self.assertEqual(len(tree.insert_calls), inserts)
        assert_detach_invariants(self, table, tree)


class DetachDeleteVsDetachTests(unittest.TestCase):
    """A load dropping a song deletes its items from every map, while
    a filter hiding the same song detaches them (Proposal 0021, §6):
    the hidden rows stay owned and reattachable."""

    def test_load_dropping_a_song_deletes_its_items_everywhere(self):
        rows = detach_spec_rows(3)
        table, tree = load_detach_table(rows)
        before = list(tree._order)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.set_rows(rows[:2])

        self.assertEqual(tree.shown_rows(table), rows[:2])
        self.assertEqual(tree._order, before[:2])
        self.assertNotIn(before[2], tree._items)
        self.assertNotIn(before[2], table._tree_item_rows)
        self.assertNotIn(before[2], table._tree_item_display)
        self.assertNotIn(before[2], table._tree_item_detached)
        assert_detach_invariants(self, table, tree)

    def test_filter_hiding_a_song_detaches_and_widen_reattaches(self):
        rows = detach_spec_rows(3, easy_indices={1})
        table, tree = load_detach_table(rows)
        before = list(tree._order)
        inserts = len(tree.insert_calls)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")
        self.assertEqual(tree.shown_rows(table), [rows[1]])
        self.assertIn(before[0], tree._items)
        self.assertIn(before[2], tree._items)
        self.assertEqual(table._tree_item_detached,
                         {before[0], before[2]})
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("All difficulties")

        self.assertEqual(tree._order, before)
        self.assertEqual(len(tree.insert_calls), inserts)
        assert_detach_invariants(self, table, tree)

    def test_true_deletion_removes_the_iid_from_every_structure(self):
        rows = detach_spec_rows(3, easy_indices={1})
        table, tree = load_detach_table(rows)
        before = list(tree._order)
        # Select the row that is about to be deleted, so its tint
        # entry is live too.
        tree.selection_add(before[2])
        table._tree_tint.note_selected(before[2])
        tree.focus(before[2])

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.set_rows(rows[:2])

        self.assertNotIn(before[2], tree._items)
        self.assertNotIn(before[2], table._tree_item_rows)
        self.assertNotIn(before[2], table._tree_item_display)
        self.assertNotIn(before[2], table._tree_item_detached)
        self.assertNotIn(before[2], tree.selection())
        self.assertNotIn(before[2], table._tree_tint.items)
        self.assertNotEqual(tree.focus(), before[2])
        assert_detach_invariants(self, table, tree)

class DetachSelectionTests(unittest.TestCase):
    """Selection and tint around detach (Proposal 0021, §6): a
    detached selected row leaves the selection and the tint, and
    returns unselected; a visible row keeps its selection across a
    preserve-selection refresh; a colliding song re-inserts fresh
    across the round trip."""

    def test_detached_selected_row_leaves_selection_and_tint(self):
        rows = detach_spec_rows(3, easy_indices={1})
        table, tree = load_detach_table(rows)
        before = list(tree._order)
        tree.selection_add(before[0])
        table._tree_tint.on_select()
        self.assertIn(row_tints.SELECTED_ROW_TAG,
                      tree.item(before[0], "tags"))

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")

        self.assertEqual(tree.selection(), ())
        self.assertEqual(table._tree_tint.items, set())
        # forget() takes the white tag off while the iid is still
        # addressable: the reset at the end of the refresh only
        # replaces the tracked set, it never touches a tag — so
        # without the forget the tag would survive on the detached
        # item and come back with it on the widen.
        self.assertNotIn(row_tints.SELECTED_ROW_TAG,
                         tree.item(before[0], "tags"))
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("All difficulties")

        # The same item id comes back, but unselected: the selection
        # was dropped at detach, not remembered — and the white tag
        # does not come back with it.
        self.assertEqual(tree._order, before)
        self.assertEqual(tree.selection(), ())
        self.assertEqual(table._tree_tint.items, set())
        self.assertNotIn(row_tints.SELECTED_ROW_TAG,
                         tree.item(before[0], "tags"))
        assert_detach_invariants(self, table, tree)

    def test_row_selected_mid_walk_comes_back_untagged(self):
        # PR #283 Revision 1 (Claude's fuzz finding, verified by
        # Muse): a row selected while a refresh walk is still running
        # is dropped from the tint tracking by the walk's final reset,
        # so by the time a later refresh detaches it, forget() used to
        # early-return and leave its white tag on — and the reattach's
        # compare-then-write saw no difference, so the row came back
        # white while unselected.
        rows = detach_spec_rows(60, easy_indices=set(range(50, 60)))
        table, tree = load_detach_table(rows)
        victim = next(item for item, row in table._tree_item_rows.items()
                      if row is rows[10])
        # Narrow to Hard with a zero budget: the walk places one item
        # and schedules a continuation — the walk is now in flight.
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 0):
            table._filter.diff_var.set("Hard")
        continuation = table._parent.after.call_args.args[1]
        # Select the victim mid-walk, the way a user click would (real
        # Tk fires <<TreeviewSelect>>; the fake has no event dispatch,
        # so drive on_select directly).
        tree.selection_add(victim)
        table._tree_tint.on_select()
        self.assertIn(row_tints.SELECTED_ROW_TAG,
                      tree.item(victim, "tags"))
        # Run the continuation: the walk finishes and resets the tint
        # tracking to the selection as it was when the refresh started,
        # so the tracker loses the victim while the tag stays.
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            continuation()
        self.assertNotIn(victim, table._tree_tint.items)
        self.assertIn(row_tints.SELECTED_ROW_TAG,
                      tree.item(victim, "tags"))
        # Narrow to Easy: the victim is detached. forget() must take
        # the tag off even though the tracker no longer knows it.
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")
        self.assertIn(victim, table._tree_item_detached)
        self.assertNotIn(row_tints.SELECTED_ROW_TAG,
                         tree.item(victim, "tags"))
        # Widen to All: the victim comes back unselected and untagged.
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("All difficulties")
        self.assertIn(victim, tree.get_children())
        self.assertNotIn(victim, tree.selection())
        self.assertNotIn(row_tints.SELECTED_ROW_TAG,
                         tree.item(victim, "tags"))
        assert_detach_invariants(self, table, tree)

    def test_visible_row_keeps_selection_across_a_sync(self):
        rows = detach_spec_rows(3, easy_indices={1})
        table, tree = load_detach_table(rows)
        before = list(tree._order)
        tree.selection_add(before[1])
        table._tree_tint.note_selected(before[1])

        instance = object.__new__(app.LibraryApp)
        instance._table = table
        instance._filter = table._filter
        instance.course_builder = None
        _, changed = merge_scores(
            rows, {(f"p{i:03d}/1", "dance-single", "hard"): {
                "Grade": "AAA", "Score": "9,876,543", "Best%": "99.00"}
                   for i in range(3)})
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            instance._on_library_changed(rows, preserve_selection=True,
                                         changed_keys=changed)

        self.assertEqual(tree.selection(), (before[1],))
        self.assertEqual(table._tree_tint.items, {before[1]})
        assert_detach_invariants(self, table, tree)

    def test_colliding_song_reinserts_fresh_across_the_round_trip(self):
        rows = diff_rows(("A/1", "dance-single", "Hard", ""),
                         ("A/1", "dance-single", "Hard", ""),
                         ("B/2", "dance-single", "Easy", ""))
        table, tree = load_detach_table(rows)
        before = list(tree._order)
        inserts = len(tree.insert_calls)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")
        # The colliding song's rows are gone from the tree entirely
        # (deleted as a block, D8), not detached — and the survivor
        # is visible, so nothing is detached at all.
        self.assertEqual(tree.shown_rows(table), [rows[2]])
        self.assertNotIn(before[0], tree._items)
        self.assertNotIn(before[1], tree._items)
        self.assertEqual(table._tree_item_detached, set())
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("All difficulties")

        # The colliding song comes back as fresh items; the survivor
        # keeps its item id.
        after = list(tree._order)
        self.assertNotEqual(after[0], before[0])
        self.assertNotEqual(after[1], before[1])
        self.assertEqual(after[2], before[2])
        self.assertEqual(len(tree.insert_calls), inserts + 2)
        assert_detach_invariants(self, table, tree)

    def test_narrow_splitting_duplicate_keys_deletes_the_block(self):
        # ChatGPT-6's detached-duplicate sequence (PR #283 review):
        # two rows share a chart key but differ in Meter, so a Meter
        # search shows one and hides the other. The tree-side
        # collision scan sees the key twice among attached items, so
        # the song collides and both rows are deleted as a block — the
        # hidden one is deleted, not detached, so no detached duplicate
        # survives for a later load to resurrect.
        rows = diff_rows(("A/1", "dance-single", "Edit", "Same"),
                         ("A/1", "dance-single", "Edit", "Same"),
                         ("B/2", "dance-single", "Hard", ""))
        rows[0]["Meter"] = 10
        rows[1]["Meter"] = 12
        table, tree = load_detach_table(rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.search_var.set("meter:10")
            table.refresh_table()
        self.assertEqual(tree.shown_rows(table), [rows[0], rows[2]])
        self.assertEqual(len(table._tree_item_rows), 2)
        self.assertEqual(len(tree.get_children()), 2)
        self.assertEqual(table._tree_item_detached, set())
        self.assertNotIn(rows[1], table._tree_item_rows.values())
        # A later load with only one of the two rows stays clean.
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.set_rows([dict(rows[0]), rows[2]])
        self.assertEqual([(r["Title"], r["Meter"])
                         for r in tree.shown_rows(table)],
                         [("1", 10), ("2", 10)])
        self.assertEqual(len(table._tree_item_rows), 2)
        self.assertEqual(table._tree_item_detached, set())
        assert_detach_invariants(self, table, tree)


class DetachFocusTests(unittest.TestCase):
    """Focus around detach (Proposal 0021, §6): detaching the
    focused row relocates focus and Enter opens nothing; the row is
    openable again once reattached."""

    def test_detaching_the_focused_row_relocates_focus(self):
        rows = detach_spec_rows(3, easy_indices={1})
        table, tree = load_detach_table(rows)
        before = list(tree._order)
        tree.focus(before[0])

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")
        # Focus moves to the first visible row, not to the detached
        # one — and Enter on that visible row opens it, which the
        # openable-again test below covers.
        self.assertNotEqual(tree.focus(), before[0])
        self.assertEqual(tree.focus(), before[1])

    def test_row_is_openable_again_once_reattached(self):
        rows = detach_spec_rows(3, easy_indices={1})
        table, tree = load_detach_table(rows)
        before = list(tree._order)
        tree.focus(before[0])

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("All difficulties")
        tree.focus(before[0])
        open_row = Mock()
        table._on_open_row = open_row
        table._invoke_open_row()
        open_row.assert_called_once_with(rows[0])

    def test_focus_on_a_detached_item_opens_nothing(self):
        rows = detach_spec_rows(3, easy_indices={1})
        table, tree = load_detach_table(rows)
        before = list(tree._order)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")
        # The focus gate: even if a stale focus lands on a detached
        # item, Enter must not open it.
        tree.focus(before[0])
        open_row = Mock()
        table._on_open_row = open_row
        table._invoke_open_row()
        open_row.assert_not_called()


class DetachOnlyDetachedTests(unittest.TestCase):
    """A filter hiding every row takes the diff path, not the full
    insert (Proposal 0021, §6): the detached set holds all owned
    items, and the widen reattaches the same ones."""

    def test_filter_hiding_every_row_detaches_all_of_them(self):
        rows = detach_spec_rows(4, easy_indices={0, 1})
        table, tree = load_detach_table(rows)
        before = list(tree._order)
        inserts = len(tree.insert_calls)
        tree.focus(before[0])

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Challenge")
        self.assertEqual(tree.shown_rows(table), [])
        self.assertEqual(tree.get_children(), ())
        self.assertEqual(table._tree_item_detached, set(before))
        self.assertEqual(len(table._tree_item_rows), 4)
        table.count_label.set.assert_called_with("0 charts shown · 4 total")
        # No visible row is left to focus, so focus is empty and
        # Enter opens nothing.
        self.assertEqual(tree.focus(), "")
        open_row = Mock()
        table._on_open_row = open_row
        table._invoke_open_row()
        open_row.assert_not_called()
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("All difficulties")

        self.assertEqual(tree._order, before)
        self.assertEqual(table._tree_item_detached, set())
        self.assertEqual(len(tree.insert_calls), inserts)
        assert_detach_invariants(self, table, tree)

class DetachSyncLoadTests(unittest.TestCase):
    """Scores change under detached rows (Proposal 0021, §6): a sync
    while rows are hidden shows the new scores on widen, and a load
    while rows are hidden reattaches the survivors with fresh row
    bindings while the gone songs are deleted."""

    def test_sync_while_detached_shows_new_scores_on_widen(self):
        rows = detach_spec_rows(4, easy_indices={2, 3})
        table, tree = load_detach_table(rows)
        before = list(tree._order)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")
        instance = object.__new__(app.LibraryApp)
        instance._table = table
        instance._filter = table._filter
        instance.course_builder = None
        _, changed = merge_scores(
            rows, {("p000/1", "dance-single", "hard"): {
                       "Grade": "AA", "Score": "5,555,555",
                       "Best%": "97.50"},
                   ("p002/1", "dance-single", "easy"): {
                       "Grade": "AAA", "Score": "9,999,999",
                       "Best%": "99.90"}})
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            instance._on_library_changed(rows, preserve_selection=True,
                                         changed_keys=changed)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("All difficulties")

        self.assertEqual(tree._order, before)
        shown = tree.shown_values()
        self.assertEqual(shown[0][HEADERS.index("Grade")],
                         "AA")
        self.assertEqual(shown[2][HEADERS.index("Grade")],
                         "AAA")
        assert_detach_invariants(self, table, tree)

    def test_load_while_detached_reattaches_survivors_with_fresh_bindings(self):
        rows = detach_spec_rows(4, easy_indices={2, 3})
        table, tree = load_detach_table(rows)
        before = list(tree._order)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")
        # A fresh load: P01 is gone, the survivors are fresh dicts
        # with a changed Meter on P00.
        fresh = [dict(rows[0], Meter=12), rows[2], rows[3]]
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.set_rows(fresh)

        # P01's item is deleted outright — it is not in the new
        # library. P00 stays detached (still hidden) but is rebound.
        self.assertNotIn(before[1], tree._items)
        self.assertNotIn(before[1], table._tree_item_rows)
        self.assertEqual(table._tree_item_rows[before[0]], fresh[0])
        self.assertIs(table._tree_item_rows[before[0]], fresh[0])
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("All difficulties")

        self.assertEqual(tree._order, [before[0], before[2], before[3]])
        self.assertIs(table._tree_item_rows[before[0]], fresh[0])
        shown = tree.shown_values()
        self.assertEqual(shown[0][HEADERS.index("Meter")], 12)
        assert_detach_invariants(self, table, tree)

    def test_reattach_writes_only_on_a_difference(self):
        rows = detach_spec_rows(3, easy_indices={1})
        table, tree = load_detach_table(rows)
        before = list(tree._order)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")
        writes = []
        real_item = tree.item

        def counting_item(item, option=None, **kwargs):
            if kwargs:
                writes.append(item)
            return real_item(item, option, **kwargs)

        with patch.object(tree, "item", counting_item), patch.object(
                table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("All difficulties")
        self.assertEqual(writes, [])

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")
        rows[0]["Grade"] = "AA"
        writes.clear()
        with patch.object(tree, "item", counting_item), patch.object(
                table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("All difficulties")
        self.assertEqual(writes, [before[0]])
        shown = tree.shown_values()
        self.assertEqual(shown[0][HEADERS.index("Grade")],
                         "AA")
        assert_detach_invariants(self, table, tree)

    def test_reattach_rebinds_a_stale_stored_binding(self):
        # Revision 3: the walk rebinds the item to the row at its
        # position when it recomputes the tuple. The §4.2 build runs
        # before the detach arm and rebinds only items already
        # detached, so an item detached by a load keeps its old row
        # dict — plant that stale binding here and assert the reattach
        # refreshes it to the current row, so the open path reads the
        # row the item is showing, not the one it showed before.
        rows = detach_spec_rows(3, easy_indices={1})
        table, tree = load_detach_table(rows)
        before = list(tree._order)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")
        table._tree_item_rows[before[0]] = dict(rows[0], Meter=99)

        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("All difficulties")

        self.assertIs(table._tree_item_rows[before[0]], rows[0])
        shown = tree.shown_values()
        self.assertEqual(shown[0][HEADERS.index("Meter")], 10)
        assert_detach_invariants(self, table, tree)


class DetachCancellationTests(unittest.TestCase):
    """A large restore cancelled mid-walk by a superseding refresh
    leaves a consistent state (Proposal 0021, §6): under the deferred
    arm the tree's children, the order list and the detached set are
    unchanged by the stale continuation, and under the fallback arm no
    item is attached-while-detached or detached-while-in-visible-order."""

    @staticmethod
    def make_cancel_table(deferred):
        # P00–P50 Hard, P51–P60 Easy: the widen restores 51 detached
        # rows, so the trigger (strictly greater than 50) takes the
        # large arm — the old 60-row fixture restored exactly 50 and
        # took the small per-index path under both arms (ChatGPT-6,
        # PR #283 review). The widen's first position is a reattach,
        # so a zero budget stops after one reattached item.
        rows = detach_spec_rows(61, easy_indices=set(range(51, 61)))
        table, tree = load_detach_table(rows)
        table._reattach_deferred = deferred
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")
        return table, tree, rows

    def _cancel_and_supersede(self, deferred):
        table, tree, rows = self.make_cancel_table(deferred)
        moves_before = len(tree.move_calls)
        set_children_before = len(tree.set_children_calls)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 0):
            table._filter.diff_var.set("All difficulties")
        # The widen stopped after one reattach and scheduled a
        # continuation; a superseding refresh narrows to Hard instead
        # of finishing the widen. The stale continuation is for the
        # all-difficulties list, so if it ran it would put the Easy
        # rows back — the generation guard is what stops it.
        widen_moves = tree.move_calls[moves_before:]
        widen_set_children = tree.set_children_calls[set_children_before:]
        first_item = next(item for item, row in
                          table._tree_item_rows.items() if row is rows[0])
        continuation = table._parent.after.call_args.args[1]
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Hard")
        children = list(tree.get_children())
        order = list(table._tree_item_order)
        detached = set(table._tree_item_detached)
        continuation()
        return (table, tree, rows, children, order, detached,
                widen_moves, widen_set_children, first_item)

    def test_cancelled_deferred_restore_leaves_state_unchanged(self):
        (table, tree, rows, children, order, detached, widen_moves,
         widen_set_children, _first_item) = \
            self._cancel_and_supersede(deferred=True)
        # The one reattach the widen processed made no tree call: the
        # deferred arm places it without touching the widget.
        self.assertEqual(widen_moves, [])
        self.assertEqual(widen_set_children, [])
        self.assertEqual(tree.shown_rows(table), rows[:51])
        self.assertEqual(len(detached), 10)
        self.assertEqual(list(tree.get_children()), children)
        self.assertEqual(table._tree_item_order, order)
        self.assertEqual(table._tree_item_detached, detached)
        assert_detach_invariants(self, table, tree)

    def test_cancelled_fallback_restore_keeps_no_half_attached_item(self):
        (table, tree, rows, children, order, detached, widen_moves,
         widen_set_children, first_item) = \
            self._cancel_and_supersede(deferred=False)
        # The one reattach the widen processed moved to "end" in its
        # own iteration, so it is attached and ordered together.
        self.assertEqual(widen_moves, [(first_item, "end")])
        self.assertEqual(widen_set_children, [])
        self.assertEqual(tree.shown_rows(table), rows[:51])
        self.assertEqual(len(detached), 10)
        self.assertEqual(list(tree.get_children()), children)
        self.assertEqual(table._tree_item_order, order)
        self.assertEqual(table._tree_item_detached, detached)
        for item in tree.get_children():
            self.assertNotIn(item, table._tree_item_detached)
        for item in table._tree_item_detached:
            self.assertNotIn(item, tree.get_children())
            key = table_module._chart_key(table._tree_item_rows[item])
            self.assertNotIn(key, table._tree_item_order)
        assert_detach_invariants(self, table, tree)

class DetachTriggerTests(unittest.TestCase):
    """The large-restore trigger (Proposal 0021, §6): a widen past
    the placement threshold takes one set_children, the deferred arm
    makes no per-item move, the fallback arm moves to "end" only, and
    a small restore moves to index with no set_children — in both the
    interleaved case and the tail case."""

    @staticmethod
    def widen_and_count(table, tree):
        """Widen from Easy to all difficulties and return the call
        deltas the walk made."""
        before = (len(tree.set_children_calls), len(tree.move_calls),
                  len(tree.index_calls), len(tree.insert_calls))
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("All difficulties")
        after = (len(tree.set_children_calls), len(tree.move_calls),
                 len(tree.index_calls), len(tree.insert_calls))
        return tuple(b - a for a, b in zip(before, after))

    def test_interleaved_widen_deferred(self):
        rows = detach_spec_rows(120, easy_indices=set(range(1, 120, 2)))
        table, tree = load_detach_table(rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")
        tree.set_children_calls.clear()
        tree.move_calls.clear()
        tree.index_calls.clear()
        tree.insert_calls.clear()

        set_children, moves, index_reads, inserts = \
            self.widen_and_count(table, tree)
        self.assertEqual((set_children, moves, index_reads, inserts),
                         (1, 0, 0, 0))
        self.assertEqual(tree.shown_rows(table), rows)
        assert_detach_invariants(self, table, tree)

    def test_tail_widen_deferred(self):
        rows = detach_spec_rows(110, easy_indices=set(range(10)))
        table, tree = load_detach_table(rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")

        set_children, moves, index_reads, inserts = \
            self.widen_and_count(table, tree)
        self.assertEqual((set_children, moves, index_reads, inserts),
                         (1, 0, 0, 0))
        self.assertEqual(tree.shown_rows(table), rows)
        assert_detach_invariants(self, table, tree)

    def test_interleaved_widen_fallback(self):
        rows = detach_spec_rows(120, easy_indices=set(range(1, 120, 2)))
        table, tree = load_detach_table(rows)
        table._reattach_deferred = False
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")
        moves_before = len(tree.move_calls)

        set_children, moves, index_reads, inserts = \
            self.widen_and_count(table, tree)
        self.assertEqual((set_children, index_reads, inserts), (1, 0, 0))
        self.assertEqual(moves, 60)
        self.assertTrue(all(index == "end" for _, index in
                            tree.move_calls[moves_before:]))
        self.assertEqual(tree.shown_rows(table), rows)
        assert_detach_invariants(self, table, tree)

    def test_tail_widen_fallback(self):
        rows = detach_spec_rows(110, easy_indices=set(range(10)))
        table, tree = load_detach_table(rows)
        table._reattach_deferred = False
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")
        moves_before = len(tree.move_calls)

        set_children, moves, index_reads, inserts = \
            self.widen_and_count(table, tree)
        self.assertEqual((set_children, index_reads, inserts), (1, 0, 0))
        self.assertEqual(moves, 100)
        self.assertTrue(all(index == "end" for _, index in
                            tree.move_calls[moves_before:]))
        self.assertEqual(tree.shown_rows(table), rows)
        assert_detach_invariants(self, table, tree)

    def test_small_restore_moves_to_index_without_set_children(self):
        rows = detach_spec_rows(3, easy_indices={1})
        table, tree = load_detach_table(rows)
        before = list(tree._order)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")
        moves_before = len(tree.move_calls)

        set_children, moves, index_reads, inserts = \
            self.widen_and_count(table, tree)
        self.assertEqual((set_children, index_reads, inserts), (0, 0, 0))
        self.assertEqual(moves, 2)
        self.assertEqual(tree.move_calls[moves_before:],
                         [(before[0], 0), (before[2], 2)])
        self.assertEqual(tree._order, before)
        assert_detach_invariants(self, table, tree)

    def test_fifty_reattachments_take_the_small_path(self):
        # The trigger is strictly greater than the threshold, so
        # exactly 50 reattachments do not pass it: the walk moves each
        # one to its index, with no set_children.
        rows = detach_spec_rows(60, easy_indices=set(range(50, 60)))
        table, tree = load_detach_table(rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")

        set_children, moves, index_reads, inserts = \
            self.widen_and_count(table, tree)
        self.assertEqual((set_children, index_reads, inserts), (0, 0, 0))
        self.assertEqual(moves, 50)
        self.assertEqual(tree.shown_rows(table), rows)
        assert_detach_invariants(self, table, tree)

    def test_fifty_one_reattachments_take_the_large_path(self):
        # One more reattachment passes the trigger, so the walk takes
        # one set_children and no per-item move.
        rows = detach_spec_rows(61, easy_indices=set(range(51, 61)))
        table, tree = load_detach_table(rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")

        set_children, moves, index_reads, inserts = \
            self.widen_and_count(table, tree)
        self.assertEqual((set_children, moves, index_reads, inserts),
                         (1, 0, 0, 0))
        self.assertEqual(tree.shown_rows(table), rows)
        assert_detach_invariants(self, table, tree)


class DetachResetTests(unittest.TestCase):
    """The driver's reset (Proposal 0021, §4.4): reset_table_state
    empties the owned maps, the detached set, the tree and the tint
    after detaches, so the next trial starts from a clean table."""

    def test_reset_table_state_empties_everything_after_detaches(self):
        rows = detach_spec_rows(4, easy_indices={1, 3})
        table, tree = load_detach_table(rows)
        before = list(tree._order)
        tree.selection_add(before[1])
        table._tree_tint.note_selected(before[1])
        tree.focus(before[1])
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")

        table.reset_table_state()

        self.assertEqual(tree.get_children(), ())
        self.assertEqual(tree._items, {})
        self.assertEqual(table._tree_item_rows, {})
        self.assertEqual(table._tree_item_order, [])
        self.assertEqual(table._tree_item_display, {})
        self.assertEqual(table._tree_item_detached, set())
        self.assertEqual(table._tree_tint.items, set())
        self.assertEqual(tree.focus(), "")
        self.assertEqual(tree.selection(), ())


class DetachCountLabelTests(unittest.TestCase):
    """The count label on a large restore (Proposal 0021, §6): the
    walk shows "Loading…" while it runs and settles on the final
    count, and an unchanged refresh shows none."""

    def test_large_restore_shows_loading_then_settles(self):
        rows = detach_spec_rows(110, easy_indices=set(range(10)))
        table, tree = load_detach_table(rows)
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            table._filter.diff_var.set("Easy")
        table.count_label.set.reset_mock()
        # A zero budget stops after the first position, so the
        # "Loading…" label is visible mid-walk.
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 0):
            table._filter.diff_var.set("All difficulties")
        table.count_label.set.assert_called_with("Loading 1 of 110 charts…")
        continuation = table._parent.after.call_args.args[1]
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS", 60):
            continuation()
        table.count_label.set.assert_called_with(
            "110 charts shown · 110 total")
        assert_detach_invariants(self, table, tree)
