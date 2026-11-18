"""Where ITGmania's files are and how they are read and joined.

Reading Stats.xml, reading the cache, and joining the two.
"""

from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from itgmania_library.library_constants import GRADE_NAMES, RADAR_FIELDS, TAP_FIELDS, TECH_FIELDS
from itgmania_library.library_format import (
    format_bpm_display,
    number,
    parse_bpms,
    split_path,
    tag_map,
)


def stats_index(stats_file: Path) -> dict[tuple, dict]:
    root = ET.parse(stats_file).getroot()
    result: dict[tuple, dict] = {}
    song_scores = root.find("SongScores")
    if song_scores is None:
        return result
    for song in song_scores.findall("Song"):
        song_path = split_path(song.get("Dir", ""))
        for steps in song.findall("Steps"):
            steps_type = steps.get("StepsType", "").casefold()
            diff = steps.get("Difficulty", "").casefold()
            desc = (steps.get("Description") or "").strip().casefold()
            score_list = steps.find("HighScoreList")
            if score_list is None:
                continue
            scores = score_list.findall("HighScore")
            best = max(scores, key=lambda score: number(score.findtext("PercentDP")), default=None)
            best_data = {}
            if best is not None:
                best_data = {tag: best.findtext(tag, "") for tag in
                             ("Score", "Grade", "PercentDP", "MaxCombo", "DateTime")}
                taps = best.find("TapNoteScores")
                if taps is not None:
                    best_data.update({"tap_" + name: taps.findtext(name, "") for name in TAP_FIELDS})

            # Determine key: 4-tuple for Edit charts with a description, 3-tuple for non-Edit or empty description
            if diff == "edit" and desc:
                key = (song_path.casefold(), steps_type, diff, desc)
            else:
                key = (song_path.casefold(), steps_type, diff)

            entry = result.setdefault(key, {"plays": "0", "last_played": ""})
            plays = score_list.findtext("NumTimesPlayed", "0")
            if number(plays) > number(entry["plays"]):
                entry["plays"] = plays
            last_played = score_list.findtext("LastPlayed", "")
            if last_played > entry["last_played"]:
                entry["last_played"] = last_played
            # Several Stats.xml Song entries can normalize to the same key.
            # Merge them without letting a later, lower record replace the best.
            if best_data and ("PercentDP" not in entry or
                              number(best_data.get("PercentDP")) > number(entry.get("PercentDP"))):
                entry.update(best_data)
    return result


def _merged_edit_fallback(scores: dict, base_key: tuple[str, str, str]) -> dict:
    """Rebuild the shared Edit score used when the cache chart has no description.

    stats_index keeps described Edits apart, but a cache chart without a
    description cannot be matched to one of them. In that case keep the
    pre-isolation result: the best score entry, the highest play count and
    the latest last-played date across the song's Edit entries (including an
    undescribed entry stored under the plain 3-tuple key).
    """
    candidates = [entry for key, entry in scores.items()
                  if isinstance(key, tuple) and len(key) in (3, 4) and key[:3] == base_key]
    if not candidates:
        return {}
    scored = [entry for entry in candidates if "PercentDP" in entry]
    merged = dict(max(scored, key=lambda entry: number(entry.get("PercentDP")))
                  if scored else candidates[0])
    plays = candidates[0].get("plays", "0")
    last_played = candidates[0].get("last_played", "")
    for entry in candidates[1:]:
        if number(entry.get("plays")) > number(plays):
            plays = entry.get("plays", "0")
        if entry.get("last_played", "") > last_played:
            last_played = entry.get("last_played", "")
    merged["plays"] = plays
    merged["last_played"] = last_played
    return merged


def _score_for_chart(scores: dict, base_key: tuple[str, str, str],
                     difficulty: str, description: str) -> dict:
    """Return the best Stats.xml entry for one chart.

    This is the score lookup parse_cache_file uses, factored out so the
    scores-only sync can run it over already-parsed rows. `description` is
    the value the score is keyed on: for the parse it is the chart's
    #DESCRIPTION (falling back to #CHARTNAME); for a sync it is the row's
    carried "Score description" field, falling back to the Chart field
    for a row that lacks it (the schema bump to 4 discards snapshots
    written before the field existed).
    """
    diff = difficulty.casefold()
    chart = (description or "").strip()
    if diff == "edit" and chart:
        score = scores.get((*base_key, chart.casefold()))
        if score is None:
            # The Stats entry itself has no description: use its shared key.
            score = scores.get(base_key, {})
    elif diff == "edit":
        # The cache chart has no description: fall back to the shared
        # result across the song's Edit entries, described or not.
        score = _merged_edit_fallback(scores, base_key)
    else:
        score = scores.get(base_key, {})
    return score or {}


def _apply_score_fields(row: dict, score: dict) -> None:
    """Rewrite a row's score-derived fields from one Stats.xml entry.

    Touches only the score fields (Score, Grade, Best %, Plays,
    Last played, the TAP_FIELDS, Max combo); every other field is left
    as it is. A missing entry blanks them, the way the parse does for
    an unscored chart.
    """
    percent = number(score.get("PercentDP")) * 100
    row["Score"] = number(score.get("Score")) if score else ""
    row["Grade"] = GRADE_NAMES.get(score.get("Grade", ""), score.get("Grade", ""))
    row["Best %"] = round(percent, 2) if score else ""
    row["Plays"] = number(score.get("plays"))
    row["Last played"] = score.get("last_played", "")
    for name in TAP_FIELDS:
        row[name] = number(score.get("tap_" + name)) if score else ""
    row["Max combo"] = number(score.get("MaxCombo")) if score else ""


# The fields _apply_score_fields owns, used to count changed rows.
_SCORE_FIELDS = ("Score", "Grade", "Best %", "Plays", "Last played",
                 *TAP_FIELDS, "Max combo")


def _score_for_row(scores: dict, row: dict) -> dict:
    """Return the Stats.xml entry for one already-parsed row.

    The score key is re-derived from the row: the base key
    (Course path, Type, Difficulty), all casefolded, plus the scoring
    description the parse carried in the row ("Score description"),
    falling back to the row's Chart field for a row that lacks it.
    A hand-edited snapshot can carry a non-string "Score description"
    (the snapshot read only checks key presence). Treat it as absent
    so the lookup falls back to the Chart field instead of failing
    the whole sync on one bad row.
    """
    base_key = (
        row["Course path"].casefold(),
        row["Type"].casefold(),
        row["Difficulty"].casefold(),
    )
    score_description = row.get("Score description")
    if not isinstance(score_description, str):
        score_description = ""
    description = score_description or row["Chart"]
    return _score_for_chart(scores, base_key, row["Difficulty"], description)


def any_scores_match(rows: list[dict], scores: dict) -> bool:
    """True if at least one row finds a Stats.xml entry with an actual score.

    A Stats.xml can hold real scores that belong to another install:
    the index is non-empty and at least one entry carries a score, so
    the empty-scores refusal does not catch it, yet merging it would
    blank every score. The sync checks this first, so a file with no
    scores for this library is refused instead of merged. A row only
    counts as matching when its entry carries a PercentDP record: an
    entry with only plays/last_played (an empty HighScoreList) is not
    a score for the chart.
    """
    return any("PercentDP" in _score_for_row(scores, row) for row in rows)


def merge_scores(rows: list[dict], scores: dict) -> int:
    """Re-derive the score fields of already-parsed rows, in place.

    The score key is re-derived from each row: the base key
    (Course path, Type, Difficulty), all casefolded, plus the scoring
    description the parse carried in the row ("Score description"),
    falling back to the row's Chart field for a row that lacks it.
    Returns the number of rows whose score fields changed. Rows are
    never added or removed -- a song added to the cache has no row to
    merge into and still needs a full refresh (issue #147).

    The parse carries the scoring description in the row, so the merge
    looks up the same entry the parse did -- including for an Edit chart
    carrying both #DESCRIPTION and a different #CHARTNAME. The schema
    bump to 4 discards snapshots written before this field existed, so
    they rebuild with it; the Chart fallback is only a defensive path
    for a row that somehow lacks the field.
    """
    changed = 0
    for row in rows:
        before = tuple(row.get(field) for field in _SCORE_FIELDS)
        score = _score_for_row(scores, row)
        _apply_score_fields(row, score)
        if tuple(row.get(field) for field in _SCORE_FIELDS) != before:
            changed += 1
    return changed


def parse_cache_file(path: Path, scores: dict) -> tuple[list[dict], int]:
    """Parse a cache file into chart rows, and count skipped chart blocks.

    Returns (rows, skipped_blocks): skipped_blocks counts chart blocks
    dropped for missing #STEPSTYPE/#DIFFICULTY metadata (issue #18).
    """
    # Cache files are UTF-8 Simfile text; split away the song metadata before chart parsing.
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    chunks = re.split(r"(?m)^#NOTEDATA:;\s*\r?\n", text)
    song_tags = tag_map(chunks[0])
    song_file = song_tags.get("SONGFILENAME", "")
    song_dir = split_path(song_file)
    song_dir = song_dir.rsplit("/", 1)[0] if "/" in song_dir else ""
    pack = song_dir.split("/", 1)[0] if song_dir else ""
    song_bpm_bounds = parse_bpms(song_tags.get("BPMS"))
    song_display_tag = song_tags.get("DISPLAYBPM")
    # The media tags (Proposal 0011, stage 1), read once per song:
    # the chart rows below carry them as hidden keys. A missing tag
    # reads as "", the way a missing Time does.
    song_music = song_tags.get("MUSIC", "")
    song_banner = song_tags.get("BANNER", "")
    song_background = song_tags.get("BACKGROUND", "")
    song_jacket = song_tags.get("JACKET", "")
    song_cdtitle = song_tags.get("CDTITLE", "")
    sample_start_tag = song_tags.get("SAMPLESTART", "")
    sample_length_tag = song_tags.get("SAMPLELENGTH", "")
    song_sample_start = (number(sample_start_tag)
                         if sample_start_tag else "")
    song_sample_length = (number(sample_length_tag)
                          if sample_length_tag else "")
    rows = []
    skipped_blocks = 0
    for chunk in chunks[1:]:
        tags = tag_map(chunk)
        chart_type = tags.get("STEPSTYPE", "")
        difficulty = tags.get("DIFFICULTY", "")
        if not chart_type or not difficulty:
            skipped_blocks += 1
            continue
        chart_bounds = parse_bpms(tags.get("BPMS")) or song_bpm_bounds
        chart_min = chart_bounds[0] if chart_bounds else ""
        chart_max = chart_bounds[1] if chart_bounds else ""
        display_tag = tags.get("DISPLAYBPM") or song_display_tag
        bpm_display = format_bpm_display(display_tag, chart_min, chart_max)
        radar_values = tags.get("RADARVALUES", "").split(",")
        radar = {name: number(value) for name, value in zip(RADAR_FIELDS, radar_values)}
        tech = [number(v, -1) for v in tags.get("TECHCOUNTS", "").split(",")]
        display_name = tags.get("CHARTNAME") or tags.get("DESCRIPTION", "")
        # Stats.xml keys an Edit by its description. #DESCRIPTION is that field;
        # #CHARTNAME is only a fallback for caches where the description landed
        # there instead (older SSC loading), not a replacement for it.
        score_description = tags.get("DESCRIPTION", "").strip() or tags.get("CHARTNAME", "").strip()
        base_key = (song_dir.casefold(), chart_type.casefold(), difficulty.casefold())
        score = _score_for_chart(scores, base_key, difficulty, score_description)
        row = {
            "Title": song_tags.get("TITLE", path.stem),
            "Subtitle": song_tags.get("SUBTITLE", ""), "Artist": song_tags.get("ARTIST", ""),
            "Pack": pack, "Type": chart_type, "Difficulty": difficulty, "Course path": song_dir,
            "Meter": number(tags.get("METER")),
            "Time": number(song_tags.get("MUSICLENGTH")) if song_tags.get("MUSICLENGTH") else "",
            "BPM": bpm_display, "bpm_min": chart_min, "bpm_max": chart_max,
            "Chart": display_name,
            # The description the score is keyed on (#DESCRIPTION, falling
            # back to #CHARTNAME): the merge reads it back, so a both-tags
            # Edit looks up the same entry the parse did (issue #152).
            "Score description": score_description,
            # The media tags (Proposal 0011, stage 1): hidden row keys,
            # never columns. Music is the chart's effective value — a
            # chart-level #MUSIC override wins, else the song's; only
            # #MUSIC has a chart-level override, so the other six ride
            # the song's tags. SongMusic is the song's own #MUSIC,
            # carried on every chart row (issue #193): the media record
            # reads it instead of inferring the song's file from the
            # charts, which could not tell a shared override from the
            # song's own music.
            "Music": tags.get("MUSIC") or song_music,
            "SongMusic": song_music,
            "Banner": song_banner,
            "Background": song_background,
            "Jacket": song_jacket,
            "CDTitle": song_cdtitle,
            "SampleStart": song_sample_start,
            "SampleLength": song_sample_length,
            # ITGmania formats #PEAKNPS as player-separated sections (P1|P2); take player 1.
            "Peak NPS": number(tags.get("PEAKNPS", "").split("|")[0]) if tags.get("PEAKNPS") else "",
            "Taps/Holds": radar.get("TapsAndHolds", ""), "Jumps": radar.get("Jumps", ""),
            "Holds": radar.get("Holds", ""), "Rolls": radar.get("Rolls", ""),
            "Mines": radar.get("Mines", ""), "Hands": radar.get("Hands", ""),
            "Lifts": radar.get("Lifts", ""),
            **{name: tech[i] if i < len(tech) and tech[i] >= 0 else ""
               for i, name in enumerate(TECH_FIELDS)},
        }
        _apply_score_fields(row, score)
        rows.append(row)
    return rows, skipped_blocks


# The media fields whose image extensions stage 1 counts (Proposal
# 0011): the Pillow call is made with these numbers.
MEDIA_IMAGE_FIELDS = ("Banner", "Background", "Jacket")


def image_extension_counts(rows: list[dict]) -> dict[str, dict[str, int]]:
    """Count image-file extensions per media field, one count per song.

    Each song contributes once (its first row by "Course path"), so a
    16-chart song does not count sixteen times. The extension is the
    lowercased suffix of the row's value, or "" where the song has no
    file for that field; a non-string value (a hand-edited snapshot)
    counts as "".
    """
    counts = {field: {} for field in MEDIA_IMAGE_FIELDS}
    seen = set()
    for row in rows:
        song = row.get("Course path", "")
        if song in seen:
            continue
        seen.add(song)
        for field in MEDIA_IMAGE_FIELDS:
            value = row.get(field)
            suffix = (Path(value).suffix.casefold()
                      if isinstance(value, str) else "")
            counts[field][suffix] = counts[field].get(suffix, 0) + 1
    return counts


def looks_like_song_tree(cache: Path) -> bool:
    """Return whether the selected folder resembles Songs/Pack/Song/*.sm|*.ssc."""
    for pack in cache.iterdir():
        if not pack.is_dir():
            continue
        for song in pack.iterdir():
            if song.is_dir() and any(
                chart.is_file() and chart.suffix.casefold() in {".sm", ".ssc"}
                for chart in song.iterdir()
            ):
                return True
    return False


def cache_dir_candidates() -> list[Path]:
    """Usual ITGmania song-cache locations for this platform, best first.

    The cache lives under the engine's user-data root, which differs per
    platform (ITGmania v1.3.0, ArchHooks::MountUserFilesystems): Windows
    %APPDATA%\\ITGmania, macOS ~/Library/Application Support/ITGmania,
    Linux ~/.itgmania. The Windows entry is the default this app has
    always used.
    """
    # sys.platform (not os.name): pathlib dispatches on os.name, so keying
    # the Windows branch on it would make the branch untestable.
    if sys.platform == "win32":
        root = Path(os.getenv("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "ITGmania"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "ITGmania"
    else:
        root = Path.home() / ".itgmania"
    return [root / "Cache" / "Songs"]


def first_existing_directory(candidates) -> Path | None:
    """First candidate that is actually a directory, else None."""
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def invalid_paths_note(cache, stats):
    """The note naming whichever of the two paths cannot be used."""
    cache_ok, stats_ok = cache.is_dir(), stats.is_file()
    if cache_ok and stats_ok:
        return ""
    if not cache_ok and not stats_ok:
        return "The cache folder and Stats.xml were not found. Choose new paths."
    if not cache_ok:
        return "The cache folder was not found. Choose a new Cache / Songs folder."
    return "The Stats.xml file was not found. Choose a new Player Stats.xml."


def _normalized_source_path(path):
    """Normalize a source path for comparison (case, spelling, and ~)."""
    return os.path.normcase(os.path.abspath(os.path.expanduser(str(path))))


__all__ = [
    "any_scores_match",
    "cache_dir_candidates",
    "first_existing_directory",
    "invalid_paths_note",
    "looks_like_song_tree",
    "merge_scores",
    "parse_cache_file",
    "stats_index",
]
