import unittest

from itgmania_library import library_course as data


class CourseModelTests(unittest.TestCase):
    def test_course_song_line_formats_path_and_difficulty(self):
        self.assertEqual(
            data.course_song_line("Pack/Song", "Hard"),
            "#SONG:Pack/Song:Hard:;",
        )

    def test_course_song_lines_from_rows(self):
        rows = [
            {"Course path": "Pack/One", "Difficulty": "Hard"},
            {"Course path": "Pack/Two", "Difficulty": "Challenge"},
        ]
        self.assertEqual(
            data.course_song_lines(rows),
            ["#SONG:Pack/One:Hard:;", "#SONG:Pack/Two:Challenge:;"],
        )

    def test_format_new_course_includes_title_and_trailing_newline(self):
        body = data.format_new_course("My Course", ["#SONG:Pack/One:Hard:;"])
        self.assertEqual(body, "#COURSE:My Course;\n#SONG:Pack/One:Hard:;\n")

    def test_parse_course_text_reads_title_and_songs(self):
        text = (
            "#COURSE:Example;\n"
            "#SONG:Pack/One:Hard:;\n"
            "#SONG:Pack/Two:Challenge:;\n"
        )
        parsed = data.parse_course_text(text)
        self.assertTrue(parsed["has_course"])
        self.assertEqual(parsed["title"], "Example")
        self.assertEqual(
            [(song["path"], song["difficulty"]) for song in parsed["songs"]],
            [("Pack/One", "Hard"), ("Pack/Two", "Challenge")],
        )
        self.assertIsNone(parsed["trailing_risk"])

    def test_parse_course_text_reads_two_and_three_parameter_songs(self):
        text = (
            "#COURSE:Mixed Course;\n"
            "#SONG:Pack/One:Hard;\n"
            "#SONG:Pack/Two:Challenge:;\n"
            "#SONG:Pack/Three:Medium:failoff;\n"
        )
        parsed = data.parse_course_text(text)
        self.assertTrue(parsed["has_course"])
        self.assertEqual(parsed["title"], "Mixed Course")
        self.assertEqual(
            [(song["path"], song["difficulty"]) for song in parsed["songs"]],
            [("Pack/One", "Hard"), ("Pack/Two", "Challenge"), ("Pack/Three", "Medium")],
        )
        self.assertIsNone(parsed["trailing_risk"])

    def test_course_trailing_risk_detects_mods_after_last_song(self):
        text = "#COURSE:Example;\n#SONG:Pack/One:Hard:;\n#MODS:xmod;\n"
        self.assertEqual(data.course_trailing_risk(text), "MODS")
        self.assertEqual(data.parse_course_text(text)["trailing_risk"], "MODS")

    def test_course_trailing_risk_detects_modifiers_after_songselect(self):
        for directive, expected in (("#MODS:xmod;\n", "MODS"), ("#GAINSECONDS:15;\n", "GAINSECONDS")):
            with self.subTest(directive=directive):
                text = f"#COURSE:Example;\n#SONGSELECT:METER=10;\n{directive}"
                self.assertEqual(data.course_trailing_risk(text), expected)
                self.assertEqual(data.parse_course_text(text)["trailing_risk"], expected)

    def test_course_trailing_risk_ignores_directives_before_last_song(self):
        text = "#COURSE:Example;\n#MODS:xmod;\n#SONG:Pack/One:Hard:;\n"
        self.assertIsNone(data.course_trailing_risk(text))

    def test_course_trailing_risk_ignores_directives_before_last_songselect(self):
        text = "#COURSE:Example;\n#MODS:xmod;\n#SONGSELECT:METER=10;\n"
        self.assertIsNone(data.course_trailing_risk(text))

    def test_course_trailing_risk_ignores_commented_out_song(self):
        # A commented-out #SONG is not a real entry, so a #MODS before it
        # still trails the last real song (issue #56).
        text = (
            "#COURSE:Example;\n"
            "#SONG:Pack/One:Hard;\n"
            "#MODS:TIME=0:LEN=5:MODS=failoff;\n"
            "// #SONG:Pack/Old:Hard;\n"
        )
        self.assertEqual(data.course_trailing_risk(text), "MODS")
        self.assertEqual(data.parse_course_text(text)["trailing_risk"], "MODS")

    def test_course_trailing_risk_ignores_commented_out_directives(self):
        for commented in ("//#MODS:xmod;", "// #GAINSECONDS:10;"):
            with self.subTest(commented=commented):
                text = f"#COURSE:Example;\n#SONG:Pack/One:Hard:;\n{commented}\n"
                self.assertIsNone(data.course_trailing_risk(text))

    def test_parse_course_text_ignores_comments(self):
        text = (
            "#COURSE:Example; // title note\n"
            "// #SONG:Pack/Old:Hard:;\n"
            "#SONG:Pack/One:Hard:; // trailing note\n"
        )
        parsed = data.parse_course_text(text)
        self.assertEqual(parsed["title"], "Example")
        self.assertEqual(
            [(song["path"], song["difficulty"]) for song in parsed["songs"]],
            [("Pack/One", "Hard")],
        )
        self.assertIsNone(parsed["trailing_risk"])

    def test_course_scan_treats_escaped_slashes_as_not_a_comment(self):
        # \/\/ is an escaped slash pair, so the #MODS after it is real.
        text = "#COURSE:Example;\n#SONG:Pack/One:Hard:; \\/\\/ #MODS:xmod;\n"
        self.assertEqual(data.course_trailing_risk(text), "MODS")
        parsed = data.parse_course_text("#COURSE:My \\/\\/ Course;\n#SONG:Pack/One:Hard:;\n")
        self.assertEqual(parsed["title"], "My \\/\\/ Course")

    def test_validate_course_fields_rejects_empty_and_unsafe_text(self):
        self.assertEqual(data.validate_course_fields([]), "Add at least one chart to the course.")
        self.assertEqual(
            data.validate_course_fields(
                [{"Course path": "Pack/One", "Difficulty": "Hard"}],
                title="",
            ),
            "Enter a title for this course.",
        )
        self.assertEqual(
            data.validate_course_fields(
                [{"Course path": "Pack/One", "Difficulty": "Hard"}],
                title="   ",
            ),
            "Enter a title for this course.",
        )
        self.assertIn(
            "titles",
            data.validate_course_fields(
                [{"Course path": "Pack/One", "Difficulty": "Hard"}],
                title="Bad:Title",
            ).casefold(),
        )
        self.assertIn(
            "paths",
            data.validate_course_fields(
                [{"Course path": "Pack:One", "Difficulty": "Hard"}],
            ).casefold(),
        )
        self.assertIn(
            "difficulties",
            data.validate_course_fields(
                [{"Course path": "Pack/One", "Difficulty": "Hard:Extra"}],
            ).casefold(),
        )
        self.assertIsNone(
            data.validate_course_fields(
                [{"Course path": "Pack/One", "Difficulty": "Hard"}],
            )
        )
        self.assertIsNone(
            data.validate_course_fields(
                [{"Course path": "Pack/One", "Difficulty": "Hard"}],
                title="Safe Title",
            )
        )

    def test_validate_course_fields_rejects_double_slash_comments(self):
        self.assertIn(
            "//",
            data.validate_course_fields(
                [{"Course path": "Pack/One", "Difficulty": "Hard"}],
                title="Spring // Autumn",
            ),
        )
        self.assertIn(
            "//",
            data.validate_course_fields(
                [{"Course path": "Pack//One", "Difficulty": "Hard"}],
            ),
        )
        self.assertIn(
            "//",
            data.validate_course_fields(
                [{"Course path": "Pack/One", "Difficulty": "Hard//Edit"}],
            ),
        )

    def test_validate_course_fields_allows_single_slash(self):
        self.assertIsNone(
            data.validate_course_fields(
                [{"Course path": "Pack/Song/Title", "Difficulty": "Hard"}],
                title="Safe / Single / Slash",
            )
        )

    def test_find_ambiguous_course_entries_unique_charts_are_not_flagged(self):
        library = [
            {"Course path": "Pack/Song", "Difficulty": "Hard", "Type": "dance-single"},
            {"Course path": "Pack/Song", "Difficulty": "Challenge", "Type": "dance-single"},
            {"Course path": "Pack/Other", "Difficulty": "Hard", "Type": "dance-double"},
        ]
        self.assertEqual(data.find_ambiguous_course_entries([library[0]], library), [])

    def test_find_ambiguous_course_entries_flags_same_difficulty_in_another_type(self):
        single = {"Course path": "Pack/Song", "Difficulty": "Hard", "Type": "dance-single"}
        double = {"Course path": "Pack/Song", "Difficulty": "Hard", "Type": "dance-double"}
        easier_double = {"Course path": "Pack/Song", "Difficulty": "Easy", "Type": "dance-double"}
        self.assertEqual(data.find_ambiguous_course_entries([single], [single, double]), [single])
        # A different difficulty in the other type is a different .CRS line, not an ambiguity.
        self.assertEqual(data.find_ambiguous_course_entries([single], [single, easier_double]), [])

    def test_find_ambiguous_course_entries_flags_a_song_with_two_edits_of_one_type(self):
        edit_one = {"Course path": "Pack/Song", "Difficulty": "Edit", "Type": "dance-single"}
        edit_two = {"Course path": "Pack/Song", "Difficulty": "Edit", "Type": "dance-single"}
        chart = {"Course path": "Pack/Song", "Difficulty": "Hard", "Type": "dance-single"}
        self.assertEqual(
            data.find_ambiguous_course_entries([edit_one], [edit_one, edit_two, chart]), [edit_one])
        # A single Edit chart is the only chart its line can mean.
        self.assertEqual(data.find_ambiguous_course_entries([edit_one], [edit_one, chart]), [])
        # An Edit in another type is the cross-type case, flagged the same way.
        double_edit = {"Course path": "Pack/Song", "Difficulty": "Edit", "Type": "dance-double"}
        self.assertEqual(
            data.find_ambiguous_course_entries([edit_one], [edit_one, double_edit]), [edit_one])

    def test_find_ambiguous_course_entries_dedupes_and_ignores_songs_not_in_the_library(self):
        single = {"Course path": "Pack/Song", "Difficulty": "Hard", "Type": "dance-single"}
        double = {"Course path": "Pack/Song", "Difficulty": "Hard", "Type": "dance-double"}
        stale = {"Course path": "Pack/Gone", "Difficulty": "Hard", "Type": "dance-single"}
        flagged = data.find_ambiguous_course_entries([single, single, stale], [single, double])
        self.assertEqual(flagged, [single])


class CourseAppendTests(unittest.TestCase):
    def test_appends_to_crlf_file_without_rewriting_existing_bytes(self):
        existing = b"#COURSE:Existing;\r\n#SONG:Pack/One:Hard:;\r\n"
        addition = data.course_append_bytes(existing, ["#SONG:Pack/Two:Challenge:;"])
        self.assertEqual(addition, b"#SONG:Pack/Two:Challenge:;\r\n")
        self.assertEqual(existing + addition,
                         b"#COURSE:Existing;\r\n#SONG:Pack/One:Hard:;\r\n"
                         b"#SONG:Pack/Two:Challenge:;\r\n")

    def test_adds_separator_if_existing_file_has_no_final_newline(self):
        addition = data.course_append_bytes(
            b"#COURSE:Existing;\n#SONG:Pack/One:Hard:;",
            ["#SONG:Pack/Two:Challenge:;"],
        )
        self.assertEqual(addition, b"\n#SONG:Pack/Two:Challenge:;\n")

    def test_appends_to_course_with_songselect(self):
        existing = b"#COURSE:Existing;\n#SONGSELECT:METER=10;\n"
        addition = data.course_append_bytes(existing, ["#SONG:Pack/Two:Challenge:;"])
        self.assertEqual(addition, b"#SONG:Pack/Two:Challenge:;\n")
        self.assertEqual(
            existing + addition,
            b"#COURSE:Existing;\n#SONGSELECT:METER=10;\n#SONG:Pack/Two:Challenge:;\n",
        )

    def test_refuses_trailing_modifiers(self):
        for directive in ("#MODS:xmod;", "#GAINSECONDS:10;"):
            with self.subTest(directive=directive):
                existing = f"#COURSE:Existing;\n#SONG:Pack/One:Hard:;\n{directive}".encode()
                with self.assertRaisesRegex(ValueError, "ends with"):
                    data.course_append_bytes(existing, ["#SONG:Pack/Two:Challenge:;"])

    def test_refuses_trailing_modifiers_after_songselect(self):
        for directive in ("#MODS:xmod;", "#GAINSECONDS:10;"):
            with self.subTest(directive=directive):
                existing = f"#COURSE:Existing;\n#SONGSELECT:METER=10;\n{directive}".encode()
                with self.assertRaisesRegex(ValueError, "ends with"):
                    data.course_append_bytes(existing, ["#SONG:Pack/Two:Challenge:;"])

    def test_refuses_files_that_are_not_courses(self):
        with self.assertRaisesRegex(ValueError, "#COURSE"):
            data.course_append_bytes(b"#TITLE:Not a course;", ["#SONG:Pack/Two:Challenge:;"])

    def test_refuses_mods_hidden_by_commented_out_song(self):
        existing = (
            b"#COURSE:Existing;\n#SONG:Pack/One:Hard;\n"
            b"#MODS:TIME=0:LEN=5:MODS=failoff;\n// #SONG:Pack/Old:Hard;\n"
        )
        with self.assertRaisesRegex(ValueError, "ends with #MODS"):
            data.course_append_bytes(existing, ["#SONG:Pack/Two:Challenge:;"])

    def test_allows_commented_out_trailing_directives(self):
        existing = b"#COURSE:Existing;\n#SONG:Pack/One:Hard:;\n//#MODS:xmod;\n"
        addition = data.course_append_bytes(existing, ["#SONG:Pack/Two:Challenge:;"])
        self.assertEqual(addition, b"#SONG:Pack/Two:Challenge:;\n")

    def test_refuses_course_whose_only_entries_are_commented_out(self):
        existing = b"#COURSE:Existing;\n// #SONG:Pack/Old:Hard;\n"
        with self.assertRaisesRegex(ValueError, "at least one #SONG"):
            data.course_append_bytes(existing, ["#SONG:Pack/Two:Challenge:;"])
