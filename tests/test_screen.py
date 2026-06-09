"""Unit tests for poster2json.screen (PosterSentry pre-screening gate).

These tests never load the real classifier or a real PDF (the PosterSentry
singleton is faked via monkeypatch), so they run on CPU in CI without GPU,
model weights, or network access.
"""

import pytest

from poster2json import screen


# --- Fakes ------------------------------------------------------------------


class _FakeSentry:
    """Stand-in for a warm PosterSentry returning a fixed poster probability."""

    def __init__(self, confidence):
        self.confidence = confidence
        self.classified = []

    def classify(self, pdf_path):
        self.classified.append(pdf_path)
        # Mirror PosterSentry.classify: confidence == poster probability.
        return {"confidence": self.confidence, "is_poster": self.confidence > 0.5}


def _use_fake(monkeypatch, confidence):
    fake = _FakeSentry(confidence)
    monkeypatch.setattr(screen, "_get_sentry", lambda: fake)
    return fake


# --- screening_enabled_default ---------------------------------------------


def test_enabled_default_when_unset(monkeypatch):
    monkeypatch.delenv("POSTER2JSON_POSTER_SENTRY", raising=False)
    assert screen.screening_enabled_default() is True


@pytest.mark.parametrize("val", ["off", "0", "false", "no", "OFF", "False"])
def test_disabled_by_falsy_env(monkeypatch, val):
    monkeypatch.setenv("POSTER2JSON_POSTER_SENTRY", val)
    assert screen.screening_enabled_default() is False


@pytest.mark.parametrize("val", ["on", "1", "true", "yes", ""])
def test_enabled_by_truthy_or_blank_env(monkeypatch, val):
    monkeypatch.setenv("POSTER2JSON_POSTER_SENTRY", val)
    assert screen.screening_enabled_default() is True


# --- screening_threshold ----------------------------------------------------


def test_threshold_default_when_unset(monkeypatch):
    monkeypatch.delenv("POSTER2JSON_POSTER_SENTRY_THRESHOLD", raising=False)
    assert screen.screening_threshold() == screen.DEFAULT_THRESHOLD


def test_threshold_parsed_from_env(monkeypatch):
    monkeypatch.setenv("POSTER2JSON_POSTER_SENTRY_THRESHOLD", "0.8")
    assert screen.screening_threshold() == 0.8


def test_threshold_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("POSTER2JSON_POSTER_SENTRY_THRESHOLD", "not-a-number")
    assert screen.screening_threshold() == screen.DEFAULT_THRESHOLD


@pytest.mark.parametrize("raw,expected", [("1.5", 1.0), ("-0.3", 0.0)])
def test_threshold_clamped(monkeypatch, raw, expected):
    monkeypatch.setenv("POSTER2JSON_POSTER_SENTRY_THRESHOLD", raw)
    assert screen.screening_threshold() == expected


# --- not_a_poster_error -----------------------------------------------------


def test_not_a_poster_error_shape():
    err = screen.not_a_poster_error(0.1234, 0.5)
    assert err["errorCode"] == "NOT_A_POSTER"
    assert err["errorCode"] == screen.NOT_A_POSTER_CODE
    assert err["failedStep"] == "poster_sentry"
    assert err["isPoster"] is False
    assert err["posterSentryConfidence"] == 0.1234
    assert err["posterSentryThreshold"] == 0.5
    # The human-readable reason must make the non-poster cause obvious.
    assert "error" in err
    assert "non-poster" in err["error"].lower()


# --- screen_poster ----------------------------------------------------------


def test_screen_poster_accepts_poster(monkeypatch):
    monkeypatch.delenv("POSTER2JSON_POSTER_SENTRY_THRESHOLD", raising=False)
    fake = _use_fake(monkeypatch, confidence=0.97)
    assert screen.screen_poster("poster.pdf") is None
    assert fake.classified == ["poster.pdf"]


def test_screen_poster_rejects_non_poster(monkeypatch):
    monkeypatch.delenv("POSTER2JSON_POSTER_SENTRY_THRESHOLD", raising=False)
    _use_fake(monkeypatch, confidence=0.12)
    rejection = screen.screen_poster("paper.pdf")
    assert rejection is not None
    assert rejection["errorCode"] == "NOT_A_POSTER"
    assert rejection["posterSentryConfidence"] == 0.12
    assert rejection["posterSentryThreshold"] == screen.DEFAULT_THRESHOLD


def test_screen_poster_threshold_boundary_is_poster(monkeypatch):
    # confidence == threshold accepts (>=), giving borderline files the benefit.
    _use_fake(monkeypatch, confidence=0.5)
    assert screen.screen_poster("borderline.pdf", threshold=0.5) is None


def test_screen_poster_respects_explicit_threshold(monkeypatch):
    # A 0.6 poster probability passes the default but fails a stricter 0.8 gate.
    _use_fake(monkeypatch, confidence=0.6)
    assert screen.screen_poster("p.pdf", threshold=0.5) is None
    _use_fake(monkeypatch, confidence=0.6)
    assert screen.screen_poster("p.pdf", threshold=0.8) is not None


def test_screen_poster_fails_open_on_classifier_error(monkeypatch):
    def _boom():
        raise RuntimeError("model weights missing")

    monkeypatch.setattr(screen, "_get_sentry", _boom)
    # A classifier outage must never reject a legitimate poster.
    assert screen.screen_poster("poster.pdf") is None
