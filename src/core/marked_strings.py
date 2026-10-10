# -*- coding: utf-8 -*-
"""Strings the game's author marked as translatable with _(), __(), ___() or _p().

Mirrors Ren'Py's own collector (renpy/translation/scanstrings.py): every
string literal passed to those functions is a string translation, whatever
it looks like. Ren'Py applies no heuristics; an old/new entry that is never
displayed simply stays unused. RenLocalizer's code/identifier heuristics
therefore must not drop these strings, only the few cases below where a
machine translation can do nothing useful.
"""
from __future__ import annotations

import ast
import re
from typing import Iterable, Iterator, List, Optional, Tuple

# Same shape as Ren'Py's STRING_RE: a marker function with one or more
# adjacent string literals as its only argument.
_LITERAL = (
    r'[uU]?(?:"""(?:[^"\\]|\\.|"(?!""))*"""'
    r"|'''(?:[^'\\]|\\.|'(?!''))*'''"
    r'|"(?:[^"\\\n]|\\.)*"'
    r"|'(?:[^'\\\n]|\\.)*')"
)
MARKED_STRING_RE = re.compile(
    r'\b(?P<func>___|__|_p|_)\s*\(\s*(?P<lits>' + _LITERAL + r'(?:\s*' + _LITERAL + r')*)\s*\)',
    re.S,
)
_CHARACTER_CALL_RE = re.compile(r'Character\s*\(\s*$')

# Format directives of strftime ("%A, %B %d %Y"). Ren'Py translates the
# weekday/month names on their own ("{#weekday}Monday"), so these patterns
# are left as they are.
_STRFTIME_RE = re.compile(r'%[aAbBcdHIjmMpSUwWxXyYZ]')
_TAG_OR_VAR_RE = re.compile(r'\{[^{}]*\}|\[[^\[\]]*\]')
_IDENTIFIER_RE = re.compile(r'^[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+$')
_PATH_OR_URL_RE = re.compile(
    r'^(?:[a-z]+://|www\.)\S+$'
    r'|^[\w\-.]+(?:/[\w\-.]+)+$'
    r'|^[\w\-]+\.(?:png|jpe?g|webp|ogg|mp3|wav|opus|ttf|otf|rpy|rpyc|json|txt)$',
    re.I,
)


def strip_comments(source: str) -> str:
    """Remove # comments outside string literals, keeping line numbers."""
    out: List[str] = []
    i = 0
    n = len(source)
    quote = ''
    while i < n:
        ch = source[i]
        if quote:
            if ch == '\\':
                out.append(source[i:i + 2])
                i += 2
                continue
            if source.startswith(quote, i):
                out.append(quote)
                i += len(quote)
                quote = ''
                continue
            if ch == '\n' and len(quote) == 1:
                quote = ''  # unterminated single-line string
            out.append(ch)
            i += 1
            continue
        if ch in '"\'':
            quote = source[i:i + 3] if source.startswith(ch * 3, i) else ch
            out.append(quote)
            i += len(quote)
            continue
        if ch == '#':
            end = source.find('\n', i)
            if end < 0:
                break
            i = end
            continue
        out.append(ch)
        i += 1
    return ''.join(out)


def reformat_p(s: str) -> str:
    """Ren'Py's _p() (renpy/minstore.py, MIT, (c) Tom Rothamel), so the old
    string matches what the game displays."""
    lines = [i.strip() for i in s.split("\n")]
    if lines and not lines[0]:
        lines.pop(0)
    if lines and not lines[-1]:
        lines.pop()
    rv = ""
    para: List[str] = []
    for line in lines:
        if not line:
            rv += " ".join(para) + "\n\n"
            para = []
        elif re.search(r"\{p[^}]*\}$", line):
            para.append(line)
            rv += " ".join(para)
            para = []
        else:
            para.append(line)
    rv += " ".join(para)
    return rv


def _evaluate(func: str, literals: str) -> Optional[str]:
    try:
        value = ast.literal_eval("(" + literals + ")")
    except (ValueError, SyntaxError):
        return None
    if not isinstance(value, str):
        return None
    return reformat_p(value) if func == "_p" else value


def scan_source(source: str, first_line: int = 1) -> Iterator[Tuple[str, int, bool]]:
    """Yield (text, line number, is_character_name) for every marked string."""
    code = strip_comments(source)
    for m in MARKED_STRING_RE.finditer(code):
        text = _evaluate(m.group('func'), m.group('lits'))
        if not text:
            continue
        line = first_line + code.count('\n', 0, m.start())
        is_name = bool(_CHARACTER_CALL_RE.search(code[max(0, m.start() - 40):m.start()]))
        yield text, line, is_name


def worth_translating(text: str) -> bool:
    """False only where a translation cannot help (no letters, date formats,
    identifiers, paths). Everything else the author marked is translated."""
    core = _TAG_OR_VAR_RE.sub('', text or '').strip()
    if not any(ch.isalpha() for ch in core):
        return False
    if len(_STRFTIME_RE.findall(text)) >= 2:
        return False
    if _IDENTIFIER_RE.match(core) or _PATH_OR_URL_RE.match(core):
        return False
    return True


def collect_from_game_dir(game_dir: str, names_allowed: bool = False) -> set:
    """Marked strings worth translating in a game's own .rpy files
    (tl/, renpy/, saves and RenLocalizer's generated files are skipped)."""
    import os

    from src.core.constants import is_renlocalizer_generated_script
    from src.utils.encoding import read_text_safely
    from pathlib import Path

    found: set = set()
    if not game_dir or not os.path.isdir(game_dir):
        return found
    for root, dirs, files in os.walk(game_dir):
        dirs[:] = [d for d in dirs if d.lower() not in ('tl', 'renpy', 'cache', 'saves', '__pycache__')]
        for name in files:
            if not name.lower().endswith('.rpy') or is_renlocalizer_generated_script(name):
                continue
            source = read_text_safely(Path(root) / name)
            if not source or '_' not in source:
                continue
            for text, _, is_name in scan_source(source):
                if (names_allowed or not is_name) and worth_translating(text):
                    found.add(text)
    return found


def scan_texts(sources: Iterable[str]) -> List[Tuple[str, bool]]:
    """Marked strings (text, is_character_name) from code snippets such as .rpyc expressions."""
    out: List[Tuple[str, bool]] = []
    for source in sources:
        if source and '_' in source and '(' in source:
            out.extend((text, is_name) for text, _, is_name in scan_source(source))
    return out
