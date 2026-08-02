# -*- coding: utf-8 -*-
"""
SettingsBackend - Pluggable Settings Manager
============================================

Extracted from AppBackend. A plain-Python class that owns all setting
read/write logic, bridging ConfigManager and TranslationManager without
any Qt dependency.  Callers wire themselves via callbacks.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from src.core.translator import TranslationEngine, TranslationManager, GoogleTranslator
from src.utils.config import ConfigManager


class SettingsBackend:
    """All settings management moved out of AppBackend into a testable, Qt-free unit.

    The class talks directly to *config* (ConfigManager) and
    *translation_manager* (TranslationManager).  Every ``set_*`` call fires
    the registered **callbacks** (e.g. ``on_max_threads_changed``) so that
    the caller (AppBackend) can relay them to QML via PyQt signals.
    """

    # ── Constructor ────────────────────────────────────────────────────────

    def __init__(
        self,
        config: ConfigManager,
        translation_manager: TranslationManager,
        logger: Optional[logging.Logger] = None,
        engine_getter: Optional[Callable[[str], TranslationEngine]] = None,
    ) -> None:
        self.config = config
        self.translation_manager = translation_manager
        self.logger = logger or logging.getLogger(__name__)

        if engine_getter is None:
            engine_getter = self._engine_from_str
        self._engine_getter = engine_getter

        # Resolve initial engine
        cfg_engine = self.config.translation_settings.selected_engine or "google"
        self._selected_engine: TranslationEngine = self._engine_getter(cfg_engine)
        if self._selected_engine not in (
            TranslationEngine.GOOGLE,
            TranslationEngine.OPENAI,
            TranslationEngine.LOCAL_LLM,
            TranslationEngine.LIBRETRANSLATE,
            TranslationEngine.CUSTOM,
        ):
            self._selected_engine = TranslationEngine.GOOGLE

        # ── Callback registries ──────────────────────────────────────────
        self._callbacks: Dict[str, List[Callable]] = {
            # General
            "max_threads": [],
            "request_delay": [],
            "max_batch_size": [],
            "multi_endpoint": [],
            "lingva_fallback": [],
            "aggressive_retry": [],
            "use_cache": [],
            "check_for_updates": [],
            "rpyc_reader": [],
            "deep_scan": [],
            "selected_engine": [],
            # OpenAI
            "openai_api_key": [],
            "openai_model": [],
            "openai_base_url": [],
            # Local LLM
            "local_llm_url": [],
            "local_llm_model": [],
            # LibreTranslate
            "libretranslate_url": [],
            "libretranslate_api_key": [],
            # Custom endpoint
            "custom_endpoint_url": [],
            "custom_endpoint_api_key": [],
            # Gemini
            "gemini_api_key": [],
            "gemini_model": [],
            # Advanced AI
            "ai_temperature": [],
            "ai_timeout": [],
            "ai_max_tokens": [],
            "ai_batch_size": [],
            "ai_retry_count": [],
            "ai_concurrency": [],
            "ai_request_delay": [],
            "ai_custom_system_prompt": [],
            # Output mode
            "output_mode": [],
            # UI / theme / language
            "language": [],
            "theme": [],
            # Glossary
            "glossary": [],
        }

    # ── Callback helpers ────────────────────────────────────────────────────

    def on(self, event: str, cb: Callable) -> None:
        """Register a callback for the given event name."""
        if event in self._callbacks:
            self._callbacks[event].append(cb)

    def _emit(self, event: str, *args: Any) -> None:
        """Fire all registered callbacks for *event*."""
        for cb in self._callbacks.get(event, []):
            try:
                cb(*args)
            except Exception:
                self.logger.exception("SettingsBackend callback error [%s]", event)

    # ── Static helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _engine_from_str(engine_str: str) -> TranslationEngine:
        """Safely converts a string engine name to TranslationEngine enum."""
        mapping = {
            "google": TranslationEngine.GOOGLE,
            "openai": TranslationEngine.OPENAI,
            "local_llm": TranslationEngine.LOCAL_LLM,
            "deepseek": TranslationEngine.OPENAI,
            "libretranslate": TranslationEngine.LIBRETRANSLATE,
            "custom": TranslationEngine.CUSTOM,
        }
        return mapping.get(engine_str.lower(), TranslationEngine.GOOGLE)

    # ═══════════════════════════════════════════════════════════════════════════
    #  General Translation Settings
    # ═══════════════════════════════════════════════════════════════════════════

    def get_max_concurrent_threads(self) -> int:
        return self.config.translation_settings.max_concurrent_threads

    def set_max_concurrent_threads(self, val: int) -> None:
        self.config.translation_settings.max_concurrent_threads = max(1, int(val))
        self._emit("max_threads")

    def get_request_delay(self) -> float:
        return self.config.translation_settings.request_delay

    def set_request_delay(self, val: float) -> None:
        self.config.translation_settings.request_delay = max(0.0, float(val))
        self._emit("request_delay")

    def get_max_batch_size(self) -> int:
        return self.config.translation_settings.max_batch_size

    def set_max_batch_size(self, val: int) -> None:
        self.config.translation_settings.max_batch_size = max(1, int(val))
        self._emit("max_batch_size")

    def get_use_multi_endpoint(self) -> bool:
        return self.config.translation_settings.use_multi_endpoint

    def set_use_multi_endpoint(self, val: bool) -> None:
        self.config.translation_settings.use_multi_endpoint = bool(val)
        self._emit("multi_endpoint")

    def get_enable_lingva_fallback(self) -> bool:
        return self.config.translation_settings.enable_lingva_fallback

    def set_enable_lingva_fallback(self, val: bool) -> None:
        self.config.translation_settings.enable_lingva_fallback = bool(val)
        self._emit("lingva_fallback")

    def get_aggressive_retry(self) -> bool:
        return self.config.translation_settings.aggressive_retry_translation

    def set_aggressive_retry(self, val: bool) -> None:
        self.config.translation_settings.aggressive_retry_translation = bool(val)
        self._emit("aggressive_retry")

    def get_use_cache(self) -> bool:
        return self.config.translation_settings.use_cache

    def set_use_cache(self, val: bool) -> None:
        self.config.translation_settings.use_cache = bool(val)
        self.translation_manager.use_cache = bool(val)
        self._emit("use_cache")

    def get_check_for_updates(self) -> bool:
        return self.config.app_settings.check_for_updates

    def set_check_for_updates(self, val: bool) -> None:
        self.config.app_settings.check_for_updates = bool(val)
        self._emit("check_for_updates")

    def get_enable_rpyc_reader(self) -> bool:
        return self.config.translation_settings.enable_rpyc_reader

    def set_enable_rpyc_reader(self, val: bool) -> None:
        self.config.translation_settings.enable_rpyc_reader = bool(val)
        self._emit("rpyc_reader")

    def get_enable_deep_scan(self) -> bool:
        return self.config.translation_settings.enable_deep_scan

    def set_enable_deep_scan(self, val: bool) -> None:
        self.config.translation_settings.enable_deep_scan = bool(val)
        self._emit("deep_scan")

    # ═══════════════════════════════════════════════════════════════════════════
    #  Engine Selection
    # ═══════════════════════════════════════════════════════════════════════════

    def get_selected_engine(self) -> str:
        return self._selected_engine.value

    def set_selected_engine(self, engine_str: str) -> None:
        """Changes the active translation engine and persists to config."""
        new_engine = self._engine_getter(engine_str)
        self.config.translation_settings.selected_engine = engine_str.lower()
        self.config.save_config()
        if new_engine == self._selected_engine:
            return
        self._selected_engine = new_engine
        self._emit("selected_engine", engine_str)

    # ═══════════════════════════════════════════════════════════════════════════
    #  OpenAI Settings
    # ═══════════════════════════════════════════════════════════════════════════

    def get_openai_api_key(self) -> str:
        return self.config.api_keys.openai_api_key or ""

    def set_openai_api_key(self, val: str) -> None:
        self.config.api_keys.openai_api_key = val.strip()
        self._emit("openai_api_key")

    def get_openai_model(self) -> str:
        return self.config.translation_settings.openai_model or "gpt-4o-mini"

    def set_openai_model(self, val: str) -> None:
        self.config.translation_settings.openai_model = val.strip()
        self._emit("openai_model")

    def get_openai_base_url(self) -> str:
        return getattr(self.config.translation_settings, "openai_base_url", "") or ""

    def set_openai_base_url(self, val: str) -> None:
        self.config.translation_settings.openai_base_url = val.strip()
        self._emit("openai_base_url")

    # ═══════════════════════════════════════════════════════════════════════════
    #  Local LLM Settings
    # ═══════════════════════════════════════════════════════════════════════════

    def get_local_llm_url(self) -> str:
        return (
            getattr(self.config.translation_settings, "local_llm_url", "")
            or "http://localhost:11434/v1"
        )

    def set_local_llm_url(self, val: str) -> None:
        self.config.translation_settings.local_llm_url = val.strip()
        self._emit("local_llm_url")

    def get_local_llm_model(self) -> str:
        return (
            getattr(self.config.translation_settings, "local_llm_model", "")
            or "llama3.2"
        )

    def set_local_llm_model(self, val: str) -> None:
        self.config.translation_settings.local_llm_model = val.strip()
        self._emit("local_llm_model")

    # ═══════════════════════════════════════════════════════════════════════════
    #  LibreTranslate Settings
    # ═══════════════════════════════════════════════════════════════════════════

    def get_libretranslate_url(self) -> str:
        return (
            getattr(self.config.translation_settings, "libretranslate_url", "")
            or "http://localhost:5000"
        )

    def set_libretranslate_url(self, val: str) -> None:
        self.config.translation_settings.libretranslate_url = val.strip()
        self._emit("libretranslate_url")

    def get_libretranslate_api_key(self) -> str:
        return getattr(self.config.translation_settings, "libretranslate_api_key", "")

    def set_libretranslate_api_key(self, val: str) -> None:
        self.config.translation_settings.libretranslate_api_key = val.strip()
        self._emit("libretranslate_api_key")

    # ═══════════════════════════════════════════════════════════════════════════
    #  Custom Endpoint Settings
    # ═══════════════════════════════════════════════════════════════════════════

    def get_custom_endpoint_url(self) -> str:
        return getattr(self.config.translation_settings, "custom_endpoint_url", "")

    def set_custom_endpoint_url(self, val: str) -> None:
        self.config.translation_settings.custom_endpoint_url = val.strip()
        self._emit("custom_endpoint_url")

    def get_custom_endpoint_api_key(self) -> str:
        return getattr(self.config.translation_settings, "custom_endpoint_api_key", "")

    def set_custom_endpoint_api_key(self, val: str) -> None:
        self.config.translation_settings.custom_endpoint_api_key = val.strip()
        self._emit("custom_endpoint_api_key")

    # ═══════════════════════════════════════════════════════════════════════════
    #  Gemini Settings
    # ═══════════════════════════════════════════════════════════════════════════

    def get_gemini_api_key(self) -> str:
        return self.config.api_keys.gemini_api_key or ""

    def set_gemini_api_key(self, val: str) -> None:
        self.config.api_keys.gemini_api_key = val.strip()
        self._emit("gemini_api_key")

    def get_gemini_model(self) -> str:
        return self.config.translation_settings.gemini_model or "gemini-2.5-flash"

    def set_gemini_model(self, val: str) -> None:
        self.config.translation_settings.gemini_model = val.strip()
        self._emit("gemini_model")

    # ═══════════════════════════════════════════════════════════════════════════
    #  Advanced AI Settings
    # ═══════════════════════════════════════════════════════════════════════════

    def get_ai_temperature(self) -> float:
        return self.config.translation_settings.ai_temperature

    def set_ai_temperature(self, val: float) -> None:
        self.config.translation_settings.ai_temperature = max(0.0, min(float(val), 2.0))
        self._emit("ai_temperature")

    def get_ai_timeout(self) -> int:
        return self.config.translation_settings.ai_timeout

    def set_ai_timeout(self, val: int) -> None:
        self.config.translation_settings.ai_timeout = max(5, min(int(val), 600))
        self._emit("ai_timeout")

    def get_ai_max_tokens(self) -> int:
        return self.config.translation_settings.ai_max_tokens

    def set_ai_max_tokens(self, val: int) -> None:
        self.config.translation_settings.ai_max_tokens = max(64, min(int(val), 32768))
        self._emit("ai_max_tokens")

    def get_ai_batch_size(self) -> int:
        return self.config.translation_settings.ai_batch_size

    def set_ai_batch_size(self, val: int) -> None:
        self.config.translation_settings.ai_batch_size = max(1, min(int(val), 10000))
        self._emit("ai_batch_size")

    def get_ai_retry_count(self) -> int:
        return self.config.translation_settings.ai_retry_count

    def set_ai_retry_count(self, val: int) -> None:
        self.config.translation_settings.ai_retry_count = max(0, min(int(val), 20))
        self._emit("ai_retry_count")

    def get_ai_concurrency(self) -> int:
        return self.config.translation_settings.ai_concurrency

    def set_ai_concurrency(self, val: int) -> None:
        self.config.translation_settings.ai_concurrency = max(1, min(int(val), 20))
        self._emit("ai_concurrency")

    def get_ai_request_delay(self) -> float:
        return self.config.translation_settings.ai_request_delay

    def set_ai_request_delay(self, val: float) -> None:
        self.config.translation_settings.ai_request_delay = max(
            0.0, min(float(val), 60.0)
        )
        self._emit("ai_request_delay")

    def get_enable_parallel_batch(self) -> bool:
        return self.config.translation_settings.enable_parallel_batch

    def set_enable_parallel_batch(self, val: bool) -> None:
        self.config.translation_settings.enable_parallel_batch = bool(val)
        self._emit("enable_parallel_batch")

    def get_ai_custom_system_prompt(self) -> str:
        return self.config.translation_settings.ai_custom_system_prompt or ""

    def set_ai_custom_system_prompt(self, val: str) -> None:
        self.config.translation_settings.ai_custom_system_prompt = val.strip()
        self._emit("ai_custom_system_prompt")

    # ═══════════════════════════════════════════════════════════════════════════
    #  Output Mode
    # ═══════════════════════════════════════════════════════════════════════════

    def get_output_mode(self) -> str:
        return self.config.translation_settings.output_mode or "strings"

    def set_output_mode(self, val: str) -> None:
        self.config.translation_settings.output_mode = val or "strings"
        self.config.save_config()
        self._emit("output_mode")

    # ═══════════════════════════════════════════════════════════════════════════
    #  UI Language
    # ═══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def get_available_ui_languages() -> list:
        return [
            {"code": "tr", "name": "🇹🇷 Türkçe"},
            {"code": "en", "name": "🇬🇧 English"},
            {"code": "de", "name": "🇩🇪 Deutsch"},
            {"code": "fr", "name": "🇫🇷 Français"},
            {"code": "es", "name": "🇪🇸 Español"},
            {"code": "ru", "name": "🇷🇺 Русский"},
            {"code": "fa", "name": "🇮🇷 فارسی"},
            {"code": "zh-CN", "name": "🇨🇳 中文 (简体)"},
            {"code": "ja", "name": "🇯🇵 日本語"},
        ]

    def get_current_ui_language(self) -> str:
        return self.config.app_settings.ui_language or "en"

    def set_ui_language(self, lang_code: str) -> None:
        try:
            from src.utils.config import Language

            lang = Language(lang_code)
            self.config.load_locale(lang)
            self.config.save_config()
            self._emit("language", lang_code)
        except Exception as e:
            self.logger.warning("Error setting UI language: %s", e)

    # ═══════════════════════════════════════════════════════════════════════════
    #  UI Theme
    # ═══════════════════════════════════════════════════════════════════════════

    def get_available_themes(self) -> list:
        return [
            {"code": "dark", "name": self.config.get_ui_text("theme_dark", "🌙 Dark")},
            {"code": "light", "name": self.config.get_ui_text("theme_light", "☀️ Light")},
            {"code": "red", "name": self.config.get_ui_text("theme_red", "🔴 Red")},
            {"code": "turquoise", "name": self.config.get_ui_text("theme_turquoise", "🔵 Turquoise")},
            {"code": "green", "name": self.config.get_ui_text("theme_green", "🌿 Green")},
            {"code": "neon", "name": self.config.get_ui_text("theme_neon", "🌈 Neon")},
        ]

    def get_current_theme(self) -> str:
        return self.config.app_settings.app_theme or "dark"

    def set_theme(self, theme: str) -> None:
        self.config.app_settings.app_theme = theme
        self.config.save_config()
        self._emit("theme", theme)

    # ═══════════════════════════════════════════════════════════════════════════
    #  Target Language
    # ═══════════════════════════════════════════════════════════════════════════

    def get_target_languages(self) -> list:
        """Return target language list as list of {code, name} dicts."""
        languages = []
        for code, name in self.config.get_target_languages_for_ui():
            languages.append({"code": code, "name": name})
        return languages

    def get_target_language(self) -> str:
        return self.config.translation_settings.target_language or "turkish"

    def set_target_language(self, lang: str) -> None:
        normalized = self.config.normalize_renpy_language_code(lang)
        self.config.translation_settings.target_language = normalized
        self.config.save_config()
        self.logger.info("[SettingsBackend] Target language: %s", normalized)

    # ═══════════════════════════════════════════════════════════════════════════
    #  Source Language
    # ═══════════════════════════════════════════════════════════════════════════

    def get_source_languages(self) -> list:
        languages = []
        for code, name in self.config.get_source_languages_for_ui():
            languages.append({"code": code, "name": name})
        return languages

    def set_source_language(self, lang: str) -> None:
        self.config.translation_settings.source_language = (
            lang.strip() if lang.strip() else "auto"
        )
        self.config.save_config()
        self.logger.info("[SettingsBackend] Source language: %s", lang or "auto")

    # ═══════════════════════════════════════════════════════════════════════════
    #  Glossary Management
    # ═══════════════════════════════════════════════════════════════════════════

    def get_glossary_list(self) -> list:
        """Return glossary as list of {source, target} dicts."""
        if hasattr(self.config, "glossary") and self.config.glossary:
            return [{"source": k, "target": v} for k, v in self.config.glossary.items()]
        return []

    def add_glossary_item(self, source: str, target: str) -> None:
        if not source.strip():
            return
        if not hasattr(self.config, "glossary"):
            self.config.glossary = {}
        self.config.glossary[source.strip()] = target.strip()
        self.config.save_glossary()
        self._emit("glossary")

    def remove_glossary_item(self, source: str) -> None:
        if hasattr(self.config, "glossary") and source in self.config.glossary:
            del self.config.glossary[source]
            self.config.save_glossary()
            self._emit("glossary")

    # ═══════════════════════════════════════════════════════════════════════════
    #  Save Settings
    # ═══════════════════════════════════════════════════════════════════════════

    def save_settings(self) -> None:
        """Persist current settings to config.json while preserving runtime overrides."""

        # 1. Snapshot all mutable settings
        threads = self.config.translation_settings.max_concurrent_threads
        delay = self.config.translation_settings.request_delay
        batch_size = self.config.translation_settings.max_batch_size
        multi = self.config.translation_settings.use_multi_endpoint
        lingva = self.config.translation_settings.enable_lingva_fallback
        aggressive = self.config.translation_settings.aggressive_retry_translation
        cache_enabled = self.config.translation_settings.use_cache
        chk_updates = self.config.app_settings.check_for_updates
        rpyc = self.config.translation_settings.enable_rpyc_reader
        deep_scan = self.config.translation_settings.enable_deep_scan
        enable_parallel = self.config.translation_settings.enable_parallel_batch

        selected_engine_str = self._selected_engine.value
        openai_key = self.config.api_keys.openai_api_key or ""
        openai_model = self.config.translation_settings.openai_model or "gpt-4o-mini"
        openai_base_url = (
            getattr(self.config.translation_settings, "openai_base_url", "") or ""
        )
        local_llm_url = (
            getattr(self.config.translation_settings, "local_llm_url", "") or ""
        )
        local_llm_model = (
            getattr(self.config.translation_settings, "local_llm_model", "")
            or "llama3.2"
        )
        gemini_key = self.config.api_keys.gemini_api_key or ""
        gemini_model = self.config.translation_settings.gemini_model or "gemini-2.5-flash"

        libretranslate_url = (
            getattr(self.config.translation_settings, "libretranslate_url", "")
            or "http://localhost:5000"
        )
        libretranslate_api_key = (
            getattr(self.config.translation_settings, "libretranslate_api_key", "") or ""
        )
        custom_endpoint_url = (
            getattr(self.config.translation_settings, "custom_endpoint_url", "") or ""
        )
        custom_endpoint_api_key = (
            getattr(self.config.translation_settings, "custom_endpoint_api_key", "")
            or ""
        )

        ai_temp = self.config.translation_settings.ai_temperature
        ai_timeo = self.config.translation_settings.ai_timeout
        ai_tokens = self.config.translation_settings.ai_max_tokens
        ai_bsize = self.config.translation_settings.ai_batch_size
        ai_retries = self.config.translation_settings.ai_retry_count
        ai_concur = self.config.translation_settings.ai_concurrency
        ai_delay = self.config.translation_settings.ai_request_delay
        ai_sys_prompt = self.config.translation_settings.ai_custom_system_prompt
        output_mode = self.config.translation_settings.output_mode

        try:
            # 2. Reload config from disk to avoid overwriting full-version keys
            self.config.load_config()

            # 3. Re-apply only the allowed settings
            self.config.translation_settings.max_concurrent_threads = threads
            self.config.translation_settings.request_delay = delay
            self.config.translation_settings.max_batch_size = batch_size
            self.config.translation_settings.use_multi_endpoint = multi
            self.config.translation_settings.enable_lingva_fallback = lingva
            self.config.translation_settings.aggressive_retry_translation = aggressive
            self.config.translation_settings.use_cache = cache_enabled
            self.config.app_settings.check_for_updates = chk_updates
            self.config.translation_settings.enable_rpyc_reader = rpyc
            self.config.translation_settings.enable_deep_scan = deep_scan
            self.config.translation_settings.enable_parallel_batch = enable_parallel

            # Engine & AI
            self.config.translation_settings.selected_engine = selected_engine_str
            self.config.api_keys.openai_api_key = openai_key
            self.config.translation_settings.openai_model = openai_model
            self.config.translation_settings.openai_base_url = openai_base_url
            self.config.translation_settings.local_llm_url = local_llm_url
            self.config.translation_settings.local_llm_model = local_llm_model

            # Gemini
            self.config.api_keys.gemini_api_key = gemini_key
            self.config.translation_settings.gemini_model = gemini_model

            # LibreTranslate / Custom
            self.config.translation_settings.libretranslate_url = libretranslate_url
            self.config.translation_settings.libretranslate_api_key = libretranslate_api_key
            self.config.translation_settings.custom_endpoint_url = custom_endpoint_url
            self.config.translation_settings.custom_endpoint_api_key = custom_endpoint_api_key

            # Advanced AI
            self.config.translation_settings.ai_temperature = ai_temp
            self.config.translation_settings.ai_timeout = ai_timeo
            self.config.translation_settings.ai_max_tokens = ai_tokens
            self.config.translation_settings.ai_batch_size = ai_bsize
            self.config.translation_settings.ai_retry_count = ai_retries
            self.config.translation_settings.ai_concurrency = ai_concur
            self.config.translation_settings.ai_request_delay = ai_delay
            self.config.translation_settings.ai_custom_system_prompt = ai_sys_prompt

            # Output mode
            self.config.translation_settings.output_mode = output_mode

            # 4. Save
            self.config.save_config()

            # 5. Restore runtime overrides
            self.config.translation_settings.enable_deep_extraction = False
            self.config.translation_settings.enable_unrpyc_decompile = False

            # 6. Apply to live translator instances
            if self.translation_manager:
                self.translation_manager.max_concurrent_requests = threads
                self.translation_manager.max_batch_size = batch_size
                self.translation_manager.use_cache = cache_enabled

                google_translator = self.translation_manager.translators.get(
                    TranslationEngine.GOOGLE
                )
                if google_translator:
                    google_translator.multi_q_concurrency = threads
                    google_translator.max_texts_per_slice = min(batch_size, 50)
                    google_translator._google_request_delay = delay
                    google_translator.use_multi_endpoint = multi
                    google_translator.enable_lingva_fallback = lingva
                    google_translator.aggressive_retry = aggressive

            return None
        except Exception as exc:
            self.logger.exception("[SettingsBackend] save_settings error")
            raise
