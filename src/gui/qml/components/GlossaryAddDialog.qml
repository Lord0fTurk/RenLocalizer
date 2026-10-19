// GlossaryAddDialog.qml — Reusable Glossary Addition Dialog
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: addGlossaryDialog
    anchors.centerIn: parent
    width: Math.min(460, parent ? parent.width * 0.85 : 460)
    padding: 0
    header: null
    footer: null
    modal: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    standardButtons: Dialog.NoButton


    function cleanTitle(str) {
        if (typeof root !== "undefined" && root.cleanModalTitle) {
            return root.cleanModalTitle(str);
        }
        return str || "";
    }

    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0.0; to: 1.0; duration: 180; easing.type: Easing.OutCubic }
        NumberAnimation { property: "scale"; from: 0.94; to: 1.0; duration: 180; easing.type: Easing.OutCubic }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; from: 1.0; to: 0.0; duration: 140; easing.type: Easing.InQuad }
        NumberAnimation { property: "scale"; from: 1.0; to: 0.96; duration: 140; easing.type: Easing.InQuad }
    }

    Overlay.modal: Rectangle {
        color: Theme.alpha(Theme.black, 0.65)
    }

    background: Rectangle {
        color: Theme.card
        radius: 18
        border.color: Theme.alpha(Theme.accent, 0.45)
        border.width: 1.5
        clip: true

        Rectangle {
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: 3
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Theme.accent }
                GradientStop { position: 1.0; color: Theme.accent2 }
            }
        }
    }

    contentItem: ColumnLayout {
        spacing: 16

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 20
            Layout.rightMargin: 18
            Layout.topMargin: 20
            spacing: 14

            Rectangle {
                width: 40; height: 40; radius: 20
                color: Theme.alpha(Theme.accent, 0.15)
                border.color: Theme.accent; border.width: 1.5

                Icon {
                    anchors.centerIn: parent
                    glyph: Icons.bookPlus
                    size: 20
                    color: Theme.accent
                }
            }

            ColumnLayout {
                spacing: 2
                Layout.fillWidth: true

                Label {
                    text: appBackend.uiTrigger, addGlossaryDialog.cleanTitle(appBackend.getTextWithDefault("glossary_dlg_add_title", "Sözlüğe Terim Ekle"))
                    font.pixelSize: 18; font.bold: true; color: Theme.txt
                }
                Label {
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_dlg_add_sub", "Çevrilmeyecek veya özel çevrilecek terim tanımlayın")
                    font.pixelSize: 12; color: Theme.txt2
                }
            }

            Item { Layout.fillWidth: true }
            Rectangle {
                width: 30; height: 30; radius: 15
                color: closeGlossaryMa.containsMouse ? Theme.alpha(Theme.white, 0.12) : "transparent"
                scale: closeGlossaryMa.pressed ? 0.92 : (closeGlossaryMa.containsMouse ? 1.08 : 1.0)
                Behavior on scale { NumberAnimation { duration: 120 } }
                Behavior on color { ColorAnimation { duration: 120 } }

                Label {
                    anchors.centerIn: parent
                    text: "✕"
                    color: closeGlossaryMa.containsMouse ? Theme.white : Theme.txtDim
                    font.pixelSize: 13; font.bold: true
                }
                MouseArea {
                    id: closeGlossaryMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: addGlossaryDialog.close()
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.leftMargin: 20
            Layout.rightMargin: 20
            Layout.preferredHeight: glossaryFormCol.implicitHeight + 24
            radius: 12
            color: Theme.input
            border.color: Theme.alpha(Theme.white, 0.08)
            border.width: 1

            ColumnLayout {
                id: glossaryFormCol
                anchors.fill: parent
                anchors.margins: 14
                spacing: 10

                Label {
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_dlg_source", "Kaynak (Orijinal Metin):")
                    color: Theme.txt
                    font.pixelSize: 12
                    font.bold: true
                }
                TextField {
                    id: addGlossarySource
                    Layout.fillWidth: true
                    height: 38
                    color: Theme.txt
                    placeholderText: (text.length === 0 && !activeFocus) ? (appBackend.getTextWithDefault("glossary_dlg_source_placeholder", "e.g. Character Name")) : ""
                    placeholderTextColor: Theme.txtDim
                    font.pixelSize: 13
                    background: Rectangle {
                        radius: 8
                        color: Theme.inputDeep
                        border.color: addGlossarySource.activeFocus ? Theme.accent : Theme.cardBorder
                        border.width: addGlossarySource.activeFocus ? 1.5 : 1
                        Behavior on border.color { ColorAnimation { duration: 150 } }
                    }
                }

                Label {
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_dlg_target", "Hedef (Çeviri):")
                    color: Theme.txt
                    font.pixelSize: 12
                    font.bold: true
                }
                TextField {
                    id: addGlossaryTarget
                    Layout.fillWidth: true
                    height: 38
                    color: Theme.txt
                    placeholderText: (text.length === 0 && !activeFocus) ? (appBackend.getTextWithDefault("glossary_dlg_target_placeholder", "e.g. Karakter Adı")) : ""
                    placeholderTextColor: Theme.txtDim
                    font.pixelSize: 13
                    background: Rectangle {
                        radius: 8
                        color: Theme.inputDeep
                        border.color: addGlossaryTarget.activeFocus ? Theme.accent : Theme.cardBorder
                        border.width: addGlossaryTarget.activeFocus ? 1.5 : 1
                        Behavior on border.color { ColorAnimation { duration: 150 } }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 20
            Layout.rightMargin: 20
            Layout.bottomMargin: 20
            spacing: 12

            Button {
                Layout.fillWidth: true; height: 40
                scale: down ? 0.97 : (hovered ? 1.02 : 1.0)
                transformOrigin: Item.Center
                Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                onClicked: addGlossaryDialog.close()

                background: Rectangle {
                    radius: 10
                    color: parent.down ? Theme.alpha(Theme.white, 0.08) : (parent.hovered ? Theme.alpha(Theme.white, 0.05) : "transparent")
                    border.color: parent.hovered ? Theme.txt2 : Theme.cardBorder
                    border.width: 1
                    Behavior on border.color { ColorAnimation { duration: 140 } }
                }
                contentItem: Label {
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("dialog_cancel", "İptal")
                    color: Theme.txt2
                    font.pixelSize: 13
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Button {
                id: addGlossarySubmitBtn
                Layout.preferredWidth: 130; height: 40
                scale: down ? 0.97 : (hovered ? 1.02 : 1.0)
                transformOrigin: Item.Center
                Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                onClicked: {
                    if (addGlossarySource.text.trim().length > 0) {
                        appBackend.addGlossaryItem(addGlossarySource.text.trim(), addGlossaryTarget.text.trim())
                        addGlossarySource.text = ""
                        addGlossaryTarget.text = ""
                        addGlossaryDialog.close()
                    }
                }

                background: Rectangle {
                    radius: 10
                    color: addGlossarySubmitBtn.hovered ? Theme.accentHover : Theme.accent
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: addGlossarySubmitBtn.hovered ? Theme.accentHover : Theme.accent }
                        GradientStop { position: 1.0; color: addGlossarySubmitBtn.hovered ? Theme.accent : Theme.accent2 }
                    }
                    Behavior on color { ColorAnimation { duration: 140 } }
                }
                contentItem: IconLabel {
                    glyph: Icons.plus
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_add_btn", "Ekle")
                    color: Theme.textOnAccent
                    font.bold: true
                    font.pixelSize: 13
                }
            }
        }
    }
}
