# -*- coding: utf-8 -*-
"""Reading and writing one game's tl/<language>/ folder for the editor."""
from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.constants import is_renlocalizer_generated_script
from src.core.tl_parser import TLParser
from src.utils.encoding import read_json_safely, read_text_safely, save_json_safely, save_text_safely

logger = logging.getLogger(__name__)

# define e = Character("Eileen") / Character(_("Eileen"), ...)
_CHARACTER_DEFINE_RE = re.compile(
    r"""^\s*(?:define|default)\s+(?P<var>[A-Za-z_][\w.]*)\s*=\s*(?:\w+\.)*Character\(\s*(?:_\(\s*)?(?P<q>["'])(?P<name>(?:(?!(?P=q)).)*)(?P=q)""",
    re.M,
)
_SKIP_DIRS = {"tl", "renpy", "cache", "saves"}


def _snapshot(path: str) -> Tuple[int, int]:
    st = os.stat(path)
    return st.st_mtime_ns, st.st_size


def speaker_names(game_dir: str) -> Dict[str, str]:
    """Map speaker variables to the names players read ("m" -> "Mia")."""
    names: Dict[str, str] = {}
    root = Path(game_dir)
    if not root.is_dir():
        return names
    for path in root.rglob("*.rpy"):
        rel_parts = {part.lower() for part in path.relative_to(root).parts[:-1]}
        if rel_parts & _SKIP_DIRS or is_renlocalizer_generated_script(path.name):
            continue
        text = read_text_safely(path)
        if not text or "Character" not in text:
            continue
        for m in _CHARACTER_DEFINE_RE.finditer(text):
            name = m.group("name").strip()
            if name:
                names.setdefault(m.group("var"), name)
    return names


@dataclass
class LoadedLanguage:
    rows: List[Dict[str, Any]] = field(default_factory=list)
    snapshots: Dict[str, Tuple[int, int]] = field(default_factory=dict)


def load_language(game_dir: str, language: str) -> LoadedLanguage:
    """Every translation slot in game/tl/<language>/ as editor rows."""
    lang_dir = os.path.join(game_dir, "tl", language)
    result = LoadedLanguage()
    if not os.path.isdir(lang_dir):
        return result
    names = speaker_names(game_dir)
    parser = TLParser()
    paths: List[str] = []
    for root, dirs, files in os.walk(lang_dir):
        dirs[:] = sorted(d for d in dirs if d.lower() != "renpy" and not d.startswith("."))
        for name in sorted(files):
            if name.lower().endswith(".rpy") and not is_renlocalizer_generated_script(name):
                paths.append(os.path.join(root, name))
    for path in paths:
        tl_file = parser.parse_file(path)
        if not tl_file:
            continue
        result.snapshots[path] = _snapshot(path)
        rel = Path(os.path.relpath(path, lang_dir)).as_posix()
        for e in tl_file.entries:
            speaker = e.character or ""
            result.rows.append({
                "file_path": path,
                "file_rel": rel,
                "line": e.line_number,
                "kind": e.entry_type,
                "block_id": e.block_id or "",
                "speaker": speaker,
                # A quoted speaker ("Shop Owner") is already the displayed name.
                "speaker_name": names.get(speaker, "") or (
                    speaker[1:-1] if len(speaker) >= 2 and speaker[0] == speaker[-1] and speaker[0] in "\"'" else ""),
                "source_ref": e.source_comment or "",
                "original": e.original_text,
                "translated": e.translated_text or "",
            })
    return result


@dataclass
class SaveResult:
    saved_ids: List[int] = field(default_factory=list)
    saved_files: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)   # changed on disk since loading
    failed_ids: List[int] = field(default_factory=list)  # slot no longer where it was
    errors: List[str] = field(default_factory=list)


def save_edits(
    edits_by_file: Dict[str, List[Dict[str, Any]]],
    snapshots: Dict[str, Tuple[int, int]],
    backup_dir: Optional[str] = None,
) -> SaveResult:
    """Write edited lines back into their tl files.

    A file that changed on disk after loading (a translation run, another
    editor) is not touched. The first save of a file in a session copies the
    original to *backup_dir* with a ``.bak`` suffix; Ren'Py loads every
    ``.rpy`` under game/, so a backup must never keep that extension.
    """
    parser = TLParser()
    result = SaveResult()
    for path, rows in edits_by_file.items():
        try:
            if snapshots.get(path) != _snapshot(path):
                result.conflicts.append(path)
                continue
            content = read_text_safely(Path(path))
            if content is None:
                result.errors.append(path)
                continue
            new_content, failed_lines = parser.apply_line_edits(content, [
                {"line": r["line"], "kind": r["kind"], "original": r["original"], "text": r["translated"]}
                for r in rows
            ])
            failed = set(failed_lines)
            if len(failed) < len(rows):
                if backup_dir:
                    _backup_once(path, backup_dir)
                if not save_text_safely(Path(path), new_content, encoding="utf-8-sig", newline="\n"):
                    result.errors.append(path)
                    continue
                snapshots[path] = _snapshot(path)
                result.saved_files.append(path)
            for r in rows:
                (result.failed_ids if r["line"] in failed else result.saved_ids).append(r["id"])
        except OSError as exc:
            logger.warning("Editor save failed for %s: %s", path, exc)
            result.errors.append(path)
    return result


def _backup_once(path: str, backup_dir: str) -> None:
    target = os.path.join(backup_dir, os.path.basename(path) + ".bak")
    if os.path.exists(target):
        return
    os.makedirs(backup_dir, exist_ok=True)
    shutil.copy2(path, target)


def sync_strings_json(lang_dir: str, changes: Dict[str, str]) -> int:
    """Update strings.json (runtime hook mode) for edited UI strings; returns entries changed."""
    json_path = os.path.join(lang_dir, "strings.json")
    if not changes or not os.path.isfile(json_path):
        return 0
    data = read_json_safely(json_path)
    if not isinstance(data, dict) or not isinstance(data.get("translations"), dict):
        return 0
    count = 0
    for section in ("translations", "dynamic"):
        mapping = data.get(section)
        if not isinstance(mapping, dict):
            continue
        for original, text in changes.items():
            if original in mapping and mapping[original] != text:
                mapping[original] = text
                count += 1
    if count:
        save_json_safely(json_path, data, indent=2)
    return count


def sync_translation_cache(cache_file: str, target_lang_codes: List[str], changes: Dict[str, str]) -> int:
    """Put hand-edited translations into the project's translation cache.

    Only an existing cache file is updated, and only entries for the given
    target language, so a later run (or a regenerated tl folder) reuses the
    edit instead of the old machine translation.
    """
    if not changes or not cache_file or not os.path.isfile(cache_file):
        return 0
    data = read_json_safely(cache_file)
    if not isinstance(data, dict):
        return 0
    wanted = {c.lower() for c in target_lang_codes if c}
    count = 0
    for sl_map in data.values():
        if not isinstance(sl_map, dict):
            continue
        for tl_map in sl_map.values():
            if not isinstance(tl_map, dict):
                continue
            for tl, text_map in tl_map.items():
                if tl.lower() not in wanted or not isinstance(text_map, dict):
                    continue
                for original, text in changes.items():
                    if original in text_map and text_map[original] != text:
                        text_map[original] = text
                        count += 1
    if count:
        save_json_safely(cache_file, data, indent=2)
    return count
