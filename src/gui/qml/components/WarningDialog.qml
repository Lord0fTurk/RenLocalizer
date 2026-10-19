// WarningDialog.qml — Reusable Fluent Warning Dialog Component
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: warningDialog
    anchors.centerIn: parent
    width: Math.min(480, parent ? parent.width * 0.85 : 480)
    padding: 0
    header: null
    footer: null
    modal: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    standardButtons: Dialog.NoButton

    property string titleText: ""
    property string bodyText: ""


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
        border.color: Theme.alpha(Theme.warn, 0.5)
        border.width: 1.5
        clip: true

        Rectangle {
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: 3
            color: Theme.warn
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
                color: Theme.warnDim
                border.color: Theme.warn; border.width: 1.5

                Icon {
                    anchors.centerIn: parent
                    glyph: Icons.triangleAlert
                    size: 20
                    color: Theme.warn
                }
            }

            ColumnLayout {
                spacing: 2
                Layout.fillWidth: true

                Label {
                    text: warningDialog.titleText.length > 0 ? warningDialog.titleText : appBackend.getTextWithDefault("warning_title", "Uyarı")
                    font.pixelSize: 18; font.bold: true; color: Theme.txt
                }
            }

            Item { Layout.fillWidth: true }
            Rectangle {
                width: 30; height: 30; radius: 15
                color: closeWarnMa.containsMouse ? Theme.alpha(Theme.white, 0.12) : "transparent"
                scale: closeWarnMa.pressed ? 0.92 : (closeWarnMa.containsMouse ? 1.08 : 1.0)
                Behavior on scale { NumberAnimation { duration: 120 } }
                Behavior on color { ColorAnimation { duration: 120 } }

                Label {
                    anchors.centerIn: parent
                    text: "✕"
                    color: closeWarnMa.containsMouse ? Theme.white : Theme.txtDim
                    font.pixelSize: 13
                    font.bold: true
                }
                MouseArea {
                    id: closeWarnMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: warningDialog.close()
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.leftMargin: 20
            Layout.rightMargin: 20
            Layout.preferredHeight: warnBodyLbl.implicitHeight + 24
            radius: 12
            color: Theme.input
            border.color: Theme.alpha(Theme.white, 0.08)
            border.width: 1

            Label {
                id: warnBodyLbl
                anchors.fill: parent
                anchors.margins: 14
                text: warningDialog.bodyText
                color: Theme.txt
                wrapMode: Text.Wrap
                font.pixelSize: 13
                lineHeight: 1.3
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 20
            Layout.rightMargin: 20
            Layout.bottomMargin: 20

            Item { Layout.fillWidth: true }

            Button {
                Layout.preferredWidth: 120
                height: 40
                scale: down ? 0.97 : (hovered ? 1.02 : 1.0)
                transformOrigin: Item.Center
                Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                onClicked: warningDialog.close()

                background: Rectangle {
                    radius: 10
                    color: parent.hovered ? Theme.warnHover : Theme.warn
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
