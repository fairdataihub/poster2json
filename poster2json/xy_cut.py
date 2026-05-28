"""Recursive XY-cut reading order recovery for pdfplumber chars.

Ports xpdf's TextOutputDev::splitChars / split / findGaps algorithm
(xpdf-4.06, TextOutputDev.cc lines 1846-4363) to Python. Constants are
from the same source, expressed in fractions of average font size.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import List, Tuple

MIN_GAP_AREA = 3.0
SPLIT_GAP_SLACK = 0.2
MIN_CHUNK_WIDTH = 2.0
MIN_GAP_SIZE = 0.2
BASELINE_RANGE = 0.5
DESCENT_ADJUST = 0.35


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
        for a, b in zip(bounds[:-1], bounds[1:]):
            sub = _chars_in(chars, a, y0, b, y1)
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
        for a, b in zip(bounds[:-1], bounds[1:]):
            sub = _chars_in(chars, x0, a, x1, b)
            if sub:
                children.append(split_block(sub, depth + 1))
        if len(children) <= 1:
            return Block("leaf", bbox, sorted(chars, key=lambda c: (c["bottom"], c["x0"])), [])
        return Block("hsplit", bbox, [], children)

    return Block("leaf", bbox, sorted(chars, key=lambda c: (c["bottom"], c["x0"])), [])


def _cluster_lines(chars):
    if not chars:
        return []
    sizes = [c.get("size", c["bottom"] - c["top"]) for c in chars]
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
    return lines


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
    if page_width > 0:
        tree = _promote_spanning_leaves(tree, page_width)
    if page_height > 0:
        tree = _merge_bottom_region(tree, page_height)
    return traverse(tree)
