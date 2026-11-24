# Implementation Proposal: 0022 — rebuild display tuples only for rows the loader says changed

| | |
|---|---|
| **Status** | Draft — for review |
| **Author** | Muse |
| **Date** | 2026-11-23 |
| **Base** | main `823e8ea` (PR #272 merged; PR #271 P5 implementation in review at Revision 3) |
| **Related** | Proposal 0019 (P5, accepted — the diff this builds on); PR #271 (P5 implementation, Revisions 1–3); Proposal 0021 (detach filter rows, draft — also touches `_apply_diff`, sequence in §6); `tools/time_table_refresh.py` (§6 driver); `tools/profile_sort_click.py` (Title-click profiler, uncommitted) |

---

In plain language: clicking the Title header takes about a second and a half, and the profile says why — the table rebuilds the display values for all 42,375 rows on every refresh, just to check whether any of them changed. It has to check, because a sync re-scores cells in place and the table has no other way to know what moved. This proposal gives the table that knowledge: the loader already knows which rows it re-scored, so it hands the table the list of changed rows, and the table rebuilds display values only for those — plus the few rows the selection tint touches. A sort or a filter change touches no rows at all, so the rebuild drops to nothing and the click is the sort plus the reorder. Nothing about the app looks different, and the table still shows exactly the same rows in exactly the same order. The one real decision is what the table trusts: instead of detecting changes itself by rebuilding every tuple, it trusts the loader's changed list — and the safe default, when nobody says what changed, is still to rebuild everything, exactly as today.

## 1. Background and Goal

P5 (proposal 0019, accepted; implementation PR #271 in review) stops the table throwing all its rows away on every refresh: `refresh_table` diffs the new visible set against the tree and only inserts, deletes, or updates what actually changed. That fixed the refresh, the sort click, and the sync at the level of rows — but the update loop inside the diff still rebuilds the display tuple for every surviving row on every refresh, because the tuple is the only record of what a row was shown with, and a sync that re-scores cells in place leaves the table no other way to detect a change. The §6 measurement and the Title-click profile on the owner's machine (2026-11-23) show that loop is now the dominant term of a click: half the click is the tuple rebuild, and Revision 3 (the key cache, PR #271) removes the next term, the chart key, leaving the tuple rebuild as the one cost left to attack.

Modularity, up front: this change alters the contract between the loader and the table — the table stops detecting changes itself and trusts a changed-rows input the loader supplies. That is why it is a proposal, not an issue: the boundary moves, and the choice constrains later work (theme 3's song page reads rows back through the table; theme 5's library writing will change rows through the same path). Done means: a Title click on the owner's machine drops from ~1.5 s to roughly half a second, a sync that changes scores still updates exactly those cells, and the full suite is green — with the measurement in §2 confirming the split before the implementation is judged.

## 2. Current State (measured on PR #271 Revision 2, owner's machine, 2026-11-23)

The update loop is `_apply_diff` [CODE: `itgmania_library/library_table.py:506`]: for every surviving item it builds `shown = _display_tuple(row, key in selected_keys)`, compares it with the saved tuple in `_tree_item_display`, and rewrites the item when they differ or the item is in the forced set (tint tracker items plus selected items — the Revision 1 tag fix, issue #273). The loop must build the fresh tuple to compare: `merge_scores` re-derives score fields in place, so on a sync the old and new row dicts are the same objects and a dict comparison would see no change. The tuple itself is `_display_tuple` [CODE: `library_table.py:70`]: 40 display values (one `dict.get` per column, `format_duration` for Time, float formatting) plus `row_tags` (difficulty and selection tags).

The numbers, from the Title-click profile Ian ran (`tools/profile_sort_click.py`, 42,375 rows) [TESTED]: click 1 sync 1.01 s, total to settled 1.50 s; click 2 sync 0.96 s, total 1.28 s; 4 batches; one `set_children` call of 0.016 s. Profiled (3.77 s): `_apply_diff` 2.85 s (75%) — `_display_tuple` 1.87 s cumulative (50%, 42,375 calls), `_chart_key` 0.74 s (20%, 508,500 calls = 12 per row), `dict.get` 0.72 s; the pump and redisplay 0.71 s (19%, including the driver's own 0.2 s of pump sleeps); the placement walk `_apply_diff_batch` 0.26 s (7%); `filter_rows` 0.07 s; the sort itself too small to make the top 25. Revision 3 (key cache, commit `5aaa8a9`, 2026-11-23) removes the `_chart_key` term — about a fifth of the click, so the click should land near 1.2 s once re-measured — and leaves `_display_tuple` as the remaining dominant term. The Xvfb check at 12,000 rows confirms the cache at scale: a Title click builds exactly 12,000 keys (144,000 before) [RAN].

The data paths into the table [CODE]: a sync re-scores the filter's rows in place and calls `refresh_table(preserve_selection=True)` (`library_librarian.py:792`, with the invariant spelled out at `:786` — "a sync re-scores that list in place (merge_scores never replaces it), so there is nothing to re-set"); a load brings fresh rows through `set_rows` inside a batch (`:795`); a sort click calls `refresh_table(preserve_selection=True)` (`library_table.py:425`); a filter change reaches the table through the subscription, which calls `refresh_table()` with no arguments. `merge_scores` [CODE: `library_sources.py:216`] already detects per-row changes — it returns the number of rows whose score fields changed (`library_loader.py:662` assigns it as `changed`) — so it knows which rows changed today; it only reports how many.

Coupling inventory: `_apply_diff` and `_apply_diff_batch` (`library_table.py`), `_display_tuple` and `_chart_key` (same file), `merge_scores` (`library_sources.py:216`), the sync and load paths (`library_loader.py:496,662`, `library_librarian.py:772–804`), the filter subscription. No settings key, no file format, no new component. The tests that pin the loop today: `DiffChangeTests`, `DiffEquivalenceTests` (the saved-tuple vs in-place mutation pin), `DiffTagTests` (the forced rewrite), `DiffKeyCacheTests` (Revision 3).

## 3. The Decision: the table trusts a changed-rows input instead of detecting changes itself

The recommendation is a `changed_keys` input on `refresh_table`, defaulting to `None` meaning "unknown — rebuild every tuple", which is exactly today's behaviour. The data paths supply it: the sync passes the set `merge_scores` reports; the load passes `None` (fresh dicts — everything is potentially new, so rebuild all, no worse than today); a sort click and a filter change pass an empty set (they change order and visibility, not data). The update loop then rebuilds a tuple only for an item whose key is in `changed_keys` or in the forced set, and keeps the saved tuple for every other item. The forced set is unchanged — the tint and selection rewrite still runs for the items it touches, so the tag fix is unaffected.

The alternatives:

- **Key cache (done, Revision 3).** It removes the `_chart_key` term (~20%) and is already in PR #271. It does not touch the tuple rebuild, which is the remaining half. Not an alternative to this proposal — a prerequisite that already landed.
- **Time-box the update loop into the batches.** The tuple builds would stream like the inserts, so the window paints after the first batch instead of freezing for the whole loop. It fixes how the click feels, not how long it takes — the total work is unchanged — and it restructures `_apply_diff` (the loop currently runs synchronously before the walk, and the walk reads the state it writes). More invasive than the changed-keys input for a smaller win. Not recommended.
- **Do nothing.** The click at ~1.2 s after Revision 3 is about ten times faster than main's ~15 s rebuild and is not a regression. Defensible — but the remaining cost is one function doing work it does not need to do on most refreshes, and the fix is a small, well-bounded contract change. Not recommended while the measurement still points at it.

This does not overturn the roadmap (§5 of the roadmap rule): it is inside the faster-refresh theme, a follow-on to P5, and it forecloses nothing a later theme needs — the display-order seam for theme 3's Previous/Next is the order list, which this does not touch.

## 4. Recommended Design in Detail

The boundary: the loader owns knowing what changed; the table owns showing it. The loader reports, the table trusts, and the table never reaches back into the loader to re-derive a change. What lives inside the table is the loop's new rule (rebuild only changed or forced items) and the `changed_keys` parameter; what stays outside is how the loader decides a row changed (the merge's own comparison, unchanged).

The contract, in full:

1. `merge_scores` reports the set of changed chart keys alongside the count it already returns — the count is `len()` of that set, so the result message and log that read `changed` today keep working. The keys are the chart keys (`Course path`, `Type`, `Difficulty`, `Chart`), the same keys the diff already uses, so no new identity is introduced.
2. The changed set travels the path the sync already takes: the worker puts it in the load result, `_loaded` receives it on the sync branch, and `refresh_table` takes it as `changed_keys=None`. `None` means unknown — rebuild every tuple. An empty set means nothing changed. A load passes `None`.
3. `refresh_table` passes `changed_keys` to `_apply_diff`, which passes it to the update loop. The loop's rule becomes: rebuild the tuple for an item whose key is in `changed_keys` or in the forced set; otherwise keep the saved tuple and the saved item. The rebind (`_tree_item_rows[item] = row`) still runs for every survivor — on a load the row dicts are fresh, and the song page and course builder read their row back through that map — so only the tuple build is skipped, never the rebind.
4. The sort and filter paths pass an empty set. `sort_by` calls `refresh_table(preserve_selection=True, changed_keys=set())`; the filter subscription, which today calls `refresh_table()` with no arguments, subscribes a call that passes the empty set (a bound partial or a one-line wrapper — decided in implementation). The empty set is explicit at each call site, never a default: a future caller that refreshes with new data and forgets the set gets `None` and rebuilds everything, which is slow but correct — the failure mode of forgetting is a slow refresh, never a stale cell.

The legibility test: the table renders the visible rows by diff, rebuilding display values only for rows the loader says changed. One sentence, and it says what the component does and what it is given.

## 5. What Does Not Change

The tree's contents and order on every refresh; the selection behaviour (carried by chart key, dropped on a colliding re-insert); the tag fix (the forced rewrite still runs); the `set_children` placement and its trigger; the snapshot and manifest formats; what `merge_scores` re-derives (only its reporting changes); the count it reports; the filter, the loader's threading, and the song page's row read-back. The roadmap order is unchanged — this is a P5 follow-on, not a new theme.

## 6. Test Plan (for the implementation PR)

Pin current behaviour first (the existing `DiffChangeTests`, `DiffEquivalenceTests`, `DiffTagTests`, and `DiffKeyCacheTests` all still pass unchanged — they exercise the `None` default). New tests: a refresh with `changed_keys` holding one key rebuilds that row's tuple and no other (count `_display_tuple` calls); a refresh with an empty set rebuilds none except forced items (a selected row still gets its forced rewrite); a refresh with `None` rebuilds all; a sync that changes a score still updates the cell end-to-end through the loader path (the changed set flows from `merge_scores` to the table). The full suite stays green, and the live smoke is a Title click and a scores sync on the owner's machine, timed with `tools/profile_sort_click.py` and the §6 driver — the acceptance gate is the click dropping from ~1.2 s (post-Revision 3) toward ~0.5 s, with the sync's changed cells verified by eye.

Staging: implementation after PR #271 merges — it modifies the P5 diff, so it must not be in flight with it. Proposal 0021 (detach) also touches `_apply_diff`: the two implementations must not be in flight at once on the same function; 0021 sequences after this one (its case is the measured 12.30 s widen, and it is re-judged on the post-Revision-2 numbers either way).

## 7. Open Questions for Reviewers

- **Q1.** Should `merge_scores` return the set of changed keys (changing its return type from `int` to `set`, with the two loader call sites taking `len()` for the count), or keep returning the count and record the set on a companion (a second return value, or an out-parameter)? Recommendation: return the set — the count is derived, one return value stays one return value, and the two call sites are the only readers.
- **Q2.** Is the empty set at the sort and filter call sites explicit enough, or should the table itself record "no data change since the last refresh" (a flag the data paths clear)? Recommendation: explicit at the call sites — the knowledge lives where the call is made, and the `None` default stays the safe fallback.
- **Q3.** What counts as "changed" — score fields only, or any display field? Recommendation: score fields only, because `merge_scores` only re-derives score fields, and a load (which can change any field) passes `None` and rebuilds all anyway.
- **Q4.** The load path passes `None` and rebuilds all — should a reload with a populated tree get the same treatment, or should the loader compare old and new values during the merge and report the changed set there too? Recommendation: `None` for now; the reload case is rare and the full insert already dominates it, so the extra comparison buys nothing measurable.

---

*Written by Muse. The numbers are the owner's §6 and Title-click profile runs, 2026-11-23; the design was reviewed against the P5 diff and the loader before drafting.*
