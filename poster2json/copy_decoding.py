"""Copy-only constrained decoding for verbatim JSON string fields.

While the model writes the value of a verbatim field (a title, a section's
content, a caption) this logits processor only lets it continue with text that
exists in the poster text it was given. It is a soft guard against paraphrase
and invention: the highest-scoring tokens are tested in order and the first one
that copies the source wins. If none of the top candidates copies the source the
step is left untouched (fail open), so decoding can never dead-end.

Everything except ``CopyOnlyProcessor.__call__`` is plain Python with no torch
dependency, so the state machine and the copy predicate are unit-testable.
"""

import re
import unicodedata
from typing import Iterable, List, Optional, Tuple

try:  # the processor base class; absent only in minimal test environments
    from transformers import LogitsProcessor as _Base
except Exception:  # pragma: no cover
    _Base = object

# JSON string values that must be copied from the poster. Descriptions are
# summaries and creator/affiliation/subject strings are reformatted, so they are
# deliberately absent.
VERBATIM_KEYS = frozenset({"title", "sectionContent", "caption"})
# Keys whose copy test ignores case: the prompt asks the model to convert an
# ALL CAPS title to Title Case.
CASE_INSENSITIVE_KEYS = frozenset({"title"})

_WS_RE = re.compile(r"\s+")
_HEADER_RE = re.compile(r"(?m)^[ \t]*#{1,6}[ \t]+")
_QUOTES = {chr(c): "'" for c in (0x2018, 0x2019, 0x201A, 0x201B, 0x201C, 0x201D, 0x201E, 0x201F, 0xAB, 0xBB, 0x2032, 0x2033, 0xB4, 0x60, 0x22)}
_DASHES = {chr(c): "-" for c in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212)}
_CHAR_MAP = str.maketrans({**_QUOTES, **_DASHES})
_SIMPLE_ESC = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "/": "/", "\\": "\\", '"': '"'}

REPLACEMENT = chr(0xFFFD)  # what a partial multi-byte token decodes to
TAIL_CHARS = 120  # only the last N chars of the current fragment are searched


def normalize(text: str) -> str:
    """Collapse whitespace runs, unify quotes and dashes, drop accents.

    The poster text reaches the model NFKD-normalized with combining marks
    removed, so an accented letter in the output must match its bare form.
    """
    if not text.isascii():
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if not unicodedata.combining(c))
    return _WS_RE.sub(" ", text.translate(_CHAR_MAP))


def normalize_source(raw_text: str) -> str:
    """Normalize the poster text for matching: drop '## ' header markers too."""
    return normalize(_HEADER_RE.sub("", raw_text)).strip()


# ---------------------------------------------------------------------------
# Incremental JSON state machine
# ---------------------------------------------------------------------------


def _scan_string(text, i, esc, uni, hexbuf):
    """Decode string-body characters of ``text`` from index ``i``.

    Returns (decoded, next_index, closed, esc, uni, hexbuf, opaque). Stops
    after an unescaped closing quote (``closed``). ``opaque`` is set when a
    \\uXXXX escape is involved: the decoded text is then not reliable.
    """
    out = []
    opaque = False
    n = len(text)
    while i < n:
        ch = text[i]
        i += 1
        if uni:
            opaque = True
            hexbuf += ch
            uni -= 1
            if not uni:
                try:
                    out.append(chr(int(hexbuf, 16)))
                except ValueError:
                    pass
                hexbuf = ""
            continue
        if esc:
            esc = False
            if ch == "u":
                uni, hexbuf, opaque = 4, "", True
            else:
                out.append(_SIMPLE_ESC.get(ch, ch))
            continue
        if ch == "\\":
            esc = True
        elif ch == '"':
            return "".join(out), i, True, esc, uni, hexbuf, opaque
        else:
            out.append(ch)
    return "".join(out), i, False, esc, uni, hexbuf, opaque


class JsonStringTracker:
    """Follow generated JSON text and report string values and their keys.

    ``feed`` returns events: ("open", field) when a string VALUE begins
    (``field`` is the key it belongs to; array elements use the array's key),
    ("text", decoded) for its unescaped characters and ("close", None).
    Key strings produce no events. Tolerant of malformed JSON.
    """

    def __init__(self):
        # stack entries: ["o", current_key, expect] or ["a", array_key]
        self.stack: List[list] = []
        self.in_str = False
        self.is_key = False
        self.field: Optional[str] = None
        self._keybuf: List[str] = []
        self._esc = False
        self._uni = 0
        self._hex = ""

    # -- queries -----------------------------------------------------------
    @property
    def in_value_string(self) -> bool:
        return self.in_str and not self.is_key

    @property
    def in_unicode_escape(self) -> bool:
        return self.in_str and self._uni > 0

    def simulate(self, text: str) -> Tuple[str, bool, bool]:
        """Effect of ``text`` on the open value string without changing state.

        Returns (decoded, closes_string, opaque). Only meaningful while
        ``in_value_string``.
        """
        dec, _, closed, _, _, _, opaque = _scan_string(text, 0, self._esc, self._uni, self._hex)
        return dec, closed, opaque

    # -- updates -----------------------------------------------------------
    def feed(self, text: str) -> list:
        events = []
        i, n = 0, len(text)
        while i < n:
            if self.in_str:
                dec, i, closed, self._esc, self._uni, self._hex, _ = _scan_string(
                    text, i, self._esc, self._uni, self._hex
                )
                if self.is_key:
                    self._keybuf.append(dec)
                elif dec:
                    events.append(("text", dec))
                if closed:
                    self.in_str = False
                    if self.is_key:
                        if self.stack and self.stack[-1][0] == "o":
                            self.stack[-1][1] = "".join(self._keybuf)
                            self.stack[-1][2] = "colon"
                    else:
                        events.append(("close", None))
                        self.field = None
                        if self.stack and self.stack[-1][0] == "o":
                            self.stack[-1][2] = "comma"
                continue
            ch = text[i]
            i += 1
            if ch == '"':
                top = self.stack[-1] if self.stack else None
                self.in_str = True
                self._esc, self._uni, self._hex = False, 0, ""
                if top is not None and top[0] == "o" and top[2] in ("key", "comma"):
                    self.is_key = True
                    self._keybuf = []
                else:
                    self.is_key = False
                    self.field = top[1] if top is not None else None
                    events.append(("open", self.field))
            elif ch == "{":
                self._value_started()
                self.stack.append(["o", None, "key"])
            elif ch == "[":
                key = self.stack[-1][1] if self.stack else None
                self._value_started()
                self.stack.append(["a", key])
            elif ch in "}]":
                if self.stack:
                    self.stack.pop()
                if self.stack and self.stack[-1][0] == "o":
                    self.stack[-1][2] = "comma"
            elif ch == ":":
                if self.stack and self.stack[-1][0] == "o":
                    self.stack[-1][2] = "value"
            elif ch == ",":
                if self.stack and self.stack[-1][0] == "o":
                    self.stack[-1][2] = "key"
        return events

    def _value_started(self):
        # A container value inside an object: the key stays attached to it
        # through the array entry; nothing else to do for objects.
        pass


# ---------------------------------------------------------------------------
# Copy predicate
# ---------------------------------------------------------------------------


def _find_word_start(hay: str, needle: str) -> int:
    """Index of ``needle`` in ``hay`` where it starts a word, else -1."""
    i = hay.find(needle)
    while i > 0 and hay[i - 1] != " ":
        i = hay.find(needle, i + 1)
    return i


class CopySource:
    """Normalized poster text and the matching state of one open string.

    Besides the copy test it refuses to keep re-copying source text that was
    already copied (a degenerate repeat loop of valid text would otherwise pass
    the copy test forever): a continuation is rejected once it extends a run of
    already-copied source longer than ``max_repeat`` characters. Section content
    is tracked across strings, every other field within its own string.
    """

    SHARED_COVERAGE = frozenset({"sectionContent"})

    def __init__(self, raw_text: str, max_repeat: int = 80):
        self.src = normalize_source(raw_text)
        self.src_lower = self.src.lower()
        self.max_repeat = max_repeat
        self._shared = {}
        self.reset()

    def reset(self, lower: bool = False, field: Optional[str] = None):
        self.lower = lower
        self.frag = ""  # tail of the current copied fragment (normalized)
        self.pos = -1  # index in the source just after the fragment, if known
        self.dup_run = 0  # length of the current run of already-copied source
        n = len(self._hay())
        if field in self.SHARED_COVERAGE:
            self.cov = self._shared.setdefault((field, lower), bytearray(n))
        else:
            self.cov = bytearray(n)

    def _hay(self) -> str:
        return self.src_lower if self.lower else self.src

    def extend(self, piece: str) -> Optional[Tuple[str, int, int]]:
        """Result of appending normalized ``piece``, or None if it is invented.

        Returns (new fragment tail, new source position, source chars covered
        by the piece).
        """
        if not piece:
            return self.frag, self.pos, 0
        if self.lower:
            piece = piece.lower()
        frag = self.frag
        if frag == "" or frag.endswith(" "):
            piece = piece.lstrip(" ")
            if not piece:
                return frag, self.pos, 0
        hay = self._hay()
        if self.pos >= 0 and hay.startswith(piece, self.pos):
            return (frag + piece)[-TAIL_CHARS:], self.pos + len(piece), len(piece)
        combined = frag + piece
        i = _find_word_start(hay, combined) if not frag else hay.find(combined)
        if i >= 0:
            return combined[-TAIL_CHARS:], i + len(combined), len(piece)
        if frag and (frag.endswith(" ") or piece.startswith(" ")):
            # word boundary: the model may skip text and start a new fragment
            nd = piece.lstrip(" ")
            if not nd:
                return frag, self.pos, 0
            i = _find_word_start(hay, nd)
            if i >= 0:
                return nd[-TAIL_CHARS:], i + len(nd), len(nd)
        return None

    def _run_after(self, pos: int, plen: int) -> int:
        """Length of the already-copied run if a piece ending at ``pos`` is added."""
        if plen <= 0 or pos < plen:
            return self.dup_run if plen <= 0 else 0
        seen = self.cov[pos - plen:pos].count(1) == plen
        return self.dup_run + plen if seen else 0

    def allows(self, piece: str) -> bool:
        res = self.extend(piece)
        if res is None:
            return False
        return self._run_after(res[1], res[2]) <= self.max_repeat

    def commit(self, piece: str):
        """Advance over ``piece`` that the model actually produced."""
        res = self.extend(piece)
        if res is not None:
            self.frag, self.pos, plen = res
            self.dup_run = self._run_after(self.pos, plen)
            if plen > 0 and self.pos >= plen:
                self.cov[self.pos - plen:self.pos] = b"" * plen
        elif piece:
            # fail-open step: restart matching from this text
            p = piece.lower() if self.lower else piece
            p = p.lstrip(" ")
            self.frag = p[-TAIL_CHARS:]
            i = self._hay().find(self.frag)
            self.pos = i + len(self.frag) if i >= 0 else -1
            self.dup_run = 0


# ---------------------------------------------------------------------------
# Logits processor
# ---------------------------------------------------------------------------


class CopyOnlyProcessor(_Base):
    """Mask top-k tokens that would leave the source inside verbatim strings."""

    def __init__(self, tokenizer, input_length: int, raw_text: str, top_k: int = 20,
                 verbatim_keys: Iterable[str] = VERBATIM_KEYS, max_repeat: int = 80):
        self.tokenizer = tokenizer
        self.input_length = input_length
        self.top_k = top_k
        self.verbatim_keys = frozenset(verbatim_keys)
        self.source = CopySource(raw_text, max_repeat)
        self.tracker = JsonStringTracker()
        self._prev_len = 0
        self._pending = []
        self._cache = {}
        self._active = False  # inside a verbatim string value
        self.stats = {"steps": 0, "constrained": 0, "masked_steps": 0,
                      "masked_tokens": 0, "fail_open": 0}

    def _tok(self, tid: int) -> str:
        s = self._cache.get(tid)
        if s is None:
            s = self.tokenizer.decode([tid], skip_special_tokens=True)
            self._cache[tid] = s
        return s

    def _advance(self, ids):
        # Byte-level BPE can split one character over several tokens; hold the
        # tokens until they decode to whole characters.
        parts = []
        for tid in ids:
            self._pending.append(tid)
            if len(self._pending) == 1:
                text = self._tok(tid)
            else:
                text = self.tokenizer.decode(self._pending, skip_special_tokens=True)
            if text.endswith(REPLACEMENT) and len(self._pending) < 4:
                continue
            parts.append(text)
            self._pending = []
        for kind, val in self.tracker.feed("".join(parts)):
            if kind == "open":
                self._active = val in self.verbatim_keys
                if self._active:
                    self.source.reset(lower=val in CASE_INSENSITIVE_KEYS, field=val)
            elif kind == "text":
                if self._active:
                    self.source.commit(normalize(val))
            else:
                self._active = False

    def summary(self) -> str:
        s = self.stats
        return (f"copy-only decoding: {s['constrained']} constrained steps of {s['steps']}, "
                f"{s['masked_steps']} steps masked ({s['masked_tokens']} tokens), "
                f"{s['fail_open']} fail-open")

    def candidate_allowed(self, tid: int) -> bool:
        """Whether token ``tid`` copies the source (or ends the string)."""
        tok = self._tok(tid)
        if REPLACEMENT in tok:
            return True  # part of a multi-byte character: judged once it is whole
        dec, closed, opaque = self.tracker.simulate(tok)
        if opaque:
            # Verbatim text is written with literal characters. Only finish an
            # escape the model already started; never open a new unicode escape.
            return self.tracker.in_unicode_escape
        return self.source.allows(normalize(dec))

    def __call__(self, input_ids, scores):
        import torch

        gen = input_ids[0, self.input_length:]
        n = len(gen)
        self.stats["steps"] += 1
        if n > self._prev_len:
            self._advance(gen[self._prev_len:].tolist())
            self._prev_len = n
        if not (self._active and self.tracker.in_value_string):
            return scores
        self.stats["constrained"] += 1
        top = torch.topk(scores[0], self.top_k)
        vals = top.values.tolist()
        idx = top.indices.tolist()
        masked = []
        live = 0
        accepted = False
        for v, tid in zip(vals, idx):
            if v == float("-inf"):
                break
            live += 1
            if self.candidate_allowed(tid):
                accepted = True
                break
            masked.append(tid)
        if masked and not accepted:
            self.stats["fail_open"] += 1  # nothing in the top-k copies the source
            return scores
        if masked:
            self.stats["masked_steps"] += 1
            self.stats["masked_tokens"] += len(masked)
            scores[0, masked] = float("-inf")
        return scores
