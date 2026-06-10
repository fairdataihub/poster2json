# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.9.11] - 2026-06-09

### Fixed

- **Superscript affiliation correction generalized to real-world notations.** 0.9.10's corrector only handled semicolon-delimited numbered lists with plain-digit markers. It now also handles numbered lists delimited by the next number (no semicolon), unicode superscript digit markers, multi-line banners (authors and affiliations on separate lines), marker ranges like "1-3", and role glyphs (asterisk, dagger, envelope, plus) which are ignored. Real affiliations are told apart from author-name false positives by a multilingual institution-keyword filter, the marker search is anchored on each model-extracted author name, and the author/affiliation boundary is split so a trailing author's marker is not mistaken for the first affiliation number. Validated on the 2025 corpus: fired on 576 of 4837 multi-author posters with zero anomalies (no author left empty or over-assigned), and verified semantically correct on real banners with up to 17 authors and complex multi-marker assignments.

## [0.9.10] - 2026-06-09

### Fixed

- **Authors no longer over-assigned every affiliation.** On posters whose banner has a numbered affiliation list and whose authors carry superscript markers (e.g. "Limaye 1,3"), the fine-tuned model frequently assigned every institution to authors — most often the lead author absorbing all of them — even when the raw text was unambiguous. A new strictly-gated postprocess step (`_correct_affiliations_from_superscripts`) parses the numbered affiliation list and each author's markers from the raw text and reassigns each author exactly their own numbered affiliations (which then resolve through ROR as usual). It is a no-op unless a clean sequential `1..N` list is found, every author has a marker, and every marker resolves to a parsed affiliation — so posters without numbered affiliations are left untouched, and a `_validation` info note is emitted when it fires. On a real 7-author poster this corrected the lead author from 5 affiliations (two of them other authors' institutions) down to his correct 2.

## [0.9.9] - 2026-06-08

### Changed

- **Affiliations sharing a ROR organization now preserve distinct sub-unit names instead of collapsing.** Previously ROR enrichment replaced every affiliation string with the org's canonical display name, so two departments of one university — e.g. `"Hamilton Glaucoma Center, … University of California San Diego"` and `"Division of Ophthalmology Informatics …, University of California San Diego"` — both became `"University of California San Diego"` and were then de-duplicated to a single entry, discarding the department detail. Affiliation resolution now keeps each **distinct** source name when several map to the same ROR id, attaching the shared identifier to each. A **single** source name still uses ROR's canonical display name, and true duplicates (the same name twice) still collapse to one. Unresolved affiliations are de-duplicated by normalized name. Internally the separate enrich + dedupe passes are replaced by one `resolve_person_affiliations` step (which subsumes the 0.9.7 dedupe).

## [0.9.8] - 2026-06-08

### Changed

- **Affiliation ROR identifiers are now resolved exclusively from the name string, never trusted from the model.** The prompt does not ask the model for an `affiliationIdentifier`, so when one appeared it had been copied off the poster (printed `ror.org/...` text or PDF link annotations) — and the pipeline trusted it: `ror.py` skipped its lookup whenever an identifier was already present, and `identifiers.py` blessed the scraped value with scheme/`schemeUri`. This bypassed the intended string→ROR-API resolution. A new strip step (`strip_extracted_affiliation_ids`) now drops any model-supplied `affiliationIdentifier` / `affiliationIdentifierScheme` / `schemeUri` before enrichment, so every affiliation is resolved by name through the ROR API. This mirrors the existing handling of `creators[].nameIdentifiers[]` (model scheme fields dropped) and of `identifiers[]` / `relatedIdentifiers[]` (handled upstream). Trade-off: an affiliation the ROR matcher can't confidently resolve keeps only its name and no identifier, even if the poster printed a correct one.

## [0.9.7] - 2026-06-08

### Fixed

- **`creators[].affiliation` / `contributors[].affiliation` always emitted as the schema's array form.** The model occasionally returned a bare string (e.g. `"affiliation": "Oregon Health & Science University, ..."`) or a single object, which violated the schema (`affiliation` must be an array) and skipped ROR enrichment entirely. A new coercion step now runs before enrichment: a bare string becomes `[string]`, a single object becomes `[object]`, blank/`null`/junk values drop the (optional) key, and blank items inside a list are filtered out. Because the value is now a proper list, string affiliations also become eligible for ROR resolution again.
- **Duplicate affiliations are collapsed.** The same organization listed twice on a creator (a recurring model artifact, e.g. the identical ROR object repeated) is now deduplicated. Entries are keyed on their ROR identifier when present, else on their normalized name; when duplicates collide the entry carrying an identifier is kept, and a bare-name entry is dropped when an identified entry already covers the same organization. Runs unconditionally, after enrichment, so it also cleans posters whose affiliations were already fully resolved.

## [0.9.6] - 2026-06-08

### Changed

- **`publisher` is now an explicit null placeholder instead of being dropped.** poster2json never guesses a publisher (it is filled downstream by posters.science), but rather than omitting the field it now emits `publisher: null`, overwriting anything the model emitted. This gives the downstream automation a consistent slot to fill and keeps the (required) field present. The bundled `poster_schema.json` marks `publisher` as nullable (`"type": ["object", "null"]`), matching the existing nullable convention (e.g. `dateInformation`).

## [0.9.5] - 2026-06-08

### Fixed

- **Top-level JSON array crash (`'list' object has no attribute 'get'`).** When the model returned a top-level JSON array (e.g. `[{...}]`) instead of an object, `extract_json_with_retry` crashed on `result.get(...)`. Parsed results are now coerced to a dict (`_as_result_dict`): a top-level array is unwrapped to its first object, and other non-object JSON becomes a structured error instead of a crash.
- **Lone UTF-16 surrogates broke JSON serialization.** The model could emit a lone surrogate (half of an emoji) into a string; `json.dump(..., ensure_ascii=False)` then raised `'utf-8' codec can't encode ... surrogates not allowed` and the whole extraction was lost. `_postprocess_json` now strips lone surrogates from all result strings, so output is always UTF-8 serializable. Applies to both extraction and the downstream merge.

## [0.9.4] - 2026-06-08

### Changed

- **The `conference` object is no longer model-extracted.** 0.9.3 dropped the conference date fields; this release drops the rest (`conferenceName`, `conferenceLocation`, `conferenceUri`, `conferenceAcronym`) so poster2json never emits a `conference` object at all. Conference information is supplied by the repository or entered on the platform, not guessed from the poster. The prompt no longer requests it, the placeholder/grounding postprocess logic is removed, and any `conference` the model emits is stripped.

## [0.9.3] - 2026-06-05

### Changed

- **Several structured fields are no longer model-extracted.** These values are either fixed provenance markers or supplied by the repository/platform upstream, so letting the model guess them only introduced hallucinations:
  - **`version`** is now always set to the fixed string `"Posters.science automated"`. It is no longer requested in the prompt or read from the poster.
  - **`rightsList`** is dropped from poster2json output. Licenses are not printed reliably on posters; rights come from the repository or platform. Any `rightsList` the model emits is removed.
  - **`descriptions[].descriptionType`** is auto-filled to its default `"Abstract"` for every generated description. The description text itself stays model-generated; only the type is set deterministically.
  - **`conference.conferenceStartDate`, `conference.conferenceEndDate`, and `conference.conferenceYear`** are dropped. Conference dates come from the repository or are entered on the platform, not extracted from the poster. The remaining conference fields (name, location) are still grounded in the poster text as before.

## [0.9.2] - 2026-06-05

### Changed

- **`creators[].nameIdentifiers[]` now carry only `nameIdentifier`.** poster2json no longer writes `nameIdentifierScheme` or `schemeURI` onto name identifiers. The schema requires only `nameIdentifier`, and both fields are derivable from the identifier URL downstream. ORCID detection and dedup now key off the `orcid.org` URL instead of the scheme field, so name + affiliation ORCID enrichment is unchanged. Any scheme/schemeURI the model emits on name identifiers is stripped.

## [0.9.1] - 2026-06-05

### Fixed

- **XY-cut reading-order blow-up on dense pages**: `split_block` now partitions characters into child blocks in a single pass (`_partition`) instead of re-scanning the full character list for every child. The old per-child scan applied a 0.5pt boundary slack that could place a character into two adjacent children on dense pages, which made the recursion grow super-linearly in time and memory and exhaust RAM (tens of GB) on pages with very high glyph counts. A 49,713-character page that previously could not finish now completes in under a second, and reading-order output is byte-identical to the previous engine across a 40-poster sample. The `MAX_PDFPLUMBER_CHARS` guard added in 0.8.2 remains as a backstop.

## [0.9.0] - 2026-06-05

### Changed

- **Publication/funder identifier extraction is now off by default; ORCID and ROR enrichment are unchanged.** poster2json no longer emits identifiers scraped from poster text by default — the top-level `identifiers[]` (DOI/arXiv), `relatedIdentifiers[]`, and funder identifiers (`fundingReferences[*].funderIdentifier`, including the Crossref/ROR funder-name lookup). These were frequently populated from reference-list citations (e.g. an `arXiv:` id printed in the References section) rather than the poster's own identifiers, so this responsibility now lives upstream. Any such identifiers the model emits are also dropped. ORCID (`creators[*].nameIdentifiers[]`) and ROR (affiliation identifiers) enrichment continue to run by default.
- Re-enable the previous behaviour per call with `extract_poster(..., extract_identifiers=True)`, the `poster2json extract --identifiers` CLI flag, or by setting `POSTER2JSON_EXTRACT_IDENTIFIERS=1` for a deployment.

## [0.8.3] - 2026-06-05

### Changed

- **fundingReferences output**: `normalize_funding_references` now derives `schemeUri` from `funderIdentifierType` (ROR, Crossref Funder ID, GRID, ISNI) when it is missing, so callers do not need to collect it unless the type is Other. It also orders each entry's keys so `schemeUri` sits with the funder identifier fields (funderName, funderIdentifier, funderIdentifierType, schemeUri) ahead of the award fields (awardTitle, awardNumber, awardUri), instead of appearing next to awardUri.

## [0.8.2] - 2026-06-05

### Fixed

- **pdfplumber memory blow-up on high character-count pages**: `get_raw_text` now probes the page character count with PyMuPDF first and skips the pdfplumber XY-cut path for pages above `MAX_PDFPLUMBER_CHARS` (30000), falling back to the bounded PyMuPDF extractor. Previously a single pathological PDF (tens of thousands of glyphs, sub-1pt fonts) could grow resident memory without bound until the process was OOM killed.
- **Ghost "lone header" and title/author sections**: the uncaptured-text recovery in `_postprocess_json` now also counts section titles and the words already parsed into titles, creators, descriptions, and subjects as captured, and skips bare section-label lines. It no longer re-imports the title and author banner or duplicate section-name headers as empty content sections. Legitimate footer recovery (for example a Contact block) is preserved.

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
