# Findings: LightOnOCR-2-1B vs pdfplumber + xy_cut (2026-07-17)

19 corpus posters + gasimova. `lightonai/LightOnOCR-2-1B`, bf16, greedy,
3.0 GB peak VRAM, ~60s/poster, on one GPU alongside the running ollama/vLLM
services.

## Verdict

**A serious candidate for structure, resolution-starved on posters, and not yet
usable as a drop-in.** It reads banners far better than we do. It loses fine
text because its vision tower is fixed at a page-sized 1540px and a poster is
four feet. Its identifier hallucinations, which the first version of this file
called disqualifying, are **irrelevant to this pipeline** -- see the retraction.

## RETRACTED: the identifier charge

The first version of this file led with "it fabricates identifiers -- 6 of 10
ORCIDs wrong -- therefore disqualifying". **That was wrong, and it was wrong
because I did not read the pipeline before measuring it.**

poster2json never reads an ORCID off a poster. `orcid.enrich_creators_orcid`
queries the ORCID API with `given-names` + `family-name` +
`affiliation-org-name` and attaches an id only on a single unambiguous hit; ROR
resolves institutions the same way. A hallucinated ORCID in the raw text is
simply never consulted, so counting hallucinated ORCIDs measured nothing about
this system. The lesson is the same one this corpus keeps teaching: **measure
the thing the pipeline actually consumes.**

What the pipeline consumes is the **lookup keys** -- author names and
affiliation strings. Re-measured on those (`keys_check.py`):

| extractor | authors found | affils found |
|---|---|---|
| pdfplumber | 90/93 = 0.968 | 43/47 = **0.915** |
| LightOnOCR | 91/93 = **0.978** | 40/47 = 0.851 |

The VLM is *slightly better* at recovering author names, and worse on
affiliations — where **all four of its extra losses are isporeu2023**, the one
poster it failed outright. Its other losses are the same abbreviation cases
pdfplumber loses (VTT, CARL, STScI, Perdomo García, Münz-Manor). It actually
recovered `the RECONS Team` and `University of Kent`, which pdfplumber missed.

And because enrichment demands an exact unambiguous match (precision over
coverage, 0.9.17), a corrupted key fails **safe**: no id attached, rather than
the wrong person's id. So the real cost of VLM corruption is coverage, not
misattribution. A far smaller charge than the one I filed.

## It reads structure better

| metric | pdfplumber + xy_cut | LightOnOCR-2-1B |
|---|---|---|
| `w` (word capture) | **0.976** | 0.936 |
| `rGlobal` | **0.835** | 0.788 |
| `rField` (length-normalized) | 0.741 | **0.765** |

On the **banner** — `authors+affiliations`, the field that cost this project
Track A, Track B and approach A — it wins **15 of 19** (2 ties, 2 losses), mean
**+0.179**: gasimova 0.742 -> 1.000, 4607450 0.244 -> 0.909, 4560930 0.600 ->
1.000. From pixels, with no xy_cut, no `_flatten_top_band`, no superscript-row
merge, no marker parsing. It also returns wrapped titles in one piece.

## Resolution: the ceiling is architectural, and posters fall off it

> UPDATE 2026-07-24: "architectural" was too strong. The 1540px ceiling
> is SOFT -- the Pixtral vision RoPE table can be rebuilt for a larger
> image_size with no retraining (run_lightonocr.py --rope-rebuild). It
> helps the worst-starved posters but not for free. See RESOLUTION.md.

**1540px is not a setting.** `PixtralVisionConfig.image_size = 1540`,
`patch_size = 14`, so the vision tower's 2D RoPE table holds 110 patch
positions per axis. Hand it a bigger image and it indexes off the end:

    modeling_pixtral.py:126  freqs = self.inv_freq[position_ids]
    CUDA error: device-side assert triggered

Two traps here, both of which cost me a sweep:

1. `PixtralImageProcessor` ships `size={"longest_edge": 1540}, do_resize=True`,
   so it **silently rescales whatever you give it back to 1540**. Rendering
   larger and feeding it in does not raise resolution — it only resamples
   twice, and measurably hurts (10890106 `w` 0.942 -> 0.723 at "2048").
   The knob is the processor's `size`, not the render.
2. Raising the processor's `size` past 1540 asserts (above). The failure is
   async, so the *first* oversized page may appear to succeed while computing
   on out-of-bounds indices; do not trust it.

**What 1540px means for a poster** (`eff_dpi.py`):

| | effective DPI at 1540px |
|---|---|
| A4 (the model card's design point) | 132 |
| poster mean | **48** |
| 17268692 (60 x 44 in) | **26** |
| **17 of 20 posters** | **under 80** |

The model card's "200 DPI, longest dimension 1540px" is self-consistent for a
page. A conference poster is 3-4 feet, so the same 1540px spreads to ~33 DPI.
**We are asking it to read 8pt body text at a quarter of the resolution it was
built for.**

Supporting evidence, honestly weak (`dpi_corr.py`): on the 3 page-sized
documents in the corpus (>=100 DPI) the VLM's recall gap **vanishes**
(mean dW **+0.012**); on the 17 poster-sized ones it is **-0.048**.
r(DPI, dW) = +0.313 — positive but weak, n=3 in the high group. Suggestive,
not proven.

## Tiling: confirms the diagnosis, does not yet fix it

Tiling is the only lever left, so `--tiles N` renders an NxN grid (6% overlap)
and OCRs each tile at 1540, multiplying effective DPI by N. At 2x2, on the
biggest posters, **recall improves exactly as the theory predicts**:

    17268692 (26 DPI)   w 0.916 -> 0.993   (beats pdfplumber's 0.986)
    42       (32 DPI)   w 0.897 -> 0.972
    15963941 (39 DPI)   w 0.945 -> 0.987   (beats pdfplumber's 0.958)

But it is not uniform (4 of 8 gained, 4 lost: 4448680 0.923 -> 0.828, gasimova
0.956 -> 0.906), and **it destroys reading order**: rGlobal 0.788 -> 0.471,
rField 0.765 -> 0.547, because concatenating quadrants chops multi-column text
mid-flow and duplicates the overlaps. Naive grid tiling is not usable.

## Where this points

The two extractors fail in opposite directions, and so do the two VLM modes:

- pdfplumber has the text exactly but has to *infer* layout (all of xy_cut).
- the VLM sees layout natively but has to *predict* every glyph, at 33 DPI.
- a full-page VLM pass has the order but starves on detail; tiles have the
  detail but lose the order.

Worth trying next, in order:

1. **Full-page pass for order + tiles for recall.** Use the full-page output as
   the skeleton and tiles only to recover text the full pass missed. Keeps
   rGlobal while capturing the +0.077 recall.
2. **Layout-aware tiling** — tile on column boundaries (xy_cut already finds
   them) instead of a blind grid, so no tile cuts a column mid-flow.
3. **Banner-only VLM.** Narrowest and safest: our pipeline everywhere, the VLM
   on the banner crop alone, where it wins +0.179 and where a crop is naturally
   page-sized so resolution starvation disappears.
4. Anything that consumes VLM text must read LaTeX superscripts (`$^{1,2}$`)
   before the affiliation corrector can use it.

## Other failure modes

- **isporeu2023** fails outright: dropped 4 of 8 authors, mis-assigned markers
  (Ciccarone 3->2, Schlichting 4->1), read "Delta Hat Ltd" as "Delta et Ltd",
  and never terminated — 6144 tokens truncated, still going at 16384 (471s),
  emitting HTML tables. Ours scores rField 0.849 there; the VLM 0.509.
- **8228476** (RTL Hebrew) is worse under the VLM too (0.503 vs 0.692), so
  approach D is not solved by switching extractor.
