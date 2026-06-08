"""Unit tests for poster2json.ror — network calls are stubbed."""

import json
from pathlib import Path

import pytest

from poster2json.ror import (
    RorClient,
    _enrich_affiliation_item,
    coerce_person_affiliations,
    dedupe_person_affiliations,
    enrich_persons,
)


class StubClient:
    """Minimal client that returns pre-canned matches without I/O."""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def lookup(self, name):
        self.calls.append(name)
        return self.table.get(name)


def test_enrich_affiliation_string_match_promotes_to_object():
    client = StubClient({"Stanford University": {"id": "https://ror.org/00f54p054", "name": "Stanford University"}})
    out = _enrich_affiliation_item("Stanford University", client)
    assert out == {
        "name": "Stanford University",
        "affiliationIdentifier": "https://ror.org/00f54p054",
        "affiliationIdentifierScheme": "ROR",
        "schemeUri": "https://ror.org/",
    }


def test_enrich_affiliation_string_no_match_unchanged():
    client = StubClient({})
    assert _enrich_affiliation_item("Unknown Inst", client) == "Unknown Inst"


def test_enrich_affiliation_object_replaces_name_with_canonical():
    client = StubClient({"东京大学": {"id": "https://ror.org/057zh3y96", "name": "The University of Tokyo"}})
    out = _enrich_affiliation_item({"name": "东京大学"}, client)
    assert out["name"] == "The University of Tokyo"
    assert out["affiliationIdentifier"] == "https://ror.org/057zh3y96"


def test_enrich_affiliation_object_with_existing_identifier_skips():
    client = StubClient({"X": {"id": "https://ror.org/different", "name": "Different"}})
    item = {"name": "X", "affiliationIdentifier": "https://ror.org/preserved"}
    out = _enrich_affiliation_item(item, client)
    assert out == item
    assert client.calls == []  # no lookup performed


def test_enrich_persons_skips_missing_affiliation():
    client = StubClient({})
    persons = [{"name": "A"}, {"name": "B", "affiliation": []}]
    out = enrich_persons(persons, client)
    assert out == persons


def test_disabled_client_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTER2JSON_ROR", "0")
    client = RorClient(cache_path=tmp_path / "ror.json")
    assert client.enabled is False
    assert client.lookup("Stanford University") is None


def test_cache_persists_across_instances(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTER2JSON_ROR", "1")
    cache = tmp_path / "ror.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({
        "stanford university": {"id": "https://ror.org/00f54p054", "name": "Stanford University"}
    }))
    client = RorClient(cache_path=cache)
    # No network call: hits cache via normalized key
    assert client.lookup("Stanford University") == {
        "id": "https://ror.org/00f54p054",
        "name": "Stanford University",
    }


def test_cache_records_negative_lookups(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTER2JSON_ROR", "1")
    cache = tmp_path / "ror.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"unknown inst": None}))
    client = RorClient(cache_path=cache)
    # Cached None -> returns None without network
    assert client.lookup("Unknown Inst") is None


def test_coerce_bare_string_affiliation_to_list():
    # The schema-violating shape reported in the field: affiliation is a string.
    persons = [{
        "name": "Tedla, Saron",
        "affiliation": "Oregon Health & Science University, School of Medicine, Portland, OR, USA",
    }]
    out = coerce_person_affiliations(persons)
    assert out[0]["affiliation"] == [
        "Oregon Health & Science University, School of Medicine, Portland, OR, USA"
    ]


def test_coerce_single_object_to_list():
    persons = [{"name": "A", "affiliation": {"name": "MIT"}}]
    out = coerce_person_affiliations(persons)
    assert out[0]["affiliation"] == [{"name": "MIT"}]


def test_coerce_drops_null_empty_and_junk():
    persons = [
        {"name": "A", "affiliation": None},
        {"name": "B", "affiliation": ""},
        {"name": "C", "affiliation": []},
        {"name": "D", "affiliation": ["  ", None, 5, {"foo": "bar"}]},
        {"name": "E"},
    ]
    out = coerce_person_affiliations(persons)
    assert "affiliation" not in out[0]
    assert "affiliation" not in out[1]
    assert "affiliation" not in out[2]
    assert "affiliation" not in out[3]  # all items were junk
    assert "affiliation" not in out[4]


def test_coerce_filters_blank_list_items_but_keeps_valid():
    persons = [{"name": "A", "affiliation": ["Stanford", "  ", {"name": "MIT"}, {}]}]
    out = coerce_person_affiliations(persons)
    assert out[0]["affiliation"] == ["Stanford", {"name": "MIT"}]


def test_dedupe_identical_objects():
    # The other reported shape: same ROR object listed twice (Jalili / UCSD).
    ucsd = {
        "name": "University of California San Diego",
        "schemeUri": "https://ror.org/",
        "affiliationIdentifier": "https://ror.org/0168r3w48",
        "affiliationIdentifierScheme": "ROR",
    }
    persons = [{"name": "Jalili, Jalil", "affiliation": [dict(ucsd), dict(ucsd)]}]
    out = dedupe_person_affiliations(persons)
    assert out[0]["affiliation"] == [ucsd]


def test_dedupe_identical_strings():
    persons = [{"name": "A", "affiliation": ["MIT", "mit", "MIT "]}]
    out = dedupe_person_affiliations(persons)
    assert out[0]["affiliation"] == ["MIT"]


def test_dedupe_prefers_identified_entry_over_bare_name():
    persons = [{"name": "A", "affiliation": [
        "Stanford University",
        {"name": "Stanford University", "affiliationIdentifier": "https://ror.org/00f54p054"},
    ]}]
    out = dedupe_person_affiliations(persons)
    assert out[0]["affiliation"] == [
        {"name": "Stanford University", "affiliationIdentifier": "https://ror.org/00f54p054"}
    ]


def test_dedupe_keeps_distinct_affiliations_and_order():
    persons = [{"name": "A", "affiliation": ["MIT", "Stanford", "MIT"]}]
    out = dedupe_person_affiliations(persons)
    assert out[0]["affiliation"] == ["MIT", "Stanford"]


def test_strip_trailing_country():
    from poster2json.ror import _strip_trailing_country

    assert _strip_trailing_country("universidad politecnica de madrid, spain") == "universidad politecnica de madrid"
    assert _strip_trailing_country("eth zurich, switzerland") == "eth zurich"
    assert _strip_trailing_country("dept of cs, univ of california, berkeley") == "dept of cs, univ of california"
    # Should NOT strip when tail has digits or is too long
    assert _strip_trailing_country("building 5, floor 3") is None
    assert _strip_trailing_country("no comma here") is None
    assert _strip_trailing_country("dept, school of engineering and applied sciences") is None


