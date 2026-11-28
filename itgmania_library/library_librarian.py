"""The shell: the main window, the menu, and the app's entry point.

LibraryApp builds the window and wires the app together. It creates
the two stores (the snapshot store and the settings store) and the Tk
variables seeded from the saved settings, then constructs every
component — the loader, the filter, the table, the song page, the
distribution panel, the course builder, the Advanced Search dialog
and the Data paths dialog — and subscribes the table refresh to the
filter's change notification. The menu, the settings save, the CSV
export and the About dialog live here, and so does the song-page
opening: the shell resolves the song's media, holds the one preview
player, and hands the page its play, stop and open-folder callbacks.

The shell is thin on purpose: load and sync are thin load_data /
sync_scores delegation to the loader, and any behaviour that needs
the window lives in a component while anything that does not need it
lives in a Tk-free data module. The startup order is part of the
contract: the window, then the stores, then the variables, then the
components, then the loader starts and the saved snapshot loads once
the window has painted. main() declares DPI awareness, builds the
root window and the app, and runs the event loop; launch.py imports
main().

Tests: tests/test_library_librarian.py (including the live window
tests and the song-page tests).
"""

from __future__ import annotations

import csv
import os
import sys
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:
    tk = None
    filedialog = None
    messagebox = None
    ttk = None
from pathlib import Path

# The release number, shown in Help > About. Keep it equal to the newest heading in CHANGELOG.md (a test checks).
__version__ = "1.4.0"

from itgmania_library import theme
from itgmania_library.advanced_search import AdvancedSearch
from itgmania_library.course_builder import CourseBuilder
from itgmania_library.data_paths_dialog import DataPathsDialog
from itgmania_library.library_filter import LibraryFilter
from itgmania_library.library_loader import LibraryLoader
from itgmania_library.library_media import (
    SongPreviewPlayer,
    build_song_media,
    charts_for_song,
    open_song_folder,
    player_available,
    song_roots,
)
from itgmania_library.library_table import LibraryTable
from itgmania_library.song_page import SongPage
from itgmania_library.distribution_panel import DistributionPanel
from itgmania_library.library_constants import (
    APP_NAME, COLUMN_GROUPS, DEFAULT_VISIBLE_COLUMNS, HEADERS)
from itgmania_library.library_geometry import (
    canonical_geometry,
    decide_main_window_save,
    declare_dpi_awareness,
    dpi_scale_factor,
    opening_geometry,
    parse_window_geometry,
    parse_window_size,
    saved_geometry_visible,
    scale_geometry,
    scale_pixels,
    work_area_of,
)
from itgmania_library.library_fonts import load_fonts
from itgmania_library.window_placement import WindowPlacement
from itgmania_library.library_sources import cache_dir_candidates, first_existing_directory
from itgmania_library.library_stores import (
    LIBRARY_CACHE_SCHEMA_VERSION,
    ManifestStore,
    SettingsStore,
    SnapshotStore,
    _migrate_config_dir,
    _settings_file_path,
    _valid_window_geometry,
    _valid_window_position,
)


class LibraryApp:
    # Defaults for state that is only set later, so every instance has these attributes.
    # The display scale factor (1.0 at 100% DPI): bare instances in tests
    # have no window to measure, so they read canonical units as-is.
    _dpi_scale = 1.0
    # The main window's remembered place (Proposal 0023): the saved
    # geometry and maximized flag, loaded at startup and written at
    # exit; the tracked last-normal-geometry, last-shown-maximized and
    # opening baseline, seeded by the placement step. The <Configure>
    # binding keeps the tracked value current; the <Map> binding
    # settles the baseline once, when the window is first shown.
    # Bare instances in tests have no window to place, so these read
    # as "never placed".
    main_window_geometry = None
    main_window_maximized = False
    _main_window_last_geometry = None
    _main_window_last_maximized = False
    _main_window_opening_geometry = None
    _main_window_baseline_settled = False

    def __init__(self, root: tk.Tk):
        self.root = root
        self._init_window()
        self._init_stores()
        self._place_main_window()
        self._init_variables()
        self._declare_late_state()
        self._init_dialog()
        self._style()
        self._build()
        self._init_loader()

    def _init_window(self):
        """Set up the main window itself.

        Needs: self.root. Provides: the title, the DPI scale factor
        (self._dpi_scale), the minimum size, the background. The opening
        geometry is set by _place_main_window, once the settings exist,
        not here (Proposal 0023).
        """
        self.root.title(APP_NAME)
        # The display scale factor (issue #51): 1.0 at 100% DPI, 1.5 at
        # 150%. Every pixel number below is stored in canonical 100%
        # units and scaled here, at the point it reaches the window.
        self._dpi_scale = dpi_scale_factor(self.root.winfo_fpixels("1i"))
        self.root.minsize(scale_pixels(theme.WINDOW_MIN_SIZE[0], self._dpi_scale),
                          scale_pixels(theme.WINDOW_MIN_SIZE[1], self._dpi_scale))
        self.root.configure(bg=theme.BG_WINDOW)

    def _init_stores(self):
        """Create the three stores that own the files on disk.

        Needs: nothing built yet. Provides: self.settings_path,
        self._snapshot_store (library_cache.json), self._manifest_store
        (library_cache_manifest.json), self._settings_store
        (settings.json) and self.saved_settings, the settings read once.
        """
        # The config dir moved with the rename (proposal 0015): migrate it
        # once before anything reads settings or the snapshot.
        self.settings_path = _migrate_config_dir(self._settings_file_path())
        # The snapshot store owns library_cache.json (proposal 0008); its
        # path is derived once here from the settings path, and it is built
        # against the current schema version.
        self._snapshot_store = SnapshotStore(
            self.library_cache_path, HEADERS, LIBRARY_CACHE_SCHEMA_VERSION)
        # The manifest store owns library_cache_manifest.json (proposal
        # 0018); its path is derived the same way, from the settings path.
        self._manifest_store = ManifestStore(self.library_cache_manifest_path)
        # The settings store owns settings.json (proposal 0008). Loading it
        # seeds the store's dedup baseline; a failure is remembered on the
        # store (last_read_error) and reported once the window is built
        # (_report_discarded_settings), since the file is read before the
        # status line exists.
        self._settings_store = SettingsStore(self.settings_path)
        self.saved_settings = self._settings_store.load()

    def _place_main_window(self):
        """Place the main window where it was left, or centered in the work area.

        Needs: self.root, self._dpi_scale, self.saved_settings. Provides:
        the root's opening geometry and maximized state, the saved
        main-window attributes, and the tracked last-normal-geometry,
        last-shown-state and opening-baseline attributes. Runs immediately
        after _init_stores, before _init_variables, so the geometry is set
        before any widget is built (Proposal 0023). The root is not mapped
        until mainloop, so placing it here shows no flash.
        """
        saved = self._valid_main_window_geometry(
            self.saved_settings.get("main_window_geometry"))
        saved_maximized = bool(self.saved_settings.get("main_window_maximized", False))
        self.main_window_geometry = saved
        self.main_window_maximized = saved_maximized
        # The desktop box, from the root's virtual-desktop readings (the
        # same readings WindowPlacement._surroundings uses for the dialogs).
        left = self.root.winfo_vrootx()
        top = self.root.winfo_vrooty()
        desktop = (left, top, left + self.root.winfo_vrootwidth(),
                   top + self.root.winfo_vrootheight())
        # The work area: the monitor holding the saved place when it is
        # visible there, the primary's when it is not or nothing is saved
        # (Proposal 0023, D3). The saved point is in canonical 100%
        # units; MonitorFromPoint takes physical pixels, so it is scaled
        # first. Off Windows the lookup returns None and the opening
        # rule falls back to the desktop.
        work_area = work_area_of()
        if saved is not None:
            parsed = parse_window_geometry(saved)
            if parsed is not None:
                point = (scale_pixels(parsed[2], self._dpi_scale),
                         scale_pixels(parsed[3], self._dpi_scale))
                saved_work_area = work_area_of(point=point)
                if saved_geometry_visible(saved, desktop, self._dpi_scale,
                                          saved_work_area, theme.WINDOW_MIN_SIZE):
                    work_area = saved_work_area
        default_size = parse_window_size(
            scale_geometry(theme.WINDOW_DEFAULT_GEOMETRY, self._dpi_scale))
        geometry = opening_geometry(
            saved, default_size, desktop, self._dpi_scale, anchor=None,
            work=work_area or desktop, min_size=theme.WINDOW_MIN_SIZE)
        self.root.geometry(geometry)
        if saved_maximized:
            # After the geometry is set, so the restored normal geometry
            # is the one behind the maximized window. Some platforms
            # maximize through an attribute, not a state (Proposal 0023,
            # item 5): a saved maximized flag copied to such a machine
            # must not crash startup.
            try:
                self.root.state("zoomed")
            except tk.TclError:
                pass
        canonical = canonical_geometry(geometry, self._dpi_scale)
        self._main_window_opening_geometry = canonical
        self._main_window_last_geometry = canonical
        self._main_window_last_maximized = saved_maximized
        self._main_window_baseline_settled = False
        self.root.bind("<Configure>", self._on_main_window_configure)
        self.root.bind("<Map>", self._on_main_window_map)

    def _on_main_window_configure(self, event):
        """Track the main window's place and shown state (Proposal 0023, D4).

        A binding on the root also receives every descendant's Configure
        events, so only the root's own events count; a resize drag costs
        one assignment per event and no I/O, and nothing is written here.
        The baseline is not touched here: the first normal Configure
        can be the owner's first move, and refining the baseline to it
        would lose the move. An unsettled (1x1) reading records
        nothing.
        """
        if event.widget is not self.root:
            return
        state = self.root.state()
        if state == "normal":
            geometry = self.root.geometry()
            parsed = parse_window_geometry(geometry)
            if parsed is None or parsed[0] <= 1 or parsed[1] <= 1:
                return
            self._main_window_last_geometry = canonical_geometry(
                geometry, self._dpi_scale)
            self._main_window_last_maximized = False
        elif state == "zoomed":
            self._main_window_last_maximized = True
        # "iconic" (minimized) records nothing: minimizing does not clear
        # a saved maximized flag.

    def _on_main_window_map(self, event):
        """Settle the opening baseline when the window is first shown.

        The geometry the window manager actually gives can differ from
        the geometry requested (Proposal 0023, D4): the baseline — and
        the tracked last-normal-geometry, which at the opening is the
        same geometry — must be the geometry the window opened with, so
        a close without a move compares against the placed geometry,
        not the requested one. The proposal sketched this at first
        idle, but before the content is laid out geometry() still reads
        1x1, and an idle callback that reschedules until the size
        settles spins the idle queue without end (observed under Xvfb);
        a <Configure> is no better, because the placement Configure
        fires while the window is still unmapped and no Configure
        follows the mapping. The <Map> event fires once, when the
        window becomes visible, with the state normal and the geometry
        settled — the window actually placed. Only while normal: the
        geometry() reading of a zoomed root is the stale pre-maximize
        value, so for a window that opens maximized the seeded values
        stand. The baseline settles on the first Map either way, so a
        later Map (after a minimize and restore) never redefines it
        to a place the owner moved to.
        """
        if event.widget is not self.root:
            return
        if self._main_window_baseline_settled:
            return
        self._main_window_baseline_settled = True
        if self.root.state() != "normal":
            return
        geometry = self.root.geometry()
        parsed = parse_window_geometry(geometry)
        if parsed is None or parsed[0] <= 1 or parsed[1] <= 1:
            return
        canonical = canonical_geometry(geometry, self._dpi_scale)
        self._main_window_opening_geometry = canonical
        self._main_window_last_geometry = canonical

    def _init_variables(self):
        """Create the Tk variables, seeded from the saved settings.

        Needs: self.saved_settings. Provides: the path, filter, search,
        column-visibility, group-visibility and distribution variables.
        """
        default_cache = first_existing_directory(cache_dir_candidates())
        default_stats = Path.cwd() / "Stats.xml"
        self.cache_var = tk.StringVar(value=self.saved_settings.get(
            "cache_dir", str(default_cache) if default_cache is not None else ""))
        self.stats_var = tk.StringVar(value=self.saved_settings.get(
            "stats_file", str(default_stats) if default_stats.is_file() else ""))
        self.search_var = tk.StringVar()
        saved_pack = self.saved_settings.get("filter_pack")
        self.pack_var = tk.StringVar(value=saved_pack if isinstance(saved_pack, str) else "All packs")
        saved_type = self.saved_settings.get("filter_type")
        self.type_var = tk.StringVar(value=saved_type if isinstance(saved_type, str) else "All types")
        saved_difficulty = self.saved_settings.get("filter_difficulty")
        self.diff_var = tk.StringVar(value=saved_difficulty if isinstance(saved_difficulty, str) else "All difficulties")
        self.scored_var = tk.BooleanVar(value=False)
        saved_visibility = self.saved_settings.get("column_visibility", {})
        if not isinstance(saved_visibility, dict):
            saved_visibility = {}
        # A column with no saved choice follows the default set; saved choices are always kept.
        self.column_visibility = {
            column: tk.BooleanVar(value=saved_visibility.get(column)
                                  if isinstance(saved_visibility.get(column), bool)
                                  else column in DEFAULT_VISIBLE_COLUMNS)
            for column in HEADERS
        }
        if not any(variable.get() for variable in self.column_visibility.values()):
            self.column_visibility[HEADERS[0]].set(True)
        # One check box per group in the Columns menu; it is checked while every column of the group is shown.
        self.group_visibility = {group: tk.BooleanVar() for group in COLUMN_GROUPS}
        self.show_distribution_panel = tk.BooleanVar(
            value=bool(self.saved_settings.get("show_distribution", False))
        )
        saved_metric = self.saved_settings.get("distribution_metric", "Meter")
        self.distribution_metric = tk.StringVar(
            value=saved_metric if saved_metric in ("Meter", "Difficulty", "BPM") else "Meter"
        )

    def _declare_late_state(self):
        """Declare, as None, every attribute that a later step fills in.

        Needs: nothing. Provides: the names _build, _init_loader and the
        dialogs assign later, listed in one place with who fills each.
        """
        # Attributes that are filled in after this point. Declaring them here lists everything the window
        # holds in one place; the comments name where each one is filled in.
        # Widgets and variables created by _build(); None until then:
        self.status = None
        self.search_entry = None
        self._filter = None  # the filter pipeline, built in _build once the search bar exists
        self._table = None  # the song table, built in _build after the filter and the panel
        # The loader is built last, by _init_loader. Until then the dialog's
        # delegates and the buttons read this attribute only when clicked,
        # and Tk delivers no click before mainloop (proposal 0014).
        self._loader = None  # the load/sync engine, built by _init_loader
        self.pack_filter = None
        self.type_filter = None
        self.diff_filter = None
        self.dist_button = None
        self.content_frame = None
        self.table_frame = None
        self.progress = None
        self.count_label = None
        self.load_button = None
        self._file_menu = None  # the File menu, built in _build_menubar
        # Window geometry remembered for the two dialogs, set in _build:
        self.course_geometry = None
        self.advanced_search_geometry = None
        self.song_page_geometry = None
        # Dialogs: a window attribute is None while that dialog is closed. The course builder is a
        # separate component (course_builder.py) that owns its window and queue; it is created in
        # _build, once the status variable exists. The Advanced Search component
        # (advanced_search.py) and the distribution panel component (distribution_panel.py)
        # follow the same pattern.
        self.advanced_search = None
        self.about_window = None
        self.course_builder = None
        self.distribution_panel = None
        # The song page (song_page.py, proposal 0011 stage 3): built in
        # _build, once, and re-raised by show(); None until then. The
        # preview player (stage 4) is built with it; the media record
        # for the song the page is showing is kept for the play callback,
        # which needs the song's music length to normalize the window.
        self.song_page = None
        self._preview_player = None
        self._song_media = None

    def _init_dialog(self):
        """Build the Data paths dialog, before the loader that drives it.

        Needs: the path variables, _save_settings, the widget factories and
        the DPI scale. Provides: self._data_paths_dialog.
        """
        # The dialog and the loader need each other: the dialog calls the
        # loader's load and path check, and the loader drives the dialog. One
        # has to be built first, so the dialog gets two shell delegates that
        # read self._loader when called (proposal 0009; 0014 Q6). The late-bound
        # references in this window, all safe because Tk runs no callback
        # before mainloop:
        #   - these two delegates and the buttons/menu items bound to load_data,
        #     sync_scores and export_csv read self._loader;
        #   - the Course Builder's two row delegates read self._table, which
        #     _build creates after the builder;
        #   - the Distribution Panel's table-frame callable (proposal 0005 Q5)
        #     reads self.table_frame, created after the panel.
        self._data_paths_dialog = DataPathsDialog(
            self.root, self.cache_var, self.stats_var,
            load_callback=self.load_data,
            save_settings=self._save_settings,
            button_factory=self._button, entry_factory=self._entry,
            dpi_scale=self._dpi_scale,
            paths_match_loaded=self._paths_match_loaded)

    def _init_loader(self):
        """Build the loader, report discarded settings, and start the loader.

        Needs: the status, progress and Load button made in _build, the
        dialog, and the stores. Provides: self._loader, started. The order is
        part of the contract: report any discarded settings first, then start.
        """
        saved = self.saved_settings
        self._loader = LibraryLoader(
            snapshot_store=self._snapshot_store,
            manifest_store=self._manifest_store,
            cache_var=self.cache_var,
            stats_var=self.stats_var,
            status=self.status,
            progress=self.progress,
            load_button=self.load_button,
            set_sync_menu_state=self._set_sync_menu_state,
            on_library_changed=self._on_library_changed,
            on_nothing_loaded=self._on_nothing_loaded,
            report_discarded_settings=self._report_discarded_settings,
            save_settings=self._save_settings,
            dialog=self._data_paths_dialog,
            had_saved_paths="cache_dir" in saved or "stats_file" in saved,
            root=self.root)
        self._report_discarded_settings()
        self._loader.start()

    def _style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background=theme.BG_TABLE, foreground=theme.TEXT_TABLE, fieldbackground=theme.BG_TABLE,
                        rowheight=scale_pixels(theme.TABLE_ROW_HEIGHT, self._dpi_scale), borderwidth=0, font=theme.FONT_BODY)
        style.configure("Treeview.Heading", background=theme.BG_TABLE_HEADING, foreground=theme.TEXT_HEADING, relief="flat",
                        font=theme.FONT_BODY_BOLD)
        style.map("Treeview", background=[("selected", theme.SELECTION_BG)], foreground=[("selected", theme.TEXT_ON_ACCENT)])
        style.configure("TCombobox", fieldbackground=theme.BG_INPUT, background=theme.BG_INPUT, foreground=theme.TEXT_PRIMARY)
        style.map(
            "TCombobox",
            fieldbackground=[
                ("readonly", "focus", theme.BG_INPUT),
                ("readonly", "pressed", theme.BG_INPUT),
                ("readonly", theme.BG_INPUT),
                ("focus", theme.BG_INPUT),
                ("pressed", theme.BG_INPUT),
                ("active", theme.BG_INPUT),
            ],
            foreground=[
                ("disabled", theme.TEXT_DISABLED),
                ("readonly", "focus", theme.TEXT_PRIMARY),
                ("readonly", "pressed", theme.TEXT_PRIMARY),
                ("readonly", theme.TEXT_PRIMARY),
                ("focus", theme.TEXT_PRIMARY),
                ("pressed", theme.TEXT_PRIMARY),
                ("active", theme.TEXT_PRIMARY),
            ],
            selectbackground=[("readonly", theme.ACCENT_BG), ("focus", theme.ACCENT_BG)],
            selectforeground=[("readonly", theme.WHITE), ("focus", theme.WHITE)],
            background=[("pressed", theme.BG_INPUT), ("active", theme.BG_INPUT)],
            arrowcolor=[("disabled", theme.TEXT_DISABLED), ("!disabled", theme.TEXT_PRIMARY)],
        )
        style.configure("Horizontal.TProgressbar", troughcolor=theme.BG_TABLE_HEADING, background=theme.ACCENT)
        self.root.option_add("*TCombobox*Listbox.background", theme.BG_INPUT)
        self.root.option_add("*TCombobox*Listbox.foreground", theme.TEXT_PRIMARY)
        self.root.option_add("*TCombobox*Listbox.selectBackground", theme.ACCENT_BG)
        self.root.option_add("*TCombobox*Listbox.selectForeground", theme.WHITE)

    def _build(self):
        top = tk.Frame(self.root, bg=theme.BG_WINDOW, padx=scale_pixels(18, self._dpi_scale), pady=scale_pixels(14, self._dpi_scale))
        top.pack(fill="x")
        tk.Label(top, text=APP_NAME, fg=theme.TEXT_TITLE, bg=theme.BG_WINDOW,
                 font=theme.FONT_APP_TITLE).pack(side="left")
        self.status = tk.StringVar(value="No saved library yet. Choose File → Data paths…, then Load / refresh.")
        tk.Label(top, textvariable=self.status, fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW,
                 font=theme.FONT_BODY).pack(side="right", padx=scale_pixels(8, self._dpi_scale))
        # The course builder component (course_builder.py): created here because it needs the
        # status variable above; the Build course button below calls its open_dialog directly.
        # The geometry it opens with comes from settings (issue #25); it is initialized here,
        # before any save can run, so a session that never opens the dialog carries the stored
        # value through unchanged.
        self.course_geometry = self._valid_course_geometry(self.saved_settings.get("course_geometry"))
        self.course_builder = CourseBuilder(self.root, self.status, self._button, self._selected_rows_for_course,
                                            self._library_rows_for_course,
                                            saved_geometry=self.course_geometry,
                                            report_geometry=self._course_geometry_changed,
                                            dpi_scale=self._dpi_scale)
        # The Advanced Search component (advanced_search.py): it edits the search variable's
        # text through its field form; the Advanced… button below calls its open_dialog directly.
        self.advanced_search_geometry = self._valid_advanced_search_geometry(
            self.saved_settings.get("advanced_search_geometry"))
        self.advanced_search = AdvancedSearch(self.root, self._entry, self._button, self._combo, self.search_var,
                                              saved_geometry=self.advanced_search_geometry,
                                              report_geometry=self._advanced_search_geometry_changed,
                                              dpi_scale=self._dpi_scale)
        # The main window's X button goes through the same exit path as File → Exit (issue #87).
        self.root.protocol("WM_DELETE_WINDOW", self._close_app)
        bar = tk.Frame(self.root, bg=theme.BG_WINDOW, padx=scale_pixels(18, self._dpi_scale), pady=scale_pixels(12, self._dpi_scale))
        bar.pack(fill="x")
        tk.Label(bar, text="Search", fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW, font=theme.FONT_BODY).pack(side="left", padx=(0, scale_pixels(6, self._dpi_scale)))
        self.search_entry = self._entry(bar, "", self.search_var)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, scale_pixels(4, self._dpi_scale)))
        self._button(bar, "Advanced…", self.advanced_search.open_dialog).pack(side="left", padx=(0, scale_pixels(8, self._dpi_scale)))
        self.pack_filter = self._combo(bar, self.pack_var, ["All packs"])
        self.pack_filter.pack(side="left", padx=scale_pixels(4, self._dpi_scale))
        self.type_filter = self._combo(bar, self.type_var, ["All types"])
        self.type_filter.pack(side="left", padx=scale_pixels(4, self._dpi_scale))
        self.diff_filter = self._combo(bar, self.diff_var, ["All difficulties"])
        self.diff_filter.pack(side="left", padx=scale_pixels(4, self._dpi_scale))
        # A pick in any filter dropdown saves the settings at once (proposal
        # 0006); _save_settings accepts the event the binding passes.
        for combo in (self.pack_filter, self.type_filter, self.diff_filter):
            combo.bind("<<ComboboxSelected>>", self._save_settings)
        tk.Checkbutton(bar, text="Scored only", variable=self.scored_var, bg=theme.BG_WINDOW, fg=theme.TEXT_LABEL,
                       activebackground=theme.BG_WINDOW, activeforeground=theme.TEXT_ON_ACCENT, selectcolor=theme.BG_INPUT,
                       font=theme.FONT_BODY).pack(side="left", padx=scale_pixels(9, self._dpi_scale))
        self.load_button = self._button(bar, "Load / refresh", self.load_data, primary=True)
        self.load_button.pack(side="left", padx=scale_pixels(4, self._dpi_scale))
        self._button(bar, "Export CSV", self.export_csv).pack(side="left", padx=scale_pixels(4, self._dpi_scale))
        self._button(bar, "Build course…", self.course_builder.open_dialog).pack(side="left", padx=scale_pixels(4, self._dpi_scale))
        # The filter pipeline (proposal 0009 Step 5): constructed once the search bar
        # widgets it takes exist. It installs the variable traces itself; the app
        # subscribes the table refresh to its change notification.
        self._filter = LibraryFilter(
            self.search_var, self.pack_var, self.type_var, self.diff_var, self.scored_var,
            self.search_entry, self.pack_filter, self.type_filter, self.diff_filter, self.root)
        # The distribution panel component (distribution_panel.py): it owns the chart panel
        # beside the table. The four variables stay the app's own (the View menu binds one,
        # the settings save reads two), row pulls go through the filter, and the panel's
        # click/Clear changes come back through the filter's apply_chart_filter so they
        # batch into one refresh. Its widgets are built by build_panel, below, once their
        # parent exists.
        self.distribution_panel = DistributionPanel(
            button_factory=self._button,
            search_var=self.search_var,
            diff_var=self.diff_var,
            show_distribution_panel=self.show_distribution_panel,
            distribution_metric=self.distribution_metric,
            filter_rows=self._filter.filter_rows,
            apply_chart_filter=self._filter.apply_chart_filter,
            save_settings=self._save_settings,
            dpi_scale=self._dpi_scale)
        # The label is the component's to set: build_panel (below) puts the saved state's
        # ◀/▶ text on the button, and the component rewrites it on every visibility change.
        self.dist_button = self._button(bar, "", self.distribution_panel.toggle)
        self.dist_button.pack(side="left", padx=scale_pixels(4, self._dpi_scale))
        self.content_frame = tk.Frame(self.root, bg=theme.BG_WINDOW)
        self.content_frame.pack(fill="both", expand=True, padx=scale_pixels(18, self._dpi_scale), pady=(0, scale_pixels(8, self._dpi_scale)))
        self.distribution_panel.build_panel(
            self.content_frame, self.dist_button, lambda: self.table_frame)
        self.table_frame = tk.Frame(self.content_frame, bg=theme.BG_WINDOW)
        self.table_frame.pack(side="left", fill="both", expand=True)
        self.count_label = tk.StringVar(value="0 charts")
        # The song page component (song_page.py, proposal 0011 stage 3):
        # built once at startup and re-raised by show(). Playback (stage
        # 4) runs through one preview player, handed to the page as its
        # play/stop callbacks; the callbacks are None when pygame-ce is
        # not installed, which is how the page knows to disable Play,
        # and the folder button stays disabled off Windows, where
        # os.startfile does not exist.
        self._preview_player = SongPreviewPlayer()
        player_on = player_available()
        play_callback = (self._play_preview if player_on else None)
        stop_callback = (self._stop_preview if player_on else None)
        # The place it was last moved or resized to comes from settings
        # (Proposal 0016); it is initialized here, before any save can run, so
        # a session that never opens the page carries the stored value through.
        self.song_page_geometry = self._valid_song_page_geometry(
            self.saved_settings.get("song_page_geometry"))
        self.song_page = SongPage(
            self.root, on_play=play_callback, on_stop=stop_callback,
            on_open_folder=open_song_folder if hasattr(os, "startfile") else None,
            dpi_scale=self._dpi_scale, button_factory=self._button,
            saved_geometry=self.song_page_geometry,
            report_geometry=self._song_page_geometry_changed)
        # The table (proposal 0009 Step 6): constructed after the filter
        # and the Distribution Panel, taking the filter and the panel's
        # show_rows; it subscribes its refresh to the filter's change
        # notification, so a filter change redraws the table.
        self._table = LibraryTable(
            self.table_frame, self._filter, self._dpi_scale,
            self.column_visibility, self.group_visibility,
            {"column_order": self.saved_settings.get("column_order", []),
             "column_widths": self.saved_settings.get("column_widths", {}),
             "sort_keys": self.saved_settings.get("sort_keys", [])},
            self.count_label, self._save_settings,
            self.distribution_panel.show_rows,
            on_open_row=self._open_song_page)
        self._filter.subscribe(self._table.refresh_on_filter_change)
        self.progress = ttk.Progressbar(self.root, mode="indeterminate", style="Horizontal.TProgressbar")
        self.progress.pack(fill="x", padx=scale_pixels(18, self._dpi_scale), pady=(0, scale_pixels(4, self._dpi_scale)))
        footer = tk.Frame(self.root, bg=theme.BG_WINDOW, padx=scale_pixels(18, self._dpi_scale), pady=scale_pixels(7, self._dpi_scale))
        footer.pack(fill="x")
        tk.Label(footer, textvariable=self.count_label, fg=theme.TEXT_MUTED, bg=theme.BG_WINDOW,
                 font=theme.FONT_BODY).pack(side="left")
        tk.Label(footer, text="Click to sort · Shift-click adds sort keys · Drag headings to reorder · Drag dividers to resize",
                 fg=theme.TEXT_FOOTER, bg=theme.BG_WINDOW, font=theme.FONT_BODY).pack(side="right")
        self._build_menubar()

    def _close_app(self):
        """The app's single exit path (issue #87): File → Exit and the main
        window's X button both land here. Destroying the root would tear
        down the course dialog without running its discard prompt, so ask
        the course builder first; if it says no, nothing is destroyed and
        the app stays exactly as it was. An approved exit with the dialog
        open also captures the dialog's geometry for next time (issue #25).
        The Advanced Search dialog needs no prompt; its geometry is
        captured the same way (issue #98). The main window's own place is
        captured the same way (Proposal 0023): only when the owner moved,
        resized or maximized it since it opened."""
        if self.course_builder is not None:
            if not self.course_builder.confirm_discard_for_app_exit():
                return
            self.course_builder.save_window_geometry()
        if self.advanced_search is not None:
            self.advanced_search.save_window_geometry()
        if self.song_page is not None:
            self.song_page.save_window_geometry()
        self._save_main_window_geometry()
        if getattr(self, "_loader", None) is not None:
            # Stop a scan still parsing: without this the window is
            # gone but the process waits for the queued pool work to
            # drain (Revision 1, Claude option A). The loader is
            # None only before _init_loader has built it; getattr
            # because bare test instances skip __init__.
            self._loader.cancel_scan()
        self.root.destroy()

    def _save_main_window_geometry(self):
        """Store the main window's place if the owner moved, resized
        or maximized it (Proposal 0023, D5).

        The tracked values are compared against the opening baseline and
        the saved flag; only what changed is stored, and only then is
        _save_settings called, so closing untouched writes nothing. A
        bare instance in tests has never been placed, so the decision is
        None and nothing is saved.
        """
        decision = decide_main_window_save(
            self._main_window_last_geometry, self._main_window_opening_geometry,
            self._main_window_last_maximized, self.main_window_maximized)
        if decision is None:
            return
        if "main_window_geometry" in decision:
            self.main_window_geometry = decision["main_window_geometry"]
        if "main_window_maximized" in decision:
            self.main_window_maximized = decision["main_window_maximized"]
        self._save_settings()

    def _course_geometry_changed(self, geometry):
        """The course window closed with a new geometry (issue #25): remember it in settings."""
        self.course_geometry = geometry
        self._save_settings()

    def _advanced_search_geometry_changed(self, geometry):
        """The Advanced Search window closed with a new geometry (issue #98): remember it in settings."""
        self.advanced_search_geometry = geometry
        self._save_settings()

    def _build_menubar(self):
        menubar = tk.Menu(self.root, tearoff=False)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Load / refresh library", command=self.load_data)
        file_menu.add_command(label="Sync scores from Stats.xml", command=self.sync_scores)
        file_menu.add_command(label="Export CSV…", command=self.export_csv)
        file_menu.add_separator()
        file_menu.add_command(label="Data paths…", command=self.open_data_paths_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._close_app)
        menubar.add_cascade(label="File", menu=file_menu)
        self._file_menu = file_menu  # the sync entry is disabled while a scan runs (issue #147)

        edit_menu = tk.Menu(menubar, tearoff=False)
        edit_menu.add_command(label="Find", accelerator="Ctrl+F", command=self._filter.focus_search)
        edit_menu.add_command(label="Advanced search…", accelerator="Ctrl+Shift+F", command=self.advanced_search.open_dialog)
        edit_menu.add_command(label="Clear search", accelerator="Esc",
                              command=self._filter.clear_search)
        menubar.add_cascade(label="Edit", menu=edit_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        columns_menu = tk.Menu(view_menu, tearoff=False)
        for group, columns in COLUMN_GROUPS.items():
            group_menu = tk.Menu(columns_menu, tearoff=False)
            group_menu.add_checkbutton(
                label="Show whole group",
                variable=self.group_visibility[group],
                command=lambda name=group: self._table.group_visibility_changed(name),
            )
            group_menu.add_separator()
            for column in columns:
                group_menu.add_checkbutton(
                    label=column,
                    variable=self.column_visibility[column],
                    command=lambda col=column: self._table.column_visibility_changed(col),
                )
            columns_menu.add_cascade(label=group, menu=group_menu)
        view_menu.add_cascade(label="Columns", menu=columns_menu)
        view_menu.add_command(label="Reset column layout", command=self._table.reset_column_layout)
        view_menu.add_separator()
        view_menu.add_checkbutton(
            label="Show distribution panel",
            variable=self.show_distribution_panel,
            command=self.distribution_panel.sync_toggle,
        )
        menubar.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label=f"About {APP_NAME}…", command=self.open_about)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.root.configure(menu=menubar)
        self.root.bind("<Control-f>", lambda _event: self._filter.focus_search())
        self.root.bind("<Control-F>", lambda _event: self._filter.focus_search())
        self.root.bind("<Control-Shift-f>", lambda _event: self.advanced_search.open_dialog())
        self.root.bind("<Control-Shift-F>", lambda _event: self.advanced_search.open_dialog())
        self.root.bind("<Escape>", self._on_main_escape)

    @staticmethod
    def _settings_file_path():
        # Thin wrapper over the module-level helper (proposal 0008): the
        # seventeen live-test patch sites redirect the settings file here.
        # The bare name is the imported helper, not this method.
        return _settings_file_path()
    def _song_page_geometry_changed(self, geometry):
        """The song page closed in a new place (Proposal 0016): remember it in settings."""
        self.song_page_geometry = geometry
        self._save_settings()

    @property
    def library_cache_path(self):
        return self.settings_path.with_name("library_cache.json")

    @property
    def library_cache_manifest_path(self):
        return self.settings_path.with_name("library_cache_manifest.json")

    @staticmethod
    def _valid_course_geometry(value):
        """The canonical geometry string to restore the course window with, or None (issue #25)."""
        return _valid_window_geometry(value, theme.COURSE_BUILDER_MIN_SIZE)

    @staticmethod
    def _valid_advanced_search_geometry(value):
        """The canonical geometry string to restore the Advanced Search window with, or None (issue #98)."""
        return _valid_window_geometry(value, theme.ADVANCED_SEARCH_MIN_SIZE)

    @staticmethod
    def _valid_song_page_geometry(value):
        """The canonical geometry to restore the song page with, or None (Proposal 0016).

        Two forms are valid: the full "WxH+X+Y" of a resized page, at least the page's
        minimum size, and the position-only "+X+Y" of a page that was only moved.
        Anything else is dropped, as for the other windows.
        """
        return (_valid_window_geometry(value, theme.SONG_PAGE_MIN_SIZE)
                or _valid_window_position(value))

    @staticmethod
    def _valid_main_window_geometry(value):
        """The canonical geometry string to restore the main window with, or None (Proposal 0023).

        The full "WxH+X+Y" form only, at least the main window's minimum
        size — a position alone is not a place the main window can open
        at, since it has a fixed default size. Anything else is dropped,
        as for the other windows.
        """
        return _valid_window_geometry(value, theme.WINDOW_MIN_SIZE)

    def _report_discarded_settings(self):
        """Append the discarded-settings note to the status line, once.

        The wording mirrors the snapshot reader's ("Saved library snapshot
        could not be read (…)", load_cached_data): the file, the reason it
        could not be used, and what the app did instead — run on defaults.
        Appending, rather than replacing, keeps whatever the snapshot load
        reported; the status line is rewritten by the next load or refresh,
        so the notice is startup-scoped like the snapshot messages.
        """
        reason = self._settings_store.last_read_error
        if reason is None:
            return
        message = f"Settings file could not be read ({reason}); using defaults."
        current = self.status.get()
        if message in current:
            return
        self.status.set(f"{current} {message}" if current else message)

    def _save_settings(self, _event=None):
        if self._table is None:
            return
        # The column order, widths, and sort keys come from the table's
        # layout_state(): the table owns that state (sort_by and
        # reset_column_layout rebind it), and the widths are read back
        # from the tree in canonical 100% units (issue #51).
        layout = self._table.layout_state()
        settings = {
            "cache_dir": self.cache_var.get(),
            "stats_file": self.stats_var.get(),
            "column_order": layout["column_order"],
            "column_visibility": {column: variable.get() for column, variable in self.column_visibility.items()},
            "column_widths": layout["column_widths"],
            "sort_keys": layout["sort_keys"],
            "show_distribution": self.show_distribution_panel.get(),
            "distribution_metric": self.distribution_metric.get(),
            "filter_pack": self.pack_var.get(),
            "filter_type": self.type_var.get(),
            "filter_difficulty": self.diff_var.get(),
        }
        # The course window's geometry joins the file only once the user has
        # actually placed the window (issue #25); a settings file that predates
        # the feature stays without the key until then.
        if self.course_geometry is not None:
            settings["course_geometry"] = self.course_geometry
        # The Advanced Search window's geometry, on the same terms (issue #98).
        if self.advanced_search_geometry is not None:
            settings["advanced_search_geometry"] = self.advanced_search_geometry
        # The song page's place, on the same terms (Proposal 0016): a full geometry
        # once resized, a position alone once only moved.
        if self.song_page_geometry is not None:
            settings["song_page_geometry"] = self.song_page_geometry
        # The main window's place (Proposal 0023): the full geometry once
        # the owner has placed the window, and the maximized flag once
        # the window has been placed in any way — moved, resized, or
        # maximized. The flag is also re-emitted when it was already in
        # the file at startup, so un-maximizing after a past maximize
        # still clears it; a bare instance in tests has no saved
        # settings, which reads as "never set".
        if self.main_window_geometry is not None:
            settings["main_window_geometry"] = self.main_window_geometry
        if (self.main_window_maximized or self.main_window_geometry is not None
                or getattr(self, "saved_settings", {}).get("main_window_maximized", False)):
            settings["main_window_maximized"] = self.main_window_maximized
        # The store owns the dedup baseline and the atomic write (proposal
        # 0008); a failed write raises OSError, which the store leaves for
        # the app to report — and the baseline stays stale so the next
        # gesture retries.
        try:
            self._settings_store.save(settings)
        except OSError as exc:
            self.status.set(f"Could not save settings: {exc}")

    def _selected_rows_for_course(self):
        """The chart rows currently selected in the main table (for the course builder)."""
        return self._table.selected_rows()

    def _open_song_page(self, row):
        """Open the song page for the focused row's song (proposal 0011).

        The song is every row sharing the row's "Course path", read from
        the filter's rows rather than the visible rows, so a filtered
        table still shows every chart; the opened chart goes first. The
        roots are derived from the selected cache dir every time the page
        opens, so the record is built from the rows as they are now.
        """
        course_path = row.get("Course path")
        if not course_path:
            return
        rows = charts_for_song(self._filter.library_rows(), course_path)
        if not rows:
            return
        # The opened chart first; the rest keep the page's type-then-difficulty order.
        rows = [row] + [other for other in rows if other is not row]
        cache_dir = self.cache_var.get().strip()
        cache_path = (Path(cache_dir) if cache_dir
                      else first_existing_directory(cache_dir_candidates()))
        media = build_song_media(course_path, song_roots(cache_path), rows)
        song = {
            "title": row.get("Title") or "",
            "artist": row.get("Artist") or "",
            "pack": row.get("Pack") or "",
            "charts": rows,
        }
        self._song_media = media
        self.song_page.show(song, media)

    def _play_preview(self, path, start, length):
        """Start the song page's preview; the effective length, or None.

        The player normalizes the window against the song's music
        length, which the page does not pass (its contract is the
        path and the raw window), so it comes from the record kept
        when the page opened. A bare instance built for a test may
        not have a player; that reads as "could not start".
        """
        player = getattr(self, "_preview_player", None)
        if player is None:
            return None
        media = getattr(self, "_song_media", None)
        total = media.music_length if media is not None else None
        return player.play(path, start, length, total)

    def _stop_preview(self):
        """Stop the song page's preview, if one is playing."""
        player = getattr(self, "_preview_player", None)
        if player is not None:
            player.stop()

    def _library_rows_for_course(self):
        """Every chart row in the loaded library (for the course builder's ambiguity check)."""
        return self._table.library_rows()

    def _dialog_is_open(self):
        for window in (self.advanced_search.window if self.advanced_search is not None else None,
                       self.course_builder.window if self.course_builder is not None else None,
                       self.song_page.window if self.song_page is not None else None,
                       self.about_window):
            if window is not None and window.winfo_exists():
                return True
        return False

    def _on_main_escape(self, _event=None):
        # Escape in a dialog is handled by the dialog. This covers focus left in the main window while a
        # dialog is open, where Escape should not silently wipe the search bar.
        if not self._dialog_is_open():
            self._filter.clear_search()

    @staticmethod
    def _entry(parent, placeholder, variable):
        entry = tk.Entry(parent, textvariable=variable, bg=theme.BG_INPUT, fg=theme.TEXT_PRIMARY, insertbackground=theme.CURSOR,
                         relief="flat", font=theme.FONT_BODY, highlightthickness=1,
                         highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT)
        if placeholder:
            entry.insert(0, placeholder)
            entry.bind("<FocusIn>", lambda e: e.widget.delete(0, "end") if e.widget.get() == placeholder else None)
        return entry

    @staticmethod
    def _combo(parent, variable, values):
        return ttk.Combobox(parent, textvariable=variable, values=values, state="readonly", width=18,
                            font=theme.FONT_BODY)

    def _button(self, parent, text, command, primary=False):
        # An instance method so the padding can scale with this display
        # (issue #51); callers pass it around bound.
        return tk.Button(parent, text=text, command=command, bg=theme.ACCENT_BG if primary else theme.BG_BUTTON,
                         fg=theme.TEXT_ON_ACCENT, activebackground=theme.ACCENT_BG_HOVER if primary else theme.BG_BUTTON_HOVER,
                         activeforeground=theme.TEXT_ON_ACCENT, relief="flat",
                         padx=scale_pixels(theme.BUTTON_PADX, self._dpi_scale), pady=scale_pixels(theme.BUTTON_PADY, self._dpi_scale),
                         font=theme.FONT_BODY_BOLD, cursor="hand2")

    def open_data_paths_dialog(self, note=None):
        """Open the Data paths dialog (proposal 0009 Step 3).

        A thin delegation to the DataPathsDialog component, which owns the
        dialog. Kept so the File menu and the loader paths that open it do
        not change.
        """
        self._data_paths_dialog.open(note)

    def load_data(self):
        """Start a library load (thin delegation to the loader)."""
        self._loader.load_data()

    def _paths_match_loaded(self):
        """Whether the selected paths match the loaded library (the dialog's check)."""
        return self._loader.paths_match_loaded()

    def sync_scores(self):
        """Start a scores-only sync (thin delegation to the loader)."""
        self._loader.sync_scores()

    def _on_library_changed(self, rows, preserve_selection, changed_keys=None):
        """The app-side part of a finished load or sync (Q2).

        preserve_selection distinguishes a sync from a load: a sync
        re-scores the same rows, so only the table refreshes (keeping
        the selection); a load brings fresh rows, so the filter takes
        them and the dropdowns reset (batched, so the table refreshes
        exactly once) and the Course Builder is told the library
        changed. changed_keys is the set merge_scores reports on a
        sync (Proposal 0022); a load passes nothing, so the table
        rebuilds every tuple.
        """
        # A reload or a sync replaces the rows the page shows; close it so
        # a stale page never shows old scores (proposal 0011). A bare
        # instance built for a loader test may not have a page; that is
        # "no page to close", not an error.
        page = getattr(self, "song_page", None)
        if page is not None:
            page.close()
        self._song_media = None
        if preserve_selection:
            # Invariant: the filter and the loader share one rows list.
            # A sync re-scores that list in place (merge_scores never
            # replaces it), so there is nothing to re-set — only the
            # refresh, keeping the selection. If the sync ever built a
            # fresh list, the filter would keep showing the old scores.
            self._table.refresh_table(preserve_selection=True,
                                      changed_keys=changed_keys)
            return
        with self._filter.batch():
            self._filter.set_rows(rows)
            self._filter.set_choices(rows)
        if self.course_builder is not None:
            # A fresh library may no longer match a course queue built from the old
            # one; the builder asks the user what to do with it (issue #82).
            self.course_builder.on_library_reloaded()

    def _on_nothing_loaded(self):
        """Repaint the empty table when no snapshot was restored."""
        self._table.refresh_table()

    def _set_sync_menu_state(self, state):
        """Enable or disable the File -> Sync scores entry (issue #147).

        Before _build_menubar has run there is no menu to update, which is
        not an error.
        """
        file_menu = self._file_menu
        if file_menu is None:
            return
        file_menu.entryconfigure("Sync scores from Stats.xml", state=state)

    def export_csv(self):
        if not self._loader.rows:
            messagebox.showinfo("No charts", "Load a library before exporting.")
            return
        path = filedialog.asksaveasfilename(title="Export chart library", defaultextension=".csv",
                                            filetypes=[("CSV files", "*.csv")],
                                            initialfile="itgmania-library.csv")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=HEADERS, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(self._loader.rows)
            self.status.set(f"Exported {len(self._loader.rows):,} charts to {path}")
        except OSError as exc:
            self.status.set(f"Could not export CSV: {exc}")
            messagebox.showerror("Export failed", f"Could not write to {path}:\n\n{exc}")

    def open_about(self):
        if self.about_window is not None and self.about_window.winfo_exists():
            self.about_window.lift()
            self.about_window.focus_force()  # raised from behind the main window: give it the keys too
            return

        window = tk.Toplevel(self.root)
        self.about_window = window
        # Withdrawn while it is built, so it appears once, centered, instead
        # of at the corner first and then jumping (Proposal 0016).
        window.withdraw()
        window.title(f"About {APP_NAME}")
        window.resizable(False, False)
        window.configure(bg=theme.BG_WINDOW)
        window.transient(self.root)

        tk.Label(window, text=APP_NAME, fg=theme.TEXT_TITLE, bg=theme.BG_WINDOW,
                 font=theme.FONT_DIALOG_TITLE).pack(anchor="w", padx=scale_pixels(24, self._dpi_scale), pady=(scale_pixels(18, self._dpi_scale), scale_pixels(2, self._dpi_scale)))
        tk.Label(window, text=f"Version {__version__}", fg=theme.TEXT_PRIMARY, bg=theme.BG_WINDOW,
                 font=theme.FONT_BODY_BOLD).pack(anchor="w", padx=scale_pixels(24, self._dpi_scale))
        tk.Label(window, text="Released under the MIT License (see the LICENSE file).", fg=theme.TEXT_MUTED,
                 bg=theme.BG_WINDOW, font=theme.FONT_BODY).pack(anchor="w", padx=scale_pixels(24, self._dpi_scale), pady=(scale_pixels(10, self._dpi_scale), scale_pixels(14, self._dpi_scale)))

        btn_row = tk.Frame(window, bg=theme.BG_WINDOW, padx=scale_pixels(24, self._dpi_scale))
        btn_row.pack(fill="x", pady=(0, scale_pixels(16, self._dpi_scale)))
        self._button(btn_row, "Close", window.destroy, primary=True).pack(side="right")

        def _close(_event=None):
            window.destroy()
            return "break"

        window.bind("<Escape>", _close)
        window.bind("<Return>", _close)
        # The window is sized by its content: make the requested size real,
        # then center it over the main window.
        window.update_idletasks()
        window.geometry(WindowPlacement(self.root, self._dpi_scale).geometry_for_content(
            window.winfo_reqwidth(), window.winfo_reqheight()))
        window.deiconify()
        # A new window does not always take keyboard focus (seen on Windows); without it Escape and Return
        # would go to the main window instead of closing this one. After the map: the window manager
        # ignores the request on a withdrawn window.
        window.focus_force()

def main():
    if tk is None:
        sys.exit(f"Tkinter is required to run the {APP_NAME} GUI.")
    # Declare DPI awareness before the first window exists (issue #51):
    # without it Windows bitmap-stretches the app at 125%/150%.
    declare_dpi_awareness()
    # Load the bundled fonts before the first window exists (Proposal 0017):
    # the theme switches to the sets that loaded, and a family that did
    # not load keeps today's Segoe sizes.
    loaded = load_fonts()
    if loaded.failed:
        # Erratum (Proposal 0017): the smoke check cannot read a
        # dataclass field, so say on stderr why the app is in Segoe.
        print("Bundled fonts failed to load:",
              ", ".join(loaded.failed), file=sys.stderr)
    theme.apply_fonts(barlow=loaded.barlow, wendy=loaded.wendy)
    root = tk.Tk()
    LibraryApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
