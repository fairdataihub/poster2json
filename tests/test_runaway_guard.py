"""Runaway generation guard: detector and the rerun on the other layout engine."""

import os

import pytest

extract = pytest.importorskip("poster2json.extract")

RAW = "\n".join(f"## Heading {i}\n" + ("word " * 40) for i in range(8))


def _result(sizes):
    return {"content": {"sections": [{"sectionTitle": f"s{i}", "sectionContent": "x" * n}
                                     for i, n in enumerate(sizes)]}}


def test_normal_result_is_not_a_runaway():
    reasons, score = extract._runaway_reasons(_result([200] * 8), RAW)
    assert reasons == [] and score == 0.0


def test_token_budget_used_up_is_a_runaway():
    reasons, _ = extract._runaway_reasons(_result([200] * 8), RAW, capped=True)
    assert any("token budget" in r for r in reasons)


def test_json_error_is_a_runaway_unless_input_too_long():
    assert extract._runaway_reasons({"error": "bad"}, RAW)[0] == ["json error"]
    assert extract._runaway_reasons({"error": "x", "errorCode": "INPUT_TOO_LONG"}, RAW)[0] == []


def test_one_giant_section_is_a_runaway_only_when_the_text_has_headings():
    giant = _result([5000, 50, 50, 50])
    assert extract._runaway_reasons(giant, RAW)[0]
    flat = "one paragraph " * 600
    assert extract._runaway_reasons(giant, flat)[0] == []     # no headings: may be one section


def test_output_far_longer_than_the_poster_text_is_a_runaway():
    reasons, _ = extract._runaway_reasons(_result([len(RAW)] * 3), RAW)
    assert any("x the poster text" in r for r in reasons)


class _Env:
    def __init__(self, monkeypatch, texts):
        self.engines = []
        self.texts = texts

        def fake_get_raw_text(path, poster_id=None, output_dir=None, captions_out=None):
            eng = os.environ.get("POSTER2JSON_LAYOUT")
            self.engines.append(eng)
            if captions_out is not None:
                captions_out.append({"kind": "figure", "text": "c", "label": None,
                                     "source": "geometry", "page": 0})
            return self.texts[eng], "pdfplumber"

        monkeypatch.setattr(extract, "get_raw_text", fake_get_raw_text)
        monkeypatch.setattr(extract, "RUNAWAY_FALLBACK", True)


def _gen_factory(outcomes, calls):
    def gen(text, caps, diag):
        calls.append(text)
        res, capped = outcomes[len(calls) - 1]
        diag["capped"] = capped
        return res
    return gen


def test_runaway_reruns_on_the_other_engine_and_keeps_the_good_result(monkeypatch):
    monkeypatch.setenv("POSTER2JSON_LAYOUT", "alto")
    env = _Env(monkeypatch, {"blocks": RAW + "\nblocks", "alto": RAW})
    calls = []
    good = _result([200] * 8)
    gen = _gen_factory([(_result([200] * 8), True), (good, False)], calls)
    res, raw, caps = extract._generate_with_layout_fallback("p.pdf", RAW, [], gen)
    assert res is good and raw.endswith("blocks") and len(caps) == 1
    assert env.engines == ["blocks"]
    assert os.environ["POSTER2JSON_LAYOUT"] == "alto"          # restored
    assert len(calls) == 2


def test_blocks_runaway_falls_back_to_alto(monkeypatch):
    monkeypatch.setenv("POSTER2JSON_LAYOUT", "blocks")
    env = _Env(monkeypatch, {"blocks": RAW, "alto": RAW + "\nalto"})
    gen = _gen_factory([({"error": "bad"}, False), (_result([200] * 8), False)], [])
    res, raw, _ = extract._generate_with_layout_fallback("p.pdf", RAW, [], gen)
    assert "error" not in res and raw.endswith("alto")
    assert env.engines == ["alto"]


def test_no_rerun_without_a_runaway(monkeypatch):
    monkeypatch.setenv("POSTER2JSON_LAYOUT", "alto")
    env = _Env(monkeypatch, {"blocks": "other", "alto": RAW})
    calls = []
    gen = _gen_factory([(_result([200] * 8), False)], calls)
    res, raw, _ = extract._generate_with_layout_fallback("p.pdf", RAW, [], gen)
    assert raw == RAW and len(calls) == 1 and env.engines == []


def test_both_runaways_keep_the_less_degenerate(monkeypatch):
    monkeypatch.setenv("POSTER2JSON_LAYOUT", "alto")
    _Env(monkeypatch, {"blocks": RAW + "\nb", "alto": RAW})
    worse = _result([5000, 10])
    better = _result([120] * 8)
    gen = _gen_factory([(worse, True), (better, True)], [])
    res, raw, _ = extract._generate_with_layout_fallback("p.pdf", RAW, [], gen)
    assert res is better                                          # capped both, one fewer reason
    gen = _gen_factory([(better, True), (worse, True)], [])
    res, raw, _ = extract._generate_with_layout_fallback("p.pdf", RAW, [], gen)
    assert res is better and raw == RAW


def test_same_text_on_both_engines_is_not_rerun(monkeypatch):
    monkeypatch.setenv("POSTER2JSON_LAYOUT", "alto")
    _Env(monkeypatch, {"blocks": RAW, "alto": RAW})
    calls = []
    gen = _gen_factory([(_result([200] * 8), True)], calls)
    extract._generate_with_layout_fallback("p.pdf", RAW, [], gen)
    assert len(calls) == 1


def test_fallback_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("POSTER2JSON_LAYOUT", "alto")
    env = _Env(monkeypatch, {"blocks": "x", "alto": RAW})
    monkeypatch.setattr(extract, "RUNAWAY_FALLBACK", False)
    calls = []
    gen = _gen_factory([(_result([200] * 8), True)], calls)
    extract._generate_with_layout_fallback("p.pdf", RAW, [], gen)
    assert len(calls) == 1 and env.engines == []
