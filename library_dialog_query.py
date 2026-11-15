"""The Advanced Search dialog <-> search-bar text."""

from __future__ import annotations

from library_constants import GRADE_OPTIONS
from library_format import format_duration
from library_search import (
    _quote_for_search,
    parse_numeric_bound,
    parse_search_query,
)


# --- Advanced Search dialog <-> search-bar text -------------------------------------------
# The dialog has boxes for only some filters. split_dialog_query() fills the boxes from the
# search bar and hands back everything the boxes cannot show exactly as "other", so applying
# the dialog never silently drops or changes a filter. build_dialog_query() is the reverse.

DIALOG_TEXT_FIELDS = ("title", "artist", "pack")
DIALOG_RANGE_FIELDS = ("meter", "bpm", "time", "peak_nps")
_DIALOG_RANGE_TOKEN_NAMES = {"meter": "meter", "bpm": "bpm", "time": "time", "peak_nps": "nps"}


def _has_quote_chars(text: str) -> bool:
    return any(char in text for char in '"\\')


def _format_dialog_token(field: str, value: str) -> str:
    """Write ``field:value`` so parse_search_query reads the same value back."""
    token = f"{field}:{value}"
    if not any(char.isspace() or char in '"\\' for char in token):
        return token
    if not _has_quote_chars(value):
        return f'{field}:"{value}"'
    return f"{field}:{_quote_for_search(value)}"


def _format_bound_number(value: float, is_duration: bool) -> str:
    if is_duration:
        return format_duration(value)
    return str(int(value)) if float(value).is_integer() else str(value)


def _absorb_into_dialog(slots: dict, field: str, value: str) -> bool:
    """Put one filter into a dialog box if the box can show it exactly; return whether it did."""
    if field in DIALOG_TEXT_FIELDS:
        if slots[field] or _has_quote_chars(value):
            return False
        slots[field] = value
        return True

    if field in DIALOG_RANGE_FIELDS:
        is_duration = field == "time"
        bound = parse_numeric_bound(value, is_duration=is_duration)
        if bound is None:
            return False
        numbers = bound[1:]
        # A time box shows whole seconds only; a fractional time would be rounded.
        if is_duration and not all(float(n).is_integer() for n in numbers):
            return False
        low, high = slots[field]
        op = bound[0]
        if op in ("range", "==") and not low and not high:
            new_low, new_high = (bound[1], bound[2]) if op == "range" else (bound[1], bound[1])
            slots[field] = [_format_bound_number(new_low, is_duration),
                            _format_bound_number(new_high, is_duration)]
            return True
        if op == ">=" and not low:
            slots[field][0] = _format_bound_number(bound[1], is_duration)
            return True
        if op == "<=" and not high:
            slots[field][1] = _format_bound_number(bound[1], is_duration)
            return True
        # Strict > and < have no box: the boxes mean >= and <=.
        return False

    if field == "grade":
        # The Min Grade box means "this grade or better" (>=) and exists once.
        if slots["grade"] or not value.startswith(">="):
            return False
        wanted = value[2:].strip().casefold()
        for option in GRADE_OPTIONS:
            if option.casefold() == wanted:
                slots["grade"] = option
                return True
        return False

    return False


def split_dialog_query(query: str) -> dict:
    """Split search-bar text into Advanced Search dialog box values plus leftovers.

    Returns a dict with free_text, title, artist, pack, grade (a grade label or ""), meter,
    bpm, time and peak_nps (each a (min, max) pair of strings, "" when unset), and other:
    search text for every filter the boxes cannot show exactly (for example plays:>=3,
    jacks:>0, grade:<B, meter:>10). build_dialog_query() adds ``other`` back unchanged.
    """
    parsed = parse_search_query(query)
    slots = {"title": "", "artist": "", "pack": "", "grade": "",
             **{name: ["", ""] for name in DIALOG_RANGE_FIELDS}}
    other = []
    for field, value in parsed["directives"]:
        if not _absorb_into_dialog(slots, field, value):
            other.append(_format_dialog_token(field, value))
    result = {"free_text": parsed["free_text"], **slots, "other": " ".join(other)}
    for name in DIALOG_RANGE_FIELDS:
        result[name] = tuple(slots[name])
    return result


def build_dialog_query(parts: dict) -> str:
    """Turn Advanced Search dialog box values (see split_dialog_query) into search-bar text."""
    def text(key: str) -> str:
        return str(parts.get(key) or "").strip()

    tokens = []
    if text("free_text"):
        tokens.append(text("free_text"))
    for field in DIALOG_TEXT_FIELDS:
        if text(field):
            tokens.append(_format_dialog_token(field, text(field)))
    for field in DIALOG_RANGE_FIELDS:
        low, high = (str(part or "").strip() for part in parts.get(field, ("", "")))
        name = _DIALOG_RANGE_TOKEN_NAMES[field]
        if low and high:
            tokens.append(f"{name}:{low}" if low == high else f"{name}:{low}-{high}")
        elif low:
            tokens.append(f"{name}:>={low}")
        elif high:
            tokens.append(f"{name}:<={high}")
    if text("grade") and text("grade") != "Any":
        tokens.append(f"grade:>={text('grade')}")
    if text("other"):
        tokens.append(text("other"))
    return " ".join(tokens)


__all__ = [
    "build_dialog_query",
    "split_dialog_query",
]
