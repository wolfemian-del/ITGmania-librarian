"""How values are displayed and sorted — the formatting and sort-key helpers."""

from __future__ import annotations

import math
import re
from datetime import datetime

from itgmania_library.library_constants import DIFFICULTY_ORDER, DIFFICULTY_RANK, GRADE_RANK


def number(value: str | None, default: float = 0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError, OverflowError):
        return default


def format_duration(seconds) -> str:
    """Format seconds as m:ss (or h:mm:ss); a non-finite or unparseable
    value reads as missing (blank), the way an empty Time already does."""
    try:
        total = float(seconds)
    except (TypeError, ValueError, OverflowError):
        return ""
    if not math.isfinite(total):
        return ""
    total = max(0, round(total))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def difficulty_sort_key(value):
    difficulty = str(value or "")
    return DIFFICULTY_RANK.get(difficulty.casefold(), len(DIFFICULTY_ORDER)), difficulty.casefold()


def grade_sort_key(value):
    """Sort grades by ITGmania tier order (S+ before S before S-, etc.)."""
    grade = str(value or "").strip()
    if not grade:
        return len(GRADE_RANK), ""
    return GRADE_RANK.get(grade.casefold(), len(GRADE_RANK)), grade.casefold()


def parse_bpms(value: str | None) -> tuple[float, float] | None:
    """Return (min, max) BPM from a #BPMS tag value, or None if unusable."""
    text = (value or "").strip()
    if not text:
        return None
    values = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            part = part.split("=", 1)[1].strip()
        try:
            val = float(part)
        except ValueError:
            continue
        # Only positive tempos count: negative values are warp markers,
        # 0 is unplayable, and NaN fails the > 0 comparison.
        if val > 0:
            values.append(val)
    if not values:
        return None
    return min(values), max(values)


def format_bpm_display(displaybpm: str | None, bpm_min, bpm_max) -> str:
    """Format a BPM cell from #DISPLAYBPM and/or parsed #BPMS bounds."""
    raw = (displaybpm or "").strip()
    if raw == "*":
        return "*"
    if raw:
        # Single value or explicit min:max (colon-separated).
        if ":" in raw:
            left, right = (piece.strip() for piece in raw.split(":", 1))
            try:
                lo, hi = float(left), float(right)
            except ValueError:
                pass
            else:
                return _format_bpm_pair(lo, hi)
        else:
            try:
                value = float(raw)
            except ValueError:
                pass
            else:
                return _format_bpm_number(value)
    if bpm_min is None or bpm_max is None or bpm_min == "" or bpm_max == "":
        return ""
    return _format_bpm_pair(float(bpm_min), float(bpm_max))


def format_refresh_time(value):
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return "unknown"


def _format_bpm_number(value: float) -> str:
    if not math.isfinite(value):
        return ""
    if value == int(value):
        return str(int(value))
    return f"{value:g}"


def _format_bpm_pair(lo: float, hi: float) -> str:
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return ""
    if lo == hi:
        return _format_bpm_number(lo)
    return f"{_format_bpm_number(lo)}–{_format_bpm_number(hi)}"


def bpm_sort_key(row: dict):
    """Sort by max BPM, then min BPM (fast charts with a slow gimmick rank high)."""
    bpm_max = row.get("bpm_max", "")
    bpm_min = row.get("bpm_min", "")
    if bpm_max in (None, "") or bpm_min in (None, ""):
        return (float("inf"), float("inf"))
    try:
        return (float(bpm_max), float(bpm_min))
    except (TypeError, ValueError, OverflowError):
        # A huge int from a hand-edited snapshot's JSON number
        # (10**10000) reads as missing, like an empty bound.
        return (float("inf"), float("inf"))


def tag_map(text: str) -> dict[str, str]:
    tags = {}
    # ITGmania MSD tags start with #KEY: and end at an unescaped ;.
    # Values may span lines (e.g. multi-segment #BPMS joined with ',\r\n' or ',\n').
    # A backslash escapes the next character (e.g. \; is a literal semicolon, \\ is a literal backslash).
    # Line breaks are consumed as whole CRLF/LF/CR units as long as they are not
    # followed by '#' (which begins a new tag line). Matching each unit in only
    # one way keeps the alternatives disjoint and parsing linear-time.
    for m in re.finditer(r"(?m)^#([^:;\r\n]+):((?:\\.|[^;\\\r\n]|(?:\r\n(?!#)|\r(?!\n)(?!#)|\n(?!#)))*);", text):
        raw_val = m.group(2).strip()
        decoded_val = re.sub(r"\\(.)", r"\1", raw_val) if "\\" in raw_val else raw_val
        tags[m.group(1).upper()] = decoded_val
    return tags


def split_path(value: str) -> str:
    """Normalize an ITGmania song path to its path below the Songs or AdditionalSongs directory.

    Cache entries usually use ``/Songs/Pack/Song/file.sm`` while Stats.xml
    commonly uses ``Songs/Pack/Song`` or ``AdditionalSongs/Pack/Song``. Some installations
    may instead store a filesystem-absolute path, so strip the prefix through the
    first component named Songs or AdditionalSongs wherever it occurs.
    """
    parts = value.replace("\\", "/").split("/")
    for index, part in enumerate(parts):
        if part.casefold() in ("songs", "additionalsongs"):
            return "/".join(parts[index + 1:]).strip("/")
    return "/".join(parts).strip("/")


__all__ = [
    "bpm_sort_key",
    "difficulty_sort_key",
    "format_bpm_display",
    "format_duration",
    "format_refresh_time",
    "grade_sort_key",
    "number",
    "parse_bpms",
    "split_path",
    "tag_map",
]
