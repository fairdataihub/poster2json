# Track B action plan: xy_cut banner reading order

## Objective

Fix the reading order of the poster banner (title, author byline, affiliation
legend) in `poster2json/xy_cut.py` so the affiliation corrector, whose logic is
now correct, fires on the extracted text as well as it does on the ideal
annotation. This is the structural half of the calibration and it touches every
poster's reading order, so regression control is the first-class concern.

## Success criteria (all measured by `calibration/reading_order_eval.py`)

1. The three ORDER-GAP posters reach `genOK = 1.00`: **gasimova, isporeu2023,
   8228476**. (Their `refOK` is already 1.00; only reading order blocks them.)
2. No end-to-end PASS regresses to fail on the currently-passing numbered
   posters (10890106, 15963941, 16083265, 17268692, 4564017, 5128504).
3. Corpus reading-order averages do not drop: `rField >= 0.727`,
   `rGlobal >= 0.835` (equal-weight per-field and global). Ideally `rField`
   rises, since the banner is a weighted field.
4. Full test suite stays green.

## Guard baselines (as of the Track A commits)

- `calibration/baselines/after_track_a.json` is the reference scoreboard.
- Corpus avg: w=0.976, rGlobal=0.835, rField=0.727.
- AFFIL: 6/13 end-to-end, 9/13 corrector-logic OK, 14/21 acceptable.
- Re-run `python reading_order_eval.py` after every xy_cut change and diff the
  per-poster w / rGlobal / rField / genOK against this file. Any drop is a
  regression to explain or revert before proceeding.

## Per-poster failure analysis (current xy_cut output)

**gasimova** (banner scramble). xy_cut emits:
```
## Clinical Dataset Structure: ... Datasets
## Patel HUB
1 , Sanjay Soundarajan 1 , Nayoon Gim 2,3,4 , ... , Gasimova Bhavesh
Aydan
## Background
## Results
1 FAIR Data Innovations Hub, ... 5 John F. Hardesty ...
```
The full-width top band is vsplit into body columns: the byline is fragmented and
reordered ("Patel HUB", "Gasimova Bhavesh", "Aydan" split), and the section
headers "## Background" / "## Results" (tops of the left and right body columns)
are emitted *between* the byline and the affiliation legend. `_banner_region`
stops at the first "## " header, so it never reaches the legend.

**isporeu2023** (byline separated from legend). The affiliation legend is near the
top, but the author byline is emitted elsewhere in the reading order, so
`_banner_region` (which starts at the lead author) walks away from the legend
instead of onto it.

**8228476** (RTL, numbers detached). Hebrew/bidi poster. Authors are one per line
with emails, and the affiliation legend arrives without its leading markers
("Technion - Israel Institute of Technology", "The Open University of Israel"
with no numbers), so there is no numbered legend to parse. This is the hardest of
the three and may need bidi-aware handling, not just banner promotion.

## Root cause

The XY-cut vsplits the whole page into columns first, because the body column
gutters extend upward to near the top of the page. The top full-width banner band
(title, byline, affiliation legend) therefore gets partitioned into the columns
and interleaved with the tops of the body sections, instead of being read as one
contiguous top-to-bottom band before the columns.

`xy_cut.py` already has the two analogous fixes for other bands:
- `_promote_spanning_leaves`: pulls a wide leaf out of a vsplit and re-wraps.
- `_merge_bottom_region`: for `bbox[1] > page_height * 0.65`, reads the bottom
  band across full width (Conclusion / References span columns).

The banner is the missing **top** analog.

## Candidate approaches (ordered by leverage and risk)

### A. Top-spanning-band promotion (primary, structural)
Mirror `_merge_bottom_region` for the top of the page: when a top-level vsplit
begins in the top band (`bbox[1] < page_height * TOP_BAND`, start ~0.22), reorder
its children so the wide/spanning rows (title, byline, affiliation legend) are
read top-to-bottom across the full width before the narrower column children.
Reuse the `_promote_spanning_leaves` wide-leaf detection (`> 0.7 * page_width`).
Expected to fix gasimova directly, and isporeu2023 if it re-unites byline with
legend. New constant `TOP_BAND` (default ~0.22), swept on the corpus.

### B. Constant sweeps (supporting)
`MIN_GAP_AREA`, `SPLIT_GAP_SLACK`, `MIN_CHUNK_WIDTH`, `MIN_GAP_SIZE`,
`BASELINE_RANGE`. Likely insufficient alone (the banner problem is topological,
not a threshold), but run `--sweep` on each to check for free wins and to confirm
A does not sit on a fragile threshold edge. Also lift the three hardcoded
heuristics to module constants so they are sweepable: single-line guard
`1.5 * avg_fs`, spanning-promote `0.7 * page_width`, bottom-merge
`0.65 * page_height`.

### C. Corrector-side banner fallback (cheap safety net, may fix isporeu2023 alone)
Independent of xy_cut: when `_banner_region` from the lead author does not yield a
parseable legend, also try building the banner from the top-of-text region (first
N lines) or search the whole pre-first-body-section span for the numbered legend.
Lower risk than editing xy_cut and may recover isporeu2023 without touching
reading order. Consider doing this first as a quick win, then A for gasimova.

### D. Bidi/RTL handling for 8228476 (separate sub-track)
The Hebrew poster needs the affiliation markers preserved through bidi
extraction. Treat as its own investigation after A and C; do not let it block the
Latin-script wins. Note `_add_bidi_markers` already exists in extract.py.

## Iteration protocol

1. Snapshot: `python reading_order_eval.py --save baselines/before_change.json`.
2. Make one change (approach A, or one swept constant).
3. `python reading_order_eval.py` and eyeball genOK on the 3 targets plus the
   per-poster rField/rGlobal vs `after_track_a.json`.
4. If a target improves and nothing regresses, run the full pytest suite, then
   commit. If anything regresses, revert or narrow the change.
5. For structural changes, also spot-check the raw banner text with
   `/tmp/trace_order.py` on the 3 targets and 3 passing posters.

Keep each xy_cut change small and independently measured; the reading order feeds
every downstream field, so a broad change with a net-positive average can still
silently break individual posters.

## Suggested order of work

1. Approach C (corrector banner fallback) as a low-risk attempt at isporeu2023.
2. Approach A (top-spanning-band promotion) for gasimova, with the full
   no-regression sweep.
3. Approach B sweeps to confirm robustness and pick up any free gains.
4. Approach D (bidi) for 8228476 as a separate, later effort.

## Out of scope / accepted non-goals

- 6724771: abstract prose bleeds into the trailing affiliation with no clean
  boundary (a corrector-side limit, tracked in Track A notes, not reading order).
- 42: annotation lists 6 authors, byline has 3 (data mismatch).
- 4519718: last author has no marker on the poster (genuine ambiguity).
- 4560930: partial (0.67); revisit after A/C.
