import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from itgmania_library import library_sources as data
from itgmania_library.library_constants import HEADERS


class ParsingTests(unittest.TestCase):
    def test_cache_chart_matches_stats_by_normalized_key(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "song.cache"
            cache_file.write_text(
                "#TITLE:Example;\n"
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#MUSICLENGTH:123;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Hard;\n"
                "#METER:10;\n",
                encoding="utf-8",
            )
            scores = {
                ("pack/song", "dance-single", "hard"): {
                    "Score": "987654", "Grade": "Tier05", "PercentDP": "0.98", "plays": "4",
                }
            }
            rows, _ = data.parse_cache_file(cache_file, scores)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Course path"], "Pack/Song")
        self.assertEqual(rows[0]["Score"], 987654)
        self.assertEqual(rows[0]["Best %"], 98.0)
        self.assertEqual(rows[0]["Plays"], 4)

    def test_subtitle_parsed_with_and_without(self):
        # Issue #49: #SUBTITLE rides along as a row key; a song without
        # one gets an empty string, not a missing key.
        fixture = Path(__file__).parent / "fixtures" / "routine_subtitle.cache"
        rows, _skipped = data.parse_cache_file(fixture, {})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Title"], "Neon Skyline")
        self.assertEqual(rows[0]["Subtitle"], "(Sunset Mix)")
        plain = Path(__file__).parent / "fixtures" / "plain_tune.cache"
        plain_rows, _ = data.parse_cache_file(plain, {})
        self.assertTrue(plain_rows)
        for row in plain_rows:
            self.assertEqual(row["Subtitle"], "")

    def test_cache_file_reports_blocks_skipped_for_missing_metadata(self):
        # Issue #18: a chart block without #STEPSTYPE or #DIFFICULTY is
        # dropped; the parse returns the count alongside the rows so the
        # load summary can report it.
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "song.cache"
            cache_file.write_text(
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Hard;\n"
                "#METER:10;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#METER:12;\n"
                "#NOTEDATA:;\n"
                "#DIFFICULTY:Challenge;\n"
                "#METER:13;\n",
                encoding="utf-8",
            )
            rows, skipped_blocks = data.parse_cache_file(cache_file, {})

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Meter"], 10)
        self.assertEqual(skipped_blocks, 2)

    def test_cache_file_with_no_chart_blocks_skips_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "song.cache"
            cache_file.write_text(
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#TITLE:No Charts;\n",
                encoding="utf-8",
            )
            rows, skipped_blocks = data.parse_cache_file(cache_file, {})

        self.assertEqual(rows, [])
        self.assertEqual(skipped_blocks, 0)

    def test_cache_radar_and_tech_counts_use_their_named_positions(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "song.cache"
            radar = list(range(len(data.RADAR_FIELDS))) * 2
            tech = list(range(len(data.TECH_FIELDS))) * 2
            cache_file.write_text(
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Challenge;\n"
                f"#RADARVALUES:{','.join(map(str, radar))};\n"
                f"#TECHCOUNTS:{','.join(map(str, tech))};\n",
                encoding="utf-8",
            )
            row = data.parse_cache_file(cache_file, {})[0][0]

        self.assertEqual(row["Taps/Holds"], 6)
        self.assertEqual(row["Jumps"], 7)
        self.assertEqual(row["Holds"], 8)
        self.assertEqual(row["Mines"], 9)
        self.assertEqual(row["Hands"], 10)
        self.assertEqual(row["Rolls"], 11)
        self.assertEqual(row["Lifts"], 12)
        for index, field in enumerate(data.TECH_FIELDS):
            self.assertEqual(row[field], index)

    def test_cache_short_radar_and_tech_lists_leave_missing_values_blank(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "short.cache"
            cache_file.write_text(
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Challenge;\n"
                "#RADARVALUES:0,1,2,3,4,5,6,7,8,9,10;\n"
                "#TECHCOUNTS:1,2;\n",
                encoding="utf-8",
            )
            row = data.parse_cache_file(cache_file, {})[0][0]

        self.assertEqual(row["Mines"], 9)
        self.assertEqual(row["Hands"], 10)
        self.assertEqual(row["Rolls"], "")
        self.assertEqual(row["Lifts"], "")
        self.assertEqual(row["Crossovers"], 1)
        self.assertEqual(row["HalfCrossovers"], 2)
        self.assertEqual(row["FullCrossovers"], "")
        self.assertEqual(row["Peak NPS"], "")

    def test_cache_peak_nps_is_parsed_when_present(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "peak.cache"
            # One value: what ITGmania writes for ordinary charts such as dance-single
            cache_file.write_text(
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Hard;\n"
                "#PEAKNPS:12.5;\n",
                encoding="utf-8",
            )
            row = data.parse_cache_file(cache_file, {})[0][0]
            self.assertEqual(row["Peak NPS"], 12.5)

            # Two values, one per player: written only for couples and routine charts
            cache_file.write_text(
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-couple;\n"
                "#DIFFICULTY:Hard;\n"
                "#PEAKNPS:14.250|14.250;\n",
                encoding="utf-8",
            )
            row_piped = data.parse_cache_file(cache_file, {})[0][0]
            self.assertEqual(row_piped["Peak NPS"], 14.25)

            # Different values per player: the first player's value is used
            cache_file.write_text(
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-couple;\n"
                "#DIFFICULTY:Hard;\n"
                "#PEAKNPS:16.8|10.5;\n",
                encoding="utf-8",
            )
            row_asym = data.parse_cache_file(cache_file, {})[0][0]
            self.assertEqual(row_asym["Peak NPS"], 16.8)

    def test_cache_file_handles_escaped_delimiters_in_title_and_path(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "escaped.cache"
            cache_file.write_text(
                "#TITLE:Song Title \\; Subtitle;\n"
                "#ARTIST:Artist \\; Feat;\n"
                "#SONGFILENAME:Songs/Pack/Special \\; Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Hard;\n"
                "#METER:9;\n",
                encoding="utf-8",
            )
            scores = {
                ("pack/special ; song", "dance-single", "hard"): {
                    "Score": "950000", "Grade": "Tier06", "PercentDP": "0.95", "plays": "3",
                }
            }
            rows, _ = data.parse_cache_file(cache_file, scores)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["Title"], "Song Title ; Subtitle")
            self.assertEqual(rows[0]["Artist"], "Artist ; Feat")
            self.assertEqual(rows[0]["Course path"], "Pack/Special ; Song")
            self.assertEqual(rows[0]["Score"], 950000)

    def test_stats_index_matches_additionalsongs_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores>"
                "<Song Dir='AdditionalSongs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Hard'>"
                "<HighScoreList><NumTimesPlayed>3</NumTimesPlayed>"
                "<HighScore><PercentDP>0.96</PercentDP><Score>456</Score></HighScore>"
                "</HighScoreList></Steps></Song>"
                "</SongScores></Stats>",
                encoding="utf-8",
            )
            scores = data.stats_index(stats_file)

        self.assertEqual(scores[("pack/song", "dance-single", "hard")]["Score"], "456")
        self.assertEqual(scores[("pack/song", "dance-single", "hard")]["plays"], "3")

    def test_additionalsongs_score_attaches_to_cached_chart(self):
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores>"
                "<Song Dir='AdditionalSongs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Hard'>"
                "<HighScoreList><NumTimesPlayed>3</NumTimesPlayed>"
                "<HighScore><PercentDP>0.96</PercentDP><Score>456</Score></HighScore>"
                "</HighScoreList></Steps></Song>"
                "</SongScores></Stats>",
                encoding="utf-8",
            )
            cache_file = Path(directory) / "song.cache"
            cache_file.write_text(
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Hard;\n",
                encoding="utf-8",
            )
            rows, _ = data.parse_cache_file(cache_file, data.stats_index(stats_file))

        self.assertEqual(rows[0]["Score"], 456)
        self.assertEqual(rows[0]["Plays"], 3)

    def test_stats_index_merges_legacy_additionalsongs_and_songs_entries(self):
        legacy = (
            "<Song Dir='AdditionalSongs/Pack/Song'>"
            "<Steps StepsType='dance-single' Difficulty='Hard'>"
            "<HighScoreList><NumTimesPlayed>9</NumTimesPlayed>"
            "<HighScore><PercentDP>0.90</PercentDP><Score>100</Score></HighScore>"
            "</HighScoreList></Steps></Song>"
        )
        current = (
            "<Song Dir='Songs/Pack/Song'>"
            "<Steps StepsType='dance-single' Difficulty='Hard'>"
            "<HighScoreList><NumTimesPlayed>5</NumTimesPlayed>"
            "<HighScore><PercentDP>0.95</PercentDP><Score>200</Score></HighScore>"
            "</HighScoreList></Steps></Song>"
        )
        # The legacy entry has more plays, the current one the better score; the merged
        # result must keep both, whichever entry comes first in the file.
        for label, entries in (("legacy first", legacy + current), ("current first", current + legacy)):
            with self.subTest(label), tempfile.TemporaryDirectory() as directory:
                stats_file = Path(directory) / "Stats.xml"
                stats_file.write_text(
                    f"<Stats><SongScores>{entries}</SongScores></Stats>", encoding="utf-8")
                entry = data.stats_index(stats_file)[("pack/song", "dance-single", "hard")]
            self.assertEqual(entry["Score"], "200")
            self.assertEqual(entry["plays"], "9")

    def test_cache_file_normalizes_crlf_in_multiline_values(self):
        # parse_cache_file reads in text mode, whose universal-newline
        # handling turns CRLF into \n before tag_map sees the text, so a
        # multiline value reaches the row with \n endings. (A byte read
        # would skip that translation and change the row.)
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "crlf.cache"
            cache_file.write_bytes(
                b"#TITLE:Song;\r\n"
                b"#ARTIST:First\r\nSecond;\r\n"
                b"#SONGFILENAME:Songs/Pack/Song/audio.ogg;\r\n"
                b"#NOTEDATA:;\r\n"
                b"#STEPSTYPE:dance-single;\r\n"
                b"#DIFFICULTY:Hard;\r\n"
                b"#METER:9;\r\n"
            )
            rows, _ = data.parse_cache_file(cache_file, {})

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Artist"], "First\nSecond")

    def test_cache_file_parses_multiline_bpms_correctly(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "tempo.cache"
            cache_file.write_text(
                "#TITLE:Tempo Change;\n"
                "#SONGFILENAME:Songs/Pack/Tempo/audio.ogg;\n"
                "#BPMS:0.000=100.000,\n"
                "16.000=150.000,\n"
                "32.000=200.000;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Hard;\n",
                encoding="utf-8",
            )
            rows, _ = data.parse_cache_file(cache_file, {})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["BPM"], "100–200")
        self.assertEqual(rows[0]["bpm_min"], 100.0)
        self.assertEqual(rows[0]["bpm_max"], 200.0)

    def test_edit_charts_match_scores_by_description(self):
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores>"
                "<Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Edit' Description='Alpha Edit'>"
                "<HighScoreList>"
                "<NumTimesPlayed>7</NumTimesPlayed><LastPlayed>2026-02-01</LastPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>950000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            scores = data.stats_index(stats_file)

            cache_file = Path(directory) / "edits.cache"
            cache_file.write_text(
                "#TITLE:Song;\n"
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Edit;\n"
                "#DESCRIPTION:Alpha Edit;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Edit;\n"
                "#DESCRIPTION:Beta Edit;\n",
                encoding="utf-8",
            )
            rows, _ = data.parse_cache_file(cache_file, scores)

        self.assertEqual(len(rows), 2)
        alpha_row = next(r for r in rows if r["Chart"] == "Alpha Edit")
        beta_row = next(r for r in rows if r["Chart"] == "Beta Edit")

        self.assertEqual(alpha_row["Score"], 950000)
        self.assertEqual(alpha_row["Best %"], 95.0)
        self.assertEqual(alpha_row["Plays"], 7)

        self.assertEqual(beta_row["Score"], "")
        self.assertEqual(beta_row["Best %"], "")
        self.assertEqual(beta_row["Plays"], 0)

    def test_edit_charts_with_the_same_description_share_a_score(self):
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores>"
                "<Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Edit' Description='Alpha Edit'>"
                "<HighScoreList><NumTimesPlayed>7</NumTimesPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>950000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            cache_file = Path(directory) / "edits.cache"
            cache_file.write_text(
                "#TITLE:Song;\n"
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Edit;\n"
                "#DESCRIPTION:Alpha Edit;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Edit;\n"
                "#DESCRIPTION:Alpha Edit;\n",
                encoding="utf-8",
            )
            rows, _ = data.parse_cache_file(cache_file, data.stats_index(stats_file))

        self.assertEqual([row["Score"] for row in rows], [950000, 950000])
        self.assertEqual([row["Plays"] for row in rows], [7, 7])

    def test_edit_charts_match_with_whitespace_and_case_differences(self):
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores>"
                "<Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Edit' Description='  MY EDIT  '>"
                "<HighScoreList><NumTimesPlayed>3</NumTimesPlayed>"
                "<HighScore><PercentDP>0.98</PercentDP><Score>980000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            scores = data.stats_index(stats_file)

            cache_file = Path(directory) / "edits.cache"
            cache_file.write_text(
                "#TITLE:Song;\n"
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Edit;\n"
                "#CHARTNAME:my edit;\n",
                encoding="utf-8",
            )
            rows, _ = data.parse_cache_file(cache_file, scores)

        self.assertEqual(rows[0]["Score"], 980000)

    def test_edit_charts_prefer_description_over_chart_name_for_scores(self):
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores>"
                "<Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Edit' Description='Alpha Edit'>"
                "<HighScoreList><NumTimesPlayed>7</NumTimesPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>950000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            cache_file = Path(directory) / "edits.cache"
            cache_file.write_text(
                "#TITLE:Song;\n"
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Edit;\n"
                "#CHARTNAME:Pretty Name;\n"
                "#DESCRIPTION:Alpha Edit;\n",
                encoding="utf-8",
            )
            rows, _ = data.parse_cache_file(cache_file, data.stats_index(stats_file))

        self.assertEqual(rows[0]["Chart"], "Pretty Name")
        self.assertEqual(rows[0]["Score"], 950000)

    def test_edit_charts_fall_back_to_shared_score_when_description_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            # Stats.xml has no Description attribute on Edit steps
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores>"
                "<Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Edit'>"
                "<HighScoreList><NumTimesPlayed>5</NumTimesPlayed>"
                "<HighScore><PercentDP>0.92</PercentDP><Score>920000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            scores = data.stats_index(stats_file)

            cache_file = Path(directory) / "edits.cache"
            cache_file.write_text(
                "#TITLE:Song;\n"
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Edit;\n"
                "#CHARTNAME:Custom Chart;\n",
                encoding="utf-8",
            )
            rows, _ = data.parse_cache_file(cache_file, scores)

        self.assertEqual(rows[0]["Score"], 920000)

    def test_edit_chart_without_description_uses_described_stats_score(self):
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores>"
                "<Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Edit' Description='Alpha Edit'>"
                "<HighScoreList><NumTimesPlayed>7</NumTimesPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>950000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            cache_file = Path(directory) / "edits.cache"
            cache_file.write_text(
                "#TITLE:Song;\n"
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Edit;\n",
                encoding="utf-8",
            )
            rows, _ = data.parse_cache_file(cache_file, data.stats_index(stats_file))

        self.assertEqual(rows[0]["Score"], 950000)
        self.assertEqual(rows[0]["Plays"], 7)

    def test_edit_chart_without_description_merges_described_stats_scores(self):
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores>"
                "<Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Edit' Description='Alpha Edit'>"
                "<HighScoreList><NumTimesPlayed>9</NumTimesPlayed><LastPlayed>2026-01-01</LastPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>950000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "<Steps StepsType='dance-single' Difficulty='Edit' Description='Beta Edit'>"
                "<HighScoreList><NumTimesPlayed>7</NumTimesPlayed><LastPlayed>2026-02-01</LastPlayed>"
                "<HighScore><PercentDP>0.99</PercentDP><Score>990000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            cache_file = Path(directory) / "edits.cache"
            cache_file.write_text(
                "#TITLE:Song;\n"
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Edit;\n",
                encoding="utf-8",
            )
            rows, _ = data.parse_cache_file(cache_file, data.stats_index(stats_file))

        # With no description on the cache side the viewer cannot tell the two
        # Edits apart, so it keeps the pre-isolation merged result: best score,
        # highest play count and latest last-played date across both entries.
        self.assertEqual(rows[0]["Score"], 990000)
        self.assertEqual(rows[0]["Plays"], 9)
        self.assertEqual(rows[0]["Last played"], "2026-02-01")

    def test_stats_index_reads_score_and_ignores_case_in_matching_key(self):
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores><Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Hard'><HighScoreList><NumTimesPlayed>2</NumTimesPlayed>"
                "<HighScore><PercentDP>0.97</PercentDP><Score>123</Score></HighScore>"
                "</HighScoreList></Steps></Song></SongScores></Stats>",
                encoding="utf-8",
            )
            scores = data.stats_index(stats_file)

        self.assertEqual(scores[("pack/song", "dance-single", "hard")]["Score"], "123")
        self.assertEqual(scores[("pack/song", "dance-single", "hard")]["plays"], "2")

    def test_stats_index_keeps_best_score_across_duplicate_normalized_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores>"
                "<Song Dir='/home/player/ITGmania/Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Hard'>"
                "<HighScoreList><NumTimesPlayed>8</NumTimesPlayed><LastPlayed>2026-01-01</LastPlayed>"
                "<HighScore><PercentDP>0.99</PercentDP><Score>999</Score></HighScore>"
                "</HighScoreList></Steps></Song>"
                "<Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Hard'>"
                "<HighScoreList><NumTimesPlayed>5</NumTimesPlayed><LastPlayed>2026-02-01</LastPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>950</Score></HighScore>"
                "</HighScoreList></Steps></Song>"
                "</SongScores></Stats>",
                encoding="utf-8",
            )
            scores = data.stats_index(stats_file)

        entry = scores[("pack/song", "dance-single", "hard")]
        self.assertEqual(entry["Score"], "999")
        self.assertEqual(entry["PercentDP"], "0.99")
        # The duplicate entries disagree on plays and last-played, so the merged
        # entry must keep the highest play count and the latest date.
        self.assertEqual(entry["plays"], "8")
        self.assertEqual(entry["last_played"], "2026-02-01")

    def test_stats_index_accepts_profile_with_no_song_scores(self):
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text("<Stats />", encoding="utf-8")
            self.assertEqual(data.stats_index(stats_file), {})


class MediaParsingTests(unittest.TestCase):
    # Proposal 0011, stage 1: the seven media tags land as hidden row keys.
    # Issue #193 adds an eighth: SongMusic, the song's own #MUSIC, carried
    # on every chart row so the media record need not infer it.
    MEDIA_KEYS = ("Music", "SongMusic", "Banner", "Background", "Jacket",
                  "CDTitle", "SampleStart", "SampleLength")

    @staticmethod
    def _write_cache(directory, song_tags, charts):
        cache_file = Path(directory) / "song.cache"
        cache_file.write_text(song_tags + "".join(charts), encoding="utf-8")
        return cache_file

    def test_media_tags_land_as_hidden_row_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = self._write_cache(
                directory,
                "#TITLE:Example;\n"
                "#SONGFILENAME:Songs/Pack/Song/song.sm;\n"
                "#MUSIC:song.ogg;\n"
                "#BANNER:banner.png;\n"
                "#BACKGROUND:bg.jpg;\n"
                "#JACKET:jacket.png;\n"
                "#CDTITLE:cdtitle.png;\n"
                "#SAMPLESTART:64.58;\n"
                "#SAMPLELENGTH:15;\n"
                "#MUSICLENGTH:93.9;\n",
                ["#NOTEDATA:;\n"
                 "#STEPSTYPE:dance-single;\n"
                 "#DIFFICULTY:Hard;\n"
                 "#METER:10;\n"],
            )
            rows, _ = data.parse_cache_file(cache_file, {})

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["Music"], "song.ogg")
        self.assertEqual(row["SongMusic"], "song.ogg")
        self.assertEqual(row["Banner"], "banner.png")
        self.assertEqual(row["Background"], "bg.jpg")
        self.assertEqual(row["Jacket"], "jacket.png")
        self.assertEqual(row["CDTitle"], "cdtitle.png")
        self.assertEqual(row["SampleStart"], 64.58)
        self.assertEqual(row["SampleLength"], 15.0)
        for key in self.MEDIA_KEYS:
            self.assertNotIn(key, HEADERS)

    def test_cache_without_media_tags_yields_empty_media_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = self._write_cache(
                directory,
                "#TITLE:Plain;\n"
                "#SONGFILENAME:Songs/Pack/Song/song.sm;\n"
                "#MUSICLENGTH:60;\n",
                ["#NOTEDATA:;\n"
                 "#STEPSTYPE:dance-single;\n"
                 "#DIFFICULTY:Hard;\n"
                 "#METER:10;\n"],
            )
            rows, _ = data.parse_cache_file(cache_file, {})

        self.assertEqual(len(rows), 1)
        for key in self.MEDIA_KEYS:
            self.assertEqual(rows[0][key], "")

    def test_chart_level_music_override_wins_over_the_song_music(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = self._write_cache(
                directory,
                "#TITLE:Example;\n"
                "#SONGFILENAME:Songs/Pack/Song/song.sm;\n"
                "#MUSIC:song.ogg;\n",
                ["#NOTEDATA:;\n"
                 "#STEPSTYPE:dance-single;\n"
                 "#DIFFICULTY:Hard;\n"
                 "#METER:10;\n"
                 "#MUSIC:chart.ogg;\n",
                 "#NOTEDATA:;\n"
                 "#STEPSTYPE:dance-single;\n"
                 "#DIFFICULTY:Challenge;\n"
                 "#METER:12;\n"],
            )
            rows, _ = data.parse_cache_file(cache_file, {})

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Music"], "chart.ogg")
        self.assertEqual(rows[1]["Music"], "song.ogg")
        # Both rows carry the song's own #MUSIC (issue #193), even the
        # chart that overrides it.
        self.assertEqual(rows[0]["SongMusic"], "song.ogg")
        self.assertEqual(rows[1]["SongMusic"], "song.ogg")

    def test_chart_level_tags_other_than_music_do_not_override(self):
        # Only #MUSIC has a chart-level override (NotesLoaderSSC.cpp
        # :678-711); a chart carrying the other six tags still takes the
        # song's values.
        with tempfile.TemporaryDirectory() as directory:
            cache_file = self._write_cache(
                directory,
                "#TITLE:Example;\n"
                "#SONGFILENAME:Songs/Pack/Song/song.sm;\n"
                "#BANNER:song-banner.png;\n"
                "#BACKGROUND:song-bg.png;\n"
                "#JACKET:song-jacket.png;\n"
                "#CDTITLE:song-cd.png;\n"
                "#SAMPLESTART:10;\n"
                "#SAMPLELENGTH:12;\n",
                ["#NOTEDATA:;\n"
                 "#STEPSTYPE:dance-single;\n"
                 "#DIFFICULTY:Hard;\n"
                 "#METER:10;\n"
                 "#BANNER:chart-banner.png;\n"
                 "#BACKGROUND:chart-bg.png;\n"
                 "#JACKET:chart-jacket.png;\n"
                 "#CDTITLE:chart-cd.png;\n"
                 "#SAMPLESTART:99;\n"
                 "#SAMPLELENGTH:99;\n"],
            )
            rows, _ = data.parse_cache_file(cache_file, {})

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["Banner"], "song-banner.png")
        self.assertEqual(row["Background"], "song-bg.png")
        self.assertEqual(row["Jacket"], "song-jacket.png")
        self.assertEqual(row["CDTitle"], "song-cd.png")
        self.assertEqual(row["SampleStart"], 10.0)
        self.assertEqual(row["SampleLength"], 12.0)

    def test_image_extension_counts_count_each_song_once(self):
        rows = [
            {"Course path": "Pack/A", "Banner": "a.png",
             "Background": "a.jpg", "Jacket": ""},
            {"Course path": "Pack/A", "Banner": "a.png",
             "Background": "a.jpg", "Jacket": ""},
            {"Course path": "Pack/B", "Banner": "b.JPG",
             "Background": "", "Jacket": "b.gif"},
            {"Course path": "Pack/C", "Banner": "",
             "Background": "c.bmp", "Jacket": 12},
        ]
        counts = data.image_extension_counts(rows)

        self.assertEqual(counts["Banner"], {".png": 1, ".jpg": 1, "": 1})
        self.assertEqual(counts["Background"],
                         {".jpg": 1, "": 1, ".bmp": 1})
        self.assertEqual(counts["Jacket"], {"": 2, ".gif": 1})


class MergeScoresTests(unittest.TestCase):
    def _write_cache(self, directory):
        cache_file = Path(directory) / "song.cache"
        cache_file.write_text(
            "#TITLE:Song;\n"
            "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
            "#NOTEDATA:;\n"
            "#STEPSTYPE:dance-single;\n"
            "#DIFFICULTY:Hard;\n"
            "#METER:10;\n"
            "#NOTEDATA:;\n"
            "#STEPSTYPE:dance-single;\n"
            "#DIFFICULTY:Challenge;\n"
            "#METER:13;\n"
            "#NOTEDATA:;\n"
            "#STEPSTYPE:dance-single;\n"
            "#DIFFICULTY:Edit;\n"
            "#DESCRIPTION:Alpha Edit;\n",
            encoding="utf-8",
        )
        return cache_file

    def test_merge_scores_matches_a_direct_reparse_with_fresh_scores(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = self._write_cache(directory)
            stats_a = Path(directory) / "StatsA.xml"
            stats_a.write_text(
                "<Stats><SongScores><Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Hard'>"
                "<HighScoreList><NumTimesPlayed>7</NumTimesPlayed><LastPlayed>2026-02-01</LastPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>900000</Score><Grade>Tier01</Grade><MaxCombo>100</MaxCombo></HighScore>"
                "</HighScoreList></Steps>"
                "<Steps StepsType='dance-single' Difficulty='Edit' Description='Alpha Edit'>"
                "<HighScoreList><NumTimesPlayed>3</NumTimesPlayed><LastPlayed>2026-01-15</LastPlayed>"
                "<HighScore><PercentDP>0.90</PercentDP><Score>950000</Score><Grade>Tier02</Grade></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            stats_b = Path(directory) / "StatsB.xml"
            stats_b.write_text(
                "<Stats><SongScores><Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Hard'>"
                "<HighScoreList><NumTimesPlayed>8</NumTimesPlayed><LastPlayed>2026-02-02</LastPlayed>"
                "<HighScore><PercentDP>0.975</PercentDP><Score>975000</Score><Grade>Tier02</Grade><MaxCombo>150</MaxCombo></HighScore>"
                "</HighScoreList></Steps>"
                "<Steps StepsType='dance-single' Difficulty='Challenge'>"
                "<HighScoreList><NumTimesPlayed>1</NumTimesPlayed><LastPlayed>2026-02-02</LastPlayed>"
                "<HighScore><PercentDP>0.80</PercentDP><Score>800000</Score><Grade>Tier05</Grade></HighScore>"
                "</HighScoreList></Steps>"
                "<Steps StepsType='dance-single' Difficulty='Edit' Description='Alpha Edit'>"
                "<HighScoreList><NumTimesPlayed>3</NumTimesPlayed><LastPlayed>2026-01-15</LastPlayed>"
                "<HighScore><PercentDP>0.90</PercentDP><Score>950000</Score><Grade>Tier02</Grade></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            rows_a, _ = data.parse_cache_file(cache_file, data.stats_index(stats_a))
            rows_b, _ = data.parse_cache_file(cache_file, data.stats_index(stats_b))
            changed = data.merge_scores(rows_a, data.stats_index(stats_b))

        # The merge must be exactly a re-parse with the fresh scores: the
        # Hard score bumped, the Challenge gained its first score, and the
        # Edit is untouched. Every field, not just the score fields.
        self.assertEqual(rows_a, rows_b)
        self.assertEqual(changed, 2)

    def test_merge_scores_with_unchanged_scores_reports_no_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = self._write_cache(directory)
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores><Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Hard'>"
                "<HighScoreList><NumTimesPlayed>7</NumTimesPlayed><LastPlayed>2026-02-01</LastPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>900000</Score><Grade>Tier01</Grade></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            scores = data.stats_index(stats_file)
            rows, _ = data.parse_cache_file(cache_file, scores)
            before = [dict(row) for row in rows]
            changed = data.merge_scores(rows, scores)

        self.assertEqual(changed, 0)
        self.assertEqual(rows, before)

    def test_merge_scores_for_a_both_tags_edit_uses_the_described_score(self):
        # An Edit chart carrying both #DESCRIPTION and #CHARTNAME with
        # different values: the parse keys its score on the description,
        # and the row now carries that description, so the merge looks up
        # the same entry instead of falling back to the shared-key score.
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores><Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Edit' Description='Real Desc'>"
                "<HighScoreList><NumTimesPlayed>5</NumTimesPlayed>"
                "<LastPlayed>2026-02-01</LastPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>950000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "<Steps StepsType='dance-single' Difficulty='Edit'>"
                "<HighScoreList><NumTimesPlayed>1</NumTimesPlayed>"
                "<LastPlayed>2026-01-01</LastPlayed>"
                "<HighScore><PercentDP>0.50</PercentDP><Score>500000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            cache_file = Path(directory) / "both.cache"
            cache_file.write_text(
                "#TITLE:Song;\n"
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Edit;\n"
                "#DESCRIPTION:Real Desc;\n"
                "#CHARTNAME:Other Name;\n",
                encoding="utf-8",
            )
            scores = data.stats_index(stats_file)
            rows, _ = data.parse_cache_file(cache_file, scores)

        # The parse keys on the description, so the row starts with the
        # described score -- and its Chart field carries the chart name.
        self.assertEqual(rows[0]["Chart"], "Other Name")
        self.assertEqual(rows[0]["Score"], 950000)
        self.assertEqual(rows[0]["Score description"], "Real Desc")
        changed = data.merge_scores(rows, scores)

        # The merge reads the carried description and keeps the described
        # score, even though an undescribed sibling entry exists.
        self.assertEqual(changed, 0)
        self.assertEqual(rows[0]["Score"], 950000)
        self.assertEqual(rows[0]["Plays"], 5)

    def test_merge_scores_blanks_fields_when_the_score_is_gone(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = self._write_cache(directory)
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores><Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Hard'>"
                "<HighScoreList><NumTimesPlayed>7</NumTimesPlayed><LastPlayed>2026-02-01</LastPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>900000</Score><Grade>Tier01</Grade></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            rows, _ = data.parse_cache_file(cache_file, data.stats_index(stats_file))
            changed = data.merge_scores(rows, {})

        hard_row = next(r for r in rows if r["Difficulty"] == "Hard")
        self.assertEqual(changed, 1)
        self.assertEqual(hard_row["Score"], "")
        self.assertEqual(hard_row["Best %"], "")
        self.assertEqual(hard_row["Grade"], "")
        self.assertEqual(hard_row["Plays"], 0)
        self.assertEqual(hard_row["Last played"], "")

    def test_merge_scores_replay_without_improving_counts_the_chart(self):
        # Replaying a song without beating the best changes only Plays and
        # Last played, so the "N charts updated" count must include them:
        # otherwise the sync reports "already up to date" for a real change.
        with tempfile.TemporaryDirectory() as directory:
            cache_file = self._write_cache(directory)
            stats_a = Path(directory) / "StatsA.xml"
            stats_a.write_text(
                "<Stats><SongScores><Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Hard'>"
                "<HighScoreList><NumTimesPlayed>7</NumTimesPlayed><LastPlayed>2026-02-01</LastPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>900000</Score><Grade>Tier01</Grade><MaxCombo>100</MaxCombo></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            stats_b = Path(directory) / "StatsB.xml"
            stats_b.write_text(
                "<Stats><SongScores><Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Hard'>"
                "<HighScoreList><NumTimesPlayed>8</NumTimesPlayed><LastPlayed>2026-02-02</LastPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>900000</Score><Grade>Tier01</Grade><MaxCombo>100</MaxCombo></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            rows, _ = data.parse_cache_file(cache_file, data.stats_index(stats_a))
            changed = data.merge_scores(rows, data.stats_index(stats_b))

        hard_row = next(r for r in rows if r["Difficulty"] == "Hard")
        self.assertEqual(changed, 1)
        self.assertEqual(hard_row["Score"], 900000)
        self.assertEqual(hard_row["Plays"], 8)
        self.assertEqual(hard_row["Last played"], "2026-02-02")

    def test_merge_scores_applies_tap_judgments_and_counts_them(self):
        # No merge fixture had TapNoteScores, so a change to the taps alone
        # (or Max combo) must still count as an update.
        with tempfile.TemporaryDirectory() as directory:
            cache_file = self._write_cache(directory)
            stats_a = Path(directory) / "StatsA.xml"
            stats_a.write_text(
                "<Stats><SongScores><Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Hard'>"
                "<HighScoreList><NumTimesPlayed>7</NumTimesPlayed><LastPlayed>2026-02-01</LastPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>900000</Score><Grade>Tier01</Grade><MaxCombo>100</MaxCombo>"
                "<TapNoteScores><W1>100</W1><W2>5</W2><W3>2</W3><W4>0</W4><W5>0</W5><Miss>1</Miss></TapNoteScores>"
                "</HighScore></HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            stats_b = Path(directory) / "StatsB.xml"
            stats_b.write_text(
                "<Stats><SongScores><Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Hard'>"
                "<HighScoreList><NumTimesPlayed>7</NumTimesPlayed><LastPlayed>2026-02-01</LastPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>900000</Score><Grade>Tier01</Grade><MaxCombo>120</MaxCombo>"
                "<TapNoteScores><W1>110</W1><W2>5</W2><W3>2</W3><W4>0</W4><W5>0</W5><Miss>0</Miss></TapNoteScores>"
                "</HighScore></HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            rows, _ = data.parse_cache_file(cache_file, data.stats_index(stats_a))
            changed = data.merge_scores(rows, data.stats_index(stats_b))

        hard_row = next(r for r in rows if r["Difficulty"] == "Hard")
        self.assertEqual(changed, 1)
        self.assertEqual(hard_row["W1"], 110)
        self.assertEqual(hard_row["Miss"], 0)
        self.assertEqual(hard_row["Max combo"], 120)

    def test_merge_scores_matches_a_mixed_case_type(self):
        # The row keeps the cache's STEPSTYPE spelling ("Dance-Single")
        # while the Stats.xml key is casefolded, so the merge must casefold
        # the Type when it re-derives the base key.
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "song.cache"
            cache_file.write_text(
                "#TITLE:Song;\n"
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:Dance-Single;\n"
                "#DIFFICULTY:Hard;\n"
                "#METER:10;\n",
                encoding="utf-8",
            )
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores><Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Hard'>"
                "<HighScoreList><NumTimesPlayed>7</NumTimesPlayed><LastPlayed>2026-02-01</LastPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>900000</Score><Grade>Tier01</Grade></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            scores = data.stats_index(stats_file)
            rows, _ = data.parse_cache_file(cache_file, scores)
            self.assertEqual(rows[0]["Type"], "Dance-Single")
            self.assertEqual(rows[0]["Score"], 900000)
            changed = data.merge_scores(rows, scores)

        self.assertEqual(changed, 0)
        self.assertEqual(rows[0]["Score"], 900000)

    def test_merge_scores_for_a_both_tags_edit_with_only_its_own_entry_keeps_the_score(self):
        # The both-tags edge, fixed: the chart's own described entry is the
        # only one, and the row carries that description, so the merge keeps
        # the score instead of blanking it.
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores><Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Edit' Description='Real Desc'>"
                "<HighScoreList><NumTimesPlayed>5</NumTimesPlayed>"
                "<LastPlayed>2026-02-01</LastPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>950000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            cache_file = Path(directory) / "both.cache"
            cache_file.write_text(
                "#TITLE:Song;\n"
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Edit;\n"
                "#DESCRIPTION:Real Desc;\n"
                "#CHARTNAME:Other Name;\n",
                encoding="utf-8",
            )
            scores = data.stats_index(stats_file)
            rows, _ = data.parse_cache_file(cache_file, scores)
            self.assertEqual(rows[0]["Score"], 950000)
            changed = data.merge_scores(rows, scores)

        self.assertEqual(changed, 0)
        self.assertEqual(rows[0]["Score"], 950000)
        self.assertEqual(rows[0]["Plays"], 5)

    def test_merge_scores_for_a_both_tags_edit_ignores_a_sibling_edit_score(self):
        # The both-tags edge, fixed: a sibling Edit's description equals
        # this chart's CHARTNAME, but the row carries this chart's own
        # description, so the merge keeps its own score.
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores><Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Edit' Description='Real Desc'>"
                "<HighScoreList><NumTimesPlayed>5</NumTimesPlayed>"
                "<LastPlayed>2026-02-01</LastPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>950000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "<Steps StepsType='dance-single' Difficulty='Edit' Description='Other Name'>"
                "<HighScoreList><NumTimesPlayed>8</NumTimesPlayed>"
                "<LastPlayed>2026-02-03</LastPlayed>"
                "<HighScore><PercentDP>0.90</PercentDP><Score>900000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            cache_file = Path(directory) / "both.cache"
            cache_file.write_text(
                "#TITLE:Song;\n"
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Edit;\n"
                "#DESCRIPTION:Real Desc;\n"
                "#CHARTNAME:Other Name;\n",
                encoding="utf-8",
            )
            scores = data.stats_index(stats_file)
            rows, _ = data.parse_cache_file(cache_file, scores)
            self.assertEqual(rows[0]["Score"], 950000)
            changed = data.merge_scores(rows, scores)

        self.assertEqual(changed, 0)
        self.assertEqual(rows[0]["Score"], 950000)
        self.assertEqual(rows[0]["Plays"], 5)

    def test_merge_scores_for_a_row_without_a_score_description_falls_back_to_the_chart_field(self):
        # A row that somehow lacks the carried description falls back to
        # the Chart field (defensive: the schema bump to 4 discards
        # snapshots written before the field existed).
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores><Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Edit' Description='Real Desc'>"
                "<HighScoreList><NumTimesPlayed>5</NumTimesPlayed>"
                "<LastPlayed>2026-02-01</LastPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>950000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "<Steps StepsType='dance-single' Difficulty='Edit'>"
                "<HighScoreList><NumTimesPlayed>1</NumTimesPlayed>"
                "<LastPlayed>2026-01-01</LastPlayed>"
                "<HighScore><PercentDP>0.50</PercentDP><Score>500000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            cache_file = Path(directory) / "both.cache"
            cache_file.write_text(
                "#TITLE:Song;\n"
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Edit;\n"
                "#DESCRIPTION:Real Desc;\n"
                "#CHARTNAME:Other Name;\n",
                encoding="utf-8",
            )
            scores = data.stats_index(stats_file)
            rows, _ = data.parse_cache_file(cache_file, scores)
            # Simulate a row without the field: drop the carried description.
            del rows[0]["Score description"]
            self.assertEqual(rows[0]["Score"], 950000)
            changed = data.merge_scores(rows, scores)

        # Without the field the merge keys on the Chart field and falls
        # back to the shared-key score, as in v1.
        self.assertEqual(changed, 1)
        self.assertEqual(rows[0]["Score"], 500000)

    def test_merge_scores_with_a_non_string_score_description_falls_back_to_the_chart_field(self):
        # A hand-edited snapshot can carry a non-string "Score description"
        # (the snapshot read only checks key presence). The merge must
        # treat it as absent and fall back to the Chart field, instead of
        # failing the whole sync on one bad row.
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores><Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Edit' Description='Real Desc'>"
                "<HighScoreList><NumTimesPlayed>5</NumTimesPlayed>"
                "<LastPlayed>2026-02-01</LastPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>950000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "<Steps StepsType='dance-single' Difficulty='Edit'>"
                "<HighScoreList><NumTimesPlayed>1</NumTimesPlayed>"
                "<LastPlayed>2026-01-01</LastPlayed>"
                "<HighScore><PercentDP>0.50</PercentDP><Score>500000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            cache_file = Path(directory) / "both.cache"
            cache_file.write_text(
                "#TITLE:Song;\n"
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Edit;\n"
                "#DESCRIPTION:Real Desc;\n"
                "#CHARTNAME:Other Name;\n",
                encoding="utf-8",
            )
            scores = data.stats_index(stats_file)
            rows, _ = data.parse_cache_file(cache_file, scores)
            # Simulate a hand-edited snapshot row: a non-string value.
            rows[0]["Score description"] = 5
            self.assertEqual(rows[0]["Score"], 950000)
            changed = data.merge_scores(rows, scores)

        # The bad field is treated as absent, so the merge keys on the
        # Chart field and falls back to the shared-key score, as in v1.
        self.assertEqual(changed, 1)
        self.assertEqual(rows[0]["Score"], 500000)

    def test_merge_scores_with_a_non_string_score_description_selects_the_chart_keyed_score(self):
        # The fallback keys on the Chart field, so when a Stats.xml entry
        # is described by that Chart value, its score wins — not the
        # shared-key score. This pins the Chart-keyed behaviour the
        # fallback test above does not (it has no Chart-keyed entry).
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores><Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Edit' Description='Real Desc'>"
                "<HighScoreList><NumTimesPlayed>5</NumTimesPlayed>"
                "<LastPlayed>2026-02-01</LastPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>950000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "<Steps StepsType='dance-single' Difficulty='Edit' Description='Other Name'>"
                "<HighScoreList><NumTimesPlayed>3</NumTimesPlayed>"
                "<LastPlayed>2026-02-02</LastPlayed>"
                "<HighScore><PercentDP>0.70</PercentDP><Score>700000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "<Steps StepsType='dance-single' Difficulty='Edit'>"
                "<HighScoreList><NumTimesPlayed>1</NumTimesPlayed>"
                "<LastPlayed>2026-01-01</LastPlayed>"
                "<HighScore><PercentDP>0.50</PercentDP><Score>500000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            cache_file = Path(directory) / "both.cache"
            cache_file.write_text(
                "#TITLE:Song;\n"
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Edit;\n"
                "#DESCRIPTION:Real Desc;\n"
                "#CHARTNAME:Other Name;\n",
                encoding="utf-8",
            )
            scores = data.stats_index(stats_file)
            rows, _ = data.parse_cache_file(cache_file, scores)
            # Simulate a hand-edited snapshot row: a non-string value.
            rows[0]["Score description"] = 5
            self.assertEqual(rows[0]["Score"], 950000)
            changed = data.merge_scores(rows, scores)

        # The bad field is treated as absent, so the merge keys on the
        # Chart field ("Other Name") and selects that entry's score.
        self.assertEqual(changed, 1)
        self.assertEqual(rows[0]["Score"], 700000)

    def test_any_scores_match_true_when_a_row_finds_a_score(self):
        # The Stats.xml holds a real score for a song in the library.
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores><Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Hard'>"
                "<HighScoreList><NumTimesPlayed>7</NumTimesPlayed>"
                "<LastPlayed>2026-02-01</LastPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>900000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            cache_file = Path(directory) / "song.cache"
            cache_file.write_text(
                "#TITLE:Song;\n"
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Hard;\n"
                "#METER:10;\n",
                encoding="utf-8",
            )
            scores = data.stats_index(stats_file)
            rows, _ = data.parse_cache_file(cache_file, scores)
            self.assertTrue(data.any_scores_match(rows, scores))

    def test_any_scores_match_false_when_scores_belong_to_another_install(self):
        # The Stats.xml holds a real score, but for a song that is not
        # in the library: no row finds it.
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores><Song Dir='Songs/OtherPack/OtherSong'>"
                "<Steps StepsType='dance-single' Difficulty='Challenge'>"
                "<HighScoreList><NumTimesPlayed>5</NumTimesPlayed>"
                "<LastPlayed>2026-02-01</LastPlayed>"
                "<HighScore><PercentDP>0.95</PercentDP><Score>950000</Score></HighScore>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            cache_file = Path(directory) / "song.cache"
            cache_file.write_text(
                "#TITLE:Song;\n"
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Hard;\n"
                "#METER:10;\n",
                encoding="utf-8",
            )
            scores = data.stats_index(stats_file)
            rows, _ = data.parse_cache_file(cache_file, {})
            self.assertFalse(data.any_scores_match(rows, scores))

    def test_any_scores_match_false_when_the_only_entry_has_no_score(self):
        # A row whose only Stats.xml entry is an empty HighScoreList
        # (plays/last_played, no PercentDP) does not count as matching.
        with tempfile.TemporaryDirectory() as directory:
            stats_file = Path(directory) / "Stats.xml"
            stats_file.write_text(
                "<Stats><SongScores><Song Dir='Songs/Pack/Song'>"
                "<Steps StepsType='dance-single' Difficulty='Hard'>"
                "<HighScoreList><NumTimesPlayed>0</NumTimesPlayed>"
                "<LastPlayed>2026-01-01</LastPlayed>"
                "</HighScoreList></Steps>"
                "</Song></SongScores></Stats>",
                encoding="utf-8",
            )
            cache_file = Path(directory) / "song.cache"
            cache_file.write_text(
                "#TITLE:Song;\n"
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Hard;\n"
                "#METER:10;\n",
                encoding="utf-8",
            )
            scores = data.stats_index(stats_file)
            rows, _ = data.parse_cache_file(cache_file, {})
            self.assertFalse(data.any_scores_match(rows, scores))


class BpmTests(unittest.TestCase):
    def test_cache_exposes_bpm_range(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "song.cache"
            cache_file.write_text(
                "#TITLE:Example;\n"
                "#SONGFILENAME:Songs/Pack/Song/audio.ogg;\n"
                "#BPMS:0.000=100.000,32.000=300.000;\n"
                "#DISPLAYBPM:100:300;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Hard;\n"
                "#METER:10;\n",
                encoding="utf-8",
            )
            row = data.parse_cache_file(cache_file, {})[0][0]
        self.assertEqual(row["BPM"], "100–300")
        self.assertEqual(row["bpm_min"], 100.0)
        self.assertEqual(row["bpm_max"], 300.0)

    def test_split_timing_fixture_overrides_and_falls_back(self):
        fixture = Path(__file__).parent / "fixtures" / "split_timing.fixture"
        rows, _skipped = data.parse_cache_file(fixture, {})
        self.assertEqual(len(rows), 2)
        easy = next(r for r in rows if r["Difficulty"] == "Easy")
        hard = next(r for r in rows if r["Difficulty"] == "Hard")
        # Easy chart has no chart timing: falls back to song-level timing
        self.assertEqual(easy["bpm_min"], 140.0)
        self.assertEqual(easy["bpm_max"], 140.0)
        self.assertEqual(easy["BPM"], "140")
        # Hard chart has split timing: overrides with chart-level timing
        self.assertEqual(hard["bpm_min"], 180.0)
        self.assertEqual(hard["bpm_max"], 200.0)
        self.assertEqual(hard["BPM"], "180–200")

    def test_chart_timing_composition_pins(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "song.cache"
            # Pin 1: Chart warp-only + song normal => song bounds
            cache_file.write_text(
                "#TITLE:Test;\n"
                "#SONGFILENAME:Songs/P/S/a.ogg;\n"
                "#BPMS:0.000=140.000;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Easy;\n"
                "#BPMS:0.000=-150.000;\n",
                encoding="utf-8",
            )
            row = data.parse_cache_file(cache_file, {})[0][0]
            self.assertEqual(row["bpm_min"], 140.0)
            self.assertEqual(row["bpm_max"], 140.0)
            self.assertEqual(row["BPM"], "140")

            # Pin 2: Bounds None without #DISPLAYBPM => cell is blank
            cache_file.write_text(
                "#TITLE:Test;\n"
                "#SONGFILENAME:Songs/P/S/a.ogg;\n"
                "#BPMS:0.000=-140.000;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Easy;\n"
                "#BPMS:0.000=-150.000;\n",
                encoding="utf-8",
            )
            row = data.parse_cache_file(cache_file, {})[0][0]
            self.assertEqual(row["bpm_min"], "")
            self.assertEqual(row["bpm_max"], "")
            self.assertEqual(row["BPM"], "")

            # Pin 3: Bounds None with #DISPLAYBPM => cell shows display text
            cache_file.write_text(
                "#TITLE:Test;\n"
                "#SONGFILENAME:Songs/P/S/a.ogg;\n"
                "#BPMS:0.000=-140.000;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Easy;\n"
                "#BPMS:0.000=-150.000;\n"
                "#DISPLAYBPM:150;\n",
                encoding="utf-8",
            )
            row = data.parse_cache_file(cache_file, {})[0][0]
            self.assertEqual(row["bpm_min"], "")
            self.assertEqual(row["bpm_max"], "")
            self.assertEqual(row["BPM"], "150")

            # Pin 4: Bounds None with #DISPLAYBPM:* => cell shows *
            cache_file.write_text(
                "#TITLE:Test;\n"
                "#SONGFILENAME:Songs/P/S/a.ogg;\n"
                "#BPMS:0.000=-140.000;\n"
                "#DISPLAYBPM:*;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Easy;\n",
                encoding="utf-8",
            )
            row = data.parse_cache_file(cache_file, {})[0][0]
            self.assertEqual(row["bpm_min"], "")
            self.assertEqual(row["bpm_max"], "")
            self.assertEqual(row["BPM"], "*")

            # Pin 5: Chart normal + song warp-only => chart bounds override
            cache_file.write_text(
                "#TITLE:Test;\n"
                "#SONGFILENAME:Songs/P/S/a.ogg;\n"
                "#BPMS:0.000=-140.000;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Easy;\n"
                "#BPMS:0.000=180.000;\n",
                encoding="utf-8",
            )
            row = data.parse_cache_file(cache_file, {})[0][0]
            self.assertEqual(row["bpm_min"], 180.0)
            self.assertEqual(row["bpm_max"], 180.0)
            self.assertEqual(row["BPM"], "180")

            # Pin 6: Chart has its own #BPMS but no #DISPLAYBPM, song has
            # #DISPLAYBPM:140 => the cell shows the song's display text
            # while the bounds are the chart's own (per-tag independence).
            cache_file.write_text(
                "#TITLE:Test;\n"
                "#SONGFILENAME:Songs/P/S/a.ogg;\n"
                "#BPMS:0.000=140.000;\n"
                "#DISPLAYBPM:140;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Easy;\n"
                "#BPMS:0.000=180.000;\n",
                encoding="utf-8",
            )
            row = data.parse_cache_file(cache_file, {})[0][0]
            self.assertEqual(row["bpm_min"], 180.0)
            self.assertEqual(row["bpm_max"], 180.0)
            self.assertEqual(row["BPM"], "140")

            # Pin 7: Chart has #DISPLAYBPM only (90:95), song has
            # #BPMS:0=140 and no #DISPLAYBPM => the cell shows the
            # chart's display text while the bounds are the song's.
            cache_file.write_text(
                "#TITLE:Test;\n"
                "#SONGFILENAME:Songs/P/S/a.ogg;\n"
                "#BPMS:0.000=140.000;\n"
                "#NOTEDATA:;\n"
                "#STEPSTYPE:dance-single;\n"
                "#DIFFICULTY:Easy;\n"
                "#DISPLAYBPM:90:95;\n",
                encoding="utf-8",
            )
            row = data.parse_cache_file(cache_file, {})[0][0]
            self.assertEqual(row["bpm_min"], 140.0)
            self.assertEqual(row["bpm_max"], 140.0)
            # A lo:hi display range renders with an en dash, as elsewhere.
            self.assertEqual(row["BPM"], "90–95")


class CacheDirCandidatesTests(unittest.TestCase):
    """Issue #21: the cache guess is per-platform and existence-gated."""

    def test_first_existing_directory_returns_the_first_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "Cache" / "Songs"
            existing.mkdir(parents=True)
            missing = root / "Nope"
            self.assertEqual(data.first_existing_directory([missing, existing]), existing)
            self.assertIsNone(data.first_existing_directory([missing, root / "AlsoNope"]))

    def test_first_existing_directory_skips_a_candidate_that_is_a_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file_candidate = root / "Cache"
            file_candidate.write_text("not a directory", encoding="utf-8")
            real = root / "Real"
            real.mkdir()
            self.assertEqual(data.first_existing_directory([file_candidate, real]), real)

    def test_candidates_on_linux(self):
        with patch.object(sys, "platform", "linux"):
            self.assertEqual(data.cache_dir_candidates(),
                             [Path.home() / ".itgmania" / "Cache" / "Songs"])

    def test_candidates_on_macos(self):
        with patch.object(sys, "platform", "darwin"):
            self.assertEqual(data.cache_dir_candidates(),
                             [Path.home() / "Library" / "Application Support"
                              / "ITGmania" / "Cache" / "Songs"])

    def test_candidates_on_windows_use_appdata(self):
        with tempfile.TemporaryDirectory() as directory:
            appdata = Path(directory)
            with patch.object(sys, "platform", "win32"), patch.dict(os.environ, {"APPDATA": str(appdata)}):
                self.assertEqual(data.cache_dir_candidates(),
                                 [appdata / "ITGmania" / "Cache" / "Songs"])

    def test_candidates_on_windows_without_appdata_fall_back_to_home(self):
        env = {key: value for key, value in os.environ.items() if key != "APPDATA"}
        with patch.object(sys, "platform", "win32"), patch.dict(os.environ, env, clear=True):
            self.assertEqual(data.cache_dir_candidates(),
                             [Path.home() / "AppData" / "Roaming"
                              / "ITGmania" / "Cache" / "Songs"])


class NonFiniteFormatTests(unittest.TestCase):
    """Issues #123 and #137: a non-finite value reads as missing (blank),
    not a crash out of the format helpers."""

    def test_cache_with_non_finite_bpms_parses_with_a_blank_bpm_cell(self):
        # Issue #137: a song with #BPMS inf and no #DISPLAYBPM used to raise
        # OverflowError out of parse_cache_file (zero rows); now the row
        # parses and its BPM cell is blank. Same for a nan #DISPLAYBPM.
        cases = {
            "inf_bpms": "#BPMS:0.000=inf;\n",
            "nan_display": "#BPMS:0.000=120.000;\n#DISPLAYBPM:nan;\n",
        }
        for name, timing in cases.items():
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as directory:
                    cache_file = Path(directory) / "song.cache"
                    cache_file.write_text(
                        "#TITLE:Bad Song;\n"
                        "#ARTIST:Tempo Crew;\n"
                        "#SONGFILENAME:Songs/Pack/Bad Song/bad.ogg;\n"
                        "#MUSICLENGTH:100.000;\n"
                        + timing +
                        "#NOTEDATA:;\n"
                        "#STEPSTYPE:dance-single;\n"
                        "#DIFFICULTY:Easy;\n"
                        "#METER:5;\n"
                        "#RADARVALUES:0.100,0.100,0.050,0.010,0.020,100,105,10,5,0,1,0,5,0;\n",
                        encoding="utf-8",
                    )
                    rows, _skipped = data.parse_cache_file(cache_file, {})
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["BPM"], "")


class InvalidPathsNoteTests(unittest.TestCase):
    """The Data paths note naming whichever path cannot be used."""

    def test_both_usable_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "Cache" / "Songs"
            cache_dir.mkdir(parents=True)
            stats_file = root / "Stats.xml"
            stats_file.write_text("<Stats/>")
            self.assertEqual(data.invalid_paths_note(cache_dir, stats_file), "")

    def test_cache_only_names_the_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stats_file = root / "Stats.xml"
            stats_file.write_text("<Stats/>")
            note = data.invalid_paths_note(root / "Cache" / "Songs", stats_file)
            self.assertIn("cache folder", note)
            self.assertNotIn("Stats.xml", note)

    def test_stats_only_names_stats(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "Cache" / "Songs"
            cache_dir.mkdir(parents=True)
            note = data.invalid_paths_note(cache_dir, root / "Stats.xml")
            self.assertIn("Stats.xml", note)
            self.assertNotIn("cache folder", note)

    def test_both_missing_names_both(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = data.invalid_paths_note(root / "Cache" / "Songs", root / "Stats.xml")
            self.assertIn("cache folder", note)
            self.assertIn("Stats.xml", note)
