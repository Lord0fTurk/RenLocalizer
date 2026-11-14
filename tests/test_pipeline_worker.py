# -*- coding: utf-8 -*-
"""Pipeline workers: the Qt-free one (CLI) and the Qt bridge (GUI)."""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from src.core.pipeline.base import PipelineResult, PipelineStage, PipelineWorker
from src.core.pipeline.signals import Signal

ROOT = Path(__file__).resolve().parents[1]


class DummyPipeline:
    """Same surface as TranslationPipeline: five signals, run(), stop()."""

    def __init__(self):
        self.stage_changed = Signal("stage_changed")
        self.progress_updated = Signal("progress_updated")
        self.log_message = Signal("log_message")
        self.finished = Signal("finished")
        self.show_warning = Signal("show_warning")
        self.should_stop = False
        self.ran = False
        self.run_thread = None

    def run(self):
        self.ran = True
        self.run_thread = threading.get_ident()
        self.stage_changed.emit("parsing", "Extracting strings")
        self.progress_updated.emit(50, 100, "Halfway")
        self.log_message.emit("info", "Processing...")
        self.show_warning.emit("Warning", "Check this")
        while not self.should_stop:
            time.sleep(0.01)
        self.finished.emit(PipelineResult(success=True, message="Stopped cleanly", stage=PipelineStage.SAVING))

    def stop(self):
        self.should_stop = True


def _collect(worker):
    seen = {"stages": [], "progress": [], "logs": [], "warnings": [], "results": [], "threads": set()}

    def record(key):
        def handler(*args):
            seen[key].append(args if len(args) > 1 else args[0])
            seen["threads"].add(threading.get_ident())
        return handler

    worker.stage_changed.connect(record("stages"))
    worker.progress_updated.connect(record("progress"))
    worker.log_message.connect(record("logs"))
    worker.show_warning.connect(record("warnings"))
    worker.finished.connect(record("results"))
    return seen


def _assert_delivered(seen):
    assert seen["stages"] == [("parsing", "Extracting strings")]
    assert seen["progress"] == [(50, 100, "Halfway")]
    assert seen["logs"] == [("info", "Processing...")]
    assert seen["warnings"] == [("Warning", "Check this")]
    assert len(seen["results"]) == 1 and seen["results"][0].success


# ── plain signal ─────────────────────────────────────────────────────────────

def test_signal_calls_listeners_in_order_and_survives_a_failing_one():
    signal, calls = Signal("x"), []
    signal.connect(lambda v: calls.append(("a", v)))
    signal.connect(lambda v: 1 / 0)                    # a broken listener
    signal.connect(lambda v: calls.append(("b", v)))
    signal.emit(7)
    assert calls == [("a", 7), ("b", 7)]               # the run goes on

    first = lambda v: calls.append(("c", v))           # noqa: E731
    signal.disconnect()
    signal.connect(first)
    signal.disconnect(first)
    signal.emit(8)
    assert calls == [("a", 7), ("b", 7)]


# ── Qt-free worker (CLI) ─────────────────────────────────────────────────────

def test_plain_worker_runs_stops_and_reports():
    pipeline = DummyPipeline()
    worker = PipelineWorker(pipeline)
    seen = _collect(worker)
    worker.start()
    deadline = time.time() + 3
    while not seen["warnings"] and time.time() < deadline:
        time.sleep(0.01)
    assert worker.isRunning() and pipeline.ran
    assert not worker.wait(50)                          # still running: wait() says so
    worker.stop()
    assert worker.wait(3000)
    assert not worker.isRunning()
    _assert_delivered(seen)
    assert seen["threads"] == {pipeline.run_thread}     # listeners run in the worker thread


def test_core_and_cli_import_without_pyqt6():
    """The translation core and the CLI must not need Qt at all."""
    code = (
        "import sys\n"
        "class Block:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'PyQt6' or name.startswith('PyQt6.'):\n"
        "            raise ImportError('PyQt6 is blocked in this test')\n"
        "sys.meta_path.insert(0, Block())\n"
        "import src.core.pipeline, src.core.translation_pipeline, src.cli_main\n"
        "from src.core.pipeline import TranslationPipeline, PipelineWorker\n"
        "print('ok', sorted(m for m in sys.modules if m.startswith('PyQt6')))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().endswith("ok []"), out.stdout


# ── Qt bridge (GUI) ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtCore import QCoreApplication

    yield QCoreApplication.instance() or QCoreApplication([])


def test_qt_worker_delivers_pipeline_signals_on_the_gui_thread(qapp):
    """The pipeline emits in the worker thread; the GUI must hear it in its own.

    Touching QML from the worker thread crashes, so this is the contract the
    bridge exists for.
    """
    from PyQt6.QtCore import QObject, pyqtSlot

    from src.backend.pipeline_worker import QtPipelineWorker

    main_thread = threading.get_ident()
    seen = {"stages": [], "progress": [], "logs": [], "warnings": [], "results": [], "threads": set()}

    class Receiver(QObject):  # lives in the GUI thread, like AppBackend
        def _note(self, key, value):
            seen[key].append(value)
            seen["threads"].add(threading.get_ident())

        @pyqtSlot(str, str)
        def on_stage(self, a, b):
            self._note("stages", (a, b))

        @pyqtSlot(int, int, str)
        def on_progress(self, a, b, c):
            self._note("progress", (a, b, c))

        @pyqtSlot(str, str)
        def on_log(self, a, b):
            self._note("logs", (a, b))

        @pyqtSlot(str, str)
        def on_warning(self, a, b):
            self._note("warnings", (a, b))

        @pyqtSlot(object)
        def on_finished(self, result):
            self._note("results", result)

    receiver = Receiver()
    pipeline = DummyPipeline()
    worker = QtPipelineWorker(pipeline)
    worker.stage_changed.connect(receiver.on_stage)
    worker.progress_updated.connect(receiver.on_progress)
    worker.log_message.connect(receiver.on_log)
    worker.show_warning.connect(receiver.on_warning)
    worker.finished.connect(receiver.on_finished)

    worker.start()
    deadline = time.time() + 3
    while not seen["warnings"] and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert worker.isRunning() and pipeline.ran
    worker.stop()
    deadline = time.time() + 3
    while not seen["results"] and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert worker.wait(3000)

    _assert_delivered(seen)
    assert pipeline.run_thread != main_thread           # the work ran elsewhere
    assert seen["threads"] == {main_thread}             # every listener ran on the GUI thread
