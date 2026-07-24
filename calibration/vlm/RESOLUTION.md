# Resolution and settings follow-up (2026-07-24)

Four questions from the review: better generation settings? a newer model? a
hidden resolution knob in the config? The answers, in order of usefulness.

## 1. The 1540px ceiling is soft: the vision RoPE table can be rebuilt

This is the real finding. Last week's file called 1540px a "hard architectural
ceiling". It is not. The vision tower precomputes a
`max_patches_per_side x max_patches_per_side` RoPE table where
`max_patches_per_side = image_size // patch_size = 1540 // 14 = 110`
(`PixtralRotaryEmbedding.compute_default_rope_parameters`). A larger image
indexes past 110 and asserts -- but the table is analytic, so it can be rebuilt
for any `image_size`:

    enc = model.model.vision_encoder
    c = enc.patch_positional_embedding.config
    c.image_size = 2464                       # 176 patches/side
    emb = PixtralRotaryEmbedding(c).to(dev)   # buffers need explicit .to(dev)
    emb.inv_freq = emb.inv_freq.to(dev)
    emb.original_inv_freq = emb.original_inv_freq.to(dev)
    enc.patch_positional_embedding = emb

No retraining. Wired into the runner as `--rope-rebuild` (only acts when
`--longest > 1540`). At 2464 it runs clean -- coherent text, VRAM 4.2 -> 5.1 GB,
and on the feasibility probe the duplicate-line fraction on the most starved
poster actually FELL (0.30 -> 0.09). NTK theta-scaling on top gave nothing extra
and 3080 began to degrade, so plain table-rebuild at ~1.6x is the sweet spot.

## 2. But more resolution is not a blanket win, because extrapolation has a cost

Scored full corpus at 2464-rebuild vs 1540 (`rope_crossover.py`). Corpus rField
went DOWN, 0.765 -> 0.731, head-to-head 8 wins / 11 losses. The per-poster split
by native effective DPI:

    already-fine (>=40 DPI at 1540)  n=5   mean d rField -0.075   clearly worse
    starved      (<40 DPI)           n=13  mean d rField -0.009   a wash

The already-fine posters degrade cleanly (6724771 0.98 -> 0.80, 4560930
0.65 -> 0.53): they are small, already at or above native resolution, so 2464
only pushes their patch grid into the never-trained 110-176 band for no added
detail. That is the cost of extrapolation, and it is real.

The starved posters are a genuine mixed bag, not the uniform win the DPI theory
predicted:

    42        (32 DPI)  rField 0.76 -> 0.99   +0.234   <- huge
    aysaekanger(33)     0.69 -> 0.76   +0.073
    8228476   (33)      0.50 -> 0.56   +0.052
    gasimova  (33)      0.90 -> 0.74   -0.167   <- its banner was already 1.00
    AISec     (33)      0.84 -> 0.74   -0.093
    10890106  (28)      truncated at 2464 (more pixels -> more tokens)
    5128504   (35)      truncated at 2464

So added detail helps some starved posters a lot and destabilizes others whose
banner was already perfect at 1540. The extrapolation cost competes with the
detail gain, and which wins is per-poster.

**Conclusion:** RoPE rebuild is a real, working lever, but "just render bigger"
is wrong. The right design is ADAPTIVE per-poster resolution -- scale each
poster toward a target effective DPI (~80-100), CAP at ~1.6x the trained grid
(≈2464) to stay in the safe extrapolation band, and never upscale a poster
already above target. Plus a higher token budget, since more pixels truncated
two dense posters at 6144. That is the follow-up worth running; a fixed edge is
not it.

## 3. Generation settings do NOT fix the failures (retraction of "we ran it wrong")

I noted last week that we used greedy while the shipped `generation_config.json`
is `do_sample=true, temperature=0.2, top_p=0.9`, and implied that was our bug.
Tested on isporeu2023, the poster that loops (`probe_combined.py`):

    greedy (what we ran)       3072tok dup=0.43  LOOP
    card: temp0.2 top_p0.9     3072tok dup=0.43  LOOP
    greedy + rep_penalty1.15   3072tok dup=0.42  LOOP

All three loop identically. Honoring the config is more correct and we should do
it, but it changes nothing on the hard cases. The isporeu loop is not a decoding
artifact: it begins exactly at `<th>Treatment</th>` (line 105, first repeat of
line 75) -- the model degenerates trying to transcribe a dense
cost-effectiveness RESULTS TABLE as HTML. That is a known VLM-OCR failure mode
and a model limitation, not a setting. The banner and prose above it are clean.

## 4. No newer or higher-res model exists

LightOnOCR-2 (Jan 2026) is current and is the flagship. Checked the org: the
only other checkpoints are same-size variants -- `-base`, `-ocr-soup` (weight
average), `-bbox` (adds bounding boxes) -- all 1B, all 1540px vision. There is
no 2B, no larger, no higher-resolution model. The `LightOnOCR-0.9B-32k` "32k" is
a pruned VOCABULARY (European-language speedup), not context length or
resolution. `-bbox` is worth a look ONLY if we later want layout coordinates;
it does not change the resolution story.

## Net

The banner win from last week stands (VLM reads author/affiliation structure far
better than xy_cut). The resolution ceiling is liftable and helps the worst
posters, but not for free, so the next experiment is adaptive resolution + token
budget, not a bigger fixed render. Settings and model-shopping are dead ends:
the config is already optimal and there is nothing newer to buy.
