"""Persistence — the snapshot store that owns library_cache.json, the
manifest store that owns library_cache_manifest.json, and the settings
store that owns settings.json."""

from __future__ import annotations

import copy
import dataclasses
import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

from itgmania_library.library_constants import APP_NAME, OLD_APP_NAME
from itgmania_library.library_geometry import parse_window_geometry, parse_window_position
from itgmania_library.library_sources import _normalized_source_path


# The library snapshot (proposal 0008): SnapshotStore owns library_cache.json.
LIBRARY_CACHE_SCHEMA_VERSION = 6

# The refresh manifest (proposal 0018): ManifestStore owns
# library_cache_manifest.json.
LIBRARY_CACHE_MANIFEST_FORMAT_VERSION = 1


def _is_valid_manifest_entry(item):
    """Whether one manifest file record has every field with the right types.

    A record is a plain dict (the snapshot's rows are plain dicts too):
    the file name, its mtime in nanoseconds and size in bytes, the song
    directory its rows carry ("" when the file produced no rows), the row
    count, and the skipped-blocks count. A mistyped or missing field means
    a hand-edited or damaged file, and the whole manifest is discarded.
    """
    if not isinstance(item, dict):
        return False
    if not isinstance(item.get("name"), str) or not item["name"]:
        return False
    if not isinstance(item.get("song_dir"), str):
        return False
    for key in ("mtime_ns", "size", "rows", "skipped_blocks"):
        value = item.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return False
    return True


def _is_valid_manifest_payload(payload):
    """Whether a manifest payload has the right version, paths, and records."""
    if not isinstance(payload, dict):
        return False
    # JSON true and 1.0 both compare equal to 1, so the version needs
    # the same integer-but-not-boolean check the other fields get.
    version = payload.get("format_version")
    if (not isinstance(version, int) or isinstance(version, bool)
            or version != LIBRARY_CACHE_MANIFEST_FORMAT_VERSION):
        return False
    if not isinstance(payload.get("cache_dir"), str):
        return False
    if not isinstance(payload.get("stats_file"), str):
        return False
    for key in ("stats_mtime_ns", "stats_size"):
        value = payload.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return False
    files = payload.get("files")
    if not isinstance(files, list):
        return False
    if not all(_is_valid_manifest_entry(item) for item in files):
        return False
    names = [item["name"] for item in files]
    return len(set(names)) == len(names)


def _nonnegative_int(value):
    """A counter value as read back from a snapshot, or 0 if it is not one."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _is_valid_row(row, headers):
    """Whether a snapshot row has every column and only JSON scalar values.

    The writer only ever writes strings, numbers, booleans, and nulls, so a
    list or dict value means a hand-edited or damaged file (issue #202);
    such a row loads today and shows wrong or blank values downstream
    (a dict Meter reads as 0). A scalar mistype (a numeric Title) renders
    as itself and is tolerated.
    """
    return (
        isinstance(row, dict)
        and all(key in row for key in (*headers, "Course path"))
        and all(
            isinstance(value, (str, int, float, bool)) or value is None
            for value in row.values()
        )
    )


def write_file_atomically(text, path):
    """Write text to a file atomically.

    The text goes to a pid/thread-unique temp file beside the target, which
    is then moved into place with os.replace; the temp file is removed in a
    finally, so a failed write leaves no litter. Serialization is the
    caller's job: the helper takes text, not a dict, so the settings file
    keeps indent=2 with default ASCII escaping and the snapshot keeps
    compact JSON with ensure_ascii=False.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


@dataclasses.dataclass
class SnapshotResult:
    """What SnapshotStore.read returns: the loaded rows, or the reason it could not load.

    Either loaded (rows, counters, refreshed_at, source_paths) or not loaded
    with a reason kind (missing / unreadable / invalid / paths_mismatch) and
    a detail string — str(exc) for unreadable, None otherwise. The app maps
    each reason kind to today's status text.
    """

    loaded: bool
    rows: list = dataclasses.field(default_factory=list)
    files: int = 0
    skipped_files: int = 0
    files_without_charts: int = 0
    skipped_blocks: int = 0
    nested_song_tree: bool = False
    refreshed_at: str = ""
    source_paths: tuple = ("", "")
    reason: str | None = None
    detail: str | None = None


class SnapshotStore:
    """Owns library_cache.json: the snapshot write, and the read with its five-branch validation.

    It never touches Tk, the app, or the status line. The app constructs one
    with the snapshot path (derived once from the settings path), hands scan
    results to write, and maps read's result onto the status line.
    """

    def __init__(self, snapshot_path, headers, schema_version=LIBRARY_CACHE_SCHEMA_VERSION):
        self.snapshot_path = Path(snapshot_path)
        self.headers = headers
        self.schema_version = schema_version

    def write(self, cache_dir, stats_file, rows, files, skipped_files,
              files_without_charts, nested_song_tree, skipped_blocks=0):
        """Write a scan's rows to the snapshot; returns refreshed_at.

        Raises OSError/TypeError/ValueError exactly as today: the worker
        catches them and reports the failure instead of delivering rows.
        Argument order matches _save_library_cache on main, default included.
        """
        refreshed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        payload = {
            "schema_version": self.schema_version,
            "cache_dir": str(cache_dir),
            "stats_file": str(stats_file),
            "refreshed_at": refreshed_at,
            "files": files,
            "skipped_files": skipped_files,
            "files_without_charts": files_without_charts,
            "skipped_blocks": skipped_blocks,
            "nested_song_tree": nested_song_tree,
            "rows": rows,
        }
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        write_file_atomically(text, self.snapshot_path)
        return refreshed_at

    def read(self, current_cache_dir, current_stats_file):
        """Read the snapshot back: the rows, or the reason it could not be loaded."""
        try:
            with self.snapshot_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            return SnapshotResult(loaded=False, reason="missing")
        except (OSError, ValueError, RecursionError) as exc:
            # ValueError covers UnicodeDecodeError and JSONDecodeError;
            # RecursionError covers a deeply nested file. FileNotFoundError
            # is caught first because it is a subclass of OSError.
            return SnapshotResult(loaded=False, reason="unreadable", detail=str(exc))

        valid_rows = isinstance(payload, dict) and isinstance(payload.get("rows"), list) \
            and all(_is_valid_row(row, self.headers) for row in payload["rows"])
        if (not valid_rows or payload.get("schema_version") != self.schema_version
                or not isinstance(payload.get("cache_dir"), str)
                or not isinstance(payload.get("stats_file"), str)):
            return SnapshotResult(loaded=False, reason="invalid")

        if not (
            _normalized_source_path(payload.get("cache_dir", ""))
            == _normalized_source_path(current_cache_dir)
            and _normalized_source_path(payload.get("stats_file", ""))
            == _normalized_source_path(current_stats_file)
        ):
            return SnapshotResult(loaded=False, reason="paths_mismatch")

        refreshed_at = payload.get("refreshed_at", "")
        return SnapshotResult(
            loaded=True,
            rows=payload["rows"],
            files=_nonnegative_int(payload.get("files")),
            skipped_files=_nonnegative_int(payload.get("skipped_files")),
            files_without_charts=_nonnegative_int(payload.get("files_without_charts")),
            skipped_blocks=_nonnegative_int(payload.get("skipped_blocks")),
            nested_song_tree=payload.get("nested_song_tree") is True,
            refreshed_at=refreshed_at if isinstance(refreshed_at, str) else "",
            source_paths=(payload["cache_dir"], payload["stats_file"]),
        )


@dataclasses.dataclass
class ManifestResult:
    """What ManifestStore.read returns: the usable records, or the reason it could not load.

    Either loaded (the per-file records by file name, and the Stats.xml
    mtime and size the scan recorded) or not loaded with a reason kind
    (missing / unreadable / invalid / paths_mismatch) and a detail string
    — str(exc) for unreadable, None otherwise. The loader maps every
    reason kind to "no manifest, full parse".
    """

    loaded: bool
    entries: dict = dataclasses.field(default_factory=dict)
    stats_mtime_ns: int = 0
    stats_size: int = 0
    reason: str | None = None
    detail: str | None = None


class ManifestStore:
    """Owns library_cache_manifest.json: the per-file record of the last scan.

    It never touches Tk, the app, or the snapshot. The loader hands it a
    scan's per-file records to write, and reads it back to decide which
    files a refresh can skip (proposal 0018). Records are plain dicts —
    the snapshot's rows are plain dicts too — keyed by file name within
    the flat cache folder.
    """

    def __init__(self, manifest_path):
        self.manifest_path = Path(manifest_path)

    def write(self, cache_dir, stats_file, stats_mtime_ns, stats_size, entries):
        """Write a scan's per-file records; entries maps file name to record.

        Raises OSError/TypeError/ValueError exactly as SnapshotStore.write
        does: the worker catches them and reports the failure instead of
        delivering rows. The previous manifest stays in place when the
        write fails (write_file_atomically replaces only on success), and
        the next refresh reuses it — see proposal 0018, Revision 1.
        """
        payload = {
            "format_version": LIBRARY_CACHE_MANIFEST_FORMAT_VERSION,
            "cache_dir": str(cache_dir),
            "stats_file": str(stats_file),
            "stats_mtime_ns": stats_mtime_ns,
            "stats_size": stats_size,
            # Sorted by file name: the walk order is arbitrary per run, so
            # an unsorted manifest would differ every refresh even when
            # nothing changed. The read builds a dict, so the order here
            # carries no meaning beyond a stable file.
            "files": [entries[name] for name in sorted(entries)],
        }
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        write_file_atomically(text, self.manifest_path)

    def read(self, current_cache_dir, current_stats_file):
        """Read the manifest back: the per-file records, or the reason it could not be loaded."""
        try:
            with self.manifest_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            return ManifestResult(loaded=False, reason="missing")
        except (OSError, ValueError, RecursionError) as exc:
            # ValueError covers UnicodeDecodeError and JSONDecodeError;
            # RecursionError covers a deeply nested file. FileNotFoundError
            # is caught first because it is a subclass of OSError.
            return ManifestResult(loaded=False, reason="unreadable", detail=str(exc))

        if not _is_valid_manifest_payload(payload):
            return ManifestResult(loaded=False, reason="invalid")

        if not (
            _normalized_source_path(payload.get("cache_dir", ""))
            == _normalized_source_path(current_cache_dir)
            and _normalized_source_path(payload.get("stats_file", ""))
            == _normalized_source_path(current_stats_file)
        ):
            return ManifestResult(loaded=False, reason="paths_mismatch")

        entries = {item["name"]: item for item in payload["files"]}
        return ManifestResult(
            loaded=True,
            entries=entries,
            stats_mtime_ns=payload["stats_mtime_ns"],
            stats_size=payload["stats_size"],
        )


def _settings_file_path():
    appdata = os.getenv("APPDATA")
    if appdata:
        config_root = Path(appdata)
    elif os.name == "nt":
        config_root = Path.home() / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        config_root = Path.home() / "Library" / "Application Support"
    else:
        config_root = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_root / APP_NAME / "settings.json"


def _migrate_config_dir(settings_path):
    """Move the old config dir to the new one once, if it is still there.

    The app was renamed (proposal 0015): the settings folder moved from
    OLD_APP_NAME to APP_NAME. On the first launch after the rename, rename
    the whole old folder so settings.json and library_cache.json come along
    untouched. Returns the settings path to use: the new one, or the old one
    when the rename fails (the old folder stays, and the next launch
    retries). When both folders exist the new one wins and the old one is
    left alone.
    """
    new_dir = settings_path.parent
    if new_dir.is_dir():
        return settings_path
    old_dir = new_dir.with_name(OLD_APP_NAME)
    if not old_dir.is_dir():
        return settings_path
    try:
        old_dir.rename(new_dir)
    except OSError:
        return old_dir / "settings.json"
    return settings_path


def _valid_column_width(value, column):
    try:
        width = int(value)
    except (TypeError, ValueError):
        return None
    return width if 55 <= width <= 2000 else None


def _valid_window_geometry(value, min_size):
    """The canonical geometry string to restore a dialog with, or None.

    The stored value must parse in full and be at least the dialog's
    minimum size — a smaller value (a 1x1 read before the window was
    ever shown, say) is rejected whole, position included — and comes
    back rebuilt in canonical form, so only ever a string Tk itself
    could have written reaches the window. Shared by the course window
    (issue #25) and the Advanced Search window (issue #98), which pass
    their own minimum sizes.
    """
    parsed = parse_window_geometry(value)
    if parsed is None:
        return None
    width, height, x, y = parsed
    min_width, min_height = min_size
    if width < min_width or height < min_height:
        return None
    # Rebuilt exactly as Tk writes a position: "+100", and "+-8" for a
    # negative coordinate. The shorter "-8" form is a different dialect —
    # Tk reads it as "8 pixels from the right edge" — so emitting it here
    # would move the window to the far side of the screen on restore.
    return f"{width}x{height}+{x}+{y}"


def _valid_window_position(value):
    """The canonical "+X+Y" string to restore a window's position with, or None.

    The position-only form (Proposal 0016): exactly two signed offsets, no
    size, so there is no minimum to check. Rebuilt as Tk writes a position,
    "+-8" for a negative coordinate, for the reason given above.
    """
    parsed = parse_window_position(value)
    if parsed is None:
        return None
    return f"+{parsed[0]}+{parsed[1]}"


class SettingsStore:
    """Owns settings.json: loading, the dedup baseline, and the atomic write.

    The app assembles the settings dict and reports failures on the status
    line; this store only reads, compares, and writes the file (proposal 0008).
    """

    def __init__(self, settings_path):
        self.settings_path = Path(settings_path)
        self._baseline = None
        self.last_read_error = None

    def load(self):
        """Read the settings file: the dict, or {} if it is missing or unusable.

        The baseline is seeded here from a deep copy of the loaded dict, so
        the returned dict and the baseline can never alias; a failed write
        leaves the baseline stale and the next save retries.
        """
        self.last_read_error = None
        try:
            with self.settings_path.open("r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("settings must be a JSON object")
        except FileNotFoundError:
            # First run: no file yet is normal, not a discarded settings file.
            data = {}
        except (OSError, ValueError, RecursionError) as exc:
            # ValueError covers UnicodeDecodeError and JSONDecodeError;
            # RecursionError covers a deeply nested file. The file existed
            # but could not be used, so the app runs on defaults.
            self.last_read_error = str(exc)
            data = {}
        self._baseline = copy.deepcopy(data)
        return data

    def save(self, settings):
        """Write the settings dict, unless it matches the last saved one.

        Raises OSError exactly as the app's writer did; the baseline updates
        only after a successful write, so a failed write retries next time.
        """
        if self._baseline == settings:
            return
        text = json.dumps(settings, indent=2)
        write_file_atomically(text, self.settings_path)
        # Snapshot by value: the settings dict holds the live column_order list, which the
        # column drag handler mutates in place, so keeping the dict itself would make the
        # next comparison compare that list against itself and skip a real change.
        self._baseline = copy.deepcopy(settings)


__all__ = [
    "LIBRARY_CACHE_MANIFEST_FORMAT_VERSION",
    "LIBRARY_CACHE_SCHEMA_VERSION",
    "ManifestResult",
    "ManifestStore",
    "SettingsStore",
    "SnapshotResult",
    "SnapshotStore",
    "write_file_atomically",
]
