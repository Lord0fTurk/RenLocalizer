// IconLabel.qml — ikon + metin. Butonların contentItem'ı ve başlıklar için.
// contentItem: IconLabel { glyph: Icons.copy; text: parent.text; color: Theme.txt; font.pixelSize: 11 }
import QtQuick
import QtQuick.Controls

Item {
    id: il
    property string glyph: ""
    property string text: ""
    property color color: Theme.txt
    property color iconColor: color
    property int iconSize: Math.round(label.font.pixelSize * 1.2)
    property int spacing: 6
    property int leftPadding: 0
    // Qt.AlignHCenter (buton) veya Qt.AlignLeft (başlık)
    property int alignment: Qt.AlignHCenter
    property alias font: label.font
    property alias elide: label.elide

    readonly property bool _hasIcon: glyph.length > 0
    readonly property real _gap: _hasIcon && text.length > 0 ? spacing : 0

    implicitWidth: leftPadding + (_hasIcon ? iconSize : 0) + _gap + label.implicitWidth
    implicitHeight: Math.max(_hasIcon ? iconSize : 0, label.implicitHeight)

    Row {
        id: row
        spacing: il._gap
        anchors.verticalCenter: parent.verticalCenter
        // Sığmayan metin Label gibi iki yana taşar; kısaltmak için elide verin.
        x: il.alignment === Qt.AlignHCenter ? (il.width - width) / 2
         : il.alignment === Qt.AlignRight ? Math.max(0, il.width - width) : il.leftPadding

        Icon {
            visible: il._hasIcon
            glyph: il.glyph
            size: il.iconSize
            color: il.iconColor
            anchors.verticalCenter: parent.verticalCenter
        }
        Label {
            id: label
            text: il.text
            color: il.color
            // Kısaltma istenmediyse ya da genişlik verilmediyse (düzen dışı) metnin kendi genişliği
            width: label.elide === Text.ElideNone || il.width <= 0 ? implicitWidth
                 : Math.min(implicitWidth, il.width - il.leftPadding - (il._hasIcon ? il.iconSize : 0) - il._gap)
            anchors.verticalCenter: parent.verticalCenter
        }
    }
}
