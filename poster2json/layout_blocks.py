"""Leaf-aware line, word and block helpers for the pdfplumber text path.

Pure functions over pdfplumber char/word dicts (x0, x1, top, bottom, size,
fontname, text), so they can be unit tested with synthetic dicts.

The XY-cut tree in ``xy_cut`` decides reading order and yields leaves.  The
helpers here build lines and words *inside* each leaf, from the same chars,
so every word belongs to exactly one line and nothing is matched back by
bounding box.
"""

from __future__ import annotations

import bisect
import re
import statistics
from collections import Counter
from typing import Dict, List, Optional, Sequence, Tuple

# Feature switches.  All on by default; the offline A/B harness flips them
# one at a time to measure each step.
FLAGS: Dict[str, bool] = {
    "leaf": True,       # force block breaks at XY-cut leaf boundaries / upward jumps
    "decomp": True,     # words and lines built from the same chars, per leaf
    "body_tol": True,   # baseline tolerance from page body font size
    "sup": True,        # attach small raised/lowered chars to their line
    "fig": True,        # separate figure/table label text from body paragraphs
    "hyphen": True,     # join words hyphenated at line ends
    "dedupe": True,     # drop overprinted duplicate glyphs
    "rotated": True,    # keep rotated text (axis labels, sidebars) as whole words
}

BASELINE_RANGE = 0.5      # same value as xy_cut.BASELINE_RANGE
SMALL_RATIO = 0.8         # chars below this fraction of the leaf size may be sup/sub
ATTACH_GAP_EM = 0.5       # max horizontal gap (in line sizes) to a main char
ATTACH_OVERLAP = 0.5      # fraction of the small char that must sit in the line band


# ---------------------------------------------------------------------------
# font size helpers
# ---------------------------------------------------------------------------

def _size(c: dict) -> float:
    s = c.get("size")
    if s is None or s <= 0:
        s = c["bottom"] - c["top"]
    return s


def mode_size(chars: Sequence[dict]) -> float:
    """Most common char size (rounded to 0.5 pt), ties go to the larger size."""
    sizes = [round(_size(c) * 2) / 2 for c in chars if c.get("text", "").strip()]
    if not sizes:
        return 0.0
    cnt = Counter(sizes)
    best = max(cnt.items(), key=lambda kv: (kv[1], kv[0]))
    return float(best[0])


body_font_size = mode_size


def line_order(chars: Sequence[dict]) -> List[dict]:
    """Order the chars of one line.

    PDF stream order when every char carries its stream index (key "_si"),
    which keeps a string drawn twice (shadow, fake bold) as two separate runs
    instead of interleaving the two copies; left to right otherwise.
    """
    if chars and all("_si" in c for c in chars):
        return sorted(chars, key=lambda c: c["_si"])
    return sorted(chars, key=lambda c: c["x0"])


# ---------------------------------------------------------------------------
# lines
# ---------------------------------------------------------------------------

def _cluster_by_baseline(chars: Sequence[dict], tol: float) -> List[List[dict]]:
    """Group chars into lines by (running mean) bottom coordinate."""
    if not chars:
        return []
    chars = sorted(chars, key=lambda c: (c["bottom"], c["x0"]))
    lines: List[List[dict]] = []
    cur = [chars[0]]
    base_sum = chars[0]["bottom"]
    for c in chars[1:]:
        base = base_sum / len(cur)
        if abs(c["bottom"] - base) <= tol:
            cur.append(c)
            base_sum += c["bottom"]
        else:
            lines.append(cur)
            cur = [c]
            base_sum = c["bottom"]
    lines.append(cur)
    return lines


def _line_band(line: Sequence[dict]) -> Tuple[float, float, float]:
    top = min(c["top"] for c in line)
    bottom = max(c["bottom"] for c in line)
    return top, bottom, mode_size(line) or (bottom - top)


def _hgap(a: dict, b: dict) -> float:
    return max(a["x0"] - b["x1"], b["x0"] - a["x1"], 0.0)


def _attach_small(lines: List[List[dict]], small: Sequence[dict]) -> List[dict]:
    """Attach small raised/lowered chars to the line they belong to.

    A small char joins a line when it sits mostly inside the line's vertical
    band (extended a little) and touches a main char horizontally.  Among the
    candidate lines the choice is, in order: the line whose own band (no
    extension) contains the char's vertical centre, then the smallest
    horizontal gap to one of its chars, then the largest vertical overlap.
    It is never the nearest line centre, so a marker raised from a name does
    not jump to a bigger-font line that happens to sit just above or below.
    Host lines much bigger than the marker (more than 2.2x) are skipped.
    Returns the chars that could not be attached.
    """
    bands = [_line_band(ln) for ln in lines]
    leftover = []
    for c in small:
        ch = max(c["bottom"] - c["top"], 0.1)
        cy = (c["top"] + c["bottom"]) / 2
        best = None
        best_key = None
        for idx, (ln, (top, bottom, lsize)) in enumerate(zip(lines, bands)):
            if lsize > 2.2 * _size(c):
                continue
            lo, hi = top - 0.3 * lsize, bottom + 0.3 * lsize
            ov = min(c["bottom"], hi) - max(c["top"], lo)
            if ov < ATTACH_OVERLAP * ch:
                continue
            gap = min(_hgap(c, m) for m in ln)
            if gap > ATTACH_GAP_EM * lsize:
                continue
            inside = top <= cy <= bottom
            key = (0 if inside else 1, gap, -ov)
            if best_key is None or key < best_key:
                best, best_key = idx, key
        if best is None:
            leftover.append(c)
        else:
            lines[best].append(c)
    return leftover


def _local_small(chars: Sequence[dict]) -> set:
    """Ids of chars that are clearly smaller than an adjacent same-row char.

    A char is a marker candidate when a horizontally adjacent char (gap under
    half its own size) is at least 1.25x bigger and the small char's vertical
    centre lies within that neighbour's box.  This finds author affiliation
    markers on a line whose leaf mixes other sizes, where the leaf's dominant
    size is not the host line's size.
    """
    cell = 64.0
    grid: Dict[Tuple[int, int], List[dict]] = {}
    for c in chars:
        grid.setdefault((int(c["x0"] // cell), int(c["top"] // cell)), []).append(c)
    out = set()
    for c in chars:
        sz = _size(c)
        cy = (c["top"] + c["bottom"]) / 2
        gx, gy = int(c["x0"] // cell), int(c["top"] // cell)
        found = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for n in grid.get((gx + dx, gy + dy), ()):
                    if n is c or _size(n) < 1.25 * sz:
                        continue
                    if _hgap(c, n) > 0.5 * sz:
                        continue
                    if n["top"] <= cy <= n["bottom"]:
                        found = True
                        break
                if found:
                    break
            if found:
                break
        if found:
            out.add(id(c))
    return out


def cluster_leaf_lines(chars: Sequence[dict], body_size: float = 0.0,
                       use_body_tol: bool = True,
                       attach_small: bool = True) -> List[List[dict]]:
    """Cluster the chars of one XY-cut leaf into lines (each sorted by x0).

    * Baseline tolerance is ``BASELINE_RANGE`` times the smaller of the page
      body size and the leaf's own dominant size, rather than the leaf mean,
      so one big title glyph does not coarsen the tolerance for the body.
    * Chars much smaller than the leaf's dominant size (superscripts,
      subscripts, footnote marks) are clustered afterwards and attached to the
      nearest line, instead of forming stray lines or splitting a line.
    """
    chars = [c for c in chars if c.get("text", "").strip()]
    if not chars:
        return []
    leaf_mode = mode_size(chars)
    if use_body_tol and body_size > 0 and leaf_mode > 0:
        ref = min(body_size, leaf_mode)
    else:
        ref = statistics.fmean(_size(c) for c in chars)
    tol = BASELINE_RANGE * max(ref, 1.0)

    small: List[dict] = []
    main = chars
    if attach_small and leaf_mode > 0:
        cut = SMALL_RATIO * leaf_mode
        local = _local_small(chars)
        small = [c for c in chars if _size(c) < cut or id(c) in local]
        main = [c for c in chars if not (_size(c) < cut or id(c) in local)]
        if not main:
            main, small = chars, []

    lines = _cluster_by_baseline(main, tol)
    if small:
        leftover = _attach_small(lines, small)
        if leftover:
            small_ref = max(statistics.fmean(_size(c) for c in leftover), 1.0)
            lines.extend(_cluster_by_baseline(leftover, BASELINE_RANGE * small_ref))

    def key(ln):
        return statistics.fmean(c["bottom"] for c in ln)

    lines.sort(key=key)
    return [line_order(ln) for ln in lines]


# ---------------------------------------------------------------------------
# words
# ---------------------------------------------------------------------------

def chars_to_words(line_chars: Sequence[dict], x_tol: float,
                   space_xs: Sequence[float] = ()) -> List[dict]:
    """Split one line's chars (any order) into word dicts.

    A word break falls between two chars when the gap exceeds ``x_tol`` or
    when a space glyph (given by its centre x in ``space_xs``) sits between
    their centres.

    Word geometry (top/bottom) and size come from the line's main-size chars,
    so an attached superscript does not inflate the word box.
    """
    chars = line_order([c for c in line_chars if c.get("text", "")])
    if not chars:
        return []
    groups: List[List[dict]] = []
    cur = [chars[0]]
    right = chars[0]["x1"]
    prev = chars[0]
    spaces = sorted(space_xs)
    line_mode = mode_size(chars)
    small_cut = SMALL_RATIO * line_mode
    for c in chars[1:]:
        has_space = False
        if spaces:
            lo = (prev["x0"] + prev["x1"]) / 2
            hi = (c["x0"] + c["x1"]) / 2
            i = bisect.bisect_right(spaces, lo)
            has_space = i < len(spaces) and spaces[i] <= hi
        # A small raised/lowered run stays on the line but is its own word,
        # so "Me-1" followed by a superscript "100" does not fuse to "Me-1100".
        size_flip = (_size(prev) < small_cut) != (_size(c) < small_cut)
        prev_x0 = prev["x0"]
        prev = c
        backwards = c["x1"] < prev_x0 - x_tol
        if c["x0"] - right > x_tol or has_space or size_flip or backwards:
            groups.append(cur)
            cur = [c]
            right = c["x1"]
        else:
            cur.append(c)
            right = max(right, c["x1"])
    groups.append(cur)

    words = []
    for g in groups:
        main = [c for c in g if _size(c) >= SMALL_RATIO * line_mode] or g
        fonts = [c["fontname"] for c in main if c.get("fontname")]
        words.append({
            "text": "".join(c["text"] for c in g),
            "x0": min(c["x0"] for c in g),
            "x1": max(c["x1"] for c in g),
            "top": min(c["top"] for c in main),
            "bottom": max(c["bottom"] for c in main),
            "size": mode_size(main) or _size(main[0]),
            "fontname": max(set(fonts), key=fonts.count) if fonts else "",
        })
    return words


def _index_spaces(spaces: Sequence[dict]) -> Dict[int, List[dict]]:
    idx: Dict[int, List[dict]] = {}
    for s in spaces:
        idx.setdefault(int(((s["top"] + s["bottom"]) / 2) // 4), []).append(s)
    return idx


def _line_space_xs(line: Sequence[dict], idx: Dict[int, List[dict]],
                   used: set) -> List[float]:
    """Centre x of every unused space glyph lying inside the line's box."""
    if not idx:
        return []
    top = min(c["top"] for c in line)
    bottom = max(c["bottom"] for c in line)
    x0 = min(c["x0"] for c in line)
    x1 = max(c["x1"] for c in line)
    lsize = mode_size(line) or (bottom - top)
    xs = []
    for key in range(int(top // 4), int(bottom // 4) + 1):
        for s in idx.get(key, ()):
            if id(s) in used:
                continue
            cy = (s["top"] + s["bottom"]) / 2
            cx = (s["x0"] + s["x1"]) / 2
            if not (top <= cy <= bottom and x0 <= cx <= x1):
                continue
            # the space must belong to this line: similar size and mostly
            # inside its box (blank filler runs in another size overlap
            # neighbouring lines and must not cut their words)
            sh = max(s["bottom"] - s["top"], 0.1)
            inside = min(s["bottom"], bottom) - max(s["top"], top)
            if inside < 0.6 * sh:
                continue
            ss = _size(s)
            if lsize > 0 and not (0.75 <= ss / lsize <= 1.34):
                continue
            used.add(id(s))
            xs.append(cx)
    return xs


def is_rotated(c: dict) -> bool:
    """True for a char drawn along a vertical (or otherwise rotated) baseline."""
    if not c.get("upright", True):
        return True
    m = c.get("matrix")
    return bool(m) and abs(m[1]) > abs(m[0]) + 1e-6


def drop_duplicate_words(words: Sequence[dict]) -> List[dict]:
    """Drop a word that repeats an earlier word of the line on top of it.

    Overprinted text (shadows, fake bold with a large offset) yields the same
    word twice in nearly the same place.  Same text and at least half of the
    narrower box overlapping horizontally and vertically means a duplicate.
    """
    kept: List[dict] = []
    for w in words:
        dup = False
        for k in kept:
            if k["text"] != w["text"]:
                continue
            ox = min(k["x1"], w["x1"]) - max(k["x0"], w["x0"])
            oy = min(k["bottom"], w["bottom"]) - max(k["top"], w["top"])
            if (ox >= 0.5 * min(k["x1"] - k["x0"], w["x1"] - w["x0"])
                    and oy >= 0.5 * min(k["bottom"] - k["top"], w["bottom"] - w["top"])):
                dup = True
                break
        if not dup:
            kept.append(w)
    return kept


def split_rotated(chars: Sequence[dict], min_ratio: float = 3.0
                  ) -> Tuple[List[dict], List[dict]]:
    """Separate rotated chars (axis labels, sidebars) from upright text.

    Rotated chars cannot be clustered into horizontal lines.  They are split
    off only when upright text clearly dominates the page (a page that is
    entirely rotated is left alone).  Returns (upright chars, rotated chars).
    """
    rot = [c for c in chars if c.get("text", "").strip() and is_rotated(c)]
    if not rot:
        return list(chars), []
    rot_ids = {id(c) for c in rot}
    up = [c for c in chars if id(c) not in rot_ids]
    if sum(1 for c in up if c.get("text", "").strip()) < min_ratio * len(rot):
        return list(chars), []
    return up, rot


def rotated_word_lines(chars: Sequence[dict], x_tol: float,
                       first_region: int = 1_000_000
                       ) -> Tuple[List[List[dict]], List[int]]:
    """Build whole words from rotated chars, one line per vertical strip.

    Chars are grouped into strips by their x centre; inside a strip they are
    read along the strip (bottom to top when the text matrix points up, else
    top to bottom) and split into words at gaps wider than ``x_tol``.  Each
    strip becomes one line with its own region id, so it never merges with
    upright blocks.  Strips are ordered left to right.
    """
    chars = [c for c in chars if c.get("text", "").strip()]
    if not chars:
        return [], []
    chars = sorted(chars, key=lambda c: (c["x0"] + c["x1"]) / 2)
    strips: List[List[dict]] = [[chars[0]]]
    for c in chars[1:]:
        cur = strips[-1]
        mean_x = sum((k["x0"] + k["x1"]) / 2 for k in cur) / len(cur)
        if abs((c["x0"] + c["x1"]) / 2 - mean_x) <= 0.6 * max(_size(c), 1.0):
            cur.append(c)
        else:
            strips.append([c])
    lines, ids = [], []
    for k, st in enumerate(strips):
        m = st[0].get("matrix")
        up = (m[1] > 0) if m else True
        st = sorted(st, key=lambda c: -c["bottom"] if up else c["top"])
        groups, cur = [], [st[0]]
        prev = st[0]
        for c in st[1:]:
            gap = (prev["top"] - c["bottom"]) if up else (c["top"] - prev["bottom"])
            if gap > x_tol:
                groups.append(cur)
                cur = [c]
            else:
                cur.append(c)
            prev = c
        groups.append(cur)
        words = []
        for g in groups:
            fonts = [c["fontname"] for c in g if c.get("fontname")]
            words.append({
                "text": "".join(c["text"] for c in g),
                "x0": min(c["x0"] for c in g), "x1": max(c["x1"] for c in g),
                "top": min(c["top"] for c in g), "bottom": max(c["bottom"] for c in g),
                "size": mode_size(g) or _size(g[0]),
                "fontname": max(set(fonts), key=fonts.count) if fonts else "",
            })
        lines.append(words)
        ids.append(first_region + k)
    return lines, ids


def build_word_lines(leaves: Sequence[Sequence[dict]], x_tol: float,
                     body_size: float = 0.0, flags: Optional[dict] = None,
                     regions: Optional[Sequence[int]] = None,
                     spaces: Sequence[dict] = ()
                     ) -> Tuple[List[List[dict]], List[int]]:
    """Leaves of chars -> (word lines, region id per line), in reading order.

    ``regions`` gives the column region of each leaf (default: leaf index).
    ``spaces`` are the page's space glyphs; they are not part of the XY-cut
    leaves, so each is matched to the single line whose box contains it and
    used as a word break.
    """
    sp_idx = _index_spaces(spaces)
    used: set = set()
    flags = FLAGS if flags is None else flags
    word_lines: List[List[dict]] = []
    leaf_ids: List[int] = []
    for li, leaf in enumerate(leaves):
        i = regions[li] if regions is not None else li
        for ln in cluster_leaf_lines(leaf, body_size,
                                     use_body_tol=flags.get("body_tol", True),
                                     attach_small=flags.get("sup", True)):
            words = drop_duplicate_words(
                chars_to_words(ln, x_tol, _line_space_xs(ln, sp_idx, used)))
            if words:
                word_lines.append(words)
                leaf_ids.append(i)
    return word_lines, leaf_ids


# ---------------------------------------------------------------------------
# hyphenation
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*", re.UNICODE)
_TRAIL_RE = re.compile(r"([^\W\d_]{2,})-$", re.UNICODE)
_LEAD_RE = re.compile(r"^([a-zß-ÿ]+)(.*)$", re.UNICODE | re.DOTALL)


def page_vocab(texts: Sequence[str]) -> set:
    """Lower-cased hyphen-aware word forms seen in the given line texts."""
    vocab = set()
    for t in texts:
        for m in _WORD_RE.finditer(t):
            vocab.add(m.group(0).lower())
    return vocab


_SENT_END_RE = re.compile(r"[.!?:;…)\]\"”]\s*$")


def continues_paragraph(prev_text: str, curr_text: str) -> bool:
    """True when ``curr_text`` reads as the continuation of ``prev_text``.

    Used at a column jump: a paragraph that runs from the bottom of one column
    to the top of the next ends its last line mid-sentence (no sentence-final
    punctuation, or a hyphen) and the next line starts in lowercase.
    """
    prev_text = prev_text.rstrip()
    curr_text = curr_text.lstrip()
    if not prev_text or not curr_text:
        return False
    if not curr_text[0].islower():
        return False
    if len(prev_text.split()) < 3:
        return False
    return not _SENT_END_RE.search(prev_text)


def join_lines(texts: Sequence[str], vocab: Optional[set] = None) -> str:
    """Join the lines of a block, repairing words hyphenated at line ends.

    A line ending in ``letters-`` followed by a line starting in lowercase is
    a candidate.  The hyphen is dropped and the halves joined when the joined
    form is a word seen elsewhere on the page, or when the hyphenated form is
    not (so true compounds like "long-term" survive).  If the page offers no
    evidence either way, the hyphen is kept and the space removed
    ("informa-tion"), which never loses a token compared with the old output.
    """
    if not texts:
        return ""
    vocab = vocab or set()
    out = texts[0]
    for nxt in texts[1:]:
        m = _TRAIL_RE.search(out)
        n = _LEAD_RE.match(nxt)
        if m and n and not out.endswith("--"):
            left = m.group(1).lower()
            right = n.group(1).lower()
            joined = left + right
            hyph = left + "-" + right
            if joined in vocab and hyph not in vocab:
                out = out[:-1] + nxt
            elif hyph in vocab:
                out = out + nxt
            else:
                out = out + nxt
            continue
        out = out + " " + nxt
    return out


# ---------------------------------------------------------------------------
# overprinted glyphs
# ---------------------------------------------------------------------------

def dedupe_overprinted(chars: Sequence[dict], tolerance: float = 1.0) -> List[dict]:
    """Drop chars drawn twice at (nearly) the same place (fake bold, shadows).

    Two chars are duplicates when text, fontname and size match and both x0
    and top are within ``tolerance`` points.  The first one in stream order
    is kept.  Same idea as pdfplumber's Page.dedupe_chars, without needing a
    Page object.
    """
    cell = max(tolerance, 0.5) * 2
    seen: Dict[tuple, List[Tuple[float, float]]] = {}
    out = []
    for c in chars:
        text = c.get("text", "")
        if not text.strip():
            out.append(c)
            continue
        base = (text, c.get("fontname"), round(_size(c), 1))
        x0, top = c["x0"], c["top"]
        gx, gy = int(x0 // cell), int(top // cell)
        dup = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for px, pt in seen.get(base + (gx + dx, gy + dy), ()):
                    if abs(px - x0) <= tolerance and abs(pt - top) <= tolerance:
                        dup = True
                        break
                if dup:
                    break
            if dup:
                break
        if dup:
            continue
        seen.setdefault(base + (gx, gy), []).append((x0, top))
        out.append(c)
    return out


# ---------------------------------------------------------------------------
# figure / table label separation
# ---------------------------------------------------------------------------

MASK_MIN_AREA = 0.0005    # fraction of page area; smaller shapes are decoration
IMAGE_MIN_AREA = 0.005
MASK_MAX_AREA = 0.25      # bigger shapes are panels or backgrounds, not figures
CLUSTER_GAP = 6.0         # pt; shapes closer than this belong to one cluster
MIN_TABLE_CELLS = 3
MIN_CLUSTER_SHAPES = 4
MIN_NUMERIC_FRACTION = 0.3
MAX_PROSE_FRACTION = 0.2
PROSE_RUN = 6
_NUM_RE = re.compile(r"\d")
_CAPTION_RE = re.compile(r"^[^A-Za-z]*(fig(ure)?|tab(le)?)\b", re.IGNORECASE)


def _area(b):
    return max(b[2] - b[0], 0.0) * max(b[3] - b[1], 0.0)


def _contains(a, b, slack=1.0):
    return (a[0] - slack <= b[0] and a[1] - slack <= b[1]
            and a[2] + slack >= b[2] and a[3] + slack >= b[3])


def _near(a, b, gap):
    return not (a[2] + gap < b[0] or b[2] + gap < a[0]
                or a[3] + gap < b[1] or b[3] + gap < a[1])


def build_figure_masks(images: Sequence[dict], shapes: Sequence[dict],
                       page_w: float, page_h: float,
                       body_size: float = 0.0) -> List[dict]:
    """Cluster page graphics into figure/table masks.

    ``images`` are page.images, ``shapes`` are rects, curves and lines.
    Returns a list of ``{"kind": "image"|"graphic", "boxes": [bbox, ...]}``.
    Huge shapes (backgrounds) and shapes that contain several others (a
    panel around a table) are ignored.  Nearby shapes (closer than about one
    body line) are clustered, so the cells and rules of a table or the axes,
    ticks and bars of a plot form one mask; a cluster of 4+ shapes is
    represented by its union box grown by a small margin, so axis tick labels
    just outside the drawing are covered.
    """
    page_area = max(page_w * page_h, 1.0)
    gap = max(CLUSTER_GAP, body_size)
    margin = 0.75 * body_size

    def box(o):
        return (o["x0"], o["top"], o["x1"], o["bottom"])

    masks: List[dict] = []
    for o in images:
        b = box(o)
        frac = _area(b) / page_area
        if IMAGE_MIN_AREA <= frac <= MASK_MAX_AREA:
            masks.append({"kind": "image", "boxes": [b]})

    cand = []
    for o in shapes:
        b = box(o)
        if _area(b) / page_area > MASK_MAX_AREA:
            continue
        if max(b[2] - b[0], b[3] - b[1]) < 1.0:
            continue
        cand.append(b)
    # a shape that fully contains 3+ other shapes is a panel, not a figure
    keep = []
    for i, b in enumerate(cand):
        if _area(b) / page_area >= MASK_MIN_AREA:
            inside = sum(1 for j, o in enumerate(cand) if j != i and _contains(b, o))
            if inside >= MIN_TABLE_CELLS:
                continue
        keep.append(b)

    parent = list(range(len(keep)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    order = sorted(range(len(keep)), key=lambda i: keep[i][0])
    for a_pos, i in enumerate(order):
        for j in order[a_pos + 1:]:
            if keep[j][0] > keep[i][2] + gap:
                break
            if _near(keep[i], keep[j], gap):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj
    groups: Dict[int, List[tuple]] = {}
    for i, b in enumerate(keep):
        groups.setdefault(find(i), []).append(b)
    for boxes in groups.values():
        if len(boxes) >= MIN_CLUSTER_SHAPES:
            u = (min(b[0] for b in boxes) - margin, min(b[1] for b in boxes) - margin,
                 max(b[2] for b in boxes) + margin, max(b[3] for b in boxes) + margin)
            if _area(u) / page_area > MASK_MAX_AREA:
                continue
            masks.append({"kind": "graphic", "boxes": [u]})
        elif sum(_area(b) for b in boxes) / page_area >= MASK_MIN_AREA:
            masks.append({"kind": "graphic", "boxes": boxes})
    return masks


def _is_numeric_token(t: str) -> bool:
    if not _NUM_RE.search(t):
        return False
    alpha = sum(ch.isalpha() for ch in t)
    return alpha <= max(1, len(t) // 3)


def _prose_fraction(words: Sequence[dict]) -> float:
    """Share of the words that sit in runs of 6+ words on one text row."""
    rows: Dict[int, int] = {}
    for w in words:
        key = int(round((w["top"] + w["bottom"]) / 2 / max(w.get("size", 10), 1)))
        rows[key] = rows.get(key, 0) + 1
    long_words = sum(n for n in rows.values() if n >= PROSE_RUN)
    return long_words / max(len(words), 1)


def split_figure_words(word_lines: Sequence[List[dict]], leaf_ids: Sequence[int],
                       masks: Sequence[dict], body_size: float
                       ) -> Tuple[list, list, list, list, list, list]:
    """Split word lines into body lines and figure-label lines.

    A word is a label candidate when its centre lies in a figure mask.  The
    candidates of a mask are kept as labels when they look like figure or
    table text (cells of a table with short entries, mostly numeric groups,
    or a few words over an image).  Headings (large or bold lines), figure
    and table captions, and prose stay in the body.  Nothing is dropped:
    labels only move to separate lines.

    Returns (body_lines, body_ids, label_lines, label_ids, body_order,
    label_order); the order lists hold each line's index in ``word_lines``.
    """
    if not masks:
        n = len(word_lines)
        return list(word_lines), list(leaf_ids), [], [], list(range(n)), []

    def mask_of(w):
        cx, cy = (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2
        for mi, m in enumerate(masks):
            for b in m["boxes"]:
                if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]:
                    return mi
        return -1

    def protected(line):
        text = " ".join(w["text"] for w in line)
        if _CAPTION_RE.match(text):
            return True
        size = max(w.get("size", 0) for w in line)
        if body_size > 0 and size >= 1.3 * body_size:
            return True
        styles = [w.get("fontname", "") for w in line]
        bold = sum(1 for f in styles if re.search(r"bold|black|heavy", f, re.I))
        return bool(styles) and bold > len(styles) / 2 and len(line) <= 8

    cand: Dict[int, List[dict]] = {}
    per_line: List[List[int]] = []
    for line in word_lines:
        idxs = []
        prot = protected(line)
        for w in line:
            mi = -1 if prot else mask_of(w)
            idxs.append(mi)
            if mi >= 0:
                cand.setdefault(mi, []).append(w)
        per_line.append(idxs)

    label_masks = set()
    for mi, ws in cand.items():
        toks = [w["text"] for w in ws]
        numeric = sum(1 for t in toks if _is_numeric_token(t)) / max(len(toks), 1)
        if _prose_fraction(ws) > MAX_PROSE_FRACTION:
            continue
        m = masks[mi]
        if m["kind"] == "image":
            ok = len(ws) <= 12 or numeric >= 0.4
        else:
            ok = numeric >= MIN_NUMERIC_FRACTION and len(ws) <= 400
        if ok:
            label_masks.add(mi)

    body, body_ids, label, label_ids = [], [], [], []
    body_order, label_order = [], []
    for n, (line, lid, idxs) in enumerate(zip(word_lines, leaf_ids, per_line)):
        keep = [w for w, mi in zip(line, idxs) if mi not in label_masks]
        lab = [w for w, mi in zip(line, idxs) if mi in label_masks]
        if keep:
            body.append(keep)
            body_ids.append(lid)
            body_order.append(n)
        if lab:
            label.append(lab)
            label_ids.append(lid)
            label_order.append(n)
    return body, body_ids, label, label_ids, body_order, label_order
