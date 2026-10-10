
# -*- coding: utf-8 -*-
"""
Glossary Extractor Tool
=======================

Extracts potential glossary terms (character names, common nouns) from Ren'Py scripts.
"""

import logging
import os
import re
from collections import Counter
from typing import Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

_SKIP_DIRS = {"tl", "renpy", "cache", "saves", "__pycache__", "python-packages"}

class GlossaryExtractor:
    """Analyzes Ren'Py files to find potential glossary terms."""
    
    def __init__(self):
        # Regex for character definitions: define e = Character("Eileen")
        self.char_def_pattern = re.compile(r'define\s+(\w+)\s*=\s*Character\s*\(\s*(?:_\()?"([^"]+)"')
        
        # Regex for character speaking: e "Hello"
        self.dialogue_pattern = re.compile(r'^\s*(\w+)\s+"', re.MULTILINE)
        
        # Regex for capitalized words in text (potential proper nouns)
        # Excludes beginning of sentences roughly
        self.proper_noun_pattern = re.compile(r'(?<!^)(?<!\.\s)(?<!\?\s)(?<!\!\s)(?<!\"\s)\b([A-Z][a-z]+)\b')

    def extract_from_directory(self, project_path: str, min_occurrence: int = 3) -> Dict[str, str]:
        """
        Scan directory and return a dict of {source_term: translation_stub}.
        """
        project_path = os.path.abspath(project_path)
        game_dir = os.path.join(project_path, "game") if os.path.isdir(os.path.join(project_path, "game")) else project_path
        
        character_map = {}  # var_name -> display_name
        term_counter = Counter()

        from src.core.constants import is_renlocalizer_generated_script

        # 1. Scan the game's own scripts. tl/ holds translated text (it would
        # feed back target-language words), renpy/ is the engine's UI.
        for root, dirs, files in os.walk(game_dir):
            dirs[:] = [d for d in dirs if d.lower() not in _SKIP_DIRS]
            for file in files:
                if file.lower().endswith('.rpy') and not is_renlocalizer_generated_script(file):
                    file_path = os.path.join(root, file)
                    self._scan_file(file_path, character_map, term_counter)
        
        # 2. Build result dictionary
        results = {}
        from src.core.glossary_manager import COMMON_ENGLISH_STOPWORDS
        
        # Add characters (High priority)
        for var_name, display_name in character_map.items():
            clean_name = (display_name or "").strip()
            if (
                clean_name
                and len(clean_name) >= 3
                and clean_name.lower() not in COMMON_ENGLISH_STOPWORDS
                and clean_name not in results
            ):
                # Name -> same name: an empty target protects nothing, the
                # identity entry keeps the name untranslated everywhere.
                results[clean_name] = clean_name
        
        # Add common terms
        for term, count in term_counter.most_common(50):
            clean_term = (term or "").strip()
            if (
                count >= min_occurrence
                and len(clean_term) >= 3
                and clean_term.lower() not in COMMON_ENGLISH_STOPWORDS
                and clean_term not in results
            ):
                results[clean_term] = ""
                    
        return results

    def _scan_file(self, file_path: str, char_map: Dict, term_counter: Counter):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            try:
                with open(file_path, 'r', encoding='latin-1') as f:
                    content = f.read()
            except Exception as e:
                logger.warning("Error reading %s with fallback encoding: %s", file_path, e)
                return
        except Exception as e:
            logger.warning("Error reading %s: %s", file_path, e)
            return

        try:
            # Find definitions: Character("Name"), Character('Name'),
            # Character(_("Name")), DynamicCharacter(...), name="..."
            from src.core.parser import _CHARACTER_NAME_ARG_RE

            for match in _CHARACTER_NAME_ARG_RE.finditer(content):
                display_name = match.group('name')
                if display_name and not any(ch in display_name for ch in '[]{}%'):
                    char_map[display_name] = display_name

            # Simple string extraction
            strings = re.findall(r'"([^"]+)"', content)
            for s in strings:
                matches = self.proper_noun_pattern.findall(s)
                for m in matches:
                    term_counter[m] += 1
        except Exception as e:
            logger.warning("Error scanning %s: %s", file_path, e)

