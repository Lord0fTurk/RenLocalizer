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


def test_qt_rgba_uses_the_zero_to_one_scale():
    """
    Qt.rgba() takes 0-1 channels. Written with 0-255 values (`Qt.rgba(245, 158,
    11, 0.08)`) the color leaves the sRGB range and renders grey-white instead
    of the intended amber, red or green tint; the sidebar logo ring came out
    #b9bbbf instead of the card color #151a29.
    """
    import glob
    import re

    qml_root = os.path.join(os.path.dirname(__file__), "..", "src", "gui", "qml")
    pattern = re.compile(r"Qt\.rgba\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,")
    offenders = []
    for path in glob.glob(os.path.join(qml_root, "**", "*.qml"), recursive=True):
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                for m in pattern.finditer(line):
                    if any(float(v) > 1 for v in m.groups()):
                        offenders.append(f"{os.path.relpath(path, qml_root)}:{lineno}: {m.group(0)}")
    assert not offenders, "Qt.rgba() with 0-255 channels:\n" + "\n".join(offenders)


def test_colors_come_from_the_theme():
    """
    Every color lives in components/Theme.qml. A hex literal or a numeric
    Qt.rgba() elsewhere is a color that themes, contrast fixes and palette
    changes will miss (the 0-255 Qt.rgba bug spread over 137 copies). Use
    Theme.<name>, or Theme.alpha(Theme.<name>, a) for a transparent tint.
    """
    import glob
    import re

    qml_root = os.path.join(os.path.dirname(__file__), "..", "src", "gui", "qml")
    hex_re = re.compile(r'"(?:#[0-9A-Fa-f]{3,8}|white|black|red|green|blue|gray|grey|yellow|cyan|magenta|orange|purple)"')
    rgba_re = re.compile(r"Qt\.rgba\(\s*[\d.]")
    offenders = []
    for path in glob.glob(os.path.join(qml_root, "**", "*.qml"), recursive=True):
        if os.path.basename(path) == "Theme.qml":
            continue
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                code = line.split("//", 1)[0]
                if hex_re.search(code) or rgba_re.search(code):
                    offenders.append(f"{os.path.relpath(path, qml_root)}:{lineno}: {line.strip()[:120]}")
    assert not offenders, "Colors outside Theme.qml:\n" + "\n".join(offenders)


def test_font_sizes_follow_the_type_scale():
    """
    Text sizes come from one scale (documented at the top of Theme.qml).
    Off-scale sizes (9, 15, 17, 22 ...) made sibling titles differ by a pixel
    or two and the hierarchy blur.
    """
    import glob
    import re

    scale = {10, 11, 12, 13, 14, 16, 18, 20, 24, 36}
    qml_root = os.path.join(os.path.dirname(__file__), "..", "src", "gui", "qml")
    pattern = re.compile(r"pixelSize:\s*(\d+)\b")
    offenders = []
    for path in glob.glob(os.path.join(qml_root, "**", "*.qml"), recursive=True):
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                for m in pattern.finditer(line):
                    if int(m.group(1)) not in scale:
                        offenders.append(f"{os.path.relpath(path, qml_root)}:{lineno}: {m.group(0)}")
    assert not offenders, f"Font sizes off the scale {sorted(scale)}:\n" + "\n".join(offenders)


def test_pages_use_the_shared_page_header():
    """
    Every page starts with components/PageHeader.qml, so titles share one size,
    icon tile, spacing and alignment with the content. 24 px is the page-title
    size: a 24 px text elsewhere is a hand-made header (there were four styles).
    """
    import glob
    import re

    qml_root = os.path.join(os.path.dirname(__file__), "..", "src", "gui", "qml")
    with open(os.path.join(qml_root, "Main.qml"), encoding="utf-8") as fh:
        main = fh.read()
    with open(os.path.join(qml_root, "components", "EditorPage.qml"), encoding="utf-8") as fh:
        editor = fh.read()
    # Dashboard, Settings, Logs, Toolbox, Glossary + the editor page
    assert len(re.findall(r"^\s*PageHeader \{", main, re.M)) == 5
    assert len(re.findall(r"^\s*PageHeader \{", editor, re.M)) == 1

    offenders = []
    for path in glob.glob(os.path.join(qml_root, "**", "*.qml"), recursive=True):
        if os.path.basename(path) == "PageHeader.qml":
            continue
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if re.search(r"pixelSize:\s*24\b", line):
                    offenders.append(f"{os.path.relpath(path, qml_root)}:{lineno}")
    assert not offenders, "Page-title size outside PageHeader:\n" + "\n".join(offenders)
