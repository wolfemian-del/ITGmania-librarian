"""The search language.

Parsing a query, matching a chart against it, and rewriting its directives.
"""

from __future__ import annotations

import math
import shlex

from library_constants import (
    GRADE_NAMES,
    GRADE_RANK,
    RADAR_COUNT_FIELDS,
    TECH_FIELDS,
)


SEARCH_FIELD_ALIASES = {
    "m": "meter",
    "meter": "meter",
    "diff_meter": "meter",
    "bpm": "bpm",
    "tempo": "bpm",
    "time": "time",
    "len": "time",
    "length": "time",
    "title": "title",
    "t": "title",
    "artist": "artist",
    "a": "artist",
    "pack": "pack",
    "p": "pack",
    "chart": "chart",
    "c": "chart",
    "diff": "difficulty",
    "difficulty": "difficulty",
    "d": "difficulty",
    "type": "type",
    "mode": "type",
    "grade": "grade",
    "g": "grade",
    "score": "score",
    "percent": "percent",
    "pct": "percent",
    "plays": "plays",
    "nps": "peak_nps",
    "peak_nps": "peak_nps",
    "peaknps": "peak_nps",
    "jumps": "jumps",
    "jump": "jumps",
    "holds": "holds",
    "hold": "holds",
    "rolls": "rolls",
    "roll": "rolls",
    "mines": "mines",
    "mine": "mines",
    "hands": "hands",
    "hand": "hands",
    "lifts": "lifts",
    "lift": "lifts",
    "taps": "taps",
    "tap": "taps",
    "taps_holds": "taps",
    "tapsholds": "taps",
    "tapsandholds": "taps",
    "taps/holds": "taps",
    **{f.casefold(): f.casefold() for f in TECH_FIELDS},
}


# Fields whose directives take a numeric bound (meter, bpm, time, score,
# percent, plays, peak_nps, the radar counts and the tech counts). An
# empty value for one of these is unfinished typing, not a filter; a
# non-empty value that will not parse is unreadable (see
# find_unreadable_directives). Text fields are not in this set: an empty
# title: is a substring of everything, so it already matches.
NUMERIC_SEARCH_FIELDS = frozenset({
    "meter", "bpm", "time", "score", "percent", "plays", "peak_nps",
    *RADAR_COUNT_FIELDS,
    *(f.casefold() for f in TECH_FIELDS),
})


def parse_duration_seconds(value: str) -> float | None:
    """Parse a duration string in seconds (e.g. '120', '90.5') or mm:ss / hh:mm:ss."""
    value = str(value or "").strip()
    if not value:
        return None
    if ":" in value:
        parts = value.split(":")
        try:
            if len(parts) == 2:
                return float(parts[0]) * 60 + float(parts[1])
            elif len(parts) == 3:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        except (TypeError, ValueError):
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_numeric_bound(raw: str, is_duration: bool = False) -> tuple | None:
    """Parse an operator or range constraint into a normalized tuple.

    Returns:
      ('range', low, high)
      ('>', val)
      ('>=', val)
      ('<', val)
      ('<=', val)
      ('==', val)
    """
    raw = str(raw or "").strip()
    if not raw:
        return None

    def conv(s: str) -> float | None:
        if is_duration:
            return parse_duration_seconds(s)
        try:
            return float(s.strip())
        except (TypeError, ValueError):
            return None

    if raw.startswith(">="):
        v = conv(raw[2:])
        return (">=", v) if v is not None else None
    if raw.startswith("<="):
        v = conv(raw[2:])
        return ("<=", v) if v is not None else None
    if raw.startswith(">"):
        v = conv(raw[1:])
        return (">", v) if v is not None else None
    if raw.startswith("<"):
        v = conv(raw[1:])
        return ("<", v) if v is not None else None
    if raw.startswith("="):
        v = conv(raw[1:])
        return ("==", v) if v is not None else None

    if ".." in raw:
        parts = raw.split("..", 1)
        low, high = conv(parts[0]), conv(parts[1])
        if low is not None and high is not None:
            return ("range", min(low, high), max(low, high))

    if "-" in raw and not raw.startswith("-"):
        parts = raw.split("-", 1)
        low, high = conv(parts[0]), conv(parts[1])
        if low is not None and high is not None:
            return ("range", min(low, high), max(low, high))

    v = conv(raw)
    return ("==", v) if v is not None else None


def _compare_bound(bound: tuple, actual) -> bool:
    if actual in (None, ""):
        return False
    try:
        val = float(actual)
    except (TypeError, ValueError):
        return False

    op = bound[0]
    if op == "range":
        return bound[1] <= val <= bound[2]
    target = bound[1]
    if op == ">":
        return val > target
    if op == ">=":
        return val >= target
    if op == "<":
        return val < target
    if op == "<=":
        return val <= target
    if op == "==":
        # NaN is not equal to itself, so a plain == test can never
        # select a NaN row; a "nan" target matches NaN values instead
        # (issue #171: the "nan" meter bar's filter is meter:nan).
        if math.isnan(target):
            return math.isnan(val)
        return val == target
    return False


def _compare_bpm_bound(bound: tuple, row: dict) -> bool:
    b_min = row.get("bpm_min")
    b_max = row.get("bpm_max")
    if b_min in (None, "") or b_max in (None, ""):
        return False
    try:
        b_min = float(b_min)
        b_max = float(b_max)
    except (TypeError, ValueError):
        return False

    op = bound[0]
    if op == "range":
        low, high = bound[1], bound[2]
        return b_max >= low and b_min <= high
    val = bound[1]
    if op == ">":
        return b_max > val
    if op == ">=":
        return b_max >= val
    if op == "<":
        return b_min < val
    if op == "<=":
        return b_min <= val
    if op == "==":
        return b_min <= val <= b_max
    return False


def split_search_query(query: str) -> list[str]:
    """Split a search query into tokens using shell-style double quotes for phrases.

    Only double quotes (") group multi-word phrases and protect colons or spaces.
    Single quotes and apostrophes (') are treated as normal text characters, so words
    with contractions (don't), possessives (Smiley's), or informal spellings (rock 'n' roll)
    remain intact and never trigger unclosed-quotation errors.
    """
    lex = shlex.shlex(query, posix=True)
    lex.whitespace_split = True
    lex.commenters = ""
    lex.quotes = '"'
    return list(lex)


def parse_search_query(query: str) -> dict:
    """Parse a query string into free-text terms and structured field criteria."""
    query = str(query or "").strip()
    if not query:
        return {"free_terms": [], "free_text": "", "directives": []}

    try:
        tokens = split_search_query(query)
    except ValueError:
        tokens = query.split()

    free_terms = []
    directives = []

    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if ":" in token:
            prefix, val = token.split(":", 1)
            field = prefix.strip().casefold()
            if field in SEARCH_FIELD_ALIASES:
                canonical = SEARCH_FIELD_ALIASES[field]
                val = val.strip().strip('"')
                directives.append((canonical, val))
                continue
        free_terms.append(token.casefold())

    free_text = " ".join(_quote_for_search(term) for term in free_terms)
    return {"free_terms": free_terms, "free_text": free_text, "directives": directives}


def match_chart_query(row: dict, query: str | dict) -> bool:
    """Return whether a chart row satisfies the search query."""
    criteria = query if isinstance(query, dict) else parse_search_query(query)

    # 1. Free terms match anywhere across main textual fields
    if criteria.get("free_terms"):
        text_corpus = " ".join(
            str(row.get(k, "")) for k in ("Title", "Subtitle", "Artist", "Pack", "Chart", "Type", "Difficulty")
        ).casefold()
        for term in criteria["free_terms"]:
            if term not in text_corpus:
                return False

    # 2. Field directives
    for field, raw_val in criteria.get("directives", []):
        if field in NUMERIC_SEARCH_FIELDS and not raw_val.strip():
            continue  # Empty numeric value: unfinished typing, not a filter
        if field == "meter":
            b = parse_numeric_bound(raw_val)
            if not b or not _compare_bound(b, row.get("Meter")):
                return False
        elif field == "bpm":
            b = parse_numeric_bound(raw_val)
            if not b or not _compare_bpm_bound(b, row):
                return False
        elif field == "time":
            b = parse_numeric_bound(raw_val, is_duration=True)
            if not b or not _compare_bound(b, row.get("Time")):
                return False
        elif field == "title":
            if raw_val.casefold() not in str(row.get("Title", "")).casefold():
                return False
        elif field == "artist":
            if raw_val.casefold() not in str(row.get("Artist", "")).casefold():
                return False
        elif field == "pack":
            if raw_val.casefold() not in str(row.get("Pack", "")).casefold():
                return False
        elif field == "chart":
            if raw_val.casefold() not in str(row.get("Chart", "")).casefold():
                return False
        elif field == "difficulty":
            if raw_val.casefold() not in str(row.get("Difficulty", "")).casefold():
                return False
        elif field == "type":
            if raw_val.casefold() not in str(row.get("Type", "")).casefold():
                return False
        elif field == "grade":
            chart_grade = str(row.get("Grade", "")).strip()
            if raw_val.startswith((">=", "<=", ">", "<")):
                if not chart_grade:
                    return False
                op = raw_val[:2] if raw_val[:2] in (">=", "<=") else raw_val[:1]
                target_grade = raw_val[len(op):].strip()
                target_key = target_grade.casefold()
                if target_key not in GRADE_RANK:
                    return False
                c_rank = GRADE_RANK.get(chart_grade.casefold())
                if c_rank is None:
                    return False
                t_rank = GRADE_RANK[target_key]
                # Lower GRADE_RANK index means higher/better grade
                if op == ">=" and not (c_rank <= t_rank):
                    return False
                if op == "<=" and not (c_rank >= t_rank):
                    return False
                if op == ">" and not (c_rank < t_rank):
                    return False
                if op == "<" and not (c_rank > t_rank):
                    return False
            else:
                if raw_val.casefold() != chart_grade.casefold():
                    return False
        elif field == "score":
            b = parse_numeric_bound(raw_val)
            if not b or not _compare_bound(b, row.get("Score")):
                return False
        elif field == "percent":
            b = parse_numeric_bound(raw_val)
            if not b or not _compare_bound(b, row.get("Best %")):
                return False
        elif field == "plays":
            b = parse_numeric_bound(raw_val)
            if not b or not _compare_bound(b, row.get("Plays")):
                return False
        elif field == "peak_nps":
            b = parse_numeric_bound(raw_val)
            if not b or not _compare_bound(b, row.get("Peak NPS")):
                return False
        elif field in RADAR_COUNT_FIELDS:
            b = parse_numeric_bound(raw_val)
            if not b or not _compare_bound(b, row.get(RADAR_COUNT_FIELDS[field])):
                return False
        elif field in {f.casefold() for f in TECH_FIELDS}:
            canonical_field = next(f for f in TECH_FIELDS if f.casefold() == field)
            b = parse_numeric_bound(raw_val)
            if not b or not _compare_bound(b, row.get(canonical_field)):
                return False

    return True


def _readable_grade(value: str) -> bool:
    """Whether a grade directive value can match a chart (issue #130).

    Mirrors the grade branch of match_chart_query, form by form: an
    operator value is readable when its target is a known grade (a display
    label or a Tier key); a bare value is readable only when it is a display
    label, which is what the matcher compares it against. A bare Tier key
    (grade:Tier06) is therefore unreadable — the table would be blank with
    no hint otherwise.
    """
    if value.startswith((">=", "<=", ">", "<")):
        target = value[2:] if value[:2] in (">=", "<=") else value[1:]
        return target.strip().casefold() in GRADE_RANK
    return value.strip().casefold() in {label.casefold() for label in GRADE_NAMES.values()}


def find_unreadable_directives(query: str | dict) -> list[str]:
    """Texts of directives whose non-empty value cannot be read.

    "meter:abc" is unreadable; "meter:" is not (an empty value is
    unfinished typing, skipped by match_chart_query). Replays the same
    checks the matcher uses: parse_numeric_bound for numeric fields
    (including durations for time:) and the grade reading above for
    grade:. Other text directives are never unreadable.
    """
    criteria = query if isinstance(query, dict) else parse_search_query(query)
    unreadable = []
    for field, raw_val in criteria.get("directives", []):
        if not raw_val.strip():
            continue
        if field in NUMERIC_SEARCH_FIELDS:
            if parse_numeric_bound(raw_val, is_duration=field == "time") is None:
                unreadable.append(f"{field}:{raw_val}")
        elif field == "grade" and not _readable_grade(raw_val):
            unreadable.append(f"{field}:{raw_val}")
    return unreadable


def filter_token_text(token) -> str:
    """Text form of a chart filter token: a plain string, or several values joined by spaces.

    A BPM range bar needs two directives (bpm:>=120 bpm:<140), so its token is a tuple of values.
    """
    if token is None:
        return ""
    if isinstance(token, str):
        return token
    return " ".join(token)


def filter_texts_match(first, second) -> bool:
    """Whether two chart filter texts select the same charts, however they were typed.

    Each text is one filter value or several joined by spaces ("11", ">=120 <140"); a bar's token tuple
    is accepted too. Every value is read the way the search reads it (parse_numeric_bound), so "11.0"
    matches "11" and "=11", and the order of the values does not matter ("<140 >=120" matches
    ">=120 <140"). Text that is not a number (a difficulty name) is compared ignoring case.
    """
    def readings(text):
        values = filter_token_text(text).split()
        keys = []
        for value in values:
            parsed = parse_numeric_bound(value)
            if parsed is None:
                keys.append(("text", value.casefold()))
            else:
                # NaN is not equal to itself, so a ("==", nan) key would
                # never equal another one; read it as the word "nan" instead.
                keys.append(tuple("nan" if isinstance(part, float) and math.isnan(part) else part
                                  for part in parsed))
        return sorted(keys, key=repr)

    return bool(filter_token_text(first).strip()) and readings(first) == readings(second)


def _needs_quotes(text: str) -> bool:
    return not text or any(char.isspace() or char in '"\\' for char in text)


def _quote_for_search(text: str) -> str:
    """Quote text for the search box so that split_search_query reads it back unchanged.

    Text with no spaces or quote/backslash characters stays as it is. Anything else goes in double quotes,
    with backslashes and double quotes escaped (the only escapes split_search_query honors inside them).
    """
    if not _needs_quotes(text):
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _format_search_token(token: str) -> str:
    """Write one token from split_search_query back as search text that reads as the same single token.

    A directive such as `pack:In The Groove` gets only its value quoted (pack:"In The Groove").
    Every other token, including free text that happens to contain a colon, is quoted as a whole,
    so a quoted phrase like "Dance Dance: Revolution" stays one phrase instead of splitting at the
    space before the colon.
    """
    prefix, colon, value = token.partition(":")
    if colon and not _needs_quotes(prefix) and SEARCH_FIELD_ALIASES.get(prefix.casefold()):
        return f"{prefix}:{_quote_for_search(value) if value else ''}"
    return _quote_for_search(token)


def replace_search_directive(query: str, directive_prefix: str, new_value: str | tuple[str, ...] | list[str] | None) -> str:
    """Replace or remove a directive in a search query, preserving free-text terms and other directives.

    Uses tokenization consistent with parse_search_query and SEARCH_FIELD_ALIASES.
    If new_value is None, removes any directives matching directive_prefix or its aliases.
    If new_value is a string, replaces the first matching directive in-place or appends it.
    If new_value is several values, they are written as several directives of that field
    (e.g. (">=120", "<140") gives "bpm:>=120 bpm:<140") in the first matching directive's place.
    Any other directives of that field are removed.
    """
    canonical_target = SEARCH_FIELD_ALIASES.get(directive_prefix.casefold(), directive_prefix.casefold())
    if new_value is None:
        new_values = []
    elif isinstance(new_value, str):
        new_values = [new_value]
    else:
        new_values = list(new_value)

    def _directive_tokens() -> list[str]:
        tokens_out = []
        for value in new_values:
            already_quoted = len(value) >= 2 and value.startswith('"') and value.endswith('"')
            text = value if already_quoted or not value else _quote_for_search(value)
            tokens_out.append(f"{canonical_target}:{text}")
        return tokens_out

    raw_query = str(query or "").strip()
    if not raw_query:
        return " ".join(_directive_tokens())

    try:
        tokens = split_search_query(raw_query)
        unbalanced = False
    except ValueError:
        # Unbalanced quote: parse_search_query splits on spaces in this case, so the words are raw text.
        tokens = raw_query.split()
        unbalanced = True

    # Each piece is (text, is_new_directive). Kept pieces are the query's own words.
    pieces = []
    replaced = False

    for token in tokens:
        if ":" in token:
            field = token.split(":", 1)[0].strip().casefold()
            if SEARCH_FIELD_ALIASES.get(field) == canonical_target:
                if not replaced and new_values:
                    pieces.extend((text, True) for text in _directive_tokens())
                    replaced = True
                continue
        pieces.append((token, False))

    if not replaced and new_values:
        pieces.extend((text, True) for text in _directive_tokens())

    if not unbalanced:
        # split_search_query took the quotes off, so each kept word is written back with quotes where it needs them.
        return " ".join(text if is_new else _format_search_token(text) for text, is_new in pieces)

    # Unbalanced case: keep the words as typed, so the search still reads the same way, unless that would
    # break the result: either a new value needs quotes (a space-separated search cannot hold it), or the
    # word that held the stray quote is gone and the rest is balanced, which the search would now read with
    # its quotes stripped. Then each kept word's quotes are escaped so it is still read as typed.
    typed = " ".join(text for text, _ in pieces)
    try:
        split_search_query(typed)
        typed_reads_as_typed = False
    except ValueError:
        typed_reads_as_typed = not any(is_new and _needs_quotes(text) for text, is_new in pieces)
    if typed_reads_as_typed:
        return typed
    return " ".join(text if is_new else _quote_for_search(text) for text, is_new in pieces)


# Chart metric name -> canonical search directive field that filters it.
CHART_FILTER_FIELDS = {"Difficulty": "difficulty", "Meter": "meter", "BPM": "bpm"}


def get_active_chart_filters(diff_filter: str, search_query: str) -> list[tuple[str, str]]:
    """Return [(metric_name, active_value), ...] for every chart metric currently filtering the table.

    Order is Difficulty, Meter, BPM. The difficulty combobox takes precedence over a diff: directive.
    When a field has several directives (bpm:>=120 bpm:<140) their values are joined with spaces,
    which is the same text filter_token_text gives for a BPM bar.
    """
    values: dict[str, list[str]] = {metric: [] for metric in CHART_FILTER_FIELDS}
    metric_by_field = {field: metric for metric, field in CHART_FILTER_FIELDS.items()}
    for field, val in parse_search_query(search_query).get("directives", []):
        if field in metric_by_field and val:
            values[metric_by_field[field]].append(val)

    active = []
    if diff_filter and diff_filter != "All difficulties":
        active.append(("Difficulty", diff_filter))
    elif values["Difficulty"]:
        active.append(("Difficulty", " ".join(values["Difficulty"])))
    for metric in ("Meter", "BPM"):
        if values[metric]:
            active.append((metric, " ".join(values[metric])))
    return active


__all__ = [
    "CHART_FILTER_FIELDS",
    "NUMERIC_SEARCH_FIELDS",
    "SEARCH_FIELD_ALIASES",
    "filter_texts_match",
    "filter_token_text",
    "find_unreadable_directives",
    "get_active_chart_filters",
    "match_chart_query",
    "parse_duration_seconds",
    "parse_numeric_bound",
    "parse_search_query",
    "replace_search_directive",
    "split_search_query",
]
