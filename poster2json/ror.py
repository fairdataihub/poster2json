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


def _enrich_affiliation_item(item, client: RorClient):
    if isinstance(item, str):
        m = client.lookup(item)
        if m:
            return {
                "name": m["name"],
                "affiliationIdentifier": m["id"],
                "affiliationIdentifierScheme": "ROR",
                "schemeUri": "https://ror.org/",
            }
        return item
    if isinstance(item, dict):
        if item.get("affiliationIdentifier"):
            return item
        name = item.get("name")
        if not isinstance(name, str):
            return item
        m = client.lookup(name)
        if m:
            out = dict(item)
            out["name"] = m["name"]
            out["affiliationIdentifier"] = m["id"]
            out["affiliationIdentifierScheme"] = "ROR"
            out.setdefault("schemeUri", "https://ror.org/")
            return out
        return item
    return item


def enrich_persons(persons: list, client: RorClient) -> list:
    """Enrich affiliations on a creators or contributors list (in place)."""
    if not isinstance(persons, list):
        return persons
    for p in persons:
        if not isinstance(p, dict):
            continue
        affs = p.get("affiliation")
        if isinstance(affs, list):
            p["affiliation"] = [_enrich_affiliation_item(a, client) for a in affs]
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


def _affiliation_name(item) -> Optional[str]:
    if isinstance(item, str):
        name = item
    elif isinstance(item, dict) and isinstance(item.get("name"), str):
        name = item["name"]
    else:
        return None
    name = unicodedata.normalize("NFKC", name).strip().casefold()
    return name or None


def _affiliation_dedupe_key(item):
    if isinstance(item, dict):
        ident = item.get("affiliationIdentifier")
        if ident:
            return ("id", str(ident).strip().lower())
    name = _affiliation_name(item)
    if name is not None:
        return ("name", name)
    return ("obj", json.dumps(item, sort_keys=True, ensure_ascii=False))


def _affiliation_richness(item) -> int:
    if isinstance(item, dict):
        return 2 if item.get("affiliationIdentifier") else 1
    return 0


def dedupe_person_affiliations(persons: list) -> list:
    """Collapse duplicate affiliation entries on every person (in place).

    Entries are keyed on their ROR identifier when present, else on their
    normalized name, so the same organization listed twice (a recurring model
    artifact) collapses to one. When duplicates collide the richer entry (one
    carrying an identifier) is kept, and a bare-name entry is dropped when an
    identified entry already covers the same organization name.
    """
    if not isinstance(persons, list):
        return persons
    for p in persons:
        if not isinstance(p, dict):
            continue
        affs = p.get("affiliation")
        if not isinstance(affs, list) or len(affs) < 2:
            continue
        order = []
        chosen = {}
        for item in affs:
            key = _affiliation_dedupe_key(item)
            if key not in chosen:
                chosen[key] = item
                order.append(key)
            elif _affiliation_richness(item) > _affiliation_richness(chosen[key]):
                chosen[key] = item
        # Drop bare-name entries already covered by an identified entry.
        identified_names = {
            _affiliation_name(it)
            for it in chosen.values()
            if isinstance(it, dict) and it.get("affiliationIdentifier")
        }
        identified_names.discard(None)
        result = []
        for key in order:
            it = chosen[key]
            if key[0] == "name" and key[1] in identified_names and _affiliation_richness(it) < 2:
                continue
            result.append(it)
        p["affiliation"] = result
    return persons


_default_client: Optional[RorClient] = None


def get_default_client() -> RorClient:
    """Process-wide singleton — avoids re-loading cache on every poster."""
    global _default_client
    if _default_client is None:
        _default_client = RorClient()
    return _default_client
