"""
Ren'Py-aware parser used by RenLocalizer.

The parser keeps track of indentation-based blocks so it can better decide
which strings should be translated and which ones belong to technical code.
"""

from __future__ import annotations

import asyncio
import ast
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from src.utils.encoding import read_text_safely
import configparser
import yaml
from src.core.deep_extraction import (
    DeepExtractionConfig,
    FStringReconstructor,
    MultiLineStructureParser,
    confidence_band,
    resolve_minimum_extraction_confidence,
    score_extraction_confidence,
    _shared_analyzer as _module_deep_var_analyzer,
)

# Module-level defaults for datasets / whitelist for rpyc reader import
DATA_KEY_BLACKLIST = {
    'id', 'code', 'name_id', 'image', 'img', 'icon', 'sfx', 'sound', 'audio',
    'voice', 'file', 'path', 'url', 'link', 'type', 'ref', 'var', 'value_id', 'texture'
}

DATA_KEY_WHITELIST = {
    'name', 'title', 'description', 'desc', 'text', 'content', 'caption',
    'label', 'prompt', 'help', 'header', 'footer', 'message', 'dialogue',
    'summary', 'quest', 'objective', 'char', 'character',
    'tips', 'hints', 'notes', 'log', 'history', 'inventory', 'items', 
    'objectives', 'goals', 'achievements', 'gallery', 'sender', 'receiver',
    'tooltip', 'alt', 'what', 'who', 'menu', 'hint', 'subtitle', 
    'stat', 'credits', 'authors', 'about', 'version_name', 'hover_text', 'selected_text'
}

# Standard Ren'Py strings to guarantee extraction (Fallthrough)
STANDARD_RENPY_STRINGS = {
    "Start", "Load", "Preferences", "About", "Help", "Quit", "Return",
    "Save", "Load Game", "Main Menu", "History", "Skip", "Auto", "Quick",
    "Q.Save", "Q.Load", "Prefs", "Back", "End Replay", "Yes", "No",
    "Empty Slot", "Test", "Language", "Music", "Sound", "Voice", "Self-Voicing",
    "Clipboard Voicing", "Text Speed", "Auto-Forward Time"
}

# =============================================================================
# TEXT TYPE CONSTANTS (v2.8.7+ - Enhanced classification for button/screen distinction)
# =============================================================================
class TextType:
    """Constants for text extraction types - prevents typos and enables IDE autocomplete."""
    DIALOGUE = 'dialogue'
    NARRATION = 'narration'
    MENU_CHOICE = 'menu_choice'
    SCREEN_TEXT = 'screen_text'
    UI_ACTION = 'ui_action'
    SHOW_TEXT = 'show_text'
    WINDOW_TEXT = 'window_text'
    HIDDEN_ARG = 'hidden_arg'
    IMMEDIATE_TRANSLATION = 'immediate_translation'
    RENPY_FUNC = 'renpy_func'
    CONFIG_TEXT = 'config_text'
    DEFINE_TEXT = 'define_text'
    EXTEND = 'extend'  # extend "text" — continues previous dialogue line
    # v2.8.7+ additions for enhanced classification
    BUTTON_TEXT = 'button_text'  # textbutton "..." action X (UI element)
    SCREEN_TRANSLATABLE = 'screen_translatable'  # text _(...) in screens (UI text)
    TOOLTIP_TEXT = 'tooltip_text'  # tooltip "..." in buttons/screens (v8.0+)

# Shared regex pattern for quoted strings (DRY principle)
# Matches: "text", 'text', r"text", f'text', rf"text", etc.
_QUOTED_STRING_PATTERN = r'(?:[rRuUbBfF]{,2})?(?P<quote>"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')'
HOTKEY_SOURCE_RE = re.compile(r"^(?P<label>.+?)\s*/\s*(?P<hotkey>[A-Za-z])$")

# Safety limits to prevent ReDoS attacks
MAX_LINE_LENGTH = 10000  # Lines longer than this skip regex processing
EMPTY_CHARACTER = ''     # Constant for empty character name in dedup key


@dataclass
class ContextNode:
    indent: int
    kind: str
    name: str = ""


class RenPyParser:
    def __init__(self, config_manager=None):
        self.logger = logging.getLogger(__name__)
        # Backwards-compatible aliases: some callers expect `config` while
        # others (newer code) reference `config_manager`. Keep both.
        self.config = config_manager
        self.config_manager = config_manager
        self._long_line_warning_keys: Set[Tuple[str, int, int]] = set()

        # Technical terms for filtering
        self.renpy_technical_terms = {
            'center', 'top', 'bottom', 'gui', 'config',
            'true', 'false', 'none', 'auto', 'png', 'jpg', 'mp3', 'ogg', 'rpy', 'rpyc', 'rpym', 'rpymc',
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
            'ascii', 'eval', 'exec', 'latin', 'western', 'greedy', 'freetype',
            'narrator', 'window', 'frame', 'vbox', 'hbox', 'side', 'grid', 'viewport',
            'fixed', 'button', 'bar', 'vbar', 'slider', 'scrollbar', 'input',
            # Added from Research: Statements & Keywords
            'layeredimage', 'transform', 'camera', 'expression', 'assert',
            'hotspot', 'hotbar', 'areapicker', 'drag', 'draggroup', 'showif', 'vpgrid',
            # Special Labels & Internal Variables
            'after_load', 'after_warp', 'before_main_menu', 'splashscreen',
            'config', 'preferences', 'gui', 'style', 'persistent',
            # Python Technical & Error Classes
            'Callable', 'Literal', 'Self', 'overload', 'override',
            'AssertionError', 'TypeError', 'ValueError', 'ZeroDivisionError',
            'ArithmeticError', 'AttributeError', 'ImportError', 'IndexError',
            'KeyError', 'NameError', 'RuntimeError', 'StopIteration',
            # Style properties & Engine UI
            'kerning', 'line_leading', 'outlines', 'antialias', 'hinting',
            'vscroller', 'hscroller', 'viewport', 'button', 'input',
            # Additional engine terms
            'zsync', 'zsyncmake', 'rpu', 'ecdsa', 'rsa', 'bbcode', 'markdown',
            'utf8', 'latin1', 'ascii'
        }

        # New: CamelCase or dot notation strings that are likely technical
        self.technical_id_re = re.compile(r'^[a-z]+(?:[A-Z][a-z0-9]+)+$|^[a-z0-9_]+\.[a-z0-9_.]+$')

        # Edge-case: Ren'Py screen language - ignore technical screen elements
        self.technical_screen_elements = {
            'vbox', 'hbox', 'frame', 'window', 'viewport', 'scrollbar', 'bar', 'slider',
            'imagebutton', 'hotspot', 'hotbar', 'side', 'input', 'button', 'confirm', 'notify',
            'layout', 'store', 'style', 'action', 'caption', 'title', 'textbutton', 'label', 'tooltip',
            'null', 'mousearea', 'key', 'timer', 'transform', 'parallel', 'contains', 'block'
        }

        # Edge-case: Ignore lines with only technical terms or variable assignments
        self.technical_line_re = re.compile(r'^(?:define|init|style|config|gui|store|layout)\b.*=\s*[^"\']+$')

        # Edge-case: Ignore lines with only numbers, file paths, or color codes
        self.numeric_or_path_re = re.compile(r'^(?:[0-9]+|[a-zA-Z0-9_/\\.-]+\.(?:png|jpg|ogg|mp3|rpy|rpyc)|#[0-9a-fA-F]{3,8})$')

        # Edge-case: Ignore lines with only Ren'Py variables or tags
        self.renpy_var_or_tag_re = re.compile(r'^(\{[^}]+\}|\[[^\]]+\])$')

        # Edge-case: Ignore lines with only whitespace or comments
        self.comment_or_empty_re = re.compile(r'^(\s*#.*|\s*)$')

        # Edge-case: Menu/choice with technical condition (if, else, jump, call)
        self.menu_technical_condition_re = re.compile(r'^\s*(?:if|else|jump|call)\b.*:')

        # Edge-case: AST node type filtering (for future AST integration)
        self.ast_technical_types = {
            'Store', 'Config', 'Style', 'Layout', 'ImageButton', 'Hotspot', 'Hotbar', 'Slider', 'Viewport', 'ScrollBar', 'Action', 'Confirm', 'Notify', 'Input', 'Frame', 'Window', 'Vbox', 'Hbox', 'Side', 'Caption', 'Title', 'Label', 'Tooltip', 'TextButton'
        }

        # Dosya uzantıları ve yol belirteçleri (Crash önleyici)
        # Bu uzantılara sahip stringler ASLA çevrilmemeli.
        self.file_extensions = {
            '.png', '.jpg', '.jpeg', '.webp', '.avif', '.bmp', '.gif', '.ico',
            '.mp3', '.ogg', '.wav', '.flac', '.opus', '.m4a',
            '.rpy', '.rpyc', '.rpym', '.rpymc', '.py', '.xml', '.json', '.yaml', '.txt',
            '.ttf', '.otf', '.woff', '.woff2'
        }
        self.path_indicators = {'/', '\\', 'http://', 'https://', 'www.'}

        # COMPILATION: Technical Keywords and Patterns (Optimization for O(1) matching)
        # Using re.compile dramatically speeds up checks inside loops
        technical_patterns = [
            r'^#[0-9a-fA-F]+$',
            r'\.ttf$|\.otf$|\.woff2?$',
            r'^%s[%\s]*$',
            r'fps|renderer|ms$',
            r'^[0-9.]+$',
            r'game_menu|sync|input|overlay',
            r'vertical|horizontal|linear',
            r'touch_keyboard|subtitle|empty',
            r'\*\*?/\*\*?', # Glob patterns
            r'\.old$|\.new$|\.bak$',
            r'^[a-z0-9_]+\.[a-z0-9_]+(?:\.[a-z0-9_]+)*$', # module.sub.attr (won't match "wow..." or "oh...")
            r'^[a-z0-9_]+=[^=]+$', # Assignment without double equals
            r'^(?:config|gui|preferences|style)\.[a-z0-9_.]+$', # Internal variables
            r'\b(?:uniform|attribute|varying|vec[234]|mat[234]|gl_FragColor|sampler2D|gl_Position|texture2D|v_tex_coord|a_tex_coord|a_position|u_transform|u_lod_bias)\b', # Shader/GLSL keywords
            r'^--?[a-z0-9_\-]+$', # Command line arguments (e.g. --force, -o)
            r'^[a-z0-9_/.]+\.(?:png|jpg|mp3|ogg|wav|webp|ttf|otf|woff2?|rpyc?|rpa)$', # Asset paths
            r'^[a-zA-Z0-9_]+/[a-zA-Z0-9_/.\-]+$', # Path fragments (folder/file)
            r'^\s*(?:jump|call|show|hide|scene|play|stop|queue)\s+[a-zA-Z0-9_]+(?:\s+[a-zA-Z0-9_]+){0,4}$', # Ren'Py commands (max 5 args)
            r'^\s*(?:if|elif|else|while|for)\s+.*:$', # Control flow (must end with colon)
            r'^\s*\$?\s*[a-zA-Z_]\w*\s*=\s*(?:[a-zA-Z_]\w*|[0-9.]+|\[.*\]|\{.*\})$',  # Variable assignment (strict bounds)
            r'^[\w\-. ]+(?:/[\w\-. ]+)+$',     # Strict path (e.g. audio/bgm.ogg)
        ]
        # Combine patterns into one regex: (?:pattern1)|(?:pattern2)|...
        # Using IgnoreCase flag for broad matching
        self.technical_re = re.compile(r'(?:' + r')|(?:'.join(technical_patterns) + r')', re.IGNORECASE)

        code_patterns = [
            r'renpy\.\w+',           # renpy.store, renpy.config, etc.
            r'\w+\s*=\s*\[',         # list assignment
            r'\w+\s*=\s*\{',         # dict assignment
            r'for\s+\w+\s+in\s+',    # for loop
            r'if\s+\w+\s+in\s+',     # if x in y
            r'\w+\[\w+\]',           # dict/list access
            r'km\[',                 # keymap access
            r'_\w+\s*\(',            # private function call
            r'True\b|False\b|None\b', # Python literals
            r'import\s+|from\s+\w+\s+import', # imports
        ]
        self.code_patterns_re = re.compile(r'(?:' + r')|(?:'.join(code_patterns) + r')')

        # Blacklist / Whitelist for data-file key filtering (used by deep scan)
        self.DATA_KEY_BLACKLIST = set(DATA_KEY_BLACKLIST)
        self.DATA_KEY_WHITELIST = set(DATA_KEY_WHITELIST)

        # --- Core regex patterns and registries (ensure attributes exist for tests) ---
        # Common quoted-string pattern (handles optional prefixes like r, u, b, f)
        self._quoted_string = r'(?:[rRuUbBfF]{,2})?(?P<quote>"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')'

        _dialogue_speaker_name = (
            r'(?!(?:textbutton|text|label|tooltip|screen|menu|scene|show|hide|call|jump|'
            r'python|init|define|default|style|image|caption|frame|transform)\b)'
            r'[A-Za-z_][\w\.]*'
        )
        _dialogue_attr_token = (
            r'(?:@\s*)?-?(?!(?:at|as|behind|onlayer|with|zorder|show|hide|scene|call|jump|'
            r'return|play|stop|queue|pause|python|screen|menu|textbutton|text|label|tooltip|'
            r'window|frame|transform|define|default|style|image|caption)\b)[A-Za-z_][\w-]*'
        )
        _dialogue_attr_tail = rf'(?:\s+{_dialogue_attr_token})*'
        _dialogue_speaker_or_quoted = (
            rf'(?:{_dialogue_speaker_name}|"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')'
        )
        self.char_dialog_re = re.compile(
            rf'^(?P<indent>\s*)(?P<char>{_dialogue_speaker_or_quoted}){_dialogue_attr_tail}\s*'
            r'(?P<quote>"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')'
            r'(?P<trailing>\s*(?:(?:with|nointeract|at)\s+\S+)?\s*(?:#.*)?)$'
        )
        self.narrator_re = re.compile(
            r'^(?P<indent>\s+)(?P<quote>"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')(?P<trailing>\s*(?:(?:with|nointeract|at)\s+\S+)?\s*(?:#.*)?)$'
        )

        self.char_multiline_re = re.compile(
            rf'^(?P<indent>\s*)(?P<char>{_dialogue_speaker_or_quoted}){_dialogue_attr_tail}\s*(?P<delim>"""|\'\'\')(?P<body>.*)$'
        )
        self.narrator_multiline_re = re.compile(
            r'^(?P<indent>\s*)(?P<delim>"""|\'\'\')(?P<body>(?![\s]*\)).*)$'
        )
        self.extend_multiline_re = re.compile(
            r'^(?P<indent>\s*)extend\s+(?P<delim>"""|\'\'\')(?P<body>(?![\s]*\)).*)$'
        )

        self.menu_choice_re = re.compile(
            r'^\s*(?P<quote>"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')\s*(?:\((?:[^)(]*|\([^)]*\))*\)\s*)?(?:if\s+[^:]+)?\s*:\s*'
        )
        self.menu_choice_multiline_re = re.compile(
            r'^\s*(?P<delim>"""|\'\'\')(?P<body>(?![\s]*\)).*)\s*(?:if\s+[^:]+)?\s*:\s*$'
        )
        self.menu_title_re = re.compile(
            r'^\s*menu\s*(?:[rRuUbBfF]{,2})?(?P<quote>"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')?:'
        )

        self.screen_text_re = re.compile(
            r'\s*(?:text|label|tooltip)\s+(?:_\s*\(\s*)?(?:[rRuUbBfF]{,2})?(?P<quote>"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')(?:\s*\))?'
        )
        self.textbutton_re = re.compile(
            r'^\s*textbutton\s+(?:_\s*\(\s*)?(?:[rRuUbBfF]{,2})?(?P<quote>"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')(?:\s*\))?'
        )
        self.textbutton_translatable_re = re.compile(
            r"^\s*textbutton\s+_\s*\(\s*(?:[rRuUbBfF]{,2})?(?P<quote>\"(?:[^\"\\]|\\.)*\"|'(?:[^\\']|\\.)*')\s*\)"
        )
        self.screen_text_translatable_re = re.compile(
            r"^\s*(?:text|label|tooltip)\s+_\s*\(\s*(?:[rRuUbBfF]{,2})?(?P<quote>\"(?:[^\"\\]|\\.)*\"|'(?:[^\\']|\\.)*')\s*\)"
        )
        self.menu_context_hotkey_re = re.compile(
            r"^\s*\"[^\"]+\"\s*:\s*\[\s*"
            r"(?P<quote>\"(?:[^\"\\]|\\.)*\"|'(?:[^\\']|\\.)*')"
            r"\s*,.*\"(?:option|submenu|exit|button)\""
        )
        self.screen_multiline_re = re.compile(
            r'^\s*(?:text|label|tooltip|textbutton)\s+(?:_\s*\(\s*)?(?P<delim>"""|\'\'\')(?P<body>.*)$'
        )

        self.config_string_re = re.compile(
            r"^\s*(?P<kind>config)\.(?P<var_name>(?:name|version|about|menu_|window_title|save_name))\s*=\s*(?:[rRuUbBfF]{,2})?(?P<quote>\"(?:[^\"\\]|\\.)*\"|'(?:[^\\']|\\.)*')"
        )
        self.gui_text_re = re.compile(
            r"^\s*(?P<kind>gui)\.(?P<var_name>(?:text|button|label|title|heading|caption|tooltip|confirm)(?:_[a-z_]*)?(?:\[[^\]]*\])?)\s*=\s*(?P<quote>\"(?:[^\"\\]|\\.)*\"|'(?:[^\\']|\\.)*')"
        )
        self.style_property_re = re.compile(
            r"^\s*style\s*\.\s*(?P<var_name>[a-zA-Z_]\w*)\s*=\s*(?P<quote>\"(?:[^\"\\]|\\.)*\"|'(?:[^\\']|\\.)*')"
        )

        # Simplified patterns to avoid complex nested quoting issues
        self._p_single_re = re.compile(r'^\s*(?:define\s+)?(?:gui|config)\.[a-zA-Z_]\w*\s*=\s*_p\s*\(')
        self._p_multiline_re = re.compile(r'^\s*(?:define\s+)?(?:gui|config)\.[a-zA-Z_]\w*\s*=\s*_p\s*\(\s*"""')
        self._underscore_re = re.compile(r'^\s*(?:define\s+)?[a-zA-Z_]\w*\s*=\s*(?:Character\s*\()?_\s*\(')
        self.define_string_re = re.compile(r'^\s*define\s+(?P<var_name>(?:gui|config)\.[a-zA-Z_]\w*)\s*=\s*' + self._quoted_string)

        self.alt_text_re = re.compile(r'\balt\b')
        self.input_text_re = re.compile(r'\b(default|prefix|suffix)\b')

        self.gui_variable_re = re.compile(r'^\s*gui\.')

        # Use the shared quoted-string pattern for these common cases to avoid
        # duplicated complex literals and accidental unbalanced escapes.
        # REMOVED: renpy.show_re (Dangerous regex that matched technical image names)

        # Actions and Input Prompts (v2.6.4 Extension)
        # Matches: Confirm("Text"), Notify("Text"), renpy.input("Text")
        # Optimized with non-greedy matching and _QUOTED_STRING_PATTERN
        self.action_call_re = re.compile(
            rf'.*?\b(?:Confirm|Notify|Tooltip|MouseTooltip|Help|renpy\.input)\s*\(\s*(?:.*?(?:prompt|message|value)\s*=\s*)?(?:_\s*\(\s*)?{_QUOTED_STRING_PATTERN}'
        )

        # Show Text Statement (v2.6.6): Captures temporary text displays
        # Example: show text "Loading..." at truecenter
        # This is commonly used for loading screens, notifications, etc.
        # Uses _QUOTED_STRING_PATTERN for DRY compliance
        self.show_text_re = re.compile(
            rf'^\s*show\s+text\s+(?:_\s*\(\s*)?{_QUOTED_STRING_PATTERN}(?:\s*\))?'
        )

        # Window Show/Hide with Text (v2.6.6): Captures window transition text
        # Example: window show "Narrator speaking..."
        # Less common but used in some visual novels
        # Extended to include 'window auto' which can also take text
        self.window_text_re = re.compile(
            rf'^\s*window\s+(?:show|hide|auto)\s+{_QUOTED_STRING_PATTERN}'
        )

        # Hidden Arguments (v2.6.6): Captures what_prefix, what_suffix, etc.
        # Example: e "Hello" (what_prefix="{i}", what_suffix="{/i}")
        # These are often missed but contain translatable formatting text
        # Extended to include color, size, font arguments that may contain translatable values
        # Only extract text-bearing hidden args, not technical values (color, size, font, etc.)
        self.hidden_args_re = re.compile(
            rf'\(\s*(?:what_prefix|what_suffix|who_prefix|who_suffix)\s*=\s*{_QUOTED_STRING_PATTERN}'
        )

        # Triple Underscore Immediate Translation (v2.6.6): ___("text")
        # Example: text ___("Hello [player]")
        # Translates AND interpolates variables immediately
        self.triple_underscore_re = re.compile(
            rf'___\s*\(\s*{_QUOTED_STRING_PATTERN}\s*\)'
        )
        # ============================================================
        # V2.6.7: NEW PATTERNS FROM REN'PY DOCUMENTATION RESEARCH
        # ============================================================
        
        # 1. Double Underscore Immediate Translation: __("text")
        # Example: text __("Translate immediately")
        # Similar to _() but translates at definition time
        # FALSE POSITIVE PREVENTION: Must not be inside comments or technical assignments
        self.double_underscore_re = re.compile(
            rf'__\s*\(\s*{_QUOTED_STRING_PATTERN}\s*\)'
        )
        
        # 2. String Interpolation with !t Flag: [variable!t]
        # Example: "I'm feeling [mood!t]."
        # The !t flag marks the variable for translation lookup
        # FALSE POSITIVE PREVENTION: Only extract if the string contains actual text, not just the variable
        # We'll handle this in post-processing, not regex
        self.interpolation_t_flag_re = re.compile(
            r'\[(\w+)!t\]'
        )
        
        # 3. Python Block Translatable Strings: python: ... = _("text")
        # Example: python:\n    message = _("Hello")
        # FALSE POSITIVE PREVENTION: Must be inside python block, not in comments
        # This is context-aware, handled in extraction logic
        self.python_translatable_re = re.compile(
            rf'^\s*(?:[a-zA-Z_]\w*\s*=\s*)?_\s*\(\s*{_QUOTED_STRING_PATTERN}\s*\)'
        )
        
        # 4. ATL Text Blocks: show text "..." at position
        # Already covered by show_text_re, but add ATL-specific patterns
        # Example: show text "Fading..." at truecenter with dissolve
        # FALSE POSITIVE PREVENTION: Must have 'show text' prefix, not 'show image'
        # (Already handled by show_text_re above)
        
        # 5. NVL Mode Dialogue: nvl "text" or nvl clear "text"
        # Example: nvl "This is NVL dialogue"
        # FALSE POSITIVE PREVENTION: Must start with 'nvl' keyword
        self.nvl_dialogue_re = re.compile(
            rf'^\s*nvl\s+(?:clear\s+)?{_QUOTED_STRING_PATTERN}'
        )
        
        # 6. Screen Parameter Text: screen my_screen(param):
        # Example: screen message_box(title, message):
        #              text title
        #              text message
        # FALSE POSITIVE PREVENTION: Only extract if parameter is used with 'text' or similar display element
        # This requires context tracking - we'll mark parameters and track their usage
        self.screen_param_usage_re = re.compile(
            r'^\s*(?:text|label|tooltip)\s+([a-zA-Z_]\w*)(?:\s|$)'
        )
        
        # 7. Image Text Overlays: image name = Text("text")
        # Example: image my_text = Text("Overlay text")
        # FALSE POSITIVE PREVENTION: Must be 'Text()' constructor, not 'text' element
        # Also check for common Text() parameters like size, color to avoid false positives
        self.image_text_overlay_re = re.compile(
            rf'^\s*image\s+\w+\s*=\s*Text\s*\(\s*{_QUOTED_STRING_PATTERN}'
        )
        
        # 8. String Substitution Context: Detect strings that will use !t flag
        # This helps us understand which strings might be interpolated
        # Example: $ mood = _("happy")  ->  "I feel [mood!t]"
        # We'll track these in a separate pass
        self.substitution_var_re = re.compile(
            r'^\s*\$?\s*([a-zA-Z_]\w*)\s*=\s*_\s*\('
        )

        # ============================================================
        # V2.7.1: DEEP EXTRACTION PATTERNS
        # ============================================================

        # 9. Bare Define String: define any_var = "text" (not just gui/config)
        # Example: define quest_title = "The Dark Forest"
        # FALSE POSITIVE PREVENTION: DeepVariableAnalyzer filters non-translatable vars
        self.bare_define_string_re = re.compile(
            r'^\s*define\s+'
            r'(?:(?:-?\d+)\s+)?'
            r'(?P<var_name>[\w.]+)\s*'
            r'=\s*'
            rf'{_QUOTED_STRING_PATTERN}'
            r'\s*$'
        )

        # 10. Bare Default String: default var = "text" (without _() wrapper)
        # Example: default player_title = "Recruit"
        self.bare_default_string_re = re.compile(
            r'^\s*default\s+'
            r'(?P<var_name>[\w.]+)\s*'
            r'=\s*'
            rf'{_QUOTED_STRING_PATTERN}'
            r'\s*$'
        )

        # 11. Character Definition: define var = Character("Name", ...)
        # Example: define mc = Character("Ethan", color="00FFCC")
        # Captures Character, DynamicCharacter, NVLCharacter, ADVCharacter
        # v2.8.7: NEW - Fix for missing character names in translations
        self.character_define_re = re.compile(
            r'^\s*define\s+'
            r'(?P<var_name>\w+)\s*'
            r'=\s*'
            r'(?:Dynamic|NVL|ADV)?Character\s*\(\s*'
            # Support both plain strings and _() wrapped strings
            r'(?:_\s*\(\s*)?'  # Optional: _( prefix
            rf'{_QUOTED_STRING_PATTERN}'
            r'(?:\s*\))?',  # Optional: ) suffix for _()
            re.MULTILINE | re.DOTALL
        )

        # 12. Python Text Call: $ renpy.confirm("text"), $ narrator("text"), etc.
        # Covers Tier-1 API calls from DeepExtractionConfig
        # Note: display_menu excluded — takes a list arg, not a string (handled by AST deep scan)
        # v2.7.2: Expanded to catch custom object methods like gallery.button
        self.python_text_call_re = re.compile(
            r'^\s*\$?\s*'
            r'(?P<func>(?:[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*))'
            r'\s*\(\s*'
            r'(?:[^,]*,\s*)?'
            rf'{_QUOTED_STRING_PATTERN}'
        )

        # 12. f-string Assignment: $ var = f"text {expr} more"
        # Example: $ msg = f"Welcome back, {player_name}!"
        self.fstring_assign_re = re.compile(
            r'^\s*\$?\s*'
            r'(?:(?:define|default)\s+)?'
            r'[\w.]+\s*=\s*'
            r'[fF](?P<fquote>["\'])(?P<fcontent>(?:[^\\"\']|\\.)+?)(?P=fquote)'
            r'\s*$'
        )

        # 13. Screen Language tooltip Property: tooltip "text"
        # Example: textbutton "Save" action FileSave(1) tooltip "Quick save"
        self.tooltip_property_re = re.compile(
            rf'\btooltip\s+{_QUOTED_STRING_PATTERN}'
        )

        # 14. QuickSave/CopyToClipboard with text args
        self.quicksave_re = re.compile(
            rf'QuickSave\s*\([^)]*message\s*=\s*{_QUOTED_STRING_PATTERN}'
        )
        self.copy_clipboard_re = re.compile(
            rf'CopyToClipboard\s*\(\s*{_QUOTED_STRING_PATTERN}'
        )
        self.screen_call_start_re = re.compile(
            r'^\s*(?P<stmt>call|show)\s+screen\s+(?P<screen_name>[A-Za-z_]\w*)\s*(?P<paren>\()'
        )
        self.screen_displayable_call_re = re.compile(
            r'^\s*(?P<property>idle|hover|selected|selected_idle|selected_hover|background|foreground|add)\s+'
            r'(?P<expr>(?:[A-Za-z_][\w.]*)\s*\(.*)$'
        )

        # Deep extraction: use module-level shared analyzer (avoids recompiling 15 regexes per parser instance)
        self._deep_var_analyzer = _module_deep_var_analyzer

        self.layout_text_re = re.compile(r'^\s*(?P<kind>layout)\.(?P<var_name>[a-zA-Z0-9_]+)\s*=\s*' + self._quoted_string)
        self.store_text_re = re.compile(r'^\s*(?P<kind>store)\.(?P<var_name>[a-zA-Z0-9_]+)\s*=\s*' + self._quoted_string)
        self.general_define_re = re.compile(r'^\s*define\s+(?P<var_name>[a-zA-Z0-9_.]+)\s*=\s*' + self._quoted_string)

        # pattern registry placeholder (populated later in code)
        self.pattern_registry = []
        self.multiline_registry = []
        self.menu_def_re = re.compile(r'^menu\s*(?:"([^\"]*)"|\'([^\']*)\')?:')
        self.screen_def_re = re.compile(r'^screen\s+([A-Za-z_]\w*)')
        self.python_block_re = re.compile(r'^(?:init(?:\s+[-+]?\d+)?\s+)?python\b.*:')
        # Label definition (ensure present for tests)
        self.label_def_re = re.compile(r'^label\s+([A-Za-z_][\w\.]*)\s*(?!hide):')
        # Hidden label definition (label xxx hide:) - these should be skipped
        self.hidden_label_re = re.compile(r'^label\s+[A-Za-z_][\w\.]*\s+hide\s*:')
        # -------------------------------------------------------------------------
        
        # Initialize v2.4.1 patterns
        self._init_new_patterns()
        
        # Populate pattern registry for regex extraction pass (3rd pass)
        self._register_patterns()
        
        # State tracking for context-aware filtering
        self._current_context_line = ""

    def _warn_once_for_excessive_line(
        self,
        file_path: Union[str, Path],
        line_number: int,
        line_length: int,
    ) -> None:
        warning_key = (str(file_path), line_number, line_length)
        if warning_key in self._long_line_warning_keys:
            return
        self._long_line_warning_keys.add(warning_key)
        if self.logger.isEnabledFor(logging.WARNING):
            self.logger.warning(
                "Skipping line %s in %s due to excessive length (%s)",
                line_number,
                file_path,
                line_length,
            )

    def _is_deep_feature_enabled(self, feature: str = None) -> bool:
        """
        V2.7.1: Check if a deep extraction feature is enabled via config toggles.
        
        Returns True when config is None (backward compatibility — no config means all features on).
        When config exists, checks master toggle first, then specific feature toggle.
        
        Args:
            feature: Specific toggle name, e.g. 'deep_extraction_bare_defines'.
                     If None, only checks the master toggle.
        """
        if self.config is None:
            return True
        ts = getattr(self.config, 'translation_settings', None)
        if ts is None:
            return True
        # Master toggle
        if not getattr(ts, 'enable_deep_extraction', True):
            return False
        # Specific feature toggle
        if feature:
            return getattr(ts, feature, True)
        return True

    def compute_translation_id(self, label_context: str, statement_text: str, serial: int = 0) -> str:
        """
        Compute Ren'Py-compatible translation ID using MD5 hash.
        
        Ren'Py generates translation IDs as: label_<8charhash>
        For collisions, appends serial: label_<8charhash>m, label_<8charhash>n, etc.
        
        v2.8.3: This ensures RenLocalizer output matches Ren'Py's internal ID format exactly,
        enabling proper loading of generated tl/ translation files.
        
        Args:
            label_context: Current label name (e.g., 'start', 'define_character')
            statement_text: Raw statement text (e.g., 'e "Thank you..."')
            serial: Collision counter (0 = first, 1 = append 'm', 2 = append 'n', etc.)
        
        Returns:
            Translation ID string (e.g., 'start_636ae3f5', 'start_bd1ad9e1m')
        """
        import hashlib
        
        # Normalize label context (remove special chars, lowercase)
        label_clean = label_context.strip().lower() if label_context else 'default'
        label_clean = re.sub(r'[^a-z0-9_]', '_', label_clean)
        label_clean = label_clean[:32]  # Limit length (safety)
        
        # Create hash from statement text (Ren'Py uses MD5 on the statement + label)
        combined = f"{label_clean}:{statement_text}".encode('utf-8', errors='replace')
        hash_obj = hashlib.md5(combined)
        hash_hex = hash_obj.hexdigest()[:8]  # 8-char hex prefix
        
        # Build translation ID
        trans_id = f"{label_clean}_{hash_hex}"
        
        # Handle collisions with serial letters (m, n, o, p, ...)
        if serial > 0:
            # serial=1 → 'm', serial=2 → 'n', etc. (Ren'Py convention)
            serial_char = chr(ord('m') + serial - 1)
            trans_id += serial_char
        
        return trans_id

        
    # ========== NEW PATTERNS FOR BETTER EXTRACTION (v2.4.1) ==========
    # These are initialized in __init__ but need class-level declarations
    nvl_narrator_re = None
    default_translatable_re = None
    show_screen_re = None
    translate_block_re = None

    def _init_new_patterns(self):
        """Initialize v2.4.1 patterns (called from __init__)."""
        import re
        
        # NVL narrator pattern - triple-quoted dialogues
        self.nvl_narrator_re = re.compile(
            r'^\s*nvl\s+clear\s+(?P<delim>"""|\'\'\')(?P<body>.*)$'
        )
        
        # Default translatable variables: default myvar = _("text")
        self.default_translatable_re = re.compile(
            r'^\s*default\s+[a-zA-Z_]\w*\s*=\s*_\s*\(\s*(?P<quote>"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')\s*\)'
        )
        
        # Show screen with string parameters
        self.show_screen_re = re.compile(
            r'^\s*show\s+screen\s+[a-zA-Z_]\w*\s*\((?:[^,)]*,\s*)*(?P<quote>"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')'
        )
        
        # Translate block detection (to skip already translated content)
        self.translate_block_re = re.compile(
            r'^\s*translate\s+([a-zA-Z_]\w*)\s+([a-zA-Z_]\w*)\s*:'
        )
        
        # ================================================================
        # Patterns referenced by _register_patterns() — defined here to
        # prevent AttributeError if _register_patterns() is ever called.
        # ================================================================
        _QS = _QUOTED_STRING_PATTERN
        
        # Notify("text") / renpy.notify("text")
        self.notify_re = re.compile(
            rf'(?:renpy\.)?[Nn]otify\s*\(\s*(?:_\s*\(\s*)?{_QS}'
        )
        # Confirm("text")
        self.confirm_re = re.compile(
            rf'[Cc]onfirm\s*\(\s*(?:_\s*\(\s*)?{_QS}'
        )
        # renpy.input("prompt")
        self.renpy_input_re = re.compile(
            rf'renpy\.input\s*\(\s*(?:_\s*\(\s*)?{_QS}'
        )
        # ATL text: show text "..."
        self.atl_text_re = re.compile(
            rf'^\s*show\s+text\s+(?:_\s*\(\s*)?{_QS}'
        )
        # renpy.say(who, "what")
        self.renpy_say_re = re.compile(
            rf'renpy\.say\s*\([^,]+,\s*{_QS}'
        )
        # Action with _("text"): action=_("text")
        self.action_text_re = re.compile(
            rf'action\s*=?\s*_\s*\(\s*{_QS}'
        )
        # caption "text" in screens
        self.caption_re = re.compile(
            rf'^\s*caption\s+(?:_\s*\(\s*)?{_QS}'
        )
        # frame title / window title text
        self.frame_title_re = re.compile(
            rf'^\s*(?:frame|window)\s+(?:_\s*\(\s*)?{_QS}'
        )
        # Generic _("text") anywhere
        self.generic_translatable_re = re.compile(
            rf'_\s*\(\s*{_QS}\s*\)'
        )
        # side "text" in screens
        self.side_text_re = re.compile(
            rf'^\s*side\s+{_QS}'
        )
        # renpy.function("text") generic
        self.python_renpy_re = re.compile(
            rf'renpy\.\w+\s*\([^)]*{_QS}'
        )
        self.renpy_function_re = re.compile(
            rf'renpy\.(?:say|notify|call_screen)\s*\([^)]*{_QS}'
        )
        # extend "text"
        self.extend_re = re.compile(
            rf'^\s*extend\s+{_QS}'
        )

    # ========== END NEW PATTERNS ==========

    def _register_patterns(self):
        # v2.8.7+ PHASE 1: Text Type Classification Enhancement
        # Pattern Priority: Most specific screen/button patterns FIRST
        # This fixes button classification (was mixed with translatable_string)
        self.pattern_registry = [
            # ========================================================================
            # TIER 1: Screen UI Button Elements (HIGHEST PRIORITY)
            # These distinguish button text from generic translatable strings
            # ========================================================================
            {'regex': self.textbutton_translatable_re, 'type': TextType.BUTTON_TEXT},  # textbutton _("X") - NOW button_text!
            {'regex': self.textbutton_re, 'type': TextType.BUTTON_TEXT},  # textbutton "X"
            {'regex': self.tooltip_property_re, 'type': TextType.TOOLTIP_TEXT},  # tooltip "..." in screens (v8.0+)
            
            # TIER 2: Screen Text Elements (separated from generic translatable)
            {'regex': self.screen_text_translatable_re, 'type': TextType.SCREEN_TRANSLATABLE},  # text _("X") in screens
            {'regex': self.screen_text_re, 'type': 'ui'},  # text/label/tooltip in screens
            {'regex': self.side_text_re, 'type': 'ui'},
            
            # TIER 3: Menu Elements
            {'regex': self.menu_choice_re, 'type': 'menu'},
            {'regex': self.menu_title_re, 'type': 'menu'},
            
            # TIER 4: Foundation Patterns
            {'regex': self.layout_text_re, 'type': 'layout'},
            {'regex': self.store_text_re, 'type': 'store'},
            {'regex': self.general_define_re, 'type': 'define'},
            {'regex': self.alt_text_re, 'type': 'alt_text'},
            {'regex': self.input_text_re, 'type': 'input'},
            {'regex': self.notify_re, 'type': 'notify'},
            {'regex': self.confirm_re, 'type': 'confirm'},
            {'regex': self.renpy_input_re, 'type': 'input'},
            
            # TIER 5: Function Calls & Dialogue
            {'regex': self.atl_text_re, 'type': 'ui'},           # ATL text blocks
            {'regex': self.renpy_say_re, 'type': 'dialogue'},    # renpy.say() calls
            {'regex': self.action_text_re, 'type': 'translatable_string'},  # action _("text")
            {'regex': self.caption_re, 'type': 'ui'},            # caption attributes
            {'regex': self.frame_title_re, 'type': 'ui'},        # frame/window titles
            {'regex': self.generic_translatable_re, 'type': 'translatable_string'},  # generic _()
            {'regex': self._p_single_re, 'type': 'paragraph'},
            {'regex': self._underscore_re, 'type': 'translatable_string'},
            {'regex': self.define_string_re, 'type': 'define'},
            
            # TIER 6: Config & GUI
            {'regex': self.config_string_re, 'type': 'config'},
            {'regex': self.gui_text_re, 'type': 'gui'},
            {'regex': self.style_property_re, 'type': 'style'},
            
            # TIER 7: Python & Ren'Py Functions
            {'regex': self.python_renpy_re, 'type': 'renpy_func'},
            {'regex': self.renpy_function_re, 'type': 'renpy_func'},
            
            # TIER 8: Dialogue Patterns (Most General - Last)
            {'regex': self.char_dialog_re, 'type': 'dialogue', 'character_group': 'char'},
            {'regex': self.extend_re, 'type': TextType.EXTEND},
            {'regex': self.narrator_re, 'type': 'dialogue'},
            {'regex': self.gui_variable_re, 'type': 'gui'},
            
            # V2.6.7+: Extended Patterns
            {'regex': self.double_underscore_re, 'type': TextType.IMMEDIATE_TRANSLATION},  # __("text")
            {'regex': self.python_translatable_re, 'type': 'translatable_string'},  # Python block _()
            {'regex': self.nvl_dialogue_re, 'type': TextType.DIALOGUE},  # NVL mode dialogue
            {'regex': self.image_text_overlay_re, 'type': TextType.SCREEN_TEXT},  # image = Text("text")
            
            # V2.4.1+: Additional Patterns
            {'regex': self.default_translatable_re, 'type': 'translatable_string'},
            {'regex': self.show_screen_re, 'type': 'ui'},
            
            # V2.7.1+: Deep Extraction Patterns
            {'regex': self.bare_define_string_re, 'type': TextType.DEFINE_TEXT, 'deep_extract': True},
            {'regex': self.character_define_re, 'type': 'character_name', 'deep_extract': False},
            {'regex': self.bare_default_string_re, 'type': TextType.DEFINE_TEXT, 'deep_extract': True},
            {'regex': self.python_text_call_re, 'type': TextType.RENPY_FUNC},
        ]

        self.multiline_registry = [
            {'regex': self.char_multiline_re, 'type': 'dialogue', 'character_group': 'char'},
            {'regex': self.extend_multiline_re, 'type': TextType.EXTEND},
            {'regex': self.narrator_multiline_re, 'type': 'dialogue'},
            {'regex': self.screen_multiline_re, 'type': 'ui'},
            # _p() multi-line patterns - check FIRST as it's most specific
            {'regex': self._p_multiline_re, 'type': 'paragraph'},
            # NEW v2.4.1 patterns
            {'regex': self.nvl_narrator_re, 'type': 'dialogue'},
        ]

        self.renpy_technical_terms = {
            'center', 'top', 'bottom', 'gui', 'config',
            'true', 'false', 'none', 'auto', 'png', 'jpg', 'mp3', 'ogg',
            'dissolve', 'fade', 'pixellate', 'move', 'moveinright', 'moveoutright',
            'zoom', 'alpha', 'xalign', 'yalign', 'xpos', 'ypos', 'xanchor', 'yanchor',
            'xzoom', 'yzoom', 'rotate', 'around', 'align', 'pos', 'anchor',
            'rgba', 'rgb', 'hex', 'matrix'
        }

        # Blacklist for technical keys in data files
        self.DATA_KEY_BLACKLIST = set(DATA_KEY_BLACKLIST)
        # Whitelist for keys that usually contain user-facing text
        self.DATA_KEY_WHITELIST = set(DATA_KEY_WHITELIST)

    def extract_from_csv(self, file_path: Path) -> List[Dict[str, Any]]:
        """Extract translatable text from CSV files."""
        entries = []
        try:
            import csv
            # Ren'Py devs often use UTF-8, but sometimes Excel saves as CP1252. We try UTF-8 first.
            try:
                content = self._read_file_lines(file_path)
            except Exception:
                # Fallback to reading as generic text if helper fails
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.readlines()
            # Re-join to parse with CSV module
            full_text = '\n'.join(content)
            from io import StringIO
            f_io = StringIO(full_text)
            # Detect dialect (separator , or ;)
            try:
                dialect = csv.Sniffer().sniff(full_text[:1024])
            except csv.Error:
                dialect = None
            reader = csv.reader(f_io, dialect) if dialect else csv.reader(f_io)
            _csv_header_row = None  # for header detection
            for row_idx, row in enumerate(reader):
                # ── CSV header row guard ──
                # Row 0 is very likely a header row (column names like "Name",
                # "Type", "Description").  Translating these causes key collisions
                # in strings.json (e.g. "Name" → "İsim" would replace all
                # occurrences of the word "Name" in dialogue).  Heuristic: if
                # EVERY non-empty cell in row 0 is a single word or short
                # identifier (no spaces, <20 chars, all ASCII-alnum/underscore),
                # treat it as a header row and skip it.
                if row_idx == 0:
                    _csv_header_row = row
                    _non_empty = [c.strip() for c in row if c.strip()]
                    if _non_empty and all(
                        len(c) < 20 and ' ' not in c and c.replace('_', '').replace('-', '').isalnum()
                        for c in _non_empty
                    ):
                        self.logger.debug(f"CSV header row skipped (detected as column names): {_non_empty[:5]}")
                        continue

                for col_idx, cell in enumerate(row):
                    # Use existing smart filter
                    # Additional sanity: remove placeholders/tags and require at least
                    # two letters to be considered translatable; attach a raw_text
                    # field (escaped and quoted) for deterministic ID generation.
                    import re
                    cleaned = re.sub(r'(\[[^\]]+\]|\{[^}]+\})', '', cell or '').strip()
                    # Language-independent: require at least two Unicode letters
                    if sum(1 for ch in cleaned if ch.isalpha()) < 2:
                        continue
                    raw_text = '"' + (cell.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')) + '"'
                    entries.append({
                        'text': cell,
                        'raw_text': raw_text,
                        'line_number': row_idx + 1,
                        'context_line': f"csv:row{row_idx}_col{col_idx}",
                        'text_type': 'string',
                        'file_path': str(file_path)
                    })
        except Exception as e:
            self.logger.error(f"CSV parsing error {file_path}: {e}")
        return entries

    def extract_from_txt(self, file_path: Path) -> List[Dict[str, Any]]:
        """Extract translatable text from TXT files (one line = one entry)."""
        entries = []
        try:
            lines = self._read_file_lines(file_path)
            for idx, line in enumerate(lines):
                line = line.strip()
                # Tighten TXT filters: require two Unicode letters after removing placeholders/tags
                import re
                cleaned = re.sub(r'(\[[^\]]+\]|\{[^}]+\})', '', line or '').strip()
                if sum(1 for ch in cleaned if ch.isalpha()) < 2:
                    continue
                raw_text = '"' + (line.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')) + '"'
                entries.append({
                    'text': line,
                    'raw_text': raw_text,
                    'line_number': idx + 1,
                    'context_line': f"txt:line{idx+1}",
                    'text_type': 'string',
                    'file_path': str(file_path)
                })
        except Exception as e:
            self.logger.error(f"TXT parsing error {file_path}: {e}")
        return entries

    def extract_translatable_text(self, file_path: Union[str, Path]) -> Set[str]:
        entries = self.extract_text_entries(file_path)
        return {entry['text'] for entry in entries}

    async def extract_translatable_text_async(self, file_path: Union[str, Path]) -> Set[str]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.extract_translatable_text, file_path)

    def extract_text_entries(self, file_path: Union[str, Path]) -> List[Dict[str, Any]]:
        """
        Gelişmiş extraction: Pyparsing grammar + context-aware regex ile UI/screen bloklarını ve Python _() fonksiyonlarını tam kapsar.
        Her entry'ye context_path ve text_type ekler, loglamayı artırır.
        """
        try:
            lines = self._read_file_lines(file_path)
        except Exception as exc:
            self.logger.error("Error reading %s: %s", file_path, exc)
            return []

        entries: List[Dict[str, Any]] = []
        seen_texts = set()
        # Prepare full content for token/lexer or pyparsing passes
        content = '\n'.join(lines)

        # 1. Pyparsing grammar ile ana extraction (tüm dosya)
        try:
            from src.core.pyparse_grammar import extract_with_pyparsing
            py_entries = extract_with_pyparsing(content, file_path=str(file_path))
            for entry in py_entries:
                ctx = entry.get('context_path') or []
                if isinstance(ctx, str):
                    ctx = [ctx]
                text_value = entry.get('text', '')
                if not self.is_meaningful_text(text_value):
                    continue
                
                # V2.7.2: Deep Variable Analysis for global Pyparsing entries
                ctx_line = entry.get('context_line', '')
                if ctx_line and ('define ' in ctx_line or 'default ' in ctx_line):
                    m_var = re.match(r'^\s*(?:define|default)\s+(?P<var_name>[a-zA-Z0-9_.]+)\s*=', ctx_line)
                    if m_var:
                        if not self._is_deep_feature_enabled('deep_extraction_bare_defines'):
                            continue  # Feature disabled → skip bare define/default strings
                        var_name = m_var.group('var_name')
                        if not self._deep_var_analyzer.is_likely_translatable(var_name):
                            continue
                # Use raw_text when available for canonical deduplication,
                # and normalize escape/newline variants so different extraction
                # passes don't produce duplicate IDs for the same literal.
                raw_text = entry.get('raw_text')
                canonical = raw_text or text_value
                canonical = canonical.replace('\r\n', '\n').replace('\r', '\n')
                # Only unescape if we have raw_text (source-level escapes);
                # text_value is already unescaped — double-decoding corrupts it.
                if raw_text:
                    canonical = self._safe_unescape(canonical)
                # Use canonical for deduplication to collapse "Text" and "Text\n" and "Text"
                # But keep original context for reconstruction if needed
                key = (canonical, entry.get('character', ''), tuple(ctx))
                
                # Check if we already have this text in this context (ignore line number differences)
                if key not in seen_texts:
                    # Route through _record_entry for text_type resolution and
                    # user-configurable type filtering (_should_translate_text).
                    filtered_entry = self._record_entry(
                        text=text_value,
                        raw_text=entry.get('raw_text'),
                        line_number=entry.get('line_number', 0),
                        context_line=entry.get('context_line', ''),
                        text_type=entry.get('text_type') or entry.get('type', ''),
                        context_path=list(ctx),
                        character=entry.get('character', ''),
                        file_path=str(file_path),
                    )
                    if filtered_entry:
                        entries.append(filtered_entry)
                        seen_texts.add(key)
        except Exception as e:
            self.logger.warning(f"Pyparsing ana extraction başarısız: {e}")

        # 1b. Lightweight lexer-based extraction (TokenStream iterator)
        try:
            from src.core.renpy_lexer import TokenStream
            stream = TokenStream(content, file_path=str(file_path))
            for token in stream:
                if token.type not in ("STRING", "TRIPLE_STRING"):
                    continue
                ctx = token.context_path or []
                if isinstance(ctx, str):
                    ctx = [ctx]
                text_value = token.text or ''
                if not self.is_meaningful_text(text_value):
                    continue
                
                # V2.7.2: Deep Variable Analysis for TokenStream entries
                ctx_line = token.context_line
                if ctx_line and ('define ' in ctx_line or 'default ' in ctx_line):
                    m_var = re.match(r'^\s*(?:define|default)\s+(?P<var_name>[a-zA-Z0-9_.]+)\s*=', ctx_line)
                    if m_var:
                        if not self._is_deep_feature_enabled('deep_extraction_bare_defines'):
                            continue  # Feature disabled → skip bare define/default strings
                        var_name = m_var.group('var_name')
                        if not self._deep_var_analyzer.is_likely_translatable(var_name):
                            continue
                raw_txt = token.raw_text
                canonical = raw_txt or text_value
                canonical = canonical.replace('\r\n', '\n').replace('\r', '\n')
                if raw_txt:
                    canonical = self._safe_unescape(canonical)
                key = (canonical, token.character or '', tuple(ctx))
                if key not in seen_texts:
                    entry = self._record_entry(
                        text=token.text,
                        raw_text=token.raw_text,
                        line_number=token.line_number or 0,
                        context_line=token.context_line,
                        text_type=token.text_type,
                        context_path=list(ctx),
                        character=token.character or '',
                        file_path=str(file_path),
                    )
                    if entry:
                        entries.append(entry)
                        seen_texts.add(key)
        except Exception as e:
            self.logger.debug(f"TokenStream extraction unavailable or failed: {e}")

        # 1c. Stateful Lexer extraction (when enable_stateful_lexer=True)
        if self.config and hasattr(self.config, 'translation_settings') and getattr(self.config.translation_settings, 'enable_stateful_lexer', False):
            try:
                from src.core.renpy_lexer import RenPyLexer
                lexer = RenPyLexer()
                lexer_tokens = lexer.tokenize(content, file_path=str(file_path))
                for token in lexer_tokens:
                    text_value = token.text or ''
                    if not self.is_meaningful_text(text_value):
                        continue
                    ctx_line = token.raw_line or ''
                    if ctx_line and ('define ' in ctx_line or 'default ' in ctx_line):
                        m_var = re.match(r'^\s*(?:define|default)\s+(?P<var_name>[a-zA-Z0-9_.]+)\s*=', ctx_line)
                        if m_var:
                            if not self._is_deep_feature_enabled('deep_extraction_bare_defines'):
                                continue  # Feature disabled → skip bare define/default strings
                            var_name = m_var.group('var_name')
                            if not self._deep_var_analyzer.is_likely_translatable(var_name):
                                continue
                    ctx = token.context_path or []
                    key = (text_value, token.character or '', tuple(ctx))
                    if key not in seen_texts:
                        entry = self._record_entry(
                            text=text_value,
                            raw_text=text_value,
                            line_number=token.line_number or 0,
                            context_line=token.raw_line,
                            text_type=token.text_type or 'dialogue',
                            context_path=list(ctx),
                            character=token.character or '',
                            file_path=str(file_path),
                        )
                        if entry:
                            entries.append(entry)
                            seen_texts.add(key)
            except Exception as e:
                self.logger.warning("StatefulLexer pass failed for %s (%s), continuing with standard passes", file_path, e)

        # 2. Regex ile context-aware extraction (UI, screen, python _() fonksiyonları)
        context_stack: List[ContextNode] = []
        
        for idx, raw_line in enumerate(lines):
            if not raw_line or raw_line.isspace():
                continue
                
            stripped_line = raw_line.strip()
            indent = self._calculate_indent(raw_line)
            
            # --- Indentation-based Context Management ---
            # 1. Pop context nodes that are no longer active (shallower than current indent)
            self._pop_contexts(context_stack, indent)
            
            # 2. Detect if this line starts a new context (label, screen, menu, python)
            new_node = self._detect_new_context(stripped_line, indent)
            
            # Skip comments early
            if stripped_line.startswith('#'):
                if new_node: # Should not happen with current _detect_new_context but just in case
                    context_stack.append(new_node)
                continue

            # Build current path for the entries found on this line
            # If a new node is starting, it is part of the context for any string on this line
            current_path = self._build_context_path(context_stack, new_node)
            
            # 3. If it's a new context node, push it to stack AFTER building path for current strings 
            # (unless it's a one-line block? Ren'Py usually isn't)
            if new_node:
                context_stack.append(new_node)
            
            # --- String Extraction ---
            # ReDoS Prevention: Skip overly long lines before ANY regex processing
            if len(raw_line) > MAX_LINE_LENGTH:
                self._warn_once_for_excessive_line(
                    file_path=file_path,
                    line_number=idx + 1,
                    line_length=len(raw_line),
                )
                continue

            for descriptor in self.pattern_registry:
                match = descriptor['regex'].match(raw_line)
                if not match:
                    continue
                
                quotes = [
                    match.group(name)
                    for name in match.groupdict()
                    if name.startswith('quote') and match.group(name)
                ]
                if not quotes and 'quote' in match.groupdict():
                    quote_value = match.groupdict().get('quote')
                    if quote_value:
                        quotes = [quote_value]
                
                # FIX: _p_single_re has no capture group — extract _p() argument separately
                if not quotes and descriptor.get('type') == 'paragraph':
                    import re as _re_p
                    p_match = _re_p.search(
                        r'_p\s*\(\s*(?:[rRuUbBfF]{,2})?(?P<quote>"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')',
                        raw_line
                    )
                    if p_match:
                        quotes = [p_match.group('quote')]

                if not quotes:
                    continue
                
                # V2.7.1: Deep Extraction variable name filtering
                # For bare define/default patterns, check if variable name suggests translatable content
                _desc_type = descriptor.get('type', '')
                if descriptor.get('deep_extract') or _desc_type in (TextType.DEFINE_TEXT, 'define', 'store', 'layout', 'config', 'gui', 'style'):
                    # Respect config toggle — skip if deep extraction for bare defines is disabled (only for non-essential types)
                    if _desc_type in (TextType.DEFINE_TEXT, 'define') and not self._is_deep_feature_enabled('deep_extraction_bare_defines'):
                        # If it's a bare define and feature is off, skip it
                        continue
                        
                    var_name = match.groupdict().get('var_name', '')
                    if var_name:
                        if not self._deep_var_analyzer.is_likely_translatable(var_name):
                            if self.logger.isEnabledFor(logging.DEBUG):
                                self.logger.debug(f"Skipping non-translatable variable: {var_name}")
                            continue

                character = ""
                char_group = descriptor.get('character_group')
                if char_group and match.groupdict().get(char_group):
                    character = match.group(char_group)
                    if character and len(character) >= 2 and character[0] == character[-1] and character[0] in ('"', "'"):
                        character = character[1:-1]
                
                for quote in quotes:
                    # preserve both raw and unescaped variants for exact matching and ID generation
                    raw, text = self._extract_string_raw_and_unescaped(quote, start_line=idx, lines=lines)
                    key = (text, character, tuple(current_path))
                    
                    if key in seen_texts:
                        continue
                    
                    text_type = descriptor.get('type') or self.determine_text_type(
                        text, stripped_line, current_path
                    )
                    
                    entry = self._record_entry(
                        text=text,
                        raw_text=raw,
                        line_number=idx + 1,
                        context_line=stripped_line,
                        text_type=text_type,
                        context_path=list(current_path),
                        character=character,
                        file_path=str(file_path),
                    )
                    
                    if entry:
                        entries.append(entry)
                        seen_texts.add(key)
                        log_line = f"{file_path}:{idx+1} [{text_type}] ctx={current_path} text={text}"
                        self.logger.info(f"[ENTRY] {log_line}")
                break

            menu_context_match = self.menu_context_hotkey_re.match(raw_line)
            if menu_context_match:
                self._process_secondary_extraction(
                    match=menu_context_match,
                    text_type=TextType.MENU_CHOICE,
                    raw_line=raw_line,
                    idx=idx,
                    lines=lines,
                    stripped_line=stripped_line,
                    current_path=current_path,
                    seen_texts=seen_texts,
                    entries=entries,
                    file_path=file_path
                )

            # --- V2.6.4: Secondary Pass for Actions (Confirm, Notify, Input) ---
            # This runs independently so we can capture BOTH the button text AND the action prompt on the same line.
            # CRITICAL FIX (v2.6.6): Now uses helper method with proper unescaped text check
            action_match = self.action_call_re.match(raw_line)
            if action_match:
                self._process_secondary_extraction(
                    match=action_match,
                    text_type=TextType.UI_ACTION,
                    raw_line=raw_line,
                    idx=idx,
                    lines=lines,
                    stripped_line=stripped_line,
                    current_path=current_path,
                    seen_texts=seen_texts,
                    entries=entries,
                    file_path=file_path
                )

            # --- V2.6.6: Secondary Pass for Show Text Statement ---
            # Captures: show text "Loading..." at truecenter
            show_text_match = self.show_text_re.match(raw_line)
            if show_text_match:
                self._process_secondary_extraction(
                    match=show_text_match,
                    text_type=TextType.SHOW_TEXT,
                    raw_line=raw_line,
                    idx=idx,
                    lines=lines,
                    stripped_line=stripped_line,
                    current_path=current_path,
                    seen_texts=seen_texts,
                    entries=entries,
                    file_path=file_path
                )

            # --- V2.6.6: Secondary Pass for Window Show/Hide Text ---
            # Captures: window show "Narrator speaking..."
            window_match = self.window_text_re.match(raw_line)
            if window_match:
                self._process_secondary_extraction(
                    match=window_match,
                    text_type=TextType.WINDOW_TEXT,
                    raw_line=raw_line,
                    idx=idx,
                    lines=lines,
                    stripped_line=stripped_line,
                    current_path=current_path,
                    seen_texts=seen_texts,
                    entries=entries,
                    file_path=file_path
                )

            # --- V2.6.6: Secondary Pass for Hidden Arguments ---
            # Captures: e "Hello" (what_prefix="{i}", what_suffix="{/i}")
            # Note: This can match multiple times per line (prefix AND suffix)
            for hidden_match in self.hidden_args_re.finditer(raw_line):
                self._process_secondary_extraction(
                    match=hidden_match,
                    text_type=TextType.HIDDEN_ARG,
                    raw_line=raw_line,
                    idx=idx,
                    lines=lines,
                    stripped_line=stripped_line,
                    current_path=current_path,
                    seen_texts=seen_texts,
                    entries=entries,
                    file_path=file_path
                )

            # --- V2.6.6: Secondary Pass for Triple Underscore Translation ---
            # Captures: text ___("Hello [player]")
            # Note: Can appear multiple times per line
            for triple_match in self.triple_underscore_re.finditer(raw_line):
                self._process_secondary_extraction(
                    match=triple_match,
                    text_type=TextType.IMMEDIATE_TRANSLATION,
                    raw_line=raw_line,
                    idx=idx,
                    lines=lines,
                    stripped_line=stripped_line,
                    current_path=current_path,
                    seen_texts=seen_texts,
                    entries=entries,
                    file_path=file_path
                )

            # --- V2.6.7: Secondary Pass for Double Underscore Translation ---
            # Captures: text __("Translate immediately")
            # Note: Can appear multiple times per line
            for double_match in self.double_underscore_re.finditer(raw_line):
                self._process_secondary_extraction(
                    match=double_match,
                    text_type=TextType.IMMEDIATE_TRANSLATION,
                    raw_line=raw_line,
                    idx=idx,
                    lines=lines,
                    stripped_line=stripped_line,
                    current_path=current_path,
                    seen_texts=seen_texts,
                    entries=entries,
                    file_path=file_path
                )

            # --- V2.6.7: Secondary Pass for NVL Dialogue ---
            # Captures: nvl "text" or nvl clear "text"
            nvl_match = self.nvl_dialogue_re.match(raw_line)
            if nvl_match:
                self._process_secondary_extraction(
                    match=nvl_match,
                    text_type=TextType.DIALOGUE,
                    raw_line=raw_line,
                    idx=idx,
                    lines=lines,
                    stripped_line=stripped_line,
                    current_path=current_path,
                    seen_texts=seen_texts,
                    entries=entries,
                    file_path=file_path
                )

            # --- V2.6.7: Secondary Pass for Image Text Overlays ---
            # Captures: image name = Text("text")
            image_text_match = self.image_text_overlay_re.match(raw_line)
            if image_text_match:
                self._process_secondary_extraction(
                    match=image_text_match,
                    text_type=TextType.SCREEN_TEXT,
                    raw_line=raw_line,
                    idx=idx,
                    lines=lines,
                    stripped_line=stripped_line,
                    current_path=current_path,
                    seen_texts=seen_texts,
                    entries=entries,
                    file_path=file_path
                )

            # --- V2.7.1: Secondary Pass for Tooltip Properties ---
            # Captures: textbutton "X" action Y tooltip "Hint text"
            if self._is_deep_feature_enabled('deep_extraction_tooltip_properties'):
                tooltip_match = self.tooltip_property_re.search(raw_line)
                if tooltip_match:
                    self._process_secondary_extraction(
                        match=tooltip_match,
                        text_type=TextType.UI_ACTION,
                        raw_line=raw_line,
                        idx=idx,
                        lines=lines,
                        stripped_line=stripped_line,
                        current_path=current_path,
                        seen_texts=seen_texts,
                        entries=entries,
                        file_path=file_path
                    )

            # --- V2.7.1: Secondary Pass for QuickSave message ---
            # Captures: QuickSave(message="Saved!")
            if self._is_deep_feature_enabled('deep_extraction_extended_api'):
                qs_match = self.quicksave_re.search(raw_line)
                if qs_match:
                    self._process_secondary_extraction(
                        match=qs_match,
                        text_type=TextType.UI_ACTION,
                        raw_line=raw_line,
                        idx=idx,
                        lines=lines,
                        stripped_line=stripped_line,
                        current_path=current_path,
                        seen_texts=seen_texts,
                        entries=entries,
                        file_path=file_path
                    )

            # --- V2.7.1: Secondary Pass for CopyToClipboard ---
            # Captures: CopyToClipboard("Link copied")
            if self._is_deep_feature_enabled('deep_extraction_extended_api'):
                ctc_match = self.copy_clipboard_re.search(raw_line)
                if ctc_match:
                    self._process_secondary_extraction(
                        match=ctc_match,
                        text_type=TextType.UI_ACTION,
                        raw_line=raw_line,
                        idx=idx,
                        lines=lines,
                        stripped_line=stripped_line,
                        current_path=current_path,
                        seen_texts=seen_texts,
                        entries=entries,
                        file_path=file_path
                    )

            # --- V2.7.1: Secondary Pass for f-string Assignments ---
            # Captures: $ msg = f"Welcome back, {player_name}!"
            if self._is_deep_feature_enabled('deep_extraction_fstrings'):
                fstr_match = self.fstring_assign_re.match(raw_line)
                if fstr_match:
                    try:
                        fcontent = fstr_match.group('fcontent')
                        template = FStringReconstructor.extract_template(fcontent)
                        if template and self.is_meaningful_text(template):
                            key = (template, EMPTY_CHARACTER, tuple(current_path) if current_path else ())
                            if key not in seen_texts:
                                entry = self._record_entry(
                                    text=template,
                                    raw_text=f'"{template}"',
                                    line_number=idx + 1,
                                    context_line=stripped_line,
                                    text_type=TextType.DEFINE_TEXT,
                                    context_path=list(current_path) if current_path else [],
                                    character=EMPTY_CHARACTER,
                                    file_path=str(file_path),
                                )
                                if entry:
                                    entries.append(entry)
                                    seen_texts.add(key)
                                    if self.logger.isEnabledFor(logging.INFO):
                                        self.logger.info(f"[ENTRY+FSTRING] {file_path}:{idx+1} text={template}")
                    except Exception as e:
                        if self.logger.isEnabledFor(logging.DEBUG):
                            self.logger.debug(f"f-string extraction failed at {file_path}:{idx+1}: {e}")

            # --- V2.7.1: Secondary Pass for Bare Define Strings ---
            # Captures: define quest_title = "The Dark Forest"
            # Uses DeepVariableAnalyzer to filter non-translatable var names
            if self._is_deep_feature_enabled('deep_extraction_bare_defines'):
                bare_def_match = self.bare_define_string_re.match(raw_line)
                if bare_def_match:
                    var_name = bare_def_match.group('var_name')
                    if self._deep_var_analyzer.is_likely_translatable(var_name):
                        self._process_secondary_extraction(
                            match=bare_def_match,
                            text_type=TextType.DEFINE_TEXT,
                            raw_line=raw_line,
                            idx=idx,
                            lines=lines,
                            stripped_line=stripped_line,
                            current_path=current_path,
                            seen_texts=seen_texts,
                            entries=entries,
                            file_path=file_path
                        )

            # --- V2.7.1: Secondary Pass for Bare Default Strings ---
            # Captures: default player_title = "Recruit"
            if self._is_deep_feature_enabled('deep_extraction_bare_defaults'):
                bare_default_match = self.bare_default_string_re.match(raw_line)
                if bare_default_match:
                    var_name = bare_default_match.group('var_name')
                    if self._deep_var_analyzer.is_likely_translatable(var_name):
                        self._process_secondary_extraction(
                            match=bare_default_match,
                            text_type=TextType.DEFINE_TEXT,
                            raw_line=raw_line,
                            idx=idx,
                            lines=lines,
                            stripped_line=stripped_line,
                            current_path=current_path,
                            seen_texts=seen_texts,
                            entries=entries,
                            file_path=file_path
                        )

            # --- v2.7.2: Secondary Pass for generic Python Method/Function calls ---
            # Using DeepExtractionConfig.TIER1_TEXT_CALLS to filter meaningful calls
            if self._is_deep_feature_enabled('deep_extraction_extended_api'):
                # Try search instead of match for flexible in-line detection
                for py_text_match in self.python_text_call_re.finditer(raw_line):
                    func_name = py_text_match.group('func')
                    # TIER1_TEXT_CALLS holds the whitelist of functions we trust
                    tier1_calls = DeepExtractionConfig.get_merged_text_calls(self.config)
                    if func_name in tier1_calls:
                        self._process_secondary_extraction(
                            match=py_text_match,
                            text_type=TextType.RENPY_FUNC,
                            raw_line=raw_line,
                            idx=idx,
                            lines=lines,
                            stripped_line=stripped_line,
                            current_path=current_path,
                            seen_texts=seen_texts,
                            entries=entries,
                            file_path=file_path
                        )

            # --- v2.7.7: Secondary Pass for call/show screen string arguments ---
            # Captures user-facing titles/prompts such as:
            #   call screen menu_interactive_scr("COMMUNICATION UPLINK ESTABLISHED...", ...)
            if self._is_deep_feature_enabled('deep_extraction_screen_arguments'):
                screen_call_match = self.screen_call_start_re.match(raw_line)
                if screen_call_match:
                    paren_col = screen_call_match.start('paren')
                    expr_source, _ = self._collect_parenthesized_expression(lines, idx, paren_col)
                    wrapped_expr = f"__screen_call{expr_source}" if expr_source else ""
                    for raw_candidate, text_candidate in self._extract_expression_text_candidates(
                        wrapped_expr,
                        mode='screen_call',
                    ):
                        self._record_secondary_text_candidate(
                            text=text_candidate,
                            raw_text=raw_candidate,
                            text_type=TextType.UI_ACTION,
                            idx=idx,
                            stripped_line=stripped_line,
                            current_path=current_path,
                            seen_texts=seen_texts,
                            entries=entries,
                            file_path=file_path,
                            log_label='SCREEN_CALL',
                        )

            # --- v2.7.7: Secondary Pass for screen helper/displayable call args ---
            # Captures UI labels embedded in helper calls such as:
            #   idle build_loc_icon("pool_icon.png", "Pool", overlay)
            if self._is_deep_feature_enabled('deep_extraction_displayable_calls'):
                displayable_call_match = self.screen_displayable_call_re.match(raw_line)
                if displayable_call_match:
                    expr_col = displayable_call_match.start('expr')
                    expr_source, _ = self._collect_parenthesized_expression(lines, idx, expr_col)
                    for raw_candidate, text_candidate in self._extract_expression_text_candidates(
                        expr_source,
                        mode='displayable_call',
                    ):
                        self._record_secondary_text_candidate(
                            text=text_candidate,
                            raw_text=raw_candidate,
                            text_type=TextType.SCREEN_TEXT,
                            idx=idx,
                            stripped_line=stripped_line,
                            current_path=current_path,
                            seen_texts=seen_texts,
                            entries=entries,
                            file_path=file_path,
                            log_label='DISPLAYABLE_CALL',
                        )

        # --- v2.8.7: Full-content scan for multiline character definitions ---
        # character_define_re uses re.DOTALL and must match across multiple lines.
        # The per-line scan above can't catch these, so we scan the full content.
        try:
            for cd_match in self.character_define_re.finditer(content):
                quote = cd_match.group('quote')
                text = self._extract_string_content(quote) if quote else ''
                if not text or not self.is_meaningful_text(text) or text in seen_texts:
                    continue
                line_num = content[:cd_match.start()].count('\n') + 1
                ctx_line = cd_match.group(0).split('\n')[0][:200]
                entry = self._record_entry(
                    text=text,
                    line_number=line_num,
                    context_line=ctx_line,
                    text_type='character_name',
                    context_path=['define:character'],
                    character='',
                    file_path=str(file_path),
                )
                if entry:
                    entries.append(entry)
                    seen_texts.add(text)
        except Exception:
            self.logger.warning("Failed to process entry for text=%r", text)

        return entries

    def _process_secondary_extraction(
        self,
        match,
        text_type: str,
        raw_line: str,
        idx: int,
        lines: List[str],
        stripped_line: str,
        current_path: List[str],
        seen_texts: Set[Tuple],
        entries: List[Dict[str, Any]],
        file_path: Union[str, Path],
    ) -> None:
        """
        Helper method for secondary extraction passes (v2.6.6).
        Eliminates code duplication across show_text, window_text, hidden_arg, and triple_underscore passes.
        
        Features:
        - Exception handling for robustness
        - Early exit on empty/invalid text
        - Deduplication with seen_texts set
        - Optimized logging with level check
        """
        try:
            quote_raw = match.group('quote')
            raw, text = self._extract_string_raw_and_unescaped(quote_raw, start_line=idx, lines=lines)
            
            # Let _record_entry apply the full context-aware filter chain.
            if not text:
                return
            
            # Deduplication key: (text, character, context_path)
            key = (text, EMPTY_CHARACTER, tuple(current_path) if current_path else ())
            
            if key in seen_texts:
                return
            
            entry = self._record_entry(
                text=text,
                raw_text=raw,
                line_number=idx + 1,
                context_line=stripped_line,
                text_type=text_type,
                context_path=list(current_path) if current_path else [],
                character=EMPTY_CHARACTER,
                file_path=str(file_path),
            )
            
            if entry:
                entries.append(entry)
                seen_texts.add(key)
                # Optimized logging: Only format string if logging is enabled
                if self.logger.isEnabledFor(logging.INFO):
                    self.logger.info(f"[ENTRY+{text_type.upper()}] {file_path}:{idx+1} [{text_type}] text={text}")
                    
        except (ValueError, IndexError, UnicodeDecodeError, AttributeError) as e:
            # Log extraction error but continue processing
            if self.logger.isEnabledFor(logging.WARNING):
                self.logger.warning(f"Secondary extraction failed at {file_path}:{idx+1} [{text_type}]: {e}")
        except Exception as e:
            # Catch-all for unexpected errors
            if self.logger.isEnabledFor(logging.ERROR):
                self.logger.error(f"Unexpected error in secondary extraction at {file_path}:{idx+1}: {e}")

    def _record_secondary_text_candidate(
        self,
        *,
        text: str,
        raw_text: Optional[str],
        text_type: str,
        idx: int,
        stripped_line: str,
        current_path: List[str],
        seen_texts: Set[Tuple],
        entries: List[Dict[str, Any]],
        file_path: Union[str, Path],
        log_label: str,
    ) -> None:
        """Record a secondary extraction candidate using the normal filter chain."""
        if not text:
            return

        key = (text, EMPTY_CHARACTER, tuple(current_path) if current_path else ())
        if key in seen_texts:
            return

        entry = self._record_entry(
            text=text,
            raw_text=raw_text,
            line_number=idx + 1,
            context_line=stripped_line,
            text_type=text_type,
            context_path=list(current_path) if current_path else [],
            character=EMPTY_CHARACTER,
            file_path=str(file_path),
        )
        if not entry:
            return

        entries.append(entry)
        seen_texts.add(key)
        if self.logger.isEnabledFor(logging.INFO):
            self.logger.info(f"[ENTRY+{log_label}] {file_path}:{idx+1} [{text_type}] text={text}")

    def _find_matching_bracket_end(
        self,
        text: str,
        open_char: str = '(',
        close_char: str = ')',
    ) -> int:
        """Return the index of the matching closing bracket, ignoring quoted strings."""
        depth = 0
        in_string = False
        string_char = ''
        triple_quote = False
        escaped = False
        saw_open = False
        idx = 0

        while idx < len(text):
            ch = text[idx]

            if escaped:
                escaped = False
                idx += 1
                continue

            if ch == '\\':
                escaped = True
                idx += 1
                continue

            if in_string:
                if triple_quote:
                    if (
                        ch == string_char
                        and idx + 2 < len(text)
                        and text[idx + 1] == string_char
                        and text[idx + 2] == string_char
                    ):
                        in_string = False
                        triple_quote = False
                        idx += 3
                        continue
                elif ch == string_char:
                    in_string = False
                idx += 1
                continue

            if ch in ('"', "'"):
                if idx + 2 < len(text) and text[idx + 1] == ch and text[idx + 2] == ch:
                    in_string = True
                    string_char = ch
                    triple_quote = True
                    idx += 3
                    continue
                in_string = True
                string_char = ch
                idx += 1
                continue

            if ch == open_char:
                saw_open = True
                depth += 1
            elif ch == close_char and saw_open:
                depth -= 1
                if depth == 0:
                    return idx

            idx += 1

        return -1

    def _collect_parenthesized_expression(
        self,
        lines: List[str],
        start_idx: int,
        start_col: int,
    ) -> Tuple[str, int]:
        """Collect a possibly multi-line parenthesized expression starting at start_col."""
        collected = ""
        for line_idx in range(start_idx, len(lines)):
            chunk = lines[line_idx][start_col:] if line_idx == start_idx else lines[line_idx]
            collected += chunk
            end_idx = self._find_matching_bracket_end(collected, '(', ')')
            if end_idx != -1:
                return collected[:end_idx + 1], line_idx
        return collected, len(lines) - 1

    def _find_balanced_markup_end(self, text: str, start: int, close_char: str) -> int:
        """Return the index of the matching closing markup delimiter.

        This is a lightweight structural scan used for Ren'Py tags and
        interpolation placeholders. It intentionally avoids regex as the
        primary decision mechanism.
        """
        if start >= len(text):
            return -1

        depth = 1
        in_single_quote = False
        in_double_quote = False
        i = start

        while i < len(text):
            char = text[i]
            if char == '\\' and i + 1 < len(text):
                i += 2
                continue

            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
            elif char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
            elif not in_single_quote and not in_double_quote:
                if close_char == '}' and char == '{':
                    depth += 1
                elif close_char == ']' and char == '[':
                    depth += 1
                elif char == close_char:
                    depth -= 1
                    if depth == 0:
                        return i

            i += 1

        return -1

    def _strip_markup_structurally(self, text: str) -> str:
        """Remove Ren'Py markup while preserving visible text.

        Tags like ``{color=...}``, ``{/w}``, and interpolation placeholders like
        ``[name]`` are stripped, but visible text between them is retained.
        """
        if not text:
            return ""

        output: List[str] = []
        i = 0
        while i < len(text):
            char = text[i]

            if char == '\\' and i + 1 < len(text):
                output.append(text[i:i + 2])
                i += 2
                continue

            if char in ('{', '['):
                close_char = '}' if char == '{' else ']'
                end_idx = self._find_balanced_markup_end(text, i + 1, close_char)
                if end_idx != -1:
                    candidate = text[i:end_idx + 1]
                    # Disambiguation tags and placeholders are removed structurally.
                    i = end_idx + 1
                    continue

            output.append(char)
            i += 1

        return ''.join(output).strip()

    def _normalize_inline_text_candidate(self, text: str) -> str:
        """Strip Ren'Py markup using structural scanning first."""
        normalized = self._strip_markup_structurally(text or '')
        if normalized:
            return normalized
        return re.sub(r'\{/?[^}]*\}|\[[^\]]*\]', '', text or '').strip()

    def _looks_like_user_facing_label(self, text: str) -> bool:
        """Conservative label detector for short UI strings and screen titles."""
        normalized = self._normalize_inline_text_candidate(text)
        if not normalized:
            return False
        if sum(1 for ch in normalized if ch.isalpha()) < 2:
            return False

        words = [part for part in re.split(r'\s+', normalized) if part]
        if len(words) >= 2:
            return True

        first_alpha = next((ch for ch in normalized if ch.isalpha()), '')
        if not first_alpha:
            return False
        return first_alpha.isupper() or normalized.isupper()

    def _is_expression_text_candidate(self, text: str, mode: str) -> bool:
        """Apply conservative filters for supplemental expression-based extraction."""
        normalized = self._normalize_inline_text_candidate(text)
        if not normalized:
            return False
        if self._deep_var_analyzer.is_technical_string(normalized):
            return False

        if mode == 'screen_call':
            return self.is_meaningful_text(text) and self._looks_like_user_facing_label(text)
        if mode == 'displayable_call':
            return self._looks_like_user_facing_label(text)
        return self.is_meaningful_text(text)

    def _extract_expression_text_candidates(
        self,
        expression_source: str,
        *,
        mode: str,
    ) -> List[Tuple[Optional[str], str]]:
        """Extract literal/f-string text candidates from a Python expression source."""
        try:
            tree = ast.parse(expression_source, mode='eval')
        except SyntaxError:
            return []

        candidates: List[Tuple[Optional[str], str]] = []
        seen_local: Set[Tuple[Optional[str], str]] = set()
        for node in ast.walk(tree):
            raw_segment = ast.get_source_segment(expression_source, node)
            text = None

            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value
            elif isinstance(node, ast.JoinedStr) and self._is_deep_feature_enabled('deep_extraction_fstrings'):
                text = FStringReconstructor.extract_from_ast_node(node, expression_source)

            if not text or not self._is_expression_text_candidate(text, mode):
                continue

            key = (raw_segment, text)
            if key in seen_local:
                continue
            seen_local.add(key)
            candidates.append((raw_segment, text))

        return candidates

    def extract_from_json(self, file_path: Path) -> List[Dict[str, Any]]:
        """
        Extract translatable strings from a JSON file.
        """
        entries = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            def recurse(obj, path, current_key):
                if isinstance(obj, str):
                    # Tighten JSON filters and include raw_text for ID stability
                    import re
                    if not self._is_meaningful_data_value(obj, current_key):
                        return
                    raw_text = '"' + (obj.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')) + '"'
                    entries.append({
                        'text': obj,
                        'raw_text': raw_text,
                        'line_number': 0,
                        'context_line': f"json:{path}",
                        'text_type': 'string',
                        'file_path': str(file_path)
                    })
                elif isinstance(obj, dict):
                    for k, v in obj.items():
                        recurse(v, f"{path}.{k}" if path else k, k)
                elif isinstance(obj, list):
                    for i, v in enumerate(obj):
                        recurse(v, f"{path}[{i}]", current_key)

            recurse(data, "", None)
        except Exception as e:
            self.logger.error(f"JSON parsing error {file_path}: {e}")
        return entries

    def extract_from_yaml(self, file_path: Path) -> List[Dict[str, Any]]:
        """
        Extract translatable strings from a YAML file.
        """
        entries = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            def recurse(obj, path, current_key):
                if isinstance(obj, str):
                    if self.is_meaningful_text(obj):
                        entries.append({
                            'text': obj,
                            'line_number': 0,
                            'context_line': f"yaml:{path}",
                            'text_type': 'string',
                            'file_path': str(file_path)
                        })
                elif isinstance(obj, dict):
                    for k, v in obj.items():
                        recurse(v, f"{path}.{k}" if path else k, k)
                elif isinstance(obj, list):
                    for i, v in enumerate(obj):
                        recurse(v, f"{path}[{i}]", current_key)

            recurse(data, "", None)
        except Exception as e:
            self.logger.error(f"YAML parsing error {file_path}: {e}")
        return entries

    def extract_from_ini(self, file_path: Path) -> List[Dict[str, Any]]:
        """
        Extract translatable strings from an INI file.
        """
        entries = []
        try:
            config = configparser.ConfigParser()
            config.read(file_path, encoding='utf-8')

            for section in config.sections():
                for key, value in config.items(section):
                    if self._is_meaningful_data_value(value, key):
                        entries.append({
                            'text': value,
                            'line_number': 0,
                            'context_line': f"ini:[{section}]{key}",
                            'text_type': 'string',
                            'file_path': str(file_path)
                        })
        except Exception as e:
            self.logger.error(f"INI parsing error {file_path}: {e}")
        return entries

    def extract_from_xml(self, file_path: Path) -> List[Dict[str, Any]]:
        """
        Extract translatable strings from an XML file.
        """
        entries = []
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()

            def recurse_xml(node, path):
                # Check text content inside the tag
                if node.text and self._is_meaningful_data_value(node.text, node.tag):
                    entries.append({
                        'text': node.text,
                        'line_number': 0,
                        'context_line': f"xml:{path}",
                        'text_type': 'string',
                        'file_path': str(file_path)
                    })

                # Check tail text (text after the tag but before the next tag)
                if node.tail and self._is_meaningful_data_value(node.tail, node.tag):
                    entries.append({
                        'text': node.tail,
                        'line_number': 0,
                        'context_line': f"xml:{path}_tail",
                        'text_type': 'string',
                        'file_path': str(file_path)
                    })

                for child in node:
                    recurse_xml(child, f"{path}/{child.tag}")

            recurse_xml(root, root.tag)
        except Exception as e:
            self.logger.error(f"XML parsing error {file_path}: {e}")
        return entries

    def parse_directory(
        self,
        directory: Union[str, Path],
        include_deep_scan: bool = True,
        recursive: bool = True,
        progress_callback: Optional[Callable[[int, int, Path], None]] = None,
    ) -> Dict[Path, List[Dict[str, Any]]]:
        """
        Parse a directory for translatable strings, restricted to Ren'Py files only.
        """
        directory = Path(directory)
        search_root = self._resolve_search_root(directory)
        results: Dict[Path, List[Dict[str, Any]]] = {}

        def _in_tl_folder(path: Path) -> bool:
            try:
                rel = str(path.relative_to(search_root)).replace('\\', '/').lower()
                return rel.startswith('tl/') or '/tl/' in rel
            except Exception:
                return False

        # Determine extensions based on settings
        should_scan_rpym = False
        if self.config and hasattr(self.config, 'translation_settings'):
            should_scan_rpym = getattr(self.config.translation_settings, 'scan_rpym_files', False)

        if should_scan_rpym:
            extensions = ["**/*.rpy", "**/*.rpym"] # Exclude .rpyc/.rpymc from text parser
        else:
            extensions = ["**/*.rpy"] # Exclude .rpyc from text parser
        files: List[Path] = []
        for ext in extensions:
            files.extend(list(search_root.glob(ext)))

        processable_files = [
            file_path
            for file_path in files
            if not _in_tl_folder(file_path) and not self._is_excluded_rpy(file_path, search_root)
        ]

        total_files = len(processable_files)
        for i, file_path in enumerate(processable_files):
            if progress_callback is not None:
                progress_callback(i + 1, total_files, file_path)
            results[file_path] = self.extract_text_entries(file_path)

            # Yield GIL every 5 files to keep UI responsive during large scans
            if i % 5 == 0:
                time.sleep(0.001)

        return results

    async def extract_from_directory_async(
        self,
        directory: Union[str, Path],
        recursive: bool = True,
        max_workers: int = 4,
    ) -> Dict[Path, Set[str]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.extract_from_directory_parallel(
                directory,
                recursive=recursive,
                max_workers=max_workers,
            ),
        )

    def extract_from_directory_parallel(
        self,
        directory: Union[str, Path],
        recursive: bool = True,
        max_workers: int = 4,
    ):
        directory = Path(directory)
        search_root = self._resolve_search_root(directory)
        results: Dict[Path, Set[str]] = {}
        if recursive:
            iterator = list(search_root.glob("**/*.rpy")) + list(search_root.glob("**/*.RPY"))
        else:
            iterator = list(search_root.glob("*.rpy")) + list(search_root.glob("*.RPY"))
        rpy_files = [f for f in iterator if not self._is_excluded_rpy(f, search_root)]

        self.logger.info(
            "Found %s .rpy files for parallel processing (excluding Ren'Py engine & tl folders)",
            len(rpy_files),
        )

        for rpy_file in rpy_files:
            try:
                results[rpy_file] = self.extract_translatable_text(rpy_file)
            except Exception as exc:
                self.logger.error("Error processing file %s: %s", rpy_file, exc)
                results[rpy_file] = set()

        total_texts = sum(len(texts) for texts in results.values())
        self.logger.info(
            "Parallel processing completed: %s files, %s total texts",
            len(results),
            total_texts,
        )
        return results

    def extract_from_directory(self, directory: Union[str, Path], recursive: bool = True) -> Dict[Path, Set[str]]:
        """
        Sequential directory extraction for backwards compatibility with tests.
        """
        directory = Path(directory)
        search_root = self._resolve_search_root(directory)
        results: Dict[Path, Set[str]] = {}
        if recursive:
            iterator = list(search_root.glob("**/*.rpy")) + list(search_root.glob("**/*.RPY"))
        else:
            iterator = list(search_root.glob("*.rpy")) + list(search_root.glob("*.RPY"))
        rpy_files = [f for f in iterator if not self._is_excluded_rpy(f, search_root)]

        for rpy_file in rpy_files:
            try:
                results[rpy_file] = self.extract_translatable_text(rpy_file)
            except Exception as exc:
                self.logger.error("Error processing file %s: %s", rpy_file, exc)
                results[rpy_file] = set()

        return results

    def _resolve_search_root(self, directory: Path) -> Path:
        """
        Prioritize 'game' folder if it exists within the selected directory.
        Ren'Py games store their translatable assets strictly in 'game/'.
        """
        game_folder = directory / "game"
        if game_folder.exists() and game_folder.is_dir():
            self.logger.info(f"Targeting 'game' folder within selected directory: {game_folder}")
            return game_folder
        
        # Linux fallback for Game/ folder
        game_folder_alt = directory / "Game"
        if game_folder_alt.exists() and game_folder_alt.is_dir():
            self.logger.info(f"Targeting 'Game' folder within selected directory: {game_folder_alt}")
            return game_folder_alt
        return directory

    def _is_excluded_rpy(self, file_path: Path, search_root: Path) -> bool:
        """
        Determines if an .rpy file should be excluded from processing.
        Excludes system folders (cache, renpy, saves, etc.) and translation folders (tl).
        """
        # Normalize path to lowercase with forward slashes for cross-platform matching
        rel_str = str(file_path.relative_to(search_root)).replace('\\', '/').lower()
        full_str = str(file_path).replace('\\', '/').lower()

        # SUPER EXCLUSION: Never, ever scan internal engine files
        # These are ALWAYS skipped regardless of settings to prevent game crashes.
        engine_markers = ['/renpy/common/', '/renpy/display/', '/renpy/library/']
        if any(marker in full_str or rel_str.startswith('renpy/') for marker in engine_markers):
            return True

        # Check for system folder exclusion setting
        should_exclude_system = True
        if self.config and hasattr(self.config, 'translation_settings'):
            should_exclude_system = getattr(self.config.translation_settings, 'exclude_system_folders', True)

        if should_exclude_system:
            # Exclude technical/system folders
            excluded_folders = {
                'cache/', 'tmp/', 'saves/', 'python-packages/', 'lib/', 'log/', 'logs/',
                '.git/', '.vscode/', '.idea/'
            }
            
            if any(rel_str.startswith(folder) or f'/{folder}' in rel_str for folder in excluded_folders):
                return True
        
        # TL folders are always skipped as we are scanning for SOURCE files to generate NEW tl files
        if rel_str.startswith('tl/') or '/tl/' in rel_str:
            return True

        # Exclude specific technical extensions that might be caught by glob
        if file_path.suffix.lower() == '.rpyb':
            return True

        return False

    def _is_in_manual_exclude_dirs(
        self,
        file_path: Path,
        search_root: Path,
        exclude_dirs: Optional[List[str]] = None,
    ) -> bool:
        """Return whether the file is inside one of the manually excluded root dirs."""
        if not exclude_dirs:
            return False

        normalized_excludes = {
            str(item).replace("\\", "/").strip("/").lower()
            for item in exclude_dirs
            if str(item).strip()
        }
        if not normalized_excludes:
            return False

        try:
            rel_parts = [part.lower() for part in file_path.relative_to(search_root).parts[:-1]]
        except Exception:
            return False

        if not rel_parts:
            return False

        return rel_parts[0] in normalized_excludes

    def _read_file_lines(self, file_path: Union[str, Path]) -> List[str]:
        text = read_text_safely(Path(file_path))
        if text is None:
            raise IOError(f"Cannot read file: {file_path}")
        return text.splitlines()

    def _calculate_indent(self, line: str) -> int:
        expanded = line.replace('\t', '    ')
        return len(expanded) - len(expanded.lstrip(' '))

    def _pop_contexts(self, stack: List[ContextNode], current_indent: int) -> None:
        while stack and current_indent <= stack[-1].indent:
            stack.pop()

    def _detect_new_context(self, stripped_line: str, indent: int) -> Optional[ContextNode]:
        # Check for hidden labels first - these should be skipped for translation
        if self.hidden_label_re.match(stripped_line):
            return ContextNode(indent=indent, kind='hidden_label', name='hidden')
        
        label_match = self.label_def_re.match(stripped_line)
        if label_match:
            return ContextNode(indent=indent, kind='label', name=label_match.group(1))

        menu_match = self.menu_def_re.match(stripped_line)
        if menu_match:
            menu_name = menu_match.group(1) or menu_match.group(2) or ''
            return ContextNode(indent=indent, kind='menu', name=menu_name)

        screen_match = self.screen_def_re.match(stripped_line)
        if screen_match:
            return ContextNode(indent=indent, kind='screen', name=screen_match.group(1))
        if self.python_block_re.match(stripped_line):
            return ContextNode(indent=indent, kind='python')

        return None

    def _context_label(self, node: ContextNode) -> str:
        return f"{node.kind}:{node.name}" if node.name else node.kind

    def _build_context_path(
        self, stack: List[ContextNode], pending: Optional[ContextNode] = None
    ) -> List[str]:
        path = [self._context_label(node) for node in stack]
        if pending:
            path.append(self._context_label(pending))
        return path

    def _handle_multiline_start(
        self,
        lines: List[str],
        index: int,
        raw_line: str,
        stripped_line: str,
        context_path: List[str],
        file_path: str = '',
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        for descriptor in self.multiline_registry:
            match = descriptor['regex'].match(raw_line)
            if not match:
                continue

            delimiter = match.group('delim')
            body = match.groupdict().get('body') or ''
            
            # Special handling for _p() - need to consume until closing ) 
            is_p_function = descriptor.get('type') == 'paragraph'
            text, end_index = self._consume_multiline(
                lines, index, delimiter, body, 
                is_p_function=is_p_function
            )

            character = ''
            char_group = descriptor.get('character_group')
            if char_group and match.groupdict().get(char_group):
                character = match.group(char_group)
                if character and len(character) >= 2 and character[0] == character[-1] and character[0] in ('"', "'"):
                    character = character[1:-1]

            entry = self._record_entry(
                text=text,
                line_number=index + 1,
                context_line=stripped_line,
                text_type=descriptor.get('type', 'dialogue'),
                context_path=context_path,
                character=character,
                file_path=file_path,
                raw_text='\n'.join(lines[index:end_index+1]) if end_index >= index else None,
            )
            return entry, end_index

        return None, index

    def _consume_multiline(
        self,
        lines: List[str],
        start_index: int,
        delimiter: str,
        initial_body: str,
        is_p_function: bool = False,
    ) -> Tuple[str, int]:
        buffer: List[str] = []
        remainder = initial_body or ''
        closing_inline = remainder.find(delimiter)
        if closing_inline != -1:
            content = remainder[:closing_inline]
            if is_p_function:
                # For _p(), process the text to normalize whitespace
                content = self._process_p_function_text(content)
            buffer.append(content)
            return "\n".join(buffer).strip('\n'), start_index

        if remainder:
            buffer.append(remainder)

        index = start_index + 1
        while index < len(lines):
            current = lines[index]
            closing_pos = current.find(delimiter)
            if closing_pos != -1:
                buffer.append(current[:closing_pos])
                # Don't include tail for _p() function text
                if not is_p_function:
                    tail = current[closing_pos + len(delimiter) :].strip()
                    # Remove trailing ) for _p() functions  
                    if tail and not tail.startswith(')'):
                        buffer.append(tail)
                
                result_text = "\n".join(buffer).strip('\n')
                if is_p_function:
                    result_text = self._process_p_function_text(result_text)
                return result_text, index

            buffer.append(current)
            index += 1

        result_text = "\n".join(buffer).strip('\n')
        if is_p_function:
            result_text = self._process_p_function_text(result_text)
        return result_text, len(lines) - 1
    
    def _process_p_function_text(self, text: str) -> str:
        """
        Process _p() function text the same way Ren'Py does:
        - Remove leading/trailing whitespace from each line
        - Collapse consecutive non-blank lines into one line (with space)
        - Blank lines become paragraph separators (double newline)
        """
        if not text:
            return ""
        
        lines = text.split('\n')
        paragraphs = []
        current_paragraph = []
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                # Blank line = paragraph separator
                if current_paragraph:
                    paragraphs.append(' '.join(current_paragraph))
                    current_paragraph = []
            else:
                current_paragraph.append(stripped)
        
        # Don't forget the last paragraph
        if current_paragraph:
            paragraphs.append(' '.join(current_paragraph))
        
        # Join paragraphs with double newline (Ren'Py format)
        return '\n\n'.join(paragraphs)

    def _record_entry(
        self,
        text: str,
        line_number: int,
        context_line: str,
        text_type: str,
        context_path: List[str],
        character: str = '',
        file_path: str = '',
        raw_text: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not text:
            return None

        visible_text = self._normalize_inline_text_candidate(text)
        analysis_text = text
        if visible_text and visible_text != text:
            # Tag-heavy strings should be judged by the visible text first.
            # Keep the original markup for output, but use the cleaned form for gating.
            analysis_text = visible_text
        
        resolved_type = text_type or self.determine_text_type(
            analysis_text,
            context_line,
            context_path,
        )
        if self._is_python_context(context_path):
            resolved_type = 'renpy_func'

        # Set state for context-aware filtering used in following checks
        self._current_context_line = context_line or ""
        
        if not self._is_force_translatable_text(
            text=analysis_text,
            resolved_type=resolved_type,
            context_line=context_line,
            context_path=context_path,
        ) and not self.is_meaningful_text(analysis_text):
            return None
        
        # Skip text inside hidden labels (label xxx hide:)
        if self._is_hidden_context(context_path):
            return None

        processed_text, placeholder_map = self.preserve_placeholders(text)

        # For texts with disambiguation tags where meaningful content is very short,
        # strip {#...} tags before translation so the engine can translate the core text.
        # After translation, the disambiguation tag is restored from placeholder_map.
        _disambig_stripped_text = None
        if '{#' in text:
            _bare_text = re.sub(r'\{#[^}]+\}', '', text).strip()
            if _bare_text and _bare_text != text:
                _bare_placeholder_text, _bare_map = self.preserve_placeholders(_bare_text)
                _core_content = re.sub(r'⟦[^⟧]+⟧', '', _bare_placeholder_text).strip()
                if _core_content and len(_core_content) <= 4:
                    processed_text = _bare_placeholder_text
                    placeholder_map = _bare_map
                    _disambig_stripped_text = _bare_text

        # Context-based type correction: if context_path indicates screen/menu,
        # override generic types like 'dialogue' with the correct category.
        # This prevents screen/menu text from being misclassified as dialogue
        # when the regex pattern matched a generic string shape.
        if context_path and resolved_type in ('dialogue', 'narration', 'monologue', 'unknown', ''):
            lowered_ctx = [ctx.lower() for ctx in context_path if ctx]
            if any(ctx.startswith('screen') for ctx in lowered_ctx):
                resolved_type = 'ui'
            elif any(ctx.startswith('menu') for ctx in lowered_ctx):
                resolved_type = 'menu'

        # Apply user-configurable type filters (e.g. translate_ui)
        if not self._should_translate_text(text, resolved_type):
            return None

        confidence = score_extraction_confidence(
            analysis_text,
            resolved_type,
            context_line,
            context_path,
            character=character,
        )
        minimum_confidence = resolve_minimum_extraction_confidence(self.config, default=0.0)

        if confidence < minimum_confidence:
            # Keep high-confidence translated strings, but drop ambiguous candidates.
            return None

        # v2.8.3: Compute Ren'Py-compatible translation ID
        # Extract label context from context_path or use a sensible default
        label_context = context_path[0] if context_path else 'unknown'
        if label_context.lower() in ('screen', 'python', 'menu'):
            # For non-dialogue contexts, use a more descriptive label
            label_context = f"{label_context}_{line_number}"
        # Clamp context_line to avoid hashing accidentally large strings
        # (e.g. when grammar passes store the full file content as context_line).
        translation_id = self.compute_translation_id(label_context, context_line[:500] if context_line else context_line)

        # context_tag is handled by callers (e.g., deep scan) via context_path
        return {
            'text': text,
            'raw_text': raw_text if raw_text is not None else None,
            'line_number': line_number,
            'context_line': context_line,
            'character': character,
            'text_type': resolved_type,
            'context_path': list(context_path),
            'processed_text': processed_text,
            'placeholder_map': placeholder_map,
            'file_path': file_path,
            'confidence': confidence,
            'confidence_band': confidence_band(confidence),
            'translation_id': translation_id,  # v2.8.3: Ren'Py-compatible ID
            '_disambig_stripped_text': _disambig_stripped_text,
        }

    def _is_python_context(self, context_path: List[str]) -> bool:
        for ctx in context_path or []:
            ctx_lower = (ctx or '').lower()
            if ctx_lower.startswith('python'):
                return True
        return False

    def _is_standard_renpy_ui_text(self, text: str) -> bool:
        return text.strip() in STANDARD_RENPY_STRINGS

    def _is_force_translatable_text(
        self,
        *,
        text: str,
        resolved_type: str,
        context_line: str,
        context_path: List[str],
    ) -> bool:
        text_strip = text.strip()
        if not text_strip:
            return False

        if self._is_standard_renpy_ui_text(text_strip):
            return True

        if resolved_type == TextType.MENU_CHOICE and HOTKEY_SOURCE_RE.match(text_strip):
            lowered_line = (context_line or '').lower()
            if any(token in lowered_line for token in ('"option"', '"submenu"', '"exit"', '"button"')):
                return True

        if resolved_type != 'translatable_string':
            return False

        lowered_line = (context_line or '').lower()
        lowered_ctx = [(ctx or '').lower() for ctx in context_path or [] if ctx]
        in_ui_context = (
            any(ctx.startswith('screen') or ctx.startswith('menu') for ctx in lowered_ctx)
            or any(
                token in lowered_line
                for token in (
                    'textbutton',
                    'window title',
                    'button',
                    'tooltip',
                    'caption',
                    'prompt',
                    'quick_menu',
                )
            )
        )
        if not in_ui_context:
            return False

        return any(ch.isalpha() for ch in text_strip)
    
    def _is_hidden_context(self, context_path: List[str]) -> bool:
        """Check if we're inside a hidden label (should not be translated)"""
        for ctx in context_path or []:
            ctx_lower = (ctx or '').lower()
            if ctx_lower.startswith('hidden_label'):
                return True
        return False

    @staticmethod
    def _safe_unescape(s: str) -> str:
        """Safely unescape standard Ren'Py/Python string escapes without corrupting non-ASCII.
        
        Unlike codecs.decode('unicode_escape'), this handles only standard escapes
        (\\n, \\t, \\\", \\', \\\\) and preserves non-ASCII text (Cyrillic, CJK, Turkish, etc.)
        intact. Uses single-pass regex to avoid ordering issues with backslash sequences.
        """
        import re as _re
        _ESCAPE_MAP = {
            '\\n': '\n', '\\t': '\t', '\\\\': '\\',
            '\\"': '"', "\\\'" : "'",
            '\\r': '\r', '\\a': '\a', '\\b': '\b',
            '\\f': '\f', '\\v': '\v',
        }
        def _replace(m):
            return _ESCAPE_MAP.get(m.group(0), m.group(0))
        return _re.sub(r'\\[nt\\"\'\'rabfv]', _replace, s)

    def _extract_string_content(self, quoted_string: str) -> str:
        if not quoted_string:
            return ''
        import re
        
        # Match optional prefixes (r, u, b, f, fr, rf, etc.) and quoted content
        # Using a more robust regex for prefixes and various string types
        m = re.match(
            r"^(?P<prefix>[rRuUbBfF]{,2})"
            r"(?P<quoted>\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''|\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')\s*$",
            quoted_string, 
            flags=re.S
        )
        
        if not m:
            return quoted_string
            
        prefix = (m.group('prefix') or '').lower()
        content_raw = m.group('quoted')
        
        # Strip quotes based on type
        if content_raw.startswith(('"""', "'''")):
            content = content_raw[3:-3]
        else:
            content = content_raw[1:-1]
            
        # If it's a raw string (r or rf or rb), we don't process escapes (mostly)
        if 'r' in prefix:
            # Even in raw strings, Ren'Py/Python handles some sequences like \" or \' 
            # if they were used to escape the delimiter.
            if content_raw.startswith('"'):
                content = content.replace('\\"', '"')
            else:
                content = content.replace("\\'", "'")
            return content
            
        # Standard string unescaping
        # Handle common Ren'Py/Python escapes
        # We avoid using ast.literal_eval for safety and because we already have the stripped content
        # Safe unescape: handles \n, \t, \", \', \\ without corrupting non-ASCII
        # (unicode_escape codec destroys non-ASCII text encoded as UTF-8 multibyte)
        content = self._safe_unescape(content)
        return content

    def _extract_string_raw_and_unescaped(self, quoted_string: str, start_line: int = None, lines: List[str] = None) -> Tuple[str, str]:
        """
        Return both the raw literal (as in source, preserving escape sequences and quoting)
        and the unescaped content (normalized) used for IDs and matching.

        If `lines` and `start_line` are provided and the quoted string spans multiple
        lines (triple-quoted), this will capture the exact original lines slice for raw.
        """
        raw = quoted_string or ''
        # Attempt to capture multi-line raw from source lines if provided
        if lines is not None and start_line is not None:
            try:
                # start_line is 0-based index
                # Find the line that contains the opening quote
                for i in range(start_line, min(start_line + 1, len(lines))):
                    if quoted_string.strip().startswith(('"""', "'''")):
                        # For triple-quoted, try to find end by scanning forward
                        delim = quoted_string.strip()[:3]
                        # naive approach: join until we find closing delim
                        j = i
                        buf = []
                        while j < len(lines):
                            buf.append(lines[j])
                            if delim in lines[j] and j != i:
                                break
                            j += 1
                        raw = '\n'.join(buf)
                        break
            except Exception:
                raw = quoted_string

        # Use existing extractor to get unescaped
        unescaped = self._extract_string_content(quoted_string)
        return raw, unescaped

    def is_meaningful_text(self, text: str) -> bool:
        """
        Check if text is suitable for translation using heuristics and filters.
        """
        # Optimization: Prevent regex engine freeze (ReDoS) on massive strings
        if not text or len(text) > 4096:
            return False
        if self._is_standard_renpy_ui_text(text):
            return True
            
        # Crash Prevention: Reject file paths, URLs, and asset names immediately
        # Using structural markup stripping before fallback regex checks.
        # Fast path: skip markup stripping if no markup characters present
        if '{' in text or '[' in text:
            _text_no_tags = self._strip_markup_structurally(text)
            if not _text_no_tags:
                _text_no_tags = re.sub(r'\{/?[^}]*\}', '', text) if '{' in text else text
        else:
            _text_no_tags = text
        if any(ind in _text_no_tags for ind in self.path_indicators):
            return False
            
        text_lower = text.lower().strip()
            
        # Extension Check (Case-insensitive)
        if any(text_lower.endswith(ext) for ext in self.file_extensions):
            return False

        # Allow single-character UI text that is explicitly translatable (e.g. _("<"), _(">"))
        if len(text.strip()) < 2 and text.strip() not in '<>{}[]()^v↑↓←→':
            return False
        text_strip = text.strip()


        # Skip generated translation/TL snippets or fragments from .tl/.rpy translation blocks
        # e.g. lines starting with 'translate <lang>' or containing 'old'/'new' markers
        if '\n' in text:
            stripped = text.strip()
            if not stripped:
                return False
            first_line = stripped.splitlines()[0].lower()
            if first_line.startswith('translate '):
                return False
            tl_lower = text.lower()
            if 'translate ' in tl_lower or 'generated by renlocalizer' in tl_lower:
                return False
            if re.search(r'(^|\n)\s*(old|new)\b', tl_lower):
                return False
        # Skip very short fragments that are only 'old'/'new' markers
        if re.fullmatch(r"\s*(old|new)\s*", text_lower):
            return False
        
        if text_lower in self.renpy_technical_terms:
            return False
            
        # Reject audio commands wrapped in angle brackets (e.g., <silence 0.4>, <from 2.0>)
        if re.match(r'^\s*<[a-zA-Z0-9_.\s]+>\s*$', text_strip):
            return False

        # Reject internal Ren'Py names (starting with _) or internal files (starting with 00)
        if text_strip.startswith('_') and ' ' not in text_strip:
            return False
        if text_strip.startswith('00') and not any(ch.isalpha() for ch in text_strip[:5]):
            return False

        if self.technical_id_re.match(text_strip):
            return False

        # FIX v2.6.6: Improved placeholder detection
        # Old pattern rejected even non-technical text in brackets like "[Привет]"
        # New logic: Only reject technical placeholders, not user text
        if re.fullmatch(r"%s", text) or re.fullmatch(r"%\([^)]+\)[sdif]", text):
            # These are definitely Python format strings - reject them
            return False
        
        # For bracketed content, check if it's a technical placeholder
        bracket_match = re.fullmatch(r"\s*\[([^\]]+)\]\s*", text)
        if bracket_match:
            inner = bracket_match.group(1).strip()
            # ALWAYS reject if contains technical markers
            if any(c in inner for c in '._=' ) or any(c.isdigit() for c in inner):
                return False  # It's a technical placeholder
            # Multiple words likely technical (command.param, function args, etc)
            if len(inner.split()) > 1:
                return False
            # Single word: only reject if it looks like English variable/keyword
            # (not Cyrillic, CJK, or other user language text)
            if not re.search(r'[а-яА-ЯёЁ\u4e00-\u9fff\u3040-\u30ff\u0600-\u06ff]', inner):
                # No non-Latin script detected - likely technical English placeholder
                # Examples: [item], [player], [inventory] - common game variables
                return False
            # Has non-Latin script (Cyrillic, CJK, Arabic) - it's user text, not technical
            # Keep it for translation
        
        # For brace content (e.g., {color=...})
        brace_match = re.fullmatch(r"\s*\{([^}]+)\}\s*", text)
        if brace_match:
            inner = brace_match.group(1).strip()
            # If it contains = or other format markers, it's technical
            if '=' in inner or any(c in inner for c in '#:_'):
                return False  # It's a technical tag
        
        # Skip Python format strings like {:,}, {:3d}, {}, {}Attitude:{} {}, etc.
        # These are used for number/string formatting and should not be translated
        # v2.7.2: Distinguish Ren'Py display tags from Python format placeholders
        # Ren'Py tags: {color=#f00}, {b}, {/b}, {i}, {size=24}, {cps=20}, {w}, {p}, {nw}
        # Python fmt:  {}, {:3d}, {0}, {name}, {:,}
        if '{' in text_strip:
            # Count ONLY Python format placeholders (not Ren'Py display tags)
            all_braces = re.findall(r'\{([^}]*)\}', text_strip)
            py_format_count = 0
            for inner_brace in all_braces:
                stripped_inner = inner_brace.strip()
                # Ren'Py tags: start with letter or / (color, b, i, size, /color, /b etc.)
                if re.match(r'^/?[a-zA-Z]', stripped_inner):
                    continue  # It's a Ren'Py display tag, skip
                # Empty {} or format specs like :3d, :, etc. are Python format
                py_format_count += 1
            
            if py_format_count >= 1:
                # Remove ALL brace content and check remaining
                remaining = re.sub(r'\{[^}]*\}', '', text_strip).strip()
                has_cyrillic = bool(re.search(r'[а-яА-ЯёЁ]', remaining))
                min_len = 2 if has_cyrillic else 3
                if not any(ch.isalpha() for ch in remaining) or len(remaining) < min_len:
                    return False
                # If format placeholders dominate the string (2+ placeholders with short remaining), skip
                if py_format_count >= 2 and len(remaining) < 10:
                    return False

        # --- O(1) Optimization: Use Pre-compiled Regex ---
        if self.technical_re.search(text_lower):
             return False

        if any(ext in text_lower for ext in ['.png', '.jpg', '.mp3', '.ogg']):
            return False

        if re.match(r'^[-+]?\d+$', text.strip()):
            return False
        
        if re.search(r'\\x[0-9a-fA-F]{2}|(?:\(\?\:|\(\?P<|\[@-Z\\-_\]|\[0-\?\]\*|\[ -/\]\*|\[@-~\])', text):
             return False
        
        if len(text_strip) > 15:
            # FIX v2.7.1: Strip Ren'Py display tags before counting symbols
            # so that {b}, {/b}, {color=#f00}, [player] don't inflate the ratio.
            _stripped_for_sym = re.sub(r'\{/?[^}]*\}|\[[^\]]*\]', '', text_strip)
            symbol_count = len(re.findall(r'[\\#\[\](){}|*+?^$]', _stripped_for_sym))
            if symbol_count > len(_stripped_for_sym) * 0.25 if _stripped_for_sym else False:
                return False
        
        # --- NEW: Gibbberish / Binary / Encrypted String Detection ---
        # Strings like ">0ہWwLmw8g/τyMȫ9{h|f0`0Z" or binary junk found in .rpyc files
        if len(text_strip) > 8:
            # Check for the Unicode Replacement Character (U+FFFD) - definitive junk
            if '\ufffd' in text_strip:
                return False
                
            # Count "broken" or very unusual characters for a translation string
            # (Outside standard Latin, Cyrillic, CJK, and common punctuation)
            # Many obfuscated games use ranges that look like junk.
            # Updated to include:
            # - Latin Extended-A/B (Turkish, Viet, etc.): \u0100-\u024F
            # - Cyrillic Supplement: \u0400-\u052F
            # - General Punctuation (Em dash, quotes): \u2000-\u206F
            # - Arabic/Farsi: \u0600-\u06FF
            # - Hebrew: \u0590-\u05FF
            strange_chars = len(re.findall(r'[^\x20-\x7E\s\u00A0-\u024F\u0400-\u052F\u0590-\u05FF\u0600-\u06FF\u2000-\u206F\u4E00-\u9FFF\u3040-\u30FF\uAC00-\uD7AF]', text_strip))
            if strange_chars > len(text_strip) * 0.4:
                return False
            
            # Check ratio of letters to total length
            # Real sentences (even short ones) have high letter density.
            # Junk/Encrypted strings have lots of numbers/symbols/null-like chars.
            # FIX v2.7.1: Strip Ren'Py tags and interpolation brackets before counting
            # so that {cps=45}, {w}, [player_name] markup doesn't skew the ratio.
            _stripped_for_alpha = re.sub(r'\{/?[^}]*\}|\[[^\]]*\]', '', text_strip)
            alpha_count = sum(1 for ch in _stripped_for_alpha if ch.isalpha())
            _effective_len = len(_stripped_for_alpha) if _stripped_for_alpha else len(text_strip)
            if alpha_count < _effective_len * 0.2 and _effective_len > 10:
                return False
            # High unique character variety in non-alpha strings is a sign of entropy (encryption/junk)
            if alpha_count < _effective_len * 0.4:
                unique_chars = len(set(_stripped_for_alpha))
                if unique_chars > _effective_len * 0.7 and _effective_len > 8:
                    return False
        # -------------------------------------------------------------

        # FIX: Reject strings that are actually code wrappers captured by mistake
        # e.g. '_("Text")' or "_('Text')"
        if (text.startswith('_("') and text.endswith('")')) or \
           (text.startswith("_('") and text.endswith("')")):
            return False

        # --- NEW: Expression / Concatenation Detection ---
        # Strings like '"inventory/" + i.img' or '"part" + str(val)'
        # FIX: Ensure '+' is not just part of a Ren'Py tag (e.g., {size=+10})
        _no_tags_concat = re.sub(r'\{/?[^}]*\}', '', text_strip)
        if ('"' in text_strip or "'" in text_strip) and ('+' in _no_tags_concat or 'str(' in text_strip or 'int(' in text_strip):
            return False
            
        # Reject obvious function calls or code-like literals captured as strings
        # e.g. some_func(arg), module.attr, key: value
        if re.match(r'^[A-Za-z_]\w*\s*\(.*\)$', text_strip):
            return False
        if re.match(r'^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+$', text_strip): # Multiple dots (module.attr)
            return False
        if re.match(r'^[A-Za-z0-9_\-]+\s*:\s*[A-Za-z0-9_\-]+$', text_strip):
            return False
        if '=' in text_strip and not (text_strip.startswith('{') or '[' in text_strip):
            # Likely an assignment if it has '=' but no Ren'Py tags/interpolations nearby
            # Dialogue rarely has '=' unless it's a tag like {color=#f00}
            if not re.search(r'\{[^}]*=[^}]*\}', text_strip):
                return False
        
        # Docstring / Embedded Code detection: Reject strings containing Python code
        # These are often docstrings or code blocks captured by mistake from .rpyc files
        if '\n' in text_strip or len(text_strip) > 60:
            # Check for Python function/class definitions
            if re.search(r'\bdef\s+\w+\s*\(|\bclass\s+\w+', text_strip):
                return False
            # Check for common Python/Ren'Py code patterns
            # O(1) Optimization: Use Pre-compiled Regex
            if self.code_patterns_re.search(text_strip):
                 return False
            
            # General tech word count
            tech_word_count = sum(1 for word in text_lower.split() if word in self.renpy_technical_terms)
            if tech_word_count >= 2 or 'python' in text_lower or 'return' in text_lower:
                return False

        # Remove placeholders/tags like [who.name] or {color=...} and check remaining content
        # BUT: Only apply this check if there's meaningful content after removal
        # If text is ONLY brackets with valid content inside (e.g., "[Привет]"), it should pass
        try:
            cleaned = re.sub(r'(\[[^\]]+\]|\{[^}]+\})', '', text_strip).strip()
            
            # If cleaned is empty, check if original text was ONLY brackets with content
            # In that case, it's already validated by earlier checks
            if not cleaned:
                # Original text is only brackets/braces - allow it if it passed earlier checks
                # (It would have failed earlier if it was a technical placeholder)
                pass
            else:
                # Text contains content after removing placeholders/tags
                # Ensure remaining content is meaningful
                alpha_count = sum(1 for ch in cleaned if ch.isalpha())
                # Russian "Я" (I), "Да" (Yes) are 1-2 chars.
                min_alpha = 1 if re.search(r'[а-яА-ЯёЁ]', cleaned) else 2
                # FIX v2.7.1: If original text contains Ren'Py interpolation [var],
                # the cleaned text may lose all alpha chars but the text is still
                # dialogue with runtime substitution (e.g. "......[name]?").
                # In this case, skip the strict alpha check — the punctuation
                # structure itself needs translation for some languages.
                has_renpy_interpolation = bool(re.search(r'\[[^\]]+\]', text_strip))
                if not has_renpy_interpolation and alpha_count < min_alpha:
                    # Allow single non-alpha UI text characters (e.g. _("<"), _(">"))
                    if len(text_strip) != 1 or text_strip not in '<>{}[]()^v↑↓←→':
                        return False
        except Exception:
            self.logger.debug("is_meaningful_text inner check failed")

        # ============================================================
        # V2.6.6: FALSE POSITIVE PREVENTION FOR NEW PATTERNS
        # ============================================================
        
        # 1. Reject single-word parameter names (screen parameters)
        # Example: "title", "message", "player_name" - these are variable names, not text
        # ALLOW: Multi-word strings or strings with spaces
        if len(text_strip.split()) == 1 and text_strip.replace('_', '').isalnum():
            # It's a valid identifier-like string (variable name) - likely a parameter, not text
            # BUT: Allow if it's a common translatable word (checked below)
            common_params = {
                'title', 'message', 'text', 'label', 'caption', 'tooltip',
                'header', 'footer', 'content', 'description', 'name', 'value',
                'prompt', 'placeholder', 'default', 'prefix', 'suffix', 'hint'
            }
            if text_strip.lower() in common_params and len(text_strip) < 15:
                # Single-word common parameter - likely a variable name
                return False
        
        # 2. Reject strings that are only interpolation placeholders
        # Example: "[mood!t]" without surrounding text
        # ALLOW: "I'm feeling [mood!t]." - has actual text
        if re.fullmatch(r'\s*\[\w+!t\]\s*', text_strip):
            return False
        
        # 3. Reject Text() constructor technical parameters
        # Example: "size=24", "color=#fff", "font=DejaVuSans.ttf"
        # ALLOW: Actual text content in Text()
        # FIX v2.7.1: Strip Ren'Py display tags first so {color=#f00}Text{/color} isn't rejected
        _no_tags_for_param = re.sub(r'\{/?[^}]*\}', '', text_strip) if '{' in text_strip else text_strip
        if '=' in _no_tags_for_param and re.search(r'\b(size|color|font|outlines|xalign|yalign|xpos|ypos|style|textalign)\s*=', _no_tags_for_param, re.IGNORECASE):
            return False
        
        # v2.7.2: Skip purely technical snake_case strings that are definitely IDs
        # e.g., "game_state", "player_name", "bg_forest" — always technical identifiers
        if text_strip.islower() and '_' in text_strip and ' ' not in text_strip:
            return False

        # 4. Reject NVL mode technical commands
        # Example: "clear", "show", "hide" when used alone
        nvl_commands = {'clear', 'show', 'hide', 'menu', 'nvl'}
        if text_strip.lower() in nvl_commands:
            return False

        return (any(ch.isalpha() for ch in text) or (text_strip in '<>{}[]()^v↑↓←→')) and len(text.strip()) >= 1

    def get_context_line(self) -> str:
        """Returns the current line being processed for context-aware filtering."""
        return self._current_context_line or ""

    def determine_text_type(
        self,
        text: str,
        context_line: str = '',
        context_path: Optional[List[str]] = None,
    ) -> str:
        if context_path:
            lowered = [ctx.lower() for ctx in context_path]
            if any(ctx.startswith('menu') for ctx in lowered):
                return 'menu'
            if any(ctx.startswith('screen') for ctx in lowered):
                return 'ui'
            if any(ctx.startswith('python') for ctx in lowered):
                return 'renpy_func'
            if any(ctx.startswith('label') for ctx in lowered):
                return 'dialogue'

        if context_line:
            lowered_line = context_line.lower()
            # Check for _p() function first (paragraph text)
            if '_p(' in lowered_line:
                return 'paragraph'
            # NEW: Check for action/function patterns
            if 'notify(' in lowered_line:
                return 'notify'
            if 'confirm(' in lowered_line:
                return 'confirm'
            if 'alt ' in lowered_line or 'alt=' in lowered_line:
                return 'alt_text'
            if 'input' in lowered_line and ('default' in lowered_line or 'prefix' in lowered_line or 'suffix' in lowered_line):
                return 'input'
            if 'textbutton' in lowered_line:
                return 'button'
            if 'menu' in lowered_line:
                return 'menu'
            if 'screen' in lowered_line:
                return 'ui'
            if 'config.' in lowered_line:
                return 'config'
            if 'gui.' in lowered_line:
                return 'gui'
            if 'style.' in lowered_line:
                return 'style'
            if 'renpy.' in lowered_line or ' notify(' in lowered_line or ' input(' in lowered_line:
                return 'renpy_func'
            # NVL mode check - nvl character prefix
            if 'nvl' in lowered_line:
                return 'dialogue'  # NVL dialogue is still dialogue

        return 'dialogue'

    def classify_text_type(self, line: str) -> str:
        """
        Satırın menü, ekran, karakter, teknik veya genel metin olup olmadığını hassas şekilde belirler.
        """
        if self.menu_def_re.match(line) or self.menu_choice_re.match(line) or self.menu_title_re.match(line):
            return "menu"
        if self.screen_def_re.match(line) or self.screen_text_re.match(line) or self.screen_multiline_re.match(line):
            return "screen"
        if self.char_dialog_re.match(line) or self.char_multiline_re.match(line):
            return "character"
        if self.technical_line_re.match(line) or self.numeric_or_path_re.match(line):
            return "technical"
        return "general"

    def quality_check(self, text: str) -> Dict[str, bool]:
        """
        Basit kalite kontrolü: anlamlılık, basit dilbilgisi işareti ve teknik uygunluk.
        """
        res = {'is_meaningful': False, 'has_grammar_error': False, 'is_technically_valid': True}
        if text and len(text.strip()) > 2 and not self.technical_line_re.match(text) and not self.numeric_or_path_re.match(text):
            res['is_meaningful'] = True
        # Basit grammar: ilk harf büyük ve noktalama içeriyorsa kabul et
        if text and (text[0].isupper() and any(p in text for p in ('.', '!', '?'))):
            res['has_grammar_error'] = False
        else:
            res['has_grammar_error'] = True
        if self.technical_line_re.match(text) or self.numeric_or_path_re.match(text):
            res['is_technically_valid'] = False
        return res

    def _should_translate_text(self, text: str, text_type: str) -> bool:
        if self.config is None:
            return True
        
        text_strip = text.strip()
        text_lower = text_strip.lower()
        
        # =================================================================
        # CRITICAL: Skip technical content that should NEVER be translated
        # These checks run BEFORE user settings to prevent breaking games
        # =================================================================
        
        # Skip empty or whitespace-only text
        if not text_strip:
            return False
        
        # Skip file paths and file names (fonts, images, audio, etc.)
        file_extensions = (
            '.otf', '.ttf', '.woff', '.woff2', '.eot',  # Fonts
            '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.ico', '.svg',  # Images
            '.mp3', '.ogg', '.wav', '.flac', '.aac', '.m4a', '.opus',  # Audio
            '.mp4', '.webm', '.avi', '.mkv', '.mov', '.ogv',  # Video
            '.rpy', '.rpyc', '.rpa', '.rpym', '.rpymc',  # Ren'Py files
            '.py', '.pyc', '.pyo',  # Python files
            '.json', '.txt', '.xml', '.csv', '.yaml', '.yml',  # Data files
            '.zip', '.rar', '.7z', '.tar', '.gz',  # Archives
        )
        if any(text_lower.endswith(ext) for ext in file_extensions):
            return False
        
        # Skip if text starts with common file path patterns
        if text_strip.startswith(('fonts/', 'images/', 'audio/', 'music/', 'sounds/', 
                                   'gui/', 'screens/', 'script/', 'game/', 'tl/')):
            return False
        
        # Skip paths with slashes that look like file paths (no spaces)
        if '/' in text_strip and ' ' not in text_strip:
            if re.match(r'^[a-zA-Z0-9_/.\-]+$', text_strip):
                return False
        
        # Skip backslash paths (Windows style)
        if '\\' in text_strip and ' ' not in text_strip:
            if re.match(r'^[a-zA-Z0-9_\\\.\-]+$', text_strip):
                return False
        
        # Skip URLs and URIs
        if re.match(r'^(https?://|ftp://|mailto:|file://|www\.)', text_lower):
            return False
        
        # Skip hex color codes
        if re.match(r'^#[0-9a-fA-F]{3,8}$', text_strip):
            return False
        
        # Skip pure numbers (including floats and negative)
        if re.match(r'^-?\d+\.?\d*$', text_strip):
            return False
        
        # Skip CSS/style-like values
        if re.match(r'^\d+(\.\d+)?(px|em|rem|%|pt|vh|vw)$', text_lower):
            return False
        
        # Skip Ren'Py screen/style element names (technical identifiers)
        # IMPORTANT: Only skip lowercase versions - "history" is technical, "History" is UI text
        renpy_technical_terms_lowercase = {
            # Screen elements & style identifiers (always lowercase in code)
            'say', 'window', 'namebox', 'choice', 'quick', 'navigation',
            'return_button', 'page_label', 'page_label_text', 'slot',
            'slot_time_text', 'slot_name_text', 'save_delete', 'pref',
            'radio', 'check', 'slider', 'tooltip_icon', 'tooltip_frame',
            'dismiss', 'history_name', 'color',  # Note: removed 'history', 'help' - these are valid UI labels
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
            # Common variable/config names (shouldn't be translated)
            'id', 'name', 'type', 'style', 'action', 'hovered', 'unhovered',
            'selected', 'insensitive', 'activate', 'alternate',
        }
        # Only skip if text is EXACTLY lowercase (technical) - not Title Case UI text
        # "history" -> skip, "History" -> translate
        if text_strip in renpy_technical_terms_lowercase:
            return False
        
        # Skip snake_case identifiers (like page_label_text, slot_time_text)
        if re.match(r'^[a-z][a-z0-9]*(_[a-z0-9]+)+$', text_strip):
            return False
        
        # Skip SCREAMING_SNAKE_CASE constants
        if re.match(r'^[A-Z][A-Z0-9]*(_[A-Z0-9]+)+$', text_strip):
            return False
        
        # Skip camelCase identifiers (likely variable names)
        if re.match(r'^[a-z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*$', text_strip) and ' ' not in text_strip:
            return False
        
        # Skip save/game identifiers like "GameName-1234567890"
        if re.match(r'^[A-Za-z_][A-Za-z0-9_]*-\d+$', text_strip):
            return False
        
        # Skip version strings like "v1.0.0" or "1.2.3"
        if re.match(r'^v?\d+\.\d+(\.\d+)?([a-z])?$', text_lower):
            return False
        
        # Single non-alpha character: only reject common bullet/separator characters,
        # allow bracket/paren/navigation chars that may be legitimate UI text (e.g. _("<"), _(">"))
        if len(text_strip) == 1 and not text_strip.isalpha():
            if text_strip in '•·–—‖|¦':
                return False
        
        # Skip if it's just Ren'Py tags/variables with no actual text
        # e.g., "{font=something}[variable]{/font}" with no human-readable text
        stripped_of_markup = self._strip_markup_structurally(text_strip)
        if not stripped_of_markup:
            stripped_of_markup = re.sub(r'\{[^}]*\}', '', text_strip)
            stripped_of_markup = re.sub(r'\[[^\]]*\]', '', stripped_of_markup)
        if not stripped_of_markup.strip():
            return False

        # =================================================================
        # User-configurable text type filters
        # =================================================================
        ts = self.config.translation_settings
        if text_type == 'dialogue' and not ts.translate_dialogue:
            return False
        if text_type == 'menu' and not ts.translate_menu:
            return False
        if text_type == 'ui' and not ts.translate_ui:
            return False
        if text_type in ('button', 'button_text') and not getattr(ts, 'translate_buttons', ts.translate_ui):
            return False
        if text_type == 'config' and not ts.translate_config_strings:
            return False
        if text_type == 'gui' and not ts.translate_gui_strings:
            return False
        if text_type == 'style' and not ts.translate_style_strings:
            return False
        if text_type == 'renpy_func' and not ts.translate_renpy_functions:
            return False
        # NEW text types
        if text_type == 'alt_text' and not getattr(ts, 'translate_alt_text', ts.translate_ui):
            return False
        if text_type == 'input' and not getattr(ts, 'translate_input_text', ts.translate_ui):
            return False
        if text_type == 'notify' and not getattr(ts, 'translate_notifications', ts.translate_dialogue):
            return False
        if text_type == 'confirm' and not getattr(ts, 'translate_confirmations', ts.translate_dialogue):
            return False
        if text_type == 'translatable_string':
            # _() marked strings should always be translated
            return True
        if text_type == 'define' and not getattr(ts, 'translate_define_strings', ts.translate_config_strings):
            return False
        # paragraph type always translatable (like dialogue)
        if text_type == 'paragraph':
            # Use same settings as dialogue
            if not ts.translate_dialogue:
                return False
        # NVL dialogue follows dialogue setting
        if text_type == 'nvl_dialogue' and not ts.translate_dialogue:
            return False
        # Screen text follows UI setting
        if text_type in ('screen_text', 'screen') and not ts.translate_ui:
            return False
        # Extend follows dialogue setting
        if text_type == 'extend' and not ts.translate_dialogue:
            return False
        # Data file strings follow config_strings setting
        if text_type == 'string' and not ts.translate_config_strings:
            return False
        # Character name definitions
        if text_type == 'character_name' and not getattr(ts, 'translate_character_names', ts.translate_dialogue):
            return False

        # ─── Pyparsing screen element types (tag name used as type) ───
        # 'text', 'label', 'viewport', 'vbox', 'hbox', etc. → UI elements
        _screen_element_types = {
            'text', 'label', 'viewport', 'vbox', 'hbox', 'frame',
            'window', 'timer', 'bar', 'vbar', 'side', 'grid',
            'text_displayable', 'show_text',
        }
        if text_type in _screen_element_types and not ts.translate_ui:
            return False
        # 'textbutton', 'imagebutton' → button elements
        if text_type in ('textbutton', 'imagebutton') and not getattr(ts, 'translate_buttons', ts.translate_ui):
            return False

        # ─── Pyparsing/grammar-assigned types ───
        # 'data_string' (generic string outside known patterns) → config strings  
        if text_type == 'data_string' and not ts.translate_config_strings:
            return False
        # 'narration', 'monologue' → dialogue
        if text_type in ('narration', 'monologue') and not ts.translate_dialogue:
            return False
        # 'menu_choice' → menu
        if text_type == 'menu_choice' and not ts.translate_menu:
            return False
        # 'python_translatable' → _() marked, always translated
        if text_type == 'python_translatable':
            return True
        # 'python_notify' → notifications
        if text_type == 'python_notify' and not getattr(ts, 'translate_notifications', ts.translate_dialogue):
            return False
        # 'python_input' → input text
        if text_type == 'python_input' and not getattr(ts, 'translate_input_text', ts.translate_ui):
            return False
        # 'define_text' (TextType.DEFINE_TEXT) → define strings
        if text_type == 'define_text' and not getattr(ts, 'translate_define_strings', ts.translate_config_strings):
            return False
        # 'config_text' → config strings
        if text_type == 'config_text' and not ts.translate_config_strings:
            return False
        # 'immediate_translation' → __("text"), always translated
        if text_type == 'immediate_translation':
            return True

        rules: Dict[str, Any] = getattr(self.config, 'never_translate_rules', {}) or {}

        try:
            for val in rules.get('exact', []) or []:
                if text_strip == val:
                    return False
            for val in rules.get('contains', []) or []:
                if val and val in text_strip:
                    return False
            for pattern in rules.get('regex', []) or []:
                try:
                    if re.search(pattern, text_strip):
                        return False
                except re.error:
                    continue
        except Exception as exc:
            self.logger.warning("never_translate rules failed: %s", exc)

        # Eğer metin 'jump', 'call', 'scene', 'show' bağlamında ise ve boşluk içermiyorsa -> ÇEVİRME
        if text_type in ('renpy_func', 'python_string'):
            context_lower = self.get_context_line().lower()  # Bağlam satırını al
            if any(keyword in context_lower for keyword in ('jump', 'call', 'scene', 'show')):
                if ' ' not in text_strip and text_strip[0].isupper():
                    # Örn: "Start", "Forest", "Date" gibi kelimeler label olabilir.
                    return False

        # Eğer metin 'font' veya 'style' bağlamında ise ve boşluk içermiyorsa -> ÇEVİRME
        if text_type in ('config', 'gui', 'style'):
            context_lower = self.get_context_line().lower()  # Bağlam satırını al
            if any(keyword in context_lower for keyword in ('font', 'style')):
                if ' ' not in text_strip:
                    # Örn: "Roboto-Regular", "GuiFont" gibi isimler çevrilmemeli.
                    return False

        return True

    def preserve_placeholders(self, text: str):
        """
        Replace Ren'Py variables, tags, and format strings with stable Unicode markers.
        Uses ⟦0000⟧ format which translation engines won't modify.
        
        Handles:
        - [variable] - Ren'Py variable interpolation
        - [var!t] - Translatable variable (special flag)
        - {tag} - Ren'Py text tags (color, bold, etc.)
        - {#identifier} - Disambiguation tags (MUST be preserved)
        - %(var)s, %s - Python format strings
        """
        if not text:
            return text, {}

        placeholder_map: Dict[str, str] = {}
        processed_text = text
        placeholder_counter = 0

        # CRITICAL: Preserve disambiguation tags {#...} FIRST
        # These are used to distinguish identical strings in different contexts
        # e.g., "New", "New{#project}", "New{#game}" are all different in Ren'Py
        disambiguation_pattern = r'\{#[^}]+\}'
        for match in re.finditer(disambiguation_pattern, text):
            placeholder_id = f"⟦D{placeholder_counter:03d}⟧"  # D for disambiguation
            placeholder_map[placeholder_id] = match.group(0)
            processed_text = processed_text.replace(match.group(0), placeholder_id, 1)
            placeholder_counter += 1

        # RenPy variable placeholders like [variable_name], [var!t] (translatable),
        # or complex expressions like [page['episode']], [var.attr], [func()]
        # The !t flag marks a variable as translatable - these are SPECIAL
        # [mood!t] - the value in 'mood' will be translated at display time
        # We need to preserve the whole placeholder but NOT translate the variable name
        # 
        # CRITICAL: Must handle nested brackets for dictionary access patterns:
        #   [page['episode']] - the inner ['episode'] must stay intact
        #   [comment['author']] - don't translate 'comment' to anything
        #
        # Strategy: Find [ then capture until we find a matching ] that's not inside quotes
        def find_bracket_content(text: str, start: int) -> Optional[Tuple[int, int]]:
            """Find matching closing bracket, handling nested quotes and brackets."""
            if start >= len(text) or text[start] != '[':
                return None
            
            depth = 1
            in_single_quote = False
            in_double_quote = False
            i = start + 1
            
            while i < len(text) and depth > 0:
                char = text[i]
                
                if char == '\\' and i + 1 < len(text):
                    i += 2  # Skip escape sequence
                    continue
                    
                if char == "'" and not in_double_quote:
                    in_single_quote = not in_single_quote
                elif char == '"' and not in_single_quote:
                    in_double_quote = not in_double_quote
                elif not in_single_quote and not in_double_quote:
                    if char == '[':
                        depth += 1
                    elif char == ']':
                        depth -= 1
                
                i += 1
            
            if depth == 0:
                return (start, i)
            return None
        
        # Find all top-level bracket expressions
        pos = 0
        bracket_matches = []
        while pos < len(processed_text):
            idx = processed_text.find('[', pos)
            if idx == -1:
                break
            
            # Skip if already processed (part of placeholder)
            if idx > 0 and processed_text[idx-1] == '⟦':
                pos = idx + 1
                continue
            
            result = find_bracket_content(processed_text, idx)
            if result:
                bracket_matches.append((result[0], result[1], processed_text[result[0]:result[1]]))
                pos = result[1]
            else:
                pos = idx + 1
        
        # Process matches in reverse order to preserve indices
        for start, end, match_text in reversed(bracket_matches):
            # Skip if already a placeholder
            if match_text.startswith('⟦'):
                continue
            
            var_content = match_text[1:-1]  # Remove outer [ ]
            
            # Check for !t flag (translatable variable)
            if '!t' in var_content:
                placeholder_id = f"⟦VT{placeholder_counter:03d}⟧"  # VT for translatable variable
            else:
                placeholder_id = f"⟦V{placeholder_counter:03d}⟧"  # V for regular variable
            
            placeholder_map[placeholder_id] = match_text
            processed_text = processed_text[:start] + placeholder_id + processed_text[end:]
            placeholder_counter += 1

        # RenPy text tags like {color=#ff0000}, {/color}, {b}, {/b}, etc.
        # BUT NOT disambiguation tags (already handled above)
        renpy_tag_pattern = r'\{[^}]*\}'
        for match in re.finditer(renpy_tag_pattern, processed_text):
            tag = match.group(0)
            if tag.startswith('⟦') or tag.startswith('{#'):  # Already processed or disambiguation
                continue
            placeholder_id = f"⟦T{placeholder_counter:03d}⟧"  # T for tag
            placeholder_map[placeholder_id] = tag
            processed_text = processed_text.replace(tag, placeholder_id, 1)
            placeholder_counter += 1

        # Python-style format strings like %(variable)s, %s, %d, etc.
        python_format_pattern = r'%\([^)]+\)[sdif]|%[sdif]'
        for match in re.finditer(python_format_pattern, processed_text):
            placeholder_id = f"⟦F{placeholder_counter:03d}⟧"  # F for format
            placeholder_map[placeholder_id] = match.group(0)
            processed_text = processed_text.replace(match.group(0), placeholder_id, 1)
            placeholder_counter += 1

        return processed_text, placeholder_map

    # Restore placeholders in translated text.
    # Uses Unicode bracket markers ⟦0000⟧ which are more resistant to translation corruption.
    def restore_placeholders(self, translated_text: str, placeholder_map: dict) -> str:
        """
        Restore placeholders in translated text.
        Uses Unicode bracket markers ⟦0000⟧ which are more resistant to translation corruption.
        """
        if not translated_text or not placeholder_map:
            return translated_text
        
        restored_text = translated_text
        
        # First try exact match - this handles most cases with Unicode markers
        for placeholder_id, original_placeholder in placeholder_map.items():
            restored_text = restored_text.replace(placeholder_id, original_placeholder)
        
        # Handle potential space insertions around Unicode markers
        for placeholder_id, original_placeholder in placeholder_map.items():
            if placeholder_id.startswith('⟦') and placeholder_id.endswith('⟧'):
                # Extract number part
                number_part = placeholder_id[1:-1]  # Get "0000" part
                
                # Try with spaces around the marker
                space_patterns = [
                    f"⟦ {number_part} ⟧",  # Spaces inside brackets
                    f"⟦ {number_part}⟧",    # Space after opening
                    f"⟦{number_part} ⟧",    # Space before closing
                    f" {placeholder_id} ",   # Spaces around
                    f" {placeholder_id}",    # Space before
                    f"{placeholder_id} ",    # Space after
                ]
                
                for pattern in space_patterns:
                    if pattern in restored_text:
                        restored_text = restored_text.replace(pattern, original_placeholder)
                
                # Regex fallback for Unicode markers with potential corruption
                import re
                unicode_patterns = [
                    r'⟦\s*' + re.escape(number_part) + r'\s*⟧',  # Flexible whitespace
                    r'\[\s*' + re.escape(number_part) + r'\s*\]',  # Similar brackets
                    r'【\s*' + re.escape(number_part) + r'\s*】',  # CJK brackets
                ]
                
                for pattern in unicode_patterns:
                    restored_text = re.sub(pattern, original_placeholder, restored_text)
        
        return restored_text

    def validate_placeholders(self, text: str, placeholder_map: dict) -> bool:
        """
        Validate that placeholders in the translated text match the original placeholders.
        Ensures that variables like [player_name] are preserved.
        
        Args:
            text: The translated text to validate.
            placeholder_map: The original placeholder map from preserve_placeholders.
        
        Returns:
            True if all placeholders are valid, False otherwise.
        """
        for placeholder_id, original_placeholder in placeholder_map.items():
            if placeholder_id not in text:
                self.logger.warning(f"Missing placeholder {placeholder_id} in text: {text}")
                return False
        return True

    # ========== DEEP STRING SCANNER ==========
    # Bu modül, normal pattern'lerin yakalayamadığı gizli metinleri bulur
    # init python bloklarındaki dictionary'ler, değişken atamaları vb.
    
    # ========== NEW: AST-BASED DEEP SCAN (v2.4.1, Enhanced v2.7.1) ==========
    
    def deep_scan_strings_ast(self, file_path: Union[str, Path]) -> List[Dict[str, Any]]:
        """
        Python AST kullanarak derin string taraması.
        Regex'in kaçırdığı nested structure'ları yakalar.
        
        v2.7.1 Enhancements:
        - Multi-line define/default structure parsing (dicts, lists)
        - Improved f-string extraction with FStringReconstructor
        - Extended API call detection via DeepExtractionConfig
        - Variable name heuristic filtering
        
        Args:
            file_path: Dosya yolu
            
        Returns:
            List of deep scan entries
        """
        import ast as python_ast
        
        try:
            lines = self._read_file_lines(file_path)
            content = '\n'.join(lines)
        except Exception as exc:
            self.logger.debug(f"AST deep scan read error: {exc}")
            return []
        
        entries: List[Dict[str, Any]] = []
        seen_texts: Set[str] = set()
        
        # Python bloklarını bul
        python_blocks = self._extract_python_blocks_for_ast(content, lines)
        
        for block_start, block_code in python_blocks:
            try:
                tree = python_ast.parse(block_code)
                
                # AST visitor ile string'leri çıkar
                def add_entry(text: str, lineno: int, text_type: str = 'deep_scan_ast'):
                    if text in seen_texts:
                        return
                    if len(text.strip()) < 3:
                        return
                    if not self.is_meaningful_text(text):
                        return
                    
                    # Filter technical strings using DeepVariableAnalyzer
                    if self._deep_var_analyzer.is_technical_string(text):
                        return

                    confidence = score_extraction_confidence(
                        text,
                        text_type,
                        lines[min(block_start + lineno - 1, len(lines) - 1)] if lines else '',
                        ['deep_scan_ast'],
                    )
                    if confidence < resolve_minimum_extraction_confidence(self.config, default=0.0):
                        return
                    
                    # NOTE: preserve_placeholders() is NOT called here.
                    # The translation pipeline applies protect_renpy_syntax()
                    # independently — calling it here would be wasted CPU.
                    entries.append({
                        'text': text,
                        'line_number': block_start + lineno,
                        'context_line': lines[min(block_start + lineno - 1, len(lines) - 1)] if lines else '',
                        'text_type': text_type,
                        'context_path': ['deep_scan_ast'],
                        'is_deep_scan': True,
                        'is_ast_scan': True,
                        'file_path': str(file_path),
                        'confidence': confidence,
                        'confidence_band': confidence_band(confidence),
                    })
                    seen_texts.add(text)
                
                # Visit all nodes
                for node in python_ast.walk(tree):
                    # String constants
                    if isinstance(node, python_ast.Constant) and isinstance(node.value, str):
                        add_entry(node.value, getattr(node, 'lineno', 1))
                    
                    # f-strings (JoinedStr) — Enhanced with FStringReconstructor
                    elif isinstance(node, python_ast.JoinedStr):
                        if self._is_deep_feature_enabled('deep_extraction_fstrings'):
                            template = FStringReconstructor.extract_from_ast_node(node, block_code)
                            if template:
                                add_entry(template, getattr(node, 'lineno', 1), 'deep_scan_fstring')
                    
                    # Call to _(), __(), or Tier-1 API calls
                    elif isinstance(node, python_ast.Call):
                        func = node.func
                        func_name = ''
                        if isinstance(func, python_ast.Name):
                            func_name = func.id
                        elif isinstance(func, python_ast.Attribute):
                            if isinstance(func.value, python_ast.Name):
                                func_name = f"{func.value.id}.{func.attr}"
                            else:
                                func_name = func.attr
                        
                        # Skip Tier-3 blacklisted calls
                        if func_name in DeepExtractionConfig.TIER3_BLACKLIST_CALLS:
                            continue
                        
                        if func_name in ('_', '__', 'renpy_say', 'notify'):
                            for arg in node.args:
                                if isinstance(arg, python_ast.Constant) and isinstance(arg.value, str):
                                    add_entry(arg.value, getattr(node, 'lineno', 1), 'translatable_call')
                        
                        # V2.7.1: Tier-1 API call extraction
                        # v2.7.1: Merged with user-defined custom_function_params
                        if self._is_deep_feature_enabled('deep_extraction_extended_api'):
                            if not hasattr(self, '_cached_merged_calls'):
                                self._cached_merged_calls = DeepExtractionConfig.get_merged_text_calls(self.config)
                            tier1_info = self._cached_merged_calls.get(func_name)
                            if tier1_info:
                                for pos_idx in tier1_info.get('pos', []):
                                    if len(node.args) > pos_idx:
                                        arg = node.args[pos_idx]
                                        if isinstance(arg, python_ast.Constant) and isinstance(arg.value, str):
                                            add_entry(arg.value, getattr(node, 'lineno', 1), 'api_call')
                                for kw_name in tier1_info.get('kw', []):
                                    for kw in node.keywords:
                                        if kw.arg == kw_name and isinstance(kw.value, python_ast.Constant) and isinstance(kw.value.value, str):
                                            add_entry(kw.value.value, getattr(node, 'lineno', 1), 'api_call')
                        
                            # V2.7.1: Tier-2 contextual calls
                            tier2_info = DeepExtractionConfig.TIER2_CONTEXTUAL_CALLS.get(func_name)
                            if tier2_info:
                                for pos_idx in tier2_info.get('pos', []):
                                    if len(node.args) > pos_idx:
                                        arg = node.args[pos_idx]
                                        if isinstance(arg, python_ast.Constant) and isinstance(arg.value, str):
                                            add_entry(arg.value, getattr(node, 'lineno', 1), 'api_call')
                                for kw_name in tier2_info.get('kw', []):
                                    for kw in node.keywords:
                                        if kw.arg == kw_name and isinstance(kw.value, python_ast.Constant) and isinstance(kw.value.value, str):
                                            add_entry(kw.value.value, getattr(node, 'lineno', 1), 'api_call')
                
            except SyntaxError:
                # Invalid Python, skip this block
                self.logger.debug("Syntax error in Python block, skipping: %s", line[:80])
            except Exception as exc:
                self.logger.debug(f"AST parse error in block: {exc}")
        
        # V2.7.1: Multi-line define/default structure extraction
        if self._is_deep_feature_enabled('deep_extraction_multiline_structures'):
            multiline_entries = self._extract_multiline_define_default(lines, file_path)
            for me in multiline_entries:
                if me.get('text') not in seen_texts:
                    entries.append(me)
                    seen_texts.add(me.get('text'))
        
        self.logger.info(f"AST deep scan found {len(entries)} strings in {file_path}")
        return entries
    
    def _extract_multiline_define_default(self, lines: List[str], file_path: Union[str, Path]) -> List[Dict[str, Any]]:
        """
        V2.7.1: Extract translatable strings from multi-line define/default structures.
        
        Handles:
            define quest_data = {
                "title": "Dragon Slayer",
                "desc": "Kill the mighty dragon",
            }
        """
        entries: List[Dict[str, Any]] = []
        idx = 0
        while idx < len(lines):
            line = lines[idx]
            info = MultiLineStructureParser.detect_multiline_start(line)
            if info:
                var_name = info['var_name']
                # Check if variable name suggests translatable content
                if not self._deep_var_analyzer.is_likely_translatable(var_name, threshold=0.35):
                    idx += 1
                    continue
                
                collected_code, end_idx = MultiLineStructureParser.collect_block(lines, idx, info)
                try:
                    results = MultiLineStructureParser.extract_translatable_values(
                        var_name, collected_code
                    )
                    for r in results:
                        text = r['text']
                        if text and self.is_meaningful_text(text):
                            entries.append({
                                'text': text,
                                'line_number': idx + 1 + r.get('lineno', 0),
                                'context_line': line.strip(),
                                'text_type': TextType.DEFINE_TEXT,
                                'context_path': [f"variable:{var_name}", r.get('context', '')],
                                'is_deep_scan': True,
                                'is_ast_scan': True,
                                'file_path': str(file_path),
                            })
                except Exception as exc:
                    self.logger.debug(f"Multi-line structure parse error at {file_path}:{idx+1}: {exc}")
                idx = end_idx + 1
            else:
                idx += 1
        return entries
    
    def _extract_python_blocks_for_ast(self, content: str, lines: List[str]) -> List[Tuple[int, str]]:
        """
        Python bloklarını AST parsing için çıkar.
        
        Returns:
            List of (start_line, code_block) tuples
        """
        blocks: List[Tuple[int, str]] = []
        
        # init python ve python bloklarını bul
        python_block_re = re.compile(r'^(\s*)(?:init\s+(?:[-+]?\d+\s+)?)?python\s*(?:\w+)?:', re.MULTILINE)
        
        in_block = False
        block_start = 0
        block_indent = 0
        block_lines: List[str] = []
        
        for idx, line in enumerate(lines):
            stripped = line.lstrip()
            current_indent = len(line) - len(stripped)
            
            if not in_block:
                # Check for python block start
                if stripped.startswith('python') or 'init python' in line.lower() or stripped.startswith('$ '):
                    if stripped.startswith('$ '):
                        # Single line python
                        code = stripped[2:].strip()
                        if code:
                            blocks.append((idx, code))
                    elif ':' in stripped:
                        in_block = True
                        block_start = idx
                        block_indent = current_indent
                        block_lines = []
            else:
                # Inside python block
                if stripped and current_indent <= block_indent and not stripped.startswith('#'):
                    # Block ended
                    if block_lines:
                        code = '\n'.join(block_lines)
                        blocks.append((block_start, code))
                    in_block = False
                    block_lines = []
                elif stripped or not block_lines:  # Include empty lines inside block
                    # Remove common indentation
                    if stripped:
                        block_lines.append(line[block_indent + 4:] if len(line) > block_indent + 4 else stripped)
        
        # Handle block at end of file
        if in_block and block_lines:
            code = '\n'.join(block_lines)
            blocks.append((block_start, code))
        
        return blocks
    
    # ========== END AST-BASED DEEP SCAN ==========

    
    def deep_scan_strings(
        self,
        file_path: Union[str, Path],
        normal_entries: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Dosyadaki TÜM string literal'leri tarar.
        Normal pattern'lerin kaçırdığı metinleri bulmak için kullanılır.

        Özellikle şunları yakalar:
        - init python bloklarındaki dictionary value'ları
        - $ ile başlayan satırlardaki string atamaları
        - List/tuple içindeki stringler
        - Fonksiyon argümanlarındaki stringler
        - Çok satırlı triple-quoted stringler

        Returns:
            List of entries with text, line_number, context info
        """
        try:
            lines = self._read_file_lines(file_path)
        except Exception as exc:
            self.logger.error("Deep scan error reading %s: %s", file_path, exc)
            return []
        
        entries: List[Dict[str, Any]] = []
        already_found: Set[Tuple[str,str]] = set()
        
        # Normal pattern'lerle bulunanları al (bunları atlamak için)
        normal_entries = normal_entries if normal_entries is not None else self.extract_text_entries(file_path)
        for entry in normal_entries:
            normalized = entry.get('processed_text') or entry.get('text')
            ctx = (entry.get('context_path') or ['deep_scan'])[0]
            already_found.add((normalized, ctx))
        
        # Tüm dosya içeriği (çok satırlı stringler için)
        full_content = '\n'.join(lines)

        # Performans: her karakter offsetinden satır numarasını O(1) ile bulmak için
        # satır başı offsetleri listesi oluştur (bisect ile binary search).
        import bisect as _bisect
        _line_offsets: List[int] = [0]
        for _ln, _lc in enumerate(lines):
            _line_offsets.append(_line_offsets[-1] + len(_lc) + 1)  # +1 for '\n'

        def _offset_to_line(offset: int) -> int:
            """Return 1-indexed line number for a character offset in full_content."""
            return _bisect.bisect_right(_line_offsets, offset)

        # Tüm string literal'leri yakalayan regex
        # Hem tek tırnak hem çift tırnak, escape karakterlerle
        # Support optional string prefixes (r, u, b, f, fr, rf, etc.)
        string_literal_re = re.compile(
            r'''(?P<quote>(?:[rRuUbBfF]{,2})?(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'))'''
        )

        # Triple-quoted stringler için ayrı regex (çok satırlı - tüm dosyada ara)
        # Triple-quoted strings with optional prefixes
        triple_quote_re = re.compile(
            r'''(?P<triple>(?:[rRuUbBfF]{,2})?(?:"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'))'''
        )

        # Key-value eşleştirmesi için regex
        key_capture_re = re.compile(r'(?:["\']?(\w+)["\']?\s*[:=]\s*)$')
        # Assignment detection (var = value)
        assignment_context_re = re.compile(r'([a-zA-Z_]\w*)\s*=\s*')
        # join call detection ("delimiter".join([...]) )
        join_call_re = re.compile(r'(?P<delim>"[^"]*"|\'[^\']*\')\s*\.\s*join\s*\(')
        # list_context_re modül düzeyinde derlenmesi gerekir — döngü içinde tekrar derlenmemesi için
        list_context_re = re.compile(r'([a-zA-Z_]\w*)\s*(?:=\s*[\[\(\{]|\+=\s*[\[\(]|\.(?:append|extend|insert)\s*\()')

        # --- Performans: python_block durumunu tüm satırlar için önceden hesapla ---
        # _is_position_in_python_block her triple-quote için O(n) tarama yapıyordu → O(n²).
        # Bunun yerine tek O(n) geçişiyle her satır numarası için bool önbelleği oluşturuyoruz.
        _python_block_cache: List[bool] = []
        _pb_active = False
        _pb_indent = 0
        for _pb_line in lines:
            _pb_stripped = _pb_line.strip()
            if not _pb_stripped or _pb_stripped.startswith('#'):
                _python_block_cache.append(_pb_active)
                continue
            _pb_ind = self._calculate_indent(_pb_line)
            if self.python_block_re.match(_pb_stripped):
                _pb_active = True
                _pb_indent = _pb_ind
                _python_block_cache.append(_pb_active)
                continue
            if _pb_active and _pb_ind <= _pb_indent:
                _pb_active = False
            _python_block_cache.append(_pb_active)

        def _cached_in_python(line_number: int) -> bool:
            """1-indexed satır için önceden hesaplanmış python_block durumunu döndür."""
            idx = line_number - 1
            if 0 <= idx < len(_python_block_cache):
                return _python_block_cache[idx]
            return False

        # Önce çok satırlı triple-quoted stringleri tüm dosyada ara
        # Bu sayede birden fazla satıra yayılan stringler de yakalanır
        for match in triple_quote_re.finditer(full_content):
            # Ensure match.group exists before accessing
            if match and match.group('triple'):
                text = self._extract_triple_string_content(match.group('triple'))

            context_tag = 'deep_scan'
            # triple quoted content: try to capture key in same line
            line_number = _offset_to_line(match.start())
            context_line = ''
            if 0 <= line_number - 1 < len(lines):
                context_line = lines[line_number - 1].strip()
            # Key capture from context_line
            key_match = key_capture_re.search(context_line[:match.start()])
            found_key = key_match.group(1) if key_match else None
            context_tag = f'variable:{found_key}' if found_key else 'deep_scan'
            if text and (text, context_tag) not in already_found:
                # Calculate in_python status — önbellekten O(1), artık O(n) tarama yok
                # line_number already computed above via _offset_to_line (O(log n))
                in_python = _cached_in_python(line_number)

                # FIX: Define context_line safely
                context_line = ""
                if 0 <= line_number - 1 < len(lines):
                    context_line = lines[line_number - 1].strip()

                # Key-value eşleştirmesi yap
                key_match = key_capture_re.search(context_line[:match.start()])
                found_key = key_match.group(1) if key_match else None

                # Now pass the defined variable
                if self._is_meaningful_data_value(text, found_key):
                    # in_python zaten yukarıda önbellekten alındı — tekrar çağrı yok
                    entry = self._create_deep_scan_entry(
                        text=text,
                        line_number=line_number,
                        context_line=context_line,
                        in_python=in_python,
                        file_path=str(file_path),
                        found_key=found_key
                    )
                    if entry:
                        entries.append(entry)
                        already_found.add((text, entry.get('context_path', ['deep_scan'])[0]))
        
        # Python/init python bloğu içinde miyiz?
        in_python_block = False
        python_block_indent = 0
        
        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            
            # Yorum satırlarını atla
            if stripped.startswith('#'):
                continue
            
            indent = self._calculate_indent(line)
            
            # Python bloğu başlangıcı
            if self.python_block_re.match(stripped):
                in_python_block = True
                python_block_indent = indent
                continue
            
            # Python bloğundan çıkış
            if in_python_block and indent <= python_block_indent and stripped:
                if not stripped.startswith('#'):
                    in_python_block = False
            
            # Normal stringler (tek satırlık)
            found_key = None
            for match in string_literal_re.finditer(line):
                text = self._extract_string_content(match.group('quote'))
                context_tag = 'deep_scan'
                # 1. Try finding context in the current line
                found_key = None
                key_match = key_capture_re.search(line[:match.start()])
                if key_match:
                    found_key = key_match.group(1)
                # list_context_re fonksiyon başında önceden derlenmiş — döngü içinde yeniden derleme yok
                list_match = list_context_re.search(line[:match.start()])

                # 2. Look back at previous lines if not found
                # Optimized: satırları ayrı ayrı tara, string birleştirme yapmadan
                if not found_key and not list_match and line_num > 1:
                    start_idx = max(0, line_num - 10)
                    for _pb_ln in range(line_num - 2, start_idx - 1, -1):
                        _pk = key_capture_re.search(lines[_pb_ln])
                        if _pk:
                            found_key = _pk.group(1)
                            break
                        _pl = list_context_re.search(lines[_pb_ln])
                        if _pl:
                            list_match = _pl
                            break

                if not found_key and list_match:
                    found_key = list_match.group(1)
                else:
                    # Try assignment var detection (same-line or lookback)
                    assign_match = assignment_context_re.search(line[:match.start()]) if not found_key else None
                    if not assign_match and line_num > 1 and not found_key:
                        start_idx = max(0, line_num - 10)
                        for _ab_ln in range(line_num - 2, start_idx - 1, -1):
                            _am = assignment_context_re.search(lines[_ab_ln])
                            if _am:
                                assign_match = _am
                                break
                        if assign_match:
                            found_key = assign_match.group(1)

                    # If not found key, check for join call around the literal
                    if not found_key:
                        # Check immediate lookback for "x".join(...)
                        sb = line[:match.start()]
                        join_m = join_call_re.search(sb)
                        if join_m:
                            found_key = 'join_delim'

                    # Pass found_key to validator
                    # handle implicit string concatenation across lines: collect contiguous string literals
                    # e.g., "Hello "\n   "World" -> Hello World
                    concat_text = text
                    # look ahead for immediate next string literal contiguous with this one
                    next_pos = match.end()
                    rest = line[next_pos:]
                    # Simple detection: if a backslash at end, within parentheses, or trailing + operator then next line may continue the expression
                    rest_r = rest.rstrip()
                    # Continuation detection — daraltılmış koşul:
                    # '(' in line and ')' not in line çok geniş kapsamlıydı; screen/label
                    # tanımlarında neredeyse her satırı tetikleyerek O(n²) taramaya yol açıyordu.
                    # Şimdi yalnızca gerçek devam belirteçleri (trailing \, +, açık parantez
                    # sadece python bloğunda) sayılıyor ve lookahead max 5 satırla sınırlı.
                    stripped_line = line.strip()
                    continuation = (
                        rest_r.endswith('\\')
                        or rest_r.endswith('+')
                        or (in_python_block and stripped_line.endswith('('))
                    )
                    if continuation:
                        # scan following lines for string literal — max 5 satır
                        j = line_num + 1
                        while j <= min(line_num + 5, len(lines)):
                            next_line = lines[j-1]
                            next_match = string_literal_re.search(next_line)
                            # ensure the next line's string literal isn't part of a new assignment
                            if next_line.strip().startswith('#'):
                                break
                            if '=' in next_line.split('\n')[0] and not next_line.strip().startswith(('"', "'")):
                                break
                            if next_match:
                                next_text = self._extract_string_content(next_match.group('quote'))
                                concat_text += next_text
                                # mark with context if found
                                key_ctx = found_key or 'deep_scan'
                                already_found.add((next_text, key_ctx))
                                j += 1
                            else:
                                break

                    if self._is_meaningful_data_value(concat_text, found_key):
                        # in_python her durumda atanmalı, aksi halde UnboundLocalError oluşur
                        in_python = in_python_block
                        entry = self._create_deep_scan_entry(
                            text=concat_text,
                            line_number=line_num,
                            context_line=stripped,
                            in_python=in_python,
                            file_path=str(file_path),
                            found_key=found_key
                        )
                        if entry:
                            entries.append(entry)
                            already_found.add((text, entry.get('context_path', ['deep_scan'])[0]))
        
        self.logger.info(f"Deep scan found {len(entries)} additional strings in {file_path}")
        return entries
    
    def _is_position_in_python_block(self, lines: List[str], target_line: int) -> bool:
        """Belirtilen satırın python bloğu içinde olup olmadığını kontrol et"""
        in_python_block = False
        python_block_indent = 0
        
        for line_num, line in enumerate(lines[:target_line], 1):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            
            indent = self._calculate_indent(line)
            
            if self.python_block_re.match(stripped):
                in_python_block = True
                python_block_indent = indent
                continue
            
            if in_python_block and indent <= python_block_indent and stripped:
                if not stripped.startswith('#'):
                    in_python_block = False
        
        return in_python_block
    
    def _extract_triple_string_content(self, triple_quoted: str) -> str:
        """Triple-quoted string'in içeriğini çıkar"""
        if not triple_quoted:
            return ''
        
        if triple_quoted.startswith('"""') and triple_quoted.endswith('"""'):
            return triple_quoted[3:-3].strip()
        elif triple_quoted.startswith("'''") and triple_quoted.endswith("'''"):
            return triple_quoted[3:-3].strip()
        return triple_quoted.strip()
    
    def _is_deep_scan_candidate(self, text: str, in_python: bool, context_line: str) -> bool:
        """
        Determine if a string is a candidate for deep scanning.

        Args:
            text: The string to evaluate.
            in_python: Whether the string is inside a Python block.
            context_line: The line of code providing context for the string.

        Returns:
            True if the string is a candidate for deep scanning, False otherwise.
        """
        # Example logic using in_python
        visible_text = self._normalize_inline_text_candidate(text)
        analysis_text = visible_text if visible_text else text

        if len(analysis_text) > 300 and in_python and context_line.strip().startswith('renpy.notify'):
            return True

        if not analysis_text or len(analysis_text.strip()) < 3:
            return False
        
        text_lower = analysis_text.lower().strip()
        context_lower = context_line.lower()
        
        # is_meaningful_text kontrolü (fix typo -> use is_meaningful_text)
        if not self.is_meaningful_text(analysis_text):
            return False
        
        # Dosya yolları ve teknik terimler
        if any(ext in text_lower for ext in ['.png', '.jpg', '.mp3', '.ogg', '.ttf', '.otf', '.rpy']):
            return False
        
        # Değişken isimleri gibi görünen tek kelimeler (snake_case, camelCase)
        if re.match(r'^[a-z_][a-z0-9_]*$', text.strip()):
            return False
        if re.match(r'^[a-z]+[A-Z][a-zA-Z0-9]*$', text.strip()):
            return False
        
        # Renk kodları (#ffffff)
        if re.match(r'^#[0-9a-fA-F]{3,8}$', text.strip()):
            return False
        
        # Saf Ren'Py değişken referansları — çevrilemez (örn: [page], [player])
        _ts = text.strip()
        if re.match(r'^\[[a-zA-Z_]\w*\]$', _ts):
            return False
        # Sadece markup/tag içeren, alfabetik içeriği olmayan stringler
        _bare = re.sub(r'\{[^}]*\}|\[[^\]]*\]', '', _ts).strip()
        if _bare and not re.search(r'[a-zA-Z\u00C0-\u024F]', _bare):
            return False
        # Label/screen/transform isimleri
        if 'label' in context_lower or 'jump' in context_lower or 'call' in context_lower:
            if re.match(r'^[a-z_][a-z0-9_]*$', text.strip()):
                return False
        
        # Transform ve style isimleri
        if 'transform' in context_lower or 'style' in context_lower:
            return False
        
        # Image/audio tanımları
        if 'image ' in context_lower or 'audio ' in context_lower:
            return False
        
        # register_ ve config. ayarları (teknik)
        if 'register_' in context_lower:
            return False
        
        # Sadece placeholder olan stringler
        if re.fullmatch(r'\s*(\[[^\]]+\]|\{[^}]+\})+\s*', analysis_text):
            return False
        
        # En az 1 harf ve en az 3 karakter içermeli (Unicode-aware)
        if not any(ch.isalpha() for ch in analysis_text) or len(analysis_text.strip()) < 3:
            return False
        
        # If the text is too long and in a Python block, check for docstring patterns
        if len(analysis_text) > 300 and context_line.strip().startswith('renpy.notify'):
            # If the text lacks game-specific tags, it is likely a docstring
            if '{' not in analysis_text and '[' not in analysis_text:
                return False  # Skip docstrings
        
        return True
    
    def _create_deep_scan_entry(
        self,
        text: str,
        line_number: int,
        context_line: str,
        in_python: bool,
        file_path: str = '',
        found_key: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Deep scan sonucu için entry oluştur"""
        processed_text, placeholder_map = self.preserve_placeholders(text)

        text_type = 'deep_scan'
        if in_python:
            text_type = 'python_string'
        context_tag = 'deep_scan'
        if found_key:
            context_tag = f'variable:{found_key}'

        return {
            'text': text,
            'line_number': line_number,
            'context_line': context_line,
            'character': '',
            'text_type': text_type,
            'context_path': [context_tag],
            'processed_text': processed_text,
            'placeholder_map': placeholder_map,
            'is_deep_scan': True,  # Marker for UI
            'file_path': file_path,
        }
    
    def extract_with_deep_scan(
        self,
        file_path: Union[str, Path],
        include_deep_scan: bool = True,
        include_ast_scan: bool = True  # NEW: v2.4.1
    ) -> List[Dict[str, Any]]:
        """
        Normal extraction + opsiyonel deep scan + AST scan.
        
        Args:
            file_path: Dosya yolu
            include_deep_scan: Regex-based deep scan sonuçlarını dahil et
            include_ast_scan: AST-based deep scan sonuçlarını dahil et (v2.4.1)
            
        Returns:
            Birleştirilmiş entry listesi
        """
        entries = self.extract_text_entries(file_path)
        seen_texts = {e.get('text', '') for e in entries}
        
        if include_deep_scan:
            deep_entries = self.deep_scan_strings(file_path, normal_entries=entries)
            for entry in deep_entries:
                if entry.get('text') not in seen_texts:
                    entries.append(entry)
                    seen_texts.add(entry.get('text'))
        
        # NEW v2.4.1: AST-based deep scan
        if include_ast_scan:
            try:
                ast_entries = self.deep_scan_strings_ast(file_path)
                for entry in ast_entries:
                    if entry.get('text') not in seen_texts:
                        entries.append(entry)
                        seen_texts.add(entry.get('text'))
            except Exception as exc:
                self.logger.debug(f"AST scan failed for {file_path}: {exc}")
        
        return entries
    
    def extract_from_directory_with_deep_scan(
        self,
        directory: Union[str, Path],
        include_deep_scan: bool = True,
        recursive: bool = True,
        exclude_dirs: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[int, int, Path], None]] = None,
    ) -> Dict[Path, List[Dict[str, Any]]]:
        """
        Klasördeki tüm dosyaları deep scan ile tara.
        
        Args:
            directory: Klasör yolu
            include_deep_scan: Deep scan dahil et
            recursive: Alt klasörleri de tara
            
        Returns:
            {dosya_yolu: [entry listesi]} dictionary
        """
        directory = Path(directory)
        search_root = self._resolve_search_root(directory)
        results: Dict[Path, List[Dict[str, Any]]] = {}
        
        if recursive:
            iterator = list(search_root.glob("**/*.rpy")) + list(search_root.glob("**/*.RPY"))
        else:
            iterator = list(search_root.glob("*.rpy")) + list(search_root.glob("*.RPY"))
        
        rpy_files = [
            f
            for f in iterator
            if not self._is_excluded_rpy(f, search_root)
            and not self._is_in_manual_exclude_dirs(f, search_root, exclude_dirs)
        ]
        
        self.logger.info(
            "Deep scan: Found %s .rpy files for processing",

            len(rpy_files),
        )
        
        total_files = len(rpy_files)
        for index, rpy_file in enumerate(rpy_files, start=1):
            try:
                if progress_callback is not None:
                    progress_callback(index, total_files, rpy_file)
                entries = self.extract_with_deep_scan(rpy_file, include_deep_scan, include_ast_scan=include_deep_scan)
                results[rpy_file] = entries
            except Exception as exc:
                # Log full traceback to aid debugging of decompiled inputs
                self.logger.exception("Error in deep scan for %s: %s", rpy_file, exc)
                results[rpy_file] = []
            if index % 5 == 0:
                time.sleep(0.001)
        
        total_normal = sum(
            len([e for e in entries if not e.get('is_deep_scan')])
            for entries in results.values()
        )
        total_deep = sum(
            len([e for e in entries if e.get('is_deep_scan')])
            for entries in results.values()
        )
        
        self.logger.info(
            "Deep scan completed: %s files, %s normal texts, %s deep scan texts",
            len(results),
            total_normal,
            total_deep,
        )
        
        return results

    # ========== RPYC DIRECT READER ==========
    # Bu modül .rpyc dosyalarını doğrudan okuyarak AST'den metin çıkarır
    # .rpy dosyası olmasa bile çalışır
    
    def extract_from_rpyc(
        self,
        file_path: Union[str, Path]
    ) -> List[Dict[str, Any]]:
        """
        .rpyc dosyasından doğrudan metin çıkar.
        AST (Abstract Syntax Tree) okuyarak çalışır.
        
        Args:
            file_path: .rpyc dosya yolu
            
        Returns:
            Metin entry listesi
        """
        try:
            from .rpyc_reader import extract_texts_from_rpyc
            return extract_texts_from_rpyc(file_path)
        except ImportError:
            self.logger.warning("rpyc_reader module not available")
            return []
        except Exception as exc:
            self.logger.error("Error reading RPYC %s: %s", file_path, exc)
            return []
    
    def extract_from_rpyc_directory(
        self,
        directory: Union[str, Path],
        recursive: bool = True
    ) -> Dict[Path, List[Dict[str, Any]]]:
        """
        Klasördeki tüm .rpyc dosyalarından metin çıkar.
        
        Args:
            directory: Klasör yolu
            recursive: Alt klasörleri de tara
            
        Returns:
            {dosya_yolu: [entry listesi]} dictionary
        """
        try:
            from .rpyc_reader import extract_texts_from_rpyc_directory
            return extract_texts_from_rpyc_directory(directory, recursive=recursive, config_manager=self.config_manager)
        except ImportError:
            self.logger.warning("rpyc_reader module not available")
            return {}
        except Exception as exc:
            self.logger.error("Error reading RPYC directory %s: %s", directory, exc)
            return {}
    
    def extract_combined(
        self,
        directory: Union[str, Path],
        include_rpy: bool = True,
        include_rpyc: bool = False,
        include_deep_scan: bool = False,
        recursive: bool = True,
        exclude_dirs: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[int, int, Path], None]] = None,
    ) -> Dict[Path, List[Dict[str, Any]]]:
        """
        Hem .rpy hem .rpyc dosyalarından metin çıkar.
        En kapsamlı çıkarma yöntemi.
        
        Args:
            directory: Klasör yolu
            include_rpy: .rpy dosyalarını işle
            include_rpyc: .rpyc dosyalarını işle (AST ile)
            include_deep_scan: Deep scan uygula (.rpy için)
            recursive: Alt klasörleri de tara
            
        Returns:
            Birleştirilmiş sonuçlar
        """
        results: Dict[Path, List[Dict[str, Any]]] = {}
        all_texts: Set[str] = set()
        
        # .rpy dosyalarından çıkar
        if include_rpy:
            rpy_results = self.extract_from_directory_with_deep_scan(
                directory,
                include_deep_scan=include_deep_scan,
                recursive=recursive,
                exclude_dirs=exclude_dirs,
                progress_callback=progress_callback,
            )
            for file_path, entries in rpy_results.items():
                results[file_path] = entries
                for entry in entries:
                    all_texts.add(entry.get('text', ''))
        
        # .rpyc dosyalarından çıkar (opsiyonel)
        if include_rpyc:
            try:
                rpyc_results = self.extract_from_rpyc_directory(directory, recursive)
                
                # RPYC sonuçlarını ekle (duplicate'leri atla)
                for file_path, entries in rpyc_results.items():
                    # Sadece .rpy'de bulunmayan metinleri ekle
                    new_entries = [
                        e for e in entries 
                        if e.get('text', '') not in all_texts
                    ]
                    
                    if new_entries:
                        if file_path not in results:
                            results[file_path] = []
                        results[file_path].extend(new_entries)
                        
                        # Yeni metinleri kaydet
                        for entry in new_entries:
                            all_texts.add(entry.get('text', ''))
                
                rpyc_only = sum(
                    len([e for e in entries if e.get('is_rpyc')])
                    for entries in results.values()
                )
                self.logger.info(
                    "RPYC extraction added %s unique texts not found in .rpy files",
                    rpyc_only
                )
                
            except Exception as exc:
                self.logger.warning("RPYC extraction failed: %s", exc)
        
        total = sum(len(entries) for entries in results.values())
        self.logger.info(
            "Combined extraction: %s files, %s total texts",
            len(results),
            total
        )
        
        
        return results

    def _is_meaningful_data_value(self, text: str, key: Optional[str]) -> bool:
        """
        Veri dosyaları (JSON, XML vb.) için özel filtre.
        Standart metinlerden daha esnek davranır (tek kelimelik eşya isimleri vb. için).
        """
        if not text:
            return False

        # --- CRITICAL SAFETY: Skip regexes and technical code sequences ---
        # Strings containing regex syntax like (?:, (?P<, \x1B, or heavy regex markers
        # Use common logic for technical detection
        if self.is_meaningful_text and not self.is_meaningful_text(text):
             # But check for regex specifically if is_meaningful_text didn't catch it
             if re.search(r'\\x[0-9a-fA-F]{2}|(?:\(\?\:|\(\?P<|\[@-Z\\-_\]|\[0-\?\]\*|\[ -/\]\*|\[@-~\])', text):
                  return False
        
        # Extra heuristic for data values: if it looks like a long technical regex or escape sequence string
        if len(re.findall(r'[\\#\[\](){}|*+?^$]', text)) > len(text) * 0.3:
            return False

        # 1. If key is provided and it's a BLACKLIST key, it's not meaningful
        if key and str(key).lower() in self.DATA_KEY_BLACKLIST:
            return False


        # If there's a key, only accept it when the key is in the whitelist
        if key:
            key_lower = str(key).lower()
            if key_lower in self.DATA_KEY_WHITELIST:
                # Accept if not a numeric or URL/file path
                if not re.match(r'^[-+]?\d+(\.\d+)?$', text.strip()) and not text.strip().startswith(('#', 'http')):
                    return True
            # If key present but not in whitelist, do not accept (smart whitelist)
            return False


        # If no key provided, use heuristics similar to is_meanful_text but allow
        # simple single-word items (e.g., 'Sword')
        if re.match(r'^[-+]?\d+(\.\d+)?$', text.strip()) or text.strip().startswith(('#', 'http')):
            return False

        if any(text.lower().endswith(ext) for ext in ['.png', '.jpg', '.mp3', '.ogg']):
            return False

        # Language-independent: strip placeholders/tags and require at least
        # two Unicode letters for data values when no key provided.
        try:
            cleaned = re.sub(r'(\[[^\]]+\]|\{[^}]+\})', '', text or '').strip()
            if sum(1 for ch in cleaned if ch.isalpha()) < 2:
                return False
        except Exception:
            # Fallback: require at least one alphabetic char
            if not any(ch.isalpha() for ch in text):
                return False

        return True



        # Extraction döngüsü içinde olmalı:
        while index < len(lines):
            raw_line = lines[index]
            stripped_line = raw_line.strip()

            # Edge-case: Teknik satırları, sadece teknik terimleri, dosya yollarını, renk kodlarını, değişken/tag satırlarını, boş veya yorum satırlarını atla
            if (
                self.technical_line_re.match(stripped_line)
                or self.numeric_or_path_re.match(stripped_line)
                or self.renpy_var_or_tag_re.match(stripped_line)
                or self.comment_or_empty_re.match(stripped_line)
            ):
                index += 1
                continue

            # Menü/choice satırlarında teknik koşulları atla
            if self.menu_technical_condition_re.match(stripped_line):
                index += 1
                continue

            # ...mevcut extraction işlemleri...
            index += 1
