# -*- coding: utf-8 -*-
"""Unit tests for Gemini safety settings, AppBackend property synchronization, and localization."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from src.backend.settings_backend import SettingsBackend


def test_gemini_safety_settings_get_set():
    mock_config = MagicMock()
    mock_config.translation_settings.gemini_safety_settings = "BLOCK_NONE"
    
    backend = SettingsBackend(mock_config, MagicMock())
    
    assert backend.get_gemini_safety_settings() == "BLOCK_NONE"
    
    backend.set_gemini_safety_settings("BLOCK_ONLY_HIGH")
    assert backend.get_gemini_safety_settings() == "BLOCK_ONLY_HIGH"
    assert mock_config.translation_settings.gemini_safety_settings == "BLOCK_ONLY_HIGH"


def test_gemini_safety_settings_default_fallback():
    mock_config = MagicMock()
    # If attribute is missing or empty, returns "BLOCK_NONE"
    del mock_config.translation_settings.gemini_safety_settings
    
    backend = SettingsBackend(mock_config, MagicMock())
    assert backend.get_gemini_safety_settings() == "BLOCK_NONE"


def test_quick_config_localization_keys():
    locales_dir = Path(__file__).resolve().parent.parent / "locales"
    required_keys = [
        "ai_quick_config_title",
        "label_gemini_safety",
        "gemini_safety_block_none",
        "gemini_safety_only_high",
        "gemini_safety_standard",
    ]
    all_locales = ["de", "en", "es", "fa", "fr", "ja", "ko", "ru", "tr", "zh-CN"]
    
    for loc in all_locales:
        file_path = locales_dir / f"{loc}.json"
        assert file_path.exists(), f"Locale file {loc}.json not found"
        data = json.loads(file_path.read_text(encoding="utf-8"))
        for key in required_keys:
            assert key in data, f"Missing key '{key}' in locales/{loc}.json"
            assert len(data[key]) > 0, f"Empty key '{key}' in locales/{loc}.json"

