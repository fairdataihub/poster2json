"""Behavior tests for poster2json.layout_streams.

All inputs are synthetic pdfplumber-style char dicts whose box, size and text
matrix agree with each other, so no PDF files are needed.  The tests follow
the numbered requirements of the layout specification (word, line, block and
order rules, and the robustness requirements).
"""

import importlib.util
import math
import os
import sys
import time
from types import SimpleNamespace

import pytest

try:
    from poster2json import layout_streams as ls
except ImportError:  # package import needs heavy deps; load the module directly
    _path = os.path.join(os.path.dirname(__file__), "..", "poster2json", "layout_streams.py")
    _spec = importlib.util.spec_from_file_location("layout_streams_t", _path)
    ls = importlib.util.module_from_spec(_spec)
    sys.modules["layout_streams_t"] = ls
    _spec.loader.exec_module(ls)

PAGE_W, PAGE_H = 600.0, 800.0


# ---------------------------------------------------------------------------
# Synthetic input
# ---------------------------------------------------------------------------
def _unit(theta):
    r = math.radians(theta)
    c, s = round(math.cos(r), 12), round(math.sin(r), 12)
    return c, s


def mk(text, x, y, size=10.0, adv=None, font="Helvetica", theta=0.0,
       page_h=PAGE_H, org=(0.0, 0.0), shear=0.0, rise_box=0.0):
    """One char.  (x, y) is the glyph origin in the top-left frame (y down);
    theta is the reading direction in that frame (90 reads downward).  ``org``
    is the page box origin (non-zero MediaBox)."""
    adv = size * 0.5 if adv is None else adv
    c, s = _unit(theta)
    # matrix in pdf space (y up): direction (c, -s), up vector (s, c)
    matrix = (c, -s, s, c, x, page_h - y)
    if shear:
        matrix = (c, -s, s + shear * c, c - shear * s, x, page_h - y)
    pts = []
    for u in (0.0, adv):
        for v in (-0.75 * size, 0.25 * size):
            pts.append((x + u * c - v * s, y + u * s + v * c))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, x1, top, bottom = min(xs), max(xs), min(ys) - rise_box, max(ys) - rise_box
    if shear:
        x1 += shear * size           # a sheared glyph's box grows although its origin stays
    return dict(text=text, size=size, fontname=font, adv=adv, upright=(theta == 0.0),
                matrix=matrix, x0=x0 + org[0], x1=x1 + org[0],
                top=top + org[1], bottom=bottom + org[1])


def string(s, x, y, size=10.0, font="Helvetica", theta=0.0, adv=None, gap_chars=()):
    """Chars for a string; spaces are real space glyphs."""
    a = size * 0.5 if adv is None else adv
    c, sn = _unit(theta)
    out = []
    pos = 0.0
    for t in s:
        out.append(mk(t, x + pos * c, y + pos * sn, size, a, font, theta))
        pos += a
    return out


def page_of(chars, w=PAGE_W, h=PAGE_H, org=(0.0, 0.0)):
    if h != PAGE_H:          # keep matrix origins consistent with the page height
        chars = [dict(c, matrix=c["matrix"][:5] + (c["matrix"][5] + h - PAGE_H,))
                 if c.get("matrix") is not None and len(c["matrix"]) == 6 else c
                 for c in chars]
    return SimpleNamespace(chars=list(chars), width=w, height=h,
                           bbox=(org[0], org[1], org[0] + w, org[1] + h))


def run(chars, w=PAGE_W, h=PAGE_H, **kw):
    return ls.ordered_blocks(page_of(chars, w, h), **kw)


def texts(blocks):
    return [" ".join(ln.text for ln in b.lines) for b in blocks]


def lines_of(blocks):
    return [ln.text for b in blocks for ln in b.lines]


def one_line(chars):
    out = lines_of(run(chars))
    assert len(out) == 1, out
    return out[0]


def para(label, x, y0, n=2, size=10.0, step=12.0, width_chars=18):
    """n lines of one paragraph; each line text is ``label`` plus filler."""
    chars = []
    for k in range(n):
        body = f"{label} l{k} ".ljust(width_chars, "z")
        chars += string(body, x, y0 + k * step, size)
    return chars


# ---------------------------------------------------------------------------
# E1: words
# ---------------------------------------------------------------------------
def test_word_gap_thresholds_fs20():
    # glyph a occupies x 200..212 (advance 12), origin gaps relative to its end
    a = mk("a", 200, 300, 20, 12)
    # origin 1.5 after the end: joins
    assert one_line([a, mk("b", 213.5, 300, 20, 12)]) == "ab"
    # origin 3 after the end: visible space
    assert one_line([a, mk("b", 215, 300, 20, 12)]) == "a b"
    # origin 7 behind the end (0.35 fs): backstep, new word, no space
    assert one_line([a, mk("b", 205, 300, 20, 12)]) == "ab"
    # origin 4 behind the end (0.2 fs): kerning, same word
    assert one_line([a, mk("b", 208, 300, 20, 12)]) == "ab"


def test_word_split_kinds_by_count():
    def nwords(chars):
        items = ls._merge_accents(ls._drop_overprints(
            ls._prepare(None, chars, ls._page_frame(page_of(chars)), None)))
        return len(ls._build_words(items))

    a = mk("a", 200, 300, 20, 12)
    assert nwords([a, mk("b", 213.5, 300, 20, 12)]) == 1
    assert nwords([a, mk("b", 215, 300, 20, 12)]) == 2
    assert nwords([a, mk("b", 205, 300, 20, 12)]) == 2
    assert nwords([a, mk("b", 208, 300, 20, 12)]) == 1
    assert nwords([a, mk("b", 212.0, 300.8, 20, 12)]) == 1      # 0.8 pt shift joins
    assert nwords([a, mk("b", 212.0, 296.0, 10, 6)]) == 2       # 4 pt shift splits


def test_raised_small_glyph_is_superscript_separated_from_name():
    chars = string("Smith", 100, 300, 20) + [mk("1", 150, 296, 12, 6)] + \
        string(" Jones", 156, 300, 20)
    assert one_line(chars) == "Smith 1 Jones"


def test_superscript_that_pokes_above_the_line_top_is_still_a_superscript():
    # the raised digit's box top is 6 pt above the name's top: it must still be
    # separated from the name, and the next name is separated by its own space
    chars = string("Toker", 100, 300, 30)
    chars += [dict(mk("1", 175, 289, 21), top=289 - 0.75 * 21)]
    chars += string(" Ida", 190, 300, 30)
    assert one_line(chars) == "Toker 1 Ida"
    chars = string("Me-1", 100, 300, 32) + string("100", 164, 291, 21)
    assert one_line(chars) == "Me-1 100"


def test_no_space_between_a_superscript_and_closing_punctuation():
    chars = string("Zande", 100, 300, 30) + string("1", 175, 288, 20)
    chars += string(",", 185, 300, 30) + string(" Loes", 200, 300, 30)
    assert one_line(chars) == "Zande 1, Loes"


def test_subscript_glues():
    chars = string("CO", 100, 300, 20) + [mk("2", 120, 305, 12, 6)] + string(" x", 126, 300, 20)
    assert one_line(chars) == "CO2 x"


def test_real_space_glyph_and_cid_boundaries():
    chars = string("ab cd", 50, 100, 10)
    assert one_line(chars) == "ab cd"
    chars = string("ab", 50, 100, 10) + [dict(mk("x", 60, 100, 10), text="(cid:12)")] \
        + string("cd", 60, 100, 10)
    assert one_line(chars) == "ab cd"


# ---------------------------------------------------------------------------
# E2: sheared glyph keeps the baseline of its origin
# ---------------------------------------------------------------------------
def test_sheared_subscript_joins_its_word_and_keeps_the_paragraph():
    chars = []
    for k in range(3):
        y = 100 + 12 * k
        chars += string("The constant K", 50, y, 9)
        sub = mk("0", 50 + 14 * 4.5, y, 9, 4.5, shear=0.33)
        sub["top"] += 19.7          # the sheared box is reported far below the K
        sub["bottom"] += 19.7
        chars.append(sub)
        chars += string(" is fixed", 50 + 15 * 4.5, y, 9)
    blocks = run(chars)
    assert len(blocks) == 1 and len(blocks[0].lines) == 3
    assert blocks[0].lines[0].text == "The constant K0 is fixed"


# ---------------------------------------------------------------------------
# E3: lines
# ---------------------------------------------------------------------------
def test_line_rules_at_size_10():
    first = string("word", 150, 500, 10, adv=12.5)          # ends at x 200
    assert first[-1]["x1"] == pytest.approx(200.0)

    def lines(nxt):
        return lines_of(run(first + nxt))

    assert lines(string("zz", 214, 500, 10)) == ["word zz"]  # 14 past the end, same row
    assert len(lines(string("zz", 216, 500, 10))) == 2        # 16 past the end
    sup = lines([mk("2", 201, 496, 6, 3)])                    # 4 above, half size
    assert sup == ["word 2"]
    assert len(lines(string("zz", 150, 512, 10))) == 2        # a later line
    assert len(lines(string("zz", 90, 500, 10))) == 2         # reading went backward


# ---------------------------------------------------------------------------
# E5-E8, E11: blocks
# ---------------------------------------------------------------------------
def test_block_leading_and_size_rules():
    def blocks(ys, sizes=None):
        chars = []
        for i, y in enumerate(ys):
            chars += string("line text here", 50, y, (sizes or [10] * len(ys))[i])
        return run(chars)

    assert len(blocks([100, 112.5, 125])) == 1
    assert len(blocks([100, 112.5, 125, 142])) == 2           # step 17 starts a block
    assert len(blocks([100, 112], [10, 10.4])) == 1
    assert len(blocks([100, 112], [10, 11])) == 2             # heading versus body


def test_bullet_glyph_box_does_not_inflate_line_step():
    # symbol-font bullet whose box top sits 5.3 pt above the text top; the
    # line step 53 is under the limit 1.5 * 38.5 on baselines
    chars = []
    for k in range(2):
        y = 200 + 53 * k
        b = mk("\u2022", 60, y, 38.5, 20, font="Symbol")
        b["top"] -= 5.3
        chars.append(b)
        chars += string(" Research software is a critical", 80, y, 38.5, adv=19)
    blocks = run(chars, w=1400, h=800)
    assert len(blocks) == 1 and len(blocks[0].lines) == 2


def test_bold_tail_and_bold_heading_stay_in_their_block():
    chars = string("vulnerability categories.", 50, 100, 10)
    chars += string("(see Figure 4).", 50, 112, 10, font="Helvetica-Bold")
    chars += string("Fine-tuning also reduced it.", 50, 124, 10)
    blocks = run(chars)
    assert len(blocks) == 1
    # with the heading split off, a same-size bold heading above body text also stays together
    chars = string("National Data Discovery", 50, 100, 10, font="Helvetica-Bold")
    chars += string("Indexes Canadian data repositories", 50, 112, 10)
    assert len(run(chars, split_headings=False)) == 1


def test_bold_heading_line_closes_before_regular_text():
    chars = string("ABSTRACT", 50, 100, 10, font="Helvetica-Bold")
    chars += string("The first results of the application", 50, 112, 10)
    chars += string("continue on a second line here", 50, 124, 10)
    blocks = run(chars)
    assert texts(blocks) == ["ABSTRACT", "The first results of the application continue on a second line here"]
    assert blocks[0].bold and not blocks[1].bold


def test_two_line_bold_heading_splits_but_a_bold_lead_in_does_not():
    chars = string("A TWO LINE", 50, 100, 10, font="Helvetica-Bold")
    chars += string("BOLD HEADING", 50, 112, 10, font="Helvetica-Bold")
    chars += string("body text follows here", 50, 124, 10)
    assert len(run(chars)) == 2
    # a bold run that only starts a line of body text is not a heading
    chars = string("Results.", 50, 100, 10, font="Helvetica-Bold")
    chars += string(" the body text continues on", 90, 100, 10)
    chars += string("and carries on below it", 50, 112, 10)
    assert len(run(chars)) == 1
    # a bold line below body text never splits (tail rule)
    chars = string("plain body line", 50, 100, 10)
    chars += string("BOLD TAIL", 50, 112, 10, font="Helvetica-Bold")
    chars += string("more plain text", 50, 124, 10)
    assert len(run(chars)) == 1


def test_lone_mark_under_a_bold_word_stays_with_it():
    chars = string("CD83", 100, 100, 11, font="Helvetica-Bold")
    chars += string("*", 100, 112, 11)
    assert texts(run(chars)) == ["CD83 *"]


def test_bold_name_above_its_contact_line_is_not_a_heading():
    chars = string("Adel ElZemity", 100, 100, 11, font="Helvetica-Bold")
    chars += string("AE455@kent.ac.uk ORCID: 0000", 100, 112, 11)
    assert len(run(chars)) == 1


def test_bold_heading_split_applies_inside_interleaved_lanes():
    chars = []
    for x in (50, 250, 450):
        chars += string("HEAD", x, 100, 10, font="Helvetica-Bold")
        for k in range(5):
            chars += string("line %d of col" % k, x, 112 + 12 * k, 10)
    blocks = run(chars)
    assert sorted(b.lines[0].text for b in blocks).count("HEAD") == 3


def test_dominant_size_bold_and_block_fields():
    chars = string("Heading words", 50, 100, 10, font="ABCDEF+Arial-BoldMT")
    blocks = run(chars)
    b = blocks[0]
    assert b.bold and b.lines[0].bold
    assert b.size == pytest.approx(10.0)
    assert b.first_line_height == pytest.approx(10.0, abs=0.01)
    assert b.direction == 0.0
    assert b.bbox == (b.x0, b.y0, b.x1, b.y1)
    assert b.lines[0].bbox[0] == pytest.approx(50.0)


def test_far_apart_same_row_segments_are_one_block_with_union_box():
    chars = string("A Title For The Poster Here", 70, 60, 30, adv=15)
    chars += string("Oliver Hahn & Steffen Lemke", 70, 100, 10)
    chars += string("ZBW - Leibniz Information Centre", 400, 100, 10)
    blocks = run(chars, w=1000, h=300)
    assert len(blocks) == 2
    assert blocks[1].x0 == pytest.approx(70.0)
    assert blocks[1].x1 == pytest.approx(400 + 32 * 5.0)
    assert len(blocks[1].lines) == 2


def test_first_line_alone_when_next_starts_right_of_its_end():
    chars = string("Title words", 50, 60, 10) + string("other region", 300, 70, 10) \
        + string("more", 300, 82, 10)
    blocks = run(chars)
    assert texts(blocks) == ["Title words", "other region more"]


# ---------------------------------------------------------------------------
# Block order: O1 to O4, E10
# ---------------------------------------------------------------------------
def col_blocks(spec):
    """spec: list of (label, x, y0) paragraphs, written in the given order."""
    chars = []
    for label, x, y0 in spec:
        chars += para(label, x, y0)
    return chars


def labels(blocks):
    return [b.lines[0].text.split()[0] for b in blocks]


def test_three_columns_read_column_major_even_when_written_row_major():          # O1
    spec = [("A1", 20, 100), ("B1", 220, 100), ("C1", 420, 100),
            ("A2", 20, 160), ("B2", 220, 160), ("C2", 420, 160)]
    assert labels(run(col_blocks(spec))) == ["A1", "A2", "B1", "B2", "C1", "C2"]


def test_title_above_columns_is_first_and_standalone():                          # O2
    spec = [("T", 20, 40)]
    spec += [("A1", 20, 100), ("B1", 220, 100), ("C1", 420, 100),
             ("A2", 20, 160), ("B2", 220, 160), ("C2", 420, 160)]
    chars = para("T", 20, 40, n=1, width_chars=60) + col_blocks(spec[1:])
    assert labels(run(chars)) == ["T", "A1", "A2", "B1", "B2", "C1", "C2"]


def test_full_width_strip_splits_the_page_into_two_bands():                      # O3
    spec = [("A1", 20, 100), ("B1", 220, 100), ("C1", 420, 100),
            ("A2", 20, 200), ("B2", 220, 200), ("C2", 420, 200)]
    chars = col_blocks(spec) + para("S", 20, 150, n=1, width_chars=110)
    assert labels(run(chars)) == ["A1", "B1", "C1", "S", "A2", "B2", "C2"]
    # band-1 columns column-major needs two blocks per column above the strip
    spec = [("A1", 20, 80), ("A2", 20, 110), ("B1", 220, 80), ("B2", 220, 110),
            ("C1", 420, 80), ("C2", 420, 110),
            ("A3", 20, 210), ("B3", 220, 210), ("C3", 420, 210)]
    chars = col_blocks(spec) + para("S", 20, 160, n=1, width_chars=110)
    got = labels(run(chars))
    assert got == ["A1", "A2", "B1", "B2", "C1", "C2", "S", "A3", "B3", "C3"]


def test_spanning_caption_is_a_barrier_to_hopping():                             # O4
    chars = para("A1", 20, 100) + para("B1", 220, 100) \
        + para("CAP", 20, 130, n=1, width_chars=70) \
        + para("A2", 20, 160) + para("B2", 220, 160)
    got = labels(run(chars))
    assert got.index("CAP") < got.index("A2") and got.index("CAP") < got.index("B2")
    assert got.index("A1") < got.index("CAP")


def test_name_then_email_pairs_keep_their_order():                               # E10
    chars = []
    for k in range(3):
        x = 20 + 190 * k
        chars += string(f"Author{k} Name", x, 100, 12)
        chars += string(f"a{k}@example.org", x, 118, 10)      # different size: own block
    got = lines_of(run(chars))
    assert got == ["Author0 Name", "a0@example.org", "Author1 Name", "a1@example.org",
                   "Author2 Name", "a2@example.org"]


# ---------------------------------------------------------------------------
# E12: accents
# ---------------------------------------------------------------------------
def test_grave_accent_before_base_composes():
    chars = string("caf", 100, 300, 20, adv=10)
    chars.append(mk("`", 130, 292, 20, adv=10))               # over the e, drawn first
    chars.append(mk("e", 130, 300, 20, adv=10))
    assert one_line(chars) == "caf\u00e8"


def test_tilde_after_base_and_no_precomposed_form():
    chars = [mk("n", 100, 300, 20, 10), mk("~", 102, 292, 20, 10)]
    assert one_line(chars) == "\u00f1"
    chars = [mk("q", 100, 300, 20, 10), mk("\u00b4", 102, 292, 20, 10)]
    assert one_line(chars) == "q\u0301"                      # mark kept, not dropped


def test_second_accent_is_ignored():
    chars = [mk("\u00b4", 102, 292, 20, 10), mk("\u00a8", 103, 292, 20, 10),
             mk("e", 100, 300, 20, 10)]
    assert one_line(chars) == "\u00e9"


def test_degree_sign_is_not_an_accent_and_caret_needs_overlap():
    chars = string("40", 100, 300, 20) + [mk("\u00b0", 124, 300, 20, 6)] \
        + [mk("N", 140, 300, 20, 12)]
    assert one_line(chars) == "40 \u00b0 N"
    # caret raised and overlapping the 2: one word
    chars = [mk("x", 100, 300, 20, 10), mk("^", 109, 292, 20, 8), mk("2", 112, 300, 20, 10)]
    assert one_line(chars) == "x^2"
    # caret set apart by a normal word gap is an ordinary glyph
    chars = [mk("x", 100, 300, 20, 10), mk("^", 125, 300, 20, 8), mk("2", 140, 300, 20, 10)]
    assert one_line(chars) == "x ^ 2"


def test_glyph_wrapped_to_another_line_is_not_glued_to_an_accent():
    chars = string("hello", 100, 300, 20) + [mk("\u00b4", 300, 292, 20, 10)] \
        + string("e", 100, 340, 20)
    lines = lines_of(run(chars))
    assert "e" in lines and not any("\u00e9" in ln for ln in lines)


# ---------------------------------------------------------------------------
# E13: overprints
# ---------------------------------------------------------------------------
def test_overprinted_title_is_collapsed():
    one = string("Big Title", 100, 100, 40)
    two = [dict(c, x0=c["x0"] + 0.6, x1=c["x1"] + 0.6, top=c["top"] + 0.6,
                bottom=c["bottom"] + 0.6,
                matrix=(c["matrix"][0], c["matrix"][1], c["matrix"][2], c["matrix"][3],
                        c["matrix"][4] + 0.6, c["matrix"][5] - 0.6)) for c in one]
    assert one_line(one + two) == "Big Title"


def test_double_letters_and_distinct_chars_are_not_overprints():
    assert one_line(string("hello all", 50, 100, 20)) == "hello all"
    base = mk("o", 100, 100, 20, 10)
    bar = mk("-", 100, 100, 20, 10)
    assert one_line([base, bar]) in ("o -", "o-", "-o")  # distinct chars survive
    assert len(lines_of(run([base, bar]))[0].replace(" ", "")) == 2


# ---------------------------------------------------------------------------
# Section 10: robustness
# ---------------------------------------------------------------------------
def test_non_zero_media_box_origin_gives_the_same_blocks():
    spec = [("A1", 20, 100), ("B1", 220, 100), ("A2", 20, 160), ("B2", 220, 160)]
    org = (-12.0, 30.0)
    plain = []
    shifted = []
    for label, x, y0 in spec:
        for k in range(2):
            pos = 0.0
            for t in f"{label} l{k} zzzz":
                plain.append(mk(t, x + pos, y0 + 12 * k, 10))
                shifted.append(mk(t, x + pos, y0 + 12 * k, 10, org=org))
                pos += 5.0
    a = ls.ordered_blocks(page_of(plain))
    b = ls.ordered_blocks(page_of(shifted, org=org))
    assert texts(a) == texts(b)
    assert [round(v, 6) for blk in a for v in blk.bbox] == \
        [round(v, 6) for blk in b for v in blk.bbox]


def test_text_inside_a_shifted_page_is_not_dropped_as_hidden():
    org = (-12.0, 30.0)
    chars = [mk(t, 2.0 + 5 * i, 12.0, 10, org=org) for i, t in enumerate("abc")]
    blocks = ls.ordered_blocks(page_of(chars, org=org))
    assert texts(blocks) == ["abc"]


def test_hidden_text_outside_the_page_is_dropped_and_splits_words():
    chars = string("ab", 50, 100, 10) + [mk("X", 5000, 100, 10)] + string("cd", 60, 100, 10)
    assert one_line(chars) == "ab cd"
    chars = [mk("a", 50, -40, 10)] + string("ok", 50, 100, 10)
    assert lines_of(run(chars)) == ["ok"]


@pytest.mark.parametrize("field,value", [
    ("x0", float("nan")), ("x1", float("inf")), ("top", None), ("bottom", float("nan")),
    ("size", float("nan")), ("matrix", (1, 0, 0, 1, float("nan"), 5)),
    ("matrix", (1, 0, 0, 1, None, 5)), ("matrix", (1, 0, 0)),
])
def test_bad_glyph_is_skipped_and_acts_as_a_boundary(field, value):
    chars = string("ab", 50, 100, 10)
    bad = mk("X", 60, 100, 10)
    bad[field] = value
    chars.append(bad)
    chars += string("cd", 60, 100, 10)
    out = lines_of(run(chars))
    assert out == ["ab cd"]


def test_missing_size_or_box_is_synthesized():
    g = mk("a", 50, 100, 10)
    no_size = dict(g)
    del no_size["size"]
    assert lines_of(run([no_size])) == ["a"]
    no_box = {k: v for k, v in g.items() if k not in ("x0", "x1", "top", "bottom")}
    assert lines_of(run([no_box])) == ["a"]
    no_matrix = {k: v for k, v in g.items() if k != "matrix"}
    assert lines_of(run([no_matrix])) == ["a"]
    zero = dict(g, size=0.0)
    assert lines_of(run([zero])) == ["a"]


def test_empty_and_degenerate_pages():
    assert run([]) == []
    assert run([mk(" ", 50, 100, 10)]) == []


def test_deep_stream_does_not_recurse():
    # thousands of blocks stacked in one column: iterative everywhere
    chars = []
    for k in range(3000):
        chars += string("ab", 50, 20 + 30 * k, 10)
    blocks = run(chars, w=600, h=100000)
    assert len(blocks) == 3000


def test_thirty_thousand_glyphs_run_in_linear_time():
    def build(n_lines):
        chars = []
        for k in range(n_lines):
            chars += string(("lorem ipsum dolor sit amet " * 3)[:50], 40 + 700 * (k % 3),
                            20 + 12 * (k // 3), 10)
        return chars

    chars = build(600)
    assert len(chars) == 30000
    t0 = time.perf_counter()
    blocks = run(chars, w=2200, h=3000)
    dt = time.perf_counter() - t0
    assert blocks
    assert dt < 4.0, dt            # target is about 1 s; allow for slow test hosts
    small = build(60)
    t0 = time.perf_counter()
    run(small, w=2200, h=3000)
    d_small = time.perf_counter() - t0
    assert dt < 40 * max(d_small, 0.005)   # 10x the glyphs, far from quadratic


def test_deterministic_output():
    spec = [("A1", 20, 100), ("B1", 220, 100), ("A2", 20, 160), ("B2", 220, 160)]
    a = texts(run(col_blocks(spec)))
    b = texts(run(col_blocks(spec)))
    assert a == b


# ---------------------------------------------------------------------------
# Interleaved content streams
# ---------------------------------------------------------------------------
def column_text(col, k):
    return f"col{col} line{k:02d} " + "lorem ipsum dolor "[: 18]


def interleaved(ncols, nlines=12, size=10.0, step=12.0, row_major=True, gap=40.0):
    width = 36 * size * 0.5
    chars = []
    order = ([(c, k) for k in range(nlines) for c in range(ncols)] if row_major
             else [(c, k) for c in range(ncols) for k in range(nlines)])
    for c, k in order:
        chars += string(column_text(c, k), 30 + c * (width + gap), 100 + k * step, size)
    return chars, 60 + ncols * (width + gap)


@pytest.mark.parametrize("ncols", [2, 3, 4, 5, 6])
def test_interleaved_streams_come_out_column_major(ncols):
    chars, w = interleaved(ncols)
    info = {}
    blocks = ls.ordered_blocks(page_of(chars, w=w, h=400), info=info)
    assert info["interleaved_regions"] == 1
    assert len(blocks) == ncols
    for c, b in enumerate(blocks):
        assert len(b.lines) == 12
        assert [ln.text.split()[0] for ln in b.lines] == [f"col{c}"] * 12
        assert [ln.text.split()[1] for ln in b.lines] == [f"line{k:02d}" for k in range(12)]


@pytest.mark.parametrize("ncols", [2, 3, 4, 5, 6])
def test_column_major_streams_are_unchanged_by_the_repair(ncols):
    chars, w = interleaved(ncols, row_major=False)
    info = {}
    with_fix = ls.ordered_blocks(page_of(chars, w=w, h=400), info=info)
    without = ls.ordered_blocks(page_of(chars, w=w, h=400), repair_interleave=False)
    assert info["interleaved_regions"] == 0
    assert texts(with_fix) == texts(without)
    assert len(with_fix) == ncols


def test_row_by_row_table_of_short_cells_is_not_repaired():
    chars = []
    for r in range(8):
        for c in range(4):
            chars += string(f"c{r}{c}", 30 + 90 * c, 100 + 12 * r, 10)
    info = {}
    ls.ordered_blocks(page_of(chars, w=500, h=300), info=info)
    assert info["interleaved_regions"] == 0


def test_interleaved_repair_needs_three_lines_per_lane():
    chars, w = interleaved(3, nlines=2)
    info = {}
    ls.ordered_blocks(page_of(chars, w=w, h=400), info=info)
    assert info["interleaved_regions"] == 0


# ---------------------------------------------------------------------------
# Skewed and rotated text
# ---------------------------------------------------------------------------
def tilted_paragraph(theta, nlines=10, x=100.0, y=100.0, size=10.0, step=12.0):
    c, s = _unit(theta)
    chars = []
    for k in range(nlines):
        ox = x - k * step * s
        oy = y + k * step * c
        chars += string(f"tilted line {k:02d} of the paragraph", ox, oy, size, theta=theta)
    return chars


@pytest.mark.parametrize("theta", [2.0, 12.0, 30.0, 45.0])
def test_skewed_paragraph_is_one_block(theta):
    blocks = run(tilted_paragraph(theta), w=800, h=800)
    assert len(blocks) == 1
    assert len(blocks[0].lines) == 10
    assert blocks[0].lines[3].text == "tilted line 03 of the paragraph"
    assert blocks[0].direction == pytest.approx(theta % 360.0, abs=0.01)


def test_rotated_label_is_its_own_block():
    chars = para("A1", 100, 100, n=3)
    chars += string("Axis label", 60, 300, 10, theta=270.0)
    chars += string("Down label", 80, 100, 10, theta=90.0)
    blocks = run(chars)
    kinds = sorted(b.direction for b in blocks)
    assert kinds == [0.0, 90.0, 270.0]
    assert any(" ".join(ln.text for ln in b.lines) == "Axis label" for b in blocks)


def test_upside_down_text_keeps_its_words():
    assert one_line(string("hello world", 300, 100, 10, theta=180.0)) == "hello world"


def test_words_of_different_directions_never_share_a_line():
    chars = string("ab", 100, 100, 10) + string("cd", 112, 100, 10, theta=90.0)
    assert len(lines_of(run(chars))) == 2


def test_tracked_baseline_with_rise_is_honored():
    # Ts text rise moves the glyph box but not the matrix origin
    chars = string("see", 100, 300, 10)
    raised = mk("1", 115, 300, 6, 3, rise_box=4.0)
    chars.append(raised)
    chars += string(" more", 118, 300, 10)
    assert one_line(chars) == "see 1 more"


# ---------------------------------------------------------------------------
# Targeted rule tests (each guards one threshold or branch)
# ---------------------------------------------------------------------------
def test_same_row_baseline_limit_is_half_the_size():
    first = string("word", 150, 500, 10, adv=12.5)           # ends at x 200
    near = string("zz", 203, 505, 10)                         # 5 below: still the row
    assert len(lines_of(run(first + near))) == 1
    far = string("zz", 203, 506.5, 10)                        # 6.5 below: next row
    assert len(lines_of(run(first + far))) == 2


def test_next_word_entirely_below_the_baseline_starts_a_line():
    first = string("word", 150, 500, 10, adv=12.5)
    low = mk("z", 203, 504, 10)
    low["top"], low["bottom"] = 503.0, 505.0                  # box wholly below the baseline
    assert len(lines_of(run(first + [low]))) == 2
    ok = mk("z", 203, 504, 10)                                # ordinary box: same row
    assert len(lines_of(run(first + [ok]))) == 1


def test_overlapping_larger_word_with_other_baseline_is_a_new_line():
    first = string("wordword", 150, 500, 10)                  # 150 to 190
    big = string("BIG", 170, 507, 20)                         # starts inside, 7 lower
    assert len(lines_of(run(first + big))) == 2


def test_title_rule_needs_a_clear_jump_to_the_right():
    # next line starts only 2 pt (0.2 L) right of the end of the first line
    chars = string("first line", 50, 100, 10) + string("second", 102, 112, 10)
    assert len(run(chars)) == 1
    chars = string("first line", 50, 100, 10) + string("second", 110, 112, 10)
    assert len(run(chars)) == 2


def test_accent_reach_and_across_limits():
    # a spacing accent half an em left of its base and raised still composes
    chars = [mk("\u00b4", 100, 292, 20, 5), mk("e", 115, 300, 20, 10)]
    assert one_line(chars) == "\u00e9"
    # an accent three ems away from any letter stays a separate glyph
    chars = [mk("e", 100, 300, 20, 10), mk("\u00b4", 200, 292, 20, 5)]
    assert not any("\u00e9" in ln for ln in lines_of(run(chars)))


def test_dotless_i_takes_an_accent():
    chars = [mk("\u0131", 100, 300, 20, 6), mk("\u00b4", 100, 292, 20, 6)]
    assert one_line(chars) == "\u00ed"


def test_dedupe_requires_same_font_and_same_character():
    a = mk("A", 100, 300, 20, 12, font="Helvetica")
    b = mk("A", 100, 300, 20, 12, font="Times-Roman")
    assert one_line([a, b]) == "AA"
    near = mk("A", 100.5, 300.5, 20, 12, font="Helvetica")
    assert one_line([a, near]) == "A"
    far = mk("A", 104, 300, 20, 12, font="Helvetica")           # a full 0.33 em away
    assert one_line([a, far]) == "AA"


def test_accent_far_from_its_base_is_not_glued():
    chars = [mk("e", 100, 300, 20, 10), mk("´", 140, 292, 20, 5)]   # 1.5 em after the base
    assert not any("é" in ln for ln in lines_of(run(chars)))


def test_same_size_raised_word_is_not_a_superscript():
    chars = string("ab", 100, 300, 10) + string("cd", 110, 296, 10)
    assert one_line(chars) == "abcd"


def test_script_flag_needs_a_smaller_size():
    # a tall word on the baseline raises the dominant top; a same-size word raised
    # by 2 pt still fits under it but is not smaller than the line size
    chars = string("aaaaaaaa ", 100, 300, 10) + string("BIG", 145, 300, 14, adv=7)
    chars += string("cc", 166, 298, 10)
    assert one_line(chars) == "aaaaaaaa BIGcc"


def test_subscript_that_qualifies_is_glued():
    chars = string("CO", 100, 300, 20) + [mk("2", 120, 303, 12, 6)]
    assert one_line(chars) == "CO2"
    chars += string(" x", 126, 300, 20)
    assert one_line(chars) == "CO2 x"


def test_nearly_parallel_words_share_a_line_and_right_angles_snap():
    chars = string("tilted", 100, 100, 10, theta=12.0)
    c, s = _unit(12.0)
    chars += string("words", 100 + 33.0 * c, 100 + 33.0 * s, 10, theta=12.4)
    blocks = run(chars)
    assert len(lines_of(blocks)) == 1 and blocks[0].lines[0].text == "tilted words"
    # a direction 0.5 degrees off a right angle is exactly that right angle
    blocks = run(string("level", 100, 100, 10, theta=0.5))
    assert blocks[0].direction == 0.0


def test_glyph_of_another_direction_never_joins_a_word_or_a_block():
    chars = string("ab", 50, 100, 10) + [mk("c", 60, 100, 10, theta=90.0)]
    out = sorted(lines_of(run(chars)))
    assert out == ["ab", "c"]
    chars = string("abc def", 50, 100, 10) + string("vertical", 50, 112, 10, theta=90.0)
    blocks = run(chars)
    assert sorted(b.direction for b in blocks) == [0.0, 90.0]


def test_line_size_and_baseline_come_from_the_bulk_of_the_text():
    # every other line starts with a raised small marker; steps stay 12 on the
    # dominant baseline, so the paragraph is one block
    chars = []
    for k in range(4):
        y = 100 + 12 * k
        if k % 2 == 0:
            chars.append(mk("1", 50, y - 4, 6, 3))
            chars += string("text of the line", 54, y, 10)
        else:
            chars += string("text of the line", 54, y, 10)
    blocks = run(chars)
    assert len(blocks) == 1 and len(blocks[0].lines) == 4
    assert all(ln.size == pytest.approx(10.0) for ln in blocks[0].lines)


def test_line_size_ties_go_to_the_larger_text():
    chars = string("ab", 50, 100, 10) + string("cd", 70, 100, 12)
    assert run(chars)[0].lines[0].size == pytest.approx(12.0)


def test_words_are_exposed_with_boxes():
    ln = run(string("two words", 50, 100, 10))[0].lines[0]
    assert [w.text for w in ln.words] == ["two", "words"]
    assert ln.words[0].x0 == pytest.approx(50.0) and ln.words[1].x0 > ln.words[0].x1
    assert ln.words[0].size == pytest.approx(10.0) and not ln.words[0].bold


def test_unreliable_matrix_frame_falls_back_to_the_glyph_boxes():
    chars = [dict(c, matrix=(1, 0, 0, 1, c["matrix"][4], 5000.0))
             for c in string("readable text", 50, 100, 10)]
    assert lines_of(run(chars)) == ["readable text"]


def test_glyphs_near_the_far_edges_of_a_shifted_page_are_kept():
    org = (-12.0, 30.0)
    chars = [mk(t, PAGE_W - 20 + 5 * i, PAGE_H - 6.0, 10, org=org) for i, t in enumerate("end")]
    blocks = ls.ordered_blocks(page_of(chars, org=org))
    assert texts(blocks) == ["end"]


def test_wide_lines_cut_interleaved_regions():
    chars = []
    width = 36 * 5.0
    for k in range(6):
        for c in range(2):
            chars += string(column_text(c, k), 30 + c * (width + 40), 100 + k * 12, 10)
    chars += string("W" * 90, 30, 100 + 6 * 12, 10)           # full width heading line
    for k in range(7, 13):
        for c in range(2):
            chars += string(column_text(c, k), 30 + c * (width + 40), 100 + k * 12, 10)
    info = {}
    blocks = ls.ordered_blocks(page_of(chars, w=500, h=400), info=info)
    assert info["interleaved_regions"] == 2
    assert len(blocks) == 5
    assert [len(b.lines) for b in blocks] == [6, 6, 1, 6, 6]


def test_columns_closer_than_a_font_size_are_one_lane():
    # staggered rows so that the two columns never share a line; the gutter is 4 pt
    chars = []
    for k in range(12):
        for c in range(2):
            chars += string(column_text(c, k), 30 + c * (30 * 5.0 + 4), 100 + k * 12 + 6 * c, 10)
    info = {}
    ls.ordered_blocks(page_of(chars, w=500, h=400), info=info)
    assert info["lines"] == 24
    assert info["interleaved_regions"] == 0
    # the same stagger with a proper gutter is repaired
    chars = []
    for k in range(12):
        for c in range(2):
            chars += string(column_text(c, k), 30 + c * (30 * 5.0 + 40), 100 + k * 12 + 6 * c, 10)
    info = {}
    ls.ordered_blocks(page_of(chars, w=500, h=400), info=info)
    assert info["interleaved_regions"] == 1


def test_interleaved_repair_needs_normal_leading_inside_each_lane():
    chars = []
    width = 36 * 5.0
    for k in range(6):
        for c in range(2):
            chars += string(column_text(c, k), 30 + c * (width + 40), 100 + k * 40, 10)
    info = {}
    ls.ordered_blocks(page_of(chars, w=500, h=400), info=info)
    assert info["interleaved_regions"] == 0


# ---------------------------------------------------------------------------
# Block order details
# ---------------------------------------------------------------------------
def test_top_most_block_is_first_even_with_a_block_just_left_of_it():
    chars = para("R1", 220, 100.0) + para("L1", 20, 100.3) \
        + para("L2", 20, 160) + para("R2", 220, 160)
    got = labels(run(chars))
    assert got[0] == "R1"
    assert got.index("L1") < got.index("L2") and got.index("R1") < got.index("R2")


def test_blocks_with_overlapping_x_ranges_are_not_hopped():
    chars = string("P text of the block", 100, 100, 10) + string("Q txt", 60, 108, 14)
    assert labels(run(chars)) == ["P", "Q"]


def test_equal_tops_keep_stream_order_when_neither_block_is_left_or_right():
    # tops differ by 0.2 pt: equal; overlapping x ranges: stream order decides
    chars = para("X", 20, 100.2) + para("Y", 60, 100.0) + para("Z", 20, 200)
    assert labels(run(chars)) == ["X", "Y", "Z"]
    chars = para("X", 20, 100.0) + para("Y", 60, 100.0) + para("Z", 20, 200)
    assert labels(run(chars)) == ["X", "Y", "Z"]


# ---------------------------------------------------------------------------
# Rotated text: pdfminer reports the box height as the size, which for text
# reading top to bottom is the glyph advance and differs for every letter
# ---------------------------------------------------------------------------
def _rotated_word(text, x, y_start, size, advs, theta=270.0):
    out = []
    y = y_start
    for ch, a in zip(text, advs):
        g = mk(ch, x, y, size, adv=a, theta=theta)
        g["size"] = g["bottom"] - g["top"]
        out.append(g)
        y += -a if theta == 270.0 else a
    return out


@pytest.mark.parametrize("theta", [90.0, 270.0])
def test_rotated_heading_keeps_one_word_per_word_whatever_the_glyph_widths(theta):
    advs = [15, 20, 13, 15, 20, 20, 20, 17, 13, 11, 20, 20]
    start = 700.0 if theta == 270.0 else 100.0
    chars = _rotated_word("Introduction", 50, start, 40, advs, theta)
    chars += _rotated_word("Methodology", 100, start, 40, advs[:11], theta)
    blocks = run(chars)
    words = [[w.text for w in ln.words] for b in blocks for ln in b.lines]
    assert ["Introduction"] in words and ["Methodology"] in words
    for b in blocks:
        assert abs(b.size - 40.0) < 0.5


def test_rotated_text_size_is_the_box_width_not_the_advance():
    chars = _rotated_word("Hi", 50, 300, 24, [9, 12], 90.0)
    blocks = run(chars)
    assert abs(blocks[0].size - 24.0) < 0.5


# ---------------------------------------------------------------------------
# Right to left words come in visual order from the content stream
# ---------------------------------------------------------------------------
ALEF, BET, GIMEL, DALET = "א", "ב", "ג", "ד"


def test_visual_order_hebrew_line_is_returned_in_logical_order():
    # printed left to right as: BET ALEF, DALET GIMEL (visual); logical text reads
    # from the right: GIMEL DALET, then ALEF BET
    chars = string(BET + ALEF + " " + DALET + GIMEL, 100, 100, 10)
    blocks = run(chars)
    assert lines_of(blocks) == [GIMEL + DALET + " " + ALEF + BET]
    assert [w.text for w in blocks[0].lines[0].words] == [ALEF + BET, GIMEL + DALET]


def test_latin_words_beside_hebrew_keep_their_place_and_order():
    chars = string("abc " + BET + ALEF + " " + DALET + GIMEL + " def", 100, 100, 10)
    assert lines_of(run(chars)) == ["abc " + GIMEL + DALET + " " + ALEF + BET + " def"]


def test_punctuation_digits_and_brackets_in_hebrew_words():
    chars = string("," + BET + ALEF + " 12 (" + DALET + GIMEL + ")", 100, 100, 10)
    # visual words: ",BA" "12" "(DG)" -> logical: "(GD)" "12" "AB,"
    assert lines_of(run(chars)) == ["(" + GIMEL + DALET + ") 12 " + ALEF + BET + ","]


def test_plain_latin_line_is_unchanged_by_the_right_to_left_rule():
    assert one_line(string("(abc) 12, def", 100, 100, 10)) == "(abc) 12, def"
