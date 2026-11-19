import tempfile
import unittest
from pathlib import Path

from itgmania_library import library_distribution as distribution
from itgmania_library import library_search as data
from itgmania_library import library_sources as sources
from itgmania_library.library_format import bpm_sort_key


class SearchQueryTests(unittest.TestCase):
    def test_parse_duration_seconds(self):
        self.assertEqual(data.parse_duration_seconds("120"), 120.0)
        self.assertEqual(data.parse_duration_seconds("2:15"), 135.0)
        self.assertEqual(data.parse_duration_seconds("01:30.5"), 90.5)
        self.assertEqual(data.parse_duration_seconds("1:00:10"), 3610.0)
        self.assertIsNone(data.parse_duration_seconds(""))
        self.assertIsNone(data.parse_duration_seconds("not-a-time"))

    def test_parse_numeric_bound_operators_and_ranges(self):
        self.assertEqual(data.parse_numeric_bound("11"), ("==", 11.0))
        self.assertEqual(data.parse_numeric_bound("10-12"), ("range", 10.0, 12.0))
        self.assertEqual(data.parse_numeric_bound("10..12"), ("range", 10.0, 12.0))
        self.assertEqual(data.parse_numeric_bound(">=10"), (">=", 10.0))
        self.assertEqual(data.parse_numeric_bound("<=12"), ("<=", 12.0))
        self.assertEqual(data.parse_numeric_bound(">200"), (">", 200.0))
        self.assertEqual(data.parse_numeric_bound("<150"), ("<", 150.0))
        self.assertEqual(data.parse_numeric_bound("=9", is_duration=False), ("==", 9.0))
        # Durations
        self.assertEqual(data.parse_numeric_bound("1:30-2:30", is_duration=True), ("range", 90.0, 150.0))
        self.assertEqual(data.parse_numeric_bound(">2:00", is_duration=True), (">", 120.0))

    def test_parse_numeric_bound_rejects_underscores(self):
        # Issue #195: float() accepts underscores, so "1_000" used to
        # parse as 1000. There is no underscore convention in the
        # search language, so an underscore makes the bound unreadable
        # — the matcher then matches nothing for it, and it is reported
        # as an unreadable directive like "meter:abc".
        self.assertIsNone(data.parse_numeric_bound("1_000"))
        self.assertIsNone(data.parse_numeric_bound("1_0_0_0"))
        self.assertIsNone(data.parse_numeric_bound(">=1_000"))
        self.assertIsNone(data.parse_numeric_bound("1_000-2_000"))
        self.assertIsNone(data.parse_numeric_bound("1_000", is_duration=True))
        self.assertIsNone(data.parse_numeric_bound("1:0_0", is_duration=True))
        row = {"Meter": 1000, "Time": 1000}
        self.assertFalse(data.match_chart_query(row, "meter:1_000"))
        self.assertTrue(data.match_chart_query(row, "meter:1000"))
        self.assertFalse(data.match_chart_query(row, "time:1_000"))
        self.assertEqual(data.find_unreadable_directives("meter:1_000"), ["meter:1_000"])

    def test_meter_nan_matches_nan_rows(self):
        # Issue #171: meter:nan selects the NaN-meter rows (the "nan"
        # bar's filter), and only them. NaN is not equal to itself, so
        # the == branch special-cases a NaN target.
        nan_row = {"Meter": float("nan")}
        self.assertTrue(data.match_chart_query(
            nan_row, data.parse_search_query("meter:nan")))
        self.assertFalse(data.match_chart_query(
            {"Meter": 10}, data.parse_search_query("meter:nan")))
        self.assertFalse(data.match_chart_query(
            nan_row, data.parse_search_query("meter:10")))

    def test_a_huge_int_in_a_row_does_not_match(self):
        # Issue #215: a huge int from a hand-edited snapshot's JSON
        # number (10**10000) must not crash the matcher; it simply
        # matches nothing, like any other unparseable value.
        self.assertFalse(data.match_chart_query(
            {"Meter": 10**10000}, data.parse_search_query("meter:10")))
        self.assertFalse(data.match_chart_query(
            {"bpm_min": 100.0, "bpm_max": 10**10000},
            data.parse_search_query("bpm:>250")))

    def test_parse_search_query_directives(self):
        q = "Smiley meter:11 bpm:200-300 time:>2:00 diff:Challenge"
        res = data.parse_search_query(q)
        self.assertEqual(res["free_terms"], ["smiley"])
        self.assertEqual(res["free_text"], "smiley")
        self.assertIn(("meter", "11"), res["directives"])
        self.assertIn(("bpm", "200-300"), res["directives"])
        self.assertIn(("time", ">2:00"), res["directives"])
        self.assertIn(("difficulty", "Challenge"), res["directives"])

    def test_parse_search_query_preserves_quoted_free_text_for_round_trip(self):
        parsed = data.parse_search_query('"In The Groove" meter:11')
        self.assertEqual(parsed["free_terms"], ["in the groove"])
        restored = data.parse_search_query(f'{parsed["free_text"]} meter:11')
        self.assertEqual(restored["free_terms"], parsed["free_terms"])
        self.assertIn(("meter", "11"), restored["directives"])

    def test_parse_search_query_with_apostrophes(self):
        # Single contraction, word-final, and embedded apostrophes
        res1 = data.parse_search_query("don't")
        self.assertEqual(res1["free_terms"], ["don't"])
        self.assertEqual(res1["free_text"], "don't")

        res2 = data.parse_search_query("don't stop believin'")
        self.assertEqual(res2["free_terms"], ["don't", "stop", "believin'"])
        self.assertEqual(res2["free_text"], "don't stop believin'")

        res3 = data.parse_search_query("rock 'n' roll")
        self.assertEqual(res3["free_terms"], ["rock", "'n'", "roll"])

        # Quoted directive with apostrophe free text
        res4 = data.parse_search_query('pack:"In The Groove" don\'t')
        self.assertEqual(res4["directives"], [("pack", "In The Groove")])
        self.assertEqual(res4["free_terms"], ["don't"])

        # Directives with apostrophes in double quotes or bare
        res5 = data.parse_search_query('title:"Don\'t Stop" artist:Guns')
        self.assertEqual(res5["directives"], [("title", "Don't Stop"), ("artist", "Guns")])

        # Trailing apostrophe in directive value is preserved
        res6 = data.parse_search_query("title:believin'")
        self.assertEqual(res6["directives"], [("title", "believin'")])

    def test_parse_search_query_keeps_apostrophes_at_directive_value_edges(self):
        # Single quotes are literal text now, so a directive value that begins
        # and ends with apostrophes keeps them. (Regression: a leftover
        # compatibility branch stripped one matched pair, turning 'Tis' into Tis.)
        res = data.parse_search_query("title:'Tis'")
        self.assertEqual(res["directives"], [("title", "'Tis'")])

        res = data.parse_search_query("title:'n'")
        self.assertEqual(res["directives"], [("title", "'n'")])

        # A value of nothing but apostrophes is kept as typed.
        res = data.parse_search_query("title:''")
        self.assertEqual(res["directives"], [("title", "''")])

        # Double-quoting the value does not change this: the apostrophes are the value.
        res = data.parse_search_query('title:"\'Tis\'"')
        self.assertEqual(res["directives"], [("title", "'Tis'")])

        res = data.parse_search_query('artist:"\'Guns N\' Roses\'"')
        self.assertEqual(res["directives"], [("artist", "'Guns N' Roses'")])

    def test_quoted_directive_values_group_but_match_by_substring(self):
        # Issue #201: quotes group a multi-word value into one directive;
        # they do not mean exact match — matching stays case-folded
        # substring, so a quoted prefix still matches a longer title.
        quoted = data.parse_search_query('title:"Butterfly Garden"')
        self.assertEqual(quoted["directives"], [("title", "Butterfly Garden")])
        self.assertEqual(quoted["free_terms"], [])

        bare = data.parse_search_query("title:Butterfly Garden")
        self.assertEqual(bare["directives"], [("title", "Butterfly")])
        self.assertEqual(bare["free_terms"], ["garden"])

        row = {"Title": "Butterfly Garden", "Subtitle": "", "Artist": "",
               "Pack": "", "Chart": "", "Type": "", "Difficulty": ""}
        self.assertTrue(data.match_chart_query(row, 'title:"Butterfly"'))
        self.assertTrue(data.match_chart_query(row, 'title:"Butterfly Garden"'))
        self.assertFalse(data.match_chart_query(row, 'title:"Garden Butterfly"'))

        # The grouping is observable, not just parsing: with the words
        # split across Title and Pack, the bare form matches (the free
        # term may sit anywhere) while the quoted form does not.
        split_row = {"Title": "Butterfly", "Subtitle": "", "Artist": "",
                     "Pack": "Garden", "Chart": "", "Type": "", "Difficulty": ""}
        self.assertTrue(data.match_chart_query(split_row, "title:Butterfly Garden"))
        self.assertFalse(data.match_chart_query(split_row, 'title:"Butterfly Garden"'))

    def test_unclosed_quote_directive_still_matches_while_typing(self):
        # Issue #201: the search runs on every keystroke, so a quoted
        # value is unclosed mid-typing. The fallback split plus the
        # quote strip keeps the half-typed value matching instead of
        # matching nothing.
        parsed = data.parse_search_query('title:"Butterfly Garden')
        self.assertEqual(parsed["directives"], [("title", "Butterfly")])
        self.assertEqual(parsed["free_terms"], ["garden"])
        row = {"Title": "Butterfly Garden", "Subtitle": "", "Artist": "",
               "Pack": "", "Chart": "", "Type": "", "Difficulty": ""}
        self.assertTrue(data.match_chart_query(row, 'title:"Butterfly Garden'))

    def test_match_chart_query_with_apostrophes(self):
        row = {"Title": "Don't Stop Believin'", "Artist": "Journey", "Pack": "Rock"}
        self.assertTrue(data.match_chart_query(row, "don't stop believin'"))
        self.assertTrue(data.match_chart_query(row, 'pack:"Rock" don\'t'))
        self.assertTrue(data.match_chart_query(row, "believin'"))
        self.assertTrue(data.match_chart_query(row, 'title:"Don\'t Stop Believin\'"'))

    def test_match_chart_query_tolerates_missing_subtitle_key(self):
        # Issue #202: a row without a Subtitle key (an old or hand-built
        # row) must not crash the search; it simply has no subtitle text.
        row = {"Title": "Butterfly Garden", "Artist": "Smiley", "Pack": "ITG"}
        self.assertTrue(data.match_chart_query(row, "butterfly"))
        self.assertTrue(data.match_chart_query(row, "title:butterfly"))
        self.assertFalse(data.match_chart_query(row, "remix"))

    def test_match_chart_query_finds_escaped_semicolon_in_subtitle(self):
        # Issue #202: a Subtitle holding a literal ; (escaped as \; in the
        # tag) is searchable by that subtitle text. There is no subtitle:
        # directive — the subtitle is searched as free text.
        row = {"Title": "Sunset", "Subtitle": "Sunset ; Mix", "Artist": "",
               "Pack": "", "Chart": "", "Type": "", "Difficulty": ""}
        self.assertTrue(data.match_chart_query(row, '"Sunset ; Mix"'))
        self.assertTrue(data.match_chart_query(row, "sunset"))

    def test_match_chart_query_meter_exact_and_range(self):
        row = {"Meter": 11, "Title": "Summer", "Artist": "Smiley", "Pack": "ITG"}
        self.assertTrue(data.match_chart_query(row, "meter:11"))
        self.assertTrue(data.match_chart_query(row, "meter:10-12"))
        self.assertTrue(data.match_chart_query(row, "meter:>=10"))
        self.assertFalse(data.match_chart_query(row, "meter:12"))
        self.assertFalse(data.match_chart_query(row, "meter:<10"))

    def test_match_chart_query_bpm_overlap(self):
        row = {"bpm_min": 180.0, "bpm_max": 240.0, "Title": "Speedy"}
        # Queries that overlap with [180, 240]
        self.assertTrue(data.match_chart_query(row, "bpm:200"))
        self.assertTrue(data.match_chart_query(row, "bpm:200-300"))
        self.assertTrue(data.match_chart_query(row, "bpm:>150"))
        self.assertTrue(data.match_chart_query(row, "bpm:<200"))
        # Queries that do NOT overlap
        self.assertFalse(data.match_chart_query(row, "bpm:100-150"))
        self.assertFalse(data.match_chart_query(row, "bpm:>260"))
        self.assertFalse(data.match_chart_query(row, "bpm:<170"))

    def test_match_chart_query_does_not_crash_when_bpm_is_missing(self):
        row = {"bpm_min": "", "bpm_max": ""}
        self.assertFalse(data.match_chart_query(row, "bpm:200"))
        self.assertFalse(data.match_chart_query(row, "bpm:180-220"))

    def test_match_chart_query_duration_seconds_and_mmss(self):
        row = {"Time": 135.0, "Title": "Song"}
        self.assertTrue(data.match_chart_query(row, "time:>120"))
        self.assertTrue(data.match_chart_query(row, "time:>2:00"))
        self.assertTrue(data.match_chart_query(row, "time:2:00-2:30"))
        self.assertFalse(data.match_chart_query(row, "time:<2:00"))
        self.assertFalse(data.match_chart_query(row, "time:>150"))

    def test_empty_numeric_directive_is_skipped_while_typing(self):
        row = {"Meter": 11, "Title": "Summer", "Artist": "Smiley", "Pack": "ITG"}
        self.assertTrue(data.match_chart_query(row, "meter:"))
        self.assertTrue(data.match_chart_query(row, "m:"))
        self.assertTrue(data.match_chart_query(row, "meter: pack:ITG"))
        self.assertFalse(data.match_chart_query(row, "meter: pack:Other"))
        self.assertTrue(data.match_chart_query({"Time": 135.0}, "time:"))
        self.assertTrue(data.match_chart_query({"bpm_min": 180.0, "bpm_max": 240.0}, "bpm:"))

    def test_empty_grade_directive_still_means_unplayed(self):
        # Issue #130: unlike the numeric fields, an empty grade: is NOT
        # skipped — grade:"" is the pinned unplayed query (see
        # test_search_filters_compose_over_fixture_rows): it matches only
        # unscored charts. The alias form behaves the same.
        scored = {"Grade": "S", "Title": "Summer", "Artist": "Smiley", "Pack": "ITG"}
        self.assertFalse(data.match_chart_query(scored, "grade:"))
        self.assertFalse(data.match_chart_query(scored, "g:"))
        self.assertTrue(data.match_chart_query({"Grade": ""}, "grade:"))
        self.assertTrue(data.match_chart_query({"Grade": ""}, 'grade:""'))

    def test_unreadable_grade_directive_matches_nothing(self):
        row = {"Grade": "S", "Title": "Summer"}
        self.assertFalse(data.match_chart_query(row, "grade:banana"))
        self.assertFalse(data.match_chart_query(row, "grade:>="))
        self.assertFalse(data.match_chart_query(row, "grade:>=banana"))
        self.assertTrue(data.match_chart_query(row, "grade:>=S"))
        self.assertFalse(data.match_chart_query({"Grade": "B"}, "grade:>=S"))

    def test_find_unreadable_directives_grades(self):
        self.assertEqual(data.find_unreadable_directives("grade:banana"), ["grade:banana"])
        self.assertEqual(data.find_unreadable_directives("grade:>="), ["grade:>="])
        self.assertEqual(data.find_unreadable_directives("grade:>=banana"), ["grade:>=banana"])
        self.assertEqual(data.find_unreadable_directives("grade:B"), [])
        self.assertEqual(data.find_unreadable_directives("grade:>=S"), [])
        self.assertEqual(data.find_unreadable_directives("grade:Tier05"), ["grade:Tier05"])
        self.assertEqual(data.find_unreadable_directives("grade:>=Tier05"), [])
        self.assertEqual(data.find_unreadable_directives("grade:"), [])
        self.assertEqual(data.find_unreadable_directives("g:banana"), ["grade:banana"])
        self.assertEqual(data.find_unreadable_directives("grade:banana meter:abc"), ["grade:banana", "meter:abc"])

    def test_unreadable_numeric_directive_matches_nothing(self):
        row = {"Meter": 11, "Title": "Summer"}
        self.assertFalse(data.match_chart_query(row, "meter:abc"))
        self.assertFalse(data.match_chart_query({"bpm_min": 180.0, "bpm_max": 240.0}, "bpm:abc"))
        row_time = {"Time": 135.0, "Title": "Song"}
        self.assertFalse(data.match_chart_query(row_time, "time:abc"))
        self.assertTrue(data.match_chart_query(row_time, "time:>2:00"))

    def test_find_unreadable_directives_names_the_filter(self):
        self.assertEqual(data.find_unreadable_directives("meter:abc"), ["meter:abc"])
        self.assertEqual(data.find_unreadable_directives("meter:11 bpm:abc time:1:30"), ["bpm:abc"])
        self.assertEqual(data.find_unreadable_directives("meter:abc bpm:xyz"), ["meter:abc", "bpm:xyz"])
        self.assertEqual(data.find_unreadable_directives("meter:"), [])
        self.assertEqual(data.find_unreadable_directives("meter:11"), [])
        self.assertEqual(data.find_unreadable_directives("time:abc"), ["time:abc"])
        self.assertEqual(data.find_unreadable_directives("nps:abc"), ["peak_nps:abc"])
        self.assertEqual(data.find_unreadable_directives("time:1:30"), [])
        self.assertEqual(data.find_unreadable_directives("title:abc"), [])

    def test_match_chart_query_free_text_and_combined(self):
        row = {
            "Title": "Delirium",
            "Artist": "Smiley",
            "Pack": "In The Groove",
            "Meter": 12,
            "bpm_min": 240.0,
            "bpm_max": 240.0,
            "Time": 115.0,
            "Difficulty": "Challenge",
            "Type": "dance-single",
            "Grade": "S+",
            "Best %": 98.5,
        }
        self.assertTrue(data.match_chart_query(row, "Smiley meter:12"))
        self.assertTrue(data.match_chart_query(row, "delirium bpm:>200 time:<2:00"))
        self.assertTrue(data.match_chart_query(row, 'pack:"in the groove" grade:>=S'))
        self.assertFalse(data.match_chart_query(row, "Smiley meter:10"))
        self.assertFalse(data.match_chart_query(row, "Vertex"))

    def test_free_text_matches_subtitle_but_title_directive_does_not(self):
        # Issue #49, proposal 0007 Q2: free-text search covers the subtitle;
        # title: keeps matching only the title, so saved searches keep
        # their meaning.
        row = {
            "Title": "Neon Skyline",
            "Subtitle": "(Sunset Mix)",
            "Artist": "Vector Coast",
            "Pack": "Fixture Pack",
            "Chart": "",
            "Type": "dance-routine",
            "Difficulty": "Hard",
        }
        self.assertTrue(data.match_chart_query(row, "sunset"))
        self.assertTrue(data.match_chart_query(row, '"sunset mix"'))
        self.assertTrue(data.match_chart_query(row, "neon"))
        self.assertFalse(data.match_chart_query(row, "title:sunset"))
        self.assertTrue(data.match_chart_query(row, "title:neon"))
        self.assertFalse(data.match_chart_query(row, "zebra"))

    def test_score_and_percent_directives_use_their_own_columns(self):
        row = {"Score": 950000, "Best %": 95.0}
        self.assertTrue(data.match_chart_query(row, "score:>=900000"))
        self.assertFalse(data.match_chart_query(row, "score:>=960000"))
        self.assertTrue(data.match_chart_query(row, "percent:>=95"))
        self.assertFalse(data.match_chart_query(row, "percent:>=96"))

    def test_search_field_aliases_register_radar_counts(self):
        expected_mappings = {
            "jumps": "jumps",
            "jump": "jumps",
            "holds": "holds",
            "hold": "holds",
            "rolls": "rolls",
            "roll": "rolls",
            "mines": "mines",
            "mine": "mines",
            "hands": "hands",
            "hand": "hands",
            "lifts": "lifts",
            "lift": "lifts",
            "taps": "taps",
            "tap": "taps",
            "taps_holds": "taps",
            "tapsholds": "taps",
            "tapsandholds": "taps",
            "taps/holds": "taps",
        }
        for alias, canonical in expected_mappings.items():
            with self.subTest(alias=alias):
                self.assertIn(alias, data.SEARCH_FIELD_ALIASES)
                self.assertEqual(data.SEARCH_FIELD_ALIASES[alias], canonical)

    def test_match_chart_query_radar_exact_and_range_bounds(self):
        row = {
            "Title": "Radar Track",
            "Taps/Holds": 450,
            "Jumps": 30,
            "Holds": 15,
            "Rolls": 5,
            "Mines": 2,
            "Hands": 4,
            "Lifts": 1,
        }

        # Exact and equality operator
        self.assertTrue(data.match_chart_query(row, "jumps:30"))
        self.assertTrue(data.match_chart_query(row, "jumps:=30"))
        self.assertFalse(data.match_chart_query(row, "jumps:25"))
        self.assertTrue(data.match_chart_query(row, "mines:2"))
        self.assertFalse(data.match_chart_query(row, "mines:0"))

        # Greater than / Greater or equal
        self.assertTrue(data.match_chart_query(row, "jumps:>20"))
        self.assertFalse(data.match_chart_query(row, "jumps:>30"))
        self.assertTrue(data.match_chart_query(row, "holds:>=15"))
        self.assertFalse(data.match_chart_query(row, "holds:>=16"))

        # Less than / Less or equal
        self.assertTrue(data.match_chart_query(row, "mines:<5"))
        self.assertFalse(data.match_chart_query(row, "mines:<2"))
        self.assertTrue(data.match_chart_query(row, "mines:<=2"))
        self.assertTrue(data.match_chart_query(row, "lifts:<=1"))
        self.assertFalse(data.match_chart_query(row, "lifts:<1"))

        # Range bounds (.. and -)
        self.assertTrue(data.match_chart_query(row, "rolls:1..10"))
        self.assertTrue(data.match_chart_query(row, "rolls:5..10"))
        self.assertFalse(data.match_chart_query(row, "rolls:6..10"))
        self.assertTrue(data.match_chart_query(row, "hands:2-6"))
        self.assertFalse(data.match_chart_query(row, "hands:5-8"))

        # Taps directive maps to Taps/Holds column
        self.assertTrue(data.match_chart_query(row, "taps:450"))
        self.assertTrue(data.match_chart_query(row, "taps:>400"))
        self.assertFalse(data.match_chart_query(row, "taps:>500"))
        self.assertTrue(data.match_chart_query(row, "taps:400-500"))
        self.assertTrue(data.match_chart_query(row, "tap:>=450"))
        self.assertTrue(data.match_chart_query(row, "taps_holds:450"))
        self.assertTrue(data.match_chart_query(row, 'taps/holds:450'))

        # Singular aliases
        self.assertTrue(data.match_chart_query(row, "jump:>25"))
        self.assertTrue(data.match_chart_query(row, "hold:15"))
        self.assertTrue(data.match_chart_query(row, "roll:5"))
        self.assertTrue(data.match_chart_query(row, "mine:2"))
        self.assertTrue(data.match_chart_query(row, "hand:4"))
        self.assertTrue(data.match_chart_query(row, "lift:1"))

        # Multiple combined directives
        self.assertTrue(data.match_chart_query(row, "jumps:>20 holds:>=15 mines:<5 taps:400-500"))
        self.assertFalse(data.match_chart_query(row, "jumps:>20 holds:>=15 mines:0 taps:400-500"))

    def test_match_chart_query_radar_missing_and_invalid(self):
        empty_row = {"Title": "Empty"}
        zero_row = {"Title": "Zero", "Mines": 0, "Jumps": 0}

        # Missing column should not match positive or exact conditions
        self.assertFalse(data.match_chart_query(empty_row, "jumps:>0"))
        self.assertFalse(data.match_chart_query(empty_row, "jumps:0"))
        self.assertFalse(data.match_chart_query(empty_row, "mines:0"))

        # Zero column matches zero
        self.assertTrue(data.match_chart_query(zero_row, "mines:0"))
        self.assertFalse(data.match_chart_query(zero_row, "mines:>0"))
        self.assertTrue(data.match_chart_query(zero_row, "jumps:<=0"))

        # Invalid bounds do not match
        row = {"Jumps": 10}
        self.assertFalse(data.match_chart_query(row, "jumps:abc"))
        # An empty bound is unfinished typing, not a filter (issue #46)
        self.assertTrue(data.match_chart_query(row, "jumps:"))

    def test_replace_search_directive_radar_counts(self):
        query = "jumps:>10 mines:0"
        self.assertEqual(data.replace_search_directive(query, "jumps", ">20"), "jumps:>20 mines:0")
        self.assertEqual(data.replace_search_directive(query, "jump", ">20"), "jumps:>20 mines:0")
        self.assertEqual(data.replace_search_directive(query, "mines", None), "jumps:>10")
        self.assertEqual(data.replace_search_directive(query, "mine", None), "jumps:>10")

    def test_match_chart_query_grade_ranges_and_unplayed_charts(self):
        played_b = {"Grade": "B", "Score": 800000}
        played_s = {"Grade": "S", "Score": 960000}
        played_star = {"Grade": "★★★★", "Score": 1000000}
        unplayed = {"Grade": "", "Score": ""}
        unplayed_none = {"Grade": None}

        # Played chart matches valid grade bounds
        self.assertTrue(data.match_chart_query(played_b, "grade:<=B"))
        self.assertTrue(data.match_chart_query(played_b, "grade:>=B"))
        self.assertTrue(data.match_chart_query(played_b, "grade:<A"))
        self.assertTrue(data.match_chart_query(played_b, "grade:>C"))
        self.assertFalse(data.match_chart_query(played_b, "grade:>B"))
        self.assertFalse(data.match_chart_query(played_b, "grade:<B"))

        self.assertTrue(data.match_chart_query(played_s, "grade:>=A"))
        self.assertTrue(data.match_chart_query(played_s, "grade:<★★★★"))
        self.assertFalse(data.match_chart_query(played_s, "grade:<=B"))

        # The top grade (★★★★) matches itself and sits above every other grade
        self.assertTrue(data.match_chart_query(played_star, "grade:★★★★"))
        self.assertTrue(data.match_chart_query(played_star, "grade:>=★★★★"))
        self.assertTrue(data.match_chart_query(played_star, "grade:>S"))
        self.assertFalse(data.match_chart_query(played_star, "grade:<★★★★"))
        self.assertFalse(data.match_chart_query(played_star, "grade:>★★★★"))

        # Tier notation works identically
        self.assertTrue(data.match_chart_query(played_s, "grade:>=Tier06"))
        self.assertTrue(data.match_chart_query(played_b, "grade:<=Tier12"))

        # Unplayed charts must NEVER match inequality comparisons
        for query in ("grade:<=B", "grade:<A", "grade:>=D", "grade:>C", "grade:<=Tier17"):
            with self.subTest(query=query):
                self.assertFalse(data.match_chart_query(unplayed, query))
                self.assertFalse(data.match_chart_query(unplayed_none, query))

        # Invalid target grade names must evaluate to False rather than matching all charts
        for invalid_query in ("grade:>=Foo", "grade:<=Invalid", "grade:>Unknown", "grade:<Bar"):
            with self.subTest(query=invalid_query):
                self.assertFalse(data.match_chart_query(played_b, invalid_query))
                self.assertFalse(data.match_chart_query(unplayed, invalid_query))

        # Exact equality matching behaves as expected
        self.assertTrue(data.match_chart_query(played_b, "grade:B"))
        self.assertFalse(data.match_chart_query(played_b, "grade:S"))
        self.assertTrue(data.match_chart_query(unplayed, 'grade:""'))
        self.assertFalse(data.match_chart_query(unplayed, "grade:B"))

    def test_quote_for_search_reads_back_unchanged(self):
        for text in ("plain", "two words", 'say "hi"', "it's", "back\\slash", 'a: "b" \\ c', ""):
            self.assertEqual(data.split_search_query(data._quote_for_search(text)) or [""], [text], repr(text))
        self.assertEqual(data._quote_for_search("plain"), "plain")
        self.assertEqual(data._quote_for_search("it's"), "it's")


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
            row = sources.parse_cache_file(cache_file, {})[0][0]
            self.assertEqual(row["bpm_min"], 100.0)
            self.assertEqual(row["bpm_max"], 300.0)
            self.assertEqual(row["BPM"], "150")
            self.assertTrue(data.match_chart_query(row, data.parse_search_query("bpm:>250")))
            self.assertEqual(bpm_sort_key(row), (300.0, 100.0))

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
            row = sources.parse_cache_file(cache_file, {})[0][0]
            self.assertEqual(row["bpm_min"], "")
            self.assertEqual(row["bpm_max"], "")
            self.assertEqual(row["BPM"], "")

            # 1. bpm_sort_key places it in the missing-BPM group (ranks after numeric BPMs)
            normal_row = {"bpm_min": 100.0, "bpm_max": 200.0}
            self.assertEqual(bpm_sort_key(row), (float("inf"), float("inf")))
            self.assertEqual(sorted([row, normal_row], key=bpm_sort_key), [normal_row, row])

            # 2. match_chart_query: does not match bpm: queries
            self.assertFalse(data.match_chart_query(row, data.parse_search_query("bpm:150")))
            self.assertFalse(data.match_chart_query(row, data.parse_search_query("bpm:>0")))
            self.assertFalse(data.match_chart_query(row, data.parse_search_query("bpm:0")))
            self.assertFalse(data.match_chart_query(row, data.parse_search_query("bpm:100-200")))

            # 3. Distribution aggregation counts it in the missing/("?") category, not numeric bins
            bins = distribution.aggregate_bpm_distribution([row])
            q_bin = next(b for b in bins if b[0] == "?")
            self.assertEqual(q_bin[1], 1)
            # Numeric bins have count 0
            self.assertTrue(all(count == 0 for label, count, _, _ in bins if label != "?"))
