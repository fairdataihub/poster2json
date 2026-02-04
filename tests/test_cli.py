"""Example CLI tests."""

import pytest
from click.testing import CliRunner

from poster2json.cli import main


@pytest.fixture
def runner():
    return CliRunner()


def test_cli_exits_zero(runner):
    result = runner.invoke(main)
    assert result.exit_code == 0
    assert "poster2json" in result.output
