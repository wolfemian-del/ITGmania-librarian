# Implementation Proposal: Size the song page by its contents, and scroll the chart list

| | |
|---|---|
| **Status** | Accepted — approved by the owner on 2026-11-17 |
| **Author** | Muse (Muse Spark 1.3) |
| **Date** | 2026-11-17 |
| **Base** | main `3f5fbd8` (merge of PR #214, Proposal 0011 stage 4) |
| **Related** | Issue #211; Proposal 0011 (the song page; Q5 deferred persistence); issue #103 (not triggered — see §5) |

## Revision 1 (2026-11-17, from Grok's review of PR #216)

Grok reviewed the draft (Accept, no changes to the proposal) and added two
items to the §6 test plan, folded in below: assert the mousewheel binding
works on the canvas when the list overflows, and confirm the window manager
places a size-only geometry on-screen for the first open.

## Review resolutions (2026-11-17)

Grok (sole reviewer, PR #216 comment 6952304339) verified the §2 arithmetic
exactly (every interval 22.0 px/chart, chrome ~558 px with images), confirmed
the boundary and contract claims against main `3f5fbd8`, and confirmed the
#103 non-trigger. His answers to the open questions, accepted by the owner:

- **Q1.** The cap is the screen height (`winfo_screenheight`), not a fixed
  maximum.
- **Q2.** The scrollbar is shown only when the chart list overflows.
- **Q3.** Content sizing applies only on the first open in a session; after a
  resize, the saved geometry wins for later opens.

---

In plain language: the song page will open at the height its song needs — short for a one-chart song, tall for Butterfly's sixteen — instead of always opening at the same fixed height, and the chart list will scroll inside the window when a song has more charts than fit on the screen. The owner will notice the window fits the song on the first open, and that a song with very many Edit charts no longer pushes the buttons off the bottom: the list scrolls instead. The one real decision is that a deliberate resize still sticks for the session (see §3), and that keeping the size across restarts is deferred, not built here.

## 1. Background and Goal

Issue #211 is the owner's smoke finding on PR #210 (Proposal 0011 stage 3): the song page opened at its default height (then 760x640), which was not tall enough to show all of a many-chart song's chart lines, let alone the buttons at the bottom. Butterfly, with 16 charts, overflowed it. The V1 stopgap — a longer hardcoded default, now 760x1000 — fits Butterfly, but a fixed height cannot fit every song: a song can carry any number of Edit charts, so no fixed height fits them all, and a one-chart song opens 420 px taller than it needs.

This change creates no new component boundary and moves none: the sizing and the scrolling live inside `song_page.py`, behind the page's existing contract. The component it belongs to is the song page, and the boundary it lives behind is the page's `show(song, media)` — the shell keeps handing it the same song and media record, and the page keeps owning its own window. Done means: a song opens at the height its content needs (capped at the screen), a song with more charts than fit scrolls its chart list instead of pushing the buttons off, and a deliberate resize still sticks for the session.

## 2. Current State (measured on main `3f5fbd8`)

The page (`itgmania_library/song_page.py`, 410 lines) builds one window per `show()` and fills it top to bottom: banner label, title, artist/pack, an images row (Background/Jacket/CD title), the music and folder lines, a "Charts" header, a charts frame with one label per chart (`pack(fill="x")`), and a button row (Play preview, Stop, Open song folder, Close). The charts frame is packed with `fill="both", expand=True`, so it takes extra space, but the window's height is fixed at open: `_geometry_for_open()` returns the saved session geometry, or `SONG_PAGE_GEOMETRY` (`"760x1000"`, `theme.py:84`), scaled by the display factor. The saved geometry is session-only — `close()` remembers it in memory, and there is no settings key (Proposal 0011 Q5). The minimum size is `(560, 420)` (`SONG_PAGE_MIN_SIZE`).

Measured under Xvfb (sandbox Tk 8.6, dpi 1.0, realistic images: a 512x160 banner, a 256x192 background, a 256x256 jacket), the window's requested height by chart count:

| Charts | Requested height |
|---|---|
| 1 | 580 px |
| 4 | 646 px |
| 8 | 734 px |
| 16 (Butterfly) | 910 px |
| 30 | 1218 px |
| 50 | 1658 px |

Each chart line costs about 22 px; the fixed chrome (banner, images row, labels, buttons) is about 558 px with images (about 310 px with placeholders only). The sandbox screen is 1024 px tall. Two consequences: Butterfly needs ~910 px, so the old 640 default overflowed by ~270 px and the current 1000 default only just fits it; and 50 charts need ~1658 px, which exceeds a 1024 px screen — so content sizing alone cannot cover the unbounded case, and a scrollbar is needed for the tail. The numbers are indicative (the owner runs Tk 9.0 on Windows, and real banner/background sizes vary), so the implementation measures the height at runtime (`winfo_reqheight`) rather than hardcoding these figures.

Coupling inventory: the page is constructed once by `library_visualizer.py` with six inputs (`parent, on_play, on_stop, on_open_folder, dpi_scale, button_factory`) and is opened through `_open_song_page(row)`; it touches `theme.py` (`SONG_PAGE_GEOMETRY`, `SONG_PAGE_MIN_SIZE`, fonts, colours), `library_geometry.py` (`scale_geometry`, `scale_pixels`), and `library_format.py` (`format_duration`, for the music line). The shell's `_dialog_is_open()` reads the page's `window` attribute, and `_on_library_changed` closes the page on reload and sync. No settings key, no file format, no other component reads the page's geometry. The live tests for the page live in `tests/test_library_visualizer.py` (`LiveSongPageOpenTests`, `LiveSongPageDirectTests`).

## 3. The Decision: size by content, scroll beyond the cap, keep the session memory

The recommendation is **both halves of issue #211, in one change**:

- **Size by content.** On the first open in a session (no saved geometry), the window opens at the height its content needs — the requested height after the fill, capped at the screen height — instead of the fixed default. The width stays the theme default (760), and the height is content-driven only.
- **Scroll the chart list.** The chart labels move into a scrollable frame (a Canvas with a vertical Scrollbar, mousewheel-bound). The scrollbar appears only when the chart list overflows its viewport; a fitting list shows no scrollbar. This is the robust answer for the unbounded case: a song with more charts than fit on the screen scrolls instead of pushing the buttons off the bottom.
- **The session memory is untouched.** Once the owner resizes the window, the saved geometry is respected for later opens in the session, exactly as today. Content sizing sets the opening height; a deliberate resize still sticks.

The rejected alternative for the session-memory interaction is sizing the height on every `show()` and taking only the position and width from the saved geometry. That would make every song open at its own height, but it would discard a deliberate user resize on the next open — the owner resized the window because it opened wrong, and once it opens right there is less to fix, but a resize the owner did make should still stand. The recommended rule is also the smaller change: `_geometry_for_open` gains the content height only on the path where there is no saved geometry.

The rejected alternative for the sizing half is sizing by content alone, with no scrollbar. It fixes the common case (1–20 charts fit under ~1000 px) but leaves the tail broken: a 30-chart song needs ~1218 px and a 50-chart song ~1658 px, both beyond the current default and the latter beyond a 1024 px screen. The rejected alternative for the scrolling half is a scrollbar alone, with the window staying at 1000 px for every song. It is robust for any count, but a one-chart song still opens ~420 px taller than it needs. Both halves together are what the owner described in the smoke finding: content-aware sizing as the graceful default, and a scrollable chart list as the robust answer for the unbounded-Edits case.

**Persistence is deferred, and that is a decision, not an oversight.** Keeping the size across restarts would need a new settings key, which Proposal 0011 Q5 deferred, and persisting a new settings key is a proposal trigger. Content sizing removes most of the reason to persist: the window opens at the right size for each song, so there is less of a resize to remember. If the owner still misses persistence after living with content sizing, it is a small follow-up — and that follow-up would also trigger issue #103 (see §5), so it should not be folded in silently later.

## 4. Recommended Design in Detail

This change does not touch a component boundary or a constructor contract: the page keeps its six inputs, the shell keeps calling `show(song, media)`, and the sizing and scrolling are internal to `SongPage`. The legibility test, applied to what changes: the page is a window that shows one song's media and charts, sized to the song it is showing, with a chart list that scrolls when the song has more charts than fit. That sentence is the whole design.

- **Content height.** After `_fill()` lays out the labels, the page reads the window's requested height (`winfo_reqheight`) and, when there is no saved geometry, sets the window's height to the smaller of that requested height and the screen height (`winfo_screenheight`). The width comes from the theme default, as today. The cap is the screen height: it adapts to the owner's display, where a fixed cap would reintroduce the problem on a taller display or waste space on a shorter one. The exact margin for the taskbar is an implementation detail; the tests pin the bound (a 50-chart song opens no taller than the screen).
- **Scrollable chart list.** The chart labels live in a Canvas with a vertical Scrollbar and a mousewheel binding, in place of the plain charts frame. The canvas's scroll region follows the labels; the scrollbar is shown only when the list overflows its viewport (hidden otherwise, so a fitting list looks exactly as it does today). The button row stays outside the scrollable area, so Play, Stop, the folder button, and Close are always visible.
- **Session memory.** `_geometry_for_open` is unchanged on the saved-geometry path: a remembered geometry is restored whole, as today. Only the no-saved-geometry path changes, from the fixed theme default to the content-sized height. `save_window_geometry` and `close()` are unchanged. The theme default `SONG_PAGE_GEOMETRY` stays `"760x1000"`: its width is still the opening width, and its height is the fallback before the content is measured.
- **What the owner sees.** A one-chart song opens short; Butterfly opens showing all 16 charts and the buttons; a song with more charts than fit opens at screen height with a scrollbar in the chart list. A resize in the session still sticks for later opens.

## 5. What Does Not Change

- No new settings key, no schema change, no new module, no new dependency. Persistence stays deferred (see §3).
- The page's constructor contract (six inputs) and the shell's `show(song, media)` call are unchanged. `library_visualizer.py` needs no change.
- The session geometry memory works exactly as today: a resize sticks for the session, and the geometry is still not persisted across restarts.
- The chart lines, the music line, the folder button, and the Play/Stop behaviour are unchanged. The minimum size `(560, 420)` is unchanged.
- **Issue #103 is not triggered.** That issue is about sharing the dialogs' window-restore rule — the on-screen check in `_geometry_for_open` that only restores a remembered position when a grabbable strip would be visible — which today lives in exactly two copies (Course Builder and Advanced Search). The song page does not carry that rule: its `_geometry_for_open` is just the saved geometry or the theme default, scaled, with no visibility check, because its memory is session-only and cannot go stale. This change adds no persisted position, so the page still needs no on-screen rule, and there are still two copies. If persistence is ever built, the page would need the rule as a third copy, and that follow-up should do the #103 extraction.
- The 760x1000 default is not removed: it remains the opening width and the fallback height.

## 6. Test Plan (for the implementation PR)

- Live tests under Xvfb in `tests/test_library_visualizer.py` (the page's existing live suites): a 1-chart song opens shorter than a 16-chart song (content sizing, not a hardcoded height); a 50-chart song opens no taller than the screen and its chart list scrolls (the scrollbar is shown and the canvas scroll region exceeds the viewport); a fitting list shows no scrollbar; the buttons are visible in all three cases; a resize in the session is still remembered for the next open (the existing geometry-persistence behaviour, pinned before the change).
- The existing live suites (`LiveSongPageOpenTests`, `LiveSongPageDirectTests`) must pass unchanged apart from the new sizing/scroll assertions — the page's visible behaviour for a fitting song is identical.
- Full suite green headless and under Xvfb; pyflakes and ruff clean; no added code line over 100 columns.
- A mutation check: the scroll region not following the labels, and the cap not applied, must each fail a test.
- The mousewheel binding on the canvas is asserted to work when the list overflows (at least that the binding is present).
- When content sizing produces a size-only geometry string (no `+x+y`), the window manager is confirmed to still place the window on-screen — the existing on-screen rule is not present, so this is the only placement path for the first open.
- Windows smoke (owner): Butterfly opens showing all 16 charts and the buttons at the bottom; a song with many Edit charts opens at screen height with a working scrollbar; a one-chart song opens short.

## 7. Open Questions — Resolved

- **Q1.** The cap is the screen height (`winfo_screenheight`). Should it instead be a fixed maximum (for example the current 1000 px default), so the window never grows past a familiar size even on a tall display? The recommendation is the screen height: it adapts to the display, and the scrollbar covers anything beyond it either way. **Resolved: screen height** (Grok agreed; owner accepted).
- **Q2.** The scrollbar is shown only when the chart list overflows. Should it always be visible, so the list's scrollability is obvious even before the owner tries to scroll? The recommendation is overflow-only: a fitting list looks exactly as it does today. **Resolved: overflow-only** (Grok agreed; owner accepted).
- **Q3.** Content sizing applies only on the first open in a session; after a resize, the saved geometry wins for later opens. Should the height instead be content-sized on every `show()`, with the saved geometry supplying only the position and width? The recommendation is the first-open rule: a deliberate resize still sticks, and the change to the session memory is nil. **Resolved: first-open rule** (Grok agreed; owner accepted).

---

*Written by Muse (Muse Spark 1.3).*
