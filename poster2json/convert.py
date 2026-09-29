"""
Convert poster files the pipeline cannot read directly into ones it can.

The extraction pipeline reads PDF (pdfplumber, with vision OCR as fallback) and
PNG/JPEG (vision OCR). Posters are deposited in other formats too, so they are
converted first, chosen by file suffix:

- Office documents (PowerPoint, Keynote, OpenDocument, Word, Publisher) become
  a PDF through LibreOffice. The text stays selectable, so the PDF is read like
  any other poster PDF, and falls back to vision OCR only if it has no text.
- SVG becomes a PDF (PyMuPDF). Text drawn as SVG <text> stays selectable and
  is read like any PDF; an SVG whose text is outlined falls back to vision OCR
  of the rendered page, exactly as an image-only PDF does.
- Other raster images (TIFF, BMP, GIF, WebP, JPEG 2000, ...) become an RGB PNG
  no larger than the vision OCR model's input size.

Conversion needs no model and runs before the pipeline. Converted files live in
a temporary directory that is removed when the caller is done.
"""

import contextlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator, Optional, Union

# The vision OCR model is given images with the long side at most this many
# pixels (extract.py resizes to it), so converting any larger only wastes work.
VISION_MAX_SIDE = 1280

# Read directly by the pipeline.
NATIVE_SUFFIXES = frozenset({".pdf", ".png", ".jpg", ".jpeg"})

# Converted to PDF with LibreOffice.
OFFICE_SUFFIXES = frozenset({
    # presentations
    ".ppt", ".pptx", ".pptm", ".pps", ".ppsx", ".pot", ".potx", ".odp", ".key",
    # drawing / desktop publishing
    ".odg", ".pub",
    # word processing
    ".doc", ".docx", ".odt", ".rtf",
})

# Converted to PDF with PyMuPDF.
VECTOR_SUFFIXES = frozenset({".svg"})

# Opened with Pillow and saved as PNG. HEIC/HEIF and AVIF need an optional
# Pillow plugin (pillow-heif, pillow-avif-plugin); without it the conversion
# fails with a clear message rather than a generic "unsupported".
RASTER_SUFFIXES = frozenset({
    ".tif", ".tiff", ".bmp", ".dib", ".gif", ".webp",
    ".jp2", ".j2k", ".jpx", ".jpf",
    ".jfif", ".jpe", ".pjpeg",
    ".ppm", ".pgm", ".pbm", ".pnm", ".tga",
    ".heic", ".heif", ".avif",
})

CONVERTIBLE_SUFFIXES = OFFICE_SUFFIXES | VECTOR_SUFFIXES | RASTER_SUFFIXES
SUPPORTED_SUFFIXES = NATIVE_SUFFIXES | CONVERTIBLE_SUFFIXES

LIBREOFFICE_TIMEOUT_SECONDS = int(os.environ.get("POSTER2JSON_LIBREOFFICE_TIMEOUT", "300"))


class ConversionError(RuntimeError):
    """A poster file could not be converted into a format the pipeline reads."""


def needs_conversion(path: Union[str, Path]) -> bool:
    return Path(path).suffix.lower() in CONVERTIBLE_SUFFIXES


def find_libreoffice() -> Optional[str]:
    """Path to the LibreOffice binary, honouring POSTER2JSON_SOFFICE."""
    override = os.environ.get("POSTER2JSON_SOFFICE")
    if override:
        return override
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    return None


def convert_office_to_pdf(src: Union[str, Path], out_dir: Union[str, Path],
                          timeout: int = LIBREOFFICE_TIMEOUT_SECONDS) -> Path:
    """Convert an office document to PDF with headless LibreOffice.

    Each call uses its own throwaway LibreOffice profile, so parallel
    conversions do not fight over the user profile lock.
    """
    src = Path(src)
    out_dir = Path(out_dir)
    soffice = find_libreoffice()
    if not soffice:
        raise ConversionError(
            f"Reading {src.suffix} files needs LibreOffice (soffice) on PATH, or "
            f"POSTER2JSON_SOFFICE pointing at it. Install LibreOffice, or convert "
            f"the poster to PDF first."
        )
    profile = Path(tempfile.mkdtemp(prefix="p2j-lo-profile-"))
    cmd = [
        soffice, "--headless", "--norestore", "--nolockcheck",
        f"-env:UserInstallation={profile.as_uri()}",
        "--convert-to", "pdf", "--outdir", str(out_dir), str(src),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ConversionError(f"LibreOffice timed out after {timeout}s converting {src.name}")
    except OSError as e:
        raise ConversionError(f"Could not run LibreOffice ({soffice}): {e}")
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    pdf = out_dir / (src.stem + ".pdf")
    if not pdf.exists() or pdf.stat().st_size == 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-300:]
        raise ConversionError(f"LibreOffice could not convert {src.name} to PDF. {detail}".strip())
    return pdf


def convert_svg_to_pdf(src: Union[str, Path], out_dir: Union[str, Path]) -> Path:
    """Convert an SVG poster to PDF with PyMuPDF, keeping <text> selectable."""
    import fitz  # PyMuPDF, already a poster2json dependency

    src = Path(src)
    out = Path(out_dir) / (src.stem + ".pdf")
    try:
        doc = fitz.open(str(src))
        out.write_bytes(doc.convert_to_pdf())
        doc.close()
    except Exception as e:
        raise ConversionError(f"Could not convert {src.name} to PDF: {e}")
    return out


def _register_optional_image_plugins(suffix: str) -> None:
    if suffix in {".heic", ".heif"}:
        try:
            from pillow_heif import register_heif_opener
        except ImportError:
            raise ConversionError(
                f"Reading {suffix} images needs the pillow-heif package "
                f"(pip install pillow-heif)."
            )
        register_heif_opener()
    elif suffix == ".avif":
        try:
            import pillow_avif  # noqa: F401  (registers the AVIF opener)
        except ImportError:
            pass  # recent Pillow builds read AVIF natively; Image.open decides


def _flatten_to_rgb(img):
    """RGB on a white background: transparency, palettes, CMYK and 16-bit all end up RGB."""
    from PIL import Image

    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    if img.mode.startswith("I;16"):
        # 16-bit greyscale (common in scientific TIFFs): Pillow clips rather
        # than scales when converting to 8-bit, so scale explicitly.
        img = img.convert("I").point(lambda v: v * (1 / 256)).convert("L")
    return img.convert("RGB")


def convert_image_to_png(src: Union[str, Path], out_dir: Union[str, Path],
                         max_side: int = VISION_MAX_SIDE) -> Path:
    """Convert a raster image to an RGB PNG sized for vision OCR.

    Multi-page TIFFs and animated GIFs contribute their first page/frame (a
    poster is one page). EXIF orientation is applied, transparency is flattened
    onto white, and the long side is capped at ``max_side``.
    """
    src = Path(src)
    out = Path(out_dir) / (src.stem + ".png")
    suffix = src.suffix.lower()

    from PIL import Image, ImageOps

    _register_optional_image_plugins(suffix)
    try:
        with Image.open(src) as img:
            img.seek(0)
            img.load()
            img = ImageOps.exif_transpose(img)
            img = _flatten_to_rgb(img)
    except ConversionError:
        raise
    except Exception as e:
        raise ConversionError(f"Could not read {src.name} as an image: {e}")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    img.save(out, format="PNG")
    return out


@contextlib.contextmanager
def prepared_input(path: Union[str, Path]) -> Iterator[str]:
    """Yield a path the pipeline can read, converting the file first if needed.

    PDF/PNG/JPEG (and unknown suffixes, which the pipeline then reports as
    unsupported) are yielded unchanged. Anything converted lives in a temporary
    directory removed on exit.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in CONVERTIBLE_SUFFIXES:
        yield str(path)
        return
    work = Path(tempfile.mkdtemp(prefix="p2j-convert-"))
    try:
        if suffix in OFFICE_SUFFIXES:
            converted = convert_office_to_pdf(path, work)
        elif suffix in VECTOR_SUFFIXES:
            converted = convert_svg_to_pdf(path, work)
        else:
            converted = convert_image_to_png(path, work)
        yield str(converted)
    finally:
        shutil.rmtree(work, ignore_errors=True)
