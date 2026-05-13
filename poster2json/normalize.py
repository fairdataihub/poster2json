"""
Output normalization for poster JSON.

Constraints worth knowing:
- License normalization NEVER fuzzy-matches across version numbers
  ("CC-BY-4.0" and "CC-BY-4.1" stay distinct, even if 4.1 is a typo).
- Subject normalization is cosmetic only — no canonicalization to MeSH,
  LCSH, or other vocabularies.
"""
import re
import unicodedata
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# License normalization
# ---------------------------------------------------------------------------

_LICENSE_RECORDS: List[Dict] = [
    {
        "spdx": "CC-BY-4.0",
        "name": "Creative Commons Attribution 4.0 International",
        "uri": "https://creativecommons.org/licenses/by/4.0/",
        "aliases": [
            "CC-BY-4.0", "CC BY 4.0", "CC-BY 4.0", "CCBY4.0",
            "cc-by-4.0", "cc-by", "CC-BY", "CC BY",
            "Creative Commons Attribution 4.0 International",
            "Creative Commons Attribution 4.0 International License",
            "Creative Commons Attribution 4.0 International license",
            "Creative Commons Attribution 4.0",
            "Creative Commons Attribution 4.0 International (CC BY 4.0)",
            "Attribution 4.0 International",
            "Creative Commons Namensnennung 4.0 International Lizenz",
            "Creative Commons Namensnennung 4.0 International Lizenz (CC BY 4.0)",
            "Creative Commons Namensnennung 4.0 International (CC BY 4.0)",
            "Creative Commons Namensnennung 4.0 International",
            "This work is licensed under a Creative Commons Attribution 4.0 International License.",
            "This work is licensed under a Creative Commons Attribution 4.0 International License",
            "Attribution 4.0 International (CC BY 4.0)",
            "Attribution 4.0 International",
            "Creative Commons Attribution 4.0 License",
        ],
    },
    {
        "spdx": "CC-BY-SA-4.0",
        "name": "Creative Commons Attribution-ShareAlike 4.0 International",
        "uri": "https://creativecommons.org/licenses/by-sa/4.0/",
        "aliases": [
            "CC-BY-SA-4.0", "CC BY-SA 4.0", "CC-BY-SA 4.0", "CC BY-SA", "CCBYSA4.0",
            "Creative Commons Attribution-ShareAlike 4.0 International",
            "Creative Commons Attribution-ShareAlike 4.0 International License",
            "Attribution-ShareAlike 4.0 International",
        ],
    },
    {
        "spdx": "CC-BY-NC-4.0",
        "name": "Creative Commons Attribution-NonCommercial 4.0 International",
        "uri": "https://creativecommons.org/licenses/by-nc/4.0/",
        "aliases": [
            "CC-BY-NC-4.0", "CC BY-NC 4.0", "CC-BY-NC 4.0", "CC BY-NC", "CC-BY-NC", "CCBYNC4.0",
            "Creative Commons Attribution-NonCommercial 4.0 International",
            "Creative Commons Attribution-NonCommercial 4.0 International License",
            "Attribution-NonCommercial 4.0 International",
        ],
    },
    {
        "spdx": "CC-BY-ND-4.0",
        "name": "Creative Commons Attribution-NoDerivatives 4.0 International",
        "uri": "https://creativecommons.org/licenses/by-nd/4.0/",
        "aliases": [
            "CC-BY-ND-4.0", "CC BY-ND 4.0", "CC-BY-ND 4.0",
            "Creative Commons Attribution-NoDerivatives 4.0 International",
            "Creative Commons Attribution-NoDerivatives 4.0 International License",
        ],
    },
    {
        "spdx": "CC-BY-NC-SA-4.0",
        "name": "Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International",
        "uri": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
        "aliases": [
            "CC-BY-NC-SA-4.0", "CC BY-NC-SA 4.0", "CC-BY-NC-SA 4.0",
            "Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International",
            "Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License",
        ],
    },
    {
        "spdx": "CC-BY-NC-ND-4.0",
        "name": "Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International",
        "uri": "https://creativecommons.org/licenses/by-nc-nd/4.0/",
        "aliases": [
            "CC-BY-NC-ND-4.0", "CC BY-NC-ND 4.0", "CC-BY-NC-ND 4.0",
            "Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International",
            "Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International License",
            "This work is licensed under a Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International License.",
            "This work is licensed under a Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International License",
        ],
    },
    {
        "spdx": "CC-BY-3.0",
        "name": "Creative Commons Attribution 3.0 Unported",
        "uri": "https://creativecommons.org/licenses/by/3.0/",
        "aliases": [
            "CC-BY-3.0", "CC BY 3.0", "cc-by-3.0-us",
            "Creative Commons Attribution 3.0",
            "Creative Commons Attribution 3.0 Unported",
        ],
    },
    {
        "spdx": "CC-BY-SA-3.0",
        "name": "Creative Commons Attribution-ShareAlike 3.0 Unported",
        "uri": "https://creativecommons.org/licenses/by-sa/3.0/",
        "aliases": [
            "CC-BY-SA-3.0", "CC BY-SA 3.0",
            "Creative Commons Attribution-ShareAlike 3.0 Unported",
        ],
    },
    {
        "spdx": "CC-BY-2.0",
        "name": "Creative Commons Attribution 2.0 Generic",
        "uri": "https://creativecommons.org/licenses/by/2.0/",
        "aliases": ["CC-BY-2.0", "CC BY 2.0"],
    },
    {
        "spdx": "CC0-1.0",
        "name": "Creative Commons Zero 1.0 Universal",
        "uri": "https://creativecommons.org/publicdomain/zero/1.0/",
        "aliases": [
            "CC0-1.0", "CC0 1.0", "CC0",
            "cc-zero", "cc0", "CC Zero",
            "Creative Commons Zero 1.0 Universal",
            "Creative Commons Zero",
            "Public Domain Dedication",
            "Public Domain",
        ],
    },
    {
        "spdx": "MIT",
        "name": "MIT License",
        "uri": "https://opensource.org/licenses/MIT",
        "aliases": ["MIT", "MIT License"],
    },
    {
        "spdx": "Apache-2.0",
        "name": "Apache License 2.0",
        "uri": "https://www.apache.org/licenses/LICENSE-2.0",
        "aliases": [
            "Apache-2.0", "Apache 2.0", "Apache License 2.0",
            "Apache License Version 2.0",
        ],
    },
    {
        "spdx": "BSD-3-Clause",
        "name": 'BSD 3-Clause "New" or "Revised" License',
        "uri": "https://opensource.org/licenses/BSD-3-Clause",
        "aliases": [
            "BSD-3-Clause", "BSD 3-Clause", "BSD 3 Clause",
            "BSD 3-Clause License", "New BSD License", "Revised BSD License",
        ],
    },
    {
        "spdx": "BSD-2-Clause",
        "name": 'BSD 2-Clause "Simplified" License',
        "uri": "https://opensource.org/licenses/BSD-2-Clause",
        "aliases": [
            "BSD-2-Clause", "BSD 2-Clause", "Simplified BSD License",
        ],
    },
    {
        "spdx": "GPL-3.0",
        "name": "GNU General Public License v3.0",
        "uri": "https://www.gnu.org/licenses/gpl-3.0.html",
        "aliases": [
            "GPL-3.0", "GPLv3", "GPL 3.0",
            "GNU General Public License v3.0",
            "GNU GPL v3", "GPL-3.0-only", "GPL-3.0-or-later",
        ],
    },
    {
        "spdx": "GPL-2.0",
        "name": "GNU General Public License v2.0",
        "uri": "https://www.gnu.org/licenses/gpl-2.0.html",
        "aliases": [
            "GPL-2.0", "GPLv2", "GPL 2.0",
            "GNU General Public License v2.0",
            "GPL-2.0-only", "GPL-2.0-or-later",
        ],
    },
    {
        "spdx": "LGPL-3.0",
        "name": "GNU Lesser General Public License v3.0",
        "uri": "https://www.gnu.org/licenses/lgpl-3.0.html",
        "aliases": [
            "LGPL-3.0", "LGPLv3",
            "GNU Lesser General Public License v3.0",
            "LGPL-3.0-only", "LGPL-3.0-or-later",
        ],
    },
    {
        "spdx": "MPL-2.0",
        "name": "Mozilla Public License 2.0",
        "uri": "https://www.mozilla.org/MPL/2.0/",
        "aliases": ["MPL-2.0", "Mozilla Public License 2.0", "MPL 2.0"],
    },
]


def _strip_alphanumeric(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _extract_integers(s: str) -> Tuple[int, ...]:
    return tuple(int(m.group()) for m in re.finditer(r"\d+", s))


def _alpha_only(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[-1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]


def _build_tables():
    by_alias: Dict[str, str] = {}
    by_spdx: Dict[str, Dict] = {}
    alpha_index: Dict[Tuple[Tuple[int, ...], str], str] = {}
    for rec in _LICENSE_RECORDS:
        spdx = rec["spdx"]
        by_spdx[spdx] = rec
        for alias in rec["aliases"]:
            stripped = _strip_alphanumeric(alias)
            if stripped:
                by_alias[stripped] = spdx
            ints = _extract_integers(alias)
            alpha = _alpha_only(alias)
            if alpha:
                alpha_index.setdefault((ints, alpha), spdx)
    return by_alias, by_spdx, alpha_index


_BY_ALIAS, _BY_SPDX, _ALPHA_INDEX = _build_tables()


def _match_license(text: str) -> Optional[str]:
    """Return canonical SPDX id for `text`, or None if no confident match."""
    if not text or not isinstance(text, str):
        return None

    stripped = _strip_alphanumeric(text)
    if not stripped:
        return None
    if stripped in _BY_ALIAS:
        return _BY_ALIAS[stripped]

    ints = _extract_integers(text)
    alpha = _alpha_only(text)
    if not alpha:
        return None
    candidates = set()
    for (cand_ints, cand_alpha), spdx in _ALPHA_INDEX.items():
        if cand_ints != ints:
            continue
        if _levenshtein(alpha, cand_alpha) <= 1:
            candidates.add(spdx)
    if len(candidates) == 1:
        return candidates.pop()

    return None


def normalize_rights_entry(entry: dict) -> dict:
    """Normalize a single rightsList entry to SPDX form when confidently matched.

    Reads `rights`, then `rightsIdentifier`, then `rightsUri` until something
    matches. Fills SPDX-aligned fields on success and leaves unknown licenses
    untouched (no destructive overwrite).
    """
    if not isinstance(entry, dict):
        return entry

    spdx = None
    for key in ("rights", "rightsIdentifier", "rightsUri"):
        candidate = entry.get(key)
        if isinstance(candidate, str):
            spdx = _match_license(candidate)
            if spdx:
                break
    if not spdx:
        return entry

    rec = _BY_SPDX[spdx]
    out = dict(entry)
    out["rights"] = rec["name"]
    out["rightsIdentifier"] = spdx
    out["rightsIdentifierScheme"] = "SPDX"
    out["schemeUri"] = "https://spdx.org/licenses/"
    if not out.get("rightsUri"):
        out["rightsUri"] = rec["uri"]
    return out


_CC_URL_RE = re.compile(
    r"https?://creativecommons\.org/(?:licenses|publicdomain)/"
    r"([-a-z]+)/(\d+\.\d+)",
    re.IGNORECASE,
)

_CC_SLUG_TO_SPDX = {
    "by": "CC-BY",
    "by-sa": "CC-BY-SA",
    "by-nc": "CC-BY-NC",
    "by-nd": "CC-BY-ND",
    "by-nc-sa": "CC-BY-NC-SA",
    "by-nc-nd": "CC-BY-NC-ND",
    "zero": "CC0",
}


def _match_cc_url(text: str) -> Optional[str]:
    m = _CC_URL_RE.search(text)
    if not m:
        return None
    slug, version = m.group(1).lower(), m.group(2)
    prefix = _CC_SLUG_TO_SPDX.get(slug)
    if not prefix:
        return None
    return f"{prefix}-{version}" if prefix != "CC0" else f"{prefix}-{version}"


_KNOWN_NON_SPDX = frozenset({
    "in copyright", "all rights reserved",
    "copyright not evaluated", "copyright undetermined",
    "other-at", "other-open", "other-closed", "other-nc", "other-pd", "other",
})

_JUNK_PATTERNS = [
    re.compile(r"^(license|rights|copyright|null|not specified|unknown)$", re.I),
    re.compile(r"^(creative commons|creative commons license|cc-nc|cc nc)$", re.I),
    re.compile(r"^sectionTitle$|^sectionContent$", re.I),
    re.compile(r"RESEARCH POSTER PRESENTATION DESIGN", re.I),
    re.compile(r"PosterPresentations\.com", re.I),
    re.compile(r"^Copyright\s+\d{4}", re.I),
    re.compile(r"has received funding from|is funded by", re.I),
    re.compile(r"Funded by the European Union", re.I),
    re.compile(r"does not necessarily reflect", re.I),
    re.compile(r"does not necessarily represent", re.I),
    re.compile(r"Practice Abstract reflects only", re.I),
    re.compile(r"^https?://(?!creativecommons\.org)", re.I),
    re.compile(r"Retrievable, Reusable, Repeatable", re.I),
    re.compile(r"^Universiteit\b|^University\b|^SRUC\b", re.I),
    re.compile(r"collabchem\.com", re.I),
    re.compile(r"Horizon\s+(2020|Europe)", re.I),
    re.compile(r"grant\s+agreement", re.I),
    re.compile(r"innovation programme", re.I),
    re.compile(r"Environmental Protection Agency", re.I),
    re.compile(r"views expressed in this", re.I),
    re.compile(r"endorsed by|endorsement", re.I),
    re.compile(r"Deutsche Forschungsgemeinschaft", re.I),
    re.compile(r"Norwegian Financial Mechanism", re.I),
    re.compile(r"zenodo-freetoread", re.I),
    re.compile(r"National Science Foundation", re.I),
    re.compile(r"Murray.Darling Basin", re.I),
    re.compile(r"Helmholtz Association", re.I),
    re.compile(r"^@\w+$", re.I),
    re.compile(r"^Open Access$", re.I),
    re.compile(r"This (project|material|work) is supported", re.I),
    re.compile(r"based upon work supported by", re.I),
    re.compile(r"^cc-?nc$", re.I),
    re.compile(r"POSTER PRESENTATION TEMPLATE", re.I),
    re.compile(r"poster template was developed", re.I),
    re.compile(r"Forschungsgemeinschaft|Forschungsdateninfrastruktur", re.I),
    re.compile(r"Helmholtz (Alliance|Young)", re.I),
    re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"),
    re.compile(r"^Copyright\s+(©\s*)?\w", re.I),
    re.compile(r"postersession\.com", re.I),
    re.compile(r"co-?funded with taxes|state parliament", re.I),
    re.compile(r"L\s*A\s*T\s*E\s*X\s*Tik\s*Z", re.I),
    re.compile(r"Science Foundation Ireland", re.I),
]


def _is_rights_junk(text: str) -> bool:
    if not text or not text.strip():
        return True
    text = text.strip()
    if len(text) > 200:
        return True
    for pat in _JUNK_PATTERNS:
        if pat.search(text):
            return True
    return False


def _coerce_to_dict(entry) -> Optional[Dict]:
    if isinstance(entry, dict):
        return entry
    if isinstance(entry, str):
        text = entry.strip()
        if not text:
            return None
        return {"rights": text}
    return None


def normalize_rights_list(rights_list) -> list:
    if isinstance(rights_list, str):
        rights_list = [rights_list]
    if not isinstance(rights_list, list):
        return rights_list

    out = []
    for raw in rights_list:
        entry = _coerce_to_dict(raw)
        if entry is None:
            continue

        all_text = " ".join(
            str(v) for v in entry.values() if isinstance(v, str)
        ).strip()

        if entry.get("rightsIdentifier") or entry.get("rights"):
            norm_id = (entry.get("rightsIdentifier") or "").strip().lower()
            norm_name = (entry.get("rights") or "").strip().lower()
            if norm_id in _KNOWN_NON_SPDX or norm_name in _KNOWN_NON_SPDX:
                out.append(entry)
                continue

        spdx_from_url = None
        for key in ("rightsUri", "rightsURI", "rights"):
            val = entry.get(key, "")
            if isinstance(val, str):
                spdx_from_url = _match_cc_url(val)
                if spdx_from_url:
                    break
        if not spdx_from_url:
            spdx_from_url = _match_cc_url(all_text)

        if spdx_from_url and spdx_from_url in _BY_SPDX:
            rec = _BY_SPDX[spdx_from_url]
            out.append({
                "rights": rec["name"],
                "rightsIdentifier": rec["spdx"],
                "rightsIdentifierScheme": "SPDX",
                "schemeUri": "https://spdx.org/licenses/",
                "rightsUri": rec["uri"],
            })
            continue

        normalized = normalize_rights_entry(entry)
        if normalized.get("rightsIdentifierScheme") == "SPDX":
            out.append(normalized)
            continue

        if _is_rights_junk(all_text):
            continue
        if any(
            _is_rights_junk(str(v).strip())
            for v in entry.values()
            if isinstance(v, str) and v.strip()
        ):
            continue

        out.append(entry)

    return out


# ---------------------------------------------------------------------------
# Subject normalization
# ---------------------------------------------------------------------------


def normalize_subject_value(s: str) -> str:
    if not isinstance(s, str):
        return s
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_award_number(s: str) -> Optional[str]:
    """Cleanup for fundingReferences[].awardNumber.

    Grant codes are alphanumeric identifiers like 'OT2OD032644' or
    'GBMF3859.01'. Whitespace, surrounding punctuation, and casing drift
    cause near-duplicates downstream. We strip outer whitespace, drop
    leading/trailing punctuation, and uppercase.

    No fuzzy matching — same rule as SPDX integer-exact: numbers and
    digits in award codes are part of the identifier and must not drift.
    Returns None for empty input.
    """
    if not isinstance(s, str):
        return s
    cleaned = unicodedata.normalize("NFKC", s).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    # Strip surrounding punctuation but keep internal . - / _ which appear
    # in real codes (GBMF3859.01, NSF-AGS-1234).
    cleaned = cleaned.strip(" .,;:()[]{}\"'")
    if not cleaned:
        return None
    return cleaned.upper()


def normalize_funding_references(funding_refs: list) -> list:
    """Cleanup awardNumber + funderName whitespace on each entry.
    Strip awardUri/schemeUri values that are not valid URLs."""
    if not isinstance(funding_refs, list):
        return funding_refs
    for fr in funding_refs:
        if not isinstance(fr, dict):
            continue
        if "awardNumber" in fr:
            fixed = normalize_award_number(fr["awardNumber"])
            if fixed is None:
                fr.pop("awardNumber", None)
            else:
                fr["awardNumber"] = fixed
        if "funderName" in fr and isinstance(fr["funderName"], str):
            fr["funderName"] = re.sub(
                r"\s+", " ", unicodedata.normalize("NFKC", fr["funderName"])
            ).strip()
        for uri_key in ("awardUri", "schemeUri"):
            val = fr.get(uri_key, "")
            if isinstance(val, str) and val and not val.startswith(("http://", "https://")):
                fr.pop(uri_key, None)
    return funding_refs


def normalize_subjects(subjects: list) -> list:
    """Cleanup + dedupe (case-insensitive, keep first occurrence's casing)."""
    if not isinstance(subjects, list):
        return subjects
    seen = set()
    out = []
    for item in subjects:
        if isinstance(item, dict):
            val = normalize_subject_value(item.get("subject", ""))
            if not val:
                continue
            key = val.lower()
            if key in seen:
                continue
            seen.add(key)
            new_item = dict(item)
            new_item["subject"] = val
            out.append(new_item)
        elif isinstance(item, str):
            val = normalize_subject_value(item)
            if not val:
                continue
            key = val.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(val)
        else:
            out.append(item)
    return out
