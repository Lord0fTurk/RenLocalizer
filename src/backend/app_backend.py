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
from PyQt6.QtGui import QDesktopServices

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
    selectedEngineChanged = pyqtSignal(str)
    openaiApiKeyChanged = pyqtSignal()
    openaiModelChanged = pyqtSignal()
    openaiBaseUrlChanged = pyqtSignal()
    geminiApiKeyChanged = pyqtSignal()
    geminiModelChanged = pyqtSignal()
    localLlmUrlChanged = pyqtSignal()
    localLlmModelChanged = pyqtSignal()
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

        # Seçili motor her zaman Google; config'e yazılmıyor (runtime override)
        self.config.translation_settings.selected_engine = "google"
        # Gerekmeyen ağır özellikleri kapat (hız + bellek tasarrufu)
        self.config.translation_settings.enable_deep_extraction = False
        self.config.translation_settings.enable_unrpyc_decompile = False
        # ── State ────────────────────────────────────────────────────────
        self._project_path: str = self.config.app_settings.last_input_directory or ""
        self._target_language: str = (
            self.config.translation_settings.target_language or "turkish"
        )
        self._is_translating: bool = False
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
        self.settings.on("rpyc_reader", lambda: self.enableRpycReaderChanged.emit())
        self.settings.on("deep_scan", lambda: self.enableDeepScanChanged.emit())
        self.settings.on("selected_engine", lambda engine_str: self.selectedEngineChanged.emit(engine_str))
        self.settings.on("openai_api_key", lambda: self.openaiApiKeyChanged.emit())
        self.settings.on("openai_model", lambda: self.openaiModelChanged.emit())
        self.settings.on("openai_base_url", lambda: self.openaiBaseUrlChanged.emit())
        self.settings.on("gemini_api_key", lambda: self.geminiApiKeyChanged.emit())
        self.settings.on("gemini_model", lambda: self.geminiModelChanged.emit())
        self.settings.on("local_llm_url", lambda: self.localLlmUrlChanged.emit())
        self.settings.on("local_llm_model", lambda: self.localLlmModelChanged.emit())
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
        self.settings.on("output_mode", lambda: self.outputModeChanged.emit())
        self.settings.on("language", lambda lang_code: self.languageChanged.emit(lang_code))
        self.settings.on("theme", lambda theme: self.themeChanged.emit(theme))
        self.settings.on("glossary", lambda: self.glossaryChanged.emit())

        # Google translator'ı her zaman hazırla (fallback)
        threading.Thread(target=self._setup_google_translator, daemon=True).start()
        # Seçili motora göre diğer translator'ları kur
        if self._selected_engine not in (TranslationEngine.GOOGLE,):
            if self._selected_engine in (
                TranslationEngine.OPENAI,
                TranslationEngine.LOCAL_LLM,
                TranslationEngine.GEMINI,
            ):
                threading.Thread(
                    target=self._setup_ai_translator,
                    args=(self._selected_engine,),
                    daemon=True,
                ).start()
            elif self._selected_engine == TranslationEngine.LIBRETRANSLATE:
                threading.Thread(target=self._setup_libretranslate, daemon=True).start()
            elif self._selected_engine == TranslationEngine.CUSTOM:
                threading.Thread(
                    target=self._setup_custom_endpoint, daemon=True
                ).start()

    # ── Private setup ────────────────────────────────────────────────────

    def _setup_google_translator(self) -> None:
        """Google Translate motorunu kurar."""
        try:
            google = GoogleTranslator(
                proxy_manager=self.proxy_manager,
                config_manager=self.config,
            )
            self.translation_manager.add_translator(TranslationEngine.GOOGLE, google)
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
            self.translation_manager.add_translator(
                TranslationEngine.LIBRETRANSLATE, lt
            )
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
            self.translation_manager.add_translator(TranslationEngine.CUSTOM, ct)
            self.logger.info(f"[AppBackend] Custom endpoint hazır: {base_url}")
        except Exception as exc:
            self.logger.error("[AppBackend] Custom endpoint kurulamadı: %s", exc)

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
            "custom": TranslationEngine.CUSTOM,
        }
        return mapping.get(engine_str.lower(), TranslationEngine.GOOGLE)

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
                self.logger.info("[AppBackend] Gemini translator hazır.")
            else:
                return
            self.translation_manager.add_translator(engine, translator)
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

    @pyqtProperty(bool, notify=uiTriggerChanged)
    def checkForUpdatesOnStartup(self) -> bool:
        return self.settings.get_check_for_updates()

    @checkForUpdatesOnStartup.setter
    def checkForUpdatesOnStartup(self, val: bool) -> None:
        self.settings.set_check_for_updates(val)
        self.refreshUI()

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

    # ── AI Engine Settings Properties ────────────────────────────────────

    @pyqtProperty(str, notify=selectedEngineChanged)
    def selectedEngine(self) -> str:
        return self.settings.get_selected_engine()

    @pyqtSlot(str)
    def setSelectedEngine(self, engine_str: str) -> None:
        """Changes the active translation engine and sets it up if needed."""
        new_engine = self._engine_from_str(engine_str)
        self.settings.set_selected_engine(engine_str)
        if new_engine == self._selected_engine:
            return
        self._selected_engine = new_engine
        # Setup new engine in background if not Google (Google always active as fallback)
        if new_engine not in (TranslationEngine.GOOGLE,):
            if new_engine in (TranslationEngine.OPENAI, TranslationEngine.LOCAL_LLM, TranslationEngine.GEMINI):
                threading.Thread(
                    target=self._setup_ai_translator, args=(new_engine,), daemon=True
                ).start()
            elif new_engine == TranslationEngine.LIBRETRANSLATE:
                threading.Thread(target=self._setup_libretranslate, daemon=True).start()
            elif new_engine == TranslationEngine.CUSTOM:
                threading.Thread(
                    target=self._setup_custom_endpoint, daemon=True
                ).start()

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

    @pyqtSlot(result=list)
    def getSourceLanguages(self) -> list:
        return self.settings.get_source_languages()

    @pyqtSlot(str)
    def setSourceLanguage(self, lang: str) -> None:
        self.settings.set_source_language(lang)

    # ── Project Slot ─────────────────────────────────────────────────────

    @pyqtSlot(str)
    def setProjectPath(self, path: str) -> None:
        """Oyun proje yolunu ayarlar ve Ren'Py projesi olup olmadığını doğrular."""
        path = _normalize_path(path)
        if not path:
            return

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

        if self._tl_mode:
            threading.Thread(target=self._run_tl_retranslation, daemon=True).start()
        else:
            self._start_pipeline_translation()

    def _start_pipeline_translation(self) -> None:
        """Normal pipeline tabanlı çeviriyi başlatır."""
        try:
            # Pipeline oluştur ve yapılandır
            self.pipeline = TranslationPipeline(self.config, self.translation_manager)
            self.pipeline.configure(
                game_exe_path=self._project_path,
                target_language=self._target_language,
                source_language="auto",
                engine=self._selected_engine,
                auto_unren=self.config.app_settings.unren_auto_download,
                use_proxy=self.config.proxy_settings.enabled,
                include_deep_scan=self.config.translation_settings.enable_deep_scan,
                include_rpyc=self.config.translation_settings.enable_rpyc_reader,
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

    @pyqtSlot()
    def stopTranslation(self) -> None:
        """Çeviri pipeline'ını durdurur."""
        if self._tl_mode:
            # TL retranslation modunda thread'i durdur
            self._tl_stop_requested = True
            self.logMessage.emit(
                "warning", self._t("log_stop_requested", "⏹ Stop request sent...")
            )
        elif self.pipeline and self._is_translating:
            self.pipeline.stop()
            self.logMessage.emit(
                "warning", self._t("log_stop_requested", "⏹ Stop request sent...")
            )

    def _run_tl_retranslation(self) -> None:
        """
        TL retranslation modu: Ren'Py SDK'nın oluşturduğu tl/ klasörünü
        okur, boş çevirileri Google Translate ile doldurur ve in-place kaydeder.

        Bu metot bir arka plan thread'inde çalışır.
        """
        self._tl_stop_requested = False
        tl_parser = TLParser()
        total_translated = 0
        total_skipped = 0
        total_saved = 0
        total_failed = 0

        try:
            # ── 1. Klasörü tara ──────────────────────────────────────────
            tl_path = self._tl_source_path
            lang = self._target_language

            self.stageChanged.emit(
                "parsing", self._t("stage_parsing", "📂 Scanning TL Files")
            )
            self.logMessage.emit("info", f"🔍 Scanning TL folder: {tl_path}")

            # parse_directory: tl/lang/ klasörünü parse et.
            # Eğer kullanıcı zaten tl/lang/ içindeyse bu da desteklenir.
            tl_files = tl_parser.parse_directory(tl_path, lang)

            if not tl_files:
                # Fallback: kullanıcı doğrudan tl/lang/ klasörünü seçti
                # parse_directory, lang alt klasörünü aramaya çalışır;
                # ama tl_path=tl/lang/ ise zaten bu klasörü dener.
                # İkinci deneme: tl_path'i doğrudan parse etmeye çalış.
                import os

                rpy_files = []
                for root, _, fnames in os.walk(tl_path):
                    for fname in fnames:
                        if fname.lower().endswith(".rpy"):
                            rpy_files.append(os.path.join(root, fname))
                if rpy_files:
                    for fpath in rpy_files:
                        tf = tl_parser.parse_file(fpath)
                        if tf:
                            tl_files.append(tf)

            if not tl_files:
                self.logMessage.emit(
                    "error",
                    self._t("log_no_rpy_files", "❌ No .rpy files found in TL folder."),
                )
                self._is_translating = False
                self.translationFinished.emit(False, "TL dosyası bulunamadı.")
                return

            stats = get_translation_stats(tl_files)
            total_entries = stats["total"]
            untranslated = stats["untranslated"]

            self.logMessage.emit(
                "info",
                f"📊 {len(tl_files)} dosya, {total_entries} giriş, "
                f"{untranslated} çeviri bekliyor, {stats['translated']} zaten çevrilmiş.",
            )

            if untranslated == 0:
                self.logMessage.emit(
                    "success",
                    self._t(
                        "log_all_translated", "✅ All translations already completed."
                    ),
                )
                self.statsReady.emit(total_entries, stats["translated"], 0)
                self.completionSummary.emit(
                    "✅ Çeviri Tamamlandı",
                    "Tüm girişler zaten çevrilmiş durumda.",
                    tl_path,
                    "",
                    0,
                )
                self._is_translating = False
                self.translationFinished.emit(True, "Zaten çevrilmiş.")
                return

            # ── 2. Çeviri ────────────────────────────────────────────────
            self.stageChanged.emit("translating", "🌐 Translating")

            google = self.translation_manager.translators.get(TranslationEngine.GOOGLE)
            if not google:
                self.logMessage.emit(
                    "error",
                    self._t("log_google_not_ready", "❌ Google Translate not ready."),
                )
                self._is_translating = False
                self.translationFinished.emit(False, "Google Translate hazır değil.")
                return

            processed = 0
            for tl_file in tl_files:
                if self._tl_stop_requested:
                    self.logMessage.emit(
                        "warning",
                        self._t("log_translation_stopped", "⏹ Translation stopped."),
                    )
                    break

                untranslated_entries = tl_file.get_untranslated()
                if not untranslated_entries:
                    continue

                # Batch translate
                texts = [e.original_text for e in untranslated_entries]
                try:
                    results = google.translate_batch(
                        texts,
                        source_lang="auto",
                        target_lang=lang,
                    )
                except Exception as exc:
                    self.logMessage.emit(
                        "warning",
                        f"⚠️ Translation error ({os.path.basename(tl_file.file_path)}): {exc}",
                    )
                    total_failed += len(texts)
                    processed += len(texts)
                    self.progressChanged.emit(
                        processed,
                        untranslated,
                        f"Hata: {os.path.basename(tl_file.file_path)}",
                    )
                    continue

                # ID → translated_text sözlüğü oluştur
                translations: dict[str, str] = {}
                for entry, result in zip(untranslated_entries, results):
                    translated = (
                        getattr(result, "translated_text", None)
                        or getattr(result, "text", None)
                        or ""
                    )
                    if translated:
                        translations[entry.translation_id] = translated
                        translations[entry.original_text] = translated  # fallback key
                        total_translated += 1
                    else:
                        total_skipped += 1

                processed += len(texts)
                self.progressChanged.emit(
                    processed,
                    untranslated,
                    f"Çevriliyor: {os.path.basename(tl_file.file_path)}",
                )

                # ── 3. Kaydet ────────────────────────────────────────────
                if translations:
                    success = tl_parser.save_translations(tl_file, translations)
                    if success:
                        total_saved += 1
                    else:
                        self.logMessage.emit(
                            "warning", f"⚠️ Save failed: {tl_file.file_path}"
                        )
                        total_failed += 1

            # ── 4. Özet ──────────────────────────────────────────────────
            self.stageChanged.emit(
                "completed", self._t("stage_completed", "✅ Completed")
            )
            self.statsReady.emit(
                total_entries,
                stats["translated"] + total_translated,
                max(0, untranslated - total_translated),
            )

            msg = (
                f"{total_translated} giriş çevrildi, "
                f"{stats['translated']} zaten çevriliydi, "
                f"{total_saved}/{len(tl_files)} dosya kaydedildi."
            )
            self.logMessage.emit("success", f"✅ TL Retranslation completed: {msg}")
            self.completionSummary.emit(
                "✅ TL Retranslation Tamamlandı", msg, tl_path, "", 0
            )
            self._is_translating = False
            self.translationFinished.emit(True, msg)

        except Exception as exc:
            self.logger.exception("[AppBackend] _run_tl_retranslation error")
            self.logMessage.emit("error", f"❌ TL retranslation error: {exc}")
            self._is_translating = False
            self.translationFinished.emit(False, str(exc))

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
        else:
            error_detail = getattr(result, "error", "") or message
            self.logMessage.emit("error", f"❌ Translation failed: {error_detail}")

        self.translationFinished.emit(success, message)

    @pyqtSlot()
    def saveSettings(self) -> None:
        """Kayıtlı ayarları config.json'a kalıcı olarak kaydeder (runtime override'lar korunarak)."""
        try:
            self.settings.save_settings()

            # Re-setup the active AI translator to apply newly saved settings
            if self._selected_engine != TranslationEngine.GOOGLE:
                threading.Thread(
                    target=self._setup_ai_translator,
                    args=(self._selected_engine,),
                    daemon=True,
                ).start()

            self.logMessage.emit(
                "success",
                self._t("log_settings_saved", "💾 Settings saved successfully."),
            )
        except Exception as exc:
            self.logger.exception("[AppBackend] saveSettings error")
            self.logMessage.emit("error", f"❌ Settings save failed: {exc}")

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
        except Exception as exc:
            err_msg = self.config.get_ui_text(
                "log_update_check_failed", "Update check failed: {error}"
            ).replace("{error}", str(exc))
            self.logMessage.emit("error", f"❌ {err_msg}")
            self.updateCheckFinished.emit(False, f"Update Check Failed: {exc}")

    # ── 12. ARAÇ KUTUSU (TOOLBOX) SLOTLARI ───────────────────────────────
    @pyqtSlot()
    def runToolFontHelper(self) -> None:
        """Run font compatibility check."""
        if not self._project_path or not os.path.exists(self._project_path):
            self.logMessage.emit(
                "error", "❌ Please select a valid game folder or EXE first."
            )
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
            check_font_for_project(self._project_path, target_lang)
            self.logMessage.emit(
                "success",
                self._t("log_font_check_done", "✅ Font check completed successfully."),
            )
        except Exception as e:
            self.logMessage.emit("error", f"❌ Font helper error: {e}")

    @pyqtSlot()
    def runToolFontInject(self) -> None:
        """Download and inject Google Fonts."""
        if not self._project_path or not os.path.exists(self._project_path):
            self.logMessage.emit(
                "error", "❌ Please select a valid game folder or EXE first."
            )
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
            result = inject_font(self._project_path, target_lang)
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
        if not self._project_path or not os.path.exists(self._project_path):
            self.logMessage.emit(
                "error", "❌ Please select a valid game project first."
            )
            return
        self.logMessage.emit(
            "info", self._t("log_lint_starting", "🩺 Ren'Py Lint scanner running...")
        )
        threading.Thread(target=self._run_renpy_lint_thread, daemon=True).start()

    def _run_renpy_lint_thread(self) -> None:
        try:
            from src.tools.renpy_lint import run_renpy_lint

            sdk_path = self.config.app_settings.renpy_sdk_path
            report = run_renpy_lint(self._project_path, sdk_path=sdk_path)
            if report is None:
                self.logMessage.emit(
                    "warning",
                    "⚠️ Ren'Py SDK not found — lint could not run. Make sure Ren'Py is installed.",
                )
            elif report.ok:
                self.logMessage.emit(
                    "success",
                    f"✅ Lint passed: {report.files_scanned} files, {report.translate_blocks} blocks, {report.old_new_pairs} pairs.",
                )
            else:
                self.logMessage.emit(
                    "warning",
                    f"⚠️ Lint: {report.errors} errors, {report.warnings} warnings\n{report.summary()}",
                )
        except Exception as e:
            self.logMessage.emit("error", f"❌ Ren'Py Lint error: {e}")

    @pyqtSlot()
    def runToolGlossaryExtractor(self) -> None:
        """Extract glossary terms from project."""
        if not self._project_path or not os.path.exists(self._project_path):
            self.logMessage.emit(
                "error", "❌ Please select a valid game project first."
            )
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
            terms = extractor.extract_from_directory(
                self._project_path, min_occurrence=3
            )
            out_json = os.path.join(self._project_path, "glossary.json")
            import json

            with open(out_json, "w", encoding="utf-8") as f:
                json.dump(terms, f, ensure_ascii=False, indent=2)
            for term in terms:
                if term not in self.config.glossary:
                    self.config.glossary[term] = ""
            self.config.save_glossary()
            self.glossaryChanged.emit()
            self.logMessage.emit(
                "success",
                f"✅ {len(terms)} terms extracted and saved to 'glossary.json'.",
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
            from src.core.translator import GoogleTranslator

            translator = GoogleTranslator(self.config)
            count = 0
            for key in empty_keys:
                try:
                    batch_result = translator.translate_batch([key], "en", "tr")
                    if batch_result and batch_result[0]:
                        translated = batch_result[0][0]
                        if translated and translated != key:
                            self.config.glossary[key] = translated
                            count += 1
                except Exception:
                    self.logger.warning("Failed to import glossary entry for key=%r", key)
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
