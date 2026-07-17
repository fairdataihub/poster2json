#!/usr/bin/env python3
"""Effective DPI each poster gets at LightOnOCR-2's fixed 1540px longest edge.

The model card's "200 DPI, longest dimension 1540px" is written for pages. A4
is 11.7in tall, so 1540px over it is ~132 DPI and the advice is self-consistent.
A conference poster is three to four feet: the same 1540px spreads far thinner,
and the vision tower's image_size=1540 is a hard ceiling (raising it indexes off
the Pixtral RoPE table and asserts), so there is no knob to compensate.
"""
import glob
import os

import pypdfium2 as pdfium

CORPUS = ("/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/"
          "json_schema/manual_poster_annotation")
EXTRA = [("gasimova(oos)", "/storage/poster-work/gasimova.pdf")]
LONGEST = 1540

items = []
for d in sorted(glob.glob(os.path.join(CORPUS, "*"))):
    pdf = glob.glob(os.path.join(d, "*.pdf"))
    if os.path.isdir(d) and pdf:
        items.append((os.path.basename(d), pdf[0]))
items.extend([(p, f) for p, f in EXTRA if os.path.exists(f)])

print(f"{'poster':40s} {'pt (w x h)':>15s} {'inches':>13s} {'eff DPI':>8s}")
rows = []
for pid, path in items:
    page = pdfium.PdfDocument(path)[0]
    w, h = page.get_width(), page.get_height()
    long_in = max(w, h) / 72.0
    dpi = LONGEST / long_in
    rows.append(dpi)
    print(f"{pid:40s} {int(w):6d} x {int(h):<6d} "
          f"{w / 72:5.1f} x {h / 72:<5.1f} {dpi:8.0f}")

print(f"\nA4 for reference (8.3 x 11.7in) at {LONGEST}px -> {LONGEST / 11.7:.0f} DPI")
print(f"poster mean {sum(rows) / len(rows):.0f} DPI, min {min(rows):.0f}, "
      f"max {max(rows):.0f}")
print(f"\n{sum(1 for d in rows if d < 80)}/{len(rows)} posters get under 80 DPI.")
