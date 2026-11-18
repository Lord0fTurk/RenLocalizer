# -*- coding: utf-8 -*-
"""
Module-level constants and regex patterns for the translation pipeline.
"""

import re
from typing import Optional


def _get_renpy_to_api_lang():
    """Get Ren'Py to API language mapping from centralized config."""
    try:
        from src.utils.config import ConfigManager
        config = ConfigManager()
        return config.get_renpy_to_api_map()
    except Exception:
        return {
            "turkish": "tr", "english": "en", "german": "de", "french": "fr",
            "spanish": "es", "italian": "it", "portuguese": "pt", "russian": "ru",
            "polish": "pl", "dutch": "nl", "japanese": "ja", "korean": "ko",
            "chinese": "zh", "chinese_s": "zh-CN", "chinese_t": "zh-TW",
            "thai": "th", "vietnamese": "vi", "indonesian": "id", "malay": "ms",
            "hindi": "hi", "persian": "fa", "arabic": "ar", "czech": "cs",
            "danish": "da", "finnish": "fi", "greek": "el", "hebrew": "he",
            "hungarian": "hu", "norwegian": "no", "romanian": "ro", "swedish": "sv",
            "ukrainian": "uk", "bulgarian": "bg", "catalan": "ca", "croatian": "hr",
            "slovak": "sk", "slovenian": "sl", "serbian": "sr",
        }


class _LazyRenpyToApiLangMap:
    def __init__(self):
        self._cache = {}
        self._loaded = False

    def _load(self):
        if not self._loaded:
            self._cache = _get_renpy_to_api_lang()
            self._loaded = True
        return self._cache

    def get(self, key, default=None):
        return self._load().get(key, default)

    def items(self):
        return self._load().items()

    def __iter__(self):
        return iter(self._load())

    def __len__(self):
        return len(self._load())

    def __contains__(self, key):
        return key in self._load()


RENPY_TO_API_LANG = _LazyRenpyToApiLangMap()
 
RTL_LANGUAGES: frozenset = frozenset({
    "arabic", "farsi", "persian", "hebrew", "urdu", "pashto", "sindhi",
    "ar", "fa", "he", "ur", "ps", "sd",
})


def is_rtl_language(lang_code: Optional[str]) -> bool:
    """Check if a given language name or ISO code is Right-to-Left (RTL)."""
    if not lang_code:
        return False
    return lang_code.strip().lower() in RTL_LANGUAGES


CORE_UI_RETRY_STRINGS = {
    "About",
    "Auto",
    "Auto-Forward",
    "Auto-Forward Time",
    "Back",
    "Begin",
    "Clipboard Voicing",
    "Continue",
    "Display",
    "Empty Slot",
    "End Replay",
    "Fast Forward",
    "Fullscreen",
    "Gallery",
    "Help",
    "History",
    "Language",
    "Load",
    "Load Game",
    "Main Menu",
    "Music",
    "Music Volume",
    "Page",
    "Page Down",
    "Page Up",
    "Preferences",
    "Prefs",
    "Q.Load",
    "Q.Save",
    "Quit",
    "Replay",
    "Return",
    "Rollback",
    "Save",
    "Self-Voicing",
    "Skip",
    "Slots",
    "Sound",
    "Sound Volume",
    "Start",
    "Text Speed",
    "Unseen Text",
    "Voice",
    "Voice Volume",
    "Window",
}
SEPARATOR_REMNANTS = ("|||", "RNLSEP", "SEP777", "TXTSEP")
HOTKEY_SOURCE_RE = re.compile(r"^(?P<label>.+?)\s*/\s*(?P<hotkey>[A-Za-z])$")
HOTKEY_VISIBLE_RE = re.compile(r"^(?P<label>.+?)\s*\[(?P<hotkey>[A-Za-z])\]$")
ANGLE_WRAPPED_SINGLE_RE = re.compile(r"^<(?P<label>[^<>|]+)>$")
VISIBLE_TEXT_APOSTROPHES = ("'", "\u2019", "\u2018", "\u02bc")
VISIBLE_TEXT_DASHES = (" - ", " \u2013 ", " \u2014 ")
VISIBLE_TEXT_SENTENCE_RE = re.compile(r"[^.!?\u2026]+(?:[.!?\u2026]+|$)")
VISIBLE_TEXT_BRIDGE_PREFIXES = ("And", "But", "So", "Or", "Then")
# Shared with the parser/formatter: a bracketed phrase with spaces is display
# text, not a placeholder (see syntax_guard.INTERPOLATION_RE).
PLACEHOLDER_BRACKET_RE = re.compile(r"\[[^\[\]\s]+\]")
RENPY_TAG_RE = re.compile(r"\{/?[^}]+\}")
# v2.8.13: printf-style format specifiers (%s, %-5d, %(name)03d, %6.2f ...).
# Covers flags (- + # 0), width, precision, length modifiers and every
# conversion character Python's % operator accepts. The space flag is
# excluded on purpose so "% word" natural language is never matched.
PRINTF_SPEC_RE = re.compile(
    r"%\([^)]*\)[-+#0]*\d*(?:\.\d+)?[hlL]?[diouxXeEfFgGcrsa]"
    r"|%[-+#0]*\d*(?:\.\d+)?[hlL]?[diouxXeEfFgGcrsa]"
)
HTML_LEAK_RE = re.compile(r"</?(?:span|div)\b", re.IGNORECASE)
# v2.8.17: strict grammar for the pure outer color-wrapper normalizer.
# Only a literal safe hex argument is accepted — Ren'Py's four color
# literal forms #rgb, #rgba, #rrggbb, #rrggbbaa. Anything else (named
# colors, gui.* references, expressions, whitespace) fails validation
# and the wrapped value is left untouched. Longest-first alternation so
# an 8-digit literal is never clipped into a shorter partial match.
SAFE_COLOR_HEX_RE = re.compile(
    r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})"
)
OUTER_COLOR_WRAPPER_RE = re.compile(
    r"^\{color=(?P<hex>#[0-9a-fA-F]{3,8})\}(?P<inner>.*)\{/color\}$",
    re.DOTALL,
)
PLACEHOLDER_REMNANT_RE = re.compile(
    r"(?i)(?:R[A-Z]{0,6}LPH[0-9A-F]{3,}|XRPYX_[A-Z0-9_]+|RNPY_[A-Z0-9_]+)"
)
TRANSLATION_ID_KEY_RE = re.compile(r"^id_[0-9a-f]{16,}$")
QUOTED_LITERAL_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\'')
DEEP_SCAN_VAR_ONLY_RE = re.compile(r"^\[[a-zA-Z_]\w*\]$")
DEEP_SCAN_MARKUP_STRIP_RE = re.compile(r"\{[^}]*\}|\[[^\]]*\]")
LATIN_EXTENDED_CHAR_RE = re.compile(r"[a-zA-Z\u00C0-\u024F]")
STRING_PAIR_BLOCK_RE = re.compile(r'^\s*old\s+"(?P<old>.*?)"\s*\n\s*new\s+"(?P<new>.*?)"\s*$', re.MULTILINE | re.DOTALL)
DIALOGUE_PAIR_BLOCK_RE = re.compile(r'^\s*#\s*(?:\w+\s+)?"(?P<old>.*?)"\s*\n\s*(?:\w+\s+)?"(?P<new>.*?)"\s*$', re.MULTILINE | re.DOTALL)
IMAGE_ONLY_BLOCK_RE = re.compile(r'^\s*(?P<kind>imagebutton|hotspot)\b')
TEXTUAL_UI_HINT_RE = re.compile(
    r'\b(?:tooltip|alt)\b|^\s*(?:text|textbutton|label|caption)\b|\bText\s*\('
)
RENPY_KEYWORDS_TO_SKIP = {
    'label', 'scene', 'show', 'hide', 'with', 'call', 'jump', 'return',
    'play', 'stop', 'queue', 'pause', 'pass', 'define', 'default', 'init',
    'style', 'image', 'transform', 'python', 'if', 'elif', 'else', 'while',
    'for', 'renpy', 'nvl', 'voice', 'camera', 'window', 'frame', 'screen',
    'bar', 'vbar', 'viewport', 'add', 'use', 'has', 'on', 'key', 'timer',
    'input', 'sound', 'music', 'audio', 'showif', 'as', 'at', 'behind',
    'onlayer', 'zorder', 'parallel', 'block', 'contains', 'repeat', 'function',
    'layeredimage', 'group', 'attribute', 'auto', 'always', 'offer', 'side',
    'vpgrid', 'grid', 'fixed', 'hstack', 'vstack', 'drag', 'draggroup',
    'hotspot', 'hotbar', 'dismiss', 'transclude', 'testcase', 'menu',
    'style_prefix', 'style_suffix', 'text_style', 'size_group', 'variant',
    'id', 'mousearea', 'selected', 'sensitive', 'action', 'hovered', 'unhovered'
}
HELPER_PROPERTY_RE = re.compile(
    r'^\s*(?:idle|hover|selected|selected_idle|selected_hover|background|foreground|add)\b'
)
DYNAMIC_UI_LINE_RE = re.compile(
    r'^\s*(?:text|tooltip|label|caption)\b.*(?:\.format\(|\bf["\'])|\bText\s*\(\s*(?:[fF]["\']|.*\.format\()'
)

COVERAGE_WARNING_UI_KEYS = {
    'image_only_ui': 'coverage_warning_image_only_ui',
    'compiled_only_scripts': 'coverage_warning_compiled_only',
    'dynamic_ui_runtime': 'coverage_warning_dynamic_ui',
    'interpolated_define_values': 'coverage_warning_interpolated_values',
}

COVERAGE_AUDIT_EXCLUDE_DIRS = {
    'tl',
    'cache',
    'saves',
    'renpy',
    'python-packages',
    'lib',
    '__pycache__',
}
