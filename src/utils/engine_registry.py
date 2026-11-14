"""One record per translation engine.

Adding an engine used to mean touching the settings validator, three id-to-enum
maps, the GUI list, the CLI list, three places that build the translator and a
handful of ``if engine in (...)`` tuples. Each of those now reads this table.

This module imports nothing from the project on purpose: ``config.py`` reads it
while the ``src.core`` package is still being imported. The translator objects
themselves are built in ``src/core/translators/factory.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class EngineSpec:
    id: str                      # what config.json, the CLI and QML call it
    enum_value: str              # TranslationEngine value it runs as
    label: str                   # proper name, never translated
    # Short description shown next to the name: (locale key, English default).
    desc: Optional[Tuple[str, str]] = None
    icon: str = "globe"          # name in components/Icons.qml
    cli_label: str = ""          # shorter name for the terminal menu
    cli_icon: str = ""
    cli_note: str = ""
    # "web": keyless/web service, "llm": instruction-following model,
    # "mt": translation-only model behind an API, "self_hosted": user's own server
    kind: str = "web"
    # Instruction-following models take XML placeholders, scene batches and the
    # ai_* settings (batch size, concurrency, request delay).
    llm: bool = False
    # (config section, field) of the API key, and the environment variable the
    # CLI falls back to. None = no key.
    key: Optional[Tuple[str, str]] = None
    key_env: Optional[str] = None
    model_field: Optional[str] = None      # field in translation_settings
    # Hard ceiling for one pipeline step; None = the user's setting applies.
    batch_cap: Optional[int] = None
    # Hard failures are handed to Google.
    google_fallback: bool = False
    # Paid/free API whose output sometimes keeps short lines as-is (Editor tip).
    api_quality_note: bool = False
    in_gui: bool = True
    in_cli: bool = True


ENGINES: Tuple[EngineSpec, ...] = (
    EngineSpec(
        id="google", enum_value="google", label="Google Translate",
        desc=("engine_desc_google", "Primary / Free"), icon="globe",
        cli_icon="🌐", cli_note="Free — 13 mirror fallback",
        batch_cap=1000,
    ),
    EngineSpec(
        id="bing", enum_value="bing", label="Bing / Microsoft Edge",
        desc=("engine_desc_bing", "Free / No key"), icon="appWindow",
        cli_label="Bing / MS Edge", cli_icon="🪟", cli_note="Free — no API key, Google fallback",
        # edge.microsoft.com: <=100 items / ~50k chars per request
        batch_cap=100, google_fallback=True,
    ),
    EngineSpec(
        id="nvidia", enum_value="nvidia", label="NVIDIA Riva",
        desc=("engine_desc_nvidia", "Free key / Translation model"), icon="zap",
        cli_label="NVIDIA (Riva)", cli_icon="🟢", cli_note="Free nvapi- key (build.nvidia.com), ~40 req/min",
        kind="mt", key=("api_keys", "nvidia_api_key"), key_env="NVIDIA_API_KEY",
        model_field="nvidia_model",
        # The translator splits a step into adaptive sub-batches itself; the step
        # only has to keep its few parallel requests fed.
        batch_cap=200, google_fallback=True, api_quality_note=True,
    ),
    EngineSpec(
        id="openai", enum_value="openai", label="OpenAI / GPT-4o",
        desc=("engine_desc_ai", "AI Engine"), icon="bot",
        cli_label="OpenAI (GPT)", cli_icon="🤖", cli_note="API key required",
        kind="llm", llm=True, key=("api_keys", "openai_api_key"), key_env="OPENAI_API_KEY",
        model_field="openai_model", api_quality_note=True,
    ),
    EngineSpec(
        # Runs as the OpenAI engine with DeepSeek's endpoint and defaults.
        id="deepseek", enum_value="openai", label="DeepSeek AI",
        desc=("engine_desc_deepseek", "Fast / Economic"), icon="brain",
        cli_label="DeepSeek", cli_icon="🔮", cli_note="API key required — OpenAI compatible",
        kind="llm", llm=True, key=("api_keys", "openai_api_key"), key_env="DEEPSEEK_API_KEY",
        model_field="openai_model", api_quality_note=True,
    ),
    EngineSpec(
        id="gemini", enum_value="gemini", label="Gemini",
        desc=("engine_desc_gemini", "Google AI"), icon="sparkles",
        cli_label="Google Gemini", cli_icon="✨", cli_note="API key required",
        kind="llm", llm=True, key=("api_keys", "gemini_api_key"), key_env="GEMINI_API_KEY",
        model_field="gemini_model", google_fallback=True, api_quality_note=True,
    ),
    EngineSpec(
        id="local_llm", enum_value="local_llm", label="Local LLM (Ollama / LM Studio)",
        icon="monitor", cli_label="Local LLM", cli_icon="🏠", cli_note="Ollama / LM Studio / built-in GGUF",
        kind="llm", llm=True, model_field="local_llm_model",
    ),
    EngineSpec(
        id="libretranslate", enum_value="libretranslate", label="LibreTranslate",
        desc=("engine_desc_local", "Self-hosted"), icon="bookOpen",
        cli_icon="🔓", cli_note="Self-hosted — Docker/Local",
        kind="self_hosted", key=("translation_settings", "libretranslate_api_key"),
    ),
    EngineSpec(
        id="custom", enum_value="custom", label="Custom Endpoint",
        desc=("engine_desc_custom", "Custom API"), icon="link",
        cli_icon="🔗", cli_note="Any LibreTranslate-compatible API",
        kind="self_hosted", key=("translation_settings", "custom_endpoint_api_key"),
    ),
    # Accepted in config.json and by the pipeline, not offered in the lists.
    EngineSpec(
        id="deepl", enum_value="deepl", label="DeepL",
        key=("api_keys", "deepl_api_key"), in_gui=False, in_cli=False,
    ),
    EngineSpec(
        id="pseudo", enum_value="pseudo", label="Pseudo-localization",
        in_gui=False, in_cli=False,
    ),
)

_BY_ID = {spec.id: spec for spec in ENGINES}
DEFAULT_ENGINE_ID = "google"


def normalize_engine_id(engine) -> str:
    """Lower-case id from a string or a TranslationEngine member."""
    if hasattr(engine, "value"):
        engine = engine.value
    return str(engine or "").strip().lower()


def engine_spec(engine) -> Optional[EngineSpec]:
    """The record for an id or enum member (an enum resolves to its own-named id)."""
    return _BY_ID.get(normalize_engine_id(engine))


def engine_ids(*, gui: bool = False, cli: bool = False) -> Tuple[str, ...]:
    """All known ids, or only those offered in the GUI / CLI list."""
    return tuple(
        spec.id for spec in ENGINES
        if (not gui or spec.in_gui) and (not cli or spec.in_cli)
    )


def is_known_engine(engine) -> bool:
    return normalize_engine_id(engine) in _BY_ID


def is_llm_engine(engine) -> bool:
    """True for instruction-following models (XML placeholders, ai_* settings)."""
    spec = engine_spec(engine)
    return bool(spec and spec.llm)


def engine_batch_cap(engine) -> Optional[int]:
    spec = engine_spec(engine)
    return spec.batch_cap if spec else None


def shows_api_quality_note(engine) -> bool:
    spec = engine_spec(engine)
    return bool(spec and spec.api_quality_note)
