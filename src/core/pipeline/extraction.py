# -*- coding: utf-8 -*-
"""
Extraction-stage functions: UNRPA, GENERATING, PARSING.
Converts methods from TranslationPipeline into independent functions.
"""

import os
import re
import ast
import time
import logging
import hashlib
import json
import tempfile
import shutil
from typing import List, Dict, Optional, Tuple, Any, Union
from pathlib import Path

from .constants import (
    RENPY_TO_API_LANG, COVERAGE_AUDIT_EXCLUDE_DIRS, QUOTED_LITERAL_RE,
    TEXTUAL_UI_HINT_RE, HELPER_PROPERTY_RE, IMAGE_ONLY_BLOCK_RE,
    DYNAMIC_UI_LINE_RE, RENPY_KEYWORDS_TO_SKIP,
)
from .validating import has_rpyc_files, has_rpy_files, is_generated_export_file
from src.core.output_formatter import format_renpy_speaker

logger = logging.getLogger(__name__)


def run_extraction(project_path: str, config, log_emit, log_error) -> bool:
    """RPA arşivlerini unrpa ile aç (tüm platformlarda çalışır)."""
    try:
        log_emit("info", config.get_log_text('unren_starting'))
        from src.utils.unrpa_adapter import UnrpaAdapter
        from pathlib import Path as _Path

        adapter = UnrpaAdapter()
        if not adapter.is_available():
            log_emit("error", config.get_log_text('log_unrpa_not_installed'))
            return False

        project_path_obj = _Path(project_path)
        game_dir = project_path_obj / "game"

        if not game_dir.exists():
            if project_path_obj.name == "game":
                game_dir = project_path_obj
            else:
                game_dir = project_path_obj

        log_emit("info", config.get_log_text('log_rpa_extracting', path=game_dir))

        try:
            success = adapter.extract_game(game_dir)
            if success:
                log_emit("info", config.get_log_text('unren_completed'))
                return True
            else:
                log_emit("info", config.get_log_text('log_rpa_not_found_or_extracted'))
                if has_rpyc_files(str(game_dir)):
                    log_emit("info", config.get_log_text('log_rpyc_continue'))
                    return True
                return False
        except Exception as e:
            log_emit("error", config.get_log_text('log_rpa_error', error=str(e)))
            if has_rpyc_files(str(game_dir)):
                log_emit("info", config.get_log_text('log_rpyc_fallback_continue'))
                return True
            return False

    except Exception as e:
        log_emit("error", config.get_log_text('unren_general_error', error=str(e)))
        return False


def cleanup_legacy_mod_files(game_dir: str, log_emit) -> int:
    """UnRen'in eklediği mod dosyalarını temizle."""
    cleanup_patterns = [
        "unren-console.rpy", "unren-console.rpyc",
        "unren-qmenu.rpy", "unren-qmenu.rpyc",
        "unren-quick.rpy", "unren-quick.rpyc",
        "unren-rollback.rpy", "unren-rollback.rpyc",
        "unren-skip.rpy", "unren-skip.rpyc",
    ]

    deleted_count = 0
    for filename in cleanup_patterns:
        filepath = os.path.join(game_dir, filename)
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                log_emit("info", config.get_log_text('unren_mod_deleted', filename=filename)
                    if config else f"Temizlendi: {filename}")
                deleted_count += 1
        except Exception as e:
            log_emit("warning", f"Silinemedi {filename}: {e}")

    return deleted_count


def escape_rpy_string(text: str) -> str:
    """Ren'Py string formatı için escape et"""
    if not text:
        return text
    text = text.replace('\\', '\\\\')
    text = text.replace('"', '\\"')
    text = text.replace('\n', '\\n')
    text = text.replace('\t', '\\t')
    return text


def encode_say_string_for_tlid(text: str) -> str:
    """Mirror Ren'Py's own `encode_say_string()` (renpy/ast.py) so that the MD5
    hash we compute for a fallback Native TLID matches what Ren'Py's compiler
    would hash for the same dialogue line. Order matters: backslash first,
    then newline/quote, then the "second of two consecutive spaces" rule.
    """
    if not text:
        return text
    text = text.replace('\\', '\\\\')
    text = text.replace('\n', '\\n')
    text = text.replace('"', '\\"')
    text = re.sub(r'(?<= ) ', '\\ ', text)
    return text


def is_nontranslatable_identifier_entry(entry) -> bool:
    """style_prefix gibi kimlik/anahtar tipindeki girdiler çevrilmemeli."""
    try:
        if isinstance(entry, dict):
            character = (entry.get('character') or '').strip().lower()
        else:
            character = (getattr(entry, 'character', '') or '').strip().lower()
        return character == 'style_prefix'
    except Exception:
        return False


def make_source_translatable(game_dir: str, config, log_emit, log_error) -> int:
    """
    Kaynak .rpy dosyalarındaki UI metinlerini çevrilebilir hale getirir.
    textbutton "Text" -> textbutton _("Text")
    Returns: Değiştirilen dosya sayısı
    """
    from src.utils.encoding import read_text_safely, save_text_safely

    patterns = [
        (r"(textbutton\s+)(['\"])([^'\"]+)\2(?=\s|$|:)",
         r'\1_(\2\3\2)'),
        (r"(\btext\s+)(['\"])([^'\"\[\]]+)\2(?=\s|$|:)",
         r'\1_(\2\3\2)'),
        (r"(tooltip\s+)(['\"])([^'\"]+)\2",
         r'\1_(\2\3\2)'),
        (r"(renpy\.notify\s*\(\s*)(['\"])([^'\"]+)\2(\s*\))",
         r'\1_(\2\3\2)\4'),
        (r"(Notify\s*\(\s*)(['\"])([^'\"]+)\2(\s*\))",
         r'\1_(\2\3\2)\4'),
        (r"(title\s*=\s*)(['\"])([^'\"]+)\2",
         r'\1_(\2\3\2)'),
        (r"(message\s*=\s*)(['\"])([^'\"]+)\2",
         r'\1_(\2\3\2)'),
        (r"(\byes\s*=\s*)(['\"])([^'\"]+)\2",
         r'\1_(\2\3\2)'),
        (r"(\bno\s*=\s*)(['\"])([^'\"]+)\2",
         r'\1_(\2\3\2)'),
        (r"(\balt\s*=\s*)(['\"])([^'\"]+)\2",
         r'\1_(\2\3\2)'),
    ]

    skip_patterns = [
        r'_\s*\(\s*[\'"]',
        r'[\'\"]\s*\+\s*[\'"]',
        r'^\s*#',
        r'^\s*$',
        r'define\s+',
        r'default\s+',
        r'=\s*[\'"][^\'"]*[\'"]\s*$',
        r'[\'"][^\'"]*\[[^\]]+\][^\'"]*[\'"]',
        r'\.format\s*\(',
        r'[\'"][^\'"]*\{\s*\}[^\'"]*[\'"]',
        r'[\'"][^\'"]*\{\d+[^}]*\}[^\'"]*[\'"]',
        r'[\'"][^\'"]*\{:[^}]+\}[^\'"]*[\'"]',
    ]

    modified_count = 0
    rpy_dir = os.path.join(game_dir, 'rpy')
    if not os.path.isdir(rpy_dir):
        rpy_dir = game_dir

    try:
        for root, dirs, files in os.walk(rpy_dir):
            if 'tl' in dirs:
                dirs.remove('tl')
            dirs[:] = [d for d in dirs if d.lower() != 'renpy']

            for filename in files:
                if not filename.lower().endswith('.rpy'):
                    continue

                filepath = os.path.join(root, filename)
                try:
                    content = read_text_safely(Path(filepath))
                    if content is None:
                        log_emit('warning', f"{filename} dosyası okunamadı (encoding)")
                        continue

                    original_content = content

                    for pattern, replacement in patterns:
                        lines = content.split('\n')
                        new_lines = []
                        for line in lines:
                            should_skip = False
                            for skip in skip_patterns:
                                if re.search(skip, line):
                                    should_skip = True
                                    break
                            if not should_skip:
                                line = re.sub(pattern, replacement, line)
                            new_lines.append(line)
                        content = '\n'.join(new_lines)

                    if content != original_content:
                        save_text_safely(Path(filepath), content, encoding='utf-8-sig', newline='\n')
                        modified_count += 1

                except Exception as e:
                    msg = f"Dosya işlenemedi {filename}: {e}"
                    log_emit("warning", msg)
                    log_error(msg)
                    continue

        if modified_count > 0:
            log_emit("info", config.get_log_text('source_files_made_translatable', count=modified_count)
                if config else f"{modified_count} dosya çevrilebilir hale getirildi.")

    except Exception as e:
        log_emit("warning", config.get_log_text('source_files_error', error=str(e))
            if config else f"Kaynak dosya hatası: {e}")

    return modified_count


def _decode_literal_candidate(raw_literal: str) -> str:
    try:
        value = ast.literal_eval(raw_literal)
        return value if isinstance(value, str) else ""
    except Exception:
        return raw_literal.strip('"\'')


def _block_has_textual_hint(parser, block_lines: List[str]) -> bool:
    for line in block_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if TEXTUAL_UI_HINT_RE.search(line):
            return True
        if not HELPER_PROPERTY_RE.match(line) and 'Notify(' not in line:
            continue
        for raw_literal in QUOTED_LITERAL_RE.findall(line):
            candidate = _decode_literal_candidate(raw_literal)
            if candidate and parser.is_meaningful_text(candidate):
                return True
    return False


def _iter_audit_files(game_dir: str, extension: str):
    for root, dirs, files in os.walk(game_dir):
        dirs[:] = [d for d in dirs if d.lower() not in COVERAGE_AUDIT_EXCLUDE_DIRS]
        for filename in files:
            if filename.lower().endswith(extension):
                yield Path(root) / filename


def _relative_audit_path(game_dir: str, file_path: Path) -> str:
    try:
        return file_path.relative_to(game_dir).as_posix()
    except Exception:
        return file_path.as_posix()


def audit_image_only_ui(game_dir: str, config) -> Dict[str, Any] | None:
    from src.core.parser import RenPyParser
    from src.utils.encoding import read_text_safely

    parser = RenPyParser(config)
    samples: List[Dict[str, Any]] = []
    count = 0

    for file_path in _iter_audit_files(game_dir, '.rpy'):
        content = read_text_safely(file_path)
        if not content:
            continue
        lines = content.splitlines()
        idx = 0
        while idx < len(lines):
            raw_line = lines[idx]
            match = IMAGE_ONLY_BLOCK_RE.match(raw_line)
            if not match:
                idx += 1
                continue

            start_idx = idx
            block_lines = [raw_line]
            stripped = raw_line.strip()
            base_indent = len(raw_line) - len(raw_line.lstrip())
            idx += 1

            if stripped.endswith(':'):
                while idx < len(lines):
                    next_line = lines[idx]
                    next_stripped = next_line.strip()
                    if next_stripped and not next_stripped.startswith('#'):
                        next_indent = len(next_line) - len(next_line.lstrip())
                        if next_indent <= base_indent:
                            break
                    block_lines.append(next_line)
                    idx += 1

            if _block_has_textual_hint(parser, block_lines):
                continue

            count += 1
            if len(samples) < 20:
                samples.append({
                    'file_path': _relative_audit_path(game_dir, file_path),
                    'line_number': start_idx + 1,
                    'kind': match.group('kind'),
                })

    if not count:
        return None
    return {
        'code': 'image_only_ui',
        'count': count,
        'samples': samples,
    }


def audit_compiled_only_scripts(game_dir: str, config, include_rpyc: bool = False) -> Dict[str, Any] | None:
    rpyc_enabled = bool(
        getattr(config.translation_settings, 'enable_rpyc_reader', False)
        or include_rpyc
    )
    if rpyc_enabled:
        return None

    rpy_paths = {
        _relative_audit_path(game_dir, path.with_suffix(''))
        for path in _iter_audit_files(game_dir, '.rpy')
    }
    rpyc_only = sorted(
        _relative_audit_path(game_dir, path)
        for path in _iter_audit_files(game_dir, '.rpyc')
        if _relative_audit_path(game_dir, path.with_suffix('')) not in rpy_paths
    )
    if not rpyc_only:
        return None
    return {
        'code': 'compiled_only_scripts',
        'count': len(rpyc_only),
        'samples': [{'file_path': path} for path in rpyc_only[:20]],
    }


def audit_dynamic_ui_runtime(game_dir: str, config, runtime_hook_enabled: bool = False) -> Dict[str, Any] | None:
    from src.utils.encoding import read_text_safely

    if runtime_hook_enabled:
        return None

    samples: List[Dict[str, Any]] = []
    count = 0
    for file_path in _iter_audit_files(game_dir, '.rpy'):
        content = read_text_safely(file_path)
        if not content:
            continue
        for idx, raw_line in enumerate(content.splitlines(), start=1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            if not DYNAMIC_UI_LINE_RE.search(raw_line):
                continue
            count += 1
            if len(samples) < 20:
                samples.append({
                    'file_path': _relative_audit_path(game_dir, file_path),
                    'line_number': idx,
                    'preview': stripped[:160],
                })

    if not count:
        return None
    return {
        'code': 'dynamic_ui_runtime',
        'count': count,
        'samples': samples,
    }


def collect_coverage_warnings(game_dir: str, config, diagnostic_report, runtime_hook_enabled: bool = False, include_rpyc: bool = False) -> List[Dict[str, Any]]:
    from .validating import is_runtime_hook_enabled as _hook_enabled

    warnings: List[Dict[str, Any]] = []
    hook_on = runtime_hook_enabled or _hook_enabled(config)

    for collector in (
        audit_image_only_ui,
        audit_compiled_only_scripts,
        audit_dynamic_ui_runtime,
    ):
        try:
            if collector is audit_dynamic_ui_runtime:
                warning = collector(game_dir, config, runtime_hook_enabled=hook_on)
            elif collector is audit_compiled_only_scripts:
                warning = collector(game_dir, config, include_rpyc=include_rpyc)
            else:
                warning = collector(game_dir, config)
        except Exception as exc:
            logger.debug("Coverage audit '%s' failed: %s", collector.__name__, exc)
            continue
        if warning:
            warnings.append(warning)
            diagnostic_report.add_coverage_warning(
                warning['code'],
                warning['count'],
                samples=warning.get('samples'),
            )
    return warnings


def reopen_stale_tl_entries(tl_files, config, diagnostic_report, record_translation_guard_event) -> Dict[str, int]:
    """Reopen stale TL entries for retranslation."""
    from .translating import classify_translation_corruption

    reopened_counts = {
        'reopened': 0,
        'corrupted': 0,
        'unchanged_core_ui': 0,
    }

    from .constants import CORE_UI_RETRY_STRINGS

    for tl_file in tl_files:
        for entry in tl_file.entries:
            translated = (entry.translated_text or '').strip()
            if not translated:
                continue

            reason: Optional[str] = None
            corruption_reason = classify_translation_corruption(entry.original_text, translated)
            if corruption_reason is not None:
                reason = 'corrupted'
                detail = corruption_reason
            elif translated == (entry.original_text or '').strip() and (entry.original_text or '').strip() in CORE_UI_RETRY_STRINGS:
                reason = 'unchanged_core_ui'
                detail = 'unchanged_core_ui'
            else:
                continue

            reopened_counts['reopened'] += 1
            reopened_counts[reason] += 1
            entry.translated_text = ''
            record_translation_guard_event(
                category='reopened_for_retranslation',
                file_path=entry.file_path or tl_file.file_path,
                translation_id=entry.translation_id or entry.compute_id(),
                original_text=entry.original_text,
                translated_text=translated,
                detail=detail,
                line_number=entry.line_number,
            )

    return reopened_counts


def generate_all_strings_file(
    entries: List[dict],
    game_dir: str,
    target_language: str,
    source_language: str,
    engine,
    translation_manager,
    config,
    log_emit,
    lang_name: str = None,
) -> Optional[str]:
    """
    Tüm çevrilecek metinleri (diyalog + UI) tek bir strings.rpy dosyasında topla.
    """
    from src.core.output_formatter import RenPyOutputFormatter

    formatter = RenPyOutputFormatter()
    skipped = 0
    lines = []
    lines.append("# Translation strings file")
    lines.append("# Auto-generated by RenLocalizer")
    lines.append("# Using Ren'Py String Translation format for maximum compatibility")
    lines.append("")

    target_lang = lang_name if lang_name else target_language
    rel_path_cache = {}
    seen_texts = set()
    entries_added = 0

    for i, entry in enumerate(entries):
        text = entry.get('text', '')
        if not text or formatter._should_skip_translation(text):
            skipped += 1
            continue

        if text in seen_texts:
            continue
        seen_texts.add(text)

        file_path = entry.get('file_path', '')
        line_num = entry.get('line_number', 0)
        character = entry.get('character', '')
        text_type = entry.get('text_type', 'unknown')
        is_nontranslatable = is_nontranslatable_identifier_entry(entry)

        escaped_text = escape_rpy_string(text)

        if file_path in rel_path_cache:
            rel_path = rel_path_cache[file_path]
        else:
            rel_path = 'unknown'
            if file_path:
                try:
                    rel_path = os.path.relpath(file_path, game_dir)
                except ValueError:
                    rel_path = os.path.abspath(file_path)
            rel_path_cache[file_path] = rel_path

        entry_lines = []

        comment_parts = [f"{rel_path}:{line_num}"]
        if character:
            comment_parts.append(f"({character})")
        if text_type and text_type != 'dialogue':
            comment_parts.append(f"[{text_type}]")
        if entry.get('is_engine_common'):
            comment_parts.append('[engine_common]')

        entry_lines.append(f"    # {' '.join(comment_parts)}")

        cached_translation = ""
        if translation_manager and not is_nontranslatable:
            api_target = RENPY_TO_API_LANG.get(target_language, target_language)
            api_source = RENPY_TO_API_LANG.get(source_language, source_language)
            cache_key = (engine.value, api_source, api_target, text)
            cached_res = translation_manager._cache.get(cache_key)

            if not cached_res:
                for k, v in translation_manager._cache.items():
                    if len(k) >= 4 and k[2] == api_target and k[3] == text:
                        cached_res = v
                        break

            if cached_res and cached_res.success:
                cached_translation = escape_rpy_string(cached_res.translated_text)

        if is_nontranslatable:
            cached_translation = escaped_text

        entry_lines.append(f'    old "{escaped_text}"')
        entry_lines.append(f'    new "{cached_translation}"')
        entry_lines.append("")

        lines.extend(entry_lines)
        entries_added += 1

        if i % 100 == 0:
            time.sleep(0.001)

    if entries_added == 0:
        return None

    header = [
        "# Translation strings file",
        "# Auto-generated by RenLocalizer",
        "# Using Ren'Py String Translation format for maximum compatibility",
        "",
        f"translate {target_lang} strings:",
        ""
    ]

    if skipped:
        try:
            log_emit("debug", config.get_log_text('technical_entries_skipped', count=skipped)
                if config else f"Teknik girdiler atlandı: {skipped}")
        except Exception:
            pass

    return '\n'.join(header + lines)


def generate_native_tlid_content(
    entries: List[dict],
    game_dir: str,
    target_language: str = "turkish",
    source_language: str = "english",
    engine=None,
    translation_manager=None,
    config=None,
    lang_name: str = None,
) -> str:
    """
    Generate native TLID format output for dialogues + strings: for UI text.
    """
    from src.core.output_formatter import RenPyOutputFormatter

    target_lang = lang_name or target_language
    formatter = RenPyOutputFormatter()

    lines = []
    lines.append("# Translation strings file")
    lines.append("# Auto-generated by RenLocalizer")
    lines.append("# Native TLID + String Translation format")
    lines.append("")

    seen_tlids: Dict[str, int] = {}
    seen_texts: set = set()
    entries_added = 0
    skipped = 0

    dialogue_entries = []
    string_entries = []

    for entry in entries:
        text = entry.get('text', '')
        if not text or formatter._should_skip_translation(text):
            skipped += 1
            continue
        if text in seen_texts:
            continue
        seen_texts.add(text)

        text_type = entry.get('text_type', '')
        if text_type in ('dialogue', 'narration', 'extend', 'bubble_dialogue', 'nvl_dialogue'):
            dialogue_entries.append(entry)
        else:
            string_entries.append(entry)

    if dialogue_entries:
        for entry in dialogue_entries:
            text = entry.get('text', '')
            who = entry.get('character', '')
            file_path = entry.get('file_path', '')

            if who and (
                ',' in who
                or ' and ' in who or ' y ' in who or ' et ' in who
                or ' und ' in who or ' e ' in who or ' i ' in who
                or ' en ' in who or ' ja ' in who or ' och ' in who
                or ' \u00e9s ' in who or ' dan ' in who or ' & ' in who
                or len(re.findall(r'\[', who)) >= 2
                or who.strip('"\'').lower() in RENPY_KEYWORDS_TO_SKIP
            ):
                string_entries.append(entry)
                continue

            fmt_who = format_renpy_speaker(who)
            source_line = f'{fmt_who} "{text}"' if fmt_who else f'"{text}"'
            escaped_source = source_line.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')

            # Real Ren'Py identifier from the compiled .rpyc AST (Translate/
            # TranslateSay node) is the exact id the game will look up at
            # runtime — use it verbatim instead of guessing a hash.
            real_id = str(entry.get('identifier') or '').strip()

            label = 'start'
            ctx = entry.get('context', '')
            ctx_path = entry.get('context_path', [])

            if ctx and 'label:' in str(ctx):
                for part in str(ctx).split('/'):
                    if part.startswith('label:'):
                        label = part.replace('label:', '')
                        break
            elif ctx_path:
                for p in ctx_path:
                    if p.lower().startswith('label:'):
                        label = p.replace('label:', '').replace('Label:', '')
                        break

            # Sanitize label to contain only valid Ren'Py identifier chars
            label = re.sub(r'[^a-zA-Z0-9_]', '_', label)

            if real_id:
                base_tlid = real_id
            else:
                # Fallback: no ground-truth id available (.rpy source not yet
                # compiled) — approximate it, matching encode_say_string() so
                # quotes/backslashes/newlines don't silently break the match.
                encoded_text = encode_say_string_for_tlid(text)
                hash_source = f'{who} "{encoded_text}"' if who else f'"{encoded_text}"'
                tlid_hash = hashlib.md5((hash_source + '\r\n').encode('utf-8')).hexdigest()[:8]
                base_tlid = f'{label}_{tlid_hash}'

            # Ensure TLID is a valid Ren'Py identifier without illegal characters (e.g. dots)
            base_tlid = re.sub(r'[^a-zA-Z0-9_]', '_', base_tlid)

            if base_tlid in seen_tlids:
                seen_tlids[base_tlid] += 1
                tlid = f'{base_tlid}_{seen_tlids[base_tlid]}'
            else:
                seen_tlids[base_tlid] = 0
                tlid = base_tlid

            if file_path:
                try:
                    rel = os.path.relpath(file_path, game_dir)
                except ValueError:
                    rel = file_path
                lines.append(f"# {rel}")

            lines.append(f"translate {target_lang} {tlid}:")
            lines.append("")
            lines.append(f'    # {escaped_source}')

            cached = ""
            if translation_manager:
                api_target = RENPY_TO_API_LANG.get(target_language, target_language)
                api_source = RENPY_TO_API_LANG.get(source_language, source_language)
                cache_key = (engine.value, api_source, api_target, text)
                cached_res = translation_manager._cache.get(cache_key)
                if cached_res and cached_res.success:
                    cached = escape_rpy_string(cached_res.translated_text)

            if cached:
                lines.append(f'    {fmt_who} "{cached}"' if fmt_who else f'    "{cached}"')
            else:
                lines.append(f'    {fmt_who} ""' if fmt_who else '    ""')

            lines.append("")
            entries_added += 1

    if not entries_added:
        return ""

    if skipped:
        logger.debug("Native TLID: %d technical entries skipped", skipped)

    return '\n'.join(lines)
