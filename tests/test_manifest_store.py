"""Headless tests for the manifest store (proposal 0018).

The store lives in library_stores.py and takes no Tk: these tests run
against tmp paths with no app husk. The manifest is the per-file record
of the last scan — name, mtime in nanoseconds, size, song directory,
row count, skipped-blocks count — plus the Stats.xml mtime and size the
scan recorded. The loader reads it back to decide which files a refresh
can skip; every reason it cannot be used falls back to a full parse.
"""

import json
import tempfile
import unittest
from pathlib import Path

from itgmania_library import library_stores
from itgmania_library.library_stores import ManifestStore


def sample_entry(name="a.cache", mtime_ns=1000, size=50,
                 song_dir="Pack/Song", rows=2, skipped_blocks=0):
    return {"name": name, "mtime_ns": mtime_ns, "size": size,
            "song_dir": song_dir, "rows": rows,
            "skipped_blocks": skipped_blocks}


class ManifestStoreTests(unittest.TestCase):
    @staticmethod
    def make_store(directory):
        path = Path(directory) / "library_cache_manifest.json"
        return ManifestStore(path), path

    def test_write_read_round_trip_preserves_entries_and_stats(self):
        with tempfile.TemporaryDirectory() as directory:
            store, _path = self.make_store(directory)
            cache_dir = Path(directory) / "Cache" / "Songs"
            stats_file = Path(directory) / "Stats.xml"
            entries = {
                "a.cache": sample_entry("a.cache", 1000, 50, "Pack/A", 2, 1),
                "b.cache": sample_entry("b.cache", 2000, 60, "Pack/B", 0, 0),
            }

            store.write(cache_dir, stats_file, 3000, 70, entries)
            result = store.read(cache_dir, stats_file)

        self.assertTrue(result.loaded)
        self.assertEqual(result.entries, entries)
        self.assertEqual(result.stats_mtime_ns, 3000)
        self.assertEqual(result.stats_size, 70)
        self.assertIsNone(result.reason)
        self.assertIsNone(result.detail)

    def test_write_sorts_entries_by_name(self):
        # The walk order is arbitrary per run, so an unsorted manifest
        # would differ every refresh even when nothing changed.
        with tempfile.TemporaryDirectory() as directory:
            store, path = self.make_store(directory)
            entries = {
                "b.cache": sample_entry("b.cache"),
                "a.cache": sample_entry("a.cache"),
            }
            store.write(Path(directory), Path(directory) / "Stats.xml",
                        1, 1, entries)
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual([item["name"] for item in payload["files"]],
                         ["a.cache", "b.cache"])

    def test_read_missing_manifest_reports_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            store, _path = self.make_store(directory)
            result = store.read(Path(directory), Path(directory) / "Stats.xml")

        self.assertFalse(result.loaded)
        self.assertEqual(result.reason, "missing")
        self.assertEqual(result.entries, {})
        self.assertIsNone(result.detail)

    def test_read_invalid_utf8_reports_unreadable_with_detail(self):
        with tempfile.TemporaryDirectory() as directory:
            store, path = self.make_store(directory)
            path.write_bytes(b"\xff\xfe{}")
            result = store.read(Path(directory), Path(directory) / "Stats.xml")

        self.assertFalse(result.loaded)
        self.assertEqual(result.reason, "unreadable")
        self.assertIsInstance(result.detail, str)
        self.assertTrue(result.detail)

    def test_read_bad_json_reports_unreadable_with_detail(self):
        with tempfile.TemporaryDirectory() as directory:
            store, path = self.make_store(directory)
            path.write_text("{not json", encoding="utf-8")
            result = store.read(Path(directory), Path(directory) / "Stats.xml")

        self.assertFalse(result.loaded)
        self.assertEqual(result.reason, "unreadable")
        self.assertIsInstance(result.detail, str)
        self.assertTrue(result.detail)

    def test_read_wrong_format_version_reports_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            store, path = self.make_store(directory)
            payload = {"format_version": 2, "cache_dir": str(directory),
                       "stats_file": str(Path(directory) / "Stats.xml"),
                       "stats_mtime_ns": 1, "stats_size": 1, "files": []}
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = store.read(Path(directory), Path(directory) / "Stats.xml")

        self.assertFalse(result.loaded)
        self.assertEqual(result.reason, "invalid")

    def test_read_entry_missing_a_field_reports_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            store, path = self.make_store(directory)
            entry = sample_entry()
            del entry["rows"]
            payload = {"format_version": 1, "cache_dir": str(directory),
                       "stats_file": str(Path(directory) / "Stats.xml"),
                       "stats_mtime_ns": 1, "stats_size": 1, "files": [entry]}
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = store.read(Path(directory), Path(directory) / "Stats.xml")

        self.assertFalse(result.loaded)
        self.assertEqual(result.reason, "invalid")

    def test_read_entry_with_mistyped_field_reports_invalid(self):
        # A boolean is an int subclass, so a True mtime must not pass as 1.
        with tempfile.TemporaryDirectory() as directory:
            store, path = self.make_store(directory)
            entry = sample_entry(mtime_ns=True)
            payload = {"format_version": 1, "cache_dir": str(directory),
                       "stats_file": str(Path(directory) / "Stats.xml"),
                       "stats_mtime_ns": 1, "stats_size": 1, "files": [entry]}
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = store.read(Path(directory), Path(directory) / "Stats.xml")

        self.assertFalse(result.loaded)
        self.assertEqual(result.reason, "invalid")

    def test_read_entry_with_negative_counter_reports_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            store, path = self.make_store(directory)
            entry = sample_entry(rows=-1)
            payload = {"format_version": 1, "cache_dir": str(directory),
                       "stats_file": str(Path(directory) / "Stats.xml"),
                       "stats_mtime_ns": 1, "stats_size": 1, "files": [entry]}
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = store.read(Path(directory), Path(directory) / "Stats.xml")

        self.assertFalse(result.loaded)
        self.assertEqual(result.reason, "invalid")

    def test_read_duplicate_file_name_reports_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            store, path = self.make_store(directory)
            payload = {"format_version": 1, "cache_dir": str(directory),
                       "stats_file": str(Path(directory) / "Stats.xml"),
                       "stats_mtime_ns": 1, "stats_size": 1,
                       "files": [sample_entry("a.cache"),
                                 sample_entry("a.cache", mtime_ns=2000)]}
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = store.read(Path(directory), Path(directory) / "Stats.xml")

        self.assertFalse(result.loaded)
        self.assertEqual(result.reason, "invalid")

    def test_read_different_source_paths_reports_paths_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            store, _path = self.make_store(directory)
            cache_dir = Path(directory) / "Cache"
            stats_file = Path(directory) / "Stats.xml"
            store.write(cache_dir, stats_file, 1, 1,
                        {"a.cache": sample_entry()})
            result = store.read(Path(directory) / "Other", stats_file)

        self.assertFalse(result.loaded)
        self.assertEqual(result.reason, "paths_mismatch")

    def test_read_paths_match_after_normalization(self):
        # The snapshot read normalizes paths the same way; the manifest
        # must agree with it, so a spelling difference (a "./" prefix)
        # does not discard a usable manifest.
        with tempfile.TemporaryDirectory() as directory:
            store, _path = self.make_store(directory)
            store.write("Cache", "Stats.xml", 1, 1,
                        {"a.cache": sample_entry()})
            result = store.read("./Cache", "./Stats.xml")

        self.assertTrue(result.loaded)


if __name__ == "__main__":
    unittest.main()
