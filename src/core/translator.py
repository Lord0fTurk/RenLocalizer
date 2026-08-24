"""Temiz ve stabilize çeviri altyapısı (Google + stub motorlar + cache + adaptif concurrency)."""

from __future__ import annotations

import asyncio
import aiohttp
import logging
import os
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple, Callable
from abc import ABC, abstractmethod
from collections import OrderedDict, deque, Counter
import random

from .syntax_guard import (
    protect_renpy_syntax,
    restore_renpy_syntax,
    validate_translation_integrity,
    inject_missing_placeholders,
    protect_renpy_syntax_html,
    restore_renpy_syntax_html,
)

from src.core.constants import (
    GOOGLE_ENDPOINTS,
    GOOGLE_BROWSER_HEADERS,
    GOOGLE_CLIENTS5_ENDPOINT,
    LINGVA_INSTANCES,
    USER_AGENTS,
    MIRROR_MAX_FAILURES,
    MIRROR_BAN_TIME,
    RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD,
    RATE_LIMIT_LONG_COOLDOWN,
    RATE_LIMIT_PRIMARY_PROBE_INTERVAL,
)
from src.core.exceptions import (
    RateLimitError,
    QuotaExceededError,
    NetworkConnectionError,
)
from src.utils.config import get_effective_batch_size
from src.version import VERSION as _APP_VERSION


class TranslationEngine(Enum):
    GOOGLE = "google"
    DEEPL = "deepl"
    OPENAI = "openai"
    GEMINI = "gemini"
    LOCAL_LLM = "local_llm"
    LIBRETRANSLATE = "libretranslate"
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
            )

            timeout = aiohttp.ClientTimeout(total=45, connect=10, sock_read=30)

            headers = {"Connection": "keep-alive"}
            if hasattr(self, "user_agents") and self.user_agents:
                headers["User-Agent"] = random.choice(self.user_agents)

            self._session = aiohttp.ClientSession(
                connector=self._connector, timeout=timeout, headers=headers
            )
            return self._session

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


class GoogleTranslator(BaseTranslator):
    """Multi-endpoint Google Translator with Lingva fallback.

    Uses multiple Google mirrors in parallel for faster translation,
    with Lingva Translate as a free fallback when Google fails.
    """

    # Use imported constants instead of hardcoded lists
    google_endpoints = GOOGLE_ENDPOINTS
    lingva_instances = LINGVA_INSTANCES

    # Default values (can be overridden from config)
    multi_q_concurrency = 16  # Paralel endpoint istekleri
    max_slice_chars = 1800  # Bir istekteki maksimum karakter (URL limit prevent)
    max_texts_per_slice = (
        50  # Maximum texts per slice (capped at separator batch limit)
    )
    use_multi_endpoint = True  # Çoklu endpoint kullan
    enable_lingva_fallback = True  # Lingva fallback aktif

    # Mirror Health Check Settings
    MIRROR_MAX_FAILURES = MIRROR_MAX_FAILURES  # Max failures before temp ban
    MIRROR_BAN_TIME = MIRROR_BAN_TIME  # Ban duration in seconds (2 min)

    def _supports_html_protection(self) -> bool:
        """
        HTML mode is reliable on official Cloud Translation HTML APIs,
        but this translator uses public web endpoints (/translate_a/single)
        where HTML handling is inconsistent.
        """
        return not any("/translate_a/single" in ep for ep in self.google_endpoints)

    def _compute_global_cooldown(self) -> float:
        """Shared 429 backoff for the single/batch paths (Google throttles by
        IP, so all mirrors share one cooldown clock). Escalates exponentially
        up to 60s; at RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD consecutive 429s the
        IP is treated as flagged and requests pause for RATE_LIMIT_LONG_COOLDOWN.
        """
        if self._consecutive_429_count >= RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD:
            return float(RATE_LIMIT_LONG_COOLDOWN)
        return min(3.0 * (2 ** (self._consecutive_429_count - 1)), 60.0)

    def _apply_global_cooldown(self) -> float:
        """Increment the 429 counter, set the shared cooldown, and announce the
        circuit breaker once per episode (arming the primary-probe window so
        primaries stay silent until RATE_LIMIT_PRIMARY_PROBE_INTERVAL has
        passed). Returns the cooldown seconds."""
        self._consecutive_429_count += 1
        global_wait = self._compute_global_cooldown()
        self._global_cooldown_until = time.time() + global_wait
        if self._consecutive_429_count == RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD:
            self._primary_probe_at = time.time() + RATE_LIMIT_PRIMARY_PROBE_INTERVAL
            self.logger.warning(
                f"Google IP rate limit persists after {self._consecutive_429_count} "
                f"consecutive 429s — switching to alternate endpoint family for "
                f"{RATE_LIMIT_LONG_COOLDOWN}s. Enable a residential proxy in "
                f"Settings or wait for the IP flag to decay."
            )
        return global_wait

    async def _wait_out_global_cooldown(self, max_wait: float = 25.0) -> None:
        """Gate each send attempt on the shared cooldown clock so parallel
        workers cannot hammer Google while it is active."""
        remaining = self._global_cooldown_until - time.time()
        if remaining > 0:
            await asyncio.sleep(min(remaining, max_wait))

    def _prepare_request_protection(
        self, request: TranslationRequest
    ) -> Tuple[str, Dict[str, str], bool]:
        """
        Prepare request text/placeholders for translation.

        If request.metadata carries preprotected text + placeholders (pipeline mode),
        avoid applying protect_renpy_syntax() again.
        """
        metadata = request.metadata if isinstance(request.metadata, dict) else {}
        preprotected = bool(metadata.get("preprotected"))
        placeholders = metadata.get("placeholders")

        if preprotected and isinstance(placeholders, dict):
            return request.text, placeholders, False

        if self.use_html_protection:
            return protect_renpy_syntax_html(request.text), {}, True

        protected_text, protected_placeholders = protect_renpy_syntax(request.text)
        return protected_text, protected_placeholders, False

    def __init__(self, *args, config_manager=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._endpoint_index = 0

        # Start from a random Lingva instance to distribute load / avoid dead first server
        self._lingva_index = 0
        if self.lingva_instances:
            self._lingva_index = random.randint(0, len(self.lingva_instances) - 1)

        self._endpoint_health: Dict[
            str, dict
        ] = {}  # {url: {'fails': int, 'banned_until': float}}
        # Global cooldown: when ANY mirror gets 429, ALL mirrors pause briefly
        # because Google rate-limits by IP, not by mirror domain.
        self._global_cooldown_until: float = 0.0
        self._consecutive_429_count: int = (
            0  # Track consecutive 429s across all mirrors
        )
        # Next wall-clock time at which a blocked primary endpoint may be
        # probed again (one request per RATE_LIMIT_PRIMARY_PROBE_INTERVAL).
        self._primary_probe_at: float = 0.0
        # Alternate-family (clients5) rescue counter — drives the periodic
        # user-visible status line while primaries are IP-blocked.
        self._clients5_rescues: int = 0

        # Initialize health tracking for all endpoints
        for ep in self.google_endpoints:
            self._endpoint_health[ep] = {"fails": 0, "banned_until": 0.0}

        # Load settings from config if available
        if config_manager:
            ts = config_manager.translation_settings
            self.use_multi_endpoint = getattr(ts, "use_multi_endpoint", True)
            self.enable_lingva_fallback = getattr(ts, "enable_lingva_fallback", True)
            self.enable_parallel_batch = getattr(ts, "enable_parallel_batch", True)
            # Slider ile kontrol edilen 'max_concurrent_threads' değerini baz alıyoruz
            self.multi_q_concurrency = getattr(ts, "max_concurrent_threads", 16)
            self.max_slice_chars = getattr(ts, "max_chars_per_request", 2000)
            self.max_texts_per_slice = min(
                get_effective_batch_size(
                    getattr(ts, "max_batch_size", 200),
                    TranslationEngine.GOOGLE,
                ),
                50,  # Google separator batch max
            )
            self.aggressive_retry = getattr(ts, "aggressive_retry_translation", False)
            # HTML Protection: force-off for Google web endpoints (/translate_a/single).
            # Those endpoints are unofficial and HTML behavior is inconsistent.
            requested_html_protection = getattr(ts, "use_html_protection", False)
            self.use_html_protection = (
                requested_html_protection and self._supports_html_protection()
            )
            if requested_html_protection and not self.use_html_protection:
                self.logger.warning(
                    "HTML protection requested but disabled for Google web endpoints; using token protection mode."
                )
            # Read request_delay for Google rate limiting
            self._google_request_delay = getattr(ts, "request_delay", 0.1)
        else:
            self.aggressive_retry = False
            self.use_html_protection = False  # Match config default
            self._google_request_delay = 0.1

        # Keep a baseline to restore when proxy adaptasyonu devre dışı
        self._base_multi_q_concurrency = self.multi_q_concurrency

    async def _get_next_endpoint(self) -> str:
        """Random endpoint selection with health checks and ban cooldown."""
        now = time.time()

        # Breaker active: callers bail instantly via the guard, so honoring
        # the shared cooldown sleep here would just stall every item for
        # min(cooldown, 25)s without sending anything.
        if (
            self._consecutive_429_count >= RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD
            and now < self._primary_probe_at
        ):
            return random.choice(self.google_endpoints)

        # Respect global cooldown (IP-based rate limit from Google).
        # Cap matches _wait_out_global_cooldown so a long circuit-breaker
        # pause spaces requests out instead of blocking one worker forever.
        if now < self._global_cooldown_until:
            remaining = self._global_cooldown_until - now
            await asyncio.sleep(min(remaining, 25.0))
            now = time.time()

        # Filter available endpoints (not banned)
        available = []
        for ep in self.google_endpoints:
            health = self._endpoint_health.get(ep, {"fails": 0, "banned_until": 0.0})
            if now > health["banned_until"]:
                # Unban if time expired
                if health["banned_until"] > 0:
                    health["banned_until"] = 0.0
                    health["fails"] = 0  # Reset failures after ban
                available.append(ep)

        if not available:
            # All mirrors banned — apply cooldown before resetting
            # Find the earliest ban expiry to determine minimum wait
            earliest_expiry = min(
                h["banned_until"] for h in self._endpoint_health.values()
            )
            cooldown = max(0, earliest_expiry - now)
            # Cap cooldown at 30s to avoid excessive blocking
            cooldown = min(cooldown, 30.0)
            if cooldown > 0:
                self.logger.warning(
                    f"All Google mirrors banned! Waiting {cooldown:.0f}s before reset..."
                )
                await asyncio.sleep(min(cooldown, 10.0))
            else:
                self.logger.warning(
                    "All Google mirrors banned! Resetting health checks."
                )
            for ep in self.google_endpoints:
                self._endpoint_health[ep] = {"fails": 0, "banned_until": 0.0}
            available = self.google_endpoints

        # Use random selection instead of broken round-robin
        # (global _endpoint_index + dynamic available list = same mirror repeatedly)
        return random.choice(available)

    def _get_next_lingva(self) -> Optional[str]:
        """Round-robin Lingva instance selection. Returns None if no instances available."""
        if not self.lingva_instances:
            return None
        self._lingva_index = (self._lingva_index + 1) % len(self.lingva_instances)
        return self.lingva_instances[self._lingva_index]

    async def _translate_via_lingva(
        self, text: str, source: str, target: str
    ) -> Optional[str]:
        """Translate using Lingva (free Google proxy, no API key)."""
        # Lingva uses different language codes
        lingva_source = source if source != "auto" else "auto"

        for _ in range(len(self.lingva_instances)):
            instance = self._get_next_lingva()
            # Encode specifically for Lingva URL structure
            url = f"{instance}/api/v1/{lingva_source}/{target}/{urllib.parse.quote(text, safe='')}"

            try:
                session = await self._get_session()
                # Reduced timeout to 6s for faster failover
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=6)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data and "translation" in data:
                            return data["translation"]
            except Exception as e:
                self.logger.debug(f"Lingva {instance} failed: {e}")
                continue

        return None

    @staticmethod
    def _extract_clients5_text(data) -> Optional[str]:
        """Normalize /translate_a/t responses: ["tr"] or [["tr", "src"], ...]."""
        if not isinstance(data, list):
            return None
        parts = []
        for item in data:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, list) and item and isinstance(item[0], str):
                parts.append(item[0])
        return "".join(parts) or None

    async def _translate_via_clients5(
        self, text: str, source: str, target: str
    ) -> Optional[str]:
        """Fallback via clients5.google.com /translate_a/t (Chrome dictionary
        client). This endpoint family keeps serving traffic when the
        /translate_a/single family is IP-range blocked."""
        params = {
            "client": "dict-chrome-ex",
            "sl": source or "auto",
            "tl": target,
            "q": text,
        }
        try:
            session = await self._get_session()
            async with session.get(
                GOOGLE_CLIENTS5_ENDPOINT,
                params=params,
                timeout=aiohttp.ClientTimeout(total=8),
                headers=GOOGLE_BROWSER_HEADERS,
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
                return self._extract_clients5_text(data)
        except Exception as e:
            self.logger.debug(f"clients5 fallback failed: {e}")
            return None

    async def translate_single(self, request: TranslationRequest) -> TranslationResult:
        """Translate single text with multi-endpoint + Lingva fallback."""
        metadata = request.metadata if isinstance(request.metadata, dict) else {}
        source_text = metadata.get("original_text") or getattr(
            metadata.get("entry"), "original_text", request.text
        )

        # Ren'Py değişkenlerini koru (veya pipeline'dan gelen preprotected veriyi kullan)
        protected_text, placeholders, request_use_html = (
            self._prepare_request_protection(request)
        )

        if request_use_html:
            # HTML wrap protection for tag-preserving requests
            # Add format=html to preserve tags
            params = {
                "client": "gtx",
                "sl": request.source_lang,
                "tl": request.target_lang,
                "dt": "t",
                "q": protected_text,
                "format": "html",  # IMPORTANT!
            }
        else:
            # Token placeholder mode — uses preprotected data from pipeline
            # or freshly generated protection from _prepare_request_protection.
            # CRITICAL: Do NOT re-call protect_renpy_syntax here; that would
            # double-protect already-tokenised text and cause nested tokens.
            params = {
                "client": "gtx",
                "sl": request.source_lang,
                "tl": request.target_lang,
                "dt": "t",
                "q": protected_text,
            }

        # Try Google endpoints first (parallel race)
        async def try_endpoint(endpoint: str) -> Optional[str]:
            # Circuit breaker active: /translate_a/single is range-blocked,
            # skip straight to the alternate-family rescue below. Primaries
            # are probed once per RATE_LIMIT_PRIMARY_PROBE_INTERVAL so a
            # decayed IP flag is picked up automatically.
            entered_as_probe = False
            if self._consecutive_429_count >= RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD:
                now = time.time()
                if now < self._primary_probe_at:
                    return None
                self._primary_probe_at = (
                    now + RATE_LIMIT_PRIMARY_PROBE_INTERVAL
                )
                entered_as_probe = True
            max_attempts = 3
            for attempt in range(1, max_attempts + 1):
                # Another worker's 429 tripped the breaker mid-flight — stop
                # burning attempts against a range-blocked host.
                if (
                    self._consecutive_429_count
                    >= RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD
                    and not entered_as_probe
                ):
                    return None
                await self._wait_out_global_cooldown()
                try:
                    query = urllib.parse.urlencode(params, doseq=True, safe="")
                    url = f"{endpoint}?{query}"
                    session = await self._get_session()

                    proxy = None
                    proxy_url_used = None
                    if self.use_proxy and self.proxy_manager:
                        p = self.proxy_manager.get_next_proxy()
                        if p:
                            proxy = p.url
                            proxy_url_used = proxy

                    async with session.get(
                        url,
                        proxy=proxy,
                        timeout=aiohttp.ClientTimeout(total=8),
                        headers=GOOGLE_BROWSER_HEADERS,
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json(content_type=None)
                            if data and isinstance(data, list) and data[0]:
                                text = "".join(
                                    part[0] for part in data[0] if part and part[0]
                                )
                                # Check for empty/corrupted response (Google sometimes returns 200 with garbage)
                                if text and len(text.strip()) > 0:
                                    # Successful translation: Reset failure count and 429 counter
                                    if endpoint in self._endpoint_health:
                                        self._endpoint_health[endpoint]["fails"] = 0
                                    self._consecutive_429_count = max(
                                        0, self._consecutive_429_count - 1
                                    )
                                    # Report proxy success
                                    if proxy_url_used and self.proxy_manager:
                                        self.proxy_manager.mark_proxy_success(
                                            proxy_url_used
                                        )
                                    return text
                            # 200 but empty/no data = soft ban signal from Google
                            if endpoint in self._endpoint_health:
                                self._endpoint_health[endpoint]["fails"] += 1
                            if proxy_url_used and self.proxy_manager:
                                self.proxy_manager.mark_proxy_failed(proxy_url_used)
                            continue

                        elif resp.status == 429:  # Too Many Requests
                            # Google rate-limits by IP — a 429 on one mirror means ALL mirrors
                            # are likely throttled. Apply global cooldown to prevent cascade bans.
                            global_wait = self._apply_global_cooldown()
                            # Also count as fail — 429 is a real failure signal
                            if endpoint in self._endpoint_health:
                                self._endpoint_health[endpoint]["fails"] += 1
                            if proxy_url_used and self.proxy_manager:
                                self.proxy_manager.mark_proxy_failed(proxy_url_used)
                            wait_time = min(global_wait, 25.0) + random.uniform(0.5, 1.5)
                            self.logger.warning(
                                f"Google 429 (Rate Limit) on {endpoint}. Global cooldown {global_wait:.0f}s (#{self._consecutive_429_count})"
                            )
                            await asyncio.sleep(wait_time)
                            continue

                        # Other HTTP errors (500, 403, etc.)
                        if endpoint in self._endpoint_health:
                            self._endpoint_health[endpoint]["fails"] += 1
                        if proxy_url_used and self.proxy_manager:
                            self.proxy_manager.mark_proxy_failed(proxy_url_used)

                except aiohttp.ClientError as e:
                    # Network/Timeout errors — likely proxy failure
                    if proxy_url_used and self.proxy_manager:
                        self.proxy_manager.mark_proxy_failed(proxy_url_used)
                    err = NetworkConnectionError(str(e), context={"endpoint": endpoint})
                    self.logger.debug(err.get_user_friendly_message())
                    # Mild Backoff: Wait 1s -> 2s
                    wait_time = (1.5**attempt) * 0.5
                    await asyncio.sleep(wait_time)
                    if endpoint in self._endpoint_health:
                        self._endpoint_health[endpoint]["fails"] += 1
                except asyncio.TimeoutError as e:
                    if proxy_url_used and self.proxy_manager:
                        self.proxy_manager.mark_proxy_failed(proxy_url_used)
                    err = NetworkConnectionError(f"Timeout: {e}", context={"endpoint": endpoint})
                    self.logger.debug(err.get_user_friendly_message())
                    wait_time = (1.5**attempt) * 0.5
                    await asyncio.sleep(wait_time)
                    if endpoint in self._endpoint_health:
                        self._endpoint_health[endpoint]["fails"] += 1
                except Exception:
                    # Network/Timeout errors — likely proxy failure
                    if proxy_url_used and self.proxy_manager:
                        self.proxy_manager.mark_proxy_failed(proxy_url_used)
                    # Mild Backoff: Wait 1s -> 2s
                    wait_time = (1.5**attempt) * 0.5
                    await asyncio.sleep(wait_time)
                    if endpoint in self._endpoint_health:
                        self._endpoint_health[endpoint]["fails"] += 1

                # Check if we should ban the mirror after this attempt
                if endpoint in self._endpoint_health:
                    if (
                        self._endpoint_health[endpoint]["fails"]
                        >= self.MIRROR_MAX_FAILURES
                    ):
                        self._endpoint_health[endpoint]["banned_until"] = (
                            time.time() + self.MIRROR_BAN_TIME
                        )
                        self.logger.warning(
                            f"Google Mirror BANNED temporarily (2min): {endpoint}"
                        )
                        return None  # Stop retrying this endpoint if banned

            return None

        translated_text = None
        max_unchanged_retries = 2  # Retry limit for unchanged translations

        # Multi-endpoint mode: Try 1 endpoint at a time to reduce ban pressure
        # (previously tried 2 in parallel, doubling request rate and causing cascade bans)
        if self.use_multi_endpoint:
            endpoints_to_try = [await self._get_next_endpoint()]
            tasks = [asyncio.create_task(try_endpoint(ep)) for ep in endpoints_to_try]

            # Wait for first successful result
            for coro in asyncio.as_completed(tasks):
                result = await coro
                if result:
                    # Cancel remaining tasks
                    for t in tasks:
                        if not t.done():
                            t.cancel()

                    # Restore logic based on protection mode
                    if self.use_html_protection:
                        final_text = restore_renpy_syntax_html(result)
                        # HTML modundaysa truncation check yap, integrity zaten HTML ile korunuyor
                        original_len = len(source_text)
                        if original_len > 20 and len(final_text) < (original_len * 0.1):
                            self.logger.warning(
                                f"Potential truncation detected (HTML mode). Original: {original_len}, Final: {len(final_text)}"
                            )
                            # Do NOT revert, let the user see the result.
                            # final_text = request.text
                        missing_vars = []  # HTML mode is safe by default
                    else:
                        final_text = restore_renpy_syntax(result, placeholders)
                        missing_vars = validate_translation_integrity(
                            final_text, placeholders
                        )

                    # 2. AŞAMA KORUMA (Validation - Global)
                    if missing_vars:
                        # v3.6: Token tamamen silinmiş mi kontrol et.
                        # Google raw çıktısında RLPH yoksa retry ve Lingva boşuna —
                        # aynı format tekrar silinecek. Doğrudan injection'a geç.
                        _tokens_totally_deleted = "RLPH" not in result
                        retry_success = False

                        if _tokens_totally_deleted:
                            self.logger.warning(
                                f"Integrity check failed (Google Multi): {missing_vars}. Tokens deleted, skipping retries..."
                            )
                        else:
                            self.logger.warning(
                                f"Integrity check failed (Google Multi): {missing_vars}. Retrying (2 attempts)..."
                            )
                            for _ in range(2):
                                await asyncio.sleep(0.2)
                                retry_res = await try_endpoint(
                                    await self._get_next_endpoint()
                                )
                                if retry_res:
                                    retry_text = restore_renpy_syntax(
                                        retry_res, placeholders
                                    )
                                    if not validate_translation_integrity(
                                        retry_text, placeholders
                                    ):
                                        final_text = retry_text
                                        retry_success = True
                                        break

                            if not retry_success and self.enable_lingva_fallback:
                                self.logger.warning(
                                    "Integrity retries failed (Multi). Trying Lingva fallback..."
                                )
                                try:
                                    lingva_result = await self._translate_via_lingva(
                                        protected_text,
                                        request.source_lang,
                                        request.target_lang,
                                    )
                                    if lingva_result:
                                        lingva_final = restore_renpy_syntax(
                                            lingva_result, placeholders
                                        )
                                        if not validate_translation_integrity(
                                            lingva_final, placeholders
                                        ):
                                            final_text = lingva_final
                                            retry_success = True
                                            self.logger.info(
                                                "Lingva rescued the translation!"
                                            )
                                except Exception:
                                    self.logger.debug("Lingva rescue attempt failed")

                        if not retry_success:
                            self.logger.warning("Attempting placeholder injection...")
                            injected = inject_missing_placeholders(
                                final_text, protected_text, placeholders, missing_vars
                            )
                            still_missing = validate_translation_integrity(
                                injected, placeholders
                            )
                            if not still_missing:
                                self.logger.info(
                                    "Placeholder injection rescued the translation!"
                                )
                                final_text = injected
                            elif (
                                final_text.strip()
                                and final_text.strip() != source_text.strip()
                            ):
                                self.logger.warning(
                                    f"Partial rescue: {len(still_missing)} vars still missing. Using injected version."
                                )
                                final_text = injected
                            else:
                                self.logger.warning(
                                    "Injection failed. Reverting to original."
                                )
                                final_text = source_text

                    # If translation equals original and aggressive_retry is enabled
                    if (
                        self.aggressive_retry
                        and final_text.strip() == source_text.strip()
                    ):
                        self.logger.debug(
                            f"Translation unchanged. Starting Aggressive Retry chain..."
                        )

                        # LEVEL 1: Try another Google Endpoint
                        retry_google_res = await try_endpoint(
                            await self._get_next_endpoint()
                        )
                        if retry_google_res:
                            if self.use_html_protection:
                                retry_google_final = restore_renpy_syntax_html(
                                    retry_google_res
                                )
                            else:
                                retry_google_final = restore_renpy_syntax(
                                    retry_google_res, placeholders
                                )

                            # Validasyon
                            if (retry_google_final.strip() != source_text.strip()) and (
                                not validate_translation_integrity(
                                    retry_google_final, placeholders
                                )
                            ):
                                self.logger.info(
                                    "Aggressive: Alternative Google Endpoint succeeded!"
                                )
                                final_text = retry_google_final
                                # Success, return immediately
                                return TranslationResult(
                                    source_text,
                                    final_text,
                                    request.source_lang,
                                    request.target_lang,
                                    TranslationEngine.GOOGLE,
                                    True,
                                    metadata={"aggressive": True},
                                )

                        # LEVEL 2: Try Lingva fallback (Eğer Google yine başarısız olduysa)
                        if self.enable_lingva_fallback:
                            self.logger.debug(
                                "Aggressive: Google failed, trying Lingva..."
                            )
                            # Lingva uses same token protection as main request
                            lingva_input, lingva_map = protected_text, placeholders

                            for retry in range(max_unchanged_retries):
                                lingva_result = await self._translate_via_lingva(
                                    lingva_input,
                                    request.source_lang,
                                    request.target_lang,
                                )
                                if lingva_result:
                                    lingva_final = restore_renpy_syntax(
                                        lingva_result, lingva_map
                                    )

                                    # Validation for Lingva
                                    if validate_translation_integrity(
                                        lingva_final, lingva_map
                                    ):
                                        continue  # Skip if broken

                                    if lingva_final.strip() != source_text.strip():
                                        return TranslationResult(
                                            source_text,
                                            lingva_final,
                                            request.source_lang,
                                            request.target_lang,
                                            TranslationEngine.GOOGLE,
                                            True,
                                            confidence=0.85,
                                            metadata=request.metadata,
                                        )
                                await asyncio.sleep(0.5)  # Brief delay between retries

                        # Try different Google endpoints sequentially
                        for retry in range(max_unchanged_retries):
                            alt_endpoint = await self._get_next_endpoint()
                            alt_result = await try_endpoint(alt_endpoint)
                            if alt_result:
                                if self.use_html_protection:
                                    alt_final = restore_renpy_syntax_html(alt_result)
                                    # HTML mode is safe implicitly
                                else:
                                    alt_final = restore_renpy_syntax(
                                        alt_result, placeholders
                                    )
                                    # INTEGRITY CHECK
                                    if validate_translation_integrity(
                                        alt_final, placeholders
                                    ):
                                        self.logger.warning(
                                            "Integrity check failed (Retry): Placeholders missing."
                                        )
                                        continue

                                if alt_final.strip() != source_text.strip():
                                    return TranslationResult(
                                        source_text,
                                        alt_final,
                                        request.source_lang,
                                        request.target_lang,
                                        TranslationEngine.GOOGLE,
                                        True,
                                        confidence=0.85,
                                        metadata=request.metadata,
                                    )
                            await asyncio.sleep(0.3)

                        # All retries failed, return the unchanged text with lower confidence
                        # This is often expected for names, interjections, etc. - use DEBUG level
                        self.logger.debug(
                            f"Translation unchanged after retries: {request.text[:50]}"
                        )

                    return TranslationResult(
                        source_text,
                        final_text,
                        request.source_lang,
                        request.target_lang,
                        TranslationEngine.GOOGLE,
                        True,
                        confidence=0.9,
                        metadata=request.metadata,
                    )
        else:
            # Single endpoint mode
            result = await try_endpoint(await self._get_next_endpoint())
            if result:
                final_text = restore_renpy_syntax(result, placeholders)

                # 2. AŞAMA KORUMA (Validation - Global)
                missing_vars = validate_translation_integrity(final_text, placeholders)
                if missing_vars:
                    _tokens_totally_deleted = "RLPH" not in result
                    retry_success = False

                    if _tokens_totally_deleted:
                        self.logger.warning(
                            f"Integrity check failed (Google Single): {missing_vars}. Tokens deleted, skipping retries..."
                        )
                    else:
                        self.logger.warning(
                            f"Integrity check failed (Google Single): {missing_vars}. Retrying (2 attempts)..."
                        )
                        for _ in range(2):
                            await asyncio.sleep(0.2)
                            retry_res = await try_endpoint(
                                await self._get_next_endpoint()
                            )
                            if retry_res:
                                retry_text = restore_renpy_syntax(
                                    retry_res, placeholders
                                )
                                if not validate_translation_integrity(
                                    retry_text, placeholders
                                ):
                                    final_text = retry_text
                                    retry_success = True
                                    break

                        if not retry_success and self.enable_lingva_fallback:
                            self.logger.warning(
                                "Integrity retries failed (Single). Trying Lingva fallback..."
                            )
                            try:
                                lingva_result = await self._translate_via_lingva(
                                    protected_text,
                                    request.source_lang,
                                    request.target_lang,
                                )
                                if lingva_result:
                                    lingva_final = restore_renpy_syntax(
                                        lingva_result, placeholders
                                    )
                                    if not validate_translation_integrity(
                                        lingva_final, placeholders
                                    ):
                                        final_text = lingva_final
                                        retry_success = True
                                        self.logger.info(
                                            "Lingva rescued the translation (Single)!"
                                        )
                            except Exception:
                                self.logger.debug("Lingva rescue single attempt failed")

                    if not retry_success:
                        self.logger.warning(
                            "Attempting placeholder injection (Single)..."
                        )
                        injected = inject_missing_placeholders(
                            final_text, protected_text, placeholders, missing_vars
                        )
                        still_missing = validate_translation_integrity(
                            injected, placeholders
                        )
                        if not still_missing:
                            self.logger.info(
                                "Placeholder injection rescued the translation (Single)!"
                            )
                            final_text = injected
                        elif (
                            final_text.strip()
                            and final_text.strip() != source_text.strip()
                        ):
                            self.logger.warning(
                                f"Partial rescue (Single): {len(still_missing)} vars still missing."
                            )
                            final_text = injected
                        else:
                            self.logger.warning(
                                "Injection failed (Single). Reverting to original."
                            )
                            final_text = source_text

                # Retry if unchanged and aggressive_retry is enabled
                if self.aggressive_retry and final_text.strip() == source_text.strip():
                    self.logger.debug(
                        f"Single-mode: translation unchanged, retrying: {request.text[:50]}"
                    )

                    # Try Lingva
                    if self.enable_lingva_fallback:
                        # Lingva uses same token protection as main request
                        lingva_input, lingva_map = protected_text, placeholders

                        lingva_result = await self._translate_via_lingva(
                            lingva_input, request.source_lang, request.target_lang
                        )
                        if lingva_result:
                            lingva_final = restore_renpy_syntax(
                                lingva_result, lingva_map
                            )

                            # Validation
                            if not validate_translation_integrity(
                                lingva_final, placeholders
                            ):
                                if lingva_final.strip() != source_text.strip():
                                    return TranslationResult(
                                        source_text,
                                        lingva_final,
                                        request.source_lang,
                                        request.target_lang,
                                        TranslationEngine.GOOGLE,
                                        True,
                                        confidence=0.85,
                                        metadata=request.metadata,
                                    )

                    # Try alternative endpoints
                    for _ in range(max_unchanged_retries):
                        alt_result = await try_endpoint(await self._get_next_endpoint())
                        if alt_result:
                            alt_final = restore_renpy_syntax(alt_result, placeholders)

                            # Validation
                            if validate_translation_integrity(alt_final, placeholders):
                                continue

                            if alt_final.strip() != source_text.strip():
                                return TranslationResult(
                                    source_text,
                                    alt_final,
                                    request.source_lang,
                                    request.target_lang,
                                    TranslationEngine.GOOGLE,
                                    True,
                                    confidence=0.85,
                                    metadata=request.metadata,
                                )
                        await asyncio.sleep(0.3)

                return TranslationResult(
                    source_text,
                    final_text,
                    request.source_lang,
                    request.target_lang,
                    TranslationEngine.GOOGLE,
                    True,
                    confidence=0.9,
                    metadata=request.metadata,
                )

        # All Google endpoints failed, try alternate endpoint families then
        # the Lingva fallback (if enabled)
        if self.enable_lingva_fallback:
            c5_result = await self._translate_via_clients5(
                protected_text, request.source_lang, request.target_lang
            )
            if c5_result:
                c5_final = restore_renpy_syntax(c5_result, placeholders)
                if placeholders and validate_translation_integrity(
                    c5_final, placeholders
                ):
                    self.logger.warning(
                        "Integrity check failed (clients5): Placeholders missing. Using original text."
                    )
                elif c5_final.strip() != source_text.strip():
                    self._clients5_rescues += 1
                    if self._clients5_rescues == 1 or self._clients5_rescues % 50 == 0:
                        self.logger.warning(
                            f"Alternate Google endpoint active: "
                            f"{self._clients5_rescues} translations rescued while "
                            f"primary endpoints are IP-blocked."
                        )
                    return TranslationResult(
                        source_text,
                        c5_final,
                        request.source_lang,
                        request.target_lang,
                        TranslationEngine.GOOGLE,
                        True,
                        confidence=0.85,
                        metadata=request.metadata,
                    )

            self.logger.debug("Google endpoints failed, trying Lingva fallback...")

            # Lingva uses same token protection as main request
            lingva_input, lingva_map = protected_text, placeholders

            lingva_result = await self._translate_via_lingva(
                lingva_input, request.source_lang, request.target_lang
            )

            if lingva_result:
                # Ren'Py değişkenlerini geri koy
                final_text = restore_renpy_syntax(lingva_result, lingva_map)

                # BÜTÜNLÜK KONTROLÜ
                # validate_translation_integrity returns list of missing vars. If list is not empty, integrity failed.
                if lingva_map and validate_translation_integrity(
                    final_text, lingva_map
                ):
                    self.logger.warning(
                        f"Integrity check failed (Lingva): Placeholders missing in translation. Using original text."
                    )
                    final_text = source_text

                return TranslationResult(
                    source_text,
                    final_text,
                    request.source_lang,
                    request.target_lang,
                    TranslationEngine.GOOGLE,
                    True,
                    confidence=0.85,
                    metadata=request.metadata,
                )

        # Last resort: sync requests library
        try:
            import requests as req_lib

            def do():
                return req_lib.get(
                    self.google_endpoints[0],
                    params=params,
                    timeout=5,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    },
                )

            resp = await asyncio.to_thread(do)
            if resp.status_code == 200:
                data2 = resp.json()
                if data2 and isinstance(data2, list) and data2[0]:
                    text = "".join(part[0] for part in data2[0] if part and part[0])

                    if self.use_html_protection:
                        # Restore using HTML method
                        final_text = restore_renpy_syntax_html(text)
                        # HTML mode is safer by default
                    else:
                        # Ren'Py değişkenlerini geri koy
                        final_text = restore_renpy_syntax(text, placeholders)
                        # BÜTÜNLÜK KONTROLÜ
                        if placeholders and validate_translation_integrity(
                            final_text, placeholders
                        ):
                            self.logger.warning(
                                f"Integrity check failed (Fallback): Placeholders missing. Using original text."
                            )
                            final_text = source_text

                    return TranslationResult(
                        source_text,
                        final_text,
                        request.source_lang,
                        request.target_lang,
                        TranslationEngine.GOOGLE,
                        True,
                        confidence=0.8,
                        metadata=request.metadata,
                    )
        except Exception as e:
            self.logger.warning("translate_single failed for text=%r: %s", text, e)

        return TranslationResult(
            source_text,
            "",
            request.source_lang,
            request.target_lang,
            TranslationEngine.GOOGLE,
            False,
            self._get_text(
                "error_all_engines_failed", "All translation methods failed"
            ),
            metadata=request.metadata,
        )

    # =====================================================================
    # SMART LANGUAGE DETECTION
    # =====================================================================
    # Detect source language by analyzing multiple text samples using
    # majority voting. This prevents incorrect detection when games have
    # mixed-language content (e.g., English game with some Russian dialogue).
    # =====================================================================

    # Detection configuration constants
    DETECT_MIN_TEXT_LENGTH = 30  # Minimum characters for a sample to be valid
    DETECT_SAMPLE_SIZE = 15  # Number of samples to analyze
    DETECT_CONFIDENCE_THRESHOLD = (
        0.50  # Lowered because we use dynamic thresholding now
    )

    def _clean_text_for_detection(self, text: str) -> str:
        """Removes tags, brackets, and syntax noise to leave pure language."""
        if not text:
            return ""
        # Remove typical Ren'Py tags {b}, {color=#fff}, etc.
        text = re.sub(r"\{[^}]*\}", "", text)
        # Remove interpolation brackets [player_name], <RLPH..>
        text = re.sub(r"\[[^]]*\]", "", text)
        text = re.sub(r"<RLPH\d+>", "", text)
        # Remove other special characters that aren't language
        text = re.sub(r"[_\-\*\/\|\\\\]", " ", text)
        return text.strip()

    async def detect_language(
        self, texts: List[str], target_lang: str = None
    ) -> Optional[str]:
        """
        Detects source language from a list of text samples using an advanced
        aggregation and progressive thresholding strategy.
        """
        # Step 1: Clean texts from syntax noise
        clean_texts = [self._clean_text_for_detection(t) for t in texts]
        clean_texts = [
            t for t in clean_texts if t.strip()
        ]  # Remove empty after cleaning

        if not clean_texts:
            self.logger.debug(
                "[Smart Detect] No suitable text left after syntax cleaning"
            )
            return None

        # Step 2: Extract meaningful texts or use Aggregation
        candidates = [t for t in clean_texts if len(t) >= self.DETECT_MIN_TEXT_LENGTH]

        if len(candidates) < self.DETECT_SAMPLE_SIZE:
            # Aggregation Strategy: Concatenate shorter strings to form blocks.
            short_texts = [
                t for t in clean_texts if len(t) < self.DETECT_MIN_TEXT_LENGTH
            ]
            random.shuffle(short_texts)

            current_block = []
            current_len = 0

            for st in short_texts:
                current_block.append(st)
                current_len += len(st)

                # If block reached 40+ chars, treat it as one valid candidate
                if current_len >= 40:
                    candidates.append(" . ".join(current_block))
                    current_block = []
                    current_len = 0

                if len(candidates) >= self.DETECT_SAMPLE_SIZE:
                    break

            # Flush remaining if we have absolutely nothing else
            if current_block and not candidates:
                candidates.append(" . ".join(current_block))

        if not candidates:
            self.logger.warning("[Smart Detect] Could not create candidate blocks.")
            return None

        # Take random sample to avoid bias from specific game sections
        sample_size = min(self.DETECT_SAMPLE_SIZE, len(candidates))
        samples = random.sample(candidates, sample_size)

        self.logger.info(
            f"[Smart Detect] Analyzing {sample_size} text samples for language detection..."
        )

        # Detect language for each sample
        detected_langs: List[str] = []
        for text in samples:
            lang = await self._detect_single_language(text)
            if lang:
                detected_langs.append(lang)

        if not detected_langs:
            self.logger.warning(
                "[Smart Detect] Could not detect language from any sample"
            )
            return None

        # Step 3: Progressive Threshold Voting
        counter = Counter(detected_langs)
        most_common = counter.most_common(2)  # Get top 2

        winner_lang, winner_count = most_common[0]
        runner_up_count = most_common[1][1] if len(most_common) > 1 else 0

        total_votes = len(detected_langs)
        winner_confidence = winner_count / total_votes
        runner_up_confidence = runner_up_count / total_votes

        self.logger.info(
            f"[Smart Detect] Results: {dict(counter)} | Top: {winner_lang} ({winner_confidence:.0%})"
        )

        # Safety check: detected language should not equal target language
        if target_lang and winner_lang.lower() == target_lang.lower():
            self.logger.warning(
                f"[Smart Detect] Detected language ({winner_lang}) equals target language. Falling back to auto."
            )
            return None

        # Progressive Logic:
        # If absolute majority (>70%): Accept immediately
        # If relative majority (>40%) AND beats runner-up by at least 25 points: Accept
        is_absolute_winner = winner_confidence >= 0.70
        is_clear_victor = (winner_confidence >= 0.40) and (
            (winner_confidence - runner_up_confidence) >= 0.25
        )

        if is_absolute_winner or is_clear_victor:
            self.logger.info(
                f"[Smart Detect] ✓ Confirmed source language: {winner_lang}"
            )
            return winner_lang
        else:
            self.logger.warning(
                f"[Smart Detect] Results too ambiguous. Using auto mode."
            )
            return None

    async def _detect_single_language(self, text: str) -> Optional[str]:
        """
        Detects the language of a single text using Google Translate API.

        Args:
            text: Text to analyze (should be 30+ characters for accuracy)

        Returns:
            ISO 639-1 language code or None on error
        """
        # Use Google's language detection endpoint
        params = {
            "client": "gtx",
            "sl": "auto",
            "tl": "en",  # Target doesn't matter for detection
            "dt": "t",
            "q": text[:500],  # Limit text length for API efficiency
        }

        # Breaker active: primaries are range-blocked and _get_next_endpoint
        # would stall on the shared cooldown — go straight to the clients5
        # fallback below.
        breaker_active = (
            self._consecutive_429_count >= RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD
            and time.time() < self._primary_probe_at
        )

        if not breaker_active:
            try:
                endpoint = await self._get_next_endpoint()
                session = await self._get_session()

                async with session.get(
                    endpoint,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=5),
                    ssl=False,
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        # Google returns detected language at index [2]
                        # Format: [[["translated", "original", null, null, 10]], null, "detected_lang"]
                        if data and isinstance(data, list) and len(data) > 2:
                            detected = data[2]
                            if isinstance(detected, str) and len(detected) >= 2:
                                return detected.lower()
            except Exception as e:
                self.logger.debug(f"Language detection failed for sample: {e}")

        # Fallback: /translate_a/t auto mode returns [["text", "detected_lang"]]
        # and keeps working when /translate_a/single is blocked.
        try:
            session = await self._get_session()
            params5 = {
                "client": "dict-chrome-ex",
                "sl": "auto",
                "tl": "en",
                "q": text[:500],
            }
            async with session.get(
                GOOGLE_CLIENTS5_ENDPOINT,
                params=params5,
                timeout=aiohttp.ClientTimeout(total=6),
                ssl=False,
                headers=GOOGLE_BROWSER_HEADERS,
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if (
                        isinstance(data, list)
                        and data
                        and isinstance(data[0], list)
                        and len(data[0]) > 1
                        and isinstance(data[0][1], str)
                        and len(data[0][1]) >= 2
                    ):
                        return data[0][1].lower()
        except Exception as e:
            self.logger.debug(f"clients5 language detection failed: {e}")

        return None

    async def translate_batch(
        self, requests: List[TranslationRequest]
    ) -> List[TranslationResult]:
        """Optimize edilmiş toplu çeviri:
        1. Aynı metinleri tek sefer çevir (dedup)
        2. Büyük listeyi karakter limitine göre slice'lara böl
        3. Slice'ları paralel (bounded) multi-q istekleriyle çalıştır
        4. Orijinal sıra korunur
        """
        if not requests:
            return []

        # Apply adaptive concurrency only when proxy kullanımda ve havuz var
        try:
            if (
                hasattr(self, "proxy_manager")
                and self.proxy_manager
                and getattr(self, "use_proxy", False)
                and getattr(self.proxy_manager, "proxies", None)
            ):
                adaptive = self.proxy_manager.get_adaptive_concurrency()
                adaptive = max(2, min(adaptive, 64))
                self.logger.debug(f"Adaptive concurrency applied: {adaptive}")
                self.multi_q_concurrency = adaptive
            else:
                # Proxy yoksa başlangıç değerine dön
                base = getattr(self, "_base_multi_q_concurrency", None)
                if base:
                    self.multi_q_concurrency = base
        except Exception:
            self.logger.debug("Failed to parse multi-q concurrency setting")

        self.logger.info(
            f"Starting batch translation: {len(requests)} texts, max_slice_chars={self.max_slice_chars}, concurrency={self.multi_q_concurrency}"
        )

        # Dil çifti karışık ise fallback
        sl = {r.source_lang for r in requests}
        tl = {r.target_lang for r in requests}
        if len(sl) > 1 or len(tl) > 1:
            return await super().translate_batch(requests)

        # Deduplikasyon
        indexed = list(enumerate(requests))
        unique_map: Dict[str, int] = {}
        unique_list: List[Tuple[int, TranslationRequest]] = []
        dup_links: Dict[int, int] = {}  # original_index -> unique_index
        for idx, req in indexed:
            key = req.text
            if key in unique_map:
                dup_links[idx] = unique_map[key]
            else:
                u_index = len(unique_list)
                unique_map[key] = u_index
                unique_list.append((idx, req))
                dup_links[idx] = u_index

        # Slice oluştur (karakter limiti + metin sayısı limiti)
        slices: List[List[Tuple[int, TranslationRequest]]] = []
        cur: List[Tuple[int, TranslationRequest]] = []
        cur_chars = 0
        for item in unique_list:
            text_len = len(item[1].text)
            # Hem karakter hem metin sayısı limitini kontrol et
            if cur and (
                cur_chars + text_len > self.max_slice_chars
                or len(cur) >= self.max_texts_per_slice
            ):
                slices.append(cur)
                cur = []
                cur_chars = 0
            cur.append(item)
            cur_chars += text_len
        if cur:
            slices.append(cur)

        self.logger.info(
            f"Dedup: {len(requests)} -> {len(unique_list)} unique, {len(slices)} slices"
        )

        # Paralel mi sıralı mı çalıştırılacak kontrol et
        is_parallel = getattr(self, "enable_parallel_batch", True)
        if hasattr(self, "config_manager") and self.config_manager:
            is_parallel = getattr(
                getattr(self.config_manager, "translation_settings", None),
                "enable_parallel_batch",
                is_parallel,
            )

        concurrency_limit = self.multi_q_concurrency if is_parallel else 1
        sem = asyncio.Semaphore(concurrency_limit)

        async def run_slice(slice_items: List[Tuple[int, TranslationRequest]]):
            async with sem:
                reqs = [r for _, r in slice_items]
                results = await self._multi_q(reqs)
                # slice içindeki index eşleşmesi (aynı uzunluk varsayımı)
                return [(slice_items[i][0], results[i]) for i in range(len(results))]

        tasks = [asyncio.create_task(run_slice(s)) for s in slices]
        gathered: List[List[Tuple[int, TranslationResult]]] = await asyncio.gather(
            *tasks
        )
        # Unique sonuç tablosu (unique sıraya göre)
        unique_results: Dict[int, TranslationResult] = {}
        for lst in gathered:
            for orig_idx, res in lst:
                # orig_idx burada unique_list içindeki orijinal global indeks değil; unique_list'te kaydettiğimiz idx
                # slice_items'te (global_index, request) vardı => orig_idx global index
                # unique index'i bulmak için dup_links'den tersine gerek yok; map oluşturalım
                # Hız için text'e göre de eşleyebilirdik; burada global index'ten unique index'e gidelim
                # unique index bul:
                # performans için bir kere hesaplanıyor
                pass

        # Daha hızlı yol: unique_list sırasına göre slice çıktılarından doldur
        # unique_list[i][0] = global index; onun sonucunu bulmak için hashedict
        global_to_result: Dict[int, TranslationResult] = {}
        for lst in gathered:
            for global_idx, res in lst:
                global_to_result[global_idx] = res

        # Şimdi tüm orijinal indeksleri sırayla doldururken dedup'u kopyala
        final_results: List[TranslationResult] = [None] * len(requests)  # type: ignore
        for original_idx, req in indexed:
            unique_idx = dup_links[original_idx]
            unique_global_index = unique_list[unique_idx][0]
            base_res = global_to_result[unique_global_index]
            if base_res is None:
                # Güvenlik fallback
                final_results[original_idx] = TranslationResult(
                    req.text,
                    "",
                    req.source_lang,
                    req.target_lang,
                    TranslationEngine.GOOGLE,
                    False,
                    "Missing base result",
                )
            else:
                # Aynı referansı paylaşmak yerine kopya (metadata farklı olabilir)
                final_results[original_idx] = TranslationResult(
                    original_text=req.text,
                    translated_text=base_res.translated_text,
                    source_lang=req.source_lang,
                    target_lang=req.target_lang,
                    engine=base_res.engine,
                    success=base_res.success,
                    error=base_res.error,
                    confidence=base_res.confidence,
                    metadata=req.metadata,
                )

        # POST-BATCH RETRY: Check for unchanged translations and retry them individually
        # Only enabled when aggressive_retry is True (configurable in settings)
        if self.aggressive_retry:
            unchanged_indices = []
            for idx, (req, res) in enumerate(zip(requests, final_results)):
                if (
                    res
                    and res.success
                    and res.translated_text.strip() == req.text.strip()
                ):
                    unchanged_indices.append(idx)

            if (
                unchanged_indices and len(unchanged_indices) <= 100
            ):  # Limit retry batch size
                self.logger.info(
                    f"Batch retry: {len(unchanged_indices)} unchanged translations found, retrying individually..."
                )

                # Retry unchanged translations with translate_single (which has full retry logic)
                sem = asyncio.Semaphore(self.multi_q_concurrency)

                async def retry_one(idx: int) -> Tuple[int, TranslationResult]:
                    async with sem:
                        req = requests[idx]
                        result = await self.translate_single(req)
                        return (idx, result)

                retry_tasks = [
                    asyncio.create_task(retry_one(idx)) for idx in unchanged_indices
                ]
                retry_results = await asyncio.gather(
                    *retry_tasks, return_exceptions=True
                )

                retry_success = 0
                for item in retry_results:
                    if isinstance(item, Exception):
                        continue
                    idx, new_result = item
                    if (
                        new_result.success
                        and new_result.translated_text.strip()
                        != requests[idx].text.strip()
                    ):
                        final_results[idx] = new_result
                        retry_success += 1

                if retry_success > 0:
                    self.logger.info(
                        f"Batch retry success: {retry_success}/{len(unchanged_indices)} translations recovered"
                    )

        return final_results

    # Separator for batch translation
    # Using a unique pattern that translation engines are unlikely to modify
    # Numbers and specific pattern make it very unlikely to be translated
    BATCH_SEPARATOR = "\n|||RNLSEP999|||\n"

    # Alternative separators to try if first fails
    BATCH_SEPARATORS = [
        "\n|||RNLSEP999|||\n",
        "\n[[[SEP777]]]\n",
        "\n###TXTSEP###\n",
    ]

    async def _multi_q(
        self, batch: List[TranslationRequest]
    ) -> List[TranslationResult]:
        """Batch translation - tries separator method first, falls back to parallel individual.

        For better performance, uses parallel individual translation when batch method fails.
        """
        if not batch:
            return []
        if len(batch) == 1:
            return [await self.translate_single(batch[0])]

        total_chars = sum(len(r.text) for r in batch)

        # Separator method dene (daha büyük batch'ler için de)
        # Limit artırıldı: 50 metin, 8000 karakter
        if len(batch) <= 50 and total_chars <= 8000:
            result = await self._try_batch_separator(batch)
            if result:
                # ── Batch integrity-fail recovery ──
                # Batch separator'da token kaybı yaşayan satırları translate_single
                # ile tekrar dene (multi-endpoint + Lingva retry pipeline'ı var).
                failed_indices = [
                    i for i, r in enumerate(result) if r.confidence == 0.0 and r.success
                ]
                if failed_indices and len(failed_indices) <= 30:
                    self.logger.info(
                        f"Batch-sep: {len(failed_indices)} integrity failures, retrying individually..."
                    )
                    for idx in failed_indices:
                        try:
                            retry = await self.translate_single(batch[idx])
                            if retry.success and retry.confidence > 0.0:
                                result[idx] = retry
                        except Exception:
                            pass  # Keep original reverted text
                    recovered = sum(
                        1 for idx in failed_indices if result[idx].confidence > 0.0
                    )
                    if recovered:
                        self.logger.info(
                            f"Batch-sep recovery: {recovered}/{len(failed_indices)} texts rescued via individual translation"
                        )
                return result
            self.logger.debug(
                f"Batch separator failed for {len(batch)} texts ({total_chars} chars), falling back to parallel"
            )

        # Separator başarısız veya batch çok büyük - paralel çeviri
        self.logger.debug(f"Using parallel translation for {len(batch)} texts")
        return await self._translate_parallel(batch)

    async def _try_batch_separator(
        self, batch: List[TranslationRequest]
    ) -> Optional[List[TranslationResult]]:
        """Try batch translation with separator. Returns None if fails."""

        protected_texts = []
        all_placeholders = []  # Her metin için placeholder sözlüğü

        html_flags = []

        for req in batch:
            protected, placeholders, req_use_html = self._prepare_request_protection(
                req
            )
            html_flags.append(req_use_html)

            protected_texts.append(protected)
            all_placeholders.append(placeholders)

        use_html = bool(html_flags) and all(html_flags)

        combined_text = self.BATCH_SEPARATOR.join(protected_texts)

        params = {
            "client": "gtx",
            "sl": batch[0].source_lang,
            "tl": batch[0].target_lang,
            "dt": "t",
            "q": combined_text,
        }
        if use_html:
            params["format"] = "html"
        query = urllib.parse.urlencode(params)

        async def try_endpoint(endpoint: str) -> Optional[List[str]]:
            """Try a single endpoint with retries, return list of translations or None."""
            # Circuit breaker active — probe-gated like the single path.
            entered_as_probe = False
            if self._consecutive_429_count >= RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD:
                now = time.time()
                if now < self._primary_probe_at:
                    return None
                self._primary_probe_at = (
                    now + RATE_LIMIT_PRIMARY_PROBE_INTERVAL
                )
                entered_as_probe = True
            max_attempts = 2  # Fewer retries than translate_single (batch is heavier)
            for attempt in range(1, max_attempts + 1):
                # Breaker tripped mid-flight by another worker — bail early.
                if (
                    self._consecutive_429_count
                    >= RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD
                    and not entered_as_probe
                ):
                    return None
                await self._wait_out_global_cooldown()
                try:
                    url = f"{endpoint}?{query}"
                    session = await self._get_session()

                    proxy = None
                    proxy_url_used = None
                    if self.use_proxy and self.proxy_manager:
                        p = self.proxy_manager.get_next_proxy()
                        if p:
                            proxy = p.url
                            proxy_url_used = proxy

                    async with session.get(
                        url,
                        proxy=proxy,
                        timeout=aiohttp.ClientTimeout(total=15),
                        headers=GOOGLE_BROWSER_HEADERS,
                    ) as resp:
                        if resp.status == 429:
                            # 429 = IP-level rate limit — apply global cooldown
                            global_wait = self._apply_global_cooldown()
                            if endpoint in self._endpoint_health:
                                self._endpoint_health[endpoint]["fails"] += 1
                                if (
                                    self._endpoint_health[endpoint]["fails"]
                                    >= self.MIRROR_MAX_FAILURES
                                ):
                                    self._endpoint_health[endpoint]["banned_until"] = (
                                        time.time() + self.MIRROR_BAN_TIME
                                    )
                                    self.logger.warning(
                                        f"Google Mirror BANNED temporarily (2min): {endpoint}"
                                    )
                            if proxy_url_used and self.proxy_manager:
                                self.proxy_manager.mark_proxy_failed(proxy_url_used)
                            self.logger.warning(
                                f"Batch-sep 429 on {endpoint}. Global cooldown {global_wait:.0f}s"
                            )
                            await asyncio.sleep(
                                min(global_wait, 25.0) + random.uniform(0.5, 1.0)
                            )
                            continue  # Retry after cooldown

                        if resp.status != 200:
                            if endpoint in self._endpoint_health:
                                self._endpoint_health[endpoint]["fails"] += 1
                                if (
                                    self._endpoint_health[endpoint]["fails"]
                                    >= self.MIRROR_MAX_FAILURES
                                ):
                                    self._endpoint_health[endpoint]["banned_until"] = (
                                        time.time() + self.MIRROR_BAN_TIME
                                    )
                                    self.logger.warning(
                                        f"Google Mirror BANNED temporarily (2min): {endpoint}"
                                    )
                            if proxy_url_used and self.proxy_manager:
                                self.proxy_manager.mark_proxy_failed(proxy_url_used)
                            self.logger.debug(
                                f"Batch-sep {endpoint}: HTTP {resp.status}"
                            )
                            return None  # Non-retryable HTTP error

                        data = await resp.json(content_type=None)
                        segs = data[0] if isinstance(data, list) and data else None
                        if not segs:
                            self.logger.debug(
                                f"Batch-sep {endpoint}: No segments in response"
                            )
                            # Empty 200 = soft ban signal, count as fail
                            if endpoint in self._endpoint_health:
                                self._endpoint_health[endpoint]["fails"] += 1
                            if proxy_url_used and self.proxy_manager:
                                self.proxy_manager.mark_proxy_failed(proxy_url_used)
                            continue  # Retry

                        # Combine all translation segments
                        full_translation = ""
                        for seg in segs:
                            if seg and seg[0]:
                                full_translation += seg[0]

                        # Split by separator
                        parts = full_translation.split(self.BATCH_SEPARATOR)

                        # Verify count matches
                        if len(parts) != len(batch):
                            self.logger.debug(
                                f"Batch-sep {endpoint}: Part count mismatch - expected {len(batch)}, got {len(parts)}"
                            )
                            return None  # Structural mismatch, don't retry

                        # Validate individual parts for separator bleeding
                        # (adjacent translations merging when separator is absorbed)
                        for pidx, (part, req) in enumerate(zip(parts, batch)):
                            orig_len = len(req.text)
                            part_len = len(part.strip())
                            # If translated part is >3x longer than original,
                            # it likely contains text from adjacent entries
                            if orig_len > 0 and part_len > max(
                                orig_len * 3, orig_len + 50
                            ):
                                self.logger.debug(
                                    f"Batch-sep {endpoint}: Part {pidx} suspiciously long ({part_len} vs {orig_len} orig) - possible separator bleeding"
                                )
                                return None
                            # Check for separator remnants in the translated part
                            if (
                                "|||" in part
                                or "RNLSEP" in part
                                or "SEP777" in part
                                or "TXTSEP" in part
                            ):
                                self.logger.debug(
                                    f"Batch-sep {endpoint}: Separator remnant found in part {pidx}"
                                )
                                return None

                        # Success - reset endpoint failures and 429 counter
                        if endpoint in self._endpoint_health:
                            self._endpoint_health[endpoint]["fails"] = 0
                        self._consecutive_429_count = max(
                            0, self._consecutive_429_count - 1
                        )
                        # Report proxy success
                        if proxy_url_used and self.proxy_manager:
                            self.proxy_manager.mark_proxy_success(proxy_url_used)
                        return parts

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    if endpoint in self._endpoint_health:
                        self._endpoint_health[endpoint]["fails"] += 1
                        if (
                            self._endpoint_health[endpoint]["fails"]
                            >= self.MIRROR_MAX_FAILURES
                        ):
                            self._endpoint_health[endpoint]["banned_until"] = (
                                time.time() + self.MIRROR_BAN_TIME
                            )
                            self.logger.warning(
                                f"Google Mirror BANNED temporarily (2min): {endpoint} ({str(e)[:50]})"
                            )
                    if proxy_url_used and self.proxy_manager:
                        self.proxy_manager.mark_proxy_failed(proxy_url_used)
                    self.logger.debug(
                        f"Batch-sep failed on {endpoint} (attempt {attempt}): {e}"
                    )
                    # Backoff before retry
                    if attempt < max_attempts:
                        await asyncio.sleep(1.0 * attempt)

            return None  # All attempts exhausted

        # Parallel endpoint racing (if enabled) — reduced to 1 to prevent cascade bans
        if self.use_multi_endpoint:
            endpoints_to_try = [await self._get_next_endpoint()]
            tasks = [asyncio.create_task(try_endpoint(ep)) for ep in endpoints_to_try]

            try:
                # Wait for first successful result
                for coro in asyncio.as_completed(tasks):
                    try:
                        result = await coro
                        if result:
                            # Cancel remaining tasks
                            for t in tasks:
                                if not t.done():
                                    t.cancel()
                            self.logger.debug(
                                f"Batch-sep success: {len(batch)} texts translated"
                            )

                            # Restore placeholders and validate integrity
                            final_results = []
                            for i, (req, translated) in enumerate(zip(batch, result)):
                                # Restore logic
                                translated_clean = (
                                    translated if translated is not None else ""
                                )
                                if use_html:
                                    restored = restore_renpy_syntax_html(
                                        translated_clean.strip()
                                    )
                                    missing = []
                                else:
                                    placeholders = all_placeholders[i]
                                    restored = restore_renpy_syntax(
                                        translated_clean.strip(), placeholders
                                    )
                                    missing = validate_translation_integrity(
                                        restored, placeholders
                                    )

                                # Truncation check - çeviri orijinalin %30'undan kısa mı?
                                # Bu, Google'ın metni kestiğini gösterir
                                original_len = len(req.text)
                                restored_len = len(restored)
                                is_truncated = original_len > 20 and restored_len < (
                                    original_len * 0.3
                                )

                                # Inflation check - çeviri orijinalden çok mu uzun?
                                # Bu, separator bleeding'i gösterir (komşu çeviriler birleşmiş)
                                is_inflated = original_len > 0 and restored_len > max(
                                    original_len * 3, original_len + 50
                                )

                                # Integrity check (HTML modunda missing zaten boş)

                                if missing or is_truncated or is_inflated:
                                    # Placeholder kayıp veya metin kesilmiş/şişmiş
                                    reason = (
                                        "truncated"
                                        if is_truncated
                                        else (
                                            "inflated" if is_inflated else "integrity"
                                        )
                                    )
                                    _meta = (
                                        req.metadata
                                        if isinstance(req.metadata, dict)
                                        else {}
                                    )
                                    _orig = _meta.get("original_text", req.text)

                                    if missing and not is_truncated and not is_inflated:
                                        # v3.5: Token tamamen silinmişse enjeksiyon dene
                                        injected = inject_missing_placeholders(
                                            restored, req.text, placeholders, missing
                                        )
                                        still_missing = validate_translation_integrity(
                                            injected, placeholders
                                        )
                                        restored_strip = (
                                            restored.strip() if restored else ""
                                        )
                                        orig_strip = _orig.strip() if _orig else ""
                                        if not still_missing or (
                                            restored_strip
                                            and restored_strip != orig_strip
                                        ):
                                            self.logger.info(
                                                f"Batch injection rescued: {_orig[:40]}..."
                                            )
                                            restored = injected
                                        else:
                                            self.logger.warning(
                                                f"Batch integrity fail, reverting: {_orig[:40]}..."
                                            )
                                            restored = _orig
                                    else:
                                        self.logger.warning(
                                            f"Batch {reason} fail, reverting: {_orig[:40]}..."
                                        )
                                        restored = _orig  # Fallback to ORIGINAL (unprotected) text

                                _meta = (
                                    req.metadata
                                    if isinstance(req.metadata, dict)
                                    else {}
                                )
                                final_results.append(
                                    TranslationResult(
                                        original_text=_meta.get(
                                            "original_text", req.text
                                        ),
                                        translated_text=restored,
                                        source_lang=req.source_lang,
                                        target_lang=req.target_lang,
                                        engine=TranslationEngine.GOOGLE,
                                        success=True,
                                        confidence=0.9
                                        if not (missing or is_truncated or is_inflated)
                                        else 0.0,
                                        metadata=req.metadata,
                                    )
                                )
                            return final_results
                    except asyncio.CancelledError:
                        raise
                # Avoid spamming user console; keep detailed info in debug logs only
                self.logger.debug(
                    f"Batch-sep: All Google endpoints failed for {len(batch)} texts"
                )
            except asyncio.CancelledError:
                # Cancel all tasks on cancellation
                for t in tasks:
                    if not t.done():
                        t.cancel()
                raise
        else:
            # Single endpoint mode (sequential)
            for _ in range(3):
                result = await try_endpoint(await self._get_next_endpoint())
                if result:
                    # Restore placeholders and validate integrity (same as multi-endpoint)
                    final_results = []
                    for i, (req, translated) in enumerate(zip(batch, result)):
                        if use_html:
                            restored = restore_renpy_syntax_html(translated.strip())
                            missing = []
                        else:
                            placeholders = all_placeholders[i]
                            restored = restore_renpy_syntax(
                                translated.strip(), placeholders
                            )
                            missing = validate_translation_integrity(
                                restored, placeholders
                            )

                        # Truncation check
                        original_len = len(req.text)
                        restored_len = len(restored)
                        is_truncated = original_len > 20 and restored_len < (
                            original_len * 0.3
                        )

                        # Inflation check (separator bleeding)
                        is_inflated = original_len > 0 and restored_len > max(
                            original_len * 3, original_len + 50
                        )

                        # missing check (empty in HTML mode)
                        if missing or is_truncated or is_inflated:
                            reason = (
                                "truncated"
                                if is_truncated
                                else ("inflated" if is_inflated else "integrity")
                            )
                            _meta = (
                                req.metadata if isinstance(req.metadata, dict) else {}
                            )
                            _orig = _meta.get("original_text", req.text)

                            if missing and not is_truncated and not is_inflated:
                                # v3.5: Token tamamen silinmişse enjeksiyon dene
                                injected = inject_missing_placeholders(
                                    restored, req.text, placeholders, missing
                                )
                                still_missing = validate_translation_integrity(
                                    injected, placeholders
                                )
                                if not still_missing or (
                                    restored.strip()
                                    and restored.strip() != _orig.strip()
                                ):
                                    self.logger.info(
                                        f"Batch injection rescued (single-ep): {_orig[:40]}..."
                                    )
                                    restored = injected
                                else:
                                    self.logger.warning(
                                        f"Batch {reason} fail, reverting: {_orig[:40]}..."
                                    )
                                    restored = _orig
                            else:
                                self.logger.warning(
                                    f"Batch {reason} fail, reverting: {_orig[:40]}..."
                                )
                                restored = (
                                    _orig  # Fallback to ORIGINAL (unprotected) text
                                )
                        _meta = req.metadata if isinstance(req.metadata, dict) else {}
                        final_results.append(
                            TranslationResult(
                                original_text=_meta.get("original_text", req.text),
                                translated_text=restored,
                                source_lang=req.source_lang,
                                target_lang=req.target_lang,
                                engine=TranslationEngine.GOOGLE,
                                success=True,
                                confidence=0.9
                                if not (missing or is_truncated or is_inflated)
                                else 0.0,
                                metadata=req.metadata,
                            )
                        )
                    return final_results

        # Batch separator failed
        return None

    async def _translate_parallel(
        self, batch: List[TranslationRequest]
    ) -> List[TranslationResult]:
        """Translate texts in parallel using multiple endpoints for speed."""
        if not batch:
            return []

        # Cap concurrency to avoid instant bans on free endpoints
        effective_concurrency = min(self.multi_q_concurrency, 8)
        sem = asyncio.Semaphore(effective_concurrency)
        delay = getattr(self, "_google_request_delay", 0.1)

        async def translate_one(req: TranslationRequest) -> TranslationResult:
            async with sem:
                # Rate limiting between parallel requests to avoid Google bans
                if delay > 0:
                    await asyncio.sleep(delay * random.uniform(0.5, 1.5))
                return await self.translate_single(req)

        # Tüm çevirileri paralel başlat
        tasks = [asyncio.create_task(translate_one(req)) for req in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Sonuçları işle
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.debug(
                    f"Parallel translation failed for text {i + 1}: {result}"
                )
                final_results.append(
                    TranslationResult(
                        batch[i].text,
                        "",
                        batch[i].source_lang,
                        batch[i].target_lang,
                        TranslationEngine.GOOGLE,
                        False,
                        str(result),
                    )
                )
            else:
                final_results.append(result)

        success_count = sum(1 for r in final_results if r.success)
        self.logger.debug(
            f"Parallel translation: {success_count}/{len(batch)} successful"
        )

        return final_results

    async def _translate_individually(
        self, batch: List[TranslationRequest]
    ) -> List[TranslationResult]:
        """Translate texts one by one as fallback."""
        results = []
        for i, req in enumerate(batch):
            try:
                result = await self.translate_single(req)
                results.append(result)
                # Rate limiting - respect configured delay with jitter
                if i < len(batch) - 1:
                    delay = getattr(self, "_google_request_delay", 0.15)
                    await asyncio.sleep(delay * random.uniform(0.8, 1.5))
            except Exception as e:
                self.logger.debug(
                    f"Individual translation failed for text {i + 1}: {e}"
                )
                results.append(
                    TranslationResult(
                        req.text,
                        "",
                        req.source_lang,
                        req.target_lang,
                        TranslationEngine.GOOGLE,
                        False,
                        str(e),
                    )
                )

            # Log progress every 10 texts
            if (i + 1) % 10 == 0:
                self.logger.debug(
                    f"Individual translation progress: {i + 1}/{len(batch)}"
                )

        return results

    def get_supported_languages(self) -> Dict[str, str]:
        return {"auto": "Auto", "en": "English", "tr": "Turkish"}


class PseudoTranslator(BaseTranslator):
    """
    Pseudo-Localization Engine for testing UI bounds and font compatibility.

    This translator doesn't call any API - it transforms text locally to help:
    1. Test UI text overflow (adds expansion markers)
    2. Test font compatibility (uses accented characters)
    3. Identify untranslated strings (wrapped markers are visible)

    Modes:
    - 'expand': Adds [!!! ... !!!] markers for length testing
    - 'accent': Replaces vowels with accented versions
    - 'both': Combines expansion and accenting (default)
    """

    # Vowel accent mapping for pseudo-localization
    ACCENT_MAP = str.maketrans("aeiouAEIOUyY", "àéîõüÀÉÎÕÜýÝ")

    # Extended accent map for more thorough testing
    EXTENDED_ACCENT_MAP = str.maketrans(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "àḃċḋéḟġḣíjḳĺṁńöṗqŕśṫûṿẁẍÿźÀḂĊḊÉḞĠḢÍJḲĹṀŃÖṖQŔŚṪÛṾẀẌŸŹ",
    )

    def __init__(self, *args, mode: str = "both", **kwargs):
        super().__init__(*args, **kwargs)
        self.mode = mode  # 'expand', 'accent', or 'both'

    def _apply_accents(self, text: str) -> str:
        """Replace ASCII letters with accented versions."""
        return text.translate(self.ACCENT_MAP)

    def _apply_expansion(self, text: str) -> str:
        """Add expansion markers to test UI bounds."""
        # ~30% expansion typical for EN->DE/FR, simulate this
        return f"[!!! {text} !!!]"

    def _pseudo_transform(self, text: str) -> str:
        """
        Transform text based on mode:
        - expand: [!!! text !!!]
        - accent: tëxt wïth àccénts
        - both: [!!! tëxt wïth àccénts !!!]
        """
        if not text or not text.strip():
            return text

        result = text

        if self.mode in ("accent", "both"):
            result = self._apply_accents(result)

        if self.mode in ("expand", "both"):
            result = self._apply_expansion(result)

        return result

    async def translate_single(self, request: TranslationRequest) -> TranslationResult:
        """Pseudo-translate a single text (no API call)."""
        # Protect Ren'Py syntax before transformation
        protected_text, placeholders = protect_renpy_syntax(request.text)

        # Split by placeholders (both Ren'Py and Glossary ones)
        # Pattern matches XRPYX...XRPYX
        # Pattern matches XRPYX...XRPYX OR New Tokens (VAR0, TAG1, ESC_OPEN, etc.) inside spans or naked
        # We need to capture the delimiter to keep it
        parts = re.split(
            r"((?:<span[^>]*>)?(?:XRPYX[A-Z0-9]+XRPYX|VAR\d+|TAG\d+|ESC_[A-Z]+|PCT\d+|DIS\d+)(?:</span>)?)",
            protected_text,
        )
        new_parts = []
        for part in parts:
            if not part:
                continue

            # Check if it's a placeholder (Token or XRPYX)
            is_placeholder = False
            if "XRPYX" in part:
                is_placeholder = True
            elif (
                "VAR" in part
                or "TAG" in part
                or "ESC_" in part
                or "PCT" in part
                or "DIS" in part
            ):
                # Simple check, robust enough for this context
                is_placeholder = True

            if is_placeholder:
                # It's a placeholder, keep it as is
                new_parts.append(part)
            else:
                # Translatable text, apply pseudo-transformation
                new_parts.append(self._pseudo_transform(part))

        pseudo_text = "".join(new_parts)

        # Restore Ren'Py syntax
        final_text = restore_renpy_syntax(pseudo_text, placeholders)

        return TranslationResult(
            original_text=request.text,
            translated_text=final_text,
            source_lang=request.source_lang,
            target_lang=request.target_lang,
            engine=TranslationEngine.PSEUDO,
            success=True,
            confidence=1.0,  # Always succeeds
            metadata={**request.metadata, "pseudo_mode": self.mode},
        )

    async def translate_batch(
        self, requests: List[TranslationRequest]
    ) -> List[TranslationResult]:
        """Pseudo-translate a batch (all local, very fast)."""
        return [await self.translate_single(r) for r in requests]

    def get_supported_languages(self) -> Dict[str, str]:
        """Pseudo-localization works for any language."""
        return {
            "pseudo": "Pseudo-Localization (Test)",
            "expand": "Expansion Test [!!! !!!]",
            "accent": "Accent Test (àccénts)",
        }


class DeepLTranslator(BaseTranslator):
    base_url_paid = "https://api.deepl.com/v2/translate"
    base_url_free = "https://api-free.deepl.com/v2/translate"

    def _map_lang(self, lang: str, is_target: bool = True) -> str:
        """Map generic language codes to DeepL specific codes."""
        if not lang:
            return "EN"
        l = lang.lower()

        # DeepL specific target mappings
        if is_target:
            if l == "en":
                return "EN-US"
            if l == "pt":
                return "PT-PT"
            if l == "zh-cn":
                return "ZH"
            if l == "zh-tw":
                return "ZH"

        # Source mappings
        if l == "en":
            return "EN"
        if l == "ja":
            return "JA"
        if l == "ko":
            return "KO"
        if l == "zh-cn" or l == "zh-tw":
            return "ZH"

        return l.upper()

    async def translate_single(self, request: TranslationRequest) -> TranslationResult:
        if not self.api_key:
            return TranslationResult(
                request.text,
                "",
                request.source_lang,
                request.target_lang,
                TranslationEngine.DEEPL,
                False,
                self._get_text("error_deepl_key_required", "DeepL API key required"),
            )

        batch_res = await self.translate_batch([request])
        return batch_res[0]

    # DeepL retry settings
    MAX_RETRIES = 3
    RETRY_DELAYS = [1.0, 2.0, 4.0]  # Exponential backoff delays in seconds

    # DeepL formality options
    FORMALITY_OPTIONS = {
        "default": None,  # DeepL decides
        "formal": "more",  # More formal (Sie in DE, Usted in ES, etc.)
        "informal": "less",  # Less formal (Du in DE, tú in ES, etc.)
    }

    async def translate_batch(
        self, requests: List[TranslationRequest]
    ) -> List[TranslationResult]:
        if not requests:
            return []
        if not self.api_key:
            return [
                TranslationResult(
                    r.text,
                    "",
                    r.source_lang,
                    r.target_lang,
                    TranslationEngine.DEEPL,
                    False,
                    self._get_text(
                        "error_deepl_key_required", "DeepL API key required"
                    ),
                )
                for r in requests
            ]

        source_lang = (
            self._map_lang(requests[0].source_lang, False)
            if requests[0].source_lang and requests[0].source_lang != "auto"
            else None
        )
        target_lang = self._map_lang(requests[0].target_lang, True)

        # DeepL XML tag handling is much more robust for placeholders
        # Replace XRPYX style placeholders with XML tags
        xml_protected_texts = []
        all_placeholders = []

        for r in requests:
            # ── Preprotected guard: pipeline may have already applied protect_renpy_syntax ──
            meta = r.metadata if isinstance(r.metadata, dict) else {}
            source_text = (
                meta.get("original_text", r.text)
                if meta.get("preprotected")
                else r.text
            )
            p_text, p_holders = protect_renpy_syntax(source_text)
            # Map XRPYX to <x id="N"/> tags
            # We must be careful not to break the mapping
            temp_text = p_text
            for i, (ph, orig) in enumerate(p_holders.items()):
                # Use a very short tag to save characters/quota
                xml_tag = f'<x i="{i}"/>'
                temp_text = temp_text.replace(ph, xml_tag)

            xml_protected_texts.append(temp_text)
            all_placeholders.append(p_holders)

        # Move auth_key to Header as per new DeepL requirements
        headers = {
            "Authorization": f"DeepL-Auth-Key {self.api_key}",
            "User-Agent": f"RenLocalizer/{_APP_VERSION}",
        }

        data = {
            "target_lang": target_lang,
            "text": xml_protected_texts,
            "tag_handling": "xml",
            "ignore_tags": "x",  # Tell DeepL to ignore our 'x' tag
        }
        if source_lang:
            data["source_lang"] = source_lang

        # Add formality if configured and supported by target language
        # DeepL formality supported targets: DE, FR, IT, ES, NL, PL, PT-BR, PT-PT, RU, JA, TR
        formality_languages = {
            "de",
            "fr",
            "it",
            "es",
            "nl",
            "pl",
            "pt",
            "ru",
            "ja",
            "tr",
        }
        # v2.7.1: config_manager.translation_settings.deepl_formality erişimi
        if self.config_manager:
            ts = getattr(self.config_manager, "translation_settings", None)
            formality_setting = (
                getattr(ts, "deepl_formality", "default") if ts else "default"
            )
        else:
            formality_setting = "default"
        formality_value = self.FORMALITY_OPTIONS.get(formality_setting)
        if formality_value and target_lang.lower()[:2] in formality_languages:
            data["formality"] = formality_value

        base_url = (
            self.base_url_free
            if ":fx" in self.api_key or self.api_key.startswith("free:")
            else self.base_url_paid
        )

        # Retry loop with exponential backoff
        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                session = await self._get_session()
                proxy = None
                if self.use_proxy and self.proxy_manager:
                    p = self.proxy_manager.get_next_proxy()
                    if p:
                        proxy = p.url

                async with session.post(
                    base_url,
                    data=data,
                    headers=headers,
                    proxy=proxy,
                    timeout=aiohttp.ClientTimeout(total=45),
                ) as resp:
                    if resp.status != 200:
                        try:
                            err_data = await resp.json()
                            msg = err_data.get("message", f"HTTP {resp.status}")
                            if resp.status == 456:
                                msg = "Quota Exceeded"
                                is_quota = True
                            else:
                                is_quota = False
                        except Exception:
                            msg = await resp.text()
                            is_quota = False

                        last_error = f"HTTP {resp.status}: {msg[:100]}"
                        if is_quota:
                            # Quota exhausted — no point retrying, return immediately
                            qe = QuotaExceededError(f"DeepL API quota aşıldı (HTTP 456)", code=456)
                            self.emit_log("error", qe.get_user_friendly_message())
                            return [
                                TranslationResult(
                                    r.text,
                                    "",
                                    r.source_lang,
                                    r.target_lang,
                                    TranslationEngine.DEEPL,
                                    False,
                                    f"DeepL Error: {last_error}",
                                    quota_exceeded=True,
                                )
                                for r in requests
                            ]
                        if attempt < self.MAX_RETRIES - 1:
                            await asyncio.sleep(self.RETRY_DELAYS[attempt])
                            continue
                        return [
                            TranslationResult(
                                r.text,
                                "",
                                r.source_lang,
                                r.target_lang,
                                TranslationEngine.DEEPL,
                                False,
                                f"DeepL Error: {last_error}",
                                quota_exceeded=is_quota,
                            )
                            for r in requests
                        ]

                    payload = await resp.json(content_type=None)

                translations = payload.get("translations", [])

                results = []
                for i, r in enumerate(requests):
                    if i < len(translations):
                        translated = translations[i].get("text", "")
                        # Map XML tags back to XRPYX placeholders
                        final_v = translated
                        for j, (ph, orig) in enumerate(all_placeholders[i].items()):
                            xml_tag = f'<x i="{j}"/>'
                            # Also handle cases where DeepL might add spaces: <x i = "0" />
                            final_v = final_v.replace(xml_tag, ph)
                            if ph not in final_v:
                                # Regex fallback for corrupted tags
                                pattern = re.compile(
                                    rf'<x\s+i\s*=\s*"{j}"\s*/>', re.IGNORECASE
                                )
                                final_v = pattern.sub(ph, final_v)

                        # Apply standard restoration
                        final_text = restore_renpy_syntax(final_v, all_placeholders[i])

                        # --- DeepL Space Cleanup for Ren'Py Tags ---
                        # Fix common cases where DeepL adds spaces inside Ren'Py tags:
                        # { i } -> {i}, { b } -> {b}, { /i } -> {/i}, etc.
                        # This regex finds { tag } patterns and removes internal spaces
                        renpy_tag_cleanup = [
                            # {/i}, {/b} etc with slash — must come BEFORE the no-slash pattern
                            # to prevent {/i} being matched by the /? pattern and losing the slash
                            (
                                r"\{\s*/\s*(i|b|u|s|plain|fast|nw|p|w|cps|color|font|size|alpha|outlinecolor|k|rb|rt)\s*\}",
                                lambda m: "{/" + m.group(1).strip() + "}",
                            ),
                            # {i}, {b}, {u}, {s}, {plain}, {fast} etc without slash
                            (
                                r"\{\s*(i|b|u|s|plain|fast|nw|p|w|cps|color|font|size|alpha|outlinecolor|k|rb|rt)\s*\}",
                                lambda m: "{" + m.group(1).strip() + "}",
                            ),
                            # {color=...}, {size=...}, {font=...} with values
                            (
                                r"\{\s*(color|size|font|alpha|outlinecolor|cps|k)\s*=\s*([^}]+?)\s*\}",
                                lambda m: (
                                    "{"
                                    + m.group(1).strip()
                                    + "="
                                    + m.group(2).strip()
                                    + "}"
                                ),
                            ),
                            # [variable] - remove internal spaces: [ variable ] -> [variable]
                            (
                                r"\[\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\]",
                                lambda m: "[" + m.group(1).strip() + "]",
                            ),
                        ]

                        for pattern, replacement in renpy_tag_cleanup:
                            final_text = re.sub(
                                pattern, replacement, final_text, flags=re.IGNORECASE
                            )

                        # Use original (unprotected) text for TranslationResult
                        meta_i = r.metadata if isinstance(r.metadata, dict) else {}
                        orig_text = meta_i.get("original_text", r.text)
                        results.append(
                            TranslationResult(
                                orig_text,
                                final_text,
                                r.source_lang,
                                r.target_lang,
                                TranslationEngine.DEEPL,
                                True,
                                confidence=0.98,
                            )
                        )
                    else:
                        meta_i = r.metadata if isinstance(r.metadata, dict) else {}
                        orig_text = meta_i.get("original_text", r.text)
                        results.append(
                            TranslationResult(
                                orig_text,
                                "",
                                r.source_lang,
                                r.target_lang,
                                TranslationEngine.DEEPL,
                                False,
                                "Missing translation in response",
                            )
                        )
                return results

            except aiohttp.ClientError as e:
                # Retry on network/timeout errors
                last_error = str(e)
                nc_err = NetworkConnectionError(str(e), context={"engine": "deepl"})
                self.logger.debug(nc_err.get_user_friendly_message())
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(self.RETRY_DELAYS[attempt])
                    continue
            except asyncio.TimeoutError as e:
                last_error = str(e)
                nc_err = NetworkConnectionError(f"Timeout: {e}", context={"engine": "deepl"})
                self.logger.debug(nc_err.get_user_friendly_message())
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(self.RETRY_DELAYS[attempt])
                    continue
            except Exception as e:
                # Retry on network/timeout errors
                last_error = str(e)
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(self.RETRY_DELAYS[attempt])
                    continue

        # All retries exhausted
        msg = last_error or "Unknown error after retries"
        is_quota = "456" in msg or "quota" in msg.lower()
        if is_quota:
            qe = QuotaExceededError("DeepL API quota aşıldı", code=456)
            msg = qe.get_user_friendly_message()
        return [
            TranslationResult(
                r.text,
                "",
                r.source_lang,
                r.target_lang,
                TranslationEngine.DEEPL,
                False,
                f"DeepL Error: {msg}",
                quota_exceeded=is_quota,
            )
            for r in requests
        ]

    def get_supported_languages(self) -> Dict[str, str]:
        return {
            "bg": "Bulgarian",
            "cs": "Czech",
            "da": "Danish",
            "de": "German",
            "el": "Greek",
            "en": "English",
            "es": "Spanish",
            "et": "Estonian",
            "fi": "Finnish",
            "fr": "French",
            "hu": "Hungarian",
            "id": "Indonesian",
            "it": "Italian",
            "ja": "Japanese",
            "ko": "Korean",
            "lt": "Lithuanian",
            "lv": "Latvian",
            "nb": "Norwegian",
            "nl": "Dutch",
            "pl": "Polish",
            "pt": "Portuguese",
            "ro": "Romanian",
            "ru": "Russian",
            "sk": "Slovak",
            "sl": "Slovenian",
            "sv": "Swedish",
            "tr": "Turkish",
            "uk": "Ukrainian",
            "zh": "Chinese",
        }


class LibreTranslateTranslator(BaseTranslator):
    """Local or public LibreTranslate API Translator with failover and rate-limit handling."""

    MAX_RETRIES = 3
    RETRY_DELAYS = [2.0, 4.0, 8.0]

    def __init__(
        self,
        base_url: str = "http://localhost:5000",
        api_key: str = "",
        proxy_manager=None,
        config_manager=None,
    ):
        super().__init__(proxy_manager, config_manager)
        # Protocol Hardening: Ensure URL starts with http:// or https://
        clean_url = base_url.strip().rstrip("/")
        if clean_url and not (
            clean_url.startswith("http://") or clean_url.startswith("https://")
        ):
            clean_url = f"http://{clean_url}"

        self.base_url = clean_url
        self.api_key = api_key
        self.logger = logging.getLogger(__name__)

        # Check if using local offline instance or public API
        self.is_local = "localhost" in self.base_url or "127.0.0.1" in self.base_url

    async def translate_single(self, request: TranslationRequest) -> TranslationResult:
        results = await self.translate_batch([request])
        return (
            results[0]
            if results
            else TranslationResult(
                request.text,
                "",
                request.source_lang,
                request.target_lang,
                TranslationEngine.LIBRETRANSLATE,
                False,
                "Batch failed",
            )
        )

    async def translate_batch(
        self, requests: List[TranslationRequest]
    ) -> List[TranslationResult]:
        if not requests:
            return []

        # LibreTranslate expects `q` as a single string or an array of strings
        # We'll batch them up into one API call
        texts_to_translate = []
        all_placeholders = []

        # Determine languages from the first request (assuming batch is homogeneous)
        # Handle regional codes (zh-CN, pt-BR) more intelligently
        def _get_lang_code(raw: str) -> str:
            raw = raw.lower().strip()
            if raw == "auto":
                return "auto"
            # Return as-is if it contains a hyphen (regional/variant) or is short (ISO 639-1/2/3)
            # Most modern MT engines use codes like 'zh-CN', 'zh-TW', 'pt-BR', 'fil', 'ber'
            if "-" in raw or len(raw) <= 3:
                return raw
            # Fallback for very long non-hyphenated strings
            return raw[:2]

        src_lang = _get_lang_code(requests[0].source_lang)
        tgt_lang = _get_lang_code(requests[0].target_lang)

        for req in requests:
            meta = req.metadata if isinstance(req.metadata, dict) else {}
            preprotected = meta.get("preprotected", False)
            placeholders = meta.get("placeholders")

            if preprotected and isinstance(placeholders, dict):
                protected_text = req.text
            else:
                protected_text, placeholders = protect_renpy_syntax(req.text)

            # Wrap placeholder tokens in <span translate="no"> for HTML mode.
            # LibreTranslate corrupts Unicode brackets ⟦⟧ in plain text mode,
            # but respects translate="no" spans in HTML mode.
            #
            # Escape bare < > & in text BEFORE wrapping spans, so the HTML
            # parser doesn't misinterpret them (e.g. "5 < 10" → "5 &lt; 10").
            # Placeholder tokens (⟦…⟧) don't contain these chars so escaping is safe.
            html_text = (
                protected_text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            for ph in sorted(placeholders.keys(), key=len, reverse=True):
                html_text = html_text.replace(ph, f'<span translate="no">{ph}</span>')

            texts_to_translate.append(html_text)
            all_placeholders.append(placeholders)

        payload = {
            "q": texts_to_translate,
            "source": src_lang,
            "target": tgt_lang,
            "format": "html",
        }
        if self.api_key:
            payload["api_key"] = self.api_key

        url = f"{self.base_url}/translate"
        results = []
        last_error = None

        # Try multiple times to prevent ban/rate-limit interruptions
        import random
        from src.core.constants import USER_AGENTS

        for attempt in range(self.MAX_RETRIES):
            try:
                session = await self._get_session()
                # Do not route local connections through proxies
                proxy = None
                if self.use_proxy and self.proxy_manager and not self.is_local:
                    p = self.proxy_manager.get_next_proxy()
                    if p:
                        proxy = p.url

                headers = {
                    "Content-Type": "application/json",
                    "User-Agent": random.choice(USER_AGENTS)
                    if not self.is_local
                    else "RenLocalizer/2.0",
                }

                async with session.post(
                    url,
                    json=payload,
                    headers=headers,
                    proxy=proxy,
                    timeout=aiohttp.ClientTimeout(total=45),
                ) as resp:
                    if resp.status != 200:
                        try:
                            err_data = await resp.json()
                            msg = err_data.get("error", f"HTTP {resp.status}")
                        except Exception:
                            msg = await resp.text()

                        # 429 Too Many Requests -> Wait and Retry
                        if resp.status == 429:
                            last_error = "Rate Limit Exceeded (429 Too Many Requests)"
                            if attempt < self.MAX_RETRIES - 1:
                                await asyncio.sleep(self.RETRY_DELAYS[attempt])
                                continue
                            else:
                                rl = RateLimitError("LibreTranslate rate limit aşıldı (HTTP 429)", code=429)
                                self.emit_log("error", rl.get_user_friendly_message())
                                return [
                                    TranslationResult(
                                        r.text,
                                        "",
                                        r.source_lang,
                                        r.target_lang,
                                        TranslationEngine.LIBRETRANSLATE,
                                        False,
                                        rl.get_user_friendly_message(),
                                        quota_exceeded=True,
                                    )
                                    for r in requests
                                ]
                        elif resp.status in (403, 401):
                            # Ban or API key issue -> Don't retry
                            return [
                                TranslationResult(
                                    r.text,
                                    "",
                                    r.source_lang,
                                    r.target_lang,
                                    TranslationEngine.LIBRETRANSLATE,
                                    False,
                                    f"API Error: {msg[:100]}",
                                )
                                for r in requests
                            ]
                        else:
                            last_error = f"HTTP {resp.status}: {msg[:100]}"
                            if attempt < self.MAX_RETRIES - 1:
                                await asyncio.sleep(self.RETRY_DELAYS[attempt])
                                continue
                            else:
                                return [
                                    TranslationResult(
                                        r.text,
                                        "",
                                        r.source_lang,
                                        r.target_lang,
                                        TranslationEngine.LIBRETRANSLATE,
                                        False,
                                        f"API Error: {last_error}",
                                    )
                                    for r in requests
                                ]

                    resp_data = await resp.json(content_type=None)

                if "translatedText" in resp_data:
                    translated_list = resp_data["translatedText"]
                    if isinstance(translated_list, str):
                        translated_list = [translated_list]

                    for i, req in enumerate(requests):
                        if i < len(translated_list):
                            translated = translated_list[i]
                            placeholders = all_placeholders[i]
                            meta = (
                                req.metadata if isinstance(req.metadata, dict) else {}
                            )
                            orig_text = meta.get("original_text", req.text)

                            # Strip HTML spans we added for placeholder protection
                            # Handle both quote styles and case variations
                            translated = re.sub(
                                r'<span[^>]*translate=["\']no["\'][^>]*>(.*?)</span>',
                                r"\1",
                                translated,
                                flags=re.IGNORECASE | re.DOTALL,
                            )
                            # Decode HTML entities that the API may have introduced
                            # &amp; MUST be decoded first — otherwise &amp;lt; → &lt; (stuck)
                            translated = (
                                translated.replace("&amp;", "&")
                                .replace("&lt;", "<")
                                .replace("&gt;", ">")
                                .replace("&quot;", '"')
                                .replace("&#39;", "'")
                            )

                            restored = restore_renpy_syntax(
                                translated.strip(), placeholders
                            )
                            missing = validate_translation_integrity(
                                restored, placeholders
                            )

                            if missing:
                                injected = inject_missing_placeholders(
                                    restored, req.text, placeholders, missing
                                )
                                if (
                                    not validate_translation_integrity(
                                        injected, placeholders
                                    )
                                    or restored.strip()
                                ):
                                    restored = injected
                                    missing = False

                            success = not missing
                            confidence = 0.9 if success else 0.0

                            results.append(
                                TranslationResult(
                                    original_text=orig_text,
                                    translated_text=restored,
                                    source_lang=req.source_lang,
                                    target_lang=req.target_lang,
                                    engine=TranslationEngine.LIBRETRANSLATE,
                                    success=success,
                                    confidence=confidence,
                                    metadata=req.metadata,
                                )
                            )
                        else:
                            results.append(
                                TranslationResult(
                                    req.text,
                                    "",
                                    req.source_lang,
                                    req.target_lang,
                                    TranslationEngine.LIBRETRANSLATE,
                                    False,
                                    "Missing translation in response",
                                )
                            )
                else:
                    error_msg = resp_data.get("error", "Unknown API Error")
                    for req in requests:
                        results.append(
                            TranslationResult(
                                req.text,
                                "",
                                req.source_lang,
                                req.target_lang,
                                TranslationEngine.LIBRETRANSLATE,
                                False,
                                f"API Error: {error_msg}",
                            )
                        )
                return results

            except Exception as e:
                # Catch connection errors
                last_error = str(e)
                if isinstance(e, aiohttp.ClientConnectorError):
                    if self.is_local:
                        last_error = self._get_text(
                            "error_libretranslate_local_offline",
                            "Local server is offline. Please start your LibreTranslate instance (or use Cloud).",
                        )
                    else:
                        last_error = (
                            f"Connection Refused: Failed to reach {self.base_url}"
                        )

                if attempt < self.MAX_RETRIES - 1 and not (
                    isinstance(e, aiohttp.ClientConnectorError) and self.is_local
                ):
                    await asyncio.sleep(self.RETRY_DELAYS[attempt])
                    continue
                else:
                    return [
                        TranslationResult(
                            r.text,
                            "",
                            r.source_lang,
                            r.target_lang,
                            TranslationEngine.LIBRETRANSLATE,
                            False,
                            f"Connection/Request Error: {last_error}",
                        )
                        for r in requests
                    ]

        return [
            TranslationResult(
                r.text,
                "",
                r.source_lang,
                r.target_lang,
                TranslationEngine.LIBRETRANSLATE,
                False,
                f"Failed: {last_error}",
            )
            for r in requests
        ]

    def get_supported_languages(self) -> Dict[str, str]:
        # Full list matching LibreTranslate's actual language coverage
        return {
            "en": "English",
            "ar": "Arabic",
            "az": "Azerbaijani",
            "bg": "Bulgarian",
            "bn": "Bengali",
            "ca": "Catalan",
            "cs": "Czech",
            "da": "Danish",
            "de": "German",
            "el": "Greek",
            "eo": "Esperanto",
            "es": "Spanish",
            "et": "Estonian",
            "fa": "Persian",
            "fi": "Finnish",
            "fr": "French",
            "ga": "Irish",
            "he": "Hebrew",
            "hi": "Hindi",
            "hu": "Hungarian",
            "id": "Indonesian",
            "it": "Italian",
            "ja": "Japanese",
            "ko": "Korean",
            "lt": "Lithuanian",
            "lv": "Latvian",
            "ms": "Malay",
            "nb": "Norwegian Bokmål",
            "nl": "Dutch",
            "pl": "Polish",
            "pt": "Portuguese",
            "ro": "Romanian",
            "ru": "Russian",
            "sk": "Slovak",
            "sl": "Slovenian",
            "sq": "Albanian",
            "sr": "Serbian",
            "sv": "Swedish",
            "th": "Thai",
            "tl": "Filipino",
            "tr": "Turkish",
            "uk": "Ukrainian",
            "ur": "Urdu",
            "vi": "Vietnamese",
            "zh": "Chinese",
        }


class TranslationManager:
    def __init__(self, proxy_manager=None, config_manager=None):
        self.proxy_manager = proxy_manager
        self.config_manager = config_manager
        self.logger = logging.getLogger(__name__)
        self.translators: Dict[TranslationEngine, BaseTranslator] = {}
        self.should_stop_callback: Optional[Callable[[], bool]] = None
        self.max_retries = 1
        self.retry_delays = [0.1, 0.2, 0.5, 1.0]
        self.max_batch_size = 500
        self.max_concurrent_requests = 32

        # Sync with config if available
        if self.config_manager:
            ts = self.config_manager.translation_settings
            self.max_retries = getattr(ts, "max_retries", 1)
            self.max_batch_size = getattr(ts, "max_batch_size", 500)
            self.max_concurrent_requests = getattr(ts, "max_concurrent_threads", 32)
            self.use_cache = getattr(ts, "use_cache", True)
        else:
            self.use_cache = True

        self.cache_capacity = 500000  # Increased from 20k to 500k to support large VNs
        self._cache: OrderedDict = OrderedDict()
        self._cache_lock = asyncio.Lock()
        self.cache_hits = 0
        self.cache_misses = 0
        # Adaptive
        self.adaptive_enabled = True
        self.max_concurrency_cap = 512
        self.min_concurrency_floor = 4
        self._recent_metrics = deque(maxlen=500)
        self._adapt_lock = asyncio.Lock()
        self._last_adapt_time = 0.0
        self.adapt_interval_sec = 5.0
        self.ai_request_delay = 1.5  # Default, will be updated by Pipeline

    def add_translator(self, engine: TranslationEngine, translator: BaseTranslator):
        self.translators[engine] = translator

    def remove_translator(self, engine: TranslationEngine):
        self.translators.pop(engine, None)

    def set_proxy_enabled(self, enabled: bool):
        for t in self.translators.values():
            t.set_proxy_enabled(enabled)

    def set_max_concurrency(self, value: int):
        self.max_concurrent_requests = max(1, int(value))

    async def close_all(self):
        tasks = []
        for t in self.translators.values():
            if hasattr(t, "close"):
                tasks.append(t.close())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def close_all_sessions(self):
        """
        Synchronous wrapper to close all translator sessions.
        Called during app shutdown to prevent asyncio cleanup errors.
        """
        try:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self.close_all())
            finally:
                loop.close()
        except Exception as e:
            # Silent fail - we're shutting down anyway
            self.logger.debug(f"Session cleanup warning: {e}")

    async def _cache_get(
        self, key: Tuple[str, str, str, str]
    ) -> Optional[TranslationResult]:
        """
        Cache'den metni getirir. Akıllı eşleştirme (auto-detect ve cross-engine) desteği sağlar.
        """
        if not self.use_cache:
            return None

        engine_val, sl, tl, text = key

        async with self._cache_lock:
            # 1. Tam Eşleşme (Engine + Langs + Text)
            val = self._cache.get(key)
            if val:
                self._cache.move_to_end(key)
                return val

            # 2. Akıllı Dil Eşleşmesi (Kaynak dili 'auto' ise ama cache'de 'en' gibi saklıysa)
            if sl == "auto":
                # 'auto' anahtarı ile bulunamadıysa, aynı motor ve hedef dil için herhangi bir kaynak dildeki çeviriye bak.
                # Not: Büyük cachelerde performans için sadece son 1000 kayda hızlıca bakabiliriz veya kalsın.
                # Genellikle kullanıcılar tek bir kaynak dilden (örn: ingilizce) çeviri yaptığı için pratik bir çözüm:
                # Cache anahtarlarını tararken sadece engine, target_lang ve text uyumuna bakıyoruz.
                for k, v in reversed(self._cache.items()):
                    # k: (engine_str, sl, tl, text)
                    if k[0] == engine_val and k[2] == tl and k[3] == text:
                        return v

            # 3. Motor Bağımsız Ebeveyn Eşleşmesi (Cross-Engine)
            # Eğer Google ile çevrilmiş bir metin varsa ve şu an OpenAI kullanılıyorsa, onu kullan.
            # (Çeviri kalitesi motorlar arasında benzerdir ve kullanıcıyı maliyetten/beklemeden kurtarır)
            for k, v in reversed(self._cache.items()):
                if k[1] == sl and k[2] == tl and k[3] == text:
                    # Motor farklı olsa bile içerik aynı
                    return v

            return None

    async def _cache_put(self, key: Tuple[str, str, str, str], val: TranslationResult):
        if not self.use_cache or not val.success:
            return
        async with self._cache_lock:
            self._cache[key] = val
            self._cache.move_to_end(key)
            if len(self._cache) > self.cache_capacity:
                self._cache.popitem(last=False)

    def _build_cache_hit_projection(
        self,
        req: TranslationRequest,
        cached: TranslationResult,
        *,
        include_request_metadata: bool,
    ) -> TranslationResult:
        """Project a cached translation into the active request context."""
        request_metadata = req.metadata if isinstance(req.metadata, dict) else {}
        cached_metadata = cached.metadata if isinstance(cached.metadata, dict) else {}
        projected_metadata: Dict = dict(cached_metadata)
        if include_request_metadata:
            projected_metadata.update(request_metadata)

        requested_original_text = request_metadata.get("original_text", req.text)
        cache_hit_type = "exact"
        if cached.engine != req.engine:
            cache_hit_type = "cross_engine"
            projected_metadata["cache_source_engine"] = cached.engine.value
        if cached.source_lang != req.source_lang:
            if cache_hit_type == "exact":
                cache_hit_type = "source_lang_fallback"
            projected_metadata["cache_source_lang"] = cached.source_lang

        projected_metadata["cache_hit_type"] = cache_hit_type

        return TranslationResult(
            original_text=requested_original_text,
            translated_text=cached.translated_text,
            source_lang=req.source_lang,
            target_lang=req.target_lang,
            engine=req.engine,
            success=cached.success,
            error=cached.error,
            confidence=cached.confidence,
            quota_exceeded=cached.quota_exceeded,
            metadata=projected_metadata,
            text_type=cached.text_type,
        )

    def _should_materialize_cache_alias(
        self,
        key: Tuple[str, str, str, str],
        cached: TranslationResult,
    ) -> bool:
        """Persist an alias when cache lookup used a fallback dimension."""
        return key[0] != cached.engine.value or key[1] != cached.source_lang

    async def translate_with_retry(self, req: TranslationRequest) -> TranslationResult:
        # ── Normalize cache key to original (unprotected) text ──
        meta = req.metadata if isinstance(req.metadata, dict) else {}
        cache_text = meta.get("original_text", req.text)
        key = (req.engine.value, req.source_lang, req.target_lang, cache_text)
        cached = await self._cache_get(key)
        if cached:
            self.cache_hits += 1
            projected = self._build_cache_hit_projection(
                req, cached, include_request_metadata=True
            )
            if self._should_materialize_cache_alias(key, cached):
                alias_result = self._build_cache_hit_projection(
                    req, cached, include_request_metadata=False
                )
                await self._cache_put(key, alias_result)
            return projected
        tr = self.translators.get(req.engine)
        if not tr:
            return TranslationResult(
                req.text,
                "",
                req.source_lang,
                req.target_lang,
                req.engine,
                False,
                f"Translator {req.engine.value} not available",
            )
        self.cache_misses += 1
        last_err = None
        start = time.time()
        for attempt in range(self.max_retries + 1):
            try:
                res = await tr.translate_single(req)
                self.logger.debug(
                    "translate_single returned: success=%s, text='%s', error=%s",
                    res.success,
                    (res.translated_text[:50] if res.translated_text else "EMPTY"),
                    res.error,
                )
                if res.success:
                    await self._cache_put(key, res)
                    self.logger.debug("Added to cache: %s...", cache_text[:30])
                    await self._record_metric(time.time() - start, True)
                    return res
                last_err = res.error
            except Exception as e:
                self.logger.debug("translate_single EXCEPTION: %s", e)
                last_err = str(e)
            if attempt < self.max_retries:
                await asyncio.sleep(
                    self.retry_delays[min(attempt, len(self.retry_delays) - 1)]
                )
        await self._record_metric(time.time() - start, False)
        return TranslationResult(
            req.text,
            "",
            req.source_lang,
            req.target_lang,
            req.engine,
            False,
            f"Failed: {last_err}",
        )

    async def translate_batch(
        self, requests: List[TranslationRequest]
    ) -> List[TranslationResult]:
        if not requests:
            return []

        # 1. Merkezi Deduplikasyon ve Cache Kontrolü
        indexed = list(enumerate(requests))
        final_results: List[Optional[TranslationResult]] = [None] * len(requests)

        # Benzersiz metinleri topla
        unique_req_map: Dict[
            Tuple[str, str, str, str], List[int]
        ] = {}  # (engine, src, tgt, text) -> [original_indices]
        for idx, req in indexed:
            # ── Normalize dedup key to original (unprotected) text ──
            meta = req.metadata if isinstance(req.metadata, dict) else {}
            cache_text = meta.get("original_text", req.text)
            key = (req.engine.value, req.source_lang, req.target_lang, cache_text)
            unique_req_map.setdefault(key, []).append(idx)

        # Cache'den kontrol et
        remaining_indices: List[int] = []

        # Aggressive Retry Check
        is_aggressive = False
        if self.config_manager and hasattr(self.config_manager, "translation_settings"):
            is_aggressive = getattr(
                self.config_manager.translation_settings,
                "aggressive_retry_translation",
                False,
            )

        for key, indices in unique_req_map.items():
            cached = await self._cache_get(key)

            # Check if cache is valid considering Aggressive Retry
            is_valid_cache = False
            if cached:
                is_valid_cache = True
                # If aggressive retry is ON and translation equals original, consider it a miss
                if (
                    is_aggressive
                    and cached.translated_text.strip() == cached.original_text.strip()
                ):
                    is_valid_cache = False

            if is_valid_cache:
                self.cache_hits += 1
                if self._should_materialize_cache_alias(key, cached):
                    alias_result = self._build_cache_hit_projection(
                        requests[indices[0]],
                        cached,
                        include_request_metadata=False,
                    )
                    await self._cache_put(key, alias_result)
                for idx in indices:
                    final_results[idx] = self._build_cache_hit_projection(
                        requests[idx],
                        cached,
                        include_request_metadata=True,
                    )
            else:
                self.cache_misses += 1
                # Sadece ilk indeksi çeviriye gönder, diğerleri bunun sonucunu bekleyecek
                remaining_indices.append(indices[0])

        if not remaining_indices:
            return final_results  # type: ignore

        # 2. Motorlara Göre Grupla (Sadece cache'de olmayanlar)
        groups: Dict[TranslationEngine, List[Tuple[int, TranslationRequest]]] = {}
        for idx in remaining_indices:
            req = requests[idx]
            groups.setdefault(req.engine, []).append((idx, req))

        for engine, items in groups.items():
            if self.should_stop_callback and self.should_stop_callback():
                break
            tr = self.translators.get(engine)
            if not tr:
                for idx, r in items:
                    final_results[idx] = TranslationResult(
                        r.text,
                        "",
                        r.source_lang,
                        r.target_lang,
                        r.engine,
                        False,
                        f"Translator {engine.value} not available",
                    )
                continue

            is_ai = engine in (
                TranslationEngine.OPENAI,
                TranslationEngine.GEMINI,
                TranslationEngine.LOCAL_LLM,
            )
            only = [r for _, r in items]

            # Batch çeviri desteği kontrolü
            can_batch = (
                isinstance(tr, GoogleTranslator)
                or is_ai
                or isinstance(tr, DeepLTranslator)
                or isinstance(tr, LibreTranslateTranslator)
            )

            translated_items: List[TranslationResult] = []
            if can_batch and len(only) > 1:
                try:
                    bout = await tr.translate_batch(only)
                    if bout and len(bout) == len(only):
                        translated_items = bout
                    else:
                        # Fallback to single if batch returns invalid size
                        translated_items = []
                except Exception as e:
                    self.logger.debug(f"Batch fail {engine.value}: {e}")
                    translated_items = []

            if translated_items:
                # Toplu sonuçları yerleştir
                for (idx, _), res in zip(items, translated_items):
                    final_results[idx] = res
                    if res.success:
                        key2 = (
                            res.engine.value,
                            res.source_lang,
                            res.target_lang,
                            res.original_text,
                        )
                        await self._cache_put(key2, res)
            else:
                # Tekil çeviri akışı
                concurrency = self.max_concurrent_requests
                if is_ai:
                    concurrency = 2
                    if self.config_manager and hasattr(
                        self.config_manager.translation_settings, "ai_concurrency"
                    ):
                        concurrency = (
                            self.config_manager.translation_settings.ai_concurrency
                        )

                sem = asyncio.Semaphore(concurrency)

                async def run_single(ix: int, rq: TranslationRequest):
                    async with sem:
                        if self.should_stop_callback and self.should_stop_callback():
                            return ix, TranslationResult(
                                rq.text,
                                "",
                                rq.source_lang,
                                rq.target_lang,
                                rq.engine,
                                False,
                                "Stopped by user",
                            )
                        res = await self.translate_with_retry(rq)
                        if is_ai and self.ai_request_delay > 0:
                            await asyncio.sleep(self.ai_request_delay)
                        return ix, res

                results = await asyncio.gather(*[run_single(i, r) for i, r in items])
                for idx, res in results:
                    final_results[idx] = res
                    if res and res.success:
                        key2 = (
                            res.engine.value,
                            res.source_lang,
                            res.target_lang,
                            res.original_text,
                        )
                        await self._cache_put(key2, res)

        # 3. Sonuçları kopya (deduplicated) satırlara dağıt
        for key, indices in unique_req_map.items():
            first_idx = indices[0]
            res = final_results[first_idx]
            if res:
                for other_idx in indices[1:]:
                    # Metadata korunarak kopyalanır
                    final_results[other_idx] = TranslationResult(
                        original_text=requests[other_idx].text,
                        translated_text=res.translated_text,
                        source_lang=res.source_lang,
                        target_lang=res.target_lang,
                        engine=res.engine,
                        success=res.success,
                        error=res.error,
                        confidence=res.confidence,
                        metadata=requests[other_idx].metadata,
                    )

        await self._maybe_adapt_concurrency()
        return [
            r
            if r
            else TranslationResult(
                requests[i].text,
                "",
                requests[i].source_lang,
                requests[i].target_lang,
                requests[i].engine,
                False,
                "Translation failed",
            )
            for i, r in enumerate(final_results)
        ]

    def get_cache_stats(self) -> Dict[str, float]:
        total = self.cache_hits + self.cache_misses
        hit_rate = (self.cache_hits / total * 100) if total else 0.0
        return {
            "size": len(self._cache),
            "capacity": self.cache_capacity,
            "hits": self.cache_hits,
            "misses": self.cache_misses,
            "hit_rate": round(hit_rate, 2),
        }

    async def _record_metric(self, dur: float, ok: bool):
        if not self.adaptive_enabled:
            return
        self._recent_metrics.append((dur, ok))
        if len(self._recent_metrics) % 25 == 0:
            await self._maybe_adapt_concurrency()

    def report_rate_limit(self, engine: TranslationEngine):
        """Signal that a rate limit was hit, triggering immediate concurrency reduction."""
        if not self.adaptive_enabled:
            return

        # Immediate reaction to rate limit
        self.ai_request_delay = min(5.0, self.ai_request_delay + 0.5)

        # Reduce AI concurrency in settings if possible
        if self.config_manager and hasattr(
            self.config_manager.translation_settings, "ai_concurrency"
        ):
            current = self.config_manager.translation_settings.ai_concurrency
            new_val = max(1, int(current * 0.5))
            if new_val != current:
                self.config_manager.translation_settings.ai_concurrency = new_val
                self.logger.warning(
                    f"Rate Limit hit! Reduced AI concurrency to {new_val} and increased delay to {self.ai_request_delay}s"
                )

    async def _maybe_adapt_concurrency(self):
        if not self.adaptive_enabled:
            return
        now = time.time()
        if now - self._last_adapt_time < self.adapt_interval_sec:
            return
        if len(self._recent_metrics) < 20:
            return
        async with self._adapt_lock:
            now2 = time.time()
            if now2 - self._last_adapt_time < self.adapt_interval_sec:
                return
            durations = [d for d, _ in self._recent_metrics]
            successes = [s for _, s in self._recent_metrics]
            avg_latency = sum(durations) / len(durations)
            fail_rate = 1 - (sum(1 for s in successes if s) / len(successes))
            old = self.max_concurrent_requests
            new = old

            # General concurrency adaptation
            if fail_rate > 0.2 or avg_latency > 1.5:
                new = max(self.min_concurrency_floor, int(old * 0.8))
            elif fail_rate < 0.05 and avg_latency < 0.5:
                # Slowly recover
                new = min(self.max_concurrency_cap, max(old + 1, int(old * 1.1)))

                # Also recover AI delay slowly
                if self.ai_request_delay > 1.5:
                    self.ai_request_delay = max(1.5, self.ai_request_delay - 0.1)

            if new != old:
                self.max_concurrent_requests = new
                self.logger.info(
                    f"Adaptive concurrency {old} -> {new} (lat={avg_latency:.3f}s fail={fail_rate:.2%})"
                )

            self._last_adapt_time = now2

    def set_concurrency_limit(self, limit: int):
        """Çeviri concurrency limitini dinamik olarak ayarla."""
        # Proxy tabanlı adaptif öneriyi TranslationManager seviyesinde uygulamak için
        # mevcut `set_max_concurrency` metodunu kullanıyoruz.
        try:
            self.set_max_concurrency(int(limit))
        except Exception:
            self.set_max_concurrency(max(1, int(limit)))

    def save_cache(self, file_path: str):
        """
        Cache içeriğini diske kaydet (Atomik & Güvenli).
        Büyük verilerde I/O bloklamasını önlemek için temp-file swap kullanılır.
        """
        if not self.use_cache:
            return

        try:
            import json
            import tempfile

            # Veriyi JSON formatına hazırla. Boş cache de diske boş obje olarak yazılır;
            # bu, "clear cache" gibi akışlarda eski dosyanın yeniden yüklenmesini engeller.
            data = {}
            for key, val in self._cache.items():
                try:
                    engine_str, sl, tl, text = key

                    if engine_str not in data:
                        data[engine_str] = {}

                    engine_dict = data[engine_str]
                    if sl not in engine_dict:
                        engine_dict[sl] = {}

                    sl_dict = engine_dict[sl]
                    if tl not in sl_dict:
                        sl_dict[tl] = {}

                    tl_dict = sl_dict[tl]
                    tl_dict[text] = val.translated_text
                except (ValueError, TypeError, KeyError):
                    continue

            # Dizini kontrol et
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            # Atomik Yazma: Önce geçici bir dosyaya yaz, sonra yer değiştir
            # Bu yöntem ani sistem kapanmalarında ana cache dosyasının bozulmasını önler.
            temp_fd, temp_path = tempfile.mkstemp(
                dir=os.path.dirname(file_path), suffix=".tmp"
            )
            try:
                with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                # Windows'ta os.replace güvenli atomik yer değiştirmeyi sağlar
                if os.path.exists(file_path):
                    try:
                        os.replace(temp_path, file_path)
                    except OSError:
                        # Eğer dosya kullanımdaysa (nadiren), saniyeler sonra tekrar denemeyi Pipeline'a bırak
                        os.remove(temp_path)
                        raise
                else:
                    os.rename(temp_path, file_path)

            except Exception as e:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise e

            self.logger.info(
                f"Cache saved atomically: {file_path} ({len(self._cache)} entries)"
            )
        except Exception as e:
            self.logger.error(f"Failed to save cache: {e}")

    def load_cache(self, file_path: str):
        """Cache içeriğini diskten yükle."""
        if not self.use_cache or not os.path.exists(file_path):
            return

        try:
            import json

            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                self.logger.warning(f"Invalid cache format in {file_path}")
                return

            count = 0
            # Init aşamasında concurrency olmadığı için lock gerekmez.
            # Doğrudan senkron olarak yükle.
            for engine_str, sl_map in data.items():
                if not isinstance(sl_map, dict):
                    continue
                for sl, tl_map in sl_map.items():
                    if not isinstance(tl_map, dict):
                        continue
                    for tl, text_map in tl_map.items():
                        if not isinstance(text_map, dict):
                            continue
                        for text, translated in text_map.items():
                            key = (engine_str, sl, tl, text)
                            # Basit validasyon
                            engine_enum = TranslationEngine.GOOGLE
                            if engine_str in [e.value for e in TranslationEngine]:
                                engine_enum = TranslationEngine(engine_str)

                            res = TranslationResult(
                                original_text=text,
                                translated_text=str(translated),
                                source_lang=sl,
                                target_lang=tl,
                                engine=engine_enum,
                                success=True,
                            )
                            self._cache[key] = res
                            count += 1

            # Kapasite limitini uygula
            while len(self._cache) > self.cache_capacity:
                self._cache.popitem(last=False)

            self.logger.info(f"Cache loaded: {file_path} ({count} entries)")
        except Exception as e:
            self.logger.error(f"Failed to load cache: {e}")
