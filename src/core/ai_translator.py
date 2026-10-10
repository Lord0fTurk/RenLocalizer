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
import html
import logging
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
    restore_renpy_syntax_xml,
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

from src.utils.net import is_local_endpoint

logger = logging.getLogger(__name__)

# ── Optional dependency guard ─────────────────────────────────────────────────
try:
    from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False

_GEMINI_MODE: Optional[str] = None
try:
    import google.genai as genai
    if hasattr(genai, "Client"):
        _GEMINI_AVAILABLE = True
        _GEMINI_MODE = "google_genai"
    elif hasattr(genai, "GenerativeModel"):
        _GEMINI_AVAILABLE = True
        _GEMINI_MODE = "legacy_generativeai"
    else:
        _GEMINI_AVAILABLE = False
        genai = None  # type: ignore
except ImportError:
    try:
        import google.generativeai as genai
        _GEMINI_AVAILABLE = True
        _GEMINI_MODE = "legacy_generativeai"
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


def profile_prefers_single_segment(config_manager) -> bool:
    """True when the configured model profile is a pure translation model.

    Mirrors AsyncBaseAITranslator._prefers_single_segment() for callers that
    only have the config (e.g. the pipeline, before a translator exists).
    """
    if not config_manager or not hasattr(config_manager, "translation_settings"):
        return False
    ts = config_manager.translation_settings
    if str(getattr(ts, "ai_model_profile", "auto") or "").strip().lower() == "hy_mt2":
        return True
    model_name = getattr(ts, "local_llm_model", None) or getattr(ts, "openai_model", None)
    return detect_model_profile(model_name) == "hy_mt2"


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
    """Parses structured JSON response from the model. Returns list of strings.
    
    Resilient against out-of-range IDs, 1-based indexing, and malformed JSON
    generated by smaller LLMs.
    """
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

        # Check if the model used 1-based indexing across the items (ids 1..count without 0)
        extracted_ids = []
        for item in translations:
            if isinstance(item, dict) and item.get("id") is not None:
                try:
                    extracted_ids.append(int(item["id"]))
                except (ValueError, TypeError):
                    pass

        is_1_based = bool(extracted_ids and 0 not in extracted_ids and min(extracted_ids) == 1 and max(extracted_ids) <= count)

        # Pass 1: Assign valid in-range IDs (0 <= int(idx) < count)
        unassigned_items: List[str] = []
        for item in translations:
            if not isinstance(item, dict):
                continue
            idx = item.get("id")
            val = item.get("translated_text")
            if val is None or not isinstance(val, str):
                continue

            assigned = False
            if idx is not None:
                try:
                    int_idx = int(idx) - 1 if is_1_based else int(idx)
                    if 0 <= int_idx < count and results[int_idx] is None:
                        results[int_idx] = val
                        assigned = True
                except (ValueError, TypeError):
                    pass
            if not assigned:
                unassigned_items.append(val)

        # Pass 2: Positional fallback for items with invalid/out-of-range IDs (e.g. model gave id=64)
        if unassigned_items and any(r is None for r in results):
            for val in unassigned_items:
                try:
                    first_empty = results.index(None)
                    results[first_empty] = val
                except ValueError:
                    break
    except Exception as exc:
        preview = (json_text or "").strip().replace("\n", " ")[:200]
        logger.warning(
            "Failed to parse AI JSON batch response (%s): %s | preview=%r",
            type(exc).__name__, exc, preview,
        )
    return results


_SCENE_LINE_RE = re.compile(
    r"^\s*(?:\[|\()?(\d+)(?:\]|\))?[\.\:\-\s]+\s*(.*)$"
)


def _build_scene_batch(
    texts: List[str], speakers: Optional[List[Optional[str]]] = None
) -> str:
    """Wraps dialogue lines into a natural script/scene screenplay format.

    Includes speaker attribution when known (e.g. `[0] Alice: Hello!`)
    which provides rich character gender/formality context to the LLM.
    """
    lines = ["### SCENE START ###"]
    for i, text in enumerate(texts):
        spk = (
            speakers[i].strip()
            if speakers and i < len(speakers) and speakers[i]
            else None
        )
        if spk:
            lines.append(f"[{i}] {spk}: {text}")
        else:
            lines.append(f"[{i}] {text}")
    lines.append("### SCENE END ###")
    return "\n".join(lines)


def _parse_scene_batch(
    response_text: str,
    count: int,
    expected_speakers: Optional[List[Optional[str]]] = None,
) -> List[Optional[str]]:
    """Parses screenplay/scene formatted lines from model output.

    Extracts each line matching `[ID] Text` or `ID. Text` etc.
    If a speaker prefix was returned (e.g. `[0] Alice: Merhaba!`), strips the
    speaker prefix to return only the translated dialogue text (`Merhaba!`).
    """
    results: List[Optional[str]] = [None] * count
    if not response_text:
        return results

    clean = response_text.strip()
    if clean.startswith("```"):
        lines_raw = clean.splitlines()
        if len(lines_raw) >= 2 and lines_raw[0].startswith("```"):
            lines_raw = lines_raw[1:]
        if lines_raw and lines_raw[-1].startswith("```"):
            lines_raw = lines_raw[:-1]
        clean = "\n".join(lines_raw)

    for line in clean.splitlines():
        line = line.strip()
        if not line or line.startswith("###"):
            continue
        m = _SCENE_LINE_RE.match(line)
        if not m:
            continue
        try:
            idx = int(m.group(1))
            if not (0 <= idx < count):
                continue
            content = m.group(2).strip()

            spk = (
                expected_speakers[idx].strip()
                if expected_speakers
                and idx < len(expected_speakers)
                and expected_speakers[idx]
                else None
            )
            if spk and content.lower().startswith(f"{spk.lower()}:"):
                content = content[len(spk) + 1 :].strip()
            elif ":" in content and spk:
                parts = content.split(":", 1)
                if len(parts) == 2 and len(parts[0].strip()) <= 30 and not any(p in parts[0] for p in ("⟦", "<", "[", "{")):
                    content = parts[1].strip()

            results[idx] = content
        except (ValueError, IndexError):
            continue

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
                if idx_str is None:
                    continue
                # Models frequently emit protected tags (<ph id="N">..</ph>) unescaped,
                # which ElementTree parses as child elements; item.text alone would
                # silently drop everything after the first tag. Re-serialize children
                # so the full inner content (tags + tails) survives.
                inner = item.text or ""
                if len(item):
                    inner += html.unescape(
                        "".join(ET.tostring(child, encoding="unicode") for child in item)
                    )
                if not inner:
                    continue
                try:
                    results[int(idx_str)] = inner
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
                if is_local_endpoint(self._base_url):
                    # A Windows/VPN system proxy would otherwise swallow every
                    # request to Ollama / LM Studio / llama-server (see src/utils/net.py).
                    try:
                        from openai import DefaultAsyncHttpxClient
                        kwargs["http_client"] = DefaultAsyncHttpxClient(trust_env=False)
                    except Exception:
                        import httpx
                        kwargs["http_client"] = httpx.AsyncClient(trust_env=False)
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

    def _prefers_single_segment(self) -> bool:
        """True when this engine must translate one segment per request.

        Two cases:
          * Hy-MT / Hunyuan-MT are *translation* models, not instruction models.
            Their model card defines a single shape ("translate the following
            text into X"), so wrapping requests in scene/XML/JSON scaffolding
            with [ID] tags makes small quants (1.8B Q4) mangle the structure —
            the batch then fails to parse and every line is retried one by one,
            which is both slow and lower quality than asking properly once.
          * The user selected ai_batch_format="single" (recommended for small
            local models): no neighbouring lines, no speaker prefixes, one
            request per line.
        """
        if self._is_hy_mt2():
            return True
        if self.config_manager:
            fmt = getattr(
                self.config_manager.translation_settings, "ai_batch_format", "scene"
            )
            return str(fmt or "").strip().lower() == "single"
        return False

    async def _translate_each_single(
        self, requests: List[TranslationRequest]
    ) -> List[TranslationResult]:
        """Translates every request on its own via translate_single.

        Concurrency is bounded by the semaphore translate_single already takes;
        adding another one here would nest the same lock and deadlock.
        """
        async def one(req: TranslationRequest) -> TranslationResult:
            if self.should_stop_callback and self.should_stop_callback():
                return TranslationResult(
                    req.text, req.text, req.source_lang, req.target_lang,
                    self._engine, True, confidence=0.0, metadata={"skipped": True},
                )
            return await self.translate_single(req)

        return list(await asyncio.gather(*(one(r) for r in requests)))

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

        # Pure translation models (Hy-MT) and the explicit "single" format skip
        # batch scaffolding entirely — see _prefers_single_segment().
        if self._prefers_single_segment():
            return await self._translate_each_single(requests)

        # Determine batch format and chunk size
        batch_format = "scene"
        effective_chunk_size = self._batch_size
        if self.config_manager and hasattr(self.config_manager, "translation_settings"):
            ts = self.config_manager.translation_settings
            batch_format = getattr(ts, "ai_batch_format", "scene") or "scene"
            if batch_format == "scene":
                effective_chunk_size = getattr(ts, "ai_scene_batch_size", 15) or 15
            else:
                effective_chunk_size = getattr(ts, "ai_batch_size", self._batch_size) or self._batch_size

        # Chunk into batches of effective_chunk_size
        chunks: List[List[Tuple[int, TranslationRequest]]] = []
        cur_chunk: List[Tuple[int, TranslationRequest]] = []
        for i, req in enumerate(requests):
            cur_chunk.append((i, req))
            if len(cur_chunk) >= effective_chunk_size:
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
            speakers_list: List[Optional[str]] = []
            
            first_req = chunk[0][1]
            first_metadata = first_req.metadata if isinstance(first_req.metadata, dict) else {}
            xml_mode = bool(first_metadata.get('xml_mode', True))  # AI by default XML

            for _, req in chunk:
                src_text = req.text.strip()
                source_list.append(src_text)
                
                req_metadata = req.metadata if isinstance(req.metadata, dict) else {}
                req_preprotected = bool(req_metadata.get('preprotected'))
                
                # Extract speaker name if available in Ren'Py metadata
                spk = req_metadata.get('character') or req_metadata.get('speaker') or req_metadata.get('who')
                speakers_list.append(str(spk) if spk else None)
                
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
            if batch_format == "scene":
                use_json = False
                src_label = (
                    _resolve_language_name(src_lang)
                    if self._is_hy_mt2()
                    else _SUPPORTED_LANGUAGES.get(src_lang, src_lang)
                )
                tgt_lang = (
                    _resolve_language_name(tgt_lang_code)
                    if self._is_hy_mt2()
                    else _SUPPORTED_LANGUAGES.get(tgt_lang_code, tgt_lang_code)
                )
                if src_lang == "auto":
                    src_label = "the original language"

                if self._is_hy_mt2():
                    # Hy-MT2 model-card recipe: instruction in user message, no system prompt
                    system_prompt = None
                    instruction = (
                        f"Translate the following scene dialogue into {tgt_lang}. "
                        "Keep each line formatted strictly as: [ID] Translated text. "
                        "Do not include the speaker name in the output line. "
                        "Retain the exact same number of lines, and preserve all special tokens and placeholders "
                        "(__PH_N__, [var], {tag}) exactly:\n\n"
                    )
                    user_content = instruction + _build_scene_batch(protected_list, speakers_list)
                else:
                    # Generic / OpenAI / DeepSeek / Local LLM scene mode
                    custom_prompt = None
                    if self.config_manager:
                        custom_prompt = getattr(self.config_manager.translation_settings, "ai_custom_system_prompt", None)

                    if custom_prompt and custom_prompt.strip():
                        system_prompt = (
                            custom_prompt.strip()
                            + "\n\nImportant: You must strictly format each translated line as: [ID] Translated dialogue text. "
                            "Do not include the speaker name in the output. Do not skip any lines. "
                            "Preserve all special tags and placeholders like __PH_0__, [var], {b} exactly."
                        )
                    else:
                        system_prompt = (
                            "You are an expert visual novel and video game translator. "
                            f"Translate the following scene dialogue from {src_label} to {tgt_lang}. "
                            "Maintain character voice, emotional context, relationship dynamics, and natural dialogue flow.\n\n"
                            "Strict Rules:\n"
                            "1) Preserve ALL special tokens and tags exactly as they appear (like __PH_0__, __PH_1__, [var], {b}, {color=...}).\n"
                            "2) Return each line with its exact index tag matching the input: [0] Translated dialogue text\n"
                            "3) Do NOT translate or include the speaker's name in your output line (return only the dialogue content).\n"
                            "4) Do NOT skip any lines or combine multiple lines into one.\n"
                            "5) Do NOT add any preamble, conversational commentary, or markdown fences."
                        )
                    user_content = _build_scene_batch(protected_list, speakers_list)
            elif batch_format == "xml":
                use_json = False
                src_label = (
                    _resolve_language_name(src_lang)
                    if self._is_hy_mt2()
                    else _SUPPORTED_LANGUAGES.get(src_lang, src_lang)
                )
                tgt_lang = (
                    _resolve_language_name(tgt_lang_code)
                    if self._is_hy_mt2()
                    else _SUPPORTED_LANGUAGES.get(tgt_lang_code, tgt_lang_code)
                )
                if src_lang == "auto":
                    src_label = "the original language"

                if self._is_hy_mt2():
                    # Hy-MT2 model-card recipe: instruction in user message, no system prompt
                    system_prompt = None
                    instruction = (
                        f"Translate the text inside each <item id=\"N\"> element into {tgt_lang}. "
                        "Keep the exact same <translations> and <item id=\"N\"> XML structure. "
                        "Preserve all special tokens and placeholders (__PH_N__, [var], {tag}) exactly:\n\n"
                    )
                    user_content = instruction + _build_xml_batch(protected_list)
                else:
                    custom_prompt = None
                    if self.config_manager:
                        custom_prompt = getattr(self.config_manager.translation_settings, "ai_custom_system_prompt", None)

                    if custom_prompt and custom_prompt.strip():
                        system_prompt = (
                            custom_prompt.strip()
                            + "\n\nImportant: You must strictly enclose your translations in: "
                            "<translations><item id=\"N\">Translated text</item></translations>. "
                            "Preserve all placeholders and tags like __PH_0__, [var], {b} exactly."
                        )
                    else:
                        system_prompt = (
                            "You are a professional visual novel and game translator. "
                            f"Translate each text item from {src_label} to {tgt_lang}. "
                            "Strict Rules:\n"
                            "1) Preserve the exact XML structure: <translations><item id=\"N\">Translated text</item></translations>\n"
                            "2) Preserve ALL special placeholders, variables, and tags like __PH_0__, __PH_1__, [var], {b}, {color=...} exactly.\n"
                            "3) Do NOT add any preamble, conversational commentary, or markdown fences."
                        )
                    user_content = _build_xml_batch(protected_list)
            elif self._is_hy_mt2():
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

            # Parse response according to mode, with graceful multi-tier fallback
            if batch_format == "scene":
                parsed = _parse_scene_batch(response, len(chunk), speakers_list)
                if all(x is None for x in parsed):
                    # In case model returned JSON or XML unexpectedly
                    parsed = _parse_json_batch(response, len(chunk))
                    if all(x is None for x in parsed):
                        parsed = _parse_xml_batch(response, len(chunk))
            elif batch_format == "xml":
                parsed = _parse_xml_batch(response, len(chunk))
                if all(x is None for x in parsed):
                    parsed = _parse_json_batch(response, len(chunk))
                    if all(x is None for x in parsed):
                        parsed = _parse_scene_batch(response, len(chunk), speakers_list)
            else:
                # Try parsing as JSON first
                parsed = _parse_json_batch(response, len(chunk))

                # Fallback to XML if JSON parsing yielded nothing
                if all(x is None for x in parsed):
                    cfg = self.config_manager
                    if cfg is not None:
                        self.emit_log(
                            "warning",
                            cfg.get_log_text(
                                "ai_batch_json_parse_failed",
                                "AI returned a malformed batch response; falling back to individual translation.",
                            ),
                        )
                    parsed = _parse_xml_batch(response, len(chunk))
                    if all(x is None for x in parsed):
                        parsed = _parse_scene_batch(response, len(chunk), speakers_list)

            for i, (orig_idx, req) in enumerate(chunk):
                src_text = source_list[i]
                req_meta = req.metadata if isinstance(req.metadata, dict) else {}
                real_orig = req_meta.get('original_text') or src_text
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
                        translated = real_orig
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
                            translated = recovered if not still_missing else real_orig
                
                # Clean any leftover orphaned/mangled placeholder residues at the very end
                translated = _clean_orphaned_placeholders(translated)

                results[orig_idx] = TranslationResult(
                    real_orig, translated, req.source_lang, req.target_lang,
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

    async def probe_endpoint(self, timeout: float = 10.0) -> Optional[str]:
        """Cheap reachability/auth check before a run. None = usable, else a reason.

        Without it an unreachable server or a rejected key only showed up as
        per-batch retries for minutes, after which every line silently went to
        the Google fallback — users saw "translated" and Google-quality text
        while believing the AI engine did the work.
        """
        if not _OPENAI_AVAILABLE:
            return None
        try:
            client = self._get_client().with_options(timeout=timeout, max_retries=0)
            await client.models.list()
            return None
        except APIConnectionError as exc:
            return f"cannot connect to {self._base_url or 'the API'} ({exc.__class__.__name__})"
        except APIStatusError as exc:
            if exc.status_code in (401, 403):
                return f"the API rejected the key (HTTP {exc.status_code})"
            # 404/405/501: many OpenAI-compatible servers have no /models.
            return None
        except Exception as exc:
            self.logger.debug(f"[{self.__class__.__name__}] endpoint probe inconclusive: {exc}")
            return None


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
# Gemini Helpers — Safety Settings & Thinking Config
# ─────────────────────────────────────────────────────────────────────────────

def _build_gemini_safety_settings(safety_level: str = "BLOCK_NONE") -> List[Any]:
    """
    Constructs safety settings list matching the requested safety level across
    all standard HarmCategories in both official google.genai and legacy SDKs.
    """
    level = (safety_level or "BLOCK_NONE").upper().strip()
    if _GEMINI_MODE == "google_genai" and genai is not None and hasattr(genai, "types"):
        threshold_map = {
            "BLOCK_NONE": getattr(genai.types.HarmBlockThreshold, "BLOCK_NONE", "BLOCK_NONE"),
            "BLOCK_ONLY_HIGH": getattr(genai.types.HarmBlockThreshold, "BLOCK_ONLY_HIGH", "BLOCK_ONLY_HIGH"),
            "STANDARD": getattr(genai.types.HarmBlockThreshold, "BLOCK_MEDIUM_AND_ABOVE", "BLOCK_MEDIUM_AND_ABOVE"),
        }
        selected_threshold = threshold_map.get(level, threshold_map["BLOCK_NONE"])

        category_names = [
            "HARM_CATEGORY_HARASSMENT",
            "HARM_CATEGORY_HATE_SPEECH",
            "HARM_CATEGORY_SEXUALLY_EXPLICIT",
            "HARM_CATEGORY_DANGEROUS_CONTENT",
            "HARM_CATEGORY_CIVIC_INTEGRITY",
        ]
        settings = []
        for cat_name in category_names:
            cat = getattr(genai.types.HarmCategory, cat_name, None)
            if cat is not None and hasattr(genai.types, "SafetySetting"):
                try:
                    settings.append(genai.types.SafetySetting(category=cat, threshold=selected_threshold))
                except Exception:
                    pass
        return settings

    # Legacy SDK or fallback dict structure
    threshold_str = "BLOCK_NONE" if level == "BLOCK_NONE" else (
        "BLOCK_ONLY_HIGH" if level == "BLOCK_ONLY_HIGH" else "BLOCK_MEDIUM_AND_ABOVE"
    )
    return [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": threshold_str},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": threshold_str},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": threshold_str},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": threshold_str},
    ]


def _build_gemini_thinking_config(model: Optional[str] = None) -> Optional[Any]:
    """
    Returns ThinkingConfig with thinking_budget=0 for translation tasks.
    Prevents reasoning models (gemini-3.1-flash-lite, gemini-2.5-flash) from
    consuming unnecessary thought tokens or stalling response.text.
    Skips 1.x models which do not support ThinkingConfig.
    """
    if model and ("1.5" in model.lower() or "1.0" in model.lower()):
        return None
    if _GEMINI_MODE == "google_genai" and genai is not None and hasattr(genai, "types") and hasattr(genai.types, "ThinkingConfig"):
        try:
            return genai.types.ThinkingConfig(thinking_budget=0)
        except Exception:
            return None
    return None


_GEMINI_BATCH_SYSTEM_PROMPT = (
    "You are a professional game translator. "
    "Translate game dialogue and UI text from {src} to {tgt}. "
    "Rules: "
    "1) Preserve ALL special tokens/tags exactly: XML tags like <ph id=\"N\">...</ph>, [variable], {{tag}}, {{color=#fff}}. "
    "2) Maintain the tone, register, style, and natural flow of the dialogue. "
    "3) You will receive an XML block with numbered <item id=\"...\"> elements. "
    "Return the EXACT SAME XML structure with the translated text inside each <item>. "
    "Do NOT add markdown code ticks (```xml), explanations, notes, or extra content outside the XML."
)

_GEMINI_SINGLE_SYSTEM_PROMPT = (
    "You are a professional game translator. "
    "Translate game dialogue and UI text from {src} to {tgt}. "
    "Preserve ALL special placeholders and tags exactly: <ph id=\"N\">...</ph>, [variable], {{tag}}, {{color=#fff}}. "
    "Maintain the tone, register, and style of the original. "
    "Return ONLY the translated text without explanations, markdown ticks, or surrounding quotes."
)


# ─────────────────────────────────────────────────────────────────────────────
# GeminiTranslator — Google Gemini (official google-genai SDK)
# ─────────────────────────────────────────────────────────────────────────────

class GeminiTranslator(BaseTranslator):
    """
    Google Gemini translator supporting official google.genai and legacy SDKs.
    Features:
      - Full safety filter customization (default BLOCK_NONE for VN dialogue)
      - Zero-budget thinking config to prevent runaway reasoning tokens
      - Token-efficient XML batching to respect free tier RPM limits
      - Exponential backoff on rate limits (429)
      - Automatic fallback delegation to GoogleTranslator
    """

    def __init__(
        self,
        *args,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        safety_level: Optional[str] = None,
        temperature: Optional[float] = None,
        timeout: Optional[float] = None,
        max_tokens: Optional[int] = None,
        batch_size: Optional[int] = None,
        proxy_manager=None,
        config_manager=None,
        **kwargs,
    ) -> None:
        if not _GEMINI_AVAILABLE:
            raise ImportError(
                "google-genai is required for Gemini translation. "
                "Install it with: pip install google-genai"
            )

        cm = config_manager or kwargs.get('config_manager', None)
        resolved_key = api_key
        if not resolved_key and cm and hasattr(cm, 'api_keys'):
            resolved_key = cm.api_keys.gemini_api_key or ""
        if not resolved_key:
            resolved_key = "none"

        # Resolve model name with priority: explicit arg -> config -> default
        model_name = model or kwargs.get('model')
        if not model_name and cm and hasattr(cm, 'translation_settings'):
            model_name = getattr(cm.translation_settings, 'gemini_model', None)
        model_name = (model_name or "gemini-2.5-flash").strip()

        # Resolve safety level
        s_level = safety_level or kwargs.get('safety_level')
        if not s_level and cm and hasattr(cm, 'translation_settings'):
            s_level = getattr(cm.translation_settings, 'gemini_safety_settings', None)
        self._safety_level: str = (s_level or "BLOCK_NONE").strip()

        # Numeric translation settings
        ts_settings = getattr(cm, 'translation_settings', None) if cm else None
        self._temperature: float = (
            temperature if temperature is not None
            else getattr(ts_settings, 'ai_temperature', AI_DEFAULT_TEMPERATURE)
        )
        self._timeout: float = (
            timeout if timeout is not None
            else getattr(ts_settings, 'ai_timeout', AI_DEFAULT_TIMEOUT)
        )
        self._max_tokens: int = (
            max_tokens if max_tokens is not None
            else getattr(ts_settings, 'ai_max_tokens', AI_DEFAULT_MAX_TOKENS)
        )
        self._batch_size: int = min(
            batch_size or getattr(ts_settings, 'ai_batch_size', 15), 50
        )

        super().__init__(
            api_key=resolved_key,
            proxy_manager=proxy_manager or kwargs.get('proxy_manager', None),
            config_manager=cm,
        )
        self._model: str = model_name
        self._engine = TranslationEngine.GEMINI
        self._semaphore_count: int = max(1, int(kwargs.get('semaphore_count', 3) or 3))
        self._semaphore: Optional[asyncio.Semaphore] = None

        if _GEMINI_MODE == "google_genai" and genai is not None:
            client_kwargs: Dict[str, Any] = {}
            if resolved_key and resolved_key != "none":
                client_kwargs["api_key"] = resolved_key
            self._client = genai.Client(**client_kwargs)
        else:
            if resolved_key and resolved_key != "none" and genai is not None and hasattr(genai, "configure"):
                genai.configure(api_key=resolved_key)
            if genai is not None and hasattr(genai, "GenerativeModel"):
                self._client = genai.GenerativeModel(model_name)
            else:
                self._client = None

    def _build_content_config(
        self,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Optional[Any]:
        """Builds a comprehensive GenerateContentConfig for google.genai."""
        if _GEMINI_MODE != "google_genai" or genai is None or not hasattr(genai, "types"):
            return None

        cfg_class = getattr(genai.types, "GenerateContentConfig", None)
        if not cfg_class:
            return None

        kwargs: Dict[str, Any] = {
            "temperature": temperature if temperature is not None else self._temperature,
            "max_output_tokens": max_tokens if max_tokens is not None else self._max_tokens,
        }

        safety_settings = _build_gemini_safety_settings(self._safety_level)
        if safety_settings:
            kwargs["safety_settings"] = safety_settings

        thinking_cfg = _build_gemini_thinking_config(self._model)
        if thinking_cfg is not None:
            kwargs["thinking_config"] = thinking_cfg

        if system_prompt:
            kwargs["system_instruction"] = system_prompt

        try:
            return cfg_class(**kwargs)
        except Exception as exc:
            self.logger.warning("Failed to build GenerateContentConfig (%s): %s", type(exc).__name__, exc)
            return None

    def _get_semaphore(self) -> asyncio.Semaphore:
        # Created lazily so it binds to the event loop that actually runs the
        # translation (the pipeline creates a fresh loop per run).
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._semaphore_count)
        return self._semaphore

    @staticmethod
    def _build_fallback_request(req: TranslationRequest, fallback: Any) -> TranslationRequest:
        """
        Builds a clean request for the fallback engine.

        Pipeline requests carry XML-protected text (<ph id="N">..</ph>) that only
        the AI prompt understands; the fallback (GoogleTranslator) must receive the
        original source text and apply its own protection scheme.
        """
        metadata = req.metadata if isinstance(req.metadata, dict) else {}
        original = metadata.get('original_text') or req.text
        fb_meta = {
            k: v for k, v in metadata.items()
            if k not in ('preprotected', 'placeholders', 'xml_mode')
        }
        fb_meta['original_text'] = original
        fb_engine = getattr(fallback, '_engine', None) or req.engine
        return TranslationRequest(
            text=original,
            source_lang=req.source_lang,
            target_lang=req.target_lang,
            engine=fb_engine,
            metadata=fb_meta,
        )

    async def _delegate_to_fallback(self, req: TranslationRequest, error: str = "") -> TranslationResult:
        """Invokes the attached fallback translator (if any) with an unprotected request."""
        fallback = getattr(self, "fallback_translator", None) or getattr(self, "_fallback", None)
        if fallback is not None:
            try:
                fb_req = self._build_fallback_request(req, fallback)
                res = await fallback.translate_single(fb_req)
                if res and res.success and (res.translated_text or "").strip():
                    meta = dict(req.metadata) if isinstance(req.metadata, dict) else {}
                    fb_engine = getattr(fallback, '_engine', None)
                    meta['fallback_engine'] = getattr(fb_engine, 'value', str(fb_engine or 'fallback'))
                    # Keep engine=GEMINI so TranslationManager cache keys stay coherent;
                    # provenance is recorded in metadata['fallback_engine'].
                    return TranslationResult(
                        original_text=req.text,
                        translated_text=res.translated_text,
                        source_lang=req.source_lang,
                        target_lang=req.target_lang,
                        engine=TranslationEngine.GEMINI,
                        success=True,
                        confidence=getattr(res, 'confidence', 0.0),
                        metadata=meta,
                    )
            except Exception as fb_exc:
                self.logger.warning("Gemini fallback translator failed: %s", fb_exc)
        req_meta = req.metadata if isinstance(req.metadata, dict) else {}
        return TranslationResult(
            original_text=req.text,
            # Never surface XML-protected text; echo the clean source instead.
            translated_text=req_meta.get('original_text') or req.text,
            source_lang=req.source_lang,
            target_lang=req.target_lang,
            engine=TranslationEngine.GEMINI,
            success=False,
            error=error or "Gemini translation failed and no fallback succeeded",
            metadata=req_meta,
        )

    @staticmethod
    def _strip_response_noise(text: str) -> str:
        """Removes markdown code fences the model may wrap around its answer."""
        t = (text or "").strip()
        if t.startswith("```"):
            t = re.sub(r'^```[a-zA-Z]*\s*', '', t)
            t = re.sub(r'\s*```$', '', t)
        return t.strip()

    def _finalize_translation(self, req: TranslationRequest, raw: str) -> Optional[str]:
        """
        Restores protected Ren'Py syntax in a raw model answer and validates it.

        Returns the restored text, or None when placeholders were lost (the caller
        then delegates to the fallback engine instead of emitting corrupted text).
        """
        text = self._strip_response_noise(raw)
        if not text:
            return None
        metadata = req.metadata if isinstance(req.metadata, dict) else {}
        placeholders = metadata.get('placeholders') or {}
        if not isinstance(placeholders, dict) or not placeholders:
            return text

        if metadata.get('xml_mode', True):
            restored = restore_renpy_syntax_xml(text, placeholders)
        else:
            restored = restore_renpy_syntax(text, placeholders)
            if validate_translation_integrity(restored, placeholders):
                recovered = _recover_placeholders_levenshtein(req.text, text, placeholders)
                restored = restore_renpy_syntax(recovered, placeholders)

        if validate_translation_integrity(restored, placeholders):
            return None
        return restored

    async def _generate(
        self,
        contents: str,
        system_instruction: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Performs one Gemini API call (official or legacy SDK) and returns raw text."""
        if _GEMINI_MODE == "google_genai" and self._client:
            config = self._build_content_config(
                system_prompt=system_instruction,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=self._model,
                    contents=contents,
                    config=config,
                ),
                timeout=self._timeout,
            )
        elif self._client:
            loop = asyncio.get_running_loop()
            gen_cfg = None
            if genai is not None and hasattr(genai, "types") and hasattr(genai.types, "GenerationConfig"):
                gen_cfg = genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                )
            safety_cfg = _build_gemini_safety_settings(self._safety_level)
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self._client.generate_content(
                        f"{system_instruction}\n\n{contents}",
                        generation_config=gen_cfg,
                        safety_settings=safety_cfg,
                    ),
                ),
                timeout=self._timeout,
            )
        else:
            return ""

        text = getattr(response, "text", None) if response else None
        return text.strip() if isinstance(text, str) else ""

    @staticmethod
    def _classify_error(exc: BaseException) -> Tuple[bool, bool]:
        """Returns (is_quota, is_safety) for a Gemini exception."""
        msg = str(exc)
        upper = msg.upper()
        is_quota = "429" in msg or "RESOURCE_EXHAUSTED" in upper or "QUOTA" in upper
        is_safety = "SAFETY" in upper or "blocked" in msg.lower() or "PROHIBITED_CONTENT" in upper
        return is_quota, is_safety

    async def translate_single(self, request: TranslationRequest) -> TranslationResult:
        """Translate a single text using Gemini with safety, thinking guard, and fallback."""
        source_lang = request.source_lang or "auto"
        target_lang = request.target_lang or "en"
        src_name = _SUPPORTED_LANGUAGES.get(source_lang, source_lang)
        tgt_name = _SUPPORTED_LANGUAGES.get(target_lang, target_lang)
        metadata = request.metadata if isinstance(request.metadata, dict) else {}

        source_text = request.text or ""
        if not source_text.strip():
            return TranslationResult(
                original_text=source_text,
                translated_text=source_text,
                source_lang=source_lang,
                target_lang=target_lang,
                engine=TranslationEngine.GEMINI,
                success=True,
                metadata=metadata,
            )

        system_instruction = _GEMINI_SINGLE_SYSTEM_PROMPT.format(src=src_name, tgt=tgt_name)
        prompt = f"Translate the following text from {src_name} to {tgt_name}:\n{source_text}"
        max_tokens = getattr(request, 'max_tokens', None) or self._max_tokens
        temperature = getattr(request, 'temperature', None)
        if temperature is None:
            temperature = self._temperature

        last_error = ""
        for attempt in range(3):
            if self.should_stop_callback and self.should_stop_callback():
                break
            try:
                async with self._get_semaphore():
                    raw = await self._generate(prompt, system_instruction, max_tokens, temperature)
            except Exception as exc:
                last_error = str(exc) or type(exc).__name__
                is_quota, is_safety = self._classify_error(exc)

                if is_safety:
                    self.logger.warning(
                        "Gemini safety filter triggered on text %r. Delegating to fallback.", source_text[:40]
                    )
                    return await self._delegate_to_fallback(request, "Content blocked by safety filter")

                if is_quota:
                    if attempt < 2:
                        wait = _jitter_sleep(2.0, attempt)
                        self.logger.warning("Gemini 429 quota hit. Retrying in %.1fs...", wait)
                        await asyncio.sleep(wait)
                        continue
                    res = await self._delegate_to_fallback(request, last_error)
                    if not res.success:
                        res.quota_exceeded = True
                    return res

                self.logger.error("Gemini translation error: %s", exc)
                if attempt < 2:
                    await asyncio.sleep(1.0)
                continue

            if not raw:
                # Empty response text (blocked or runaway thinking) -> delegate to fallback
                self.logger.warning("Gemini returned empty text for %r; attempting fallback.", source_text[:40])
                return await self._delegate_to_fallback(request, "Empty response from Gemini")

            final = self._finalize_translation(request, raw)
            if final is None:
                self.logger.warning(
                    "Gemini lost protected placeholders for %r; attempting fallback.", source_text[:40]
                )
                return await self._delegate_to_fallback(request, "Placeholder integrity check failed")

            return TranslationResult(
                original_text=source_text,
                translated_text=final,
                source_lang=source_lang,
                target_lang=target_lang,
                engine=TranslationEngine.GEMINI,
                success=True,
                confidence=0.9,
                metadata=metadata,
            )

        return await self._delegate_to_fallback(request, last_error)

    async def _translate_chunk(self, chunk: List[TranslationRequest]) -> List[TranslationResult]:
        """Translates one XML batch chunk; falls back per item or per chunk on failure."""
        source_lang = chunk[0].source_lang or "auto"
        target_lang = chunk[0].target_lang or "en"
        src_name = _SUPPORTED_LANGUAGES.get(source_lang, source_lang)
        tgt_name = _SUPPORTED_LANGUAGES.get(target_lang, target_lang)

        xml_batch = _build_xml_batch([r.text for r in chunk])
        system_instruction = _GEMINI_BATCH_SYSTEM_PROMPT.format(src=src_name, tgt=tgt_name)
        # Batch token budget: allocate proportionally up to 8192
        batch_max_tokens = min(8192, max(2048, len(chunk) * 200))

        parsed: Optional[List[Optional[str]]] = None
        for attempt in range(3):
            if self.should_stop_callback and self.should_stop_callback():
                break
            try:
                async with self._get_semaphore():
                    response_text = await self._generate(
                        xml_batch, system_instruction, batch_max_tokens, self._temperature
                    )
            except Exception as exc:
                is_quota, is_safety = self._classify_error(exc)
                if is_safety:
                    self.logger.warning("Gemini batch hit safety filter. Splitting batch into individual requests.")
                    break
                if is_quota:
                    if attempt < 2:
                        wait = _jitter_sleep(2.5, attempt)
                        self.logger.warning("Gemini batch 429 rate limit. Retrying in %.1fs...", wait)
                        await asyncio.sleep(wait)
                        continue
                    break
                self.logger.error("Gemini batch translation error on attempt %d: %s", attempt + 1, exc)
                if attempt < 2:
                    await asyncio.sleep(1.0)
                continue

            if response_text:
                candidate = _parse_xml_batch(response_text, len(chunk))
                if any(t is not None for t in candidate):
                    parsed = candidate
                    break
            self.logger.warning(
                "Gemini batch attempt %d returned unparseable or empty XML. Response preview: %r",
                attempt + 1, (response_text or "")[:150],
            )

        results: List[TranslationResult] = []
        if parsed is not None:
            for i, req in enumerate(chunk):
                val = parsed[i] if i < len(parsed) else None
                final = self._finalize_translation(req, val) if val is not None else None
                if final is not None:
                    results.append(TranslationResult(
                        original_text=req.text,
                        translated_text=final,
                        source_lang=source_lang,
                        target_lang=target_lang,
                        engine=TranslationEngine.GEMINI,
                        success=True,
                        confidence=0.9,
                        metadata=req.metadata if isinstance(req.metadata, dict) else {},
                    ))
                else:
                    # Item missing from the batch answer or lost its placeholders
                    results.append(await self.translate_single(req))
            return results

        # Whole chunk failed: item-by-item (translate_single handles 429/safety/fallback itself)
        self.logger.warning("Gemini XML batch failed; falling back to item-by-item translation.")
        for req in chunk:
            results.append(await self.translate_single(req))
        return results

    async def translate_batch(self, requests: List[TranslationRequest]) -> List[TranslationResult]:
        """
        Translates requests in structured XML chunks of `ai_batch_size` (max 50) items.
        Chunks run concurrently, bounded by the request semaphore, to respect
        Free Tier RPM limits while keeping throughput on paid tiers.
        """
        if not requests:
            return []
        if len(requests) == 1:
            return [await self.translate_single(requests[0])]

        chunk_size = max(1, int(self._batch_size or 1))
        chunks = [requests[i:i + chunk_size] for i in range(0, len(requests), chunk_size)]
        chunk_results = await asyncio.gather(*(self._translate_chunk(c) for c in chunks))

        results: List[TranslationResult] = []
        for cr in chunk_results:
            results.extend(cr)
        return results

    async def close(self) -> None:
        await super().close()
        if hasattr(self, "_client") and self._client and hasattr(self._client, "close"):
            try:
                self._client.close()
            except Exception:
                pass

    def get_supported_languages(self) -> Dict[str, str]:
        return {
            "en": "English", "tr": "Turkish", "de": "German",
            "fr": "French", "es": "Spanish", "ru": "Russian",
            "ja": "Japanese", "zh": "Chinese", "ko": "Korean",
            "ar": "Arabic", "fa": "Persian", "it": "Italian",
            "pt": "Portuguese", "nl": "Dutch", "pl": "Polish",
        }

