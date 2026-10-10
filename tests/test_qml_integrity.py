# -*- coding: utf-8 -*-
"""
Test to ensure Main.qml and all QML components load without syntax or binding errors.
"""
import os
import sys
import pytest
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication
from PyQt6.QtQml import QQmlApplicationEngine


def test_qml_loads_cleanly():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QML_DISABLE_DISK_CACHE"] = "1"

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv[:1])

    from src.backend.app_backend import AppBackend
    backend = AppBackend(parent=app)

    engine = QQmlApplicationEngine(app)
    engine.rootContext().setContextProperty("appBackend", backend)
    from src.backend.editor_backend import EditorBackend
    # Parented so Python keeps it alive; an unowned object is collected at once
    # and the editor page would bind against null.
    editor_backend = EditorBackend(backend, parent=app)
    engine.rootContext().setContextProperty("editorBackend", editor_backend)

    qml_root = os.path.abspath("src/gui/qml")
    engine.addImportPath(qml_root)
    qml_path = os.path.join(qml_root, "Main.qml")

    errors = []
    def on_warnings(warnings):
        for w in warnings:
            errors.append(w.toString())

    engine.warnings.connect(on_warnings)
    engine.load(QUrl.fromLocalFile(qml_path))

    assert len(engine.rootObjects()) > 0, f"QML failed to load: {errors}"
    script_errors = [e for e in errors if "TypeError" in e or "ReferenceError" in e]
    assert not script_errors, "QML script errors:\n" + "\n".join(script_errors)


def test_no_helper_receives_ui_trigger_as_argument():
    """
    `appBackend.uiTrigger` is a bool used only to re-evaluate bindings via the
    comma operator (`text: appBackend.uiTrigger, helper(...)`). Passing it as a
    function argument (`helper(appBackend.uiTrigger, ...)`) hands `true` to string
    helpers such as cleanModalTitle/cleanTitle and raises
    "TypeError: Property 'replace' of object true is not a function" at runtime.
    """
    import glob
    import re

    qml_root = os.path.join(os.path.dirname(__file__), "..", "src", "gui", "qml")
    offenders = []
    pattern = re.compile(r"\b([A-Za-z_][\w.]*)\(\s*appBackend\.uiTrigger\s*,")
    for path in glob.glob(os.path.join(qml_root, "**", "*.qml"), recursive=True):
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                for m in pattern.finditer(line):
                    # `(appBackend.uiTrigger, x)` grouping has no callee name before "("
                    if m.group(1):
                        offenders.append(f"{os.path.relpath(path, qml_root)}:{lineno}: {line.strip()[:120]}")
    assert not offenders, "uiTrigger passed as a function argument:\n" + "\n".join(offenders)


def test_hy_mt_prompt_warning_is_gated_like_the_control_it_points_at():
    """
    The "set Model Profile to 'generic'" warning must only appear where that
    selector exists. hyMt2Active is derived from the model NAME alone, so with
    e.g. Google selected it can be true while the Hy-MT profile card
    (visible: selectedEngine === "local_llm") is hidden — sending the user to
    a setting they cannot see.
    """
    import re

    qml = os.path.join(os.path.dirname(__file__), "..", "src", "gui", "qml", "Main.qml")
    with open(qml, encoding="utf-8") as fh:
        content = fh.read()

    # The profile selector's own gate, for reference.
    assert 'visible: appBackend.selectedEngine === "local_llm"' in content

    index = content.find("ai_prompt_ignored_hy_mt2")
    assert index != -1, "prompt-ignored warning key missing from Main.qml"
    block = content[max(0, index - 900):index]
    visible_lines = re.findall(r"visible: ([^\n]+)", block)
    assert visible_lines, "warning label has no visible binding"
    gate = visible_lines[-1]
    assert "hyMt2Active" in gate and 'selectedEngine === "local_llm"' in gate, gate
