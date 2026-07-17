#!/usr/bin/env python3
"""Score LightOnOCR-2's raw output against the same controls as our pipeline.

Phase 2 of the VLM comparison. Runs under plain ~/myenv (it needs poster2json
for the control) and reads the .md files phase 1 wrote.

Both extractors are scored by the SAME code against the SAME reference: the
human `_raw.md` transcription. Nothing here is VLM-specific, so neither side
gets a metric of its own.

    w        word capture vs _raw.md. Format-blind; the fairest single number
             for "did it read the page".
    rGlobal  whole-document ROUGE-L. Order-sensitive, format-blind.
    rField   per-field ROUGE-L, length-normalized (title, authors+affiliations,
             each section count once each). CAVEAT: this one needs the output
             to carry markdown headers so it can be chunked into fields. Our
             pipeline emits '## '; LightOnOCR emits '#'/'##' of its own accord.
             If a future model emits flat text, its rField will be low for
             reasons of format rather than reading, so read w and rGlobal first.
"""
import argparse
import glob
import json
import os
import statistics
import sys

REPO = "/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/poster2json"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "calibration"))
from poster2json import extract as E   # noqa: E402
E.log = lambda *a, **k: None
import reading_order_eval as REV       # noqa: E402

CORPUS = ("/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/"
          "json_schema/manual_poster_annotation")
EXTRA = [("gasimova(oos)", "/storage/poster-work/gasimova.pdf",
          "/storage/poster-work/gasimova_clean_raw.md")]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")


def score(gen, ref_md):
    if not gen or not gen.strip():
        return None
    macro, fields = REV.field_scores(gen, ref_md)
    return {
        "w": round(len(REV._words(gen) & REV._words(ref_md))
                   / max(len(REV._words(ref_md)), 1), 3),
        "r_global": round(REV._rougeL(REV._alpha(ref_md), REV._alpha(gen)), 3),
        "r_field": round(macro, 3),
        "fields": fields,
    }


def items():
    out = []
    for d in sorted(glob.glob(os.path.join(CORPUS, "*"))):
        if not os.path.isdir(d):
            continue
        pid = os.path.basename(d)
        pdf = glob.glob(os.path.join(d, "*.pdf"))
        raw = glob.glob(os.path.join(d, "*_raw.md"))
        if raw:
            out.append((pid, pdf[0] if pdf else "", raw[0]))
    for pid, pdf, raw in EXTRA:
        if os.path.exists(raw):
            out.append((pid, pdf if os.path.exists(pdf) else "", raw))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", default=None)
    ap.add_argument("--details", action="store_true")
    ap.add_argument("--vlm-dir", default=None,
                    help="dir of VLM .md files under calibration/vlm "
                         "(default: out); use to compare a resolution sweep")
    ap.add_argument("--only-vlm", action="store_true",
                    help="skip the control (faster when sweeping the VLM)")
    args = ap.parse_args()

    vlm_dir = (os.path.join(os.path.dirname(os.path.abspath(__file__)), args.vlm_dir)
               if args.vlm_dir else OUT)
    rows = []
    for pid, pdf, rawp in items():
        with open(rawp, encoding="utf-8") as fh:
            ref = fh.read()
        row = {"id": pid}
        vlm_path = os.path.join(vlm_dir, f"{pid}.md")
        if os.path.exists(vlm_path):
            with open(vlm_path, encoding="utf-8") as fh:
                row["vlm"] = score(fh.read(), ref)
        if pdf and not args.only_vlm:
            row["ctl"] = score(E.extract_text_with_pdfplumber(pdf) or "", ref)
        if args.vlm_dir and "vlm" not in row:
            continue
        rows.append(row)

    print(f"  {'poster':40s} {'--- pdfplumber + xy_cut ---':>28} "
          f"{'--- LightOnOCR-2-1B ---':>26}")
    print(f"  {'':40s} {'w':>6} {'rGlob':>7} {'rField':>7} "
          f"{'w':>6} {'rGlob':>7} {'rField':>7}  {'dField':>7}")
    for r in rows:
        c, v = r.get("ctl"), r.get("vlm")

        def f(d, k):
            return f"{d[k]:.3f}" if d else "   -  "
        d = (f"{v['r_field'] - c['r_field']:+.3f}" if (c and v) else "   -  ")
        print(f"  {r['id']:40s} {f(c, 'w'):>6} {f(c, 'r_global'):>7} "
              f"{f(c, 'r_field'):>7} {f(v, 'w'):>6} {f(v, 'r_global'):>7} "
              f"{f(v, 'r_field'):>7}  {d:>7}")

    print("  " + "-" * 104)
    for label, key in (("pdfplumber+xy_cut", "ctl"), ("LightOnOCR-2-1B  ", "vlm")):
        got = [r[key] for r in rows if r.get(key) and "oos" not in r["id"]]
        if got:
            print(f"  {label}  n={len(got):2d}  "
                  f"w={statistics.fmean(g['w'] for g in got):.3f}  "
                  f"rGlobal={statistics.fmean(g['r_global'] for g in got):.3f}  "
                  f"rField={statistics.fmean(g['r_field'] for g in got):.3f}")

    both = [r for r in rows if r.get("ctl") and r.get("vlm") and "oos" not in r["id"]]
    if both:
        wins = sum(1 for r in both if r["vlm"]["r_field"] > r["ctl"]["r_field"])
        print(f"  head-to-head on {len(both)} posters scored by both: "
              f"VLM better on rField for {wins}, worse for {len(both) - wins}")

    if args.details:
        print("\nper-field (control -> vlm):")
        for r in rows:
            if not (r.get("ctl") and r.get("vlm")):
                continue
            print(f"  {r['id']}")
            cf = {n: s for n, s, _ in r["ctl"]["fields"]}
            for n, s, ln in r["vlm"]["fields"]:
                base = cf.get(n)
                d = f"{s - base:+.3f}" if base is not None else "  new"
                print(f"      {base if base is None else f'{base:.3f}'} -> "
                      f"{s:.3f}  {d}  ({ln:4d}w)  {n}")

    if args.save:
        with open(args.save, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2)
        print(f"\nsaved {args.save}")


if __name__ == "__main__":
    main()
