# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Structural checks for Ren'Py text tags and replacement characters in translated strings.

The rules below mirror ``renpy.text.extras.check_text_tags`` and
``renpy.text.textsupport.tokenize`` of Ren'Py 8.0.3:

* ``{{`` is a literal brace, ``{`` ... ``}`` is a tag;
* ``{#...}`` tags are ignored;
* the argument after ``=`` is not part of the tag name;
* a closing tag must close the most recently opened tag;
* tags that take a closing tag must be closed before the end.

Unknown (custom) tags are treated as self-closing unless the source string
itself closes them, so a game-specific tag is never rejected just because it
is unknown here.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Set, Tuple

# Ren'Py 8.0.3 renpy/text/extras.py ``text_tags``: True = needs a closing tag.
RENPY_PAIRED_TAGS: Set[str] = {
    "alpha", "alt", "art", "b", "i", "u", "a", "plain", "font", "color",
    "outlinecolor", "size", "noalt", "s", "rt", "rb", "k", "cps", "",
}
RENPY_SELF_CLOSING_TAGS: Set[str] = {
    "done", "image", "p", "w", "fast", "nw", "space", "vspace",
}

REPLACEMENT_CHAR = "\ufffd"


def tokenize_tags(text: str) -> Tuple[List[str], Optional[str]]:
    """Return (tag bodies in order, error). Mirrors Ren'Py's tokenizer."""
    tags: List[str] = []
    i = 0
    n = len(text or "")
    while i < n:
        ch = text[i]
        if ch != "{":
            i += 1
            continue
        if i + 1 < n and text[i + 1] == "{":
            i += 2  # literal brace
            continue
        end = text.find("}", i + 1)
        if end < 0:
            return tags, "unterminated_tag"
        body = text[i + 1:end]
        if body == "":
            return tags, "empty_tag"
        tags.append(body)
        i = end + 1
    return tags, None


def _tag_name(body: str) -> str:
    return body.split("=", 1)[0]


def paired_tags_for(source: str) -> Set[str]:
    """Paired tag names valid for this source (Ren'Py's + custom ones it closes)."""
    paired = set(RENPY_PAIRED_TAGS)
    tags, _ = tokenize_tags(source or "")
    for body in tags:
        if body.startswith("/"):
            paired.add(_tag_name(body[1:]))
    return paired


def tag_structure_error(text: str, paired: Optional[Iterable[str]] = None) -> Optional[str]:
    """Return a short reason when Ren'Py would reject the tags of ``text``."""
    paired_set = set(paired) if paired is not None else set(RENPY_PAIRED_TAGS)
    tags, error = tokenize_tags(text or "")
    if error:
        return error
    stack: List[str] = []
    for body in tags:
        if body.startswith("#"):
            continue
        name = _tag_name(body)
        if name.startswith("/"):
            closing = name[1:]
            if not stack:
                return f"close_without_open:{closing}"
            if stack[-1] != closing:
                return f"close_mismatch:{closing}!={stack[-1]}"
            stack.pop()
            continue
        if name in paired_set:
            stack.append(name)
    if stack:
        return "left_open:" + ",".join(stack)
    return None


def tag_structure_regression(source: str, translated: str) -> Optional[str]:
    """Reason when the translation breaks tag structure that the source keeps.

    Returns None when the source itself is not well formed (nothing to
    compare against: the multiset check still applies) or when the
    translation is valid.
    """
    paired = paired_tags_for(source)
    if tag_structure_error(source, paired) is not None:
        # Source already malformed (or uses open-ended tags on purpose):
        # require at least the same tag sequence as the source.
        src_tags, _ = tokenize_tags(source or "")
        out_tags, err = tokenize_tags(translated or "")
        if err:
            return err
        if [t for t in src_tags if not t.startswith("#")] != [t for t in out_tags if not t.startswith("#")]:
            return "tag_order_changed"
        return None
    return tag_structure_error(translated, paired)


def introduces_replacement_char(source: str, translated: str) -> bool:
    """True when the translation carries U+FFFD that the source does not.

    U+FFFD is what a decoder writes for bytes it could not read; it is never
    a valid translation result (e.g. "Actualmente \ufffd\ufffd[em_love] de 17.").
    """
    return REPLACEMENT_CHAR in (translated or "") and REPLACEMENT_CHAR not in (source or "")
