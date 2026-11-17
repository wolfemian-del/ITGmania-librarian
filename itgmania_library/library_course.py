"""The .crs text format."""

from __future__ import annotations

import re


COURSE_UNSAFE_CHARS = (";", ":", "\r", "\n")


def course_song_line(course_path: str, difficulty: str) -> str:
    """Format one #SONG entry for a CRS file."""
    return f"#SONG:{course_path}:{difficulty}:;"


def course_song_lines(rows: list[dict]) -> list[str]:
    """Format #SONG lines from chart rows that already carry Course path and Difficulty."""
    return [course_song_line(row["Course path"], row["Difficulty"]) for row in rows]


def format_new_course(title: str, song_lines: list[str], newline: str = "\n") -> str:
    """Build a complete new CRS document body (including a trailing newline)."""
    lines = [f"#COURSE:{title};", *song_lines]
    return newline.join(lines) + newline


def _contains_unsafe_course_text(value: str) -> bool:
    return "//" in value or any(char in value for char in COURSE_UNSAFE_CHARS)


def validate_course_fields(rows: list[dict], title: str | None = None) -> str | None:
    """Return a human-readable error if course fields are invalid, else None.

    When ``title`` is provided (not None), a blank title is rejected. Pass
    ``title=None`` to skip title checks (e.g. append flows that do not set one).

    Does not decide mixed-type policy; callers that care about mixed chart types
    should inspect the rows themselves after this returns None.
    """
    if title is not None:
        cleaned = title.strip()
        if not cleaned:
            return "Enter a title for this course."
        if _contains_unsafe_course_text(cleaned):
            return "Course titles cannot contain semicolons, colons, newlines, or '//' comment markers."
    if not rows:
        return "Add at least one chart to the course."
    if any(not row.get("Course path") or not row.get("Difficulty") for row in rows):
        return "One or more selected charts are missing a song path or difficulty."
    if any(_contains_unsafe_course_text(str(row.get("Course path", ""))) for row in rows):
        return "Song paths cannot contain semicolons, colons, newlines, or '//' comment markers."
    if any(_contains_unsafe_course_text(str(row.get("Difficulty", ""))) for row in rows):
        return "Difficulties cannot contain semicolons, colons, newlines, or '//' comment markers."
    return None


def find_ambiguous_course_entries(entries: list[dict], library_rows: list[dict]) -> list[dict]:
    """Return the queued entries a .CRS line cannot pin to one specific chart.

    A #SONG line records only the song (its course path) and a difficulty word —
    not the chart type, and not which Edit chart. An entry is ambiguous when the
    library holds another chart the same line could equally mean:

    - a chart for the same song at the same difficulty in a different chart
      type, or
    - for an Edit entry, a second Edit chart for the same song and chart type
      (the line cannot say which Edit was picked).

    Entries come back in queue order, each distinct (path, difficulty, type)
    once, however many times it was queued. Difficulty and type comparisons
    ignore case, matching how the table's filters compare them.
    """
    by_song: dict[str, list[dict]] = {}
    for row in library_rows:
        by_song.setdefault(row.get("Course path", ""), []).append(row)

    def key_of(row):
        return (str(row.get("Difficulty", "")).strip().casefold(),
                str(row.get("Type", "")).strip().casefold())

    flagged = []
    seen = set()
    for entry in entries:
        identity = (entry.get("Course path", ""), *key_of(entry))
        if identity in seen:
            continue
        seen.add(identity)
        difficulty, chart_type = key_of(entry)
        sibling_keys = [key_of(sibling)
                        for sibling in by_song.get(entry.get("Course path", ""), [])]
        cross_type = any(diff == difficulty and other_type != chart_type
                         for diff, other_type in sibling_keys)
        same_type_edits = sum(1 for diff, other_type in sibling_keys
                              if diff == "edit" and other_type == chart_type)
        if cross_type or (difficulty == "edit" and same_type_edits > 1):
            flagged.append(entry)
    return flagged


def _strip_course_comments(text: str) -> str:
    """Return a copy of CRS text with ``//`` comments removed, for scanning only.

    ITGmania ignores everything from ``//`` to the end of the line. A backslash
    escapes the next character, so an escaped slash pair is not a comment,
    while a ``//`` following an escaped backslash still starts one. Newlines
    are kept, so the copy keeps the original line structure. Callers scan this
    copy but must write the original text/bytes when appending.
    """
    out = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            out.append(text[index:index + 2])
            index += 2
            continue
        if char == "/" and text[index + 1:index + 2] == "/":
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def parse_course_text(text: str) -> dict:
    """Parse CRS text into title, ordered song entries, and trailing-risk info.

    Returns a dict with:
      title: str | None
      songs: list of {path, difficulty, raw} in file order
      trailing_risk: 'MODS' | 'GAINSECONDS' | None
      has_course: bool
    """
    text = _strip_course_comments(text)
    course_match = re.search(r"#COURSE\s*:([^;]*);", text, re.IGNORECASE)
    title = course_match.group(1).strip() if course_match else None
    songs = []
    for match in re.finditer(
        r"#SONG\s*:([^:;\r\n]*):([^:;\r\n]*)(?::([^;]*))?;", text, re.IGNORECASE
    ):
        songs.append({
            "path": match.group(1).strip(),
            "difficulty": match.group(2).strip(),
            "raw": match.group(0),
        })
    song_starts = list(re.finditer(r"#(?:SONG|SONGSELECT)\s*:", text, re.IGNORECASE))
    trailing_risk = None
    if song_starts:
        trailing_risk = course_trailing_risk(text)
    return {
        "title": title,
        "songs": songs,
        "trailing_risk": trailing_risk,
        "has_course": course_match is not None,
    }


def course_trailing_risk(text: str) -> str | None:
    """Return 'MODS' or 'GAINSECONDS' if that directive follows the last #SONG or #SONGSELECT, else None."""
    text = _strip_course_comments(text)
    songs = list(re.finditer(r"#(?:SONG|SONGSELECT)\s*:", text, re.IGNORECASE))
    if not songs:
        return None
    risky = re.search(r"#(MODS|GAINSECONDS)\s*:", text[songs[-1].end():], re.IGNORECASE)
    if not risky:
        return None
    return risky.group(1).upper()


def course_append_bytes(existing: bytes, song_lines: list[str]) -> bytes:
    """Validate an existing CRS and return only the bytes safe to append."""
    text = existing.decode("utf-8-sig")
    parsed = parse_course_text(text)
    scan_text = _strip_course_comments(text)
    has_entries = bool(re.search(r"#(?:SONG|SONGSELECT)\s*:", scan_text, re.IGNORECASE))
    if not parsed["has_course"] or not has_entries:
        raise ValueError("The selected file must contain #COURSE and at least one #SONG or #SONGSELECT entry.")
    risk = parsed["trailing_risk"]
    if risk:
        raise ValueError(
            f"This course ends with #{risk}, which may affect the chart entries being appended. "
            "The existing course was left unchanged. Remove or resolve that directive in the course file, then try again."
        )
    if not song_lines:
        raise ValueError("Add at least one chart before appending to a course.")

    newline = b"\r\n" if b"\r\n" in existing else b"\n"
    prefix = newline if existing and not existing.endswith((b"\n", b"\r")) else b""
    return prefix + newline.join(line.encode("utf-8") for line in song_lines) + newline


__all__ = [
    "COURSE_UNSAFE_CHARS",
    "course_append_bytes",
    "course_song_line",
    "course_song_lines",
    "course_trailing_risk",
    "find_ambiguous_course_entries",
    "format_new_course",
    "parse_course_text",
    "validate_course_fields",
]
