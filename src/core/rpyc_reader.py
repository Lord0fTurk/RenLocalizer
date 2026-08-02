"""
RPYC File Reader for RenLocalizer.

This module reads compiled Ren'Py script files (.rpyc) and extracts
translatable text directly from the AST (Abstract Syntax Tree).

This provides more reliable extraction than regex-based parsing of .rpy files,
especially for:
- Text inside init python blocks
- Dynamically generated dialogue
- Complex screen definitions
- Menu items with conditions

Implementation based on Ren'Py's internal pickle format (MIT licensed).

The Fake* classes below only reproduce the class/attribute names Ren'Py's
own `renpy/ast.py` (Copyright 2004-2026 Tom Rothamel, MIT License) uses in
its pickled .rpyc output, which is required for pickle to unpickle those
files at all -- no original Ren'Py source or logic is copied.
"""

from __future__ import annotations

import collections
import logging
import pickle
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)

# Import the whitelist and parser utilities from parser.py
from .parser import DATA_KEY_WHITELIST, RenPyParser
import ast
import re
import io
import traceback
import binascii
import sys
from src.core.deep_extraction import (
    DeepExtractionConfig,
    DeepVariableAnalyzer,
    FStringReconstructor,
    confidence_band,
    resolve_minimum_extraction_confidence,
    score_extraction_confidence,
    _shared_analyzer as _deep_var_analyzer,
)


# ============================================================================
# PERFORMANCE: PRE-COMPILED REGEX PATTERNS (REGEX POOLING)
# ============================================================================
# Compiling these at module level prevents re-compilation for every single string check.

# Universal ID Ranges (Latin, Cyrillic, Greek, Arabic, Hebrew, Thai, CJK, Hangul)
# Used to build other regexes securely
_UNICODE_RANGES = (
    r'a-zA-Z'                                   # Latin Basic
    r'\u00C0-\u00FF\u0100-\u024F\u1E00-\u1EFF'  # Latin Extended
    r'\u0400-\u052F\u2DE0-\u2DFF\uA640-\uA69F'  # Cyrillic (Expanded)
    r'\u0370-\u03FF\u1F00-\u1FFF'               # Greek
    r'\u0600-\u06FF\u0750-\u077F'               # Arabic
    r'\u0590-\u05FF'                            # Hebrew
    r'\u0E00-\u0E7F'                            # Thai
    r'\u4E00-\u9FFF\u3400-\u4DBF'               # CJK Unified
    r'\u3040-\u309F\u30A0-\u30FF'               # Hiragana/Katakana
    r'\uAC00-\uD7AF'                            # Hangul
)

# Checks for characters allowed in valid text (Letters + Numbers + Common Punctuation)
_RE_VALID_TEXT_CHARS = re.compile(f'[{_UNICODE_RANGES}]')

# Binary / Corruption Checks
_RE_PUA = re.compile(r'[\uE000-\uF8FF\uFFF0-\uFFFF]')
_RE_CONTROL_CHARS = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]')

# Inverse logic: Match things that are NOT valid text, whitespace, or common symbols
# Used to detect binary blobs disguised as strings
_RE_NON_PRINTABLE_HIGH_RATIO = re.compile(f'[^\\x20-\\x7E\\s{_UNICODE_RANGES}]')

# For short strings, any character NOT in our safe ranges is "unusual"
_RE_UNUSUAL_SHORT = re.compile(f'[^\\x20-\\x7E{_UNICODE_RANGES}]')

_RE_ASCII_LETTERS = re.compile(r'[a-zA-Z]') # Kept for variable name checking
_RE_ANY_LETTER = re.compile(f'[{_UNICODE_RANGES}]') # Used for language-agnostic text validation

# Format Checks
_RE_COLOR_HEX = re.compile(r'^#[0-9a-fA-F]{3,8}$')
_RE_PURE_NUMBER = re.compile(r'^-?\d+\.?\d*$')
_RE_SNAKE_CASE = re.compile(r'^[a-z][a-z0-9]*(_[a-z0-9]+)+$') # Strictly ASCII for technical variables
_RE_HAS_LETTER = re.compile(f'[{_UNICODE_RANGES}]')

# Python Code Patterns (Combined for speed)
_PYTHON_CODE_PATTERNS = [
    r'\bdef\s+\w+\s*\(', r'\bclass\s+\w+\s*[:\(]', r'\bfor\s+\w+\s+in\s+', 
    r'\bif\s+\w+\s+in\s+\w+:', r'\bimport\s+\w+', r'\bfrom\s+\w+\s+import', 
    r'\breturn\s+\w+', r'\braise\s+\w+', r'renpy\.\w+\.\w+', r'renpy\.\w+\(', 
    r'_\w+\[', r'\w+\s*=\s*True\b', r'\w+\s*=\s*False\b', r'\w+\s*=\s*None\b',
]
_RE_PYTHON_CODE = re.compile('|'.join(f'(?:{p})' for p in _PYTHON_CODE_PATTERNS))

_RE_STR_CONCAT = re.compile(r'"\s*\+\s*\w+\s*\+\s*"')
_RE_ATTR_CONCAT = re.compile(r'\w+\.\w+\s*\+')

_PYTHON_BUILTINS = [
    r'\bstr\s*\(', r'\bint\s*\(', r'\bfloat\s*\(', r'\blen\s*\(',
    r'\blist\s*\(', r'\bdict\s*\(', r'\btuple\s*\(', r'\bset\s*\('
]
_RE_PYTHON_BUILTINS = re.compile('|'.join(f'(?:{p})' for p in _PYTHON_BUILTINS))

_RE_FILE_PATH_VAR = re.compile(r'["\']?[\w/]+["\']?\s*\+\s*\w+')
_RE_FILE_PATH_STRICT = re.compile(r'^[\w\-. ]+(?:/[\w\-. ]+)+$') # Detects paths like 'audio/bgm/track.ogg'
_RE_STRICT_SNAKE_CASE = re.compile(r'^[a-z_][a-z0-9_]*$') # Identifies likely variable names


# ============================================================================
# FAKE REN'PY MODULE SYSTEM
# ============================================================================
# We need to create fake classes that match Ren'Py's AST structure
# so pickle can deserialize the .rpyc files without the actual Ren'Py SDK


class FakeModuleRegistry:
    """Registry for fake modules needed to unpickle Ren'Py AST."""
    
    _modules: Dict[str, Any] = {}
    _classes: Dict[str, type] = {}
    
    @classmethod
    def register_module(cls, name: str, module: Any) -> None:
        cls._modules[name] = module
    
    @classmethod
    def register_class(cls, full_name: str, klass: type) -> None:
        cls._classes[full_name] = klass
    
    @classmethod
    def get_class(cls, module: str, name: str) -> Optional[type]:
        full_name = f"{module}.{name}"
        return cls._classes.get(full_name)


class FakeASTBase:
    """Base class for fake Ren'Py AST nodes."""
    
    def __init__(self):
        self.linenumber: int = 0
        self.filename: str = ""
    
    def __getattr__(self, name: str) -> Any:
        """Fallback for missing attributes in legacy/variant Ren'Py AST nodes."""
        if name == "hide":
            return False
        if name == "code":
            return None
        if name == "store":
            return "store"
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def __setstate__(self, state: dict) -> None:
        """Handle pickle deserialization with Data Integrity protection."""
        # Initialize extra_state to capture unknown slots (Future Proofing)
        self._extra_state = None
        
        if isinstance(state, dict):
            self.__dict__.update(state)
        elif isinstance(state, tuple):
            # Some nodes use (dict, slotstate) or longer tuples.
            # Merge any dict parts into the object's __dict__.
            found_dict = False
            for part in state:
                if isinstance(part, dict):
                    self.__dict__.update(part)
                    found_dict = True
            
            # CRITICAL: Preserve the full state tuple if it contains non-dict components.
            # This ensures that if Ren'Py adds new slots in the tuple we don't throw them away.
            if len(state) > 1 or not found_dict:
                 self._extra_state = state


# ============================================================================
# FAKE REN'PY AST CLASSES
# ============================================================================
# These mirror the essential Ren'Py AST node types we need for text extraction


class FakeSay(FakeASTBase):
    """Represents dialogue: character "text" """
    def __init__(self):
        super().__init__()
        self.who: Optional[str] = None  # Character speaking
        self.who_fast: bool = False  # Fast lookup for simple names
        self.what: str = ""  # The dialogue text
        self.with_: Optional[str] = None
        self.interact: bool = True
        self.attributes: Optional[tuple] = None
        self.arguments: Optional[Any] = None
        self.temporary_attributes: Optional[tuple] = None
        self.identifier: Optional[str] = None
        self.explicit_identifier: bool = False


class FakeBubble(FakeSay):
    """
    Represents a speech bubble (Ren'Py 8.5+).
    Functionally similar to Say, but distinct in AST.
    """
    def __init__(self):
        super().__init__()
        self.properties: Optional[dict] = None # Capture alt, tooltip, help
        self.code: Optional[Any] = None # Some bubbles might have code blocks

    def __setstate__(self, state):
        # Bubbles can store properties in a dictionary within the state
        super().__setstate__(state)
        # Standard FakeASTBase handling usually catches basic slots,
        # but we ensure properties are explicitly accessible.
        pass


class FakeTranslateSay(FakeSay):
    """
    A node that combines a translate and a say statement.
    This is used in newer Ren'Py versions for translatable dialogue.
    """
    def __init__(self):
        super().__init__()
        self.identifier: Optional[str] = None
        self.alternate: Optional[str] = None
        self.language: Optional[str] = None
        self.translatable: bool = True
        self.translation_relevant: bool = True
    
    @property
    def after(self):
        return getattr(self, 'next', None)
    
    @property
    def block(self) -> list:
        return []


class FakeMenu(FakeASTBase):
    """Represents menu statement with choices."""
    def __init__(self):
        super().__init__()
        self.items: List[Tuple[str, Any, Any]] = []  # (label, condition, block)
        self.set: Optional[str] = None
        self.with_: Optional[str] = None
        self.has_caption: bool = False
        self.arguments: Optional[Any] = None
        self.item_arguments: Optional[List[Any]] = None
        self.statement_start: Optional[Any] = None


class FakeLabel(FakeASTBase):
    """Represents label statement."""
    def __init__(self):
        super().__init__()
        self.name: str = ""
        self.block: List[Any] = []
        self.parameters: Optional[Any] = None
        self.hide: bool = False


class FakeInit(FakeASTBase):
    """Represents init block."""
    def __init__(self):
        super().__init__()
        self.block: List[Any] = []
        self.priority: int = 0


class FakePython(FakeASTBase):
    """Represents python/$ code block."""
    def __init__(self):
        super().__init__()
        self.code: Optional[Any] = None
        self.hide: bool = False
        self.store: str = "store"

    def __setstate__(self, state: dict) -> None:
        # EarlyPython nodes (mapped to FakePython) may omit 'hide' from their
        # pickle state because EarlyPython predates the hide attribute.
        # Set safe defaults before applying state so AttributeError is avoided.
        self.code = None
        self.hide = False
        self.store = "store"
        super().__setstate__(state)


class FakeEarlyPython(FakePython):
    """Represents EarlyPython node (pre-dates hide attribute in older Ren'Py versions)."""
    def __init__(self):
        super().__init__()
        self.hide = False

    def __setstate__(self, state) -> None:
        super().__setstate__(state)
        self.hide = getattr(self, 'hide', False)


class FakePyCode:
    """Represents Python code object inside AST."""
    def __init__(self):
        self.source: str = ""
        self.location: tuple = ()
        self.mode: str = "exec"
        self.py: Optional[int] = None
        self.bytecode: Optional[bytes] = None
    
    def __setstate__(self, state: tuple) -> None:
        try:
            if isinstance(state, dict):
                # Older pickles may supply a dict
                self.__dict__.update(state)
            elif isinstance(state, tuple) or isinstance(state, list):
                # Some pickles provide (something, source, location, mode, py, ...)
                if len(state) >= 4:
                    # Safely assign known positions
                    # skip first element if it's not the source
                    possible = state[:5]
                    # Find the first element that looks like source (string)
                    for elem in possible:
                        if isinstance(elem, str) and elem and elem != possible[0]:
                            # prefer the second position for source when structure matches
                            break
                    # Best-effort assignment based on common layouts
                    try:
                        _, self.source, self.location, self.mode = state[:4]
                    except Exception:
                        # Fallback: try to find string and assign
                        for part in state:
                            if isinstance(part, str):
                                self.source = part
                                break
                        # location/mode may remain defaults
                    if len(state) >= 5:
                        try:
                            self.py = state[4]
                        except Exception:
                            pass
        except Exception:
            # Be conservative on unknown formats
            pass
        self.bytecode = None


class FakePyExpr(str):
    """
    Represents Python expression in AST (subclass of str).
    In newer Ren'Py versions, includes additional fields like hashcode and col_offset.
    """
    
    def __new__(cls, s: str = "", filename: str = "", linenumber: int = 0, 
                py: int = None, hashcode: int = None, col_offset: int = 0,
                *args):  # Accept any extra arguments
        instance = str.__new__(cls, s)
        instance.filename = filename
        instance.linenumber = linenumber
        instance.py = py
        instance.hashcode = hashcode
        instance.col_offset = col_offset
        return instance
    
    def __getnewargs__(self) -> tuple:
        return (str(self),)
    
    def __reduce__(self):
        # Handle pickle properly
        return (FakePyExpr, (str(self), getattr(self, 'filename', ''), 
                            getattr(self, 'linenumber', 0)))
    
    def __setstate__(self, state):
        # Handle any extra state
        if isinstance(state, dict):
            for k, v in state.items():
                setattr(self, k, v)


class FakeScreen(FakeASTBase):
    """Represents screen definition."""
    def __init__(self):
        super().__init__()
        self.name: str = ""
        self.screen: Optional[Any] = None  # SL2 screen object
        self.parameters: Optional[Any] = None


class FakeTranslate(FakeASTBase):
    """Represents translate block."""
    def __init__(self):
        super().__init__()
        self.identifier: str = ""
        self.language: Optional[str] = None
        self.block: List[Any] = []


class FakeTranslateString(FakeASTBase):
    """Represents string translation."""
    def __init__(self):
        super().__init__()
        self.language: Optional[str] = None
        self.old: str = ""
        self.new: str = ""


class FakeTranslateBlock(FakeASTBase):
    """Represents translate block (style/python)."""
    def __init__(self):
        super().__init__()
        self.language: Optional[str] = None
        self.block: List[Any] = []


class FakeUserStatement(FakeASTBase):
    """Represents user-defined statement (like nvl, music, etc.)."""
    def __init__(self):
        super().__init__()
        self.line: str = ""
        self.parsed: Optional[Any] = None
        self.block: Optional[List[Any]] = None
        self.translatable: bool = False
        self.code_block: Optional[List[Any]] = None
        self.translation_relevant: bool = False
        self.subparses: List[Any] = []
        self.atl: Optional[Any] = None
        self.init_priority: Optional[int] = None
        self.init_offset: Optional[int] = None


class FakePostUserStatement(FakeASTBase):
    """Post-execution node for user statements."""
    def __init__(self):
        super().__init__()
        self.parent: Optional[Any] = None


class FakeIf(FakeASTBase):
    """Represents if/elif/else statement."""
    def __init__(self):
        super().__init__()
        self.entries: List[Tuple[Any, List[Any]]] = []  # (condition, block)


class FakeWhile(FakeASTBase):
    """Represents while loop."""
    def __init__(self):
        super().__init__()
        self.condition: Any = None
        self.block: List[Any] = []


class FakeDefine(FakeASTBase):
    """Represents define statement."""
    def __init__(self):
        super().__init__()
        self.varname: str = ""
        self.code: Optional[Any] = None
        self.store: str = "store"
        self.operator: str = "="
        self.index: Optional[Any] = None


class FakeDefault(FakeASTBase):
    """Represents default statement."""
    def __init__(self):
        super().__init__()
        self.varname: str = ""
        self.code: Optional[Any] = None
        self.store: str = "store"


class FakeImage(FakeASTBase):
    """Represents image statement."""
    def __init__(self):
        super().__init__()
        self.imgname: tuple = ()
        self.code: Optional[Any] = None
        self.atl: Optional[Any] = None


class FakeShow(FakeASTBase):
    """Represents show statement."""
    def __init__(self):
        super().__init__()
        self.imspec: tuple = ()
        self.atl: Optional[Any] = None


class FakeScene(FakeASTBase):
    """Represents scene statement."""
    def __init__(self):
        super().__init__()
        self.imspec: Optional[tuple] = None
        self.layer: str = "master"
        self.atl: Optional[Any] = None


class FakeHide(FakeASTBase):
    """Represents hide statement."""
    def __init__(self):
        super().__init__()
        self.imspec: tuple = ()


class FakeWith(FakeASTBase):
    """Represents with statement."""
    def __init__(self):
        super().__init__()
        self.expr: str = ""
        self.paired: Optional[str] = None


class FakeCall(FakeASTBase):
    """Represents call statement."""
    def __init__(self):
        super().__init__()
        self.label: str = ""
        self.expression: bool = False
        self.arguments: Optional[Any] = None


class FakeJump(FakeASTBase):
    """Represents jump statement."""
    def __init__(self):
        super().__init__()
        self.target: str = ""
        self.expression: bool = False


class FakeReturn(FakeASTBase):
    """Represents return statement."""
    def __init__(self):
        super().__init__()
        self.expression: Optional[str] = None


class FakePass(FakeASTBase):
    """Represents pass statement."""
    pass


class FakeTestcase(FakeASTBase):
    """
    Represents testcase statement (Ren'Py 8.x+).
    Used for automated testing scenarios.
    Example: testcase "test_menu" label start
    """
    def __init__(self):
        super().__init__()
        self.label: str = ""  # Target label for the test
        self.options: Optional[str] = None  # Test options/configuration
        self.block: List[Any] = []  # Test block content


class FakeGeneric(FakeASTBase):
    """Generic fallback for unknown AST nodes."""
    def __init__(self):
        super().__init__()
        self._unknown_type: str = ""


class FakeArgumentInfo:
    """Represents argument information for calls."""
    def __init__(self):
        self.arguments: List[tuple] = []
        self.extrapos: Optional[str] = None
        self.extrakw: Optional[str] = None
    
    def __setstate__(self, state):
        if isinstance(state, dict):
            self.__dict__.update(state)
        elif isinstance(state, tuple) or isinstance(state, list):
            # Some pickles provide a tuple/list whose first element contains the dict state
            # Be lenient: if the first element is a dict, merge it; otherwise merge any dict parts
            if state:
                if isinstance(state[0], dict):
                    self.__dict__.update(state[0])
                else:
                    for part in state:
                        if isinstance(part, dict):
                            self.__dict__.update(part)


class FakeParameterInfo:
    """Represents parameter information for definitions."""
    def __init__(self):
        self.parameters: List[tuple] = []
        self.extrapos: Optional[str] = None
        self.extrakw: Optional[str] = None
    
    def __setstate__(self, state):
        if isinstance(state, dict):
            self.__dict__.update(state)
        elif isinstance(state, tuple) or isinstance(state, list):
            # Be lenient: merge any dict parts from tuple/list state
            for part in state:
                if isinstance(part, dict):
                    self.__dict__.update(part)


class FakeATLTransformBase:
    """Base for ATL transform objects."""
    def __init__(self):
        self.atl: Optional[Any] = None
        self.parameters: Optional[Any] = None
        self.statements: List[Any] = []
    
    def __setstate__(self, state):
        if isinstance(state, dict):
            self.__dict__.update(state)


class FakeRawBlock:
    """ATL raw block."""
    def __init__(self):
        self.statements: List[Any] = []
        self.animation: bool = False
        self.loc: tuple = ()
    
    def __setstate__(self, state):
        if isinstance(state, dict):
            self.__dict__.update(state)


class FakeNode:
    """Generic node from renpy.ast.Node."""
    def __init__(self):
        self.filename: str = ""
        self.linenumber: int = 0
        self._name: Optional[Any] = None
        self.name_version: int = 0
        self.name_serial: int = 0
        self.next: Optional[Any] = None
    
    def __setstate__(self, state):
        if isinstance(state, dict):
            self.__dict__.update(state)
        elif isinstance(state, tuple) or isinstance(state, list):
            # (dict, slotstate, ...) format - merge any dict parts
            for part in state:
                if isinstance(part, dict):
                    self.__dict__.update(part)


# SL2 (Screen Language 2) fake classes
class FakeSLScreen:
    """Screen Language 2 screen object."""
    def __init__(self):
        self.name: str = ""
        self.children: List[Any] = []
        self.keyword: List[tuple] = []
        self.parameters: Optional[Any] = None
        self.location: tuple = ()
    
    def __setstate__(self, state: dict) -> None:
        if isinstance(state, dict):
            self.__dict__.update(state)


class FakeSLDisplayable:
    """Screen Language displayable (text, textbutton, etc.)."""
    def __init__(self):
        self.displayable: Any = None
        self.style: Optional[str] = None
        self.positional: List[str] = []
        self.keyword: List[tuple] = []
        self.children: List[Any] = []
        self.location: tuple = ()
    
    def __setstate__(self, state: dict) -> None:
        if isinstance(state, dict):
            self.__dict__.update(state)


class FakeSLIf:
    """Screen Language if statement."""
    def __init__(self):
        self.entries: List[Tuple[Any, Any]] = []  # (condition, block)

    def __setstate__(self, state: dict) -> None:
        if isinstance(state, dict):
            self.__dict__.update(state)


class FakeActionBase:
    """Base for serialized Ren'Py actions."""
    pass

class FakeConfirm(FakeActionBase):
    def __init__(self):
        self.prompt = ""
        self.yes = None
        self.no = None

    def __setstate__(self, state):
        # Confirm often pickles as (prompt, yes, no) tuple or dict
        if isinstance(state, tuple):
             # Heuristic: first arg is usually prompt
             if len(state) > 0 and isinstance(state[0], str):
                 self.prompt = state[0]
        elif isinstance(state, dict):
             self.__dict__.update(state)

class FakeNotify(FakeActionBase):
    def __init__(self):
        self.message = ""
    
    def __setstate__(self, state):
        if isinstance(state, tuple) and len(state) > 0:
            self.message = state[0]
        elif isinstance(state, dict):
            self.__dict__.update(state)

class FakeTooltip(FakeActionBase):
    def __init__(self):
        self.value = ""

    def __setstate__(self, state):
        if isinstance(state, tuple) and len(state) > 0:
            self.value = state[0]
        elif isinstance(state, dict):
             self.__dict__.update(state)

class FakeHelp(FakeActionBase):
    def __init__(self):
        self.help = ""

    def __setstate__(self, state):
        if isinstance(state, tuple) and len(state) > 0:
            self.help = state[0]
        elif isinstance(state, dict):
            self.__dict__.update(state)



class FakeSLFor:
    """Screen Language for loop."""
    def __init__(self):
        self.variable: str = ""
        self.expression: str = ""
        self.children: List[Any] = []
        self.location: tuple = ()
    
    def __setstate__(self, state: dict) -> None:
        if isinstance(state, dict):
            self.__dict__.update(state)


class FakeSLBlock:
    """Screen Language block."""
    def __init__(self):
        self.children: List[Any] = []
        self.keyword: List[tuple] = []
        self.location: tuple = ()
    
    def __setstate__(self, state: dict) -> None:
        if isinstance(state, dict):
            self.__dict__.update(state)


class FakeSLUse:
    """Screen Language use statement."""
    def __init__(self):
        self.target: str = ""
        self.args: Optional[Any] = None
        self.block: Optional[Any] = None
        self.location: tuple = ()
    
    def __setstate__(self, state: dict) -> None:
        if isinstance(state, dict):
            self.__dict__.update(state)


class FakeSLPython:
    """Screen Language python block."""
    def __init__(self):
        self.code: Optional[Any] = None
        self.location: tuple = ()
    
    def __setstate__(self, state: dict) -> None:
        if isinstance(state, dict):
            self.__dict__.update(state)


class FakeSLDefault:
    """Screen Language default statement."""
    def __init__(self):
        self.variable: str = ""
        self.expression: str = ""
        self.location: tuple = ()
    
    def __setstate__(self, state: dict) -> None:
        if isinstance(state, dict):
            self.__dict__.update(state)

# SL2 (Screen Language 2) fake classes for Ren'Py 8.x
class FakeSLDrag(FakeASTBase):
    """Screen Language drag statement (new in 8.x)."""
    def __init__(self):
        super().__init__()
        self.children: List[Any] = []
        self.keyword: List[tuple] = []
    
    def __setstate__(self, state: dict) -> None:
        if isinstance(state, dict):
            self.__dict__.update(state)


class FakeSLOnEvent(FakeASTBase):
    """Screen Language on event handler."""
    def __init__(self):
        super().__init__()
        self.event: str = ""
        self.action: Any = None
    
    def __setstate__(self, state: dict) -> None:
        if isinstance(state, dict):
            self.__dict__.update(state)


class FakeSLBar(FakeASTBase):
    """Screen Language bar/vbar with value."""
    def __init__(self):
        super().__init__()
        self.positional: List[Any] = []
        self.keyword: List[tuple] = []
    
    def __setstate__(self, state: dict) -> None:
        if isinstance(state, dict):
            self.__dict__.update(state)
# Revertable containers from renpy.revertable / renpy.python
class FakeRevertableList(list):
    """Ren'Py revertable list."""
    pass


class FakeRevertableDict(dict):
    """Ren'Py revertable dict."""
    pass


class FakeTestcase(FakeASTBase):
    """Represents a testcase statement (Ren'Py 8.x)."""
    def __init__(self):
        super().__init__()
        self.label: str = ""
        self.test: str = ""
        self.block: List[Any] = []
        self.description: Optional[str] = None


class FakeSLDrag(FakeSLDisplayable):
    """Screen Language drag statement."""
    def __init__(self):
        super().__init__()
        self.drag_name: str = ""
        self.draggable: Optional[Any] = None
        self.droppable: Optional[Any] = None
        self.dragged: Optional[Any] = None
        self.dropped: Optional[Any] = None


class FakeSLBar(FakeSLDisplayable):
    """Screen Language Bar and VBar."""
    def __init__(self):
        super().__init__()
        self.value: Optional[Any] = None
        self.range: Optional[Any] = None


class FakeOrderedDict(dict):
    """Tolerant OrderedDict replacement for unpickling.

    Some pickles encode ordered mappings as a sequence of pairs or slightly
    different structures. The standard `dict.update()` can raise
    "too many values to unpack (expected 2)" when an item tuple contains
    more than two elements. This class accepts several state shapes and
    only consumes the first two elements of each pair when present.
    """
    def __setstate__(self, state):
        """
        Robust state handling for Ren'Py 8.x + Python 3.
        Supports:
        - Dict state
        - Tuple of (dict,)
        - List of pairs [(k,v), (k,v)]
        - Flat list [k, v, k, v] (New Ren'Py serialization)
        """
        try:
            # 1. Standard Dict
            if isinstance(state, dict):
                self.update(state)
                return

            # 2. Tuple Wrapper (state,)
            if isinstance(state, tuple) and len(state) == 1 and isinstance(state[0], (list, dict)):
                self.__setstate__(state[0])
                return

            # 3. List / Tuple of items
            if isinstance(state, (list, tuple)):
                # Case A: Pairs [(k,v), (k,v)]
                if all(isinstance(el, (list, tuple)) and len(el) == 2 for el in state):
                    for k, v in state:
                        self[k] = v
                    return
                
                # Case B: Flat list [k, v, k, v] (Ren'Py 8.2+ Optimization)
                if len(state) >= 2 and len(state) % 2 == 0:
                    # Heuristic: Check if odd elements look like keys (strings/ints)
                    # This is slightly risky but necessary for flat lists.
                    try:
                        for i in range(0, len(state), 2):
                            self[state[i]] = state[i+1]
                        return
                    except TypeError:
                        pass # Fallback if unhashable

                # Case C: Mixed/Legacy (try finding dicts)
                for part in state:
                    if isinstance(part, dict):
                        self.update(part)
        except Exception:
            pass


class FakeRevertableSet(set):
    """Ren'Py revertable set."""
    def __setstate__(self, state):
        if isinstance(state, tuple):
            self.update(state[0].keys() if isinstance(state[0], dict) else state[0])
        else:
            self.update(state)


class FakeSentinel:
    """Ren'Py sentinel object."""
    def __init__(self, name: str = ""):
        self.name = name


# ============================================================================
# CUSTOM UNPICKLER
# ============================================================================


class RenpyUnpickler(pickle.Unpickler):
    """
    Custom unpickler that redirects Ren'Py classes to our fake implementations.
    """
    
    # Mapping of Ren'Py class paths to our fake classes
    CLASS_MAP = {
        # Core AST nodes (renpy.ast)
        ("renpy.ast", "Say"): FakeSay,
        ("renpy.ast", "TranslateSay"): FakeTranslateSay,  # New: combined translate+say
        ("renpy.ast", "Menu"): FakeMenu,
        ("renpy.ast", "Label"): FakeLabel,
        ("renpy.ast", "Init"): FakeInit,
        ("renpy.ast", "Python"): FakePython,
        ("renpy.ast", "EarlyPython"): FakeEarlyPython,
        ("renpy.ast", "PyCode"): FakePyCode,
        ("renpy.ast", "Screen"): FakeScreen,
        ("renpy.ast", "Translate"): FakeTranslate,
        ("renpy.ast", "TranslateString"): FakeTranslateString,
        ("renpy.ast", "TranslateBlock"): FakeTranslateBlock,
        ("renpy.ast", "TranslateEarlyBlock"): FakeTranslateBlock,
        ("renpy.ast", "TranslatePython"): FakeTranslateBlock,
        ("renpy.ast", "EndTranslate"): FakePass,
        ("renpy.ast", "UserStatement"): FakeUserStatement,
        ("renpy.ast", "PostUserStatement"): FakePostUserStatement,  # New
        ("renpy.ast", "If"): FakeIf,
        ("renpy.ast", "While"): FakeWhile,
        ("renpy.ast", "Define"): FakeDefine,
        ("renpy.ast", "Default"): FakeDefault,
        ("renpy.ast", "Image"): FakeImage,
        ("renpy.ast", "Show"): FakeShow,
        ("renpy.ast", "Scene"): FakeScene,
        ("renpy.ast", "Hide"): FakeHide,
        ("renpy.ast", "With"): FakeWith,
        ("renpy.ast", "Call"): FakeCall,
        ("renpy.ast", "Jump"): FakeJump,
        ("renpy.ast", "Return"): FakeReturn,
        ("renpy.ast", "Pass"): FakePass,
        ("renpy.ast", "Transform"): FakeGeneric,
        ("renpy.ast", "Style"): FakeGeneric,
        ("renpy.ast", "Testcase"): FakeTestcase,
        ("renpy.ast", "Camera"): FakeGeneric,
        ("renpy.ast", "ShowLayer"): FakeGeneric,
        ("renpy.ast", "RPY"): FakeGeneric,
        ("renpy.ast", "Node"): FakeNode,  # Base node
        
        # PyExpr locations
        ("renpy.ast", "PyExpr"): FakePyExpr,
        ("renpy.astsupport", "PyExpr"): FakePyExpr,
        
        # Parameter and Argument info
        ("renpy.ast", "ArgumentInfo"): FakeArgumentInfo,
        ("renpy.parameter", "ArgumentInfo"): FakeArgumentInfo,
        ("renpy.parameter", "ParameterInfo"): FakeParameterInfo,
        ("renpy.ast", "ParameterInfo"): FakeParameterInfo,
        ("renpy.parameter", "Parameter"): FakeGeneric,
        ("renpy.parameter", "Signature"): FakeGeneric,
        
        # New Ren'Py 8.5.2 Nodes
        ("renpy.ast", "Bubble"): FakeBubble,
        
        # ATL (Animation and Transformation Language)
        ("renpy.atl", "RawBlock"): FakeRawBlock,
        ("renpy.atl", "RawMultipurpose"): FakeGeneric,
        ("renpy.atl", "RawChild"): FakeGeneric,
        ("renpy.atl", "RawChoice"): FakeGeneric,
        ("renpy.atl", "RawParallel"): FakeGeneric,
        ("renpy.atl", "RawRepeat"): FakeGeneric,
        ("renpy.atl", "RawTime"): FakeGeneric,
        ("renpy.atl", "RawOn"): FakeGeneric,
        ("renpy.atl", "RawEvent"): FakeGeneric,
        ("renpy.atl", "RawFunction"): FakeGeneric,
        ("renpy.atl", "RawContainsExpr"): FakeGeneric,
        
        # Screen Language 2 (renpy.sl2.slast)
        ("renpy.sl2.slast", "SLScreen"): FakeSLScreen,
        ("renpy.sl2.slast", "SLDisplayable"): FakeSLDisplayable,
        ("renpy.sl2.slast", "SLIf"): FakeSLIf,
        ("renpy.sl2.slast", "SLShowIf"): FakeSLIf,
        ("renpy.sl2.slast", "SLFor"): FakeSLFor,
        ("renpy.sl2.slast", "SLBlock"): FakeSLBlock,
        ("renpy.sl2.slast", "SLUse"): FakeSLUse,
        ("renpy.sl2.slast", "SLPython"): FakeSLPython,
        ("renpy.sl2.slast", "SLDefault"): FakeSLDefault,
        ("renpy.sl2.slast", "SLDrag"): FakeSLDrag,
        ("renpy.sl2.slast", "SLOnEvent"): FakeSLOnEvent,
        ("renpy.sl2.slast", "SLBar"): FakeSLBar,
        ("renpy.sl2.slast", "SLVBar"): FakeSLBar, # VBar shares structure with Bar
        ("renpy.sl2.slast", "SLCanvas"): FakeGeneric, # Usually custom, map to generic
        ("renpy.sl2.slast", "SLPass"): FakeGeneric,
        ("renpy.sl2.slast", "SLBreak"): FakeGeneric,
        ("renpy.sl2.slast", "SLContinue"): FakeGeneric,
        ("renpy.sl2.slast", "SLTransclude"): FakeGeneric,
        ("renpy.sl2.slast", "SLNull"): FakeGeneric,
        ("renpy.sl2.slast", "SLUseTransform"): FakeGeneric,
        
        # Ren'Py 8.x: Case-sensitive variant (lowercase 'b')
        ("renpy.sl2.slast", "SLVbar"): FakeSLBar,
        ("renpy.ast", "EarlyStatement"): FakeGeneric,
        ("renpy.ast", "RPYBlock"): FakeGeneric,
        
        # Revertable containers
        ("renpy.revertable", "RevertableList"): FakeRevertableList,
        ("renpy.revertable", "RevertableDict"): FakeRevertableDict,
        ("renpy.revertable", "RevertableSet"): FakeRevertableSet,
        ("renpy.revertable", "RevertableObject"): FakeGeneric,
        ("renpy.python", "RevertableList"): FakeRevertableList,
        ("renpy.python", "RevertableDict"): FakeRevertableDict,
        ("renpy.python", "RevertableSet"): FakeRevertableSet,
        ("renpy.python", "RevertableObject"): FakeGeneric,
        
        # CSlots support (Ren'Py 8.x+)
        ("renpy.cslots", "Object"): FakeGeneric,
        
        # Character and other display
        ("renpy.character", "ADVCharacter"): FakeGeneric,
        ("renpy.character", "Character"): FakeGeneric,
        
        # Lexer/Parser support
        ("renpy.lexer", "SubParse"): FakeGeneric,
        
        # Audio
        ("renpy.audio.audio", "AudioData"): FakeGeneric,
        ("renpy.audio.music", "MusicContext"): FakeGeneric,
        
        # Display
        ("renpy.display.transform", "ATLTransform"): FakeATLTransformBase,
        ("renpy.display.motion", "ATLTransform"): FakeATLTransformBase,
        
        # Object/Other
        ("renpy.object", "Sentinel"): FakeSentinel,
        ("renpy.object", "Object"): FakeGeneric,
        
        # Store
        ("renpy.store", "object"): FakeGeneric,
        ("store", "object"): FakeGeneric,
        
        # Python 2 compatibility (fix_imports issue)
        ("__builtin__", "set"): set,
        ("__builtin__", "frozenset"): frozenset,
        
        # Collections
        ("collections", "OrderedDict"): FakeOrderedDict,
        ("collections", "defaultdict"): collections.defaultdict,

        # Actions (UI/Store)
        ("renpy.ui", "Confirm"): FakeConfirm,
        ("renpy.store", "Confirm"): FakeConfirm,
        ("store", "Confirm"): FakeConfirm,
        
        ("renpy.ui", "Notify"): FakeNotify,
        ("renpy.store", "Notify"): FakeNotify,
        ("store", "Notify"): FakeNotify,

        ("renpy.ui", "Tooltip"): FakeTooltip,
        ("renpy.store", "Tooltip"): FakeTooltip,
        ("store", "Tooltip"): FakeTooltip,

        ("renpy.ui", "Help"): FakeHelp,
        ("renpy.store", "Help"): FakeHelp,
        ("store", "Help"): FakeHelp,
    }

    # Minimal allowlist of harmless builtins needed for pickle internals
    SAFE_BUILTINS = {
        ("builtins", "set"): set,
        ("builtins", "frozenset"): frozenset,
        ("builtins", "dict"): dict,
        ("builtins", "list"): list,
        ("builtins", "tuple"): tuple,
        ("builtins", "str"): str,
        ("builtins", "int"): int,
        ("builtins", "float"): float,
        ("builtins", "bool"): bool,
        ("__builtin__", "set"): set,
        ("__builtin__", "frozenset"): frozenset,
        ("__builtin__", "dict"): dict,
        ("__builtin__", "list"): list,
        ("__builtin__", "tuple"): tuple,
        ("__builtin__", "str"): str,
        ("__builtin__", "unicode"): str,
        ("__builtin__", "int"): int,
        ("__builtin__", "long"): int,
        ("__builtin__", "float"): float,
        ("__builtin__", "bool"): bool,
    }
    
    def find_class(self, module: str, name: str) -> type:
        """Override to redirect Ren'Py classes to our fakes."""
        key = (module, name)
        
        if key in self.CLASS_MAP:
            return self.CLASS_MAP[key]
        
        # For unknown renpy classes, return generic handler
        if module.startswith("renpy."):
            logger.debug(f"Unknown Ren'Py class: {module}.{name}")
            return FakeGeneric

        # Allow a small set of harmless builtins used by pickle internals
        if key in self.SAFE_BUILTINS:
            return self.SAFE_BUILTINS[key]

        # Explicitly allow Python 2 compatibility names
        if module in ("__builtin__", "builtins") and name in ("object",):
            return object
        
        # For store classes (game-defined)
        if module.startswith("store.") or module == "store":
            logger.debug(f"Store class: {module}.{name}")
            return FakeGeneric
        
        # Allow Python AST nodes (_ast module) - used in .rpymc screen cache files
        # AST nodes are safe data structures used by Ren'Py's screen language compiler
        if module == "_ast":
            import _ast
            if hasattr(_ast, name):
                return getattr(_ast, name)
            logger.debug(f"Unknown AST node: {name}")
            return FakeGeneric
        
        # Also allow 'ast' module (alternative import path)
        if module == "ast":
            import ast
            if hasattr(ast, name):
                return getattr(ast, name)
            logger.debug(f"Unknown ast node: {name}")
            return FakeGeneric
        
        # Block everything else to avoid executing arbitrary globals during unpickle
        raise pickle.UnpicklingError(f"Disallowed global: {module}.{name}")


# ============================================================================
# RPYC FILE READER
# ============================================================================


@dataclass
class RpycHeader:
    """Header information from .rpyc file."""
    version: int  # 1 or 2
    slot_count: int
    slots: Dict[int, Tuple[int, int]]  # slot_id -> (start, length)


class RpycReadError(Exception):
    """Error reading .rpyc file."""
    pass


def read_rpyc_header(data: bytes) -> RpycHeader:
    """
    Parse .rpyc file header.
    
    RPYC v2 format:
    - 10 bytes: "RENPY RPC2"
    - Repeated: 12 bytes (slot_id, start, length) as little-endian uint32
    - End when slot_id == 0
    
    RPYC v1 format:
    - Just zlib-compressed pickle data (no header)
    """
    # Eğer RPC2 değilse hemen pes etme, belki de RPC3'tür ama yapısı benzerdir.
    if data.startswith(b"RENPY RPC"):
        # RPC2 veya RPC3 fark etmeksizin işlemeyi dene
        pass
    elif not data.startswith(b"RENPY RPC2"):
        # V1 (Sıkıştırılmış pickle) varsayımı
        return RpycHeader(version=1, slot_count=0, slots={})
    
    # RPYC v2
    position = 10
    slots = {}
    
    while position + 12 <= len(data):
        slot_id, start, length = struct.unpack("<III", data[position:position + 12])
        
        if slot_id == 0:
            break
        
        slots[slot_id] = (start, length)
        position += 12
    
    return RpycHeader(version=2, slot_count=len(slots), slots=slots)


def read_rpyc_file(file_path: Union[str, Path]) -> List[Any]:
    """
    Read .rpyc file and return AST nodes.
    
    Args:
        file_path: Path to .rpyc file
        
    Returns:
        List of AST nodes
        
    Raises:
        RpycReadError: If file cannot be read/parsed
    """
    file_path = Path(file_path)
    
    if not file_path.exists():
        raise RpycReadError(f"File not found: {file_path}")
    
    if file_path.suffix.lower() not in ('.rpyc', '.rpymc'):
        raise RpycReadError(f"Not an RPYC file: {file_path}")
    
    try:
        with open(file_path, 'rb') as f:
            data = f.read()
    except IOError as e:
        raise RpycReadError(f"Cannot read file: {e}")
    
    header = read_rpyc_header(data)
    
    # v2.7.2: Obfuscation detection — check for non-standard magic numbers
    if header.version == 2 and not data.startswith(b"RENPY RPC2"):
        magic_prefix = data[:10]
        logger.warning(
            f"Non-standard RPYC magic number detected in {file_path}: {magic_prefix!r}. "
            f"This file may be obfuscated or use a custom format."
        )
    
    # Get the compressed data
    if header.version == 1:
        compressed = data
    else:
        # v2.7.2: Slot fallback — try slot 1 first, then slot 2 if unavailable
        slot_id = None
        for candidate_slot in (1, 2):
            if candidate_slot in header.slots:
                slot_id = candidate_slot
                break
        
        if slot_id is None:
            raise RpycReadError(
                f"No data slot found in RPYC v2 file: {file_path}. "
                f"Available slots: {list(header.slots.keys())}. "
                f"The file may be obfuscated or corrupted."
            )
        
        start, length = header.slots[slot_id]
        compressed = data[start:start + length]
    
    # Decompress
    try:
        decompressed = zlib.decompress(compressed)
    except zlib.error as e:
        # v2.7.2: If v2 decompression fails, try treating the entire file as v1 (raw zlib)
        if header.version == 2:
            logger.warning(f"V2 slot decompression failed for {file_path}, retrying as raw zlib (v1 fallback)")
            try:
                decompressed = zlib.decompress(data)
            except zlib.error:
                raise RpycReadError(
                    f"Decompression failed: {e}. "
                    f"The file may be obfuscated or use custom compression."
                )
        else:
            raise RpycReadError(f"Decompression failed: {e}")
    
    # Unpickle using our custom unpickler
    # v2.7.2: Try multiple encoding strategies for Python 2/3 compatibility
    unpickle_errors = []
    for encoding in ('ASCII', 'latin-1', 'bytes'):
        try:
            unpickler = RenpyUnpickler(io.BytesIO(decompressed), encoding=encoding)
            result = unpickler.load()

            # Result is typically (data, stmts) tuple
            if isinstance(result, tuple) and len(result) >= 2:
                return result[1]  # Return statements

            return result if isinstance(result, list) else [result]

        except (UnicodeDecodeError, UnicodeError) as e:
            # Encoding mismatch — try next encoding
            unpickle_errors.append((encoding, str(e)))
            continue
        except Exception as e:
            # Non-encoding error — collect and break
            unpickle_errors.append((encoding, str(e)))
            break
    
    # All attempts failed — produce detailed diagnostics
    tb = traceback.format_exc()
    try:
        slot_info = getattr(header, 'slots', None)
    except Exception:
        slot_info = None

    try:
        snippet = decompressed[:512]
        snippet_hex = binascii.hexlify(snippet).decode('ascii')
    except Exception:
        snippet_hex = repr(decompressed[:200])

    error_details = "; ".join(f"[{enc}] {err}" for enc, err in unpickle_errors)
    msg = (
        f"Unpickle failed for {file_path}.\n"
        f"Attempted encodings: {error_details}\n"
        f"Header slots: {slot_info}\n"
        f"Traceback:\n{tb}\n"
        f"Decompressed (first 512 bytes, hex): {snippet_hex}"
    )

    try:
        logger.error(msg)
    except Exception:
        pass

    try:
        sys.stderr.write(msg + "\n")
    except Exception:
        try:
            sys.stderr.write(msg.encode('utf-8', errors='replace').decode('utf-8', errors='replace') + "\n")
        except Exception:
            pass

    raise RpycReadError(
        f"Unpickle failed after trying encodings {[e for e,_ in unpickle_errors]}. "
        f"See application logs for details."
    )


# ============================================================================
# AST TEXT EXTRACTOR
# ============================================================================


@dataclass
class ExtractedText:
    """Represents text extracted from AST."""
    text: str
    line_number: int
    source_file: str
    text_type: str  # 'dialogue', 'menu', 'ui', 'string', etc.
    character: str = ""
    context: str = ""
    placeholder_map: Dict[str, str] = None
    context_path: List[str] = None
    node_type: str = ""
    confidence: float = 0.0
    confidence_band: str = "candidate"
    # Real Ren'Py translate identifier baked into the compiled .rpyc (Translate/
    # TranslateSay node), when available. When present this is the exact id
    # Ren'Py's own runtime lookup_translate() will use — no hash guessing needed.
    identifier: str = ""


class ASTTextExtractor:
    """
    Extracts translatable text from Ren'Py AST nodes.
    """
    
    def __init__(self, config_manager=None):
        self.extracted: List[ExtractedText] = []
        # Map text -> (context, ExtractedText) to handle deduplication and prefer more specific
        self.seen_map: Dict[tuple, ExtractedText] = {}
        self.current_file: str = ""
        self.config_manager = config_manager
        # Copy whitelist from parser for context-aware extraction
        self.DATA_KEY_WHITELIST = DATA_KEY_WHITELIST
        # Instantiate parser once for performance (placeholder preservation, etc.)
        self.parser = RenPyParser(config_manager)
        
        # Filter settings
        self.translate_character_names = False
        if self.config_manager is not None and not isinstance(self.config_manager, bool):
             self.translate_character_names = getattr(self.config_manager.translation_settings, 'translate_character_names', False)

    def _is_deep_feature_enabled(self, feature: str = None) -> bool:
        """
        V2.7.1: Check if a deep extraction feature is enabled via config toggles.
        Returns True when config_manager is None (backward compatibility).
        """
        if self.config_manager is None:
            return True
        ts = getattr(self.config_manager, 'translation_settings', None)
        if ts is None:
            return True
        if not getattr(ts, 'enable_deep_extraction', True):
            return False
        if feature:
            return getattr(ts, feature, True)
        return True
    
    def extract_from_file(self, file_path: Union[str, Path]) -> List[ExtractedText]:
        """
        Extract all translatable text from an .rpyc file.
        
        Args:
            file_path: Path to .rpyc file
            
        Returns:
            List of ExtractedText objects
        """
        self.extracted = []
        self.seen_texts = set()
        self.seen_map: Dict[tuple, ExtractedText] = {}
        self.current_file = str(file_path)
        
        try:
            ast_nodes = read_rpyc_file(file_path)
            self._walk_nodes(ast_nodes)
        except RpycReadError as e:
            logger.exception(f"Failed to read {file_path}: {e}")
        
        return self.extracted
    
    def _add_text(
        self,
        text: str,
        line_number: int,
        text_type: str,
        character: str = "",
        context: str = "",
        placeholder_map: Dict[str, str] = None,
        node_type: str = "",
        identifier: str = "",
    ) -> None:
        """Add extracted text if it's meaningful."""
        if not text or not text.strip():
            return

        visible_text = self.parser._normalize_inline_text_candidate(text)
        analysis_text = visible_text if visible_text else text
            
        # Detect NVL mode: check if character is nvl-related
        nvl_chars = {'narrator_nvl', 'nvl', 'side_nvl', 'nvl_narrator'}
        if character and character.lower() in nvl_chars:
            text_type = 'nvl_dialogue'

        # Duplicate handling: if we already have this text, prefer the one with variable context or data_string
        key = (text, context, node_type or text_type)
        existing = self.seen_map.get(key)
        # If existing has same (text, context) skip
        if existing:
            # If existing has no context but new context exists, replace existing
            if context and not existing.context:
                # Remove existing from list
                try:
                    self.extracted.remove(existing)
                except ValueError:
                    pass
                # continue to add new
            else:
                return
        
        # Skip technical strings using the advanced parser logic
        if not self.parser.is_meaningful_text(analysis_text):
            return
        
        # Additional context-aware technical filtering
        if self._is_technical_string(analysis_text, context):
            return
        
        # Apply user-configurable text type filters (translate_dialogue, translate_ui, etc.)
        if not self.parser._should_translate_text(text, text_type):
            return

        confidence = score_extraction_confidence(
            analysis_text,
            text_type,
            context,
            [context] if context else [],
            character=character,
        )
        minimum_confidence = resolve_minimum_extraction_confidence(self.config_manager, default=0.0)

        if confidence < minimum_confidence:
            return

        # store in seen_map
        context_path = []
        if context:
            context_path = [p for p in str(context).split('/') if p]
        self.seen_map[key] = ExtractedText(
            text=text,
            line_number=line_number,
            source_file=self.current_file,
            text_type=text_type,
            character=character,
            context=context,
            placeholder_map=placeholder_map or {},
            context_path=context_path,
            node_type=node_type or text_type,
            confidence=confidence,
            confidence_band=confidence_band(confidence),
            identifier=identifier or "",
        )
        self.extracted.append(self.seen_map[key])
        logger.info(f"[AST ENTRY] {self.current_file}:{line_number} [{node_type or text_type}] ctx={context_path} text={text}")

    def _context_requires_whitelist(self, context: str) -> bool:
        """Return True when context-based whitelist filtering should be enforced."""
        if not context:
            return False
        context_lower = context.lower()
        return (
            context_lower.startswith("rpyc_val:") or
            context_lower.startswith("variable:") or
            context_lower.startswith("data:")
        )
    
    def _is_technical_string(self, text: str, context: str = "") -> bool:
        """
        Additional context-dependent technical string checks.
        Optimized with Regex Pooling and Early Returns for v2.6.4.
        """
        text_strip = text.strip()
        
        # --- EARLY RETURNS (PERFORMANCE) ---
        if not text_strip:
            return True
            
        text_len = len(text_strip)
        
        # Very short text rules
        if text_len == 1:
            # Allow only if it looks like a valid single letter (e.g. 'I', 'a', Cyrillic)
            # Fast check using pre-compiled regex
            return not bool(_RE_HAS_LETTER.match(text_strip))
            
        # Pure numbers (integers or floats)
        if text_strip[0].isdigit() or text_strip[0] == '-':
            if _RE_PURE_NUMBER.match(text_strip):
                return True

        text_lower = text_strip.lower()
        context_lower = context.lower() if context else ""

        # --- BINARY/CORRUPTED STRING DETECTION (Pooled Regex) ---
        if '\ufffd' in text_strip: return True
        if _RE_PUA.search(text_strip): return True
        if _RE_CONTROL_CHARS.search(text_strip): return True
        
        # Heuristic: Short strings with absolutely no letters are suspicious context for translations
        # (unless they are punctuation which usually get skipped anyway)
        if text_len < 10 and not _RE_HAS_LETTER.search(text_strip):
            return True

        # Complex corruption checks (expensive, do only if suspicious)
        # Using ratio checks is expensive, do it only for medium-length strings
        if 5 < text_len < 50:
             # Unusual chars ratio
             strange_chars = len(_RE_NON_PRINTABLE_HIGH_RATIO.findall(text_strip))
             if strange_chars > text_len * 0.3:
                 return True
             
             # Low alpha content (Using ANY_LETTER instead of ASCII_LETTERS for Global Support)
             if text_len > 8:
                 # Original ASCII check killed Russian/Chinese text. Now we check for ANY valid letter.
                 alpha_count = len(_RE_ANY_LETTER.findall(text_strip))
                 # If text is long but has very few actual letters (e.g. mostly symbols/numbers), kill it.
                 if alpha_count < text_len * 0.2:
                     return True

        if 3 <= text_len <= 15:
            unusual_chars_count = len(_RE_UNUSUAL_SHORT.findall(text_strip))
            # Relaxed check: Allow non-ASCII if they are valid letters in supported languages
            if unusual_chars_count >= 1 and len(_RE_ANY_LETTER.findall(text_strip)) <= 1:
                return True
        # --- END BINARY/CORRUPTED ---

        # Common file extensions
        # Fast suffix check
        if '.' in text_strip and text_len > 4:
            if text_lower.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.ico',
                                    '.mp3', '.ogg', '.wav', '.flac', '.aac', '.m4a',
                                    '.mp4', '.webm', '.avi', '.mkv', '.mov',
                                    '.ttf', '.otf', '.rpy', '.rpyc', '.json')):
                return True

        # Path prefixes (case-insensitive for Linux)
        if text_lower.startswith(('images/', 'audio/', 'gui/', 'fonts/', 'music/', 'sounds/',
                                   'video/', 'videos/', 'screens/', 'script/', 'game/', 'tl/',
                                   'backgrounds/', 'sfx/', 'bgm/', 'cg/', 'bg/', 'movies/', 'sound/')):
            return True

        # Color codes (Hex)
        if text_strip.startswith('#') and _RE_COLOR_HEX.match(text_strip):
            return True

        # Snake_case identifiers (technical_variable_name)
        # Only check if it looks like a variable (no spaces)
        if ' ' not in text_strip and '_' in text_strip:
            if _RE_SNAKE_CASE.match(text_strip):
                return True
        
        # Strict Path Check (New v2.6.4)
        if '/' in text_strip and ' ' not in text_strip:
            if _RE_FILE_PATH_STRICT.match(text_strip):
                return True

        # Strict Variable Name Check (New v2.6.4)
        if ' ' not in text_strip and text_strip.islower() and '_' in text_strip:
             if _RE_STRICT_SNAKE_CASE.match(text_strip):
                 # Variables usually don't have punctuation except specific ones
                 return True

        # Check against the whitelist (context-based)
        if context and self._context_requires_whitelist(context_lower) and not any(key in context_lower for key in DATA_KEY_WHITELIST):
            return True
        
        # Ren'Py internal identifiers
        if text_strip.startswith('renpy.') or ' renpy.' in text_strip:
            return True

        # --- PYTHON CODE DETECTION (Pooled) ---
        if _RE_PYTHON_CODE.search(text_strip):
            return True
        
        # --- STRING CONCATENATION ---
        if '+' in text_strip:
             if len(text_strip) < 60 and _RE_STR_CONCAT.search(text_strip):
                 return True
             if len(text_strip) < 40 and _RE_ATTR_CONCAT.search(text_strip):
                 return True
             if len(text_strip) < 80 and _RE_FILE_PATH_VAR.search(text_strip):
                 return True

        # --- PYTHON BUILTINS ---
        if '(' in text_strip and text_len < 80 and ' ' not in text_strip:
             if _RE_PYTHON_BUILTINS.search(text_strip):
                 return True
        
        return False

    def _extract_string_content(self, quoted_string: str) -> str:
        """Helper to clean quotes and unescape characters.
        Supports optional Python string prefixes like f, r, b, u, fr, rf, etc.
        """
        if not quoted_string:
            return ''
        import re
        m = re.match(r"^(?P<prefix>[rRuUbBfF]{,2})?(?P<quoted>\"\"\"[\s\S]*?\"\"\"|\'\'\'[\s\S]*?\'\'\'|\"(?:[^\"\\]|\\.)*\"|\'(?:[^'\\]|\\.)*\')$", quoted_string, flags=re.S)
        if m:
            content_raw = m.group('quoted')
            if content_raw.startswith('"""') and content_raw.endswith('"""'):
                content = content_raw[3:-3]
            elif content_raw.startswith("'''") and content_raw.endswith("'''"):
                content = content_raw[3:-3]
            elif content_raw.startswith('"') and content_raw.endswith('"'):
                content = content_raw[1:-1]
            elif content_raw.startswith("'") and content_raw.endswith("'"):
                content = content_raw[1:-1]
            else:
                content = content_raw
        else:
            content = quoted_string

        # Unescape standard sequences
        content = content.replace('\"', '"').replace("\\'", "'")
        content = content.replace('\\n', '\n').replace('\\t', '\t')
        return content
    
    def _walk_nodes(self, nodes: List[Any], context: str = "", identifier: str = "") -> None:
        """Recursively walk AST nodes and extract text.

        `identifier` carries the real Ren'Py translate id of the enclosing
        Translate block (default-language only), so the contained Say node
        can be tagged with it instead of a guessed hash.
        """
        # Safety: Catch recursion depth if AST is malformed or excessively deep
        try:
            if not isinstance(nodes, (list, tuple)):
                nodes = [nodes]
            
            for node in nodes:
                self._process_node(node, context, identifier=identifier)
        except RecursionError:
            pass # Stop processing this branch deeply to prevent crash

    def _extract_from_code_obj(self, code_obj: Any, line_number: int, var_name: str = "") -> None:
        """Extract strings from a code-like object using AST parsing and fallback to Regex.
        
        Args:
            code_obj: The code object to extract from
            line_number: Source line number
            var_name: Optional variable name (from FakeDefine/FakeDefault) for smart filtering
        """
        if code_obj is None:
            return
        
        # V2.7.1: Smart variable filtering — skip non-translatable variables early
        if var_name:
            classification = _deep_var_analyzer.classify(var_name)
            if classification == "non_translatable":
                return  # Skip entirely
            
        code = ""
        if hasattr(code_obj, 'source'):
            code = code_obj.source
        elif isinstance(code_obj, FakePyExpr):
            code = str(code_obj)
        elif isinstance(code_obj, str):
            code = code_obj
            
        if not code:
            return

        # Phase 5: Python AST Parsing for RPYC code blocks
        # This is much more accurate than Regex for Python code
        try:
            # Remove common indentation to prevent SyntaxError
            import textwrap
            dedented_code = textwrap.dedent(code)
            
            tree = ast.parse(dedented_code)
            
            for node in ast.walk(tree):
                # String constants (Python 3.8+ and older)
                val = None
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    val = node.value
                elif hasattr(ast, 'Str') and isinstance(node, ast.Str):
                    val = node.s
                
                if val:
                    # Extraction Rules for naked strings:
                    # Naked strings in Python code are often technical IDs (pept, nifacecream).
                    # We only extract them if they look like real human-readable text.
                    
                    val_strip = val.strip()
                    # 1. Has spaces -> Likely a sentence or phrase
                    if ' ' in val_strip:
                        self._add_text(val, line_number, 'python_ast', context='python_naked')
                    # 2. Starts with Uppercase and meaningful -> Potential UI label or Name
                    elif val_strip and val_strip[0].isupper() and len(val_strip) > 2:
                        if self.parser.is_meaningful_text(val):
                            self._add_text(val, line_number, 'python_ast', context='python_naked')
                    # 3. Else: skip likely technical IDs (pept, pedom, etc)
                    # Note: _() and renpy.say() are handled separately below by Call node processing
                
                # Translatable calls: _("text"), __("text"), renpy.say(...)
                if isinstance(node, ast.Call):
                    func_name = ""
                    if isinstance(node.func, ast.Name):
                        func_name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        # Handle renpy.say, renpy.notify
                        if hasattr(node.func.value, 'id') and node.func.value.id == 'renpy':
                            func_name = f"renpy.{node.func.attr}"

                    
                    # Define function groups based on settings
                    target_funcs = {'_', '__', 'Tr', 'tr', 'renpy.say', 'renpy.notify', 'Notify'}
                                    
                    # Add character definitions only if enabled
                    if getattr(self, 'translate_character_names', True):
                         target_funcs.update({'Character', 'ADVCharacter', 'NVLCharacter', 'DynamicCharacter'})

                    if func_name in target_funcs:
                        for arg in node.args:
                            arg_val = None
                            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                                arg_val = arg.value
                            elif hasattr(ast, 'Str') and isinstance(arg, ast.Str):
                                arg_val = arg.s
                            
                            if arg_val:
                                self._add_text(arg_val, line_number, 'call_arg', context=func_name)

                # Enhanced Data Structure Crawling (New v2.6.4)
                # Catch strings inside Lists ["Item 1", "Item 2"] and Dicts {"name": "Hero"}
                elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                    for elt in node.elts:
                        val = None
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            val = elt.value
                        elif hasattr(ast, 'Str') and isinstance(elt, ast.Str):
                            val = elt.s
                            
                        # Strict filtering for lists (high risk of assets/IDs)
                        if val and len(val) > 2:
                            # Must pass strict checks: no paths, no technical IDs
                            if not self.parser.is_technical_string(val) and self.parser.is_meaningful_text(val):
                                 self._add_text(val, line_number, 'python_list', context='list_item')

                elif isinstance(node, ast.Dict):
                    # Only check values, keys are usually technical identifiers
                    for val_node in node.values:
                        val = None
                        if isinstance(val_node, ast.Constant) and isinstance(val_node.value, str):
                            val = val_node.value
                        elif hasattr(ast, 'Str') and isinstance(val_node, ast.Str):
                            val = val_node.s
                            
                        if val and len(val) > 2:
                            if not self.parser.is_technical_string(val) and self.parser.is_meaningful_text(val):
                                 self._add_text(val, line_number, 'python_dict', context='dict_value')
                                
        except Exception:
            # Fallback to Regex if AST parsing fails (e.g. incomplete code fragments)
            self._extract_strings_from_code(code, line_number)

    def _extract_screen_text_value(self, value: str, line_number: int, context: str, node_type: str) -> None:
        """Extract text from a screen keyword/displayable value."""
        text = value.strip()
        if not text:
            return
        # If it's a quoted literal, extract directly.
        if (
            (text.startswith('"') and text.endswith('"')) or
            (text.startswith("'") and text.endswith("'")) or
            (text.startswith('"""') and text.endswith('"""')) or
            (text.startswith("'''") and text.endswith("'''"))
        ):
            text = self._extract_string_content(text)
            if text:
                self._add_text(text, line_number, 'ui', context=context, node_type=node_type)
            return
        # If it looks like an expression, defer to code parsing.
        if any(token in text for token in ("_(", "__(", "renpy.", "Text(", "[")):
            self._extract_strings_from_code(text, line_number)
            return
        # Otherwise treat as a literal label.
        self._add_text(text, line_number, 'ui', context=context, node_type=node_type)
    
    def _process_node(self, node: Any, context: str = "", identifier: str = "") -> None:
        """Process a single AST node."""
        if node is None:
            return
        
        node_type = type(node).__name__
        
        # TranslateSay (combined translate+say in newer Ren'Py)
        if isinstance(node, FakeTranslateSay):
            character = getattr(node, 'who', '') or ""
            what = getattr(node, 'what', '')
            # The node already carries the exact id Ren'Py's compiler assigned
            # (only meaningful for the default-language node, language is None).
            lang = getattr(node, 'language', None)
            real_id = (getattr(node, 'identifier', '') or '') if lang is None else ''
            if what and isinstance(what, str):
                self._add_text(
                    str(what),
                    getattr(node, 'linenumber', 0),
                    'dialogue',
                    character=str(character) if character else "",
                    context=f"translate:{getattr(node, 'identifier', '')}",
                    node_type=node_type,
                    identifier=real_id,
                )
        
        # Dialogue (Say statement)
        elif isinstance(node, FakeSay):
            character = getattr(node, 'who', '') or ""
            what = getattr(node, 'what', '')
            
            # Metadata optimization: what can be a FakePyExpr (subclass of str) or literal str
            if what and isinstance(what, str):
                self._add_text(
                    str(what),
                    getattr(node, 'linenumber', 0),
                    'dialogue',
                    character=str(character) if character else "",
                    context=context,
                    node_type=node_type,
                    identifier=identifier,
                )
            
            # Check arguments for additional text (e.g. what_prefix="...")
            args = getattr(node, 'arguments', None)
            if args:
                 # Flatten arguments structure to find strings
                 # FakeArgumentInfo or tuple/list
                 candidates = []
                 if isinstance(args, FakeArgumentInfo):
                     candidates.extend([a for arg_tuple in args.arguments for a in arg_tuple if isinstance(a, str)])
                 elif isinstance(args, (list, tuple)):
                     candidates.extend([a for a in args if isinstance(a, str)])
                 
                 for arg_text in candidates:
                     if arg_text and isinstance(arg_text, str) and not self._is_technical_string(arg_text, context="say_arg"):
                          self._add_text(
                            str(arg_text),
                            getattr(node, 'linenumber', 0),
                            'dialogue_arg',
                            character=str(character) if character else "",
                            context=f"{context}/arg",
                            node_type=node_type
                        )
        
        # Menu choices
        elif isinstance(node, FakeMenu):
            for item in getattr(node, 'items', []):
                if isinstance(item, (list, tuple)) and len(item) >= 1:
                    label = item[0]
                    if label and isinstance(label, str):
                        self._add_text(
                            label,
                            getattr(node, 'linenumber', 0),
                            'menu',
                            context=context,
                            node_type=node_type
                        )
                    # Process menu item block
                    if len(item) >= 3 and item[2]:
                        self._walk_nodes(item[2], f"{context}/menu_item")
        
        # Ren'Py 8.5+ Bubble (Speech Bubbles)
        elif isinstance(node, FakeBubble):
            character = getattr(node, 'who', '') or ""
            what = getattr(node, 'what', '')
            
            # 1. Main Dialogue
            if what and isinstance(what, str):
                self._add_text(
                    str(what),
                    getattr(node, 'linenumber', 0),
                    'bubble_dialogue', # Specialized type
                    character=str(character) if character else "",
                    context=context,
                    node_type=node_type
                )
            
            # 2. Bubble Properties (alt, tooltip, help)
            props = getattr(node, 'properties', None)
            if props and isinstance(props, dict):
                for key in ['alt', 'tooltip', 'help', 'caption']:
                    val = props.get(key)
                    if val and isinstance(val, str):
                         self._add_text(
                            val,
                            getattr(node, 'linenumber', 0),
                            f'bubble_prop_{key}',
                            context=f"{context}/bubble_prop",
                            node_type=node_type
                        )

        # Ren'Py 8.5+ Testcase
        elif isinstance(node, FakeTestcase):
            # Extract description if present
            desc = getattr(node, 'description', None)
            if desc and isinstance(desc, str):
                 self._add_text(
                    desc,
                    getattr(node, 'linenumber', 0),
                    'testcase_desc',
                    context=context,
                    node_type=node_type
                )
            
            # Recursively check the test block
            # Test blocks might contain standard Say nodes or other verifiable statements
            block = getattr(node, 'block', None)
            if block:
                # Use a specific context to track we are inside a test
                self._walk_nodes(block, f"{context}/testcase:{getattr(node, 'label', 'unknown')}")

        # Screen Language Drag
        elif isinstance(node, FakeSLDrag):
            # 1. Drag Name (if meaningful)
            dname = getattr(node, 'drag_name', None)
            if dname and isinstance(dname, str):
                # Only add if it's NOT a technical ID (e.g. looks like a title)
                if not self._is_technical_string(dname, context="drag_name"):
                     self._add_text(
                        dname,
                        getattr(node, 'linenumber', 0),
                        'ui_drag_name',
                        context=f"{context}/drag",
                        node_type=node_type
                    )

        # Label block
        elif isinstance(node, FakeLabel):
            label_name = getattr(node, 'name', '')
            new_context = f"label:{label_name}"
            if getattr(node, 'block', None):
                self._walk_nodes(node.block, new_context)
        
        # Init block
        elif isinstance(node, FakeInit):
            if getattr(node, 'block', None):
                self._walk_nodes(node.block, f"{context}/init")
        
        # If statement
        elif isinstance(node, FakeIf):
            for entry in getattr(node, 'entries', []):
                if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    if entry[1]:
                        self._walk_nodes(entry[1], context)
        
        # While loop
        elif isinstance(node, FakeWhile):
            if getattr(node, 'block', None):
                self._walk_nodes(node.block, context)
        
        # Python Code Block (New v2.6.4)
        elif isinstance(node, FakePython):
            code_obj = getattr(node, 'code', None)
            self._extract_from_code_obj(code_obj, getattr(node, 'linenumber', 0))

        # User Statement (New v2.6.4)
        elif isinstance(node, FakeUserStatement):
            line = getattr(node, 'line', '')
            if line:
                # User statements are unstructured, use loose extraction from the raw line
                # e.g. "chapter set 'Beginning'"
                self._extract_strings_from_code(line, getattr(node, 'linenumber', 0))
        
        # Translate block - extract both old and new
        elif isinstance(node, FakeTranslateString):
            if getattr(node, 'old', ''):
                self._add_text(
                    node.old,
                    getattr(node, 'linenumber', 0),
                    'string',
                    context='translate',
                    node_type=node_type
                )
        
        # Translate (dialogue) block
        elif isinstance(node, FakeTranslate):
            block = getattr(node, 'block', None)
            if block:
                lang = getattr(node, 'language', None)
                # Only the default-language block's id matches what the shipped
                # game will look up; translated-language blocks reuse that same id.
                real_id = (getattr(node, 'identifier', '') or '') if lang is None else ''
                self._walk_nodes(block, f"translate:{lang or 'None'}", identifier=real_id)

        # Translate block (style/python)
        elif isinstance(node, FakeTranslateBlock):
            block = getattr(node, 'block', None)
            if block:
                lang = getattr(node, 'language', None)
                self._walk_nodes(block, f"translate:{lang or 'None'}")
        
        # Screen
        elif isinstance(node, FakeScreen):
            screen_obj = getattr(node, 'screen', None)
            screen_name = getattr(node, 'name', getattr(screen_obj, 'name', 'unknown') if screen_obj else 'unknown')
            if screen_obj:
                self._process_screen_node(screen_obj, f"screen:{screen_name}")
        
        # Define statement - check for translatable strings
        elif isinstance(node, FakeDefine):
            if self._is_deep_feature_enabled('deep_extraction_bare_defines'):
                code = getattr(node, 'code', None)
                if code:
                    # V2.7.1: Smart variable filtering for bare define strings
                    var_name = getattr(node, 'varname', '')
                    self._extract_from_code_obj(code, getattr(node, 'linenumber', 0), var_name=var_name)

        # Default statement - check for translatable strings
        elif isinstance(node, FakeDefault):
            if self._is_deep_feature_enabled('deep_extraction_bare_defaults'):
                code = getattr(node, 'code', None)
                if code:
                    # V2.7.1: Smart variable filtering for bare default strings
                    var_name = getattr(node, 'varname', '')
                    self._extract_from_code_obj(code, getattr(node, 'linenumber', 0), var_name=var_name)
        
        # ATL / RawBlock
        elif isinstance(node, FakeRawBlock):
            body = getattr(node, 'code', None) or getattr(node, 'block', None) or getattr(node, 'string', None)
            if isinstance(body, str):
                self._extract_strings_from_code(body, getattr(node, 'linenumber', 0))

        # Show/Scene — descend into their ATL block (may contain Python with strings)
        elif isinstance(node, (FakeShow, FakeScene)):
            atl = getattr(node, 'atl', None)
            if atl is not None:
                self._process_node(atl, f"{context}:atl")

        # Generic block handling
        elif hasattr(node, 'block') and node.block:
            self._walk_nodes(node.block, context)

    def _extract_from_action(self, action: Any, line_number: int, context: str) -> None:
        """Extract text from Action objects (Confirm, Notify, etc.)."""
        if isinstance(action, (list, tuple)):
            for act in action:
                self._extract_from_action(act, line_number, context)
            return

        if isinstance(action, FakeConfirm):
            if hasattr(action, 'prompt') and action.prompt:
                self._add_text(action.prompt, line_number, 'ui_action', context=f"{context}:Confirm")
        elif isinstance(action, FakeNotify):
            if hasattr(action, 'message') and action.message:
                self._add_text(action.message, line_number, 'ui_action', context=f"{context}:Notify")
        elif isinstance(action, FakeHelp):
             if hasattr(action, 'help') and isinstance(action.help, str):
                 self._add_text(action.help, line_number, 'ui_action', context=f"{context}:Help")
        elif isinstance(action, FakeTooltip):
             if hasattr(action, 'value') and isinstance(action.value, str):
                 self._add_text(action.value, line_number, 'ui_action', context=f"{context}:Tooltip")
    
    def _process_screen_node(self, node: Any, context: str = "") -> None:
        """Process Screen Language nodes."""
        if node is None:
            return
        
        # SL2 Screen
        if isinstance(node, FakeSLScreen):
            # Process children
            for child in getattr(node, 'children', []):
                self._process_screen_node(child, context)
        
        # SL2 Displayable (text, textbutton, etc.)
        elif isinstance(node, FakeSLDisplayable):
            line_number = 0
            loc = getattr(node, 'location', None)
            if isinstance(loc, (list, tuple)) and len(loc) > 1 and isinstance(loc[1], int):
                line_number = loc[1]

            # Extract from displayable expression if present
            displayable = getattr(node, 'displayable', None)
            if isinstance(displayable, FakePyExpr) or hasattr(displayable, 'source'):
                self._extract_from_code_obj(displayable, line_number)
            # Check positional arguments for text
            for pos in getattr(node, 'positional', []):
                if isinstance(pos, str) and pos.strip():
                    self._extract_screen_text_value(pos, line_number, context, type(node).__name__)
                elif isinstance(pos, FakePyExpr) or hasattr(pos, 'source'):
                    self._extract_from_code_obj(pos, line_number)
            
            # Check keyword arguments for text-related properties
            for kw in getattr(node, 'keyword', []):
                if isinstance(kw, (list, tuple)) and len(kw) >= 2:
                    key, value = kw[0], kw[1]
                    if key in ('text', 'alt', 'tooltip', 'caption', 'title') and value:
                        if isinstance(value, str):
                            self._extract_screen_text_value(value, line_number, context, type(node).__name__)
                        elif isinstance(value, FakePyExpr) or hasattr(value, 'source'):
                            self._extract_from_code_obj(value, line_number)
                    
                    elif key == 'action':
                        self._extract_from_action(value, line_number, context)
            
            # Process children
            for child in getattr(node, 'children', []):
                self._process_screen_node(child, context)
        
        # SL2 If/ShowIf
        elif isinstance(node, FakeSLIf):
            for entry in getattr(node, 'entries', []):
                if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    self._process_screen_node(entry[1], context)
        
        # SL2 For
        elif isinstance(node, FakeSLFor):
            for child in getattr(node, 'children', []):
                self._process_screen_node(child, context)
        
        # SL2 Block
        elif isinstance(node, FakeSLBlock):
            for child in getattr(node, 'children', []):
                self._process_screen_node(child, context)

        # SL2 Use
        elif isinstance(node, FakeSLUse):
            block = getattr(node, 'block', None)
            if block:
                self._process_screen_node(block, context)

        # SL2 Python
        elif isinstance(node, FakeSLPython):
            line_number = 0
            loc = getattr(node, 'location', None)
            if isinstance(loc, (list, tuple)) and len(loc) > 1 and isinstance(loc[1], int):
                line_number = loc[1]
            self._extract_from_code_obj(getattr(node, 'code', None), line_number)

        # SL2 Default
        elif isinstance(node, FakeSLDefault):
            line_number = 0
            loc = getattr(node, 'location', None)
            if isinstance(loc, (list, tuple)) and len(loc) > 1 and isinstance(loc[1], int):
                line_number = loc[1]
            self._extract_from_code_obj(getattr(node, 'expression', None), line_number)

        # SL2 OnEvent — extract from its action (may contain Confirm/Notify/Tooltip)
        elif isinstance(node, FakeSLOnEvent):
            line_number = 0
            loc = getattr(node, 'location', None)
            if isinstance(loc, (list, tuple)) and len(loc) > 1 and isinstance(loc[1], int):
                line_number = loc[1]
            action = getattr(node, 'action', None)
            if action is not None:
                self._extract_from_action(action, line_number, context)
    
    def _extract_strings_from_code(self, code: str, line_number: int) -> None:
        """Extract string literals from Python code with enhanced pattern matching."""
        import re
        p = self.parser
        # Try AST-based parsing first — this is more robust for Python code
        try:
            if self._extract_strings_from_code_ast(code, line_number):
                return
        except Exception:
            pass
        
        # Match _("text") pattern - standard translation function
        translatable_pattern = r'_\s*\(\s*["\'](.+?)["\']\s*\)'
        for match in re.finditer(translatable_pattern, code):
            text = match.group(1)
            processed_text, placeholder_map = p.preserve_placeholders(text)
            self._add_text(processed_text, line_number, 'string', context='python/_', placeholder_map=placeholder_map)
        
        # Match __("text") pattern - double underscore translation
        double_under_pattern = r'__\s*\(\s*["\'](.+?)["\']\s*\)'
        for match in re.finditer(double_under_pattern, code):
            text = match.group(1)
            processed_text, placeholder_map = p.preserve_placeholders(text)
            self._add_text(processed_text, line_number, 'string', context='python/__', placeholder_map=placeholder_map)
        
        # Match renpy.notify("text") pattern
        notify_pattern = r'renpy\.notify\s*\(\s*["\'](.+?)["\']\s*\)'
        for match in re.finditer(notify_pattern, code):
            text = match.group(1)
            processed_text, placeholder_map = p.preserve_placeholders(text)
            self._add_text(processed_text, line_number, 'ui', context='notify', placeholder_map=placeholder_map)
        
        # Match Character("Name", ...) pattern
        char_pattern = r'Character\s*\(\s*["\'](.+?)["\']\s*[\),]'
        for match in re.finditer(char_pattern, code):
            text = match.group(1)
            processed_text, placeholder_map = p.preserve_placeholders(text)
            self._add_text(processed_text, line_number, 'string', context='character_define', placeholder_map=placeholder_map)
        
        # Match DynamicCharacter("Name", ...) pattern
        dyn_char_pattern = r'DynamicCharacter\s*\(\s*["\'](.+?)["\']\s*[\),]'
        for match in re.finditer(dyn_char_pattern, code):
            text = match.group(1)
            processed_text, placeholder_map = p.preserve_placeholders(text)
            self._add_text(processed_text, line_number, 'string', context='character_define', placeholder_map=placeholder_map)
        
        # Match renpy.say(who, "text") pattern
        say_pattern = r'renpy\.say\s*\([^,]*,\s*["\'](.+?)["\']\s*[\),]'
        for match in re.finditer(say_pattern, code):
            text = match.group(1)
            processed_text, placeholder_map = p.preserve_placeholders(text)
            self._add_text(processed_text, line_number, 'dialogue', context='python/say', placeholder_map=placeholder_map)
        
        # Match Text("content") pattern (displayable)
        text_display_pattern = r'Text\s*\(\s*["\'](.+?)["\']\s*[\),]'
        for match in re.finditer(text_display_pattern, code):
            text = match.group(1)
            processed_text, placeholder_map = p.preserve_placeholders(text)
            self._add_text(processed_text, line_number, 'ui', context='displayable', placeholder_map=placeholder_map)
        
        # ============================================================
        # V2.6.7: NEW PATTERNS FROM REN'PY DOCUMENTATION RESEARCH
        # ============================================================
        
        # Match ___("text") pattern - triple underscore immediate translation
        # Example: text ___("Hello [player]")
        # Translates AND interpolates variables immediately
        triple_under_pattern = r'___\s*\(\s*["\'](.+?)["\']\s*\)'
        for match in re.finditer(triple_under_pattern, code):
            text = match.group(1)
            processed_text, placeholder_map = p.preserve_placeholders(text)
            self._add_text(processed_text, line_number, 'string', context='python/___', placeholder_map=placeholder_map)
        
        # Detect strings with !t flag interpolation
        # Example: "I'm feeling [mood!t]."
        # The !t flag marks the variable for translation lookup
        # We extract the full string, not just the variable
        t_flag_pattern = r'["\'](.* ?\[\w+!t\].+?)["\']'
        for match in re.finditer(t_flag_pattern, code):
            text = match.group(1)
            # Only extract if it has actual text, not just the placeholder
            if len(text.replace('[', '').replace(']', '').strip()) > 3:
                processed_text, placeholder_map = p.preserve_placeholders(text)
                self._add_text(processed_text, line_number, 'string', context='interpolation_t', placeholder_map=placeholder_map)
        
        # Match nvl "text" or nvl clear "text" patterns
        # Example: nvl "This is NVL dialogue"
        # NVL mode is used for novel-style text display
        nvl_pattern = r'nvl\s+(?:clear\s+)?["\'](.+?)["\']'
        for match in re.finditer(nvl_pattern, code):
            text = match.group(1)
            processed_text, placeholder_map = p.preserve_placeholders(text)
            self._add_text(processed_text, line_number, 'dialogue', context='nvl', placeholder_map=placeholder_map)
        
        # Match config.name = "Game Name" pattern
        config_name_pattern = r'config\.(name|version)\s*=\s*["\'](.+?)["\']'
        for match in re.finditer(config_name_pattern, code):
            text = match.group(2)
            processed_text, placeholder_map = p.preserve_placeholders(text)
            self._add_text(processed_text, line_number, 'string', context='config', placeholder_map=placeholder_map)
        
        # Match gui.text_* = "..." patterns
        gui_text_pattern = r'gui\.\w*text\w*\s*=\s*["\'](.+?)["\']'
        for match in re.finditer(gui_text_pattern, code):
            text = match.group(1)
            processed_text, placeholder_map = p.preserve_placeholders(text)
            self._add_text(processed_text, line_number, 'ui', context='gui', placeholder_map=placeholder_map)
        
        # Match gui.* patterns for text extraction
        gui_variable_pattern = r'gui\.\w*\s*=\s*["\'](.+?)["\']'
        for match in re.finditer(gui_variable_pattern, code):
            text = match.group(1)
            processed_text, placeholder_map = p.preserve_placeholders(text)
            self._add_text(processed_text, line_number, 'ui', context='gui', placeholder_map=placeholder_map)
        

        
        # --- UPDATED: Generic "Smart Key" Scanner ---
        # Use robust regex that handles escaped quotes
        # Support optional prefixes like f, r, b, u, fr, rf etc.
        generic_string_re = re.compile(r'''(?P<quote>(?:[rRuUbBfF]{,2})?(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'))''')

        # Regex for context: var = [  OR  var = {  OR  "key":  OR var = "string" (assignment)
        list_context_re = re.compile(r'(?P<var>[a-zA-Z_]\w*)\s*(?:=\s*[\[\(\{]|\+=\s*[\[\(]|\.(?:append|extend|insert)\s*\()|["\'](?P<key>\w+)["\']\s*[:=]')
        assignment_context_re = re.compile(r'(?P<var>[a-zA-Z_]\w*)\s*=\s*')

        for match in generic_string_re.finditer(code):
            raw_text = match.group('quote')
            text = self._extract_string_content(raw_text)

            if not text or len(text) < 2:
                continue
            if self._is_technical_string(text):
                continue

            # Look backwards for context (multiple lines/1000 chars)
            start_pos = match.start()
            lookback_len = 1000
            lookback = code[max(0, start_pos-lookback_len):start_pos]

            found_key = None
            key_match = list(list_context_re.finditer(lookback))
            if key_match:
                last = key_match[-1]
                found_key = last.groupdict().get('var') or last.groupdict().get('key')

            is_whitelisted = found_key and found_key.lower() in self.DATA_KEY_WHITELIST

            if found_key:
                if is_whitelisted:
                    processed_text, placeholder_map = p.preserve_placeholders(text)
                    self._add_text(processed_text, line_number, 'data_string', context=f"rpyc_val:{found_key}", placeholder_map=placeholder_map)
                else:
                    # Not whitelisted, but was assigned to a var - add cautiously as generic string
                    # Use empty context to avoid whitelist-based rejection; context holds var name in metadata
                    processed_text, placeholder_map = p.preserve_placeholders(text)
                    self._add_text(processed_text, line_number, 'string', context='', placeholder_map=placeholder_map)
            else:
                # No variable found - treat as a generic string in code (non-whitelisted context)
                # Use empty context so technical string heuristics only filter out technical values
                processed_text, placeholder_map = p.preserve_placeholders(text)
                self._add_text(processed_text, line_number, 'string', context='', placeholder_map=placeholder_map)
    
    def _extract_strings_from_code_ast(self, code: str, line_number: int) -> bool:
        """AST-based extraction for Python code blocks, focusing on string constants, f-strings, lists and dicts."""
        import textwrap
        import ast
        
        clean_code = code
        # Strip leading Ren'Py python block header: init python: or python:
        header_re = re.compile(r'^(?:\s*init\s+python\s*:|\s*python\s*:)', flags=re.I)
        match = header_re.match(code.strip().splitlines()[0]) if code.strip() else None
        
        if match:
            # Remove the first header line and dedent the rest to make it valid python
            lines = code.splitlines()
            # find first non-empty line that is the header
            idx = 0
            for i, l in enumerate(lines):
                if header_re.match(l):
                    idx = i
                    break
            block_lines = lines[idx+1:]
            clean_code = textwrap.dedent('\n'.join(block_lines))

        try:
            tree = ast.parse(clean_code)
        except Exception:
            return False

        p = self.parser
        
        # V2.7.1: Config-aware feature check closure for nested DeepStringVisitor
        is_deep_enabled = self._is_deep_feature_enabled
        
        # Helper to add text securely
        def add_text_val(raw_text: str, rel_line: int, ctx: str = '', text_type: str = 'python_string'):
            if not raw_text or len(raw_text.strip()) < 2:
                return
            
            # Additional heuristic: Skip strings that look like file paths or technical IDs
            if re.match(r'^[a-zA-Z0-9_/\\.-]+\.(png|jpg|mp3|ogg|rpy|rpyc|webp|gif)$', raw_text, re.I):
                return
            
            processed_text, placeholder_map = p.preserve_placeholders(raw_text)
            
            # Use strict context filtering if needed
            if self._is_technical_string(raw_text, context=ctx):
                return
                
            self._add_text(
                processed_text, 
                line_number + rel_line - 1, # Adjust for relative line in block
                text_type, 
                context=ctx or '', 
                character='', 
                placeholder_map=placeholder_map
            )

        class DeepStringVisitor(ast.NodeVisitor):
            def __init__(self, source_code):
                self.source_code = source_code
                self.context_stack = []

            def _get_context(self):
                # Limit context depth to avoid overly long identifiers
                return "/".join(self.context_stack[-3:]) if self.context_stack else ""

            def visit_Assign(self, node):
                # Track variable names as context
                pushed = False
                try:
                    target = node.targets[0]
                    if isinstance(target, ast.Name):
                        self.context_stack.append(f"var:{target.id}")
                        pushed = True
                    elif isinstance(target, ast.Attribute):
                         self.context_stack.append(f"var:{target.attr}")
                         pushed = True
                except Exception:
                    pass
                
                self.generic_visit(node)
                
                if pushed:
                    self.context_stack.pop()

            def visit_Call(self, node):
                # Handle _("text") and others
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    # Handle renpy.notify, renpy.input etc.
                    if isinstance(node.func.value, ast.Name) and node.func.value.id == 'renpy':
                        func_name = f"renpy.{node.func.attr}"
                    else:
                        func_name = node.func.attr
                
                # Tier-3 Blacklist: Skip all arguments from these calls FIRST
                if func_name in DeepExtractionConfig.TIER3_BLACKLIST_CALLS:
                    return  # Don't generic_visit into blacklisted call args
                
                # 1. Functions where ALL arguments are potential text (Translation functions)
                if func_name in ('_', '__', 'p'):
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            add_text_val(arg.value, getattr(node, 'lineno', 0), self._get_context(), 'call_arg')
                        elif isinstance(arg, ast.JoinedStr):
                            self.visit_JoinedStr(arg)

                # 2. Functions where the FIRST argument is text
                elif func_name in ('notify', 'renpy.notify', 'Confirm', 'Notify', 'MouseTooltip', 'ui.text', 'ui.textbutton', 'ui.label'):
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        add_text_val(node.args[0].value, getattr(node, 'lineno', 0), f"call:{func_name}", 'ui_arg')

                # 3. renpy.input / input (prompt is 1st arg or 'prompt' kwarg)
                elif func_name in ('input', 'renpy.input'):
                    # Check first arg
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        add_text_val(node.args[0].value, getattr(node, 'lineno', 0), "input_prompt", 'ui_arg')
                    # Check 'prompt' kwarg
                    for kw in node.keywords:
                        if kw.arg == 'prompt' and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            add_text_val(kw.value.value, getattr(node, 'lineno', 0), "input_prompt", 'ui_arg')

                # 4. renpy.say (who, what, ...) -> 'what' is the 2nd argument
                elif func_name == 'renpy.say':
                    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                        add_text_val(node.args[1].value, getattr(node, 'lineno', 0), "say_what", 'dialogue')

                # 5. achievement.register(key, title="...", description="...")
                elif func_name == 'achievement.register':
                    for kw in node.keywords:
                        if kw.arg in ('title', 'description') and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            add_text_val(kw.value.value, getattr(node, 'lineno', 0), f"achievement_{kw.arg}", 'ui_string')

                # 6. Tooltip("Text")
                elif func_name == 'Tooltip':
                     if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        add_text_val(node.args[0].value, getattr(node, 'lineno', 0), "tooltip", 'ui_string')

                # ============================================================
                # V2.7.1: DEEP EXTRACTION — Extended API Call Coverage
                # Only active when deep_extraction_extended_api is enabled
                # ============================================================

                elif is_deep_enabled('deep_extraction_extended_api') and func_name == 'QuickSave':
                    for kw in node.keywords:
                        if kw.arg == 'message' and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            add_text_val(kw.value.value, getattr(node, 'lineno', 0), "QuickSave.message", 'ui_string')

                # 8. CopyToClipboard("Link copied")
                elif is_deep_enabled('deep_extraction_extended_api') and func_name == 'CopyToClipboard':
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        add_text_val(node.args[0].value, getattr(node, 'lineno', 0), "CopyToClipboard", 'ui_string')

                # 9. FilePageNameInputValue(pattern="Page {}", auto="Auto", quick="Quick")
                elif is_deep_enabled('deep_extraction_extended_api') and func_name == 'FilePageNameInputValue':
                    for kw in node.keywords:
                        if kw.arg in ('pattern', 'auto', 'quick') and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            add_text_val(kw.value.value, getattr(node, 'lineno', 0), f"FilePageName.{kw.arg}", 'ui_string')

                # 10. narrator("text") — direct character proxy call
                elif is_deep_enabled('deep_extraction_extended_api') and func_name == 'narrator':
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        add_text_val(node.args[0].value, getattr(node, 'lineno', 0), "narrator", 'dialogue')

                # 11. renpy.display_notify(message)
                elif is_deep_enabled('deep_extraction_extended_api') and func_name == 'renpy.display_notify':
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        add_text_val(node.args[0].value, getattr(node, 'lineno', 0), "display_notify", 'ui_arg')

                # 12. renpy.display_menu([("Option A", "a"), ...]) — extract captions
                elif is_deep_enabled('deep_extraction_extended_api') and func_name == 'renpy.display_menu':
                    if node.args and isinstance(node.args[0], ast.List):
                        for elt in node.args[0].elts:
                            if isinstance(elt, ast.Tuple) and elt.elts:
                                first = elt.elts[0]
                                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                                    add_text_val(first.value, getattr(node, 'lineno', 0), "display_menu.caption", 'menu_choice')

                # 13. renpy.confirm("Are you sure?")
                elif is_deep_enabled('deep_extraction_extended_api') and func_name == 'renpy.confirm':
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        add_text_val(node.args[0].value, getattr(node, 'lineno', 0), "renpy.confirm", 'ui_arg')

                self.generic_visit(node)

            def visit_Dict(self, node):
                # Iterate over keys and values
                for k, v in zip(node.keys, node.values):
                    # Use key as context for value
                    key_ctx = "item"
                    if k and isinstance(k, ast.Constant):
                        key_ctx = str(k.value)
                    
                    self.context_stack.append(key_ctx)
                    self.visit(v) # Visit value
                    self.context_stack.pop()
                    
                    # We typically don't visit keys for translation unless they are strictly strings
                    # But usually dictionary keys are technical. Skipping keys.

            def visit_List(self, node):
                # Lists in assignments usually imply data
                self.generic_visit(node)

            def visit_Constant(self, node):
                if isinstance(node.value, str) and len(node.value) > 1:
                    ctx = self._get_context()
                    # Only extract if we are in a meaningful context (assignment or inside struct)
                    if ctx:
                        add_text_val(node.value, getattr(node, 'lineno', 0), ctx, 'data_string')
            
            def visit_JoinedStr(self, node):
                # F-String Reconstruction — Enhanced v2.7.1 with FStringReconstructor
                if not is_deep_enabled('deep_extraction_fstrings'):
                    return
                template = FStringReconstructor.extract_from_ast_node(node, self.source_code)
                if template:
                    add_text_val(template, getattr(node, 'lineno', 0), self._get_context(), 'f_string')

        # Run visitor
        visitor = DeepStringVisitor(clean_code)
        visitor.visit(tree)
        return True


    def _extract_strings_from_line(self, line: str, line_number: int) -> None:
        """Extract string literals from a line of code."""
        import re

        # First check for common translatable patterns
        self._extract_strings_from_code(line, line_number)

        # Robust regex for manual line scanning
        string_literal_re = re.compile(r'''(?P<quote>(?:[rRuUbBfF]{,2})?(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'))''')

        # Context regex
        list_context_re = re.compile(r'([a-zA-Z_]\w*)\s*(?:=\s*[\[\(\{]|\+=\s*[\[\(]|\.(?:append|extend|insert)\s*\()')

        for match in string_literal_re.finditer(line):
            raw_text = match.group('quote')
            text = self._extract_string_content(raw_text)

            if text:
                # Check for variable context
                found_key = None
                list_match = list_context_re.search(line[:match.start()])
                if list_match:
                    found_key = list_match.group(1)

                is_whitelisted_key = found_key and found_key.lower() in self.DATA_KEY_WHITELIST

                # Check UI keywords if not whitelisted
                ui_keywords = ['text', 'label', 'button', 'tooltip', 'caption', 'title']
                is_ui_text = any(kw in line.lower() for kw in ui_keywords) and not self._is_technical_string(text)

                if is_whitelisted_key:
                    self._add_text(text, line_number, 'list_item', context=f"variable:{found_key}")
                elif is_ui_text:
                    self._add_text(text, line_number, 'string', context="ui_keyword")


# ============================================================================
# PUBLIC API
# ============================================================================


def extract_texts_from_rpyc(
    file_path: Union[str, Path],
    config_manager: Any = None
) -> List[Dict[str, Any]]:
    """
    Extract translatable texts from a .rpyc file.
    
    Args:
        file_path: Path to .rpyc file
        config_manager: Optional config manager instance
        
    Returns:
        List of dicts with text, line_number, text_type, etc.
    """
    extractor = ASTTextExtractor(config_manager)
    results = extractor.extract_from_file(file_path)
    
    return [
        {
            'text': r.text,
            'line_number': r.line_number,
            'text_type': r.text_type,
            'character': r.character,
            'context_path': [r.context] if r.context else [],
            'context': r.context,
            'source_file': r.source_file,
            'node_type': r.node_type,
            'is_rpyc': True,
            'confidence': r.confidence,
            'confidence_band': r.confidence_band,
            # Real Ren'Py-assigned translate id from the compiled AST, when available.
            'identifier': r.identifier,
        }
        for r in results
    ]


def extract_texts_from_rpyc_directory(
    directory: Union[str, Path],
    recursive: bool = True,
    config_manager: Any = None
) -> Dict[Path, List[Dict[str, Any]]]:
    """
    Extract translatable texts from all .rpyc files in a directory.

    Args:
        directory: Directory path (should be the game folder directly)
        recursive: Search subdirectories
        config_manager: Optional config manager instance

    Returns:
        Dict mapping file paths to extracted texts
    """
    directory = Path(directory)
    results = {}

    # Use directory directly - caller should pass game folder
    search_root = directory

    # Find .rpyc and .rpymc files
    pattern_rpyc = "**/*.rpyc" if recursive else "*.rpyc"
    pattern_rpymc = "**/*.rpymc" if recursive else "*.rpymc"
    rpyc_files = list(search_root.glob(pattern_rpyc)) + list(search_root.glob(pattern_rpymc))

    # Exclude tl/ folder and renpy engine files, except renpy/common
    filtered_files = []
    for f in rpyc_files:
        try:
            rel_path = f.relative_to(search_root)
            rel_str = str(rel_path).lower()
            # Skip if in tl/ subdirectory
            if rel_str.startswith('tl\\') or rel_str.startswith('tl/'):
                continue
            # Allow renpy/common and project-copied renpy under subfolders
            # Exclude only if renpy/ sits at the root of the search (engine files)
            if rel_str.startswith('renpy/') and 'common' not in rel_str:
                continue
            filtered_files.append(f)
        except ValueError:
            # If relative_to fails, include the file
            filtered_files.append(f)

    rpyc_files = filtered_files

    logger.info(f"Found {len(rpyc_files)} .rpyc/.rpymc files")

    for rpyc_file in rpyc_files:
        try:
            texts = extract_texts_from_rpyc(rpyc_file, config_manager=config_manager)
            results[rpyc_file] = texts
            logger.debug(f"Extracted {len(texts)} texts from {rpyc_file}")
        except Exception as e:
            logger.exception(f"Error extracting from {rpyc_file}: {e}")
            results[rpyc_file] = []

    total = sum(len(texts) for texts in results.values())
    logger.info(f"Total extracted from RPYC: {total} texts from {len(results)} files")

    return results


# Quick test
if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.DEBUG)
    
    if len(sys.argv) > 1:
        path = sys.argv[1]
        if Path(path).is_file():
            texts = extract_texts_from_rpyc(path)
            for t in texts:
                print(f"[{t['text_type']}] {t['text'][:50]}...")
        else:
            results = extract_texts_from_rpyc_directory(path)
            for file, texts in results.items():
                print(f"\n{file.name}: {len(texts)} texts")
                for t in texts[:5]:
                    print(f"  [{t['text_type']}] {t['text'][:40]}...")
