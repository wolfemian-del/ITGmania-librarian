"""The background data engine: loads the library, syncs scores, reports progress.

LibraryLoader (proposal 0009 Step 4) owns the scan/sync workers, the result
queue, the polling, the progress and status reporting, and the load results
(rows, loaded_source_paths, last_refreshed_at, the snapshot-summary counters).
It never touches the table or the filter variables directly; everything the
UI needs arrives through the callbacks in its constructor (on_library_changed,
on_nothing_loaded), and the DataPathsDialog component it is given.

Tests: tests/test_library_loader.py.
"""

from __future__ import annotations

import multiprocessing
import os
import queue
import threading
import time
try:
    import tkinter as tk
    from tkinter import messagebox
except ImportError:
    tk = None
    messagebox = None
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime
from pathlib import Path

from itgmania_library.library_format import format_refresh_time
from itgmania_library.library_sources import (
    _init_pool_worker,
    _normalized_source_path,
    any_scores_match,
    edit_fallback_index,
    invalid_paths_note,
    looks_like_song_tree,
    merge_scores,
    parse_cache_file,
    parse_cache_file_task,
    stats_index,
)


# The process-pool parse (proposal 0020, §4.4): module constants, set
# from the pass-4 measurement in tools/time_refresh_parse.py. Neither
# is a settings key or a constructor input, so the loader's constructor
# is untouched. Both values are provisional — pass 4 on the owner's
# machine (Ryzen 9 4900HS, 8 cores / 16 threads) settles the worker
# count over 4/8/16 and the threshold from the measured spawn cost
# before any PR lands. There is no chunksize constant: D3's
# submit-plus-as_completed submits one future per file, so the
# 32-file chunks §4.2 sketches have no role — per-file submission
# gives finer balance and per-file progress (see _parse_files_pool).
POOL_WORKERS = os.cpu_count() or 1
POOL_MIN_FILES = 300


def _manifest_covers_snapshot(entries, rows):
    """Whether the manifest's song directories exactly cover the snapshot's row groups.

    Proposal 0018, D2: validity by coverage, not timestamps. The check
    survives the scores sync because the sync never adds or removes rows
    (and never changes Course paths), so the song-directory sets still
    match even though refreshed_at moved. An entry with no rows claims
    nothing, so a file that produced no charts can neither cover nor
    break a song directory.
    """
    snapshot_dirs = {row["Course path"] for row in rows}
    claimed_dirs = {entry["song_dir"] for entry in entries.values() if entry["rows"] > 0}
    return snapshot_dirs == claimed_dirs


class LibraryLoader:
    """Load the library (scan or snapshot), sync scores, report progress/status.

    Every input is keyword-only (proposal 0014), in five groups:

    Data:
      snapshot_store:       the snapshot store, passed in (already standalone).
      manifest_store:       the manifest store, passed in (proposal 0018).
      cache_var, stats_var: the path variables, read.
    The window the loader drives:
      status:               the status StringVar, for progress/status reporting.
      progress:             the progress-bar widget.
      load_button:          the Load button widget, disabled during a load.
      set_sync_menu_state:  callable, enabling/disabling File -> Sync scores.
    What the loader tells the shell:
      on_library_changed:   callback (rows, preserve_selection,
                            changed_keys=None), delivered when a load
                            or a sync finishes, for the table/filter/
                            Course Builder part only (Q2). A sync
                            passes the set merge_scores reports; a load
                            passes nothing, so the table rebuilds all.
      on_nothing_loaded:    callback, delivered when load_cached_data finds no
                            snapshot, so the shell repaints the empty table.
      report_discarded_settings: callback, for the discarded-settings note the
                            shell reports (the settings store stays in the
                            shell, so _report_discarded_settings stays app-side
                            and the loader calls it through this callback).
      save_settings:        callable.
    The dialog it talks to:
      dialog:               the DataPathsDialog component, for open(),
                            set_note(), and maybe_show_first_run().
      had_saved_paths:      whether saved settings contained path keys, for the
                            dialog's first-run check (the loader never sees the
                            settings file).
    Scheduling:
      root:                 for after() scheduling of the result polling.

    The shell calls start() once, after construction (proposal 0014).
    """

    def __init__(self, *, snapshot_store, manifest_store, cache_var, stats_var,
                 status, progress, load_button, set_sync_menu_state,
                 on_library_changed, on_nothing_loaded,
                 report_discarded_settings, save_settings,
                 dialog, had_saved_paths, root):
        self.snapshot_store = snapshot_store
        self.manifest_store = manifest_store
        self.cache_var = cache_var
        self.stats_var = stats_var
        self.status = status
        self.progress = progress
        self.load_button = load_button
        self.set_sync_menu_state = set_sync_menu_state
        self.on_library_changed = on_library_changed
        self.on_nothing_loaded = on_nothing_loaded
        self.dialog = dialog
        self.save_settings = save_settings
        self.root = root
        self.report_discarded_settings = report_discarded_settings
        self.had_saved_paths = had_saved_paths
        # Load results and worker state (the engine's own state, §2).
        self.rows: list[dict] = []
        self.loaded_source_paths = None
        self.last_refreshed_at = ""
        self._load_generation = 0  # counts Load / refresh requests; a scan from an older request is dropped
        self._scan_in_flight = False  # a scan is running; the scores sync refuses to start while one is (issue #147)
        self._sync_in_flight = False  # a scores sync is running; a second sync refuses to start while one is (issue #147)
        self._snapshot_lock = threading.Lock()  # one scan at a time may check its generation and write the snapshot
        self._load_results = queue.Queue()  # finished scans wait here; only the main thread delivers them (_poll_load_results)
        self._load_started_at = None
        # The snapshot summary _loaded records for the scores sync to write
        # back (proposal 0014 declares them here; the reads keep their
        # getattr defaults for bare test instances).
        self._snapshot_files = 0
        self._snapshot_skipped_files = 0
        self._snapshot_files_without_charts = 0
        self._snapshot_nested_song_tree = False
        self._snapshot_skipped_blocks = 0

    def start(self):
        """Begin the loader's startup, once, after the shell has built it.

        Watches the two path variables, starts the result polling, and
        schedules the saved-snapshot load for after the window has painted.
        The shell calls _report_discarded_settings() just before this.
        """
        for var in (self.cache_var, self.stats_var):
            var.trace_add("write", lambda *_: self._source_paths_changed())
        self.root.after(75, self._poll_load_results)
        # The saved snapshot is loaded once the window has painted, not here:
        # reading and rendering it can take a moment at library scale, and doing
        # it before the event loop starts would leave the user watching the
        # console (or an unpainted window) with no explanation.
        if self.snapshot_store.snapshot_path.is_file():
            self.status.set("Loading saved library…")
            self.progress.start(12)
        self.root.after(50, self._load_initial_snapshot)

    def _load_initial_snapshot(self):
        """Load the saved snapshot (scheduled by start() so the window paints first)."""
        if self._load_generation:
            # A Load / refresh pressed inside the deferral window supersedes
            # the startup restore: the scan owns the progress bar, the Load
            # button, and the status line until it delivers, and its result
            # replaces whatever the restore would have shown.
            return
        try:
            self.load_cached_data()
        finally:
            self.progress.stop()
            # The snapshot load rewrites the status line, so a discarded
            # settings file reported at build time would be erased here;
            # appending it again keeps the notice visible after startup.
            self.report_discarded_settings()
        # Last startup step: if no snapshot restored and the paths are not
        # both usable, ask where the library is before leaving an empty table.
        # The dialog's first-run check takes its two facts as arguments
        # (Step 3): whether a snapshot is loaded, and whether saved
        # settings contained path keys (had_saved_paths, a constructor
        # input, since the loader never sees the settings file).
        snapshot_loaded = self.loaded_source_paths is not None
        self.dialog.maybe_show_first_run(snapshot_loaded, self.had_saved_paths)

    def load_cached_data(self):
        # The store reads and validates; this method only maps the result
        # onto the status line and delivers the rows (proposal 0008).
        result = self.snapshot_store.read(self.cache_var.get(), self.stats_var.get())
        if result.loaded:
            self._loaded(
                result.rows, result.files, result.skipped_files,
                result.files_without_charts, result.skipped_blocks,
                result.nested_song_tree,
                refreshed_at=result.refreshed_at,
                from_cache=True,
                source_paths=result.source_paths,
            )
            self._report_moved_source_paths(*result.source_paths)
            self._report_newer_stats_file()
            return
        if result.reason == "missing":
            self.status.set("No saved library yet. Choose File → Data paths…, then Load / refresh.")
        elif result.reason == "unreadable":
            self.status.set(f"Saved library snapshot could not be read ({result.detail}). Click Load / refresh to rebuild it.")
        elif result.reason == "invalid":
            self.status.set("Saved library snapshot is invalid or outdated. Click Load / refresh to rebuild it.")
        else:  # paths_mismatch
            self.status.set("Saved library snapshot is for different data paths. Click Load / refresh to rebuild it.")
        # No snapshot restored: no refresh follows, so the table stays
        # empty and the status line tells the user to Load / refresh.
        # [CODE] on_nothing_loaded covers the path load_cached_data used
        # to refresh directly.
        self.on_nothing_loaded()

    def _source_paths_changed(self):
        if not self.loaded_source_paths:
            return
        if self.paths_match_loaded():
            stamp = format_refresh_time(self.last_refreshed_at)
            self.status.set(
                f"Showing saved library snapshot · {len(self.rows):,} charts"
                f" · last refreshed {stamp}.")
        else:
            self.status.set(
                "Displayed library uses different data paths."
                " Click Load / refresh to show the selected sources.")
        # While the Data paths dialog is open, the same news shows inside it
        # (the conditional note), not only on the status line behind the modal.
        # At first run there is no snapshot loaded, so the early return above
        # leaves the dialog's first-run note alone.
        self.dialog.set_note(self.dialog.paths_changed())

    def paths_match_loaded(self):
        """Whether the current paths match the loaded snapshot's sources.

        True when no snapshot is loaded: there is nothing to differ from.
        Bare test instances without path state report True the same way.
        """
        loaded = getattr(self, "loaded_source_paths", None)
        if not loaded:
            return True
        cache_var = getattr(self, "cache_var", None)
        stats_var = getattr(self, "stats_var", None)
        if cache_var is None or stats_var is None:
            return True
        current = (cache_var.get(), stats_var.get())
        return all(
            _normalized_source_path(saved) == _normalized_source_path(selected)
            for saved, selected in zip(loaded, current))

    def _report_moved_source_paths(self, cache_dir: str, stats_file: str) -> None:
        """Append a note when a restored snapshot's saved paths no longer exist.

        The snapshot restores on a string match only, so a moved ITGmania
        folder is invisible until the next refresh fails. The note names the
        missing side and points at File → Data paths…, where replacements
        are picked.
        """
        missing = []
        if cache_dir and not Path(cache_dir).is_dir():
            missing.append("cache folder")
        if stats_file and not Path(stats_file).is_file():
            missing.append("Stats.xml")
        if not missing:
            return
        if len(missing) == 2:
            message = ("The saved cache folder and Stats.xml no longer exist. "
                       "Choose File → Data paths…, then Load / refresh.")
        elif missing[0] == "cache folder":
            message = ("The saved cache folder no longer exists. "
                       "Choose File → Data paths…, then Load / refresh.")
        else:
            message = ("The saved Stats.xml no longer exists. "
                       "Choose File → Data paths…, then Load / refresh.")
        # A bare instance built for a snapshot test may carry a Mock status
        # whose get() is not a string; that is "no status line", not an error.
        current = self.status.get()
        if not isinstance(current, str):
            current = ""
        if message in current:
            return
        self.status.set(f"{current} {message}" if current else message)

    def _report_newer_stats_file(self):
        """Append a hint when Stats.xml is newer than the restored snapshot (issue #147).

        A play session changes Stats.xml without touching the cache, so the
        saved scores can go stale while the snapshot still restores fine.
        The hint compares the *selected* Stats.xml path against the
        snapshot's refreshed_at -- that is the file a sync would read. One
        benign wrinkle: a Stats.xml change during a scan reads as newer
        than the snapshot just written, so the hint can fire for a sync
        that changes nothing.
        """
        refreshed_at = getattr(self, "last_refreshed_at", "")
        if not refreshed_at:
            return
        stats = Path(self.stats_var.get())
        if not stats.is_file():
            return
        try:
            mtime = stats.stat().st_mtime
            stamp = datetime.fromisoformat(refreshed_at).timestamp()
        except (OSError, ValueError, TypeError):
            return
        if mtime <= stamp:
            return
        message = ("Stats.xml is newer than the saved library. "
                   "Choose File → Sync scores from Stats.xml to refresh scores.")
        # A bare instance built for a snapshot test may carry a Mock status
        # whose get() is not a string; that is "no status line", not an error.
        current = self.status.get()
        if not isinstance(current, str):
            current = ""
        if message in current:
            return
        self.status.set(f"{current} {message}" if current else message)

    def load_data(self):
        cache, stats = Path(self.cache_var.get()), Path(self.stats_var.get())
        if not cache.is_dir() or not stats.is_file():
            # Invalid paths open the Data paths dialog instead of an error box:
            # the fix is in the dialog, so that is where the user should be.
            self.dialog.open(note=invalid_paths_note(cache, stats))
            return
        self.save_settings()
        self.progress.start(12)
        self.status.set("Reading chart cache and player scores…")
        # Disabled until the scan's result is delivered, so a second click cannot
        # pile up scans; the File menu entry still starts a newer scan, which
        # supersedes this one by generation and owns re-enabling the button.
        self.load_button.configure(state="disabled")
        self._load_generation += 1
        generation = self._load_generation
        # A scan is in flight until its result is delivered; the scores sync
        # refuses to start while one is, and its menu entry is disabled.
        self._scan_in_flight = True
        self.set_sync_menu_state("disabled")
        # The scan's clock for its time-remaining estimate (see _show_load_progress).
        self._load_started_at = time.monotonic()
        threading.Thread(target=self._load_worker, args=(cache, stats, generation), daemon=True).start()

    def _load_is_stale(self, generation):
        return self._load_generation != generation

    def _load_worker(self, cache: Path, stats_file: Path, generation: int):
        # A scan whose generation is no longer the latest stops quietly. The newer scan keeps the
        # progress bar running, and _loaded / _load_failed ignore anything from an older generation.
        try:
            # The stat is taken before the read: the manifest records the
            # stat of the file the scores were read from. Taken after, a
            # Stats.xml replaced in the gap would be recorded with the new
            # stat and old scores, and later refreshes would skip the
            # merge. Taken before, a change in the other direction only
            # costs a re-merge next time (the safe direction).
            stats_stat = stats_file.stat()
            scores = stats_index(stats_file)
            # One scandir walk (proposal 0018, §4.2): the entry stat
            # results are the manifest comparison, so no second stat call.
            # A file whose stat fails is skipped, the way is_file() used
            # to skip it — it is not in the scan at all.
            scanned = []
            with os.scandir(cache) as entries:
                for entry in entries:
                    if not entry.is_file():
                        continue
                    try:
                        scanned.append((entry.name, entry.stat()))
                    except OSError:
                        continue
            total = len(scanned)
            if self._load_is_stale(generation):
                # Superseded before the first file: queue nothing, not even
                # the progress report below.
                return
            # The total is known before any file is parsed: report it at once
            # so the bar can go determinate, then report as the loop goes.
            self._load_results.put(("progress", 0, total, generation))
            # The Edit fallback index is built once for the whole scan and
            # shared by every file's parse, so the fallback never rescans
            # the scores dict per undescribed Edit chart (issue #203).
            edit_index = edit_fallback_index(scores)
            # The incremental path (proposal 0018): the manifest is read
            # first, and the snapshot only when the manifest loaded — the
            # snapshot read is the expensive one, and a missing manifest
            # already means a full parse. A bare test instance without a
            # manifest store scans the same way (getattr, like the
            # _snapshot_* reads below).
            manifest_store = getattr(self, "manifest_store", None)
            manifest_result = (manifest_store.read(cache, stats_file)
                               if manifest_store is not None else None)
            snapshot_result = None
            incremental = False
            if manifest_result is not None and manifest_result.loaded:
                snapshot_result = self.snapshot_store.read(cache, stats_file)
                incremental = (snapshot_result.loaded
                               and _manifest_covers_snapshot(
                                   manifest_result.entries,
                                   snapshot_result.rows))
            stats_changed = (incremental
                             and (manifest_result.stats_mtime_ns
                                  != stats_stat.st_mtime_ns
                                  or manifest_result.stats_size
                                  != stats_stat.st_size))
            if incremental:
                # Group the snapshot's rows by song directory, in snapshot
                # order, and find the song directories two files claim:
                # both of those files are always re-parsed, so no rows are
                # lost to a duplicated cache file (proposal 0018, §4.2).
                groups = {}
                for row in snapshot_result.rows:
                    groups.setdefault(row["Course path"], []).append(row)
                claimed = {}
                for name, entry in manifest_result.entries.items():
                    if entry["rows"] > 0:
                        claimed.setdefault(entry["song_dir"], []).append(name)
                duplicate_dirs = {song_dir for song_dir, names in claimed.items()
                                  if len(names) > 1}
            rows = []
            skipped_files = 0
            files_without_charts = 0
            skipped_blocks = 0
            reparsed_files = 0
            reused_files = 0
            new_entries = {}
            # Phase 1 — decide (proposal 0020, §4.2): the reuse-or-parse
            # decision for every scanned file, in walk order. Reused
            # files hand their snapshot rows over at once; the rest
            # join the parse list with their scan index, which is what
            # the pool results are sorted back into. The parse itself
            # moves to phase 2, so the pool path never interleaves
            # parsing with deciding.
            reused_rows = {}
            to_parse = []
            for index, (name, stat) in enumerate(scanned, start=1):
                if self._load_is_stale(generation):
                    return
                entry = (manifest_result.entries.get(name)
                         if incremental else None)
                if (entry is not None
                        and entry["mtime_ns"] == stat.st_mtime_ns
                        and entry["size"] == stat.st_size
                        and entry["song_dir"] not in duplicate_dirs
                        and (entry["rows"] == 0
                             or len(groups.get(entry["song_dir"], ()))
                             == entry["rows"])):
                    # Unchanged file, uniquely claimed, and the snapshot
                    # group for its song holds exactly the rows the
                    # manifest recorded for this file — those are the rows
                    # reused. The group can hold more: a newer file for the
                    # same song can land in the snapshot while the manifest
                    # write fails, and the stale manifest still claims the
                    # old file alone — the coverage check compares
                    # song-directory sets, not which files claim them, so
                    # it cannot see that. The zero-row exemption matters:
                    # a zero-row record's "" group can legitimately be
                    # non-empty (another file's rows with no
                    # #SONGFILENAME), which the guard below handles.
                    # A zero-row record claims nothing, so it extends no
                    # rows — its recorded directory is "" and another
                    # file's rows can carry that same directory (a cache
                    # file with no #SONGFILENAME), which reusing here
                    # would duplicate.
                    if entry["rows"] > 0:
                        reused_rows[index] = groups.get(entry["song_dir"], [])
                    if entry["rows"] == 0:
                        files_without_charts += 1
                    skipped_blocks += entry["skipped_blocks"]
                    reused_files += 1
                    new_entries[name] = entry
                else:
                    to_parse.append((index, name, stat))
            # Phase 2 — parse the list, serially or through the pool
            # (proposal 0020, §4.2). A superseded scan returns here
            # without delivering, the way the old loop returned
            # mid-loop. reparsed_files counts every file the parse was
            # attempted on, failed or not, as the old loop did.
            parsed = self._parse_files(to_parse, cache, scores, edit_index,
                                       generation, reused_files, total)
            if parsed is None:
                return
            parsed_rows, skipped_files = parsed
            reparsed_files = len(to_parse)
            # Phase 3 — assemble in walk order (proposal 0020, D3): the
            # pool's results arrive unordered, so the merge reads them
            # back by scan index — reused rows and parsed rows
            # interleave exactly as the old single loop extended them.
            for index, (name, stat) in enumerate(scanned, start=1):
                if index in reused_rows:
                    rows.extend(reused_rows[index])
                elif index in parsed_rows:
                    chart_rows, blocks = parsed_rows[index]
                    skipped_blocks += blocks
                    if not chart_rows:
                        files_without_charts += 1
                    rows.extend(chart_rows)
                    # The song directory the file's rows carry, or ""
                    # when the file produced no rows (proposal 0018,
                    # §4.1): a zero-row record claims nothing.
                    song_dir = chart_rows[0]["Course path"] if chart_rows else ""
                    new_entries[name] = {
                        "name": name, "mtime_ns": stat.st_mtime_ns,
                        "size": stat.st_size, "song_dir": song_dir,
                        "rows": len(chart_rows), "skipped_blocks": blocks,
                    }

            # A changed Stats.xml re-derives scores over all rows instead
            # of forcing a re-parse (proposal 0018, D3): Stats.xml changes
            # on every play session, so a re-parse here would make the
            # manifest useless in practice. Fresh rows were already scored
            # inline by the parse, so merging them again is a no-op.
            if stats_changed:
                merge_scores(rows, scores, edit_index)
            nested_song_tree = looks_like_song_tree(cache) if not scanned else False
            cache_error = ""
            manifest_error = ""
            # The generation check and the snapshot write happen under one lock. Without it, an older
            # scan that passed the check could still be writing after a newer scan had written its
            # own snapshot, leaving the older data on disk.
            with self._snapshot_lock:
                if self._load_is_stale(generation):
                    return
                # The bar is already full here; name the phase so the tail
                # of the load does not look like a stall.
                self._load_results.put(("phase", "Saving snapshot…", generation))
                try:
                    refreshed_at = self.snapshot_store.write(
                        cache, stats_file, rows, len(scanned), skipped_files,
                        files_without_charts, nested_song_tree, skipped_blocks)
                except (OSError, TypeError, ValueError) as exc:
                    refreshed_at = ""
                    cache_error = str(exc)
                else:
                    # The manifest is written only if the snapshot write
                    # succeeded, under the same lock (proposal 0018,
                    # §4.2). A failed manifest write leaves the previous
                    # manifest in place and the next refresh reuses it
                    # (Revision 1); the failure is reported through
                    # manifest_error, naming the file that failed — the
                    # snapshot was saved, so it must not be reported
                    # through cache_error.
                    if manifest_store is not None:
                        try:
                            manifest_store.write(
                                cache, stats_file, stats_stat.st_mtime_ns,
                                stats_stat.st_size, new_entries)
                        except (OSError, TypeError, ValueError) as exc:
                            manifest_error = f"library_cache_manifest.json: {exc}"

            # Hand the result to the main thread through the queue. Calling Tk
            # (root.after) from this worker thread is not guaranteed safe.
            delivery = {
                "skipped_files": skipped_files,
                "files_without_charts": files_without_charts,
                "skipped_blocks": skipped_blocks,
                "nested_song_tree": nested_song_tree,
                "refreshed_at": refreshed_at,
                "cache_error": cache_error,
                "manifest_error": manifest_error,
                "source_paths": (str(cache), str(stats_file)),
                "generation": generation,
            }
            if incremental and reused_files:
                # The manifest was used and at least one file was reused:
                # _loaded names the re-parsed count (proposal 0018,
                # Revision 2). A full parse — or a refresh that reused
                # nothing — carries no count, so the old text stands.
                delivery["reparsed_files"] = reparsed_files
            self._load_results.put(("loaded", (rows, len(scanned)), delivery))
        except ET.ParseError as exc:
            self._load_results.put(("failed",
                                    f"Stats.xml is malformed or incomplete and could not be parsed.\n\n{exc}",
                                    generation))
        except OSError as exc:
            self._load_results.put(("failed",
                                    f"Could not read the selected cache folder or Stats.xml.\n\n{exc}",
                                    generation))
        except Exception as exc:
            self._load_results.put(("failed", str(exc), generation))

    def _report_parse_progress(self, done, total, generation):
        """Report parse progress on the old loop's cadence.

        Every 25 files, and on the last one: often enough for the bar
        to move smoothly, rarely enough to churn the queue. A scan
        superseded mid-parse stops reporting with it. `done` counts the
        files whose rows are in hand, reused files included.
        """
        if (done % 25 == 0 or done == total) and not self._load_is_stale(generation):
            self._load_results.put(("progress", done, total, generation))

    def _parse_files(self, to_parse, cache, scores, edit_index, generation,
                     done_base, total):
        """Parse the files the decision loop marked for parsing.

        Returns (parsed, skipped): parsed maps each file's scan index
        to (rows, skipped_blocks); skipped counts the files whose parse
        raised. Returns None when a newer Load superseded this scan
        mid-parse — the caller returns without delivering, the way the
        old loop returned mid-loop.

        The pool engages only when the list reaches POOL_MIN_FILES
        (proposal 0020, D5): below that the serial loop runs exactly
        as before, so a warm refresh that re-parses a handful of files
        never pays the spawn cost.
        """
        if len(to_parse) < POOL_MIN_FILES:
            return self._parse_files_serial(to_parse, cache, scores, edit_index,
                                            generation, done_base, total)
        return self._parse_files_pool(to_parse, cache, scores, edit_index,
                                      generation, done_base, total)

    def _parse_files_serial(self, to_parse, cache, scores, edit_index,
                            generation, done_base, total):
        """Parse the list one file at a time, exactly as the old loop did.

        The per-file try/except is the same: any failure parsing one
        file skips that file — a malformed cache must not kill the
        whole load (issue #205). The count reaches the load summary
        the way unreadable files already do. The catch is deliberately
        broad — the parse touches the file, the tag regex and the
        scores index, and no single file's failure mode should sink
        the scan. A failed file is not recorded in the manifest, so it
        is re-parsed on every refresh until it succeeds (proposal
        0018, §4.2). Calls the module-level parse_cache_file, so the
        counting wrappers in the manifest tests still see every parse.
        """
        parsed = {}
        skipped = 0
        for done, (index, name, stat) in enumerate(to_parse, start=1):
            if self._load_is_stale(generation):
                return None
            try:
                parsed[index] = parse_cache_file(cache / name, scores, edit_index)
            except Exception:
                skipped += 1
            self._report_parse_progress(done_base + done, total, generation)
        return parsed, skipped

    def _parse_files_pool(self, to_parse, cache, scores, edit_index,
                          generation, done_base, total):
        """Parse the list across a process pool (proposal 0020, §4.2).

        One future per file, collected with as_completed (D3): a slow
        file cannot stall the stream behind it, and the results are
        collected by scan index, so the merge in _load_worker reads
        them back in walk order. The scores travel once per worker
        through the pool initializer (D2). A pool that cannot start,
        or a worker that dies mid-parse, falls back to the serial loop
        for the files still outstanding (D6): a pool problem never
        loses the library or fails the load. The pool is shut down in
        the finally on every exit path (D4) — a parent that exits
        without shutting its pool down waits for the longest running
        task, which the sandbox measured at 10.2 s.
        """
        parsed = {}
        skipped = 0
        remaining = list(to_parse)
        stale = False
        pool_failed = False
        executor = None
        try:
            executor = ProcessPoolExecutor(
                max_workers=POOL_WORKERS,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=_init_pool_worker, initargs=(scores,))
            futures = {
                executor.submit(parse_cache_file_task, index, str(cache / name)):
                    (index, name, stat)
                for index, name, stat in to_parse
            }
            done = 0
            for future in as_completed(futures):
                if self._load_is_stale(generation):
                    stale = True
                    break
                item = futures[future]
                index, _name, _stat = item
                try:
                    _index, rows, blocks = future.result()
                except BrokenProcessPool:
                    # A worker died: stop collecting, shut the pool
                    # down, and re-parse the files still outstanding
                    # serially — including this one, whose result is
                    # unknown, not necessarily failed.
                    pool_failed = True
                    break
                except Exception:
                    # A per-file parse failure: counted and skipped,
                    # exactly as the serial loop counts it (issue #205).
                    skipped += 1
                else:
                    parsed[index] = (rows, blocks)
                remaining.remove(item)
                done += 1
                self._report_parse_progress(done_base + done, total, generation)
        except Exception:
            # The pool could not start at all (a spawn error, or a
            # frozen executable without freeze_support): the whole
            # outstanding list goes serial, so the load still delivers.
            pool_failed = True
        finally:
            if executor is not None:
                executor.shutdown(wait=not stale, cancel_futures=stale)
        if stale:
            return None
        if pool_failed:
            # The files the pool already resolved count as done, so the
            # fallback's progress continues from where the pool left off.
            resolved = len(parsed) + skipped
            serial = self._parse_files_serial(remaining, cache, scores,
                                              edit_index, generation,
                                              done_base + resolved, total)
            if serial is None:
                return None
            serial_parsed, serial_skipped = serial
            parsed.update(serial_parsed)
            skipped += serial_skipped
        return parsed, skipped

    def sync_scores(self):
        """Re-read Stats.xml and refresh the score fields of the loaded rows (issue #147).

        A manual File -> Sync scores action: the cache is not re-parsed, so
        a sync is ~4-5 s at 35k charts in the sandbox against ~20 s for a
        full Load / refresh. New songs still need a full refresh -- there
        is no row to merge their scores into.
        """
        if getattr(self, "_scan_in_flight", False):
            self.status.set("A library load is in progress. Wait for it to finish, then sync scores.")
            return
        if getattr(self, "_sync_in_flight", False):
            self.status.set("A scores sync is already in progress. Wait for it to finish, then sync again.")
            return
        if not self.rows:
            self.status.set("No library loaded. Load / refresh first, then sync scores.")
            return
        if not self.paths_match_loaded():
            self.status.set(
                "The selected data paths differ from the loaded library."
                " Load / refresh first, then sync scores.")
            return
        cache, stats = Path(self.cache_var.get()), Path(self.stats_var.get())
        if not stats.is_file():
            # Invalid paths open the Data paths dialog instead of an error box:
            # the fix is in the dialog, so that is where the user should be.
            self.dialog.open(note=invalid_paths_note(cache, stats))
            return
        self._sync_in_flight = True
        self.set_sync_menu_state("disabled")
        self.progress.start(12)
        self.status.set("Syncing scores from Stats.xml…")
        # Capture the rows and the generation on the main thread: a Load
        # pressed during the sync replaces self.rows and bumps the
        # generation, which the worker and the delivery both check.
        threading.Thread(
            target=self._sync_scores_worker,
            args=(cache, stats, self.rows, self._load_generation),
            daemon=True).start()

    def _sync_scores_worker(self, cache, stats_file, rows, generation):
        # A sync whose generation is no longer the latest stops quietly: a
        # Load pressed during it owns the rows and the snapshot now.
        try:
            # Stats.xml is the worker's input; if the game rewrites it
            # after the read, the merged scores are stale. Capture the
            # mtime before the read and check it again before persisting,
            # so a mid-sync change never lands in the snapshot silently.
            stats_mtime = Path(stats_file).stat().st_mtime
            scores = stats_index(stats_file)
        except ET.ParseError as exc:
            self._load_results.put(("scores_sync_failed",
                                    "Stats.xml is malformed or incomplete and "
                                    "could not be parsed.\n\n"
                                    f"{exc}",
                                    generation))
            return
        except OSError as exc:
            self._load_results.put(("scores_sync_failed",
                                    f"Could not read the selected Stats.xml.\n\n{exc}",
                                    generation))
            return
        except Exception as exc:
            # Anything else stats_index can raise (for example a LookupError
            # for an unsupported encoding in the XML declaration) must still
            # reach the main thread, or the progress bar spins forever.
            self._load_results.put(("scores_sync_failed",
                                    f"Could not sync scores from Stats.xml.\n\n{exc}",
                                    generation))
            return
        if not any("PercentDP" in entry for entry in scores.values()):
            # A Stats.xml with no actual scores (a fresh profile, the
            # wrong file, or HighScoreLists with no HighScore entries)
            # would blank every score and report success. Refuse the
            # sync instead, so nothing is changed.
            self._load_results.put(("scores_sync_failed",
                                    "The selected Stats.xml contains no scores.\n\n"
                                    "Check that you picked the right file — "
                                    "no scores were changed.",
                                    generation))
            return
        # The Edit fallback index is built once for this sync and shared
        # by the match check and the merge, so the fallback never rescans
        # the scores dict per undescribed Edit row (issue #203).
        edit_index = edit_fallback_index(scores)
        if not any_scores_match(rows, scores, edit_index):
            # The Stats.xml has scores, but none for the songs in this
            # library (for example a profile from another install).
            # Merging it would blank every score and report success.
            # Refuse the sync instead, so nothing is changed.
            self._load_results.put(("scores_sync_failed",
                                    "The selected Stats.xml has no scores "
                                    "for the songs in this library.\n\n"
                                    "Check that you picked the right file — "
                                    "no scores were changed.",
                                    generation))
            return
        try:
            changed, changed_keys = merge_scores(rows, scores, edit_index)
        except Exception as exc:
            # A row with a non-text Course path / Type / Difficulty
            # would otherwise end the thread silently; deliver the
            # failure. (Chart and Score description are normalized in
            # _score_for_row, so they cannot raise here.)
            self._load_results.put(("scores_sync_failed",
                                    f"Could not sync scores from Stats.xml.\n\n{exc}",
                                    generation))
            return
        # The generation check and the snapshot write happen under one lock,
        # exactly like the scan worker's: without it, a sync that passed the
        # check could still be writing after a newer scan had written its
        # own snapshot, leaving the older data on disk.
        cache_error = ""
        refreshed_at = ""
        with self._snapshot_lock:
            if self._load_is_stale(generation):
                return
            try:
                current_mtime = Path(stats_file).stat().st_mtime
            except OSError:
                current_mtime = None
            if current_mtime != stats_mtime:
                # Stats.xml changed between the read and the snapshot
                # write: the merged scores are stale. Do not persist them;
                # the snapshot's stamp stays put, so the startup hint fires
                # and the user re-syncs for the latest scores.
                cache_error = ("Stats.xml changed during the sync. "
                               "Sync again for current scores.")
            else:
                try:
                    refreshed_at = self.snapshot_store.write(
                        cache, stats_file, rows,
                        getattr(self, "_snapshot_files", 0),
                        getattr(self, "_snapshot_skipped_files", 0),
                        getattr(self, "_snapshot_files_without_charts", 0),
                        getattr(self, "_snapshot_nested_song_tree", False),
                        getattr(self, "_snapshot_skipped_blocks", 0))
                except (OSError, TypeError, ValueError) as exc:
                    refreshed_at = ""
                    cache_error = str(exc)
        self._load_results.put(("scores_synced", (rows, changed, changed_keys), {
            "refreshed_at": refreshed_at,
            "cache_error": cache_error,
            "generation": generation,
        }))

    def _scores_synced(self, rows, changed, changed_keys=None, refreshed_at="",
                       cache_error="", generation=None):
        if generation is not None and self._load_is_stale(generation):
            # A Load superseded this sync: the sync is over, so clear the
            # flag, but the Load owns the progress bar, status line and menu.
            self._sync_in_flight = False
            # The merge already rewrote the rows in place: without this
            # the table would keep showing the old scores, and the next
            # sync would find nothing new to report (Greptile P1 on
            # PR #277, confirmed live by Claude's Lane A). Rebuild
            # everything from the current rows — self.rows, not the
            # passed rows, since a finished Load may have replaced the
            # list already. Only the table refreshes here.
            self.on_library_changed(self.rows, preserve_selection=True,
                                    changed_keys=None)
            return
        self._sync_in_flight = False
        self.set_sync_menu_state("normal")
        self.progress.stop()
        # Back to indeterminate for the next snapshot restore, which has no
        # total to count against.
        self.progress.configure(mode="indeterminate", value=0)
        self.rows = rows
        # The snapshot's stamp only moves when the save succeeded; a failed
        # save leaves the in-memory scores fresh but the snapshot stale.
        if refreshed_at:
            self.last_refreshed_at = refreshed_at
        if changed:
            noun = "chart" if changed == 1 else "charts"
            message = f"Scores synced · {changed:,} {noun} updated"
        else:
            message = "Scores are already up to date"
        if refreshed_at:
            message += f" · last refreshed {format_refresh_time(refreshed_at)}"
        self.status.set(message + ".")
        if cache_error:
            self.status.set(self.status.get() + f" Local snapshot not saved: {cache_error}")
        # Full re-insert for v1 (issue #147): the merge is the fast part,
        # and a targeted cell patch would have to decide what to do about
        # the scored-only filter and the count label. Preserve the
        # selection, which a full reload currently drops.
        # The table refresh (preserving the selection) arrives through
        # the callback. [CODE] Q2: the handlers' engine half moves in.
        # The changed set travels with it (Proposal 0022), so the table
        # rebuilds only the changed tuples.
        self.on_library_changed(rows, preserve_selection=True,
                                changed_keys=changed_keys)

    def _scores_sync_failed(self, message, generation=None):
        if generation is not None and self._load_is_stale(generation):
            # A Load superseded this sync: the sync is over, so clear the
            # flag, but the Load owns the progress bar, status line and menu.
            self._sync_in_flight = False
            # A merge that raised partway may already have rewritten some
            # rows in place (Claude's Lane A on PR #277, injected fault):
            # without this the table would keep showing the old scores,
            # and the next sync would find nothing new for those rows.
            # Rebuild everything from the current rows.
            self.on_library_changed(self.rows, preserve_selection=True,
                                    changed_keys=None)
            return
        self._sync_in_flight = False
        self.set_sync_menu_state("normal")
        self.progress.stop()
        self.progress.configure(mode="indeterminate", value=0)
        self.status.set("Could not sync scores.")
        # Same hazard as the stale branch above: a merge that raised
        # partway may already have rewritten some rows in place.
        self.on_library_changed(self.rows, preserve_selection=True,
                                changed_keys=None)
        messagebox.showerror("Could not sync scores", message)

    def _poll_load_results(self):
        # Runs on the main thread for the life of the window: deliver whatever
        # finished scans queued, then schedule the next poll. _loaded and
        # _load_failed drop results from superseded generations themselves.
        try:
            while True:
                result = self._load_results.get_nowait()
                if result[0] == "loaded":
                    _, args, kwargs = result
                    self._loaded(*args, **kwargs)
                elif result[0] == "scores_synced":
                    _, args, kwargs = result
                    self._scores_synced(*args, **kwargs)
                elif result[0] == "scores_sync_failed":
                    _, message, generation = result
                    self._scores_sync_failed(message, generation=generation)
                elif result[0] == "progress":
                    _, done, total, generation = result
                    self._show_load_progress(done, total, generation)
                elif result[0] == "phase":
                    _, text, generation = result
                    self._show_load_phase(text, generation)
                else:
                    _, message, generation = result
                    self._load_failed(message, generation=generation)
        except queue.Empty:
            pass
        finally:
            try:
                self.root.after(75, self._poll_load_results)
            except tk.TclError:
                pass

    def _show_load_progress(self, done, total, generation):
        """Show a scan's progress on the main thread: determinate bar, files done, ETA.

        The first message of a scan carries the total, which is when the bar
        can go determinate — until then it bounced while Stats.xml parsed.
        The ETA is a straight line from the average rate so far; it only
        appears once 50 files are done, so the first few files cannot make
        it jump around.
        """
        if generation is not None and self._load_is_stale(generation):
            return
        if total > 0:
            # ["mode"] comes back as a Tcl index object, not a str, so the
            # comparison needs str() — a bare == "determinate" never matches.
            if str(self.progress["mode"]) != "determinate":
                self.progress.stop()
                self.progress.configure(mode="determinate", maximum=total, value=0)
            self.progress["value"] = done
        text = f"Reading chart cache… {done:,} / {total:,} files"
        started = self._load_started_at
        if started is not None and done >= 50 and done < total:
            elapsed = time.monotonic() - started
            if elapsed > 0:
                remaining = elapsed * (total - done) / done
                text += f" · about {max(1, round(remaining))} s left"
        self.status.set(text)

    def _show_load_phase(self, text, generation):
        """Name a scan phase on the status line (e.g. the snapshot write)."""
        if generation is not None and self._load_is_stale(generation):
            return
        self.status.set(text)

    def _load_failed(self, message, generation=None):
        if generation is not None and self._load_is_stale(generation):
            return
        self.load_button.configure(state="normal")
        self._scan_in_flight = False
        self.set_sync_menu_state("normal")
        self.progress.stop()
        # Back to indeterminate for the next snapshot restore, which has no
        # total to count against.
        self.progress.configure(mode="indeterminate", value=0)
        self.status.set("Could not load library.")
        # A Load that started during a sync superseded it: the sync's
        # merge already rewrote the rows in place, and the table never
        # heard (Greptile P1 on PR #277, confirmed live by Claude's
        # Lane A). Rebuild everything from the current rows, so the
        # failed Load cannot strand the merged scores on screen.
        self.on_library_changed(self.rows, preserve_selection=True,
                                changed_keys=None)
        messagebox.showerror("Could not load library", message)

    def _loaded(self, rows, files, skipped_files=0, files_without_charts=0, skipped_blocks=0,
                nested_song_tree=False, refreshed_at="", cache_error="",
                from_cache=False, source_paths=None, generation=None,
                reparsed_files=None, manifest_error=""):
        if generation is not None and self._load_is_stale(generation):
            return
        self.load_button.configure(state="normal")
        self._scan_in_flight = False
        self.set_sync_menu_state("normal")
        self.progress.stop()
        # Back to indeterminate for the next snapshot restore, which has no
        # total to count against.
        self.progress.configure(mode="indeterminate", value=0)
        self.rows = rows
        # The scores sync re-saves the snapshot with the merged rows, so it
        # needs the scan's summary values; keep them alongside the rows.
        self._snapshot_files = files
        self._snapshot_skipped_files = skipped_files
        self._snapshot_files_without_charts = files_without_charts
        self._snapshot_nested_song_tree = nested_song_tree
        self._snapshot_skipped_blocks = skipped_blocks
        if source_paths:
            self.loaded_source_paths = source_paths
        self.last_refreshed_at = refreshed_at
        # The app-side part (reset the dropdowns, tell the Course Builder,
        # set the table's rows) arrives through the callback, in the same
        # position the dropdown reset occupied, so the table still refreshes
        # before the status text below. [CODE] Q2: the handlers' engine half
        # moves into the loader; the app keeps on_library_changed.
        self.on_library_changed(rows, preserve_selection=False)
        if from_cache:
            stamp = format_refresh_time(refreshed_at)
            self.status.set(f"Showing saved library snapshot · {len(rows):,} charts · last refreshed {stamp}.")
        elif files == 0:
            hint = " This looks like a regular Songs tree; select the flat Cache/Songs folder instead." \
                if nested_song_tree else " Select the flat Cache/Songs folder."
            self.status.set("No files found at this folder level." + hint)
        else:
            # A manifest-assisted refresh names the re-parsed count
            # (proposal 0018, Revision 2): "parsed N charts" would claim
            # charts were read that were copied forward from the snapshot,
            # so the word is replaced, not appended to. None means a full
            # parse, and the line stays exactly as it was.
            if reparsed_files is None:
                summary = f"Scanned {files:,} files · parsed {len(rows):,} charts"
            else:
                summary = (f"Scanned {files:,} files · re-parsed {reparsed_files:,} "
                           f"· {len(rows):,} charts in total")
            if skipped_files:
                summary += f" · skipped {skipped_files:,} unreadable"
            if files_without_charts:
                summary += f" · {files_without_charts:,} with no charts"
            if skipped_blocks:
                summary += f" · {skipped_blocks:,} chart blocks skipped (missing metadata)"
            self.status.set(summary + ".")
        if not from_cache and refreshed_at:
            self.status.set(
                self.status.get()
                + f" Snapshot refreshed {format_refresh_time(refreshed_at)}.")
        if not from_cache and cache_error:
            self.status.set(self.status.get() + f" Local snapshot not saved: {cache_error}")
        if not from_cache and manifest_error:
            # A manifest-only failure must not wear the snapshot's label:
            # the snapshot was saved, and the message says so.
            self.status.set(self.status.get()
                            + f" Local refresh manifest not saved: {manifest_error}")
