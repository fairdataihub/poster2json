"""CLI tests."""

import json
import pytest
from click.testing import CliRunner

from poster2json.cli import main

# Minimal valid poster JSON for validate command
VALID_POSTER_JSON = {
    "identifiers": [{"identifier": "10.5072/test.1", "identifierType": "DOI"}],
    "creators": [{"name": "Doe, John"}],
    "titles": [{"title": "Test Poster"}],
    "publisher": {"name": "Test Publisher"},
    "publicationYear": 2025,
    "subjects": [{"subject": "Testing"}],
    "dates": [{"date": "2025", "dateType": "Created"}],
    "language": "en",
    "types": {"resourceType": "Poster"},
    "formats": ["PDF"],
    "rightsList": [{"rights": "CC-BY-4.0"}],
    "descriptions": [{"descriptionType": "Abstract", "description": "Test."}],
    "fundingReferences": [{"funderName": "Test Funder"}],
    "conference": {"conferenceName": "Test Conference", "conferenceYear": 2025},
}


@pytest.fixture
def runner():
    return CliRunner()


def test_cli_exits_zero(runner):
    result = runner.invoke(main)
    assert result.exit_code == 0
    assert "poster2json" in result.output


def test_cli_version(runner):
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "poster2json" in result.output
    assert "0.1" in result.output or "version" in result.output.lower()


def test_cli_validate_valid_file(runner, tmp_path):
    json_file = tmp_path / "poster.json"
    json_file.write_text(json.dumps(VALID_POSTER_JSON, indent=2), encoding="utf-8")
    result = runner.invoke(main, ["validate", str(json_file)])
    assert result.exit_code == 0
    assert "Valid" in result.output or "valid" in result.output.lower()


def test_cli_validate_invalid_json(runner, tmp_path):
    json_file = tmp_path / "bad.json"
    json_file.write_text("not valid json", encoding="utf-8")
    result = runner.invoke(main, ["validate", str(json_file)])
    assert result.exit_code != 0


def test_cli_validate_verbose(runner, tmp_path):
    json_file = tmp_path / "poster.json"
    json_file.write_text(json.dumps(VALID_POSTER_JSON, indent=2), encoding="utf-8")
    result = runner.invoke(main, ["validate", str(json_file), "--verbose"])
    assert result.exit_code == 0


def test_cli_info(runner):
    result = runner.invoke(main, ["info"])
    assert result.exit_code == 0
    assert "poster2json" in result.output
    assert "Documentation" in result.output or "documentation" in result.output.lower()
