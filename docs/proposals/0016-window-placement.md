# Implementation Proposal: One placement rule for the dialogs — centered over the main window, remembered once moved

| | |
|---|---|
| **Status** | Draft — Revision 1, for re-review |
| **Author** | Claude (Sonnet 5.5) |
| **Date** | 2026-11-19 |
| **Base** | main `aed5218` (unchanged since the first draft) |
| **Related** | PR #241 (this proposal); Issue #103 (this proposal is its trigger); Proposal 0003 §4 and issue #98 (dialog geometry memory); Proposal 0011 Q5 (song page persistence, deferred); Proposal 0013 §§2–5 (song page sizing); issue #51 (display scaling) |

---

In plain language: none of the app's secondary windows chooses where to appear. Five of them leave the position to Windows, and on the owner's machine Windows puts every one of them at the top-left corner of the screen, whatever the main window is doing. This proposal makes every one of them open centered over the main window, the first time and any later time the owner has not deliberately moved it. Once the owner moves or resizes Build a course, Advanced Search or the song page, the app remembers that place, and the song page — the one window that forgets on quit today — remembers across restarts like the other two. The rule that decides whether a remembered position is still on screen exists today as two word-for-word copies (issue #103), and the song page would have been a third, so the rule moves into one tested place first.

Three choices are the owner's to make by feel, and each is written as a plain question in §3: whether a dialog you never touched keeps following the main window (D3), what the song page remembers when you move it (D4), and whether windows must stay clear of the taskbar (D6). The review also found that centering done naively would make the taskbar problem worse than it is today, which is why D6 exists.

## Revision 1 (2026-11-19, from the six-lane review of PR #241)

Reviewed by Grok (Lane A, the rule), Muse (Lanes B, C and D: the helper, behavior changes, staging), Gemini 3 Flash (Lane C), Codex (Lane E, run on the owner's Windows 11 machine under Python 3.14.7) and ChatGPT-6 (Lane F, fresh read). Every lane but Gemini's returned Revise. What changed:

| Finding (lane) | Where it is folded in |
|---|---|
| The rule's prose left ten details to guess; clamping must cover both edges (A, Gemini) | §4.1 states every step and carries test vectors |
| PR 1 cannot be the final rule and also "change nothing" (A) | §4.1 gives PR 1 its own contract; run against today's code on 228 cases, no mismatch |
| The helper must own the saved value; `record_opening` overwrite, once-per-open and destroyed-window rules; it must run after the final geometry; `default_size` had no producer (B, Gemini, Codex, F) | §4.2 |
| Data paths must not be withdrawn; About needs `update_idletasks` and a focus call after `deiconify` (B, F, Gemini) | §4.3 |
| The main window's `geometry()` is stale when it is maximized (E, measured) | D2 |
| A screen-height window runs under the taskbar; centering would make it deterministic (E measured, C, F); window frames are outside `geometry()` sizes (derived) | New D6, §4.1 |
| D4: B is the better match for "a move persists", and the draft left out that Proposal 0013 §3 rejected B's shape in another form (C) | D4; recommendation changed from A to B |
| The 0013 amendment covers §§2–5, not §§4–5; D3's two edges; the new key read by an older version (C, F) | §5, D3, D5 |
| PR 2 is too large; PR 1's pins leave thresholds loose (two mutations survive); PR 3's tests miss the two sharpest the other keys have; list errors (D) | §6: four PRs, new pins, corrected lists |
| Live checks missed restart persistence, maximized, minimized, scale change, old settings file, modality, exit with a moved window (D, E, F) | §6 live checks, now sixteen |
| Native dialogs out of scope; plain-language D3/D4; §5 mixed changes into "does not change"; constructor not enumerated; no full-suite line (F) | §1, §3, §4.2, §5, §6 |
| Q7's parenthetical was ambiguous (C) | Q7 |

Recommendations that changed: D4 from A to B (reasons in D4); three PRs became four; D6 is new. The owner decisions still open are D3, D4, D6 and the §7 questions.

**Facts the review established** (Codex, Windows 11, Python 3.14.7, 100% scaling, one 1920×1080 monitor, `declare_dpi_awareness()` called first, [RAN]): a size-only transient opens at `+0+0` whatever the parent's position (three positions tried); for a normal main window, `geometry()` centers the dialog's client area exactly (frame inset 8 px left, 31 px top); for a maximized one, `geometry()` still reports the pre-maximize `+150+100` while the client area is at (0, 23), and `winfo_x/y/width/height` center exactly; the work area is 1920×1032 (a 48 px taskbar), and a screen-height window at y=0 reached y=1092; withdrawing while building gave one map at the final geometry, against two maps without; `grab_set()` worked on a withdrawn window. Not measured: 125% and 150% scaling, two monitors.

## 1. Background and Goal

Issue #103 filed a deliberate duplication: the on-screen check that decides whether to reopen a window where it was exists in `CourseBuilder` and `AdvancedSearch`, "identical today", to be shared "when a third dialog needs geometry memory". Proposal 0013 §5 recorded that the song page was not that third dialog because its memory was session-only, and that any persistence follow-up "should do the #103 extraction". The owner has now asked for first opens to be centered rather than upper-left, and for a move of the song page to persist; this is that follow-up.

Owner decisions already taken (2026-11-19): center over the main window, not the screen; apply the placement through shared logic to all the dialogs; a move of the song page persists.

Scope: the five windows the app builds itself as `tk.Toplevel`. The native message boxes and file pickers (`messagebox`, `filedialog`) are positioned by Tk and Windows and are not touched. The main window's own opening position stays under the window manager; only its size is set (`LibraryApp._init_window`).

Modularity: this change adds one small component, `window_placement.py` (a helper each window holds; it is not a window and imports no Tkinter), adds pure functions to `library_geometry.py`, adds two optional inputs to `SongPage`'s constructor, and persists one new settings key. Each is a proposal trigger under AGENTS.md. It amends earlier proposals on the points in §5.

Done means:

- Every secondary window opens centered over the main window unless the owner has deliberately placed it, and never with its bottom edge under the taskbar.
- The on-screen rule exists once, with direct unit tests.
- The song page keeps a deliberate placement across restarts under a new `song_page_geometry` key.
- The deliberate changes in §5, and nothing unrelated, differ from today.

## 2. Current State (measured on main `aed5218`)

The app opens five secondary windows (`tk.Toplevel` at `course_builder.py:122`, `advanced_search.py:132`, `song_page.py:134`, `data_paths_dialog.py:84`, `library_librarian.py:775`; a package-wide search for `simpledialog`, `overrideredirect` and `.post()` found no others, Lane F):

| Window | Opens with | Position | Remembers |
|---|---|---|---|
| Build a course | saved geometry, else `1000x620` | restored if visible on the desktop, else size only | position and size on every normal close, key `course_geometry` |
| Advanced Search | saved geometry, else `560x620` | same rule, its own copy | same, key `advanced_search_geometry` |
| Song page | this session's saved geometry, else `760x1000`, then resized to its content | saved position reused with no on-screen check; otherwise size only | only after a deliberate move or resize, this session only |
| Data paths (modal) | fixed `560x260`, set at creation | size only | nothing |
| About | its content, not resizable | none | nothing |

[CODE] for every cell. [RAN] (Codex) For a size-only window, Windows places it at `+0+0`, the top-left of the screen, whatever the main window's position.

**The duplicated rule.** [CODE] `CourseBuilder._geometry_for_open` (`course_builder.py:79–114`) and `AdvancedSearch._geometry_for_open` (`advanced_search.py:60–96`) hold the same decision: parse the saved string, scale it by the display factor, and restore it only when at least `scale_pixels(100)` by `scale_pixels(32)` pixels are visible on the virtual desktop and the top edge is no more than `scale_pixels(16)` above the desktop's top; otherwise use the size alone. [RAN] An AST comparison (Python 3.13.18, docstrings ignored) found the two bodies identical apart from the theme default's name. Lane D's mutation run shows the pair of existing test sets pins the thresholds only loosely (§6, PR 1).

**The duplicated save half.** [CODE] `save_window_geometry` is `course_builder.py:252–267` and `advanced_search.py:98–113`: return if the window is gone, return unless its state is `normal`, convert to canonical 100% units, store it in the window's own `_saved_geometry` (so closing and reopening within one session reuses it), and report it. The song page's version (`song_page.py:554–575`) also stores `_saved_geometry`, and returns unless the geometry differs from the one recorded at open (`_record_opening_geometry`, 540–552, which records once, `if self._opening_geometry is None`, and is reset in `close()`).

**Shell wiring, per remembering window.** [CODE] `library_librarian.py`: an attribute, a validator wrapper over `_valid_window_geometry` (`library_stores.py:220`), construction with `saved_geometry` and `report_geometry`, a `_..._geometry_changed` callback, two lines in `_save_settings` (567–571), and a call in `_close_app` before the root is destroyed (course builder and Advanced Search only; the song page is torn down with the root and its move is lost at exit).

**The song page's own logic.** [CODE] `_size_to_content` (`song_page.py:353–372`) calls `update_idletasks()` and then sets a size-only geometry from the chart list's height, capped at `winfo_screenheight()`; it runs only when `_saved_geometry is None` (line 234). `show()` on an open page only refills it. `close()` (line 511) saves on every close path.

**Frame sizes.** [RAN] (Codex) Tk `geometry()` sizes are client sizes, and positions are the outer frame's top-left. On this machine the frame adds 8 px at left, right and bottom and 31 px at the top at 100% scaling, so a window's outer box is 16 px wider and 39 px taller than the size in its geometry string. The existing rule and its tests ignore the frame.

**Tests.** [RAN] `tests.test_advanced_search` and `tests.test_course_builder` pass (77 tests, 3.13.18); the full suite is 819 tests OK, 74 skipped (live-window tests, no Tkinter in the sandbox). The paired geometry classes are 16 tests each. The shell wiring is tested in `test_library_librarian.py` (course, Advanced Search, and the live wiring guards). Nothing covers centering, the frame, the work area, or the song page's geometry.

**Docs that mention this.** README.md line 67; `docs/ARCHITECTURE.md` (layer diagram, module table, construction entries, "Dialogs and the panel persist differently by design"); `CHANGELOG.md` Unreleased.

## 3. The Decisions

**D1. Where the shared logic lives. Recommended (unanimous across the review): pure functions in `library_geometry.py` plus a small helper, `WindowPlacement`, in a new `window_placement.py`.** The pure functions decide the geometry; the helper owns what would otherwise be copied into three windows: reading the main window's box, holding the current saved value, holding the geometry the window opened with, and saving only a deliberate change. Alternative: the pure functions only, with that state left in each window. Lane B's trace showed the state, not the arithmetic, is what drifts: record once per open, compare on close, reset, guard against a destroyed window. Three copies of that would recreate issue #103.

**D2. The centering convention (owner-decided: over the main window), now measured.** A window opens centered over the main window's client area. The anchor is read from the main window as follows: when its state is `normal`, its `geometry()` string (offset and size; Codex measured the dialog's client area centered exactly); when it is `zoomed`, its `winfo_x`, `winfo_y`, `winfo_width` and `winfo_height` (`geometry()` is stale then, 158 px right and 108 px down of the visible center in Codex's probe); when it is minimized or withdrawn, there is no anchor and the window is centered in the work area (D6) of the primary monitor. A dialog that is already open is not moved when the main window later moves, minimizes or restores. The centered position is then clamped so the window's whole outer box, frame included, lies inside the work area. [UNVERIFIED] In the normal state `winfo_x/y` are expected to equal the `geometry()` offsets, which would let the two branches become one; a live check settles it (§6, check 7).

**D3. Should a dialog you never moved keep following the main window?** If you leave Build a course or Advanced Search where it first opened, it opens centered over the main window again next time, even if you have moved the main window; if you move or resize it, that placement is remembered instead. Recommended: yes, for all three remembering windows. Today the two dialogs save on every normal close; once windows are centered, a dialog closed untouched would save its centered position and keep appearing there after the main window moved to another monitor. The song page already saves only a deliberate change, and the helper extends that rule to the dialogs. The rule compares the closing geometry with the geometry the window opened with. Two edges, both small: a dialog moved away and then dragged back to exactly its opening spot records nothing, so if the main window has also moved meanwhile the next open re-centers; and because a plain close no longer saves, a saved position that has become unusable (an unplugged monitor) stays in the settings file until the owner next moves the window. It does no harm — the on-screen test rejects it on every open, and the window centers — but it is not refreshed as it is today. Also, the settings file is still rewritten for other reasons; the change is only that a plain close writes no new geometry. This amends Proposal 0003 §4 and issue #98's close-time save.

**D4. After you move or resize the song page, what should happen to its size on later songs?** Option A remembers both position and size, so a page you moved while a one-chart song (580 px tall) was showing stays 580 px tall for a sixteen-chart song (910 px needed), with a scrolling chart list. Option B remembers a move as a position only and a resize as a size too, so a moved page still sizes itself to each song.

- **A: one saved geometry, Proposal 0013's session rule carried across restarts.** Any move or resize saves position and size. It reuses the existing key shape and validator unchanged. The sharp edge is not a one-time cost: songs have between one and many charts, so a frozen size fits one kind of song; fixing it by resizing breaks the other (resized to 910 px, every one-chart song opens in a tall, mostly empty window), and the only way back to content sizing is deleting the setting. The edge exists today within a session; persistence makes it permanent.
- **B (recommended): position and size remembered separately, in one key with two accepted forms.** `WxH+X+Y` means the owner resized: size and position are restored and content sizing is off, as in A. `+X+Y` means the owner only moved it: the position is restored and the page still sizes itself to its song (shifted up if a taller song would run past the taskbar). The baseline comparison tells the two apart: a size that differs from the opening size is a resize; only a position that differs is a move. This is what the owner asked for ("if the user moves it elsewhere it should persist"), and it also removes the edge within a session. Cost: one position-only parse and validator, one branch in the helper's save and one in the opening rule, and a constructor flag (`content_sized`, input 5 in §4.2).

Why the recommendation changed from A to B: Muse's Lane C showed the recurring cost described above, which my first draft called a one-time edge; and showed that my claim "B can be added later without breaking A's key" is true only in the narrow sense that the value still parses, because once A stores a full geometry nobody can tell a deliberate resize from a size frozen by a move. Proposal 0013 §3 considered the nearest alternative — sizing the height on every `show()` and taking only position and width from the saved geometry — and rejected it because it would discard a deliberate resize; B keeps a deliberate resize, which is the objection's point. Three reviewers (Codex, Gemini, ChatGPT-6) preferred A, Codex and ChatGPT-6 conditionally: both said they would switch if the frozen height looked wrong in use, and Lane C's description is exactly that case. It is a close call and the owner's to make by feel. B amends Proposal 0013 §3's rule (a move no longer freezes the size, also within a session).

**D5. The fallback and the key.** When a saved position is no longer on the desktop (an unplugged monitor), the saved size is kept (capped to the work area) and the window is centered, instead of the size-only handoff to the window manager that the two dialogs do today. The song page's key is `song_page_geometry`, optional, omitted from the settings file until the owner has deliberately placed the window, validated by `_valid_window_geometry` against `theme.SONG_PAGE_MIN_SIZE` (560 by 420). Reading across versions: a file from an earlier version has no such key and opens as today; a file written by this version and read by an earlier one loses the key on that earlier version's next save (`_save_settings` writes a fixed set of keys), so the song page forgets its place. That is acceptable for one optional UI value, and no migration is proposed.

**D6. Should windows be kept clear of the taskbar? Recommended: yes — fit them to the work area of the main window's monitor.** [RAN] (Codex) On the owner's machine the work area is 1920×1032 under a 48 px taskbar, and a screen-height window reached y=1092, 60 px past the work area. The song page's cap (`winfo_screenheight()`, Proposal 0013 Q1) does not prevent that today, but today a size-only window sits at `+0+0`, so any page up to about 1000 px tall clears the taskbar. Centering changes that: [RAN] (the reference run in §4.1) a sixteen-chart page, 760×910, centered over a main window at +100+250 and clamped to the whole desktop, ends with its outer bottom at y=1080, covering the bottom 48 px, where the song page's button row sits (it is built first and packed at the bottom of the window); the same page clamped to the work area ends at y=1032. So the first draft would have made a case that works today fail, and the clamp half of this decision is not really optional.

- **W1 (recommended): clamp and cap to the work area.** The pure function takes the work-area box; the song page's height cap reads it instead of the screen height, minus the frame (this amends Proposal 0013 Q1); a small function in `library_geometry.py` asks Windows for the work area of the monitor holding the main window (`MonitorFromWindow` and `GetMonitorInfoW`, via `ctypes`, which that module already imports for DPI awareness), and returns the virtual desktop when it fails or the platform is not Windows; with no window handle it returns the primary monitor's work area, which is what D2 uses when the main window is minimized. About 20 lines, untestable in the sandbox beyond a fake, so a live check covers it. [UNVERIFIED] on two monitors.
- **W2: keep the whole desktop.** Simpler, and the taskbar problem stays, now reachable by centering. If chosen, the live check on the taskbar and the "never under the taskbar" line in §1 are removed, and a follow-up issue records it.

The on-screen test for a *saved* position keeps using the whole virtual desktop, as today: a window the owner deliberately dragged partly under the taskbar is restored where it was.

## 4. Recommended Design in Detail

**4.1 The pure functions (`library_geometry.py`, layer 0, no Tkinter).** One-sentence description: given the geometry saved last time, a default size, the main window's box, the desktop and the work area, it returns the geometry string a window should open with.

PR 1 contract (no behavior change):

```
opening_geometry(saved, size, desktop, scale) -> str
```

`saved` is the canonical `WxH+X+Y` string or None; `size` is the default as a physical `(width, height)` pair; `desktop` is `(left, top, right, bottom)` of the virtual desktop in physical pixels; `scale` is the display factor. If `saved` parses and passes today's visibility test it returns the scaled geometry with no size cap; otherwise it returns the size alone as `WxH`, so the window manager places it. [RAN] This reproduces `CourseBuilder._geometry_for_open` on 228 cases (four scales, three desktop shapes including negative origins, the threshold boundaries); Grok's ten-case table, in which seven cases diverge between the PR 1 contract and the final rule, shows the same fact from the other side.

Final contract (PR 2):

```
opening_geometry(saved, size, desktop, scale, *, anchor=None, work=None, frame=(16, 39)) -> str
```

`anchor` is `(x, y, width, height)` of the main window or None; `work` is the work-area box (default: `desktop`); `frame` is the window frame's extra width and height in canonical 100% units, scaled by `scale` (the measured 16 and 39). Units are physical pixels except `saved` and `frame`. Steps, in order:

1. If `saved` parses, scale its four numbers with `scale_pixels` (Python's `round`, as today); the usable size is the saved size capped to `work`: width at most `work width − frame width`, height at most `work height − frame height`, never below 1. Without a usable saved geometry, the usable size is `size`, capped the same way.
2. If `saved` parsed and its (capped) box passes today's visibility test against `desktop` (at least 100 by 32 scaled pixels visible; top edge at most 16 scaled pixels above the desktop's top), return the capped size at the saved position, formatted with `format_geometry` (so a negative offset reads `+-8`).
3. Otherwise center. With an `anchor`, the position is `anchor x + (anchor width − width) // 2` and `anchor y + (anchor height − height) // 2` (the dialog and the main window have the same frame, so their client areas share a center). Without one, the window's outer box is centered in `work`: `work left + (work width − (width + frame width)) // 2`, and the same for the top.
4. Clamp the position so the outer box (size plus frame) lies inside `work` on all four edges: `x = max(left, min(x, right − (width + frame width)))`, and the same for `y`. Return the geometry with `format_geometry`.

Test vectors, 1920×1080 desktop, work area 1920×1032, frame 16 and 39, scale 1.0 [RAN] with the reference implementation (Python 3.13.18; it is outside the repo, and 20,000 random cases also confirmed that every centered result lies wholly inside the work area and that no size exceeds it):

| `saved`, `size`, `anchor` | Result |
|---|---|
| none, 1000×620, main 1500×850 at +100+50 | `1000x620+350+165` |
| none, 760×580 (one-chart page), same main window | `760x580+470+185` |
| none, 760×910 (sixteen charts), main at +100+250 | `760x910+470+83`; clamped to the whole desktop it would be `+131`, covering the taskbar |
| none, 760×1400 (a fifty-chart page), same as the first row | `760x993+470+0` (capped; outer bottom y=1032) |
| none, 1000×620, no anchor | `1000x620+452+186` |
| `900x620+30+40` | `900x620+30+40` (visible: unchanged) |
| `3000x2000+10+10` | `1904x993+10+10` (capped, position kept) |
| `900x620+5000+40` (second monitor gone), anchor as row 1 | `900x620+400+165` (size kept, centered) |
| `900x620+-1500+40`, desktop −1920…1920 | `900x620+-1500+40` (negative origin restores) |
| `1x1+0+0`, anchor as row 1 | `1x1+849+474` (not visible: centered) |

Other pure functions: `parse_course_geometry` is renamed `parse_window_geometry` in PR 1 (it already serves non-course code; Q7); `parse_window_size(text)` returns `(width, height)` or None for a size-only string such as the theme's `"1000x620"`, which `parse_window_geometry` rejects (and which `scale_geometry` accepts), so every caller has a producer for `size`; `work_area_of(hwnd)` returns the box or None (D6); and, only if D4 is B, `parse_window_position(text)` for the `+X+Y` form.

**4.2 The helper (`window_placement.py`, layer 1; it imports no Tkinter and works on the window objects it is handed, as `library_filter` does at layer 2).** One-sentence description: given its owner window, the display scale and the geometry saved last time (if any), it says what geometry a window should open with, remembers the geometry the window actually opened with, and reports a new geometry only when the owner has moved or resized the window.

Constructor, enumerated:

1. `parent`: the owner window the placement is relative to (today always the main window; the contract does not assume it).
2. `dpi_scale`: the display scale factor.
3. `saved_geometry` (default None): the canonical geometry saved last time. From construction on, the helper owns the current value; the windows' own `_saved_geometry` attributes go away.
4. `report_geometry` (default None): called with the canonical string when a new geometry is to be stored.
5. `content_sized` (default False; only if D4 is B): the window sizes itself to its content, so a pure move is stored as `+X+Y`.

Methods and their contracts:

- `geometry_for_open(default_size_text)`: takes the canonical size string from the theme (`"1000x620"`), scales it, reads the anchor (D2), the desktop and the work area (D6), and calls `opening_geometry`.
- `geometry_for_content(width, height)`: the same for a window whose size is known only after it is built (physical pixels); used by the song page after its chart list is filled.
- `has_saved_size`: read-only; true when the saved value includes a size. The song page's content sizing runs only when it is false (the test `_saved_geometry is None` at `song_page.py:234` becomes this).
- `record_opening(window)`: called exactly once per open, after the window's final geometry has been set and, for a window built while withdrawn, after `deiconify()`. It clears any earlier baseline at once, then schedules an idle callback that records the geometry the window has once placed. The callback does nothing if the window is gone or a baseline is already set, so a minimize and restore, which nothing re-triggers, can never overwrite it. It must come after `update_idletasks()`, which runs pending idle callbacks: scheduled before the song page's content sizing, it would record the 760×1000 opening geometry, and every plain close would then look like a resize.
- `save(window)`: returns if the window is gone or its state is not `normal`. PR 2 stores and reports the current canonical geometry, as today; from PR 3 it also returns unless a baseline exists and the current geometry differs from it. When it stores, it updates `saved_geometry` first, so that closing and reopening within one session reuses the new place, then calls `report_geometry`.
- `saved_geometry`: read-only property for the current value.

A window with no memory (Data paths, About) constructs it with only the first two inputs; `save` then reports nothing.

**4.3 What each window does.**

| Window | Sequence |
|---|---|
| Build a course, Advanced Search | `_geometry_for_open` becomes `placement.geometry_for_open(theme default)`; the size is known when the window is created, so there is nothing to withdraw. `save_window_geometry` delegates to `placement.save`. `record_opening` is called once the window exists. Constructors and shell wiring are unchanged. |
| Song page | Withdrawn at creation; the content is built; if `placement.has_saved_size` the geometry is `geometry_for_open(theme default)`, otherwise `_size_to_content` ends with `geometry_for_content(width, content height)`, its cap now the work area minus the frame (D6); then `deiconify()`, `focus_force()` (as today, after the map) and `record_opening`. A second `show()` on the open page changes nothing. `close()` calls `placement.save`. |
| Data paths (modal) | Not withdrawn: its size is fixed and known, so the centered geometry is set at creation and `grab_set()` is called after the form is built, exactly as today. (`grab_set()` also worked on a withdrawn window in Codex's probe; the point is that nothing here needs it.) |
| About | Withdrawn at creation; content built; `update_idletasks()` so the requested size is real; `geometry_for_open` from `winfo_reqwidth` and `winfo_reqheight`; `deiconify()`; `focus_force()` after the map (the window manager ignores it on a withdrawn window). |

**4.4 Shell changes (PR 4).** A `song_page_geometry` attribute seeded from the settings file at startup, a `_valid_song_page_geometry` wrapper, a `_song_page_geometry_changed` callback, construction of `SongPage` with the two new optional inputs, two lines in `_save_settings`, and `song_page.save_window_geometry()` in `_close_app` before the root is destroyed (the page is otherwise torn down without `close()` running). This repeats the existing per-window pattern a third time, as AGENTS.md allows; a table-driven version is not part of this change.

**4.5 Interface narrative (for the owner's approval).** Open Build a course, Advanced Search, a song page, Data paths or About: the window opens centered over the library window; if it would reach past the screen edge or under the taskbar, it is shifted back onto the screen, and a window taller than the screen's usable area is shortened to fit. If the library window is minimized, the window opens centered on the screen instead, and it is not moved if the library window is later moved or minimized. Move the library window and open one again: the window follows it. Drag Build a course somewhere else and close it: the next open is there, now and after a restart. The song page behaves the same way once moved; before that it opens centered at the height its song needs. What it keeps after you move it depends on D4: under B it keeps the position and still fits each song, until you resize it, after which it keeps that size too; under A it keeps that size for every song until you resize it again.

## 5. What Does Not Change, and What Does on Purpose

Does not change:

- The visibility thresholds (100 by 32 pixels, 16 at the top), 100%-unit storage, and the minimum-size validation in `_valid_window_geometry`.
- The keys `course_geometry` and `advanced_search_geometry`, their validators, minimum sizes and shell wiring; the constructors of `CourseBuilder`, `AdvancedSearch` and `DataPathsDialog` keep their inputs.
- The song page's content sizing and chart-list scrolling (Proposal 0013), and its "a plain close records nothing" rule.
- The main window's own position (left to the window manager; only its size is set), the About text, the data paths dialog's behavior apart from where it appears, and everything about message boxes and file pickers.
- Settings files written by earlier versions.

Deliberately changed, and the earlier text each supersedes:

- Opening position: all five windows open centered, not at the window manager's choice.
- Proposal 0003 §4 and issue #98: the two dialogs save on a deliberate change instead of every normal close, and the lost-position fallback is the saved size centered instead of the size alone.
- Proposal 0013 §§2–5, wherever the geometry is described as session-only (§2's "session-only … no settings key", §3's session-memory and "Persistence is deferred" decisions, §4's "unchanged on the saved-geometry path", §5's "no new settings key" and "still not persisted", and §5's "Issue #103 is not triggered"); and, under D4 = B, §3's rule that a move freezes the size.
- Proposal 0013 Q1 (the song page height cap) if D6 is W1.
- Proposal 0011 Q5 decided on a fixed default with no persistence in v1; adding persistence now fulfills that deferral and is not an amendment.

## 6. Test Plan (for the implementation PRs)

Full suite: `python -m unittest discover -s tests` must pass at the end of every PR (819 passed, 74 skipped at the base; the skips are the live-window tests, which need Tkinter). Four PRs, one at a time, each naming this proposal and saying it does not depart from it. PR 2 and PR 3 land back to back, because between them a centered dialog closed untouched still saves its centered position.

**PR 1: extract the rule, no behavior change.** `opening_geometry` with the PR 1 contract in `library_geometry.py`; both dialogs call it; `parse_course_geometry` renamed `parse_window_geometry` with no alias, and `parse_window_size` added; `tests/test_import_surface.py` updated for the names. The existing paired test sets stay unchanged and green, and they are looser than they look: Lane D applied seven mutations to both copies and two survive (a width threshold of 200 instead of 100; a height threshold of 200 instead of 32), and the title-bar allowance is pinned only between 16 and 40. So the new direct tests are written against the union of the two sets' cases and add: a height sliver; each threshold at its boundary (exactly 100 px visible restores, 99 does not; the same for 32; the title bar at −16 restores, −17 does not); 150% scaling; an unparseable value; a negative-origin desktop; and a table-driven pin of the 228-case comparison against the old function before it is deleted.

**PR 2: center through the helper.** `window_placement.py` (the opening half and an unconditional `save`); the widened `opening_geometry`; `work_area_of` (if W1); the five windows moved onto the helper as in §4.3, with the song page's cap changed to the work area (a separate commit, so W2 can drop it). New Tk-free tests with fake windows: centering with and without an anchor, the maximized and minimized anchor rules, clamping at each edge, a window larger than the work area, frame and scaling, the fallback keeping the saved size; the helper owning the saved value (move, close, reopen within one session restores the moved geometry: the in-session memory must not depend on `report_geometry`); `has_saved_size`; content sizing still running when nothing is saved. Updates: `tests/test_import_surface.py` (a names-resolve method for `window_placement`), `docs/ARCHITECTURE.md` (layer diagram, module table, construction entries, one line saying the helper follows the filter's pattern at layer 1), and a CHANGELOG entry (centering is user-visible). `tests/test_theme.py`'s `WINDOW_SOURCES` needs no change: the helper uses no theme names. `tests/test_layer_enforcement.py` needs none: it reads the import graph and pins only the eight Tk-importing modules.

**PR 3: save only a deliberate change.** `record_opening` and the baseline comparison in `save`, for the three remembering windows. Tests: a plain close saves nothing; a move saves; a minimized or maximized window saves nothing; a close before the idle callback ran saves nothing and never saves a previous open's baseline; a second open overwrites the baseline; the callback run twice leaves the baseline unchanged (a restore cannot overwrite it); a baseline recorded before content sizing is the bug to be pinned (the song page's plain close after content sizing saves nothing).

**PR 4: the song page remembers.** The key, validator, constructor inputs, callback, exit hook and, if D4 is B, the position-only form and `content_sized`. Tests as for the other two keys: validator accept and reject including the `+-8` canonical spelling; the song page's own floor (560 by 420 accepted, one pixel below rejected, and values between the other two dialogs' floors accepted here); the key present only when set; **the stored geometry survives a save triggered by an unrelated change** (the key is seeded at startup, so a routine save in a session that never opens the page carries it through); the callback stores and saves; an approved exit saves before the root is destroyed (a mock-app test of `_close_app`, plus the live wiring guard that the app passes the pair, as for the other two). If B: a move saves `+X+Y`, a resize saves the full form, a move after a resize saves the full form with the new position, the position-only form with a taller song is shifted up, not resized. Updates: `docs/ARCHITECTURE.md`'s song page construction entry (its six inputs gain two), README line 67 (the song page joins the course and Advanced Search windows), and the CHANGELOG entry extended.

**Live checks on Windows (the owner; not runnable in the sandbox).** The fake-window tests cover none of the real placement, so these are the only coverage for it, and each is an acceptance step, not optional confirmation. After PR 2, unless noted:

1. Open Build a course, Advanced Search, a song page, Data paths and About with the main window in the middle of the screen, off to one side, and low on the screen: each opens centered over it, with no flash at the top-left.
2. Move the main window and open a dialog again: it follows. With a dialog open, move, minimize and restore the main window: the dialog is not moved and stays usable.
3. (After PR 3.) Drag Build a course elsewhere, close it, move the main window, reopen: it opens where it was dragged. Quit and relaunch: the same. Do the same with Advanced Search.
4. (After PR 3.) Open and close a dialog without moving it, move the main window, reopen: it re-centers. Minimize, restore, close and reopen: it re-centers and nothing is saved.
5. Taskbar: with the main window low on the screen, a sixteen-chart song page and a fifty-chart one (and Build a course) at 100%, 125% and 150% scaling: the bottom button row is above the taskbar, flush with it or a few pixels clear, never covered (this checks the frame allowance too).
6. Song page, D4: with a one-chart song showing, move the page, then open the sixteen-chart song. Under B it opens at its own height at the moved position; under A at the one-chart height with a scrolling list. Then resize it, open another song: the size sticks.
7. Maximize the main window and open a dialog: it is centered within about a title bar, not off to one side (Codex measured 158 px right, 108 px down if `geometry()` were used). Also confirm in a probe that `winfo_x/y` equal the `geometry()` offsets for a normal window (D2).
8. Minimize the main window and open a dialog: it opens centered on the screen's work area; restore the main window and the dialog is usable.
9. Data paths, first run (no settings file): centered, and the main window is blocked while it is open.
10. About and the song page: no visible jump, and Escape closes them without a click first.
11. Change the display scaling between two runs: a saved dialog position comes back adapted to the new scale and on screen (the goal is the canonical placement, not the same physical pixels).
12. (After PR 4.) Move the song page, quit, relaunch, open a song: it opens where it was moved.
13. Quit with a moved Build a course or song page still open, relaunch: the position is kept.
14. Start with a settings file from before this change (it has the two old keys and no song page key): the old keys restore as before and the song page centers and sizes to its song.
15. Two monitors, if available: a dialog moved to the second monitor, then the monitor unplugged and the app relaunched, opens centered at its saved size; a main window on the second monitor, also maximized, centers its dialogs on that monitor and not across both.
16. Frame constants (16 and 39 at 100%) at 125% and 150%: the clamped window's edges sit at the work area's, with no gap larger than a few pixels.

## 7. Open Questions for Reviewers

Tally from the first review round in brackets.

- **Q1.** Which windows? All five, including the fixed Data paths and About; native message boxes and file pickers are excluded. [Unanimous yes; F asked for the exclusion to be said.]
- **Q2.** The helper, not the pure functions alone (D1)? Recommended: the helper. [Unanimous yes.]
- **Q3.** Dialogs save only a deliberate move or resize (D3)? Recommended: yes. [Unanimous yes, with the two edges named.]
- **Q4.** Song page memory: A or B (D4)? Recommended: B (changed). [A: Gemini, Codex, ChatGPT-6, the last two conditional on trying the one-chart-to-sixteen-chart case; B: Muse.] The owner decides.
- **Q5.** When a saved position is lost, keep the saved size (capped) and center (D5)? Recommended: yes. [Unanimous yes.]
- **Q6.** Fit windows to the work area, W1, or keep the whole desktop, W2 (D6)? Recommended: W1 (new). [The first draft's "separate fix" was agreed to by Gemini, Muse and ChatGPT-6 as staging; Codex's measurement and the centered-clamp run show it is not separate once windows are centered.]
- **Q7.** Rename `parse_course_geometry` to `parse_window_geometry` with no alias? Issue #103 said only to *consider* the rename, "keeping an alias". Every caller is inside the package (`library_geometry.py`, `library_stores.py`, `course_builder.py`, `advanced_search.py`) or its tests, and `tests/test_import_surface.py` pins the name, so an alias would be dead weight. Recommended: rename, no alias. [Unanimous yes.]
- **Q8.** Four PRs (extract; center; save only a deliberate change; the song page remembers)? Recommended: yes. [Three PRs were proposed; Muse (Lane D) asked for the split of PR 2; Gemini, Codex and ChatGPT-6 agreed with three.]

---

*Written by Claude (Sonnet 5.5). Revision 1 incorporates the review of PR #241 by Grok, Muse, Gemini 3 Flash, Codex and ChatGPT-6, listed at the top. The reference implementation and checks behind §4.1 are in the author's scratch directory, not the repo, and can be committed under `tests/` in PR 1 if the reviewers want them.*
