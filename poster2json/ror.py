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
            mtype = item.get("matching_type", "")
            score = item.get("score", 0.0)
            # ROR's `chosen=True` alone is too permissive: COMMON TERMS at
            # 0.90 has matched "Dept of CS, Univ. of California, Berkeley"
            # to "California Coast University". Accept EXACT and PHRASE
            # outright; require >=0.95 for fuzzier modes.
            if mtype in ("EXACT", "PHRASE"):
                accept = True
            else:
                accept = score >= 0.95
            if not accept:
                break
            org = item.get("organization", {})
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
    """Resolve affiliations against ROR and collapse same-org duplicates.

    Operates in place on a creators/contributors list. Each affiliation (a
    string or a ``{"name": ...}`` object — model-supplied identifiers were
    already stripped) is looked up in ROR by name:

    - **Unresolved** affiliations keep their original value and are
      de-duplicated by normalized name.
    - A ROR org reached by a **single** distinct source name is emitted once,
      using ROR's canonical display name plus the identifier.
    - When **several distinct** source names resolve to the **same** ROR org
      (e.g. two departments of one university), each distinct name is kept with
      the shared identifier, preserving the sub-unit detail instead of
      collapsing to one canonical entry.

    True duplicates (the same name listed twice) always collapse to one entry.
    """
    if not isinstance(persons, list):
        return persons
    for p in persons:
        if not isinstance(p, dict):
            continue
        affs = p.get("affiliation")
        if not isinstance(affs, list):
            continue

        # Look each item up once, remembering its original display name.
        records = []  # (display_name | None, ror_match | None, raw_item)
        for item in affs:
            name = _affiliation_display_name(item)
            ror = client.lookup(name) if name else None
            records.append((name, ror, item))

        # How many distinct source names map to each resolved ROR id?
        names_per_id = {}
        for name, ror, _ in records:
            if ror and name:
                names_per_id.setdefault(ror["id"], set()).add(_norm_name(name))

        out = []
        seen = set()
        for name, ror, raw in records:
            if ror and name:
                rid = ror["id"]
                if len(names_per_id.get(rid, ())) > 1:
                    # Several distinct sub-units of one org: keep each name.
                    key = ("id+name", rid, _norm_name(name))
                    display = name
                else:
                    # Single source name: use ROR's canonical display name.
                    key = ("id", rid)
                    display = ror["name"]
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "name": display,
                    "affiliationIdentifier": rid,
                    "affiliationIdentifierScheme": "ROR",
                    "schemeUri": "https://ror.org/",
                })
            else:
                # Unresolved: keep original value, de-dupe by normalized name.
                if name is not None:
                    key = ("name", _norm_name(name))
                    if key in seen:
                        continue
                    seen.add(key)
                out.append(raw)
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
