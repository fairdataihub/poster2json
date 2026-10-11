"""Deterministic figure and table caption extraction from page geometry.

The core is engine neutral.  It takes the text blocks of one page, the figure
and table regions of that page and the words inside them, and returns the
captions.  The default ``blocks`` engine of ``extract.py`` calls it per page;
another layout engine can call it with its own blocks.

Inputs (plain dicts, units in points, y grows downward):

* block:  ``{"hpos", "vpos", "width", "height", "text", "fontsize", "bold"}``
  plus optional ``"fig": True`` for blocks that are figure-internal labels.
* region: ``{"kind": "image" | "graphic", "box": (x0, top, x1, bottom)}``
* word:   ``{"x0", "x1", "top", "bottom", "text", "size"}``

A caption starts at either

* a block that begins with a printed label ("Figure 2.", "Fig. 2:", "Table 1")
  followed by a separator.  The label is a strong signal; the block may sit
  anywhere on the page.
* an unlabeled block that sits directly below, above or beside a region, is
  set in a font no larger than the body text, reads like a sentence and is not
  text inside the region (axis labels, legend entries, cell text).

The caption is then grown across continuation blocks (same column, same font
size, small vertical gap) so wrapped and multi part captions are whole.
"""

import re
from collections import Counter
from typing import Dict, List, Optional, Sequence

# Label at the start of a block: "Figure 2.", "Fig. 2:", "Table 1 |", "FIGURE S3 -".
# The number may be missing when a separator follows ("Figure: ...").
_LABEL_RE = re.compile(
    r"^[^\w]*(?P<word>fig(?:ure)?s?|tab(?:le)?s?)\.?\s*"
    r"(?:(?P<num>S?\d+[A-Za-z]?|[IVX]{1,4})\b(?P<sep>\s*[.:|\u2013\u2014-])?"
    r"|(?P<sep2>\s*[.:|]))",
    re.IGNORECASE,
)
# A second label inside a block that starts with one ("Figure 1: ... Figure 2: ...").
_INLINE_LABEL_RE = re.compile(
    r"(?<=[\s.;])(?P<word>fig(?:ure)?s?|tab(?:le)?s?)\.?\s*(?P<num>S?\d+[A-Za-z]?)\s*[.:|]\s*(?=[A-Z])",
    re.IGNORECASE,
)
_CONNECTORS = {"see", "in", "and", "of", "to", "from", "with", "per", "vs", "versus",
               "fig", "figure", "table", "tab", "or", "as", "by", "on", "for", "at"}
# A block that is only the label word, with the number in the next block.
_LABEL_WORD_RE = re.compile(r"^\W*(fig(?:ure)?|tab(?:le)?)\.?\W*$", re.IGNORECASE)
# Footer, disclaimer and funding statements are not captions.
_NOT_CAPTION_RE = re.compile(
    r"supported by|funded by|\bfunding\b|\bgrants?\b|copyright|\u00a9|rights reserved|"
    r"acknowledg|\bthank|\bcontact|correspondence|obtained through|\bscan\b|"
    r"\bqr\b|\be-?mail\b",
    re.IGNORECASE,
)

# Tunables, as multiples of the font size unless noted.
ADJ_GAP = 2.5            # max vertical gap between a region and its caption
TIGHT_GAP = 1.6          # gap that counts as directly touching the region
SIDE_GAP = 2.0           # max horizontal gap for a caption beside a region
GROW_GAP = 1.5           # max vertical gap between caption blocks
GROW_GAP_BODY = 0.8      # same, when the caption is set at body size
SIZE_TOL = 0.12          # font size tolerance inside one caption
SMALL_RATIO = 0.95       # font below this * body size: smaller than body text
BODY_RATIO = 1.05        # font up to this * body size: set at body size
BODY_WIDTH_RATIO = 1.05    # body-size caption width vs the width of its figure
BODY_MAX_LINES = 10      # a body-size unlabeled caption is at most this tall
LABEL_MAX_RATIO = 1.35   # labeled caption font <= this * body size
MIN_WORDS = 6
MIN_SHORT_WORDS = 3      # tight caption directly under an image
MIN_ALPHA_FRACTION = 0.6
MIN_REGION_W = 3.0       # region must be at least this many body sizes wide
MIN_REGION_H = 2.0       # ... and tall
MIN_FIGURE_SHAPES = 4    # a vector figure is a cluster of at least this many shapes
PANEL_WORDS = 25         # a region holding a paragraph this long is a text panel
INSIDE_FRACTION = 0.5
BANNER_FRACTION = 0.15   # unlabeled blocks ending above this part of the page are banner text
FOOTER_FRACTION = 0.93   # blocks starting below this part of the page are footers


def match_label(text: str) -> Optional[dict]:
    """Parse a leading figure/table label.  Returns None when there is none."""
    m = _LABEL_RE.match(text or "")
    if not m:
        return None
    kind = "table" if m.group("word")[:3].lower() == "tab" else "figure"
    return {
        "kind": kind,
        "num": m.group("num"),
        "has_sep": bool(m.group("sep") or m.group("sep2")),
        "end": m.end(),
    }


def split_inline_labels(text: str) -> List[str]:
    """Split a caption block that holds several labeled captions in a row.

    The text must start with a label.  A later label starts a new caption only
    when it is not part of a sentence ("see Figure 2: ...")."""
    if not match_label(text):
        return [text]
    cuts = []
    for m in _INLINE_LABEL_RE.finditer(text):
        prev = re.findall(r"[A-Za-z]+", text[:m.start()])
        if prev and prev[-1].lower() in _CONNECTORS:
            continue
        if m.start() < 8:
            continue
        cuts.append(m.start())
    if not cuts:
        return [text]
    parts, last = [], 0
    for c in cuts:
        parts.append(text[last:c].strip())
        last = c
    parts.append(text[last:].strip())
    return [p for p in parts if p]


def _box(b: dict) -> tuple:
    return (b["hpos"], b["vpos"], b["hpos"] + b["width"], b["vpos"] + b["height"])


def _area(b) -> float:
    return max(b[2] - b[0], 0.0) * max(b[3] - b[1], 0.0)


def _inter(a, b) -> float:
    return _area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def _overlap_1d(a0, a1, b0, b1) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _alpha_words(text: str) -> List[str]:
    return re.findall(r"[^\W\d_]{2,}", text, re.UNICODE)


def _looks_like_sentence(text: str, min_words: int = MIN_WORDS) -> bool:
    toks = text.split()
    if len(toks) < min_words:
        return False
    alpha = _alpha_words(text)
    if len(alpha) < max(min_words - 1, 2):
        return False
    if sum(len(w) for w in alpha) / max(len(text.replace(" ", "")), 1) < MIN_ALPHA_FRACTION:
        return False
    if re.search(r"@\S+\.\S+|https?://|www\.", text):
        return False
    return any(w.islower() for w in alpha)


def body_size_of(blocks: Sequence[dict], fallback: float = 0.0) -> float:
    """Body font size: the text-weighted median size of running (long) blocks.

    More robust than the most common character size, which tiny figure text
    can dominate, and than the mode, which a long reference list can take."""
    weight: Counter = Counter()
    for b in blocks:
        if b.get("fig") or b["fontsize"] <= 0:
            continue
        n = len(b["text"].strip())
        if n >= 60:
            weight[round(b["fontsize"] * 2) / 2] += n
    if not weight:
        return fallback
    total = sum(weight.values())
    acc = 0
    for size in sorted(weight):
        acc += weight[size]
        if acc >= total / 2:
            return float(size)
    return fallback


def regions_from_masks(masks: Sequence[dict], body_size: float) -> List[dict]:
    """Turn ``layout_blocks.build_figure_masks`` output into caption regions."""
    out = []
    for m in masks:
        boxes = m["boxes"]
        box = (min(b[0] for b in boxes), min(b[1] for b in boxes),
               max(b[2] for b in boxes), max(b[3] for b in boxes))
        if (box[2] - box[0] < MIN_REGION_W * body_size
                or box[3] - box[1] < MIN_REGION_H * body_size):
            continue
        out.append({"kind": m["kind"], "box": box, "shapes": len(boxes)})
    return out


def _is_table_like(region: dict, words: Sequence[dict]) -> bool:
    """A graphic region whose text forms a grid of rows and aligned columns."""
    if region["kind"] != "graphic":
        return False
    box = region["box"]
    inside = [w for w in words
              if box[0] <= (w["x0"] + w["x1"]) / 2 <= box[2]
              and box[1] <= (w["top"] + w["bottom"]) / 2 <= box[3]]
    if len(inside) < 6:
        return False
    size = max(sorted(w.get("size", 10) for w in inside)[len(inside) // 2], 1.0)
    rows: Dict[int, List[dict]] = {}
    for w in inside:
        rows.setdefault(int(round((w["top"] + w["bottom"]) / 2 / (0.8 * size))), []).append(w)
    multi = [r for r in rows.values() if len(r) >= 2]
    if len(rows) < 3 or len(multi) < 0.6 * len(rows):
        return False
    starts: Dict[int, int] = {}
    for r in multi:
        for k in {int(round(w["x0"] / (1.5 * size))) for w in r}:
            starts[k] = starts.get(k, 0) + 1
    repeated = sum(1 for n in starts.values() if n >= 0.6 * len(multi))
    return repeated >= 2


def _region_is_panel(region: dict, blocks: Sequence[dict], body_size: float) -> bool:
    """A box around running prose is a text panel, not a figure."""
    box = region["box"]
    for b in blocks:
        if b.get("fig"):
            continue
        bb = _box(b)
        if (_inter(bb, box) >= 0.8 * max(_area(bb), 1e-6)
                and len(_alpha_words(b["text"])) >= PANEL_WORDS
                and b["fontsize"] >= 0.9 * body_size):
            return True
    return False


def _adjacent(bb, region_box, fs: float):
    """Where ``bb`` sits relative to the region and the gap to it.

    Returns ``(side, gap)`` with side in below/above/right/left, or None."""
    gap_v = ADJ_GAP * fs
    gap_h = SIDE_GAP * fs
    w = bb[2] - bb[0]
    rw = region_box[2] - region_box[0]
    hov = _overlap_1d(bb[0], bb[2], region_box[0], region_box[2]) / max(min(w, rw), 1e-6)
    if hov >= 0.5:
        d_below = bb[1] - region_box[3]
        if -0.5 * fs <= d_below <= gap_v:
            return "below", d_below
        d_above = region_box[1] - bb[3]
        if -0.5 * fs <= d_above <= gap_v:
            return "above", d_above
    h = bb[3] - bb[1]
    rh = region_box[3] - region_box[1]
    vov = _overlap_1d(bb[1], bb[3], region_box[1], region_box[3]) / max(min(h, rh), 1e-6)
    if vov >= 0.6:
        d_right = bb[0] - region_box[2]
        if -0.5 * fs <= d_right <= gap_h:
            return "right", d_right
        d_left = region_box[0] - bb[2]
        if -0.5 * fs <= d_left <= gap_h:
            return "left", d_left
    return None


def _merge_label_words(blocks: Sequence[dict]) -> List[dict]:
    """Join a block holding only "Figure" with the block to its right on the
    same row ("3. Overview of ..."), set apart by a font change."""
    work = [dict(b, orig=[i]) for i, b in enumerate(blocks)]
    drop = set()
    for i, b in enumerate(work):
        if i in drop or not _LABEL_WORD_RE.match(b["text"].strip()):
            continue
        fs = max(b["fontsize"], 1.0)
        bb = _box(b)
        for j, c in enumerate(work):
            if j == i or j in drop:
                continue
            cb = _box(c)
            if (abs(cb[1] - bb[1]) < 0.5 * fs and -0.3 * fs <= cb[0] - bb[2] <= 1.5 * fs
                    and re.match(r"^\s*(S?\d+[A-Za-z]?|[IVX]{1,4})\s*[.:|]", c["text"], re.I)):
                b["text"] = b["text"].strip() + " " + c["text"].strip()
                b["hpos"], b["vpos"] = min(bb[0], cb[0]), min(bb[1], cb[1])
                b["width"] = max(bb[2], cb[2]) - b["hpos"]
                b["height"] = max(bb[3], cb[3]) - b["vpos"]
                b["fontsize"] = c["fontsize"]
                b["bold"] = c["bold"]
                b["orig"] = b["orig"] + c["orig"]
                drop.add(j)
                break
    return [b for i, b in enumerate(work) if i not in drop]


def find_captions(blocks: Sequence[dict], regions: Sequence[dict],
                  words: Sequence[dict], body_size: float,
                  page_h: float = 0.0, allow_unlabeled: bool = True) -> List[dict]:
    """Find the captions of one page.

    Returns dicts ``{"kind": "figure"|"table", "label": str|None, "text": str,
    "blocks": [indices into blocks], "source": "label"|"geometry"}`` in the
    order of the first block of each caption in ``blocks``.  Several captions
    can share one block when a block holds a row of labeled captions.
    """
    if not blocks:
        return []
    body_size = body_size_of(blocks, body_size)
    if body_size <= 0:
        return []
    work = _merge_label_words(blocks)
    n = len(work)
    boxes = [_box(b) for b in work]
    regs = [r for r in regions if not _region_is_panel(r, work, body_size)]
    for r in regs:
        r["table"] = _is_table_like(r, words)
    # a vector figure needs a real cluster; a few rules are decoration
    figure_regs = [r for r in regs
                   if r["kind"] == "image" or r["shapes"] >= MIN_FIGURE_SHAPES or r["table"]]

    def inside_region(i) -> bool:
        a = max(_area(boxes[i]), 1e-6)
        return any(_inter(boxes[i], r["box"]) / a >= INSIDE_FRACTION for r in regs)

    used = set()
    caps: List[dict] = []

    def grow(start: int, first_text: Optional[str] = None) -> List[int]:
        chain = [start]
        label_only = len((first_text or work[start]["text"]).strip()) <= 16
        sfs = max(work[start]["fontsize"], 1.0)
        at_body = work[start]["fontsize"] >= 0.98 * body_size
        gap_lim = (GROW_GAP_BODY if at_body else GROW_GAP) * sfs
        while len(chain) < 12:
            lb = boxes[chain[-1]]
            best = None
            for j in range(n):
                if j in used or j in chain or work[j].get("fig"):
                    continue
                b = work[j]
                lab = match_label(b["text"])
                if lab and lab["has_sep"]:
                    continue
                bb = boxes[j]
                gap = bb[1] - lb[3]
                if gap < -0.3 * sfs or gap > gap_lim:
                    continue
                tol = 0.3 if (label_only and len(chain) == 1) else SIZE_TOL
                if abs(b["fontsize"] - work[start]["fontsize"]) > tol * work[start]["fontsize"]:
                    continue
                cb = (min(boxes[k][0] for k in chain), lb[1], max(boxes[k][2] for k in chain), lb[3])
                ov = _overlap_1d(bb[0], bb[2], cb[0], cb[2]) / max(min(bb[2] - bb[0], cb[2] - cb[0]), 1e-6)
                if ov < 0.6 or abs(bb[0] - cb[0]) > 3 * sfs:
                    continue
                if (b["bold"] and len(b["text"]) < 40 and not work[start]["bold"]
                        and not label_only):
                    continue
                if best is None or gap < best[0]:
                    best = (gap, j)
            if best is None:
                break
            chain.append(best[1])
            label_only = False
        return chain

    def flows_into_text(chain, side, fs) -> bool:
        """True when body-size text continues on the side of the chain that
        faces away from the region: the block is one paragraph of a text flow,
        not a caption."""
        cb = (min(boxes[k][0] for k in chain), min(boxes[k][1] for k in chain),
              max(boxes[k][2] for k in chain), max(boxes[k][3] for k in chain))
        for j in range(n):
            if j in chain or work[j].get("fig"):
                continue
            c = work[j]
            if c["bold"] or c["fontsize"] > BODY_RATIO * body_size:
                # a heading right above: this is the first paragraph of a section
                hb = boxes[j]
                if (side != "above" and 0 <= cb[1] - hb[3] <= 2 * fs
                        and _overlap_1d(hb[0], hb[2], cb[0], cb[2]) > 0
                        and (c["fontsize"] > 1.15 * body_size or c["bold"])
                        and len(c["text"]) < 120):
                    return True
                continue
            if abs(c["fontsize"] - work[chain[0]]["fontsize"]) > SIZE_TOL * work[chain[0]]["fontsize"]:
                continue
            if len(c["text"].strip()) < 20:
                continue
            bb = boxes[j]
            if _overlap_1d(bb[0], bb[2], cb[0], cb[2]) < 0.5 * min(bb[2] - bb[0], cb[2] - cb[0]):
                continue
            below = bb[1] - cb[3]
            above = cb[1] - bb[3]
            lim = 2.0 * fs
            if side in ("below", "right", "left") and -0.3 * fs <= below <= lim:
                return True
            if side in ("above", "right", "left") and -0.3 * fs <= above <= lim:
                return True
        return False

    def is_table_cell(i, fs) -> bool:
        """A short cell sits just left of the block on the same row."""
        for j in range(n):
            if j == i or work[j].get("fig"):
                continue
            c = boxes[j]
            b = boxes[i]
            if (len(work[j]["text"].strip()) <= 30 and 0 <= b[0] - c[2] <= 8 * fs
                    and _overlap_1d(b[1], b[3], c[1], c[3]) >= 0.5 * min(b[3] - b[1], c[3] - c[1])):
                return True
        return False

    def figure_span(r, fs):
        """Horizontal extent of the figure: the region with the tiles beside
        it that share its rows (a figure made of several images)."""
        x0, x1 = r["box"][0], r["box"][2]
        grown = True
        while grown:
            grown = False
            for o in figure_regs:
                b = o["box"]
                if (_overlap_1d(b[1], b[3], r["box"][1], r["box"][3])
                        >= 0.5 * min(b[3] - b[1], r["box"][3] - r["box"][1])
                        and b[0] <= x1 + 2 * fs and b[2] >= x0 - 2 * fs
                        and (b[0] < x0 or b[2] > x1)):
                    x0, x1 = min(x0, b[0]), max(x1, b[2])
                    grown = True
        return x0, x1

    def orig_of(chain) -> List[int]:
        return [o for k in chain for o in work[k]["orig"]]

    def emit(chain, text, kind, label, source):
        text = re.sub(r"\s+", " ", text).strip()
        used.update(chain)
        caps.append({"kind": kind, "label": label, "text": text,
                     "blocks": orig_of(chain), "source": source})

    # 1. labeled captions
    for i in range(n):
        b = work[i]
        if i in used or b.get("fig"):
            continue
        lab = match_label(b["text"])
        if not lab or b["fontsize"] > LABEL_MAX_RATIO * body_size:
            continue
        fs = max(b["fontsize"], 1.0)
        near = any(_adjacent(boxes[i], r["box"], fs) for r in regs)
        rest = b["text"][lab["end"]:].strip()
        if not lab["has_sep"] and (not near or not rest):
            continue
        parts = split_inline_labels(b["text"])
        last_chain = grow(i, parts[-1])
        for k, part in enumerate(parts):
            pl = match_label(part) or lab
            label = part[:pl["end"]].strip() if pl else None
            if k < len(parts) - 1:
                emit([i], part, pl["kind"], label, "label")
            else:
                text = " ".join([part] + [work[c]["text"].strip() for c in last_chain[1:]])
                emit(last_chain, text, pl["kind"], label, "label")

    # 2. unlabeled captions next to a region
    if allow_unlabeled:
        for i in range(n):
            if i in used:
                continue
            b = work[i]
            fs = b["fontsize"]
            if b.get("fig") or fs <= 0 or b["bold"] and len(b["text"]) < 80:
                continue
            ratio = fs / body_size
            if ratio > BODY_RATIO:
                continue
            if page_h and (boxes[i][1] > FOOTER_FRACTION * page_h
                           or boxes[i][3] < BANNER_FRACTION * page_h):
                continue
            if _NOT_CAPTION_RE.search(b["text"]) or inside_region(i):
                continue
            hit = None
            for r in figure_regs:
                adj = _adjacent(boxes[i], r["box"], fs)
                if adj and (hit is None or adj[1] < hit[0]):
                    hit = (adj[1], r, adj[0])
            if hit is None:
                continue
            gap, r, side = hit
            tight = gap <= TIGHT_GAP * fs
            if r["kind"] == "image" and tight:
                min_words = MIN_SHORT_WORDS
            else:
                min_words = MIN_WORDS
            if not _looks_like_sentence(b["text"], min_words):
                continue
            if ratio >= SMALL_RATIO:
                # set at body size: only a short, tight block qualifies
                if side == "above" or not tight or r["table"]:
                    continue
                if boxes[i][3] - boxes[i][1] > BODY_MAX_LINES * 1.3 * fs:
                    continue
                # a caption does not run wider than the figure it labels;
                # running text spans the column and is wider than the figure
                if side in ("below", "above"):
                    x0, x1 = figure_span(r, fs)
                    if (boxes[i][2] - boxes[i][0]) > BODY_WIDTH_RATIO * (x1 - x0):
                        continue
            if re.match(r"^\s*[\u2022\u25aa\u25cf\u00b7\uf0b7*-]\s", b["text"]):
                continue
            if r["kind"] != "image" and is_table_cell(i, fs):
                continue
            chain = grow(i)
            if ratio >= SMALL_RATIO and flows_into_text(chain, side, fs):
                continue
            emit(chain, " ".join(work[c]["text"].strip() for c in chain),
                 "table" if r["table"] else "figure", None, "geometry")

    caps.sort(key=lambda c: c["blocks"][0])
    return caps


# ---------------------------------------------------------------------------
# merging with the model output
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def _tokens(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def strip_label(text: str) -> str:
    """The caption without its printed "Figure N." label."""
    lab = match_label(text)
    if lab and lab["has_sep"]:
        return text[lab["end"]:].strip()
    return text.strip()


def remove_caption_spans(text: str, captions: Sequence[str], threshold: float = 0.9) -> str:
    """Remove copies of the given captions from ``text``.

    A copy is the caption (with or without its label) written out in full,
    differing at most in white space, or a run of words of about the same
    length that matches the caption word for word at ``threshold`` or better.
    Anything shorter or looser stays.  Each removal leaves one space.
    """
    import difflib

    for cap in captions:
        for variant in dict.fromkeys([cap, strip_label(cap)]):
            cwords = _tokens(variant)
            if len(cwords) < 4:
                continue
            pat = r"\s+".join(re.escape(w) for w in variant.split())
            text, n = re.subn(pat, " ", text)
            if n:
                break
            # near-exact: slide a window over the words of the text
            matches = list(re.finditer(r"\S+", text))
            twords = [(_tokens(m.group(0)) or [""])[0] for m in matches]
            m_len = len(cwords)
            best = None
            for k, w in enumerate(twords):
                if w != cwords[0]:
                    continue
                for span in range(max(m_len - 3, 3), m_len + 4):
                    if k + span > len(twords):
                        break
                    r = difflib.SequenceMatcher(None, cwords, twords[k:k + span],
                                                autojunk=False).ratio()
                    if r >= threshold and (best is None or r > best[0]):
                        best = (r, k, span)
                if best:
                    break
            if best:
                _, k, span = best
                text = text[:matches[k].start()] + " " + text[matches[k + span - 1].end():]
                break
    return text


def _containment(a: Sequence[str], b: Sequence[str]) -> float:
    """Share of the distinct tokens of ``a`` that also occur in ``b``."""
    sa = set(a)
    return len(sa & set(b)) / len(sa) if sa else 0.0


def merge_captions(det: Sequence[dict], model_figures: Sequence[str],
                   model_tables: Sequence[str], raw_text: str) -> Dict[str, List[str]]:
    """Combine deterministic captions with the model's.

    Deterministic captions win and keep reading order.  A model caption is kept
    only when it is grounded in the text the model was given (at least 80
    percent of its distinct words occur there) and not already covered by a
    deterministic or earlier caption (60 percent of its words inside one, or
    that caption mostly inside it).  Returns ``{"figure": [...], "table": [...]}``.
    """
    out = {"figure": [c["text"] for c in det if c["kind"] == "figure"],
           "table": [c["text"] for c in det if c["kind"] == "table"]}
    seen = [_tokens(c["text"]) for c in det]
    raw_tokens = set(_tokens(raw_text))
    for kind, extra in (("figure", model_figures), ("table", model_tables)):
        for cap in extra:
            toks = _tokens(cap)
            if len(toks) < 3:
                continue
            if sum(1 for t in set(toks) if t in raw_tokens) < 0.8 * len(set(toks)):
                continue
            if any(_containment(toks, d) >= 0.6 or _containment(d, toks) >= 0.8
                   for d in seen if d):
                continue
            out[kind].append(cap)
            seen.append(toks)
    return out
