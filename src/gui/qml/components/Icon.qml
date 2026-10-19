// Icon.qml — Lucide ikonu, kare bir kutu içinde (satırlar hizalı kalsın diye).
// Icon { glyph: Icons.search; size: 14; color: Theme.txtDim }
import QtQuick

Item {
    id: icon
    property string glyph: ""
    property int size: 16
    property color color: Theme.txt

    implicitWidth: size
    implicitHeight: size

    Text {
        anchors.centerIn: parent
        text: icon.glyph
        color: icon.color
        font.family: Icons.family
        font.pixelSize: icon.size
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
}
