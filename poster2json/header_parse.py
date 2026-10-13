"""Deterministic author and affiliation parsing of the poster header.

The model sees the whole poster and, with copy-only decoding, still varies from
run to run on the author block: it joins "A & B" into one creator, trims a
printed affiliation to its institution name, merges two affiliations into one
string or hands every author the same one. When the printed header is
regular, those answers are fully determined by the text, so this module reads
them from the text:

  * ``parse_header(raw_text)`` finds the author line(s) (names separated by
    commas, "&", "and" or ";", each optionally followed by marker numbers,
    letters or symbols) and the affiliation list (entries introduced by
    "1 ...", "1. ...", "a ..." or a symbol, on one line or one per line) in the
    top of the extracted text, and pairs authors with affiliations by marker.
  * ``ground_creators`` applies the parse to the model's creators. When the
    parse is confident it supplies the printed order, the full printed
    affiliation strings and the assignment; when it is not, the model output is
    kept and only two safe repairs are made: creators joined by "&"/"and"/";"
    are split, and an affiliation that is a sub-span of exactly one printed
    affiliation entry is expanded to the printed entry.

Everything is poster-agnostic: no poster, name or institution is special-cased.
Affiliation strings are never canonicalized here; ROR lookup runs afterwards on
the final strings and matches exactly.
"""

import copy
import os
import re
import unicodedata
from typing import Dict, List, Optional, Tuple

# Set POSTER2JSON_HEADER_GROUNDING=0 (or this to False) to turn grounding off.
HEADER_GROUNDING = os.environ.get("POSTER2JSON_HEADER_GROUNDING", "1").strip().lower() not in {
    "0", "false", "no", "off"}

MAX_LINES = 45          # lines of the text searched for the header
MAX_NAME_WORDS = 6
MAX_ENTRY_LEN = 260     # longer "affiliations" ran into body text
MAX_UNMARKED_AFFIL = 220
UNMARKED_WINDOW = 3     # lines after the authors searched for unmarked affiliations
UNMARKED_ADJACENT = 1   # the single unmarked affiliation must be this close

# ---------------------------------------------------------------- vocabulary
_SUPER = {
    "\u2070": "0", "\u00b9": "1", "\u00b2": "2", "\u00b3": "3", "\u2074": "4",
    "\u2075": "5", "\u2076": "6", "\u2077": "7", "\u2078": "8", "\u2079": "9",
    "\u2080": "0", "\u2081": "1", "\u2082": "2", "\u2083": "3", "\u2084": "4",
    "\u2085": "5", "\u2086": "6", "\u2087": "7", "\u2088": "8", "\u2089": "9",
    "\u207a": ",", "\u208a": ",", "\u207b": "-", "\u208b": "-",
}
_SUPER_LETTERS = {"\u1d43": "a", "\u1d47": "b", "\u1d9c": "c", "\u1d48": "d", "\u1d49": "e",
                  "\u1da0": "f", "\u1d4d": "g", "\u02b0": "h"}
_SUPER_RUN = re.compile("[" + "".join(re.escape(c) for c in {**_SUPER, **_SUPER_LETTERS}) + "]+")
_SYMBOL_CHARS = "*\u2020\u2021\u00a7\u00b6#\u204e\u2217\u2051"
_SYMBOL_CANON = {"\u204e": "*", "\u2217": "*", "\u2051": "*"}

_DEGREES = {
    "phd", "ph.d", "ph.d.", "md", "m.d", "m.d.", "mls", "mslis", "dds", "msc", "m.sc", "bsc", "mph",
    "mba", "ms", "ma", "ba", "bs", "rn", "dvm", "pharmd", "dphil", "mphil", "mbbs", "frcp", "msn",
    "dnp", "ma.", "ms.", "jr", "jr.", "sr", "sr.", "esq", "dmd", "dpt", "ot", "pt", "cpa", "pe",
}
_TITLES = {"dr", "dr.", "prof", "prof.", "professor", "mr", "mr.", "mrs", "mrs.", "ms.", "mx"}
_PARTICLES = {
    "van", "von", "der", "den", "de", "del", "della", "di", "da", "dos", "das", "du", "la", "le",
    "bin", "ibn", "al", "el", "ter", "ten", "zu", "zur", "af", "av", "st", "st.", "y", "e", "do",
}
_CAP_PARTICLES = {"van", "von", "der", "den", "de", "del", "della", "di", "da", "dos", "du", "la", "le",
                  "bin", "ibn", "al", "el", "ter", "ten"}

_JOB_WORDS = {
    "manager", "director", "officer", "professor", "engineer", "student", "postdoc", "researcher",
    "scientist", "coordinator", "lead", "associate", "fellow", "outreach", "analyst", "specialist",
    "librarian", "candidate", "chair", "head", "intern", "assistant", "lecturer", "curator",
}
_SENTENCE_WORDS = re.compile(
    r"(?:is|are|was|were|has|have|had|that|which|this|these|those|by|with|from|their|we|our|it|its"
    r"|can|will|should|would|may|not)", re.I)

_INSTITUTION = re.compile(
    r"\b(?:univ\w*|institut\w*|department|dept|school|college|hospital|cent(?:er|re|ro)|centrum|zentrum"
    r"|laborator\w*|labs?|facult\w*|research|academy|akademi\w*|ministry|society|foundation|council"
    r"|clinic\w*|observator\w*|librar\w*|museum|company|ltd|inc|gmbh|llc|corp\w*|agency|network|hub"
    r"|division|s\.?r\.?l|kgaa|polytechni\w*|politecnic\w*|consortium|association|bureau|office"
    r"|ecole|programme?|survey|service|authority|organi[sz]ation|alliance|partnership|ag"
    r"|universit\u00e4t|universit\u00e9|universit\u00e0|h\u00f4pital|\u00e9cole|polit\u00e9cnica|szpital)\b",
    re.I,
)
_GROUP_TAIL = re.compile(
    r"^(?:(?:and|&|,)\s*)?(?:on behalf of\s+)?(?:the\s+)?[A-Z][\w\-]*(?:\s+[\w\-]+){0,5}?\s+"
    r"(?:Team|Consortium|Collaboration|Group|Task Force|Working Group|Committee|Network)\b[.,;]?\s*",
)
_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_ORCID = re.compile(r"(?:ORCID(?:\s*iDs?)?:?\s*)?(?:https?://orcid\.org/)?\d{4}-\s?\d{4}-\s?\d{4}-\s?\d{3}[\dX]", re.I)
_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_LABEL = re.compile(r"^(?:authors?|presenting author|presented by|by)\s*:?\s+", re.I)

# --------------------------------------------------------------- tokenizing
_ITEM = r"(?:\d{1,2}(?!\d)|[" + re.escape(_SYMBOL_CHARS) + r"]+)"
_SEP_BETWEEN = (
    r"(?:\s*,\s*|\s*\+\s*(?=\d)|\s*[\u2013\u2014\-]\s*(?=\d)|(?<=[" + re.escape(_SYMBOL_CHARS) + r"])(?=\d)"
    r"|(?<=\d)(?=[" + re.escape(_SYMBOL_CHARS) + r"]))"
)
_MARK_RUN = _ITEM + r"(?:" + _SEP_BETWEEN + _ITEM + r")*"
_LETTER_RUN = r"(?<=[^\W\d_.]\s)[a-h](?:\s*,\s*[a-h])*(?![\w.'\u2019\-])(?=\s*(?:[,;&]|$|and\b))"
_TOK = re.compile(
    r"(?P<ws>\s+)"
    r"|(?P<mark>" + _MARK_RUN + r"|" + _LETTER_RUN + r")"
    r"|(?P<sep>[,;&]|\band\b)"
    r"|(?P<word>[^\W\d_](?:[^\W\d_]|['\u2019\-.])*)"
    r"|(?P<other>.)",
    re.U,
)


def _normalize(line: str) -> str:
    """Superscript characters become plain marker text; symbols are canonical."""
    def sup(m):
        s = "".join(_SUPER.get(c) or _SUPER_LETTERS.get(c, c) for c in m.group(0))
        return " " + s + " "
    line = _SUPER_RUN.sub(sup, line)
    for k, v in _SYMBOL_CANON.items():
        line = line.replace(k, v)
    line = line.replace("\u00a0", " ").replace("\u200b", "")
    return re.sub(r"[ \t]+", " ", line).strip()


def _strip_noise(line: str) -> str:
    """Drop e-mails, ORCID ids, URLs and an "Authors:" label from an author line."""
    # an e-mail / ORCID printed after a name ends that name
    line = _EMAIL.sub(" , ", line)
    line = _ORCID.sub(" , ", line)
    line = _URL.sub(" , ", line)
    line = _LABEL.sub("", line.strip())
    return re.sub(r"\s+", " ", line).strip()


def _marks(run: str) -> List[str]:
    """Expand a marker run ("1,2" / "1-3" / "4-5-6" / "*" / "6" + "\u00b6") to marker strings."""
    run = run.strip()
    out: List[str] = []
    # symbols and letters stay as they are, digits are expanded
    for part in re.findall(r"\d{1,2}(?:\s*[\u2013\u2014\-]\s*\d{1,2})+|\d{1,2}|[" + re.escape(_SYMBOL_CHARS) + r"]+|[a-h]", run):
        if re.search(r"[\u2013\u2014\-]", part):
            nums = [int(x) for x in re.split(r"\s*[\u2013\u2014\-]\s*", part)]
            if len(nums) == 2 and nums[0] < nums[1] <= nums[0] + 15:
                out.extend(str(n) for n in range(nums[0], nums[1] + 1))
            else:
                out.extend(str(n) for n in nums)
        else:
            out.append(part)
    return out


def _is_initial(w: str) -> bool:
    return bool(re.fullmatch(r"[^\W\d_]\.?", w))


def _word_kind(w: str, has_words: bool) -> str:
    """name | particle | degree | title | stop for one word token."""
    bare = w.rstrip(",;")
    low = bare.lower()
    if low in _DEGREES or low.rstrip(".") in _DEGREES:
        return "degree"
    if not has_words and (low in _TITLES or low.rstrip(".") in _TITLES):
        return "title"
    if bare[0].isupper():
        return "name"
    if low in _PARTICLES and has_words:
        return "particle"
    return "stop"


def _clean_word(w: str) -> str:
    return w[:-1] if len(w) > 2 and w.endswith(".") and not re.fullmatch(r"(?:[^\W\d_]\.)+", w) else w


class _Person:
    __slots__ = ("words", "marks")

    def __init__(self):
        self.words: List[str] = []
        self.marks: List[str] = []


def _scan_names(line: str):
    """Scan names off the front of ``line``.

    Returns ``(persons, rest, ok)``; ``rest`` is the unscanned remainder and
    ``ok`` is False when a name is malformed (so the line is not an author line).
    """
    persons: List[_Person] = []
    cur: Optional[_Person] = None
    pos = 0
    n = len(line)
    toks = []
    while pos < n:
        m = _TOK.match(line, pos)
        if m is None:
            break
        if m.lastgroup != "ws":
            toks.append((m.lastgroup, m.group(0), m.start()))
        pos = m.end()

    def close():
        nonlocal cur
        if cur is not None and cur.words:
            persons.append(cur)
        cur = None

    i = 0
    rest_at = None
    kind_at_stop = None
    while i < len(toks):
        kind, text, start = toks[i]
        if kind == "word":
            has = cur is not None and bool(cur.words)
            if cur is not None and cur.marks:
                close()
                has = False
            wk = _word_kind(text, has)
            if wk == "degree":
                i += 1
                continue
            if wk == "title":
                i += 1
                continue
            if wk == "stop":
                rest_at = start
                kind_at_stop = "stop"
                break
            if wk == "name" and has and text.isupper() and len(text.rstrip(".")) >= 3 \
                    and not all(w.isupper() for w in cur.words if len(w.rstrip(".")) > 1):
                # An acronym after a mixed-case name starts the next field ("... Lemke ZBW ...").
                rest_at = start
                break
            if cur is None:
                cur = _Person()
            cur.words.append(_clean_word(text))
            i += 1
        elif kind == "mark":
            if cur is None or not cur.words:
                rest_at = start
                break
            cur.marks.extend(_marks(text))
            i += 1
        elif kind == "sep":
            # a separator before a degree ("Surkis, PhD, MLS 1") is part of the name
            j = i + 1
            if j < len(toks) and toks[j][0] == "word" and _word_kind(toks[j][1], True) == "degree":
                i += 1
                continue
            close()
            i += 1
        else:  # other punctuation
            if text == "." and (i == len(toks) - 1):
                i += 1
                continue
            rest_at = start
            break
    stopped_open = cur is not None and bool(cur.words) and not cur.marks
    close()
    if (rest_at is not None and stopped_open and len(persons) >= 3 and toks
            and kind_at_stop == "stop"):
        others = [len(p.words) for p in persons[:-1]]
        extra = len(persons[-1].words) - max(others)
        if extra > 0:
            # "... Evgeniya N. Ivanova Section of Genetics": the surplus capitalized
            # words belong to the next field, not to the name
            cut_word = persons[-1].words[-extra]
            idx = line.rfind(cut_word, 0, rest_at)
            if idx >= 0:
                persons[-1].words = persons[-1].words[:-extra]
                rest_at = idx
    rest = line[rest_at:].strip() if rest_at is not None else ""
    ok = True
    for p in persons:
        if not (2 <= len(p.words) <= MAX_NAME_WORDS):
            ok = False
        elif all(_is_initial(w) for w in p.words):
            ok = False
        elif _INSTITUTION.search(" ".join(p.words)):
            ok = False
        elif any(w.lower().strip(".,") in _JOB_WORDS for w in p.words):
            ok = False
    return persons, rest, ok


# ---------------------------------------------------------------- name split
def split_person_name(words: List[str], vancouver: bool = False) -> Tuple[str, str]:
    """(given, family) of a printed name, particles kept with the family name."""
    if len(words) == 1:
        return "", words[0]
    if vancouver:
        return words[-1], " ".join(words[:-1])
    j = len(words) - 1
    while j - 1 >= 1 and (words[j - 1].lower() in _PARTICLES
                          or (words[j - 1].lower() in _CAP_PARTICLES and j - 1 >= 1 and len(words) > 2)):
        j -= 1
    return " ".join(words[:j]), " ".join(words[j:])


def _is_vancouver(persons) -> bool:
    """Every name ends in 1-3 capital initials ("Colombo GL", "Naik J")."""
    if len(persons) < 2:
        return False
    for p in persons:
        w = p.words
        if len(w) < 2 or not re.fullmatch(r"[A-Z]{1,3}", w[-1].rstrip(".")):
            return False
        if any(_is_initial(x) for x in w[:-1]):
            return False
    return True


# ------------------------------------------------------- affiliation entries
_SYM = re.escape(_SYMBOL_CHARS)
_CAND = re.compile(
    r"(?:(?<=\s)|(?<=[;,.)])|^)"
    r"(?:(?P<d>\d{1,2})(?!\d)[.)]?|(?P<s>[" + _SYM + r"]{1,3})|(?P<l>[a-h])[.)]?(?=\s))"
    r"\s*(?=[A-Z\u00c0-\u00de(])"
)


def _first_cut(text: str) -> str:
    """Drop trailing contact material (e-mail, URL, bar) from an entry."""
    cut = len(text)
    for rx in (_EMAIL, _URL, re.compile(r"\s\|\s")):
        m = rx.search(text)
        if m:
            cut = min(cut, m.start())
    text = text[:cut]
    return re.sub(r"[\s,;.|*" + _SYM + r"]+$", "", text).strip()


def _parse_affiliation_lines(lines: List[Tuple[int, str]]):
    """Sequential marker list over the candidate lines -> ({marker: text}, scheme).

    Digits count up from 1, letters from a, symbols in order of appearance. The
    first entry must name an institution; later entries continue the sequence on
    the same line or the next candidate line.
    """
    scheme = None
    accepted: List[Tuple[int, int, int, str]] = []   # (line_pos, start, end_of_marker, marker)
    last_line_pos = None
    syms_seen: List[str] = []
    for lp, (idx, text) in enumerate(lines):
        cands = list(_CAND.finditer(text))
        for ci, m in enumerate(cands):
            if m.group("d") is not None:
                sch, mark = "d", m.group("d")
            elif m.group("s") is not None:
                sch, mark = "s", m.group("s")
            else:
                sch, mark = "l", m.group("l")
            seg_end = cands[ci + 1].start() if ci + 1 < len(cands) else len(text)
            seg = text[m.end():seg_end]
            if scheme is None:
                start_ok = (sch == "d" and mark == "1") or (sch == "l" and mark == "a") or sch == "s"
                if not start_ok:
                    continue
                if not _INSTITUTION.search(seg[:280]):
                    # an entry without an institution word ("Veterinary Bacteriology, Sciensano")
                    # starts a list only when the next entry follows on the same line and
                    # an institution word appears in the rest of the line
                    nxt_mark = {"d": str(int(mark) + 1) if sch == "d" else None,
                                "l": chr(ord(mark) + 1) if sch == "l" else None}.get(sch)
                    follows = nxt_mark is not None and any(
                        (c.group("d") or c.group("l")) == nxt_mark for c in cands[ci + 1:])
                    if not (follows and _INSTITUTION.search(text[m.end():m.end() + 600])):
                        continue
            else:
                if sch != scheme:
                    continue
                if sch == "d" and int(mark) != int(accepted[-1][3]) + 1:
                    continue
                if sch == "l" and ord(mark) != ord(accepted[-1][3]) + 1:
                    continue
                if sch == "s" and mark in syms_seen:
                    continue
                if last_line_pos is None or lp - last_line_pos > 1:
                    continue
                if not (_INSTITUTION.search(seg[:280]) or 3 <= len(seg.strip()) <= 200):
                    continue
            scheme = sch
            accepted.append((lp, m.start(), m.end(), mark))
            if sch == "s":
                syms_seen.append(mark)
            last_line_pos = lp
    if scheme == "l" and len(accepted) < 2:
        return None
    if not accepted:
        return None
    entries: Dict[str, str] = {}
    order: List[str] = []
    for k, (lp, s, e, mark) in enumerate(accepted):
        text = lines[lp][1]
        nxt = next((a for a in accepted[k + 1:] if a[0] == lp), None)
        seg = text[e: nxt[1] if nxt else len(text)]
        seg = _first_cut(seg.strip())
        if not seg:
            continue
        if len(seg) > MAX_ENTRY_LEN:
            return {"__too_long__": seg[:40]}, scheme
        entries[mark] = seg
        order.append(mark)
    if not entries:
        return None
    return entries, scheme


# ------------------------------------------------------------------- parsing
class HeaderParse:
    def __init__(self):
        self.authors: List[dict] = []       # {words, given, family, marks, name}
        self.entries: Dict[str, str] = {}   # marker -> printed affiliation
        self.scheme: Optional[str] = None
        self.unmarked: List[str] = []       # unmarked affiliation lines near the authors
        self.assigned: List[Optional[List[str]]] = []
        self.confident = False
        self.reason = ""
        self.group_tail = ""

    def affiliation_strings(self) -> List[str]:
        return list(self.entries.values()) or list(self.unmarked)

    def creators(self) -> List[dict]:
        """The parse as a creators list (for scoring and for new creators)."""
        out = []
        for a, aff in zip(self.authors, self.assigned or [None] * len(self.authors)):
            out.append(_creator_from_author(a, aff or []))
        return out


def _creator_from_author(a: dict, affiliations: List[str]) -> dict:
    c = {"name": a["name"]}
    if a["family"]:
        c["givenName"] = a["given"]
        c["familyName"] = a["family"]
        if not a["given"]:
            c.pop("givenName")
    c["nameType"] = "Personal"
    c["affiliation"] = list(affiliations)
    return c


def _title_norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def parse_header(raw_text: str, exclude: Optional[List[str]] = None) -> HeaderParse:
    """Parse the author line(s) and affiliation list from the top of ``raw_text``."""
    hp = HeaderParse()
    if not raw_text:
        hp.reason = "no text"
        return hp
    excl = [e for e in (_title_norm(x) for x in (exclude or [])) if e]

    lines: List[str] = []
    for ln in raw_text.splitlines():
        s = ln.strip()
        if not s:
            continue
        s = re.sub(r"^#+\s*", "", s)
        if not s or re.match(r"^\[.*extracted\]$", s):
            continue
        lines.append(_normalize(s))
        if len(lines) >= MAX_LINES:
            break

    persons_all: List[_Person] = []
    author_line_idx: List[int] = []
    cand: List[Tuple[int, str]] = []        # affiliation candidate lines (idx, text)
    other_run = 0
    for idx, line in enumerate(lines):
        norm = _title_norm(line)
        if norm and any(norm == e or (len(norm) > 12 and norm in e) for e in excl):
            continue
        stripped = _strip_noise(line)
        if not stripped:
            continue  # an e-mail / URL / ORCID only line
        if re.match(r"^(?:contact|correspondence|e-?mail)\b", stripped, re.I):
            continue
        persons, rest, ok = _scan_names(stripped)
        is_author = False
        if persons and ok:
            marked = any(p.marks for p in persons)
            if len(persons) >= 2 or marked:
                gm = _GROUP_TAIL.match(rest) if rest else None
                tail = rest
                if gm:
                    hp.group_tail = gm.group(0).strip()
                    tail = rest[gm.end():].strip()
                if not tail or _CAND.search(tail) or _INSTITUTION.search(tail):
                    is_author = True
                    persons_all.extend(persons)
                    author_line_idx.append(idx)
                    if tail:
                        cand.append((idx, tail))
        if is_author:
            other_run = 0
            continue
        if _CAND.search(stripped) or _INSTITUTION.search(stripped):
            cand.append((idx, stripped))
            other_run = 0 if len(stripped) < 400 else other_run
        elif len(stripped) > 60:
            other_run += 1
            if author_line_idx and other_run >= 2:
                break

    if not persons_all:
        hp.reason = "no author line"
        return hp

    vanc = _is_vancouver(persons_all)
    seen = set()
    for p in persons_all:
        given, family = split_person_name(p.words, vanc)
        key = _title_norm(" ".join(p.words))
        if key in seen:
            continue
        seen.add(key)
        name = f"{family}, {given}" if given else family
        hp.authors.append({"words": p.words, "given": given, "family": family,
                           "marks": p.marks, "name": name})

    parsed = _parse_affiliation_lines(cand)
    if parsed is not None:
        entries, hp.scheme = parsed
        if "__too_long__" in entries:
            hp.reason = "affiliation entry ran into body text"
            return hp
        hp.entries = entries
    last_author = max(author_line_idx)
    if not hp.entries:
        near = [(i, t) for i, t in cand
                if i >= min(author_line_idx) and i <= last_author + UNMARKED_WINDOW
                and _INSTITUTION.search(t) and len(t) <= MAX_UNMARKED_AFFIL
                and not _CAND.match(t) and _affiliation_like(t)]
        hp.unmarked = [t for _, t in near]
        if len(near) == 1 and near[0][0] > last_author + UNMARKED_ADJACENT:
            hp.unmarked = []
    _resolve(hp)
    return hp


def _affiliation_like(text: str) -> bool:
    """An unmarked line is taken as an affiliation only when it does not read as a sentence."""
    if text[:1] in "\"'\u201c\u2018\u2022\u25cf-" or len(text.split()) > 24:
        return False
    return not _SENTENCE_WORDS.search(text)


def _resolve(hp: HeaderParse) -> None:
    """Decide whether the parse is confident and compute the assignment."""
    n = len(hp.authors)
    hp.assigned = [None] * n
    marked_any = any(a["marks"] for a in hp.authors)

    if not hp.entries:
        if not marked_any and len(hp.unmarked) == 1 and n >= 2:
            hp.assigned = [[hp.unmarked[0]] for _ in range(n)]
            hp.confident = True
            hp.reason = "single unmarked affiliation shared by all authors"
        elif not hp.unmarked and not marked_any:
            hp.reason = "no affiliation found"
        elif len(hp.unmarked) > 1 and not marked_any:
            hp.reason = "several affiliations without markers"
        else:
            hp.reason = "author markers without an affiliation list"
        return

    kind = {"d": str.isdigit, "l": str.isalpha, "s": lambda m: not m.isalnum()}[hp.scheme]
    refs: List[Optional[List[str]]] = []
    for a in hp.authors:
        usable = [m for m in a["marks"] if kind(m)]
        if hp.scheme == "s":
            usable = [m for m in usable if m in hp.entries]
        if any(m not in hp.entries for m in usable):
            hp.reason = f"marker {next(m for m in usable if m not in hp.entries)!r} has no affiliation entry"
            return
        refs.append(usable or None)
    marked = [r for r in refs if r]
    if not marked:
        hp.reason = "affiliation list but no author carries a marker"
        return
    unmarked_idx = [i for i, r in enumerate(refs) if not r]
    if len(unmarked_idx) > max(1, n // 4):
        hp.reason = f"{len(unmarked_idx)} of {n} authors carry no marker"
        return
    used = {m for r in marked for m in r}
    uncovered = [m for m in hp.entries if m not in used]
    if uncovered and not unmarked_idx:
        hp.reason = f"affiliation entries never referenced by an author: {uncovered}"
        return
    for i, r in enumerate(refs):
        if r:
            hp.assigned[i] = [hp.entries[m] for m in dict.fromkeys(r)]
    if unmarked_idx:
        if len(unmarked_idx) == 1 and len(uncovered) == 1:
            hp.assigned[unmarked_idx[0]] = [hp.entries[uncovered[0]]]
        # otherwise stay None: the model's assignment (expanded) is kept for them
    hp.confident = True
    hp.reason = "markers resolve" + (f" ({len(unmarked_idx)} unmarked)" if unmarked_idx else "")


# ------------------------------------------------------------------ grounding
def _alpha_tokens(text: str) -> List[str]:
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).split()


def _tok_compat(x: str, y: str) -> bool:
    return x == y or (len(x) == 1 and y.startswith(x)) or (len(y) == 1 and x.startswith(y))


def _same_person(a: str, b: str) -> bool:
    ta, tb = _alpha_tokens(a), _alpha_tokens(b)
    if not ta or not tb:
        return False
    if sorted(ta) == sorted(tb):
        return True
    small, large = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if set(ta) & set(tb) and all(any(_tok_compat(t, u) for u in large) for t in small):
        return True
    return False


def _creator_text(c: dict) -> str:
    g, f = c.get("givenName"), c.get("familyName")
    if g or f:
        return " ".join(x for x in (g, f) if x)
    n = c.get("name") or ""
    if "," in n:
        fam, giv = n.split(",", 1)
        return f"{giv.strip()} {fam.strip()}"
    return n


_JOIN = re.compile(r"\s*(?:&|;|\band\b)\s*")


def split_joined_creators(creators: List[dict]) -> Tuple[List[dict], List[str]]:
    """Split a creator that holds several people ("Hahn, Oliver & Lemke, Steffen")."""
    out: List[dict] = []
    notes: List[str] = []
    for c in creators:
        if not isinstance(c, dict):
            out.append(c)
            continue
        name = c.get("name") or ""
        parts = [p.strip(" ,") for p in _JOIN.split(name)] if _JOIN.search(name) else []
        ok = len(parts) >= 2 and all(parts)
        if ok:
            for p in parts:
                # "Family, Given" or "Given Family": at least two name tokens
                if len(_alpha_tokens(p)) < 2 or _INSTITUTION.search(p):
                    ok = False
        if not ok:
            out.append(c)
            continue
        for p in parts:
            new = {k: v for k, v in c.items() if k not in ("name", "givenName", "familyName")}
            if "," in p:
                fam, giv = [x.strip() for x in p.split(",", 1)]
            else:
                words = p.split()
                giv, fam = split_person_name(words)
            new["name"] = f"{fam}, {giv}" if giv else fam
            if giv:
                new["givenName"] = giv
            if fam:
                new["familyName"] = fam
            new["affiliation"] = copy.deepcopy(c.get("affiliation") or [])
            out.append(new)
        notes.append(f"split joined creator {name!r} into {len(parts)} people")
    return out, notes


def _aff_name(a) -> str:
    return a if isinstance(a, str) else (a.get("name", "") if isinstance(a, dict) else "")


def _expand_affiliation(text: str, entries: List[str]) -> Optional[str]:
    """The printed entry that ``text`` is a strict sub-span of, if exactly one."""
    tt = _alpha_tokens(text)
    if len(tt) < 2:
        return None
    hits = []
    for e in entries:
        et = _alpha_tokens(e)
        if et == tt:
            return None  # already the printed entry
        L = len(tt)
        if any(et[i:i + L] == tt for i in range(len(et) - L + 1)):
            hits.append(e)
    return hits[0] if len(hits) == 1 else None


def _expand_creator_affiliations(c: dict, entries: List[str], notes: List[str]) -> None:
    affs = c.get("affiliation")
    if isinstance(affs, str):
        affs = [affs]
    if not isinstance(affs, list):
        return
    new_affs, changed = [], False
    for a in affs:
        full = _expand_affiliation(_aff_name(a), entries) if _aff_name(a) else None
        if full:
            notes.append(f"expanded affiliation {_aff_name(a)!r} -> {full!r}")
            new_affs.append(full)
            changed = True
        else:
            new_affs.append(a)
    if changed:
        c["affiliation"] = list(dict.fromkeys(a if isinstance(a, str) else a.get("name", "") for a in new_affs)) \
            if all(isinstance(a, str) for a in new_affs) else new_affs


_DEGREE_IN_NAME = re.compile(r"(?:,|\s)\s*(?:Ph\.?D\.?|M\.?D\.?|MLS|MSLIS|DDS|MSc|MPH|MBA|DVM|RN)\b", re.I)


def ground_creators(creators, hp: HeaderParse) -> Tuple[list, List[str]]:
    """Apply a header parse to the model's creators. Returns (creators, notes)."""
    if not isinstance(creators, list):
        return creators, []
    creators = [c for c in creators]
    creators, notes = split_joined_creators(creators)

    if hp is None or not hp.authors:
        return creators, notes

    model_people = [c for c in creators if isinstance(c, dict)]
    if hp.confident and model_people:
        # Sanity gate: most of what the model found must be among the printed
        # authors, otherwise the parsed line is probably not the author block.
        hits = sum(1 for c in model_people
                   if any(_same_person(" ".join(a["words"]), _creator_text(c)) for a in hp.authors))
        if hits * 2 < len(model_people):
            notes.append(f"header parse ignored: only {hits} of {len(model_people)} model creators "
                         "are among the printed authors")
            hp = copy.copy(hp)
            hp.confident = False

    if not hp.confident:
        entries = hp.affiliation_strings()
        if entries:
            creators = copy.deepcopy(creators)
            for c in creators:
                if isinstance(c, dict):
                    _expand_creator_affiliations(c, entries, notes)
        return creators, notes

    # confident: printed order, printed affiliation strings, marker assignment
    model = [c for c in creators if isinstance(c, dict)]
    used = set()
    result: List[dict] = []
    for a, assigned in zip(hp.authors, hp.assigned):
        match = None
        for j, c in enumerate(model):
            if j not in used and _same_person(" ".join(a["words"]), _creator_text(c)):
                match = j
                break
        if match is not None:
            used.add(match)
            c = copy.deepcopy(model[match])
            if _DEGREE_IN_NAME.search(c.get("name") or ""):
                fixed = _creator_from_author(a, [])
                for k in ("name", "givenName", "familyName"):
                    if k in fixed:
                        c[k] = fixed[k]
                notes.append(f"removed degree suffix from {model[match].get('name')!r}")
            if assigned is not None:
                before = [_aff_name(x) for x in (c.get("affiliation") or [])]
                if before != assigned:
                    notes.append(f"affiliations of {c.get('name')!r}: {before} -> {assigned}")
                c["affiliation"] = list(assigned)
            else:
                _expand_creator_affiliations(c, hp.affiliation_strings(), notes)
        else:
            c = _creator_from_author(a, assigned or [])
            notes.append(f"added creator {c['name']!r} from the printed author line")
        result.append(c)
    extras = [c for j, c in enumerate(model) if j not in used]
    for c in extras:
        _expand_creator_affiliations(c, hp.affiliation_strings(), notes)
    result.extend(copy.deepcopy(extras))
    if [c.get("name") for c in result] != [c.get("name") for c in creators if isinstance(c, dict)]:
        notes.append("creator order/membership set from the printed author line")
    return result, notes
