# -*- coding: utf-8 -*-
"""
Tests for language persistence and dialog locale key completeness.
Ensures that:
1. All supported locale files contain all required UI dialog keys.
2. QML ComboBoxes initialize with persisted settings without reverting to Turkish.
3. ConfigManager correctly persists and reloads UI and target languages.
"""

import json
import sys
from pathlib import Path

import pytest

REQUIRED_DIALOG_KEYS = [
    "completion_summary_subtitle",
    "dialog_ok",
    "dialog_cancel",
    "warning_title",
    "factory_reset_subtitle",
    "factory_reset_done_sub",
    "glossary_dlg_add_sub",
    "glossary_add_btn",
    "update_download_btn",
]

SUPPORTED_LANGUAGES = ["ru", "en", "tr", "de", "es", "fr", "fa", "zh-CN", "ja", "ko"]


def test_all_locales_have_dialog_keys():
    """Verify that all supported locales contain all required dialog keys with non-empty values."""
    locales_dir = Path("locales")
    assert locales_dir.exists(), "locales directory must exist"

    for lang in SUPPORTED_LANGUAGES:
        file_path = locales_dir / f"{lang}.json"
        assert file_path.exists(), f"Locale file {file_path} must exist"

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for key in REQUIRED_DIALOG_KEYS:
            assert key in data, f"Key '{key}' missing in {lang}.json"
            assert isinstance(data[key], str), f"Key '{key}' in {lang}.json must be a string"
            assert len(data[key].strip()) > 0, f"Key '{key}' in {lang}.json cannot be empty"


def test_config_manager_preserves_ui_and_target_language():
    """Verify that ConfigManager saves and loads both ui_language and target_language correctly."""
    from src.utils.config import ConfigManager, Language

    cfg_file = "test_config_persist.json"
    cm1 = ConfigManager(config_file=cfg_file)
    cm1.load_locale(Language.RUSSIAN)
    cm1.translation_settings.target_language = "russian"
    cm1.translation_settings.source_language = "english"
    saved = cm1.save_config()
    assert saved is True, "Config saving must succeed"

    cm2 = ConfigManager(config_file=cfg_file)
    assert cm2.app_settings.ui_language == "ru"
    assert cm2.translation_settings.target_language == "russian"
    assert cm2.translation_settings.source_language == "english"

    # Cleanup test file
    test_path = cm1.data_dir / cfg_file
    if test_path.exists():
        test_path.unlink()


@pytest.mark.parametrize("ui_language", ["ru", "ko"])
def test_qml_comboboxes_sync_persisted_languages(ui_language, tmp_path, monkeypatch):
    """Verify that the settings UI loads the persisted interface and target languages."""
    monkeypatch.setattr("src.utils.path_manager.get_data_path", lambda: tmp_path)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("QML_DISABLE_DISK_CACHE", "1")

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtQml import QQmlApplicationEngine
    from PyQt6.QtCore import QUrl

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv[:1])

    from src.backend.app_backend import AppBackend

    backend = AppBackend(parent=app)
    backend.config.translation_settings.target_language = "russian"
    backend.config.translation_settings.source_language = "auto"
    backend.setUILanguage(ui_language)
    assert backend.config.app_settings.ui_language == ui_language
    from src.utils.config import ConfigManager

    assert ConfigManager().app_settings.ui_language == ui_language

    engine = QQmlApplicationEngine(app)
    engine.rootContext().setContextProperty("appBackend", backend)
    from src.backend.editor_backend import EditorBackend
    editor_backend = EditorBackend(backend, parent=app)
    engine.rootContext().setContextProperty("editorBackend", editor_backend)

    qml_root = Path("src/gui/qml").resolve()
    engine.addImportPath(str(qml_root))
    engine.load(QUrl.fromLocalFile(str(qml_root / "Main.qml")))
    assert len(engine.rootObjects()) > 0, "Main.qml must load cleanly"

    root = engine.rootObjects()[0]

    combos = {}
    def walk(obj):
        name = obj.metaObject().className()
        # The Toolbox language-activation combo lists game/tl folders of the
        # last opened project, which can be "turkish" too — not a settings combo.
        if "ComboBox" in name and obj.objectName() != "toolLangActivateCombo":
            val = obj.property("currentValue")
            text = obj.property("displayText")
            idx = obj.property("currentIndex")
            if val in ("russian", "turkish", "german", "english"):
                combos["target"] = (val, text, idx)
            elif val in ("ru", "tr", "de", "en", "ko"):
                combos["ui_lang"] = (val, text, idx)
            elif val == "auto" and obj.property("valueRole") == "code":
                combos["source"] = (val, text, idx)
        for ch in obj.children():
            walk(ch)

    walk(root)

    assert "target" in combos, "Target language combo must be found"
    assert combos["target"][0] == "russian", f"Target language combo must be 'russian', got {combos['target']}"

    assert "ui_lang" in combos, "UI language combo must be found"
    assert combos["ui_lang"][0] == ui_language
    if ui_language == "ko":
        assert "한국어" in combos["ui_lang"][1]
        assert combos["source"][1] == "자동 감지 (auto)"
        assert backend.config.get_ui_text("nav_editor") == "편집기"
