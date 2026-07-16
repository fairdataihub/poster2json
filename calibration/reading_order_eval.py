#!/usr/bin/env python3
"""Reading-order calibration harness for poster2json's xy_cut.

A fast, CPU-only proxy for the reading-order component of the 20-poster
validation. For each annotated poster it runs `extract_text_with_pdfplumber`
(which drives `xy_cut.chars_to_reading_order`) and scores the resulting raw
text against the human `_raw.md` ground truth using the same two metrics
`poster-extraction-validation/validate_model.py` uses:

    word_capture = |gen_words & ref_words| / |ref_words|
    rouge_l      = rougeL F-measure (use_stemmer=True), ref vs gen

Why a proxy: the official metrics run the 8B LLM per poster (~200s each).
Reading order is fully determined upstream of the model, so scoring raw text
against `_raw.md` isolates xy_cut and lets us sweep constants in seconds. A
final GPU run of validate_model.py confirms real pass/fail after tuning.

Scope: the pdfplumber/xy_cut path only. Image-only posters (e.g. 4737132, no
PDF) go through vision OCR and are skipped here. gasimova is included as an
out-of-sample regression check (banner reading-order failure we are fixing).

Usage:
  python reading_order_eval.py                       # baseline, current constants
  python reading_order_eval.py --set MIN_GAP_AREA=2.5 SPLIT_GAP_SLACK=0.3
  python reading_order_eval.py --sweep MIN_GAP_AREA 2.0,2.5,3.0,3.5,4.0
  python reading_order_eval.py --save baselines/baseline.json
"""
import argparse
import glob
import json
import os
import re
import statistics
import sys

REPO = "/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/poster2json"
CORPUS = ("/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/"
          "json_schema/manual_poster_annotation")
# Out-of-sample checks (not part of the official 20-poster set).
EXTRA = {
    "gasimova(oos)": ("/storage/poster-work/gasimova.pdf",
                      "/storage/poster-work/gasimova_clean_raw.md"),
}
# xy_cut module constants that can be swept.
TUNABLE = ("MIN_GAP_AREA", "SPLIT_GAP_SLACK", "MIN_CHUNK_WIDTH",
           "MIN_GAP_SIZE", "BASELINE_RANGE", "DESCENT_ADJUST")

sys.path.insert(0, REPO)
from poster2json import xy_cut          # noqa: E402
from poster2json import extract as E    # noqa: E402
from rouge_score import rouge_scorer    # noqa: E402

E.log = lambda *a, **k: None            # silence extractor logging

_WORD = re.compile(r"\w+", re.UNICODE)
_SCORER = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)


def _words(t):
    return _WORD.findall(t.lower())


def _strip_md(t):
    """Drop markdown structure tokens (headers, table pipes, bullets) but keep
    every word, so the score reflects content + order, not formatting."""
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.M)
    t = t.replace("|", " ").replace("•", " ").replace("¹", "1")
    return t


def _score(gen, ref):
    gw, rw = set(_words(gen)), set(_words(ref))
    wc = len(gw & rw) / max(len(rw), 1)
    rl = _SCORER.score(ref, gen)["rougeL"].fmeasure
    return wc, rl


def _snapshot():
    return {k: getattr(xy_cut, k) for k in TUNABLE}


def _apply(params):
    for k, v in (params or {}).items():
        if k not in TUNABLE:
            raise SystemExit(f"unknown constant: {k} (tunable: {TUNABLE})")
        setattr(xy_cut, k, float(v))


def _items():
    out = []
    for d in sorted(glob.glob(os.path.join(CORPUS, "*"))):
        if not os.path.isdir(d):
            continue
        pid = os.path.basename(d)
        pdfs = glob.glob(os.path.join(d, "*.pdf"))
        raws = glob.glob(os.path.join(d, "*_raw.md"))
        if pdfs and raws:
            out.append((pid, pdfs[0], raws[0]))
    for pid, (pdf, raw) in EXTRA.items():
        if os.path.exists(pdf) and os.path.exists(raw):
            out.append((pid, pdf, raw))
    return out


def run(params=None):
    _apply(params)
    rows = []
    for pid, pdf, raw in _items():
        try:
            gen = E.extract_text_with_pdfplumber(pdf) or ""
            with open(raw, encoding="utf-8") as fh:
                ref = _strip_md(fh.read())
            wc, rl = _score(_strip_md(gen), ref)
            rows.append({"id": pid, "w": round(wc, 3), "r": round(rl, 3),
                         "chars": len(gen)})
        except Exception as ex:  # noqa: BLE001
            rows.append({"id": pid, "w": None, "r": None,
                         "error": f"{type(ex).__name__}: {ex}"[:140]})
    return rows


def _avg(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return statistics.fmean(vals) if vals else float("nan")


def _print(rows, header=""):
    if header:
        print(header)
    print(f"  {'poster':40s} {'w':>6} {'r':>6} {'chars':>7}")
    for r in rows:
        if r.get("w") is None:
            print(f"  {r['id']:40s} {'ERR':>6} {'':>6}   {r.get('error','')}")
        else:
            print(f"  {r['id']:40s} {r['w']:6.3f} {r['r']:6.3f} {r['chars']:7d}")
    off = [r for r in rows if "oos" in r["id"]]
    core = [r for r in rows if "oos" not in r["id"] and r.get("w") is not None]
    print(f"  {'-'*62}")
    print(f"  {'AVG (official corpus)':40s} {_avg(core,'w'):6.3f} "
          f"{_avg(core,'r'):6.3f}")
    if off:
        print(f"  {'gasimova (oos)':40s} "
              f"{off[0]['w'] if off[0]['w'] is not None else float('nan'):6.3f} "
              f"{off[0]['r'] if off[0]['r'] is not None else float('nan'):6.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", nargs="*", default=[], metavar="K=V")
    ap.add_argument("--sweep", nargs=2, metavar=("CONST", "V1,V2,.."))
    ap.add_argument("--save", metavar="PATH")
    args = ap.parse_args()

    base = _snapshot()

    if args.sweep:
        const, vals = args.sweep[0], [v for v in args.sweep[1].split(",") if v]
        print(f"SWEEP {const} over {vals} (baseline {const}={base[const]})\n")
        summary = []
        for v in vals:
            _apply(dict(base))               # reset to baseline
            rows = run({const: v})
            core = [r for r in rows if "oos" not in r["id"]
                    and r.get("w") is not None]
            oos = [r for r in rows if "oos" in r["id"] and r.get("w") is not None]
            aw, ar = _avg(core, "w"), _avg(core, "r")
            gr = oos[0]["r"] if oos else float("nan")
            summary.append((v, aw, ar, gr))
            print(f"  {const}={v:>7}  corpus w={aw:.3f} r={ar:.3f}  "
                  f"gasimova r={gr:.3f}")
        return

    params = dict(p.split("=", 1) for p in args.set) if args.set else None
    label = "BASELINE (current constants)" if not params else f"CONFIG {params}"
    print(f"constants: {_snapshot() if not params else {**base, **params}}\n")
    rows = run(params)
    _print(rows, label)
    if args.save:
        os.makedirs(os.path.dirname(args.save) or ".", exist_ok=True)
        with open(args.save, "w", encoding="utf-8") as fh:
            json.dump({"constants": {**base, **(params or {})}, "rows": rows},
                      fh, indent=2)
        print(f"\nsaved {args.save}")


if __name__ == "__main__":
    main()
