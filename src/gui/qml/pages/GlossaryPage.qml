// Glossary: searchable term list, import/export.
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

Item {
    id: pageGlossary
    visible: navIndex === 4
    Layout.fillWidth: true
    Layout.fillHeight: true

    property string searchQuery: ""

    transform: Translate { id: animTrGlossary; y: 14 }
    opacity: 0.0
    ParallelAnimation {
        id: animEntranceGlossary
        NumberAnimation { target: animTrGlossary; property: "y"; from: 14; to: 0; duration: 220; easing.type: Easing.OutCubic }
        NumberAnimation { target: pageGlossary; property: "opacity"; from: 0.0; to: 1.0; duration: 180; easing.type: Easing.OutQuad }
    }
    onVisibleChanged: if (visible) animEntranceGlossary.restart()

    // Sabit Sticky Header (Arama + İşlem Araç Çubuğu)
    PageHeader {
        id: glossaryStickyHeader
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        glyph: Icons.bookA
        title: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_title", "Term Glossary")
        subtitle: appBackend.uiTrigger, (pageGlossary.filteredGlossaryModel().length) + " / " + (appBackend.glossary.glossaryList ? appBackend.glossary.glossaryList.length : 0) + " " + appBackend.getTextWithDefault("glossary_count", "terms loaded.")
        actions: [
            Button {
                height: 34; text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_btn_add", "Add Term")
                onClicked: { addGlossarySource.text = ""; addGlossaryTarget.text = ""; addGlossaryDialog.open() }
                background: Rectangle { radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input; border.color: Theme.borderControl; border.width: 1 }
                contentItem: IconLabel { glyph: Icons.plus; text: parent.text; color: Theme.txt; iconColor: Theme.txt2; font.pixelSize: 11; font.bold: true }
            },
            Button {
                height: 34; text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_btn_import", "Import")
                onClicked: importGlossaryDialog.open()
                background: Rectangle { radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input; border.color: Theme.cardBorder; border.width: 1 }
                contentItem: IconLabel { glyph: Icons.download; text: parent.text; color: Theme.txt; font.pixelSize: 11 }
            },
            Button {
                height: 34; text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_btn_export", "Export")
                onClicked: exportGlossaryDialog.open()
                background: Rectangle { radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input; border.color: Theme.cardBorder; border.width: 1 }
                contentItem: IconLabel { glyph: Icons.upload; text: parent.text; color: Theme.txt; font.pixelSize: 11 }
            },
            Button {
                height: 34; text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_btn_fill", "Fill Source")
                onClicked: appBackend.glossary.fillEmptyGlossaryWithSource()
                background: Rectangle { radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input; border.color: Theme.cardBorder; border.width: 1 }
                contentItem: IconLabel { glyph: Icons.clipboardCopy; text: parent.text; color: Theme.txt; font.pixelSize: 11 }
            },
            Button {
                height: 34; text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_btn_translate", "Translate Empty")
                onClicked: appBackend.glossary.translateEmptyGlossary()
                background: Rectangle { radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input; border.color: Theme.cardBorder; border.width: 1 }
                contentItem: IconLabel { glyph: Icons.languages; text: parent.text; color: Theme.txt; iconColor: Theme.txt2; font.pixelSize: 11; font.bold: true }
            }
        ]

        // Alt Satır: Arama Çubuğu
        RowLayout {
            Layout.fillWidth: true; spacing: 10
            Rectangle {
                Layout.fillWidth: true; height: 32; radius: 8; color: Theme.input; border.color: Theme.cardBorder; border.width: 1
                RowLayout {
                    anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 10; spacing: 8
                    Icon { glyph: Icons.search; size: 14; color: Theme.txtDim }
                    TextInput {
                        id: glossarySearchInput
                        Layout.fillWidth: true
                        font.pixelSize: 12; color: Theme.txt
                        clip: true
                        Text {
                            anchors.fill: parent
                            verticalAlignment: Text.AlignVCenter
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_search_placeholder", "Sözlükte terim veya çeviri ara...")
                            color: Theme.txtDim; font.pixelSize: 12
                            visible: !glossarySearchInput.text && !glossarySearchInput.activeFocus
                        }
                        onTextChanged: pageGlossary.searchQuery = text.trim().toLowerCase()
                    }
                    Button {
                        visible: glossarySearchInput.text.length > 0
                        width: 18; height: 18
                        text: "✕"
                        onClicked: { glossarySearchInput.text = ""; pageGlossary.searchQuery = "" }
                        background: Item {}
                        contentItem: Label { text: "✕"; color: Theme.txtDim; font.pixelSize: 10; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    }
                }
            }
        }
    }

    function filteredGlossaryModel() {
        appBackend.uiTrigger
        var list = appBackend.glossary.glossaryList || []
        var q = pageGlossary.searchQuery
        if (!q) return list
        var result = []
        for (var i = 0; i < list.length; i++) {
            var item = list[i]
            var s = (item.source || "").toLowerCase()
            var t = (item.target || "").toLowerCase()
            if (s.indexOf(q) !== -1 || t.indexOf(q) !== -1) {
                result.push(item)
            }
        }
        return result
    }

    // Scroll Edilebilir İçerik (Liste & Empty State)
    ScrollView {
        anchors.top: glossaryStickyHeader.bottom
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical: ScrollBar {}

        ColumnLayout {
            width: Math.min(parent.width - 48, 1180)
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 10

            Item { Layout.preferredHeight: 6 } // başlık çizgisiyle ilk satır arası

            // Tablo Başlığı
            RowLayout {
                Layout.fillWidth: true; spacing: 12
                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_col_source", "Source (Original)"); font.pixelSize: 12; font.bold: true; color: Theme.txt2; Layout.fillWidth: true; Layout.preferredWidth: 320 }
                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_col_target", "Target (Translation)"); font.pixelSize: 12; font.bold: true; color: Theme.txt2; Layout.fillWidth: true }
                Item { Layout.preferredWidth: 40 }
            }

            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.cardBorder }

            // Boş Durum (Empty State) Kartı
            Rectangle {
                visible: pageGlossary.filteredGlossaryModel().length === 0
                Layout.fillWidth: true; Layout.preferredHeight: 180
                radius: 0; color: "transparent"; border.width: 0
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.cardBorder }
                ColumnLayout {
                    anchors.centerIn: parent; spacing: 10
                    Icon { glyph: Icons.bookOpen; size: 36; color: Theme.txtDim; Layout.alignment: Qt.AlignHCenter }
                    Label {
                        text: appBackend.uiTrigger, pageGlossary.searchQuery.length > 0
                            ? appBackend.getTextWithDefault("glossary_no_search_results", "Aramanızla eşleşen terim bulunamadı.")
                            : appBackend.getTextWithDefault("glossary_empty_state", "Henüz terim eklenmedi. 'Terim Ekle' veya 'İçe Aktar' ile başlayın.")
                        font.pixelSize: 13; color: Theme.txt2; font.bold: true; Layout.alignment: Qt.AlignHCenter
                    }
                }
            }

            // Terimler Listesi (ListView)
            ListView {
                id: glossaryListView
                Layout.fillWidth: true
                Layout.preferredHeight: contentHeight
                model: pageGlossary.filteredGlossaryModel()
                clip: true; interactive: false
                spacing: 8
                delegate: RowLayout {
                    width: glossaryListView.width; spacing: 12
                    Rectangle {
                        Layout.fillWidth: true; Layout.preferredWidth: 320; height: 42; radius: 8
                        color: Theme.input; border.color: Theme.cardBorder; border.width: 1
                        Label {
                            anchors.fill: parent; anchors.margins: 12
                            text: modelData.source; color: Theme.txt; font.pixelSize: 12
                            elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true; height: 42; radius: 8
                        color: Theme.input; border.color: modelData.target ? Theme.cardBorder : Theme.alpha(Theme.error, 0.35); border.width: 1
                        Label {
                            anchors.fill: parent; anchors.margins: 12
                            text: modelData.target || appBackend.getTextWithDefault("glossary_empty", "(empty)"); color: modelData.target ? Theme.txt : Theme.error
                            font.pixelSize: 12; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter
                        }
                    }
                    Button {
                        Layout.preferredWidth: 36; height: 36
                        text: "✕"
                        onClicked: appBackend.glossary.removeGlossaryItem(modelData.source)
                        background: Rectangle { radius: 8; color: parent.hovered ? Theme.dangerTint : "transparent"; border.color: "transparent" }
                        contentItem: Label { text: "✕"; color: Theme.error; font.pixelSize: 14; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    }
                }
            }

            Item { height: 24 }
        }
    }
}
