# Implementation Proposal: Barlow Condensed body text and Wendy titles, bundled and loaded per-process

| | |
|---|---|
| **Status** | Accepted - 11/22/2026 |
| **Author** | Muse |
| **Date** | 2026-11-22 |
| **Base** | main `05cefcb` (PR #264 merged) |
| **Related** | `docs/fonts-barlow-wendy-scope.md` (the scope this proposal turns into a design); `docs/ROADMAP.md` (the font update is the immediate next step, scoped not a theme); board item "Font update — Barlow Condensed + Wendy" (Triaged, Scoped) |

---

In plain language: the app gets the Simply Love look the owner picked by blind comparison — Barlow Condensed for every bit of body and UI text, and Wendy for the four title labels the app itself writes. The font files travel with the app in a new `fonts/` folder and are loaded into the running process only, so nothing is installed on the machine and the app looks the same on any Windows PC. The one real decision in this proposal is where that loading lives and how the theme switches to the new fonts: a small new module owns the loading, and `theme.py` gains a setter that the startup code calls before any window is built. If either font fails to load, that font's text falls back to today's Segoe at today's sizes, and the app never fails to start over a font.

## Revision 1 (2026-11-22, from the Greptile and Grok reviews of PR #265)

Grok reviewed as sole reviewer and signed off: **Approve**. Every cited code fact holds against main `05cefcb`, all seven decisions are the right ones, the loader contract is complete, the test plan covers the important edges, and Q1 is agreed (the About dialog's "Version …" line stays Barlow). Greptile reviewed COMMENTED, confidence 4/5, safe to merge, with one P2 finding, confirmed and fixed here. What changed:

| Finding | Where it is folded in |
|---|---|
| The loader's argument disagreed: §4.1 said `load_fonts(fonts_dir)` while §4.3 called `load_fonts()` with no argument, leaving the implementer guessing who chooses the folder (Greptile P2) | §4.1 now defines `load_fonts(fonts_dir=None)` with the module-relative default; §4.3 calls it with no argument |
| The ARCHITECTURE.md amendment should also cover the layer-table date line and the module-inventory table (Grok, non-blocking) | §5 names the four spots to update; there is no date line on the layer table, so there is nothing to update there |
| Consider logging or returning the files that failed to register, useful for the Windows smoke check (Grok, non-blocking, not required by the contract) | Recorded here for the implementer, not a contract change: `FontLoadResult` already carries the files that did register, and the loader may log the failures for the smoke check |

## Erratum (2026-11-22, from the Claude Lane A review of PR #266)

The implementation departed from the accepted §4.1 text in one place, and clarified §4.2 in another. Both are recorded here rather than silently, on the owner's decision.

- **`FontLoadResult` also carries `failed`.** §4.1 as accepted said the failures were "recorded for the implementer, not a contract change" and that the loader "may log" them; the implementation instead returns the failed files as a fourth dataclass field. The field is additive and defaulted, and `main()` reads only `.barlow` and `.wendy`, so no caller breaks. `main()` now prints the failed files to stderr when the list is non-empty, so the Windows smoke check can read why the app is in Segoe — a dataclass field alone cannot be read from a double-click. Known limit, unchanged: on the error path (the register call raises) the loader still returns `failed=()` with both families `False`, which looks identical to the non-Windows result.
- **`apply_fonts` restores on a false flag.** §4.2 says the setter "rebinds the nine public names" and §6 requires "a reset to Segoe after each test"; a false flag therefore restores that family's Segoe values rather than leaving the names alone. That reading is a clarification, not a departure — a leave-alone setter could not provide the reset.

## 1. Background and Goal

The owner compared mockups of three fonts on the real app and picked Barlow Condensed over Yanone and Miso. Miso cannot be bundled at all (its license forbids redistributing it with source code), and Wendy's coverage gaps would show mid-word on accented song titles, so Wendy is used only on the four title strings the app controls and the song-page title stays Barlow — that amendment dropped the whole fallback question. The roadmap stages this as the immediate next step, a scoped update ahead of theme 2, with a short proposal first and then one implementation PR.

Modularity, up front: this change creates one new component boundary, a font-loader module, and alters `theme.py`'s contract (it gains a setter that rebinds its font constants). It creates no new settings key, no file format, and no constructor change anywhere. The loader depends on nothing in the package except the standard library, so it sits at layer 0 beside `library_geometry.py`.

Done means: Barlow everywhere Segoe UI was, Wendy on the four titles, the song-page title in Barlow, the app starting and looking right on the owner's Windows machine (the smoke check), the mockups re-run with the real bundled files, and the full suite green.

## 2. Current State (measured on main `05cefcb`)

Every font the window uses is a tuple in `theme.py` [CODE: `itgmania_library/theme.py:59-67`]:

| Constant | Today | Call sites |
|---|---|---|
| `FONT_BODY` | ("Segoe UI", 9) | body text everywhere |
| `FONT_BODY_BOLD` | ("Segoe UI Semibold", 9) | bold body text |
| `FONT_SMALL` | ("Segoe UI", 8) | small text |
| `FONT_ENTRY_LARGE` | ("Segoe UI", 10) | course title box |
| `FONT_PANEL_TITLE` | ("Segoe UI Semibold", 11) | "Distribution" heading, `distribution_panel.py:140` |
| `FONT_DIALOG_TITLE` | ("Segoe UI Semibold", 15) | Advanced Search heading, About title, song-page title |
| `FONT_COURSE_TITLE` | ("Segoe UI Semibold", 17) | "Build a new course" heading, `course_builder.py:105` |
| `FONT_APP_TITLE` | ("Segoe UI Semibold", 19) | main window title, `library_librarian.py:326` |
| `FONT_MONO_BOLD` | ("Consolas", 9, "bold") | Advanced Search query text |

45 uses of `theme.FONT_*` across six window files [CODE: grep count — `advanced_search.py` 10, `course_builder.py` 5, `data_paths_dialog.py` 2, `distribution_panel.py` 5, `library_librarian.py` 14, `song_page.py` 9]. The four Wendy sites are exactly the ones the scope doc verified: the app title (`library_librarian.py:326`), the About title (`library_librarian.py:842`), the Advanced Search heading (`advanced_search.py:106`) and the course-builder heading (`course_builder.py:105`). The song-page title shares `FONT_DIALOG_TITLE` (`song_page.py:186`), so the swap must split that constant.

Startup: `main()` [CODE: `library_librarian.py:869`] calls `declare_dpi_awareness()` [CODE: `library_librarian.py:874`, defined in `library_geometry.py:289`] and then builds the `LibraryApp` on a fresh `tk.Tk` root. There is no `fonts/` directory in the repo. The layer table puts `theme.py` and `library_geometry.py` at layer 0 [CODE: `docs/ARCHITECTURE.md:33`], and the architecture doc says the OS window system is touched in exactly two places, both in `library_geometry.py` [CODE: `docs/ARCHITECTURE.md:238`]. The import-surface test pins each module's public names [CODE: `tests/test_import_surface.py:103-105`, the `window_placement` precedent], and the theme guard covers the ten window-source files [CODE: `tests/test_theme.py:13-20`].

The sizes this proposal uses are the scope doc's width-matched equalizing sizes: body 11 pt, small 10, entry 12, panel title 14 bold, song-page title Barlow SemiBold 15; Wendy 26 pt for the app title, 20 for the dialog titles, 22 for the course title. The font files are fetchable from the sandbox now [RAN: `curl`, 2026-11-22 — `BarlowCondensed-Regular.ttf` 102,480 bytes and `BarlowCondensed-SemiBold.ttf` 109,428 bytes from `github.com/google/fonts`, `OFL.txt` 4,377 bytes from the same directory, and the Wendy download from `dl.dafont.com/dl/?f=wendy`, 4,367 bytes].

## 3. The Decisions

**D1. The loader is a new module, `library_fonts.py`, at layer 0.** It depends on nothing in the package except the standard library and `ctypes`, like `library_geometry.py` does for DPI awareness and the work-area lookup. `theme.py` stays layer 0 and never imports the loader; `main()` (layer 5) wires the two together. Alternative: fold the loading into `library_geometry.py`, where the other OS calls live. Rejected: it would put font knowledge in the geometry module and blur both modules' one-sentence descriptions, and the architecture doc's "exactly two places" line would still need amending either way.

**D2. Bundle the files and load them per-process.** The `fonts/` directory ships with the repo, and Windows loads them with `AddFontResourceEx` and `FR_PRIVATE` — per-process, no install, no admin, gone when the process ends. Alternatives: rely on the fonts being installed on the user's machine (rejected — they are not, and the app must look the same everywhere), or install them system-wide (rejected — needs admin and mutates the user's machine). The load happens in `main()` before `tk.Tk()` is created, next to `declare_dpi_awareness()`.

**D3. The theme switches by a setter, not by new constants at every call site.** `theme.py` holds both font sets and an `apply_fonts()` setter that rebinds the public `FONT_*` names; `main()` calls it with what the loader reported, before any widget is built (constants are read at widget construction, so the ordering is what matters). Alternatives: a font-set parameter through every window constructor (rejected — it would touch every constructor for one global choice), or parallel constant families with each call site picking (rejected — 45 call sites).

**D4. Fallback is total, per family.** If Barlow fails to load, every Barlow usage falls back to Segoe at the old sizes; if Wendy fails, the four titles fall back to Segoe Semibold at the old sizes. A half-loaded family (Barlow Regular without SemiBold) falls back as a whole, because mixed families would look broken. The app never fails to start over a font.

**D5. `FONT_DIALOG_TITLE` splits.** It becomes Wendy 20 pt, and the song page gets its own Barlow title constant, `FONT_SONG_TITLE` (Barlow SemiBold 15 pt), used at `song_page.py:186` — a one-line change plus the new constant. This is the scope doc's amendment, recorded here as the decision.

**D6. The mockup driver gets a repo home.** `~/workspace/overnight/mockup_driver.py` is cited by the landed scope doc, and repo documents may only cite repo paths, so the driver lands as `tools/mockup_driver.py` in the implementation PR, with its hardcoded worktree path replaced by a repo-root path derived from the file's own location. It is the same driver that produced the blind-comparison screenshots, so the implementation re-runs it with the real bundled files.

**D7. Provenance is recorded beside the files.** Barlow Condensed statics (Light, Regular, SemiBold, Bold) come from `github.com/google/fonts` (`ofl/barlowcondensed/`), `wendy.ttf` from `dafont.com/wendy.font`, `OFL.txt` ships beside Barlow, and `FONTS.md` records Wendy's source and "100% Free" classification and the OFL terms for Barlow. The repo's code stays MIT; the fonts carry their own terms in that note.

## 4. Recommended Design in Detail

**4.1 `library_fonts.py` (layer 0, no Tkinter, no package imports).** One-sentence description: given the folder the bundled fonts live in, it registers them with the operating system for this process only and reports which families resolved.

Public surface: `load_fonts(fonts_dir=None)` returns a frozen dataclass `FontLoadResult` with two booleans, `barlow` and `wendy`, and the list of files registered. When `fonts_dir` is None it defaults to the `fonts/` directory beside the package, derived from the module file (`Path(__file__).resolve().parent.parent / "fonts"`), never the working directory. `main()` calls it with no argument and takes that default; a test passes its own folder. On Windows it calls `AddFontResourceEx` with `FR_PRIVATE` through `ctypes`; it returns before touching `ctypes.windll` when `sys.platform != "win32"`, and catches `(AttributeError, OSError)`, so importing the module elsewhere still works. Loading twice is idempotent — a second call returns the same result without re-registering. A missing folder, a missing file or a corrupt file yields `False` for that family, never an exception. The module must not reach back into the package: no `theme` import, no settings read, no window code.

**4.2 `theme.py`: two sets and a setter.** The module holds the Segoe set (today's values, unchanged) and the Barlow/Wendy set, and `apply_fonts(*, barlow: bool, wendy: bool)` rebinds the public names: with `barlow` true, `FONT_BODY`, `FONT_BODY_BOLD`, `FONT_SMALL`, `FONT_ENTRY_LARGE` and `FONT_PANEL_TITLE` take the Barlow sizes and `FONT_SONG_TITLE` takes Barlow SemiBold 15; with `wendy` true, `FONT_DIALOG_TITLE`, `FONT_COURSE_TITLE` and `FONT_APP_TITLE` take the Wendy sizes. `FONT_MONO_BOLD` stays Consolas in both sets. Importing the module leaves the Segoe values in place, so any test that never calls the setter sees today's fonts.

**4.3 Wiring in `main()`.** After `declare_dpi_awareness()` and before `tk.Tk()`: `result = load_fonts()` then `theme.apply_fonts(barlow=result.barlow, wendy=result.wendy)`. No other call site changes, except `song_page.py:186`, which reads `FONT_SONG_TITLE` instead of `FONT_DIALOG_TITLE`. The four Wendy sites change only through the rebinding — their lines are untouched.

**4.4 `fonts/` contents.** `BarlowCondensed-Light.ttf`, `BarlowCondensed-Regular.ttf`, `BarlowCondensed-SemiBold.ttf`, `BarlowCondensed-Bold.ttf`, `wendy.ttf`, `OFL.txt`, `FONTS.md`. The implementation PR fetches the files from the sources in D7 and verifies the sizes against the §2 figures.

**4.5 What the loader must not do.** Never raise on a missing or corrupt file; never write outside the process (private registration only, no install); never import Tkinter; never read settings or the snapshot.

## 5. What Does Not Change, and What Does on Purpose

Does not change:

- Column widths, `TABLE_ROW_HEIGHT` (27), dialog geometry, menu-bar or title-bar fonts (drawn by the OS), `FONT_MONO_BOLD`, the distribution chart's text sizes (matplotlib picks its own family), and the About dialog's "Version …" line, which stays Barlow (see Q1).
- No new settings key, no schema change, no constructor change anywhere, no settings-file migration.
- Miso in any form; the "Distribution" panel heading stays Barlow (it is `FONT_PANEL_TITLE`, in the Barlow set).

Deliberately changed:

- Every `FONT_*` value the window reads, through the setter — the only call site that changes by hand is `song_page.py:186`.
- `docs/ARCHITECTURE.md`: the layer diagram (layer 0 gains `library_fonts.py`), the Shared foundations row, the module-by-module paragraph, and the module-inventory table (a new row for `library_fonts.py`); the "exactly two places" line becomes three places across two modules (geometry: work-area lookup and DPI awareness; fonts: font registration); the entry-point paragraph gains the font load. There is no date line on the layer table, so there is nothing to update there.
- `docs/fonts-barlow-wendy-scope.md`: its mockup-driver citation now points at `tools/mockup_driver.py`.

## 6. Test Plan (for the implementation PR)

One PR, naming this proposal and saying it does not depart from it.

- **Loader unit tests** (`tests/test_library_fonts.py`, new): a missing fonts folder returns both `False` with no exception; a corrupt file returns `False` for its family; loading twice is idempotent; the non-Windows path returns nothing loaded. The platform check is written so the test can exercise it without a Windows machine.
- **Theme tests:** both sets' values (Barlow sizes, Wendy sizes, `FONT_SONG_TITLE`), the setter rebinding all nine names, and a reset to Segoe after each test so no test leaks a font set into the next.
- **Import surface:** a pin for `library_fonts` in `tests/test_import_surface.py`, in the shape of the `window_placement` pin. The theme-usage guard in `tests/test_theme.py` covers `FONT_SONG_TITLE` automatically, since it derives its names from usage.
- **Full suite:** `python -m unittest discover -s tests` green (934 tests, 74 skipped headless, at the base).
- **Mockups:** the driver re-run under Xvfb from `tools/mockup_driver.py` with the real bundled files, producing the Barlow shot for comparison against the earlier mockups.
- **Docs:** `CHANGELOG.md` gains an Unreleased entry; `docs/ARCHITECTURE.md` as in §5; `README.md` line 71 still describes the theme file correctly and needs no change beyond the fonts note if the layout is listed.
- **Windows smoke check by the owner:** warranted — the loading path is Windows-only and cannot be verified in this sandbox. The mockup screenshots are Linux rendering; the smoke check is the real verification.

## 7. Open Questions for Reviewers

- **Q1.** The About dialog's "Version …" line stays Barlow (only the `APP_NAME` label is Wendy). Recommended: yes, as the scope doc says.

---

*Written by Muse.*
