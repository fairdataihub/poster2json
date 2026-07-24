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

_FENCE_MARKER = re.compile(r"^[ \t]*```.*$", re.MULTILINE)
_TABLE = re.compile(r"<table\b(.*?)</table>", re.DOTALL | re.IGNORECASE)
_CELL = re.compile(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", re.DOTALL | re.IGNORECASE)
_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_TRAIL_WS = re.compile(r"[ \t]+\n")
_BLANKS = re.compile(r"\n{3,}")

# A data table's cells are short (numbers, units, short labels); a LAYOUT table
# -- which the model uses to reproduce a poster's column grid -- holds whole
# prose paragraphs. Median cell length separates them.
_DATA_CELL_MAXLEN = 45


def _table_repl(m):
    """Drop a data table (short cells); keep a layout table's prose."""
    cells = _CELL.findall(m.group(1))
    if not cells:
        return ""
    lens = sorted(len(re.sub(r"<[^>]+>", "", c).strip()) for c in cells)
    median = lens[len(lens) // 2]
    if median <= _DATA_CELL_MAXLEN:
        return ""                                   # data within an image
    # layout grid: keep the cell text as paragraphs, one per cell
    return "\n\n".join(re.sub(r"<[^>]+>", "", c).strip() for c in cells) + "\n"


def scrub(text: str) -> str:
    if not text:
        return text
    text = _FENCE_MARKER.sub("", text)     # drop ``` markers, keep caption prose
    text = _TABLE.sub(_table_repl, text)   # drop data tables, keep layout prose
    text = _TAG.sub("", text)              # remaining tags, keep inner text
    text = _TRAIL_WS.sub("\n", text)
    text = _BLANKS.sub("\n\n", text)
    return text.strip()


if __name__ == "__main__":
    import sys
    print(scrub(open(sys.argv[1], encoding="utf-8").read()))
