"""Unit tests for poster2json.layout_blocks and the leaf-aware XY-cut helpers.

All inputs are synthetic char/word dicts, no PDFs needed.
"""

import pytest

from poster2json import layout_blocks as lb
from poster2json import xy_cut


def ch(text, x0, top, size=10.0, width=None, font="Arial", bottom=None):
    width = size * 0.5 if width is None else width
    return {
        "text": text, "x0": x0, "x1": x0 + width, "top": top,
        "bottom": top + size if bottom is None else bottom,
        "size": size, "fontname": font,
    }


def text_chars(s, x0, top, size=10.0, font="Arial"):
    out = []
    x = x0
    for t in s:
        if t == " ":
            x += size * 0.5
            continue
        out.append(ch(t, x, top, size, font=font))
        x += size * 0.5
    return out


def word(text, x0, top, size=10.0, font="Arial", w=None):
    w = size * 0.5 * len(text) if w is None else w
    return {"text": text, "x0": x0, "x1": x0 + w, "top": top,
            "bottom": top + size, "size": size, "fontname": font}


# ---------------------------------------------------------------- font size

def test_mode_size_prefers_most_common_and_ignores_spaces():
    chars = [ch("a", 0, 0, 10), ch("b", 5, 0, 10), ch("c", 10, 0, 24), ch(" ", 15, 0, 40)]
    assert lb.mode_size(chars) == 10.0


def test_mode_size_empty():
    assert lb.mode_size([]) == 0.0


# ------------------------------------------------------------------- lines

def test_cluster_leaf_lines_two_lines():
    chars = text_chars("hello", 0, 0) + text_chars("world", 0, 14)
    lines = lb.cluster_leaf_lines(chars, body_size=10.0)
    assert len(lines) == 2
    assert "".join(c["text"] for c in lines[0]) == "hello"
    assert "".join(c["text"] for c in lines[1]) == "world"


def test_body_size_tolerance_not_inflated_by_one_big_char():
    # One 40pt glyph in a leaf of 10pt text must not coarsen the tolerance so
    # much that two 10pt lines (14pt apart) merge.
    chars = text_chars("alpha", 0, 0) + text_chars("beta", 0, 14) + [ch("X", 100, 0, 40)]
    lines = lb.cluster_leaf_lines(chars, body_size=10.0, use_body_tol=True,
                                  attach_small=False)
    texts = ["".join(c["text"] for c in ln) for ln in lines]
    assert any("alpha" in t for t in texts)
    assert any("beta" in t for t in texts)
    assert not any("alpha" in t and "beta" in t for t in texts)


def test_superscript_attached_to_its_line():
    base = text_chars("Smith", 0, 20, 10.0)
    # raised 5pt tall-ish digit, 6pt size, right after the name
    sup = ch("1", 25.0, 17.0, size=6.0)
    other = text_chars("Jones", 0, 34, 10.0)
    lines = lb.cluster_leaf_lines(base + [sup] + other, body_size=10.0)
    assert len(lines) == 2
    first = "".join(c["text"] for c in lines[0])
    assert first == "Smith1"


def test_unattached_small_text_becomes_its_own_line():
    body = text_chars("Body text here", 0, 0, 12.0)
    # small text far below, with no neighbouring main char: a footnote
    foot = text_chars("note", 0, 60, 6.0)
    lines = lb.cluster_leaf_lines(body + foot, body_size=12.0)
    assert len(lines) == 2


def test_all_small_leaf_is_not_dropped():
    chars = text_chars("tiny", 0, 0, 6.0)
    lines = lb.cluster_leaf_lines(chars, body_size=12.0)
    assert len(lines) == 1


# ------------------------------------------------------------------- words

def test_chars_to_words_splits_on_gap():
    chars = text_chars("ab", 0, 0) + text_chars("cd", 20, 0)
    words = lb.chars_to_words(chars, x_tol=3.0)
    assert [w["text"] for w in words] == ["ab", "cd"]


def test_chars_to_words_splits_on_space_glyph():
    chars = [ch("a", 0, 0), ch("b", 5, 0)]  # touching, no gap
    assert [w["text"] for w in lb.chars_to_words(chars, 3.0)] == ["ab"]
    assert [w["text"] for w in lb.chars_to_words(chars, 3.0, space_xs=[5.0])] == ["a", "b"]


def test_superscript_is_its_own_word_but_not_its_own_line():
    chars = text_chars("Me-1", 0, 20, 10.0) + [ch("100", 20.0, 17.0, size=6.0, width=9.0)]
    words = lb.chars_to_words(chars, x_tol=3.0)
    assert [w["text"] for w in words] == ["Me-1", "100"]
    # word box comes from the main-size chars, so the line is not inflated
    assert words[0]["top"] == 20.0


def test_every_word_belongs_to_exactly_one_line():
    leaf = (text_chars("one two", 0, 0) + text_chars("three four", 0, 14)
            + text_chars("five", 0, 28))
    word_lines, ids = lb.build_word_lines([leaf], x_tol=3.0, body_size=10.0,
                                          flags=dict(lb.FLAGS))
    texts = [w["text"] for ln in word_lines for w in ln]
    assert sorted(texts) == sorted(["one", "two", "three", "four", "five"])
    assert len(word_lines) == 3
    assert ids == [0, 0, 0]


def test_space_glyph_of_other_size_does_not_split_words():
    # A blank filler run in a bigger size that overlaps the line must be ignored.
    line = text_chars("extensively", 0, 0, 8.0)
    filler = [{"text": " ", "x0": 10.0 + 3 * i, "x1": 13.0 + 3 * i, "top": 2.0,
               "bottom": 14.0, "size": 12.0, "fontname": "Arial"} for i in range(5)]
    leaf = line
    word_lines, _ = lb.build_word_lines([leaf], 3.0, 8.0, spaces=filler)
    assert [w["text"] for w in word_lines[0]] == ["extensively"]


def test_space_glyph_of_same_line_splits_words():
    line = [ch("a", 0, 0), ch("b", 5, 0)]
    space = {"text": " ", "x0": 4.0, "x1": 6.0, "top": 0, "bottom": 10,
             "size": 10.0, "fontname": "Arial"}
    word_lines, _ = lb.build_word_lines([line], 3.0, 10.0, spaces=[space])
    assert [w["text"] for w in word_lines[0]] == ["a", "b"]


def test_shadow_text_keeps_two_runs_in_stream_order():
    # The same string drawn twice, the second copy shifted by 2pt: sorting by
    # x would interleave the copies ("FFAAIRIR"); stream order keeps them apart.
    first = text_chars("FAIR", 0, 0)
    second = text_chars("FAIR", 2, 0)
    chars = first + second
    for i, c in enumerate(chars):
        c["_si"] = i
    words = lb.chars_to_words(chars, x_tol=3.0)
    assert [w["text"] for w in words] == ["FAIR", "FAIR"]
    assert [w["text"] for w in lb.drop_duplicate_words(words)] == ["FAIR"]


def test_drop_duplicate_words_keeps_distant_repeats():
    a = word("data", 0, 0)
    b = word("data", 100, 0)
    assert len(lb.drop_duplicate_words([a, b])) == 2


# ------------------------------------------------------------- hyphenation

def test_join_lines_plain():
    assert lb.join_lines(["hello world", "again"]) == "hello world again"


def test_join_lines_dehyphenates_when_joined_form_seen():
    vocab = lb.page_vocab(["information is power", "informa-", "tion"])
    out = lb.join_lines(["rich in informa-", "tion about it"], vocab)
    assert out == "rich in information about it"


def test_join_lines_keeps_true_compound():
    vocab = lb.page_vocab(["a long-term plan", "long-", "term"])
    out = lb.join_lines(["a long-", "term plan"], vocab)
    assert out == "a long-term plan"


def test_join_lines_unknown_keeps_hyphen_without_space():
    out = lb.join_lines(["some informa-", "tion here"], set())
    assert out == "some informa-tion here"


def test_join_lines_uppercase_continuation_not_joined():
    out = lb.join_lines(["see Fig-", "Ure"], set())
    assert out == "see Fig- Ure"


def test_continues_paragraph():
    assert lb.continues_paragraph("and the results of the", "second experiment were")
    assert not lb.continues_paragraph("and the results of the study.", "second")
    assert not lb.continues_paragraph("and the results of the", "Second experiment")
    assert not lb.continues_paragraph("Methods", "second")


# --------------------------------------------------------------- overprint

def test_dedupe_overprinted_removes_double_strike():
    a = ch("A", 10, 10)
    b = dict(a, x0=10.4, top=10.3)  # drawn again, 0.4pt off
    c = ch("A", 30, 10)             # a real second A
    out = lb.dedupe_overprinted([a, b, c])
    assert len(out) == 2


def test_dedupe_overprinted_keeps_repeated_letters_and_spaces():
    ll = [ch("l", 10, 0, width=2.0), ch("l", 12, 0, width=2.0)]
    sp = [ch(" ", 20, 0), ch(" ", 20, 0)]
    out = lb.dedupe_overprinted(ll + sp)
    assert len(out) == 4


# ----------------------------------------------------------------- rotated

def rot_char(t, x0, top, size=8.0, up=True):
    c = ch(t, x0, top, size, width=size, bottom=top + size * 0.6)
    c["matrix"] = (0.0, 1.0 if up else -1.0, -1.0, 0.0, x0, top)
    return c


def test_split_rotated_separates_vertical_chars():
    body = text_chars("a long upright sentence of body text here", 0, 0)
    rot = [rot_char("Y", 500, 300 - 5 * i) for i in range(4)]
    up, r = lb.split_rotated(body + rot)
    assert len(r) == 4 and len(up) == len(body)


def test_split_rotated_leaves_fully_rotated_page_alone():
    rot = [rot_char("Y", 500, 300 - 5 * i) for i in range(10)]
    up, r = lb.split_rotated(rot)
    assert r == [] and len(up) == 10


def test_rotated_word_lines_reads_bottom_to_top_and_keeps_words():
    # "AB" then a gap then "C", drawn upward at x=500
    chars = [rot_char("A", 500, 300), rot_char("B", 500, 295.5),
             rot_char("C", 500, 250)]
    lines, ids = lb.rotated_word_lines(chars, x_tol=3.0)
    assert len(lines) == 1
    assert [w["text"] for w in lines[0]] == ["AB", "C"]
    assert ids[0] >= 1_000_000


def test_rotated_word_lines_separate_strips():
    chars = [rot_char("A", 500, 300), rot_char("B", 560, 300)]
    lines, ids = lb.rotated_word_lines(chars, x_tol=3.0)
    assert len(lines) == 2 and ids[0] != ids[1]


# ------------------------------------------------------------ figure masks

def rect(x0, top, x1, bottom):
    return {"x0": x0, "top": top, "x1": x1, "bottom": bottom}


def test_build_figure_masks_ignores_background_and_clusters_cells():
    page_w, page_h = 600.0, 800.0
    background = rect(0, 0, 600, 800)
    cells = [rect(100 + 50 * i, 100 + 20 * j, 150 + 50 * i, 120 + 20 * j)
             for i in range(3) for j in range(3)]
    masks = lb.build_figure_masks([], [background] + cells, page_w, page_h, 10.0)
    assert len(masks) == 1
    assert masks[0]["kind"] == "graphic"
    x0, y0, x1, y1 = masks[0]["boxes"][0]
    assert x0 < 100 and y0 < 100 and x1 > 250 and y1 > 160


def test_build_figure_masks_drops_panel_with_many_children():
    page_w, page_h = 600.0, 800.0
    panel = rect(10, 10, 300, 300)
    kids = [rect(20, 20 + 30 * j, 100, 40 + 30 * j) for j in range(4)]
    # far apart so children do not cluster into one big union that is kept
    masks = lb.build_figure_masks([], [panel] + kids, page_w, page_h, 4.0)
    for m in masks:
        for b in m["boxes"]:
            assert not (b[0] == 10 and b[2] == 300)


def test_build_figure_masks_images():
    masks = lb.build_figure_masks([rect(0, 0, 200, 200)], [], 600.0, 800.0)
    assert [m["kind"] for m in masks] == ["image"]


def test_split_figure_words_moves_numeric_labels_only():
    masks = [{"kind": "graphic", "boxes": [(0, 0, 100, 40)]}]
    plot_line = [word("49", 5, 5), word("36.75", 40, 5), word("0", 80, 5)]
    body_line = [word("A", 200, 100), word("sentence", 220, 100), word("here", 280, 100)]
    body, body_ids, lab, lab_ids, bo, lo = lb.split_figure_words(
        [plot_line, body_line], [0, 0], masks, 10.0)
    assert [w["text"] for w in lab[0]] == ["49", "36.75", "0"]
    assert [w["text"] for w in body[0]] == ["A", "sentence", "here"]
    assert bo == [1] and lo == [0]
    # nothing is dropped
    assert sum(len(l) for l in body) + sum(len(l) for l in lab) == 6


def test_split_figure_words_keeps_prose_inside_mask():
    masks = [{"kind": "graphic", "boxes": [(0, 0, 400, 100)]}]
    prose = [word(w, 10 + 40 * i, 10) for i, w in enumerate(
        "this is a long running sentence of prose".split())]
    body, _, lab, _, _, _ = lb.split_figure_words([prose], [0], masks, 10.0)
    assert lab == [] and len(body) == 1


def test_split_figure_words_keeps_captions_and_headings():
    masks = [{"kind": "graphic", "boxes": [(0, 0, 400, 100)]}]
    cap = [word("Figure", 10, 10), word("2", 50, 10), word("1", 70, 10), word("2", 80, 10)]
    head = [word("RESULTS", 10, 50, size=20.0)]
    body, _, lab, _, _, _ = lb.split_figure_words([cap, head], [0, 0], masks, 10.0)
    assert lab == [] and len(body) == 2


def test_split_figure_words_no_masks_is_identity():
    lines = [[word("a", 0, 0)], [word("b", 0, 20)]]
    body, ids, lab, lab_ids, bo, lo = lb.split_figure_words(lines, [3, 4], [], 10.0)
    assert body == lines and ids == [3, 4] and lab == [] and bo == [0, 1]


# ------------------------------------------------------------------ xy_cut

def test_chars_to_leaves_two_columns_have_different_regions():
    left = text_chars("left column text", 0, 0) + text_chars("more left text", 0, 14)
    right = text_chars("right column text", 300, 0) + text_chars("more right text", 300, 14)
    leaves, regions = xy_cut.chars_to_leaves(left + right, page_width=600, page_height=800)
    assert len(leaves) == len(regions) >= 2
    assert len(set(regions)) >= 2
    # reading order: all left chars before right chars
    first = "".join(c["text"] for c in leaves[0])
    assert "left" in first.replace("more", "") or "left" in first


def test_chars_to_leaves_empty():
    assert xy_cut.chars_to_leaves([]) == ([], [])


def test_chars_to_reading_order_unchanged_api():
    chars = text_chars("hello", 0, 0) + text_chars("world", 0, 14)
    lines = xy_cut.chars_to_reading_order(chars, page_width=600, page_height=800)
    assert ["".join(c["text"] for c in ln) for ln in lines] == ["hello", "world"]


# ----------------------------------------------- block builder (needs torch)

def _blocks_fn():
    pytest.importorskip("torch")
    from poster2json.extract import _lines_to_blocks
    return _lines_to_blocks


def test_lines_to_blocks_breaks_at_region_change():
    f = _blocks_fn()
    # bottom of column 1 then top of column 2 (upward jump): never one block
    lines = [[word("end", 10, 700), word("of", 40, 700), word("col.", 60, 700)],
             [word("start", 300, 100), word("of", 340, 100), word("col2", 370, 100)]]
    assert len(f(lines, leaf_ids=[0, 1])) == 2
    assert len(f(lines, leaf_ids=[0, 0])) == 2  # upward jump alone also breaks


def test_lines_to_blocks_paragraph_continues_across_columns():
    f = _blocks_fn()
    lines = [[word("and", 10, 700), word("the", 40, 700), word("results", 60, 700)],
             [word("continue", 300, 100), word("here.", 360, 100)]]
    blocks = f(lines, leaf_ids=[0, 1])
    assert len(blocks) == 1
    assert blocks[0]["text"] == "and the results continue here."


def test_lines_to_blocks_same_region_stacked_lines_merge():
    f = _blocks_fn()
    lines = [[word("one", 10, 100), word("two", 40, 100)],
             [word("three", 10, 112), word("four", 50, 112)]]
    blocks = f(lines, leaf_ids=[0, 0])
    assert len(blocks) == 1
    assert blocks[0]["text"] == "one two three four"


def test_lines_to_blocks_same_row_cells_do_not_break():
    f = _blocks_fn()
    lines = [[word("1.", 10, 100)], [word("Introduction", 40, 100)]]
    assert len(f(lines, leaf_ids=[0, 1])) == 1


def test_lines_to_blocks_hyphen_join_flag():
    f = _blocks_fn()
    lines = [[word("some", 10, 100), word("informa-", 40, 100)],
             [word("tion", 10, 112), word("here", 40, 112)]]
    assert f(lines, hyphen_join=False)[0]["text"] == "some informa- tion here"
    assert f(lines, hyphen_join=True)[0]["text"] == "some informa-tion here"


def test_lines_to_blocks_legacy_call_unchanged():
    f = _blocks_fn()
    lines = [[word("a", 10, 100)], [word("b", 10, 112)]]
    blocks = f(lines)
    assert len(blocks) == 1 and blocks[0]["text"] == "a b"
