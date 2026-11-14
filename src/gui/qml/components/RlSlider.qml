// A neutral slider (see RlSwitch for why it is not accent-coloured).
//   RlSlider { from: 1; to: 32; stepSize: 1; value: x; onMoved: x = value }
import QtQuick
import QtQuick.Templates as T

T.Slider {
    id: control
    implicitWidth: 200
    implicitHeight: 28
    opacity: enabled ? 1.0 : 0.45

    background: Rectangle {
        x: control.leftPadding
        y: control.topPadding + control.availableHeight / 2 - height / 2
        width: control.availableWidth
        height: 4; radius: 2
        color: Theme.borderControl
        Rectangle {
            width: control.visualPosition * parent.width
            height: parent.height; radius: 2
            color: Theme.txt2
        }
    }

    handle: Rectangle {
        x: control.leftPadding + control.visualPosition * (control.availableWidth - width)
        y: control.topPadding + control.availableHeight / 2 - height / 2
        width: 16; height: 16; radius: 8
        color: Theme.txt
        border.color: control.visualFocus ? Theme.accent : Theme.bg
        border.width: 2
        scale: control.pressed ? 1.15 : 1.0
        Behavior on scale { NumberAnimation { duration: 100 } }
    }
}
