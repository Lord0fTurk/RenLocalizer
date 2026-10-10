# -*- coding: utf-8 -*-
"""Checks for hand-edited translations.

The editor uses the same rule as the pipeline's stale-entry pass
(``classify_translation_corruption``): a line the editor accepts without a
warning is never reopened and overwritten by the next translation run.
"""
from __future__ import annotations

import re
from typing import List, Optional

from src.core.pipeline.constants import PRINTF_SPEC_RE
from src.core.pipeline.translating import classify_translation_corruption

# Ren'Py text tags, [interpolations] and printf specifiers. "[[" and "{{"
# are escaped literal brackets, not code.
_TOKEN_RE = re.compile(
    r"(?<!\{)\{(?!\{)[^{}]*\}|(?<!\[)\[(?!\[)[^\[\]]*\]|" + PRINTF_SPEC_RE.pattern
)

STATUS_EMPTY = "empty"
STATUS_SOURCE_COPY = "source_copy"
STATUS_TRANSLATED = "translated"


def code_tokens(text: str) -> List[str]:
    """Tags, variables and format specifiers in *text*, unique, in order."""
    return list(dict.fromkeys(_TOKEN_RE.findall(text or "")))


def translation_status(original: str, translated: str) -> str:
    trans = (translated or "").strip()
    if not trans:
        return STATUS_EMPTY
    if trans == (original or "").strip():
        return STATUS_SOURCE_COPY
    return STATUS_TRANSLATED


def find_problem(original: str, translated: str) -> Optional[str]:
    """Reason code the pipeline would reject this translation for, or None."""
    if translation_status(original, translated) != STATUS_TRANSLATED:
        return None
    return classify_translation_corruption(original, translated)
