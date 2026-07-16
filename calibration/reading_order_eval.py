#!/usr/bin/env python3
"""Reading-order + affiliation calibration harness for poster2json's xy_cut.

Fast, CPU-only proxy for the reading-order component of the 20-poster
validation, extended with a per-field (length-normalized) ROUGE-L and a banner
sub-metric driven by the real affiliation corrector. No 8B LLM: reading order
is fixed upstream of the model, so we score xy_cut raw text against the human
`_raw.md` and the annotation JSON. Confirm real pass/fail with a GPU run of
poster-extraction-validation/validate_model.py after tuning.

Three metrics, all normalization-matched to validate_model.py
(`normalize_text` = NFKD + strip combining marks; `strip_to_alphanumeric`):

1. GLOBAL  word_capture + global rougeL (the old top-line; banner drowns in it).

2. FIELD   rougeL per field (title, authors+affiliations, each section),
   best-match against gen chunks, aggregated as an equal-weight macro average
   ("normalized for length": a 3-word affiliation field counts as much as a
   500-word content section). This is the headline the banner can't hide in.

3. AFFIL   the banner sub-metric. For every poster, seed the affiliation
   corrector (`_correct_affiliations_from_superscripts`) with the annotation's
   author names + blank affiliations, run it on (a) the ideal `_raw.md` order
   and (b) the xy_cut raw text, and compare each author's assigned affiliation
   to the annotation ground truth. Separates corrector LOGIC coverage (ref)
   from reading-order quality (gen). Goal: all 21 posters pass on both.

Corpus: json_schema/manual_poster_annotation/<id>/{<id>.pdf,<id>_raw.md,<id>.json}
(19 PDFs; 4737132 is image-only -> ref-only, no xy_cut). gasimova is the 21st
(out-of-sample banner bug), GT at /storage/poster-work/gasimova_annotation.json.
"""
import argparse
import difflib
import glob
import json
import os
import re
import statistics
import sys
import unicodedata

REPO = "/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/poster2json"
CORPUS = ("/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/"
          "json_schema/manual_poster_annotation")
EXTRA = {  # id -> (pdf, raw_md, annotation_json); pdf="" means ref-only
    "gasimova(oos)": ("/storage/poster-work/gasimova.pdf",
                      "/storage/poster-work/gasimova_clean_raw.md",
                      "/storage/poster-work/gasimova_annotation.json"),
}
TUNABLE = ("MIN_GAP_AREA", "SPLIT_GAP_SLACK", "MIN_CHUNK_WIDTH",
           "MIN_GAP_SIZE", "BASELINE_RANGE", "DESCENT_ADJUST", "TOP_BAND",
           "TOP_BAND_DOMINANCE", "SUPERSCRIPT_SIZE_RATIO", "SUPERSCRIPT_RISE",
           "SUPERSCRIPT_MIN_DIGITS")

sys.path.insert(0, REPO)
from poster2json import xy_cut          # noqa: E402
from poster2json import extract as E    # noqa: E402
from rouge_score import rouge_scorer    # noqa: E402

E.log = lambda *a, **k: None
_SCORER = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)


# ---- normalization (matches validate_model.py) ------------------------------
def _norm(text):
    if isinstance(text, list):
        text = " ".join(str(t) for t in text)
    text = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in text if not unicodedata.combining(c))


def _alpha(text):
    return re.sub(r"\s+", " ",
                  re.sub(r"[^a-zA-Z0-9\s]", "", _norm(text))).strip().lower()


def _rougeL(ref, gen):
    return _SCORER.score(ref, gen)["rougeL"].fmeasure


def _words(t):
    return set(_alpha(t).split())


# ---- markdown field parsing -------------------------------------------------
def _parse_md(text):
    """(title, banner, [(header, body), ...]). Handles both `#`/`##` (ref) and
    gen output where the title is emitted as `## <title>`."""
    title, banner, sections = "", [], []
    header, body, seen = None, [], False
    for ln in text.splitlines():
        s = ln.strip()
        h2 = re.match(r"^#{2,}\s+(.*)", s)
        h1 = re.match(r"^#\s+(.*)", s)
        if h2:
            if header is not None:
                sections.append((header, "\n".join(body).strip()))
            header, body, seen = h2.group(1).strip(), [], True
        elif h1 and not seen and not title:
            title = h1.group(1).strip()
        elif header is None:
            if s:
                banner.append(s)
        else:
            body.append(s)
    if header is not None:
        sections.append((header, "\n".join(body).strip()))
    return title, "\n".join(banner).strip(), sections


def _gen_chunks(gen_text):
    title, banner, sections = _parse_md(gen_text)
    chunks = [title, banner] + [b for _, b in sections] + [h for h, _ in sections]
    return [c for c in chunks if c.strip()]


# ---- metric 2: per-field length-normalized rougeL ---------------------------
def field_scores(gen_text, ref_md):
    r_title, r_banner, r_secs = _parse_md(ref_md)
    chunks = [_alpha(c) for c in _gen_chunks(gen_text)] or [""]
    fields = [("title", r_title), ("authors+affiliations", r_banner)]
    fields += [(f"S:{h[:34]}", b) for h, b in r_secs]
    out = []
    for name, ref in fields:
        if not ref.strip():
            continue
        ra = _alpha(ref)
        best = max(_rougeL(ra, c) for c in chunks)
        out.append((name, round(best, 3), len(ra.split())))
    macro = statistics.fmean(s for _, s, _ in out) if out else float("nan")
    return macro, out


# ---- metric 3: affiliation corrector banner sub-metric ----------------------
def _affil_match(got, gt_names):
    """True if an assigned affiliation string faithfully renders any GT name.

    Asymmetric on purpose. An assigned string may say LESS than ground truth:
    poster legends abbreviate what deposit metadata spells out ("STScI,
    Baltimore, MD" for "Space Telescope Science Institute (STScI), Baltimore,
    MD"), and that is a faithful extraction of the poster. It may not say MORE:
    tokens ground truth lacks are byline or body text that leaked into the
    legend through a mis-bounded entry, which is precisely the failure this
    harness exists to catch. An earlier version accepted any string merely
    CONTAINING the GT tokens, which scored 'Aydan Gasimova 1 FAIR Data
    Innovations Hub...' as correct and hid two real defects.
    """
    g = _alpha(got)
    if not g:
        return False
    gtoks = set(g.split())
    for name in gt_names:
        n = _alpha(name)
        toks = set(n.split())
        if not toks:
            continue
        extra = gtoks - toks        # content GT does not have -> leaked junk
        missing = toks - gtoks      # content GT has that the poster abbreviated
        if len(extra) > 2:
            continue
        if not missing:
            return True
        if not extra and len(gtoks) >= 3:
            return True             # clean abbreviation of the GT name
        if len(missing) / len(toks) <= 0.2:
            return True
        if difflib.SequenceMatcher(None, g, n).ratio() >= 0.72:
            return True
    return False


def _run_corrector(raw_text, gt_creators):
    """Seed creators with GT names + blank affiliation, run corrector, return
    (fired, per_author_correct_list)."""
    creators = []
    for c in gt_creators:
        nm = c["name"]
        fam = nm.split(",")[0].strip() if "," in nm else nm
        creators.append({"name": nm, "familyName": fam, "affiliation": []})
    result = {"creators": creators}
    try:
        E._correct_affiliations_from_superscripts(result, raw_text)
    except Exception:  # noqa: BLE001
        return False, [False] * len(gt_creators)
    fired = any(n.get("message", "").startswith("Affiliations reassigned")
                for n in result.get("_validation", []))
    correct = []
    for c, gt in zip(result["creators"], gt_creators):
        gt_names = [a.get("name", "") for a in gt.get("affiliation", []) if a.get("name")]
        got = c.get("affiliation") or []
        got = got if isinstance(got, list) else [got]
        # every GT affil must be matched by some assigned string, and count aligns
        if gt_names:
            ok = len(got) == len(gt_names) and all(
                any(_affil_match(x, [gn]) for x in got) for gn in gt_names)
        else:
            # group authors ("the RECONS Team") have no GT affiliation;
            # correct means the corrector assigned nothing
            ok = not got
        correct.append(ok)
    return fired, correct


def affil_metric(gen_text, ref_md, annotation):
    gt = [c for c in annotation.get("creators", []) if c.get("name")]
    n = len(gt)
    distinct = {a.get("name") for c in gt for a in c.get("affiliation", []) if a.get("name")}
    scheme = "numbered" if len(distinct) >= 2 else "single"
    res = {"scheme": scheme, "n_authors": n}
    if n < 2:
        res["status"] = "n/a(<2 authors)"
        return res
    f_ref, c_ref = _run_corrector(ref_md, gt)
    res["ref_fired"] = f_ref
    res["ref_correct"] = round(sum(c_ref) / n, 3)
    if gen_text is not None:
        f_gen, c_gen = _run_corrector(gen_text, gt)
        res["gen_fired"] = f_gen
        res["gen_correct"] = round(sum(c_gen) / n, 3)
    if scheme == "single":
        res["status"] = "single(n/a)"
    elif not (f_ref and all(c_ref)):
        res["status"] = "LOGIC-GAP"          # corrector fails even on ideal order
    elif gen_text is None:
        res["status"] = "ref-ok(img)"
    elif f_gen and all(c_gen):
        res["status"] = "PASS"
    else:
        res["status"] = "ORDER-GAP"          # logic ok, reading order breaks it
    return res


# ---- driver -----------------------------------------------------------------
def _snapshot():
    return {k: getattr(xy_cut, k) for k in TUNABLE}


def _apply(params):
    for k, v in (params or {}).items():
        if k not in TUNABLE:
            raise SystemExit(f"unknown constant {k}; tunable={TUNABLE}")
        setattr(xy_cut, k, float(v))


def _items():
    out = []
    for d in sorted(glob.glob(os.path.join(CORPUS, "*"))):
        if not os.path.isdir(d):
            continue
        pid = os.path.basename(d)
        pdf = glob.glob(os.path.join(d, "*.pdf"))
        raw = glob.glob(os.path.join(d, "*_raw.md"))
        ann = os.path.join(d, f"{pid}.json")
        if raw and os.path.exists(ann):
            out.append((pid, pdf[0] if pdf else "", raw[0], ann))
    for pid, (pdf, raw, ann) in EXTRA.items():
        if os.path.exists(raw) and os.path.exists(ann):
            out.append((pid, pdf if os.path.exists(pdf) else "", raw, ann))
    return out


def run(params=None):
    _apply(params)
    rows = []
    for pid, pdf, raw, ann in _items():
        row = {"id": pid}
        try:
            with open(raw, encoding="utf-8") as fh:
                ref_md = fh.read()
            with open(ann, encoding="utf-8") as fh:
                annotation = json.load(fh)
            gen = E.extract_text_with_pdfplumber(pdf) if pdf else None
            if pdf:
                row["w"] = round(len(_words(gen) & _words(ref_md)) /
                                 max(len(_words(ref_md)), 1), 3)
                row["r_global"] = round(_rougeL(_alpha(ref_md), _alpha(gen)), 3)
                macro, fields = field_scores(gen, ref_md)
                row["r_field"] = round(macro, 3)
                row["fields"] = fields
            row["affil"] = affil_metric(gen, ref_md, annotation)
        except Exception as ex:  # noqa: BLE001
            row["error"] = f"{type(ex).__name__}: {ex}"[:160]
        rows.append(row)
    return rows


def _fmt(rows):
    print(f"  {'poster':40s} {'w':>5} {'rGlob':>6} {'rField':>7} "
          f"{'scheme':>8} {'refOK':>6} {'genOK':>6} {'status':>10}")
    for r in rows:
        if "error" in r:
            print(f"  {r['id']:40s} ERR {r['error']}")
            continue
        a = r.get("affil", {})
        w = f"{r['w']:.2f}" if "w" in r else "  -"
        rg = f"{r['r_global']:.3f}" if "r_global" in r else "   - "
        rf = f"{r['r_field']:.3f}" if "r_field" in r else "    - "
        rc = a.get("ref_correct")
        gc = a.get("gen_correct")
        print(f"  {r['id']:40s} {w:>5} {rg:>6} {rf:>7} {a.get('scheme','?'):>8} "
              f"{(f'{rc:.2f}' if rc is not None else '-'):>6} "
              f"{(f'{gc:.2f}' if gc is not None else '-'):>6} {a.get('status','?'):>10}")
    core = [r for r in rows if "oos" not in r["id"] and "w" in r]
    print(f"  {'-'*94}")
    if core:
        print(f"  corpus avg   w={statistics.fmean(r['w'] for r in core):.3f}  "
              f"rGlobal={statistics.fmean(r['r_global'] for r in core):.3f}  "
              f"rField={statistics.fmean(r['r_field'] for r in core):.3f}")
    passes = sum(1 for r in rows if r.get("affil", {}).get("status")
                 in ("PASS", "ref-ok(img)", "single(n/a)", "n/a(<2 authors)"))
    numbered = [r for r in rows if r.get("affil", {}).get("scheme") == "numbered"]
    npass = sum(1 for r in numbered if r.get("affil", {}).get("status") == "PASS")
    reflogic = sum(1 for r in numbered
                   if r.get("affil", {}).get("status") in ("PASS", "ref-ok(img)", "ORDER-GAP"))
    print(f"  AFFIL corrector: {npass}/{len(numbered)} numbered posters end-to-end PASS; "
          f"{reflogic}/{len(numbered)} corrector-logic OK on ideal order; "
          f"{passes}/{len(rows)} of all 21 acceptable")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", nargs="*", default=[], metavar="K=V")
    ap.add_argument("--sweep", nargs=2, metavar=("CONST", "V1,V2,.."))
    ap.add_argument("--save", metavar="PATH")
    ap.add_argument("--details", action="store_true", help="print per-field rougeL")
    args = ap.parse_args()
    base = _snapshot()

    if args.sweep:
        const, vals = args.sweep[0], [v for v in args.sweep[1].split(",") if v]
        print(f"SWEEP {const} (baseline {base[const]})")
        for v in vals:
            _apply(dict(base))
            rows = run({const: v})
            core = [r for r in rows if "oos" not in r["id"] and "w" in r]
            numbered = [r for r in rows if r.get("affil", {}).get("scheme") == "numbered"]
            npass = sum(1 for r in numbered if r.get("affil", {}).get("status") == "PASS")
            print(f"  {const}={v:>7}  rField={statistics.fmean(r['r_field'] for r in core):.3f}"
                  f"  rGlobal={statistics.fmean(r['r_global'] for r in core):.3f}"
                  f"  affilPASS={npass}/{len(numbered)}")
        return

    params = dict(p.split("=", 1) for p in args.set) if args.set else None
    print(f"constants: {{**{base}, **{params or {}}}}\n")
    rows = run(params)
    _fmt(rows)
    if args.details:
        print("\nper-field rougeL:")
        for r in rows:
            if "fields" not in r:
                continue
            print(f"  {r['id']}")
            for name, sc, ln in r["fields"]:
                print(f"      {sc:.3f}  ({ln:4d}w)  {name}")
    if args.save:
        os.makedirs(os.path.dirname(args.save) or ".", exist_ok=True)
        with open(args.save, "w", encoding="utf-8") as fh:
            json.dump({"constants": {**base, **(params or {})}, "rows": rows}, fh, indent=2)
        print(f"\nsaved {args.save}")


if __name__ == "__main__":
    main()
