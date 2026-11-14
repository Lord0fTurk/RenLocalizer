// Offers a newer release.
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
    id: updateDialog
    anchors.centerIn: parent
    width: Math.min(480, root.width * 0.85)
    padding: 0
    header: null
    footer: null
    modal: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    standardButtons: Dialog.NoButton
    property string latestVersion: ""
    property string releaseUrl: ""

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
        border.color: Theme.borderControl
        border.width: 1
        clip: true
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
                color: "transparent"
                border.color: Theme.borderControl; border.width: 1

                Icon {
                    anchors.centerIn: parent
                    glyph: Icons.rocket
                    size: 20
                    color: Theme.txt2
                }
            }

            ColumnLayout {
                spacing: 2
                Layout.fillWidth: true

                Label {
                    text: appBackend.uiTrigger, cleanModalTitle(appBackend.getTextWithDefault("update_available_title", "Yeni Sürüm Mevcut"))
                    font.pixelSize: 18; font.bold: true; color: Theme.txt
                }
                Label {
                    text: updateDialog.latestVersion.length > 0 ? ("v" + updateDialog.latestVersion) : ""
                    font.pixelSize: 12; color: Theme.accent; font.bold: true
                    visible: updateDialog.latestVersion.length > 0
                }
            }

            Item { Layout.fillWidth: true }
            Rectangle {
                width: 30; height: 30; radius: 15
                color: closeUpdateMa.containsMouse ? Theme.alpha(Theme.white, 0.12) : "transparent"
                scale: closeUpdateMa.pressed ? 0.92 : (closeUpdateMa.containsMouse ? 1.08 : 1.0)
                Behavior on scale { NumberAnimation { duration: 120 } }
                Behavior on color { ColorAnimation { duration: 120 } }

                Label {
                    anchors.centerIn: parent
                    text: "✕"
                    color: closeUpdateMa.containsMouse ? Theme.white : Theme.txtDim
                    font.pixelSize: 13; font.bold: true
                }
                MouseArea {
                    id: closeUpdateMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: updateDialog.close()
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.leftMargin: 20
            Layout.rightMargin: 20
            Layout.preferredHeight: updateBodyCol.implicitHeight + 24
            radius: 12
            color: Theme.input
            border.color: Theme.borderControl
            border.width: 1

            ColumnLayout {
                id: updateBodyCol
                anchors.fill: parent
                anchors.margins: 14
                spacing: 6

                Label {
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("update_available_msg", "RenLocalizer'ın yeni bir sürümü yayınlandı.")
                    color: Theme.txt
                    font.pixelSize: 13
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
                Label {
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("update_available_click", "Güncellemeyi indirmek için İndir butonuna tıklayın.")
                    color: Theme.txt2
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
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
                onClicked: updateDialog.close()

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
                id: updateDownloadBtn
                Layout.preferredWidth: 140; height: 40
                scale: down ? 0.97 : (hovered ? 1.02 : 1.0)
                transformOrigin: Item.Center
                Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                onClicked: {
                    if (updateDialog.releaseUrl) Qt.openUrlExternally(updateDialog.releaseUrl)
                    updateDialog.close()
                }

                background: Rectangle {
                    radius: 10
                    color: updateDownloadBtn.hovered ? Theme.accentHover : Theme.accent
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: updateDownloadBtn.hovered ? Theme.accentHover : Theme.accent }
                        GradientStop { position: 1.0; color: updateDownloadBtn.hovered ? Theme.accentHover : Theme.accent }
                    }
                    Behavior on color { ColorAnimation { duration: 140 } }
                }
                contentItem: IconLabel {
                    glyph: Icons.download
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("update_download_btn", "İndir")
                    color: Theme.textOnAccent
                    font.bold: true
                    font.pixelSize: 13
                }
            }
        }
    }
}
