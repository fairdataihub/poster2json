"""Unit tests for poster2json.normalize."""

import pytest

from poster2json.normalize import (
    _match_license,
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
