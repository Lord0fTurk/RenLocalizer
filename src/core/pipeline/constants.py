# -*- coding: utf-8 -*-
"""
Module-level constants and regex patterns for the translation pipeline.
"""

import re


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

CORE_UI_RETRY_STRINGS = {
    "About",
    "Auto",
    "Back",
    "End Replay",
    "Help",
    "History",
    "Load",
    "Load Game",
    "Main Menu",
    "Preferences",
    "Prefs",
    "Q.Load",
    "Q.Save",
    "Save",
    "Skip",
    "Start",
    "Unseen Text",
}
SEPARATOR_REMNANTS = ("|||", "RNLSEP", "SEP777", "TXTSEP")
HOTKEY_SOURCE_RE = re.compile(r"^(?P<label>.+?)\s*/\s*(?P<hotkey>[A-Za-z])$")
HOTKEY_VISIBLE_RE = re.compile(r"^(?P<label>.+?)\s*\[(?P<hotkey>[A-Za-z])\]$")
ANGLE_WRAPPED_SINGLE_RE = re.compile(r"^<(?P<label>[^<>|]+)>$")
VISIBLE_TEXT_APOSTROPHES = ("'", "\u2019", "\u2018", "\u02bc")
VISIBLE_TEXT_DASHES = (" - ", " \u2013 ", " \u2014 ")
VISIBLE_TEXT_SENTENCE_RE = re.compile(r"[^.!?\u2026]+(?:[.!?\u2026]+|$)")
VISIBLE_TEXT_BRIDGE_PREFIXES = ("And", "But", "So", "Or", "Then")
PLACEHOLDER_BRACKET_RE = re.compile(r"\[[^\]]+\]")
RENPY_TAG_RE = re.compile(r"\{/?[^}]+\}")
HTML_LEAK_RE = re.compile(r"</?(?:span|div)\b", re.IGNORECASE)
PLACEHOLDER_REMNANT_RE = re.compile(
    r"(?i)(?:R[A-Z]{0,6}LPH[0-9A-F]{3,}|XRPYX_[A-Z0-9_]+|RNPY_[A-Z0-9_]+)"
)
TRANSLATION_ID_KEY_RE = re.compile(r"^id_[0-9a-f]{16,}$")
QUOTED_LITERAL_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\'')
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
    'hotspot', 'hotbar', 'dismiss', 'transclude', 'testcase', 'menu'
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
