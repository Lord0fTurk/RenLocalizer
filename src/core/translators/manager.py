# -*- coding: utf-8 -*-
"""
TranslationManager: manages translator instances, caches, and dispatching.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict, deque
from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple, Callable, Union

from .base import (
    BaseTranslator,
    TranslationEngine,
    TranslationRequest,
    TranslationResult,
)
from .google import GoogleTranslator
from .services import DeepLTranslator, LibreTranslateTranslator, BingTranslator

_CORRUPT_OR_PROTECTED_CACHE_RE = re.compile(
    r'<ph\b|\bph\s*>|</\s*ph\s*>|\u27e6|\u27e7|__PH_\d+__|XRPYX_|RLPH[0-9A-F]{3,}'
)


def _is_corrupt_or_protected_cache_text(text: str) -> bool:
    """True for keys or values containing leaked placeholder tokens or XML remnants."""
    if not text:
        return False
    return bool(_CORRUPT_OR_PROTECTED_CACHE_RE.search(text))


_is_protected_cache_text = _is_corrupt_or_protected_cache_text


class _ObservableCacheDict(OrderedDict):
    """OrderedDict that tracks dirty state and secondary O(1) lookup indices."""

    def __init__(self, manager: "TranslationManager", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._manager = manager

    def __setitem__(self, key, val):
        super().__setitem__(key, val)
        mgr = getattr(self, "_manager", None)
        if mgr is not None:
            mgr._is_dirty = True
            try:
                engine_str, sl, tl, text = key
                mgr._engine_text_index[(engine_str, tl, text)] = val
                mgr._text_target_index[(tl, text)] = val
            except (ValueError, TypeError):
                pass

    def __delitem__(self, key):
        super().__delitem__(key)
        mgr = getattr(self, "_manager", None)
        if mgr is not None:
            mgr._is_dirty = True
            try:
                engine_str, sl, tl, text = key
                mgr._engine_text_index.pop((engine_str, tl, text), None)
                mgr._text_target_index.pop((tl, text), None)
            except (ValueError, TypeError):
                pass

    def pop(self, key, *args):
        mgr = getattr(self, "_manager", None)
        res = super().pop(key, *args)
        if mgr is not None:
            mgr._is_dirty = True
            try:
                engine_str, sl, tl, text = key
                mgr._engine_text_index.pop((engine_str, tl, text), None)
                mgr._text_target_index.pop((tl, text), None)
            except (ValueError, TypeError):
                pass
        return res

    def popitem(self, last=True):
        res = super().popitem(last=last)
        mgr = getattr(self, "_manager", None)
        if mgr is not None:
            mgr._is_dirty = True
            try:
                key, val = res
                engine_str, sl, tl, text = key
                if mgr._engine_text_index.get((engine_str, tl, text)) == val:
                    mgr._engine_text_index.pop((engine_str, tl, text), None)
                if mgr._text_target_index.get((tl, text)) == val:
                    mgr._text_target_index.pop((tl, text), None)
            except (ValueError, TypeError):
                pass
        return res

    def clear(self):
        super().clear()
        mgr = getattr(self, "_manager", None)
        if mgr is not None:
            mgr._is_dirty = True
            mgr._engine_text_index.clear()
            mgr._text_target_index.clear()


class TranslationManager:
    def __init__(self, proxy_manager=None, config_manager=None):
        self._cache_bypass = threading.local()
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

        self._is_dirty: bool = False
        self._engine_text_index: Dict[Tuple[str, str, str], TranslationResult] = {}
        self._text_target_index: Dict[Tuple[str, str], TranslationResult] = {}
        self.cache_capacity = 500000  # Increased from 20k to 500k to support large VNs
        self._cache: OrderedDict = _ObservableCacheDict(self)
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

            # 2. Akıllı Dil Eşleşmesi (aynı motor, hedef dil ve metin)
            val = self._engine_text_index.get((engine_val, tl, text))
            if val:
                return val

            # 3. Motor Bağımsız Ebeveyn Eşleşmesi (Cross-Engine)
            val = self._text_target_index.get((tl, text))
            if val:
                return val

            return self._scan_unindexed_cache(tl, text)

    def _scan_unindexed_cache(self, tl: str, text: str) -> Optional[TranslationResult]:
        """Linear lookup, only when _cache was swapped for a plain dict.

        _ObservableCacheDict keeps both indexes current on every write, so a
        miss there is a real miss; scanning 500k entries per miss made the
        "O(1)" fast path O(N*M) on partially cached projects.
        """
        if isinstance(self._cache, _ObservableCacheDict):
            return None
        for k, v in reversed(list(self._cache.items())):
            if k[2] == tl and k[3] == text and v and v.success and v.translated_text:
                return v
        return None

    def get_cached_translation(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        engine: Optional[Union[TranslationEngine, str]] = None,
    ) -> Optional[TranslationResult]:
        """Synchronous O(1) cache lookup for pipeline pre-resolution.

        Checks exact engine match first, then engine-agnostic match for target_lang.
        Returns None if cache is disabled, text is empty, or not found in cache.
        """
        if not self.use_cache or not text:
            return None

        engine_val = ""
        if engine:
            engine_val = engine.value if isinstance(engine, TranslationEngine) else str(engine)

        # 1. Exact engine match
        if engine_val:
            val = self._cache.get((engine_val, source_lang, target_lang, text))
            if val and val.success and val.translated_text:
                return val

            # 2. Same engine, any source language / auto
            val = self._engine_text_index.get((engine_val, target_lang, text))
            if val and val.success and val.translated_text:
                return val

        # 3. Cross-engine / any engine match for target_lang + text
        val = self._text_target_index.get((target_lang, text))
        if val and val.success and val.translated_text:
            return val

        return self._scan_unindexed_cache(target_lang, text)

    async def _cache_put(self, key: Tuple[str, str, str, str], val: TranslationResult):
        if not self.use_cache or not val.success:
            return
        # Do not cache corrupt translations that leaked placeholders or tokens
        if _is_corrupt_or_protected_cache_text(key[3]) or _is_corrupt_or_protected_cache_text(val.translated_text):
            return
        async with self._cache_lock:
            self._cache[key] = val
            self._cache.move_to_end(key)
            if len(self._cache) > self.cache_capacity:
                self._cache.popitem(last=False)

    @property
    def use_cache(self) -> bool:
        """Cache switch; always False on a thread inside ``bypass_cache()``."""
        bypass = getattr(self, "_cache_bypass", None)
        return getattr(self, "_use_cache", True) and not getattr(bypass, "active", False)

    @use_cache.setter
    def use_cache(self, value: bool) -> None:
        self._use_cache = bool(value)

    @contextmanager
    def bypass_cache(self):
        """Neither read nor write the cache on the calling thread.

        Used by the editor's suggestions: the cache holds the line's current
        translation (or the hand edit synced on save), so a lookup would just
        return it. Thread-local, so a translation run on another thread keeps
        using the cache.
        """
        previous = getattr(self._cache_bypass, "active", False)
        self._cache_bypass.active = True
        try:
            yield
        finally:
            self._cache_bypass.active = previous

    async def cache_remove(self, key: Tuple[str, str, str, str]):
        """Remove a specific key from memory cache (e.g. when rejected by output guard)."""
        if not self.use_cache:
            return
        async with self._cache_lock:
            self._cache.pop(key, None)

    async def cache_update_text(self, key: Tuple[str, str, str, str], updated_translated_text: str):
        """Update cached translation text with cleaned/normalized output from pipeline."""
        if not self.use_cache:
            return
        if _is_corrupt_or_protected_cache_text(key[3]) or _is_corrupt_or_protected_cache_text(updated_translated_text):
            await self.cache_remove(key)
            return
        async with self._cache_lock:
            cached = self._cache.get(key)
            if cached and cached.translated_text != updated_translated_text:
                cached.translated_text = updated_translated_text
                self._cache.move_to_end(key)
                # In-place mutation bypasses _ObservableCacheDict.__setitem__.
                self._is_dirty = True

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

    @staticmethod
    def _cache_key_for(req: TranslationRequest) -> Tuple[str, str, str, str]:
        """Cache key for *req*, always keyed by the original (unprotected) text.

        Lookups normalise to metadata['original_text'], so stores must do the
        same. Storing `result.original_text` instead meant AI engines — which
        return the XML/token-protected text they were given — wrote keys that
        no later lookup could ever match, so every line containing a
        placeholder was re-translated on each run.
        """
        meta = req.metadata if isinstance(req.metadata, dict) else {}
        text = meta.get("original_text", req.text)
        return (req.engine.value, req.source_lang, req.target_lang, text)

    async def translate_with_retry(self, req: TranslationRequest) -> TranslationResult:
        # ── Normalize cache key to original (unprotected) text ──
        key = self._cache_key_for(req)
        cache_text = key[3]
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
            key = self._cache_key_for(req)
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
                or isinstance(tr, BingTranslator)
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
                for (idx, batch_req), res in zip(items, translated_items):
                    final_results[idx] = res
                    if res.success:
                        await self._cache_put(self._cache_key_for(batch_req), res)
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
                        await self._cache_put(self._cache_key_for(requests[idx]), res)

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

        if not self._is_dirty and os.path.exists(file_path):
            self.logger.debug(f"Cache save skipped (not dirty): {file_path}")
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
                    tr_text = val.translated_text or ""
                    # Never persist corrupt translations containing placeholder remnants or unclosed tags
                    if _is_corrupt_or_protected_cache_text(text) or _is_corrupt_or_protected_cache_text(tr_text):
                        continue

                    if engine_str not in data:
                        data[engine_str] = {}

                    engine_dict = data[engine_str]
                    if sl not in engine_dict:
                        engine_dict[sl] = {}

                    sl_dict = engine_dict[sl]
                    if tl not in sl_dict:
                        sl_dict[tl] = {}

                    tl_dict = sl_dict[tl]
                    tl_dict[text] = tr_text
                except (ValueError, TypeError, KeyError):
                    continue

            # Dizini kontrol et
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            # Atomik Yazma: orjson / json fallback ile güvenli atomik kayıt
            from src.utils.encoding import save_json_safely
            success = save_json_safely(file_path, data, indent=2)
            if success:
                self._is_dirty = False
                self.logger.info(
                    f"Cache saved atomically: {file_path} ({len(self._cache)} entries)"
                )
            else:
                self.logger.error(f"Failed to save cache: {file_path}")
        except Exception as e:
            self.logger.error(f"Failed to save cache: {e}")

    def _backup_unreadable_cache(self, file_path: str) -> Optional[str]:
        try:
            if os.path.getsize(file_path) == 0:
                return None
            import shutil
            backup_path = f"{file_path}.{time.strftime('%Y%m%d-%H%M%S')}.bak"
            shutil.copy2(file_path, backup_path)
            self.logger.warning(f"Backed up unreadable cache to {backup_path}")
            return backup_path
        except Exception as exc:
            self.logger.warning(f"Could not back up unreadable cache {file_path}: {exc}")
            return None

    def load_cache(self, file_path: str):
        """Cache içeriğini diskten yükle."""
        if not self.use_cache or not os.path.exists(file_path):
            return

        try:
            from src.utils.encoding import read_json_safely
            data = read_json_safely(file_path)

            if not isinstance(data, dict):
                self.logger.warning(f"Invalid or unreadable cache file: {file_path}")
                # The next checkpoint would overwrite it with only this run's
                # entries; keep a copy so a lock/AV hiccup or a torn write
                # does not silently cost the user the whole project cache.
                self._backup_unreadable_cache(file_path)
                return

            count = 0
            # Init aşamasında concurrency olmadığı için lock gerekmez.
            # Doğrudan senkron olarak yükle.
            skipped_protected = 0
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
                            tr_str = str(translated) if translated is not None else ""
                            if _is_corrupt_or_protected_cache_text(text) or _is_corrupt_or_protected_cache_text(tr_str):
                                # Written by previous builds or corrupted outputs;
                                # drop it so clean fresh translations can be produced.
                                skipped_protected += 1
                                continue
                            key = (engine_str, sl, tl, text)
                            # Basit validasyon
                            engine_enum = TranslationEngine.GOOGLE
                            if engine_str in [e.value for e in TranslationEngine]:
                                engine_enum = TranslationEngine(engine_str)

                            res = TranslationResult(
                                original_text=text,
                                translated_text=tr_str,
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

            if skipped_protected:
                self.logger.info(
                    "Dropped %d corrupted or placeholder-leaked cache entries",
                    skipped_protected,
                )
            self._is_dirty = False
            self.logger.info(f"Cache loaded: {file_path} ({count} entries)")
        except Exception as e:
            self.logger.error(f"Failed to load cache: {e}")
