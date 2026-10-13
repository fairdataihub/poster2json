"""Deterministic author and affiliation parsing of the poster header."""

import pytest

from poster2json import extract, header_parse
from poster2json.header_parse import ground_creators, parse_header, split_joined_creators

TITLE = "## A Study of Things That Happen In Labs"


def _model(name, affs=()):
    fam, giv = [x.strip() for x in name.split(",", 1)]
    return {"name": name, "givenName": giv, "familyName": fam, "nameType": "Personal",
            "affiliation": list(affs)}


def _affs(c):
    return [a if isinstance(a, str) else a["name"] for a in c["affiliation"]]


# ------------------------------------------------------------------ parsing
def test_comma_markers_with_one_line_numbered_list():
    text = (
        f"{TITLE}\n"
        "## Ada Lovelace 1, Grace Hopper 1, Alan Turing 2,3, Edsger Dijkstra 4\n"
        "## Background\n"
        "1 Analytical Engine Institute, London, UK, 2 Department of Computing, University of Manchester, "
        "Manchester, UK 3 Bletchley Research Group, Bletchley, UK 4 Department of Mathematics, "
        "Eindhoven University of Technology, Eindhoven, NL\n"
        "Long body text begins here and goes on for a while about the methods used in the study.\n"
    )
    hp = parse_header(text)
    assert hp.confident
    assert [a["name"] for a in hp.authors] == [
        "Lovelace, Ada", "Hopper, Grace", "Turing, Alan", "Dijkstra, Edsger"]
    assert list(hp.entries) == ["1", "2", "3", "4"]
    assert hp.entries["2"] == "Department of Computing, University of Manchester, Manchester, UK"
    assert hp.assigned[2] == [hp.entries["2"], hp.entries["3"]]
    assert hp.assigned[3] == ["Department of Mathematics, Eindhoven University of Technology, Eindhoven, NL"]


def test_one_affiliation_per_line():
    text = (
        f"{TITLE}\n"
        "Maria Garcia a, John Smith b, Wei Zhang a,b\n"
        "a Department of Biology, University of Somewhere, Springfield, USA\n"
        "b Institute of Physics, Technical University of Elsewhere, Berlin, Germany\n"
        "## Introduction\n"
    )
    hp = parse_header(text)
    assert hp.confident and hp.scheme == "l"
    assert hp.assigned[0] == ["Department of Biology, University of Somewhere, Springfield, USA"]
    assert len(hp.assigned[2]) == 2


def test_numbers_on_their_own_lines_with_superscript_characters():
    text = (
        "Ana Silva\u00b9, Bruno Costa\u00b2\u207a\u00b9\n"
        "\u00b9Universidade de Lisboa, Lisboa, Portugal\n"
        "\u00b2Instituto Superior Tecnico, Lisboa, Portugal\n"
    )
    hp = parse_header(text)
    assert hp.confident
    assert [len(x) for x in hp.assigned] == [1, 2]


def test_text_after_nfkd_normalization():
    # the text reaching post-processing has superscripts folded to "1+2" and no space before entries
    text = (
        "Andrew Couperus*1+2, Todd Henry2, Rachel Osten3, and the RECONS Team 1Georgia State University, "
        "Atlanta, GA 2RECONS Institute, Chambersburg, PA 3STScI, Baltimore, MD * andcoup@example.edu | www.example.edu\n"
    )
    hp = parse_header(text)
    assert hp.confident
    assert [len(x) for x in hp.assigned] == [2, 1, 1]
    assert hp.entries["3"] == "STScI, Baltimore, MD"


def test_ampersand_join_in_author_line_without_markers():
    text = (
        f"{TITLE}\n"
        "Oliver Hahn & Steffen Lemke ZBW \u2014 Leibniz Information Centre for Economics\n"
        "## Introduction\n"
    )
    hp = parse_header(text)
    assert hp.confident
    assert [a["name"] for a in hp.authors] == ["Hahn, Oliver", "Lemke, Steffen"]
    assert hp.assigned[0] == hp.assigned[1] == ["ZBW \u2014 Leibniz Information Centre for Economics"]


def test_symbols_are_not_affiliations():
    text = (
        f"{TITLE}\n"
        "Ada Lovelace 1*, Grace Hopper 2\u2020, Alan Turing 1,2\n"
        "1 Analytical Engine Institute, London, UK\n"
        "2 Department of Computing, University of Manchester, Manchester, UK\n"
        "* corresponding author: ada@example.org \u2020 equal contribution\n"
    )
    hp = parse_header(text)
    assert hp.confident and hp.scheme == "d"
    assert list(hp.entries) == ["1", "2"]
    assert len(hp.assigned[0]) == 1 and len(hp.assigned[1]) == 1 and len(hp.assigned[2]) == 2


def test_symbol_markers_that_label_affiliations():
    text = (
        "Ana Silva *, Bruno Costa **, Carla Dias *\n"
        "* Universidade de Lisboa, Lisboa, Portugal ** Instituto Superior Tecnico, Lisboa, Portugal\n"
    )
    hp = parse_header(text)
    assert hp.confident and hp.scheme == "s"
    assert hp.assigned[1] == ["Instituto Superior Tecnico, Lisboa, Portugal"]


def test_partial_markers_unmarked_author_gets_the_unused_entry():
    text = (
        f"{TITLE}\n"
        "Ada Lovelace, PhD 1, Grace Hopper, MLS 1, Alan Turing, DDS, MD, PhD\n"
        "1 Analytical Engine Institute, London, UK; 2 Bluestone Center, University of Somewhere, USA\n"
    )
    hp = parse_header(text)
    assert hp.confident
    assert [a["name"] for a in hp.authors][2] == "Turing, Alan"   # degrees are not name parts
    assert hp.assigned[2] == ["Bluestone Center, University of Somewhere, USA"]


def test_no_marker_single_affiliation_is_shared():
    text = (
        f"{TITLE}\n"
        "Ada Lovelace, Grace Hopper and Alan Turing\n"
        "Department of Computing, University of Manchester, Manchester, UK\n"
        "## Introduction\n"
    )
    hp = parse_header(text)
    assert hp.confident
    assert all(a == ["Department of Computing, University of Manchester, Manchester, UK"] for a in hp.assigned)


def test_no_marker_several_affiliations_is_not_confident():
    text = (
        f"{TITLE}\n"
        "Ada Lovelace, Grace Hopper\n"
        "Department of Computing, University of Manchester, Manchester, UK\n"
        "Analytical Engine Institute, London, UK\n"
    )
    hp = parse_header(text)
    assert not hp.confident


def test_unparseable_header():
    for text in (
        "## A Poster Without Authors\n## Introduction\nSome text about the Department of Things.\n",
        "## Digital Humanists\nRongqian Ma, Indiana University Bloomington\n## Abstract\n",
    ):
        hp = parse_header(text)
        assert not hp.confident


def test_body_numbered_list_is_not_an_affiliation_list():
    text = (
        "Ada Lovelace 1, Grace Hopper 1\n"
        "## Problem\n1. Not interoperable. The data cannot be combined.\n2. Not reusable. Too narrow.\n"
    )
    hp = parse_header(text)
    assert not hp.confident


def test_unresolved_marker_is_not_confident():
    text = (
        "Ada Lovelace 1, Grace Hopper 3\n"
        "1 Analytical Engine Institute, London, UK 2 Department of Computing, University of Manchester, UK\n"
    )
    assert not parse_header(text).confident


def test_vancouver_names_particles_and_group_tail():
    text = (
        "Ivanyi P 1 , Bullement A 2 , Colombo GL 1,2\n"
        "1 Hannover Medical School, Hannover, Germany; 2 Delta Hat Ltd, Nottingham, UK\n"
    )
    hp = parse_header(text)
    assert hp.confident
    assert hp.authors[2]["family"] == "Colombo" and hp.authors[2]["given"] == "GL"

    text = (
        "Meike van der Zande 1, Loes PM Duivenvoorde 1, and the Gut Team\n"
        "1 Wageningen Food Safety Research, Wageningen, The Netherlands\n"
    )
    hp = parse_header(text)
    assert hp.confident
    assert hp.authors[0]["family"] == "van der Zande" and hp.authors[0]["given"] == "Meike"
    assert len(hp.authors) == 2


def test_emails_and_orcids_in_the_author_line_are_ignored():
    text = (
        "Authors Ada Lovelace 1 ada@example.org, Grace Hopper 2 ORCID: 0000-0002-5402-7837\n"
        "1 Analytical Engine Institute, London, UK 2 Department of Computing, University of Manchester, UK\n"
    )
    hp = parse_header(text)
    assert hp.confident
    assert [a["name"] for a in hp.authors] == ["Lovelace, Ada", "Hopper, Grace"]


def test_title_line_is_not_an_author_line():
    text = "## Digital Humanists And Others\nAda Lovelace 1, Grace Hopper 1\n1 Some Institute, Town, UK\n"
    hp = parse_header(text, exclude=["Digital Humanists And Others"])
    assert [a["name"] for a in hp.authors] == ["Lovelace, Ada", "Hopper, Grace"]


# ------------------------------------------------------------------ grounding
GASIMOVA_LIKE = (
    f"{TITLE}\n"
    "## Ada Lovelace 1, Grace Hopper 1, Alan Turing 2,3\n"
    "## Background\n"
    "1 FAIR Data Innovations Hub, Medical Innovations Institute, San Diego, CA, USA, "
    "2 Department of Ophthalmology, University of Washington, Seattle, WA, USA "
    "3 Department of Bioengineering, University of Washington, Seattle, WA, USA\n"
)


def test_grounding_expands_trimmed_affiliations_and_fixes_assignment():
    hp = parse_header(GASIMOVA_LIKE)
    model = [
        _model("Lovelace, Ada", ["Medical Innovations Institute"]),
        _model("Hopper, Grace", ["Medical Innovations Institute"]),
        _model("Turing, Alan", ["University of Washington"]),
    ]
    model[0]["nameIdentifiers"] = [{"nameIdentifier": "https://orcid.org/0000-0002-5402-7837"}]
    out, notes = ground_creators(model, hp)
    assert _affs(out[0]) == ["FAIR Data Innovations Hub, Medical Innovations Institute, San Diego, CA, USA"]
    assert _affs(out[2]) == [
        "Department of Ophthalmology, University of Washington, Seattle, WA, USA",
        "Department of Bioengineering, University of Washington, Seattle, WA, USA"]
    assert out[0]["nameIdentifiers"][0]["nameIdentifier"].endswith("7837")   # enrichment kept
    assert notes


def test_grounding_splits_joined_creator_and_orders_by_print():
    text = "Oliver Hahn & Steffen Lemke ZBW \u2014 Leibniz Information Centre for Economics\n"
    hp = parse_header(text)
    model = [{"name": "Hahn, Oliver & Lemke, Steffen", "givenName": "Oliver & Steffen",
              "familyName": "Hahn & Lemke", "nameType": "Personal",
              "affiliation": ["ZBW \u2014 Leibniz Information Centre for Economics"]}]
    out, _ = ground_creators(model, hp)
    assert [c["name"] for c in out] == ["Hahn, Oliver", "Lemke, Steffen"]
    assert out[1]["givenName"] == "Steffen" and out[1]["familyName"] == "Lemke"
    assert all(_affs(c) == ["ZBW \u2014 Leibniz Information Centre for Economics"] for c in out)


def test_grounding_adds_missing_author_and_keeps_model_only_creator():
    hp = parse_header(GASIMOVA_LIKE)
    model = [_model("Lovelace, Ada"), _model("Hopper, Grace"), {"name": "The Analytical Team",
                                                                  "nameType": "Organizational"}]
    out, _ = ground_creators(model, hp)
    assert [c["name"] for c in out] == ["Lovelace, Ada", "Hopper, Grace", "Turing, Alan", "The Analytical Team"]


def test_degree_suffix_in_model_name_is_replaced_by_printed_name():
    text = (
        "Alisa Surkis, PhD, MLS 1, Richard McGowan, MLS 1\n"
        "1 NYU Health Sciences Libraries, New York University School of Medicine, New York, NY\n"
    )
    hp = parse_header(text)
    model = [_model("Surkis, Alisa, PhD, MLS"), _model("McGowan, Richard, MLS")]
    out, _ = ground_creators(model, hp)
    assert [c["name"] for c in out] == ["Surkis, Alisa", "McGowan, Richard"]


def test_not_confident_keeps_model_but_splits_and_expands():
    text = (
        "Ada Lovelace 1, Grace Hopper 5\n"      # marker 5 does not resolve: not confident
        "1 Analytical Engine Institute, London, UK 2 Department of Computing, University of Manchester, UK\n"
    )
    hp = parse_header(text)
    assert not hp.confident
    model = [_model("Lovelace, Ada", ["Analytical Engine Institute"]),
             _model("Hopper, Grace", ["Somewhere Else"]),
             {"name": "Turing, Alan & Dijkstra, Edsger", "givenName": "Alan & Edsger",
              "familyName": "Turing & Dijkstra", "affiliation": ["Department of Computing"]}]
    out, _ = ground_creators(model, hp)
    assert [c["name"] for c in out] == ["Lovelace, Ada", "Hopper, Grace", "Turing, Alan", "Dijkstra, Edsger"]
    assert _affs(out[0]) == ["Analytical Engine Institute, London, UK"]
    assert _affs(out[1]) == ["Somewhere Else"]                  # not a sub-span of any entry
    assert _affs(out[2]) == ["Department of Computing, University of Manchester, UK"]


def test_expansion_needs_exactly_one_printed_entry():
    text = (
        "Ada Lovelace 1, Grace Hopper 9\n"
        "1 Department of Ophthalmology, University of Washington, Seattle 2 Department of Bioengineering, "
        "University of Washington, Seattle\n"
    )
    hp = parse_header(text)
    out, _ = ground_creators([_model("Lovelace, Ada", ["University of Washington"])], hp)
    assert _affs(out[0]) == ["University of Washington"]


def test_split_joined_creators_leaves_organizations_alone():
    orgs = [{"name": "Procter and Gamble", "affiliation": []},
            {"name": "Smith, John & Jane", "affiliation": []}]
    out, notes = split_joined_creators(orgs)
    assert out == orgs and not notes


def test_unparseable_header_leaves_model_output():
    hp = parse_header("## Title Only\nNo authors here at all, just some prose in a poster.\n")
    model = [_model("Lovelace, Ada", ["Analytical Engine Institute"])]
    out, notes = ground_creators(model, hp)
    assert out == model and not notes


# --------------------------------------------------------------- integration
def _result(model):
    return {"titles": [{"title": "A Study of Things That Happen In Labs"}], "creators": model}


def test_extract_hook_replaces_creators(monkeypatch):
    monkeypatch.setattr(header_parse, "HEADER_GROUNDING", True)
    result = _result([_model("Lovelace, Ada", ["Medical Innovations Institute"])])
    assert extract._ground_creators_from_header(result, GASIMOVA_LIKE) is True
    assert [c["name"] for c in result["creators"]] == ["Lovelace, Ada", "Hopper, Grace", "Turing, Alan"]
    assert _affs(result["creators"][0]) == [
        "FAIR Data Innovations Hub, Medical Innovations Institute, San Diego, CA, USA"]


def test_extract_hook_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(header_parse, "HEADER_GROUNDING", False)
    model = [_model("Lovelace, Ada", ["Medical Innovations Institute"])]
    result = _result(list(model))
    assert extract._ground_creators_from_header(result, GASIMOVA_LIKE) is False
    assert result["creators"] == model


def test_extract_hook_never_raises(monkeypatch):
    monkeypatch.setattr(header_parse, "HEADER_GROUNDING", True)

    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(header_parse, "parse_header", boom)
    model = [_model("Lovelace, Ada")]
    result = _result(list(model))
    assert extract._ground_creators_from_header(result, GASIMOVA_LIKE) is False
    assert result["creators"] == model


def test_parse_ignored_when_model_creators_are_not_the_printed_authors():
    hp = parse_header(GASIMOVA_LIKE)
    model = [_model("Nobody, Known", ["Elsewhere Institute"]), _model("Other, Person")]
    out, notes = ground_creators(model, hp)
    assert [c["name"] for c in out] == ["Nobody, Known", "Other, Person"]
    assert any("ignored" in n for n in notes)
