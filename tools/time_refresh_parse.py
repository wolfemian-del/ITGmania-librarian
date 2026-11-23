#!/usr/bin/env python3
# Developer timing tool, kept in tools/ and not shipped with the app.
# Run it from the repo root: copy this file next to launch.py, then
# `python time_refresh_parse.py "<cache-dir>" "<stats-xml>"`.
"""Time the Load / refresh worker phases over a real cache folder, no UI.

Mirrors LibraryLoader._load_worker (library_loader.py) phase by phase,
minus the parts that belong to the app: the snapshot and manifest are
written to a temp file instead of the real ones (timed, then deleted),
and the table insert on the main thread is not run at all. Read-only on
your library: it only reads the cache files and Stats.xml, and the only
thing it writes is the throwaway snapshot and manifest in the system
temp dir.

Usage (from the repo root, next to launch.py):
    python time_refresh_parse.py <cache-dir> <stats-xml>

<cache-dir> is the Cache folder from File -> Data paths... in the app
(the folder holding one file per song, flat, no subfolders);
<stats-xml> is the Player Stats.xml from the same dialog.

Three passes are timed. Pass 1 may already use cached file contents;
measuring a cold read needs separate preparation outside this script.
Pass 2 measures a warm read. Compare the worker subtotal with the warm
Load / refresh total you timed in the app (~30 s): the remainder is
queue delivery plus the table insert on the main thread. Pass 3 runs the
real worker incrementally against the snapshot and manifest pass 2
wrote, with nothing changed since: it re-parses nothing, so its worker
total is the number proposal 0018 promises (~1 s at Ian's scale).
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from itgmania_library.library_constants import HEADERS
from itgmania_library.library_loader import LibraryLoader
from itgmania_library.library_sources import (
    edit_fallback_index,
    parse_cache_file,
    stats_index,
)
from itgmania_library.library_stores import ManifestStore, SnapshotStore


def _time(call):
    start = time.perf_counter()
    result = call()
    return result, time.perf_counter() - start


def run_pass(cache_dir, stats_file, tmp):
    """One full worker pass; returns (rows, files, counts, phase_times).

    The snapshot and manifest are written to tmp (timed, then deleted
    with it), so pass 2 leaves a usable pair for the incremental pass.
    """
    times = {}
    scores, times["stats_index"] = _time(lambda: stats_index(stats_file))
    files, times["discovery"] = _time(
        lambda: [p for p in cache_dir.iterdir() if p.is_file()])
    edit_index, times["edit_index"] = _time(
        lambda: edit_fallback_index(scores))

    rows = []
    entries = {}
    counts = {"skipped_files": 0, "files_without_charts": 0, "skipped_blocks": 0}

    def _parse_all():
        for path in files:
            try:
                stat = path.stat()
                chart_rows, blocks = parse_cache_file(path, scores, edit_index)
                counts["skipped_blocks"] += blocks
                if not chart_rows:
                    counts["files_without_charts"] += 1
                rows.extend(chart_rows)
            except Exception:
                counts["skipped_files"] += 1
                continue
            entries[path.name] = {
                "name": path.name, "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
                "song_dir": chart_rows[0]["Course path"] if chart_rows else "",
                "rows": len(chart_rows), "skipped_blocks": blocks,
            }

    _, times["parse"] = _time(_parse_all)

    # The real snapshot and manifest writes, to throwaway paths (timed,
    # then deleted with tmp).
    stats_stat = stats_file.stat()
    store = SnapshotStore(tmp / "library_cache.json", HEADERS)
    _, times["snapshot_write"] = _time(lambda: store.write(
        cache_dir, stats_file, rows, len(files),
        counts["skipped_files"], counts["files_without_charts"],
        False, counts["skipped_blocks"]))
    manifest = ManifestStore(tmp / "library_cache_manifest.json")
    _, times["manifest_write"] = _time(lambda: manifest.write(
        cache_dir, stats_file, stats_stat.st_mtime_ns, stats_stat.st_size,
        entries))
    return rows, files, counts, times


def run_incremental_pass(cache_dir, stats_file, tmp):
    """One incremental worker pass against tmp's snapshot and manifest.

    Runs the real _load_worker on a bare loader instance, so the number
    is the worker's own, not a re-implementation. Returns (rows, files,
    counts, seconds, reparsed_files).
    """
    instance = object.__new__(LibraryLoader)
    instance._load_generation = 1
    instance._snapshot_lock = threading.Lock()
    instance._load_results = queue.Queue()
    instance.snapshot_store = SnapshotStore(tmp / "library_cache.json", HEADERS)
    instance.manifest_store = ManifestStore(tmp / "library_cache_manifest.json")
    start = time.perf_counter()
    instance._load_worker(cache_dir, stats_file, generation=1)
    seconds = time.perf_counter() - start
    items = []
    while not instance._load_results.empty():
        items.append(instance._load_results.get_nowait())
    failed = [item for item in items if item[0] == "failed"]
    if failed:
        raise RuntimeError(f"incremental pass failed: {failed[0][1]}")
    loaded = [item for item in items if item[0] == "loaded"]
    _kind, args, kwargs = loaded[0]
    rows, files = args
    counts = {key: kwargs[key] for key in
              ("skipped_files", "files_without_charts", "skipped_blocks")}
    return rows, files, counts, seconds, kwargs.get("reparsed_files")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cache_dir", type=Path,
                        help="Cache folder (one file per song, flat)")
    parser.add_argument("stats_xml", type=Path,
                        help="Player Stats.xml")
    args = parser.parse_args(argv)
    if not args.cache_dir.is_dir():
        parser.error(f"cache dir is not a directory: {args.cache_dir}")
    if not args.stats_xml.is_file():
        parser.error(f"stats file is not a file: {args.stats_xml}")

    print(f"Python {sys.version.split()[0]}"
          f"  CPUs (logical): {os.cpu_count()}")
    print(f"cache dir: {args.cache_dir}")
    print(f"stats file: {args.stats_xml}")
    totals = []
    # One temp dir for all three passes: pass 2 leaves the snapshot and
    # manifest pass 3 reads, and everything is deleted at the end.
    with tempfile.TemporaryDirectory(prefix="refresh-timing-") as tmp:
        tmp = Path(tmp)
        for pass_no in (1, 2):
            rows, files, counts, times = run_pass(
                args.cache_dir, args.stats_xml, tmp)
            total = sum(times.values())
            totals.append(total)
            print(f"\npass {pass_no}: {len(files):,} files,"
                  f" {len(rows):,} chart rows"
                  f" ({len(rows) / max(len(files), 1):.1f} rows/file)")
            for name in ("stats_index", "discovery", "edit_index", "parse",
                         "snapshot_write", "manifest_write"):
                print(f"  {name:<15} {times[name]:7.2f} s")
            print(f"  {'worker total':<15} {total:7.2f} s"
                  f"  (parse: {len(files) / max(times['parse'], 1e-9):,.0f} files/s)")
            if (counts["skipped_files"] or counts["files_without_charts"]
                    or counts["skipped_blocks"]):
                print(f"  skipped files: {counts['skipped_files']},"
                      f" files without charts: {counts['files_without_charts']},"
                      f" skipped blocks: {counts['skipped_blocks']}")
        rows, files, counts, seconds, reparsed = run_incremental_pass(
            args.cache_dir, args.stats_xml, tmp)
        print(f"\npass 3 (incremental, nothing changed): {files:,} files,"
              f" {len(rows):,} chart rows, re-parsed {reparsed}")
        print(f"  {'worker total':<15} {seconds:7.2f} s")
        if (counts["skipped_files"] or counts["files_without_charts"]
                or counts["skipped_blocks"]):
            print(f"  skipped files: {counts['skipped_files']},"
                  f" files without charts: {counts['files_without_charts']},"
                  f" skipped blocks: {counts['skipped_blocks']}")
    print(f"\npass 1 total: {totals[0]:.2f} s"
          f"   pass 2 total: {totals[1]:.2f} s"
          f"   pass 3 total: {seconds:.2f} s"
          f"   (pass 2 is the warm number)")
    print("The app's warm Load / refresh total minus the pass 2 worker"
          " total is queue delivery plus the table insert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
