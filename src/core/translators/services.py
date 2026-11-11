# -*- coding: utf-8 -*-
"""
Additional translation engines: PseudoTranslator, DeepLTranslator, LibreTranslateTranslator.
"""
from __future__ import annotations

import asyncio
import aiohttp
import json
import logging
import os
import random
import re
import time
import urllib.parse
from typing import Dict, List, Optional, Tuple, Callable

from src.core.constants import USER_AGENTS, BING_EDGE_TRANSLATE_ENDPOINT
from src.core.exceptions import (
    RateLimitError,
    QuotaExceededError,
    NetworkConnectionError,
)
from src.core.syntax_guard import (
    protect_renpy_syntax,
    restore_renpy_syntax,
    validate_translation_integrity,
    inject_missing_placeholders,
)
from src.version import VERSION as _APP_VERSION
from .base import (
    IN_FALLBACK,
    BaseTranslator,
    TranslationEngine,
    TranslationRequest,
    TranslationResult,
)

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
        super().__init__(proxy_manager=proxy_manager, config_manager=config_manager)
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


# ─────────────────────────────────────────────────────────────────────────────
# BingTranslator — Microsoft Edge (Bing) keyless translation
# ─────────────────────────────────────────────────────────────────────────────

class BingTranslator(BaseTranslator):
    """
    Keyless Microsoft Translator via the Edge browser's web-translation endpoint.

    Contract (verified live 2026-09-21):
        POST https://edge.microsoft.com/translate/translatetext
             ?isEnterpriseClient=false&to=<lang>[&from=<lang>]&textType=html
        body: JSON array of strings
        resp: [{"translations": [{"text": "...", "to": "tr"}], "detectedLanguage": {...}}, ...]

    No token, cookie or API key is involved (the former `/translate/auth` JWT flow
    was retired by Microsoft in August 2026). Requests are sent as plain text
    with the pipeline's `⟦…⟧` placeholder tokens left raw: the service passes
    them through untouched, whereas HTML mode with `<span class="notranslate">`
    swallows neighbouring words into the span (verified live). Integrity is
    still validated and repaired after the call.
    The request family is fully independent from Google's, so this engine keeps
    working while Google's endpoints are IP-throttled; on hard failure it
    delegates the same (token-protected) requests to `fallback_translator`.
    """

    MAX_ITEMS_PER_REQUEST = 100      # observed: 120 items accepted; keep margin
    MAX_CHARS_PER_REQUEST = 40_000   # service rejects ~50k+ with HTTP 400
    MAX_RETRIES = 3
    RETRY_DELAYS = [2.0, 4.0, 8.0]
    CONCURRENT_CHUNKS = 3

    # RenLocalizer / ISO codes -> Microsoft Translator codes
    _LANG_MAP = {
        "zh": "zh-Hans", "zh-cn": "zh-Hans", "zh-hans": "zh-Hans",
        "zh-tw": "zh-Hant", "zh-hk": "zh-Hant", "zh-hant": "zh-Hant",
        "pt": "pt", "pt-br": "pt", "pt-pt": "pt-pt",
        "no": "nb", "nb": "nb",
        "sr": "sr-Cyrl", "sr-latn": "sr-Latn",
        "tl": "fil", "fil": "fil",
        "iw": "he", "he": "he",
        "jw": "jv", "jv": "jv",
        "mn": "mn-Cyrl",
        "tlh": "tlh-Latn",
    }

    def __init__(self, proxy_manager=None, config_manager=None, **kwargs):
        super().__init__(proxy_manager=proxy_manager, config_manager=config_manager)
        self.logger = logging.getLogger(__name__)
        self._engine = TranslationEngine.BING
        self.endpoint = kwargs.get("endpoint") or BING_EDGE_TRANSLATE_ENDPOINT
        self._chunk_semaphore: Optional[asyncio.Semaphore] = None
        # Fallback (Google) is for hard failures only; never for unchanged second opinions.
        self.fallback_for_unchanged_retry = False

    # ── helpers ──────────────────────────────────────────────────────────

    @classmethod
    def _map_lang(cls, lang: str) -> Optional[str]:
        raw = (lang or "").strip()
        if not raw or raw.lower() == "auto":
            return None
        return cls._LANG_MAP.get(raw.lower(), raw)

    def _build_url(self, src: Optional[str], tgt: str) -> str:
        params = {"isEnterpriseClient": "false", "to": tgt}
        if src:
            params["from"] = src
        return f"{self.endpoint}?{urllib.parse.urlencode(params)}"

    def _failed(self, req: TranslationRequest, error: str, quota: bool = False) -> TranslationResult:
        meta = req.metadata if isinstance(req.metadata, dict) else {}
        return TranslationResult(
            original_text=meta.get("original_text", req.text),
            translated_text="",
            source_lang=req.source_lang,
            target_lang=req.target_lang,
            engine=TranslationEngine.BING,
            success=False,
            error=error,
            quota_exceeded=quota,
            metadata=meta,
        )

    def _get_chunk_semaphore(self) -> asyncio.Semaphore:
        if self._chunk_semaphore is None:
            self._chunk_semaphore = asyncio.Semaphore(self.CONCURRENT_CHUNKS)
        return self._chunk_semaphore

    # ── public API ───────────────────────────────────────────────────────

    async def translate_single(self, request: TranslationRequest) -> TranslationResult:
        results = await self.translate_batch([request])
        return results[0] if results else self._failed(request, "Batch failed")

    async def translate_batch(
        self, requests: List[TranslationRequest]
    ) -> List[TranslationResult]:
        if not requests:
            return []

        src = self._map_lang(requests[0].source_lang)
        tgt = self._map_lang(requests[0].target_lang) or "en"

        # Prepare token-protected payload texts (plain text mode, raw ⟦…⟧ tokens)
        protected_texts: List[str] = []
        all_placeholders: List[Dict[str, str]] = []
        for req in requests:
            meta = req.metadata if isinstance(req.metadata, dict) else {}
            placeholders = meta.get("placeholders")
            if meta.get("preprotected") and isinstance(placeholders, dict):
                protected_text = req.text
            else:
                protected_text, placeholders = protect_renpy_syntax(req.text)
            protected_texts.append(protected_text)
            all_placeholders.append(placeholders)

        # Chunk by item count and character budget
        chunks: List[List[int]] = []
        cur: List[int] = []
        cur_chars = 0
        for i, t in enumerate(protected_texts):
            if cur and (len(cur) >= self.MAX_ITEMS_PER_REQUEST or cur_chars + len(t) > self.MAX_CHARS_PER_REQUEST):
                chunks.append(cur)
                cur, cur_chars = [], 0
            cur.append(i)
            cur_chars += len(t)
        if cur:
            chunks.append(cur)

        raw: List[Optional[str]] = [None] * len(requests)
        chunk_errors: Dict[int, Tuple[str, bool]] = {}  # request index -> (error, quota)

        async def run_chunk(indices: List[int]) -> None:
            async with self._get_chunk_semaphore():
                await self._translate_indices(indices, protected_texts, src, tgt, raw, chunk_errors)

        await asyncio.gather(*(run_chunk(c) for c in chunks))

        # Post-process: restore placeholders, validate integrity
        results: List[Optional[TranslationResult]] = [None] * len(requests)
        failed_indices: List[int] = []
        for i, req in enumerate(requests):
            translated = raw[i]
            if translated is None:
                failed_indices.append(i)
                continue
            placeholders = all_placeholders[i]
            meta = req.metadata if isinstance(req.metadata, dict) else {}
            restored = restore_renpy_syntax(translated.strip(), placeholders)
            missing = validate_translation_integrity(restored, placeholders)
            if missing:
                injected = inject_missing_placeholders(restored, protected_texts[i], placeholders, missing)
                if not validate_translation_integrity(injected, placeholders):
                    restored, missing = injected, []
            if missing:
                chunk_errors[i] = ("Placeholder integrity check failed", False)
                failed_indices.append(i)
                continue
            results[i] = TranslationResult(
                original_text=meta.get("original_text", req.text),
                translated_text=restored,
                source_lang=req.source_lang,
                target_lang=req.target_lang,
                engine=TranslationEngine.BING,
                success=True,
                confidence=0.9,
                metadata=meta,
            )

        # Hard failures: delegate to the fallback engine (same token scheme), else report
        if failed_indices:
            fallback = getattr(self, "fallback_translator", None) or getattr(self, "_fallback", None)
            fb_results: List[Optional[TranslationResult]] = [None] * len(failed_indices)
            if fallback is not None:
                first_err = chunk_errors.get(failed_indices[0], ("unknown", False))[0]
                self.emit_log("warning", self._get_text(
                    "log_bing_fallback",
                    "[Bing] {count} item(s) failed ({reason}); delegating to fallback engine.",
                    count=len(failed_indices), reason=first_err,
                ))
                token = IN_FALLBACK.set(True)
                try:
                    fb_out = await fallback.translate_batch([requests[i] for i in failed_indices])
                    if fb_out and len(fb_out) == len(failed_indices):
                        fb_results = list(fb_out)
                except Exception as exc:
                    self.logger.warning("Bing fallback translator failed: %s", exc)
                finally:
                    IN_FALLBACK.reset(token)
            fb_engine = getattr(getattr(fallback, "_engine", None), "value", "fallback")
            for pos, i in enumerate(failed_indices):
                fb = fb_results[pos]
                if fb is not None and fb.success and (fb.translated_text or "").strip():
                    meta = dict(requests[i].metadata) if isinstance(requests[i].metadata, dict) else {}
                    meta["fallback_engine"] = fb_engine
                    results[i] = TranslationResult(
                        original_text=fb.original_text,
                        translated_text=fb.translated_text,
                        source_lang=requests[i].source_lang,
                        target_lang=requests[i].target_lang,
                        engine=TranslationEngine.BING,
                        success=True,
                        confidence=getattr(fb, "confidence", 0.0),
                        metadata=meta,
                    )
                else:
                    err, quota = chunk_errors.get(i, ("Bing translation failed", False))
                    results[i] = self._failed(requests[i], err, quota)

        return results  # type: ignore[return-value]

    async def _translate_indices(
        self,
        indices: List[int],
        texts: List[str],
        src: Optional[str],
        tgt: str,
        raw: List[Optional[str]],
        chunk_errors: Dict[int, Tuple[str, bool]],
    ) -> None:
        """Translates one chunk in place; splits on size errors, retries on 429/network."""
        payload = [texts[i] for i in indices]
        url = self._build_url(src, tgt)
        last_error = "Unknown error"
        quota = False

        for attempt in range(self.MAX_RETRIES):
            if self.should_stop_callback and self.should_stop_callback():
                last_error = "Stopped by user"
                break
            try:
                session = await self._get_session()
                proxy = None
                if self.use_proxy and self.proxy_manager:
                    p = self.proxy_manager.get_next_proxy()
                    if p:
                        proxy = p.url
                headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": random.choice(USER_AGENTS),
                    "Origin": "https://www.bing.com",
                    "Referer": "https://www.bing.com/",
                }
                async with session.post(
                    url,
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers=headers,
                    proxy=proxy,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        if isinstance(data, str):
                            data = json.loads(data)
                        if not isinstance(data, list) or len(data) != len(indices):
                            last_error = "Unexpected response shape"
                            break
                        for pos, item in enumerate(data):
                            try:
                                raw[indices[pos]] = item["translations"][0]["text"]
                            except (KeyError, IndexError, TypeError):
                                chunk_errors[indices[pos]] = ("Missing translation in response", False)
                        return

                    body = (await resp.text())[:200]
                    if resp.status == 429:
                        quota = True
                        last_error = "Rate limit exceeded (HTTP 429)"
                        if attempt < self.MAX_RETRIES - 1:
                            await asyncio.sleep(self.RETRY_DELAYS[attempt])
                            continue
                        rl = RateLimitError("Bing rate limit exceeded (HTTP 429)", code=429)
                        self.emit_log("warning", rl.get_user_friendly_message())
                        break
                    if resp.status == 400 and "maximum allowed translation size" in body.lower() and len(indices) > 1:
                        # Split and retry both halves (also covers oversized single lines gracefully)
                        mid = len(indices) // 2
                        await self._translate_indices(indices[:mid], texts, src, tgt, raw, chunk_errors)
                        await self._translate_indices(indices[mid:], texts, src, tgt, raw, chunk_errors)
                        return
                    if resp.status in (400, 401, 403, 404):
                        # Unsupported language / contract change / blocked — no point retrying
                        last_error = f"HTTP {resp.status}: {body or 'request rejected'}"
                        break
                    last_error = f"HTTP {resp.status}: {body}"
                    if attempt < self.MAX_RETRIES - 1:
                        await asyncio.sleep(self.RETRY_DELAYS[attempt])
                        continue
                    break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = f"Connection/Request Error: {exc}"
                if self.note_tls_error(exc):
                    break  # retrying cannot fix a missing CA store
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(self.RETRY_DELAYS[attempt])
                    continue
                break

        self.logger.warning("Bing chunk of %d items failed: %s", len(indices), last_error)
        for i in indices:
            if raw[i] is None:
                chunk_errors[i] = (last_error, quota)

    def get_supported_languages(self) -> Dict[str, str]:
        return {
            "en": "English", "tr": "Turkish", "de": "German", "fr": "French",
            "es": "Spanish", "it": "Italian", "pt": "Portuguese", "ru": "Russian",
            "uk": "Ukrainian", "pl": "Polish", "cs": "Czech", "nl": "Dutch",
            "sv": "Swedish", "da": "Danish", "fi": "Finnish", "nb": "Norwegian",
            "hu": "Hungarian", "ro": "Romanian", "bg": "Bulgarian", "el": "Greek",
            "ja": "Japanese", "ko": "Korean", "zh-Hans": "Chinese (Simplified)",
            "zh-Hant": "Chinese (Traditional)", "vi": "Vietnamese", "th": "Thai",
            "id": "Indonesian", "ms": "Malay", "fil": "Filipino", "hi": "Hindi",
            "bn": "Bengali", "ar": "Arabic", "fa": "Persian", "he": "Hebrew",
            "az": "Azerbaijani", "kk": "Kazakh", "uz": "Uzbek", "ka": "Georgian",
            "hy": "Armenian", "sr-Cyrl": "Serbian", "hr": "Croatian", "sk": "Slovak",
            "sl": "Slovenian", "lt": "Lithuanian", "lv": "Latvian", "et": "Estonian",
        }
