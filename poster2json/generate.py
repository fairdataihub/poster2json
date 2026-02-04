"""Example generation functions - write minimal JSON/text outputs."""

import json
from os import makedirs, path

from . import utils, validate


def generate_example_json(data, file_path):
    """Write a dict as JSON to file_path (example). Validates and writes."""
    if not utils.validate_file_path(file_path, writable=True):
        raise ValueError("Invalid file path")
    if not validate.validate_example(data):
        raise ValueError("Invalid input data")
    if not path.exists(path.dirname(file_path)):
        makedirs(path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return file_path
