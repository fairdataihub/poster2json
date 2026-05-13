"""
Heuristic language detection for extracted poster body text.

We detect from the raw OCR/PDF text rather than trusting the LLM. The model
has been observed to emit `language: "en"` for posters whose body is in
Japanese/Spanish/etc. but whose metadata fragments happened to be in
English. Detecting on the body text directly is more reliable.

Returns ISO 639-1 lower-case codes when the detector is confident enough,
or None otherwise -- null is always better than a guessed wrong language.
"""
import hashlib
import json
from pathlib import Path
from typing import Optional


MIN_CHARS = 200
# CJK/Arabic/Cyrillic/etc. encode several bits more per codepoint than Latin
# scripts; 50 non-ASCII codepoints is plenty of signal for confident
# detection. This stops e.g. a 130-char Japanese poster from being skipped.
MIN_NON_ASCII = 50

# Lazy singleton -- lingua's wheel is ~170MB and the detector loads ngram
# models on first detection. Avoid paying that cost at import time.
_detector = None

# Disk-persisted language cache keyed by MD5 of whitespace-collapsed text.
# Avoids re-running lingua on unchanged files across batch re-runs.
LANG_CACHE_PATH = Path.home() / ".cache" / "poster2json" / "lang.json"
_lang_cache = None


def _build_detector():
    global _detector
    if _detector is None:
        from lingua import Language, LanguageDetectorBuilder

        # Set chosen for research-context coverage. Includes major Western
        # European, East Asian, South/Southeast Asian, Middle Eastern, and
        # Slavic languages. Adding more increases model footprint and the
        # risk of close-call false positives between similar languages.
        languages = [
            Language.ARABIC,
            Language.BENGALI,
            Language.CHINESE,
            Language.CZECH,
            Language.DANISH,
            Language.DUTCH,
            Language.ENGLISH,
            Language.FINNISH,
            Language.FRENCH,
            Language.GERMAN,
            Language.GREEK,
            Language.HEBREW,
            Language.HINDI,
            Language.HUNGARIAN,
            Language.INDONESIAN,
            Language.ITALIAN,
            Language.JAPANESE,
            Language.KOREAN,
            Language.BOKMAL,
            Language.NYNORSK,
            Language.POLISH,
            Language.PORTUGUESE,
            Language.ROMANIAN,
            Language.RUSSIAN,
            Language.SPANISH,
            Language.SWEDISH,
            Language.THAI,
            Language.TURKISH,
            Language.UKRAINIAN,
            Language.VIETNAMESE,
        ]
        # `with_minimum_relative_distance(0.10)` makes detect_language_of
        # return None when the top two candidates are within 10% — i.e.
        # ambiguous between e.g. Spanish and Portuguese.
        _detector = (
            LanguageDetectorBuilder.from_languages(*languages)
            .with_minimum_relative_distance(0.10)
            .build()
        )
    return _detector


def _get_lang_cache() -> dict:
    global _lang_cache
    if _lang_cache is None:
        try:
            if LANG_CACHE_PATH.exists():
                _lang_cache = json.loads(LANG_CACHE_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            pass
        if _lang_cache is None:
            _lang_cache = {}
    return _lang_cache


def save_lang_cache():
    """Flush language cache to disk. Call at end of batch processing."""
    if not _lang_cache:
        return
    try:
        LANG_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = LANG_CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(_lang_cache))
        tmp.replace(LANG_CACHE_PATH)
    except OSError:
        pass


def detect_language(text: str, min_chars: int = MIN_CHARS) -> Optional[str]:
    """Return ISO 639-1 lower-case code, or None if undetermined.

    Args:
        text: Raw poster text (OCR or PDF body).
        min_chars: Minimum length (whitespace-collapsed) before attempting
            detection. Defaults to 200; below this the signal is too thin
            and metadata fragments dominate.
    """
    if not isinstance(text, str):
        return None
    cleaned = " ".join(text.split())
    non_ascii = sum(1 for c in cleaned if ord(c) > 0x7F)
    if len(cleaned) < min_chars and non_ascii < MIN_NON_ASCII:
        return None

    text_hash = hashlib.md5(cleaned.encode("utf-8", errors="replace")).hexdigest()
    cache = _get_lang_cache()
    if text_hash in cache:
        return cache[text_hash]

    result = _build_detector().detect_language_of(cleaned)
    lang = result.iso_code_639_1.name.lower() if result else None
    cache[text_hash] = lang
    return lang
