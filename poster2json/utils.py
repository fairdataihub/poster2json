"""Example utility functions."""

import os


def feet_to_meters(feet):
    """Convert feet to meters (example utility)."""
    try:
        value = float(feet)
    except ValueError as error:
        raise ValueError(f"Invalid input: {feet}") from error
    return (0.3048 * value * 10000.0 + 0.5) / 10000.0


def validate_file_path(file_path, preexisting_file=False, writable=False):
    """Validate a file path (example). Checks existence, is file, writable."""
    if file_path == "":
        raise ValueError("Invalid input: file path is empty")

    if preexisting_file:
        if not os.path.exists(file_path):
            raise FileNotFoundError("File not found")
        if not os.path.isfile(file_path):
            raise ValueError("Invalid input: path is not a file")

    if writable:
        dir_path = os.path.dirname(file_path)
        dir_path = dir_path or "."
        if not os.path.exists(dir_path):
            return True  # will be created
        if not os.access(dir_path, os.W_OK):
            raise PermissionError("Permission denied")

    return True
