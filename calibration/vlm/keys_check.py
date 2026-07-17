#!/usr/bin/env python3
"""Lookup-key fidelity: are the strings the enrichment actually queries on intact?

poster2json does NOT read ORCIDs off a poster. `enrich_creators_orcid` queries
the ORCID API with given-names + family-name + affiliation-org-name and attaches
an id only on a single unambiguous hit; ROR resolves institutions the same way.
So an ORCID hallucinated into the raw text never reaches the output, and
checking hallucinated ORCIDs measures nothing about this pipeline.

What DOES matter is the query keys. If an extractor drops an author, the lookup
never runs. If it corrupts an institution ("Delta Hat Ltd" -> "Delta et Ltd"),
the affiliation-org-name query misses. Because the enrichment demands an exact,
unambiguous match (precision over coverage, 0.9.17), a corrupted key normally
fails SAFE -- no id attached -- rather than attaching the wrong person's id. So
the cost of VLM corruption here is coverage, not misattribution. That is a very
different, and much smaller, charge than the one the identifier check implied.

Reports, per extractor: of the author family names and distinct affiliation
strings the annotation says are on the poster, how many appear verbatim in the
extracted text.
"""
import glob
import json
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
          "/storage/poster-work/gasimova_annotation.json")]
OUT = os.path.join(REPO, "calibration/vlm/out")


def norm(t):
    t = unicodedata.normalize("NFKD", str(t))
    t = "".join(c for c in t if not unicodedata.combining(c))
    for a, b in (("’", "'"), ("‘", "'"), ("–", "-"), ("—", "-")):
        t = t.replace(a, b)
    t = re.sub(r"[^a-z0-9 ]+", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def items():
    out = []
    for d in sorted(glob.glob(os.path.join(CORPUS, "*"))):
        if not os.path.isdir(d):
            continue
        pid = os.path.basename(d)
        pdf = glob.glob(os.path.join(d, "*.pdf"))
        ann = os.path.join(d, f"{pid}.json")
        if pdf and os.path.exists(ann):
            out.append((pid, pdf[0], ann))
    for pid, pdf, ann in EXTRA:
        if os.path.exists(pdf) and os.path.exists(ann):
            out.append((pid, pdf, ann))
    return out


tot = {"ctl": {"name": [0, 0], "aff": [0, 0]}, "vlm": {"name": [0, 0], "aff": [0, 0]}}
lost = []
for pid, pdf, annp in items():
    with open(annp, encoding="utf-8") as fh:
        ann = json.load(fh)
    creators = [c for c in ann.get("creators", []) if c.get("name")]
    fams, affs = [], []
    for c in creators:
        nm = c["name"]
        fams.append(nm.split(",")[0].strip() if "," in nm else nm)
        for a in c.get("affiliation", []) or []:
            n = a.get("name") if isinstance(a, dict) else a
            if n and n not in affs:
                affs.append(n)

    texts = {"ctl": E.extract_text_with_pdfplumber(pdf) or ""}
    p = os.path.join(OUT, f"{pid}.md")
    texts["vlm"] = open(p, encoding="utf-8").read() if os.path.exists(p) else ""

    for label, text in texts.items():
        nt = norm(text)
        for fam in fams:
            nf = norm(fam)
            hit = bool(nf) and nf in nt
            tot[label]["name"][0] += hit
            tot[label]["name"][1] += 1
            if not hit:
                lost.append((pid, label, "author", fam))
        for aff in affs:
            # institution head phrase: what affiliation-org-name would query on
            head = norm(aff.split(",")[0])
            hit = bool(head) and head in nt
            tot[label]["aff"][0] += hit
            tot[label]["aff"][1] += 1
            if not hit:
                lost.append((pid, label, "affil", aff[:56]))

print(f"{'extractor':12s} {'key':7s} {'found':>7s} {'of':>4s} {'rate':>7s}")
for label in ("ctl", "vlm"):
    name = "pdfplumber" if label == "ctl" else "LightOnOCR"
    for k in ("name", "aff"):
        got, n = tot[label][k]
        kind = "authors" if k == "name" else "affils"
        print(f"{name:12s} {kind:7s} {got:7d} {n:4d} {got / max(n, 1):7.3f}")

print("\nlookup keys the extractor lost (no ORCID/ROR query can fire):")
for label in ("ctl", "vlm"):
    rows = [r for r in lost if r[1] == label]
    name = "pdfplumber" if label == "ctl" else "LightOnOCR"
    print(f"  --- {name}: {len(rows)} ---")
    for pid, _, kind, val in rows[:14]:
        print(f"     {pid:38s} {kind:5s} {val!r}")
