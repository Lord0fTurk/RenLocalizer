# -*- coding: utf-8 -*-
"""
Regression tests for cache reuse across runs (v2.8.17).

Lookups key the cache by the original (unprotected) text, but stores used
``result.original_text`` — and AI engines return the XML/token-protected text
they were handed. Every line containing a placeholder was therefore written
under a key no lookup could match, so it was re-translated on every run (and on
every restart, since the same keys were persisted). Plain lines without
placeholders happened to work, which is why the loss was easy to miss.
"""

import asyncio
import os
import tempfile
from types import SimpleNamespace


from src.core.syntax_guard import protect_renpy_syntax_xml
from src.core.translator import (
    TranslationEngine,
    TranslationManager,
    TranslationRequest,
    TranslationResult,
)


def _config():
    return SimpleNamespace(
        translation_settings=SimpleNamespace(
            openai_model="gpt-4o-mini", openai_base_url="", ai_temperature=0.3,
            ai_timeout=30, ai_max_tokens=512, ai_batch_size=15, ai_scene_batch_size=15,
            ai_concurrency=2, ai_retry_count=1, ai_custom_system_prompt="",
            ai_model_profile="auto", ai_batch_format="scene", use_cache=True,
            aggressive_retry_translation=False,
        ),
        api_keys=SimpleNamespace(openai_api_key="x"),
    )


def _pipeline_requests(texts, engine=TranslationEngine.OPENAI):
    """Requests shaped exactly like the pipeline builds them (preprotected)."""
    requests = []
    for source in texts:
        protected, placeholders = protect_renpy_syntax_xml(source)
        requests.append(TranslationRequest(
            text=protected, source_lang="en", target_lang="tr", engine=engine,
            metadata={"preprotected": True, "original_text": source,
                      "placeholders": placeholders, "xml_mode": True},
        ))
    return requests


def _openai_translator(config, calls):
    from src.core.ai_translator import OpenAITranslator

    translator = OpenAITranslator(api_key="x", config_manager=config)

    async def fake_call_api(system_prompt, user_content, **kwargs):
        calls.append(user_content)
        return "\n".join(f"[{i}] ceviri{i}" for i in range(user_content.count("[")))

    translator._call_api = fake_call_api
    return translator


TEXTS = ["Hello [name], welcome!", "Save game", "{b}Bold{/b} and [x] mixed"]


class TestCacheKeyNormalization:
    def test_key_uses_the_original_text_not_the_protected_one(self):
        protected, placeholders = protect_renpy_syntax_xml("Hello [name]!")
        request = TranslationRequest(
            text=protected, source_lang="en", target_lang="tr",
            engine=TranslationEngine.OPENAI,
            metadata={"preprotected": True, "original_text": "Hello [name]!",
                      "placeholders": placeholders},
        )
        assert TranslationManager._cache_key_for(request) == (
            "openai", "en", "tr", "Hello [name]!",
        )

    def test_key_falls_back_to_the_request_text(self):
        request = TranslationRequest("Plain", "en", "tr", TranslationEngine.GOOGLE)
        assert TranslationManager._cache_key_for(request)[3] == "Plain"


class TestReuseAcrossRuns:
    def test_second_identical_batch_makes_no_api_call(self):
        config = _config()
        calls = []
        manager = TranslationManager(config_manager=config)
        manager.add_translator(TranslationEngine.OPENAI, _openai_translator(config, calls))

        asyncio.run(manager.translate_batch(_pipeline_requests(TEXTS)))
        assert len(calls) == 1, "first run translates"

        asyncio.run(manager.translate_batch(_pipeline_requests(TEXTS)))
        assert len(calls) == 1, "second run must be served entirely from the cache"
        assert manager.cache_hits == len(TEXTS)

    def test_cached_keys_never_contain_protection_tags(self):
        config = _config()
        manager = TranslationManager(config_manager=config)
        manager.add_translator(TranslationEngine.OPENAI, _openai_translator(config, []))

        asyncio.run(manager.translate_batch(_pipeline_requests(TEXTS)))

        cached_texts = [key[3] for key in manager._cache]
        assert sorted(cached_texts) == sorted(TEXTS)
        assert not any("<ph" in text or "⟦" in text for text in cached_texts)

    def test_cache_survives_a_restart(self):
        """A saved cache must still be usable after reload — the real complaint."""
        config = _config()
        calls = []
        translator = _openai_translator(config, calls)

        first = TranslationManager(config_manager=config)
        first.add_translator(TranslationEngine.OPENAI, translator)
        asyncio.run(first.translate_batch(_pipeline_requests(TEXTS)))
        assert len(calls) == 1

        path = os.path.join(tempfile.mkdtemp(), "translation_cache.json")
        first.save_cache(path)

        second = TranslationManager(config_manager=config)
        second.add_translator(TranslationEngine.OPENAI, translator)
        second.load_cache(path)
        asyncio.run(second.translate_batch(_pipeline_requests(TEXTS)))

        assert len(calls) == 1, "a restarted run must not re-translate"
        assert second.cache_hits == len(TEXTS)
        assert second.cache_misses == 0

    def test_single_request_path_also_stores_a_usable_key(self):
        """translate_batch falls back to per-item translation when a batch fails."""
        config = _config()
        calls = []
        manager = TranslationManager(config_manager=config)

        class Failing:
            _engine = TranslationEngine.OPENAI

            async def translate_batch(self, requests):
                raise RuntimeError("batch unavailable")

            async def translate_single(self, request):
                calls.append(request.text)
                meta = request.metadata if isinstance(request.metadata, dict) else {}
                return TranslationResult(
                    original_text=request.text,  # protected, as AI engines do
                    translated_text="ceviri",
                    source_lang=request.source_lang,
                    target_lang=request.target_lang,
                    engine=TranslationEngine.OPENAI,
                    success=True,
                    metadata=meta,
                )

        manager.add_translator(TranslationEngine.OPENAI, Failing())

        asyncio.run(manager.translate_batch(_pipeline_requests(TEXTS)))
        assert len(calls) == len(TEXTS)

        asyncio.run(manager.translate_batch(_pipeline_requests(TEXTS)))
        assert len(calls) == len(TEXTS), "the per-item fallback must cache reusably too"

    def test_plain_text_without_placeholders_still_works(self):
        """This path always worked; guard it so a future fix cannot break it."""
        config = _config()
        calls = []
        manager = TranslationManager(config_manager=config)
        manager.add_translator(TranslationEngine.OPENAI, _openai_translator(config, calls))

        plain = ["Save game", "Load game"]
        asyncio.run(manager.translate_batch(_pipeline_requests(plain)))
        asyncio.run(manager.translate_batch(_pipeline_requests(plain)))
        assert len(calls) == 1


class TestLegacyCacheCleanup:
    def test_entries_written_under_protected_text_are_dropped_on_load(self, tmp_path):
        """A cache from an older build must not waste capacity on dead keys."""
        import json

        path = tmp_path / "translation_cache.json"
        path.write_text(json.dumps({
            "openai": {"en": {"tr": {
                'Hello <ph id="0">[name]</ph>!': "Merhaba [name]!",   # unusable
                "Hello __PH_0__!": "Merhaba!",                        # unusable
                "\u27e6RLPH1_0\u27e7 gold": "altin",                  # unusable
                "Save game": "Kaydet",                                # usable
            }}}
        }), encoding="utf-8")

        manager = TranslationManager()
        manager.load_cache(str(path))

        assert [key[3] for key in manager._cache] == ["Save game"]
