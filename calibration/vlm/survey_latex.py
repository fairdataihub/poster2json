#!/usr/bin/env python3
"""Enumerate LaTeX-ish tokens in scrubbed VLM outputs to design safe handling."""
import glob
import os
import re
import sys

REPO = "/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/poster2json"
sys.path.insert(0, os.path.join(REPO, "calibration/vlm"))
from vlm_scrub import scrub

V = os.path.join(REPO, "calibration/vlm/out")
pats = {}
examples = {}
for f in glob.glob(os.path.join(V, "*.md")):
    t = scrub(open(f, encoding="utf-8").read())
    for m in re.finditer(r"\$[^$]{0,60}?\$|\\[a-zA-Z]+", t):
        s = m.group(0)
        key = re.sub(r"\d", "N", s)[:26]
        pats[key] = pats.get(key, 0) + 1
        examples.setdefault(key, s)

print("token-shape  count  example")
for k, v in sorted(pats.items(), key=lambda x: -x[1])[:25]:
    print(f"  {v:3d}  {examples[k]!r}")

# lone $ (currency vs math)
print("\nlone $ occurrences (currency risk):")
for f in glob.glob(os.path.join(V, "*.md")):
    t = scrub(open(f, encoding="utf-8").read())
    for m in re.finditer(r"\$\d[\d,.]*", t):
        print(f"  {os.path.basename(f):30s} {m.group(0)!r}")
