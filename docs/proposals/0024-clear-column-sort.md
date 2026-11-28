# Implementation Proposal: Clear the column sort back to unsorted

| | |
|---|---|
| **Status** | Draft — for review |
| **Author** | Muse |
| **Date** | 2026-11-28 |
| **Base** | main `4bbe911` (merge of PR #288, main-window geometry) |
| **Related** | Issue #278 |

Once a column sort is set, the table can only flip between ascending and descending — there is no way back to unsorted, the library's load order. This proposal adds a View-menu "Clear sort" item that returns the table to load order, and makes that unsorted state persist across restarts. The one real decision is the mechanism: a menu item, not a third click state on the header.

## 1. Background and Goal

From use (Ian, 2026-11-24, issue #278). The table always has at least one sort key by construction: on startup, an empty saved sort list is replaced with Pack ascending, so the default state is itself a sort. The View menu's "Reset column layout" resets column order, visibility, and widths, but never touches the sort.

Done means: the table offers a way back to unsorted; with no sort, the table shows rows in load order and no column carries a sort marker; and the unsorted state persists across restarts the way the sort keys do today — which means an empty `sort_keys` has to become a real persisted state instead of the startup code replacing it with Pack ascending.

This is a small feature: no new component boundary, no new settings key, no constructor contract change. It gets a short proposal anyway, because the issue itself says so ("If implementation finds a real design fork, a short proposal comes first") and there are two: the clearing mechanism (third click state vs a menu item), and how an empty saved sort list becomes a real persisted state without disturbing the first-launch default.

## 2. Current State (measured on main `4bbe911`)

- `sort_by` (`itgmania_library/library_table.py:501`) only toggles or replaces the key list. A plain click on the sorted column flips it; a plain click on another column makes it the sole ascending key; a Shift-click adds or flips a key. It never removes a key and never empties the list. [CODE]
- `reset_column_layout` (`library_table.py:347`) rebinds column order, visibility, and widths, then saves settings. It never touches `_sort_keys`. [CODE]
- The startup seed (`library_table.py:243-253`) loads the saved `sort_keys`, validates each item, and then runs `if not self._sort_keys: self._sort_keys = [("Pack", False)]`. So an empty saved list — or a list whose items are all invalid — becomes Pack ascending. The saved value is read with `saved_layout.get("sort_keys", [])`, which cannot tell a missing key from a present-but-empty list. [CODE]
- `layout_state()` (`library_table.py:302-314`) returns `"sort_keys": [[column, descending] for column, descending in self._sort_keys]`, so an empty `_sort_keys` would persist as `[]` with no change to the shape. The librarian's `_save_settings` (`itgmania_library/library_librarian.py:811-818`) writes `layout["sort_keys"]` straight from it. No save-side change is needed. [CODE]
- The View menu already has the sibling command: `view_menu.add_command(label="Reset column layout", command=self._table.reset_column_layout)` (`library_librarian.py:715`). [CODE]
- `_update_sort_headings` (`library_table.py:522`) renders a plain heading for any column not in the sort keys, so an empty key list needs no heading change. [CODE]
- The sort loop (`library_table.py:569`) is `for column, descending in reversed(self._sort_keys)`: with an empty key list it runs zero passes, so the display order is the filter's row order — load order. `filter_rows` (`itgmania_library/library_filter.py:177`) returns the rows that pass the filters in the order they were loaded; it filters, never reorders. [CODE]
- Tests that pin the current fallback: `test_no_valid_sort_key_falls_back_to_the_default` (`tests/test_library_table.py:1038`, a seed whose items are all invalid falls back to `[["Pack", False]]`) and `test_non_list_seed_values_fall_back_to_defaults` (`:1045`, a non-list seed falls back). Both must keep passing. [CODE]
- The README's sort line (`README.md:48`): "Click a column heading to sort. Click it again to reverse the order." That line gains the "Clear sort" mention. [CODE]

## 3. The Decisions

**D1. The mechanism is a View-menu "Clear sort" item, not a third click state.** A menu item clears the whole sort in one action whether there is one key or five, it is parallel to "Reset column layout" in the same menu, and it is explicit and self-describing. A third click state (asc → desc → none) is rejected for three reasons: it makes desc → asc two clicks instead of one (desc → none → asc), it only handles the single-key case cleanly and is ambiguous under Shift-click multi-key sorts, and it changes the click rhythm every user has already learned. The rejected alternative is the third click state.

**D2. A present-but-empty saved `sort_keys` list is a deliberate unsorted state; a missing key, a non-list value, or a list with no valid item still falls back to Pack ascending.** This preserves the first-launch default (Pack ascending) and both existing fallback tests, and it needs no new settings key or format change — the format stays a list of `[column, descending]` pairs; only the interpretation of a present-but-empty list changes. The seed has to distinguish "absent" from "present and empty", which the current `.get("sort_keys", [])` cannot, so it reads the key with `"sort_keys" in saved_layout` instead.

**D3. Unsorted means load order, with no fallback sort.** That is the natural consequence of an empty key list — the sort loop runs zero passes — and it is what the issue asks for ("the library's load order").

## 4. Recommended Design in Detail

No new component boundary. The table still owns its sort state (`_sort_keys`); the librarian still reads it through `layout_state()` and writes it through `_save_settings`. The one-sentence description a standalone reader needs: the table owns its sort state, clearing it empties the key list, and an empty saved list means unsorted.

- **New table method `clear_sort()`.** It sets `self._sort_keys = []`, then calls `self.refresh_table(preserve_selection=True, changed_keys=set())` and `self._save_settings()` — the same tail `sort_by` already uses, since a sort changes order, not data. No heading change is needed (`_update_sort_headings` already renders plain headings for unsorted columns).
- **View menu.** One new command beside "Reset column layout" (`library_librarian.py:715`): `view_menu.add_command(label="Clear sort", command=self._table.clear_sort)`. That label is the interface change; there is no other visible surface.
- **Seed change** (`library_table.py:243-253`). The saved list is read so that absence is distinguishable from an empty list:

  - Key absent, or value not a list → `self._sort_keys = [("Pack", False)]` (first launch, or an old file; the current behaviour, and the two fallback tests above).
  - Key present and a list → validate each item as today; if the list was empty, `_sort_keys` stays `[]` (unsorted, D2); if it had items but none valid, fall back to `[("Pack", False)]` (the current behaviour, and `test_no_valid_sort_key_falls_back_to_the_default`).
- **No save-side change.** `layout_state()` already returns `[]` for an empty key list, and the librarian already writes it, so a cleared sort persists as `"sort_keys": []`.

## 5. What Does Not Change

- Sorting itself: multi-column sort, the sort keys, the sort order, and the sort loop are untouched.
- The click behaviour: a plain click still toggles or replaces, a Shift-click still adds or flips. No third click state.
- `reset_column_layout`: it still resets order, visibility, and widths, and still never touches the sort.
- The first-launch default (Pack ascending) and the fallback for a missing, non-list, or all-invalid saved list.
- The settings format: still a list of `[column, descending]` pairs. No new settings key, no new file format.
- Every other component: the song page, the distribution panel, the filter, and the course builder are untouched.

## 6. Test Plan (for the implementation PR)

- **New tests.** `clear_sort` empties `_sort_keys`, refreshes, and persists `[]` through `layout_state()`; a present-but-empty saved list seeds unsorted (no Pack-ascending fallback); the unsorted table shows load order with no sort marker on any heading; the View menu carries a "Clear sort" command that calls `clear_sort`.
- **Existing tests that must keep passing.** `test_no_valid_sort_key_falls_back_to_the_default` and `test_non_list_seed_values_fall_back_to_defaults` — the fallback semantics are preserved by D2.
- **Suite.** Full suite green (`python -m unittest discover -s tests`); README's sort line (`README.md:48`) gains the "Clear sort" mention.
- **Live smoke.** None required beyond the owner's normal check: the change is small, headless-testable, and the only visible surface is one standard menu command.

## 7. Open Questions for Reviewers

- **Q1.** Is the View-menu "Clear sort" item the right (only) mechanism, or should the header also gain a third click state? The recommendation is the menu item only, for the three reasons in D1.
- **Q2.** Should "Reset column layout" also clear the sort, so there is one reset instead of two? The recommendation is no — reset-layout deliberately never touched the sort, and folding it in would change what "Reset column layout" does.

---

*Written by Muse.*
