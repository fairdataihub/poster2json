"""poster2json - Example package structure."""

from importlib.metadata import PackageNotFoundError, version

from . import generate, utils, validate

try:
    __version__ = version("poster2json")
except PackageNotFoundError:
    __version__ = "(local)"

del PackageNotFoundError
del version
