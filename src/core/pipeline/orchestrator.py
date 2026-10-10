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
    BingTranslator,
)
from src.core.ai_translator import (
    OpenAITranslator,
    GeminiTranslator,
    LocalLLMTranslator,
    profile_prefers_single_segment as _profile_prefers_single_segment,
)
from src.core.output_formatter import RenPyOutputFormatter
from src.core.diagnostics import DiagnosticReport
from src.core.exceptions import EngineUnavailableError

from .base import PipelineStage, PipelineResult, PipelineWorker
from .constants import (
    RENPY_TO_API_LANG,
    TRANSLATION_ID_KEY_RE,
    DEEP_SCAN_VAR_ONLY_RE,
    DEEP_SCAN_MARKUP_STRIP_RE,
    LATIN_EXTENDED_CHAR_RE,
    STRING_PAIR_BLOCK_RE,
    DIALOGUE_PAIR_BLOCK_RE,
    is_rtl_language,
)
from .validating import (
    find_rpymc_files, extract_strings_from_rpymc_ast,
    has_rpy_files, has_rpyc_files, has_rpa_files,
    needs_re_extraction, normalize_tl_encodings,
    is_generated_export_file, is_runtime_hook_enabled as _is_hook_enabled,
    emit_scan_progress as _emit_scan,
    probe_directory_writable,
    has_game_script_files,
)
from .extraction import (
    run_extraction, cleanup_legacy_mod_files,
    make_source_translatable, escape_rpy_string,
    is_nontranslatable_identifier_entry,
    generate_all_strings_file, generate_native_tlid_content, merge_tl_content,
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
    is_sentence_shaped_natural_language,
    should_retry_unchanged,
    retry_unchanged_candidate,
    normalize_outer_color_wrapper,
    get_requested_translation_batch_size, get_effective_translation_batch_size,
    emit_batch_size_cap_notice_if_needed,
    execute_single_request_with_retry_mode,
    retry_unchanged_core_ui,
    protect_glossary_terms,
    get_extraction_mode as _extraction_mode,
    is_aggressive_extraction_mode as _is_aggressive,
)
from .saving import (
    generate_strings_json,
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

# py3langid speaks bare ISO 639-1; the translation APIs want these spellings.
_OFFLINE_LANG_TO_API = {"zh": "zh-CN"}

# Persist the translation cache after this many newly translated lines.
CACHE_CHECKPOINT_INTERVAL = 100


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
        self.is_tl_mode: bool = False
        self._deep_scan_completed_in_generating: bool = False
        self._translation_guard_events: List[Dict[str, Any]] = []
        self._translation_guard_counts: Dict[str, int] = {}
        self._translation_guard_sample_limit = 200

    # ---- Diagnostics helpers ----

    def _reset_translation_diagnostics(self) -> None:
        self.diagnostic_report = DiagnosticReport()
        self._last_diagnostic_path = None
        self._deep_scan_completed_in_generating = False
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

    def _should_retry_unchanged(self, original_text):
        return should_retry_unchanged(original_text)

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

    def _get_marked_texts(self):
        """Strings the author marked with _() in this game: from extraction,
        plus a scan of the game's .rpy files (TL mode has no extraction)."""
        marked = getattr(self, '_marked_texts', None)
        if marked is None:
            marked = self._marked_texts = set()
        if not getattr(self, '_marked_texts_scanned', False):
            self._marked_texts_scanned = True
            try:
                from src.core.marked_strings import collect_from_game_dir
                root = self.project_path or ''
                game_dir = root if os.path.basename(os.path.normpath(root)).lower() == 'game' else os.path.join(root, 'game')
                names = bool(getattr(self.config.translation_settings, 'translate_character_names', False))
                marked.update(collect_from_game_dir(game_dir, names))
            except Exception as exc:
                self.logger.debug(f"Marked-string scan failed: {exc}")
        return marked

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
        include_rpyc: bool = False,
        is_tl_mode: bool = False,
    ):
        """Pipeline ayarlarını yapılandır."""
        self.is_tl_mode = is_tl_mode
        self.include_deep_scan = include_deep_scan
        self.include_rpyc = include_rpyc
        from src.utils.path_manager import unwrap_mac_app
        game_exe_path = unwrap_mac_app(game_exe_path)  # Game.app → Contents/Resources/autorun
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
            if getattr(self, "is_tl_mode", False):
                result = self.translate_existing_tl(
                    tl_root_path=self.game_exe_path,
                    target_language=self.target_language,
                    source_language=self.source_language,
                    engine=self.engine,
                    use_proxy=self.use_proxy,
                )
            else:
                result = self._run_pipeline()
            self.finished.emit(result)
        except EngineUnavailableError as e:
            self.finished.emit(PipelineResult(
                success=False,
                message=e.message,
                stage=PipelineStage.ERROR,
                error=e.message,
            ))
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
        return cleanup_legacy_mod_files(game_dir, self.log_message.emit, self.config)

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

        if is_rtl_language(renpy_lang) or is_rtl_language(target_iso):
            self.log_message.emit(
                "info",
                "[RTL] Target language is Right-to-Left (RTL). Ensure a compatible font is installed or use Toolbox -> Font Injector if characters appear disconnected.",
            )

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

        if not probe_directory_writable(str(lang_dir)):
            return PipelineResult(
                success=False,
                message=self.config.get_ui_text(
                    "pipeline_game_folder_not_writable",
                    "The game folder is not writable: {path}. Move the game to a user folder "
                    "(e.g. Documents) or run RenLocalizer as administrator.",
                ).replace("{path}", str(lang_dir)),
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
        source_copies = 0
        for tl_file in tl_files:
            for e in tl_file.entries:
                if e.needs_translation():
                    all_entries.append(e)
                elif e.is_source_copy():
                    # Ren'Py SDK templates copy the source into the translation
                    # slot; treating that as "done" meant TL mode translated
                    # nothing on a freshly generated tl/<lang> folder.
                    e.translated_text = ""
                    all_entries.append(e)
                    source_copies += 1
        if source_copies:
            self.log_message.emit("info", self.config.get_log_text(
                'log_tl_source_copies',
                "{count} lines still contain the original text (Ren'Py template) and will be translated.",
                count=source_copies,
            ))

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

        if not translations and getattr(self, '_sent_for_translation', 1):
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

        if is_rtl_language(self.target_language):
            self.log_message.emit(
                "info",
                "[RTL] Target language is Right-to-Left (RTL). Ensure a compatible font is installed or use Toolbox -> Font Injector if characters appear disconnected.",
            )

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

        if not probe_directory_writable(game_dir):
            return PipelineResult(
                success=False,
                message=self.config.get_ui_text(
                    "pipeline_game_folder_not_writable",
                    "The game folder is not writable: {path}. Move the game to a user folder "
                    "(e.g. Documents) or run RenLocalizer as administrator.",
                ).replace("{path}", game_dir),
                stage=PipelineStage.ERROR
            )

        # Only the game's own scripts count: tl/, the bundled renpy/ engine and
        # our zzz_* files made archive-only games look "ready" (issue #20).
        has_rpy = has_game_script_files(game_dir, ('.rpy',))
        has_rpyc = has_game_script_files(game_dir, ('.rpyc',))
        has_rpa = self._has_rpa_files(game_dir)

        if has_rpa and not has_rpy and not has_rpyc and not self.auto_unren:
            return PipelineResult(
                success=False,
                message=self.config.get_ui_text(
                    "pipeline_rpa_extraction_disabled",
                    "The game's scripts are packed in .rpa archives, but archive extraction is "
                    "disabled. Enable automatic extraction (CLI: --extract-rpa) and run again.",
                ),
                stage=PipelineStage.ERROR,
            )

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

            has_rpy = has_game_script_files(game_dir, ('.rpy',))
            has_rpyc = has_game_script_files(game_dir, ('.rpyc',))

        if not has_rpy and not has_rpyc:
            # Nothing of the game itself to translate: carrying on would only
            # translate Ren'Py engine strings and report "100% translated".
            return PipelineResult(
                success=False,
                message=self.config.get_ui_text(
                    "pipeline_no_game_scripts",
                    "No game scripts (.rpy/.rpyc) were found in the game folder, so there is "
                    "nothing of the game to translate. If the game uses .rpa archives, check "
                    "that they could be extracted.",
                ),
                stage=PipelineStage.ERROR,
            )

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

        if getattr(self, 'include_deep_scan', False) and not getattr(self, '_deep_scan_completed_in_generating', False):
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
                # Native TLID mode intentionally writes no strings.json.
                if os.path.isfile(os.path.join(lang_dir, "strings.json")):
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

        if not translations and getattr(self, '_sent_for_translation', 1):
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
            # Native TLID mode intentionally writes no strings.json.
            if os.path.isfile(os.path.join(lang_dir, "strings.json")):
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
            for entries in scan_res.values():
                for e in entries:
                    txt = e.get('text')
                    if not txt or len(txt) <= 1:
                        continue
                    if txt in existing:
                        continue
                    _stripped = txt.strip()
                    if DEEP_SCAN_VAR_ONLY_RE.match(_stripped):
                        continue
                    _core = DEEP_SCAN_MARKUP_STRIP_RE.sub('', _stripped).strip()
                    if _core and not LATIN_EXTENDED_CHAR_RE.search(_core):
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
                    and not os.path.exists(os.path.splitext(p)[0] + '.rpy')
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

            self.log_message.emit("info", self.config.get_log_text('log_scanning_source_rpy'))
            parse_results = parser.extract_combined(
                game_dir,
                include_rpy=True,
                include_rpyc=use_rpyc,
                include_deep_scan=use_deep,
                recursive=True,
                exclude_dirs=['tl', 'cache', '__pycache__'],
                progress_callback=lambda current, total, file_path: self._emit_scan_progress(
                    self.config.get_log_text('log_source_scan_progress'), current, total, file_path, step=50),
            )
            source_texts = []
            for i, (file_path, entries) in enumerate(parse_results.items()):
                for entry in entries:
                    entry['file_path'] = str(file_path)
                    source_texts.append(entry)
                if i % 50 == 0:
                    time.sleep(0.001)
            self.log_message.emit("info", self.config.get_log_text('log_source_scan_completed', count=len(parse_results)))

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
                        if entry.get('marked'):
                            # Ren'Py's own _() strings ("{#weekday}Monday"): its
                            # template includes them, the filters below would not.
                            valid_entries.append(entry)
                            continue
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
                                if not entry.get('marked') and re.search(r'[\\#\[\](){}|*+^$]', txt):
                                    if re.search(r'\*\.\w+|\.\.\/|\\[a-z]', txt):
                                        continue
                                if not entry.get('marked') and re.search(r'[{}]', txt) and len(txt) > 10:
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

            if use_deep:
                self._deep_scan_completed_in_generating = True
            existing_texts = {e.get('text') for e in source_texts if e.get('text')}

            try:
                from src.utils.unrpyc_adapter import UnrpycAdapter
                from pathlib import Path
                adapter = UnrpycAdapter()
                if adapter.available:
                    _skip_dirs = {"tl", "renpy", "common", "cache", "__pycache__"}
                    orphaned_rpyc = []
                    for root, dirs, files in os.walk(game_dir):
                        dirs[:] = [d for d in dirs if d not in _skip_dirs]
                        for f in files:
                            fl = f.lower()
                            if fl.endswith(('.rpyc', '.rpymc')):
                                base_stem = f[:-5]
                                src_ext = '.rpym' if fl.endswith('.rpymc') else '.rpy'
                                src_path = os.path.join(root, base_stem + src_ext)
                                if not os.path.exists(src_path):
                                    orphaned_rpyc.append(Path(root) / f)

                    if orphaned_rpyc:
                        self.log_message.emit('info', self.config.get_log_text('log_orphaned_rpyc_found', count=len(orphaned_rpyc)))
                        with adapter.decompile_to_temp(orphaned_rpyc, Path(game_dir)) as (tmpdir, decompiled):
                            if decompiled:
                                self.log_message.emit('info', self.config.get_log_text('log_decompiled_parsing_extra', count=len(decompiled)))
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
                    else:
                        self.log_message.emit('debug', self.config.get_log_text('log_unrpyc_redundant_skipped'))
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
                    for root, dirs, files in os.walk(lang_tl_path):
                        for filename in files:
                            if not filename.lower().endswith('.rpy'):
                                continue
                            filepath = os.path.join(root, filename)
                            try:
                                with open(filepath, 'r', encoding='utf-8-sig', errors='replace') as f:
                                    content = f.read()
                                for match in STRING_PAIR_BLOCK_RE.finditer(content):
                                    old_text = match.group('old')
                                    if old_text:
                                        old_text = old_text.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace('\\\\', '\\')
                                        existing_global_strings.add(old_text)
                                for m2 in DIALOGUE_PAIR_BLOCK_RE.finditer(content):
                                    old_t = m2.group('old')
                                    if old_t:
                                        old_t = old_t.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace('\\\\', '\\')
                                        existing_global_strings.add(old_t)
                                self.logger.debug(f"Scanned {filepath}: found existing entries")
                            except Exception as fe:
                                self.logger.debug(f"Failed to scan {filepath}: {fe}")
                    if existing_global_strings:
                        self.log_message.emit("info", self.config.get_log_text('log_existing_tl_entries_skipped', count=len(existing_global_strings)))
            except Exception as e:
                self.logger.warning(f"Existing TL scan failed: {e}")

            # Remember what the author marked with _(): the tl lines written
            # below are translated later from the tl files, where that is lost.
            self._marked_texts = getattr(self, '_marked_texts', None) or set()
            self._marked_texts.update(e.get('text', '') for e in source_texts if e.get('marked'))

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
                    self.log_message.emit('info', f"Native TLID: {len(self._native_ui_entries)} UI entries reserved for native screen/dialogue translation.")

            file_groups = {}
            game_dir_abs = os.path.normpath(os.path.abspath(game_dir))
            game_dir_key = os.path.normcase(game_dir_abs)
            seen_texts = set(existing_global_strings)
            seen_dialogue_locs = set()

            for entry in source_texts:
                text = entry.get('text', '')
                if not text:
                    continue
                who = (entry.get('character') or '').strip()
                text_type = entry.get('text_type', '')
                is_dialogue = bool(who) or text_type in ('dialogue', 'narration', 'extend', 'bubble_dialogue', 'nvl_dialogue')

                if use_native and is_dialogue:
                    loc_key = (entry.get('file_path', ''), entry.get('line_number', 0), text)
                    if loc_key in seen_dialogue_locs:
                        continue
                    seen_dialogue_locs.add(loc_key)
                else:
                    if text in seen_texts:
                        continue
                    seen_texts.add(text)

                file_path = entry.get('file_path', '')
                try:
                    # Compare normalised paths: "C:/x/game" and "C:\\x\\game\\a.rpy"
                    # are the same folder; a substring test sent every script
                    # to external_libs.rpy when the two spellings differed.
                    abs_file = os.path.normpath(os.path.abspath(file_path)) if file_path else ''
                    if abs_file and os.path.normcase(abs_file).startswith(game_dir_key + os.sep):
                        rel_path = os.path.relpath(abs_file, game_dir_abs)
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

            if not file_groups:
                self.log_message.emit("info", "No new strings to generate for translation files.")
                return True

            self.log_message.emit("info", f"Generating {len(file_groups)} separate translation files for {renpy_lang}...")
            # Ren'Py keys `old "..."` globally, so one shared set must span every
            # generated file (seeded with what is already on disk). Native mode
            # can demote dialogue into string entries per file, which happens
            # after the dedup above — without this, the same shout line in two
            # scripts crashes the game on startup.
            shared_string_texts = set(existing_global_strings)
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
                            seen_string_texts=shared_string_texts,
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

                    if os.path.exists(full_path):
                        try:
                            with open(full_path, 'r', encoding='utf-8-sig', errors='replace') as ef:
                                existing_content = ef.read()
                            merged_content = merge_tl_content(existing_content, content, renpy_lang)
                            save_text_safely(Path(full_path), merged_content, encoding='utf-8-sig', newline='\n')
                        except Exception as _merge_err:
                            self.logger.warning(f"Merge failed for {rel_path}: {_merge_err}")
                            save_text_safely(Path(full_path), content, encoding='utf-8-sig', newline='\n')
                    else:
                        save_text_safely(Path(full_path), content, encoding='utf-8-sig', newline='\n')

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
        try:
            _engine_val = getattr(self.engine, 'value', str(self.engine))
            _model_val = getattr(getattr(self.config, 'api_keys', None), 'openai_model', '')
            self.diagnostic_report.set_provenance(engine=_engine_val, model=_model_val)
        except Exception:
            pass

        filtered_entries: List[TranslationEntry] = []
        for entry in entries:
            if self._is_nontranslatable_identifier_entry(entry):
                continue
            if (formatter._should_skip_translation(entry.original_text)
                    and entry.original_text not in self._get_marked_texts()):
                continue
            filtered_entries.append(entry)

        skipped = len(entries) - len(filtered_entries)
        if skipped:
            self.log_message.emit("debug", self.config.get_log_text('placeholder_excluded', count=skipped))

        entries = filtered_entries
        total = len(entries)
        # Lets callers tell "the engine returned nothing" from "every entry
        # was filtered as technical text, so nothing was sent".
        self._sent_for_translation = total

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
            _ai_batch_format = str(
                getattr(self.config.translation_settings, 'ai_batch_format', 'scene') or ''
            ).strip().lower()
            _single_mode = _ai_batch_format == 'single' or _profile_prefers_single_segment(self.config)
            if _single_mode:
                # Batch size is irrelevant here: every line is its own request.
                self.log_message.emit("info", self.config.get_log_text(
                    'log_ai_single_segment_mode',
                    'Single-segment mode: each line is sent as its own request (no batching, no neighbouring-line context).',
                ))
            else:
                self.log_message.emit("debug", f"AI engine detected, using batch size: {batch_size}")
            if not _single_mode and batch_size > 1000:
                self.log_message.emit("info", self.config.get_log_text(
                    'log_ai_batch_large_notice',
                    'Large AI batch size in use ({batch}). This may increase token usage, latency, or API failure risk.',
                    batch=batch_size,
                ))
        else:
            self._emit_batch_size_cap_notice_if_needed(requested_batch_size, batch_size)

        api_target_lang = RENPY_TO_API_LANG.get(self.target_language, self.target_language)
        api_source_lang = RENPY_TO_API_LANG.get(self.source_language, self.source_language)

        from src.utils.path_manager import translation_cache_file
        cache_file = translation_cache_file(self.config, self.project_path, self.game_exe_path, self.target_language)
        cache_dir = os.path.dirname(cache_file)
        if getattr(self.config.translation_settings, 'use_global_cache', True):
            self.log_message.emit("info", f"Using global data cache: [{os.path.basename(os.path.dirname(cache_dir))}]")
        else:
            self.log_message.emit("info", "Using local project-specific cache.")

        os.makedirs(cache_dir, exist_ok=True)
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

        # Unified Event Loop for detection and all translation requests
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        if self.source_language.lower() == "auto":
            self.log_message.emit("info", self.config.get_log_text('smart_detect_starting'))
            text_samples = [e.original_text for e in entries if getattr(e, 'original_text', None) and len(e.original_text.strip()) > 3]
            detected_lang = None

            # 1. Aşama: Çevrimdışı (offline) py3langid — yalnızca güven eşiği
            # aşılırsa kullanılır; yanlış kaynak dil tüm çalıştırmayı bozar.
            try:
                from src.utils.lang_detect import detect_source_language
                offline_lang = detect_source_language(text_samples)
                if offline_lang:
                    detected_lang = _OFFLINE_LANG_TO_API.get(offline_lang, offline_lang)
            except Exception as e:
                self.logger.debug(f"py3langid offline detection error: {e}")

            # 2. Aşama: Çevrimdışı tespit başarısızsa ve Google motoru seçiliyse online fallback
            if not detected_lang and self.engine == TranslationEngine.GOOGLE:
                try:
                    detection_translator = GoogleTranslator(config_manager=self.config)
                    detected_lang = loop.run_until_complete(
                        detection_translator.detect_language(text_samples, target_lang=api_target_lang)
                    )
                    loop.run_until_complete(detection_translator.close_session())
                except Exception as e:
                    self.logger.warning(f"Smart online language detection failed: {e}")

            if detected_lang:
                api_source_lang = detected_lang
                self.log_message.emit("info", self.config.get_log_text(
                    'smart_detect_success',
                    detected_lang=detected_lang.upper(),
                ))
            else:
                self.log_message.emit("warning", self.config.get_log_text('smart_detect_fallback'))
                api_source_lang = "auto"

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

        if self.engine == TranslationEngine.BING and self.engine not in self.translation_manager.translators:
            t = BingTranslator(
                proxy_manager=getattr(self.translation_manager, "proxy_manager", None),
                config_manager=self.config,
            )
            fallback = self.translation_manager.translators.get(TranslationEngine.GOOGLE)
            if fallback is None:
                fallback = GoogleTranslator(proxy_manager=getattr(self.translation_manager, "proxy_manager", None), config_manager=self.config)
                fallback.status_callback = self.log_message.emit
            t.set_fallback_translator(fallback)
            t.status_callback = self.log_message.emit
            self.translation_manager.add_translator(TranslationEngine.BING, t)

        # Fail fast instead of quietly translating everything with the Google
        # fallback when the selected AI server is down or the key is wrong.
        active_translator = self.translation_manager.translators.get(self.engine)
        if active_translator is not None and hasattr(active_translator, "probe_endpoint"):
            reason = None
            try:
                reason = loop.run_until_complete(active_translator.probe_endpoint())
            except Exception as probe_exc:
                self.logger.debug(f"Engine probe failed unexpectedly: {probe_exc}")
            if reason:
                message = self.config.get_log_text(
                    'log_engine_unreachable',
                    "The {engine} engine is not usable: {reason}. Nothing was translated — "
                    "check the URL/API key, or start Ollama / LM Studio / the built-in server first.",
                    engine=getattr(self.engine, 'value', str(self.engine)), reason=reason,
                )
                self.log_message.emit("error", message)
                try:
                    loop.run_until_complete(self.translation_manager.close_all())
                    loop.close()
                except Exception:
                    pass
                raise EngineUnavailableError(message)

        _auto_names_added = 0
        # AutoProtect adds names to the in-memory glossary for this run only;
        # remember the user's own glossary so the names are removed afterwards
        # instead of leaking into the next game (or into glossary.json on save).
        _glossary_before_autoprotect = getattr(self.config, 'glossary', None)
        if getattr(self.config.translation_settings, 'auto_protect_character_names', True):
            existing_glossary = dict(self.config.glossary) if hasattr(self.config, 'glossary') and self.config.glossary else {}
            existing_lower = {k.lower() for k in existing_glossary}
            from src.core.glossary_manager import COMMON_ENGLISH_STOPWORDS
            candidates: set = set()
            for entry in entries:
                candidates.add((getattr(entry, 'character', '') or '').strip())
            # Speaker variables ("e", "mc") are rarely the names players read;
            # the Character("Rose") display names are what appear in dialogue.
            # Only when names are not meant to be translated.
            if not getattr(self.config.translation_settings, 'translate_character_names', False):
                try:
                    from src.core.parser import collect_character_display_names
                    names_root = os.path.join(self.project_path or '', 'game')
                    if not os.path.isdir(names_root):
                        names_root = self.project_path or ''
                    candidates |= collect_character_display_names(names_root)
                except Exception as name_exc:
                    self.logger.debug(f"Character display-name scan failed: {name_exc}")
            char_names: set = set()
            for c in candidates:
                if (c and len(c) >= 3 and not c.startswith('[') and not c.startswith('{')
                        and not c.startswith('$') and c.lower() not in existing_lower
                        and c.lower() not in COMMON_ENGLISH_STOPWORDS and c[0].isupper()):
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

        # ── Fast-Path Pre-Pass: Instant O(1) Cache & TM Resolution ──
        pending_entries: List[TranslationEntry] = []
        cache_hit_count = 0

        for entry in entries:
            translation_id = getattr(entry, 'translation_id', '') or TLParser.make_translation_id(
                entry.file_path, entry.line_number, entry.original_text,
                getattr(entry, 'context_path', []), getattr(entry, 'raw_text', None)
            )

            # 1. External TM Check
            if _external_tm is not None:
                _tm_result = _external_tm.get_exact(entry.original_text)
                if _tm_result is not None:
                    translations[translation_id] = _tm_result
                    translations.setdefault(entry.original_text, _tm_result)
                    _tm_hit_count += 1
                    try:
                        if _tm_result != entry.original_text:
                            self.diagnostic_report.mark_translated(
                                entry.file_path, translation_id, _tm_result, original_text=entry.original_text
                            )
                        else:
                            self.diagnostic_report.mark_unchanged(
                                entry.file_path, translation_id, original_text=entry.original_text
                            )
                    except Exception:
                        pass
                    continue

            # 2. Already translated in current session (e.g. repeated string)
            if entry.original_text in translations:
                existing_tr = translations[entry.original_text]
                translations[translation_id] = existing_tr
                cache_hit_count += 1
                try:
                    if existing_tr != entry.original_text:
                        self.diagnostic_report.mark_translated(
                            entry.file_path, translation_id, existing_tr, original_text=entry.original_text
                        )
                    else:
                        self.diagnostic_report.mark_unchanged(
                            entry.file_path, translation_id, original_text=entry.original_text
                        )
                except Exception:
                    pass
                continue

            # 3. TranslationManager Fast-Path Cache Check
            cached_res = self.translation_manager.get_cached_translation(
                entry.original_text, api_source_lang, api_target_lang, self.engine
            )
            if cached_res and cached_res.success and cached_res.translated_text:
                cached_text = cached_res.translated_text
                # Apply glossary if configured
                if self.config and hasattr(self.config, 'glossary') and self.config.glossary:
                    cached_text = formatter.apply_glossary(
                        text=cached_text, glossary=self.config.glossary, original_text=entry.original_text
                    )
                # Normalize outer color wrapper
                cached_text = normalize_outer_color_wrapper(entry.original_text, cached_text)
                # Output integrity validation
                safe_text, blocked_reason = self._sanitize_translation_for_output(
                    original=entry.original_text,
                    translated=cached_text,
                    file_path=entry.file_path,
                    translation_id=translation_id,
                )
                if blocked_reason is None:
                    translations[translation_id] = safe_text
                    translations.setdefault(entry.original_text, safe_text)
                    cache_hit_count += 1
                    self.translation_manager.cache_hits += 1
                    try:
                        if safe_text != entry.original_text:
                            self.diagnostic_report.mark_translated(
                                entry.file_path, translation_id, safe_text, original_text=entry.original_text
                            )
                        else:
                            self.diagnostic_report.mark_unchanged(
                                entry.file_path, translation_id, original_text=entry.original_text
                            )
                    except Exception:
                        pass
                    continue

            # Unresolved -> needs actual translation engine call
            pending_entries.append(entry)

        if cache_hit_count > 0:
            self.log_message.emit("info", self.config.get_log_text(
                'log_cache_fast_path_hits',
                "[Cache] {hits}/{total} lines resolved instantly from cache.",
                hits=cache_hit_count, total=total,
            ))

        if not pending_entries:
            self.log_message.emit("success", self.config.get_log_text(
                'log_cache_fast_path_all',
                "All {total} lines resolved from cache; translation engine skipped.",
                total=total,
            ))
            self.progress_updated.emit(total, total, self.config.get_log_text(
                'progress_cache_all', "Resolved from cache",
            ))

        try:
            unchanged_count = 0
            failed_entries: List[str] = []
            sample_logs: List[str] = []
            stop_quota = False
            is_ai_engine = self.engine in (TranslationEngine.OPENAI, TranslationEngine.GEMINI, TranslationEngine.LOCAL_LLM)
            batch_entries = pending_entries
            pending_total = len(batch_entries)
            resolved_base = total - pending_total
            # Progress starts at resolved_base after the cache fast-path, so a
            # "current % 100" test would almost never hit; track the delta.
            last_checkpoint = resolved_base
            for i in range(0, pending_total, batch_size):
                if self.should_stop:
                    break

                batch = batch_entries[i:i + batch_size]
                current = resolved_base + min(i + batch_size, pending_total)
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
                                      'character': getattr(entry, 'character', None),
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
                                              'character': getattr(entry, 'character', None),
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
                                          'character': getattr(entry, 'character', None),
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
                                  'character': getattr(entry, 'character', None),
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
                                _tid = (
                                    (result.metadata.get('translation_id') if isinstance(result.metadata, dict) else None)
                                    or (result_request.metadata.get('translation_id') if result_request and isinstance(result_request.metadata, dict) else None)
                                    or getattr(entry, 'translation_id', None)
                                    or result.original_text
                                )
                                _entry_results.append((_tid, restored, entry, True, None, result_request))
                            else:
                                _tid = (
                                    (result.metadata.get('translation_id') if isinstance(result.metadata, dict) else None)
                                    or (result_request.metadata.get('translation_id') if result_request and isinstance(result_request.metadata, dict) else None)
                                    or getattr(entry, 'translation_id', None)
                                    or result.original_text
                                )
                                _entry_results.append((_tid, None, entry, False, result.error or "empty", result_request))
                        else:
                            _entry_results.append(("", None, entry, False, "missing_result", None))

                for tid, restored, entry, success, error, request in _entry_results:
                    if success and restored is not None:
                        retry_recovered = False
                        blocked_reason = None
                        raw_before_norm = restored
                        restored = normalize_outer_color_wrapper(entry.original_text, restored)
                        was_normalized = (restored != raw_before_norm)

                        _orig_clean = (entry.original_text or '').strip()
                        _rest_clean = (restored or '').strip()
                        _rest_unquoted = _rest_clean.strip('"`\'“”')
                        is_exact_unchanged = (_rest_clean == _orig_clean)
                        is_case_or_quote_unchanged = (
                            bool(_orig_clean)
                            and _rest_unquoted.lower() == _orig_clean.lower()
                            and self._should_retry_unchanged_core_ui(_orig_clean)
                        )
                        is_unchanged = is_exact_unchanged or is_case_or_quote_unchanged
                        should_retry, retry_kind = self._should_retry_unchanged(entry.original_text) if is_unchanged else (False, '')
                        if is_unchanged and should_retry:
                            restored, retry_recovered = retry_unchanged_candidate(
                                loop, request, entry, restored, self.translation_manager, retry_kind=retry_kind
                            )
                            norm_retry = normalize_outer_color_wrapper(entry.original_text, restored)
                            if norm_retry != restored:
                                was_normalized = True
                                restored = norm_retry
                            if retry_recovered and self.config and hasattr(self.config, 'glossary') and self.config.glossary:
                                restored = formatter.apply_glossary(
                                    text=restored, glossary=self.config.glossary, original_text=entry.original_text,
                                )
                            elif is_case_or_quote_unchanged and not retry_recovered:
                                # When a core UI string was returned unchanged (e.g. lowercase 'return' or quoted),
                                # and retry didn't produce a new translation, keep exact original capitalization.
                                restored = _orig_clean

                        restored, blocked_reason = self._sanitize_translation_for_output(
                            original=entry.original_text, translated=restored,
                            file_path=entry.file_path, translation_id=tid, line_number=entry.line_number,
                        )
                        cache_key = (
                            self.translation_manager._cache_key_for(request)
                            if request is not None
                            else (getattr(self.engine, 'value', str(self.engine)), api_source_lang, api_target_lang, entry.original_text)
                        )
                        if blocked_reason is not None:
                            guard_reason_text = self._get_guard_reason_text(blocked_reason)
                            self.log_message.emit("guard", self.config.get_log_text(
                                'log_guard_reverted_translation',
                                'Guard kept original text after suspicious translator output ({reason}) in {path}:{line}',
                                reason=guard_reason_text, path=entry.file_path, line=entry.line_number,
                            ))
                            # Evict corrupted output from cache so it never poisons persistent storage
                            try:
                                loop.run_until_complete(self.translation_manager.cache_remove(cache_key))
                            except Exception:
                                pass
                        elif was_normalized or retry_recovered:
                            # Update cache entry with cleaned or normalized translation
                            try:
                                loop.run_until_complete(self.translation_manager.cache_update_text(cache_key, restored))
                            except Exception:
                                pass

                        if restored:
                            translations[tid] = restored
                            translations.setdefault(entry.original_text, restored)
                            try:
                                file_path = entry.file_path
                                if blocked_reason is not None:
                                    pass
                                else:
                                    if was_normalized:
                                        self.diagnostic_report.mark_normalized_wrapper(
                                            file_path, tid,
                                            original_text=entry.original_text,
                                            translated_text=raw_before_norm,
                                            normalized_text=restored,
                                        )
                                        self._record_translation_guard_event(
                                            category='normalized_wrapper', file_path=file_path, translation_id=tid,
                                            original_text=entry.original_text, translated_text=restored,
                                            detail='outer_color_wrapper', line_number=entry.line_number,
                                        )
                                    if retry_recovered:
                                        self.diagnostic_report.mark_translated(file_path, tid, restored, original_text=entry.original_text)
                                        self.diagnostic_report.mark_recovered(file_path, tid, 'retry', original_text=entry.original_text, translated_text=restored)
                                        self._record_translation_guard_event(
                                            category='recovered_by_retry', file_path=file_path, translation_id=tid,
                                            original_text=entry.original_text, translated_text=restored,
                                            detail=f'{retry_kind}_retry', line_number=entry.line_number,
                                        )
                                    elif restored == entry.original_text:
                                        unchanged_reason = f'unchanged_{retry_kind}' if retry_kind else 'unchanged_other'
                                        self.diagnostic_report.mark_unchanged(file_path, tid, original_text=entry.original_text, reason=unchanged_reason)
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
                        norm_tr_seg = normalize_outer_color_wrapper(orig_seg, tr_seg)
                        safe_seg, blocked_reason = self._sanitize_translation_for_output(
                            original=orig_seg, translated=norm_tr_seg, file_path='strings.json', translation_id=orig_seg,
                        )
                        if blocked_reason is not None or safe_seg == orig_seg:
                            continue
                        if orig_seg not in translations:
                            translations[orig_seg] = safe_seg
                            self._last_atomic_segments[orig_seg] = safe_seg
                            _seg_added += 1
                    if _seg_added:
                        self.emit_log("debug", f"[AtomicSegments] {_seg_added} individual segment translations registered from delimiter groups")

                if current - last_checkpoint >= CACHE_CHECKPOINT_INTERVAL:
                    last_checkpoint = current
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
            if _auto_names_added:
                _lock = getattr(self.config, '_lock', None)
                if _lock:
                    _lock.acquire()
                try:
                    self.config.glossary = _glossary_before_autoprotect
                finally:
                    if _lock:
                        _lock.release()
            try:
                self.translation_manager.save_cache(cache_file)
            except Exception as _fce:
                self.logger.debug(f"Finally cache save notice: {_fce}")
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

    # ---- _generate_strings_json delegation ----

    def _generate_strings_json(
        self,
        tl_files: List[TranslationFile],
        lang_dir: str,
        extra_translations: Optional[Dict[str, str]] = None,
    ) -> Optional[int]:
        """Tüm çevirileri strings.json dosyasına aktarır (delegated to saving.generate_strings_json)."""
        return generate_strings_json(
            tl_files=tl_files,
            lang_dir=lang_dir,
            extra_translations=extra_translations,
            is_aggressive=self._is_aggressive_extraction_mode(),
            record_guard_event=self._record_translation_guard_event,
            diagnostic_report=getattr(self, 'diagnostic_report', None),
            log_emit=self.log_message.emit if hasattr(self, 'log_message') else None,
            config=getattr(self, 'config', None),
            logger_override=getattr(self, 'logger', None),
        )

    # ---- legacy methods kept for backward compat ----

    def _execute_single_request_with_retry_mode(self, loop, translator, request):
        return execute_single_request_with_retry_mode(loop, translator, request)

    def _retry_unchanged_core_ui(self, loop, request, entry, current_text):
        return retry_unchanged_core_ui(loop, request, entry, current_text, self.translation_manager)
