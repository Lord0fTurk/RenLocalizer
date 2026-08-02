"""
Output Formatter
===============

Formats translation results into Ren'Py translate block format.
"""

import logging
import hashlib
from typing import List, Dict, Set, TYPE_CHECKING, Optional
from pathlib import Path
import re

if TYPE_CHECKING:
    from src.core.translator import TranslationResult


def _preserve_case(src: str, dst: str) -> str:
    # Kaynak kelimenin büyük/küçük harfini hedefe uygula
    if not src or not dst:
        return dst
    if src.isupper():
        return dst.upper()
    if src[0].isupper():
        return dst.capitalize()
    return dst


class RenPyOutputFormatter:
    def apply_glossary(self, text: str, glossary: dict, original_text: str = None) -> str:
        """
        Glossary'deki terimleri öncelik sırasına göre (uzun terim önce) metin içinde değiştirir.
        """
        from src.core.glossary_manager import GlossaryManager
        return GlossaryManager.apply_glossary(text, glossary, original_text=original_text)
    
    # File extensions that should never be translated
    SKIP_FILE_EXTENSIONS = (
        '.otf', '.ttf', '.woff', '.woff2',  # Fonts
        '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.ico',  # Images
        '.mp3', '.ogg', '.wav', '.flac', '.aac', '.m4a',  # Audio
        '.mp4', '.webm', '.avi', '.mkv', '.mov',  # Video
        '.rpy', '.rpyc', '.rpa',  # Ren'Py files
        '.py',  # Only Python source should be skipped
    )
    
    # Ren'Py technical terms that should never be translated
    # NOTE: Only lowercase terms here - Title Case like "History" are valid UI labels
    RENPY_TECHNICAL_TERMS = {
        # Screen elements & style identifiers (always lowercase in code)
        'say', 'window', 'namebox', 'choice', 'quick', 'navigation',
        'return_button', 'page_label', 'page_label_text', 'slot',
        'slot_time_text', 'slot_name_text', 'save_delete', 'pref',
        'radio', 'check', 'slider', 'tooltip_icon', 'tooltip_frame',
        'dismiss', 'history_name', 'color',  # Note: removed 'history', 'help' - valid UI labels
        'confirm_prompt', 'notify',
        'nvl_window', 'nvl_button', 'medium', 'touch', 'small',
        'replay_locked',
        # Style & layout properties
        'show', 'hide', 'unicode', 'center',
        'top', 'bottom', 'true', 'false', 'none', 'null', 'auto',
        # Common screen/action identifiers
        'add_post', 'card', 'money_get', 'money_pay', 'mp',
        'pass_time', 'rel_down', 'rel_up',
        # Input/output
        'input', 'output', 'default', 'value',
        # Common config/variable names
        'id', 'name', 'type', 'style', 'action', 'hovered', 'unhovered',
        'selected', 'insensitive', 'activate', 'alternate',
        # Common technical single words
        'idle', 'hover', 'focus', 'selected_idle',
        'selected_hover', 'selected_focus', 'selected_insensitive',
        # Transitions & Motion
        'dissolve', 'fade', 'pixellate', 'move', 'moveinright', 'moveoutright',
        'moveinleft', 'moveoutleft', 'moveintop', 'moveouttop', 'moveinbottom', 'moveoutbottom',
        'inright', 'inleft', 'intop', 'inbottom', 'outright', 'outleft', 'outtop', 'outbottom',
        'wiperight', 'wipeleft', 'wipeup', 'wipedown',
        'slideright', 'slideleft', 'slideup', 'slidedown',
        'slideawayright', 'slideawayleft', 'slideawayup', 'slideawaydown',
        'irisout', 'irisin', 'pushright', 'pushleft', 'pushup', 'pushdown',
        'zoom', 'alpha', 'xalign', 'yalign', 'xpos', 'ypos', 'xanchor', 'yanchor',
        'xzoom', 'yzoom', 'rotate', 'around', 'align', 'pos', 'anchor',
        'rgba', 'rgb', 'hex', 'matrix', 'linear', 'ease', 'easein', 'easeout',
        # Engine Keywords
        'ascii', 'eval', 'exec', 'latin', 'western', 'greedy', 'freetype',
        'narrator', 'fixed', 'grid', 'viewport', 'vpgrid', 'canvas',
        # Added from Research
        'layeredimage', 'transform', 'camera', 'expression', 'assert',
        'hotspot', 'hotbar', 'areapicker', 'drag', 'draggroup', 'showif',
        'after_load', 'after_warp', 'before_main_menu', 'splashscreen',
        'config', 'preferences', 'gui', 'persistent',  # style already above
        # Ren'Py statement keywords (v2.7.3 — crash-causing when translated)
        'scene', 'with', 'at', 'behind', 'as', 'onlayer', 'zorder',
        'parallel', 'block', 'contains', 'pause', 'repeat', 'function',
        # Ren'Py core statement keywords — MUST stay untranslated
        'return', 'screen', 'label', 'menu', 'init', 'call', 'jump',
        'python', 'define', 'image',
        # Ren'Py screen language elements — purely technical, never user text
        'textbutton', 'imagebutton', 'mousearea', 'nearrect',
        'hbox', 'vbox', 'vbar', 'transclude', 'testcase',
        'nvl', 'elif',
        'kerning', 'line_leading', 'outlines', 'antialias', 'hinting',
        'vscroller', 'hscroller', 'button',  # viewport, input, ascii already above
        'zsync', 'zsyncmake', 'rpu', 'ecdsa', 'rsa', 'bbcode', 'markdown',
        'utf8', 'latin1',
    }
    
    # Pre-compiled regex patterns for performance (class-level caching)
    _FORMAT_PLACEHOLDER_RE = re.compile(r'\{[^}]*\}')
    _VARIABLE_RE = re.compile(r'\[[^\[\]]+\]')
    _DISAMBIGUATION_RE = re.compile(r'\{#[^}]+\}')
    _TAG_RE = re.compile(r'\{[^{}]*\}')
    _URL_RE = re.compile(r'^(https?://|ftp://|mailto:|www\.)')
    _HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{3,8}$')
    _NUMBER_RE = re.compile(r'^-?\d+\.?\d*$')
    _FUNC_CALL_RE = re.compile(r'^[A-Za-z_][\w.]*\s*\(.*\)$')  # obj.method(...) dahil
    _MODULE_ATTR_RE = re.compile(r'^[A-Za-z_]\w*\.[A-Za-z_]\w*$')
    _KEYVAL_RE = re.compile(r'^[A-Za-z0-9_\-]+\s*:\s*[A-Za-z0-9_\-]+$')
    # Code expression detection: dotted access + subscript/comparison/boolean
    # Catches: tris.attr['SLU'] >= 3, GAME.mc.getTally('Job') or ..., obj.isAt() in [...]
    _CODE_EXPR_RE = re.compile(
        r'^[A-Za-z_][\w.]*'                    # obj.attr.method start
        r'(?:\[.*?\]|\(.*?\))'               # followed by subscript or call
        r'(?:\s*(?:>=|<=|==|!=|>|<|\band\b|\bor\b|\bnot\b|\bin\b)\s*.+)?$'  # optional comparison
    )
    _SNAKE_CASE_RE = re.compile(r'^[a-z][a-z0-9]*(_[a-z0-9]+)+$')
    _SCREAMING_SNAKE_RE = re.compile(r'^[A-Z][A-Z0-9]*(_[A-Z0-9]+)+$')
    _GAME_SAVE_ID_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*-\d+$')
    _VERSION_RE = re.compile(r'^v?\d+\.\d+(\.\d+)?([a-z])?$')
    _FILE_PATH_SLASH_RE = re.compile(r'^[a-zA-Z0-9_/.\-]+$')
    _FILE_PATH_BACKSLASH_RE = re.compile(r'^[a-zA-Z0-9_\\\.\-]+$')
    _ANGLE_PLACEHOLDER_RE = re.compile(r'[\u27e6\u27e7]')  # ⟦placeholder⟧ gibi
    _QMARK_PLACEHOLDER_RE = re.compile(r'\?[A-Za-z]\d{3}\?')  # ?V000? ?T000? vb.
    # v2.7.3: Python condition pattern — 'var_name' in obj.attr (multi-word support)
    # Now handles: 'reactor activated' in GAME.mc.done (spaces inside quotes)
    _PYTHON_CONDITION_RE = re.compile(
        r"""^\s*['"][^'"]+['"]\s+(?:not\s+)?in\s+[A-Za-z_]\w*\.\w+"""
    )
    # v2.7.3: Code logic with dotted access — not GAME.x.y(), khelara not in GAME.crew
    _CODE_LOGIC_RE = re.compile(
        r'^\s*(?:not\s+)?[A-Za-z_][\w.]*(?:\([^)]*\))?'
        r'\s+(?:not\s+)?in\s+[A-Za-z_][\w.]*'
    )
    # v2.7.3: Dotted path IN list — GAME.hour in [18,19], GAME.getStarSys().ID in ['X']
    _DOTTED_IN_RE = re.compile(
        r'^\s*[A-Za-z_][\w.]*(?:\([^)]*\))?(?:\.[A-Za-z_]\w*)*\s+(?:not\s+)?in\s+\['
    )
    # v2.7.3: Dotted path + comparison/modulo — GAME.day%5 == 0, GAME.hour < 18
    _DOTTED_COMPARE_RE = re.compile(
        r'^\s*[A-Za-z_][\w.]*(?:\([^)]*\))?(?:\.[A-Za-z_]\w*)*[%\s]*(?:==|!=|>=|<=|<|>)'
    )
    # v2.7.3: List comprehension — [x >= 70 for x in items]
    _LIST_COMPREHENSION_RE = re.compile(
        r'\[.*\bfor\s+\w+\s+in\b.*\]'
    )
    # v2.7.3: Method call on bracket/paren result — ].count(True), ).items()
    _BRACKET_METHOD_RE = re.compile(
        r'[\]\)]\s*\.\w+\s*\('
    )
    # v2.7.3: Short ALL_CAPS game terms (2-6 pure uppercase letters)
    _SHORT_ALL_CAPS_RE = re.compile(r'^[A-Z]{2,6}$')
    # v2.7.3: Format string templates: "...".format(...)
    _FORMAT_TEMPLATE_RE = re.compile(r'"[^"]*"\s*\.format\s*\(')
    
    # v2.8.3: Ren'Py-specific false positive patterns (from official docs research)
    # Character definition code strings that are NOT translatable
    _CHAR_CODE_PARAM_RE = re.compile(
        r'(?:who_prefix|what_suffix|who_suffix|what_prefix|voice_tag|image|icon|sound)\s*='
    )
    # GUI font/config assignments (value side)
    _GUI_FONT_ASSIGN_RE = re.compile(
        r'(?:define\s+)?(?:gui|config)\.\w*(?:font|size|spacing|color|delay)\s*='
    )
    # Image tag references in define/Character statements
    _IMAGE_TAG_REF_RE = re.compile(
        r'(?:^|\s)image\s*=\s*["\'][a-zA-Z0-9_\-]+["\']'
    )
    # Ren'Py show/scene/hide attribute strings (e.g., 'happy', 'concerned')
    _SHOW_ATTR_RE = re.compile(
        r'^\s*(?:show|scene|hide)\s+[a-zA-Z_]\w*\s+[a-zA-Z_]\w*\s*$'
    )

    # Pre-compiled Python code & builtin call patterns for high performance
    _PYTHON_CODE_RE = re.compile(
        r'(?:'
        r'\bdef\s+\w+\s*\(|'
        r'\bclass\s+\w+\s*[:\(]|'
        r'(?:^|\n)\s*for\s+\w+\s+in\s+\w+\s*:|'
        r'\bif\s+\w+\s+in\s+\w+:|'
        r'\bimport\s+\w+|'
        r'\bfrom\s+\w+\s+import|'
        r'\breturn\s+(?:self|cls|True|False|None|\d|\(|\[|\{|"|\')|'
        r'\braise\s+\w+|'
        r'\btry\s*:|'
        r'\bexcept\s+\w*:|'
        r'(?:^|\n)\s*while\s+\w+\s*:|'
        r'\bwhile\s+(?:True|False|not\s+|\d)|'
        r'\blambda\s+\w*:|'
        r'\bwith\s+\w+\s*\(.*\)\s+as\s+|'
        r'renpy\.\w+\.\w+|'
        r'renpy\.\w+\(|'
        r'_\w+\[|'
        r'\w+\s*=\s*\[|'
        r'\w+\s*=\s*\{|'
        r'\w+\s*=\s*True\b|'
        r'\w+\s*=\s*False\b|'
        r'\w+\s*=\s*None\b'
        r')'
    )
    _PYTHON_BUILTIN_CALLS_RE = re.compile(
        r'\b(?:str|int|float|len|list|dict|tuple|set|abs|min|max|round|range|format|repr|ord|chr)\s*\('
    )

    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def _should_skip_translation(self, text: str) -> bool:
        """
        Check if a text should be skipped from translation output.
        Returns True if the text is a technical term, file path, or identifier.
        This is a SAFETY NET - parser should have already filtered most of these.
        Uses pre-compiled regex patterns for performance.
        """
        text_strip = text.strip()
        text_lower = text_strip.lower()
        
        # Skip empty text
        if not text_strip:
            return True

        # --- CRITICAL SAFETY: Skip regexes and technical code sequences ---
        # Strings containing regex syntax like (?:, (?P<, \x1B, or heavy regex markers
        # These are commonly found in renpy/common scripts and must never be translated.
        if re.search(r'\\x[0-9a-fA-F]{2}|(?:\(\?\:|\(\?P<|\[@-Z\\-_\]|\[0-\?\]\*|\[ -/\]\*|\[@-~\])', text_lower):
             return True
        
        # Skip underscore prefixes (internal variables)
        if text_strip.startswith('_') and ' ' not in text_strip:
            return True
        
        # Skip internal file indices (starting with 00)
        if text_strip.startswith('00') and not any(ch.isalpha() for ch in text_strip[:5]):
            return True
        
        # Shader/GLSL check
        if re.search(r'\b(?:uniform|attribute|varying|vec[234]|mat[234]|gl_FragColor|sampler2D|gl_Position|texture2D|v_tex_coord|a_tex_coord|a_position|u_transform|u_lod_bias)\b', text):
            return True
        
        # --- PYTHON CODE / DOCSTRING DETECTION ---
        # Skip strings containing Python code patterns (commonly from docstrings)
        # These cause critical game-breaking issues when translated
        if self._PYTHON_CODE_RE.search(text_strip):
            return True
        
        # --- STRING CONCATENATION / CODE EXPRESSIONS ---
        # Skip strings that are Python string concatenation or code expressions
        # e.g., "inventory/"+i.img+".png", "ui/" + l + "_quest_select.png"
        if re.search(r'"\s*\+\s*\w+\s*\+\s*"', text_strip):  # "xxx" + var + "xxx"
            return True
        if re.search(r'\w+\.\w+\s*\+', text_strip):  # object.attr +
            return True
        
        # --- PYTHON BUILT-IN FUNCTION CALLS ---
        # Skip strings containing Python function calls like str(), int(), len()
        # v2.5.0: Now smarter - if the string is long and has spaces, it's likely a quest text
        # we only skip short technical strings like "image_"+str(i)+".png"
        if len(text_strip) < 80 or ' ' not in text_strip.strip():
            if self._PYTHON_BUILTIN_CALLS_RE.search(text_strip):
                return True
        
        # --- FILE PATH PATTERNS WITH VARIABLES ---
        # Skip strings that look like path templates with string concatenation
        # e.g., "minigame/dice_"+str(one)+".png", "images/"+name+".jpg"
        # NOTE: Pattern requires quotes or '/' to avoid catching "2 + 2", "Add +5"
        if re.search(r'["\'][\w/]*["\']\s*\+\s*\w+', text_strip) or re.search(r'\w+/\w+\s*\+\s*\w+', text_strip):
            return True
        
        # --- RENPY-ONLY MARKUP STRINGS (no translatable content) ---
        # Skip strings that are ONLY Ren'Py tags/variables with no actual text
        # e.g., "[quest[char][event_char]]", "{b}Morning{/b} : [schedule[char][0]]"
        stripped_of_tags = self._TAG_RE.sub('', text_strip)
        stripped_of_vars = self._VARIABLE_RE.sub('', stripped_of_tags)
        stripped_of_markup = stripped_of_vars.strip()
        # If after removing all tags/vars, only punctuation/numbers/spaces remain, skip
        if stripped_of_markup and not re.search(r'[a-zA-Z\u00C0-\u024F\u0400-\u04FF\u4E00-\u9FFF\u3040-\u30FF\uAC00-\uD7AF]{2,}', stripped_of_markup):
            return True
        
        # --- SINGLE TECHNICAL WORDS ---
        # Skip very short strings that are likely technical identifiers
        # e.g., "img", "id", "name" (without context)
        if len(text_strip) <= 4 and text_strip.isalpha() and text_strip.islower():
            if text_strip in {'img', 'id', 'name', 'type', 'key', 'val', 'var', 'str', 'int', 'len', 'max', 'min', 'sum', 'map', 'set', 'get', 'put', 'add', 'del', 'pop', 'all', 'any', 'obj', 'src', 'dst', 'pos', 'neg', 'abs', 'ord', 'chr', 'hex', 'oct', 'bin', 'dir', 'cls', 'fmt', 'arg', 'opt', 'cfg', 'env', 'tmp', 'msg', 'err', 'log', 'dbg', 'idx', 'ptr', 'buf', 'ctx', 'ref'}:
                return True
            
        # Command line arguments
        if re.match(r'^--?[a-z0-9_\-]+$', text_strip):
            return True
            
        # Gibberish / Binary / Encrypted String Detection (Safety Net)
        # CRITICAL: Detect corrupted strings from .rpyc files
        
        # CHECK 1: Replacement character and common corruption indicators
        if '\ufffd' in text_strip:  # Unicode replacement character
            return True
        
        # CHECK 2: Private Use Area characters (typically from binary corruption)
        # These are characters in ranges that should never appear in normal text
        if re.search(r'[\uE000-\uF8FF\uFFF0-\uFFFF]', text_strip):
            return True
        
        # CHECK 3: Control characters (except common whitespace)
        # Characters 0x00-0x1F (except tab, newline, carriage return) and 0x7F-0x9F
        if re.search(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', text_strip):
            return True
        
        # CHECK 4: High ratio of non-printable or unusual characters
        # This catches strings like "���/Tė", "|d�T", "�iYME�."
        # Allowed character ranges:
        # - Basic ASCII printable: \x20-\x7E
        # - Extended Latin: \u00A0-\u00FF
        # - Cyrillic: \u0400-\u04FF
        # - CJK: \u4E00-\u9FFF
        # - Japanese: \u3040-\u30FF
        # - Korean: \uAC00-\uD7AF
        # - Common punctuation and symbols
        strange_chars = len(re.findall(r'[^\x20-\x7E\s\u00A0-\u00FF\u0100-\u024F\u0400-\u04FF\u4E00-\u9FFF\u3040-\u30FF\uAC00-\uD7AF]', text_strip))
        
        # If more than 30% strange characters, it's likely corrupted
        if len(text_strip) > 0 and strange_chars > len(text_strip) * 0.3:
            return True
        
        # CHECK 5: Strings with very few alphabetic characters
        if len(text_strip) > 3:
            alpha_count = sum(1 for ch in text_strip if ch.isalpha())
            # If less than 20% alphabetic and string is longer than 5 chars, likely binary
            if alpha_count < len(text_strip) * 0.2 and len(text_strip) > 5:
                return True
            # Low alpha ratio + high character variety = likely random/binary data
            if alpha_count < len(text_strip) * 0.4:
                unique_chars = len(set(text_strip))
                if unique_chars > len(text_strip) * 0.7:
                    return True
            
        # CHECK 6: Detect specific patterns of rpyc corruption
        # Strings like "z�X�", "qu�p��", "@Bq#8W" - random looking with special chars
        if len(text_strip) >= 3 and len(text_strip) <= 15:
            # Count unusual character sequences
            unusual_sequences = len(re.findall(r'[^\x20-\x7E]', text_strip))
            ascii_letters = len(re.findall(r'[a-zA-Z]', text_strip))
            # If we have unusual chars and very few letters, skip
            if unusual_sequences >= 1 and ascii_letters <= 3:
                return True
        
        # Heuristic: If string is long and has high punctuation/symbol density, it's likely code/regex
        if len(text_strip) > 20:
            symbol_count = len(re.findall(r'[\\#\[\](){}|*+?^$]', text_strip))
            if symbol_count > len(text_strip) * 0.3:
                return True
        
        # Skip Python format strings like {:,}, {:3d}, {}, {}Attitude:{} {}
        # These are used for number/string formatting and should not be translated
        if '{' in text_strip:
            # First strip Ren'Py text tags before counting format placeholders.
            # Tags like {b}, {/b}, {i}, {color=#fff}, {/color}, {size=20} etc.
            # are legitimate Ren'Py markup, NOT Python format placeholders.
            _renpy_tag_stripped = re.sub(
                r'\{/?(?:b|i|u|s|plain|color|font|size|cps|nw|fast|w|p|a|outlinecolor|alpha|k|rt|rb|image|space|vspace)(?:=[^}]*)?\}',
                '', text_strip
            )
            # Count ACTUAL format placeholders (not Ren'Py tags)
            format_count = len(self._FORMAT_PLACEHOLDER_RE.findall(_renpy_tag_stripped))
            if format_count >= 1:
                # Remove format placeholders and check remaining content
                remaining = self._FORMAT_PLACEHOLDER_RE.sub('', _renpy_tag_stripped).strip()
                # If remaining has no meaningful letters, skip
                if not re.search(r'[a-zA-ZçğıöşüÇĞIİÖŞÜа-яА-Яа-яА-Я]{3,}', remaining):
                    return True
                # If format placeholders dominate the string, skip
                if format_count >= 2 and len(remaining) < 10:
                    return True
        
        # Skip file names/paths (fonts, images, audio, etc.)
        if any(text_lower.endswith(ext) for ext in self.SKIP_FILE_EXTENSIONS):
            return True
        
        # Skip paths starting with common folder names (case-insensitive for Linux)
        if text_lower.startswith(('fonts/', 'images/', 'audio/', 'music/', 'sounds/', 
                                   'gui/', 'screens/', 'script/', 'game/', 'tl/',
                                   'video/', 'videos/', 'backgrounds/', 'sfx/', 'bgm/',
                                   'cg/', 'bg/', 'movies/', 'sound/')):
            return True
        
        # Skip paths with slashes (file paths like "fonts/something.otf")
        if '/' in text_strip and ' ' not in text_strip:
            if self._FILE_PATH_SLASH_RE.match(text_strip):
                return True
        
        # Skip backslash paths (Windows style)
        if '\\' in text_strip and ' ' not in text_strip:
            if self._FILE_PATH_BACKSLASH_RE.match(text_strip):
                return True
        
        # Skip URLs (using cached pattern)
        if self._URL_RE.match(text_lower):
            return True
        
        # Skip hex color codes (using cached pattern)
        if self._HEX_COLOR_RE.match(text_strip):
            return True
        
        # Skip pure numbers (using cached pattern)
        if self._NUMBER_RE.match(text_strip):
            return True
        
        # Skip Ren'Py technical terms - ONLY exact lowercase match
        # "history" -> skip, "History" -> translate (UI label)
        if text_strip in self.RENPY_TECHNICAL_TERMS:
            return True
        
        # v2.7.3: Python builtin constants as standalone text
        # "True", "False", "None" are NEVER translatable — they are Python keywords
        if text_strip in ('True', 'False', 'None'):
            return True

        # Known translatable dotted UI labels that look like module.attribute references
        # e.g. "Q.Save", "Q.Load" — quick menu button text, not code
        _translatable_dotted_ui = {'Q.Save', 'Q.Load', 'Q.Menu', 'A.Save', 'A.Load', 'S.Save', 'S.Load'}
        if text_strip in _translatable_dotted_ui:
            return False

        # Skip likely function calls or code-like literals
        if self._FUNC_CALL_RE.match(text_strip):
            return True
        # Also skip 'not func_call()' patterns (negated code expressions)
        if text_strip.startswith('not ') and self._FUNC_CALL_RE.match(text_strip[4:].strip()):
            return True
        # Skip module.attribute references
        if self._MODULE_ATTR_RE.match(text_strip):
            return True
        # Skip code expressions: dotted access + subscript/comparison
        # e.g., tris.attr['SLU'] >= 3, GAME.mc.getTally('Job') or ...
        if self._CODE_EXPR_RE.match(text_strip):
            return True
        # Skip key:value like config entries
        if self._KEYVAL_RE.match(text_strip):
            return True

        # Skip angled placeholder markers like ⟦V000⟧
        if self._ANGLE_PLACEHOLDER_RE.search(text_strip):
            return True

        # Skip strings that are likely file system patterns or technical globs.
        # IMPORTANT: Use the tag-stripped version so that Ren'Py closing tags like
        # {/w}, {/b}, {/color} don't falsely trigger the '/' check when combined
        # with asterisks (e.g., "{color=#5175ea}*giggle*{/w}" is valid dialogue).
        _tag_stripped_for_glob = self._TAG_RE.sub('', text_strip)
        if '*' in _tag_stripped_for_glob and ('/' in _tag_stripped_for_glob or '\\' in _tag_stripped_for_glob):
            return True
        if re.search(r'\*\*?/\*\*?', _tag_stripped_for_glob):
            return True
            
        # Skip module.attribute references (stricter: multiple dots or technical prefixes)
        if re.match(r'^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+$', text_strip):
            return True
        if text_lower.startswith(('renpy.', 'config.', 'gui.', '_.')):
            return True

        # Skip question-mark placeholders like ?V000? ?T000?
        if self._QMARK_PLACEHOLDER_RE.search(text_strip):
            return True

        # Skip obvious config/version placeholders that should remain untouched
        if "config.version" in text_strip or "[config." in text_strip:
            return True

        # Skip snake_case identifiers (using cached pattern)
        if self._SNAKE_CASE_RE.match(text_strip):
            return True
        
        # Skip SCREAMING_SNAKE_CASE constants (using cached pattern)
        if self._SCREAMING_SNAKE_RE.match(text_strip):
            return True
        
        # Skip save identifiers like "GameName-1234567890" (using cached pattern)
        if self._GAME_SAVE_ID_RE.match(text_strip):
            return True
        
        # Skip version strings (using cached pattern)
        if self._VERSION_RE.match(text_lower):
            return True
        
        # Skip if it's just Ren'Py tags/variables with no actual text
        stripped_of_tags = self._TAG_RE.sub('', text_strip)
        stripped_of_vars = self._VARIABLE_RE.sub('', stripped_of_tags)
        if not stripped_of_vars.strip():
            return True
        
        # =================================================================
        # v2.7.3: Additional False-Positive Guards (from crash analysis)
        # =================================================================
        
        # --- PYTHON CONDITION STRINGS ---
        # Pattern: 'var_name' in obj.attr  /  'reactor activated' in GAME.mc.done
        # These are game logic conditions that MUST NOT be translated.
        if self._PYTHON_CONDITION_RE.match(text_strip):
            return True
        
        # --- DOTTED PATH + IN [LIST] ---
        # Pattern: GAME.hour in [18,19,20], GAME.getStarSys().ID in ['X']
        if self._DOTTED_IN_RE.match(text_strip):
            return True
        
        # --- DOTTED PATH + COMPARISON/MODULO ---
        # Pattern: GAME.day%5 == 0, GAME.hour < 18
        if self._DOTTED_COMPARE_RE.match(text_strip):
            return True
        
        # --- LIST COMPREHENSION ---
        # Pattern: [x >= 70 for x in bot.skills.values()].count(True) >= 3
        if self._LIST_COMPREHENSION_RE.search(text_strip):
            return True
        
        # --- METHOD CALL ON BRACKET/PAREN RESULT ---
        # Pattern: ].count(True), ).items(), ).ID
        if self._BRACKET_METHOD_RE.search(text_strip) and '.' in text_strip:
            return True
        
        # --- CODE LOGIC WITH DOTTED ACCESS ---
        # Pattern: not GAME.questSys.isDone('QID_...')
        #          khelara not in GAME.crew
        #          GAME.hour < 18 and GAME.questSys.isDone(...)
        # IMPORTANT: Require at least one dotted path (obj.attr) to avoid
        # catching natural language like "Getting in Shape"
        if self._CODE_LOGIC_RE.match(text_strip) and '.' in text_strip:
            return True
        
        # Broader code detection: dotted access + comparison/boolean in same string
        # e.g., "GAME.hour < 18 and GAME.questSys.isDone('QID_...')"
        # v2.7.3: Lowered threshold to 1 dotted ref (was 2) when operators present
        # NOTE: Require 3+ chars before dot to avoid abbreviations (e.g., U.S., Dr.)
        dot_refs = re.findall(r'[A-Za-z_]\w{2,}\.\w+', text_strip)
        if len(dot_refs) >= 1 and re.search(r'\b(?:and|or|not)\b|[<>=!]=|(?<![<>])[<>](?![<>])', text_strip):
            return True
        
        # --- SHORT ALL_CAPS GAME TERMS ---
        # Pattern: NOT, REP, INT, CON, STR, DEX, TEC (game stat abbreviations)
        # These are 2-6 uppercase letters, commonly used as skill/stat identifiers.
        # EXCLUSION: Common English words that SHOULD be translated when Title Case is used
        # but are game tokens when ALL_CAPS. We only skip pure ALL_CAPS 2-6 char strings.
        if self._SHORT_ALL_CAPS_RE.match(text_strip):
            # Safety: allow very common English words even in ALL_CAPS
            # "OK", "NO" are valid UI labels, but "NOT", "REP", "STR" etc. are game stats
            _caps_translate_whitelist = {
                'OK', 'NO', 'ON', 'UP', 'GO', 'OR', 'AN', 'IF', 'BY', 'IN', 'IS', 'DO',
                'YES', 'YEP', 'YEA', 'NAH', 'HI', 'HEY', 'BYE', 'AH', 'OH', 'AW', 'OW',
                'EW', 'OOH', 'AAH', 'HMM', 'HM', 'UM', 'UH', 'WOW', 'YAY', 'BOO', 'YO',
                'WHO', 'WHY', 'HOW', 'HUH', 'EH', 'WAIT', 'STOP', 'HELP', 'COME', 'LOOK',
                'WHAT', 'SURE', 'FINE', 'DONE', 'NEXT', 'BACK', 'AWAY', 'HERE', 'OVER',
                'LEFT', 'GOOD', 'AT', 'TO', 'ME', 'HE', 'SHE', 'US', 'SO', 'AS', 'AM',
                'BE', 'IT', 'WE', 'MY', 'HIS', 'HER', 'OUR', 'ITS',
                # v2.8.8: Difficulty levels & common game UI (false positives)
                'EASY', 'NORMAL', 'HARD', 'MEDIUM', 'CUM', 'SEX', 'ASS',
                'NEW', 'OLD', 'TOP', 'BEST', 'FAST', 'SLOW', 'HIGH', 'LOW',
                'BIG', 'HOT', 'WET', 'DRY', 'FUN', 'CUT', 'RUN', 'FLY',
                'DAY', 'NIGHT', 'SUN', 'MOON', 'SKY', 'SEA',
                'MAN', 'WOMAN', 'BOY', 'GIRL', 'GUY', 'LAD',
                'RED', 'BLUE', 'GREEN', 'PINK', 'GOLD', 'DARK', 'LIGHT',
                'FREE', 'OPEN', 'CLOSE', 'LOCK', 'SAVE', 'LOAD', 'PLAY',
                'MAIN', 'MENU', 'EXIT', 'QUIT', 'HOME', 'PAGE', 'FILE',
                'SIZE', 'TEXT', 'FONT', 'SOUL', 'LIFE', 'LOVE', 'HATE',
                'TRUE', 'FALSE', 'MALE', 'FEMALE', 'BOTH',
                'ALL', 'ANY', 'SOME', 'MANY', 'FEW', 'MORE', 'LESS',
                'WIN', 'LOSE', 'DRAW', 'SHOT', 'HIT', 'KILL', 'DIE',
                'GET', 'SET', 'PUT', 'LET', 'ASK', 'TALK'
            }
            if text_strip not in _caps_translate_whitelist:
                return True
        
        # --- FORMAT STRING TEMPLATES ---
        # Pattern: "Track: {} | Dist: {}".format(race.ground, race.laps)
        if self._FORMAT_TEMPLATE_RE.search(text_strip):
            return True
        
        # --- PYTHON EXPRESSION WITH SINGLE-QUOTED IDENTIFIERS ---
        # Strings that start with a single-quoted identifier followed by code operators
        # e.g., 'exemption_talk' in moira.done → missed by _PYTHON_CONDITION_RE if multiline
        if text_strip.startswith("'") and re.match(r"^'[\w.]+'", text_strip):
            # If the rest contains code-like pattern, skip
            rest = re.sub(r"^'[\w.]+'", '', text_strip).strip()
            if rest and re.match(r'^(?:in\b|not\b|and\b|or\b|==|!=|>=|<=|>|<)', rest):
                return True

        # =================================================================
        # v2.8.3: Ren'Py-Specific False Positive Guards
        # =================================================================

        # --- CHARACTER CODE PARAMETER STRINGS ---
        # Pattern: who_prefix="[", what_suffix=")", voice_tag="eileen_voice"
        # These are code parameters inside Character() definitions — NOT translatable
        if self._CHAR_CODE_PARAM_RE.search(text_strip):
            return True

        # --- GUI FONT/CONFIG ASSIGNMENTS ---
        # Pattern: define gui.text_font = "Noto Sans.ttf", config.window_title = "..."
        # Font paths and config settings are NOT translatable text
        if self._GUI_FONT_ASSIGN_RE.search(text_strip):
            return True

        # --- IMAGE TAG REFERENCES ---
        # Pattern: image="char_eileen" in Character definition
        # Image tags are asset references, NOT translatable
        if self._IMAGE_TAG_REF_RE.search(text_strip):
            return True

        return False
    
    def sanitize_translation_id(self, text: str) -> str:
        """Create a valid Ren'Py translation ID from text (sanitized, short)."""
        text = re.sub(r'[^a-zA-Z0-9_]', '_', text)
        text = re.sub(r'_+', '_', text).strip('_')
        if text and text[0].isdigit():
            text = '_' + text
        return (text or 'translated_text')[:50]

    def make_hash_id(self, original_text: str, context_path: Optional[List[str]] = None,
                     file_path: str = "", line_number: int = 0) -> str:
        """Hash-based primary ID; context-aware to avoid collisions."""
        base = f"{file_path}:{line_number}:{'|'.join(context_path or [])}:{original_text}"
        digest = hashlib.sha1(base.encode("utf-8", errors="ignore")).hexdigest()[:16]
        return f"id_{digest}"
    
    def escape_renpy_string(self, text: str) -> str:
        """Escape special characters for Ren'Py strings.
        
        Handles:
        - Backslashes, quotes, newlines, tabs, carriage returns
        - Protects Ren'Py variables [var], [var!t] and tags {tag}
        - Protects disambiguation tags {#identifier}
        - Handles double brackets [[ and {{
        """
        if not text:
            return text
            
        import re
        
        # Find all Ren'Py variables [variable] and expressions (including !t flag)
        variable_pattern = re.compile(r'\[[^\[\]]+\]')
        variables = variable_pattern.findall(text)
        
        # CRITICAL: Find disambiguation tags {#...} FIRST - these must be preserved exactly
        disambiguation_pattern = re.compile(r'\{#[^}]+\}')
        disambiguation_tags = disambiguation_pattern.findall(text)
        
        # Find all Ren'Py tags like {i}, {b}, {color=#ff0000}, {/i}, etc.
        tag_pattern = re.compile(r'\{[^{}]*\}')
        tags = tag_pattern.findall(text)
        
        # Replace variables and tags with placeholders temporarily
        temp_text = text
        protection_map = {}
        counter = 0
        
        # Protect disambiguation tags FIRST (highest priority)
        for dtag in disambiguation_tags:
            placeholder = f"⟦DIS{counter:03d}⟧"
            protection_map[placeholder] = dtag
            temp_text = temp_text.replace(dtag, placeholder, 1)
            counter += 1
        
        # Protect variables
        for var in variables:
            placeholder = f"⟦VAR{counter:03d}⟧"
            protection_map[placeholder] = var
            temp_text = temp_text.replace(var, placeholder, 1)
            counter += 1
        
        # Protect tags (excluding disambiguation which are already protected)
        for tag in tags:
            if tag.startswith('{#'):  # Skip disambiguation tags
                continue
            placeholder = f"⟦TAG{counter:03d}⟧"
            protection_map[placeholder] = tag
            temp_text = temp_text.replace(tag, placeholder, 1)
            counter += 1
        
        # Now escape special characters for Ren'Py string literal.
        # IMPORTANT: Escape backslashes FIRST to prevent double-escaping.
        # Previous bug: [[ was converted to \[\[ then \\ escaped all \,
        # producing \\[\\[ (double-escaped and invalid Ren'Py).
        temp_text = temp_text.replace('\\', '\\\\')  # Escape backslashes first
        temp_text = temp_text.replace('"', '\\"')     # Escape double quotes
        temp_text = temp_text.replace('\r', '')       # Remove carriage returns
        temp_text = temp_text.replace('\n', '\\n')    # Escape newlines
        temp_text = temp_text.replace('\t', '\\t')    # Escape tabs
        # Note: [[ and {{ are already correct Ren'Py escapes for literal
        # [ and { brackets. They must be preserved as-is (not re-escaped).
        # [variable] and {tag} patterns were protected via placeholders above.
        
        # Restore variables and tags
        for placeholder, original_content in protection_map.items():
            temp_text = temp_text.replace(placeholder, original_content)
        
        return temp_text
    
    def generate_translation_block(self, 
                                 original_text: str, 
                                 translated_text: str, 
                                 language_code: str,
                                 translation_id: str = None,
                                 context: str = None,
                                 mode: str = "simple") -> str:
        """Generate a single translation block."""
        
        if not translation_id:
            # Create string-based translation that matches any label
            # This is more compatible with existing Ren'Py games
            import hashlib
            text_hash = hashlib.md5(original_text.encode('utf-8')).hexdigest()[:8]
            translation_id = f"strings_{text_hash}"
        
        escaped_original = self.escape_renpy_string(original_text)
        escaped_translated = self.escape_renpy_string(translated_text)
        
        if mode == "old_new":
            # Old/new format - INDIVIDUAL ENTRY (for building larger block)
            block = (
                f"    old \"{escaped_original}\"\n"
                f"    new \"{escaped_translated}\"\n\n"
            )
        else:
            # Simple format - original text in comment, direct translation line
            comment_original = escaped_original.replace('\n', '\\n')
            block = (
                f"    # \"{comment_original}\"\n"
                f"    \"{escaped_translated}\"\n\n"
            )
        
        return block
    
    def generate_character_translation(self,
                                     character_name: str,
                                     original_text: str,
                                     translated_text: str,
                                     language_code: str,
                                     translation_id: str = None,
                                     mode: str = "simple") -> str:
        """Generate a character dialogue translation block."""
        
        escaped_original = self.escape_renpy_string(original_text)
        escaped_translated = self.escape_renpy_string(translated_text)
        
        if mode == "old_new":
            # String-based format - INDIVIDUAL ENTRY (for building larger block)
            block = (
                f"    old {character_name} \"{escaped_original}\"\n"
                f"    new {character_name} \"{escaped_translated}\"\n\n"
            )
        else:
            # Simple format - original text in comment, direct translation line
            comment_original = escaped_original.replace('\n', '\\n')
            block = (
                f"    # {character_name} \"{comment_original}\"\n"
                f"    {character_name} \"{escaped_translated}\"\n\n"
            )
        
        return block
    
    def generate_menu_translation(self,
                                menu_options: List[Dict],
                                language_code: str,
                                menu_id: str = None) -> str:
        """Generate menu translation block - DEPRECATED. 
        
        Menu translations should use translate strings format instead.
        This method is kept for compatibility but menu items should be 
        included in the main strings block.
        """
        
        # Menu choices should be in translate strings block, not separate menu blocks
        # According to RenPy documentation: menu choices use "translate strings" format
        
        block = f"# NOTE: Menu choices should be in 'translate {language_code} strings:' block\n"
        block += f"# This is the old format and may not work properly in RenPy\n\n"
        
        if not menu_id:
            menu_id = f"menu_{self.sanitize_translation_id('_'.join([opt['original'] for opt in menu_options[:3]]))}"
        
        block += f"translate {language_code} {menu_id}:\n\n"
        
        for i, option in enumerate(menu_options):
            original = self.escape_renpy_string(option['original'])
            translated = self.escape_renpy_string(option['translated'])
            # Add each choice with real newlines
            block += f'    # "{original}"\n'
            block += f'    "{translated}"\n'
        
        block += "\n"
        return block
    
    def format_translation_file(self,
                              translation_results: List,
                              language_code: str,
                              source_file: Path = None,
                              include_header: bool = True,
                              output_format: str = "old_new",
                              glossary: dict = None) -> str:
        """Format complete translation file with SEPARATE blocks for each translation."""
        
        output_lines = []
        
        if include_header:
            header = self.generate_file_header(language_code, source_file)
            output_lines.append(header)
        
        # CRITICAL FIX: Create ONE translate strings block for ALL translations
        # This is the CORRECT Ren'Py format
        
        seen_translations = set()
        string_translations = []
        
        # Add the opening translate strings block
        string_translations.append(f"translate {language_code} strings:")
        string_translations.append("")
        
        for result in translation_results:
            if not result.success or not result.translated_text:
                continue

            original_text = result.original_text
            translated_text = result.translated_text
            metadata = getattr(result, 'metadata', {}) or {}
            ctx_path = metadata.get('context_path') or []
            if isinstance(ctx_path, str):
                ctx_path = [ctx_path]
            file_path = metadata.get('file_path', '')
            line_number = metadata.get('line_number', 0)
            translation_id = metadata.get('translation_id') or getattr(result, 'translation_id', None)
            if not translation_id:
                translation_id = self.make_hash_id(original_text, ctx_path, file_path, line_number)

            # GLOSSARY uygula (sadece çeviri metnine)
            if glossary:
                translated_text = self.apply_glossary(translated_text, glossary, original_text=original_text)

            # CRITICAL: Skip technical content that should not be translated
            if self._should_skip_translation(original_text):
                self.logger.debug(f"Skipping technical content: {original_text[:50]}...")
                continue

            # Avoid duplicates - use translation_id primarily, fallback to text pair
            key = translation_id or f"{original_text}_{translated_text}"
            if key in seen_translations:
                continue
            seen_translations.add(key)

            text_type = getattr(result, 'text_type', None)
            
            # Add source file/line comment for translator reference (if available)
            source_info = ""
            if hasattr(result, 'metadata') and result.metadata:
                file_path = result.metadata.get('file_path', '')
                line_number = result.metadata.get('line_number', '')
                if file_path and line_number:
                    # Extract just filename for cleaner output
                    import os
                    filename = os.path.basename(file_path)
                    source_info = f"    # {filename}:{line_number}\n"
            
            # Check if this is a paragraph text (_p() function)
            is_paragraph = (
                text_type == 'paragraph' or 
                '\n\n' in original_text or  # Contains paragraph breaks
                len(original_text) > 200  # Long text likely from _p()
            )
            
            if is_paragraph:
                # Use _p() format for paragraph text
                escaped_original = self._escape_for_old_string(original_text)
                formatted_translated = self._format_p_function_output(translated_text)
                
                if output_format == "old_new":
                    if source_info:
                        string_translations.append(source_info.rstrip())
                    string_translations.append(f"    # id: {translation_id}")
                    string_translations.append(f'    old "{escaped_original}"')
                    string_translations.append(f'    new {formatted_translated}')
                    string_translations.append("")
                else:
                    # Simple format - just old/new without meta-comments
                    string_translations.append(f'    old "{escaped_original}"')
                    string_translations.append(f'    new {formatted_translated}')
                    string_translations.append("")
            else:
                # Standard string format
                escaped_original = self.escape_renpy_string(original_text)
                escaped_translated = self.escape_renpy_string(translated_text)
                
                if output_format == "old_new":
                    if source_info:
                        string_translations.append(source_info.rstrip())
                    string_translations.append(f"    # id: {translation_id}")
                    string_translations.append(f'    old "{escaped_original}"')
                    string_translations.append(f'    new "{escaped_translated}"')
                    string_translations.append("")
                else:
                    # Simple format - just old/new without meta-comments
                    string_translations.append(f'    old "{escaped_original}"')
                    string_translations.append(f'    new "{escaped_translated}"')
                    string_translations.append("")
        
        # Combine header and strings
        output_lines.extend(string_translations)
        
        # Join sections with real newlines
        return "\n".join(output_lines)
    
    def _escape_for_old_string(self, text: str) -> str:
        """
        Escape text for use in 'old' string.
        Ren'Py expects paragraph breaks as literal \\n\\n in old strings.
        """
        # Protect Ren'Py variables and tags first
        variable_pattern = re.compile(r'\[[^\[\]]+\]')
        tag_pattern = re.compile(r'\{[^{}]*\}')
        
        variables = variable_pattern.findall(text)
        tags = tag_pattern.findall(text)
        
        temp_text = text
        protection_map = {}
        
        for i, var in enumerate(variables):
            placeholder = f"__VAR_{i}__"
            protection_map[placeholder] = var
            temp_text = temp_text.replace(var, placeholder, 1)
        
        for i, tag in enumerate(tags):
            placeholder = f"__TAG_{i}__"
            protection_map[placeholder] = tag
            temp_text = temp_text.replace(tag, placeholder, 1)
        
        # Escape quotes and backslashes
        temp_text = temp_text.replace('\\', '\\\\')
        temp_text = temp_text.replace('"', '\\"')
        
        # Convert newlines to escaped form for old string
        temp_text = temp_text.replace('\n', '\\n')
        
        # Restore protected content
        for placeholder, original_content in protection_map.items():
            temp_text = temp_text.replace(placeholder, original_content)
        
        return temp_text
    
    def _format_p_function_output(self, text: str) -> str:
        """
        Format translated text as _p() function for Ren'Py.
        Example output:
        _p(\"\"\"
            First paragraph line one
            first paragraph line two.

            Second paragraph.
            \"\"\")
        """
        # Split by paragraph breaks
        paragraphs = text.split('\n\n')
        
        # Format with proper indentation for _p() 
        lines = ['_p("""']
        
        for i, para in enumerate(paragraphs):
            # Each paragraph on its own line with indentation
            para_lines = para.split('\n')
            for line in para_lines:
                lines.append(f"    {line.strip()}")
            
            # Add blank line between paragraphs (except after last)
            if i < len(paragraphs) - 1:
                lines.append("")
        
        lines.append('    """)')
        
        return '\n'.join(lines)
    
    def generate_file_header(self, language_code: str, source_file: Path = None) -> str:
        """Generate file header with metadata."""
        from datetime import datetime
        from src.version import VERSION
        
        header = f"""# Ren'Py Translation File
# Language: {language_code}
# Generated by: RenLocalizer v{VERSION}
# Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        if source_file:
            header += f"# Source file: {source_file}\\n"
        
        header += """
# This file contains automatic translations.
# Please review and edit as needed.

"""
        return header
    
    def save_translation_file(self,
                            translation_results: List,
                            output_path: Path,
                            language_code: str,
                            source_file: Path = None,
                            output_format: str = "simple") -> bool:
        """Save translations to file."""
        try:
            # Ensure output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Generate content
            content = self.format_translation_file(
                translation_results,
                language_code,
                source_file,
                output_format=output_format
            )
            
            # Write file with UTF-8 encoding (with BOM for Windows compatibility)
            # Using utf-8-sig ensures Ren'Py correctly reads the file on all systems
            with open(output_path, 'w', encoding='utf-8-sig', newline='\n') as f:
                f.write(content)
            
            self.logger.info(f"Saved translation file: {output_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error saving translation file {output_path}: {e}")
            return False
    
    def organize_output_files(self,
                            translation_results: List,
                            output_base_dir: Path,
                            language_code: str,
                            source_files: List[Path] = None,
                            output_format: str = "old_new",
                            create_renpy_structure: bool = True) -> List[Path]:
        """Organize translations into language-specific directories."""
        
        output_files = []
        
        # Determine if this is a Ren'Py project and create proper structure
        if create_renpy_structure:
            # Check if we're in a Ren'Py project (has game folder)
            game_dir = self._find_game_directory(output_base_dir)
            if game_dir:
                # Create Ren'Py translation structure: game/tl/[language]/
                lang_dir = game_dir / "tl" / language_code
                self.logger.info(f"Creating Ren'Py translation structure: {lang_dir}")
                
                # Create language initialization file for Ren'Py - do it immediately
                self._create_language_init_file(game_dir, language_code)
            else:
                # Not a Ren'Py project, create standard structure
                lang_dir = output_base_dir / language_code
                self.logger.info(f"Creating standard translation structure: {lang_dir}")
        else:
            # Create language directory
            lang_dir = output_base_dir / language_code
        
        lang_dir.mkdir(parents=True, exist_ok=True)
        
        # CRITICAL FIX: Create ONE translation file for all strings
        # This prevents duplicate string errors in Ren'Py
        
        # Global deduplication - remove EXACT duplicates only
        # NOTE: Case-sensitive! "Cafeteria" and "cafeteria" are DIFFERENT strings in Ren'Py
        seen_strings = set()
        unique_results = []
        
        for result in translation_results:
            # Case-sensitive key - Ren'Py treats "Cafeteria" and "cafeteria" as different strings
            string_key = result.original_text.strip()
            if string_key not in seen_strings:
                seen_strings.add(string_key)
                unique_results.append(result)
            else:
                self.logger.debug(f"Skipping duplicate string: {result.original_text[:50]}...")
        
        # Create single master translation file
        # Use 'strings.rpy' for Ren'Py compatibility (same as _run_translate_command)
        output_filename = f"strings.rpy"
        output_path = lang_dir / output_filename
        
        if self.save_translation_file(
            unique_results, 
            output_path, 
            language_code, 
            None,  # No specific source file
            output_format=output_format
        ):
            output_files.append(output_path)
            self.logger.info(f"Created master translation file: {output_path} with {len(unique_results)} unique strings")
        
        return output_files
    
    def _find_game_directory(self, base_path: Path) -> Path:
        """Find the game directory in a Ren'Py project."""
        # Check current directory and parent directories for 'game' folder
        current = Path(base_path).resolve()
        
        # Check if current path contains 'game' folder
        if (current / "game").exists() and (current / "game").is_dir():
            return current / "game"
        
        # Check parent directories
        for parent in current.parents:
            game_dir = parent / "game"
            if game_dir.exists() and game_dir.is_dir():
                # Verify it's a Ren'Py game directory by checking for common files
                if any((game_dir / file).exists() for file in ["options.rpy", "script.rpy", "gui.rpy"]):
                    return game_dir
        
        # Check if current directory itself is the game directory
        if any((current / file).exists() for file in ["options.rpy", "script.rpy", "gui.rpy"]):
            return current
        
        return None
    
    def _create_language_init_file(self, game_dir: Path, language_code: str):
        """RenPy dökümantasyonuna tam uyumlu, akıllı başlatıcı dosya üretimi."""
        try:
            init_file_path = game_dir / f"zzz_{language_code}_language.rpy"
            content = (
                f"# Auto-generated language initializer by RenLocalizer\n"
                f"init 1500 python:\n"
                f"    # Ensure the game switches to this language upon first install or change\n"
                f"    # Using late init (1500) to overwrite other scripts safely\n"
                f"    if getattr(persistent, 'renlocalizer_target_lang', None) != \"{language_code}\":\n"
                f"        persistent.renlocalizer_target_lang = \"{language_code}\"\n"
                f"        _preferences.language = \"{language_code}\"\n"
                f"\n"
                f"define config.default_language = \"{language_code}\"\n"
            )
            with open(init_file_path, 'w', encoding='utf-8-sig', newline='\n') as f:
                f.write(content)
            self.logger.info(f"Created smart language file: {init_file_path}")
        except Exception as e:
            self.logger.error(f"Error creating language init file: {e}")
