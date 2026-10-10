# -*- coding: utf-8 -*-
"""
AppBackend - RenLocalizer Python-QML Köprüsü
==================================================

RenLocalizer çeviri akışı için Python-QML köprü katmanı.
Google Translate ve AI motorları (OpenAI, DeepSeek, LocalLLM) ile
çeviri sürecini yönetir.
"""

import logging
import os
import sys
import threading
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, pyqtProperty, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import QSystemTrayIcon

from src.utils.config import ConfigManager
from src.version import VERSION
from src.core.translator import (
    TranslationManager,
    TranslationEngine,
    GoogleTranslator,
)
from src.core.ai_translator import (
    OpenAITranslator,
    DeepSeekTranslator,
    LocalLLMTranslator,
    GeminiTranslator,
)
from src.core.local_llm_server import (
    LlamaServerError,
    LlamaServerManager,
    cleanup_stale_server,
)
from src.core.proxy_manager import ProxyManager
from src.core.translation_pipeline import TranslationPipeline, PipelineWorker
from src.core.tl_parser import TLParser, get_translation_stats
from src.backend.settings_backend import SettingsBackend


def _normalize_path(raw: str) -> str:
    """QML file:// URI'sini veya ham yolu OS path'e dönüştür."""
    if not raw:
        return raw
    clean_raw = raw.strip('"')
    # Eğer girdi düz bir OS yolu ise (URL şeması içermiyorsa), doğrudan temizle ve dön
    if "://" not in clean_raw:
        return os.path.normpath(clean_raw)
    local = QUrl(clean_raw).toLocalFile()
    if local:
        return os.path.normpath(local)
    try:
        parsed = urllib.parse.urlparse(clean_raw)
        path_str = parsed.path
        if sys.platform == "win32" and path_str.startswith("/"):
            path_str = path_str[1:]
        return os.path.normpath(urllib.parse.unquote(path_str))
    except Exception:
        return os.path.normpath(urllib.parse.unquote(clean_raw))


class AppBackend(QObject):
    """
    RenLocalizer — Python-QML köprüsü.

    Google Translate ve AI motorları (OpenAI, DeepSeek, LocalLLM) ile çeviri akışını yönetir.
    """

    # ── Signals (QML tarafından dinlenir) ────────────────────────────────
    logMessage = pyqtSignal(str, str, arguments=["level", "message"])
    progressChanged = pyqtSignal(int, int, str, arguments=["current", "total", "text"])
    stageChanged = pyqtSignal(str, str, arguments=["stage", "displayName"])
    translationStarted = pyqtSignal()
    translationFinished = pyqtSignal(bool, str, arguments=["success", "message"])
    # Internal: worker thread -> GUI thread hand-off after llama-server start.
    _builtinServerPrepared = pyqtSignal(bool, str)
    statsReady = pyqtSignal(
        int, int, int, arguments=["total", "translated", "untranslated"]
    )
    completionSummary = pyqtSignal(
        str,
        str,
        str,
        str,
        int,
        arguments=[
            "title",
            "message",
            "outputPath",
            "diagnosticPath",
            "reviewNoteCount",
        ],
    )
    warningMessage = pyqtSignal(str, str, arguments=["title", "message"])
    updateAvailable = pyqtSignal(
        str, str, str, arguments=["currentVersion", "latestVersion", "releaseUrl"]
    )
    updateCheckFinished = pyqtSignal(bool, str, arguments=["hasUpdate", "message"])
    glossaryChanged = pyqtSignal()
    # ── Settings Signals (QML Two-way bindings) ────────────────────────
    maxThreadsChanged = pyqtSignal()
    requestDelayChanged = pyqtSignal()
    maxBatchSizeChanged = pyqtSignal()
    multiEndpointChanged = pyqtSignal()
    lingvaFallbackChanged = pyqtSignal()
    aggressiveRetryChanged = pyqtSignal()
    useCacheChanged = pyqtSignal()
    uiTriggerChanged = pyqtSignal()
    languageChanged = pyqtSignal(str)
    themeChanged = pyqtSignal(str)
    enableRpycReaderChanged = pyqtSignal()
    enableDeepScanChanged = pyqtSignal()
    activateLanguageOnLaunchChanged = pyqtSignal()
    enableStatefulLexerChanged = pyqtSignal()
    enableDesktopNotificationsChanged = pyqtSignal()
    checkForUpdatesOnStartupChanged = pyqtSignal()
    selectedEngineChanged = pyqtSignal(str)
    openaiApiKeyChanged = pyqtSignal()
    openaiModelChanged = pyqtSignal()
    openaiBaseUrlChanged = pyqtSignal()
    geminiApiKeyChanged = pyqtSignal()
    geminiModelChanged = pyqtSignal()
    geminiSafetySettingsChanged = pyqtSignal()
    localLlmUrlChanged = pyqtSignal()
    localLlmModelChanged = pyqtSignal()
    localLlmModeChanged = pyqtSignal()
    localLlmGgufPathChanged = pyqtSignal()
    localLlmServerPathChanged = pyqtSignal()
    localLlmBackendChanged = pyqtSignal()
    localLlmGpuLayersChanged = pyqtSignal()
    localLlmCtxSizeChanged = pyqtSignal()
    localServerStatusChanged = pyqtSignal()
    libretranslateUrlChanged = pyqtSignal()
    libretranslateApiKeyChanged = pyqtSignal()
    customEndpointUrlChanged = pyqtSignal()
    customEndpointApiKeyChanged = pyqtSignal()
    aiTemperatureChanged = pyqtSignal()
    aiTimeoutChanged = pyqtSignal()
    aiMaxTokensChanged = pyqtSignal()
    aiBatchSizeChanged = pyqtSignal()
    aiRetryCountChanged = pyqtSignal()
    aiConcurrencyChanged = pyqtSignal()
    aiRequestDelayChanged = pyqtSignal()
    enableParallelBatchChanged = pyqtSignal()
    aiCustomSystemPromptChanged = pyqtSignal()
    aiModelProfileChanged = pyqtSignal()
    hyMt2StatusChanged = pyqtSignal()
    aiBatchFormatChanged = pyqtSignal()
    aiSceneBatchSizeChanged = pyqtSignal()
    outputModeChanged = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self._version = VERSION

        # ── ConfigManager ────────────────────────────────────────────────
        self.config = ConfigManager()

        # ── Migration to 2.8.6 ───────────────────────────────────────────
        # Reset previously forced-false settings to True once.
        migration_marker = Path(self.config.data_dir) / ".migrated_286"
        if not migration_marker.exists():
            self.config.translation_settings.enable_rpyc_reader = True
            self.config.translation_settings.enable_deep_scan = True
            try:
                self.config.save_config()
                migration_marker.touch()
            except Exception as e:
                self.logger.warning(f"Could not write migration marker: {e}")

        # Gerekmeyen ağır özellikleri kapat (hız + bellek tasarrufu)
        self.config.translation_settings.enable_deep_extraction = False
        self.config.translation_settings.enable_unrpyc_decompile = False
        # ── State ────────────────────────────────────────────────────────
        self._project_path: str = self.config.app_settings.last_input_directory or ""
        self._target_language: str = (
            self.config.translation_settings.target_language or "turkish"
        )
        self._is_translating: bool = False
        self._preparing_builtin_server: bool = False
        self._ui_trigger: bool = False
        # TL retranslation mode (Ren'Py SDK-generated tl/ directory)
        self._tl_mode: bool = False
        self._tl_source_path: str = ""

        # ── Pipeline ─────────────────────────────────────────────────────
        self.pipeline: Optional[TranslationPipeline] = None
        self.pipeline_worker: Optional[PipelineWorker] = None

        # ── Translation Infrastructure ───────────────────────────────────
        self.proxy_manager = ProxyManager()
        self.proxy_manager.configure_from_settings(self.config.proxy_settings)

        self.translation_manager = TranslationManager(self.proxy_manager, self.config)
        # Owns the optional built-in llama-server child process (GGUF runner).
        self.llama_server = LlamaServerManager(log_callback=self.logMessage.emit)
        self._runtime_progress_pct: int = -1
        # A hard kill of a previous run never reached shutdown(); reclaim the
        # VRAM and port a surviving llama-server would still be holding.
        try:
            cleanup_stale_server()
        except Exception as exc:
            self.logger.debug(f"[AppBackend] stale llama-server cleanup skipped: {exc}")

        # ── SettingsBackend ───────────────────────────────────────────────
        self.settings = SettingsBackend(
            config=self.config,
            translation_manager=self.translation_manager,
            logger=self.logger,
            engine_getter=self._engine_from_str,
        )
        self._selected_engine = self.settings._selected_engine

        # Wire SettingsBackend callbacks → PyQt signals
        self.settings.on("max_threads", lambda: self.maxThreadsChanged.emit())
        self.settings.on("request_delay", lambda: self.requestDelayChanged.emit())
        self.settings.on("max_batch_size", lambda: self.maxBatchSizeChanged.emit())
        self.settings.on("multi_endpoint", lambda: self.multiEndpointChanged.emit())
        self.settings.on("lingva_fallback", lambda: self.lingvaFallbackChanged.emit())
        self.settings.on("aggressive_retry", lambda: self.aggressiveRetryChanged.emit())
        self.settings.on("use_cache", lambda: self.useCacheChanged.emit())
        self.settings.on("check_for_updates", lambda: self.refreshUI())
        self.settings.on("enable_desktop_notifications", lambda: self.enableDesktopNotificationsChanged.emit())
        self.settings.on("rpyc_reader", lambda: self.enableRpycReaderChanged.emit())
        self.settings.on("deep_scan", lambda: self.enableDeepScanChanged.emit())
        self.settings.on("activate_language_on_launch", lambda: self.activateLanguageOnLaunchChanged.emit())
        self.settings.on("stateful_lexer", lambda: self.enableStatefulLexerChanged.emit())
        self.settings.on("selected_engine", lambda engine_str: self.selectedEngineChanged.emit(engine_str))
        self.settings.on("openai_api_key", lambda: self.openaiApiKeyChanged.emit())
        self.settings.on("openai_model", lambda: self.openaiModelChanged.emit())
        self.settings.on("openai_base_url", lambda: self.openaiBaseUrlChanged.emit())
        self.settings.on("gemini_api_key", lambda: self.geminiApiKeyChanged.emit())
        self.settings.on("gemini_model", lambda: self.geminiModelChanged.emit())
        self.settings.on("gemini_safety_settings", lambda: self.geminiSafetySettingsChanged.emit())
        self.settings.on("local_llm_url", lambda: self.localLlmUrlChanged.emit())
        self.settings.on("local_llm_model", lambda: self.localLlmModelChanged.emit())
        self.settings.on("local_llm_model", lambda: self.hyMt2StatusChanged.emit())
        self.settings.on("local_llm_mode", lambda: self.localLlmModeChanged.emit())
        self.settings.on("local_llm_gguf_path", lambda: self.localLlmGgufPathChanged.emit())
        self.settings.on("local_llm_server_path", lambda: self.localLlmServerPathChanged.emit())
        self.settings.on("local_llm_backend", lambda: self.localLlmBackendChanged.emit())
        self.settings.on("local_llm_gpu_layers", lambda: self.localLlmGpuLayersChanged.emit())
        self.settings.on("local_llm_ctx_size", lambda: self.localLlmCtxSizeChanged.emit())
        self.settings.on("libretranslate_url", lambda: self.libretranslateUrlChanged.emit())
        self.settings.on("libretranslate_api_key", lambda: self.libretranslateApiKeyChanged.emit())
        self.settings.on("custom_endpoint_url", lambda: self.customEndpointUrlChanged.emit())
        self.settings.on("custom_endpoint_api_key", lambda: self.customEndpointApiKeyChanged.emit())
        self.settings.on("ai_temperature", lambda: self.aiTemperatureChanged.emit())
        self.settings.on("ai_timeout", lambda: self.aiTimeoutChanged.emit())
        self.settings.on("ai_max_tokens", lambda: self.aiMaxTokensChanged.emit())
        self.settings.on("ai_batch_size", lambda: self.aiBatchSizeChanged.emit())
        self.settings.on("ai_retry_count", lambda: self.aiRetryCountChanged.emit())
        self.settings.on("ai_concurrency", lambda: self.aiConcurrencyChanged.emit())
        self.settings.on("ai_request_delay", lambda: self.aiRequestDelayChanged.emit())
        self.settings.on("enable_parallel_batch", lambda: self.enableParallelBatchChanged.emit())
        self.settings.on("ai_custom_system_prompt", lambda: self.aiCustomSystemPromptChanged.emit())
        self.settings.on("ai_model_profile", lambda: self.aiModelProfileChanged.emit())
        self.settings.on("ai_model_profile", lambda: self.hyMt2StatusChanged.emit())
        self.settings.on("ai_batch_format", lambda: self.aiBatchFormatChanged.emit())
        self.settings.on("ai_scene_batch_size", lambda: self.aiSceneBatchSizeChanged.emit())
        self.settings.on("output_mode", lambda: self.outputModeChanged.emit())
        self.settings.on("language", lambda lang_code: self.languageChanged.emit(lang_code))
        self.settings.on("theme", lambda theme: self.themeChanged.emit(theme))
        self.settings.on("glossary", lambda: self.glossaryChanged.emit())
        self._builtinServerPrepared.connect(self._on_builtin_server_prepared)

        # Google translator'ı her zaman hazırla (fallback)
        threading.Thread(target=self._setup_google_translator, daemon=True).start()
        # Seçili motora göre diğer translator'ları kur
        self._setup_selected_engine_async(self._selected_engine)

        # ── System Tray & Desktop Notifications ──────────────────────────
        self._tray_icon: Optional[QSystemTrayIcon] = None
        self._init_system_tray()

    # ── Private setup ────────────────────────────────────────────────────

    def _setup_google_translator(self) -> None:
        """Google Translate motorunu kurar."""
        try:
            google = GoogleTranslator(
                proxy_manager=self.proxy_manager,
                config_manager=self.config,
            )
            self._replace_translator(TranslationEngine.GOOGLE, google)
            self.logger.info("[AppBackend] Google Translate hazır.")
        except Exception as exc:
            self.logger.error("[AppBackend] Google Translate kurulamadı: %s", exc)

    def _setup_libretranslate(self) -> None:
        """LibreTranslate motorunu kurar (kullanıcı tanımlı URL veya localhost:5000)."""
        try:
            from src.core.translator import LibreTranslateTranslator

            base_url = getattr(
                self.config.translation_settings,
                "libretranslate_url",
                "http://localhost:5000",
            )
            api_key = getattr(
                self.config.translation_settings, "libretranslate_api_key", ""
            )
            lt = LibreTranslateTranslator(
                base_url=base_url,
                api_key=api_key,
                proxy_manager=self.proxy_manager,
                config_manager=self.config,
            )
            self._replace_translator(TranslationEngine.LIBRETRANSLATE, lt)
            self.logger.info(f"[AppBackend] LibreTranslate hazır: {base_url}")
        except Exception as exc:
            self.logger.error("[AppBackend] LibreTranslate kurulamadı: %s", exc)

    def _setup_custom_endpoint(self) -> None:
        """Custom HTTP endpoint translator — herhangi bir çeviri API'sine uyumlu."""
        try:
            from src.core.translator import LibreTranslateTranslator

            base_url = getattr(
                self.config.translation_settings, "custom_endpoint_url", ""
            )
            if not base_url:
                self.logger.warning(
                    "[AppBackend] Custom endpoint URL boş, Google fallback kullanılacak."
                )
                return
            api_key = getattr(
                self.config.translation_settings, "custom_endpoint_api_key", ""
            )
            ct = LibreTranslateTranslator(
                base_url=base_url,
                api_key=api_key,
                proxy_manager=self.proxy_manager,
                config_manager=self.config,
            )
            self._replace_translator(TranslationEngine.CUSTOM, ct)
            self.logger.info(f"[AppBackend] Custom endpoint hazır: {base_url}")
        except Exception as exc:
            self.logger.error("[AppBackend] Custom endpoint kurulamadı: %s", exc)

    def _setup_bing_translator(self) -> None:
        """Bing / Microsoft Edge (anahtarsız) motorunu kurar; Google fallback bağlanır."""
        try:
            from src.core.translator import BingTranslator

            bt = BingTranslator(
                proxy_manager=self.proxy_manager,
                config_manager=self.config,
            )
            fallback = self.translation_manager.translators.get(TranslationEngine.GOOGLE)
            if fallback is None:
                fallback = GoogleTranslator(
                    proxy_manager=self.proxy_manager,
                    config_manager=self.config,
                )
            bt.set_fallback_translator(fallback)
            self._replace_translator(TranslationEngine.BING, bt)
            self.logger.info("[AppBackend] Bing (Microsoft Edge) translator hazır.")
        except Exception as exc:
            self.logger.error("[AppBackend] Bing translator kurulamadı: %s", exc)

    @staticmethod
    def _engine_from_str(engine_str: str) -> TranslationEngine:
        """Safely converts a string engine name to TranslationEngine enum."""
        mapping = {
            "google": TranslationEngine.GOOGLE,
            "openai": TranslationEngine.OPENAI,
            "local_llm": TranslationEngine.LOCAL_LLM,
            "deepseek": TranslationEngine.OPENAI,  # DeepSeek routed via OPENAI enum
            "gemini": TranslationEngine.GEMINI,
            "libretranslate": TranslationEngine.LIBRETRANSLATE,
            "bing": TranslationEngine.BING,
            "custom": TranslationEngine.CUSTOM,
        }
        return mapping.get(engine_str.lower(), TranslationEngine.GOOGLE)

    def _replace_translator(self, engine: TranslationEngine, translator) -> None:
        """Register *translator*, best-effort closing the instance it replaces."""
        previous = self.translation_manager.translators.get(engine)
        if previous is not None and previous is not translator and hasattr(previous, "close"):
            try:
                import asyncio
                try:
                    running_loop = asyncio.get_running_loop()
                except RuntimeError:
                    running_loop = None

                if running_loop is not None and running_loop.is_running():
                    running_loop.create_task(previous.close())
                else:
                    temp_loop = asyncio.new_event_loop()
                    try:
                        temp_loop.run_until_complete(previous.close())
                    finally:
                        temp_loop.close()
            except Exception:
                pass  # Old instance will be GC'd; never block translation on this
        self.translation_manager.add_translator(engine, translator)

    def _refresh_active_translator(self) -> None:
        """Rebuild the active engine's translator from the CURRENT config.

        Synchronous on purpose: constructors perform no network I/O, and a
        background setup thread could race the pipeline startup.
        """
        engine = self._selected_engine
        try:
            if engine in (
                TranslationEngine.OPENAI,
                TranslationEngine.LOCAL_LLM,
                TranslationEngine.GEMINI,
            ):
                self._setup_ai_translator(engine)
            elif engine == TranslationEngine.LIBRETRANSLATE:
                self._setup_libretranslate()
            elif engine == TranslationEngine.BING:
                self._setup_bing_translator()
            elif engine == TranslationEngine.CUSTOM:
                self._setup_custom_endpoint()
        except Exception as exc:
            self.logger.warning(f"[AppBackend] Translator refresh failed: {exc}")

    def _is_builtin_local_llm(self, engine: Optional[TranslationEngine] = None) -> bool:
        engine = engine or self._selected_engine
        return (
            engine == TranslationEngine.LOCAL_LLM
            and getattr(self.config.translation_settings, "local_llm_mode", "external") == "builtin"
        )

    def _setup_selected_engine_async(self, engine: TranslationEngine) -> None:
        """Pre-build *engine*'s translator in the background, outside a run.

        Translation start always calls _refresh_active_translator(), so this is
        only a warm-up. It must not run during a translation: _replace_translator
        closes the previous instance — the one the running pipeline is using —
        from another thread and event loop.
        """
        if engine == TranslationEngine.GOOGLE:
            return
        if self._is_translating:
            self.logMessage.emit("info", self._t(
                "log_engine_change_next_run",
                "Engine settings saved; they will apply to the next translation run.",
            ))
            return
        if self._is_builtin_local_llm(engine):
            # Loading a GGUF into VRAM is deferred until a translation starts
            # (or the user presses "Start server"), not done on every launch.
            return
        if engine in (TranslationEngine.OPENAI, TranslationEngine.LOCAL_LLM, TranslationEngine.GEMINI):
            target, args = self._setup_ai_translator, (engine,)
        elif engine == TranslationEngine.LIBRETRANSLATE:
            target, args = self._setup_libretranslate, ()
        elif engine == TranslationEngine.BING:
            target, args = self._setup_bing_translator, ()
        elif engine == TranslationEngine.CUSTOM:
            target, args = self._setup_custom_endpoint, ()
        else:
            return
        threading.Thread(target=target, args=args, daemon=True).start()

    def _setup_ai_translator(self, engine: Optional[TranslationEngine] = None) -> None:
        """Builds and registers the selected AI translator in the translation manager."""
        if engine is None:
            engine = self._selected_engine
        try:
            api_key = self.config.api_keys.openai_api_key or ""
            if engine == TranslationEngine.OPENAI:
                # Check if this is DeepSeek (openai_base_url points to deepseek)
                base_url = (
                    getattr(self.config.translation_settings, "openai_base_url", "")
                    or ""
                )
                if "deepseek" in base_url.lower():
                    translator = DeepSeekTranslator(
                        api_key=api_key,
                        proxy_manager=self.proxy_manager,
                        config_manager=self.config,
                    )
                    self.logger.info("[AppBackend] DeepSeek translator hazır.")
                else:
                    translator = OpenAITranslator(
                        api_key=api_key,
                        proxy_manager=self.proxy_manager,
                        config_manager=self.config,
                    )
                    self.logger.info("[AppBackend] OpenAI translator hazır.")
            elif engine == TranslationEngine.LOCAL_LLM:
                # Built-in GGUF mode: run llama-server ourselves and translate
                # against it, so no Ollama / LM Studio install is needed.
                if getattr(self.config.translation_settings, "local_llm_mode", "external") == "builtin":
                    base_url = self._start_builtin_server()
                    translator = LocalLLMTranslator(
                        proxy_manager=self.proxy_manager,
                        config_manager=self.config,
                    )
                    translator._base_url = base_url
                    translator._client = None  # rebuilt lazily against the new URL
                else:
                    translator = LocalLLMTranslator(
                        proxy_manager=self.proxy_manager,
                        config_manager=self.config,
                    )
                self.logger.info("[AppBackend] Local LLM translator hazır.")
            elif engine == TranslationEngine.GEMINI:
                gemini_api_key = self.config.api_keys.gemini_api_key or ""
                translator = GeminiTranslator(
                    api_key=gemini_api_key,
                    proxy_manager=self.proxy_manager,
                    config_manager=self.config,
                )
                # Safety-blocked / quota-exhausted / placeholder-broken items are
                # delegated to Google Translate (same wiring the pipeline applies
                # when it constructs the Gemini translator itself).
                fallback = self.translation_manager.translators.get(TranslationEngine.GOOGLE)
                if fallback is None:
                    fallback = GoogleTranslator(
                        proxy_manager=self.proxy_manager,
                        config_manager=self.config,
                    )
                translator.set_fallback_translator(fallback)
                self.logger.info("[AppBackend] Gemini translator hazır.")
            else:
                return
            self._replace_translator(engine, translator)
        except ImportError as exc:
            self.logger.error("[AppBackend] AI paket eksik: %s", exc)
            self.logMessage.emit("error", str(exc))
        except Exception as exc:
            self.logger.error("[AppBackend] AI translator kurulamadı: %s", exc)

    # ── pyqtProperty ─────────────────────────────────────────────────────

    @pyqtProperty(str, constant=True)
    def version(self) -> str:
        return self._version

    @pyqtProperty(bool, notify=translationStarted)
    def isTranslating(self) -> bool:
        return self._is_translating

    @pyqtProperty(bool, notify=uiTriggerChanged)
    def uiTrigger(self) -> bool:
        return self._ui_trigger

    # ── Settings Properties (Two-way binding support) ──────────────────
    @pyqtProperty(int, notify=maxThreadsChanged)
    def maxConcurrentThreads(self) -> int:
        return self.settings.get_max_concurrent_threads()

    @maxConcurrentThreads.setter
    def maxConcurrentThreads(self, val: int) -> None:
        self.settings.set_max_concurrent_threads(val)

    @pyqtProperty(float, notify=requestDelayChanged)
    def requestDelay(self) -> float:
        return self.settings.get_request_delay()

    @requestDelay.setter
    def requestDelay(self, val: float) -> None:
        self.settings.set_request_delay(val)

    @pyqtProperty(int, notify=maxBatchSizeChanged)
    def maxBatchSize(self) -> int:
        return self.settings.get_max_batch_size()

    @maxBatchSize.setter
    def maxBatchSize(self, val: int) -> None:
        self.settings.set_max_batch_size(val)

    @pyqtProperty(bool, notify=multiEndpointChanged)
    def useMultiEndpoint(self) -> bool:
        return self.settings.get_use_multi_endpoint()

    @useMultiEndpoint.setter
    def useMultiEndpoint(self, val: bool) -> None:
        self.settings.set_use_multi_endpoint(val)

    @pyqtProperty(bool, notify=lingvaFallbackChanged)
    def enableLingvaFallback(self) -> bool:
        return self.settings.get_enable_lingva_fallback()

    @enableLingvaFallback.setter
    def enableLingvaFallback(self, val: bool) -> None:
        self.settings.set_enable_lingva_fallback(val)

    @pyqtProperty(bool, notify=aggressiveRetryChanged)
    def aggressiveRetry(self) -> bool:
        return self.settings.get_aggressive_retry()

    @aggressiveRetry.setter
    def aggressiveRetry(self, val: bool) -> None:
        self.settings.set_aggressive_retry(val)

    @pyqtProperty(bool, notify=useCacheChanged)
    def useCache(self) -> bool:
        return self.settings.get_use_cache()

    @useCache.setter
    def useCache(self, val: bool) -> None:
        self.settings.set_use_cache(val)

    @pyqtProperty(bool, notify=checkForUpdatesOnStartupChanged)
    def checkForUpdatesOnStartup(self) -> bool:
        return self.settings.get_check_for_updates()

    @checkForUpdatesOnStartup.setter
    def checkForUpdatesOnStartup(self, val: bool) -> None:
        self.settings.set_check_for_updates(val)
        self.refreshUI()

    @pyqtProperty(bool, notify=enableDesktopNotificationsChanged)
    def enableDesktopNotifications(self) -> bool:
        return self.settings.get_enable_desktop_notifications()

    @enableDesktopNotifications.setter
    def enableDesktopNotifications(self, val: bool) -> None:
        self.settings.set_enable_desktop_notifications(val)

    def _init_system_tray(self) -> None:
        """PyQt6 QSystemTrayIcon sistemini güvenle başlatır."""
        try:
            if QSystemTrayIcon.isSystemTrayAvailable():
                self._tray_icon = QSystemTrayIcon(self)
                root_dir = Path(__file__).resolve().parent.parent.parent
                icon_path = root_dir / "icon.png"
                if not icon_path.exists():
                    icon_path = root_dir / "icon.ico"
                if icon_path.exists():
                    self._tray_icon.setIcon(QIcon(str(icon_path)))
                self._tray_icon.show()
            else:
                self.logger.info("[AppBackend] QSystemTrayIcon is not available on this platform/environment.")
        except Exception as e:
            self.logger.warning(f"[AppBackend] Could not initialize QSystemTrayIcon: {e}")

    @pyqtSlot(str, str)
    @pyqtSlot(str, str, bool)
    def send_desktop_notification(
        self, title_key_or_text: str, message_key_or_text: str, is_error: bool = False
    ) -> None:
        """Kullanıcının aktif arayüz diline göre yerelleştirilmiş masaüstü bildirimi gönderir."""
        if not self.enableDesktopNotifications:
            return

        title = self._t(title_key_or_text, title_key_or_text)
        message = self._t(message_key_or_text, message_key_or_text)

        try:
            if self._tray_icon and QSystemTrayIcon.isSystemTrayAvailable():
                icon_type = (
                    QSystemTrayIcon.MessageIcon.Critical
                    if is_error
                    else QSystemTrayIcon.MessageIcon.Information
                )
                self._tray_icon.showMessage(title, message, icon_type, 5000)
            else:
                self.logger.info(f"[Desktop Notification] [{title}] {message}")
        except Exception as e:
            self.logger.warning(f"[AppBackend] Failed to send desktop notification: {e}")

    @pyqtProperty(bool, notify=enableRpycReaderChanged)
    def enableRpycReader(self) -> bool:
        return self.settings.get_enable_rpyc_reader()

    @enableRpycReader.setter
    def enableRpycReader(self, val: bool) -> None:
        self.settings.set_enable_rpyc_reader(val)

    @pyqtProperty(bool, notify=enableDeepScanChanged)
    def enableDeepScan(self) -> bool:
        return self.settings.get_enable_deep_scan()

    @enableDeepScan.setter
    def enableDeepScan(self, val: bool) -> None:
        self.settings.set_enable_deep_scan(val)

    @pyqtProperty(bool, notify=activateLanguageOnLaunchChanged)
    def activateLanguageOnLaunch(self) -> bool:
        return self.settings.get_activate_language_on_launch()

    @activateLanguageOnLaunch.setter
    def activateLanguageOnLaunch(self, val: bool) -> None:
        self.settings.set_activate_language_on_launch(val)

    @pyqtProperty(bool, notify=enableStatefulLexerChanged)
    def enableStatefulLexer(self) -> bool:
        return self.settings.get_enable_stateful_lexer()

    @enableStatefulLexer.setter
    def enableStatefulLexer(self, val: bool) -> None:
        self.settings.set_enable_stateful_lexer(val)

    # ── AI Engine Settings Properties ────────────────────────────────────

    @pyqtProperty(str, notify=selectedEngineChanged)
    def selectedEngine(self) -> str:
        return self.settings.get_selected_engine()

    @pyqtSlot(str)
    def setSelectedEngine(self, engine_str: str) -> None:
        """Changes the active translation engine and sets it up if needed."""
        clean_str = (engine_str or "google").lower()
        new_engine = self._engine_from_str(clean_str)
        self.settings.set_selected_engine(clean_str)
        self._selected_engine = new_engine
        # Setup new engine in background if not Google (Google always active as fallback)
        self._setup_selected_engine_async(new_engine)

    @pyqtProperty(str, notify=openaiApiKeyChanged)
    def openaiApiKey(self) -> str:
        return self.settings.get_openai_api_key()

    @openaiApiKey.setter
    def openaiApiKey(self, val: str) -> None:
        self.settings.set_openai_api_key(val)

    @pyqtProperty(str, notify=openaiModelChanged)
    def openaiModel(self) -> str:
        return self.settings.get_openai_model()

    @openaiModel.setter
    def openaiModel(self, val: str) -> None:
        self.settings.set_openai_model(val)

    @pyqtProperty(str, notify=openaiBaseUrlChanged)
    def openaiBaseUrl(self) -> str:
        return self.settings.get_openai_base_url()

    @openaiBaseUrl.setter
    def openaiBaseUrl(self, val: str) -> None:
        self.settings.set_openai_base_url(val)

    @pyqtProperty(str, notify=localLlmUrlChanged)
    def localLlmUrl(self) -> str:
        return self.settings.get_local_llm_url()

    @localLlmUrl.setter
    def localLlmUrl(self, val: str) -> None:
        self.settings.set_local_llm_url(val)

    @pyqtProperty(str, notify=localLlmModelChanged)
    def localLlmModel(self) -> str:
        return self.settings.get_local_llm_model()

    @localLlmModel.setter
    def localLlmModel(self, val: str) -> None:
        self.settings.set_local_llm_model(val)

    # ── Built-in GGUF runner (llama.cpp server) ──────────────────────────

    @pyqtProperty(str, notify=localLlmModeChanged)
    def localLlmMode(self) -> str:
        return self.settings.get_local_llm_mode()

    @localLlmMode.setter
    def localLlmMode(self, val: str) -> None:
        self.settings.set_local_llm_mode(val)

    @pyqtProperty(str, notify=localLlmGgufPathChanged)
    def localLlmGgufPath(self) -> str:
        return self.settings.get_local_llm_gguf_path()

    @localLlmGgufPath.setter
    def localLlmGgufPath(self, val: str) -> None:
        self.settings.set_local_llm_gguf_path(_normalize_path(val) or val)

    @pyqtProperty(str, notify=localLlmServerPathChanged)
    def localLlmServerPath(self) -> str:
        return self.settings.get_local_llm_server_path()

    @localLlmServerPath.setter
    def localLlmServerPath(self, val: str) -> None:
        self.settings.set_local_llm_server_path(_normalize_path(val) or val)

    @pyqtProperty(str, notify=localLlmBackendChanged)
    def localLlmBackend(self) -> str:
        return self.settings.get_local_llm_backend()

    @localLlmBackend.setter
    def localLlmBackend(self, val: str) -> None:
        self.settings.set_local_llm_backend(val)

    @pyqtProperty(int, notify=localLlmGpuLayersChanged)
    def localLlmGpuLayers(self) -> int:
        return self.settings.get_local_llm_gpu_layers()

    @localLlmGpuLayers.setter
    def localLlmGpuLayers(self, val: int) -> None:
        self.settings.set_local_llm_gpu_layers(val)

    @pyqtProperty(int, notify=localLlmCtxSizeChanged)
    def localLlmCtxSize(self) -> int:
        return self.settings.get_local_llm_ctx_size()

    @localLlmCtxSize.setter
    def localLlmCtxSize(self, val: int) -> None:
        self.settings.set_local_llm_ctx_size(val)

    @pyqtProperty(str, notify=localServerStatusChanged)
    def localServerStatus(self) -> str:
        """stopped | downloading | starting | ready | error"""
        return self.llama_server.status

    @pyqtProperty(str, notify=localServerStatusChanged)
    def localServerDetail(self) -> str:
        return self.llama_server.base_url or self.llama_server.last_error

    @pyqtProperty(bool, notify=localServerStatusChanged)
    def localRuntimeReady(self) -> bool:
        """True when a llama-server binary is available (own or downloaded)."""
        try:
            return self.llama_server.resolve_binary(
                self.settings.get_local_llm_server_path(),
                self.settings.get_local_llm_backend(),
            ) is not None
        except Exception:
            return False

    @pyqtSlot(result=str)
    def localRuntimeDownloadSize(self) -> str:
        """Human-readable size hint for the selected backend download."""
        from src.core.local_llm_server import resolve_asset_name

        name = resolve_asset_name(self.settings.get_local_llm_backend())
        return name or ""

    @pyqtSlot()
    def downloadLocalRuntime(self) -> None:
        """Downloads the pinned llama.cpp build (explicit user action)."""
        backend = self.settings.get_local_llm_backend()

        def _worker() -> None:
            self.localServerStatusChanged.emit()
            try:
                self.llama_server.download_runtime(backend, progress_cb=self._on_runtime_progress)
                self.logMessage.emit(
                    "success",
                    self._t("log_llama_runtime_ready", "llama.cpp runtime is ready."),
                )
            except LlamaServerError as exc:
                self.logMessage.emit("error", str(exc))
            except Exception as exc:
                self.logger.error("[AppBackend] llama.cpp runtime download failed: %s", exc)
                self.logMessage.emit("error", str(exc))
            finally:
                self._runtime_progress_pct = -1
                self.localServerStatusChanged.emit()

        threading.Thread(target=_worker, daemon=True).start()

    def _on_runtime_progress(self, downloaded: int, total: int) -> None:
        if total <= 0:
            return
        pct = int(downloaded * 100 / total)
        if pct >= getattr(self, "_runtime_progress_pct", -1) + 10:
            self._runtime_progress_pct = pct
            self.logMessage.emit("info", f"[llama.cpp] {pct}% ({downloaded // 1048576}/{total // 1048576} MB)")

    @pyqtSlot()
    def startLocalServer(self) -> None:
        """Starts the built-in server with the configured GGUF model."""
        if self._is_translating:
            # start() restarts the server when settings changed, which would
            # cut off the running translation's requests.
            self.logMessage.emit("warning", self._t(
                "log_local_server_busy",
                "Stop the running translation before restarting the local model server.",
            ))
            return

        def _worker() -> None:
            self.localServerStatusChanged.emit()
            try:
                self._start_builtin_server()
                # Rebuild the translator so it points at the new base URL.
                self._setup_ai_translator(TranslationEngine.LOCAL_LLM)
            except LlamaServerError as exc:
                self.logMessage.emit("error", str(exc))
            except Exception as exc:
                self.logger.error("[AppBackend] llama-server start failed: %s", exc)
                self.logMessage.emit("error", str(exc))
            finally:
                self.localServerStatusChanged.emit()

        threading.Thread(target=_worker, daemon=True).start()

    @pyqtSlot()
    def stopLocalServer(self) -> None:
        self.llama_server.stop()
        self.localServerStatusChanged.emit()

    def _start_builtin_server(self) -> str:
        """Starts (or reuses) the llama-server process; returns its base URL."""
        ts = self.config.translation_settings
        return self.llama_server.start(
            model_path=getattr(ts, "local_llm_gguf_path", ""),
            user_path=getattr(ts, "local_llm_server_path", ""),
            backend=getattr(ts, "local_llm_backend", "vulkan"),
            gpu_layers=getattr(ts, "local_llm_gpu_layers", -1),
            ctx_size=getattr(ts, "local_llm_ctx_size", 4096),
            parallel=max(1, int(getattr(ts, "ai_concurrency", 2) or 2)),
            port=getattr(ts, "local_llm_server_port", 0),
        )

    # ── AI Model Profile (Hy-MT2) Properties ──────────────────────────────

    @pyqtProperty(str, notify=aiModelProfileChanged)
    def aiModelProfile(self) -> str:
        return self.settings.get_ai_model_profile()

    @aiModelProfile.setter
    def aiModelProfile(self, val: str) -> None:
        self.settings.set_ai_model_profile(val)

    @pyqtProperty(bool, notify=hyMt2StatusChanged)
    def hyMt2Detected(self) -> bool:
        """True when the configured local LLM model name matches the Hy-MT family."""
        return self.settings.is_hy_mt2_model_detected()

    @pyqtProperty(bool, notify=hyMt2StatusChanged)
    def hyMt2Active(self) -> bool:
        """True when the Hy-MT2 profile is effectively in use (forced or detected)."""
        return self.settings.is_hy_mt2_active()

    # ── AI Batch Format & Scene Translation Mode Properties ───────────────

    @pyqtProperty(str, notify=aiBatchFormatChanged)
    def aiBatchFormat(self) -> str:
        return self.settings.get_ai_batch_format()

    @aiBatchFormat.setter
    def aiBatchFormat(self, val: str) -> None:
        self.settings.set_ai_batch_format(val)

    @pyqtProperty(int, notify=aiSceneBatchSizeChanged)
    def aiSceneBatchSize(self) -> int:
        return self.settings.get_ai_scene_batch_size()

    @aiSceneBatchSize.setter
    def aiSceneBatchSize(self, val: int) -> None:
        self.settings.set_ai_scene_batch_size(val)

    # Alias for QML convenience
    @pyqtProperty(int, notify=aiSceneBatchSizeChanged)
    def aiSceneSize(self) -> int:
        return self.settings.get_ai_scene_batch_size()

    @aiSceneSize.setter
    def aiSceneSize(self, val: int) -> None:
        self.settings.set_ai_scene_batch_size(val)

    # ── LibreTranslate Properties ─────────────────────────────────────────

    @pyqtProperty(str, notify=libretranslateUrlChanged)
    def libretranslateUrl(self) -> str:
        return self.settings.get_libretranslate_url()

    @libretranslateUrl.setter
    def libretranslateUrl(self, val: str) -> None:
        self.settings.set_libretranslate_url(val)

    @pyqtProperty(str, notify=libretranslateApiKeyChanged)
    def libretranslateApiKey(self) -> str:
        return self.settings.get_libretranslate_api_key()

    @libretranslateApiKey.setter
    def libretranslateApiKey(self, val: str) -> None:
        self.settings.set_libretranslate_api_key(val)

    # ── Custom Endpoint Properties ────────────────────────────────────────

    @pyqtProperty(str, notify=customEndpointUrlChanged)
    def customEndpointUrl(self) -> str:
        return self.settings.get_custom_endpoint_url()

    @customEndpointUrl.setter
    def customEndpointUrl(self, val: str) -> None:
        self.settings.set_custom_endpoint_url(val)

    @pyqtProperty(str, notify=customEndpointApiKeyChanged)
    def customEndpointApiKey(self) -> str:
        return self.settings.get_custom_endpoint_api_key()

    @customEndpointApiKey.setter
    def customEndpointApiKey(self, val: str) -> None:
        self.settings.set_custom_endpoint_api_key(val)

    # ── Gemini Properties ─────────────────────────────────────────────────

    @pyqtProperty(str, notify=geminiApiKeyChanged)
    def geminiApiKey(self) -> str:
        return self.settings.get_gemini_api_key()

    @geminiApiKey.setter
    def geminiApiKey(self, val: str) -> None:
        self.settings.set_gemini_api_key(val)

    @pyqtProperty(str, notify=geminiModelChanged)
    def geminiModel(self) -> str:
        return self.settings.get_gemini_model()

    @geminiModel.setter
    def geminiModel(self, val: str) -> None:
        self.settings.set_gemini_model(val)

    @pyqtProperty(str, notify=geminiSafetySettingsChanged)
    def geminiSafetySettings(self) -> str:
        return self.settings.get_gemini_safety_settings()

    @geminiSafetySettings.setter
    def geminiSafetySettings(self, val: str) -> None:
        self.settings.set_gemini_safety_settings(val)

    # ── Advanced AI Settings Properties ──────────────────────────────────

    @pyqtProperty(float, notify=aiTemperatureChanged)
    def aiTemperature(self) -> float:
        return self.settings.get_ai_temperature()

    @aiTemperature.setter
    def aiTemperature(self, val: float) -> None:
        self.settings.set_ai_temperature(val)

    @pyqtProperty(int, notify=aiTimeoutChanged)
    def aiTimeout(self) -> int:
        return self.settings.get_ai_timeout()

    @aiTimeout.setter
    def aiTimeout(self, val: int) -> None:
        self.settings.set_ai_timeout(val)

    @pyqtProperty(int, notify=aiMaxTokensChanged)
    def aiMaxTokens(self) -> int:
        return self.settings.get_ai_max_tokens()

    @aiMaxTokens.setter
    def aiMaxTokens(self, val: int) -> None:
        self.settings.set_ai_max_tokens(val)

    @pyqtProperty(int, notify=aiBatchSizeChanged)
    def aiBatchSize(self) -> int:
        return self.settings.get_ai_batch_size()

    @aiBatchSize.setter
    def aiBatchSize(self, val: int) -> None:
        self.settings.set_ai_batch_size(val)

    @pyqtProperty(int, notify=aiRetryCountChanged)
    def aiRetryCount(self) -> int:
        return self.settings.get_ai_retry_count()

    @aiRetryCount.setter
    def aiRetryCount(self, val: int) -> None:
        self.settings.set_ai_retry_count(val)

    @pyqtProperty(int, notify=aiConcurrencyChanged)
    def aiConcurrency(self) -> int:
        return self.settings.get_ai_concurrency()

    @aiConcurrency.setter
    def aiConcurrency(self, val: int) -> None:
        self.settings.set_ai_concurrency(val)

    @pyqtProperty(float, notify=aiRequestDelayChanged)
    def aiRequestDelay(self) -> float:
        return self.settings.get_ai_request_delay()

    @aiRequestDelay.setter
    def aiRequestDelay(self, val: float) -> None:
        self.settings.set_ai_request_delay(val)

    @pyqtProperty(bool, notify=enableParallelBatchChanged)
    def enableParallelBatch(self) -> bool:
        return self.settings.get_enable_parallel_batch()

    @enableParallelBatch.setter
    def enableParallelBatch(self, val: bool) -> None:
        self.settings.set_enable_parallel_batch(val)

    @pyqtProperty(str, notify=aiCustomSystemPromptChanged)
    def aiCustomSystemPrompt(self) -> str:
        return self.settings.get_ai_custom_system_prompt()

    @aiCustomSystemPrompt.setter
    def aiCustomSystemPrompt(self, val: str) -> None:
        self.settings.set_ai_custom_system_prompt(val)

    # ── Output Mode Property ──────────────────────────────────────────────

    @pyqtProperty(str, notify=outputModeChanged)
    def outputMode(self) -> str:
        return self.settings.get_output_mode()

    @outputMode.setter
    def outputMode(self, val: str) -> None:
        self.settings.set_output_mode(val)

    # ── Utility Slots ────────────────────────────────────────────────────

    @pyqtSlot(str)
    def copyToClipboard(self, text: str) -> None:
        """Copies the given text to system clipboard."""
        from PyQt6.QtGui import QGuiApplication

        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(text)

    @pyqtSlot(str, result=str)
    def urlToPath(self, url: str) -> str:
        """QML file:// URL'sini OS path'e çevirir."""
        return _normalize_path(url)

    @pyqtSlot(str, result=bool)
    def openLocalPath(self, path: str) -> bool:
        """Yerel dosya veya klasörü masaüstü kabuğuyla açar."""
        if not path:
            return False
        local = _normalize_path(path)
        if not local:
            return False
        return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(local)))

    @pyqtSlot(result=str)
    def get_app_url(self) -> str:
        """Uygulamanın çalışma dizinini file:// URL olarak döndürür."""
        return QUrl.fromLocalFile(os.getcwd()).toString()

    @pyqtSlot(str, result=str)
    def get_asset_url(self, relative_path: str) -> str:
        """Asset'in tam dosya URL'sini döndürür (frozen bundle uyumlu)."""
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            base = Path(sys._MEIPASS)
        else:
            base = Path(os.getcwd())
        full = base / relative_path
        return QUrl.fromLocalFile(str(full)).toString()

    @pyqtSlot(result=bool)
    def clearTranslationCache(self) -> bool:
        """Seçili projenin yerel ve genel çeviri belleklerini (cache) temizler."""
        if not self._project_path:
            self.logMessage.emit(
                "warning",
                self._t("cache_no_project", "No project selected to clear cache."),
            )
            return False

        try:
            # 1. Clear memory cache in translation manager
            self.translation_manager._cache.clear()
            self.translation_manager.cache_hits = 0
            self.translation_manager.cache_misses = 0

            # Resolve actual project root directory and EXE path
            if os.path.isfile(self._project_path):
                project_dir = os.path.dirname(self._project_path)
                exe_path = self._project_path
            else:
                project_dir = self._project_path
                exe_path = None

            from src.utils.path_manager import get_project_id

            project_name = get_project_id(project_dir, exe_path)

            # 2. Local cache deletion: <project_path>/game/tl/<lang>/translation_cache.json
            if self._target_language:
                local_cache = os.path.join(
                    self._project_path,
                    "game",
                    "tl",
                    self._target_language,
                    "translation_cache.json",
                )
                if os.path.exists(local_cache):
                    try:
                        os.remove(local_cache)
                        self.logMessage.emit(
                            "info",
                            f"Local project cache removed: {os.path.basename(local_cache)}",
                        )
                    except Exception as ex:
                        self.logMessage.emit(
                            "warning", f"Could not remove local cache: {ex}"
                        )

            # 3. Global project cache deletion: <data_dir>/cache/<project_name>/
            base_cache_dir = os.path.join(
                self.config.data_dir,
                getattr(self.config.translation_settings, "cache_path", "cache"),
            )
            global_project_cache = os.path.join(base_cache_dir, project_name)

            if os.path.exists(global_project_cache):
                import shutil

                try:
                    shutil.rmtree(global_project_cache)
                    self.logMessage.emit(
                        "info", f"Global cache for project '{project_name}' removed."
                    )
                except Exception as ex:
                    self.logMessage.emit(
                        "warning", f"Could not remove global cache folder: {ex}"
                    )

            self.logMessage.emit(
                "info",
                self._t(
                    "log_cache_cleared",
                    "Translation memory (cache) cleared successfully.",
                ),
            )
            return True
        except Exception as e:
            self.logger.exception("Failed to clear translation cache")
            self.logMessage.emit("error", f"Failed to clear cache: {e}")
            return False

    @pyqtSlot()
    def refreshUI(self) -> None:
        """Arayüzü yeniler ve uiTrigger sinyali gönderir."""
        self._ui_trigger = not self._ui_trigger
        self.uiTriggerChanged.emit()

    @pyqtSlot(str, result=str)
    def getText(self, key: str) -> str:
        return self.config.get_ui_text(key, key)

    @pyqtSlot(str, str, result=str)
    def getTextWithDefault(self, key: str, default: str) -> str:
        return self.config.get_ui_text(key, default)

    def _t(self, key: str, default: str) -> str:
        """Internal helper — localized log/UI string. Falls back to English."""
        return self.config.get_ui_text(key, default)

    # ── UI Language Management ──
    @pyqtSlot(result=list)
    def getAvailableUILanguages(self) -> list:
        return self.settings.get_available_ui_languages()

    @pyqtSlot(result=str)
    def getCurrentUILanguage(self) -> str:
        return self.settings.get_current_ui_language()

    @pyqtSlot(str)
    def setUILanguage(self, lang_code: str) -> None:
        self.settings.set_ui_language(lang_code)
        self.refreshUI()

    # ── UI Theme Management ──
    @pyqtSlot(result=list)
    def getAvailableThemes(self) -> list:
        return self.settings.get_available_themes()

    @pyqtSlot(result=str)
    def getCurrentTheme(self) -> str:
        return self.settings.get_current_theme()

    @pyqtSlot(str)
    def setTheme(self, theme: str) -> None:
        self.settings.set_theme(theme)
        self.refreshUI()

    # ── Language Slots ───────────────────────────────────────────────────

    @pyqtSlot(result=list)
    def getTargetLanguages(self) -> list:
        return self.settings.get_target_languages()

    @pyqtSlot(result=str)
    def getTargetLanguage(self) -> str:
        return self.settings.get_target_language()

    @pyqtSlot(str)
    def setTargetLanguage(self, lang: str) -> None:
        self.settings.set_target_language(lang)
        self._target_language = self.config.normalize_renpy_language_code(lang)
        self.refreshUI()

    @pyqtSlot(result=list)
    def getSourceLanguages(self) -> list:
        return self.settings.get_source_languages()

    @pyqtSlot(result=str)
    def getSourceLanguage(self) -> str:
        return self.settings.get_source_language()

    @pyqtSlot(str)
    def setSourceLanguage(self, lang: str) -> None:
        self.settings.set_source_language(lang)
        self.refreshUI()

    # ── Project Slot ─────────────────────────────────────────────────────

    @pyqtSlot(str)
    def setProjectPath(self, path: str) -> None:
        """Oyun proje yolunu ayarlar ve Ren'Py projesi olup olmadığını doğrular."""
        path = _normalize_path(path)
        if not path:
            return

        # macOS Ren'Py app: the game lives in Game.app/Contents/Resources/autorun.
        from src.utils.path_manager import unwrap_mac_app
        app_root = unwrap_mac_app(path)
        if app_root != path:
            path = app_root
            self.logMessage.emit(
                "info",
                self._t("log_mac_app_bundle", "🍎 macOS app package detected — using {path}").format(path=path),
            )

        self._project_path = path
        self._tl_mode = False
        self._tl_source_path = ""
        self.config.app_settings.last_input_directory = path
        self.config.save_config()
        self.logMessage.emit("info", f"📁 Project path: {path}")

        # --- TL Retranslation mode detection ---
        # If the user selected a tl/ directory or a language subfolder inside tl/,
        # activate TL retranslation mode (fill empty translations in-place).
        norm = os.path.normpath(path)
        path_parts = norm.replace("\\", "/").split("/")
        is_tl_folder = (
            os.path.basename(norm).lower() == "tl"
            or (len(path_parts) >= 2 and path_parts[-2].lower() == "tl")
            or (
                os.path.isdir(path)
                and any(
                    f.lower().endswith(".rpy") for _, _, fs in os.walk(path) for f in fs
                )
                and not os.path.isdir(os.path.join(path, "game"))
                and "tl" in norm.lower().replace("\\", "/").split("/")
            )
        )

        if is_tl_folder and os.path.isdir(path):
            self._tl_mode = True
            self._tl_source_path = path
            self.logMessage.emit(
                "info",
                self._t(
                    "log_tl_folder_detected",
                    "🔄 TL folder detected — Retranslation mode active. Only empty translations will be filled, existing translations will be preserved.",
                ),
            )
            return

        # Ren'Py projesi doğrulama
        project_dir = os.path.dirname(path) if os.path.isfile(path) else path
        game_dir = os.path.join(project_dir, "game")
        if not os.path.isdir(game_dir):
            alt = os.path.join(project_dir, "Game")
            if os.path.isdir(alt):
                game_dir = alt

        if os.path.isdir(game_dir):
            self.logMessage.emit(
                "info",
                self._t("log_project_detected", "✅ Valid Ren'Py project detected."),
            )
        else:
            self.logMessage.emit(
                "warning",
                self._t(
                    "log_game_folder_missing",
                    "⚠️ game/ folder not found. Please select a valid Ren'Py project directory.",
                ),
            )

    @pyqtSlot(result=str)
    def getLastProjectPath(self) -> str:
        return self.config.app_settings.last_input_directory or ""

    # ── Translation Control Slots ────────────────────────────────────────

    @pyqtSlot()
    def startTranslation(self) -> None:
        """Çeviri pipeline'ını başlatır (normal veya TL retranslation modu)."""
        if not self._project_path:
            self.logMessage.emit(
                "error",
                self._t(
                    "log_select_game", "❌ Please select a game folder or EXE first."
                ),
            )
            return

        if self._is_translating:
            return

        self._is_translating = True
        self.translationStarted.emit()
        self._start_pipeline_translation()

    def _start_pipeline_translation(self, builtin_server_ready: bool = False) -> None:
        """Pipeline tabanlı çeviriyi başlatır (normal veya TL modu)."""
        if self._is_builtin_local_llm() and not builtin_server_ready:
            # Loading a GGUF can take a minute; doing it in the synchronous
            # refresh below froze the UI. Start (or reuse) the server on a
            # worker thread and come back here through a queued signal.
            self.logMessage.emit("info", self._t(
                "log_local_server_preparing",
                "Preparing the local model server before translation...",
            ))

            def _prepare() -> None:
                try:
                    self._start_builtin_server()
                    self._builtinServerPrepared.emit(True, "")
                except Exception as exc:
                    self.logger.error("[AppBackend] llama-server start failed: %s", exc)
                    self._builtinServerPrepared.emit(False, str(exc))

            self._preparing_builtin_server = True
            threading.Thread(target=_prepare, daemon=True).start()
            return

        try:
            # Rebuild the selected engine's translator from the CURRENT config.
            # Translator instances are created at app startup and cached in the
            # TranslationManager; without this refresh, settings edited in the
            # UI (model name, URL, concurrency, Hy-MT2 profile, ...) would not
            # apply until the app is restarted.
            self._refresh_active_translator()

            # Pipeline oluştur ve yapılandır
            self.pipeline = TranslationPipeline(self.config, self.translation_manager)
            target_path = self._tl_source_path if self._tl_mode else self._project_path
            
            # Ensure target and source languages are freshly synced from config
            effective_target = self.config.normalize_renpy_language_code(
                self.config.translation_settings.target_language or self._target_language or "turkish"
            )
            self._target_language = effective_target
            effective_source = self.config.translation_settings.source_language or "auto"

            self.pipeline.configure(
                game_exe_path=target_path,
                target_language=self._target_language,
                source_language=effective_source,
                engine=self._selected_engine,
                auto_unren=self.config.app_settings.unren_auto_download,
                use_proxy=self.config.proxy_settings.enabled,
                include_deep_scan=self.config.translation_settings.enable_deep_scan,
                include_rpyc=self.config.translation_settings.enable_rpyc_reader,
                is_tl_mode=self._tl_mode,
            )

            # Pipeline sinyallerini bu backend'e bağla
            self.pipeline.stage_changed.connect(self._on_stage_changed)
            self.pipeline.progress_updated.connect(self._on_progress_updated)
            self.pipeline.log_message.connect(self._on_log_message)
            self.pipeline.finished.connect(self._on_pipeline_finished)
            self.pipeline.show_warning.connect(self._on_show_warning)

            self.logMessage.emit(
                "info",
                self._t("log_translation_starting", "🚀 Translation starting..."),
            )

            # Worker thread'de pipeline'ı çalıştır
            self.pipeline_worker = PipelineWorker(self.pipeline)
            self.pipeline_worker.start()

        except Exception as exc:
            self.logger.exception("[AppBackend] startTranslation error")
            self.logMessage.emit("error", f"❌ Translation start error: {exc}")
            self._is_translating = False
            self.translationFinished.emit(False, str(exc))

    def _on_builtin_server_prepared(self, ok: bool, error: str) -> None:
        self.localServerStatusChanged.emit()
        if not self._preparing_builtin_server:
            return  # stopped while the model was loading
        self._preparing_builtin_server = False
        if ok:
            self._start_pipeline_translation(builtin_server_ready=True)
            return
        self.logMessage.emit("error", f"❌ {error}")
        self._is_translating = False
        self.translationFinished.emit(False, error)

    def stop_translation(self, wait_ms: int = 0) -> None:
        """Stops the translation pipeline and optionally waits for worker thread termination."""
        if self._preparing_builtin_server:
            # No pipeline yet — the model is still loading. The server keeps
            # loading in the background and is reused by the next run.
            self._preparing_builtin_server = False
            self._is_translating = False
            self.logMessage.emit(
                "warning", self._t("log_stop_requested", "⏹ Stop request sent...")
            )
            self.translationFinished.emit(False, "stopped")
            return
        if self.pipeline and self._is_translating:
            self.pipeline.stop()
            self.logMessage.emit(
                "warning", self._t("log_stop_requested", "⏹ Stop request sent...")
            )
            if wait_ms > 0 and self.pipeline_worker and self.pipeline_worker.isRunning():
                self.pipeline_worker.wait(wait_ms)

    @pyqtSlot()
    def stopTranslation(self) -> None:
        """Çeviri pipeline'ını durdurur."""
        self.stop_translation(wait_ms=0)

    @pyqtSlot()
    def shutdown(self, timeout_ms: int = 3000) -> None:
        """Safely persists settings and stops worker thread on application exit."""
        try:
            self.llama_server.stop()
        except Exception as exc:
            self.logger.warning(f"[AppBackend] llama-server stop on shutdown failed: {exc}")

        try:
            self.persistSettingsOnExit()
        except Exception as exc:
            self.logger.warning(f"[AppBackend] persistSettingsOnExit on shutdown failed: {exc}")

        if self.pipeline and self._is_translating:
            try:
                self.pipeline.stop()
            except Exception as exc:
                self.logger.warning(f"[AppBackend] pipeline.stop on shutdown failed: {exc}")

        if self.pipeline_worker and self.pipeline_worker.isRunning():
            self.logger.info(f"[AppBackend] Waiting for pipeline worker to finish (timeout={timeout_ms}ms)...")
            finished = self.pipeline_worker.wait(timeout_ms)
            if not finished:
                self.logger.warning("[AppBackend] Pipeline worker did not finish in time during shutdown.")

    # ── Pipeline Signal Handlers ─────────────────────────────────────────

    def _on_stage_changed(self, stage: str, display_name: str) -> None:
        self.stageChanged.emit(stage, display_name)

    def _on_progress_updated(self, current: int, total: int, text: str) -> None:
        self.progressChanged.emit(current, total, text)

    def _on_log_message(self, level: str, message: str) -> None:
        self.logMessage.emit(level, message)

    def _on_show_warning(self, title: str, message: str) -> None:
        self.warningMessage.emit(title, message)

    def _on_pipeline_finished(self, result: object) -> None:
        """Pipeline tamamlandığında veya hatayla bittiğinde çağrılır."""
        self._is_translating = False

        success = getattr(result, "success", False)
        message = getattr(result, "message", "")
        stats = getattr(result, "stats", None) or {}
        output_path = getattr(result, "output_path", "") or ""

        # İstatistikleri yayınla
        total = stats.get("total", 0)
        translated = stats.get("translated", 0)
        untranslated = stats.get("untranslated", total - translated)
        self.statsReady.emit(total, translated, untranslated)

        # Tamamlanma özeti
        if success:
            title = "✅ Çeviri Tamamlandı"
            diag_path = getattr(result, "error", "") or ""
            # Diagnostic path'i stats'tan almayı dene
            if stats and "diagnostic_path" in stats:
                diag_path = stats["diagnostic_path"]
            self.completionSummary.emit(title, message, output_path, diag_path, 0)
            self.send_desktop_notification(
                "desktop_notify_complete_title",
                "desktop_notify_complete_msg",
                is_error=False,
            )
        else:
            error_detail = getattr(result, "error", "") or message
            self.logMessage.emit("error", f"❌ Translation failed: {error_detail}")
            self.send_desktop_notification(
                "desktop_notify_error_title",
                "desktop_notify_error_msg",
                is_error=True,
            )

        self.translationFinished.emit(success, message)

    @pyqtSlot()
    def saveSettings(self) -> None:
        """Kayıtlı ayarları config.json'a kalıcı olarak kaydeder (runtime override'lar korunarak)."""
        try:
            self.settings.save_settings()

            # Re-setup the active translator to apply newly saved settings
            self._setup_selected_engine_async(self._selected_engine)

            self.logMessage.emit(
                "success",
                self._t("log_settings_saved", "💾 Settings saved successfully."),
            )
        except Exception as exc:
            self.logger.exception("[AppBackend] saveSettings error")
            self.logMessage.emit("error", f"❌ Settings save failed: {exc}")

    @pyqtSlot()
    def persistSettingsOnExit(self) -> None:
        """Best-effort persistence of in-memory settings when the app quits.

        Most setters only update the in-memory ConfigManager, so without this
        hook edits made in the UI (model name, server URL, concurrency,
        Hy-MT2 profile, temperature, ...) would be lost on restart.
        """
        try:
            self.config.save_config()
        except Exception:
            self.logger.exception("[AppBackend] persistSettingsOnExit failed")

    @pyqtSlot(result=str)
    def getDataDir(self) -> str:
        """Absolute path where config, caches, logs and glossary are stored."""
        return str(self.config.data_dir)

    @pyqtSlot(result=bool)
    def factoryReset(self) -> bool:
        """Restore the first-launch state: default settings + wiped user data."""
        if self._is_translating:
            self.logMessage.emit(
                "warning",
                self._t(
                    "factory_reset_busy",
                    "Stop the running translation before factory reset.",
                ),
            )
            return False
        try:
            self.settings.factory_reset()

            # Sync runtime engine state back to the default engine
            self._selected_engine = TranslationEngine.GOOGLE
            self.settings._selected_engine = TranslationEngine.GOOGLE
            self.config.translation_settings.selected_engine = "google"

            # Clear the in-memory translation cache as well
            self.translation_manager._cache.clear()
            self.translation_manager.cache_hits = 0
            self.translation_manager.cache_misses = 0

            # Re-register the default translator with default settings
            self._setup_google_translator()

            self.refreshUI()
            self.logMessage.emit(
                "success",
                self._t(
                    "log_factory_reset_done",
                    "🔄 Factory reset complete. Restart the app for a clean start.",
                ),
            )
            return True
        except Exception as exc:
            self.logger.exception("[AppBackend] factoryReset error")
            self.logMessage.emit("error", f"❌ Factory reset failed: {exc}")
            return False

    @pyqtSlot()
    def restartApplication(self) -> None:
        """Relaunch the application (used after factory reset)."""
        import subprocess

        try:
            if getattr(sys, "frozen", False):
                subprocess.Popen([sys.executable])
            else:
                repo_root = Path(__file__).resolve().parent.parent
                subprocess.Popen(
                    [sys.executable, str(repo_root / "run.py")],
                    cwd=str(repo_root),
                )
            from PyQt6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None:
                app.quit()
        except Exception as exc:
            self.logger.exception("[AppBackend] restartApplication error")
            self.logMessage.emit("error", f"❌ Restart failed: {exc}")

    @pyqtSlot(bool)
    def checkForUpdates(self, manual: bool = False) -> None:
        """Yeni güncellemeleri denetler (asenkron)."""
        if not manual and not self.config.app_settings.check_for_updates:
            return

        msg = self.config.get_ui_text("update_checking", "Checking for updates...")
        self.logMessage.emit("info", f"🔍 {msg}")
        threading.Thread(
            target=self._check_updates_thread, args=(manual,), daemon=True
        ).start()

    def _check_updates_thread(self, manual: bool) -> None:
        try:
            from src.utils.update_checker import check_for_updates

            result = check_for_updates(self._version)
            if result.update_available:
                log_msg = self.config.get_ui_text(
                    "log_update_available", "Update available: {version}"
                ).replace("{version}", result.latest_version)
                self.logMessage.emit("success", f"🔔 {log_msg}")
                self.updateAvailable.emit(
                    result.current_version,
                    result.latest_version,
                    result.release_url,
                )
                self.updateCheckFinished.emit(
                    True, f"Update found: {result.latest_version}"
                )
            else:
                msg = self.config.get_ui_text(
                    "update_check_no_update", "You are up to date."
                )
                if manual:
                    self.logMessage.emit("info", f"ℹ️ {msg}")
                self.updateCheckFinished.emit(False, msg)
        except RuntimeError as exc:
            # Underlying C++ object was destroyed while thread was finishing
            self.logger.debug(f"[AppBackend] Update check thread aborted due to object teardown: {exc}")
        except Exception as exc:
            try:
                err_msg = self.config.get_ui_text(
                    "log_update_check_failed", "Update check failed: {error}"
                ).replace("{error}", str(exc))
                self.logMessage.emit("error", f"❌ {err_msg}")
                self.updateCheckFinished.emit(False, f"Update Check Failed: {exc}")
            except RuntimeError:
                pass

    # ── 12. ARAÇ KUTUSU (TOOLBOX) SLOTLARI ───────────────────────────────
    @pyqtSlot()
    def runToolFontHelper(self) -> None:
        """Run font compatibility check."""
        if not self._require_tool_game_dir():
            return
        self.logMessage.emit(
            "info",
            self._t(
                "log_font_check_starting", "🔤 Font compatibility check starting..."
            ),
        )
        threading.Thread(target=self._run_font_helper_thread, daemon=True).start()

    def _run_font_helper_thread(self) -> None:
        try:
            from src.tools.font_helper import check_font_for_project

            target_lang = getattr(
                self.config.translation_settings, "target_language", "turkish"
            )
            # The selected path may be the game's EXE; fonts live under game/.
            summary = check_font_for_project(self._tool_game_dir(), target_lang)
            total = summary.get("fonts_checked", 0)
            compat = summary.get("compatible_fonts", 0)
            incompat = summary.get("incompatible_fonts", 0)
            suggestions = summary.get("suggestions", [])
            sug_str = f" Recommended: {', '.join(suggestions[:3])}" if suggestions else ""
            basis = (
                "the characters your translation uses"
                if summary.get("basis") == "translation"
                else f"a '{target_lang}' sample (no translation yet)"
            )
            if incompat > 0:
                missing = summary.get("missing_by_font", {})
                details = "; ".join(f"{name}: {chars}" for name, chars in list(missing.items())[:3])
                self.logMessage.emit(
                    "warning",
                    f"⚠️ Font check against {basis}: {total} font(s) scanned — {incompat} cannot show "
                    f"all characters (missing → {details}).{sug_str} Use 'Inject' to add a matching font.",
                )
            elif total > 0:
                self.logMessage.emit(
                    "success",
                    f"✅ Font check against {basis}: all {compat} font(s) can show '{target_lang}'.",
                )
            else:
                self.logMessage.emit(
                    "info",
                    f"ℹ️ No custom fonts found in game folder. Ren'Py will use its default font.{sug_str}",
                )
        except Exception as e:
            self.logMessage.emit("error", f"❌ Font helper error: {e}")

    @pyqtSlot()
    def runToolFontInject(self) -> None:
        """Download and inject Google Fonts."""
        if not self._require_tool_game_dir():
            return
        self.logMessage.emit(
            "info", "🔤 Downloading and injecting font from Google Fonts..."
        )
        threading.Thread(target=self._run_font_inject_thread, daemon=True).start()

    def _run_font_inject_thread(self) -> None:
        try:
            from src.tools.font_injector import inject_font

            target_lang = getattr(
                self.config.translation_settings, "target_language", "turkish"
            )
            result = inject_font(self._tool_game_dir(), target_lang)
            if result.get("success"):
                self.logMessage.emit(
                    "success", f"✅ Font injected: {result.get('font', '?')}"
                )
            else:
                self.logMessage.emit(
                    "warning", f"⚠️ Font injection failed: {result.get('message', '?')}"
                )
        except Exception as e:
            self.logMessage.emit("error", f"❌ Font injection error: {e}")

    @pyqtSlot()
    def runToolRenpyLint(self) -> None:
        """Run Ren'Py lint on game project."""
        if not self._require_tool_game_dir():
            return
        self.logMessage.emit(
            "info", self._t("log_lint_starting", "🩺 Ren'Py Lint scanner running...")
        )
        threading.Thread(target=self._run_renpy_lint_thread, daemon=True).start()

    def _run_renpy_lint_thread(self) -> None:
        try:
            from src.tools.renpy_lint import lint_translation_output

            sdk_path = self.config.app_settings.renpy_sdk_path
            game_dir = self._tool_game_dir()
            tl_dir = os.path.join(game_dir, "tl")
            target_path = tl_dir if os.path.isdir(tl_dir) else game_dir
            report = lint_translation_output(
                target_path,
                try_engine_lint=bool(sdk_path),
                game_dir=os.path.dirname(game_dir),
                sdk_path=sdk_path,
            )
            if report is None:
                self.logMessage.emit("warning", "⚠️ Lint could not run on the selected project.")
            elif report.ok:
                self.logMessage.emit(
                    "success",
                    f"✅ Lint passed: {report.files_scanned} files scanned, {report.translate_blocks} translate blocks, {report.old_new_pairs} old/new pairs. No syntax or indentation errors found.",
                )
            else:
                self.logMessage.emit(
                    "warning",
                    f"⚠️ Lint findings: {report.errors} error(s), {report.warnings} warning(s)\n{report.summary()}",
                )
        except Exception as e:
            self.logMessage.emit("error", f"❌ Ren'Py Lint error: {e}")

    # ── Tool: language activation file ──────────────────────────────────

    def _tool_game_dir(self) -> Optional[str]:
        """game/ folder of the selected project (path may be the exe, the
        project root, game/ itself or a tl/ folder inside it)."""
        path = self._project_path
        if not path:
            return None
        if os.path.isfile(path):
            path = os.path.dirname(path)
        parts = os.path.normpath(path).split(os.sep)
        lowered = [p.lower() for p in parts]
        if "tl" in lowered:
            idx = len(lowered) - 1 - lowered[::-1].index("tl")
            path = os.sep.join(parts[:idx]) or path
        if os.path.basename(os.path.normpath(path)).lower() == "game" and os.path.isdir(path):
            return path
        candidate = os.path.join(path, "game")
        return candidate if os.path.isdir(candidate) else None

    def _require_tool_game_dir(self) -> Optional[str]:
        """game/ dir for a Toolbox action, or None after telling the user why."""
        game_dir = self._tool_game_dir()
        if not game_dir:
            self.logMessage.emit("error", self._t(
                "log_select_game", "❌ Please select a game folder or EXE first."))
        return game_dir

    @pyqtSlot(result=list)
    def toolListTlLanguages(self) -> list:
        """Languages that have a game/tl/<lang> folder in the selected project."""
        game_dir = self._tool_game_dir()
        if not game_dir:
            return []
        from src.core.pipeline.saving import list_tl_languages
        return list_tl_languages(game_dir)

    @pyqtSlot(result=str)
    def toolDefaultTlLanguage(self) -> str:
        """Pre-selection for the tool: the dashboard target if it has a tl/ folder."""
        langs = self.toolListTlLanguages()
        target = (self._target_language or "").lower()
        for lang in langs:
            if lang.lower() == target:
                return lang
        return langs[0] if langs else ""

    @pyqtSlot(str)
    def runToolActivateLanguage(self, language: str) -> None:
        """Write game/zzz_<lang>_language.rpy so the game starts in *language*.

        Ren'Py does not list tl/ folders by itself; without this file (or a
        language menu in the game) a finished translation never shows up.
        """
        game_dir = self._tool_game_dir()
        if not game_dir:
            self.logMessage.emit("error", self._t(
                "log_select_game", "❌ Please select a game folder or EXE first."))
            return
        language = (language or "").strip()
        if not language:
            self.logMessage.emit("warning", self._t(
                "tool_lang_no_tl", "No translation folders found in game/tl. Translate the game first."))
            return
        from src.core.pipeline.saving import create_language_init_file
        create_language_init_file(game_dir, language, self.config, self.logMessage.emit, force=True)
        self.logMessage.emit("success", self._t(
            "log_lang_activated", "✅ The game will now start in: {lang}").replace("{lang}", language))

    @pyqtSlot()
    def runToolRemoveLanguageActivation(self) -> None:
        """Remove RenLocalizer's language activation file(s) from game/."""
        game_dir = self._tool_game_dir()
        if not game_dir:
            self.logMessage.emit("error", self._t(
                "log_select_game", "❌ Please select a game folder or EXE first."))
            return
        from src.core.pipeline.saving import remove_language_init_files
        removed = remove_language_init_files(game_dir)
        if removed:
            self.logMessage.emit("success", self._t(
                "log_lang_activation_removed",
                "✅ Language activation removed; the game starts in its own language again."))
        else:
            self.logMessage.emit("info", self._t(
                "log_lang_activation_none", "No language activation file was found in game/."))

    @pyqtSlot()
    def runToolGlossaryExtractor(self) -> None:
        """Extract glossary terms from project."""
        if not self._require_tool_game_dir():
            return
        self.logMessage.emit(
            "info",
            self._t("log_glossary_extracting", "📚 Extracting glossary terms..."),
        )
        threading.Thread(
            target=self._run_glossary_extractor_thread, daemon=True
        ).start()

    def _run_glossary_extractor_thread(self) -> None:
        try:
            from src.tools.glossary_extractor.extractor import GlossaryExtractor

            extractor = GlossaryExtractor()
            # Scan game/ (the selected path may be the EXE). The terms go into
            # RenLocalizer's own glossary; nothing is written into the game.
            terms = extractor.extract_from_directory(
                self._tool_game_dir(), min_occurrence=3
            )
            added = 0
            for term, target in terms.items():
                if term not in self.config.glossary:
                    self.config.glossary[term] = target
                    added += 1
            self.config.save_glossary()
            self.glossaryChanged.emit()
            self.logMessage.emit(
                "success",
                self._t(
                    "log_glossary_extracted",
                    "✅ {found} terms found, {added} new ones added to the glossary (Glossary tab).",
                ).replace("{found}", str(len(terms))).replace("{added}", str(added)),
            )
        except Exception as e:
            self.logMessage.emit("error", f"❌ Glossary extractor error: {e}")

    # ── 📚 Sözlük Yönetimi (Glossary Management) ──────────────────────────

    @pyqtProperty(list, notify=glossaryChanged)
    def glossaryList(self) -> list:
        return self.settings.get_glossary_list()

    @pyqtSlot(str, str)
    def addGlossaryItem(self, source: str, target: str) -> None:
        self.settings.add_glossary_item(source, target)

    @pyqtSlot(str)
    def removeGlossaryItem(self, source: str) -> None:
        self.settings.remove_glossary_item(source)

    @pyqtSlot()
    def translateEmptyGlossary(self) -> None:
        """Boş hedef alanlarını Google Translate ile çevir."""
        threading.Thread(
            target=self._translate_empty_glossary_thread, daemon=True
        ).start()

    def _run_translate_batch_sync(self, translator, requests):
        """Run an async ``translate_batch`` from a worker thread.

        Creates a dedicated event loop and drops any aiohttp session bound to a
        previous (now-dead) loop, then closes the session afterwards. Without
        this, calling ``translate_batch`` synchronously returns a coroutine, and
        reusing a stale session raises 'Event loop is closed'.
        """
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(translator.close())
            return loop.run_until_complete(translator.translate_batch(requests))
        finally:
            try:
                loop.run_until_complete(translator.close())
            except Exception:
                pass
            loop.close()

    def _translate_empty_glossary_thread(self) -> None:
        try:
            if not hasattr(self.config, "glossary"):
                return
            empty_keys = [k for k, v in self.config.glossary.items() if not v]
            if not empty_keys:
                self.logMessage.emit(
                    "info", "✅ All glossary terms already have translations."
                )
                return

            self.logMessage.emit(
                "info", f"🌐 Translating {len(empty_keys)} empty terms via Google..."
            )
            from src.core.translator import (
                GoogleTranslator,
                TranslationEngine,
                TranslationRequest,
            )

            from src.tools.font_injector import _normalize_lang_code

            ts = getattr(self.config, "translation_settings", None)
            raw_src = getattr(ts, "source_language", "auto") if ts else "auto"
            raw_tgt = getattr(ts, "target_language", "turkish") if ts else "turkish"
            src_lang = _normalize_lang_code(raw_src) if raw_src != "auto" else "auto"
            tgt_lang = _normalize_lang_code(raw_tgt)

            translator = GoogleTranslator(config_manager=self.config)
            count = 0
            for key in empty_keys:
                try:
                    request = TranslationRequest(
                        text=key,
                        source_lang=src_lang,
                        target_lang=tgt_lang,
                        engine=TranslationEngine.GOOGLE,
                    )
                    results = self._run_translate_batch_sync(translator, [request])
                    if results:
                        translated = results[0].translated_text
                        if translated and translated != key:
                            self.config.glossary[key] = translated
                            count += 1
                except Exception:
                    self.logger.warning(
                        "Failed to translate glossary entry for key=%r", key
                    )
                if count % 10 == 0 and count > 0:
                    self.logMessage.emit(
                        "info", f"🌐 Translated: {count}/{len(empty_keys)}"
                    )

            self.config.save_glossary()
            self.glossaryChanged.emit()
            self.logMessage.emit(
                "success", f"✅ {count} glossary terms translated and saved."
            )
        except Exception as e:
            self.logMessage.emit("error", f"❌ Glossary translation failed: {e}")

    @pyqtSlot()
    def fillEmptyGlossaryWithSource(self) -> None:
        """Fill empty targets with source text."""
        if not hasattr(self.config, "glossary"):
            return
        count = 0
        for k, v in self.config.glossary.items():
            if not v:
                self.config.glossary[k] = k
                count += 1
        if count > 0:
            self.config.save_glossary()
            self.glossaryChanged.emit()
            self.logMessage.emit(
                "success", f"✅ {count} empty terms filled with source text."
            )
        else:
            self.logMessage.emit(
                "info", self._t("log_empty_terms_none", "No empty terms to fill.")
            )

    @pyqtSlot(str)
    def exportGlossary(self, filepath: str) -> None:
        """Export glossary to JSON/XLSX/CSV."""
        try:
            from src.utils.data_transfer import export_glossary_to_file

            glossary = getattr(self.config, "glossary", {})
            export_glossary_to_file(glossary, filepath)
            self.logMessage.emit("success", f"📤 Glossary exported to: {filepath}")
        except Exception as e:
            self.logMessage.emit("error", f"❌ Export error: {e}")

    @pyqtSlot(str)
    def importGlossary(self, filepath: str) -> None:
        """Import glossary from JSON/XLSX/CSV."""
        try:
            from src.utils.data_transfer import import_glossary_from_file

            imported = import_glossary_from_file(filepath)
            if not hasattr(self.config, "glossary"):
                self.config.glossary = {}
            new_count = 0
            updated_count = 0
            for src, tgt in imported.items():
                if src in self.config.glossary:
                    if self.config.glossary[src] != tgt and tgt:
                        self.config.glossary[src] = tgt
                        updated_count += 1
                else:
                    self.config.glossary[src] = tgt
                    new_count += 1
            self.config.save_glossary()
            self.glossaryChanged.emit()
            self.logMessage.emit(
                "success", f"📥 Imported: {new_count} new, {updated_count} updated."
            )
        except Exception as e:
            self.logMessage.emit("error", f"❌ Import error: {e}")
