# Scope: Barlow Condensed + Wendy in a single update

**Decision (Ian, 2026-11-22):** one update, both fonts. Barlow Condensed for all body and UI text; Wendy sparsely, for four title labels only — the strings the app controls. **Amended 2026-11-22: the song-page title stays Barlow.** The accent-fallback question made Wendy on user data not worth it: a fallback é mid-word reads as a defect, and controlling the fallback would need a per-run composite widget plus a coverage table. With the song title in Barlow, every Wendy string is fixed ASCII the app controls, so Wendy's coverage gaps can never trigger and the fallback question disappears entirely.

## Wendy's four usages (verified in code — the blast radius is exactly these)

| # | Where | File:line | Current font | Wendy size |
|---|---|---|---|---|
| 1 | Main application title ("ITGmania Librarian") | `library_librarian.py:326` | FONT_APP_TITLE, Segoe Semi 19 | **26 pt** |
| 2 | About dialog title (APP_NAME label) | `library_librarian.py:842` | FONT_DIALOG_TITLE, Segoe Semi 15 | **20 pt** |
| 3 | Advanced Search heading | `advanced_search.py:106` | FONT_DIALOG_TITLE, Segoe Semi 15 | **20 pt** |
| 4 | Course builder heading ("Build a new course") | `course_builder.py:105` | FONT_COURSE_TITLE, Segoe Semi 17 | **22 pt** |

Sizes are width-matched to Segoe Semibold by measurement: app title 19 → 26.0, dialog 15 → 20.4, course 17 → 22.4 (rounded down; the equalizing sizes are starting points and the final call is visual).

**The song-page title stays Barlow.** It currently shares FONT_DIALOG_TITLE with the About title and the Advanced Search heading (`song_page.py:186`), so the swap must split that constant: FONT_DIALOG_TITLE becomes Wendy 20 pt, and the song page gets its own Barlow title constant (e.g. FONT_SONG_TITLE, Barlow SemiBold 15 pt) — a one-line change plus the new constant. The song title is the only Wendy usage that was exposed to user data; with it in Barlow, the accent, `!`, Cyrillic, and CJK fallback questions are all moot, and no per-run composite widget or coverage table is needed.

**What this means in practice:**
- FONT_APP_TITLE, FONT_DIALOG_TITLE, and FONT_COURSE_TITLE all become Wendy, plus the new FONT_SONG_TITLE in Barlow. Nothing else uses those constants — verified by grep — so the swap touches exactly the labels above plus the one-line song-page split.
- FONT_PANEL_TITLE ("Distribution" heading) stays Barlow. FONT_MONO_BOLD (Consolas, Advanced Search query text) stays. Menu bar and window title bars are drawn by the OS and can't take Wendy — the About dialog's OS title "About ITGmania Librarian" stays in the system font; only the APP_NAME label inside it is Wendy.
- Wendy renders lowercase as capitals (measured: identical glyphs), so all four read as all-caps: ITGMANIA LIBRARIAN, ADVANCED SEARCH, BUILD A NEW COURSE. That is the SL look, not a defect.
- No accented-title verification is needed anymore: every Wendy string is fixed ASCII that Wendy covers (the four strings use only letters and spaces; Wendy covers all of those).

## Barlow's usage (everything else)

The remaining theme constants become Barlow Condensed at the equalizing sizes from the measurement report: body 11 pt (Regular; bold via the Bold face), small 10, entry 12, panel title 14 bold — plus the new FONT_SONG_TITLE (Barlow SemiBold 15 pt) for the song-page title. Headings that are currently Semibold map to Barlow SemiBold where the weight exists, else Bold. Table, dialogs, buttons, song-page body text, status bar — all Barlow. Column widths and TABLE_ROW_HEIGHT (27) stay; Barlow's line height at 9 pt is 14.4 px, exactly Segoe's, and at 11 pt it is 17.6 px, still under 27.

## Bundling and licensing

- New `fonts/` directory in the repo: Barlow Condensed statics (Light, Regular, SemiBold, Bold — 4 files, ~100 KB each), `wendy.ttf` (~10 KB), `OFL.txt` (SIL OFL 1.1, verified in the google/fonts directory for Barlow), and a short `FONTS.md` note recording Wendy's source (dafont.com/wendy.font, "100% Free" classification, no license text shipped) and the OFL terms for Barlow. The repo's code stays MIT; the fonts carry their own terms, recorded in that note.
- Miso is not in this update at all — no Miso files, no Miso license question.

## Loader design

- New Tk-free module (proposed name `library_fonts.py`; layer assignment is the proposal's call — it depends on nothing in the package except stdlib and ctypes, so layer 0 or 1). It owns: locating the bundled files, loading them, and reporting which families resolved.
- Windows: `AddFontResourceEx` with `FR_PRIVATE` via ctypes — per-process, no install, no admin, fonts vanish with the process. Called from `main()` before `tk.Tk()` is created (next to `declare_dpi_awareness()`). On failure, or on non-Windows, the loader reports nothing loaded and theme falls back to the Segoe sizes.
- Theme switch: `theme.py` gains the two font sets and a small setter the loader's result feeds before any widget is built (constants are read at widget construction, so the ordering is what matters, not a constructor change). No constructor contract changes anywhere; no new settings key; no schema change.
- Fallback is total: if either font fails to load, that font's usages fall back to Segoe at the old sizes. The app never fails to start over a font.

## Proposal, tests, verification

- **Proposal first** (short): a new module is a component boundary, and bundle-plus-per-process-load vs use-if-installed are defensible designs constraining later work. The proposal carries the loader design, the layer assignment, and the FONTS.md note shape. Then one implementation PR.
- **Tests:** loader unit tests (missing files → fallback, no crash; double-load idempotent; non-Windows path returns nothing loaded), theme tests for both font sets, full suite green. Mockup driver re-run (`~/workspace/overnight/mockup_driver.py`) with the real bundled files. No accented-title case is needed anymore — no Wendy string is exposed to user data.
- **Windows smoke check by Ian:** warranted here — the loading path is Windows-only and cannot be verified in this sandbox. The mockup screenshots are Linux rendering; the smoke check is the real verification.
- **Not in scope:** Miso in any form, the "Distribution" panel heading, menu-bar or title-bar fonts, any change to column widths, row height, or dialog geometry (dialogs size by content, so the bigger Wendy titles just make them wider).

## Open questions

- None blocking. One small call Ian may want to make at review time: whether the About dialog's "Version …" line stays Barlow (scope says yes — only the APP_NAME label is Wendy).
