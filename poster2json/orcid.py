"""
ORCID enrichment for poster creators.

Searches the ORCID expanded-search endpoint to match creators by name +
affiliation.  Only attaches an ORCID when there is a single unambiguous
hit (``num-found == 1``) whose name matches the query.

Authentication: set ``ORCID_CLIENT_ID`` and ``ORCID_CLIENT_SECRET`` env
vars to use the authenticated Member API (24 req/s).  Without them, falls
back to the public API (2 req/s).

Always-on by default; opt out with ``POSTER2JSON_ORCID=0``.  Disk-cached
at ``~/.cache/poster2json/orcid.json``;
auto-disables after the first network failure of a run.
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


ORCID_PUBLIC_API = "https://pub.orcid.org/v3.0/expanded-search/"
ORCID_MEMBER_API = "https://pub.orcid.org/v3.0/expanded-search/"
ORCID_TOKEN_URL = "https://orcid.org/oauth/token"
TIMEOUT = 3.0
RATE_LIMIT_PUBLIC = 0.5
RATE_LIMIT_AUTHENTICATED = 0.042
CACHE_PATH = Path.home() / ".cache" / "poster2json" / "orcid.json"


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _names_match(query: str, result: str) -> bool:
    """Case- and accent-insensitive name comparison."""
    if not query or not result:
        return False
    q = unicodedata.normalize("NFKD", query.strip().lower())
    q = "".join(c for c in q if not unicodedata.combining(c))
    r = unicodedata.normalize("NFKD", result.strip().lower())
    r = "".join(c for c in r if not unicodedata.combining(c))
    return q == r


class OrcidClient:
    """Disk-cached, rate-limited ORCID lookup.

    Uses the authenticated Member API when ORCID_CLIENT_ID and
    ORCID_CLIENT_SECRET env vars are set (24 req/s), otherwise falls
    back to the public API (2 req/s).
    """

    def __init__(self, enabled: bool = True, cache_path: Path = CACHE_PATH):
        env = os.environ.get("POSTER2JSON_ORCID", "1")
        self.enabled = enabled and env != "0"
        self.cache_path = cache_path
        self._cache: dict = {}
        self._last_call = 0.0
        self._warned = False
        self._access_token: Optional[str] = None
        self._api_url = ORCID_PUBLIC_API
        self._rate_limit = RATE_LIMIT_PUBLIC
        if self.enabled:
            self._load_cache()
            self._try_authenticate()

    def _try_authenticate(self):
        client_id = os.environ.get("ORCID_CLIENT_ID")
        client_secret = os.environ.get("ORCID_CLIENT_SECRET")
        if not client_id or not client_secret:
            return
        try:
            body = urllib.parse.urlencode({
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
                "scope": "/read-public",
            }).encode()
            req = urllib.request.Request(
                ORCID_TOKEN_URL, data=body,
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                token_data = json.loads(r.read())
            self._access_token = token_data["access_token"]
            self._api_url = ORCID_MEMBER_API
            self._rate_limit = RATE_LIMIT_AUTHENTICATED
            print(
                f"[orcid] Authenticated (client {client_id[:10]}..., 24 req/s)",
                file=sys.stderr,
            )
        except Exception as e:
            print(
                f"[orcid] OAuth failed, falling back to public API: {e}",
                file=sys.stderr,
            )

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
        if delta < self._rate_limit:
            time.sleep(self._rate_limit - delta)
        self._last_call = time.time()

    def lookup(
        self, given: str, family: str, affiliation: Optional[str] = None
    ) -> Optional[str]:
        """Return an ORCID iD (``0000-0002-...``) or ``None``.

        Requires *affiliation* as a disambiguator — name-only searches
        are too ambiguous and return ``None`` immediately.
        """
        if not self.enabled:
            return None
        given = _normalize(given) if given else ""
        family = _normalize(family) if family else ""
        if not given or not family:
            return None
        if not affiliation:
            return None
        affiliation = _normalize(affiliation)

        key = f"{given.lower()}|{family.lower()}|{affiliation.lower()}"
        if key in self._cache:
            return self._cache[key]

        parts = [
            f'given-names:"{given}"',
            f'family-name:"{family}"',
            f'affiliation-org-name:"{affiliation}"',
        ]
        q = " AND ".join(parts)

        self._throttle()
        url = f"{self._api_url}?q={urllib.parse.quote(q)}&rows=5"
        headers = {"Accept": "application/json"}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                data = json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            if not self._warned:
                print(
                    f"[orcid] lookup failed; disabling for this run: {e}",
                    file=sys.stderr,
                )
                self._warned = True
                self.enabled = False
            return None

        match = None
        num = data.get("num-found", 0)
        results = data.get("expanded-result") or []

        if num == 1 and len(results) == 1:
            hit = results[0]
            if _names_match(given, hit.get("given-names", "")) and _names_match(
                family, hit.get("family-names", "")
            ):
                match = hit.get("orcid-id")

        self._cache[key] = match
        self._save_cache()
        return match


# ------------------------------------------------------------------
# Enrichment helpers
# ------------------------------------------------------------------


def _creator_has_orcid(creator: dict) -> bool:
    for ni in creator.get("nameIdentifiers", []):
        if isinstance(ni, dict) and ni.get("nameIdentifierScheme") == "ORCID":
            return True
    return False


def _creator_affiliation_name(creator: dict) -> Optional[str]:
    for aff in creator.get("affiliation") or []:
        if isinstance(aff, str) and aff.strip():
            return aff.strip()
        if isinstance(aff, dict):
            name = aff.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return None


def enrich_creators_orcid(creators: list, client: OrcidClient) -> list:
    """Add ORCID to creators that have givenName + familyName + affiliation
    but no existing ORCID identifier."""
    if not isinstance(creators, list) or not client.enabled:
        return creators
    for creator in creators:
        if not isinstance(creator, dict):
            continue
        if _creator_has_orcid(creator):
            continue
        given = creator.get("givenName")
        family = creator.get("familyName")
        if not given or not family:
            continue
        affiliation = _creator_affiliation_name(creator)
        orcid = client.lookup(given, family, affiliation)
        if not orcid:
            continue
        creator.setdefault("nameIdentifiers", [])
        creator["nameIdentifiers"].append(
            {
                "nameIdentifier": f"https://orcid.org/{orcid}",
                "nameIdentifierScheme": "ORCID",
                "schemeURI": "https://orcid.org",
            }
        )
    return creators


# ------------------------------------------------------------------
# Singleton
# ------------------------------------------------------------------

_default_client: Optional[OrcidClient] = None


def get_default_client() -> OrcidClient:
    global _default_client
    if _default_client is None:
        _default_client = OrcidClient()
    return _default_client
