# -*- coding: utf-8 -*-
import pytest
from unittest.mock import MagicMock
from src.backend.settings_backend import SettingsBackend


class MockConfig:
    def __init__(self):
        self.translation_settings = MagicMock()
        self.api_keys = MagicMock()
        self.proxy_settings = MagicMock()
        self.save_config = MagicMock()


class TestSettingsSanitization:

    def setup_method(self):
        self.config = MockConfig()
        self.translation_manager = MagicMock()
        self.backend = SettingsBackend(self.config, self.translation_manager)

    def test_api_key_sanitization(self):
        """Test that API keys with whitespace are stripped."""
        dirty_key = "  sk-my-secret-key  \n"
        self.backend.set_gemini_api_key(dirty_key)

        # Verify stored value is stripped (Gemini key is in api_keys)
        assert self.config.api_keys.gemini_api_key == "sk-my-secret-key"

    def test_model_name_sanitization(self):
        """Test that model names are sanitized."""
        dirty_model = "\tgemini-2.5-flash "
        self.backend.set_gemini_model(dirty_model)
        assert self.config.translation_settings.gemini_model == "gemini-2.5-flash"

    def test_url_sanitization(self):
        """Test URL sanitization."""
        dirty_url = " http://localhost:1234/v1/  "
        self.backend.set_openai_base_url(dirty_url)
        assert self.config.translation_settings.openai_base_url == "http://localhost:1234/v1/"

    def test_empty_string_handling(self):
        """Test empty string input."""
        self.backend.set_gemini_api_key("")
        assert self.config.api_keys.gemini_api_key == ""
