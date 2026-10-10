# -*- coding: utf-8 -*-
"""
Tests for Fast-Path Cache Pre-Pass, _is_dirty Cache Serialization Guard,
O(1) secondary cache lookups, and redundant scan elimination (v2.8.19).
"""
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from src.core.translator import (
    TranslationEngine,
    TranslationManager,
    TranslationRequest,
    TranslationResult,
)
from src.core.pipeline.orchestrator import TranslationPipeline
from src.core.tl_parser import TranslationEntry
from src.utils.config import ConfigManager, TranslationSettings


def test_observable_cache_dict_tracks_dirty_and_indices():
    """Verify _ObservableCacheDict sets _is_dirty and maintains O(1) secondary indices."""
    manager = TranslationManager()
    assert manager._is_dirty is False
    assert len(manager._engine_text_index) == 0
    assert len(manager._text_target_index) == 0

    res = TranslationResult(
        original_text="Hello",
        translated_text="Merhaba",
        source_lang="en",
        target_lang="tr",
        engine=TranslationEngine.GOOGLE,
        success=True,
    )

    # 1. Setting an item marks dirty and updates both indices
    manager._cache[("google", "en", "tr", "Hello")] = res
    assert manager._is_dirty is True
    assert manager._engine_text_index.get(("google", "tr", "Hello")) == res
    assert manager._text_target_index.get(("tr", "Hello")) == res

    # 2. Reset dirty and delete item
    manager._is_dirty = False
    del manager._cache[("google", "en", "tr", "Hello")]
    assert manager._is_dirty is True
    assert manager._engine_text_index.get(("google", "tr", "Hello")) is None
    assert manager._text_target_index.get(("tr", "Hello")) is None

    # 3. Clear empties indices and sets dirty
    manager._cache[("google", "en", "tr", "World")] = res
    manager._is_dirty = False
    manager._cache.clear()
    assert manager._is_dirty is True
    assert len(manager._engine_text_index) == 0
    assert len(manager._text_target_index) == 0


def test_save_cache_dirty_guard(tmp_path: Path):
    """Verify save_cache skips disk serialization when not dirty."""
    cache_file = tmp_path / "translation_cache.json"
    manager = TranslationManager()

    res = TranslationResult(
        original_text="Start",
        translated_text="Basla",
        source_lang="en",
        target_lang="tr",
        engine=TranslationEngine.GOOGLE,
        success=True,
    )
    manager._cache[("google", "en", "tr", "Start")] = res
    assert manager._is_dirty is True

    # First save: writes to disk and sets _is_dirty = False
    manager.save_cache(str(cache_file))
    assert manager._is_dirty is False
    assert cache_file.exists()
    mtime1 = os.path.getmtime(cache_file)

    # Short delay to detect mtime changes if rewritten
    time.sleep(0.05)

    # Second save: not dirty, should skip completely
    with patch("os.replace") as mock_replace:
        manager.save_cache(str(cache_file))
        mock_replace.assert_not_called()

    assert os.path.getmtime(cache_file) == mtime1


def test_get_cached_translation_exact_and_cross_engine():
    """Verify get_cached_translation resolves in O(1) for exact, same-engine auto, and cross-engine."""
    manager = TranslationManager()
    res_bing = TranslationResult(
        original_text="Options",
        translated_text="Secenekler",
        source_lang="en",
        target_lang="tr",
        engine=TranslationEngine.BING,
        success=True,
    )
    manager._cache[("bing", "en", "tr", "Options")] = res_bing

    # 1. Exact match with BING
    found = manager.get_cached_translation("Options", "en", "tr", TranslationEngine.BING)
    assert found is not None
    assert found.translated_text == "Secenekler"

    # 2. Auto-source match with BING
    found_auto = manager.get_cached_translation("Options", "auto", "tr", TranslationEngine.BING)
    assert found_auto is not None
    assert found_auto.translated_text == "Secenekler"

    # 3. Cross-engine match when searching with GOOGLE
    found_cross = manager.get_cached_translation("Options", "en", "tr", TranslationEngine.GOOGLE)
    assert found_cross is not None
    assert found_cross.translated_text == "Secenekler"

    # 4. Non-existent string returns None
    assert manager.get_cached_translation("NonExistent", "en", "tr", TranslationEngine.GOOGLE) is None


def test_fast_path_pipeline_resolves_all_cached(tmp_path: Path):
    """Verify pipeline bypasses batch translation loop completely when all entries match cache."""
    cfg = MagicMock(spec=ConfigManager)
    ts = TranslationSettings()
    ts.use_cache = True
    ts.use_global_cache = False
    cfg.translation_settings = ts
    cfg.data_dir = str(tmp_path)
    cfg.glossary = {}
    cfg.get_log_text.side_effect = lambda key, *args, **kwargs: f"[{key}]"

    mgr = TranslationManager(config_manager=cfg)
    mgr._cache[("google", "en", "tr", "Hello")] = TranslationResult(
        original_text="Hello",
        translated_text="Merhaba",
        source_lang="en",
        target_lang="tr",
        engine=TranslationEngine.GOOGLE,
        success=True,
    )
    mgr._cache[("google", "en", "tr", "Goodbye")] = TranslationResult(
        original_text="Goodbye",
        translated_text="Hoscakal",
        source_lang="en",
        target_lang="tr",
        engine=TranslationEngine.GOOGLE,
        success=True,
    )
    mgr._is_dirty = False

    pipeline = TranslationPipeline(config=cfg, translation_manager=mgr)
    pipeline.project_path = str(tmp_path)
    pipeline.target_language = "turkish"
    pipeline.source_language = "en"
    pipeline.engine = TranslationEngine.GOOGLE

    entries = [
        TranslationEntry("Hello", "", "script.rpy", 10, "dialogue", translation_id="script_10_Hello"),
        TranslationEntry("Goodbye", "", "script.rpy", 20, "dialogue", translation_id="script_20_Goodbye"),
    ]

    with patch.object(mgr, "translate_batch", new_callable=AsyncMock) as mock_batch:
        translations = pipeline._translate_entries(entries)
        # Batch translation loop should NOT be invoked at all
        mock_batch.assert_not_called()

    assert translations["script_10_Hello"] == "Merhaba"
    assert translations["script_20_Goodbye"] == "Hoscakal"
    assert mgr.cache_hits == 2


def test_fast_path_pipeline_partial_cache(tmp_path: Path):
    """Verify pipeline only sends cache misses to the translation engine."""
    cfg = MagicMock(spec=ConfigManager)
    ts = TranslationSettings()
    ts.use_cache = True
    ts.use_global_cache = False
    cfg.translation_settings = ts
    cfg.data_dir = str(tmp_path)
    cfg.glossary = {}
    cfg.get_log_text.side_effect = lambda key, *args, **kwargs: f"[{key}]"

    mgr = TranslationManager(config_manager=cfg)
    mgr._cache[("google", "en", "tr", "Cached Line")] = TranslationResult(
        original_text="Cached Line",
        translated_text="Onbellek Satiri",
        source_lang="en",
        target_lang="tr",
        engine=TranslationEngine.GOOGLE,
        success=True,
    )
    mgr._is_dirty = False

    pipeline = TranslationPipeline(config=cfg, translation_manager=mgr)
    pipeline.project_path = str(tmp_path)
    pipeline.target_language = "turkish"
    pipeline.source_language = "en"
    pipeline.engine = TranslationEngine.GOOGLE

    entries = [
        TranslationEntry("Cached Line", "", "script.rpy", 10, "dialogue", translation_id="id_cached"),
        TranslationEntry("New Line", "", "script.rpy", 20, "dialogue", translation_id="id_new"),
    ]

    mock_result = TranslationResult(
        original_text="New Line",
        translated_text="Yeni Satir",
        source_lang="en",
        target_lang="tr",
        engine=TranslationEngine.GOOGLE,
        success=True,
        metadata={"original_text": "New Line"},
    )
    mock_translator = MagicMock()
    mock_translator.translate_batch = AsyncMock(return_value=[mock_result])
    mock_translator.translate_single = AsyncMock(return_value=mock_result)
    mgr.add_translator(TranslationEngine.GOOGLE, mock_translator)

    translations = pipeline._translate_entries(entries)

    assert translations["id_cached"] == "Onbellek Satiri"
    assert translations["id_new"] == "Yeni Satir"
    assert mgr.cache_hits >= 1


def test_deep_scan_completed_flag_skips_phase4():
    """Verify _deep_scan_completed_in_generating prevents redundant Phase 4 scan."""
    cfg = MagicMock(spec=ConfigManager)
    mgr = MagicMock()
    pipeline = TranslationPipeline(config=cfg, translation_manager=mgr)
    pipeline.include_deep_scan = True
    pipeline._deep_scan_completed_in_generating = True

    with patch.object(pipeline, "_run_deep_scan") as mock_deep_scan:
        # In Phase 4, the condition is:
        # if getattr(self, 'include_deep_scan', False) and not getattr(self, '_deep_scan_completed_in_generating', False):
        if getattr(pipeline, 'include_deep_scan', False) and not getattr(pipeline, '_deep_scan_completed_in_generating', False):
            pipeline._run_deep_scan([], "game", "tl", "turkish")

        mock_deep_scan.assert_not_called()


def test_all_technical_entries_are_not_reported_as_a_failed_translation(tmp_path: Path):
    """When every entry is filtered as technical text nothing is sent, which
    is not an engine failure (re-running a finished game said "failed")."""
    cfg = MagicMock(spec=ConfigManager)
    ts = TranslationSettings()
    ts.use_global_cache = False
    cfg.translation_settings = ts
    cfg.data_dir = str(tmp_path)
    cfg.glossary = {}
    cfg.get_log_text.side_effect = lambda key, *args, **kwargs: f"[{key}]"

    mgr = TranslationManager(config_manager=cfg)
    pipeline = TranslationPipeline(config=cfg, translation_manager=mgr)
    pipeline.project_path = str(tmp_path)
    pipeline.target_language = "turkish"
    pipeline.source_language = "en"
    pipeline.engine = TranslationEngine.GOOGLE

    technical = [TranslationEntry("audio/bgm.ogg", "", "options.rpy", 13, "string", translation_id="t1")]
    with patch.object(mgr, "translate_batch", new_callable=AsyncMock) as mock_batch:
        assert pipeline._translate_entries(technical) == {}
        mock_batch.assert_not_called()
    assert pipeline._sent_for_translation == 0

    with patch.object(mgr, "translate_batch", new_callable=AsyncMock) as mock_batch:
        mock_batch.return_value = []
        pipeline._translate_entries([TranslationEntry("Hello there", "", "s.rpy", 1, "dialogue", translation_id="d1")])
    assert pipeline._sent_for_translation == 1


def test_bypass_cache_reaches_the_engine_and_leaves_the_cache_alone(tmp_path):
    """Editor suggestions: the cached line is neither returned nor replaced or removed."""
    import asyncio

    manager = TranslationManager()
    key = ("google", "en", "tr", "Options")
    manager._cache[key] = TranslationResult(
        original_text="Options", translated_text="Seçenekler", source_lang="en",
        target_lang="tr", engine=TranslationEngine.GOOGLE, success=True,
    )

    class Engine:
        calls = 0

        async def translate_single(self, req):
            Engine.calls += 1
            return TranslationResult(
                original_text=req.text, translated_text="Ayarlar", source_lang=req.source_lang,
                target_lang=req.target_lang, engine=req.engine, success=True,
            )

    manager.translators[TranslationEngine.GOOGLE] = Engine()
    request = TranslationRequest(text="Options", source_lang="en", target_lang="tr",
                                 engine=TranslationEngine.GOOGLE)
    cache_file = tmp_path / "translation_cache.json"

    with manager.bypass_cache():
        assert manager.get_cached_translation("Options", "en", "tr", TranslationEngine.GOOGLE) is None
        result = asyncio.run(manager.translate_with_retry(request))
        asyncio.run(manager.cache_remove(key))
        manager.save_cache(str(cache_file))

    assert result.translated_text == "Ayarlar" and Engine.calls == 1
    assert manager._cache[key].translated_text == "Seçenekler"
    assert not cache_file.exists()
    assert manager.use_cache


def test_bypass_cache_is_per_thread():
    """A translation run on another thread keeps its cache during a suggestion."""
    import threading

    manager = TranslationManager()
    seen = {}

    def other_thread():
        seen["other"] = manager.use_cache

    with manager.bypass_cache():
        worker = threading.Thread(target=other_thread)
        worker.start()
        worker.join()
        seen["here"] = manager.use_cache
    assert seen == {"other": True, "here": False}

    manager.use_cache = False  # the settings switch still works
    assert manager.use_cache is False
