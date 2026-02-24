"""Unit tests for poster2json.identifiers and caption ID auto-generation."""

import pytest

from poster2json.identifiers import (
    enrich_json_with_identifiers,
    extract_identifiers_from_text,
    infer_identifier_scheme,
)
from poster2json.extract import _normalize_captions


# ============================
# infer_identifier_scheme
# ============================


class TestInferIdentifierScheme:
    def test_orcid_bare(self):
        assert infer_identifier_scheme("0000-0002-1825-0097") == (
            "ORCID",
            "https://orcid.org",
        )

    def test_orcid_url(self):
        assert infer_identifier_scheme("https://orcid.org/0000-0002-1825-0097") == (
            "ORCID",
            "https://orcid.org",
        )

    def test_doi_prefix(self):
        assert infer_identifier_scheme("10.1234/foo.bar") == (
            "DOI",
            "https://doi.org",
        )

    def test_doi_url(self):
        assert infer_identifier_scheme("https://doi.org/10.1234/foo.bar") == (
            "DOI",
            "https://doi.org",
        )

    def test_doi_with_doi_prefix(self):
        assert infer_identifier_scheme("doi:10.1234/foo") == (
            "DOI",
            "https://doi.org",
        )

    def test_crossref_funder_before_doi(self):
        result = infer_identifier_scheme("10.13039/501100001659")
        assert result == ("Crossref Funder ID", "https://doi.org/10.13039")

    def test_crossref_funder_url(self):
        result = infer_identifier_scheme("https://doi.org/10.13039/501100001659")
        assert result == ("Crossref Funder ID", "https://doi.org/10.13039")

    def test_arxiv(self):
        assert infer_identifier_scheme("arXiv:2301.12345") == (
            "arXiv",
            "https://arxiv.org/abs",
        )

    def test_arxiv_url(self):
        assert infer_identifier_scheme("https://arxiv.org/abs/2301.12345v2") == (
            "arXiv",
            "https://arxiv.org/abs",
        )

    def test_ror(self):
        assert infer_identifier_scheme("https://ror.org/0abcde123") == (
            "ROR",
            "https://ror.org",
        )

    def test_isni(self):
        assert infer_identifier_scheme("https://isni.org/isni/0000000121032683") == (
            "ISNI",
            "https://isni.org",
        )

    def test_grid(self):
        assert infer_identifier_scheme("https://grid.ac/grid.12345.a") == (
            "GRID",
            "https://grid.ac",
        )

    def test_unknown_returns_none(self):
        assert infer_identifier_scheme("just some text") is None

    def test_empty_returns_none(self):
        assert infer_identifier_scheme("") is None

    def test_none_returns_none(self):
        assert infer_identifier_scheme(None) is None


# ============================
# extract_identifiers_from_text
# ============================


class TestExtractIdentifiers:
    def test_orcid_in_text(self):
        text = "Contact: https://orcid.org/0000-0002-1825-0097"
        result = extract_identifiers_from_text(text)
        assert "orcid" in result
        assert "0000-0002-1825-0097" in result["orcid"]

    def test_orcid_bare_in_text(self):
        text = "ORCID 0000-0002-1825-0097"
        result = extract_identifiers_from_text(text)
        assert "orcid" in result
        assert "0000-0002-1825-0097" in result["orcid"]

    def test_multiple_orcids(self):
        text = "0000-0002-1825-0097 and 0000-0001-2345-6789"
        result = extract_identifiers_from_text(text)
        assert len(result.get("orcid", [])) == 2

    def test_doi_in_text(self):
        text = "Published at doi:10.1234/example.2025"
        result = extract_identifiers_from_text(text)
        assert "doi" in result
        assert "10.1234/example.2025" in result["doi"]

    def test_doi_url_in_text(self):
        text = "See https://doi.org/10.5281/zenodo.123456"
        result = extract_identifiers_from_text(text)
        assert "doi" in result
        assert "10.5281/zenodo.123456" in result["doi"]

    def test_arxiv_colon_format(self):
        text = "Preprint: arXiv:2301.12345"
        result = extract_identifiers_from_text(text)
        assert "arxiv" in result
        assert "2301.12345" in result["arxiv"]

    def test_arxiv_url_format(self):
        text = "https://arxiv.org/abs/2301.12345v2"
        result = extract_identifiers_from_text(text)
        assert "arxiv" in result
        assert "2301.12345v2" in result["arxiv"]

    def test_ror_in_text(self):
        text = "Affiliation: https://ror.org/0abcde123"
        result = extract_identifiers_from_text(text)
        assert "ror" in result
        assert "0abcde123" in result["ror"]

    def test_crossref_funder_in_text(self):
        text = "Funded by https://doi.org/10.13039/501100001659"
        result = extract_identifiers_from_text(text)
        assert "crossref_funder" in result
        assert "10.13039/501100001659" in result["crossref_funder"]

    def test_crossref_funder_excluded_from_doi(self):
        text = "https://doi.org/10.13039/501100001659"
        result = extract_identifiers_from_text(text)
        assert "doi" not in result or "10.13039/501100001659" not in result.get(
            "doi", []
        )

    def test_deduplication(self):
        text = "doi:10.1234/foo and doi:10.1234/foo again"
        result = extract_identifiers_from_text(text)
        assert len(result.get("doi", [])) == 1

    def test_empty_text(self):
        assert extract_identifiers_from_text("") == {}

    def test_no_identifiers(self):
        text = "This poster discusses machine learning methods."
        assert extract_identifiers_from_text(text) == {}

    def test_doi_trailing_period_stripped(self):
        text = "See doi:10.1234/foo.bar."
        result = extract_identifiers_from_text(text)
        assert result["doi"][0] == "10.1234/foo.bar"

    def test_mixed_identifiers(self):
        text = """
        Author: 0000-0002-1825-0097
        DOI: doi:10.5281/zenodo.123
        arXiv:2301.12345
        Funder: https://doi.org/10.13039/501100001659
        """
        result = extract_identifiers_from_text(text)
        assert "orcid" in result
        assert "doi" in result
        assert "arxiv" in result
        assert "crossref_funder" in result


# ============================
# enrich_json_with_identifiers
# ============================


class TestEnrichJson:
    def test_adds_doi_from_text(self):
        data = {"creators": [{"name": "Doe, John"}]}
        text = "doi:10.1234/example"
        result = enrich_json_with_identifiers(data, text)
        assert any(
            i.get("identifier") == "10.1234/example"
            for i in result.get("identifiers", [])
        )

    def test_no_duplicate_doi(self):
        data = {
            "identifiers": [
                {"identifier": "10.1234/example", "identifierType": "DOI"}
            ]
        }
        text = "doi:10.1234/example"
        result = enrich_json_with_identifiers(data, text)
        dois = [
            i
            for i in result["identifiers"]
            if i.get("identifier") == "10.1234/example"
        ]
        assert len(dois) == 1

    def test_orcid_1to1_mapping(self):
        data = {
            "creators": [
                {"name": "Doe, John"},
                {"name": "Smith, Jane"},
            ]
        }
        text = "0000-0002-1825-0097 0000-0001-2345-6789"
        result = enrich_json_with_identifiers(data, text)
        assert len(result["creators"][0].get("nameIdentifiers", [])) == 1
        assert len(result["creators"][1].get("nameIdentifiers", [])) == 1
        assert "0000-0002-1825-0097" in result["creators"][0]["nameIdentifiers"][0]["nameIdentifier"]
        assert "0000-0001-2345-6789" in result["creators"][1]["nameIdentifiers"][0]["nameIdentifier"]

    def test_orcid_single_to_first_creator(self):
        data = {
            "creators": [
                {"name": "Doe, John"},
                {"name": "Smith, Jane"},
                {"name": "Lee, Pat"},
            ]
        }
        text = "0000-0002-1825-0097"
        result = enrich_json_with_identifiers(data, text)
        assert len(result["creators"][0].get("nameIdentifiers", [])) == 1
        assert len(result["creators"][1].get("nameIdentifiers", [])) == 0

    def test_orcid_no_duplicate(self):
        data = {
            "creators": [
                {
                    "name": "Doe, John",
                    "nameIdentifiers": [
                        {
                            "nameIdentifier": "https://orcid.org/0000-0002-1825-0097",
                            "nameIdentifierScheme": "ORCID",
                            "schemeURI": "https://orcid.org",
                        }
                    ],
                }
            ]
        }
        text = "0000-0002-1825-0097"
        result = enrich_json_with_identifiers(data, text)
        assert len(result["creators"][0]["nameIdentifiers"]) == 1

    def test_infers_scheme_for_existing_identifier(self):
        data = {
            "identifiers": [{"identifier": "10.1234/foo", "identifierType": ""}]
        }
        result = enrich_json_with_identifiers(data, "")
        assert result["identifiers"][0]["identifierType"] == "DOI"

    def test_infers_scheme_for_existing_name_identifier(self):
        data = {
            "creators": [
                {
                    "name": "Doe, John",
                    "nameIdentifiers": [
                        {"nameIdentifier": "https://orcid.org/0000-0002-1825-0097"}
                    ],
                }
            ]
        }
        result = enrich_json_with_identifiers(data, "")
        ni = result["creators"][0]["nameIdentifiers"][0]
        assert ni["nameIdentifierScheme"] == "ORCID"
        assert ni["schemeURI"] == "https://orcid.org"

    def test_infers_funder_scheme(self):
        data = {
            "fundingReferences": [
                {
                    "funderName": "DFG",
                    "funderIdentifier": "10.13039/501100001659",
                }
            ]
        }
        result = enrich_json_with_identifiers(data, "")
        fr = result["fundingReferences"][0]
        assert fr["funderIdentifierType"] == "Crossref Funder ID"
        # fundingReferences uses schemeUri (lowercase i)
        assert fr["schemeUri"] == "https://doi.org/10.13039"

    def test_funder_id_from_text(self):
        data = {
            "fundingReferences": [{"funderName": "DFG"}]
        }
        text = "Funded by https://doi.org/10.13039/501100001659"
        result = enrich_json_with_identifiers(data, text)
        assert result["fundingReferences"][0]["funderIdentifier"] == "10.13039/501100001659"

    def test_arxiv_from_text(self):
        data = {}
        text = "arXiv:2301.12345"
        result = enrich_json_with_identifiers(data, text)
        assert any(
            i.get("identifierType") == "arXiv"
            for i in result.get("identifiers", [])
        )

    def test_empty_raw_text(self):
        data = {"creators": [{"name": "Doe, John"}]}
        result = enrich_json_with_identifiers(data, "")
        assert result == data

    def test_does_not_mutate_original(self):
        data = {"creators": [{"name": "Doe, John"}]}
        original_creators = data["creators"].copy()
        enrich_json_with_identifiers(data, "doi:10.1234/foo")
        # Top-level dict should not have been mutated
        assert "identifiers" not in data


# ============================
# Caption ID auto-generation
# ============================


class TestCaptionIdAutoGeneration:
    def test_auto_generates_fig_ids(self):
        captions = [
            {"caption": "Figure 1. Overview"},
            {"caption": "Figure 2. Results"},
        ]
        result = _normalize_captions(captions, caption_type="fig")
        assert result[0]["id"] == "fig1"
        assert result[1]["id"] == "fig2"

    def test_auto_generates_table_ids(self):
        captions = [{"caption": "Table 1. Parameters"}]
        result = _normalize_captions(captions, caption_type="table")
        assert result[0]["id"] == "table1"

    def test_preserves_existing_ids(self):
        captions = [
            {"id": "custom1", "caption": "Figure 1. Overview"},
            {"caption": "Figure 2. Results"},
        ]
        result = _normalize_captions(captions, caption_type="fig")
        assert result[0]["id"] == "custom1"
        assert result[1]["id"] == "fig2"

    def test_string_caption_gets_id(self):
        result = _normalize_captions("A single caption", caption_type="fig")
        assert len(result) == 1
        assert result[0]["id"] == "fig1"
        assert result[0]["caption"] == "A single caption"

    def test_default_caption_type_is_fig(self):
        captions = [{"caption": "Some figure"}]
        result = _normalize_captions(captions)
        assert result[0]["id"] == "fig1"

    def test_empty_list(self):
        result = _normalize_captions([], caption_type="fig")
        assert result == []

    def test_empty_string(self):
        result = _normalize_captions("", caption_type="fig")
        assert result == []
