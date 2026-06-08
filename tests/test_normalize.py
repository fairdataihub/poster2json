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
    assert out["rights"] == "Creative Commons Attribution 4.0 International"


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
    # conference is no longer model-extracted at all; it is dropped entirely.
    assert "conference" not in out


def test_conference_all_placeholder_collapses_to_null():
    from poster2json.extract import _postprocess_json

    data = {"conference": {"conferenceName": "Name of Conference", "conferenceLocation": "City, Country"}}
    out = _postprocess_json(data, raw_text="")
    assert "conference" not in out


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


def test_publisher_stripped_from_output():
    from poster2json.extract import _postprocess_json

    data = {"publisher": {"name": "Some University"}}
    out = _postprocess_json(data, raw_text="")
    assert "publisher" not in out


def test_conference_dropped_even_when_real():
    from poster2json.extract import _postprocess_json

    data = {"conference": {"conferenceName": "US-RSE'25", "conferenceYear": 2025}}
    out = _postprocess_json(data, raw_text="")
    # Even a real, well-formed conference is dropped — it comes from metadata.
    assert "conference" not in out


def test_conference_dropped_even_when_grounded():
    from poster2json.extract import _postprocess_json

    data = {"conference": {"conferenceName": "ICML 2025", "conferenceYear": 2025}}
    out = _postprocess_json(data, raw_text="Presented at ICML 2025, Vancouver")
    # No grounding logic remains; conference is dropped regardless of the text.
    assert "conference" not in out


def test_conference_not_in_poster_text_stripped():
    from poster2json.extract import _postprocess_json

    data = {"conference": {"conferenceName": "US-RSE'25", "conferenceYear": 2025}}
    out = _postprocess_json(data, raw_text="Drug-polymer interactions in nanoparticle delivery systems")
    assert "conference" not in out


def test_as_result_dict_unwraps_top_level_array():
    from poster2json.extract import _as_result_dict

    # The model sometimes wraps the object in a JSON array.
    assert _as_result_dict([{"titles": [{"title": "X"}]}]) == {"titles": [{"title": "X"}]}
    assert _as_result_dict({"a": 1}) == {"a": 1}
    assert "error" in _as_result_dict([])
    assert "error" in _as_result_dict("not an object")


def test_strip_surrogates_recursive():
    from poster2json.extract import _strip_surrogates

    out = _strip_surrogates({"titles": [{"title": "Lab \ud83d Group"}], "n": 3})
    title = out["titles"][0]["title"]
    assert "\ud83d" not in title
    title.encode("utf-8")  # must not raise
    assert out["n"] == 3


def test_postprocess_strips_surrogates_so_json_dumps_succeeds():
    import json
    from poster2json.extract import _postprocess_json

    # Lone surrogates in the model output broke json.dump(ensure_ascii=False).
    data = {"titles": [{"title": "A\ud83dB"}], "subjects": [{"subject": "x\ud83d"}]}
    out = _postprocess_json(data, raw_text="")
    json.dumps(out, ensure_ascii=False).encode("utf-8")  # must not raise
