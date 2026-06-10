# Extraction Prompt: Design and History

This document opens up the LLM extraction prompt for review. The prompt has been
iterated on heavily over the past year, mostly in isolation, and the reasoning
behind each choice has lived in commit messages, changelog entries, and a field
coverage tracker rather than in one place. The goal here is to put the decisions
side by side with the two things they answer to:

- the **[poster-json-schema](https://github.com/fairdataihub/poster-json-schema)**
  repo (`v0.2`, `$id: https://posters.science/schema/v0.2/poster_schema.json`),
  which defines the output contract, and
- the **Poster.json Field Coverage** tracker (the "Poster Sharing" sheet), which
  records, for every schema field, where its value actually comes from (the LLM,
  a regex pass, an external API, the platform, or the user).

The prompt itself lives in `poster2json/extract.py` as `EXTRACTION_PROMPT` and
`FALLBACK_PROMPT`. It is the Stage 2 step described in
[architecture.md](architecture.md); this document is the deep dive on why it asks
for what it asks for.

## The one idea the prompt is built around

The model is only asked to read what is printed on the poster as content and
topic. Everything that is administrative, provenance, or identifier metadata is
filled in deterministically after the model runs (regex, ROR/ORCID/Crossref/SPDX
APIs, file inspection) or is supplied by the platform and the user.

The cleanest way to see this is to compare the schema's `required` list against
what the prompt requests. The schema requires eight top-level fields:

```
["creators", "titles", "publicationYear", "subjects", "descriptions",
 "publisher", "conference", "formats"]
```

Of those eight, the prompt asks the model for **four**: `creators`, `titles`,
`subjects`, and `descriptions`. It does **not** ask for `publisher`, `conference`,
`formats`, or `publicationYear`. Those four are required by the schema but are
filled by the platform and the file system, never guessed by the model.
`publicationYear` was the last of them to move off the model; see
[How we got here](#how-we-got-here).

This split is the result of roughly a year of moving fields off the model one at
a time, each time a field turned out to be a hallucination source or was better
served by a deterministic lookup. The history of those moves is in
[How we got here](#how-we-got-here).

## Who owns each field today

The table reconciles three sources: the schema (is the field required, what type),
the Field Coverage tracker (where the value comes from), and the code (is it in
the prompt, what does post-processing do to it). Only the post-processing actions
that change ownership are listed; routine normalization is omitted.

### Fields the model owns

| Schema field | Required | Tracker source | In prompt | Post-processing |
|---|---|---|---|---|
| `titles[].title` | yes | LLM | yes | ALL-CAPS titles recased, acronyms preserved |
| `creators[].name` | yes (creators) | LLM | yes | name string only |
| `creators[].givenName` / `familyName` | no | LLM | yes | used to derive `nameType` |
| `creators[].affiliation[].name` | no | LLM | yes | resolved to ROR by name |
| `subjects[].subject` | yes | LLM | yes (3 to 5) | NFKC normalize, dedupe, flatten to strings |
| `descriptions[].description` (summary) | yes | LLM | yes (3 to 4 sentences) | text only |
| `researchField` | no | LLM | yes (4 domains or null) | placeholder or junk values coerced to null |
| `content.sections[].sectionTitle` / `sectionContent` | no | LLM | yes | dedupe, verbatim content |
| `imageCaptions[]` / `tableCaptions[]` | no | LLM | yes | normalized to caption arrays |

### Fields the model is deliberately not asked for

| Schema field | Required | Tracker source | In prompt | Post-processing |
|---|---|---|---|---|
| `publicationYear` | yes | platform | no | dropped from prompt, force-nulled (set at publish) |
| `publisher` | yes | platform | no | forced to `null` (set at publish) |
| `conference.*` | yes | platform / user | no | stripped from model output |
| `formats[]` | yes | file extension | no | stripped, set from the file's MIME type |
| `version` | no | platform | no | forced to the string `"Posters.science automated"` |
| `rightsList[]` | no | user / SPDX | no | stripped (license chosen at publish) |
| `language` | no | lingua | no | overwritten by the lingua detector, or null |
| `types.*` | no | platform | no | not requested |
| `dates[]` | no | platform | no | not requested |
| `identifiers[]` | no | Zenodo API | off by default | regex and PDF link annotations when enabled |
| `relatedIdentifiers[]` | no | LLM + regex + PDF links | off by default | regex and PDF links primary |
| `creators[].nameType` | no | platform | no | derived from given/family name |
| `creators[].nameIdentifiers[]` | no | ORCID API | no | scheme fields stripped, ORCID added by lookup |
| `creators[].affiliation[].affiliationIdentifier` | no | ROR API | no | stripped, resolved from name |

### A field the three sources disagree on

`fundingReferences` is worth calling out because the tracker, the schema, and the
prompt do not currently line up. The tracker marks `funderName`, `awardNumber`,
and `awardUri` as LLM-sourced. The post-processing code is set up to normalize
funding and to look up funder ROR identifiers when funding references are present
(`extract.py` around line 2459). But the current `EXTRACTION_PROMPT` JSON block
does not list `fundingReferences` at all, so the model is only enriched on funding
it happens to volunteer, not funding it is asked to produce. This is one of the
[open questions](#open-questions-for-review) below.

## The current prompt, choice by choice

The primary prompt is `EXTRACTION_PROMPT`. Each rule in it answers a specific
failure we hit during the year of iteration.

- **Verbatim copy, no paraphrase or summary.** Section content must be copied
  exactly. The model's instinct is to summarize; for a FAIR archive we need the
  poster's own words. This rule is the oldest one in the prompt and traces back to
  the first MVP ("Section content should be the EXACT quoted text").

- **Use the poster's own section headers, not a fixed list.** The prompt names the
  common headers (Abstract, Introduction, Methods, Results, Discussion,
  Conclusions, References, Acknowledgements) only as examples and tells the model
  to prefer the poster's actual headers. Real posters do not follow a fixed
  section taxonomy.

- **`## ` marks a detected header.** The pdfplumber text stage prefixes
  layout-detected headers with `## ` (see architecture.md, Stage 1). The prompt
  tells the model these are headers so it splits sections on them instead of
  merging everything into one blob.

- **"Key Findings" is not "References".** The model repeatedly mislabeled a
  results section as references and vice versa, so the prompt defines both
  explicitly (Key Findings are discoveries and results; References are numbered
  citations with authors and years).

- **Captions go in `imageCaptions` / `tableCaptions`, not in section content.**
  Figure and table captions are their own schema arrays. Without this rule the
  model buries captions inside the nearest section.

- **Untitled text is still a section.** Footer text, contact lines, and URLs are
  emitted as a section with an empty `sectionTitle` rather than dropped, so no
  poster text is lost.

- **Grounding: metadata comes from the poster or is null.** The GROUNDING rule
  tells the model not to invent metadata. If a value is not printed on the poster,
  it must be null. This rule was added after the model filled in plausible but
  fabricated values.

- **ALL-CAPS titles are recased, acronyms preserved.** A title printed in all caps
  is converted to title case while keeping real acronyms intact
  (`SARS-CoV-2`, not `SARS-COV-2`).

- **`researchField` is one of exactly four OpenAlex domains, or null.** The four
  domains are Health Sciences, Life Sciences, Physical Sciences, Social Sciences.
  Note that the schema only *documents* these four (as the field description and
  examples on a plain string type); the hard "one of these four or null"
  constraint is enforced by the prompt and by a post-processing deny-list, not by
  the schema. The field was renamed from `domain` to avoid confusion with
  biological taxonomy.

- **`subjects`: 3 to 5 keywords.** A bounded count keeps the keyword list useful
  and is later normalized and deduped.

- **`descriptions`: a 3 to 4 sentence summary.** The model writes a short summary
  of the whole poster. Only the description text is model-generated; the schema's
  `descriptionType` is no longer requested in the prompt and is set to `Other`
  deterministically in post-processing, because the summary is machine-generated.
  `Abstract` is reserved for the author's own formal abstract, which the platform
  attaches downstream, so poster2json never emits it.

### The fallback prompt

`FALLBACK_PROMPT` is a shorter version of the same instructions. The pipeline
escalates to it when the full prompt produces truncated or unparseable JSON. The
shorter prompt leaves more of the token budget for output. This two-prompt design
is a direct product of the long fight with truncation and repetition described in
the history below.

### Why the prompt embeds the JSON shape

The prompt carries a literal JSON template with the exact field names and nesting.
Early versions found that without a concrete shape the model invented field names
(`posterTitle` inside `posterContent`, a `contributors` array that is not in the
schema). Embedding the shape, and removing concrete *example values* from it (see
history), keeps the output aligned to the schema without teaching the model to
echo sample data as real content.

## How we got here

The prompt's history falls into three eras. Specific changelog versions and
commits are cited so each decision can be traced.

### Era 1: the MVP series (vision plus 8B, rich schema)

The earliest prompts lived in `json_schema/llama_poster_extraction_mvp*.py` (the
series runs well past v14). They paired a vision OCR model with Llama-3.1-8B for
JSON structuring and asked for a fairly rich DataCite-flavored schema, including
`identifiers` (poster number), `creators` with `nameIdentifiers` and
`affiliation`, `titles`, `posterContent.sections`, and image and table captions.
The core rules that survive to today (verbatim copy, the author name format
`LastName, FirstName`, section discipline) were all present in this era.

Most of the churn across these versions was not about which metadata fields to
extract. It was about OCR engine choices and about fighting JSON truncation and
repetition loops (raising the output token limit, limiting section counts,
removing a repetition penalty that broke JSON, extracting only the first complete
JSON object). The set of metadata fields stayed close to constant. Notably, the
MVP line never asked for `publisher`, `conference`, `version`, `rightsList`,
`language`, `subjects`, or `researchField`; those entered only once the prompt
moved into the package.

### Era 2: the December 2025 schema migration

Two scripts dated 2025-12-18 did a structural alignment to the schema rather than
a field-ownership change:

- `migrate_python_prompts.py` removed `posterTitle` from every prompt's JSON
  example, because the title moved out of `posterContent` and into the top-level
  `titles` array.
- `migrate_json_schema.py` migrated annotated data files the same way and also
  dropped the non-schema `contributors` field in favor of `creators`.

### Era 3: the package, and the systematic removal of administrative fields

Once the prompt moved into `poster2json`, the dominant theme became moving fields
off the model. Each of these is a deliberate decision to let a deterministic
source own a field the model had been guessing.

1. **Grounding rule added** (v0.5.4). Every metadata value must come from poster
   text or be null. This still anchors the current prompt.

2. **Example values removed from the prompt** (v0.5.6). Concrete samples like
   `"Zenodo"` and `"Figure 1: Experimental setup"` were echoed by the model as
   real data, so they were stripped from the in-prompt schema.

3. **`researchField` added** (v0.4.1). A new model-owned field, constrained to the
   four OpenAlex domains, with a post-processing deny-list for junk values.

4. **`language` taken off the model** (v0.4.2, re-hardened in v0.9.13). The lingua
   detector on body text always overwrites any model value. This was prompted by
   non-English posters being labeled `en`.

5. **Identifier extraction moved to regex and APIs** (v0.1.4 through the v0.5.x and
   v0.6.x series). DOIs, ORCIDs, arXiv IDs, ROR, and funder ids are extracted by
   regex and looked up via API rather than trusted from the model.

6. **`publicationYear` grounded, then removed.** The prompt once had a hardcoded
   example year and a "use the current year if not found" instruction, which
   fabricated years at scale; commit `6ab31af` (2026-05-19) changed it to null
   with a strict "only if explicitly printed" rule. It was later removed from the
   model entirely (v0.9.14, commit `79f02d7`): dropped from both prompts and
   force-nulled in post-processing, because the platform sets the publication year
   at publish time.

7. **`formats` set from the file** (v0.6.x). Dropped from the prompt and set
   deterministically from the file extension and MIME type.

8. **`publisher` removed** (commit `ab81be9`; made an explicit `null` placeholder
   in v0.9.6). The publisher is the repository or platform, not something printed
   on the poster.

9. **Publication and funder identifier extraction gated off by default** (v0.9.0).
   These were too often populated from a poster's reference-list citations rather
   than the poster's own identifiers, so the responsibility moved upstream. Re-enable
   with `extract_identifiers=True` or `POSTER2JSON_EXTRACT_IDENTIFIERS=1`. ORCID
   and ROR name-based enrichment still always run.

10. **`nameIdentifiers` carry only the identifier** (v0.9.2). Scheme fields are
    stripped; ORCID is added by lookup.

11. **`version`, `rightsList`, `descriptionType`, conference dates removed**
    (v0.9.3). `version` is forced to a provenance string; `rightsList` is stripped
    (license is chosen by the user at publish); `descriptionType` is set
    deterministically in post-processing (to `Abstract` at the time, corrected to
    `Other` in v0.9.15); conference dates are dropped.

12. **The whole `conference` object removed** (v0.9.4). v0.9.3 dropped only the
    dates; v0.9.4 dropped the rest. Conference metadata is supplied by the
    repository and the platform.

13. **Affiliation identifiers resolved from name only** (v0.9.8). Any model or
    poster-scraped `affiliationIdentifier` is stripped before ROR resolves the
    affiliation by name.

14. **`nameType` derived, not asked for** (v0.9.12). Set to Personal or
    Organizational from the presence of given and family names.

15. **`descriptionType` removed from the prompt and corrected to `Other`**
    (v0.9.15). The model's description is a machine-generated summary, so its type
    is `Other`; `Abstract` is reserved for the author's own formal abstract, which
    the platform attaches downstream. Post-processing had forced `Abstract` since
    v0.9.3; it now sets `Other`, and the prompt no longer asks for the type. (The
    value flip-flopped earlier: set to `Other` in `3945d81` on 2026-05-04, reverted
    to `Abstract` in `74536e8` on 2026-05-19.)

The endpoint of all these moves is exactly the "Tracker source" column in the
Field Coverage sheet: the fields marked LLM are the ones the prompt still owns,
and everything marked platform, regex, or an API name is a field the prompt was
deliberately relieved of.

## Open questions for review

Most of the inconsistencies that surfaced when this doc was first drafted have
since been resolved: `publicationYear` was removed from the model (v0.9.14),
`descriptionType` was removed from the prompt and corrected to `Other` (v0.9.15),
and the grounding note no
longer singles out a field. Two items remain.

1. **`fundingReferences` is kept as a model field, and the prompt should ask for
   it.** Funder name and award number are LLM-sourced by design: the coverage
   tracker lists them as LLM, and post-processing already normalizes funding and
   looks up funder ROR identifiers when funding references are present. The gap is
   that the current prompt does not request `fundingReferences`, so the model is
   only enriched on funding it happens to volunteer. The fix is to add
   `fundingReferences` (funderName, awardNumber, awardUri) to the prompt's JSON
   shape so funding is extracted on purpose rather than by accident.

2. **The model-ownership boundary is worth stating as one rule.** The working
   principle, visible across the whole history, is that descriptive and topical
   content (titles, creators, subjects, the summary, sections, captions,
   researchField) stays with the model, while administrative and provenance
   metadata (publisher, conference, dates, version, formats, language, license,
   identifiers, publicationYear) moves to deterministic sources, APIs, or the
   platform. Writing that rule down gives future field decisions something to
   follow.

## References

- Schema: [fairdataihub/poster-json-schema](https://github.com/fairdataihub/poster-json-schema),
  `v0.2`, `$id: https://posters.science/schema/v0.2/poster_schema.json`. The
  schema bundled in `poster2json/poster2json/schemas/poster_schema.json` tracks
  this version.
- Field provenance: the Poster.json Field Coverage tracker, "Poster Sharing"
  sheet, which maps every schema field to its source (LLM, regex, API, platform,
  user).
- Prompt source: `EXTRACTION_PROMPT` and `FALLBACK_PROMPT` in
  `poster2json/extract.py`; the post-processing that enforces the ownership
  boundary is in `_postprocess_json` in the same file.
- Pipeline context: [architecture.md](architecture.md), Stage 2 (JSON
  Structuring).
- Decision trail: `CHANGELOG.md` (versions 0.4.x through 0.9.x) and the predecessor
  prompts in `json_schema/llama_poster_extraction_mvp*.py`.
