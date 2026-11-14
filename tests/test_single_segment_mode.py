# -*- coding: utf-8 -*-
"""
Tests for single-segment translation mode (v2.8.17).

Pure translation models (Tencent Hy-MT / Hunyuan-MT) are not instruction
models: their model card defines one shape, "translate the following text
into X". Wrapping their requests in scene/XML/JSON scaffolding with [ID] tags
made small quants mangle the structure, which forced a slow per-line retry
spiral. They now bypass batching entirely, as does the user-selectable
ai_batch_format="single" option.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock


from src.core.ai_translator import (
    LocalLLMTranslator,
    profile_prefers_single_segment,
)
from src.core.translator import TranslationEngine, TranslationRequest, TranslationResult


def _config(**overrides):
    settings = dict(
        local_llm_model="llama3.2",
        local_llm_url="http://localhost:11434/v1",
        openai_model="gpt-4o-mini",
        ai_model_profile="auto",
        ai_batch_format="scene",
        ai_batch_size=15,
        ai_scene_batch_size=15,
        ai_temperature=0.3,
        ai_timeout=60,
        ai_max_tokens=2048,
        ai_concurrency=2,
        ai_retry_count=1,
        ai_custom_system_prompt="",
    )
    settings.update(overrides)
    return SimpleNamespace(
        translation_settings=SimpleNamespace(**settings),
        api_keys=SimpleNamespace(openai_api_key=""),
    )


def _translator(**overrides):
    return LocalLLMTranslator(config_manager=_config(**overrides))


def _requests(n):
    return [
        TranslationRequest(f"Line {i}", "en", "tr", TranslationEngine.LOCAL_LLM)
        for i in range(n)
    ]


class TestModeDetection:
    def test_hy_mt2_model_name_prefers_single(self):
        t = _translator(local_llm_model="hf.co/tencent/Hy-MT2-1.8B-GGUF:Q4_K_M")
        assert t._is_hy_mt2() is True
        assert t._prefers_single_segment() is True

    def test_forced_profile_prefers_single(self):
        t = _translator(local_llm_model="my-custom-model", ai_model_profile="hy_mt2")
        assert t._prefers_single_segment() is True

    def test_batch_format_single_prefers_single(self):
        t = _translator(ai_batch_format="single")
        assert t._is_hy_mt2() is False
        assert t._prefers_single_segment() is True

    def test_generic_model_keeps_batching(self):
        t = _translator()
        assert t._prefers_single_segment() is False

    def test_config_level_helper_matches(self):
        assert profile_prefers_single_segment(_config(ai_model_profile="hy_mt2")) is True
        assert profile_prefers_single_segment(
            _config(local_llm_model="Hunyuan-MT-7B")
        ) is True
        assert profile_prefers_single_segment(_config()) is False
        assert profile_prefers_single_segment(None) is False


class TestBatchBypass:
    def test_batch_fans_out_to_single_and_keeps_order(self):
        t = _translator(ai_batch_format="single")
        seen = []

        async def fake_single(req):
            seen.append(req.text)
            await asyncio.sleep(0)  # force interleaving between gathered tasks
            return TranslationResult(
                req.text, f"TR:{req.text}", req.source_lang, req.target_lang,
                t._engine, True,
            )

        t.translate_single = fake_single
        results = asyncio.run(t.translate_batch(_requests(5)))

        assert [r.translated_text for r in results] == [f"TR:Line {i}" for i in range(5)]
        assert sorted(seen) == sorted(f"Line {i}" for i in range(5))

    def test_no_scene_or_xml_scaffolding_is_built(self, monkeypatch):
        """The model must never see ### SCENE START ### or <translations> in this mode."""
        t = _translator(local_llm_model="Hy-MT2-1.8B")
        sent = []

        async def fake_call_api(system_prompt, user_content, **kwargs):
            sent.append(user_content)
            return "çeviri"

        monkeypatch.setattr(t, "_call_api", fake_call_api)
        results = asyncio.run(t.translate_batch(_requests(3)))

        assert len(sent) == 3, "one API call per line"
        assert all("SCENE START" not in c for c in sent)
        assert all("<translations>" not in c for c in sent)
        assert all("[0]" not in c for c in sent)
        assert all(r.success for r in results)

    def test_semaphore_is_not_nested(self):
        """translate_single takes the semaphore; the fan-out must not take it again."""
        t = _translator(ai_batch_format="single", ai_concurrency=1)
        active = {"now": 0, "max": 0}

        async def fake_single(req):
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
            async with t._get_semaphore():
                await asyncio.sleep(0)
            active["now"] -= 1
            return TranslationResult(
                req.text, "ok", req.source_lang, req.target_lang, t._engine, True
            )

        t.translate_single = fake_single
        # Would hang forever if _translate_each_single also held the semaphore.
        results = asyncio.run(asyncio.wait_for(t.translate_batch(_requests(4)), timeout=5))
        assert len(results) == 4
        assert active["max"] > 1, "fan-out itself must not serialise the requests"

    def test_stop_callback_short_circuits_remaining_items(self):
        t = _translator(ai_batch_format="single")
        t.should_stop_callback = lambda: True
        t.translate_single = AsyncMock()

        results = asyncio.run(t.translate_batch(_requests(3)))
        assert t.translate_single.await_count == 0
        assert all(r.metadata.get("skipped") for r in results)
        assert [r.translated_text for r in results] == [f"Line {i}" for i in range(3)]

    def test_generic_model_still_batches(self, monkeypatch):
        t = _translator(ai_batch_format="scene")
        sent = []

        async def fake_call_api(system_prompt, user_content, **kwargs):
            sent.append(user_content)
            return "\n".join(f"[{i}] çeviri {i}" for i in range(3))

        monkeypatch.setattr(t, "_call_api", fake_call_api)
        asyncio.run(t.translate_batch(_requests(3)))
        assert len(sent) == 1, "scene mode must still send one batched request"
        assert "SCENE START" in sent[0]


class TestConfigValidation:
    def test_single_is_a_valid_batch_format(self):
        from src.utils.config import TranslationSettings

        ts = TranslationSettings(ai_batch_format="single")
        assert ts.ai_batch_format == "single"

        ts_bad = TranslationSettings(ai_batch_format="nonsense")
        assert ts_bad.ai_batch_format == "scene"

    def test_settings_backend_accepts_single(self):
        from unittest.mock import MagicMock
        from src.backend.settings_backend import SettingsBackend

        cfg = MagicMock()
        cfg.translation_settings.selected_engine = "local_llm"
        backend = SettingsBackend(cfg, MagicMock())
        backend.set_ai_batch_format("single")
        assert cfg.translation_settings.ai_batch_format == "single"
