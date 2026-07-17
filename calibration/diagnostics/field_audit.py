#!/usr/bin/env python3
"""Every field of every poster: session-start baseline vs now.

rField is the length-normalized per-field ROUGE-L: each field (title,
authors+affiliations, and each section) scores once regardless of how many
words it has, so a 3-word banner counts as much as a 500-word section.
This prints the per-field delta so nothing can hide in an average.
"""
import json
import sys

BASE = sys.argv[1]
NEW = sys.argv[2]

base = {r["id"]: r for r in json.load(open(BASE, encoding="utf-8"))["rows"]}
new = {r["id"]: r for r in json.load(open(NEW, encoding="utf-8"))["rows"]}

changed = []
same = 0
total = 0
for pid in sorted(base):
    b, n = base[pid], new.get(pid, {})
    bf = {f[0]: (f[1], f[2]) for f in b.get("fields", [])}
    nf = {f[0]: (f[1], f[2]) for f in n.get("fields", [])}
    keys = sorted(set(bf) | set(nf))
    rows = []
    for k in keys:
        bv = bf.get(k, (None, 0))[0]
        nv = nf.get(k, (None, 0))[0]
        w = nf.get(k, bf.get(k, (0, 0)))[1]
        total += 1
        if bv is None or nv is None:
            rows.append((k, bv, nv, None, w))
        elif abs(nv - bv) > 0.0005:
            rows.append((k, bv, nv, nv - bv, w))
        else:
            same += 1
    if rows:
        changed.append((pid, rows))

print(f"{total} fields across {len(base)} posters; {same} byte-identical, "
      f"{total - same} changed\n")
for pid, rows in changed:
    print(f"=== {pid} ===")
    for k, bv, nv, d, w in rows:
        bs = f"{bv:.3f}" if bv is not None else "  -  "
        ns = f"{nv:.3f}" if nv is not None else "  -  "
        ds = f"{d:+.3f}" if d is not None else "  new/gone"
        arrow = "IMPROVED" if (d or 0) > 0 else ("WORSE" if (d or 0) < 0 else "")
        print(f"   {bs} -> {ns}  {ds}  ({w:4d}w)  {k[:46]:46s} {arrow}")
    print()
