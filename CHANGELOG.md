# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
