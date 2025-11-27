"""Glossary Editor Dialog
=========================

Simple dialog to edit glossary.json (source term -> preferred translation).
"""

import json
from pathlib import Path
import logging

try:
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
        QPushButton, QDialogButtonBox, QLabel
    )
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QIcon
except ImportError:
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
        QPushButton, QDialogButtonBox, QLabel
    )
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon

from src.utils.config import ConfigManager
from src.gui.professional_themes import get_theme_qss


class GlossaryEditorDialog(QDialog):
    """Small dialog to view/edit glossary.json entries."""

    def __init__(self, config_manager: ConfigManager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.logger = logging.getLogger(__name__)

        # Determine glossary file path from translation settings
        self.glossary_path = Path(self.config_manager.translation_settings.glossary_file)

        self._init_ui()
        self._load_glossary()
        self._apply_theme()

    def _apply_theme(self):
        """Apply current theme to dialog."""
        current_theme = self.config_manager.get_setting('ui.theme', 'dark')
        qss = get_theme_qss(current_theme)
        self.setStyleSheet(qss)

    def _init_ui(self):
        """Build dialog layout."""
        self.setWindowTitle(self.config_manager.get_ui_text("glossary_title"))
        self.setModal(True)
        self.resize(600, 400)

        # Icon
        icon_path = Path(__file__).parent.parent.parent / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        layout = QVBoxLayout(self)

        info_label = QLabel(self.config_manager.get_ui_text("glossary_info"))
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Table: Source term | Preferred translation
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([
            self.config_manager.get_ui_text("glossary_source"),
            self.config_manager.get_ui_text("glossary_target"),
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        # Row buttons
        btn_layout = QHBoxLayout()
        self.add_row_btn = QPushButton(self.config_manager.get_ui_text("glossary_add"))
        self.remove_row_btn = QPushButton(self.config_manager.get_ui_text("glossary_remove"))
        self.add_row_btn.clicked.connect(self._add_row)
        self.remove_row_btn.clicked.connect(self._remove_selected_rows)
        btn_layout.addWidget(self.add_row_btn)
        btn_layout.addWidget(self.remove_row_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # OK / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_glossary(self):
        """Load existing glossary.json into the table."""
        data = {}
        try:
            if self.glossary_path.exists():
                with open(self.glossary_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    if isinstance(raw, dict):
                        data = raw
        except Exception as e:
            self.logger.warning(f"Could not load glossary file {self.glossary_path}: {e}")

        for src, dst in data.items():
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(src)))
            self.table.setItem(row, 1, QTableWidgetItem(str(dst)))

    def _add_row(self):
        """Append an empty row to the table."""
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(""))
        self.table.setItem(row, 1, QTableWidgetItem(""))

    def _remove_selected_rows(self):
        """Remove selected rows from the table."""
        selected = self.table.selectionModel().selectedRows()
        for index in sorted(selected, key=lambda i: i.row(), reverse=True):
            self.table.removeRow(index.row())

    def _collect_glossary(self) -> dict:
        """Collect table contents into a dict."""
        result = {}
        for row in range(self.table.rowCount()):
            src_item = self.table.item(row, 0)
            dst_item = self.table.item(row, 1)
            if not src_item or not dst_item:
                continue
            src = (src_item.text() or "").strip()
            dst = (dst_item.text() or "").strip()
            if not src or not dst:
                continue
            result[src] = dst
        return result

    def accept(self):
        """Save glossary.json on OK."""
        try:
            data = self._collect_glossary()
            self.glossary_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.glossary_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            # Update config manager in-memory glossary so new translations see it immediately
            self.config_manager.glossary = data
            self.logger.info(f"Glossary saved with {len(data)} entries to {self.glossary_path}")
        except Exception as e:
            self.logger.error(f"Error saving glossary: {e}")
            try:
                from PyQt6.QtWidgets import QMessageBox
            except ImportError:  # PySide6 fallback
                from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(
                self,
                self.config_manager.get_ui_text("error"),
                self.config_manager.get_ui_text("glossary_save_error").format(error=str(e)),
            )
        super().accept()
