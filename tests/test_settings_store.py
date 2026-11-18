"""Headless tests for the settings store (proposal 0008, PR 2).

The store lives in library_stores.py and takes no Tk: these tests run
against tmp paths with no app husk. The load tests are the settings-behaviour
cases moved out of the app harnesses (proposal 0008 §6 step 3); the save
tests pin the dedup baseline, the deepcopy, and the temp-file cleanup.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from itgmania_library import library_stores
from itgmania_library.library_stores import SettingsStore


def make_store(directory):
    return SettingsStore(Path(directory) / "settings.json")


SETTINGS = {"cache_dir": "/cache", "stats_file": "/stats.xml",
            "column_order": ["Pack", "Meter"]}


class SettingsStoreLoadTests(unittest.TestCase):
    def test_load_of_a_valid_dict(self):
        with tempfile.TemporaryDirectory() as directory:
            store = make_store(directory)
            store.settings_path.write_text(json.dumps(SETTINGS), encoding="utf-8")

            self.assertEqual(store.load(), SETTINGS)
            self.assertIsNone(store.last_read_error)

    def test_load_of_a_corrupt_file_returns_empty_dict_and_records_the_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            store = make_store(directory)
            store.settings_path.write_text("{not json", encoding="utf-8")

            self.assertEqual(store.load(), {})
            self.assertIn("Expecting", store.last_read_error)

    def test_load_of_a_misencoded_file_returns_empty_dict_and_records_the_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            store = make_store(directory)
            store.settings_path.write_bytes(b"\xff\xfe not utf-8")

            self.assertEqual(store.load(), {})
            self.assertIsNotNone(store.last_read_error)

    def test_load_of_a_non_object_returns_empty_dict_and_records_the_failure(self):
        # Readable JSON that is not an object is discarded the same way:
        # there are no settings in it to keep.
        with tempfile.TemporaryDirectory() as directory:
            store = make_store(directory)
            store.settings_path.write_text("[1, 2]", encoding="utf-8")

            self.assertEqual(store.load(), {})
            self.assertIn("JSON object", store.last_read_error)

    def test_load_of_a_missing_file_returns_empty_dict_and_records_no_failure(self):
        # First run: no file yet is normal, and must not cry wolf.
        with tempfile.TemporaryDirectory() as directory:
            store = make_store(directory)

            self.assertEqual(store.load(), {})
            self.assertIsNone(store.last_read_error)

    def test_load_of_a_bom_saved_file_is_honoured_and_records_no_failure(self):
        # Issue #119: a BOM is stripped by utf-8-sig, so a BOM-saved file
        # reads fine and is not a discarded-settings case.
        with tempfile.TemporaryDirectory() as directory:
            store = make_store(directory)
            store.settings_path.write_bytes(
                b"\xef\xbb\xbf" + json.dumps(SETTINGS).encode("utf-8"))

            self.assertEqual(store.load(), SETTINGS)
            self.assertIsNone(store.last_read_error)

    def test_load_of_a_deeply_nested_file_returns_empty_dict(self):
        # Issue #122: a settings file nested far past the recursion limit
        # raises RecursionError out of json.load; it must fall back to
        # defaults instead of killing startup before the window appears.
        # Depth 1,000,000 for the same version-dependent reason as the
        # snapshot test: 10,000 levels raise on 3.12 but parse on 3.14,
        # so the depth must exceed every supported version's limit.
        with tempfile.TemporaryDirectory() as directory:
            store = make_store(directory)
            store.settings_path.write_text("[" * 1000000 + "]" * 1000000, encoding="utf-8")

            self.assertEqual(store.load(), {})

    @unittest.skipIf(sys.version_info < (3, 11),
                     "the int-string conversion limit is 3.11+")
    def test_load_of_an_oversized_integer_returns_empty_dict(self):
        # Issue #122: an integer past the 4,300-digit conversion limit
        # raises ValueError out of json.load; same fallback as above.
        with tempfile.TemporaryDirectory() as directory:
            store = make_store(directory)
            store.settings_path.write_text("[" + "9" * 5000 + "]", encoding="utf-8")

            self.assertEqual(store.load(), {})


class SettingsStoreSaveTests(unittest.TestCase):
    def test_save_skips_disk_write_when_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            store = make_store(directory)
            store.load()  # seeds the baseline (no file yet)

            store.save(dict(SETTINGS))
            self.assertTrue(store.settings_path.is_file())
            first_mtime = store.settings_path.stat().st_mtime_ns

            # A second save with no changes skips the write.
            with patch("itgmania_library.library_stores.json") as mock_json:
                # The mock stands in for the whole json module, so give
                # dumps its real behaviour: the test proves it is never
                # called, not that calling it breaks.
                mock_json.dumps.side_effect = json.dumps
                store.save(dict(SETTINGS))
                mock_json.dumps.assert_not_called()
            self.assertEqual(store.settings_path.stat().st_mtime_ns, first_mtime)

            # A change writes.
            changed = dict(SETTINGS, cache_dir="/other")
            store.save(changed)
            data = json.loads(store.settings_path.read_text(encoding="utf-8"))
            self.assertEqual(data["cache_dir"], "/other")

    def test_save_deepcopies_the_baseline(self):
        # The settings dict holds the live column_order list, which the
        # column drag handler mutates in place; if the baseline kept the
        # dict itself, the next comparison would compare that list against
        # itself and skip a real change.
        with tempfile.TemporaryDirectory() as directory:
            store = make_store(directory)
            store.load()
            settings = {"column_order": ["Pack", "Meter", "Time"]}

            store.save(settings)
            self.assertNotEqual(
                json.loads(store.settings_path.read_text(encoding="utf-8"))["column_order"][0],
                "Meter")

            settings["column_order"].remove("Meter")
            settings["column_order"].insert(0, "Meter")
            store.save(settings)

            data = json.loads(store.settings_path.read_text(encoding="utf-8"))
            self.assertEqual(data["column_order"], settings["column_order"])
            self.assertEqual(data["column_order"][0], "Meter")

    def test_load_returns_a_dict_that_does_not_alias_the_baseline(self):
        # Mutating the dict load() returned must not move the baseline, or
        # the next save of that dict would be skipped as unchanged.
        with tempfile.TemporaryDirectory() as directory:
            store = make_store(directory)
            store.settings_path.write_text(json.dumps(SETTINGS), encoding="utf-8")

            loaded = store.load()
            loaded["cache_dir"] = "/other"
            store.save(loaded)

            data = json.loads(store.settings_path.read_text(encoding="utf-8"))
            self.assertEqual(data["cache_dir"], "/other")

    def test_failed_save_leaves_no_temp_file_and_raises(self):
        # Proposal 0008 §6 step 1 (store side): a failed settings dump
        # leaves no settings.tmp behind. The failure is forced inside
        # os.replace, so the temp file exists when the write fails.
        with tempfile.TemporaryDirectory() as directory:
            store = make_store(directory)
            store.load()

            store.settings_path.write_text("old contents", encoding="utf-8")
            # Patch the store's os reference, not os.replace itself
            # (that patches the shared module and leaks to every
            # module in the process). wraps keeps the rest of os real,
            # including getpid, which names the temp file.
            with patch("itgmania_library.library_stores.os", wraps=os) as mock_os:
                mock_os.replace.side_effect = OSError("locked")
                with self.assertRaises(OSError):
                    store.save(dict(SETTINGS))

            self.assertEqual([p for p in Path(directory).iterdir()
                              if p.name.endswith(".tmp")], [])
            # The old file itself must survive too: a store that damaged
            # its own file before delegating would pass the no-temp check.
            self.assertEqual(
                store.settings_path.read_text(encoding="utf-8"),
                "old contents")
            # The baseline stays stale, so the next save retries.
            store.save(dict(SETTINGS))
            self.assertTrue(store.settings_path.is_file())

    def test_save_after_load_skips_when_the_dict_is_unchanged(self):
        # The baseline is seeded by load(): saving back the dict that was
        # just loaded, unchanged, writes nothing. Without the seed the
        # first save after startup would always rewrite the file.
        with tempfile.TemporaryDirectory() as directory:
            store = make_store(directory)
            store.settings_path.write_text(json.dumps(SETTINGS), encoding="utf-8")
            store.load()
            first_mtime = store.settings_path.stat().st_mtime_ns

            store.save(dict(SETTINGS))

            self.assertEqual(store.settings_path.stat().st_mtime_ns, first_mtime)

    def test_baseline_is_seeded_from_the_raw_file_dict(self):
        # Proposal 0008 §6 step 4: a settings file with an obsolete key,
        # load(), save() the assembled dict unchanged — the file is
        # rewritten without the key, because the baseline starts as the
        # raw file dict and differs from the assembled one.
        with tempfile.TemporaryDirectory() as directory:
            store = make_store(directory)
            store.settings_path.write_text(
                json.dumps(dict(SETTINGS, obsolete_key=1)), encoding="utf-8")

            store.load()
            store.save(dict(SETTINGS))

            data = json.loads(store.settings_path.read_text(encoding="utf-8"))
            self.assertNotIn("obsolete_key", data)
            self.assertEqual(data["cache_dir"], "/cache")


class SettingsStoreValidatorTests(unittest.TestCase):
    def test_valid_window_geometry_accepts_and_canonicalizes(self):
        self.assertEqual(
            library_stores._valid_window_geometry("1000x620+10+10", (700, 440)),
            "1000x620+10+10")
        # A negative coordinate is rebuilt in Tk's own spelling ("+-8"):
        # the shorter "-8" form means "8px from the right edge" to Tk.
        self.assertEqual(
            library_stores._valid_window_geometry("1000x620+-8+100", (700, 440)),
            "1000x620+-8+100")
        self.assertEqual(
            library_stores._valid_window_geometry("1000x620-8+100", (700, 440)),
            "1000x620+-8+100")

    def test_valid_window_geometry_rejects_unusable_values(self):
        for value in (None, 42, "garbage", "1000x620", "1x1+0+0",
                      "699x620+0+0", "1000x439+0+0"):
            with self.subTest(value=value):
                self.assertIsNone(
                    library_stores._valid_window_geometry(value, (700, 440)))

    def test_valid_window_geometry_honours_the_given_minimum(self):
        self.assertEqual(
            library_stores._valid_window_geometry("500x530+10+10", (480, 520)),
            "500x530+10+10")
        self.assertIsNone(
            library_stores._valid_window_geometry("500x530+10+10", (700, 440)))
        self.assertEqual(
            library_stores._valid_window_geometry("900x500+10+10", (700, 440)),
            "900x500+10+10")
        self.assertIsNone(
            library_stores._valid_window_geometry("900x500+10+10", (480, 520)))

    def test_valid_column_width_accepts_in_range_and_rejects_the_rest(self):
        for value in (55, 100, 2000):
            with self.subTest(value=value):
                self.assertEqual(
                    library_stores._valid_column_width(value, "Pack"), value)
        for value in (None, "garbage", 54, 2001):
            with self.subTest(value=value):
                self.assertIsNone(
                    library_stores._valid_column_width(value, "Pack"))


class MigrateConfigDirTests(unittest.TestCase):
    """The settings-folder migration (proposal 0015)."""

    def test_old_dir_with_both_files_moves_whole(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            old_dir = root / "ITGmania Library Visualizer"
            old_dir.mkdir()
            (old_dir / "settings.json").write_text("{}", encoding="utf-8")
            (old_dir / "library_cache.json").write_text("{}", encoding="utf-8")
            new_path = root / "ITGmania Librarian" / "settings.json"

            self.assertEqual(
                library_stores._migrate_config_dir(new_path), new_path)
            self.assertFalse(old_dir.exists())
            self.assertTrue((new_path.parent / "settings.json").is_file())
            self.assertTrue(
                (new_path.parent / "library_cache.json").is_file())

    def test_both_dirs_exist_prefers_new_and_leaves_old(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            old_dir = root / "ITGmania Library Visualizer"
            old_dir.mkdir()
            (old_dir / "settings.json").write_text("{}", encoding="utf-8")
            new_dir = root / "ITGmania Librarian"
            new_dir.mkdir()
            new_path = new_dir / "settings.json"

            self.assertEqual(
                library_stores._migrate_config_dir(new_path), new_path)
            self.assertTrue(old_dir.is_dir())

    def test_neither_dir_exists_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as root:
            new_path = Path(root) / "ITGmania Librarian" / "settings.json"

            self.assertEqual(
                library_stores._migrate_config_dir(new_path), new_path)
            self.assertFalse(new_path.parent.exists())

    def test_failed_rename_falls_back_to_the_old_path(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            old_dir = root / "ITGmania Library Visualizer"
            old_dir.mkdir()
            (old_dir / "settings.json").write_text("{}", encoding="utf-8")
            new_path = root / "ITGmania Librarian" / "settings.json"

            with patch.object(Path, "rename", side_effect=OSError("denied")):
                result = library_stores._migrate_config_dir(new_path)

            self.assertEqual(result, old_dir / "settings.json")
            self.assertTrue(old_dir.is_dir())
            self.assertFalse(new_path.parent.exists())

    def test_new_path_is_a_file_falls_back_to_the_old_path(self):
        # Grok on PR #233: the new path existing as a file (not a
        # directory) was the one untested branch — the rename onto it
        # raises OSError and the migration falls back to the old path.
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            old_dir = root / "ITGmania Library Visualizer"
            old_dir.mkdir()
            (old_dir / "settings.json").write_text("{}", encoding="utf-8")
            new_path = root / "ITGmania Librarian" / "settings.json"
            new_path.parent.write_text("not a directory", encoding="utf-8")

            result = library_stores._migrate_config_dir(new_path)

            self.assertEqual(result, old_dir / "settings.json")
            self.assertTrue(old_dir.is_dir())
            self.assertTrue(new_path.parent.is_file())


if __name__ == "__main__":
    unittest.main()
