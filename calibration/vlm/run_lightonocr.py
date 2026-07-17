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

Rendering follows the model card: 200 DPI, longest side 1540px, aspect kept.
"""
import argparse
import glob
import json
import os
import time

import torch
from PIL import Image

MODEL = "lightonai/LightOnOCR-2-1B"
CORPUS = ("/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/"
          "json_schema/manual_poster_annotation")
EXTRA = [("gasimova(oos)", "/storage/poster-work/gasimova.pdf")]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")


def render(path, dpi, longest):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(path)
    img = doc[0].render(scale=dpi / 72).to_pil().convert("RGB")
    w, h = img.size
    s = longest / max(w, h)
    if s < 1:
        img = img.resize((round(w * s), round(h * s)), Image.LANCZOS)
    return img


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
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--longest", type=int, default=1540)
    ap.add_argument("--max-new-tokens", type=int, default=6144)
    ap.add_argument("--only", default=None, help="run a single poster id")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    from transformers import LightOnOcrForConditionalGeneration, LightOnOcrProcessor

    t0 = time.time()
    model = LightOnOcrForConditionalGeneration.from_pretrained(
        MODEL, dtype=torch.bfloat16).to("cuda").eval()
    processor = LightOnOcrProcessor.from_pretrained(MODEL)
    print(f"model loaded in {time.time() - t0:.1f}s", flush=True)

    runs = []
    for pid, pdf in items():
        if args.only and pid != args.only:
            continue
        img = render(pdf, args.dpi, args.longest)
        conv = [{"role": "user", "content": [{"type": "image", "image": img}]}]
        inputs = processor.apply_chat_template(
            conv, add_generation_prompt=True, tokenize=True,
            return_dict=True, return_tensors="pt")
        inputs = {k: (v.to("cuda", torch.bfloat16) if v.is_floating_point()
                      else v.to("cuda")) for k, v in inputs.items()}
        t = time.time()
        with torch.inference_mode():
            out_ids = model.generate(**inputs, max_new_tokens=args.max_new_tokens,
                                     do_sample=False)
        gen = out_ids[0, inputs["input_ids"].shape[1]:]
        text = processor.decode(gen, skip_special_tokens=True)
        secs = time.time() - t
        # A generation that stops exactly at the cap was truncated, and a
        # truncated page silently loses recall; flag it rather than score it.
        truncated = int(gen.shape[0]) >= args.max_new_tokens
        with open(os.path.join(OUT, f"{pid}.md"), "w", encoding="utf-8") as fh:
            fh.write(text)
        runs.append({"id": pid, "image": list(img.size), "tokens": int(gen.shape[0]),
                     "seconds": round(secs, 1), "chars": len(text),
                     "truncated": truncated})
        print(f"{pid:42s} {img.size[0]}x{img.size[1]:<5} "
              f"{gen.shape[0]:5d} tok {secs:6.1f}s{'  TRUNCATED' if truncated else ''}",
              flush=True)

    meta = {"model": MODEL, "dpi": args.dpi, "longest": args.longest,
            "max_new_tokens": args.max_new_tokens,
            "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2),
            "runs": runs}
    with open(os.path.join(OUT, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    n_trunc = sum(1 for r in runs if r["truncated"])
    print(f"\n{len(runs)} posters, peak VRAM {meta['peak_vram_gb']} GB, "
          f"{n_trunc} truncated -> {OUT}")


if __name__ == "__main__":
    main()
