# -*- coding: utf-8 -*-
"""
Google Translator implementation with multi-endpoint routing and Lingva fallback.
"""
from __future__ import annotations

import asyncio
import aiohttp
import json
import logging
import os
import re
import time
import urllib.parse
from collections import OrderedDict, deque, Counter
import random
from typing import Dict, List, Optional, Tuple, Callable

from src.core.syntax_guard import (
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
    GOOGLE_BATCHEXECUTE_ENDPOINT,
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

from .base import (
    IN_FALLBACK,
    BaseTranslator,
    TranslationEngine,
    TranslationRequest,
    TranslationResult,
)
from .router import EndpointRouter, _FamilyHealth

# client= ids /translate_a/single answers with the same reply. Since 2026-09 Google
# answers client=gtx with 429 in some regions while "at" and "dict-chrome-ex" still work.
PRIMARY_CLIENTS: Tuple[str, ...] = ("gtx", "at", "dict-chrome-ex")


class GoogleTranslator(BaseTranslator):
    """Multi-endpoint Google Translator with Lingva fallback.

    Uses multiple Google mirrors in parallel for faster translation,
    with Lingva Translate as a free fallback when Google fails.
    """

    # Use imported constants instead of hardcoded lists
    google_endpoints = GOOGLE_ENDPOINTS
    lingva_instances = LINGVA_INSTANCES

    async def close(self) -> None:
        """Clean up background probe task and HTTP session."""
        if hasattr(self, "_router") and self._router is not None:
            self._router.close()
        await super().close()

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
        # Gracefully handle positional config_manager (e.g. GoogleTranslator(config))
        if args and hasattr(args[0], "translation_settings"):
            config_manager = args[0]
            args = args[1:]
        super().__init__(*args, config_manager=config_manager, **kwargs)
        self.config_manager = config_manager
        self._endpoint_index = 0
        # Client id that last got a 200 from /translate_a/single (tried first).
        self._primary_client: str = PRIMARY_CLIENTS[0]
        # Bing (separate request family, independent IP limit) takes over lines every
        # Google family failed on. Built lazily; has no fallback of its own.
        self.bing_fallback_enabled: bool = True
        self._bing_fallback = None
        self._bing_down_until: float = 0.0

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
            0  # Track consecutive 429s across all mirrors (backward-compat)
        )
        # Next wall-clock time at which a blocked primary endpoint may be
        # probed again (one request per RATE_LIMIT_PRIMARY_PROBE_INTERVAL).
        # Kept for backward-compat; EndpointRouter owns the probe logic now.
        self._primary_probe_at: float = 0.0
        # Alternate-family rescue counter — drives the periodic status line.
        self._alternate_rescues: int = 0

        # ── Smart endpoint router ─────────────────────────────────────────
        # Manages PRIMARY → BATCHEXECUTE → CLIENTS5 → LINGVA routing with
        # per-family health tracking and a non-blocking background probe.
        self._router = EndpointRouter()
        # Probe lock: ensures only ONE concurrent worker sends a primary probe
        # request, preventing N workers from all probing simultaneously and
        # triggering N × 429.
        self._probe_lock: asyncio.Lock = asyncio.Lock()
        # Inject the probe callback so the router can issue real requests.
        self._router._do_probe = self._probe_primary_endpoint  # type: ignore[assignment]

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

    async def _probe_primary_endpoint(self) -> bool:
        """Single lightweight probe request to any primary mirror.
        Called by EndpointRouter._probe_loop() — runs in background, never
        blocks the in-flight translation pipeline.
        Returns True if the primary endpoint is responding normally."""
        endpoint = random.choice(self.google_endpoints)
        for client in self._client_order():
            params = {
                "client": client,
                "sl": "en",
                "tl": "tr",
                "dt": "t",
                "q": "test",
            }
            try:
                query = urllib.parse.urlencode(params)
                url = f"{endpoint}?{query}"
                session = await self._get_session()
                async with session.get(
                    url,
                    proxy=self._proxy_url(),
                    timeout=aiohttp.ClientTimeout(total=6),
                    headers=GOOGLE_BROWSER_HEADERS,
                ) as resp:
                    if resp.status == 200:
                        self.logger.info(
                            "Primary probe succeeded on %s — primary endpoints restored.", endpoint
                        )
                        # Sync legacy counter so _try_batch_separator guard works too
                        self._consecutive_429_count = 0
                        self._primary_probe_at = 0.0
                        self._set_primary_client(client)
                        return True
                    if resp.status == 429:
                        self.logger.debug("Primary probe got 429 on %s (client=%s).", endpoint, client)
                        continue
            except Exception as exc:
                self.logger.debug("Primary probe exception on %s: %s", endpoint, exc)
                return False
        return False

    def _client_order(self) -> List[str]:
        """Primary client ids, the one that worked last first."""
        return [self._primary_client] + [c for c in PRIMARY_CLIENTS if c != self._primary_client]

    def _alternate_client(self, tried: set) -> Optional[str]:
        """A client id not yet refused by this request, or None when all were."""
        for client in self._client_order():
            if client not in tried:
                return client
        return None

    def _set_primary_client(self, client: str) -> None:
        if client != self._primary_client:
            self.logger.warning(
                "Google refused client=%s; using client=%s from now on", self._primary_client, client
            )
            self._primary_client = client

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
                    url, proxy=self._proxy_url(), timeout=aiohttp.ClientTimeout(total=6)
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
                proxy=self._proxy_url(),
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

    async def _post_batchexecute(self, inner_args: str) -> Optional[str]:
        """POST one MkEWBc RPC to TranslateWebserverUi and return the raw
        length-prefixed envelope body, or None on any failure."""
        freq = json.dumps(
            [[["MkEWBc", inner_args, None, "generic"]]], separators=(",", ":")
        )
        params = {
            "rpcids": "MkEWBc",
            "source-path": "/",
            "f.sid": "",
            "bl": "",
            "hl": "en-US",
            "soc-app": "1",
            "soc-platform": "1",
            "soc-device": "1",
            "_reqid": str(random.randint(1000, 9999)),
            "rt": "c",
        }
        headers = dict(GOOGLE_BROWSER_HEADERS)
        headers["Content-Type"] = "application/x-www-form-urlencoded;charset=UTF-8"
        try:
            session = await self._get_session()
            async with session.post(
                GOOGLE_BATCHEXECUTE_ENDPOINT,
                proxy=self._proxy_url(),
                params=params,
                data=f"f.req={urllib.parse.quote(freq)}&",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=12),
            ) as resp:
                if resp.status != 200:
                    return None
                return await resp.text()
        except Exception as e:
            self.logger.debug(f"batchexecute request failed: {e}")
            return None

    @staticmethod
    def _iter_batchexecute_inner(raw: Optional[str]):
        """Yield parsed inner payloads from a batchexecute envelope body."""
        if not raw:
            return
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("[") or "MkEWBc" not in line:
                continue
            try:
                envelope = json.loads(line)
                yield json.loads(envelope[0][2])
            except (ValueError, IndexError, TypeError):
                continue

    @staticmethod
    def _parse_batchexecute_text(raw: Optional[str]) -> Optional[str]:
        """Extract joined sentence translations from a batchexecute body."""
        for inner in GoogleTranslator._iter_batchexecute_inner(raw):
            try:
                node = inner[1][0][0]
            except (TypeError, IndexError):
                continue
            if isinstance(node, str):
                # Plain-string node: the whole translation in one value.
                if node:
                    return node
                continue
            if isinstance(node, list):
                if len(node) > 5 and isinstance(node[5], list):
                    text = "".join(s[0] for s in node[5] if s and s[0])
                    if text:
                        return text
                if node and isinstance(node[0], str) and node[0]:
                    return node[0]
        return None

    @staticmethod
    def _extract_batchexecute_lang(raw: Optional[str]) -> Optional[str]:
        """Detected source language sits at inner[0][2] in auto mode."""
        for inner in GoogleTranslator._iter_batchexecute_inner(raw):
            try:
                detected = inner[0][2]
                if isinstance(detected, str) and len(detected) >= 2:
                    return detected.lower()
            except (TypeError, IndexError):
                continue
        return None

    async def _translate_via_batchexecute(
        self, text: str, source: str, target: str
    ) -> Optional[str]:
        """Fallback via the TranslateWebserverUi RPC layer (MkEWBc) — a third,
        fully separate Google pipeline. Verified live while /translate_a/single
        was range-blocked."""
        args = json.dumps([[text, source or "auto", target, True], [None]])
        raw = await self._post_batchexecute(args)
        return self._parse_batchexecute_text(raw)

    async def _translate_via_batchexecute_batch(
        self,
        texts: List[str],
        source: str,
        target: str,
    ) -> Optional[List[str]]:
        """Multi-item batch via the TranslateWebserverUi RPC layer (MkEWBc).

        Sends all texts in a single f.req array POST — one round-trip for
        the whole batch. Each item is tagged with its index (str(i)).
        Google streams envelopes (wrb.fr) back asynchronously in arbitrary
        order; we match each item by its ID tag back to its exact slot.

        Returns None if any item failed to parse or was omitted.
        """
        if not texts:
            return None

        # Build per-item RPC frames tagged with original index: [[text, src, tgt, True], [None]]
        rpc_items = [
            ["MkEWBc", json.dumps([[t, source or "auto", target, True], [None]]), None, str(i)]
            for i, t in enumerate(texts)
        ]
        freq = json.dumps([rpc_items], separators=(",", ":"))

        params = {
            "rpcids": "MkEWBc",
            "source-path": "/",
            "f.sid": "",
            "bl": "",
            "hl": "en-US",
            "soc-app": "1",
            "soc-platform": "1",
            "soc-device": "1",
            "_reqid": str(random.randint(1000, 9999)),
            "rt": "c",
        }
        headers = dict(GOOGLE_BROWSER_HEADERS)
        headers["Content-Type"] = "application/x-www-form-urlencoded;charset=UTF-8"

        try:
            session = await self._get_session()
            async with session.post(
                GOOGLE_BATCHEXECUTE_ENDPOINT,
                proxy=self._proxy_url(),
                params=params,
                data=f"f.req={urllib.parse.quote(freq)}&",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    self.logger.debug(
                        "batchexecute batch HTTP %d for %d items", resp.status, len(texts)
                    )
                    return None
                raw = await resp.text()
        except Exception as exc:
            self.logger.debug("batchexecute batch request failed: %s", exc)
            return None

        # Parse per-item responses from length-prefixed wrb.fr envelopes
        results: List[Optional[str]] = [None] * len(texts)
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("[") or "wrb.fr" not in line:
                continue
            try:
                env = json.loads(line)
                for entry in env:
                    if isinstance(entry, list) and len(entry) >= 4 and entry[0] == "wrb.fr":
                        try:
                            item_id = int(entry[-1])
                        except (ValueError, TypeError):
                            continue
                        if not (0 <= item_id < len(texts)):
                            continue
                        if not entry[2]:
                            continue
                        inner = json.loads(entry[2])
                        try:
                            node = inner[1][0][0]
                        except (TypeError, IndexError):
                            continue

                        if isinstance(node, str) and node:
                            results[item_id] = node
                        elif isinstance(node, list) and len(node) > 5 and isinstance(node[5], list):
                            text_out = "".join(s[0] for s in node[5] if s and s[0])
                            results[item_id] = text_out or None
                        elif isinstance(node, list) and node and isinstance(node[0], str) and node[0]:
                            results[item_id] = node[0]
            except (ValueError, TypeError):
                continue

        # If any item is missing, fail over to clients5 gracefully
        if any(r is None for r in results):
            received = sum(1 for r in results if r is not None)
            self.logger.debug(
                "batchexecute batch incomplete: received %d/%d items", received, len(texts)
            )
            return None

        return [r for r in results if r is not None]

    async def _translate_via_clients5_parallel(
        self,
        batch: List[TranslationRequest],
        router: "EndpointRouter",
    ) -> List["TranslationResult"]:
        """Translate a batch using clients5 single-item calls in parallel.

        Used when the primary/batchexecute families are blocked. Concurrency
        is capped so we don't hammer the alternate endpoint.
        """
        sem = asyncio.Semaphore(min(self.multi_q_concurrency, 16))

        async def _one(req: TranslationRequest) -> TranslationResult:
            async with sem:
                meta = req.metadata if isinstance(req.metadata, dict) else {}
                source_text = meta.get("original_text", req.text)
                protected, placeholders, _ = self._prepare_request_protection(req)

                raw = await self._translate_via_clients5(
                    protected, req.source_lang, req.target_lang
                )
                if raw:
                    router.record_family_success(EndpointRouter.FAMILY_CLIENTS5)
                    restored = restore_renpy_syntax(raw, placeholders)
                    if placeholders and validate_translation_integrity(restored, placeholders):
                        # Integrity failed — try batchexecute as per-item fallback
                        raw2 = await self._translate_via_batchexecute(
                            protected, req.source_lang, req.target_lang
                        )
                        if raw2:
                            restored = restore_renpy_syntax(raw2, placeholders)
                            if validate_translation_integrity(restored, placeholders):
                                restored = source_text
                        else:
                            restored = source_text
                    if restored.strip() != source_text.strip():
                        self._alternate_rescues += 1
                        if self._alternate_rescues == 1 or self._alternate_rescues % 50 == 0:
                            self.logger.warning(
                                "Alternate Google endpoint active: %d translations rescued "
                                "while primary endpoints are IP-blocked.",
                                self._alternate_rescues,
                            )
                    return TranslationResult(
                        source_text, restored,
                        req.source_lang, req.target_lang,
                        TranslationEngine.GOOGLE, True,
                        confidence=0.85, metadata=req.metadata,
                    )

                router.record_family_failure(EndpointRouter.FAMILY_CLIENTS5, block_for=0.0)
                return TranslationResult(
                    source_text, source_text,
                    req.source_lang, req.target_lang,
                    TranslationEngine.GOOGLE, False,
                    "clients5 failed", metadata=req.metadata,
                )

        tasks = [asyncio.create_task(_one(r)) for r in batch]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)

        results: List[TranslationResult] = []
        for i, item in enumerate(gathered):
            if isinstance(item, Exception):
                req = batch[i]
                meta = req.metadata if isinstance(req.metadata, dict) else {}
                src = meta.get("original_text", req.text)
                results.append(TranslationResult(
                    src, src, req.source_lang, req.target_lang,
                    TranslationEngine.GOOGLE, False, str(item), metadata=req.metadata,
                ))
            else:
                results.append(item)
        return results

    # ------------------------------------------------------------------
    # Bing hand-off: Google throttles per IP, so a flagged IP loses every Google
    # family at once. Bing's endpoint is limited independently and keeps the run alive.
    # ------------------------------------------------------------------

    def _bing_fallback_available(self) -> bool:
        if not self.bing_fallback_enabled or IN_FALLBACK.get():
            return False
        if time.time() < self._bing_down_until:
            return False
        stop = self.should_stop_callback
        return not (stop and stop())

    async def _delegate_to_bing(
        self, requests: List[TranslationRequest]
    ) -> List[Optional[TranslationResult]]:
        """Translate ``requests`` with Bing; None for every line Bing could not do either."""
        from .services import BingTranslator

        if self._bing_fallback is None:
            self._bing_fallback = BingTranslator(
                proxy_manager=self.proxy_manager, config_manager=self.config_manager
            )
        bing = self._bing_fallback
        bing.status_callback = self.status_callback
        token = IN_FALLBACK.set(True)
        try:
            answers = await bing.translate_batch(requests)
        except Exception as exc:  # best effort: the Google failure is already recorded
            self.logger.warning("Bing fallback failed: %s", exc)
            answers = []
        finally:
            IN_FALLBACK.reset(token)
        if len(answers) != len(requests):
            answers = [None] * len(requests)
        out: List[Optional[TranslationResult]] = []
        for req, ans in zip(requests, answers):
            if ans is not None and ans.success and (ans.translated_text or "").strip():
                meta = dict(req.metadata) if isinstance(req.metadata, dict) else {}
                meta["fallback_engine"] = "bing"
                out.append(
                    TranslationResult(
                        original_text=ans.original_text,
                        translated_text=ans.translated_text,
                        source_lang=req.source_lang,
                        target_lang=req.target_lang,
                        engine=TranslationEngine.GOOGLE,
                        success=True,
                        confidence=getattr(ans, "confidence", 0.0),
                        metadata=meta,
                    )
                )
            else:
                out.append(None)
        if not any(out):
            # Bing is blocked too; do not queue every following line behind its retries.
            self._bing_down_until = time.time() + 60.0
        return out

    async def translate_single(self, request: TranslationRequest) -> TranslationResult:
        """Google first; when every Google path failed, Bing gets one try."""
        result = await self._translate_single_google(request)
        if result.success or not self._bing_fallback_available():
            return result
        answer = (await self._delegate_to_bing([request]))[0]
        return answer if answer is not None else result

    async def translate_batch(
        self, requests: List[TranslationRequest]
    ) -> List[TranslationResult]:
        """Google first; lines every Google path failed on go to Bing in one call."""
        results = await self._translate_batch_google(requests)
        if not self._bing_fallback_available():
            return results
        failed = [i for i, r in enumerate(results) if r is None or not r.success]
        if not failed:
            return results
        self.emit_log("warning", self._get_text(
            "log_google_bing_fallback",
            "[Google] {count} item(s) failed; delegating to Bing.",
            count=len(failed),
        ))
        answers = await self._delegate_to_bing([requests[i] for i in failed])
        for index, answer in zip(failed, answers):
            if answer is not None:
                results[index] = answer
        return results

    async def _translate_single_google(self, request: TranslationRequest) -> TranslationResult:
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
                async with self._probe_lock:
                    if now < self._primary_probe_at:
                        return None
                    # Atomically claim the probe slot
                    self._primary_probe_at = now + RATE_LIMIT_PRIMARY_PROBE_INTERVAL
                entered_as_probe = True
            max_attempts = 3
            tried_clients: set = set()
            client = self._primary_client
            attempt = 0
            while attempt < max_attempts:
                attempt += 1
                # Another worker's 429 tripped the breaker mid-flight — stop
                # burning attempts against a range-blocked host.
                if (
                    self._consecutive_429_count
                    >= RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD
                    and not entered_as_probe
                ):
                    return None
                # Probe skips global cooldown — its purpose is to test
                # whether the IP block has lifted, not to wait it out.
                if not entered_as_probe:
                    await self._wait_out_global_cooldown()
                try:
                    query = urllib.parse.urlencode({**params, "client": client}, doseq=True, safe="")
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
                                    self._router.record_primary_success()
                                    self._set_primary_client(client)
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
                            # Another client id may still be served: not an IP flag yet.
                            tried_clients.add(client)
                            alternate = self._alternate_client(tried_clients)
                            if alternate is not None:
                                client = alternate
                                attempt -= 1
                                continue
                            # Google rate-limits by IP — a 429 on one mirror means ALL mirrors
                            # are likely throttled. Apply global cooldown to prevent cascade bans.
                            global_wait = self._apply_global_cooldown()
                            # Also count as fail — 429 is a real failure signal
                            if endpoint in self._endpoint_health:
                                self._endpoint_health[endpoint]["fails"] += 1
                            if proxy_url_used and self.proxy_manager:
                                self.proxy_manager.mark_proxy_failed(proxy_url_used)
                            # Notify router — triggers ALTERNATE state on Nth 429
                            self._router.record_primary_429()
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
                    if self.note_tls_error(e):
                        return None  # a CA problem is not the mirror's fault
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
            for family, fetcher in (
                ("clients5", self._translate_via_clients5),
                ("batchexecute", self._translate_via_batchexecute),
            ):
                alt_result = await fetcher(
                    protected_text, request.source_lang, request.target_lang
                )
                if not alt_result:
                    continue
                alt_final = restore_renpy_syntax(alt_result, placeholders)
                if placeholders and validate_translation_integrity(
                    alt_final, placeholders
                ):
                    self.logger.warning(
                        f"Integrity check failed ({family}): Placeholders missing. "
                        f"Using original text."
                    )
                    continue
                if alt_final.strip() != source_text.strip():
                    self._alternate_rescues += 1
                    if (
                        self._alternate_rescues == 1
                        or self._alternate_rescues % 50 == 0
                    ):
                        self.logger.warning(
                            f"Alternate Google endpoint active: "
                            f"{self._alternate_rescues} translations rescued while "
                            f"primary endpoints are IP-blocked."
                        )
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
            self.logger.warning(
                "translate_single failed for text=%r: %s", request.text, e
            )

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
            "client": self._primary_client,
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
                    proxy=self._proxy_url(),
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=5),
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
                proxy=self._proxy_url(),
                params=params5,
                timeout=aiohttp.ClientTimeout(total=6),
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

        try:
            args = json.dumps([[text[:500], "auto", "en", True], [None]])
            detected = self._extract_batchexecute_lang(
                await self._post_batchexecute(args)
            )
            if detected:
                return detected
        except Exception as e:
            self.logger.debug(f"batchexecute language detection failed: {e}")

        return None

    async def _translate_batch_google(
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
        # When not using proxies, cap concurrency to 4 to prevent Google's WAF
        # from instantly flagging the residential IP with a burst-rate 429.
        if is_parallel and not getattr(self, "use_proxy", False):
            concurrency_limit = min(concurrency_limit, 4)
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
                        result = await self._translate_single_google(req)
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
        """Batch translation with smart router: PRIMARY → BATCHEXECUTE → CLIENTS5.

        Routing is determined by EndpointRouter which tracks per-family health
        and circuit breaker state. When primaries are blocked the batch goes
        directly to batchexecute (true multi-item) or clients5 (parallel)
        without wasting time on doomed primary probe attempts.
        """
        if not batch:
            return []
        if len(batch) == 1:
            return [await self._translate_single_google(batch[0])]

        router = self._router
        total_chars = sum(len(r.text) for r in batch)

        # ── PRIMARY PATH ────────────────────────────────────────────────────
        # Only attempt batch separator when primaries are healthy.
        # When primary_blocked, skip straight to alternate families — this
        # is the key fix that eliminates the 25-50s probe-induced stalls.
        if not router.primary_blocked and len(batch) <= 50 and total_chars <= 8000:
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
                            retry = await self._translate_single_google(batch[idx])
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
                f"Batch separator failed for {len(batch)} texts ({total_chars} chars)"
            )

        # ── ALTERNATE FAMILIES (primary blocked or separator failed) ────────
        best = router.best_family_for_batch()

        # BATCHEXECUTE: true multi-item batch — single round-trip
        if best in (EndpointRouter.FAMILY_BATCHEXECUTE, EndpointRouter.FAMILY_PRIMARY):
            source_lang = batch[0].source_lang
            target_lang = batch[0].target_lang
            protected_texts = []
            all_placeholders = []
            for req in batch:
                protected, placeholders, _ = self._prepare_request_protection(req)
                protected_texts.append(protected)
                all_placeholders.append(placeholders)

            raw_results = await self._translate_via_batchexecute_batch(
                protected_texts, source_lang, target_lang
            )
            if raw_results:
                router.record_family_success(EndpointRouter.FAMILY_BATCHEXECUTE)
                self.logger.info(
                    "batchexecute batch: translated %d texts in one round-trip.", len(batch)
                )
                final: List[TranslationResult] = []
                for req, raw, placeholders in zip(batch, raw_results, all_placeholders):
                    meta = req.metadata if isinstance(req.metadata, dict) else {}
                    source_text = meta.get("original_text", req.text)
                    restored = restore_renpy_syntax(raw, placeholders) if raw else source_text
                    if placeholders and raw and validate_translation_integrity(restored, placeholders):
                        restored = source_text
                    final.append(TranslationResult(
                        source_text, restored,
                        req.source_lang, req.target_lang,
                        TranslationEngine.GOOGLE, True,
                        confidence=0.85, metadata=req.metadata,
                    ))
                return final

            router.record_family_failure(EndpointRouter.FAMILY_BATCHEXECUTE, block_for=120.0)
            self.logger.debug("batchexecute batch failed — falling through to clients5.")
            best = router.best_family_for_batch()

        # CLIENTS5: parallel single-item calls
        if best == EndpointRouter.FAMILY_CLIENTS5:
            return await self._translate_via_clients5_parallel(batch, router)

        # LINGVA / last resort: fall back to parallel individual translate_single
        self.logger.debug(f"Using parallel translation for {len(batch)} texts (lingva/last resort)")
        return await self._translate_parallel(batch)

    async def _try_batch_separator(
        self, batch: List[TranslationRequest]
    ) -> Optional[List[TranslationResult]]:
        """Try batch translation with separator. Returns None if fails.

        When the EndpointRouter marks primary endpoints as blocked, this
        method returns None immediately so _multi_q can route to
        batchexecute/clients5 without triggering any probe sleep.
        """
        # Fast exit: primaries are IP-blocked — no point attempting them.
        if self._router.primary_blocked:
            return None

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
                async with self._probe_lock:
                    if now < self._primary_probe_at:
                        return None
                    # Atomically claim the probe slot
                    self._primary_probe_at = now + RATE_LIMIT_PRIMARY_PROBE_INTERVAL
                entered_as_probe = True
            max_attempts = 2  # Fewer retries than translate_single (batch is heavier)
            tried_clients: set = set()
            client = self._primary_client
            attempt = 0
            while attempt < max_attempts:
                attempt += 1
                # Breaker tripped mid-flight by another worker — bail early.
                if (
                    self._consecutive_429_count
                    >= RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD
                    and not entered_as_probe
                ):
                    return None
                # Probe requests skip the global cooldown — they are supposed
                # to test whether the IP block has lifted, not wait it out.
                if not entered_as_probe:
                    await self._wait_out_global_cooldown()
                try:
                    session = await self._get_session()

                    proxy = None
                    proxy_url_used = None
                    if self.use_proxy and self.proxy_manager:
                        p = self.proxy_manager.get_next_proxy()
                        if p:
                            proxy = p.url
                            proxy_url_used = proxy

                    post_headers = dict(GOOGLE_BROWSER_HEADERS)
                    post_headers["Content-Type"] = "application/x-www-form-urlencoded;charset=utf-8"

                    async with session.post(
                        endpoint,
                        data=urllib.parse.urlencode({**params, "client": client}),
                        proxy=proxy,
                        timeout=aiohttp.ClientTimeout(total=15),
                        headers=post_headers,
                    ) as resp:
                        if resp.status == 429:
                            # Another client id may still be served: not an IP flag yet.
                            tried_clients.add(client)
                            alternate = self._alternate_client(tried_clients)
                            if alternate is not None:
                                client = alternate
                                attempt -= 1
                                continue
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
                        if segs:
                            self._set_primary_client(client)
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
                    if self.note_tls_error(e):
                        return None  # a CA problem is not the mirror's fault
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
                return await self._translate_single_google(req)

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
                result = await self._translate_single_google(req)
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


