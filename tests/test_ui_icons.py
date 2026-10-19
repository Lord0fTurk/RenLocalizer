# -*- coding: utf-8 -*-
"""
The interface draws its icons with a Lucide subset font (components/Icons.qml,
fonts/RenLocalizerIcons.ttf), not with emoji: emoji look different on every OS,
need an emoji font on Linux, and doubled up when a locale string and the QML
both added one. These tests keep the icon set consistent.
"""
import glob
import json
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..")
QML_ROOT = os.path.join(ROOT, "src", "gui", "qml")
ICONS_QML = os.path.join(QML_ROOT, "components", "Icons.qml")
ICON_FONT = os.path.join(QML_ROOT, "fonts", "RenLocalizerIcons.ttf")

ICON_DEF_RE = re.compile(r'readonly property string (\w+): "\x5cu([0-9a-f]{4})"')  # x5c: the backslash of the QML escape
# Pictographs, and symbols written with the emoji variation selector (⚠️, ✏️ ...)
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF]|[\u2600-\u27BF]\uFE0F")


def _qml_files():
    return glob.glob(os.path.join(QML_ROOT, "**", "*.qml"), recursive=True)


def _icon_defs():
    with open(ICONS_QML, encoding="utf-8") as fh:
        return {name: int(code, 16) for name, code in ICON_DEF_RE.findall(fh.read())}


def test_every_icon_used_in_qml_is_defined():
    """A misspelled Icons.<name> is undefined in QML and draws nothing, silently."""
    defined = set(_icon_defs()) | {"family", "loader"}
    missing = []
    for path in _qml_files():
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                for name in re.findall(r"\bIcons\.(\w+)", line.split("//", 1)[0]):
                    if name not in defined:
                        missing.append(f"{os.path.relpath(path, QML_ROOT)}:{lineno}: Icons.{name}")
    assert not missing, "Unknown icons (add them in scripts/build_icon_font.py):\n" + "\n".join(missing)


def test_icon_font_contains_every_icon():
    from fontTools.ttLib import TTFont

    font = TTFont(ICON_FONT)
    cmap = font.getBestCmap()
    absent = [name for name, code in _icon_defs().items() if code not in cmap]
    assert not absent, f"Icons.qml codes missing from the font: {absent}"
    assert font["name"].getDebugName(1) == "RenLocalizer Icons"
    assert os.path.exists(os.path.join(QML_ROOT, "fonts", "LUCIDE_LICENSE.txt"))


# Log routing in Main.qml reads the emoji the backend puts in front of its
# messages; those are message content, not interface icons.
EMOJI_ALLOWED = ("message.indexOf(", "message.replace(", '"📊 " + appBackend.getTextWithDefault("original_text"')


def test_qml_draws_icons_not_emoji():
    offenders = []
    for path in _qml_files():
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                code = line.split("//", 1)[0]
                if EMOJI_RE.search(code) and not any(a in code for a in EMOJI_ALLOWED):
                    offenders.append(f"{os.path.relpath(path, QML_ROOT)}:{lineno}: {line.strip()[:110]}")
    assert not offenders, "Emoji in QML (use Icon / IconLabel with Icons.<name>):\n" + "\n".join(offenders)


# Keys the backend also writes into the log keep their emoji; the QML strips it
# (stripLeadingEmoji) before showing them.
LOCALE_EMOJI_ALLOWED = {
    "log_select_game", "update_available_title", "stage_completed", "stage_error", "stage_generating",
    "stage_parsing", "stage_saving", "stage_translating", "stage_unren", "stage_validating", "hy_mt2_detected",
}


def test_interface_strings_do_not_start_with_emoji():
    used = set()
    for path in _qml_files():
        with open(path, encoding="utf-8") as fh:
            used |= set(re.findall(r'(?:getTextWithDefault|page\.t)\(\s*"([\w.]+)"', fh.read()))
    lead = re.compile(r"^\s*(?:[\U0001F300-\U0001FAFF]|[\u2600-\u27BF])")
    offenders = []
    for path in sorted(glob.glob(os.path.join(ROOT, "locales", "*.json"))):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        for key in sorted(used - LOCALE_EMOJI_ALLOWED):
            value = data.get(key)
            if isinstance(value, str) and lead.match(value):
                offenders.append(f"{os.path.basename(path)}: {key} = {value[:40]!r}")
    assert not offenders, "Interface strings that start with an emoji (the QML draws the icon):\n" + "\n".join(offenders)
