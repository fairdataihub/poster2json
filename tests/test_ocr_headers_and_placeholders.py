"""Vision OCR header marking and prompt-template placeholder cleanup.

Both come from an image poster (a PNG with no printed authors) that came back
with every section merged into one and a "LastName, FirstName" creator. The OCR
text below mirrors what Qwen2-VL returned for it.
"""

from poster2json.extract import (
    _drop_placeholder_affiliations,
    _is_placeholder,
    _is_placeholder_person,
    _mark_ocr_headers,
    _postprocess_json,
)

OCR = """The transfer of microplastics from algae fertilizer into crops

Introduction
- Research question: Are microplastics being transferred into crops?
- Figure 1: Map of Mount Desert Rock (MDR)

Methods
- Algae was collected in glass jars from three tidal zones

Results
- In algae samples, microplastic fibers were the most common.

Types of Microplastics
- FRAGMENTS
- This picture shows a microplastic fragment.

Figure 3. Fully grown arugula plants

This sentence stands alone on its own line.

Acknowledgements
- Thank you so much to my mentor!"""


def _headers(text):
    return [ln[3:] for ln in text.splitlines() if ln.startswith("## ")]


def test_ocr_headers_are_marked_like_pdfplumber():
    marked = _mark_ocr_headers(OCR)
    assert _headers(marked) == [
        "Introduction", "Methods", "Results", "Types of Microplastics", "Acknowledgements",
    ]


def test_title_bullets_sentences_and_captions_are_not_headers():
    marked = _mark_ocr_headers(OCR)
    first = marked.splitlines()[0]
    assert first == "The transfer of microplastics from algae fertilizer into crops"
    assert "- FRAGMENTS" in marked
    assert "## Figure 3. Fully grown arugula plants" not in marked
    assert "## This sentence stands alone on its own line." not in marked


def test_markdown_and_bold_headings_are_normalized():
    text = "Poster Title\n\n### Results\ntext here\n**Methods:**\nmore text"
    assert _headers(_mark_ocr_headers(text)) == ["Results", "Methods"]


def test_title_heading_marker_is_removed_not_turned_into_a_section():
    text = "# Poster Title\n\nIntroduction\nbody"
    marked = _mark_ocr_headers(text)
    assert marked.splitlines()[0] == "Poster Title"
    assert _headers(marked) == ["Introduction"]


def test_marking_is_idempotent():
    once = _mark_ocr_headers(OCR)
    assert _mark_ocr_headers(once) == once


def test_short_line_between_blank_lines_is_not_a_header():
    # neither line is directly followed by content
    assert _headers(_mark_ocr_headers("Title\n\nBody text here\n\nLiterature Cited")) == []


# --- placeholders ------------------------------------------------------------

def test_template_creator_is_a_placeholder_person():
    assert _is_placeholder_person({
        "name": "LastName, FirstName", "givenName": "FirstName", "familyName": "LastName"})
    assert _is_placeholder_person({"name": "Last Name, First Name"})
    assert _is_placeholder_person({"name": "LASTNAME,FIRSTNAME"})


def test_real_people_are_not_placeholders():
    assert not _is_placeholder_person({"name": "Smith, Jane", "givenName": "Jane",
                                       "familyName": "Smith"})
    # one real field is enough to keep the person
    assert not _is_placeholder_person({"name": "Smith, Jane", "givenName": "FirstName"})
    assert not _is_placeholder_person({})


def test_template_affiliations_are_dropped_real_ones_kept():
    p = {"affiliation": ["Institution Name", "University of Maine", {"name": "Institution"}]}
    _drop_placeholder_affiliations(p)
    assert p["affiliation"] == ["University of Maine"]
    s = {"affiliation": "Institution Name"}
    _drop_placeholder_affiliations(s)
    assert s["affiliation"] == []


def test_postprocess_drops_template_creator_subjects_description_and_section():
    out = _postprocess_json({
        "creators": [{"name": "LastName, FirstName", "givenName": "FirstName",
                      "familyName": "LastName", "affiliation": ["Institution Name"]}],
        "titles": [{"title": "The transfer of microplastics"}],
        "subjects": [{"subject": "keyword1"}, {"subject": "microplastics"},
                     {"subject": "Keyword 2"}],
        "descriptions": [{"description": "A 3-4 sentence summary of the full poster..."}],
        "content": {"sections": [
            {"sectionTitle": "Methods",
             "sectionContent": "Full verbatim text of this section from the poster..."},
            {"sectionTitle": "Results",
             "sectionContent": "Arugula grown with algae had five times more microplastics."},
        ]},
    }, raw_text="")
    assert out["creators"] == []
    assert [s["subject"] for s in out["subjects"]] == ["microplastics"]
    assert out["descriptions"] == []
    titles = [s.get("sectionTitle") for s in out["content"]["sections"]]
    assert "Methods" not in titles and "Results" in titles


def test_existing_placeholder_behavior_is_unchanged():
    assert _is_placeholder("Caption text")
    assert _is_placeholder("  Main Poster Title ")
    assert _is_placeholder("Institution Name...")
    assert not _is_placeholder("Results show a five-fold increase")
    assert not _is_placeholder(None)


# --- malformed JSON from the model: a list closed over an open object ---------

import json

import torch

from poster2json.extract import (
    _JsonBraceProcessor,
    _repair_mismatched_closers,
    _robust_json_parse,
)

# Shape of what the model produced for the PNG: the description object is never
# closed before "]", then the real content follows, then chatter after the JSON.
MALFORMED = """{
  "creators": [],
  "descriptions": [
    {
      "description": "Arugula grown with algae had more microplastics."
  ],
  "researchField": "Life Sciences",
  "content": {
    "sections": [
      {"sectionTitle": "Introduction", "sectionContent": "Why this matters."},
      {"sectionTitle": "Methods", "sectionContent": "Algae was collected [in jars]."}
    ]
  }
}
I did not include the references. {Please} let me know if you need anything ]."""


def test_mismatched_closer_is_repaired_and_content_survives():
    fixed = _repair_mismatched_closers(MALFORMED)
    obj = json.JSONDecoder().raw_decode(fixed)[0]
    assert [s["sectionTitle"] for s in obj["content"]["sections"]] == ["Introduction", "Methods"]
    assert obj["researchField"] == "Life Sciences"


def test_robust_parse_keeps_sections_despite_missing_brace_and_chatter():
    out = _robust_json_parse(MALFORMED)
    assert "error" not in out
    assert [s["sectionTitle"] for s in out["content"]["sections"]] == ["Introduction", "Methods"]


def test_valid_json_is_unchanged_by_closer_repair():
    good = '{"a": [1, {"b": "x ] } y"}], "c": {"d": []}} trailing'
    assert _repair_mismatched_closers(good) == good


class _CharTokenizer:
    """One token per character, so the processor sees text as it is generated."""

    def __init__(self, text):
        self.vocab = sorted(set(text))
        self.ids = {c: i for i, c in enumerate(self.vocab)}

    def encode(self, text):
        return [self.ids[c] for c in text]

    def decode(self, ids, skip_special_tokens=True):
        return "".join(self.vocab[int(i)] for i in ids)


def _eos_allowed_after(text):
    tok = _CharTokenizer(MALFORMED + "{}[]")
    eos = len(tok.vocab)  # an id outside the character vocabulary
    proc = _JsonBraceProcessor({eos}, tok, input_length=0)
    ids = torch.tensor([tok.encode(text)])
    scores = torch.zeros((1, eos + 1))
    out = proc(ids, scores)
    return out[0, eos].item() != float("-inf"), out, eos, proc


def test_processor_holds_eos_while_json_is_open():
    allowed, _, _, _ = _eos_allowed_after(MALFORMED[: MALFORMED.index('"researchField"')])
    assert not allowed


def test_processor_ends_generation_once_outer_object_closes_despite_missing_brace():
    json_part = MALFORMED[: MALFORMED.index("\nI did not")]
    allowed, out, eos, proc = _eos_allowed_after(json_part)
    assert proc.complete and allowed
    # everything but EOS is ruled out, so the model cannot keep writing chatter
    assert torch.isinf(out[0, :eos]).all()


# --- raw-text recovery and "## " header lines -------------------------------------

def _recovered(raw, sections):
    out = _postprocess_json({"titles": [{"title": "Title Here"}],
                             "content": {"sections": sections}}, raw_text=raw)
    return [(s.get("sectionTitle"), s["sectionContent"]) for s in out["content"]["sections"]]


def test_real_text_the_model_missed_is_reclaimed():
    raw = ("Title Here\n## Introduction\nMicroplastics enter crops through algae.\n"
           "## Acknowledgements\nThank you so much to my mentor and peers for the help.\n")
    secs = _recovered(raw, [{"sectionTitle": "Introduction",
                             "sectionContent": "Microplastics enter crops through algae."}])
    assert any("Thank you so much to my mentor" in c for _, c in secs)


def test_block_made_only_of_a_header_line_is_not_reclaimed():
    # captured text on both sides isolates the header, as on the real poster
    raw = ("Title Here\n## Introduction\nMicroplastics enter crops through algae.\n"
           "## Literature Cited\n## Results\nArugula grown with algae had more plastic.\n")
    secs = _recovered(raw, [
        {"sectionTitle": "Introduction", "sectionContent": "Microplastics enter crops through algae."},
        {"sectionTitle": "Results", "sectionContent": "Arugula grown with algae had more plastic."}])
    assert not any("Literature Cited" in c for _, c in secs)


def test_reclaimed_block_under_a_title_the_model_used_stays_untitled():
    raw = ("Title Here\n## Introduction\nMicroplastics enter crops through algae.\n"
           "Zebra quartz vexing jumbled wizard phrases appear nowhere else at all.\n")
    secs = _recovered(raw, [{"sectionTitle": "Introduction",
                             "sectionContent": "Microplastics enter crops through algae."}])
    titles = [t for t, _ in secs]
    assert titles.count("Introduction") == 1
    assert (None, "Zebra quartz vexing jumbled wizard phrases appear nowhere else at all.") in secs
