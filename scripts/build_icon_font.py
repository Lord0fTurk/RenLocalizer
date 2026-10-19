"""Build RenLocalizer's icon font from Lucide and regenerate Icons.qml.

The interface draws its icons with a small subset of the Lucide icon font
(ISC license), so the app needs neither QtSvg nor emoji fonts. To add an icon:

1. Download the pinned package and verify it (sizes/SHA-256 from jsDelivr):
       https://cdn.jsdelivr.net/npm/lucide-static@1.48.0/font/lucide.ttf
       https://cdn.jsdelivr.net/npm/lucide-static@1.48.0/font/codepoints.json
       https://cdn.jsdelivr.net/npm/lucide-static@1.48.0/LICENSE
   Pick names on https://lucide.dev/icons (they must exist in codepoints.json).
2. Add the name to ICONS below and run:
       python scripts/build_icon_font.py <folder with the three files>
3. Use it as Icons.<camelCaseName> in QML.

Writes src/gui/qml/fonts/RenLocalizerIcons.ttf, src/gui/qml/fonts/LUCIDE_LICENSE.txt
and src/gui/qml/components/Icons.qml.
"""
import json
import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

ICONS = """
app-window bell book-a book-open book-plus bot brain chart-column circle-check circle-x
clipboard-copy copy database download eraser file-json flag folder folder-open gamepad-2 history play
gauge globe heart info languages layout-dashboard lightbulb link lock monitor package
party-popper plus refresh-cw replace rocket rotate-ccw save scan-search search settings
shield-alert sliders-horizontal sparkles square square-pen stethoscope target terminal
trash-2 triangle-alert type undo-2 upload wrench x zap
""".split()

# JavaScript reserved words cannot be QML property names.
RESERVED = {"package": "packageBox"}
FAMILY = "RenLocalizer Icons"
REPO = Path(__file__).resolve().parents[1]


def qml_name(name: str) -> str:
    if name in RESERVED:
        return RESERVED[name]
    head, *rest = name.split("-")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def main(src: Path) -> None:
    def find(name: str) -> Path:
        for candidate in (src / name, src / "font" / name):
            if candidate.exists():
                return candidate
        raise SystemExit(f"{name} not found in {src}")

    codepoints = json.loads(find("codepoints.json").read_text(encoding="utf-8"))
    missing = [n for n in ICONS if n not in codepoints]
    if missing:
        raise SystemExit(f"Not in this Lucide version: {', '.join(missing)}")
    codes = {n: codepoints[n] for n in ICONS}

    fonts_dir = REPO / "src" / "gui" / "qml" / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    # Keep Lucide's timestamp so a rebuild produces the same bytes.
    font = TTFont(find("lucide.ttf"), recalcTimestamp=False)
    options = subset.Options()
    options.layout_features = []
    options.name_IDs = ["*"]
    options.notdef_outline = True
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=list(codes.values()))
    subsetter.subset(font)
    # Own family name, so a system-wide Lucide install cannot shadow the subset.
    for record in font["name"].names:
        if record.nameID in (1, 4, 16):
            record.string = FAMILY
        elif record.nameID == 6:
            record.string = FAMILY.replace(" ", "")
    font.save(fonts_dir / "RenLocalizerIcons.ttf")
    (fonts_dir / "LUCIDE_LICENSE.txt").write_bytes(find("LICENSE").read_bytes())

    lines = [
        "// Icons.qml — Lucide ikonları (ISC, fonts/LUCIDE_LICENSE.txt), alt küme: fonts/RenLocalizerIcons.ttf.",
        "// Bu dosya üretilir: yeni ikon için scripts/build_icon_font.py içindeki listeye adı ekleyip yeniden çalıştırın.",
        "// Kullanım: Icon { glyph: Icons.search; size: 14 } veya IconLabel { glyph: Icons.save; text: ... }",
        "pragma Singleton",
        "import QtQuick",
        "",
        "QtObject {",
        "    readonly property string family: loader.name",
        '    property FontLoader loader: FontLoader { source: Qt.resolvedUrl("../fonts/RenLocalizerIcons.ttf") }',
        "",
    ]
    for name in sorted(codes):
        escape = chr(92) + "u" + format(codes[name], "04x")  # QML string escape, e.g. 
        lines.append(f'    readonly property string {qml_name(name)}: "{escape}" // {name}')
    lines.append("}")
    (REPO / "src" / "gui" / "qml" / "components" / "Icons.qml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(codes)} icons, {(fonts_dir / 'RenLocalizerIcons.ttf').stat().st_size} bytes")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]))
