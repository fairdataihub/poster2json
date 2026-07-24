#!/usr/bin/env python3
"""Survey VLM outputs (scrubbed) for further post-processing opportunities:
image placeholders, character-decomposition oddities, footer handling."""
import glob
import os
import re
import sys
import unicodedata

REPO = "/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/poster2json"
sys.path.insert(0, os.path.join(REPO, "calibration/vlm"))
from vlm_scrub import scrub

VDIR = os.path.join(REPO, "calibration/vlm/out")
files = sorted(glob.glob(os.path.join(VDIR, "*.md")))

# 1. image placeholder markers
print("=== 1. IMAGE / placeholder markers ===")
img_pat = re.compile(r"!\[.*?\]|\[image[^\]]*\]|\[figure[^\]]*\]|<img|!\[\]|\[\s*\]|"
                     r"^\s*\[.*?\]\s*$", re.IGNORECASE)
counts = {}
for f in files:
    t = scrub(open(f, encoding="utf-8").read())
    for m in re.finditer(r"^.*?(!\[[^\]]*\]\([^)]*\)|!\[[^\]]*\]|\[image[^\]]*\]|"
                         r"\[figure\s*\d*\]|<img[^>]*>).*$", t, re.MULTILINE | re.IGNORECASE):
        counts[os.path.basename(f)] = counts.get(os.path.basename(f), 0) + 1
        if counts[os.path.basename(f)] <= 2:
            print(f"  {os.path.basename(f):40s} {m.group(0)[:80]!r}")
print("  files with image markers:", len(counts))

# 2. character decomposition: combining marks, unusual unicode, spaced-out letters
print("\n=== 2. CHARACTER / DECOMPOSITION oddities ===")
for f in files[:8]:
    t = scrub(open(f, encoding="utf-8").read())
    combining = sum(1 for c in t if unicodedata.combining(c))
    # spaced-out letters "M a l a t e" pattern
    spaced = len(re.findall(r"\b(?:[A-Za-z]\s){3,}[A-Za-z]\b", t))
    # latex-ish leftovers
    latex = len(re.findall(r"\$[^$]*\$|\\[a-zA-Z]+", t))
    # non-ascii symbols
    if combining or spaced or latex:
        print(f"  {os.path.basename(f):40s} combining={combining} spaced-runs={spaced} latex={latex}")

# 3. footer sections: what appears in the last ~15% of lines
print("\n=== 3. FOOTER region (last 6 lines) of a few ===")
for name in ("gasimova(oos).md", "42.md", "4564017.md"):
    p = os.path.join(VDIR, name)
    if not os.path.exists(p):
        continue
    lines = [l for l in scrub(open(p, encoding="utf-8").read()).splitlines() if l.strip()]
    print(f"  --- {name} ---")
    for l in lines[-6:]:
        print(f"     {l[:95]!r}")
