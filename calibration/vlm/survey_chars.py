#!/usr/bin/env python3
"""Enumerate every non-ASCII character in the scrubbed VLM outputs, so the
normalization map is built from what actually appears, not guesses."""
import glob
import os
import sys
import unicodedata
from collections import Counter

REPO = "/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/poster2json"
sys.path.insert(0, os.path.join(REPO, "calibration/vlm"))
from vlm_scrub import scrub

V = os.path.join(REPO, "calibration/vlm/out")
counts = Counter()
for f in glob.glob(os.path.join(V, "*.md")):
    t = scrub(open(f, encoding="utf-8").read())
    for ch in t:
        if ord(ch) > 127:
            counts[ch] += 1

print(f"{'char':>5} {'codepoint':>10} {'count':>6}  name")
for ch, n in counts.most_common(60):
    try:
        name = unicodedata.name(ch)
    except ValueError:
        name = "?"
    print(f"{ch!r:>5} {'U+%04X' % ord(ch):>10} {n:>6}  {name}")
