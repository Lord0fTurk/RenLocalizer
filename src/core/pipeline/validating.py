# -*- coding: utf-8 -*-
"""
Validation-stage functions extracted from TranslationPipeline.
Each function operates independently, receiving needed state via parameters.
"""

import os
import ast
import logging
from typing import List, Optional
from pathlib import Path

from .constants import COVERAGE_AUDIT_EXCLUDE_DIRS

logger = logging.getLogger(__name__)


def find_rpymc_files(directory: str) -> list:
    """Klasörde ve alt klasörlerinde .rpymc dosyalarını bulur."""
    rpymc_files = []
    for root, dirs, files in os.walk(directory):
        for f in files:
            if f.lower().endswith('.rpymc'):
                rpymc_files.append(os.path.join(root, f))
    return rpymc_files


def extract_strings_from_rpymc_ast(ast_root) -> list:
    """
    AST'den stringleri çıkarır (İteratif & Güvenli).
    Recursion yerine Stack kullanarak derin nested yapılarda çökme riskini (StackOverflow) önler.
    """
    strings = set()
    PRIORITY_KEYS = {'text', 'content', 'value', 'caption', 'label', 'description', 'message', 'body'}
    stack = [ast_root]

    while stack:
        node = stack.pop()

        if isinstance(node, str):
            s = node.strip()
            if len(s) > 2 and not s.isspace():
                strings.add(s)

        elif isinstance(node, (list, tuple)):
            stack.extend(node)

        elif isinstance(node, dict):
            for key, value in node.items():
                stack.append(value)

        elif hasattr(node, '__dict__'):
            for value in vars(node).values():
                stack.append(value)

    result = list(strings)
    return result


def has_rpy_files(directory: str) -> bool:
    """Klasörde .rpy dosyası var mı?"""
    for root, dirs, files in os.walk(directory):
        for f in files:
            if f.lower().endswith('.rpy'):
                return True
    return False


def has_rpyc_files(directory: str) -> bool:
    """Klasörde .rpyc dosyası var mı?"""
    for root, dirs, files in os.walk(directory):
        for f in files:
            if f.lower().endswith('.rpyc'):
                return True
    return False


def has_rpa_files(directory: str) -> bool:
    """Klasörde .rpa arşiv dosyası var mı?"""
    for root, dirs, files in os.walk(directory):
        for f in files:
            if f.lower().endswith('.rpa'):
                return True
    return False


def needs_re_extraction(game_dir: str, tl_dir: str, config, log_emit, rpyc_enabled: bool = False, include_rpyc: bool = False) -> bool:
    """
    Geliştirici oyun dosyalarını (.rpy/.rpyc) günellediğinde, tl/ klasöründeki mevcut
    çevirilerden (genelde strings.json veya tl/*.rpy) daha yeni olup olmadığını kontrol eder.
    Eğer daha yeni kaynak dosyalar varsa True döndürür ve yeniden extract yapılmasını zorlar.
    """
    import json

    try:
        rpyc_enabled = rpyc_enabled or include_rpyc
        if rpyc_enabled:
            diag_dir = os.path.join(tl_dir, 'diagnostics')
            sig_path = os.path.join(diag_dir, 'rpyc_extraction_signature.json')
            expected_sig = 'rpyc_reader_slot12_encoding_fallback_root_filter_v1'
            try:
                if not os.path.exists(sig_path):
                    log_emit('info', 'RPYC extraction signature missing. Forcing one-time re-extraction to refresh coverage.')
                    return True
                with open(sig_path, 'r', encoding='utf-8') as sf:
                    payload = json.load(sf)
                if payload.get('signature') != expected_sig:
                    log_emit('info', 'RPYC extraction signature outdated. Forcing one-time re-extraction to refresh coverage.')
                    return True
            except Exception as e:
                log_emit('info', f'RPYC extraction signature unreadable ({e}); forcing re-extraction to refresh coverage.')
                return True

        tl_mtime = 0
        for root, dirs, files in os.walk(tl_dir):
            for f in files:
                if f.lower().endswith('.rpy'):
                    fmtime = os.path.getmtime(os.path.join(root, f))
                    if fmtime > tl_mtime:
                        tl_mtime = fmtime

        if tl_mtime == 0:
            tl_mtime = os.path.getmtime(tl_dir)

        for root, dirs, files in os.walk(game_dir):
            if 'tl' in dirs:
                dirs.remove('tl')
            dirs[:] = [d for d in dirs if d.lower() != 'renpy']
            for f in files:
                if f.lower().endswith('.rpy') or f.lower().endswith('.rpyc'):
                    fmtime = os.path.getmtime(os.path.join(root, f))
                    if fmtime > tl_mtime:
                        return True
        return False
    except Exception as e:
        logger.debug(f"mtime check failed: {e}")
        return False


def normalize_tl_encodings(tl_dir: str, log_emit) -> int:
    """
    tl/<lang> içindeki .rpy dosyalarını UTF-8-SIG'e yeniden yazar.
    Ren'Py loader'ı 'python_strict' ile okuduğu için geçersiz byte'lar
    (örn. 0xBE) oyunu düşürüyor; burada tamamını normalize ediyoruz.
    """
    from src.utils.encoding import normalize_to_utf8_sig

    tl_path = Path(tl_dir)
    if not tl_path.exists():
        return 0

    normalized = 0
    for file_path in tl_path.rglob("*.rpy"):
        try:
            if normalize_to_utf8_sig(file_path):
                normalized += 1
        except Exception as e:
            log_emit("warning", f"Encoding normalize failed for {file_path}: {e}")
    return normalized


def is_generated_export_file(file_path: str) -> bool:
    basename = os.path.basename(file_path or '')
    lowered = basename.lower()
    return lowered.startswith('zz_rl_exported_') and lowered.endswith('.rpy')


def is_runtime_hook_enabled(config) -> bool:
    """Single source of truth for whether runtime assets should be generated."""
    ts = getattr(config, 'translation_settings', None)
    if ts is None:
        return False
    enable_runtime_hook = bool(getattr(ts, 'enable_runtime_hook', True))
    auto_generate_hook = bool(getattr(ts, 'auto_generate_hook', True))
    force_runtime = bool(getattr(ts, 'force_runtime_translation', False))
    return force_runtime or (enable_runtime_hook and auto_generate_hook)


def emit_scan_progress(log_emit, label: str, current: int, total: int, file_path, step: int = 25) -> None:
    if total <= 0:
        return
    if current != 1 and current != total and current % step != 0:
        return
    file_name = Path(file_path).name
    log_emit("info", f"{label}: {current}/{total} ({file_name})")
