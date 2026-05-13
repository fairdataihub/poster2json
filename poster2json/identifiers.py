"""
Identifier extraction and enrichment for poster2json.

Extracts well-known scholarly identifiers (ORCID, DOI, ROR, arXiv, etc.)
from raw poster text using regex, and enriches Llama JSON output with
scheme/schemeURI metadata and newly discovered identifiers.
"""

import re
from typing import Dict, List, Optional, Tuple

# ============================
# IDENTIFIER PATTERNS
# ============================

# Each entry: (compiled_regex, scheme_name, scheme_uri, group_index_for_value)
# group_index_for_value: which regex group contains the canonical identifier value

ORCID_RE = re.compile(
    r"(?:https?://orcid\.org/)?((?:\d{4}-){3}\d{3}[\dX])\b"
)
DOI_RE = re.compile(
    r"(?:(?:https?://)?(?:dx\.)?doi\.org/|doi:\s*)(10\.\d{4,9}/[^\s,;\"'}\]>]+)",
    re.IGNORECASE,
)
ARXIV_RE = re.compile(
    r"(?:arXiv:\s*|(?:https?://)?arxiv\.org/abs/)(\d{4}\.\d{4,5}(?:v\d+)?)",
    re.IGNORECASE,
)
ROR_RE = re.compile(
    r"https?://ror\.org/(0[a-z0-9]{6}\d{2})\b"
)
ISNI_RE = re.compile(
    r"https?://isni\.org/isni/(\d{15}[\dX])\b"
)
GRID_RE = re.compile(
    r"https?://grid\.ac/(grid\.\d+\.\w+)\b"
)
CROSSREF_FUNDER_RE = re.compile(
    r"(?:https?://doi\.org/)?10\.13039/(\d+)\b"
)
BARE_ROR_RE = re.compile(r"^0[a-z0-9]{6}\d{2}$")

# Strips the resolver URL from DOIs. Preserves case in the suffix because
# DOI suffixes can be (and are) registered as case-sensitive even though
# Crossref's resolver treats them case-insensitively. Dedup elsewhere uses
# .lower() so this is safe.
DOI_URL_PREFIX_RE = re.compile(
    r"^\s*(?:(?:https?://)?(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE
)


def canonicalize_doi(value: str) -> str:
    """Return a bare DOI ('10.xxxx/...') given any of: bare DOI,
    'doi:10.xxxx/...', 'https://doi.org/10.xxxx/...', 'http://dx.doi.org/...'.
    Non-DOI strings pass through unchanged.
    """
    if not isinstance(value, str):
        return value
    stripped = DOI_URL_PREFIX_RE.sub("", value).strip()
    return stripped if stripped.startswith("10.") else value

# Scheme metadata lookup
SCHEME_TABLE = {
    "orcid": ("ORCID", "https://orcid.org"),
    "doi": ("DOI", "https://doi.org"),
    "arxiv": ("arXiv", "https://arxiv.org/abs"),
    "ror": ("ROR", "https://ror.org"),
    "isni": ("ISNI", "https://isni.org"),
    "grid": ("GRID", "https://grid.ac"),
    "crossref_funder": ("Crossref Funder ID", "https://doi.org/10.13039"),
}


# ============================
# SCHEME INFERENCE
# ============================


def infer_identifier_scheme(value: str) -> Optional[Tuple[str, str]]:
    """
    Given an identifier string, infer its (scheme, schemeURI).

    Returns:
        Tuple of (scheme, schemeURI) or None if unrecognized.
    """
    if not value or not isinstance(value, str):
        return None
    value = value.strip()

    # ORCID: 0000-0002-1234-5678 or https://orcid.org/...
    if ORCID_RE.fullmatch(value) or re.fullmatch(
        r"https?://orcid\.org/(?:\d{4}-){3}\d{3}[\dX]", value
    ):
        return SCHEME_TABLE["orcid"]

    # Crossref Funder DOI — must check before generic DOI
    if re.match(r"(?:https?://doi\.org/)?10\.13039/", value):
        return SCHEME_TABLE["crossref_funder"]

    # DOI: 10.xxxx/... or https://doi.org/10.xxxx/...
    if re.match(r"(?:https?://(?:dx\.)?doi\.org/|doi:)?\s*10\.\d{4,9}/", value, re.IGNORECASE):
        return SCHEME_TABLE["doi"]

    # arXiv
    if re.match(r"(?:arXiv:|(?:https?://)?arxiv\.org/abs/)", value, re.IGNORECASE):
        return SCHEME_TABLE["arxiv"]

    # ROR
    if re.match(r"https?://ror\.org/", value):
        return SCHEME_TABLE["ror"]

    # ISNI
    if re.match(r"https?://isni\.org/isni/", value):
        return SCHEME_TABLE["isni"]

    # GRID
    if re.match(r"https?://grid\.ac/", value):
        return SCHEME_TABLE["grid"]

    return None


# ============================
# TEXT EXTRACTION
# ============================


def extract_identifiers_from_text(raw_text: str) -> Dict[str, List[str]]:
    """
    Scan raw poster text for well-known identifiers.

    Returns:
        Dict keyed by identifier type with lists of unique values found.
        Example: {"orcid": ["0000-0002-1234-5678"], "doi": ["10.1234/example"]}
    """
    if not raw_text:
        return {}

    results: Dict[str, List[str]] = {}

    # Extract Crossref Funder IDs FIRST so we can exclude them from DOI matches
    funder_dois = set()
    for m in CROSSREF_FUNDER_RE.finditer(raw_text):
        funder_id = f"10.13039/{m.group(1)}"
        funder_dois.add(funder_id)
        results.setdefault("crossref_funder", [])
        if funder_id not in results["crossref_funder"]:
            results["crossref_funder"].append(funder_id)

    # ORCIDs
    for m in ORCID_RE.finditer(raw_text):
        orcid = m.group(1)
        results.setdefault("orcid", [])
        if orcid not in results["orcid"]:
            results["orcid"].append(orcid)

    # DOIs (excluding Crossref Funder DOIs)
    for m in DOI_RE.finditer(raw_text):
        doi = m.group(1).rstrip(".")
        if doi in funder_dois or doi.startswith("10.13039/"):
            continue
        results.setdefault("doi", [])
        if doi not in results["doi"]:
            results["doi"].append(doi)

    # arXiv
    for m in ARXIV_RE.finditer(raw_text):
        arxiv_id = m.group(1)
        results.setdefault("arxiv", [])
        if arxiv_id not in results["arxiv"]:
            results["arxiv"].append(arxiv_id)

    # ROR
    for m in ROR_RE.finditer(raw_text):
        ror_id = m.group(1)
        results.setdefault("ror", [])
        if ror_id not in results["ror"]:
            results["ror"].append(ror_id)

    # ISNI
    for m in ISNI_RE.finditer(raw_text):
        isni_id = m.group(1)
        results.setdefault("isni", [])
        if isni_id not in results["isni"]:
            results["isni"].append(isni_id)

    # GRID
    for m in GRID_RE.finditer(raw_text):
        grid_id = m.group(1)
        results.setdefault("grid", [])
        if grid_id not in results["grid"]:
            results["grid"].append(grid_id)

    return results


# ============================
# JSON ENRICHMENT
# ============================


def _existing_identifier_values(data: dict, field: str) -> set:
    """Collect existing identifier values from a list-of-dicts field."""
    values = set()
    for item in data.get(field, []):
        if isinstance(item, dict):
            for key in ("identifier", "funderIdentifier", "value"):
                if key in item:
                    values.add(item[key].strip().lower())
    return values


def _enrich_existing_identifiers(data: dict) -> dict:
    """Add scheme/schemeURI to identifiers already present in the JSON."""
    # Top-level identifiers[]
    for item in data.get("identifiers", []):
        if not isinstance(item, dict):
            continue
        value = item.get("identifier", "")
        result = infer_identifier_scheme(value)
        if result:
            scheme, uri = result
            if "identifierType" not in item or not item["identifierType"]:
                item["identifierType"] = scheme
            # Canonicalize DOI form (strip https://doi.org/ etc.)
            if scheme == "DOI" and isinstance(value, str):
                item["identifier"] = canonicalize_doi(value)

    # creators[*].nameIdentifiers[]
    for creator in data.get("creators", []):
        if not isinstance(creator, dict):
            continue
        for ni in creator.get("nameIdentifiers", []):
            if not isinstance(ni, dict):
                continue
            value = ni.get("nameIdentifier", "")
            result = infer_identifier_scheme(value)
            if result:
                scheme, uri = result
                if "nameIdentifierScheme" not in ni or not ni["nameIdentifierScheme"]:
                    ni["nameIdentifierScheme"] = scheme
                if "schemeURI" not in ni or not ni["schemeURI"]:
                    ni["schemeURI"] = uri
                # Fix 1: bare ORCIDs -> full URL format
                if scheme == "ORCID":
                    m = ORCID_RE.search(value)
                    if m and not value.startswith("http"):
                        ni["nameIdentifier"] = f"https://orcid.org/{m.group(1)}"

    # creators[*].affiliation[*].affiliationIdentifier -- normalize bare ROR IDs
    for creator in data.get("creators", []):
        if not isinstance(creator, dict):
            continue
        for aff in creator.get("affiliation") or []:
            if not isinstance(aff, dict):
                continue
            aid = aff.get("affiliationIdentifier", "")
            if isinstance(aid, str) and BARE_ROR_RE.match(aid):
                aff["affiliationIdentifier"] = f"https://ror.org/{aid}"
            aid = aff.get("affiliationIdentifier", "")
            if isinstance(aid, str) and "ror.org/" in aid:
                if not aff.get("affiliationIdentifierScheme"):
                    aff["affiliationIdentifierScheme"] = "ROR"
                aff.setdefault("schemeUri", "https://ror.org/")

    # fundingReferences[*].funderIdentifier
    for fr in data.get("fundingReferences", []):
        if not isinstance(fr, dict):
            continue
        fid = fr.get("funderIdentifier", "")
        result = infer_identifier_scheme(fid)
        if result:
            scheme, uri = result
            if "funderIdentifierType" not in fr or not fr["funderIdentifierType"]:
                fr["funderIdentifierType"] = scheme
            if "schemeUri" not in fr or not fr["schemeUri"]:
                fr["schemeUri"] = uri
            # Fix 6: keep Crossref Funder DOIs in full URL format for Zenodo
            if scheme == "Crossref Funder ID" and isinstance(fid, str):
                bare = canonicalize_doi(fid)
                if bare.startswith("10.13039/"):
                    fr["funderIdentifier"] = f"https://doi.org/{bare}"

    # relatedIdentifiers[*].relatedIdentifier — canonicalize DOIs
    for ri in data.get("relatedIdentifiers", []):
        if not isinstance(ri, dict):
            continue
        rid = ri.get("relatedIdentifier", "")
        if isinstance(rid, str):
            rid_type = ri.get("relatedIdentifierType", "")
            if rid_type == "DOI" or DOI_URL_PREFIX_RE.match(rid):
                ri["relatedIdentifier"] = canonicalize_doi(rid)

    return data


def _add_extracted_identifiers(data: dict, extracted: Dict[str, List[str]]) -> dict:
    """Place regex-extracted identifiers into the correct schema locations."""
    if not extracted:
        return data

    # --- DOIs and arXiv → identifiers[] ---
    existing_ids = _existing_identifier_values(data, "identifiers")
    if "identifiers" not in data:
        data["identifiers"] = []

    for doi in extracted.get("doi", []):
        if doi.lower() not in existing_ids:
            data["identifiers"].append({
                "identifier": doi,
                "identifierType": "DOI",
            })
            existing_ids.add(doi.lower())

    for arxiv_id in extracted.get("arxiv", []):
        full_id = f"arXiv:{arxiv_id}"
        if full_id.lower() not in existing_ids and arxiv_id.lower() not in existing_ids:
            data["identifiers"].append({
                "identifier": full_id,
                "identifierType": "arXiv",
            })
            existing_ids.add(full_id.lower())

    # --- ORCIDs → creators[*].nameIdentifiers[] ---
    orcids = extracted.get("orcid", [])
    if orcids:
        creators = data.get("creators", [])
        existing_orcids = set()
        for c in creators:
            if isinstance(c, dict):
                for ni in c.get("nameIdentifiers", []):
                    if isinstance(ni, dict):
                        v = ni.get("nameIdentifier", "")
                        # Normalize to bare ORCID for dedup
                        m = ORCID_RE.search(v)
                        if m:
                            existing_orcids.add(m.group(1))

        new_orcids = [o for o in orcids if o not in existing_orcids]

        if new_orcids and creators:
            if len(new_orcids) == len(creators):
                # 1:1 mapping by position
                for i, orcid in enumerate(new_orcids):
                    if isinstance(creators[i], dict):
                        creators[i].setdefault("nameIdentifiers", [])
                        creators[i]["nameIdentifiers"].append({
                            "nameIdentifier": f"https://orcid.org/{orcid}",
                            "nameIdentifierScheme": "ORCID",
                            "schemeURI": "https://orcid.org",
                        })
            else:
                # Attach all to first creator
                if isinstance(creators[0], dict):
                    creators[0].setdefault("nameIdentifiers", [])
                    for orcid in new_orcids:
                        creators[0]["nameIdentifiers"].append({
                            "nameIdentifier": f"https://orcid.org/{orcid}",
                            "nameIdentifierScheme": "ORCID",
                            "schemeURI": "https://orcid.org",
                        })

    # --- Crossref Funder IDs → fundingReferences[*].funderIdentifier ---
    funder_ids = extracted.get("crossref_funder", [])
    if funder_ids:
        if "fundingReferences" not in data:
            data["fundingReferences"] = []

        existing_funder_ids = set()
        for fr in data["fundingReferences"]:
            if isinstance(fr, dict) and "funderIdentifier" in fr:
                existing_funder_ids.add(fr["funderIdentifier"].lower())

        # Assign to existing fundingReferences without funderIdentifier first
        unassigned = []
        for fid in funder_ids:
            if fid.lower() in existing_funder_ids:
                continue
            assigned = False
            for fr in data["fundingReferences"]:
                if isinstance(fr, dict) and not fr.get("funderIdentifier"):
                    fr["funderIdentifier"] = fid
                    fr["funderIdentifierType"] = "Crossref Funder ID"
                    fr["schemeUri"] = "https://doi.org/10.13039"
                    assigned = True
                    existing_funder_ids.add(fid.lower())
                    break
            if not assigned:
                unassigned.append(fid)

        # Remaining funder IDs get new entries
        for fid in unassigned:
            data["fundingReferences"].append({
                "funderName": "Unknown Funder",
                "funderIdentifier": fid,
                "funderIdentifierType": "Crossref Funder ID",
                "schemeUri": "https://doi.org/10.13039",
            })

    # ROR and ISNI: informational only in V1 — no forced placement
    return data


_LICENSE_URL_RE = re.compile(
    r"https?://(creativecommons\.org|spdx\.org|opensource\.org/licenses)",
    re.IGNORECASE,
)


def merge_pdf_link_annotations(data: dict, pdf_links: List[str]) -> dict:
    """Merge PDF link annotations into the JSON output.

    Classifies each URI and places it in the correct schema field:
    - DOIs -> identifiers[]
    - arXiv -> identifiers[]
    - ORCIDs -> creators[*].nameIdentifiers[]
    - Other scholarly URLs -> relatedIdentifiers[] with relationType "References"

    Skips license URLs (creativecommons.org, spdx.org) since those are
    handled by normalize_rights_list.
    """
    if not pdf_links:
        return data

    result = data.copy()

    scholarly_text = "\n".join(pdf_links)
    extracted = extract_identifiers_from_text(scholarly_text)
    if extracted:
        result = _add_extracted_identifiers(result, extracted)

    scholarly_uris = set()
    for vals in extracted.values():
        for v in vals:
            scholarly_uris.add(v.lower())

    existing_related = set()
    for ri in result.get("relatedIdentifiers", []):
        if isinstance(ri, dict):
            existing_related.add(ri.get("relatedIdentifier", "").lower())

    existing_ids = set()
    for ident in result.get("identifiers", []):
        if isinstance(ident, dict):
            val = ident.get("identifier", "").lower()
            existing_ids.add(val)
            if val.startswith("10."):
                existing_ids.add(f"https://doi.org/{val}")

    new_related = []
    for uri in pdf_links:
        uri_lower = uri.lower().rstrip("/")
        if _LICENSE_URL_RE.search(uri):
            continue
        if any(uri_lower.endswith(sv) or sv in uri_lower for sv in scholarly_uris):
            continue
        if uri_lower in existing_related or uri_lower.rstrip("/") in existing_related:
            continue
        if uri_lower in existing_ids:
            continue

        scheme = infer_identifier_scheme(uri)
        if scheme:
            continue

        new_related.append({
            "relatedIdentifier": uri,
            "relatedIdentifierType": "URL",
            "relationType": "References",
        })

    if new_related:
        result.setdefault("relatedIdentifiers", [])
        result["relatedIdentifiers"].extend(new_related)

    return result


def enrich_json_with_identifiers(data: dict, raw_text: str) -> dict:
    """
    Main entry point for identifier enrichment.

    1. Infers scheme/schemeURI for identifiers already in the Llama JSON.
    2. Extracts new identifiers from raw poster text via regex.
    3. Places them in correct schema locations (no duplicates).

    Args:
        data: The Llama-generated JSON dict.
        raw_text: The raw OCR text from the poster.

    Returns:
        Enriched copy of the data dict.
    """
    result = data.copy()

    # Step 1: enrich what's already there
    result = _enrich_existing_identifiers(result)

    # Step 2: extract from raw text
    extracted = extract_identifiers_from_text(raw_text)

    # Step 3: add new identifiers
    result = _add_extracted_identifiers(result, extracted)

    return result
