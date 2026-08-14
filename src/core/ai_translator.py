# -*- coding: utf-8 -*-
"""
AI Translator Implementations for RenLocalizer.
=====================================================

Supports OpenAI, DeepSeek (OpenAI-compatible), Local LLM (Ollama/LM Studio) and Gemini.

All engines share a common base that handles:
  - XML-based batch segmentation (token-efficient)
  - Exponential backoff with jitter
  - quota_exceeded flag propagation
  - Safety filter / content policy graceful recovery (return original text)
  - Conditional import guard (if openai not installed, engines raise ImportError)
"""
from __future__ import annotations

import asyncio
import random
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

from src.core.translator import (
    BaseTranslator,
    TranslationEngine,
    TranslationRequest,
    TranslationResult,
)
from src.core.syntax_guard import (
    protect_renpy_syntax,
    restore_renpy_syntax,
    validate_translation_integrity,
    inject_missing_placeholders,
)
from src.utils.constants import (
    AI_DEFAULT_TEMPERATURE,
    AI_DEFAULT_TIMEOUT,
    AI_LOCAL_TIMEOUT,
    AI_DEFAULT_MAX_TOKENS,
    AI_MAX_RETRIES,
    AI_LOCAL_URL,
)

# ── Optional dependency guard ─────────────────────────────────────────────────
try:
    from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False

try:
    import google.genai as genai
    _GEMINI_AVAILABLE = True
except ImportError:
    try:
        import google.generativeai as genai
        _GEMINI_AVAILABLE = True
    except ImportError:
        _GEMINI_AVAILABLE = False
        genai = None  # type: ignore

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_XML_ITEM_RE = re.compile(r'<item\s+id="(\d+)">(.*?)</item>', re.DOTALL)

_SUPPORTED_LANGUAGES: Dict[str, str] = {
    "auto": "Auto-detect",
    "en": "English", "tr": "Turkish", "de": "German", "fr": "French",
    "es": "Spanish", "it": "Italian", "pt": "Portuguese", "ru": "Russian",
    "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "ar": "Arabic",
    "pl": "Polish", "nl": "Dutch", "sv": "Swedish", "no": "Norwegian",
    "da": "Danish", "fi": "Finnish", "hu": "Hungarian", "cs": "Czech",
    "ro": "Romanian", "uk": "Ukrainian", "vi": "Vietnamese", "th": "Thai",
}


# ─────────────────────────────────────────────────────────────────────────────
# Model Profiles — family-specific prompting/sampling.
#
# "hy_mt2": Tencent Hy-MT / Hunyuan-MT translation models (1.8B / 7B / 30B-A3B,
# GGUF or otherwise). Translation-specialized models trained on short user-role
# instructions; the authors state the models have NO default system prompt.
# Official instruction templates and sampling recipe come from the model card:
# https://huggingface.co/tencent/Hy-MT2-7B-GGUF
# ─────────────────────────────────────────────────────────────────────────────

_HY_MT2_RE = re.compile(r"(?:hy|hunyuan)[-_ ]?mt", re.IGNORECASE)


def detect_model_profile(model_name: Optional[str]) -> Optional[str]:
    """Return "hy_mt2" when the model name belongs to the Hy-MT family, else None.

    Matches: "Hy-MT2-7B-GGUF", "hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M",
             "tencent/Hy-MT1.5-1.8B", "hunyuan-mt-7b", "hy_mt2", "Hy MT2".
    Does NOT match: "llama3.2", "gpt-4o-mini", "mistral-7b", "qwen2-mt-7b"
    (different "-mt" family).
    """
    if not model_name:
        return None
    return "hy_mt2" if _HY_MT2_RE.search(model_name) else None


# Hy-MT2 supports 33 languages; supplement _SUPPORTED_LANGUAGES (which drives
# UI dropdowns and must stay unchanged) with the remaining codes for prompts.
_HY_MT2_EXTRA_LANGUAGES: Dict[str, str] = {
    "he": "Hebrew", "hi": "Hindi", "bn": "Bengali", "fa": "Persian",
    "fil": "Filipino", "ms": "Malay", "id": "Indonesian",
    "ta": "Tamil", "te": "Telugu", "ur": "Urdu", "my": "Burmese",
    "km": "Khmer", "lo": "Lao", "mn": "Mongolian", "kk": "Kazakh",
    "ug": "Uyghur", "bo": "Tibetan",
    "zh-CN": "Chinese", "zh-TW": "Traditional Chinese", "yue": "Cantonese",
}


def _resolve_language_name(code: Optional[str]) -> str:
    """Map a language code to its full English name for Hy-MT2 prompts.

    Hy-MT2 instructions expect full language names, not codes.
    """
    if not code or code == "auto":
        return "the original language"
    name = _SUPPORTED_LANGUAGES.get(code)
    if name and name != "Auto-detect":
        return name
    name = _HY_MT2_EXTRA_LANGUAGES.get(code)
    if name:
        return name
    return code  # Last resort: pass the raw code through


def resolve_model_profile(config_manager, model_name: Optional[str]) -> Optional[str]:
    """Resolve the effective model profile from config + autodetection.

    config.translation_settings.ai_model_profile:
      "auto"    -> detect from model_name
      "generic" -> force no profile
      "hy_mt2"  -> force the Hy-MT2 profile
    """
    cfg_profile = "auto"
    if config_manager and hasattr(config_manager, "translation_settings"):
        cfg_profile = (
            getattr(config_manager.translation_settings, "ai_model_profile", "auto")
            or "auto"
        )
    cfg_profile = str(cfg_profile).strip().lower()
    if cfg_profile == "generic":
        return None
    if cfg_profile == "hy_mt2":
        return "hy_mt2"
    return detect_model_profile(model_name)


def _build_xml_batch(texts: List[str]) -> str:
    """Wraps texts in an XML structure for token-efficient batching."""
    parts = ["<translations>"]
    for i, text in enumerate(texts):
        # Escape special XML chars
        safe = (
            text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
        )
        parts.append(f'  <item id="{i}">{safe}</item>')
    parts.append("</translations>")
    return "\n".join(parts)


import json

AI_BATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "translated_text": {"type": "string"}
                },
                "required": ["id", "translated_text"]
            }
        }
    },
    "required": ["translations"]
}


def _build_json_batch(texts: List[str]) -> str:
    """Wraps texts in a JSON structure matching the schema."""
    items = []
    for i, text in enumerate(texts):
        items.append({"id": i, "text": text})
    return json.dumps({"items_to_translate": items}, ensure_ascii=False)


def _parse_json_batch(json_text: str, count: int) -> List[Optional[str]]:
    """Parses structured JSON response from the model. Returns list of strings."""
    results: List[Optional[str]] = [None] * count
    try:
        clean_text = json_text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        if clean_text.startswith("```"):
            clean_text = clean_text[3:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
        clean_text = clean_text.strip()

        data = json.loads(clean_text)
        translations = data.get("translations", [])
        for item in translations:
            idx = item.get("id")
            val = item.get("translated_text")
            if idx is not None and val is not None:
                results[int(idx)] = val
    except Exception:
        pass
    return results


def _recover_placeholders_levenshtein(source_text: str, translated_text: str, placeholders: Dict[str, str]) -> str:
    """
    Attempts to recover missing placeholders in translated_text by aligning them
    relative to their neighbor words (anchors) in source_text using Levenshtein distance.
    """
    if not placeholders:
        return translated_text

    src_words = source_text.split()
    tr_words = translated_text.split()

    if not tr_words:
        return translated_text

    def edit_distance(s1: str, s2: str) -> int:
        if len(s1) > len(s2):
            s1, s2 = s2, s1
        distances = list(range(len(s1) + 1))
        for i2, c2 in enumerate(s2):
            distances_ = [i2 + 1]
            for i1, c1 in enumerate(s1):
                if c1 == c2:
                    distances_.append(distances[i1])
                else:
                    distances_.append(1 + min((distances[i1], distances[i1 + 1], distances_[-1])))
            distances = distances_
        return distances[-1]

    def clean_punct(w: str) -> str:
        return re.sub(r'[^\w\s\u0080-\uffff]', '', w).lower()

    for token, original_val in placeholders.items():
        if token in translated_text:
            continue

        token_idx = -1
        for idx, w in enumerate(src_words):
            if token in w:
                token_idx = idx
                break

        if token_idx == -1:
            continue

        left_anchor = src_words[token_idx - 1] if token_idx > 0 else None
        right_anchor = src_words[token_idx + 1] if token_idx < len(src_words) - 1 else None

        best_left_idx = -1
        best_left_val = 9999
        best_right_idx = -1
        best_right_val = 9999

        for idx, w in enumerate(tr_words):
            w_clean = clean_punct(w)
            if not w_clean:
                continue
            if left_anchor:
                la_clean = clean_punct(left_anchor)
                dist = edit_distance(w_clean, la_clean)
                if dist < best_left_val and dist < max(3, len(la_clean) // 2):
                    best_left_val = dist
                    best_left_idx = idx
            if right_anchor:
                ra_clean = clean_punct(right_anchor)
                dist = edit_distance(w_clean, ra_clean)
                if dist < best_right_val and dist < max(3, len(ra_clean) // 2):
                    best_right_val = dist
                    best_right_idx = idx

        insert_idx = -1
        if best_left_idx != -1 and best_right_idx != -1:
            if best_left_idx < best_right_idx:
                insert_idx = best_left_idx + 1
            else:
                insert_idx = best_right_idx
        elif best_left_idx != -1:
            insert_idx = best_left_idx + 1
        elif best_right_idx != -1:
            insert_idx = best_right_idx
        else:
            insert_idx = len(tr_words)

        if insert_idx != -1:
            tr_words.insert(insert_idx, token)

    return _clean_orphaned_placeholders(" ".join(tr_words))


def _clean_orphaned_placeholders(text: str) -> str:
    """Removes any mangled or orphaned placeholder residues like PHxxxx_y, RLPHxxxx_y, ⟦, ⟧ etc."""
    if not text:
        return text
    # 1. Remove namespaced token codes like RLPHxxxx or PHxxxx (with or without brackets, spaces, underscores, indices)
    text = re.sub(r'⟦?\s*(?:R[A-Z]{0,6}LPH|PH)[0-9A-F]{3,}(?:\s*_\s*\d+|\s*\d+)?\s*⟧?', '', text, flags=re.IGNORECASE)
    
    # 2. Mask valid digit-based placeholders (e.g. ⟦0⟧, ⟦12⟧) so they don't get stripped
    valid_tokens = re.findall(r'⟦\d+⟧', text)
    for i, token in enumerate(valid_tokens):
        text = text.replace(token, f"__VALID_PH_{i}__")
        
    # 3. Clean any orphaned bracket remains
    text = text.replace('\u27e6', '').replace('\u27e7', '')
    
    # 4. Restore valid masked tokens
    for i, token in enumerate(valid_tokens):
        text = text.replace(f"__VALID_PH_{i}__", token)
        
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _parse_xml_batch(xml_text: str, count: int) -> List[Optional[str]]:
    """Parses XML batch response. Returns list of strings (None for missing items)."""
    results: List[Optional[str]] = [None] * count
    try:
        # Try to find and parse the <translations> block
        start = xml_text.find("<translations>")
        end = xml_text.find("</translations>")
        if start != -1 and end != -1:
            xml_block = xml_text[start: end + len("</translations>")]
            root = ET.fromstring(xml_block)
            for item in root.findall("item"):
                idx_str = item.get("id")
                if idx_str is not None and item.text is not None:
                    try:
                        results[int(idx_str)] = item.text
                    except (ValueError, IndexError):
                        pass
            return results
    except ET.ParseError:
        pass

    # Fallback: regex scan
    for m in _XML_ITEM_RE.finditer(xml_text):
        try:
            idx = int(m.group(1))
            results[idx] = m.group(2)
        except (ValueError, IndexError):
            pass
    return results


def _jitter_sleep(base: float, attempt: int, cap: float = 60.0) -> float:
    """Returns wait time with full jitter: uniform(0, min(cap, base * 2^attempt))."""
    return random.uniform(0, min(cap, base * (2 ** attempt)))


# ─────────────────────────────────────────────────────────────────────────────
# AsyncBaseAITranslator
# ─────────────────────────────────────────────────────────────────────────────

class AsyncBaseAITranslator(BaseTranslator):
    """
    Shared base for all OpenAI-compatible AI translators.

    Subclasses must set:
      - self._client: AsyncOpenAI instance
      - self._engine: TranslationEngine enum value
      - self._model: str  (model name)
      - self._timeout: float  (request timeout in seconds)
      - self._batch_size: int  (segments per XML batch request)
      - self._semaphore_count: int  (max parallel API requests)
    """

    _SYSTEM_PROMPT_TEMPLATE = (
        "You are a professional game translator. "
        "Translate game dialogue and UI text from {src} to {tgt}. "
        "Preserve ALL special placeholders and XML tags exactly: tokens like <ph id=\"N\">...</ph>, "
        "[variable], {tag}, {color=#fff}. "
        "Maintain the tone, register and style of the original. "
        "Return only the translated text, no explanations."
    )

    _BATCH_SYSTEM_PROMPT_TEMPLATE = (
        "You are a professional game translator. "
        "Translate game dialogue/UI text from {src} to {tgt}. "
        "Rules: 1) Preserve ALL special tokens/tags exactly (XML tags like <ph id=\"N\">...</ph>, [var], {tag}). "
        "2) Maintain tone, register, style. "
        "3) You will receive an XML block with numbered <item> elements. "
        "Return the SAME XML structure with translated text inside each <item>. "
        "Do NOT add explanations or extra content outside the XML."
    )

    def __init__(
        self,
        api_key: Optional[str] = None,
        proxy_manager=None,
        config_manager=None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        batch_size: Optional[int] = None,
        semaphore_count: Optional[int] = None,
    ) -> None:
        super().__init__(api_key=api_key, proxy_manager=proxy_manager, config_manager=config_manager)
        if not _OPENAI_AVAILABLE:
            raise ImportError(
                "The 'openai' package is required for AI translation engines. "
                "Install it with: pip install openai"
            )
        self._model: str = model or "gpt-4o-mini"
        self._base_url: Optional[str] = base_url
        self._timeout: float = timeout or AI_DEFAULT_TIMEOUT
        self._batch_size: int = batch_size or 20
        self._semaphore_count: int = semaphore_count or 5
        self._engine: TranslationEngine = TranslationEngine.OPENAI
        self._client: Optional[AsyncOpenAI] = None
        self._semaphore: Optional[asyncio.Semaphore] = None

        # Resolve model-family profile (config override + autodetection).
        # None = generic behaviour; "hy_mt2" = Tencent Hy-MT optimized path.
        self._model_profile: Optional[str] = resolve_model_profile(
            config_manager, self._model
        )
        if self._model_profile == "hy_mt2":
            self.logger.info(
                f"[{self.__class__.__name__}] Hy-MT model profile active for "
                f"'{self._model}' — official instruction templates, no system "
                "prompt, model-card sampling."
            )
            if config_manager and hasattr(config_manager, "translation_settings"):
                csp = getattr(
                    config_manager.translation_settings,
                    "ai_custom_system_prompt", "",
                ) or ""
                if csp.strip():
                    self.logger.info(
                        f"[{self.__class__.__name__}] Hy-MT models have no system "
                        "prompt — ai_custom_system_prompt is ignored. Set "
                        "ai_model_profile='generic' to use a custom prompt."
                    )

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            kwargs: Dict[str, Any] = {
                "api_key": self.api_key or "none",
                "timeout": self._timeout,
                "max_retries": 0,  # We handle retries ourselves
            }
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    def _map_unicode_to_ascii_placeholders(
        self, text: str, placeholders: Dict[str, str]
    ) -> Tuple[str, Dict[str, str]]:
        """
        Maps namespaced Unicode tokens (e.g. ⟦RLPHxxxx_0⟧) to tokenizer-friendly
        ASCII placeholders (__PH_0__) to optimize model attention and prevent mutilation.
        Returns mapped text and the new mapping registry.
        """
        if not text or not placeholders:
            return text, {}

        # Filter out metadata wrapper keys
        vars_only = [
            k for k in placeholders.keys()
            if not k.startswith("__WRAPPER_") and not k.startswith("__TAG_")
        ]
        
        ascii_map: Dict[str, str] = {}
        mapped_text = text
        for i, unicode_token in enumerate(vars_only):
            ascii_token = f"__PH_{i}__"
            ascii_map[ascii_token] = unicode_token
            mapped_text = mapped_text.replace(unicode_token, ascii_token)
            
        return mapped_text, ascii_map

    def _map_ascii_to_unicode_placeholders(
        self, text: str, ascii_map: Dict[str, str]
    ) -> str:
        """
        Reverts the tokenizer-friendly ASCII placeholders (__PH_0__) back to their
        original namespaced Unicode tokens using tolerance-based regex.
        """
        if not text or not ascii_map:
            return text

        result = text
        # Regex to capture '__PH_0__', '__ PH_0__', '__ph_0__' etc. with spaces
        ph_pattern = re.compile(r'(?i)__\s*PH\s*_\s*(\d+)\s*__')
        
        def _replace_ph(m: re.Match) -> str:
            try:
                idx = int(m.group(1))
                ascii_key = f"__PH_{idx}__"
                return ascii_map.get(ascii_key, m.group(0))
            except (ValueError, IndexError):
                return m.group(0)
                
        result = ph_pattern.sub(_replace_ph, result)
        return result

    def _get_semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._semaphore_count)
        return self._semaphore

    # Hy-MT2 model-card sampling recipe (1.8B / 7B).
    HY_MT2_TEMPERATURE = 0.7
    HY_MT2_TOP_P = 0.6
    HY_MT2_EXTRA_BODY: Dict[str, Any] = {"top_k": 20, "repetition_penalty": 1.05}

    def _is_hy_mt2(self) -> bool:
        return self._model_profile == "hy_mt2"

    def _get_sampling_kwargs(self) -> Dict[str, Any]:
        """Engine-specific sampling kwargs passed through to _call_api.

        Hy-MT2 uses the model-card recipe (top_p 0.6, top_k 20,
        repetition_penalty 1.05). extra_body carries the non-standard fields;
        _call_api drops them automatically if a server rejects them (400).
        Generic models keep today's behaviour (temperature only).
        """
        if self._is_hy_mt2():
            return {
                "top_p": self.HY_MT2_TOP_P,
                "extra_body": dict(self.HY_MT2_EXTRA_BODY),
            }
        return {}

    def _get_temperature(self) -> float:
        if self._is_hy_mt2():
            # Model-card recommendation is 0.7. Honour an explicit user change
            # of the ai_temperature setting, otherwise apply the recipe.
            cfg_val = None
            if self.config_manager:
                cfg_val = getattr(
                    self.config_manager.translation_settings,
                    "ai_temperature", None,
                )
            if cfg_val is not None and float(cfg_val) != AI_DEFAULT_TEMPERATURE:
                return float(cfg_val)
            return self.HY_MT2_TEMPERATURE
        if self.config_manager:
            return getattr(self.config_manager.translation_settings, "ai_temperature", AI_DEFAULT_TEMPERATURE)
        return AI_DEFAULT_TEMPERATURE

    # ── Hy-MT2 prompt builders (official model-card instruction templates) ──

    def _build_hy_mt2_single_prompt(
        self,
        tgt_lang_name: str,
        protected_text: str,
        placeholders: Dict[str, str],
        xml_mode: bool = True,
    ) -> str:
        """Official default-translation instruction + delimiter preservation.

        Hy-MT2 is trained on a short user-role instruction and has no system
        prompt, so everything goes into the user message (fewer prompt tokens
        = faster prefill, better adherence).
        """
        # Everything up to the final ":" + blank line is the instruction;
        # only the source text may follow it. Hy-MT2 was trained on this
        # exact shape — any instruction sentence placed AFTER the colon is
        # treated as text and gets translated/echoed into the output.
        instruction = (
            f"Translate the following text into {tgt_lang_name}. Note that you "
            "should only output the translated result without any additional "
            "explanation"
        )
        if placeholders:
            if xml_mode:
                # placeholders keys are the bare ids of <ph id="N">...</ph> tags
                tokens = [f'<ph id="{k}">' for k in sorted(placeholders.keys())][:6]
            else:
                tokens = sorted(set(placeholders.keys()))[:6]
            token_list = ", ".join(tokens)
            instruction += (
                ". You must retain the exact same number of delimiters and "
                f"placeholder tokens ({token_list}) in the translated output; "
                "never omit, escape, translate, or reorder them"
            )
        return instruction + ":\n\n" + protected_text

    def _build_hy_mt2_batch_prompt(self, src_lang_name: str, tgt_lang_name: str) -> str:
        """Official structured-data (format-locked) instruction for JSON batches.

        Names generic token formats instead of per-item tokens: the instruction
        is per-chunk while placeholders differ per item, and per-item integrity
        is enforced afterwards by validate_translation_integrity anyway.
        """
        return (
            f"The following is structured data containing text segments to "
            f"translate from {src_lang_name} into {tgt_lang_name}. Translate "
            "only the visible user-facing text inside the \"text\" field of "
            "each item. Preserve the data structure exactly: keep all keys and "
            "\"id\" values unchanged; never translate or modify placeholders "
            "like <ph id=\"N\">...</ph>, __PH_N__, [var], {tag}, {{var}}, "
            "${var}, %s, %d. Keep the exact same number of items.\n"
            "Return a JSON object with this exact structure, nothing else:\n"
            "{\"translations\": [{\"id\": integer, \"translated_text\": string}]}"
        )

    def _get_max_tokens(self) -> int:
        if self.config_manager:
            return getattr(self.config_manager.translation_settings, "ai_max_tokens", AI_DEFAULT_MAX_TOKENS)
        return AI_DEFAULT_MAX_TOKENS

    def _get_retry_count(self) -> int:
        if self.config_manager:
            return getattr(self.config_manager.translation_settings, "ai_retry_count", AI_MAX_RETRIES)
        return AI_MAX_RETRIES

    async def _call_api(
        self,
        system_prompt: Optional[str],
        user_content: str,
        use_json_schema: bool = False,
        top_p: Optional[float] = None,
        extra_body: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Makes a single API call with retry + jitter backoff. Returns response text or None.

        system_prompt=None omits the system message entirely (required by
        translation-specialized models such as Tencent Hy-MT that are trained
        without a system prompt). top_p/extra_body are only forwarded when set.
        """
        client = self._get_client()
        retries = self._get_retry_count()

        for attempt in range(retries + 1):
            try:
                messages: List[Dict[str, str]] = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": user_content})

                kwargs: Dict[str, Any] = {
                    "model": self._model,
                    "messages": messages,
                    "temperature": self._get_temperature(),
                    "max_tokens": self._get_max_tokens(),
                }
                if top_p is not None:
                    kwargs["top_p"] = top_p
                if extra_body is not None:
                    kwargs["extra_body"] = extra_body
                if use_json_schema:
                    kwargs["response_format"] = {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "translation_response",
                            "strict": True,
                            "schema": AI_BATCH_SCHEMA
                        }
                    }
                response = await client.chat.completions.create(**kwargs)
                finish_reason = response.choices[0].finish_reason
                if finish_reason == "content_filter":
                    # Safety filter block — return None to trigger graceful recovery
                    self.logger.warning(
                        f"[{self.__class__.__name__}] Content filter triggered. "
                        "Will return original text for affected segment(s)."
                    )
                content = response.choices[0].message.content or None
                if content:
                    self.logger.debug(f"[{self.__class__.__name__}] Raw Response (truncated): {content[:300]}")
                return content

            except Exception as exc:
                if _OPENAI_AVAILABLE and isinstance(exc, APIStatusError) and exc.status_code == 400:
                    # Layered compatibility fallback for local servers
                    # (LM Studio / Ollama / llama.cpp variants):
                    # 1) extra_body fields (top_k, repetition_penalty) may be
                    #    rejected by servers that validate unknown keys.
                    if extra_body is not None:
                        self.logger.warning(
                            f"[{self.__class__.__name__}] Server rejected extra_body fields (400). "
                            "Retrying request immediately without extra_body."
                        )
                        return await self._call_api(
                            system_prompt, user_content,
                            use_json_schema=use_json_schema,
                            top_p=top_p,
                            extra_body=None,
                        )
                    # 2) Then drop JSON Schema constraints (existing behaviour).
                    if use_json_schema:
                        self.logger.warning(
                            f"[{self.__class__.__name__}] Custom engine failed on response_format json_schema (400). "
                            "Retrying request immediately without JSON Schema constraints."
                        )
                        return await self._call_api(
                            system_prompt, user_content,
                            use_json_schema=False,
                            top_p=top_p,
                        )

                if _OPENAI_AVAILABLE and isinstance(exc, APIStatusError):
                    status = exc.status_code
                    if status == 404:
                        self.logger.error(
                            f"[{self.__class__.__name__}] Error 404: Model '{self._model}' not found on the server. "
                            f"Please verify if model name is spelled correctly or ensure it is downloaded/loaded on your server."
                        )
                    elif status == 401:
                        self.logger.error(
                            f"[{self.__class__.__name__}] Error 401: Unauthorized. "
                            f"Please check if your API Key is valid or configured correctly."
                        )
                elif _OPENAI_AVAILABLE and isinstance(exc, APIConnectionError):
                    self.logger.error(
                        f"[{self.__class__.__name__}] Connection Error: Could not connect to host '{self._base_url or 'OpenAI'}'. "
                        f"Please verify your internet connection or check if your Local LLM engine (Ollama/LM Studio) is running."
                    )

                is_quota = False
                is_retryable = False
                retry_after: Optional[float] = None

                if _OPENAI_AVAILABLE:
                    if isinstance(exc, APIStatusError):
                        status = exc.status_code
                        # Check for Retry-After header
                        try:
                            ra = exc.response.headers.get("retry-after")
                            if ra:
                                retry_after = float(ra)
                        except Exception:
                            pass
                        if status == 429:
                            is_quota = True
                            is_retryable = True
                        elif status in (500, 502, 503, 504):
                            is_retryable = True
                        # 400, 401, 403 → not retryable
                    elif isinstance(exc, (APITimeoutError, APIConnectionError)):
                        is_retryable = True

                if not is_retryable and not is_quota:
                    self.logger.error(f"[{self.__class__.__name__}] Non-retryable error: {exc}")
                    return None

                if attempt >= retries:
                    if is_quota:
                        self.logger.warning(f"[{self.__class__.__name__}] Quota exceeded after {retries} retries.")
                    else:
                        self.logger.warning(f"[{self.__class__.__name__}] API error after {retries} retries: {exc}")
                    return None

                wait = retry_after if retry_after else _jitter_sleep(2.0, attempt)
                self.logger.warning(
                    f"[{self.__class__.__name__}] Retry {attempt + 1}/{retries} in {wait:.1f}s — {exc}"
                )
                await asyncio.sleep(wait)

        return None

    async def translate_single(self, request: TranslationRequest) -> TranslationResult:
        """Translates a single segment."""
        source_text = request.text.strip()
        if not source_text:
            return TranslationResult(
                source_text, source_text, request.source_lang, request.target_lang,
                self._engine, True, confidence=1.0,
            )

        metadata = request.metadata if isinstance(request.metadata, dict) else {}
        preprotected = bool(metadata.get('preprotected'))
        xml_mode = bool(metadata.get('xml_mode', True))  # AI by default XML

        if preprotected:
            protected = request.text
            placeholders = metadata.get('placeholders', {})
        else:
            from src.core.syntax_guard import protect_renpy_syntax_xml
            if xml_mode:
                protected, placeholders = protect_renpy_syntax_xml(source_text)
            else:
                protected, placeholders = protect_renpy_syntax(source_text)
 
        # Map Unicode placeholders to tokenizer-friendly ASCII placeholders
        if xml_mode:
            mapped_protected = protected
            ascii_map = {}
        else:
            mapped_protected, ascii_map = self._map_unicode_to_ascii_placeholders(protected, placeholders)

        if self._is_hy_mt2():
            # Official Hy-MT instruction lives in the user message; Hy-MT
            # models have no system prompt (model card). Shorter prompt = faster.
            src = _resolve_language_name(request.source_lang)
            tgt = _resolve_language_name(request.target_lang)
            system_prompt = None
            if xml_mode:
                delimiter_map = placeholders
            else:
                # Token mode sends ASCII __PH_N__ tokens to the model
                delimiter_map = dict(ascii_map) if ascii_map else placeholders
            user_content = self._build_hy_mt2_single_prompt(
                tgt, mapped_protected, delimiter_map, xml_mode=xml_mode
            )
        else:
            src = _SUPPORTED_LANGUAGES.get(request.source_lang, request.source_lang)
            if request.source_lang == "auto":
                src = "the original language"
            tgt = _SUPPORTED_LANGUAGES.get(request.target_lang, request.target_lang)

            custom_prompt = None
            if self.config_manager:
                custom_prompt = getattr(self.config_manager.translation_settings, "ai_custom_system_prompt", None)

            if custom_prompt and custom_prompt.strip():
                system_prompt = (
                    custom_prompt.strip() +
                    "\n\nImportant: You must strictly preserve all placeholders like __PH_0__, __PH_1__ exactly as they appear."
                )
            else:
                system_prompt = (
                    "You are a professional game translator. "
                    f"Translate game dialogue and UI text from {src} to {tgt}. "
                    "Preserve ALL special placeholders exactly: tokens like __PH_0__, __PH_1__, "
                    "[variable], {tag}, {color=#fff}. "
                    "Maintain the tone, register and style of the original. "
                    "Return only the translated text, no explanations.\n\n"
                    "Examples with placeholders:\n"
                    "- Input: \"Hello __PH_0__, welcome to __PH_1__.\"\n"
                    "- Output: \"Merhaba __PH_0__, __PH_1__ sitesine hoş geldiniz.\"\n"
                    "- Input: \"Press {i}Enter{/i} to start [game_name].\"\n"
                    "- Output: \"{i}Enter{/i} tuşuna basarak [game_name] oyununu başlatın.\""
                )
            user_content = mapped_protected

        async with self._get_semaphore():
            response = await self._call_api(
                system_prompt, user_content, **self._get_sampling_kwargs()
            )
 
        if response is None:
            # Graceful recovery: return original
            return TranslationResult(
                source_text, source_text, request.source_lang, request.target_lang,
                self._engine, True, confidence=0.0, metadata={"skipped": True},
            )
 
        if xml_mode:
            from src.core.syntax_guard import restore_renpy_syntax_xml
            translated = restore_renpy_syntax_xml(response.strip(), placeholders)
            missing = validate_translation_integrity(translated, placeholders)
            if missing:
                translated = source_text
        else:
            unmapped_response = self._map_ascii_to_unicode_placeholders(response.strip(), ascii_map)
            translated = restore_renpy_syntax(unmapped_response, placeholders)
            missing = validate_translation_integrity(translated, placeholders)
            if missing:
                # Attempt smart Levenshtein recovery first
                recovered_lev = _recover_placeholders_levenshtein(source_text, translated, placeholders)
                recovered_lev = restore_renpy_syntax(recovered_lev, placeholders)
                still_missing = validate_translation_integrity(recovered_lev, placeholders)
                if not still_missing:
                    translated = recovered_lev
                else:
                    recovered = inject_missing_placeholders(translated, protected, placeholders, missing)
                    recovered = restore_renpy_syntax(recovered, placeholders)
                    still_missing = validate_translation_integrity(recovered, placeholders)
                    translated = recovered if not still_missing else source_text
        
        # Clean any leftover orphaned/mangled placeholder residues at the very end
        translated = _clean_orphaned_placeholders(translated)

        return TranslationResult(
            source_text, translated, request.source_lang, request.target_lang,
            self._engine, True, confidence=0.9, metadata=request.metadata,
        )

    async def translate_batch(self, requests: List[TranslationRequest]) -> List[TranslationResult]:
        """Translates a batch using structured JSON Schema or XML grouping for token efficiency."""
        if not requests:
            return []
        if len(requests) == 1:
            return [await self.translate_single(requests[0])]

        # Chunk into batches of self._batch_size
        chunks: List[List[Tuple[int, TranslationRequest]]] = []
        cur_chunk: List[Tuple[int, TranslationRequest]] = []
        for i, req in enumerate(requests):
            cur_chunk.append((i, req))
            if len(cur_chunk) >= self._batch_size:
                chunks.append(cur_chunk)
                cur_chunk = []
        if cur_chunk:
            chunks.append(cur_chunk)

        results: List[Optional[TranslationResult]] = [None] * len(requests)
        sem = self._get_semaphore()

        async def process_chunk(chunk: List[Tuple[int, TranslationRequest]]) -> None:
            protected_list: List[str] = []
            placeholder_list: List[Dict] = []
            source_list: List[str] = []
            ascii_maps_list: List[Dict[str, str]] = []
            
            first_req = chunk[0][1]
            first_metadata = first_req.metadata if isinstance(first_req.metadata, dict) else {}
            xml_mode = bool(first_metadata.get('xml_mode', True))  # AI by default XML

            for _, req in chunk:
                src_text = req.text.strip()
                source_list.append(src_text)
                
                req_metadata = req.metadata if isinstance(req.metadata, dict) else {}
                req_preprotected = bool(req_metadata.get('preprotected'))
                
                if req_preprotected:
                    prot = src_text
                    ph = req_metadata.get('placeholders', {})
                else:
                    from src.core.syntax_guard import protect_renpy_syntax_xml
                    if xml_mode:
                        prot, ph = protect_renpy_syntax_xml(src_text)
                    else:
                        prot, ph = protect_renpy_syntax(src_text)
                
                if xml_mode:
                    mapped_prot = prot
                    ascii_map = {}
                else:
                    mapped_prot, ascii_map = self._map_unicode_to_ascii_placeholders(prot, ph)
                    
                protected_list.append(mapped_prot)
                placeholder_list.append(ph)
                ascii_maps_list.append(ascii_map)

            src_lang = chunk[0][1].source_lang
            tgt_lang_code = chunk[0][1].target_lang

            use_json = True
            if self._is_hy_mt2():
                # Official structured-data instruction in the user message;
                # no system prompt for Hy-MT models.
                src_label = _resolve_language_name(src_lang)
                tgt_lang = _resolve_language_name(tgt_lang_code)
                system_prompt = None
                user_content = (
                    self._build_hy_mt2_batch_prompt(src_label, tgt_lang)
                    + "\n\n"
                    + _build_json_batch(protected_list)
                )
            else:
                src_label = _SUPPORTED_LANGUAGES.get(src_lang, src_lang)
                if src_lang == "auto":
                    src_label = "the original language"
                tgt_lang = _SUPPORTED_LANGUAGES.get(tgt_lang_code, tgt_lang_code)

                # Check for custom system prompt
                custom_prompt = None
                if self.config_manager:
                    custom_prompt = getattr(self.config_manager.translation_settings, "ai_custom_system_prompt", None)

                if custom_prompt and custom_prompt.strip():
                    system_prompt = (
                        custom_prompt.strip() +
                        "\n\nImportant: You must strictly return your response in the requested JSON structure matching the schema: "
                        "{'translations': [{'id': integer, 'translated_text': string}]}. "
                        "Do not add any conversational text or markdown wrappers. "
                        "You must strictly preserve all placeholders like __PH_0__, __PH_1__ exactly as they appear."
                    )
                else:
                    system_prompt = (
                        "You are a professional game translator. "
                        f"Translate game dialogue/UI text from {src_label} to {tgt_lang}. "
                        "Rules: 1) Preserve ALL special tokens/tags exactly (like __PH_0__, __PH_1__, [var], {tag}). "
                        "2) Maintain tone, register, style. "
                        "3) Respond ONLY with a JSON object matching this schema: "
                        "{'translations': [{'id': integer, 'translated_text': string}]}. "
                        "Do NOT add any conversational prefix, suffix, or markdown code block formatting.\n\n"
                        "Examples with placeholders:\n"
                        "- Input: \"Hello __PH_0__, welcome to __PH_1__.\"\n"
                        "- Output: \"Merhaba __PH_0__, __PH_1__ sitesine hoş geldiniz.\"\n"
                        "- Input: \"Press {i}Enter{/i} to start [game_name].\"\n"
                        "- Output: \"{i}Enter{/i} tuşuna basarak [game_name] oyununu başlatın.\""
                    )
                user_content = _build_json_batch(protected_list)

            async with sem:
                response = await self._call_api(
                    system_prompt, user_content,
                    use_json_schema=use_json,
                    **self._get_sampling_kwargs(),
                )

            if response is None:
                # Graceful recovery for whole chunk
                for orig_idx, req in chunk:
                    results[orig_idx] = TranslationResult(
                        req.text, req.text, req.source_lang, req.target_lang,
                        self._engine, True, confidence=0.0, metadata={"skipped": True},
                    )
                return

            # Try parsing as JSON first
            parsed = _parse_json_batch(response, len(chunk))

            # Fallback to XML if JSON parsing yielded nothing
            if all(x is None for x in parsed):
                parsed = _parse_xml_batch(response, len(chunk))

            for i, (orig_idx, req) in enumerate(chunk):
                src_text = source_list[i]
                translated_raw = parsed[i]
                if translated_raw is None:
                    # Fallback to individual translate
                    results[orig_idx] = await self.translate_single(req)
                    continue

                if xml_mode:
                    from src.core.syntax_guard import restore_renpy_syntax_xml
                    translated = restore_renpy_syntax_xml(translated_raw.strip(), placeholder_list[i])
                    missing = validate_translation_integrity(translated, placeholder_list[i])
                    if missing:
                        translated = src_text
                else:
                    unmapped_raw = self._map_ascii_to_unicode_placeholders(translated_raw.strip(), ascii_maps_list[i])
                    translated = restore_renpy_syntax(unmapped_raw, placeholder_list[i])
                    missing = validate_translation_integrity(translated, placeholder_list[i])
                    if missing:
                        # Attempt smart Levenshtein recovery first
                        recovered_lev = _recover_placeholders_levenshtein(src_text, translated, placeholder_list[i])
                        recovered_lev = restore_renpy_syntax(recovered_lev, placeholder_list[i])
                        still_missing = validate_translation_integrity(recovered_lev, placeholder_list[i])
                        if not still_missing:
                            translated = recovered_lev
                        else:
                            recovered = inject_missing_placeholders(
                                translated, protected_list[i], placeholder_list[i], missing
                            )
                            recovered = restore_renpy_syntax(recovered, placeholder_list[i])
                            still_missing = validate_translation_integrity(recovered, placeholder_list[i])
                            translated = recovered if not still_missing else src_text
                
                # Clean any leftover orphaned/mangled placeholder residues at the very end
                translated = _clean_orphaned_placeholders(translated)

                results[orig_idx] = TranslationResult(
                    src_text, translated, req.source_lang, req.target_lang,
                    self._engine, True, confidence=0.9, metadata=req.metadata,
                )

        await asyncio.gather(*(process_chunk(ch) for ch in chunks))

        # Fill any None gaps with original text (safety net)
        for i, req in enumerate(requests):
            if results[i] is None:
                results[i] = TranslationResult(
                    req.text, req.text, req.source_lang, req.target_lang,
                    self._engine, True, confidence=0.0,
                )

        return results  # type: ignore[return-value]

    def get_supported_languages(self) -> Dict[str, str]:
        return _SUPPORTED_LANGUAGES

    async def close(self) -> None:
        await super().close()
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None


# ─────────────────────────────────────────────────────────────────────────────
# OpenAITranslator
# ─────────────────────────────────────────────────────────────────────────────

class OpenAITranslator(AsyncBaseAITranslator):
    """
    OpenAI translator (gpt-4o-mini default).

    Uses XML batch for token efficiency and full retry/quota handling.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        proxy_manager=None,
        config_manager=None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs,
    ) -> None:
        resolved_model = model
        if not resolved_model and config_manager:
            resolved_model = getattr(
                config_manager.translation_settings, "openai_model", "gpt-4o-mini"
            )
        resolved_model = resolved_model or "gpt-4o-mini"

        resolved_base_url = base_url
        if not resolved_base_url and config_manager:
            resolved_base_url = getattr(
                config_manager.translation_settings, "openai_base_url", None
            ) or None

        timeout = AI_DEFAULT_TIMEOUT
        if config_manager:
            timeout = getattr(config_manager.translation_settings, "ai_timeout", AI_DEFAULT_TIMEOUT)

        batch_size = 20
        if config_manager:
            batch_size = getattr(config_manager.translation_settings, "ai_batch_size", 20)

        super().__init__(
            api_key=api_key,
            proxy_manager=proxy_manager,
            config_manager=config_manager,
            model=resolved_model,
            base_url=resolved_base_url,
            timeout=timeout,
            batch_size=batch_size,
            semaphore_count=5,
        )
        self._engine = TranslationEngine.OPENAI


# ─────────────────────────────────────────────────────────────────────────────
# DeepSeekTranslator
# ─────────────────────────────────────────────────────────────────────────────

_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
_DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-flash"


class DeepSeekTranslator(OpenAITranslator):
    """
    DeepSeek translator via OpenAI-compatible API.

    Uses the same XML batch pipeline as OpenAI; only the endpoint and model differ.
    Higher concurrency allowed (DeepSeek supports more concurrent requests).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        proxy_manager=None,
        config_manager=None,
        **kwargs,
    ) -> None:
        super().__init__(
            api_key=api_key,
            proxy_manager=proxy_manager,
            config_manager=config_manager,
            model=_DEEPSEEK_DEFAULT_MODEL,
            base_url=_DEEPSEEK_BASE_URL,
        )
        # DeepSeek allows more concurrent requests than OpenAI
        self._semaphore_count = 12
        self._semaphore = None  # Reset so new semaphore is created with updated count
        self._timeout = 120.0
        self._engine = TranslationEngine.OPENAI  # Routed through OpenAI engine enum


# ─────────────────────────────────────────────────────────────────────────────
# LocalLLMTranslator
# ─────────────────────────────────────────────────────────────────────────────

class LocalLLMTranslator(OpenAITranslator):
    """
    Local LLM translator via Ollama / LM Studio OpenAI-compatible API.

    Connects to a local inference server (default: Ollama at localhost:11434).
    Concurrency defaults to 2 but honours the ai_concurrency setting — local
    servers with parallel slots (LM Studio, llama.cpp --parallel) benefit from
    higher values.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        proxy_manager=None,
        config_manager=None,
        **kwargs,
    ) -> None:
        base_url = AI_LOCAL_URL
        model = "llama3.2"
        if config_manager:
            base_url = (
                getattr(config_manager.translation_settings, "local_llm_url", None)
                or AI_LOCAL_URL
            )
            model = (
                getattr(config_manager.translation_settings, "local_llm_model", None)
                or "llama3.2"
            )

        super().__init__(
            api_key=api_key or "none",  # Local LLM doesn't need a real key
            proxy_manager=proxy_manager,
            config_manager=config_manager,
            model=model,
            base_url=base_url,
        )
        # Local GPUs default to modest concurrency, but respect the user's
        # ai_concurrency setting (servers with parallel slots can use more).
        concurrency = 2
        if config_manager:
            concurrency = getattr(
                config_manager.translation_settings, "ai_concurrency", 2
            ) or 2
        try:
            self._semaphore_count = max(1, int(concurrency))
        except (TypeError, ValueError):
            self._semaphore_count = 2
        self._semaphore = None
        self._timeout = AI_LOCAL_TIMEOUT
        self._batch_size = 10  # Smaller batches for slower local models
        self._engine = TranslationEngine.LOCAL_LLM


# ─────────────────────────────────────────────────────────────────────────────
# GeminiTranslator — Google Gemini (official google-genai SDK)
# ─────────────────────────────────────────────────────────────────────────────

class GeminiTranslator(BaseTranslator):
    """Google Gemini translator using the official google-genai SDK."""

    def __init__(self, *args, api_key: Optional[str] = None, **kwargs) -> None:
        if not _GEMINI_AVAILABLE:
            raise ImportError(
                "google-genai is required for Gemini translation. "
                "Install it with: pip install google-genai"
            )
        resolved_key = api_key
        if not resolved_key:
            cm = kwargs.get('config_manager', None)
            if cm and hasattr(cm, 'api_keys'):
                resolved_key = cm.api_keys.gemini_api_key or ""
        if not resolved_key:
            resolved_key = "none"  # Allow instantiation without key; fails gracefully at translate time

        if resolved_key != "none":
            genai.configure(api_key=resolved_key)

        config_manager = kwargs.get('config_manager', None)
        model_name = "gemini-2.5-flash"
        if config_manager and hasattr(config_manager, 'translation_settings'):
            model_name = getattr(config_manager.translation_settings, 'gemini_model', None) or model_name

        super().__init__(
            api_key=resolved_key,
            proxy_manager=kwargs.get('proxy_manager', None),
            config_manager=config_manager,
        )
        self._client = genai.GenerativeModel(model_name)
        self._model: str = model_name
        self._timeout = kwargs.get('timeout', AI_DEFAULT_TIMEOUT)
        self._batch_size = min(kwargs.get('batch_size', 20), 50)
        self._engine = TranslationEngine.GEMINI

    async def translate_single(self, request: TranslationRequest) -> TranslationResult:
        """Translate a single text using Gemini."""
        try:
            loop = asyncio.get_event_loop()
            source_lang = request.source_lang or "auto"
            target_lang = request.target_lang or "en"

            prompt = (
                f"Translate the following text from {source_lang} to {target_lang}. "
                f"Only return the translation, nothing else. "
                f"Do NOT modify or translate any code, markup, HTML tags, or placeholders: "
                f"{request.text}"
            )

            response = await loop.run_in_executor(
                None,
                lambda: self._client.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=getattr(request, 'temperature', 0.3),
                        max_output_tokens=getattr(request, 'max_tokens', 2048),
                    ),
                    safety_settings={
                        'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE',
                        'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE',
                        'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE',
                        'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE',
                    }
                )
            )

            translated = response.text.strip() if response and response.text else request.text

            return TranslationResult(
                original_text=request.text,
                translated_text=translated,
                source_lang=source_lang,
                target_lang=target_lang,
                engine=TranslationEngine.GEMINI,
                success=bool(translated and translated != request.text),
            )

        except Exception as exc:
            error_msg = str(exc)
            if "SAFETY" in error_msg.upper() or "blocked" in error_msg.lower():
                return TranslationResult(
                    original_text=request.text,
                    translated_text=request.text,
                    source_lang=request.source_lang or "auto",
                    target_lang=request.target_lang or "en",
                    engine=TranslationEngine.GEMINI,
                    success=False,
                    error="Content blocked by safety filter - original text returned",
                )
            self.logger.error(f"Gemini translation error: {exc}")
            return TranslationResult(
                original_text=request.text,
                translated_text=request.text,
                source_lang=request.source_lang or "auto",
                target_lang=request.target_lang or "en",
                engine=TranslationEngine.GEMINI,
                success=False,
                error=error_msg,
            )

    async def translate_batch(self, requests: List[TranslationRequest]) -> List[TranslationResult]:
        results = []
        for req in requests:
            result = await self.translate_single(req)
            results.append(result)
        return results

    def get_supported_languages(self) -> Dict[str, str]:
        return {
            "en": "English", "tr": "Turkish", "de": "German",
            "fr": "French", "es": "Spanish", "ru": "Russian",
            "ja": "Japanese", "zh": "Chinese", "ko": "Korean",
            "ar": "Arabic", "fa": "Persian", "it": "Italian",
            "pt": "Portuguese", "nl": "Dutch", "pl": "Polish",
        }
