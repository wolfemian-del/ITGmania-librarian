"""Decision, counts, Stats, and status-line tests for the manifest refresh (proposal 0018, §6).

These tests run the real _load_worker against small fixture folders with
real SnapshotStore and ManifestStore instances, and count the real
parse_cache_file calls — so they pin the per-file decisions (reuse,
re-parse, retry, duplicate) rather than the store alone. The status-line
tests drive _loaded directly with the delivery kwargs the worker sends.
"""

import json
import os
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from itgmania_library import library_loader as loader
from itgmania_library import library_sources as sources
from itgmania_library import library_stores as stores
from itgmania_library.library_constants import HEADERS


def cache_text(song="Pack/Song", title="Song", difficulty="Hard", charts=1):
    """One cache file: the given song, one chart block per chart."""
    text = (f"#SONGFILENAME:Songs/{song}/audio.ogg;\n"
            f"#TITLE:{title};\n")
    for _ in range(charts):
        text += ("#NOTEDATA:;\n#STEPSTYPE:dance-single;\n"
                 f"#DIFFICULTY:{difficulty};\n")
    return text


def stats_text(percent="0.96", score="456", song="Pack/Song"):
    """A Stats.xml scoring the song's dance-single Hard chart."""
    return ("<Stats><SongScores>"
            f"<Song Dir='Songs/{song}'>"
            "<Steps StepsType='dance-single' Difficulty='Hard'>"
            "<HighScoreList><NumTimesPlayed>3</NumTimesPlayed>"
            f"<HighScore><PercentDP>{percent}</PercentDP><Score>{score}</Score></HighScore>"
            "</HighScoreList></Steps></Song>"
            "</SongScores></Stats>")


class _StubStatus:
    """A status line without a window: a str behind get/set, like StringVar."""

    def __init__(self, value=""):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


class ManifestRefreshTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.cache_dir = root / "Cache"
        self.cache_dir.mkdir()
        self.stats_file = root / "Stats.xml"
        self.stats_file.write_text("<Stats/>", encoding="utf-8")
        self.root = root

    def make_instance(self):
        instance = object.__new__(loader.LibraryLoader)
        instance._load_generation = 1
        instance._snapshot_lock = threading.Lock()
        instance._load_results = queue.Queue()
        instance.root = Mock()
        instance.snapshot_store = stores.SnapshotStore(
            self.root / "library_cache.json", HEADERS)
        instance.manifest_store = stores.ManifestStore(
            self.root / "library_cache_manifest.json")
        return instance

    def write_cache(self, name, **kwargs):
        (self.cache_dir / name).write_text(cache_text(**kwargs), encoding="utf-8")

    def run_worker(self, instance, parse_calls, fail_names=()):
        """Run the worker once, counting real parses; return the loaded delivery."""
        def counting_parse(path, scores, edit_index=None):
            parse_calls.append(path.name)
            if path.name in fail_names:
                raise ValueError("boom")
            return sources.parse_cache_file(path, scores, edit_index)

        with patch.object(loader, "parse_cache_file", counting_parse):
            instance._load_worker(self.cache_dir, self.stats_file, generation=1)
        items = []
        while not instance._load_results.empty():
            items.append(instance._load_results.get_nowait())
        failed = [item for item in items if item[0] == "failed"]
        self.assertEqual(failed, [], f"worker failed: {failed}")
        loaded = [item for item in items if item[0] == "loaded"]
        self.assertEqual(len(loaded), 1)
        _kind, args, kwargs = loaded[0]
        return args, kwargs

    def test_unchanged_refresh_reparses_nothing_and_keeps_rows(self):
        self.write_cache("a.cache", song="Pack/A")
        self.write_cache("b.cache", song="Pack/B")
        instance = self.make_instance()
        calls = []
        rows1, kwargs1 = self.run_worker(instance, calls)
        self.assertEqual(sorted(calls), ["a.cache", "b.cache"])
        self.assertEqual(len(rows1[0]), 2)
        self.assertNotIn("reparsed_files", kwargs1)  # first run is a full parse

        calls.clear()
        rows2, kwargs2 = self.run_worker(instance, calls)
        self.assertEqual(calls, [])
        self.assertEqual(rows2[0], rows1[0])
        self.assertEqual(kwargs2["reparsed_files"], 0)
        self.assertEqual(rows2[1], 2)
        self.assertEqual(kwargs2["skipped_files"], 0)

    def test_changed_file_is_reparsed_and_its_rows_replaced(self):
        self.write_cache("a.cache", song="Pack/A")
        self.write_cache("b.cache", song="Pack/B")
        instance = self.make_instance()
        calls = []
        rows1, _ = self.run_worker(instance, calls)
        calls.clear()
        # Same song, harder chart: the file changed, so only it is parsed.
        self.write_cache("b.cache", song="Pack/B", difficulty="Challenge")
        rows2, kwargs2 = self.run_worker(instance, calls)
        self.assertEqual(calls, ["b.cache"])
        self.assertEqual(kwargs2["reparsed_files"], 1)
        self.assertEqual(len(rows2[0]), 2)
        difficulties = sorted(row["Difficulty"] for row in rows2[0])
        self.assertEqual(difficulties, ["Challenge", "Hard"])
        # The manifest now records the new mtime, so a third refresh is quiet.
        calls.clear()
        rows3, kwargs3 = self.run_worker(instance, calls)
        self.assertEqual(calls, [])
        self.assertEqual(rows3[0], rows2[0])
        self.assertEqual(kwargs3["reparsed_files"], 0)

    def test_new_file_is_parsed_and_deleted_file_drops_its_rows(self):
        self.write_cache("a.cache", song="Pack/A")
        self.write_cache("b.cache", song="Pack/B")
        instance = self.make_instance()
        calls = []
        rows1, _ = self.run_worker(instance, calls)
        self.assertEqual(len(rows1[0]), 2)
        calls.clear()
        self.write_cache("c.cache", song="Pack/C")
        (self.cache_dir / "a.cache").unlink()
        rows2, kwargs2 = self.run_worker(instance, calls)
        self.assertEqual(calls, ["c.cache"])
        self.assertEqual(kwargs2["reparsed_files"], 1)
        songs = sorted(row["Course path"] for row in rows2[0])
        self.assertEqual(songs, ["Pack/B", "Pack/C"])

    def test_failed_file_is_retried_on_every_refresh(self):
        self.write_cache("a.cache", song="Pack/A")
        self.write_cache("bad.cache", song="Pack/Bad")
        instance = self.make_instance()
        calls = []
        rows1, kwargs1 = self.run_worker(instance, calls, fail_names=("bad.cache",))
        self.assertIn("bad.cache", calls)
        self.assertEqual(kwargs1["skipped_files"], 1)
        self.assertEqual(len(rows1[0]), 1)
        # The failed file is not in the manifest, so the next refresh tries it again.
        manifest = json.loads(
            (self.root / "library_cache_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual([item["name"] for item in manifest["files"]], ["a.cache"])
        calls.clear()
        rows2, kwargs2 = self.run_worker(instance, calls, fail_names=("bad.cache",))
        self.assertIn("bad.cache", calls)
        self.assertEqual(kwargs2["skipped_files"], 1)
        # The retried failure counts in the re-parsed number (§4.4).
        self.assertEqual(kwargs2["reparsed_files"], 1)
        self.assertEqual(len(rows2[0]), 1)
        # Once it parses, it lands in the manifest and is reused like the rest.
        calls.clear()
        rows3, kwargs3 = self.run_worker(instance, calls)
        self.assertEqual(sorted(calls), ["bad.cache"])
        self.assertEqual(len(rows3[0]), 2)
        manifest = json.loads(
            (self.root / "library_cache_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(item["name"] for item in manifest["files"]),
                         ["a.cache", "bad.cache"])

    def test_zero_row_record_does_not_reuse_another_files_rows(self):
        # A zero-row record's song directory is "", and another file's
        # rows can carry that same directory (a cache file with no
        # #SONGFILENAME). Reusing the group for the zero-row file would
        # duplicate those rows.
        (self.cache_dir / "a.cache").write_text(
            "#TITLE:A;\n#NOTEDATA:;\n#STEPSTYPE:dance-single;\n#DIFFICULTY:Hard;\n",
            encoding="utf-8")
        (self.cache_dir / "b.cache").write_text(
            "#SONGFILENAME:Songs/Pack/B/audio.ogg;\n#TITLE:B;\n", encoding="utf-8")
        instance = self.make_instance()
        calls = []
        rows1, _ = self.run_worker(instance, calls)
        self.assertEqual(len(rows1[0]), 1)
        calls.clear()
        rows2, kwargs2 = self.run_worker(instance, calls)
        self.assertEqual(calls, [])
        self.assertEqual(len(rows2[0]), 1)
        self.assertEqual(rows2[0], rows1[0])
        self.assertEqual(kwargs2["reparsed_files"], 0)

    def test_duplicate_song_dir_is_always_reparsed(self):
        # Two cache files for the same song: the snapshot cannot tell
        # whose rows are whose, so both are re-parsed every refresh.
        self.write_cache("a.cache", song="Pack/Same")
        self.write_cache("b.cache", song="Pack/Same")
        instance = self.make_instance()
        calls = []
        rows1, _ = self.run_worker(instance, calls)
        self.assertEqual(sorted(calls), ["a.cache", "b.cache"])
        self.assertEqual(len(rows1[0]), 2)
        calls.clear()
        rows2, kwargs2 = self.run_worker(instance, calls)
        self.assertEqual(sorted(calls), ["a.cache", "b.cache"])
        self.assertEqual(rows2[0], rows1[0])
        # Nothing was reused, so no re-parsed count is carried: the
        # full-parse text stands (proposal 0018, Revision 2).
        self.assertNotIn("reparsed_files", kwargs2)

    def test_counts_and_order_match_a_full_parse(self):
        self.write_cache("a.cache", song="Pack/A")
        (self.cache_dir / "b.cache").write_text(
            "#SONGFILENAME:Songs/Pack/B/audio.ogg;\n#TITLE:B;\n", encoding="utf-8")
        (self.cache_dir / "c.cache").write_text(
            "#SONGFILENAME:Songs/Pack/C/audio.ogg;\n#TITLE:C;\n"
            "#NOTEDATA:;\n#STEPSTYPE:dance-single;\n"
            "#NOTEDATA:;\n#STEPSTYPE:dance-single;\n#DIFFICULTY:Hard;\n",
            encoding="utf-8")
        instance = self.make_instance()
        calls = []
        rows1, kwargs1 = self.run_worker(instance, calls)
        self.assertEqual(rows1[1], 3)
        self.assertEqual(kwargs1["files_without_charts"], 1)
        self.assertEqual(kwargs1["skipped_blocks"], 1)
        self.assertEqual(len(rows1[0]), 2)

        # Nothing changed: the incremental refresh returns the same rows
        # in the same order, with the same counts.
        calls.clear()
        rows2, kwargs2 = self.run_worker(instance, calls)
        self.assertEqual(calls, [])
        self.assertEqual(rows2[0], rows1[0])
        self.assertEqual(rows2[1], rows1[1])
        for key in ("skipped_files", "files_without_charts", "skipped_blocks"):
            self.assertEqual(kwargs2[key], kwargs1[key], key)

        # One file gains a chart: the incremental result must equal a
        # fresh full parse of the same folder (the manifest is deleted
        # for the comparison run, so it falls back to a full parse).
        self.write_cache("a.cache", song="Pack/A", charts=2)
        calls.clear()
        rows3, kwargs3 = self.run_worker(instance, calls)
        self.assertEqual(calls, ["a.cache"])
        (self.root / "library_cache_manifest.json").unlink()
        calls.clear()
        rows4, kwargs4 = self.run_worker(instance, calls)
        self.assertEqual(sorted(calls), ["a.cache", "b.cache", "c.cache"])
        self.assertEqual(rows4[0], rows3[0])
        self.assertEqual(rows4[1], rows3[1])
        for key in ("skipped_files", "files_without_charts", "skipped_blocks"):
            self.assertEqual(kwargs4[key], kwargs3[key], key)
        self.assertNotIn("reparsed_files", kwargs4)

    def test_stale_manifest_is_reused_after_a_failed_write(self):
        # Proposal 0018, Revision 1: a failed manifest write leaves the
        # previous manifest in place, and the next refresh reuses it.
        self.write_cache("a.cache", song="Pack/A")
        self.write_cache("b.cache", song="Pack/B")
        instance = self.make_instance()
        calls = []
        rows1, _ = self.run_worker(instance, calls)
        manifest_bytes = (self.root / "library_cache_manifest.json").read_bytes()

        real_write = instance.manifest_store.write

        def failing_write(*args):
            raise OSError("disk full")

        instance.manifest_store.write = failing_write
        calls.clear()
        rows2, kwargs2 = self.run_worker(instance, calls)
        self.assertEqual(calls, [])
        self.assertEqual(rows2[0], rows1[0])
        self.assertEqual(kwargs2["reparsed_files"], 0)
        # The failure is the manifest's, not the snapshot's: the snapshot
        # was saved, so the message must not say otherwise.
        self.assertIn("library_cache_manifest.json", kwargs2["manifest_error"])
        self.assertEqual(kwargs2["cache_error"], "")
        # The failed write left the previous manifest untouched on disk.
        self.assertEqual((self.root / "library_cache_manifest.json").read_bytes(),
                         manifest_bytes)

        instance.manifest_store.write = real_write
        calls.clear()
        rows3, kwargs3 = self.run_worker(instance, calls)
        self.assertEqual(calls, [])
        self.assertEqual(rows3[0], rows1[0])
        self.assertEqual(kwargs3["reparsed_files"], 0)
        self.assertEqual(kwargs3["cache_error"], "")
        self.assertEqual((self.root / "library_cache_manifest.json").read_bytes(),
                         manifest_bytes)

    def test_failed_manifest_write_then_new_file_for_known_song(self):
        # Claude's finding 1 (PR #269): a failed manifest write, plus a
        # new file for an already-known song, showed duplicate rows — the
        # stale manifest claims the old file alone, and the coverage check
        # compares song-directory sets, not which files claim them.
        self.write_cache("a.cache", song="Pack/A")
        instance = self.make_instance()
        calls = []
        rows1, _ = self.run_worker(instance, calls)
        self.assertEqual(len(rows1[0]), 1)
        self.write_cache("b.cache", song="Pack/A")
        calls.clear()
        with patch.object(instance.manifest_store, "write",
                          side_effect=OSError("disk full")):
            rows2, _ = self.run_worker(instance, calls)
        self.assertEqual(len(rows2[0]), 2)
        calls.clear()
        rows3, kwargs3 = self.run_worker(instance, calls)
        self.assertEqual(sorted(calls), ["a.cache", "b.cache"])
        self.assertEqual(len(rows3[0]), 2)
        self.assertEqual(rows3[0], rows2[0])
        self.assertNotIn("reparsed_files", kwargs3)

    def test_failed_snapshot_write_records_no_manifest(self):
        # The manifest is written only after a successful snapshot write:
        # a changed file whose snapshot write failed must be re-parsed
        # next time, not recorded as up to date.
        self.write_cache("a.cache", song="Pack/A")
        self.write_cache("b.cache", song="Pack/B")
        instance = self.make_instance()
        calls = []
        rows1, _ = self.run_worker(instance, calls)
        manifest_bytes = (self.root / "library_cache_manifest.json").read_bytes()
        self.write_cache("a.cache", song="Pack/A", charts=2)
        real_write = instance.snapshot_store.write

        def failing_write(*args):
            raise OSError("disk full")

        instance.snapshot_store.write = failing_write
        calls.clear()
        rows2, kwargs2 = self.run_worker(instance, calls)
        self.assertEqual(len(rows2[0]), 3)
        self.assertIn("disk full", kwargs2["cache_error"])
        self.assertEqual((self.root / "library_cache_manifest.json").read_bytes(),
                         manifest_bytes)
        instance.snapshot_store.write = real_write
        calls.clear()
        rows3, _ = self.run_worker(instance, calls)
        self.assertIn("a.cache", calls)
        self.assertEqual(len(rows3[0]), 3)
        self.assertEqual(rows3[0], rows2[0])

    def test_coverage_failure_falls_back_to_full_parse(self):
        # A readable manifest that does not cover the snapshot (here a
        # hand-edited song directory) falls back to a full parse.
        self.write_cache("a.cache", song="Pack/A")
        self.write_cache("b.cache", song="Pack/B")
        instance = self.make_instance()
        calls = []
        rows1, _ = self.run_worker(instance, calls)
        manifest_path = self.root / "library_cache_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in manifest["files"]:
            if item["name"] == "a.cache":
                item["song_dir"] = "Pack/Elsewhere"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        calls.clear()
        rows2, kwargs2 = self.run_worker(instance, calls)
        self.assertEqual(sorted(calls), ["a.cache", "b.cache"])
        self.assertEqual(rows2[0], rows1[0])
        self.assertNotIn("reparsed_files", kwargs2)

    def test_unusable_snapshot_with_good_manifest_falls_back_to_full_parse(self):
        self.write_cache("a.cache", song="Pack/A")
        self.write_cache("b.cache", song="Pack/B")
        instance = self.make_instance()
        calls = []
        rows1, _ = self.run_worker(instance, calls)
        (self.root / "library_cache.json").write_text("not json", encoding="utf-8")
        calls.clear()
        rows2, kwargs2 = self.run_worker(instance, calls)
        self.assertEqual(sorted(calls), ["a.cache", "b.cache"])
        self.assertEqual(rows2[0], rows1[0])
        self.assertNotIn("reparsed_files", kwargs2)

    def test_stats_replaced_during_read_is_merged_next_refresh(self):
        # The stat is taken before the read: if Stats.xml is replaced
        # while it is being read, the manifest records the old stat, so
        # the next refresh re-merges. Taken after, it would record the
        # new stat against old scores and skip the merge.
        self.write_cache("a.cache", song="Pack/Song")
        self.stats_file.write_text(stats_text(), encoding="utf-8")
        instance = self.make_instance()
        calls = []
        rows1, _ = self.run_worker(instance, calls)
        self.assertEqual(rows1[0][0]["Score"], 456)
        real_index = loader.stats_index

        def replacing_index(path):
            scores = real_index(path)
            self.stats_file.write_text(stats_text(percent="0.50", score="789"),
                                       encoding="utf-8")
            return scores

        calls.clear()
        with patch.object(loader, "stats_index", replacing_index):
            rows2, _ = self.run_worker(instance, calls)
        self.assertEqual(rows2[0][0]["Score"], 456)
        calls.clear()
        rows3, _ = self.run_worker(instance, calls)
        self.assertEqual(calls, [])
        self.assertEqual(rows3[0][0]["Score"], 789)

    def test_stats_mtime_only_change_merges_scores(self):
        self.write_cache("a.cache", song="Pack/Song")
        self.stats_file.write_text(stats_text(), encoding="utf-8")
        instance = self.make_instance()
        calls = []
        rows1, _ = self.run_worker(instance, calls)
        self.assertEqual(rows1[0][0]["Score"], 456)
        calls.clear()
        # Same length, new mtime: the score changes digits (456 -> 789),
        # so only the mtime moves.
        self.stats_file.write_text(stats_text(percent="0.50", score="789"),
                                   encoding="utf-8")
        rows2, kwargs2 = self.run_worker(instance, calls)
        self.assertEqual(calls, [])
        self.assertEqual(kwargs2["reparsed_files"], 0)
        self.assertEqual(rows2[0][0]["Score"], 789)

    def test_stats_size_only_change_merges_scores(self):
        self.write_cache("a.cache", song="Pack/Song")
        self.stats_file.write_text(stats_text(), encoding="utf-8")
        instance = self.make_instance()
        calls = []
        rows1, _ = self.run_worker(instance, calls)
        manifest = json.loads(
            (self.root / "library_cache_manifest.json").read_text(encoding="utf-8"))
        old_mtime_ns = manifest["stats_mtime_ns"]
        calls.clear()
        # Longer score, old mtime: only the size moves.
        self.stats_file.write_text(stats_text(percent="0.50", score="1000000"),
                                   encoding="utf-8")
        os.utime(self.stats_file, ns=(old_mtime_ns, old_mtime_ns))
        rows2, kwargs2 = self.run_worker(instance, calls)
        self.assertEqual(calls, [])
        self.assertEqual(kwargs2["reparsed_files"], 0)
        self.assertEqual(rows2[0][0]["Score"], 1000000)

    def test_same_size_file_with_new_mtime_is_reparsed(self):
        self.write_cache("a.cache", song="Pack/A")
        instance = self.make_instance()
        calls = []
        rows1, _ = self.run_worker(instance, calls)
        calls.clear()
        # Same length, new mtime: the title changes one letter.
        self.write_cache("a.cache", song="Pack/A", title="Sona")
        rows2, _ = self.run_worker(instance, calls)
        self.assertEqual(calls, ["a.cache"])
        self.assertEqual(len(rows2[0]), 1)

    def test_new_size_file_with_old_mtime_is_reparsed(self):
        self.write_cache("a.cache", song="Pack/A")
        instance = self.make_instance()
        calls = []
        rows1, _ = self.run_worker(instance, calls)
        manifest = json.loads(
            (self.root / "library_cache_manifest.json").read_text(encoding="utf-8"))
        old_mtime_ns = next(item["mtime_ns"] for item in manifest["files"]
                            if item["name"] == "a.cache")
        calls.clear()
        self.write_cache("a.cache", song="Pack/A", charts=2)
        os.utime(self.cache_dir / "a.cache", ns=(old_mtime_ns, old_mtime_ns))
        rows2, _ = self.run_worker(instance, calls)
        self.assertEqual(calls, ["a.cache"])
        self.assertEqual(len(rows2[0]), 2)

    def test_scandir_stat_failure_skips_the_file_quietly(self):
        # A file whose stat fails is not in the scan at all: it is not
        # parsed, and it is not counted in skipped_files.
        self.write_cache("a.cache", song="Pack/A")
        instance = self.make_instance()

        class _GhostEntry:
            name = "ghost.cache"

            def is_file(self):
                return True

            def stat(self):
                raise OSError("cannot stat")

        real_scandir = os.scandir

        class _ScandirWithGhost:
            def __init__(self, path):
                self._iterator = real_scandir(path)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self._iterator.close()
                return False

            def __iter__(self):
                yield _GhostEntry()
                yield from self._iterator

        calls = []
        with patch.object(os, "scandir", _ScandirWithGhost):
            rows, kwargs = self.run_worker(instance, calls)
        self.assertEqual(len(rows[0]), 1)
        self.assertEqual(kwargs["skipped_files"], 0)

    def test_stats_stat_failure_fails_the_load(self):
        # The stat is taken before the read, so a Stats.xml that vanishes
        # before the stat fails the load rather than recording a stat for
        # scores that were never read.
        self.write_cache("a.cache", song="Pack/A")
        instance = self.make_instance()
        stats_file = self.stats_file
        real_stat = Path.stat

        def failing_stat(path):
            if path == stats_file:
                raise OSError("gone")
            return real_stat(path)

        with patch.object(Path, "stat", failing_stat):
            instance._load_worker(self.cache_dir, self.stats_file, generation=1)
        items = []
        while not instance._load_results.empty():
            items.append(instance._load_results.get_nowait())
        failed = [item for item in items if item[0] == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertIn("Could not read", failed[0][1])

    def test_changed_stats_merges_scores_without_reparsing(self):
        self.write_cache("a.cache", song="Pack/Song")
        self.stats_file.write_text(stats_text(), encoding="utf-8")
        instance = self.make_instance()
        calls = []
        rows1, _ = self.run_worker(instance, calls)
        self.assertEqual(rows1[0][0]["Score"], 456)
        calls.clear()
        # A new play session: a different (and longer) score, so both the
        # mtime and the size move.
        self.stats_file.write_text(stats_text(percent="0.50", score="1000000"),
                                   encoding="utf-8")
        rows2, kwargs2 = self.run_worker(instance, calls)
        self.assertEqual(calls, [])
        self.assertEqual(kwargs2["reparsed_files"], 0)
        self.assertEqual(rows2[0][0]["Score"], 1000000)

    def test_unchanged_stats_leaves_reused_rows_untouched(self):
        self.write_cache("a.cache", song="Pack/Song")
        self.stats_file.write_text(stats_text(), encoding="utf-8")
        instance = self.make_instance()
        calls = []
        rows1, _ = self.run_worker(instance, calls)
        self.assertEqual(rows1[0][0]["Score"], 456)
        calls.clear()
        rows2, kwargs2 = self.run_worker(instance, calls)
        self.assertEqual(calls, [])
        self.assertEqual(rows2[0], rows1[0])

    def test_discarded_manifest_delivers_the_full_parse_text(self):
        # Claude's worker-level assertion (proposal 0018, Revision 2): a
        # refresh that discards the manifest carries no re-parsed count,
        # so _loaded shows the full-parse text.
        self.write_cache("a.cache", song="Pack/A")
        instance = self.make_instance()
        calls = []
        self.run_worker(instance, calls)
        (self.root / "library_cache_manifest.json").write_text(
            "{not json", encoding="utf-8")
        calls.clear()
        _rows, kwargs = self.run_worker(instance, calls)
        self.assertEqual(calls, ["a.cache"])
        self.assertNotIn("reparsed_files", kwargs)


class ManifestCoverageTests(unittest.TestCase):
    def test_exact_cover_is_usable(self):
        entries = {
            "a.cache": {"song_dir": "Songs/Pack/A", "rows": 2},
            "b.cache": {"song_dir": "Songs/Pack/B", "rows": 0},
        }
        rows = [{"Course path": "Songs/Pack/A"}]
        self.assertTrue(loader._manifest_covers_snapshot(entries, rows))

    def test_snapshot_dir_not_claimed_is_not_usable(self):
        entries = {"a.cache": {"song_dir": "Songs/Pack/A", "rows": 2}}
        rows = [{"Course path": "Songs/Pack/A"},
                {"Course path": "Songs/Pack/B"}]
        self.assertFalse(loader._manifest_covers_snapshot(entries, rows))

    def test_claimed_dir_not_in_snapshot_is_not_usable(self):
        entries = {
            "a.cache": {"song_dir": "Songs/Pack/A", "rows": 2},
            "b.cache": {"song_dir": "Songs/Pack/B", "rows": 1},
        }
        rows = [{"Course path": "Songs/Pack/A"}]
        self.assertFalse(loader._manifest_covers_snapshot(entries, rows))

    def test_zero_row_entry_claims_nothing(self):
        # A file that produced no rows can carry any song directory (its
        # record says "") without breaking coverage either way.
        entries = {
            "a.cache": {"song_dir": "Songs/Pack/A", "rows": 2},
            "b.cache": {"song_dir": "Songs/Pack/Nowhere", "rows": 0},
        }
        rows = [{"Course path": "Songs/Pack/A"}]
        self.assertTrue(loader._manifest_covers_snapshot(entries, rows))

    def test_empty_snapshot_and_empty_manifest_cover(self):
        self.assertTrue(loader._manifest_covers_snapshot({}, []))


class StatusLineTests(unittest.TestCase):
    @staticmethod
    def make_loaded():
        instance = object.__new__(loader.LibraryLoader)
        instance._load_generation = 0
        instance.status = _StubStatus()
        instance.progress = Mock()
        instance.load_button = Mock()
        instance.set_sync_menu_state = Mock()
        instance.on_library_changed = Mock()
        return instance

    def test_reparsed_count_replaces_parsed(self):
        instance = self.make_loaded()
        rows = [{"Title": "a"}, {"Title": "b"}]
        instance._loaded(rows, 2, reparsed_files=3)
        self.assertEqual(
            instance.status.get(),
            "Scanned 2 files · re-parsed 3 · 2 charts in total.")

    def test_reparsed_zero_is_shown(self):
        instance = self.make_loaded()
        rows = [{"Title": "a"}, {"Title": "b"}]
        instance._loaded(rows, 2, reparsed_files=0)
        self.assertEqual(
            instance.status.get(),
            "Scanned 2 files · re-parsed 0 · 2 charts in total.")

    def test_no_count_keeps_the_old_text(self):
        instance = self.make_loaded()
        rows = [{"Title": "a"}, {"Title": "b"}]
        instance._loaded(rows, 2)
        self.assertEqual(
            instance.status.get(), "Scanned 2 files · parsed 2 charts.")

    def test_conditional_segments_follow_the_new_base(self):
        instance = self.make_loaded()
        rows = [{"Title": "a"}, {"Title": "b"}]
        instance._loaded(rows, 2, skipped_files=1, reparsed_files=1)
        self.assertEqual(
            instance.status.get(),
            "Scanned 2 files · re-parsed 1 · 2 charts in total"
            " · skipped 1 unreadable.")

    def test_manifest_error_names_the_manifest_not_the_snapshot(self):
        instance = self.make_loaded()
        rows = [{"Title": "a"}, {"Title": "b"}]
        instance._loaded(rows, 2,
                         manifest_error="library_cache_manifest.json: disk full")
        self.assertEqual(
            instance.status.get(),
            "Scanned 2 files · parsed 2 charts."
            " Local refresh manifest not saved:"
            " library_cache_manifest.json: disk full")
        self.assertNotIn("Local snapshot not saved", instance.status.get())


if __name__ == "__main__":
    unittest.main()
