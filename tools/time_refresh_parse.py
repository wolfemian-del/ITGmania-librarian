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
Pass 4 runs the real worker's pool path (proposal 0020) at 4, 8 and 16
workers over the same cache folder, warm; with --cold it runs pass 4
only, one worker count per invocation (pass --workers 4, 8 or 16), after
you have dropped the OS cache (a reboot is the reliable way on
Windows) so the cold number is a cold read — a second count in the same
invocation would read warmed file contents and still be labeled cold
(Revision 1). Each worker count gets a fresh temp dir, so no manifest
survives between runs to turn the full parse into a reuse.
"""

from __future__ import annotations

import argparse
import ctypes
import multiprocessing
import os
import pickle
import queue
import sys
import tempfile
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from itgmania_library.library_constants import HEADERS
from itgmania_library.library_sources import (
    _init_pool_worker,
    edit_fallback_index,
    parse_cache_file,
    parse_cache_file_task,
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
    # Imported here, not at module top, so a spawn child re-importing
    # this file as __mp_main__ does not pull in the loader module (and
    # its guarded Tkinter import) — the child only needs the data
    # modules (ChatGPT-6 follow-up 1, Revision 1).
    from itgmania_library.library_loader import LibraryLoader

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


def _peak_rss_bytes():
    """Peak RSS of this process in bytes, or None when it cannot be read.

    resource covers Linux (ru_maxrss in KiB) and macOS (bytes); Windows
    reads PeakWorkingSetSize through GetProcessMemoryInfo.
    """
    try:
        import resource
        factor = 1024 if sys.platform != "darwin" else 1
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * factor
    except (ImportError, AttributeError, ValueError):
        pass
    if sys.platform == "win32":
        try:
            counters = _WindowsMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(
                    handle, ctypes.byref(counters), counters.cb):
                return counters.PeakWorkingSetSize
        except (ImportError, AttributeError, OSError):
            pass
    return None


class _WindowsMemoryCounters(ctypes.Structure):
    """PROCESS_MEMORY_COUNTERS, for GetProcessMemoryInfo (Windows only).

    Defined at module level so both the parent-peak reader and the
    process-tree sampler below share it; it is only instantiated on
    Windows. ctypes itself imports on every platform.
    """

    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _current_rss_bytes(pid):
    """Current RSS of one process in bytes, or None when unreadable.

    Linux reads /proc/<pid>/status; Windows opens the process and
    reads WorkingSetSize through GetProcessMemoryInfo. A process
    that exited between listing and reading returns None.
    """
    if sys.platform.startswith("linux"):
        try:
            with open(f"/proc/{pid}/status", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            return None
        return None
    if sys.platform == "win32":
        try:
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
            if not handle:
                return None
            try:
                counters = _WindowsMemoryCounters()
                counters.cb = ctypes.sizeof(counters)
                if ctypes.windll.psapi.GetProcessMemoryInfo(
                        handle, ctypes.byref(counters), counters.cb):
                    return counters.WorkingSetSize
            finally:
                kernel32.CloseHandle(handle)
        except (ImportError, AttributeError, OSError):
            return None
    return None


def _child_pids():
    """PIDs of this process's children, or None when unlistable.

    Linux scans /proc for entries whose PPid is this process;
    Windows walks a Toolhelp32Snapshot. Other platforms return
    None: the aggregate RSS is then unavailable, not zero.
    """
    if sys.platform.startswith("linux"):
        children = []
        try:
            entries = os.listdir("/proc")
        except OSError:
            return None
        for entry in entries:
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/status",
                          encoding="utf-8") as handle:
                    ppid = None
                    for line in handle:
                        if line.startswith("PPid:"):
                            ppid = int(line.split()[1])
                            break
            except (OSError, ValueError, IndexError):
                continue
            if ppid == os.getpid():
                children.append(int(entry))
        return children
    if sys.platform == "win32":
        try:
            from ctypes import wintypes

            class _ProcessEntry(ctypes.Structure):
                _fields_ = [
                    ("dwSize", wintypes.DWORD),
                    ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260),
                ]

            kernel32 = ctypes.windll.kernel32
            snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
            if snapshot == -1:
                return None
            try:
                entry = _ProcessEntry()
                entry.dwSize = ctypes.sizeof(entry)
                children = []
                ok = kernel32.Process32FirstW(snapshot,
                                              ctypes.byref(entry))
                while ok:
                    if entry.th32ParentProcessID == os.getpid():
                        children.append(entry.th32ProcessID)
                    ok = kernel32.Process32NextW(snapshot,
                                                 ctypes.byref(entry))
                return children
            finally:
                kernel32.CloseHandle(snapshot)
        except (ImportError, AttributeError, OSError):
            return None
    return None


class _TreeRssSampler(threading.Thread):
    """Sample parent + children RSS during a pool run (Revision 1).

    The pool's workers are child processes, so the parent's peak RSS
    alone cannot answer proposal 0020's Q5 (the total transient
    footprint of the pool). A daemon thread polls the process tree
    while the run is in progress and keeps the highest parent +
    children sum it sees. Start before the run, stop after; read
    .peak, which is None when child enumeration is unavailable on
    this platform, so the aggregate is reported as unavailable
    rather than as the parent-only number. Never raises: a failed
    sample is skipped, and the thread stops on its event.
    """

    def __init__(self, interval=0.1):
        super().__init__(daemon=True)
        self.interval = interval
        self.peak = None
        # Named _stop_event, not _stop: threading.Thread already has
        # a _stop() method the join machinery calls.
        self._stop_event = threading.Event()

    def run(self):
        # Sample once at once, so even a run shorter than the
        # interval leaves a reading; then poll until stopped.
        # _sample returns False when child enumeration is
        # unavailable on this platform: stop polling then, and
        # leave the peak unset (unavailable, not zero).
        if not self._sample():
            return
        while not self._stop_event.wait(self.interval):
            if not self._sample():
                return

    def _sample(self):
        """One sample; False when enumeration is unavailable."""
        try:
            children = _child_pids()
            if children is None:
                return False
            total = _current_rss_bytes(os.getpid()) or 0
            for pid in children:
                total += _current_rss_bytes(pid) or 0
            if self.peak is None or total > self.peak:
                self.peak = total
            return True
        except Exception:
            return True

    def stop(self):
        self._stop_event.set()
        self.join()


def _measure_pool_startup(cache_dir, scores, workers):
    """Time one pool's spawn cost: create it, start every worker, shut it down.

    The executor spawns its workers lazily, one per submitted task, so
    a single submit only times one worker. Submit one file per worker
    and wait for all of them, so the measured cost is the whole pool's
    startup — the number the break-even threshold is computed from
    (Greptile finding 2, Revision 1). The files' parses (~4 ms each
    at Ian's scale) ride along and are negligible against the spawn.
    """
    files = [p for p in cache_dir.iterdir() if p.is_file()]
    if not files:
        return 0.0
    start = time.perf_counter()
    executor = ProcessPoolExecutor(
        max_workers=workers,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_init_pool_worker, initargs=(scores,))
    try:
        futures = [executor.submit(parse_cache_file_task, 1, str(files[0]))
                   for _ in range(workers)]
        for future in futures:
            try:
                future.result()
            except Exception:
                pass  # a file's parse is not what is timed here
    finally:
        executor.shutdown(wait=True)
    return time.perf_counter() - start


def run_pool_pass(cache_dir, stats_file, workers):
    """One full parse through the real worker's pool path (proposal 0020).

    Runs the real _load_worker on a bare loader instance with fresh
    stores in its own temp dir (no manifest, so nothing is reused),
    with POOL_WORKERS and POOL_MIN_FILES patched so the pool engages.
    Returns (rows, files, counts, seconds, startup_seconds,
    peak_rss_bytes, aggregate_rss_bytes, scores_entries,
    scores_pickle_bytes). The aggregate is the highest parent +
    workers RSS the sampler saw during the run (Revision 1): the
    parent peak alone cannot answer Q5's total transient footprint.
    It is None when child enumeration is unavailable on this
    platform. The brief startup pool's RSS is not included: it is
    transient and small against the full run.
    """
    from itgmania_library import library_loader
    from itgmania_library.library_loader import LibraryLoader

    scores = stats_index(stats_file)
    startup = _measure_pool_startup(cache_dir, scores, workers)
    with tempfile.TemporaryDirectory(prefix="refresh-pool-timing-") as tmp:
        tmp = Path(tmp)
        instance = object.__new__(LibraryLoader)
        instance._load_generation = 1
        instance._snapshot_lock = threading.Lock()
        instance._load_results = queue.Queue()
        instance.snapshot_store = SnapshotStore(tmp / "library_cache.json", HEADERS)
        instance.manifest_store = ManifestStore(tmp / "library_cache_manifest.json")
        sampler = _TreeRssSampler()
        sampler.start()
        start = time.perf_counter()
        with patch.object(library_loader, "POOL_WORKERS", workers), \
                patch.object(library_loader, "POOL_MIN_FILES", 1):
            instance._load_worker(cache_dir, stats_file, generation=1)
        seconds = time.perf_counter() - start
        sampler.stop()
        peak = _peak_rss_bytes()
        aggregate = sampler.peak
        items = []
        while not instance._load_results.empty():
            items.append(instance._load_results.get_nowait())
    failed = [item for item in items if item[0] == "failed"]
    if failed:
        raise RuntimeError(f"pool pass failed: {failed[0][1]}")
    loaded = [item for item in items if item[0] == "loaded"]
    _kind, args, kwargs = loaded[0]
    rows, files = args
    counts = {key: kwargs[key] for key in
              ("skipped_files", "files_without_charts", "skipped_blocks")}
    return (rows, files, counts, seconds, startup, peak, aggregate,
            len(scores), len(pickle.dumps(scores)))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cache_dir", type=Path,
                        help="Cache folder (one file per song, flat)")
    parser.add_argument("stats_xml", type=Path,
                        help="Player Stats.xml")
    parser.add_argument("--cold", action="store_true",
                        help="Run pass 4 only, as a cold read: drop the OS"
                        " cache first (a reboot is the reliable way on"
                        " Windows), so the number is a cold read")
    parser.add_argument("--workers", type=int, choices=(4, 8, 16),
                        default=None,
                        help="Run pass 4 for one worker count only"
                        " (default: 4, 8 and 16)")
    args = parser.parse_args(argv)
    if not args.cache_dir.is_dir():
        parser.error(f"cache dir is not a directory: {args.cache_dir}")
    if not args.stats_xml.is_file():
        parser.error(f"stats file is not a file: {args.stats_xml}")
    worker_counts = ([args.workers] if args.workers is not None
                     else [4, 8, 16])
    if args.cold and len(worker_counts) > 1:
        # A cold run reads the library from disk; the first count's
        # read warms the OS cache, so a second count in the same
        # invocation would be warm while still labeled cold
        # (Greptile finding 3, Revision 1). One count per cold
        # invocation, with a fresh cache drop before each.
        parser.error("--cold runs one worker count per invocation:"
                     " pass --workers 4, 8 or 16 and drop the OS cache"
                     " before each run")

    print(f"Python {sys.version.split()[0]}"
          f"  CPUs (logical): {os.cpu_count()}")
    print(f"cache dir: {args.cache_dir}")
    print(f"stats file: {args.stats_xml}")
    if args.cold:
        print("\npass 4 (cold): the OS cache should already be dropped —"
              " otherwise this is just another warm run.")
        _run_pool_passes(args.cache_dir, args.stats_xml, cold=True,
                         worker_counts=worker_counts)
        return 0
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
        _run_pool_passes(args.cache_dir, args.stats_xml,
                         worker_counts=worker_counts)
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


def _run_pool_passes(cache_dir, stats_file, cold=False, worker_counts=(4, 8, 16)):
    """Pass 4 (proposal 0020, §4.5): the pool path at 4, 8 and 16 workers.

    Each worker count gets a fresh temp dir inside run_pool_pass, so no
    manifest survives between runs. The numbers that settle the module
    constants are the worker total (against pass 2's serial parse) and
    the pool startup: the break-even file count is about
    startup / (3.9 ms x (1 - 1/workers)). The aggregate RSS is the
    parent + workers peak the sampler saw (Revision 1): the ~1 GB
    figure from proposal 0020's Q5 is a pre-merge tuning gate, not
    an enforced runtime ceiling — nothing in this commit stops the
    pool from engaging above it.
    """
    label = "cold" if cold else "warm"
    for workers in worker_counts:
        rows, files, counts, seconds, startup, peak, aggregate, entries, pickled = (
            run_pool_pass(cache_dir, stats_file, workers))
        print(f"\npass 4 ({label}, {workers} workers): {files:,} files,"
              f" {len(rows):,} chart rows")
        print(f"  {'pool startup':<15} {startup:7.2f} s")
        print(f"  {'worker total':<15} {seconds:7.2f} s"
              f"  (parse: {files / max(seconds, 1e-9):,.0f} files/s)")
        if peak is None:
            print("  peak RSS (parent): unreadable on this platform")
        else:
            print(f"  peak RSS (parent): {peak / (1024 * 1024):,.0f} MB")
        if aggregate is None:
            print("  peak RSS (aggregate): unavailable on this platform")
        else:
            print(f"  peak RSS (aggregate): {aggregate / (1024 * 1024):,.0f} MB")
        print(f"  scores: {entries:,} entries, {pickled:,} bytes pickled")
        if (counts["skipped_files"] or counts["files_without_charts"]
                or counts["skipped_blocks"]):
            print(f"  skipped files: {counts['skipped_files']},"
                  f" files without charts: {counts['files_without_charts']},"
                  f" skipped blocks: {counts['skipped_blocks']}")


if __name__ == "__main__":
    raise SystemExit(main())
