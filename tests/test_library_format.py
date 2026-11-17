import time
import unittest

from itgmania_library import library_format as data
from itgmania_library.library_constants import GRADE_NAMES, GRADE_OPTIONS


class SplitPathTests(unittest.TestCase):
    def test_split_path_normalizes_root_relative_paths(self):
        self.assertEqual(data.split_path("Songs/Pack/Song"), "Pack/Song")
        self.assertEqual(data.split_path("/Songs/Pack/Song"), "Pack/Song")
        self.assertEqual(data.split_path("Songs\\Pack\\Song"), "Pack/Song")
        self.assertEqual(data.split_path("AdditionalSongs/Pack/Song"), "Pack/Song")
        self.assertEqual(data.split_path("/AdditionalSongs/Pack/Song"), "Pack/Song")
        self.assertEqual(data.split_path("AdditionalSongs\\Pack\\Song"), "Pack/Song")

    def test_split_path_case_insensitivity_and_precedence(self):
        self.assertEqual(data.split_path("additionalsongs/Pack/Song"), "Pack/Song")
        self.assertEqual(data.split_path("ADDITIONALSONGS/Pack/Song"), "Pack/Song")
        self.assertEqual(data.split_path("songs/Pack/Song"), "Pack/Song")
        # When both occur in a path, the first matching component wins
        self.assertEqual(
            data.split_path("/Archive/Songs/Backup/AdditionalSongs/Pack/Song"),
            "Backup/AdditionalSongs/Pack/Song",
        )
        self.assertEqual(
            data.split_path("/Archive/AdditionalSongs/Backup/Songs/Pack/Song"),
            "Backup/Songs/Pack/Song",
        )

    def test_split_path_normalizes_filesystem_absolute_paths(self):
        self.assertEqual(
            data.split_path(r"C:\Games\ITGmania\Songs\Pack\Song"), "Pack/Song")
        self.assertEqual(
            data.split_path(r"D:\Games\ITGmania\AdditionalSongs\Pack\Song"), "Pack/Song")
        self.assertEqual(
            data.split_path("/home/player/ITGmania/Songs/Pack/Song"), "Pack/Song")
        self.assertEqual(
            data.split_path("/home/player/ITGmania/AdditionalSongs/Pack/Song"), "Pack/Song")

    def test_split_path_requires_songs_or_additionalsongs_component(self):
        path = r"C:\Games\MySongs\Pack\Song"
        self.assertEqual(data.split_path(path), "C:/Games/MySongs/Pack/Song")
        path2 = r"C:\Games\CustomSongs\Pack\Song"
        self.assertEqual(data.split_path(path2), "C:/Games/CustomSongs/Pack/Song")


class TagMapTests(unittest.TestCase):
    def test_tag_map_parses_escaped_delimiters(self):
        text = (
            "#TITLE:Song Title \\; Subtitle;\n"
            "#ARTIST:Artist \\; Feat;\n"
            "#TAG_WITH_BACKSLASH:Prefix\\\\Suffix;\n"
            "#TAG_ENDING_IN_SEMI:Ending with semi\\;;\n"
            "#TAG_WITH_ESCAPED_BACKSLASH_THEN_SEMI:Path\\\\;\n"
            "#TAG_WITH_ESCAPED_COLON:Key\\:Value;\n"
            "#NORMAL:NormalValue;\n"
        )
        tags = data.tag_map(text)
        self.assertEqual(tags["TITLE"], "Song Title ; Subtitle")
        self.assertEqual(tags["ARTIST"], "Artist ; Feat")
        self.assertEqual(tags["TAG_WITH_BACKSLASH"], "Prefix\\Suffix")
        self.assertEqual(tags["TAG_ENDING_IN_SEMI"], "Ending with semi;")
        self.assertEqual(tags["TAG_WITH_ESCAPED_BACKSLASH_THEN_SEMI"], "Path\\")
        self.assertEqual(tags["TAG_WITH_ESCAPED_COLON"], "Key:Value")
        self.assertEqual(tags["NORMAL"], "NormalValue")

    def test_tag_map_decodes_a_value_of_only_backslashes(self):
        # An escaped backslash pair decodes to one backslash; the value
        # contains a backslash, so the unescape pass runs on it.
        tags = data.tag_map("#ONLY:" + "\\" * 2 + ";\n")
        self.assertEqual(tags["ONLY"], "\\")

    def test_tag_map_decodes_escaped_slashes(self):
        # ITGmania writes "//" in text as "\/\/" so it is not read as a comment.
        tags = data.tag_map("#SONGFILENAME:Songs/Pack/My\\/\\/Song/audio.ogg;\n")
        self.assertEqual(tags["SONGFILENAME"], "Songs/Pack/My//Song/audio.ogg")

    def test_tag_map_supports_multiline_values_and_hash_in_text(self):
        text = (
            "#TITLE:Track #1 - Summer;\n"
            "#ARTIST:Artist #9 & Friends;\n"
            "#BPMS:0.000=120.000,\r\n"
            "16.000=140.000,\r\n"
            "32.000=160.000;\n"
            "#GENRE:Dance;\n"
        )
        tags = data.tag_map(text)
        self.assertEqual(tags["TITLE"], "Track #1 - Summer")
        self.assertEqual(tags["ARTIST"], "Artist #9 & Friends")
        self.assertEqual(tags["GENRE"], "Dance")
        self.assertEqual(data.parse_bpms(tags["BPMS"]), (120.0, 160.0))

    def test_tag_map_does_not_backtrack_over_blank_lines_in_unterminated_value(self):
        text = "#TITLE:" + "\n" * 25 + "unterminated\n#ARTIST:Artist;"
        started = time.perf_counter()
        tags = data.tag_map(text)
        elapsed = time.perf_counter() - started
        self.assertEqual(tags, {"ARTIST": "Artist"})
        self.assertLess(elapsed, 1.0)


class DifficultySortTests(unittest.TestCase):
    def test_difficulty_key_matches_filter_gameplay_order(self):
        values = ["Edit", "Hard", "Challenge", "Medium", "Easy", "Beginner", "Custom"]
        self.assertEqual(
            sorted(values, key=data.difficulty_sort_key),
            ["Beginner", "Easy", "Medium", "Hard", "Challenge", "Edit", "Custom"],
        )

    def test_difficulty_key_is_case_insensitive(self):
        values = ["hard", "Beginner", "EASY"]
        self.assertEqual(sorted(values, key=data.difficulty_sort_key), ["Beginner", "EASY", "hard"])


class BpmFormatTests(unittest.TestCase):
    def test_parse_bpms_single_and_range(self):
        self.assertEqual(data.parse_bpms("0.000=150.000"), (150.0, 150.0))
        self.assertEqual(data.parse_bpms("0.000=100.000,64.000=300.000"), (100.0, 300.0))
        self.assertIsNone(data.parse_bpms(""))
        self.assertIsNone(data.parse_bpms("not-a-bpm"))

    def test_format_bpm_display_prefers_displaybpm(self):
        self.assertEqual(data.format_bpm_display("*", 100, 300), "*")
        self.assertEqual(data.format_bpm_display("180", 100, 300), "180")
        self.assertEqual(data.format_bpm_display("120:180", 100, 300), "120–180")
        self.assertEqual(data.format_bpm_display("", 150, 150), "150")
        self.assertEqual(data.format_bpm_display("", 100, 300), "100–300")
        self.assertEqual(data.format_bpm_display(None, "", ""), "")

    def test_bpm_sort_key_orders_by_max_then_min(self):
        slow_gimmick = {"bpm_min": 100, "bpm_max": 300}
        steady = {"bpm_min": 120, "bpm_max": 150}
        ordered = sorted([steady, slow_gimmick], key=data.bpm_sort_key)
        self.assertEqual(ordered[0], steady)
        self.assertEqual(ordered[1], slow_gimmick)

    def test_parse_bpms_positive_values_only(self):
        # Synthetic cases from issue #48 with post-fix expectations
        self.assertEqual(data.parse_bpms("0=150,64=-150"), (150.0, 150.0))
        self.assertEqual(data.parse_bpms("0=0,4=150"), (150.0, 150.0))
        self.assertEqual(data.parse_bpms("0=150,10=999999"), (150.0, 999999.0))
        # NaN handling (fold-in): keep-filter on v > 0 drops NaN without poisoning min/max
        self.assertEqual(data.parse_bpms("0=nan,4=150"), (150.0, 150.0))
        self.assertIsNone(data.parse_bpms("0=nan"))
        # All-nonpositive returns None (treated as no BPM)
        self.assertIsNone(data.parse_bpms("0=-150,64=0"))

    def test_format_bpm_display_post_fix_synthetic_values(self):
        # Post-fix display expectations for synthetic cases
        min1, max1 = data.parse_bpms("0=150,64=-150")
        self.assertEqual(data.format_bpm_display(None, min1, max1), "150")
        min2, max2 = data.parse_bpms("0=0,4=150")
        self.assertEqual(data.format_bpm_display(None, min2, max2), "150")
        min3, max3 = data.parse_bpms("0=150,10=999999")
        self.assertEqual(data.format_bpm_display(None, min3, max3), "150–999999")


class GradeSortTests(unittest.TestCase):
    def test_grade_sort_key_follows_tier_order(self):
        grades = ["S-", "S+", "S", "A+", "A", "D", "★★★★"]
        ordered = sorted(grades, key=data.grade_sort_key)
        self.assertEqual(ordered, ["★★★★", "S+", "S", "S-", "A+", "A", "D"])

    def test_grade_filter_options_are_defined_labels(self):
        self.assertEqual(GRADE_OPTIONS, tuple(GRADE_NAMES.values()))


class NonFiniteFormatTests(unittest.TestCase):
    """Issues #123 and #137: a non-finite value reads as missing (blank),
    not a crash out of the format helpers."""

    def test_format_duration_treats_non_finite_as_missing(self):
        for value in ("nan", "1e999", float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                self.assertEqual(data.format_duration(value), "")

    def test_format_duration_treats_unparseable_as_missing(self):
        for value in ("abc", None):
            with self.subTest(value=value):
                self.assertEqual(data.format_duration(value), "")

    def test_format_duration_still_formats_real_values(self):
        self.assertEqual(data.format_duration(0), "0:00")
        self.assertEqual(data.format_duration(90), "1:30")
        self.assertEqual(data.format_duration(3661), "1:01:01")
        self.assertEqual(data.format_duration("120"), "2:00")

    def test_format_bpm_display_treats_non_finite_as_missing(self):
        self.assertEqual(data.format_bpm_display(None, float("inf"), float("inf")), "")
        self.assertEqual(data.format_bpm_display("nan", 150, 150), "")
        self.assertEqual(data.format_bpm_display("inf", 150, 150), "")
        self.assertEqual(data.format_bpm_display("150:inf", 150, 150), "")
        self.assertEqual(data.format_bpm_display("nan:nan", 150, 150), "")
        self.assertEqual(data.format_bpm_display(None, 150, float("inf")), "")

    def test_format_bpm_display_still_formats_real_values(self):
        self.assertEqual(data.format_bpm_display(None, 100, 300), "100–300")
        self.assertEqual(data.format_bpm_display("120", 100, 300), "120")
        self.assertEqual(data.format_bpm_display("*", 100, 300), "*")
        self.assertEqual(data.format_bpm_display(None, 150, 150), "150")


class HugeIntValueTests(unittest.TestCase):
    """Issue #215: a huge int from a hand-edited snapshot's JSON number
    (10**10000) reads as missing, not a crash out of the format helpers."""

    def test_number_treats_a_huge_int_as_missing(self):
        self.assertEqual(data.number(10**10000), 0)
        self.assertEqual(data.number(10**10000, ""), "")

    def test_format_duration_treats_a_huge_int_as_missing(self):
        self.assertEqual(data.format_duration(10**10000), "")

    def test_bpm_sort_key_treats_a_huge_int_as_missing(self):
        self.assertEqual(
            data.bpm_sort_key({"bpm_max": 10**10000, "bpm_min": 150}),
            (float("inf"), float("inf")),
        )
        self.assertEqual(
            data.bpm_sort_key({"bpm_max": 300, "bpm_min": 100}),
            (300.0, 100.0),
        )


class FormatRefreshTimeTests(unittest.TestCase):
    """format_refresh_time: an ISO timestamp in, a display string out."""

    def test_naive_iso_renders_as_local_date_and_time(self):
        # A naive timestamp is read as local time, so the wall time is
        # unchanged by astimezone() whatever the timezone.
        self.assertEqual(
            data.format_refresh_time("2026-11-14T10:30:00"), "2026-11-14 10:30")

    def test_date_only_renders_at_midnight(self):
        self.assertEqual(
            data.format_refresh_time("2026-11-14"), "2026-11-14 00:00")

    def test_unparseable_is_unknown(self):
        for value in (None, "", "not-a-date"):
            with self.subTest(value=value):
                self.assertEqual(data.format_refresh_time(value), "unknown")
