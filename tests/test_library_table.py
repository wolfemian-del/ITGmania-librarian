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

from itgmania_library.library_constants import TAP_FIELDS
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
    # The app subscribes the table's refresh to the filter once the table
    # exists; the filter's rows were set before that, so the setup itself
    # does not refresh.
    filt.subscribe(table.refresh_table)
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
        self._counter = 0
        # How the table reordered rows: a test reads these to pin the
        # move arm (per-item moves for a small reorder, one set_children
        # for a large one).
        self.move_calls = []
        self.set_children_calls = []

    def insert(self, parent, index, values=(), tags=()):
        item = f"item{self._counter}"
        self._counter += 1
        self._items[item] = {"values": tuple(values), "tags": tuple(tags)}
        if index == "end" or index >= len(self._order):
            self._order.append(item)
        else:
            self._order.insert(index, item)
        return item

    def delete(self, *items):
        for item in items:
            self._items.pop(item, None)
            if item in self._order:
                self._order.remove(item)
            self._selection.discard(item)

    def move(self, item, parent, index):
        self.move_calls.append(item)
        self._order.remove(item)
        if index == "end" or index >= len(self._order):
            self._order.append(item)
        else:
            self._order.insert(index, item)

    def set_children(self, parent, *items):
        """Reorder the level in one call, like the real Treeview: items
        omitted from the list are detached, not destroyed, so they keep
        their values, tags and selection state."""
        self.set_children_calls.append(tuple(items))
        self._order = list(items)

    def index(self, item):
        return self._order.index(item)

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

    def focus(self):
        return ""

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
                preserve_selection=True)
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
        table.refresh_table.assert_called_once_with(preserve_selection=True)

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


class DiffFilterTests(unittest.TestCase):
    """A filter narrowing keeps the surviving items (Proposal 0019, §6)."""

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
        self.assertEqual(len(tree._items), 1)
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
