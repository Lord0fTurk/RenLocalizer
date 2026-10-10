# -*- coding: utf-8 -*-
"""Regression tests for the stale-translator bug.

Translator instances are created at app startup and cached in the
TranslationManager. Before the fix, settings edited in the UI (Local LLM
model name, URL, concurrency, Hy-MT2 profile) never reached the running
translation because the cached translator kept its construction-time values.

AppBackend._refresh_active_translator must rebuild the active engine's
translator from the CURRENT config before each translation run.
"""

import logging
from types import SimpleNamespace

from src.core.translator import TranslationEngine, TranslationManager


def _make_backend_stub(model="llama3.2", concurrency=2, profile="auto"):
    """Duck-typed AppBackend stand-in (Qt-free) carrying the real methods."""
    from src.backend.app_backend import AppBackend

    settings = SimpleNamespace(
        local_llm_model=model,
        local_llm_url="http://localhost:1234/v1",
        ai_concurrency=concurrency,
        ai_model_profile=profile,
        ai_temperature=0.3,
        ai_timeout=60,
        ai_max_tokens=2048,
        ai_batch_size=10,
        ai_retry_count=1,
        ai_custom_system_prompt="",
        openai_model="gpt-4o-mini",
        openai_base_url="",
    )
    stub = SimpleNamespace(
        config=SimpleNamespace(
            translation_settings=settings,
            api_keys=SimpleNamespace(openai_api_key=""),
        ),
        translation_manager=TranslationManager(),
        proxy_manager=None,
        _selected_engine=TranslationEngine.LOCAL_LLM,
        logger=logging.getLogger("test-refresh"),
        logMessage=SimpleNamespace(emit=lambda *a, **k: None),
    )
    for name in (
        "_setup_ai_translator",
        "_setup_libretranslate",
        "_setup_custom_endpoint",
        "_replace_translator",
        "_refresh_active_translator",
    ):
        setattr(stub, name, getattr(AppBackend, name).__get__(stub))
    return stub


class TestActiveTranslatorRefresh:
    def test_refresh_rebuilds_local_llm_with_current_settings(self):
        stub = _make_backend_stub(model="llama3.2", concurrency=2)
        stub._refresh_active_translator()
        old = stub.translation_manager.translators[TranslationEngine.LOCAL_LLM]
        assert old._model == "llama3.2"
        assert old._semaphore_count == 2
        assert old._model_profile is None

        # User edits settings in the UI (in-memory config changes)
        stub.config.translation_settings.local_llm_model = "tencent/Hy-MT2-7B-GGUF"
        stub.config.translation_settings.ai_concurrency = 4

        stub._refresh_active_translator()
        new = stub.translation_manager.translators[TranslationEngine.LOCAL_LLM]
        assert new is not old, "translator must be rebuilt, not reused"
        assert new._model == "tencent/Hy-MT2-7B-GGUF"
        assert new._semaphore_count == 4
        assert new._model_profile == "hy_mt2"

    def test_refresh_applies_forced_profile(self):
        stub = _make_backend_stub(model="my-custom-model", profile="hy_mt2")
        stub._refresh_active_translator()
        t = stub.translation_manager.translators[TranslationEngine.LOCAL_LLM]
        assert t._model_profile == "hy_mt2"

    def test_refresh_replaces_openai_translator_on_url_change(self):
        stub = _make_backend_stub()
        stub._selected_engine = TranslationEngine.OPENAI
        stub._refresh_active_translator()
        old = stub.translation_manager.translators[TranslationEngine.OPENAI]

        stub.config.translation_settings.openai_base_url = "http://localhost:1234/v1"
        stub._refresh_active_translator()
        new = stub.translation_manager.translators[TranslationEngine.OPENAI]
        assert new is not old
        assert new._base_url == "http://localhost:1234/v1"

    def test_refresh_attaches_google_fallback_to_gemini(self):
        """GUI-built Gemini translators must carry the Google fallback (safety/quota/placeholder recovery)."""
        import pytest
        from src.core.ai_translator import _GEMINI_AVAILABLE
        if not _GEMINI_AVAILABLE:
            pytest.skip("google-genai not installed")
        from src.core.translator import GoogleTranslator

        stub = _make_backend_stub()
        stub.config.api_keys.gemini_api_key = "fake-key"
        stub.config.translation_settings.gemini_model = "gemini-2.5-flash"
        stub.config.translation_settings.gemini_safety_settings = "BLOCK_NONE"
        stub._selected_engine = TranslationEngine.GEMINI

        google = GoogleTranslator(config_manager=None)
        stub.translation_manager.add_translator(TranslationEngine.GOOGLE, google)

        stub._refresh_active_translator()
        gemini = stub.translation_manager.translators[TranslationEngine.GEMINI]
        assert gemini.fallback_translator is google
        assert gemini._safety_level == "BLOCK_NONE"

    def _guard_stub(self, engine, mode="external", translating=False):
        from src.backend.app_backend import AppBackend

        stub = _make_backend_stub()
        stub._selected_engine = engine
        stub._is_translating = translating
        stub.config.translation_settings.local_llm_mode = mode
        stub.messages = []
        stub.logMessage = SimpleNamespace(emit=lambda level, msg: stub.messages.append((level, msg)))
        stub._t = lambda key, default: default
        for name in ("_is_builtin_local_llm", "_setup_selected_engine_async"):
            setattr(stub, name, getattr(AppBackend, name).__get__(stub))
        return stub

    def test_no_translator_swap_during_running_translation(self, monkeypatch):
        """Replacing the in-use translator closed its HTTP session mid-request."""
        import threading

        started = []
        monkeypatch.setattr(threading, "Thread", lambda *a, **k: started.append(k) or SimpleNamespace(start=lambda: None))
        stub = self._guard_stub(TranslationEngine.OPENAI, translating=True)
        stub._setup_selected_engine_async(TranslationEngine.OPENAI)
        assert started == []
        assert stub.messages and stub.messages[0][0] == "info"

    def test_builtin_gguf_server_not_started_by_warmup(self, monkeypatch):
        """Launch / engine selection must not load a GGUF into VRAM."""
        import threading

        started = []
        monkeypatch.setattr(threading, "Thread", lambda *a, **k: started.append(k) or SimpleNamespace(start=lambda: None))
        stub = self._guard_stub(TranslationEngine.LOCAL_LLM, mode="builtin")
        stub._setup_selected_engine_async(TranslationEngine.LOCAL_LLM)
        assert started == []

        external = self._guard_stub(TranslationEngine.LOCAL_LLM, mode="external")
        external._setup_selected_engine_async(TranslationEngine.LOCAL_LLM)
        assert len(started) == 1

    def test_refresh_builds_bing_with_google_fallback(self):
        from src.core.translator import BingTranslator, GoogleTranslator

        stub = _make_backend_stub()
        stub._selected_engine = TranslationEngine.BING
        for name in ("_setup_bing_translator",):
            from src.backend.app_backend import AppBackend
            setattr(stub, name, getattr(AppBackend, name).__get__(stub))
        google = GoogleTranslator(config_manager=None)
        stub.translation_manager.add_translator(TranslationEngine.GOOGLE, google)

        stub._refresh_active_translator()
        bing = stub.translation_manager.translators[TranslationEngine.BING]
        assert isinstance(bing, BingTranslator)
        assert bing.fallback_translator is google
