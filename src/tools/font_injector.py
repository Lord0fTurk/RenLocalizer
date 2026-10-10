# -*- coding: utf-8 -*-
"""
Font Injector Module (Google Fonts API Integration)
===================================================

Automatically downloads and injects compatible fonts for specific languages 
into Ren'Py projects. Uses Google Fonts download endpoint.
"""

import os
import requests
import logging
import zipfile
import io
import shutil
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Any

logger = logging.getLogger(__name__)

# Mapping: Language Code -> ordered fallback candidates (Font Family, Is RTL?)
FONT_CANDIDATES: Dict[str, Tuple[Tuple[str, bool], ...]] = {
    # RTL Languages
    "fa": (("Vazirmatn", True), ("Noto Sans Arabic", True), ("Sahel", True)),
    "ar": (("Noto Sans Arabic", True), ("Cairo", True), ("Tajawal", True)),
    "he": (("Noto Sans Hebrew", True), ("Rubik", True), ("Heebo", True)),
    "ur": (("Noto Sans Arabic", True), ("Gulzar", True)),
    # CJK Languages
    "ja": (("Noto Sans JP", False), ("M PLUS 1p", False), ("Kosugi Maru", False)),
    "zh": (("Noto Sans SC", False),),
    "zh_tw": (("Noto Sans TC", False),),
    "ko": (("Noto Sans KR", False), ("Nanum Gothic", False)),
    # Cyrillic
    "ru": (("Noto Sans", False), ("PT Sans", False), ("Ubuntu", False)),
    "uk": (("Noto Sans", False), ("PT Sans", False), ("Ubuntu", False)),
    "be": (("Noto Sans", False), ("PT Sans", False)),
    # Southeast Asian & Indic
    "th": (("Noto Sans Thai", False), ("Sarabun", False), ("Prompt", False)),
    "vi": (("Be Vietnam Pro", False), ("Noto Sans", False), ("Inter", False)),
    "id": (("Noto Sans", False), ("Inter", False), ("Open Sans", False)),
    "ms": (("Noto Sans", False), ("Inter", False), ("Open Sans", False)),
    "hi": (("Noto Sans Devanagari", False),),
    "bn": (("Noto Sans Bengali", False),),
    # Greek & European Latin
    "el": (("Noto Sans", False), ("Roboto", False)),
    "tr": (("Noto Sans", False), ("Inter", False), ("Open Sans", False)),
    "pl": (("Noto Sans", False), ("Inter", False), ("Roboto", False)),
    "cs": (("Noto Sans", False), ("Inter", False), ("Roboto", False)),
    "hu": (("Noto Sans", False), ("Inter", False), ("Roboto", False)),
    "ro": (("Noto Sans", False), ("Inter", False), ("Roboto", False)),
    "en": (("Noto Sans", False), ("Inter", False), ("Open Sans", False)),
    "fr": (("Noto Sans", False), ("Inter", False), ("Open Sans", False)),
    "de": (("Noto Sans", False), ("Inter", False), ("Open Sans", False)),
    "es": (("Noto Sans", False), ("Inter", False), ("Open Sans", False)),
    "it": (("Noto Sans", False), ("Inter", False), ("Open Sans", False)),
    "pt": (("Noto Sans", False), ("Inter", False), ("Open Sans", False)),
    "pt_br": (("Noto Sans", False), ("Inter", False), ("Open Sans", False)),
}

LANG_NAME_TO_CODE: Dict[str, str] = {
    # Turkish
    "turkish": "tr", "tur": "tr", "tr": "tr",
    # Russian & Cyrillic
    "russian": "ru", "rus": "ru", "ru": "ru",
    "ukrainian": "uk", "ukr": "uk", "uk": "uk",
    "belarusian": "be", "bel": "be", "be": "be",
    # Japanese
    "japanese": "ja", "jpn": "ja", "japan": "ja", "nihongo": "ja", "ja": "ja", "jp": "ja",
    # Korean
    "korean": "ko", "kor": "ko", "korea": "ko", "hangul": "ko", "ko": "ko", "kr": "ko",
    # Chinese (Simplified)
    "chinese": "zh", "chi": "zh", "zho": "zh", "zh": "zh",
    "schinese": "zh", "chinese_s": "zh", "chinese_simplified": "zh",
    "simplified_chinese": "zh", "zh_cn": "zh", "zh_hans": "zh", "zh_sg": "zh", "zh_s": "zh",
    # Chinese (Traditional)
    "tchinese": "zh_tw", "chinese_t": "zh_tw", "chinese_traditional": "zh_tw",
    "traditional_chinese": "zh_tw", "zh_tw": "zh_tw", "zh_hant": "zh_tw", "zh_hk": "zh_tw", "zh_t": "zh_tw",
    # RTL Languages
    "arabic": "ar", "ara": "ar", "ar": "ar",
    "persian": "fa", "fas": "fa", "per": "fa", "farsi": "fa", "fa": "fa",
    "hebrew": "he", "heb": "he", "iw": "he", "he": "he",
    "urdu": "ur", "urd": "ur", "ur": "ur",
    # Southeast Asian & Indic
    "thai": "th", "tha": "th", "th": "th",
    "vietnamese": "vi", "vie": "vi", "vi": "vi",
    "indonesian": "id", "ind": "id", "id": "id",
    "malay": "ms", "msa": "ms", "ms": "ms",
    "hindi": "hi", "hin": "hi", "hi": "hi",
    "bengali": "bn", "ben": "bn", "bn": "bn",
    # European / Latin
    "english": "en", "eng": "en", "en": "en",
    "french": "fr", "fra": "fr", "fre": "fr", "francais": "fr", "fr": "fr",
    "german": "de", "deu": "de", "ger": "de", "deutsch": "de", "de": "de",
    "spanish": "es", "spa": "es", "espanol": "es", "castilian": "es", "es": "es",
    "italian": "it", "ita": "it", "italiano": "it", "it": "it",
    "portuguese": "pt", "por": "pt", "portugues": "pt", "pt": "pt",
    "brazilian": "pt_br", "brazilian_portuguese": "pt_br", "pt_br": "pt_br",
    "polish": "pl", "pol": "pl", "polski": "pl", "pl": "pl",
    "czech": "cs", "ces": "cs", "cze": "cs", "cs": "cs",
    "hungarian": "hu", "hun": "hu", "hu": "hu",
    "romanian": "ro", "ron": "ro", "rum": "ro", "ro": "ro",
    "greek": "el", "ell": "el", "gre": "el", "el": "el",
}

GUI_FONT_FIELDS = (
    "text_font", "name_text_font", "interface_text_font",
    "button_text_font", "choice_button_text_font",
    "system_font", "glyph_font",
)

STYLE_FONT_NAMES = (
    "default", "say_dialogue", "say_label", "input", "button_text",
    "choice_button_text", "namebox", "notify_text", "history_text",
    "confirm_prompt_text", "navigation_button_text", "quick_button_text",
)

RTL_STYLE_NAMES = (
    "default", "say_dialogue", "say_label", "input", "button_text",
    "choice_button_text", "history_text", "namebox", "notify_text",
    "confirm_prompt_text", "navigation_button_text", "quick_button_text",
)


def _normalize_lang_code(lang_code: str) -> str:
    cleaned = lang_code.lower().strip().replace(" ", "_").replace("-", "_")
    if cleaned in LANG_NAME_TO_CODE:
        return LANG_NAME_TO_CODE[cleaned]
    # Fallback to prefix before first underscore (e.g. es_ES -> es, pt_PT -> pt)
    base = cleaned.split("_")[0]
    if base in LANG_NAME_TO_CODE:
        return LANG_NAME_TO_CODE[base]
    return base


def _download_font(font_family: str, target_dir: Path) -> Tuple[bool, str]:
    font_id = font_family.lower().strip().replace(' ', '-')
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}

    # Dynamically query available subsets from GWFH API so non-Latin scripts (Arabic, Hebrew, CJK) are retained
    subsets_str = "latin,latin-ext,cyrillic,cyrillic-ext,greek,greek-ext,vietnamese,arabic,hebrew,thai"
    try:
        meta_resp = requests.get(f"https://gwfh.mranftl.com/api/fonts/{font_id}", headers=headers, timeout=10)
        if meta_resp.status_code == 200:
            meta_subsets = meta_resp.json().get("subsets", [])
            if meta_subsets:
                subsets_str = ",".join(meta_subsets)
    except Exception as e:
        logger.debug(f"GWFH metadata query failed for {font_id}: {e}")

    urls = [
        f"https://gwfh.mranftl.com/api/fonts/{font_id}?download=zip&subsets={subsets_str}&variants=regular,400,500,700",
    ]

    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=60)
            if resp.status_code != 200 or len(resp.content) < 1000:
                continue
            z = zipfile.ZipFile(io.BytesIO(resp.content))
            font_files = [f for f in z.namelist() if f.lower().endswith(('.ttf', '.otf'))]
            if not font_files:
                continue
            regulars = [f for f in font_files if "regular" in f.lower() or "-400" in f.lower()]
            best = regulars[0] if regulars else font_files[0]
            target = target_dir / os.path.basename(best)
            with open(target, "wb") as dst:
                shutil.copyfileobj(z.open(best), dst)
            logger.info(f"Downloaded font: {target}")
            return True, os.path.basename(best)
        except Exception as e:
            logger.warning(f"Font download failed ({url}): {e}")
            continue
    return False, ""


def inject_font(game_dir: str, lang_code: str) -> Dict[str, Any]:
    base_lang = _normalize_lang_code(lang_code)

    if base_lang in FONT_CANDIDATES:
        candidates = FONT_CANDIDATES[base_lang]
    else:
        # The table covers ~30 languages; every other one gets the Noto
        # family made for its writing system (Devanagari, Georgian, Thaana,
        # Ethiopic...), RTL when the script is right-to-left.
        from src.tools.lang_scripts import font_candidates
        candidates = tuple(font_candidates(lang_code)[0])
    game_path = Path(game_dir)
    if (game_path / "game").exists():
        game_path = game_path / "game"

    fonts_dir = game_path / "tl" / "renlocalizer_fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)

    font_family = candidates[0][0]
    is_rtl = candidates[0][1]
    font_filename = ""

    for candidate_font, candidate_rtl in candidates:
        ok, fname = _download_font(candidate_font, fonts_dir)
        if ok:
            font_family = candidate_font
            is_rtl = candidate_rtl
            font_filename = fname
            break

    if not font_filename:
        return {"success": False, "message": "Could not download any font candidate."}

    rpy_path = game_path / "zzz_renlocalizer_font.rpy"
    font_rel = f"tl/renlocalizer_fonts/{font_filename}"

    rtl_snippet = ""
    if is_rtl:
        rtl_snippet = f'''    try: gui.language = "unicode"; config.rtl = True
    except Exception: pass
    for _rs in {list(RTL_STYLE_NAMES)}:
        try:
            _rst = getattr(style, _rs, None)
            if _rst:
                try: _rst.language = "unicode"
                except Exception: pass
                try: _rst.reading_order = "wrtl"
                except Exception: pass
        except Exception: pass
'''

    block = f'''
init -999 python:
    if not hasattr(renpy.store, "renlocalizer_fonts"):
        renpy.store.renlocalizer_fonts = {{}}
    if not hasattr(renpy.store, "orig_get_font"):
        renpy.store.orig_get_font = renpy.text.font.get_font
        def renlocalizer_get_font_hook(*args, **kwargs):
            if not args:
                return renpy.store.orig_get_font(*args, **kwargs)
            current_lang = _preferences.language
            fs = renpy.store.renlocalizer_fonts
            if current_lang in fs and args[0] != fs[current_lang].get("Default", ""):
                args = (fs[current_lang]["Default"],) + args[1:]
            return renpy.store.orig_get_font(*args, **kwargs)
        renpy.text.font.get_font = renlocalizer_get_font_hook

translate {lang_code} python:
    if not hasattr(renpy.store, "renlocalizer_fonts"):
        renpy.store.renlocalizer_fonts = {{}}
    renpy.store.renlocalizer_fonts["{lang_code}"] = {{"Default": "{font_rel}"}}
    for _f in {list(GUI_FONT_FIELDS)}:
        try:
            if hasattr(gui, _f): setattr(gui, _f, "{font_rel}")
        except Exception: pass
    for _s in {list(STYLE_FONT_NAMES)}:
        try:
            _st = getattr(style, _s, None)
            if _st: _st.font = "{font_rel}"
        except Exception: pass
{rtl_snippet}    try:
        if hasattr(renpy.text.font, "font_cache"): renpy.text.font.font_cache.clear()
        if hasattr(renpy.text.font, "font_names"): renpy.text.font.font_names.clear()
    except Exception: pass
    style.rebuild()
    try: renpy.restart_interaction()
    except Exception: pass
'''

    with open(rpy_path, 'w', encoding='utf-8') as f:
        f.write(block)

    return {
        "success": True,
        "message": f"Font {font_family} injected for {lang_code}",
        "font": font_family,
        "path": str(rpy_path),
    }
