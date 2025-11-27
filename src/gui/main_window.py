"""
Main Window
==========

Main application window with modern PyQt6/PySide6 interface.
"""

import sys
import logging
import asyncio
import time
from pathlib import Path
from typing import Optional, List

try:
    from PyQt6.QtWidgets import (
        QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox, QDoubleSpinBox,
        QProgressBar, QTextEdit, QFileDialog, QMenuBar, QStatusBar,
        QGroupBox, QCheckBox, QTabWidget, QSplitter, QTreeWidget, QTreeWidgetItem,
        QMessageBox, QDialog, QDialogButtonBox, QFormLayout, QSlider
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
    from PyQt6.QtGui import QFont, QIcon, QPixmap, QAction
    GUI_FRAMEWORK = "PyQt6"
except ImportError:
    from PySide6.QtWidgets import (
        QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox, QDoubleSpinBox,
        QProgressBar, QTextEdit, QFileDialog, QMenuBar, QStatusBar,
        QGroupBox, QCheckBox, QTabWidget, QSplitter, QTreeWidget, QTreeWidgetItem,
        QMessageBox, QDialog, QDialogButtonBox, QFormLayout, QSlider
    )
    from PySide6.QtCore import Qt, QThread, Signal as pyqtSignal, QTimer, QSize
    from PySide6.QtGui import QFont, QIcon, QPixmap, QAction
    GUI_FRAMEWORK = "PySide6"

from src.utils.config import ConfigManager
from src.version import VERSION
from src.core.parser import RenPyParser
from src.core.translator import TranslationManager, TranslationEngine, GoogleTranslator, DeepLTranslator, YandexTranslator
from src.core.output_formatter import RenPyOutputFormatter
from src.gui.translation_worker import TranslationWorker
from src.gui.settings_dialog import SettingsDialog
from src.gui.api_keys_dialog import ApiKeysDialog
from src.gui.glossary_dialog import GlossaryEditorDialog
from src.gui.info_dialog import InfoDialog
from src.gui.professional_themes import get_theme_qss

class MainWindow(QMainWindow):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        
        # Initialize components
        self.config_manager = ConfigManager()
        self.parser = RenPyParser(config_manager=self.config_manager)
        
        # Current theme (default: solarized)
        self.current_theme = self.config_manager.app_settings.theme
        
        # Lazy import to avoid circular imports
        from src.core.proxy_manager import ProxyManager
        self.proxy_manager = ProxyManager()
        # İlk konfigürasyonu config'ten al
        try:
            if hasattr(self.config_manager, 'proxy_settings'):
                self.proxy_manager.configure_from_settings(self.config_manager.proxy_settings)
        except Exception as e:
            self.logger.warning(f"Could not configure ProxyManager from settings: {e}")
        
        self.translation_manager = TranslationManager(self.proxy_manager)
        self.output_formatter = RenPyOutputFormatter()
        
        # Translation worker
        self.translation_worker = None
        self.worker_thread = None

        # Track active model download dialogs to avoid reopening same one (unused now)
        self._active_model_downloads = set()
        self._recently_closed_dialogs = {}

        # State
        self.current_directory = None
        self.extracted_texts = []
        self.translation_results = []
        
        # Initialize UI
        self.init_ui()
        self.setup_translation_engines()
        
        # Load settings
        self.load_settings()
        
        # Initialize proxy manager in background
        self.initialize_proxy_manager()
        
        # Refresh UI language after everything is set up
        self.refresh_ui_language()
        
        # Status update timer
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(1000)  # Update every second
    
    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle(self.config_manager.get_ui_text("app_title"))
        # Daha kompakt varsayılan pencere boyutu
        self.setMinimumSize(800, 500)
        
        # Set application icon
        # PyInstaller için exe çalışma zamanında doğru yolu bulma
        if getattr(sys, 'frozen', False):
            # PyInstaller ile paketlenmiş exe durumu - temporary dizinde icon var
            icon_path = Path(sys._MEIPASS) / "icon.ico"
        else:
            # Normal Python çalışma zamanı
            icon_path = Path(__file__).parent.parent.parent / "icon.ico"
        
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Create main layout
        layout = QVBoxLayout(central_widget)
        
        # Create menu bar
        self.create_menu_bar()
        
        # Create main content
        self.create_main_content(layout)
        
        # Create status bar
        self.create_status_bar()
        
        # Apply theme
        self.apply_theme()
    
    def create_menu_bar(self):
        """Create the menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu(self.config_manager.get_ui_text("file_menu"))
        
        open_action = QAction(self.config_manager.get_ui_text("open_directory"), self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_directory)
        file_menu.addAction(open_action)
        
        file_menu.addSeparator()
        
        save_action = QAction(self.config_manager.get_ui_text("save_translations"), self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_translations)
        file_menu.addAction(save_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction(self.config_manager.get_ui_text("exit"), self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Edit menu
        edit_menu = menubar.addMenu(self.config_manager.get_ui_text("edit_menu"))
        
        settings_action = QAction(self.config_manager.get_ui_text("settings"), self)
        settings_action.triggered.connect(self.show_settings)
        edit_menu.addAction(settings_action)
        
        api_keys_action = QAction(self.config_manager.get_ui_text("api_keys"), self)
        api_keys_action.triggered.connect(self.show_api_keys)
        edit_menu.addAction(api_keys_action)

        glossary_action = QAction(self.config_manager.get_ui_text("glossary_menu"), self)
        glossary_action.triggered.connect(self.show_glossary_editor)
        edit_menu.addAction(glossary_action)
        
        # View menu with theme options
        view_menu = menubar.addMenu(self.config_manager.get_ui_text("view_menu"))
        
        # Theme submenu
        theme_menu = view_menu.addMenu(self.config_manager.get_ui_text("theme_menu"))
        
        dark_theme_action = QAction(self.config_manager.get_ui_text("dark_theme"), self)
        dark_theme_action.triggered.connect(lambda: self.change_theme('dark'))
        theme_menu.addAction(dark_theme_action)
        
        solarized_theme_action = QAction(self.config_manager.get_ui_text("solarized_theme"), self)
        solarized_theme_action.triggered.connect(lambda: self.change_theme('solarized'))
        theme_menu.addAction(solarized_theme_action)
        
        # Help menu
        help_menu = menubar.addMenu(self.config_manager.get_ui_text("help_menu"))
        
        about_action = QAction(self.config_manager.get_ui_text("about"), self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
        
        info_action = QAction(self.config_manager.get_ui_text("info"), self)
        info_action.triggered.connect(self.show_info)
        help_menu.addAction(info_action)
    
    def create_main_content(self, parent_layout):
        """Create the main content area (only controls + progress)."""
        control_panel = self.create_control_panel()
        parent_layout.addWidget(control_panel)
    
    def create_control_panel(self) -> QWidget:
        """Create the control panel (minimal, wizard-like)."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # STEP 1: Project folder
        self.input_group = QGroupBox(self.config_manager.get_ui_text("input_section"))
        self.input_group._ui_key = "input_section"  # Store key for language updates
        input_layout = QFormLayout(self.input_group)

        self.directory_input = QLineEdit()
        self.directory_input.setPlaceholderText(self.config_manager.get_ui_text("directory_placeholder"))
        self.browse_button = QPushButton(self.config_manager.get_ui_text("browse"))
        self.browse_button.setProperty("class", "secondary")
        self.browse_button.clicked.connect(self.open_directory)

        dir_layout = QHBoxLayout()
        dir_layout.addWidget(self.directory_input)
        dir_layout.addWidget(self.browse_button)

        input_layout.addRow(self.config_manager.get_ui_text("directory_label"), dir_layout)
        layout.addWidget(self.input_group)

        # STEP 2: Basic translation options
        self.trans_group = QGroupBox(self.config_manager.get_ui_text("translation_settings"))
        self.trans_group._ui_key = "translation_settings"  # Store key for language updates
        trans_layout = QFormLayout(self.trans_group)

        # Source language
        self.source_lang_combo = QComboBox()
        self.populate_language_combo(self.source_lang_combo, include_auto=True)
        trans_layout.addRow(self.config_manager.get_ui_text("source_lang_label"), self.source_lang_combo)

        # Target language
        self.target_lang_combo = QComboBox()
        self.populate_language_combo(self.target_lang_combo)
        trans_layout.addRow(self.config_manager.get_ui_text("target_lang_label"), self.target_lang_combo)

        # Translation engine
        self.engine_combo = QComboBox()
        self.populate_engine_combo()
        trans_layout.addRow(self.config_manager.get_ui_text("translation_engine_label"), self.engine_combo)

        # Output format (compact description, detay InfoDialog'da)
        self.output_format_combo = QComboBox()
        self.output_format_combo.addItem("Simple", "simple")
        self.output_format_combo.addItem("Old/New", "old_new")
        self.output_format_combo.setCurrentIndex(1)
        trans_layout.addRow(self.config_manager.get_ui_text("output_format_label"), self.output_format_combo)

        layout.addWidget(self.trans_group)

        # STEP 3: Advanced ayarları artık Settings diyaloguna taşındı (burada panel yok)
        
        # Control buttons
        button_layout = QHBoxLayout()
        
        self.start_button = QPushButton(self.config_manager.get_ui_text("start_translation"))
        self.start_button.setProperty("class", "success")
        self.start_button.clicked.connect(self.start_translation)
        button_layout.addWidget(self.start_button)
        
        self.stop_button = QPushButton(self.config_manager.get_ui_text("stop_translation"))
        self.stop_button.setProperty("class", "error")
        self.stop_button.clicked.connect(self.stop_translation)
        self.stop_button.setEnabled(False)
        button_layout.addWidget(self.stop_button)
        
        layout.addLayout(button_layout)
        
        # Progress
        progress_group = QGroupBox(self.config_manager.get_ui_text("progress"))
        progress_layout = QVBoxLayout(progress_group)
        
        self.progress_bar = QProgressBar()
        progress_layout.addWidget(self.progress_bar)
        
        self.progress_label = QLabel(self.config_manager.get_ui_text("ready"))
        self.progress_label.setProperty("class", "caption")
        progress_layout.addWidget(self.progress_label)
        
        layout.addWidget(progress_group)
        
        # Add stretch to push everything to top
        layout.addStretch()
        
        return widget
    
    # Sonuç ve log panelleri artık ana pencerede gösterilmiyor.
    
    def populate_language_combo(self, combo: QComboBox, include_auto: bool = False):
        """Populate language combo box."""
        languages = self.config_manager.get_supported_languages()
        
        if not include_auto and 'auto' in languages:
            del languages['auto']
        
        for code, name in languages.items():
            combo.addItem(f"{name} ({code})", code)
    
    def populate_engine_combo(self):
        """Populate translation engine combo box with type indicators."""
        engines = [
            (TranslationEngine.GOOGLE, self.config_manager.get_ui_text("translation_engines.google")),
            (TranslationEngine.DEEPL, self.config_manager.get_ui_text("translation_engines.deepl")),
            (TranslationEngine.BING, self.config_manager.get_ui_text("translation_engines.bing")),
            (TranslationEngine.YANDEX, self.config_manager.get_ui_text("translation_engines.yandex")),
            (TranslationEngine.LIBRETRANSLATOR, self.config_manager.get_ui_text("translation_engines.libretranslator"))
        ]
        
        for engine, name in engines:
            self.engine_combo.addItem(name, engine)
    
    def refresh_engine_combo(self):
        """Refresh translation engine combo box when language changes."""
        # Save current selection
        current_engine = self.engine_combo.currentData()
        
        # Clear and repopulate
        self.engine_combo.clear()
        self.populate_engine_combo()
        
        # Restore selection
        if current_engine:
            for i in range(self.engine_combo.count()):
                if self.engine_combo.itemData(i) == current_engine:
                    self.engine_combo.setCurrentIndex(i)
                    break
    
    def create_status_bar(self):
        """Create the status bar."""
        self.status_bar = self.statusBar()
        
        # Status label
        self.status_label = QLabel(self.config_manager.get_ui_text("ready"))
        self.status_label.setProperty("class", "subtitle")
        self.status_bar.addWidget(self.status_label)
        
        # Stats labels
        self.files_label = QLabel(self.config_manager.get_ui_text("files_status").format(count=0))
        self.files_label.setProperty("class", "caption")
        self.status_bar.addPermanentWidget(self.files_label)
        
        self.texts_label = QLabel(self.config_manager.get_ui_text("texts_status").format(count=0))
        self.texts_label.setProperty("class", "caption")
        self.status_bar.addPermanentWidget(self.texts_label)
        
        self.translations_label = QLabel(self.config_manager.get_ui_text("translations_status").format(count=0))
        self.translations_label.setProperty("class", "caption")
        self.status_bar.addPermanentWidget(self.translations_label)
    
    def apply_theme(self):
        """Apply the current theme to the application."""
        try:
            # Get QSS for current theme
            qss = get_theme_qss(self.current_theme)
            self.setStyleSheet(qss)
            
            # Set window properties for modern look
            self.setWindowTitle(f"RenLocalizer v{VERSION} - Professional Ren'Py Translation Tool")
            
            self.logger.info(f"Applied {self.current_theme} theme successfully")
            
        except Exception as e:
            self.logger.error(f"Error applying theme {self.current_theme}: {e}")
            # Fallback to light theme
            if self.current_theme != 'light':
                self.current_theme = 'light'
                self.apply_theme()
    
    def change_theme(self, theme_name: str):
        """Change the application theme."""
        available_themes = ['dark', 'solarized']  # Şu an için sadece bu temalar aktif
        if theme_name in available_themes:
            self.current_theme = theme_name
            self.config_manager.app_settings.theme = theme_name  # set_setting yerine doğrudan atama
            self.config_manager.save_config()
            self.apply_theme()
            self.logger.info(f"Theme changed to: {theme_name}")
        else:
            self.logger.warning(f"Unknown or unavailable theme: {theme_name}")
    
    def setup_translation_engines(self):
        """Setup translation engines."""
        # Add Google Translator (free)
        google_translator = GoogleTranslator(proxy_manager=self.proxy_manager)
        self.translation_manager.add_translator(TranslationEngine.GOOGLE, google_translator)
        
    # Offline engine: optional third-party engines can be added here.
        
        # Add Deep-Translator (multi-engine wrapper) - optional
        try:
            # Deep-Translator removed from available engines
            self.logger.info("✅ Deep-Translator engine loaded successfully")
        except ImportError as e:
            self.logger.warning(f"⚠️ Deep-Translator not available: {e}")
            self.logger.info("💡 To install: pip install deep-translator")
        except Exception as e:
            self.logger.warning(f"⚠️ Deep-Translator engine error: {e}")
        
        # Add DeepL if API key is available
        deepl_key = self.config_manager.get_api_key("deepl")
        if deepl_key:
            deepl_translator = DeepLTranslator(api_key=deepl_key, proxy_manager=self.proxy_manager)
            self.translation_manager.add_translator(TranslationEngine.DEEPL, deepl_translator)
        
        # Add Yandex if API key is available
        yandex_key = self.config_manager.get_api_key("yandex")
        if yandex_key:
            yandex_translator = YandexTranslator(api_key=yandex_key, proxy_manager=self.proxy_manager)
            self.translation_manager.add_translator(TranslationEngine.YANDEX, yandex_translator)
    
    def initialize_proxy_manager(self):
        """Initialize proxy manager in background only if enabled."""
        # Check if proxy is enabled in config
        proxy_enabled = self.config_manager.proxy_settings.enabled
        if not proxy_enabled:
            self.logger.info("Proxy disabled in config - skipping proxy initialization")
            # Update status to show proxy is disabled
            QTimer.singleShot(100, lambda: self.status_label.setText(f"{self.config_manager.get_ui_text('ready')} - No Proxy"))
            return
        
        import asyncio
        import threading
        
        def run_async_init():
            try:
                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Run proxy initialization
                loop.run_until_complete(self.proxy_manager.initialize())
                
                # Log proxy stats
                stats = self.proxy_manager.get_proxy_stats()
                self.logger.info(f"Proxy manager initialized: {stats['working_proxies']}/{stats['total_proxies']} working proxies")
                
            except Exception as e:
                self.logger.error(f"Error initializing proxy manager: {e}")
            finally:
                loop.close()
        
        # Start proxy initialization in background thread
        proxy_thread = threading.Thread(target=run_async_init, daemon=True)
        proxy_thread.start()
        self.logger.info("Proxy manager initialization started in background")
    
    def load_settings(self):
        """Load settings from configuration."""
        # Set language selections
        source_lang = self.config_manager.translation_settings.source_language
        target_lang = self.config_manager.translation_settings.target_language
        
        # Find and set current language selections
        for i in range(self.source_lang_combo.count()):
            if self.source_lang_combo.itemData(i) == source_lang:
                self.source_lang_combo.setCurrentIndex(i)
                break
        
        for i in range(self.target_lang_combo.count()):
            if self.target_lang_combo.itemData(i) == target_lang:
                self.target_lang_combo.setCurrentIndex(i)
                break
        
        # Set output format
        output_format = getattr(self.config_manager.app_settings, 'output_format', 'old_new')
        for i in range(self.output_format_combo.count()):
            if self.output_format_combo.itemData(i) == output_format:
                self.output_format_combo.setCurrentIndex(i)
                break
        
        # Set last directory
        if self.config_manager.app_settings.last_input_directory:
            self.directory_input.setText(self.config_manager.app_settings.last_input_directory)
    
    def save_settings(self):
        """Save current settings."""
        # Language settings
        self.config_manager.translation_settings.source_language = self.source_lang_combo.currentData()
        self.config_manager.translation_settings.target_language = self.target_lang_combo.currentData()
        
            # Other settings removed as advanced settings are no longer controlled from main window
        # Save output format
        self.config_manager.app_settings.output_format = self.output_format_combo.currentData()
        
        # Directory
        self.config_manager.app_settings.last_input_directory = self.directory_input.text()
        
        # Save to file
        self.config_manager.save_config()
    
    def open_directory(self):
        """Open directory dialog."""
        directory = QFileDialog.getExistingDirectory(
            self,
            self.config_manager.get_ui_text("select_directory_title"),
            self.config_manager.app_settings.last_input_directory
        )
        
        if directory:
            self.directory_input.setText(directory)
            self.current_directory = Path(directory)
            self.scan_directory()
    
    def scan_directory(self):
        """Scan directory for .rpy files."""
        if not self.current_directory or not self.current_directory.exists():
            self.status_label.setText("No directory selected or directory doesn't exist")
            return
        
        try:
            self.status_label.setText(self.config_manager.get_ui_text("scanning_directory"))
            
            # Find .rpy files (currently always use sequential parsing in UI)
            rpy_files = list(self.current_directory.rglob('*.rpy'))

            # Use standard processing for now (parallel path removed from UI)
            self.status_label.setText("Using sequential processing...")
            self.extracted_texts = self.parser.parse_directory(self.current_directory)

            # Update status
            processing_mode = "sequential"
            self.files_label.setText(self.config_manager.get_ui_text("files_status").format(count=len(rpy_files)))
            self.texts_label.setText(self.config_manager.get_ui_text("texts_status").format(count=len(self.extracted_texts)))
            self.status_label.setText(f"{self.config_manager.get_ui_text('directory_scanned')} ({processing_mode})")
            
            self.logger.info(f"Scanned directory: {len(self.extracted_texts)} texts found using {processing_mode} processing")
            
        except Exception as e:
            self.logger.error(f"Error scanning directory: {e}")
            self.status_label.setText(self.config_manager.get_ui_text("error_scanning_directory"))
    
    def start_translation(self):
        """Start the translation process."""
        # Önce klasör seçimi kontrolü
        if not self.current_directory or not Path(self.directory_input.text()).exists():
            QMessageBox.warning(
                self,
                self.config_manager.get_ui_text("warning"),
                self.config_manager.get_ui_text("no_directory_warning"),
            )
            return

        if not self.extracted_texts:
            QMessageBox.warning(
                self,
                self.config_manager.get_ui_text("warning"),
                self.config_manager.get_ui_text("no_texts_warning"),
            )
            return
        
        # Get current settings
        source_lang = self.source_lang_combo.currentData()
        target_lang = self.target_lang_combo.currentData()
        engine = self.engine_combo.currentData()
        # Proxy ve concurrency ayarları artık sadece Settings diyalogundan okunuyor
        use_proxy = getattr(self.config_manager.proxy_settings, "enabled", False)
        max_threads = int(getattr(self.config_manager.translation_settings, "max_concurrent_threads", 16) or 16)
        max_threads = max(1, min(max_threads, 256))
        
        # Store parameters for potential restart after model download
        self.last_translation_params = {
            'source_lang': source_lang,
            'target_lang': target_lang, 
            'engine': engine,
            'use_proxy': use_proxy
        }
        
        # Configure translation manager based on proxy setting (from settings)
        if use_proxy:
            self.logger.info("Translation will use proxy rotation")
        else:
            self.logger.info("Translation will use direct connection (no proxy)")

        # Apply concurrency from settings
        try:
            self.translation_manager.set_max_concurrency(max_threads)
            self.logger.info(f"Max concurrent requests set to {max_threads}")
        except Exception:
            pass
        
        # Create and start worker
        self.translation_worker = TranslationWorker(
            texts=self.extracted_texts,
            source_lang=source_lang,
            target_lang=target_lang,
            engine=engine,
            translation_manager=self.translation_manager,
            config=self.config_manager,
            use_proxy=use_proxy
        )
        
        # Connect signals
        self.translation_worker.progress_updated.connect(self.update_progress)
        self.translation_worker.translation_completed.connect(self.on_translation_completed)
        self.translation_worker.error_occurred.connect(self.on_translation_error)
        self.translation_worker.finished.connect(self.on_translation_finished)
        
        # Start in thread
        self.worker_thread = QThread()
        self.translation_worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.translation_worker.run)
        self.worker_thread.start()
        
        # Update UI state
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText(self.config_manager.get_ui_text("starting_translation"))
    
    def stop_translation(self):
        """Stop the translation process."""
        if self.translation_worker:
            self.translation_worker.stop()
        
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText(self.config_manager.get_ui_text("stopping"))
    
    def update_progress(self, completed: int, total: int, current_text: str):
        """Update translation progress."""
        if total > 0:
            progress = int((completed / total) * 100)
            self.progress_bar.setValue(progress)
            self.progress_label.setText(f"{completed}/{total} - {current_text[:50]}...")
            self.translations_label.setText(self.config_manager.get_ui_text("translations_status").format(count=completed))
    
    def on_translation_completed(self, results):
        """Handle translation completion."""
        self.translation_results = results
        self.status_label.setText(self.config_manager.get_ui_text("translation_completed"))

        # Save extracted texts summary as a simple .txt log
        try:
            report_path = self._save_extracted_texts_report()
        except Exception as e:
            self.logger.warning(f"Could not save extracted texts report: {e}")
        
        # Auto-save translations if auto-save is enabled
        if hasattr(self.config_manager.app_settings, 'auto_save_translations') and self.config_manager.app_settings.auto_save_translations:
            self.auto_save_translations()
        else:
            # Show save dialog
            reply = QMessageBox.question(
                self,
                self.config_manager.get_ui_text("save_translations"),
                self.config_manager.get_ui_text("auto_save_question"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.save_translations()

    def _save_extracted_texts_report(self) -> Optional[str]:
        """Write a simple extracted-texts report to a .txt file and return its path.

        This replaces the old 'Extracted Texts' tab with a file-based log.
        """
        if not self.extracted_texts:
            return None

        try:
            logs_dir = Path.cwd() / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            current_time = time.strftime("%Y%m%d_%H%M%S")
            report_file = logs_dir / f"extracted_texts_{current_time}.txt"

            with open(report_file, "w", encoding="utf-8") as f:
                f.write("# Extracted texts report\n")
                f.write(f"# Total texts: {len(self.extracted_texts)}\n\n")
                for item in self.extracted_texts:
                    line = item.get("line_number", "?")
                    fpath = item.get("file_path", "?")
                    ttype = item.get("type", "?")
                    text = (item.get("text", "") or "").replace("\n", " ")
                    if len(text) > 150:
                        text = text[:150] + "..."
                    f.write(f"{fpath}:{line} | {ttype} | {text}\n")

            return str(report_file)
        except Exception as e:
            self.logger.warning(f"Error writing extracted texts report: {e}")
            return None
    
    def auto_save_translations(self):
        """Automatically save translations to default location."""
        if not self.translation_results:
            return
        
        try:
            # Determine output directory based on project structure
            output_dir = self._determine_output_directory()
            
            target_lang = self.target_lang_combo.currentData()
            selected_format = self.output_format_combo.currentData()

            # Save with Ren'Py structure support
            output_files = self.output_formatter.organize_output_files(
                self.translation_results,
                Path(output_dir),
                target_lang,
                output_format=selected_format,
                create_renpy_structure=True  # Enable Ren'Py structure
            )
            
            self.config_manager.app_settings.last_output_directory = output_dir
            self.save_settings()
            
            # Show success message in status bar
            self.status_label.setText(
                f"{self.config_manager.get_ui_text('translation_completed')} - "
                f"{self.config_manager.get_ui_text('auto_saved')} ({len(output_files)} files)"
            )
            
        except Exception as e:
            self.logger.error(f"Error auto-saving translations: {e}")
            
            # Show error dialog
            QMessageBox.critical(
                self,
                self.config_manager.get_ui_text("auto_save_error"),
                self.config_manager.get_ui_text("auto_save_error_message").format(error=str(e))
            )

    def _sync_results_from_tree(self):
        """Sync manual edits from results tree back into translation_results list."""
        # Eski sonuç ağacı UI'si kaldırıldığı için burada senkronize edilecek bir şey yok
        return

    def on_result_item_changed(self, item, column):
        """Handle inline edit on translation results tree (live sync)."""
        if column != 1:  # Only translated column is editable
            return
        idx = item.data(0, Qt.ItemDataRole.UserRole)
        if idx is None:
            return
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            return
        if 0 <= idx < len(self.translation_results):
            self.translation_results[idx].translated_text = item.text(1)
    
    def _determine_output_directory(self) -> str:
        """Determine the best output directory for translations."""
        # Check if we have a current directory (input directory)
        if self.current_directory:
            project_root = Path(self.current_directory)
            
            # Check if it's a Ren'Py project (has game folder)
            game_dir = None
            
            # Check current directory and parents for game folder
            current = project_root
            while current != current.parent:
                if (current / "game").exists():
                    game_dir = current
                    break
                current = current.parent
            
            if game_dir:
                # Ren'Py project detected - return project root
                return str(game_dir)
            else:
                # Not a Ren'Py project - use input directory
                return str(project_root)
        
        # Use last output directory or create default
        output_dir = self.config_manager.app_settings.last_output_directory
        if not output_dir or not Path(output_dir).exists():
            # Create default output directory
            current_time = time.strftime("%Y%m%d_%H%M%S")
            output_dir = Path.cwd() / "translations" / f"translation_{current_time}"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_dir = str(output_dir)
        
        return output_dir
    
    def on_translation_error(self, error_message):
        """Handle translation error."""
        self.logger.error(f"Translation error: {error_message}")
        QMessageBox.critical(self, self.config_manager.get_ui_text("translation_error"), error_message)
    
    def on_translation_finished(self):
        """Handle translation process finished."""
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        
        if self.worker_thread:
            self.worker_thread.quit()
            self.worker_thread.wait()
            self.worker_thread = None
        
        self.translation_worker = None
    
    def update_results_tree(self):
        """Legacy stub: results tree UI has been removed."""
        return
    
    def save_translations(self):
        """Save translations to files."""
        if not self.translation_results:
            QMessageBox.warning(self, self.config_manager.get_ui_text("warning"), self.config_manager.get_ui_text("no_translations_warning"))
            return
        
        output_dir = QFileDialog.getExistingDirectory(
            self,
            self.config_manager.get_ui_text("select_output_directory"),
            self.config_manager.app_settings.last_output_directory
        )
        
        if output_dir:
            try:
                target_lang = self.target_lang_combo.currentData()
                selected_format = self.output_format_combo.currentData()
                
                # Kullanıcının sonuç tablosunda yaptığı manuel düzenlemeleri uygula
                self._sync_results_from_tree()

                # Save with Ren'Py structure support
                output_files = self.output_formatter.organize_output_files(
                    self.translation_results,
                    Path(output_dir),
                    target_lang,
                    output_format=selected_format,
                    create_renpy_structure=True  # Enable Ren'Py structure
                )
                
                self.config_manager.app_settings.last_output_directory = output_dir
                self.save_settings()
                
                QMessageBox.information(
                    self,
                    self.config_manager.get_ui_text("success"),
                    self.config_manager.get_ui_text("translations_saved").format(count=len(output_files), directory=output_dir)
                )
                
            except Exception as e:
                self.logger.error(f"Error saving translations: {e}")
                QMessageBox.critical(self, self.config_manager.get_ui_text("error"), self.config_manager.get_ui_text("error_saving").format(error=str(e)))
    
    def update_status(self):
        """Update status periodically."""
        # Update proxy status in status bar
        if hasattr(self, 'proxy_manager') and self.proxy_manager.proxies:
            stats = self.proxy_manager.get_proxy_stats()
            working_proxies = stats['working_proxies']
            total_proxies = stats['total_proxies']
            
            # Update status bar with proxy info
            if working_proxies > 0:
                extra = ""
                # Cache stats ekle
                if hasattr(self, 'translation_manager'):
                    try:
                        cstats = self.translation_manager.get_cache_stats()
                        extra = f" - Cache: {cstats['hits']}/{cstats['misses']} ({cstats['hit_rate']}%)"
                    except Exception:
                        pass
                conc_part = ""
                if hasattr(self, 'translation_manager'):
                    try:
                        conc_part = f" - Concurrency: {self.translation_manager.max_concurrent_requests}"
                    except Exception:
                        pass
                self.status_label.setText(f"{self.config_manager.get_ui_text('ready')} - Proxy: {working_proxies}/{total_proxies}{conc_part}{extra}")
            else:
                self.status_label.setText(f"{self.config_manager.get_ui_text('ready')} - No Proxy")
        else:
            # Show loading proxy status
            extra = ""
            if hasattr(self, 'translation_manager'):
                try:
                    cstats = self.translation_manager.get_cache_stats()
                    extra = f" - Cache: {cstats['hits']}/{cstats['misses']} ({cstats['hit_rate']}%)"
                except Exception:
                    pass
            conc_part = ""
            if hasattr(self, 'translation_manager'):
                try:
                    conc_part = f" - Concurrency: {self.translation_manager.max_concurrent_requests}"
                except Exception:
                    pass
            self.status_label.setText(f"{self.config_manager.get_ui_text('ready')} - Loading Proxies...{conc_part}{extra}")
    
    def show_settings(self):
        """Show settings dialog."""
        dialog = SettingsDialog(self.config_manager, self)
        dialog.language_changed.connect(self.refresh_ui_language)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load_settings()
            # Check if language or theme changed
            if hasattr(dialog, 'language_changed_flag') and dialog.language_changed_flag:
                self.refresh_ui_language()
            if hasattr(dialog, 'theme_changed_flag') and dialog.theme_changed_flag:
                self.current_theme = self.config_manager.app_settings.theme
                self.apply_theme()
    
    def show_api_keys(self):
        """Show API keys dialog."""
        dialog = ApiKeysDialog(self.config_manager, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.setup_translation_engines()  # Refresh engines with new keys

    def show_glossary_editor(self):
        """Show glossary editor dialog."""
        dialog = GlossaryEditorDialog(self.config_manager, self)
        dialog.exec()
    
    def show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            self.config_manager.get_ui_text("about_title"),
            self.config_manager.get_ui_text("about_content").format(
                framework=GUI_FRAMEWORK,
                version=VERSION,
                year="2025",
                team="RenLocalizer Team" if self.config_manager.app_settings.ui_language == "en" else "RenLocalizer Ekibi"
            )
        )
    
    def show_info(self):
        """Show multi-page info dialog with detailed information."""
        dialog = InfoDialog(self)
        dialog.exec()
    
    def closeEvent(self, event):
        """Handle application close."""
        # Stop any running translation
        if self.translation_worker:
            self.stop_translation()
        
        # Save settings
        self.save_settings()

        # Asenkron translator oturumlarını kapat
        try:
            import asyncio
            asyncio.run(self.translation_manager.close_all())
        except Exception:
            pass
        
        event.accept()
    
    def refresh_ui_language(self):
        """Refresh UI elements when language changes."""
        # Update window title
        self.setWindowTitle(self.config_manager.get_ui_text("app_title"))
        
        # Update menu items (recreate menu bar)
        self.menuBar().clear()
        self.create_menu_bar()
        
        # Update group box titles and labels
        self.update_control_panel_texts()
        self.update_results_panel_texts()
        self.update_status_bar_texts()
        
        # Update button texts
        self.start_button.setText(self.config_manager.get_ui_text("start_translation"))
        self.stop_button.setText(self.config_manager.get_ui_text("stop_translation"))
        
        # Update progress label
        self.progress_label.setText(self.config_manager.get_ui_text("ready"))
        
        # Update status label
        self.status_label.setText(self.config_manager.get_ui_text("ready"))
        
        # Update translation engine combo box
        self.refresh_engine_combo()
    
    def update_control_panel_texts(self):
        """Update control panel text elements."""
        # Update group box titles
        if hasattr(self, 'input_group'):
            self.input_group.setTitle(self.config_manager.get_ui_text("input_section"))
        if hasattr(self, 'trans_group'):
            self.trans_group.setTitle(self.config_manager.get_ui_text("translation_settings"))
        if hasattr(self, 'advanced_group'):
            self.advanced_group.setTitle(self.config_manager.get_ui_text("advanced_settings"))
        
        # Update button texts
        if hasattr(self, 'browse_button'):
            self.browse_button.setText(self.config_manager.get_ui_text("browse"))
        if hasattr(self, 'directory_input'):
            self.directory_input.setPlaceholderText(self.config_manager.get_ui_text("directory_placeholder"))
    
    def update_results_panel_texts(self):
        """Update results panel text elements."""
        # Artık sonuç paneli olmadığından burada güncellenecek bir şey yok
        return
    
    def update_status_bar_texts(self):
        """Update status bar text elements."""
        if hasattr(self, 'files_label'):
            current_count = self.files_label.text().split(': ')[-1] if ': ' in self.files_label.text() else '0'
            self.files_label.setText(self.config_manager.get_ui_text("files_status").format(count=current_count))
        
        if hasattr(self, 'texts_label'):
            current_count = self.texts_label.text().split(': ')[-1] if ': ' in self.texts_label.text() else '0'
            self.texts_label.setText(self.config_manager.get_ui_text("texts_status").format(count=current_count))
        
        if hasattr(self, 'translations_label'):
            current_count = self.translations_label.text().split(': ')[-1] if ': ' in self.translations_label.text() else '0'
            self.translations_label.setText(self.config_manager.get_ui_text("translations_status").format(count=current_count))
    
    def on_proxy_setting_changed(self, state):
        """Handle proxy setting changes."""
        enabled = getattr(self.config_manager.proxy_settings, "enabled", False)
        self.logger.info(f"Proxy setting changed: {'enabled' if enabled else 'disabled'}")
        
        # Update translation manager
        if hasattr(self, 'translation_manager'):
            self.translation_manager.set_proxy_enabled(enabled)
        
        # Update config
        self.config_manager.proxy_settings.enabled = enabled
        
        # Save config if auto-save is enabled
        if self.config_manager.app_settings.auto_save_settings:
            self.config_manager.save_config()
    
    def refresh_proxies(self):
        """Manually refresh proxy list."""
        # Check if proxy is enabled
        if not self.config_manager.proxy_settings.enabled:
            self.logger.info("Proxy disabled - skipping proxy refresh")
            self.status_label.setText(f"{self.config_manager.get_ui_text('ready')} - No Proxy")
            return
            
        if hasattr(self, 'proxy_manager'):
            self.logger.info("Manually refreshing proxy list...")
            
            # Run proxy refresh in background thread
            import threading
            
            def refresh_task():
                try:
                    # Run async proxy initialization in new event loop
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(self.proxy_manager.initialize())
                    loop.close()
                    
                    # Log result
                    stats = self.proxy_manager.get_proxy_stats()
                    self.logger.info(
                        f"Proxy refresh completed. Working proxies: {stats['working_proxies']}/{stats['total_proxies']}"
                    )
                    
                except Exception as e:
                    self.logger.error(f"Error refreshing proxies: {e}")
            
            refresh_thread = threading.Thread(target=refresh_task, daemon=True)
            refresh_thread.start()

    # OPUS-MT model download handling removed (offline OPUS engine disabled)
    
    def restart_translation_after_download(self):
        """Restart translation after model download."""
        try:
            # Re-trigger translation with same settings
            if hasattr(self, 'last_translation_params'):
                params = self.last_translation_params
                self.start_translation()
            else:
                self.logger.warning("No previous translation parameters found")
                
        except Exception as e:
            self.logger.error(f"Error restarting translation: {e}")
            self.on_translation_error(f"Restart error: {e}")
