# -*- coding: utf-8 -*-
"""Tests for AI translator implementations (OpenAI, DeepSeek, LocalLLM, Gemini)."""

import json as _json
import sys
from unittest.mock import MagicMock, patch
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
        assert t._semaphore_count == 2

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

    def test_instantiation_with_mocked_genai(self):
        mock_genai = MagicMock()
        mock_genai.types = MagicMock()
        mock_genai.types.GenerationConfig = MagicMock()
        mock_genai.GenerativeModel = MagicMock()
        mock_genai.configure = MagicMock()

        import src.core.ai_translator as ai_mod
        with patch.object(ai_mod, "_GEMINI_AVAILABLE", True), \
             patch.object(ai_mod, "genai", mock_genai, create=True):
            t = ai_mod.GeminiTranslator(api_key="test-key")
            mock_genai.configure.assert_called_once_with(api_key="test-key")
            assert t._engine == TranslationEngine.GEMINI

    def test_get_supported_languages(self):
        mock_genai = MagicMock()
        mock_genai.GenerativeModel = MagicMock()
        mock_genai.configure = MagicMock()

        import src.core.ai_translator as ai_mod
        with patch.object(ai_mod, "_GEMINI_AVAILABLE", True), \
             patch.object(ai_mod, "genai", mock_genai, create=True):
            t = ai_mod.GeminiTranslator(api_key="test-key")
            langs = t.get_supported_languages()
            assert isinstance(langs, dict)
            assert "tr" in langs
            assert "en" in langs


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
