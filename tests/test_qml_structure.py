# -*- coding: utf-8 -*-
"""Main.qml is the window shell; pages, the sidebar and the dialogs are files.

The moved files still use names that live in Main.qml (root, showToast(), the
file dialogs, ...). QML resolves those through the component that instantiates
the file, and a miss only shows when the handler runs (a click), never at load.
So this test asks the running engine, from inside each file's own scope.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

QML = Path(__file__).resolve().parents[1] / "src" / "gui" / "qml"

# instance id in Main.qml -> file
MOVED = {
    "sidebarPane": "components/Sidebar.qml",
    "pageDashboard": "pages/DashboardPage.qml",
    "pageSettings": "pages/SettingsPage.qml",
    "pageLogs": "pages/LogPage.qml",
    "pageToolbox": "pages/ToolboxPage.qml",
    "pageGlossary": "pages/GlossaryPage.qml",
    "completionDialog": "dialogs/CompletionDialog.qml",
    "updateDialog": "dialogs/UpdateDialog.qml",
    "factoryResetDialog": "dialogs/FactoryResetDialog.qml",
    "factoryResetDoneDialog": "dialogs/FactoryResetDoneDialog.qml",
}
_STRING = re.compile(r'"(?:[^"\\]|\\.)*"' + r"|'(?:[^'\\]|\\.)*'")


def _code(path: Path) -> str:
    """Source without string contents and comments."""
    return "\n".join(_STRING.sub('""', line).split("//")[0]
                     for line in path.read_text(encoding="utf-8").splitlines())


def _ids(code: str) -> set:
    return set(re.findall(r"\bid:\s*([A-Za-z_]\w*)", code))


def _uses(name: str, code: str) -> bool:
    return re.search(r"(?<![\w.])%s\b" % re.escape(name), code) is not None


def test_main_qml_stays_a_shell():
    lines = len((QML / "Main.qml").read_text(encoding="utf-8").splitlines())
    assert lines < 900, f"Main.qml grew to {lines} lines; new pages and dialogs get their own file"
    for rel in MOVED.values():
        assert (QML / rel).is_file(), rel


def test_no_file_reaches_into_another_files_ids():
    """An id is visible in its own file and, through the instance hierarchy, in
    files Main.qml instantiates. An id inside one page is NOT visible in another
    page, nor in Main.qml: those need a property or alias on the page root."""
    codes = {inst: _code(QML / rel) for inst, rel in MOVED.items()}
    own = {inst: _ids(code) for inst, code in codes.items()}
    main_code = _code(QML / "Main.qml")
    problems = []
    for owner, names in own.items():
        for name in names - _ids(main_code):
            for user, code in codes.items():
                if user != owner and name not in own[user] and _uses(name, code):
                    problems.append(f"{MOVED[user]} uses id '{name}' that lives inside {MOVED[owner]}")
            if _uses(name, main_code):
                problems.append(f"Main.qml uses id '{name}' that lives inside {MOVED[owner]} "
                                f"(go through {owner}.<alias>)")
    assert not problems, "\n".join(problems)


def test_moved_files_can_reach_what_they_use_from_main_qml():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QML_DISABLE_DISK_CACHE"] = "1"
    from PyQt6.QtCore import QUrl
    from PyQt6.QtQml import QQmlApplicationEngine, QQmlExpression
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])
    from src.backend.app_backend import AppBackend
    from src.backend.editor_backend import EditorBackend

    backend = AppBackend(parent=app)
    engine = QQmlApplicationEngine(app)
    engine.rootContext().setContextProperty("appBackend", backend)
    editor_backend = EditorBackend(backend, parent=app)
    engine.rootContext().setContextProperty("editorBackend", editor_backend)
    engine.addImportPath(str(QML))
    engine.load(QUrl.fromLocalFile(str(QML / "Main.qml")))
    assert engine.rootObjects(), "Main.qml failed to load"
    root = engine.rootObjects()[0]
    root_ctx = engine.contextForObject(root)

    main_code = _code(QML / "Main.qml")
    main_names = _ids(main_code)
    main_names |= set(re.findall(r"^\s{4}function\s+([A-Za-z_]\w*)", main_code, re.M))
    main_names |= set(re.findall(r"^\s{4}property\s+\w+\s+([A-Za-z_]\w*)", main_code, re.M))
    assert {"root", "showToast", "navIndex", "fileDialog"} <= main_names

    unresolved, checked = [], 0
    for inst, rel in MOVED.items():
        code = _code(QML / rel)
        obj = QQmlExpression(root_ctx, root, inst).evaluate()[0]
        assert obj is not None, f"Main.qml has no instance with id {inst}"
        inner = engine.contextForObject(obj)
        for name in sorted(n for n in main_names - _ids(code) if _uses(n, code)):
            expr = QQmlExpression(inner, obj, f"(typeof {name}) !== 'undefined'")
            ok = expr.evaluate()[0]
            checked += 1
            if expr.hasError() or ok is not True:
                unresolved.append(f"{rel}: {name}")
    assert checked > 30, "the check found almost nothing to verify; did the layout change?"
    assert not unresolved, "Names from Main.qml that a moved file cannot reach:\n" + "\n".join(unresolved)


def test_opening_every_page_raises_nothing_in_python(monkeypatch):
    """PyQt aborts the process when a slot called from QML raises. Opening a page
    runs that page's slots (the editor refreshes its language list, the toolbox
    lists tl folders...), so a renamed or moved backend member kills the app the
    moment the user clicks the menu. The rest of the suite cannot see that."""
    import time
    import traceback

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QML_DISABLE_DISK_CACHE"] = "1"
    from PyQt6.QtCore import QUrl
    from PyQt6.QtQml import QQmlApplicationEngine, QQmlExpression
    from PyQt6.QtWidgets import QApplication

    raised = []
    monkeypatch.setattr(sys, "excepthook",
                        lambda t, v, tb: raised.append("".join(traceback.format_exception(t, v, tb))))

    app = QApplication.instance() or QApplication(sys.argv[:1])
    from src.backend.app_backend import AppBackend
    from src.backend.editor_backend import EditorBackend

    backend = AppBackend(parent=app)
    engine = QQmlApplicationEngine(app)
    engine.rootContext().setContextProperty("appBackend", backend)
    editor_backend = EditorBackend(backend, parent=app)
    engine.rootContext().setContextProperty("editorBackend", editor_backend)
    engine.addImportPath(str(QML))
    qml_errors = []
    engine.warnings.connect(lambda ws: qml_errors.extend(w.toString() for w in ws))
    engine.load(QUrl.fromLocalFile(str(QML / "Main.qml")))
    assert engine.rootObjects(), "Main.qml failed to load"
    root = engine.rootObjects()[0]
    root.show()

    def pump(seconds):
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            time.sleep(0.01)

    context = engine.contextForObject(root)
    for nav in (1, 2, 3, 4, 5, 0):
        QQmlExpression(context, root, f"root.navIndex = {nav}").evaluate()
        pump(0.35)
    for sub in (0, 1, 2):
        QQmlExpression(context, root, f"root.navIndex = 1; pageSettings.settingsSubTab = {sub}").evaluate()
        pump(0.2)
    root.hide()

    assert not raised, "A backend slot raised while a page opened:\n" + "\n".join(raised)
    script_errors = [e for e in qml_errors if "TypeError" in e or "ReferenceError" in e]
    assert not script_errors, "QML script errors while paging:\n" + "\n".join(script_errors)
