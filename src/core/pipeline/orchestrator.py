# -*- coding: utf-8 -*-
"""
TranslationPipeline orchestrator.
Manages the end-to-end translation workflow, delegating to submodules.
"""

import os
import logging
import asyncio
import json
import re
import time
from typing import Optional, List, Dict, Any
from pathlib import Path
import shutil

from PyQt6.QtCore import QObject, pyqtSignal

from src.utils.config import ConfigManager
from src.utils.encoding import save_text_safely
from src.core.tl_parser import TLParser, TranslationFile, TranslationEntry, get_translation_stats
from src.core.parser import RenPyParser
from src.core.translator import (
    TranslationManager,
    TranslationRequest,
    TranslationEngine,
    GoogleTranslator,
    DeepLTranslator,
    LibreTranslateTranslator,
)
from src.core.ai_translator import OpenAITranslator, GeminiTranslator, LocalLLMTranslator
from src.core.output_formatter import RenPyOutputFormatter
from src.core.diagnostics import DiagnosticReport

from .base import PipelineStage, PipelineResult, PipelineWorker
from .constants import (
    RENPY_TO_API_LANG,
    TRANSLATION_ID_KEY_RE,
)
from .validating import (
    find_rpymc_files, extract_strings_from_rpymc_ast,
    has_rpy_files, has_rpyc_files, has_rpa_files,
    needs_re_extraction, normalize_tl_encodings,
    is_generated_export_file, is_runtime_hook_enabled as _is_hook_enabled,
    emit_scan_progress as _emit_scan,
)
from .extraction import (
    run_extraction, cleanup_legacy_mod_files,
    make_source_translatable, escape_rpy_string,
    is_nontranslatable_identifier_entry,
    generate_all_strings_file, generate_native_tlid_content,
    reopen_stale_tl_entries, collect_coverage_warnings,
    audit_image_only_ui, audit_compiled_only_scripts, audit_dynamic_ui_runtime,
)
from .translating import (
    reset_translation_diagnostics as _reset_diag,
    record_translation_guard_event as _record_guard,
    classify_translation_corruption, get_guard_reason_text,
    sanitize_translation_for_output as _sanitize,
    validate_placeholders, extract_validation_placeholders,
    should_retry_unchanged_core_ui,
    get_requested_translation_batch_size, get_effective_translation_batch_size,
    emit_batch_size_cap_notice_if_needed,
    execute_single_request_with_retry_mode,
    retry_unchanged_core_ui,
    protect_glossary_terms,
    get_extraction_mode as _extraction_mode,
    is_aggressive_extraction_mode as _is_aggressive,
)
from .saving import (
    synthesize_hotkey_visible_variants,
    synthesize_angle_wrapper_variants,
    synthesize_visible_text_variants,
    synthesize_visible_fragment_variants,
    synthesize_runtime_observed_variants,
    analyze_runtime_miss_log,
    write_translation_reports,
    emit_coverage_warning_summary,
    manage_runtime_hook,
    create_language_init_file,
    write_atomic_segments_rpy,
    generate_visible_text_aliases,
)


class TranslationPipeline(QObject):
    """
    Entegre çeviri pipeline'ı.
    
    Akış:
    1. Proje doğrulama
    2. UnRen (gerekirse)
    3. Translate komutu ile tl/<dil>/ oluşturma
    4. tl/<dil>/*.rpy dosyalarını parse etme
    5. old "..." metinlerini çevirme
    6. new "..." alanlarına yazma ve kaydetme
    """

    stage_changed = pyqtSignal(str, str)
    progress_updated = pyqtSignal(int, int, str)
    log_message = pyqtSignal(str, str)
    finished = pyqtSignal(object)
    show_warning = pyqtSignal(str, str)

    def __init__(
        self,
        config: ConfigManager,
        translation_manager: TranslationManager,
        parent=None
    ):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)

        self.config = config
        self.translation_manager = translation_manager
        self.tl_parser = TLParser()
        self.diagnostic_report = DiagnosticReport()
        self.error_log_path = Path("pipeline_debug.log")
        self.normalize_count = 0
        self._last_diagnostic_path: Optional[str] = None

        self.current_stage = PipelineStage.IDLE
        self.should_stop = False
        self.is_running = False

        self._log_queue = []
        self._last_log_time = 0
        self._log_throttle_interval = 0.08

        self.game_exe_path: Optional[str] = None
        self.project_path: Optional[str] = None
        self.target_language: str = "turkish"
        self.source_language: str = "en"
        self.engine: TranslationEngine = TranslationEngine.GOOGLE
        self.auto_unren: bool = True
        self.use_proxy: bool = False
        self._translation_guard_events: List[Dict[str, Any]] = []
        self._translation_guard_counts: Dict[str, int] = {}
        self._translation_guard_sample_limit = 200

    # ---- Diagnostics helpers ----

    def _reset_translation_diagnostics(self) -> None:
        self.diagnostic_report = DiagnosticReport()
        self._last_diagnostic_path = None
        self._translation_guard_events = []
        self._translation_guard_counts = {
            'unchanged_by_engine': 0,
            'blocked_as_corrupted': 0,
            'recovered_by_retry': 0,
            'recovered_by_synthesized_variant': 0,
        }

    def _record_translation_guard_event(self, **kwargs) -> None:
        _record_guard(
            self._translation_guard_events,
            self._translation_guard_counts,
            self._translation_guard_sample_limit,
            **kwargs,
        )

    def _emit_scan_progress(self, label, current, total, file_path, step=25):
        _emit_scan(self.log_message.emit, label, current, total, file_path, step)

    # ---- Legacy name delegation (some are still methods for deep coupling) ----

    def _classify_translation_corruption(self, original, translated):
        return classify_translation_corruption(original, translated)

    def _get_guard_reason_text(self, reason):
        return get_guard_reason_text(reason, self.config)

    def _sanitize_translation_for_output(self, *, original, translated, file_path,
                                           translation_id, line_number=0):
        return _sanitize(
            original=original,
            translated=translated,
            file_path=file_path,
            translation_id=translation_id,
            diagnostic_report=self.diagnostic_report,
            log_emit=self.log_message.emit,
            config=self.config,
            record_guard_event_fn=self._record_translation_guard_event,
            line_number=line_number,
        )

    def _should_retry_unchanged_core_ui(self, original_text):
        return should_retry_unchanged_core_ui(original_text)

    def _get_requested_translation_batch_size(self):
        return get_requested_translation_batch_size(self.engine, self.config)

    def _get_effective_translation_batch_size(self):
        return get_effective_translation_batch_size(self.engine, self.config)

    def _emit_batch_size_cap_notice_if_needed(self, requested, effective):
        emit_batch_size_cap_notice_if_needed(requested, effective, self.engine, self.config, self.log_message.emit)

    def _get_extraction_mode(self):
        return _extraction_mode(self.config)

    def _is_aggressive_extraction_mode(self):
        return _is_aggressive(self.config)

    def _extract_validation_placeholders(self, text, source_text=''):
        return extract_validation_placeholders(text, source_text)

    def _is_nontranslatable_identifier_entry(self, entry):
        return is_nontranslatable_identifier_entry(entry)

    def _escape_rpy_string(self, text):
        return escape_rpy_string(text)

    def _is_generated_export_file(self, file_path):
        return is_generated_export_file(file_path)

    def _is_runtime_hook_enabled(self):
        return _is_hook_enabled(self.config)

    # ---- Properties / Helpers that stay as methods (variant synthesis) ----

    def _synthesize_hotkey_visible_variants(self, mapping):
        return synthesize_hotkey_visible_variants(mapping)

    def _synthesize_angle_wrapper_variants(self, mapping):
        return synthesize_angle_wrapper_variants(mapping)

    def _synthesize_visible_text_variants(self, mapping):
        return synthesize_visible_text_variants(mapping)

    def _synthesize_visible_fragment_variants(self, mapping):
        return synthesize_visible_fragment_variants(mapping, self._is_aggressive_extraction_mode())

    def _synthesize_runtime_observed_variants(self, mapping, lang_dir):
        return synthesize_runtime_observed_variants(mapping, lang_dir, self._is_aggressive_extraction_mode())

    def _generate_visible_text_aliases(self, text):
        return generate_visible_text_aliases(text)

    def _split_visible_sentences(self, text):
        from .saving import _split_visible_sentences as _f
        return _f(text)

    def _normalize_runtime_alias_text(self, text):
        from .saving import _normalize_runtime_alias_text as _f
        return _f(text)

    def _find_runtime_alias_match_index(self, container_text, source_text):
        from .saving import _find_runtime_alias_match_index as _f
        return _f(container_text, source_text)

    def _build_runtime_observed_alias(self, observed_text, source_text, translated_text):
        from .saving import _build_runtime_observed_alias as _f
        return _f(observed_text, source_text, translated_text)

    def _build_bridge_prefixed_variant(self, text, prefix):
        from .saving import _build_bridge_prefixed_variant as _f
        return _f(text, prefix)

    def _unwrap_single_angle_text(self, text):
        from .saving import _unwrap_single_angle_text as _f
        return _f(text)

    def validate_placeholders(self, original, translated):
        return validate_placeholders(original, translated)

    def analyze_runtime_miss_log(self, log_path):
        return analyze_runtime_miss_log(log_path)

    # ---- Coverage audit delegation ----

    def _audit_image_only_ui(self, game_dir):
        return audit_image_only_ui(game_dir, self.config)

    def _audit_compiled_only_scripts(self, game_dir):
        return audit_compiled_only_scripts(game_dir, self.config, getattr(self, 'include_rpyc', False))

    def _audit_dynamic_ui_runtime(self, game_dir):
        return audit_dynamic_ui_runtime(game_dir, self.config, self._is_runtime_hook_enabled())

    def _iter_audit_files(self, game_dir, extension):
        from .extraction import _iter_audit_files as _f
        return _f(game_dir, extension)

    def _relative_audit_path(self, game_dir, file_path):
        from .extraction import _relative_audit_path as _f
        return _f(game_dir, file_path)

    def _decode_literal_candidate(self, raw_literal):
        from .extraction import _decode_literal_candidate as _f
        return _f(raw_literal)

    def _block_has_textual_hint(self, parser, block_lines):
        from .extraction import _block_has_textual_hint as _f
        return _f(parser, block_lines)

    # ---- Extraction delegation ----
    def _find_rpymc_files(self, directory):
        return find_rpymc_files(directory)

    def _extract_strings_from_rpymc_ast(self, ast_root):
        return extract_strings_from_rpymc_ast(ast_root)

    def _has_rpy_files(self, directory):
        return has_rpy_files(directory)

    def _has_rpyc_files(self, directory):
        return has_rpyc_files(directory)

    def _has_rpa_files(self, directory):
        return has_rpa_files(directory)

    def _needs_re_extraction(self, game_dir, tl_dir):
        rpyc_enabled = bool(
            getattr(self.config.translation_settings, 'enable_rpyc_reader', False)
            or getattr(self, 'include_rpyc', False)
        )
        return needs_re_extraction(game_dir, tl_dir, self.config, self.log_message.emit, rpyc_enabled, getattr(self, 'include_rpyc', False))

    # ---- Core pipeline orchestration ----

    def emit_log(self, level, message):
        if level in ('error', 'warning'):
            self.log_message.emit(level, message)
            return
        current_time = time.time()
        if current_time - self._last_log_time > self._log_throttle_interval:
            self.log_message.emit(level, message)
            self._last_log_time = current_time

    def _log_error(self, message):
        if getattr(self.config, 'debug_mode', False) or getattr(self, 'always_log_errors', False):
            try:
                with self.error_log_path.open("a", encoding="utf-8") as f:
                    f.write(message + "\n")
            except Exception:
                self.logger.debug(f"Error log yazılamadı: {message}")
        try:
            self.diagnostic_report.mark_skipped('pipeline', f'error:{message}')
        except Exception:
            self.logger.debug("diagnostic mark_skipped failed: %s", message)

    def configure(
        self,
        game_exe_path: str,
        target_language: str,
        source_language: str = "en",
        engine: TranslationEngine = TranslationEngine.GOOGLE,
        auto_unren: bool = True,
        use_proxy: bool = False,
        include_deep_scan: bool = False,
        include_rpyc: bool = False
    ):
        """Pipeline ayarlarını yapılandır."""
        self.include_deep_scan = include_deep_scan
        self.include_rpyc = include_rpyc
        self.game_exe_path = game_exe_path

        if os.path.isdir(game_exe_path):
            candidate = game_exe_path
            if os.path.basename(candidate).lower() == 'game':
                candidate = os.path.dirname(candidate)
            elif not os.path.isdir(os.path.join(candidate, 'game')):
                parent = os.path.dirname(candidate)
                if os.path.isdir(os.path.join(parent, 'game')):
                    candidate = parent
        else:
            candidate = os.path.dirname(game_exe_path)
            try:
                if os.path.basename(candidate).lower() == 'game':
                    candidate = os.path.dirname(candidate)
                    self.log_message.emit('info', self.config.get_ui_text('pipeline_project_normalize_game'))
                elif not os.path.isdir(os.path.join(candidate, 'game')):
                    parent = os.path.dirname(candidate)
                    if os.path.isdir(os.path.join(parent, 'game')):
                        candidate = parent
                        self.log_message.emit('info', self.config.get_ui_text('pipeline_project_normalize_parent'))
            except Exception:
                candidate = os.path.dirname(game_exe_path)

        self.project_path = candidate
        reverse_lang_map = {v.lower(): k for k, v in RENPY_TO_API_LANG.items()}
        self.target_language = reverse_lang_map.get((target_language or "").lower(), target_language)
        self.source_language = source_language
        self.engine = engine
        self.auto_unren = auto_unren
        self.use_proxy = use_proxy

    def stop(self):
        self.should_stop = True
        self.log_message.emit("warning", self.config.get_ui_text("stop_requested"))

    def _set_stage(self, stage, message=""):
        self.current_stage = stage
        self.stage_changed.emit(stage.value, message)
        stage_label = self.config.get_log_text(f"stage_{stage.value}", stage.value.upper())
        self.log_message.emit("info", f"[{stage_label}] {message}")

    def run(self):
        self.is_running = True
        self.should_stop = False
        try:
            result = self._run_pipeline()
            self.finished.emit(result)
        except Exception as e:
            self.logger.exception("Pipeline hatası")
            result = PipelineResult(
                success=False,
                message=f"Beklenmeyen hata: {str(e)}",
                stage=PipelineStage.ERROR,
                error=str(e)
            )
            self.finished.emit(result)
        finally:
            self.is_running = False

    def _stopped_result(self):
        return PipelineResult(
            success=False,
            message=self.config.get_ui_text("pipeline_user_stopped"),
            stage=PipelineStage.IDLE
        )

    def _protect_glossary_terms(self, text, xml_mode=False):
        return protect_glossary_terms(text, self.config, xml_mode=xml_mode)

    def _normalize_tl_encodings(self, tl_dir):
        return normalize_tl_encodings(tl_dir, self.log_message.emit)

    def _collect_coverage_warnings(self, game_dir):
        return collect_coverage_warnings(
            game_dir, self.config, self.diagnostic_report,
            self._is_runtime_hook_enabled(), getattr(self, 'include_rpyc', False)
        )

    def _emit_coverage_warning_summary(self):
        emit_coverage_warning_summary(
            self.diagnostic_report, self.config, self.log_message.emit, self._last_diagnostic_path
        )

    def _reopen_stale_tl_entries(self, tl_files):
        return reopen_stale_tl_entries(
            tl_files, self.config, self.diagnostic_report, self._record_translation_guard_event
        )

    def _make_source_translatable(self, game_dir):
        return make_source_translatable(game_dir, self.config, self.log_message.emit, self._log_error)

    def _run_extraction(self, project_path):
        return run_extraction(project_path, self.config, self.log_message.emit, self._log_error)

    def _cleanup_legacy_mod_files(self, game_dir):
        return cleanup_legacy_mod_files(game_dir, self.log_message.emit)

    def _write_translation_reports(self, lang_dir):
        self._last_diagnostic_path = write_translation_reports(
            lang_dir, self.target_language, self.diagnostic_report,
            self._translation_guard_counts, self._translation_guard_events,
            self._translation_guard_sample_limit,
            self.log_message.emit, self.config,
        )

    def _manage_runtime_hook(self):
        manage_runtime_hook(self.project_path, self.target_language, self.config, self.log_message.emit)

    def _create_language_init_file(self, game_dir):
        create_language_init_file(game_dir, self.target_language, self.config, self.log_message.emit)

    def _write_atomic_segments_rpy(self, tl_dir, renpy_lang):
        write_atomic_segments_rpy(tl_dir, renpy_lang)

    # ---- translate_existing_tl (stays as method) ----

    def translate_existing_tl(
        self,
        tl_root_path: str,
        target_language: str,
        source_language: str = "auto",
        engine: TranslationEngine = TranslationEngine.GOOGLE,
        use_proxy: bool = False,
    ) -> PipelineResult:
        """Var olan tl/<dil> klasöründeki .rpy dosyalarını doğrudan çevirir."""
        self._reset_translation_diagnostics()
        reverse_lang_map = {v.lower(): k for k, v in RENPY_TO_API_LANG.items()}
        target_iso = (target_language or "").lower()
        renpy_lang = reverse_lang_map.get(target_iso, target_iso)

        self.target_language = renpy_lang
        self.source_language = source_language
        self.engine = engine
        self.use_proxy = use_proxy
        self.project_path = os.path.abspath(Path(tl_root_path).parent.parent) if tl_root_path else None

        self._set_stage(PipelineStage.PARSING, self.config.get_ui_text("stage_parsing"))

        p = Path(tl_root_path)
        lang_dir: Optional[Path] = None
        tl_path: Optional[Path] = None

        target_dir_names: List[str] = []
        for name in [renpy_lang, target_iso]:
            if name and name not in target_dir_names:
                target_dir_names.append(name)

        def matches_name(path_obj):
            return path_obj.name.lower() in target_dir_names

        if matches_name(p) and p.parent.name.lower() == "tl":
            lang_dir = p
            tl_path = p.parent
        elif p.name.lower() == "tl":
            tl_path = p
            for name in target_dir_names:
                candidate = tl_path / name
                if candidate.exists():
                    lang_dir = candidate
                    break
        if lang_dir is None and (p / "tl").exists():
            tl_path = p / "tl"
            for name in target_dir_names:
                candidate = tl_path / name
                if candidate.exists():
                    lang_dir = candidate
                    break
        if lang_dir is None:
            for name in target_dir_names:
                candidate = p / name
                if candidate.exists():
                    lang_dir = candidate
                    tl_path = p if p.name.lower() == "tl" else p.parent if p.parent.name.lower() == "tl" else p
                    break
        if lang_dir is None and p.is_dir():
            try:
                has_rpy = next(p.rglob("*.rpy"), None) is not None
            except Exception:
                has_rpy = False
            if has_rpy:
                lang_dir = p
                tl_path = p.parent if p.parent else p

        if lang_dir is None:
            return PipelineResult(
                success=False,
                message=self.config.get_log_text('tl_dir_not_found', path=f"{p} ({'/'.join(target_dir_names)})"),
                stage=PipelineStage.ERROR,
            )

        if not lang_dir.exists():
            return PipelineResult(
                success=False,
                message=self.config.get_log_text('tl_dir_not_found', path=str(lang_dir)),
                stage=PipelineStage.ERROR,
            )

        self.log_message.emit("info", self.config.get_log_text('tl_directory_info', tl_path=str(tl_path), lang_dir=lang_dir.name, input=target_language))

        game_dir = None
        try:
            if lang_dir.parent.name.lower() == "tl":
                game_dir = lang_dir.parent.parent
            elif tl_path and tl_path.name.lower() == "tl":
                game_dir = tl_path.parent
        except Exception:
            game_dir = None

        tl_files = self.tl_parser.parse_directory(str(tl_path), lang_dir.name)

        target_tl_dir = os.path.normcase(os.path.join(str(tl_path), lang_dir.name))
        filtered_files: List[TranslationFile] = []
        for tl_file in tl_files:
            if self._is_generated_export_file(tl_file.file_path):
                self.log_message.emit("debug", f"[ExportFilter] Skipping generated export file: {tl_file.file_path}")
                continue
            fp_norm = os.path.normcase(tl_file.file_path)
            if fp_norm.startswith(target_tl_dir):
                tl_file.entries = [
                    e for e in tl_file.entries
                    if os.path.normcase(e.file_path or tl_file.file_path).startswith(target_tl_dir)
                ]
                filtered_files.append(tl_file)
            else:
                self.log_message.emit("info", self.config.get_log_text('log_other_lang_skipped', path=tl_file.file_path))
        tl_files = filtered_files

        try:
            normalized = self._normalize_tl_encodings(str(lang_dir))
            if normalized:
                self.log_message.emit("info", self.config.get_log_text('log_tl_normalized', count=normalized))
                self.normalize_count = normalized
        except Exception as e:
            msg = self.config.get_log_text('encoding_normalize_failed', path=str(lang_dir), error=str(e))
            self.log_message.emit("warning", msg)
            self._log_error(msg)

        if not tl_files:
            return PipelineResult(
                success=False,
                message=self.config.get_ui_text("pipeline_files_not_found_parse"),
                stage=PipelineStage.ERROR,
            )

        reopened_counts = self._reopen_stale_tl_entries(tl_files)
        if reopened_counts['reopened']:
            self.log_message.emit("info",
                f"Reopened stale TL entries for retranslation: {reopened_counts['reopened']} "
                f"(corrupted={reopened_counts['corrupted']}, unchanged_core_ui={reopened_counts['unchanged_core_ui']})")

        all_entries: List[TranslationEntry] = []
        for tl_file in tl_files:
            all_entries.extend(tl_file.get_untranslated())

        try:
            self.diagnostic_report.project = os.path.basename(os.path.abspath(tl_root_path))
            self.diagnostic_report.target_language = self.target_language
            for tl_file in tl_files:
                for e in tl_file.entries:
                    fp = e.file_path or tl_file.file_path
                    self.diagnostic_report.add_extracted(fp, {
                        'text': e.original_text,
                        'line_number': e.line_number,
                        'context_path': getattr(e, 'context_path', [])
                    })
        except Exception:
            self.logger.debug("Failed to extract error attributes from translation error")

        if not all_entries:
            stats = get_translation_stats(tl_files)
            if game_dir and game_dir.exists():
                self._create_language_init_file(str(game_dir))
                self._manage_runtime_hook()
            return PipelineResult(
                success=True,
                message=self.config.get_ui_text("pipeline_all_already_translated"),
                stage=PipelineStage.COMPLETED,
                stats=stats,
                output_path=str(lang_dir)
            )

        self.log_message.emit("info", self.config.get_ui_text("pipeline_entries_to_translate").replace("{count}", str(len(all_entries))))

        self._set_stage(PipelineStage.TRANSLATING, self.config.get_ui_text("stage_translating"))
        translations = self._translate_entries(all_entries)

        if not translations:
            return PipelineResult(
                success=False,
                message=self.config.get_ui_text("pipeline_translate_failed"),
                stage=PipelineStage.ERROR
            )

        self._set_stage(PipelineStage.SAVING, self.config.get_ui_text("stage_saving"))
        saved_count = 0
        for tl_file in tl_files:
            file_translations: Dict[str, str] = {}
            for entry in tl_file.entries:
                tid = getattr(entry, 'translation_id', '') or TLParser.make_translation_id(
                    entry.file_path, entry.line_number, entry.original_text
                )
                if tid in translations:
                    file_translations[tid] = translations[tid]
                elif entry.original_text in translations:
                    file_translations[entry.original_text] = translations[entry.original_text]

            if file_translations:
                success = self.tl_parser.save_translations(tl_file, file_translations)
                if success:
                    saved_count += 1
                    try:
                        for tid in file_translations.keys():
                            self.diagnostic_report.mark_written(tl_file.file_path, tid)
                    except Exception:
                        self.logger.debug("diagnostic mark_written loop failed")

        _old_seg_path2 = os.path.join(str(lang_dir), '_rl_segments.rpy')
        if os.path.exists(_old_seg_path2):
            try:
                os.remove(_old_seg_path2)
                self.emit_log("info", "[AtomicSegments] Removed obsolete _rl_segments.rpy")
                _old_seg_rpyc2 = _old_seg_path2 + 'c'
                if os.path.exists(_old_seg_rpyc2):
                    os.remove(_old_seg_rpyc2)
            except Exception:
                self.logger.debug("Failed to remove old .rpyc2 file")

        tl_files_updated = [
            tl_file for tl_file in self.tl_parser.parse_directory(str(tl_path), lang_dir.name)
            if not self._is_generated_export_file(tl_file.file_path)
        ]
        stats = get_translation_stats(tl_files_updated)

        if game_dir and game_dir.exists():
            self._create_language_init_file(str(game_dir))
            self._generate_strings_json(tl_files_updated, str(lang_dir), extra_translations=translations)
            self._manage_runtime_hook()

        try:
            self._write_translation_reports(str(lang_dir))
        except Exception as exc:
            self.logger.debug(f"Failed to write translation reports: {exc}")

        self._set_stage(PipelineStage.COMPLETED, self.config.get_ui_text("stage_completed"))
        summary = self.config.get_ui_text("pipeline_completed_summary").replace("{translated}", str(len(translations))).replace("{saved}", str(saved_count))
        if self.normalize_count:
            summary += f" | Normalize edilen tl dosyasi: {self.normalize_count}"

        return PipelineResult(
            success=True,
            message=summary,
            stage=PipelineStage.COMPLETED,
            stats=stats,
            output_path=str(lang_dir)
        )

    # ---- _run_pipeline (main flow) ----

    def _run_pipeline(self) -> PipelineResult:
        self._reset_translation_diagnostics()

        self._set_stage(PipelineStage.VALIDATING, self.config.get_ui_text("stage_validating"))

        if not self.game_exe_path:
            return PipelineResult(
                success=False,
                message=self.config.get_ui_text("pipeline_invalid_exe"),
                stage=PipelineStage.ERROR
            )

        is_file = os.path.isfile(self.game_exe_path)
        is_dir = os.path.isdir(self.game_exe_path)

        if not is_file and not is_dir:
            return PipelineResult(
                success=False,
                message=self.config.get_ui_text("pipeline_invalid_exe") + f" (path does not exist: {self.game_exe_path})",
                stage=PipelineStage.ERROR
            )

        project_path = self.project_path
        try:
            if os.path.basename(project_path).lower() == 'game':
                project_path = os.path.dirname(project_path)
            elif not os.path.isdir(os.path.join(project_path, 'game')):
                parent = os.path.dirname(project_path)
                if os.path.isdir(os.path.join(parent, 'game')):
                    project_path = parent
        except Exception:
            self.logger.debug("Project path resolution fallback failed")
        game_dir = os.path.join(project_path, 'game')

        if not os.path.isdir(game_dir):
            return PipelineResult(
                success=False,
                message=self.config.get_ui_text("pipeline_game_folder_missing"),
                stage=PipelineStage.ERROR
            )

        has_rpy = self._has_rpy_files(game_dir)
        has_rpyc = self._has_rpyc_files(game_dir)
        has_rpa = self._has_rpa_files(game_dir)

        self.rpymc_entries = []
        should_scan_rpym = getattr(self.config.translation_settings, 'scan_rpym_files', False)

        if should_scan_rpym:
            rpymc_files = self._find_rpymc_files(game_dir)
            if rpymc_files:
                from src.core.rpyc_reader import extract_texts_from_rpyc
                for rpymc_path in rpymc_files:
                    try:
                        texts = extract_texts_from_rpyc(rpymc_path, config_manager=self.config)
                        for t in texts:
                            text_val = t.get('text') or ""
                            if not text_val:
                                continue
                            ctx_path = t.get('context_path') or []
                            if isinstance(ctx_path, str):
                                ctx_path = [ctx_path]
                            entry = TranslationEntry(
                                original_text=text_val,
                                translated_text="",
                                file_path=str(rpymc_path),
                                line_number=t.get('line_number', 0) or 0,
                                entry_type="rpymc",
                                character=t.get('character'),
                                source_comment=None,
                                block_id=None,
                                context_path=ctx_path,
                                translation_id=TLParser.make_translation_id(
                                    str(rpymc_path), t.get('line_number', 0) or 0, text_val, ctx_path, t.get('raw_text')
                                )
                            )
                            self.rpymc_entries.append(entry)
                    except Exception as e:
                        msg = f".rpymc extraction failed: {rpymc_path} ({e})"
                        self.log_message.emit('warning', msg)
                        self._log_error(msg)
                self.log_message.emit('debug', self.config.get_log_text('rpymc_entry_count', count=len(self.rpymc_entries)))
        else:
            self.log_message.emit('debug', "Skipping .rpymc scan (scan_rpym_files disabled)")

        if self.should_stop:
            return self._stopped_result()

        needs_extraction = has_rpa and self.auto_unren
        needs_decompile = not has_rpy and has_rpyc and self.auto_unren

        if needs_extraction or needs_decompile:
            self.log_message.emit("info", self.config.get_log_text('rpa_extraction_needed'))
            self._set_stage(PipelineStage.UNRPA, self.config.get_ui_text("stage_unren"))

            success = self._run_extraction(project_path)
            if not success:
                import os as _os
                if _os.name != "nt" and has_rpyc:
                    self.log_message.emit("warning", self.config.get_log_text('log_rpa_failed_rpyc_continue'))
                else:
                    return PipelineResult(
                        success=False,
                        message=self.config.get_ui_text("unren_launch_failed").format(error=""),
                        stage=PipelineStage.ERROR
                    )

            tl_path_clean = os.path.join(game_dir, 'tl')
            if os.path.exists(tl_path_clean):
                for root, dirs, files in os.walk(tl_path_clean):
                    if 'common' in root.replace('\\', '/').split('/'):
                        for f in files:
                            try:
                                os.remove(os.path.join(root, f))
                            except Exception as e:
                                self.logger.warning(f"Failed to clean up common file {f}: {e}")

            has_rpy = self._has_rpy_files(game_dir)

        rpyc_only_mode = False
        if not has_rpy and has_rpyc:
            rpyc_enabled = getattr(self.config.translation_settings, 'enable_rpyc_reader', False) or getattr(self, 'include_rpyc', False)
            if rpyc_enabled:
                self.log_message.emit("info", self.config.get_ui_text("pipeline_rpyc_only_mode", "RPYC-only mode: No .rpy files found, reading .rpyc files directly."))
                rpyc_only_mode = True
            else:
                return PipelineResult(
                    success=False,
                    message=self.config.get_ui_text("pipeline_no_rpy_files") + " " + self.config.get_ui_text("pipeline_enable_rpyc_hint", "(Try enabling RPYC Reader)"),
                    stage=PipelineStage.ERROR
                )

        if self.should_stop:
            return self._stopped_result()

        self._set_stage(PipelineStage.GENERATING, self.config.get_ui_text("stage_generating"))
        self._make_source_translatable(game_dir)

        if self.should_stop:
            return self._stopped_result()

        self._set_stage(PipelineStage.GENERATING, f"{self.config.get_ui_text('stage_generating')} ({self.target_language})")

        tl_dir = os.path.join(game_dir, 'tl', self.target_language)

        self.log_message.emit("info", "Full extraction mode enabled: running translation template generation on every run.")
        success = self._run_translate_command(project_path)

        if not success and not os.path.isdir(tl_dir):
            return PipelineResult(
                success=False,
                message=self.config.get_ui_text("pipeline_translate_failed"),
                stage=PipelineStage.ERROR
            )

        if self.should_stop:
            return self._stopped_result()

        self._set_stage(PipelineStage.PARSING, self.config.get_ui_text("stage_parsing"))

        reverse_lang_map = {v.lower(): k for k, v in RENPY_TO_API_LANG.items()}
        renpy_lang = reverse_lang_map.get(self.target_language.lower(), self.target_language)

        tl_path = os.path.join(game_dir, 'tl')
        tl_files = self.tl_parser.parse_directory(tl_path, renpy_lang)

        target_tl_dir = os.path.normcase(os.path.join(tl_path, renpy_lang))
        filtered_files: List[TranslationFile] = []
        for tl_file in tl_files:
            if self._is_generated_export_file(tl_file.file_path):
                self.log_message.emit("debug", f"[ExportFilter] Skipping generated export file: {tl_file.file_path}")
                continue
            fp_norm = os.path.normcase(tl_file.file_path)
            if fp_norm.startswith(target_tl_dir):
                tl_file.entries = [
                    e for e in tl_file.entries
                    if os.path.normcase(e.file_path or tl_file.file_path).startswith(target_tl_dir)
                ]
                filtered_files.append(tl_file)
            else:
                self.log_message.emit("info", self.config.get_log_text('other_lang_folder_skipped', path=tl_file.file_path))
        tl_files = filtered_files

        if getattr(self, 'include_deep_scan', False):
            self._run_deep_scan(tl_files, game_dir, tl_path, renpy_lang)

        _unrpyc_enabled = getattr(self.config.translation_settings, 'enable_unrpyc_decompile', True)
        if _unrpyc_enabled and has_rpyc:
            self._run_unrpyc_decompile_scan(has_rpyc, game_dir, tl_path, renpy_lang, tl_files)

        try:
            normalized = self._normalize_tl_encodings(os.path.join(tl_path, renpy_lang))
            if normalized:
                self.log_message.emit("info", self.config.get_log_text('log_tl_normalized', count=normalized))
                self.normalize_count = normalized
        except Exception as e:
            msg = self.config.get_log_text('encoding_normalize_failed', path="tl", error=str(e))
            self.log_message.emit("warning", msg)
            self._log_error(msg)

        if not tl_files:
            return PipelineResult(
                success=False,
                message=self.config.get_ui_text("pipeline_files_not_found_parse"),
                stage=PipelineStage.ERROR
            )

        reopened_counts = self._reopen_stale_tl_entries(tl_files)
        if reopened_counts['reopened']:
            self.log_message.emit("info",
                f"Reopened stale TL entries for retranslation: {reopened_counts['reopened']} "
                f"(corrupted={reopened_counts['corrupted']}, unchanged_core_ui={reopened_counts['unchanged_core_ui']})")

        all_entries = []
        for tl_file in tl_files:
            all_entries.extend(tl_file.get_untranslated())

        use_native = getattr(self.config.translation_settings, 'output_mode', 'strings') == 'native'
        if use_native:
            existing_texts = {e.original_text for e in all_entries}
            ui_injected = 0
            native_sources = []
            if hasattr(self, '_native_ui_entries') and self._native_ui_entries:
                native_sources.append(('UI', self._native_ui_entries))
            if hasattr(self, '_native_deepscan_entries') and self._native_deepscan_entries:
                native_sources.append(('deep scan', self._native_deepscan_entries))
            for source_name, source_list in native_sources:
                for e_data in source_list:
                    text = e_data.get('text', '')
                    if not text or text in existing_texts:
                        continue
                    entry = TranslationEntry(
                        original_text=text,
                        translated_text="",
                        file_path=e_data.get('file_path', '_native_ui.rpy'),
                        line_number=e_data.get('line_number', 0) or 1,
                        entry_type='string',
                        translation_id=TLParser.make_translation_id(
                            e_data.get('file_path', '_native_ui.rpy'),
                            e_data.get('line_number', 0) or 1,
                            text
                        )
                    )
                    all_entries.append(entry)
                    existing_texts.add(text)
                    ui_injected += 1
            if ui_injected:
                self.log_message.emit('info', f"Injected {ui_injected} native UI/deepscan entries into translation pipeline.")

        try:
            self.diagnostic_report.project = os.path.basename(os.path.abspath(game_dir))
            self.diagnostic_report.target_language = self.target_language
            for tl_file in tl_files:
                for e in tl_file.entries:
                    fp = e.file_path or tl_file.file_path
                    self.diagnostic_report.add_extracted(fp, {
                        'text': e.original_text,
                        'line_number': e.line_number,
                        'context_path': getattr(e, 'context_path', [])
                    })
        except Exception:
            self.logger.debug("Failed to extract error attributes (dup)")

        try:
            self._collect_coverage_warnings(game_dir)
        except Exception as exc:
            self.logger.debug(f"Coverage warning collection failed: {exc}")

        if not all_entries:
            stats = get_translation_stats(tl_files)
            if game_dir and os.path.isdir(game_dir):
                self._create_language_init_file(str(game_dir))
                lang_dir = os.path.join(tl_path, renpy_lang)
                self._generate_strings_json(tl_files, lang_dir)
                self._manage_runtime_hook()
                try:
                    from src.core.exporter import export_strings_to_rpy
                    if export_strings_to_rpy(str(game_dir), renpy_lang):
                        self.log_message.emit("info", "Auto-exported translation strings to classic .rpy files.")
                except Exception as e:
                    self.logger.warning(f"Auto-export to RPY failed: {e}")

                try:
                    self._write_translation_reports(lang_dir)
                    self._emit_coverage_warning_summary()
                except Exception as exc:
                    self.logger.debug(f"Failed to write translation reports: {exc}")

            return PipelineResult(
                success=True,
                message=self.config.get_ui_text("pipeline_all_already_translated"),
                stage=PipelineStage.COMPLETED,
                stats=stats,
                output_path=tl_dir
            )

        self.log_message.emit("info", self.config.get_ui_text("pipeline_entries_to_translate").replace("{count}", str(len(all_entries))))

        if self.should_stop:
            return self._stopped_result()

        if getattr(self, 'rpymc_entries', None):
            self.log_message.emit('info', self.config.get_log_text('rpymc_adding_entries', count=len(self.rpymc_entries)))
            all_entries.extend(self.rpymc_entries)

        self._set_stage(PipelineStage.TRANSLATING, self.config.get_ui_text("stage_translating"))
        translations = self._translate_entries(all_entries)

        if self.should_stop:
            return self._stopped_result()

        if not translations:
            return PipelineResult(
                success=False,
                message=self.config.get_ui_text("pipeline_translate_failed"),
                stage=PipelineStage.ERROR
            )

        self._set_stage(PipelineStage.SAVING, self.config.get_ui_text("stage_saving"))

        saved_count = 0
        for tl_file in tl_files:
            file_translations = {}
            for entry in tl_file.entries:
                tid = getattr(entry, 'translation_id', '') or TLParser.make_translation_id(
                    entry.file_path, entry.line_number, entry.original_text
                )
                if tid in translations:
                    file_translations[tid] = translations[tid]
                elif entry.original_text in translations:
                    file_translations[entry.original_text] = translations[entry.original_text]

            if file_translations:
                success = self.tl_parser.save_translations(tl_file, file_translations)
                if success:
                    saved_count += 1
                    try:
                        for tid in file_translations.keys():
                            self.diagnostic_report.mark_written(tl_file.file_path, tid)
                    except Exception:
                        self.logger.debug("diagnostic mark_written loop failed (tl_parser path)")

        try:
            rpyc_removed = 0
            for root, dirs, files in os.walk(tl_dir):
                for fname in files:
                    if fname.lower().endswith('.rpyc'):
                        rpy_path = os.path.join(root, fname[:-1])
                        if os.path.exists(rpy_path):
                            os.remove(os.path.join(root, fname))
                            rpyc_removed += 1
            if rpyc_removed:
                self.log_message.emit('info', f"Removed {rpyc_removed} stale .rpyc files to force Ren'Py recompile.")
        except Exception as rpyc_err:
            self.logger.debug(f"Failed to clean .rpyc files: {rpyc_err}")

        _old_seg_path = os.path.join(tl_dir, '_rl_segments.rpy')
        if os.path.exists(_old_seg_path):
            try:
                os.remove(_old_seg_path)
                self.emit_log("info", "[AtomicSegments] Removed obsolete _rl_segments.rpy (translations handled by runtime hook)")
                _old_seg_rpyc = _old_seg_path + 'c'
                if os.path.exists(_old_seg_rpyc):
                    os.remove(_old_seg_rpyc)
            except Exception:
                self.logger.debug("Failed to remove old .rpyc file")

        self._create_language_init_file(game_dir)

        tl_files_updated = [
            tl_file for tl_file in self.tl_parser.parse_directory(tl_path, self.target_language)
            if not self._is_generated_export_file(tl_file.file_path)
        ]
        stats = get_translation_stats(tl_files_updated)

        report_dir = tl_dir
        if game_dir and os.path.isdir(game_dir):
            self._create_language_init_file(str(game_dir))
            lang_dir = os.path.join(tl_path, renpy_lang)
            report_dir = lang_dir
            self._generate_strings_json(tl_files_updated, lang_dir, extra_translations=translations)
            self._manage_runtime_hook()
            try:
                from src.core.exporter import export_strings_to_rpy
                if export_strings_to_rpy(str(game_dir), renpy_lang):
                    self.log_message.emit("info", "Auto-exported translation strings to classic .rpy files.")
            except Exception as e:
                self.logger.warning(f"Auto-export to RPY failed: {e}")

        try:
            self._write_translation_reports(report_dir)
            self._emit_coverage_warning_summary()
        except Exception as exc:
            self.logger.debug(f"Failed to write translation reports: {exc}")

        self._set_stage(PipelineStage.COMPLETED, self.config.get_ui_text("stage_completed"))
        summary = self.config.get_ui_text("pipeline_completed_summary").replace("{translated}", str(len(translations))).replace("{saved}", str(saved_count))
        if self.normalize_count:
            summary += f" | {self.config.get_log_text('log_tl_normalized', count=self.normalize_count)}"

        return PipelineResult(
            success=True,
            message=summary,
            stage=PipelineStage.COMPLETED,
            stats=stats,
            output_path=tl_dir
        )

    # ---- Deep Scan & Unrpyc helpers ----

    def _run_deep_scan(self, tl_files, game_dir, tl_path, renpy_lang):
        self.log_message.emit("info", self.config.get_log_text('deep_scan_running'))
        try:
            parser = RenPyParser(self.config)
            scan_res = parser.extract_combined(
                str(game_dir), include_rpy=True, include_rpyc=True,
                include_deep_scan=True, recursive=True,
                exclude_dirs=['renpy', 'common', 'tl', 'lib', 'python-packages'],
                progress_callback=lambda current, total, file_path: self._emit_scan_progress(
                    "Deep scan progress", current, total, file_path, step=25),
            )

            existing = {e.original_text for t in tl_files for e in t.entries}
            missing = []
            _var_only_re = re.compile(r'^\[[a-zA-Z_]\w*\]$')
            _markup_strip_re = re.compile(r'\{[^}]*\}|\[[^\]]*\]')
            for entries in scan_res.values():
                for e in entries:
                    txt = e.get('text')
                    if not txt or len(txt) <= 1:
                        continue
                    if txt in existing:
                        continue
                    _stripped = txt.strip()
                    if _var_only_re.match(_stripped):
                        continue
                    _core = _markup_strip_re.sub('', _stripped).strip()
                    if _core and not re.search(r'[a-zA-Z\u00C0-\u024F]', _core):
                        continue
                    missing.append(e)
                    existing.add(txt)

            if missing:
                self.log_message.emit("info", self.config.get_log_text('deep_scan_found', count=len(missing)))
                if not hasattr(self, '_native_deepscan_entries'):
                    self._native_deepscan_entries = []
                for m in missing:
                    m_text = m.get('text', '')
                    if m_text and len(m_text) > 1:
                        self._native_deepscan_entries.append(m)
                self.log_message.emit('info', f"Deep scan: {len(missing)} entries reserved for pipeline injection (no separate .rpy file).")
        except Exception as e:
            self.log_message.emit("warning", self.config.get_log_text('deep_scan_error', error=str(e)))

    def _run_unrpyc_decompile_scan(self, has_rpyc, game_dir, tl_path, renpy_lang, tl_files):
        self.log_message.emit("debug", self.config.get_log_text('unrpyc_decompile_running', default="Starting unrpyc decompile scan..."))
        try:
            from src.utils.unrpyc_adapter import UnrpycAdapter as _UnrpycAdapter
            from pathlib import Path as _Path
            import glob as _glob

            _adapter = _UnrpycAdapter()
            if _adapter.available:
                _rpyc_files = [
                    _Path(p) for p in _glob.glob(
                        os.path.join(game_dir, '**', '*.rpyc'), recursive=True
                    )
                    if not any(
                        skip in p.replace('\\', '/').split('/')
                        for skip in ('tl', 'renpy', 'common', 'cache', '__pycache__')
                    )
                ]
                if _rpyc_files:
                    with _adapter.decompile_to_temp(_rpyc_files, _Path(game_dir)) as (_tmp, _decompiled):
                        if _decompiled:
                            self.log_message.emit("info", self.config.get_log_text(
                                'unrpyc_decompile_found', default="Unrpyc: {count} file(s) decompiled.", count=len(_decompiled)))
                            _parser_uc = RenPyParser(self.config)
                            _scan_uc = _parser_uc.extract_combined(
                                _tmp, include_rpy=True, include_rpyc=False, include_deep_scan=False,
                                recursive=True, exclude_dirs=['tl', 'cache', '__pycache__'],
                            )
                            _existing_uc = {e.original_text for t in tl_files for e in t.entries}
                            _missing_uc = []
                            for _uc_entries in _scan_uc.values():
                                for _uc_e in _uc_entries:
                                    _txt = _uc_e.get('text')
                                    if _txt and _txt not in _existing_uc and len(_txt) > 1:
                                        _missing_uc.append(_uc_e)
                                        _existing_uc.add(_txt)

                            if _missing_uc:
                                self.log_message.emit("info", self.config.get_log_text(
                                    'unrpyc_decompile_new_strings', default="Unrpyc: {count} additional string(s) found.", count=len(_missing_uc)))
                                _uc_out_dir = os.path.join(tl_path, renpy_lang)
                                os.makedirs(_uc_out_dir, exist_ok=True)
                                _uc_file = os.path.join(_uc_out_dir, "strings_unrpyc.rpy")
                                _uc_lines = [
                                    "# Strings found via unrpyc decompile (complementary to RPYC reader)",
                                    f"translate {renpy_lang} strings:\n",
                                ]
                                for _m in _missing_uc:
                                    _o = _m['text'].replace('"', '\\"').replace('\n', '\\n')
                                    if _m.get('context'):
                                        _uc_lines.append(f"    # context: {_m['context']}")
                                    _uc_lines.append(f'    old "{_o}"\n    new ""\n')
                                with open(_uc_file, 'w', encoding='utf-8') as _f:
                                    _f.write('\n'.join(_uc_lines))
                                for _ntf in self.tl_parser.parse_directory(_uc_out_dir, renpy_lang):
                                    if os.path.normcase(_ntf.file_path) == os.path.normcase(_uc_file):
                                        tl_files.append(_ntf)
                                        break
            else:
                tmp_json = Path('tmp') / 'decompile_extract_results.json'
                if tmp_json.is_file():
                    try:
                        with tmp_json.open('r', encoding='utf-8') as _f:
                            _decomp_data = json.load(_f)
                    except Exception as _je:
                        self.log_message.emit('warning', self.config.get_log_text(
                            'unrpyc_decompile_error', default="Unrpyc decompile scan failed: {error}", error=str(_je)))
                        _decomp_data = {}

                    if _decomp_data:
                        self.log_message.emit('info', self.config.get_log_text(
                            'unrpyc_decompile_found', default="Unrpyc (preview data): using {count} file(s) from tmp.", count=len(_decomp_data)))
                        try:
                            _parser_uc = RenPyParser(self.config)
                            _scan_uc = _decomp_data
                            _existing_uc = {e.original_text for t in tl_files for e in t.entries}
                            _missing_uc = []
                            for _uc_entries in _scan_uc.values():
                                for _uc_e in _uc_entries:
                                    _txt = _uc_e.get('text')
                                    if _txt and _txt not in _existing_uc and len(_txt) > 1:
                                        _missing_uc.append(_uc_e)
                                        _existing_uc.add(_txt)

                            if _missing_uc:
                                self.log_message.emit('info', self.config.get_log_text(
                                    'unrpyc_decompile_new_strings', default="Unrpyc (preview): {count} additional string(s) found.", count=len(_missing_uc)))
                                _uc_out_dir = os.path.join(tl_path, renpy_lang)
                                os.makedirs(_uc_out_dir, exist_ok=True)
                                _uc_file = os.path.join(_uc_out_dir, "strings_unrpyc.rpy")
                                _uc_lines = [
                                    "# Strings found via unrpyc decompile (from tmp/decompile_extract_results.json)",
                                    f"translate {renpy_lang} strings:\n",
                                ]
                                for _m in _missing_uc:
                                    _o = (_m.get('text') or '').replace('"', '\\"').replace('\n', '\\n')
                                    if _m.get('context'):
                                        _uc_lines.append(f"    # context: {_m.get('context')}")
                                    _uc_lines.append(f'    old "{_o}"\n    new ""\n')
                                try:
                                    with open(_uc_file, 'w', encoding='utf-8') as _f:
                                        _f.write('\n'.join(_uc_lines))
                                    for _ntf in self.tl_parser.parse_directory(_uc_out_dir, renpy_lang):
                                        if os.path.normcase(_ntf.file_path) == os.path.normcase(_uc_file):
                                            tl_files.append(_ntf)
                                            break
                                except Exception as _w:
                                    self.log_message.emit('warning', self.config.get_log_text(
                                        'unrpyc_decompile_error', default="Unrpyc decompile write failed: {error}", error=str(_w)))
                        except Exception:
                            self.log_message.emit('debug', 'Unrpyc preview merge failed; skipping.')
                    else:
                        self.log_message.emit("debug", "Unrpyc decompile: no decompiler backend available — skipping.")
                else:
                    self.log_message.emit("debug", "Unrpyc decompile: no decompiler backend available — skipping.")
        except Exception as _uc_exc:
            self.log_message.emit("warning", self.config.get_log_text('unrpyc_decompile_error',
                default="Unrpyc decompile scan failed: {error}", error=str(_uc_exc)))

    # ---- _run_translate_command ----
    # This is too large and deeply coupled; stays as a method.

    def _run_translate_command(self, project_path: str) -> bool:
        """Kaynak dosyaları parse edip tl/ klasörüne çeviri şablonları oluştur"""
        try:
            self.log_message.emit("info", self.config.get_log_text('log_translation_files_creating', lang=self.target_language))

            reverse_lang_map = {v.lower(): k for k, v in RENPY_TO_API_LANG.items()}
            renpy_lang = reverse_lang_map.get(self.target_language.lower(), self.target_language)

            game_dir = os.path.join(project_path, 'game')
            tl_dir = os.path.join(game_dir, 'tl', renpy_lang)

            os.makedirs(tl_dir, exist_ok=True)

            from src.core.parser import RenPyParser
            parser = RenPyParser(self.config)

            use_deep = getattr(self, 'include_deep_scan', False)
            use_rpyc = getattr(self, 'include_rpyc', False)

            if self.config and hasattr(self.config, 'translation_settings'):
                settings = self.config.translation_settings
                if not use_deep:
                    use_deep = getattr(settings, 'enable_deep_scan', getattr(settings, 'use_deep_scan', True))
                use_rpyc = True

            self.log_message.emit("info", "Scanning source .rpy files...")
            parse_results = parser.extract_combined(
                game_dir,
                include_rpy=True,
                include_rpyc=use_rpyc,
                include_deep_scan=use_deep,
                recursive=True,
                exclude_dirs=['tl', 'cache', '__pycache__'],
                progress_callback=lambda current, total, file_path: self._emit_scan_progress(
                    "Source scan progress", current, total, file_path, step=50),
            )
            source_texts = []
            for i, (file_path, entries) in enumerate(parse_results.items()):
                for entry in entries:
                    entry['file_path'] = str(file_path)
                    source_texts.append(entry)
                if i % 50 == 0:
                    time.sleep(0.001)
            self.log_message.emit("info", f"Source scan completed. {len(parse_results)} files processed.")

            renpy_common_path = os.path.normpath(os.path.abspath(os.path.join(game_dir, 'renpy', 'common')))
            if os.path.isdir(renpy_common_path):
                before_len = len(source_texts)
                def abs_path(p):
                    try:
                        return os.path.normpath(os.path.abspath(str(p)))
                    except Exception:
                        return ''
                source_texts = [e for e in source_texts if not abs_path(e.get('file_path', '')).startswith(renpy_common_path)]
                after_len = len(source_texts)
                if before_len != after_len:
                    self.log_message.emit('debug', f'Removed {before_len - after_len} entries from initial game parse that belong to renpy/common to avoid duplicates')

            # Scan renpy/common
            renpy_dir = os.path.join(project_path, 'renpy')
            renpy_common = os.path.join(renpy_dir, 'common')
            if os.path.isdir(renpy_common):
                self.log_message.emit("info", self.config.get_log_text('log_scanning_renpy_common', path=renpy_common))
                from src.core.parser import RenPyParser
                from src.utils.config import ConfigManager as LocalConfig
                import copy
                temp_conf = LocalConfig()
                temp_conf.translation_settings = copy.deepcopy(self.config.translation_settings)
                temp_conf.translation_settings.translate_ui = True
                temp_parser = RenPyParser(temp_conf)
                try:
                    common_results = temp_parser.parse_directory(renpy_common)
                except Exception:
                    common_results = parser.parse_directory(renpy_common)

                for file_path, entries in common_results.items():
                    valid_entries = []
                    for entry in entries:
                        txt = entry.get('text', '')
                        if re.search(r'[\\#\[\](){}|*+^$]', txt):
                            if re.search(r'\*\.\w+|\.\.\/|\\[a-z]', txt):
                                continue
                        if re.search(r'[{}]', txt) and len(txt) > 10:
                            continue
                        if txt.lower().strip() in parser.renpy_technical_terms:
                            continue
                        valid_entries.append(entry)
                    for entry in valid_entries:
                        entry['file_path'] = str(file_path)
                        entry['is_engine_common'] = True
                        source_texts.append(entry)

                if use_rpyc:
                    try:
                        from src.core.rpyc_reader import extract_texts_from_rpyc_directory
                        rpyc_results = extract_texts_from_rpyc_directory(renpy_common)
                        for file_path, entries in rpyc_results.items():
                            for entry in entries:
                                txt = entry.get('text', '')
                                if re.search(r'[\\#\[\](){}|*+^$]', txt):
                                    if re.search(r'\*\.\w+|\.\.\/|\\[a-z]', txt):
                                        continue
                                if re.search(r'[{}]', txt) and len(txt) > 10:
                                    continue
                                if txt.lower().strip() in parser.renpy_technical_terms:
                                    continue
                                patched = dict(entry)
                                patched['file_path'] = str(file_path)
                                patched['is_engine_common'] = True
                                if 'text_type' in patched and 'type' not in patched:
                                    patched['type'] = patched.get('text_type')
                                source_texts.append(patched)
                    except Exception as exc:
                        self.log_message.emit("warning", self.config.get_log_text('log_engine_common_scan_failed', error=str(exc)))

            deep_results = {}
            rpyc_results = {}
            existing_texts = {e['text'] for e in source_texts}
            deep_count = 0

            if use_deep:
                self.log_message.emit("info", self.config.get_log_text('deep_scan_running_short'))
                deep_results = parser.extract_from_directory_with_deep_scan(
                    game_dir,
                    exclude_dirs=['tl', 'cache', '__pycache__'],
                    progress_callback=lambda current, total, file_path: self._emit_scan_progress(
                        "Deep scan progress", current, total, file_path, step=25),
                )

            if use_rpyc:
                self.log_message.emit("warning", "\u23f3 Scanning .rpyc (Binary) database... This may take time depending on file size. Please wait, program is not frozen!")
                self.log_message.emit("info", self.config.get_log_text('rpyc_scan_running'))
                try:
                    from src.core.rpyc_reader import extract_texts_from_rpyc_directory
                    rpyc_results = extract_texts_from_rpyc_directory(game_dir, config_manager=self.config)
                    self.log_message.emit("success", f"\u2705 .rpyc scan completed. {len(rpyc_results)} files processed.")
                except ImportError:
                    self.log_message.emit("warning", self.config.get_log_text('rpyc_module_not_found'))

            if deep_results:
                self.log_message.emit("info", self.config.get_log_text('deep_scan_merging'))
                for file_path, entries in deep_results.items():
                    for entry in entries:
                        if entry.get('is_deep_scan'):
                            entry['file_path'] = str(file_path)
                            source_texts.append(entry)

            if rpyc_results:
                self.log_message.emit("info", self.config.get_log_text('rpyc_data_merging'))
                existing_texts = {e.get('text') for e in source_texts}
                for file_path, entries in rpyc_results.items():
                    for entry in entries:
                        text = entry.get('text', '')
                        if text and text not in existing_texts:
                            entry['file_path'] = str(file_path)
                            source_texts.append(entry)
                            existing_texts.add(text)

            try:
                from src.utils.unrpyc_adapter import UnrpycAdapter
                import tempfile, shutil
                adapter = UnrpycAdapter()
                if adapter.available:
                    tmpdir = tempfile.mkdtemp(prefix="renlocalizer_unrpyc_")
                    try:
                        decompiled = adapter.decompile_directory(game_dir, tmpdir)
                        if decompiled:
                            self.log_message.emit('info', f"Decompiled {len(decompiled)} files; parsing decompiled .rpy for extra texts")
                            decomp_results = parser.extract_combined(
                                tmpdir, include_rpy=True, include_rpyc=False,
                                include_deep_scan=use_deep, recursive=True,
                            )
                            for file_path, entries in decomp_results.items():
                                for entry in entries:
                                    text = entry.get('text')
                                    if text and text not in existing_texts:
                                        entry['file_path'] = str(file_path)
                                        source_texts.append(entry)
                                        existing_texts.add(text)
                    finally:
                        try:
                            shutil.rmtree(tmpdir)
                        except Exception:
                            self.logger.debug("Failed to remove temp directory")
            except Exception as exc:
                self.log_message.emit('warning', self.config.get_log_text('log_decompile_merge_failed', error=str(exc)))

            if not source_texts:
                self.log_message.emit("warning", self.config.get_log_text('no_translatable_texts'))
                return False

            self.log_message.emit("info", self.config.get_log_text('texts_found_creating', count=len(source_texts)))

            existing_global_strings = set()
            try:
                lang_tl_path = os.path.join(game_dir, 'tl', renpy_lang)
                if os.path.isdir(lang_tl_path):
                    string_pair_pattern = re.compile(r'^\s*old\s+"(?P<old>.*?)"\s*\n\s*new\s+"(?P<new>.*?)"\s*$', re.MULTILINE | re.DOTALL)
                    dialogue_block_pat = re.compile(r'^\s*#\s*(?:\w+\s+)?"(?P<old>.*?)"\s*\n\s*(?:\w+\s+)?"(?P<new>.*?)"\s*$', re.MULTILINE | re.DOTALL)
                    for root, dirs, files in os.walk(lang_tl_path):
                        for filename in files:
                            if not filename.lower().endswith('.rpy'):
                                continue
                            filepath = os.path.join(root, filename)
                            try:
                                with open(filepath, 'r', encoding='utf-8-sig', errors='replace') as f:
                                    content = f.read()
                                for match in string_pair_pattern.finditer(content):
                                    old_text = match.group('old')
                                    if old_text:
                                        old_text = old_text.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace('\\\\', '\\')
                                        existing_global_strings.add(old_text)
                                for m2 in dialogue_block_pat.finditer(content):
                                    old_t = m2.group('old')
                                    if old_t:
                                        old_t = old_t.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace('\\\\', '\\')
                                        existing_global_strings.add(old_t)
                                self.logger.debug(f"Scanned {filepath}: found existing entries")
                            except Exception as fe:
                                self.logger.debug(f"Failed to scan {filepath}: {fe}")
                    if existing_global_strings:
                        self.log_message.emit("info", f"Found {len(existing_global_strings)} existing 'old \"...\"' entries in tl/ files (including untranslated placeholders). Skipping these to prevent Ren'Py duplicate-string crash (7.5+/8.x).")
            except Exception as e:
                self.logger.warning(f"Existing TL scan failed: {e}")

            seen_map = {}
            for entry in source_texts:
                text = entry.get('text', '')
                if not text:
                    continue
                if text in existing_global_strings:
                    continue
                existing = seen_map.get(text)
                if not existing:
                    seen_map[text] = entry
                else:
                    if not existing.get('is_engine_common') and entry.get('is_engine_common'):
                        seen_map[text] = entry
                    elif not existing.get('is_deep_scan') and entry.get('is_deep_scan'):
                        seen_map[text] = entry

            use_native = getattr(self.config.translation_settings, 'output_mode', 'strings') == 'native'
            if use_native:
                self._native_ui_entries = [
                    e for e in seen_map.values()
                    if e.get('text_type', '') not in ('dialogue', 'narration', 'extend', 'bubble_dialogue', 'nvl_dialogue')
                ]
                if self._native_ui_entries:
                    self.log_message.emit('info', f"Native TLID: {len(self._native_ui_entries)} UI entries reserved for runtime hook translation.")

            file_groups = {}
            seen_texts = set()
            for t in existing_global_strings:
                seen_texts.add(t)

            for entry in source_texts:
                text = entry.get('text', '')
                if not text or text in seen_texts:
                    continue
                file_path = entry.get('file_path', '')
                try:
                    if game_dir in file_path:
                        rel_path = os.path.relpath(file_path, game_dir)
                    else:
                        if 'renpy' in file_path and 'common' in file_path:
                            rel_path = os.path.join('_engine', 'common', os.path.basename(file_path))
                        else:
                            rel_path = 'external_libs.rpy'
                    rel_path = os.path.splitext(rel_path)[0] + '.rpy'
                    rel_path = rel_path.lstrip('./\\')
                except Exception:
                    rel_path = 'strings.rpy'

                if rel_path not in file_groups:
                    file_groups[rel_path] = []
                file_groups[rel_path].append(entry)
                seen_texts.add(text)

            if not file_groups:
                self.log_message.emit("info", "No new strings to generate for translation files.")
                return True

            self.log_message.emit("info", f"Generating {len(file_groups)} separate translation files for {renpy_lang}...")
            generated_count = 0
            total_entries_count = 0

            for rel_path, entries in file_groups.items():
                if self.should_stop:
                    return False
                try:
                    use_native2 = getattr(self.config.translation_settings, 'output_mode', 'strings') == 'native'
                    if use_native2:
                        content = generate_native_tlid_content(
                            entries, game_dir,
                            target_language=self.target_language,
                            source_language=self.source_language,
                            engine=self.engine,
                            translation_manager=self.translation_manager,
                            config=self.config,
                            lang_name=renpy_lang,
                        )
                    else:
                        content = generate_all_strings_file(
                            entries, game_dir,
                            target_language=self.target_language,
                            source_language=self.source_language,
                            engine=self.engine,
                            translation_manager=self.translation_manager,
                            config=self.config,
                            log_emit=self.log_message.emit,
                            lang_name=renpy_lang,
                        )
                    if not content:
                        continue

                    full_path = os.path.normpath(os.path.join(tl_dir, rel_path))
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)

                    temp_path = full_path + '.tmp'
                    with open(temp_path, 'w', encoding='utf-8-sig', newline='\n') as f:
                        f.write(content)
                        f.flush()
                        os.fsync(f.fileno())

                    if os.path.exists(full_path):
                        translate_start = content.find(f'translate {renpy_lang} strings:')
                        if translate_start >= 0:
                            append_block = '\n\n' + content[translate_start:]
                            try:
                                with open(full_path, 'a', encoding='utf-8-sig', newline='\n') as fa:
                                    fa.write(append_block)
                                os.remove(temp_path)
                            except Exception as _append_err:
                                self.logger.warning(f"Append failed for {rel_path}, falling back to replace: {_append_err}")
                                os.replace(temp_path, full_path)
                        else:
                            os.remove(temp_path)
                    else:
                        os.rename(temp_path, full_path)

                    generated_count += 1
                    total_entries_count += len(entries)

                except Exception as fe:
                    self.logger.error(f"Failed to generate {rel_path}: {fe}")
                    continue

            self.log_message.emit("success", f"Successfully created {generated_count} translation files ({total_entries_count} unique strings total).")

            try:
                diag_dir = os.path.join(tl_dir, 'diagnostics')
                os.makedirs(diag_dir, exist_ok=True)
                sig_path = os.path.join(diag_dir, 'rpyc_extraction_signature.json')
                save_text_safely(
                    Path(sig_path),
                    json.dumps({
                        'signature': 'rpyc_reader_slot12_encoding_fallback_root_filter_v1',
                        'written_at': int(time.time()),
                    }, ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )
            except Exception as sig_err:
                self.logger.debug(f"Failed to write RPYC extraction signature: {sig_err}")

            return True

        except Exception as e:
            self.log_message.emit("error", self.config.get_log_text('translation_file_error', error=str(e)))
            return False

    # ---- _translate_entries (stays as method due to deep coupling) ----
    # This method is ~940 lines and deeply coupled. It remains here for now,
    # delegating helper calls to the translating submodule where possible.

    def _translate_entries(self, entries: List[TranslationEntry]) -> Dict[str, str]:
        """Girişleri çevir (placeholder koruması zorunlu)."""
        from src.core.translator import protect_renpy_syntax
        from src.core.syntax_guard import (
            split_delimited_text, rejoin_delimited_text,
            split_angle_pipe_groups, rejoin_angle_pipe_groups,
            protect_renpy_syntax_xml, restore_renpy_syntax_xml,
        )
        translations = {}
        self._last_atomic_segments = {}
        formatter = RenPyOutputFormatter()

        filtered_entries: List[TranslationEntry] = []
        for entry in entries:
            if self._is_nontranslatable_identifier_entry(entry):
                continue
            if formatter._should_skip_translation(entry.original_text):
                continue
            filtered_entries.append(entry)

        skipped = len(entries) - len(filtered_entries)
        if skipped:
            self.log_message.emit("debug", self.config.get_log_text('placeholder_excluded', count=skipped))

        entries = filtered_entries
        total = len(entries)

        self.translation_manager.should_stop_callback = lambda: self.should_stop
        for engine_type, translator in self.translation_manager.translators.items():
            if hasattr(translator, 'status_callback'):
                translator.status_callback = self.log_message.emit
            if hasattr(translator, 'should_stop_callback'):
                translator.should_stop_callback = lambda: self.should_stop
        if total == 0:
            return translations

        requested_batch_size = self._get_requested_translation_batch_size()
        batch_size = self._get_effective_translation_batch_size()

        if self.engine in (TranslationEngine.OPENAI, TranslationEngine.GEMINI, TranslationEngine.LOCAL_LLM):
            self.log_message.emit("debug", f"AI engine detected, using batch size: {batch_size}")
            if batch_size > 1000:
                self.log_message.emit("info", self.config.get_log_text(
                    'log_ai_batch_large_notice',
                    'Large AI batch size in use ({batch}). This may increase token usage, latency, or API failure risk.',
                    batch=batch_size,
                ))
        else:
            self._emit_batch_size_cap_notice_if_needed(requested_batch_size, batch_size)

        api_target_lang = RENPY_TO_API_LANG.get(self.target_language, self.target_language)
        api_source_lang = RENPY_TO_API_LANG.get(self.source_language, self.source_language)

        if self.source_language.lower() == "auto" and self.engine == TranslationEngine.GOOGLE:
            self.log_message.emit("info", self.config.get_log_text('smart_detect_starting', "[Smart Detect] Kaynak dil tespit ediliyor..."))
            text_samples = [e.original_text for e in entries]
            translator = self.translation_manager.translators.get(TranslationEngine.GOOGLE)
            if not translator:
                translator = GoogleTranslator(config_manager=self.config)
                self.translation_manager.add_translator(TranslationEngine.GOOGLE, translator)
            try:
                detection_translator = GoogleTranslator(config_manager=self.config)
                detect_loop = asyncio.new_event_loop()
                detected_lang = detect_loop.run_until_complete(
                    detection_translator.detect_language(text_samples, target_lang=api_target_lang)
                )
                detect_loop.run_until_complete(detection_translator.close_session())
                detect_loop.close()
                if detected_lang:
                    api_source_lang = detected_lang
                    self.log_message.emit("info", self.config.get_log_text(
                        'smart_detect_success', f"[Smart Detect] \u2713 Kaynak dil tespit edildi: {detected_lang.upper()}"))
                else:
                    self.log_message.emit("warning", self.config.get_log_text(
                        'smart_detect_fallback', "[Smart Detect] Guven esigi gecilemedi, 'auto' modunda devam ediliyor."))
                    api_source_lang = "auto"
            except Exception as e:
                self.logger.warning(f"Smart language detection failed: {e}")
                api_source_lang = "auto"

        should_use_global_cache = getattr(self.config.translation_settings, 'use_global_cache', True)
        if should_use_global_cache:
            from src.utils.path_manager import get_project_id
            project_name = get_project_id(self.project_path, self.game_exe_path)
            base_cache_dir = os.path.join(self.config.data_dir, getattr(self.config.translation_settings, 'cache_path', 'cache'))
            cache_dir = os.path.join(base_cache_dir, project_name, self.target_language)
            self.log_message.emit("info", f"Using global data cache: [{project_name}]")
        else:
            cache_dir = os.path.join(self.project_path, 'game', 'tl', self.target_language)
            self.log_message.emit("info", "Using local project-specific cache.")

        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, "translation_cache.json")
        self.translation_manager.load_cache(cache_file)

        _external_tm = None
        _tm_hit_count = 0
        if getattr(self.config.translation_settings, 'use_external_tm', False):
            try:
                import json as _json
                tm_source_paths = _json.loads(
                    getattr(self.config.translation_settings, 'external_tm_sources', '[]')
                )
                if tm_source_paths:
                    from src.tools.external_tm import ExternalTMStore
                    tm_dir = str(os.path.join(self.config.data_dir, "tm"))
                    _external_tm = ExternalTMStore(tm_dir=tm_dir)
                    loaded = _external_tm.load_sources(tm_source_paths)
                    if loaded > 0:
                        self.log_message.emit("info", f"[ExternalTM] {loaded} entry loaded from {_external_tm.loaded_source_count} source(s)")
                    else:
                        self.log_message.emit("warning", "[ExternalTM] No entries loaded — TM lookup disabled")
                        _external_tm = None
            except Exception as _tm_err:
                self.logger.warning(f"External TM load failed: {_tm_err}")
                _external_tm = None

        if total == 0:
            self.translation_manager.save_cache(cache_file)
            return translations

        self.log_message.emit("info", self.config.get_log_text('translation_lang_api', lang=self.target_language, api=api_target_lang))

        loop = asyncio.new_event_loop()

        if self.engine == TranslationEngine.GOOGLE and self.engine not in self.translation_manager.translators:
            gt = GoogleTranslator(config_manager=self.config, proxy_manager=getattr(self.translation_manager, "proxy_manager", None))
            self.translation_manager.add_translator(TranslationEngine.GOOGLE, gt)
        if self.engine == TranslationEngine.DEEPL and self.engine not in self.translation_manager.translators:
            deepl_key = getattr(getattr(self.config, "api_keys", None), "deepl_api_key", "") or ""
            dt = DeepLTranslator(api_key=deepl_key, proxy_manager=getattr(self.translation_manager, "proxy_manager", None), config_manager=self.config)
            dt.status_callback = self.log_message.emit
            self.translation_manager.add_translator(TranslationEngine.DEEPL, dt)

        if self.engine == TranslationEngine.OPENAI and self.engine not in self.translation_manager.translators:
            base_url = self.config.translation_settings.openai_base_url
            api_key_to_use = self.config.api_keys.openai_api_key
            if base_url and "deepseek" in base_url.lower():
                ds_key = getattr(self.config.api_keys, "deepseek_api_key", "")
                if ds_key:
                    self.log_message.emit("info", self.config.get_log_text('log_deepseek_mode'))
                    api_key_to_use = ds_key
                else:
                    self.log_message.emit("info", self.config.get_log_text('log_deepseek_fallback'))
            t = OpenAITranslator(
                api_key=api_key_to_use, model=self.config.translation_settings.openai_model,
                base_url=base_url, proxy_manager=getattr(self.translation_manager, "proxy_manager", None),
                config_manager=self.config, temperature=self.config.translation_settings.ai_temperature,
                timeout=self.config.translation_settings.ai_timeout,
                max_tokens=self.config.translation_settings.ai_max_tokens
            )
            t.status_callback = self.log_message.emit
            self.translation_manager.add_translator(TranslationEngine.OPENAI, t)

        if self.engine == TranslationEngine.GEMINI and self.engine not in self.translation_manager.translators:
            t = GeminiTranslator(
                api_key=self.config.api_keys.gemini_api_key, model=self.config.translation_settings.gemini_model,
                safety_level=self.config.translation_settings.gemini_safety_settings,
                proxy_manager=getattr(self.translation_manager, "proxy_manager", None),
                config_manager=self.config, temperature=self.config.translation_settings.ai_temperature,
                timeout=self.config.translation_settings.ai_timeout,
                max_tokens=self.config.translation_settings.ai_max_tokens
            )
            fallback = GoogleTranslator(proxy_manager=getattr(self.translation_manager, "proxy_manager", None), config_manager=self.config)
            fallback.status_callback = self.log_message.emit
            t.set_fallback_translator(fallback)
            t.status_callback = self.log_message.emit
            self.translation_manager.add_translator(TranslationEngine.GEMINI, t)

        if self.engine == TranslationEngine.LOCAL_LLM and self.engine not in self.translation_manager.translators:
            t = LocalLLMTranslator(
                model=self.config.translation_settings.local_llm_model,
                base_url=self.config.translation_settings.local_llm_url,
                proxy_manager=getattr(self.translation_manager, "proxy_manager", None),
                config_manager=self.config, temperature=self.config.translation_settings.ai_temperature,
                timeout=self.config.translation_settings.ai_timeout,
                max_tokens=self.config.translation_settings.ai_max_tokens
            )
            t.status_callback = self.log_message.emit
            self.translation_manager.add_translator(TranslationEngine.LOCAL_LLM, t)

        if self.engine == TranslationEngine.LIBRETRANSLATE and self.engine not in self.translation_manager.translators:
            from src.core.translator import LibreTranslateTranslator
            t = LibreTranslateTranslator(
                base_url=self.config.translation_settings.libretranslate_url,
                api_key=self.config.translation_settings.libretranslate_api_key,
                proxy_manager=getattr(self.translation_manager, "proxy_manager", None),
                config_manager=self.config
            )
            t.status_callback = self.log_message.emit
            self.translation_manager.add_translator(TranslationEngine.LIBRETRANSLATE, t)

        _auto_names_added = 0
        if getattr(self.config.translation_settings, 'auto_protect_character_names', True):
            existing_glossary = self.config.glossary if hasattr(self.config, 'glossary') and self.config.glossary else {}
            existing_lower = {k.lower() for k in existing_glossary}
            char_names: set = set()
            for entry in entries:
                c = getattr(entry, 'character', '') or ''
                c = c.strip()
                if (c and len(c) >= 2 and not c.startswith('[') and not c.startswith('{')
                        and not c.startswith('$') and c.lower() not in existing_lower and c[0].isupper()):
                    char_names.add(c)
            if char_names:
                _lock = getattr(self.config, '_lock', None)
                if _lock:
                    _lock.acquire()
                try:
                    for name in char_names:
                        existing_glossary[name] = name
                    self.config.glossary = existing_glossary
                finally:
                    if _lock:
                        _lock.release()
                _auto_names_added = len(char_names)
                self.log_message.emit("info", f"[AutoProtect] {_auto_names_added} character name(s) protected: {', '.join(sorted(char_names)[:10])}")

        try:
            unchanged_count = 0
            failed_entries: List[str] = []
            sample_logs: List[str] = []
            stop_quota = False
            is_ai_engine = self.engine in (TranslationEngine.OPENAI, TranslationEngine.GEMINI, TranslationEngine.LOCAL_LLM)
            for i in range(0, total, batch_size):
                if self.should_stop:
                    break

                batch = entries[i:i + batch_size]
                current = min(i + batch_size, total)
                if batch:
                    self.progress_updated.emit(current, total, batch[0].original_text[:50])

                requests = []
                _delimiter_groups = {}
                _multi_group_data = {}
                _delimiter_enabled = getattr(self.config.translation_settings, 'enable_delimiter_aware_translation', True)
                _tm_resolved_indices = set()
                _prev_entry_text = None
                _prev_entry_file = None

                for entry_idx, entry in enumerate(batch):
                    translation_id = getattr(entry, 'translation_id', '') or TLParser.make_translation_id(
                        entry.file_path, entry.line_number, entry.original_text,
                        getattr(entry, 'context_path', []), getattr(entry, 'raw_text', None)
                    )

                    if _external_tm is not None:
                        _tm_result = _external_tm.get_exact(entry.original_text)
                        if _tm_result is not None:
                            translations[translation_id] = _tm_result
                            translations.setdefault(entry.original_text, _tm_result)
                            _tm_hit_count += 1
                            _tm_resolved_indices.add(entry_idx)
                            try:
                                if _tm_result != entry.original_text:
                                    self.diagnostic_report.mark_translated(
                                        entry.file_path, translation_id, _tm_result, original_text=entry.original_text)
                                else:
                                    self.diagnostic_report.mark_unchanged(
                                        entry.file_path, translation_id, original_text=entry.original_text)
                            except Exception:
                                self.logger.warning("diagnostic mark_unchanged failed for translation_id=%s in %s", translation_id, entry.file_path)
                            _prev_entry_text = entry.original_text
                            _prev_entry_file = entry.file_path
                            continue

                    multi_result = split_angle_pipe_groups(entry.original_text) if _delimiter_enabled else None
                    if multi_result is not None:
                        template, groups = multi_result
                        req_start_idx = len(requests)
                        group_lens = [len(g) for g in groups]
                        _multi_group_data[entry_idx] = (req_start_idx, group_lens, translation_id, entry.original_text)
                        _log_preview = entry.original_text[:80].replace('<', '\u2039').replace('>', '\u203a')
                        self.log_message.emit("debug", f"[MultiGroup] {len(groups)} groups ({sum(group_lens)} segments): {_log_preview}")

                        if is_ai_engine:
                            protected_template, ph_template = protect_renpy_syntax_xml(template)
                            protected_template, gph_template = self._protect_glossary_terms(protected_template, xml_mode=True)
                        else:
                            protected_template, ph_template = protect_renpy_syntax(template)
                            protected_template, gph_template = self._protect_glossary_terms(protected_template)
                        ph_template.update(gph_template)

                        requests.append(TranslationRequest(
                            text=protected_template, source_lang=api_source_lang, target_lang=api_target_lang,
                            engine=self.engine,
                            metadata={'preprotected': True, 'original_text': template, 'entry': entry,
                                      'translation_id': translation_id, 'file_path': entry.file_path,
                                      'line_number': entry.line_number,
                                      'context_path': getattr(entry, 'context_path', []),
                                      'placeholders': ph_template, 'xml_mode': is_ai_engine,
                                      '_multi_group_template': True}
                        ))

                        for group in groups:
                            for seg in group:
                                seg_text = seg.strip()
                                if is_ai_engine:
                                    protected_seg, ph_seg = protect_renpy_syntax_xml(seg_text)
                                    protected_seg, gph_seg = self._protect_glossary_terms(protected_seg, xml_mode=True)
                                else:
                                    protected_seg, ph_seg = protect_renpy_syntax(seg_text)
                                    protected_seg, gph_seg = self._protect_glossary_terms(protected_seg)
                                ph_seg.update(gph_seg)
                                requests.append(TranslationRequest(
                                    text=protected_seg, source_lang=api_source_lang, target_lang=api_target_lang,
                                    engine=self.engine,
                                    metadata={'preprotected': True, 'original_text': seg_text, 'entry': entry,
                                              'translation_id': translation_id, 'file_path': entry.file_path,
                                              'line_number': entry.line_number,
                                              'context_path': getattr(entry, 'context_path', []),
                                              'placeholders': ph_seg, 'xml_mode': is_ai_engine,
                                              '_multi_group_segment': True}
                                ))
                        _prev_entry_text = entry.original_text
                        _prev_entry_file = entry.file_path
                        continue

                    delim_result = split_delimited_text(entry.original_text) if _delimiter_enabled else None
                    if delim_result is not None:
                        segments, delimiter, d_prefix, d_suffix = delim_result
                        req_start_idx = len(requests)
                        _delimiter_groups[entry_idx] = (req_start_idx, len(segments), delimiter, d_prefix, d_suffix, translation_id, entry.original_text)
                        _log_preview = entry.original_text[:80].replace('<', '\u2039').replace('>', '\u203a')
                        self.log_message.emit("debug", f"[Delimiter] Split into {len(segments)} segments: {_log_preview}")
                        for seg in segments:
                            seg_text = seg.strip()
                            if is_ai_engine:
                                protected_text, placeholders = protect_renpy_syntax_xml(seg_text)
                                protected_text, glossary_placeholders = self._protect_glossary_terms(protected_text, xml_mode=True)
                            else:
                                protected_text, placeholders = protect_renpy_syntax(seg_text)
                                protected_text, glossary_placeholders = self._protect_glossary_terms(protected_text)
                            placeholders.update(glossary_placeholders)
                            req = TranslationRequest(
                                text=protected_text, source_lang=api_source_lang, target_lang=api_target_lang,
                                engine=self.engine,
                                metadata={'preprotected': True, 'original_text': seg_text, 'entry': entry,
                                          'translation_id': translation_id, 'file_path': entry.file_path,
                                          'line_number': entry.line_number,
                                          'context_path': getattr(entry, 'context_path', []),
                                          'placeholders': placeholders, 'xml_mode': is_ai_engine,
                                          '_delimiter_segment': True}
                            )
                            requests.append(req)
                        _prev_entry_text = entry.original_text
                        _prev_entry_file = entry.file_path
                        continue

                    if is_ai_engine:
                        protected_text, placeholders = protect_renpy_syntax_xml(entry.original_text)
                        protected_text, glossary_placeholders = self._protect_glossary_terms(protected_text, xml_mode=True)
                    else:
                        protected_text, placeholders = protect_renpy_syntax(entry.original_text)
                        protected_text, glossary_placeholders = self._protect_glossary_terms(protected_text)
                    placeholders.update(glossary_placeholders)

                    req = TranslationRequest(
                        text=protected_text, source_lang=api_source_lang, target_lang=api_target_lang,
                        engine=self.engine,
                        metadata={'preprotected': True, 'original_text': entry.original_text, 'entry': entry,
                                  'translation_id': translation_id, 'file_path': entry.file_path,
                                  'line_number': entry.line_number,
                                  'context_path': getattr(entry, 'context_path', []),
                                  'placeholders': placeholders, 'xml_mode': is_ai_engine,
                                  'context_hint': _prev_entry_text if (
                                      getattr(entry, 'text_type', '') == 'extend'
                                      and _prev_entry_file == entry.file_path
                                  ) else None}
                    )
                    requests.append(req)
                    _prev_entry_text = entry.original_text
                    _prev_entry_file = entry.file_path

                self.translation_manager.set_proxy_enabled(self.use_proxy)
                self.translation_manager.ai_request_delay = getattr(self.config.translation_settings, 'ai_request_delay', 1.5)
                results = loop.run_until_complete(self.translation_manager.translate_batch(requests))

                _entry_results = []
                _atomic_segments = []
                _req_cursor = 0

                for entry_idx, entry in enumerate(batch):
                    if entry_idx in _tm_resolved_indices:
                        continue

                    if entry_idx in _multi_group_data:
                        req_start, group_lens, tid, orig_text = _multi_group_data[entry_idx]
                        total_reqs = 1 + sum(group_lens)
                        template_idx = req_start
                        all_success = True
                        seg_error = None

                        if template_idx < len(results):
                            template_result = results[template_idx]
                            if not template_result.success or not template_result.translated_text:
                                all_success = False
                                seg_error = (template_result.error or "empty_template")
                                if template_result.quota_exceeded:
                                    stop_quota = True
                        else:
                            all_success = False
                            seg_error = "missing_template_result"

                        translated_template = None
                        translated_groups = []

                        if all_success:
                            translated_template = template_result.translated_text
                            if self.config and hasattr(self.config, 'glossary') and self.config.glossary:
                                translated_template = formatter.apply_glossary(
                                    text=translated_template, glossary=self.config.glossary,
                                    original_text=template_result.metadata.get('original_text', '')
                                )
                            seg_cursor = req_start + 1
                            for gl in group_lens:
                                group_segs = []
                                for s in range(gl):
                                    r_idx = seg_cursor + s
                                    if r_idx < len(results):
                                        result = results[r_idx]
                                        if result.success and result.translated_text:
                                            raw = result.translated_text
                                            if self.config and hasattr(self.config, 'glossary') and self.config.glossary:
                                                raw = formatter.apply_glossary(
                                                    text=raw, glossary=self.config.glossary,
                                                    original_text=result.metadata.get('original_text', '')
                                                )
                                            group_segs.append(raw)
                                        else:
                                            all_success = False
                                            seg_error = result.error or "empty_segment"
                                            if result.quota_exceeded:
                                                stop_quota = True
                                            break
                                        if result.quota_exceeded:
                                            stop_quota = True
                                    else:
                                        all_success = False
                                        seg_error = "missing_segment_result"
                                        break
                                translated_groups.append(group_segs)
                                seg_cursor += gl
                                if not all_success:
                                    break

                        _req_cursor = req_start + total_reqs

                        if all_success and translated_template and len(translated_groups) == len(group_lens):
                            restored = rejoin_angle_pipe_groups(translated_template, translated_groups)
                            if restored is None:
                                self.log_message.emit("guard", self.config.get_log_text(
                                    'log_guard_structural_original',
                                    '{category} guard kept original text after structural validation: {preview}',
                                    category='[MultiGroup]', preview=orig_text[:80],
                                ))
                                _entry_results.append((tid, orig_text, entry, True, None, None))
                            else:
                                _entry_results.append((tid, restored, entry, True, None, None))
                                seg_r_cursor = req_start + 1
                                for grp_segs in translated_groups:
                                    for tr_seg in grp_segs:
                                        if seg_r_cursor < len(results):
                                            orig_seg = results[seg_r_cursor].metadata.get('original_text', '')
                                            if orig_seg and tr_seg and orig_seg != tr_seg:
                                                _atomic_segments.append((orig_seg, tr_seg))
                                            seg_r_cursor += 1
                        else:
                            _entry_results.append((tid, None, entry, False, seg_error, None))

                    elif entry_idx in _delimiter_groups:
                        req_start, seg_count, delim, d_prefix, d_suffix, tid, orig_text = _delimiter_groups[entry_idx]
                        translated_segments = []
                        all_success = True
                        seg_error = None

                        for seg_i in range(seg_count):
                            r_idx = req_start + seg_i
                            if r_idx < len(results):
                                result = results[r_idx]
                                if result.success and result.translated_text:
                                    raw = result.translated_text
                                    if self.config and hasattr(self.config, 'glossary') and self.config.glossary:
                                        raw = formatter.apply_glossary(
                                            text=raw, glossary=self.config.glossary,
                                            original_text=result.metadata.get('original_text', '')
                                        )
                                    translated_segments.append(raw)
                                else:
                                    all_success = False
                                    seg_error = result.error or "empty"
                                    if result.quota_exceeded:
                                        stop_quota = True
                                    break
                                if result.quota_exceeded:
                                    stop_quota = True
                            else:
                                all_success = False
                                seg_error = "missing_result"
                                break

                        _req_cursor = req_start + seg_count

                        if all_success and len(translated_segments) == seg_count:
                            restored = rejoin_delimited_text(translated_segments, delim, d_prefix, d_suffix, original_text=orig_text)
                            if restored is None:
                                self.log_message.emit("guard", self.config.get_log_text(
                                    'log_guard_structural_original',
                                    '{category} guard kept original text after structural validation: {preview}',
                                    category='[Delimiter]', preview=orig_text[:80],
                                ))
                                _entry_results.append((tid, orig_text, entry, True, None, None))
                            else:
                                _entry_results.append((tid, restored, entry, True, None, None))
                                for seg_i in range(seg_count):
                                    r_idx = req_start + seg_i
                                    if r_idx < len(results) and results[r_idx].success:
                                        orig_seg = results[r_idx].metadata.get('original_text', '')
                                        tr_seg = translated_segments[seg_i] if seg_i < len(translated_segments) else ''
                                        if orig_seg and tr_seg and orig_seg != tr_seg:
                                            _atomic_segments.append((orig_seg, tr_seg))
                        else:
                            _entry_results.append((tid, None, entry, False, seg_error, None))
                    else:
                        if _req_cursor < len(results):
                            result_request = requests[_req_cursor]
                            result = results[_req_cursor]
                            _req_cursor += 1
                            if result.quota_exceeded:
                                stop_quota = True
                            if result.success:
                                translated_raw = result.translated_text
                                if self.config and hasattr(self.config, 'glossary') and self.config.glossary:
                                    translated_raw = formatter.apply_glossary(
                                        text=translated_raw, glossary=self.config.glossary,
                                        original_text=entry.original_text
                                    )
                                restored = translated_raw if translated_raw else ""
                                _entry_results.append((result.metadata.get('translation_id') or result.original_text, restored, entry, True, None, result_request))
                            else:
                                _entry_results.append((result.metadata.get('translation_id') or result.original_text, None, entry, False, result.error or "empty", result_request))
                        else:
                            _entry_results.append(("", None, entry, False, "missing_result", None))

                for tid, restored, entry, success, error, request in _entry_results:
                    if success and restored is not None:
                        retry_recovered = False
                        blocked_reason = None
                        if restored.strip() == entry.original_text.strip() and self._should_retry_unchanged_core_ui(entry.original_text):
                            restored, retry_recovered = retry_unchanged_core_ui(loop, request, entry, restored, self.translation_manager)
                            if retry_recovered and self.config and hasattr(self.config, 'glossary') and self.config.glossary:
                                restored = formatter.apply_glossary(
                                    text=restored, glossary=self.config.glossary, original_text=entry.original_text,
                                )

                        restored, blocked_reason = self._sanitize_translation_for_output(
                            original=entry.original_text, translated=restored,
                            file_path=entry.file_path, translation_id=tid, line_number=entry.line_number,
                        )
                        if blocked_reason is not None:
                            guard_reason_text = self._get_guard_reason_text(blocked_reason)
                            self.log_message.emit("guard", self.config.get_log_text(
                                'log_guard_reverted_translation',
                                'Guard kept original text after suspicious translator output ({reason}) in {path}:{line}',
                                reason=guard_reason_text, path=entry.file_path, line=entry.line_number,
                            ))

                        if restored:
                            translations[tid] = restored
                            translations.setdefault(entry.original_text, restored)
                            try:
                                file_path = entry.file_path
                                if blocked_reason is not None:
                                    pass
                                elif retry_recovered:
                                    self.diagnostic_report.mark_translated(file_path, tid, restored, original_text=entry.original_text)
                                    self.diagnostic_report.mark_recovered(file_path, tid, 'retry', original_text=entry.original_text, translated_text=restored)
                                    self._record_translation_guard_event(
                                        category='recovered_by_retry', file_path=file_path, translation_id=tid,
                                        original_text=entry.original_text, translated_text=restored,
                                        detail='core_ui_retry', line_number=entry.line_number,
                                    )
                                elif restored == entry.original_text:
                                    unchanged_reason = 'unchanged_core_ui' if self._should_retry_unchanged_core_ui(entry.original_text) else None
                                    self.diagnostic_report.mark_unchanged(file_path, tid, original_text=entry.original_text, reason=unchanged_reason)
                                    if unchanged_reason:
                                        self._record_translation_guard_event(
                                            category='unchanged_by_engine', file_path=file_path, translation_id=tid,
                                            original_text=entry.original_text, translated_text=restored,
                                            detail=unchanged_reason, line_number=entry.line_number,
                                        )
                                else:
                                    self.diagnostic_report.mark_translated(file_path, tid, restored, original_text=entry.original_text)
                            except Exception:
                                self.logger.warning("diagnostic mark_translated failed for %s (%s)", tid, file_path)

                            if restored == entry.original_text and blocked_reason is None:
                                unchanged_count += 1
                                if len(sample_logs) < 5:
                                    sample_logs.append(f"UNCHANGED {entry.file_path}:{entry.line_number} -> {entry.original_text[:80]}")
                    else:
                        err = error or "empty"
                        file_info = f"{entry.file_path}:{entry.line_number}"
                        if file_info == ":":
                            err_entry = f"({err})"
                        else:
                            err_entry = f"{file_info} ({err})"
                        failed_entries.append(err_entry)
                        try:
                            self.diagnostic_report.mark_skipped(entry.file_path, f"translate_failed:{err}", {'text': entry.original_text, 'line_number': entry.line_number})
                        except Exception:
                            self.logger.warning("diagnostic mark_skipped failed for %s", entry.file_path)

                if _atomic_segments:
                    _seg_added = 0
                    for orig_seg, tr_seg in _atomic_segments:
                        safe_seg, blocked_reason = self._sanitize_translation_for_output(
                            original=orig_seg, translated=tr_seg, file_path='strings.json', translation_id=orig_seg,
                        )
                        if blocked_reason is not None or safe_seg == orig_seg:
                            continue
                        if orig_seg not in translations:
                            translations[orig_seg] = safe_seg
                            self._last_atomic_segments[orig_seg] = safe_seg
                            _seg_added += 1
                    if _seg_added:
                        self.emit_log("debug", f"[AtomicSegments] {_seg_added} individual segment translations registered from delimiter groups")

                if current % 500 == 0:
                    self.translation_manager.save_cache(cache_file)
                    self.emit_log("debug", f"Checkpoint saved: {cache_file} (Progress: {current}/{total})")

                if stop_quota:
                    engine_name = getattr(self.engine, 'value', str(self.engine))
                    self.log_message.emit("error", self.config.get_log_text('error_api_quota', engine=engine_name))
                    self.should_stop = True
                    break
                self.emit_log("info", self.config.get_log_text('translated_count', current=current, total=total))

            if unchanged_count:
                self.log_message.emit("warning", self.config.get_log_text('unchanged_count_msg', unchanged=unchanged_count, total=len(translations)))
                for s in sample_logs:
                    self.log_message.emit("warning", s)
                self._log_error(f"UNCHANGED translations: {unchanged_count} / {len(translations)}\n" + "\n".join(sample_logs))
                is_aggressive = getattr(self.config.translation_settings, 'aggressive_retry_translation', False)
                if not is_aggressive:
                    self.log_message.emit("info", self.config.get_log_text('log_hint_aggressive_retry'))

            if failed_entries:
                sample = "\n".join(failed_entries[:10])
                self.log_message.emit("warning", self.config.get_log_text('translation_failed_count', count=len(failed_entries), sample=sample))
                self._log_error(f"Translation failures ({len(failed_entries)}):\n{sample}")

            self.translation_manager.save_cache(cache_file)
            self.log_message.emit("info", self.config.get_log_text('log_cache_saved', path=cache_file, count=len(translations)))

            if _external_tm is not None and _tm_hit_count > 0:
                _tm_stats = _external_tm.stats
                _source_names = _external_tm.loaded_source_names
                self.log_message.emit("info", f"[ExternalTM] {_tm_hit_count} entries resolved from TM (hit rate: {_tm_stats['hit_rate']}%, {_tm_stats['misses']} misses)")
                if _source_names:
                    self.log_message.emit("info", f"[ExternalTM] Sources: {', '.join(_source_names)}")
                self.log_message.emit("debug", f"[ExternalTM] Total TM entries in memory: {_tm_stats['entries']} from {_tm_stats['sources']} source(s)")

        finally:
            try:
                if loop.is_running():
                    pass
                loop.run_until_complete(self.translation_manager.close_all())
                loop.run_until_complete(loop.shutdown_asyncgens())
                if hasattr(loop, 'shutdown_default_executor'):
                    loop.run_until_complete(loop.shutdown_default_executor())
                loop.close()
            except Exception as e:
                self.logger.debug(f"Loop cleanup notice: {e}")

        return translations

    # ---- _generate_strings_json (stays as method due to deep coupling) ----

    def _generate_strings_json(self, tl_files: List[TranslationFile], lang_dir: str, extra_translations: dict = None):
        """Tüm çevirileri strings.json dosyasına aktarır."""
        try:
            mapping: Dict[str, str] = {}
            skipped_corrupt = 0
            skipped_reason_counts = {
                'separator_remnant': 0, 'placeholder_remnant': 0, 'html_leakage': 0,
                'length_inflation': 0, 'placeholder_set_mismatch': 0,
                'renpy_tag_set_mismatch': 0, 'duplicate_key_conflict': 0,
                'case_insensitive_conflict': 0,
            }
            mapping_sources: Dict[str, List[dict]] = {}
            lower_to_orig: Dict[str, List[str]] = {}
            skipped_samples = []

            def _mark_skipped(reason, original, translated):
                nonlocal skipped_corrupt
                skipped_corrupt += 1
                if reason in skipped_reason_counts:
                    skipped_reason_counts[reason] += 1
                if len(skipped_samples) < 200:
                    sample = {'reason': reason, 'original': original, 'translated': translated}
                    if reason == 'duplicate_key_conflict' and original in mapping:
                        sample['existing_translation'] = mapping[original]
                        sample['sources'] = mapping_sources.get(original, [])
                    skipped_samples.append(sample)

            def _try_add_mapping(original, translated, source_file=None, line_num=None):
                orig = (original or '').strip()
                trans = (translated or '').strip()
                if not orig or not trans or orig == trans:
                    return
                if TRANSLATION_ID_KEY_RE.fullmatch(orig):
                    return
                reason = self._classify_translation_corruption(orig, trans)
                if reason is not None:
                    _mark_skipped(reason, orig, trans)
                    self.logger.debug("strings.json: Skipping %s in translation of: %s", reason, orig[:40])
                    return
                if orig in mapping:
                    if mapping[orig] != trans:
                        _mark_skipped('duplicate_key_conflict', orig, trans)
                        self.logger.debug("strings.json: Duplicate key conflict: %s", orig[:40])
                    return
                lower_orig = orig.lower()
                if lower_orig in lower_to_orig:
                    has_ci_conflict = False
                    for other_orig in lower_to_orig[lower_orig]:
                        if mapping[other_orig] != trans:
                            has_ci_conflict = True
                            break
                    if has_ci_conflict:
                        _mark_skipped('case_insensitive_conflict', orig, trans)
                    if orig not in lower_to_orig[lower_orig]:
                        lower_to_orig[lower_orig].append(orig)
                else:
                    lower_to_orig[lower_orig] = [orig]
                mapping[orig] = trans
                if source_file:
                    if orig not in mapping_sources:
                        mapping_sources[orig] = []
                    mapping_sources[orig].append({'file': source_file, 'line': line_num})

            for tfile in tl_files:
                for entry in tfile.entries:
                    if entry.original_text and entry.translated_text:
                        _try_add_mapping(
                            entry.original_text, entry.translated_text,
                            source_file=os.path.basename(tfile.file_path), line_num=entry.line_number
                        )

            if extra_translations:
                for orig, trans in extra_translations.items():
                    _try_add_mapping(orig, trans)

            try:
                from src.core.syntax_guard import split_angle_pipe_groups, split_delimited_text
                _seg_additions = {}
                _seg_count = 0
                for m_orig, m_trans in list(mapping.items()):
                    orig_split = split_angle_pipe_groups(m_orig)
                    if orig_split is not None:
                        trans_split = split_angle_pipe_groups(m_trans)
                        if trans_split is not None:
                            _, orig_groups = orig_split
                            _, trans_groups = trans_split
                            for g_idx in range(min(len(orig_groups), len(trans_groups))):
                                o_segs = orig_groups[g_idx]
                                t_segs = trans_groups[g_idx]
                                for s_idx in range(min(len(o_segs), len(t_segs))):
                                    o_s = o_segs[s_idx].strip()
                                    t_s = t_segs[s_idx].strip()
                                    if o_s and t_s and o_s != t_s and o_s not in mapping and o_s not in _seg_additions:
                                        _seg_additions[o_s] = t_s
                                        _seg_count += 1
                        continue
                    if '|' not in m_orig:
                        continue
                    orig_delim = split_delimited_text(m_orig)
                    if orig_delim is None:
                        if '|' in m_orig and '|' in m_trans:
                            o_parts = m_orig.split('|')
                            t_parts = m_trans.split('|')
                            if (len(o_parts) >= 2 and len(o_parts) == len(t_parts) and len(o_parts) <= 6):
                                _pipe_valid = True
                                for _p in o_parts:
                                    if sum(1 for ch in _p.strip() if ch.isalpha()) < 2:
                                        _pipe_valid = False
                                        break
                                if _pipe_valid:
                                    for o_s, t_s in zip(o_parts, t_parts):
                                        o_s = o_s.strip()
                                        t_s = t_s.strip()
                                        if o_s and t_s and o_s != t_s and o_s not in mapping and o_s not in _seg_additions:
                                            _seg_additions[o_s] = t_s
                                            _seg_count += 1
                        continue
                    o_segs, _, _, _ = orig_delim
                    trans_delim = split_delimited_text(m_trans)
                    if trans_delim is not None:
                        t_segs, _, _, _ = trans_delim
                    elif '|' in m_trans:
                        t_segs = m_trans.split('|')
                    else:
                        continue
                    for s_idx in range(min(len(o_segs), len(t_segs))):
                        o_s = o_segs[s_idx].strip()
                        t_s = t_segs[s_idx].strip()
                        if o_s and t_s and o_s != t_s and o_s not in mapping and o_s not in _seg_additions:
                            _seg_additions[o_s] = t_s
                            _seg_count += 1
                if _seg_additions:
                    mapping.update(_seg_additions)
                    self.logger.info(f"strings.json: {_seg_count} individual segments extracted from delimiter groups")
            except Exception as e:
                self.logger.debug(f"strings.json segment splitting skipped: {e}")

            try:
                _RENPY_TAG_RE2 = re.compile(
                    r'\{/?(?:b|i|u|s|plain|color|font|size|cps|nw|fast|w|p|a|'
                    r'outlinecolor|alpha|k|rt|rb|image|space|vspace)(?:=[^}]*)?\}'
                )
                _tag_stripped_additions = {}
                _tag_strip_count = 0
                for m_orig, m_trans in list(mapping.items()):
                    if not _RENPY_TAG_RE2.search(m_orig):
                        continue
                    stripped_orig = _RENPY_TAG_RE2.sub('', m_orig).strip()
                    stripped_trans = _RENPY_TAG_RE2.sub('', m_trans).strip()
                    if (stripped_orig and stripped_trans and stripped_orig != stripped_trans
                            and len(stripped_orig) >= 2 and any(c.isalpha() for c in stripped_orig)
                            and stripped_orig not in mapping
                            and stripped_orig not in _tag_stripped_additions):
                        _tag_stripped_additions[stripped_orig] = stripped_trans
                        _tag_strip_count += 1
                if _tag_stripped_additions:
                    mapping.update(_tag_stripped_additions)
                    self.logger.info(f"strings.json: {_tag_strip_count} tag-stripped entries added for replace_text coverage")
            except Exception as e:
                self.logger.debug(f"strings.json tag-stripping skipped: {e}")

            for synth_fn, detail_name in [
                (self._synthesize_hotkey_visible_variants, 'visible_hotkey_variant'),
                (self._synthesize_angle_wrapper_variants, 'angle_wrapper_variant'),
                (self._synthesize_visible_text_variants, 'visible_text_variant'),
                (self._synthesize_visible_fragment_variants, 'visible_fragment_variant'),
            ]:
                try:
                    additions = synth_fn(mapping)
                    if additions:
                        for key, value in additions.items():
                            if key in mapping:
                                continue
                            mapping[key] = value
                            self._record_translation_guard_event(
                                category='recovered_by_synthesized_variant',
                                file_path='strings.json', translation_id=key,
                                original_text=key, translated_text=value,
                                detail=detail_name,
                            )
                            try:
                                self.diagnostic_report.mark_recovered(
                                    'strings.json', key, 'synthesized_variant',
                                    original_text=key, translated_text=value,
                                )
                            except Exception:
                                self.logger.debug("diagnostic mark_written failed during runtime coverage synthesis for key=%s", key)
                        self.logger.info(f"strings.json: {len(additions)} {detail_name} synthesized for runtime coverage")
                except Exception as e:
                    self.logger.debug(f"strings.json {detail_name} synthesis skipped: {e}")

            try:
                runtime_observed_additions = self._synthesize_runtime_observed_variants(mapping, lang_dir)
                if runtime_observed_additions:
                    for key, value in runtime_observed_additions.items():
                        if key in mapping:
                            continue
                        mapping[key] = value
                        self._record_translation_guard_event(
                            category='recovered_by_synthesized_variant',
                            file_path='strings.json', translation_id=key,
                            original_text=key, translated_text=value,
                            detail='runtime_observed_variant',
                        )
                        try:
                            self.diagnostic_report.mark_recovered(
                                'strings.json', key, 'synthesized_variant',
                                original_text=key, translated_text=value,
                            )
                        except Exception:
                            self.logger.debug("diagnostic mark_written failed during runtime-observed alias synthesis for key=%s", key)
                    self.logger.info(f"strings.json: {len(runtime_observed_additions)} runtime-observed aliases synthesized from missed-string diagnostics")
            except Exception as e:
                self.logger.debug(f"strings.json runtime-observed synthesis skipped: {e}")

            if skipped_corrupt > 0:
                self.logger.warning(f"strings.json: Skipped {skipped_corrupt} potentially corrupted translation(s)")
                reason_summary = ', '.join(f"{name}={count}" for name, count in skipped_reason_counts.items() if count > 0)
                if reason_summary:
                    self.logger.info(f"strings.json: Corruption reasons -> {reason_summary}")
                try:
                    diag_dir = os.path.join(lang_dir, 'diagnostics')
                    os.makedirs(diag_dir, exist_ok=True)
                    report_path = os.path.join(diag_dir, 'strings_json_skipped_corruptions.json')
                    save_text_safely(Path(report_path), json.dumps({
                        'generated_at': int(time.time()),
                        'total_skipped': skipped_corrupt,
                        'reason_counts': skipped_reason_counts,
                        'sample_limit': 100,
                        'samples': skipped_samples,
                    }, ensure_ascii=False, indent=2), encoding='utf-8')
                    self.logger.info(f"strings.json: Wrote skipped-corruption report -> {report_path}")
                except Exception as report_exc:
                    self.logger.debug(f"strings.json: Failed to write skipped-corruption report: {report_exc}")

            if mapping:
                json_path = os.path.join(lang_dir, "strings.json")
                try:
                    from src.core.exporter import _has_dynamic_variables
                    dynamic_entries = {k: v for k, v in mapping.items() if _has_dynamic_variables(k)}
                except Exception:
                    dynamic_entries = {}
                payload = {"translations": mapping, "dynamic": dynamic_entries}
                save_text_safely(Path(json_path), json.dumps(payload, ensure_ascii=False, indent=4), encoding='utf-8')
                dyn_msg = f" ({len(dynamic_entries)} dynamic)" if dynamic_entries else ""
                self.log_message.emit('info', self.config.get_log_text('log_strings_json_generated', count=len(mapping)) + dyn_msg)
                return len(mapping)
        except Exception as e:
            self.logger.warning(f"Failed to generate strings.json: {e}")

    # ---- legacy methods kept for backward compat ----

    def _execute_single_request_with_retry_mode(self, loop, translator, request):
        return execute_single_request_with_retry_mode(loop, translator, request)

    def _retry_unchanged_core_ui(self, loop, request, entry, current_text):
        return retry_unchanged_core_ui(loop, request, entry, current_text, self.translation_manager)
