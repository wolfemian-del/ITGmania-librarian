"""Tests for the song-media helpers (Proposal 0011, stage 2)."""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from itgmania_library import library_media as media

SONG_DIR = "Pack/Song"


def _row(**overrides):
    row = {
        "Course path": SONG_DIR,
        "Type": "dance-single",
        "Difficulty": "Beginner",
        "Music": "song.ogg",
        "Banner": "banner.png",
        "Background": "bg.png",
        "Jacket": "jacket.png",
        "CDTitle": "cdtitle.png",
        "SampleStart": 64.58,
        "SampleLength": 15.0,
        "Time": 93.988,
    }
    row.update(overrides)
    return row


class SongRootsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.user_data = self.base / "userdata"
        self.cache_dir = self.user_data / "Cache" / "Songs"
        self.cache_dir.mkdir(parents=True)
        self.save_dir = self.user_data / "Save"
        self.save_dir.mkdir(parents=True)

    def _write_prefs(self, text, encoding="utf-8"):
        (self.save_dir / "Preferences.ini").write_text(text, encoding=encoding)

    def test_roots_from_preferences_ini(self):
        extra1 = self.base / "extra1"
        extra2 = self.base / "extra2"
        readonly = self.base / "readonly"
        folders1 = self.base / "folders1"
        folders2 = self.base / "folders2"
        self._write_prefs(
            "AdditionalSongFoldersWritable="
            f"{extra1},{extra2}\n"
            f"AdditionalSongFoldersReadOnly={readonly}\n"
            f"AdditionalFoldersWritable={folders1}\n"
            f"AdditionalFoldersReadOnly={folders2}\n"
        )
        # Within one list the later entries outrank the earlier ones.
        self.assertEqual(media.song_roots(self.cache_dir), [
            extra2, extra1, readonly,
            folders1 / "Songs", folders2 / "Songs",
            self.user_data / "Songs",
        ])

    def test_deprecated_song_folders_win_when_nonempty(self):
        deprecated = self.base / "deprecated"
        writable = self.base / "writable"
        self._write_prefs(
            f"AdditionalSongFolders={deprecated}\n"
            f"AdditionalSongFoldersWritable={writable}\n"
        )
        roots = media.song_roots(self.cache_dir)
        self.assertEqual(roots[0], deprecated)
        self.assertNotIn(writable, roots)

    def test_empty_deprecated_falls_back_to_writable(self):
        writable = self.base / "writable"
        self._write_prefs(
            "AdditionalSongFolders=\n"
            f"AdditionalSongFoldersWritable={writable}\n"
        )
        self.assertEqual(media.song_roots(self.cache_dir)[0], writable)

    def test_deprecated_additional_folders_win_when_nonempty(self):
        deprecated = self.base / "deprecated"
        writable = self.base / "writable"
        self._write_prefs(
            f"AdditionalFolders={deprecated}\n"
            f"AdditionalFoldersWritable={writable}\n"
        )
        roots = media.song_roots(self.cache_dir)
        self.assertEqual(roots[0], deprecated / "Songs")
        self.assertNotIn(writable / "Songs", roots)

    def test_missing_preferences_ini(self):
        self.assertEqual(media.song_roots(self.cache_dir),
                         [self.user_data / "Songs"])

    def test_non_utf8_preferences_ini(self):
        (self.save_dir / "Preferences.ini").write_bytes(b"\xff\xfe\x00bad")
        self.assertEqual(media.song_roots(self.cache_dir),
                         [self.user_data / "Songs"])

    def test_bom_preferences_ini(self):
        extra = self.base / "extra"
        self._write_prefs(
            f"AdditionalSongFoldersWritable={extra}\n",
            encoding="utf-8-sig",
        )
        self.assertEqual(media.song_roots(self.cache_dir),
                         [extra, self.user_data / "Songs"])

    def test_roots_dedupe(self):
        extra = self.base / "extra"
        self._write_prefs(
            f"AdditionalSongFoldersWritable={extra}\n"
            f"AdditionalSongFoldersReadOnly={extra}\n"
        )
        self.assertEqual(media.song_roots(self.cache_dir),
                         [extra, self.user_data / "Songs"])

    def test_none_cache_dir(self):
        self.assertEqual(media.song_roots(None), [])


class ResolveMediaFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root1 = self.base / "root1"
        self.root2 = self.base / "root2"
        self.song1 = self.root1 / SONG_DIR
        self.song2 = self.root2 / SONG_DIR
        self.song1.mkdir(parents=True)
        self.song2.mkdir(parents=True)
        self.roots = [self.root1, self.root2]

    def _write(self, folder, name):
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        return path

    def test_file_in_one_root(self):
        wanted = self._write(self.song2, "banner.png")
        self.assertEqual(
            media.resolve_media_file(SONG_DIR, "banner.png", self.roots,
                                     "image"),
            wanted)

    def test_first_root_wins(self):
        # song_roots already reverses each list, so the first root is
        # the winning mount.
        self._write(self.song2, "banner.png")
        wanted = self._write(self.song1, "banner.png")
        self.assertEqual(
            media.resolve_media_file(SONG_DIR, "banner.png", self.roots,
                                     "image"),
            wanted)

    def test_missing_file(self):
        self.assertIsNone(
            media.resolve_media_file(SONG_DIR, "banner.png", self.roots,
                                     "image"))

    def test_bare_filename(self):
        wanted = self._write(self.song1, "banner.png")
        self.assertEqual(
            media.resolve_media_file(SONG_DIR, "banner.png", self.roots,
                                     "image"),
            wanted)

    def test_subdirectory(self):
        wanted = self._write(self.song1, "images/banner.png")
        self.assertEqual(
            media.resolve_media_file(SONG_DIR, "images/banner.png",
                                     self.roots, "image"),
            wanted)

    def test_dotdot_inside_pack(self):
        wanted = self._write(self.root1 / "Pack", "sibling.png")
        self.assertEqual(
            media.resolve_media_file(SONG_DIR, "../sibling.png", self.roots,
                                     "image"),
            wanted)

    def test_absolute_value(self):
        self.assertIsNone(
            media.resolve_media_file(SONG_DIR, "/etc/banner.png", self.roots,
                                     "image"))

    def test_drive_letter_value(self):
        self.assertIsNone(
            media.resolve_media_file(SONG_DIR, "C:\\Games\\banner.png",
                                     self.roots, "image"))
        self.assertIsNone(
            media.resolve_media_file(SONG_DIR, "C:/Games/banner.png",
                                     self.roots, "image"))

    def test_vfs_top_relative_value(self):
        # The file exists under the song folder itself, so only the
        # prefix check makes this "not found": without it the value
        # would resolve as a subfolder of the song folder.
        self._write(self.song1 / "Songs" / SONG_DIR, "banner.png")
        self.assertIsNone(
            media.resolve_media_file(SONG_DIR, "Songs/Pack/Song/banner.png",
                                     self.roots, "image"))

    def test_escaping_dotdot(self):
        # The file exists outside the pack folder, but the form refuses
        # to leave it.
        self._write(self.root1, "escape.png")
        self.assertIsNone(
            media.resolve_media_file(SONG_DIR, "../../escape.png",
                                     self.roots, "image"))
        self.assertIsNone(
            media.resolve_media_file(SONG_DIR, "../../../etc/passwd",
                                     self.roots, "image"))

    def test_extension_outside_allowlist(self):
        self._write(self.song1, "banner.mp4")
        self._write(self.song1, "music.txt")
        self._write(self.song1, "music.ogg")
        self.assertIsNone(
            media.resolve_media_file(SONG_DIR, "banner.mp4", self.roots,
                                     "image"))
        self.assertIsNone(
            media.resolve_media_file(SONG_DIR, "music.txt", self.roots,
                                     "audio"))
        self.assertIsNone(
            media.resolve_media_file(SONG_DIR, "music.ogg", self.roots,
                                     "image"))
        self.assertIsNone(
            media.resolve_media_file(SONG_DIR, "banner.png", self.roots,
                                     "audio"))

    def test_uppercase_extension(self):
        wanted = self._write(self.song1, "BANNER.PNG")
        self.assertEqual(
            media.resolve_media_file(SONG_DIR, "BANNER.PNG", self.roots,
                                     "image"),
            wanted)

    def test_non_string_filename(self):
        self.assertIsNone(
            media.resolve_media_file(SONG_DIR, 12, self.roots, "image"))
        self.assertIsNone(
            media.resolve_media_file(SONG_DIR, None, self.roots, "image"))

    def test_empty_filename(self):
        self.assertIsNone(
            media.resolve_media_file(SONG_DIR, "", self.roots, "image"))

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            media.resolve_media_file(SONG_DIR, "banner.png", self.roots,
                                     "video")

    def test_filename_with_drive_letter_component(self):
        # A "C:" component anywhere in the value drops the root on
        # Windows, so it is refused even though the file exists.
        self._write(self.song1 / "sub" / "C:", "banner.png")
        self.assertIsNone(
            media.resolve_media_file(SONG_DIR, "sub/C:/banner.png",
                                     self.roots, "image"))

    def test_song_dir_with_drive_letter(self):
        self.assertIsNone(
            media.resolve_media_file("C:/Windows", "banner.png",
                                     self.roots, "image"))

    def test_empty_song_dir(self):
        self.assertIsNone(
            media.resolve_media_file("", "banner.png", self.roots, "image"))

    def test_song_dir_with_dotdot(self):
        self.assertIsNone(
            media.resolve_media_file("../Pack/Song", "banner.png",
                                     self.roots, "image"))


class ChartsForSongTests(unittest.TestCase):
    def test_filters_by_course_path(self):
        rows = [_row(), _row(**{"Course path": "Other/Song"}),
                _row(Difficulty="Challenge")]
        got = media.charts_for_song(rows, SONG_DIR)
        self.assertEqual([row["Difficulty"] for row in got],
                         ["Beginner", "Challenge"])

    def test_orders_by_type_then_difficulty(self):
        rows = [
            _row(Type="dance-single", Difficulty="Challenge"),
            _row(Type="dance-double", Difficulty="Hard"),
            _row(Type="dance-single", Difficulty="Beginner"),
            _row(Type="pump-single", Difficulty="Easy"),
        ]
        got = media.charts_for_song(rows, SONG_DIR)
        self.assertEqual(
            [(row["Type"], row["Difficulty"]) for row in got],
            [("dance-double", "Hard"), ("dance-single", "Beginner"),
             ("dance-single", "Challenge"), ("pump-single", "Easy")])

    def test_unknown_difficulty_sorts_last(self):
        rows = [_row(Difficulty="Impossible"), _row(Difficulty="Beginner")]
        got = media.charts_for_song(rows, SONG_DIR)
        self.assertEqual([row["Difficulty"] for row in got],
                         ["Beginner", "Impossible"])

    def test_no_charts_for_unknown_path(self):
        self.assertEqual(media.charts_for_song([_row()], "Other/Song"), [])


class BuildSongMediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root1 = self.base / "root1"
        self.root2 = self.base / "root2"
        self.song1 = self.root1 / SONG_DIR
        self.song2 = self.root2 / SONG_DIR
        self.song1.mkdir(parents=True)
        self.song2.mkdir(parents=True)
        self.roots = [self.root1, self.root2]

    def _write(self, folder, name):
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        return path

    def _write_full_set(self, folder):
        for name in ("banner.png", "bg.png", "jacket.png", "cdtitle.png",
                     "song.ogg"):
            self._write(folder, name)

    def test_full_record(self):
        self._write_full_set(self.song1)
        rows = [_row(), _row(Difficulty="Challenge")]
        record = media.build_song_media(SONG_DIR, self.roots, rows)
        self.assertEqual(record.banner, self.song1 / "banner.png")
        self.assertEqual(record.background, self.song1 / "bg.png")
        self.assertEqual(record.jacket, self.song1 / "jacket.png")
        self.assertEqual(record.cd_title, self.song1 / "cdtitle.png")
        self.assertEqual(record.music, self.song1 / "song.ogg")
        self.assertEqual(record.music_length, 93.988)
        self.assertEqual(record.sample_start, 64.58)
        self.assertEqual(record.sample_length, 15.0)
        self.assertEqual(record.folder, self.song1)

    def test_missing_files_and_folder(self):
        rows = [_row(**{"Course path": "Pack/Empty"})]
        record = media.build_song_media("Pack/Empty", self.roots, rows)
        self.assertIsNone(record.banner)
        self.assertIsNone(record.background)
        self.assertIsNone(record.jacket)
        self.assertIsNone(record.cd_title)
        self.assertIsNone(record.music)
        self.assertIsNone(record.folder)
        # The length and sample window are cache facts about the song's
        # music, so they survive even when the file is not on disk; only
        # a chart-level #MUSIC override suppresses them.
        self.assertEqual(record.music_length, 93.988)
        self.assertEqual(record.sample_start, 64.58)
        self.assertEqual(record.sample_length, 15.0)

    def test_song_under_no_root(self):
        self._write_full_set(self.song1)
        rows = [_row(), _row(Difficulty="Challenge")]
        record = media.build_song_media(SONG_DIR, [], rows)
        self.assertIsNone(record.banner)
        self.assertIsNone(record.background)
        self.assertIsNone(record.jacket)
        self.assertIsNone(record.cd_title)
        self.assertIsNone(record.music)
        self.assertIsNone(record.folder)
        # As in test_missing_files_and_folder: the length and sample
        # window are cache facts, not filesystem facts.
        self.assertEqual(record.music_length, 93.988)
        self.assertEqual(record.sample_start, 64.58)
        self.assertEqual(record.sample_length, 15.0)

    def test_split_pack(self):
        # Banner from one root, music from another: resolution is per
        # file, not per folder.
        self._write(self.song1, "banner.png")
        self._write(self.song2, "song.ogg")
        record = media.build_song_media(SONG_DIR, self.roots, [_row()])
        self.assertEqual(record.banner, self.song1 / "banner.png")
        self.assertEqual(record.music, self.song2 / "song.ogg")

    def test_opened_chart_with_own_music(self):
        self._write(self.song1, "alt.ogg")
        self._write_full_set(self.song1)
        rows = [_row(Music="alt.ogg"), _row(Difficulty="Challenge")]
        record = media.build_song_media(SONG_DIR, self.roots, rows)
        self.assertEqual(record.music, self.song1 / "alt.ogg")
        self.assertIsNone(record.music_length)
        self.assertIsNone(record.sample_start)
        self.assertIsNone(record.sample_length)
        # The other media still resolve from the opened row.
        self.assertEqual(record.banner, self.song1 / "banner.png")

    def test_opened_chart_is_song_music_other_chart_overrides(self):
        # The opened chart carries the song's music and another chart
        # overrides: the window is dropped, since the song's file
        # cannot be told apart from the override. Harmless — the
        # player seam defaults to the start of the song.
        self._write(self.song1, "alt.ogg")
        self._write_full_set(self.song1)
        rows = [_row(), _row(Difficulty="Challenge", Music="alt.ogg")]
        record = media.build_song_media(SONG_DIR, self.roots, rows)
        self.assertEqual(record.music, self.song1 / "song.ogg")
        self.assertIsNone(record.music_length)
        self.assertIsNone(record.sample_start)
        self.assertIsNone(record.sample_length)

    def test_opened_chart_is_song_music_two_others_override(self):
        self._write(self.song1, "alt.ogg")
        self._write_full_set(self.song1)
        rows = [_row(), _row(Difficulty="Challenge", Music="alt.ogg"),
                _row(Difficulty="Medium", Music="alt.ogg")]
        record = media.build_song_media(SONG_DIR, self.roots, rows)
        self.assertEqual(record.music, self.song1 / "song.ogg")
        self.assertIsNone(record.music_length)
        self.assertIsNone(record.sample_start)
        self.assertIsNone(record.sample_length)

    def test_opened_chart_override_two_others_differ(self):
        # Two different overrides in one song: the window is dropped
        # rather than applied to the wrong file.
        self._write(self.song1, "alt.ogg")
        self._write(self.song1, "other.ogg")
        self._write_full_set(self.song1)
        rows = [_row(Music="alt.ogg"), _row(Difficulty="Challenge"),
                _row(Difficulty="Medium", Music="other.ogg")]
        record = media.build_song_media(SONG_DIR, self.roots, rows)
        self.assertEqual(record.music, self.song1 / "alt.ogg")
        self.assertIsNone(record.music_length)
        self.assertIsNone(record.sample_start)
        self.assertIsNone(record.sample_length)

    def test_all_charts_same_override_keeps_window(self):
        # Every chart carries the same file, so the code cannot tell an
        # override shared by all charts from the song's own music: the
        # window is kept, and the limit is documented in build_song_media.
        self._write(self.song1, "alt.ogg")
        self._write_full_set(self.song1)
        rows = [_row(Music="alt.ogg"),
                _row(Difficulty="Challenge", Music="alt.ogg")]
        record = media.build_song_media(SONG_DIR, self.roots, rows)
        self.assertEqual(record.music, self.song1 / "alt.ogg")
        self.assertEqual(record.music_length, 93.988)
        self.assertEqual(record.sample_start, 64.58)

    def test_song_dir_with_drive_letter(self):
        self._write_full_set(self.song1)
        record = media.build_song_media("C:/Windows", self.roots, [_row()])
        self.assertIsNone(record.banner)
        self.assertIsNone(record.background)
        self.assertIsNone(record.jacket)
        self.assertIsNone(record.cd_title)
        self.assertIsNone(record.music)
        self.assertIsNone(record.folder)
        # The length and sample window are cache facts, so they survive
        # even when the song dir itself is unusable.
        self.assertEqual(record.music_length, 93.988)
        self.assertEqual(record.sample_start, 64.58)

    def test_single_chart_song(self):
        self._write_full_set(self.song1)
        record = media.build_song_media(SONG_DIR, self.roots, [_row()])
        self.assertEqual(record.music, self.song1 / "song.ogg")
        self.assertEqual(record.music_length, 93.988)
        self.assertEqual(record.sample_start, 64.58)

    def test_non_string_media_values(self):
        # F1 carry-over from the stage-1 review: a hand-edited snapshot
        # can hold any type, and none of them may fail the page open.
        self._write_full_set(self.song1)
        rows = [_row(Banner=12, Music=None, Jacket=["x"],
                     SampleStart="abc", SampleLength=float("nan"))]
        record = media.build_song_media(SONG_DIR, self.roots, rows)
        self.assertIsNone(record.banner)
        self.assertIsNone(record.music)
        self.assertIsNone(record.jacket)
        self.assertIsNone(record.sample_start)
        self.assertIsNone(record.sample_length)
        self.assertEqual(record.background, self.song1 / "bg.png")

    def test_non_finite_music_length(self):
        self._write_full_set(self.song1)
        record = media.build_song_media(
            SONG_DIR, self.roots, [_row(Time=float("inf"))])
        self.assertEqual(record.music, self.song1 / "song.ogg")
        self.assertIsNone(record.music_length)

    def test_numeric_string_sample_values(self):
        self._write_full_set(self.song1)
        record = media.build_song_media(
            SONG_DIR, self.roots, [_row(SampleStart="64.58")])
        self.assertEqual(record.sample_start, 64.58)

    def test_boolean_sample_value(self):
        self._write_full_set(self.song1)
        record = media.build_song_media(
            SONG_DIR, self.roots, [_row(SampleStart=True)])
        self.assertIsNone(record.sample_start)

    def test_empty_rows(self):
        self.assertEqual(media.build_song_media(SONG_DIR, self.roots, []),
                         media.SongMedia())

    def test_folder_is_highest_priority_root(self):
        record = media.build_song_media(SONG_DIR, self.roots, [_row()])
        self.assertEqual(record.folder, self.song1)


class OpenSongFolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "Song"
        self.folder.mkdir()

    def test_none_returns_false(self):
        self.assertFalse(media.open_song_folder(None))

    def test_missing_folder_returns_false(self):
        self.assertFalse(
            media.open_song_folder(Path(self.tmp.name) / "gone"))

    def test_file_not_folder_returns_false(self):
        path = Path(self.tmp.name) / "file.txt"
        path.write_text("x")
        self.assertFalse(media.open_song_folder(path))

    def test_no_startfile_returns_false(self):
        # os.startfile exists only on Windows; stub the module's os
        # reference with one that has no startfile at all.
        with mock.patch.object(media, "os", SimpleNamespace()):
            self.assertFalse(media.open_song_folder(self.folder))

    def test_startfile_called(self):
        with mock.patch.object(os, "startfile", create=True) as fake:
            self.assertTrue(media.open_song_folder(self.folder))
        fake.assert_called_once_with(str(self.folder))

    def test_startfile_error_returns_false(self):
        def raising(path):
            raise OSError("nope")

        with mock.patch.object(os, "startfile", raising, create=True):
            self.assertFalse(media.open_song_folder(self.folder))


class NormalizeSampleWindowTests(unittest.TestCase):
    def test_valid_window_passes_through(self):
        self.assertEqual(
            media.normalize_sample_window(64.58, 15.0, 93.988),
            (64.58, 15.0))

    def test_window_ending_exactly_at_the_end_passes_through(self):
        self.assertEqual(
            media.normalize_sample_window(78.988, 15.0, 93.988),
            (78.988, 15.0))

    def test_blank_length_plays_twelve_seconds(self):
        self.assertEqual(
            media.normalize_sample_window(10.0, None, 93.988),
            (10.0, 12.0))

    def test_zero_length_plays_twelve_seconds(self):
        self.assertEqual(
            media.normalize_sample_window(10.0, 0, 93.988),
            (10.0, 12.0))

    def test_negative_length_plays_twelve_seconds(self):
        # Stage-2 F5: a negative value is unusable, not a window.
        self.assertEqual(
            media.normalize_sample_window(10.0, -3.0, 93.988),
            (10.0, 12.0))

    def test_start_of_minus_one_starts_at_zero_for_twelve(self):
        self.assertEqual(
            media.normalize_sample_window(-1.0, 15.0, 93.988),
            (0.0, 12.0))

    def test_blank_start_starts_at_zero_for_twelve(self):
        self.assertEqual(
            media.normalize_sample_window(None, 15.0, 93.988),
            (0.0, 12.0))

    def test_overrunning_window_starts_at_zero_for_twelve(self):
        self.assertEqual(
            media.normalize_sample_window(90.0, 15.0, 93.988),
            (0.0, 12.0))

    def test_overrunning_a_short_song_plays_to_its_end(self):
        self.assertEqual(
            media.normalize_sample_window(90.0, 15.0, 8.0),
            (0.0, 8.0))

    def test_unknown_music_length_caps_nothing(self):
        self.assertEqual(
            media.normalize_sample_window(10.0, 15.0, None),
            (10.0, 15.0))

    def test_blank_window_plays_twelve_from_zero(self):
        # A chart with its own #MUSIC has no window at all.
        self.assertEqual(
            media.normalize_sample_window(None, None, None),
            (0.0, 12.0))

    def test_non_finite_and_non_numeric_values_read_as_missing(self):
        self.assertEqual(
            media.normalize_sample_window("abc", "nan", "inf"),
            (0.0, 12.0))

    def test_zero_or_negative_music_length_is_unknown(self):
        self.assertEqual(
            media.normalize_sample_window(10.0, 15.0, 0),
            (10.0, 15.0))
        self.assertEqual(
            media.normalize_sample_window(10.0, 15.0, -5.0),
            (10.0, 15.0))

    def test_huge_ints_read_as_missing(self):
        # A huge int from a hand-edited snapshot's JSON number must
        # not raise OverflowError into the Play action.
        self.assertEqual(
            media.normalize_sample_window(10 ** 10000, 15.0, 93.988),
            (0.0, 12.0))
        self.assertEqual(
            media.normalize_sample_window(64.58, 10 ** 10000, 93.988),
            (64.58, 12.0))
        self.assertEqual(
            media.normalize_sample_window(64.58, 15.0, 10 ** 10000),
            (64.58, 15.0))


class PlayerAvailableTests(unittest.TestCase):
    def test_installed_pygame_is_available(self):
        with mock.patch.object(media.importlib.util, "find_spec",
                               return_value=object()):
            self.assertTrue(media.player_available())

    def test_missing_pygame_is_not_available(self):
        with mock.patch.object(media.importlib.util, "find_spec",
                               return_value=None):
            self.assertFalse(media.player_available())

    def test_broken_lookup_reads_as_no_player(self):
        with mock.patch.object(media.importlib.util, "find_spec",
                               side_effect=ImportError("broken")):
            self.assertFalse(media.player_available())


class _FakeMusic:
    """A recording stand-in for pygame.mixer.music."""

    def __init__(self):
        self.load_calls = []
        self.play_calls = []
        self.stop_calls = 0
        self.load_error = None
        self.stop_error = None
        self.play_error = None
        self.raise_on_nonzero_start = False

    def load(self, path):
        if self.load_error is not None:
            raise self.load_error
        self.load_calls.append(path)

    def play(self, loops=0, start=0.0, fade_ms=0):
        self.play_calls.append((loops, start))
        if self.play_error is not None:
            raise self.play_error
        if self.raise_on_nonzero_start and start != 0.0:
            raise NotImplementedError("position not implemented")

    def stop(self):
        self.stop_calls += 1
        if self.stop_error is not None:
            raise self.stop_error


class _FakeMixer:
    """A recording stand-in for pygame.mixer."""

    def __init__(self):
        self.music = _FakeMusic()
        self.init_calls = 0
        self.init_error = None

    def init(self):
        self.init_calls += 1
        if self.init_error is not None:
            raise self.init_error


class SongPreviewPlayerTests(unittest.TestCase):
    def setUp(self):
        self.mixer = _FakeMixer()
        self.player = media.SongPreviewPlayer(mixer=self.mixer)
        self.path = Path("Pack") / "Song" / "song.ogg"

    def test_play_returns_the_effective_length(self):
        self.assertEqual(
            self.player.play(self.path, 64.58, 15.0, 93.988), 15.0)
        self.assertEqual(self.mixer.init_calls, 1)
        self.assertEqual(self.mixer.music.load_calls, [str(self.path)])
        self.assertEqual(self.mixer.music.play_calls, [(0, 64.58)])

    def test_second_play_does_not_init_again(self):
        self.player.play(self.path, 64.58, 15.0, 93.988)
        self.player.play(self.path, 10.0, 12.0, 93.988)
        self.assertEqual(self.mixer.init_calls, 1)
        self.assertEqual(self.mixer.music.play_calls,
                         [(0, 64.58), (0, 10.0)])

    def test_play_normalizes_the_window_first(self):
        self.assertEqual(
            self.player.play(self.path, -1.0, 15.0, 93.988), 12.0)
        self.assertEqual(self.mixer.music.play_calls, [(0, 0.0)])

    def test_init_failure_returns_none_and_retries(self):
        self.mixer.init_error = RuntimeError("no device")
        self.assertIsNone(self.player.play(self.path, 64.58, 15.0, 93.988))
        self.mixer.init_error = None
        self.assertEqual(
            self.player.play(self.path, 64.58, 15.0, 93.988), 15.0)
        self.assertEqual(self.mixer.init_calls, 2)

    def test_load_failure_returns_none(self):
        self.mixer.music.load_error = RuntimeError("unreadable")
        self.assertIsNone(self.player.play(self.path, 64.58, 15.0, 93.988))
        self.assertEqual(self.mixer.music.play_calls, [])

    def test_play_falls_back_to_the_start_when_the_mixer_cannot_seek(self):
        # A mixer that cannot set the position for the file's format
        # (WAV seeking is undocumented): the preview still plays,
        # from the start for the window length.
        self.mixer.music.raise_on_nonzero_start = True
        self.assertEqual(
            self.player.play(self.path, 64.58, 15.0, 93.988), 15.0)
        self.assertEqual(self.mixer.music.play_calls,
                         [(0, 64.58), (0, 0.0)])

    def test_play_returns_none_when_even_the_fallback_fails(self):
        self.mixer.music.play_error = RuntimeError("no device")
        self.assertIsNone(self.player.play(self.path, 64.58, 15.0, 93.988))

    def test_failed_lazy_import_returns_none(self):
        player = media.SongPreviewPlayer()
        with mock.patch.object(media, "_import_mixer",
                               side_effect=ImportError("no pygame")):
            self.assertIsNone(
                player.play(self.path, 64.58, 15.0, 93.988))

    def test_stop_stops_the_music(self):
        self.player.play(self.path, 64.58, 15.0, 93.988)
        self.player.stop()
        self.assertEqual(self.mixer.music.stop_calls, 1)

    def test_stop_before_play_is_a_no_op(self):
        self.player.stop()
        self.assertEqual(self.mixer.music.stop_calls, 0)

    def test_stop_never_raises(self):
        self.player.play(self.path, 64.58, 15.0, 93.988)
        self.mixer.music.stop_error = RuntimeError("gone")
        self.player.stop()


if __name__ == "__main__":
    unittest.main()
