# -*- coding: utf-8 -*-
"""A minimal signal for the pipeline, so the core does not depend on Qt.

``connect`` / ``emit`` mirror the part of Qt's API the pipeline used. Callbacks
run in the thread that emits. The GUI must not be touched from the worker
thread, so it listens through ``src/backend/pipeline_worker.QtPipelineWorker``,
which re-emits each of these as a Qt signal (queued to the GUI thread). The CLI
has no such constraint and connects directly.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, List

logger = logging.getLogger(__name__)


class Signal:
    """Calls every connected callback, in connection order."""

    def __init__(self, name: str = "") -> None:
        self._name = name
        self._callbacks: List[Callable] = []
        self._lock = threading.Lock()

    def connect(self, callback: Callable) -> None:
        with self._lock:
            self._callbacks.append(callback)

    def disconnect(self, callback: Callable | None = None) -> None:
        with self._lock:
            if callback is None:
                self._callbacks.clear()
            else:
                self._callbacks = [cb for cb in self._callbacks if cb != callback]

    def emit(self, *args) -> None:
        with self._lock:
            callbacks = list(self._callbacks)
        for callback in callbacks:
            try:
                callback(*args)
            except Exception:
                # A listener that fails (a closed window, a broken progress bar)
                # must not abort the translation run.
                logger.exception("Listener of pipeline signal '%s' failed", self._name)
