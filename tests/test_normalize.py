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


def test_postprocess_drops_version_and_nulls_publication_year():
    # version and publicationYear are platform-owned (set at publish), never
    # extracted: version is dropped (optional in schema), publicationYear is
    # emitted as null rather than the model's guess.
    from poster2json.extract import _postprocess_json

    out = _postprocess_json(
        {"publicationYear": 2019, "version": "model guess"}, raw_text=""
    )
    assert out["publicationYear"] is None
    assert "version" not in out


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


def test_publisher_set_to_null_placeholder():
    from poster2json.extract import _postprocess_json

    data = {"publisher": {"name": "Some University"}}
    out = _postprocess_json(data, raw_text="")
    # Publisher is filled downstream; the model's value is replaced with a null
    # placeholder rather than dropped.
    assert out["publisher"] is None


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


def test_superscript_corrector_reassigns_from_markers():
    from poster2json.extract import _correct_affiliations_from_superscripts

    raw = (
        "Abridged Retinal Fluorescence Lifetimes in Glaucoma\n"
        "Siddharth Limaye 1,3 Shahin Hallaj 1,2 , Maria Jessica Cruz 4 , "
        "Saron Tedla 5 , Jalil Jalili 1,2 , Mark Christopher 1,2 , Linda M. Zangwill 1,2 "
        "1 Hamilton Glaucoma Center, University of California, San Diego, CA, US; "
        "2 Division of Ophthalmology Informatics, University of California, San Diego, CA, USA; "
        "3 Carle Illinois College of Medicine, University of Illinois at Urbana-Champaign, IL, USA; "
        "4 University of California, Davis, School of Medicine, CA, USA; "
        "5 Oregon Health and Science University, School of Medicine, OR, USA\n"
        "## BACKGROUND\n"
    )
    # The model over-assigned every institution to every author.
    everything = ["Hamilton", "Division", "Carle", "Davis", "Oregon"]
    result = {"creators": [
        {"name": "Limaye, Siddharth", "familyName": "Limaye", "affiliation": list(everything)},
        {"name": "Hallaj, Shahin", "familyName": "Hallaj", "affiliation": list(everything)},
        {"name": "Cruz, Maria Jessica", "familyName": "Cruz", "affiliation": list(everything)},
        {"name": "Tedla, Saron", "familyName": "Tedla", "affiliation": list(everything)},
        {"name": "Jalili, Jalil", "familyName": "Jalili", "affiliation": list(everything)},
        {"name": "Christopher, Mark", "familyName": "Christopher", "affiliation": list(everything)},
        {"name": "Zangwill, Linda M.", "familyName": "Zangwill", "affiliation": list(everything)},
    ]}
    _correct_affiliations_from_superscripts(result, raw)
    affs = [c["affiliation"] for c in result["creators"]]
    # Limaye 1,3 -> Hamilton (UCSD) + Carle (UIUC), not all 5
    assert len(affs[0]) == 2
    assert affs[0][0].startswith("Hamilton") and "Urbana-Champaign" in affs[0][1]
    # Cruz 4 -> only UC Davis; Tedla 5 -> only OHSU
    assert len(affs[2]) == 1 and "Davis" in affs[2][0]
    assert len(affs[3]) == 1 and "Oregon" in affs[3][0]
    # 1,2 authors -> both UCSD departments
    assert len(affs[1]) == 2
    assert any(n.get("level") == "info" for n in result.get("_validation", []))


def test_superscript_corrector_noop_without_numbered_list():
    from poster2json.extract import _correct_affiliations_from_superscripts

    raw = "Jane Doe, John Smith\nUniversity of Somewhere\n## INTRODUCTION\n"
    result = {"creators": [
        {"name": "Doe, Jane", "familyName": "Doe", "affiliation": ["University of Somewhere"]},
        {"name": "Smith, John", "familyName": "Smith", "affiliation": ["University of Somewhere"]},
    ]}
    before = [list(c["affiliation"]) for c in result["creators"]]
    _correct_affiliations_from_superscripts(result, raw)
    assert [c["affiliation"] for c in result["creators"]] == before
    assert "_validation" not in result


def test_superscript_corrector_next_number_delimited_multiline():
    from poster2json.extract import _correct_affiliations_from_superscripts

    # Real-corpus pattern: affiliations on their own line, delimited by the next
    # number (no ';'), authors on the line above.
    raw = (
        "Evolution Poster\n"
        "Noelle M. Mason 1 , Chris X. McDaniels 1 , John P. Korbin 1,2 & Lisa N. Barrow 1\n"
        "1 Museum of Southwestern Biology, University of New Mexico, 2 Sandia National Laboratories\n"
        "## Background\n"
    )
    result = {"creators": [
        {"name": "Mason, Noelle M.", "familyName": "Mason", "affiliation": ["X", "Y"]},
        {"name": "McDaniels, Chris X.", "familyName": "McDaniels", "affiliation": ["X", "Y"]},
        {"name": "Korbin, John P.", "familyName": "Korbin", "affiliation": ["X", "Y"]},
        {"name": "Barrow, Lisa N.", "familyName": "Barrow", "affiliation": ["X", "Y"]},
    ]}
    _correct_affiliations_from_superscripts(result, raw)
    affs = [c["affiliation"] for c in result["creators"]]
    assert len(affs[0]) == 1 and "Museum" in affs[0][0]      # Mason 1
    assert len(affs[2]) == 2 and any("Sandia" in a for a in affs[2])  # Korbin 1,2
    assert len(affs[3]) == 1 and "Museum" in affs[3][0]      # Barrow 1 (not the affil "1")


def test_superscript_corrector_unicode_superscripts():
    from poster2json.extract import _correct_affiliations_from_superscripts

    raw = (
        "Marine Poster\n"
        "Eva Troianou ¹, Evi Abatzidou ¹, Ioannis Tzovenis ¹,²\n"
        "¹ Institute of Marine Biology, Lixouri, Greece "
        "² Microphykos Research Centre, Athens, Greece\n"
        "## Abstract\n"
    )
    result = {"creators": [
        {"name": "Troianou, Eva", "familyName": "Troianou", "affiliation": ["x"]},
        {"name": "Abatzidou, Evi", "familyName": "Abatzidou", "affiliation": ["x"]},
        {"name": "Tzovenis, Ioannis", "familyName": "Tzovenis", "affiliation": ["x"]},
    ]}
    _correct_affiliations_from_superscripts(result, raw)
    affs = [c["affiliation"] for c in result["creators"]]
    assert len(affs[0]) == 1 and "Marine" in affs[0][0]      # Troianou superscript-1
    assert len(affs[2]) == 2                                  # Tzovenis 1,2


def test_superscript_corrector_expands_ranges():
    from poster2json.extract import _correct_affiliations_from_superscripts

    raw = (
        "Title\n"
        "Alice Smith 1-3, Bob Jones 2\n"
        "1 Alpha University, 2 Beta Institute, 3 Gamma College\n"
        "## Intro\n"
    )
    result = {"creators": [
        {"name": "Smith, Alice", "familyName": "Smith", "affiliation": ["x"]},
        {"name": "Jones, Bob", "familyName": "Jones", "affiliation": ["x"]},
    ]}
    _correct_affiliations_from_superscripts(result, raw)
    affs = [c["affiliation"] for c in result["creators"]]
    assert len(affs[0]) == 3                                  # Smith 1-3 -> all three
    assert len(affs[1]) == 1 and "Beta" in affs[1][0]        # Jones 2 -> Beta


def test_superscript_corrector_noop_when_block_runs_into_abstract():
    from poster2json.extract import _correct_affiliations_from_superscripts

    # The last numbered affiliation is followed immediately by the abstract on
    # the same banner run (no header break), so the naive parse would swallow
    # the body text. The corrector must detect that and stay a no-op.
    raw = (
        "Early reproductive failure in kakapo\n"
        "Olivia Janes 1, Jana Wold 1,2, Tammy Steeves 2\n"
        "1 Centre National de la Recherche Scientifique (CNRS), Rennes, France; "
        "2 University of Canterbury, New Zealand "
        "Early reproductive failure in kakapo Kakapo are a Nationally Critical "
        "taonga species endemic to Aotearoa New Zealand and experience high rates "
        "of early embryo death across the breeding population studied here.\n"
    )
    original = ["School of Biological Sciences"]
    result = {"creators": [
        {"name": "Janes, Olivia", "familyName": "Janes", "affiliation": list(original)},
        {"name": "Wold, Jana", "familyName": "Wold", "affiliation": list(original)},
        {"name": "Steeves, Tammy", "familyName": "Steeves", "affiliation": list(original)},
    ]}
    _correct_affiliations_from_superscripts(result, raw)
    # Untouched: no reassignment, no abstract text grabbed as an affiliation.
    for c in result["creators"]:
        assert c["affiliation"] == original
    assert not result.get("_validation")


def test_affiliation_ran_into_body_detector():
    from poster2json.extract import _affiliation_ran_into_body

    assert not _affiliation_ran_into_body("University of California, San Diego, CA, US")
    assert not _affiliation_ran_into_body(
        "LPL, Laboratoire de Physique des Lasers, Universite Paris 13, "
        "Sorbonne Paris Cite, Villetaneuse, France"
    )
    # prose / abstract text
    assert _affiliation_ran_into_body(
        "Kakapo are a Nationally Critical taonga species endemic to Aotearoa "
        "New Zealand and experience high rates of early embryo death"
    )
    # all-caps section headers grabbed from the body
    assert _affiliation_ran_into_body(
        "Univ. of California San Diego USA MOTIVATION THE GAS PUFF Z PINCH "
        "THE MACHINE LEARN IMAGE RESULTS"
    )
    # absurdly long single segment
    assert _affiliation_ran_into_body("Institute of " + "x" * 200)


def test_creator_nametype_personal_vs_organizational():
    from poster2json.extract import _postprocess_json

    data = {"creators": [
        {"name": "Smith, Jane", "givenName": "Jane", "familyName": "Smith"},
        {"name": "AI-READI Consortium"},
    ]}
    out = _postprocess_json(data, raw_text="")
    assert out["creators"][0]["nameType"] == "Personal"
    assert out["creators"][1]["nameType"] == "Organizational"


def test_postprocess_dedupes_repeated_sections():
    from poster2json.extract import _postprocess_json

    # The model looped and emitted the same fragment as three untitled sections
    # (the TTW sketchnote-poster case): they must collapse to one.
    data = {"content": {"sections": [
        {"sectionTitle": "", "sectionContent": "than you might think!"},
        {"sectionTitle": "", "sectionContent": "than you might think!"},
        {"sectionTitle": "", "sectionContent": "than you might think!"},
    ]}}
    out = _postprocess_json(data, raw_text="")
    secs = out["content"]["sections"]
    assert len(secs) == 1
    assert secs[0]["sectionContent"] == "than you might think!"


def test_postprocess_dedup_prefers_titled_section():
    from poster2json.extract import _postprocess_json

    # Same content appears untitled then titled; keep the titled copy.
    data = {"content": {"sections": [
        {"sectionContent": "shared body text content goes here"},
        {"sectionTitle": "Collaboration", "sectionContent": "shared body text content goes here"},
    ]}}
    out = _postprocess_json(data, raw_text="")
    secs = out["content"]["sections"]
    assert len(secs) == 1
    assert secs[0].get("sectionTitle") == "Collaboration"


def test_postprocess_keeps_distinct_sections():
    from poster2json.extract import _postprocess_json

    data = {"content": {"sections": [
        {"sectionTitle": "Intro", "sectionContent": "first distinct section body"},
        {"sectionTitle": "Methods", "sectionContent": "second distinct section body"},
    ]}}
    out = _postprocess_json(data, raw_text="")
    assert len(out["content"]["sections"]) == 2


def test_postprocess_strips_markdown_from_sections():
    from poster2json.extract import _postprocess_json

    data = {"content": {"sections": [
        {"sectionTitle": "**Methods**",
         "sectionContent": "We used **phenomenological** qualitative analysis of interviews."},
    ]}}
    out = _postprocess_json(data, raw_text="")
    s = out["content"]["sections"][0]
    assert s["sectionTitle"] == "Methods"
    assert "**" not in s["sectionContent"]
    assert "phenomenological qualitative" in s["sectionContent"]


def test_postprocess_drops_bare_structural_labels():
    from poster2json.extract import _postprocess_json

    # The Tokarski poster case: the model emitted bold meta-labels as section
    # content with no real text. These are scaffolding and must be dropped.
    data = {"content": {"sections": [
        {"sectionContent": "**Title and Subtitle:**"},
        {"sectionContent": "**Author Names and Affiliations:**"},
        {"sectionTitle": "Study Objectives",
         "sectionContent": "How do parents of adolescents perceive the transition process?"},
    ]}}
    out = _postprocess_json(data, raw_text="")
    secs = out["content"]["sections"]
    assert len(secs) == 1
    assert secs[0]["sectionTitle"] == "Study Objectives"


def test_postprocess_keeps_label_with_real_content():
    from poster2json.extract import _postprocess_json

    # "Label: actual content" carries information and is NOT a bare label.
    data = {"content": {"sections": [
        {"sectionContent": "Contact: tokarsk1@duq.edu and the project website"},
    ]}}
    out = _postprocess_json(data, raw_text="")
    assert len(out["content"]["sections"]) == 1


def test_recovery_does_not_reinject_ocr_markdown_labels():
    from poster2json.extract import _postprocess_json

    # The vision OCR decorates labels with markdown ("**STUDY OBJECTIVES:**");
    # the model already captured those as real titled sections. The raw-text
    # recovery must NOT re-add the decorated labels as untitled junk sections.
    raw_text = (
        "**Title and Subtitle:**\n"
        "A Qualitative Study of the Transition Process\n\n"
        "**STUDY OBJECTIVES:**\n"
        "How do parents of adolescents with IDD perceive the transition process?\n\n"
        "**THEMES:**\n"
        "Matching client and context. Parents are the driving force.\n"
    )
    data = {
        "titles": [{"title": "A Qualitative Study of the Transition Process"}],
        "content": {"sections": [
            {"sectionTitle": "Study Objectives",
             "sectionContent": "How do parents of adolescents with IDD perceive the transition process?"},
            {"sectionTitle": "Themes",
             "sectionContent": "Matching client and context. Parents are the driving force."},
        ]},
    }
    out = _postprocess_json(data, raw_text=raw_text)
    secs = out["content"]["sections"]
    joined = " ".join(s.get("sectionContent", "") for s in secs)
    # No bare markdown labels survived, and none were re-added as sections.
    assert "**" not in joined
    assert not any(_bare in s.get("sectionContent", "") for s in secs
                   for _bare in ("Title and Subtitle:", "STUDY OBJECTIVES:", "THEMES:"))
    # The two real titled sections are intact.
    titles = [s.get("sectionTitle") for s in secs]
    assert "Study Objectives" in titles and "Themes" in titles


def test_orcid_enrichment_uses_affiliation_resolver():
    from poster2json.orcid import enrich_creators_orcid

    class FakeClient:
        enabled = True

        def __init__(self):
            self.seen = []

        def lookup(self, given, family, affiliation):
            self.seen.append(affiliation)
            return "0000-0001-2345-6789" if affiliation == "University of Example" else None

    creators = [{
        "givenName": "Jane", "familyName": "Smith",
        "affiliation": [{"name": "Dept of X, University of Example, City, Country",
                         "affiliationIdentifier": "https://ror.org/abc123"}],
    }]
    fc = FakeClient()
    out = enrich_creators_orcid(
        creators, fc, affiliation_resolver=lambda n: "University of Example"
    )
    # The resolved canonical name (not the long sub-unit string) was queried.
    assert fc.seen == ["University of Example"]
    nids = out[0].get("nameIdentifiers", [])
    assert nids and "0000-0001-2345-6789" in nids[0]["nameIdentifier"]


def test_language_always_owned_by_lingua_not_llm():
    from poster2json.extract import _postprocess_json

    # The LLM hallucinated "en" for a clearly German body; lingua must win.
    # (Body must exceed the detector's MIN_CHARS floor of 200.)
    german = (
        "Untersuchung der Wirksamkeit neuer Therapien bei Patienten mit "
        "chronischen Erkrankungen. Die Ergebnisse zeigen eine deutliche "
        "Verbesserung der Lebensqualitaet und der Behandlungsergebnisse. "
        "Diese Studie wurde an mehreren Krankenhaeusern durchgefuehrt und "
        "umfasste mehrere hundert Teilnehmer ueber einen langen Zeitraum."
    )
    out = _postprocess_json({"language": "en"}, raw_text=german)
    assert out["language"] == "de"

    # With no body text the model's guess is still discarded, not trusted.
    out2 = _postprocess_json({"language": "en"}, raw_text="")
    assert out2["language"] is None


def test_superscript_corrector_honorifics_between_name_and_marker():
    from poster2json.extract import _correct_affiliations_from_superscripts

    raw = (
        "Title\n"
        "Bhavesh Patel, Ph.D.¹, Daniel Garijo, Ph.D.², on behalf of the Task Force\n"
        "¹FAIR Data Innovations Hub, California Medical Innovations Institute, San Diego, CA, USA "
        "²Universidad Politecnica de Madrid, Spain\n"
        "## Background\n"
    )
    result = {"creators": [
        {"name": "Patel, Bhavesh", "familyName": "Patel", "affiliation": ["x"]},
        {"name": "Garijo, Daniel", "familyName": "Garijo", "affiliation": ["x"]},
    ]}
    _correct_affiliations_from_superscripts(result, raw)
    affs = [c["affiliation"] for c in result["creators"]]
    assert len(affs[0]) == 1 and "FAIR Data" in affs[0][0]
    assert len(affs[1]) == 1 and "Madrid" in affs[1][0]


def test_superscript_corrector_minus_range_and_modifier_separator():
    from poster2json.extract import _correct_affiliations_from_superscripts

    # U+207B superscript minus as a range ("1-2"), U+02D2 as a "," separator.
    raw = (
        "Title\n"
        "Michael Timmermans¹⁻², Bert Bogaerts², Ana Ruiz¹˒²\n"
        "¹Alpha University, ²Beta Institute\n"
        "## Intro\n"
    )
    result = {"creators": [
        {"name": "Timmermans, Michael", "familyName": "Timmermans", "affiliation": ["x"]},
        {"name": "Bogaerts, Bert", "familyName": "Bogaerts", "affiliation": ["x"]},
        {"name": "Ruiz, Ana", "familyName": "Ruiz", "affiliation": ["x"]},
    ]}
    _correct_affiliations_from_superscripts(result, raw)
    affs = [c["affiliation"] for c in result["creators"]]
    assert len(affs[0]) == 2                       # 1-2 range
    assert len(affs[1]) == 1 and "Beta" in affs[1][0]
    assert len(affs[2]) == 2                       # 1,2 via U+02D2


def test_superscript_corrector_role_glyphs_in_marker():
    from poster2json.extract import _correct_affiliations_from_superscripts

    raw = (
        "Title\n"
        "Andrew Couperus*1+2, Todd Henry2, Rachel Osten1\n"
        "1 Georgia State University, Atlanta, GA 2 RECONS Institute, Chambersburg, PA\n"
        "## Intro\n"
    )
    result = {"creators": [
        {"name": "Couperus, Andrew", "familyName": "Couperus", "affiliation": ["x"]},
        {"name": "Henry, Todd", "familyName": "Henry", "affiliation": ["x"]},
        {"name": "Osten, Rachel", "familyName": "Osten", "affiliation": ["x"]},
    ]}
    _correct_affiliations_from_superscripts(result, raw)
    affs = [c["affiliation"] for c in result["creators"]]
    assert len(affs[0]) == 2                        # *1+2 -> [1, 2]
    assert len(affs[2]) == 1 and "Georgia" in affs[2][0]


def test_superscript_corrector_degree_abuts_marker():
    from poster2json.extract import _correct_affiliations_from_superscripts

    raw = (
        "Title\n"
        "Alisa Surkis, PhD, MLS1, Aileen McCrillis, MSLIS1, Brian Schmidt, DDS2\n"
        "1 NYU Health Sciences Libraries, New York University; 2 Bluestone Center for Clinical Research\n"
        "## Intro\n"
    )
    result = {"creators": [
        {"name": "Surkis, Alisa", "familyName": "Surkis", "affiliation": ["x"]},
        {"name": "McCrillis, Aileen", "familyName": "McCrillis", "affiliation": ["x"]},
        {"name": "Schmidt, Brian", "familyName": "Schmidt", "affiliation": ["x"]},
    ]}
    _correct_affiliations_from_superscripts(result, raw)
    affs = [c["affiliation"] for c in result["creators"]]
    assert "NYU" in affs[0][0]
    assert "Bluestone" in affs[2][0]


def test_superscript_corrector_initials_and_keywordless_affiliation():
    from poster2json.extract import _correct_affiliations_from_superscripts

    # "Family Initial" byline (no comma) and a keyword-less company affiliation
    # ("Delta Hat Ltd") that must still be bounded by the sequential markers.
    raw = (
        "Title\n"
        "Ivanyi P1, Bullement A2, Colombo GL1,2\n"
        "1 Hannover Medical School, Germany; 2 Delta Hat Ltd, Nottingham, UK\n"
        "## Intro\n"
    )
    result = {"creators": [
        {"name": "Ivanyi, P", "familyName": "Ivanyi", "affiliation": ["x"]},
        {"name": "Bullement, A", "familyName": "Bullement", "affiliation": ["x"]},
        {"name": "Colombo, GL", "familyName": "Colombo", "affiliation": ["x"]},
    ]}
    _correct_affiliations_from_superscripts(result, raw)
    affs = [c["affiliation"] for c in result["creators"]]
    assert "Hannover" in affs[0][0]                 # Ivanyi P1
    assert "Delta Hat" in affs[1][0]                # keyword-less, bounded
    assert len(affs[2]) == 2                        # Colombo GL1,2


def test_superscript_corrector_skips_collective_author():
    from poster2json.extract import _correct_affiliations_from_superscripts

    raw = (
        "Title\n"
        "Andrew Couperus1, Todd Henry2, and the RECONS Team\n"
        "1 Georgia State University, Atlanta, GA 2 RECONS Institute, Chambersburg, PA\n"
        "## Intro\n"
    )
    result = {"creators": [
        {"name": "Couperus, Andrew", "familyName": "Couperus", "affiliation": ["x"]},
        {"name": "Henry, Todd", "familyName": "Henry", "affiliation": ["x"]},
        {"name": "the RECONS Team", "affiliation": ["x"]},
    ]}
    _correct_affiliations_from_superscripts(result, raw)
    affs = [c["affiliation"] for c in result["creators"]]
    assert "Georgia" in affs[0][0]
    assert "RECONS Institute" in affs[1][0]
    assert affs[2] == ["x"]                         # collective author untouched


def test_superscript_corrector_asterisk_footnote_scheme():
    from poster2json.extract import _correct_affiliations_from_superscripts

    # Asterisk-keyed affiliations (* / **) with a compound surname printed as
    # only "Perdomo" in the byline, and a corresponding-author digit (¹email)
    # that must be ignored.
    raw = (
        "Title\n"
        "A. Perdomo*,**,¹, N. Vitas*,**, E. Khomenko*,**\n"
        "*Instituto de Astrofisica de Canarias, La Laguna, Spain "
        "**Departamento de Astrofisica, Universidad de La Laguna, Spain ¹aperdomo@iac.es\n"
        "## ABSTRACT\n"
    )
    result = {"creators": [
        {"name": "Perdomo Garcia, Andrea", "familyName": "Perdomo Garcia", "affiliation": ["x"]},
        {"name": "Vitas, Nikola", "familyName": "Vitas", "affiliation": ["x"]},
        {"name": "Khomenko, Elena", "familyName": "Khomenko", "affiliation": ["x"]},
    ]}
    _correct_affiliations_from_superscripts(result, raw)
    affs = [c["affiliation"] for c in result["creators"]]
    assert len(affs[0]) == 2 and "Instituto" in affs[0][0] and "Universidad" in affs[0][1]
    assert len(affs[2]) == 2 and "Instituto" in affs[2][0]
