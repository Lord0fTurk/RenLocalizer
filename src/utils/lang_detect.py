"""Offline source-language detection (py3langid, BSD-3-Clause).

The raw ``py3langid.classify()`` returns an unnormalised log-probability, so a
caller cannot tell a confident answer from a guess. Visual-novel samples are
full of character names, UI words and markup ("Mio Akira Sakura", "{b}Day 1{/b}")
which the model happily labels as Shona or Uzbek. A wrong source language is
then applied to the whole run, so this module only answers when it is sure and
returns ``None`` otherwise (callers keep ``"auto"``).
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Iterable, Optional, Tuple

logger = logging.getLogger("RenLocalizer")

MIN_CONFIDENCE = 0.90
MIN_WORDS_PER_SAMPLE = 3
MIN_SAMPLES = 8
MAX_SAMPLES = 60

# Ren'Py text tags, interpolations and RenLocalizer placeholders.
_MARKUP_RE = re.compile(r"\{[^{}]*\}|\[[^\[\]]*\]|⟦[^⟧]*⟧|<ph\b[^>]*>.*?</ph>|%\(?\w*\)?[sd]")
_WS_RE = re.compile(r"\s+")

_identifier = None
_identifier_lock = threading.Lock()
_identifier_failed = False


def _get_identifier():
    global _identifier, _identifier_failed
    if _identifier is not None or _identifier_failed:
        return _identifier
    with _identifier_lock:
        if _identifier is None and not _identifier_failed:
            try:
                from py3langid.langid import LanguageIdentifier, MODEL_FILE

                _identifier = LanguageIdentifier.from_model_file(MODEL_FILE, norm_probs=True)
            except Exception as exc:  # ImportError, or model data missing in a frozen build
                _identifier_failed = True
                logger.debug("py3langid unavailable: %s", exc)
    return _identifier


def clean_sample(text: str) -> str:
    return _WS_RE.sub(" ", _MARKUP_RE.sub(" ", text or "")).strip()


def build_detection_sample(texts: Iterable[str], max_samples: int = MAX_SAMPLES) -> Optional[str]:
    """Join a spread of sentence-like lines; None when there is too little prose."""
    cleaned = [c for c in (clean_sample(t) for t in texts) if len(c.split()) >= MIN_WORDS_PER_SAMPLE]
    if len(cleaned) < MIN_SAMPLES:
        return None
    # Spread over the whole project instead of the first lines, which are
    # usually options/screens strings and character names.
    step = max(1, len(cleaned) // max_samples)
    return " ".join(cleaned[::step][:max_samples])


def classify_with_confidence(text: str) -> Optional[Tuple[str, float]]:
    identifier = _get_identifier()
    if identifier is None or not text:
        return None
    try:
        lang, prob = identifier.classify(text)
        return str(lang).lower(), float(prob)
    except Exception as exc:
        logger.debug("py3langid classify failed: %s", exc)
        return None


def detect_source_language(
    texts: Iterable[str],
    min_confidence: float = MIN_CONFIDENCE,
) -> Optional[str]:
    """ISO 639-1 code when confident, else None."""
    sample = build_detection_sample(texts)
    if sample is None:
        return None
    result = classify_with_confidence(sample)
    if result is None:
        return None
    lang, prob = result
    if prob < min_confidence:
        logger.info("Offline language detection not confident (%s, p=%.2f); keeping 'auto'", lang, prob)
        return None
    logger.info("Offline language detection: %s (p=%.3f)", lang, prob)
    return lang
