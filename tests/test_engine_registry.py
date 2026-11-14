# -*- coding: utf-8 -*-
"""One table describes every engine; GUI, CLI, settings and pipeline read it."""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.translators.base import TranslationEngine
from src.core.translators.factory import build_translator, engine_enum
from src.utils import engine_registry as reg

ROOT = Path(__file__).resolve().parents[1]


def make_config(**settings):
    ts = dict(
        openai_model="gpt-4o-mini", openai_base_url="", gemini_model="gemini-2.5-flash",
        gemini_safety_settings="BLOCK_NONE", nvidia_model="", local_llm_model="llama3.2",
        local_llm_url="http://localhost:11434/v1", libretranslate_url="https://lt.example.org",
        libretranslate_api_key="", custom_endpoint_url="", custom_endpoint_api_key="",
        ai_concurrency=2, ai_batch_size=10, ai_timeout=60, ai_temperature=0.3, ai_max_tokens=2048,
        ai_model_profile="generic", ai_custom_system_prompt="", ai_retry_count=1,
    )
    ts.update(settings)
    return SimpleNamespace(
        translation_settings=SimpleNamespace(**ts),
        api_keys=SimpleNamespace(openai_api_key="sk-x", gemini_api_key="AIza-x", nvidia_api_key="nvapi-x",
                                 deepl_api_key=""),
        get_ui_text=lambda key, default="": default,
        get_log_text=lambda key, default="", **kw: default,
    )


# ── the table itself ─────────────────────────────────────────────────────────

def test_ids_are_unique_and_map_to_real_engines():
    ids = [spec.id for spec in reg.ENGINES]
    assert len(ids) == len(set(ids))
    for spec in reg.ENGINES:
        assert TranslationEngine(spec.enum_value)          # raises on a typo
    assert engine_enum("deepseek") is TranslationEngine.OPENAI
    assert engine_enum("no-such-engine") is TranslationEngine.GOOGLE
    assert engine_enum(TranslationEngine.BING) is TranslationEngine.BING


def test_llm_flag_matches_the_three_instruction_model_engines():
    llm = {engine_enum(spec.id) for spec in reg.ENGINES if spec.llm}
    assert llm == {TranslationEngine.OPENAI, TranslationEngine.GEMINI, TranslationEngine.LOCAL_LLM}
    assert reg.is_llm_engine(TranslationEngine.GEMINI) and reg.is_llm_engine("deepseek")
    assert not reg.is_llm_engine(TranslationEngine.NVIDIA)   # translation model, not an LLM
    assert not reg.is_llm_engine("google") and not reg.is_llm_engine("unknown")


def test_api_note_engines():
    assert {s.id for s in reg.ENGINES if s.api_quality_note} == {"nvidia", "openai", "gemini", "deepseek"}


def test_key_fields_exist_in_the_config_dataclasses():
    from src.utils.config import ApiKeys, ConfigManager, TranslationSettings

    sections = {"api_keys": ApiKeys(), "translation_settings": TranslationSettings()}
    for spec in reg.ENGINES:
        if spec.key:
            section, field = spec.key
            assert hasattr(sections[section], field), spec.id
            assert spec.key in ConfigManager.SECRET_FIELDS, f"{spec.id}: key is not kept in the credential store"
        if spec.model_field:
            assert hasattr(sections["translation_settings"], spec.model_field), spec.id


# ── consumers read the table ─────────────────────────────────────────────────

def test_settings_accept_every_registered_engine_and_reject_others():
    from src.utils.config import TranslationSettings

    for engine_id in reg.engine_ids():
        assert TranslationSettings(selected_engine=engine_id).selected_engine == engine_id
    assert TranslationSettings(selected_engine="yandex").selected_engine == "google"


def test_batch_caps_come_from_the_table():
    from src.utils.config import ENGINE_BATCH_SIZE_CAPS, get_engine_batch_size_cap

    assert ENGINE_BATCH_SIZE_CAPS == {"google": 1000, "bing": 100, "nvidia": 200}
    assert get_engine_batch_size_cap(TranslationEngine.BING) == 100
    assert get_engine_batch_size_cap("openai") is None


def test_cli_lists_exactly_the_registered_cli_engines():
    import src.cli_main as cli

    assert [row[0] for row in cli.ENGINES] == list(reg.engine_ids(cli=True))
    assert cli.ENGINE_MAP == {eid: engine_enum(eid) for eid in reg.engine_ids(cli=True)}
    # The numbered terminal menu must not shift under people's fingers.
    assert [row[0] for row in cli.ENGINES] == [
        "google", "bing", "nvidia", "openai", "deepseek", "gemini", "local_llm", "libretranslate", "custom",
    ]


def test_gui_list_has_no_second_copy_of_the_engines():
    qml_root = ROOT / "src" / "gui" / "qml"
    assert "appBackend.engineList" in (qml_root / "pages" / "DashboardPage.qml").read_text(encoding="utf-8")
    for path in qml_root.rglob("*.qml"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r'"id":\s*"(google|bing|nvidia|openai|gemini|deepseek)"', text), path.name
    icons = (ROOT / "src" / "gui" / "qml" / "components" / "Icons.qml").read_text(encoding="utf-8")
    en = json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))
    for spec in reg.ENGINES:
        if not spec.in_gui:
            continue
        assert re.search(r"property string %s\b" % re.escape(spec.icon), icons), f"{spec.id}: icon {spec.icon}"
        if spec.desc:
            assert spec.desc[0] in en, f"{spec.id}: locale key {spec.desc[0]}"


# ── the factory ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("engine_id,class_name", [
    ("google", "GoogleTranslator"), ("bing", "BingTranslator"), ("nvidia", "NvidiaTranslator"),
    ("openai", "OpenAITranslator"), ("deepseek", "DeepSeekTranslator"), ("gemini", "GeminiTranslator"),
    ("local_llm", "LocalLLMTranslator"), ("libretranslate", "LibreTranslateTranslator"),
])
def test_factory_builds_each_engine(engine_id, class_name):
    translator = build_translator(engine_id, make_config())
    assert translator.__class__.__name__ == class_name
    spec = reg.engine_spec(engine_id)
    fallback = getattr(translator, "fallback_translator", None)
    if spec.google_fallback:
        assert fallback.__class__.__name__ == "GoogleTranslator", engine_id
    else:
        assert fallback is None, engine_id


def test_every_gui_and_cli_engine_can_be_built():
    config = make_config(custom_endpoint_url="https://mt.example.org")
    for engine_id in set(reg.engine_ids(gui=True)) | set(reg.engine_ids(cli=True)):
        assert build_translator(engine_id, config) is not None, engine_id


def test_factory_reuses_the_callers_google_as_fallback():
    google = build_translator("google", make_config())
    bing = build_translator("bing", make_config(), google=google)
    assert bing.fallback_translator is google


def test_openai_pointed_at_deepseek_builds_the_deepseek_translator():
    config = make_config(openai_base_url="https://api.deepseek.com/v1")
    assert build_translator("openai", config).__class__.__name__ == "DeepSeekTranslator"


def test_custom_endpoint_needs_a_url():
    assert build_translator("custom", make_config()) is None
    built = build_translator("custom", make_config(custom_endpoint_url="https://mt.example.org"))
    assert built.__class__.__name__ == "LibreTranslateTranslator"
    assert build_translator("custom", make_config(), base_url="https://flag.example.org") is not None


def test_factory_passes_the_status_callback_to_engine_and_fallback():
    seen = []
    nvidia = build_translator("nvidia", make_config(), status_callback=lambda level, msg: seen.append(msg))
    nvidia.emit_log("info", "from engine")
    nvidia.fallback_translator.emit_log("info", "from fallback")
    assert seen == ["from engine", "from fallback"]


def test_unknown_engines_are_not_built():
    assert build_translator("yandex", make_config()) is None
    assert build_translator("pseudo", make_config()) is None   # known id, built by the pipeline itself
