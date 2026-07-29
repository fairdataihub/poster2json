#!/usr/bin/env python3
"""Run LightOnOCR-2-1B over the poster corpus and save its raw output.

Phase 1 of the VLM comparison. Kept separate from scoring because it needs
transformers v5 (LightOnOcr* landed in v5; the pipeline's ~/myenv is on 4.57
and MUST NOT be upgraded under it). Run as:

    CUDA_VISIBLE_DEVICES=1 PYTHONPATH=~/locr-libs \
        ~/myenv/bin/python calibration/vlm/run_lightonocr.py

~/locr-libs holds transformers v5 installed with `pip install --target`, so it
shadows 4.57 for this process only and leaves every other consumer of ~/myenv
alone. Writes one <id>.md per poster into calibration/vlm/out/ and a run.json
of timings; scoring is phase 2 (compare_vlm.py), which runs under plain
~/myenv because it needs poster2json for the control.

Resolution: --longest sets the render size AND the processor's longest_edge
together. They must agree; see render() and the processor note in main().
"""
import argparse
import glob
import json
import os
import time

import torch

MODEL = "lightonai/LightOnOCR-2-1B"
CORPUS = ("/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/"
          "json_schema/manual_poster_annotation")
EXTRA = [("gasimova(oos)", "/storage/poster-work/gasimova.pdf")]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")


def render(path, longest):
    """Rasterize page 1 straight from the vector at the target size.

    Renders at exactly the size the model will see rather than at a fixed DPI
    followed by a downscale. A poster is enormous (gasimova is 3312pt, about
    46 inches): at 200 DPI it rasterizes to ~9200px, and squeezing that to
    1540 throws away almost everything. Worse, the processor resizes AGAIN to
    its own longest_edge, so a pre-resize costs a second resampling pass for
    nothing -- measurably so, which is why an early sweep that only changed
    the pre-resize made things WORSE (10890106 w 0.942 -> 0.723) instead of
    better. Rendering from the vector at the final size resamples once, and
    pdfium does it from the source geometry.
    """
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(path)
    page = doc[0]
    scale = longest / max(page.get_width(), page.get_height())
    return page.render(scale=scale).to_pil().convert("RGB")



def render_tiles(path, longest, spec):
    """Page 1 as a grid of tiles, each rendered at `longest` from vector.

    Tiling is the only resolution lever available: image_size=1540 is baked into
    the vision tower's RoPE table, so a larger image asserts rather than helps.
    `spec` is an int N (NxN grid, historical behaviour) or "RxC" (e.g. "1x3"
    for full-height COLUMN STRIPS -- which preserve a poster's column reading
    order by construction, unlike a grid that cuts columns horizontally).
    Tiles overlap by 6% so a line of text on a seam is whole in one of them.
    """
    import pypdfium2 as pdfium
    if isinstance(spec, str) and "x" in spec:
        rows, cols = (int(x) for x in spec.lower().split("x"))
    else:
        rows = cols = int(spec)
    doc = pdfium.PdfDocument(path)
    page = doc[0]
    w_pt, h_pt = page.get_width(), page.get_height()
    if rows <= 1 and cols <= 1:
        scale = longest / max(w_pt, h_pt)
        return [page.render(scale=scale).to_pil().convert("RGB")]
    n = max(rows, cols)
    full = page.render(scale=longest * n / max(w_pt, h_pt)).to_pil().convert("RGB")
    W, H = full.size
    tw, th = W / cols, H / rows
    ov = 0.06
    out = []
    for r in range(rows):
        for c in range(cols):
            box = (max(0, int((c - ov) * tw)), max(0, int((r - ov) * th)),
                   min(W, int((c + 1 + ov) * tw)), min(H, int((r + 1 + ov) * th)))
            out.append(full.crop(box))
    return out


def items():
    out = []
    for d in sorted(glob.glob(os.path.join(CORPUS, "*"))):
        if not os.path.isdir(d):
            continue
        pid = os.path.basename(d)
        pdf = glob.glob(os.path.join(d, "*.pdf"))
        if pdf:
            out.append((pid, pdf[0]))
    for pid, pdf in EXTRA:
        if os.path.exists(pdf):
            out.append((pid, pdf))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--longest", type=int, default=1540,
                    help="longest edge in px, for BOTH the render and the "
                         "processor (they must agree or it resamples twice)")
    ap.add_argument("--rope-rebuild", action="store_true",
                    help="rebuild the vision RoPE table for --longest so the "
                         "1540px vision ceiling lifts. Extrapolates the "
                         "positional grid; no retraining. See calibration/vlm "
                         "RoPE findings.")
    ap.add_argument("--max-new-tokens", type=int, default=6144)
    ap.add_argument("--only", default=None, help="run a single poster id")
    ap.add_argument("--tiles", type=str, default="1",
                    help="split the page into a grid and OCR each tile at "
                         "--longest, concatenating the results. An int N gives "
                         "an NxN grid; 'RxC' (e.g. '1x3') gives full-height "
                         "column strips, which preserve column reading order. "
                         "The vision tower is fixed at 1540px, which is ~132 "
                         "DPI over A4 but ~33 over a four-foot poster; tiling "
                         "is the only way to give it page-like detail.")
    ap.add_argument("--ids", default=None,
                    help="comma-separated poster ids to run")
    ap.add_argument("--out", default=None,
                    help="output dir name under calibration/vlm (default: out)")
    args = ap.parse_args()

    out_dir = (os.path.join(os.path.dirname(os.path.abspath(__file__)), args.out)
               if args.out else OUT)
    os.makedirs(out_dir, exist_ok=True)
    from transformers import LightOnOcrForConditionalGeneration, LightOnOcrProcessor

    t0 = time.time()
    model = LightOnOcrForConditionalGeneration.from_pretrained(
        MODEL, dtype=torch.bfloat16).to("cuda").eval()
    # PixtralImageProcessor ships size={"longest_edge": 1540} and do_resize=True,
    # so it silently rescales every page to 1540 no matter what is handed to it:
    # feeding a bigger image achieves nothing but a second resampling pass. The
    # resolution knob is HERE, not in the render. Pixtral encodes arbitrary sizes
    # (14px patches, 2x2 spatial merge), so raising this genuinely gives the model
    # more pixels -- at ~4x the image tokens for 2x the edge.
    processor = LightOnOcrProcessor.from_pretrained(
        MODEL, size={"longest_edge": args.longest})
    print(f"processor longest_edge={processor.image_processor.size}", flush=True)

    if args.rope_rebuild and args.longest > 1540:
        from transformers.models.pixtral.modeling_pixtral import PixtralRotaryEmbedding
        enc = model.model.vision_encoder
        c = enc.patch_positional_embedding.config
        c.image_size = args.longest
        dev = next(enc.parameters()).device
        emb = PixtralRotaryEmbedding(c).to(dev)
        emb.inv_freq = emb.inv_freq.to(dev)
        emb.original_inv_freq = emb.original_inv_freq.to(dev)
        enc.patch_positional_embedding = emb
        print(f"rebuilt vision RoPE for image_size={args.longest} "
              f"({args.longest // 14} patches/side)", flush=True)
    print(f"model loaded in {time.time() - t0:.1f}s", flush=True)

    runs = []
    for pid, pdf in items():
        if args.only and pid != args.only:
            continue
        if args.ids and pid not in [x.strip() for x in args.ids.split(",")]:
            continue
        tiles = render_tiles(pdf, args.longest, args.tiles)
        t = time.time()
        parts, n_tok, truncated = [], 0, False
        for tile in tiles:
            conv = [{"role": "user", "content": [{"type": "image", "image": tile}]}]
            inputs = processor.apply_chat_template(
                conv, add_generation_prompt=True, tokenize=True,
                return_dict=True, return_tensors="pt")
            inputs = {k: (v.to("cuda", torch.bfloat16) if v.is_floating_point()
                          else v.to("cuda")) for k, v in inputs.items()}
            with torch.inference_mode():
                out_ids = model.generate(**inputs,
                                         max_new_tokens=args.max_new_tokens,
                                         do_sample=False)
            gen = out_ids[0, inputs["input_ids"].shape[1]:]
            parts.append(processor.decode(gen, skip_special_tokens=True))
            n_tok += int(gen.shape[0])
            # A generation that stops exactly at the cap was truncated, and a
            # truncated page silently loses recall; flag it rather than score it.
            truncated |= int(gen.shape[0]) >= args.max_new_tokens
        text = "\n\n".join(parts)
        secs = time.time() - t
        img = tiles[0]
        with open(os.path.join(out_dir, f"{pid}.md"), "w", encoding="utf-8") as fh:
            fh.write(text)
        runs.append({"id": pid, "image": list(img.size), "tiles": len(tiles), "tokens": n_tok,
                     "seconds": round(secs, 1), "chars": len(text),
                     "truncated": truncated})
        print(f"{pid:42s} {len(tiles)}x{img.size[0]}x{img.size[1]:<5} "
              f"{n_tok:5d} tok {secs:6.1f}s{'  TRUNCATED' if truncated else ''}",
              flush=True)

    meta = {"model": MODEL, "longest": args.longest, "tiles": args.tiles,
            "rope_rebuild": args.rope_rebuild,
            "max_new_tokens": args.max_new_tokens,
            "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2),
            "runs": runs}
    with open(os.path.join(out_dir, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    n_trunc = sum(1 for r in runs if r["truncated"])
    print(f"\n{len(runs)} posters, peak VRAM {meta['peak_vram_gb']} GB, "
          f"{n_trunc} truncated -> {out_dir}")


if __name__ == "__main__":
    main()
