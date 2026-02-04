"""Unit tests for poster2json.utils module."""

import pytest

from poster2json.utils import feet_to_meters, validate_file_path


def test_feet_to_meters_integer():
    assert feet_to_meters(42) == pytest.approx(12.8016, rel=1e-4)


def test_feet_to_meters_invalid_raises():
    with pytest.raises(ValueError, match="Invalid input"):
        feet_to_meters("hello")


def test_validate_file_path_empty_raises():
    with pytest.raises(ValueError, match="empty"):
        validate_file_path("")


def test_validate_file_path_nonexistent_raises():
    with pytest.raises(FileNotFoundError):
        validate_file_path("nonexistent_file_xyz_123.md", preexisting_file=True)


def test_validate_file_path_valid(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("ok")
    assert validate_file_path(str(f), preexisting_file=True) is True
