#!/usr/bin/env python3
"""Score VLM outputs raw vs scrubbed, per poster, to measure the scrub's effect."""
import glob
import os
import statistics
import sys

REPO = "/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/poster2json"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "calibration"))
sys.path.insert(0, os.path.join(REPO, "calibration/vlm"))
from poster2json import extract as E
E.log = lambda *a, **k: None
import reading_order_eval as REV
from vlm_scrub import scrub

CORPUS = ("/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/"
          "json_schema/manual_poster_annotation")
EXTRA = [("gasimova(oos)", "/storage/poster-work/gasimova_clean_raw.md")]
VDIR = os.path.join(REPO, "calibration/vlm", sys.argv[1] if len(sys.argv) > 1 else "out")


def score(gen, ref):
    if not gen or not gen.strip():
        return None
    m, _ = REV.field_scores(gen, ref)
    w = len(REV._words(gen) & REV._words(ref)) / max(len(REV._words(ref)), 1)
    g = REV._rougeL(REV._alpha(ref), REV._alpha(gen))
    return round(w, 3), round(g, 3), round(m, 3)


items = []
for d in sorted(glob.glob(os.path.join(CORPUS, "*"))):
    if os.path.isdir(d):
        pid = os.path.basename(d)
        raw = glob.glob(os.path.join(d, "*_raw.md"))
        if raw:
            items.append((pid, raw[0]))
items.extend(EXTRA)

print(f"VLM dir: {os.path.basename(VDIR)}")
print(f"{'poster':40s} {'raw w/rG/rF':>20} {'scrubbed w/rG/rF':>20} {'dRF':>7}")
raws, scrs = [], []
for pid, rawp in items:
    p = os.path.join(VDIR, f"{pid}.md")
    if not os.path.exists(p):
        continue
    ref = open(rawp, encoding="utf-8").read()
    txt = open(p, encoding="utf-8").read()
    a = score(txt, ref)
    b = score(scrub(txt), ref)
    if not (a and b):
        continue
    if "oos" not in pid:
        raws.append(a); scrs.append(b)
    d = b[2] - a[2]
    flag = "  <--" if abs(d) > 0.01 else ""
    print(f"{pid:40s} {a[0]:.2f}/{a[1]:.2f}/{a[2]:.2f}     "
          f"{b[0]:.2f}/{b[1]:.2f}/{b[2]:.2f}     {d:+.3f}{flag}")

print(f"\ncorpus (n={len(raws)}):")
print(f"  raw       w={statistics.fmean(x[0] for x in raws):.3f} "
      f"rGlobal={statistics.fmean(x[1] for x in raws):.3f} "
      f"rField={statistics.fmean(x[2] for x in raws):.3f}")
print(f"  scrubbed  w={statistics.fmean(x[0] for x in scrs):.3f} "
      f"rGlobal={statistics.fmean(x[1] for x in scrs):.3f} "
      f"rField={statistics.fmean(x[2] for x in scrs):.3f}")
