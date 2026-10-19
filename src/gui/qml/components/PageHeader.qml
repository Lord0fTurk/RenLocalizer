// PageHeader.qml — her sayfanın sabit üst başlığı.
// İkon kutusu + başlık + alt başlık, sağda eylemler (actions), altında isteğe
// bağlı satırlar (sekmeler, filtreler, arama — doğrudan içine yazılır).
// İçerikle aynı genişlikte ve hizada durur: contentWidth = min(width - 48, maxContentWidth);
// sayfa içeriği de bu genişliği kullanmalı.
//
//   PageHeader {
//       anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
//       glyph: Icons.terminal; title: ...; subtitle: ...
//       actions: [ Button { ... } ]
//       RowLayout { ... }   // başlığın altındaki satır
//   }
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: header
    property string glyph: ""
    property string title: ""
    property string subtitle: ""
    // Kartlı sayfalar 1180'de durur; log ve editör gibi çalışma sayfaları tam genişlik ister
    property int maxContentWidth: 1180
    property alias actions: actionRow.data
    default property alias content: extraColumn.data
    readonly property real contentWidth: Math.min(width - 48, maxContentWidth)

    color: Theme.bg
    z: 10
    implicitHeight: column.implicitHeight + 34

    ColumnLayout {
        id: column
        width: header.contentWidth
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: 18
        spacing: 14

        GridLayout {
            id: topGrid
            Layout.fillWidth: true
            // Eylemler başlığın yanına sığmazsa (dar pencere, uzun çeviri) alt satıra iner
            readonly property bool narrow: actionRow.visible
                && width < (tile.visible ? tile.width + 14 : 0) + titleLabel.implicitWidth + actionRow.implicitWidth + columnSpacing
            columns: narrow ? 1 : 2
            columnSpacing: 16
            rowSpacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 14
                Rectangle {
                    id: tile
                    visible: header.glyph.length > 0
                    implicitWidth: 40; implicitHeight: 40; radius: 10
                    color: Theme.alpha(Theme.accent, 0.12)
                    border.color: Theme.alpha(Theme.accent, 0.3); border.width: 1
                    Icon { anchors.centerIn: parent; glyph: header.glyph; size: 20; color: Theme.accent }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    Label {
                        id: titleLabel
                        Layout.fillWidth: true
                        text: header.title
                        font.pixelSize: 24; font.bold: true; color: Theme.txt
                        elide: Text.ElideRight
                    }
                    Label {
                        Layout.fillWidth: true
                        visible: text.length > 0
                        text: header.subtitle
                        font.pixelSize: 12; color: Theme.txt2
                        elide: Text.ElideRight
                    }
                }
            }

            RowLayout {
                id: actionRow
                visible: children.length > 0
                spacing: 10
                Layout.alignment: topGrid.narrow ? Qt.AlignLeft : (Qt.AlignRight | Qt.AlignVCenter)
            }
        }

        ColumnLayout {
            id: extraColumn
            Layout.fillWidth: true
            visible: children.length > 0
            spacing: 10
        }
    }

    Rectangle {
        anchors.bottom: parent.bottom
        anchors.left: parent.left; anchors.right: parent.right
        height: 1
        color: Theme.cardBorder
        opacity: 0.6
    }
}
