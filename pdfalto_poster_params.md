# PDFAlto Custom Parameters & Heuristics in poster2json

Every numerical cutoff, heuristic, and custom parameter in the poster2json pdfalto pipeline. These were tuned empirically against our poster corpus and are load-bearing — any migration target must replicate or improve on each one.

Source file: `poster2json/extract.py`

---

## 1. CLI Flags

| Flag | Line | Purpose |
|------|------|---------|
| `-noImage` | 271 | Suppress image extraction, text only |
| `-readingOrder` | 271 | Preserve native reading order for multi-column poster layouts |
| `timeout=60` | 274 | 60-second subprocess timeout to prevent hangs on malformed PDFs |

These are the only two flags passed to the pdfalto binary. Everything below is how we interpret and transform the ALTO XML output.

---

## 2. Duplicate Line Detection

**Location:** `_parse_alto_xml()`, lines 422–431

Within each `<TextBlock>`, lines at the same vertical position with high word overlap are dropped as duplicates. pdfalto sometimes emits the same line twice with slightly different coordinates.

| Parameter | Value | Purpose |
|-----------|-------|---------|
| VPOS tolerance | `< 2` units | Two lines within 2 ALTO units of each other vertically are candidates for dedup |
| Word overlap threshold | `> 0.8` (80%) | If >80% of words match (set intersection / max set size), the second line is dropped |

---

## 3. Column Boundary Detection

**Location:** `_detect_column_boundaries()`, lines 335–374

Detects column structure by analyzing gaps between block center-x positions. Used to validate that pdfalto's reading order is sane.

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Minimum gap width | `page_width * 0.05` (5% of page) | A horizontal gap must exceed 5% of page width to register as a column boundary |
| Max column boundaries | `6` | Up to 6 boundaries = 7 columns max. Posters rarely exceed this. |
| Min blocks per column | `3` | A column must contain at least 3 text blocks to be valid; prevents false splits from stray elements |

Algorithm: sort all block center-x values, find gaps > 5% page width, take the 6 largest, then prune any boundary that would create a column with fewer than 3 blocks.

---

## 4. Font/Style Parsing

**Location:** `_parse_text_styles()`, lines 293–332

Parses `<TextStyle>` definitions from the ALTO `<Styles>` section. These feed into header detection.

| Parameter | Value | Purpose |
|-----------|-------|---------|
| FONTSIZE | float from `FONTSIZE` attribute | Font size per style ID |
| Bold detection | `"bold" in FONTSTYLE.lower()` | Boolean flag per style |
| Italic detection | `"italic" in FONTSTYLE.lower()` | Boolean flag per style |
| Namespace fallback | Try `{http://www.loc.gov/standards/alto/ns-v3#}`, then bare | Handles both namespaced and non-namespaced ALTO XML output |

---

## 5. Header Detection

**Location:** `_parse_alto_xml()`, lines 486–513

Identifies section headers in the poster by combining font size analysis with conservative text-pattern filters. Detected headers are prefixed with `## ` so the downstream LLM can use them for section segmentation.

### Median Body Font Size Calculation (line 472)

```
median_fontsize = sorted(all_fontsizes)[len // 2]
```

Computed across all style-referenced blocks. This is the baseline for "normal" text.

### Header Qualification Filters (all must pass)

| Filter | Value | Purpose |
|--------|-------|---------|
| Max text length | `<= 120` characters | Long blocks are body text, not headers |
| Starts with letter | `re.match(r'[A-Za-z]')` | Skips blocks starting with bullets, numbers, or symbols |
| Min alphabetic words | `>= 2` words of 2+ letters | Single-word fragments aren't headers |
| Contact exclusion: email | `@\S+\.\S+` | Blocks containing email addresses are never headers |
| Contact exclusion: phone | `\+\d[\d\s]{6,}` | Blocks containing phone numbers are never headers |
| Contact exclusion: URL | `www\.` or `https?://` | Blocks containing URLs are never headers |

### Header Font Thresholds (either triggers header)

| Condition | Threshold | Purpose |
|-----------|-----------|---------|
| Bold + large enough | `bold AND fontsize >= median_fontsize` | Bold text at or above median body size = header |
| Large font (any style) | `fontsize > median_fontsize * 1.3` | Any font >1.3x the median = header, regardless of bold |

---

## 6. Block-Level Processing Decisions

**Location:** `_parse_alto_xml()`, lines 437–481

These are deliberate architectural decisions, not just parameters — each one was learned the hard way.

| Decision | Value/Behavior | Rationale |
|----------|---------------|-----------|
| Line joining within blocks | Single space join of all lines per block (line 439) | Preserving PDF line breaks splits mid-sentence and confuses the LLM during JSON structuring |
| Block-level deduplication | **REMOVED** (lines 462–464) | Was incorrectly dropping legitimate blocks with similar text at similar vpos (e.g. "724 words" vs "755 words" in adjacent columns) |
| Gap markers (blank lines between blocks) | **REMOVED** (lines 479–481) | Blank lines changed how the LLM segmented content vs. reference annotations, hurting validation scores |
| Reading order sort | **DELIBERATELY SKIPPED** (lines 474–477) | Do NOT sort blocks by vpos — pdfalto's `-readingOrder` flag already handles column layout correctly. Sorting by vpos scrambles multi-column poster content. |

---

## 7. Text Normalization Pre-Model

**Location:** `_normalize_raw_text_for_model()`, lines 1281–1308

Applied to raw pdfalto text before it's sent to the LLM for JSON structuring. Reduces token count and prevents JSON parse failures from quote characters.

| Transformation | Implementation | Purpose |
|----------------|----------------|---------|
| NFKD normalization | `unicodedata.normalize("NFKD")` | Converts superscripts (¹²³⁺), subscripts (ₛ), and compatibility chars to ASCII equivalents. Cuts token count. |
| Combining mark removal | Filter `unicodedata.combining(c)` | Strips diacritics left by NFKD decomposition |
| Smart double quotes → `'` | `“ ”` → `'` | Prevents model from outputting unescaped `"` inside JSON string values |
| Smart single quotes → `'` | `‘ ’` → `'` | Same rationale |
| Guillemets → `'` | `« »` → `'` | Same rationale (French/Spanish posters) |
| Mixed-pair cleanup | `re.sub(r"'(\w+...)\\"")` | Fixes leftover curly-open + straight-close pairs |
| Inline scare-quote fix | `re.sub(r'...\"...\"...')` | `word "quoted" word` → `word 'quoted' word` to prevent JSON breakage |

---

## 8. Post-Extraction Unicode Cleanup

**Location:** `_clean_unicode_artifacts()`, lines 1005–1041

Applied to the structured JSON output. Uses NFKC (not NFKD) to recompose accented characters for byte-level comparison in downstream systems.

| Transformation | Implementation | Purpose |
|----------------|----------------|---------|
| NFKC normalization | `unicodedata.normalize("NFKC")` | Recomposes accented characters (é as one codepoint, not e + combining acute). Required for Spanish, German, French posters. |
| Bidi/zero-width removal | 16 specific codepoints stripped | LRM (`‎`), RLM (`‏`), embedding controls (`‪`–`‮`), isolates (`⁦`–`⁩`), ZWS (`​`), ZWNJ (`‌`), ZWJ (`‍`), BOM (`﻿`), soft hyphen (`­`) |
| Unicode whitespace normalization | `[  -     　]` → ASCII space | Normalizes NBSP, em/en/thin/hair spaces, line/paragraph separators, ideographic space |
| Multi-space collapse | `r" {2,}"` → single space | Cleans up whitespace runs left by prior transformations |

---

## 9. Minimum Text Quality Gate

**Location:** `get_raw_text()`, line 575

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Min pdfalto output | `> 500` characters | If pdfalto produces ≤500 characters, the pipeline falls back to PyMuPDF. Catches scanned-image PDFs and extraction failures. |

---

## 10. Uncaptured Text Recovery

**Location:** `_postprocess_json()`, lines 1159–1198

After the LLM generates JSON, this pass compares the raw pdfalto text against the structured sections and recovers any trailing content the LLM dropped (commonly footer text, contact info, URLs).

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Word overlap threshold | `< 0.5` (50%) | A raw text line is "uncaptured" if fewer than 50% of its words appear in any section's content |
| Min recovered length | `> 10` characters | Only appends recovered block if it contains meaningful content |
| Recovery scope | Trailing contiguous block only | Resets on each captured line — only the last contiguous run of uncaptured lines is recovered |

---

## 11. JSON Repair Passes

**Location:** `_repair_unescaped_quotes()`, lines 861–878

These handle JSON breakage caused by pdfalto-extracted text containing quotes that survive into the model output.

| Repair | Pattern | Purpose |
|--------|---------|---------|
| Unit-slash quotes | `(\d+ pc/")` → `(\d+ pc/\\")` | Fixes unescaped quotes after unit denominators (e.g. `16.7 pc/"`) |
| Parenthesized unit-slash | `(\d+ \w+/")` → escaped | Same pattern inside parentheses |
| Inline scare-quotes | `word "quoted" word` → `word 'quoted' word` | Converts remaining unescaped double quotes inside JSON values to single quotes |

---

## Summary

**30+ individually tuned parameters across 11 pipeline stages:**

1. CLI flags (2 flags + timeout)
2. Duplicate line detection (2 thresholds)
3. Column boundary detection (3 thresholds)
4. Font/style parsing (4 attributes + namespace fallback)
5. Header detection (6 filters + 2 font thresholds + median calculation)
6. Block-level processing (4 architectural decisions, 2 of which are deliberate removals)
7. Pre-model text normalization (7 transformations)
8. Post-extraction Unicode cleanup (4 transformations + 16 specific codepoints)
9. Text quality gate (1 threshold)
10. Uncaptured text recovery (3 parameters)
11. JSON repair (3 patterns)

Any replacement for pdfalto must produce output that allows these same heuristics to function, or each one must be consciously re-evaluated and re-tuned against the poster corpus.
