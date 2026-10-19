# -*- coding: utf-8 -*-
"""EditorBackend: load, filter, edit, save, and the lock during translation runs."""
import contextlib
import os
import time
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal

from src.backend.editor_backend import EditorBackend

TL = (
    "translate turkish start_1:\n\n    # m \"Hello, [name]!\"\n    m \"\"\n\n"
    "translate turkish start_2:\n\n    # m \"Bye.\"\n    m \"Bye.\"\n\n"
    "translate turkish strings:\n\n    old \"Start\"\n    new \"Başla\"\n"
)


@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


class FakeApp(QObject):
    translationStarted = pyqtSignal()
    translationFinished = pyqtSignal(bool, str)

    def __init__(self, game_dir, tmp_path):
        super().__init__()
        self._game_dir = game_dir
        self._project_path = os.path.dirname(game_dir)
        self._is_translating = False
        self.config = SimpleNamespace(
            get_ui_text=lambda key, default=None, **kw: default,
            data_dir=str(tmp_path / "data"),
            translation_settings=SimpleNamespace(
                target_language="turkish", use_global_cache=False, cache_path="cache", source_language="auto"),
        )

    def _tool_game_dir(self):
        return self._game_dir


@pytest.fixture
def editor(qapp, tmp_path):
    game_dir = tmp_path / "proj" / "game"
    (game_dir / "tl" / "turkish").mkdir(parents=True)
    (game_dir / "script.rpy").write_text('define m = Character("Mia")\n', encoding="utf-8")
    (game_dir / "tl" / "turkish" / "script.rpy").write_text(TL, encoding="utf-8")
    app = FakeApp(str(game_dir), tmp_path)
    backend = EditorBackend(app)
    messages = []
    backend.notify.connect(lambda level, msg: messages.append((level, msg)))
    backend.messages = messages
    backend.fake_app = app
    return backend


def wait_idle(backend, timeout=10.0):
    deadline = time.time() + timeout
    QCoreApplication.processEvents()
    while backend.busy and time.time() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    QCoreApplication.processEvents()
    assert not backend.busy


def load(editor):
    editor.refreshLanguages()
    assert editor.languages == ["turkish"]
    assert editor.preferredLanguage() == "turkish"
    editor.loadLanguage("turkish")
    wait_idle(editor)
    assert editor.loaded


def test_load_filter_and_select(editor):
    load(editor)
    assert editor.totalCount == 3
    assert editor.stats["empty"] == 1 and editor.stats["source_copy"] == 1
    editor.setStatusFilter("untranslated")
    assert editor.totalCount == 2
    editor.setStatusFilter("all")
    editor.setSearch("hello")
    assert [r["speaker"] for r in editor.rows] == ["Mia"]
    sel = editor.selected
    assert sel["original"] == "Hello, [name]!" and sel["tokens"] == ["[name]"]
    assert sel["nextText"] == "Bye."


def test_edit_warning_save_and_lock(editor):
    load(editor)
    editor.setSearch("hello")
    editor.applyEdit("Merhaba!")
    assert editor.selected["problem"] == "placeholder_set_mismatch" and editor.selected["problemText"]
    editor.applyEdit("Merhaba, [name]!")
    assert editor.selected["problem"] == "" and editor.hasUnsavedChanges

    editor.fake_app.translationStarted.emit()
    assert editor.locked
    editor.applyEdit("ignored while a translation run writes the same files")
    editor.save()
    assert not editor.busy and editor.selected["translated"] == "Merhaba, [name]!"
    editor.fake_app.translationFinished.emit(True, "")
    wait_idle(editor)
    assert not editor.locked and editor.hasUnsavedChanges  # reload kept the edit

    editor.save()
    wait_idle(editor)
    assert not editor.hasUnsavedChanges
    assert any(level == "success" for level, _ in editor.messages)
    text = open(os.path.join(editor.fake_app._game_dir, "tl", "turkish", "script.rpy"), encoding="utf-8-sig").read()
    assert 'm "Merhaba, [name]!"' in text
    backups = os.path.join(editor.fake_app._game_dir, "tl", ".diagnostics", "turkish", "editor_backup")
    assert any(f.endswith(".rpy.bak") for _, _, fs in os.walk(backups) for f in fs)


def test_replace_all_respects_filters(editor):
    load(editor)
    editor.setKindFilter("string")
    assert editor.replaceAll("Başla", "Oyna", False) == 1
    editor.setKindFilter("all")
    editor.setSearch("bye")
    assert editor.rows[0]["translated"] == "Bye."


class _FakeManager:
    """Records whether the cache was bypassed while the pipeline ran."""

    def __init__(self):
        self.bypassed = False

    @contextlib.contextmanager
    def bypass_cache(self):
        self.bypassed = True
        try:
            yield
        finally:
            self.bypassed = False


def _fake_pipeline(monkeypatch, calls, answer):
    import src.core.pipeline as pipeline_pkg

    class FakePipeline:
        def __init__(self, config, manager):
            self.manager = manager

        def configure(self, **kwargs):
            calls.update(kwargs)

        def _translate_entries(self, entries):
            calls["text"] = entries[0].original_text
            calls["cache_bypassed"] = self.manager.bypassed
            return {entries[0].translation_id: answer}

    monkeypatch.setattr(pipeline_pkg, "TranslationPipeline", FakePipeline)


def test_suggest_fills_the_editor_without_saving(editor, monkeypatch):
    calls = {}
    _fake_pipeline(monkeypatch, calls, "Merhaba, [name]!")
    app = editor.fake_app
    app._selected_engine = "google"
    app.translation_manager = _FakeManager()
    app._is_builtin_local_llm = lambda: False
    app._refresh_active_translator = lambda: None
    app.config.proxy_settings = SimpleNamespace(enabled=False)

    load(editor)
    editor.setSearch("hello")
    editor.suggest()
    wait_idle(editor)
    assert calls["text"] == "Hello, [name]!" and calls["target_language"] == "turkish"
    # The cache would only hand back the current translation.
    assert calls["cache_bypassed"] and not app.translation_manager.bypassed
    assert editor.selected["translated"] == "Merhaba, [name]!" and editor.selected["modified"]
    path = os.path.join(app._game_dir, "tl", "turkish", "script.rpy")
    assert "Merhaba" not in open(path, encoding="utf-8").read()


def test_suggest_says_so_when_the_engine_repeats_the_translation(editor, monkeypatch):
    calls = {}
    _fake_pipeline(monkeypatch, calls, "Başla")
    app = editor.fake_app
    app._selected_engine = "bing"
    app.translation_manager = _FakeManager()
    app._is_builtin_local_llm = lambda: False
    app._refresh_active_translator = lambda: None
    app.config.proxy_settings = SimpleNamespace(enabled=False)

    load(editor)
    editor.setSearch("start")
    editor.suggest()
    wait_idle(editor)
    assert calls["text"] == "Start" and calls["cache_bypassed"]
    assert editor.selected["translated"] == "Başla" and not editor.selected["modified"]
    assert editor.messages[-1][0] == "info"


def test_warning_follows_the_text_being_typed(editor):
    load(editor)
    editor.setSearch("hello")
    assert editor.problemFor("Merhaba, [name]!") == ""
    assert "[variable]" in editor.problemFor("Merhaba!")
    assert editor.problemFor("") == ""  # an empty slot is untranslated, not broken
    # Nothing is applied while typing: the row still has its stored translation.
    assert editor.selected["translated"] == "" and not editor.selected["modified"]
