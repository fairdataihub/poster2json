"""
PosterSentry pre-screening
==========================

The single place PosterSentry is wired into poster2json. It runs as a gate at
the front of :func:`poster2json.extract.extract_poster`: a confident non-poster
(a mislabeled paper, slide deck, abstract booklet, etc.) is rejected *before*
the expensive LLM extraction stage, so junk uploads fail fast with an obvious
reason instead of yielding meaningless metadata.

Failure contract (the reason must be obvious downstream)
--------------------------------------------------------
A rejection is returned as an ordinary extraction-result dict carrying an
``error`` key, so existing consumers that branch on ``"error" in result``
(e.g. the posters.science job worker, which then marks the ExtractionJob
``failed`` and stores ``error`` verbatim) need no changes. On top of that
human-readable string the dict carries machine-readable fields so the API and
the posters.science platform can distinguish "this file isn't a poster" from a
generic extraction failure and surface it to the submitter:

    {
        "error": "PosterSentry classified this submission as a non-poster ...",
        "errorCode": "NOT_A_POSTER",     # stable, branch on this
        "failedStep": "poster_sentry",
        "isPoster": False,
        "posterSentryConfidence": 0.18,  # poster probability [0, 1]
        "posterSentryThreshold": 0.5,
    }

Fail-open
---------
Any error *running* the classifier (model not installed, weights missing, a
corrupt PDF) is swallowed and the submission proceeds to extraction. A
classifier outage must never reject a legitimate poster; only a confident
non-poster verdict does.

Configuration
-------------
- ``POSTER2JSON_POSTER_SENTRY``            on/off (default: on)
- ``POSTER2JSON_POSTER_SENTRY_THRESHOLD``  poster-probability cutoff (default: 0.5)
"""

import os
from typing import Any, Dict, Optional

# Stable, machine-readable failure code for the non-poster case. Downstream
# (posters.science API / job worker) branches on result["errorCode"] to tell a
# non-poster apart from a generic extraction failure. Do not rename without
# coordinating with the platform.
NOT_A_POSTER_CODE = "NOT_A_POSTER"

# Names the pipeline stage that rejected the submission, for log/UI clarity.
FAILED_STEP = "poster_sentry"

# Poster probability at or above which a submission is accepted as a poster.
DEFAULT_THRESHOLD = 0.5

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}

# Lazily-initialised PosterSentry singleton. Initialising loads the model2vec
# text embedder and the classifier head once; we keep it warm across calls.
_sentry: Optional[Any] = None


def screening_enabled_default() -> bool:
    """Whether screening runs when the caller does not pass ``screen_posters``.

    Defaults to on; set ``POSTER2JSON_POSTER_SENTRY`` to a falsy value
    (0/false/no/off) to disable it for a deployment.
    """
    val = os.environ.get("POSTER2JSON_POSTER_SENTRY", "").strip().lower()
    if val in _FALSY:
        return False
    return True


def screening_threshold() -> float:
    """Poster-probability cutoff, read from the environment.

    Below this value a submission is rejected as a non-poster. Defaults to
    :data:`DEFAULT_THRESHOLD`; an unparseable value falls back to the default.
    The result is clamped to ``[0.0, 1.0]``.
    """
    raw = os.environ.get("POSTER2JSON_POSTER_SENTRY_THRESHOLD", "").strip()
    if not raw:
        return DEFAULT_THRESHOLD
    try:
        threshold = float(raw)
    except ValueError:
        from .extract import log

        log(f"PosterSentry: invalid POSTER2JSON_POSTER_SENTRY_THRESHOLD "
            f"{raw!r}; using {DEFAULT_THRESHOLD}")
        return DEFAULT_THRESHOLD
    return min(max(threshold, 0.0), 1.0)


def not_a_poster_error(confidence: float, threshold: float) -> Dict[str, Any]:
    """Build the NOT_A_POSTER failure result for a confident non-poster.

    Returns a plain extraction-result dict with an ``error`` key (so existing
    ``"error" in result`` consumers fail the job) plus machine-readable fields
    for callers that want to branch on the non-poster case specifically.
    """
    return {
        "error": (
            f"PosterSentry classified this submission as a non-poster "
            f"(poster probability {confidence:.2f}, below the {threshold:.2f} "
            f"threshold). Skipped LLM extraction because the file does not "
            f"appear to be a scientific poster."
        ),
        "errorCode": NOT_A_POSTER_CODE,
        "failedStep": FAILED_STEP,
        "isPoster": False,
        "posterSentryConfidence": round(float(confidence), 4),
        "posterSentryThreshold": round(float(threshold), 4),
    }


def _get_sentry():
    """Return the warm PosterSentry singleton, initialising it on first use.

    Imports ``poster_sentry`` lazily so the dependency is only required when
    screening actually runs (and so importing this module stays cheap).
    """
    global _sentry
    if _sentry is None:
        from poster_sentry import PosterSentry

        sentry = PosterSentry()
        sentry.initialize()
        _sentry = sentry
    return _sentry


def screen_poster(
    pdf_path: str, threshold: Optional[float] = None
) -> Optional[Dict[str, Any]]:
    """Screen a PDF with PosterSentry before extraction.

    Returns a NOT_A_POSTER error dict (see :func:`not_a_poster_error`) when the
    file is a confident non-poster, or ``None`` to proceed with extraction.

    Fails open: any error *running* the classifier is logged and ``None`` is
    returned, so a classifier outage never rejects a legitimate poster.

    Args:
        pdf_path: Path to the PDF to screen.
        threshold: Poster-probability cutoff. Defaults to
            :func:`screening_threshold` (the ``POSTER2JSON_POSTER_SENTRY_THRESHOLD``
            env var, else :data:`DEFAULT_THRESHOLD`).
    """
    from .extract import log

    threshold = screening_threshold() if threshold is None else threshold

    try:
        result = _get_sentry().classify(pdf_path)
    except Exception as exc:  # noqa: BLE001 - fail open on any classifier error
        log(f"PosterSentry screening unavailable ({exc}); proceeding with extraction")
        return None

    # PosterSentry returns confidence == poster probability. Apply our own
    # threshold rather than its built-in is_poster so the env override is honored.
    confidence = float(result.get("confidence", 0.0))
    is_poster = confidence >= threshold
    log(f"PosterSentry: poster probability {confidence:.4f} "
        f"(threshold {threshold:.2f}) -> {'poster' if is_poster else 'NON-POSTER'}")

    if is_poster:
        return None
    return not_a_poster_error(confidence, threshold)
