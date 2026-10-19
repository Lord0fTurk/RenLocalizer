// ToastNotification.qml — Reusable Fluent Toast Notification Component
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: toast
    z: 999
    anchors.right: parent ? parent.right : undefined
    anchors.bottom: parent ? parent.bottom : undefined
    anchors.margins: 28
    width: Math.min(520, toastText.implicitWidth + 64)
    radius: 12
    height: Math.max(48, toastText.implicitHeight + 28)

    property string message: ""
    property string toastType: "info"


    color: toastType === "success" ? Theme.toastSuccess :
           toastType === "error"   ? Theme.toastError :
           toastType === "warning" ? Theme.toastWarn : Theme.toastInfo
    border.color: toastType === "success" ? Theme.success :
                  toastType === "error"   ? Theme.error :
                  toastType === "warning" ? Theme.warn : Theme.accent
    border.width: 1.5

    opacity: 0.0
    visible: opacity > 0
    scale: opacity > 0 ? 1.0 : 0.94
    transformOrigin: Item.BottomRight
    transform: Translate {
        y: toast.opacity > 0 ? 0 : 14
        Behavior on y { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
    }
    Behavior on scale { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
    Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutQuad } }

    function show(msg, type) {
        message = msg
        toastType = type || "info"
        opacity = 1.0
        toastTimer.restart()
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 12
        Icon {
            glyph: toast.toastType === "success" ? Icons.circleCheck :
                   toast.toastType === "error"   ? Icons.circleX :
                   toast.toastType === "warning" ? Icons.triangleAlert : Icons.info
            color: toast.toastType === "success" ? Theme.success :
                   toast.toastType === "error"   ? Theme.error :
                   toast.toastType === "warning" ? Theme.warn : Theme.accent
            size: 18
        }
        Label {
            id: toastText
            text: toast.message
            color: Theme.txt
            font.pixelSize: 13
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
        }
    }
    Timer {
        id: toastTimer
        interval: 3500
        onTriggered: toast.opacity = 0.0
    }
}
