# -*- coding: utf-8 -*-
"""
Saving-stage functions extracted from TranslationPipeline.
Includes strings.json generation, runtime hook management, variant synthesis,
coverage warnings, and translation report writing.
"""

import os
import re
import json
import time
import logging
from typing import List, Dict, Optional, Tuple, Any, Set
from pathlib import Path

from .constants import (
    RENPY_TO_API_LANG, HOTKEY_SOURCE_RE, HOTKEY_VISIBLE_RE,
    ANGLE_WRAPPED_SINGLE_RE, VISIBLE_TEXT_APOSTROPHES, VISIBLE_TEXT_DASHES,
    VISIBLE_TEXT_SENTENCE_RE, VISIBLE_TEXT_BRIDGE_PREFIXES,
    TRANSLATION_ID_KEY_RE, COVERAGE_WARNING_UI_KEYS,
)
from .translating import classify_translation_corruption
from .validating import is_runtime_hook_enabled as _is_runtime_hook_enabled

logger = logging.getLogger(__name__)


def synthesize_hotkey_visible_variants(mapping: Dict[str, str]) -> Dict[str, str]:
    additions: Dict[str, str] = {}
    for original, translated in list(mapping.items()):
        match = HOTKEY_SOURCE_RE.match((original or '').strip())
        if not match:
            continue
        label = match.group('label').strip()
        hotkey = match.group('hotkey').upper()
        visible_key = f"{label} [{hotkey}]"
        translated_stripped = (translated or '').strip()
        translated_label = translated_stripped

        translated_hotkey_match = HOTKEY_SOURCE_RE.match(translated_stripped)
        if translated_hotkey_match:
            translated_label = translated_hotkey_match.group('label').strip()
        else:
            visible_match = HOTKEY_VISIBLE_RE.match(translated_stripped)
            if visible_match and visible_match.group('hotkey').upper() == hotkey:
                translated_label = visible_match.group('label').strip()

        visible_value = f"{translated_label} [{hotkey}]"
        if (
            visible_key
            and visible_value
            and visible_key != visible_value
            and visible_key not in mapping
            and visible_key not in additions
        ):
            additions[visible_key] = visible_value
    return additions


def _unwrap_single_angle_text(text: str) -> Optional[str]:
    stripped = (text or '').strip()
    if not stripped:
        return None
    match = ANGLE_WRAPPED_SINGLE_RE.match(stripped)
    if match:
        return match.group('label').strip() or None
    if stripped.startswith('<') and stripped.endswith('>') and '|' not in stripped:
        return stripped[1:-1].strip() or None
    if stripped.startswith('<') and '|' not in stripped:
        return stripped[1:].strip() or None
    if stripped.endswith('>') and '|' not in stripped:
        return stripped[:-1].strip() or None
    return None


def synthesize_angle_wrapper_variants(mapping: Dict[str, str]) -> Dict[str, str]:
    additions: Dict[str, str] = {}
    for original, translated in list(mapping.items()):
        inner_original = _unwrap_single_angle_text(original)
        if not inner_original:
            continue
        translated_stripped = (translated or '').strip()
        inner_translated = _unwrap_single_angle_text(translated_stripped) or translated_stripped
        inner_translated = inner_translated.strip()
        if (
            not inner_translated
            or inner_original == inner_translated
            or inner_original in mapping
            or inner_original in additions
        ):
            continue
        additions[inner_original] = inner_translated
    return additions


def generate_visible_text_aliases(text: str) -> List[str]:
    stripped = (text or '').strip()
    if not stripped:
        return []
    variants: set[str] = set()
    if any(ch in stripped for ch in VISIBLE_TEXT_APOSTROPHES):
        for apostrophe in VISIBLE_TEXT_APOSTROPHES:
            candidate = stripped
            for current in VISIBLE_TEXT_APOSTROPHES:
                candidate = candidate.replace(current, apostrophe)
            if candidate != stripped:
                variants.add(candidate)
    if "..." in stripped:
        variants.add(stripped.replace("...", "\u2026"))
    if "\u2026" in stripped:
        variants.add(stripped.replace("\u2026", "..."))
    for dash in VISIBLE_TEXT_DASHES:
        if dash in stripped:
            for replacement in VISIBLE_TEXT_DASHES:
                if replacement != dash:
                    variants.add(stripped.replace(dash, replacement))
    normalized_space = re.sub(r"\s+", " ", stripped.replace("\u00a0", " ")).strip()
    if normalized_space != stripped:
        variants.add(normalized_space)
    return sorted(v for v in variants if v and v != stripped)


def synthesize_visible_text_variants(mapping: Dict[str, str]) -> Dict[str, str]:
    additions: Dict[str, str] = {}
    blocked: set[str] = set()
    for original, translated in list(mapping.items()):
        translated_stripped = (translated or '').strip()
        if not translated_stripped:
            continue
        for alias in generate_visible_text_aliases(original):
            if alias in blocked:
                continue
            if alias in mapping:
                blocked.add(alias)
                additions.pop(alias, None)
                continue
            existing = additions.get(alias)
            if existing is not None and existing != translated_stripped:
                blocked.add(alias)
                additions.pop(alias, None)
                continue
            additions[alias] = translated_stripped
    return additions


def _split_visible_sentences(text: str) -> List[str]:
    stripped = (text or '').strip()
    if not stripped:
        return []
    parts = [match.group(0).strip() for match in VISIBLE_TEXT_SENTENCE_RE.finditer(stripped)]
    return [part for part in parts if part]


def _build_bridge_prefixed_variant(text: str, prefix: str) -> Optional[str]:
    stripped = (text or '').strip()
    if not stripped:
        return None
    if stripped.lower().startswith(prefix.lower() + ' '):
        return None
    if stripped[0].isalpha():
        stripped = stripped[0].lower() + stripped[1:]
    return f"{prefix} {stripped}"


def synthesize_visible_fragment_variants(mapping: Dict[str, str], is_aggressive: bool = False) -> Dict[str, str]:
    additions: Dict[str, str] = {}
    blocked: set[str] = set()
    min_source_length = 64 if is_aggressive else 80
    min_source_sentences = 2 if is_aggressive else 3
    min_target_sentences = 1 if is_aggressive else 2
    max_count_limit = 3 if is_aggressive else 2
    min_fragment_length = 36 if is_aggressive else 48
    min_fragment_words = 5 if is_aggressive else 7

    for original, translated in list(mapping.items()):
        source = (original or '').strip()
        target = (translated or '').strip()
        if not source or not target:
            continue
        if len(source) < min_source_length:
            continue
        if any(token in source for token in ('[', ']', '{', '}')):
            continue

        source_sentences = _split_visible_sentences(source)
        target_sentences = _split_visible_sentences(target)
        if len(source_sentences) < min_source_sentences or len(target_sentences) < min_target_sentences:
            continue

        max_count = min(max_count_limit, len(source_sentences) - 1, len(target_sentences))
        for count in range(1, max_count + 1):
            source_fragment = ' '.join(source_sentences[:count]).strip()
            target_fragment = ' '.join(target_sentences[:count]).strip()
            if len(source_fragment) < min_fragment_length or source_fragment.count(' ') < min_fragment_words:
                continue

            candidate_keys = [source_fragment]
            for prefix in VISIBLE_TEXT_BRIDGE_PREFIXES:
                prefixed = _build_bridge_prefixed_variant(source_fragment, prefix)
                if prefixed:
                    candidate_keys.append(prefixed)

            for candidate in candidate_keys:
                if candidate in blocked:
                    continue
                if candidate in mapping:
                    blocked.add(candidate)
                    additions.pop(candidate, None)
                    continue
                existing = additions.get(candidate)
                if existing is not None and existing != target_fragment:
                    blocked.add(candidate)
                    additions.pop(candidate, None)
                    continue
                additions[candidate] = target_fragment

    return additions


def _normalize_runtime_alias_text(text: str) -> str:
    normalized = (text or '').strip()
    if not normalized:
        return ''
    for current in VISIBLE_TEXT_APOSTROPHES:
        normalized = normalized.replace(current, "'")
    normalized = normalized.replace('\u2026', '...')
    normalized = normalized.replace('\u2013', '-').replace('\u2014', '-').replace('\u2212', '-')
    normalized = re.sub(r'\s+', ' ', normalized.replace('\u00a0', ' ')).strip()
    return normalized.casefold()


def _find_runtime_alias_match_index(container_text: str, source_text: str) -> int:
    lowered_container = container_text.casefold()
    lowered_source = source_text.casefold()
    start = lowered_container.find(lowered_source)
    if start < 0:
        return -1
    end = start + len(source_text)
    before = container_text[start - 1] if start > 0 else ''
    after = container_text[end] if end < len(container_text) else ''
    if before and before.isalnum():
        return -1
    if after and after.isalnum():
        return -1
    return start


def _build_runtime_observed_alias(observed_text: str, source_text: str, translated_text: str) -> Optional[str]:
    observed = (observed_text or '').strip()
    source = (source_text or '').strip()
    translated = (translated_text or '').strip()
    if not observed or not source or not translated:
        return None
    if _normalize_runtime_alias_text(observed) == _normalize_runtime_alias_text(source):
        return translated
    start = _find_runtime_alias_match_index(observed, source)
    if start < 0:
        return None
    end = start + len(source)
    return observed[:start] + translated + observed[end:]


def synthesize_runtime_observed_variants(mapping: Dict[str, str], lang_dir: str, is_aggressive: bool = False) -> Dict[str, str]:
    log_path = Path(lang_dir) / 'diagnostics' / 'runtime_missed_strings.jsonl'
    if not log_path.is_file():
        return {}

    analysis = analyze_runtime_miss_log(str(log_path))
    additions: Dict[str, str] = {}
    blocked: set[str] = set()
    accepted_actions = {'promote_alias', 'review_candidate'} if is_aggressive else {'promote_alias'}
    min_source_length = 24 if is_aggressive else 32
    min_source_words = 3 if is_aggressive else 4
    normalized_mapping = {
        _normalize_runtime_alias_text(source): (source, target)
        for source, target in mapping.items()
        if source and target
    }

    for candidate in analysis.get('top_candidates', []):
        if candidate.get('suggested_action') not in accepted_actions:
            continue
        observed_text = (candidate.get('text') or '').strip()
        if not observed_text or observed_text in mapping or observed_text in blocked:
            continue

        matched_pairs: list[tuple[str, str]] = []
        normalized_observed = _normalize_runtime_alias_text(observed_text)
        exact_pair = normalized_mapping.get(normalized_observed)
        if exact_pair is not None:
            matched_pairs.append(exact_pair)
        else:
            for source_text, translated_text in mapping.items():
                source_clean = (source_text or '').strip()
                translated_clean = (translated_text or '').strip()
                if not source_clean or not translated_clean:
                    continue
                if len(source_clean) < min_source_length or source_clean.count(' ') < min_source_words:
                    continue
                if any(token in source_clean for token in ('[', ']', '{', '}')):
                    continue
                if _find_runtime_alias_match_index(observed_text, source_clean) >= 0:
                    matched_pairs.append((source_clean, translated_clean))
                if len(matched_pairs) > 1:
                    break

        if len(matched_pairs) != 1:
            if len(matched_pairs) > 1:
                blocked.add(observed_text)
                additions.pop(observed_text, None)
            continue

        source_text, translated_text = matched_pairs[0]
        alias_value = _build_runtime_observed_alias(observed_text, source_text, translated_text)
        if not alias_value or alias_value == observed_text:
            continue

        existing = additions.get(observed_text)
        if existing is not None and existing != alias_value:
            blocked.add(observed_text)
            additions.pop(observed_text, None)
            continue
        additions[observed_text] = alias_value

    return additions


def analyze_runtime_miss_log(log_path: str) -> Dict[str, Any]:
    from src.core.runtime_coverage import load_runtime_miss_log, score_runtime_miss_entries, summarize_runtime_miss_scores
    entries = load_runtime_miss_log(log_path)
    scored = score_runtime_miss_entries(entries)
    summary = summarize_runtime_miss_scores(entries)
    return {
        'summary': summary,
        'top_candidates': [
            {
                'text': item.text,
                'score': item.score,
                'confidence': item.confidence,
                'suggested_action': item.suggested_action,
                'risk': item.risk,
                'reasons': item.reasons,
                'entry': item.entry,
            }
            for item in scored[:50]
        ],
    }


def write_translation_reports(lang_dir: str, target_language: str, diagnostic_report,
                                translation_guard_counts, translation_guard_events,
                                translation_guard_sample_limit, log_emit, config) -> Optional[str]:
    from src.utils.encoding import save_text_safely

    diag_dir = os.path.join(lang_dir, 'diagnostics')
    os.makedirs(diag_dir, exist_ok=True)
    diag_path = os.path.join(diag_dir, f'diagnostic_{target_language}.json')
    diagnostic_report.write(diag_path)
    log_emit('info', config.get_log_text('log_diagnostic_written', path=diag_path))

    report_path = os.path.join(diag_dir, 'translation_blocked_or_fallback.json')
    payload = {
        'generated_at': int(time.time()),
        'counts': dict(translation_guard_counts),
        'sample_limit': translation_guard_sample_limit,
        'samples': translation_guard_events,
    }
    save_text_safely(Path(report_path), json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return diag_path


def emit_coverage_warning_summary(diagnostic_report, config, log_emit, last_diagnostic_path: Optional[str] = None) -> None:
    warnings = getattr(diagnostic_report, 'coverage_warnings', [])
    if not warnings:
        return

    for warning in warnings[:3]:
        text_key = COVERAGE_WARNING_UI_KEYS.get(warning.get('code', ''), '')
        default_text = warning.get('code', 'warning')
        localized = config.get_ui_text(text_key, default_text).format(count=warning.get('count', 0))
        log_emit('warning', f"\u26a0\ufe0f {localized}")

    if last_diagnostic_path:
        report_line = config.get_ui_text('coverage_warning_report_path', 'Diagnostics report: {path}').format(path=last_diagnostic_path)
        log_emit('warning', report_line)


def manage_runtime_hook(project_path: str, target_language: str, config, log_emit) -> None:
    """Manages the runtime translation hook script based on settings."""
    from src.core.runtime_hook_template import render_runtime_hook
    from src.utils.encoding import save_text_safely

    if not project_path:
        return

    try:
        game_dir = Path(project_path) / "game"
        if not game_dir.exists():
            return

        hook_filename = "zzz_renlocalizer_runtime.rpy"
        hook_path = game_dir / hook_filename

        for old in game_dir.glob("*_renlocalizer_*.rpy"):
            if old.name != hook_filename:
                old.unlink(missing_ok=True)

        should_exist = _is_runtime_hook_enabled(config)

        target_lang = target_language or getattr(config.translation_settings, 'target_language', 'turkish') or 'turkish'
        reverse_lang_map = {v.lower(): k for k, v in RENPY_TO_API_LANG.items()}
        renpy_lang = reverse_lang_map.get(target_lang.lower(), target_lang)

        use_native = getattr(config.translation_settings, 'output_mode', 'strings') == 'native'

        if use_native:
            if hook_path.exists():
                os.remove(hook_path)
            hook_pyc_rm = game_dir / (hook_filename + "c")
            if hook_pyc_rm.exists():
                try:
                    os.remove(hook_pyc_rm)
                except Exception:
                    logger.debug("Failed to remove .rpyc hook file (rm variant)")
            log_emit('info', config.get_ui_text("log_hook_removed").replace("{filename}", hook_filename))
        elif should_exist:
            content = render_runtime_hook(
                renpy_lang,
                runtime_string_diagnostics=getattr(
                    config.translation_settings,
                    "runtime_string_diagnostics",
                    False,
                ),
            )
            save_text_safely(hook_path, content, encoding="utf-8")
            hook_pyc_std = game_dir / (hook_filename + "c")
            if hook_pyc_std.exists():
                try:
                    os.remove(hook_pyc_std)
                except Exception:
                    logger.debug("Failed to remove .rpyc hook file (std variant)")
            log_emit('info', config.get_ui_text("log_hook_installed").replace("{filename}", hook_filename))
        else:
            if hook_path.exists():
                os.remove(hook_path)
            hook_pyc_rm = game_dir / (hook_filename + "c")
            if hook_pyc_rm.exists():
                try:
                    os.remove(hook_pyc_rm)
                except Exception:
                    logger.debug("Failed to remove .rpyc hook file (duplicate rm)")
            log_emit('info', config.get_ui_text("log_hook_removed").replace("{filename}", hook_filename))

    except Exception as e:
        logger.warning(f"Failed to manage runtime hook: {e}")


def create_language_init_file(game_dir: str, target_language: str, config, log_emit, lang_map=None) -> None:
    """Dil başlangıç dosyasını oluşturur."""
    from src.utils.encoding import save_text_safely

    try:
        lang_map_val = lang_map if lang_map is not None else RENPY_TO_API_LANG
        language_code = (target_language or '').strip().lower()
        if not language_code:
            try:
                language_code = getattr(config.translation_settings, 'target_language', '') or ''
            except Exception:
                language_code = ''
        original_input = language_code
        reverse_lang_map = {v.lower(): k for k, v in lang_map_val.items()}
        if language_code:
            language_code = reverse_lang_map.get(language_code, language_code)
        else:
            tl_root = Path(game_dir) / "tl"
            subdirs = sorted([p.name for p in tl_root.iterdir() if p.is_dir()]) if tl_root.exists() else []
            if len(subdirs) == 1:
                language_code = subdirs[0].lower()
            else:
                language_code = 'turkish'

        try:
            for existing in Path(game_dir).glob("*_language.rpy"):
                if "renlocalizer" in existing.name or existing.name.startswith("a0_") or existing.name.startswith("zzz_"):
                    if existing.name != f"zzz_{language_code}_language.rpy":
                        existing.unlink(missing_ok=True)
        except Exception:
            logger.debug("Failed to clean up existing language init files")

        init_file = os.path.join(game_dir, f'zzz_{language_code}_language.rpy')
        if os.path.exists(init_file):
            os.remove(init_file)

        safe_code = language_code.replace("-", "_").replace(" ", "_").replace(".", "_")

        content = f'''# ============================================================
# RenLocalizer - Safe Language Activation v2.7.5
# ============================================================
# Bu dosya oyunun dilini {language_code.title()}'ye ayarlar.
#
# KRITIK: init -2'den ONCE (gui.init oncesi) hicbir config/screen
# islemi yapilmaz. Bu, IndexError crash'ini onler.
#
# Ren'Py dil secim onceligi (dokumantasyondan):
#   1. config.language (None degilse, diger HER SEYI ezer)
#   2. Kullanicinin daha once sectigi dil
#   3. config.enable_language_autodetect
#   4. config.default_language
#   5. None (varsayilan dil)

# ============================================================
# PHASE 1: Safe Language Override (AFTER gui.init)
# ============================================================
define config.language = "{language_code}"

# ============================================================
# PHASE 2: Runtime Enforcement (Game Start Hook)
# ============================================================
init python:
    def _rl_force_{safe_code}_language():
        """
        Oyun her basladiginda dili kontrol et ve gerekirse {language_code.title()}'ye cevir.
        """
        try:
            current = getattr(_preferences, 'language', None)
            if current != "{language_code}":
                renpy.change_language("{language_code}")
        except Exception:
            logger.debug("Template string reference evaluation failed")

    if _rl_force_{safe_code}_language not in config.start_callbacks:
        config.start_callbacks.append(_rl_force_{safe_code}_language)

# ============================================================
# PHASE 3: Persistent Override (Save File Protection)
# ============================================================
init python:
    try:
        if hasattr(persistent, "language"):
            persistent.language = "{language_code}"
        if hasattr(persistent, "game_language"):
            persistent.game_language = "{language_code}"
        if hasattr(persistent, "selected_language"):
            persistent.selected_language = "{language_code}"
    except Exception:
        logger.debug("Template string persistent reference evaluation failed")
'''
        save_text_safely(Path(init_file), content, encoding='utf-8-sig', newline='\n')
        log_emit("info", config.get_ui_text("pipeline_lang_init_created").replace("{path}", init_file))

    except Exception as e:
        log_emit("warning", config.get_ui_text("pipeline_lang_init_failed").format(error=e))


def write_atomic_segments_rpy(tl_dir: str, renpy_lang: str) -> None:
    """DEPRECATED (v2.7.1 hotfix) — Bu metod artık çağrılmıyor."""
    logger.debug("_write_atomic_segments_rpy is deprecated, skipping")
    return
