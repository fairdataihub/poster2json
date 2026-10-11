"""Unit tests for deterministic caption extraction (poster2json.captions).

Pages are built from synthetic chars, rects and images and pushed through the
same steps the pdfplumber engine uses (XY-cut leaves, word lines, blocks,
figure masks), so the tests cover geometry and not only the rules.
"""

from poster2json import captions as cap
from poster2json import layout_blocks as lb
from poster2json import xy_cut
from poster2json.extract import _lines_to_blocks

PAGE_W, PAGE_H = 600.0, 800.0
BODY = 12.0


def _chars(text, x, top, size, font="Arial"):
    out = []
    for t in text:
        out.append({"text": t, "x0": x, "x1": x + size * 0.5, "top": top,
                    "bottom": top + size, "size": size, "fontname": font})
        x += size * 0.5
    return out


def lines(texts, x, top, size, font="Arial", leading=1.25):
    """One char line per text, stacked downward."""
    out = []
    for k, t in enumerate(texts):
        out += _chars(t, x, top + k * size * leading, size, font)
    return out


def para(n, x, top, size, width_chars=50, font="Arial", word="alpha beta gamma delta"):
    text = (word + " ") * 100
    rows = [text[i * width_chars:(i + 1) * width_chars].strip() for i in range(n)]
    return lines(rows, x, top, size, font)


def rect(x0, top, x1, bottom):
    return {"x0": x0, "x1": x1, "top": top, "bottom": bottom}


def image(x0, top, x1, bottom):
    return rect(x0, top, x1, bottom)


def run(chars, images=(), shapes=()):
    """Blocks, regions and captions of a synthetic page."""
    leaves, regions = xy_cut.chars_to_leaves(chars, page_width=PAGE_W, page_height=PAGE_H)
    word_lines, leaf_ids = lb.build_word_lines(
        leaves, 3.0, lb.body_font_size(chars), regions=regions,
        spaces=[c for c in chars if c["text"] == " "])
    all_words = [w for ln in word_lines for w in ln]
    masks = lb.build_figure_masks(list(images), list(shapes), PAGE_W, PAGE_H, BODY)
    body_lines, body_ids, lab_lines, lab_ids, body_order, lab_order = lb.split_figure_words(
        word_lines, leaf_ids, masks, BODY)
    blocks = _lines_to_blocks(body_lines, leaf_ids=body_ids, orders=body_order)
    for b in _lines_to_blocks(lab_lines, leaf_ids=lab_ids, orders=lab_order) if lab_lines else []:
        b["fig"] = True
        blocks.append(b)
    found = cap.find_captions(blocks, cap.regions_from_masks(masks, BODY), all_words,
                              BODY, PAGE_H)
    return blocks, found


def body_text():
    """Two body paragraphs that fix the body font at 12 pt, far from the figure."""
    return para(8, 50, 520, BODY, 60) + para(8, 330, 520, BODY, 40)


# ------------------------------------------------------------------ labels

def test_match_label_variants():
    assert cap.match_label("Figure 2. A) first")["kind"] == "figure"
    assert cap.match_label("Fig. 3: x")["kind"] == "figure"
    assert cap.match_label("TABLE 1: x")["kind"] == "table"
    assert cap.match_label("Table S2 | x")["has_sep"]
    assert cap.match_label("Figure: most observed")["has_sep"]
    assert cap.match_label("The figure shows") is None
    assert not cap.match_label("Figure 2 shows the result")["has_sep"]


def test_split_inline_labels():
    parts = cap.split_inline_labels("Figure 1: Security categories Figure 2: Dataset creation process")
    assert len(parts) == 2 and parts[1].startswith("Figure 2")
    # a reference inside a sentence is not a new caption
    assert len(cap.split_inline_labels("Figure 1: Results are shown (see Figure 2: panel B)")) == 1


# --------------------------------------------------------- caption finding

def test_labeled_caption_below_image():
    chars = body_text() + lines(["Figure 1. Mean response of treated cells over time."],
                                60, 306, 9.0)
    blocks, found = run(chars, images=[image(50, 100, 350, 300)])
    assert len(found) == 1
    assert found[0]["kind"] == "figure"
    assert found[0]["text"].startswith("Figure 1. Mean response")
    assert found[0]["label"] == "Figure 1."
    assert found[0]["source"] == "label"


def test_unlabeled_caption_below_image():
    chars = body_text() + lines(
        ["Mean response of treated cells over time in the first experiment."], 60, 306, 9.0)
    blocks, found = run(chars, images=[image(50, 100, 350, 300)])
    assert len(found) == 1
    assert found[0]["source"] == "geometry"
    assert found[0]["kind"] == "figure"
    assert found[0]["label"] is None


def test_caption_beside_image():
    chars = body_text() + lines(
        ["Response curves of", "treated cells over time", "in the first experiment",
         "with standard errors."], 262, 150, 9.0)
    blocks, found = run(chars, images=[image(50, 100, 255, 300)])
    assert len(found) == 1
    assert found[0]["text"].startswith("Response curves of treated cells")
    assert "standard errors" in found[0]["text"]


def test_caption_grows_across_blocks():
    # a bold label line breaks the block; the plain text below continues it
    chars = (body_text()
             + lines(["Figure 2."], 60, 306, 9.0, font="Arial-Bold")
             + lines(["A) Response of treated cells over time. B) Response of",
                      "control cells over the same period."], 60, 317, 9.0))
    blocks, found = run(chars, images=[image(50, 100, 350, 300)])
    assert len(found) == 1
    assert found[0]["text"].startswith("Figure 2. A) Response")
    assert found[0]["text"].endswith("same period.")
    assert len(found[0]["blocks"]) == 2


def test_two_labeled_captions_in_one_block():
    chars = body_text() + lines(
        ["Figure 1: Security categories of the dataset Figure 2: Dataset creation process"],
        50, 306, 9.0)
    blocks, found = run(chars, images=[image(50, 100, 350, 300)])
    assert [c["text"][:8] for c in found] == ["Figure 1", "Figure 2"]


def test_figure_internal_text_is_not_a_caption():
    # vector figure: axes and bars, tick labels inside, axis title below
    shapes = [rect(80, 120, 82, 280), rect(80, 278, 340, 280)]
    shapes += [rect(100 + 40 * k, 280 - 20 * (k + 1), 120 + 40 * k, 280) for k in range(6)]
    ticks = []
    for k in range(6):
        ticks += lines([str(k * 10)], 100 + 40 * k, 284, 8.0)
    chars = body_text() + ticks + lines(["Time (days)"], 190, 296, 8.0)
    blocks, found = run(chars, shapes=shapes)
    assert found == []


def test_table_caption_above_grid():
    cells = []
    chars = body_text()
    for r in range(4):
        for c in range(3):
            x0 = 60 + 90 * c
            top = 150 + 22 * r
            cells.append(rect(x0, top, x0 + 90, top + 22))
            chars += lines([str(10 * r + c + 1)], x0 + 10, top + 6, 9.0)
    chars += lines(["Table 1. Baseline characteristics of the participants."], 60, 128, 9.0)
    blocks, found = run(chars, shapes=cells)
    assert len(found) == 1
    assert found[0]["kind"] == "table"
    assert found[0]["text"].startswith("Table 1.")


def test_unlabeled_caption_above_grid_is_a_table():
    cells = []
    chars = body_text()
    for r in range(4):
        for c in range(3):
            x0 = 60 + 90 * c
            top = 150 + 22 * r
            cells.append(rect(x0, top, x0 + 90, top + 22))
            chars += lines([str(10 * r + c + 1)], x0 + 10, top + 6, 9.0)
    chars += lines(["Baseline characteristics of the study participants by group."], 60, 128, 9.0)
    blocks, found = run(chars, shapes=cells)
    assert len(found) == 1
    assert found[0]["kind"] == "table"
    assert found[0]["source"] == "geometry"


def test_full_size_body_paragraph_near_figure_is_not_a_caption():
    # a long paragraph at body size right under the image is running text
    chars = body_text() + para(14, 50, 306, BODY, 60)
    blocks, found = run(chars, images=[image(50, 100, 350, 300)])
    assert found == []


def test_body_paragraph_followed_by_more_text_is_not_a_caption():
    chars = (body_text()
             + para(3, 50, 306, BODY, 60) + para(3, 50, 368, BODY, 60))
    blocks, found = run(chars, images=[image(50, 100, 350, 300)])
    assert found == []


def test_footer_and_funding_text_is_not_a_caption():
    chars = body_text() + lines(
        ["This research was supported by a grant from the national agency."], 60, 306, 9.0)
    blocks, found = run(chars, images=[image(50, 100, 350, 300)])
    assert found == []


# ------------------------------------------------------ merging with model

def test_remove_caption_spans_exact_and_near():
    c = "Figure 1. Mean response of treated cells over time in the first experiment."
    text = "Intro text here. " + c + " More body text follows."
    out = cap.remove_caption_spans(text, [c])
    assert "Mean response" not in out and "Intro text here." in out and "More body" in out
    # label dropped by the model, one word changed
    near = ("Before. Mean response of treated cells over time in the second experiment."
            " After.")
    out = cap.remove_caption_spans(near, [c])
    assert "Mean response" not in out and "Before." in out and "After." in out
    # a different sentence stays
    other = "The response of treated cells was measured twice a day."
    assert cap.remove_caption_spans(other, [c]) == other


def test_merge_captions_deterministic_wins_and_grounded_model_caption_kept():
    det = [{"kind": "figure", "text": "Figure 1. Mean response of treated cells over time."}]
    raw = ("Dose curves of the reference compound across all sites were fitted "
           "jointly for the whole panel")
    out = cap.merge_captions(
        det,
        ["Mean response of treated cells over time.",            # covered
         "Dose curves of the reference compound across all sites",  # grounded, new
         "Invented caption about something never printed anywhere"],  # not grounded
        [], raw)
    assert out["figure"][0].startswith("Figure 1.")
    assert out["figure"][1].startswith("Dose curves")
    assert len(out["figure"]) == 2 and out["table"] == []


# ------------------------------------------------------- postprocess hook

def test_postprocess_writes_deterministic_captions_and_cleans_sections():
    from poster2json.extract import _postprocess_json
    capt = "Figure 1. Mean response of treated cells over time in the first experiment."
    raw = ("Results\nCells responded within a day.\n[Figure caption 1 extracted]\n"
           "Controls stayed flat for the whole period.")
    data = {
        "titles": [{"title": "T"}],
        "content": {"sections": [{
            "sectionTitle": "Results",
            "sectionContent": "Cells responded within a day. " + capt
                              + " [Figure caption 1 extracted] Controls stayed flat for the whole period.",
        }]},
        "imageCaptions": [{"id": "fig1", "caption": "Mean response of treated cells over time"}],
        "tableCaptions": [],
    }
    out = _postprocess_json(data, raw_text=raw, det_captions=[
        {"kind": "figure", "text": capt, "label": "Figure 1.", "source": "label"}])
    assert out["imageCaptions"] == [{"id": "fig1", "caption": capt}]
    sec = out["content"]["sections"][0]["sectionContent"]
    assert "Mean response" not in sec and "caption 1" not in sec
    assert "Cells responded" in sec and "Controls stayed flat" in sec
    # no ghost section from the marker line
    assert len(out["content"]["sections"]) == 1


def test_column_wide_paragraph_under_narrow_image_is_not_a_caption():
    # body-size text wider than the figure it sits under is running text
    chars = body_text() + para(5, 50, 306, BODY, 56)
    blocks, found = run(chars, images=[image(50, 100, 300, 300)])
    assert found == []
