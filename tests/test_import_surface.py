"""The import-surface pin (Proposal 0010, Step 1).

Every name the app consumes from the nine data modules, grouped by the
module it lives in. The pin was built during the split so no move could
silently drop a name: if a name stops resolving from its home module,
this fails before the suite ever reaches the behaviour tests. With
`library_data.py` deleted at Step 9, every method imports from its new
module.

The list is built from the names consumers actually import, not from
`__all__`: five of them (`_normalized_source_path`, `_settings_file_path`,
`_valid_window_geometry`, `_valid_column_width`, `_quote_for_search`) are
not in `__all__`, and a pin built from `__all__` alone would have let a
move drop them silently. The stdlib module attributes the namespace-patch
tests read (`data.sys`, `data.ctypes`) are deliberately not in this list —
those tests themselves fail loudly if they go missing, and they are not
names this file defines.
"""

import unittest

from itgmania_library import library_constants
from itgmania_library import library_course
from itgmania_library import library_format
from itgmania_library import library_geometry
from itgmania_library import library_dialog_query
from itgmania_library import library_distribution
from itgmania_library import library_search
from itgmania_library import library_sources
from itgmania_library import library_stores


class ImportSurfaceTests(unittest.TestCase):
    def _assert_resolve(self, names, module):
        for name in names:
            with self.subTest(name=name):
                self.assertIsNotNone(getattr(module, name, None))

    def test_constants_names_resolve(self):
        # Re-pointed to library_constants.py at Step 2.
        self._assert_resolve((
            "APP_NAME",
            "COLUMN_GROUPS",
            "DEFAULT_VISIBLE_COLUMNS",
            "DIFFICULTY_ORDER",
            "GRADE_NAMES",
            "GRADE_OPTIONS",
            "HEADERS",
            "NUMERIC_COLUMNS",
            "OLD_APP_NAME",
            "RADAR_FIELDS",
            "TAP_FIELDS",
            "TECH_FIELDS",
        ), module=library_constants)

    def test_format_names_resolve(self):
        # Re-pointed to library_format.py at Step 2.
        self._assert_resolve((
            "bpm_sort_key",
            "difficulty_sort_key",
            "format_bpm_display",
            "format_duration",
            "format_refresh_time",
            "grade_sort_key",
            "number",
            "parse_bpms",
            "split_path",
            "tag_map",
        ), module=library_format)

    def test_sources_names_resolve(self):
        # Re-pointed to library_sources.py at Step 3.
        self._assert_resolve((
            "_normalized_source_path",
            "any_scores_match",
            "cache_dir_candidates",
            "edit_fallback_index",
            "first_existing_directory",
            "invalid_paths_note",
            "looks_like_song_tree",
            "merge_scores",
            "parse_cache_file",
            "stats_index",
        ), module=library_sources)

    def test_geometry_names_resolve(self):
        # Re-pointed to library_geometry.py at Step 4.
        self._assert_resolve((
            "declare_dpi_awareness",
            "dpi_scale_factor",
            "format_geometry",
            "opening_geometry",
            "parse_window_geometry",
            "parse_window_size",
            "scale_geometry",
            "scale_pixels",
        ), module=library_geometry)

    def test_course_names_resolve(self):
        # Re-pointed to library_course.py at Step 4.
        self._assert_resolve((
            "course_append_bytes",
            "course_song_line",
            "course_song_lines",
            "course_trailing_risk",
            "find_ambiguous_course_entries",
            "format_new_course",
            "parse_course_text",
            "validate_course_fields",
        ), module=library_course)

    def test_search_names_resolve(self):
        # Re-pointed to library_search.py at Step 5.
        self._assert_resolve((
            "CHART_FILTER_FIELDS",
            "SEARCH_FIELD_ALIASES",
            "_quote_for_search",
            "filter_texts_match",
            "filter_token_text",
            "find_unreadable_directives",
            "get_active_chart_filters",
            "match_chart_query",
            "parse_duration_seconds",
            "parse_numeric_bound",
            "parse_search_query",
            "replace_search_directive",
            "split_search_query",
        ), module=library_search)

    def test_dialog_query_names_resolve(self):
        # Re-pointed to library_dialog_query.py at Step 6.
        self._assert_resolve((
            "build_dialog_query",
            "split_dialog_query",
        ), module=library_dialog_query)

    def test_stores_names_resolve(self):
        # Re-pointed to library_stores.py at Step 7.
        self._assert_resolve((
            "LIBRARY_CACHE_SCHEMA_VERSION",
            "SettingsStore",
            "SnapshotStore",
            "_migrate_config_dir",
            "_settings_file_path",
            "_valid_column_width",
            "_valid_window_geometry",
            "write_file_atomically",
        ), module=library_stores)

    def test_distribution_names_resolve(self):
        # Re-pointed to library_distribution.py at Step 8.
        self._assert_resolve((
            "ChartBar",
            "aggregate_bpm_distribution",
            "aggregate_difficulty_distribution",
            "aggregate_meter_distribution",
            "chart_bar_at",
            "chart_bars",
            "chart_clear_decision",
            "chart_click_decision",
            "distribution_summary_stats",
        ), module=library_distribution)
