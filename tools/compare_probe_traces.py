#!/usr/bin/env python3
# Reviewer tool, kept in tools/ and not shipped with the app. Standard library only.
"""Compare two traces written by probe_changed_keys.py (first = before, second = after).

    python tools/compare_probe_traces.py before.json after.json

Prints one line per step: whether the visible cells (values, tags, selection) are
identical in both traces, how many display tuples each run rebuilt, and how many rows
the in-memory oracle found stale in each. Then lists the oracle failures, the
changed-keys deliveries the loader handed the shell, and any step that never settled.
A step where the second trace has oracle failures and the first has none is a
regression; a step where the cells differ but the second has none is the second run
showing newer or corrected data.
"""
import json
import sys

old = json.load(open(sys.argv[1]))
new = json.load(open(sys.argv[2]))
if [s["label"] for s in old] != [s["label"] for s in new]:
    sys.exit("The two traces have different steps: run both with the same --scenario.")

print(f"{'step':<66}{'rows':>5} {'visible cells old==new':>23} {'rebuilds old/new':>17}"
      f" {'oracle fails old/new':>21}")
for a, b in zip(old, new):
    diff_rows = sum(1 for x, y in zip(a["cells"], b["cells"]) if x != y)
    diff_rows += abs(len(a["cells"]) - len(b["cells"]))  # zip stops at the shorter
    same = a["cells"] == b["cells"]
    flag = "identical" if same else f"DIFFER ({diff_rows} rows)"
    rebuilt = f"{a['rebuilds']:>8}/{b['rebuilds']:<8}"
    stale = f"{len(a['oracle_bad']):>10}/{len(b['oracle_bad']):<10}"
    print(f"{a['label'][:65]:<66}{b['rows']:>5} {flag:>23} {rebuilt} {stale}")

print("\n--- oracle failures (cells or tags that disagree with the in-memory rows) ---")
for a, b in zip(old, new):
    for tag, t in (("OLD", a), ("NEW", b)):
        if t["oracle_bad"]:
            kinds = {}
            for item in t["oracle_bad"]:
                kinds[item[0]] = kinds.get(item[0], 0) + 1
            print(f"[{tag}] {t['label']}: {kinds}")
            for item in t["oracle_bad"][:3]:
                print("        ", item)

print("\n--- changed-keys deliveries (what the loader handed the shell) ---")
for b in new:
    if b["deliveries"]:
        print(b["label"], "->", b["deliveries"], "|", b["status"])

print("\n--- not settled ---")
for tag, trace in (("OLD", old), ("NEW", new)):
    for s in trace:
        if not s["settled"]:
            print(tag, s["label"])
