#!/usr/bin/env python3
"""Two questions, one model load, flushed per result.

Q1 Generation settings. We ran greedy (do_sample=False). The shipped
   generation_config is do_sample=True, temperature=0.2, top_p=0.9. Greedy is a
   known cause of OCR repetition loops. Does honoring the config stop
   isporeu2023 looping? (loop = hits the token cap with high duplicate-line
   fraction). Modest 3072 cap so a loop is detected fast, not run to 8192.

Q2 RoPE resolution ceiling. The vision RoPE table is 110x110
   (image_size//patch_size). Rebuilding it for a larger image_size lets a bigger
   render run at all -- does the text stay coherent (extrapolation), and does
   NTK theta-scaling help (interpolation)? Tested on 17268692, the most starved
   poster (26 DPI at 1540).
"""
import sys, time
import torch

MODEL = "lightonai/LightOnOCR-2-1B"
A = "/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/json_schema/manual_poster_annotation"
LOOP_PDF = f"{A}/isporeu2023ee359130949-pdf/isporeu2023ee359130949-pdf.pdf"
RES_PDF = f"{A}/17268692/17268692.pdf"

import pypdfium2 as pdfium


def render(pdf, longest):
    page = pdfium.PdfDocument(pdf)[0]
    s = longest / max(page.get_width(), page.get_height())
    return page.render(scale=s).to_pil().convert("RGB")


def out(s):
    print(s, flush=True)


from transformers import LightOnOcrForConditionalGeneration, LightOnOcrProcessor
from transformers.models.pixtral.modeling_pixtral import PixtralRotaryEmbedding
model = LightOnOcrForConditionalGeneration.from_pretrained(MODEL, dtype=torch.bfloat16).to("cuda").eval()
torch.manual_seed(0)
out("model loaded")


def infer(img, gen, proc):
    conv=[{"role":"user","content":[{"type":"image","image":img}]}]
    inp=proc.apply_chat_template(conv,add_generation_prompt=True,tokenize=True,return_dict=True,return_tensors="pt")
    inp={k:(v.to("cuda",torch.bfloat16) if v.is_floating_point() else v.to("cuda")) for k,v in inp.items()}
    t=time.time()
    try:
        with torch.inference_mode():
            o=model.generate(**inp, **gen)
    except Exception as e:
        return None, f"FAILED {type(e).__name__}: {str(e)[:70]}", 0
    g=o[0, inp["input_ids"].shape[1]:]
    return g, proc.decode(g, skip_special_tokens=True), time.time()-t


def report(txt, g, secs, cap):
    lines=[l for l in txt.splitlines() if l.strip()]
    dup=1-len(set(lines))/max(len(lines),1)
    head=next((l for l in lines if len(l)>25), txt[:80])[:100]
    loop = "  <-LOOP" if (g.shape[0]>=cap and dup>0.3) else ""
    return f"{g.shape[0]}tok {secs:.0f}s dup={dup:.2f}{loop} | {head!r}"


out("\n### Q1: generation settings on the looping poster (isporeu2023)")
proc = LightOnOcrProcessor.from_pretrained(MODEL, size={"longest_edge":1540})
img = render(LOOP_PDF, 1540)
for name, gen in [
    ("greedy (what we ran)", dict(do_sample=False, max_new_tokens=3072)),
    ("card: temp0.2 top_p0.9", dict(do_sample=True, temperature=0.2, top_p=0.9, max_new_tokens=3072)),
    ("greedy + rep_penalty1.15", dict(do_sample=False, repetition_penalty=1.15, max_new_tokens=3072)),
]:
    g, txt, secs = infer(img, gen, proc)
    out(f"  {name:26s} {report(txt, g, secs, 3072)}")

out("\n### Q2: RoPE past 1540 on the most starved poster (17268692, 26 DPI)")
GEN = dict(do_sample=True, temperature=0.2, top_p=0.9, max_new_tokens=4096)
vt = model.model.vision_tower if hasattr(model.model, "vision_tower") else model.vision_tower


def set_rope(image_size, theta=10000):
    vt.config.image_size = image_size
    vt.config.rope_theta = theta
    if hasattr(vt.config, "rope_parameters"):
        vt.config.rope_parameters["rope_theta"] = theta
    emb = PixtralRotaryEmbedding(vt.config, device="cuda")
    # find and replace the rotary module
    for name, mod in vt.named_modules():
        if isinstance(mod, PixtralRotaryEmbedding):
            parent = vt
            *path, last = name.split(".")
            for p in path:
                parent = getattr(parent, p)
            setattr(parent, last, emb)
            return name
    return "NOT FOUND"


loc = None
for n, m in vt.named_modules():
    if isinstance(m, PixtralRotaryEmbedding):
        loc = n
out(f"  rotary module at vision_tower.{loc}")

# baseline at 1540, stock
proc = LightOnOcrProcessor.from_pretrained(MODEL, size={"longest_edge":1540})
g, txt, secs = infer(render(RES_PDF, 1540), GEN, proc)
out(f"  1540 stock                 {report(txt, g, secs, 4096)}")

for longest, theta_mode in [(2464, 1.0), (2464, "ntk"), (3080, "ntk")]:
    side = longest  # image_size = render longest (square-ish patch grid cap)
    theta = 10000 * (longest/1540) if theta_mode=="ntk" else 10000
    set_rope(image_size=longest, theta=theta)
    proc = LightOnOcrProcessor.from_pretrained(MODEL, size={"longest_edge":longest})
    g, txt, secs = infer(render(RES_PDF, longest), GEN, proc)
    tag = f"{longest} rebuild" + (f" NTKtheta{longest/1540:.1f}x" if theta_mode=="ntk" else " extrapolate")
    out(f"  {tag:26s} {report(txt, g, secs, 4096) if g is not None else txt}")
