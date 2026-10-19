// Icons.qml — Lucide ikonları (ISC, fonts/LUCIDE_LICENSE.txt), alt küme: fonts/RenLocalizerIcons.ttf.
// Bu dosya üretilir: yeni ikon için scripts/build_icon_font.py içindeki listeye adı ekleyip yeniden çalıştırın.
// Kullanım: Icon { glyph: Icons.search; size: 14 } veya IconLabel { glyph: Icons.save; text: ... }
pragma Singleton
import QtQuick

QtObject {
    readonly property string family: loader.name
    property FontLoader loader: FontLoader { source: Qt.resolvedUrl("../fonts/RenLocalizerIcons.ttf") }

    readonly property string appWindow: "\ue426" // app-window
    readonly property string bell: "\ue059" // bell
    readonly property string bookA: "\ue544" // book-a
    readonly property string bookOpen: "\ue05f" // book-open
    readonly property string bookPlus: "\ue3f3" // book-plus
    readonly property string bot: "\ue1bb" // bot
    readonly property string brain: "\ue3c6" // brain
    readonly property string chartColumn: "\ue2a3" // chart-column
    readonly property string circleCheck: "\ue226" // circle-check
    readonly property string circleX: "\ue084" // circle-x
    readonly property string clipboardCopy: "\ue225" // clipboard-copy
    readonly property string copy: "\ue09e" // copy
    readonly property string database: "\ue0ad" // database
    readonly property string download: "\ue0b2" // download
    readonly property string eraser: "\ue28f" // eraser
    readonly property string fileJson: "\ue36b" // file-json
    readonly property string flag: "\ue0d1" // flag
    readonly property string folder: "\ue0d7" // folder
    readonly property string folderOpen: "\ue247" // folder-open
    readonly property string gamepad2: "\ue0df" // gamepad-2
    readonly property string gauge: "\ue1bf" // gauge
    readonly property string globe: "\ue0e8" // globe
    readonly property string heart: "\ue0f2" // heart
    readonly property string history: "\ue1f5" // history
    readonly property string info: "\ue0f9" // info
    readonly property string languages: "\ue0fe" // languages
    readonly property string layoutDashboard: "\ue1c1" // layout-dashboard
    readonly property string lightbulb: "\ue1c2" // lightbulb
    readonly property string link: "\ue102" // link
    readonly property string lock: "\ue10b" // lock
    readonly property string monitor: "\ue11d" // monitor
    readonly property string packageBox: "\ue129" // package
    readonly property string partyPopper: "\ue343" // party-popper
    readonly property string play: "\ue13c" // play
    readonly property string plus: "\ue13d" // plus
    readonly property string refreshCw: "\ue145" // refresh-cw
    readonly property string replace: "\ue3db" // replace
    readonly property string rocket: "\ue286" // rocket
    readonly property string rotateCcw: "\ue148" // rotate-ccw
    readonly property string save: "\ue14d" // save
    readonly property string scanSearch: "\ue537" // scan-search
    readonly property string search: "\ue151" // search
    readonly property string settings: "\ue154" // settings
    readonly property string shieldAlert: "\ue1fe" // shield-alert
    readonly property string slidersHorizontal: "\ue29a" // sliders-horizontal
    readonly property string sparkles: "\ue412" // sparkles
    readonly property string square: "\ue167" // square
    readonly property string squarePen: "\ue172" // square-pen
    readonly property string stethoscope: "\ue2f1" // stethoscope
    readonly property string target: "\ue180" // target
    readonly property string terminal: "\ue181" // terminal
    readonly property string trash2: "\ue18e" // trash-2
    readonly property string triangleAlert: "\ue193" // triangle-alert
    readonly property string type: "\ue198" // type
    readonly property string undo2: "\ue2a1" // undo-2
    readonly property string upload: "\ue19e" // upload
    readonly property string wrench: "\ue1b1" // wrench
    readonly property string x: "\ue1b2" // x
    readonly property string zap: "\ue1b4" // zap
}
