# -*- coding: utf-8 -*-
"""Backend bridge for the Developer Inspection page (shown when developerMode is enabled)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, QUrl, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QDesktopServices

from src.utils.encoding import read_json_safely


class DeveloperBackend(QObject):
    """Reads isolated pipeline diagnostics for the active project and exposes actionable items."""

    stateChanged = pyqtSignal()

    def __init__(self, app_backend: Any, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.app = app_backend
        self._game_dir: str = ""
        self._language: str = ""
        self._languages: List[str] = []
        self._category: str = "all"
        self._search: str = ""
        self._report_path: str = ""
        self._summary: Dict[str, Any] = {}
        self._all_items: List[Dict[str, Any]] = []
        self._items: List[Dict[str, Any]] = []

        if hasattr(app_backend, "translationFinished"):
            app_backend.translationFinished.connect(lambda *_: self.refresh())

    # ── Properties ──────────────────────────────────────────────────────

    @pyqtProperty("QVariantList", notify=stateChanged)
    def languages(self) -> List[str]:
        return self._languages

    @pyqtProperty(str, notify=stateChanged)
    def language(self) -> str:
        return self._language

    @pyqtProperty(str, notify=stateChanged)
    def categoryFilter(self) -> str:
        return self._category

    @pyqtProperty(str, notify=stateChanged)
    def searchQuery(self) -> str:
        return self._search

    @pyqtProperty(str, notify=stateChanged)
    def reportPath(self) -> str:
        return self._report_path

    @pyqtProperty("QVariantMap", notify=stateChanged)
    def summary(self) -> Dict[str, Any]:
        return self._summary

    @pyqtProperty("QVariantList", notify=stateChanged)
    def items(self) -> List[Dict[str, Any]]:
        return self._items

    # ── Slots ───────────────────────────────────────────────────────────

    @pyqtSlot(str)
    def setCategoryFilter(self, category: str) -> None:
        cat = (category or "all").strip().lower()
        if cat not in ("all", "blocked", "warnings", "files"):
            cat = "all"
        if cat != self._category:
            self._category = cat
            self._apply_filter()
            self.stateChanged.emit()

    @pyqtSlot(str)
    def setSearchQuery(self, query: str) -> None:
        cleaned = (query or "").strip()
        if cleaned != self._search:
            self._search = cleaned
            self._apply_filter()
            self.stateChanged.emit()

    @pyqtSlot(str)
    def loadLanguage(self, language: str) -> None:
        if language and language != self._language:
            self._language = language
        self.refresh()

    @pyqtSlot()
    def refresh(self) -> None:
        """Reload diagnostics from tl/.diagnostics/<lang>/ for the current project."""
        from src.core.pipeline.saving import get_diagnostics_dir, list_tl_languages

        game_dir = self.app._tool_game_dir() or ""
        self._game_dir = game_dir
        self._languages = list_tl_languages(game_dir) if game_dir else []
        self._language = self._resolve_language(self._languages)

        if not game_dir or not self._language:
            self._clear_state()
            self.stateChanged.emit()
            return

        lang_dir = os.path.join(game_dir, "tl", self._language)
        diag_dir = get_diagnostics_dir(lang_dir, self._language)
        diag_file = os.path.join(diag_dir, f"diagnostic_{self._language}.json")
        guard_file = os.path.join(diag_dir, "translation_blocked_or_fallback.json")

        self._report_path = diag_file if os.path.isfile(diag_file) else ""
        diag_data = read_json_safely(diag_file) if self._report_path else None
        guard_data = read_json_safely(guard_file) if os.path.isfile(guard_file) else None

        self._build_items(diag_data, guard_data, game_dir, lang_dir)
        self._apply_filter()
        self.stateChanged.emit()

    @pyqtSlot(str)
    def openInExternalEditor(self, path: str) -> None:
        """Open a file path in the OS default text/code editor."""
        if not path or not os.path.exists(path):
            return
        if hasattr(self.app, "openLocalPath"):
            self.app.openLocalPath(path)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(path)))

    @pyqtSlot(str)
    def openParentFolder(self, path: str) -> None:
        """Open the containing directory of a file path."""
        if not path:
            return
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        if folder and os.path.isdir(folder):
            self.openInExternalEditor(folder)

    @pyqtSlot()
    def openRawReport(self) -> None:
        """Open the active diagnostic_<lang>.json file in the OS editor."""
        if self._report_path and os.path.isfile(self._report_path):
            self.openInExternalEditor(self._report_path)

    # ── Internal helpers ────────────────────────────────────────────────

    def _clear_state(self) -> None:
        self._report_path = ""
        self._summary = {}
        self._all_items = []
        self._items = []

    def _resolve_language(self, available: List[str]) -> str:
        if not available:
            return ""
        if self._language in available:
            return self._language
        target = (getattr(self.app.config.translation_settings, "target_language", "") or "").lower()
        for lang in available:
            if lang.lower() == target:
                return lang
        return available[0]

    def _apply_filter(self) -> None:
        base = (
            self._all_items
            if self._category == "all"
            else [it for it in self._all_items if it.get("category") == self._category]
        )
        q = self._search.lower()
        if not q:
            self._items = list(base)
            return
        self._items = [
            it for it in base
            if q in (
                f"{it.get('title', '')} {it.get('detail', '')} "
                f"{it.get('filePath', '')} {it.get('badge', '')}"
            ).lower()
        ]

    def _resolve_openable_paths(self, raw_path: str, game_dir: str, lang_dir: str) -> tuple[str, str]:
        """Return (source_or_best_path, tl_output_path) for an entry."""
        if not raw_path:
            return ("", "")
        candidate = raw_path if os.path.isabs(raw_path) else os.path.join(game_dir, raw_path)
        tl_candidate = ""
        try:
            rel = os.path.relpath(os.path.abspath(candidate), os.path.abspath(game_dir))
            if not rel.startswith(".."):
                stem = os.path.splitext(rel)[0] + ".rpy"
                possible_tl = os.path.join(lang_dir, stem)
                if os.path.isfile(possible_tl):
                    tl_candidate = possible_tl
        except ValueError:
            pass
        src_exists = os.path.isfile(candidate)
        return (candidate if src_exists else tl_candidate, tl_candidate)

    def _build_items(
        self,
        diag_data: Optional[Dict[str, Any]],
        guard_data: Optional[Dict[str, Any]],
        game_dir: str,
        lang_dir: str,
    ) -> None:
        totals = diag_data.get("totals", {}) if isinstance(diag_data, dict) else {}
        prov = diag_data.get("provenance", {}) if isinstance(diag_data, dict) else {}
        items: List[Dict[str, Any]] = []

        if isinstance(guard_data, dict):
            for sample in guard_data.get("samples", []) or []:
                if not isinstance(sample, dict):
                    continue
                open_path, tl_path = self._resolve_openable_paths(
                    str(sample.get("file_path") or ""), game_dir, lang_dir
                )
                tl_rel = os.path.relpath(tl_path, lang_dir).replace("\\", "/") if tl_path else ""
                orig_preview = str(sample.get("original_preview") or "")
                items.append({
                    "category": "blocked",
                    "badge": str(sample.get("category") or "guard"),
                    "title": orig_preview or str(sample.get("translation_id") or ""),
                    "detail": str(sample.get("detail") or sample.get("translated_preview") or ""),
                    "filePath": tl_path or open_path,
                    "fileRel": tl_rel,
                    "editorQuery": orig_preview[:80],
                    "sourcePath": open_path,
                    "line": int(sample.get("line_number") or 0),
                })

        if isinstance(diag_data, dict):
            self._append_warning_items(items, diag_data, game_dir, lang_dir)
            self._append_file_items(items, diag_data, game_dir, lang_dir)

        self._all_items = items
        self._summary = {
            "engine": str(prov.get("engine") or ""),
            "model": str(prov.get("model") or ""),
            "translated": int(totals.get("translated") or 0),
            "blocked": int(totals.get("blocked_as_corrupted") or 0),
            "unchanged": int(totals.get("unchanged_by_engine") or totals.get("unchanged") or 0),
            "warnings": int(totals.get("coverage_warning_count") or 0),
            "totalItems": len(items),
        }

    def _append_warning_items(
        self,
        items: List[Dict[str, Any]],
        diag_data: Dict[str, Any],
        game_dir: str,
        lang_dir: str,
    ) -> None:
        for warn in diag_data.get("coverage_warnings", []) or []:
            if not isinstance(warn, dict):
                continue
            code = str(warn.get("code") or "warning")
            count = int(warn.get("count") or 0)
            samples = warn.get("samples") or []
            if samples and isinstance(samples, list):
                for smp in samples[:25]:
                    if not isinstance(smp, dict):
                        continue
                    raw_fp = str(smp.get("file_path") or "")
                    open_path, tl_path = self._resolve_openable_paths(raw_fp, game_dir, lang_dir)
                    tl_rel = os.path.relpath(tl_path, lang_dir).replace("\\", "/") if tl_path else ""
                    var_name = str(smp.get("variable") or smp.get("label") or "")
                    smp_val = str(smp.get("value") or "")
                    items.append({
                        "category": "warnings",
                        "badge": code,
                        "title": var_name or Path(raw_fp).name or code,
                        "detail": str(smp_val or smp.get("reason") or f"count={count}"),
                        "filePath": open_path or tl_path,
                        "fileRel": tl_rel,
                        "editorQuery": smp_val[:80] if smp_val else "",
                        "sourcePath": open_path,
                        "line": int(smp.get("line_number") or 0),
                    })
            else:
                items.append({
                    "category": "warnings",
                    "badge": code,
                    "title": code,
                    "detail": f"count={count}",
                    "filePath": self._report_path,
                    "fileRel": "",
                    "editorQuery": "",
                    "sourcePath": self._report_path,
                    "line": 0,
                })

    def _append_file_items(
        self,
        items: List[Dict[str, Any]],
        diag_data: Dict[str, Any],
        game_dir: str,
        lang_dir: str,
    ) -> None:
        files_map = diag_data.get("files", {})
        if not isinstance(files_map, dict):
            return
        for raw_fp, info in files_map.items():
            if not isinstance(info, dict):
                continue
            blocked = int(info.get("blocked") or 0)
            unchanged = int(info.get("unchanged") or 0)
            skipped = int(info.get("skipped") or 0)
            if blocked == 0 and unchanged == 0 and skipped == 0:
                continue
            open_path, tl_path = self._resolve_openable_paths(str(raw_fp), game_dir, lang_dir)
            tl_rel = os.path.relpath(tl_path, lang_dir).replace("\\", "/") if tl_path else ""
            items.append({
                "category": "files",
                "badge": f"blocked:{blocked} unchanged:{unchanged}",
                "title": os.path.basename(str(raw_fp)) or str(raw_fp),
                "detail": (
                    f"translated={info.get('translated', 0)}, "
                    f"written={info.get('written', 0)}, skipped={skipped}"
                ),
                "filePath": tl_path or open_path,
                "fileRel": tl_rel,
                "editorQuery": "",
                "sourcePath": open_path,
                "line": 0,
            })
