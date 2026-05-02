# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.1] - 2026-05-01

Phase 2 of the field-normalization audit (ORCID).

### Added

- **ORCID enrichment via public API** (`poster2json/orcid.py`): always-on (`POSTER2JSON_ORCID=0` to opt out), disk-cached at `~/.cache/poster2json/orcid.json`, rate-limited to 2 req/s, 1500ms timeout — same shape as `ror.py` and `funders.py`. Searches the ORCID expanded-search endpoint by `given-names` + `family-name` + `affiliation-org-name`. Only attaches when exactly one result matches (single high-confidence hit) and the returned name passes accent-insensitive comparison. Requires affiliation as a disambiguator — name-only searches are skipped. Runs after regex-based ORCID extraction so creators who already have an ORCID from the poster text are not re-queried.

## [0.5.0] - 2026-05-01

Phase 1 of the field-normalization audit (DOI / funder / award).

### Added

- **DOI canonical form** (`identifiers.canonicalize_doi`): strips `https://doi.org/`, `dx.doi.org/`, and `doi:` prefixes from DOIs. Applied to `identifiers[].identifier`, `fundingReferences[].funderIdentifier` (Crossref Funder DOIs), and `relatedIdentifiers[].relatedIdentifier`. Suffix case is preserved.
- **Funder enrichment via ROR** (`poster2json/funders.py`): always-on (`POSTER2JSON_FUNDER=0` to opt out), disk-cached, rate-limited, 1500ms timeout — same shape as `ror.py`. Stricter accept criteria than affiliations: requires the matched org's `types` to include `"funder"`. When matched, populates `funderIdentifier` (Crossref Funder DOI when available, else ROR URL), `funderIdentifierType` (`"Crossref Funder ID"` or `"ROR"`), and `schemeUri`. Replaces messy input names with ROR's canonical display name. Bare acronyms like "NIH" that hit a non-funder sub-institute are correctly skipped.
- **Award number cleanup** (`normalize.normalize_award_number`): NFKC, whitespace-collapse, surrounding-punctuation strip, uppercase. No fuzzy matching — same integer-exact rule as SPDX. Drops empty values to None.

## [0.4.4] - 2026-04-29

### Fixed

- OOM on image posters when the API has the JSON model warm-loaded. `extract_poster()` now unloads the JSON model before reading an image (Qwen2-VL-7B at bf16 needs ~15GB; on a 24GB card with JSON resident ~9GB, vision load was OOMing by a few hundred MB). PDF posters are unaffected — they never load vision, so the JSON warm-load stays free.

## [0.4.3] - 2026-04-24

### Documented

- README pipeline overview now lists the lingua / ROR / SPDX features added in 0.4.0–0.4.2; expanded JSON output example with `language`, `researchField`, ROR-enriched affiliation, and SPDX-normalized rights; added a "Notes on auto-populated fields" section covering the 4 OpenAlex domains and the `POSTER2JSON_ROR=0` opt-out.
- Corrected docstrings, README, architecture.md, and CLI help that called the default model "fine-tuned" — `fairdataihub/Llama-3.1-8B-Poster-Extraction` is a verbatim mirror of Meta's `Llama-3.1-8B-Instruct`.
- Citation block bumped to current version.

(No code changes from 0.4.2; re-published because PyPI doesn't allow file-name reuse and 0.4.2 was already uploaded.)

## [0.4.2] - 2026-04-24

### Added

- Heuristic language detection on raw poster body text via `lingua-language-detector`. New `poster2json/language.py` module loads a 29-language detector lazily (Western European + East Asian + South/Southeast Asian + Middle Eastern + Slavic). Result is emitted as ISO 639-1 in the `language` field. Returns null below the minimum body-text threshold or when the detector can't separate the top two candidates by ≥10% (configured via `with_minimum_relative_distance(0.10)`).
- `_postprocess_json` always overwrites `language` with the heuristic's result (or null). Reason: the LLM has been observed to emit `language: "en"` for posters with English metadata fragments but Japanese/Spanish/etc. body content (the figshare poster at DOI 10.6084/m9.figshare.10116536.v1 is the canary case — now correctly tagged `ja`). Body-text heuristic is more reliable than the model.
- Hybrid threshold: 200 chars OR 50 non-ASCII codepoints. CJK/Arabic/Cyrillic encode much more info per codepoint than Latin scripts, so a 130-char Japanese poster passes the gate that a 130-char English poster wouldn't.

### Dependencies

- Added `lingua-language-detector >=2.1,<2.2` (~96MB wheel; lazy-init so no import-time cost). Pinned below 2.2 because 2.2.0 dropped Python 3.10/3.11 and we still target ^3.10.

## [0.4.1] - 2026-04-24

### Added

- `researchField` is now in both `EXTRACTION_PROMPT` and `FALLBACK_PROMPT` with explicit instruction: must be one of the four OpenAlex top-level domains ("Health Sciences", "Life Sciences", "Physical Sciences", "Social Sciences") or null. Previously the field wasn't mentioned in either prompt, so the model never had a chance to fill it.
- Post-process placeholder filter: `researchField` values matching the deny-list `{"", "Other", "Unknown", "N/A", "Research field", "Domain", "Field", "None"}` (case-insensitive) are coerced to None. Belt-and-suspenders against model drift and against legacy data flowing through the pipeline.

### Changed

- Bundled `poster2json/schemas/poster_schema.json` synced from canonical poster-json-schema repo (researchField examples + description updated to OpenAlex four-domain guidance).

## [0.4.0] - 2026-04-24

### Added

- **License normalization**: extracted `rightsList` entries are matched against an SPDX license table (CC family, MIT, Apache, BSD, GPL/LGPL, MPL, CC0). Tier 1 is exact match after lowercase + strip-to-alphanumeric; tier 2 is alpha-fuzzy with **integer-exact** (e.g. `CC-BIY-4.0` → `CC-BY-4.0` fixes the typo, but `CC-BY-4.1` is left alone — version numbers are never fuzzy-matched). Matches populate `rightsIdentifier`, `rightsIdentifierScheme="SPDX"`, `schemeUri`, and backfill `rightsUri`. Unknown licenses pass through untouched.
- **Subject cleanup**: `subjects` entries are NFKC-normalized, whitespace-collapsed, and deduped case-insensitively (first occurrence's casing wins).
- **ROR enrichment** (always-on, opt out with `POSTER2JSON_ROR=0`): `creators[].affiliation`, `contributors[].affiliation`, and `publisher` are looked up against ROR's `/organizations?affiliation=` matcher. On a confident match (EXACT/PHRASE outright, FUZZY/COMMON-TERMS only at score ≥ 0.95), the original string is replaced with ROR's canonical display name and an identifier is attached. Disk-cached at `~/.cache/poster2json/ror.json`; in-memory dedupe per run; rate-limited to 2 req/sec; 1500ms timeout. ROR auto-disables for the rest of a run after the first network failure.

### Changed

- `_clean_unicode_artifacts` (output path) now applies NFKC composition. Spanish/German/French/Japanese characters in emitted JSON now use single-codepoint composed form (e.g. `é` as one codepoint, not `e + ́`). NFKD remains on the pre-LLM input path because decomposition cuts token count on superscripts.
- `utils.normalize_text` switched from NFKD to NFKC to match the output convention.

## [0.3.2] - 2026-04-24

### Security

- Bump `pillow` 12.1.0 → 12.2.0. Clears CVE-2026-40192 (high, FITS GZIP decompression bomb) and CVE-2026-25990 (high, PSD out-of-bounds write).
- Bump `black` (dev) 22.12.0 → 26.3.1; relaxed constraint from `^22.1` to `^26.3`. Clears CVE-2026-32274 (high, arbitrary file write via cache filename).

## [0.3.1] - 2026-04-24

### Security

- Bump transitive `nltk` dep (via `rouge-score`) from 3.9.2 → 3.9.4. Clears CVE-2025-14009 (critical Zip Slip, GHSA-7p94-766c-hgjp) and CVE-2026-33230 (medium XSS).

## [0.3.0] - 2026-04-24

### Changed

- Default quantization for the JSON-structuring Llama model is now **4bit** (NF4) across both PDF and image/OCR pipelines. Previously auto-selected 8bit when <16GB free and fp16 otherwise, and forced bf16 on the OCR path. Use `--quantization 8bit` or `--quantization fp16` to opt into higher precision.
- VRAM floor drops to ~8GB for PDF posters at the 4bit default (image/OCR posters still need ~16GB because of the bf16 Qwen2-VL vision model).

### Documented

- `--model` flag: clarified in help text and README that any HuggingFace instruct repo id is accepted (e.g. `google/gemma-2-9b-it`, `Qwen/Qwen2.5-7B-Instruct`), not just the default fine-tuned Llama.

### Removed

- `force_full_precision` parameter on `load_json_model` (dead after the 4bit default — quality on OCR output at 4bit has held up in the canary set; revisit if regressions appear).

## [0.2.3] - 2026-04-06

### Fixed

- Prompt: replace conference placeholder examples with null to prevent LLM echoing template values as real data
- Prompt: add explicit anti-hallucination instructions for conference fields (never invent names, locations, dates, URLs)
- Remove post-process placeholder stripping patch (root cause fixed in prompt)

## [0.1.12] - 2026-03-19

### Fixed

- ALTO XML parser: preserve pdfalto reading order instead of sorting by vpos (fixes validation regression from 95% to ~50%)
- ALTO XML parser: remove block-level dedup that was dropping legitimate similar blocks
- ALTO XML parser: join TextLines into single line per block to avoid splitting sentences
- ALTO XML parser: remove gap-line insertion that changed LLM content segmentation
- ALTO XML parser: tighten header detection — require letter-start, ≥2 alpha words, ≤120 chars

## [0.1.11] - 2026-03-11

### Fixed

- Post-process: strip empty-string values from conference metadata fields
- Prompt: instruct model to convert ALL-CAPS titles to Title Case preserving acronyms (e.g. SARS-CoV-2)
- Prompt: instruct model to omit conference/publisher when not found, rather than hallucinating placeholders
- Post-process: strip prompt-placeholder hallucinations ("Name of Conference", "City, Country", "YYYY-MM-DD", etc.) from conference metadata and publisher fields

## [0.1.8] - 2026-03-11 [YANKED]

### Note

- v0.1.8 placeholder post-processing and v0.1.9 title-case changes consolidated into v0.1.10

### Fixed

- Post-process: strip prompt-placeholder hallucinations ("Name of Conference", "City, Country", "YYYY-MM-DD", etc.) from conference metadata and publisher fields

## [0.1.7] - 2026-02-28

### Fixed

- Post-process: omit `sectionTitle` when empty instead of writing `""` (violates schema `minLength: 1`)
- Post-process: strip "Unknown" placeholder values from conference metadata and optional string fields

## [0.1.6] - 2026-02-26

### Changed

- ALTO XML reading order: replace column-major sort with row-band grouping via vertical-overlap merging
- Split row-bands at full-width block boundaries (>60% page width) to preserve section ordering in mixed layouts
- Header detection: limit to blocks ≤150 chars and ≤3 lines to prevent bold body paragraphs from being marked as headers
- Skip contact-like text (emails, URLs, phone numbers) from header detection

## [0.1.5] - 2026-02-25

### Fixed

- Pre-model Unicode normalization of raw OCR text (NFKD decomposition, smart/curly quote replacement) to prevent unescaped double-quotes inside JSON string values
- General unescaped inline scare-quote repair in `_repair_unescaped_quotes()` as a JSON parse safety net

## [0.1.4] - 2026-02-24

### Added

- Regex-based identifier extraction from raw poster text (DOI, ORCID, arXiv, ROR, Crossref Funder ID)
- Automatic scheme/schemeURI inference for identifiers
- Caption ID auto-generation (`fig1`, `fig2`, `table1`, etc.)
- New `identifiers.py` module with `enrich_json_with_identifiers()`

## [0.1.3] - 2026-02-20

### Fixed

- CLI test fixtures updated for required conference fields
- Schema sync: publisher mandatory, conferenceYear required

## [0.1.2] - 2026-02-14

### Changed

- Updated model ID from jimnoneill to fairdataihub HuggingFace org
- Synced prompts and schema with poster_schema v0.1
- Updated field proportion threshold to 0.5-2.0

## [0.1.1] - 2026-02-04

### Added

- Add documentation to the package.
- Add tests to the package.
- Update the logo for the package.

## [0.1.0] - 2026-02-04

### Added

- Initial poster2json package.
