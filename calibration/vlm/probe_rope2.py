#!/usr/bin/env python3
"""Can we lift the 1540px vision ceiling by rebuilding the Pixtral RoPE table?

The table is max_patches_per_side = image_size//patch_size = 110. A larger image
asserts. Rebuild it for a bigger image_size and the render runs; the question is
whether the LEARNED weights still produce coherent text at never-trained
positions (extrapolation) and whether NTK theta-scaling (interpolation) helps.

Module lives at model.vision_encoder.patch_positional_embedding.
Tested on 17268692 (26 DPI at 1540, the most resolution-starved poster) so any
gain from real added detail shows up.
"""
import sys, time
import torch

MODEL = "lightonai/LightOnOCR-2-1B"
PDF = ("/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/json_schema/"
       "manual_poster_annotation/17268692/17268692.pdf")

import pypdfium2 as pdfium
_page = pdfium.PdfDocument(PDF)[0]


def render(longest):
    s = longest / max(_page.get_width(), _page.get_height())
    return _page.render(scale=s).to_pil().convert("RGB")


def out(s): print(s, flush=True)


from transformers import LightOnOcrForConditionalGeneration, LightOnOcrProcessor
from transformers.models.pixtral.modeling_pixtral import PixtralRotaryEmbedding
model = LightOnOcrForConditionalGeneration.from_pretrained(MODEL, dtype=torch.bfloat16).to("cuda").eval()
enc = model.model.vision_encoder
GEN = dict(do_sample=True, temperature=0.2, top_p=0.9, max_new_tokens=4096)
torch.manual_seed(0)
out("loaded; rope at model.vision_encoder.patch_positional_embedding")


def set_rope(image_size, theta):
    c = enc.patch_positional_embedding.config
    c.image_size = image_size
    c.rope_theta = theta
    if hasattr(c, "rope_parameters"):
        c.rope_parameters["rope_theta"] = theta
    dev = next(enc.parameters()).device
    emb = PixtralRotaryEmbedding(c)
    # move every registered buffer (inv_freq, original_inv_freq) onto the device
    emb = emb.to(dev)
    emb.inv_freq = emb.inv_freq.to(dev)
    emb.original_inv_freq = emb.original_inv_freq.to(dev)
    enc.patch_positional_embedding = emb


def go(longest, image_size, theta, tag):
    if image_size is not None:
        set_rope(image_size, theta)
    proc = LightOnOcrProcessor.from_pretrained(MODEL, size={"longest_edge": longest})
    img = render(longest)
    conv=[{"role":"user","content":[{"type":"image","image":img}]}]
    inp=proc.apply_chat_template(conv,add_generation_prompt=True,tokenize=True,return_dict=True,return_tensors="pt")
    inp={k:(v.to("cuda",torch.bfloat16) if v.is_floating_point() else v.to("cuda")) for k,v in inp.items()}
    t=time.time()
    try:
        with torch.inference_mode():
            o=model.generate(**inp, **GEN)
    except Exception as e:
        out(f"  {tag:30s} FAILED {type(e).__name__}: {str(e)[:60]}"); return
    g=o[0, inp["input_ids"].shape[1]:]
    txt=proc.decode(g, skip_special_tokens=True)
    lines=[l for l in txt.splitlines() if l.strip()]
    dup=1-len(set(lines))/max(len(lines),1)
    words=len(txt.split())
    head=next((l for l in lines if len(l)>25), txt[:80])[:95]
    out(f"  {tag:30s} {img.size[0]}x{img.size[1]} {g.shape[0]}tok {time.time()-t:.0f}s "
        f"words={words} dup={dup:.2f}\n      {head!r}")


# baseline (stock 1540 table)
go(1540, None, None, "1540 stock")
# extrapolation: bigger table, same theta
go(2464, 2464, 10000, "2464 rebuild (extrapolate)")
# NTK interpolation: bigger table + theta scaled by side ratio
go(2464, 2464, int(10000 * (2464/1540)), "2464 rebuild + NTK theta1.6x")
go(3080, 3080, int(10000 * (3080/1540)), "3080 rebuild + NTK theta2.0x")
# reset and re-confirm baseline unharmed
go(1540, 1540, 10000, "1540 rebuilt (sanity)")
