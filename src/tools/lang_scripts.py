# -*- coding: utf-8 -*-
"""
Language → writing system data for the font tools.

The font check and the font injector used hand-written tables for ~21
languages; for the other ~114 of the 135 languages RenLocalizer translates to,
every font was reported incompatible and no font could be injected. This
module covers all of them:

* ``resolve_lang_code`` maps a Ren'Py language name / API code / English name
  ("persian", "fa", "Persian") to the API code using the app's own language
  table.
* ``script_of`` gives the writing system; ``script_sample_chars`` and
  ``script_fonts`` give characters to test and Google Fonts families to use.
* ``collect_translation_chars`` returns the characters a game's translation
  actually uses — the most accurate thing to check a font against, for any
  language, with no table at all.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# API code -> script. Anything not listed is written in Latin script.
_SCRIPT_BY_CODE: Dict[str, str] = {
    **dict.fromkeys(("ar", "fa", "ur", "ps", "sd", "ug", "ckb"), "Arabic"),
    **dict.fromkeys(("he", "iw", "yi"), "Hebrew"),
    "dv": "Thaana",
    **dict.fromkeys(("hi", "mr", "ne", "sa", "bho", "mai", "doi", "gom"), "Devanagari"),
    **dict.fromkeys(("bn", "as"), "Bengali"),
    "pa": "Gurmukhi",
    "gu": "Gujarati",
    "kn": "Kannada",
    "ml": "Malayalam",
    "ta": "Tamil",
    "te": "Telugu",
    "or": "Oriya",
    "si": "Sinhala",
    "th": "Thai",
    "lo": "Lao",
    "km": "Khmer",
    "my": "Myanmar",
    "ka": "Georgian",
    "hy": "Armenian",
    **dict.fromkeys(("am", "ti"), "Ethiopic"),
    "mni-mtei": "Meetei",
    **dict.fromkeys(("ru", "uk", "be", "bg", "mk", "sr", "kk", "ky", "mn", "tg", "tt", "tyv"), "Cyrillic"),
    "el": "Greek",
    "ja": "Japanese",
    **dict.fromkeys(("zh", "zh-cn"), "HanSimplified"),
    "zh-tw": "HanTraditional",
    "ko": "Hangul",
}

# Letter ranges sampled when a game has no translation yet to learn from.
_SCRIPT_RANGES: Dict[str, Tuple[Tuple[int, int], ...]] = {
    "Latin": ((0x41, 0x5A), (0x61, 0x7A)),
    "Cyrillic": ((0x410, 0x44F),),
    "Greek": ((0x391, 0x3A9), (0x3B1, 0x3C9)),
    "Arabic": ((0x621, 0x64A), (0x67E, 0x67E), (0x686, 0x686), (0x698, 0x698), (0x6AF, 0x6AF), (0x6CC, 0x6CC)),
    "Hebrew": ((0x5D0, 0x5EA),),
    "Thaana": ((0x780, 0x7A5),),
    "Devanagari": ((0x905, 0x939),),
    "Bengali": ((0x985, 0x9B9),),
    "Gurmukhi": ((0xA05, 0xA39),),
    "Gujarati": ((0xA85, 0xAB9),),
    "Oriya": ((0xB05, 0xB39),),
    "Tamil": ((0xB85, 0xBB9),),
    "Telugu": ((0xC05, 0xC39),),
    "Kannada": ((0xC85, 0xCB9),),
    "Malayalam": ((0xD05, 0xD39),),
    "Sinhala": ((0xD85, 0xDC6),),
    "Thai": ((0xE01, 0xE2E),),
    "Lao": ((0xE81, 0xEAE),),
    "Myanmar": ((0x1000, 0x102A),),
    "Georgian": ((0x10D0, 0x10FA),),
    "Armenian": ((0x531, 0x556), (0x561, 0x586)),
    "Ethiopic": ((0x1200, 0x1248),),
    "Khmer": ((0x1780, 0x17B3),),
    "Meetei": ((0xABC0, 0xABE2),),
    "Japanese": ((0x3041, 0x3093), (0x30A1, 0x30F3)),
    "HanSimplified": ((0x4E00, 0x4E3F),),
    "HanTraditional": ((0x4E00, 0x4E3F),),
    "Hangul": ((0xAC00, 0xAC3F),),
}

# Google Fonts families per script (first that downloads wins) and RTL flag.
_SCRIPT_FONTS: Dict[str, Tuple[Tuple[str, ...], bool]] = {
    "Latin": (("Noto Sans", "Inter", "Open Sans"), False),
    "Cyrillic": (("Noto Sans", "PT Sans"), False),
    "Greek": (("Noto Sans", "Roboto"), False),
    "Arabic": (("Noto Sans Arabic", "Vazirmatn", "Cairo"), True),
    "Hebrew": (("Noto Sans Hebrew", "Rubik"), True),
    "Thaana": (("Noto Sans Thaana",), True),
    "Devanagari": (("Noto Sans Devanagari", "Hind"), False),
    "Bengali": (("Noto Sans Bengali", "Hind Siliguri"), False),
    "Gurmukhi": (("Noto Sans Gurmukhi",), False),
    "Gujarati": (("Noto Sans Gujarati",), False),
    "Oriya": (("Noto Sans Oriya",), False),
    "Tamil": (("Noto Sans Tamil",), False),
    "Telugu": (("Noto Sans Telugu",), False),
    "Kannada": (("Noto Sans Kannada",), False),
    "Malayalam": (("Noto Sans Malayalam",), False),
    "Sinhala": (("Noto Sans Sinhala",), False),
    "Thai": (("Noto Sans Thai", "Sarabun"), False),
    "Lao": (("Noto Sans Lao",), False),
    "Myanmar": (("Noto Sans Myanmar",), False),
    "Georgian": (("Noto Sans Georgian",), False),
    "Armenian": (("Noto Sans Armenian",), False),
    "Ethiopic": (("Noto Sans Ethiopic",), False),
    "Khmer": (("Noto Sans Khmer",), False),
    "Meetei": (("Noto Sans Meetei Mayek",), False),
    "Japanese": (("Noto Sans JP", "M PLUS 1p"), False),
    "HanSimplified": (("Noto Sans SC",), False),
    "HanTraditional": (("Noto Sans TC",), False),
    "Hangul": (("Noto Sans KR", "Nanum Gothic"), False),
}

_TAG_RE = re.compile(r"\{[^{}]*\}|\[[^\[\]]*\]")
_QUOTED_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
_ESCAPE_RE = re.compile(r"\\(.)")


@lru_cache(maxsize=1)
def _language_table() -> Dict[str, str]:
    """renpy name / api code / English name (lower-case) -> api code (lower-case)."""
    table: Dict[str, str] = {}
    try:
        from src.utils.config import ConfigManager

        for item in ConfigManager.get_all_languages(None):
            api = str(item.get("api", "")).lower()
            for key in ("renpy", "api", "english"):
                value = str(item.get(key, "")).strip().lower()
                if value and api:
                    table.setdefault(value, api)
                    table.setdefault(value.replace(" ", "_"), api)
    except Exception:
        pass
    return table


def resolve_lang_code(language: str) -> str:
    """'persian' / 'Persian' / 'fa' / 'zh_CN' -> 'fa' / 'zh-cn' (lower-case API code)."""
    raw = (language or "").strip().lower()
    if not raw:
        return ""
    table = _language_table()
    for candidate in (raw, raw.replace("_", "-"), raw.replace("-", "_")):
        if candidate in table:
            return table[candidate]
    # Common Ren'Py folder names the app table does not use ("chinese",
    # "schinese", "tchinese", "jp", "brazilian"...).
    try:
        from src.tools.font_injector import LANG_NAME_TO_CODE

        alias = LANG_NAME_TO_CODE.get(raw.replace("-", "_").replace(" ", "_"))
        if alias:
            return {"zh": "zh-cn", "zh_tw": "zh-tw", "pt_br": "pt"}.get(alias, alias)
    except Exception:
        pass
    return raw.replace("_", "-")


def script_of(language: str) -> str:
    code = resolve_lang_code(language)
    return _SCRIPT_BY_CODE.get(code) or _SCRIPT_BY_CODE.get(code.split("-")[0], "Latin")


@lru_cache(maxsize=None)
def script_sample_chars(script: str) -> str:
    chars = []
    for start, end in _SCRIPT_RANGES.get(script, _SCRIPT_RANGES["Latin"]):
        for cp in range(start, end + 1):
            ch = chr(cp)
            if unicodedata.category(ch).startswith("L"):
                chars.append(ch)
    return "".join(chars)


def script_fonts(script: str) -> Tuple[Tuple[str, ...], bool]:
    return _SCRIPT_FONTS.get(script, _SCRIPT_FONTS["Latin"])


def collect_translation_chars(game_dir: str, language: str) -> Set[str]:
    """Characters used by the translated text in game/tl/<language>.

    Only translation lines are read (``new "..."`` and translated dialogue),
    not the commented source or ``old "..."``; Ren'Py tags and interpolations
    are ignored. Returns an empty set when there is no translation yet.
    """
    lang_dir = _find_tl_dir(game_dir, language)
    if lang_dir is None:
        return set()
    chars: Set[str] = set()
    for path in lang_dir.rglob("*.rpy"):
        try:
            text = path.read_text(encoding="utf-8-sig", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("old "):
                continue
            if stripped.startswith(("translate ", "label ", "init ", "define ", "style ")):
                continue
            for match in _QUOTED_RE.finditer(stripped):
                content = _ESCAPE_RE.sub(r"\1", _TAG_RE.sub("", match.group(1)))
                for ch in content:
                    if not ch.isspace() and not unicodedata.category(ch).startswith("C"):
                        chars.add(ch)
    return chars


def _find_tl_dir(game_dir: str, language: str) -> Optional[Path]:
    tl_root = Path(game_dir) / "tl"
    if not tl_root.is_dir() or not language:
        return None
    wanted = {language.lower(), resolve_lang_code(language)}
    for child in tl_root.iterdir():
        if child.is_dir() and (child.name.lower() in wanted or resolve_lang_code(child.name) in wanted):
            return child
    return None


def font_candidates(language: str) -> Tuple[List[Tuple[str, bool]], str]:
    """Google Fonts candidates (family, is_rtl) for *language*, plus its script."""
    script = script_of(language)
    families, rtl = script_fonts(script)
    return [(family, rtl) for family in families], script
