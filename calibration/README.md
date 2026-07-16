# xy_cut + affiliation-corrector calibration

Calibration workbench for poster reading order and author->affiliation
recovery in `poster2json`. Two coupled goals:

1. `xy_cut.py` reading order on multi-column posters (raise fidelity, no
   regressions).
2. The affiliation corrector (`_correct_affiliations_from_superscripts` in
   `extract.py`) must recover correct per-author affiliations on **all 21**
   posters (the 20-poster corpus + the gasimova out-of-sample banner bug).

**Do not merge until sign-off.** We calibrate the pdfplumber/xy_cut path
instead of reverting to pdfalto because the migration off pdfalto was a
licensing decision (pdfalto's xpdf dependency is GPLv2, incompatible with this
package's MIT distribution). pdfalto scored ~88% vs pdfplumber's current 80%.

## Corpus

`json_schema/manual_poster_annotation/<id>/` holds `<id>.pdf`, `<id>_raw.md`
(human reading-order ground truth) and `<id>.json` (schema annotation, the
author->affiliation ground truth). 19 are PDFs; `4737132` is image-only (vision
OCR, no xy_cut, ref-only here). gasimova is the 21st: PDF + clean `_raw.md` +
hand-built `gasimova_annotation.json`, all under `/storage/poster-work/`.

## Metrics (all normalization-matched to validate_model.py)

`reading_order_eval.py` runs `extract_text_with_pdfplumber` (which drives
xy_cut) per poster and reports three metrics with no LLM in the loop, because
reading order and the affiliation corrector are both upstream of the model.
Confirm real pass/fail with a GPU `validate_model.py` run after tuning.

1. **GLOBAL** word_capture + whole-document rougeL. The old top-line; the
   banner is a tiny fraction of tokens so it hides here (gasimova scored 0.888
   global despite a scrambled banner).

2. **FIELD (length-normalized)** rougeL per field (title, authors+affiliations,
   each section), each field best-matched against gen chunks, then aggregated as
   an **equal-weight macro average**. Normalizing for length means a 3-word
   affiliation field counts the same as a 500-word section, so banner and short
   fields can no longer be masked. Corpus baseline rField=0.727 vs rGlobal=0.835,
   and it correctly craters weak posters (4607450 0.403, 4448680 0.434). This is
   the headline calibration number.

3. **AFFIL (banner sub-metric, the affiliation corrector)** for every poster:
   seed the corrector with the annotation's author names + blank affiliations,
   run it on (a) the ideal `_raw.md` order and (b) the xy_cut raw text, and
   compare each author's assigned affiliation to the annotation ground truth
   (normalized match, count-aware). This separates two failure modes:
   - **refOK** corrector logic coverage on ideal order.
   - **genOK** end-to-end with the current reading order.

   Status per poster: PASS (fired + all authors correct on gen) / ORDER-GAP
   (logic ok on ref, reading order breaks it) / LOGIC-GAP (fails even on ideal
   order) / single(n/a) or n/a(<2 authors) (corrector not applicable).

## Baseline and Track A progress

Original baseline (`baselines/baseline.json`): corpus avg w=0.976, rGlobal=0.835,
**rField=0.727**; affiliation corrector 1/13 numbered posters end-to-end,
4/13 logic-OK on ideal order.

**Track A (corrector robustness, `extract.py`) — done for the common cases**
(`baselines/after_track_a.json`, corrector-logic 4/13 -> **8/13**, full test
suite green, +6 unit tests in `tests/test_normalize.py`). Landed, each measured
by refOK climbing with zero regressions:

| gap | example | fix |
|---|---|---|
| honorific between name and marker | `Patel, Ph.D.1` | honorific/degree run in `_author_marker_nums` |
| degree abuts marker (no boundary) | `Surkis, MLS1` | degree token followed by `(?![A-Za-z])` |
| superscript-minus range | `Timmermans1-2` | `_SUP_TRANS` folds U+207B -> `-` |
| modifier-letter separator | `Dettori1,2` (U+02D2) | `_SUP_TRANS` folds -> `,` |
| role glyphs in marker | `Couperus*1+2` | role-glyph gap + `+` join in `_parse_marker_run` |
| given-name initials before marker | `Ivanyi P1`, `Colombo GL3` | uppercase-initials frag |
| keyword-less affiliation dropped | `Delta Hat Ltd`, `STScI` | markers bound entries; >=1 keyword gate |
| collective/group author | `the RECONS Team` | skip non-person creators |

**Remaining LOGIC-GAP (5), lower priority / not pure corrector bugs:** 4564017
(asterisk `*`/`**` affiliation scheme + compound surname "Perdomo Garcia") — a
distinct marker alphabet, the next corrector chunk; 6724771 (14 authors, the
abstract bleeds into the banner so the trailing affiliation swallows it — verbose
institute names look like prose to the guard); 4560930 (partial 0.67); 42
(annotation lists 6 authors, byline has 3 — data mismatch, not a corrector bug);
4519718 (last author has no marker on the poster — genuine ambiguity, the
corrector correctly declines to guess).

**Track B — reading order (`xy_cut.py`). 4 ORDER-GAP posters:** gasimova,
5128504, 8228476, isporeu2023. Corrector logic is now correct (refOK=1.00); xy_cut
scrambles the banner so it never fires on gen. The banner scramble is structural:
the top full-width title/byline/affiliation band should hsplit off before the body
vsplits into columns. Likely a top-spanning-band promotion mirroring
`_promote_spanning_leaves` / `_merge_bottom_region`.

## Usage

    python reading_order_eval.py                       # baseline, all 3 metrics
    python reading_order_eval.py --details             # + per-field rougeL
    python reading_order_eval.py --set MIN_GAP_AREA=2.5 SPLIT_GAP_SLACK=0.3
    python reading_order_eval.py --sweep MIN_GAP_AREA 2.0,2.5,3.0,3.5,4.0
    python reading_order_eval.py --save baselines/<name>.json

## xy_cut levers

Six sweepable module constants (monkeypatched, no source edit to explore):
MIN_GAP_AREA 3.0, SPLIT_GAP_SLACK 0.2, MIN_CHUNK_WIDTH 2.0, MIN_GAP_SIZE 0.2,
BASELINE_RANGE 0.5, DESCENT_ADJUST 0.35. Three hardcoded heuristics are also
candidate levers (lift to constants before sweeping): single-line guard
`1.5*avg_fs`, spanning-promote `0.7*page_width`, bottom-merge `0.65*page_height`.
