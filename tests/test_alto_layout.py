"""Tests for the extract.py wiring of the alto layout engine.

The engine itself (poster2json.layout_streams) is covered by
tests/test_layout_streams.py.  These tests cover what extract.py does around
it: the engine switch, the block dict form, the per-page fallback to the
default engine, and the guarantee that the alto-only changes (caption label
kept as printed, contact block ordering) do not leak into the default path.
"""

import pytest

from .test_layout_streams import PAGE_H, PAGE_W, page_of, string


def _blk(text, x, y, w=100.0, h=12.0, fs=10.0, order=0):
    return {"text": text, "hpos": x, "vpos": y, "width": w, "height": h,
            "fontsize": fs, "bold": False, "order": order}


def _page():
    chars = (string("Poster Title Here", 50, 60, size=30)
             + string("first line of the body", 40, 150)
             + string("second line of the body", 40, 162))
    return page_of(chars)


def test_layout_engine_switch_and_block_dicts(monkeypatch):
    extract = pytest.importorskip("poster2json.extract")

    monkeypatch.delenv("POSTER2JSON_LAYOUT", raising=False)
    assert extract._layout_engine() == extract.LAYOUT_ENGINE == "blocks"
    monkeypatch.setenv("POSTER2JSON_LAYOUT", "ALTO")
    assert extract._layout_engine() == "alto"
    monkeypatch.setenv("POSTER2JSON_LAYOUT", "bogus")
    assert extract._layout_engine() == "blocks"

    page = _page()
    blocks = extract._alto_blocks(page, page.chars, PAGE_W, PAGE_H)
    assert blocks[0]["text"] == "Poster Title Here"
    assert blocks[0]["fontsize"] == 30
    assert blocks[1]["text"] == "first line of the body second line of the body"
    for key in ("hpos", "vpos", "width", "height", "cx", "text", "fontsize",
                "bold", "region", "order"):
        assert key in blocks[0]


def test_rotated_blocks_are_flagged_for_the_header_rules():
    extract = pytest.importorskip("poster2json.extract")
    chars = string("Poster Title Here", 50, 60, size=30) + string("side label", 20, 600, size=10, theta=270.0)
    page = page_of(chars)
    blocks = extract._alto_blocks(page, page.chars, PAGE_W, PAGE_H)
    flags = {b["text"]: b["rotated"] for b in blocks}
    assert flags == {"Poster Title Here": False, "side label": True}


@pytest.mark.parametrize("exc", [RecursionError("maximum recursion depth exceeded"),
                                 ValueError("bad glyph"), ZeroDivisionError()])
def test_alto_failure_falls_back_to_the_blocks_engine(monkeypatch, exc):
    extract = pytest.importorskip("poster2json.extract")
    page = _page()
    sentinel = ([_blk("fallback", 0, 0)], [])

    def boom(*a, **k):
        raise exc

    monkeypatch.setenv("POSTER2JSON_LAYOUT", "alto")
    monkeypatch.setattr(extract, "_alto_blocks", boom)
    monkeypatch.setattr(extract, "_xy_cut_blocks", lambda *a, **k: sentinel)
    blocks, fig_blocks, used_alto = extract._page_blocks(
        page, page.chars, list(page.chars), 3.0, PAGE_W, PAGE_H)
    assert blocks == sentinel[0] and fig_blocks == [] and used_alto is False


def test_alto_success_reports_alto(monkeypatch):
    extract = pytest.importorskip("poster2json.extract")
    page = _page()
    monkeypatch.setenv("POSTER2JSON_LAYOUT", "alto")
    blocks, fig_blocks, used_alto = extract._page_blocks(
        page, page.chars, list(page.chars), 3.0, PAGE_W, PAGE_H)
    assert used_alto is True and fig_blocks == [] and blocks


def test_default_engine_never_calls_the_alto_engine(monkeypatch):
    extract = pytest.importorskip("poster2json.extract")
    page = _page()
    sentinel = ([_blk("default", 0, 0)], [])
    monkeypatch.delenv("POSTER2JSON_LAYOUT", raising=False)
    monkeypatch.setattr(extract, "_alto_blocks",
                        lambda *a, **k: pytest.fail("alto engine called"))
    monkeypatch.setattr(extract, "_xy_cut_blocks", lambda *a, **k: sentinel)
    blocks, _, used_alto = extract._page_blocks(
        page, page.chars, list(page.chars), 3.0, PAGE_W, PAGE_H)
    assert blocks == sentinel[0] and used_alto is False


# ------------------------------------------------ contact block ordering

def _contact_page():
    blocks = [_blk("Title Words", 40, 20, 500, 40, fs=40, order=0)]
    for i, n in enumerate(["Ann", "Bob", "Cy"]):
        blocks.append(_blk(f"{n} Smith 1", 40 + 150 * i, 80 + 0.3 * i, 120, 12, order=1 + 2 * i))
        blocks.append(_blk(f"{n.lower()}@uni.edu", 40 + 150 * i, 94 + 0.1 * (3 - i), 120, 12,
                           order=2 + 2 * i))
    blocks.append(_blk("Body text of the poster goes here", 40, 300, 200, 200, order=9))
    return blocks


def test_email_stays_after_its_author_name_in_alto():
    extract = pytest.importorskip("poster2json.extract")
    out = extract._partition_blocks(_contact_page(), page_h=1000.0, page_median_fs=10.0,
                                    col_start=80.0, col_end=900.0, span_threshold=300.0,
                                    alto=True)
    texts = [b["text"] for b in out]
    assert texts[1:7] == ["Ann Smith 1", "ann@uni.edu", "Bob Smith 1", "bob@uni.edu",
                          "Cy Smith 1", "cy@uni.edu"]


def test_default_partition_is_the_original_one():
    extract = pytest.importorskip("poster2json.extract")
    out = extract._partition_blocks(_contact_page(), page_h=1000.0, page_median_fs=10.0,
                                    col_start=80.0, col_end=900.0, span_threshold=300.0)
    texts = [b["text"] for b in out]
    # original behavior: e-mail blocks are lifted and sorted by raw (top, left)
    assert texts[0] == "Title Words"
    raw = sorted([b for b in _contact_page() if "@" in b["text"]],
                 key=lambda b: (b["vpos"], b["hpos"]))
    assert texts[1:4] == [b["text"] for b in raw]
    assert out == extract._partition_blocks_default(
        _contact_page(), 1000.0, 10.0, 80.0, 900.0, 300.0)


def test_standalone_contact_blocks_are_lifted_in_row_order_in_alto():
    extract = pytest.importorskip("poster2json.extract")
    # three contact blocks on one printed row whose float tops are jittered
    blocks = [
        _blk("Title Words", 40, 20, 500, 40, fs=40, order=0),
        _blk("Body text of the poster goes here", 40, 300, 200, 200, order=1),
        _blk("c@uni.edu", 400, 80.30, 100, 12, order=2),
        _blk("a@uni.edu", 40, 80.45, 100, 12, order=3),
        _blk("b@uni.edu", 200, 80.10, 100, 12, order=4),
    ]
    out = extract._partition_blocks(blocks, page_h=1000.0, page_median_fs=10.0,
                                    col_start=80.0, col_end=900.0, span_threshold=300.0,
                                    alto=True)
    assert [b["text"] for b in out][1:4] == ["a@uni.edu", "b@uni.edu", "c@uni.edu"]


# ------------------------------------------------ caption labels

def test_caption_label_is_kept_as_printed_in_alto():
    extract = pytest.importorskip("poster2json.extract")
    split = lambda t: extract._split_caption_label(t, keep_label=True)  # noqa: E731
    assert split("Fig. 1. Spectrum of MDH") == ("Fig. 1", "Spectrum of MDH")
    assert split("Figure 2: Overview") == ("Figure 2", "Overview")
    assert split("Table 3. Results by group") == ("Table 3", "Results by group")
    assert split("Tab 4: Costs") == ("Tab 4", "Costs")
    assert split("Figures of merit are listed") is None
    assert split("Fig. 1") is None


def test_default_caption_label_is_normalized():
    extract = pytest.importorskip("poster2json.extract")
    split = extract._split_caption_label
    assert split("Fig. 1. Spectrum of MDH") == ("Figure 1", "Spectrum of MDH")
    assert split("fig 2: Overview") == ("Figure 2", "Overview")
    assert split("Tab. 3: Costs") == ("Table 3", "Costs")
    assert split("Table 4. Results") == ("Table 4", "Results")
    assert split("Figures of merit are listed") is None


# ------------------------------------------------ headline run

def test_title_font_blocks_after_other_text_keep_their_place_in_alto():
    extract = pytest.importorskip("poster2json.extract")
    blocks = [
        _blk("Big Title", 40, 20, 500, 40, fs=40, order=0),
        _blk("Subtitle in title font", 40, 62, 400, 30, fs=30, order=1),
        _blk("Ann Smith and Bob Jones", 40, 100, 300, 12, order=2),
        _blk("Introduction", 40, 130, 200, 30, fs=30, order=3),
        _blk("Body text of the poster goes here", 40, 300, 200, 200, order=4),
    ]
    out = extract._partition_blocks(blocks, page_h=1000.0, page_median_fs=10.0,
                                    col_start=160.0, col_end=900.0, span_threshold=300.0,
                                    alto=True)
    assert [b["text"] for b in out] == [
        "Big Title", "Subtitle in title font", "Ann Smith and Bob Jones",
        "Introduction", "Body text of the poster goes here"]
    # the original partition still lifts every title-font block
    old = extract._partition_blocks(blocks, page_h=1000.0, page_median_fs=10.0,
                                    col_start=160.0, col_end=900.0, span_threshold=300.0)
    assert [b["text"] for b in old][:3] == ["Big Title", "Subtitle in title font", "Introduction"]
