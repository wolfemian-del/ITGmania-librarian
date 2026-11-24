#!/usr/bin/env python3
# Reviewer tool, kept in tools/ and not shipped with the app. Needs Tkinter and a
# display (on a headless machine: `xvfb-run -a python3 tools/probe_changed_keys.py`).
"""Differential live-table probe for the changed-keys refresh (Proposal 0022).

Drives the REAL LibraryApp (real loader, filter and table, a real ttk.Treeview) over
a synthetic library written to a temp folder, and after every step records what the
tree visibly shows: cell values, row tags and selection. An oracle then checks every
visible row against what the loader's in-memory row says it should show
(`_display_tuple`), and reports stale cells, stale tags and wrong row counts.

Run it once per commit, then compare the two traces with compare_probe_traces.py:

    git worktree add /tmp/before <commit-before-the-change>
    python tools/probe_changed_keys.py --repo /tmp/before --work /tmp/w1 \
        --out before.json
    python tools/probe_changed_keys.py --repo . --work /tmp/w2 --out after.json
    python tools/compare_probe_traces.py before.json after.json

--repo is the checkout whose `itgmania_library` package is driven; --work is a scratch
folder (deleted and recreated); --out is the JSON trace. Nothing in your real settings,
cache or Stats.xml is read or written: a temporary settings file points the app at the
synthetic data.

--scenario main (default, 35 steps): load, sorts, selection and tint, filter edits,
syncs (including changes to hidden rows and two rows sharing one chart key), a sync
delivered after a sort, reloads, and a sync that fails part-way.
--scenario retry (5 steps): a sync result is queued, the user starts a Load, the sync
result is dropped as stale, the Load fails, and the user syncs again. A table that
shows old scores here, with the status line reading "Scores are already up to date",
has lost a change the loader already merged into memory.

This drives private names (`_display_tuple`, `_tree_item_rows`, `_load_results`,
`_settings_file_path`); if a refactor renames one, fix the probe rather than the app.
"""
import argparse
import copy
import json
import os
import shutil
import sys
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument("--repo", required=True)
parser.add_argument("--work", required=True)
parser.add_argument("--out", required=True)
parser.add_argument("--scenario", choices=("main", "retry"), default="main")
args = parser.parse_args()
sys.path.insert(0, args.repo)

from itgmania_library import library_librarian as app_mod  # noqa: E402
from itgmania_library import library_sources as S  # noqa: E402
from itgmania_library import library_table as T  # noqa: E402

REAL_DISPLAY = T._display_tuple
CALLS = {"n": 0}


def counting_display_tuple(row, selected=False):
    CALLS["n"] += 1
    return REAL_DISPLAY(row, selected)


T._display_tuple = counting_display_tuple

WORK = Path(args.work)
if WORK.exists():
    shutil.rmtree(WORK)
CACHE = WORK / "cache"
CACHE.mkdir(parents=True)
STATS = WORK / "Stats.xml"
SETTINGS = WORK / "config" / "settings.json"
SETTINGS.parent.mkdir()

DIFFS = [("Beginner", 3), ("Easy", 5), ("Medium", 7), ("Hard", 9), ("Challenge", 12)]
RADAR = "0.300,0.270,0.120,0.050,0.070,240,258,38,15,1,5,0,10,0"
PACKS = ["Alpha Pack", "Beta Pack", "Gamma Pack"]
N_SONGS = 70


def song_dir(i):
    return f"Songs/{PACKS[i % 3]}/Song {i:03d}"


def write_cache(i, title=None, artist=None, meter_bump=0):
    title = title or f"Song {i:03d}"
    artist = artist or f"Artist {i % 7}"
    lines = [f"#TITLE:{title};", f"#ARTIST:{artist};",
             f"#SONGFILENAME:{song_dir(i)}/song.ogg;", f"#MUSICLENGTH:{90 + i}.000;",
             f"#BPMS:0.000={100 + i}.000;"]
    for d, (name, meter) in enumerate(DIFFS):
        lines += ["#NOTEDATA:;", "#STEPSTYPE:dance-single;", f"#DIFFICULTY:{name};",
                  f"#METER:{meter + (meter_bump if d == 3 else 0)};",
                  f"#RADARVALUES:{RADAR};", f"#PEAKNPS:{5 + (i + d) % 9}.25;"]
    path = CACHE / f"song_{i:03d}.cache"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_twins():
    """One song with two Edit charts sharing a description (one chart key)."""
    lines = ["#TITLE:Twins;", "#ARTIST:Twin Artist;",
             "#SONGFILENAME:Songs/Alpha Pack/Twins/twins.ogg;", "#MUSICLENGTH:100.000;",
             "#BPMS:0.000=150.000;",
             "#NOTEDATA:;", "#STEPSTYPE:dance-single;", "#DIFFICULTY:Hard;",
             "#METER:9;",
             f"#RADARVALUES:{RADAR};", "#PEAKNPS:8.25;"]
    for meter in (10, 11):
        lines += ["#NOTEDATA:;", "#STEPSTYPE:dance-single;", "#DIFFICULTY:Edit;",
                  "#DESCRIPTION:Same;", f"#METER:{meter};", f"#RADARVALUES:{RADAR};",
                  "#PEAKNPS:9.25;"]
    (CACHE / "twins.cache").write_text("\n".join(lines) + "\n", encoding="utf-8")


def entry(plays, last, pct, grade, combo):
    return {"plays": plays, "last": last, "pct": pct, "score": int(pct * 1_000_000),
            "grade": grade, "combo": combo}


def base_entries():
    out = {}
    for i in range(N_SONGS):
        for d, (name, _) in enumerate(DIFFS):
            if (i + d) % 3 != 0:
                out[(song_dir(i), name, "")] = entry(
                    1 + (i * 3 + d) % 9, f"2026-10-{1 + (i + d) % 28:02d}",
                    round(0.80 + ((i * 7 + d * 3) % 19) / 100, 4),
                    f"Tier0{1 + (i + d) % 7}", 100 + i + d * 10)
    twins = "Songs/Alpha Pack/Twins"
    out[(twins, "Hard", "")] = entry(4, "2026-10-02", 0.9, "Tier03", 200)
    out[(twins, "Edit", "Same")] = entry(6, "2026-10-04", 0.85, "Tier04", 150)
    return out


def with_changes(entries, salt):
    """A copy with edited, new, removed and date-only score changes."""
    out = copy.deepcopy(entries)
    for i in range(N_SONGS):
        hard = (song_dir(i), "Hard", "")
        easy = (song_dir(i), "Easy", "")
        medium = (song_dir(i), "Medium", "")
        begin = (song_dir(i), "Beginner", "")
        if i % 5 == salt % 5 and hard in out:
            e = out[hard]
            e.update(plays=e["plays"] + 1, pct=min(0.99, round(e["pct"] + 0.01, 4)),
                     grade="Tier01", combo=e["combo"] + 7)
            e["score"] = int(e["pct"] * 1_000_000)
        if i % 11 == salt % 11 and easy not in out:
            out[easy] = entry(2, "2026-11-02", 0.77, "Tier05", 90)
        if i % 13 == salt % 13 and medium in out:
            del out[medium]
        if i % 7 == salt % 7 and begin in out:
            out[begin]["last"] = "2026-11-20"
    return out


def write_stats(entries):
    by_song = {}
    for (sd, diff, desc), e in entries.items():
        by_song.setdefault(sd, []).append((diff, desc, e))
    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<Stats>", "  <SongScores>"]
    for sd, items in by_song.items():
        out.append(f'    <Song Dir="{sd}">')
        for diff, desc, e in items:
            d = f' Description="{desc}"' if desc else ""
            out += [f'      <Steps StepsType="dance-single" Difficulty="{diff}"{d}>',
                    "        <HighScoreList>",
                    f"          <NumTimesPlayed>{e['plays']}</NumTimesPlayed>",
                    f"          <LastPlayed>{e['last']}</LastPlayed>",
                    "          <HighScore>", "            <Name>PROB</Name>",
                    f"            <Grade>{e['grade']}</Grade>",
                    f"            <Score>{e['score']}</Score>",
                    f"            <PercentDP>{e['pct']}</PercentDP>",
                    f"            <MaxCombo>{e['combo']}</MaxCombo>",
                    f"            <DateTime>{e['last']} 12:00:00</DateTime>",
                    "            <TapNoteScores>",
                    f"              <W1>{e['combo']}</W1><W2>{e['plays']}</W2>",
                    f"              <W3>{e['plays'] % 4}</W3>",
                    f"              <Miss>{e['plays'] % 3}</Miss>",
                    "            </TapNoteScores>", "          </HighScore>",
                    "        </HighScoreList>", "      </Steps>"]
        out.append("    </Song>")
    out += ["  </SongScores>", "</Stats>"]
    STATS.write_text("\n".join(out) + "\n", encoding="utf-8")
    stamp = time.time() + len(out)  # make every rewrite look newer to the manifest
    os.utime(STATS, (stamp, stamp))


for i in range(N_SONGS):
    write_cache(i)
write_twins()
STATE_A = base_entries()
write_stats(STATE_A)
SETTINGS.write_text(json.dumps({"cache_dir": str(CACHE), "stats_file": str(STATS)}),
                    encoding="utf-8")

root = tk.Tk()
settings_patch = patch.object(app_mod.LibraryApp, "_settings_file_path",
                              staticmethod(lambda: SETTINGS))
settings_patch.start()
app = app_mod.LibraryApp(root)
loader, table, filt = app._loader, app._table, app._filter

# Record what the loader hands the shell on a sync or load (the changed-keys contract).
DELIVERIES = []
_orig_cb = loader.on_library_changed


def recording_callback(rows, preserve_selection, **kw):
    ck = kw.get("changed_keys", "<absent>")
    shown = ck if isinstance(ck, str) or ck is None else len(ck)
    DELIVERIES.append({"preserve_selection": preserve_selection,
                       "changed_keys": shown})
    return _orig_cb(rows, preserve_selection, **kw)


loader.on_library_changed = recording_callback


def settle(timeout=90):
    deadline = time.monotonic() + timeout
    quiet_since = None
    while time.monotonic() < deadline:
        root.update()
        busy = (getattr(loader, "_scan_in_flight", False)
                or getattr(loader, "_sync_in_flight", False)
                or table.count_label.get().startswith("Loading")
                or len(table.tree.get_children()) != len(filt.filter_rows()))
        if busy:
            quiet_since = None
        elif quiet_since is None:
            quiet_since = time.monotonic()
        elif time.monotonic() - quiet_since > 0.4:
            return True
        time.sleep(0.02)
    return False


TRACE = []


def trace(label, **extra):
    """Settle, then record the tree. A callable extra is read after settling."""
    settled = settle()
    extra = {k: v() if callable(v) else v for k, v in extra.items()}
    rebuilds = CALLS["n"]
    tree = table.tree
    sel = set(tree.selection())
    items = list(tree.get_children())
    lib_ids = {id(r) for r in filt.library_rows()}
    cells, bad = [], []
    for pos, item in enumerate(items):
        vals = tuple(str(v) for v in tree.item(item, "values"))
        tags = tuple(sorted(str(t) for t in tree.item(item, "tags")))
        row = table._tree_item_rows.get(item)
        cells.append([list(vals), list(tags), item in sel])
        if row is None:
            bad.append(["no_row", pos])
            continue
        who = f"{row.get('Title')}/{row.get('Difficulty')}/{row.get('Chart')}"
        if id(row) not in lib_ids:
            bad.append(["stale_row_dict", pos, who])
        ev, et = REAL_DISPLAY(row, item in sel)
        ev = tuple(str(v) for v in ev)
        if ev != vals:
            cols = [app_mod.HEADERS[k] for k in range(len(vals)) if ev[k] != vals[k]]
            bad.append(["stale_cells", pos, who, cols])
        if tuple(sorted(et)) != tags:
            bad.append(["wrong_tags", pos, who, list(tags), sorted(et)])
    visible = filt.filter_rows()
    if len(visible) != len(items):
        bad.append(["row_count", len(items), len(visible)])
    white = [c for c in cells if "selected_row" in c[1]]
    TRACE.append({"label": label, "settled": settled, "rows": len(items),
                  "selected": len(sel), "white": len(white), "rebuilds": rebuilds,
                  "oracle_bad": bad, "status": app.status.get(),
                  "deliveries": list(DELIVERIES), "cells": cells, **extra})
    DELIVERIES.clear()
    CALLS["n"] = 0


def find(title, diff, chart=None):
    for item, row in table._tree_item_rows.items():
        if (row.get("Title") == title and row.get("Difficulty") == diff
                and (chart is None or row.get("Chart") == chart)):
            return item
    raise KeyError((title, diff, chart))


def select(*specs):
    table.tree.selection_set([find(*s) for s in specs])
    root.update()


def scenario_main():
    """The 35-step sequence: see the module docstring."""
    # 0. load ---------------------------------------------------------------------
    loader.load_data()
    trace("00 load (first)")

    # 1-2. sort clicks ------------------------------------------------------------
    table.sort_by("Title")
    trace("01 sort Title asc")
    table.sort_by("Title")
    trace("02 sort Title desc")

    # 3-6. selection + tint through sorts -------------------------------------------
    select(("Song 010", "Hard"), ("Song 020", "Easy"))
    trace("03 select two rows")
    table.sort_by("Meter")
    trace("04 sort Meter, selection kept (both stay white)")
    select(("Song 030", "Medium"))
    trace("05 select a different row (the two lose white)")
    table.sort_by("Plays")
    trace("06 sort Plays (no stale white left behind)")

    # 7-9. filter edits --------------------------------------------------------------
    select(("Song 040", "Hard"))
    app.diff_var.set("Hard")
    trace("07 filter Hard (selection cleared, tag must clear)")
    app.diff_var.set("All difficulties")
    trace("08 filter back to all")
    app.search_var.set("Song 01")
    trace("09 search typed")
    app.search_var.set("")
    trace("10 search cleared")

    # 11+. syncs ---------------------------------------------------------------------
    STATE_B = with_changes(STATE_A, 0)
    write_stats(STATE_B)
    select(("Song 010", "Hard"), ("Song 011", "Easy"), ("Song 012", "Hard"))
    loader.sync_scores()
    trace("11 sync B, selection on changed+new+unchanged rows")
    table.sort_by("Best %")
    trace("12 sort Best % after sync")

    app.diff_var.set("Hard")
    trace("13a narrow to Hard")
    STATE_B2 = with_changes(STATE_B, 1)
    write_stats(STATE_B2)
    loader.sync_scores()
    trace("13b sync B2 while narrowed (changes also hit hidden rows)")
    app.diff_var.set("All difficulties")
    trace("13c widen: hidden changed rows must show new values")

    STATE_C = copy.deepcopy(STATE_B2)
    twin = ("Songs/Alpha Pack/Twins", "Edit", "Same")
    STATE_C[twin] = entry(9, "2026-11-21", 0.95, "Tier02", 300)
    write_stats(STATE_C)
    twin_items = [i for i, r in table._tree_item_rows.items()
                  if r.get("Title") == "Twins" and r.get("Difficulty") == "Edit"]
    loader.sync_scores()
    trace("14 sync C: two rows share one chart key, both change",
          twin_rows_before=len(twin_items))

    app.search_var.set("meter:10")
    trace("14b narrow so only ONE twin is visible (meter:10)")
    STATE_C2 = copy.deepcopy(STATE_C)
    STATE_C2[twin] = entry(11, "2026-11-22", 0.97, "Tier01", 310)
    write_stats(STATE_C2)
    loader.sync_scores()
    trace("14c sync while one twin is visible: set holds 1 key, visible twin updates")
    app.search_var.set("")
    trace("14d widen: the hidden twin returns, both twins must show the new score")

    table.tree.selection_set(table.tree.get_children())
    root.update()
    trace("15a select all (Ctrl+A)")
    table.sort_by("Artist")
    trace("15b sort Artist with everything selected")
    table.tree.selection_set([])
    root.update()
    trace("15c clear selection")

    # 16. a sort between the merge and the delivery of its changed set ----------------
    STATE_D = with_changes(STATE_C, 2)
    write_stats(STATE_D)
    scores = S.stats_index(STATS)
    result = S.merge_scores(loader.rows, scores)
    keys = None if isinstance(result, int) else result[1]
    table.sort_by("Plays")
    trace("16a merged in place, sort clicked, sync not delivered yet (transient)")
    if keys is None:
        app._on_library_changed(loader.rows, True)
    else:
        app._on_library_changed(loader.rows, True, changed_keys=keys)
    trace("16b sync delivered")

    # 17-19. reloads -----------------------------------------------------------------
    for i in (2, 9, 30):
        write_cache(i, title=f"Song {i:03d} renamed", artist="New Artist", meter_bump=2)
    loader.load_data()
    trace("17 reload: cache files changed (Title/Artist/Meter at unchanged keys)")

    STATE_E = with_changes(STATE_D, 3)
    write_stats(STATE_E)
    loader.load_data()
    trace("18 reload: Stats.xml changed only (reused rows re-scored in the worker)")

    app.diff_var.set("Hard")
    select(("Song 040", "Hard"))
    write_cache(4, title="Song 004 again", meter_bump=1)
    write_stats(with_changes(STATE_E, 4))
    loader.load_data()
    trace("19 reload while narrowed to Hard with a selection")
    app.diff_var.set("All difficulties")
    trace("19b widen after reload")

    # 19c. a row whose saved tuple still says "selected" after the selection moved
    STATE_F = with_changes(STATE_E, 4)
    select(("Song 050", "Hard"))
    table.sort_by("Title")
    trace("19c select Song 050 Hard, sort (its saved tuple now records the white tag)")
    select(("Song 051", "Hard"))
    trace("19d select another row (050 loses white straight on the tree)")
    table.sort_by("Artist")
    trace("19e sort (050 is unselected and unforced; saved tuple stale, tree correct)")
    STATE_F2 = copy.deepcopy(STATE_F)
    STATE_F2[(song_dir(50), "Hard", "")]["plays"] += 5
    write_stats(STATE_F2)
    loader.sync_scores()
    trace("19f sync changes Song 050 Hard: stale white record gone, new plays shown")

    # 20. a sync that fails part-way (rows already merged in place) -------------
    write_stats(with_changes(STATE_E, 0))
    count = {"n": 0}
    real_score_for_row = S._score_for_row

    def failing_score_for_row(scores, row, edit_index):
        count["n"] += 1
        if count["n"] == 120:
            raise RuntimeError("probe: injected failure partway through the merge")
        return real_score_for_row(scores, row, edit_index)

    shown_errors = []
    with patch.object(S, "_score_for_row", failing_score_for_row), \
            patch("itgmania_library.library_loader.messagebox.showerror",
                  lambda *a, **k: shown_errors.append(a)):
        loader.sync_scores()
        trace("20a sync fails part-way", errors=lambda: len(shown_errors))
    table.sort_by("Title")
    trace("20b sort Title afterwards")


def scenario_retry():
    """A dropped sync result followed by a failed Load, then a retry."""
    loader.load_data()
    trace("R0 load")

    write_stats(with_changes(STATE_A, 0))
    loader.sync_scores()
    waited = time.monotonic()
    while loader._load_results.qsize() == 0 and time.monotonic() - waited < 30:
        time.sleep(0.01)  # no root.update(): the poll cannot deliver it yet
    queued = loader._load_results.qsize()

    def failing_load_worker(self, cache, stats_file, generation):
        self._load_results.put(
            ("load_failed", "probe: injected load failure", generation))

    shown = []
    with patch.object(type(loader), "_load_worker", failing_load_worker), \
            patch("itgmania_library.library_loader.messagebox.showerror",
                  lambda *a, **k: shown.append(a)):
        loader.load_data()
        trace("R1 sync queued, Load started, sync result dropped, Load fails",
              queued_before_load=queued, error_boxes=lambda: len(shown))
    loader.sync_scores()
    trace("R2 user retries the sync against the same Stats.xml")
    table.sort_by("Title")
    trace("R3 sort afterwards")
    loader.load_data()
    trace("R4 a successful Load")


try:
    {"main": scenario_main, "retry": scenario_retry}[args.scenario]()
finally:
    root.destroy()
Path(args.out).write_text(json.dumps(TRACE), encoding="utf-8")
print("wrote", args.out, "steps:", len(TRACE))
