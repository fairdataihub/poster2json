"""Example validation - simple checks you can extend."""


def validate_example(data):
    """Return True if data is a non-empty dict (example validator)."""
    return isinstance(data, dict) and len(data) > 0
