# Implementation Proposal: Make the startup wiring plain

| | |
|---|---|
| **Status** | Draft |
| **Author** | Claude (Sonnet 5.5) |
| **Date** | 2026-11-17 |
| **Base** | main `be300eda` (PR #218 merged) |
| **Related** | Issue #208 (open); proposals 0005 (Q5, the sibling-frame callable), 0009 (loader and dialog contracts), 0011 stages 3–4 (song page and player wiring), 0012 (package). |

In plain language: starting the app is one 133-line constructor, and the loader is built from 14 positional arguments. This proposal changes neither the window nor any behaviour. The loader's arguments get names at the call site. The loader gains one public `start()` that does its own startup, so the shell stops calling four of its private methods. The shell's constructor becomes a short list of named steps, each saying what it needs and what it provides. The dialog–loader cycle stays, because it cannot be removed. It is stated once, in one place. The one real decision is how to make the 14 arguments readable: names (recommended) or two small bundles of arguments (§3).

## 1. Background and Goal

Issue #208 asks for the startup wiring to read plainly. "Done" means a reviewer can read `__init__` top to bottom as an ordered list of steps; can find every reference that is resolved late by searching for one thing; and can read the loader's call site without counting arguments.

Modularity question: this change creates no component and moves no boundary. It alters one constructor contract (the loader's, to keyword-only) and adds one public method to the loader. It adds no coupling across any existing boundary; it removes the shell's reach into four private loader names.

## 2. Current State (measured on main `be300eda`)

Full map, line citations and the parameter sort are in Appendix A. The load-bearing facts:

- `LibraryApp.__init__` is 133 lines (61–193), and `_build` is 123 (234–356) [RAN].
- The loader's constructor takes 14 positional arguments (`library_loader.py:65–68`), is called once (`library_visualizer.py:174`), and is never called by any headless test [CODE].
- Three references are bound before their target exists (L1/L2, L3, L4). Only L1 and L2 are lambdas the brief knew of. They form a real cycle between the dialog and the loader.
- The shell calls four loader methods by private name (184, 185, 193, 167).
- Five loader attributes (`_snapshot_*`) are first assigned in `_loaded` (632–636) and read with `getattr` defaults (476–480).
- The song page and preview player are built at 326–333 before the table and the loader; nothing there is late-bound. Their glue (`_open_song_page`, `_play_preview`, `_stop_preview`, `_song_media`, about 50 lines at 529–579) stays in the shell.

## 3. The Decision

**Option A — an assembly function.** A `build_app(root)` function in a new module builds the pieces in order and hands them to `LibraryApp`.
- Contract change: `LibraryApp(root)` becomes `LibraryApp(parts)`. That is `main()` plus 30 test call sites.
- Cost: a new module (new entries in the `TK_MODULES` pin in `tests/test_layer_enforcement.py` and in `WINDOW_SOURCES`), and the widget factories have to be passed in or duplicated.
- It removes no late binding; the cycle and L4 move into the new module.
- **Not the recommendation:** the biggest blast radius for the least reading gain.

**Option B — bundle the loader's arguments.** Two small objects: `LoaderView(status, progress, load_button, set_sync_menu_state)` and `LoaderHooks(on_library_changed, on_nothing_loaded, save_settings, report_discarded_settings)`. The constructor drops from 14 to 8.
- Cost: two new types that exist only to carry arguments. A reader must learn them, and the call site still has to build them in the right order.
- It is the right shape if the loader keeps gaining inputs.
- **Not the recommendation, but close.** If the owner prefers fewer parameters over named ones, this is the alternative.

**Option C (recommended) — keep the order, make it plain in place.**
- The loader's 14 inputs become keyword-only, documented in five groups.
- The loader gains a public `start()`, so it owns its startup.
- The shell's `__init__` becomes named steps.
- The two dialog lambdas become named delegates, and the late-bound references are listed once.

It matches Option B's call-site clarity with no new types, and it is the only option that also shortens `__init__` and removes the private-name access. The cost is a mild contract change to the loader.

**Also considered: a two-phase loader** (built early, `attach_view()` later). It would remove the dialog's lambdas but leaves the cycle on the loader's side and a half-built object that needs guards. Rejected.

## 4. Recommended Design in Detail (Option C)

**Boundary.** No component moves. The only contracts that change are the loader's constructor (keyword-only) and one new public method on the loader. `DataPathsDialog`, `CourseBuilder`, `AdvancedSearch`, `DistributionPanel`, `LibraryFilter`, `LibraryTable`, `SongPage` and `LibraryApp(root)` keep their contracts. The 0009 pattern is untouched.

**LibraryLoader constructor.** The same 14 inputs, keyword-only, documented in five groups:
1. Data: `snapshot_store`, `cache_var`, `stats_var`.
2. The window the loader drives: `status`, `progress`, `load_button`, `set_sync_menu_state`.
3. What the loader tells the shell: `on_library_changed`, `on_nothing_loaded`, `report_discarded_settings`, `save_settings`.
4. The dialog it talks to, `dialog`, and `had_saved_paths`, which is forwarded to the dialog's first-run check.
5. `root`, for scheduling.

The five `_snapshot_*` counters are declared in `__init__` with the defaults the `getattr`s use today (`0, 0, 0, False, 0`).

**`LibraryLoader.start()`** (new, public, no arguments). It runs the shell's lines 183–185 and 190–193, in the same order: the two path traces, `after(75, _poll_load_results)`, the "Loading saved library…" status and progress start when the snapshot file exists, then `after(50, _load_initial_snapshot)`. The file check uses `self.snapshot_store.snapshot_path` (`library_stores.py:84`), the same path the shell derives at 77. The shell calls `_report_discarded_settings()` first, then `start()`, so the order is unchanged.

**Public name.** `_current_paths_match_loaded` becomes `paths_match_loaded` (5 source lines, 9 test lines), since the shell and the dialog call it across the boundary. The other three private names stay private; after `start()` nothing outside the loader calls them (Q3).

**Shell `__init__`** becomes named private steps, each with a one-paragraph docstring stating *needs* and *provides*:
1. `_init_window()` (62–71)
2. `_init_stores()` (72–84)
3. `_init_variables()` (85–119)
4. `_declare_late_state()` (120–155), grouped by the step that fills each name, now including `course_geometry`, `advanced_search_geometry` and `_file_menu`
5. `_init_dialog()` (156–167)
6. `_style()` then `_build()`
7. `_init_loader()` (170–182), ending with `self._loader.start()`

Two dialog lambdas are replaced by `load_callback=self.load_data` (the existing delegate at 633) and a one-line `_paths_match_loaded` delegate. A comment above step 5 states the cycle once and lists the only places that read `self._loader` after construction: `load_data`, `sync_scores`, `export_csv` and `_paths_match_loaded`. The stale comment at 127–129 is corrected.

**Song page and preview player.** They appear as one named stage inside `_build` (326–333) and need no change. They are built before the table and the loader, so they add no late-bound reference.

**Legibility sentence.** The loader is the background data engine; it is given its stores and variables, the window parts it drives, and the callbacks it reports through, and it starts itself with `start()`.

## 5. What Does Not Change

- Behaviour, window layout and focus order; the startup order of effects.
- The order of the constructions in `_build`, including 0005 Q5's table-frame callable (L4).
- Settings keys and file formats; `HEADERS`; the snapshot schema.
- `DataPathsDialog`'s constructor and its first-run contract (0009), unless the owner decides Q2.
- The guards a test pins (T3, T4, T7, T8, T9, T10), and every existing test's expectations.
- The widget factories; the shell's song-page glue.

## 6. Test Plan (for the implementation PRs)

Two PRs, loader first.

**PR 1 — the loader.**
- First commit, tests only: a headless test that builds the real loader through its constructor by keyword, with Mocks. It passes on the current code (a positional signature already accepts keywords) and must pass again after the change. The loader module imports without Tkinter, so the ubuntu job runs it.
- Then the keyword-only constructor, the public rename and the declared counters. `start()` arrives with its own order-pinning test (the two traces, `after(75)`, status and progress when the snapshot file exists, `after(50)`), which cannot pass before `start()` exists.
- The tests-only `make_loader` helper replaces `_make_wired_loader` and `make_instance` (T2). The 37 bare loader tests are untouched.
- Acceptance: the full suite gives the same results as before the change on CI, with the live tests green on `windows-ui`.

**PR 2 — the shell.** Named steps, the two delegates, the declared late state, the comment fixes. No test changes except that `LoaderDelegationTests` gains the `_paths_match_loaded` delegate.

**Owner's Windows smoke (live; I cannot run it).** Launch with a saved snapshot (status shows "Loading saved library…" then the snapshot line). Launch with no snapshot and no saved paths (first-run dialog). Launch with an unreadable `settings.json` (the note appears once). Press Load in the dialog with valid and invalid paths. Run a sync. Edit a path while a snapshot is loaded (the differ note appears in the dialog). Quit and relaunch.

Also update: the README architecture paragraph if it names the loader's startup, and the proposals README index.

## 7. Open Questions for Reviewers

- **Q1.** Option C over Option B? **Recommend C.** It is a close call on the constructor alone; the `start()` and named steps decide it.
- **Q2.** Move `had_saved_paths` into the dialog's constructor? **Recommend no, not in this change.** It would alter the accepted 0009 first-run contract for the sake of one parameter.
- **Q3.** Rename `_current_paths_match_loaded` to `paths_match_loaded`? **Recommend yes.** It is the only private name that must be crossed after `start()`.
- **Q4.** Apply the "remove a guard only when no test relies on it" rule, with no test rewrites? **Recommend yes.**
- **Q5.** The four repeated "stop the bar, reset it to indeterminate" stanzas in the loader (498–501, 533–534, 610–613, 625–628) and the song-page glue in the shell. Out of scope here. **Recommend separate issues.**

---

*Written by Claude (Sonnet 5.5). No other model reviewed this draft.*

**Where it could be cut.** §2 repeats Appendix A and can shrink to a pointer. §6's smoke list and Q5 can go to the implementation PRs. If the owner picks Option B, §4 becomes about half as long, and the `start()` and named-steps material moves to a separate follow-up.

---

# Appendix A — Investigation behind this proposal

Paths are relative to `itgmania_library/` unless they begin with `tests/` or `docs/`. Read at main `be300eda`; sandbox Python 3.13.18 with no Tkinter (the owner runs 3.14.7 on Windows 11). Appendix A can be dropped when the proposal is filed as Accepted; §2 carries the load-bearing facts.

## A0. The brief's numbers, checked at `be300eda`

| Claim | Measured | Tag |
|---|---|---|
| Shell is 755 lines (issue says 660) | 755 | [CODE] `wc -l library_visualizer.py` |
| `LibraryApp.__init__` is 126 lines, 51–176 | **Stale.** `def` at 61, ends at 193: **133 lines** | [RAN] AST script, Python 3.13.18 |
| `LibraryApp` class | 55–741, 687 lines, 31 methods | [RAN] same script |
| `_build` | 234–356, 123 lines | [RAN] |
| `LibraryLoader` is 667 lines | 667 (class 38–667) | [CODE] |
| Loader `__init__` takes 14 positional parameters, 65–68 | Confirmed; the whole `__init__` is 65–92 | [RAN] |
| "About ten Tk variables" | 11 attributes: 7 `StringVar`, 2 `BooleanVar`, 2 dicts of `BooleanVar` (`column_visibility`, `group_visibility`), at 87–118. `status` (239) and `count_label` (318) are made later, in `_build`. | [CODE] |
| "About twenty-five attributes declared None" | **21**, at 123–155: 18 filled by `_build`, 1 filled by `__init__` itself (`_loader`, 174), 2 filled at runtime (`_song_media`, `about_window`). **3 more are never declared at all**: `course_geometry` (247), `advanced_search_geometry` (255), `_file_menu` (397). | [RAN] AST script |

The issue text carries the same stale `51-176` range. It was verified against `3809e02`, before the song-page wiring landed.

## A1. The wiring, in order

`__init__` is lines 61–193. Each row says what is built, what it needs, and whether anything is bound before its target exists.

| # | Lines | Step | Needs | Notes |
|---|---|---|---|---|
| 1 | 62–71 | Root: title, DPI scale (67), geometry, minsize, background | `root` | `_dpi_scale` is first set here. A class default `1.0` (59) covers bare test instances. |
| 2 | 72–77 | `settings_path` (443–448 wrapper), `SnapshotStore` | the path | `library_cache_path` (450–452) is derived from `settings_path`. |
| 3 | 83–84 | `SettingsStore.load()` → `saved_settings` | the path | A read failure is parked on `last_read_error` and reported later: 182, and loader 109. |
| 4 | 85–119 | 11 variable attributes, seeded from `saved_settings` | `saved_settings` | A settings-to-variables block, inline. |
| 5 | 120–155 | 21 attributes set to `None` | – | Comments name who fills each. |
| 6 | 161–167 | `DataPathsDialog` | root, the two path vars, `_save_settings`, `_button`, `_entry`, `_dpi_scale` | **Late-bound lambdas** at 163 and 167 reach `self._loader`, which is `None` until 174. |
| 7 | 168 | `_style()` | – | |
| 8 | 169 | `_build()` | see below | |
| 9 | 173–181 | `LibraryLoader(14 positional)` | `status` (239), `load_button` (282), `progress` (348), dialog (161) | The only call site. Built after `_build` because it needs three widgets made inside it. |
| 10 | 182 | `_report_discarded_settings()` | `status`, `_settings_store` | |
| 11 | 183–185 | Path traces (184), `after(75, _poll_load_results)` (185) | loader | Calls loader methods by their **underscore** names. |
| 12 | 190–193 | "Loading saved library…" status and progress start; `after(50, _load_initial_snapshot)` | loader | Asks `library_cache_path.is_file()` (190), a second derivation of a path the `SnapshotStore` already holds (`library_stores.py:84`). The loader stops the bar (`library_loader.py:105`): one indicator, two owners. |

`_build()` (234–356), in order:

| Lines | Built | Dependency notes |
|---|---|---|
| 235–241 | Top bar; `status` StringVar made at 239 | Consumed by `CourseBuilder` (248) and the loader. |
| 247–252 | `CourseBuilder` | Takes `_selected_rows_for_course` (525–527) and `_library_rows_for_course` (581–583). Both read `self._table`, which is `None` until 338. **Named delegates, but late-bound.** |
| 255–260 | `AdvancedSearch` | – |
| 262 | `WM_DELETE_WINDOW` → `_close_app` | Both components it touches already exist. |
| 266–285 | Search entry, three combos (269–274), `load_button` (282), Export (284), Build course (285) | Buttons bound to `load_data`, `export_csv`. These read `self._loader`, which is `None` until 174. Safe because Tk callbacks cannot run before `mainloop` [INFERRED]. |
| 289–291 | `LibraryFilter` | Installs its own variable traces in its constructor (`library_filter.py:66, 68`). |
| 298–307 | `DistributionPanel` | Takes the filter's `filter_rows` and `apply_chart_filter`, and `_save_settings`. |
| 310–315 | `dist_button`, `content_frame`, `build_panel(..., lambda: self.table_frame)` | **Late-bound lambda** (315). `table_frame` is made at 316. Deliberate and accepted: proposal 0005 Q5 (`docs/proposals/0005-distribution-panel-split.md:608–614`). |
| 316–318 | `table_frame`, `count_label` | – |
| 326–333 | `SongPreviewPlayer`, `SongPage` (0011 stages 3–4) | Built before the table and the loader, so nothing here is late-bound. Its callbacks `_play_preview`, `_stop_preview` (559–579) and `_open_song_page` (529–557) live in the shell. |
| 338–347 | `LibraryTable`, then `_filter.subscribe(_table.refresh_table)` | Needs the filter, `panel.show_rows`, `_save_settings`, `on_open_row`. |
| 348–349 | `progress` | Made last, needed by the loader. |
| 350–356 | Footer, then `_build_menubar()` (385–441) | `_file_menu` is first assigned at 397. Menu commands reach `self._table` (413, 420, 424) after it exists. |

### Everything bound before its target exists

| ID | Where | Binds to | Form | Verdict |
|---|---|---|---|---|
| L1 | 163 | `self._loader.load_data` | lambda | Known. `load_data` (633–635) already exists as a shell delegate to the same call. |
| L2 | 167 | `self._loader._current_paths_match_loaded` | lambda | Known. It also reaches an underscore method. |
| L3 | 248–249 | `self._table` (via 525, 581) | named delegates | **New finding.** Same pattern, not mentioned in the brief. |
| L4 | 314–315 | `self.table_frame` | lambda | **New finding.** Accepted design (0005 Q5); this proposal leaves it alone. |
| L5 | 278, 282, 284, 389–393 | `self._loader`, `self._data_paths_dialog` at click time | bound methods | Safe only because nothing fires before `mainloop` [INFERRED]. |
| L6 | 164, 306, 344, 278 | `_save_settings` reads `self._table` (488, returns early if `None`), `course_geometry` (511) and `advanced_search_geometry` (514), both assigned in `_build` | bound method | The `None` guard is also what keeps the undeclared geometry attributes from being read too early [INFERRED]. No test sets `_table = None`, and I could not find a production call that reaches it; its purpose is [UNVERIFIED]. |

**The one true cycle.** The dialog needs the loader's `load_data` and path check (L1, L2). The loader needs the dialog's `open`, `set_note`, `paths_changed` and `maybe_show_first_run` (`library_loader.py:117, 160, 253, 376`). Two objects that call each other cannot both be fully built first. One late binding is unavoidable. The aim is to make it explicit, not to remove it.

**Loader methods the shell calls by private name:** `_source_paths_changed` (184), `_poll_load_results` (185), `_load_initial_snapshot` (193), `_current_paths_match_loaded` (167). The loader's real startup API is underscore-named.

**Comment that is no longer true.** Lines 127–129 say the loader is built "before the filter's traces are installed". The filter installs its traces inside `_build` (289), before the loader exists. No trace callback reads `_loader`, so nothing breaks, but the stated reason is wrong [CODE].

## A2. The loader's 14 parameters, sorted

| # | Parameter | Group | Read at (`library_loader.py`) | Constructor? |
|---|---|---|---|---|
| 1 | `snapshot_store` | store | 122, 322, 474 | Yes. A true dependency. |
| 2 | `cache_var` | shared variable | 122, 249, 372 | Yes |
| 3 | `stats_var` | shared variable | 122, 227, 249, 372 | Yes |
| 4 | `status` | shared variable (the status line) | 28 sites | Yes |
| 5 | `progress` | widget | 15 sites | Yes |
| 6 | `load_button` | widget | 261, 607, 622 | Yes |
| 7 | `set_sync_menu_state` | callback into a widget | 267, 379, 497, 532, 609, 624 | Yes |
| 8 | `on_library_changed` | callback | 523, 645 | Yes |
| 9 | `on_nothing_loaded` | callback | 146 only | Yes |
| 10 | `dialog` | sibling component | 117, 160, 253, 376 | Yes. This is one end of the cycle. |
| 11 | `save_settings` | callback | **255 only** | Yes (see below) |
| 12 | `root` | framework handle | **567 only** (`after`), plus `start()` if added | Yes |
| 13 | `report_discarded_settings` | callback | **109 only** | Yes |
| 14 | `had_saved_paths` | flag | **117 only**, forwarded to the dialog | Yes, today (Q2) |

Groups: store 1, variables 3, widgets 2, callbacks 5, sibling 1, framework 1, flag 1.

What would break if a group moved:

- **Widgets and `status`.** They come from `_build` (239, 282, 348), so the loader cannot be built earlier. A later `attach_view()` would let the loader be built first and remove the dialog's two lambdas. But it leaves a half-built loader whose methods need guards, which is exactly the "None until filled" problem. Rejected (§3).
- **`save_settings`.** It is called at 255, after the path check at 249–254. The shell cannot save first without repeating the check.
- **`report_discarded_settings`.** It runs after the snapshot load rewrites the status line (loader 105–109). Only the loader knows when that is.
- **`had_saved_paths`.** The loader is only a courier; it never uses the flag. It belongs with the dialog, but the first-run contract it feeds (`maybe_show_first_run(snapshot_loaded, had_saved_paths)`) was settled in proposal 0009. I left it alone (Q2).
- **Positional order.** Three adjacent callables (`set_sync_menu_state`, `on_library_changed`, `on_nothing_loaded`, 177–178) have different signatures. Swapping two would not fail until the callback ran.

## A3. "The wiring bends around the tests" — what is true

**Verdict.** Partly. The construction order is shaped by Tk (widgets must exist first) and by the dialog–loader cycle, not by tests. The tests have shaped the defensive reads, and the test setup copies the wiring by hand.

Counts [CODE, from grep]: 20 `getattr(self, …)` reads (shell 6, loader 11, dialog 3). `is not None` component guards at `library_visualizer.py:367, 371, 586–589, 656, 670`. Bare-instance construction in tests: 37 `LibraryLoader`, 38 `LibraryApp`, 2 `DataPathsDialog`. **Zero tests call `LibraryLoader(...)`.** The 14-argument constructor is executed only by live `LibraryApp(root)` tests (28 in `tests/test_library_visualizer.py`, 2 in `tests/test_ui_distribution.py`), which need Tk.

| # | Case | What the test needs | What the wiring does | Proposal |
|---|---|---|---|---|
| T1 | Loader `getattr` defaults: 168, 171, 172, 224, 360, 363, 476–480; Mock-status `isinstance` guards: 204–208, 239–243 | A bare loader with only the attributes that test sets (`tests/test_library_loader.py:85` onward, 37 sites) | `__init__` always sets all of these except the five `_snapshot_*` counters (first assigned at 632–636). A sync cannot start before a load has set them (366) [INFERRED]. | **Declare the five counters in `__init__`** (same defaults as the `getattr`s). Keep the other guards for now. |
| T2 | `_make_wired_loader` (`tests/test_library_loader.py:1579–1609`) and `make_instance` (395–419) | A loader wired to a bare app, and a real dialog pointing at a bare loader | Hand-copies the 14 assignments, the 9 internal ones, and the dialog lambda | **Isolate.** One tests-only `make_loader(**overrides)` that calls the real keyword constructor. Constructor changes then break one helper, not several copies. |
| T3 | `_on_library_changed` guards: `getattr(self, "song_page")` (655), `course_builder is not None` (670) | `CourseReloadNotificationTests` (`tests/test_library_visualizer.py:1257–1291`); line 1282 pins "no builder yet, no error" | Both components are built before the loader exists, so the guards cannot fire in production [INFERRED] | **Keep.** A test pins them. `_run_loaded` (1261–1271) also sets nine attributes the method never reads, left over from before the filter split [INFERRED]. Tidy in a tests-only follow-up. |
| T4 | `_play_preview` / `_stop_preview` `getattr` (568, 571, 577) | Tests at `tests/test_library_visualizer.py:1823–1856` cover the play/stop glue, including "no player → `None`" (1833) | `_preview_player` is set at 326, before any callback can run | **Keep.** Pinned. `_song_media` is the one genuinely runtime-`None` value here (556, 658). |
| T5 | `_report_discarded_settings` `getattr(self, "_settings_store")` (477) | The tests I read (`tests/test_library_visualizer.py:555–572`, `tests/test_library_loader.py:502–507`) all set `_settings_store` | The store is made at 83, before anything calls this | **Remove if the suite stays green without touching a test.** |
| T6 | `_set_sync_menu_state` `getattr(self, "_file_menu")` (685) | The test sets `_file_menu` (`:1318`) | `_file_menu` is first assigned in `_build_menubar` (397) and is not declared in `__init__` | Declare `_file_menu = None` with the other late attributes. The guard goes only if the suite stays green without it (rule below). |
| T7 | `_close_app` / `_dialog_is_open` `None` checks (367, 371, 586–589) | `tests/test_library_visualizer.py:1689–1706` pin "no course builder" | The components are now built eagerly; the comment at 139–143 still describes the older lazy pattern | **Keep.** Pinned. |
| T8 | Dialog `getattr` ×3 (`data_paths_dialog.py:133, 140, 150`) | `tests/test_data_paths_dialog.py:84, 126` build a bare dialog and set only some attributes | `__init__` sets all three (67–69); `close()` resets them to `None` (156–158), so a `None` check is real, but `getattr` also tolerates bare instances | **Keep.** Pinned. |
| T9 | `_dpi_scale = 1.0` class default (59; also `course_builder.py:48`, `advanced_search.py:41`, `distribution_panel.py:80`) | Bare instances have no window to measure | Shadowed by `__init__` at 67 | **Keep.** One line each. |
| T10 | `_settings_file_path` wrapper (443–448) | 20 `patch.object(app.LibraryApp, "_settings_file_path", …)` sites in two live-test files | Indirection only. The comment at 446 says "seventeen"; the count is 20. | **Keep.** Correct the number if that block is edited anyway. |

**Rule for the implementation PRs.** A guard that production cannot reach is removed only when no test relies on it. A guard a test pins stays. No existing test is rewritten for this change.

## A4. What I ran

- [RAN] `python3 -m unittest discover -s tests`, Python 3.13.18: **777 tests, 1 failure, 56 errors, 72 skipped.** This is not a green run and it is not a baseline for the app: the sandbox has no Tkinter.
  - 55 errors are `AttributeError: None does not have the attribute 'Treeview'` (53 in `test_library_table`, 2 in `test_library_loader`), which is Tkinter being absent.
  - 1 error and 1 failure are in `test_ui_distribution` (the lazy-matplotlib loader tests). Matplotlib 3.11.2 imports here, so I have not isolated the cause.
  - The repo was clean afterwards (`git status`: 0 changes).
- [RAN] An AST script (Python 3.13.18) for the line spans and attribute lists in A0, A1 and A3.
- Not run: the app window, and every live test. For every claim about runtime order I read the source. The owner's Windows smoke is part of the test plan (§6).
