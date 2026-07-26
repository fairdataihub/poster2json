#!/usr/bin/env python3
"""Scrub markup out of LightOnOCR output, keeping prose and captions.

The VLM faithfully transcribes a poster's figures and tables as HTML tables and
fenced code blocks. Our goal is captions, not the tabular data inside an image,
so this strips the MARKUP while keeping the prose it wraps:

  - ``` code-fence markers (```, ```plaintext, ```html) -- remove the marker
    lines, KEEP the content, because the model uses fences as figure separators
    and the content is the caption ("Figure 3. A) hiPSCs ...");
  - whole <table>...</table> blocks whose cells are short -- that is data within
    an image -- while keeping a LAYOUT table's prose (the model reproduces the
    poster's column grid as a <table> holding paragraphs);
  - remaining HTML tags (<div>, <br>, <span>, ...) while KEEPING the text they
    wrap, because the model uses <div> for layout around real content.

It deliberately leaves "---" horizontal rules and "##" headers, which are clean
structure. Only the tabular data payload is removed; every caption survives.
"""
import re
import unicodedata

_FENCE_MARKER = re.compile(r"^[ \t]*```.*$", re.MULTILINE)

# Markdown image placeholders. The model marks every figure it cannot read as
# ![image](image_N.png) (or with a data-describing alt like "Pie chart ...
# Malware (19,224)"), which is exactly the data-within-an-image we do not want:
# it adds "image png" tokens that match no caption. The real caption is separate
# prose, so dropping the whole marker keeps captions and removes the noise.
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")

# LaTeX the model emits for superscripts, subscripts and math. The superscripts
# are author AFFILIATION markers ($^{1,2}$ -> 1,2), which are meaningful content
# and must survive as their digits; the rest ($\alpha$, $\mu_1$) is figure math.
# Currency ($600) is safe: it has no closing $, so the paired-$ patterns skip it.
_LATEX_SUPSUB = re.compile(r"\$\s*[_^]\s*\{([^{}$]*)\}\s*\$")   # $^{1,2}$ -> 1,2
_LATEX_SUPSUB1 = re.compile(r"\$\s*[_^]\s*([A-Za-z0-9])\s*\$")  # $^2$ -> 2
_LATEX_MATH = re.compile(r"\$([^$]{1,60}?)\$")                  # $...$ -> inner
_LATEX_GREEK = {
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ",
    r"\lambda": "λ", r"\mu": "μ", r"\tau": "τ", r"\sigma": "σ", r"\pi": "π",
    r"\chi": "χ", r"\phi": "φ", r"\theta": "θ", r"\Delta": "Δ", r"\bullet": "",
    r"\text": "", r"\times": "×", r"\pm": "±", r"\approx": "≈", r"\sim": "~",
}
_LATEX_CMD = re.compile(r"\\[a-zA-Z]+")


def _delatex(text: str) -> str:
    """Turn the model's LaTeX into plain text, preserving affiliation markers."""
    text = _LATEX_SUPSUB.sub(r"\1", text)
    text = _LATEX_SUPSUB1.sub(r"\1", text)

    def _math(m):
        inner = m.group(1)
        for k, v in _LATEX_GREEK.items():
            inner = inner.replace(k, v)
        inner = _LATEX_CMD.sub("", inner)          # drop leftover \commands
        return inner.replace("{", "").replace("}", "").replace("^", "").replace("_", " ")
    return _LATEX_MATH.sub(_math, text)
_TABLE = re.compile(r"<table\b(.*?)</table>", re.DOTALL | re.IGNORECASE)
_CELL = re.compile(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", re.DOTALL | re.IGNORECASE)
_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_TRAIL_WS = re.compile(r"[ \t]+\n")
_BLANKS = re.compile(r"\n{3,}")

# A poster's foot carries sponsor/institution LOGOS, which the model transcribes
# as trailing standalone bold or ALL-CAPS name lines ("**FAIR DATA INNOVATIONS
# HUB**", "**AI-READI**"). They are branding, not a content section, and are not
# in the human transcription, so they only dilute the tail. Peel them off the
# end -- and only the end, so a bold heading mid-document is untouched.
_BOLD_ONLY = re.compile(r"\*\*[^*]+\*\*$")


# Reproducibility: the model leaves typographic variants (curly quotes, en/em
# dashes, arrows) untouched while other things get decomposed, so the character
# set the downstream LLM converts to JSON is inconsistent. Collapse each variant
# family to ONE ASCII form, drop box-drawing art (the model rendering a folder
# tree as |-- lines), and NFKC-normalize the rest -- which unifies duplicate
# encodings (micro sign U+00B5 vs greek mu U+03BC, super/subscript digits) while
# LEAVING real content: Hebrew/Arabic/Greek letters, accented names, units.
_BOXDRAW = re.compile(r"[─-▟]+")   # box-drawing + block elements
_PUNCT = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "‒": "-", "―": "-", "−": "-",
    "…": "...", " ": " ", " ": " ", " ": " ", " ": " ",
    "→": "->", "⟶": "->", "➔": "->", "⇒": "->", "➙": "->",
    "←": "<-", "⟵": "<-", "⇐": "<-",
})


def _normalize_chars(text: str) -> str:
    text = _BOXDRAW.sub(" ", text)
    text = text.translate(_PUNCT)
    # NFKC collapses compatibility variants (micro->mu, super/subscripts) to a
    # single representation; combining marks on Hebrew/accents are preserved.
    return unicodedata.normalize("NFKC", text)


def _strip_footer_logos(text: str) -> str:
    lines = text.splitlines()
    while lines:
        s = lines[-1].strip()
        if not s:
            lines.pop()
            continue
        logo = (len(s) < 60 and not s.startswith("#")
                and (_BOLD_ONLY.fullmatch(s)
                     or (s.isupper() and len(s.split()) <= 6)))
        if not logo:
            break
        lines.pop()
    return "\n".join(lines)

# A data table's cells are short (numbers, units, short labels); a LAYOUT table
# -- which the model uses to reproduce a poster's column grid -- holds whole
# prose paragraphs. Median cell length separates them.
_DATA_CELL_MAXLEN = 45
_BULLET = re.compile(r"[•▪◦‣·∙]|<br\b")
_PROSE_CELL_MINLEN = 40


def _cell_text(c):
    return re.sub(r"<[^>]+>", "", _IMAGE.sub("", c)).strip()   # drop ![img] then tags


def _is_prose_cell(raw):
    """A table cell that is genuine free text (a quote, a finding), not a short
    label, a number, or a bulleted grid column."""
    breaks = len(_BULLET.findall(raw))            # count on RAW (bullets/<br> intact)
    txt = _cell_text(raw)
    if len(txt) < _PROSE_CELL_MINLEN:             # short label / numeric cell
        return False
    if breaks > 2:                                # bulleted grid column (the 4448680 noise)
        return False
    letters = sum(ch.isalpha() for ch in txt)
    return bool(txt) and letters >= 0.5 * len(txt)  # not a pure-numeric grid


def _table_repl(m):
    """Layout table -> keep every cell's prose. Data table -> drop the grid but
    RESCUE any long free-text cells (interview quotes, findings) that would
    otherwise be lost with the table; a poster's Results sometimes live in an
    Example column. Table CLASSIFICATION (median cell length) is unchanged, so
    layout tables are handled byte-identically to before."""
    cells = _CELL.findall(m.group(1))
    if not cells:
        return ""
    lens = sorted(len(re.sub(r"<[^>]+>", "", c).strip()) for c in cells)
    median = lens[len(lens) // 2]
    if median <= _DATA_CELL_MAXLEN:
        kept = [_cell_text(c) for c in cells if _is_prose_cell(c)]
        return ("\n\n".join(kept) + "\n") if kept else ""
    # layout grid: keep the cell text as paragraphs, one per cell
    return "\n\n".join(re.sub(r"<[^>]+>", "", c).strip() for c in cells) + "\n"


# Figure/chart scaffolding the VLM reads out of image regions: lone panel labels
# ("A"/"B"/"C") and an orphaned code-fence language token emitted without its
# backticks ("plaintext"). These survive as their own lines, match no caption,
# and drag per-field ROUGE-L precision down. (The bare-number-run variant was
# rejected in review — it deletes real F1 result values on 8228476.)
_SCAFFOLD_LABEL = re.compile(
    r"^(?:[A-Za-z][.)]?|plaintext|html|python|json|text|markdown|yaml|css|bash|sql)$")


def _strip_scaffold(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines()
                     if not (ln.strip() and _SCAFFOLD_LABEL.match(ln.strip())))


def scrub(text: str) -> str:
    if not text:
        return text
    text = _FENCE_MARKER.sub("", text)     # drop ``` markers, keep caption prose
    text = _TABLE.sub(_table_repl, text)   # drop data tables, keep layout prose
    text = _IMAGE.sub("", text)            # drop image placeholders
    text = _delatex(text)                  # LaTeX -> plain, keep affil markers
    text = _TAG.sub("", text)              # remaining tags, keep inner text
    text = _normalize_chars(text)          # one canonical char per variant family
    text = _TRAIL_WS.sub("\n", text)
    text = _BLANKS.sub("\n\n", text)
    text = _strip_scaffold(text)           # drop lone panel labels / orphan fence tokens
    text = _strip_footer_logos(text.strip())   # peel sponsor/logo lines off foot
    return text.strip()


if __name__ == "__main__":
    import sys
    print(scrub(open(sys.argv[1], encoding="utf-8").read()))
