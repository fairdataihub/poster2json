"""Unit tests for poster2json.validate module."""

from poster2json.validate import (
    get_validation_errors,
    validate_comprehensive,
    validate_poster,
)

# Minimal valid poster JSON satisfying schema required fields
VALID_MINIMAL_POSTER = {
    "identifiers": [{"identifier": "10.5072/test.1", "identifierType": "DOI"}],
    "creators": [{"name": "Doe, John"}],
    "titles": [{"title": "Test Poster Title"}],
    "publisher": {"name": "Test Publisher"},
    "publicationYear": 2025,
    "subjects": [{"subject": "Testing"}],
    "dates": [{"date": "2025", "dateType": "Created"}],
    "language": "en",
    "types": {"resourceType": "Poster"},
    "formats": ["PDF"],
    "rightsList": [{"rights": "CC-BY-4.0"}],
    "descriptions": [{"descriptionType": "Abstract", "description": "A test abstract."}],
    "fundingReferences": [{"funderName": "Test Funder"}],
    "conference": {"conferenceName": "Test Conference", "conferenceYear": 2025},
}


def test_validate_poster_valid():
    assert validate_poster(VALID_MINIMAL_POSTER) is True


def test_validate_poster_invalid_empty():
    assert validate_poster({}) is False


def test_validate_poster_invalid_missing_required():
    data = {"titles": [{"title": "X"}]}
    assert validate_poster(data) is False


def test_validate_poster_invalid_wrong_type():
    assert validate_poster([]) is False
    assert validate_poster("not a dict") is False


def test_get_validation_errors_valid():
    assert get_validation_errors(VALID_MINIMAL_POSTER) == []


def test_get_validation_errors_invalid_returns_errors():
    errors = get_validation_errors({})
    assert len(errors) > 0
    for err in errors:
        assert "path" in err
        assert "message" in err
        assert "schema_path" in err


def test_validate_comprehensive_valid():
    result = validate_comprehensive(VALID_MINIMAL_POSTER)
    assert result["valid"] is True
    assert result["schema_errors"] == []
    assert "field_issues" in result
    assert "warnings" in result


def test_validate_comprehensive_invalid_schema():
    result = validate_comprehensive({})
    assert result["valid"] is False
    assert len(result["schema_errors"]) > 0


def test_validate_comprehensive_checks_creators_format():
    data = dict(VALID_MINIMAL_POSTER)
    data["creators"] = [{"name": "NoComma"}]
    result = validate_comprehensive(data)
    assert "field_issues" in result
    assert any("Family, Given" in str(i) for i in result["field_issues"])


def test_validate_comprehensive_warns_missing_content():
    result = validate_comprehensive(VALID_MINIMAL_POSTER)
    assert any("content" in str(w) for w in result["warnings"])
