"""Unit tests for poster2json.generate module.

Skipped: poster2json.generate does not exist yet. Remove skip when module is added.
"""

import pytest

pytest.importorskip("poster2json.generate", reason="poster2json.generate module not implemented")


def test_generate_example_json_valid(tmp_path):
    from poster2json.generate import generate_example_json

    data = {"title": "Test", "version": "1.0"}
    out = tmp_path / "out.json"
    generate_example_json(data, str(out))
    assert out.read_text().strip().startswith("{")
    assert "Test" in out.read_text()
    assert "1.0" in out.read_text()


def test_generate_example_json_empty_data_raises(tmp_path):
    import pytest
    from poster2json.generate import generate_example_json

    out = tmp_path / "out.json"
    with pytest.raises(ValueError, match="Invalid input"):
        generate_example_json({}, str(out))
