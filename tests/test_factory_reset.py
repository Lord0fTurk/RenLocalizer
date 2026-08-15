# -*- coding: utf-8 -*-
"""Tests for SettingsBackend.factory_reset (restore first-launch state)."""

from pathlib import Path
from unittest.mock import MagicMock

from src.backend.settings_backend import SettingsBackend


class MockConfig:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.translation_settings = MagicMock()
        self.api_keys = MagicMock()
        self.proxy_settings = MagicMock()
        self.glossary = {"hero": "Kahraman"}
        self.critical_terms = ["mana"]
        self.never_translate_rules = {"Excalibur": True}
        self.reset_to_defaults = MagicMock()
        self.save_config = MagicMock()


def _seed_data_dir(data_dir: Path) -> None:
    """Create the files/dirs a normal session would leave behind."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "glossary.json").write_text("{}", encoding="utf-8")
    (data_dir / "critical_terms.json").write_text("[]", encoding="utf-8")
    (data_dir / "never_translate.json").write_text("{}", encoding="utf-8")
    (data_dir / ".migrated_286").write_text("", encoding="utf-8")
    (data_dir / "config.json").write_text("{}", encoding="utf-8")
    cache = data_dir / "cache" / "MyGame" / "turkish"
    cache.mkdir(parents=True)
    (cache / "translation_cache.json").write_text("{}", encoding="utf-8")
    tm = data_dir / "tm"
    tm.mkdir()
    (tm / "external.json").write_text("{}", encoding="utf-8")
    logs = data_dir / "logs"
    logs.mkdir()
    (logs / "app.log").write_text("log", encoding="utf-8")


def test_factory_reset_wipes_user_data(tmp_path: Path) -> None:
    data_dir = tmp_path / "RenLocalizer"
    _seed_data_dir(data_dir)
    config = MockConfig(data_dir)
    backend = SettingsBackend(config, MagicMock())

    assert backend.factory_reset() is True

    # Standalone user-data files removed
    for name in ("glossary.json", "critical_terms.json", "never_translate.json", ".migrated_286"):
        assert not (data_dir / name).exists(), name

    # Data directories wiped (logs/ and tm/ are recreated empty afterwards)
    assert not (data_dir / "cache").exists()
    assert (data_dir / "tm").is_dir()
    assert list((data_dir / "tm").iterdir()) == []
    assert (data_dir / "logs").is_dir()
    assert list((data_dir / "logs").iterdir()) == []

    # Settings reset + defaults persisted
    config.reset_to_defaults.assert_called_once()
    config.save_config.assert_called_once()
    assert config.glossary == {}
    assert config.critical_terms == []
    assert config.never_translate_rules == {}


def test_factory_reset_on_clean_install_does_not_fail(tmp_path: Path) -> None:
    data_dir = tmp_path / "RenLocalizer"
    data_dir.mkdir()
    config = MockConfig(data_dir)
    backend = SettingsBackend(config, MagicMock())

    assert backend.factory_reset() is True
    config.reset_to_defaults.assert_called_once()
    config.save_config.assert_called_once()
