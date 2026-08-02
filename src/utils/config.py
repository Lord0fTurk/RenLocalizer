"""
Configuration Manager
====================

Manages application settings and configuration.
"""

import json
import logging
import locale
import os
import sys
import threading
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict, fields
from enum import Enum
from src.utils.constants import (
    AI_DEFAULT_TEMPERATURE,
    AI_DEFAULT_TIMEOUT,
    AI_DEFAULT_MAX_TOKENS,
    AI_MAX_RETRIES,
    MAX_CHARS_PER_REQUEST,
    WINDOW_DEFAULT_WIDTH,
)


class Language(Enum):
    """Supported UI languages."""

    TURKISH = "tr"
    ENGLISH = "en"
    GERMAN = "de"
    FRENCH = "fr"
    SPANISH = "es"
    RUSSIAN = "ru"
    PERSIAN = "fa"
    CHINESE_S = "zh-CN"
    JAPANESE = "ja"


TURKIC_PRIMARY_LANG_IDS = {
    0x1F,  # Turkish
    0x2C,  # Azerbaijani
    0x29,  # Persian (Azeri regions often use this)
    0x3F,  # Kazakh
    0x40,  # Kyrgyz
    0x42,  # Turkmen
    0x43,  # Uzbek
    0x44,  # Tatar
}

TURKIC_LANGUAGE_CODES = {
    "tr",
    "az",
    "azb",
    "tk",
    "uz",
    "kk",
    "ky",
    "tt",
    "ba",
    "ug",
    "sah",
    "kaa",
}

VALID_APP_THEMES: tuple[str, ...] = (
    "dark",
    "light",
    "red",
    "turquoise",
    "green",
    "neon",
    "auto",
)

MAX_GENERAL_BATCH_SIZE = 10000
MAX_AI_BATCH_SIZE = 10000
ENGINE_BATCH_SIZE_CAPS: dict[str, int] = {
    "google": 1000,
    "yandex": 1000,
}

EXTRACTION_MODE_THRESHOLDS: dict[str, float] = {
    "strict": 0.85,
    "balanced": 0.58,
    "aggressive": 0.35,
}

LEGACY_APP_SETTING_ALIASES: dict[str, str] = {
    "theme": "app_theme",
}


def _is_turkic_locale(code: str) -> bool:
    normalized = (code or "").lower().replace("_", "-")
    primary = normalized.split("-")[0]
    return primary in TURKIC_LANGUAGE_CODES


def normalize_engine_code(engine: Any) -> str:
    """Normalize engine enum/string values to a lowercase config code."""
    if hasattr(engine, "value"):
        engine = getattr(engine, "value")
    return str(engine or "").strip().lower()


def get_engine_batch_size_cap(engine: Any) -> Optional[int]:
    """Return the hard cap for engines that require a lower effective batch size."""
    return ENGINE_BATCH_SIZE_CAPS.get(normalize_engine_code(engine))


def get_effective_batch_size(requested: int, engine: Any) -> int:
    """Apply engine-specific hard limits while preserving the stored user setting."""
    try:
        requested_int = max(1, int(requested))
    except (ValueError, TypeError):
        requested_int = 1

    cap = get_engine_batch_size_cap(engine)
    return min(requested_int, cap) if cap is not None else requested_int


def _build_ui_lang_map() -> dict[str, str]:
    """Build a mapping from locale codes to available UI language codes."""
    return {
        "tr": "tr",
        "az": "tr",
        "en": "en",
        "de": "de",
        "fr": "fr",
        "es": "es",
        "ru": "ru",
        "fa": "fa",
        "zh": "zh-CN",
        "ja": "ja",
    }


def detect_system_language() -> str:
    """Detect the system language and return appropriate UI language code."""
    logger = logging.getLogger(__name__)
    lang_map = _build_ui_lang_map()
    try:
        # Method 1: Windows locale detection
        if os.name == "nt":
            try:
                import ctypes

                lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
                primary_lang = lang_id & 0x3FF

                _WIN_LANG_MAP = {
                    0x09: "en",
                    0x07: "de",
                    0x0C: "fr",
                    0x0A: "es",
                    0x19: "ru",
                    0x29: "fa",
                    0x04: "zh-CN",
                    0x11: "ja",
                }
                if primary_lang in TURKIC_PRIMARY_LANG_IDS:
                    return "tr"
                if primary_lang in _WIN_LANG_MAP:
                    return _WIN_LANG_MAP[primary_lang]
            except Exception:
                logger.debug("Failed to detect Windows language")

        # Method 2: Standard locale detection (Linux/macOS)
        try:
            system_locale = locale.getlocale()[0]
            if system_locale:
                if _is_turkic_locale(system_locale):
                    return "tr"
                lang_part = system_locale.split("_")[0].lower()
                if lang_part in lang_map:
                    return lang_map[lang_part]
        except Exception:
            logger.debug("Failed to detect Unix locale language")

        # Method 3: Environment variables
        try:
            for env_var in ["LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES"]:
                env_value = os.environ.get(env_var, "").lower()
                if not env_value:
                    continue
                if _is_turkic_locale(env_value):
                    return "tr"
                for code, ui_code in lang_map.items():
                    if code in env_value:
                        return ui_code
        except Exception:
            logger.debug("Failed to detect language from environment")

        return "en"
    except Exception:
        return "en"


@dataclass
class TranslationSettings:
    """Translation-related settings."""

    selected_engine: str = "google"  # Persisted engine selection (google, deepl, openai, gemini, local_llm, libretranslate, yandex)
    source_language: str = "auto"
    target_language: str = "tr"
    max_concurrent_threads: int = 8  # Lowered from 32 to prevent instant Google bans
    request_delay: float = (
        0.15  # Delay between requests (seconds) — also used by Google translator
    )
    max_batch_size: int = (
        100  # Default batch size (user adjustable, lower = more stable)
    )
    enable_proxy: bool = False  # Disabled by default
    enable_parallel_batch: bool = True  # Toplu çeviride paralel (semaphore) isteklere izin ver (kapatılabilir)
    max_retries: int = 3
    timeout: int = 30
    enable_runtime_hook: bool = True
    # Multi-endpoint Google Translator settings (v2.1.0)
    use_multi_endpoint: bool = True  # Birden fazla Google mirror kullan
    enable_lingva_fallback: bool = (
        True  # Lingva fallback (ücretsiz, API key gerektirmez)
    )
    max_chars_per_request: int = (
        MAX_CHARS_PER_REQUEST  # Bir istekteki maksimum karakter
    )
    # Glossary & critical terms
    # Glossary & critical terms
    glossary_file: str = "glossary.json"  # Terim sözlüğü yolu (proje köküne göre)
    critical_terms_file: str = "critical_terms.json"  # Kritik kelimeler listesi
    # Type-based translation filters
    translate_dialogue: bool = True
    translate_menu: bool = True
    translate_ui: bool = True
    translate_config_strings: bool = True
    translate_gui_strings: bool = True
    translate_style_strings: bool = True
    translate_renpy_functions: bool = True
    # NEW: Extended text type filters (v2.2.0)
    translate_buttons: bool = True  # textbutton metinleri
    translate_alt_text: bool = (
        True  # imagebutton/hotspot/hotbar alt metinleri (erişilebilirlik)
    )
    translate_input_text: bool = True  # input default/prefix/suffix metinleri
    translate_notifications: bool = True  # Notify() ve renpy.notify() metinleri
    translate_confirmations: bool = True  # Confirm() ve renpy.confirm() metinleri
    translate_define_strings: bool = True  # define statements ile tanımlanan stringler
    translate_character_names: bool = False  # NEW: Character("Name") isimleri

    # v2.8.7: Native TLID output mode — generates translate <lang> <label>_<hash>:
    # blocks instead of translate <lang> strings: for dialogues. UI text stays strings:.
    # Runtime hook still active but handles only UI/screen text when native mode enabled.
    output_mode: str = "native"  # "strings" | "native"
    # Deep Scan: Normal pattern'lerin kaçırdığı gizli stringleri bul
    # init python bloklarındaki dictionary'ler, değişken atamaları vb.
    enable_deep_scan: bool = True  # Varsayılan artık açık (gizli string taraması)
    # RPYC Reader: Derlenmiş .rpyc dosyalarını AST ile doğrudan oku
    enable_rpyc_reader: bool = True  # Varsayılan artık açık (derlenmiş .rpyc okuma)
    # Unrpyc Decompile: .rpyc → .rpy decompile edip regex parser ile de tara (complementary)
    # Mevcut rpyc_reader'ın yanında çalışır; daha fazla metin yakalanır.
    # Gereksinim: unrpyc (pip install git+https://github.com/CensoredUsername/unrpyc.git)
    # veya rpycdec (pip install rpycdec) kurulu olmalıdır.
    enable_unrpyc_decompile: bool = (
        True  # Varsayılan açık (kurulu değilse sessizce atlanır)
    )
    # Deep Extraction v2.7.1: Extended extraction for non-standard patterns
    enable_deep_extraction: bool = (
        True  # Master toggle for all deep extraction features
    )
    deep_extraction_bare_defines: bool = True  # define var = "text" without _() wrapper
    deep_extraction_bare_defaults: bool = (
        True  # default var = "text" without _() wrapper
    )
    deep_extraction_fstrings: bool = True  # f-string template extraction
    deep_extraction_multiline_structures: bool = True  # Multi-line dict/list parsing
    deep_extraction_extended_api: bool = True  # Extended Ren'Py API call coverage
    deep_extraction_tooltip_properties: bool = True  # tooltip property extraction
    deep_extraction_screen_arguments: bool = (
        True  # call/show screen positional string args
    )
    deep_extraction_displayable_calls: bool = (
        True  # screen helper/displayable call args
    )
    extraction_mode: str = "balanced"  # strict | balanced | aggressive
    minimum_extraction_confidence: float = 0.58  # Drop only low-confidence candidates
    # Delimiter-Aware Translation (v2.7.2): Split pipe-delimited variant text before translation
    # Handles patterns like <seg1|seg2|seg3> commonly used for random NPC dialogue
    enable_delimiter_aware_translation: bool = True
    # Include renpy/common from installed Ren'Py SDKs (optional)
    include_engine_common: bool = True
    context_limit: int = 10  # Number of surrounding lines for context
    # AI Settings (v2.5.0)
    openai_model: str = "gpt-3.5-turbo"
    openai_base_url: str = ""  # For OpenRouter or Local
    gemini_model: str = "gemini-2.5-flash"
    gemini_safety_settings: str = "BLOCK_NONE"  # BLOCK_NONE, BLOCK_ONLY_HIGH, STANDARD
    local_llm_model: str = "llama3.2"
    local_llm_url: str = "http://localhost:11434/v1"
    local_llm_timeout: int = (
        300  # Local LLM için ayrı timeout (saniye) - yerel modeller daha yavaş olabilir
    )
    libretranslate_url: str = "http://localhost:5000"  # Local LibreTranslate Endpoint
    libretranslate_api_key: str = ""  # Optional API key for managed instances
    custom_endpoint_url: str = ""  # Custom translation API endpoint
    custom_endpoint_api_key: str = ""  # Optional API key for custom endpoint
    # Advanced AI Settings
    ai_temperature: float = AI_DEFAULT_TEMPERATURE  # 0.0-1.0, lower = more consistent, higher = more creative
    ai_timeout: int = AI_DEFAULT_TIMEOUT  # seconds, timeout for AI requests
    ai_max_tokens: int = AI_DEFAULT_MAX_TOKENS  # max output tokens
    ai_batch_size: int = 50  # Number of lines per AI request batch (1-10000)
    ai_retry_count: int = AI_MAX_RETRIES  # number of retries on failure
    ai_concurrency: int = 2  # NEW: Maximum concurrent requests for AI engines
    ai_request_delay: float = 1.5  # NEW: Delay between AI requests (seconds)
    ai_custom_system_prompt: str = (
        ""  # User-defined system prompt (empty = use built-in)
    )
    # Aggressive Translation Retry: Retry unchanged translations with Lingva/alt endpoints (slower but more thorough)
    aggressive_retry_translation: bool = (
        False  # Default off for speed (user can enable)
    )
    # NEW: Directory & File filtering (v2.5.2)
    exclude_system_folders: bool = (
        True  # Automatically skip renpy/, cache/, saves/, etc.
    )
    scan_rpym_files: bool = False  # Changed to False to save API usage/time       # Skip .rpym and .rpymc files by default (usually technical)
    auto_generate_hook: bool = (
        True  # Automatically generate Runtime Hook after translation
    )
    runtime_string_diagnostics: bool = (
        False  # Write bounded runtime miss diagnostics from the hook
    )
    # NEW: Cache Management (v2.5.3)
    use_global_cache: bool = (
        True  # Global cache (keeps translations in program folder for portability)
    )
    use_cache: bool = True  # Translation Memory cache enabled
    cache_path: str = "cache"  # Global cache directory name
    # DeepL Settings
    deepl_formality: str = (
        "default"  # default, formal, informal - Hitap şekli (Sen/Siz)
    )
    # v2.7.1: Custom function parameter extraction config
    # Users can define which function calls to extract and which params are translatable
    # Format: {"func_name": {"pos": [0, 1], "kw": ["prompt"]}} — same as DeepExtractionConfig.TIER1_TEXT_CALLS
    # Example: {"Quest": {"pos": [0, 1, 2]}, "large_notify": {"pos": [0, 1]}}
    custom_function_params: str = (
        "{}"  # JSON string (dataclass doesn't support dict default)
    )
    # v2.7.1: Auto-protect character names from translation
    # When enabled, Character() define names are auto-added to glossary (name → name)
    auto_protect_character_names: bool = True
    # Runtime Translation Hook (Zorla Çeviri)
    # DEPRECATED: Use auto_generate_hook instead. Kept for backwards compatibility.
    force_runtime_translation: bool = (
        False  # Oyun içi metinleri zorla çevir (eksik !t flagleri için)
    )
    # Debug/Development settings
    show_debug_engines: bool = (
        False  # Pseudo-Localization gibi debug motorlarını ana listede göster
    )
    # HTML Wrap Protection (v2.6.7) - <span translate="no"> tag protection
    # Default: True - Google Translate'e HTML span'ları göz ardı etmesini söyler
    # Modern approach (v2.6.7): Token'lar yerine HTML span'lar daha güvenilir
    use_html_protection: bool = False

    # External Translation Memory (v2.7.3) — harici TM desteği
    use_external_tm: bool = False  # TM lookup aktif mi
    external_tm_match_mode: str = "exact"  # "exact" | "fuzzy"
    external_tm_fuzzy_threshold: float = 0.85  # Fuzzy match eşik değeri (0.5–1.0)
    external_tm_sources: str = "[]"  # Aktif TM kaynak yolları (JSON string)

    def __post_init__(self):
        """Validate and clamp all numeric/enum fields to safe ranges."""

        def _safe_int(val, default: int, lo: int, hi: int) -> int:
            try:
                return max(lo, min(int(val), hi))
            except (ValueError, TypeError):
                return default

        def _safe_float(val, default: float, lo: float, hi: float) -> float:
            try:
                return max(lo, min(float(val), hi))
            except (ValueError, TypeError):
                return default

        # --- Numeric clamps (prevent infinite loops, deadlocks, OOM) ---
        self.max_concurrent_threads = _safe_int(self.max_concurrent_threads, 4, 1, 64)
        self.request_delay = _safe_float(self.request_delay, 0.5, 0.0, 60.0)
        self.max_batch_size = _safe_int(
            self.max_batch_size, 100, 1, MAX_GENERAL_BATCH_SIZE
        )
        self.max_retries = _safe_int(self.max_retries, 3, 1, 20)
        self.timeout = _safe_int(self.timeout, 30, 5, 600)
        self.max_chars_per_request = _safe_int(
            self.max_chars_per_request, 4500, 100, 50000
        )
        self.context_limit = _safe_int(self.context_limit, 5, 1, 100)
        self.local_llm_timeout = _safe_int(self.local_llm_timeout, 120, 10, 3600)
        self.ai_temperature = _safe_float(self.ai_temperature, 0.3, 0.0, 2.0)
        self.ai_timeout = _safe_int(self.ai_timeout, 60, 5, 600)
        self.ai_max_tokens = _safe_int(self.ai_max_tokens, 4096, 64, 32768)
        self.ai_batch_size = _safe_int(self.ai_batch_size, 50, 1, MAX_AI_BATCH_SIZE)
        self.ai_retry_count = _safe_int(self.ai_retry_count, 3, 0, 20)
        self.ai_concurrency = _safe_int(self.ai_concurrency, 1, 1, 20)
        self.ai_request_delay = _safe_float(self.ai_request_delay, 1.5, 0.0, 60.0)

        # --- Enum / allowlist checks ---
        _valid_engines = (
            "google",
            "deepl",
            "openai",
            "gemini",
            "local_llm",
            "libretranslate",
            "custom",
            "yandex",
            "pseudo",
            "opus_mt",
        )
        if self.selected_engine not in _valid_engines:
            self.selected_engine = "google"
        if self.output_mode not in ("strings", "native"):
            self.output_mode = "native"
        if self.deepl_formality not in ("default", "formal", "informal"):
            self.deepl_formality = "default"
        if self.gemini_safety_settings not in (
            "BLOCK_NONE",
            "BLOCK_ONLY_HIGH",
            "STANDARD",
        ):
            self.gemini_safety_settings = "BLOCK_NONE"
        extraction_mode = str(self.extraction_mode).strip().lower() or "balanced"
        if extraction_mode not in EXTRACTION_MODE_THRESHOLDS:
            extraction_mode = "balanced"
        self.extraction_mode = extraction_mode
        self.minimum_extraction_confidence = EXTRACTION_MODE_THRESHOLDS[extraction_mode]

        # --- String sanitisation ---
        self.source_language = str(self.source_language).strip() or "auto"
        self.target_language = str(self.target_language).strip() or "tr"
        self.openai_base_url = str(self.openai_base_url).strip()
        self.local_llm_url = (
            str(self.local_llm_url).strip() or "http://localhost:11434/v1"
        )
        self.libretranslate_url = (
            str(self.libretranslate_url).strip() or "http://localhost:5000"
        )
        self.libretranslate_api_key = str(self.libretranslate_api_key).strip()

        # --- JSON field validation ---
        try:
            json.loads(self.custom_function_params)
        except (json.JSONDecodeError, TypeError):
            self.custom_function_params = "{}"

        # External TM validation (v2.7.3)
        if self.external_tm_match_mode not in ("exact", "fuzzy"):
            self.external_tm_match_mode = "exact"
        self.external_tm_fuzzy_threshold = _safe_float(
            self.external_tm_fuzzy_threshold, 0.85, 0.5, 1.0
        )
        try:
            parsed = json.loads(self.external_tm_sources)
            if not isinstance(parsed, list) or not all(
                isinstance(p, str) for p in parsed
            ):
                self.external_tm_sources = "[]"
        except (json.JSONDecodeError, TypeError):
            self.external_tm_sources = "[]"


@dataclass
class ApiKeys:
    """API keys for various translation services."""

    deepl_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""

    def __post_init__(self):
        """Strip whitespace from all API keys."""
        self.deepl_api_key = (self.deepl_api_key or "").strip()
        self.openai_api_key = (self.openai_api_key or "").strip()
        self.gemini_api_key = (self.gemini_api_key or "").strip()


@dataclass
class AppSettings:
    """General application settings."""

    ui_language: str = ""  # Will be auto-detected if empty
    app_theme: str = "dark"  # Application theme preset
    last_input_directory: str = ""
    check_for_updates: bool = True
    # Output format: 'old_new' (Ren'Py official old/new blocks, recommended) or 'simple' (legacy)
    output_format: str = "old_new"
    # UnRen integration (Auto RPA Extraction)
    unren_auto_download: bool = True
    # Path to Ren'Py SDK directory (for engine lint). Leave empty for auto-detection.
    renpy_sdk_path: str = ""

    def __post_init__(self):
        """Validate enum/allowlist fields."""
        normalized_theme = str(self.app_theme).strip().lower()
        if normalized_theme not in VALID_APP_THEMES:
            normalized_theme = "dark"
        self.app_theme = normalized_theme
        if self.output_format not in ("old_new", "simple"):
            self.output_format = "old_new"
        self.ui_language = str(self.ui_language).strip()


@dataclass
class ProxySettings:
    """Proxy-related settings."""

    enabled: bool = False  # Disabled by default
    auto_rotate: bool = True
    test_on_startup: bool = True
    update_interval: int = 3600  # seconds
    max_failures: int = 10
    proxy_url: str = ""  # User's personal proxy (e.g. http://user:pass@host:port)
    manual_proxies: list = None

    def __post_init__(self):
        if self.manual_proxies is None:
            self.manual_proxies = []
        # Clamp numeric fields (safe against None/string values)
        try:
            self.update_interval = max(60, min(int(self.update_interval), 86400))
        except (ValueError, TypeError):
            self.update_interval = 3600
        try:
            self.max_failures = max(1, min(int(self.max_failures), 100))
        except (ValueError, TypeError):
            self.max_failures = 10
        self.proxy_url = (self.proxy_url or "").strip()


class ConfigManager:
    """Manages application configuration."""

    def __init__(self, config_file: str = "config.json"):
        self.logger = logging.getLogger(__name__)

        # Determine and initialize the dynamic data path (System vs Portable)
        from src.utils.path_manager import get_data_path, ensure_data_directories

        self.data_dir = get_data_path()
        ensure_data_directories(self.data_dir)

        self.config_file = self.data_dir / config_file
        self._lock = threading.Lock()  # Thread-safety for configuration

        # Get the correct locales directory for both dev and executable
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            # Running as PyInstaller executable
            self.locales_dir = Path(sys._MEIPASS) / "locales"
        else:
            # Running in development
            self.locales_dir = Path("locales")

        # Default configuration
        self.translation_settings = TranslationSettings()
        self.translation_settings.target_language = self.normalize_renpy_language_code(
            self.translation_settings.target_language
        )
        if (
            self.translation_settings.source_language
            and self.translation_settings.source_language != "auto"
        ):
            self.translation_settings.source_language = (
                self.normalize_renpy_language_code(
                    self.translation_settings.source_language
                )
            )
        self.api_keys = ApiKeys()
        self.app_settings = AppSettings()
        self.proxy_settings = ProxySettings()

        # Load language files
        self._language_data = {}
        self._load_language_files()

        # Load glossary and critical terms
        self.glossary = self._load_json_file(
            self.translation_settings.glossary_file, default={}
        )
        self.critical_terms = self._load_json_file(
            self.translation_settings.critical_terms_file, default=[]
        )

        # Load never-translate rules (optional)
        self.never_translate_rules = self._load_json_file(
            "never_translate.json", default={}
        )

        # Load existing configuration
        self.load_config()

    def save_config(self, app_settings: Optional[AppSettings] = None) -> bool:
        """Save configuration to file safely (Atomic & Thread-Safe)."""
        with self._lock:  # Ensure thread safety
            try:
                # If specific settings provided, update our instance
                if app_settings is not None:
                    self.app_settings = app_settings

                config_data = {
                    "translation_settings": asdict(self.translation_settings),
                    "api_keys": asdict(self.api_keys),
                    "app_settings": asdict(self.app_settings),
                    "proxy_settings": asdict(self.proxy_settings),
                }

                # Check for write permissions proactively
                dir_name = self.config_file.parent.absolute()
                if not os.access(dir_name, os.W_OK):
                    self.logger.error(
                        f"Cannot save config: Directory {dir_name} is not writable. Settings will not be persisted."
                    )
                    return False

                # Atomic Write Strategy: Write to temp -> Rename
                # This prevents file corruption if write fails or power is lost
                import tempfile
                import shutil

                # Create temp file in same directory to ensure atomic move works
                temp_fd, temp_path = tempfile.mkstemp(dir=str(dir_name), text=True)
                try:
                    with os.fdopen(temp_fd, "w", encoding="utf-8") as tf:
                        json.dump(config_data, tf, indent=4, ensure_ascii=False)

                    # Atomic replace
                    shutil.move(temp_path, str(self.config_file))
                    self.logger.info("Configuration saved successfully (Atomic)")
                    return True
                except Exception as e:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    raise e

            except PermissionError:
                self.logger.error(
                    f"Permission denied: Could not save configuration to {self.config_file}"
                )
                return False
            except Exception as e:
                self.logger.error(f"Error saving configuration: {e}")
                # Fallback to direct write if atomic fails for other reasons
                try:
                    with open(self.config_file, "w", encoding="utf-8") as f:
                        json.dump(config_data, f, indent=4, ensure_ascii=False)
                    return True
                except Exception:
                    return False

    def _filter_config_data(self, dataclass_type, data):
        """Filter dictionary keys to match dataclass fields to avoid __init__ errors."""
        if not isinstance(data, dict):
            return {}
        valid_fields = {f.name for f in fields(dataclass_type)}
        return {k: v for k, v in data.items() if k in valid_fields}

    def _load_language_files(self):
        """Load language JSON files from locales directory dynamically."""
        # Mapping from filename stem to language code (for old-style names)
        FILENAME_TO_LANG_CODE = {
            "turkish": "tr",
            "english": "en",
            "spanish": "es",
            "german": "de",
            "french": "fr",
            "russian": "ru",
            "simplified_chinese": "zh-CN",
            "chinese": "zh-CN",
            # Direct API codes (new naming convention)
            "tr": "tr",
            "en": "en",
            "es": "es",
            "de": "de",
            "fr": "fr",
            "ru": "ru",
            "zh-cn": "zh-CN",  # lowercase version for case-insensitive matching
            "ja": "ja",
        }

        try:
            self.logger.debug(f"Loading language files from: {self.locales_dir}")

            if not self.locales_dir.exists():
                self.logger.warning(f"Locales directory not found: {self.locales_dir}")
                self._language_data = self._get_fallback_translations()
                return

            # Dynamically load all JSON files
            for json_file in self.locales_dir.glob("*.json"):
                try:
                    stem = json_file.stem.lower()  # e.g., "tr", "en", "zh-cn"

                    # Map to proper language code
                    if stem in FILENAME_TO_LANG_CODE:
                        lang_code = FILENAME_TO_LANG_CODE[stem]
                    else:
                        # Fallback: use stem as-is for 2-letter codes, otherwise first 2 chars
                        lang_code = stem if len(stem) <= 5 else stem[:2]

                    with open(json_file, "r", encoding="utf-8") as f:
                        self._language_data[lang_code] = json.load(f)
                    self.logger.debug(f"Loaded {json_file.name} as '{lang_code}'")
                except Exception as file_err:
                    self.logger.warning(f"Could not load {json_file.name}: {file_err}")

            self.logger.info(
                f"Loaded {len(self._language_data)} language files: {list(self._language_data.keys())}"
            )

        except Exception as e:
            self.logger.warning(f"Could not load language files: {e}")
            # Fallback to embedded translations if JSON files fail
            self._language_data = self._get_fallback_translations()

    def _load_json_file(self, filename: str, default):
        """Load a JSON file from the smart data directory; return default on error."""
        try:
            path = self.data_dir / filename
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            self.logger.warning(f"Could not load JSON file {filename}: {e}")
        return default

    def _get_fallback_translations(self) -> Dict[str, Dict[str, Any]]:
        """Fallback translations if JSON files are not available."""
        _en_core = {
            "app_title": "RenLocalizer",
            "file_menu": "File",
            "help_menu": "Help",
            "about": "About",
            "info": "Info",
            "settings": "Settings",
            "exit": "Exit",
            "start": "Start",
            "stop": "Stop",
            "save": "Save",
            "cancel": "Cancel",
            "ok": "OK",
            "close": "Close",
            "error": "Error",
            "warning": "Warning",
            "success": "Success",
            "update_checking": "Checking for updates...",
            "check_updates_now_label": "Check Now:",
            "check_updates_now_button": "Check",
            "check_updates_now_tooltip": "Check for updates right now",
            "update_available_title": "Update Available",
            "update_available_message": "A new version is available: {latest} (current: {current}).\nOpen the releases page?",
            "update_up_to_date": "You are up to date (v{current}).",
            "update_check_failed": "Update check failed: {error}",
            "update_check_unavailable": "Update check is not available.",
            "update_open_release": "Open Releases Page",
            "update_later": "Later",
            "info_dialog": {
                "title": "Program Information Center",
                "tabs": {"formats": "Output Formats"},
            },
        }
        return {
            "tr": {
                "app_title": "RenLocalizer",
                "file_menu": "Dosya",
                "help_menu": "Yardım",
                "about": "Hakkında",
                "info": "Bilgi",
                "settings": "Ayarlar",
                "exit": "Çıkış",
                "start": "Başlat",
                "stop": "Durdur",
                "save": "Kaydet",
                "cancel": "İptal",
                "ok": "Tamam",
                "close": "Kapat",
                "error": "Hata",
                "warning": "Uyarı",
                "success": "Başarılı",
                "update_checking": "Güncellemeler kontrol ediliyor...",
                "check_updates_now_label": "Şimdi Kontrol:",
                "check_updates_now_button": "Kontrol Et",
                "check_updates_now_tooltip": "Güncellemeleri şimdi kontrol et",
                "update_available_title": "Güncelleme Var",
                "update_available_message": "Yeni sürüm mevcut: {latest} (şu an: {current}).\nSürüm sayfası açılsın mı?",
                "update_up_to_date": "Güncelsiniz (v{current}).",
                "update_check_failed": "Güncelleme kontrolü başarısız: {error}",
                "update_check_unavailable": "Güncelleme kontrolü şu anda kullanılamıyor.",
                "update_open_release": "Sürümler Sayfasını Aç",
                "update_later": "Daha Sonra",
                "info_dialog": {
                    "title": "Program Bilgi Merkezi",
                    "tabs": {"formats": "Çıktı Formatları"},
                },
            },
            "en": _en_core,
            "de": dict(_en_core),
            "fr": dict(_en_core),
            "es": dict(_en_core),
            "ru": dict(_en_core),
            "fa": dict(_en_core),
            "zh-CN": dict(_en_core),
            "ja": dict(_en_core),
        }

    def load_config(self) -> bool:
        """Load configuration from file."""
        try:
            config_loaded = False

            if self.config_file.exists():
                with open(self.config_file, "r", encoding="utf-8") as f:
                    config_data = json.load(f)

                # Load translation settings
                if "translation_settings" in config_data:
                    trans_data = self._filter_config_data(
                        TranslationSettings, config_data["translation_settings"]
                    )
                    self.translation_settings = TranslationSettings(**trans_data)
                    normalized_target = self.normalize_renpy_language_code(
                        self.translation_settings.target_language
                    )
                    normalized_source = self.translation_settings.source_language
                    if normalized_source and normalized_source != "auto":
                        normalized_source = self.normalize_renpy_language_code(
                            normalized_source
                        )
                    if (
                        normalized_target != self.translation_settings.target_language
                        or normalized_source
                        != self.translation_settings.source_language
                    ):
                        self.translation_settings.target_language = normalized_target
                        self.translation_settings.source_language = normalized_source
                        config_loaded = True

                # Load API keys
                if "api_keys" in config_data:
                    api_data = self._filter_config_data(
                        ApiKeys, config_data["api_keys"]
                    )
                    self.api_keys = ApiKeys(**api_data)

                # Load app settings
                if "app_settings" in config_data:
                    app_settings_data = dict(config_data["app_settings"])
                    if (
                        "theme" in app_settings_data
                        and "app_theme" not in app_settings_data
                    ):
                        app_settings_data["app_theme"] = app_settings_data.pop("theme")
                    app_data = self._filter_config_data(AppSettings, app_settings_data)
                    self.app_settings = AppSettings(**app_data)

                # Load proxy settings
                if "proxy_settings" in config_data:
                    proxy_data = config_data["proxy_settings"]
                    # Migration: custom_proxies -> manual_proxies
                    if (
                        "custom_proxies" in proxy_data
                        and "manual_proxies" not in proxy_data
                    ):
                        proxy_data["manual_proxies"] = proxy_data.pop("custom_proxies")
                    elif "custom_proxies" in proxy_data:
                        proxy_data.pop("custom_proxies")

                    proxy_data = self._filter_config_data(ProxySettings, proxy_data)
                    self.proxy_settings = ProxySettings(**proxy_data)

                config_loaded = True
                self.logger.info("Configuration loaded successfully")
            else:
                self.logger.info(
                    "Config file not found. Creating default configuration."
                )
                self.save_config()  # Create the file with default values immediately

            # Auto-detect system language if not set or if using defaults
            if not self.app_settings.ui_language or not config_loaded:
                detected_lang = detect_system_language()
                self.app_settings.ui_language = detected_lang
                self.logger.info(f"Auto-detected system language: {detected_lang}")

                # Save the detected language to config for future use
                if config_loaded:  # Only save if config was successfully loaded
                    self.save_config()

            return config_loaded

        except Exception as e:
            self.logger.error(f"Error loading configuration: {e}")
            # Even if config loading fails, set system language
            detected_lang = detect_system_language()
            self.app_settings.ui_language = detected_lang
            self.logger.info(
                f"Config failed, using auto-detected language: {detected_lang}"
            )
            return False

    @staticmethod
    def _normalize_dataclass_instance(instance: Any) -> None:
        """Run dataclass-level validation after in-memory mutations."""
        validator = getattr(instance, "__post_init__", None)
        if callable(validator):
            validator()

    @staticmethod
    def _resolve_setting_alias(section: str, setting: str) -> str:
        """Map legacy config keys to the current dataclass field names."""
        if section in {"ui", "app"}:
            return LEGACY_APP_SETTING_ALIASES.get(setting, setting)
        return setting

    def _get_section_object(self, section: str) -> Any | None:
        """Return the config section object for dot-notation helpers."""
        if section in {"ui", "app"}:
            return self.app_settings
        if section == "translation":
            return self.translation_settings
        if section == "proxy":
            return self.proxy_settings
        return None

    def get_api_to_renpy_map(self) -> Dict[str, str]:
        """Get API language code to Ren'Py language code mapping."""
        return {item["api"].lower(): item["renpy"] for item in self.get_all_languages()}

    def normalize_renpy_language_code(self, code: Any) -> str:
        """Normalize a language code to the Ren'Py folder key.

        Accepts legacy API codes (e.g. tr, es, zh-CN) and returns the
        Ren'Py language key used for tl/<lang>/ directories.
        """
        value = str(code or "").strip()
        if not value:
            return "turkish"

        lowered = value.lower()
        renpy_codes = {
            item["renpy"].lower(): item["renpy"] for item in self.get_all_languages()
        }
        if lowered in renpy_codes:
            return renpy_codes[lowered]

        api_to_renpy = self.get_api_to_renpy_map()
        if lowered in api_to_renpy:
            return api_to_renpy[lowered]

        # Legacy naming fallback
        legacy_map = {
            "tr": "turkish",
            "zh-cn": "chinese_s",
            "zh_tw": "chinese_t",
            "zh-tw": "chinese_t",
        }
        return legacy_map.get(lowered, value)

    def save_glossary(self) -> bool:
        """Save glossary to file."""
        try:
            filename = self.translation_settings.glossary_file
            path = self.data_dir / filename
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.glossary, f, indent=4, ensure_ascii=False)
            self.logger.info(f"Glossary saved to {path}")
            return True
        except Exception as e:
            self.logger.error(f"Error saving glossary: {e}")
            return False

    def get_api_key(self, service: str) -> str:
        """Get API key for a service."""
        return getattr(self.api_keys, f"{service}_api_key", "")

    def set_api_key(self, service: str, api_key: str) -> None:
        """Set API key for a service."""
        attr_name = f"{service}_api_key"
        if not hasattr(self.api_keys, attr_name):
            self.logger.warning("Unknown API key service requested: %s", service)
            return

        setattr(self.api_keys, attr_name, api_key)
        self._normalize_dataclass_instance(self.api_keys)
        self.save_config()

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a setting value using dot notation (e.g., 'app.app_theme')."""
        try:
            parts = key.split(".")
            if len(parts) == 2:
                section, setting = parts
                setting = self._resolve_setting_alias(section, setting)
                section_obj = self._get_section_object(section)
                if section_obj is not None:
                    return getattr(section_obj, setting, default)
            return default
        except Exception:
            return default

    def set_setting(self, key: str, value: Any) -> None:
        """Set a setting value using dot notation (e.g., 'app.app_theme')."""
        try:
            parts = key.split(".")
            if len(parts) != 2:
                self.logger.warning(
                    "Invalid config key format for set_setting: %s", key
                )
                return

            section, setting = parts
            setting = self._resolve_setting_alias(section, setting)
            section_obj = self._get_section_object(section)
            if section_obj is None:
                self.logger.warning("Unknown config section requested: %s", section)
                return
            if not hasattr(section_obj, setting):
                self.logger.warning("Unknown config setting requested: %s", key)
                return

            if section == "translation" and setting == "target_language":
                value = self.normalize_renpy_language_code(value)
            elif (
                section == "translation"
                and setting == "source_language"
                and value != "auto"
            ):
                value = self.normalize_renpy_language_code(value)

            setattr(section_obj, setting, value)
            self._normalize_dataclass_instance(section_obj)
            self.save_config()
        except Exception as e:
            self.logger.error(f"Error setting {key} to {value}: {e}")

    def load_locale(self, lang: Language) -> None:
        """Compatibility method for language switching."""
        self.app_settings.ui_language = lang.value
        self.logger.info(f"UI Language shifted to: {lang.value}")

    def get_supported_languages(self) -> Dict[str, str]:
        """Get supported language codes and names (API code -> English name)."""
        return {item["api"]: item["english"] for item in self.get_all_languages()}

    def get_all_languages(self) -> list:
        """
        Central language list - single source of truth.
        Returns list of dicts with 'renpy', 'api', 'english', and 'native' keys.
        """
        return [
            {"renpy": "turkish", "api": "tr", "english": "Turkish", "native": "Türkçe"},
            {
                "renpy": "english",
                "api": "en",
                "english": "English",
                "native": "English",
            },
            {"renpy": "german", "api": "de", "english": "German", "native": "Deutsch"},
            {"renpy": "french", "api": "fr", "english": "French", "native": "Français"},
            {
                "renpy": "spanish",
                "api": "es",
                "english": "Spanish",
                "native": "Español",
            },
            {
                "renpy": "italian",
                "api": "it",
                "english": "Italian",
                "native": "Italiano",
            },
            {
                "renpy": "portuguese",
                "api": "pt",
                "english": "Portuguese",
                "native": "Português",
            },
            {
                "renpy": "russian",
                "api": "ru",
                "english": "Russian",
                "native": "Русский",
            },
            {"renpy": "polish", "api": "pl", "english": "Polish", "native": "Polski"},
            {"renpy": "dutch", "api": "nl", "english": "Dutch", "native": "Nederlands"},
            {
                "renpy": "japanese",
                "api": "ja",
                "english": "Japanese",
                "native": "日本語",
            },
            {"renpy": "korean", "api": "ko", "english": "Korean", "native": "한국어"},
            {
                "renpy": "chinese_s",
                "api": "zh-CN",
                "english": "Chinese (Simplified)",
                "native": "简体中文",
            },
            {
                "renpy": "chinese_t",
                "api": "zh-TW",
                "english": "Chinese (Traditional)",
                "native": "繁體中文",
            },
            {"renpy": "arabic", "api": "ar", "english": "Arabic", "native": "العربية"},
            {"renpy": "thai", "api": "th", "english": "Thai", "native": "ไทย"},
            {
                "renpy": "vietnamese",
                "api": "vi",
                "english": "Vietnamese",
                "native": "Tiếng Việt",
            },
            {
                "renpy": "indonesian",
                "api": "id",
                "english": "Indonesian",
                "native": "Bahasa Indonesia",
            },
            {
                "renpy": "malay",
                "api": "ms",
                "english": "Malay",
                "native": "Bahasa Melayu",
            },
            {"renpy": "hindi", "api": "hi", "english": "Hindi", "native": "हिन्दी"},
            {
                "renpy": "persian",
                "api": "fa",
                "english": "Persian (Farsi)",
                "native": "فارsi",
            },
            {"renpy": "czech", "api": "cs", "english": "Czech", "native": "Čeština"},
            {"renpy": "danish", "api": "da", "english": "Danish", "native": "Dansk"},
            {"renpy": "finnish", "api": "fi", "english": "Finnish", "native": "Suomi"},
            {"renpy": "greek", "api": "el", "english": "Greek", "native": "Ελληνικά"},
            {"renpy": "hebrew", "api": "he", "english": "Hebrew", "native": "עברית"},
            {
                "renpy": "hungarian",
                "api": "hu",
                "english": "Hungarian",
                "native": "Magyar",
            },
            {
                "renpy": "norwegian",
                "api": "no",
                "english": "Norwegian",
                "native": "Norsk",
            },
            {
                "renpy": "romanian",
                "api": "ro",
                "english": "Romanian",
                "native": "Română",
            },
            {
                "renpy": "swedish",
                "api": "sv",
                "english": "Swedish",
                "native": "Svenska",
            },
            {
                "renpy": "ukrainian",
                "api": "uk",
                "english": "Ukrainian",
                "native": "Українська",
            },
            {
                "renpy": "bulgarian",
                "api": "bg",
                "english": "Bulgarian",
                "native": "Български",
            },
            {"renpy": "catalan", "api": "ca", "english": "Catalan", "native": "Català"},
            {
                "renpy": "croatian",
                "api": "hr",
                "english": "Croatian",
                "native": "Hrvatski",
            },
            {
                "renpy": "slovak",
                "api": "sk",
                "english": "Slovak",
                "native": "Slovenčina",
            },
            {
                "renpy": "slovenian",
                "api": "sl",
                "english": "Slovenian",
                "native": "Slovenščina",
            },
            {"renpy": "serbian", "api": "sr", "english": "Serbian", "native": "Српски"},
            {
                "renpy": "afrikaans",
                "api": "af",
                "english": "Afrikaans",
                "native": "Afrikaans",
            },
            {
                "renpy": "albanian",
                "api": "sq",
                "english": "Albanian",
                "native": "Shqip",
            },
            {"renpy": "amharic", "api": "am", "english": "Amharic", "native": "አማርኛ"},
            {
                "renpy": "armenian",
                "api": "hy",
                "english": "Armenian",
                "native": "Հայերեն",
            },
            {
                "renpy": "azerbaijani",
                "api": "az",
                "english": "Azerbaijani",
                "native": "Azərbaycanca",
            },
            {"renpy": "basque", "api": "eu", "english": "Basque", "native": "Euskara"},
            {
                "renpy": "belarusian",
                "api": "be",
                "english": "Belarusian",
                "native": "Беларуская",
            },
            {"renpy": "bengali", "api": "bn", "english": "Bengali", "native": "বাংলা"},
            {
                "renpy": "bosnian",
                "api": "bs",
                "english": "Bosnian",
                "native": "Bosanski",
            },
            {
                "renpy": "esperanto",
                "api": "eo",
                "english": "Esperanto",
                "native": "Esperanto",
            },
            {
                "renpy": "estonian",
                "api": "et",
                "english": "Estonian",
                "native": "Eesti",
            },
            {
                "renpy": "filipino",
                "api": "tl",
                "english": "Filipino",
                "native": "Filipino",
            },
            {
                "renpy": "galician",
                "api": "gl",
                "english": "Galician",
                "native": "Galego",
            },
            {
                "renpy": "georgian",
                "api": "ka",
                "english": "Georgian",
                "native": "ქართული",
            },
            {
                "renpy": "gujarati",
                "api": "gu",
                "english": "Gujarati",
                "native": "ગુજરાતી",
            },
            {
                "renpy": "haitian_creole",
                "api": "ht",
                "english": "Haitian Creole",
                "native": "Kreyòl Ayisyen",
            },
            {"renpy": "hausa", "api": "ha", "english": "Hausa", "native": "Hausa"},
            {
                "renpy": "icelandic",
                "api": "is",
                "english": "Icelandic",
                "native": "Íslenska",
            },
            {"renpy": "igbo", "api": "ig", "english": "Igbo", "native": "Asụsụ Igbo"},
            {"renpy": "irish", "api": "ga", "english": "Irish", "native": "Gaeilge"},
            {
                "renpy": "javanese",
                "api": "jv",
                "english": "Javanese",
                "native": "Basa Jawa",
            },
            {"renpy": "kannada", "api": "kn", "english": "Kannada", "native": "ಕನ್ನಡ"},
            {
                "renpy": "kazakh",
                "api": "kk",
                "english": "Kazakh",
                "native": "Қазақ тілі",
            },
            {"renpy": "khmer", "api": "km", "english": "Khmer", "native": "ភាសាខ្មែរ"},
            {"renpy": "kurdish", "api": "ku", "english": "Kurdish", "native": "Kurdî"},
            {"renpy": "kyrgyz", "api": "ky", "english": "Kyrgyz", "native": "Кыргызча"},
            {"renpy": "lao", "api": "lo", "english": "Lao", "native": "ພາສາລາວ"},
            {
                "renpy": "latvian",
                "api": "lv",
                "english": "Latvian",
                "native": "Latviešu",
            },
            {
                "renpy": "lithuanian",
                "api": "lt",
                "english": "Lithuanian",
                "native": "Lietuvių",
            },
            {
                "renpy": "luxembourgish",
                "api": "lb",
                "english": "Luxembourgish",
                "native": "Lëtzebuergesch",
            },
            {
                "renpy": "macedonian",
                "api": "mk",
                "english": "Macedonian",
                "native": "Македонски",
            },
            {
                "renpy": "malagasy",
                "api": "mg",
                "english": "Malagasy",
                "native": "Malagasy",
            },
            {
                "renpy": "malayalam",
                "api": "ml",
                "english": "Malayalam",
                "native": "മലയാളം",
            },
            {"renpy": "maltese", "api": "mt", "english": "Maltese", "native": "Malti"},
            {"renpy": "maori", "api": "mi", "english": "Maori", "native": "Māori"},
            {"renpy": "marathi", "api": "mr", "english": "Marathi", "native": "मराठी"},
            {
                "renpy": "mongolian",
                "api": "mn",
                "english": "Mongolian",
                "native": "Монгол",
            },
            {
                "renpy": "myanmar",
                "api": "my",
                "english": "Myanmar (Burmese)",
                "native": "ဗမာ",
            },
            {"renpy": "nepali", "api": "ne", "english": "Nepali", "native": "नेपाली"},
            {"renpy": "pashto", "api": "ps", "english": "Pashto", "native": "پښتو"},
            {"renpy": "punjabi", "api": "pa", "english": "Punjabi", "native": "ਪੰਜਾਬੀ"},
            {
                "renpy": "samoan",
                "api": "sm",
                "english": "Samoan",
                "native": "Gagana Sāmoa",
            },
            {
                "renpy": "scots_gaelic",
                "api": "gd",
                "english": "Scots Gaelic",
                "native": "Gàidhlig",
            },
            {"renpy": "shona", "api": "sn", "english": "Shona", "native": "chiShona"},
            {"renpy": "sindhi", "api": "sd", "english": "Sindhi", "native": "سنڌي"},
            {"renpy": "sinhala", "api": "si", "english": "Sinhala", "native": "සිංහල"},
            {"renpy": "somali", "api": "so", "english": "Somali", "native": "Soomaali"},
            {
                "renpy": "swahili",
                "api": "sw",
                "english": "Swahili",
                "native": "Kiswahili",
            },
            {"renpy": "tajik", "api": "tg", "english": "Tajik", "native": "Тоҷикӣ"},
            {"renpy": "tamil", "api": "ta", "english": "Tamil", "native": "தமிழ்"},
            {"renpy": "telugu", "api": "te", "english": "Telugu", "native": "తెలుగు"},
            {"renpy": "urdu", "api": "ur", "english": "Urdu", "native": "اردو"},
            {"renpy": "uzbek", "api": "uz", "english": "Uzbek", "native": "Oʻzbekcha"},
            {"renpy": "welsh", "api": "cy", "english": "Welsh", "native": "Cymraeg"},
            {"renpy": "xhosa", "api": "xh", "english": "Xhosa", "native": "isiXhosa"},
            {"renpy": "yiddish", "api": "yi", "english": "Yiddish", "native": "ייִדיש"},
            {"renpy": "yoruba", "api": "yo", "english": "Yoruba", "native": "Yorùbá"},
            {"renpy": "zulu", "api": "zu", "english": "Zulu", "native": "isiZulu"},
        ]

    def get_renpy_to_api_map(self) -> Dict[str, str]:
        """Get Ren'Py language code to API code mapping."""
        return {item["renpy"]: item["api"] for item in self.get_all_languages()}

    def get_target_languages_for_ui(self) -> list:
        """Get languages for UI dropdowns as list of (renpy_code, display_name) tuples."""
        result = []
        for item in self.get_all_languages():
            name = item["native"]
            # Add English name in parens if it differs from native
            if item["english"].lower() != item["native"].lower():
                name = f"{item['native']} ({item['english']})"
            result.append((item["renpy"], name))
        return result

    def get_source_languages_for_ui(self) -> list:
        """Get languages for source language UI dropdown, with Auto-detect first."""
        result = [("auto", "🤖 Auto-detect")]
        for item in self.get_all_languages():
            name = item["native"]
            if item["english"].lower() != item["native"].lower():
                name = f"{item['native']} ({item['english']})"
            result.append((item["renpy"], name))
        return result

    def get_ui_translations(self) -> Dict[str, Dict[str, Any]]:
        """Get UI translations for supported languages from JSON files."""
        return self._language_data

    def get_ui_text(self, key: str, default: str = None, **kwargs) -> Any:
        """Get UI text in current language with support for nested keys and formatting."""
        translations = self.get_ui_translations()
        current_lang = self.app_settings.ui_language

        # Support for nested keys like 'info_dialog.title'
        def get_nested_value(data: Dict, key_path: str):
            keys = key_path.split(".")
            value = data
            for k in keys:
                if isinstance(value, dict) and k in value:
                    value = value[k]
                else:
                    return None
            return value

        result = None
        # Try current language first
        if current_lang in translations:
            result = get_nested_value(translations[current_lang], key)

        # Fallback to English
        if result is None and "en" in translations:
            result = get_nested_value(translations["en"], key)

        # Fallback to provided default or key itself
        if result is None:
            result = default if default is not None else key

        # Apply formatting if kwargs provided and result is a string
        if kwargs and isinstance(result, str):
            try:
                return result.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                # If formatting fails, return result as-is
                return result

        return result

    def get_log_text(self, key: str, default: str = None, **kwargs) -> str:
        """
        Get localized log message from pipeline_logs section.
        Supports placeholder formatting with kwargs.

        Example:
            get_log_text("unren_completed_code", code=0)
            -> "UnRen tamamlandı (kod: 0)"
        """
        full_key = f"pipeline_logs.{key}"
        # Use key as default if neither template nor explicit default provided
        template = self.get_ui_text(full_key, default if default is not None else key)

        # Apply placeholders if any
        if kwargs and isinstance(template, str):
            try:
                return template.format(**kwargs)
            except KeyError:
                # If some placeholders are missing, return template as-is
                return template
        return template

    def reset_to_defaults(self) -> None:
        """Reset configuration to defaults."""
        self.translation_settings = TranslationSettings()
        self.api_keys = ApiKeys()
        self.app_settings = AppSettings()
        self.proxy_settings = ProxySettings()
        self.logger.info("Configuration reset to defaults")
