# -*- coding: utf-8 -*-
"""
Tests for Desktop Notification System in RenLocalizer.
Verifies config defaults, SettingsBackend integration, AppBackend slots/properties,
and locales dictionary keys for desktop notifications across languages.
"""

import os
import pytest
from unittest.mock import MagicMock, patch

from src.utils.config import ConfigManager, AppSettings
from src.backend.settings_backend import SettingsBackend
from src.core.translator import TranslationManager


def test_config_desktop_notifications_default():
    """Verify that enable_desktop_notifications defaults to True in AppSettings."""
    settings = AppSettings()
    assert hasattr(settings, "enable_desktop_notifications")
    assert settings.enable_desktop_notifications is True


def test_settings_backend_desktop_notifications():
    """Verify getter/setter and callback firing in SettingsBackend."""
    config = ConfigManager()
    tm = MagicMock(spec=TranslationManager)
    sb = SettingsBackend(config=config, translation_manager=tm)

    callback_called = []
    sb.on("enable_desktop_notifications", lambda: callback_called.append(True))

    assert sb.get_enable_desktop_notifications() is True

    sb.set_enable_desktop_notifications(False)
    assert sb.get_enable_desktop_notifications() is False
    assert len(callback_called) == 1

    sb.set_enable_desktop_notifications(True)
    assert sb.get_enable_desktop_notifications() is True
    assert len(callback_called) == 2


def test_locales_has_desktop_notification_keys():
    """Verify that all supported locales contain desktop notification translation keys."""
    import json
    from pathlib import Path

    locales_dir = Path(__file__).resolve().parent.parent / "locales"
    required_keys = [
        "enable_desktop_notifications_label",
        "enable_desktop_notifications_tooltip",
        "desktop_notify_complete_title",
        "desktop_notify_complete_msg",
        "desktop_notify_error_title",
        "desktop_notify_error_msg",
    ]

    json_files = list(locales_dir.glob("*.json"))
    assert len(json_files) >= 9, "Expected at least 9 locale files"

    for json_file in json_files:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        for key in required_keys:
            assert key in data, f"Key '{key}' missing in {json_file.name}"
