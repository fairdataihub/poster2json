"""Unit tests for poster2json.funders. Network calls are stubbed."""

import json
from pathlib import Path

import pytest

from poster2json.funders import FunderClient, enrich_funding_references


class StubClient:
    def __init__(self, table):
        self.table = table
        self.calls = []

    def lookup(self, name):
        self.calls.append(name)
        return self.table.get(name)


def test_enrich_skips_when_no_match():
    c = StubClient({})
    frs = [{"funderName": "Unknown Funder"}]
    out = enrich_funding_references(frs, c)
    assert out == [{"funderName": "Unknown Funder"}]


def test_enrich_replaces_name_and_attaches_fundref():
    c = StubClient({
        "National Institutes of Health": {
            "id": "https://doi.org/10.13039/100000002",
            "name": "National Institutes of Health",
            "scheme": "Crossref Funder ID",
            "scheme_uri": "https://doi.org/10.13039",
        }
    })
    frs = [{"funderName": "National Institutes of Health"}]
    out = enrich_funding_references(frs, c)
    assert out[0] == {
        "funderName": "National Institutes of Health",
        "funderIdentifier": "https://doi.org/10.13039/100000002",
        "funderIdentifierType": "Crossref Funder ID",
        "schemeUri": "https://doi.org/10.13039",
    }


def test_enrich_canonicalizes_display_name():
    """ROR returns its preferred display name even when input is messy."""
    c = StubClient({
        "Gates Fdn.": {
            "id": "https://doi.org/10.13039/100000865",
            "name": "Gates Foundation",
            "scheme": "Crossref Funder ID",
            "scheme_uri": "https://doi.org/10.13039",
        }
    })
    frs = [{"funderName": "Gates Fdn."}]
    out = enrich_funding_references(frs, c)
    assert out[0]["funderName"] == "Gates Foundation"


def test_enrich_preserves_existing_identifier():
    c = StubClient({"X": {"id": "ignored", "name": "ignored", "scheme": "ROR", "scheme_uri": "ignored"}})
    frs = [{"funderName": "X", "funderIdentifier": "https://doi.org/preserved"}]
    out = enrich_funding_references(frs, c)
    assert out == [{"funderName": "X", "funderIdentifier": "https://doi.org/preserved"}]
    assert c.calls == []  # no lookup performed


def test_enrich_falls_back_to_ror_when_no_fundref():
    c = StubClient({
        "Some Foundation": {
            "id": "https://ror.org/000ror000",
            "name": "Some Foundation",
            "scheme": "ROR",
            "scheme_uri": "https://ror.org",
        }
    })
    frs = [{"funderName": "Some Foundation"}]
    out = enrich_funding_references(frs, c)
    assert out[0]["funderIdentifier"] == "https://ror.org/000ror000"
    assert out[0]["funderIdentifierType"] == "ROR"


def test_disabled_client_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTER2JSON_FUNDER", "0")
    c = FunderClient(cache_path=tmp_path / "f.json")
    assert c.enabled is False
    assert c.lookup("National Institutes of Health") is None


def test_cache_persists_across_instances(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTER2JSON_FUNDER", "1")
    cache = tmp_path / "f.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({
        "national institutes of health": {
            "id": "https://doi.org/10.13039/100000002",
            "name": "National Institutes of Health",
            "scheme": "Crossref Funder ID",
            "scheme_uri": "https://doi.org/10.13039",
        }
    }))
    c = FunderClient(cache_path=cache)
    assert c.lookup("National Institutes of Health")["id"] == "https://doi.org/10.13039/100000002"


def test_cache_records_negative_lookups(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTER2JSON_FUNDER", "1")
    cache = tmp_path / "f.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"unknown funder": None}))
    c = FunderClient(cache_path=cache)
    assert c.lookup("Unknown Funder") is None
