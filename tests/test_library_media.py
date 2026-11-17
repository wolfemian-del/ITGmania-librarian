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
        # The file exists under the root, but the form is refused, not
        # the absence: a Songs/... value is a VFS-top path.
        self._write(self.root1 / "Songs" / SONG_DIR, "banner.png")
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


if __name__ == "__main__":
    unittest.main()
