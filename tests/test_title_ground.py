"""Title grounding: typographic candidate selection and the grounding rules."""

from poster2json.extract import _postprocess_json
from poster2json.title_ground import candidate_from_lines, ground_title


def L(text, size, top, h=None):
    h = h or size
    return {"text": text, "size": size, "top": top, "bottom": top + h}


# ---------- candidate selection ----------

def test_candidate_is_topmost_large_group_not_biggest_quote():
    lines = [
        L("Your funding infrastructure wishes", 67, 0),
        L("Grant-ID", 67, 83),
        L("The primary challenge reported by funders", 96, 375),
        L("is connecting grants to subsequent", 96, 510),
    ]
    assert candidate_from_lines(lines) == "Your funding infrastructure wishes Grant-ID"


def test_candidate_joins_mixed_size_title_lines():
    lines = [
        L("Presenting the", 66, 10),
        L("Actionable Guidelines for FAIR Research", 80, 90),
        L("Software Task Force", 80, 180),
    ]
    assert candidate_from_lines(lines) == (
        "Presenting the Actionable Guidelines for FAIR Research Software Task Force")


def test_candidate_skips_urls_emails_short_and_author_lines():
    lines = [
        L("www.example.org/poster", 90, 0),
        L("jane@example.org contact us today", 90, 50),
        L("Short line", 90, 100),
        L("A. Smith , B. Jones , C. Lee 1,2", 90, 150),
        L("Real Poster Title Here", 70, 600),
    ]
    assert candidate_from_lines(lines) == "Real Poster Title Here"


def test_candidate_stops_at_body_text_and_large_gap():
    lines = [
        L("A Study of Something Important", 60, 0),
        L("Introduction text that is much smaller than the title", 20, 90),
        L("Another Big Heading Far Below", 60, 600),
    ]
    assert candidate_from_lines(lines) == "A Study of Something Important"


def test_candidate_drops_venue_banner_line():
    lines = [
        L("5th Balkan Scientific Conference on Biology", 44, 40),
        L("Biochemical analysis of insecticide effects", 40, 107),
        L("on zebra mussels", 40, 155),
    ]
    assert candidate_from_lines(lines) == (
        "Biochemical analysis of insecticide effects on zebra mussels")


def test_candidate_none_when_nothing_plausible():
    assert candidate_from_lines([]) is None
    assert candidate_from_lines([L("two words", 80, 0)]) is None


# ---------- grounding rules ----------

CAND = "Presenting the Actionable Guidelines for FAIR Research Software Task Force"


def test_trimmed_title_is_extended_to_candidate():
    t, act = ground_title("Actionable Guidelines for FAIR Research Software Task Force", CAND, "")
    assert (t, act) == (CAND, "extend")


def test_grounded_complete_title_is_kept():
    t, act = ground_title(CAND, CAND, "")
    assert (t, act) == (CAND, "keep")


def test_model_title_longer_than_candidate_is_kept():
    model = "Cost-effectiveness of pembrolizumab versus cetuximab regimens in Italy"
    t, act = ground_title(model, "Cost-effectiveness of pembrolizumab versus cetuximab", "")
    assert (t, act) == (model, "keep")


def test_pull_quote_paraphrase_replaced_by_candidate():
    raw = ("Your funding infrastructure wishes Grant-ID\n"
           "The primary challenge reported by funders is connecting grants to "
           "research activities and outputs\n")
    t, act = ground_title("Connecting Grants to Research Activities and Outputs",
                          "Your funding infrastructure wishes Grant-ID", raw)
    assert (t, act) == ("Your funding infrastructure wishes Grant-ID", "replace")


def test_invented_title_is_kept_and_flagged():
    raw = "What is Portage? Shared Platforms and Services\nSome body text about data."
    t, act = ground_title("Portage: A National Research Data Management Initiative",
                          "What is Portage? Shared Platforms and Services", raw)
    assert (t, act) == ("Portage: A National Research Data Management Initiative", "warn")
    t, act = ground_title("An Invented Title About Nothing", None, raw)
    assert act == "warn" and t == "An Invented Title About Nothing"


def test_all_caps_candidate_keeps_model_casing():
    t, act = ground_title("Modeling of 3D Atmospheres of Cool Stars with the Mancha Code",
                          "MODELING OF 3D ATMOSPHERES OF COOL STARS WITH THE MANCHA CODE", "")
    assert act == "keep" and t.startswith("Modeling")
    t, act = ground_title("Atmospheres of Cool Stars with the Mancha Code",
                          "MODELING OF ATMOSPHERES OF COOL STARS WITH THE MANCHA CODE", "")
    assert act == "extend" and t == "Modeling of Atmospheres of Cool Stars with the Mancha Code"


# ---------- integration with _postprocess_json ----------

def _data(title, extra=None):
    titles = [{"title": title}]
    if extra:
        titles.append(extra)
    return {"titles": titles, "creators": [], "subjects": [], "descriptions": []}


def test_postprocess_none_candidate_leaves_title_unchanged():
    out = _postprocess_json(_data("Some Model Title About Things"), raw_text="unrelated text")
    assert out["titles"][0]["title"] == "Some Model Title About Things"
    out2 = _postprocess_json(_data("Some Model Title About Things"), raw_text="",
                             title_candidate=None)
    assert out2["titles"][0]["title"] == "Some Model Title About Things"


def test_postprocess_extends_title_and_keeps_subtitle():
    sub = {"title": "A subtitle", "titleType": "Subtitle"}
    out = _postprocess_json(
        _data("Actionable Guidelines for FAIR Research Software Task Force", sub),
        raw_text=CAND, title_candidate=CAND)
    assert out["titles"][0]["title"] == CAND
    assert out["titles"][1] == sub
