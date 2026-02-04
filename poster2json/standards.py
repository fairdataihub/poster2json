"""Example abstract base class for domain implementations."""

from abc import abstractmethod


class DataDomain:
    """
    Abstract base class for defining data domain implementations (example).

    Subclasses implement convert() and metadata() for a specific domain.
    """

    @abstractmethod
    def convert(self, infile, outfile, **kwargs):
        """Convert data from infile to outfile. Override in subclass."""
        pass

    @abstractmethod
    def metadata(self, files, outfile, **kwargs):
        """Extract metadata from files and save to outfile. Override in subclass."""
        pass
