"""Utility functions for poster2json."""

import os
import re
import unicodedata
from pathlib import Path
from typing import Optional


def validate_file_path(
    file_path: str, 
    preexisting_file: bool = False, 
    writable: bool = False
) -> bool:
    """
    Validate a file path.
    
    Args:
        file_path: Path to validate
        preexisting_file: If True, check that file exists
        writable: If True, check that directory is writable
        
    Returns:
        True if valid
        
    Raises:
        ValueError: If path is empty or invalid
        FileNotFoundError: If preexisting_file=True and file doesn't exist
        PermissionError: If writable=True and directory is not writable
    """
    if not file_path:
        raise ValueError("Invalid input: file path is empty")

    if preexisting_file:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        if not os.path.isfile(file_path):
            raise ValueError(f"Path is not a file: {file_path}")

    if writable:
        dir_path = os.path.dirname(file_path) or "."
        if not os.path.exists(dir_path):
            return True  # will be created
        if not os.access(dir_path, os.W_OK):
            raise PermissionError(f"Cannot write to directory: {dir_path}")

    return True


def is_supported_format(file_path: str) -> bool:
    """
    Check if file format is supported for poster extraction.
    
    Args:
        file_path: Path to poster file
        
    Returns:
        True if PDF, JPG, JPEG, or PNG
    """
    ext = Path(file_path).suffix.lower()
    return ext in [".pdf", ".jpg", ".jpeg", ".png"]


def get_poster_format(file_path: str) -> Optional[str]:
    """
    Get the format type of a poster file.
    
    Args:
        file_path: Path to poster file
        
    Returns:
        "pdf", "image", or None if unsupported
    """
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    elif ext in [".jpg", ".jpeg", ".png"]:
        return "image"
    return None


def normalize_text(text: str) -> str:
    """
    Normalize text for comparison.
    
    Handles:
    - Unicode normalization (NFKD)
    - Whitespace consolidation
    - Quote unification
    - Dash normalization
    
    Args:
        text: Input text
        
    Returns:
        Normalized text
    """
    if isinstance(text, list):
        text = " ".join(str(t) for t in text)
    elif not isinstance(text, str):
        text = str(text)

    # Whitespace normalization
    space_chars = [
        "\xa0", "\u2000", "\u2001", "\u2002", "\u2003", "\u2004",
        "\u2005", "\u2006", "\u2007", "\u2008", "\u2009", "\u200a",
        "\u202f", "\u205f", "\u3000",
    ]
    for space in space_chars:
        text = text.replace(space, " ")

    # Quote normalization
    single_quotes = [""", """, "‛", "′", "‹", "›", "‚", "‟"]
    for quote in single_quotes:
        text = text.replace(quote, "'")

    double_quotes = ['"', '"', "„", "‟", "«", "»", "〝", "〞", "〟", "＂"]
    for quote in double_quotes:
        text = text.replace(quote, '"')

    # Dash normalization
    hyphens_and_dashes = ["‐", "‑", "‒", "–", "—", "―", "−"]
    for dash in hyphens_and_dashes:
        text = text.replace(dash, "-")

    # Unicode normalization
    text = unicodedata.normalize("NFKD", text)

    return text


def extract_numbers(text: str) -> set:
    """
    Extract all numeric values from text.
    
    Args:
        text: Input text
        
    Returns:
        Set of numeric strings found
    """
    return set(re.findall(r"\d+\.?\d*", text))


def strip_to_alphanumeric(text: str) -> str:
    """
    Strip text to alphanumeric characters only.
    
    Args:
        text: Input text
        
    Returns:
        Lowercase text with only alphanumeric chars and spaces
    """
    return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9\s]", "", text)).strip().lower()
