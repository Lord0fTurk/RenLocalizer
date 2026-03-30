# -*- coding: utf-8 -*-
"""
App Backend - Python-QML Bridge
================================

This module provides the bridge between QML UI and Python backend logic.
All QML-callable methods and signals are defined here.
"""

import logging
import os
import sys
import threading
import asyncio
import json
import time
import webbrowser
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, pyqtProperty, QUrl, QThread
from PyQt6.QtGui import QDesktopServices, QGuiApplication

from src.utils.config import ConfigManager, get_effective_batch_size, get_engine_batch_size_cap
from src.version import VERSION
from src.utils.constants import (
    AI_DEFAULT_TEMPERATURE, AI_DEFAULT_TIMEOUT, MAX_CHARS_PER_REQUEST,
    WINDOW_DEFAULT_WIDTH, WINDOW_DEFAULT_HEIGHT
)
from src.core.runtime_hook_template import render_runtime_hook
from src.core.translator import (
    TranslationManager, TranslationEngine,
    GoogleTranslator, DeepLTranslator, PseudoTranslator
)
from src.core.proxy_manager import ProxyManager
from src.core.translation_pipeline import TranslationPipeline, PipelineWorker

if TYPE_CHECKING:
    from src.core.ai_translator import OpenAITranslator, GeminiTranslator, LocalLLMTranslator
from src.utils.data_transfer import export_glossary_to_file, import_glossary_from_file


class AppBackend(QObject):
    """
    Python-QML köprüsü.
    
    QML tarafından çağrılabilir metotlar (@pyqtSlot) ve
    QML'e bildirim gönderen sinyaller (pyqtSignal) içerir.
    """
    
    # ========== SIGNALS (QML'e bildirim gönderir) ==========
    logMessage = pyqtSignal(str, str, arguments=['level', 'message'])
    progressChanged = pyqtSignal(int, int, str, arguments=['current', 'total', 'text'])
    stageChanged = pyqtSignal(str, str, arguments=['stage', 'displayName'])
    translationStarted = pyqtSignal()
    translationFinished = pyqtSignal(bool, str, arguments=['success', 'message'])
    statsReady = pyqtSignal(int, int, int, arguments=['total', 'translated', 'untranslated'])
    completionSummary = pyqtSignal(str, str, str, str, int, arguments=['title', 'message', 'outputPath', 'diagnosticPath', 'reviewNoteCount'])
    warningMessage = pyqtSignal(str, str, arguments=['title', 'message'])
    languageRefresh = pyqtSignal()
    updateAvailable = pyqtSignal(str, str, str, arguments=['currentVersion', 'latestVersion', 'releaseUrl'])
    updateCheckFinished = pyqtSignal(bool, str, arguments=['hasUpdate', 'message']) # NEW explicit signal
    engineChanged = pyqtSignal()
    tmSourcesChanged = pyqtSignal()
    
    # Initialization Signals (For UI BusyIndicator)
    initializationChanged = pyqtSignal()
    initMessageChanged = pyqtSignal()
    busyChanged = pyqtSignal() # New signal for general busy state
    
    def __init__(
        self,
        config_manager: ConfigManager,
        emoji_font_family: str = "",
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.config = config_manager
        self.logger = logging.getLogger(__name__)
        self._version = VERSION
        self._emoji_font_family = emoji_font_family
        self._ui_trigger = False
        
        # State
        self._project_path = self.config.app_settings.last_input_directory or ""
        self._target_language = getattr(self.config.translation_settings, 'target_language', "turkish")
        self._source_language = getattr(self.config.translation_settings, 'source_language', "auto")
        self._selected_engine = getattr(self.config.translation_settings, 'selected_engine', "google")
        self._is_translating = False
        self._is_initializing = False
        self._is_busy = False # General busy state for tools
        self._init_message = ""
        
        # Pipeline
        self.pipeline: Optional[TranslationPipeline] = None
        self.pipeline_worker: Optional[PipelineWorker] = None
        
        # Managers
        self.proxy_manager = ProxyManager()
        self.proxy_manager.configure_from_settings(self.config.proxy_settings)
        self.translation_manager = TranslationManager(self.proxy_manager, self.config)

        self._start_async_setup() # Heavy setup to thread
        
        # Initial Cache Load (Async call)
        self._update_cache_path_async()

    def _start_async_setup(self):
        """Move heavy engine setup to background thread."""
        threading.Thread(target=self._setup_translation_engines, daemon=True).start()

    @pyqtProperty(bool, notify=busyChanged)
    def isBusy(self):
        """Returns True if any background tool is running."""
        return self._is_busy

    def _set_busy(self, busy: bool):
        if self._is_busy != busy:
            self._is_busy = busy
            self.busyChanged.emit()

    @pyqtProperty(bool, notify=initializationChanged)
    def isInitializing(self):
        """Returns True if the backend is initializing (e.g. loading AI models)."""
        return self._is_initializing

    @pyqtProperty(str, notify=initMessageChanged)
    def initializationMessage(self):
        """Returns the current initialization status message."""
        return self._init_message

    def _set_initializing(self, active: bool, message: str = ""):
        """Internal helper to update initialization state and emit signals safely."""
        if self._is_initializing != active:
            self._is_initializing = active
            self.initializationChanged.emit()
        
        if self._init_message != message:
            self._init_message = message
            self.initMessageChanged.emit()
    
    def _setup_translation_engines(self):
        """Setup available translation engines."""
        # Local imports to avoid heavy startup load
        from src.core.ai_translator import OpenAITranslator, GeminiTranslator, LocalLLMTranslator

        # 1. Google Translate (Web)
        google_translator = GoogleTranslator(
            proxy_manager=self.proxy_manager,
            config_manager=self.config
        )
        self.translation_manager.add_translator(TranslationEngine.GOOGLE, google_translator)
        
        # 2. Pseudo (Test)
        pseudo_translator = PseudoTranslator(mode="both")
        self.translation_manager.add_translator(TranslationEngine.PSEUDO, pseudo_translator)
        
        # 3. DeepL
        deepl_key = self.config.get_api_key("deepl")
        if deepl_key:
            deepl_translator = DeepLTranslator(api_key=deepl_key, proxy_manager=self.proxy_manager, config_manager=self.config)
            self.translation_manager.add_translator(TranslationEngine.DEEPL, deepl_translator)

        # 4. OpenAI
        openai_key = self.config.get_api_key("openai")
        # OpenAI her zaman ekle (Key boş olsa bile, kullanıcı sonradan girebilir)
        openai_translator = OpenAITranslator(
            api_key=openai_key or "dummy", # Key yoksa dummy ver, request anında kontrol edilebilir
            model=getattr(self.config.translation_settings, 'openai_model', 'gpt-3.5-turbo'),
            base_url=getattr(self.config.translation_settings, 'openai_base_url', None),
            config_manager=self.config,
            proxy_manager=self.proxy_manager
        )
        self.translation_manager.add_translator(TranslationEngine.OPENAI, openai_translator)

        # 5. Gemini
        gemini_key = self.config.get_api_key("gemini")
        gemini_translator = GeminiTranslator(
            api_key=gemini_key or "dummy",
            model=getattr(self.config.translation_settings, 'gemini_model', 'gemini-2.0-flash-exp'),
            config_manager=self.config
        )
        self.translation_manager.add_translator(TranslationEngine.GEMINI, gemini_translator)



        # 6. Local LLM
        local_translator = LocalLLMTranslator(
            model=getattr(self.config.translation_settings, 'local_llm_model', 'llama3.2'),
            base_url=getattr(self.config.translation_settings, 'local_llm_url', 'http://localhost:11434/v1'),
            config_manager=self.config
        )
        self.translation_manager.add_translator(TranslationEngine.LOCAL_LLM, local_translator)

        # 7. LibreTranslate
        from src.core.translator import LibreTranslateTranslator
        lt_translator = LibreTranslateTranslator(
            base_url=getattr(self.config.translation_settings, 'libretranslate_url', 'http://localhost:5000'),
            api_key=getattr(self.config.translation_settings, 'libretranslate_api_key', ''),
            config_manager=self.config
        )
        self.translation_manager.add_translator(TranslationEngine.LIBRETRANSLATE, lt_translator)

        # 8. Yandex Translate (Free, Widget API)
        from src.core.translator import YandexTranslator
        yandex_translator = YandexTranslator(
            proxy_manager=self.proxy_manager,
            config_manager=self.config
        )
        # Attach Google as fallback for Yandex
        yandex_translator.set_fallback_translator(google_translator)
        self.translation_manager.add_translator(TranslationEngine.YANDEX, yandex_translator)

        # Opus MT (Local Transformers) - Removed in v2.7.8
        pass
    
    @pyqtSlot()
    def refreshUI(self):
        """Tüm arayüz metinlerini yenilemek için tetikleyiciyi değiştir."""
        self._ui_trigger = not self._ui_trigger
        self.languageRefresh.emit()

    @pyqtProperty(bool, notify=languageRefresh)
    def uiTrigger(self) -> bool:
        """Property used to trigger QML text refresh when language changes."""
        return self._ui_trigger

    @pyqtSlot(result=str)
    def get_app_path(self) -> str:
        """Return the current working directory (for file path usage)."""
        return os.getcwd().replace("\\", "/")

    @pyqtSlot(result=str)
    def get_app_url(self) -> str:
        """Return cwd as a file:// URL for QML FolderDialog.currentFolder."""
        return QUrl.fromLocalFile(os.getcwd()).toString()

    @pyqtSlot(str, result=str)
    def urlToPath(self, url: str) -> str:
        """Convert QML FileDialog/FolderDialog output to a local file path."""
        return self._normalize_path(url)

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Normalize a file:// URL or raw path into a local OS path.

        QUrl.toLocalFile() correctly handles cross-platform differences,
        URL-decoding, and file:/// vs file:// inconsistencies.
        """
        if not path:
            return path
        local = QUrl(path).toLocalFile()
        if local:
            return local
        # Already a plain path; still decode URL-encoded characters.
        return urllib.parse.unquote(path)

    @pyqtSlot(str, result=str)
    def get_asset_url(self, relative_path: str) -> str:
        """Returns a valid file URL for the asset, handling frozen state."""
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            base = Path(sys._MEIPASS)
        else:
            # Development mode: assume running from project root
            base = Path(os.getcwd())
        
        full_path = base / relative_path
        # Convert to forward slashes for QML
        return QUrl.fromLocalFile(str(full_path)).toString()
    
    # ========== PROPERTIES ==========
    
    @pyqtProperty(str, constant=True)
    def version(self) -> str:
        return self._version

    @pyqtProperty(str, constant=True)
    def emojiFontFamily(self) -> str:
        return self._emoji_font_family
    
    @pyqtProperty(bool, notify=translationStarted)
    def isTranslating(self) -> bool:
        return self._is_translating

    @pyqtProperty(str, notify=engineChanged)
    def selectedEngine(self) -> str:
        return self._selected_engine
    
    # ========== SLOTS (QML'den çağrılabilir) ==========
    
    @pyqtSlot(str, result=str)
    def getText(self, key: str) -> str:
        """Yerelleştirilmiş metin döndür."""
        return self.config.get_ui_text(key, key)
    
    @pyqtSlot(str, str, result=str)
    def getTextWithDefault(self, key: str, default: str) -> str:
        """Yerelleştirilmiş metin döndür, bulunamazsa default kullan."""
        return self.config.get_ui_text(key, default)
    
    @pyqtSlot(result=list)
    def getAvailableEngines(self) -> list:
        """Kullanılabilir çeviri motorlarını döndür."""
        engines = [
            {"code": "google", "name": self.config.get_ui_text("translation_engines.google", "🌐 Google Translate (Free)")},
            {"code": "deepl", "name": self.config.get_ui_text("translation_engines.deepl", "🔷 DeepL (API Key)")},
            {"code": "openai", "name": self.config.get_ui_text("translation_engines.openai", "🤖 OpenAI / OpenRouter")},
            {"code": "gemini", "name": self.config.get_ui_text("translation_engines.gemini", "✨ Google Gemini")},

            {"code": "local_llm", "name": self.config.get_ui_text("translation_engines.local_llm", "🖥️ Local LLM")},
            {"code": "libretranslate", "name": self.config.get_ui_text("translation_engines.libretranslate", "🌐 LibreTranslate (Local)")},
            {"code": "yandex", "name": self.config.get_ui_text("translation_engines.yandex", "🔵 Yandex Translate (Free)")},
        ]
        
        # Pseudo motorunu debug modunda göster
        if getattr(self.config.translation_settings, 'show_debug_engines', False):
             engines.append({"code": "pseudo", "name": self.config.get_ui_text("pseudo_engine_name", "🧪 Pseudo-Localization")})
        
        return engines
    
    @pyqtSlot(result=list)
    def getSourceLanguages(self) -> list:
        """Kaynak dilleri döndür."""
        languages = [{"code": "auto", "name": self.config.get_ui_text("auto_detect", "🔍 Auto Detect")}]
        for code, name in self.config.get_target_languages_for_ui():
            languages.append({"code": code, "name": name})
        return languages
    
    @pyqtSlot(result=list)
    def getTargetLanguages(self) -> list:
        """Hedef dilleri döndür."""
        languages = []
        for code, name in self.config.get_target_languages_for_ui():
            languages.append({"code": code, "name": name})
        return languages
    
    @pyqtSlot(str)
    def openUrl(self, url: str):
        """Open external URLs; route local paths to file manager handling."""
        if not url:
            return

        parsed = QUrl(url)
        # If caller passes a local path/URL, delegate to local opener.
        if parsed.isLocalFile() or url.startswith("file://") or os.path.isabs(url):
            self.openLocalPath(url)
            return

        QDesktopServices.openUrl(parsed)

    @pyqtSlot(str, result=bool)
    def openLocalPath(self, path: str) -> bool:
        """Open a local file or directory path with the desktop shell."""
        if not path:
            return False

        local_path = self._normalize_path(path)
        if not local_path:
            return False

        # fromLocalFile gives desktop environments a clear local target.
        return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(local_path)))

    @pyqtSlot(str, result=bool)
    def copyTextToClipboard(self, text: str) -> bool:
        try:
            QGuiApplication.clipboard().setText(text or "")
            return True
        except Exception:
            return False

    @pyqtSlot(str, result=str)
    def extractRPA(self, path: str) -> str:
        """RPA arşivlerini çıkar."""
        path = self._normalize_path(path)
        try:
            from src.utils.unrpa_adapter import UnrpaAdapter
            adapter = UnrpaAdapter()
            
            project_dir = os.path.dirname(path) if os.path.isfile(path) else path
            game_dir = os.path.join(project_dir, 'game') if os.path.isdir(os.path.join(project_dir, 'game')) else project_dir
            
            success = adapter.extract_game(Path(game_dir))
            if success:
                return self.config.get_ui_text("unren_completed", "RPA extraction completed.")
            else:
                return self.config.get_ui_text("log_rpa_not_found_or_extracted", "RPA file not found or already extracted.")
        except Exception as e:
            return f"{self.config.get_ui_text('error', 'Error')}: {str(e)}"

    @pyqtSlot(str, result=str)
    def cleanupSDK(self, path: str) -> str:
        """SDK temizliği yap (UnRen mod dosyalarını sil)."""
        if self._is_busy:
            return self.config.get_ui_text("app_busy", "Another operation is in progress...")

        self._set_busy(True)
        # We must run this in a thread to avoid main thread blocking
        threading.Thread(target=self._run_cleanup_thread, args=(path,), daemon=True).start()
        return self.config.get_ui_text("msg_task_started", "Operation started in background...")

    def _run_cleanup_thread(self, path):
        try:
            path = self._normalize_path(path)
            project_dir = os.path.dirname(path) if os.path.isfile(path) else path
            game_dir = os.path.join(project_dir, 'game') if os.path.isdir(os.path.join(project_dir, 'game')) else project_dir
            
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
                if os.path.exists(filepath):
                    os.remove(filepath)
                    deleted_count += 1
            
            msg = self.config.get_ui_text("msg_sdk_cleanup_success", f"Cleanup completed. {deleted_count} files removed.").replace("{count}", str(deleted_count))
            self.logMessage.emit("success", msg)
        except Exception as e:
            self.logMessage.emit("error", f"{self.config.get_ui_text('error', 'Error')}: {str(e)}")
        finally:
            self._set_busy(False)

    @pyqtSlot()
    def runUnRen(self):
        """UnRen arayüzünü aç veya işlemi başlat (Tools page shortcut)."""
        if not self._project_path:
            self.warningMessage.emit(self.config.get_ui_text("warning", "Warning"), self.config.get_ui_text("select_game_folder", "Please select the game folder first."))
            return
        
        if self._is_busy:
            self.warningMessage.emit(self.config.get_ui_text("warning", "Warning"), self.config.get_ui_text("app_busy", "Another operation is in progress..."))
            return

        self.logMessage.emit("info", self.config.get_ui_text("msg_unren_requested", "UnRPA extraction requested..."))
        self._set_busy(True)
        threading.Thread(target=self._run_unren_thread, daemon=True).start()

    def _run_unren_thread(self):
        try:
            result = self.extractRPA(self._project_path)
            self.logMessage.emit("info", result)
        finally:
            self._set_busy(False)

    @pyqtSlot()
    def runHealthCheck(self):
        """Sağlık kontrolünü başlat."""
        if not self._project_path:
            self.warningMessage.emit(self.config.get_ui_text("warning", "Warning"), self.config.get_ui_text("select_game_folder", "Please select the game folder first."))
            return
        
        if self._is_busy: return

        self.logMessage.emit("info", self.config.get_ui_text("log_health_check_analyzing", "Starting Health Check..."))
        self._set_busy(True)
        threading.Thread(target=self._run_health_check_thread, daemon=True).start()
        
    def _run_health_check_thread(self):
        try:
            self.logMessage.emit("info", self.config.get_ui_text("log_health_check_analyzing"))
            time.sleep(1)
            
            # Use directory if file selected
            base_dir = self._project_path
            if os.path.isfile(base_dir):
                base_dir = os.path.dirname(base_dir)
                
            self.logMessage.emit("info", self.config.get_ui_text("log_health_check_verifying"))
            report = self.healthCheck(base_dir)
            self.logMessage.emit("success", self.config.get_log_text("log_health_check_success", report=report))
        except Exception as e:
            self.logMessage.emit("error", self.config.get_ui_text("msg_error_health_check", "Health check error: {error}").replace("{error}", str(e)))
        finally:
            self._set_busy(False)
        
    @pyqtSlot()
    def runFontCheck(self):
        """Font kontrolünü başlat."""
        if not self._project_path:
            self.warningMessage.emit(self.config.get_ui_text("warning", "Warning"), self.config.get_ui_text("select_game_folder", "Please select the game folder first."))
            return
            
        if self._is_busy: return

        target_lang = self.config.translation_settings.target_language
        self.logMessage.emit("info", self.config.get_log_text("log_font_check_testing", lang=target_lang.upper()))
        
        # Simüle edilmiş aşamalı kontrol
        self._set_busy(True)
        threading.Thread(target=self._run_font_check_thread, args=(target_lang,), daemon=True).start()

    def _run_font_check_thread(self, lang):
        try:
            lang = lang.lower()
            time.sleep(1)
            self.logMessage.emit("info", self.config.get_ui_text("log_font_check_starting"))
            time.sleep(2)
            
            # Daha kapsamlı dil bazlı kontrol mantığı
            if any(x in lang for x in ["tr", "turkish"]):
                self.logMessage.emit("warning", self.config.get_ui_text("log_font_check_risk_tr"))
            elif any(x in lang for x in ["ru", "russian", "uk", "ukrainian"]):
                self.logMessage.emit("warning", self.config.get_ui_text("log_font_check_warn_ru"))
            elif any(x in lang for x in ["ar", "arabic", "fa", "persian", "he", "hebrew"]):
                self.logMessage.emit("error", self.config.get_ui_text("log_font_check_error_rtl"))
            elif any(x in lang for x in ["zh", "chinese", "ja", "japanese", "ko", "korean"]):
                self.logMessage.emit("error", self.config.get_ui_text("log_font_check_error_cjk"))
            else:
                self.logMessage.emit("success", self.config.get_log_text("log_font_check_success", lang=lang.upper()))
            
        except Exception as e:
            self.logMessage.emit("error", self.config.get_ui_text("msg_error_font_check", "Font check error: {error}").replace("{error}", str(e)))
        finally:
            self._set_busy(False)

    @pyqtSlot()
    def autoInjectFont(self):
        """Uyumlu fontu otomatik indir ve enjekte et."""
        if not self._project_path:
            self.warningMessage.emit(self.config.get_ui_text("warn_title", "Warning"), self.config.get_ui_text("select_game_folder", "Please select the game folder first."))
            return
            
        if self._is_busy: return

        target_lang = self.config.translation_settings.target_language or "turkish"
        
        # Kullanıcı onayı gerekebilir ama şimdilik direkt işlem yapılıyor çünkü araçlar menüsünden çağrılacak
        self.logMessage.emit("info", self.config.get_ui_text("log_font_inject_start", "Auto font injection started for {lang}...").replace("{lang}", target_lang))
        
        self._set_busy(True)
        threading.Thread(target=self._run_font_inject_thread, args=(target_lang, None), daemon=True).start()

    @pyqtSlot(str)
    def manualInjectFont(self, font_name: str):
        """Kullanıcının seçtiği fontu indir ve enjekte et."""
        if not self._project_path:
            self.warningMessage.emit(self.config.get_ui_text("warn_title", "Warning"), self.config.get_ui_text("select_game_folder", "Please select the game folder first."))
            return
            
        if self._is_busy: return
        
        if not font_name:
            return

        target_lang = self.config.translation_settings.target_language or "turkish"
        
        self.logMessage.emit("info", self.config.get_ui_text("log_font_inject_start", "Starting font injection...").replace("{lang}", f"{target_lang} ({font_name})"))
        
        self._set_busy(True)
        threading.Thread(target=self._run_font_inject_thread, args=(target_lang, font_name), daemon=True).start()

    @pyqtSlot(result=list)
    def getGoogleFontsList(self) -> list:
        """Kullanılabilir Google fontlarını döndür."""
        try:
            from src.utils.font_injector import FontInjector
            injector = FontInjector()
            return injector.get_available_fonts()
        except Exception:
            return ["Roboto", "Noto Sans", "Open Sans"] # Fallback

    def _run_font_inject_thread(self, lang, force_font=None):
        try:
            from src.utils.font_injector import FontInjector
            injector = FontInjector()
            
            # Proje yolunu al (eğer dosya ise klasöre çevir)
            base_dir = self._project_path
            if os.path.isfile(base_dir):
                base_dir = os.path.dirname(base_dir)
            
            # İşlemi yap (force_font parametresiyle)
            result = injector.inject_font(base_dir, lang, force_font_family=force_font)
            
            # Localization logic
            # result['ui_key'] is the translation key
            # result['ui_args'] are the parameters for python .format()
            ui_key = result.get("ui_key", "log_font_inject_error")
            ui_args = result.get("ui_args", {})
            fallback_msg = result.get("message", "An error occurred")
            
            # Get template from config using the key
            msg_template = self.config.get_ui_text(ui_key, fallback_msg)
            
            # Format the message (safely)
            try:
                final_msg = msg_template.format(**ui_args)
            except Exception as e:
                # Fallback if format fails (missing keys in json or args)
                final_msg = fallback_msg + f" (Loc err: {e})"

            if result["success"]:
                self.logMessage.emit("success", final_msg)
            else:
                self.logMessage.emit("error", final_msg)
                
        except Exception as e:
            self.logMessage.emit("error", self.config.get_ui_text("log_font_inject_critical_error", "Font injection critical error: {error}").replace("{error}", str(e)))
        finally:
            self._set_busy(False)

    @pyqtSlot(str, result=str)
    def healthCheck(self, path: str) -> str:
        """Oyun sağlığını kontrol et."""
        path = self._normalize_path(path)
        try:
            from src.tools.health_check import run_health_check
            report = run_health_check(path, verbose=False)
            return report.summary()
        except Exception as e:
            return f"{self.config.get_ui_text('error', 'Error')}: {str(e)}"

    @pyqtSlot(str, result=str)
    def fontCheck(self, path: str) -> str:
        """Font uyumluluğunu kontrol et."""
        path = self._normalize_path(path)
        try:
            from src.tools.font_helper import check_font_for_project
            summary = check_font_for_project(path, "tr", verbose=False)
            return self.config.get_ui_text("font_check_summary", "Checked: {total}\nOK: {comp}\nIssue: {incomp}").format(
                total=summary['fonts_checked'],
                comp=summary['compatible_fonts'],
                incomp=summary['incompatible_fonts']
            )
        except Exception as e:
            return f"{self.config.get_ui_text('error', 'Error')}: {str(e)}"
    
    @pyqtSlot(result=str)
    def getLastProjectPath(self) -> str:
        """Son kullanılan proje yolunu getir."""
        return self.config.app_settings.last_input_directory or ""

    @pyqtSlot(str)
    def setProjectPath(self, path: str):
        """Proje klasörünü ayarla."""
        path = self._normalize_path(path)
        # Replace OS-specific separators
        path = os.path.normpath(path)
        
        self.config.app_settings.last_input_directory = path
        self._project_path = path  # Update internal state
        self.config.save_config()
        self.logMessage.emit("info", self.config.get_log_text("log_project_path_set", path=path))

        # Validate
        project_dir = os.path.dirname(path) if os.path.isfile(path) else path
        
        # Check for 'game' or 'Game' directory (Case-sensitivity on Linux)
        game_dir = os.path.join(project_dir, 'game')
        if not os.path.isdir(game_dir):
            alt_game_dir = os.path.join(project_dir, 'Game')
            if os.path.isdir(alt_game_dir):
                game_dir = alt_game_dir

        if os.path.isdir(game_dir):
            self.logMessage.emit("info", "✅ " + self.config.get_ui_text("valid_renpy_project", "Valid Ren'Py project"))
        else:
            self.logMessage.emit("warning", "⚠️ " + self.config.get_ui_text("game_folder_not_found", "game/ folder not found"))

        # Reload cache for the new project (Async)
        self._update_cache_path_async()
    
    @pyqtSlot(str)
    def setEngine(self, engine: str):
        """Çeviri motorunu ayarla ve başlat."""
        changed = self._selected_engine != engine
        self._selected_engine = engine
        self.config.translation_settings.selected_engine = engine
        self.config.save_config()
        if changed:
            self.engineChanged.emit()
        self.logMessage.emit("info", self.config.get_log_text("log_engine_selected", engine=engine))

        requested_batch = getattr(self.config.translation_settings, 'max_batch_size', 100)
        effective_batch = get_effective_batch_size(requested_batch, engine)
        cap = get_engine_batch_size_cap(engine)
        if cap is not None and effective_batch != requested_batch:
            self.logMessage.emit(
                "info",
                self.config.get_log_text(
                    'log_batch_size_engine_cap_applied',
                    'Requested batch size {requested} exceeds the effective limit for {engine}; using {effective} (cap: {cap}).',
                    requested=requested_batch,
                    engine=engine,
                    effective=effective_batch,
                    cap=cap,
                ),
            )
        
        # Trigger async initialization
        self.update_translation_engine()

        # Show warnings for AI engines
        if engine in ["openai", "gemini", "deepseek", "local_llm"]:
            self.warningMessage.emit(
                self.config.get_ui_text("warning", "⚠️ Warning"),
                self.config.get_ui_text("ai_censorship_warning", "AI models may apply censorship or run slowly.")
            )

    @pyqtSlot()
    def update_translation_engine(self):
        """Update translation engine based on current settings (Async)."""
        engine_str = getattr(self.config.translation_settings, 'selected_engine', "google")
        use_proxy = getattr(self.config.proxy_settings, 'enabled', False)
        
        self.logger.info(f"Initializing translation engine: {engine_str} (Proxy: {use_proxy})")
        
        # Translate UI text for loading message
        msg = self.config.get_ui_text("msg_loading_ai", "Loading AI module and libraries...")
        
        # Start async initialization
        self._set_initializing(True, msg)
        
        def run_setup():
            try:
                # Convert string to enum
                from src.core.translator import TranslationEngine
                try:
                    engine_enum = TranslationEngine(engine_str)
                except ValueError:
                    engine_enum = TranslationEngine.GOOGLE

                self._setup_engine(engine_enum, use_proxy)
                
                # Success
                self.logMessage.emit("info", self.config.get_log_text("log_engine_initialized", engine=engine_str))
            except Exception as e:
                self.logger.error(f"Error initializing engine {engine_str}: {e}")
                import traceback
                traceback.print_exc()
                self.logMessage.emit("error", self.config.get_log_text("log_engine_init_failed", error=str(e)))
            finally:
                # Reset state on main thread
                # Since we are in a thread, we should ideally use QMetaObject.invokeMethod, 
                # but PyQt signals/properties are thread-safe for emitting.
                # To be 100% safe for property updates affecting UI:
                self._set_initializing(False, "")

        threading.Thread(target=run_setup, daemon=True).start()
    
    @pyqtSlot(result=str)
    def getSourceLanguage(self) -> str:
        return self._source_language

    @pyqtSlot(str)
    def setSourceLanguage(self, lang: str):
        """Kaynak dili ayarla."""
        self._source_language = lang
        self.config.translation_settings.source_language = lang
        self.config.save_config()
    @pyqtSlot(result=str)
    def getTargetLanguage(self) -> str:
        return self._target_language

    @pyqtSlot(str)
    def setTargetLanguage(self, lang: str):
        """Hedef dili ayarla."""
        self._target_language = lang
        self.config.translation_settings.target_language = lang
        self.config.save_config()
        # Reload cache for the new language (Async to avoid UI freeze)
        self._update_cache_path_async()

    def _update_cache_path_async(self):
        """Starts async cache update."""
        threading.Thread(target=self._update_cache_path, daemon=True).start()

    def _update_cache_path(self):
        """Proje veya dil değiştiğinde cache dosyasını yeniden yükle (Background Thread)."""
        if not self._project_path or not self._target_language:
            return

        try:
            cache_file = self._get_current_cache_file()

            # Always reset before loading so project/language switches never leak stale entries.
            self.translation_manager._cache.clear()
            self.translation_manager.cache_hits = 0
            self.translation_manager.cache_misses = 0

            if cache_file and os.path.exists(cache_file):
                self.translation_manager.load_cache(cache_file)

        except Exception as e:
            self.logger.error(f"Failed to update cache path: {e}")
    
    @pyqtSlot(result=list)
    def getGlossaryItems(self) -> list:
        """Sözlük öğelerini getir."""
        return [{"source": k, "target": v, "notes": ""} for k, v in self.config.glossary.items()]

    @pyqtSlot(str, str)
    def addGlossaryItem(self, source: str, target: str):
        """Sözlük öğesi ekle."""
        if not source: return
        self.config.glossary[source] = target
        self.config.save_glossary()

    @pyqtSlot(str)
    def removeGlossaryItem(self, source: str):
        """Sözlük öğesi sil."""
        if source in self.config.glossary:
            del self.config.glossary[source]
            self.config.save_glossary()

    @pyqtSlot(result=str)
    def extractGlossaryTerms(self) -> str:
        """Projeden terimleri otomatik çıkar."""
        if not self._project_path:
            return self.config.get_ui_text("glossary_extract_no_project", "Select a project first.")
            
        try:
            from src.tools.glossary_extractor import GlossaryExtractor
            extractor = GlossaryExtractor()
            terms = extractor.extract_from_directory(self._project_path, min_occurrence=3)
            
            added = 0
            for term in terms.keys():
                if term not in self.config.glossary:
                    self.config.glossary[term] = ""
                    added += 1
            
            if added > 0:
                self.config.save_glossary()
                return self.config.get_ui_text("msg_glossary_extracted_success", f"{added} yeni terim eklendi.").replace("{count}", str(added))
            return self.config.get_ui_text("msg_glossary_extracted_fail", "No new terms found.")
        except ImportError:
            return self.config.get_ui_text("glossary_extractor_not_found", "GlossaryExtractor module not found.")
        except Exception as e:
            return f"{self.config.get_ui_text('error', 'Hata')}: {str(e)}"

    @pyqtSlot()
    def translateEmptyGlossaryItems(self):
        """Boş sözlük terimlerini Google Translate ile doldur (Threadli)."""
        threading.Thread(target=self._translate_glossary_thread, daemon=True).start()

    def _translate_glossary_thread(self):
        try:
            import requests
            empty_keys = [k for k, v in self.config.glossary.items() if not v]
            if not empty_keys:
                self.logMessage.emit("info", self.config.get_ui_text("msg_glossary_translate_no_empty", "No empty terms to translate."))
                return

            self.logMessage.emit("info", self.config.get_ui_text("msg_glossary_translating", "Translating {count} terms...").replace("{count}", str(len(empty_keys))))
            
            count = 0
            for key in empty_keys:
                try:
                    # Simple sync Google Translate call
                    url = "https://translate.googleapis.com/translate_a/single"
                    params = {
                        "client": "gtx", "sl": "auto", "tl": self.config.translation_settings.target_language, 
                        "dt": "t", "q": key
                    }
                    data = requests.get(url, params=params, timeout=5).json()
                    if data and isinstance(data, list) and len(data) > 0:
                        first = data[0]
                        if isinstance(first, list) and len(first) > 0 and isinstance(first[0], list) and len(first[0]) > 0:
                            self.config.glossary[key] = first[0][0]
                            count += 1
                except Exception:
                    pass
            
            if count > 0:
                self.config.save_glossary()
                self.logMessage.emit("success", self.config.get_ui_text("msg_glossary_translate_success", "{count} terms translated and saved.").replace("{count}", str(count)))
                # Refresh UI signal needed here if we were strictly MVVM, 
                # but QML will refresh on next getGlossaryItems call or we can emit a signal.
            else:
                self.logMessage.emit("warning", self.config.get_ui_text("msg_glossary_translate_fail", "No terms could be translated."))
                
        except Exception as e:
            self.logMessage.emit("error", f"Glossary translation error: {e}")

    @pyqtSlot()
    def fillEmptyGlossaryWithSource(self):
        """Boş çevirileri kaynak metinle doldur."""
        count = 0
        for k, v in self.config.glossary.items():
            if not v:
                self.config.glossary[k] = k
                count += 1
        
        if count > 0:
            self.config.save_glossary()
            self.logMessage.emit("success", self.config.get_ui_text("msg_glossary_fill_source_success", "{count} terms filled with source.").replace("{count}", str(count)))
        else:
            self.logMessage.emit("info", self.config.get_ui_text("msg_glossary_translate_no_empty", "No empty terms to fill."))

    @pyqtSlot()
    def generateRuntimeHook(self):
        """Runtime Hook dosyasını oluştur (Çevirileri zorla yükle)."""
        if not self._project_path:
            self.warningMessage.emit(self.config.get_ui_text("warn_title", "Warning"), self.config.get_ui_text("select_game_folder", "Please select the game folder first."))
            return
            
        try:
            self.logMessage.emit("info", self.config.get_ui_text("log_hook_preparing"))
            # Fix: If project_path is a file (the exe), get the directory
            base_dir = self._project_path
            if os.path.isfile(base_dir):
                base_dir = os.path.dirname(base_dir)
                
            game_dir = os.path.join(base_dir, "game")
            if not os.path.exists(game_dir):
                self.logMessage.emit("error", self.config.get_ui_text("error_hook_game_not_found"))
                return

            self.logMessage.emit("info", self.config.get_ui_text("log_hook_configuring"))
            
            # Ren'Py native dil koduna çevir
            target_lang = self.config.translation_settings.target_language or "turkish"
            
            # ISO -> Native mapping
            from src.core.translation_pipeline import RENPY_TO_API_LANG
            reverse_lang_map = {v.lower(): k for k, v in RENPY_TO_API_LANG.items()}
            renpy_lang = reverse_lang_map.get(target_lang.lower(), target_lang)
            
            # 1. strings.json Oluştur (Use pipeline's generator to avoid code duplication)
            try:
                from src.core.tl_parser import TLParser
                from src.core.translation_pipeline import TranslationPipeline
                
                tl_dir = os.path.join(game_dir, "tl")
                if os.path.exists(tl_dir):
                    lang_dir = os.path.join(tl_dir, renpy_lang)
                    if os.path.isdir(lang_dir):
                        # Use TLParser + pipeline's _generate_strings_json (DRY)
                        tl_parser = TLParser()
                        tl_files = tl_parser.parse_directory(tl_dir, renpy_lang)
                        
                        # Create pipeline instance just to use _generate_strings_json
                        pipeline = TranslationPipeline(self.config, self.translation_manager)
                        pipeline._generate_strings_json(tl_files, lang_dir)
                        self.logMessage.emit('info', self.config.get_ui_text('log_strings_json_generated'))
            except Exception as json_err:
                self.logger.warning(f"Failed to generate strings.json in backend: {json_err}")

            # 2. Hook Dosyasını Yaz
            hook_content = render_runtime_hook(
                renpy_lang,
                runtime_string_diagnostics=getattr(
                    self.config.translation_settings,
                    "runtime_string_diagnostics",
                    False,
                ),
            )
            
            hook_filename = "zzz_renlocalizer_runtime.rpy"
            hook_path = os.path.join(game_dir, hook_filename)
            
            self.logMessage.emit("info", self.config.get_ui_text("log_hook_writing").replace("{filename}", hook_filename))
            
            with open(hook_path, "w", encoding="utf-8") as f:
                f.write(hook_content)
            
            self.logMessage.emit("success", self.config.get_ui_text("log_hook_installed").replace("{filename}", hook_filename))
            return True
            
        except Exception as e:
            self.logMessage.emit("error", f"Hook error: {str(e)}")
            self.logger.error(f"Error generating hook: {e}")
            return False
            

    @pyqtSlot(str, str, str, str, bool)
    def startTLTranslation(self, tl_path: str, target_lang: str, source_lang: str, engine: str, use_proxy: bool):
        """Mevcut bir TL klasörünü çevirmeye başla."""
        tl_path = self._normalize_path(tl_path)
        self.logMessage.emit("info", self.config.get_ui_text("log_tl_started"))
        self.logMessage.emit("info", self.config.get_log_text("log_tl_folder", folder=os.path.basename(tl_path)))
        self.logMessage.emit("info", self.config.get_log_text("log_tl_info", engine=engine.upper(), lang=target_lang.upper()))
        threading.Thread(
            target=self._run_tl_translation_thread, 
            args=(tl_path, target_lang, source_lang, engine, use_proxy),
            daemon=True
        ).start()

    def _run_tl_translation_thread(self, tl_path, target_lang, source_lang, engine_str, use_proxy):
        try:
            from src.core.translation_pipeline import TranslationPipeline
            engine = self._get_engine_enum(engine_str)
            
            pipeline = TranslationPipeline(self.config, self.translation_manager)
            pipeline.log_message.connect(self.logMessage)
            pipeline.progress_updated.connect(self._on_progress_updated)
            
            result = pipeline.translate_existing_tl(
                tl_path, target_lang, source_lang, engine, use_proxy
            )
            
            if result.success:
                self.logMessage.emit("success", result.message)
            else:
                self.logMessage.emit("error", result.message)
                
        except Exception as e:
            self.logMessage.emit("error", self.config.get_ui_text("msg_error_tl_translate", "TL translation error: {error}").replace("{error}", str(e)))

    def _get_engine_enum(self, engine_str: str) -> TranslationEngine:
        """String engine adını enum'a çevir."""
        from src.core.translator import TranslationEngine
        mapping = {
            "google": TranslationEngine.GOOGLE,
            "deepl": TranslationEngine.DEEPL,
            "openai": TranslationEngine.OPENAI,
            "gemini": TranslationEngine.GEMINI,
            "local_llm": TranslationEngine.LOCAL_LLM,
            "libretranslate": TranslationEngine.LIBRETRANSLATE,
            "yandex": TranslationEngine.YANDEX,
            "pseudo": TranslationEngine.PSEUDO,
        }
        return mapping.get(engine_str, TranslationEngine.GOOGLE)
    
    @pyqtSlot()
    def startTranslation(self):
        """Çeviri işlemini başlat."""
        if not self._project_path:
            self.logMessage.emit("error", self.config.get_ui_text("please_select_exe", "Please select a game"))
            return
        
        if self._is_translating:
            return
        
        self._is_translating = True
        self.translationStarted.emit()
        
        try:
            # Get engine enum
            engine = self._get_engine_enum(self._selected_engine)
            use_proxy = getattr(self.config.proxy_settings, "enabled", False)
            
            # Setup engine-specific translators
            self._setup_engine(engine, use_proxy)
            
            # Create pipeline
            self.pipeline = TranslationPipeline(self.config, self.translation_manager)
            self.pipeline.configure(
                game_exe_path=self._project_path,
                target_language=self._target_language,
                source_language=self._source_language,
                engine=engine,
                auto_unren=self.config.app_settings.unren_auto_download,
                use_proxy=use_proxy
            )
            
            # Connect signals
            self.pipeline.stage_changed.connect(self._on_stage_changed)
            self.pipeline.progress_updated.connect(self._on_progress_updated)
            self.pipeline.log_message.connect(self._on_log_message)
            self.pipeline.finished.connect(self._on_pipeline_finished)
            self.pipeline.show_warning.connect(self._on_show_warning)
            
            self.logMessage.emit("info", self.config.get_ui_text("pipeline_starting", "Pipeline starting..."))
            
            # Start worker
            self.pipeline_worker = PipelineWorker(self.pipeline)
            self.pipeline_worker.start()
            
        except Exception as e:
            self.logMessage.emit("error", self.config.get_ui_text("msg_error_init", "Initialization error: {error}").replace("{error}", str(e)))
            self._is_translating = False
            self.translationFinished.emit(False, str(e))
    
    def _setup_engine(self, engine: TranslationEngine, use_proxy: bool):
        """Initialize selected translation engine."""
        # Local imports
        from src.core.ai_translator import OpenAITranslator, GeminiTranslator, LocalLLMTranslator

        ts = self.config.translation_settings
        self.translation_manager.max_retries = ts.max_retries
        self.translation_manager.max_batch_size = ts.max_batch_size
        self.translation_manager.set_max_concurrency(ts.max_concurrent_threads)
        
        self.translation_manager.set_max_concurrency(ts.max_concurrent_threads)
        
        # Google Translate is always available as fallback, no heavy import needed
        # self.translation_manager.add_translator(...) # Already added in init
        
        if engine == TranslationEngine.OPENAI:
            if not self.config.api_keys.openai_api_key:
                raise ValueError(self.config.get_ui_text("error_api_key_missing", "API Key Missing").format(engine="OpenAI"))
                
            self.translation_manager.add_translator(
                TranslationEngine.OPENAI,
                OpenAITranslator(
                    api_key=self.config.api_keys.openai_api_key,
                    model=ts.openai_model or "gpt-3.5-turbo",
                    base_url=ts.openai_base_url,
                    proxy_manager=self.proxy_manager if use_proxy else None,
                    config_manager=self.config,
                    temperature=ts.ai_temperature,
                    timeout=ts.ai_timeout,
                    max_tokens=ts.ai_max_tokens
                )
            )
        elif engine == TranslationEngine.LOCAL_LLM:
            self.translation_manager.add_translator(
                TranslationEngine.LOCAL_LLM,
                LocalLLMTranslator(
                    model=ts.local_llm_model or "llama3.2",
                    base_url=ts.local_llm_url or "http://localhost:11434/v1",
                    proxy_manager=self.proxy_manager if use_proxy else None,
                    config_manager=self.config,
                    temperature=ts.ai_temperature,
                    timeout=getattr(ts, 'local_llm_timeout', 300),
                    max_tokens=ts.ai_max_tokens
                )
            )
        elif engine == TranslationEngine.GEMINI:
            if not self.config.api_keys.gemini_api_key:
                raise ValueError(self.config.get_ui_text("error_api_key_missing", "API Key Missing").format(engine="Gemini"))

            gemini_translator = GeminiTranslator(
                api_key=self.config.api_keys.gemini_api_key,
                model=ts.gemini_model or "gemini-pro",
                safety_level=ts.gemini_safety_settings,
                proxy_manager=self.proxy_manager if use_proxy else None,
                config_manager=self.config,
                temperature=ts.ai_temperature,
                timeout=ts.ai_timeout,
                max_tokens=ts.ai_max_tokens
            )
            fallback = GoogleTranslator(self.proxy_manager, self.config)
            gemini_translator.set_fallback_translator(fallback)
            self.translation_manager.add_translator(TranslationEngine.GEMINI, gemini_translator)

        elif engine == TranslationEngine.DEEPL:
            self.translation_manager.add_translator(
                TranslationEngine.DEEPL,
                DeepLTranslator(
                    api_key=self.config.api_keys.deepl_api_key,
                    proxy_manager=self.proxy_manager,
                    config_manager=self.config
                )
            )
        elif engine == TranslationEngine.LIBRETRANSLATE:
            from src.core.translator import LibreTranslateTranslator
            self.translation_manager.add_translator(
                TranslationEngine.LIBRETRANSLATE,
                LibreTranslateTranslator(
                    base_url=ts.libretranslate_url or "http://localhost:5000",
                    api_key=ts.libretranslate_api_key or "",
                    config_manager=self.config
                )
            )
    
    @pyqtSlot()
    def stopTranslation(self):
        """Çeviri işlemini durdur."""
        if self.pipeline:
            self.logMessage.emit("warning", self.config.get_ui_text("stop_requested", "Durdurma istendi..."))
            self.pipeline.stop()
            
            if self.pipeline_worker:
                try:
                    if not self.pipeline_worker.wait(5000):
                        self.logger.warning("Pipeline worker did not stop within 5s, terminating thread.")
                        self.pipeline_worker.terminate()
                        self.pipeline_worker.wait(2000)
                except Exception:
                    pass
                self.pipeline_worker = None
    
    @pyqtSlot(bool)
    def checkForUpdates(self, manual: bool = False):
        """Check for updates."""
        if not manual and not self.config.app_settings.check_for_updates:
            return

        self.logMessage.emit("info", self.config.get_ui_text("update_checking", "Checking for updates..."))
        threading.Thread(target=self._check_updates_thread, args=(manual,), daemon=True).start()

    def _check_updates_thread(self, manual: bool):
        try:
            from src.utils.update_checker import check_for_updates
            result = check_for_updates(self._version)
            
            if result.update_available:
                self.logMessage.emit("success", self.config.get_log_text("log_update_available", version=result.latest_version))
                # Emit update signal: current, latest, url
                self.updateAvailable.emit(
                    result.current_version,
                    result.latest_version,
                    result.release_url
                )
                if manual:
                     self.updateCheckFinished.emit(True, f"Update found: {result.latest_version}")
            else:
                msg = self.config.get_ui_text("update_check_no_update", "You are up to date.")
                if manual:
                     self.logMessage.emit("success", msg)
                     self.updateCheckFinished.emit(False, msg)
        except Exception as e:
            if manual:
                self.logMessage.emit("error", self.config.get_ui_text("log_update_check_failed", "Update check failed: {error}").replace("{error}", str(e)))
                self.updateCheckFinished.emit(False, f"Update Check Failed: {e}")

    # ========== HELPERS ==========

    @pyqtSlot(result=str)
    def get_app_path(self) -> str:
        """Uygulamanın çalıştığı dizini döndür (Dosya yolları için)."""
        return os.getcwd().replace("\\", "/")

    # ========== PIPELINE SIGNAL HANDLERS ==========
    
    def _on_stage_changed(self, stage: str, message: str):
        """Handle pipeline stage change."""
        stage_keys = {
            "idle": "stage_idle", "validating": "stage_validating",
            "unren": "stage_unren", "generating": "stage_generating",
            "parsing": "stage_parsing", "translating": "stage_translating",
            "saving": "stage_saving", "completed": "stage_completed",
            "error": "stage_error"
        }
        display_name = self.config.get_ui_text(stage_keys.get(stage, "stage_idle"), stage)
        self.stageChanged.emit(stage, display_name)
    
    def _on_progress_updated(self, current: int, total: int, text: str):
        """Handle translation progress update."""
        self.progressChanged.emit(current, total, text)
    
    def _on_log_message(self, level: str, message: str):
        """Handle log message from pipeline."""
        self.logMessage.emit(level, message)
    
    def _on_show_warning(self, title: str, message: str):
        """Show warning popup from pipeline."""
        self.warningMessage.emit(title, message)

    def _build_completion_summary(self, result) -> dict:
        """Build a user-friendly completion summary payload for the GUI."""
        review_note_count = 0
        diagnostic_path = ""
        if self.pipeline is not None:
            review_note_count = len(getattr(self.pipeline.diagnostic_report, 'coverage_warnings', []) or [])
            diagnostic_path = getattr(self.pipeline, '_last_diagnostic_path', '') or ''

        lines = [result.message]
        if review_note_count > 0:
            lines.append(
                self.config.get_ui_text(
                    'translation_complete_with_notes',
                    '{count} review note(s) are available in diagnostics.',
                ).format(count=review_note_count)
            )
        else:
            lines.append(
                self.config.get_ui_text(
                    'translation_complete_no_notes',
                    'No review notes were detected.',
                )
            )

        lines.append(
            self.config.get_ui_text(
                'translation_complete_hint',
                "Tip: If the game doesn't start in the translated language, press Shift+L to switch.",
            )
        )

        return {
            'title': self.config.get_ui_text('translation_complete_title', 'Translation Complete'),
            'message': '\n'.join(line for line in lines if line),
            'output_path': result.output_path or '',
            'diagnostic_path': diagnostic_path,
            'review_note_count': review_note_count,
        }

    def _on_pipeline_finished(self, result):
        """Handle pipeline completion."""
        self._is_translating = False
        
        if result.success:
            self.logMessage.emit("success", f"✅ {result.message}")
            if result.stats:
                self.statsReady.emit(
                    result.stats.get('total', 0),
                    result.stats.get('translated', 0),
                    result.stats.get('untranslated', 0)
                )
        else:
            self.logMessage.emit("error", f"❌ {result.message}")
            if result.error:
                self.logMessage.emit("error", f"Detail: {result.error}")
        
        if self.config.translation_settings.auto_generate_hook and result.success:
            self.generateRuntimeHook()

        if result.success:
            completion = self._build_completion_summary(result)
            self.completionSummary.emit(
                completion['title'],
                completion['message'],
                completion['output_path'],
                completion['diagnostic_path'],
                completion['review_note_count'],
            )

        self.translationFinished.emit(result.success, result.message)
        
        # Cleanup
        if self.pipeline_worker:
            try:
                if not self.pipeline_worker.wait(2000):
                    self.pipeline_worker.terminate()
                    self.pipeline_worker.wait(1000)
            except Exception:
                pass
            self.pipeline_worker = None
        
        # Close async sessions
        try:
            threading.Thread(
                target=lambda: asyncio.run(self.translation_manager.close_all()),
                daemon=True
            ).start()
        except Exception:
            pass

    @pyqtSlot(str, str, result=str)
    def exportGlossary(self, path: str, format_type: str) -> str:
        """Export glossary to file."""
        path = self._normalize_path(path)
        try:
            # Ensure correct extension
            if not path.lower().endswith(f".{format_type}"):
                path += f".{format_type}"
                
            export_glossary_to_file(self.config.glossary, path)
            msg = self.config.get_ui_text("glossary_export_success", "Glossary exported successfully to {path}").format(path=path)
            self.logMessage.emit("success", msg)
            return "" # Empty string = success
        except Exception as e:
            err = str(e)
            self.logMessage.emit("error", self.config.get_ui_text("log_export_failed", "Export failed: {error}").replace("{error}", err))
            return err
            
    @pyqtSlot(str, result=str)
    def importGlossary(self, path: str) -> str:
        """Import glossary from file (merge with existing)."""
        path = self._normalize_path(path)
        try:
            new_term_count = 0
            updated_term_count = 0
            
            imported_data = import_glossary_from_file(path)
            
            for source, target in imported_data.items():
                if source in self.config.glossary:
                    if self.config.glossary[source] != target:
                         self.config.glossary[source] = target
                         updated_term_count += 1
                else:
                    self.config.glossary[source] = target
                    new_term_count += 1
            
            if new_term_count > 0 or updated_term_count > 0:
                self.config.save_glossary()
                msg = self.config.get_ui_text("glossary_import_success", "Imported: {new} new, {updated} updated.").format(
                    new=new_term_count, updated=updated_term_count
                )
                self.logMessage.emit("success", msg)
                return "" # Success
            else:
                msg = self.config.get_ui_text("glossary_import_no_change", "No changes made. File might be identical or empty.")
                self.logMessage.emit("info", msg)
                return msg

        except Exception as e:
            err = str(e)
            self.logMessage.emit("error", self.config.get_ui_text("log_import_failed", "Import failed: {error}").replace("{error}", err))
            return err

    # ========== CACHE EXPLORER SLOTS ==========

    @pyqtSlot(str, result=list)
    def getCacheEntries(self, filter_text: str = "") -> list:
        """Get flattened cache entries for UI."""
        entries = []
        filter_text = filter_text.lower()
        
        # cache key: (engine, sl, tl, text) -> val: TranslationResult
        # Accessing private member _cache for Explorer functionality
        # Need to be thread-safe if updated dynamically, but for UI view it's mostly fine
        # We'll take a snapshot
        
        try:
            # Refresh from the active cache file so the page stays aligned with
            # the current project/language after data-dir/path changes.
            self._update_cache_path()
            cache_snapshot = list(self.translation_manager._cache.items())
            
            # Sort by most recent (which are at the end of OrderedDict) -> reverse
            cache_snapshot.reverse()
            
            count = 0
            limit = 1000 # Hard limit for UI performance for now
            
            for key, val in cache_snapshot:
                engine, sl, tl, original = key
                translated = val.translated_text
                
                if filter_text:
                    if (filter_text not in original.lower() and 
                        filter_text not in translated.lower() and 
                        filter_text not in engine.lower()):
                        continue
                        
                entries.append({
                    "engine": engine,
                    "source_lang": sl,
                    "target_lang": tl,
                    "original": original,
                    "translated": translated
                })
                count += 1
                if count >= limit:
                    break
                    
            return entries
        except Exception as e:
            self.logMessage.emit("error", self.config.get_ui_text("log_cache_list_error", "Error listing cache: {error}").replace("{error}", str(e)))
            return []

    def _get_current_cache_file(self) -> Optional[str]:
        """Helper to get current cache file path based on settings."""
        if not self._project_path or not self._target_language:
            return None
            
        try:
            should_use_global_cache = getattr(self.config.translation_settings, 'use_global_cache', True)
            project_dir = os.path.dirname(self._project_path) if os.path.isfile(self._project_path) else self._project_path
            
            if should_use_global_cache:
                project_name = os.path.basename(project_dir.rstrip('/\\')) or "default_project"
                base_cache_dir = os.path.join(self.config.data_dir, getattr(self.config.translation_settings, 'cache_path', 'cache'))
                cache_dir = os.path.join(base_cache_dir, project_name, self._target_language)
            else:
                cache_dir = os.path.join(project_dir, 'game', 'tl', self._target_language)
                
            return os.path.join(cache_dir, "translation_cache.json")
        except Exception:
            return None

    @pyqtSlot(str, str, str, str, result=bool)
    def deleteCacheEntry(self, engine: str, source_lang: str, target_lang: str, original: str) -> bool:
        """Delete a specific cache entry."""
        key = (engine, source_lang, target_lang, original)
        if key in self.translation_manager._cache:
            del self.translation_manager._cache[key]
            
            cache_file = self._get_current_cache_file()
            if cache_file:
                self.translation_manager.save_cache(cache_file)
            return True
        return False

    @pyqtSlot(str, str, str, str, str, result=bool)
    def updateCacheEntry(self, engine: str, source_lang: str, target_lang: str, original: str, new_translation: str) -> bool:
        """Update a specific cache entry."""
        key = (engine, source_lang, target_lang, original)
        if key in self.translation_manager._cache:
            # Update the translated text
            res = self.translation_manager._cache[key]
            res.translated_text = new_translation
            
            cache_file = self._get_current_cache_file()
            if cache_file:
                self.translation_manager.save_cache(cache_file)
            return True
        return False

    @pyqtSlot(result=bool)
    def clearCache(self) -> bool:
        """Clear all cache."""
        try:
            self.translation_manager._cache.clear()
            
            cache_file = self._get_current_cache_file()
            if cache_file and os.path.exists(os.path.dirname(cache_file)):
                self.translation_manager.save_cache(cache_file)
                
            self.logMessage.emit("success", self.config.get_ui_text("log_cache_cleared", "Translation memory cleared."))
            return True
        except Exception as e:
            self.logMessage.emit("error", self.config.get_ui_text("log_cache_clear_error", "Error clearing cache: {error}").replace("{error}", str(e)))
            return False

    @pyqtSlot(result=int)
    def getCacheSize(self) -> int:
        return len(self.translation_manager._cache)

    # ========== v2.7.1 TOOL SLOTS ==========

    @pyqtSlot()
    def exportProject(self):
        """Export project as .rlproj archive."""
        def _run():
            try:
                from src.utils.project_io import export_project
                if not self._project_path:
                    self.logMessage.emit("error", self.config.get_ui_text("tool_project_export_no_project", "No project loaded. Please select a game folder first."))
                    return

                project_dir = os.path.dirname(self._project_path) if os.path.isfile(self._project_path) else self._project_path
                project_name = os.path.basename(project_dir.rstrip('/\\')) or "project"
                out_path = os.path.join(project_dir, f"{project_name}.rlproj")

                cache_data = None
                try:
                    cache_snapshot = dict(self.translation_manager._cache)
                    if cache_snapshot:
                        cache_data = {str(k): v.translated_text for k, v in cache_snapshot.items()}
                except Exception:
                    pass

                result = export_project(
                    config_manager=self.config,
                    output_path=out_path,
                    cache_data=cache_data,
                    include_api_keys=False,
                )
                self.logMessage.emit("success", self.config.get_ui_text("tool_project_export_success", "Project exported: {path}").format(path=result))
            except Exception as e:
                self.logMessage.emit("error", self.config.get_ui_text("tool_project_export_error", "Export failed: {error}").format(error=str(e)))

        threading.Thread(target=_run, daemon=True).start()

    @pyqtSlot()
    def importProject(self):
        """Import project from .rlproj archive."""
        def _run():
            try:
                from src.utils.project_io import import_project, apply_import
                if not self._project_path:
                    self.logMessage.emit("error", self.config.get_ui_text("tool_project_import_no_project", "No project loaded. Please select a game folder first."))
                    return

                project_dir = os.path.dirname(self._project_path) if os.path.isfile(self._project_path) else self._project_path

                # Find .rlproj files
                rlproj_files = list(Path(project_dir).glob("*.rlproj"))
                if not rlproj_files:
                    self.logMessage.emit("error", self.config.get_ui_text("tool_project_import_not_found", "No .rlproj file found in the game directory."))
                    return

                archive = str(rlproj_files[0])
                result = import_project(archive)
                if not result.ok:
                    self.logMessage.emit("error", f"Import failed: {'; '.join(result.warnings)}")
                    return

                messages = apply_import(result, self.config)
                for msg in messages:
                    self.logMessage.emit("info", msg)
                self.logMessage.emit("success", self.config.get_ui_text("tool_project_import_success", "Project imported successfully."))
            except Exception as e:
                self.logMessage.emit("error", self.config.get_ui_text("tool_project_import_error", "Import failed: {error}").format(error=str(e)))

        threading.Thread(target=_run, daemon=True).start()

    @pyqtSlot()
    def encryptTranslations(self):
        """Obfuscate translation output files."""
        def _run():
            try:
                from src.utils.translation_crypto import obfuscate_rpy_file
                if not self._project_path:
                    self.logMessage.emit("error", self.config.get_ui_text("tool_encrypt_no_project", "No project loaded. Please select a game folder first."))
                    return

                project_dir = os.path.dirname(self._project_path) if os.path.isfile(self._project_path) else self._project_path
                tl_dir = os.path.join(project_dir, "game", "tl")
                if not os.path.isdir(tl_dir):
                    self.logMessage.emit("error", self.config.get_ui_text("tool_encrypt_no_tl", "No 'game/tl' directory found."))
                    return

                count = 0
                for root_d, dirs, files in os.walk(tl_dir):
                    for f in files:
                        if f.endswith(".rpy") and not f.startswith("_rl_"):
                            fpath = os.path.join(root_d, f)
                            try:
                                obfuscate_rpy_file(fpath)
                                count += 1
                            except Exception as e:
                                self.logMessage.emit("warning", f"Skip {f}: {e}")

                self.logMessage.emit("success", self.config.get_ui_text("tool_encrypt_success", "{count} file(s) obfuscated.").format(count=count))
            except Exception as e:
                self.logMessage.emit("error", self.config.get_ui_text("tool_encrypt_error", "Encryption failed: {error}").format(error=str(e)))

        threading.Thread(target=_run, daemon=True).start()

    @pyqtSlot()
    def runTranslationLint(self):
        """Run translation lint on output files."""
        def _run():
            try:
                from src.tools.renpy_lint import lint_translation_output
                if not self._project_path:
                    self.logMessage.emit("error", self.config.get_ui_text("tool_lint_no_project", "No project loaded. Please select a game folder first."))
                    return

                project_dir = os.path.dirname(self._project_path) if os.path.isfile(self._project_path) else self._project_path
                tl_dir = os.path.join(project_dir, "game", "tl")
                if not os.path.isdir(tl_dir):
                    self.logMessage.emit("error", self.config.get_ui_text("tool_lint_no_tl", "No 'game/tl' directory found."))
                    return

                self.logMessage.emit("info", self.config.get_ui_text("tool_lint_running", "Running translation lint..."))
                report = lint_translation_output(tl_dir, game_dir=project_dir)

                if not report.issues:
                    self.logMessage.emit("success", self.config.get_ui_text("tool_lint_clean", "✓ No issues found! Translation files look clean."))
                else:
                    errors = sum(1 for i in report.issues if i.severity.value in ("error", "critical"))
                    warnings = sum(1 for i in report.issues if i.severity.value == "warning")
                    self.logMessage.emit("warning", self.config.get_ui_text("tool_lint_result", "Lint complete: {errors} error(s), {warnings} warning(s), {total} total issues.").format(
                        errors=errors, warnings=warnings, total=len(report.issues)
                    ))
                    for issue in report.issues[:20]:
                        self.logMessage.emit("info", f"[{issue.code}] {issue.file}:{issue.line} — {issue.message}")
                    if len(report.issues) > 20:
                        self.logMessage.emit("info", f"... and {len(report.issues) - 20} more issues.")
            except Exception as e:
                self.logMessage.emit("error", self.config.get_ui_text("tool_lint_error", "Lint failed: {error}").format(error=str(e)))

        threading.Thread(target=_run, daemon=True).start()

    @pyqtSlot()
    def packRPA(self):
        """Pack translation files into an RPA archive."""
        def _run():
            try:
                from src.utils.rpa_packer import pack_translations
                if not self._project_path:
                    self.logMessage.emit("error", self.config.get_ui_text("tool_rpa_pack_no_project", "No project loaded. Please select a game folder first."))
                    return

                project_dir = os.path.dirname(self._project_path) if os.path.isfile(self._project_path) else self._project_path
                tl_dir = os.path.join(project_dir, "game", "tl")
                if not os.path.isdir(tl_dir):
                    self.logMessage.emit("error", self.config.get_ui_text("tool_rpa_pack_no_tl", "No 'game/tl' directory found."))
                    return

                self.logMessage.emit("info", self.config.get_ui_text("tool_rpa_pack_running", "Packing translations into RPA archive..."))
                result = pack_translations(
                    tl_directory=tl_dir,
                    game_dir=os.path.join(project_dir, "game"),
                )

                if result:
                    self.logMessage.emit("success", self.config.get_ui_text("tool_rpa_pack_success", "RPA archive created: {path}").format(path=result))
                else:
                    self.logMessage.emit("warning", self.config.get_ui_text("tool_rpa_pack_empty", "No files found to pack."))
            except Exception as e:
                self.logMessage.emit("error", self.config.get_ui_text("tool_rpa_pack_error", "RPA packing failed: {error}").format(error=str(e)))

        threading.Thread(target=_run, daemon=True).start()

    # ==================== EXTERNAL TM (v2.7.3) ====================

    @pyqtSlot(str, str, str)
    def importExternalTM(self, tl_path: str, source_name: str, language: str):
        """Harici tl/ klasöründen TM import et."""
        if self._is_busy:
            self.warningMessage.emit(
                self.config.get_ui_text("warning", "Warning"),
                self.config.get_ui_text("app_busy", "Another operation is in progress...")
            )
            return

        tl_path = self._normalize_path(tl_path)
        tl_path = tl_path.replace("/", os.sep)

        if not source_name.strip():
            source_name = os.path.basename(os.path.dirname(tl_path)) or "Unknown"

        self.logMessage.emit("info", self.config.get_ui_text(
            "tm_import_started", "Importing Translation Memory from: {path}..."
        ).replace("{path}", tl_path))
        self._set_busy(True)
        threading.Thread(
            target=self._run_tm_import_thread,
            args=(tl_path, source_name, language),
            daemon=True
        ).start()

    def _run_tm_import_thread(self, tl_path: str, source_name: str, language: str):
        try:
            from src.tools.external_tm import ExternalTMStore
            tm_dir = str(os.path.join(self.config.data_dir, "tm"))
            store = ExternalTMStore(tm_dir=tm_dir)
            result = store.import_from_tl_directory(
                tl_lang_dir=tl_path,
                source_name=source_name,
                language=language,
                progress_callback=lambda c, t, m: self.logMessage.emit("debug", m)
            )

            if result.success:
                self.logMessage.emit("success", self.config.get_ui_text(
                    "tm_import_success",
                    "TM imported successfully: {count} entries from '{name}'"
                ).replace("{count}", str(result.imported)).replace("{name}", source_name))
                self.tmSourcesChanged.emit()

                details = []
                if result.skipped_empty > 0:
                    details.append(f"empty: {result.skipped_empty}")
                if result.skipped_same > 0:
                    details.append(f"same: {result.skipped_same}")
                if result.skipped_technical > 0:
                    details.append(f"technical: {result.skipped_technical}")
                if result.skipped_short > 0:
                    details.append(f"short: {result.skipped_short}")
                if result.skipped_duplicate > 0:
                    details.append(f"duplicate: {result.skipped_duplicate}")
                if details:
                    self.logMessage.emit("info", f"[TM] Skipped: {', '.join(details)}")
            else:
                self.logMessage.emit("error", self.config.get_ui_text(
                    "tm_import_failed", "TM import failed: {error}"
                ).replace("{error}", result.error))
        except Exception as e:
            self.logMessage.emit("error", f"TM import error: {e}")
        finally:
            self._set_busy(False)

    @pyqtSlot(result=list)
    def getAvailableTMSources(self) -> list:
        """tm/ klasöründeki mevcut TM kaynaklarını listele."""
        try:
            from src.tools.external_tm import ExternalTMStore
            tm_dir = str(os.path.join(self.config.data_dir, "tm"))
            store = ExternalTMStore(tm_dir=tm_dir)
            sources = store.list_available_sources()
            return [s.to_dict() for s in sources]
        except Exception as e:
            self.logger.warning(f"TM list error: {e}")
            return []

    @pyqtSlot(str, result=bool)
    def deleteTMSource(self, file_path: str) -> bool:
        """Bir TM kaynağını sil."""
        try:
            from src.tools.external_tm import ExternalTMStore
            tm_dir = str(os.path.join(self.config.data_dir, "tm"))
            store = ExternalTMStore(tm_dir=tm_dir)
            success = store.delete_source(file_path)
            if success:
                self.logMessage.emit("info", self.config.get_ui_text(
                    "tm_source_deleted", "TM source deleted."
                ))
                self.tmSourcesChanged.emit()
            return success
        except Exception as e:
            self.logMessage.emit("error", f"TM delete error: {e}")
            return False

    @pyqtSlot(str, str, result=bool)
    def renameTMSource(self, file_path: str, new_name: str) -> bool:
        """Bir TM kaynağının adını değiştirir."""
        try:
            from src.tools.external_tm import ExternalTMStore
            tm_dir = str(os.path.join(self.config.data_dir, "tm"))
            store = ExternalTMStore(tm_dir=tm_dir)
            success, msg = store.rename_source(file_path, new_name)
            if success:
                self.logMessage.emit("success", f"TM renamed: {msg}")
                self.tmSourcesChanged.emit()
            else:
                self.logMessage.emit("error", f"TM rename failed: {msg}")
            return success
        except Exception as e:
            self.logMessage.emit("error", f"TM rename error: {e}")
            return False

    @pyqtSlot(str, str, result=bool)
    def mergeTMSources(self, source_paths_json: str, new_name: str) -> bool:
        """Birden fazla TM kaynağını birleştirir."""
        import json as _json
        try:
            source_paths = _json.loads(source_paths_json)
            if len(source_paths) < 2:
                self.logMessage.emit("error", "Need at least 2 sources to merge")
                return False
            
            from src.tools.external_tm import ExternalTMStore
            tm_dir = str(os.path.join(self.config.data_dir, "tm"))
            store = ExternalTMStore(tm_dir=tm_dir)
            success, msg, new_path = store.merge_sources(source_paths, new_name)
            if success:
                self.logMessage.emit("success", f"TM merged: {msg}")
                self.tmSourcesChanged.emit()
            else:
                self.logMessage.emit("error", f"TM merge failed: {msg}")
            return success
        except Exception as e:
            self.logMessage.emit("error", f"TM merge error: {e}")
            return False

    @pyqtSlot(str, str, result=bool)
    def exportTMSource(self, file_path: str, export_path: str) -> bool:
        """Bir TM kaynağını yedekler."""
        try:
            from src.tools.external_tm import ExternalTMStore
            tm_dir = str(os.path.join(self.config.data_dir, "tm"))
            store = ExternalTMStore(tm_dir=tm_dir)
            success, msg = store.export_source(file_path, export_path)
            if success:
                self.logMessage.emit("success", f"TM exported: {msg}")
            else:
                self.logMessage.emit("error", f"TM export failed: {msg}")
            return success
        except Exception as e:
            self.logMessage.emit("error", f"TM export error: {e}")
            return False

    @pyqtSlot(result=bool)
    def getUseExternalTM(self) -> bool:
        """External TM aktif mi?"""
        return getattr(self.config.translation_settings, 'use_external_tm', False)

    @pyqtSlot(bool)
    def setUseExternalTM(self, enabled: bool):
        """External TM aç/kapa."""
        self.config.translation_settings.use_external_tm = enabled
        self.config.save_config()
        self.refreshUI()  # HomePage TM kartının görünürlüğünü güncelle

    @pyqtSlot(result=str)
    def getExternalTMSources(self) -> str:
        """Aktif TM kaynak yollarını JSON string olarak döndür."""
        return getattr(self.config.translation_settings, 'external_tm_sources', '[]')

    @pyqtSlot(str)
    def setExternalTMSources(self, sources_json: str):
        """Aktif TM kaynak yollarını ayarla."""
        self.config.translation_settings.external_tm_sources = sources_json
        self.config.save_config()

    @pyqtSlot(str, bool)
    def toggleTMSource(self, file_path: str, enabled: bool):
        """Tek bir TM kaynağını aktif/pasif yap."""
        import json as _json
        try:
            current = _json.loads(
                getattr(self.config.translation_settings, 'external_tm_sources', '[]')
            )
            if not isinstance(current, list):
                current = []

            if enabled and file_path not in current:
                current.append(file_path)
            elif not enabled and file_path in current:
                current.remove(file_path)

            self.config.translation_settings.external_tm_sources = _json.dumps(current)
            self.config.save_config()
        except Exception as e:
            self.logger.warning(f"TM toggle error: {e}")
