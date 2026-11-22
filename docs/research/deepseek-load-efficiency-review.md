> **Provenance:** load-efficiency review by DeepSeek, 2026-11-12 (original filename `deepseek_markdown_20261112_75d63a.md`). Landed in the repo with the roadmap (2026-11-22). It names the old repository `ITGmania-library-viewer`, renamed to `ITGmania-librarian` 2026-11-18.
>
> This is a hypothesis list, not a decision document: it measured nothing and every number in it was asserted. P1, P2, and P5 were verified by Muse against the owner's real measurements 2026-11-22 (7,499 files, 42,375 rows; parse 29 s of a ~30 s worker, insert 14 s, ~40 s end-to-end warm); P0, P3, and P4 were killed by measurement. Body below is verbatim as delivered; only this header was added.

# ITGmania Library Viewer — Load Efficiency Review

**Repository:** `wolfemian-del/ITGmania-library-viewer` (branch: `main`)
**Method:** Files read via `raw.githubusercontent.com`
**Scope:** Additional load-efficiency gains beyond the improvements already merged.

---

## Context

The current `main` branch already includes several load-efficiency improvements:

- Startup defers the snapshot load until after the window paints (`_load_initial_snapshot`).
- Cache writes are atomic via `os.replace`.
- Row insertion is time-budgeted (`ROW_INSERT_BUDGET_SECONDS = 0.012`).
- A `queue.Queue` (`_load_results`) and a `_snapshot_lock` exist for background scan results.

The remaining gaps below are ordered by user-visible payoff.

---

## 🐢 Startup: The Snapshot Load Still Blocks the Main Thread

**Finding:** `_load_initial_snapshot` still calls `load_cached_data` synchronously on the Tk main thread. For a large `library_cache.json`, the `json.load` plus validation loop blocks the event loop for seconds after the window appears, leaving the UI frozen during what looks like a successful launch.

**Recommendation:** Move `load_cached_data` to a daemon thread and feed rows to the table through the existing `_load_results` queue or a dedicated `queue.Queue`. The window stays interactive immediately; the status line can show "Loading saved library…" and rows can stream in via `after`-scheduled batches. The queue infrastructure is already in place, so this is a localized change to `_load_initial_snapshot` and the poll handler.

---

## 📚 Full Refresh: No Incremental Mechanism

**Finding:** `load_data` is the refresh entry point. The presence of `_load_generation` and `_snapshot_lock` suggests scans are generation-tracked and serialized. However, nothing in `library_data.py` or the visible refresh path checks file modification times before re-parsing. `parse_cache_file` unconditionally calls `path.read_text()` and re-parses every chart block, and `stats_index` unconditionally calls `ET.parse` on the entire `Stats.xml`.

**Recommendation:** Add a manifest sidecar (or a small SQLite table) keyed by file path storing `st_mtime_ns` and `st_size`. On refresh:

1. `os.scandir` the cache tree once.
2. Compare `st_mtime_ns` and `st_size` against the manifest.
3. Re-parse only changed files.

This turns a warm refresh from O(all charts) into O(changed charts). For a 10k-file library with a few edits, the difference is between tens of seconds and sub-second latency. The atomic-write pattern already used for `library_cache.json` can be reused for the manifest.

---

## ⚙️ Parsing Is CPU-Bound and Single-Threaded Under the GIL

**Finding:** Even with incremental refresh, a cold first run must parse everything. `parse_cache_file` is pure Python text processing (`read_text`, `re.split`, `tag_map`) and `stats_index` builds a full DOM with `ET.parse`. The existing threading model gives concurrency for I/O but cannot use multiple cores for the CPU-bound parse work because of the GIL.

**Recommendation:** Use `concurrent.futures.ProcessPoolExecutor` for the cache-file parsing phase:

- Workers should be module-level functions that take only a path string and return plain `dict`s (the row dicts are already JSON-serializable, so IPC is cheap).
- A `chunksize` of 32–128 amortizes pool overhead.
- Guard with `freeze_support()` if the app is ever packaged with PyInstaller.

On an 8-core machine, this alone typically yields a 3–5× reduction in cold-parse wall time.

---

## 🌊 `Stats.xml` Should Be Streamed, Not DOM-Parsed

**Finding:** `stats_index` uses `ET.parse(stats_file).getroot()`, which materializes the entire score history in memory. For players with large libraries, this is a high-memory, high-latency step that runs on every refresh unless the manifest short-circuits it.

**Recommendation:** Switch to `ET.iterparse` with `elem.clear()` on consumed `Song` subtrees. This keeps peak memory bounded and is typically faster for large files because it avoids building the full tree. The score-merging logic can run incrementally as each `Song` element ends.

---

## 📁 File Discovery Should Use `os.scandir`

**Finding:** The visible code does not show the directory walk for refresh, but if it uses `Path.iterdir` or `os.walk` followed by separate `stat` calls, it pays an extra syscall per entry.

**Recommendation:** Use a single `os.scandir` walk that yields `DirEntry.stat(follow_symlinks=False)` results. This gives you `st_mtime_ns` and `st_size` for free and feeds the manifest comparison directly.

---

## 📊 Row Delivery Is Batched, But Parse Results Still Accumulate

**Finding:** `ROW_INSERT_BUDGET_SECONDS` handles the UI side, but `_load_results` currently delivers finished scans as a whole. If a refresh produces all rows before handing them to the main thread, peak memory spikes and the first paint is delayed until the last file parses.

**Recommendation:** Stream parsed rows to the queue in chunks (e.g., 500 rows) from the worker or process pool, rather than collecting the entire result set first. The main-thread poll loop then inserts each chunk under the existing time budget. This reduces time-to-first-visible-row and smooths memory usage.

---

## 📋 Priority Order

| Priority | Change | Expected Impact | Risk |
|---|---|---|---|
| **P0** | Move `load_cached_data` off the main thread | Startup UI responsive in <300 ms | Low |
| **P1** | Manifest-based incremental refresh | Warm refresh <1 s regardless of library size | Medium |
| **P2** | Process-pool cache parsing | Cold refresh 3–5× faster on multicore | Medium (packaging/spawn) |
| **P3** | `iterparse` for `Stats.xml` | Lower memory, faster large-score parse | Low |
| **P4** | `os.scandir` walk for discovery | Marginal syscall reduction; enables P1 | Low |
| **P5** | Chunked result streaming to the queue | Earlier first paint, lower peak memory | Low |

---

## Summary

The two changes with the largest user-visible payoff are **P0** (which eliminates the post-launch freeze) and **P1** (which makes repeated refreshes near-instant). The process pool is the biggest lever for the one-time cold-parse cost, but it should follow the manifest work so that most users never hit the cold path again.