# -*- coding: utf-8 -*-
"""Toolbox actions: fonts, lint, glossary extraction, RPA, language activation.

Part of the QML bridge; split out of AppBackend. QML reaches it as
``appBackend.toolbox``. It shares the app backend's config, settings and logger
through properties, so a replaced config is picked up here too.
"""

import os
import threading
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSlot



class ToolboxBackend(QObject):

    def __init__(self, app) -> None:
        super().__init__(app)
        self.app = app

    # Shared state lives on the app backend.
    @property
    def config(self):
        return self.app.config

    @property
    def settings(self):
        return self.app.settings

    @property
    def logger(self):
        return self.app.logger

    @property
    def proxy_manager(self):
        return self.app.proxy_manager

    def _t(self, key: str, default: str) -> str:
        return self.app._t(key, default)

    # ── 12. ARAÇ KUTUSU (TOOLBOX) SLOTLARI ───────────────────────────────
    @pyqtSlot()
    def runToolFontHelper(self) -> None:
        """Run font compatibility check."""
        if not self._require_tool_game_dir():
            return
        self.app.logMessage.emit(
            "info",
            self._t(
                "log_font_check_starting", "🔤 Font compatibility check starting..."
            ),
        )
        threading.Thread(target=self._run_font_helper_thread, daemon=True).start()

    def _run_font_helper_thread(self) -> None:
        try:
            from src.tools.font_helper import check_font_for_project

            target_lang = getattr(
                self.config.translation_settings, "target_language", "turkish"
            )
            # The selected path may be the game's EXE; fonts live under game/.
            summary = check_font_for_project(self.app._tool_game_dir(), target_lang)
            total = summary.get("fonts_checked", 0)
            compat = summary.get("compatible_fonts", 0)
            incompat = summary.get("incompatible_fonts", 0)
            suggestions = summary.get("suggestions", [])
            sug_str = f" Recommended: {', '.join(suggestions[:3])}" if suggestions else ""
            basis = (
                "the characters your translation uses"
                if summary.get("basis") == "translation"
                else f"a '{target_lang}' sample (no translation yet)"
            )
            if incompat > 0:
                missing = summary.get("missing_by_font", {})
                details = "; ".join(f"{name}: {chars}" for name, chars in list(missing.items())[:3])
                self.app.logMessage.emit(
                    "warning",
                    f"⚠️ Font check against {basis}: {total} font(s) scanned — {incompat} cannot show "
                    f"all characters (missing → {details}).{sug_str} Use 'Inject' to add a matching font.",
                )
            elif total > 0:
                self.app.logMessage.emit(
                    "success",
                    f"✅ Font check against {basis}: all {compat} font(s) can show '{target_lang}'.",
                )
            else:
                self.app.logMessage.emit(
                    "info",
                    f"ℹ️ No custom fonts found in game folder. Ren'Py will use its default font.{sug_str}",
                )
        except Exception as e:
            self.app.logMessage.emit("error", f"❌ Font helper error: {e}")

    @pyqtSlot()
    def runToolFontInject(self) -> None:
        """Download and inject Google Fonts."""
        if not self._require_tool_game_dir():
            return
        self.app.logMessage.emit(
            "info", "🔤 Downloading and injecting font from Google Fonts..."
        )
        threading.Thread(target=self._run_font_inject_thread, daemon=True).start()

    def _run_font_inject_thread(self) -> None:
        try:
            from src.tools.font_injector import inject_font

            target_lang = getattr(
                self.config.translation_settings, "target_language", "turkish"
            )
            result = inject_font(self.app._tool_game_dir(), target_lang)
            if result.get("success"):
                self.app.logMessage.emit(
                    "success", f"✅ Font injected: {result.get('font', '?')}"
                )
            else:
                self.app.logMessage.emit(
                    "warning", f"⚠️ Font injection failed: {result.get('message', '?')}"
                )
        except Exception as e:
            self.app.logMessage.emit("error", f"❌ Font injection error: {e}")

    @pyqtSlot()
    def runToolRenpyLint(self) -> None:
        """Run Ren'Py lint on game project."""
        if not self._require_tool_game_dir():
            return
        self.app.logMessage.emit(
            "info", self._t("log_lint_starting", "🩺 Ren'Py Lint scanner running...")
        )
        threading.Thread(target=self._run_renpy_lint_thread, daemon=True).start()

    def _run_renpy_lint_thread(self) -> None:
        try:
            from src.tools.renpy_lint import lint_translation_output

            sdk_path = self.config.app_settings.renpy_sdk_path
            game_dir = self.app._tool_game_dir()
            tl_dir = os.path.join(game_dir, "tl")
            target_path = tl_dir if os.path.isdir(tl_dir) else game_dir
            report = lint_translation_output(
                target_path,
                try_engine_lint=bool(sdk_path),
                game_dir=os.path.dirname(game_dir),
                sdk_path=sdk_path,
            )
            if report is None:
                self.app.logMessage.emit("warning", "⚠️ Lint could not run on the selected project.")
            elif report.ok:
                self.app.logMessage.emit(
                    "success",
                    f"✅ Lint passed: {report.files_scanned} files scanned, {report.translate_blocks} translate blocks, {report.old_new_pairs} old/new pairs. No syntax or indentation errors found.",
                )
            else:
                self.app.logMessage.emit(
                    "warning",
                    f"⚠️ Lint findings: {report.errors} error(s), {report.warnings} warning(s)\n{report.summary()}",
                )
        except Exception as e:
            self.app.logMessage.emit("error", f"❌ Ren'Py Lint error: {e}")

    # ── Tool: language activation file ──────────────────────────────────

    def _require_tool_game_dir(self) -> Optional[str]:
        """game/ dir for a Toolbox action, or None after telling the user why."""
        game_dir = self.app._tool_game_dir()
        if not game_dir:
            self.app.logMessage.emit("error", self._t(
                "log_select_game", "❌ Please select a game folder or EXE first."))
        return game_dir

    @pyqtSlot(result=list)
    def toolListTlLanguages(self) -> list:
        """Languages that have a game/tl/<lang> folder in the selected project."""
        game_dir = self.app._tool_game_dir()
        if not game_dir:
            return []
        from src.core.pipeline.saving import list_tl_languages
        return list_tl_languages(game_dir)

    @pyqtSlot(result=str)
    def toolDefaultTlLanguage(self) -> str:
        """Pre-selection for the tool: the dashboard target if it has a tl/ folder."""
        langs = self.toolListTlLanguages()
        target = (self.app._target_language or "").lower()
        for lang in langs:
            if lang.lower() == target:
                return lang
        return langs[0] if langs else ""

    @pyqtSlot(str)
    def runToolActivateLanguage(self, language: str) -> None:
        """Write game/zzz_<lang>_language.rpy so the game starts in *language*.

        Ren'Py does not list tl/ folders by itself; without this file (or a
        language menu in the game) a finished translation never shows up.
        """
        game_dir = self.app._tool_game_dir()
        if not game_dir:
            self.app.logMessage.emit("error", self._t(
                "log_select_game", "❌ Please select a game folder or EXE first."))
            return
        language = (language or "").strip()
        if not language:
            self.app.logMessage.emit("warning", self._t(
                "tool_lang_no_tl", "No translation folders found in game/tl. Translate the game first."))
            return
        from src.core.pipeline.saving import create_language_init_file
        create_language_init_file(game_dir, language, self.config, self.app.logMessage.emit, force=True)
        self.app.logMessage.emit("success", self._t(
            "log_lang_activated", "✅ The game will now start in: {lang}").replace("{lang}", language))

    @pyqtSlot()
    def runToolRemoveLanguageActivation(self) -> None:
        """Remove RenLocalizer's language activation file(s) from game/."""
        game_dir = self.app._tool_game_dir()
        if not game_dir:
            self.app.logMessage.emit("error", self._t(
                "log_select_game", "❌ Please select a game folder or EXE first."))
            return
        from src.core.pipeline.saving import remove_language_init_files
        removed = remove_language_init_files(game_dir)
        if removed:
            self.app.logMessage.emit("success", self._t(
                "log_lang_activation_removed",
                "✅ Language activation removed; the game starts in its own language again."))
        else:
            self.app.logMessage.emit("info", self._t(
                "log_lang_activation_none", "No language activation file was found in game/."))

    @pyqtSlot()
    def runToolGlossaryExtractor(self) -> None:
        """Extract glossary terms from project."""
        if not self._require_tool_game_dir():
            return
        self.app.logMessage.emit(
            "info",
            self._t("log_glossary_extracting", "📚 Extracting glossary terms..."),
        )
        threading.Thread(
            target=self._run_glossary_extractor_thread, daemon=True
        ).start()

    def _run_glossary_extractor_thread(self) -> None:
        try:
            from src.tools.glossary_extractor.extractor import GlossaryExtractor

            extractor = GlossaryExtractor()
            # Scan game/ (the selected path may be the EXE). The terms go into
            # RenLocalizer's own glossary; nothing is written into the game.
            terms = extractor.extract_from_directory(
                self.app._tool_game_dir(), min_occurrence=3
            )
            added = 0
            for term, target in terms.items():
                if term not in self.config.glossary:
                    self.config.glossary[term] = target
                    added += 1
            self.config.save_glossary()
            self.app.glossary.glossaryChanged.emit()
            self.app.logMessage.emit(
                "success",
                self._t(
                    "log_glossary_extracted",
                    "✅ {found} terms found, {added} new ones added to the glossary (Glossary tab).",
                ).replace("{found}", str(len(terms))).replace("{added}", str(added)),
            )
        except Exception as e:
            self.app.logMessage.emit("error", f"❌ Glossary extractor error: {e}")
