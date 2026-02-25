# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
