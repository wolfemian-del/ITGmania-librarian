# Changelog

## Unreleased

- The app is now called ITGmania Librarian instead of ITGmania Library Visualizer: the window title, the About dialog and the settings folder all use the new name, and on first launch your settings folder moves to the new name, bringing your settings and saved library with it. Nothing else changes.
- Double-click a chart (or press Enter on it) to open the song page: the song's banner, background, jacket and CD title, its music file with its length and preview window, and all of its charts with meter, BPM and scores. A file that is missing or is not a PNG shows a placeholder, and a song whose folder is not under any known song folder says so with the folder button disabled. Play preview plays the song's sample window in the app (pygame-ce, optional — without it Play is disabled); Stop ends it early, and closing the page or opening another song stops it too. Playback of a chart with its own `#MUSIC` plays that file from the start for 12 seconds, since it has no sample window of its own. The page now opens at the height its song needs instead of a fixed height, and the chart list scrolls inside the window when a song has more charts than fit on the screen; a resize in the session is still remembered for the next open. The buttons at the bottom of the page now stay visible even when the window was resized short — before, a short saved height could push them off the window entirely.
- The launch command is now `python launch.py` instead of `python library_visualizer.py`. The app itself is unchanged: the nineteen modules now live in the `itgmania_library` package, and `launch.py` at the repository root starts it.
- A chart with an absurd Time value no longer renders as a hundreds-of-characters duration in the Time column; anything longer than 99 hours, 59 minutes reads as blank, the way a missing Time already does.
- Loading the library no longer fails outright when one cache file cannot be parsed; that file is skipped and counted in the load summary, the way an unreadable file already is.
- A numeric search value with an underscore in it (for example `meter:1_000`) no longer reads as a number; it matches nothing, the way an unreadable value already does, and the count line says so.
- The song page's preview window now comes from the song's own music file, stored on every chart row, instead of being guessed from the charts: a song whose charts all share one `#MUSIC` override no longer plays the song's sample window against that other track, and a chart with its own `#MUSIC` no longer keeps a window it should not have. The snapshot schema bumps to 6, so an old snapshot rebuilds once.
- A filter subscriber that raises an error no longer stops the remaining subscribers from being told about the change; the first failure is still reported after all of them have run. Today there is only one subscriber, so nothing changes visibly — this keeps a second one from being silently skipped.
- A batch of filter changes started inside another batch no longer refreshes the table when the inner block ends; the refresh waits for the outermost block, so nested batches refresh once. Nothing nests batches today, so nothing changes visibly.
- Loading the library (and syncing scores) no longer re-scans the whole Stats file for every Edit chart without a description; the Edit entries are indexed once per load instead, so a library with many undescribed Edits loads faster. The scores themselves are unchanged.
- The rule that decides whether Build a course and Advanced Search reopen where you left them now lives in one place instead of two identical copies (issue #103), with direct tests of each threshold. Nothing changes visibly: the windows reopen exactly as before. (Proposal 0016, step 1 of 4.)
- Build a course, Advanced Search, the song page, the Data paths dialog and About now open centered over the library window, instead of in the top-left corner of the screen. A window that would reach past the screen edge or under the taskbar is shifted back onto the screen, and a window taller than the usable screen is shortened to fit (the song page's tall chart list scrolls, as before). If the library window is minimized, they open centered on the screen. A place you moved Build a course or Advanced Search to is still remembered and restored exactly as before. (Proposal 0016, step 2 of 4.)
- Build a course, Advanced Search and the song page no longer remember a place they were never moved from: a window you open and close without moving or resizing it reopens centered over the library window next time, instead of pinning wherever it first appeared. A move or resize is still remembered. The song page now remembers a move or resize for the rest of the session only, the same way it did before, and opens at the height its song needs when you have not resized it. (Proposal 0016, step 3 of 4.)

## 1.3.0 - 2026-11-15

### Scores sync
- New File → Sync scores from Stats.xml: after a play session, refresh just the score columns from Stats.xml without re-parsing the cache (about 4–5 seconds instead of about 20 at 35k charts). It only updates scores for songs already in the library — new songs still need Load / refresh. When Stats.xml is newer than the saved library, the status line says so at startup.
- Edit charts that have both a `#DESCRIPTION` and a different `#CHARTNAME` now keep the right score across syncs (before, the sync could blank the score or show a sibling Edit's score). The snapshot format bumps from version 3 to 4, so snapshots written before this fix are discarded and rebuilt with the correction — no saved library keeps the old wrong behaviour.
- The sync now refuses with a clear message, changing nothing, when the selected Stats.xml contains no scores at all (a fresh profile, or the wrong file) or holds scores for other songs (a profile from another install) — instead of blanking every score and reporting success. If Stats.xml changes while a sync is running, the snapshot is not saved, so the startup hint fires and you re-sync for the latest scores. One bad row in a hand-edited snapshot no longer fails the whole sync.

### Library table
- The distribution panel's bars now show the rows they say they show: clicking a "nan" meter bar shows the NaN-meter charts instead of emptying the table, clicking a Difficulty bar shows all the rows it counts even when a difficulty name differs only by capitalisation or surrounding spaces, and clicking a high-precision meter bar (like 11.123456789) shows its chart instead of no rows.

### Other
- The app's internals were reorganised in two steps: the main window's loading, filtering and table code now live in their own components, and the data helpers were split into nine focused modules. These moves were not intended to change behavior.

## 1.2.1 - 2026-11-12

### Library table
- A song with a non-finite tempo (`#BPMS` of `inf`, `#DISPLAYBPM` of `nan`/`inf`) no longer fails the whole library load; its BPM cell is blank instead. A snapshot row with a non-finite `Time` (`"nan"`/`"1e999"`) no longer crashes the table build; its Time cell is blank.
- The distribution panel no longer prints `Mean: inf` or `Mean: nan` for a corrupt cache; summary stats use finite values only, and all NaN meters form a single bar with the true count.

### Startup and loading
- The cache path field now fills in with the usual ITGmania cache location for your platform when it exists, instead of always guessing a Windows-shaped path; on a fresh install with no cache folder yet, the field starts empty.
- When `settings.json` exists but can't be read, the status line says so and that defaults are being used, instead of silently discarding the file.
- When a restored snapshot's saved cache folder or Stats.xml no longer exists, the status line says so and points at File → Data paths…, instead of failing silently on the next refresh.
- The Data paths dialog is now a single modal window titled 'Where is your library?'; it opens once per session at startup when no snapshot was restored and the paths are not both usable, and Load / refresh opens it when the paths are invalid.
- Load / refresh now shows a determinate progress bar with a files-done count and an ETA, and a 'Saving snapshot…' phase at the end.

### Other
- The app is now DPI-aware on Windows, so it renders at the right physical size on 125% and 150% displays; stored window geometry and column widths are in canonical 100% units.
- A failed settings save no longer leaves a `settings.tmp` file behind.
- The snapshot and settings persistence now live in their own components in `library_data.py` (`SnapshotStore` and `SettingsStore`); these moves were not intended to change behavior.

## 1.2.0 - 2026-11-11

### Library table
- New Subtitle column: shows each song's subtitle, searchable by free text, hidden by default (turn it on under View → Columns).
- BPM now uses real tempos for filtering, sorting and the distribution chart; the BPM column shows `#DISPLAYBPM`, and a chart's own `#BPMS`/`#DISPLAYBPM` win over the song's when present. Tempos of zero or below are ignored.
- Ctrl+A selects all rows in the results table.
- The Pack, Type and Difficulty filter dropdowns are remembered across restarts, and fall back to "All …" when a saved value no longer exists.
- The count line now says when a search filter value cannot be read (for example `meter:abc`), and reports cache chart blocks skipped for missing metadata.

### Startup and loading
- The window paints before the saved library loads, and large libraries insert rows in time-boxed batches, so startup feels faster.
- Cache parsing is faster (about 11% of the parse loop).
- A mis-encoded or BOM-saved `settings.json` no longer crashes startup or silently loses settings, and deeply nested or oversized-number JSON no longer crashes the readers.

### Other
- Challenge difficulty tint lightened to meet contrast (`#c084fc`).
- First-run welcome text names the Load button.
- The distribution panel now lives in its own component; this move was not intended to change behavior.
- Proposal, PR and issue templates added for contributors.

## 1.1.0 - 2026-11-09

### Search
- Filter by a chart's radar note counts: directives such as `jumps:>10`, `mines:0` and `hands:0`, with comparisons (`>=`, `>`, `<=`, `<`) and ranges (`jumps:10-20`, `mines:1..5`). `taps:` counts taps and hold notes together, matching the Taps/Holds column.

### Courses
- Ctrl+Z undoes the last removal from the course queue (one step).
- Quitting the app asks before discarding a course queue you have not saved, and the dialog's close button asks the same as Escape does.
- Reloading the library with a queue in progress asks what to do with the queue instead of discarding it silently.
- Saving warns before writing when a queued entry matches more than one chart in the library.
- Queue rows use the same difficulty tints as the main table, selected rows keep white text, and Delete/Backspace removes the selected rows.
- The Course Builder window remembers its size and position, including across restarts, and recovers if it was left partly off-screen. Its default size is wider, so the controls row fits.

### Windows
- The Advanced Search window remembers its size and position too, with the same off-screen recovery.

### Under the hood
- The Course Builder and the Advanced Search dialog now live in their own modules (`course_builder.py`, `advanced_search.py`) and share the row-tint rule from `row_tints.py`; layout sizes are centralized in `theme.py`. These moves were not intended to change behavior.
- README corrections: score matching also keys on an Edit chart's description, and the layout constants live in `theme.py`.

## 1.0.0 - 2026-11-07

First release. Written against ITGmania v1.3.0 stable. Needs Python 3.10 or newer.

### Library table
- Reads ITGmania's song cache and a player's `Stats.xml` (read-only) into one table with chart details, best scores, grades, play counts and tech counts.
- Saves a snapshot of the parsed library, so later launches start from it until you choose Load / refresh.
- Sort by any column; drag headings to reorder and dividers to resize; show or hide columns by group.
- Rows are tinted by difficulty.
- Export the full library to CSV.

### Search and filters
- Free-text search plus field filters: meter, BPM, length, title, artist, pack, difficulty, grade, score, percent, NPS and tech counts.
- Advanced search window that fills from the search bar and keeps any filter it has no box for.
- Filter by pack, steps type, difficulty, and scored charts only.

### Distribution panel
- Optional side panel (needs `matplotlib`) charting Meter, Difficulty and BPM for the current view; clicking a bar filters the table.

### Courses
- Course builder: queue charts, reorder them, then save a new `.CRS` file or append to an existing one without changing its existing contents. It warns when trailing `#MODS` or `#GAINSECONDS` directives could affect the appended entries.

### Other
- Help → About shows the version and license.
- Every color and font is defined in `theme.py`.
- Released under the MIT License.
