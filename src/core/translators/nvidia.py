# -*- coding: utf-8 -*-
"""
NvidiaTranslator: NVIDIA Riva-Translate through the free NVIDIA API Catalog.

Contract (verified live 2026-11-08 with a personal ``nvapi-`` key):

    POST https://integrate.api.nvidia.com/v1/chat/completions
    system message = language pair ("en-tr"), user message = the text
    -> choices[0].message.content = the translation, nothing else

Findings that shaped this module (measured, not assumed):

* The pipeline's ``⟦RLPH…⟧`` placeholder tokens survive untouched (the XML
  ``<ph>`` scheme does not), so this engine uses the same token mode as
  Google/Bing.
* Riva is a pure translation model: a free-form instruction as the system
  message breaks it (it answers in random languages). Only ``xx-yy`` works.
* A text with real line breaks is merged into one line, so such a text is split
  per line and rejoined here.
* The free tier allows ~40 requests/minute, so single-line requests would take
  hours. Several lines can share one request as numbered tags (``<s0>…</s0>``):
  up to ~30 lines kept their order and tokens, 80+ lines got lost or merged.
  The number that works varies run to run, so ``AdaptiveBatchSizer`` finds it
  while translating (additive increase, multiplicative decrease) instead of
  hard-coding one.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import Counter, deque
from typing import Callable, Dict, List, Optional, Tuple

import aiohttp

from src.core.constants import NVIDIA_API_BASE_URL, NVIDIA_DEFAULT_MODEL
from src.core.syntax_guard import (
    protect_renpy_syntax,
    restore_renpy_syntax,
    validate_translation_integrity,
    inject_missing_placeholders,
)
from .base import (
    IN_FALLBACK,
    BaseTranslator,
    TranslationEngine,
    TranslationRequest,
    TranslationResult,
)

# Several lines share one request as ``<s0>text</s0> <s1>text</s1> ...``. A plain
# separator (" ||| ") lost lines whenever the model read one fragment as the
# continuation of the previous one ("Changing person" + "to '" -> one line); with
# numbered tags a missing line is identified, so only that line is asked again.
# Measured on a real game's strings: tags recovered 120/120 lines, the separator
# kept the right count in only 4 of 8 groups.
_TAG_RE = re.compile(r"<s(\d+)>(.*?)</s\1>", re.S)
_TAG_LIKE_RE = re.compile(r"</?s\d+>")
_TOKEN_RE = re.compile(r"⟦[^⟧]*⟧")

# Riva-Translate-4B-Instruct-v2 language codes (model card, 37 languages).
_RIVA_CODES = (
    "en", "cs", "da", "de", "el", "es-ES", "es-US", "fi", "fr", "hu", "it", "lt",
    "lv", "nl", "no", "pl", "pt-PT", "pt-BR", "ro", "ru", "sk", "sv", "zh-CN",
    "zh-TW", "ja", "hi", "ko", "et", "sl", "bg", "uk", "hr", "ar", "vi", "tr",
    "id", "th",
)
_RIVA_BY_LOWER = {c.lower(): c for c in _RIVA_CODES}
_RIVA_ALIASES = {
    "es": "es-ES", "pt": "pt-BR", "zh": "zh-CN", "zh-hans": "zh-CN",
    "zh-hant": "zh-TW", "zh-hk": "zh-TW", "nb": "no", "nn": "no",
}


def riva_language_code(lang: str, *, default: Optional[str] = None) -> Optional[str]:
    """Map an app/ISO language code to the Riva code, or ``default`` if unsupported."""
    raw = (lang or "").strip().replace("_", "-").lower()
    if not raw or raw == "auto":
        return default
    if raw in _RIVA_BY_LOWER:
        return _RIVA_BY_LOWER[raw]
    if raw in _RIVA_ALIASES:
        return _RIVA_ALIASES[raw]
    primary = raw.split("-")[0]
    return _RIVA_BY_LOWER.get(primary) or _RIVA_ALIASES.get(primary) or default


class AdaptiveBatchSizer:
    """Finds how many lines one request can carry, while translating.

    A bad request (wrong number of parts, or more than ``tolerated_bad_ratio`` of
    its lines lost a token) does not shrink the size by itself: one odd line can
    spoil any group it lands in, and the translator already recovers that group by
    splitting it. Only a second bad request among the last ``window`` ones shrinks
    the size (to 70 %). ``grow_after`` clean full-size requests in a row grow it by
    ``grow_step``.

    Requests smaller than the current size (a short tail, a retry half) carry no
    information about whether the size could grow, so they never grow it.
    """

    def __init__(
        self,
        start: int = 15,
        minimum: int = 4,
        maximum: int = 30,
        grow_after: int = 3,
        grow_step: int = 3,
        tolerated_bad_ratio: float = 0.10,
        window: int = 6,
    ) -> None:
        self.minimum = max(1, int(minimum))
        self.maximum = max(self.minimum, int(maximum))
        self.size = max(self.minimum, min(self.maximum, int(start)))
        self.grow_after = max(1, int(grow_after))
        self.grow_step = max(1, int(grow_step))
        self.tolerated_bad_ratio = tolerated_bad_ratio
        self._recent: deque = deque(maxlen=max(2, int(window)))
        self._clean_streak = 0

    def record(self, lines: int, count_ok: bool, bad_lines: int = 0) -> int:
        """Feed one finished multi-line request; returns the new size."""
        if lines < 2:
            return self.size
        problem = (not count_ok) or (bad_lines / lines > self.tolerated_bad_ratio)
        self._recent.append(problem)
        if problem:
            self._clean_streak = 0
            if sum(self._recent) >= 2:
                self.size = max(self.minimum, int(self.size * 0.7))
                self._recent.clear()
        elif bad_lines:
            self._clean_streak = 0
        elif lines >= self.size:
            self._clean_streak += 1
            if self._clean_streak >= self.grow_after:
                self.size = min(self.maximum, self.size + self.grow_step)
                self._clean_streak = 0
        return self.size


class RateLimiter:
    """Spaces requests evenly (``60 / rpm`` seconds apart) instead of allowing bursts.

    The free tier rejected a burst of ~30 requests with 429 even though the
    per-minute total was within the limit, and a sliding window then stalled for
    most of a minute. Even spacing never bursts. ``slow_down()`` widens the
    spacing after a 429; ``back_off()`` pauses every waiting caller at once.
    """

    def __init__(
        self,
        rpm: int = 35,
        floor: int = 10,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], "asyncio.Future"] = asyncio.sleep,
    ) -> None:
        self.rpm = max(1, int(rpm))
        self.floor = max(1, int(floor))
        self._clock = clock
        self._sleep = sleep
        self._next_slot = 0.0

    async def acquire(self) -> None:
        # No await between reading and writing _next_slot, so concurrent callers
        # each get their own slot.
        now = self._clock()
        start = max(now, self._next_slot)
        self._next_slot = start + 60.0 / self.rpm
        wait = start - now
        if wait > 0:
            await self._sleep(wait)

    def slow_down(self) -> None:
        self.rpm = max(self.floor, int(self.rpm * 0.8))

    def back_off(self, seconds: float) -> None:
        self._next_slot = max(self._next_slot, self._clock() + max(0.0, seconds))


def _tokens_intact(source: str, output: str) -> bool:
    return Counter(_TOKEN_RE.findall(source)) == Counter(_TOKEN_RE.findall(output))


class NvidiaTranslator(BaseTranslator):
    """Riva-Translate via the NVIDIA API Catalog, with adaptive multi-line requests."""

    MAX_CHARS_PER_REQUEST = 3500     # long lines drift more; cap the characters too
    MAX_RETRIES = 3
    RETRY_DELAYS = [5.0, 10.0, 20.0]
    REQUEST_TIMEOUT = 75             # a normal 20-line request takes 5-10 s
    CONCURRENT_REQUESTS = 3
    REQUESTS_PER_MINUTE = 35         # free tier is ~40; keep a margin

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        proxy_manager=None,
        config_manager=None,
        **kwargs,
    ):
        super().__init__(api_key=(api_key or "").strip(), proxy_manager=proxy_manager,
                         config_manager=config_manager)
        self.logger = logging.getLogger(__name__)
        self._engine = TranslationEngine.NVIDIA
        self.model = (model or NVIDIA_DEFAULT_MODEL).strip()
        self.base_url = (base_url or NVIDIA_API_BASE_URL).rstrip("/")
        self.sizer = AdaptiveBatchSizer(
            start=kwargs.get("start_batch", 15), minimum=kwargs.get("min_batch", 4),
            maximum=kwargs.get("max_batch", 30),
        )
        self.limiter = RateLimiter(rpm=kwargs.get("rpm", self.REQUESTS_PER_MINUTE))
        self._semaphore: Optional[asyncio.Semaphore] = None
        # Fallback (Google) is for hard failures only, never for unchanged second opinions.
        self.fallback_for_unchanged_retry = False
        self._auth_error = ""  # set once the key is rejected (HTTP 401/403)
        self.sleep = asyncio.sleep  # replaced in tests

    # ── helpers ──────────────────────────────────────────────────────────

    def _get_semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.CONCURRENT_REQUESTS)
        return self._semaphore

    def _failed(self, req: TranslationRequest, error: str, quota: bool = False) -> TranslationResult:
        meta = req.metadata if isinstance(req.metadata, dict) else {}
        return TranslationResult(
            original_text=meta.get("original_text", req.text),
            translated_text="",
            source_lang=req.source_lang,
            target_lang=req.target_lang,
            engine=TranslationEngine.NVIDIA,
            success=False,
            error=error,
            quota_exceeded=quota,
            metadata=meta,
        )

    STOP_POLL_SECONDS = 0.2

    def _stop_requested(self) -> bool:
        return bool(self.should_stop_callback and self.should_stop_callback())

    async def probe_endpoint(self) -> Optional[str]:
        """None when usable, else a short reason (checked before a run starts)."""
        if not self.api_key:
            return "no NVIDIA API key set (get a free one at build.nvidia.com)"
        # GET /models answers 200 without a key and with a made-up one (checked
        # live 2026-11-11), so only a real completion tells whether the key works.
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "en-de"},
                {"role": "user", "content": "Hi"},
            ],
            "temperature": 0,
            "max_tokens": 8,
        }
        try:
            await self.limiter.acquire()
            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/chat/completions",
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                proxy=self._proxy_url(),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status in (401, 403):
                    return f"the NVIDIA API key was rejected (HTTP {resp.status})"
                if resp.status == 404:
                    return f"the model '{self.model}' was not found (HTTP 404)"
                # 429 / 5xx: the key was accepted or the service is busy; the
                # run's own retry and fallback handling deals with those.
                return None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return f"cannot connect to {self.base_url} ({exc.__class__.__name__})"

    async def _call(self, system: str, text: str) -> Tuple[Optional[str], str, bool]:
        """One chat completion. Returns (content, error, quota_exhausted)."""
        if not self.api_key:
            return None, "No NVIDIA API key set", False
        if self._auth_error:
            return None, self._auth_error, False
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            "temperature": 0,
            "max_tokens": min(4096, max(256, int(len(text) * 1.2) + 64)),
        }
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        url = f"{self.base_url}/chat/completions"
        last_error = "Unknown error"
        quota = False
        for attempt in range(self.MAX_RETRIES):
            if self.should_stop_callback and self.should_stop_callback():
                return None, "Stopped by user", False
            await self.limiter.acquire()
            started = time.monotonic()
            try:
                session = await self._get_session()
                async with session.post(
                    url, data=payload, headers=headers, proxy=self._proxy_url(),
                    timeout=aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        try:
                            content = data["choices"][0]["message"]["content"]
                        except (KeyError, IndexError, TypeError):
                            return None, "Unexpected response shape", False
                        self.emit_log(
                            "debug",
                            f"[NVIDIA] {max(1, len(_TAG_RE.findall(text)))} line(s), {len(text)} -> "
                            f"{len(content or '')} chars in {time.monotonic() - started:.1f}s "
                            f"(batch size {self.sizer.size}, {self.limiter.rpm} req/min)",
                        )
                        return (content or ""), "", False
                    detail = (await resp.text())[:200]
                    if resp.status == 429:
                        quota = True
                        last_error = "Rate limit exceeded (HTTP 429)"
                        self.limiter.slow_down()
                        self.emit_log("warning", f"[NVIDIA] HTTP 429 after {time.monotonic() - started:.1f}s; "
                                                 f"limit lowered to {self.limiter.rpm} req/min.")
                        delay = self.RETRY_DELAYS[min(attempt, len(self.RETRY_DELAYS) - 1)]
                        try:
                            delay = max(delay, float(resp.headers.get("Retry-After", 0)))
                        except (TypeError, ValueError):
                            pass
                        if attempt < self.MAX_RETRIES - 1:
                            # Every waiting request pauses, not just this one.
                            self.limiter.back_off(delay)
                            continue
                        return None, last_error, True
                    if resp.status in (401, 403):
                        # A rejected key fails every line: stop asking, and never
                        # let Google translate the run in this engine's name.
                        self._auth_error = f"the NVIDIA API key was rejected (HTTP {resp.status})"
                        self.emit_log("error", f"[NVIDIA] {self._auth_error}; nothing more is sent "
                                               "and the Google fallback is not used.")
                        return None, self._auth_error, False
                    if resp.status in (400, 404):
                        return None, f"HTTP {resp.status}: {detail or 'request rejected'}", False
                    last_error = f"HTTP {resp.status}: {detail}"
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = f"Connection/Request Error: {exc.__class__.__name__}: {exc}"
                self.emit_log("warning", f"[NVIDIA] request failed after {time.monotonic() - started:.1f}s "
                                         f"({exc.__class__.__name__}); attempt {attempt + 1}/{self.MAX_RETRIES}.")
                if self.note_tls_error(exc):
                    return None, last_error, False
            if attempt < self.MAX_RETRIES - 1:
                await self.sleep(self.RETRY_DELAYS[min(attempt, len(self.RETRY_DELAYS) - 1)])
        return None, last_error, quota

    # ── translation core ─────────────────────────────────────────────────

    async def _single(self, u: int, texts: List[str], system: str,
                      raw: List[Optional[str]], errors: Dict[int, Tuple[str, bool]]) -> None:
        async with self._get_semaphore():
            content, err, quota = await self._call(system, texts[u])
        if content is None or not content.strip():
            errors[u] = (err or "Empty response", quota)
            return
        raw[u] = content.strip()

    async def _run_group(self, units: List[int], texts: List[str], system: str,
                         raw: List[Optional[str]], errors: Dict[int, Tuple[str, bool]]) -> None:
        if len(units) == 1:
            await self._single(units[0], texts, system, raw, errors)
            return
        payload = " ".join(f"<s{k}>{texts[u]}</s{k}>" for k, u in enumerate(units))
        async with self._get_semaphore():
            content, err, quota = await self._call(system, payload)
        if content is None:
            for u in units:
                errors[u] = (err, quota)
            return
        found = {int(k): v.strip() for k, v in _TAG_RE.findall(content)}
        if not found:
            # Nothing usable came back (the model dropped the tags altogether):
            # split the group and try the halves.
            before = self.sizer.size
            self.sizer.record(len(units), False)
            self.emit_log(
                "info",
                f"[NVIDIA] reply for {len(units)} lines had no usable tags; "
                f"splitting (batch size {before} -> {self.sizer.size}).",
            )
            mid = len(units) // 2
            await asyncio.gather(
                self._run_group(units[:mid], texts, system, raw, errors),
                self._run_group(units[mid:], texts, system, raw, errors),
            )
            return
        bad: List[int] = []
        for k, u in enumerate(units):
            part = found.get(k, "")
            if part and _tokens_intact(texts[u], part):
                raw[u] = part
            else:
                bad.append(u)
        before = self.sizer.size
        self.sizer.record(len(units), True, len(bad))
        if self.sizer.size != before:
            self.emit_log("info", f"[NVIDIA] adaptive batch size {before} -> {self.sizer.size}.")
        # A line that is missing or lost a token is asked again on its own: with no
        # neighbours the model has nothing to merge or shift.
        for u in bad:
            await self._single(u, texts, system, raw, errors)

    def _build_groups(self, units: List[int], texts: List[str]) -> List[List[int]]:
        groups: List[List[int]] = []
        cur: List[int] = []
        chars = 0
        size = self.sizer.size
        for u in units:
            t = texts[u]
            if _TAG_LIKE_RE.search(t):  # would be mistaken for our own markers
                groups.append([u])
                continue
            if cur and (len(cur) >= size or chars + len(t) > self.MAX_CHARS_PER_REQUEST):
                groups.append(cur)
                cur, chars = [], 0
            cur.append(u)
            chars += len(t)
        if cur:
            groups.append(cur)
        return groups

    async def translate_single(self, request: TranslationRequest) -> TranslationResult:
        results = await self.translate_batch([request])
        return results[0] if results else self._failed(request, "Batch failed")

    async def translate_batch(self, requests: List[TranslationRequest]) -> List[TranslationResult]:
        if not requests:
            return []

        src = riva_language_code(requests[0].source_lang, default="en")
        tgt = riva_language_code(requests[0].target_lang)
        if tgt is None:
            msg = f"Riva-Translate does not support target language '{requests[0].target_lang}'"
            return await self._delegate_all(requests, msg)
        system = f"{src}-{tgt}"

        protected: List[str] = []
        placeholders: List[Dict[str, str]] = []
        for req in requests:
            meta = req.metadata if isinstance(req.metadata, dict) else {}
            ph = meta.get("placeholders")
            if meta.get("preprotected") and isinstance(ph, dict):
                text = req.text
            else:
                text, ph = protect_renpy_syntax(req.text)
            protected.append(text)
            placeholders.append(ph)

        # Riva merges a text's line breaks into one line, so translate per line.
        unit_texts: List[str] = []
        unit_owner: List[Tuple[int, int]] = []
        segments: List[List[str]] = []
        for i, text in enumerate(protected):
            segs = text.split("\n")
            segments.append(segs)
            for j, seg in enumerate(segs):
                if seg.strip():
                    unit_owner.append((i, j))
                    unit_texts.append(seg.strip())

        raw_units: List[Optional[str]] = [None] * len(unit_texts)
        errors: Dict[int, Tuple[str, bool]] = {}
        pending = list(range(len(unit_texts)))
        while pending:
            # Re-read the size per wave so growth/shrink applies to the rest of this step.
            groups = self._build_groups(pending[: max(self.sizer.size * 6, 1)], unit_texts)
            consumed = sum(len(g) for g in groups)
            wave = asyncio.ensure_future(asyncio.gather(
                *(self._run_group(g, unit_texts, system, raw_units, errors) for g in groups)
            ))
            # Poll the stop flag while requests are in flight: cancelling the wave
            # aborts the open HTTP calls at once instead of waiting up to REQUEST_TIMEOUT.
            try:
                while not wave.done():
                    await asyncio.wait({wave}, timeout=self.STOP_POLL_SECONDS)
                    if not wave.done() and self._stop_requested():
                        break
                else:
                    wave.result()
            finally:
                # Also reached when this coroutine itself is cancelled
                # (TranslationManager polls the same stop flag and usually wins):
                # asyncio.wait() does not cancel what it waits for, so without
                # this the open requests kept running after Stop.
                if not wave.done():
                    wave.cancel()
                    try:
                        await wave
                    except BaseException:
                        pass
            pending = pending[consumed:]
            if self._stop_requested():
                break

        if self._stop_requested():
            # No fallback engine, no further work: the user asked to stop.
            return [self._failed(r, "Stopped by user") for r in requests]

        by_request: Dict[int, Dict[int, str]] = {}
        failed_unit: Dict[int, Tuple[str, bool]] = {}
        for u, (i, j) in enumerate(unit_owner):
            if raw_units[u] is None:
                failed_unit.setdefault(i, errors.get(u, ("Translation missing", False)))
            else:
                by_request.setdefault(i, {})[j] = raw_units[u]

        results: List[Optional[TranslationResult]] = [None] * len(requests)
        failed: List[int] = []
        chunk_errors: Dict[int, Tuple[str, bool]] = {}
        for i, req in enumerate(requests):
            if i in failed_unit:
                chunk_errors[i] = failed_unit[i]
                failed.append(i)
                continue
            lines = []
            for j, seg in enumerate(segments[i]):
                if j in by_request.get(i, {}):
                    lead = seg[: len(seg) - len(seg.lstrip())]
                    trail = seg[len(seg.rstrip()):]
                    lines.append(lead + by_request[i][j] + trail)
                else:
                    lines.append(seg)
            translated = "\n".join(lines)
            ph = placeholders[i]
            meta = req.metadata if isinstance(req.metadata, dict) else {}
            restored = restore_renpy_syntax(translated, ph)
            missing = validate_translation_integrity(restored, ph)
            if missing:
                injected = inject_missing_placeholders(restored, protected[i], ph, missing)
                if not validate_translation_integrity(injected, ph):
                    restored, missing = injected, []
            if missing:
                chunk_errors[i] = ("Placeholder integrity check failed", False)
                failed.append(i)
                continue
            results[i] = TranslationResult(
                original_text=meta.get("original_text", req.text),
                translated_text=restored,
                source_lang=req.source_lang,
                target_lang=req.target_lang,
                engine=TranslationEngine.NVIDIA,
                success=True,
                confidence=0.9,
                metadata=meta,
            )

        if failed:
            await self._fill_from_fallback(requests, results, failed, chunk_errors)
        return results  # type: ignore[return-value]

    async def _delegate_all(self, requests: List[TranslationRequest], reason: str) -> List[TranslationResult]:
        results: List[Optional[TranslationResult]] = [None] * len(requests)
        idx = list(range(len(requests)))
        await self._fill_from_fallback(requests, results, idx, {i: (reason, False) for i in idx})
        return results  # type: ignore[return-value]

    async def _fill_from_fallback(self, requests, results, failed, chunk_errors) -> None:
        fallback = getattr(self, "fallback_translator", None) or getattr(self, "_fallback", None)
        fb_results: List[Optional[TranslationResult]] = [None] * len(failed)
        if fallback is not None and not IN_FALLBACK.get() and not self._auth_error:
            first_err = chunk_errors.get(failed[0], ("unknown", False))[0]
            self.emit_log("warning", f"[NVIDIA] {len(failed)} item(s) failed ({first_err}); "
                                     "delegating to fallback engine.")
            token = IN_FALLBACK.set(True)
            try:
                out = await fallback.translate_batch([requests[i] for i in failed])
                if out and len(out) == len(failed):
                    fb_results = list(out)
            except Exception as exc:
                self.logger.warning("NVIDIA fallback translator failed: %s", exc)
            finally:
                IN_FALLBACK.reset(token)
        fb_engine = getattr(getattr(fallback, "_engine", None), "value", "fallback")
        for pos, i in enumerate(failed):
            fb = fb_results[pos]
            if fb is not None and fb.success and (fb.translated_text or "").strip():
                meta = dict(requests[i].metadata) if isinstance(requests[i].metadata, dict) else {}
                meta["fallback_engine"] = fb_engine
                results[i] = TranslationResult(
                    original_text=fb.original_text,
                    translated_text=fb.translated_text,
                    source_lang=requests[i].source_lang,
                    target_lang=requests[i].target_lang,
                    engine=TranslationEngine.NVIDIA,
                    success=True,
                    confidence=getattr(fb, "confidence", 0.0),
                    metadata=meta,
                )
            else:
                err, quota = chunk_errors.get(i, ("NVIDIA translation failed", False))
                results[i] = self._failed(requests[i], err, quota)

    def get_supported_languages(self) -> Dict[str, str]:
        return {c: c for c in _RIVA_CODES}
