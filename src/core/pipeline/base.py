# -*- coding: utf-8 -*-
"""
Pipeline base types: PipelineStage, PipelineResult, PipelineWorker.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any

import threading


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
    stats: Optional[Dict[str, Any]] = None
    output_path: Optional[str] = None
    error: Optional[str] = None


class PipelineWorker(threading.Thread):
    """Runs a pipeline on a background thread. No Qt: this is what the CLI uses.

    The GUI uses src/backend/pipeline_worker.QtPipelineWorker instead, which
    delivers the same signals to the GUI thread. The names below match it, so
    callers can use either.
    """

    def __init__(self, pipeline: Any, parent: Optional[Any] = None) -> None:
        super().__init__(name="pipeline-worker", daemon=True)
        self.pipeline = pipeline
        # The pipeline's own signals; listeners run in this worker thread.
        self.stage_changed = pipeline.stage_changed
        self.progress_updated = pipeline.progress_updated
        self.log_message = pipeline.log_message
        self.finished = pipeline.finished
        self.show_warning = pipeline.show_warning

    def run(self) -> None:
        self.pipeline.run()

    def stop(self) -> None:
        """Signals the underlying pipeline to abort execution."""
        self.pipeline.stop()

    def isRunning(self) -> bool:
        return self.is_alive()

    def wait(self, timeout_ms: Optional[int] = None) -> bool:
        """Join for up to ``timeout_ms``; True when the thread has finished."""
        self.join(None if timeout_ms is None else timeout_ms / 1000.0)
        return not self.is_alive()
