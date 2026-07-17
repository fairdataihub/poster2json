#!/usr/bin/env python3
"""Identifier fidelity: does each extractor invent or corrupt exact strings?

ROUGE rewards overlap and cannot see a wrong digit. For a metadata pipeline
that is the whole ballgame: an ORCID with two digits changed is worse than no
ORCID, because it silently attributes work to another researcher. This checks
the strings that must be exact -- ORCIDs, DOIs, emails, URLs -- against the
human `_raw.md`, for BOTH extractors, and reports:

    recovered  present in the reference and reproduced exactly
    missed     present in the reference, absent from the output
    invented   present in the output, absent from the reference (FABRICATED)

A pipeline that copies the PDF text layer can only ever miss; it cannot invent.
A VLM re-renders every glyph from pixels and can do both.
"""
import glob
import os
import re
import sys
import unicodedata

REPO = "/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/poster2json"
sys.path.insert(0, REPO)
from poster2json import extract as E  # noqa: E402
E.log = lambda *a, **k: None

CORPUS = ("/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/"
          "json_schema/manual_poster_annotation")
EXTRA = [("gasimova(oos)", "/storage/poster-work/gasimova.pdf",
          "/storage/poster-work/gasimova_clean_raw.md")]
OUT = os.path.join(REPO, "calibration/vlm/out")

PATTERNS = {
    "orcid": re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b"),
    "doi": re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
}


def norm(t):
    t = unicodedata.normalize("NFKD", t)
    return "".join(c for c in t if not unicodedata.combining(c))


def find(text, kind):
    t = norm(text)
    if kind == "email":
        # LaTeX/markdown escaping varies; compare the address only.
        t = t.replace("\\", "")
    return {m.group(0).rstrip(".,;)").lower() for m in PATTERNS[kind].finditer(t)}


def items():
    out = []
    for d in sorted(glob.glob(os.path.join(CORPUS, "*"))):
        if not os.path.isdir(d):
            continue
        pid = os.path.basename(d)
        pdf = glob.glob(os.path.join(d, "*.pdf"))
        raw = glob.glob(os.path.join(d, "*_raw.md"))
        if pdf and raw:
            out.append((pid, pdf[0], raw[0]))
    for pid, pdf, raw in EXTRA:
        if os.path.exists(pdf) and os.path.exists(raw):
            out.append((pid, pdf, raw))
    return out


totals = {}
detail = []
for pid, pdf, rawp in items():
    with open(rawp, encoding="utf-8") as fh:
        ref = fh.read()
    ctl = E.extract_text_with_pdfplumber(pdf) or ""
    vlm = ""
    p = os.path.join(OUT, f"{pid}.md")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            vlm = fh.read()
    for kind in PATTERNS:
        want = find(ref, kind)
        if not want:
            continue
        for label, text in (("ctl", ctl), ("vlm", vlm)):
            got = find(text, kind)
            rec = want & got
            invented = got - want
            k = (label, kind)
            t = totals.setdefault(k, {"recovered": 0, "missed": 0, "invented": 0})
            t["recovered"] += len(rec)
            t["missed"] += len(want - got)
            t["invented"] += len(invented)
            if invented:
                detail.append((pid, label, kind, sorted(invented)[:3],
                               sorted(want)[:3]))

print(f"{'extractor':12s} {'kind':7s} {'recovered':>10s} {'missed':>7s} {'INVENTED':>9s}")
for label in ("ctl", "vlm"):
    for kind in PATTERNS:
        t = totals.get((label, kind))
        if not t:
            continue
        name = "pdfplumber" if label == "ctl" else "LightOnOCR"
        print(f"{name:12s} {kind:7s} {t['recovered']:10d} {t['missed']:7d} "
              f"{t['invented']:9d}")

print("\ninvented strings (present in output, absent from the poster):")
for pid, label, kind, inv, want in detail:
    name = "pdfplumber" if label == "ctl" else "LightOnOCR"
    print(f"  {pid} [{name}/{kind}]")
    print(f"     invented: {inv}")
    print(f"     poster has: {want}")
