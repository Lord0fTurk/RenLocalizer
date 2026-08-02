# -*- coding: utf-8 -*-
"""
Pipeline base types: PipelineStage, PipelineResult, PipelineWorker.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict

from PyQt6.QtCore import QThread, pyqtSignal


class PipelineStage(Enum):
    """Pipeline aşamaları"""
    IDLE = "idle"
    VALIDATING = "validating"
    UNRPA = "unrpa"
    GENERATING = "generating"
    PARSING = "parsing"
    TRANSLATING = "translating"
    SAVING = "saving"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class PipelineResult:
    """Pipeline sonucu"""
    success: bool
    message: str
    stage: PipelineStage
    stats: Optional[Dict] = None
    output_path: Optional[str] = None
    error: Optional[str] = None


class PipelineWorker(QThread):
    """Pipeline için QThread wrapper"""

    stage_changed = pyqtSignal(str, str)
    progress_updated = pyqtSignal(int, int, str)
    log_message = pyqtSignal(str, str)
    finished = pyqtSignal(object)
    show_warning = pyqtSignal(str, str)

    def __init__(self, pipeline, parent=None):
        super().__init__(parent)
        self.pipeline = pipeline

        self.pipeline.stage_changed.connect(self.stage_changed)
        self.pipeline.progress_updated.connect(self.progress_updated)
        self.pipeline.log_message.connect(self.log_message)
        self.pipeline.finished.connect(self._on_finished)
        self.pipeline.show_warning.connect(self.show_warning)

    def _on_finished(self, result):
        self.finished.emit(result)

    def run(self):
        self.pipeline.run()

    def stop(self):
        self.pipeline.stop()
