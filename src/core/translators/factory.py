"""Builds the translator for an engine id: the one place that does it.

The GUI, the CLI and the pipeline each used to construct translators on their
own, and had drifted apart (the pipeline never used the DeepSeek class, the CLI
read LibreTranslate's URL for the custom endpoint, fallbacks were wired in some
paths only). They all call ``build_translator`` now.

Engine facts (key, fallback, ...) come from ``src/utils/engine_registry.py``.
"""
from __future__ import annotations

from typing import Callable, Optional

from src.utils.engine_registry import DEFAULT_ENGINE_ID, engine_spec, normalize_engine_id

from .base import BaseTranslator, TranslationEngine


def engine_enum(engine) -> TranslationEngine:
    """TranslationEngine for an id ("deepseek" -> OPENAI); unknown ids -> GOOGLE."""
    if isinstance(engine, TranslationEngine):
        return engine
    spec = engine_spec(engine) or engine_spec(DEFAULT_ENGINE_ID)
    return TranslationEngine(spec.enum_value)


def _setting(config, name: str, default=""):
    return getattr(getattr(config, "translation_settings", None), name, default) or default


def build_translator(
    engine,
    config,
    proxy_manager=None,
    *,
    google: Optional[BaseTranslator] = None,
    base_url: str = "",
    api_key: str = "",
    status_callback: Optional[Callable[[str, str], None]] = None,
) -> Optional[BaseTranslator]:
    """A ready translator for ``engine`` (an id or enum member), or None.

    None means the engine cannot be built from the current settings (a custom
    endpoint without a URL) or is not one this factory knows; the caller keeps
    whatever it had. ``google`` is reused as the fallback engine when given.
    ``base_url`` / ``api_key`` override the stored values for the self-hosted
    engines (CLI flags). Constructors do no network I/O.
    """
    engine_id = normalize_engine_id(engine)
    spec = engine_spec(engine_id)
    if spec is None:
        return None
    common = dict(proxy_manager=proxy_manager, config_manager=config)
    keys = getattr(config, "api_keys", None)
    translator: Optional[BaseTranslator] = None

    if engine_id == "google":
        from .google import GoogleTranslator

        translator = GoogleTranslator(**common)
    elif engine_id == "bing":
        from .services import BingTranslator

        translator = BingTranslator(**common)
    elif engine_id == "nvidia":
        from .nvidia import NvidiaTranslator

        translator = NvidiaTranslator(
            api_key=getattr(keys, "nvidia_api_key", "") or "",
            model=_setting(config, "nvidia_model"),
            **common,
        )
    elif engine_id in ("openai", "deepseek"):
        from src.core.ai_translator import DeepSeekTranslator, OpenAITranslator

        key = getattr(keys, "openai_api_key", "") or ""
        # "deepseek" is the OpenAI engine pointed at DeepSeek; a config that
        # only carries the URL means the same thing.
        if engine_id == "deepseek" or "deepseek" in _setting(config, "openai_base_url").lower():
            translator = DeepSeekTranslator(api_key=key, **common)
        else:
            translator = OpenAITranslator(api_key=key, **common)
    elif engine_id == "gemini":
        from src.core.ai_translator import GeminiTranslator

        translator = GeminiTranslator(api_key=getattr(keys, "gemini_api_key", "") or "", **common)
    elif engine_id == "local_llm":
        from src.core.ai_translator import LocalLLMTranslator

        translator = LocalLLMTranslator(**common)
    elif engine_id == "libretranslate":
        from .services import LibreTranslateTranslator

        translator = LibreTranslateTranslator(
            base_url=base_url or _setting(config, "libretranslate_url", "http://localhost:5000"),
            api_key=api_key or _setting(config, "libretranslate_api_key"),
            **common,
        )
    elif engine_id == "custom":
        from .services import LibreTranslateTranslator

        url = base_url or _setting(config, "custom_endpoint_url")
        if not url:
            return None
        translator = LibreTranslateTranslator(
            base_url=url, api_key=api_key or _setting(config, "custom_endpoint_api_key"), **common
        )
    else:
        return None

    if status_callback is not None:
        translator.status_callback = status_callback
    if spec.google_fallback:
        fallback = google
        if fallback is None:
            from .google import GoogleTranslator

            fallback = GoogleTranslator(**common)
            if status_callback is not None:
                fallback.status_callback = status_callback
        translator.set_fallback_translator(fallback)
    return translator
