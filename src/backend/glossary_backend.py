# -*- coding: utf-8 -*-
"""Glossary list, add/remove, auto-translate, import and export.

Part of the QML bridge; split out of AppBackend. QML reaches it as
``appBackend.glossary``. It shares the app backend's config, settings and logger
through properties, so a replaced config is picked up here too.
"""

import asyncio
import threading

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, pyqtProperty



class GlossaryBackend(QObject):
    glossaryChanged = pyqtSignal()

    def __init__(self, app) -> None:
        super().__init__(app)
        self.app = app
        app.settings.on("glossary", lambda: self.glossaryChanged.emit())

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

    # ── 📚 Sözlük Yönetimi (Glossary Management) ──────────────────────────

    @pyqtProperty(list, notify=glossaryChanged)
    def glossaryList(self) -> list:
        return self.settings.get_glossary_list()

    @pyqtSlot(str, str)
    def addGlossaryItem(self, source: str, target: str) -> None:
        self.settings.add_glossary_item(source, target)

    @pyqtSlot(str)
    def removeGlossaryItem(self, source: str) -> None:
        self.settings.remove_glossary_item(source)

    @pyqtSlot()
    def translateEmptyGlossary(self) -> None:
        """Boş hedef alanlarını Google Translate ile çevir."""
        threading.Thread(
            target=self._translate_empty_glossary_thread, daemon=True
        ).start()

    def _run_translate_batch_sync(self, translator, requests):
        """Run an async ``translate_batch`` from a worker thread.

        Creates a dedicated event loop and drops any aiohttp session bound to a
        previous (now-dead) loop, then closes the session afterwards. Without
        this, calling ``translate_batch`` synchronously returns a coroutine, and
        reusing a stale session raises 'Event loop is closed'.
        """

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(translator.close())
            return loop.run_until_complete(translator.translate_batch(requests))
        finally:
            try:
                loop.run_until_complete(translator.close())
            except Exception:
                pass
            loop.close()

    def _translate_empty_glossary_thread(self) -> None:
        try:
            if not hasattr(self.config, "glossary"):
                return
            empty_keys = [k for k, v in self.config.glossary.items() if not v]
            if not empty_keys:
                self.app.logMessage.emit(
                    "info", "✅ All glossary terms already have translations."
                )
                return

            self.app.logMessage.emit(
                "info", f"🌐 Translating {len(empty_keys)} empty terms via Google..."
            )
            from src.core.translator import (
                GoogleTranslator,
                TranslationEngine,
                TranslationRequest,
            )

            from src.tools.font_injector import _normalize_lang_code

            ts = getattr(self.config, "translation_settings", None)
            raw_src = getattr(ts, "source_language", "auto") if ts else "auto"
            raw_tgt = getattr(ts, "target_language", "turkish") if ts else "turkish"
            src_lang = _normalize_lang_code(raw_src) if raw_src != "auto" else "auto"
            tgt_lang = _normalize_lang_code(raw_tgt)

            translator = GoogleTranslator(config_manager=self.config)
            count = 0
            for key in empty_keys:
                try:
                    request = TranslationRequest(
                        text=key,
                        source_lang=src_lang,
                        target_lang=tgt_lang,
                        engine=TranslationEngine.GOOGLE,
                    )
                    results = self._run_translate_batch_sync(translator, [request])
                    if results:
                        translated = results[0].translated_text
                        if translated and translated != key:
                            self.config.glossary[key] = translated
                            count += 1
                except Exception:
                    self.logger.warning(
                        "Failed to translate glossary entry for key=%r", key
                    )
                if count % 10 == 0 and count > 0:
                    self.app.logMessage.emit(
                        "info", f"🌐 Translated: {count}/{len(empty_keys)}"
                    )

            self.config.save_glossary()
            self.glossaryChanged.emit()
            self.app.logMessage.emit(
                "success", f"✅ {count} glossary terms translated and saved."
            )
        except Exception as e:
            self.app.logMessage.emit("error", f"❌ Glossary translation failed: {e}")

    @pyqtSlot()
    def fillEmptyGlossaryWithSource(self) -> None:
        """Fill empty targets with source text."""
        if not hasattr(self.config, "glossary"):
            return
        count = 0
        for k, v in self.config.glossary.items():
            if not v:
                self.config.glossary[k] = k
                count += 1
        if count > 0:
            self.config.save_glossary()
            self.glossaryChanged.emit()
            self.app.logMessage.emit(
                "success", f"✅ {count} empty terms filled with source text."
            )
        else:
            self.app.logMessage.emit(
                "info", self._t("log_empty_terms_none", "No empty terms to fill.")
            )

    @pyqtSlot(str)
    def exportGlossary(self, filepath: str) -> None:
        """Export glossary to JSON/XLSX/CSV."""
        try:
            from src.utils.data_transfer import export_glossary_to_file

            glossary = getattr(self.config, "glossary", {})
            export_glossary_to_file(glossary, filepath)
            self.app.logMessage.emit("success", f"📤 Glossary exported to: {filepath}")
        except Exception as e:
            self.app.logMessage.emit("error", f"❌ Export error: {e}")

    @pyqtSlot(str)
    def importGlossary(self, filepath: str) -> None:
        """Import glossary from JSON/XLSX/CSV."""
        try:
            from src.utils.data_transfer import import_glossary_from_file

            imported = import_glossary_from_file(filepath)
            if not hasattr(self.config, "glossary"):
                self.config.glossary = {}
            new_count = 0
            updated_count = 0
            for src, tgt in imported.items():
                if src in self.config.glossary:
                    if self.config.glossary[src] != tgt and tgt:
                        self.config.glossary[src] = tgt
                        updated_count += 1
                else:
                    self.config.glossary[src] = tgt
                    new_count += 1
            self.config.save_glossary()
            self.glossaryChanged.emit()
            self.app.logMessage.emit(
                "success", f"📥 Imported: {new_count} new, {updated_count} updated."
            )
        except Exception as e:
            self.app.logMessage.emit("error", f"❌ Import error: {e}")
