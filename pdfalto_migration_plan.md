# PDFAlto Migration Plan

poster2json is MIT-licensed. pdfalto is licensed under Apache 2.0 but statically links Xpdf (GPLv2), creating a license compatibility problem for distribution. We need to migrate to a fully MIT/Apache-compatible PDF text extraction tool.

## Candidates

### 1. pdfplumber (MIT)

**What it is:** Python wrapper around pdfminer.six. Pure Python, no binary dependencies. Extracts text with full positional metadata (bounding boxes per character, word, and line).

**License:** MIT — fully compatible.

**Pros:**
- Pure Python, pip-installable, no binary to ship
- Character-level bounding boxes (x0, y0, x1, y1) — more granular than pdfalto's ALTO XML blocks
- Word and line clustering built in (`extract_words()`, `extract_text()`)
- Table detection (`extract_tables()`) — could improve tableCaptions extraction
- Active maintenance, large user base
- Page dimensions directly available (`page.width`, `page.height`)
- No GPU required

**Cons:**
- No native reading order — we'd need to implement column detection and reading order ourselves
- No native font style metadata on text lines (bold/italic) — would need to inspect character-level `fontname` strings (e.g. `"TimesNewRoman-Bold"`) and parse style from the name
- No native header detection — our font-size heuristics would need to operate on raw character/word fontsize data
- Slower than pdfalto on large PDFs (pure Python vs. C++)
- No layout analysis model — purely geometric

**Migration effort:** MEDIUM-HIGH. The raw positional data is there, but we'd be rebuilding reading order, column detection, and font style parsing from scratch rather than getting them from ALTO XML structure.

### 2. Surya (GPL-3.0 — problematic, see below)

**What it is:** Deep learning OCR + layout analysis. Uses a FoundationPredictor backbone with separate detection, recognition, and layout heads. Provides reading order via `LayoutBox.position`.

**License:** GPL-3.0 — **NOT compatible with our MIT license for distribution.** Could be used as an optional dependency or external service, but cannot be bundled or required.

**We already tested it:** `json_schema/surya_smoke_test.py` evaluated Surya 0.17.1 on poster 4737132 (German, with screenshot noise).

**What we learned from the smoke test:**
- API: `DetectionPredictor`, `FoundationPredictor`, `RecognitionPredictor(foundation)`, `LayoutPredictor(foundation)`
- Text lines have `.polygon` (not `.bbox`), `.text`, `.confidence`
- Layout boxes have `.polygon`, `.label`, `.position` (reading order), `.confidence`
- Layout labels include `Picture`, `Figure`, `Text`, `Title`, `Section-header`, etc.
- `LayoutBox.position` gives reading order directly — no `OrderingPredictor` needed
- Layout filter successfully excluded screenshot/figure regions
- Requires CUDA GPU with sufficient VRAM (loads 4 model heads)

**Pros:**
- Native reading order via `LayoutBox.position` — direct replacement for pdfalto's `-readingOrder`
- Native layout labels (`Title`, `Section-header`) — could replace our font-based header detection entirely
- Handles scanned/image PDFs natively (it's an OCR model)
- Region-level text grouping built in
- Confidence scores per text line and layout region

**Cons:**
- **GPL-3.0 license** — cannot be a required dependency of MIT-licensed poster2json
- Requires CUDA GPU (~4-6GB VRAM for the model stack)
- Slower startup (model loading) vs pdfalto's instant binary
- API instability between versions (0.17.x changed from `.bbox` to `.polygon`, removed `OrderingPredictor`)
- Would compete for GPU memory with our Llama JSON model and Qwen vision model

**Migration effort:** MEDIUM for the extraction itself (Surya gives us more structure than pdfalto), but the license problem makes it a non-starter as a hard dependency.

---

## Recommendation

**Primary path: pdfplumber** — it's MIT, pure Python, and gives us the positional data we need. The extra work is rebuilding reading order and header detection, but we already have the algorithms in `_detect_column_boundaries()` and the header heuristics — they just need to operate on pdfplumber's coordinate system instead of ALTO XML.

**Optional acceleration: Surya as an opt-in backend** — if the user has Surya installed and a GPU available, use it for reading order and layout labels. But pdfplumber must be the default path that works without GPU or GPL dependencies.

---

## Migration Phases

### Phase 1: pdfplumber integration (parallel path)

Build `extract_text_with_pdfplumber()` alongside the existing pdfalto path. Do not remove pdfalto yet.

**1a. Raw text extraction**
- Use `page.extract_words()` to get words with bounding boxes (`x0`, `y0`, `x1`, `y1`, `text`, `fontname`, `size`)
- Group words into lines by vertical proximity (replace ALTO `<TextLine>`)
- Group lines into blocks by spatial proximity (replace ALTO `<TextBlock>`)

**1b. Reading order**
- Port `_detect_column_boundaries()` to operate on pdfplumber word coordinates
- Same parameters: 5% page-width gap threshold, max 6 boundaries, min 3 blocks per column
- Within each column, sort blocks top-to-bottom
- Across columns, process left-to-right (or use the existing boundary-based ordering)

**1c. Font style extraction**
- Parse `fontname` strings for bold/italic (e.g. `"Arial-BoldItalicMT"` → bold=True, italic=True)
- Extract `size` directly from word metadata
- Build equivalent of `_parse_text_styles()` return format so header detection works unchanged

**1d. Header detection**
- Same algorithm, same thresholds: median fontsize, 1.3x threshold, bold >= median, <= 120 chars, starts with letter, >= 2 alpha words, contact exclusion
- Should work with minimal changes since it operates on fontsize/bold/italic abstractions

**1e. Deduplication**
- Same line-level dedup: VPOS tolerance < 2 units, word overlap > 80%
- Coordinate system will differ (pdfplumber uses points, pdfalto uses ALTO units) — may need to recalibrate the VPOS tolerance

**1f. Validation**
- Run both pdfalto and pdfplumber paths on the full poster corpus
- Compare extracted text character-by-character
- Run through the full pipeline (LLM structuring + validation) and compare scores
- The 5-poster canary set is the fast iteration target

### Phase 2: Surya opt-in backend

**Only if needed** — if pdfplumber's reading order on complex multi-column posters isn't good enough.

- Gate behind `try: import surya` with pdfplumber fallback
- Use `LayoutBox.position` for reading order
- Use `LayoutBox.label` for header detection (bypassing font heuristics)
- Document GPU requirements
- Do NOT make it a required dependency (GPL)

### Phase 3: pdfalto removal

- Remove pdfalto binary from `poster2json/executables/`
- Remove `PDFALTO_PATH` discovery code
- Remove `extract_text_with_pdfalto()`
- Remove `_parse_alto_xml()`, `_parse_text_styles()`
- Update `_detect_column_boundaries()` if it was modified for pdfplumber coordinates
- Update docs, README, installation instructions
- Remove any CI steps that install pdfalto
- Bump semver (minor version at minimum)

---

## Parameter Migration Checklist

Every parameter from `pdfalto_poster_params.md` must be accounted for. Check off each one during migration:

- [ ] `-noImage` equivalent (pdfplumber: just don't extract images — default behavior)
- [ ] `-readingOrder` equivalent (pdfplumber: manual column detection + sort)
- [ ] 60-second timeout (pdfplumber: pure Python, may need per-page timeout)
- [ ] Line dedup VPOS tolerance < 2 (recalibrate for pdfplumber coordinate units)
- [ ] Line dedup word overlap > 80%
- [ ] Column gap threshold: 5% page width
- [ ] Max column boundaries: 6
- [ ] Min blocks per column: 3
- [ ] Font style parsing (bold/italic from fontname strings)
- [ ] Median fontsize calculation
- [ ] Header max length: 120 chars
- [ ] Header starts-with-letter filter
- [ ] Header min 2 alpha words
- [ ] Header contact exclusion (email/phone/URL)
- [ ] Header bold threshold: >= median fontsize
- [ ] Header large-font threshold: > 1.3x median
- [ ] Block line joining (single space)
- [ ] No block-level dedup (keep this decision)
- [ ] No gap markers (keep this decision)
- [ ] No vpos sort (replaced by column-aware reading order)
- [ ] Pre-model NFKD normalization
- [ ] Smart quote replacement
- [ ] Min output threshold: 500 chars for fallback
- [ ] Uncaptured text recovery: < 50% word overlap
- [ ] Uncaptured text min length: > 10 chars
- [ ] JSON repair: unit-slash quotes, scare-quotes

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| pdfplumber reading order worse than pdfalto on complex posters | HIGH | Phase 2 Surya fallback; extensive canary testing |
| Font style parsing from fontname strings unreliable | MEDIUM | Build a lookup of common font name patterns; test against corpus |
| Coordinate system differences break dedup thresholds | MEDIUM | Recalibrate VPOS tolerance against the canary set |
| pdfplumber slower on large PDFs | LOW | Most posters are single-page; timeout handles edge cases |
| Surya API changes in future versions | LOW | Pin version; gate behind try/import |
| Regression in validation scores during migration | HIGH | Run full corpus validation before and after; do not merge until parity |
