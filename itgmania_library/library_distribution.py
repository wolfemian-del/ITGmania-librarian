"""The distribution charts — aggregating the library into the meter,
difficulty, and BPM distributions the panel draws."""

import math
import statistics
from typing import NamedTuple

from itgmania_library.library_constants import DIFFICULTY_ORDER
from itgmania_library.library_search import (
    CHART_FILTER_FIELDS,
    _compare_bpm_bound,
    filter_texts_match,
    get_active_chart_filters,
    parse_numeric_bound,
    replace_search_directive,
)


__all__ = [
    "ChartBar",
    "aggregate_bpm_distribution",
    "aggregate_difficulty_distribution",
    "aggregate_meter_distribution",
    "chart_bar_at",
    "chart_bars",
    "chart_clear_decision",
    "chart_click_decision",
    "distribution_summary_stats",
]


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
        # The token is the full-precision value, so a click selects
        # exactly the rows the bar counts (issue #173); the label stays
        # the rounded display text. Integer meters are exact already,
        # so their token is the label.
        token = label if m_val.is_integer() else str(m_val)
        is_active = filter_texts_match(active_val, token) if active_val is not None else False
        result.append((label, count, token, is_active))

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
