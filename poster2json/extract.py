"""
Poster Extraction Module

Extract structured JSON metadata from scientific posters (PDF/images)
using Large Language Models.

Models:
- Llama 3.1 8B Poster Extraction: JSON structuring (via HuggingFace transformers)
- Qwen2-VL-7B-Instruct: Vision OCR for images

Requirements:
- pdfplumber: layout-aware PDF text extraction (MIT-licensed)
- CUDA-capable GPU with ≥16GB VRAM
"""

import gc
import json
import os
import re
import tempfile
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import torch
from PIL import Image
from transformers import (
    AutoModelForCausalLM,
    AutoProcessor,
    AutoTokenizer,
    BitsAndBytesConfig,
    LogitsProcessor,
    LogitsProcessorList,
    Qwen2VLForConditionalGeneration,
    TextStreamer,
)

# Model configuration
JSON_MODEL_ID = "fairdataihub/Llama-3.1-8B-Poster-Extraction"
VISION_MODEL_ID = "Qwen/Qwen2-VL-7B-Instruct"

# Token limits
MAX_JSON_TOKENS = 18000
MAX_RETRY_TOKENS = 24000
MAX_INPUT_TOKENS = 15000

# Schema URL
SCHEMA_URL = "https://posters.science/schema/v0.2/poster_schema.json"

# File extension → MIME type per DataCite metadata schema 4.7
EXT_TO_FORMAT = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

# Scraping publication/funder identifiers out of poster text (top-level
# identifiers[], funder identifiers, relatedIdentifiers) is OFF by default —
# that responsibility is handled upstream. ORCID and ROR enrichment always run.
# Toggle per call via the extract_identifiers argument, or set the default for a
# deployment with the POSTER2JSON_EXTRACT_IDENTIFIERS environment variable.
_TRUTHY_ENV = {"1", "true", "yes", "on"}


def _identifiers_flag_default() -> bool:
    """Default for extract_identifiers, read from the environment."""
    return os.environ.get("POSTER2JSON_EXTRACT_IDENTIFIERS", "").strip().lower() in _TRUTHY_ENV

# Standalone section headings that posters print as a single bare word/phrase.
# Small-caption/footer fonts mean the font-size header heuristic misses these,
# so the LLM merges "References"/"Acknowledgements" into the adjacent body blob
# and the buried section matches at ~0.15 instead of ~1.0 section-level ROUGE.
_SECTION_KEYWORDS = frozenset({
    "abstract", "introduction", "background", "objective", "objectives",
    "aim", "aims", "hypothesis", "methods", "methodology",
    "materials and methods", "results", "results and discussion",
    "discussion", "conclusion", "conclusions", "summary",
    "references", "reference", "bibliography",
    "acknowledgements", "acknowledgments", "acknowledgement",
    "funding", "limitations", "future work", "future directions",
    "contact", "contact information",
})

# Dense conference posters often cram several footer sections onto one
# extracted line, marked by inline ALL-CAPS labels with a colon, e.g.
# "...results REFERENCES: 1. ... ABBREVIATIONS: CCR, ... DISCLOSURES: ...".
# Case-sensitive (uppercase only) so we don't split on the same word used
# in normal prose. Splitting here lets the LLM isolate each footer section.
_INLINE_LABELS = (
    "REFERENCES", "REFERENCE", "BIBLIOGRAPHY", "ABBREVIATIONS",
    "DISCLOSURES", "DISCLOSURE", "ACKNOWLEDGEMENTS", "ACKNOWLEDGMENTS",
    "FUNDING", "CONFLICTS OF INTEREST", "CONFLICT OF INTEREST",
    "COMPETING INTERESTS", "CORRESPONDING AUTHOR", "CONTACT",
    "CONCLUSIONS", "CONCLUSION",
)
_INLINE_LABEL_RE = re.compile(
    r"(?:(?<=[\s.;)])|^)(" + "|".join(_INLINE_LABELS) + r")\s*:\s+"
)

# Inline ALL-CAPS sub-header led by an em/en dash, e.g. "TWINS — Our second
# sample ..." glued onto the end of a prior paragraph. Requires sentence-end
# or line-start before, an uppercase letter after, to avoid matching inline
# abbreviation definitions like "CCR — cetuximab" (lowercase after dash).
_INLINE_DASH_HEAD_RE = re.compile(
    r"(?:(?<=[.;])\s+|^)([A-Z][A-Z]{2,})\s*[—–]\s+(?=[A-Z])"
)


def log(msg: str):
    """Timestamped logging."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


class ProgressStreamer(TextStreamer):
    """Custom streamer that logs progress during token generation."""

    def __init__(self, tokenizer, log_every: int = 100, **kwargs):
        defaults = {"skip_prompt": True, "skip_special_tokens": True}
        super().__init__(tokenizer, **{**defaults, **kwargs})
        self.log_every = log_every
        self.token_count = 0
        self.start_time = None

    def on_finalized_text(self, text: str, stream_end: bool = False):
        if self.start_time is None:
            self.start_time = time.time()
        self.token_count += len(text.split()) if text.strip() else 1
        if (self.token_count % self.log_every == 0) or stream_end:
            elapsed = time.time() - self.start_time
            tokens_per_sec = self.token_count / elapsed if elapsed > 0 else 0
            log(f"   Generation progress: ~{self.token_count} tokens ({tokens_per_sec:.1f} tok/s)")


# ============================
# GPU UTILITIES
# ============================


def free_gpu():
    """Best-effort GPU memory cleanup."""
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()


def get_best_gpu(min_memory_gb: int = 16) -> str:
    """
    Get the GPU with most available memory.

    Returns device string like 'cuda:0' or 'cpu' if no GPU available.
    """
    if not torch.cuda.is_available():
        return "cpu"

    num_gpus = torch.cuda.device_count()
    if num_gpus == 0:
        return "cpu"

    best_gpu = 0
    max_free = 0
    for i in range(num_gpus):
        free_mem, total_mem = torch.cuda.mem_get_info(i)
        free_gb = free_mem / (1024**3)
        total_gb = total_mem / (1024**3)
        log(f"   GPU {i}: {free_gb:.1f}GB free / {total_gb:.1f}GB total")
        if free_mem > max_free:
            max_free = free_mem
            best_gpu = i

    max_free_gb = max_free / (1024**3)
    if max_free_gb < min_memory_gb:
        log(f"WARNING: Best GPU has only {max_free_gb:.1f}GB free, model needs ~{min_memory_gb}GB")

    log(f"   Selected GPU {best_gpu} with {max_free_gb:.1f}GB free")
    return f"cuda:{best_gpu}"


# ============================
# VISION MODEL (QWEN2-VL)
# ============================

_vision_model = None
_vision_processor = None


def load_vision_model():
    """Load Qwen2-VL for image OCR."""
    global _vision_model, _vision_processor
    if _vision_model is None:
        device = get_best_gpu()
        if device != "cpu":
            device_map_value = int(device.split(":")[1])
        else:
            device_map_value = "cpu"
        log(f"Loading {VISION_MODEL_ID} for image OCR on {device}...")
        try:
            _vision_model = Qwen2VLForConditionalGeneration.from_pretrained(
                VISION_MODEL_ID,
                torch_dtype=torch.bfloat16,
                device_map=device_map_value,
            )
            _vision_processor = AutoProcessor.from_pretrained(VISION_MODEL_ID)
            log(f"   ✓ Vision model loaded on {device}")
        except Exception as e:
            log(f"   ✗ Failed to load vision model: {e}")
            if _vision_model is not None:
                del _vision_model
                _vision_model = None
            free_gpu()
            raise
    return _vision_model, _vision_processor


def unload_vision_model():
    """Unload vision model to free GPU memory."""
    global _vision_model, _vision_processor
    if _vision_model is not None:
        del _vision_model
        _vision_model = None
    if _vision_processor is not None:
        del _vision_processor
        _vision_processor = None
    free_gpu()
    log("   ✓ Vision model unloaded, GPU memory cleared")


def extract_text_with_qwen_vision(image_path: str) -> str:
    """Use Qwen2-VL for high-quality image OCR."""
    log(f"Starting vision OCR on image: {image_path}")
    model, processor = load_vision_model()

    image = Image.open(image_path).convert("RGB")
    original_size = image.size
    max_size = 1280
    if max(image.size) > max_size:
        ratio = max_size / max(image.size)
        image = image.resize(
            (int(image.size[0] * ratio), int(image.size[1] * ratio)),
            Image.Resampling.LANCZOS,
        )
        log(f"   Resized image from {original_size} to {image.size}")
    else:
        log(f"   Image size: {image.size} (no resize needed)")

    prompt = """Transcribe ALL visible text from this scientific poster exactly as written.

Include:
- Title and subtitle
- Author names and affiliations
- All section headers and content
- Algorithm/method descriptions
- Figure and table captions
- Numbers, statistics, equations
- References and URLs

Rules:
- Output the raw text ONLY
- Do NOT add explanations or interpretations
- Do NOT translate any text
- Preserve the original language
- Include all bullet points and lists"""

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": prompt},
            ],
        }
    ]

    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text], images=[image], return_tensors="pt", padding=True).to(
        model.device
    )

    t0 = time.time()
    with torch.no_grad():
        output = model.generate(**inputs, max_new_tokens=4000, do_sample=False)
    vision_elapsed = time.time() - t0
    log(f"   Vision OCR generate() finished in {vision_elapsed:.2f} seconds")

    response = processor.batch_decode(output, skip_special_tokens=True)[0]
    if "assistant" in response:
        response = response.split("assistant")[-1].strip()

    log(f"   Completed vision OCR for: {image_path}")
    return response


# ============================
# PDF TEXT EXTRACTION
# ============================


def _detect_column_boundaries(cx_values: list, page_w: float) -> list:
    """Detect column boundaries from block center-x gap analysis.

    Returns sorted list of x-positions where column boundaries occur.
    A boundary is a gap between consecutive cx values > 5% of page width.
    Requires min 3 blocks per column to be valid.
    """
    from bisect import bisect_right

    if len(cx_values) < 2:
        return []

    sorted_cx = sorted(cx_values)
    min_gap = page_w * 0.05

    # Find gaps between consecutive cx values
    gaps = []
    for i in range(1, len(sorted_cx)):
        gap = sorted_cx[i] - sorted_cx[i - 1]
        if gap > min_gap:
            boundary = (sorted_cx[i - 1] + sorted_cx[i]) / 2
            gaps.append((gap, boundary))

    # Sort by gap size descending, take up to 6 boundaries (7 columns max)
    gaps.sort(reverse=True)
    boundaries = sorted(b for _, b in gaps[:6])

    # Remove boundaries that create columns with too few blocks
    min_blocks = 3
    valid = []
    for b in boundaries:
        test_bounds = sorted(valid + [b])
        counts = [0] * (len(test_bounds) + 1)
        for cx in cx_values:
            idx = bisect_right(test_bounds, cx)
            counts[idx] += 1
        if all(c >= min_blocks for c in counts):
            valid.append(b)

    return sorted(valid)


def _detect_column_boundaries_from_gaps(lines: list,
                                        page_w: float) -> list:
    """Detect column boundaries from consistent within-line X-gaps.

    For each wide line with body-text spacing, find gaps significantly
    larger than the line's median gap. Cluster positions; a tight cluster
    with 5+ supporting lines is a column boundary.
    """
    gap_positions = []
    for line in lines:
        sw = sorted(line, key=lambda w: w["x0"])
        if len(sw) < 4:
            continue
        width = sw[-1]["x1"] - sw[0]["x0"]
        if width < page_w * 0.5:
            continue

        gaps = []
        for j in range(1, len(sw)):
            gap = sw[j]["x0"] - sw[j - 1]["x1"]
            pos = (sw[j - 1]["x1"] + sw[j]["x0"]) / 2
            gaps.append((gap, pos))

        if not gaps:
            continue

        median_gap = sorted(g for g, _ in gaps)[len(gaps) // 2]
        if median_gap > 20:
            continue
        threshold = max(median_gap * 1.8, 20)
        for gap, pos in gaps:
            if gap > threshold:
                gap_positions.append(pos)

    if len(gap_positions) < 3:
        return []

    sorted_pos = sorted(gap_positions)
    cluster_tol = page_w * 0.02
    clusters = [[sorted_pos[0]]]
    for pos in sorted_pos[1:]:
        if pos - clusters[-1][-1] < cluster_tol:
            clusters[-1].append(pos)
        else:
            clusters.append([pos])

    from bisect import bisect_right

    max_range = cluster_tol * 2
    candidates = sorted(
        sum(c) / len(c) for c in clusters
        if len(c) >= 5 and (max(c) - min(c)) <= max_range
    )[:2]

    line_cxs = []
    for line in lines:
        cx = (min(w["x0"] for w in line)
              + max(w["x1"] for w in line)) / 2
        line_cxs.append(cx)

    min_blocks = 3
    min_col_width = page_w * 0.08
    valid = []
    for b in candidates:
        test = sorted(valid + [b])
        counts = [0] * (len(test) + 1)
        for cx in line_cxs:
            counts[bisect_right(test, cx)] += 1
        if not all(c >= min_blocks for c in counts):
            continue
        edges = [0] + test + [page_w]
        widths_ok = all(
            edges[i + 1] - edges[i] >= min_col_width
            for i in range(len(edges) - 1)
        )
        if widths_ok:
            valid.append(b)

    return sorted(valid)


def _validate_boundaries(boundaries: list, lines: list,
                         page_w: float) -> list:
    """Remove boundaries that lack word-gap support from actual text lines.

    A boundary is valid only if multiple lines have a word gap (>= 15pt)
    whose midpoint falls within 5% of page width of the boundary.
    """
    if not boundaries or not lines:
        return boundaries

    tolerance = page_w * 0.05
    min_support = 3
    validated = []

    for b in boundaries:
        support = 0
        for line in lines:
            sw = sorted(line, key=lambda w: w["x0"])
            if len(sw) < 2:
                continue
            for j in range(1, len(sw)):
                gap = sw[j]["x0"] - sw[j - 1]["x1"]
                if gap < 15:
                    continue
                mid = (sw[j - 1]["x1"] + sw[j]["x0"]) / 2
                if abs(mid - b) <= tolerance:
                    support += 1
                    break
        if support >= min_support:
            validated.append(b)

    return validated


def _parse_font_style(fontname: str) -> dict:
    """Parse bold/italic from a pdfplumber fontname string.

    Font names follow the pattern 'SUBSET+FamilyName-Style' where style
    contains 'Bold', 'Italic', 'BoldItalic', etc.
    """
    lower = fontname.lower()
    suffix = lower.rsplit("-", 1)[-1] if "-" in lower else ""
    return {
        "bold": ("bold" in lower or "black" in lower or "heavy" in lower
                 or "bd" in suffix or "demi" in suffix),
        "italic": ("italic" in lower or "oblique" in lower or "it" in suffix),
    }


def _filter_phantom_spaces(chars: list) -> list:
    """Remove space characters fully contained within a non-space character.

    Some PDFs embed invisible space glyphs on top of real characters, causing
    pdfplumber's extract_words to split words at those phantom boundaries
    (e.g. "For" → "F or").  A phantom space is one whose entire horizontal
    extent [x0, x1] falls within a non-space character's [x0, x1] on the
    same line.  Legitimate word-separating spaces extend beyond the adjacent
    character's bounds and are preserved.
    """
    non_space = [(c["x0"], c["x1"], c["top"]) for c in chars if c["text"].strip()]
    if not non_space:
        return chars

    from bisect import bisect_right

    ns_by_row = {}
    for x0, x1, top in non_space:
        row = round(top)
        ns_by_row.setdefault(row, []).append((x0, x1))
    for row in ns_by_row:
        ns_by_row[row].sort()

    filtered = []
    for c in chars:
        if not c["text"].strip():
            row = round(c["top"])
            is_phantom = False
            for r in (row - 1, row, row + 1):
                intervals = ns_by_row.get(r)
                if not intervals:
                    continue
                idx = bisect_right(intervals, (c["x0"], float("inf"))) - 1
                if idx >= 0 and intervals[idx][0] <= c["x0"] + 1 and c["x1"] <= intervals[idx][1] + 1:
                    is_phantom = True
                    break
            if is_phantom:
                continue
        filtered.append(c)
    return filtered


def _annotate_words_with_fonts(words: list, chars: list) -> None:
    """Add fontname to each word from overlapping raw characters.

    pdfplumber's extract_words groups chars by extra_attrs, which means
    including fontname would break words at font-subset boundaries (e.g.
    ligature ﬀ in a different subset splitting "different" → "di|ff|erent").
    We extract with extra_attrs=["size"] only, then look up each word's
    dominant fontname from the raw chars.
    """
    from bisect import bisect_left, bisect_right

    non_space = [c for c in chars if c["text"].strip()]
    if not non_space:
        return
    non_space.sort(key=lambda c: (round(c["top"]), c["x0"]))
    tops = [round(c["top"]) for c in non_space]

    for w in words:
        w_top = round(w["top"])
        lo = bisect_left(tops, w_top - 2)
        hi = bisect_right(tops, w_top + 2)
        matching = [
            c for c in non_space[lo:hi]
            if c["x0"] >= w["x0"] - 1 and c["x1"] <= w["x1"] + 1
        ]
        if matching:
            fonts = [c["fontname"] for c in matching if c.get("fontname")]
            w["fontname"] = max(set(fonts), key=fonts.count) if fonts else ""
        else:
            w["fontname"] = ""


def _group_words_into_lines(words: list, vtol: float = 3.0) -> list:
    """Group pdfplumber words into lines by vertical proximity.

    Words within vtol points of each other vertically are on the same line.
    Returns list of lines, each a list of words sorted left-to-right.
    """
    if not words:
        return []

    sorted_words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    lines = []
    current_line = [sorted_words[0]]

    for w in sorted_words[1:]:
        if abs(w["top"] - current_line[0]["top"]) <= vtol:
            current_line.append(w)
        else:
            current_line.sort(key=lambda w: w["x0"])
            lines.append(current_line)
            current_line = [w]
    if current_line:
        current_line.sort(key=lambda w: w["x0"])
        lines.append(current_line)

    return lines


def _assign_lines_to_columns(lines: list, boundaries: list,
                              page_width: float = 0) -> list:
    """Assign lines to columns, splitting cross-column merges.

    When words at the same y-position from different columns get grouped
    into one line, this function detects the gutter gap (much wider than
    normal word spacing) and splits them apart.  Titles that intentionally
    span the full width are kept intact.
    """
    from bisect import bisect_right

    abs_split_min = page_width * 0.05 if page_width else 100

    columns = [[] for _ in range(len(boundaries) + 1)]
    for line in lines:
        sorted_words = sorted(line, key=lambda w: w["x0"])

        if len(sorted_words) < 2:
            cx = (sorted_words[0]["x0"] + sorted_words[0]["x1"]) / 2
            columns[bisect_right(boundaries, cx)].append(line)
            continue

        word_gaps = [sorted_words[i]["x0"] - sorted_words[i - 1]["x1"]
                     for i in range(1, len(sorted_words))]
        median_gap = min(sorted(word_gaps)[len(word_gaps) // 2], 50)
        gutter_min = max(median_gap * 4, 20)

        split_indices = []
        for i, gap in enumerate(word_gaps):
            if gap < gutter_min:
                continue
            left_x1 = sorted_words[i]["x1"]
            right_x0 = sorted_words[i + 1]["x0"]
            mid = (left_x1 + right_x0) / 2
            crosses = any(left_x1 <= b <= right_x0 for b in boundaries)
            near = any(abs(mid - b) < gap * 1.5 for b in boundaries)
            large = gap >= abs_split_min
            if crosses or near or large:
                split_indices.append(i + 1)

        if not split_indices:
            cx = (min(w["x0"] for w in line) + max(w["x1"] for w in line)) / 2
            columns[bisect_right(boundaries, cx)].append(line)
        else:
            cuts = [0] + split_indices + [len(sorted_words)]
            for j in range(len(cuts) - 1):
                sub = sorted_words[cuts[j]:cuts[j + 1]]
                cx = (min(w["x0"] for w in sub) + max(w["x1"] for w in sub)) / 2
                columns[bisect_right(boundaries, cx)].append(sub)

    for col in columns:
        col.sort(key=lambda line: min(w["top"] for w in line))

    return columns


def _line_is_bold(line: list) -> bool:
    """Check if a line's dominant font is bold."""
    styles = [_parse_font_style(w.get("fontname", "")) for w in line]
    bold_count = sum(1 for s in styles if s["bold"])
    return bold_count > len(styles) / 2 if styles else False


def _line_dominant_size(line: list) -> float:
    """Get the most common font size in a line."""
    sizes = [w["size"] for w in line if w.get("size", 0) > 0]
    if not sizes:
        return 0
    return max(set(sizes), key=sizes.count)


def _lines_to_blocks(lines: list, line_height_mult: float = 1.5) -> list:
    """Group vertically-sorted lines within a single column into blocks.

    A new block starts when:
      - The vertical gap exceeds line_height_mult * median line height, OR
      - The font style changes (bold to non-bold or vice versa), OR
      - The font size jumps significantly (> 1.3x ratio)
    """
    if not lines:
        return []

    line_heights = []
    for line in lines:
        h = max(w["bottom"] for w in line) - min(w["top"] for w in line)
        line_heights.append(max(h, 1.0))
    median_lh = sorted(line_heights)[len(line_heights) // 2]
    gap_threshold = median_lh * line_height_mult

    block_groups = [[lines[0]]]
    for i in range(1, len(lines)):
        prev_bottom = max(w["bottom"] for w in lines[i - 1])
        curr_top = min(w["top"] for w in lines[i])
        gap = curr_top - prev_bottom

        prev_bold = _line_is_bold(lines[i - 1])
        curr_bold = _line_is_bold(lines[i])
        prev_size = _line_dominant_size(lines[i - 1])
        curr_size = _line_dominant_size(lines[i])
        size_ratio = max(curr_size, prev_size) / max(min(curr_size, prev_size), 0.1)

        style_break = False
        if size_ratio > 1.3:
            style_break = True
        elif prev_bold != curr_bold and gap > 0:
            curr_text = " ".join(w["text"] for w in lines[i])
            prev_text = " ".join(w["text"] for w in lines[i - 1])
            short_line = len(curr_text) <= 120 or len(prev_text) <= 120
            if short_line:
                style_break = True

        if gap > gap_threshold or style_break:
            block_groups.append([lines[i]])
        else:
            block_groups[-1].append(lines[i])

    blocks = []
    for group in block_groups:
        all_words = [w for line in group for w in line]
        x0 = min(w["x0"] for w in all_words)
        top = min(w["top"] for w in all_words)
        x1 = max(w["x1"] for w in all_words)
        bottom = max(w["bottom"] for w in all_words)
        bw = x1 - x0
        bh = bottom - top
        cx = x0 + bw / 2

        seen_texts = []
        deduped_lines = []
        for line in group:
            line_top = min(w["top"] for w in line)
            line_words = set(w["text"] for w in line)
            line_text = " ".join(w["text"] for w in line)

            is_dup = False
            for sv, sw, _ in seen_texts:
                if abs(sv - line_top) < 2:
                    if line_words and sw:
                        overlap = len(line_words & sw) / max(len(line_words), len(sw))
                        if overlap > 0.8:
                            is_dup = True
                            break
            if not is_dup:
                seen_texts.append((line_top, line_words, line_text))
                deduped_lines.append(line_text)

        if not deduped_lines:
            continue

        block_text = " ".join(deduped_lines)

        fontsizes = [w["size"] for w in all_words if w.get("size", 0) > 0]
        fontnames = [w["fontname"] for w in all_words if w.get("fontname")]

        dominant_size = max(set(fontsizes), key=fontsizes.count) if fontsizes else 0
        styles = [_parse_font_style(fn) for fn in fontnames]
        bold_count = sum(1 for s in styles if s["bold"])
        is_bold = bold_count > len(styles) / 2 if styles else False

        blocks.append({
            "hpos": x0,
            "vpos": top,
            "width": bw,
            "height": bh,
            "cx": cx,
            "text": block_text,
            "fontsize": dominant_size,
            "bold": is_bold,
        })

    return blocks


def _chars_to_word_lines(char_lines, words):
    """Map XY-cut char-level lines back to word-level lines.

    For each char-level line, find the words whose characters
    predominantly fall on that line (by spatial overlap).
    """
    from bisect import bisect_left, bisect_right

    word_tops = sorted(set(w["top"] for w in words))
    word_by_pos = {}
    for w in words:
        key = (round(w["top"], 1), round(w["x0"], 1))
        word_by_pos[key] = w

    assigned = set()
    result = []
    for char_line in char_lines:
        if not char_line:
            continue
        line_y_min = min(c["top"] for c in char_line)
        line_y_max = max(c["bottom"] for c in char_line)
        line_x_min = min(c["x0"] for c in char_line)
        line_x_max = max(c["x1"] for c in char_line)

        line_words = []
        for w in words:
            if id(w) in assigned:
                continue
            w_cy = (w["top"] + w["bottom"]) / 2
            w_cx = (w["x0"] + w["x1"]) / 2
            if (line_y_min - 2 <= w_cy <= line_y_max + 2
                    and line_x_min - 5 <= w_cx <= line_x_max + 5):
                line_words.append(w)
                assigned.add(id(w))

        if line_words:
            line_words.sort(key=lambda w: w["x0"])
            result.append(line_words)

    unassigned = [w for w in words if id(w) not in assigned]
    if unassigned:
        unassigned.sort(key=lambda w: (w["top"], w["x0"]))
        cur = [unassigned[0]]
        for w in unassigned[1:]:
            if abs(w["top"] - cur[0]["top"]) <= 3:
                cur.append(w)
            else:
                result.append(sorted(cur, key=lambda w: w["x0"]))
                cur = [w]
        if cur:
            result.append(sorted(cur, key=lambda w: w["x0"]))

    return result


def _split_inline_sections(text: str):
    """Split a run-on block at inline ALL-CAPS section labels and em-dash
    sub-headers. Returns a list of (heading_or_None, body) segments, or None
    if the block contains no inline boundary (the common case)."""
    marks = []
    for m in _INLINE_LABEL_RE.finditer(text):
        marks.append((m.start(), m.end(), m.group(1).title()))
    for m in _INLINE_DASH_HEAD_RE.finditer(text):
        marks.append((m.start(), m.end(), m.group(1).title()))
    if not marks:
        return None
    marks.sort()
    segments = []
    pre = text[:marks[0][0]].strip()
    if pre:
        segments.append((None, pre))
    for i, (_s, end, heading) in enumerate(marks):
        nxt = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        segments.append((heading, text[end:nxt].strip()))
    return segments


def extract_text_with_pdfplumber(pdf_path: str) -> Optional[str]:
    """Extract text from PDF using pdfplumber (layout-aware).

    Uses recursive XY-cut tree (ported from xpdf's splitChars algorithm)
    to determine reading order, then groups words into blocks and
    prefixes headers with '## ' based on font size/style analysis.

    Pipeline:
      1. Extract chars and words with (x0, y0, x1, y1, fontname, size)
      2. Recursive XY-cut on chars to determine reading order
      3. Map char-level lines back to word-level lines
      4. Group word lines into blocks by vertical gaps
      5. Classify blocks as header/meta/body/footer
      6. Detect headers via font size/bold heuristics
    """
    import pdfplumber

    log(f"Attempting text extraction with pdfplumber for: {pdf_path}")
    t0 = time.time()

    try:
        pdf = pdfplumber.open(pdf_path)
    except Exception as e:
        log(f"pdfplumber failed to open {pdf_path}: {e}")
        return None

    all_output_lines = []

    try:
        for page in pdf.pages:
            page_w = page.width
            page_h = page.height

            from pdfplumber.utils.text import extract_words as _pw_extract_words
            chars = _filter_phantom_spaces(page.chars)

            text_chars = [c for c in chars if c.get("text", "").strip()]
            if text_chars:
                median_fs = float(np.median([c["size"] for c in text_chars]))
                x_tol = round(max(1.5, min(median_fs * 0.25, 3.0)), 2)
                space_chars = [c for c in chars if c.get("text") == " " and c["x1"] - c["x0"] > 0]
                if space_chars:
                    space_w = float(np.median([c["x1"] - c["x0"] for c in space_chars]))
                    x_tol = round(min(x_tol, space_w * 0.7), 2)
            else:
                x_tol = 3
            log(f"   x_tolerance={x_tol} (median_font={median_fs if text_chars else '?'}pt)")
            words = _pw_extract_words(chars, x_tolerance=x_tol,
                                     extra_attrs=["size"],
                                     use_text_flow=True)
            _annotate_words_with_fonts(words, chars)
            if not words:
                continue

            from poster2json.xy_cut import chars_to_reading_order

            reading_lines = chars_to_reading_order(chars, page_width=page_w, page_height=page_h)
            if not reading_lines:
                continue

            word_lines = _chars_to_word_lines(reading_lines, words)
            all_blocks = _lines_to_blocks(word_lines)
            for blk in all_blocks:
                blk["col"] = 0
                blk["flow_idx"] = 0

            if not all_blocks:
                continue

            all_fontsizes = [blk["fontsize"] for blk in all_blocks if blk["fontsize"] > 0]
            page_median_fs = sorted(all_fontsizes)[len(all_fontsizes) // 2] if all_fontsizes else 0

            text_left = min(blk["hpos"] for blk in all_blocks)
            text_right = max(blk["hpos"] + blk["width"] for blk in all_blocks)
            text_span = text_right - text_left
            span_threshold = text_span * 0.5

            min_col_block_len = 10
            col_tops = {}
            for blk in all_blocks:
                c = blk["col"]
                if blk["width"] <= span_threshold and len(blk["text"].strip()) >= min_col_block_len:
                    col_tops[c] = min(col_tops.get(c, float("inf")), blk["vpos"])
            if not col_tops:
                for blk in all_blocks:
                    c = blk["col"]
                    if blk["width"] <= span_threshold:
                        col_tops[c] = min(col_tops.get(c, float("inf")), blk["vpos"])
            col_start = min(col_tops.values()) if col_tops else 0
            col_end = max(blk["vpos"] + blk["height"] for blk in all_blocks
                         if blk["width"] <= span_threshold) if col_tops else page_h

            _meta_re = re.compile(
                r'@\S+\.\S+|orcid\.org|ORCID:\s*\d|^Authors?\b',
            )
            top_zone = page_h * 0.12
            header_blocks = []
            meta_blocks = []
            body_blocks = []
            footer_blocks = []
            for blk in all_blocks:
                is_wide = blk["width"] > span_threshold
                is_title_font = page_median_fs > 0 and blk["fontsize"] >= page_median_fs * 1.4
                if is_title_font and blk["vpos"] + blk["height"] <= col_start + page_h * 0.02:
                    header_blocks.append(blk)
                elif is_wide and blk["vpos"] > col_end:
                    footer_blocks.append(blk)
                elif (not is_wide
                      and blk["vpos"] + blk["height"] <= top_zone
                      and _meta_re.search(blk["text"])):
                    meta_blocks.append(blk)
                else:
                    body_blocks.append(blk)

            header_blocks.sort(key=lambda b: b["vpos"])
            meta_blocks.sort(key=lambda b: (b["vpos"], b["hpos"]))
            footer_blocks.sort(key=lambda b: b["vpos"])
            all_blocks = header_blocks + meta_blocks + body_blocks + footer_blocks

            median_fontsize = page_median_fs

            for blk in all_blocks:
                _t = blk["text"].strip()
                if not _t:
                    continue

                # Figure/table caption: split the "Figure N"/"Table N" label
                # onto its own header line so the LLM isolates the caption as a
                # caption section instead of merging it into adjacent body text.
                # Captions are small-font, so the font-size header heuristic
                # below never catches them; a buried short caption tanks
                # section-level ROUGE (matches at ~0.2 instead of ~1.0).
                _cap = re.match(
                    r"^[^A-Za-z]*(fig(?:ure)?|tab(?:le)?)\.?\s*(\d+)\s*[.:]\s*(\S.*)$",
                    _t, re.IGNORECASE | re.DOTALL,
                )
                if _cap:
                    _kind = "Figure" if _cap.group(1)[:3].lower() == "fig" else "Table"
                    all_output_lines.append(f"## {_kind} {_cap.group(2)}")
                    all_output_lines.append(_add_bidi_markers(_cap.group(3).strip()))
                    continue

                # Standalone section heading printed as a bare keyword line
                # (e.g. "References", "Acknowledgements"). Force a ## header so
                # the LLM splits it out instead of merging it into the body.
                if _t.rstrip(":.").strip().lower() in _SECTION_KEYWORDS:
                    all_output_lines.append(f"## {_add_bidi_markers(_t)}")
                    continue

                # Run-on block cramming multiple sections onto one line via
                # inline ALL-CAPS labels ("...REFERENCES: ... ABBREVIATIONS: ...")
                # or em-dash sub-headers ("265. TWINS — Our second sample ...").
                # Split into labeled sections so the LLM doesn't merge them.
                _segs = _split_inline_sections(_t)
                if _segs:
                    for _head, _body in _segs:
                        if _head:
                            all_output_lines.append(f"## {_head}")
                        if _body:
                            all_output_lines.append(_add_bidi_markers(_body))
                    continue

                _words = _t.split()
                _single_char = sum(1 for w in _words if len(w) <= 1)
                if len(_words) >= 2 and _single_char > len(_words) * 0.6:
                    continue
                if len(_t) <= 3 and not re.match(r'^[•●▪]+$', _t):
                    continue
                _alpha_words = re.findall(r'[A-Za-z]{2,}', _t)
                _starts_with_letter = bool(re.match(r'[A-Za-z]', _t))
                _is_contact = bool(
                    re.search(r'@\S+\.\S+', _t)
                    or re.search(r'\+\d[\d\s]{6,}', _t)
                    or re.search(r'www\.', _t, re.I)
                    or re.search(r'https?://', _t, re.I)
                )

                is_header = False
                _is_continuation = bool(re.match(
                    r'(?:to|and|or|the|a|an|in|of|for|with|by|from|that|which|when)\s', _t
                ))
                min_words = 1 if blk["bold"] else 2
                if (median_fontsize > 0 and len(_t) <= 120
                        and _starts_with_letter and len(_alpha_words) >= min_words
                        and not _is_contact and not _is_continuation):
                    fs = blk["fontsize"]
                    if blk["bold"] and fs >= median_fontsize:
                        is_header = True
                    elif fs > median_fontsize * 1.3:
                        if len(_alpha_words) == 1:
                            is_header = _alpha_words[0].isupper()
                        else:
                            is_header = True

                text = _add_bidi_markers(blk["text"])
                if is_header:
                    text = f"## {text}"
                all_output_lines.append(text)

    finally:
        pdf.close()

    elapsed = time.time() - t0

    if not all_output_lines:
        log(f"pdfplumber produced no text for: {pdf_path}")
        return None

    result = "\n".join(all_output_lines)
    log(f"pdfplumber extracted {len(result)} characters in {elapsed:.2f} seconds")
    return result


def extract_text_with_pymupdf(pdf_path: str) -> str:
    """Fallback text extraction using PyMuPDF."""
    import fitz

    log(f"Attempting text extraction with PyMuPDF for: {pdf_path}")
    t0 = time.time()
    doc = fitz.open(pdf_path)
    text = "\n".join(page.get_text("text") for page in doc)
    doc.close()
    elapsed = time.time() - t0
    log(f"PyMuPDF extracted {len(text)} characters in {elapsed:.2f} seconds")
    return text.strip()


MIN_PDF_TEXT_CHARS = 200

# Above this page-0 character count, skip pdfplumber's XY-cut reading-order
# engine (which can hang for many minutes and exhaust system RAM on pathological
# PDFs — e.g. vectorised text or millions of glyphs) and use the bounded PyMuPDF
# extractor instead.
MAX_PDFPLUMBER_CHARS = 30000


def _pdf_char_count(pdf_path: str) -> int:
    """Cheap character-count probe via PyMuPDF, used to gate the expensive
    pdfplumber reading-order engine. Stops early once well past any threshold."""
    try:
        import fitz
        doc = fitz.open(pdf_path)
        n = 0
        for page in doc:
            n += len(page.get_text("text"))
            if n > 200000:
                break
        doc.close()
        return n
    except Exception:
        return 0


def extract_pdf_link_annotations(pdf_path: str) -> list:
    """Extract URI link annotations embedded in a PDF.

    Returns a deduplicated list of URI strings found via PyMuPDF
    page.get_links(). These are clickable links in the PDF annotation
    layer, independent of any selectable text.
    """
    import fitz

    seen = set()
    uris = []
    try:
        doc = fitz.open(pdf_path)
        for page in doc:
            for link in page.get_links():
                uri = link.get("uri", "")
                if uri and uri not in seen:
                    seen.add(uri)
                    uris.append(uri)
        doc.close()
    except Exception as e:
        log(f"Failed to extract PDF link annotations: {e}")
    if uris:
        log(f"Extracted {len(uris)} link annotations from PDF")
    return uris


def _render_pdf_to_image(pdf_path: str) -> Optional[str]:
    """Render the first page of a PDF to a temporary PNG for vision OCR."""
    import fitz
    import tempfile

    log(f"Rendering PDF page to image for vision OCR: {pdf_path}")
    try:
        doc = fitz.open(pdf_path)
        page = doc[0]
        zoom = 2.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        pix.save(tmp.name)
        doc.close()
        log(f"   Rendered page to {pix.width}x{pix.height} image: {tmp.name}")
        return tmp.name
    except Exception as e:
        log(f"   Failed to render PDF to image: {e}")
        return None


def get_raw_text(
    poster_path: str, poster_id: str = None, output_dir: str = None
) -> Tuple[str, str]:
    """
    Get raw text from a poster file.

    Args:
        poster_path: Path to poster file (PDF, JPG, PNG)
        poster_id: Optional ID for caching
        output_dir: Optional directory for cached results

    Returns:
        Tuple of (text, source) where source indicates extraction method
    """
    log(f"Starting raw text extraction for: {poster_path}")
    ext = Path(poster_path).suffix.lower()

    if ext in [".jpg", ".jpeg", ".png"]:
        # Check cache
        if output_dir and poster_id:
            for ext_check in [".md", ".txt"]:
                cache_file = Path(output_dir) / f"{poster_id}_raw{ext_check}"
                if cache_file.exists():
                    with open(cache_file) as f:
                        text = f.read()
                    if len(text) > 500:
                        log(f"Using cached OCR text ({len(text)} characters)")
                        return text, "qwen_vision_cached"

        text = extract_text_with_qwen_vision(poster_path)
        log(f"Image OCR produced {len(text)} characters")
        return text, "qwen_vision"

    if ext == ".pdf":
        # Guard: pdfplumber's XY-cut reading-order engine can hang and blow up
        # memory on pathological PDFs with very high character counts. Probe the
        # char count cheaply with PyMuPDF and skip pdfplumber for oversized pages.
        if _pdf_char_count(poster_path) <= MAX_PDFPLUMBER_CHARS:
            text = extract_text_with_pdfplumber(poster_path)
            if text and len(text.strip()) >= MIN_PDF_TEXT_CHARS:
                log(f"Using pdfplumber output ({len(text)} characters)")
                return text, "pdfplumber"
        else:
            log(f"PDF exceeds {MAX_PDFPLUMBER_CHARS} chars; skipping pdfplumber "
                f"(XY-cut) to avoid hang/OOM, falling back to PyMuPDF")
        text = extract_text_with_pymupdf(poster_path)
        if text and len(text.strip()) >= MIN_PDF_TEXT_CHARS:
            log(f"Using PyMuPDF fallback ({len(text)} characters)")
            return text, "pymupdf"

        log(f"PDF text extraction yielded only {len(text.strip()) if text else 0} chars, "
            f"falling back to vision OCR")
        unload_json_model()
        img_path = _render_pdf_to_image(poster_path)
        if img_path:
            try:
                ocr_text = extract_text_with_qwen_vision(img_path)
                if ocr_text and len(ocr_text.strip()) > len(text.strip() if text else ""):
                    log(f"Vision OCR fallback produced {len(ocr_text)} characters")
                    return ocr_text, "qwen_vision_pdf"
            finally:
                try:
                    os.remove(img_path)
                except OSError:
                    pass

        if text and text.strip():
            log(f"Vision OCR did not improve; using PyMuPDF ({len(text)} chars)")
            return text, "pymupdf"

        return "", "unknown"

    return "", "unknown"


# ============================
# JSON MODEL (LLAMA)
# ============================

_json_model = None
_json_tokenizer = None


def load_json_model(
    model_id: Optional[str] = None,
    quantization: Optional[str] = None,
):
    """Load the JSON-structuring LLM.

    Args:
        model_id: override the default JSON_MODEL_ID. Accepts any HuggingFace
            repo id (e.g. the default Llama-3.1-8B-Instruct, or a generic
            instruct model like google/gemma-2-9b-it, Qwen/Qwen2.5-7B-Instruct).
        quantization: precision mode — one of "fp16", "8bit", "4bit".
            Defaults to "4bit" (NF4), which fits on ~6GB VRAM.
    """
    global _json_model, _json_tokenizer
    resolved_model_id = model_id or JSON_MODEL_ID
    if _json_model is None:
        device = get_best_gpu()

        if device != "cpu":
            gpu_id = int(device.split(":")[1])
            free_mem, _ = torch.cuda.mem_get_info(gpu_id)
            free_gb = free_mem / (1024**3)
            device_map_value = gpu_id
        else:
            free_gb = 32
            device_map_value = "cpu"

        log(f"Loading {resolved_model_id} for JSON structuring on {device}...")

        try:
            _json_tokenizer = AutoTokenizer.from_pretrained(resolved_model_id)

            mode = (quantization or "4bit").lower()
            if mode not in {"fp16", "8bit", "4bit"}:
                raise ValueError(
                    f"quantization must be one of fp16|8bit|4bit, got {quantization!r}"
                )

            # Try Flash Attention 2
            try:
                import flash_attn

                attn_impl = "flash_attention_2"
                log("   Using Flash Attention 2 for faster inference")
            except ImportError:
                attn_impl = None
                log("   Flash Attention not available, using default attention")

            model_kwargs = {
                "device_map": device_map_value,
                "low_cpu_mem_usage": True,
            }
            if attn_impl:
                model_kwargs["attn_implementation"] = attn_impl

            if mode == "8bit":
                log(f"   Using 8-bit quantization (free={free_gb:.1f}GB)")
                model_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
            elif mode == "4bit":
                log(f"   Using 4-bit NF4 quantization (free={free_gb:.1f}GB)")
                model_kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=torch.bfloat16,
                    bnb_4bit_use_double_quant=True,
                )
            else:  # fp16 (bfloat16)
                log(f"   Using bfloat16 (free={free_gb:.1f}GB)")
                model_kwargs["torch_dtype"] = torch.bfloat16

            _json_model = AutoModelForCausalLM.from_pretrained(resolved_model_id, **model_kwargs)
            log(f"   ✓ JSON model loaded on {device} ({mode})")
        except Exception as e:
            log(f"   ✗ Failed to load JSON model: {e}")
            if _json_model is not None:
                del _json_model
                _json_model = None
            if _json_tokenizer is not None:
                del _json_tokenizer
                _json_tokenizer = None
            free_gpu()
            raise
    return _json_model, _json_tokenizer


def unload_json_model():
    """Unload JSON model to free GPU memory."""
    global _json_model, _json_tokenizer
    if _json_model is not None:
        del _json_model
        _json_model = None
    if _json_tokenizer is not None:
        del _json_tokenizer
        _json_tokenizer = None
    free_gpu()
    log("   ✓ JSON model unloaded, GPU memory cleared")


def _get_eos_token_ids(tokenizer):
    """Collect all EOS-like token IDs from the tokenizer."""
    eos_ids = set()
    eid = tokenizer.eos_token_id
    if isinstance(eid, (list, tuple)):
        eos_ids.update(eid)
    elif eid is not None:
        eos_ids.add(eid)
    for tok in ("<|end_of_text|>", "<|eom_id|>", "<|eot_id|>"):
        tid = tokenizer.convert_tokens_to_ids(tok)
        if tid is not None and tid != tokenizer.unk_token_id:
            eos_ids.add(tid)
    return eos_ids


class _JsonBraceProcessor(LogitsProcessor):
    """Suppress EOS tokens until generated JSON has balanced braces.

    Llama 3.1 has three EOS tokens (128001, 128008, 128009).
    HuggingFace's min_new_tokens only suppresses the primary one,
    so the model hits <|eot_id|> early and produces truncated JSON.
    This processor suppresses all EOS tokens until the outermost
    JSON object is closed (brace depth returns to 0).
    """

    def __init__(self, eos_token_ids, tokenizer, input_length):
        self.eos_token_ids = eos_token_ids
        self.tokenizer = tokenizer
        self.input_length = input_length
        self._prev_len = 0
        self._depth = 0
        self._in_string = False
        self._escape = False
        self._seen_brace = False

    def _update_depth(self, text):
        for ch in text:
            if self._escape:
                self._escape = False
                continue
            if ch == '\\' and self._in_string:
                self._escape = True
                continue
            if ch == '"':
                self._in_string = not self._in_string
                continue
            if not self._in_string:
                if ch == '{':
                    self._depth += 1
                    self._seen_brace = True
                elif ch == '}':
                    self._depth -= 1

    def __call__(self, input_ids, scores):
        gen = input_ids[0, self.input_length :]
        n = len(gen)
        if n == 0:
            for eid in self.eos_token_ids:
                scores[:, eid] = float("-inf")
            return scores
        if n > self._prev_len:
            new_text = self.tokenizer.decode(
                gen[self._prev_len :], skip_special_tokens=True
            )
            self._update_depth(new_text)
            self._prev_len = n
        if not self._seen_brace or self._depth > 0:
            for eid in self.eos_token_ids:
                scores[:, eid] = float("-inf")
        return scores


def _generate(model, tokenizer, prompt: str, max_tokens: int) -> str:
    """Generate response using the Llama model."""
    messages = [{"role": "user", "content": prompt}]
    input_text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(input_text, return_tensors="pt").to(model.device)
    input_length = inputs["input_ids"].shape[1]

    log(f"Generating with max_tokens={max_tokens}, input_length={input_length}")

    eos_ids = _get_eos_token_ids(tokenizer)
    processor = _JsonBraceProcessor(eos_ids, tokenizer, input_length)

    streamer = ProgressStreamer(tokenizer, log_every=200)
    t0 = time.time()
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_tokens,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
            streamer=streamer,
            logits_processor=LogitsProcessorList([processor]),
        )
    elapsed = time.time() - t0
    tokens_generated = outputs.shape[1] - input_length
    log(
        f"   Generated {tokens_generated} tokens in {elapsed:.2f}s ({tokens_generated/elapsed:.1f} tok/s)"
    )

    return tokenizer.decode(outputs[0][input_length:], skip_special_tokens=True)


# ============================
# EXTRACTION PROMPTS
# ============================

EXTRACTION_PROMPT = """Convert this scientific poster text to JSON format.

CRITICAL RULES:
1. Extract ALL required fields: creators, titles, subjects, descriptions
2. Create SEPARATE sections for EACH distinct topic/header found in the poster
3. Use the poster's OWN section headers exactly as they appear. Lines prefixed with "## " indicate detected headers from the poster layout. Standard headers (Abstract, Introduction, Methods, Results, Discussion, Conclusions, References, Acknowledgements) are common examples, but always prefer the poster's actual headers over generic ones.
4. Each section must have its OWN "sectionTitle" and "sectionContent"
5. Copy ALL poster text EXACTLY into sections - do not paraphrase, summarize, or skip any text. Every line of the poster text below must appear in your output.
6. "Key Findings" ≠ "References": Key Findings = discoveries/results; References = numbered citations with authors/years
7. Figure/table captions belong in imageCaptions/tableCaptions, NOT inside sectionContent.
8. Text without a clear header (e.g. contact info, URLs, footer text) is still a section — use "sectionTitle": "" with the verbatim text as "sectionContent". Do NOT skip any poster text.

JSON SCHEMA (all top-level fields are REQUIRED):
{{
  "creators": [
    {{"name": "LastName, FirstName", "givenName": "FirstName", "familyName": "LastName", "affiliation": ["Institution Name"]}}
  ],
  "titles": [{{"title": "Main Poster Title"}}],
  "subjects": [{{"subject": "keyword1"}}, {{"subject": "keyword2"}}, {{"subject": "keyword3"}}],
  "descriptions": [{{"description": "A 3-4 sentence summary of the full poster..."}}],
  "researchField": null,
  "content": {{
    "sections": [
      {{"sectionTitle": "Introduction", "sectionContent": "Full verbatim text of this section from the poster..."}},
      {{"sectionTitle": "Methods", "sectionContent": "Full verbatim text of this section from the poster..."}},
      {{"sectionTitle": "Results", "sectionContent": "Full verbatim text of this section from the poster..."}}
    ]
  }},
  "imageCaptions": [],
  "tableCaptions": []
}}

EXTRACTION NOTES:
- subjects: Extract 3-5 keywords from poster content
- descriptions: Write a 3-4 sentence summary of the full poster.
- titles: If the poster title is ALL CAPS, convert to proper Title Case preserving acronyms (e.g. "RESEARCH ON SARS-CoV-2" not "RESEARCH ON SARS-COV-2")- imageCaptions/tableCaptions: Include captions for figures/tables on the poster. If none exist, use [].
- researchField: MUST be exactly one of: "Health Sciences" | "Life Sciences" | "Physical Sciences" | "Social Sciences" — or null if unclear.
- GROUNDING: Only extract values that appear as text on the poster — do not invent metadata. For section content, copy ALL text verbatim — do not skip or shorten.

POSTER TEXT TO CONVERT:
{raw_text}

OUTPUT VALID JSON ONLY:"""

FALLBACK_PROMPT = """Convert poster text to JSON. REQUIRED FIELDS:
1. creators, titles, subjects, descriptions, content
2. SEPARATE section for EACH header found in the poster text. Use the poster's own headers. Lines starting with "## " are detected headers.
3. Copy ALL text EXACTLY verbatim — every line of poster text must appear in a section
4. If title is ALL CAPS, convert to Title Case preserving acronyms (SARS-CoV-2, not SARS-COV-2)
5. imageCaptions/tableCaptions: for figures/tables on the poster. If none, use [].

{{
  "creators": [{{"name": "LastName, FirstName", "givenName": "FirstName", "familyName": "LastName", "affiliation": ["Institution"]}}],
  "titles": [{{"title": "Poster Title"}}],
  "subjects": [{{"subject": "keyword1"}}, {{"subject": "keyword2"}}],
  "descriptions": [{{"description": "3-4 sentence summary of the full poster"}}],
  "researchField": null,
  "content": {{
    "sections": [{{"sectionTitle": "Header", "sectionContent": "Full verbatim text of this section..."}}]
  }},
  "imageCaptions": [],
  "tableCaptions": []
}}

researchField MUST be exactly one of: "Health Sciences", "Life Sciences", "Physical Sciences", "Social Sciences" — or null if unclear.

TEXT:
{raw_text}

JSON:"""


# ============================
# JSON PARSING & REPAIR
# ============================


def _is_truncated(json_str: str) -> bool:
    """Check if JSON output was truncated."""
    open_braces = json_str.count("{") - json_str.count("}")
    open_brackets = json_str.count("[") - json_str.count("]")
    if open_braces > 0 or open_brackets > 0:
        return True
    if json_str.rstrip().endswith((",", ":", '"')):
        return True
    return False


def _extract_first_json_object(s: str) -> str:
    """Extract first complete JSON object from string."""
    if not s or s[0] != "{":
        return ""
    depth = 0
    in_string = False
    escape_next = False

    for i, char in enumerate(s):
        if escape_next:
            escape_next = False
            continue
        if char == "\\" and in_string:
            escape_next = True
            continue
        if char == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return s[: i + 1]
    return s


def _repair_unescaped_quotes(s: str) -> str:
    """Fix unescaped double-quotes inside JSON string values.

    Walks the JSON character-by-character. When inside a string value,
    any `"` that would prematurely close the string (i.e. the character
    after it doesn't look like valid JSON structure) gets escaped.
    Handles code snippets, citations, and nested speech the LLM failed
    to escape.
    """
    result = []
    i = 0
    n = len(s)
    in_string = False
    is_key = True

    while i < n:
        c = s[i]

        if not in_string:
            result.append(c)
            if c == '"':
                in_string = True
                is_key = not any(
                    s[j] == ":" for j in range(len(result) - 2, max(len(result) - 20, -1), -1)
                    if j >= 0 and s[j] == ":"
                )
            i += 1
            continue

        if c == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if nxt in '"\\/bfnrtu':
                result.append(c)
                result.append(nxt)
            else:
                result.append("\\\\")
                result.append(nxt)
            i += 2
            continue

        if c == '"':
            j = i + 1
            while j < n and s[j] in " \t\r\n":
                j += 1
            if j >= n:
                result.append(c)
                in_string = False
            elif s[j] in "}]":
                result.append(c)
                in_string = False
            elif s[j] == ":":
                result.append(c)
                in_string = False
            elif s[j] == ",":
                k = j + 1
                while k < n and s[k] in " \t\r\n":
                    k += 1
                if k < n and s[k] in '"{[0123456789tfn-':
                    result.append(c)
                    in_string = False
                else:
                    result.append('\\"')
            else:
                result.append('\\"')
            i += 1
            continue

        if c == "\n":
            result.append("\\n")
            i += 1
            continue
        if c == "\r":
            result.append("\\r")
            i += 1
            continue
        if c == "\t":
            result.append("\\t")
            i += 1
            continue
        if ord(c) < 0x20:
            result.append(f"\\u{ord(c):04x}")
            i += 1
            continue

        result.append(c)
        i += 1

    return "".join(result)


def _repair_trailing_commas(s: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", s)


def _repair_unicode(s: str) -> str:
    s = re.sub(r"\\u[0-9a-fA-F]{0,3}(?![0-9a-fA-F])", "", s)
    s = re.sub(r"[\x00-\x1f]", " ", s)
    return s


def _repair_truncation(s: str) -> str:
    s = _repair_trailing_commas(s)
    in_string = False
    escape = False
    open_braces = 0
    open_brackets = 0

    for c in s:
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            open_braces += 1
        elif c == "}":
            open_braces -= 1
        elif c == "[":
            open_brackets += 1
        elif c == "]":
            open_brackets -= 1

    if in_string:
        s = s.rstrip()
        if not s.endswith('"'):
            s += '"'
        if '"sectionContent":' in s[-1000:] or "sectionContent" in s[-500:]:
            open_braces += 1

    s = s.rstrip()
    while s and s[-1] not in '{}[]"0123456789truefalsenull':
        s = s[:-1].rstrip()
    if s.endswith(","):
        s = s[:-1]

    partial_literals = {
        "n": "null", "nu": "null", "nul": "null",
        "t": "true", "tr": "true", "tru": "true",
        "f": "false", "fa": "false", "fal": "false", "fals": "false",
    }
    for partial, full in partial_literals.items():
        if s.endswith(": " + partial) or s.endswith(":" + partial):
            s = s[:-(len(partial))] + full
            break

    s += "]" * max(0, open_brackets) + "}" * max(0, open_braces)
    return s


def _repair_all(s: str) -> str:
    s = _repair_unescaped_quotes(s)
    s = _repair_unicode(s)
    s = _repair_trailing_commas(s)
    s = _repair_truncation(s)
    return s


def _robust_json_parse(response: str) -> dict:
    """Robustly parse JSON from LLM response."""
    response = response.strip()

    # Handle markdown code blocks
    if "```json" in response:
        start_marker = response.find("```json")
        end_marker = response.find("```", start_marker + 7)
        if end_marker > start_marker:
            response = response[start_marker + 7 : end_marker]
    elif "```" in response:
        start_marker = response.find("```")
        end_marker = response.find("```", start_marker + 3)
        if end_marker > start_marker:
            response = response[start_marker + 3 : end_marker]

    response = response.strip()
    start = response.find("{")
    if start == -1:
        return {"error": "No JSON found", "raw": response[:3000]}

    json_str = response[start:]
    json_str = _repair_unescaped_quotes(json_str)

    extracted = _extract_first_json_object(json_str)
    if extracted:
        json_str = extracted

    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    repair_funcs = [
        _repair_unescaped_quotes,
        _repair_trailing_commas,
        _repair_unicode,
        _repair_truncation,
        _repair_all,
    ]

    for repair_func in repair_funcs:
        try:
            repaired = repair_func(json_str)
            return json.loads(repaired)
        except Exception:
            continue

    try:
        repaired = _repair_all(_repair_unescaped_quotes(json_str))
        return json.loads(repaired)
    except Exception:
        pass

    # Last resort: json_repair library (MIT, zero-dep, LLM-aware)
    try:
        from json_repair import repair_json

        repaired = repair_json(json_str, return_objects=False)
        return json.loads(repaired)
    except Exception:
        pass

    return {"error": "JSON parse failed", "raw": json_str[:3000]}


# ============================
# POST-PROCESSING
# ============================


def _add_bidi_markers(text: str) -> str:
    """Wrap RTL character runs in bidi embedding markers.

    pdfplumber does not emit bidi markers around Hebrew, Arabic, and other
    RTL words. Without them the LLM receives bare RTL codepoints in an
    unstructured layout and fails to extract sections.
    """
    if not text:
        return text
    has_rtl = False
    for ch in text:
        if unicodedata.bidirectional(ch) in ("R", "AL"):
            has_rtl = True
            break
    if not has_rtl:
        return text
    words = text.split(" ")
    result = []
    for word in words:
        if any(unicodedata.bidirectional(c) in ("R", "AL") for c in word):
            result.append(f"‫{word}‬")
        else:
            result.append(word)
    return " ".join(result)


def _clean_unicode_artifacts(text: str) -> str:
    """Remove bidirectional Unicode markers and other artifacts.

    NFKC composes accented characters back to single codepoints (\u00e9 as one
    codepoint, not e + combining acute) \u2014 required for downstream consumers
    that compare strings byte-for-byte (Spanish, German, French posters).
    NFKD is still used pre-LLM in `_normalize_raw_text_for_model` because
    decomposition cuts token count on superscripts/subscripts.
    """
    if not isinstance(text, str):
        return text

    bidi_chars = [
        "\u200e",
        "\u200f",
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
        "\u200b",
        "\u200c",
        "\u200d",
        "\ufeff",
        "\u00ad",
    ]
    for char in bidi_chars:
        text = text.replace(char, "")

    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[\u00a0\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]", " ", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def _normalize_captions(captions_input, caption_type: str = "fig") -> list:
    """Normalize captions to object format with id and caption fields.

    Auto-generates missing IDs as {caption_type}1, {caption_type}2, etc.
    """
    normalized = []
    seen_texts = set()

    # Handle various input formats
    if isinstance(captions_input, str):
        return [{"id": f"{caption_type}1", "caption": captions_input}] if captions_input.strip() else []

    if not isinstance(captions_input, list):
        return []

    for idx, item in enumerate(captions_input):
        caption_obj = None

        if isinstance(item, str):
            # String format - convert to object
            if item.strip():
                caption_obj = {"caption": item.strip()}
        elif isinstance(item, dict):
            # Check for new format: {"id": "...", "caption": "..."}
            if "caption" in item:
                caption_obj = {
                    "caption": item["caption"].strip() if isinstance(item["caption"], str) else str(item["caption"])
                }
                if "id" in item and item["id"]:
                    caption_obj["id"] = str(item["id"]).strip()
            # Old format: {"captions": ["text1", "text2"]} - join into single caption
            elif "captions" in item or "captionParts" in item:
                parts = item.get("captions", item.get("captionParts", []))
                if isinstance(parts, list) and parts:
                    caption_text = " ".join(p.strip() for p in parts if isinstance(p, str) and p.strip())
                    if caption_text:
                        caption_obj = {"caption": caption_text}
                elif isinstance(parts, str) and parts.strip():
                    caption_obj = {"caption": parts.strip()}

        if caption_obj and caption_obj.get("caption"):
            # Deduplicate by first 100 chars of caption
            key = caption_obj["caption"].lower()[:100]
            if key not in seen_texts:
                seen_texts.add(key)
                normalized.append(caption_obj)

    # Auto-generate missing IDs
    for i, cap in enumerate(normalized, start=1):
        if "id" not in cap:
            cap["id"] = f"{caption_type}{i}"

    return normalized


_PLACEHOLDER_STRINGS = frozenset({
    "name of conference", "conference name", "city, country",
    "conference organizer or institution name",
    "institution name", "complete verbatim text",
    "table not found in the poster text",
    "no table found", "no tables found",
    "table not found", "not found in poster",
    "figure 1. caption text", "table 1. caption text",
    "caption text", "figure caption", "table caption",
    "yyyy-mm-dd", "yyyy", "http://example.com",
    "https://example.com", "conference url",
    "poster title", "main poster title",
})


def _is_placeholder(value: str) -> bool:
    """Return True if value matches a known template/placeholder string."""
    return value.strip().lower() in _PLACEHOLDER_STRINGS


def _needs_ror_enrichment(persons) -> bool:
    if not isinstance(persons, list):
        return False
    for p in persons:
        if not isinstance(p, dict):
            continue
        for aff in p.get("affiliation") or []:
            if isinstance(aff, str) and aff.strip():
                return True
            if isinstance(aff, dict) and aff.get("name") and not aff.get("affiliationIdentifier"):
                return True
    return False


def _needs_orcid_enrichment(creators) -> bool:
    if not isinstance(creators, list):
        return False
    for c in creators:
        if not isinstance(c, dict):
            continue
        if not c.get("givenName") or not c.get("familyName"):
            continue
        has_aff = any(
            (isinstance(a, str) and a.strip()) or (isinstance(a, dict) and a.get("name"))
            for a in c.get("affiliation") or []
        )
        if not has_aff:
            continue
        has_orcid = any(
            isinstance(ni, dict) and (
                ni.get("nameIdentifierScheme") == "ORCID"
                or "orcid.org" in str(ni.get("nameIdentifier", "")).lower()
            )
            for ni in c.get("nameIdentifiers") or []
        )
        if not has_orcid:
            return True
    return False


def _needs_funder_enrichment(funding_refs) -> bool:
    if not isinstance(funding_refs, list):
        return False
    for fr in funding_refs:
        if isinstance(fr, dict) and fr.get("funderName") and not fr.get("funderIdentifier"):
            return True
    return False


_SECTION_LABELS = {
    "introduction", "intro", "background", "objective", "objectives", "aim", "aims",
    "method", "methods", "methodology", "materials", "approach",
    "result", "results", "discussion", "conclusion", "conclusions",
    "abstract", "summary", "references", "acknowledgements", "acknowledgments",
    "future work", "limitations", "contact",
}


def _is_section_label_only(text: str) -> bool:
    """True if `text` is nothing but section-label keywords (e.g. "Methodology"
    or "Introduction Results") — a lone-header echo, not real content."""
    t = re.sub(r"[#*•:/\-–—]", " ", text or "").strip().lower()
    if not t or len(t) > 45:
        return False
    toks = [w for w in t.split() if w]
    return bool(toks) and all(w in _SECTION_LABELS for w in toks)


# --- Author/affiliation superscript correction -------------------------------
# The fine-tuned model frequently over-assigns affiliations (most often the
# lead author absorbs every institution) even when the raw text is unambiguous.
# When a poster banner carries a numbered affiliation list, the superscript
# markers in the raw text are authoritative, so affiliations are reassigned
# deterministically. Strictly gated throughout: any ambiguity is a no-op that
# leaves the model's output untouched.

# unicode superscript digits -> ascii (the corrector sees the un-normalized text)
_SUP_TRANS = str.maketrans({
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
    "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
})

# institution keyword (multilingual stems) — distinguishes a real numbered
# affiliation from a number that merely precedes the next author's name
_INSTITUTION_KW = re.compile(
    r"(?i)(universi|institut|instituto|departa|depart|dipart|college|colleg|"
    r"colegio|school|escuela|scuola|hospital|clinic|laborator|cent(?:er|re|ro)|"
    r"zentrum|facult|academ|foundation|fundac|fondazione|stiftung|ministr|"
    r"program|division|divisi|research|investigac|forschung|museum|museo|"
    r"society|sociedad|council|agency|observator|engineering|technolog|"
    r"hochschule|polytechni|gmbh)"
)

# a numbered affiliation marker: 1-2 digits at a boundary, then a capitalized
# institution name (optionally space/dot separated, including accented capitals)
_AFFIL_MARK = re.compile(r"(?:(?<=[\s;,(])|^)(\d{1,2})[.\s]{0,2}(?=[A-ZÀ-ɏ(])")


def _parse_marker_run(run: str):
    """Parse an author marker run ("1,3" / "1-3,6" / "4 2") into a list of ints,
    expanding ranges. Returns ``None`` on anything unexpected so the caller can
    bail (keeping the corrector a strict no-op under ambiguity)."""
    nums = []
    for part in re.split(r"[,\s]+", run.strip()):
        if not part:
            continue
        rng = re.match(r"^(\d{1,2})[–—-](\d{1,2})$", part)
        if rng:
            a, b = int(rng.group(1)), int(rng.group(2))
            if not (a <= b and b - a <= 15):
                return None
            nums.extend(range(a, b + 1))
        elif part.isdigit() and len(part) <= 2:
            nums.append(int(part))
        else:
            return None
    return nums or None


def _banner_region(raw_text: str, first_family: str):
    """The author/affiliation banner: the first line naming the lead author plus
    following lines up to the next detected header, joined into one string."""
    lines = raw_text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if re.search(re.escape(first_family), ln, re.IGNORECASE):
            start = i
            break
    if start is None:
        return None
    out = []
    for off, ln in enumerate(lines[start:start + 12]):
        s = ln.strip().lstrip("#").strip()
        if off > 0 and (ln.lstrip().startswith("## ") or (s and _is_section_label_only(s))):
            break
        if s:
            out.append(s)
    return " ".join(out) if out else None


def _parse_affiliation_block(region: str):
    """Parse the numbered affiliation list from a (superscript-normalized) banner
    region into ``({n: text}, block_start_index)``. Handles ``;``-, comma- and
    next-number-delimited lists. Returns ``None`` unless a clean sequential
    ``1..N`` (N>=2) run of institution-bearing entries is found."""
    cands = [(int(m.group(1)), m.start(1), m.end()) for m in _AFFIL_MARK.finditer(region)]
    real = []
    for i, (num, ms, me) in enumerate(cands):
        seg_end = cands[i + 1][1] if i + 1 < len(cands) else len(region)
        if _INSTITUTION_KW.search(region[me:seg_end][:280]):
            real.append((num, ms, me))
    if len(real) < 2:
        return None
    seq = []
    expect = 1
    for num, ms, me in real:
        if num == expect:
            seq.append((num, ms, me))
            expect += 1
    if len(seq) < 2 or seq[-1][0] != len(seq):
        return None
    amap = {}
    for j, (num, ms, me) in enumerate(seq):
        end = seq[j + 1][1] if j + 1 < len(seq) else len(region)
        txt = region[me:end].strip().strip(",;").strip()
        if not txt:
            return None
        amap[num] = txt
    return amap, seq[0][1]


def _author_marker_nums(author_region: str, family: str):
    """Marker numbers adjacent to ``family`` in the author byline (anchored on
    the LLM-extracted author name). Role glyphs (``*``/``+``/contact symbols)
    terminate the digit run and are ignored. ``None`` if no marker is found."""
    m = re.search(re.escape(family) + r"[.\s]{0,4}(\d[\d,–—\-\s]*)",
                  author_region, re.IGNORECASE)
    if not m:
        return None
    return _parse_marker_run(m.group(1))


def _correct_affiliations_from_superscripts(result: dict, raw_text: str) -> None:
    """Reassign each author's affiliations from the poster banner's numbered list
    using superscript markers in the (authoritative) raw text, anchoring the
    marker search on each LLM-extracted author name. Strictly gated: a no-op
    unless a clean sequential numbered list is found, every author has a marker,
    and every marker resolves to a parsed affiliation — so posters without
    numbered affiliations are left untouched."""
    if not raw_text:
        return
    creators = result.get("creators")
    if not isinstance(creators, list) or len(creators) < 2:
        return
    families = []
    for c in creators:
        if not isinstance(c, dict):
            return
        fam = c.get("familyName") or ""
        if not fam:
            nm = c.get("name", "")
            fam = nm.split(",")[0].strip() if "," in nm else ""
        if not fam or len(fam) < 2:
            return
        families.append(fam)

    region = _banner_region(raw_text, families[0])
    if not region:
        return
    region = region.translate(_SUP_TRANS)
    parsed = _parse_affiliation_block(region)
    if not parsed:
        return
    amap, block_start = parsed
    author_region = region[:block_start]

    plan = []
    for fam in families:
        marks = _author_marker_nums(author_region, fam)
        if not marks or any(n not in amap for n in marks):
            return
        plan.append(marks)

    for c, marks in zip(creators, plan):
        c["affiliation"] = [amap[n] for n in marks]
    notes = result.setdefault("_validation", [])
    if isinstance(notes, list):
        notes.append({
            "field": "creators",
            "level": "info",
            "message": "Affiliations reassigned from author superscript markers in the poster banner.",
        })


def _postprocess_json(
    data: dict, raw_text: str = "", extract_identifiers: bool = False
) -> dict:
    """Comprehensive post-processing for extracted JSON.

    ORCID and ROR enrichment always run. Publication/funder identifier
    extraction (top-level identifiers[], funder identifiers, relatedIdentifiers)
    only runs when extract_identifiers is True; otherwise it is handled upstream.
    """
    result = data.copy()

    # Add schema
    if "$schema" not in result:
        result["$schema"] = SCHEMA_URL

    # Migrate old field names to new schema
    # posterContent -> content
    if "posterContent" in result and "content" not in result:
        result["content"] = result.pop("posterContent")

    # domain -> researchField
    if "domain" in result and "researchField" not in result:
        result["researchField"] = result.pop("domain")

    # Drop LLM-hallucinated formats — set deterministically from file extension
    result.pop("formats", None)

    # version and publicationYear are assigned by the platform at publish time
    # (Zenodo deposit version; current year), never by extraction — letting the
    # model guess only seeds placeholder/wrong values downstream. version is
    # optional in the schema, so drop it. publicationYear stays a required
    # field (the platform fills it at publish); extraction emits null as a
    # placeholder rather than guessing the poster's printed year. The bundled
    # schema is intentionally left strict (integer) — the *final* poster.json
    # carries a real year supplied by posters.science.
    result.pop("version", None)
    result["publicationYear"] = None

    # The model's description is a machine-generated summary, so its
    # descriptionType is "Other". "Abstract" is reserved for the author's own
    # formal abstract, which the platform attaches downstream (the submitter's
    # poster abstract), never poster2json's summary. The type is set
    # deterministically here; the prompt no longer asks the model for it, so
    # only the description text (the summary) is model-generated.
    descs = result.get("descriptions")
    if isinstance(descs, list):
        for d in descs:
            if isinstance(d, dict) and d.get("description"):
                d["descriptionType"] = "Other"

    # Ensure caption fields exist and normalize with auto-generated IDs
    for key, ctype in [("imageCaptions", "fig"), ("tableCaptions", "table")]:
        if key not in result:
            result[key] = []
        elif isinstance(result[key], (dict, list)):
            result[key] = _normalize_captions(result[key], caption_type=ctype)

    # Conference is not extracted by the model at all; it is supplied by the
    # repository or entered on the platform. Drop anything the model emits.
    result.pop("conference", None)

    # Publisher is filled downstream by posters.science, never guessed by the
    # model. Emit an explicit null placeholder (overwriting anything the model
    # or metadata supplied) so the downstream automation has a slot to fill.
    result["publisher"] = None

    # Filter bogus captions (hallucinated "not found" or template echoes)
    for key in ("imageCaptions", "tableCaptions"):
        if key in result and isinstance(result[key], list):
            result[key] = [
                cap for cap in result[key]
                if isinstance(cap, dict)
                and not _is_placeholder(cap.get("caption", ""))
            ]

    # Clean Unicode from string fields
    for key in ["researchField"]:
        if key in result and isinstance(result[key], str):
            result[key] = _clean_unicode_artifacts(result[key])

    # Strip placeholder/fallback values from researchField. The schema asks for
    # one of the four OpenAlex top-level domains; anything else is the model
    # echoing template text or hedging, which downstream rolls up as "Other".
    rf = result.get("researchField")
    if isinstance(rf, str):
        if rf.strip().lower() in {
            "", "other", "unknown", "n/a", "na", "none",
            "research field", "domain", "field",
        }:
            result["researchField"] = None

    # Clean content sections
    if "content" in result and isinstance(result["content"], dict):
        sections = result["content"].get("sections", [])
        if isinstance(sections, list):
            cleaned_sections = []
            for section in sections:
                if not isinstance(section, dict):
                    continue
                title = _clean_unicode_artifacts(section.get("sectionTitle", "").strip())
                content = section.get("sectionContent", "")
                if isinstance(content, list):
                    content = " ".join(str(c) for c in content)
                content = _clean_unicode_artifacts(
                    content.strip() if isinstance(content, str) else ""
                )
                if content and len(content) > 10:
                    entry = {"sectionContent": content}
                    if title:
                        entry["sectionTitle"] = title
                    cleaned_sections.append(entry)
            # Recover uncaptured raw text as untitled section(s).
            # The LLM sometimes drops footer content (contact info, URLs).
            # Compare raw text lines against section content and reclaim
            # any contiguous block of missing lines.
            if raw_text and cleaned_sections:
                # Collect all captured text. As well as section content + captions
                # this MUST include section titles and the words already parsed
                # into structured metadata (titles / creators / descriptions /
                # subjects); otherwise the recovery step re-imports the title and
                # author banner and bare section-label headers as junk "ghost"
                # sections.
                captured = set()
                for sec in cleaned_sections:
                    captured.update(sec["sectionContent"].lower().split())
                    captured.update(
                        sec.get("sectionTitle", "").replace("#", " ").lower().split()
                    )
                for key in ("imageCaptions", "tableCaptions"):
                    for cap in result.get(key, []) or []:
                        if isinstance(cap, dict):
                            for v in cap.values():
                                if isinstance(v, str):
                                    captured.update(v.lower().split())
                for fld in ("titles", "creators", "descriptions", "subjects"):
                    for obj in result.get(fld, []) or []:
                        if isinstance(obj, dict):
                            for v in obj.values():
                                if isinstance(v, str):
                                    captured.update(v.lower().split())
                                elif isinstance(v, list):
                                    for it in v:
                                        if isinstance(it, str):
                                            captured.update(it.lower().split())
                                        elif isinstance(it, dict):
                                            for vv in it.values():
                                                if isinstance(vv, str):
                                                    captured.update(vv.lower().split())

                # Strip ## prefixes and find ALL uncaptured blocks
                raw_lines = [
                    ln.lstrip("# ").strip() if ln.startswith("## ") else ln.strip()
                    for ln in raw_text.split("\n")
                ]
                all_uncaptured_blocks = []
                current_block = []
                for ln in raw_lines:
                    if not ln:
                        continue
                    # Never reclaim a bare section-label header ("Methodology",
                    # "Introduction Results", ...) as recovered content.
                    if _is_section_label_only(ln):
                        if current_block and len(" ".join(current_block)) > 10:
                            all_uncaptured_blocks.append(current_block)
                        current_block = []
                        continue
                    words = ln.lower().split()
                    if not words:
                        continue
                    hit = sum(1 for w in words if w in captured)
                    if hit / len(words) < 0.5:
                        current_block.append(ln)
                    else:
                        if current_block and len(" ".join(current_block)) > 10:
                            all_uncaptured_blocks.append(current_block)
                        current_block = []
                if current_block and len(" ".join(current_block)) > 10:
                    all_uncaptured_blocks.append(current_block)

                for block in all_uncaptured_blocks:
                    blob = "\n".join(block)
                    # Drop blocks that are entirely section-label echoes.
                    if _is_section_label_only(blob):
                        continue
                    cleaned_sections.append({
                        "sectionContent": blob,
                    })

            result["content"]["sections"] = cleaned_sections

    # Build sections from raw text when LLM produced none
    if raw_text:
        has_sections = (
            "content" in result
            and isinstance(result.get("content"), dict)
            and result["content"].get("sections")
        )
        if not has_sections:
            if "content" not in result or not isinstance(result.get("content"), dict):
                result["content"] = {}

            # Collect words already captured in LLM metadata for dedup
            meta_words = set()
            for creator in result.get("creators", []):
                if isinstance(creator, dict):
                    for v in creator.values():
                        if isinstance(v, str):
                            meta_words.update(v.lower().split())
                        elif isinstance(v, list):
                            for item in v:
                                if isinstance(item, str):
                                    meta_words.update(item.lower().split())
            for title_obj in result.get("titles", []):
                if isinstance(title_obj, dict):
                    for v in title_obj.values():
                        if isinstance(v, str):
                            meta_words.update(v.lower().split())

            raw_sections = []
            current_title = ""
            current_lines = []
            for ln in raw_text.split("\n"):
                ln = ln.strip()
                if not ln:
                    continue
                if ln.startswith("## "):
                    if current_lines:
                        content = "\n".join(current_lines)
                        words = content.lower().split()
                        overlap = sum(1 for w in words if w in meta_words) / max(len(words), 1)
                        if overlap < 0.7 and len(content) > 10:
                            entry = {"sectionContent": content}
                            if current_title:
                                entry["sectionTitle"] = current_title
                            raw_sections.append(entry)
                    current_title = ln[3:].strip()
                    current_lines = []
                else:
                    current_lines.append(ln)
            if current_lines:
                content = "\n".join(current_lines)
                words = content.lower().split()
                overlap = sum(1 for w in words if w in meta_words) / max(len(words), 1)
                if overlap < 0.7 and len(content) > 10:
                    entry = {"sectionContent": content}
                    if current_title:
                        entry["sectionTitle"] = current_title
                    raw_sections.append(entry)
            if raw_sections:
                result["content"]["sections"] = raw_sections

    # Clean creators/contributors and set nameType. poster2json does not ask the
    # model for nameType; it is derived from whether the model produced a
    # person-name split (givenName/familyName) — "Personal" — versus an
    # organization name only — "Organizational" — matching the schema enum.
    for _person_field in ("creators", "contributors"):
        _persons = result.get(_person_field)
        if not isinstance(_persons, list):
            continue
        for creator in _persons:
            if not isinstance(creator, dict):
                continue
            if "name" in creator:
                creator["name"] = _clean_unicode_artifacts(creator.get("name", ""))
            creator["nameType"] = (
                "Personal" if (creator.get("givenName") or creator.get("familyName"))
                else "Organizational"
            )

    # Clean titles
    if "titles" in result and isinstance(result["titles"], list):
        for title_obj in result["titles"]:
            if isinstance(title_obj, dict) and "title" in title_obj:
                title_obj["title"] = _clean_unicode_artifacts(title_obj.get("title", ""))

    # Licenses are not extracted from the poster by the model; rights are
    # provided by the repository or platform upstream. Drop any the model emits.
    result.pop("rightsList", None)

    # Cleanup + dedupe subjects
    if "subjects" in result:
        from .normalize import normalize_subjects

        result["subjects"] = normalize_subjects(result["subjects"])

    # Language is owned entirely by the lingua-based detector, never the LLM.
    # The model has been observed to hallucinate `language` from English
    # metadata fragments (e.g. the figshare Japanese poster at DOI
    # 10.6084/m9.figshare.10116536.v1), so its value is always discarded and
    # re-derived from the raw body text. When there is no body text (or the
    # detector is unsure), null is more honest than a guess.
    from .language import detect_language

    result["language"] = detect_language(raw_text) if raw_text else None

    # Reassign affiliations from author superscript markers when the poster
    # banner has a numbered affiliation list (the model commonly over-assigns,
    # e.g. the lead author absorbing every institution). Strictly gated, so it
    # is a no-op on posters without a numbered list. Runs before resolution so
    # the reassigned name strings get ROR-resolved normally.
    _correct_affiliations_from_superscripts(result, raw_text)

    # Affiliation normalization: coerce to the schema's array form (the model
    # sometimes emits a bare string or single object), drop any model-supplied
    # identifiers (ROR IDs are resolved from the name, never trusted from what
    # the model scraped off the poster), then resolve against ROR. Resolution
    # also collapses same-org duplicates while preserving distinct sub-unit
    # names that share one ROR id. Coerce/strip run unconditionally; resolution
    # is gated on something actually being unresolved.
    from .ror import coerce_person_affiliations, strip_extracted_affiliation_ids
    for _persons_key in ("creators", "contributors"):
        if _persons_key in result:
            result[_persons_key] = coerce_person_affiliations(result[_persons_key])
            result[_persons_key] = strip_extracted_affiliation_ids(result[_persons_key])

    if (_needs_ror_enrichment(result.get("creators"))
            or _needs_ror_enrichment(result.get("contributors"))):
        from .ror import get_default_client, resolve_person_affiliations
        ror = get_default_client()
        for _persons_key in ("creators", "contributors"):
            if _persons_key in result:
                result[_persons_key] = resolve_person_affiliations(
                    result[_persons_key], ror
                )

    # Funder + award normalization, then ROR funder lookup
    if "fundingReferences" in result:
        from .normalize import normalize_funding_references
        result["fundingReferences"] = normalize_funding_references(
            result["fundingReferences"]
        )
        if extract_identifiers and _needs_funder_enrichment(result["fundingReferences"]):
            from .funders import enrich_funding_references
            from .funders import get_default_client as get_funder_client
            result["fundingReferences"] = enrich_funding_references(
                result["fundingReferences"], get_funder_client()
            )

    # Enrich with identifiers from raw text. ORCID/ROR always run; the rest is
    # gated by extract_identifiers (handled upstream by default).
    if raw_text:
        from .identifiers import enrich_json_with_identifiers

        result = enrich_json_with_identifiers(result, raw_text, extract_identifiers)

    # ORCID lookup -- skip if all creators already have ORCID
    if _needs_orcid_enrichment(result.get("creators")):
        from .orcid import enrich_creators_orcid
        from .orcid import get_default_client as get_orcid_client
        from .ror import get_default_client as get_ror_client
        _ror = get_ror_client()

        def _canonical_affiliation(name):
            # ORCID's affiliation search does not match long sub-unit strings;
            # query with the ROR canonical institution name when available.
            r = _ror.lookup(name) if name else None
            return (r or {}).get("name") or name

        result["creators"] = enrich_creators_orcid(
            result["creators"], get_orcid_client(),
            affiliation_resolver=_canonical_affiliation,
        )

    # Drop lone UTF-16 surrogates the model can emit (half of an emoji); they
    # cannot be UTF-8 encoded and would break json.dump(ensure_ascii=False).
    result = _strip_surrogates(result)
    return result


# ============================
# MAIN EXTRACTION FUNCTION
# ============================


def _normalize_raw_text_for_model(text: str) -> str:
    """Normalize Unicode in raw OCR text before feeding to the model.

    NFKD decomposition converts superscripts (¹²³⁺), subscripts (ₛ),
    and other compatibility characters to their ASCII equivalents,
    reducing token count and improving model JSON generation.

    Smart/curly quotes are replaced with single quotes to prevent the
    model from outputting unescaped straight double-quotes inside JSON
    string values (e.g. OCR ``\u201ctwin\u201d`` → model ``"twin"`` →
    broken JSON).
    """
    # NFKD: ¹→1, ²→2, ³→3, ⁺→+, ₛ→s, etc.
    text = unicodedata.normalize("NFKD", text)
    # Remove combining marks left over from decomposition
    text = "".join(c for c in text if not unicodedata.combining(c))
    # Replace smart/curly quotes with straight single quotes
    text = text.replace("\u201c", "'").replace("\u201d", "'")  # " " → '
    text = text.replace("\u2018", "'").replace("\u2019", "'")  # ' ' → '
    text = text.replace("\u00ab", "'").replace("\u00bb", "'")  # « » → '
    # Fix mixed-pair leftovers: curly open (now ') + straight close (")
    # e.g. 'twin" → 'twin'
    text = re.sub(r"'(\w+(?:\s+\w+)*)\"", r"'\1'", text)
    # Fix remaining inline scare-quotes: word "quoted" word → word 'quoted' word
    text = re.sub(
        r'(?<=\w)\s"(\w+(?:\s+\w+)*)"\s(?=\w)', r" '\1' ", text
    )
    return text


def _strip_surrogates(obj):
    """Recursively drop lone UTF-16 surrogate code points (e.g. half of an
    emoji the model emitted). They are valid ``str`` but cannot be UTF-8
    encoded, so they break ``json.dump(..., ensure_ascii=False)`` and file
    writes downstream."""
    if isinstance(obj, str):
        if any("\ud800" <= c <= "\udfff" for c in obj):
            return obj.encode("utf-8", "ignore").decode("utf-8")
        return obj
    if isinstance(obj, dict):
        return {k: _strip_surrogates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_surrogates(v) for v in obj]
    return obj


def _as_result_dict(result):
    """The model occasionally returns a top-level JSON array instead of an
    object; unwrap it to the first object so the rest of the pipeline can treat
    the result as a dict (avoids ``'list' object has no attribute 'get'``)."""
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict):
                return item
        return {"error": "model returned a JSON array with no object", "raw": str(result)[:500]}
    return {"error": f"model returned non-object JSON ({type(result).__name__})", "raw": str(result)[:500]}


def extract_json_with_retry(
    raw_text: str, model, tokenizer, extract_identifiers: bool = False
) -> dict:
    """
    Send raw poster text to the LLM and robustly parse the JSON response.

    This function:
      1. Checks input length against MAX_INPUT_TOKENS
      2. Normalizes Unicode in the raw text
      3. Calls the model with a full prompt
      4. Retries with more tokens if truncation is detected
      5. Falls back to a shorter prompt if needed
      6. Runs repair passes to make the JSON parseable
    """
    raw_text = _normalize_raw_text_for_model(raw_text)

    input_tokens = len(tokenizer.encode(raw_text, add_special_tokens=False))
    if input_tokens > MAX_INPUT_TOKENS:
        log(f"Input too long: {input_tokens} tokens (max {MAX_INPUT_TOKENS})")
        return {
            "error": f"input_too_long: poster text is {input_tokens} tokens, "
                     f"exceeding the {MAX_INPUT_TOKENS}-token limit for reliable extraction",
            "errorCode": "INPUT_TOO_LONG",
            "_input_tokens": input_tokens,
            "_max_input_tokens": MAX_INPUT_TOKENS,
        }

    prompt = EXTRACTION_PROMPT.format(raw_text=raw_text)

    log("Starting primary JSON extraction with full prompt")
    response = _generate(model, tokenizer, prompt, MAX_JSON_TOKENS)
    result = _as_result_dict(_robust_json_parse(response))
    if "error" in result:
        log(f"Primary JSON parse error: {result['error']}")
    else:
        log("Primary JSON parse succeeded")

    # Retry with more tokens if truncation detected
    if "error" in result or _is_truncated(result.get("raw", "")):
        log(f"Retrying with max_tokens={MAX_RETRY_TOKENS}")
        response = _generate(model, tokenizer, prompt, MAX_RETRY_TOKENS)
        result = _as_result_dict(_robust_json_parse(response))

    # Fallback to shorter prompt
    if "error" in result or _is_truncated(result.get("raw", "")):
        log("Using fallback shorter prompt")
        fallback_prompt = FALLBACK_PROMPT.format(raw_text=raw_text)
        response = _generate(model, tokenizer, fallback_prompt, MAX_RETRY_TOKENS)
        result = _as_result_dict(_robust_json_parse(response))

    result = _postprocess_json(
        result, raw_text=raw_text, extract_identifiers=extract_identifiers
    )
    return result


def extract_poster(
    poster_path: str,
    model_id: Optional[str] = None,
    quantization: Optional[str] = None,
    extract_identifiers: Optional[bool] = None,
) -> dict:
    """
    Extract structured JSON metadata from a scientific poster.

    Args:
        poster_path: Path to the poster file (PDF, JPG, or PNG).
        model_id: Override the default JSON structuring model
            (Llama-3.1-8B-Instruct). Accepts any HuggingFace repo id
            (e.g. google/gemma-2-9b-it, Qwen/Qwen2.5-7B-Instruct).
        quantization: Precision mode: "fp16", "8bit", or "4bit".
            Defaults to "4bit" (NF4) when unset.
        extract_identifiers: Emit publication/funder identifiers scraped from
            the poster text — top-level identifiers[] (DOI/arXiv), funder
            identifiers, and relatedIdentifiers. Off by default (handled
            upstream); ORCID and ROR enrichment always run. When None, the
            default comes from the POSTER2JSON_EXTRACT_IDENTIFIERS env var.
    """
    if extract_identifiers is None:
        extract_identifiers = _identifiers_flag_default()
    log(f"Processing poster: {poster_path}")

    # For image posters (and PDFs that may need vision OCR fallback):
    # unload the JSON model BEFORE the vision model loads. Qwen2-VL-7B
    # at bf16 needs ~15GB; on a 24GB card the JSON model warm-loaded by
    # api.py healthcheck is ~9GB resident, leaving the vision load short
    # by a few hundred MB and OOMing.
    # Cost: ~10s of JSON reload after OCR.
    ext = Path(poster_path).suffix.lower()
    if ext in {".jpg", ".jpeg", ".png"}:
        unload_json_model()

    # Extract raw text (may trigger vision OCR for image-only PDFs)
    t_extract_start = time.time()
    raw_text, source = get_raw_text(poster_path)
    t_extract_elapsed = time.time() - t_extract_start

    # Extract PDF link annotations (clickable URIs in the annotation layer)
    pdf_links = []
    if ext == ".pdf":
        pdf_links = extract_pdf_link_annotations(poster_path)

    if not raw_text or source == "unknown":
        return {"error": "Failed to extract text. Unsupported format or extraction failed."}

    log(f"Extracted {len(raw_text)} chars using {source} in {t_extract_elapsed:.2f}s")

    # Unload vision model before loading JSON model
    unload_vision_model()

    # Load JSON model
    model, tokenizer = load_json_model(
        model_id=model_id,
        quantization=quantization,
    )

    try:
        t_json_start = time.time()
        generated = extract_json_with_retry(
            raw_text, model, tokenizer, extract_identifiers=extract_identifiers
        )
        t_json_elapsed = time.time() - t_json_start

        if "error" in generated and source == "pdfplumber":
            log(f"pdfplumber text failed after {t_json_elapsed:.2f}s, retrying with PyMuPDF")
            pymupdf_text = extract_text_with_pymupdf(poster_path)
            if pymupdf_text and len(pymupdf_text) > 500:
                t_retry_start = time.time()
                generated = extract_json_with_retry(
                    pymupdf_text, model, tokenizer, extract_identifiers=extract_identifiers
                )
                t_retry_elapsed = time.time() - t_retry_start
                if "error" not in generated:
                    log(f"PyMuPDF fallback succeeded in {t_retry_elapsed:.2f}s")
                else:
                    log(f"PyMuPDF fallback also failed after {t_retry_elapsed:.2f}s")

        if "error" in generated:
            log(f"Extraction completed with error after {time.time() - t_json_start:.2f}s")
        else:
            log(f"Extraction succeeded in {time.time() - t_json_start:.2f}s")

        if pdf_links and "error" not in generated:
            from .identifiers import merge_pdf_link_annotations
            generated = merge_pdf_link_annotations(
                generated, pdf_links, extract_identifiers
            )

        fmt = EXT_TO_FORMAT.get(ext)
        if fmt and "error" not in generated:
            generated["formats"] = [fmt]

        unload_json_model()
        return generated
    except Exception as e:
        log(f"ERROR: {e}")
        import traceback

        traceback.print_exc()
        unload_json_model()
        return {"error": str(e)}
