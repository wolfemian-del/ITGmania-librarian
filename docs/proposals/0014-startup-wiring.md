# Implementation Proposal: Make the startup wiring plain

| | |
|---|---|
| **Status** | Accepted — approved by the owner on 2026-11-18, with the review resolutions below |
| **Author** | Claude (Sonnet 5.5) |
| **Date** | 2026-11-17; revised 2026-11-18 |
| **Base** | main `048ca38` (PR #226 merged). The first draft was measured at `be300eda`. |
| **Related** | Issue #208 (open); PR #225; proposals 0005 (Q5, the sibling-frame callable), 0009 (loader and dialog contracts), 0011 stages 3–4 (song page and player wiring), 0012 (package). |

## Review resolutions (2026-11-18)

- **Q1: Option C, as recommended.** Keyword-only loader inputs, a public `start()` and named startup steps. Option B stays available as a later step.
- **Q6: named shell delegates, as recommended.** Option D (explicit attach) is not taken, because it would change the 0009 dialog contract.
- **Q2 to Q5: the recommendations stand.** No reviewer disagreed, and the owner accepted the proposal as written.

## Revision 1 (2026-11-18, from the five reviews of PR #225)

Five reviews came in on head `207290d`: a design review (adversary lane), ChatGPT-6 (executed verification), Muse (cold read and process), Codex (tests) and Greptile (automated). I checked each finding against the code at `048ca38` and ran what could be run without a window. Option C is still the recommendation. The owner's choice between C, B and the new Option D is open (Q1, Q6). What changed:

- **Re-based and re-measured at `048ca38`.** Shell, dialog and stores citations are unchanged. Loader citations after line 300 moved by +7 (PR #223). In `tests/test_library_loader.py`, citations moved +22 after line 328 and +66 after line 760. Bare loader constructions in tests are now 38 (37 at `be300eda`).
- **Wording corrected.** L5 no longer lists line 278 (a settings-save callback, already L6). "Never declared at all" is now "not predeclared in `__init__`". "37 bare loader tests" now counts construction sites. "The 0009 pattern is untouched" is now "the 0009 construction order is kept; its two lambdas become named delegates". "Cannot be removed" is gone (see Option D). "Matches Option B's call-site clarity" is gone. "Exactly four places" is now four methods, to be confirmed by a grep in PR 2.
- **Added.** Option D (tie the cycle with an explicit attach) and Q6. `start()` taking over the startup status text and progress start is now stated as an ownership move (§4), with the order constraints listed. 0009's loader inputs are compared with today's (§4). T2 covers three helpers and three modes. PR 1 now carries the shell lines that call the loader (Greptile, Codex). PR 2 gains a headless wiring test, because swapping two adjacent callbacks fails no test today (ChatGPT-6). Appendix B is the owner's smoke list, widened from Codex's gaps.
- **Trimmed.** §2 is key facts only. The two-phase loader is one line. The song-page paragraph moved into §5. The "Where it could be cut" note is gone. The plain-language paragraph is shorter and glosses its terms.
- **Not adopted.** Codex's reading that the sync-flag defaults and the song-page `getattr` are unpinned: removing them fails 2 and 7 tests (A4). Muse's "12 inputs" for 0009: it has 12 numbered items naming 14 inputs (§4). Greptile's 100-character finding: Greptile withdrew it after the owner's reply, since AGENTS.md puts that limit under code rules.

In plain language: starting the app runs through one long setup routine (the shell's constructor, 133 lines), and the part that loads your library, the loader, is handed 14 unnamed values in a fixed order. This proposal changes nothing you can see or do. It gives the 14 values names where they are handed over, gives the loader a public `start()` so the shell stops reaching into its private parts, and splits the long setup routine into short named steps. One knot stays: the Data paths dialog and the loader each need the other, so one must be built first and handed a stand-in for the other. The proposal states that once, in one place. The real decision for you is how to make the 14 values readable: names (recommended), two small bundles (Option B), or a different way to tie the knot (Option D).

## 1. Background and Goal

Issue #208 asks for the startup wiring to read plainly. "Done" means a reviewer can read `__init__` top to bottom as an ordered list of steps; can find every reference that is resolved late by searching for one thing; and can read the loader's call site without counting arguments.

Modularity question: this change creates no component and moves no boundary. It alters one constructor contract (the loader's, to keyword-only) and adds one public method to the loader. It adds no coupling across any existing boundary; it removes the shell's reach into four private loader names.

## 2. Current State (measured on main `048ca38`)

Full map, line citations and the parameter sort are in Appendix A. The load-bearing facts:

- `LibraryApp.__init__` is 133 lines (61–193), and `_build` is 123 (234–356) [RAN].
- The loader's constructor takes 14 positional arguments (`library_loader.py:65–68`), is called once (`library_visualizer.py:174`), and is never called by any headless test. Swapping two adjacent callbacks at 177–178 fails no test [RAN by ChatGPT-6].
- Four references are bound before their target exists: the dialog's two lambdas (L1, L2, a real cycle with the loader), the course builder's two delegates that read `self._table` (L3), and the table-frame callable (L4, accepted in 0005 Q5).
- The shell calls four loader methods by private name (167, 184, 185, 193).
- Five loader attributes (`_snapshot_*`) are first assigned in `_loaded` (639–643) and read with `getattr` defaults (483–487).

## 3. The Decision

**Option A — an assembly function.** A `build_app(root)` function in a new module builds the pieces in order and hands them to `LibraryApp`.
- Contract change: `LibraryApp(root)` becomes `LibraryApp(parts)`. That is `main()` plus 30 test call sites.
- Cost: a new module (new entries in the `TK_MODULES` pin in `tests/test_layer_enforcement.py` and in `WINDOW_SOURCES`), and the widget factories have to be passed in or duplicated.
- It removes no late binding; the cycle and L4 move into the new module.
- **Not the recommendation:** the biggest blast radius for the least reading gain.

**Option B — bundle the loader's arguments.** Two small objects: `LoaderView(status, progress, load_button, set_sync_menu_state)` and `LoaderHooks(on_library_changed, on_nothing_loaded, save_settings, report_discarded_settings)`. The constructor drops from 14 to 8.
- The call site shows the roles without counting names, and B scales if the loader keeps gaining inputs. `start()` and the named steps do not depend on this choice and could ride with B; what separates B from C is only the constructor's shape.
- Cost: two new types that exist only to carry arguments. A reader must learn them, and the call site still has to build them in the right order.
- **Not the recommendation, but a real alternative.** The design review rated B the clearer call site and the clearer test shape (Q1).

**Option C (recommended) — keep the order, make it plain in place.**
- The loader's 14 inputs become keyword-only, documented in five groups.
- The loader gains a public `start()`, so it owns its startup.
- The shell's `__init__` becomes named steps.
- The two dialog lambdas become named delegates, and the late-bound references are listed once.

Keyword names make each argument say what it is and end the swap hazard, with no new types. The call site stays 14 lines long. Moving to B later is a small step from here. The cost is a mild contract change to the loader.

**Option D — tie the cycle after construction.** Build the dialog with its two callables left empty, build the loader, then hand the dialog the loader's methods in one explicit step, before anything can run. The cycle is then one visible call instead of two lambdas, and neither object is half-built for its own job. This is a defensible alternative.
- Not the recommendation: the dialog's constructor contract is settled by 0009 (`load_callback` and `paths_match_loaded` as inputs), and D would change it. D also does not remove the late step; it moves it from two named shell methods into the dialog's contract. Until the attach, the dialog would fail if reached (`data_paths_dialog.py:101, 167, 232`); C's delegates fail the same way if called before the loader exists (an `AttributeError` on `None`). Both rely on nothing firing before `mainloop` [INFERRED] (Q6).

**Also considered: a two-phase loader** (built early, `attach_view()` later). It leaves a half-built loader whose methods need guards. Rejected.

## 4. Recommended Design in Detail (Option C)

**Boundary.** No component moves. The contracts that change are the loader's constructor (keyword-only) and one new public method on the loader. `DataPathsDialog`, `CourseBuilder`, `AdvancedSearch`, `DistributionPanel`, `LibraryFilter`, `LibraryTable`, `SongPage` and `LibraryApp(root)` keep their contracts. The 0009 construction order is kept (dialog first, loader second, the dialog's two callables resolved late); only the lambdas' form changes.

**LibraryLoader constructor.** The same 14 inputs, keyword-only, documented in five groups:
1. Data: `snapshot_store`, `cache_var`, `stats_var`.
2. The window the loader drives: `status`, `progress`, `load_button`, `set_sync_menu_state`.
3. What the loader tells the shell: `on_library_changed`, `on_nothing_loaded`, `report_discarded_settings`, `save_settings`.
4. The dialog it talks to, `dialog`, and `had_saved_paths`, which is forwarded to the dialog's first-run check.
5. `root`, for scheduling.

0009 §4 listed 14 inputs in 12 numbered items. Today's 14 differ by four names: 0009's `on_scores_sync_failed` and `on_load_failed` are no longer inputs, and `report_discarded_settings` and `had_saved_paths` were added after 0009.

The five `_snapshot_*` counters are declared in `__init__` with the defaults the `getattr`s use today (`0, 0, 0, False, 0`). The `getattr` reads stay, because two tests build bare instances that rely on them (A4).

**`LibraryLoader.start()`** (new, public, no arguments). It runs the shell's lines 183–185 and 190–193 in the same order: the two path traces, `after(75, _poll_load_results)`, the "Loading saved library…" status and progress start when the snapshot file exists, then `after(50, _load_initial_snapshot)`. The file check uses `self.snapshot_store.snapshot_path` (`library_stores.py:84`), replacing the shell's second derivation of the same path (`library_cache_path`, 190).

This is an ownership move. The loader already writes every other status line and stops the bar (`library_loader.py:105`); after the change it also starts the bar and writes the first status line, so one object owns the indicator. The shell keeps the decision to start the engine and the widgets it passes in. The order constraints to preserve, each pinned by `start()`'s order test or the smoke list (Appendix B):
1. `_report_discarded_settings()` runs before `start()`. When a snapshot exists, `start()` then replaces that status with "Loading saved library…", and the loader reports the discarded settings again after the restore (`library_loader.py:109`).
2. The traces come first, then the 75 ms poll, then the snapshot check, then the 50 ms initial load, which is scheduled whether or not a snapshot exists.

**Public name.** `_current_paths_match_loaded` becomes `paths_match_loaded` (5 source lines, 9 test lines), since the shell and the dialog call it across the boundary. The other three private names stay private; after `start()` nothing outside the loader calls them (Q3).

**Shell `__init__`** becomes named private steps, each with a one-paragraph docstring stating *needs* and *provides*:
1. `_init_window()` (62–71)
2. `_init_stores()` (72–84)
3. `_init_variables()` (85–119)
4. `_declare_late_state()` (120–155), grouped by the step that fills each name, now including `course_geometry`, `advanced_search_geometry` and `_file_menu`
5. `_init_dialog()` (156–167)
6. `_style()` then `_build()`
7. `_init_loader()` (170–182), ending with `self._loader.start()`

The two dialog lambdas are replaced by `load_callback=self.load_data` (the existing delegate at 633) and a one-line `_paths_match_loaded` delegate. A comment above step 5 states the cycle once and lists the late-bound references: the dialog pair (L1, L2), the course builder's two delegates that read `_table` (L3), and the table-frame callable (L4, left alone). After construction, `self._loader` is read by four methods: `load_data`, `sync_scores`, `export_csv` and `_paths_match_loaded`. PR 2 confirms that with a grep. The stale comment at 127–129 is corrected.

**Legibility sentence.** The loader is the background data engine: it loads the library, syncs scores and reports progress. It is given its store and shared variables, the window parts it drives, the dialog it talks to and the callbacks it reports through, and it starts itself with `start()`.

## 5. What Does Not Change

- Behaviour, window layout and focus order; the startup order of effects.
- The order of the constructions in `_build`, including 0005 Q5's table-frame callable (L4).
- The song page and preview player (0011 stages 3–4): they are built at 326–333, before the table and the loader, so nothing there is late-bound. Their glue (`_open_song_page`, `_play_preview`, `_stop_preview`, `_song_media`, about 50 lines at 529–579) stays in the shell.
- Settings keys and file formats; `HEADERS`; the snapshot schema.
- `DataPathsDialog`'s constructor and its first-run contract (0009), unless the owner decides Q2 or Q6.
- The guards a test pins, and every existing test's expectations.
- The widget factories.

## 6. Test Plan (for the implementation PRs)

Two PRs, loader first. The guard rule: a guard is removed only when no test relies on it. Under that rule two guards go, both in PR 2: the `_settings_store` `getattr` (477, with the stale comment lines that excuse it) and the `_file_menu` `getattr` (685), once `_file_menu = None` is declared. Everything else stays (A3, A4).

**PR 1 — the loader, and the shell lines that call it.**
1. First commit, tests only: a `make_loader(**overrides)` helper that builds the real loader through its constructor by keyword, with Mocks for the store and variables. It needs an optional `app=` (binds `on_library_changed` to the app's real handler and sets `app._loader`) and a real-dialog mode. It replaces the three hand-copies (T2). It passes on the current code, because the 14 parameters already accept keywords [RAN by ChatGPT-6], and the loader module imports without Tkinter, so the ubuntu job runs it. Until the rename it uses the old private name; the rename commit edits that one line. The 38 bare loader constructions are untouched.
2. Then the keyword-only constructor, the declared counters, the public rename, and `start()` with its own order-pinning test (the two traces, `after(75)`, status and progress when the snapshot file exists, `after(50)`), which cannot pass before `start()` exists.
3. The shell edits that keep the app starting, in the same PR: the call site at 174–181 converted to keywords; lines 183–185 and 190–193 replaced by `self._loader.start()` after `_report_discarded_settings()`; the lambda at 167 pointed at `paths_match_loaded`. Without them the constructor change raises `TypeError` at startup, and every live test inherits it.
- Acceptance: the full suite gives the same results as before the change on CI, with the live tests green on `windows-ui`.

**PR 2 — the shell, based on PR 1.** Named steps, the two delegates, the declared late state, the two guard removals, the comment fixes. Tests: `LoaderDelegationTests` gains the `_paths_match_loaded` delegate, and a headless wiring test builds a bare shell with Mock parts, calls `_init_loader()` and checks that each loader input is the shell attribute meant (for example `on_library_changed` is `_on_library_changed`). The author swaps two arguments in the sandbox and records that the test fails. Keywords already end the positional swap; the test pins the name-to-attribute mapping. No existing test is rewritten.

**Owner's Windows smoke (live; I cannot run it).** Appendix B.

Also update: the README architecture paragraph if it names the loader's startup, and the proposals README index.

## 7. Open Questions — Resolved

- **Q1.** Option C over Option B? **Recommend C**, on cost, and because B can follow from it. The design review preferred B for call-site clarity; if the owner values that most, B is a sound choice, and `start()` and the named steps still apply.
- **Q2.** Move `had_saved_paths` into the dialog's constructor? **Recommend no, not in this change.** It would alter the accepted 0009 first-run contract for the sake of one parameter.
- **Q3.** Rename `_current_paths_match_loaded` to `paths_match_loaded`? **Recommend yes.** It is the only private name that must be crossed after `start()`.
- **Q4.** Apply the "remove a guard only when no test relies on it" rule, with no test rewrites? **Recommend yes.**
- **Q5.** The four repeated "stop the bar, reset it to indeterminate" stanzas in the loader (505–508, 540–541, 617–620, 632–635) and the song-page glue in the shell. Out of scope here. **Recommend separate issues.**
- **Q6.** Keep the two dialog callables as named shell delegates (C), or tie the cycle with an explicit attach after both objects exist (Option D)? **Recommend the delegates:** D changes the 0009 dialog contract and moves the late step rather than removing it.

---

*Written by Claude (Sonnet 5.5). Revision 1 folds in the reviews listed above. The first draft was filed before any other model had read it.*

---

# Appendix A — Investigation behind this proposal

Paths are relative to `itgmania_library/` unless they begin with `tests/` or `docs/`. Read at main `048ca38`; sandbox Python 3.13.18 with no Tkinter (the owner runs 3.14.7 on Windows 11). `library_visualizer.py`, `data_paths_dialog.py` and `library_stores.py` (apart from one constant) are unchanged since `be300eda`, so their citations are as first measured. Appendix A can be dropped when the proposal is filed as Accepted; §2 carries the load-bearing facts.

## A0. The brief's numbers, checked

| Claim | Measured | Tag |
|---|---|---|
| Shell is 755 lines (issue says 660) | 755 | [CODE] `wc -l library_visualizer.py` |
| `LibraryApp.__init__` is 126 lines, 51–176 | **Stale.** `def` at 61, ends at 193: **133 lines** | [RAN] AST script, Python 3.13.18; also [RAN] by ChatGPT-6, Python 3.13.5 |
| `LibraryApp` class | 55–741, 687 lines, 31 methods | [RAN] same script |
| `_build` | 234–356, 123 lines | [RAN] |
| `LibraryLoader` is 667 lines | **674** (class 38–674); 667 at `be300eda`, +7 from PR #223 | [CODE] |
| Loader `__init__` takes 14 positional parameters, 65–68 | Confirmed; the whole `__init__` is 65–92 | [RAN] |
| "About ten Tk variables" | 11 attributes: 7 `StringVar`, 2 `BooleanVar`, 2 dicts of `BooleanVar` (`column_visibility`, `group_visibility`), at 87–118. `status` (239) and `count_label` (318) are made later, in `_build`. | [CODE] |
| "About twenty-five attributes declared None" | **21**, at 123–155: 18 filled by `_build`, 1 filled by `__init__` itself (`_loader`, 174), 2 filled at runtime (`_song_media`, `about_window`). **3 more are not predeclared in `__init__`**: `course_geometry` (247), `advanced_search_geometry` (255), `_file_menu` (397). Each is assigned later, so none is missing at run time, but a reader of `__init__` does not see them. | [RAN] AST script |

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
| L3 | 248–249 | `self._table` (via 525, 581) | named delegates | **New finding.** Same pattern as L1 and L2, not mentioned in the brief. The named steps do not remove it; the late-state comment lists it. |
| L4 | 314–315 | `self.table_frame` | lambda | **New finding.** Accepted design (0005 Q5); this proposal leaves it alone. |
| L5 | 282, 284, 389–391, 393 | `self._loader`, `self._data_paths_dialog` at click time | bound methods | Safe only because nothing fires before `mainloop` [INFERRED]. The menu commands call shell methods (`load_data`, `sync_scores`, `export_csv`, `open_data_paths_dialog`); they do not read `self._loader` themselves. |
| L6 | 164, 278, 306, 344 | `_save_settings` reads `self._table` (488, returns early if `None`), `course_geometry` (511) and `advanced_search_geometry` (514), both assigned in `_build` | bound method | The `None` guard is also what keeps the undeclared geometry attributes from being read too early [INFERRED]. No test sets `_table = None`, and I could not find a production call that reaches it; its purpose is [UNVERIFIED]. |

**The one true cycle.** The dialog needs the loader's `load_data` and path check (L1, L2). The loader needs the dialog's `open`, `set_note`, `paths_changed` and `maybe_show_first_run` (`library_loader.py:117, 160, 253, 383`). Two objects that call each other cannot both be fully built with every dependency resolved at construction. The design question is where the late step lives: in two lambdas (today), two named shell delegates (C), or one explicit attach (D).

**Loader methods the shell calls by private name:** `_source_paths_changed` (184), `_poll_load_results` (185), `_load_initial_snapshot` (193), `_current_paths_match_loaded` (167). The loader's real startup API is underscore-named.

**Comment that is no longer true.** Lines 127–129 say the loader is built "before the filter's traces are installed". The filter installs its traces inside `_build` (289), before the loader exists. No trace callback reads `_loader`, so nothing breaks, but the stated reason is wrong [CODE].

## A2. The loader's 14 parameters, sorted

| # | Parameter | Group | Read at (`library_loader.py`) | Constructor? |
|---|---|---|---|---|
| 1 | `snapshot_store` | store | 122, 329, 481 | Yes. A true dependency. |
| 2 | `cache_var` | shared variable | 122, 249, 379 | Yes |
| 3 | `stats_var` | shared variable | 122, 227, 249, 379 | Yes |
| 4 | `status` | shared variable (the status line) | 28 lines | Yes |
| 5 | `progress` | widget | 15 lines | Yes |
| 6 | `load_button` | widget | 261, 614, 629 | Yes |
| 7 | `set_sync_menu_state` | callback into a widget | 267, 386, 504, 539, 616, 631 | Yes |
| 8 | `on_library_changed` | callback | 530, 652 | Yes |
| 9 | `on_nothing_loaded` | callback | 146 only | Yes |
| 10 | `dialog` | sibling component | 117, 160, 253, 383 | Yes. This is one end of the cycle. |
| 11 | `save_settings` | callback | **255 only** | Yes (see below) |
| 12 | `root` | framework handle | **574 only** (`after`), plus `start()` if added | Yes |
| 13 | `report_discarded_settings` | callback | **109 only** | Yes |
| 14 | `had_saved_paths` | flag | **117 only**, forwarded to the dialog | Yes, today (Q2) |

Groups: store 1, variables 3, widgets 2, callbacks 5, sibling 1, framework 1, flag 1.

What would break if a group moved:

- **Widgets and `status`.** They come from `_build` (239, 282, 348), so the loader cannot be built earlier. A later `attach_view()` would let the loader be built first and remove the dialog's two lambdas. But it leaves a half-built loader whose methods need guards, which is exactly the "None until filled" problem. Rejected (§3).
- **`save_settings`.** It is called at 255, after the path check at 249–254. The shell cannot save first without repeating the check.
- **`report_discarded_settings`.** It runs after the snapshot load rewrites the status line (loader 105–109). Only the loader knows when that is.
- **`had_saved_paths`.** The loader is only a courier; it never uses the flag. It belongs with the dialog, but the first-run contract it feeds (`maybe_show_first_run(snapshot_loaded, had_saved_paths)`) was settled in proposal 0009. I left it alone (Q2).
- **Positional order.** Three adjacent callables (`set_sync_menu_state`, `on_library_changed`, `on_nothing_loaded`, 177–178) have different signatures. Swapping two does not fail until the callback runs, and no existing test catches it [RAN by ChatGPT-6]. Keyword names end this; the PR 2 wiring test pins the mapping.

## A3. "The wiring bends around the tests" — what is true

**Verdict.** Partly. The construction order is shaped by Tk (widgets must exist first) and by the dialog–loader cycle, not by tests. The tests have shaped the defensive reads, and the test setup copies the wiring by hand.

Counts [CODE, from grep and an AST script]: 20 `getattr(self, …)` reads (shell 6, loader 11, dialog 3). `is not None` component guards at `library_visualizer.py:367, 371, 586–589, 656, 670`. Bare-instance construction in tests: 38 `LibraryLoader` (37 at `be300eda`), 38 `LibraryApp`, 2 `DataPathsDialog`. **Zero tests call `LibraryLoader(...)`.** The 14-argument constructor is executed only by live `LibraryApp(root)` tests (28 in `tests/test_library_visualizer.py`, 2 in `tests/test_ui_distribution.py`), which need Tk.

| # | Case | What the test needs | What the wiring does | Proposal |
|---|---|---|---|---|
| T1 | Loader `getattr` defaults: 168, 171, 172, 224, 367, 370, 483–487; Mock-status `isinstance` guards: 204–208, 239–243 | A bare loader with only the attributes that test sets (`tests/test_library_loader.py:85` onward, 38 sites) | `__init__` always sets all of these except the five `_snapshot_*` counters (first assigned at 639–643). A sync cannot start before a load has set them (373) [INFERRED]. | **Declare the five counters in `__init__`** (same defaults as the `getattr`s). **Keep every `getattr`**: removing them fails 2 tests for the counters, 2 for the sync flags, 3 for the path variables and 6 for `last_refreshed_at` (A4). |
| T2 | Three hand-copies of the loader's wiring: `_make_wired_loader` (`tests/test_library_loader.py:1645–1675`), `SourcePathsChangedTests.make_instance` (420–440), `InitialSnapshotTests.make_instance` (378–386) | A loader wired to a bare app; a real dialog pointing at a bare loader; a loader with a few attributes set | Hand-copy the 14 assignments, the 9 internal ones, and the dialog lambda. `_make_wired_loader` leaves `snapshot_store`, `cache_var` and `stats_var` unset and sets `app._loader`. | **Isolate.** One tests-only `make_loader(**overrides)` that calls the real keyword constructor, supplies Mock stores and variables, takes an optional `app=`, and has a real-dialog mode. Constructor changes then break one helper, not three copies. |
| T3 | `_on_library_changed` guards: `getattr(self, "song_page")` (655), `course_builder is not None` (670) | `CourseReloadNotificationTests` (`tests/test_library_visualizer.py:1257–1292`); line 1283 pins "no builder yet, no error". Seven tests in `LoaderFilterPersistenceTests` and `LoadBatchesFilterChangesTests` wire the real handler to a bare app; `tests/test_library_loader.py` never sets `song_page`. | Both components are built before the loader exists, so the guards cannot fire in production [INFERRED] | **Keep.** Pinned (the `song_page` read by 7 tests, A4). `_run_loaded` (1258–1275) also sets nine attributes the method never reads, left over from before the filter split [INFERRED]. Tidy in a tests-only follow-up. |
| T4 | `_play_preview` / `_stop_preview` `getattr` (568, 571, 577) | Tests at `tests/test_library_visualizer.py:1820–1860` (`PlayPreviewShellTests`) cover the play/stop glue, including "no player → `None`" (1835) and "stop without a player" (1857) | `_preview_player` is set at 326, before any callback can run | **Keep.** Pinned (3 tests). `_song_media` is the one genuinely runtime-`None` value here (556, 658). |
| T5 | `_report_discarded_settings` `getattr(self, "_settings_store")` (477) | The tests I read (`tests/test_library_visualizer.py:555–572`, `tests/test_library_loader.py:524–529, 549–550`) all set `_settings_store` | The store is made at 83, before anything calls this | **Remove**: no test fails without it (A4). The comment lines that excuse the guard go with it. |
| T6 | `_set_sync_menu_state` `getattr(self, "_file_menu")` (685) | The test sets `_file_menu` (`:1318`) | `_file_menu` is first assigned in `_build_menubar` (397) and is not predeclared in `__init__` | Declare `_file_menu = None` with the other late attributes, then **remove** the guard: no test fails without it (A4). |
| T7 | `_close_app` / `_dialog_is_open` `None` checks (367, 371, 586–589) | `tests/test_library_visualizer.py:1671–1707`: `make_app` sets `advanced_search = None` (1679), and `test_exit_destroys_the_root_when_there_is_no_course_builder` (1687) pins "no course builder" | The components are now built eagerly; the comment at 139–143 still describes the older lazy pattern | **Keep.** Pinned [CODE]. |
| T8 | Dialog `getattr` ×3 (`data_paths_dialog.py:133, 140, 150`) | `tests/test_data_paths_dialog.py:84, 126` build a bare dialog and set only some attributes | `__init__` sets all three (67–69); `close()` resets them to `None` (156–158), so a `None` check is real, but `getattr` also tolerates bare instances | **Keep.** Pinned (1 test, A4). |
| T9 | `_dpi_scale = 1.0` class default (59; also `course_builder.py:48`, `advanced_search.py:41`, `distribution_panel.py:80`) | Bare instances have no window to measure | Shadowed by `__init__` at 67 | **Keep.** One line each. |
| T10 | `_settings_file_path` wrapper (443–448) | 20 `patch.object(app.LibraryApp, "_settings_file_path", …)` sites in two live-test files (counted again by ChatGPT-6) | Indirection only. The comment at 446 says "seventeen"; the count is 20. | **Keep.** Correct the number if that block is edited anyway. |

**Rule for the implementation PRs.** A guard that production cannot reach is removed only when no test relies on it. A guard a test pins stays. No existing test is rewritten for this change.

## A4. What I ran

- [RAN] `python3 -m unittest discover -s tests` at `048ca38` (with the local merges), Python 3.13.18: **783 tests, 1 failure, 56 errors, 73 skipped.** This is not a green run and it is not a baseline for the app: the sandbox has no Tkinter.
  - 55 errors are Tkinter being absent (53 in `test_library_table`, 2 in `test_library_loader`).
  - 1 error and 1 failure are in `test_ui_distribution`: `_load_matplotlib()` returns `False`, and a bare `DistributionPanel` then lacks `_matplotlib_missing_label`. ChatGPT-6 traced the same two tests, with Tk installed and no display, to matplotlib's `TkAgg` backend failing to load headless; I take the same cause here [INFERRED].
- [RAN] by ChatGPT-6, Python 3.13.5 with Tk but no display, at `be300eda`: 777 tests, 1 failure, 1 error, 72 skipped (the same two tests). The same run found: all 14 parameters accepted by keyword (the tests-only first commit can pass today); a Mock sketch of `start()` that reproduces the order at 182–193; and a swap of two adjacent callbacks at 177 that failed no additional test.
- [RAN] A guard-removal experiment on a scratch copy, 217 tests (`test_library_loader`, `test_library_visualizer`, `test_data_paths_dialog`, `test_end_to_end`), Python 3.13.18. The baseline has 2 failing tests (Tkinter absent). Each row removes one guard and counts tests that newly fail:

| Guard removed | Newly failing |
|---|---|
| `_scan_in_flight` / `_sync_in_flight` defaults (367, 370) | 2 |
| Five `_snapshot_*` reads, with the counters declared in `__init__` (483–487) | 2 |
| `last_refreshed_at` (224) | 6 |
| `cache_var`, `stats_var`, `loaded_source_paths` (168, 171, 172) | 3 |
| `_settings_store` (477) | **0** |
| `song_page` (655) | 7 |
| `_file_menu` (685), with `_file_menu = None` declared | **0** |
| `_preview_player`, `_song_media` (568, 571, 577) | 3 |
| Dialog `getattr` ×3 | 1 |

- [RAN] An AST script (Python 3.13.18) for the line spans, attribute lists, parameter reads and `getattr` lists in A0 to A3. ChatGPT-6 reran the same measurements at `be300eda` and found them correct.
- Not run: the app window, and every live test. For every claim about runtime order I read the source. The owner's Windows smoke is Appendix B.

# Appendix B — Owner's Windows smoke list

Plain-language checks for the owner, for after PR 1 and again after PR 2. Each should look exactly as it does today. I cannot run any of them.

1. **Saved snapshot.** Launch with a saved library. The status shows "Loading saved library…", then the snapshot line; the bar runs and stops; the table fills.
2. **First run.** Launch with no snapshot and no saved paths. The Data paths dialog appears. Close it and reopen it from File → Data paths…; it does not pop up again by itself. Relaunch with still nothing loaded; it appears again.
3. **Damaged settings.** Launch with a copy of `settings.json` that has junk characters in it. The "settings could not be read" note appears once, after the snapshot line when a snapshot exists.
4. **Damaged snapshot.** Launch with a damaged `library_cache.json`. A line says the saved library could not be read and points at Load / refresh. Try an outdated snapshot too, if you have one.
5. **Load from the dialog.** Press Load in the Data paths dialog with valid paths, then with invalid ones.
6. **Sync.** Run File → Sync scores twice in a row. Then start a full Load and choose Sync during the scan: the status says a load is in progress, and the Sync entry and the Load button stay disabled until it ends.
7. **Newer Stats.xml.** With a restored snapshot and a Stats.xml newer than it, the hint to choose File → Sync scores appears.
8. **Changed path.** Edit a path while a snapshot is loaded. The "differs from loaded" note appears in the dialog.
9. **Exit paths.** Close with the window's X button and with File → Exit, once with the Build course window open (the discard prompt appears) and once with Advanced Search open (its position is remembered).
10. **Quit and relaunch.** Everything comes back as before.
11. **Best effort.** Click Load the instant the window appears. A 50 ms window cannot be hit reliably; the order test in PR 1 is the real cover.
