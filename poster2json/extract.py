"""
Poster Extraction Module

Extract structured JSON metadata from scientific posters (PDF/images)
using Large Language Models.

Models:
- Llama 3.1 8B Poster Extraction: JSON structuring (via HuggingFace transformers)
- Qwen2-VL-7B-Instruct: Vision OCR for images

Requirements:
- pdfalto: PDF layout analysis tool (https://github.com/kermitt2/pdfalto)
- CUDA-capable GPU with ≥16GB VRAM
"""

import gc
import json
import os
import re
import shutil
import subprocess
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
    Qwen2VLForConditionalGeneration,
    TextStreamer,
)

# Model configuration
JSON_MODEL_ID = "fairdataihub/Llama-3.1-8B-Poster-Extraction"
VISION_MODEL_ID = "Qwen/Qwen2-VL-7B-Instruct"

# Token limits
MAX_JSON_TOKENS = 18000
MAX_RETRY_TOKENS = 24000

# Schema URL
SCHEMA_URL = "https://posters.science/schema/v0.2/poster_schema.json"

# Find pdfalto executable
PDFALTO_PATH = os.environ.get("PDFALTO_PATH")
if not PDFALTO_PATH:
    known_paths = [
        Path(__file__).parent / "executables" / "pdfalto",
        Path.home() / "Downloads" / "pdfalto",
        "/usr/local/bin/pdfalto",
        "/usr/bin/pdfalto",
    ]
    for p in known_paths:
        if Path(p).exists():
            PDFALTO_PATH = str(p)
            break
    if not PDFALTO_PATH:
        pdfalto_in_path = shutil.which("pdfalto")
        if pdfalto_in_path:
            PDFALTO_PATH = pdfalto_in_path


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


def extract_text_with_pdfalto(pdf_path: str) -> Optional[str]:
    """Extract text from PDF using pdfalto (layout-aware)."""
    log(f"Attempting text extraction with pdfalto for: {pdf_path}")
    if PDFALTO_PATH is None:
        return None
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            xml_path = os.path.join(tmpdir, "output.xml")
            t0 = time.time()
            result = subprocess.run(
                [PDFALTO_PATH, "-noImage", "-readingOrder", pdf_path, xml_path],
                capture_output=True,
                text=True,
                timeout=60,
            )
            elapsed = time.time() - t0
            if result.returncode != 0:
                raise RuntimeError(f"pdfalto returned code {result.returncode}: {result.stderr}")
            if not os.path.exists(xml_path):
                raise RuntimeError("pdfalto did not produce output XML")
            text = _parse_alto_xml(xml_path)
            if text is None:
                log(f"pdfalto XML parsing failed for: {pdf_path}")
            else:
                log(f"pdfalto extracted {len(text)} characters in {elapsed:.2f} seconds")
            return text
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"pdfalto timeout processing {pdf_path}")
    except Exception as e:
        raise RuntimeError(f"pdfalto error: {e}")


def _parse_text_styles(root, ns: str) -> dict:
    """Parse <TextStyle> definitions from ALTO <Styles> section.

    Returns dict keyed by style ID with fontsize (float), bold (bool),
    italic (bool) fields.
    """
    styles = {}
    for ts in root.findall(f".//{ns}TextStyle"):
        sid = ts.get("ID", "")
        if not sid:
            continue
        fontsize = 0.0
        try:
            fontsize = float(ts.get("FONTSIZE", "0"))
        except (ValueError, TypeError):
            pass
        fontstyle = (ts.get("FONTSTYLE") or "").lower()
        styles[sid] = {
            "fontsize": fontsize,
            "bold": "bold" in fontstyle,
            "italic": "italic" in fontstyle,
        }
    # Try without namespace if nothing found
    if not styles:
        for ts in root.findall(".//TextStyle"):
            sid = ts.get("ID", "")
            if not sid:
                continue
            fontsize = 0.0
            try:
                fontsize = float(ts.get("FONTSIZE", "0"))
            except (ValueError, TypeError):
                pass
            fontstyle = (ts.get("FONTSTYLE") or "").lower()
            styles[sid] = {
                "fontsize": fontsize,
                "bold": "bold" in fontstyle,
                "italic": "italic" in fontstyle,
            }
    return styles


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


def _parse_alto_xml(xml_path: str) -> Optional[str]:
    """Parse ALTO XML output from pdfalto.

    Preserves pdfalto's native reading order (-readingOrder flag),
    deduplicates lines within blocks, and prefixes detected headers
    with '## ' based on font size/style analysis.
    """
    from xml.etree import ElementTree as ET

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()

        # Detect namespace
        ns = "{http://www.loc.gov/standards/alto/ns-v3#}"
        if not root.findall(f".//{ns}TextBlock"):
            ns = ""

        # Parse text styles for header detection
        styles = _parse_text_styles(root, ns)

        # Get page dimensions
        page = root.find(f".//{ns}Page")
        page_w = float(page.get("WIDTH", "1")) if page is not None else 1.0
        page_h = float(page.get("HEIGHT", "1")) if page is not None else 1.0

        # Extract blocks with spatial info
        blocks = []
        for tb in root.findall(f".//{ns}TextBlock"):
            hpos = float(tb.get("HPOS", "0"))
            vpos = float(tb.get("VPOS", "0"))
            bw = float(tb.get("WIDTH", "0"))
            bh = float(tb.get("HEIGHT", "0"))

            # Collect TextLines, deduplicating within the block
            seen_lines = []  # list of (vpos, words_set, text)
            for tl in tb.findall(f".//{ns}TextLine"):
                line_vpos = float(tl.get("VPOS", "0"))
                strings = tl.findall(f".//{ns}String")
                words = [s.get("CONTENT", "") for s in strings if s.get("CONTENT")]
                if not words:
                    continue
                line_text = " ".join(words)
                word_set = set(words)

                # Skip duplicate lines: same VPOS and >80% word overlap
                is_dup = False
                for sv, sw, st in seen_lines:
                    if abs(sv - line_vpos) < 2:  # same vertical position
                        if len(word_set) > 0 and len(sw) > 0:
                            overlap = len(word_set & sw) / max(len(word_set), len(sw))
                            if overlap > 0.8:
                                is_dup = True
                                break
                if not is_dup:
                    seen_lines.append((line_vpos, word_set, line_text))

            if not seen_lines:
                continue

            # Join all lines into a single line per block (like the old parser).
            # Preserving PDF line breaks splits sentences and confuses the LLM.
            block_text = " ".join(text for _, _, text in seen_lines)

            # Collect style refs for header detection
            style_refs = set()
            for s in tb.findall(f".//{ns}String"):
                sr = s.get("STYLEREFS", "")
                if sr:
                    style_refs.update(sr.split())

            cx = hpos + bw / 2
            blocks.append({
                "hpos": hpos,
                "vpos": vpos,
                "width": bw,
                "height": bh,
                "cx": cx,
                "text": block_text,
                "style_refs": style_refs,
            })

        if not blocks:
            return None

        # NOTE: Block-level dedup removed — pdfalto with -readingOrder already
        # handles duplicates. The dedup was dropping legitimate blocks that had
        # similar text at similar vpos (e.g. "724 words" vs "755 words").

        # Determine median body font size for header detection
        body_sizes = []
        for blk in blocks:
            for sr in blk["style_refs"]:
                if sr in styles and styles[sr]["fontsize"] > 0:
                    body_sizes.append(styles[sr]["fontsize"])
        median_fontsize = sorted(body_sizes)[len(body_sizes) // 2] if body_sizes else 0

        # Preserve pdfalto's reading order (from -readingOrder flag).
        # Do NOT sort by vpos — pdfalto already handles column layout
        # and reading order correctly. Sorting by vpos overrides that
        # and scrambles multi-column poster content.

        # Build output — one line per block, no gap markers.
        # Gap markers (blank lines) were removed because they change how
        # the LLM segments content vs the reference annotations.
        output_lines = []

        for blk in blocks:

            # Detect header: bold font >= median body size, or any font > 1.3x median
            # Conservative filters to avoid false positives:
            #   - Short blocks only (≤120 chars)
            #   - Must start with a letter (skip bullets, numbers, symbols)
            #   - Must contain ≥2 alphabetic words
            #   - Skip contact-like text (emails, phones, URLs)
            is_header = False
            _t = blk["text"].strip()
            _alpha_words = re.findall(r'[A-Za-z]{2,}', _t)
            _starts_with_letter = bool(re.match(r'[A-Za-z]', _t))
            _is_contact = bool(
                re.search(r'@\S+\.\S+', _t)       # email
                or re.search(r'\+\d[\d\s]{6,}', _t)  # phone
                or re.search(r'www\.', _t, re.I)    # URL
                or re.search(r'https?://', _t, re.I)
            )
            if (median_fontsize > 0 and len(_t) <= 120
                    and _starts_with_letter and len(_alpha_words) >= 2
                    and not _is_contact):
                for sr in blk["style_refs"]:
                    st = styles.get(sr, {})
                    fs = st.get("fontsize", 0)
                    if st.get("bold") and fs >= median_fontsize:
                        is_header = True
                        break
                    if fs > median_fontsize * 1.3:
                        is_header = True
                        break

            text = blk["text"]
            if is_header:
                text = f"## {text}"

            output_lines.append(text)

        return "\n".join(output_lines)
    except Exception:
        return None


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
        text = extract_text_with_pdfalto(poster_path)
        if text and len(text) > 500:
            log(f"Using pdfalto output ({len(text)} characters)")
            return text, "pdfalto"
        text = extract_text_with_pymupdf(poster_path)
        log(f"Using PyMuPDF fallback ({len(text)} characters)")
        return text, "pymupdf"

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


def _generate(model, tokenizer, prompt: str, max_tokens: int) -> str:
    """Generate response using the Llama model."""
    messages = [{"role": "user", "content": prompt}]
    input_text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(input_text, return_tensors="pt").to(model.device)

    log(f"Generating with max_tokens={max_tokens}, input_length={inputs['input_ids'].shape[1]}")

    streamer = ProgressStreamer(tokenizer, log_every=200)
    t0 = time.time()
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_tokens,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
            streamer=streamer,
        )
    elapsed = time.time() - t0
    tokens_generated = outputs.shape[1] - inputs["input_ids"].shape[1]
    log(
        f"   Generated {tokens_generated} tokens in {elapsed:.2f}s ({tokens_generated/elapsed:.1f} tok/s)"
    )

    return tokenizer.decode(outputs[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True)


# ============================
# EXTRACTION PROMPTS
# ============================

EXTRACTION_PROMPT = """Convert this scientific poster text to JSON format.

CRITICAL RULES:
1. Extract ALL required fields: creators, titles, publicationYear, subjects, descriptions, publisher, conference, formats
2. Create SEPARATE sections for EACH distinct topic/header found in the poster
3. Use the poster's OWN section headers exactly as they appear. Lines prefixed with "## " indicate detected headers from the poster layout. Standard headers (Abstract, Introduction, Methods, Results, Discussion, Conclusions, References, Acknowledgements) are common examples, but always prefer the poster's actual headers over generic ones.
4. Each section must have its OWN "sectionTitle" and "sectionContent"
5. Copy ALL text EXACTLY - do not paraphrase or summarize
6. "Key Findings" ≠ "References": Key Findings = discoveries/results; References = numbered citations with authors/years
7. Figure/table captions belong in imageCaptions/tableCaptions, NOT inside sectionContent
8. Text without a clear header (e.g. contact info, URLs, footer text) is still a section — use "sectionTitle": "" with the verbatim text as "sectionContent". Do NOT skip any poster text.

JSON SCHEMA (all top-level fields are REQUIRED):
{{
  "creators": [
    {{"name": "LastName, FirstName", "givenName": "FirstName", "familyName": "LastName", "affiliation": ["Institution Name"]}}
  ],
  "titles": [{{"title": "Main Poster Title"}}],
  "publicationYear": 2025,
  "subjects": [{{"subject": "keyword1"}}, {{"subject": "keyword2"}}, {{"subject": "keyword3"}}],
  "descriptions": [{{"description": "The abstract text from the poster...", "descriptionType": "Abstract"}}],
  "publisher": {{"name": "Conference Organizer or Institution Name"}},
  "conference": null,
  "formats": ["PDF"],
  "researchField": null,
  "content": {{
    "sections": [
      {{"sectionTitle": "Introduction", "sectionContent": "Complete verbatim text..."}},
      {{"sectionTitle": "Methods", "sectionContent": "Complete verbatim text..."}},
      {{"sectionTitle": "Results", "sectionContent": "Complete verbatim text..."}}
    ]
  }},
  "imageCaptions": [{{"id": "fig1", "caption": "Figure 1. Caption text"}}, {{"id": "fig2", "caption": "Figure 2. Caption text"}}],
  "tableCaptions": [{{"id": "table1", "caption": "Table 1. Caption text"}}]
}}

EXTRACTION NOTES:
- publicationYear: Extract from poster or conference date, use current year if not found
- subjects: Extract 3-5 keywords from poster content
- descriptions: Use the Abstract section content, descriptionType is REQUIRED
- publisher: Use conference organizer, hosting institution, or repository name
- titles: If the poster title is ALL CAPS, convert to proper Title Case preserving acronyms (e.g. "RESEARCH ON SARS-CoV-2" not "RESEARCH ON SARS-COV-2")
- conference: Extract ONLY from text clearly visible on the poster (header, footer, logos).
  * If conference details are NOT visible, set "conference": null — do NOT invent names, locations, dates, URLs, or acronyms.
  * NEVER output generic values like "Name of Conference", "City, Country", "Conference Name", or made-up URLs.
  * If only SOME fields are visible (e.g. name and year but not location), include only those: {{"conferenceName": "ACL 2024", "conferenceYear": 2024}}
  * If no conference information is found at all, output "conference": null
- publisher: Extract from poster. If not found, set to null — do NOT use placeholder text
- formats: Set to ["PDF"] for PDF files, ["PNG"] or ["JPEG"] for images
- imageCaptions/tableCaptions: Use "id" field (e.g., "fig1") for cross-referencing if needed
- rightsList: OPTIONAL - include if license/copyright info found on poster
- researchField: Top-level OpenAlex domain. MUST be EXACTLY one of:
    "Health Sciences" | "Life Sciences" | "Physical Sciences" | "Social Sciences"
  Pick the single best fit based on poster content (subjects, methods, findings).
  If unclear, set to null. NEVER output "Other", "Unknown", "Research field",
  empty string, or any other placeholder text.

POSTER TEXT TO CONVERT:
{raw_text}

OUTPUT VALID JSON ONLY:"""

FALLBACK_PROMPT = """Convert poster text to JSON. REQUIRED FIELDS:
1. creators, titles, publicationYear, subjects, descriptions, publisher, conference, formats, content
2. SEPARATE section for EACH header found in the poster text. Use the poster's own headers. Lines starting with "## " are detected headers.
3. Copy ALL text EXACTLY verbatim
4. If title is ALL CAPS, convert to Title Case preserving acronyms (SARS-CoV-2, not SARS-COV-2)
5. conference/publisher: extract ONLY if clearly visible on the poster. If not found, set to null. NEVER invent names, locations, dates, URLs, or use generic placeholders.

{{
  "creators": [{{"name": "LastName, FirstName", "givenName": "FirstName", "familyName": "LastName", "affiliation": ["Institution"]}}],
  "titles": [{{"title": "Poster Title"}}],
  "publicationYear": 2025,
  "subjects": [{{"subject": "keyword1"}}, {{"subject": "keyword2"}}],
  "descriptions": [{{"description": "Abstract text", "descriptionType": "Abstract"}}],
  "publisher": {{"name": "Conference or Institution"}},
  "conference": null,
  "formats": ["PDF"],
  "researchField": null,
  "content": {{
    "sections": [{{"sectionTitle": "Header", "sectionContent": "verbatim text"}}]
  }},
  "imageCaptions": [{{"id": "fig1", "caption": "Figure 1. Caption"}}],
  "tableCaptions": [{{"id": "table1", "caption": "Table 1. Caption"}}]
}}

researchField MUST be exactly one of: "Health Sciences", "Life Sciences", "Physical Sciences", "Social Sciences" — or null if unclear. NEVER output "Other", "Unknown", or placeholder text.

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

    Handles two patterns:
    1. Quotes after units: e.g. ``16.7 pc/"`` → ``16.7 pc/\\"``
    2. Inline scare-quotes: e.g. ``M dwarf "twin" binaries``
       → ``M dwarf 'twin' binaries``
    """
    # Unit-slash pattern (original)
    s = re.sub(
        r'(\d+\s*(?:pc|km|m|cm|mm|Hz|kHz|MHz|GHz|s|ms|ns|arcsec|arcmin|deg))/"',
        r'\1/\\"',
        s,
    )
    s = re.sub(r'\((\d+\.?\d*\s*\w+)/"\)', r'(\1/\\")', s)
    # Inline scare-quotes: word "quoted word(s)" word → single quotes
    s = re.sub(r'(?<=\w)\s*"\s*(\w+(?:\s+\w+)*)\s*"\s*(?=\w)', r" '\1' ", s)
    return s


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

    return {"error": "JSON parse failed", "raw": json_str[:3000]}


# ============================
# POST-PROCESSING
# ============================


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


def _postprocess_json(data: dict, raw_text: str = "") -> dict:
    """Comprehensive post-processing for extracted JSON."""
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

    # Ensure caption fields exist and normalize with auto-generated IDs
    for key, ctype in [("imageCaptions", "fig"), ("tableCaptions", "table")]:
        if key not in result:
            result[key] = []
        elif isinstance(result[key], (dict, list)):
            result[key] = _normalize_captions(result[key], caption_type=ctype)

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
                # Collect all captured text (sections + captions)
                captured = set()
                for sec in cleaned_sections:
                    for w in sec["sectionContent"].lower().split():
                        captured.add(w)
                for cap in result.get("imageCaptions", []):
                    if isinstance(cap, dict):
                        for v in cap.values():
                            if isinstance(v, str):
                                for w in v.lower().split():
                                    captured.add(w)

                # Strip ## prefixes and find uncaptured lines
                raw_lines = [
                    ln.lstrip("# ").strip() if ln.startswith("## ") else ln.strip()
                    for ln in raw_text.split("\n")
                ]
                uncaptured = []
                for ln in raw_lines:
                    if not ln:
                        continue
                    words = ln.lower().split()
                    if not words:
                        continue
                    hit = sum(1 for w in words if w in captured)
                    if hit / len(words) < 0.5:
                        uncaptured.append(ln)
                    else:
                        # Reset — only keep trailing uncaptured block
                        uncaptured = []

                if uncaptured and len(" ".join(uncaptured)) > 10:
                    cleaned_sections.append({
                        "sectionContent": "\n".join(uncaptured),
                    })

            result["content"]["sections"] = cleaned_sections

    # Clean creators
    if "creators" in result and isinstance(result["creators"], list):
        for creator in result["creators"]:
            if isinstance(creator, dict) and "name" in creator:
                creator["name"] = _clean_unicode_artifacts(creator.get("name", ""))

    # Clean titles
    if "titles" in result and isinstance(result["titles"], list):
        for title_obj in result["titles"]:
            if isinstance(title_obj, dict) and "title" in title_obj:
                title_obj["title"] = _clean_unicode_artifacts(title_obj.get("title", ""))

    # Normalize licenses to SPDX form when confidently matched
    if "rightsList" in result:
        from .normalize import normalize_rights_list

        result["rightsList"] = normalize_rights_list(result["rightsList"])

    # Cleanup + dedupe subjects
    if "subjects" in result:
        from .normalize import normalize_subjects

        result["subjects"] = normalize_subjects(result["subjects"])

    # Heuristic language detection on the raw body text. Overwrites any
    # value the LLM may have emitted — the model has been observed to
    # hallucinate `language` from English metadata fragments (e.g. the
    # figshare Japanese poster at DOI 10.6084/m9.figshare.10116536.v1).
    if raw_text:
        from .language import detect_language

        detected = detect_language(raw_text)
        if detected:
            result["language"] = detected
        else:
            # Body text too short or detector unsure — null is more
            # honest than guessing.
            result["language"] = None

    # ROR enrichment for affiliations and publisher
    from .ror import enrich_persons, enrich_publisher, get_default_client

    ror = get_default_client()
    if "creators" in result:
        result["creators"] = enrich_persons(result["creators"], ror)
    if "contributors" in result:
        result["contributors"] = enrich_persons(result["contributors"], ror)
    if "publisher" in result:
        result["publisher"] = enrich_publisher(result["publisher"], ror)

    # Funder + award normalization, then ROR funder lookup
    if "fundingReferences" in result:
        from .normalize import normalize_funding_references

        result["fundingReferences"] = normalize_funding_references(
            result["fundingReferences"]
        )

        from .funders import enrich_funding_references
        from .funders import get_default_client as get_funder_client

        result["fundingReferences"] = enrich_funding_references(
            result["fundingReferences"], get_funder_client()
        )

    # Enrich with identifiers from raw text
    if raw_text:
        from .identifiers import enrich_json_with_identifiers

        result = enrich_json_with_identifiers(result, raw_text)

    # ORCID lookup for creators still missing one (after regex extraction)
    if "creators" in result:
        from .orcid import enrich_creators_orcid
        from .orcid import get_default_client as get_orcid_client

        result["creators"] = enrich_creators_orcid(
            result["creators"], get_orcid_client()
        )

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


def extract_json_with_retry(raw_text: str, model, tokenizer) -> dict:
    """
    Send raw poster text to the LLM and robustly parse the JSON response.

    This function:
      1. Normalizes Unicode in the raw text
      2. Calls the model with a full prompt
      3. Retries with more tokens if truncation is detected
      4. Falls back to a shorter prompt if needed
      5. Runs repair passes to make the JSON parseable
    """
    raw_text = _normalize_raw_text_for_model(raw_text)
    prompt = EXTRACTION_PROMPT.format(raw_text=raw_text)

    log("Starting primary JSON extraction with full prompt")
    response = _generate(model, tokenizer, prompt, MAX_JSON_TOKENS)
    result = _robust_json_parse(response)
    if "error" in result:
        log(f"Primary JSON parse error: {result['error']}")
    else:
        log("Primary JSON parse succeeded")

    # Retry with more tokens if truncation detected
    if "error" in result or _is_truncated(result.get("raw", "")):
        log(f"Retrying with max_tokens={MAX_RETRY_TOKENS}")
        response = _generate(model, tokenizer, prompt, MAX_RETRY_TOKENS)
        result = _robust_json_parse(response)

    # Fallback to shorter prompt
    if "error" in result or _is_truncated(result.get("raw", "")):
        log("Using fallback shorter prompt")
        fallback_prompt = FALLBACK_PROMPT.format(raw_text=raw_text)
        response = _generate(model, tokenizer, fallback_prompt, MAX_RETRY_TOKENS)
        result = _robust_json_parse(response)

    result = _postprocess_json(result, raw_text=raw_text)
    return result


def extract_poster(
    poster_path: str,
    model_id: Optional[str] = None,
    quantization: Optional[str] = None,
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
    """
    log(f"Processing poster: {poster_path}")

    # For image posters: unload the JSON model BEFORE the vision model
    # loads. Qwen2-VL-7B at bf16 needs ~15GB; on a 24GB card the JSON
    # model warm-loaded by api.py healthcheck is ~9GB resident, leaving
    # the vision load short by a few hundred MB and OOMing.
    # Cost: ~10s of JSON reload after OCR. PDF posters skip this branch.
    ext = Path(poster_path).suffix.lower()
    if ext in {".jpg", ".jpeg", ".png"}:
        unload_json_model()

    # Extract raw text
    t_extract_start = time.time()
    raw_text, source = get_raw_text(poster_path)
    t_extract_elapsed = time.time() - t_extract_start

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
        generated = extract_json_with_retry(raw_text, model, tokenizer)
        t_json_elapsed = time.time() - t_json_start

        if "error" in generated:
            log(f"Extraction completed with error after {t_json_elapsed:.2f}s")
        else:
            log(f"Extraction succeeded in {t_json_elapsed:.2f}s")

        unload_json_model()
        return generated
    except Exception as e:
        log(f"ERROR: {e}")
        import traceback

        traceback.print_exc()
        unload_json_model()
        return {"error": str(e)}
