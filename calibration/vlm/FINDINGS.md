# Findings: LightOnOCR-2-1B vs pdfplumber + xy_cut (2026-07-16)

First run, 19 corpus posters + gasimova. Model `lightonai/LightOnOCR-2-1B`,
200 DPI, longest side 1540px, bf16, greedy. **3.0 GB peak VRAM, ~60s/poster**
on one GPU alongside the running ollama/vLLM services.

## Verdict

**Not a drop-in replacement — it fabricates identifiers. But it reads poster
structure markedly better than we do, and that is worth having.**

Do not read the headline averages alone; they say the opposite of what matters.

## It reads better

| metric | pdfplumber + xy_cut | LightOnOCR-2-1B |
|---|---|---|
| `w` (word capture) | **0.976** | 0.936 |
| `rGlobal` | **0.835** | 0.788 |
| `rField` (length-normalized) | 0.741 | **0.765** |

rField, the metric we treat as the headline, favours the VLM. Head-to-head it
wins 12 of 19. On the **banner** — `authors+affiliations`, the field that cost
this project Track A, Track B and approach A — it wins **15 of 19** (2 ties, 2
losses), mean **+0.179**:

    gasimova   0.742 -> 1.000     4607450   0.244 -> 0.909
    4560930    0.600 -> 1.000     aysaekanger 0.429 -> 0.880
    4446908    0.667 -> 1.000     10890106  0.600 -> 0.925
    42         0.640 -> 0.913     AISec     0.696 -> 0.929

It gets these right for free, from pixels, with no xy_cut, no
`_flatten_top_band`, no superscript-row merge, no marker parsing. It also
returns wrapped titles in one piece (10890106, which our block grouper still
splits) and emits its own markdown headers.

## It invents identifiers

This is disqualifying for a metadata pipeline and ROUGE cannot see it. Exact
strings checked against the human transcription (`fidelity_check.py`):

| extractor | kind | recovered | missed | **invented** |
|---|---|---|---|---|
| pdfplumber | orcid | 9 | 1 | **0** |
| pdfplumber | doi | 10 | 0 | **0** |
| pdfplumber | email | 20 | 2 | 1* |
| LightOnOCR | orcid | 4 | 6 | **6** |
| LightOnOCR | doi | 7 | 3 | **2** |
| LightOnOCR | email | 18 | 4 | 2 |

\* not a fabrication: the poster prints `1aperdomo@iac.es` where the `1` is a
superscript affiliation marker glued to the address. Our extractor correctly
splits it; the checker counts the clean address as "not in the reference".

**6 of 10 ORCIDs are wrong.** Actual corruptions:

    DOI    10.1101/2024.08.13.24311948  ->  10.1105/2024.08.13.24311348
    DOI    10.1007/978-3-031-02170-1    ->  10.1007/978-3-031-02701-1
    email  joneilliii@sdsu.edu          ->  joneilliii@sdssu.edu
    ORCID  0000-0002-2862-7302          ->  0000-0002-3982-7202

These are not near-misses, they are different identifiers. A corrupted ORCID
attributes a poster to another researcher; a corrupted DOI resolves to the
wrong paper or nowhere. Silent, plausible, and worse than no value at all.
A text-layer extractor cannot do this: it can only miss.

The reason is structural, not a tuning problem. The VLM re-renders every glyph
from pixels, so an identifier is a prediction. pdfplumber copies bytes the
author embedded.

## Other failure modes seen

- **isporeu2023** is a genuine failure: it dropped 4 of 8 authors, mis-assigned
  markers (Ciccarone 3 -> 2, Schlichting 4 -> 1), read "Delta Hat Ltd" as
  "Delta et Ltd", and hallucinated 3 ORCIDs. It also never terminated: 6144
  tokens truncated, and at 16384 it was STILL going (471s), emitting HTML
  tables. Our pipeline scores 0.849 rField on this poster; the VLM 0.509.
- **8228476** (RTL Hebrew) is worse under the VLM too (rField 0.503 vs 0.692),
  so approach D is not solved by switching extractor.
- Superscripts come back as LaTeX (`$^{1,2}$`). Harmless for raw-text scoring
  (`_alpha()` reduces it to `12`, matching the reference's NFKD-normalized
  `¹˒²`) but the affiliation corrector would need to read it.

## Where this points

A hybrid is the obvious shape, and the numbers support it: **take structure
from the VLM, take exact strings from the text layer.** The VLM is good at
precisely what xy_cut finds hard (which text belongs to which line, in what
order) and bad at precisely what pdfplumber gets for free (reproducing a string
exactly). They fail in opposite directions.

Concretely, worth testing next:

1. VLM output as the reading-order source, then verify/replace every ORCID,
   DOI and email against the PDF text layer — reject any identifier the text
   layer does not contain verbatim. This bounds the fabrication to zero while
   keeping the banner gains.
2. Or narrower and safer: keep our pipeline, and use the VLM only for the
   banner region, where it wins by +0.179 and where identifiers can be
   cross-checked against a small, well-defined slice of text.
3. Re-run with `--dpi 300` before concluding on recall; `w` is 0.936 vs our
   0.976 and some of that gap may be resolution, not the model.

Do NOT wire this into the pipeline on the strength of rField=0.765.
