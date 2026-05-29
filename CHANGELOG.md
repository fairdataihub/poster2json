# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.1.0 (2026-05-29)


### Features

* :sparkles: trigger redeploy upon succesful python publish ([2c30ddd](https://github.com/fairdataihub/poster2json/commit/2c30ddde2fc74f47b7bbec49976d91c51526f384))
* add json-repair as last-resort JSON parse fallback (0.5.8) ([54b542f](https://github.com/fairdataihub/poster2json/commit/54b542fe59a6423a0a680f330cfffd2cc6ac665f))
* add pdfplumber text extraction as pdfalto replacement ([5b29572](https://github.com/fairdataihub/poster2json/commit/5b29572be69410b5cbc3e7bc9dbe49818ce2b2e9))
* add sync_schema.py for canonical schema fetching ([8933b23](https://github.com/fairdataihub/poster2json/commit/8933b238e644731d445954c02cdde5932e27679d))
* add tests ([1e04dc0](https://github.com/fairdataihub/poster2json/commit/1e04dc0706b0efafbc24d3a6898b19232a05ad9b))
* authenticated ORCID API via OAuth client_credentials (0.5.10) ([d61a268](https://github.com/fairdataihub/poster2json/commit/d61a26811d17960e1e5907c898690b91fb4b5475))
* bidi embedding markers and font-size header detection (v0.6.5) ([193d663](https://github.com/fairdataihub/poster2json/commit/193d663332f3616db488c2ac9ac1a02245d05594))
* default JSON model to 4bit and document custom --model flag ([f730bfc](https://github.com/fairdataihub/poster2json/commit/f730bfc3e798e8d809b5c88591175b09b506d257))
* enhanced license normalization + junk filtering ([c169cad](https://github.com/fairdataihub/poster2json/commit/c169cad86aba91bdcfc3809cbac4461ae5181dcf))
* EOS brace-balance processor and adaptive x_tolerance ([84bbd2a](https://github.com/fairdataihub/poster2json/commit/84bbd2a2bb1abcef9ea441b8066d52b34643d96e))
* extract PDF link annotations into identifiers and relatedIdentifiers ([06863d0](https://github.com/fairdataihub/poster2json/commit/06863d0012ff37f2a1f2db01f292ef6158b3640c))
* ground researchField on the OpenAlex 4 domains ([bee8a41](https://github.com/fairdataihub/poster2json/commit/bee8a4126836cffa1491dc24710aa51b350ef7fe))
* heuristic language detection on raw poster text ([6ba04cb](https://github.com/fairdataihub/poster2json/commit/6ba04cb3dd42ae6217168f6e6f21251595bebbe3))
* improve pdfplumber column detection and reading order ([c9afd35](https://github.com/fairdataihub/poster2json/commit/c9afd35a19444fd45e117285ef9d29050dbeb9e3))
* improve pdfplumber section segmentation (v0.7.1) ([5422d9c](https://github.com/fairdataihub/poster2json/commit/5422d9c9d8796a6e631c8f2c2d0a77bde3f05c62))
* Phase 1 — DOI / funder / award normalization (0.5.0) ([e4c67bc](https://github.com/fairdataihub/poster2json/commit/e4c67bc0ab2fb7c1957eea5433b047b75899e1e8))
* Phase 2 — ORCID enrichment via public API (0.5.1) ([04c9350](https://github.com/fairdataihub/poster2json/commit/04c9350a40181f487cc2c8a5eebf0ef1242bd18e))
* Phase 3 — publisher-suspect _validation warning (0.5.2) ([34382a9](https://github.com/fairdataihub/poster2json/commit/34382a9935f7e958565caa67d2872b00f2ecbfab))
* regex identifier extraction and caption ID auto-generation ([a5a3518](https://github.com/fairdataihub/poster2json/commit/a5a3518852b52038c7bcbcc8ad2c811c43f5c741))
* reject oversized inputs before GPU inference (MAX_INPUT_TOKENS) ([157bcc9](https://github.com/fairdataihub/poster2json/commit/157bcc91a56c4b08da67ac98232df81e9b49867c))
* remove pdfalto code, finalize pdfplumber pipeline (v0.8.0) ([edd7828](https://github.com/fairdataihub/poster2json/commit/edd7828655b49291d780774236aa429a244b4785))
* replace column-major sort with recursive XY-cut reading order ([8080621](https://github.com/fairdataihub/poster2json/commit/80806216c8b8654eb9ce3b5005ea7fc0e10cdb4b))
* request 3-4 sentence poster description in extraction prompts ([4092f4a](https://github.com/fairdataihub/poster2json/commit/4092f4a13d8bfccd3cdf588d07772c46100cdb23))
* request 3-4 sentence poster description in extraction prompts ([843f6c0](https://github.com/fairdataihub/poster2json/commit/843f6c0a2a19d8d3aadcc6316963e7edf9698c48))
* SPDX license, subject, and ROR normalization on output ([096d281](https://github.com/fairdataihub/poster2json/commit/096d2811fb8c266792cf0e755b6c2787c707935e))
* split run-on blocks at inline section labels (v0.7.2) ([f04b8a7](https://github.com/fairdataihub/poster2json/commit/f04b8a7e25aeda11c82129ec167166bfb3976089))
* update poster_schema.json to v0.2 (DataCite 4.7) ([11af839](https://github.com/fairdataihub/poster2json/commit/11af839544166ff3d815606bc74e3352f8fbe8a4))
* vision OCR fallback for image-only PDFs ([1e3e3f6](https://github.com/fairdataihub/poster2json/commit/1e3e3f67e2920ca56139362827ba9ce611154bce))


### Bug Fixes

* add min_new_tokens to prevent early EOS + repair partial JSON literals ([e10d8dc](https://github.com/fairdataihub/poster2json/commit/e10d8dc4acba49781881f19a8a017f082c605eed))
* anti-hallucination safety nets + prompt grounding rule (0.5.4) ([5dbca4d](https://github.com/fairdataihub/poster2json/commit/5dbca4dfc0f1e61a81246c9080550601f4e7d98f))
* build sections from raw text when LLM truncates before content ([e0810e7](https://github.com/fairdataihub/poster2json/commit/e0810e716bc1e795af27e22c0315a4b79af1386d))
* dedup section fallback against LLM metadata to avoid duplicates ([862c535](https://github.com/fairdataihub/poster2json/commit/862c535923176f95a0f1a14af93e9693dd44d724))
* **deps:** bump nltk 3.9.2 -&gt; 3.9.4 to clear CVE-2025-14009 (critical) ([610f73c](https://github.com/fairdataihub/poster2json/commit/610f73c87a33a614846017ba420acb409e807bbf))
* **deps:** bump pillow 12.1.0 -&gt; 12.2.0 and black 22.12.0 -> 26.3.1 ([943d07e](https://github.com/fairdataihub/poster2json/commit/943d07e1895fe22c178e72602811a629b09f4bd7))
* derive formats from file extension instead of LLM extraction ([ce3d707](https://github.com/fairdataihub/poster2json/commit/ce3d70781776e5b32954b931eca2130d98070803))
* fix dependencies ([6c6fc67](https://github.com/fairdataihub/poster2json/commit/6c6fc67e1b9c55332fe48321388fcaf4b9643424))
* funder identifiers use URL format everywhere, update tests ([b4cf8ca](https://github.com/fairdataihub/poster2json/commit/b4cf8ca9b7b6b6c2a7275a50a3cf4809f8a0fdaf))
* license canonical display name + version field extraction (0.5.9) ([84d4b63](https://github.com/fairdataihub/poster2json/commit/84d4b639c137b02d1547d36efd9446ac0bd15ce0))
* normalize identifiers to URL format for Zenodo validation ([bd34144](https://github.com/fairdataihub/poster2json/commit/bd34144822116572915fb9c9e8a71c4f701e1a16))
* prevent XY-cut vertical splits on single-line blocks ([ede75ff](https://github.com/fairdataihub/poster2json/commit/ede75ff8280d166fadc6c4f09c276e24206393ab))
* Prompt updates for title casing and placeholder hallucinations (v0.1.9) ([53b39e6](https://github.com/fairdataihub/poster2json/commit/53b39e64e504a259d671ed02ac4827524fcdcc0f))
* PyMuPDF fallback when pdfalto text causes JSON parse failure (0.5.5) ([3100b63](https://github.com/fairdataihub/poster2json/commit/3100b63a133bfbed6eeeffc26121035fd061fc61))
* reduce prompt prohibition language to recover LLM output length ([a9f40bf](https://github.com/fairdataihub/poster2json/commit/a9f40bf713d88801cf7145ff7199d37d92b5d0fc))
* remove concrete example values from prompts to prevent echoing (0.5.6) ([0254d9c](https://github.com/fairdataihub/poster2json/commit/0254d9c73de8521e93a76f49784cb506711fd69b))
* Revert ALTO XML column reordering that caused validation regression (v0.1.12) ([5795520](https://github.com/fairdataihub/poster2json/commit/5795520c83ec9e411812b004343f9f61aa91bdfb))
* rewrite _repair_unescaped_quotes as character-walking JSON repair ([aff3980](https://github.com/fairdataihub/poster2json/commit/aff398058c158612a1ae481bdfad88d5ccc1b59d))
* ROR rate limit 6 req/s, retry with backoff, 25-failure circuit breaker ([005776a](https://github.com/fairdataihub/poster2json/commit/005776a9c0f9c3d64601345d83c9b4dd76406d32))
* Smart title-case for ALL-CAPS poster titles (v0.1.9) ([97f3c4d](https://github.com/fairdataihub/poster2json/commit/97f3c4d8e3c38a02bf30afd70b402e506191ab42))
* stop conference field hallucination at the prompt level ([33289f0](https://github.com/fairdataihub/poster2json/commit/33289f0a0b4a40d73022b4a0d811081a6d591ebb))
* stop hallucinating publicationYear in extraction prompts ([6ab31af](https://github.com/fairdataihub/poster2json/commit/6ab31af33f5d9444bc2b528e8eead4872435d5a1))
* stop hardcoding descriptionType to Other, default to Abstract ([74536e8](https://github.com/fairdataihub/poster2json/commit/74536e8d6a67fdd98a3830901c9b649e285cfb75))
* Strip empty-string conference metadata values (v0.1.11) ([22357dc](https://github.com/fairdataihub/poster2json/commit/22357dc57dc7ac082234959ad8540e633411b4f8))
* strip mailto: links from PDF link annotations ([56b9020](https://github.com/fairdataihub/poster2json/commit/56b9020e82c1bb33280859f591ba36f8fb75c128))
* Strip prompt-placeholder hallucinations from conference metadata ([1a41d29](https://github.com/fairdataihub/poster2json/commit/1a41d2920bbc507cf366cb2f16830d48d533998a))
* suppress invalid escape sequence warning in repair function ([a48c493](https://github.com/fairdataihub/poster2json/commit/a48c493a9790b02d74bed27cf18493529872849c))
* tag auto-generated descriptions as Other instead of Abstract ([3945d81](https://github.com/fairdataihub/poster2json/commit/3945d810acea66a64f693d0ba7e446b35c845391))
* unload JSON model before vision load on image posters ([b85c08c](https://github.com/fairdataihub/poster2json/commit/b85c08c9e4ae0def7122f5c39e9762013917b9d5))
* update code and docs for poster_schema v0.2 (DataCite 4.7) ([01cc762](https://github.com/fairdataihub/poster2json/commit/01cc762474551be8c0fe487b8955b668cf6c2397))
* update markdownlint configuration and improve README.md content ([f06e74c](https://github.com/fairdataihub/poster2json/commit/f06e74cc83db1c92cae75561c2a5f25f7c5b5f05))
* update README.md by removing unnecessary brackets from URLs ([45e12d0](https://github.com/fairdataihub/poster2json/commit/45e12d0e54d2e046da18c85d115aa4aeea9d74a8))
* use MIME types for formats per DataCite schema 4.7 ([e3f82ae](https://github.com/fairdataihub/poster2json/commit/e3f82aefa149955838bac370b36523d846af2fc0))


### Reverts

* remove min_new_tokens (model ignores it for multi-EOS configs) ([f2fcbbc](https://github.com/fairdataihub/poster2json/commit/f2fcbbcf4f8c71d40ddb8238abc6c349abad1136))


### Documentation

* add AI-generated image attribution hover to logo ([077617b](https://github.com/fairdataihub/poster2json/commit/077617b8b7dad682e2a9c708e553e1d1be7ecb83))
* add funding section, version to citation, remove acknowledgements ([8223b35](https://github.com/fairdataihub/poster2json/commit/8223b354532662dbaf02d1f5d4ddc3570a29471b))
* add normalization and enrichment pipeline to architecture ([4e305d4](https://github.com/fairdataihub/poster2json/commit/4e305d49f017d344ad245bdbb305964bba383040))
* correct model description and surface 0.4.x features in README ([80827e6](https://github.com/fairdataihub/poster2json/commit/80827e6daea664f2a58a35451cdf361d92f35f9a))
* pdfalto parameter inventory and migration plan ([f68dd7c](https://github.com/fairdataihub/poster2json/commit/f68dd7c3fa59589c62c5679901fbce6f4f6de3ca))

## [0.8.0] - 2026-05-28

Migrate PDF text extraction from pdfalto to pdfplumber, removing the last GPL-licensed
dependency. Consolidates the 0.6.x–0.7.x migration line into one release.

### Changed

- **pdfplumber is now the default (and only) PDF text extractor.** PDF posters are extracted with `pdfplumber` (MIT, pure Python) instead of the `pdfalto` binary (Xpdf / GPLv2). PyMuPDF remains the low-text fallback. This removes the project's only GPL-licensed dependency and the platform-specific binary requirement; no binary install, no subprocess, no ALTO XML.
- **Minimum-text quality gate** in `get_raw_text` lowered to `MIN_PDF_TEXT_CHARS = 200` (was a shared `>500` gate across two extractors). With a single primary extractor, output below the threshold falls back to PyMuPDF.

### Added

- **Recursive XY-cut reading-order engine** (`poster2json/xy_cut.py`): a port of xpdf's largest-gap XY-cut tree that reconstructs multi-column reading order directly from `page.chars`. Replaces the migration-era flow-ordering + column-assignment pipeline, and handles spanning titles/footnotes/footers that the old column-major sort could not interleave (`_promote_spanning_leaves`, `_merge_bottom_region`).
- **Inline section/caption splitter**: figure/table captions and bare section-keyword headers in the extracted text are promoted to `## ` headers so the LLM isolates them as distinct sections.
- `pdfplumber >=0.10.0` dependency.

### Removed

- All pdfalto code: `extract_text_with_pdfalto()`, `_parse_alto_xml()`, `_parse_text_styles()`, the `PDFALTO_PATH` binary lookup, and the `subprocess`-based invocation. The `pdfalto` (for PDF processing) line in CLI `--version`/info output is gone.

### Documentation

- `README.md`, `docs/index.md`, `docs/architecture.md`, `docs/evaluation.md` updated for the pdfplumber pipeline; `crosswalk.md` annotated for migration completion and the XY-cut rewrite; new `llama_generation_settings.md` documenting the JSON-model generation knobs.
- Validation: **19/20 (95%)** on the 20-poster annotated set (word 0.92 / ROUGE-L 0.85 / numbers 0.97 / fields 0.88). The lone failure is a dense table/flowchart poster whose reference annotation splits one visual region into many fine-grained sections.

## [0.5.9] - 2026-05-08

License display name normalization + version field extraction.

### Fixed

- **License canonical display name**: `normalize_rights_entry` now always sets `rights` to the full canonical name (e.g. "Creative Commons Attribution 4.0 International") when an SPDX match is found. Previously preserved the raw LLM output (e.g. "cc-by-4.0"), causing inconsistent display between manual and auto-registered posters.

### Added

- **Version field extraction**: both `EXTRACTION_PROMPT` and `FALLBACK_PROMPT` now include `version` as a required field. Extracts version strings (e.g. "v1.0", "Version 2") when explicitly printed on the poster; defaults to null otherwise.

## [0.5.8] - 2026-05-06

Add json-repair as last-resort JSON parse fallback.

### Added

- **json-repair fallback**: after all hand-rolled repair passes fail, `_robust_json_parse` now tries the `json-repair` library (MIT, zero-dep, LLM-aware) as a final attempt before returning an error. Our own repair functions run first and are unchanged.

### Dependencies

- Added `json-repair >=0.30.0` (~47kB pure Python, zero transitive deps).

## [0.5.7] - 2026-05-06

Robust JSON quote repair + version bump for PyPI re-publish.

### Fixed

- **Character-walking quote repair**: `_repair_unescaped_quotes` rewritten from regex to a character-by-character JSON walker that correctly handles unescaped quotes inside string values (code snippets, citations, nested speech). Fixes the class of JSON parse failures where pdfalto text contained special characters the LLM failed to escape.

## [0.5.6] - 2026-05-06

Anti-example-echoing: remove concrete values from prompts and add conference grounding check.

### Fixed

- **Prompt de-contamination**: replaced all concrete example values in EXTRACTION_PROMPT (publisher `"Zenodo"`, conference `"US-RSE'25"`, caption `"Figure 1: Experimental setup"`) with type-annotated placeholders. The model was echoing these examples as real data for unrelated posters.
- **Conference grounding check**: `_postprocess_json` now verifies that any extracted `conferenceName` actually appears in the raw poster text. If the name is not found in the source text, the entire conference object is nullified. This catches hallucinated conference names that survive the placeholder filter.
- **Schema example cleanup**: `imageCaptions` in the JSON template changed from a populated example to `[]`, matching `tableCaptions`.

## [0.5.5] - 2026-05-06

PyMuPDF fallback when pdfalto text causes JSON parse failures.

### Fixed

- **PyMuPDF fallback on JSON parse failure**: when `extract_json_with_retry` fails with pdfalto-extracted text, `extract_poster` now retries the full extraction pipeline using PyMuPDF text before giving up. Some posters produce pdfalto text that consistently causes the LLM to emit unparseable JSON (e.g. 5128504.pdf), while PyMuPDF text for the same poster parses cleanly. The fallback is transparent — no API or CLI changes.

## [0.5.4] - 2026-05-05

Anti-hallucination hardening (conference/caption/publisher placeholders + prompt improvements).

### Fixed

- **Conference placeholder safety net**: `_postprocess_json` now strips known placeholder values ("Name of Conference", "City, Country", etc.) from `conferenceName`, `conferenceLocation`, and `conferenceUrl`. Conference objects with no remaining meaningful fields collapse to `null`.
- **Bogus caption filter**: `imageCaptions` and `tableCaptions` entries whose caption text matches a placeholder pattern (e.g. "Table not found in the poster text") are removed.
- **Publisher placeholder stripping**: Publisher objects whose name matches template echoes (e.g. "Conference Organizer or Institution Name") are nullified.
- **ROR trailing-country retry**: affiliations like "Universidad Politecnica de Madrid, Spain" now retry without the ", Spain" suffix when the full string gets no ROR match, improving hit rate for poster-style affiliations.

### Changed

- **Extraction prompt hardened**: added Rule 0 "GROUNDING" (every value must come from poster text or be null), strengthened caption/conference/publisher instructions with positive and negative examples, removed placeholder strings from the schema example template (publisher is now `null` in the example, captions use `[]`), added rule 6/7 to fallback prompt.

## [0.5.3] - 2026-05-04

Tag auto-generated descriptions as "Other" instead of "Abstract" so users can provide
their own formal abstract separately.

### Changed

- Extraction prompt now uses `descriptionType: "Other"` for machine-generated poster
  summaries. Previously hardcoded as "Abstract", which misrepresented auto-extracted
  content as user-provided abstracts. The frontend will let users supply their own
  abstract (tagged "Abstract") and optionally keep the generated summary as "Other".

## [0.5.2] - 2026-05-01

Phase 3 of the field-normalization audit (publisher-suspect detection).

### Added

- **Publisher-suspect warning**: after ROR enrichment, if the publisher's `publisherIdentifier` matches any creator or contributor `affiliationIdentifier`, a `_validation` warning is emitted (`field: "publisher"`, `level: "warning"`). This flags the common case where a poster author listed their university as the publisher instead of the repository/platform (e.g. Zenodo, figshare). No data is changed — the dashboard can use the warning to suppress these entries from "Top Publishers" rollups.

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
