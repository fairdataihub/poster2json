"""Recursive XY-cut reading order recovery for pdfplumber chars.

Ports xpdf's TextOutputDev::splitChars / split / findGaps algorithm
(xpdf-4.06, TextOutputDev.cc lines 1846-4363) to Python. Constants are
from the same source, expressed in fractions of average font size.
"""

from __future__ import annotations

import bisect
import re
import statistics
from dataclasses import dataclass, field
from typing import List, Tuple

MIN_GAP_AREA = 3.0
SPLIT_GAP_SLACK = 0.2
MIN_CHUNK_WIDTH = 2.0
MIN_GAP_SIZE = 0.2
BASELINE_RANGE = 0.5
DESCENT_ADJUST = 0.35
TOP_BAND = 0.22
TOP_BAND_DOMINANCE = 0.85
SUPERSCRIPT_SIZE_RATIO = 0.85
SUPERSCRIPT_RISE = 0.6
SUPERSCRIPT_MIN_DIGITS = 2

# Glyphs an affiliation-marker row may contain: digits, the separators posters
# put between them, and the role/footnote symbols that ride alongside.
_MARKER_ROW_RE = re.compile(r"[\d\s,;.+*†‡§¶#\-–—]+")


@dataclass
class Block:
    kind: str  # "vsplit" | "hsplit" | "leaf"
    bbox: Tuple[float, float, float, float]
    chars: List[dict] = field(default_factory=list)
    children: List[Block] = field(default_factory=list)


def _bbox_and_stats(chars):
    xs0 = [c["x0"] for c in chars]
    xs1 = [c["x1"] for c in chars]
    ys0 = [c["top"] for c in chars]
    ys1 = [c["bottom"] for c in chars]
    sizes = [c.get("size", c["bottom"] - c["top"]) for c in chars]
    avg_fs = statistics.fmean(sizes) if sizes else 1.0
    min_fs = min(sizes) if sizes else 1.0
    return (min(xs0), min(ys0), max(xs1), max(ys1)), max(avg_fs, 0.1), max(min_fs, 0.1)


def _gaps_1d(chars, axis):
    if axis == "x":
        intervals = sorted((c["x0"], c["x1"]) for c in chars)
    else:
        intervals = sorted((c["top"], c["bottom"]) for c in chars)
    gaps = []
    cur_end = intervals[0][1]
    for a, b in intervals[1:]:
        if a > cur_end + 0.01:
            gaps.append(((cur_end + a) / 2.0, a - cur_end))
        cur_end = max(cur_end, b)
    return gaps


def _chars_in(chars, x0, y0, x1, y1):
    out = []
    for c in chars:
        cx = (c["x0"] + c["x1"]) / 2
        cy = c["bottom"] - DESCENT_ADJUST * (c["bottom"] - c["top"])
        if x0 - 0.5 <= cx < x1 + 0.5 and y0 - 0.5 <= cy < y1 + 0.5:
            out.append(c)
    return out


def _partition(chars, bounds, axis):
    """Split `chars` into one list per [bounds[i], bounds[i+1]) interval in a
    single pass, keyed by the same center coordinate `_chars_in` uses.

    Equivalent to calling `_chars_in` once per interval, because cut positions
    always land inside whitespace gaps and no char center is within the old
    0.5pt boundary slack of a cut, so assignment is unambiguous. Runs in
    O(n log k) instead of O(n*k), and assigns each char to exactly one child
    (the old per-interval slack could place a char into two children, which is
    what made the recursion blow up on dense pages)."""
    n_intervals = len(bounds) - 1
    buckets = [[] for _ in range(n_intervals)]
    if n_intervals == 1:
        buckets[0].extend(chars)
        return buckets
    for c in chars:
        if axis == "x":
            coord = (c["x0"] + c["x1"]) / 2.0
        else:
            coord = c["bottom"] - DESCENT_ADJUST * (c["bottom"] - c["top"])
        i = bisect.bisect_right(bounds, coord) - 1
        if i < 0:
            i = 0
        elif i >= n_intervals:
            i = n_intervals - 1
        buckets[i].append(c)
    return buckets


def _min_chunk_width(chars, gaps, max_g, avg_fs, bbox):
    x0, _, x1, _ = bbox
    slack = SPLIT_GAP_SLACK * avg_fs
    cuts = sorted(g[0] for g in gaps if g[1] > max_g - slack)
    bounds = [x0] + cuts + [x1]
    if len(bounds) < 2:
        return 1e9
    return min(b - a for a, b in zip(bounds[:-1], bounds[1:]))


def split_block(chars, depth=0) -> Block:
    if not chars:
        return Block("leaf", (0, 0, 0, 0), [], [])

    if len(chars) <= 2:
        bbox, _, _ = _bbox_and_stats(chars)
        return Block("leaf", bbox, sorted(chars, key=lambda c: (c["bottom"], c["x0"])), [])

    bbox, avg_fs, min_fs = _bbox_and_stats(chars)
    x0, y0, x1, y1 = bbox
    block_h = max(y1 - y0, 0.1)
    block_w = max(x1 - x0, 0.1)

    if depth > 50:
        return Block("leaf", bbox, sorted(chars, key=lambda c: (c["bottom"], c["x0"])), [])

    vgaps = _gaps_1d(chars, "x")
    hgaps = _gaps_1d(chars, "y")
    max_v = max((g[1] for g in vgaps), default=0.0)
    max_h = max((g[1] for g in hgaps), default=0.0)

    gap_threshold_v = MIN_GAP_AREA * (avg_fs ** 2) / block_h
    min_gap = MIN_GAP_SIZE * min_fs
    min_chunk = MIN_CHUNK_WIDTH * avg_fs

    is_single_line = block_h < 1.5 * avg_fs

    do_vsplit = (
        not is_single_line
        and max_v > min_gap
        and max_v > gap_threshold_v
        and _min_chunk_width(chars, vgaps, max_v, avg_fs, bbox) > min_chunk
    )

    gap_threshold_h = MIN_GAP_AREA * (avg_fs ** 2) / block_w
    do_hsplit = (not do_vsplit) and max_h > min_gap and max_h > gap_threshold_h

    if do_vsplit:
        slack = SPLIT_GAP_SLACK * avg_fs
        cuts = sorted(g[0] for g in vgaps if g[1] > max_v - slack)
        bounds = [x0] + cuts + [x1]
        children = []
        for sub in _partition(chars, bounds, "x"):
            if sub:
                children.append(split_block(sub, depth + 1))
        if len(children) <= 1:
            return Block("leaf", bbox, sorted(chars, key=lambda c: (c["bottom"], c["x0"])), [])
        return Block("vsplit", bbox, [], children)

    if do_hsplit:
        slack = SPLIT_GAP_SLACK * avg_fs
        cuts = sorted(g[0] for g in hgaps if g[1] > max_h - slack)
        bounds = [y0] + cuts + [y1]
        children = []
        for sub in _partition(chars, bounds, "y"):
            if sub:
                children.append(split_block(sub, depth + 1))
        if len(children) <= 1:
            return Block("leaf", bbox, sorted(chars, key=lambda c: (c["bottom"], c["x0"])), [])
        return Block("hsplit", bbox, [], children)

    return Block("leaf", bbox, sorted(chars, key=lambda c: (c["bottom"], c["x0"])), [])


def _char_fs(c):
    return c.get("size", c["bottom"] - c["top"])


def _line_fs(line):
    return max(_char_fs(c) for c in line)


def _line_base(line):
    return statistics.median([c["bottom"] for c in line])


def _is_marker_row(line):
    """True if a line is made only of affiliation-marker glyphs (digits and
    their separators). Geometry alone cannot identify a superscript row: plenty
    of ordinary text is smaller than, and sits inside, a neighbouring line — a
    single letter from a rotated axis label, a byline under a title, a logo
    beside a heading. What makes a row markers is that it carries digits and
    nothing else.

    A lone digit does not qualify. Rejoining a row rewrites line extents and so
    shifts the median line height the block grouper keys on, re-blocking the
    page; that is worth risking only on unambiguous evidence, and one stray
    digit (a figure number, a data label, an axis tick) is not it. A genuine
    stranded byline row annotates several authors and carries a marker for
    each."""
    txt = "".join(c["text"] for c in line)
    return (bool(_MARKER_ROW_RE.fullmatch(txt))
            and sum(ch.isdigit() for ch in txt) >= SUPERSCRIPT_MIN_DIGITS)


def _is_superscript_row(small, large):
    """True if line ``small`` is a row of affiliation markers belonging to
    ``large``.

    Four conditions, none sufficient alone: the row is marker glyphs only,
    every glyph is materially smaller than the text it annotates, the raised
    baseline stays within an em of that text's, and the row sits horizontally
    inside the other line's run. The last separates markers interleaved with
    the names they follow from a smaller element set off to the side, such as a
    logo beside a title, which shares a baseline band but not the horizontal
    run.
    """
    if not _is_marker_row(small) or _is_marker_row(large):
        return False
    fs_l = _line_fs(large)
    if _line_fs(small) >= SUPERSCRIPT_SIZE_RATIO * fs_l:
        return False
    if abs(_line_base(small) - _line_base(large)) > SUPERSCRIPT_RISE * fs_l:
        return False
    sx0 = min(c["x0"] for c in small)
    sx1 = max(c["x1"] for c in small)
    lx0 = min(c["x0"] for c in large)
    lx1 = max(c["x1"] for c in large)
    return sx0 >= lx0 - fs_l and sx1 <= lx1 + fs_l


def _merge_superscript_rows(lines):
    """Fold a stranded row of superscript markers back into its text line.

    Baseline clustering keys on ``bottom``, so a byline's affiliation markers —
    raised half an em above the names they follow — can land just outside the
    tolerance and become a line of their own ("1 1 2,3,4 5 5 5 1"). Ordering
    then interleaves them with the names and the author list is unreadable.
    Rejoining the row and re-sorting by x restores the printed order.
    """
    if len(lines) < 2:
        return lines
    out = [lines[0]]
    for ln in lines[1:]:
        prev = out[-1]
        if _is_superscript_row(ln, prev) or _is_superscript_row(prev, ln):
            out[-1] = sorted(prev + ln, key=lambda c: c["x0"])
        else:
            out.append(ln)
    return out


def _cluster_lines(chars):
    if not chars:
        return []
    sizes = [_char_fs(c) for c in chars]
    avg_fs = statistics.fmean(sizes) if sizes else 1.0
    tol = BASELINE_RANGE * max(avg_fs, 1.0)
    chars = sorted(chars, key=lambda c: (c["bottom"], c["x0"]))
    lines = []
    cur = [chars[0]]
    cur_base = chars[0]["bottom"]
    for c in chars[1:]:
        if abs(c["bottom"] - cur_base) <= tol:
            cur.append(c)
            cur_base = statistics.fmean(ch["bottom"] for ch in cur)
        else:
            lines.append(sorted(cur, key=lambda c: c["x0"]))
            cur = [c]
            cur_base = c["bottom"]
    if cur:
        lines.append(sorted(cur, key=lambda c: c["x0"]))
    return _merge_superscript_rows(lines)


def _promote_spanning_leaves(block, page_width):
    """Promote wide leaves nested in vsplits to hsplit siblings.

    Handles layouts where a spanning block (title, footnote, sidebar)
    ends up inside a column split because its y-position overlaps the
    column region. Promotes any leaf wider than 0.7 × page_width out
    of its vsplit parent and re-wraps as an hsplit ordered by y.
    """
    if block.kind == "leaf":
        return block
    block.children = [_promote_spanning_leaves(c, page_width) for c in block.children]
    if block.kind != "vsplit":
        return block

    wide_threshold = 0.7 * page_width
    wide = []
    narrow = []
    for child in block.children:
        child_w = child.bbox[2] - child.bbox[0]
        if child.kind == "leaf" and child_w > wide_threshold:
            wide.append(child)
        else:
            narrow.append(child)

    if not wide or not narrow:
        return block

    all_children = sorted(block.children, key=lambda c: c.bbox[1])
    new_children = []
    col_group = []
    for child in all_children:
        if child in wide:
            if col_group:
                if len(col_group) == 1:
                    new_children.append(col_group[0])
                else:
                    xs = [c.bbox[0] for c in col_group]
                    ys = [c.bbox[1] for c in col_group]
                    xe = [c.bbox[2] for c in col_group]
                    ye = [c.bbox[3] for c in col_group]
                    new_children.append(Block(
                        "vsplit", (min(xs), min(ys), max(xe), max(ye)), [], col_group
                    ))
                col_group = []
            new_children.append(child)
        else:
            col_group.append(child)
    if col_group:
        if len(col_group) == 1:
            new_children.append(col_group[0])
        else:
            xs = [c.bbox[0] for c in col_group]
            ys = [c.bbox[1] for c in col_group]
            xe = [c.bbox[2] for c in col_group]
            ye = [c.bbox[3] for c in col_group]
            new_children.append(Block(
                "vsplit", (min(xs), min(ys), max(xe), max(ye)), [], col_group
            ))

    if len(new_children) == 1:
        return new_children[0]
    return Block("hsplit", block.bbox, [], new_children)


def _collect_chars(block):
    if block.kind == "leaf":
        return list(block.chars)
    out = []
    for child in block.children:
        out.extend(_collect_chars(child))
    return out


def _flatten_top_band(block, page_width, page_height):
    """Re-read the top banner band as full-width baseline lines.

    Poster banners (title, byline, affiliation legend) are stacked
    full-width rows. Stray x-projection gaps in the band (a logo set off
    at the margin, a byline word space aligned with a body gutter) vsplit
    it into columns, fragmenting the byline and legend. Any vsplit that
    lies entirely within the top band, spans most of the page width, and
    has one child carrying nearly all the text (the others being debris,
    not a genuine second column) is flattened to a leaf so traverse()
    re-clusters its chars into lines across the full width. The mass
    dominance test keeps real two-column banners (title one side, an
    author/contact box the other) reading column by column.
    """
    if block.kind == "leaf":
        return block
    if (block.kind == "vsplit"
            and block.bbox[3] <= page_height * TOP_BAND
            and block.bbox[2] - block.bbox[0] > 0.7 * page_width):
        counts = [len(_collect_chars(c)) for c in block.children]
        total = sum(counts)
        if total and max(counts) / total >= TOP_BAND_DOMINANCE:
            chars = _collect_chars(block)
            return Block("leaf", block.bbox,
                         sorted(chars, key=lambda c: (c["bottom"], c["x0"])), [])
    block.children = [_flatten_top_band(c, page_width, page_height)
                      for c in block.children]
    return block


def _merge_bottom_region(block, page_height):
    """Merge bottom portions of top-level vsplits into horizontal reading order.

    In academic posters, the bottom region often has sections (Conclusion,
    References, Acknowledgements) that should be read top-to-bottom across
    the full width, not column-by-column.
    """
    if block.kind == "leaf":
        return block
    block.children = [_merge_bottom_region(c, page_height) for c in block.children]
    if block.kind != "vsplit" or len(block.children) < 2:
        return block

    if block.bbox[1] < page_height * 0.65:
        return block

    reordered = sorted(block.children, key=lambda c: c.bbox[1])
    return Block("hsplit", block.bbox, [], reordered)


def traverse(block: Block) -> list:
    if block.kind == "leaf":
        return _cluster_lines(block.chars)
    out = []
    for ch in block.children:
        out.extend(traverse(ch))
    return out


def chars_to_reading_order(raw_chars: list, page_width: float = 0,
                           page_height: float = 0) -> list:
    chars = [c for c in raw_chars if c.get("text", "").strip()]
    if not chars:
        return []
    tree = split_block(chars)
    if page_width > 0 and page_height > 0:
        tree = _flatten_top_band(tree, page_width, page_height)
    if page_width > 0:
        tree = _promote_spanning_leaves(tree, page_width)
    if page_height > 0:
        tree = _merge_bottom_region(tree, page_height)
    return traverse(tree)
