# xy_cut reading-order calibration

Calibration workbench for `poster2json/xy_cut.py` (the recursive XY-cut that
recovers reading order from pdfplumber chars). Goal: raise reading-order
fidelity on multi-column posters without regressing the passing set, and fix
the banner class of failure (scrambled author byline + affiliation legend that
defeats `_correct_affiliations_from_superscripts`).

**Do not merge until sign-off.** We calibrate xy_cut rather than revert to
pdfalto because the migration off pdfalto was a licensing decision: pdfalto's
xpdf dependency is GPLv2, incompatible with this package's MIT distribution.
pdfalto scored ~88% vs pdfplumber's current 80% on the 20-poster corpus, so the
target is to close that gap in the MIT-licensed path.

## Corpus

`json_schema/manual_poster_annotation/<id>/` holds `<id>.pdf` + `<id>_raw.md`
(human reading-order ground truth). 19 of the 20 are PDFs; `4737132` is an
image-only poster (vision OCR path, not xy_cut) and is skipped here. `gasimova`
is an out-of-sample regression check (`/storage/poster-work/`), the banner bug
that started this work.

## Fast proxy metric

`reading_order_eval.py` scores xy_cut raw text against `_raw.md` with the same
two metrics `poster-extraction-validation/validate_model.py` uses:

    word_capture = |gen_words & ref_words| / |ref_words|
    rouge_l      = rougeL F-measure (use_stemmer=True), ref vs gen

Reading order is fixed upstream of the LLM, so this isolates xy_cut and runs in
seconds (no 8B model). After tuning, confirm real pass/fail with a GPU run of
validate_model.py.

    python reading_order_eval.py                       # baseline
    python reading_order_eval.py --set MIN_GAP_AREA=2.5 SPLIT_GAP_SLACK=0.3
    python reading_order_eval.py --sweep MIN_GAP_AREA 2.0,2.5,3.0,3.5,4.0

## Baseline (current constants, `baselines/baseline.json`)

Official corpus (19 PDF posters): **w = 0.973, r = 0.840**. gasimova (oos):
w = 0.962, r = 0.888. Lowest r: aysaekanger 0.661, 10890106 0.679, 17268692
0.707, 4560930 0.736, 8228476 0.745 — these track the crosswalk's full-pipeline
failures (4560930, 16083265, 17268692, aysaekanger).

## Known caveat: global ROUGE-L masks the banner failure

gasimova scores r=0.888 despite a scrambled banner, because the banner is a
small fraction of total tokens. The banner failure is localized but
high-impact (it breaks author->affiliation mapping). Before tuning, add a
**banner sub-metric**: score reading order of just the author + affiliation
region, or (stronger) check whether `_correct_affiliations_from_superscripts`
fires and yields the annotation's author->affiliation mapping. Optimize the
global proxy and the banner sub-metric together so we do not trade banner
correctness for a marginal global gain.

## Levers

Six module constants (swept by monkeypatch, no source edit needed to explore):

| constant | baseline | role |
|---|---|---|
| MIN_GAP_AREA | 3.0 | primary split threshold (gap_w x block_h vs this x fs^2) |
| SPLIT_GAP_SLACK | 0.2 | co-cut gaps within slack x fs of the max (3+ col splits) |
| MIN_CHUNK_WIDTH | 2.0 | min child chunk width (x fs) |
| MIN_GAP_SIZE | 0.2 | min gap (x min_fs) |
| BASELINE_RANGE | 0.5 | line clustering tolerance (x fs) |
| DESCENT_ADJUST | 0.35 | baseline shift for containment |

Three hardcoded heuristics are also candidate levers (would need to be lifted to
module constants before sweeping): single-line guard `block_h < 1.5*avg_fs`
(split_block), spanning-leaf promote `0.7*page_width`
(`_promote_spanning_leaves`), bottom-merge `0.65*page_height`
(`_merge_bottom_region`). The banner scramble points at the top-of-page
spanning region: the title/byline/affiliation band should hsplit off before the
body vsplits into columns. Likely work is a top-spanning-band promotion mirror
of `_promote_spanning_leaves`/`_merge_bottom_region`.
