"""Recursive XY-cut reading order recovery for pdfplumber chars.

Ports xpdf's TextOutputDev::splitChars / split / findGaps algorithm
(xpdf-4.06, TextOutputDev.cc lines 1846-4363) to Python. Constants are
from the same source, expressed in fractions of average font size.
"""

from __future__ import annotations

import bisect
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


def iter_leaves(block: Block):
    """Yield the leaf blocks of an XY-cut tree in reading order."""
    for leaf, _path in iter_leaves_with_path(block):
        yield leaf


def iter_leaves_with_path(block: Block, path: tuple = ()):
    """Yield (leaf, column path) in reading order.

    The path records, for every vsplit (column split) on the way down from the
    root, which child the leaf lives under.  Two leaves with the same path are
    stacked vertically inside one column region; different paths mean the
    reading order jumps between columns.
    """
    if block.kind == "leaf":
        yield block, path
        return
    for i, ch in enumerate(block.children):
        sub = path + ((id(block), i),) if block.kind == "vsplit" else path
        yield from iter_leaves_with_path(ch, sub)


def _build_tree(raw_chars: list, page_width: float, page_height: float):
    chars = [c for c in raw_chars if c.get("text", "").strip()]
    if not chars:
        return None
    tree = split_block(chars)
    if page_width > 0:
        tree = _promote_spanning_leaves(tree, page_width)
    if page_height > 0:
        tree = _merge_bottom_region(tree, page_height)
    return tree


def chars_to_leaves(raw_chars: list, page_width: float = 0,
                    page_height: float = 0):
    """Return (leaf char lists, column region id per leaf), in reading order.

    Unlike chars_to_reading_order this keeps the XY-cut structure, so callers
    can refuse to merge text across column-region boundaries.  Region ids are
    small ints, equal for leaves with the same column path.
    """
    tree = _build_tree(raw_chars, page_width, page_height)
    if tree is None:
        return [], []
    leaves, regions, seen = [], [], {}
    for leaf, path in iter_leaves_with_path(tree):
        if not leaf.chars:
            continue
        leaves.append(leaf.chars)
        regions.append(seen.setdefault(path, len(seen)))
    return leaves, regions


def chars_to_leaf_lines(raw_chars: list, page_width: float = 0,
                        page_height: float = 0):
    """Like chars_to_reading_order, but also return a column region id per line."""
    tree = _build_tree(raw_chars, page_width, page_height)
    if tree is None:
        return [], []
    lines, ids, seen = [], [], {}
    for leaf, path in iter_leaves_with_path(tree):
        rid = seen.setdefault(path, len(seen))
        for ln in _cluster_lines(leaf.chars):
            lines.append(ln)
            ids.append(rid)
    return lines, ids


def chars_to_reading_order(raw_chars: list, page_width: float = 0,
                           page_height: float = 0) -> list:
    tree = _build_tree(raw_chars, page_width, page_height)
    if tree is None:
        return []
    return traverse(tree)
