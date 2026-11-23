"""Time the table side of a refresh on the real library (Proposal 0019, §6).

Opens the real app on the owner's library — the real settings, cache, and
Stats.xml — and times, separately: filter_rows; the no-change refresh
(filter + sorts + diff walk + the panel push); tree.delete of all items;
tree.insert per row (steady-state and first paint); the after(1, ...)
batch overhead at ROW_INSERT_BUDGET_SECONDS 12/50/200 ms; the
distribution redraw; the diff with a few changed rows; and the detach
trial (Proposal 0021, D7): the filter-toggle round trip through the
production table, and the raw detach/reattach against delete/insert in
a disposable Treeview at the library's scale.

Run from the repo, next to launch.py, on Windows with a display:
    python tools/time_table_refresh.py

Nothing is written: no load, no sync, no snapshot save — the script only
reads the library and drives the table. The report says whether the split
confirms §2's inference (per-item insert dominates the ~14 s) or
contradicts it. If the redraw or the batch scheduling dominates instead,
§7 Q3 says the implementation PR also takes that term.
"""

import sys
import time
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import tkinter as tk  # noqa: E402

from itgmania_library import library_librarian as app  # noqa: E402
from itgmania_library import library_table as table_module  # noqa: E402

BUDGETS_MS = (12, 50, 200)
CHANGED_ROWS = 5


def pump_until(root, condition, timeout=120):
    """Run the event loop until condition() is true or the timeout hits."""
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        root.update()
        time.sleep(0.02)
    return condition()


def wait_for_settled(root, table, visible_count, timeout=180):
    """Pump until the tree holds the visible rows and the count label has
    settled (no longer a 'Loading …' progress count)."""
    def settled():
        return (len(table.tree.get_children()) == visible_count
                and not table.count_label.get().startswith("Loading"))
    return pump_until(root, settled, timeout)


def reset_table_state(table):
    """Empty the tree and clear the table's saved diff state together
    (Greptile P1 #1): deleting the items without clearing
    _tree_item_rows/_tree_item_order/_tree_item_display leaves the diff
    thinking every row is already showing, so the next refresh skips
    every insert and the trial waits the full deadline. The tint tracker
    and the focus go with them, so no stale tag or focused row survives
    the reset."""
    table.tree.delete(*table.tree.get_children())
    table._tree_item_rows.clear()
    table._tree_item_order.clear()
    table._tree_item_display.clear()
    table._tree_tint.reset()
    table.tree.focus("")


def time_full_insert(root, table, visible_count, budget_ms):
    """Empty the tree, then time the full re-insert at one batch budget.

    Returns (total seconds, batches, first-paint seconds). The batch
    count is the after() reschedules the inserter made; the first paint
    is when the first row appears in the tree — read right after the
    refresh returns, because the first batch inserts synchronously and
    a root.update() in the pump drains the whole after() chain in one
    call, so a check after update() always reports the finished tree
    (Revision 2: the first-paint number used to equal the total).
    """
    reset_table_state(table)
    batches = [0]
    original_after = table._parent.after

    def counting_after(ms, func, *args, **kwargs):
        batches[0] += 1
        return original_after(ms, func, *args, **kwargs)

    table._parent.after = counting_after
    try:
        with patch.object(table_module, "ROW_INSERT_BUDGET_SECONDS",
                          budget_ms / 1000):
            started = time.perf_counter()
            table.refresh_table()
            painted_at = None
            if table.tree.get_children():
                painted_at = time.perf_counter()
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                root.update()
                if painted_at is None and table.tree.get_children():
                    painted_at = time.perf_counter()
                if (len(table.tree.get_children()) == visible_count
                        and not table.count_label.get().startswith("Loading")):
                    break
                time.sleep(0.005)
            total = time.perf_counter() - started
    finally:
        table._parent.after = original_after
    first_paint = (painted_at - started) if painted_at is not None else None
    return total, batches[0], first_paint


def time_filter_toggle(root, table, filt, visible_count, rows):
    """Time the filter-toggle round trip through the production table
    (Proposal 0021, D7): narrow to one difficulty, then widen back to
    all of them. The widening is the operation detach accelerates: today
    it re-inserts every hidden row, with detach it reattaches them.
    Returns (narrow seconds, widen seconds, narrowed count, difficulty).
    The filter is left where it started (all difficulties)."""
    difficulties = sorted({row["Difficulty"] for row in rows
                           if row["Difficulty"]})
    pick = "Hard" if "Hard" in difficulties else difficulties[len(difficulties) // 2]
    started = time.perf_counter()
    filt.diff_var.set(pick)
    narrowed = len(filt.filter_rows())
    wait_for_settled(root, table, narrowed)
    narrow_s = time.perf_counter() - started
    started = time.perf_counter()
    filt.diff_var.set("All difficulties")
    wait_for_settled(root, table, visible_count)
    widen_s = time.perf_counter() - started
    return narrow_s, widen_s, narrowed, pick


def time_raw_detach_reattach(root, row_count):
    """Time the raw Tk operations in a disposable Treeview (Proposal
    0021, D7): detach every row and reattach each one at its index,
    against deleting every row and inserting them all again. No
    LibraryTable bookkeeping exists here, so no saved state can be
    corrupted — the comparison is bare Tk only. Returns (detach seconds,
    reattach seconds, delete seconds, insert seconds)."""
    tree = tk.ttk.Treeview(root)
    for _ in range(row_count):
        tree.insert("", "end")
    root.update()
    children = tree.get_children()
    start = time.perf_counter()
    for item in children:
        tree.detach(item)
    detach_s = time.perf_counter() - start
    start = time.perf_counter()
    for index, item in enumerate(children):
        tree.move(item, "", index)
    root.update()
    reattach_s = time.perf_counter() - start
    start = time.perf_counter()
    tree.delete(*tree.get_children())
    delete_s = time.perf_counter() - start
    start = time.perf_counter()
    for _ in range(row_count):
        tree.insert("", "end")
    root.update()
    insert_s = time.perf_counter() - start
    tree.destroy()
    return detach_s, reattach_s, delete_s, insert_s


def main():
    root = tk.Tk()
    application = app.LibraryApp(root)
    table = application._table
    filt = application._filter
    panel = application.distribution_panel
    # Wait for the initial load to settle completely, not just for the
    # first row (Greptile P2 #4): the first rows stream in through
    # _insert_batch, and a no-change refresh measured before the fill
    # finishes would absorb the rest of it.
    if not pump_until(root, lambda: len(filt.library_rows()) > 0, 120):
        print("The table is empty after 120 s: no snapshot restored?")
        print("Load the library in the app once, then run this again.")
        root.destroy()
        return
    if not wait_for_settled(root, table, len(filt.library_rows())):
        print("The table never settled: the initial fill did not finish.")
        root.destroy()
        return
    rows = filt.library_rows()
    visible = filt.filter_rows()
    print(f"Library: {len(rows):,} charts shown · "
          f"{len(rows):,} total (filter passes all)")

    # filter_rows on its own, and the no-change refresh (filter + sorts
    # + diff walk + the panel push) — the difference is the sorts, the
    # diff walk, and one redraw.
    start = time.perf_counter()
    filt.filter_rows()
    filter_s = time.perf_counter() - start
    start = time.perf_counter()
    table.refresh_table()
    wait_for_settled(root, table, len(visible))
    refresh_s = time.perf_counter() - start
    print(f"filter_rows: {filter_s:.2f} s")
    print(f"no-change refresh (filter + sorts + diff + panel push): {refresh_s:.2f} s")

    # tree.delete of every item, timed on its own.
    start = time.perf_counter()
    table.tree.delete(*table.tree.get_children())
    delete_s = time.perf_counter() - start
    print(f"tree.delete of {len(visible):,} items: {delete_s:.2f} s")

    # The full insert at each budget (the tree is empty after the delete,
    # so each refresh streams in through _insert_batch).
    insert_total_12 = None
    for budget_ms in BUDGETS_MS:
        total, batches, first_paint = time_full_insert(
            root, table, len(visible), budget_ms)
        if budget_ms == 12:
            insert_total_12 = total
        per_row = total / max(len(visible), 1)
        paint = f"{first_paint:.2f} s" if first_paint is not None else "n/a"
        print(f"full insert, {budget_ms} ms budget: {total:.2f} s "
              f"({per_row * 1000:.2f} ms/row, {batches} batches, "
              f"first paint {paint})")

    # The distribution redraw, as the refresh pays it (a no-op when the
    # panel is closed, which is the honest number for that state).
    panel_open = bool(panel.show_distribution_panel.get())
    start = time.perf_counter()
    panel.show_rows(visible)
    root.update()
    redraw_s = time.perf_counter() - start
    print(f"distribution redraw (panel {'open' if panel_open else 'closed'}): "
          f"{redraw_s:.2f} s")

    # The diff with a few changed rows: fresh dicts for the whole library
    # (as a load brings), with CHANGED_ROWS scores changed.
    new_rows = [dict(row) for row in rows]
    for row in new_rows[:CHANGED_ROWS]:
        row["Grade"] = "AAA"
    start = time.perf_counter()
    filt.set_rows(new_rows)
    wait_for_settled(root, table, len(visible))
    changed_s = time.perf_counter() - start
    print(f"diff refresh, {CHANGED_ROWS} changed rows: {changed_s:.2f} s")

    # The detach trial (Proposal 0021, D7): the filter-toggle round
    # trip through the production table, then the raw Tk comparison.
    narrow_s, widen_s, narrowed, pick = time_filter_toggle(
        root, table, filt, len(visible), rows)
    print(f"filter toggle to {pick} ({narrowed:,} rows): {narrow_s:.2f} s; "
          f"widen back: {widen_s:.2f} s")
    detach_s, reattach_s, raw_delete_s, raw_insert_s = \
        time_raw_detach_reattach(root, len(visible))
    raw_detach_total = detach_s + reattach_s
    raw_delete_total = raw_delete_s + raw_insert_s
    ratio = (raw_delete_total / raw_detach_total
             if raw_detach_total else float("inf"))
    print(f"raw detach+reattach at {len(visible):,} rows: "
          f"{raw_detach_total:.2f} s (detach {detach_s:.2f} s, "
          f"reattach {reattach_s:.2f} s); delete+insert: "
          f"{raw_delete_total:.2f} s (delete {raw_delete_s:.2f} s, "
          f"insert {raw_insert_s:.2f} s); ratio {ratio:.1f}x")

    print()
    # refresh_s already includes one redraw (refresh_table pushes the
    # visible rows to the panel), so adding redraw_s again would count
    # it twice (Greptile P2 #4).
    other_s = delete_s + refresh_s
    if insert_total_12 is not None and insert_total_12 > other_s * 2:
        print("Verdict: per-item insert dominates — §2's inference holds.")
    else:
        print("Verdict: the insert does NOT dominate — see §7 Q3, the "
              "implementation should also take the dominant term.")
    root.destroy()


if __name__ == "__main__":
    main()
