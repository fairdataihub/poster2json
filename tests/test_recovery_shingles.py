"""Raw-text recovery judges long lines by word n-gram shingle coverage."""

import pytest

pytest.importorskip("torch")

from poster2json import extract as E  # noqa: E402

CAPTURED = (
    "The effective temperature and gravity are given for the sun and the K0V star. "
    "The horizontal size and height of the domain is larger for the sun than for the M0V star. "
    "For earlier spectral types, the granule cell size is larger and the vertical "
    "velocities are higher."
)
# Shares nearly all of its vocabulary with CAPTURED but says something else.
DROPPED = (
    "The properties of the convection of the K0V and M0V stars are in general "
    "agreement with the results from the sun and the size of the domain for the stars"
)


def _check(line, fields=(CAPTURED,), meta=None):
    words = [w.strip(":.,;()") for w in line.lower().split()]
    captured = set()
    for f in fields:
        captured.update(f.lower().split())
    shingles = E._build_shingles(fields, E._RECOVERY_NGRAM)
    return E._line_is_uncaptured(line, words, captured, shingles, meta)


def test_dropped_long_paragraph_is_uncaptured_despite_shared_vocabulary():
    words = [w.strip(":.,;()") for w in DROPPED.lower().split()]
    bag_hit = sum(1 for w in words if w in set(CAPTURED.lower().split()))
    assert bag_hit / len(words) >= 0.5  # the old unigram rule would call it captured
    assert _check(DROPPED) is True


def test_lightly_reformatted_paragraph_is_captured():
    reformatted = (
        "•  The effective   temperature and gravity are given for the sun and the "
        "K0V star.   The horizontal size and height of the do-\nmain is larger for the sun "
        "than for the M0V star."
    )
    # hyphen/line-wrap differences cost a few shingles, not most of them
    assert _check(reformatted) is False


def test_short_lines_keep_unigram_rule():
    assert _check("the sun and the star") is False
    assert _check("zebra mussels everywhere") is True


def test_shingles_do_not_cross_field_boundaries():
    fields = ["alpha beta gamma delta", "epsilon zeta eta theta"]
    sh = E._build_shingles(fields, 3)
    assert ("delta", "epsilon", "zeta") not in sh
    assert ("alpha", "beta", "gamma") in sh


def test_author_banner_is_not_reclaimed():
    banner = "Laura Dettori 1,2 , Paolo Malune 2 , Marta Cara 1,2 and Enzo Tramontano 2"
    meta = set(E._norm_tokens("Laura Dettori Paolo Malune Marta Cara Enzo Tramontano"))
    assert _check(banner, fields=("Something unrelated entirely here",), meta=meta) is False


def test_email_banner_is_not_reclaimed():
    line = "Ophir Munz Manor ophirmm@openu.ac.il Adir Cohen adircohen@campus.technion.ac.il"
    assert _check(line, fields=("zzz yyy xxx",)) is False


def _extraction(sections):
    return {
        "titles": [{"title": "A poster title"}],
        "content": {"sections": [{"sectionTitle": t, "sectionContent": c}
                                 for t, c in sections]},
    }


def test_postprocess_reclaims_dropped_paragraph():
    raw = "## Results\n" + CAPTURED + "\n" + DROPPED + "\n"
    out = E._postprocess_json(_extraction([("Results", CAPTURED)]), raw_text=raw)
    contents = [s["sectionContent"] for s in out["content"]["sections"]]
    assert any("properties of the convection" in c for c in contents)


def test_postprocess_does_not_duplicate_reformatted_paragraph():
    raw = ("• " + CAPTURED.replace(" for the sun", "  for the  sun") + "\n")
    out = E._postprocess_json(_extraction([("Results", CAPTURED)]), raw_text=raw)
    assert len(out["content"]["sections"]) == 1
