# -*- coding: utf-8 -*-
"""QML bridge for the translation editor page.

The editor reads and writes game/tl/<language>/*.rpy directly. It is
read-only while a translation run is active (both would write the same
files) and reloads afterwards, carrying unsaved edits over.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot

from src.core.editor.checks import code_tokens, find_problem
from src.core.editor.project import (
    LoadedLanguage, load_language, save_edits, sync_strings_json, sync_translation_cache,
)
from src.core.editor.store import KIND_FILTERS, STATUS_FILTERS, EditorStore

PAGE_SIZE = 50

_PROBLEM_TEXT = {
    "placeholder_set_mismatch": ("editor_problem_placeholder", "A [variable] or placeholder from the original is missing or changed."),
    "renpy_tag_set_mismatch": ("editor_problem_tags", "Text tags ({i}, {color}, ...) differ from the original."),
    "renpy_tag_order_mismatch": ("editor_problem_tag_order",
                                 "A text tag is closed before it is opened (for example {/i} before {i}); the game shows an error on this line."),
    "renpy_tag_order_invalid": ("editor_problem_tag_order",
                                "A text tag is closed before it is opened (for example {/i} before {i}); the game shows an error on this line."),
    "printf_set_mismatch": ("editor_problem_printf", "Format codes (%s, %d, ...) differ from the original."),
    "length_inflation": ("editor_problem_length", "The translation is much longer than the original."),
    "html_leakage": ("editor_problem_html", "The translation contains HTML markup."),
    "replacement_char": ("editor_problem_replacement_char",
                         "The translation contains an unreadable replacement character (U+FFFD)."),
    "placeholder_remnant": ("editor_problem_remnant", "The translation contains a leftover placeholder token."),
    "separator_remnant": ("editor_problem_remnant", "The translation contains a leftover placeholder token."),
}


class EditorBackend(QObject):
    languagesChanged = pyqtSignal()
    stateChanged = pyqtSignal()        # loaded / busy / locked / language / game
    pageChanged = pyqtSignal()         # rows, filters, paging, stats
    selectedChanged = pyqtSignal()
    notify = pyqtSignal(str, str, arguments=["level", "message"])
    _workDone = pyqtSignal(object, object)

    def __init__(self, app_backend: Any, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.app = app_backend
        self.store = EditorStore()
        self._loaded: Optional[LoadedLanguage] = None
        self._game_dir = ""
        self._language = ""
        self._languages: List[str] = []
        self._busy = False
        self._locked = bool(getattr(app_backend, "_is_translating", False))
        self._session_stamp = time.strftime("%Y%m%d-%H%M%S")

        self._search = ""
        self._file = "all"
        self._kind = "all"
        self._status = "all"
        self._pending_focus_query: Optional[str] = None
        self._pending_focus_file: Optional[str] = None
        self._page = 1
        self._total = 0
        self._rows: List[Dict[str, Any]] = []
        self._stats: Dict[str, int] = {}
        self._selected: Dict[str, Any] = {}

        self._workDone.connect(self._on_work_done)
        app_backend.translationStarted.connect(self._on_translation_started)
        app_backend.translationFinished.connect(self._on_translation_finished)

    # ── Helpers ─────────────────────────────────────────────────────────

    def _t(self, key: str, default: str, **kwargs: Any) -> str:
        text = self.app.config.get_ui_text(key, default)
        try:
            return text.format(**kwargs) if kwargs else text
        except (KeyError, IndexError, ValueError):
            return text

    def _run(self, job: Callable[[], Any], done: Callable[[Any], None]) -> None:
        """Run *job* off the GUI thread; *done* gets its result (or exception) on the GUI thread."""
        self._busy = True
        self.stateChanged.emit()

        def worker() -> None:
            try:
                result: Any = job()
            except Exception as exc:  # reported in _on_work_done
                self.logger.exception("[Editor] background job failed")
                result = exc
            self._workDone.emit(done, result)

        threading.Thread(target=worker, daemon=True).start()

    def _on_work_done(self, done: Callable[[Any], None], result: Any) -> None:
        self._busy = False
        if isinstance(result, Exception):
            self.notify.emit("error", f"❌ {result}")
        else:
            done(result)
        self.stateChanged.emit()

    def _view(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "file": row["file_rel"],
            "line": row["line"],
            "kind": row["kind"],
            "speaker": row["speaker_name"] or row["speaker"],
            "original": row["original"],
            "translated": row["translated"],
            "status": row["status"],
            "problem": row["problem"],
            "rejected": row["rejected"],
            "modified": bool(row["modified"]),
        }

    def _problem_text(self, code: str) -> str:
        if not code:
            return ""
        key, default = _PROBLEM_TEXT.get(code, ("editor_problem_generic", "This translation has a problem."))
        return self._t(key, default)

    def _refresh_page(self) -> None:
        rows, self._total = self.store.query(self._search, self._file, self._kind, self._status,
                                             self._page, PAGE_SIZE)
        pages = max(1, (self._total + PAGE_SIZE - 1) // PAGE_SIZE)
        if self._page > pages:
            self._page = pages
            rows, self._total = self.store.query(self._search, self._file, self._kind, self._status,
                                                 self._page, PAGE_SIZE)
        self._rows = [self._view(r) for r in rows]
        self._stats = self.store.stats()
        self.pageChanged.emit()
        ids = [r["id"] for r in self._rows]
        if self._selected.get("id") in ids:
            self._select(self._selected["id"])
        elif ids:
            self._select(ids[0])
        else:
            self._selected = {}
            self.selectedChanged.emit()

    def _select(self, entry_id: int) -> None:
        row = self.store.get(entry_id)
        if not row:
            self._selected = {}
        else:
            prev, nxt = self.store.neighbors(entry_id)
            view = self._view(row)
            view.update({
                "sourceRef": row["source_ref"],
                "blockId": row["block_id"],
                "tokens": code_tokens(row["original"]),
                "problemText": self._problem_text(row["problem"]),
                "rejectedText": self._problem_text(row["rejected"]) if row["rejected"] and row["status"] == "source_copy" else "",
                "prevSpeaker": (prev["speaker_name"] or prev["speaker"]) if prev else "",
                "prevText": (prev["translated"] or prev["original"]) if prev else "",
                "nextSpeaker": (nxt["speaker_name"] or nxt["speaker"]) if nxt else "",
                "nextText": (nxt["translated"] or nxt["original"]) if nxt else "",
            })
            self._selected = view
        self.selectedChanged.emit()

    def _replace_row(self, row: Optional[Dict[str, Any]]) -> None:
        if not row:
            return
        view = self._view(row)
        self._rows = [view if r["id"] == row["id"] else r for r in self._rows]
        self._stats = self.store.stats()
        self.pageChanged.emit()
        self._select(row["id"])

    # ── Properties ──────────────────────────────────────────────────────

    @pyqtProperty("QVariantList", notify=languagesChanged)
    def languages(self) -> List[str]:
        return self._languages

    @pyqtProperty(str, notify=stateChanged)
    def language(self) -> str:
        return self._language

    @pyqtProperty(str, notify=stateChanged)
    def gameName(self) -> str:
        return os.path.basename(os.path.dirname(self._game_dir)) if self._game_dir else ""

    @pyqtProperty(bool, notify=stateChanged)
    def loaded(self) -> bool:
        return self._loaded is not None

    @pyqtProperty(bool, notify=stateChanged)
    def busy(self) -> bool:
        return self._busy

    @pyqtProperty(bool, notify=stateChanged)
    def locked(self) -> bool:
        return self._locked

    @pyqtProperty("QVariantList", notify=pageChanged)
    def rows(self) -> List[Dict[str, Any]]:
        return self._rows

    @pyqtProperty("QVariantList", notify=pageChanged)
    def files(self) -> List[str]:
        return self.store.files() if self._loaded else []

    @pyqtProperty("QVariantMap", notify=pageChanged)
    def stats(self) -> Dict[str, int]:
        return self._stats

    @pyqtProperty(int, notify=pageChanged)
    def page(self) -> int:
        return self._page

    @pyqtProperty(int, notify=pageChanged)
    def pageCount(self) -> int:
        return max(1, (self._total + PAGE_SIZE - 1) // PAGE_SIZE)

    @pyqtProperty(int, notify=pageChanged)
    def totalCount(self) -> int:
        return self._total

    @pyqtProperty(bool, notify=pageChanged)
    def hasUnsavedChanges(self) -> bool:
        return bool(self._stats.get("modified"))

    @pyqtProperty("QVariantMap", notify=selectedChanged)
    def selected(self) -> Dict[str, Any]:
        return self._selected

    @pyqtProperty(str, notify=pageChanged)
    def search(self) -> str:
        return self._search

    @pyqtProperty(str, notify=pageChanged)
    def fileFilter(self) -> str:
        return self._file

    @pyqtProperty(str, notify=pageChanged)
    def kindFilter(self) -> str:
        return self._kind

    @pyqtProperty(str, notify=pageChanged)
    def statusFilter(self) -> str:
        return self._status

    # ── Loading ─────────────────────────────────────────────────────────

    @pyqtSlot()
    def refreshLanguages(self) -> None:
        """Language folders of the currently selected project."""
        from src.core.pipeline.saving import list_tl_languages

        game_dir = self.app._tool_game_dir() or ""
        if self._loaded is not None and game_dir != self._game_dir:
            self._loaded = None
            self._game_dir = game_dir
            self._language = ""
            self.store = EditorStore()
            self._rows = []
            self._stats = {}
            self._selected = {}
            self._total = 0
            self._page = 1
            self.stateChanged.emit()
            self.pageChanged.emit()
            self.selectedChanged.emit()
        self._languages = list_tl_languages(game_dir) if game_dir else []
        self.languagesChanged.emit()

    @pyqtSlot(result=str)
    def preferredLanguage(self) -> str:
        """The configured target language if it has a tl folder, else the first one."""
        if self._language and self._language in self._languages:
            return self._language
        target = (self.app.config.translation_settings.target_language or "").lower()
        for name in self._languages:
            if name.lower() == target:
                return name
        return self._languages[0] if self._languages else ""

    @pyqtSlot(str)
    def loadLanguage(self, language: str) -> None:
        game_dir = self.app._tool_game_dir() or ""
        if not game_dir or not language or self._busy:
            if not game_dir:
                self.notify.emit("error", self._t("log_select_game", "❌ Please select a game folder or EXE first."))
            return
        if game_dir != self._game_dir or language != self._language:
            self.store.load([])  # a different folder: nothing to carry over
            self._selected = {}
        self._game_dir, self._language = game_dir, language

        def done(loaded: LoadedLanguage) -> None:
            self._loaded = loaded
            self.store.load(loaded.rows)
            self._page = 1
            if self._pending_focus_query is not None or self._pending_focus_file is not None:
                q = self._pending_focus_query or ""
                f = self._pending_focus_file or ""
                self._pending_focus_query = None
                self._pending_focus_file = None
                self._apply_focus(q, f)
            else:
                self._refresh_page()
            self.notify.emit("info", self._t("editor_loaded", "{count} lines loaded.", count=len(loaded.rows)))

        self._run(lambda: load_language(game_dir, language), done)

    def _apply_focus(self, search_query: str, file_rel: str) -> None:
        self._kind = "all"
        self._status = "all"
        files = self.store.files() if self._loaded else []
        self._file = file_rel if (file_rel and file_rel in files) else "all"
        self._search = (search_query or "").strip()
        self._page = 1
        self._refresh_page()
        if self._rows:
            self._select(self._rows[0]["id"])

    @pyqtSlot(str, str, str)
    def focusEntry(self, language: str, search_query: str = "", file_rel: str = "") -> None:
        """Open *language* in the editor, filter by *file_rel*/*search_query*, and select the first match."""
        game_dir = self.app._tool_game_dir() or ""
        if not game_dir or not language:
            return
        if self._loaded is not None and game_dir == self._game_dir and language == self._language:
            self._apply_focus(search_query, file_rel)
            return
        self._pending_focus_query = search_query or ""
        self._pending_focus_file = file_rel or ""
        self.loadLanguage(language)

    @pyqtSlot()
    def reload(self) -> None:
        if self._language:
            self.loadLanguage(self._language)

    # ── Filters and paging ──────────────────────────────────────────────

    @pyqtSlot(str)
    def setSearch(self, text: str) -> None:
        if text != self._search:
            self._search, self._page = text, 1
            self._refresh_page()

    @pyqtSlot(str)
    def setFileFilter(self, value: str) -> None:
        value = value or "all"
        if value != self._file:
            self._file, self._page = value, 1
            self._refresh_page()

    @pyqtSlot(str)
    def setKindFilter(self, value: str) -> None:
        if value in KIND_FILTERS and value != self._kind:
            self._kind, self._page = value, 1
            self._refresh_page()

    @pyqtSlot(str)
    def setStatusFilter(self, value: str) -> None:
        if value in STATUS_FILTERS and value != self._status:
            self._status, self._page = value, 1
            self._refresh_page()

    @pyqtSlot(int)
    def setPage(self, page: int) -> None:
        page = max(1, min(page, self.pageCount))
        if page != self._page:
            self._page = page
            self._refresh_page()

    # ── Editing ─────────────────────────────────────────────────────────

    @pyqtSlot(int)
    def select(self, entry_id: int) -> None:
        self._select(entry_id)

    @pyqtSlot(str, result=str)
    def problemFor(self, text: str) -> str:
        """Warning for *text* as the selected line's translation, while it is typed."""
        if not self._selected:
            return ""
        code = find_problem(self._selected.get("original", ""), text)
        return self._problem_text(code) if code else ""

    @pyqtSlot(str)
    def applyEdit(self, text: str) -> None:
        if self._locked or not self._selected:
            return
        if text != self._selected.get("translated"):
            self._replace_row(self.store.update(self._selected["id"], text))

    @pyqtSlot()
    def revertSelected(self) -> None:
        if self._locked or not self._selected:
            return
        self._replace_row(self.store.revert(self._selected["id"]))

    @pyqtSlot(str, str, bool, result=int)
    def replaceAll(self, find: str, replace: str, match_case: bool) -> int:
        """Replace in translations matching the current filters; returns lines changed."""
        if self._locked or not self._loaded:
            return 0
        count = self.store.replace_all(find, replace, match_case, self._search, self._file,
                                       self._kind, self._status)
        self._refresh_page()
        self.notify.emit("info", self._t("editor_replaced", "{count} lines changed.", count=count))
        return count

    # ── Saving ──────────────────────────────────────────────────────────

    def _target_codes(self) -> List[str]:
        from src.core.pipeline.constants import RENPY_TO_API_LANG

        language = self._language
        codes = [language, RENPY_TO_API_LANG.get(language.lower(), "")]
        if language.lower() == (self.app.config.translation_settings.target_language or "").lower():
            codes.append(RENPY_TO_API_LANG.get(language.lower(), language))
        return [c for c in codes if c]

    def _sync_memory_cache(self, changes: Dict[str, str], codes: List[str]) -> None:
        tm = getattr(self.app, "translation_manager", None)
        cache = getattr(tm, "_cache", None)
        if not changes or cache is None:
            return
        from src.core.pipeline.constants import RENPY_TO_API_LANG
        from src.core.translator import TranslationEngine, TranslationResult
        from src.core.translators.factory import engine_enum

        wanted = {c.lower() for c in codes if c}
        updated_originals = set()
        target_bucket = None
        for key, val in list(cache.items()):
            if not (isinstance(key, tuple) and len(key) == 4):
                continue
            eng_str, sl, tl, orig = key
            if tl.lower() in wanted:
                if target_bucket is None:
                    target_bucket = (eng_str, sl, tl, getattr(val, "engine", None))
                if orig in changes and isinstance(val, TranslationResult):
                    val.translated_text = changes[orig]
                    val.success = True
                    updated_originals.add(orig)
        missing = {o: t for o, t in changes.items() if o not in updated_originals}
        if missing:
            if target_bucket is not None:
                eng_str, sl, tl, eng_obj = target_bucket
                if not isinstance(eng_obj, TranslationEngine):
                    eng_obj = engine_enum(eng_str)
            else:
                selected = getattr(self.app.config.translation_settings, "selected_engine", "google") or "google"
                eng_obj = engine_enum(selected)
                eng_str = eng_obj.value
                sl = getattr(self.app.config.translation_settings, "source_language", "auto") or "auto"
                tl = RENPY_TO_API_LANG.get(self._language.lower(), self._language)
            for orig, text in missing.items():
                cache[(eng_str, sl, tl, orig)] = TranslationResult(
                    orig, text, sl, tl, eng_obj, True, confidence=1.0
                )

    @pyqtSlot()
    def save(self) -> None:
        if self._locked or not self._loaded or self._busy:
            return
        edits = self.store.modified_by_file()
        if not edits:
            self.notify.emit("info", self._t("editor_nothing_to_save", "No changes to save."))
            return
        from src.core.pipeline.constants import RENPY_TO_API_LANG
        from src.core.pipeline.saving import get_diagnostics_dir
        from src.core.translators.factory import engine_enum
        from src.utils.path_manager import resolve_project_root, translation_cache_file

        lang_dir = os.path.join(self._game_dir, "tl", self._language)
        backup_dir = os.path.join(get_diagnostics_dir(lang_dir, self._language), "editor_backup", self._session_stamp)
        snapshots = self._loaded.snapshots
        project_root = resolve_project_root(self._game_dir)
        cache_file = translation_cache_file(self.app.config, project_root, self.app._project_path, self._language)
        codes = self._target_codes()
        selected_eng = getattr(self.app.config.translation_settings, "selected_engine", "google") or "google"
        insert_eng = engine_enum(selected_eng).value
        insert_src = getattr(self.app.config.translation_settings, "source_language", "auto") or "auto"
        insert_tl = RENPY_TO_API_LANG.get(self._language.lower(), self._language)
        pending_changes: Dict[str, str] = {}

        def job() -> Any:
            result = save_edits(edits, snapshots, backup_dir, lang_dir=lang_dir)
            saved = set(result.saved_ids)
            changes = {
                r["original"]: r["translated"]
                for rows in edits.values() for r in rows
                if r["id"] in saved and r["status"] == "translated" and not r["problem"]
            }
            pending_changes.update(changes)
            strings = {
                r["original"]: r["translated"]
                for rows in edits.values() for r in rows
                if r["id"] in saved and r["kind"] == "string" and r["status"] == "translated" and not r["problem"]
            }
            try:
                sync_strings_json(lang_dir, strings)
                sync_translation_cache(
                    cache_file,
                    codes,
                    changes,
                    insert_missing_engine=insert_eng,
                    insert_missing_source=insert_src,
                    insert_missing_target=insert_tl,
                )
            except Exception as exc:  # the tl files are saved; the cache is a bonus
                self.logger.warning("[Editor] cache/strings.json sync failed: %s", exc)
            return result

        def done(result: Any) -> None:
            self._sync_memory_cache(pending_changes, codes)
            self.store.mark_saved(result.saved_ids)
            self._refresh_page()
            if result.saved_ids:
                self.notify.emit("success", self._t(
                    "editor_saved", "{count} lines saved to {files} files.",
                    count=len(result.saved_ids), files=len(result.saved_files)))
            if result.conflicts:
                self.notify.emit("warning", self._t(
                    "editor_conflict",
                    "{files} files changed on disk after loading and were not saved. Reload, then save again.",
                    files=len(result.conflicts)))
            if result.failed_ids:
                self.notify.emit("warning", self._t(
                    "editor_failed_lines",
                    "{count} lines were not found where they were loaded and were not saved. Reload the editor.",
                    count=len(result.failed_ids)))
            if result.errors:
                self.notify.emit("error", self._t(
                    "editor_write_error", "{files} files could not be written.", files=len(result.errors)))

        self._run(job, done)

    # ── Machine suggestion ──────────────────────────────────────────────

    @pyqtSlot()
    def suggest(self) -> None:
        """Translate the selected line with the selected engine; the result is put in the editor, not saved."""
        if self._locked or not self._selected or self._busy:
            return
        row = self.store.get(self._selected["id"])
        if not row:
            return
        app = self.app
        if app._is_builtin_local_llm() and not app.llama_server.is_running():
            self.notify.emit("warning", self._t(
                "editor_suggest_server", "Start the local model server first (AI settings)."))
            return
        app._refresh_active_translator()
        # The project's own path keeps the cache id identical to a normal run.
        exe_path = app._project_path if app._tool_game_dir() == self._game_dir else os.path.dirname(self._game_dir)
        language = self._language

        def job() -> Any:
            from src.core.pipeline import TranslationPipeline
            from src.core.tl_parser import TranslationEntry

            pipeline = TranslationPipeline(app.config, app.translation_manager)
            pipeline.configure(
                game_exe_path=exe_path,
                target_language=language,
                source_language=app.config.translation_settings.source_language or "auto",
                engine=app._selected_engine,
                use_proxy=app.config.proxy_settings.enabled,
            )
            entry = TranslationEntry(
                original_text=row["original"], translated_text="", file_path=row["file_path"],
                line_number=row["line"], entry_type=row["kind"], translation_id="editor_suggestion",
            )
            # The cache holds this line's current translation (or the hand edit
            # synced on save); a suggestion has to come from the engine.
            with app.translation_manager.bypass_cache():
                return pipeline._translate_entries([entry]).get("editor_suggestion", "")

        entry_id = row["id"]

        def done(text: Any) -> None:
            if not text or text == row["original"]:
                self.notify.emit("warning", self._t("editor_suggest_failed", "No suggestion was returned."))
                return
            current = self.store.get(entry_id)
            if current and text == current["translated"]:
                self.notify.emit("info", self._t(
                    "editor_suggest_same", "The engine suggests the current translation."))
                return
            self._replace_row(self.store.update(entry_id, text))

        self._run(job, done)

    # ── Translation run coordination ────────────────────────────────────

    def _on_translation_started(self) -> None:
        self._locked = True
        self.stateChanged.emit()

    def _on_translation_finished(self, *_args: Any) -> None:
        self._locked = False
        self.stateChanged.emit()
        self.refreshLanguages()
        if self._loaded is not None and self._language:
            self.reload()
