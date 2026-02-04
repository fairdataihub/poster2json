"""Example domain implementation - stub that shows the pattern."""

from .standards import DataDomain


class ExampleDomain(DataDomain):
    """Example DataDomain subclass. Override convert and metadata for real use."""

    def convert(self, infile, outfile, **kwargs):
        """Stub: copy or transform infile to outfile."""
        with open(infile, "rb") as f_in:
            data = f_in.read()
        with open(outfile, "wb") as f_out:
            f_out.write(data)

    def metadata(self, files, outfile, **kwargs):
        """Stub: write a minimal metadata file listing input paths."""
        with open(outfile, "w", encoding="utf-8") as f:
            f.write("# Example metadata\n")
            for p in files:
                f.write(f"- {p}\n")
