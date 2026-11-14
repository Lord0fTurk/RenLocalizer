// A neutral switch: the accent colour is reserved for the primary action,
// progress and focus, so "on" is shown by a filled track in the text colour.
//   RlSwitch { checked: appBackend.someFlag; onToggled: appBackend.someFlag = checked }
import QtQuick
import QtQuick.Templates as T

T.Switch {
    id: control
    implicitWidth: 40
    implicitHeight: 24
    opacity: enabled ? 1.0 : 0.45

    indicator: Rectangle {
        width: 40; height: 22; radius: 11
        anchors.verticalCenter: parent.verticalCenter
        color: control.checked ? Theme.txt : "transparent"
        border.color: control.visualFocus ? Theme.accent : (control.checked ? Theme.txt : Theme.txtDim)
        border.width: control.visualFocus ? 2 : 1
        Behavior on color { ColorAnimation { duration: 120 } }

        Rectangle {
            width: 14; height: 14; radius: 7
            y: 4
            x: control.checked ? parent.width - width - 4 : 4
            color: control.checked ? Theme.bg : Theme.txt2
            Behavior on x { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
        }
    }
}
