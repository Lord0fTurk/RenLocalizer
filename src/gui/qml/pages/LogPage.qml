// Log console: level filter, search, auto-scroll.
// Moved out of Main.qml unchanged. Names that are not defined in this file
// (root, showToast(), navIndex, the file dialogs, ...) belong to Main.qml and
// resolve through the component that instantiates this one.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs
import QtQuick.Window
import "../components"

Item {
    id: pageLogs
    // Used by Main.qml (backend signal handlers, file dialogs, drag & drop).
    property alias logConsoleListView: logConsoleListView
    visible: navIndex === 2
    Layout.fillWidth: true
    Layout.fillHeight: true

    property string selectedLevel: "ALL"
    property string logSearchQuery: ""

    transform: Translate { id: animTrLogs; y: 14 }
    opacity: 0.0
    ParallelAnimation {
        id: animEntranceLogs
        NumberAnimation { target: animTrLogs; property: "y"; from: 14; to: 0; duration: 220; easing.type: Easing.OutCubic }
        NumberAnimation { target: pageLogs; property: "opacity"; from: 0.0; to: 1.0; duration: 180; easing.type: Easing.OutQuad }
    }
    onVisibleChanged: if (visible) animEntranceLogs.restart()

    // Sabit Sticky Terminal Araç Çubuğu
    PageHeader {
        id: logStickyHeader
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        maxContentWidth: 100000 // çalışma sayfası: tam genişlik
        glyph: Icons.terminal
        title: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_logs", "Log Console & System Diagnostics")
        subtitle: appBackend.uiTrigger, logModel.count + " " + appBackend.getTextWithDefault("logs_count_label", "events recorded in session.")
        actions: [
            Button {
                height: 34; text: appBackend.uiTrigger, appBackend.getTextWithDefault("copy_log", "Copy Log")
                onClicked: {
                    var lines = []
                    for (var i = 0; i < logModel.count; i++) {
                        var item = logModel.get(i)
                        lines.push(item.ts + " [" + item.level.toUpperCase() + "] " + item.message)
                    }
                    appBackend.copyToClipboard(lines.join("\n"))
                    showToast(appBackend.getTextWithDefault("log_copied_clipboard", "Log copied to clipboard!"), "info")
                }
                background: Rectangle { radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input; border.color: Theme.cardBorder; border.width: 1 }
                contentItem: IconLabel { glyph: Icons.copy; text: parent.text; color: Theme.txt; font.pixelSize: 11; font.bold: true }
            },
            Button {
                height: 34; text: appBackend.uiTrigger, appBackend.getTextWithDefault("clear_log", "Clear")
                onClicked: logModel.clear()
                background: Rectangle { radius: 8; color: parent.hovered ? Theme.dangerTint : Theme.input; border.color: Theme.cardBorder; border.width: 1 }
                contentItem: IconLabel { glyph: Icons.trash2; text: parent.text; color: Theme.error; font.pixelSize: 11; font.bold: true }
            }
        ]

        // Alt Satır: Seviye Filtreleri (Segments) + Canlı Arama
        RowLayout {
            Layout.fillWidth: true; spacing: 12

            // Segmented Level Filter Bar
            Rectangle {
                height: 32; radius: 8
                color: Theme.card; border.color: Theme.cardBorder; border.width: 1
                Layout.preferredWidth: filterRow.implicitWidth + 8

                RowLayout {
                    id: filterRow
                    anchors.centerIn: parent
                    spacing: 4

                    Repeater {
                        model: [
                            { label: "All", tag: "editor_status_all", key: "ALL", color: Theme.txt },
                            { label: "INFO", tag: "log_tag_info", key: "INFO", color: Theme.txt2 },
                            { label: "WARN", tag: "log_tag_warn", key: "WARNING", color: Theme.warn },
                            { label: "ERROR", tag: "log_tag_error", key: "ERROR", color: Theme.error }
                        ]
                        delegate: Rectangle {
                            width: Math.max(60, levelLabel.implicitWidth + 20); height: 26; radius: 6
                            color: pageLogs.selectedLevel === modelData.key ? Theme.alpha(modelData.color, 0.18) : "transparent"
                            border.color: pageLogs.selectedLevel === modelData.key ? modelData.color : "transparent"; border.width: 1
                            Label {
                                id: levelLabel
                                anchors.centerIn: parent
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault(modelData.tag, modelData.label).replace("[", "").replace("]", "")
                                font.pixelSize: 10; font.bold: pageLogs.selectedLevel === modelData.key
                                color: pageLogs.selectedLevel === modelData.key ? modelData.color : Theme.txt2
                            }
                            MouseArea {
                                anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                onClicked: pageLogs.selectedLevel = modelData.key
                            }
                        }
                    }
                }
            }

            // Canlı Arama Kutusu
            Rectangle {
                Layout.fillWidth: true; height: 32; radius: 8
                color: Theme.input; border.color: Theme.cardBorder; border.width: 1
                RowLayout {
                    anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 10; spacing: 6
                    Icon { glyph: Icons.search; size: 13; color: Theme.txtDim }
                    TextInput {
                        id: logSearchInput
                        Layout.fillWidth: true
                        font.pixelSize: 11; color: Theme.txt
                        clip: true
                        Text {
                            anchors.fill: parent
                            verticalAlignment: Text.AlignVCenter
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("logs_search_placeholder", "Loglarda filtrele veya anahtar kelime ara...")
                            color: Theme.txtDim; font.pixelSize: 11
                            visible: !logSearchInput.text && !logSearchInput.activeFocus
                        }
                        onTextChanged: pageLogs.logSearchQuery = text.trim().toLowerCase()
                    }
                    Button {
                        visible: logSearchInput.text.length > 0
                        width: 18; height: 18; text: "✕"
                        onClicked: { logSearchInput.text = ""; pageLogs.logSearchQuery = "" }
                        background: Item {}
                        contentItem: Label { text: "✕"; color: Theme.txtDim; font.pixelSize: 10; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    }
                }
            }
        }
    }

    // Konsol Çıktı Terminali (Doğrudan ListView — Nested Scroll Yok!)
    Rectangle {
        anchors.top: logStickyHeader.bottom
        anchors.bottom: parent.bottom
        anchors.horizontalCenter: parent.horizontalCenter
        width: logStickyHeader.contentWidth
        anchors.topMargin: 16; anchors.bottomMargin: 24
        radius: 12
        color: Qt.darker(Theme.card, 1.25)
        border.color: Theme.cardBorder
        border.width: 1

        ListView {
            id: logConsoleListView
            anchors.fill: parent
            anchors.margins: 12
            clip: true
            model: logModel
            spacing: 4
            ScrollBar.vertical: ScrollBar {}

            // Otomatik aşağı kaydırma
            onCountChanged: {
                if (logConsoleListView.atYEnd || logModel.count < 10) {
                    logConsoleListView.positionViewAtEnd()
                }
            }

            delegate: Item {
                id: logItemDelegate
                property bool matchesLevel: pageLogs.selectedLevel === "ALL" || (model.level || "").toUpperCase() === pageLogs.selectedLevel
                property bool matchesSearch: pageLogs.logSearchQuery.length === 0 || (model.message || "").toLowerCase().indexOf(pageLogs.logSearchQuery) !== -1
                property bool isVisibleInFilter: matchesLevel && matchesSearch

                visible: isVisibleInFilter
                width: logConsoleListView.width
                height: isVisibleInFilter ? logRowLayout.implicitHeight + 4 : 0

                RowLayout {
                    id: logRowLayout
                    anchors.fill: parent
                    spacing: 10

                    Label {
                        text: model.ts || ""
                        color: Theme.txtDim; font.pixelSize: 11; font.family: "Consolas, 'Courier New', monospace"
                        Layout.preferredWidth: 65
                    }
                    Label {
                        text: logPrefix(model.level)
                        color: logColor(model.level)
                        font.bold: true; font.pixelSize: 11; font.family: "Consolas, 'Courier New', monospace"
                        Layout.preferredWidth: 55
                    }
                    Label {
                        text: model.message || ""
                        color: logColor(model.level)
                        font.pixelSize: 11; font.family: "Consolas, 'Courier New', monospace"
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                    }
                }
            }
        }
    }
}
