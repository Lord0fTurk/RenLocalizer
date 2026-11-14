// Translate page: pick the game, the language pair and the engine, then run.
//
// Layout: a label rail with four rows (Game, Languages, Engine, Output) and a
// Run panel on the right. Below ~1000 px of page width the Run panel becomes a
// dock along the bottom. No cards: rows are separated by space and hairlines.
// The language pair is the one loud element; the accent colour appears only on
// the Translate button, the progress bar and focus.
//
// Names that are not defined in this file (root, navIndex, isTranslating,
// showToast(), the file dialogs, logModel, ...) belong to Main.qml and resolve
// through the component that instantiates this one.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs
import QtQuick.Window
import "../components"

Item {
    id: pageDashboard
    // Used by Main.qml (backend signal handlers, file dialogs, drag & drop).
    property alias logListView: logListView
    property alias progressBar: progressBar
    property alias progressLabel: progressLabel
    property alias projectPathField: projectPathField
    property alias sourceLangCombo: sourceLangCombo
    property alias targetLangCombo: targetLangCombo
    Layout.fillWidth: true
    Layout.fillHeight: true

    readonly property bool wide: width >= 1000
    readonly property var info: appBackend.projectInfo
    readonly property bool hasPath: projectPathField.text.trim().length > 0
    readonly property bool hasProject: hasPath && !!info && !!info.ok
    readonly property bool finished: statsVisible && !isTranslating
    // A stopped run of this game and language can be continued (core/run_state.py).
    readonly property var resume: appBackend.resumeInfo
    readonly property bool canResume: !isTranslating && !!resume && resume.available === true
    readonly property var estimate: appBackend.estimate
    readonly property bool hasEstimate: !isTranslating && !finished && !!estimate && !!estimate.state
    function estimateText() {
        if (!estimate || !estimate.state) return ""
        if (estimate.state === "computing")
            return appBackend.getTextWithDefault("dash_estimate_computing", "Counting lines...")
        var key = estimate.seconds > 0 ? "dash_estimate_time" : "dash_estimate_lines"
        var def = estimate.seconds > 0 ? "About {lines} lines to translate, {time}" : "About {lines} lines to translate"
        return appBackend.getTextWithDefault(key, def)
            .replace("{lines}", estimate.left).replace("{time}", estimate.duration)
    }
    function resumeText() {
        return appBackend.getTextWithDefault("dash_resume_progress", "{done} of {total} lines done")
            .replace("{done}", resume.done).replace("{total}", resume.total)
    }

    // Main.qml writes the run's progress here; the panel and the dock both read it.
    QtObject { id: progressBar; property real value: 0.0 }
    QtObject { id: progressLabel; property string text: "" }

    // The line being translated (speaker, original, translation), once per batch.
    property string liveSpeaker: ""
    property string liveOriginal: ""
    property string liveTranslation: ""
    Connections {
        target: appBackend
        function onLineTranslated(speaker, original, translation) {
            pageDashboard.liveSpeaker = speaker
            pageDashboard.liveOriginal = original
            pageDashboard.liveTranslation = translation
        }
        function onTranslationStarted() {
            pageDashboard.liveSpeaker = ""; pageDashboard.liveOriginal = ""; pageDashboard.liveTranslation = ""
        }
    }

    function startOrStop() {
        if (isTranslating) {
            appBackend.stopTranslation()
            return
        }
        if (!pageDashboard.hasPath) {
            projectPathField.triggerShake()
            showToast(appBackend.getTextWithDefault("log_select_game", "Please select a game folder or EXE."), "warning")
            return
        }
        appBackend.startTranslation()
    }

    function outputFolder() {
        return "game/tl/" + (appBackend.getTargetLanguage() || "")
    }

    // ── small building blocks ────────────────────────────────────────────

    // A row of the form: its label sits on a rail at the left.
    component FieldRow: RowLayout {
        id: fieldRow
        property string label: ""
        default property alias content: fieldBody.data
        Layout.fillWidth: true
        spacing: 0
        Label {
            text: fieldRow.label
            color: Theme.txt2; font.pixelSize: 13
            Layout.preferredWidth: pageDashboard.wide ? 112 : 96
            Layout.alignment: Qt.AlignTop
            topPadding: 5
            elide: Text.ElideRight
        }
        ColumnLayout { id: fieldBody; Layout.fillWidth: true; spacing: 10 }
    }

    component Hairline: Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.cardBorder }

    // A quiet button: outline, no fill until hovered.
    component QuietButton: Button {
        id: quiet
        property string glyph: ""
        implicitHeight: 34
        topInset: 0; bottomInset: 0; leftInset: 0; rightInset: 0
        leftPadding: 12; rightPadding: 12; topPadding: 0; bottomPadding: 0
        opacity: enabled ? 1.0 : 0.45
        background: Rectangle {
            radius: 6
            color: quiet.down ? Theme.cardHover : (quiet.hovered ? Theme.surfaceSubtle : "transparent")
            border.color: quiet.visualFocus ? Theme.accent : Theme.borderControl
            border.width: 1
        }
        contentItem: IconLabel {
            glyph: quiet.glyph
            text: quiet.text
            color: Theme.txt; iconColor: Theme.txt2
            font.pixelSize: 13
        }
    }

    // Small text choices under a language ("Recent"-style shortcuts).
    component QuickPick: Label {
        property bool current: false
        signal picked()
        font.pixelSize: 12
        color: current ? Theme.txt : (pickHover.hovered ? Theme.txt : Theme.txtDim)
        font.weight: current ? Font.DemiBold : Font.Normal
        HoverHandler { id: pickHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: parent.picked() }
    }

    // The primary action. The only accent-filled element on the page.
    component RunButton: Button {
        id: run
        implicitHeight: 46
        topInset: 0; bottomInset: 0; leftInset: 0; rightInset: 0
        leftPadding: 0; rightPadding: 0; topPadding: 0; bottomPadding: 0
        enabled: !isTranslating || currentStage !== "idle"
        text: appBackend.uiTrigger, pageDashboard.canResume, isTranslating
            ? appBackend.getTextWithDefault("dash_stop", "Stop")
            : (pageDashboard.canResume
                ? appBackend.getTextWithDefault("dash_continue", "Continue")
                : appBackend.getTextWithDefault("dash_translate", "Translate"))
        onClicked: pageDashboard.startOrStop()
        background: Rectangle {
            radius: 7
            color: isTranslating ? (run.hovered ? Theme.surfaceSubtle : "transparent")
                                 : (run.down ? Theme.accentHover : (run.hovered ? Theme.accentHover : Theme.accent))
            border.color: isTranslating ? (run.hovered ? Theme.error : Theme.borderControl) : "transparent"
            border.width: 1
            opacity: (!isTranslating && !pageDashboard.hasPath) ? 0.45 : 1.0
            Behavior on color { ColorAnimation { duration: 120 } }
        }
        contentItem: IconLabel {
            glyph: isTranslating ? Icons.square : ""
            text: run.text
            color: isTranslating ? (run.hovered ? Theme.error : Theme.txt) : Theme.textOnAccent
            iconColor: color
            font.pixelSize: 16; font.weight: Font.DemiBold
        }
    }

    // Status line + progress, shared by the panel and the dock.
    component RunStatus: ColumnLayout {
        spacing: 0
        RowLayout {
            Layout.fillWidth: true
            Label {
                text: appBackend.uiTrigger, getStageDisplayText(currentStage)
                font.pixelSize: 16; font.weight: Font.DemiBold
                color: currentStage === "error" ? Theme.error : Theme.txt
                Layout.fillWidth: true; elide: Text.ElideRight
            }
            Label {
                visible: isTranslating
                text: Math.round(progressBar.value * 100) + "%"
                font.pixelSize: 16; font.weight: Font.DemiBold; color: Theme.txt
            }
        }
        Rectangle {
            visible: isTranslating
            Layout.topMargin: 12; Layout.fillWidth: true
            implicitHeight: 4; radius: 2; color: Theme.cardBorder
            Rectangle {
                width: parent.width * Math.max(0, Math.min(1, progressBar.value))
                height: parent.height; radius: 2; color: Theme.accent
                Behavior on width { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
            }
        }
        Label {
            visible: isTranslating && text.length > 0
            Layout.topMargin: 8; Layout.fillWidth: true
            text: progressLabel.text
            color: Theme.txt2; font.pixelSize: 12; elide: Text.ElideRight
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ── setup column ─────────────────────────────────────────────────
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            ScrollView {
                id: setupScroll
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                contentWidth: availableWidth
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                ColumnLayout {
                    id: setupCol
                    x: pageDashboard.wide ? 44 : 28
                    width: Math.min(setupScroll.availableWidth - 2 * x, 780)
                    spacing: pageDashboard.wide ? 24 : 18

                    Item { implicitHeight: pageDashboard.wide ? 14 : 6 }

                    // ── Game ─────────────────────────────────────────────
                    Label {
                        visible: !pageDashboard.hasProject
                        Layout.fillWidth: true
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("dash_empty_title", "Which game do you want to translate?")
                        font.pixelSize: 24; font.weight: Font.DemiBold; color: Theme.txt
                        wrapMode: Text.WordWrap
                    }

                    FieldRow {
                        label: appBackend.uiTrigger, appBackend.getTextWithDefault("dash_game", "Game")

                        Label {
                            visible: pageDashboard.hasProject
                            Layout.fillWidth: true
                            text: pageDashboard.hasProject
                                ? (pageDashboard.info.name || "") + (pageDashboard.info.game_version ? "  " + pageDashboard.info.game_version : "")
                                : ""
                            font.pixelSize: 20; font.weight: Font.DemiBold; color: Theme.txt
                            elide: Text.ElideRight
                        }
                        Label {
                            visible: !pageDashboard.hasProject
                            Layout.fillWidth: true
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("dash_drop_hint", "Drop the game folder or its .exe here, or paste the path")
                            color: Theme.txt2; font.pixelSize: 13; wrapMode: Text.WordWrap
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            TextField {
                                id: projectPathField
                                Layout.fillWidth: true
                                implicitHeight: 34
                                topPadding: 0; bottomPadding: 0; leftPadding: 12; rightPadding: 12
                                verticalAlignment: TextInput.AlignVCenter
                                font.pixelSize: 13; color: Theme.txt
                                selectByMouse: true
                                enabled: !isTranslating
                                property bool hasError: false
                                onTextChanged: if (hasError) hasError = false
                                onEditingFinished: if (text.length > 0) appBackend.setProjectPath(text)

                                transform: Translate { id: pathFieldShake; x: 0 }
                                SequentialAnimation {
                                    id: shakeFieldAnim
                                    alwaysRunToEnd: true
                                    onStarted: projectPathField.hasError = true
                                    NumberAnimation { target: pathFieldShake; property: "x"; to: -8; duration: 40; easing.type: Easing.OutQuad }
                                    NumberAnimation { target: pathFieldShake; property: "x"; to: 8;  duration: 60; easing.type: Easing.InOutQuad }
                                    NumberAnimation { target: pathFieldShake; property: "x"; to: -6; duration: 50; easing.type: Easing.InOutQuad }
                                    NumberAnimation { target: pathFieldShake; property: "x"; to: 5;  duration: 45; easing.type: Easing.InOutQuad }
                                    NumberAnimation { target: pathFieldShake; property: "x"; to: 0;  duration: 40; easing.type: Easing.OutQuad }
                                    PauseAnimation { duration: 1200 }
                                    PropertyAction { target: projectPathField; property: "hasError"; value: false }
                                }
                                function triggerShake() { shakeFieldAnim.restart() }

                                background: Rectangle {
                                    radius: 6
                                    color: Theme.input
                                    border.color: projectPathField.hasError ? Theme.error
                                        : (projectPathField.activeFocus ? Theme.accent : Theme.borderControl)
                                    border.width: 1
                                }
                                Label {
                                    anchors.left: parent.left; anchors.leftMargin: 12
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("input_placeholder", "C:/Games/MyGame/MyGame.exe...")
                                    color: Theme.txtDim; font.pixelSize: 13
                                    visible: projectPathField.text.length === 0 && !projectPathField.activeFocus
                                }
                            }
                            QuietButton {
                                id: btnBrowseFolder
                                glyph: Icons.folderOpen
                                enabled: !isTranslating
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("browse_folder", "Folder")
                                onClicked: folderDialog.open()
                            }
                            QuietButton {
                                id: btnBrowseExe
                                enabled: !isTranslating
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("browse_exe", "EXE File")
                                onClicked: fileDialog.open()
                            }
                            QuietButton {
                                id: btnRecentProjects
                                visible: pageDashboard.hasProject
                                enabled: !isTranslating && appBackend.recentProjects.length > 0
                                glyph: Icons.history
                                implicitWidth: 34
                                leftPadding: 0; rightPadding: 0
                                ToolTip.visible: hovered
                                ToolTip.delay: 300
                                ToolTip.text: appBackend.uiTrigger, appBackend.getTextWithDefault("recent_projects", "Recent projects")
                                onClicked: recentPopup.open()

                                Popup {
                                    id: recentPopup
                                    y: parent.height + 6
                                    x: parent.width - width
                                    width: Math.min(520, root.width - 300)
                                    padding: 6
                                    background: Rectangle { color: Theme.card; radius: 8; border.color: Theme.cardBorder; border.width: 1 }
                                    contentItem: ColumnLayout {
                                        spacing: 2
                                        Repeater {
                                            model: appBackend.recentProjects
                                            delegate: ItemDelegate {
                                                id: recentRow
                                                Layout.fillWidth: true
                                                implicitHeight: 46
                                                onClicked: {
                                                    recentPopup.close()
                                                    appBackend.setProjectPath(modelData)
                                                    projectPathField.text = modelData
                                                }
                                                background: Rectangle { radius: 6; color: recentRow.hovered ? Theme.cardHover : "transparent" }
                                                contentItem: ColumnLayout {
                                                    spacing: 1
                                                    Label { Layout.fillWidth: true; text: root.projectLabel(modelData); color: Theme.txt; font.pixelSize: 13; font.weight: Font.DemiBold; elide: Text.ElideRight }
                                                    Label { Layout.fillWidth: true; text: modelData; color: Theme.txtDim; font.pixelSize: 11; elide: Text.ElideMiddle }
                                                }
                                            }
                                        }
                                        Rectangle { Layout.fillWidth: true; Layout.topMargin: 4; implicitHeight: 1; color: Theme.cardBorder }
                                        ItemDelegate {
                                            id: clearRecentRow
                                            Layout.fillWidth: true
                                            implicitHeight: 34
                                            onClicked: { recentPopup.close(); appBackend.clearRecentProjects() }
                                            background: Rectangle { radius: 6; color: clearRecentRow.hovered ? Theme.dangerTint : "transparent" }
                                            contentItem: IconLabel {
                                                alignment: Qt.AlignLeft; leftPadding: 4
                                                glyph: Icons.trash2
                                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("recent_projects_clear", "Clear list")
                                                color: Theme.error; font.pixelSize: 12
                                            }
                                        }
                                    }
                                }
                            }
                            QuietButton {
                                visible: pageDashboard.hasProject && !!pageDashboard.info.launcher
                                glyph: Icons.play
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("completion_launch_game", "Launch Game")
                                onClicked: appBackend.launchGame()
                            }
                        }

                        // Facts about the selected game.
                        Flow {
                            id: factsFlow
                            Layout.fillWidth: true
                            spacing: 20
                            visible: pageDashboard.hasProject && !pageDashboard.info.tl_mode
                            function facts() {
                                var i = pageDashboard.info, out = []
                                if (!i || !i.ok || i.tl_mode) return out
                                if (i.renpy_version) out.push(["Ren'Py", i.renpy_version])
                                if (i.rpy) out.push([".rpy", String(i.rpy)])
                                if (i.rpyc) out.push([".rpyc", String(i.rpyc)])
                                if (i.rpa) out.push([".rpa", String(i.rpa)])
                                if (i.tl_languages && i.tl_languages.length)
                                    out.push([appBackend.getTextWithDefault("project_existing_translations", "Existing translations"), i.tl_languages.join(", ")])
                                return out
                            }
                            Repeater {
                                model: appBackend.uiTrigger, factsFlow.facts()
                                Row {
                                    spacing: 6
                                    Label { text: modelData[0]; color: Theme.txtDim; font.pixelSize: 12 }
                                    Label { text: modelData[1]; color: Theme.txt2; font.pixelSize: 12 }
                                }
                            }
                        }

                        // Anything that would stop the run, in the pipeline's own words.
                        Repeater {
                            model: pageDashboard.hasPath && !!pageDashboard.info && !!pageDashboard.info.path ? (pageDashboard.info.notices || []) : []
                            delegate: RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                Icon {
                                    glyph: modelData.level === "warn" ? Icons.triangleAlert : Icons.info
                                    size: 14
                                    color: modelData.level === "warn" ? Theme.warn : Theme.txt2
                                    Layout.alignment: Qt.AlignTop
                                    Layout.topMargin: 1
                                }
                                Label {
                                    Layout.fillWidth: true
                                    wrapMode: Text.WordWrap
                                    text: appBackend.uiTrigger, root.stripLeadingEmoji(appBackend.getTextWithDefault(modelData.key, modelData.default))
                                    color: modelData.level === "warn" ? Theme.warn : Theme.txt2
                                    font.pixelSize: 12
                                }
                            }
                        }
                    }

                    // Recent games, when nothing is loaded: the page is an invitation.
                    FieldRow {
                        visible: !pageDashboard.hasProject && appBackend.recentProjects.length > 0
                        label: appBackend.uiTrigger, appBackend.getTextWithDefault("recent_projects", "Recent projects")
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            Repeater {
                                model: appBackend.recentProjects
                                delegate: ItemDelegate {
                                    id: recentInline
                                    Layout.fillWidth: true
                                    implicitHeight: 44
                                    leftPadding: 0; rightPadding: 0
                                    onClicked: {
                                        appBackend.setProjectPath(modelData)
                                        projectPathField.text = modelData
                                    }
                                    background: Item {
                                        Rectangle { anchors.fill: parent; anchors.leftMargin: -8; anchors.rightMargin: -8; radius: 6; color: recentInline.hovered ? Theme.cardHover : "transparent" }
                                        Rectangle { visible: index > 0; width: parent.width; height: 1; color: Theme.cardBorder }
                                    }
                                    contentItem: RowLayout {
                                        spacing: 16
                                        Label { text: root.projectLabel(modelData); color: Theme.txt; font.pixelSize: 13; font.weight: Font.DemiBold; Layout.preferredWidth: 200; elide: Text.ElideRight }
                                        Label { text: modelData; color: Theme.txt2; font.pixelSize: 12; Layout.fillWidth: true; elide: Text.ElideMiddle }
                                    }
                                }
                            }
                        }
                    }

                    Hairline {}

                    // ── Languages: the one loud thing on the page ─────────
                    FieldRow {
                        label: appBackend.uiTrigger, appBackend.getTextWithDefault("dash_languages", "Languages")
                        enabled: !isTranslating
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: pageDashboard.wide ? 18 : 12

                            ColumnLayout {
                                spacing: 2
                                ComboBox {
                                    id: sourceLangCombo
                                    implicitHeight: pageDashboard.wide ? 48 : 34; implicitWidth: contentItem.implicitWidth; padding: 0
                                    model: appBackend.getSourceLanguages()
                                    textRole: "name"; valueRole: "code"
                                    function syncSourceLanguage() {
                                        var src = appBackend.getSourceLanguage() || "auto"
                                        var idx = sourceLangCombo.indexOfValue(src)
                                        if (idx >= 0) sourceLangCombo.currentIndex = idx
                                    }
                                    Component.onCompleted: syncSourceLanguage()
                                    Connections {
                                        target: appBackend
                                        function onUiTriggerChanged() { sourceLangCombo.syncSourceLanguage() }
                                    }
                                    onActivated: appBackend.setSourceLanguage(currentValue)
                                    background: Item {}
                                    // The language name is the page's headline: its own name, large.
                                    contentItem: RowLayout {
                                        spacing: 8
                                        Label {
                                            readonly property string full: sourceLangCombo.displayText !== "" ? sourceLangCombo.displayText : appBackend.getTextWithDefault("auto_detect", "Auto-detect")
                                            text: full.indexOf(" (") > 0 ? full.substring(0, full.indexOf(" (")) : full
                                            color: sourceLangCombo.enabled ? Theme.txt : Theme.txt2
                                            font.pixelSize: pageDashboard.wide ? 36 : 20
                                            font.weight: Font.DemiBold
                                            elide: Text.ElideRight
                                            Layout.maximumWidth: pageDashboard.wide ? 300 : 220
                                        }
                                        Label {
                                            text: "\u25BE"
                                            color: sourceLangCombo.hovered || sourceLangCombo.activeFocus ? Theme.txt : Theme.txt2
                                            font.pixelSize: 20
                                            Layout.alignment: Qt.AlignBottom
                                            Layout.bottomMargin: pageDashboard.wide ? 6 : 2
                                        }
                                        Item { Layout.fillWidth: true }
                                    }
                                    indicator: Item {}
                                    delegate: ItemDelegate {
                                        width: sourceLangCombo.width
                                        contentItem: Label { text: modelData.name; color: sourceLangCombo.highlightedIndex === index ? Theme.accent : Theme.txt; font.pixelSize: 12; leftPadding: 14; elide: Text.ElideRight }
                                        background: Rectangle { color: hovered ? Theme.alpha(Theme.accent, 0.12) : "transparent"; Behavior on color { ColorAnimation { duration: 120 } } }
                                    }
                                    popup: Popup {
                                        id: sourceLangPopup
                                        y: sourceLangCombo.height + 4
                                        width: Math.min(520, Math.max(340, root.width - 48))
                                        height: Math.min(420, root.height - 180)
                                        padding: 10
                                        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

                                        property string searchFilter: ""
                                        property var allLanguages: []

                                        function refreshLanguages() {
                                            allLanguages = appBackend.getSourceLanguages() || []
                                        }

                                        function getFilteredList() {
                                            appBackend.uiTrigger
                                            var raw = allLanguages.length > 0 ? allLanguages : (appBackend.getSourceLanguages() || [])
                                            var q = searchFilter.trim().toLowerCase()
                                            if (!q) return raw
                                            var res = []
                                            for (var i = 0; i < raw.length; i++) {
                                                var item = raw[i]
                                                var nameStr = (item.name || "").toLowerCase()
                                                var codeStr = (item.code || "").toLowerCase()
                                                if (nameStr.indexOf(q) !== -1 || codeStr.indexOf(q) !== -1) {
                                                    res.push(item)
                                                }
                                            }
                                            return res
                                        }

                                        onAboutToShow: {
                                            refreshLanguages()
                                            searchFilter = ""
                                            sourceSearchInput.text = ""
                                            sourceSearchTimer.restart()
                                        }

                                        Timer {
                                            id: sourceSearchTimer
                                            interval: 60
                                            repeat: false
                                            onTriggered: sourceSearchInput.forceActiveFocus()
                                        }

                                        background: Rectangle {
                                            color: Theme.card
                                            radius: 12
                                            border.color: Theme.alpha(Theme.accent, 0.4)
                                            border.width: 1
                                        }

                                        contentItem: ColumnLayout {
                                            spacing: 8
                                            anchors.fill: parent

                                            // 1. Canlı Arama Çubuğu
                                            Rectangle {
                                                Layout.fillWidth: true; height: 36; radius: 8
                                                color: Theme.input
                                                border.color: sourceSearchInput.activeFocus ? Theme.accent : Theme.cardBorder
                                                border.width: 1

                                                RowLayout {
                                                    anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 8; spacing: 6
                                                    Icon { glyph: Icons.search; size: 14; color: Theme.txtDim }
                                                    TextInput {
                                                        id: sourceSearchInput
                                                        Layout.fillWidth: true
                                                        font.pixelSize: 12; color: Theme.txt
                                                        clip: true
                                                        Text {
                                                            anchors.fill: parent; verticalAlignment: Text.AlignVCenter
                                                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("lang_search_placeholder", "Dil veya kod ara... (örn: ja, tr, en)")
                                                            color: Theme.txtDim; font.pixelSize: 12
                                                            visible: !sourceSearchInput.text && !sourceSearchInput.activeFocus
                                                        }
                                                        onTextChanged: sourceLangPopup.searchFilter = text.trim().toLowerCase()
                                                        onAccepted: {
                                                            var list = sourceLangPopup.getFilteredList()
                                                            if (list.length > 0) {
                                                                appBackend.setSourceLanguage(list[0].code)
                                                                sourceLangCombo.syncSourceLanguage()
                                                                sourceLangPopup.close()
                                                            }
                                                        }
                                                    }
                                                    Button {
                                                        visible: sourceSearchInput.text.length > 0
                                                        width: 20; height: 20; text: "✕"
                                                        onClicked: { sourceSearchInput.text = ""; sourceLangPopup.searchFilter = "" }
                                                        background: Item {}
                                                        contentItem: Label { text: "✕"; color: Theme.txtDim; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                                    }
                                                }
                                            }

                                            // 2. İki Sütunlu Responsive Dil Izgarası
                                            GridView {
                                                id: sourceGridView
                                                Layout.fillWidth: true
                                                Layout.fillHeight: true
                                                clip: true
                                                cellWidth: width > 420 ? Math.floor(width / 2) : width
                                                cellHeight: 38
                                                model: sourceLangPopup.getFilteredList()
                                                ScrollBar.vertical: ScrollBar {}

                                                delegate: Rectangle {
                                                    width: sourceGridView.cellWidth - 4
                                                    height: 34
                                                    radius: 6
                                                    color: mouseAreaSrcGrid.containsMouse ? Theme.alpha(Theme.accent, 0.12) : (sourceLangCombo.currentValue === modelData.code ? Theme.alpha(Theme.accent, 0.08) : Theme.input)
                                                    border.color: sourceLangCombo.currentValue === modelData.code ? Theme.accent : (mouseAreaSrcGrid.containsMouse ? Theme.alpha(Theme.accent, 0.35) : Theme.cardBorder)
                                                    border.width: 1

                                                    RowLayout {
                                                        anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 8; spacing: 6
                                                        Label {
                                                            text: modelData.name
                                                            color: sourceLangCombo.currentValue === modelData.code ? Theme.accent : Theme.txt
                                                            font.pixelSize: 11; font.bold: sourceLangCombo.currentValue === modelData.code
                                                            Layout.fillWidth: true; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter
                                                        }
                                                        Rectangle {
                                                            width: srcCodeBadge.implicitWidth + 8; height: 18; radius: 4
                                                            color: sourceLangCombo.currentValue === modelData.code ? Theme.alpha(Theme.accent, 0.25) : Theme.alpha(Theme.white, 0.06)
                                                            Label {
                                                                id: srcCodeBadge; anchors.centerIn: parent
                                                                text: (modelData.code || "").toUpperCase()
                                                                font.pixelSize: 10; font.bold: true
                                                                color: sourceLangCombo.currentValue === modelData.code ? Theme.accent : Theme.txtDim
                                                            }
                                                        }
                                                        Label {
                                                            visible: sourceLangCombo.currentValue === modelData.code
                                                            text: "✓"; color: Theme.accent; font.bold: true; font.pixelSize: 11; verticalAlignment: Text.AlignVCenter
                                                        }
                                                    }

                                                    MouseArea {
                                                        id: mouseAreaSrcGrid
                                                        anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                                        onClicked: {
                                                            appBackend.setSourceLanguage(modelData.code)
                                                            sourceLangCombo.syncSourceLanguage()
                                                            sourceLangPopup.close()
                                                        }
                                                    }
                                                }
                                            }

                                            // 3. Alt Bilgi Çubuğu (Footer)
                                            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.cardBorder }
                                            RowLayout {
                                                Layout.fillWidth: true
                                                Label {
                                                    text: sourceLangPopup.getFilteredList().length + " " + appBackend.getTextWithDefault("languages_available", "dil listelendi")
                                                    font.pixelSize: 10; color: Theme.txtDim
                                                }
                                                Item { Layout.fillWidth: true }
                                                Label {
                                                    text: appBackend.getTextWithDefault("lang_nav_hint", "↵ Enter: Seç | Esc: Kapat")
                                                    font.pixelSize: 10; color: Theme.txtDim
                                                }
                                            }
                                        }
                                    }
                                }
                                RowLayout {
                                    spacing: 12
                                    Repeater {
                                        model: [
                                            { name: "Auto", code: "auto" },
                                            { name: "JA", code: "japanese" },
                                            { name: "EN", code: "english" },
                                            { name: "ZH", code: "chinese_s" },
                                            { name: "KO", code: "korean" }
                                        ]
                                        QuickPick {
                                            text: modelData.name
                                            current: sourceLangCombo.currentValue === modelData.code
                                            onPicked: { appBackend.setSourceLanguage(modelData.code); sourceLangCombo.syncSourceLanguage() }
                                        }
                                    }
                                }
                            }

                            Button {
                                id: btnSwapLanguages
                                Layout.alignment: Qt.AlignTop
                                Layout.topMargin: pageDashboard.wide ? 8 : 0
                                implicitWidth: 34; implicitHeight: 34
                                topInset: 0; bottomInset: 0; leftInset: 0; rightInset: 0
                                leftPadding: 0; rightPadding: 0; topPadding: 0; bottomPadding: 0
                                ToolTip.visible: hovered
                                ToolTip.delay: 250
                                ToolTip.text: appBackend.uiTrigger, appBackend.getTextWithDefault("swap_languages", "Swap source and target languages")
                                background: Rectangle {
                                    radius: 17
                                    color: btnSwapLanguages.hovered ? Theme.cardHover : "transparent"
                                    border.color: btnSwapLanguages.visualFocus ? Theme.accent : Theme.borderControl
                                    border.width: 1
                                }
                                contentItem: Label {
                                    text: "\u21C4"
                                    font.pixelSize: 16
                                    color: btnSwapLanguages.hovered ? Theme.txt : Theme.txt2
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                                onClicked: {
                                    var curSrc = appBackend.getSourceLanguage() || "auto"
                                    var curTgt = appBackend.getTargetLanguage() || "turkish"
                                    if (curSrc === "auto") {
                                        appBackend.setSourceLanguage(curTgt)
                                        appBackend.setTargetLanguage(curTgt === "english" ? "turkish" : "english")
                                    } else {
                                        appBackend.setSourceLanguage(curTgt)
                                        appBackend.setTargetLanguage(curSrc)
                                    }
                                    sourceLangCombo.syncSourceLanguage()
                                    targetLangCombo.syncTargetLanguage()
                                }
                            }

                            ColumnLayout {
                                spacing: 2
                                ComboBox {
                                    id: targetLangCombo
                                    implicitHeight: pageDashboard.wide ? 48 : 34; implicitWidth: contentItem.implicitWidth; padding: 0
                                    model: appBackend.getTargetLanguages()
                                    textRole: "name"; valueRole: "code"
                                    function syncTargetLanguage() {
                                        var tgt = appBackend.getTargetLanguage() || "turkish"
                                        var idx = targetLangCombo.indexOfValue(tgt)
                                        if (idx >= 0) targetLangCombo.currentIndex = idx
                                    }
                                    Component.onCompleted: syncTargetLanguage()
                                    Connections {
                                        target: appBackend
                                        function onUiTriggerChanged() { targetLangCombo.syncTargetLanguage() }
                                    }
                                    onActivated: appBackend.setTargetLanguage(currentValue)
                                    background: Item {}
                                    // The language name is the page's headline: its own name, large.
                                    contentItem: RowLayout {
                                        spacing: 8
                                        Label {
                                            readonly property string full: targetLangCombo.displayText !== "" ? targetLangCombo.displayText : ""
                                            text: full.indexOf(" (") > 0 ? full.substring(0, full.indexOf(" (")) : full
                                            color: targetLangCombo.enabled ? Theme.txt : Theme.txt2
                                            font.pixelSize: pageDashboard.wide ? 36 : 20
                                            font.weight: Font.DemiBold
                                            elide: Text.ElideRight
                                            Layout.maximumWidth: pageDashboard.wide ? 300 : 220
                                        }
                                        Label {
                                            text: "\u25BE"
                                            color: targetLangCombo.hovered || targetLangCombo.activeFocus ? Theme.txt : Theme.txt2
                                            font.pixelSize: 20
                                            Layout.alignment: Qt.AlignBottom
                                            Layout.bottomMargin: pageDashboard.wide ? 6 : 2
                                        }
                                        Item { Layout.fillWidth: true }
                                    }
                                    indicator: Item {}
                                    delegate: ItemDelegate {
                                        width: targetLangCombo.width
                                        contentItem: Label { text: modelData.name; color: targetLangCombo.highlightedIndex === index ? Theme.accent : Theme.txt; font.pixelSize: 12; leftPadding: 14; elide: Text.ElideRight }
                                        background: Rectangle { color: hovered ? Theme.alpha(Theme.accent, 0.12) : "transparent"; Behavior on color { ColorAnimation { duration: 120 } } }
                                    }
                                    popup: Popup {
                                        id: targetLangPopup
                                        y: targetLangCombo.height + 4
                                        x: Math.min(0, targetLangCombo.width - targetLangPopup.width)
                                        width: Math.min(520, Math.max(340, root.width - 48))
                                        height: Math.min(420, root.height - 180)
                                        padding: 10
                                        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

                                        property string searchFilter: ""
                                        property var allLanguages: []

                                        function refreshLanguages() {
                                            allLanguages = appBackend.getTargetLanguages() || []
                                        }

                                        function getFilteredList() {
                                            appBackend.uiTrigger
                                            var raw = allLanguages.length > 0 ? allLanguages : (appBackend.getTargetLanguages() || [])
                                            var q = searchFilter.trim().toLowerCase()
                                            if (!q) return raw
                                            var res = []
                                            for (var i = 0; i < raw.length; i++) {
                                                var item = raw[i]
                                                var nameStr = (item.name || "").toLowerCase()
                                                var codeStr = (item.code || "").toLowerCase()
                                                if (nameStr.indexOf(q) !== -1 || codeStr.indexOf(q) !== -1) {
                                                    res.push(item)
                                                }
                                            }
                                            return res
                                        }

                                        onAboutToShow: {
                                            refreshLanguages()
                                            searchFilter = ""
                                            targetSearchInput.text = ""
                                            targetSearchTimer.restart()
                                        }

                                        Timer {
                                            id: targetSearchTimer
                                            interval: 60
                                            repeat: false
                                            onTriggered: targetSearchInput.forceActiveFocus()
                                        }

                                        background: Rectangle {
                                            color: Theme.card
                                            radius: 12
                                            border.color: Theme.alpha(Theme.accent, 0.4)
                                            border.width: 1
                                        }

                                        contentItem: ColumnLayout {
                                            spacing: 8
                                            anchors.fill: parent

                                            // 1. Canlı Arama Çubuğu
                                            Rectangle {
                                                Layout.fillWidth: true; height: 36; radius: 8
                                                color: Theme.input
                                                border.color: targetSearchInput.activeFocus ? Theme.accent : Theme.cardBorder
                                                border.width: 1

                                                RowLayout {
                                                    anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 8; spacing: 6
                                                    Icon { glyph: Icons.search; size: 14; color: Theme.txtDim }
                                                    TextInput {
                                                        id: targetSearchInput
                                                        Layout.fillWidth: true
                                                        font.pixelSize: 12; color: Theme.txt
                                                        clip: true
                                                        Text {
                                                            anchors.fill: parent; verticalAlignment: Text.AlignVCenter
                                                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("lang_search_placeholder", "Dil veya kod ara... (örn: ja, tr, en)")
                                                            color: Theme.txtDim; font.pixelSize: 12
                                                            visible: !targetSearchInput.text && !targetSearchInput.activeFocus
                                                        }
                                                        onTextChanged: targetLangPopup.searchFilter = text.trim().toLowerCase()
                                                        onAccepted: {
                                                            var list = targetLangPopup.getFilteredList()
                                                            if (list.length > 0) {
                                                                appBackend.setTargetLanguage(list[0].code)
                                                                targetLangCombo.syncTargetLanguage()
                                                                targetLangPopup.close()
                                                            }
                                                        }
                                                    }
                                                    Button {
                                                        visible: targetSearchInput.text.length > 0
                                                        width: 20; height: 20; text: "✕"
                                                        onClicked: { targetSearchInput.text = ""; targetLangPopup.searchFilter = "" }
                                                        background: Item {}
                                                        contentItem: Label { text: "✕"; color: Theme.txtDim; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                                    }
                                                }
                                            }

                                            // 2. İki Sütunlu Responsive Dil Izgarası
                                            GridView {
                                                id: targetGridView
                                                Layout.fillWidth: true
                                                Layout.fillHeight: true
                                                clip: true
                                                cellWidth: width > 420 ? Math.floor(width / 2) : width
                                                cellHeight: 38
                                                model: targetLangPopup.getFilteredList()
                                                ScrollBar.vertical: ScrollBar {}

                                                delegate: Rectangle {
                                                    width: targetGridView.cellWidth - 4
                                                    height: 34
                                                    radius: 6
                                                    color: mouseAreaTgtGrid.containsMouse ? Theme.alpha(Theme.accent, 0.12) : (targetLangCombo.currentValue === modelData.code ? Theme.alpha(Theme.accent, 0.08) : Theme.input)
                                                    border.color: targetLangCombo.currentValue === modelData.code ? Theme.accent : (mouseAreaTgtGrid.containsMouse ? Theme.alpha(Theme.accent, 0.35) : Theme.cardBorder)
                                                    border.width: 1

                                                    RowLayout {
                                                        anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 8; spacing: 6
                                                        Label {
                                                            text: modelData.name
                                                            color: targetLangCombo.currentValue === modelData.code ? Theme.accent : Theme.txt
                                                            font.pixelSize: 11; font.bold: targetLangCombo.currentValue === modelData.code
                                                            Layout.fillWidth: true; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter
                                                        }
                                                        Rectangle {
                                                            width: tgtCodeBadge.implicitWidth + 8; height: 18; radius: 4
                                                            color: targetLangCombo.currentValue === modelData.code ? Theme.alpha(Theme.accent, 0.25) : Theme.alpha(Theme.white, 0.06)
                                                            Label {
                                                                id: tgtCodeBadge; anchors.centerIn: parent
                                                                text: (modelData.code || "").toUpperCase()
                                                                font.pixelSize: 10; font.bold: true
                                                                color: targetLangCombo.currentValue === modelData.code ? Theme.accent : Theme.txtDim
                                                            }
                                                        }
                                                        Label {
                                                            visible: targetLangCombo.currentValue === modelData.code
                                                            text: "✓"; color: Theme.accent; font.bold: true; font.pixelSize: 11; verticalAlignment: Text.AlignVCenter
                                                        }
                                                    }

                                                    MouseArea {
                                                        id: mouseAreaTgtGrid
                                                        anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                                        onClicked: {
                                                            appBackend.setTargetLanguage(modelData.code)
                                                            targetLangCombo.syncTargetLanguage()
                                                            targetLangPopup.close()
                                                        }
                                                    }
                                                }
                                            }

                                            // 3. Alt Bilgi Çubuğu (Footer)
                                            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.cardBorder }
                                            RowLayout {
                                                Layout.fillWidth: true
                                                Label {
                                                    text: targetLangPopup.getFilteredList().length + " " + appBackend.getTextWithDefault("languages_available", "dil listelendi")
                                                    font.pixelSize: 10; color: Theme.txtDim
                                                }
                                                Item { Layout.fillWidth: true }
                                                Label {
                                                    text: appBackend.getTextWithDefault("lang_nav_hint", "↵ Enter: Seç | Esc: Kapat")
                                                    font.pixelSize: 10; color: Theme.txtDim
                                                }
                                            }
                                        }
                                    }
                                }
                                RowLayout {
                                    spacing: 12
                                    Repeater {
                                        model: [
                                            { name: "TR", code: "turkish" },
                                            { name: "EN", code: "english" },
                                            { name: "DE", code: "german" },
                                            { name: "ES", code: "spanish" },
                                            { name: "RU", code: "russian" },
                                            { name: "FR", code: "french" }
                                        ]
                                        QuickPick {
                                            text: modelData.name
                                            current: targetLangCombo.currentValue === modelData.code
                                            onPicked: { appBackend.setTargetLanguage(modelData.code); targetLangCombo.syncTargetLanguage() }
                                        }
                                    }
                                }
                            }

                            Item { Layout.fillWidth: true }
                        }
                    }

                    Hairline {}

                    // ── Engine ───────────────────────────────────────────
                    FieldRow {
                        label: appBackend.uiTrigger, appBackend.getTextWithDefault("dash_engine", "Engine")
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 14
                            ComboBox {
                                id: engineComboBox
                                Layout.preferredWidth: 330; implicitHeight: 36
                                // Swapping engines mid-run would replace the translator the pipeline is using
                                enabled: !isTranslating
                                function engineModel() {
                                    // One table for GUI, CLI and pipeline: src/utils/engine_registry.py
                                    return appBackend.engineList.map(function(e) {
                                        return {"id": e.id, "icon": Icons[e.icon], "name": e.name}
                                    })
                                }
                                model: engineModel()
                                textRole: "name"; valueRole: "id"
                                function syncIndex() {
                                    var idx = indexOfValue(appBackend.selectedEngine || "google");
                                    if (idx >= 0 && currentIndex !== idx) {
                                        currentIndex = idx;
                                    }
                                }
                                Component.onCompleted: syncIndex()
                                Connections {
                                    target: appBackend
                                    function onSelectedEngineChanged(eng) { engineComboBox.syncIndex() }
                                    function onUiTriggerChanged() { engineComboBox.syncIndex() }
                                }
                                onActivated: { appBackend.setSelectedEngine(currentValue); appBackend.refreshUI() }
                                background: Rectangle {
                                    radius: 6; color: Theme.input; border.color: parent.activeFocus ? Theme.accent : (parent.hovered ? Theme.txtDim : Theme.borderControl); border.width: 1
                                    Behavior on border.color { ColorAnimation { duration: 150 } }
                                }
                                contentItem: IconLabel {
                                    alignment: Qt.AlignLeft; leftPadding: 14
                                    glyph: engineComboBox.currentIndex >= 0 ? engineComboBox.model[engineComboBox.currentIndex].icon : ""
                                    text: engineComboBox.displayText; color: Theme.txt; iconColor: Theme.txt2; font.pixelSize: 12; elide: Text.ElideRight
                                }
                                delegate: ItemDelegate {
                                    width: engineComboBox.width
                                    contentItem: IconLabel { alignment: Qt.AlignLeft; leftPadding: 14; glyph: modelData.icon; text: modelData.name; color: Theme.txt; iconColor: Theme.txt2; font.pixelSize: 12; elide: Text.ElideRight }
                                    background: Rectangle { color: hovered ? Theme.alpha(Theme.accent, 0.12) : "transparent"; Behavior on color { ColorAnimation { duration: 120 } } }
                                }
                                popup: Popup { y: engineComboBox.height + 4; width: engineComboBox.width; implicitHeight: Math.min(contentItem.implicitHeight, 240); padding: 4; contentItem: ListView { clip: true; implicitHeight: contentHeight; model: engineComboBox.delegateModel; ScrollBar.vertical: ScrollBar {} } background: Rectangle { color: Theme.card; radius: 8; border.color: Theme.cardBorder; border.width: 1 } }
                            }
                            Item { Layout.fillWidth: true }
                            Label {
                                visible: appBackend.selectedEngineIsLlm
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("dash_more_ai", "More AI settings")
                                color: aiLinkHover.hovered ? Theme.txt : Theme.txt2
                                font.pixelSize: 12; font.underline: true
                                HoverHandler { id: aiLinkHover; cursorShape: Qt.PointingHandCursor }
                                TapHandler { onTapped: { navIndex = 1; pageSettings.settingsSubTab = 1 } }
                            }
                        }
                        // 0) NVIDIA (Riva-Translate) Hızlı Yapılandırma
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 14
                            visible: appBackend.selectedEngine === "nvidia"

                            ColumnLayout {
                                Layout.fillWidth: true; Layout.preferredWidth: 4; spacing: 4
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_nvidia_key", "NVIDIA API Key:"); color: Theme.txt2; font.pixelSize: 11; font.bold: true }
                                    Item { Layout.fillWidth: true }
                                    Label {
                                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("link_nvidia_get_key", "Get a free key →")
                                        color: nvidiaKeyLinkMa.containsMouse ? Theme.white : Theme.accent
                                        font.pixelSize: 11; font.underline: true
                                        MouseArea {
                                            id: nvidiaKeyLinkMa
                                            anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                            onClicked: Qt.openUrlExternally("https://build.nvidia.com/nvidia/riva-translate-4b-instruct-v2")
                                        }
                                    }
                                }
                                TextField {
                                    id: quickNvidiaKeyField
                                    Layout.fillWidth: true; height: 38
                                    text: appBackend.nvidiaApiKey; echoMode: TextInput.Password; placeholderText: (text.length === 0 && !activeFocus) ? ("nvapi-...") : ""
                                    onEditingFinished: appBackend.nvidiaApiKey = text
                                    background: Rectangle {
                                        radius: 6; color: Theme.input; border.color: parent.activeFocus ? Theme.accent : Theme.cardBorder; border.width: 1
                                        Behavior on border.color { ColorAnimation { duration: 150 } }
                                    }
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true; Layout.preferredWidth: 3; spacing: 4
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_gemini_model", "Model:"); color: Theme.txt2; font.pixelSize: 11; font.bold: true }
                                TextField {
                                    id: quickNvidiaModelField
                                    Layout.fillWidth: true; height: 38
                                    text: appBackend.nvidiaModel; placeholderText: (text.length === 0 && !activeFocus) ? ("nvidia/riva-translate-4b-instruct-v2") : ""
                                    onEditingFinished: appBackend.nvidiaModel = text
                                    background: Rectangle {
                                        radius: 6; color: Theme.input; border.color: parent.activeFocus ? Theme.accent : Theme.cardBorder; border.width: 1
                                        Behavior on border.color { ColorAnimation { duration: 150 } }
                                    }
                                }
                            }

                            Connections {
                                target: appBackend
                                function onNvidiaApiKeyChanged() { quickNvidiaKeyField.text = appBackend.nvidiaApiKey }
                                function onNvidiaModelChanged() { quickNvidiaModelField.text = appBackend.nvidiaModel }
                            }
                        }

                        Label {
                            Layout.fillWidth: true; visible: appBackend.selectedEngineShowsApiNote
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("api_quality_note", "Tip: short one-word lines, names and texts with many placeholders are sometimes kept as-is. You can adjust any of them in the Editor after the run.")
                            color: Theme.txt2; font.pixelSize: 11; wrapMode: Text.WordWrap
                        }

                        // 1) Gemini Hızlı Yapılandırma
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 14
                            visible: appBackend.selectedEngine === "gemini"

                            ColumnLayout {
                                Layout.fillWidth: true; Layout.preferredWidth: 4; spacing: 4
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_gemini_key", "Gemini API Key:"); color: Theme.txt2; font.pixelSize: 11; font.bold: true }
                                TextField {
                                    id: quickGeminiKeyField
                                    Layout.fillWidth: true; height: 38
                                    text: appBackend.geminiApiKey; echoMode: TextInput.Password; placeholderText: (text.length === 0 && !activeFocus) ? ("AIza...") : ""
                                    onEditingFinished: appBackend.geminiApiKey = text
                                    background: Rectangle {
                                        radius: 6; color: Theme.input; border.color: parent.activeFocus ? Theme.accent : Theme.cardBorder; border.width: 1
                                        Behavior on border.color { ColorAnimation { duration: 150 } }
                                    }
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true; Layout.preferredWidth: 3; spacing: 4
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_gemini_model", "Model:"); color: Theme.txt2; font.pixelSize: 11; font.bold: true }
                                TextField {
                                    id: quickGeminiModelField
                                    Layout.fillWidth: true; height: 38
                                    text: appBackend.geminiModel; placeholderText: (text.length === 0 && !activeFocus) ? ("gemini-2.0-flash") : ""
                                    onEditingFinished: appBackend.geminiModel = text
                                    background: Rectangle {
                                        radius: 6; color: Theme.input; border.color: parent.activeFocus ? Theme.accent : Theme.cardBorder; border.width: 1
                                        Behavior on border.color { ColorAnimation { duration: 150 } }
                                    }
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true; Layout.preferredWidth: 4; spacing: 4
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_gemini_safety", "Safety Filter Level:"); color: Theme.txt2; font.pixelSize: 11; font.bold: true }
                                ComboBox {
                                    id: quickGeminiSafetyCombo
                                    Layout.fillWidth: true; height: 38
                                    function safetyModel() {
                                        appBackend.uiTrigger
                                        return [
                                            { "id": "BLOCK_NONE", "name": "BLOCK_NONE (NSFW / Free)" },
                                            { "id": "BLOCK_ONLY_HIGH", "name": "BLOCK_ONLY_HIGH (High Risk)" },
                                            { "id": "STANDARD", "name": "STANDARD (Strict)" }
                                        ]
                                    }
                                    model: safetyModel()
                                    textRole: "name"; valueRole: "id"
                                    function syncSafety() {
                                        var val = appBackend.geminiSafetySettings || "BLOCK_NONE"
                                        var idx = quickGeminiSafetyCombo.indexOfValue(val)
                                        if (idx >= 0) quickGeminiSafetyCombo.currentIndex = idx
                                    }
                                    Component.onCompleted: syncSafety()
                                    Connections {
                                        target: appBackend
                                        function onGeminiSafetySettingsChanged() { quickGeminiSafetyCombo.syncSafety() }
                                        function onUiTriggerChanged() { quickGeminiSafetyCombo.syncSafety() }
                                    }
                                    onActivated: appBackend.geminiSafetySettings = currentValue
                                    background: Rectangle {
                                        radius: 6; color: Theme.input; border.color: parent.activeFocus ? Theme.accent : (parent.hovered ? Theme.txtDim : Theme.borderControl); border.width: 1
                                        Behavior on border.color { ColorAnimation { duration: 150 } }
                                    }
                                    contentItem: Label { leftPadding: 12; text: quickGeminiSafetyCombo.displayText; color: Theme.txt; font.pixelSize: 11; verticalAlignment: Text.AlignVCenter }
                                    delegate: ItemDelegate {
                                        width: quickGeminiSafetyCombo.width
                                        contentItem: Label { text: modelData.name; color: Theme.txt; font.pixelSize: 11; leftPadding: 12 }
                                        background: Rectangle { color: hovered ? Theme.alpha(Theme.accent, 0.12) : "transparent"; Behavior on color { ColorAnimation { duration: 120 } } }
                                    }
                                    popup: Popup { y: quickGeminiSafetyCombo.height; width: quickGeminiSafetyCombo.width; implicitHeight: Math.min(contentItem.implicitHeight, 180); padding: 4; contentItem: ListView { clip: true; implicitHeight: contentHeight; model: quickGeminiSafetyCombo.delegateModel; ScrollBar.vertical: ScrollBar {} } background: Rectangle { color: Theme.card; radius: 8; border.color: Theme.cardBorder; border.width: 1 } }
                                }
                            }
                        }

                        // 2) OpenAI / DeepSeek Hızlı Yapılandırma
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 14
                            visible: appBackend.selectedEngine === "openai" || appBackend.selectedEngine === "deepseek"

                            ColumnLayout {
                                Layout.fillWidth: true; Layout.preferredWidth: 6; spacing: 4
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_openai_key", "API Key:"); color: Theme.txt2; font.pixelSize: 11; font.bold: true }
                                TextField {
                                    id: quickOpenaiKeyField
                                    Layout.fillWidth: true; height: 38
                                    text: appBackend.openaiApiKey; echoMode: TextInput.Password; placeholderText: (text.length === 0 && !activeFocus) ? ("sk-...") : ""
                                    onEditingFinished: appBackend.openaiApiKey = text
                                    background: Rectangle {
                                        radius: 6; color: Theme.input; border.color: parent.activeFocus ? Theme.accent : Theme.cardBorder; border.width: 1
                                        Behavior on border.color { ColorAnimation { duration: 150 } }
                                    }
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true; Layout.preferredWidth: 5; spacing: 4
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_openai_model", "Model:"); color: Theme.txt2; font.pixelSize: 11; font.bold: true }
                                TextField {
                                    id: quickOpenaiModelField
                                    Layout.fillWidth: true; height: 38
                                    text: appBackend.openaiModel; placeholderText: (text.length === 0 && !activeFocus) ? (appBackend.selectedEngine === "deepseek" ? "deepseek-chat" : "gpt-4o-mini") : ""
                                    onEditingFinished: appBackend.openaiModel = text
                                    background: Rectangle {
                                        radius: 6; color: Theme.input; border.color: parent.activeFocus ? Theme.accent : Theme.cardBorder; border.width: 1
                                        Behavior on border.color { ColorAnimation { duration: 150 } }
                                    }
                                }
                            }
                        }

                        // 3a) Local LLM — built-in GGUF runner: the URL/model fields do
                        // nothing in this mode (the port is chosen by RenLocalizer), so
                        // show the model file and server state instead of inviting users
                        // to copy the log's port into the URL field.
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 14
                            visible: appBackend.selectedEngine === "local_llm" && appBackend.localLlmMode === "builtin"

                            ColumnLayout {
                                Layout.fillWidth: true; Layout.preferredWidth: 7; spacing: 4
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("local_llm_gguf_label", "GGUF Model File:"); color: Theme.txt2; font.pixelSize: 11; font.bold: true }
                                RowLayout {
                                    Layout.fillWidth: true; spacing: 6
                                    TextField {
                                        Layout.fillWidth: true; height: 38
                                        text: appBackend.localLlmGgufPath; placeholderText: (text.length === 0 && !activeFocus) ? ("C:/models/model-Q4_K_M.gguf") : ""
                                        onEditingFinished: appBackend.localLlmGgufPath = text
                                        background: Rectangle {
                                            radius: 6; color: Theme.input; border.color: parent.activeFocus ? Theme.accent : Theme.cardBorder; border.width: 1
                                            Behavior on border.color { ColorAnimation { duration: 150 } }
                                        }
                                    }
                                    Button {
                                        id: btnQuickGguf
                                        Layout.preferredWidth: 38; Layout.preferredHeight: 38
                                        onClicked: ggufDialog.open()
                                        ToolTip.visible: hovered
                                        ToolTip.delay: 250
                                        ToolTip.text: appBackend.uiTrigger, appBackend.getTextWithDefault("select_gguf_title", "Select GGUF model file")
                                        background: Rectangle {
                                            radius: 8; color: btnQuickGguf.hovered ? Theme.cardHover : Theme.input
                                            border.color: btnQuickGguf.hovered ? Theme.accent : Theme.cardBorder; border.width: 1
                                        }
                                        contentItem: Item {
                                            Icon { anchors.centerIn: parent; glyph: Icons.folderOpen; size: 16; color: btnQuickGguf.hovered ? Theme.accent : Theme.txt }
                                        }
                                    }
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true; Layout.preferredWidth: 4; spacing: 4
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("local_llm_server_state_label", "Built-in server:"); color: Theme.txt2; font.pixelSize: 11; font.bold: true }
                                Label {
                                    Layout.fillWidth: true; Layout.preferredHeight: 38
                                    verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
                                    font.pixelSize: 12
                                    color: appBackend.localServerStatus === "ready" ? Theme.success
                                         : appBackend.localServerStatus === "error" ? Theme.error : Theme.txt2
                                    text: appBackend.uiTrigger, appBackend.localServerStatus === "ready"
                                          ? appBackend.getTextWithDefault("local_server_ready", "Server running") + " · " + appBackend.localServerDetail
                                          : appBackend.localServerStatus === "error"
                                            ? appBackend.localServerDetail
                                            : appBackend.localServerStatus === "starting"
                                              ? appBackend.getTextWithDefault("local_server_starting", "Loading model...")
                                              : appBackend.getTextWithDefault("local_llm_server_auto_start", "Starts automatically with the translation")
                                }
                            }
                        }

                        // 3) Local LLM Hızlı Yapılandırma (Ollama / LM Studio)
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 14
                            visible: appBackend.selectedEngine === "local_llm" && appBackend.localLlmMode !== "builtin"

                            ColumnLayout {
                                Layout.fillWidth: true; Layout.preferredWidth: 6; spacing: 4
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("local_llm_url_label", "Ollama / LM Studio URL:"); color: Theme.txt2; font.pixelSize: 11; font.bold: true }
                                TextField {
                                    id: quickLocalLlmUrlField
                                    Layout.fillWidth: true; height: 38
                                    text: appBackend.localLlmUrl; placeholderText: (text.length === 0 && !activeFocus) ? ("http://localhost:11434/v1") : ""
                                    onEditingFinished: appBackend.localLlmUrl = text
                                    background: Rectangle {
                                        radius: 6; color: Theme.input; border.color: parent.activeFocus ? Theme.accent : Theme.cardBorder; border.width: 1
                                        Behavior on border.color { ColorAnimation { duration: 150 } }
                                    }
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true; Layout.preferredWidth: 5; spacing: 4
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("local_llm_model_label", "Model Name:"); color: Theme.txt2; font.pixelSize: 11; font.bold: true }
                                TextField {
                                    id: quickLocalLlmModelField
                                    Layout.fillWidth: true; height: 38
                                    text: appBackend.localLlmModel; placeholderText: (text.length === 0 && !activeFocus) ? ("qwen2.5-coder:7b-instruct") : ""
                                    onEditingFinished: appBackend.localLlmModel = text
                                    background: Rectangle {
                                        radius: 6; color: Theme.input; border.color: parent.activeFocus ? Theme.accent : Theme.cardBorder; border.width: 1
                                        Behavior on border.color { ColorAnimation { duration: 150 } }
                                    }
                                }
                            }
                        }

                        // Senkronizasyon Bağlantıları (Settings sekmesiyle anlık iki-yönlü parite)
                        Connections {
                            target: appBackend
                            function onGeminiApiKeyChanged() { quickGeminiKeyField.text = appBackend.geminiApiKey }
                            function onGeminiModelChanged() { quickGeminiModelField.text = appBackend.geminiModel }
                            function onOpenaiApiKeyChanged() { quickOpenaiKeyField.text = appBackend.openaiApiKey }
                            function onOpenaiModelChanged() { quickOpenaiModelField.text = appBackend.openaiModel }
                            function onLocalLlmUrlChanged() { quickLocalLlmUrlField.text = appBackend.localLlmUrl }
                            function onLocalLlmModelChanged() { quickLocalLlmModelField.text = appBackend.localLlmModel }
                        }
                    }

                    // ── Output ───────────────────────────────────────────
                    FieldRow {
                        label: appBackend.uiTrigger, appBackend.getTextWithDefault("dash_output", "Output")
                        enabled: !isTranslating
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 14
                            Rectangle {
                                implicitWidth: modeRow.implicitWidth + 6; implicitHeight: 36
                                radius: 6; color: Theme.input
                                border.color: Theme.borderControl; border.width: 1
                                Layout.alignment: Qt.AlignTop
                                Row {
                                    id: modeRow
                                    anchors.centerIn: parent
                                    Repeater {
                                        model: [
                                            { mode: "native", key: "mode_native_btn", fallback: "Native TLID" },
                                            { mode: "strings", key: "mode_strings_btn", fallback: "Standard (strings.json)" }
                                        ]
                                        delegate: Button {
                                            id: modeButton
                                            readonly property bool active: appBackend.outputMode === modelData.mode
                                            implicitHeight: 30
                                            topInset: 0; bottomInset: 0; leftInset: 0; rightInset: 0
                                            leftPadding: 14; rightPadding: 14; topPadding: 0; bottomPadding: 0
                                            text: appBackend.uiTrigger, appBackend.getTextWithDefault(modelData.key, modelData.fallback)
                                            onClicked: appBackend.outputMode = modelData.mode
                                            background: Rectangle {
                                                radius: 5
                                                color: modeButton.active ? Theme.cardHover : "transparent"
                                                border.color: modeButton.visualFocus ? Theme.accent : "transparent"
                                                border.width: 1
                                            }
                                            contentItem: Label {
                                                text: modeButton.text
                                                color: modeButton.active ? Theme.txt : Theme.txt2
                                                font.pixelSize: 13
                                                font.weight: modeButton.active ? Font.DemiBold : Font.Normal
                                                horizontalAlignment: Text.AlignHCenter
                                                verticalAlignment: Text.AlignVCenter
                                            }
                                        }
                                    }
                                }
                            }
                            Label {
                                Layout.fillWidth: true
                                wrapMode: Text.WordWrap
                                color: Theme.txt2; font.pixelSize: 12
                                text: appBackend.uiTrigger, appBackend.outputMode === "native"
                                    ? appBackend.getTextWithDefault("output_mode_hint", "If part of the game's interface stays untranslated, switch to Standard and translate again.")
                                    : appBackend.getTextWithDefault("desc_strings_mode", "")
                            }
                        }
                    }

                    Item { implicitHeight: 20 }
                }
            }

            // ── narrow windows: the run controls dock at the bottom ───────
            Rectangle {
                visible: !pageDashboard.wide
                Layout.fillWidth: true
                implicitHeight: 84
                color: Theme.card
                Rectangle { width: parent.width; height: 1; color: Theme.cardBorder }
                Rectangle {   // progress along the dock's top edge
                    visible: isTranslating
                    width: parent.width * Math.max(0, Math.min(1, progressBar.value)); height: 2; color: Theme.accent
                    Behavior on width { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
                }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 28; anchors.rightMargin: 28
                    spacing: 20
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 3
                        Label {
                            text: appBackend.uiTrigger, getStageDisplayText(currentStage)
                            font.pixelSize: 16; font.weight: Font.DemiBold
                            color: currentStage === "error" ? Theme.error : Theme.txt
                            Layout.fillWidth: true; elide: Text.ElideRight
                        }
                        Label {
                            Layout.fillWidth: true; elide: Text.ElideRight
                            color: Theme.txt2; font.pixelSize: 12
                            text: appBackend.uiTrigger, isTranslating
                                ? (Math.round(progressBar.value * 100) + "%   " + progressLabel.text)
                                : (pageDashboard.finished
                                    ? appBackend.getTextWithDefault("dash_done", "Translated {done} of {total} lines").replace("{done}", translatedLines).replace("{total}", totalLines)
                                    : (pageDashboard.canResume
                                      ? pageDashboard.resumeText()
                                      : pageDashboard.hasEstimate
                                        ? pageDashboard.estimateText()
                                        : pageDashboard.hasProject
                                        ? appBackend.getTextWithDefault("dash_output_goes", "Output goes to {path}.").replace("{path}", pageDashboard.outputFolder())
                                        : appBackend.getTextWithDefault("dash_run_empty_title", "Nothing to run yet")))
                        }
                    }
                    QuietButton {
                        visible: pageDashboard.finished
                        glyph: Icons.squarePen
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("completion_open_editor", "Review in Editor")
                        implicitHeight: 42
                        onClicked: root.openEditorForTarget()
                    }
                    RunButton { implicitWidth: 168; implicitHeight: 42 }
                }
            }
        }

        // ── run panel (wide windows) ─────────────────────────────────────
        Rectangle {
            visible: pageDashboard.wide
            Layout.preferredWidth: 388
            Layout.fillHeight: true
            color: Theme.card
            Rectangle { width: 1; height: parent.height; color: Theme.cardBorder }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 32
                anchors.topMargin: 40
                spacing: 0

                // nothing selected
                ColumnLayout {
                    visible: !pageDashboard.hasProject && !isTranslating
                    Layout.fillWidth: true
                    spacing: 8
                    Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("dash_run_empty_title", "Nothing to run yet")
                        font.pixelSize: 16; font.weight: Font.DemiBold; color: Theme.txt
                    }
                    Label {
                        Layout.fillWidth: true; wrapMode: Text.WordWrap
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("dash_run_empty_desc", "Pick a game and this side shows the run: its progress and the lines as they are translated.")
                        color: Theme.txt2; font.pixelSize: 13
                    }
                }

                // ready, running or finished
                ColumnLayout {
                    visible: pageDashboard.hasProject || isTranslating
                    Layout.fillWidth: true
                    spacing: 0

                    RunStatus { Layout.fillWidth: true }

                    // The line being translated, shown the way the game shows it.
                    Rectangle {
                        visible: isTranslating && pageDashboard.liveTranslation.length > 0
                        Layout.topMargin: 22; Layout.fillWidth: true
                        implicitHeight: liveCol.implicitHeight + 28
                        radius: 8; color: Theme.bg
                        border.color: Theme.cardBorder; border.width: 1
                        ColumnLayout {
                            id: liveCol
                            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                            anchors.margins: 14
                            spacing: 6
                            Label {
                                visible: pageDashboard.liveSpeaker.length > 0
                                text: pageDashboard.liveSpeaker
                                color: Theme.txt2; font.pixelSize: 12; font.weight: Font.DemiBold
                            }
                            Label {
                                Layout.fillWidth: true; wrapMode: Text.WordWrap
                                maximumLineCount: 3; elide: Text.ElideRight
                                text: pageDashboard.liveOriginal; textFormat: Text.PlainText
                                color: Theme.txt2; font.pixelSize: 13
                            }
                            Label {
                                Layout.fillWidth: true; wrapMode: Text.WordWrap
                                maximumLineCount: 4; elide: Text.ElideRight
                                text: pageDashboard.liveTranslation; textFormat: Text.PlainText
                                color: Theme.txt; font.pixelSize: 14
                            }
                        }
                    }

                    // finished: what the run did
                    Label {
                        visible: pageDashboard.finished
                        Layout.topMargin: 10; Layout.fillWidth: true; wrapMode: Text.WordWrap
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("dash_done", "Translated {done} of {total} lines").replace("{done}", translatedLines).replace("{total}", totalLines)
                        color: Theme.txt2; font.pixelSize: 13
                    }

                    Label {
                        visible: pageDashboard.canResume && !pageDashboard.finished
                        Layout.topMargin: 10; Layout.fillWidth: true; wrapMode: Text.WordWrap
                        text: appBackend.uiTrigger, pageDashboard.resumeText()
                        color: Theme.txt2; font.pixelSize: 13
                    }
                    Label {
                        visible: pageDashboard.hasEstimate
                        Layout.topMargin: 6; Layout.fillWidth: true; wrapMode: Text.WordWrap
                        text: appBackend.uiTrigger, pageDashboard.estimate, pageDashboard.estimateText()
                        color: Theme.txt2; font.pixelSize: 13
                    }

                    RunButton { Layout.topMargin: 24; Layout.fillWidth: true }

                    QuietButton {
                        visible: pageDashboard.finished
                        Layout.topMargin: 10; Layout.fillWidth: true
                        implicitHeight: 40
                        glyph: Icons.squarePen
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("completion_open_editor", "Review in Editor")
                        onClicked: root.openEditorForTarget()
                    }

                    Label {
                        Layout.topMargin: 12; Layout.fillWidth: true; wrapMode: Text.WordWrap
                        color: Theme.txtDim; font.pixelSize: 12
                        text: appBackend.uiTrigger, isTranslating
                            ? appBackend.getTextWithDefault("dash_kept_note", "Lines translated so far are kept.")
                            : appBackend.getTextWithDefault("dash_output_goes", "Output goes to {path}.").replace("{path}", pageDashboard.outputFolder())
                    }
                }

                Item { Layout.fillHeight: true; Layout.minimumHeight: 16 }

                // log tail: one quiet strip; the full log is its own page
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Hairline {}
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: 6
                        Label {
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("dash_log", "Log")
                            color: Theme.txt2; font.pixelSize: 13
                            Layout.fillWidth: true
                        }
                        Label {
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("dash_open", "Open")
                            color: logLinkHover.hovered ? Theme.txt : Theme.txt2
                            font.pixelSize: 12; font.underline: true
                            HoverHandler { id: logLinkHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: navIndex = 2 }
                        }
                    }
                    ListView {
                        id: logListView
                        Layout.fillWidth: true
                        Layout.preferredHeight: 124
                        clip: true
                        spacing: 5
                        model: logModel
                        delegate: RowLayout {
                            width: logListView.width
                            spacing: 10
                            Label { text: model.ts; color: Theme.txtDim; font.pixelSize: 11 }
                            Label {
                                text: root.stripLeadingEmoji(model.message)
                                color: (model.level === "error" || model.level === "warning") ? logColor(model.level) : Theme.txt2
                                font.pixelSize: 11
                                Layout.fillWidth: true; elide: Text.ElideRight
                            }
                        }
                    }
                }
            }
        }
    }
}
