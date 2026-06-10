"""
ROR enrichment for affiliations and publishers.

Always-on by default; opt out with `POSTER2JSON_ROR=0`. Uses ROR's
`/organizations?affiliation=` endpoint, which runs ROR's own matcher
tuned for messy strings from paper affiliations.

When a chosen match is found, the original name string is replaced with
ROR's canonical display name and an identifier is attached.
"""
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional


ROR_API = "https://api.ror.org/organizations"
ROR_TIMEOUT = 5.0
ROR_RATE_LIMIT = 0.16
ROR_MAX_CONSECUTIVE_FAILURES = 25
ROR_RETRY_ATTEMPTS = 3
CACHE_PATH = Path.home() / ".cache" / "poster2json" / "ror.json"


def _normalize_query(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _strip_trailing_country(s: str) -> Optional[str]:
    """Strip a trailing ', Country' suffix common in poster affiliations.

    Returns the stripped string if it looks like a country was removed,
    else None.  Only strips if what follows the last comma is 1-3 words
    with no digits (to avoid stripping department info).
    """
    if "," not in s:
        return None
    base, _, tail = s.rpartition(",")
    tail = tail.strip()
    if not tail or not base.strip():
        return None
    words = tail.split()
    if 1 <= len(words) <= 3 and not any(c.isdigit() for c in tail):
        return base.strip()
    return None


def _ror_display_name(org: dict) -> Optional[str]:
    for n in org.get("names", []):
        if "ror_display" in n.get("types", []):
            return n.get("value")
    return None


# Institution/sub-unit keywords used to tell a trailing *address* ("La Jolla,
# CA, US") apart from a trailing *sub-unit* ("School of Medicine") after an org
# name. Kept local to ror.py (extract.py's richer copy pulls heavy deps).
_INST_KW = re.compile(
    r"(?i)(univers|institut|instituto|departa|department|dipart|division|"
    r"divisi|school|escuela|colleg|hospital|clinic|laborator|cent(?:er|re|ro)|"
    r"zentrum|facult|academ|foundation|fundac|research|hochschule|polytechni)"
)


def _norm_match(s: str) -> str:
    """Accent- and case-insensitive normalization for exact name comparison,
    preserving commas (org names like 'University of California, San Diego')."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def _org_match_names(org: dict) -> list:
    """Every matchable name for a ROR org: display name, labels, aliases,
    acronyms — anything in the v2 ``names`` array."""
    out = []
    for n in org.get("names", []):
        v = n.get("value")
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
    return out


def _is_geography_tail(rest: str) -> bool:
    """True when the text after an org name is only an address (city/state/
    country/postal), not a further sub-unit — so the affiliation is the org
    plus its location, e.g. 'University of X' + ', La Jolla, CA, US'."""
    if not rest:
        return True
    if _INST_KW.search(rest):
        return False
    segs = [s.strip() for s in rest.split(",") if s.strip()]
    return len(segs) <= 4 and all(len(s) <= 30 for s in segs)


def _affiliation_is_exact(aff_key: str, org: dict) -> bool:
    """True when the affiliation string IS this organization (optionally
    followed only by its address), as opposed to a department/sub-unit that
    merely *contains* the org name. ROR's matcher returns the parent org for
    sub-unit strings (e.g. 'Hamilton Glaucoma Center, …, UCSD' -> UCSD); the
    exact-only policy attaches an identifier only to the former."""
    a = _norm_match(aff_key)
    for nm in _org_match_names(org):
        n = _norm_match(nm)
        if not n:
            continue
        if a == n:
            return True
        if a.startswith(n):
            rest = a[len(n):].lstrip(" ,.;")
            if not rest or _is_geography_tail(rest):
                return True
    return False


class RorClient:
    """Disk-cached, rate-limited ROR matcher.

    One instance per process is sufficient — the in-memory cache dedupes
    repeat lookups within a run; the disk cache survives across runs.
    """

    def __init__(self, enabled: bool = True, cache_path: Path = CACHE_PATH):
        env = os.environ.get("POSTER2JSON_ROR", "1")
        self.enabled = enabled and env != "0"
        self.cache_path = cache_path
        self._cache = {}
        self._last_call = 0.0
        self._warned = False
        self._consecutive_failures = 0
        if self.enabled:
            self._load_cache()

    def _load_cache(self):
        try:
            if self.cache_path.exists():
                self._cache = json.loads(self.cache_path.read_text())
        except (OSError, json.JSONDecodeError):
            self._cache = {}

    def _save_cache(self):
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._cache))
            tmp.replace(self.cache_path)
        except OSError:
            pass

    def _throttle(self):
        delta = time.time() - self._last_call
        if delta < ROR_RATE_LIMIT:
            time.sleep(ROR_RATE_LIMIT - delta)
        self._last_call = time.time()

    def _query_ror(self, key: str) -> Optional[dict]:
        """Single ROR API call with retries. Returns match dict or None."""
        url = f"{ROR_API}?affiliation={urllib.parse.quote(key)}"
        last_err = None
        for attempt in range(ROR_RETRY_ATTEMPTS):
            self._throttle()
            try:
                with urllib.request.urlopen(url, timeout=ROR_TIMEOUT) as r:
                    data = json.loads(r.read())
                self._consecutive_failures = 0
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                if attempt < ROR_RETRY_ATTEMPTS - 1:
                    time.sleep(1.0 * (attempt + 1))
        else:
            self._consecutive_failures += 1
            if self._consecutive_failures >= ROR_MAX_CONSECUTIVE_FAILURES:
                print(
                    f"[ror] {ROR_MAX_CONSECUTIVE_FAILURES} consecutive failures; "
                    f"disabling for this run: {last_err}",
                    file=sys.stderr,
                )
                self.enabled = False
            elif not self._warned:
                print(f"[ror] lookup failed: {last_err}", file=sys.stderr)
                self._warned = True
            return None

        for item in data.get("items", []):
            if not item.get("chosen"):
                continue
            org = item.get("organization", {})
            # Exact-only: attach an identifier only when the affiliation string
            # IS this organization (optionally followed by its address), not a
            # department/sub-unit that merely contains the org name. ROR's
            # matcher (and its score/matching_type) happily map sub-unit strings
            # to the parent org, which over-broadened identifiers before.
            if not _affiliation_is_exact(key, org):
                break
            display = _ror_display_name(org)
            rid = org.get("id")
            if display and rid:
                return {"id": rid, "name": display}
            break
        return None

    def lookup(self, name: str) -> Optional[dict]:
        """Return {'id': ror_url, 'name': canonical_name} or None.

        None means "no confident match" — cached so we don't re-query.
        After the first network failure of a run, ROR is disabled for the
        rest of the run to avoid blocking on a flaky network.
        """
        if not self.enabled or not isinstance(name, str):
            return None
        key = _normalize_query(name)
        if not key:
            return None
        if key in self._cache:
            return self._cache[key]

        match = self._query_ror(key)

        # Retry without trailing country suffix (e.g. "..., Spain")
        if match is None and self.enabled:
            stripped = _strip_trailing_country(key)
            if stripped and stripped not in self._cache:
                match = self._query_ror(stripped)

        self._cache[key] = match
        self._save_cache()
        return match


def _affiliation_display_name(item) -> Optional[str]:
    """Return the human-readable affiliation name (string, or dict ``name``)."""
    if isinstance(item, str):
        return item.strip() or None
    if isinstance(item, dict) and isinstance(item.get("name"), str):
        return item["name"].strip() or None
    return None


def _norm_name(name: str) -> str:
    return unicodedata.normalize("NFKC", name).strip().casefold()


def resolve_person_affiliations(persons: list, client: RorClient) -> list:
    """Attach ROR identifiers to affiliations, never rewriting the text.

    Operates in place on a creators/contributors list. Each affiliation (a
    string or a ``{"name": ...}`` object — model-supplied identifiers were
    already stripped) is looked up in ROR by name. ``RorClient.lookup`` only
    returns a match on an **exact** organization match (the affiliation IS the
    org, optionally followed by its address), so department/sub-unit strings
    resolve to nothing and are left untouched.

    - **Resolved** (exact): the extracted text is kept verbatim and a ROR
      identifier is attached. ROR's canonical display name is *not* substituted,
      so two distinct sub-units of one university stay distinct.
    - **Unresolved**: the original value is kept unchanged.

    True duplicates (the same name listed twice) collapse to one entry.
    """
    if not isinstance(persons, list):
        return persons
    for p in persons:
        if not isinstance(p, dict):
            continue
        affs = p.get("affiliation")
        if not isinstance(affs, list):
            continue

        out = []
        seen = set()
        for item in affs:
            name = _affiliation_display_name(item)
            if name is None:
                out.append(item)
                continue
            dedupe_key = _norm_name(name)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            ror = client.lookup(name)
            if ror:
                out.append({
                    "name": name,  # keep the extracted text; never canonicalize
                    "affiliationIdentifier": ror["id"],
                    "affiliationIdentifierScheme": "ROR",
                    "schemeUri": "https://ror.org/",
                })
            else:
                out.append(item)
        p["affiliation"] = out
    return persons


def _coerce_affiliation_value(aff):
    """Coerce one person's ``affiliation`` into the schema's array form.

    The schema requires ``affiliation`` to be an array of strings/objects, but
    the model sometimes emits a bare string or a single object. Returns a
    non-empty list, or ``None`` to signal the key should be dropped (it was
    null, empty, or contained only junk — ``affiliation`` is optional).
    """
    if isinstance(aff, str):
        s = aff.strip()
        return [s] if s else None
    if isinstance(aff, dict):
        return [aff] if (aff.get("name") or aff.get("affiliationIdentifier")) else None
    if isinstance(aff, list):
        out = []
        for item in aff:
            if isinstance(item, str):
                s = item.strip()
                if s:
                    out.append(s)
            elif isinstance(item, dict):
                if item.get("name") or item.get("affiliationIdentifier"):
                    out.append(item)
            # drop anything else (numbers, None, nested lists)
        return out or None
    return None


def coerce_person_affiliations(persons: list) -> list:
    """Normalize ``affiliation`` on every person to a list (in place).

    A bare string becomes ``[string]``, a single object becomes ``[object]``,
    and null/empty values drop the key. Runs before ROR enrichment so the
    enrichment and the schema both see a proper array.
    """
    if not isinstance(persons, list):
        return persons
    for p in persons:
        if not isinstance(p, dict) or "affiliation" not in p:
            continue
        coerced = _coerce_affiliation_value(p["affiliation"])
        if coerced is None:
            p.pop("affiliation", None)
        else:
            p["affiliation"] = coerced
    return persons


_AFFILIATION_ID_FIELDS = (
    "affiliationIdentifier",
    "affiliationIdentifierScheme",
    "schemeUri",
)


def strip_extracted_affiliation_ids(persons: list) -> list:
    """Drop model-supplied affiliation identifiers so IDs come only from ROR.

    poster2json's policy is that affiliation ROR identifiers are resolved from
    the affiliation *name* via the ROR API — never trusted from whatever the
    model copied off the poster (printed ``ror.org/...`` text or link
    annotations). The prompt does not request an identifier, so any
    ``affiliationIdentifier`` / ``affiliationIdentifierScheme`` / ``schemeUri``
    present was scraped by the model; we remove it here, before enrichment, so
    ``resolve_person_affiliations`` resolves each affiliation by name. Mirrors
    how ``creators[].nameIdentifiers[]`` drop model-emitted scheme fields.
    """
    if not isinstance(persons, list):
        return persons
    for p in persons:
        if not isinstance(p, dict):
            continue
        affs = p.get("affiliation")
        if not isinstance(affs, list):
            continue
        for aff in affs:
            if isinstance(aff, dict):
                for field in _AFFILIATION_ID_FIELDS:
                    aff.pop(field, None)
    return persons


_default_client: Optional[RorClient] = None


def get_default_client() -> RorClient:
    """Process-wide singleton — avoids re-loading cache on every poster."""
    global _default_client
    if _default_client is None:
        _default_client = RorClient()
    return _default_client
