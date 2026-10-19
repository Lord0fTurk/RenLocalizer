// Translation editor page: browse and hand-edit game/tl/<language>/*.rpy.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

Item {
    id: page

    // The main window; colors come from its palette.
    property string pendingLanguage: ""

    function t(key, fallback) {
        return appBackend.uiTrigger, appBackend.getTextWithDefault(key, fallback)
    }

    // Push the text in the translation box into the store before anything
    // that changes the selection or writes files.
    function commitPending() {
        if (!editorBackend.selected || editorBackend.selected.id === undefined || editorBackend.locked)
            return
        if (transArea.text !== (editorBackend.selected.translated || ""))
            editorBackend.applyEdit(transArea.text)
    }

    // Warning for the text being typed; the row itself is updated when the
    // edit is committed (moving to another line, saving, filtering...).
    property string liveProblem: ""

    // Ctrl+Enter: keep the edit and move to the next line (next page at the end).
    function selectNext() {
        commitPending()
        var rows = editorBackend.rows
        var id = editorBackend.selected.id
        for (var i = 0; i < rows.length; i++) {
            if (rows[i].id !== id)
                continue
            if (i + 1 < rows.length) {
                editorBackend.select(rows[i + 1].id)
                rowList.positionViewAtIndex(i + 1, ListView.Contain)
            } else if (editorBackend.page < editorBackend.pageCount) {
                editorBackend.setPage(editorBackend.page + 1)
                rowList.positionViewAtBeginning()
            }
            break
        }
        transArea.forceActiveFocus()
        transArea.cursorPosition = transArea.length
    }

    function openLanguage(name) {
        if (!name || name === editorBackend.language && editorBackend.loaded)
            return
        commitPending()
        if (editorBackend.hasUnsavedChanges) {
            pendingLanguage = name
            unsavedDialog.open()
            return
        }
        editorBackend.loadLanguage(name)
    }

    function statusColor(row) {
        if (row.problem) return Theme.warn
        if (row.modified) return Theme.accent
        if (row.status === "translated") return Theme.success
        return Theme.txtDim
    }

    function start() {
        editorBackend.refreshLanguages()
        if (!editorBackend.loaded) {
            var lang = editorBackend.preferredLanguage()
            if (lang) editorBackend.loadLanguage(lang)
        }
    }

    onVisibleChanged: if (visible) start()

    Shortcut {
        sequences: ["Ctrl+S"]
        enabled: page.visible
        onActivated: { page.commitPending(); editorBackend.save() }
    }

    Connections {
        target: editorBackend
        function onSelectedChanged() {
            transArea.text = editorBackend.selected.translated || ""
            page.liveProblem = editorBackend.selected.problemText || ""
        }
    }

    Timer {
        id: liveCheckTimer
        interval: 300
        onTriggered: page.liveProblem = editorBackend.selected.id === undefined ? "" : editorBackend.problemFor(transArea.text)
    }

    component Chip: Rectangle {
        property string label
        property color tint
        property bool active: false
        signal clicked()
        implicitHeight: 28
        implicitWidth: chipText.implicitWidth + 22
        radius: 14
        color: active ? Theme.alpha(tint, 0.22) : Theme.alpha(tint, 0.08)
        border.color: Theme.alpha(tint, active ? 0.8 : 0.3)
        Label {
            id: chipText
            anchors.centerIn: parent
            text: parent.label
            color: parent.tint
            font.pixelSize: 12
            font.bold: parent.active
        }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: parent.clicked() }
    }

    // Same look as the app's other buttons (e.g. the Glossary toolbar):
    // emphasised buttons get a coloured border and label, the rest stay neutral.
    component ActionButton: Button {
        id: actionButton
        property color tint: Theme.accent
        property bool emphasized: true
        property string glyph: ""
        implicitHeight: 34
        // Material adds 6px insets above and below; the app's buttons use none.
        topInset: 0; bottomInset: 0
        leftPadding: 12; rightPadding: 12
        opacity: enabled ? 1.0 : 0.5
        background: Rectangle {
            radius: 8
            color: actionButton.down ? Theme.cardHover : (actionButton.hovered && actionButton.enabled ? Theme.cardHover : Theme.input)
            border.color: actionButton.emphasized ? actionButton.tint
                        : (actionButton.hovered && actionButton.enabled ? Theme.accent : Theme.cardBorder)
            border.width: 1
            Behavior on border.color { ColorAnimation { duration: 150 } }
        }
        contentItem: IconLabel {
            glyph: actionButton.glyph
            text: actionButton.text
            color: actionButton.emphasized ? actionButton.tint : Theme.txt
            font.pixelSize: 11
            font.bold: actionButton.emphasized
        }
    }

    // Combo box in the app's style (see the Toolbox language list in Main.qml).
    component ThemedCombo: ComboBox {
        id: combo
        implicitHeight: 36
        topInset: 0; bottomInset: 0
        font.pixelSize: 12
        background: Rectangle {
            radius: 8
            color: Theme.input
            border.color: combo.hovered || combo.visualFocus ? Theme.accent : Theme.cardBorder
            border.width: 1
            Behavior on border.color { ColorAnimation { duration: 150 } }
        }
        contentItem: Label {
            leftPadding: 12; rightPadding: 30
            text: combo.displayText
            color: combo.enabled ? Theme.txt : Theme.txtDim
            font.pixelSize: 12
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }
        delegate: ItemDelegate {
            width: combo.width
            contentItem: Label {
                text: modelData
                color: combo.highlightedIndex === index ? Theme.accent : Theme.txt
                font.pixelSize: 12; leftPadding: 12; elide: Text.ElideRight
            }
            background: Rectangle { color: hovered ? Theme.alpha(Theme.accent, 0.12) : "transparent" }
        }
        popup: Popup {
            y: combo.height + 4
            width: combo.width
            implicitHeight: Math.min(contentItem.implicitHeight + 8, 320)
            padding: 4
            contentItem: ListView {
                clip: true
                implicitHeight: contentHeight
                model: combo.delegateModel
                currentIndex: combo.highlightedIndex
                ScrollBar.vertical: ScrollBar {}
            }
            background: Rectangle { color: Theme.card; radius: 8; border.color: Theme.cardBorder; border.width: 1 }
        }
    }

    // Single-line input like the Glossary search box.
    component ThemedInput: Rectangle {
        id: inputBox
        property alias text: inputField.text
        property string placeholder: ""
        property string icon: ""
        implicitHeight: 34
        radius: 8
        color: Theme.input
        border.color: inputField.activeFocus ? Theme.accent : Theme.cardBorder
        border.width: 1
        Behavior on border.color { ColorAnimation { duration: 150 } }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10; anchors.rightMargin: 10
            spacing: 8
            Icon { visible: inputBox.icon.length > 0; glyph: inputBox.icon; size: 14; color: Theme.txtDim }
            TextInput {
                id: inputField
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
                    text: inputBox.placeholder
                    color: Theme.txtDim
                    font.pixelSize: 12
                    elide: Text.ElideRight
                    visible: !inputField.text && !inputField.activeFocus
                }
            }
            Label {
                visible: inputField.text.length > 0
                text: "✕"; color: Theme.txtDim; font.pixelSize: 10
                MouseArea { anchors.fill: parent; anchors.margins: -4; cursorShape: Qt.PointingHandCursor; onClicked: inputField.text = "" }
            }
        }
    }

    PageHeader {
        id: editorHeader
        anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
        maxContentWidth: 100000 // çalışma sayfası: tam genişlik
        glyph: Icons.squarePen
        title: page.t("editor_title", "Translation Editor")
        subtitle: editorBackend.gameName ? editorBackend.gameName : page.t("editor_subtitle", "Edit the translations in the game's tl folder line by line")
        actions: [
            ThemedCombo {
                id: langCombo
                objectName: "editorLanguageCombo"
                Layout.preferredWidth: 170
                model: editorBackend.languages
                enabled: !editorBackend.busy && count > 0
                currentIndex: Math.max(0, editorBackend.languages.indexOf(editorBackend.language))
                onActivated: page.openLanguage(currentText)
            },
            ActionButton {
                emphasized: false
                glyph: Icons.refreshCw
                text: page.t("editor_reload", "Reload")
                enabled: !editorBackend.busy
                onClicked: { page.commitPending(); page.start(); if (editorBackend.loaded) editorBackend.reload() }
            },
            ActionButton {
                tint: Theme.success
                glyph: Icons.save
                text: page.t("editor_save", "Save") + (editorBackend.stats.modified ? " (" + editorBackend.stats.modified + ")" : "")
                enabled: editorBackend.loaded && !editorBackend.busy && !editorBackend.locked
                onClicked: { page.commitPending(); editorBackend.save() }
            }
        ]
    }

    ColumnLayout {
        anchors.top: editorHeader.bottom; anchors.topMargin: 14
        anchors.bottom: parent.bottom; anchors.bottomMargin: 14
        anchors.horizontalCenter: parent.horizontalCenter
        width: editorHeader.contentWidth
        spacing: 10

        // ── Notices ──────────────────────────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            visible: editorBackend.locked
            implicitHeight: 34; radius: 8
            color: Theme.warnDim; border.color: Theme.warn
            IconLabel {
                anchors.centerIn: parent
                glyph: Icons.lock
                text: page.t("editor_locked", "A translation is running; the editor is read-only until it finishes.")
                color: Theme.warn; font.pixelSize: 12
            }
        }
        // Empty state, styled like the glossary's
        Rectangle {
            Layout.fillWidth: true
            Layout.topMargin: 6
            Layout.preferredHeight: 180
            visible: !editorBackend.busy && editorBackend.languages.length === 0
            radius: 14; color: Theme.card; border.color: Theme.cardBorder; border.width: 1
            ColumnLayout {
                anchors.centerIn: parent
                width: parent.width - 48
                spacing: 10
                Icon { glyph: Icons.squarePen; size: 36; color: Theme.txtDim; Layout.alignment: Qt.AlignHCenter }
                Label {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    text: page.t("editor_no_languages", "No tl folder found for the selected game. Select a game and run a translation first.")
                    color: Theme.txt2; font.pixelSize: 13; font.bold: true; wrapMode: Text.WordWrap
                }
            }
        }
        BusyIndicator {
            Layout.alignment: Qt.AlignHCenter
            visible: editorBackend.busy && !editorBackend.loaded
            running: visible
        }
        // The row list is the only item that takes the spare height; while it
        // is hidden this keeps the header and the notices at the top.
        Item {
            Layout.fillHeight: true
            visible: !editorBackend.loaded
        }

        // ── Stats and filters ────────────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            visible: editorBackend.loaded
            spacing: 8
            Chip {
                tint: Theme.txt2
                label: page.t("editor_status_all", "All") + "  " + (editorBackend.stats.total || 0)
                active: editorBackend.statusFilter === "all"
                onClicked: { page.commitPending(); editorBackend.setStatusFilter("all") }
            }
            Chip {
                tint: Theme.txtDim
                label: page.t("editor_status_untranslated", "Untranslated") + "  " + ((editorBackend.stats.empty || 0) + (editorBackend.stats.source_copy || 0))
                active: editorBackend.statusFilter === "untranslated"
                onClicked: { page.commitPending(); editorBackend.setStatusFilter("untranslated") }
            }
            Chip {
                tint: Theme.success
                label: page.t("editor_status_translated", "Translated") + "  " + Math.max(0, (editorBackend.stats.total || 0) - (editorBackend.stats.empty || 0) - (editorBackend.stats.source_copy || 0))
                active: editorBackend.statusFilter === "translated"
                onClicked: { page.commitPending(); editorBackend.setStatusFilter("translated") }
            }
            Chip {
                tint: Theme.accent
                label: page.t("editor_status_modified", "Unsaved") + "  " + (editorBackend.stats.modified || 0)
                active: editorBackend.statusFilter === "modified"
                onClicked: { page.commitPending(); editorBackend.setStatusFilter("modified") }
            }
            Chip {
                tint: Theme.warn
                label: page.t("editor_status_warnings", "Warnings") + "  " + (editorBackend.stats.warnings || 0)
                active: editorBackend.statusFilter === "warnings"
                onClicked: { page.commitPending(); editorBackend.setStatusFilter("warnings") }
            }
            Item { Layout.fillWidth: true }
        }

        RowLayout {
            Layout.fillWidth: true
            visible: editorBackend.loaded
            spacing: 8
            ThemedInput {
                id: searchField
                Layout.fillWidth: true
                Layout.preferredHeight: 36
                icon: Icons.search
                placeholder: page.t("editor_search_placeholder", "Search original, translation or speaker")
                onTextChanged: searchTimer.restart()
                Timer {
                    id: searchTimer
                    interval: 250
                    onTriggered: { page.commitPending(); editorBackend.setSearch(searchField.text) }
                }
            }
            ThemedCombo {
                id: fileCombo
                Layout.preferredWidth: 200
                model: [page.t("editor_all_files", "All files")].concat(editorBackend.files)
                currentIndex: editorBackend.fileFilter === "all" ? 0 : Math.max(0, editorBackend.files.indexOf(editorBackend.fileFilter) + 1)
                onActivated: function(index) {
                    page.commitPending()
                    editorBackend.setFileFilter(index === 0 ? "all" : editorBackend.files[index - 1])
                }
            }
            ThemedCombo {
                id: kindCombo
                Layout.preferredWidth: 150
                readonly property var keys: ["all", "dialogue", "string"]
                model: [page.t("editor_kind_all", "All types"), page.t("editor_kind_dialogue", "Dialogue"), page.t("editor_kind_string", "Interface text")]
                currentIndex: Math.max(0, keys.indexOf(editorBackend.kindFilter))
                onActivated: function(index) { page.commitPending(); editorBackend.setKindFilter(keys[index]) }
            }
            ActionButton {
                emphasized: false
                Layout.preferredHeight: 36
                glyph: Icons.replace
                text: page.t("editor_replace", "Replace")
                enabled: !editorBackend.locked
                onClicked: { page.commitPending(); replacePopup.open() }
            }
        }

        // ── Line list ────────────────────────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 160
            visible: editorBackend.loaded
            radius: 10
            color: Theme.card
            border.color: Theme.cardBorder

            ListView {
                id: rowList
                anchors.fill: parent
                anchors.margins: 4
                clip: true
                model: editorBackend.rows
                ScrollBar.vertical: ScrollBar {}
                delegate: Rectangle {
                    width: rowList.width
                    height: 50
                    radius: 6
                    readonly property bool current: editorBackend.selected.id === modelData.id
                    color: current ? Theme.alpha(Theme.accent, 0.10) : (rowMouse.containsMouse ? Theme.cardHover : "transparent")
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 10; anchors.rightMargin: 10
                        spacing: 10
                        Rectangle { width: 8; height: 8; radius: 4; color: page.statusColor(modelData) }
                        Label {
                            Layout.preferredWidth: 90
                            text: modelData.speaker || (modelData.kind === "string" ? "UI" : "—")
                            color: Theme.txt2; font.pixelSize: 12; font.bold: true; elide: Text.ElideRight
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Label {
                                Layout.fillWidth: true
                                text: modelData.original
                                color: Theme.txt2; font.pixelSize: 12; elide: Text.ElideRight; textFormat: Text.PlainText
                            }
                            Label {
                                Layout.fillWidth: true
                                text: modelData.translated || "—"
                                color: modelData.status === "translated" ? Theme.txt : Theme.txtDim
                                font.pixelSize: 13; elide: Text.ElideRight; textFormat: Text.PlainText
                            }
                        }
                        Label {
                            text: modelData.file + ":" + modelData.line
                            color: Theme.txtDim; font.pixelSize: 11
                        }
                    }
                    MouseArea {
                        id: rowMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            var target = index
                            page.commitPending()
                            editorBackend.select(modelData.id)
                            rowList.positionViewAtIndex(target, ListView.Contain)
                        }
                    }
                }
                Label {
                    anchors.centerIn: parent
                    visible: rowList.count === 0
                    text: page.t("editor_empty", "No lines match the filters.")
                    color: Theme.txtDim
                }
            }
        }

        // ── Paging ───────────────────────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            visible: editorBackend.loaded
            spacing: 8
            Label {
                text: editorBackend.totalCount + " " + page.t("editor_lines", "lines")
                color: Theme.txtDim; font.pixelSize: 12
            }
            Item { Layout.fillWidth: true }
            ActionButton {
                emphasized: false
                text: "◀"; implicitWidth: 40
                enabled: editorBackend.page > 1
                onClicked: { page.commitPending(); editorBackend.setPage(editorBackend.page - 1) }
            }
            Label {
                text: editorBackend.page + " / " + editorBackend.pageCount
                color: Theme.txt2; font.pixelSize: 12
            }
            ActionButton {
                emphasized: false
                text: "▶"; implicitWidth: 40
                enabled: editorBackend.page < editorBackend.pageCount
                onClicked: { page.commitPending(); editorBackend.setPage(editorBackend.page + 1) }
            }
        }

        // ── Detail ───────────────────────────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            // 290 when there is room; on short windows it gives way down to 200
            // instead of pushing its buttons out of the page.
            Layout.fillHeight: true
            Layout.preferredHeight: 290
            Layout.maximumHeight: 290
            Layout.minimumHeight: 200
            visible: editorBackend.loaded && editorBackend.selected.id !== undefined
            radius: 10
            color: Theme.card
            border.color: page.liveProblem ? Theme.warn : Theme.cardBorder

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Label {
                        text: editorBackend.selected.speaker || (editorBackend.selected.kind === "string" ? page.t("editor_kind_string", "Interface text") : page.t("editor_narrator", "Narrator"))
                        color: Theme.accent; font.bold: true; font.pixelSize: 13
                    }
                    Label {
                        Layout.fillWidth: true
                        text: (editorBackend.selected.file || "") + ":" + (editorBackend.selected.line || "")
                              + (editorBackend.selected.sourceRef ? "   ←  " + editorBackend.selected.sourceRef : "")
                        color: Theme.txtDim; font.pixelSize: 11; elide: Text.ElideRight
                    }
                }
                Label {
                    Layout.fillWidth: true
                    visible: !!page.liveProblem
                    text: "⚠ " + page.liveProblem + " " + page.t("editor_problem_hint", "The next translation run would replace this line.")
                    color: Theme.warn; font.pixelSize: 12; wrapMode: Text.WordWrap
                }
                Label {
                    Layout.fillWidth: true
                    visible: !!editorBackend.selected.prevText
                    text: "↑ " + (editorBackend.selected.prevSpeaker ? editorBackend.selected.prevSpeaker + ": " : "") + (editorBackend.selected.prevText || "")
                    color: Theme.txtDim; font.pixelSize: 11; elide: Text.ElideRight; textFormat: Text.PlainText
                }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 10
                    TextArea {
                            Layout.fillWidth: true; Layout.fillHeight: true
                            Layout.preferredWidth: 1
                            clip: true
                            readOnly: true
                            selectByMouse: true
                            wrapMode: TextEdit.Wrap
                            textFormat: TextEdit.PlainText
                            topInset: 0; bottomInset: 0; padding: 10; topPadding: 10
                            text: editorBackend.selected.original || ""
                            color: Theme.txt2
                            background: Rectangle { radius: 8; color: Theme.input; border.color: Theme.cardBorder }
                    }
                    TextArea {
                            id: transArea
                            Layout.fillWidth: true; Layout.fillHeight: true
                            Layout.preferredWidth: 1
                            clip: true
                            objectName: "editorTranslationArea"
                            readOnly: editorBackend.locked
                            selectByMouse: true
                            wrapMode: TextEdit.Wrap
                            textFormat: TextEdit.PlainText
                            topInset: 0; bottomInset: 0; padding: 10; topPadding: 10
                            color: Theme.txt
                            background: Rectangle { radius: 8; color: Theme.input; border.color: transArea.activeFocus ? Theme.accent : Theme.cardBorder }
                            onTextChanged: liveCheckTimer.restart()
                            Keys.onPressed: function(event) {
                                if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && (event.modifiers & Qt.ControlModifier)) {
                                    page.selectNext()
                                    event.accepted = true
                                }
                            }
                    }
                }
                Label {
                    Layout.fillWidth: true
                    visible: !!editorBackend.selected.nextText
                    text: "↓ " + (editorBackend.selected.nextSpeaker ? editorBackend.selected.nextSpeaker + ": " : "") + (editorBackend.selected.nextText || "")
                    color: Theme.txtDim; font.pixelSize: 11; elide: Text.ElideRight; textFormat: Text.PlainText
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Repeater {
                        model: editorBackend.selected.tokens || []
                        delegate: Chip {
                            tint: Theme.purple
                            label: modelData
                            onClicked: if (!editorBackend.locked) { transArea.insert(transArea.cursorPosition, modelData); transArea.forceActiveFocus() }
                        }
                    }
                    Item { Layout.fillWidth: true }
                    ActionButton {
                        emphasized: false
                        glyph: Icons.undo2
                        text: page.t("editor_revert", "Revert")
                        enabled: !editorBackend.locked && !!editorBackend.selected.modified
                        onClicked: editorBackend.revertSelected()
                    }
                    ActionButton {
                        tint: Theme.purple
                        glyph: Icons.sparkles
                        text: page.t("editor_suggest", "Suggest")
                        enabled: !editorBackend.locked && !editorBackend.busy
                        onClicked: { page.commitPending(); editorBackend.suggest() }
                    }
                    Label {
                        text: page.t("editor_next_hint", "Ctrl+Enter: next line")
                        color: Theme.txtDim; font.pixelSize: 11
                    }
                }
            }
        }
    }

    // ── Replace popup ────────────────────────────────────────────────
    Popup {
        id: replacePopup
        anchors.centerIn: parent
        width: 420
        modal: true
        padding: 16
        background: Rectangle { radius: 12; color: Theme.card; border.color: Theme.cardBorder }
        ColumnLayout {
            anchors.fill: parent
            spacing: 10
            Label { text: page.t("editor_replace", "Replace"); color: Theme.txt; font.bold: true; font.pixelSize: 16 }
            Label {
                Layout.fillWidth: true
                text: page.t("editor_replace_hint", "Only translations shown by the current filters change. Tags and [variables] are never touched.")
                color: Theme.txt2; font.pixelSize: 12; wrapMode: Text.WordWrap
            }
            ThemedInput { id: findField; Layout.fillWidth: true; placeholder: page.t("editor_find", "Find") }
            ThemedInput { id: replaceField; Layout.fillWidth: true; placeholder: page.t("editor_replace_with", "Replace with") }
            CheckBox { id: caseBox; text: page.t("editor_match_case", "Match case") }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton { emphasized: false; text: page.t("editor_cancel", "Cancel"); onClicked: replacePopup.close() }
                ActionButton {
                    text: page.t("editor_replace_apply", "Replace all")
                    enabled: findField.text.length > 0
                    onClicked: {
                        editorBackend.replaceAll(findField.text, replaceField.text, caseBox.checked)
                        replacePopup.close()
                    }
                }
            }
        }
    }

    // ── Unsaved changes when switching language ──────────────────────
    Dialog {
        id: unsavedDialog
        anchors.centerIn: parent
        modal: true
        title: page.t("editor_unsaved_title", "Unsaved changes")
        Label {
            text: page.t("editor_unsaved_switch", "Your unsaved edits will be lost if you open another language.")
            color: Theme.txt; wrapMode: Text.WordWrap
        }
        footer: DialogButtonBox {
            Button {
                text: page.t("editor_discard", "Discard")
                DialogButtonBox.buttonRole: DialogButtonBox.DestructiveRole
                onClicked: { unsavedDialog.close(); editorBackend.loadLanguage(page.pendingLanguage) }
            }
            Button {
                text: page.t("editor_cancel", "Cancel")
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
                onClicked: {
                    unsavedDialog.close()
                    langCombo.currentIndex = Math.max(0, editorBackend.languages.indexOf(editorBackend.language))
                }
            }
        }
    }
}
