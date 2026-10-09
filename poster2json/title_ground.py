"""Ground the model's poster title in the printed page-1 typography.

The model sometimes trims the printed title, paraphrases the largest pull
quote into a title, or invents one when the printed title is not in the text
layer. Section text is not affected; this module is about the title only.

Two pieces, both deterministic and poster-agnostic:

  * ``compute_title_candidate`` reads page-1 geometry with pdfplumber and
    returns the printed title as typography sees it: the topmost large-font
    line group in the top part of the page.
  * ``ground_title`` compares the model title with that candidate and the raw
    text and returns the title to keep.
"""

import re
import unicodedata
from typing import List, Optional, Tuple

BAND_FRACTION = 0.35      # top share of page 1 searched for the title
SIZE_FLOOR = 0.6          # candidate font >= this x the largest size in the band
JOIN_SIZE_TOL = 0.25      # adjacent lines join when sizes are within 25%
JOIN_GAP_EM = 1.0         # max vertical gap between joined lines, in font sizes
WORD_SIZE_KEEP = 0.75     # within a line, keep words >= this x the line's largest
MIN_WORDS = 3
MIN_SIZE_RATIO = 1.6      # candidate font >= this x the page median word size
MAX_CANDIDATE_WORDS = 40
COVERAGE = 0.9            # token LCS coverage that counts as "grounded"
MIN_SHARE = 0.5           # model title must cover this share of a longer candidate

# Event banner above a title ("5th Balkan Conference on ..."): dropped when it
# is the first line of a multi-line group.
_VENUE_RE = re.compile(
    r"\b(conference|symposium|congress|workshop|annual meeting|proceedings|summit)\b", re.I)
_URL_RE = re.compile(r"(https?://|www\.|\.(com|org|edu|net|gov|io)\b|@)", re.I)


def _tokens(text: str) -> List[str]:
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\s]", " ", t.lower()).split()


def _lcs(a: List[str], b: List[str]) -> int:
    row = [0] * (len(b) + 1)
    for x in a:
        prev = 0
        for j, y in enumerate(b):
            cur = row[j + 1]
            row[j + 1] = prev + 1 if x == y else max(row[j + 1], row[j])
            prev = cur
    return row[-1]


def coverage(title_tokens: List[str], other_tokens: List[str]) -> float:
    """Share of title_tokens found, in order, inside other_tokens."""
    if not title_tokens:
        return 0.0
    return _lcs(title_tokens, other_tokens) / len(title_tokens)


def grounded_in_text(title_tokens: List[str], text: str) -> float:
    """Best token coverage of the title inside any window of the text.

    A window (about twice the title length) keeps the match local, so a title
    whose words are merely scattered across the poster does not count as found.
    """
    if not title_tokens:
        return 0.0
    toks = _tokens(text)
    win = 2 * len(title_tokens) + 2
    step = max(1, len(title_tokens) // 2)
    best = 0.0
    for i in range(0, max(1, len(toks) - win + step), step):
        best = max(best, coverage(title_tokens, toks[i:i + win]))
        if best >= 1.0:
            break
    return best


def _is_author_line(text: str) -> bool:
    """Author and affiliation lines: digit, comma or marker heavy."""
    words = text.split()
    if not words:
        return True
    digitish = sum(1 for w in words if re.search(r"\d", w) or re.fullmatch(r"[*†‡§¶,]+", w))
    if digitish / len(words) > 0.25:
        return True
    if text.count(",") >= 3 and text.count(",") / len(words) > 0.3:
        return True
    # Name lists: "A. Perdomo , N. Vitas & E. Khomenko", "Ann Lee , Bo Chan".
    seps = sum(1 for w in words if w in {",", "&", "and", ";"})
    initials = sum(1 for w in words if re.fullmatch(r"(?:[A-Z]\.)+,?", w))
    if initials >= 2 and (initials + seps) / len(words) >= 0.3:
        return True
    commas = text.count(",")
    if commas >= 2 and commas / len(words) >= 0.15 and all(
            w[0].isupper() or not w[0].isalpha() or w == "and" for w in words):
        return True
    return False


def _group_lines(words: List[dict]) -> List[dict]:
    """Cluster words into visual lines by vertical overlap; sizes may mix."""
    lines: List[dict] = []
    words = [w for w in words if not re.fullmatch(r"#\w+", w["text"])]
    for w in sorted(words, key=lambda w: (w["top"] + w["bottom"]) / 2):
        h = w["bottom"] - w["top"]
        placed = False
        for ln in lines:
            ov = min(ln["bottom"], w["bottom"]) - max(ln["top"], w["top"])
            if ov > 0.5 * min(ln["bottom"] - ln["top"], h):
                ln["words"].append(w)
                ln["top"] = min(ln["top"], w["top"])
                ln["bottom"] = max(ln["bottom"], w["bottom"])
                placed = True
                break
        if not placed:
            lines.append({"top": w["top"], "bottom": w["bottom"], "words": [w]})
    for ln in lines:
        # Mixed sizes on one line (author names beside a title, superscripts):
        # keep only words close to the line's largest size. A title that mixes
        # 80 pt and 66 pt words stays whole (ratio 0.83).
        big = max(w["size"] for w in ln["words"])
        ln["words"] = [w for w in ln["words"] if w["size"] >= WORD_SIZE_KEEP * big]
        ln["words"].sort(key=lambda w: w["x0"])
        ln["text"] = " ".join(w["text"] for w in ln["words"])
        ln["size"] = max(w["size"] for w in ln["words"])
        ln["x0"] = min(w["x0"] for w in ln["words"])
        ln["x1"] = max(w["x1"] for w in ln["words"])
    lines.sort(key=lambda ln: ln["top"])
    return lines


def candidate_from_lines(lines: List[dict]) -> Optional[str]:
    """Title candidate text from visual lines (top band of page 1)."""
    info = candidate_info_from_lines(lines)
    return info[0] if info else None


def candidate_info_from_lines(lines: List[dict]) -> Optional[Tuple[str, float]]:
    """Pick the title candidate from visual lines (top band of page 1).

    Each line is a dict with text, size, top, bottom. Pure function so the
    selection rules can be unit tested without a PDF. Returns (text, size).
    """
    elig = []
    for ln in lines:
        txt = ln["text"].strip()
        if not txt or _URL_RE.search(txt) or _is_author_line(txt):
            continue
        elig.append(ln)
    if not elig:
        return None
    biggest = max(ln["size"] for ln in elig)
    for start, first in enumerate(elig):
        if first["size"] < SIZE_FLOOR * biggest:
            continue
        group = [first]
        base = first["size"]
        for ln in elig[start + 1:]:
            prev = group[-1]
            if ln["top"] - prev["bottom"] > JOIN_GAP_EM * base * 2:
                break
            if ln["size"] > (1 + JOIN_SIZE_TOL) * base:
                break
            if ln["size"] < (1 - JOIN_SIZE_TOL) * base:
                continue  # smaller interleaved line (role, affiliation); skip it
            if ln["top"] - prev["bottom"] > JOIN_GAP_EM * base:
                break
            group.append(ln)
        # A one- or two-word first line (a label, a lone heading) is not a
        # title unless the group it starts reaches the minimum length.
        if sum(len(ln["text"].split()) for ln in group) >= MIN_WORDS:
            return _finish_group(group, base)
    return None


def _finish_group(group: List[dict], base: float) -> Optional[Tuple[str, float]]:
    if len(group) > 1 and _VENUE_RE.search(group[0]["text"]):
        group = group[1:]
    text = ""
    for ln in group:
        t = ln["text"].strip()
        # Join a hyphenated line break without the space.
        text = (text[:-1] + t if text.endswith("-") and t[:1].islower()
                else (text + " " + t if text else t))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([:;,.?!])", r"\1", text)
    n = len(text.split())
    if n < MIN_WORDS or n > MAX_CANDIDATE_WORDS:
        return None
    return text, base


def title_candidate_info(pdf_path: str) -> Optional[Tuple[str, float]]:
    """(candidate text, candidate size / page median word size), or None."""
    try:
        import statistics
        import pdfplumber

        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                return None
            page = pdf.pages[0]
            words = page.extract_words(extra_attrs=["size"], keep_blank_chars=False)
            words = [w for w in words if w["text"].strip()]
            if not words:
                return None
            body = statistics.median(w["size"] for w in words)
            band = page.height * BAND_FRACTION
            info = candidate_info_from_lines(
                _group_lines([w for w in words if w["top"] < band]))
            if not info:
                return None
            return info[0], info[1] / body if body else 0.0
    except Exception:
        return None


def compute_title_candidate(pdf_path: str) -> Optional[str]:
    """Typographic title candidate from page 1 of a PDF, or None.

    The title must stand clearly above the body text (MIN_SIZE_RATIO times the
    page's median word size); a heading that is barely larger than body text
    is a section heading, not the poster title.
    """
    info = title_candidate_info(pdf_path)
    if not info or info[1] < MIN_SIZE_RATIO:
        return None
    return info[0]


def _match_case(candidate: str, model_title: str) -> str:
    """An all-caps candidate gets Title Case, keeping the model's word forms."""
    letters = [c for c in candidate if c.isalpha()]
    if not letters or not all(c.isupper() for c in letters):
        return candidate
    forms = {w.lower().strip(".,:;()"): w for w in model_title.split()}
    out = []
    for w in candidate.split():
        key = w.lower().strip(".,:;()")
        out.append(forms.get(key, w.capitalize() if len(w) > 1 else w))
    return " ".join(out)


def ground_title(
    model_title: str, candidate: Optional[str], raw_text: str = ""
) -> Tuple[str, str]:
    """Return (title, action). Action is one of keep, extend, replace, warn."""
    mt = _tokens(model_title)
    if not mt:
        return model_title, "keep"
    ct = _tokens(candidate) if candidate else []
    if len(ct) < MIN_WORDS:
        # No plausible candidate: keep the model title, but flag one that is
        # not in the text at all (likely invented).
        if raw_text and grounded_in_text(mt, raw_text) < COVERAGE:
            return model_title, "warn"
        return model_title, "keep"
    if coverage(ct, mt) >= COVERAGE and len(mt) > len(ct):
        # The candidate is only part of the model title (the printed title
        # continues in a smaller font, or the text layer splits it): the
        # model title is the more complete one.
        return model_title, "keep"
    if coverage(mt, ct) >= COVERAGE:
        if len(ct) > len(mt) and len(mt) / len(ct) >= MIN_SHARE:
            return _match_case(candidate, model_title), "extend"
        return model_title, "keep"
    # Model title is not the printed top title. If it came from elsewhere in
    # the text (a pull quote), the typographic candidate is the better
    # evidence. If it is in the text nowhere (invented), the candidate may be
    # an unrelated heading and the real title may not be extractable, so keep
    # the model title and flag it rather than swap in another guess.
    if raw_text and grounded_in_text(mt, raw_text) < COVERAGE:
        return model_title, "warn"
    return _match_case(candidate, model_title), "replace"
