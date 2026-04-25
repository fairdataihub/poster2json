"""Unit tests for poster2json.language detection."""

import pytest

from poster2json.language import detect_language


# Body-text fragments long enough to exceed the 200-char threshold.
ENGLISH = (
    "We present a deep learning model for automated diabetic retinopathy "
    "detection from retinal fundus images. Our convolutional neural network "
    "was trained on 100,000 labeled images and achieved 94.2% sensitivity "
    "and 89.5% specificity on a held-out test set of 5,000 images."
)
SPANISH = (
    "Presentamos un modelo de aprendizaje profundo para la detección "
    "automatizada de retinopatía diabética a partir de imágenes del fondo "
    "de ojo. Nuestra red neuronal convolucional fue entrenada con 100.000 "
    "imágenes etiquetadas y alcanzó una sensibilidad del 94,2 por ciento."
)
GERMAN = (
    "Wir präsentieren ein Deep-Learning-Modell zur automatisierten Erkennung "
    "der diabetischen Retinopathie anhand von Netzhautbildern. Unser "
    "konvolutionelles neuronales Netz wurde mit 100.000 markierten Bildern "
    "trainiert und erreichte eine Sensitivität von 94,2 Prozent."
)
JAPANESE = (
    "ヤチダモ13年生の伐採後の萌芽について、北海道道央地域における造林試験地で"
    "調査した結果を報告する。伐採後3年間にわたる萌芽数と樹高成長を測定した結果、"
    "萌芽の発生は伐採後1年目に集中していることが明らかになった。考察では、樹齢と"
    "萌芽性能の関係について議論する。"
)
# The figshare DOI 10.6084/m9.figshare.10116536.v1 case Dorian flagged:
# Japanese poster body content with English metadata mixed in, which made
# the LLM emit `language: en`. The heuristic on full body text should
# correctly identify it as Japanese.
JAPANESE_WITH_ENGLISH_METADATA = (
    "Sprouting after felling of 13-years-old Betula platyphylla "
    "var. japonica stems. "
    "図1: 萌芽数の経時変化 結果として、伐採後3年間で平均萌芽数は12.3本/株となり、"
    "樹高は最大2.1mに達した。考察では、樹齢と萌芽性能の関係について議論する。"
    "本研究は北海道道央地域における造林試験地で実施された。"
)


@pytest.mark.parametrize(
    "text,expected",
    [
        (ENGLISH, "en"),
        (SPANISH, "es"),
        (GERMAN, "de"),
        (JAPANESE, "ja"),
        (JAPANESE_WITH_ENGLISH_METADATA, "ja"),
    ],
)
def test_detect_language_long_text(text, expected):
    assert detect_language(text) == expected


def test_detect_language_below_min_chars_returns_none():
    # Far below the 200-char floor
    assert detect_language("Hello world") is None


def test_detect_language_empty_returns_none():
    assert detect_language("") is None


def test_detect_language_non_string_returns_none():
    assert detect_language(None) is None
    assert detect_language(42) is None


def test_detect_language_custom_min_chars():
    short_english = "We present a deep learning model for diabetic retinopathy."
    # Below default threshold
    assert detect_language(short_english) is None
    # With a relaxed threshold it should work
    assert detect_language(short_english, min_chars=10) == "en"


def test_postprocess_overwrites_hallucinated_language():
    """Even if the LLM emits a wrong language, post-process should
    overwrite it with the heuristic's detection from the raw text."""
    from poster2json.extract import _postprocess_json

    # Simulate the figshare bug: model emitted en, but body is Japanese
    extraction = {"language": "en"}
    out = _postprocess_json(extraction, raw_text=JAPANESE_WITH_ENGLISH_METADATA)
    assert out["language"] == "ja"


def test_postprocess_nullifies_language_when_undetectable():
    """When raw_text is too short, language should be set to None
    rather than preserving whatever the LLM hallucinated."""
    from poster2json.extract import _postprocess_json

    extraction = {"language": "en"}
    out = _postprocess_json(extraction, raw_text="Too short.")
    assert out["language"] is None
