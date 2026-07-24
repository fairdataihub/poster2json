#!/usr/bin/env python3
"""Show the HTML/code-fence regions in a couple of VLM outputs to design a scrub."""
import glob
import os
import re

V = "/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/poster2json/calibration/vlm"

for name in ("out/gasimova(oos).md", "out/16083265.md", "out/10890106.md",
             "out/isporeu2023ee359130949-pdf.md"):
    p = os.path.join(V, name)
    if not os.path.exists(p):
        continue
    lines = open(p, encoding="utf-8").read().splitlines()
    fence = sum(1 for l in lines if l.strip().startswith("```"))
    html = sum(1 for l in lines if re.search(r"</?(table|tr|td|th|thead|tbody|div|img|br|span)", l, re.I))
    print("=" * 70)
    print(f"{name}  ({len(lines)} lines, {fence} fence lines, {html} html lines)")
    for i, l in enumerate(lines):
        if l.strip().startswith("```") or re.search(r"</?(table|tr|td|th|thead|tbody|div|img|br)", l, re.I):
            print(f"  L{i:3d}: {l[:95]!r}")
