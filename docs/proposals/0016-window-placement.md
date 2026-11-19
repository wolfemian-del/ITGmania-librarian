# Implementation Proposal: One placement rule for the dialogs — centered over the main window, remembered once moved

| | |
|---|---|
| **Status** | Draft — for review |
| **Author** | Claude (Sonnet 5.5) |
| **Date** | 2026-11-19 |
| **Base** | main `aed5218` (merge of PR #240, issue #207) |
| **Related** | Issue #103 (this proposal is its trigger); Proposal 0003 (course window geometry); Proposal 0011 Q5 (song page persistence, deferred); Proposal 0013 §4, §5 (song page sizing; "that follow-up should do the #103 extraction"); issue #51 (display scaling) |

---

In plain language: none of the app's secondary windows chooses where to appear. Five of them leave the position to Windows (at most they say how big to be), and the owner has observed that it picks a spot near the top-left of the screen. This proposal makes every one of them open centered over the main window, the first time and any later time the owner has not deliberately moved it. Once the owner moves or resizes Build a course, Advanced Search or the song page, the app remembers that place, and the song page — the one window that forgets on quit today — remembers across restarts like the other two. The rule that decides whether a remembered position is still on screen exists today as two word-for-word copies (issue #103), and the song page would have been a third, so the rule moves into one tested place first.

The real decisions are who remembers what and when (§3 D3, D4): the two existing dialogs would stop saving a position on every close and save only a deliberate move or resize, and the song page's remembered geometry has one sharp edge that the owner should judge by feel (§3 D4).

## 1. Background and Goal

Issue #103 filed a deliberate duplication: the on-screen check that decides whether to reopen a window where it was exists in `CourseBuilder` and `AdvancedSearch`, "identical today", to be shared "when a third dialog needs geometry memory". Proposal 0013 §5 recorded that the song page was not that third dialog because its memory was session-only, and that any persistence follow-up "should do the #103 extraction". The owner has now asked for the song page to remember a move, and for first opens to be centered rather than upper-left; this is that follow-up.

Owner decisions already taken (2026-11-19): center over the main window, not the screen; apply the placement through shared logic to all the dialogs; a move of the song page persists.

Modularity: this change adds one small component, `window_placement.py` (a helper object each window holds; it is not itself a window and imports no Tkinter), adds one pure function to `library_geometry.py`, adds two optional inputs to `SongPage`'s constructor, and persists one new settings key. Each of those is a proposal trigger under AGENTS.md (constructor contract, new settings key, two or more defensible designs). It also amends Proposals 0003 and 0013 on two points (§3 D3, D4).

Done means:

- Every secondary window opens centered over the main window unless the owner has deliberately placed it.
- The on-screen rule exists once, with direct unit tests.
- The song page keeps a deliberate move or resize across restarts under a new `song_page_geometry` key.
- Nothing else about the windows changes (§5).

## 2. Current State (measured on main `aed5218`)

The app opens five secondary windows (`tk.Toplevel` at `course_builder.py:122`, `advanced_search.py:132`, `song_page.py:134`, `data_paths_dialog.py:84`, `library_librarian.py:775`):

| Window | Opens with | Position | Remembers |
|---|---|---|---|
| Build a course | saved geometry, else `1000x620` | restored if visible on the desktop, else the window manager's choice | position and size on every normal close, key `course_geometry` |
| Advanced Search | saved geometry, else `560x620` | same rule, its own copy | same, key `advanced_search_geometry` |
| Song page | this session's saved geometry, else `760x1000`, then resized to its content | saved position reused as-is (no on-screen check); otherwise the window manager's choice | only after a deliberate move or resize, this session only |
| Data paths (modal) | fixed `560x260` | the window manager's choice | nothing |
| About | its content, not resizable | the window manager's choice | nothing |

[CODE] for every cell. That the window manager's choice is near the top-left is [OBSERVED] by the owner; I could not open a window here (no Tkinter in the sandbox).

**The duplicated rule.** [CODE] `CourseBuilder._geometry_for_open` (`course_builder.py:79–114`, 36 lines) and `AdvancedSearch._geometry_for_open` (`advanced_search.py:60–96`, 37 lines) hold the same decision: parse the saved string, scale it by the display factor, and restore it only when at least `scale_pixels(100)` by `scale_pixels(32)` pixels of it are visible on the virtual desktop and its top edge is no more than `scale_pixels(16)` above the desktop's top; otherwise use the size alone. [RAN] An AST comparison of the two function bodies (Python 3.13.18, docstrings ignored) found them identical apart from the name of the theme default (`COURSE_BUILDER_GEOMETRY` / `ADVANCED_SEARCH_GEOMETRY`).

**The duplicated save half.** [CODE] `save_window_geometry` is `course_builder.py:252–267` and `advanced_search.py:98–113`, 16 lines each: return if the window is gone, return unless its state is `normal`, convert to canonical 100% units, store, report. The song page has a third, different version (`song_page.py:554–575`) that also returns unless the geometry differs from the one it opened with (`_record_opening_geometry`, 540–552; reset in `close()`, line 538).

**Shell wiring, per remembering window.** [CODE] `library_librarian.py`: an attribute (183–184), a validator wrapper over `_valid_window_geometry` (515–522; the shared validator is `library_stores.py:220`), construction with `saved_geometry` and `report_geometry` (307–319), a `_..._geometry_changed` callback (435–443), two lines in `_save_settings` (567–571), and a call in `_close_app` (line 418; it calls `save_window_geometry` for the course builder and Advanced Search, not the song page).

**The song page's own logic.** [CODE] `_size_to_content` (`song_page.py:353–372`) sets a size-only geometry after the chart list is filled; it runs only when `_saved_geometry is None` (line 234). `close()` (511) saves on every close path (the X button and Escape both call it, lines 222–223), and a library reload closes the page through `close()` (`library_librarian.py` ~line 717).

**Tests.** [RAN] `tests.test_advanced_search` and `tests.test_course_builder` pass, 77 tests, Python 3.13.18. The paired geometry tests are `test_course_builder.py:751–783` and `test_advanced_search.py:112–145`; shell wiring is tested at `test_library_librarian.py:40–161` (course), 164–223 (Advanced Search) and the live wiring guard at 1530–1551. All use fake windows; none exercises centering, because no code centers a window. No test covers the song page's geometry.

**Docs that mention this.** README.md line 67 (the sizes and positions of the course and Advanced Search windows); `docs/ARCHITECTURE.md` (layer diagram, the construction entries for the two dialogs, and "Dialogs and the panel persist differently by design"); `CHANGELOG.md` Unreleased.

## 3. The Decisions

**D1. Where the shared logic lives. Recommended: a pure function in `library_geometry.py` plus a small helper, `WindowPlacement`, in a new `window_placement.py`.** The pure function decides the geometry; the helper owns the window-side steps that would otherwise be copied into each window: reading the desktop and main-window boxes, recording the geometry a window opened with, saving only on a deliberate change, and reporting it. Alternatives: (a) the pure function only, with those steps left in each window, which keeps the file count down but leaves roughly 15 lines of Tk glue in each of three windows, including the stateful opening baseline, so a fourth copy of the #103 problem; (b) status quo copies, which cannot center five windows consistently. I recommend the helper because the opening-baseline logic must behave identically in three places, which is exactly the shape that has drifted before. This is the proposal's largest decision; (a) is a defensible smaller version.

**D2. The centering rule (owner-decided: over the main window).** A window opens centered over the main window. If the main window is minimized or hidden there is nothing to center over, so the desktop is used. The result is clamped so the window's top-left corner lies inside the virtual desktop and its size never exceeds the desktop's. The main window is read through its `geometry()` string, so the position uses the same convention as the geometry the dialog is given. [UNVERIFIED] Whether that convention centers the dialog's visible frame or its client area exactly; the difference is a title-bar height, about 30 px at 100% scaling, and is a Windows check (§6).

**D3. When a window's place is remembered. Recommended: only after a deliberate move or resize, for all three remembering windows.** Today the two dialogs save on every normal close (Proposal 0003 §4, issue #98). If that stayed, then once a centered dialog is closed unchanged, its centered position would be saved and every later open would restore it; after the owner moved the main window (to another monitor, say) the dialog would keep appearing on the old spot. Saving only when the geometry differs from the one the window opened with (the song page's existing rule) lets a never-moved dialog keep following the main window and lets a deliberately placed one stay put. The visible cost is that the settings file is no longer rewritten by a plain close. This amends Proposals 0003 §4 and issue #98's close-time save.

**D4. What the song page remembers across restarts.** Two options:

- **A (recommended, a close call): one saved geometry, the Proposal 0013 rule carried across restarts.** A move or resize saves position and size; every later open uses them; content sizing applies only until the first deliberate change. The sharp edge: if the owner moves the window while a one-chart song is showing (580 px tall, Proposal 0013 §2), every later song, including a sixteen-chart song (910 px needed), opens at 580 px in that place, with its chart list scrolling. [CODE] This already happens within a session today, because a move records the whole geometry (`song_page.py:569–575`); persistence extends it across restarts, and the only way back to content sizing is removing the setting.
- **B: position and size remembered separately.** A move remembers only the position and a resize remembers the size, so a window that was only moved keeps content sizing at the saved position. This matches "if the owner moves it elsewhere it should persist" more exactly. Cost: a second saved form (a position-only value, or a second key), a position-only parse and validator, and a larger helper; it also revises the 0013 rule the owner accepted on 2026-11-17.

A reuses the existing key shape, validator and helper unchanged, and B can be added later without breaking A's key. I recommend A for that reason and because the sharp edge exists today; the owner, as the look-and-feel arbiter, may prefer B after trying the edge by hand (§6 check 7).

**D5. The fallback and the key.** When a saved position is no longer on the desktop (an unplugged monitor), the saved size is kept and the window is centered, instead of the size-only handoff to the window manager that the two dialogs do today. The song page's new key is `song_page_geometry`, named like the other two, optional, omitted from the settings file until the owner has deliberately placed the window, validated by `_valid_window_geometry` against `theme.SONG_PAGE_MIN_SIZE` (560 by 420).

## 4. Recommended Design in Detail

**4.1 The pure function (`library_geometry.py`, layer 0, no Tkinter).** One-sentence description: given the geometry saved last time, a default size, the main window's box and the desktop, it returns the geometry string a window should open with.

```
opening_geometry(saved, default_size, anchor, desktop, scale) -> str
  saved         canonical "WxH+X+Y" in 100% units, or None
  default_size  (width, height) in physical pixels, used when nothing usable is saved
  anchor        (x, y, width, height) of the main window, or None
  desktop       (left, top, right, bottom) of the virtual desktop, physical pixels
  scale         the display scale factor
```

1. A saved value that parses is scaled to physical pixels; its size is capped to the desktop's.
2. If its position passes today's visibility test (at least 100 by 32 scaled pixels visible; top edge no more than 16 scaled pixels above the desktop's top), the full saved geometry is returned.
3. Otherwise the saved size (or `default_size` when nothing parsed) is centered on `anchor`, or on the desktop when `anchor` is None, then clamped so the window lies inside the desktop; the full geometry, position included, is returned.

Worked example (on a 1920 by 1080 desktop, main window `1500x850` at +100+50): a `1000x620` dialog opens at +350+165; a one-chart song page, `760x580` (Proposal 0013 §2's measured height), at +470+185. `parse_course_geometry` is renamed `parse_window_geometry` in the same stage; it already serves non-course code (§7 Q7).

**4.2 The helper (`window_placement.py`, layer 1, no Tkinter import; it works on the window objects it is handed, as `library_filter` does).** One-sentence description: given its parent window, the display scale and the geometry saved last time (if any), it says what geometry a window should open with and reports a new geometry back only when the owner actually moved or resized the window.

Constructor, four inputs: `parent`, `dpi_scale`, `saved_geometry=None`, `report_geometry=None` (the same pair the two dialogs already take). Methods:

- `geometry_for_open(default_size)` reads the desktop from the parent's `winfo_vroot*` values and the anchor from `parent.geometry()` (None unless the parent's state is `normal` or `zoomed`), then calls `opening_geometry`.
- `record_opening(window)` schedules an idle callback that records the geometry the window actually has once placed and sized.
- `save(window)` does nothing unless the window exists, is in state `normal`, has an opening geometry and now differs from it; otherwise it stores the new canonical geometry and calls `report_geometry`.
- `saved_geometry` (read-only property): the value the song page's content-sizing test reads instead of `_saved_geometry is None`.

A window with no memory (Data paths, About) constructs it without the last two inputs: `save` then reports nothing.

**4.3 What each window does.**

| Window | Passes as `default_size` | Notes |
|---|---|---|
| Build a course, Advanced Search | the scaled theme default | `_geometry_for_open` becomes a one-line call; the two `save_window_geometry` bodies become delegations; their constructor and shell wiring are unchanged |
| Song page | the scaled `760x1000` at creation; after the chart list is filled and the content height is known, the width and that height | content sizing runs only when `placement.saved_geometry` is None; the window is withdrawn while it is built and shown once the final geometry is set, so it never appears at the wrong place and size first |
| Data paths | `560x260` scaled | centered over the main window; it is modal, so this is also where the first-run question appears |
| About | its requested size after the content is built | withdrawn while built, as the song page |

**4.4 Shell changes (PR 3).** A `song_page_geometry` attribute, a `_valid_song_page_geometry` wrapper and a `_song_page_geometry_changed` callback; construction of `SongPage` with the two new optional inputs (`saved_geometry`, `report_geometry`); two lines in `_save_settings`; `song_page.save_window_geometry()` in `_close_app` after the other two. This repeats the existing per-window pattern a third time, as AGENTS.md allows; a table-driven version of that wiring is not part of this change.

**4.5 Interface narrative (for the owner's approval).** Open Build a course, Advanced Search, a song page, Data paths or About: the window appears in the middle of the library window, not at the top-left. Move the library window and open one again: the window follows it. Drag Build a course somewhere else and close it: the next open is there, now and after a restart. The song page behaves the same once moved; before that, it opens at the height its song needs, centered.

## 5. What Does Not Change

- The visibility thresholds (100 by 32 pixels, 16 pixels at the top), the 100%-unit storage, and the minimum-size validation in `_valid_window_geometry`.
- The keys `course_geometry` and `advanced_search_geometry`, their validators, minimum sizes and shell wiring; the constructors of `CourseBuilder`, `AdvancedSearch` and `DataPathsDialog` keep their inputs.
- The song page's content sizing and chart-list scrolling (Proposal 0013), and its "a plain close records nothing" rule, which D3 extends to the other two dialogs.
- The main window's own opening size and position; the About text; the data paths dialog's behavior apart from where it appears.
- Settings files written by earlier versions: the new key is additive and absent until the owner places the song page.
- Amended on purpose: Proposal 0003 §4 and issue #98 (save on every close becomes save on a deliberate change; the size-only fallback becomes saved size centered), and Proposal 0013 §§4–5 (the song page's geometry is now persisted).

## 6. Test Plan (for the implementation PRs)

Three PRs, one at a time, in this order; each names this proposal and says it does not depart from it.

**PR 1 — extract the rule, no behavior change.** Add `opening_geometry` to `library_geometry.py` with today's exact outcomes (signature without `anchor`; the size-only fallbacks stay), have both dialogs call it, and rename `parse_course_geometry` to `parse_window_geometry`. The two existing paired test sets stay unchanged and green as the pin; new direct tests cover the function: fully visible, partly visible, on an unplugged monitor, title bar above the desktop, 150% scaling, an unparseable value. Update `tests/test_import_surface.py` for the new and renamed names. Proves the extraction moved the rule without changing it.

**PR 2 — center, and save only a deliberate change.** Add `window_placement.py`; widen `opening_geometry` (adds `anchor`, centering, the size cap and the centered fallback); move the dialogs' opening and saving onto the helper; center the song page, Data paths and About (withdraw while building). New tests, all Tk-free with fake windows: centering over an anchor, with no anchor, clamping at each desktop edge, a window larger than the desktop, scaling; the helper's record-then-save behavior (a plain close saves nothing, a move saves, a minimized window saves nothing, a window closed before its baseline is recorded saves nothing); song page content sizing still runs when nothing is saved. The existing live wiring guards stay. Update `tests/test_theme.py` `WINDOW_SOURCES` and `docs/ARCHITECTURE.md` (the layer diagram, module table and construction entries).

**PR 3 — the song page remembers.** The key, validator, constructor inputs, callback and exit hook of §4.4, with the same shell tests the other two dialogs have (validator accept and reject, key present only when set, callback stores and saves, approved exit saves before the root is destroyed) plus a live wiring guard that the app passes the pair. README line 67 and a CHANGELOG entry.

**Live checks on Windows (the owner; not runnable in the sandbox).**

1. Open Build a course, Advanced Search, a song page, Data paths and About with the main window in the middle of the screen: each opens centered over it.
2. Move the main window, open a dialog again: it follows.
3. Drag Build a course elsewhere, close it, move the main window, reopen: it opens where it was dragged. Quit and relaunch: same.
4. Open and close a dialog without moving it, move the main window, reopen: it re-centers.
5. Song page: a one-chart song, then a sixteen-chart song: each centered, no visible jump from the top-left.
6. A tall song page (screen height) at 125% and 150% scaling: the buttons are above the taskbar. [UNVERIFIED] The cap is the screen height (Proposal 0013 Q1), not the work area; if the bottom sits behind the taskbar, that predates this proposal and is a separate fix.
7. Move the song page with a one-chart song showing, then open the sixteen-chart song: the D4 sharp edge, to judge A against B.
8. On a two-monitor setup, move a dialog to the second monitor, unplug it (or change the layout), relaunch: the dialog opens centered at its saved size.

## 7. Open Questions for Reviewers

- **Q1.** Which windows? The owner said "all of the dialogs"; this draft takes that as all five, including the fixed Data paths form and the About window, which only gain centering. Recommended: all five. Confirm.
- **Q2.** Helper or pure function only (D1)? Recommended: the helper.
- **Q3.** Dialogs save only a deliberate move or resize (D3)? Recommended: yes.
- **Q4.** Song page memory: A or B (D4)? Recommended: A; a close call.
- **Q5.** When a saved position is lost, keep the saved size and center (D5)? Recommended: yes; the alternative is to ignore the saved geometry whole.
- **Q6.** The taskbar: stay with the screen-height cap and treat a covered button row as a separate bug if the Windows check shows it? Recommended: yes; reading the work area would need `ctypes`, which the app already uses only for DPI awareness.
- **Q7.** Rename `parse_course_geometry` to `parse_window_geometry` with no alias? Its callers are all inside the package and `tests/test_import_surface.py` pins it. Recommended: rename, no alias (issue #103 suggested keeping one).
- **Q8.** Three PRs (extract, center, remember)? Recommended: yes; PR 1 is the no-behavior-change step.

---

*Written by Claude (Sonnet 5.5). No other model has reviewed this draft yet.*
