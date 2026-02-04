"""
poster2json - Convert scientific posters to structured JSON metadata.

Extract structured metadata from scientific poster PDFs and images
using Large Language Models. Output conforms to the poster-json-schema
(DataCite-based format).

Basic Usage:
    >>> from poster2json import extract_poster, validate_poster
    >>> 
    >>> # Extract metadata from a poster
    >>> result = extract_poster("poster.pdf")
    >>> print(result["titles"][0]["title"])
    
    >>> # Validate extracted JSON
    >>> is_valid = validate_poster(result)

CLI Usage:
    $ poster2json extract poster.pdf -o result.json
    $ poster2json validate result.json
"""

from importlib.metadata import PackageNotFoundError, version

# Main functions
from .extract import extract_poster
from .validate import (
    get_validation_errors,
    validate_comprehensive,
    validate_poster,
)

try:
    __version__ = version("poster2json")
except PackageNotFoundError:
    __version__ = "(local)"

del PackageNotFoundError
del version

__all__ = [
    "extract_poster",
    "validate_poster",
    "validate_comprehensive",
    "get_validation_errors",
    "__version__",
]
