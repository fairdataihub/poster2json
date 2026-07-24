#!/usr/bin/env python3
"""Rank every field of every poster by current rField score, lowest first.

rField is a per-poster macro-average over fields (title, authors+affiliations,
each section) each counting once. So the biggest headroom is in fields that
score low AND belong to posters whose average is dragged down by them. This
lists the worst fields with their poster's overall rField, so leverage is
visible: a 0.30 field on a 0.90 poster is a bigger opportunity than a 0.60
field on a 0.60 poster (which may just be a hard poster).
"""
import glob
import os
import statistics
import sys

REPO = "/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/poster2json"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "calibration"))
from poster2json import extract as E
E.log = lambda *a, **k: None
import reading_order_eval as REV

CORPUS = ("/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/"
          "json_schema/manual_poster_annotation")
EXTRA = [("gasimova(oos)", "/storage/poster-work/gasimova.pdf",
          "/storage/poster-work/gasimova_clean_raw.md")]


def items():
    o = []
    for d in sorted(glob.glob(os.path.join(CORPUS, "*"))):
        if not os.path.isdir(d):
            continue
        pid = os.path.basename(d)
        pdf = glob.glob(os.path.join(d, "*.pdf"))
        raw = glob.glob(os.path.join(d, "*_raw.md"))
        if pdf and raw:
            o.append((pid, pdf[0], raw[0]))
    o.extend([(p, f, r) for p, f, r in EXTRA if os.path.exists(f)])
    return o


all_fields = []
by_kind = {}
for pid, pdf, rawp in items():
    ref = open(rawp, encoding="utf-8").read()
    gen = E.extract_text_with_pdfplumber(pdf) or ""
    macro, fields = REV.field_scores(gen, ref)
    for name, sc, ln in fields:
        kind = "title" if name == "title" else \
               "banner" if name == "authors+affiliations" else "section"
        all_fields.append((sc, pid, name, ln, round(macro, 3), kind))
        by_kind.setdefault(kind, []).append(sc)

all_fields.sort()
print("=== 20 lowest-scoring fields (score, poster rField, words, field) ===")
for sc, pid, name, ln, macro, kind in all_fields[:20]:
    print(f"  {sc:.3f}  (posterRF {macro:.2f}) {ln:4d}w  {pid[:26]:26s} {name[:40]}")

print("\n=== mean score by field kind (where is the systemic loss?) ===")
for kind, scores in sorted(by_kind.items()):
    print(f"  {kind:8s} n={len(scores):3d}  mean={statistics.fmean(scores):.3f}  "
          f"min={min(scores):.3f}  #below0.6={sum(1 for s in scores if s < 0.6)}")

# Potential: if every field below 0.7 rose to 0.7, what would corpus rField be?
per_poster = {}
for sc, pid, name, ln, macro, kind in all_fields:
    per_poster.setdefault(pid, []).append(sc)
cur = statistics.fmean(statistics.fmean(v) for k, v in per_poster.items() if "oos" not in k)
lift = statistics.fmean(
    statistics.fmean(max(s, 0.7) for s in v)
    for k, v in per_poster.items() if "oos" not in k)
print(f"\ncorpus rField now={cur:.3f}; if all fields >=0.70 -> {lift:.3f} "
      f"(+{lift - cur:.3f} ceiling from lifting the tail)")
