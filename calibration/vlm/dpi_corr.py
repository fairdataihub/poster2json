#!/usr/bin/env python3
"""Does the VLM's recall gap track effective DPI?

Hypothesis: LightOnOCR-2 is not worse at reading than pdfplumber; it is
resolution-starved on posters. Its vision tower is fixed at 1540px longest edge
(image_size=1540 -- raising it indexes off the Pixtral RoPE table and asserts),
which is ~132 DPI over A4 but ~33 DPI over a four-foot poster. If that is the
cause, then (vlm_w - ctl_w) should rise with a poster's effective DPI, and the
few page-sized posters should show no gap at all.
"""
import glob
import json
import os
import sys

import pypdfium2 as pdfium

CMP = "/tmp/vlm_cmp.json"
CORPUS = ("/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/"
          "json_schema/manual_poster_annotation")
EXTRA = {"gasimova(oos)": "/storage/poster-work/gasimova.pdf"}
LONGEST = 1540

paths = {}
for d in sorted(glob.glob(os.path.join(CORPUS, "*"))):
    pdf = glob.glob(os.path.join(d, "*.pdf"))
    if os.path.isdir(d) and pdf:
        paths[os.path.basename(d)] = pdf[0]
paths.update(EXTRA)

rows = []
for r in json.load(open(CMP, encoding="utf-8")):
    pid = r["id"]
    if pid not in paths or not (r.get("ctl") and r.get("vlm")):
        continue
    page = pdfium.PdfDocument(paths[pid])[0]
    dpi = LONGEST / (max(page.get_width(), page.get_height()) / 72.0)
    rows.append((dpi, pid, r["ctl"]["w"], r["vlm"]["w"],
                 r["vlm"]["w"] - r["ctl"]["w"],
                 r["vlm"]["r_field"] - r["ctl"]["r_field"]))

rows.sort()
print(f"{'poster':40s} {'DPI':>5} {'ctl w':>6} {'vlm w':>6} {'dW':>7} {'dField':>7}")
for dpi, pid, cw, vw, dw, df in rows:
    print(f"{pid:40s} {dpi:5.0f} {cw:6.3f} {vw:6.3f} {dw:+7.3f} {df:+7.3f}")


def pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return num / (dx * dy) if dx and dy else float("nan")


dpis = [r[0] for r in rows]
dws = [r[4] for r in rows]
print(f"\npearson r(effective DPI, vlm_w - ctl_w) = {pearson(dpis, dws):+.3f}  "
      f"(n={len(rows)})")

hi = [r for r in rows if r[0] >= 100]
lo = [r for r in rows if r[0] < 60]
for label, grp in (("page-sized (>=100 DPI)", hi), ("poster-sized (<60 DPI)", lo)):
    if grp:
        print(f"  {label:24s} n={len(grp)}  "
              f"mean dW={sum(r[4] for r in grp) / len(grp):+.3f}  "
              f"mean dField={sum(r[5] for r in grp) / len(grp):+.3f}")
