# -*- coding: utf-8 -*-
"""Regression suite for RenLocalizer v2.9.1 hardening & bug-fix plan."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.app_backend import AppBackend
from src.backend.developer_backend import DeveloperBackend
from src.backend.editor_backend import EditorBackend
from src.backend.settings_backend import SettingsBackend
from src.core.ai_translator import (
    _DEEPSEEK_DEFAULT_MODEL,
    DeepSeekTranslator,
    GeminiTranslator,
    LocalLLMTranslator,
    OpenAITranslator,
    profile_prefers_single_segment,
)
from src.core.editor.project import load_language, save_edits, sync_translation_cache
from src.core.editor.store import EditorStore
from src.core.pipeline.orchestrator import TranslationPipeline
from src.core.pipeline.validating import needs_re_extraction
from src.core.tl_parser import TLParser, TranslationEntry
from src.core.translator import TranslationEngine, TranslationManager, TranslationRequest, TranslationResult
from src.core.translators.factory import build_translator
from src.core.translators.google import GoogleTranslator
from src.core.translators.router import EndpointRouter
from src.utils.config import ConfigManager


# ---------------------------------------------------------------------------
# Step 1: Settings, Hy-MT2 detection, factory reset, and factory routing
# ---------------------------------------------------------------------------


def test_settings_save_preserves_deepseek_and_advanced_fields(tmp_path: Path):
    cfg = ConfigManager(config_file=str(tmp_path / "config.json"))
    cfg.translation_settings.selected_engine = "deepseek"
    cfg.translation_settings.activate_language_on_launch = False
    cfg.translation_settings.translate_character_names = True
    cfg.translation_settings.enable_stateful_lexer = True
    cfg.translation_settings.ai_model_profile = "hy_mt2"
    cfg.translation_settings.ai_batch_format = "json"
    cfg.translation_settings.ai_scene_batch_size = 25
    cfg.translation_settings.deepseek_thinking = True
    cfg.app_settings.enable_desktop_notifications = False

    sb = SettingsBackend(cfg, MagicMock())
    sb.save_settings()

    reloaded = ConfigManager(config_file=str(tmp_path / "config.json"))
    ts = reloaded.translation_settings
    assert ts.selected_engine == "deepseek"
    assert ts.activate_language_on_launch is False
    assert ts.translate_character_names is True
    assert ts.enable_stateful_lexer is True
    assert ts.ai_model_profile == "hy_mt2"
    assert ts.ai_batch_format == "json"
    assert ts.ai_scene_batch_size == 25
    assert ts.deepseek_thinking is True
    assert reloaded.app_settings.enable_desktop_notifications is False


def test_factory_reset_deletes_run_state_and_engine_speed(tmp_path: Path):
    cfg_dir = tmp_path / "appdata"
    cfg_dir.mkdir(parents=True)
    for name in ("run_state.json", "engine_speed.json"):
        (cfg_dir / name).write_text("{}", encoding="utf-8")

    cfg = ConfigManager(config_file=str(cfg_dir / "config.json"))
    cfg.data_dir = cfg_dir
    sb = SettingsBackend(cfg, MagicMock())
    assert sb.factory_reset() is True

    assert not (cfg_dir / "run_state.json").exists()
    assert not (cfg_dir / "engine_speed.json").exists()


def test_hymt2_detected_for_builtin_gguf_and_emits_signal(tmp_path: Path):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication

    _ = QApplication.instance() or QApplication(sys.argv[:1])

    cfg = ConfigManager(config_file=str(tmp_path / "config.json"))
    cfg.translation_settings.local_llm_mode = "builtin"
    cfg.translation_settings.local_llm_model = "llama3.2"
    cfg.translation_settings.local_llm_gguf_path = str(tmp_path / "HY-MT1.5-1.8B-Q4_K_M.gguf")

    sb = SettingsBackend(cfg, MagicMock())
    assert sb.is_hy_mt2_model_detected() is True

    with patch("src.backend.app_backend.ConfigManager", return_value=cfg):
        app_be = AppBackend()
        emitted = []
        app_be.hyMt2StatusChanged.connect(lambda: emitted.append(True))
        app_be.localLlmMode = "external"
        app_be.localLlmMode = "builtin"
        app_be.localLlmGgufPath = str(tmp_path / "other.gguf")
        assert len(emitted) == 3


def test_factory_deepseek_url_only_redirects_openai(tmp_path: Path):
    cfg = ConfigManager(config_file=str(tmp_path / "config.json"))
    cfg.translation_settings.openai_base_url = "https://api.deepseek.com/v1"
    cfg.api_keys.openai_api_key = "sk-test"

    tr_openai = build_translator("openai", cfg)
    assert isinstance(tr_openai, DeepSeekTranslator)

    tr_google = build_translator("google", cfg)
    assert isinstance(tr_google, GoogleTranslator)


# ---------------------------------------------------------------------------
# Step 2.1: AI Translator isolation, error semantics, DeepSeek, LocalLLM, Gemini
# ---------------------------------------------------------------------------


def test_profile_prefers_single_segment_scoped_by_engine(tmp_path: Path):
    cfg = ConfigManager(config_file=str(tmp_path / "config.json"))
    cfg.translation_settings.ai_model_profile = "auto"
    cfg.translation_settings.local_llm_mode = "builtin"
    cfg.translation_settings.local_llm_gguf_path = str(tmp_path / "HY-MT1.5-1.8B-Q4_K_M.gguf")
    cfg.translation_settings.openai_model = "gpt-4o-mini"

    assert profile_prefers_single_segment(cfg, engine="local_llm") is True
    assert profile_prefers_single_segment(cfg, engine="openai") is False
    assert profile_prefers_single_segment(cfg, engine=TranslationEngine.OPENAI) is False

    # OpenAI translator must NOT silently inherit Hy-MT from config when forced
    cfg.translation_settings.ai_model_profile = "hy_mt2"
    oa = OpenAITranslator(api_key="sk-test", config_manager=cfg)
    assert oa._model_profile is None

    # LocalLLMTranslator DOES allow forced profile and picks up builtin GGUF hint
    cfg.translation_settings.ai_model_profile = "auto"
    ll = LocalLLMTranslator(config_manager=cfg)
    assert ll._model_profile == "hy_mt2"


def test_async_ai_error_vs_content_filter_outcomes(tmp_path: Path, monkeypatch):
    cfg = ConfigManager(config_file=str(tmp_path / "config.json"))
    cfg.translation_settings.ai_retry_count = 0
    tr = OpenAITranslator(api_key="sk-test", config_manager=cfg)

    from src.core import ai_translator as ai_mod

    class FakeAPIStatusError(Exception):
        def __init__(self, status_code: int):
            super().__init__(f"HTTP {status_code}")
            self.status_code = status_code
            self.response = SimpleNamespace(headers={})

    monkeypatch.setattr(ai_mod, "APIStatusError", FakeAPIStatusError)
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(side_effect=FakeAPIStatusError(429))
    monkeypatch.setattr(tr, "_get_client", lambda: fake_client)

    req_single = TranslationRequest(
        text='<ph id="0">{b}</ph>Hello',
        source_lang="en",
        target_lang="tr",
        engine=TranslationEngine.OPENAI,
        metadata={"preprotected": True, "placeholders": {'<ph id="0">': "{b}"}, "original_text": "{b}Hello"},
    )
    res_single = asyncio.run(tr.translate_single(req_single))
    assert res_single.success is False
    assert res_single.quota_exceeded is True
    assert res_single.translated_text == ""
    assert res_single.original_text == "{b}Hello"

    # Batch failure -> success=False, quota_exceeded=True, clean real_orig
    req_b1 = TranslationRequest(
        text="Line 1",
        source_lang="en",
        target_lang="tr",
        engine=TranslationEngine.OPENAI,
        metadata={"original_text": "{i}Line 1{/i}"},
    )
    req_b2 = TranslationRequest(
        text="Line 2",
        source_lang="en",
        target_lang="tr",
        engine=TranslationEngine.OPENAI,
    )
    res_batch = asyncio.run(tr.translate_batch([req_b1, req_b2]))
    assert len(res_batch) == 2
    assert all(not r.success and r.quota_exceeded for r in res_batch)
    assert res_batch[0].original_text == "{i}Line 1{/i}"
    assert res_batch[0].translated_text == ""

    # 2) finish_reason == "content_filter" -> success=True, skipped=True, real_orig
    msg = SimpleNamespace(content=None)
    choice = SimpleNamespace(finish_reason="content_filter", message=msg)
    fake_client.chat.completions.create = AsyncMock(return_value=SimpleNamespace(choices=[choice]))
    res_filtered = asyncio.run(tr.translate_single(req_single))
    assert res_filtered.success is True
    assert res_filtered.metadata.get("skipped") is True
    assert res_filtered.metadata.get("content_filtered") is True
    assert res_filtered.translated_text == "{b}Hello"
    assert "<ph" not in res_filtered.translated_text


def test_deepseek_filters_foreign_models(tmp_path: Path):
    cfg = ConfigManager(config_file=str(tmp_path / "config.json"))
    for bad in ("gpt-4o", "o1-mini", "claude-3-5-sonnet-20241022", "gemini-2.5-flash", "qwen-2.5-72b", "meta/llama-3"):
        cfg.translation_settings.openai_model = bad
        ds = DeepSeekTranslator(api_key="sk-ds", config_manager=cfg)
        assert ds._model == _DEEPSEEK_DEFAULT_MODEL, f"Expected fallback for {bad}, got {ds._model}"

    cfg.translation_settings.openai_model = "deepseek-reasoner"
    ds_ok = DeepSeekTranslator(api_key="sk-ds", config_manager=cfg)
    assert ds_ok._model == "deepseek-reasoner"


def test_gemini_probe_custom_prompt_retry_and_no_chunk_storm(tmp_path: Path, monkeypatch):
    from src.core import ai_translator as ai_mod

    monkeypatch.setattr(ai_mod, "_GEMINI_AVAILABLE", True)
    monkeypatch.setattr(ai_mod, "_GEMINI_MODE", "google_genai")
    mock_genai = MagicMock()
    mock_genai.types.HttpOptions = MagicMock()
    monkeypatch.setattr(ai_mod, "genai", mock_genai)

    cfg = ConfigManager(config_file=str(tmp_path / "config.json"))
    cfg.translation_settings.ai_retry_count = 1
    cfg.translation_settings.ai_custom_system_prompt = "Translate literally and keep {braces} untouched."

    tr = GeminiTranslator(api_key="AIza-test", config_manager=cfg)

    # Probe handles missing key & 401/404 cleanly
    tr._client.aio.models.get = AsyncMock(side_effect=Exception("401 UNAUTHENTICATED"))
    assert "rejected" in (asyncio.run(tr.probe_endpoint()) or "")

    tr._client.aio.models.get = AsyncMock(side_effect=Exception("404 NOT_FOUND"))
    assert "not found" in (asyncio.run(tr.probe_endpoint()) or "")

    tr._client.aio.models.get = AsyncMock(return_value=SimpleNamespace(name="gemini-2.5-flash"))
    assert asyncio.run(tr.probe_endpoint()) is None

    # Custom prompt containing {braces} works and ai_retry_count=1 executes 2 attempts (not 3)
    calls = {"n": 0}

    async def fail_transient(*args, **kwargs):
        calls["n"] += 1
        raise RuntimeError("503 temporary")

    monkeypatch.setattr(tr, "_generate", fail_transient)
    req = TranslationRequest(text="Hello", source_lang="en", target_lang="tr", engine=TranslationEngine.GEMINI)
    res = asyncio.run(tr.translate_single(req))
    assert res.success is False
    assert calls["n"] == 2  # retries=1 => range(2)

    # Chunk-wide 429 quota error delegates directly to fallback without 50x translate_single storm
    chunk_calls = {"gen": 0, "single": 0, "fb": 0}

    async def fail_429(*args, **kwargs):
        chunk_calls["gen"] += 1
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    async def spy_single(r):
        chunk_calls["single"] += 1
        return await GeminiTranslator.translate_single(tr, r)

    async def fake_fb(r, err=""):
        chunk_calls["fb"] += 1
        return TranslationResult(r.text, r.text, r.source_lang, r.target_lang, TranslationEngine.GEMINI, False, error=err)

    monkeypatch.setattr(tr, "_generate", fail_429)
    monkeypatch.setattr(tr, "translate_single", spy_single)
    monkeypatch.setattr(tr, "_delegate_to_fallback", fake_fb)

    with patch("asyncio.sleep", new=AsyncMock()):
        chunk = [
            TranslationRequest(text=f"Line {i}", source_lang="en", target_lang="tr", engine=TranslationEngine.GEMINI)
            for i in range(5)
        ]
        out = asyncio.run(tr._translate_chunk(chunk))

    assert len(out) == 5
    assert chunk_calls["single"] == 0
    assert chunk_calls["fb"] == 5
    assert all(r.quota_exceeded for r in out)


# ---------------------------------------------------------------------------
# Step 2.2: Google Router 429/success hooks, _multi_q, and sync fallback proxy
# ---------------------------------------------------------------------------


def test_google_router_hooks_multi_q_and_sync_proxy(tmp_path: Path, monkeypatch):
    cfg = ConfigManager(config_file=str(tmp_path / "config.json"))
    proxy_mgr = MagicMock()
    proxy_mgr.get_next_proxy = MagicMock(return_value=SimpleNamespace(url="http://127.0.0.1:8888"))
    gt = GoogleTranslator(config_manager=cfg, proxy_manager=proxy_mgr)
    gt.use_proxy = True
    gt.google_endpoints = [gt.google_endpoints[0]]
    gt.use_multi_endpoint = False

    # Test sync requests.get fallback passes proxies
    captured_kwargs = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return [[["Merhaba", "Hello"]]]

    import requests as req_lib

    def fake_get(url, **kwargs):
        captured_kwargs.update(kwargs)
        return FakeResp()

    monkeypatch.setattr(req_lib, "get", fake_get)
    monkeypatch.setattr(gt, "_get_session", AsyncMock(side_effect=RuntimeError("no aiohttp session")))
    monkeypatch.setattr(gt, "_translate_via_clients5", AsyncMock(return_value=None))
    monkeypatch.setattr(gt, "_translate_via_batchexecute", AsyncMock(return_value=None))
    monkeypatch.setattr(gt, "_translate_via_lingva", AsyncMock(return_value=None))

    res = asyncio.run(gt.translate_single(
        TranslationRequest(text="Hello", source_lang="en", target_lang="tr", engine=TranslationEngine.GOOGLE)
    ))
    assert res.success is True
    assert res.translated_text == "Merhaba"
    assert captured_kwargs.get("proxies") == {
        "http": "http://127.0.0.1:8888",
        "https": "http://127.0.0.1:8888",
    }

    # Test _multi_q (>1 items) falls through primary -> batchexecute fail -> clients5 parallel
    gt._router._health[EndpointRouter.FAMILY_PRIMARY].record_success()
    monkeypatch.setattr(gt, "_try_batch_separator", AsyncMock(return_value=None))
    monkeypatch.setattr(gt, "_translate_via_batchexecute_batch", AsyncMock(return_value=None))
    expected = [
        TranslationResult("Hi", "Selam", "en", "tr", TranslationEngine.GOOGLE, True),
        TranslationResult("Bye", "Görüşürüz", "en", "tr", TranslationEngine.GOOGLE, True),
    ]
    c5_mock = AsyncMock(return_value=expected)
    monkeypatch.setattr(gt, "_translate_via_clients5_parallel", c5_mock)

    batch_out = asyncio.run(gt._multi_q([
        TranslationRequest(text="Hi", source_lang="en", target_lang="tr", engine=TranslationEngine.GOOGLE),
        TranslationRequest(text="Bye", source_lang="en", target_lang="tr", engine=TranslationEngine.GOOGLE),
    ]))
    assert c5_mock.await_count == 1
    assert batch_out == expected


def test_google_try_batch_separator_notifies_router_on_429_and_200(tmp_path: Path, monkeypatch):
    cfg = ConfigManager(config_file=str(tmp_path / "config.json"))
    gt = GoogleTranslator(config_manager=cfg)
    gt.google_endpoints = [gt.google_endpoints[0]]
    gt.use_multi_endpoint = False
    gt._router.record_primary_429 = MagicMock(wraps=gt._router.record_primary_429)
    gt._router.record_primary_success = MagicMock(wraps=gt._router.record_primary_success)

    # Mock single client to avoid client rotation loop
    monkeypatch.setattr(gt, "_alternate_client", lambda tried: None)

    class _MockCtxResp:
        def __init__(self, status: int, payload=None):
            self.status = status
            self._payload = payload

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def json(self, content_type=None):
            return self._payload

    responses = [
        _MockCtxResp(429),
        _MockCtxResp(200, [[["Selam", "Hello"]]]),
    ]

    class _MockSession:
        def get(self, *args, **kwargs):
            return responses.pop(0)

        def post(self, *args, **kwargs):
            return responses.pop(0)

    monkeypatch.setattr(gt, "_get_session", AsyncMock(return_value=_MockSession()))

    with patch("asyncio.sleep", new=AsyncMock()):
        reqs = [TranslationRequest(text="Hello", source_lang="en", target_lang="tr", engine=TranslationEngine.GOOGLE)]
        parts = asyncio.run(gt._try_batch_separator(reqs))

    assert len(parts) == 1 and parts[0].translated_text == "Selam"
    assert gt._router.record_primary_429.call_count >= 1
    assert gt._router.record_primary_success.call_count == 1


# ---------------------------------------------------------------------------
# Step 3: Pipeline validating, provenance, proxy detection, cache & TLParser
# ---------------------------------------------------------------------------


def test_validating_reads_dot_diagnostics_and_legacy_fallback(tmp_path: Path):
    game_dir = tmp_path / "game"
    tl_dir = game_dir / "tl" / "turkish"
    game_dir.mkdir(parents=True)
    tl_dir.mkdir(parents=True)
    (game_dir / "script.rpy").write_text('label start:\n    "Hi"\n', encoding="utf-8")
    (tl_dir / "script.rpy").write_text('translate turkish strings:\n    old "Hi"\n    new "Selam"\n', encoding="utf-8")

    # Isolated .diagnostics/<lang> signature takes precedence
    diag_dir = game_dir / "tl" / ".diagnostics" / "turkish"
    diag_dir.mkdir(parents=True)
    (diag_dir / "rpyc_extraction_signature.json").write_text(
        json.dumps({"signature": "rpyc_reader_slot12_encoding_fallback_root_filter_v1"}),
        encoding="utf-8",
    )
    logs = []
    assert needs_re_extraction(str(game_dir), str(tl_dir), True, lambda lvl, msg: logs.append(msg)) is False

    # Missing new path falls back to legacy tl/<lang>/diagnostics
    (diag_dir / "rpyc_extraction_signature.json").unlink()
    legacy = tl_dir / "diagnostics"
    legacy.mkdir()
    (legacy / "rpyc_extraction_signature.json").write_text(
        json.dumps({"signature": "rpyc_reader_slot12_encoding_fallback_root_filter_v1"}),
        encoding="utf-8",
    )
    assert needs_re_extraction(str(game_dir), str(tl_dir), True, lambda lvl, msg: logs.append(msg)) is False


def test_orchestrator_provenance_proxy_and_aggressive_cache(tmp_path: Path, monkeypatch):
    cfg = ConfigManager(config_file=str(tmp_path / "config.json"))
    cfg.translation_settings.gemini_model = "gemini-2.5-pro"
    cfg.translation_settings.aggressive_retry_translation = True

    proxy_mgr = MagicMock()
    proxy_mgr.get_next_proxy = MagicMock(return_value=None)
    tm = TranslationManager(proxy_manager=proxy_mgr, config_manager=cfg)
    tm.translators[TranslationEngine.GEMINI] = MagicMock(_model="gemini-2.5-pro")
    pipe = TranslationPipeline(cfg, tm)
    pipe.engine = TranslationEngine.GEMINI
    pipe.target_language = "turkish"
    pipe.source_language = "en"

    # Empty entry triggers provenance with gemini_model without running network
    pipe._translate_entries([])
    assert pipe.diagnostic_report.engine == "gemini"
    assert pipe.diagnostic_report.model == "gemini-2.5-pro"

    # Aggressive retry skips unchanged cached entry
    tm._cache[("gemini", "en", "tr", "Attack")] = TranslationResult(
        "Attack", "Attack", "en", "tr", TranslationEngine.GEMINI, True
    )
    sent_texts = []

    async def fake_translate_batch(reqs):
        for r in reqs:
            sent_texts.append(r.text)
        return [
            TranslationResult(r.text, "Saldır", r.source_lang, r.target_lang, TranslationEngine.GEMINI, True)
            for r in reqs
        ]

    monkeypatch.setattr(tm, "translate_batch", fake_translate_batch)

    entry = TranslationEntry(
        original_text="Attack",
        translated_text="",
        file_path=str(tmp_path / "game" / "script.rpy"),
        line_number=10,
        entry_type="string",
        translation_id="id_attack",
        context_path=[],
    )

    out = pipe._translate_entries([entry])
    assert sent_texts  # Was NOT skipped by cache
    assert out.get("id_attack") == "Saldır" or out.get("Attack") == "Saldır"


def test_tl_parser_context_and_apply_line_edits_empty_fallback(tmp_path: Path):
    rpy = tmp_path / "screens.rpy"
    content = (
        "translate turkish strings:\n"
        "\n"
        "    # context: screen:main_menu\n"
        '    old "Play"\n'
        '    new ""\n'
    )
    rpy.write_text(content, encoding="utf-8")

    parser = TLParser()
    tf = parser.parse_file(str(rpy))
    assert len(tf.entries) == 1
    expected_id = tf.entries[0].translation_id

    updated = parser.update_translations(tf, {expected_id: "Oyna"})
    assert 'new "Oyna"' in updated

    # Blank edit via apply_line_edits restores original via _final_text
    reverted, failed = parser.apply_line_edits(
        updated,
        [{"line": tf.entries[0].line_number, "kind": "string", "original": "Play", "text": ""}],
    )
    assert failed == []
    assert 'new "Play"' in reverted


# ---------------------------------------------------------------------------
# Step 4: Editor backups, cache sync, CLI fixes, and SettingsPage QML
# ---------------------------------------------------------------------------


def test_editor_nested_backup_and_cache_sync_and_project_reset(tmp_path: Path):
    lang_dir = tmp_path / "game" / "tl" / "turkish"
    (lang_dir / "a").mkdir(parents=True)
    (lang_dir / "b").mkdir(parents=True)
    file_a = lang_dir / "a" / "common.rpy"
    file_b = lang_dir / "b" / "common.rpy"
    tpl = 'translate turkish strings:\n\n    old "Ok"\n    new ""\n'
    file_a.write_text(tpl, encoding="utf-8")
    file_b.write_text(tpl, encoding="utf-8")

    backup_dir = tmp_path / "backups"
    loaded = load_language(str(tmp_path / "game"), "turkish")
    store = EditorStore()
    store.load(loaded.rows)
    rows, _ = store.query()
    store.update(rows[0]["id"], "Tamam")
    store.update(rows[1]["id"], "Peki")
    res = save_edits(store.modified_by_file(), loaded.snapshots, str(backup_dir), lang_dir=str(lang_dir))
    assert len(res.saved_files) == 2
    assert (backup_dir / "a__common.rpy.bak").is_file()
    assert (backup_dir / "b__common.rpy.bak").is_file()

    # Cache sync preserves 3-arg contract while insert_missing_engine inserts missing entries
    cache = tmp_path / "translation_cache.json"
    cache.write_text(json.dumps({"google": {"auto": {"tr": {"Start": "Basla"}}}}), encoding="utf-8")
    changed = sync_translation_cache(
        str(cache),
        ["tr", "turkish"],
        {"Start": "Başla", "New": "Yeni"},
        insert_missing_engine="google",
        insert_missing_source="auto",
        insert_missing_target="tr",
    )
    assert changed == 2
    saved_cache = json.loads(cache.read_text(encoding="utf-8"))
    assert saved_cache["google"]["auto"]["tr"]["New"] == "Yeni"

    # EditorBackend handles missing problem codes & resets loaded state across projects
    cfg = ConfigManager(config_file=str(tmp_path / "config.json"))
    tm = TranslationManager(config_manager=cfg)
    mock_app = SimpleNamespace(
        config=cfg,
        translation_manager=tm,
        _is_translating=False,
        _project_path="",
        _tool_game_dir=lambda: str(tmp_path / "game"),
        translationStarted=MagicMock(),
        translationFinished=MagicMock(),
    )
    eb = EditorBackend(mock_app)
    assert eb._problem_text("replacement_char")
    assert eb._problem_text("renpy_tag_order_invalid")

    eb._loaded = loaded
    eb._game_dir = str(tmp_path / "game")
    eb._language = "turkish"
    game2 = tmp_path / "game2"
    (game2 / "tl" / "french").mkdir(parents=True)
    (game2 / "tl" / "french" / "script.rpy").write_text('translate french strings:\n', encoding="utf-8")
    mock_app._tool_game_dir = lambda: str(game2)
    eb.refreshLanguages()
    assert eb.loaded is False
    assert eb.languages == ["french"]


def test_cli_pseudo_transform_and_config_post_init(tmp_path: Path):
    from src.cli_main import run_pseudo_command, run_translate_command

    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True)
    rpy = game_dir / "intro.rpy"
    rpy.write_text('label start:\n    "Hello world"\n', encoding="utf-8")
    out_dir = tmp_path / "custom_pseudo"

    args = SimpleNamespace(input_path=str(tmp_path), mode="accent", output=str(out_dir))
    rc = run_pseudo_command(args)
    assert rc == 0
    pseudo_out = out_dir / "game" / "intro.rpy"
    assert pseudo_out.is_file()
    assert "Hello world" not in pseudo_out.read_text(encoding="utf-8")

    # --config override runs __post_init__ clamping invalid values
    bad_cfg = tmp_path / "override.json"
    bad_cfg.write_text(json.dumps({
        "translation_settings": {"ai_batch_format": "bogus_format", "ai_batch_size": 999}
    }), encoding="utf-8")
    tr_args = SimpleNamespace(
        input_path=str(tmp_path),
        config=str(bad_cfg),
        engine="google",
        target_lang="tr",
        source_lang="en",
        extract_rpa=False,
        rpyc=False,
        deep_scan=False,
        language_init=False,
        tl=False,
        lt_url="",
        lt_key="",
        verbose=False,
    )
    with patch("src.cli_main.setup_engines", side_effect=RuntimeError("stop_after_config")) as mock_setup:
        with pytest.raises(RuntimeError, match="stop_after_config"):
            run_translate_command(tr_args)
    clamped_cfg = mock_setup.call_args[0][0]
    assert clamped_cfg.translation_settings.ai_batch_format == "scene"


def test_settings_page_visibility_and_two_way_qml_bindings(tmp_path: Path):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QML_DISABLE_DISK_CACHE"] = "1"
    from PyQt6.QtCore import QUrl
    from PyQt6.QtQml import QQmlApplicationEngine, QQmlExpression
    from PyQt6.QtWidgets import QApplication

    qml_dir = Path(__file__).resolve().parents[1] / "src" / "gui" / "qml"
    app = QApplication.instance() or QApplication(sys.argv[:1])
    cfg = ConfigManager(config_file=str(tmp_path / "config.json"))
    with patch("src.backend.app_backend.ConfigManager", return_value=cfg):
        backend = AppBackend(parent=app)
    engine = QQmlApplicationEngine(app)
    engine.rootContext().setContextProperty("appBackend", backend)
    editor_backend = EditorBackend(backend, parent=app)
    engine.rootContext().setContextProperty("editorBackend", editor_backend)
    developer_backend = DeveloperBackend(backend, parent=app)
    engine.rootContext().setContextProperty("developerBackend", developer_backend)
    engine.addImportPath(str(qml_dir))
    engine.load(QUrl.fromLocalFile(str(qml_dir / "Main.qml")))
    assert engine.rootObjects()

    root = engine.rootObjects()[0]
    root.show()
    app.processEvents()
    root_ctx = engine.contextForObject(root)
    page_settings = QQmlExpression(root_ctx, root, "pageSettings").evaluate()[0]
    assert page_settings is not None

    inner_item = next(c for c in page_settings.children() if c.property("visible") is not None)
    inner_ctx = engine.contextForObject(inner_item)

    # Activate Settings -> AI sub-tab so parent containers don't mask section visibility
    QQmlExpression(root_ctx, root, "navIndex = 1").evaluate()
    QQmlExpression(inner_ctx, inner_item, "pageSettings.settingsSubTab = 1").evaluate()
    app.processEvents()

    def eval_settings(expr: str):
        expr_obj = QQmlExpression(inner_ctx, inner_item, expr)
        val = expr_obj.evaluate()[0]
        assert not expr_obj.hasError(), f"QML expression failed: {expr} ({expr_obj.error().toString()})"
        return val

    # Check Base URL visibility: only visible for openai, NOT deepseek/openrouter
    backend.setSelectedEngine("deepseek")
    app.processEvents()
    assert eval_settings("settingsOpenaiBaseUrlField.parent.visible") is False
    backend.setSelectedEngine("openai")
    app.processEvents()
    assert eval_settings("settingsOpenaiBaseUrlField.parent.visible") is True

    # Check Local LLM section visibility: NOT visible for google
    backend.setSelectedEngine("google")
    app.processEvents()
    assert eval_settings("localLlmModeCombo.parent.parent.visible") is False
    backend.setSelectedEngine("local_llm")
    app.processEvents()
    assert eval_settings("localLlmModeCombo.parent.parent.visible") is True

    # Check AI Batch Mode section visibility: only openai/deepseek/openrouter/local_llm
    backend.setSelectedEngine("gemini")
    app.processEvents()
    assert eval_settings("aiBatchModeCombo.parent.parent.parent.visible") is False
    backend.setSelectedEngine("google")
    app.processEvents()
    assert eval_settings("aiBatchModeCombo.parent.parent.parent.visible") is False
    backend.setSelectedEngine("openai")
    app.processEvents()
    assert eval_settings("aiBatchModeCombo.parent.parent.parent.visible") is True

    # Two-way sync: changing appBackend properties updates SettingsPage fields
    backend.openaiApiKey = "sk-updated-123"
    backend.openaiModel = "gpt-4o"
    backend.localLlmUrl = "http://localhost:1234/v1"
    app.processEvents()
    assert eval_settings("settingsOpenaiKeyField.text") == "sk-updated-123"
    assert eval_settings("settingsOpenaiModelField.text") == "gpt-4o"
    assert eval_settings("settingsLocalLlmUrlField.text") == "http://localhost:1234/v1"
    root.hide()


def test_developer_mode_setting_and_developer_backend(tmp_path: Path):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication

    _ = QApplication.instance() or QApplication(sys.argv[:1])

    cfg = ConfigManager(config_file=str(tmp_path / "config.json"))
    assert cfg.app_settings.developer_mode is False
    with patch("src.backend.app_backend.ConfigManager", return_value=cfg):
        app_be = AppBackend()
        app_be.developerMode = True
        assert app_be.developerMode is True
    assert ConfigManager(config_file=str(tmp_path / "config.json")).app_settings.developer_mode is True

    # Build a fake game with .diagnostics/turkish reports
    game_dir = tmp_path / "game"
    lang_dir = game_dir / "tl" / "turkish"
    diag_dir = game_dir / "tl" / ".diagnostics" / "turkish"
    lang_dir.mkdir(parents=True)
    diag_dir.mkdir(parents=True)
    src_script = game_dir / "script.rpy"
    src_script.write_text('label start:\n    "Hi"\n', encoding="utf-8")
    (lang_dir / "script.rpy").write_text('translate turkish strings:\n    old "Hi"\n    new "Selam"\n', encoding="utf-8")

    (diag_dir / "diagnostic_turkish.json").write_text(json.dumps({
        "_notice": "Developer diagnostic report",
        "totals": {"translated": 1, "blocked_as_corrupted": 1, "unchanged_by_engine": 0, "coverage_warning_count": 1},
        "provenance": {"engine": "google", "model": ""},
        "coverage_warnings": [{
            "code": "interpolated_define_values",
            "count": 1,
            "samples": [{"variable": "mood", "value": "Happy", "file_path": str(src_script), "line_number": 2}],
        }],
        "files": {str(src_script): {"translated": 1, "written": 1, "blocked": 1, "unchanged": 0, "skipped": 0}},
    }), encoding="utf-8")
    (diag_dir / "translation_blocked_or_fallback.json").write_text(json.dumps({
        "samples": [{
            "category": "blocked_as_corrupted",
            "detail": "placeholder_remnant",
            "original_preview": "Hello [name]",
            "file_path": str(src_script),
            "line_number": 2,
        }]
    }), encoding="utf-8")

    mock_app = SimpleNamespace(
        config=cfg,
        _tool_game_dir=lambda: str(game_dir),
        openLocalPath=MagicMock(),
    )
    db = DeveloperBackend(mock_app)
    db.refresh()
    assert db.language == "turkish"
    assert db.summary["blocked"] == 1
    assert len(db.items) == 3  # 1 blocked + 1 warning + 1 affected file

    db.setCategoryFilter("blocked")
    assert len(db.items) == 1
    assert db.items[0]["badge"] == "blocked_as_corrupted"

    db.setCategoryFilter("all")
    db.setSearchQuery("mood")
    assert len(db.items) == 1
    assert db.items[0]["title"] == "mood"

    db.openInExternalEditor(db.items[0]["filePath"])
    assert mock_app.openLocalPath.call_count == 1

    # Verify EditorBackend.focusEntry filters and selects the matching row
    from src.core.editor.project import load_language as _load_lang

    (lang_dir / "script.rpy").write_text(
        'translate turkish strings:\n\n    old "Hi"\n    new "Selam"\n\n    old "Hello [name]"\n    new ""\n',
        encoding="utf-8",
    )
    eb_app = SimpleNamespace(
        config=cfg,
        translation_manager=TranslationManager(config_manager=cfg),
        _is_translating=False,
        _project_path="",
        _tool_game_dir=lambda: str(game_dir),
        translationStarted=MagicMock(),
        translationFinished=MagicMock(),
    )
    eb = EditorBackend(eb_app)
    eb._loaded = _load_lang(str(game_dir), "turkish")
    eb._game_dir = str(game_dir)
    eb._language = "turkish"
    eb.store.load(eb._loaded.rows)
    eb.focusEntry("turkish", "Hello [name]", "script.rpy")
    assert eb.search == "Hello [name]"
    assert eb.selected.get("original") == "Hello [name]"

