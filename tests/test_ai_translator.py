# -*- coding: utf-8 -*-
"""Tests for AI translator implementations (OpenAI, DeepSeek, LocalLLM, Gemini)."""

import json as _json
import re
from unittest.mock import MagicMock, patch, AsyncMock
from types import SimpleNamespace

import pytest

from src.core.ai_translator import (
    _build_xml_batch,
    _parse_xml_batch,
    _build_json_batch,
    _parse_json_batch,
    _recover_placeholders_levenshtein,
)
from src.core.translator import (
    TranslationEngine,
    TranslationRequest,
    TranslationResult,
)


def _make_config(**overrides):
    defaults = {
        "openai_model": "gpt-4o-mini",
        "ai_temperature": 0.3,
        "ai_timeout": 30,
        "ai_max_tokens": 2048,
        "ai_batch_size": 50,
        "ai_retry_count": 3,
        "ai_concurrency": 5,
        "ai_request_delay": 0.1,
        "ai_custom_system_prompt": "",
        "openai_base_url": "",
        "local_llm_url": "http://localhost:11434/v1",
        "local_llm_model": "llama3.2",
        "gemini_model": "gemini-2.5-flash",
        "ai_model_profile": "auto",
    }
    defaults.update(overrides)
    settings = SimpleNamespace(**defaults)
    api_keys = SimpleNamespace(openai_api_key="sk-test", gemini_api_key="test-key")
    return SimpleNamespace(translation_settings=settings, api_keys=api_keys)


# ─────────────────────────────────────────────────────────────────────────────
# XML / JSON / Recovery Batch Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestXmlBatch:
    def test_build_basic(self):
        result = _build_xml_batch(["Hello", "World"])
        assert '<item id="0">Hello</item>' in result
        assert result.startswith("<translations>")

    def test_build_escapes_special_chars(self):
        result = _build_xml_batch(["a < b & c"])
        assert "&lt;" in result
        assert "&amp;" in result

    def test_build_empty_list(self):
        result = _build_xml_batch([])
        assert result == "<translations>\n</translations>"

    def test_parse_basic(self):
        xml = '<translations><item id="0">Merhaba</item><item id="1">Dunya</item></translations>'
        results = _parse_xml_batch(xml, 2)
        assert results[0] == "Merhaba"
        assert results[1] == "Dunya"

    def test_parse_fallback_regex(self):
        xml = 'prefix <item id="0">Test</item> suffix'
        results = _parse_xml_batch(xml, 1)
        assert results[0] == "Test"

    def test_parse_missing_items(self):
        xml = '<translations><item id="1">Only</item></translations>'
        results = _parse_xml_batch(xml, 2)
        assert results[0] is None
        assert results[1] == "Only"


class TestJsonBatch:
    def test_build_basic(self):
        texts = ["Hello", "World"]
        result = _build_json_batch(texts)
        parsed = _json.loads(result)
        assert len(parsed["items_to_translate"]) == 2

    def test_parse_basic(self):
        response_data = {
            "translations": [
                {"id": 0, "translated_text": "Merhaba"},
                {"id": 1, "translated_text": "Dunya"},
            ]
        }
        json_str = _json.dumps(response_data)
        results = _parse_json_batch(json_str, 2)
        assert results[0] == "Merhaba"

    def test_parse_with_markdown_wrapping(self):
        wrapped = "```json\n" + _json.dumps({
            "translations": [{"id": 0, "translated_text": "Test"}]
        }) + "\n```"
        results = _parse_json_batch(wrapped, 1)
        assert results[0] == "Test"


class TestLevenshteinRecovery:
    def test_exact_match_no_recovery_needed(self):
        result = _recover_placeholders_levenshtein(
            "Hello __PH_0__", "Merhaba __PH_0__", {"__PH_0__": "<ph>"}
        )
        assert "__PH_0__" in result

    def test_empty_placeholders_returns_unchanged(self):
        result = _recover_placeholders_levenshtein("Hello world", "Merhaba dunya", {})
        assert result == "Merhaba dunya"


# ─────────────────────────────────────────────────────────────────────────────
# Translator Instantiation Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestOpenAITranslator:
    def test_raises_without_openai_package(self):
        with patch("src.core.ai_translator._OPENAI_AVAILABLE", False):
            from src.core.ai_translator import OpenAITranslator
            with pytest.raises(ImportError, match="openai"):
                OpenAITranslator(api_key="sk-test")

    def test_config_sets_model(self):
        config = _make_config(openai_model="gpt-4o")
        from src.core.ai_translator import OpenAITranslator
        t = OpenAITranslator(api_key="sk-test-key", config_manager=config)
        assert t._model == "gpt-4o"
        assert t._engine == TranslationEngine.OPENAI

    def test_semaphore_lazy_init(self):
        config = _make_config()
        from src.core.ai_translator import OpenAITranslator
        t = OpenAITranslator(api_key="sk-test-key", config_manager=config)
        sem = t._get_semaphore()
        assert sem is not None


class TestDeepSeekTranslator:
    def test_instantiation_defaults(self):
        config = _make_config()
        from src.core.ai_translator import DeepSeekTranslator
        t = DeepSeekTranslator(api_key="sk-test", config_manager=config)
        assert t._engine == TranslationEngine.OPENAI
        assert "deepseek" in t._base_url
        assert t._semaphore_count == 12

    def test_inherits_from_openai(self):
        from src.core.ai_translator import DeepSeekTranslator, OpenAITranslator
        assert issubclass(DeepSeekTranslator, OpenAITranslator)


class TestLocalLLMTranslator:
    def test_instantiation_defaults(self):
        config = _make_config()
        from src.core.ai_translator import LocalLLMTranslator
        t = LocalLLMTranslator(config_manager=config)
        assert t._engine == TranslationEngine.LOCAL_LLM
        # _make_config fixture sets ai_concurrency=5
        assert t._semaphore_count == 5

    def test_concurrency_defaults_to_two_without_setting(self):
        config = _make_config(ai_concurrency=None)
        from src.core.ai_translator import LocalLLMTranslator
        t = LocalLLMTranslator(config_manager=config)
        assert t._semaphore_count == 2

    def test_concurrency_honours_ai_concurrency_setting(self):
        config = _make_config(ai_concurrency=4)
        from src.core.ai_translator import LocalLLMTranslator
        t = LocalLLMTranslator(config_manager=config)
        assert t._semaphore_count == 4

    def test_instantiation_custom_url(self):
        config = _make_config(local_llm_url="http://localhost:8080/v1")
        from src.core.ai_translator import LocalLLMTranslator
        t = LocalLLMTranslator(config_manager=config)
        assert "8080" in t._base_url

    def test_inherits_from_openai(self):
        from src.core.ai_translator import LocalLLMTranslator, OpenAITranslator
        assert issubclass(LocalLLMTranslator, OpenAITranslator)


class TestGeminiTranslator:
    def test_raises_without_gemini_package(self):
        with patch("src.core.ai_translator._GEMINI_AVAILABLE", False):
            from src.core.ai_translator import GeminiTranslator
            with pytest.raises(ImportError, match="google-genai"):
                GeminiTranslator(api_key="test-key")

    def test_instantiation_with_google_genai_client(self):
        import src.core.ai_translator as ai_mod
        mock_genai = MagicMock()
        mock_genai.Client = MagicMock()

        with patch.object(ai_mod, "_GEMINI_AVAILABLE", True), \
             patch.object(ai_mod, "_GEMINI_MODE", "google_genai"), \
             patch.object(ai_mod, "genai", mock_genai, create=True):
            t = ai_mod.GeminiTranslator(api_key="test-key")
            mock_genai.Client.assert_called_once_with(api_key="test-key")
            assert t._engine == TranslationEngine.GEMINI

    def test_instantiation_with_legacy_genai(self):
        mock_genai = MagicMock()
        mock_genai.GenerativeModel = MagicMock()
        mock_genai.configure = MagicMock()

        import src.core.ai_translator as ai_mod
        with patch.object(ai_mod, "_GEMINI_AVAILABLE", True), \
             patch.object(ai_mod, "_GEMINI_MODE", "legacy_generativeai"), \
             patch.object(ai_mod, "genai", mock_genai, create=True):
            t = ai_mod.GeminiTranslator(api_key="test-key")
            mock_genai.configure.assert_called_once_with(api_key="test-key")
            assert t._engine == TranslationEngine.GEMINI

    def test_get_supported_languages(self):
        import src.core.ai_translator as ai_mod
        mock_genai = MagicMock()
        mock_genai.Client = MagicMock()

        with patch.object(ai_mod, "_GEMINI_AVAILABLE", True), \
             patch.object(ai_mod, "_GEMINI_MODE", "google_genai"), \
             patch.object(ai_mod, "genai", mock_genai, create=True):
            t = ai_mod.GeminiTranslator(api_key="test-key")
            langs = t.get_supported_languages()
            assert isinstance(langs, dict)
            assert "tr" in langs
            assert "en" in langs

    def test_build_gemini_safety_settings(self):
        """Verify safety settings threshold mapping and categories."""
        from src.core.ai_translator import _build_gemini_safety_settings
        settings = _build_gemini_safety_settings("BLOCK_NONE")
        assert len(settings) >= 4
        # All categories should be mapped without error

    def test_build_gemini_thinking_config(self):
        """Verify that thinking budget is set to 0 to prevent runaway reasoning tokens."""
        from src.core.ai_translator import _build_gemini_thinking_config
        tc = _build_gemini_thinking_config()
        if tc is not None:
            assert getattr(tc, "thinking_budget", None) == 0

    def test_translate_single_success(self):
        """Verify single translation with mock client response."""
        import asyncio
        from src.core.ai_translator import GeminiTranslator
        from src.core.translator import TranslationEngine

        t = GeminiTranslator(api_key="fake-key")
        mock_response = MagicMock()
        mock_response.text = "Merhaba dünya!"
        
        mock_models = MagicMock()
        mock_models.generate_content = AsyncMock(return_value=mock_response)
        mock_aio = MagicMock(models=mock_models)
        t._client = MagicMock(aio=mock_aio)

        req = TranslationRequest(text="Hello world!", source_lang="en", target_lang="tr", engine=TranslationEngine.GEMINI)
        result = asyncio.run(t.translate_single(req))
        assert result.success is True
        assert result.translated_text == "Merhaba dünya!"

    def test_translate_single_safety_delegation_to_fallback(self):
        """Verify that safety filter triggers delegation to fallback translator."""
        import asyncio
        from src.core.ai_translator import GeminiTranslator
        from src.core.translator import TranslationResult, TranslationEngine

        t = GeminiTranslator(api_key="fake-key")
        mock_models = MagicMock()
        mock_models.generate_content = AsyncMock(side_effect=Exception("SAFETY block triggered"))
        mock_aio = MagicMock(models=mock_models)
        t._client = MagicMock(aio=mock_aio)

        mock_fallback = MagicMock()
        mock_fallback.translate_single = AsyncMock(return_value=TranslationResult(
            original_text="Mature dialogue",
            translated_text="Yetişkin diyalog",
            source_lang="en",
            target_lang="tr",
            engine=TranslationEngine.GOOGLE,
            success=True,
        ))
        t.set_fallback_translator(mock_fallback)

        req = TranslationRequest(text="Mature dialogue", source_lang="en", target_lang="tr", engine=TranslationEngine.GEMINI)
        result = asyncio.run(t.translate_single(req))
        assert result.success is True
        assert result.translated_text == "Yetişkin diyalog"
        mock_fallback.translate_single.assert_awaited_once()

    def test_translate_batch_xml_success(self):
        """Verify structured XML batch translation parsing in one request."""
        import asyncio
        from src.core.ai_translator import GeminiTranslator
        from src.core.translator import TranslationEngine

        t = GeminiTranslator(api_key="fake-key")
        mock_response = MagicMock()
        mock_response.text = (
            "<translations>\n"
            '  <item id="0">Günaydın</item>\n'
            '  <item id="1">İyi akşamlar</item>\n'
            "</translations>"
        )

        mock_models = MagicMock()
        mock_models.generate_content = AsyncMock(return_value=mock_response)
        mock_aio = MagicMock(models=mock_models)
        t._client = MagicMock(aio=mock_aio)

        reqs = [
            TranslationRequest(text="Good morning", source_lang="en", target_lang="tr", engine=TranslationEngine.GEMINI),
            TranslationRequest(text="Good evening", source_lang="en", target_lang="tr", engine=TranslationEngine.GEMINI),
        ]
        results = asyncio.run(t.translate_batch(reqs))
        assert len(results) == 2
        assert results[0].success is True
        assert results[0].translated_text == "Günaydın"
        assert results[1].success is True
        assert results[1].translated_text == "İyi akşamlar"
        # Must be called only once for batch
        assert mock_models.generate_content.await_count == 1

    # ── Placeholder restoration, fallback request shape, chunking ────────────

    @staticmethod
    def _make_gemini(response_text=None, side_effect=None):
        from src.core.ai_translator import GeminiTranslator

        t = GeminiTranslator(api_key="fake-key")
        mock_models = MagicMock()
        if side_effect is not None:
            mock_models.generate_content = AsyncMock(side_effect=side_effect)
        else:
            mock_response = MagicMock()
            mock_response.text = response_text
            mock_models.generate_content = AsyncMock(return_value=mock_response)
        t._client = MagicMock(aio=MagicMock(models=mock_models))
        return t, mock_models

    @staticmethod
    def _protected_request(source):
        from src.core.syntax_guard import protect_renpy_syntax_xml
        from src.core.translator import TranslationEngine

        protected, placeholders = protect_renpy_syntax_xml(source)
        req = TranslationRequest(
            text=protected, source_lang="en", target_lang="tr", engine=TranslationEngine.GEMINI,
            metadata={"preprotected": True, "original_text": source,
                      "placeholders": placeholders, "xml_mode": True},
        )
        return req, protected, placeholders

    def test_single_restores_xml_placeholders(self):
        """<ph id=N> tags from the pipeline must be turned back into Ren'Py syntax."""
        import asyncio

        source = "Hello [player_name], {color=#f00}welcome{/color}!"
        req, protected, _ = self._protected_request(source)
        model_answer = protected.replace("Hello", "Merhaba").replace("welcome", "hoş geldin")
        t, _ = self._make_gemini(response_text=model_answer)

        result = asyncio.run(t.translate_single(req))
        assert result.success is True
        assert result.translated_text == "Merhaba [player_name], {color=#f00}hoş geldin{/color}!"
        assert "<ph" not in result.translated_text

    def test_single_lost_placeholder_delegates_to_fallback(self):
        """A model answer that drops a placeholder must not be emitted; fallback is used."""
        import asyncio
        from src.core.translator import TranslationResult, TranslationEngine

        source = "Hello [player_name]!"
        req, _, _ = self._protected_request(source)
        t, _ = self._make_gemini(response_text="Merhaba!")  # placeholder dropped

        fallback = MagicMock()
        fallback._engine = TranslationEngine.GOOGLE
        fallback.translate_single = AsyncMock(return_value=TranslationResult(
            original_text=source, translated_text="Merhaba [player_name]!",
            source_lang="en", target_lang="tr", engine=TranslationEngine.GOOGLE, success=True,
        ))
        t.set_fallback_translator(fallback)

        result = asyncio.run(t.translate_single(req))
        assert result.success is True
        assert result.translated_text == "Merhaba [player_name]!"
        assert result.metadata.get("fallback_engine") == "google"

    def test_single_lost_placeholder_without_fallback_fails(self):
        import asyncio

        req, _, _ = self._protected_request("Hello [player_name]!")
        t, _ = self._make_gemini(response_text="Merhaba!")
        result = asyncio.run(t.translate_single(req))
        assert result.success is False
        assert "<ph" not in result.translated_text

    def test_fallback_receives_unprotected_request(self):
        """Fallback engines must get the original text, not the XML-protected AI text."""
        import asyncio
        from src.core.translator import TranslationResult, TranslationEngine

        source = "Hello [player_name]!"
        req, protected, _ = self._protected_request(source)
        t, _ = self._make_gemini(side_effect=Exception("SAFETY block triggered"))

        fallback = MagicMock()
        fallback._engine = TranslationEngine.GOOGLE
        fallback.translate_single = AsyncMock(return_value=TranslationResult(
            original_text=source, translated_text="Merhaba [player_name]!",
            source_lang="en", target_lang="tr", engine=TranslationEngine.GOOGLE, success=True,
        ))
        t.set_fallback_translator(fallback)

        asyncio.run(t.translate_single(req))
        sent = fallback.translate_single.await_args.args[0]
        assert sent.text == source
        assert sent.engine == TranslationEngine.GOOGLE
        assert "preprotected" not in sent.metadata
        assert "placeholders" not in sent.metadata
        assert sent.metadata["original_text"] == source

    def test_batch_restores_placeholders_even_when_model_unescapes_tags(self):
        """Models often return <ph> tags unescaped inside <item>; inner content must survive."""
        import asyncio
        from src.core.translator import TranslationEngine

        source = "Hello [player_name], {color=#f00}welcome{/color}!"
        req0, protected, _ = self._protected_request(source)
        req1 = TranslationRequest(text="Good evening", source_lang="en", target_lang="tr",
                                  engine=TranslationEngine.GEMINI,
                                  metadata={"preprotected": True, "original_text": "Good evening",
                                            "placeholders": {}, "xml_mode": True})
        answer0 = protected.replace("Hello", "Merhaba").replace("welcome", "hoş geldin")
        xml = (
            "<translations>\n"
            f'  <item id="0">{answer0}</item>\n'
            '  <item id="1">İyi akşamlar</item>\n'
            "</translations>"
        )
        t, mock_models = self._make_gemini(response_text=xml)

        results = asyncio.run(t.translate_batch([req0, req1]))
        assert mock_models.generate_content.await_count == 1
        assert results[0].translated_text == "Merhaba [player_name], {color=#f00}hoş geldin{/color}!"
        assert results[1].translated_text == "İyi akşamlar"

    def test_batch_chunks_by_batch_size(self):
        """Large request lists are split into ai_batch_size XML chunks (not one giant request)."""
        import asyncio
        from src.core.ai_translator import GeminiTranslator
        from src.core.translator import TranslationEngine

        t = GeminiTranslator(api_key="fake-key", batch_size=4)
        seen_sizes = []

        async def fake_generate(contents, system_instruction, max_tokens, temperature):
            ids = [int(i) for i in re.findall(r'<item id="(\d+)">', contents)]
            seen_sizes.append(len(ids))
            return "<translations>" + "".join(f'<item id="{i}">T{i}</item>' for i in ids) + "</translations>"

        t._generate = fake_generate
        reqs = [TranslationRequest(text=f"Line {i}", source_lang="en", target_lang="tr",
                                   engine=TranslationEngine.GEMINI) for i in range(10)]
        results = asyncio.run(t.translate_batch(reqs))
        assert sorted(seen_sizes) == [2, 4, 4]
        assert len(results) == 10
        assert all(r.success for r in results)
        assert results[9].translated_text == "T1"  # id is chunk-local; last chunk has 2 items
        assert results[4].translated_text == "T0"

    def test_batch_missing_item_falls_back_to_single(self):
        import asyncio
        from src.core.translator import TranslationEngine

        t, mock_models = self._make_gemini(response_text='<translations><item id="0">Bir</item></translations>')
        single_resp = MagicMock()
        single_resp.text = "İki"
        batch_resp = MagicMock()
        batch_resp.text = '<translations><item id="0">Bir</item></translations>'
        mock_models.generate_content = AsyncMock(side_effect=[batch_resp, single_resp])

        reqs = [TranslationRequest(text="One", source_lang="en", target_lang="tr", engine=TranslationEngine.GEMINI),
                TranslationRequest(text="Two", source_lang="en", target_lang="tr", engine=TranslationEngine.GEMINI)]
        results = asyncio.run(t.translate_batch(reqs))
        assert results[0].translated_text == "Bir"
        assert results[1].translated_text == "İki"
        assert mock_models.generate_content.await_count == 2

    def test_unchanged_answer_is_still_a_success(self):
        """Same-text answers (e.g. proper nouns) are legitimate results, not failures."""
        import asyncio
        from src.core.translator import TranslationEngine

        t, _ = self._make_gemini(response_text="Sorcerer")
        req = TranslationRequest(text="Sorcerer", source_lang="en", target_lang="tr", engine=TranslationEngine.GEMINI)
        result = asyncio.run(t.translate_single(req))
        assert result.success is True
        assert result.translated_text == "Sorcerer"


# ─────────────────────────────────────────────────────────────────────────────
# TranslationResult Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestTranslationResult:
    def test_successful_result(self):
        result = TranslationResult(
            original_text="Hello",
            translated_text="Merhaba",
            source_lang="en",
            target_lang="tr",
            engine=TranslationEngine.OPENAI,
            success=True,
        )
        assert result.success is True
        assert not result.quota_exceeded

    def test_failed_result(self):
        result = TranslationResult(
            original_text="Hello",
            translated_text="Hello",
            source_lang="en",
            target_lang="tr",
            engine=TranslationEngine.GEMINI,
            success=False,
            error="API error",
        )
        assert result.success is False

    def test_quota_exceeded_flag(self):
        result = TranslationResult(
            original_text="Hello",
            translated_text="Hello",
            source_lang="en",
            target_lang="tr",
            engine=TranslationEngine.OPENAI,
            success=False,
            error="Rate limit",
            quota_exceeded=True,
        )
        assert result.quota_exceeded is True


# ─────────────────────────────────────────────────────────────────────────────
# Model Profile (Hy-MT2) Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestModelProfileDetection:
    @pytest.mark.parametrize("name,expected", [
        ("Hy-MT2-7B-GGUF", "hy_mt2"),
        ("hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M", "hy_mt2"),
        ("tencent/Hy-MT2-7B-GGUF", "hy_mt2"),
        ("tencent/Hy-MT1.5-1.8B", "hy_mt2"),
        ("hunyuan-mt-7b", "hy_mt2"),
        ("hy_mt2", "hy_mt2"),
        ("Hy MT2 30B-A3B", "hy_mt2"),
        ("llama3.2", None),
        ("gpt-4o-mini", None),
        ("mistral-7b", None),
        ("qwen2-mt-7b", None),  # different "-mt" family, must NOT match
        ("", None),
        (None, None),
    ])
    def test_detect_model_profile(self, name, expected):
        from src.core.ai_translator import detect_model_profile
        assert detect_model_profile(name) == expected

    @pytest.mark.parametrize("code,expected", [
        ("tr", "Turkish"),
        ("en", "English"),
        ("he", "Hebrew"),
        ("zh-CN", "Chinese"),
        ("auto", "the original language"),
        ("", "the original language"),
        ("xx", "xx"),  # unknown -> passthrough
    ])
    def test_resolve_language_name(self, code, expected):
        from src.core.ai_translator import _resolve_language_name
        assert _resolve_language_name(code) == expected


class TestHyMT2ProfileBehavior:
    def _make(self, model="hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M", **overrides):
        from src.core.ai_translator import LocalLLMTranslator
        cfg = _make_config(local_llm_model=model, **overrides)
        return LocalLLMTranslator(config_manager=cfg)

    def test_profile_autodetected(self):
        assert self._make()._model_profile == "hy_mt2"

    def test_forced_generic_overrides_autodetect(self):
        assert self._make(ai_model_profile="generic")._model_profile is None

    def test_forced_hy_mt2_on_unrelated_model(self):
        t = self._make(model="llama3.2", ai_model_profile="hy_mt2")
        assert t._model_profile == "hy_mt2"

    def test_generic_model_keeps_no_profile(self):
        assert self._make(model="llama3.2")._model_profile is None

    def test_sampling_kwargs_hy_mt2(self):
        t = self._make()
        kw = t._get_sampling_kwargs()
        assert kw["top_p"] == 0.6
        assert kw["extra_body"]["top_k"] == 20
        assert kw["extra_body"]["repetition_penalty"] == 1.05

    def test_sampling_kwargs_generic_empty(self):
        t = self._make(model="llama3.2")
        assert t._get_sampling_kwargs() == {}

    def test_temperature_defaults_to_model_card(self):
        assert self._make()._get_temperature() == 0.7

    def test_temperature_respects_user_override(self):
        assert self._make(ai_temperature=0.2)._get_temperature() == 0.2

    def test_temperature_generic_uses_config(self):
        assert self._make(model="llama3.2", ai_temperature=0.5)._get_temperature() == 0.5

    def test_single_prompt_contains_official_instruction(self):
        t = self._make()
        prompt = t._build_hy_mt2_single_prompt(
            "Turkish", 'Hello <ph id="0">[name]</ph>', {"0": "[name]"}, xml_mode=True
        )
        assert "Translate the following text into Turkish" in prompt
        assert "only output the translated result" in prompt
        assert 'Hello <ph id="0">[name]</ph>' in prompt

    def test_single_prompt_lists_delimiters_when_present(self):
        t = self._make()
        prompt = t._build_hy_mt2_single_prompt(
            "Turkish", 'Hi <ph id="0">[x]</ph>', {"0": "[x]"}, xml_mode=True
        )
        assert "retain the exact same number of delimiters" in prompt
        assert '<ph id="0">' in prompt

    def test_single_prompt_omits_delimiter_note_when_empty(self):
        t = self._make()
        prompt = t._build_hy_mt2_single_prompt("Turkish", "Hello", {}, xml_mode=True)
        assert "retain the exact same number of delimiters" not in prompt

    def test_single_prompt_text_is_the_only_content_after_colon(self):
        """Hy-MT2 treats everything after 'instruction:\\n\\n' as source text.

        Regression: the delimiter note used to be appended after the colon,
        so the model translated/echoed the instruction itself into the output.
        """
        t = self._make()
        text = 'Hi <ph id="0">[x]</ph>, welcome.'
        prompt = t._build_hy_mt2_single_prompt(
            "Turkish", text, {"0": "[x]"}, xml_mode=True
        )
        # Instruction ends with the colon separator, then ONLY the text follows
        assert prompt.endswith(":\n\n" + text)
        instruction_part = prompt[: -len(text)]
        assert "Translate the following text into Turkish" in instruction_part
        assert "retain the exact same number of delimiters" in instruction_part
        # No instruction content may leak after the separator
        after_separator = prompt[len(instruction_part):]
        assert after_separator == text

    def test_batch_prompt_is_format_locked(self):
        t = self._make()
        prompt = t._build_hy_mt2_batch_prompt("English", "Turkish")
        assert "translate from English into Turkish" in prompt
        assert '"text"' in prompt
        assert '"translations"' in prompt
        assert "nothing else" in prompt

    def test_call_api_omits_system_message_when_none(self):
        import asyncio
        from unittest.mock import AsyncMock

        t = self._make()
        captured = {}

        async def fake_create(**kwargs):
            captured.update(kwargs)
            resp = MagicMock()
            resp.choices = [MagicMock()]
            resp.choices[0].message.content = "Merhaba"
            resp.choices[0].finish_reason = "stop"
            return resp

        t._client = MagicMock()
        t._client.chat.completions.create = AsyncMock(side_effect=fake_create)
        asyncio.run(t._call_api(None, "Translate the following text into Turkish."))

        roles = [m["role"] for m in captured["messages"]]
        assert "system" not in roles
        assert roles[0] == "user"

    def test_call_api_keeps_system_message_for_generic(self):
        import asyncio
        from unittest.mock import AsyncMock

        t = self._make(model="llama3.2")
        captured = {}

        async def fake_create(**kwargs):
            captured.update(kwargs)
            resp = MagicMock()
            resp.choices = [MagicMock()]
            resp.choices[0].message.content = "Merhaba"
            resp.choices[0].finish_reason = "stop"
            return resp

        t._client = MagicMock()
        t._client.chat.completions.create = AsyncMock(side_effect=fake_create)
        asyncio.run(t._call_api("You are a translator.", "Hello"))

        assert captured["messages"][0]["role"] == "system"
        assert captured["messages"][0]["content"] == "You are a translator."
        # Generic path must not inject top_p/extra_body
        assert "top_p" not in captured
        assert "extra_body" not in captured

    def test_call_api_forwards_sampling_kwargs(self):
        import asyncio
        from unittest.mock import AsyncMock

        t = self._make()
        captured = {}

        async def fake_create(**kwargs):
            captured.update(kwargs)
            resp = MagicMock()
            resp.choices = [MagicMock()]
            resp.choices[0].message.content = "Merhaba"
            resp.choices[0].finish_reason = "stop"
            return resp

        t._client = MagicMock()
        t._client.chat.completions.create = AsyncMock(side_effect=fake_create)
        asyncio.run(t._call_api(None, "Translate...", **t._get_sampling_kwargs()))

        assert captured["top_p"] == 0.6
        assert captured["extra_body"]["top_k"] == 20
        assert captured["temperature"] == 0.7
