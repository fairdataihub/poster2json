"""
Funder enrichment via ROR.

ROR's `/organizations?affiliation=` matcher is the same one we use for
affiliations, but funder records also carry a `FundRef` external_id (the
Crossref Funder Registry DOI prefix `10.13039/...`) which is the canonical
identifier most current funder workflows expect.

Match criteria are stricter than for affiliations:
  - matching_type EXACT/PHRASE OR score >= 0.95 (same as ror.py)
  - organization.types contains "funder"

When matched, populate:
  funderIdentifier     = "https://doi.org/10.13039/<fundref>" if FundRef present
                         else the ROR URL
  funderIdentifierType = "Crossref Funder ID" or "ROR" accordingly
  schemeUri            = the relevant scheme base URL
  funderName           = ROR canonical display name (replaces messy input)
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
TIMEOUT = 1.5
RATE_LIMIT = 0.5
CACHE_PATH = Path.home() / ".cache" / "poster2json" / "funders.json"


def _normalize_query(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _ror_display_name(org: dict) -> Optional[str]:
    for n in org.get("names", []):
        if "ror_display" in n.get("types", []):
            return n.get("value")
    return None


def _fundref_id(org: dict) -> Optional[str]:
    for ext in org.get("external_ids", []) or []:
        if ext.get("type") == "fundref":
            preferred = ext.get("preferred")
            if preferred:
                return preferred
            allv = ext.get("all") or []
            if allv:
                return allv[0]
    return None


class FunderClient:
    """Disk-cached, rate-limited ROR funder matcher.

    Sibling of poster2json.ror.RorClient with stricter result criteria
    (must be tagged 'funder' in ROR types) and a FundRef-DOI-preferring
    output shape.
    """

    def __init__(self, enabled: bool = True, cache_path: Path = CACHE_PATH):
        env = os.environ.get("POSTER2JSON_FUNDER", "1")
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
        if delta < RATE_LIMIT:
            time.sleep(RATE_LIMIT - delta)
        self._last_call = time.time()

    def lookup(self, name: str) -> Optional[dict]:
        """Return {'id', 'name', 'scheme'} or None.

        scheme is "Crossref Funder ID" when a FundRef DOI is available,
        otherwise "ROR" (the URL becomes the identifier).
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
            with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
                data = json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            if not self._warned:
                print(
                    f"[funders] lookup failed; disabling for this run: {e}",
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
            if mtype in ("EXACT", "PHRASE"):
                accept = True
            else:
                accept = score >= 0.95
            if not accept:
                break
            org = item.get("organization", {})
            types = org.get("types", []) or []
            if "funder" not in types:
                # Matched ROR but not flagged as a funder — skip silently.
                # Common case: bare acronym like "NIH" hits a sub-institute.
                break
            display = _ror_display_name(org)
            ror_id = org.get("id")
            fundref = _fundref_id(org)
            if not display or not ror_id:
                break
            if fundref:
                match = {
                    "id": f"https://doi.org/10.13039/{fundref}",
                    "name": display,
                    "scheme": "Crossref Funder ID",
                    "scheme_uri": "https://doi.org/10.13039",
                }
            else:
                match = {
                    "id": ror_id,
                    "name": display,
                    "scheme": "ROR",
                    "scheme_uri": "https://ror.org",
                }
            break

        self._cache[key] = match
        self._save_cache()
        return match


def enrich_funding_references(funding_refs: list, client: FunderClient) -> list:
    """Populate funderIdentifier/Type/schemeUri on entries with a recognisable
    funder name. Replaces the messy input name with ROR's canonical form."""
    if not isinstance(funding_refs, list):
        return funding_refs
    for fr in funding_refs:
        if not isinstance(fr, dict):
            continue
        # Skip if already has a non-empty funder identifier
        if fr.get("funderIdentifier"):
            continue
        name = fr.get("funderName")
        if not isinstance(name, str):
            continue
        m = client.lookup(name)
        if not m:
            continue
        fr["funderName"] = m["name"]
        fr["funderIdentifier"] = m["id"]
        fr["funderIdentifierType"] = m["scheme"]
        fr.setdefault("schemeUri", m["scheme_uri"])
    return funding_refs


_default_client: Optional[FunderClient] = None


def get_default_client() -> FunderClient:
    global _default_client
    if _default_client is None:
        _default_client = FunderClient()
    return _default_client
