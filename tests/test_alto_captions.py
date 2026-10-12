"""The alto layout engine feeds the engine neutral caption module.

Captions are found from the alto blocks and the figure regions, replaced in the
raw text by the one-line marker, and returned through ``captions_out`` exactly
as for the default engine; the alto caption label rule only handles labeled
blocks the caption module did not take.
"""

from types import SimpleNamespace

import pytest

from .test_layout_streams import PAGE_H, PAGE_W, page_of, string

CAPTION = "Figure 1. Spectrum of the sample measured at room temperature with the new probe."
BODY = "alpha beta gamma delta epsilon zeta eta theta iota kappa"


def _page():
    chars = []
    for k in range(6):
        chars += string(BODY, 40, 400 + k * 12)          # body text, 10 pt
    chars += string(CAPTION, 40, 262, size=9.0)           # caption right under the image
    page = page_of(chars)
    page.images = [{"x0": 40, "x1": 300, "top": 100, "bottom": 255}]
    page.rects, page.curves, page.lines = [], [], []
    return page


def _run(monkeypatch, engine, page=None, captions=True):
    import pdfplumber

    extract = pytest.importorskip("poster2json.extract")
    page = page or _page()
    pdf = SimpleNamespace(pages=[page], close=lambda: None)
    monkeypatch.setattr(pdfplumber, "open", lambda *_a, **_k: pdf)
    monkeypatch.setenv("POSTER2JSON_LAYOUT", engine)
    monkeypatch.setattr(extract, "CAPTION_ENGINE", captions)
    monkeypatch.setattr(extract, "CAPTION_RAW_MODE", "marker")
    caps = []
    text = extract.extract_text_with_pdfplumber("x.pdf", captions_out=caps)
    return text, caps


@pytest.mark.parametrize("engine", ["blocks", "alto"])
def test_caption_is_extracted_and_replaced_by_marker(monkeypatch, engine):
    text, caps = _run(monkeypatch, engine)
    assert len(caps) == 1
    assert caps[0]["kind"] == "figure"
    assert caps[0]["text"].startswith("Figure 1.")
    assert "room temperature" in caps[0]["text"]
    assert "[Figure caption 1 extracted]" in text
    assert "room temperature" not in text
    assert "## Figure 1" not in text            # not handled twice by the label rule
    assert "alpha beta" in text                  # body text is kept


def test_alto_page_geometry_reaches_the_caption_module(monkeypatch):
    extract = pytest.importorskip("poster2json.extract")
    page = _page()
    geo = {}
    monkeypatch.setenv("POSTER2JSON_LAYOUT", "alto")
    text_chars, x_tol, _ = extract._char_stats(page.chars, tolerant=True)
    blocks, fig_blocks, used_alto = extract._page_blocks(
        page, page.chars, text_chars, x_tol, PAGE_W, PAGE_H, geo)
    assert used_alto and not fig_blocks and blocks
    assert {"x0", "x1", "top", "bottom", "text", "size"} <= set(geo["words"][0])
    assert any(r["kind"] == "image" for r in geo["masks"])


def test_labeled_block_left_by_the_caption_module_keeps_the_alto_label_rule(monkeypatch):
    # no figure near the labeled line and captions off: the alto label rule
    # splits the label onto its own heading line and keeps it as printed
    page = page_of(string("Fig. 2. A line of text that is just prose here.", 40, 100))
    page.images, page.rects, page.curves, page.lines = [], [], [], []
    text, caps = _run(monkeypatch, "alto", page=page, captions=False)
    assert caps == []
    assert text.splitlines()[0] == "## Fig. 2"
