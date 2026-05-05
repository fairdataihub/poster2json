"""Unit tests for poster2json.normalize."""

import pytest

from poster2json.normalize import (
    _match_license,
    normalize_award_number,
    normalize_funding_references,
    normalize_rights_entry,
    normalize_rights_list,
    normalize_subject_value,
    normalize_subjects,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        # Tier 1: exact alphanumeric match
        ("CC-BY-4.0", "CC-BY-4.0"),
        ("cc-by-4.0", "CC-BY-4.0"),
        ("CC BY 4.0", "CC-BY-4.0"),
        ("CCBY4.0", "CC-BY-4.0"),
        ("Creative Commons Attribution 4.0 International", "CC-BY-4.0"),
        ("CC-BY-NC-SA-4.0", "CC-BY-NC-SA-4.0"),
        ("cc by nc sa 4.0", "CC-BY-NC-SA-4.0"),
        ("CC0", "CC0-1.0"),
        ("CC0-1.0", "CC0-1.0"),
        ("MIT", "MIT"),
        ("MIT License", "MIT"),
        ("apache 2.0", "Apache-2.0"),
        ("GPLv3", "GPL-3.0"),
        # Tier 2: alpha-fuzzy with integer-exact
        ("CC-BIY-4.0", "CC-BY-4.0"),  # one-letter alpha typo, version intact
        # Should NOT match: integer mismatch
        ("CC-BY-4.1", None),
        ("CC-BY-5.0", None),
        # Should NOT match: ambiguous (matches multiple at distance 1)
        ("CC-BY-S-4.0", None),
        # Should NOT match: unknown
        ("All rights reserved", None),
        ("Proprietary", None),
        ("", None),
        (None, None),
    ],
)
def test_match_license(text, expected):
    assert _match_license(text) == expected


def test_normalize_rights_entry_match_fills_spdx_fields():
    out = normalize_rights_entry({"rights": "cc-by-4.0"})
    assert out["rightsIdentifier"] == "CC-BY-4.0"
    assert out["rightsIdentifierScheme"] == "SPDX"
    assert out["schemeUri"] == "https://spdx.org/licenses/"
    assert out["rightsUri"] == "https://creativecommons.org/licenses/by/4.0/"
    assert out["rights"] == "cc-by-4.0"  # original preserved


def test_normalize_rights_entry_no_match_unchanged():
    entry = {"rights": "All rights reserved"}
    assert normalize_rights_entry(entry) == entry


def test_normalize_rights_entry_falls_back_to_identifier_then_uri():
    # rights missing -> uses rightsIdentifier
    out = normalize_rights_entry({"rightsIdentifier": "cc by 4.0"})
    assert out["rightsIdentifier"] == "CC-BY-4.0"
    # canonical name backfilled into `rights`
    assert out["rights"] == "Creative Commons Attribution 4.0 International"


def test_normalize_rights_entry_does_not_overwrite_existing_uri():
    out = normalize_rights_entry(
        {"rights": "CC-BY-4.0", "rightsUri": "https://custom.example/cc-by-4.0"}
    )
    assert out["rightsUri"] == "https://custom.example/cc-by-4.0"


def test_normalize_rights_list_handles_mix():
    rights_list = [
        {"rights": "MIT"},
        {"rights": "All rights reserved"},
        {"rights": "Apache 2.0"},
    ]
    out = normalize_rights_list(rights_list)
    assert out[0]["rightsIdentifier"] == "MIT"
    assert "rightsIdentifier" not in out[1]
    assert out[2]["rightsIdentifier"] == "Apache-2.0"


def test_normalize_subject_value_nfkc_and_whitespace():
    # NFKC composes accented chars to single codepoints
    decomposed = "café"  # café as e + combining acute
    assert normalize_subject_value(decomposed) == "café"
    # Internal whitespace collapse
    assert normalize_subject_value("  hello   world  ") == "hello world"


def test_normalize_subjects_dedupe_case_insensitive():
    subs = [
        {"subject": "Machine Learning"},
        {"subject": "machine learning"},
        "Type 2 Diabetes",
        "type 2 diabetes",
        {"subject": ""},
        {"subject": "  Diabetic   Retinopathy  "},
    ]
    out = normalize_subjects(subs)
    values = [s["subject"] if isinstance(s, dict) else s for s in out]
    assert values == ["Machine Learning", "Type 2 Diabetes", "Diabetic Retinopathy"]


def test_normalize_subjects_preserves_first_casing():
    subs = [{"subject": "machine learning"}, {"subject": "Machine Learning"}]
    out = normalize_subjects(subs)
    assert out == [{"subject": "machine learning"}]


@pytest.mark.parametrize(
    "rf_in,expected",
    [
        ("Health Sciences", "Health Sciences"),
        ("Life Sciences", "Life Sciences"),
        ("Physical Sciences", "Physical Sciences"),
        ("Social Sciences", "Social Sciences"),
        # Placeholder/fallback values should null out
        ("Other", None),
        ("other", None),
        ("OTHER", None),
        ("", None),
        ("Research field", None),
        ("Unknown", None),
        ("N/A", None),
        ("Domain", None),
        # Legit-looking but non-canonical values pass through (we don't
        # enforce the enum at normalization time)
        ("Other Sciences", "Other Sciences"),
        ("Bioinformatics", "Bioinformatics"),
        # Already-null stays null
        (None, None),
    ],
)
def test_postprocess_strips_researchfield_placeholders(rf_in, expected):
    from poster2json.extract import _postprocess_json

    out = _postprocess_json({"researchField": rf_in}, raw_text="")
    assert out.get("researchField") == expected


@pytest.mark.parametrize(
    "in_,expected",
    [
        ("OT2OD032644", "OT2OD032644"),
        ("ot2od032644", "OT2OD032644"),
        ("  OT2OD032644  ", "OT2OD032644"),
        ("GBMF3859.01", "GBMF3859.01"),
        ("nsf-ags-1234", "NSF-AGS-1234"),
        ("(OT2OD032644)", "OT2OD032644"),
        ("OT2OD032644.", "OT2OD032644"),
        ("", None),
        ("   ", None),
    ],
)
def test_normalize_award_number(in_, expected):
    assert normalize_award_number(in_) == expected


def test_normalize_funding_references_drops_empty_award():
    frs = [{"funderName": "NIH", "awardNumber": "  "}]
    out = normalize_funding_references(frs)
    assert "awardNumber" not in out[0]


def test_normalize_funding_references_normalizes_funder_whitespace():
    frs = [{"funderName": "  National  Institutes  of   Health  "}]
    out = normalize_funding_references(frs)
    assert out[0]["funderName"] == "National Institutes of Health"


# ------------------------------------------------------------------
# Publisher-suspect detection (Phase 3)
# ------------------------------------------------------------------


def test_publisher_suspect_flag_when_ror_matches_affiliation():
    from poster2json.extract import _postprocess_json

    data = {
        "publisher": {
            "name": "University of Barcelona",
            "publisherIdentifier": "https://ror.org/021018s57",
        },
        "creators": [
            {
                "givenName": "Sofia",
                "familyName": "Garcia",
                "affiliation": [
                    {
                        "name": "University of Barcelona",
                        "affiliationIdentifier": "https://ror.org/021018s57",
                        "affiliationIdentifierScheme": "ROR",
                    }
                ],
            }
        ],
    }
    out = _postprocess_json(data, raw_text="")
    assert "_validation" in out
    warnings = [w for w in out["_validation"] if w["field"] == "publisher"]
    assert len(warnings) == 1
    assert warnings[0]["level"] == "warning"
    assert "https://ror.org/021018s57" in warnings[0]["message"]


def test_publisher_suspect_not_flagged_when_ror_differs():
    from poster2json.extract import _postprocess_json

    data = {
        "publisher": {
            "name": "Zenodo",
            "publisherIdentifier": "https://ror.org/04wxnsj81",
        },
        "creators": [
            {
                "givenName": "Sofia",
                "familyName": "Garcia",
                "affiliation": [
                    {
                        "name": "University of Barcelona",
                        "affiliationIdentifier": "https://ror.org/021018s57",
                    }
                ],
            }
        ],
    }
    out = _postprocess_json(data, raw_text="")
    assert "_validation" not in out


def test_publisher_suspect_not_flagged_without_publisher_id(monkeypatch):
    monkeypatch.setenv("POSTER2JSON_ROR", "0")
    import poster2json.ror as ror_mod

    ror_mod._default_client = None  # reset singleton so env var takes effect

    from poster2json.extract import _postprocess_json

    data = {
        "publisher": {"name": "University of Barcelona"},
        "creators": [
            {
                "givenName": "Sofia",
                "familyName": "Garcia",
                "affiliation": [
                    {
                        "name": "University of Barcelona",
                        "affiliationIdentifier": "https://ror.org/021018s57",
                    }
                ],
            }
        ],
    }
    out = _postprocess_json(data, raw_text="")
    assert "_validation" not in out
    ror_mod._default_client = None  # cleanup


def test_publisher_suspect_checks_contributors_too():
    from poster2json.extract import _postprocess_json

    data = {
        "publisher": {
            "name": "MIT",
            "publisherIdentifier": "https://ror.org/042nb2s44",
        },
        "creators": [],
        "contributors": [
            {
                "givenName": "Alice",
                "familyName": "Smith",
                "affiliation": [
                    {
                        "name": "MIT",
                        "affiliationIdentifier": "https://ror.org/042nb2s44",
                    }
                ],
            }
        ],
    }
    out = _postprocess_json(data, raw_text="")
    assert "_validation" in out
    assert any(w["field"] == "publisher" for w in out["_validation"])


# ------------------------------------------------------------------
# Placeholder safety net (0.5.4)
# ------------------------------------------------------------------


def test_conference_placeholder_stripped():
    from poster2json.extract import _postprocess_json

    data = {
        "conference": {
            "conferenceName": "Name of Conference",
            "conferenceYear": 2024,
        }
    }
    out = _postprocess_json(data, raw_text="")
    # conferenceName stripped; conferenceYear remains → object not collapsed
    assert out["conference"] == {"conferenceYear": 2024}


def test_conference_all_placeholder_collapses_to_null():
    from poster2json.extract import _postprocess_json

    data = {"conference": {"conferenceName": "Name of Conference", "conferenceLocation": "City, Country"}}
    out = _postprocess_json(data, raw_text="")
    assert out["conference"] is None


def test_bogus_table_caption_filtered():
    from poster2json.extract import _postprocess_json

    data = {
        "tableCaptions": [
            {"id": "table1", "caption": "Table not found in the poster text"},
        ],
        "imageCaptions": [
            {"id": "fig1", "caption": "Figure 1: Experimental setup"},
        ],
    }
    out = _postprocess_json(data, raw_text="")
    assert out["tableCaptions"] == []
    assert len(out["imageCaptions"]) == 1


def test_publisher_placeholder_stripped():
    from poster2json.extract import _postprocess_json

    data = {"publisher": {"name": "Conference Organizer or Institution Name"}}
    out = _postprocess_json(data, raw_text="")
    assert out["publisher"] is None


def test_real_conference_preserved():
    from poster2json.extract import _postprocess_json

    data = {"conference": {"conferenceName": "US-RSE'25", "conferenceYear": 2025}}
    out = _postprocess_json(data, raw_text="")
    assert out["conference"]["conferenceName"] == "US-RSE'25"
