"""Unit tests for poster2json.utils module."""

import pytest

from poster2json.utils import (
    extract_numbers,
    get_poster_format,
    is_supported_format,
    normalize_text,
    strip_to_alphanumeric,
    validate_file_path,
)


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


def test_validate_file_path_directory_raises(tmp_path):
    with pytest.raises(ValueError, match="not a file"):
        validate_file_path(str(tmp_path), preexisting_file=True)


def test_validate_file_path_no_flags():
    assert validate_file_path("/some/path.json") is True


def test_is_supported_format_pdf():
    assert is_supported_format("poster.pdf") is True
    assert is_supported_format("poster.PDF") is True


def test_is_supported_format_images():
    assert is_supported_format("poster.jpg") is True
    assert is_supported_format("poster.jpeg") is True
    assert is_supported_format("poster.png") is True


def test_is_supported_format_unsupported():
    assert is_supported_format("poster.txt") is False
    assert is_supported_format("poster.docx") is False
    assert is_supported_format("poster") is False


def test_get_poster_format_pdf():
    assert get_poster_format("poster.pdf") == "pdf"


def test_get_poster_format_image():
    assert get_poster_format("poster.jpg") == "image"
    assert get_poster_format("poster.jpeg") == "image"
    assert get_poster_format("poster.png") == "image"


def test_get_poster_format_unsupported():
    assert get_poster_format("poster.txt") is None
    assert get_poster_format("poster") is None


def test_normalize_text_string():
    assert normalize_text("  hello  world  ") == "  hello  world  "


def test_normalize_text_unicode_quotes():
    # Unicode curly double quotes (U+201C, U+201D) normalize to straight "
    left_right = "\u201chello\u201d"
    assert normalize_text(left_right) == '"hello"'


def test_normalize_text_list_coerced():
    assert normalize_text(["a", "b"]) == "a b"


def test_normalize_text_non_string_coerced():
    assert normalize_text(42) == "42"


def test_extract_numbers():
    assert extract_numbers("Version 2.1 and 3") == {"2", "2.1", "3"}


def test_extract_numbers_empty():
    assert extract_numbers("no digits") == set()


def test_strip_to_alphanumeric():
    assert strip_to_alphanumeric("Hello, World!") == "hello world"


def test_strip_to_alphanumeric_whitespace():
    assert strip_to_alphanumeric("  a   b  ") == "a b"
