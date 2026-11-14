// Shown when a run finishes: playable rate, breakdown badges, output paths.
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

Dialog {
    id: completionDialog
    anchors.centerIn: parent
    width: Math.min(600, root.width * 0.90)
    padding: 0
    header: null
    footer: null
    modal: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    standardButtons: Dialog.NoButton

    property string summaryText: ""
    property string outputPath: ""
    property string diagPath: ""

    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0.0; to: 1.0; duration: 200; easing.type: Easing.OutCubic }
        NumberAnimation { property: "scale"; from: 0.92; to: 1.0; duration: 240; easing.type: Easing.OutBack; easing.overshoot: 1.3 }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; from: 1.0; to: 0.0; duration: 150; easing.type: Easing.InQuad }
        NumberAnimation { property: "scale"; from: 1.0; to: 0.94; duration: 150; easing.type: Easing.InQuad }
    }

    Overlay.modal: Rectangle {
        color: Theme.alpha(Theme.black, 0.65)
    }

    background: Rectangle {
        color: Theme.card
        radius: 10
        border.color: Theme.borderControl
        border.width: 1
        clip: true

        // Üst kısımdaki hafif neon gradyan vurgusu
    }

    contentItem: ColumnLayout {
        spacing: 18

        // 1. Üst Başlık ve Rozet
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 22
            Layout.rightMargin: 20
            Layout.topMargin: 20
            spacing: 14

            Rectangle {
                width: 42; height: 42; radius: 21
                color: Theme.successDim
                border.color: Theme.success; border.width: 1.5

                Icon {
                    anchors.centerIn: parent
                    glyph: Icons.partyPopper
                    size: 20
                    color: Theme.success
                }
            }

            ColumnLayout {
                spacing: 3
                Layout.fillWidth: true

                Label {
                    text: appBackend.uiTrigger, cleanModalTitle(appBackend.getTextWithDefault("completion_summary_title", "Çeviri ve Derleme Tamamlandı"))
                    font.pixelSize: 18; font.bold: true; color: Theme.txt
                }
                Label {
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("completion_summary_subtitle", "Oyun yerelleştirme dosyaları başarıyla üretildi.")
                    font.pixelSize: 12; color: Theme.txt2
                }
            }

            Item { Layout.fillWidth: true }
            // Sağ üst kapatma '✕' butonu
            Rectangle {
                width: 32; height: 32; radius: 16
                color: closeCompletionMa.containsMouse ? Theme.alpha(Theme.white, 0.12) : "transparent"
                scale: closeCompletionMa.pressed ? 0.92 : (closeCompletionMa.containsMouse ? 1.08 : 1.0)
                Behavior on scale { NumberAnimation { duration: 120 } }
                Behavior on color { ColorAnimation { duration: 120 } }

                Label {
                    anchors.centerIn: parent
                    text: "✕"
                    color: closeCompletionMa.containsMouse ? Theme.white : Theme.txtDim
                    font.pixelSize: 13
                    font.bold: true
                }
                MouseArea {
                    id: closeCompletionMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: completionDialog.close()
                }
            }
        }

        // 2. Özet Bilgi Kartı
        Rectangle {
            Layout.fillWidth: true
            Layout.leftMargin: 22
            Layout.rightMargin: 22
            Layout.preferredHeight: summaryCol.implicitHeight + 24
            radius: 12
            color: Theme.input
            border.color: Theme.borderControl
            border.width: 1

            ColumnLayout {
                id: summaryCol
                anchors.fill: parent
                anchors.margins: 14
                spacing: 10

                // Rich stats bindings (v2.8.21)
                readonly property var st: appBackend.completionStats
                readonly property bool hasStats: !!(st && st.total > 0)
                readonly property real playPct: hasStats ? (st.playable_pct !== undefined ? st.playable_pct : 100.0) : 100.0
                readonly property int totalCnt: hasStats ? (st.total || 0) : 0
                readonly property int transCnt: hasStats ? (st.translated || 0) : 0
                readonly property int sameCnt: hasStats ? (st.same_as_source || 0) : 0
                readonly property int pendCnt: hasStats ? (st.pending || 0) : 0

                // 2a. Oynanabilirlik Başlığı & Çubuğu
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    visible: summaryCol.hasStats

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        Icon {
                            glyph: Icons.gamepad2
                            size: 16
                            color: summaryCol.playPct >= 98.0 ? Theme.success : (summaryCol.playPct >= 90.0 ? Theme.accent : Theme.warn)
                        }

                        Label {
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("completion_playable_rate", "Playable: {pct}% Ready").replace("{pct}", summaryCol.playPct.toFixed(1))
                            font.pixelSize: 13
                            font.bold: true
                            color: summaryCol.playPct >= 98.0 ? Theme.success : (summaryCol.playPct >= 90.0 ? Theme.accent : Theme.warn)
                        }

                        Item { Layout.fillWidth: true }

                        Label {
                            text: appBackend.uiTrigger, (summaryCol.st && summaryCol.st.saved_count ? appBackend.getTextWithDefault("completion_saved_files", "{count} files updated").replace("{count}", summaryCol.st.saved_count) : "")
                            font.pixelSize: 11
                            color: Theme.txtDim
                            visible: !!(summaryCol.st && summaryCol.st.saved_count)
                        }
                    }

                    // Mini dolum çizgisi
                    Rectangle {
                        Layout.fillWidth: true
                        height: 5
                        radius: 2.5
                        color: Theme.inputDeep

                        Rectangle {
                            width: Math.max(6, Math.min(parent.width, parent.width * (summaryCol.playPct / 100.0)))
                            height: parent.height
                            radius: 2.5
                            gradient: Gradient {
                                orientation: Gradient.Horizontal
                                GradientStop { position: 0.0; color: Theme.accent }
                                GradientStop { position: 1.0; color: summaryCol.playPct >= 98.0 ? Theme.success : Theme.accent }
                            }
                        }
                    }
                }

                // 2b. 3'lü İstatistik Rozetleri (Badge Grid)
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    visible: summaryCol.hasStats

                    // Kart 1: Çevrilen
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 64
                        radius: 8
                        color: Theme.statusSuccessSubtle
                        border.color: Theme.statusSuccessBorder
                        border.width: 1

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 8
                            spacing: 2

                            RowLayout {
                                spacing: 4
                                Icon { glyph: Icons.circleCheck; size: 12; color: Theme.success }
                                Label {
                                    text: summaryCol.transCnt.toLocaleString()
                                    font.bold: true; font.pixelSize: 16; color: Theme.txt
                                }
                                Item { Layout.fillWidth: true }
                                Label {
                                    text: summaryCol.totalCnt > 0 ? ((summaryCol.transCnt / summaryCol.totalCnt) * 100).toFixed(1) + "%" : ""
                                    font.pixelSize: 11; font.bold: true; color: Theme.success
                                }
                            }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("completion_badge_translated", "Translated Texts")
                                font.pixelSize: 11; color: Theme.txt2; elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                        }
                    }

                    // Kart 2: Orijinal Korunan (İsimler, Sesler)
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 64
                        radius: 8
                        color: Theme.cardHover
                        border.color: Theme.borderControl
                        border.width: 1

                        ToolTip.visible: sameCardMa.containsMouse
                        ToolTip.text: appBackend.uiTrigger, appBackend.getTextWithDefault("completion_tooltip_identical", "Character names, sound effects, and symbols that naturally stay identical.")
                        ToolTip.delay: 300

                        MouseArea {
                            id: sameCardMa
                            anchors.fill: parent
                            hoverEnabled: true
                        }

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 8
                            spacing: 2

                            RowLayout {
                                spacing: 4
                                Icon { glyph: Icons.languages; size: 12; color: Theme.accent }
                                Label {
                                    text: summaryCol.sameCnt.toLocaleString()
                                    font.bold: true; font.pixelSize: 16; color: Theme.txt
                                }
                                Item { Layout.fillWidth: true }
                                Label {
                                    text: summaryCol.totalCnt > 0 ? ((summaryCol.sameCnt / summaryCol.totalCnt) * 100).toFixed(1) + "%" : ""
                                    font.pixelSize: 11; font.bold: true; color: Theme.accent
                                }
                            }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("completion_badge_identical", "Kept as Original")
                                font.pixelSize: 11; color: Theme.txt2; elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                        }
                    }

                    // Kart 3: Güvenlik Koruması / Bekleyen
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 64
                        radius: 8
                        color: summaryCol.pendCnt > 0 ? Theme.statusWarningSubtle : Theme.surfaceControl
                        border.color: summaryCol.pendCnt > 0 ? Theme.statusWarningBorder : Theme.borderControl
                        border.width: 1

                        ToolTip.visible: pendCardMa.containsMouse
                        ToolTip.text: appBackend.uiTrigger, appBackend.getTextWithDefault("completion_tooltip_protected", "Lines preserved to avoid syntax errors.")
                        ToolTip.delay: 300

                        MouseArea {
                            id: pendCardMa
                            anchors.fill: parent
                            hoverEnabled: true
                        }

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 8
                            spacing: 2

                            RowLayout {
                                spacing: 4
                                Icon {
                                    glyph: summaryCol.pendCnt > 0 ? Icons.shieldAlert : Icons.circleCheck
                                    size: 12
                                    color: summaryCol.pendCnt > 0 ? Theme.warn : Theme.txtDim
                                }
                                Label {
                                    text: summaryCol.pendCnt.toLocaleString()
                                    font.bold: true; font.pixelSize: 16
                                    color: summaryCol.pendCnt > 0 ? Theme.warn : Theme.txtDim
                                }
                                Item { Layout.fillWidth: true }
                                Label {
                                    text: summaryCol.pendCnt === 0 ? "✓" : ""
                                    font.pixelSize: 11; font.bold: true
                                    color: Theme.success
                                }
                            }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("completion_badge_protected", "Safety Guard")
                                font.pixelSize: 11; color: Theme.txt2; elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                        }
                    }
                }

                // 2c. Geriye Uyumluluk Fallback (Eğer stats yoksa)
                RowLayout {
                    spacing: 10
                    Layout.fillWidth: true
                    visible: !summaryCol.hasStats

                    Rectangle {
                        width: 26; height: 26; radius: 6
                        color: Theme.alpha(Theme.accent, 0.12)
                        Layout.alignment: Qt.AlignTop
                        Icon {
                            anchors.centerIn: parent
                            glyph: Icons.chartColumn
                            size: 14
                            color: Theme.accent
                        }
                    }

                    Label {
                        text: completionDialog.summaryText
                        color: Theme.txt
                        font.pixelSize: 13
                        font.weight: Font.Medium
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                        lineHeight: 1.35
                    }
                }

                // Çıktı klasör yolu (varsa)
                Rectangle {
                    Layout.fillWidth: true
                    height: 32
                    radius: 7
                    color: Theme.inputDeep
                    border.color: Theme.alpha(Theme.white, 0.06)
                    border.width: 1
                    visible: completionDialog.outputPath.length > 0

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 10
                        anchors.rightMargin: 10
                        spacing: 8

                        Icon {
                            glyph: Icons.folder
                            size: 14
                            color: Theme.txt2
                        }
                        Label {
                            text: completionDialog.outputPath
                            color: Theme.txtDim
                            font.pixelSize: 11
                            font.family: "Consolas"
                            elide: Text.ElideMiddle
                            Layout.fillWidth: true
                        }
                    }
                }
            }
        }
        // 3a. Sonraki adımlar: oyunu çeviriyle başlat, çeviriyi editörde gözden geçir
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 22
            Layout.rightMargin: 22
            spacing: 12

            Button {
                id: launchGameBtn
                Layout.fillWidth: true; height: 42
                visible: !!appBackend.projectInfo.launcher
                scale: down ? 0.97 : (hovered ? 1.02 : 1.0)
                transformOrigin: Item.Center
                Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                onClicked: appBackend.launchGame()
                background: Rectangle {
                    radius: 10
                    color: launchGameBtn.down ? Theme.alpha(Theme.success, 0.25) : (launchGameBtn.hovered ? Theme.alpha(Theme.success, 0.18) : Theme.alpha(Theme.success, 0.1))
                    border.color: Theme.alpha(Theme.success, launchGameBtn.hovered ? 0.8 : 0.45)
                    border.width: 1
                    Behavior on color { ColorAnimation { duration: 140 } }
                }
                contentItem: IconLabel {
                    glyph: Icons.play
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("completion_launch_game", "Launch Game")
                    color: Theme.success; font.bold: true; font.pixelSize: 13
                }
            }

            Button {
                id: reviewEditorBtn
                Layout.fillWidth: true; height: 42
                scale: down ? 0.97 : (hovered ? 1.02 : 1.0)
                transformOrigin: Item.Center
                Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                onClicked: { completionDialog.close(); root.openEditorForTarget() }
                background: Rectangle {
                    radius: 10
                    color: reviewEditorBtn.down ? Theme.alpha(Theme.purple, 0.22) : (reviewEditorBtn.hovered ? Theme.alpha(Theme.purple, 0.14) : Theme.input)
                    border.color: reviewEditorBtn.hovered ? Theme.purple : Theme.alpha(Theme.white, 0.12)
                    border.width: 1
                    Behavior on color { ColorAnimation { duration: 140 } }
                }
                contentItem: IconLabel {
                    glyph: Icons.squarePen
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("completion_open_editor", "Review in Editor")
                    color: reviewEditorBtn.hovered ? Theme.purple : Theme.txt; font.bold: true; font.pixelSize: 13
                }
            }
        }

        // 3b. Destek satırı: yalnızca 3. tamamlanan çeviriden itibaren, kapatılınca bir daha gösterilmez
        Rectangle {
            Layout.fillWidth: true
            Layout.leftMargin: 22
            Layout.rightMargin: 22
            visible: !!appBackend.completionStats.show_support
            implicitHeight: supportCol.implicitHeight + 20
            radius: 10
            color: Theme.alpha(Theme.support, 0.07)
            border.color: Theme.alpha(Theme.support, 0.35)
            border.width: 1

            ColumnLayout {
                id: supportCol
                anchors.fill: parent
                anchors.margins: 10
                spacing: 6

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Icon { glyph: Icons.heart; size: 16; color: Theme.support }
                    Label {
                        Layout.fillWidth: true
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("completion_support_text", "If this tool saved you time, you can support its developer.")
                        font.pixelSize: 12
                        color: Theme.txt2
                        wrapMode: Text.WordWrap
                    }
                    Button {
                        id: supportBtn
                        implicitHeight: 28
                        implicitWidth: supportLabel.implicitWidth + 24
                        topInset: 0; bottomInset: 0; leftInset: 0; rightInset: 0; padding: 0
                        onClicked: Qt.openUrlExternally("https://www.patreon.com/cw/LordOfTurk")
                        background: Rectangle {
                            radius: 8
                            color: Theme.alpha(Theme.support, supportBtn.hovered ? 0.28 : 0.16)
                            border.color: Theme.alpha(Theme.support, 0.6)
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 140 } }
                        }
                        contentItem: Label {
                            id: supportLabel
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("completion_support_btn", "Support")
                            font.pixelSize: 11
                            font.bold: true
                            color: Theme.support
                        }
                    }
                }

                CheckBox {
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("completion_support_hide", "Don't show again")
                    font.pixelSize: 11
                    padding: 0
                    onToggled: appBackend.setHideSupportPrompt(checked)
                }
            }
        }

        // 3. Alt Butonlar Grubu
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 22
            Layout.rightMargin: 22
            Layout.bottomMargin: 20
            spacing: 12

            // Çıktı Klasörünü Aç (Secondary Action Button)
            Button {
                id: openFolderBtn
                Layout.fillWidth: true; height: 42
                visible: completionDialog.outputPath.length > 0
                scale: down ? 0.97 : (hovered ? 1.02 : 1.0)
                transformOrigin: Item.Center
                Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                onClicked: if (completionDialog.outputPath) appBackend.openLocalPath(completionDialog.outputPath)

                background: Rectangle {
                    radius: 10
                    color: openFolderBtn.down ? Theme.cardHover : (openFolderBtn.hovered ? Theme.cardHover : Theme.input)
                    border.color: openFolderBtn.hovered ? Theme.accent : Theme.alpha(Theme.white, 0.12)
                    border.width: 1
                    Behavior on color { ColorAnimation { duration: 140 } }
                    Behavior on border.color { ColorAnimation { duration: 140 } }
                }
                contentItem: RowLayout {
                    spacing: 8
                    Item { Layout.fillWidth: true }
                    Icon { glyph: Icons.folderOpen; size: 14; color: openFolderBtn.hovered ? Theme.txt : Theme.txt }
                    Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("open_output_folder", "Çıktı Klasörünü Aç")
                        color: openFolderBtn.hovered ? Theme.txt : Theme.txt
                        font.bold: true; font.pixelSize: 13
                    }
                    Item { Layout.fillWidth: true }
                }
            }

            // Tamam (Primary Action Button)
            Button {
                id: completionOkBtn
                Layout.preferredWidth: completionDialog.outputPath.length > 0 ? 130 : parent.width
                Layout.fillWidth: completionDialog.outputPath.length === 0
                height: 42
                scale: down ? 0.97 : (hovered ? 1.02 : 1.0)
                transformOrigin: Item.Center
                Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                onClicked: completionDialog.close()

                background: Rectangle {
                    radius: 10
                    color: completionOkBtn.hovered ? Theme.accentHover : Theme.accent
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: completionOkBtn.hovered ? Theme.accentHover : Theme.accent }
                        GradientStop { position: 1.0; color: completionOkBtn.hovered ? Theme.accentHover : Theme.accent }
                    }
                    Behavior on color { ColorAnimation { duration: 140 } }
                }
                contentItem: Label {
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("dialog_ok", "Tamam")
                    color: Theme.textOnAccent
                    font.bold: true
                    font.pixelSize: 13
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
        }
    }
}
