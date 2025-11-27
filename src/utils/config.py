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
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum

class Language(Enum):
    """Supported UI languages."""
    TURKISH = "tr"
    ENGLISH = "en"

def detect_system_language() -> str:
    """Detect the system language and return appropriate UI language code."""
    try:
        # Method 1: Windows locale detection
        if os.name == 'nt':  # Windows
            try:
                import ctypes
                # Get user default UI language
                lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
                # Primary language mask
                primary_lang = lang_id & 0x3FF
                
                # Turkish: 0x1F, English: 0x09
                if primary_lang == 0x1F:  # Turkish
                    return 'tr'
                elif primary_lang == 0x09:  # English
                    return 'en'
            except:
                pass
        
        # Method 2: Standard locale detection
        try:
            system_locale = locale.getdefaultlocale()[0]
            if system_locale:
                lang_part = system_locale.split('_')[0].lower()
                if lang_part == 'tr':
                    return 'tr'
                elif lang_part == 'en':
                    return 'en'
        except:
            pass
        
        # Method 3: Environment variables
        try:
            for env_var in ['LANG', 'LANGUAGE', 'LC_ALL', 'LC_MESSAGES']:
                env_value = os.environ.get(env_var, '').lower()
                if env_value:
                    if 'tr' in env_value:
                        return 'tr'
                    elif 'en' in env_value:
                        return 'en'
        except:
            pass
        
        # Default to English if detection fails
        return 'en'
        
    except Exception:
        return 'en'

@dataclass
class TranslationSettings:
    """Translation-related settings."""
    source_language: str = "auto"
    target_language: str = "tr"
    max_concurrent_threads: int = 32
    request_delay: float = 0.1
    max_batch_size: int = 100
    enable_proxy: bool = True
    max_retries: int = 3
    timeout: int = 30
    # Glossary & critical terms
    # Glossary & critical terms
    glossary_file: str = "glossary.json"  # Terim sözlüğü yolu (proje köküne göre)
    critical_terms_file: str = "critical_terms.json"  # Kritik kelimeler listesi
    # Type-based translation filters
    translate_dialogue: bool = True
    translate_menu: bool = True
    translate_ui: bool = False
    translate_config_strings: bool = False
    translate_gui_strings: bool = False
    translate_style_strings: bool = False
    translate_renpy_functions: bool = False

@dataclass
class ApiKeys:
    """API keys for various translation services."""
    google_api_key: str = ""
    deepl_api_key: str = ""
    bing_api_key: str = ""
    yandex_api_key: str = ""

@dataclass
class AppSettings:
    """General application settings."""
    ui_language: str = ""  # Will be auto-detected if empty
    theme: str = "solarized"  # Varsayılan tema solarized olarak ayarlandı
    window_width: int = 1200
    window_height: int = 800
    last_input_directory: str = ""
    last_output_directory: str = ""
    auto_save_settings: bool = True
    auto_save_translations: bool = True
    check_for_updates: bool = True
    # Output format: 'old_new' (Ren'Py official old/new blocks, recommended) or 'simple' (legacy)
    output_format: str = "old_new"
    # Parser workers for parallel file processing
    parser_workers: int = 4

@dataclass
class ProxySettings:
    """Proxy-related settings."""
    enabled: bool = True
    auto_rotate: bool = True
    test_on_startup: bool = True
    update_interval: int = 3600  # seconds
    max_failures: int = 10
    custom_proxies: list = None
    
    def __post_init__(self):
        if self.custom_proxies is None:
            self.custom_proxies = []

class ConfigManager:
    """Manages application configuration."""
    
    def __init__(self, config_file: str = "config.json"):
        self.logger = logging.getLogger(__name__)
        self.config_file = Path(config_file)
        
        # Get the correct locales directory for both dev and executable
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            # Running as PyInstaller executable
            self.locales_dir = Path(sys._MEIPASS) / "locales"
        else:
            # Running in development
            self.locales_dir = Path("locales")
        
        # Default configuration
        self.translation_settings = TranslationSettings()
        self.api_keys = ApiKeys()
        self.app_settings = AppSettings()
        self.proxy_settings = ProxySettings()
        
        # Load language files
        self._language_data = {}
        self._load_language_files()

        # Load glossary and critical terms
        self.glossary = self._load_json_file(self.translation_settings.glossary_file, default={})
        self.critical_terms = self._load_json_file(self.translation_settings.critical_terms_file, default=[])

        # Load never-translate rules (optional)
        self.never_translate_rules = self._load_json_file("never_translate.json", default={})
        
        # Load existing configuration
        self.load_config()
    
    def _load_language_files(self):
        """Load language JSON files from locales directory."""
        try:
            self.logger.debug(f"Loading language files from: {self.locales_dir}")
            self.logger.debug(f"Locales directory exists: {self.locales_dir.exists()}")
            
            # Load Turkish
            tr_file = self.locales_dir / "turkish.json"
            self.logger.debug(f"Turkish file path: {tr_file}")
            if tr_file.exists():
                with open(tr_file, 'r', encoding='utf-8') as f:
                    self._language_data['tr'] = json.load(f)
                self.logger.debug("Turkish language data loaded successfully")
            else:
                self.logger.warning(f"Turkish language file not found: {tr_file}")
            
            # Load English
            en_file = self.locales_dir / "english.json"
            self.logger.debug(f"English file path: {en_file}")
            if en_file.exists():
                with open(en_file, 'r', encoding='utf-8') as f:
                    self._language_data['en'] = json.load(f)
                self.logger.debug("English language data loaded successfully")
            else:
                self.logger.warning(f"English language file not found: {en_file}")
                
        except Exception as e:
            self.logger.error(f"Error loading language files: {e}")
            # Fallback to minimal English text
            self._language_data = {
                'en': {
                    'app_title': 'RenLocalizer V2',
                    'start_translation': 'Start Translation',
                    'stop_translation': 'Stop Translation'
                },
                'tr': {
                    'app_title': 'RenLocalizer V2',
                    'start_translation': 'Çeviriyi Başlat',
                    'stop_translation': 'Çeviriyi Durdur'
                }
            }
                    
            self.logger.info(f"Loaded {len(self._language_data)} language files")
        except Exception as e:
            self.logger.warning(f"Could not load language files: {e}")
            # Fallback to embedded translations if JSON files fail
            self._language_data = self._get_fallback_translations()

    def _load_json_file(self, filename: str, default):
        """Load a JSON file from project root; return default on error."""
        try:
            path = Path(filename)
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            self.logger.warning(f"Could not load JSON file {filename}: {e}")
        return default
    
    def _get_fallback_translations(self) -> Dict[str, Dict[str, Any]]:
        """Fallback translations if JSON files are not available."""
        return {
            'tr': {
                'app_title': 'RenLocalizer V2',
                'file_menu': 'Dosya',
                'help_menu': 'Yardım',
                'about': 'Hakkında',
                'info': 'Bilgi',
                'info_dialog': {
                    'title': 'Program Bilgi Merkezi',
                    'tabs': {
                        'formats': 'Çıktı Formatları'
                    }
                }
            },
            'en': {
                'app_title': 'RenLocalizer V2',
                'file_menu': 'File',
                'help_menu': 'Help',
                'about': 'About',
                'info': 'Info',
                'info_dialog': {
                    'title': 'Program Information Center',
                    'tabs': {
                        'formats': 'Output Formats'
                    }
                }
            }
        }
    
    def load_config(self) -> bool:
        """Load configuration from file."""
        try:
            config_loaded = False
            
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                
                # Load translation settings
                if 'translation_settings' in config_data:
                    trans_data = config_data['translation_settings']
                    self.translation_settings = TranslationSettings(**trans_data)
                
                # Load API keys
                if 'api_keys' in config_data:
                    api_data = config_data['api_keys']
                    self.api_keys = ApiKeys(**api_data)
                
                # Load app settings
                if 'app_settings' in config_data:
                    app_data = config_data['app_settings']
                    self.app_settings = AppSettings(**app_data)
                
                # Load proxy settings
                if 'proxy_settings' in config_data:
                    proxy_data = config_data['proxy_settings']
                    self.proxy_settings = ProxySettings(**proxy_data)
                
                config_loaded = True
                self.logger.info("Configuration loaded successfully")
            else:
                self.logger.info("Config file doesn't exist, using defaults")
            
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
            self.logger.info(f"Config failed, using auto-detected language: {detected_lang}")
            return False
    
    def save_config(self, app_settings: Optional[AppSettings] = None) -> bool:
        """Save configuration to file."""
        try:
            # If specific settings provided, update our instance
            if app_settings is not None:
                self.app_settings = app_settings
            
            config_data = {
                'translation_settings': asdict(self.translation_settings),
                'api_keys': asdict(self.api_keys),
                'app_settings': asdict(self.app_settings),
                'proxy_settings': asdict(self.proxy_settings)
            }
            
            # Create backup if file exists
            if self.config_file.exists():
                backup_file = self.config_file.with_suffix('.json.bak')
                # Remove existing backup if it exists
                if backup_file.exists():
                    try:
                        backup_file.unlink()
                    except OSError as e:
                        self.logger.warning(f"Could not remove existing backup: {e}")
                # Create new backup
                try:
                    self.config_file.rename(backup_file)
                except OSError as e:
                    self.logger.warning(f"Could not create backup: {e}")
                    # If backup fails, continue without backup
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
            
            self.logger.info("Configuration saved successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Error saving configuration: {e}")
            return False
    
    def get_api_key(self, service: str) -> str:
        """Get API key for a service."""
        return getattr(self.api_keys, f"{service}_api_key", "")
    
    def set_api_key(self, service: str, api_key: str) -> None:
        """Set API key for a service."""
        setattr(self.api_keys, f"{service}_api_key", api_key)
        if self.app_settings.auto_save_settings:
            self.save_config()
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a setting value using dot notation (e.g., 'ui.theme')."""
        try:
            parts = key.split('.')
            if len(parts) == 2:
                section, setting = parts
                if section == 'ui' or section == 'app':
                    return getattr(self.app_settings, setting, default)
                elif section == 'translation':
                    return getattr(self.translation_settings, setting, default)
                elif section == 'proxy':
                    return getattr(self.proxy_settings, setting, default)
            return default
        except Exception:
            return default
    
    def set_setting(self, key: str, value: Any) -> None:
        """Set a setting value using dot notation (e.g., 'ui.theme')."""
        try:
            parts = key.split('.')
            if len(parts) == 2:
                section, setting = parts
                if section == 'ui' or section == 'app':
                    setattr(self.app_settings, setting, value)
                elif section == 'translation':
                    setattr(self.translation_settings, setting, value)
                elif section == 'proxy':
                    setattr(self.proxy_settings, setting, value)
                
                if self.app_settings.auto_save_settings:
                    self.save_config()
        except Exception as e:
            self.logger.error(f"Error setting {key} to {value}: {e}")
    
    def get_supported_languages(self) -> Dict[str, str]:
        """Get supported language codes and names."""
        return {
            'auto': 'Auto Detect',
            'en': 'English',
            'tr': 'Turkish',
            'es': 'Spanish',
            'fr': 'French',
            'de': 'German',
            'it': 'Italian',
            'pt': 'Portuguese',
            'ru': 'Russian',
            'ja': 'Japanese',
            'ko': 'Korean',
            'zh': 'Chinese (Simplified)',
            'zh-tw': 'Chinese (Traditional)',
            'ar': 'Arabic',
            'hi': 'Hindi',
            'th': 'Thai',
            'vi': 'Vietnamese',
            'pl': 'Polish',
            'nl': 'Dutch',
            'sv': 'Swedish',
            'da': 'Danish',
            'no': 'Norwegian',
            'fi': 'Finnish'
        }
    
    def get_ui_translations(self) -> Dict[str, Dict[str, Any]]:
        """Get UI translations for supported languages from JSON files."""
        return self._language_data
    
    def get_ui_text(self, key: str) -> Any:
        """Get UI text in current language with support for nested keys."""
        translations = self.get_ui_translations()
        current_lang = self.app_settings.ui_language
        
        # Support for nested keys like 'info_dialog.title'
        def get_nested_value(data: Dict, key_path: str):
            keys = key_path.split('.')
            value = data
            for k in keys:
                if isinstance(value, dict) and k in value:
                    value = value[k]
                else:
                    return None
            return value
        
        # Try current language first
        if current_lang in translations:
            value = get_nested_value(translations[current_lang], key)
            if value is not None:
                return value
        
        # Fallback to English
        if 'en' in translations:
            value = get_nested_value(translations['en'], key)
            if value is not None:
                return value
        
        # Fallback to key itself
        return key
    
    def reset_to_defaults(self) -> None:
        """Reset configuration to defaults."""
        self.translation_settings = TranslationSettings()
        self.api_keys = ApiKeys()
        self.app_settings = AppSettings()
        self.proxy_settings = ProxySettings()
        self.logger.info("Configuration reset to defaults")
