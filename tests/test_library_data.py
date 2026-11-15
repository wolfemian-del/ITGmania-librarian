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




class AdvancedSearchDialogTests(unittest.TestCase):
    """The Advanced Search dialog must never drop or change a filter it cannot show."""

    ROWS = [
        {"Title": "Alpha Song", "Artist": "Ann", "Pack": "Pack One", "Difficulty": "Hard",
         "Meter": 10, "bpm_min": 150.0, "bpm_max": 150.0, "Time": 90.0, "Peak NPS": 12.0,
         "Grade": "S", "Best %": 95.0, "Plays": 4, "Jacks": 2},
        {"Title": "Beta Song", "Artist": "Bob", "Pack": "Pack Two", "Difficulty": "Challenge",
         "Meter": 12, "bpm_min": 120.0, "bpm_max": 180.0, "Time": 150.0, "Peak NPS": 15.5,
         "Grade": "B", "Best %": 70.0, "Plays": 1, "Jacks": 0},
        {"Title": "Gamma Song", "Artist": "Cy", "Pack": "Pack One", "Difficulty": "Easy",
         "Meter": 5, "bpm_min": 90.0, "bpm_max": 90.0, "Time": 75.0, "Peak NPS": 4.0,
         "Grade": "", "Best %": "", "Plays": 0, "Jacks": 0},
    ]

    def matches(self, query):
        return [row["Title"] for row in self.ROWS if data.match_chart_query(row, query)]

    def round_trip(self, query):
        return data.build_dialog_query(data.split_dialog_query(query))

    def test_filters_without_a_box_are_kept(self):
        parts = data.split_dialog_query("jacks:>0 plays:>=3 type:single diff:hard pack:One")
        self.assertEqual(parts["pack"], "One")
        self.assertEqual(parts["other"], "jacks:>0 plays:>=3 type:single difficulty:hard")

    def test_radar_filters_without_a_box_are_kept(self):
        parts = data.split_dialog_query("jumps:>10 mines:0 holds:>=5 taps:100-200 pack:One")
        self.assertEqual(parts["pack"], "One")
        self.assertEqual(parts["other"], "jumps:>10 mines:0 holds:>=5 taps:100-200")
        self.assertEqual(data.build_dialog_query(parts), "pack:One jumps:>10 mines:0 holds:>=5 taps:100-200")

    def test_peak_nps_loads_into_its_boxes(self):
        parts = data.split_dialog_query("nps:>=10 nps:<=20")
        self.assertEqual(parts["peak_nps"], ("10", "20"))
        self.assertEqual(parts["other"], "")

    def test_filters_the_boxes_would_change_are_kept(self):
        for query in ("grade:<B", "grade:S", "grade:>S", "meter:>10", "bpm:<150",
                      "time:<=90.5", "grade:>=Zzz", "meter:abc", "bpm:"):
            with self.subTest(query=query):
                parts = data.split_dialog_query(query)
                self.assertEqual(parts["other"], query)
                self.assertEqual(parts["grade"], "")
                self.assertEqual(parts["meter"] + parts["bpm"] + parts["time"], ("",) * 6)

    def test_second_filter_for_a_taken_box_is_kept(self):
        parts = data.split_dialog_query("meter:>=8 meter:>=10 title:a title:b")
        self.assertEqual(parts["meter"], ("8", ""))
        self.assertEqual(parts["title"], "a")
        self.assertEqual(parts["other"], "meter:>=10 title:b")

    def test_values_with_spaces_stay_quoted(self):
        parts = data.split_dialog_query('title:"Alpha Song" plays:">= 3" artist:"a b"')
        self.assertEqual(parts["title"], "Alpha Song")
        self.assertEqual(parts["artist"], "a b")
        self.assertEqual(data.build_dialog_query(parts),
                         'title:"Alpha Song" artist:"a b" plays:">= 3"')

    def test_dialog_absorbs_and_formats_apostrophes(self):
        parts = data.split_dialog_query('title:"Don\'t Stop" artist:"Guns N\' Roses" pack:"80\'s Hits"')
        self.assertEqual(parts["title"], "Don't Stop")
        self.assertEqual(parts["artist"], "Guns N' Roses")
        self.assertEqual(parts["pack"], "80's Hits")
        self.assertEqual(parts["other"], "")
        self.assertEqual(
            data.build_dialog_query(parts),
            'title:"Don\'t Stop" artist:"Guns N\' Roses" pack:"80\'s Hits"'
        )

    def test_dialog_round_trip_keeps_apostrophes_at_value_edges(self):
        # A Title box value that begins and ends with apostrophes must come
        # back exactly. (Regression: the parser stripped the pair, so the
        # dialog read 'Tis' back as Tis.)
        built = data.build_dialog_query({"title": "'Tis'"})
        self.assertEqual(data.split_dialog_query(built)["title"], "'Tis'")
        self.assertEqual(data.parse_search_query(built)["directives"],
                         [("title", "'Tis'")])

        parts = data.split_dialog_query(
            data.build_dialog_query({"title": "'Guns N' Roses'"}))
        self.assertEqual(parts["title"], "'Guns N' Roses'")
        self.assertEqual(parts["other"], "")

    def test_grade_label_is_matched_without_regard_to_case(self):
        self.assertEqual(data.split_dialog_query("grade:>=s")["grade"], "S")
        self.assertEqual(data.split_dialog_query("grade:>=S+")["grade"], "S+")

    def test_building_from_boxes_matches_the_old_dialog_output(self):
        parts = {"free_text": "song", "title": "Alpha Song", "pack": "One",
                 "meter": ("8", "12"), "bpm": ("140", ""), "time": ("1:00", "1:00"),
                 "peak_nps": ("", "20"), "grade": "A", "other": "plays:>=1"}
        self.assertEqual(
            data.build_dialog_query(parts),
            'song title:"Alpha Song" pack:One meter:8-12 bpm:>=140 time:1:00 nps:<=20 '
            'grade:>=A plays:>=1')
        self.assertEqual(data.build_dialog_query({"grade": "Any"}), "")

    def test_applying_the_dialog_never_changes_which_charts_match(self):
        queries = (
            "jacks:>0 plays:>=3", "grade:<B", "grade:S", "grade:>=B", "meter:>10", "meter:10-12",
            "meter:>=5 meter:<=10", "bpm:>=140 bpm:<=160", "bpm:150", "time:<=1:30", "time:<=90.5",
            "nps:>=10", "nps:>10", "title:song artist:ann pack:one", 'pack:"pack one" percent:>80',
            "song meter:>=8 score:>0 diff:hard", "percent:<50", "bpm:", "grade:", "alpha beta",
        )
        for query in queries:
            with self.subTest(query=query):
                self.assertEqual(self.matches(self.round_trip(query)), self.matches(query))

    def test_a_second_trip_through_the_dialog_changes_nothing(self):
        for query in ("jacks:>0 meter:>=8 meter:<=12 grade:>=B grade:<S title:alpha",
                      'artist:"a b" plays:">= 3" time:1:00-2:00'):
            with self.subTest(query=query):
                once = self.round_trip(query)
                self.assertEqual(self.round_trip(once), once)


