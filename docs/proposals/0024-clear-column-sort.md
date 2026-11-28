# Implementation Proposal: Clear the column sort back to unsorted

| | |
|---|---|
| **Status** | Draft — for review |
| **Author** | Muse |
| **Date** | 2026-11-28 |
| **Base** | main `4bbe911` (merge of PR #288, main-window geometry) |
| **Related** | Issue #278 |
| **Revision** | Revision 1 (2026-11-28) — reworks D2 to the caller-plus-`isinstance` seam, fixes the citations, corrects §5, and expands §6, per Claude's review of 2026-11-28 (comment 7242994225, verdict Request changes). |

Once a column sort is set, the table can only flip between ascending and descending — there is no way back to unsorted, the library's load order. This proposal adds a View-menu "Clear sort" item that returns the table to load order, and makes that unsorted state persist across restarts. The one real decision is the mechanism: a menu item, not a third click state on the header.

## 1. Background and Goal

From use (Ian, 2026-11-24, issue #278). The table always has at least one sort key by construction: on startup, an empty saved sort list is replaced with Pack ascending, so the default state is itself a sort. The View menu's "Reset column layout" resets column order, visibility, and widths, but never touches the sort.

Done means: the table offers a way back to unsorted; with no sort, the table shows rows in load order and no column carries a sort marker; and the unsorted state persists across restarts the way the sort keys do today — which means an empty `sort_keys` has to become a real persisted state instead of the startup code replacing it with Pack ascending.

This is a small feature: no new component boundary, no new settings key, no constructor contract change. It gets a short proposal anyway, because the issue itself says so ("If implementation finds a real design fork, a short proposal comes first") and there are two: the clearing mechanism (third click state vs a menu item), and how an empty saved sort list becomes a real persisted state without disturbing the first-launch default.

## 2. Current State (measured on main `4bbe911`)

- `sort_by` (`itgmania_library/library_table.py:501`) only toggles or replaces the key list. A plain click on the *first* sort key's column flips its direction; a plain click on another column makes it the sole ascending key (dropping the other keys); a Shift-click adds or flips a key. It never removes a key and never empties the list. [CODE]
- `reset_column_layout` (`library_table.py:347`) rebinds column order, visibility, and widths, then saves settings. It never touches `_sort_keys`. [CODE]
- The startup seed has two halves, and the distinction between "nothing was ever saved" and "the user cleared the sort" has to survive both. The table's seed parse (`library_table.py:243-253`) loads the saved `sort_keys`, validates each item, and then runs `if not self._sort_keys: self._sort_keys = [("Pack", False)]`. But the librarian builds the seed the table receives as `{"column_order": ..., "column_widths": ..., "sort_keys": self.saved_settings.get("sort_keys", [])}` (`itgmania_library/library_librarian.py:599-601`), so the `sort_keys` key is always present and "missing" and "present but empty" both reach the table as the same `[]`. A seam that only reads `"sort_keys" in saved_layout` in the table cannot work — the caller has to keep the distinction. The fix is at the caller: drop the default (`self.saved_settings.get("sort_keys")`, so a missing key stays missing as `None`), and in the table's seed parse treat a list as a saved sort and anything else as "no saved sort" (see §4). [CODE]
- `layout_state()` (`library_table.py:298-315`) returns `"sort_keys": [[column, descending] for column, descending in self._sort_keys]` (`:313-314`), so an empty `_sort_keys` would persist as `[]` with no change to the shape. The librarian's `_save_settings` (`itgmania_library/library_librarian.py:811-818`) writes `layout["sort_keys"]` straight from it. No save-side change is needed. [CODE]
- The View menu already has the sibling command: `view_menu.add_command(label="Reset column layout", command=self._table.reset_column_layout)` (`library_librarian.py:715`). [CODE]
- `_update_sort_headings` (`library_table.py:522`) renders a plain heading for any column not in the sort keys, so an empty key list needs no heading change. [CODE]
- The sort loop (`library_table.py:569`) is `for column, descending in reversed(self._sort_keys)`: with an empty key list it runs zero passes, so the display order is the filter's row order — load order. `filter_rows` (`itgmania_library/library_filter.py:177`) returns the rows that pass the filters in the order they were loaded; it filters, never reorders. [CODE]
- "Load order" is the order the app read the rows from disk: the cache folder's `os.scandir` walk order (`itgmania_library/library_loader.py:441`; phase 3 at `:579-586`), the same for a full parse and for the manifest-incremental path. It is stable across refreshes and restarts, but it is not alphabetical or otherwise designed: a song's charts sit together, and packs are possibly not grouped. What it actually looks like on a real library depends on how Windows lists the Cache folder and is unverified in the sandbox. [CODE, UNVERIFIED]
- Tests that pin the current fallback: `test_no_valid_sort_key_falls_back_to_the_default` (`tests/test_library_table.py:1038`, a seed whose items are all invalid falls back to `[["Pack", False]]`) and `test_non_list_seed_values_fall_back_to_defaults` (`:1049`, a non-list seed falls back). Both must keep passing. [CODE]
- The README's sort line (`README.md:48`): "Click a column heading to sort. Click it again to reverse the order." That line gains the "Clear sort" mention. [CODE]

## 3. The Decisions

**D1. The mechanism is a View-menu "Clear sort" item, not a third click state.** A menu item clears the whole sort in one action whether there is one key or five, it is parallel to "Reset column layout" in the same menu, and it is explicit and self-describing. A third click state (asc → desc → none) is rejected for three reasons, of which the first two carry the decision: it makes desc → asc two clicks instead of one (desc → none → asc), and it only handles the single-key case cleanly and is ambiguous under Shift-click multi-key sorts, where a plain click already collapses everything to one key. The third reason — that it changes the click rhythm every user has already learned — is the weakest. A better reason the menu fits: clearing discards state, possibly a multi-key sort the user built, so a deliberate menu action suits it. The rejected alternative is the third click state.

**D2. A present-but-empty saved `sort_keys` list is a deliberate unsorted state; a missing key, a non-list value, or a list with no valid item still falls back to Pack ascending.** This preserves the first-launch default (Pack ascending) and both existing fallback tests, and it needs no new settings key or format change — the format stays a list of `[column, descending]` pairs; only the interpretation of a present-but-empty list changes. The distinction between "missing" and "present and empty" has to survive from the settings file to the table, so it is kept at the caller: the librarian drops the `.get(..., [])` default (`self.saved_settings.get("sort_keys")`, so a missing key stays missing as `None`), and the table's seed parse treats a list as a saved sort and anything else as "no saved sort" (see §4). Once the caller keeps the distinction, no `"sort_keys" in saved_layout` test is needed in the table.

**D3. Unsorted means load order, with no fallback sort.** That is the natural consequence of an empty key list — the sort loop runs zero passes — and it is what the issue asks for ("the library's load order").

## 4. Recommended Design in Detail

No new component boundary. The table still owns its sort state (`_sort_keys`); the librarian still reads it through `layout_state()` and writes it through `_save_settings`. The one-sentence description a standalone reader needs: the table owns its sort state, clearing it empties the key list, and an empty saved list means unsorted.

- **New table method `clear_sort()`.** It returns immediately when `_sort_keys` is already empty (a refresh would redraw the distribution chart for no reason), otherwise it sets `self._sort_keys = []`, then calls `self.refresh_table(preserve_selection=True, changed_keys=set())` and `self._save_settings()` — the same tail `sort_by` already uses, since a sort changes order, not data. No heading change is needed (`_update_sort_headings` already renders plain headings for unsorted columns).
- **View menu.** One new command beside "Reset column layout" (`library_librarian.py:715`): `view_menu.add_command(label="Clear sort", command=self._table.clear_sort)`. The item is always enabled, like "Reset column layout" — greying it when unsorted would need a new table-to-menu notification on every sort change for little benefit. The menu reads, in order: "Reset column layout", then "Clear sort", then the existing distribution-panel toggle; where separators fall stays as today. That label is the interface change; the footer hint (`library_librarian.py:612`, "Click to sort · Shift-click adds sort keys · …") also describes sorting and is left as it is — the new item is documented in the README only (see §6).
- **Seed change, in two places** (`library_table.py:243-253` and `library_librarian.py:599-601`). The librarian drops the default so a missing key stays missing:

  ```python
  "sort_keys": self.saved_settings.get("sort_keys")},
  ```

  and the table's seed parse treats a list as a saved sort and anything else as "no saved sort":

  ```python
  saved_sort_keys = saved_layout.get("sort_keys")
  if isinstance(saved_sort_keys, list):
      ...validate items exactly as today...
      if saved_sort_keys and not self._sort_keys:   # had items, none valid
          self._sort_keys = [("Pack", False)]
  else:                                              # missing, None, or not a list
      self._sort_keys = [("Pack", False)]
  ```

  So: key absent, `None`, or not a list → `[("Pack", False)]` (first launch, or an old file; the current behaviour, and the two fallback tests above); key present and a list → validate each item as today, and if the list was empty `_sort_keys` stays `[]` (unsorted, D2), or if it had items but none valid fall back to `[("Pack", False)]` (the current behaviour, and `test_no_valid_sort_key_falls_back_to_the_default`). The `saved_layout` docstring (`library_table.py:136-138`) states that an empty list means unsorted.
- **No save-side change.** `layout_state()` already returns `[]` for an empty key list, and the librarian already writes it, so a cleared sort persists as `"sort_keys": []`.

## 5. What Does Not Change

- Sorting itself: multi-column sort, the sort keys, the sort order, and the sort loop are untouched.
- The click behaviour: a plain click still toggles or replaces, a Shift-click still adds or flips. No third click state.
- `reset_column_layout`: it still resets order, visibility, and widths, and still never touches the sort.
- The first-launch default (Pack ascending) and the fallback for a missing, non-list, or all-invalid saved list — true with the caller fix in §4; without it, a first launch would start unsorted.
- The settings format: still a list of `[column, descending]` pairs. No new settings key, no new file format. An older build reading a saved `[]` would just show Pack ascending, so there is no downgrade hazard.
- Every other component: the song page, the distribution panel, the filter, and the course builder are untouched.

The librarian *is* touched, at two places: the seed default at `library_librarian.py:599-601` (§4) and the menu item at `:715`. Three documents change with the code: the README's sort line (`README.md:48`, gains the "Clear sort" mention), `docs/ARCHITECTURE.md:238` (its "a key that is missing or invalid simply falls back to its default" gains the qualifier that an empty `sort_keys` is a valid value that does not), and the `saved_layout` docstring (`library_table.py:136-138`, which states that an empty list means unsorted).

## 6. Test Plan (for the implementation PR)

- **New tests.**
  - `clear_sort` empties `_sort_keys`, refreshes, and persists `[]` through `layout_state()`; a present-but-empty saved list seeds unsorted (no Pack-ascending fallback); the unsorted table shows load order with no sort marker on any heading; the View menu carries a "Clear sort" command that calls `clear_sort`.
  - **A seam test through the real caller**, the one that would have caught the D2 problem: `make_live_app` (`tests/test_ui_distribution.py:995`) already takes a settings dict — no file or `{}` → `layout_state()["sort_keys"] == [["Pack", False]]`; `{"sort_keys": []}` → `[]`. It needs real Tk, so it is skipped in headless sandboxes and runs on the owner's Windows machine and the Windows CI job.
  - **Table-level pins side by side:** key missing, `None`, non-list, `[]`, and all-invalid items as five distinct cases.
  - **`sort_by` from the empty state:** a plain click gives `[(col, False)]`, a Shift-click gives one key.
  - **`clear_sort` details:** selection is preserved, `changed_keys=set()` (no tuples rebuilt), and clearing an already-unsorted table does nothing.
  - **Order after clearing equals `filter_rows()` order** and no heading carries a marker (the diff fixture, `make_diff_table`, can assert tree order).
  - **A persistence round trip:** clear, saved as `"sort_keys": []`, reseeded unsorted.
  - **The menu item:** the "View menu carries Clear sort" test needs real Tk (the existing pattern is `tests/test_ui_distribution.py:1143-1150`), so it is skipped in a sandbox without Tk.
- **Existing tests that must keep passing.** `test_no_valid_sort_key_falls_back_to_the_default` and `test_non_list_seed_values_fall_back_to_defaults` — the fallback semantics are preserved by D2.
- **Suite.** Full suite green (`python -m unittest discover -s tests`); README's sort line (`README.md:48`) gains the "Clear sort" mention; `docs/ARCHITECTURE.md:238` gains the qualifier in §5.
- **Live smoke (owner, four steps).** The D2 problem is invisible to headless tests, so the owner runs this short check:
  1. Delete `settings.json`, start the app: the heading shows `Pack ↑1`.
  2. Sort by Title, choose View → Clear sort: all heading markers disappear and the rows show load order. Is that order acceptable (§2)?
  3. Close and reopen: still unsorted, no marker.
  4. Click any heading: a fresh ascending sort starts. Then check Reset column layout leaves the sort alone.

## 7. Open Questions for Reviewers

- **Q1.** Is the View-menu "Clear sort" item the right (only) mechanism, or should the header also gain a third click state? The recommendation is the menu item only, for the reasons in D1. Three additions: the item is documented in the README only, not the footer (the footer is one line, and a fifth clause has not been measured to fit at the minimum window width); the item is always enabled, and `clear_sort` returns immediately when already unsorted rather than greying the item (which would need a new table-to-menu notification on every sort change); and the menu reads "Reset column layout", then "Clear sort", then the existing distribution-panel toggle, with separators as today.
- **Q2.** Should "Reset column layout" also clear the sort, so there is one reset instead of two? The recommendation is no — not because reset-layout deliberately never touched the sort (no comment says so, and the table's own docstring groups `_sort_keys` with column order and widths as the layout `layout_state()` persists together), but because the two operations have different targets: a fresh install starts at Pack ascending, while Clear sort goes to unsorted, so a combined reset must pick one. If it picked Pack ascending, "Clear sort" would still be needed; if it picked unsorted, Reset would no longer restore the fresh-install look (README:53 describes Reset as the fresh-install state). A second reason is that people reset the layout to fix messy columns, and losing their row order would be a visible side effect on an unrelated axis.

---

*Written by Muse.*
