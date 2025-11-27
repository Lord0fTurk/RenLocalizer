"""
Translation Worker
=================

Background worker for handling translation tasks with placeholder preservation.
"""

import asyncio
import logging
from typing import List, Dict
from pathlib import Path

try:
    from PyQt6.QtCore import QObject, pyqtSignal
except ImportError:
    from PySide6.QtCore import QObject, Signal as pyqtSignal

from src.core.translator import TranslationManager, TranslationRequest, TranslationEngine
from src.core.parser import RenPyParser  # Import for placeholder preservation
from src.utils.config import ConfigManager

class TranslationWorker(QObject):
    """Worker for background translation processing."""
    
    # Signals
    progress_updated = pyqtSignal(int, int, str)  # completed, total, current_text
    translation_completed = pyqtSignal(list)  # translation_results
    error_occurred = pyqtSignal(str)  # error_message
    # No model download signal (OPUS-MT removed)
    finished = pyqtSignal()
    
    def __init__(self, texts: List[Dict], source_lang: str, target_lang: str, 
                 engine: TranslationEngine, translation_manager: TranslationManager,
                 config: ConfigManager, use_proxy: bool = True):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        
        self.texts = texts
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.engine = engine
        self.translation_manager = translation_manager
        self.config = config
        self.use_proxy = use_proxy
        
        # Initialize placeholder preservation system
        self.parser = RenPyParser()
        self.logger.info("Placeholder preservation system initialized")
        
        self.is_running = False
        self.should_stop = False
        self.results = []

        # Load glossary and critical terms from config
        self.glossary = getattr(self.config, 'glossary', {}) or {}
        self.critical_terms = set(getattr(self.config, 'critical_terms', []) or [])
    
    def stop(self):
        """Stop the translation process."""
        self.should_stop = True
        self.logger.info("Translation stop requested")
    
    def run(self):
        """Run the translation process."""
        try:
            self.is_running = True
            self.should_stop = False
            
            # Run async translation
            asyncio.run(self._translate_texts())
            
        except Exception as e:
            self.logger.error(f"Translation worker error: {e}", exc_info=True)
            self.error_occurred.emit(str(e))
        finally:
            self.is_running = False
            self.finished.emit()
    
    async def _translate_texts(self):
        """Translate all texts asynchronously."""
        try:
            self.logger.info(f"Starting translation of {len(self.texts)} texts")
            
            # Configure proxy usage
            self.translation_manager.set_proxy_enabled(self.use_proxy)
            
            # Create translation requests with placeholder preservation
            requests = []
            placeholder_maps = []  # Store placeholder mappings for restoration
            
            for text_data in self.texts:
                if self.should_stop:
                    break
                
                original_text = text_data['text']
                
                # CRITICAL: Preserve placeholders before translation
                processed_text, placeholder_map = self.parser.preserve_placeholders(original_text)
                
                request = TranslationRequest(
                    text=processed_text,  # Use processed text for translation
                    source_lang=self.source_lang,
                    target_lang=self.target_lang,
                    engine=self.engine,
                    metadata={
                        'type': text_data.get('type', 'unknown'),
                        'character': text_data.get('character'),
                        'context': text_data.get('context', ''),
                        'file_path': text_data.get('file_path', ''),
                        'line_number': text_data.get('line_number', 0),
                        'original_text': original_text,  # Store original text
                        'placeholder_map': placeholder_map  # Store placeholder mapping
                    }
                )
                requests.append(request)
                placeholder_maps.append(placeholder_map)
                
                # Log placeholder preservation
                if placeholder_map:
                    self.logger.debug(f"Preserved {len(placeholder_map)} placeholders in: {original_text[:50]}...")
            
            if self.should_stop:
                self.logger.info("Translation stopped by user")
                return
            
            # Process in batches
            batch_size = self.config.translation_settings.max_batch_size
            total_requests = len(requests)
            completed = 0
            
            self.results = []
            quality_issues = []  # For simple quality report
            
            for i in range(0, len(requests), batch_size):
                if self.should_stop:
                    break
                
                batch = requests[i:i + batch_size]
                
                # Update progress
                current_text = batch[0].text if batch else ""
                self.progress_updated.emit(completed, total_requests, current_text)
                
                # Translate batch
                batch_results = await self.translation_manager.translate_batch(batch)
                
                # No OPUS-MT model download handling — OPUS-MT engine removed
                
                # CRITICAL: Restore placeholders in translated text
                for result in batch_results:
                    if result.success and result.translated_text:
                        # Get placeholder map from metadata
                        placeholder_map = result.metadata.get('placeholder_map', {})
                        original_text = result.metadata.get('original_text', result.original_text)
                        
                        if placeholder_map:
                            # Restore placeholders in translated text
                            result.translated_text = self.parser.restore_placeholders(
                                result.translated_text, placeholder_map
                            )
                            
                            # Update original text to the real original
                            result.original_text = original_text
                            
                            # Log restoration
                            self.logger.debug(f"Restored {len(placeholder_map)} placeholders in translated text")

                        # Apply glossary replacements (post-processing)
                        if self.glossary:
                            result.translated_text = self._apply_glossary(
                                result.translated_text,
                                self.glossary
                            )

                        # Check critical terms preservation; log only
                        self._check_critical_terms(result, quality_issues)
                
                self.results.extend(batch_results)
                
                completed += len(batch_results)
                
                # Update progress
                self.progress_updated.emit(completed, total_requests, "")
                
                self.logger.debug(f"Completed batch {i//batch_size + 1}, total: {completed}/{total_requests}")
            
            if not self.should_stop:
                self.logger.info(f"Translation completed: {len(self.results)} results")

                # Simple quality report (log-only for now)
                if quality_issues:
                    self.logger.warning("Quality Report: potential issues detected:")
                    for issue in quality_issues[:50]:  # limit log spam
                        self.logger.warning(issue)
                else:
                    self.logger.info("Quality Report: no critical term issues detected")
                self.translation_completed.emit(self.results)
            else:
                self.logger.info("Translation stopped")
                
        except Exception as e:
            self.logger.error(f"Error in translation process: {e}", exc_info=True)
            self.error_occurred.emit(str(e))

    def _apply_glossary(self, text: str, glossary: Dict[str, str]) -> str:
        """Apply simple glossary replacements on translated text.

        Glossary format (glossary.json):
        {
          "HP": "Can Puanı",
          "Save": "Kayıt",
          "Load": "Yükle"
        }
        """
        try:
            # Basit ve deterministik: uzun anahtarlar önce, büyük/küçük harf duyarlı
            for src, dst in sorted(glossary.items(), key=lambda x: -len(x[0])):
                if not src:
                    continue
                text = text.replace(src, dst)
        except Exception as e:
            self.logger.warning(f"Glossary application failed: {e}")
        return text

    def _check_critical_terms(self, result, quality_issues):
        """Check that critical terms are preserved; log warnings if not.

        critical_terms.json format:
        [
          "player_name",
          "HP",
          "SpecialItem42"
        ]
        """
        try:
            if not self.critical_terms:
                return
            original = result.original_text or ""
            translated = result.translated_text or ""
            for term in self.critical_terms:
                if not term:
                    continue
                in_original = term in original
                in_translated = term in translated
                if in_original and not in_translated:
                    msg = (
                        f"Critical term missing after translation: '{term}' | "
                        f"file={result.metadata.get('file_path')} line={result.metadata.get('line_number')}"
                    )
                    self.logger.warning(msg)
                    quality_issues.append(msg)
        except Exception as e:
            self.logger.warning(f"Critical term check failed: {e}")
