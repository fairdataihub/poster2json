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
ROR_TIMEOUT = 1.5
ROR_RATE_LIMIT = 0.5
CACHE_PATH = Path.home() / ".cache" / "poster2json" / "ror.json"


def _normalize_query(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


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

        self._throttle()
        url = f"{ROR_API}?affiliation={urllib.parse.quote(key)}"
        try:
            with urllib.request.urlopen(url, timeout=ROR_TIMEOUT) as r:
                data = json.loads(r.read())
        except Exception as e:  # noqa: BLE001 — best-effort enrichment
            if not self._warned:
                print(
                    f"[ror] lookup failed; disabling ROR enrichment for this run: {e}",
                    file=sys.stderr,
                )
                self._warned = True
                self.enabled = False
            return None

        match = None
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
                match = {"id": rid, "name": display}
            break

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


def enrich_publisher(publisher, client: RorClient):
    if not isinstance(publisher, dict):
        return publisher
    if publisher.get("publisherIdentifier"):
        return publisher
    name = publisher.get("name")
    if not isinstance(name, str):
        return publisher
    m = client.lookup(name)
    if m:
        out = dict(publisher)
        out["name"] = m["name"]
        out["publisherIdentifier"] = m["id"]
        return out
    return publisher


_default_client: Optional[RorClient] = None


def get_default_client() -> RorClient:
    """Process-wide singleton — avoids re-loading cache on every poster."""
    global _default_client
    if _default_client is None:
        _default_client = RorClient()
    return _default_client
