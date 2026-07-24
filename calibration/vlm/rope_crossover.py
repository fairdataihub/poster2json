#!/usr/bin/env python3
"""1540 vs 2464-RoPE-rebuild per poster, sorted by native DPI, truncations flagged.

Tests the hypothesis that higher resolution helps ONLY the resolution-starved
posters (big, low effective DPI at 1540) and hurts the already-fine ones (small,
high DPI -- pushing them past native resolution and past safe RoPE extrapolation).
If so, resolution should be adaptive: scale each poster toward a target DPI, not
a fixed longest edge for all.
"""
import glob, json, os, sys
import pypdfium2 as pdfium

REPO = "/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/poster2json"
sys.path.insert(0, REPO); sys.path.insert(0, os.path.join(REPO, "calibration"))
from poster2json import extract as E
E.log = lambda *a, **k: None
import reading_order_eval as REV
V = os.path.join(REPO, "calibration/vlm")
CORPUS = ("/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/"
          "json_schema/manual_poster_annotation")
EXTRA = [("gasimova(oos)", "/storage/poster-work/gasimova.pdf",
          "/storage/poster-work/gasimova_clean_raw.md")]


def score(gen, ref):
    if not gen or not gen.strip():
        return None
    m, _ = REV.field_scores(gen, ref)
    return (round(len(REV._words(gen) & REV._words(ref)) / max(len(REV._words(ref)), 1), 3),
            round(m, 3))


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


trunc = {}
for tag, d in (("1540", "out"), ("2464", "out_rope2464")):
    j = os.path.join(V, d, "run.json")
    if os.path.exists(j):
        for r in json.load(open(j))["runs"]:
            trunc[(tag, r["id"])] = r.get("truncated", False)

rows = []
for pid, pdf, rawp in items():
    ref = open(rawp, encoding="utf-8").read()
    page = pdfium.PdfDocument(pdf)[0]
    dpi = 1540 / (max(page.get_width(), page.get_height()) / 72.0)
    r = {"pid": pid, "dpi": dpi}
    for tag, d in (("1540", "out"), ("2464", "out_rope2464")):
        p = os.path.join(V, d, f"{pid}.md")
        r[tag] = score(open(p, encoding="utf-8").read(), ref) if os.path.exists(p) else None
    rows.append(r)

rows.sort(key=lambda r: r["dpi"])
print(f"{'poster':40s} {'nat.DPI':>7} {'1540 w/rF':>13} {'2464 w/rF':>13} {'d rField':>9} {'trunc'}")
gain_starved = gain_fine = 0
ns = nf = 0
for r in rows:
    a, b = r.get("1540"), r.get("2464")
    if not (a and b):
        continue
    df = b[1] - a[1]
    tr = "2464T" if trunc.get(("2464", r["pid"])) else ""
    starved = r["dpi"] < 40
    if starved and not tr:
        gain_starved += df; ns += 1
    elif not starved and not tr:
        gain_fine += df; nf += 1
    print(f"{r['pid']:40s} {r['dpi']:7.0f} {a[0]:.2f}/{a[1]:.2f}    "
          f"{b[0]:.2f}/{b[1]:.2f}    {df:+9.3f} {tr}")
print()
if ns:
    print(f"starved (<40 DPI, not truncated) n={ns}: mean d rField {gain_starved/ns:+.3f}")
if nf:
    print(f"already-fine (>=40 DPI)         n={nf}: mean d rField {gain_fine/nf:+.3f}")
