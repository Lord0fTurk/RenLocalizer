# -*- coding: utf-8 -*-
"""
File-by-File Exporter for RenLocalizer
======================================

Reads translations from strings.json and converts them into standard 
Ren'Py translation (.rpy) files. Useful for translators who prefer classic 
file structures instead of runtime JSON injection.

In Native TLID mode, dynamic texts (containing {variable} patterns from
Python f-strings) are excluded — they're handled by the micro runtime hook.
"""

import os
import json
import re
import logging
from pathlib import Path
from src.utils.encoding import save_text_safely

logger = logging.getLogger(__name__)

# Known Ren'Py text tags — anything else in {braces} is a Python variable
_RENPY_TAG_NAMES = frozenset({
    'b', 'i', 'u', 's', 'plain', 'color', 'font', 'size', 'cps',
    'nw', 'fast', 'w', 'p', 'a', 'image', 'alpha', 'k', 'rt', 'rb',
    'space', 'vspace', 'outlinecolor',
})


_RPY_ESCAPE_MAP = {'n': '\n', 't': '\t', '"': '"', '\\': '\\'}


def _unescape_rpy(text: str) -> str:
    """Unescape a Ren'Py string literal in a single left-to-right pass.

    Chained ``.replace()`` is order-dependent and corrupts literal
    backslashes (an escaped ``\\n`` is misread as a real newline), which
    breaks export dedup. A single pass maps each escape exactly once.
    """
    return re.sub(r'\\(.)', lambda m: _RPY_ESCAPE_MAP.get(m.group(1), m.group(1)), text)


def _has_dynamic_variables(text: str) -> bool:
    """Return True if text contains Python {variable} patterns (not Ren'Py tags)."""
    braced = re.findall(r'\{([^}]+)\}', text)
    if not braced:
        return False
    for b in braced:
        # {/b} → strip '/', {color=#fff} → take 'color'
        tag_name = b.lstrip('/').split('=')[0].strip().lower()
        if tag_name not in _RENPY_TAG_NAMES:
            return True
    return False

def _resolve_game_dir(project_path: str) -> str:
    """Accept either the project root or the game directory itself."""
    normalized_path = os.path.normpath(project_path)
    if os.path.basename(normalized_path).lower() == "game" and os.path.isdir(normalized_path):
        return normalized_path
    return os.path.join(normalized_path, "game")


def export_strings_to_rpy(project_path: str, target_lang: str, skip_dynamic: bool = False) -> bool:
    """
    Reads translations and exports them as standard Ren'Py translation blocks.
    Accepts either the project root or the game directory itself.
    
    If skip_dynamic is True, texts with Python {variable} patterns are excluded
    (they're handled by the micro runtime hook in Native TLID mode).
    """
    game_dir = _resolve_game_dir(project_path)
    tl_dir = os.path.join(game_dir, "tl", target_lang)
    json_path = os.path.join(tl_dir, "strings.json")
    
    if not os.path.exists(json_path):
        logger.warning(f"Export failed: {json_path} does not exist.")
        return False
        
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # Standardize data format (v2.7.2 supports both flat dict and metadata-rich dict)
        mapping = {}
        if isinstance(data, dict):
            if "translations" in data: # Metadata-rich format
                mapping = data["translations"]
            else: # Flat dict format (old/simple)
                mapping = data
                
        if not mapping:
            logger.info("Nothing to export.")
            return True

        # To avoid Duplicate Translation errors, we must ensure each string is only
        # defined ONCE. If it's already in an existing .rpy file in the tl folder,
        # we skip it here.
        existing_texts = set()
        for root, _, files in os.walk(tl_dir):
            for filename in files:
                if filename.lower().endswith('.rpy') and not filename.startswith('zz_rl_exported'):
                    try:
                        with open(os.path.join(root, filename), 'r', encoding='utf-8-sig', errors='replace') as rf:
                            content = rf.read()
                            # Find 'old "..."' matches
                            for match in re.findall(r'^\s*old\s+"(.*?)"\s*$', content, re.MULTILINE):
                                # Unescape for matching
                                u = _unescape_rpy(match)
                                existing_texts.add(u)
                    except Exception: continue

        # Filter mapping to only include new/missing translations
        export_mapping = {k: v for k, v in mapping.items() if k not in existing_texts}
        
        if not export_mapping:
            logger.info("All strings already exist in .rpy files. Skipping redundant export.")
            return True
            
        export_file_path = os.path.join(tl_dir, f"zz_rl_exported_{target_lang}.rpy")
        
        lines = [
            "# Exported from RenLocalizer strings.json",
            f"# Target Language: {target_lang}",
            "",
            f"translate {target_lang} strings:",
            ""
        ]
        
        count = 0
        skipped_dynamic = 0
        for orig, trans in export_mapping.items():
            if not orig or not trans: continue
            if skip_dynamic and _has_dynamic_variables(orig):
                skipped_dynamic += 1
                continue
            safe_orig = orig.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\t', '\\t')
            safe_trans = trans.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\t', '\\t')
            lines.append(f'    old "{safe_orig}"\n    new "{safe_trans}"\n')
            count += 1
            
        if skipped_dynamic > 0:
            logger.info(f"Skipped {skipped_dynamic} dynamic texts (handled by micro hook)")
        if count > 0:
            save_text_safely(Path(export_file_path), "\n".join(lines), encoding='utf-8-sig', newline='\n')
            logger.info(f"Exported {count} unique strings to {export_file_path}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error exporting strings: {e}")
        return False
