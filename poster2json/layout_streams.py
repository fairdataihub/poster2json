"""Stream-order text layout for pdfplumber pages.

Glyphs become words, words become lines and lines become blocks, all in
content-stream order and in one pass each.  The blocks are then sorted top
down and re-ordered by a column aware band rule.  There is no page-wide
statistic anywhere: every tolerance is a fraction of the font size of the
text it is applied to, except one small absolute baseline tolerance.

Public entry point::

    blocks = ordered_blocks(page, chars=None, repair_interleave=True, info=None)

``page`` is a pdfplumber page (anything with ``chars``, ``bbox`` or
``width``/``height``).  ``chars`` may be passed to replace ``page.chars``.
The result is a list of :class:`Block` in reading order.  Each block holds
:class:`Line` objects with ``text``, ``bbox``, dominant ``size`` and a
``bold`` flag.

Everything is iterative; bad glyphs (NaN, infinite or missing numbers) are
skipped and act as word boundaries, they never raise.
"""

from __future__ import annotations

import math
import re
import unicodedata
from bisect import bisect_right
from typing import Dict, List, Optional, Sequence, Tuple

__all__ = ["Word", "Line", "Block", "ordered_blocks"]

# ---------------------------------------------------------------------------
# Tolerances.  All are fractions of a font size unless the name says "PT".
# ---------------------------------------------------------------------------
_PAGE_SLOP_PT = 2.0          # glyph origin may sit this far outside the page
_BASELINE_TOL_PT = 1.0       # the only absolute number: word level baseline shift
_WORD_GAP = 0.10             # gap above this (fraction of fs) is a visible space
_BACKSTEP = 0.30             # origin this far behind the previous end restarts a word
_COINC_ALONG = 0.10          # overprint tolerances, fraction of fs
_COINC_ACROSS = 0.20
_ANGLE_TOL = 3.0             # degrees: words/lines of one direction
_SNAP_DEG = 1.0              # snap text direction to a right angle within this
_ROW_FRAC = 0.5              # same visual row: baseline within this times size
_FAR_FRAC = 1.5              # next word may start this far (times L) past the end
_SIZE_DIFF = 0.05            # blocks: relative size difference limit
_LEADING = 1.5               # blocks: baseline step limit, times previous size
_TITLE_JUMP = 0.3            # first line stands alone when the next starts this far right
_ACCENT_REACH = 0.8          # an accent belongs to a base within this times fs
_HOP_CAP = 512               # bound on the backwards scan of the band rule
_SUPERSCRIPT_SIZE = 0.97     # a script word is smaller than this times L
_HEADING_MAX_LINES = 3       # a heading is at most this many wholly bold lines
_HEADING_BOLD = 0.95         # a line is wholly bold from this share of its characters
_HEADING_NEXT_ALNUM = 3      # the regular line after a heading has at least this many letters or digits
_SCRIPT_REACH = 0.5          # a superscript top may pass the line top by this times L

# Interleaved stream repair
_WIDE_LINE_FRAC = 0.6        # lines wider than this fraction of the page are barriers
_LANE_OVERLAP = 0.5
_MIN_LANE_LINES = 3
_MAX_MEAN_RUN = 2.0
_SHORT_LINE_L = 8.0
_STEP_OK_FRAC = 0.7

_CIDRE = "(cid:"
_CONTACT = re.compile(r"@\w|orcid|https?://|www\.", re.I)
_CLOSERS = frozenset(",;.:)]}")

_UNIT = {0.0: (1.0, 0.0), 90.0: (0.0, 1.0), 180.0: (-1.0, 0.0), 270.0: (0.0, -1.0)}

# Marker for a real space glyph in the glyph list.  ``None`` marks a dropped
# or invalid glyph (a word boundary that is not a printed space).
_SPACE = object()


# ---------------------------------------------------------------------------
# Output objects
# ---------------------------------------------------------------------------
class Word:
    """A word of a line with its page box."""

    __slots__ = ("text", "x0", "y0", "x1", "y1", "size", "bold")


class Line:
    """A text line: ``text``, ``bbox``, dominant ``size``, ``bold`` flag and ``words``."""

    __slots__ = ("text", "x0", "y0", "x1", "y1", "size", "bold", "th", "c", "s",
                 "v", "px", "py", "up", "dn", "vt", "vb", "us", "ue", "nchar", "nbold",
                 "idx", "nwords", "words", "maxsize")

    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Line({self.text!r})"


class Block:
    """A block of consecutive same-size lines of one direction."""

    __slots__ = ("lines", "x0", "y0", "x1", "y1", "size", "bold", "first_line_height",
                 "direction", "seq")

    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)

    @property
    def text(self) -> str:
        return "\n".join(ln.text for ln in self.lines)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Block({self.text[:40]!r}, {len(self.lines)} lines)"


# ---------------------------------------------------------------------------
# Internal records
# ---------------------------------------------------------------------------
class _Glyph:
    __slots__ = ("ch", "fs", "ox", "oy", "ex", "ey", "th", "c", "s", "up", "dn",
                 "bx0", "by0", "bx1", "by1", "bold", "font", "acc", "ascii_acc", "accd",
                 "key", "off")


class _Word:
    __slots__ = ("chars", "th", "c", "s", "v", "fs", "ox", "oy", "ex", "ey", "lx", "ly",
                 "ue", "up", "dn", "bx0", "by0", "bx1", "by1", "sp", "nb", "n")

    @property
    def text(self) -> str:
        return "".join(self.chars)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _ang_close(a: float, b: float, tol: float = _ANGLE_TOL) -> bool:
    d = (a - b + 180.0) % 360.0 - 180.0
    return -tol <= d <= tol


_BOLD_PREFIX = re.compile(r"^[A-Z]{6}\+")
_BOLD_CACHE: Dict[str, bool] = {}


def _is_bold(fontname) -> bool:
    key = fontname if isinstance(fontname, str) else ""
    hit = _BOLD_CACHE.get(key)
    if hit is not None:
        return hit
    name = _BOLD_PREFIX.sub("", key).lower()
    res = ("bold" in name or "heavy" in name or "black" in name
           or name.endswith("-bd") or name.endswith(",bd") or name.endswith("-bdit"))
    if len(_BOLD_CACHE) < 4096:
        _BOLD_CACHE[key] = res
    return res


# Accents.  A spacing accent is a modifier symbol whose compatibility
# decomposition (NFKD of the glyph itself) is a space followed by a combining
# mark.  A few modifier letters have no decomposition at all and get an explicit combining form.
_NO_DECOMP_ACCENTS = {"\u02c6": "\u0302", "\u02c7": "\u030c"}
_ASCII_ACCENTS = {"^": "\u0302", "`": "\u0300", "~": "\u0303"}
_ACCENT_CACHE: Dict[str, Optional[Tuple[str, bool]]] = {}


def _accent_form(ch: str) -> Optional[Tuple[str, bool]]:
    """(combining mark, is_ascii_lookalike) when ``ch`` is an accent glyph."""
    if ch in _ACCENT_CACHE:
        return _ACCENT_CACHE[ch]
    res: Optional[Tuple[str, bool]] = None
    if len(ch) == 1:
        if ch in _ASCII_ACCENTS:
            res = (_ASCII_ACCENTS[ch], True)
        elif unicodedata.category(ch) == "Mn":
            res = (ch, False)
        elif ch in _NO_DECOMP_ACCENTS:
            res = (_NO_DECOMP_ACCENTS[ch], False)
        elif unicodedata.category(ch) == "Sk":
            d = unicodedata.normalize("NFKD", ch)
            if len(d) == 2 and d[0] == " " and unicodedata.category(d[1]) == "Mn":
                res = (d[1], False)
    if len(_ACCENT_CACHE) < 4096:
        _ACCENT_CACHE[ch] = res
    return res


def _compose(base: str, mark: str) -> str:
    if base == "\u0131":
        base = "i"
    out = unicodedata.normalize("NFC", base + mark)
    return out if len(out) == 1 else base + mark


def _finite_sum(*vals: float) -> bool:
    s = 0.0
    for v in vals:
        s += v
    return s - s == 0.0


def _num(v) -> Optional[float]:
    """float(v), or None for missing or non numeric values (NaN is returned)."""
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError, OverflowError):
        return None


# ---------------------------------------------------------------------------
# Page frame
# ---------------------------------------------------------------------------
def _page_frame(page) -> Tuple[float, float, float, float, float, float, float]:
    """(origin x, origin y, width, height, root height, mediabox x0, mediabox top).

    The first two are the page box origin that is subtracted from every
    coordinate.  The last three convert the text matrix (kept by pdfminer
    relative to the media box, y up) to the pdfplumber top-left frame.
    """
    bbox = getattr(page, "bbox", None)
    ox = oy = 0.0
    w = _num(getattr(page, "width", None))
    h = _num(getattr(page, "height", None))
    try:
        if bbox is not None and len(bbox) == 4:
            b = [float(x) for x in bbox]
            if _finite_sum(*b):
                ox, oy = b[0], b[1]
                w, h = b[2] - b[0], b[3] - b[1]
    except (TypeError, ValueError):
        pass
    if w is None or h is None or not _finite_sum(w, h):
        w, h = 0.0, 0.0
    root = getattr(page, "root_page", None) or page
    mbx, mby = ox, oy
    root_h = h
    try:
        mb = getattr(root, "mediabox", None)
        if mb is not None and len(mb) == 4:
            m = [float(x) for x in mb]
            if _finite_sum(*m):
                mbx, mby = m[0], m[1]
        rh = _num(getattr(root, "height", None))
        if rh is not None and _finite_sum(rh) and rh > 0:
            root_h = rh
    except (TypeError, ValueError):
        pass
    return ox, oy, w, h, root_h, mbx, mby


# ---------------------------------------------------------------------------
# Glyph preparation
# ---------------------------------------------------------------------------
def _direction(a: float, b: float, c: float, d: float):
    """(theta degrees in the top-left frame, cos, sin) or None when degenerate."""
    if a * a + b * b < 1e-18:
        a, b = d, -c           # reading direction is perpendicular to the up vector
        if a * a + b * b < 1e-18:
            return None
    th = math.degrees(math.atan2(-b, a)) % 360.0
    for snap in (0.0, 90.0, 180.0, 270.0, 360.0):
        if abs(th - snap) <= _SNAP_DEG:
            th = 0.0 if snap == 360.0 else snap
            cs = _UNIT[th]
            return th, cs[0], cs[1]
    r = math.radians(th)
    return th, math.cos(r), math.sin(r)


def _across_from_box(th, c, s, x0, y0, x1, y1):
    """(min v, max v) of a page box in the frame (c, s)."""
    if th == 0.0:
        return y0, y1
    if th == 90.0:
        return -x1, -x0
    if th == 180.0:
        return -y1, -y0
    if th == 270.0:
        return x0, x1
    vs = (-x0 * s + y0 * c, -x1 * s + y0 * c, -x0 * s + y1 * c, -x1 * s + y1 * c)
    return min(vs), max(vs)


def _prepare(page, chars, frame, info) -> list:
    """Glyph records in stream order; ``None`` and ``_SPACE`` are boundaries."""
    ox0, oy0, pw, ph, root_h, mbx, mby = frame
    items: list = []
    use_box_origin = _frame_is_unreliable(chars, frame)
    rise_groups: Dict[str, Dict[float, int]] = {}
    risers: list = []
    dropped = 0
    for ch in chars:
        try:
            g = _make_glyph(ch, ox0, oy0, pw, ph, root_h, mbx, mby, use_box_origin)
        except Exception:                                   # noqa: BLE001 - never raise
            g = None
        if g is None or g is _SPACE:
            if g is None:
                dropped += 1
            items.append(g)
            continue
        if g.key is not None:
            d = rise_groups.setdefault(g.font, {})
            d[g.key] = d.get(g.key, 0) + 1
            risers.append(g)
        items.append(g)
    # Text rise (Ts) moves the glyph box but not the matrix origin.  The box
    # offset from the baseline is constant per font, so a deviation from the
    # font's usual offset is a rise.
    if risers:
        mode = {}
        for font, d in rise_groups.items():
            best = max(d.items(), key=lambda kv: (kv[1], -abs(kv[0])))
            mode[font] = best[0]
        for g in risers:
            r = (mode[g.font] - g.off) * g.fs
            if abs(r) > max(0.3, 0.04 * g.fs):
                g.ox += r * g.s
                g.oy -= r * g.c
                g.ex += r * g.s
                g.ey -= r * g.c
                g.up -= r
                g.dn += r
    if info is not None:
        info["dropped_glyphs"] = dropped
    return items


def _frame_is_unreliable(chars, frame) -> bool:
    """True when matrix origins do not sit on the glyph boxes (odd producer or
    a page object that does not follow the pdfplumber frame)."""
    ox0, oy0, pw, ph, root_h, mbx, mby = frame
    ok = bad = 0
    for ch in chars:
        if ok + bad >= 200:
            break
        try:
            m = ch.get("matrix")
            if m is None or len(m) != 6:
                continue
            a, b, c, d, e, f = (float(v) for v in m)
            size = float(ch["size"])
            top = float(ch["top"]) - oy0
            bot = float(ch["bottom"]) - oy0
            if not (_finite_sum(a, b, c, d, e, f, size, top, bot) and size > 0):
                continue
            if abs(b) > 1e-6 * abs(a) or abs(c) > 1e-6 * abs(d) or a <= 0 or d <= 0:
                continue
            yb = (root_h - f) + mby - oy0
        except Exception:                                   # noqa: BLE001
            continue
        if top - 0.5 * size <= yb <= bot + 0.5 * size:
            ok += 1
        else:
            bad += 1
    return (ok + bad) >= 5 and bad > ok


def _make_glyph(ch, ox0, oy0, pw, ph, root_h, mbx, mby, use_box_origin):
    text = ch.get("text")
    if not isinstance(text, str) or not text:
        return None
    if text.startswith(_CIDRE):
        return None
    if text.isspace():
        return _SPACE

    x0 = ch.get("x0")
    x1 = ch.get("x1")
    top = ch.get("top")
    bot = ch.get("bottom")
    boxv = (x0, x1, top, bot)
    have_box = all(v is not None for v in boxv)
    if not have_box and any(v is not None for v in boxv):
        return None                                         # partial box: invalid
    if have_box:
        x0, x1, top, bot = (_num(v) for v in boxv)
        if x0 is None or x1 is None or top is None or bot is None:
            return None
        if not _finite_sum(x0, x1, top, bot):
            return None
        x0 -= ox0
        x1 -= ox0
        top -= oy0
        bot -= oy0

    mat = ch.get("matrix")
    have_mat = mat is not None
    a = b = c = d = e = f = 0.0
    if have_mat:
        try:
            if len(mat) != 6:
                return None
            vals = [_num(v) for v in mat]
        except TypeError:
            return None
        if any(v is None for v in vals):
            return None
        a, b, c, d, e, f = vals
        if not _finite_sum(a, b, c, d, e, f):
            return None
    elif not have_box:
        return None

    size = ch.get("size")
    fs = None
    if size is not None:
        fs = _num(size)
        if fs is None or not _finite_sum(fs):
            return None
    if fs is None or fs <= 0:
        if have_box and bot - top > 0:
            fs = bot - top
        elif have_mat and math.hypot(c, d) > 0:
            fs = math.hypot(c, d)
        else:
            return None
    if fs <= 0:
        return None

    if not have_mat:
        a, d = 1.0, 1.0                                     # synthesize upright text
        b = c = 0.0
    dr = _direction(a, b, c, d)
    if dr is None:
        return None
    th, cs, sn = dr

    # pdfminer reports the page-box height as the size of a glyph.  For text
    # reading top to bottom or bottom to top that height is the glyph advance,
    # so every letter gets a different size.  The box width is the font size.
    if have_box and (th == 90.0 or th == 270.0) and x1 - x0 > 0:
        if abs((x1 - x0) - fs) > 0.05 * max(x1 - x0, fs):
            fs = x1 - x0

    # Origin in the normalized top-left frame.
    if have_mat and not use_box_origin:
        px = e + mbx - ox0
        py = (root_h - f) + mby - oy0
    elif have_box:
        px, py = _origin_from_box(th, x0, x1, top, bot, fs)
    else:
        return None
    if not (-_PAGE_SLOP_PT <= px <= pw + _PAGE_SLOP_PT
            and -_PAGE_SLOP_PT <= py <= ph + _PAGE_SLOP_PT):
        return None                                         # hidden text

    # Advance along the reading direction.
    scale = math.hypot(a, b) if have_mat else 1.0
    adv = _num(ch.get("adv"))
    sheared = False
    if have_mat:
        cd = math.hypot(c, d)
        if cd > 0 and abs(a * c + b * d) > 0.05 * scale * cd:
            sheared = True
    if adv is not None and _finite_sum(adv) and adv >= 0 and have_mat:
        length = adv * scale
        if length <= 0 and have_box:
            length = _box_advance(th, cs, sn, x0, x1, top, bot, fs)
    elif have_box:
        length = _box_advance(th, cs, sn, x0, x1, top, bot, fs)
        if sheared and abs(d) > 0:
            length = max(0.0, length - abs(c / d) * fs)
    else:
        length = 0.5 * fs

    # Box and across offsets.
    if have_box and not sheared:
        bx0, by0, bx1, by1 = x0, top, x1, bot
        vt, vb = _across_from_box(th, cs, sn, bx0, by0, bx1, by1)
        v0 = -px * sn + py * cs
        up = v0 - vt
        dn = vb - v0
        if up + dn <= 0.0:
            up, dn = 0.75 * fs, 0.25 * fs
            bx0, by0, bx1, by1 = _synth_box(px, py, cs, sn, length, up, dn)
    else:
        up, dn = 0.75 * fs, 0.25 * fs
        bx0, by0, bx1, by1 = _synth_box(px, py, cs, sn, length, up, dn)

    g = _Glyph()
    g.ch = text
    g.fs = fs
    g.ox = px
    g.oy = py
    g.ex = px + length * cs
    g.ey = py + length * sn
    g.th = th
    g.c = cs
    g.s = sn
    g.up = up
    g.dn = dn
    g.bx0 = bx0
    g.by0 = by0
    g.bx1 = bx1
    g.by1 = by1
    font = ch.get("fontname")
    g.font = font if isinstance(font, str) else ""
    g.bold = _is_bold(g.font)
    acc = _accent_form(text)
    g.acc = acc[0] if acc else None
    g.ascii_acc = bool(acc and acc[1])
    g.accd = False
    if have_box and not sheared and have_mat and not use_box_origin:
        g.key = round(dn / fs, 3)
        g.off = dn / fs
    else:
        g.key = None
        g.off = 0.0
    return g


def _origin_from_box(th, x0, x1, top, bot, fs):
    """Origin estimated from a glyph box (ascent 0.75, descent 0.25)."""
    if th == 0.0:
        return x0, bot - 0.25 * fs
    if th == 90.0:
        return x0 + 0.25 * fs, top
    if th == 180.0:
        return x1, top + 0.25 * fs
    if th == 270.0:
        return x1 - 0.25 * fs, bot
    return x0, bot - 0.25 * fs


def _box_advance(th, cs, sn, x0, x1, top, bot, fs):
    if th == 0.0 or th == 180.0:
        return max(0.0, x1 - x0)
    if th == 90.0 or th == 270.0:
        return max(0.0, bot - top)
    w = x1 - x0
    h = bot - top
    return max(0.0, w * abs(cs) + h * abs(sn) - 2.0 * fs * abs(sn) * abs(cs))


def _synth_box(px, py, cs, sn, length, up, dn):
    """Page box of a glyph rectangle given by origin, advance and offsets."""
    pts = []
    for u in (0.0, length):
        for v in (-up, dn):
            pts.append((px + u * cs - v * sn, py + u * sn + v * cs))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


# ---------------------------------------------------------------------------
# Overprints
# ---------------------------------------------------------------------------
_LEVEL_CELL: Dict[int, float] = {}


def _drop_overprints(items: list) -> list:
    """Remove glyphs that repeat an earlier glyph at (almost) the same origin."""
    grid: Dict[tuple, list] = {}
    out: list = []
    log2 = math.log2
    floor = math.floor
    for g in items:
        if g is None or g is _SPACE:
            out.append(g)
            continue
        fs = g.fs
        lv = log2(fs) * 2.0 + 0.5
        k = int(floor(lv))
        frac = lv - k
        levels = (k,)
        if frac < 0.06:
            levels = (k, k - 1)
        elif frac > 0.94:
            levels = (k, k + 1)
        dup = False
        ch = g.ch
        gx, gy = g.ox, g.oy
        for kk in levels:
            cell = _LEVEL_CELL.get(kk)
            if cell is None:
                cell = 0.5 * 2.0 ** (kk / 2.0)
                _LEVEL_CELL[kk] = cell
            ix = int(floor(gx / cell))
            iy = int(floor(gy / cell))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    lst = grid.get((kk, ix + dx, iy + dy))
                    if not lst:
                        continue
                    for h in lst:
                        if h.ch != ch or h.font != g.font:
                            continue
                        if abs(h.fs - fs) > 0.02 * max(h.fs, fs):
                            continue
                        if not _ang_close(h.th, g.th, 1.0):
                            continue
                        rx = gx - h.ox
                        ry = gy - h.oy
                        du = rx * h.c + ry * h.s
                        dv = -rx * h.s + ry * h.c
                        if abs(du) <= _COINC_ALONG * fs and abs(dv) <= _COINC_ACROSS * fs:
                            dup = True
                            break
                    if dup:
                        break
                if dup:
                    break
            if dup:
                break
        if dup:
            continue
        cell = _LEVEL_CELL.get(k)
        if cell is None:
            cell = 0.5 * 2.0 ** (k / 2.0)
            _LEVEL_CELL[k] = cell
        key = (k, int(floor(gx / cell)), int(floor(gy / cell)))
        lst = grid.get(key)
        if lst is None:
            grid[key] = [g]
        else:
            lst.append(g)
        out.append(g)
    return out


# ---------------------------------------------------------------------------
# Accents
# ---------------------------------------------------------------------------
def _is_base(h) -> bool:
    return (isinstance(h, _Glyph) and h.acc is None and len(h.ch) == 1
            and (h.ch.isalpha() or h.ch == "\u0131"))


def _accent_dist(a: _Glyph, h: _Glyph) -> Optional[float]:
    """Horizontal distance between accent a and base h along h's reading
    direction, or None when a cannot belong to h."""
    if not _ang_close(a.th, h.th):
        return None
    c, s = h.c, h.s
    ua0 = a.ox * c + a.oy * s
    ua1 = a.ex * c + a.ey * s
    if ua1 < ua0:
        ua0, ua1 = ua1, ua0
    uh0 = h.ox * c + h.oy * s
    uh1 = h.ex * c + h.ey * s
    if uh1 < uh0:
        uh0, uh1 = uh1, uh0
    va = -a.ox * s + a.oy * c
    vh = -h.ox * s + h.oy * c
    if abs(va - vh) > h.fs:
        return None
    gap = max(0.0, ua0 - uh1, uh0 - ua1)
    if gap > _ACCENT_REACH * h.fs:
        return None
    if a.ascii_acc:
        width = ua1 - ua0
        overlap = min(ua1, uh1) - max(ua0, uh0)
        if width <= 0 or overlap <= width / 3.0:
            return None
    return abs((ua0 + ua1) / 2.0 - (uh0 + uh1) / 2.0)


def _merge_accents(items: list) -> list:
    """Fold spacing accents and combining marks into the base letter."""
    out: list = []
    n = len(items)
    i = 0
    while i < n:
        g = items[i]
        if g is None or g is _SPACE or g.acc is None:
            out.append(g)
            i += 1
            continue
        prev = out[-1] if out else None
        j = i + 1
        while j < n and isinstance(items[j], _Glyph) and items[j].acc is not None:
            j += 1
        nxt = items[j] if j < n else None
        dp = _accent_dist(g, prev) if _is_base(prev) else None
        dn = _accent_dist(g, nxt) if _is_base(nxt) else None
        target = None
        if dp is not None and dn is not None:
            if g.ch and unicodedata.category(g.ch) == "Mn":
                target = prev
            else:
                target = nxt if dn <= dp else prev
        elif dp is not None:
            target = prev
        elif dn is not None:
            target = nxt
        if target is None:
            out.append(g)                                   # stands alone
        elif not target.accd:
            target.ch = _compose(target.ch, g.acc)
            target.accd = True
        # else: a second accent on the same base is ignored
        i += 1
    return out


# ---------------------------------------------------------------------------
# Glyphs to words
# ---------------------------------------------------------------------------
def _new_word(g: _Glyph) -> _Word:
    w = _Word()
    w.chars = [g.ch]
    w.th = g.th
    w.c = g.c
    w.s = g.s
    w.v = -g.ox * g.s + g.oy * g.c
    w.fs = g.fs
    w.ox = g.ox
    w.oy = g.oy
    w.ex = g.ex
    w.ey = g.ey
    w.lx = g.ox
    w.ly = g.oy
    w.ue = g.ex * g.c + g.ey * g.s
    w.up = g.up
    w.dn = g.dn
    w.bx0 = g.bx0
    w.by0 = g.by0
    w.bx1 = g.bx1
    w.by1 = g.by1
    w.sp = False
    w.n = len(g.ch)
    w.nb = w.n if g.bold else 0
    return w


def _build_words(items: list) -> List[_Word]:
    words: List[_Word] = []
    cur: Optional[_Word] = None
    for g in items:
        if g is _SPACE:
            if cur is not None:
                cur.sp = True
                cur = None
            elif words:
                words[-1].sp = True
            continue
        if g is None:                       # dropped or invalid glyph: word boundary
            if cur is not None:
                cur.sp = True
                cur = None
            elif words:
                words[-1].sp = True
            continue
        if cur is not None:
            if g.th != cur.th and not _ang_close(g.th, cur.th):
                cur = None
            else:
                cc = cur.c
                ss = cur.s
                u = g.ox * cc + g.oy * ss
                v = -g.ox * ss + g.oy * cc
                fs = cur.fs
                gap = u - cur.ue
                if gap > _WORD_GAP * fs:
                    cur.sp = True
                    cur = None
                elif gap < -_BACKSTEP * fs:
                    cur = None
                elif abs(v - cur.v) > _BASELINE_TOL_PT:
                    cur = None
                else:
                    rx = g.ox - cur.lx
                    ry = g.oy - cur.ly
                    du = rx * cc + ry * ss
                    dv = -rx * ss + ry * cc
                    if abs(du) <= _COINC_ALONG * fs and abs(dv) <= _COINC_ACROSS * fs:
                        cur = None
        if cur is None:
            cur = _new_word(g)
            words.append(cur)
            continue
        cur.chars.append(g.ch)
        cur.n += len(g.ch)
        if g.bold:
            cur.nb += len(g.ch)
        cur.ex = g.ex
        cur.ey = g.ey
        cur.lx = g.ox
        cur.ly = g.oy
        cur.ue = g.ex * cc + g.ey * ss
        if g.up > cur.up:
            cur.up = g.up
        if g.dn > cur.dn:
            cur.dn = g.dn
        if g.bx0 < cur.bx0:
            cur.bx0 = g.bx0
        if g.by0 < cur.by0:
            cur.by0 = g.by0
        if g.bx1 > cur.bx1:
            cur.bx1 = g.bx1
        if g.by1 > cur.by1:
            cur.by1 = g.by1
    return words


# ---------------------------------------------------------------------------
# Words to lines
# ---------------------------------------------------------------------------
def _heavy(pairs: List[Tuple[float, float]], prefer_large: bool = True) -> float:
    """Weighted median of (value, weight) pairs."""
    pairs = sorted(pairs, reverse=prefer_large)
    total = sum(w for _, w in pairs)
    half = total / 2.0
    acc = 0.0
    for val, w in pairs:
        acc += w
        if acc >= half:
            return val
    return pairs[-1][0]


def _dominant_baseline(vs: List[Tuple[float, float]]) -> float:
    """Baseline of the heaviest cluster of word baselines (weights n * size)."""
    vs = sorted(vs)
    best_w = -1.0
    best = vs[0][0]
    cluster: List[Tuple[float, float]] = []
    last = None
    for v, w in vs + [(None, 0.0)]:
        if v is None or (last is not None and v - last > _BASELINE_TOL_PT):
            if cluster:
                tw = sum(x for _, x in cluster)
                if tw > best_w:
                    best_w = tw
                    best = _heavy(cluster)
            cluster = []
        if v is not None:
            cluster.append((v, w))
            last = v
    return best


# ---------------------------------------------------------------------------
# Right to left words.  The content stream of most producers lists Hebrew and
# Arabic glyphs left to right as they are printed (visual order); the logical
# text is the reverse.
# ---------------------------------------------------------------------------
_MIRROR = str.maketrans("()[]{}<>", ")(][}{><")


def _rtl_classes(texts: List[str]) -> List[str]:
    """'R' for right to left words, 'L' for the rest.  A word without letters
    (digits, punctuation) between two right to left words belongs to them."""
    cls = []
    any_r = False
    for t in texts:
        r = l = 0
        for ch in t:
            b = unicodedata.bidirectional(ch)
            if b == "R" or b == "AL":
                r += 1
            elif b == "L":
                l += 1
        if r and r >= l:
            cls.append("R")
            any_r = True
        elif l:
            cls.append("L")
        else:
            cls.append("N")
    if not any_r:
        return ["L"] * len(texts)
    n = len(cls)
    out = list(cls)
    k = 0
    while k < n:
        if cls[k] != "N":
            k += 1
            continue
        j = k
        while j < n and cls[j] == "N":
            j += 1
        if k > 0 and j < n and cls[k - 1] == "R" and cls[j] == "R":
            for q in range(k, j):
                out[q] = "R"
        else:
            for q in range(k, j):
                out[q] = "L"
        k = j
    return out


def _rtl_text(text: str) -> str:
    """Logical order of a visually ordered right to left word.  Digit runs
    keep their order, combining marks stay behind their letter and paired
    brackets are mirrored."""
    clusters: List[str] = []
    for ch in text:
        if clusters and unicodedata.category(ch) == "Mn":
            clusters[-1] += ch
        elif (clusters and unicodedata.bidirectional(ch) in ("EN", "AN")
              and unicodedata.bidirectional(clusters[-1][-1]) in ("EN", "AN")):
            clusters[-1] += ch
        else:
            clusters.append(ch)
    return "".join(clusters[::-1]).translate(_MIRROR)



def _make_line(words: List[_Word], idx: int) -> Line:
    first = words[0]
    cc, ss = first.c, first.s
    rows = []
    for w in words:
        us = w.ox * cc + w.oy * ss
        ue = w.ex * cc + w.ey * ss
        if ue < us:
            us, ue = ue, us
        v = -w.ox * ss + w.oy * cc
        rows.append((us, ue, v))
    # weights n * size; ties go to the earlier word of the line
    v_dom = _dominant_baseline([(rows[k][2], words[k].n * words[k].fs - 1e-6 * k)
                                for k in range(len(words))])
    size = _heavy([(w.fs, float(w.n)) for w in words])
    # dominant extent: words standing on the dominant baseline
    dom_up = dom_dn = 0.0
    for k, w in enumerate(words):
        if abs(rows[k][2] - v_dom) <= _BASELINE_TOL_PT:
            dom_up = max(dom_up, w.up)
            dom_dn = max(dom_dn, w.dn)
    dom_top = v_dom - dom_up
    dom_bot = v_dom + dom_dn

    kinds = []                                  # +1 superscript, -1 subscript, 0 plain
    for k, w in enumerate(words):
        v = rows[k][2]
        kind = 0
        if w.fs < _SUPERSCRIPT_SIZE * size:
            # A raised number usually pokes above the cap height of the text it
            # follows, so its top may rise above the dominant extent by a
            # fraction of the line size (a symbol far above is not a script).
            if v < v_dom - _BASELINE_TOL_PT and v - w.up >= dom_top - _SCRIPT_REACH * size:
                kind = 1
            elif v > v_dom + _BASELINE_TOL_PT and v + w.dn <= dom_bot + _BASELINE_TOL_PT:
                kind = -1
        kinds.append(kind)

    # flags[k]: a space separates word k-1 and word k
    flags = [False] * len(words)
    for k in range(1, len(words)):
        space = words[k - 1].sp
        if not space and (kinds[k] == 1) != (kinds[k - 1] == 1):
            # "Name 1, Other": no space between a raised mark and closing punctuation
            space = not (kinds[k - 1] == 1 and words[k].chars[0] in _CLOSERS)
        flags[k] = space
    texts = [w.text for w in words]
    cls = _rtl_classes(texts)
    if "R" in cls:
        texts = [_rtl_text(t) if c == "R" else t for t, c in zip(texts, cls)]
    parts: List[str] = []
    k = 0
    while k < len(words):
        if k and flags[k]:
            parts.append(" ")
        if cls[k] == "R":
            j = k
            while j + 1 < len(words) and cls[j + 1] == "R":
                j += 1
            # the stream is in visual order: a run of right to left words reads
            # from its right end
            for q in range(j, k - 1, -1):
                parts.append(texts[q])
                if q > k and flags[q]:
                    parts.append(" ")
            k = j + 1
        else:
            parts.append(texts[k])
            k += 1

    ln = Line()
    ln.text = "".join(parts).strip()
    ln.x0 = min(w.bx0 for w in words)
    ln.y0 = min(w.by0 for w in words)
    ln.x1 = max(w.bx1 for w in words)
    ln.y1 = max(w.by1 for w in words)
    ln.size = size
    ln.nchar = sum(w.n for w in words)
    ln.nbold = sum(w.nb for w in words)
    ln.bold = ln.nbold * 2 >= ln.nchar and ln.nbold > 0
    ln.th = first.th
    ln.c = cc
    ln.s = ss
    ln.v = v_dom
    ln.us = min(r[0] for r in rows)
    ln.ue = max(r[1] for r in rows)
    ln.vt = min(rows[k][2] - words[k].up for k in range(len(words)))
    ln.vb = max(rows[k][2] + words[k].dn for k in range(len(words)))
    ln.up = v_dom - ln.vt
    ln.dn = ln.vb - v_dom
    ln.px = ln.us * cc - v_dom * ss
    ln.py = ln.us * ss + v_dom * cc
    ln.idx = idx
    ln.nwords = len(words)
    ln.maxsize = max(w.fs for w in words)
    out_words = []
    for w in words:
        ow = Word()
        ow.text = texts[len(out_words)]
        ow.x0, ow.y0, ow.x1, ow.y1 = w.bx0, w.by0, w.bx1, w.by1
        ow.size = w.fs
        ow.bold = w.nb * 2 >= w.n and w.nb > 0
        out_words.append(ow)
    ln.words = out_words
    return ln


def _build_lines(words: List[_Word]) -> List[Line]:
    lines: List[Line] = []
    cur: List[_Word] = []
    cc = ss = 0.0
    run_max = 0.0
    last_us = last_ue = last_v = 0.0
    for w in words:
        if cur:
            if w.th != cur[0].th and not _ang_close(w.th, cur[0].th):
                ok = False
            else:
                us = w.ox * cc + w.oy * ss
                ue = w.ex * cc + w.ey * ss
                v = -w.ox * ss + w.oy * cc
                if ue < us:
                    us, ue = ue, us
                dv = v - last_v
                big = run_max if run_max > w.fs else w.fs
                if abs(dv) > _ROW_FRAC * big:
                    ok = False
                elif v - w.up > last_v:
                    ok = False                              # entirely on a later line
                elif us < last_us:
                    ok = False                              # reading went backward
                elif us < last_ue and abs(dv) > _ROW_FRAC * run_max:
                    ok = False                              # stacked material
                elif us - last_ue > _FAR_FRAC * run_max:
                    ok = False
                else:
                    ok = True
            if not ok:
                lines.append(_make_line(cur, len(lines)))
                cur = []
        if not cur:
            cc, ss = w.c, w.s
            us = w.ox * cc + w.oy * ss
            ue = w.ex * cc + w.ey * ss
            if ue < us:
                us, ue = ue, us
            v = -w.ox * ss + w.oy * cc
            run_max = w.fs
        else:
            if w.fs > run_max:
                run_max = w.fs
        cur.append(w)
        last_us, last_ue, last_v = us, ue, v
    if cur:
        lines.append(_make_line(cur, len(lines)))
    return lines


# ---------------------------------------------------------------------------
# Interleaved column streams
# ---------------------------------------------------------------------------
def _upright(ln: Line) -> bool:
    return ln.th == 0.0


def _lane_assignment(lines: List[Line], page_w: float, info: Optional[dict]) -> Dict[int, Tuple[int, int]]:
    """Map line index -> (region, lane) for lines inside interleaved regions."""
    cand = [ln for ln in lines if _upright(ln) and ln.text]
    if len(cand) < 2 * _MIN_LANE_LINES:
        return {}
    wide_cut = _WIDE_LINE_FRAC * page_w if page_w > 0 else float("inf")
    barrier_y: List[float] = []
    narrow: List[Line] = []
    for ln in cand:
        if ln.x1 - ln.x0 > wide_cut:
            barrier_y.append((ln.y0 + ln.y1) / 2.0)
        else:
            narrow.append(ln)
    barrier_y.sort()
    regions: Dict[int, List[Line]] = {}
    for ln in narrow:
        regions.setdefault(bisect_right(barrier_y, (ln.y0 + ln.y1) / 2.0), []).append(ln)

    result: Dict[int, Tuple[int, int]] = {}
    flagged = 0
    for rid, rl in regions.items():
        if len(rl) < 2 * _MIN_LANE_LINES:
            continue
        body = _heavy([(ln.size, float(ln.nchar)) for ln in rl])
        # lanes by horizontal overlap
        lanes: List[list] = []                  # [lo, hi, [lines]]
        for ln in sorted(rl, key=lambda q: (q.x0, q.idx)):
            if lanes:
                lane = lanes[-1]
                overlap = min(lane[1], ln.x1) - max(lane[0], ln.x0)
                shorter = min(ln.x1 - ln.x0, lane[1] - lane[0])
                if overlap >= _LANE_OVERLAP * shorter and overlap > 0:
                    lane[1] = max(lane[1], ln.x1)
                    lane[2].append(ln)
                    continue
            lanes.append([ln.x0, ln.x1, [ln]])
        merged: List[list] = []
        for lane in lanes:
            if merged and lane[0] - merged[-1][1] < body:
                merged[-1][1] = max(merged[-1][1], lane[1])
                merged[-1][2].extend(lane[2])
            else:
                merged.append(lane)
        lanes = merged
        big = [lane for lane in lanes if len(lane[2]) >= _MIN_LANE_LINES]
        if len(big) < 2:
            continue
        lane_of: Dict[int, int] = {}
        for li, lane in enumerate(lanes):
            for ln in lane[2]:
                lane_of[ln.idx] = li
        seq = sorted(rl, key=lambda q: q.idx)
        runs = 0
        prev_lane = None
        for ln in seq:
            if lane_of[ln.idx] != prev_lane:
                runs += 1
                prev_lane = lane_of[ln.idx]
        if len(seq) / runs >= _MAX_MEAN_RUN:
            continue
        short = sum(1 for ln in rl if ln.x1 - ln.x0 < _SHORT_LINE_L * body)
        if short * 2 > len(rl):
            continue
        good = True
        for lane in big:
            ls = sorted(lane[2], key=lambda q: q.idx)
            ok = tot = 0
            for a, b in zip(ls, ls[1:]):
                tot += 1
                step = b.v - a.v
                if (0.0 < step < _LEADING * a.size
                        and abs(a.size - b.size) < _SIZE_DIFF * max(a.size, b.size)):
                    ok += 1
            if tot == 0 or ok < _STEP_OK_FRAC * tot:
                good = False
                break
        if not good:
            continue
        flagged += 1
        for ln in rl:
            result[ln.idx] = (rid, lane_of[ln.idx])
    if info is not None:
        info["interleaved_regions"] = flagged
    return result


# ---------------------------------------------------------------------------
# Lines to blocks
# ---------------------------------------------------------------------------
def _joins(prev: Line, ln: Line) -> bool:
    if ln.th != prev.th and not _ang_close(ln.th, prev.th):
        return False
    cc, ss = prev.c, prev.s
    v = -ln.px * ss + ln.py * cc
    if v + ln.dn < prev.v - prev.up:                       # bottom above the previous top
        return False
    if abs(ln.maxsize - prev.maxsize) >= _SIZE_DIFF * max(ln.maxsize, prev.maxsize):
        return False
    if v - prev.v >= _LEADING * prev.size:
        return False
    return True


def _heading_ends(open_lines: List[Line], ln: Line) -> bool:
    """True when the open block is a heading (a few wholly bold lines) and the
    next line is regular text.  A bold tail after body text never splits."""
    if len(open_lines) > _HEADING_MAX_LINES:
        return False
    for q in open_lines:
        if q.nchar <= 0 or q.nbold < _HEADING_BOLD * q.nchar:
            return False
    if ln.nbold * 2 >= ln.nchar:
        return False
    if _CONTACT.search(ln.text):
        return False                    # a name above its e-mail or ORCID is not a heading
    # a lone mark ("*", "1") under a bold word belongs to it, not to a paragraph
    return sum(1 for ch in ln.text if ch.isalnum()) >= _HEADING_NEXT_ALNUM


def _make_block(lines: List[Line]) -> Block:
    b = Block()
    b.lines = lines
    b.x0 = min(ln.x0 for ln in lines)
    b.y0 = min(ln.y0 for ln in lines)
    b.x1 = max(ln.x1 for ln in lines)
    b.y1 = max(ln.y1 for ln in lines)
    b.size = _heavy([(ln.size, float(ln.nchar)) for ln in lines])
    nch = sum(ln.nchar for ln in lines)
    nb = sum(ln.nbold for ln in lines)
    b.bold = nb * 2 >= nch and nb > 0
    b.first_line_height = max(lines[0].up + lines[0].dn, 1e-6)
    b.direction = lines[0].th
    b.seq = lines[0].idx
    return b


def _build_blocks(lines: List[Line], lane_of: Dict[int, Tuple[int, int]],
                  split_headings: bool = True) -> List[Block]:
    done: List[Block] = []
    seq_open: List[Line] = []
    lane_open: Dict[Tuple[int, int], List[Line]] = {}

    # The first line of the page stands alone when the next item starts clearly
    # to the right of its end (a title followed by another region).
    first_alone = False
    if len(lines) > 1 and lines[0].idx not in lane_of and lines[1].idx not in lane_of:
        a, b = lines[0], lines[1]
        if b.th == a.th or _ang_close(b.th, a.th):
            if b.px * a.c + b.py * a.s - a.ue > _TITLE_JUMP * a.size:
                first_alone = True

    def flush_lanes():
        for key in sorted(lane_open, key=lambda k: lane_open[k][0].idx):
            done.append(_make_block(lane_open[key]))
        lane_open.clear()

    for i, ln in enumerate(lines):
        lane = lane_of.get(ln.idx)
        if lane is not None:
            if seq_open:
                done.append(_make_block(seq_open))
                seq_open = []
            cur = lane_open.get(lane)
            if (cur is not None and _joins(cur[-1], ln)
                    and not (split_headings and _heading_ends(cur, ln))):
                cur.append(ln)
            else:
                if cur is not None:
                    done.append(_make_block(cur))
                lane_open[lane] = [ln]
            continue
        if lane_open:
            flush_lanes()
        if (seq_open and not (first_alone and i == 1) and _joins(seq_open[-1], ln)
                and not (split_headings and _heading_ends(seq_open, ln))):
            seq_open.append(ln)
            continue
        if seq_open:
            done.append(_make_block(seq_open))
        seq_open = [ln]
    if seq_open:
        done.append(_make_block(seq_open))
    flush_lanes()
    return done


# ---------------------------------------------------------------------------
# Block order
# ---------------------------------------------------------------------------
def _order_blocks(blocks: List[Block]) -> List[Block]:
    """Top down, then column aware band rule (see module docstring)."""
    n = len(blocks)
    if n < 2:
        return list(blocks)
    srt = sorted(blocks, key=lambda b: (b.y0, b.seq))
    # tops that agree within a small tolerance are equal: stream order decides
    grouped: List[Block] = []
    start = 0
    for k in range(1, n + 1):
        if k == n or srt[k].y0 - srt[k - 1].y0 > max(0.5, 0.1 * srt[k - 1].first_line_height):
            grouped.extend(sorted(srt[start:k], key=lambda b: b.seq))
            start = k
    srt = grouped

    top = [b.y0 for b in srt]
    bot = [b.y1 for b in srt]
    tol = [b.first_line_height for b in srt]

    # related to an earlier block: running maximum of (bottom + tolerance), or
    # the nearest earlier top lies within this block's tolerance above it
    prev_rel = [False] * n
    run_max = float("-inf")
    for k in range(n):
        if k:
            prev_rel[k] = top[k] <= run_max or top[k] - top[k - 1] <= tol[k]
        run_max = max(run_max, bot[k] + tol[k])
    # related to a later block: next top inside this extent, or some later
    # block has this top inside its own widened extent
    next_rel = [False] * n
    suffix_min = float("inf")
    for k in range(n - 2, -1, -1):
        suffix_min = min(suffix_min, top[k + 1] - tol[k + 1])
        next_rel[k] = top[k + 1] <= bot[k] + tol[k] or suffix_min <= top[k]
    banded = [prev_rel[k] or next_rel[k] for k in range(n)]

    out: List[Block] = []
    k = 0
    while k < n:
        if not banded[k]:
            out.append(srt[k])
            k += 1
            continue
        j = k
        while j < n and banded[j]:
            j += 1
        placed: List[Block] = []
        floor_pos = 1 if k == 0 else 0
        for t in range(k, j):
            b = srt[t]
            pos = len(placed)
            steps = 0
            while pos > floor_pos and steps < _HOP_CAP and placed[pos - 1].x0 > b.x1:
                pos -= 1
                steps += 1
            placed.insert(pos, b)
        out.extend(placed)
        k = j
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def ordered_blocks(page, chars: Optional[Sequence[dict]] = None, *,
                   repair_interleave: bool = True,
                   split_headings: bool = True,
                   info: Optional[dict] = None) -> List[Block]:
    """Blocks of one pdfplumber page in reading order.

    ``chars`` defaults to ``page.chars`` (content-stream order).  Coordinates
    of the result are relative to the page box origin.  ``info`` receives
    counters (glyphs, words, lines, blocks, interleaved_regions).  With
    ``split_headings`` a short wholly bold block is closed before regular text
    of the same size that follows it; ``False`` gives the plain stream rules.
    """
    if chars is None:
        chars = page.chars
    frame = _page_frame(page)
    items = _prepare(page, chars, frame, info)
    items = _drop_overprints(items)
    items = _merge_accents(items)
    words = _build_words(items)
    lines = _build_lines(words)
    lines = [ln for ln in lines if ln.text]
    for i, ln in enumerate(lines):
        ln.idx = i
    lane_of: Dict[int, Tuple[int, int]] = {}
    if repair_interleave and lines:
        lane_of = _lane_assignment(lines, frame[2], info)
    blocks = _build_blocks(lines, lane_of, split_headings)
    blocks = _order_blocks(blocks)
    if info is not None:
        info.setdefault("interleaved_regions", 0)
        info["glyphs"] = sum(1 for g in items if isinstance(g, _Glyph))
        info["words"] = len(words)
        info["lines"] = len(lines)
        info["blocks"] = len(blocks)
    return blocks
