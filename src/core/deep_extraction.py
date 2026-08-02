# -*- coding: utf-8 -*-
"""
Minimal but functional Deep Extraction helpers ported from the full
Standard-Version to improve extraction coverage.

This module intentionally keeps dependencies low while providing:
- variable-name heuristics (`DeepVariableAnalyzer`)
- f-string reconstruction helpers (`FStringReconstructor`)
- simple multi-line block parsing (`MultiLineStructureParser`)
- confidence scoring helpers for extraction candidates
"""

from dataclasses import dataclass
import re
from typing import Tuple, Union


@dataclass
class DeepExtractionConfig:
    min_confidence: float = 0.35
    allow_single_word_items: bool = True
    max_regex_noise_ratio: float = 0.35
    # Tiered call maps used by AST scan logic in parser.py
    TIER3_BLACKLIST_CALLS = {'eval', 'exec', 'compile', 'open', 'os.system'}
    TIER2_CONTEXTUAL_CALLS = {}

    @classmethod
    def get_merged_text_calls(cls, config=None):
        """Return a merged set/list of Python function names that should be
        treated as text-carrying calls during deep extraction.
        """
        # Minimal conservative default set — can be extended from config
        # Return a mapping of function name -> {'pos': [pos_indices], 'kw': [kw_names]}
        defaults = {
            'renpy.notify': {'pos': [0], 'kw': []},
            'notify': {'pos': [0], 'kw': []},
            'renpy.say': {'pos': [1], 'kw': []},
            'say': {'pos': [1], 'kw': []},
            'renpy.notify_once': {'pos': [0], 'kw': []},
            'Character': {'pos': [0], 'kw': []},
            'renpy.jump': {'pos': [], 'kw': []},
            'renpy.call': {'pos': [], 'kw': []},
            'renpy.show': {'pos': [], 'kw': []},
            'renpy.hide': {'pos': [], 'kw': []},
        }
        try:
            if config is None:
                return defaults
            ts = getattr(config, 'translation_settings', None)
            extra = {}
            if ts is not None:
                for name in getattr(ts, 'deep_extraction_extra_calls', []) or []:
                    extra[name] = {'pos': [0], 'kw': []}
            # merge defaults and extras (extras override)
            merged = dict(defaults)
            merged.update(extra)
            return merged
        except Exception:
            return defaults


class DeepVariableAnalyzer:
    """Heuristics for determining whether a variable/key likely contains
    translatable text or technical data (paths, IDs, flags).
    """

    TECHNICAL_KEYWORDS = {
        'file', 'path', 'url', 'image', 'img', 'icon', 'sfx', 'sound', 'voice',
        'id', 'code', 'hash', 'uuid', 'crc', 'size', 'width', 'height', 'bytes',
        'flags', 'enabled', 'timeout', 'timestamp', 'date', 'version'
    }

    def __init__(self, config: DeepExtractionConfig | None = None):
        self.config = config or DeepExtractionConfig()

    def is_likely_translatable(self, var_name: str | None, *args, **kwargs) -> bool:
        if not var_name:
            return True
        name = str(var_name).lower()
        # If key contains technical keywords, consider non-translatable
        for kw in self.TECHNICAL_KEYWORDS:
            if kw in name.split('_') or kw in name.split('.'):
                return False
        # short keys like 'title', 'name', 'desc' are translatable
        if any(tok in name for tok in ('title', 'name', 'desc', 'text', 'label', 'caption', 'message', 'dialog')):
            return True
        # conservative default
        return True

    def classify(self, var_name: str) -> str:
        """Classify a variable name for RPYC reader compatibility.
        
        Returns: "translatable" | "non_translatable" | "uncertain"
        
        This version uses a conservative approach: always return "translatable"
        to ensure maximum extraction. The parser's own filters will catch
        false positives later.
        """
        return "translatable"

    def is_technical_string(self, text: str, *args, **kwargs) -> bool:
        if not text:
            return True
        t = text.strip()
        # URLs, file extensions, and very short tokens are technical
        if re.search(r'https?://|www\.|\\/|\.|\.(png|jpg|ogg|mp3|rpy|rpyc|json|xml|yaml)$', t, re.IGNORECASE):
            return True
        if len(t) <= 2:
            return True
        # too many punctuation/escape characters indicates code/regex
        noise = len(re.findall(r'[\\#\[\]{}|*+?^$]', t))
        if noise > max(1, len(t) * self.config.max_regex_noise_ratio):
            return True
        return False


class FStringReconstructor:
    """Lightweight f-string reconstructor.

    Exposes `reconstruct(text)` which replaces Python-style `{var}` and
    format fields with placeholder tokens to preserve structure during
    translation.
    """

    _brace_re = re.compile(r'\{[^}]+\}')

    def reconstruct(self, text: str) -> str:
        if not text:
            return text
        # Replace each {expr} with a stable placeholder like ⟦PH_n⟧
        def _repl(m):
            inner = m.group(0)[1:-1].strip()
            key = re.sub(r'\W+', '_', inner)[:20]
            return f'⟦PH_{key}⟧'

        return self._brace_re.sub(_repl, text)

    @staticmethod
    def extract_template(fstring_literal: str) -> str | None:
        """Given the inner contents of an f-string literal (without the f prefix),
        return a stable template where expressions are replaced with placeholders.
        Example: 'Welcome {player_name}!' -> 'Welcome ⟦PH_player_name⟧!'
        """
        if not fstring_literal:
            return None
        try:
            recon = FStringReconstructor()
            # strip optional surrounding quotes
            s = fstring_literal
            if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
                s = s[1:-1]
            return recon.reconstruct(s)
        except Exception:
            return None

    @staticmethod
    def extract_from_ast_node(node, source: str) -> str | None:
        """Reconstruct text from an AST JoinedStr node.

        Walks `node.values` and converts constants and formatted values
        into a placeholder-preserved string.
        """
        try:
            parts = []
            for v in getattr(node, 'values', []):
                import ast
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    parts.append(v.value)
                elif isinstance(v, ast.FormattedValue):
                    # Attempt to extract the source slice for the formatted value
                    inner = ast.get_source_segment(source, v) or '{expr}'
                    key = re.sub(r'\W+', '_', inner.strip())[:20]
                    parts.append(f'⟦PH_{key}⟧')
                else:
                    # Fallback: raw source segment
                    seg = ast.get_source_segment(source, v)
                    if seg:
                        parts.append(seg)
            if not parts:
                return None
            return ''.join(parts)
        except Exception:
            return None


class MultiLineStructureParser:
    """Simple utilities to normalize multiline Ren'Py-like blocks.

    Methods:
    - `split_lines(text)` → list of meaningful lines
    - `normalize_block(text)` → collapse excessive whitespace while
       preserving intentional newlines.
    """

    def split_lines(self, text: str):
        if not text:
            return []
        lines = [ln.rstrip() for ln in text.splitlines()]
        # remove surrounding empty lines
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        return [ln for ln in lines if ln.strip()]

    def normalize_block(self, text: str) -> str:
        lines = self.split_lines(text)
        return '\n'.join(lines)

    @staticmethod
    def detect_multiline_start(line: str):
        """Detect a multiline define/default start line.

        Returns dict with var_name and opener char if found, otherwise None.
        """
        if not line:
            return None
        # Match define/default var = { or [ or triple-quoted string or assignment to multiline string
        m = re.match(r"^\s*(?:define|default)\s+([A-Za-z0-9_\.]+)\s*=\s*(?P<opener>\{|\[|\"\"\"|\'\'\'|\"|' )", line)
        if not m:
            # also match bare assignment that starts a block on next line: define foo =
            m2 = re.match(r"^\s*(?:define|default)\s+([A-Za-z0-9_\.]+)\s*=\s*$", line)
            if m2:
                return {'var_name': m2.group(1), 'opener': None}
            return None
        opener = m.group('opener')
        return {'var_name': m.group(1), 'opener': opener}

    @staticmethod
    def collect_block(lines: list, start_idx: int, info: dict):
        # Return (block_text, end_idx) where end_idx is index of line after block
        opener = info.get('opener')
        collected = []
        idx = start_idx
        # If opener is triple-quote, find corresponding end triple-quote
        if opener in ('"""', "'''"):
            term = opener
            # include starting line
            while idx < len(lines):
                line = lines[idx]
                collected.append(line)
                if term in line and idx != start_idx:
                    idx += 1
                    break
                idx += 1
            return '\n'.join(collected), idx

        # If opener is None (assignment continued on following lines), try to collect a dict/list block
        if opener is None:
            # look ahead for { or [ or triple-quote on subsequent lines
            look = idx + 1
            while look < len(lines) and not lines[look].strip():
                look += 1
            if look < len(lines) and lines[look].lstrip().startswith(('{', '[')):
                opener = lines[look].lstrip()[0]
                idx = look
            else:
                # nothing to collect
                return lines[start_idx], start_idx + 1

        if opener in ('{', '['):
            closer = '}' if opener == '{' else ']'
            depth = 0
            while idx < len(lines):
                line = lines[idx]
                collected.append(line)
                depth += line.count(opener) - line.count(closer)
                idx += 1
                if depth <= 0:
                    break
            return '\n'.join(collected), idx

        # Fallback: single-line
        return lines[start_idx], start_idx + 1

    @staticmethod
    def extract_translatable_values(var_name: str, block: str):
        """Extract simple key->string pairs from a dict/list block.

        Returns list of {'text': str, 'lineno': int, 'context': key}
        """
        results = []
        lines = block.splitlines()

        # Translatable key names commonly used in Ren'Py game data structures.
        # Categories: quest systems, character profiles, phone/chat, schedule,
        # inventory, achievements, tutorial, journal, UI screens, general text.
        # Sourced from real Ren'Py game patterns and community conventions.
        _translatable_keys = {
            # Core / general
            'title', 'name', 'desc', 'text', 'content', 'body',
            'label', 'caption', 'header', 'subtitle', 'heading',
            'intro', 'outro', 'greeting', 'farewell',
            # Quest & mission systems
            'objective', 'objectives', 'description', 'summary', 'brief', 'briefing',
            'quest_name', 'quest_desc', 'quest_title', 'quest_text',
            'task', 'tasks', 'goal', 'goals', 'step', 'steps', 'stage',
            'detail', 'details', 'info', 'information',
            # Character profiles & bios
            'bio', 'biography', 'backstory', 'personality', 'history', 'background',
            'profile', 'introduction', 'quote', 'saying', 'catchphrase', 'motto',
            # Phone messages & chat systems
            'message', 'subject', 'preview', 'snippet',
            'sender', 'chat', 'reply', 'post', 'comment',
            # Schedule & calendar
            'event_name', 'event_title', 'event_desc',
            'schedule_entry', 'calendar_note', 'reminder', 'appointment',
            'activity', 'plan', 'agenda',
            # Inventory & shops
            'item_name', 'item_desc', 'item_description',
            'flavor_text', 'lore', 'examine_text', 'inspect_text',
            # Achievements & gallery
            'achievement_name', 'unlock_text',
            'gallery_name', 'gallery_desc', 'cg_name', 'cg_desc',
            'scene_name', 'scene_desc', 'scene_title',
            # Tutorial & help
            'tutorial_text', 'guide_text', 'help_text', 'explanation',
            'instruction', 'instructions',
            # Journal & diary
            'entry', 'journal_entry', 'log_entry', 'diary_text',
            'note', 'memo', 'entry_title', 'entry_body',
            # UI screen elements
            'tooltip', 'hint', 'tip',
            'tooltip_text', 'hover_text', 'status_text',
            'notification', 'alert', 'warning', 'prompt', 'confirm',
            'button_text', 'badge_text',
            # Dialogue & story
            'narration', 'narrative', 'story', 'story_text',
            'dialog', 'dialogue', 'line',
            'option', 'choice', 'question', 'answer',
        }

        # 1) dict-style quoted keys: 'key': 'value' or "key": "value"
        for m in re.finditer(r"([\'\"])(?P<key>[A-Za-z0-9_\- ]+)\1\s*:\s*([\'\"])(?P<val>.*?)(?:\3)", block, re.DOTALL):
            key = m.group('key')
            val = m.group('val').strip()
            start_pos = m.start()
            lineno = block[:start_pos].count('\n')
            if any(tok in key.lower() for tok in _translatable_keys):
                results.append({'text': val, 'lineno': lineno, 'context': key})

        # 2) bare-key: value (where value is quoted string)
        for m in re.finditer(r"(?m)^(?P<key>[A-Za-z0-9_\- ]+)\s*:\s*([\'\"])(?P<val>.*?)(?:\2)$", block):
            key = m.group('key')
            val = m.group('val').strip()
            lineno = block[:m.start()].count('\n')
            if any(tok in key.lower() for tok in _translatable_keys):
                results.append({'text': val, 'lineno': lineno, 'context': key})

        # 3) list-style of strings: ["a", "b", ...] — if var_name suggests translatable
        if any(tok in var_name.lower() for tok in _translatable_keys):
            for m in re.finditer(r"([\'\"])(?P<val>.*?)(?:\1)", block, re.DOTALL):
                val = m.group('val').strip()
                lineno = block[:m.start()].count('\n')
                # Skip very short or technical-looking values
                if val and len(val) >= 3 and not re.search(r'^[a-z_]+://|^\d+$|^[A-Z_]+$', val):
                    results.append({'text': val, 'lineno': lineno, 'context': var_name})

        return results


def confidence_band(text: Union[str, float]) -> Tuple[float, float]:
    """Return a (low, high) confidence band for a candidate string.

    Short or punctuation-heavy strings get lower bands.
    """
    # If a numeric confidence is provided, return a narrow band around it.
    try:
        if isinstance(text, (int, float)):
            c = float(text)
            low = max(0.0, c - 0.05)
            high = min(1.0, c + 0.05)
            return (low, high)
    except Exception:
        pass

    if not text:
        return (0.0, 0.1)
    t = str(text).strip()
    length = len(t)
    alpha_count = sum(1 for c in t if c.isalpha())
    alpha_ratio = alpha_count / max(1, length)
    # heuristic
    if alpha_ratio < 0.3 or length < 3:
        return (0.0, 0.3)
    if length < 10:
        return (0.3, 0.7)
    return (0.6, 1.0)


def resolve_minimum_extraction_confidence(config: DeepExtractionConfig | None = None, default: float = 0.5) -> float:
    cfg = config or DeepExtractionConfig()
    try:
        return float(getattr(cfg, 'min_confidence', default))
    except Exception:
        return default


def score_extraction_confidence(text: str, text_type: str | None = None, context_line: str | None = None,
                              context_path: list | None = None, character: str | None = None, **kwargs) -> float:
    """Compute a 0..1 confidence score indicating how likely `text` is
    a meaningful translatable string.
    """
    if not text or not text.strip():
        return 0.0
    t = text.strip()
    length = len(t)
    alpha = sum(1 for c in t if c.isalpha())
    alpha_ratio = alpha / length
    # Penalize file-like strings and URLs
    if re.search(r'https?://|www\.|\\/|\.(png|jpg|ogg|mp3|rpy|rpyc|json|xml|yaml)$', t, re.IGNORECASE):
        return 0.0
    # base score from alphabetic density and length
    score = min(1.0, alpha_ratio * 0.9 + min(1.0, length / 120.0) * 0.3)
    # boost if sentence-like punctuation present
    if re.search(r'[.!?…]', t):
        score = min(1.0, score + 0.12)
    # demote if too many special chars
    noise = len(re.findall(r'[\\#\[\]{}|*+?^$]', t))
    if noise > 0:
        score *= max(0.0, 1.0 - noise * 0.12)
    return float(max(0.0, min(1.0, score)))


# Module-shared analyzer for backward imports
_shared_analyzer = DeepVariableAnalyzer()
