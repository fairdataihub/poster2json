#!/usr/bin/env python3
"""Corpus-wide annotation audit: does the ground truth claim things the poster
does not say?

The test that caught poster 42, applied to all 21. For each poster, compare the
annotation against the HUMAN transcription (_raw.md), which is by definition
what the poster says. Anything in the annotation but absent from the
transcription came from somewhere else (the paper, the Zenodo record) and is
unreachable by any extractor, so it silently caps that poster's score.

Reports, per poster:
  - creators whose family name never appears in _raw.md
  - creators who appear ONLY inside the References section
  - GT affiliation strings whose leading institution phrase is absent
  - full .json creators disagreeing with _sub-json.json creators
"""
import glob
import json
import os
import re
import unicodedata

A = ("/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/"
     "json_schema/manual_poster_annotation")
EXTRA = [("gasimova(oos)", "/storage/poster-work/gasimova_clean_raw.md",
          "/storage/poster-work/gasimova_annotation.json", None)]


_STOP = {"university", "department", "institute", "school", "research",
         "center", "centre", "college", "laboratory", "faculty", "division",
         "hospital", "national", "science", "sciences", "medical", "medicine",
         "technology", "technical", "health", "public"}


def norm(t):
    t = unicodedata.normalize("NFKD", str(t))
    t = "".join(c for c in t if not unicodedata.combining(c))
    for a, b in (("’", "'"), ("‘", "'"), ("–", "-"), ("—", "-")):
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t).strip().lower()


def refs_start(raw):
    """Offset where the reference list begins, or len(raw)."""
    m = re.search(r"^#{1,6}\s*(references|bibliography|reference list)\b",
                  raw, re.IGNORECASE | re.MULTILINE)
    return m.start() if m else len(raw)


items = []
for d in sorted(glob.glob(os.path.join(A, "*"))):
    if not os.path.isdir(d):
        continue
    pid = os.path.basename(d)
    raw = glob.glob(os.path.join(d, "*_raw.md"))
    ann = os.path.join(d, f"{pid}.json")
    sub = glob.glob(os.path.join(d, "*_sub-json.json"))
    if raw and os.path.exists(ann):
        items.append((pid, raw[0], ann, sub[0] if sub else None))
items.extend(EXTRA)

problems = 0
for pid, rawp, annp, subp in items:
    with open(rawp, encoding="utf-8") as fh:
        raw = fh.read()
    with open(annp, encoding="utf-8") as fh:
        ann = json.load(fh)
    nraw = norm(raw)
    body = norm(raw[:refs_start(raw)])
    msgs = []

    creators = [c for c in ann.get("creators", []) if c.get("name")]
    for c in creators:
        nm = c["name"]
        fam = nm.split(",")[0].strip() if "," in nm else nm
        nf = norm(fam)
        if len(nf) < 3:
            continue
        if nf not in nraw:
            msgs.append(f"author ABSENT from poster: {nm!r}")
        elif nf not in body:
            msgs.append(f"author only in REFERENCES: {nm!r}")

    seen = set()
    for c in creators:
        for a in c.get("affiliation", []):
            name = a.get("name") if isinstance(a, dict) else a
            if not name or name in seen:
                continue
            seen.add(name)
            # Only flag an affiliation the poster does not gesture at AT ALL.
            # Posters abbreviate constantly ("VTT" for "VTT Technical Research
            # Centre of Finland Ltd", "STScI", "Technion"), and expanding an
            # abbreviation is faithful, not invented. Requiring a substring
            # match on the leading phrase flags those and buries the real
            # thing. A genuinely fabricated affiliation shares no distinctive
            # word with the poster at all.
            words = [w for w in re.findall(r"[a-z]{5,}", norm(name))
                     if w not in _STOP]
            if words and not any(w in nraw for w in words):
                msgs.append(f"affiliation ABSENT from poster: {name[:64]!r}")

    if subp and os.path.exists(subp):
        with open(subp, encoding="utf-8") as fh:
            sub = json.load(fh)
        sn = [c.get("name") for c in sub.get("creators", []) if c.get("name")]
        fn = [c.get("name") for c in creators]
        if sn and sn != fn:
            msgs.append(f"full .json creators {fn} != sub-json {sn}")

    if msgs:
        problems += 1
        print(f"=== {pid} ===")
        for m in msgs:
            print("   " + m)
        print()

print(f"{problems} of {len(items)} posters have annotation content "
      f"absent from the poster.")
