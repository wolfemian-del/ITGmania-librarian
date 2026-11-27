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
from collections import Counter
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
    """Empty the tree and clear the table's saved diff state together.

    Delegates to LibraryTable.reset_table_state (Proposal 0021,
    §4.4): the table owns the maps, so it owns the reset — and a
    reset through get_children() alone would leave detached items
    orphaned in the widget while the maps are cleared.
    """
    table.reset_table_state()


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


def time_raw_arm(root, row_count, deferred, budget_ms=12):
    """Time one raw reattach arm in a disposable Treeview (Proposal
    0021, D7): detach every row, then reattach them the way the arm
    does — the deferred arm with one set_children call, the
    self-contained arm with a move to "end" per item plus one
    set_children. The moves run in budget-sized batches with the event
    loop pumped between them, the way _apply_diff_batch yields, so a
    small budget pays the between-batch cost the arm's batches incur;
    the deferred arm takes one batch whatever the budget. No
    LibraryTable bookkeeping exists here, so no saved state can be
    corrupted — the comparison is bare Tk only. Returns (seconds,
    batches)."""
    tree = tk.ttk.Treeview(root)
    for _ in range(row_count):
        tree.insert("", "end")
    root.update()
    children = list(tree.get_children())
    for item in children:
        tree.detach(item)
    root.update()
    batches = 0
    started = time.perf_counter()
    if deferred:
        tree.set_children("", *children)
        batches = 1
    else:
        budget = budget_ms / 1000
        index = 0
        while index < len(children):
            batches += 1
            deadline = time.perf_counter() + budget
            while index < len(children) and time.perf_counter() < deadline:
                tree.move(children[index], "", "end")
                index += 1
            root.update()
        tree.set_children("", *children)
    root.update()
    total = time.perf_counter() - started
    tree.destroy()
    return total, batches


def time_raw_small_reattach(root, row_count, count):
    """Time a small restore in a disposable Treeview (Proposal 0021,
    §6): detach `count` rows near the end of the tree, then move each
    back to its index — the per-item arm the walk takes under the
    placement threshold, at the high indices where move-to-index costs
    most. Returns seconds."""
    tree = tk.ttk.Treeview(root)
    for _ in range(row_count):
        tree.insert("", "end")
    root.update()
    children = list(tree.get_children())
    targets = children[-count:] if count else []
    for item in targets:
        tree.detach(item)
    root.update()
    started = time.perf_counter()
    for index, item in enumerate(targets, start=len(children) - count):
        tree.move(item, "", index)
    root.update()
    total = time.perf_counter() - started
    tree.destroy()
    return total


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


def _restore_filters(filt, saved):
    """Put the filter choices back (see main: the trials clear them)."""
    filt.pack_var.set(saved[0])
    filt.type_var.set(saved[1])
    filt.diff_var.set(saved[2])


def main():
    root = tk.Tk()
    application = app.LibraryApp(root)
    table = application._table
    filt = application._filter
    panel = application.distribution_panel
    # The trials measure the full library, so a saved filter that hides
    # rows would make the startup wait time out (Greptile P2,
    # retrigger 2026-11-23): the wait expects the tree to hold the
    # whole library, and set_choices keeps a valid saved choice. Clear
    # all three filters first, and put the saved choices back at every
    # exit so the driver leaves the app as it found it.
    saved_filters = (filt.pack_var.get(), filt.type_var.get(),
                     filt.diff_var.get())
    filt.pack_var.set("All packs")
    filt.type_var.set("All types")
    filt.diff_var.set("All difficulties")
    # Wait for the initial load to settle completely, not just for the
    # first row (Greptile P2 #4): the first rows stream in through
    # _insert_batch, and a no-change refresh measured before the fill
    # finishes would absorb the rest of it.
    if not pump_until(root, lambda: len(filt.library_rows()) > 0, 120):
        print("The table is empty after 120 s: no snapshot restored?")
        print("Load the library in the app once, then run this again.")
        _restore_filters(filt, saved_filters)
        root.destroy()
        return
    if not wait_for_settled(root, table, len(filt.library_rows())):
        print("The table never settled: the initial fill did not finish.")
        _restore_filters(filt, saved_filters)
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

    # The raw variants for both reattach arms (Proposal 0021, D7):
    # the deferred arm (one set_children) against the self-contained
    # fallback (a move to "end" per item, then one set_children),
    # the fallback at both the app's 12 ms budget and a larger one —
    # the comparison measures an arm, not a budget. The deferred arm
    # stays unless a variant shows the fallback faster, or the
    # cancellation test fails against it.
    deferred_s, deferred_batches = time_raw_arm(
        root, len(visible), deferred=True)
    fallback_12_s, fallback_12_batches = time_raw_arm(
        root, len(visible), deferred=False, budget_ms=12)
    fallback_200_s, fallback_200_batches = time_raw_arm(
        root, len(visible), deferred=False, budget_ms=200)
    print(f"raw deferred reattach at {len(visible):,} rows: "
          f"{deferred_s:.2f} s ({deferred_batches} batch)")
    print(f"raw self-contained reattach at {len(visible):,} rows: "
          f"{fallback_12_s:.2f} s at 12 ms "
          f"({fallback_12_batches} batches), {fallback_200_s:.2f} s "
          f"at 200 ms ({fallback_200_batches} batches)")
    for count in (1, 10, 50):
        small_s = time_raw_small_reattach(root, len(visible), count)
        print(f"raw small reattach, {count} rows near the end: "
              f"{small_s:.3f} s")
    # Colliding songs and rows (Proposal 0021, Q8): whether the
    # delete-and-reinsert fallback for colliding songs is worth
    # extending to detach is settled on this count.
    key_counts = Counter(table_module._chart_key(row) for row in rows)
    colliding_songs = {key[0] for key, n in key_counts.items() if n > 1}
    colliding_rows = sum(n for n in key_counts.values() if n > 1)
    print(f"colliding songs: {len(colliding_songs)} "
          f"({colliding_rows} rows)")

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
    _restore_filters(filt, saved_filters)
    root.destroy()


if __name__ == "__main__":
    main()
