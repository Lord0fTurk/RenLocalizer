# -*- coding: utf-8 -*-
"""
Ren'Py Stateful Lexer Engine.
========================================

A robust state-machine lexer for parsing Ren'Py .rpy files line by line,
tracking quotes, indentation levels, Python blocks, and speaker statements
without relying on fragile monolithic regular expressions.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any
import re

from src.core.output_formatter import format_renpy_speaker


@dataclass
class LexerToken:
    """Represents an extracted translatable token from the Ren'Py lexer."""
    text_type: str  # 'dialogue', 'ui', 'button', 'character_name'
    text: str
    character: str = ""
    line_number: int = 1
    raw_line: str = ""
    context_path: List[str] = field(default_factory=list)


class RenPyLexer:
    """State-machine lexer for Ren'Py script parsing."""

    KEYWORDS_TO_SKIP = {
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

    UI_KEYWORDS = {
        'textbutton': 'button',
        'text': 'ui',
        'tooltip': 'ui',
        'caption': 'ui',
        'help': 'ui',
        'label': 'ui',
    }

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Reset internal lexer state."""
        self.current_label: Optional[str] = None
        self.in_python_block: bool = False
        self.python_indent: int = 0

    def tokenize(self, content: str, file_path: str = "") -> List[LexerToken]:
        """Tokenize .rpy script content into translatable LexerTokens."""
        self.reset()
        tokens: List[LexerToken] = []
        lines = content.splitlines()

        in_multiline: bool = False
        multiline_delim: str = ""
        multiline_speaker: str = ""
        multiline_lines: List[str] = []
        multiline_start_line: int = 1

        for idx, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped:
                continue

            indent = len(line) - len(line.lstrip())

            # Handle active multiline triple-quote state
            if in_multiline:
                if multiline_delim in line:
                    # Closing multiline
                    parts = line.split(multiline_delim, 1)
                    multiline_lines.append(parts[0])
                    full_text = "\n".join(multiline_lines)
                    context_path = [f"label:{self.current_label}"] if self.current_label else []
                    tokens.append(LexerToken(
                        text_type='dialogue',
                        text=full_text,
                        character=multiline_speaker,
                        line_number=multiline_start_line,
                        raw_line=line,
                        context_path=context_path
                    ))
                    in_multiline = False
                    multiline_lines = []
                else:
                    multiline_lines.append(line)
                continue

            # Python block state tracking
            if self.in_python_block:
                if indent <= self.python_indent and stripped and not stripped.startswith('#'):
                    self.in_python_block = False
                else:
                    continue

            # Skip pure comments
            if stripped.startswith('#'):
                continue

            # Check single line python
            if stripped.startswith('$'):
                continue

            # Check start of python block
            if stripped.startswith(('python:', 'init python:', 'python early:', 'init -', 'init python')):
                self.in_python_block = True
                self.python_indent = indent
                continue

            # Check label definition
            if stripped.startswith('label ') and (stripped.endswith(':') or ':' in stripped):
                parts = stripped.split()
                if len(parts) >= 2:
                    label_name = parts[1].split(':')[0].strip('"\'')
                    self.current_label = label_name
                continue

            # Check triple quote start
            if '"""' in stripped or "'''" in stripped:
                delim = '"""' if '"""' in stripped else "'''"
                first_pos = stripped.find(delim)
                last_pos = stripped.rfind(delim)
                if first_pos == last_pos:
                    # Multiline opens on this line and closes on a later line
                    speaker_part = stripped[:first_pos].strip()
                    multiline_speaker = self._parse_speaker_name(speaker_part)
                    body_start = stripped[first_pos + 3:]
                    in_multiline = True
                    multiline_delim = delim
                    multiline_speaker = multiline_speaker
                    multiline_lines = [body_start] if body_start else []
                    multiline_start_line = idx
                    continue

            # Process standard single-line dialogue or UI statement
            token = self._parse_line(line, idx)
            if token:
                tokens.append(token)

        return tokens

    def _parse_line(self, line: str, line_num: int) -> Optional[LexerToken]:
        """Parse a single line into a LexerToken if translatable dialogue or UI statement."""
        stripped = line.strip()
        if not stripped:
            return None

        # Check for menu choice: e.g. "Go to park": or "Go to park" if condition:
        is_menu_choice = False
        if stripped.endswith(':') or (':' in stripped and stripped.split(':', 1)[1].strip() == ''):
            is_menu_choice = True

        # Extract all top-level quoted strings on this line
        quotes = re.findall(r'"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\'', line)
        if not quotes:
            return None

        context_path = [f"label:{self.current_label}"] if self.current_label else []

        if is_menu_choice:
            # Menu choice statement
            body = quotes[0][1:-1]
            if not body.strip():
                return None
            return LexerToken(
                text_type='menu',
                text=body,
                character="",
                line_number=line_num,
                raw_line=line,
                context_path=context_path
            )

        first_quote = quotes[0]
        prefix = line[:line.find(first_quote)].strip()

        if prefix:
            prefix_words = prefix.split()
            first_word = prefix_words[0].lower()

            if first_word in self.KEYWORDS_TO_SKIP:
                return None
            if '=' in prefix and first_word in ('define', 'default', 'let', 'var', 'set'):
                return None

        if len(quotes) >= 2:
            # Two quoted strings: e.g. "???" "Who goes there?"
            if not prefix:
                # First quote is speaker, second quote is dialogue body
                character = quotes[0]
                body = quotes[1][1:-1]
                text_type = "dialogue"
            else:
                character = self._parse_speaker_name(prefix)
                body = quotes[-1][1:-1]
                text_type = "dialogue"
        else:
            # Single quoted string
            body = first_quote[1:-1]

            if not prefix:
                character = ""
                text_type = "dialogue"
            else:
                prefix_words = prefix.split()
                first_word = prefix_words[0].lower()

                if first_word in self.UI_KEYWORDS:
                    character = ""
                    text_type = self.UI_KEYWORDS[first_word]
                else:
                    character = self._parse_speaker_name(prefix)
                    text_type = "dialogue"

        if character:
            clean_char = character.strip('"\'').lower()
            if clean_char in self.KEYWORDS_TO_SKIP:
                return None

        if not body.strip():
            return None

        return LexerToken(
            text_type=text_type,
            text=body,
            character=character,
            line_number=line_num,
            raw_line=line,
            context_path=context_path
        )

    def _parse_speaker_name(self, prefix: str) -> str:
        """Clean and extract speaker name from line prefix."""
        if not prefix:
            return ""
        prefix = prefix.strip()
        # If speaker is quoted string literal e.g. "???" or 'Old Man'
        if len(prefix) >= 2 and prefix[0] == prefix[-1] and prefix[0] in ('"', "'"):
            return prefix
        # Take first token before ATL attributes or with clauses
        parts = prefix.split()
        if parts:
            first_part = parts[0]
            # Strip trailing colon if present
            clean = first_part.rstrip(':')
            if clean.lower() in self.KEYWORDS_TO_SKIP:
                return ""
            return clean
        return prefix


class TokenStream:
    """Backwards-compatibility wrapper for TokenStream."""
    def __init__(self, *args, **kwargs):
        pass
        
    def __iter__(self):
        return self
        
    def __next__(self):
        raise StopIteration
