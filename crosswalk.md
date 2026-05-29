# PDFAlto → pdfplumber Migration Crosswalk

Parameter-by-parameter crosswalk from the pdfalto extraction pipeline to pdfplumber. Every cutoff, heuristic, and architectural decision from `pdfalto_poster_params.md` is mapped to its pdfplumber equivalent, with rationale for changes.

> **Status (v0.8.0): migration complete.** pdfplumber is the default and only PDF text extractor; PyMuPDF remains as a low-text fallback. All pdfalto code is removed — `_parse_alto_xml()`, `_parse_text_styles()`, `extract_text_with_pdfalto()`, the `PDFALTO_PATH` lookup, and the `subprocess`/ALTO-XML machinery no longer exist in `extract.py`. This document is retained as the migration record and a parameter reference.
>
> **Reading order has since been rewritten.** §§5–7 and §10 describe the *initial* migration design (geometric line grouping → column-boundary detection → column-major ordering). That subsystem was superseded by a recursive **XY-cut** splitter in `poster2json/xy_cut.py` (see §7). The column-detection helpers (`_detect_column_boundaries`, `_detect_column_boundaries_from_gaps`, `_validate_boundaries`, `_group_words_into_lines`, `_assign_lines_to_columns`) remain defined in `extract.py` but are **no longer called**. For the current pipeline see [docs/architecture.md](docs/architecture.md); for current validation scores see [docs/evaluation.md](docs/evaluation.md).
>
> Line numbers below are approximate as of the migration commit. Function names are the stable anchors.

Source files: `poster2json/extract.py`, `poster2json/xy_cut.py`
- pdfalto path: removed (was `_parse_alto_xml()`, `_parse_text_styles()`)
- pdfplumber path: `extract_text_with_pdfplumber()` and helpers
- reading order: `xy_cut.chars_to_reading_order()` (replaced the column-assignment helpers)

---

## 1. PDF Extraction Invocation

### pdfalto

| Flag | Purpose |
|------|---------|
| `-noImage` | Suppress image extraction, text only |
| `-readingOrder` | Preserve native reading order for multi-column layouts |
| `timeout=60` | 60-second subprocess timeout |

Invoked as a subprocess calling the pdfalto binary. Outputs ALTO XML which is then parsed by `_parse_alto_xml()`.

### pdfplumber

| Setting | Value | Purpose | Sensitivity |
|---------|-------|---------|-------------|
| `use_text_flow=True` | Enabled | Uses PDF's internal character stream order instead of geometric sorting. Replaces pdfalto's `-readingOrder` flag. | **HIGH** — disabling this scrambles multi-column reading order. This is the single most important setting. |
| `extra_attrs=["size"]` | Font size grouping | Groups words by font size to preserve size metadata. `fontname` is deliberately excluded (see §4). | **MEDIUM** — adding `fontname` to extra_attrs breaks words at font-subset boundaries (ligature glyphs in different subsets). |
| No subprocess | Pure Python | No binary dependency, no timeout needed. pdfplumber runs in-process via `pdfplumber.open()`. | N/A |
| No `-noImage` equivalent needed | pdfplumber extracts text only by default | Image data is accessed via separate `page.images` API, never mixed with text. | N/A |

**Key difference:** pdfalto outputs structured ALTO XML (TextBlocks → TextLines → Strings). pdfplumber outputs flat character arrays (`page.chars`) which we process through `_pw_extract_words()` to get word-level bounding boxes, then build lines/blocks ourselves.

---

## 2. Phantom Space Filtering (NEW — pdfplumber only)

**Location:** `_filter_phantom_spaces()`, line 576

Some PDFs embed invisible space glyphs on top of real characters, causing `extract_words` to split words at phantom boundaries (e.g. "For" → "F or"). pdfalto did not have this problem because ALTO XML encodes words as `<String>` elements directly.

| Parameter | Value | Purpose | Sensitivity |
|-----------|-------|---------|-------------|
| Containment tolerance | `± 1pt` | A space is phantom if its [x0, x1] falls within a non-space char's [x0, x1] ± 1pt | **LOW** — tight tolerance avoids false positives |
| Row matching | `± 1 row` (rounded top) | Checks adjacent pixel rows for containment matches | **LOW** — handles minor vertical misalignment |

**pdfalto equivalent:** None needed — ALTO XML pre-segments words.

---

## 3. Font/Style Parsing

### pdfalto

Parsed from `<TextStyle>` definitions in ALTO `<Styles>` section:

| Attribute | Source |
|-----------|--------|
| FONTSIZE | `FONTSIZE` XML attribute (float) |
| Bold | `"bold" in FONTSTYLE.lower()` |
| Italic | `"italic" in FONTSTYLE.lower()` |
| Namespace | Try `{http://www.loc.gov/standards/alto/ns-v3#}`, then bare |

### pdfplumber

| Attribute | Source | Sensitivity |
|-----------|--------|-------------|
| Font size | `word["size"]` — directly from `extra_attrs=["size"]` in `_pw_extract_words()` | **NONE** — native attribute |
| Bold | `_parse_font_style(fontname)`: checks for `"bold"`, `"black"`, `"heavy"` in full name; `"bd"`, `"demi"` in suffix after last hyphen | **MEDIUM** — font naming conventions vary; suffix parsing (`rsplit("-", 1)[-1]`) catches `Arial-BoldMT` patterns |
| Italic | `_parse_font_style(fontname)`: checks for `"italic"`, `"oblique"` in full name; `"it"` in suffix | **LOW** — italic rarely affects pipeline decisions |

**Key difference:** pdfplumber gives us `fontname` per character (e.g. `"AAAAAH+TimesNewRoman-BoldMT"`), not a pre-parsed style. We parse bold/italic from the name string in `_parse_font_style()` (line 561).

### Font Annotation Strategy

**Location:** `_annotate_words_with_fonts()`, line 618

Fonts are NOT included in `extra_attrs` for `extract_words` because PDF font subsetting creates multiple fontname variants for the same visual font (e.g. `AAAAAH+Arial`, `AAAAAI+Arial` for different glyph subsets). Including `fontname` in `extra_attrs` would split single words at subset boundaries.

Instead, we extract words with `extra_attrs=["size"]` only, then retroactively assign the dominant fontname from overlapping raw characters.

| Parameter | Value | Purpose | Sensitivity |
|-----------|-------|---------|-------------|
| Top tolerance | `± 2 rows` | Match chars within 2pt vertically of the word | **LOW** |
| X tolerance | `± 1pt` | Match chars within word's horizontal extent | **LOW** |
| Dominant font | `max(set(fonts), key=fonts.count)` | Most frequent fontname among matching chars | **LOW** — majority vote is robust |

---

## 4. Duplicate Line Detection

### pdfalto

| Parameter | Value | Purpose |
|-----------|-------|---------|
| VPOS tolerance | `< 2` ALTO units | Two lines at same vertical position |
| Word overlap | `> 0.8` (80%) | Set intersection / max set size |

### pdfplumber

**Location:** `_lines_to_blocks()`, line 804 (within block assembly)

| Parameter | Value | Purpose | Sensitivity |
|-----------|-------|---------|-------------|
| VPOS tolerance | `< 2pt` | Same threshold, but in PDF points (1/72 inch) rather than ALTO units. In practice these are similar scale. | **LOW** — dedup is conservative |
| Word overlap | `> 0.8` (80%) | Identical threshold | **LOW** |

**Key difference:** In pdfalto, dedup happened within each `<TextBlock>`. In pdfplumber, dedup happens during block assembly in `_lines_to_blocks()`, after lines are grouped into blocks. Same logic, different pipeline position.

---

## 5. Line Grouping (NEW — replaces ALTO TextLine)

> **Superseded by XY-cut (§7).** `_group_words_into_lines()` is no longer called. Lines now come from the XY-cut leaf clustering in `xy_cut._cluster_lines()` (baseline tolerance `BASELINE_RANGE = 0.5 × avg font size`), then re-aggregated to word level by `_chars_to_word_lines()`. The parameters below describe the original geometric grouper, kept here as a reference.

**Location:** `_group_words_into_lines()`, line 650 (retained, uncalled)

pdfalto provides `<TextLine>` elements directly. pdfplumber gives raw words that we must group into lines.

| Parameter | Value | Purpose | Sensitivity |
|-----------|-------|---------|-------------|
| Vertical tolerance (`vtol`) | `3.0pt` | Words within 3pt vertically are on the same line | **HIGH** — too small splits subscripts/superscripts into separate lines; too large merges vertically adjacent lines |
| Sort order | By `(top, x0)` | Y-position primary, x-position secondary | **MEDIUM** — ensures left-to-right within each line |

---

## 6. Column Boundary Detection

> **Superseded by XY-cut (§7).** Explicit column-boundary detection is gone. The XY-cut splitter discovers column structure implicitly as vertical gaps in the recursion, so there is no boundary list to compute or validate. `_detect_column_boundaries()`, `_detect_column_boundaries_from_gaps()`, and `_validate_boundaries()` remain defined but are uncalled. The original design is documented below.

### pdfalto

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Minimum gap width | `page_width * 0.05` (5%) | Gap must exceed 5% of page width |
| Max boundaries | `6` (7 columns max) | Upper limit on column count |
| Min blocks per column | `3` | Prevents false splits from stray elements |

Algorithm: sort block center-x values, find gaps > 5%, take 6 largest, prune columns with < 3 blocks.

### pdfplumber

**Location:** `_detect_column_boundaries()`, line 336

| Parameter | Value | Purpose | Sensitivity |
|-----------|-------|---------|-------------|
| Minimum gap width | `page_width * 0.05` (5%) | **Identical** to pdfalto | **MEDIUM** — this threshold works across our corpus |
| Max boundaries | `6` (7 columns max) | **Identical** | **LOW** — posters rarely exceed 4 columns |
| Min blocks per column | `3` | **Identical** | **MEDIUM** — prevents single-element false columns |

**Input difference:** pdfalto used block center-x values; pdfplumber uses line center-x values (since blocks haven't been formed yet at this stage). This gives more data points and finer-grained gap detection.

### Boundary Validation (NEW — pdfplumber only)

**Location:** `_validate_boundaries()`, line 378

An additional validation pass not present in pdfalto. Checks that detected column boundaries have supporting evidence in the actual text layout.

| Parameter | Value | Purpose | Sensitivity |
|-----------|-------|---------|-------------|
| Word gap threshold | `≥ 15pt` | A word-to-word gap must be at least 15pt to count as gutter evidence | **HIGH** — too low picks up normal word spacing; too high misses narrow gutters |
| Boundary tolerance | `page_width * 0.05` | Gap midpoint must be within 5% of page width of the boundary | **MEDIUM** — allows for imprecise column alignment |
| Min support lines | `3` | At least 3 lines must show a gap near the boundary | **MEDIUM** — prevents single-line false boundaries |

---

## 7. Reading Order (recursive XY-cut)

### pdfalto

pdfalto's `-readingOrder` flag handled this internally. The ALTO XML output was already in reading order. poster2json deliberately **did not** sort by vpos to preserve pdfalto's ordering.

### pdfplumber (current)

The flow-order + column-assignment approach originally written for the migration could not represent layouts where spanning blocks (titles, footnotes, sidebars) interleave between column groups — the column-major `(col, vpos)` sort always grouped a whole column together. It was replaced by a port of xpdf's recursive **XY-cut** tree, the same algorithm behind pdfalto's `-readingOrder`.

**Location:** `poster2json/xy_cut.py`, `chars_to_reading_order(chars, page_width, page_height)`, called from `extract_text_with_pdfplumber()` (line 870).

The splitter works on `page.chars` directly (not pre-grouped lines). At each level it finds the largest vertical and horizontal gaps among the character bounding boxes; if a gap clears a font-size-relative threshold it cuts there and recurses, preferring column (vertical) cuts. Equally-large gaps at the same level are co-cut. Leaf chunks are clustered into lines by baseline proximity, then the tree is walked in reading order (vertical-split children left-to-right, horizontal-split children top-to-bottom).

| Constant | Value | Purpose | Sensitivity |
|----------|-------|---------|-------------|
| `MIN_GAP_AREA` | `3.0` | A candidate gap must satisfy `gap_width × block_height ≥ MIN_GAP_AREA × avg_font_size²` to be a split point | **HIGH** — the primary cut gate; too low over-splits prose, too high merges columns |
| `MIN_GAP_SIZE` | `0.2` | Floor on gap width as a fraction of `avg_font_size` before a gap is even considered | **MEDIUM** |
| `SPLIT_GAP_SLACK` | `0.2` | Gaps within `SPLIT_GAP_SLACK × avg_font_size` of the largest are co-cut at the same level (handles evenly-spaced multi-column grids) | **MEDIUM** |
| `MIN_CHUNK_WIDTH` | `2.0` | Each child chunk must exceed `MIN_CHUNK_WIDTH × avg_font_size` wide, else the split is rejected | **MEDIUM** — prevents slivering off single-glyph columns |
| `BASELINE_RANGE` | `0.5` | Leaf chars within `BASELINE_RANGE × avg_font_size` vertically are clustered onto one line | **HIGH** — too small splits sub/superscripts; too large merges adjacent lines |
| `DESCENT_ADJUST` | `0.35` | Char center used for containment is shifted toward the baseline by this fraction of height (matches xpdf's `descentAdjustFactor`) | **LOW** |

**Spanning-block promotion:** after the tree is built, `_promote_spanning_leaves()` lifts full-width leaves (titles, banners, footnotes that cross the whole text span) out of any single column so they emit in their true top-to-bottom position rather than being trapped inside the first column. `_merge_bottom_region()` does the same for a full-width footer band. This is the specific capability the old column-major sort lacked.

**Bridge to the block builder:** `_chars_to_word_lines(reading_lines, words)` (line 737) maps the char-level XY-cut lines back onto the already-extracted word boxes (a word goes to the line where most of its chars land), so `_lines_to_blocks()` keeps its word-level input contract. Blocks are emitted in XY-cut order and tagged `col = 0` (line 877) — there is no longer any column index to sort on.

**`use_text_flow=True` is still set** on `_pw_extract_words()` (line 863), but only to get stable word bounding boxes; it is no longer the reading-order driver. Reading order comes entirely from the XY-cut tree.

**Key architectural difference:** pdfalto gave us reading order for free via xpdf's XY-cut. pdfplumber gives us raw chars, so we run that same XY-cut ourselves in `xy_cut.py` rather than approximating it with a column-major sort.

---

## 8. Block Assembly

### pdfalto

pdfalto provided `<TextBlock>` elements directly. Lines within blocks were joined with single spaces. poster2json used pdfalto's block boundaries as-is.

### pdfplumber

**Location:** `_lines_to_blocks()`, line 748

We build blocks from y-sorted lines within each column. A new block starts when any of these conditions is met:

| Trigger | Threshold | Purpose | Sensitivity |
|---------|-----------|---------|-------------|
| Vertical gap | `> median_line_height * 1.5` | Gap between lines exceeds 1.5× the column's median line height | **HIGH** — this is the primary block-break signal. Too high merges distinct sections; too low over-fragments paragraphs. The 4564017 DEVELOPED CONVECTION section has a 5.3pt gap below the 12pt threshold, causing a merge that contributes to r=0.74. |
| Font size jump | `size_ratio > 1.3` | Max/min font size ratio between adjacent lines exceeds 1.3× | **MEDIUM** — catches header-to-body transitions |
| Bold transition | `prev_bold != curr_bold AND gap > 0 AND short_line` | Bold-to-non-bold (or vice versa) when there's any vertical gap and either line is ≤120 chars | **MEDIUM** — detects section header boundaries |
| Line height floor | `max(h, 1.0)` | Minimum 1pt line height to prevent division by zero | **NONE** — safety clamp |

**Line joining within blocks:** single space join of all lines per block (identical to pdfalto).

---

## 9. Header Detection

### pdfalto

| Filter | Value |
|--------|-------|
| Max text length | `≤ 120` characters |
| Starts with letter | `re.match(r'[A-Za-z]')` |
| Min alphabetic words | `≥ 2` words of 2+ letters |
| Contact exclusion: email | `@\S+\.\S+` |
| Contact exclusion: phone | `\+\d[\d\s]{6,}` |
| Contact exclusion: URL | `www\.` or `https?://` |
| Bold + large enough | `bold AND fontsize >= median_fontsize` |
| Large font (any style) | `fontsize > median_fontsize * 1.3` |

### pdfplumber

**Location:** `extract_text_with_pdfplumber()`, line 1020

| Filter | Value | Change from pdfalto | Sensitivity |
|--------|-------|---------------------|-------------|
| Max text length | `≤ 120` characters | **Identical** | **LOW** |
| Starts with letter | `re.match(r'[A-Z]')` | **Changed:** uppercase only (vs any letter in pdfalto) | **LOW** — poster headers are virtually always uppercase-initial |
| Min alphabetic words | `≥ 2` (non-bold) or `≥ 1` (bold) | **Changed:** bold single-word headers are allowed (e.g. "ABSTRACT", "METHODS") | **MEDIUM** — improves recall for common bold single-word section headers |
| Contact exclusion: email | `@\S+\.\S+` | **Identical** | **LOW** |
| Contact exclusion: phone | `\+\d[\d\s]{6,}` | **Identical** | **LOW** |
| Contact exclusion: URL | `www\.` or `https?://` | **Identical** | **LOW** |
| Bold + large enough | `bold AND fontsize >= median_fontsize` | **Identical** | **MEDIUM** |
| Large font (any style) | `fontsize > median_fontsize * 1.3` | **Identical** | **MEDIUM** |

### Additional Filters (NEW — pdfplumber only)

| Filter | Value | Purpose | Sensitivity |
|--------|-------|---------|-------------|
| Single-char word ratio | `> 60%` words are single-character → skip block | Filters out spaced-out decorative text or OCR noise | **LOW** |
| Min block length | `> 3` characters (unless bullet chars) | Drops tiny stray text fragments | **LOW** |

---

## 10. Layout Zoning (NEW — pdfplumber only)

**Location:** `extract_text_with_pdfplumber()`, line 914

pdfplumber adds a layout zoning pass not present in pdfalto. The XY-cut tree (§7) already produces correct reading order; zoning then hoists page-level furniture (title banner, author/affiliation metadata, footer) out of the body flow so the LLM sees them in their conventional positions. Blocks are classified into four zones:

| Zone | Criterion | Sort Order |
|------|-----------|------------|
| Header | Title-font block (`fontsize ≥ 1.4 × page-median font`) in the top region (`vpos + height ≤ col_start + 2% page height`) | By vpos (top to bottom) |
| Meta | Narrow block in top 12% of page containing email/ORCID/`Authors` patterns | By (vpos, hpos) |
| Footer | Wide block (`width > 50% text span`) below column content end | By vpos |
| Body | Everything else | **Untouched — kept in XY-cut reading order** |

| Parameter | Value | Purpose | Sensitivity |
|-----------|-------|---------|-------------|
| Title-font threshold | `fontsize ≥ 1.4 ×` page-median font size | Identifies the spanning title/banner. **Changed from the original width-based test** — large headers in asymmetric layouts aren't always wider than 50% of the span, but they are reliably larger-font | **MEDIUM** |
| Wide threshold | `> 50%` of text span | Now used only for the footer test | **MEDIUM** |
| Top zone | `12%` of page height | Meta content (author affiliations, ORCIDs) region | **LOW** |
| Column start tolerance | `+ 2%` page height | Header blocks can extend slightly into column region | **LOW** |
| Min column block length | `10` characters | Blocks shorter than 10 chars don't count when computing column start position | **LOW** |
| Meta pattern | `@\S+\.\S+`, `orcid.org`, `ORCID:\s*\d`, `^Authors?\b` | Identifies affiliation/contact metadata blocks | **LOW** |

**Final sort order:** header → meta → body → footer. Header, meta, and footer are each vpos-sorted; **body blocks are not re-sorted** — they retain the XY-cut reading order from §7. (The old column-major `(col, vpos)` body sort was removed; re-sorting would undo the spanning-block interleaving the XY-cut tree produces.)

---

## 11. Text Normalization Pre-Model

**Location:** `_normalize_raw_text_for_model()`, line 1281

**Unchanged.** Both pdfalto and pdfplumber extracted text passes through the same normalization function before the LLM:

| Transformation | Implementation | Sensitivity |
|----------------|----------------|-------------|
| NFKD normalization | `unicodedata.normalize("NFKD")` | **LOW** |
| Combining mark removal | Filter `unicodedata.combining(c)` | **LOW** |
| Smart double quotes → `'` | `" "` → `'` | **LOW** |
| Smart single quotes → `'` | `' '` → `'` | **LOW** |
| Guillemets → `'` | `« »` → `'` | **LOW** |
| Mixed-pair cleanup | Regex fix for curly-open + straight-close | **LOW** |
| Inline scare-quote fix | `"quoted"` → `'quoted'` | **LOW** |

---

## 12. Post-Extraction Unicode Cleanup

**Location:** `_clean_unicode_artifacts()`, line 1005

**Unchanged.** Applied to structured JSON output from both paths:

| Transformation | Implementation | Sensitivity |
|----------------|----------------|-------------|
| NFKC normalization | `unicodedata.normalize("NFKC")` | **LOW** |
| Bidi/zero-width removal | 16 specific codepoints | **LOW** |
| Unicode whitespace normalization | Various Unicode spaces → ASCII space | **LOW** |
| Multi-space collapse | `r" {2,}"` → single space | **LOW** |

---

## 13. Minimum Text Quality Gate

**Location:** `get_raw_text()`, line 1093 (`MIN_PDF_TEXT_CHARS`, line 1041)

**Changed.** pdfplumber is now the primary PDF extractor; PyMuPDF is the fallback. `get_raw_text()` runs pdfplumber first and accepts its output if it has at least `MIN_PDF_TEXT_CHARS` characters, otherwise it falls back to PyMuPDF. (During the migration both pdfalto and pdfplumber shared a `> 500`-char gate; with pdfalto gone there is a single extractor and the gate dropped to 200.)

| Parameter | Value | Sensitivity |
|-----------|-------|-------------|
| `MIN_PDF_TEXT_CHARS` | `200` characters | **LOW** — catches scanned-image PDFs and extraction failures; below this, fall back to PyMuPDF |

---

## 14. Uncaptured Text Recovery

**Location:** `_postprocess_json()`, line 1159

**Unchanged.** Operates on the LLM's JSON output regardless of text extraction source:

| Parameter | Value | Sensitivity |
|-----------|-------|-------------|
| Word overlap threshold | `< 0.5` (50%) | **LOW** |
| Min recovered length | `> 10` characters | **LOW** |
| Recovery scope | Trailing contiguous block only | **LOW** |

---

## 15. JSON Repair

**Location:** `_repair_unescaped_quotes()`, line 861

**Unchanged.** Same repair patterns for both extractors:

| Repair | Pattern | Sensitivity |
|--------|---------|-------------|
| Unit-slash quotes | `(\d+ pc/")` → escaped | **LOW** |
| Parenthesized unit-slash | `(\d+ \w+/")` → escaped | **LOW** |
| Inline scare-quotes | `"quoted"` → `'quoted'` | **LOW** |

---

## Validation Scores (5-Poster Canary Set, 4bit quantization)

> **Interim numbers, kept for the migration record.** This 5-poster canary (build `v19c`) is what justified the cutover from pdfalto to pdfplumber — it shows pdfplumber matching or beating pdfalto on the same posters. It is **not** the final result. After the reading-order rewrite (§7) and the inline-section splitter, the full 20-poster set reaches **19/20 (95%)**. For current per-poster scores and aggregates see [docs/evaluation.md](docs/evaluation.md).

### pdfplumber v19c

| Poster | w | r | n | f | Pass |
|--------|------|------|------|------|------|
| 17268692 | 0.77 | 0.80 | 0.80 | 0.80 | ✅ |
| 4564017 | 0.90 | 0.74 | 0.95 | 0.84 | ❌ |
| 8228476 | 0.86 | 0.81 | 0.94 | 1.00 | ✅ |
| AISec2025 | 0.81 | 0.82 | 0.98 | 1.07 | ✅ |
| isporeu | 0.82 | 0.91 | 0.84 | 1.12 | ✅ |
| **Average** | **0.83** | **0.82** | **0.90** | **0.97** | **4/5** |

### pdfalto (same conditions)

| Poster | w | r | n | f | Pass |
|--------|------|------|------|------|------|
| 17268692 | 0.88 | 0.91 | 0.88 | 0.84 | ✅ |
| 4564017 | 0.73 | 0.73 | 0.85 | 0.78 | ❌ |
| 8228476 | 0.73 | 0.80 | 1.00 | 0.68 | ❌ |
| AISec2025 | 0.87 | 0.88 | 0.96 | 0.82 | ✅ |
| isporeu | 0.82 | 0.84 | 0.84 | 1.08 | ✅ |
| **Average** | **0.80** | **0.83** | **0.91** | **0.84** | **3/5** |

### Comparison

| Metric | pdfalto | pdfplumber | Delta |
|--------|---------|------------|-------|
| Pass rate | 3/5 (60%) | 4/5 (80%) | **+1 poster** |
| Avg word_capture | 0.804 | 0.832 | **+0.028** |
| Avg rouge_l | 0.830 | 0.816 | -0.014 |
| Avg number_capture | 0.905 | 0.902 | -0.003 |
| Avg field_proportion | 0.842 | 0.966 | **+0.124** |

**Key wins for pdfplumber:**
- 8228476 (Hebrew+English poster): flipped from ❌ to ✅ — w improved 0.73→0.86, f improved 0.68→1.00
- isporeu: rouge improved 0.84→0.91
- 4564017: word capture improved 0.73→0.90 (still fails on rouge by 0.01)

**Key regression:**
- 17268692: w dropped 0.88→0.77, r dropped 0.91→0.80 (still passes)

---

## Parameter Summary

**pdfalto: 30+ parameters across 11 stages**
**pdfplumber: 45+ parameters across 15 stages**

New stages added by pdfplumber:
- Phantom space filtering (§2) — handles a PDF artifact pdfalto didn't encounter
- Font annotation strategy (§3) — works around font subsetting in `extract_words`
- Recursive XY-cut reading order (§7, `xy_cut.py`) — the current reading-order engine; replaced the migration-era line-grouping (§5) and column-detection (§6) stages, which are now uncalled
- Layout zoning (§10) — hoists header/meta/footer out of the XY-cut body flow

Stages identical between extractors: §11–§15 (text normalization, Unicode cleanup, quality gate, uncaptured text recovery, JSON repair). These operate downstream of extraction and are extractor-agnostic.

---

## License

| | pdfalto | pdfplumber |
|---|---------|------------|
| Tool license | Apache 2.0 | MIT |
| Dependency license | Xpdf (GPLv2) — **incompatible** | pdfminer.six (MIT) |
| Distribution | Binary, platform-specific | Pure Python, pip install |
| GPU required | No | No |
