import tempfile
import unittest
from pathlib import Path

import library_data as data


class BpmTests(unittest.TestCase):
    def test_display_text_differs_from_real_bounds(self):
        # Q1-B: the cell shows #DISPLAYBPM while the filter and the sort
        # follow the real #BPMS bounds. A song with #DISPLAYBPM:150 and
        # #BPMS:0=100,32=300 shows cell "150" with bounds 100/300;
        # bpm:>250 matches it and the sort key follows the 300.
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "song.cache"
            cache_file.write_text(
                "#TITLE:Test;\n"
                "#SONGFILENAME:Songs/P/S/a.ogg;\n"
                "#BPMS:0.000=100.000,32.000=300.000;\n"
                "#DISPLAYBPM:150;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Easy;\n",
                encoding="utf-8",
            )
            row = data.parse_cache_file(cache_file, {})[0][0]
            self.assertEqual(row["bpm_min"], 100.0)
            self.assertEqual(row["bpm_max"], 300.0)
            self.assertEqual(row["BPM"], "150")
            self.assertTrue(data.match_chart_query(row, data.parse_search_query("bpm:>250")))
            self.assertEqual(data.bpm_sort_key(row), (300.0, 100.0))

    def test_missing_bpm_downstream_consumers(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "song.cache"
            # An all-nonpositive/warp-only song produces empty bounds
            cache_file.write_text(
                "#TITLE:Warp Only;\n"
                "#SONGFILENAME:Songs/P/S/a.ogg;\n"
                "#BPMS:0.000=-150.000,64.000=0.000;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Challenge;\n",
                encoding="utf-8",
            )
            row = data.parse_cache_file(cache_file, {})[0][0]
            self.assertEqual(row["bpm_min"], "")
            self.assertEqual(row["bpm_max"], "")
            self.assertEqual(row["BPM"], "")

            # 1. bpm_sort_key places it in the missing-BPM group (ranks after numeric BPMs)
            normal_row = {"bpm_min": 100.0, "bpm_max": 200.0}
            self.assertEqual(data.bpm_sort_key(row), (float("inf"), float("inf")))
            self.assertEqual(sorted([row, normal_row], key=data.bpm_sort_key), [normal_row, row])

            # 2. match_chart_query: does not match bpm: queries
            self.assertFalse(data.match_chart_query(row, data.parse_search_query("bpm:150")))
            self.assertFalse(data.match_chart_query(row, data.parse_search_query("bpm:>0")))
            self.assertFalse(data.match_chart_query(row, data.parse_search_query("bpm:0")))
            self.assertFalse(data.match_chart_query(row, data.parse_search_query("bpm:100-200")))

            # 3. Distribution aggregation counts it in the missing/("?") category, not numeric bins
            bins = data.aggregate_bpm_distribution([row])
            q_bin = next(b for b in bins if b[0] == "?")
            self.assertEqual(q_bin[1], 1)
            # Numeric bins have count 0
            self.assertTrue(all(count == 0 for label, count, _, _ in bins if label != "?"))


class GradeSortTests(unittest.TestCase):
    def test_grade_filter_options_are_defined_labels(self):
        self.assertEqual(data.GRADE_OPTIONS, tuple(data.GRADE_NAMES.values()))




