# -*- coding: utf-8 -*-
"""
Base translation types and abstract translator class.
"""
from __future__ import annotations

import asyncio
import contextvars
import aiohttp
import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple, Callable

from src.core.constants import USER_AGENTS
from src.utils import net as _net
from src.utils.net import build_ssl_context

# True while an engine hands work to its fallback engine. A fallback never hands the
# same work on again (Bing -> Google -> Bing would otherwise loop).
IN_FALLBACK: contextvars.ContextVar[bool] = contextvars.ContextVar("rl_in_fallback", default=False)


class TranslationEngine(Enum):
    GOOGLE = "google"
    DEEPL = "deepl"
    OPENAI = "openai"
    GEMINI = "gemini"
    LOCAL_LLM = "local_llm"
    LIBRETRANSLATE = "libretranslate"
    BING = "bing"  # Microsoft Edge web-translation endpoint (keyless)
    NVIDIA = "nvidia"  # NVIDIA API Catalog: Riva-Translate (free nvapi- key)
    CUSTOM = "custom"  # Generic HTTP endpoint (LibreTranslate/Argos/any)
    PSEUDO = "pseudo"  # Pseudo-localization for UI testing


@dataclass
class TranslationRequest:
    text: str
    source_lang: str
    target_lang: str
    engine: TranslationEngine
    metadata: Dict = field(default_factory=dict)


@dataclass
class TranslationResult:
    original_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    engine: TranslationEngine
    success: bool
    error: Optional[str] = None
    confidence: float = 0.0
    quota_exceeded: bool = False  # Flag for API quota exhaustion
    metadata: Dict = field(default_factory=dict)
    text_type: Optional[str] = None  # Type of text: 'paragraph', 'dialogue', etc.


class BaseTranslator(ABC):
    def __init__(
        self, api_key: Optional[str] = None, proxy_manager=None, config_manager=None
    ):
        self.api_key = api_key
        self.proxy_manager = proxy_manager
        self.config_manager = config_manager
        self.use_proxy = True
        self.logger = logging.getLogger(self.__class__.__name__)
        self.status_callback: Optional[Callable[[str, str], None]] = (
            None  # (level, message)
        )
        self.should_stop_callback: Optional[Callable[[], bool]] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._connector: Optional[aiohttp.TCPConnector] = None
        self._session_lock = (
            asyncio.Lock()
        )  # Mutex for thread-safe session creation checks
        self.user_agents = USER_AGENTS
        self.enable_parallel_batch = True
        if config_manager and hasattr(config_manager, "translation_settings"):
            self.enable_parallel_batch = getattr(
                config_manager.translation_settings, "enable_parallel_batch", True
            )
        self.fallback_translator: Optional[BaseTranslator] = None
        self._fallback: Optional[BaseTranslator] = None
        # Whether the pipeline may ask the fallback engine for a second opinion
        # when this engine returns a string unchanged. Plain MT engines (Bing)
        # opt out: their own retry already ran and the fallback is the same class.
        self.fallback_for_unchanged_retry: bool = True

    def set_fallback_translator(self, fallback: Optional[BaseTranslator]) -> None:
        """Sets a secondary fallback translator to invoke if primary engine fails."""
        self.fallback_translator = fallback
        self._fallback = fallback

    def emit_log(self, level: str, message: str):
        """Emits log to both standard logger and UI status callback."""
        # ... logic as before ...
        if level.lower() == "error":
            self.logger.error(message)
        elif level.lower() == "warning":
            self.logger.warning(message)
        else:
            self.logger.info(message)

        if self.status_callback:
            self.status_callback(level, message)

    async def _get_session(self) -> aiohttp.ClientSession:
        """
        Get or create a reused client session with optimized TCP/DNS settings.
        Implemented with Double-Checked Locking to prevent race conditions in high concurrency.
        """
        if self._session and not self._session.closed:
            return self._session

        async with self._session_lock:
            # Second check inside lock
            if self._session and not self._session.closed:
                return self._session

            # TCP Connector Optimization
            self._connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=20,
                ttl_dns_cache=300,
                use_dns_cache=True,
                force_close=False,
                enable_cleanup_closed=True,
                # Packaged Linux builds carry the build machine's OpenSSL paths;
                # see src/utils/net.py (GitHub #23).
                ssl=build_ssl_context(),
            )

            timeout = aiohttp.ClientTimeout(total=45, connect=10, sock_read=30)

            headers = {"Connection": "keep-alive"}
            if hasattr(self, "user_agents") and self.user_agents:
                headers["User-Agent"] = random.choice(self.user_agents)

            self._session = aiohttp.ClientSession(
                connector=self._connector, timeout=timeout, headers=headers
            )
            return self._session

    _tls_error_reported = False

    def note_tls_error(self, exc: BaseException) -> bool:
        """True (and logs once) when ``exc`` is a certificate verification failure.

        Callers skip their backoff / mirror-ban path for it: retrying another
        mirror cannot fix a missing CA store and only made runs crawl (#23).
        """
        if not _net.is_certificate_error(exc):
            return False
        if not BaseTranslator._tls_error_reported:
            BaseTranslator._tls_error_reported = True
            self.logger.error(
                "TLS certificate verification failed (%s). CA source: %s. "
                "Set SSL_CERT_FILE to your system CA bundle (e.g. /etc/ssl/cert.pem) and restart.",
                exc,
                _net.ssl_context_source or "unknown",
            )
        return True

    def _get_text(self, key: str, default: str, **kwargs) -> str:
        """Helper to get localized text from config_manager."""
        try:
            if self.config_manager:
                return self.config_manager.get_ui_text(key, default).format(**kwargs)
            return default.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            # Locale file may have mismatched format keys
            if self.config_manager:
                return self.config_manager.get_ui_text(key, default)
            return default

    async def close(self):
        if self._session:
            try:
                await self._session.close()
            except Exception:
                self.logger.debug("Failed to close aiohttp session")
            self._session = None
            self._connector = None

    async def close_session(self):
        """Alias for close() to match naming convention used in detection logic."""
        await self.close()

    def set_proxy_enabled(self, enabled: bool):
        self.use_proxy = enabled

    def _proxy_url(self) -> Optional[str]:
        """The user's proxy for the next request, or None (Settings > Proxy)."""
        if self.use_proxy and self.proxy_manager:
            proxy = self.proxy_manager.get_next_proxy()
            if proxy:
                return proxy.url
        return None

    async def _make_request(self, url: str, method: str = "GET", **kwargs):
        session = await self._get_session()
        proxy = None
        if self.use_proxy and self.proxy_manager:
            p = self.proxy_manager.get_next_proxy()
            if p:
                proxy = p.url
        if method.upper() == "GET":
            async with session.get(url, proxy=proxy, **kwargs) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
                raise RuntimeError(
                    self._get_text(
                        "error_http", f"HTTP {resp.status}", status=resp.status
                    )
                )
        elif method.upper() == "POST":
            async with session.post(url, proxy=proxy, **kwargs) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
                raise RuntimeError(
                    self._get_text(
                        "error_http", f"HTTP {resp.status}", status=resp.status
                    )
                )
        else:
            raise ValueError(
                self._get_text("error_unsupported_method", "Unsupported method")
            )

    @abstractmethod
    async def translate_single(
        self, request: TranslationRequest
    ) -> TranslationResult: ...

    async def translate_batch(
        self, requests: List[TranslationRequest]
    ) -> List[TranslationResult]:
        is_parallel = getattr(self, "enable_parallel_batch", True)
        if hasattr(self, "config_manager") and self.config_manager:
            is_parallel = getattr(
                getattr(self.config_manager, "translation_settings", None),
                "enable_parallel_batch",
                is_parallel,
            )
        if not is_parallel or len(requests) <= 1:
            return [await self.translate_single(r) for r in requests]

        limit = getattr(self, "multi_q_concurrency", 4)
        sem = asyncio.Semaphore(limit)

        async def _guarded(req: TranslationRequest) -> TranslationResult:
            async with sem:
                return await self.translate_single(req)

        return list(await asyncio.gather(*[_guarded(r) for r in requests]))

    @abstractmethod
    def get_supported_languages(self) -> Dict[str, str]: ...

    def _check_integrity(self, text: str, placeholders: Dict[str, str]) -> bool:
        """
        Check if all original placeholder values (e.g., [name], {{tag}}) are present in the text.
        Returns False if any placeholder value is missing.
        """
        if not placeholders:
            return True

        # Orijinal tokenlerin (örn: [name]) çevrilmiş metinde geçip geçmediğine bak
        # Case-insensitive arama yapalım çünkü AI bazen büyük/küçük harf değiştirebilir
        text_lower = text.lower()
        for orig_val in placeholders.values():
            if orig_val.lower().strip() not in text_lower:
                return False
        return True


