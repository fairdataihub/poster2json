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
           "SUPERSCRIPT_MIN_DIGITS", "LINE_SIZE_RATIO", "LINE_MAX_GAP")

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



def _rougeL_prf(ref, gen):
    """(precision, recall, fmeasure) for rougeL.  rouge_score's convention is
    score(target, prediction): precision is w.r.t. the PREDICTION (gen), recall
    w.r.t. the TARGET (ref) -- identical arg order to the existing _rougeL()."""
    s = _SCORER.score(ref, gen)["rougeL"]
    return s.precision, s.recall, s.fmeasure


def field_prf(gen_text, ref_md):
    """Decompose the headline rField into RECALL and PRECISION per field.

    Same reference-anchored fields and same length normalization as
    field_scores() (equal-weight macro: a 3-word banner counts as much as a
    500-word section), and the *same alignment rule* (each ref field takes the
    gen chunk that maximizes rougeL F).  For that aligned pair we report:

      recall    = LCS / len(ref field)   -- of the reference field, how much the
                  extractor reproduced.  This is the recall the old rField hid.
      precision = LCS / len(gen chunk)   -- of the gen chunk aligned to this
                  field, how much is actually in the reference; i.e. did the
                  extractor pad the field with tokens the reference lacks.
                  THIS is the in-field hallucination signal (rec. #1).
      f1        = rougeL F of the aligned pair.  By construction this equals the
                  old field_scores() macro, so f1_macro == existing rField --
                  the new information is the recall/precision split, not F1.

    Returns (recall_macro, precision_macro, f1_macro, per_field) where per_field
    rows are (name, recall, precision, f1, ref_len, gen_len).

    NOTE (validated on the corpus): aligned precision conflates two defects --
    true hallucination AND mis-segmentation (gen merged two ref sections into
    one chunk, so half its tokens don't match the aligned field even though they
    ARE elsewhere in the reference).  Poster `42` scores aligned precision 0.68
    yet fabrication_soft() 0.003: its low precision is segmentation, not
    invention.  Use aligned precision to localize which field degraded, and the
    corpus fabrication number below to say whether content was actually invented.
    """
    r_title, r_banner, r_secs = _parse_md(ref_md)
    chunks = [_alpha(c) for c in _gen_chunks(gen_text)] or [""]
    fields = [("title", r_title), ("authors+affiliations", r_banner)]
    fields += [(f"S:{h[:34]}", b) for h, b in r_secs]
    per = []
    for name, ref in fields:
        ra = _alpha(ref)
        if not ra.strip():
            continue
        best = max(chunks, key=lambda c: _rougeL_prf(ra, c)[2])
        p, r, f = _rougeL_prf(ra, best)
        per.append((name, round(r, 3), round(p, 3), round(f, 3),
                    len(ra.split()), len(best.split())))
    r_macro = statistics.fmean(x[1] for x in per) if per else float("nan")
    p_macro = statistics.fmean(x[2] for x in per) if per else float("nan")
    f_macro = statistics.fmean(x[3] for x in per) if per else float("nan")
    return r_macro, p_macro, f_macro, per


# ---- corpus FABRICATION number (folds keys_check / fidelity_check) -----------
# Two components, deliberately kept as distinct units because they mean
# different things and a single blended float would hide the categorical one:
#
#   SOFT  token-level fabrication rate = fraction of generated alpha tokens that
#         are absent from the reference vocabulary.  This is exactly "gen adds
#         tokens the reference lacks", generalized from the aligned pair to the
#         whole poster, so it is immune to mis-segmentation (a token counts as
#         supported no matter which section it landed in).  Micro-averaged over
#         the corpus (sum unsupported / sum tokens) it is one number per
#         extractor.  Measured 0.033 pdfplumber vs 0.316 LightOnOCR.
#
#   HARD  invented exact identifiers (ORCID / DOI / email present in the output,
#         absent from the poster) -- fidelity_check.py's charge.  One wrong
#         ORCID silently misattributes work, so this is categorical, not a rate.
#         Measured 1 pdfplumber vs 10 LightOnOCR.
#
# keys_check.py's "lost lookup keys" is the mirror image (RECALL: keys dropped so
# no ORCID/ROR query fires) and belongs to the recall side already surfaced by
# recall_macro, not to fabrication -- lost != invented -- so it is reported as a
# companion, never folded into the fabrication scalar.
#
# Single headline: report "soft=NN.N%  hard=N ids".  Flag an extractor/poster as
# FABRICATING iff hard > 0 (any misattribution) OR soft > FAB_SOFT_TAU.

FAB_SOFT_TAU = 0.10

_ID_PATTERNS = {
    "orcid": re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b"),
    "doi": re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
}


def _find_ids(text, kind):
    t = _norm(text)
    if kind == "email":
        t = t.replace("\\", "")
    return {m.group(0).rstrip(".,;)").lower()
            for m in _ID_PATTERNS[kind].finditer(t)}


def invented_ids(gen_text, ref_md):
    """{kind: [strings]} present in gen, absent from ref (hard fabrication)."""
    out = {}
    for kind in _ID_PATTERNS:
        extra = _find_ids(gen_text, kind) - _find_ids(ref_md, kind)
        if extra:
            out[kind] = sorted(extra)
    return out


def fabrication_soft(gen_text, ref_md):
    """(rate, n_unsupported, n_total): generated alpha tokens absent from the
    reference vocabulary. The soft-hallucination volume for one poster."""
    voc = set(_alpha(ref_md).split())
    toks = _alpha(gen_text).split()
    if not toks:
        return 0.0, 0, 0
    unsup = sum(1 for t in toks if t not in voc)
    return unsup / len(toks), unsup, len(toks)


def corpus_fabrication(gen_provider, label="gen"):
    """Fold both signals into ONE corpus number for an extractor.

    gen_provider(pid, pdf, raw, ann) -> gen text (or "" / None to skip a poster,
    e.g. an image-only poster or a missing VLM .md).  Returns a dict with the
    micro soft rate, the hard invented-id count, and a boolean `fabricating`.
    Reuse the harness for pdfplumber AND for LightOnOCR by swapping the provider
    (see main()).  Micro (token-weighted), not macro, so long posters dominate
    proportionally to how much text they actually contribute.
    """
    unsup = tot = hard = 0
    per = []
    for pid, pdf, raw, ann in _items():
        ref_md = open(raw, encoding="utf-8").read()
        gen = gen_provider(pid, pdf, raw, ann)
        if not gen:
            continue
        rate, u, t = fabrication_soft(gen, ref_md)
        inv = invented_ids(gen, ref_md)
        h = sum(len(v) for v in inv.values())
        unsup += u
        tot += t
        hard += h
        per.append({"id": pid, "soft": round(rate, 3),
                    "invented": inv, "n_tok": t})
    soft = unsup / tot if tot else float("nan")
    return {"label": label, "soft": round(soft, 4), "hard_ids": hard,
            "n_tok": tot,
            "fabricating": hard > 0 or (tot and soft > FAB_SOFT_TAU),
            "per_poster": per}


# ============================================================================
# Superset driver: only ADDS keys/columns; every pre-existing key, column, and
# CLI flag keeps its old meaning.
# ============================================================================
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
                macro, fields = field_scores(gen, ref_md)   # unchanged rField
                row["r_field"] = round(macro, 3)
                row["fields"] = fields
                # NEW: recall/precision split + F1 (== r_field by construction)
                rM, pM, fM, prf = field_prf(gen, ref_md)
                row["recall_field"] = round(rM, 3)
                row["prec_field"] = round(pM, 3)
                row["f1_field"] = round(fM, 3)
                row["fields_prf"] = prf
                # NEW: per-poster fabrication signals
                srate, su, st = fabrication_soft(gen, ref_md)
                row["fab_soft"] = round(srate, 3)
                row["inv_ids"] = invented_ids(gen, ref_md)
            row["affil"] = affil_metric(gen, ref_md, annotation)
        except Exception as ex:  # noqa: BLE001
            row["error"] = f"{type(ex).__name__}: {ex}"[:160]
        rows.append(row)
    return rows


def _fmt(rows):
    print(f"  {'poster':40s} {'w':>5} {'rGlob':>6} {'rField':>7} "
          f"{'rec':>5} {'prec':>5} {'fab':>5} "
          f"{'scheme':>8} {'refOK':>6} {'genOK':>6} {'status':>10}")
    for r in rows:
        if "error" in r:
            print(f"  {r['id']:40s} ERR {r['error']}")
            continue
        a = r.get("affil", {})
        w = f"{r['w']:.2f}" if "w" in r else "  -"
        rg = f"{r['r_global']:.3f}" if "r_global" in r else "   - "
        rf = f"{r['r_field']:.3f}" if "r_field" in r else "    - "
        rc_f = f"{r['recall_field']:.2f}" if "recall_field" in r else "  -"
        pc_f = f"{r['prec_field']:.2f}" if "prec_field" in r else "  -"
        fb = f"{r['fab_soft']:.2f}" if "fab_soft" in r else "  -"
        rc = a.get("ref_correct")
        gc = a.get("gen_correct")
        print(f"  {r['id']:40s} {w:>5} {rg:>6} {rf:>7} {rc_f:>5} {pc_f:>5} "
              f"{fb:>5} {a.get('scheme','?'):>8} "
              f"{(f'{rc:.2f}' if rc is not None else '-'):>6} "
              f"{(f'{gc:.2f}' if gc is not None else '-'):>6} "
              f"{a.get('status','?'):>10}")
    core = [r for r in rows if "oos" not in r["id"] and "w" in r]
    print(f"  {'-'*110}")
    if core:
        print(f"  corpus avg   w={statistics.fmean(r['w'] for r in core):.3f}  "
              f"rGlobal={statistics.fmean(r['r_global'] for r in core):.3f}  "
              f"rField={statistics.fmean(r['r_field'] for r in core):.3f}  "
              f"recall={statistics.fmean(r['recall_field'] for r in core):.3f}  "
              f"prec={statistics.fmean(r['prec_field'] for r in core):.3f}  "
              f"F1={statistics.fmean(r['f1_field'] for r in core):.3f}")
    passes = sum(1 for r in rows if r.get("affil", {}).get("status")
                 in ("PASS", "ref-ok(img)", "single(n/a)", "n/a(<2 authors)"))
    numbered = [r for r in rows if r.get("affil", {}).get("scheme") == "numbered"]
    npass = sum(1 for r in numbered if r.get("affil", {}).get("status") == "PASS")
    reflogic = sum(1 for r in numbered
                   if r.get("affil", {}).get("status") in ("PASS", "ref-ok(img)", "ORDER-GAP"))
    print(f"  AFFIL corrector: {npass}/{len(numbered)} numbered posters end-to-end PASS; "
          f"{reflogic}/{len(numbered)} corrector-logic OK on ideal order; "
          f"{passes}/{len(rows)} of all 21 acceptable")


def _fab_summary(vlm_out=None):
    """Single corpus fabrication number, pdfplumber vs (optional) LightOnOCR.
    vlm_out: dir of scrubbed <id>.md (e.g. calibration/vlm/out). For a true
    apples-to-apples charge, feed SCRUBBED VLM text (vlm_scrub.scrub) here."""
    def ctl(pid, pdf, raw, ann):
        return E.extract_text_with_pdfplumber(pdf) if pdf else ""
    # VLM text is scrubbed before scoring fabrication, so the charge is against
    # the text we actually ship, not raw markup (raw overstates soft ~+5pts).
    try:
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "vlm"))
        from vlm_scrub import scrub as _scrub
    except Exception:
        def _scrub(t):
            return t
    print("\nFABRICATION (corpus, folds fidelity_check invented-ids + soft rate;"
          f" flag if hard>0 or soft>{FAB_SOFT_TAU}):")
    for prov, name in ([(ctl, "pdfplumber")] +
                       ([(lambda pid, pdf, raw, ann,
                          _d=vlm_out: (_scrub(open(os.path.join(_d, f"{pid}.md"),
                                            encoding="utf-8").read())
                                       if os.path.exists(os.path.join(_d, f"{pid}.md"))
                                       else ""), "LightOnOCR")]
                        if vlm_out and os.path.isdir(vlm_out) else [])):
        f = corpus_fabrication(prov, name)
        print(f"  {name:12s} soft={f['soft']*100:5.1f}%  hard={f['hard_ids']:2d} ids  "
              f"({f['n_tok']} tok)  ->  {'FABRICATING' if f['fabricating'] else 'clean'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", nargs="*", default=[], metavar="K=V")
    ap.add_argument("--sweep", nargs=2, metavar=("CONST", "V1,V2,.."))
    ap.add_argument("--save", metavar="PATH")
    ap.add_argument("--details", action="store_true", help="print per-field rougeL")
    ap.add_argument("--fab", nargs="?", const="vlm/out", default=None,
                    metavar="VLM_OUT_DIR",
                    help="print corpus fabrication (optionally vs a VLM out dir)")
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
                  f"  prec={statistics.fmean(r['prec_field'] for r in core):.3f}"
                  f"  fab={statistics.fmean(r['fab_soft'] for r in core):.3f}"
                  f"  rGlobal={statistics.fmean(r['r_global'] for r in core):.3f}"
                  f"  affilPASS={npass}/{len(numbered)}")
        return

    params = dict(p.split("=", 1) for p in args.set) if args.set else None
    print(f"constants: {{**{base}, **{params or {}}}}\n")
    rows = run(params)
    _fmt(rows)
    if args.fab is not None:
        vlm = args.fab if os.path.isabs(args.fab) else os.path.join(REPO, "calibration", args.fab)
        _fab_summary(vlm)
    if args.details:
        print("\nper-field recall / precision / f1:")
        for r in rows:
            if "fields_prf" not in r:
                continue
            print(f"  {r['id']}")
            for name, rc, pc, f1, rl, gl in r["fields_prf"]:
                print(f"      r={rc:.3f} p={pc:.3f} f1={f1:.3f}  "
                      f"(ref {rl:4d}w / gen {gl:4d}w)  {name}")
    if args.save:
        os.makedirs(os.path.dirname(args.save) or ".", exist_ok=True)
        with open(args.save, "w", encoding="utf-8") as fh:
            json.dump({"constants": {**base, **(params or {})}, "rows": rows}, fh, indent=2)
        print(f"\nsaved {args.save}")


if __name__ == "__main__":
    main()
