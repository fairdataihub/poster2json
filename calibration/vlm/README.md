# LightOnOCR-2 as an extraction option: raw-text comparison

Feature branch `feature/lightonocr-eval`. Asks one question and no others:
**does an end-to-end VLM read a poster better than pdfplumber + xy_cut?**
Raw text only. No affiliation corrector, no JSON, no LLM stage.

Branched from `feature/xy-cut-calibration`, not `main`, deliberately: that
branch holds the current best pipeline (rField 0.741 vs main's 0.727) and the
harness whose metrics both sides are scored with. Comparing a new model against
a stale control would flatter it.

## What is being compared

| | control | candidate |
|---|---|---|
| | `extract_text_with_pdfplumber` (pdfplumber + xy_cut) | `lightonai/LightOnOCR-2-1B` |
| input | PDF text layer | page rendered to an image |
| output | markdown-ish text | markdown |

Both are scored by the same code against the same reference, the human
`_raw.md` transcription. Neither side gets a metric of its own.

- `w` — word capture vs `_raw.md`. Format-blind; the fairest single number for
  "did it read the page".
- `rGlobal` — whole-document ROUGE-L. Order-sensitive, format-blind.
- `rField` — per-field ROUGE-L, length-normalized (title, authors+affiliations,
  and each section count once each regardless of length). **Needs the output to
  carry markdown headers** so it can be chunked into fields. Ours emits `## `;
  LightOnOCR emits `#`/`##` of its own accord, so the comparison holds. A model
  that emitted flat text would score badly here for reasons of format rather
  than reading — so read `w` and `rGlobal` first.

## Running it

Two phases, two environments, on purpose.

    # phase 1: generate (needs transformers v5)
    CUDA_VISIBLE_DEVICES=1 PYTHONPATH=~/locr-libs \
        ~/myenv/bin/python calibration/vlm/run_lightonocr.py

    # phase 2: score (needs poster2json, i.e. plain ~/myenv)
    ~/myenv/bin/python calibration/vlm/compare_vlm.py --details

### The environment split matters

`LightOnOcrForConditionalGeneration` / `LightOnOcrProcessor` landed in
**transformers v5**. `~/myenv` is on **4.57.6** and is what poster2json, the
calibration harness and the 8B validation all import. **Do not upgrade it in
place.** Instead:

    ~/myenv/bin/pip install --target ~/locr-libs "transformers>=5" pypdfium2

`PYTHONPATH=~/locr-libs` shadows 4.57 for that one process and leaves every
other consumer alone. Verified: transformers 5.14.1 + torch 2.8.0+cu128 (torch
is reused from `~/myenv`, not reinstalled). A `--system-site-packages` venv does
NOT work here, because `~/myenv` is itself a venv and the new venv inherits the
base interpreter's packages, not `~/myenv`'s.

### GPU etiquette

hpcf's GPUs are usually busy: GPU 1 typically runs an ollama llama-server and
two vLLM engines (~74 of 98 GB). LightOnOCR-2-1B is small — **2.5 GB peak, bf16**
— so it coexists on GPU 1's headroom via `CUDA_VISIBLE_DEVICES=1`. It is loaded
with plain transformers rather than vLLM precisely because vLLM pre-allocates a
memory pool and would fight the running engines. **Do not kill those services to
make room.** GPU 0 (the 4090) has only ~3.5 GB free and drives the display.

## Rendering and the 1540px ceiling

**Read this before trying to raise resolution.** `--longest` sets the render
size AND the processor's `longest_edge` together, and 1540 is a hard ceiling:

- `PixtralImageProcessor` ships `size={"longest_edge": 1540}, do_resize=True`,
  so it silently rescales whatever you hand it back to 1540. Rendering bigger
  without changing the processor buys nothing and costs a second resampling
  pass — measurably (10890106 `w` 0.942 -> 0.723). The knob is the processor.
- Raising the processor past 1540 asserts: `PixtralVisionConfig.image_size` is
  1540 with `patch_size` 14, so the vision RoPE table holds 110 patch positions
  per axis and a larger image indexes off the end
  (`modeling_pixtral.py:126  freqs = self.inv_freq[position_ids]`). The CUDA
  assert is **async**, so the first oversized page can look like it worked while
  computing on out-of-bounds indices. Do not trust it.

1540px is ~132 DPI over A4 — self-consistent with the model card — but a
conference poster is 3-4 feet, so it lands at ~33 DPI (17 of our 20 posters get
under 80; see `eff_dpi.py`). `--tiles N` is the only lever: it OCRs an NxN grid
at 1540 each, multiplying effective DPI by N. It recovers recall on the largest
posters but destroys reading order; see FINDINGS.md.

`--max-new-tokens` defaults to 6144. A generation that stops exactly at the cap
was truncated and has silently lost recall; the runner flags those in `run.json`
and in its output rather than letting them be scored as if complete.

## What to watch for

- **Hallucination.** A VLM can produce fluent text that is not on the poster.
  ROUGE rewards recall and will not punish invention. Read some outputs before
  believing a headline number. But measure it against what the pipeline
  CONSUMES: poster2json looks ORCIDs up from name + affiliation and never reads
  them off the poster, so hallucinated ORCIDs are moot and the lookup keys are
  what matter (`keys_check.py`). `fidelity_check.py` still reports invented
  exact strings, since that is worth knowing, but it does not gate this
  pipeline. FINDINGS.md has the retraction.
- **LaTeX.** LightOnOCR emits `$^{1,2}$` for superscript markers. Harmless for
  raw-text scoring (`_alpha()` strips it to `12`, and the reference's `¹˒²`
  NFKD-normalizes to the same), but it would need handling before the
  affiliation corrector could consume VLM output. Out of scope here.
- **The banner is the interesting part.** That is where our pipeline needed all
  of Track A/B and approach A. Compare `authors+affiliations` per-field
  (`--details`) as much as the corpus average.
