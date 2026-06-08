"""Unit tests for poster2json.ror — network calls are stubbed."""

import json
from pathlib import Path

import pytest

from poster2json.ror import (
    RorClient,
    coerce_person_affiliations,
    resolve_person_affiliations,
    strip_extracted_affiliation_ids,
)


class StubClient:
    """Minimal client that returns pre-canned matches without I/O."""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def lookup(self, name):
        self.calls.append(name)
        return self.table.get(name)


_UCSD = {"id": "https://ror.org/0168r3w48", "name": "University of California San Diego"}


def test_resolve_single_match_uses_canonical_name():
    client = StubClient({"OHSU, School of Medicine, Portland, OR, USA": {
        "id": "https://ror.org/009avj582", "name": "Oregon Health & Science University"}})
    persons = [{"name": "Tedla", "affiliation": ["OHSU, School of Medicine, Portland, OR, USA"]}]
    out = resolve_person_affiliations(persons, client)
    assert out[0]["affiliation"] == [{
        "name": "Oregon Health & Science University",
        "affiliationIdentifier": "https://ror.org/009avj582",
        "affiliationIdentifierScheme": "ROR",
        "schemeUri": "https://ror.org/",
    }]


def test_resolve_distinct_departments_same_org_kept_with_shared_id():
    # The Jalili case: two different UCSD department strings -> same ROR id ->
    # both kept, each with its original name plus the shared identifier.
    hamilton = "Hamilton Glaucoma Center, ... University of California San Diego, La Jolla, CA, US"
    informatics = "Division of Ophthalmology Informatics ... University of California San Diego, La Jolla, CA, USA"
    client = StubClient({hamilton: _UCSD, informatics: _UCSD})
    persons = [{"name": "Jalili", "affiliation": [hamilton, informatics]}]
    out = resolve_person_affiliations(persons, client)
    affs = out[0]["affiliation"]
    assert [a["name"] for a in affs] == [hamilton, informatics]
    assert all(a["affiliationIdentifier"] == "https://ror.org/0168r3w48" for a in affs)
    assert all(a["affiliationIdentifierScheme"] == "ROR" for a in affs)


def test_resolve_identical_strings_collapse_to_one_canonical():
    client = StubClient({"UC San Diego": _UCSD})
    persons = [{"name": "X", "affiliation": ["UC San Diego", "UC San Diego"]}]
    out = resolve_person_affiliations(persons, client)
    assert out[0]["affiliation"] == [{
        "name": "University of California San Diego",
        "affiliationIdentifier": "https://ror.org/0168r3w48",
        "affiliationIdentifierScheme": "ROR",
        "schemeUri": "https://ror.org/",
    }]


def test_resolve_unresolved_kept_and_deduped_by_name():
    client = StubClient({})  # nothing resolves
    persons = [{"name": "X", "affiliation": ["Some Tiny Lab", "some tiny lab ", "Other Inst"]}]
    out = resolve_person_affiliations(persons, client)
    assert out[0]["affiliation"] == ["Some Tiny Lab", "Other Inst"]


def test_resolve_ignores_model_id_after_strip():
    # strip removes the model-supplied id, resolve looks up by name and
    # attaches ROR's own id (not whatever the model copied off the poster).
    client = StubClient({"University of California San Diego": _UCSD})
    persons = [{"name": "X", "affiliation": [
        {"name": "University of California San Diego", "affiliationIdentifier": "https://ror.org/WRONG"}]}]
    persons = strip_extracted_affiliation_ids(persons)
    out = resolve_person_affiliations(persons, client)
    assert out[0]["affiliation"][0]["affiliationIdentifier"] == "https://ror.org/0168r3w48"


def test_resolve_skips_persons_without_affiliation():
    client = StubClient({})
    persons = [{"name": "A"}, {"name": "B", "affiliation": []}]
    out = resolve_person_affiliations(persons, client)
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


def test_strip_extracted_affiliation_ids_removes_model_supplied_ids():
    # The model is not asked for an identifier; anything present was scraped
    # off the poster and must be dropped so the name is resolved via ROR.
    persons = [{"name": "A", "affiliation": [{
        "name": "University of California San Diego",
        "schemeUri": "https://ror.org/",
        "affiliationIdentifier": "https://ror.org/scraped-off-poster",
        "affiliationIdentifierScheme": "ROR",
    }]}]
    out = strip_extracted_affiliation_ids(persons)
    assert out[0]["affiliation"] == [{"name": "University of California San Diego"}]


def test_strip_leaves_string_affiliations_untouched():
    persons = [{"name": "A", "affiliation": ["Stanford University"]}]
    out = strip_extracted_affiliation_ids(persons)
    assert out[0]["affiliation"] == ["Stanford University"]


def test_strip_then_resolve_no_match_leaves_bare_name():
    # If ROR can't confidently match, the affiliation keeps only its name
    # (no id) — the accepted trade-off of strip-and-resolve.
    persons = [{"name": "A", "affiliation": [{
        "name": "Some Tiny Lab",
        "affiliationIdentifier": "https://ror.org/whatever",
    }]}]
    persons = strip_extracted_affiliation_ids(persons)
    out = resolve_person_affiliations(persons, StubClient({}))
    assert out[0]["affiliation"] == [{"name": "Some Tiny Lab"}]


def test_strip_trailing_country():
    from poster2json.ror import _strip_trailing_country

    assert _strip_trailing_country("universidad politecnica de madrid, spain") == "universidad politecnica de madrid"
    assert _strip_trailing_country("eth zurich, switzerland") == "eth zurich"
    assert _strip_trailing_country("dept of cs, univ of california, berkeley") == "dept of cs, univ of california"
    # Should NOT strip when tail has digits or is too long
    assert _strip_trailing_country("building 5, floor 3") is None
    assert _strip_trailing_country("no comma here") is None
    assert _strip_trailing_country("dept, school of engineering and applied sciences") is None


