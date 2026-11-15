"""Tk-independent parsing and formatting helpers for the ITGmania library, including the snapshot store (SnapshotStore) that owns library_cache.json and the settings store (SettingsStore) that owns settings.json."""

from __future__ import annotations

import copy
import dataclasses
import json
import math
import os
import statistics
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from library_constants import (
    COLUMN_GROUPS,
    DEFAULT_VISIBLE_COLUMNS,
    DEFAULT_VISIBLE_GROUPS,
    DIFFICULTY_ORDER,
    GRADE_NAMES,
    GRADE_OPTIONS,
    HEADERS,
    NUMERIC_COLUMNS,
    RADAR_COUNT_FIELDS,
    RADAR_FIELDS,
    TAP_FIELDS,
    TECH_FIELDS,
)
from library_format import (
    bpm_sort_key,
    difficulty_sort_key,
    format_bpm_display,
    format_duration,
    format_refresh_time,
    grade_sort_key,
    number,
    parse_bpms,
    split_path,
    tag_map,
)
from library_sources import (
    _normalized_source_path,
    any_scores_match,
    cache_dir_candidates,
    first_existing_directory,
    invalid_paths_note,
    looks_like_song_tree,
    merge_scores,
    parse_cache_file,
    stats_index,
)
from library_geometry import (
    declare_dpi_awareness,
    dpi_scale_factor,
    format_geometry,
    parse_course_geometry,
    scale_geometry,
    scale_pixels,
)
from library_course import (
    course_append_bytes,
    course_song_line,
    course_song_lines,
    course_trailing_risk,
    find_ambiguous_course_entries,
    format_new_course,
    parse_course_text,
    validate_course_fields,
)
from library_search import (
    CHART_FILTER_FIELDS,
    SEARCH_FIELD_ALIASES,
    _compare_bpm_bound,
    filter_texts_match,
    filter_token_text,
    find_unreadable_directives,
    get_active_chart_filters,
    match_chart_query,
    parse_numeric_bound,
    parse_search_query,
    replace_search_directive,
)
from library_dialog_query import (
    build_dialog_query,
    split_dialog_query,
)


__all__ = [
    "CHART_FILTER_FIELDS",
    "COLUMN_GROUPS",
    "DEFAULT_VISIBLE_COLUMNS",
    "DEFAULT_VISIBLE_GROUPS",
    "DIFFICULTY_ORDER",
    "GRADE_NAMES",
    "GRADE_OPTIONS",
    "HEADERS",
    "LIBRARY_CACHE_SCHEMA_VERSION",
    "NUMERIC_COLUMNS",
    "RADAR_COUNT_FIELDS",
    "RADAR_FIELDS",
    "SEARCH_FIELD_ALIASES",
    "TAP_FIELDS",
    "TECH_FIELDS",
    "ChartBar",
    "SettingsStore",
    "SnapshotResult",
    "SnapshotStore",
    "aggregate_bpm_distribution",
    "aggregate_difficulty_distribution",
    "aggregate_meter_distribution",
    "any_scores_match",
    "bpm_sort_key",
    "build_dialog_query",
    "cache_dir_candidates",
    "chart_bar_at",
    "chart_bars",
    "chart_clear_decision",
    "chart_click_decision",
    "course_append_bytes",
    "course_song_line",
    "course_song_lines",
    "course_trailing_risk",
    "declare_dpi_awareness",
    "difficulty_sort_key",
    "distribution_summary_stats",
    "dpi_scale_factor",
    "filter_texts_match",
    "filter_token_text",
    "find_ambiguous_course_entries",
    "find_unreadable_directives",
    "first_existing_directory",
    "format_bpm_display",
    "format_duration",
    "format_geometry",
    "format_new_course",
    "format_refresh_time",
    "get_active_chart_filters",
    "grade_sort_key",
    "invalid_paths_note",
    "looks_like_song_tree",
    "match_chart_query",
    "merge_scores",
    "number",
    "parse_bpms",
    "parse_cache_file",
    "parse_course_geometry",
    "parse_course_text",
    "parse_numeric_bound",
    "parse_search_query",
    "replace_search_directive",
    "scale_geometry",
    "scale_pixels",
    "split_dialog_query",
    "split_path",
    "stats_index",
    "tag_map",
    "validate_course_fields",
    "write_file_atomically",
]


# The library snapshot (proposal 0008): SnapshotStore owns library_cache.json.
LIBRARY_CACHE_SCHEMA_VERSION = 4


def _nonnegative_int(value):
    """A counter value as read back from a snapshot, or 0 if it is not one."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


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
            and all(isinstance(row, dict) and all(key in row for key in (*self.headers, "Course path"))
                    for row in payload["rows"])
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
    return config_root / "ITGmania Library Visualizer" / "settings.json"


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
    parsed = parse_course_geometry(value)
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


class ChartBar(NamedTuple):
    """One row of the distribution chart, in the chart's own coordinates, as the click handler needs it."""
    y_min: float
    y_max: float
    label: str
    token: str | tuple  # the filter value(s) a click applies; "" when the row cannot be clicked
    click_width: float = float("inf")  # a click to the right of this x does nothing


def chart_bars(items, *, min_click_fraction: float, bar_height: float, axis_headroom: float):
    """Turn aggregate rows into clickable chart bars, with the chart's x-axis limit.

    items are (label, count, token, is_active) in display order (the caller reverses the aggregate's
    order, as the window always has). Bar i is centred on position i: its y-extents are derived from
    the position and bar_height, with y_max as y_min + bar_height — the same arithmetic the window
    used to read back from the drawn bars (computing it as position + bar_height/2 can differ in the
    last digit). A row with no charts has nothing to filter to, so its token is blanked and it is not
    clickable, unless it is the active filter, which has to stay clickable so that clicking it again
    can switch it off. Returns (bars, axis_max).
    """
    max_count = max((count for _label, count, _token, _active in items), default=1)
    axis_max = max_count * axis_headroom
    min_click_width = axis_max * min_click_fraction
    bars = []
    for i, (label, count, token, is_active) in enumerate(items):
        y_min = i - bar_height / 2
        bars.append(ChartBar(
            y_min, y_min + bar_height, label,
            token if count > 0 or is_active else "", max(count, min_click_width)))
    return bars, axis_max


def chart_bar_at(bars, x, y):
    """The bar a chart click at data coordinates (x, y) lands on, or None.

    x and y are None when the click is outside the plot area (for example on a row label).
    A bar with no token (an empty row) is not clickable, and neither is a bar labelled "?",
    whatever its token: the Meter and BPM "?" rows (missing values) carry empty tokens anyway,
    but an unrecognised difficulty text passes through as its own token, so a difficulty
    literally named "?" would otherwise be clickable — the window's handler never allowed that.
    """
    if x is None or y is None:
        return None
    for bar in bars:
        if bar.y_min <= y <= bar.y_max and 0 <= x <= bar.click_width:
            return bar if bar.token and bar.label != "?" else None
    return None


def chart_click_decision(metric: str, token, diff_filter: str, query: str):
    """What a click on a chart bar writes: (difficulty, query), None for a variable it does not write.

    Difficulty clicks write the dropdown (the clicked difficulty, or "All difficulties" when the
    click toggles the active one off) and write the query only when removing a redundant diff
    directive changes it. Other metrics never write the dropdown and always write the query,
    applying the bar's token or removing it when the click toggles the active filter off.
    Whether the clicked filter is already active is read the way the window reads it today,
    so a hand-typed equivalent ("meter:11.0", "bpm:<140 bpm:>=120") still toggles off.
    """
    current = dict(get_active_chart_filters(diff_filter, query)).get(metric)
    already_active = current is not None and filter_texts_match(current, token)
    if metric == "Difficulty":
        new_query = replace_search_directive(query, "diff", None)
        return ("All difficulties" if already_active else token,
                new_query if new_query != query else None)
    return None, replace_search_directive(
        query, CHART_FILTER_FIELDS[metric], None if already_active else token)


def chart_clear_decision(diff_filter: str, query: str):
    """What clearing every chart filter writes: (difficulty, query), or None when nothing is active.

    None is the complete no-op: no chart filter is active, so nothing is written and nothing
    refreshes. Otherwise the query comes back with every active chart filter's directive
    stripped (and is written even when the stripped text equals the current one), and the
    difficulty is "All difficulties" when Difficulty is among the active filters, else None
    (the dropdown is not written).
    """
    active = get_active_chart_filters(diff_filter, query)
    if not active:
        return None
    stripped = query
    for metric, _value in active:
        stripped = replace_search_directive(stripped, CHART_FILTER_FIELDS[metric], None)
    difficulty = "All difficulties" if any(metric == "Difficulty" for metric, _ in active) else None
    return difficulty, stripped


def aggregate_meter_distribution(rows: list[dict], active_val: str | None = None) -> list[tuple[str, int, str, bool]]:
    """Aggregate row counts per meter level.

    Float meters like 11.0 are normalized to integer strings ("11"). parse_cache_file stores a chart with
    no METER tag as 0, so such charts get an ordinary "0" bar: the table shows 0 for them and meter:0
    finds them, which keeps the bar's number equal to the rows after clicking it. Only rows with no
    value at all or text that is not a number (not produced by parse_cache_file) are grouped into "?"
    at the end (non-interactive). NaN meters get one "nan" bar of their own: NaN is not equal to
    itself, so it cannot be a dict key, and one bar per NaN row would also double-count.
    Returns list of (label, count, filter_token, is_active).
    """
    counts: dict[str, int] = {}
    numeric_keys: dict[float, str] = {}
    missing_count = 0
    nan_count = 0

    for row in rows:
        meter_raw = row.get("Meter")
        if meter_raw in (None, ""):
            missing_count += 1
            continue
        try:
            m_val = float(meter_raw)
        except (TypeError, ValueError):
            missing_count += 1
            continue
        if math.isnan(m_val):
            nan_count += 1
            continue
        label = str(int(m_val)) if m_val.is_integer() else f"{m_val:g}"
        counts[label] = counts.get(label, 0) + 1
        numeric_keys[m_val] = label

    result = []
    for m_val in sorted(numeric_keys.keys()):
        label = numeric_keys[m_val]
        count = counts[label]
        is_active = filter_texts_match(active_val, label) if active_val is not None else False
        result.append((label, count, label, is_active))

    if nan_count > 0:
        result.append(("nan", nan_count, "nan",
                       filter_texts_match(active_val, "nan") if active_val is not None else False))

    if missing_count > 0:
        result.append(("?", missing_count, "", False))

    return result


def aggregate_difficulty_distribution(rows: list[dict], active_val: str | None = None) -> list[tuple[str, int, str, bool]]:
    """Aggregate row counts per difficulty tier in canonical DIFFICULTY_ORDER.

    Returns list of (label, count, filter_token, is_active).
    """
    counts: dict[str, int] = {diff: 0 for diff in DIFFICULTY_ORDER}
    extra_diffs: dict[str, int] = {}

    for row in rows:
        diff = str(row.get("Difficulty") or "").strip()
        matched = False
        for d in DIFFICULTY_ORDER:
            if diff.casefold() == d.casefold():
                counts[d] += 1
                matched = True
                break
        if not matched and diff:
            extra_diffs[diff] = extra_diffs.get(diff, 0) + 1

    result = []
    for diff in DIFFICULTY_ORDER:
        count = counts.get(diff, 0)
        is_active = (active_val.casefold() == diff.casefold()) if active_val else False
        result.append((diff, count, diff, is_active))

    for diff, count in extra_diffs.items():
        is_active = (active_val.casefold() == diff.casefold()) if active_val else False
        result.append((diff, count, diff, is_active))

    return result


# (bar label, bpm: directive values that select the bar). Each range is half-open [low, high), so a
# chart at exactly 140 BPM belongs to 140-159 only, and a chart at 139.5 belongs to 120-139.
BPM_BINS = (
    ("<120", ("<120",)),
    ("120-139", (">=120", "<140")),
    ("140-159", (">=140", "<160")),
    ("160-179", (">=160", "<180")),
    ("180-199", (">=180", "<200")),
    ("200+", (">=200",)),
)


def _bpm_range(row: dict) -> tuple[float, float] | None:
    """Return a row's (bpm_min, bpm_max), or None when either is missing or not a number."""
    try:
        low, high = row.get("bpm_min"), row.get("bpm_max")
        if low in (None, "") or high in (None, ""):
            return None
        return float(low), float(high)
    except (TypeError, ValueError):
        return None


def aggregate_bpm_distribution(
    rows: list[dict], active_val: str | None = None
) -> list[tuple[str, int, tuple[str, ...], bool]]:
    """Count charts per BPM range; a chart counts in every range its tempo span touches.

    A chart that runs 100-150 BPM is counted in <120, 120-139 and 140-159. Each bar is counted with
    the same test as the bpm: filter (_compare_bpm_bound) on the bar's own directives, so the number
    on a bar always equals the number of rows the table shows after clicking it. Bar counts therefore
    add up to more than the number of charts when some charts change tempo across ranges.

    Returns list of (label, count, filter_token, is_active). filter_token is a tuple of bpm:
    directive values; is_active compares its space-joined text with active_val.
    """
    bounds_by_label = {
        label: [parse_numeric_bound(value) for value in values] for label, values in BPM_BINS
    }
    counts = {label: 0 for label, _ in BPM_BINS}
    missing_count = 0

    for row in rows:
        if _bpm_range(row) is None:
            missing_count += 1
            continue
        for label, bounds in bounds_by_label.items():
            if all(_compare_bpm_bound(bound, row) for bound in bounds):
                counts[label] += 1

    result = []
    for label, values in BPM_BINS:
        is_active = bool(active_val) and filter_texts_match(active_val, values)
        result.append((label, counts[label], values, is_active))

    if missing_count > 0:
        result.append(("?", missing_count, "", False))

    return result


def distribution_summary_stats(metric: str, rows: list[dict]) -> str:
    """Calculate summary statistics for the active distribution metric on current visible rows.

    For multimodal data, the lowest mode is selected deterministically.
    """
    if not rows:
        return "0 charts"

    if metric == "Meter":
        vals = []
        for r in rows:
            m = r.get("Meter")
            if m not in (None, ""):
                try:
                    v = float(m)
                    # Non-finite values would make the mean/median read
                    # "inf"/"nan"; they are excluded, like missing ones.
                    if math.isfinite(v):
                        vals.append(int(v) if v.is_integer() else v)
                except (TypeError, ValueError):
                    pass
        if not vals:
            return f"{len(rows):,} charts"
        mean_val = statistics.mean(vals)
        med_val = statistics.median(vals)
        modes = statistics.multimode(vals)
        mode_val = min(modes)
        return f"{len(rows):,} charts · Median: {med_val:g} · Mean: {mean_val:.1f} · Mode: {mode_val:g}"

    if metric == "Difficulty":
        diff_counts = {d: 0 for d in DIFFICULTY_ORDER}
        for r in rows:
            d = str(r.get("Difficulty") or "")
            for c in DIFFICULTY_ORDER:
                if d.casefold() == c.casefold():
                    diff_counts[c] += 1
                    break
        sorted_diffs = sorted(diff_counts.items(), key=lambda item: (-item[1], DIFFICULTY_ORDER.index(item[0])))
        top_diff, top_count = sorted_diffs[0]
        if top_count > 0:
            return f"{len(rows):,} charts · Mode: {top_diff} ({top_count:,})"
        return f"{len(rows):,} charts"

    if metric == "BPM":
        vals = []
        for r in rows:
            b = r.get("bpm_max")
            if b not in (None, ""):
                try:
                    v = float(b)
                    # As for Meter: non-finite tempos would read "inf"/"nan".
                    if math.isfinite(v):
                        vals.append(v)
                except (TypeError, ValueError):
                    pass
        if not vals:
            return f"{len(rows):,} charts"
        mean_val = statistics.mean(vals)
        med_val = statistics.median(vals)
        return (f"{len(rows):,} charts · Median: {med_val:.0f} · Mean: {mean_val:.0f}\n"
                "A chart counts in every range its tempo touches.")

    return f"{len(rows):,} charts"
