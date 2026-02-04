"""Unit tests for poster2json.validate module."""

from poster2json.validate import validate_example


def test_validate_example_non_empty_dict():
    assert validate_example({"a": 1}) is True
    assert validate_example({"title": "x"}) is True


def test_validate_example_empty_dict():
    assert validate_example({}) is False


def test_validate_example_not_dict():
    assert validate_example([]) is False
    assert validate_example("x") is False
    assert validate_example(None) is False
