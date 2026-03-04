# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.1.0 (2026-03-04)


### Features

* add tests ([1e04dc0](https://github.com/fairdataihub/poster2json/commit/1e04dc0706b0efafbc24d3a6898b19232a05ad9b))
* regex identifier extraction and caption ID auto-generation ([a5a3518](https://github.com/fairdataihub/poster2json/commit/a5a3518852b52038c7bcbcc8ad2c811c43f5c741))


### Bug Fixes

* fix dependencies ([6c6fc67](https://github.com/fairdataihub/poster2json/commit/6c6fc67e1b9c55332fe48321388fcaf4b9643424))
* update markdownlint configuration and improve README.md content ([f06e74c](https://github.com/fairdataihub/poster2json/commit/f06e74cc83db1c92cae75561c2a5f25f7c5b5f05))
* update README.md by removing unnecessary brackets from URLs ([45e12d0](https://github.com/fairdataihub/poster2json/commit/45e12d0e54d2e046da18c85d115aa4aeea9d74a8))

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
