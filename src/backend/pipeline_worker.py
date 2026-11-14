# -*- coding: utf-8 -*-
"""Runs a TranslationPipeline on a QThread and turns its signals into Qt signals.

The pipeline itself is plain Python (src/core/pipeline/signals.py) and calls its
listeners in the worker thread. Re-emitting through Qt signals here is what
makes delivery to the GUI thread safe: Qt queues a signal emitted from another
thread to receivers that live in the GUI thread.
"""
from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal


class QtPipelineWorker(QThread):
    stage_changed = pyqtSignal(str, str)
    progress_updated = pyqtSignal(int, int, str)
    log_message = pyqtSignal(str, str)
    finished = pyqtSignal(object)
    show_warning = pyqtSignal(str, str)
    line_translated = pyqtSignal(str, str, str)

    def __init__(self, pipeline: Any, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.pipeline = pipeline
        pipeline.stage_changed.connect(self.stage_changed.emit)
        pipeline.progress_updated.connect(self.progress_updated.emit)
        pipeline.log_message.connect(self.log_message.emit)
        pipeline.finished.connect(self.finished.emit)
        pipeline.show_warning.connect(self.show_warning.emit)
        if hasattr(pipeline, "line_translated"):
            pipeline.line_translated.connect(self.line_translated.emit)

    def run(self) -> None:
        self.pipeline.run()

    def stop(self) -> None:
        self.pipeline.stop()
