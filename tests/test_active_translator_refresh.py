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
