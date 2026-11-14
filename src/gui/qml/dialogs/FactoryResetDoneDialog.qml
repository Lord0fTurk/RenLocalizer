// Shown after a factory reset; restarts the app.
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
    id: factoryResetDoneDialog
    anchors.centerIn: parent
    width: Math.min(480, root.width * 0.85)
    padding: 0
    header: null
    footer: null
    modal: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    standardButtons: Dialog.NoButton

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
        radius: 10
        border.color: Theme.alpha(Theme.success, 0.45)
        border.width: 1.5
        clip: true

        Rectangle {
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: 3
            color: Theme.success
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
                color: Theme.successDim
                border.color: Theme.success; border.width: 1.5

                Icon {
                    anchors.centerIn: parent
                    glyph: Icons.circleCheck
                    size: 20
                    color: Theme.success
                }
            }

            ColumnLayout {
                spacing: 2
                Layout.fillWidth: true

                Label {
                    text: appBackend.uiTrigger, cleanModalTitle(appBackend.getTextWithDefault("factory_reset_done_title", "Sıfırlama Tamamlandı"))
                    font.pixelSize: 18; font.bold: true; color: Theme.txt
                }
                Label {
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_done_sub", "Ayarlar varsayılan duruma getirildi")
                    font.pixelSize: 12; color: Theme.txt2
                }
            }

            Item { Layout.fillWidth: true }
            Rectangle {
                width: 30; height: 30; radius: 15
                color: closeResetDoneMa.containsMouse ? Theme.alpha(Theme.white, 0.12) : "transparent"
                scale: closeResetDoneMa.pressed ? 0.92 : (closeResetDoneMa.containsMouse ? 1.08 : 1.0)
                Behavior on scale { NumberAnimation { duration: 120 } }
                Behavior on color { ColorAnimation { duration: 120 } }

                Label {
                    anchors.centerIn: parent
                    text: "✕"
                    color: closeResetDoneMa.containsMouse ? Theme.white : Theme.txtDim
                    font.pixelSize: 13; font.bold: true
                }
                MouseArea {
                    id: closeResetDoneMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: factoryResetDoneDialog.close()
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.leftMargin: 20
            Layout.rightMargin: 20
            Layout.preferredHeight: resetDoneBodyLbl.implicitHeight + 24
            radius: 12
            color: Theme.input
            border.color: Theme.borderControl
            border.width: 1

            Label {
                id: resetDoneBodyLbl
                anchors.fill: parent
                anchors.margins: 14
                text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_done_msg", "Program ilk kurulduğu haline döndü. Temiz bir başlangıç için uygulamayı yeniden başlatın; bundan sonra yaptığınız ayarlar otomatik kaydedilecektir.")
                color: Theme.txt
                wrapMode: Text.Wrap
                font.pixelSize: 13
                lineHeight: 1.35
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
                onClicked: factoryResetDoneDialog.close()

                background: Rectangle {
                    radius: 10
                    color: parent.down ? Theme.alpha(Theme.white, 0.08) : (parent.hovered ? Theme.alpha(Theme.white, 0.05) : "transparent")
                    border.color: parent.hovered ? Theme.txt2 : Theme.cardBorder
                    border.width: 1
                    Behavior on border.color { ColorAnimation { duration: 140 } }
                }
                contentItem: Label {
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_restart_later", "Daha Sonra")
                    color: Theme.txt2
                    font.pixelSize: 13
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Button {
                id: factoryRestartBtn
                Layout.preferredWidth: 180; height: 40
                scale: down ? 0.97 : (hovered ? 1.02 : 1.0)
                transformOrigin: Item.Center
                Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                onClicked: appBackend.restartApplication()

                background: Rectangle {
                    radius: 10
                    color: factoryRestartBtn.hovered ? Theme.accentHover : Theme.accent
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: factoryRestartBtn.hovered ? Theme.accentHover : Theme.accent }
                        GradientStop { position: 1.0; color: factoryRestartBtn.hovered ? Theme.accentHover : Theme.accent }
                    }
                    Behavior on color { ColorAnimation { duration: 140 } }
                }
                contentItem: IconLabel {
                    glyph: Icons.refreshCw
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_restart_now", "Şimdi Yeniden Başlat")
                    color: Theme.textOnAccent
                    font.bold: true
                    font.pixelSize: 13
                }
            }
        }
    }
}
