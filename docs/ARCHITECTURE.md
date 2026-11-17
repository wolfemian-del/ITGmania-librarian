# Architecture

This is the map of the code for a reader who wants to change it. The user
guide stays in `README.md`.

## Launch

Run `launch.py` from the repository root (`python launch.py`). It is the
only file you run: it imports `main` from
`itgmania_library.library_visualizer` and calls it. The other 18 modules
live in the `itgmania_library` package and are imported by it (directly or
through each other), by their absolute package names
(`from itgmania_library.library_sources import ...`). As an aside,
`python -m itgmania_library` from the repo root launches the app too,
through the package's `__main__.py`.

## Layers

A module only imports modules in lower layers. The layering below was
measured from the import graph (no cycles) at v1.3.0, not drawn from intent.

```
5  library_visualizer.py — the shell (LibraryApp)
4  library_table.py
3  library_loader.py · library_stores.py · advanced_search.py
   distribution_panel.py · data_paths_dialog.py
2  library_filter.py · course_builder.py · library_sources.py
   library_dialog_query.py · library_distribution.py
1  library_format.py · library_search.py · row_tints.py
0  library_constants.py · library_geometry.py · library_course.py · theme.py
```

Read top to bottom as "built from". The shell builds the UI components, the
components read the data modules, and the data modules depend only on each
other and on the standard library.

Two naming facts to know before you trust the prefixes:

- The `library_` prefix does **not** mean Tk-free. The nine Tk-free data
  modules are `library_constants`, `library_format`, `library_sources`,
  `library_geometry`, `library_course`, `library_search`,
  `library_dialog_query`, `library_stores` and `library_distribution`.
  `library_loader`, `library_filter` and `library_table` are UI components
  that carry the same prefix: the loader and the table import Tkinter, while
  the filter does not import it (it works on the widgets it is handed, so a
  Tk-free stand-in can drive it in tests).
- The UI components without the prefix are `advanced_search`,
  `course_builder`, `data_paths_dialog` and `distribution_panel`, plus
  `row_tints` and `theme`.

## Modules

"Tests" is the file that covers the module; live
(window) tests for the UI components stay in `tests/test_library_visualizer.py`.

| Module | What it holds | Tests |
| --- | --- | --- |
| `itgmania_library/library_visualizer.py` | the shell: `LibraryApp`, the menu, and the `main()` entry point | `tests/test_library_visualizer.py` |
| `itgmania_library/library_loader.py` | the load/sync engine: scan and sync workers, result queue, generation counters, snapshot counters | `tests/test_library_loader.py` |
| `itgmania_library/library_search.py` | the search language: parser, matcher, and the numeric-bound helpers | `tests/test_library_search.py` |
| `itgmania_library/course_builder.py` | the Build-a-course dialog and its queue | `tests/test_course_builder.py` |
| `itgmania_library/library_table.py` | the song table: sorting, column order and widths, row tinting | `tests/test_library_table.py` |
| `itgmania_library/distribution_panel.py` | the distribution side panel and its charts | `tests/test_ui_distribution.py` |
| `itgmania_library/library_sources.py` | scores, cache, and path helpers | `tests/test_library_sources.py` |
| `itgmania_library/library_distribution.py` | the distribution charts: meter, difficulty, and BPM aggregation | `tests/test_distribution.py` |
| `itgmania_library/advanced_search.py` | the Advanced Search dialog | `tests/test_advanced_search.py` |
| `itgmania_library/library_stores.py` | persistence: the snapshot and settings stores | `tests/test_snapshot_store.py`, `tests/test_settings_store.py` |
| `itgmania_library/data_paths_dialog.py` | the Data paths dialog | `tests/test_data_paths_dialog.py` |
| `itgmania_library/library_filter.py` | the filter pipeline: the five filter variables, traces, search debounce | `tests/test_library_filter.py` |
| `itgmania_library/library_course.py` | .crs text-format helpers: formatting, parsing, trailing-modifier detection, field validation | `tests/test_library_course.py` |
| `itgmania_library/library_format.py` | formatting and sort-key helpers | `tests/test_library_format.py` |
| `itgmania_library/library_dialog_query.py` | the Advanced Search dialog's query conversion | `tests/test_library_dialog_query.py` |
| `itgmania_library/library_geometry.py` | window geometry and DPI helpers | `tests/test_library_geometry.py` |
| `itgmania_library/theme.py` | every color, font, and fixed size the window uses | `tests/test_theme.py` |
| `itgmania_library/row_tints.py` | the difficulty row tints, shared by the table and the course builder | `tests/test_row_tints.py` |
| `itgmania_library/library_constants.py` | the shared column and grade tables | `tests/test_import_surface.py` |

## How the pieces fit

**The filter is the single holder of the rows inside the UI.** The loader
hands the loaded rows to the filter; the table reads the rows through the
filter; the main window subscribes its refresh to the filter's change
notification. The table owns the sort keys, the column order and widths, and
the row tinting, and exposes the layout and the selected and library rows the
main window reads back.

**Dialogs and the panel persist differently by design.** A dialog's geometry
is a value passed in and a callback reporting it back out, while the panel's
variables are shared objects, because the View menu and the settings save
both bind them directly.

**The shell is thin.** `LibraryApp` builds the components and wires them
together, then keeps only thin `load_data` / `sync_scores` delegation to the
loader. If a behaviour needs the window, it lives in a component; if it does
not need the window, it lives in a Tk-free data module with tests in `tests/`.

## Component construction

Each component is built by the main window with the few things it needs.

- **Build-a-course dialog** (`course_builder.py`): its parent window, the
  status variable, the button factory, a way to read the table's selected
  rows, a way to read every row in the library, the remembered window
  geometry, a callback that reports the geometry when the window closes, and
  the display scale factor.
- **Advanced Search dialog** (`advanced_search.py`): its parent window, the
  three widget factories, the search variable it edits, the remembered window
  geometry, a callback that reports the geometry when the window closes, and
  the display scale factor.
- **Distribution panel** (`distribution_panel.py`): the button factory, the
  four variables it shares with the window (the search and difficulty
  variables, its show/hide variable, and its metric selector), a way to pull
  rows when the chart's own metric is the active filter, a callback that
  applies a chart click or Clear as one batched filter change, the settings
  save, and the display scale factor.
- **Data paths dialog** (`data_paths_dialog.py`): its parent window, the two
  path variables it edits, a zero-argument load callback, the settings save,
  the entry and button factories, the display scale factor, and a callable
  that reports whether the paths match the loaded snapshot.
- **Load/sync engine** (`library_loader.py`): the snapshot store, the two
  path variables, the status variable, the progress bar, the Load button, a
  callable that enables or disables File → Sync scores, the callbacks that
  report a finished load or sync and a load that found nothing, the Data
  paths dialog, the settings save, the root window, a callback that reports
  discarded settings, and whether saved settings contained path keys. It owns
  the loaded rows, the snapshot-summary counters, the scan/sync workers, the
  result queue, and the generation counters.
- **Filter pipeline** (`library_filter.py`): the five filter variables, the
  search entry, the three dropdown widgets, and the root window. It owns the
  rows it filters, the variable traces, and the search debounce.
- **Song table** (`library_table.py`): the table frame, the filter, the
  display scale factor, the column and group visibility objects the View menu
  binds, the saved column order, widths, and sort keys, the count label, the
  settings save, and a callable that pushes the visible rows to the
  distribution panel.
