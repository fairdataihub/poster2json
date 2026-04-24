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
            "CC-BY-4.0", "CC BY 4.0", "CCBY4.0",
            "Creative Commons Attribution 4.0 International",
            "Creative Commons Attribution 4.0",
            "Attribution 4.0 International",
        ],
    },
    {
        "spdx": "CC-BY-SA-4.0",
        "name": "Creative Commons Attribution-ShareAlike 4.0 International",
        "uri": "https://creativecommons.org/licenses/by-sa/4.0/",
        "aliases": [
            "CC-BY-SA-4.0", "CC BY-SA 4.0", "CCBYSA4.0",
            "Creative Commons Attribution-ShareAlike 4.0 International",
            "Attribution-ShareAlike 4.0 International",
        ],
    },
    {
        "spdx": "CC-BY-NC-4.0",
        "name": "Creative Commons Attribution-NonCommercial 4.0 International",
        "uri": "https://creativecommons.org/licenses/by-nc/4.0/",
        "aliases": [
            "CC-BY-NC-4.0", "CC BY-NC 4.0", "CCBYNC4.0",
            "Creative Commons Attribution-NonCommercial 4.0 International",
            "Attribution-NonCommercial 4.0 International",
        ],
    },
    {
        "spdx": "CC-BY-ND-4.0",
        "name": "Creative Commons Attribution-NoDerivatives 4.0 International",
        "uri": "https://creativecommons.org/licenses/by-nd/4.0/",
        "aliases": [
            "CC-BY-ND-4.0", "CC BY-ND 4.0",
            "Creative Commons Attribution-NoDerivatives 4.0 International",
        ],
    },
    {
        "spdx": "CC-BY-NC-SA-4.0",
        "name": "Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International",
        "uri": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
        "aliases": [
            "CC-BY-NC-SA-4.0", "CC BY-NC-SA 4.0",
            "Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International",
        ],
    },
    {
        "spdx": "CC-BY-NC-ND-4.0",
        "name": "Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International",
        "uri": "https://creativecommons.org/licenses/by-nc-nd/4.0/",
        "aliases": [
            "CC-BY-NC-ND-4.0", "CC BY-NC-ND 4.0",
            "Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International",
        ],
    },
    {
        "spdx": "CC-BY-3.0",
        "name": "Creative Commons Attribution 3.0 Unported",
        "uri": "https://creativecommons.org/licenses/by/3.0/",
        "aliases": [
            "CC-BY-3.0", "CC BY 3.0",
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
            "Creative Commons Zero 1.0 Universal",
            "Creative Commons Zero",
            "Public Domain Dedication",
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
    if not out.get("rights"):
        out["rights"] = rec["name"]
    out["rightsIdentifier"] = spdx
    out["rightsIdentifierScheme"] = "SPDX"
    out["schemeUri"] = "https://spdx.org/licenses/"
    if not out.get("rightsUri"):
        out["rightsUri"] = rec["uri"]
    return out


def normalize_rights_list(rights_list) -> list:
    if not isinstance(rights_list, list):
        return rights_list
    return [normalize_rights_entry(e) for e in rights_list]


# ---------------------------------------------------------------------------
# Subject normalization
# ---------------------------------------------------------------------------


def normalize_subject_value(s: str) -> str:
    if not isinstance(s, str):
        return s
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


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
