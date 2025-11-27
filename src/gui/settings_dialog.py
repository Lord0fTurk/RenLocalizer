"""
Settings Dialog
==============

Dialog for configuring application settings.
"""

import logging

try:
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget,
        QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox, QDoubleSpinBox,
        QCheckBox, QGroupBox, QDialogButtonBox, QSlider, QTextEdit
    )
    from PyQt6.QtCore import Qt, pyqtSignal
    from PyQt6.QtGui import QIcon
except ImportError:
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget,
        QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox, QDoubleSpinBox,
        QCheckBox, QGroupBox, QDialogButtonBox, QSlider, QTextEdit
    )
    from PySide6.QtCore import Qt, Signal as pyqtSignal
    from PySide6.QtGui import QIcon

from src.utils.config import ConfigManager, Language
from src.gui.professional_themes import get_theme_qss

class SettingsDialog(QDialog):
    """Settings dialog for configuring the application."""
    
    language_changed = pyqtSignal()
    
    def __init__(self, config_manager: ConfigManager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.logger = logging.getLogger(__name__)
        self.language_changed_flag = False
        self.theme_changed_flag = False
        
        self.init_ui()
        self.load_settings()
        self.apply_theme()
        
        # Connect language change signal
        self.ui_language_combo.currentTextChanged.connect(self.on_language_changed)
    
    def apply_theme(self):
        """Apply current theme to dialog."""
        current_theme = self.config_manager.get_setting('ui.theme', 'dark')
        qss = get_theme_qss(current_theme)
        self.setStyleSheet(qss)
    
    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle(self.config_manager.get_ui_text("settings"))
        self.setModal(True)
        self.resize(500, 600)
        
        # Set dialog icon
        from pathlib import Path
        import sys
        # PyInstaller için exe çalışma zamanında doğru yolu bulma
        if getattr(sys, 'frozen', False):
            # PyInstaller ile paketlenmiş exe durumu - temporary dizinde icon var
            icon_path = Path(sys._MEIPASS) / "icon.ico"
        else:
            # Normal Python çalışma zamanı
            icon_path = Path(__file__).parent.parent.parent / "icon.ico"
        
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        
        layout = QVBoxLayout(self)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)
        
        # Create tabs
        self.create_general_tab()
        self.create_translation_tab()
        self.create_proxy_tab()
        self.create_advanced_tab()
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | 
            QDialogButtonBox.StandardButton.Cancel |
            QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self.restore_defaults)
        layout.addWidget(buttons)
    
    def create_general_tab(self):
        """Create general settings tab."""
        widget = QGroupBox()
        layout = QFormLayout(widget)
        
        # UI Language
        self.ui_language_combo = QComboBox()
        self.ui_language_combo.addItem("Türkçe", Language.TURKISH.value)
        self.ui_language_combo.addItem("English", Language.ENGLISH.value)
        layout.addRow(self.config_manager.get_ui_text("ui_language_label"), self.ui_language_combo)
        
        # Theme
        self.theme_combo = QComboBox()
        self.theme_combo.addItem(self.config_manager.get_ui_text("dark_theme"), "dark")
        self.theme_combo.addItem(self.config_manager.get_ui_text("solarized_theme"), "solarized")
        layout.addRow(self.config_manager.get_ui_text("theme_label"), self.theme_combo)
        
        # Auto save settings
        self.auto_save_check = QCheckBox()
        layout.addRow(self.config_manager.get_ui_text("auto_save_label"), self.auto_save_check)
        
        # Auto save translations
        self.auto_save_translations_check = QCheckBox()
        layout.addRow(self.config_manager.get_ui_text("auto_save_translations_label"), self.auto_save_translations_check)
        
        # Check for updates
        self.check_updates_check = QCheckBox()
        layout.addRow(self.config_manager.get_ui_text("check_updates_label"), self.check_updates_check)
        
        self.tab_widget.addTab(widget, self.config_manager.get_ui_text("general_tab"))
    
    def create_translation_tab(self):
        """Create translation settings tab."""
        widget = QGroupBox()
        layout = QFormLayout(widget)
        
        # Default languages
        lang_group = QGroupBox(self.config_manager.get_ui_text("default_languages_group"))
        lang_layout = QFormLayout(lang_group)
        
        self.default_source_combo = QComboBox()
        self.populate_language_combo(self.default_source_combo, include_auto=True)
        lang_layout.addRow(self.config_manager.get_ui_text("source_lang_label"), self.default_source_combo)
        
        self.default_target_combo = QComboBox()
        self.populate_language_combo(self.default_target_combo)
        lang_layout.addRow(self.config_manager.get_ui_text("target_lang_label"), self.default_target_combo)
        
        layout.addWidget(lang_group)
        
        # Performance settings
        perf_group = QGroupBox(self.config_manager.get_ui_text("performance_group"))
        perf_layout = QFormLayout(perf_group)
        
        self.max_threads_spin = QSpinBox()
        self.max_threads_spin.setRange(1, 128)
        perf_layout.addRow(self.config_manager.get_ui_text("max_threads_label"), self.max_threads_spin)
        
        self.max_batch_spin = QSpinBox()
        self.max_batch_spin.setRange(1, 1000)
        perf_layout.addRow(self.config_manager.get_ui_text("max_batch_label"), self.max_batch_spin)
        
        self.request_delay_spin = QDoubleSpinBox()
        self.request_delay_spin.setRange(0.0, 10.0)
        self.request_delay_spin.setSingleStep(0.1)
        self.request_delay_spin.setSuffix(" s")
        perf_layout.addRow(self.config_manager.get_ui_text("request_delay_setting_label"), self.request_delay_spin)
        
        layout.addWidget(perf_group)
        
        # Retry settings
        retry_group = QGroupBox(self.config_manager.get_ui_text("retry_settings_group"))
        retry_layout = QFormLayout(retry_group)
        
        self.max_retries_spin = QSpinBox()
        self.max_retries_spin.setRange(0, 10)
        retry_layout.addRow(self.config_manager.get_ui_text("max_retries_label"), self.max_retries_spin)
        
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 300)
        self.timeout_spin.setSuffix(" s")
        retry_layout.addRow(self.config_manager.get_ui_text("timeout_label"), self.timeout_spin)
        
        layout.addWidget(retry_group)
        
        self.tab_widget.addTab(widget, self.config_manager.get_ui_text("translation_tab"))
    
    def create_proxy_tab(self):
        """Create proxy settings tab."""
        widget = QGroupBox()
        layout = QFormLayout(widget)
        
        # Enable proxy
        self.enable_proxy_check = QCheckBox()
        layout.addRow(self.config_manager.get_ui_text("enable_proxy_label"), self.enable_proxy_check)
        
        # Auto rotate
        self.auto_rotate_check = QCheckBox()
        layout.addRow(self.config_manager.get_ui_text("auto_rotate_label"), self.auto_rotate_check)
        
        # Test on startup
        self.test_startup_check = QCheckBox()
        layout.addRow(self.config_manager.get_ui_text("test_startup_label"), self.test_startup_check)
        
        # Update interval
        self.update_interval_spin = QSpinBox()
        self.update_interval_spin.setRange(300, 86400)  # 5 minutes to 24 hours
        self.update_interval_spin.setSuffix(" s")
        layout.addRow(self.config_manager.get_ui_text("update_interval_label"), self.update_interval_spin)
        
        # Max failures
        self.max_failures_spin = QSpinBox()
        self.max_failures_spin.setRange(1, 100)
        layout.addRow(self.config_manager.get_ui_text("max_failures_label"), self.max_failures_spin)
        
        # Custom proxies
        custom_group = QGroupBox(self.config_manager.get_ui_text("custom_proxies_group"))
        custom_layout = QVBoxLayout(custom_group)
        
        custom_layout.addWidget(QLabel(self.config_manager.get_ui_text("custom_proxies_note")))
        
        self.custom_proxies_text = QTextEdit()
        self.custom_proxies_text.setMaximumHeight(100)
        custom_layout.addWidget(self.custom_proxies_text)
        
        # Manual refresh button
        proxy_button_layout = QHBoxLayout()
        self.refresh_proxies_btn = QPushButton(self.config_manager.get_ui_text("refresh_proxies_btn"))
        self.refresh_proxies_btn.clicked.connect(self.refresh_proxies_clicked)
        proxy_button_layout.addWidget(self.refresh_proxies_btn)
        proxy_button_layout.addStretch()
        custom_layout.addLayout(proxy_button_layout)
        
        layout.addWidget(custom_group)
        
        self.tab_widget.addTab(widget, self.config_manager.get_ui_text("proxy_tab"))
    
    def create_advanced_tab(self):
        """Create advanced settings tab."""
        widget = QGroupBox()
        layout = QFormLayout(widget)
        
        # Logging level
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItem("DEBUG", "DEBUG")
        self.log_level_combo.addItem("INFO", "INFO")
        self.log_level_combo.addItem("WARNING", "WARNING")
        self.log_level_combo.addItem("ERROR", "ERROR")
        layout.addRow(self.config_manager.get_ui_text("log_level_label"), self.log_level_combo)
        
        # Max log file size
        self.max_log_size_spin = QSpinBox()
        self.max_log_size_spin.setRange(1, 100)
        self.max_log_size_spin.setSuffix(" MB")
        layout.addRow(self.config_manager.get_ui_text("max_log_size_label"), self.max_log_size_spin)
        
        # Memory optimization
        memory_group = QGroupBox(self.config_manager.get_ui_text("memory_optimization_group"))
        memory_layout = QFormLayout(memory_group)
        
        self.chunk_size_spin = QSpinBox()
        self.chunk_size_spin.setRange(1024, 1048576)  # 1KB to 1MB
        self.chunk_size_spin.setSuffix(" bytes")
        memory_layout.addRow(self.config_manager.get_ui_text("chunk_size_label"), self.chunk_size_spin)
        
        layout.addWidget(memory_group)
        
        # Debugging
        debug_group = QGroupBox(self.config_manager.get_ui_text("debugging_group"))
        debug_layout = QFormLayout(debug_group)
        
        self.debug_mode_check = QCheckBox()
        debug_layout.addRow(self.config_manager.get_ui_text("debug_mode_label"), self.debug_mode_check)
        
        self.verbose_logging_check = QCheckBox()
        debug_layout.addRow(self.config_manager.get_ui_text("verbose_logging_label"), self.verbose_logging_check)
        
        layout.addWidget(debug_group)
        
        self.tab_widget.addTab(widget, self.config_manager.get_ui_text("advanced_tab"))
    
    def populate_language_combo(self, combo: QComboBox, include_auto: bool = False):
        """Populate language combo box."""
        languages = self.config_manager.get_supported_languages()
        
        if not include_auto and 'auto' in languages:
            del languages['auto']
        
        for code, name in languages.items():
            combo.addItem(f"{name} ({code})", code)
    
    def load_settings(self):
        """Load current settings into the dialog."""
        # General settings
        ui_lang = self.config_manager.app_settings.ui_language
        for i in range(self.ui_language_combo.count()):
            if self.ui_language_combo.itemData(i) == ui_lang:
                self.ui_language_combo.setCurrentIndex(i)
                break
        
        theme = self.config_manager.app_settings.theme
        for i in range(self.theme_combo.count()):
            if self.theme_combo.itemData(i) == theme:
                self.theme_combo.setCurrentIndex(i)
                break
        
        self.auto_save_check.setChecked(self.config_manager.app_settings.auto_save_settings)
        self.auto_save_translations_check.setChecked(self.config_manager.get_setting('ui.auto_save_translations', True))
        self.check_updates_check.setChecked(self.config_manager.app_settings.check_for_updates)
        
        # Translation settings
        source_lang = self.config_manager.translation_settings.source_language
        for i in range(self.default_source_combo.count()):
            if self.default_source_combo.itemData(i) == source_lang:
                self.default_source_combo.setCurrentIndex(i)
                break
        
        target_lang = self.config_manager.translation_settings.target_language
        for i in range(self.default_target_combo.count()):
            if self.default_target_combo.itemData(i) == target_lang:
                self.default_target_combo.setCurrentIndex(i)
                break
        
        self.max_threads_spin.setValue(self.config_manager.translation_settings.max_concurrent_threads)
        self.max_batch_spin.setValue(self.config_manager.translation_settings.max_batch_size)
        self.request_delay_spin.setValue(self.config_manager.translation_settings.request_delay)
        self.max_retries_spin.setValue(self.config_manager.translation_settings.max_retries)
        self.timeout_spin.setValue(self.config_manager.translation_settings.timeout)
        
        # Proxy settings
        self.enable_proxy_check.setChecked(self.config_manager.proxy_settings.enabled)
        self.auto_rotate_check.setChecked(self.config_manager.proxy_settings.auto_rotate)
        self.test_startup_check.setChecked(self.config_manager.proxy_settings.test_on_startup)
        self.update_interval_spin.setValue(self.config_manager.proxy_settings.update_interval)
        self.max_failures_spin.setValue(self.config_manager.proxy_settings.max_failures)
        
        # Custom proxies
        custom_proxies = self.config_manager.proxy_settings.custom_proxies
        if custom_proxies:
            self.custom_proxies_text.setPlainText('\\n'.join(custom_proxies))
        
        # Advanced settings
        self.log_level_combo.setCurrentText("INFO")  # Default
        self.max_log_size_spin.setValue(10)  # 10 MB default
        self.chunk_size_spin.setValue(8192)  # 8KB default
        self.debug_mode_check.setChecked(False)
        self.verbose_logging_check.setChecked(False)
    
    def save_settings(self):
        """Save settings from the dialog."""
        # Check if language or theme changed
        old_language = self.config_manager.app_settings.ui_language
        old_theme = self.config_manager.app_settings.theme
        
        # General settings
        self.config_manager.app_settings.ui_language = self.ui_language_combo.currentData()
        self.config_manager.app_settings.theme = self.theme_combo.currentData()
        self.config_manager.app_settings.auto_save_settings = self.auto_save_check.isChecked()
        self.config_manager.set_setting('ui.auto_save_translations', self.auto_save_translations_check.isChecked())
        self.config_manager.app_settings.check_for_updates = self.check_updates_check.isChecked()
        
        # Translation settings
        self.config_manager.translation_settings.source_language = self.default_source_combo.currentData()
        self.config_manager.translation_settings.target_language = self.default_target_combo.currentData()
        self.config_manager.translation_settings.max_concurrent_threads = self.max_threads_spin.value()
        self.config_manager.translation_settings.max_batch_size = self.max_batch_spin.value()
        self.config_manager.translation_settings.request_delay = self.request_delay_spin.value()
        self.config_manager.translation_settings.max_retries = self.max_retries_spin.value()
        self.config_manager.translation_settings.timeout = self.timeout_spin.value()
        
        # Proxy settings
        self.config_manager.proxy_settings.enabled = self.enable_proxy_check.isChecked()
        self.config_manager.proxy_settings.auto_rotate = self.auto_rotate_check.isChecked()
        self.config_manager.proxy_settings.test_on_startup = self.test_startup_check.isChecked()
        self.config_manager.proxy_settings.update_interval = self.update_interval_spin.value()
        self.config_manager.proxy_settings.max_failures = self.max_failures_spin.value()
        
        # Custom proxies
        custom_text = self.custom_proxies_text.toPlainText().strip()
        if custom_text:
            self.config_manager.proxy_settings.custom_proxies = [
                line.strip() for line in custom_text.split('\n') if line.strip()
            ]
        else:
            self.config_manager.proxy_settings.custom_proxies = []
        
        # Set flags for parent window
        if old_language != self.config_manager.app_settings.ui_language:
            self.language_changed_flag = True
        if old_theme != self.config_manager.app_settings.theme:
            self.theme_changed_flag = True
        
        # Save to file
        self.config_manager.save_config()
        self.logger.info("Settings saved")
    
    def on_language_changed(self):
        """Handle language change event."""
        # Update UI language immediately
        current_lang = self.ui_language_combo.currentData()
        if current_lang:
            self.config_manager.app_settings.ui_language = current_lang
            self.refresh_dialog_language()
    
    def refresh_dialog_language(self):
        """Refresh dialog language when changed."""
        # Update window title
        self.setWindowTitle(self.config_manager.get_ui_text("settings"))
        
        # Update tab titles
        self.tab_widget.setTabText(0, self.config_manager.get_ui_text("general_tab"))
        self.tab_widget.setTabText(1, self.config_manager.get_ui_text("translation_tab"))
        self.tab_widget.setTabText(2, self.config_manager.get_ui_text("proxy_tab"))
        self.tab_widget.setTabText(3, self.config_manager.get_ui_text("advanced_tab"))
        
        # Emit signal to parent
        self.language_changed.emit()
    
    def restore_defaults(self):
        """Restore default settings."""
        self.config_manager.reset_to_defaults()
        self.load_settings()
        self.logger.info("Settings restored to defaults")
    
    def accept(self):
        """Accept and save settings."""
        self.save_settings()
        super().accept()
    
    def refresh_proxies_clicked(self):
        """Handle refresh proxies button click."""
        try:
            # Get parent window's proxy manager
            parent_window = self.parent()
            if hasattr(parent_window, 'refresh_proxies'):
                parent_window.refresh_proxies()
                # Show message
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self, 
                    self.config_manager.get_ui_text("info"), 
                    self.config_manager.get_ui_text("proxy_refresh_started")
                )
            else:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self, 
                    self.config_manager.get_ui_text("warning"), 
                    self.config_manager.get_ui_text("proxy_refresh_unavailable")
                )
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(
                self, 
                self.config_manager.get_ui_text("error"), 
                f"Proxy refresh error: {e}"
            )
