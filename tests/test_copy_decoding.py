"""Copy-only constrained decoding: state machine, copy predicate, switches."""

import pytest

from poster2json.copy_decoding import (
    CopySource,
    JsonStringTracker,
    normalize,
    normalize_source,
)


def _events(text, tracker=None):
    t = tracker or JsonStringTracker()
    return t, t.feed(text)


def _texts(events):
    """Join text events per opened string: list of (field, text)."""
    out, cur = [], None
    for kind, val in events:
        if kind == "open":
            cur = [val, ""]
            out.append(cur)
        elif kind == "text":
            cur[1] += val
    return [tuple(x) for x in out]


# ---------------- state machine ----------------


def test_tracker_keys_and_values_with_odd_whitespace():
    _, ev = _events('{ "titles" :\n [ {  "title"  :   "Hello World" } ] }')
    assert _texts(ev) == [("title", "Hello World")]


def test_tracker_key_strings_are_not_values():
    _, ev = _events('{"a": "x", "b": "y"}')
    assert _texts(ev) == [("a", "x"), ("b", "y")]


def test_tracker_escapes():
    _, ev = _events(r'{"sectionContent": "a\nb\t\"q\" \\ c \u00e9"}')
    assert _texts(ev) == [("sectionContent", 'a\nb\t"q" \\ c \u00e9')]


def test_tracker_escape_split_across_chunks():
    t = JsonStringTracker()
    ev = []
    for chunk in ['{"sectionContent": "a\\', 'nb \\', '"x\\', '"', ' \\u00', 'e9", "k": "v"}']:
        ev += t.feed(chunk)
    assert _texts(ev) == [("sectionContent", 'a\nb "x" \u00e9'), ("k", "v")]


def test_tracker_nested_arrays_and_objects():
    doc = (
        '{"content": {"sections": [{"sectionTitle": "A", "sectionContent": "one"},'
        ' {"sectionTitle": "B", "sectionContent": "two"}]},'
        ' "imageCaptions": [{"id": "fig1", "caption": "cap"}],'
        ' "creators": [{"affiliation": ["U1", "U2"]}]}'
    )
    _, ev = _events(doc)
    assert _texts(ev) == [
        ("sectionTitle", "A"), ("sectionContent", "one"),
        ("sectionTitle", "B"), ("sectionContent", "two"),
        ("id", "fig1"), ("caption", "cap"),
        ("affiliation", "U1"), ("affiliation", "U2"),
    ]


def test_tracker_in_value_string_flag_and_simulate():
    t = JsonStringTracker()
    t.feed('{"title": "Ab')
    assert t.in_value_string and t.field == "title"
    dec, closed, opaque = t.simulate('c"}')
    assert (dec, closed, opaque) == ("c", True, False)
    assert t.in_value_string  # simulate does not change state
    dec, closed, _ = t.simulate("c d")
    assert (dec, closed) == ("c d", False)
    t.feed('"')
    assert not t.in_value_string


def test_tracker_simulate_unicode_escape_is_opaque():
    t = JsonStringTracker()
    t.feed('{"title": "x')
    assert t.simulate("\\u00e9")[2] is True


# ---------------- normalization ----------------


def test_normalize_unifies_quotes_dashes_whitespace():
    assert normalize("a \u201cb\u201d\n\n c\u2014d  e\u2019s") == "a 'b' c-d e's"
    assert normalize('say "x"') == "say 'x'"


def test_normalize_source_strips_header_markers():
    assert normalize_source("## Methods\nWe did   it\n### Results\nok") == "Methods We did it Results ok"


# ---------------- copy predicate ----------------

SRC = "## Introduction\nGlioblastoma is the most lethal primary brain tumor.\nFigure 1: noise noise\nTreatment options remain limited."


def _commit_all(cs, pieces):
    for p in pieces:
        assert cs.allows(p), p
        cs.commit(p)


def test_copy_substring_continuation_mid_word():
    cs = CopySource(SRC)
    _commit_all(cs, ["Gliob", "lastoma", " is", " the", " most"])
    assert cs.frag.endswith("is the most")


def test_copy_rejects_invented_words():
    cs = CopySource(SRC)
    _commit_all(cs, ["Glioblastoma", " is"])
    assert not cs.allows(" an")  # "is an" not in source, and " an" alone...
    assert not cs.allows(" aggressive")
    assert not cs.allows(" xyzzy")


def test_copy_rejects_invented_first_word():
    cs = CopySource(SRC)
    assert not cs.allows("Zebrafish")


def test_copy_new_fragment_at_word_boundary_skips_noise():
    cs = CopySource(SRC)
    _commit_all(cs, ["Glioblastoma", " is", " the", " most", " lethal", " primary", " brain", " tumor."])
    # skip the figure noise and join the next block
    assert cs.allows(" Treatment")
    cs.commit(" Treatment")
    assert cs.allows(" options") and not cs.allows(" choices")


def test_copy_new_fragment_not_allowed_mid_word():
    cs = CopySource(SRC)
    _commit_all(cs, ["Glioblastoma", " is"])
    # glued on with no word boundary and not a continuation of the source
    assert not cs.allows("Treatment")


def test_copy_matching_ignores_quote_style_whitespace_and_markers():
    cs = CopySource('He said \u201chello\u201d to the\n\nworld \u2013 again')
    _commit_all(cs, ["He said", " 'hello'", " to the world", " -", " again"])


def test_copy_header_marker_text_is_matchable_but_marker_is_not():
    cs = CopySource(SRC)
    assert cs.allows("Introduction Glioblastoma")
    assert not cs.allows("## Introduction")


def test_copy_case_insensitive_mode_for_titles():
    cs = CopySource("RESEARCH ON SARS-CoV-2 SPIKE")
    assert not cs.allows("Research")
    cs.reset(lower=True)
    _commit_all(cs, ["Research", " on", " SARS-CoV-2", " Spike"])


def test_copy_closing_quote_always_allowed():
    # empty text before the closing quote must pass at any point
    cs = CopySource(SRC)
    _commit_all(cs, ["Glioblastoma", " is"])
    assert cs.allows("")


def test_copy_long_fragment_uses_tail_window():
    words = [f"w{i}" for i in range(400)]
    cs = CopySource(" ".join(words))
    for i, w in enumerate(words):
        piece = w if i == 0 else " " + w
        assert cs.allows(piece)
        cs.commit(piece)
    assert len(cs.frag) <= 120


# ---------------- processor (needs torch) ----------------


class _Tok:
    """Character-ish tokenizer: id -> string table."""

    def __init__(self, vocab):
        self.vocab = vocab

    def decode(self, ids, skip_special_tokens=True):
        return "".join(self.vocab[i] for i in ids)


def _proc(vocab, src, prompt_len=1, top_k=3):
    pytest.importorskip("torch")
    from poster2json.copy_decoding import CopyOnlyProcessor

    return CopyOnlyProcessor(_Tok(vocab), prompt_len, src, top_k)


def test_processor_masks_invented_token_and_counts():
    torch = pytest.importorskip("torch")
    vocab = ['{"title": "', "Gluon", " Physics", " Magic", '"', "x"]
    p = _proc(vocab, "Gluon Physics rocks")
    ids = torch.tensor([[9, 0, 1]])  # prompt token then the opening and "Gluon"
    scores = torch.tensor([[0.0, 0.0, 1.0, 5.0, 4.0, 0.0]])  # " Magic" > '"' > " Physics"
    out = p(ids, scores.clone())
    assert out[0, 3] == float("-inf") and out[0, 4] != float("-inf")
    assert p.stats["masked_steps"] == 1 and p.stats["fail_open"] == 0


def test_processor_fail_open_when_no_top_k_candidate_copies():
    torch = pytest.importorskip("torch")
    vocab = ['{"title": "', "Gluon", " Magic", " Fake", " Wrong", "ok"]
    p = _proc(vocab, "Gluon Physics", top_k=3)
    ids = torch.tensor([[9, 0, 1]])
    scores = torch.tensor([[0.0, 0.0, 3.0, 2.0, 1.0, -1.0]])
    out = p(ids, scores.clone())
    assert torch.equal(out, scores)
    assert p.stats["fail_open"] == 1


def test_processor_ignores_unconstrained_fields():
    torch = pytest.importorskip("torch")
    vocab = ['{"description": "', "Invented", " stuff"]
    p = _proc(vocab, "Gluon Physics")
    ids = torch.tensor([[9, 0]])
    scores = torch.tensor([[0.0, 0.0, 2.0]])
    out = p(ids, scores.clone())
    assert torch.equal(out, scores) and p.stats["constrained"] == 0


# ---------------- switches ----------------


def test_disabled_switches_leave_generation_inputs_unchanged(monkeypatch):
    torch = pytest.importorskip("torch")
    from poster2json import extract as E

    monkeypatch.setattr(E, "COPY_ONLY_DECODING", False)
    monkeypatch.setattr(E, "USE_SYSTEM_PROMPT", "")
    assert E._build_messages("PROMPT", "SYS") == [{"role": "user", "content": "PROMPT"}]

    seen = {}

    class Tok:
        eos_token_id = 0
        unk_token_id = -1

        def apply_chat_template(self, messages, tokenize, add_generation_prompt):
            seen["messages"] = messages
            return "x"

        def __call__(self, text, return_tensors):
            class R(dict):
                def to(self, dev):
                    return self

            return R(input_ids=torch.tensor([[1, 2]]))

        def convert_tokens_to_ids(self, t):
            return -1

        def decode(self, ids, skip_special_tokens=True):
            return ""

    class Model:
        device = "cpu"

        def generate(self, **kw):
            seen["kw"] = kw
            return torch.tensor([[1, 2, 3]])

    E._generate(Model(), Tok(), "PROMPT", 10, system="SYS", copy_source="text")
    assert seen["messages"] == [{"role": "user", "content": "PROMPT"}]
    procs = list(seen["kw"]["logits_processor"])
    assert len(procs) == 1 and type(procs[0]).__name__ == "_JsonBraceProcessor"


def test_system_prompt_switch_adds_system_turn(monkeypatch):
    pytest.importorskip("torch")
    from poster2json import extract as E

    monkeypatch.setattr(E, "USE_SYSTEM_PROMPT", "move")
    msgs = E._build_messages("U", "S")
    assert msgs == [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]


def test_system_prompt_keeps_every_rule():
    pytest.importorskip("torch")
    from poster2json import extract as E

    assert E.EXTRACTION_PROMPT.count("CRITICAL RULES:") == 1
    for rule in E._PROMPT_RULES.splitlines():
        if rule.strip():
            assert rule in E.EXTRACTION_SYSTEM_PROMPT
    assert "{raw_text}" in E.EXTRACTION_USER_PROMPT
    assert "JSON SCHEMA" in E.EXTRACTION_USER_PROMPT
    assert "{raw_text}" not in E.EXTRACTION_SYSTEM_PROMPT


def test_new_fragment_must_start_at_a_source_word_start():
    cs = CopySource("Glioblastoma is lethal")
    _commit_all(cs, ["Glioblastoma", " is"])
    assert not cs.allows(" ethal")  # occurs only mid-word
    assert not cs.allows(" ast")
    assert cs.allows(" lethal")


def test_repeat_loop_of_valid_text_is_cut():
    src = " ".join(f"word{i}" for i in range(60))
    cs = CopySource(src, max_repeat=40)
    words = src.split()
    for i, w in enumerate(words[:20]):
        piece = w if i == 0 else " " + w
        assert cs.allows(piece)
        cs.commit(piece)
    # jump back to the start and copy the same text again
    assert cs.allows(" word0")
    cs.commit(" word0")
    rejected = False
    for w in words[1:20]:
        if not cs.allows(" " + w):
            rejected = True
            break
        cs.commit(" " + w)
    assert rejected


def test_repeat_guard_does_not_block_first_copy_or_other_fields():
    src = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    cs = CopySource(src, max_repeat=8)
    cs.reset(field="title")
    _commit_all(cs, ["alpha", " beta", " gamma", " delta"])
    cs.reset(field="title")  # a new string starts with fresh coverage
    _commit_all(cs, ["alpha", " beta", " gamma", " delta"])
    cs.reset(field="sectionContent")
    _commit_all(cs, ["alpha", " beta"])
    cs.reset(field="sectionContent")  # shared across section strings
    cs.commit("alpha")
    assert not cs.allows(" beta")  # re-copies already-copied source


def test_normalize_drops_accents():
    assert normalize("Caf\u00e9 Z\u00fcrich") == "Cafe Zurich"
    assert CopySource("Cafe Zurich").allows(normalize("Caf\u00e9"))


def test_processor_never_opens_a_unicode_escape_and_waits_for_whole_chars():
    torch = pytest.importorskip("torch")
    vocab = ['{"sectionContent": "', "Technion", " \\u2212", " \ufffd", " Israel"]
    p = _proc(vocab, "Technion Israel")
    ids = torch.tensor([[9, 0, 1]])
    scores = torch.tensor([[0.0, 0.0, 5.0, 3.0, 2.0]])
    out = p(ids, scores.clone())
    assert out[0, 2] == float("-inf")  # unicode escape masked
    assert out[0, 3] != float("-inf")  # partial multi-byte token left alone
