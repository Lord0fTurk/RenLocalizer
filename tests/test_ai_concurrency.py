# -*- coding: utf-8 -*-
"""
AI Concurrency in the batched modes (GitHub #21).

translate_batch() cuts its requests into chunks and runs them in parallel,
bounded by ai_concurrency. The pipeline used to hand it one chunk's worth of
lines per step (ai_batch_size), so scene/JSON/XML sent one request at a time
whatever the setting said; only single-line mode, which fans out per line,
reached the configured concurrency.
"""

import asyncio
import json
import re
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.ai_translator import LocalLLMTranslator, ai_lines_per_request
from src.core.pipeline.orchestrator import TranslationPipeline
from src.core.pipeline.translating import get_effective_translation_batch_size
from src.core.tl_parser import TranslationEntry
from src.core.translator import TranslationEngine, TranslationManager
from src.utils.config import ConfigManager, TranslationSettings

_SCENE_ID_RE = re.compile(r"^\[(\d+)\]", re.MULTILINE)
_XML_ID_RE = re.compile(r'<item id="(\d+)">')


def _settings(**overrides) -> TranslationSettings:
    ts = TranslationSettings()
    ts.use_global_cache = False
    ts.ai_batch_size = 15
    ts.ai_scene_batch_size = 15
    ts.ai_concurrency = 4
    ts.ai_request_delay = 0.0
    for key, value in overrides.items():
        setattr(ts, key, value)
    return ts


def _config(tmp_path, **overrides):
    cfg = MagicMock(spec=ConfigManager)
    cfg.translation_settings = _settings(**overrides)
    cfg.data_dir = str(tmp_path)
    cfg.glossary = {}
    cfg.get_log_text.side_effect = lambda key, default="", **kwargs: default or key
    return cfg


def _reply(batch_format: str, user_content: str) -> str:
    """A well-formed model answer in the shape the request asked for."""
    if batch_format == "scene":
        ids = [int(i) for i in _SCENE_ID_RE.findall(user_content)]
        return "\n".join(f"[{i}] Satır {i}" for i in ids)
    if batch_format == "xml":
        ids = [int(i) for i in _XML_ID_RE.findall(user_content)]
        items = "".join(f'<item id="{i}">Satır {i}</item>' for i in ids)
        return f"<translations>{items}</translations>"
    ids = [item["id"] for item in json.loads(user_content)["items_to_translate"]]
    return json.dumps({"translations": [{"id": i, "translated_text": f"Satır {i}"} for i in ids]})


def _run_pipeline(tmp_path, line_count: int, **overrides):
    """Translates line_count dialogue lines through the real pipeline and
    TranslationManager with a Local LLM whose API call is faked."""
    cfg = _config(tmp_path, **overrides)
    batch_format = cfg.translation_settings.ai_batch_format

    translator = LocalLLMTranslator(config_manager=cfg)
    translator.probe_endpoint = AsyncMock(return_value=None)
    stats = {"active": 0, "peak": 0, "sizes": []}

    async def fake_call_api(system_prompt, user_content, **kwargs):
        stats["active"] += 1
        stats["peak"] = max(stats["peak"], stats["active"])
        try:
            await asyncio.sleep(0.02)
            reply = _reply(batch_format, user_content)
            stats["sizes"].append(reply.count("Satır"))
            return reply
        finally:
            stats["active"] -= 1

    translator._call_api = fake_call_api

    manager = TranslationManager(config_manager=cfg)
    manager.add_translator(TranslationEngine.LOCAL_LLM, translator)
    pipeline = TranslationPipeline(config=cfg, translation_manager=manager)
    pipeline.project_path = str(tmp_path)
    pipeline.target_language = "turkish"
    pipeline.source_language = "en"
    pipeline.engine = TranslationEngine.LOCAL_LLM

    entries = [
        TranslationEntry(
            f"She looked at the clock for the {i}th time.", "", "script.rpy", i + 1,
            "dialogue", translation_id=f"line_{i}",
        )
        for i in range(line_count)
    ]
    translations = pipeline._translate_entries(entries)
    return translations, stats


@pytest.mark.parametrize("batch_format", ["scene", "json", "xml"])
def test_batched_modes_use_the_configured_concurrency(tmp_path, batch_format):
    translations, stats = _run_pipeline(tmp_path, 60, ai_batch_format=batch_format)

    assert stats["peak"] == 4
    assert all(translations.get(f"line_{i}", "").startswith("Satır") for i in range(60))


def test_concurrency_never_exceeds_the_setting(tmp_path):
    _, stats = _run_pipeline(tmp_path, 60, ai_batch_format="json", ai_concurrency=2)
    assert stats["peak"] == 2


def test_scene_block_size_sets_the_request_size(tmp_path):
    """ai_scene_batch_size larger than ai_batch_size used to be cut down to
    ai_batch_size by the pipeline step."""
    _, stats = _run_pipeline(
        tmp_path, 60, ai_batch_format="scene",
        ai_batch_size=15, ai_scene_batch_size=30, ai_concurrency=1,
    )
    assert stats["sizes"] == [30, 30]


class TestStepSize:
    def _cfg(self, **overrides):
        cfg = MagicMock()
        cfg.translation_settings = _settings(**overrides)
        return cfg

    def test_ai_step_holds_one_request_per_parallel_slot(self):
        cfg = self._cfg(ai_batch_format="json", ai_batch_size=15, ai_concurrency=4)
        assert get_effective_translation_batch_size(TranslationEngine.LOCAL_LLM, cfg) == 60
        assert get_effective_translation_batch_size(TranslationEngine.OPENAI, cfg) == 60

    def test_scene_requests_are_sized_by_the_scene_block(self):
        cfg = self._cfg(ai_batch_format="scene", ai_scene_batch_size=10, ai_concurrency=3)
        assert ai_lines_per_request(cfg, TranslationEngine.LOCAL_LLM) == 10
        assert get_effective_translation_batch_size(TranslationEngine.LOCAL_LLM, cfg) == 30

    def test_a_larger_ai_batch_size_is_kept(self):
        cfg = self._cfg(ai_batch_format="scene", ai_batch_size=50, ai_scene_batch_size=15, ai_concurrency=2)
        assert get_effective_translation_batch_size(TranslationEngine.LOCAL_LLM, cfg) == 50

    def test_gemini_chunks_by_ai_batch_size_up_to_fifty(self):
        cfg = self._cfg(ai_batch_format="scene", ai_batch_size=80, ai_scene_batch_size=10, ai_concurrency=2)
        assert ai_lines_per_request(cfg, TranslationEngine.GEMINI) == 50
        assert get_effective_translation_batch_size(TranslationEngine.GEMINI, cfg) == 100

    def test_non_ai_engines_are_unchanged(self):
        cfg = self._cfg(ai_concurrency=8)
        cfg.translation_settings.max_batch_size = 200
        assert get_effective_translation_batch_size(TranslationEngine.GOOGLE, cfg) == 200
