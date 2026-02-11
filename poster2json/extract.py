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
SCHEMA_URL = "https://posters.science/schema/v0.1/poster_schema.json"

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


def _parse_alto_xml(xml_path: str) -> Optional[str]:
    """Parse ALTO XML output from pdfalto."""
    from xml.etree import ElementTree as ET

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        text_blocks = root.findall(".//{http://www.loc.gov/standards/alto/ns-v3#}TextBlock")
        if not text_blocks:
            text_blocks = root.findall(".//TextBlock")

        lines = []
        for block in text_blocks:
            strings = block.findall(".//{http://www.loc.gov/standards/alto/ns-v3#}String")
            if not strings:
                strings = block.findall(".//String")
            words = [s.get("CONTENT", "") for s in strings if s.get("CONTENT")]
            if words:
                lines.append(" ".join(words))
        return "\n".join(lines)
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


def load_json_model(force_full_precision: bool = False):
    """Load Llama 3.1 8B for JSON structuring."""
    global _json_model, _json_tokenizer
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

        log(f"Loading {JSON_MODEL_ID} for JSON structuring on {device}...")

        try:
            _json_tokenizer = AutoTokenizer.from_pretrained(JSON_MODEL_ID)

            use_8bit = free_gb < 16 and device != "cpu" and not force_full_precision

            # Try Flash Attention 2
            try:
                import flash_attn

                attn_impl = "flash_attention_2"
                log("   Using Flash Attention 2 for faster inference")
            except ImportError:
                attn_impl = None
                log("   Flash Attention not available, using default attention")

            if use_8bit:
                log(f"   Using 8-bit quantization (only {free_gb:.1f}GB free)")
                model_kwargs = {
                    "load_in_8bit": True,
                    "device_map": device_map_value,
                    "low_cpu_mem_usage": True,
                }
                if attn_impl:
                    model_kwargs["attn_implementation"] = attn_impl
                _json_model = AutoModelForCausalLM.from_pretrained(JSON_MODEL_ID, **model_kwargs)
            else:
                if force_full_precision and free_gb < 16:
                    log(f"   Forcing full precision for quality ({free_gb:.1f}GB free)")
                model_kwargs = {
                    "torch_dtype": torch.bfloat16,
                    "device_map": device_map_value,
                    "low_cpu_mem_usage": True,
                }
                if attn_impl:
                    model_kwargs["attn_implementation"] = attn_impl
                _json_model = AutoModelForCausalLM.from_pretrained(JSON_MODEL_ID, **model_kwargs)
            log(f"   ✓ JSON model loaded on {device}")
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
3. Common section headers: Abstract, Introduction, Background, Methods, Results, Key Findings, Discussion, Conclusions, References, Acknowledgements, Contact
4. Each section must have its OWN "sectionTitle" and "sectionContent"
5. Copy ALL text EXACTLY - do not paraphrase or summarize
6. "Key Findings" ≠ "References": Key Findings = discoveries/results; References = numbered citations with authors/years

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
  "conference": {{
    "conferenceName": "Name of Conference",
    "conferenceYear": 2025,
    "conferenceLocation": "City, Country",
    "conferenceStartDate": "YYYY-MM-DD",
    "conferenceEndDate": "YYYY-MM-DD"
  }},
  "formats": ["PDF"],
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
- conference: conferenceName and conferenceYear are REQUIRED; extract from poster header/footer
- formats: Set to ["PDF"] for PDF files, ["PNG"] or ["JPEG"] for images
- imageCaptions/tableCaptions: Use "id" field (e.g., "fig1") for cross-referencing if needed
- rightsList: OPTIONAL - include if license/copyright info found on poster

POSTER TEXT TO CONVERT:
{raw_text}

OUTPUT VALID JSON ONLY:"""

FALLBACK_PROMPT = """Convert poster text to JSON. REQUIRED FIELDS:
1. creators, titles, publicationYear, subjects, descriptions, publisher, conference, formats, content
2. SEPARATE section for EACH header (Abstract, Intro, Methods, Results, Discussion, Conclusions, References)
3. Copy ALL text EXACTLY verbatim

{{
  "creators": [{{"name": "LastName, FirstName", "givenName": "FirstName", "familyName": "LastName", "affiliation": ["Institution"]}}],
  "titles": [{{"title": "Poster Title"}}],
  "publicationYear": 2025,
  "subjects": [{{"subject": "keyword1"}}, {{"subject": "keyword2"}}],
  "descriptions": [{{"description": "Abstract text", "descriptionType": "Abstract"}}],
  "publisher": {{"name": "Conference or Institution"}},
  "conference": {{"conferenceName": "Conference Name", "conferenceYear": 2025, "conferenceLocation": "Location"}},
  "formats": ["PDF"],
  "content": {{
    "sections": [{{"sectionTitle": "Header", "sectionContent": "verbatim text"}}]
  }},
  "imageCaptions": [{{"id": "fig1", "caption": "Figure 1. Caption"}}],
  "tableCaptions": [{{"id": "table1", "caption": "Table 1. Caption"}}]
}}

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
    """Fix quotes that appear after / which are not properly escaped."""
    s = re.sub(
        r'(\d+\s*(?:pc|km|m|cm|mm|Hz|kHz|MHz|GHz|s|ms|ns|arcsec|arcmin|deg))/"',
        r'\1/\\"',
        s,
    )
    s = re.sub(r'\((\d+\.?\d*\s*\w+)/"\)', r'(\1/\\")', s)
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
    """Remove bidirectional Unicode markers and other artifacts."""
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

    text = re.sub(r"[\u00a0\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]", " ", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def _normalize_captions(captions_input) -> list:
    """Normalize captions to object format with id and caption fields."""
    normalized = []
    seen_texts = set()

    # Handle various input formats
    if isinstance(captions_input, str):
        return [{"caption": captions_input}] if captions_input.strip() else []

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

    return normalized


def _postprocess_json(data: dict) -> dict:
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

    # Ensure caption fields exist and normalize to string arrays
    for key in ["imageCaptions", "tableCaptions"]:
        if key not in result:
            result[key] = []
        elif isinstance(result[key], (dict, list)):
            result[key] = _normalize_captions(result[key])

    # Clean Unicode from string fields
    for key in ["researchField"]:
        if key in result and isinstance(result[key], str):
            result[key] = _clean_unicode_artifacts(result[key])

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
                    cleaned_sections.append({"sectionTitle": title, "sectionContent": content})
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

    return result


# ============================
# MAIN EXTRACTION FUNCTION
# ============================


def extract_json_with_retry(raw_text: str, model, tokenizer) -> dict:
    """
    Send raw poster text to the LLM and robustly parse the JSON response.

    This function:
      1. Calls the model with a full prompt
      2. Retries with more tokens if truncation is detected
      3. Falls back to a shorter prompt if needed
      4. Runs repair passes to make the JSON parseable
    """
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

    result = _postprocess_json(result)
    return result


def extract_poster(poster_path: str) -> dict:
    """
    Extract structured JSON metadata from a scientific poster.

    This is the main entry point for poster extraction.

    Args:
        poster_path: Path to the poster file (PDF, JPG, or PNG)

    Returns:
        Dictionary containing structured poster metadata conforming to
        the poster-json-schema.

    Example:
        >>> result = extract_poster("poster.pdf")
        >>> print(result["titles"][0]["title"])
        "Machine Learning Approaches to Diabetic Retinopathy Detection"
    """
    log(f"Processing poster: {poster_path}")

    # Extract raw text
    t_extract_start = time.time()
    raw_text, source = get_raw_text(poster_path)
    t_extract_elapsed = time.time() - t_extract_start

    if not raw_text or source == "unknown":
        return {"error": "Failed to extract text. Unsupported format or extraction failed."}

    log(f"Extracted {len(raw_text)} chars using {source} in {t_extract_elapsed:.2f}s")

    # Unload vision model before loading JSON model
    ext = Path(poster_path).suffix.lower()
    is_image_poster = ext in [".jpg", ".jpeg", ".png"]
    unload_vision_model()

    # Load JSON model
    model, tokenizer = load_json_model(force_full_precision=is_image_poster)

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
