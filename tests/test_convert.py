"""Converting poster files the pipeline cannot read directly (poster2json.convert)."""

from pathlib import Path

import pytest
from PIL import Image

from poster2json import convert
from poster2json.convert import (
    VISION_MAX_SIDE,
    ConversionError,
    convert_image_to_png,
    convert_office_to_pdf,
    convert_svg_to_pdf,
    find_libreoffice,
    needs_conversion,
    prepared_input,
)


def test_suffix_classes():
    assert needs_conversion("a.pptx") and needs_conversion("a.PPT") and needs_conversion("a.tif")
    assert needs_conversion("a.svg") and needs_conversion("a.docx")
    assert not needs_conversion("a.pdf") and not needs_conversion("a.png")
    assert not needs_conversion("a.jpeg") and not needs_conversion("a.txt")


@pytest.mark.parametrize("name", ["poster.pdf", "poster.png", "poster.JPG", "poster.txt"])
def test_native_and_unknown_files_pass_through_unchanged(tmp_path, name):
    f = tmp_path / name
    f.write_bytes(b"x")
    with prepared_input(f) as usable:
        assert usable == str(f)


def _open_png(path):
    img = Image.open(path)
    assert Path(path).suffix == ".png" and img.format == "PNG"
    return img


def test_cmyk_tiff_becomes_rgb_png(tmp_path):
    src = tmp_path / "poster.tif"
    Image.new("CMYK", (400, 300), (0, 255, 255, 0)).save(src)
    img = _open_png(convert_image_to_png(src, tmp_path))
    assert img.mode == "RGB" and img.size == (400, 300)
    r, g, b = img.getpixel((10, 10))
    assert r > 200 and g < 60 and b < 60  # CMYK (0,255,255,0) is red


def test_16bit_tiff_is_scaled_not_clipped(tmp_path):
    src = tmp_path / "scan.tiff"
    Image.new("I;16", (50, 50), 32768).save(src)  # mid grey in 16 bits
    img = _open_png(convert_image_to_png(src, tmp_path))
    value = img.getpixel((5, 5))[0]
    assert 120 <= value <= 136  # ~128, not clipped to 255


def test_multipage_tiff_uses_first_page(tmp_path):
    src = tmp_path / "pages.tif"
    first = Image.new("RGB", (80, 60), (255, 255, 255))
    second = Image.new("RGB", (80, 60), (0, 0, 0))
    first.save(src, save_all=True, append_images=[second])
    img = _open_png(convert_image_to_png(src, tmp_path))
    assert img.getpixel((5, 5)) == (255, 255, 255)


def test_transparent_gif_is_flattened_onto_white(tmp_path):
    src = tmp_path / "poster.gif"
    img = Image.new("P", (40, 40), 0)
    img.putpalette([0, 0, 0] * 256)
    img.save(src, transparency=0)
    out = _open_png(convert_image_to_png(src, tmp_path))
    assert out.mode == "RGB" and out.getpixel((1, 1)) == (255, 255, 255)


@pytest.mark.parametrize("suffix,fmt", [(".webp", "WEBP"), (".bmp", "BMP"), (".jfif", "JPEG")])
def test_other_raster_formats(tmp_path, suffix, fmt):
    src = tmp_path / ("poster" + suffix)
    Image.new("RGB", (120, 90), (10, 120, 200)).save(src, format=fmt)
    img = _open_png(convert_image_to_png(src, tmp_path))
    assert img.size == (120, 90)


def test_large_image_is_capped_at_vision_size(tmp_path):
    src = tmp_path / "huge.tif"
    Image.new("RGB", (4000, 3000), (255, 255, 255)).save(src)
    img = _open_png(convert_image_to_png(src, tmp_path))
    assert max(img.size) == VISION_MAX_SIDE
    assert img.size == (VISION_MAX_SIDE, 960)  # aspect ratio kept


def test_svg_becomes_pdf_with_selectable_text(tmp_path):
    import fitz

    src = tmp_path / "poster.svg"
    src.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600">'
        '<rect width="800" height="600" fill="white"/>'
        '<text x="40" y="80" font-size="48">Poster Title</text>'
        '<text x="40" y="160" font-size="20">Jane Smith, University of Maine</text></svg>',
        encoding="utf-8",
    )
    pdf = convert_svg_to_pdf(src, tmp_path)
    assert pdf.suffix == ".pdf"
    text = fitz.open(pdf)[0].get_text()
    assert "Poster Title" in text and "Jane Smith, University of Maine" in text
    with prepared_input(src) as usable:
        assert usable.endswith(".pdf")


def test_broken_svg_raises_conversion_error(tmp_path):
    src = tmp_path / "broken.svg"
    src.write_text("<svg this is not valid", encoding="utf-8")
    with pytest.raises(ConversionError, match="broken.svg"):
        convert_svg_to_pdf(src, tmp_path)


def test_unreadable_image_raises_conversion_error(tmp_path):
    src = tmp_path / "broken.tif"
    src.write_bytes(b"not a tiff at all")
    with pytest.raises(ConversionError, match="broken.tif"):
        convert_image_to_png(src, tmp_path)


def test_converted_files_are_cleaned_up(tmp_path):
    src = tmp_path / "poster.bmp"
    Image.new("RGB", (30, 30)).save(src)
    with prepared_input(src) as usable:
        assert Path(usable).exists() and usable.endswith(".png")
    assert not Path(usable).exists()


def test_libreoffice_found_at_default_install_location_when_not_on_path(tmp_path, monkeypatch):
    monkeypatch.delenv("POSTER2JSON_SOFFICE", raising=False)
    monkeypatch.setattr(convert.shutil, "which", lambda name: None)
    fake = tmp_path / "soffice"
    fake.write_text("")
    monkeypatch.setattr(convert, "_LIBREOFFICE_DEFAULT_PATHS", (str(tmp_path / "nope"), str(fake)))
    assert find_libreoffice() == str(fake)


def test_missing_libreoffice_gives_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.delenv("POSTER2JSON_SOFFICE", raising=False)
    monkeypatch.setattr(convert.shutil, "which", lambda name: None)
    monkeypatch.setattr(convert, "_LIBREOFFICE_DEFAULT_PATHS", ())
    src = tmp_path / "poster.pptx"
    src.write_bytes(b"x")
    with pytest.raises(ConversionError, match="LibreOffice"):
        convert_office_to_pdf(src, tmp_path)


def test_broken_libreoffice_path_gives_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTER2JSON_SOFFICE", str(tmp_path / "no-such-soffice"))
    src = tmp_path / "poster.pptx"
    src.write_bytes(b"x")
    with pytest.raises(ConversionError, match="LibreOffice"):
        convert_office_to_pdf(src, tmp_path)


@pytest.mark.skipif(find_libreoffice() is None, reason="LibreOffice not installed")
def test_office_document_becomes_pdf_with_selectable_text(tmp_path):
    import fitz

    src = tmp_path / "poster.rtf"
    src.write_text(r"{\rtf1\ansi Microplastics in crops\par Methods: algae collected\par}",
                   encoding="ascii")
    pdf = convert_office_to_pdf(src, tmp_path / "out")
    text = fitz.open(pdf)[0].get_text()
    assert "Microplastics in crops" in text and "algae collected" in text


# --- wiring into extract_poster (no models are loaded) ----------------------

def test_extract_poster_reports_conversion_failure_without_loading_models(tmp_path):
    from poster2json.extract import extract_poster

    src = tmp_path / "broken.tif"
    src.write_bytes(b"garbage")
    out = extract_poster(str(src))
    assert out["errorCode"] == "CONVERSION_FAILED" and "broken.tif" in out["error"]


def test_extract_poster_runs_pipeline_on_converted_file_with_original_suffix(tmp_path, monkeypatch):
    import poster2json.extract as ex

    seen = {}

    def fake_pipeline(path, original_ext, *args):
        seen["path"], seen["ext"] = path, original_ext
        seen["exists_during_run"] = Path(path).exists()
        return {"ok": True}

    monkeypatch.setattr(ex, "_extract_prepared", fake_pipeline)
    src = tmp_path / "poster.webp"
    Image.new("RGB", (60, 40)).save(src, format="WEBP")
    assert ex.extract_poster(str(src)) == {"ok": True}
    assert seen["path"].endswith(".png") and seen["exists_during_run"]
    assert seen["ext"] == ".webp"
    assert ex.EXT_TO_FORMAT[".webp"] == "image/webp"
    assert ex.EXT_TO_FORMAT[".pptx"].endswith("presentationml.presentation")
