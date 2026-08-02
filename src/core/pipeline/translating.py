# -*- coding: utf-8 -*-
"""
Translation-stage functions extracted from TranslationPipeline.
"""

import re
import asyncio
from typing import Optional, List, Dict, Tuple, Any, Union

from .constants import (
    SEPARATOR_REMNANTS, PLACEHOLDER_REMNANT_RE, HTML_LEAK_RE,
    PLACEHOLDER_BRACKET_RE, RENPY_TAG_RE, HOTKEY_SOURCE_RE,
)


def reset_translation_diagnostics(diagnostic_report) -> None:
    """Reset diagnostic counters before a new translation run."""
    from src.core.diagnostics import DiagnosticReport
    if diagnostic_report is None:
        return
    diagnostic_report.__init__()


def record_translation_guard_event(
    translation_guard_events: List[Dict],
    translation_guard_counts: Dict[str, int],
    translation_guard_sample_limit: int,
    *,
    category: str,
    file_path: str,
    translation_id: str = '',
    original_text: str = '',
    translated_text: str = '',
    detail: str = '',
    line_number: int = 0,
) -> None:
    if category not in translation_guard_counts:
        translation_guard_counts[category] = 0
    translation_guard_counts[category] += 1
    if len(translation_guard_events) >= translation_guard_sample_limit:
        return
    translation_guard_events.append({
        'category': category,
        'file_path': file_path,
        'translation_id': translation_id,
        'line_number': line_number,
        'detail': detail,
        'original_preview': (original_text or '')[:160],
        'translated_preview': (translated_text or '')[:160],
    })


def extract_validation_placeholders(text: str, source_text: str = '') -> List[str]:
    placeholders = PLACEHOLDER_BRACKET_RE.findall(text or '')
    hotkey_match = HOTKEY_SOURCE_RE.match((source_text or '').strip())
    if hotkey_match and placeholders:
        hotkey_suffix = f"[{hotkey_match.group('hotkey').upper()}]"
        stripped_text = (text or '').strip()
        if stripped_text.endswith(hotkey_suffix):
            for idx in range(len(placeholders) - 1, -1, -1):
                if placeholders[idx].upper() == hotkey_suffix:
                    placeholders.pop(idx)
                    break
    return sorted(re.sub(r'\s+', '', ph) for ph in placeholders)


def validate_placeholders(original: str, translated: str) -> bool:
    """
    Çeviri sonrası değişkenlerin doğruluğunu kontrol eder.
    v2.7.2: Fuzzy matching - boşluklu versiyonları da kabul et.
    """
    orig_vars = re.findall(r'\[[^\]]+\]', original)
    for var in orig_vars:
        if var not in translated:
            var_content = var[1:-1]
            var_normalized = re.sub(r'\s+', '', var_content)
            found = False
            for trans_var in re.findall(r'\[[^\]]+\]', translated):
                trans_content = trans_var[1:-1]
                trans_normalized = re.sub(r'\s+', '', trans_content)
                if var_normalized == trans_normalized:
                    found = True
                    break
            if not found:
                return False
    return True


def classify_translation_corruption(original: str, translated: str) -> Optional[str]:
    orig = (original or '').strip()
    trans = (translated or '').strip()
    if not orig or not trans:
        return None
    if any(remnant in trans for remnant in SEPARATOR_REMNANTS):
        return 'separator_remnant'
    if '\u27e6' in trans or '\u27e7' in trans or PLACEHOLDER_REMNANT_RE.search(trans) or '<ph id=' in trans or '</ph>' in trans:
        return 'placeholder_remnant'
    if HTML_LEAK_RE.search(trans):
        return 'html_leakage'
    if len(trans) > max(len(orig) * 4, len(orig) + 80):
        return 'length_inflation'
    if not validate_placeholders(original=orig, translated=trans):
        return 'placeholder_set_mismatch'
    if extract_validation_placeholders(orig) != extract_validation_placeholders(trans, source_text=orig):
        return 'placeholder_set_mismatch'
    if '\u27e6' not in orig and '\u27e7' not in orig:
        if sorted(RENPY_TAG_RE.findall(orig)) != sorted(RENPY_TAG_RE.findall(trans)):
            return 'renpy_tag_set_mismatch'
    return None


def get_guard_reason_text(reason: str, config) -> str:
    reason_key_map = {
        'separator_remnant': ('guard_reason_separator_remnant', 'separator markers leaked into the output'),
        'placeholder_remnant': ('guard_reason_placeholder_remnant', 'placeholder tokens leaked into the output'),
        'html_leakage': ('guard_reason_html_leakage', 'HTML markup leaked into the output'),
        'length_inflation': ('guard_reason_length_inflation', 'translated text expanded far beyond the source'),
        'placeholder_set_mismatch': ('guard_reason_placeholder_set_mismatch', 'placeholder structure changed'),
        'renpy_tag_set_mismatch': ('guard_reason_renpy_tag_set_mismatch', "Ren'Py text tags changed"),
    }
    key, default = reason_key_map.get(reason, ('guard_reason_unknown', (reason or 'suspicious translator output').replace('_', ' ')))
    return config.get_log_text(key, default)


def sanitize_translation_for_output(
    *,
    original: str,
    translated: str,
    file_path: str,
    translation_id: str,
    diagnostic_report,
    log_emit,
    config,
    record_guard_event_fn,
    line_number: int = 0,
) -> Tuple[str, Optional[str]]:
    reason = classify_translation_corruption(original, translated)
    if reason is None:
        return translated, None

    record_guard_event_fn(
        category='blocked_as_corrupted',
        file_path=file_path,
        translation_id=translation_id,
        original_text=original,
        translated_text=translated,
        detail=reason,
        line_number=line_number,
    )
    try:
        diagnostic_report.mark_blocked(
            file_path,
            translation_id,
            'corrupt_blocked',
            original_text=original,
            translated_text=translated,
        )
    except Exception:
        pass
    return original, reason


def should_retry_unchanged_core_ui(original_text: str) -> bool:
    from .constants import CORE_UI_RETRY_STRINGS
    return (original_text or '').strip() in CORE_UI_RETRY_STRINGS


def get_requested_translation_batch_size(engine, config) -> int:
    from src.core.translator import TranslationEngine
    if engine in (TranslationEngine.OPENAI, TranslationEngine.GEMINI, TranslationEngine.LOCAL_LLM):
        return getattr(config.translation_settings, 'ai_batch_size', 50)
    return getattr(config.translation_settings, 'max_batch_size', 100)


def get_effective_translation_batch_size(engine, config) -> int:
    from src.core.translator import TranslationEngine
    from src.utils.config import get_effective_batch_size as _get_eff
    requested = get_requested_translation_batch_size(engine, config)
    if engine in (TranslationEngine.OPENAI, TranslationEngine.GEMINI, TranslationEngine.LOCAL_LLM):
        return requested
    return _get_eff(requested, engine)


def emit_batch_size_cap_notice_if_needed(requested: int, effective: int, engine, config, log_emit) -> None:
    if effective == requested:
        return
    from src.utils.config import get_engine_batch_size_cap
    cap = get_engine_batch_size_cap(engine) or effective
    engine_name = getattr(engine, 'value', str(engine))
    log_emit("info", config.get_log_text(
        'log_batch_size_engine_cap_applied',
        'Requested batch size {requested} exceeds the effective limit for {engine}; using {effective} (cap: {cap}).',
        requested=requested, engine=engine_name, effective=effective, cap=cap,
    ))


def execute_single_request_with_retry_mode(loop, translator, request) -> Optional[Any]:
    ts = getattr(translator, '_config_manager', None)
    if ts is None:
        original_flag = getattr(translator, 'aggressive_retry', None)
        try:
            if original_flag is not None:
                translator.aggressive_retry = True
            return loop.run_until_complete(translator.translate_single(request))
        except Exception as exc:
            return None
        finally:
            if original_flag is not None:
                translator.aggressive_retry = original_flag

    ts_settings = getattr(ts, 'translation_settings', None)
    original_config_flag = getattr(ts_settings, 'aggressive_retry_translation', False) if ts_settings else False
    original_translator_flag = getattr(translator, 'aggressive_retry', None)
    try:
        if ts_settings is not None:
            ts_settings.aggressive_retry_translation = True
        if original_translator_flag is not None:
            translator.aggressive_retry = True
        return loop.run_until_complete(translator.translate_single(request))
    except Exception as exc:
        return None
    finally:
        if ts_settings is not None:
            ts_settings.aggressive_retry_translation = original_config_flag
        if original_translator_flag is not None:
            translator.aggressive_retry = original_translator_flag


def retry_unchanged_core_ui(loop, request, entry, current_text: str, translation_manager) -> Tuple[str, bool]:
    if request is None or not should_retry_unchanged_core_ui(entry.original_text):
        return current_text, False

    translator = translation_manager.translators.get(request.engine)
    if translator is None:
        return current_text, False

    retry_result = execute_single_request_with_retry_mode(loop, translator, request)
    if retry_result and getattr(retry_result, 'success', False):
        retry_text = (getattr(retry_result, 'translated_text', '') or '').strip()
        if retry_text and retry_text != entry.original_text.strip():
            return retry_text, True

    fallback_translator = getattr(translator, 'fallback_translator', None) or getattr(translator, '_fallback', None)
    if fallback_translator is not None:
        fallback_result = execute_single_request_with_retry_mode(loop, fallback_translator, request)
        if fallback_result and getattr(fallback_result, 'success', False):
            fallback_text = (getattr(fallback_result, 'translated_text', '') or '').strip()
            if fallback_text and fallback_text != entry.original_text.strip():
                return fallback_text, True

    return current_text, False


def protect_glossary_terms(text: str, config, xml_mode: bool = False) -> Tuple[str, Dict[str, str]]:
    if not config or not hasattr(config, 'glossary') or not config.glossary:
        return text, {}
    from src.core.glossary_manager import GlossaryManager
    return GlossaryManager.protect_terms(text, config.glossary, xml_mode=xml_mode)


def get_extraction_mode(config) -> str:
    ts = getattr(config, 'translation_settings', None)
    mode = str(getattr(ts, 'extraction_mode', 'balanced') or 'balanced').strip().lower()
    if mode not in ('strict', 'balanced', 'aggressive'):
        return 'balanced'
    return mode


def is_aggressive_extraction_mode(config) -> bool:
    return get_extraction_mode(config) == 'aggressive'
