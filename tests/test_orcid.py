"""Unit tests for poster2json.orcid. Network calls are stubbed."""

import json
from pathlib import Path

import pytest

from poster2json.orcid import (
    OrcidClient,
    _creator_affiliation_name,
    _creator_has_orcid,
    _names_match,
    enrich_creators_orcid,
)


# ------------------------------------------------------------------
# Stub client for logic tests
# ------------------------------------------------------------------


class StubClient:
    """Returns pre-canned ORCID iDs keyed by (given, family, affiliation)."""

    def __init__(self, table, enabled=True):
        self.table = table
        self.calls = []
        self.enabled = enabled

    def lookup(self, given, family, affiliation=None):
        self.calls.append((given, family, affiliation))
        return self.table.get((given, family, affiliation))


# ------------------------------------------------------------------
# _names_match
# ------------------------------------------------------------------


def test_names_match_case_insensitive():
    assert _names_match("James", "james")
    assert _names_match("O'Neill", "o'neill")


def test_names_match_accent_insensitive():
    assert _names_match("José", "Jose")
    assert _names_match("Müller", "Muller")


def test_names_match_rejects_different_names():
    assert not _names_match("James", "Jamie")
    assert not _names_match("Smith", "Smyth")


def test_names_match_empty():
    assert not _names_match("", "James")
    assert not _names_match("James", "")
    assert not _names_match("", "")


# ------------------------------------------------------------------
# _creator_has_orcid / _creator_affiliation_name
# ------------------------------------------------------------------


def test_creator_has_orcid_true():
    c = {
        "nameIdentifiers": [
            {"nameIdentifier": "https://orcid.org/0000-0002-1234-5678", "nameIdentifierScheme": "ORCID"}
        ]
    }
    assert _creator_has_orcid(c) is True


def test_creator_has_orcid_false_empty():
    assert _creator_has_orcid({}) is False
    assert _creator_has_orcid({"nameIdentifiers": []}) is False


def test_creator_has_orcid_false_non_orcid():
    c = {"nameIdentifiers": [{"nameIdentifier": "https://ror.org/abc", "nameIdentifierScheme": "ROR"}]}
    assert _creator_has_orcid(c) is False


def test_creator_affiliation_name_from_string():
    c = {"affiliation": ["Stanford University"]}
    assert _creator_affiliation_name(c) == "Stanford University"


def test_creator_affiliation_name_from_object():
    c = {"affiliation": [{"name": "Stanford University", "affiliationIdentifier": "https://ror.org/00f54p054"}]}
    assert _creator_affiliation_name(c) == "Stanford University"


def test_creator_affiliation_name_none():
    assert _creator_affiliation_name({}) is None
    assert _creator_affiliation_name({"affiliation": []}) is None


# ------------------------------------------------------------------
# enrich_creators_orcid
# ------------------------------------------------------------------


def test_enrich_attaches_orcid():
    client = StubClient({
        ("Sofia", "Garcia", "University of Barcelona"): "0000-0001-2345-6789",
    })
    creators = [
        {
            "givenName": "Sofia",
            "familyName": "Garcia",
            "affiliation": [{"name": "University of Barcelona"}],
        }
    ]
    out = enrich_creators_orcid(creators, client)
    ni = out[0]["nameIdentifiers"]
    assert len(ni) == 1
    assert ni[0]["nameIdentifier"] == "https://orcid.org/0000-0001-2345-6789"
    assert "nameIdentifierScheme" not in ni[0]
    assert "schemeURI" not in ni[0]


def test_enrich_skips_existing_orcid():
    client = StubClient({
        ("James", "O'Neill", "Georgetown University"): "0000-0002-0345-1080",
    })
    creators = [
        {
            "givenName": "James",
            "familyName": "O'Neill",
            "affiliation": [{"name": "Georgetown University"}],
            "nameIdentifiers": [
                {"nameIdentifier": "https://orcid.org/0000-0002-0345-1080", "nameIdentifierScheme": "ORCID"}
            ],
        }
    ]
    out = enrich_creators_orcid(creators, client)
    assert client.calls == []  # no lookup performed
    assert len(out[0]["nameIdentifiers"]) == 1


def test_enrich_skips_missing_given_or_family():
    client = StubClient({})
    creators = [
        {"familyName": "Garcia", "affiliation": [{"name": "X"}]},
        {"givenName": "Sofia", "affiliation": [{"name": "X"}]},
        {"name": "AI Research Lab", "affiliation": [{"name": "X"}]},
    ]
    out = enrich_creators_orcid(creators, client)
    assert client.calls == []


def test_enrich_no_match_leaves_creator_unchanged():
    client = StubClient({})
    creators = [
        {
            "givenName": "Unique",
            "familyName": "Person",
            "affiliation": [{"name": "Nowhere University"}],
        }
    ]
    out = enrich_creators_orcid(creators, client)
    assert "nameIdentifiers" not in out[0]


def test_enrich_multiple_creators_selective():
    client = StubClient({
        ("Alice", "Smith", "MIT"): "0000-0003-1111-2222",
        ("Bob", "Jones", "MIT"): None,
    })
    creators = [
        {"givenName": "Alice", "familyName": "Smith", "affiliation": ["MIT"]},
        {"givenName": "Bob", "familyName": "Jones", "affiliation": ["MIT"]},
    ]
    out = enrich_creators_orcid(creators, client)
    assert len(out[0]["nameIdentifiers"]) == 1
    assert "nameIdentifiers" not in out[1]


def test_enrich_disabled_client_noop():
    client = StubClient({}, enabled=False)
    creators = [
        {"givenName": "A", "familyName": "B", "affiliation": ["X"]},
    ]
    out = enrich_creators_orcid(creators, client)
    assert client.calls == []


# ------------------------------------------------------------------
# Real client: cache, env-var disable
# ------------------------------------------------------------------


def test_disabled_via_env(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTER2JSON_ORCID", "0")
    c = OrcidClient(cache_path=tmp_path / "orcid.json")
    assert c.enabled is False
    assert c.lookup("James", "O'Neill", "Georgetown") is None


def test_cache_persists_across_instances(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTER2JSON_ORCID", "1")
    cache = tmp_path / "orcid.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({
        "sofia|garcia|university of barcelona": "0000-0001-2345-6789",
    }))
    c = OrcidClient(cache_path=cache)
    assert c.lookup("Sofia", "Garcia", "University of Barcelona") == "0000-0001-2345-6789"


def test_cache_records_negative_lookups(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTER2JSON_ORCID", "1")
    cache = tmp_path / "orcid.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"unknown|person|nowhere": None}))
    c = OrcidClient(cache_path=cache)
    assert c.lookup("Unknown", "Person", "Nowhere") is None


def test_lookup_requires_affiliation(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTER2JSON_ORCID", "1")
    c = OrcidClient(cache_path=tmp_path / "orcid.json")
    assert c.lookup("James", "O'Neill") is None
    assert c.lookup("James", "O'Neill", None) is None
