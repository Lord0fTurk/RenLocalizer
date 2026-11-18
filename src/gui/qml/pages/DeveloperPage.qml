// Developer inspection page: styled after EditorPage (header, themed combo/search, chips, flat list).
// Visible in navigation only when appBackend.developerMode is enabled.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import "../components"

Item {
    id: pageDeveloper
    Layout.fillWidth: true
    Layout.fillHeight: true

    onVisibleChanged: if (visible) developerBackend.refresh()

    component DevChip: Rectangle {
        property string label
        property color tint
        property bool active: false
        signal clicked()
        implicitHeight: 28
        implicitWidth: devChipText.implicitWidth + 22
        radius: 14
        color: active ? Theme.alpha(tint, 0.22) : Theme.alpha(tint, 0.08)
        border.color: Theme.alpha(tint, active ? 0.8 : 0.3)
        Label {
            id: devChipText
            anchors.centerIn: parent
            text: parent.label
            color: parent.tint
            font.pixelSize: 12
            font.bold: parent.active
        }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: parent.clicked() }
    }

    component DevActionButton: Button {
        id: devActionBtn
        property color tint: Theme.accent
        property bool emphasized: false
        property string glyph: ""
        implicitHeight: 34
        topInset: 0; bottomInset: 0
        leftPadding: 12; rightPadding: 12
        opacity: enabled ? 1.0 : 0.5
        background: Rectangle {
            radius: 8
            color: devActionBtn.down ? Theme.cardHover : (devActionBtn.hovered && devActionBtn.enabled ? Theme.cardHover : Theme.input)
            border.color: devActionBtn.emphasized ? devActionBtn.tint
                        : (devActionBtn.hovered && devActionBtn.enabled ? Theme.txtDim : Theme.borderControl)
            border.width: 1
            Behavior on border.color { ColorAnimation { duration: 150 } }
        }
        contentItem: IconLabel {
            glyph: devActionBtn.glyph
            text: devActionBtn.text
            color: devActionBtn.emphasized ? devActionBtn.tint : Theme.txt
            font.pixelSize: 11
            font.bold: devActionBtn.emphasized
        }
    }

    component DevCombo: ComboBox {
        id: devCombo
        implicitHeight: 36
        topInset: 0; bottomInset: 0
        font.pixelSize: 12
        background: Rectangle {
            radius: 8
            color: Theme.input
            border.color: devCombo.hovered || devCombo.visualFocus ? Theme.txtDim : Theme.borderControl
            border.width: 1
            Behavior on border.color { ColorAnimation { duration: 150 } }
        }
        contentItem: Label {
            leftPadding: 12; rightPadding: 30
            text: devCombo.displayText
            color: devCombo.enabled ? Theme.txt : Theme.txtDim
            font.pixelSize: 12
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }
        delegate: ItemDelegate {
            width: devCombo.width
            contentItem: Label {
                text: modelData
                color: Theme.txt
                font.pixelSize: 12; leftPadding: 12; elide: Text.ElideRight
            }
            background: Rectangle { color: hovered ? Theme.cardHover : "transparent" }
        }
        popup: Popup {
            y: devCombo.height + 4
            width: devCombo.width
            implicitHeight: Math.min(contentItem.implicitHeight + 8, 320)
            padding: 4
            contentItem: ListView {
                clip: true
                implicitHeight: contentHeight
                model: devCombo.delegateModel
                currentIndex: devCombo.highlightedIndex
                ScrollBar.vertical: ScrollBar {}
            }
            background: Rectangle { color: Theme.card; radius: 8; border.color: Theme.cardBorder; border.width: 1 }
        }
    }

    component DevSearchInput: Rectangle {
        id: devInputBox
        property alias text: devInputField.text
        property string placeholder: ""
        property string icon: ""
        implicitHeight: 34
        radius: 8
        color: Theme.input
        border.color: devInputField.activeFocus ? Theme.txtDim : Theme.borderControl
        border.width: 1
        Behavior on border.color { ColorAnimation { duration: 150 } }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10; anchors.rightMargin: 10
            spacing: 8
            Icon { visible: devInputBox.icon.length > 0; glyph: devInputBox.icon; size: 14; color: Theme.txtDim }
            TextInput {
                id: devInputField
                Layout.fillWidth: true
                font.pixelSize: 12
                color: Theme.txt
                selectionColor: Theme.alpha(Theme.accent, 0.35)
                selectByMouse: true
                clip: true
                verticalAlignment: TextInput.AlignVCenter
                Text {
                    anchors.fill: parent
                    verticalAlignment: Text.AlignVCenter
                    text: devInputBox.placeholder
                    color: Theme.txtDim
                    font.pixelSize: 12
                    elide: Text.ElideRight
                    visible: !devInputField.text && !devInputField.activeFocus
                }
            }
            Label {
                visible: devInputField.text.length > 0
                text: "✕"; color: Theme.txtDim; font.pixelSize: 10
                MouseArea { anchors.fill: parent; anchors.margins: -4; cursorShape: Qt.PointingHandCursor; onClicked: devInputField.text = "" }
            }
        }
    }

    PageHeader {
        id: devPageHeader
        anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
        maxContentWidth: 100000
        glyph: Icons.stethoscope
        title: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_developer", "Geliştirici")
        subtitle: appBackend.uiTrigger, appBackend.getTextWithDefault("dev_page_desc", "Engellenen satırları, kapsam uyarılarını ve tanılama raporunu inceleyin.")
        actions: [
            DevCombo {
                id: devPageLangCombo
                Layout.preferredWidth: 170
                enabled: developerBackend.languages.length > 0
                model: developerBackend.languages
                currentIndex: Math.max(0, developerBackend.languages.indexOf(developerBackend.language))
                onActivated: developerBackend.loadLanguage(currentText)
            },
            DevActionButton {
                id: devPageRefreshBtn
                glyph: Icons.refreshCw
                text: appBackend.uiTrigger, appBackend.getTextWithDefault("dev_refresh", "Yenile")
                onClicked: developerBackend.refresh()
            },
            DevActionButton {
                id: devPageOpenJsonBtn
                emphasized: true
                tint: Theme.accent
                glyph: Icons.fileJson
                enabled: developerBackend.reportPath.length > 0
                text: appBackend.uiTrigger, appBackend.getTextWithDefault("dev_open_raw_report", "Raporu Aç (JSON)")
                onClicked: developerBackend.openRawReport()
            }
        ]
    }

    ColumnLayout {
        anchors.top: devPageHeader.bottom; anchors.topMargin: 14
        anchors.bottom: parent.bottom; anchors.bottomMargin: 14
        anchors.horizontalCenter: parent.horizontalCenter
        width: devPageHeader.contentWidth
        spacing: 10

        // Notice bar + Engine provenance
        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Icon { glyph: Icons.info; size: 14; color: Theme.txtDim }
            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                font.pixelSize: 12
                color: Theme.txt2
                text: appBackend.uiTrigger, appBackend.getTextWithDefault(
                    "dev_report_notice",
                    "Not: diagnostic_<dil>.json ve bu sayfadaki teknik detaylar geliştiriciler ve ileri düzey incelemeler içindir."
                )
            }
            Label {
                visible: (developerBackend.summary.engine || "").length > 0
                text: (developerBackend.summary.engine || "") + (developerBackend.summary.model ? " / " + developerBackend.summary.model : "")
                color: Theme.txtDim
                font.pixelSize: 11
            }
        }

        // Toolbar: Search bar + filter chips
        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            DevSearchInput {
                id: devPageSearchBox
                Layout.fillWidth: true
                Layout.maximumWidth: 360
                icon: Icons.search
                placeholder: appBackend.uiTrigger, appBackend.getTextWithDefault("dev_search_placeholder", "Satır, dosya veya uyarı ara...")
                onTextChanged: developerBackend.setSearchQuery(text)
            }

            DevChip {
                label: appBackend.uiTrigger, appBackend.getTextWithDefault("dev_filter_all", "Tümü")
                tint: Theme.txt
                active: developerBackend.categoryFilter === "all"
                onClicked: developerBackend.setCategoryFilter("all")
            }
            DevChip {
                label: appBackend.uiTrigger, appBackend.getTextWithDefault("dev_filter_blocked", "Engellenenler")
                tint: Theme.danger
                active: developerBackend.categoryFilter === "blocked"
                onClicked: developerBackend.setCategoryFilter("blocked")
            }
            DevChip {
                label: appBackend.uiTrigger, appBackend.getTextWithDefault("dev_filter_warnings", "Kapsam Uyarıları")
                tint: Theme.warn
                active: developerBackend.categoryFilter === "warnings"
                onClicked: developerBackend.setCategoryFilter("warnings")
            }
            DevChip {
                label: appBackend.uiTrigger, appBackend.getTextWithDefault("dev_filter_files", "Etkilenen Dosyalar")
                tint: Theme.accent
                active: developerBackend.categoryFilter === "files"
                onClicked: developerBackend.setCategoryFilter("files")
            }

            Item { Layout.fillWidth: true }

            Label {
                text: developerBackend.items.length + ""
                color: Theme.txtDim
                font.pixelSize: 12
            }
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.cardBorder }

        // Flat list rows (EditorPage / LogPage style)
        ListView {
            id: devPageList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: developerBackend.items
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            Label {
                anchors.centerIn: parent
                visible: devPageList.count === 0
                text: appBackend.uiTrigger, appBackend.getTextWithDefault(
                    "dev_empty_state",
                    "Gösterilecek tanılama kaydı yok. Bir proje seçip çeviri çalıştırdıktan sonra burada listelenir."
                )
                color: Theme.txtDim
                font.pixelSize: 13
                horizontalAlignment: Text.AlignHCenter
                width: Math.min(parent.width - 40, 460)
                wrapMode: Text.WordWrap
            }

            delegate: Item {
                id: devPageRowItem
                width: devPageList.width
                height: devPageRowCol.implicitHeight + 16

                Rectangle {
                    anchors.fill: parent
                    color: devPageRowMa.containsMouse ? Theme.cardHover : "transparent"
                }

                MouseArea {
                    id: devPageRowMa
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.NoButton
                }

                ColumnLayout {
                    id: devPageRowCol
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: 6
                    anchors.rightMargin: 12
                    spacing: 4

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        Rectangle {
                            radius: 4
                            color: modelData.category === "blocked" ? Theme.alpha(Theme.danger, 0.16)
                                 : (modelData.category === "warnings" ? Theme.alpha(Theme.warn, 0.16) : Theme.alpha(Theme.accent, 0.14))
                            implicitWidth: devPageBadgeLbl.implicitWidth + 12
                            implicitHeight: 20
                            Label {
                                id: devPageBadgeLbl
                                anchors.centerIn: parent
                                text: modelData.badge
                                color: modelData.category === "blocked" ? Theme.danger
                                     : (modelData.category === "warnings" ? Theme.warn : Theme.accent)
                                font.pixelSize: 11
                                font.bold: true
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            text: modelData.title
                            color: Theme.txt
                            font.pixelSize: 13
                            font.bold: true
                            elide: Text.ElideRight
                        }

                        DevActionButton {
                            visible: (modelData.fileRel || modelData.editorQuery || "").length > 0
                            emphasized: true
                            tint: Theme.accent
                            glyph: Icons.languages
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("dev_open_in_editor", "Editörde Aç")
                            onClicked: {
                                editorBackend.focusEntry(
                                    developerBackend.language,
                                    modelData.editorQuery || "",
                                    modelData.fileRel || ""
                                )
                                navIndex = 5
                            }
                        }

                        DevActionButton {
                            visible: (modelData.filePath || "").length > 0
                            glyph: Icons.squarePen
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("dev_open_external_editor", "Harici Editörde Aç")
                            onClicked: developerBackend.openInExternalEditor(modelData.filePath)
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        visible: (modelData.detail || "").length > 0
                        text: modelData.detail || ""
                        color: Theme.txt2
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }

                    Label {
                        Layout.fillWidth: true
                        visible: (modelData.filePath || "").length > 0
                        text: (modelData.filePath || "") + (modelData.line > 0 ? (":" + modelData.line) : "")
                        color: Theme.txtDim
                        font.pixelSize: 11
                        elide: Text.ElideMiddle
                    }
                }

                Rectangle {
                    anchors.bottom: parent.bottom
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 1
                    color: Theme.cardBorder
                }
            }
        }
    }
}
