// HomePage.qml - Ana Sayfa (Tam Sürüm)
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs

Rectangle {
    id: homePage
    color: Material.background

    property bool isTranslating: false
    property string currentStage: "idle"
    property int totalLines: 0
    property int translatedLines: 0
    property int untranslatedLines: 0
    property bool statsAvailable: false
    property var tmHomeSources: []

    function refreshTMHomeSources() {
        tmHomeSources = backend.getAvailableTMSources()
    }

    onVisibleChanged: {
        if (visible) refreshTMHomeSources()
    }

    Connections {
        target: backend
        function onTranslationFinished(success, message) {
            refreshTMHomeSources()
        }
        function onTmSourcesChanged() {
            refreshTMHomeSources()
        }
    }

    // Public functions for backend signals
    function addLog(level, message) {
        // Vibecoding: Raw data push for better performance & flexibility
        var timestamp = new Date().toLocaleTimeString(Qt.locale(), "HH:mm:ss")
        logModel.append({
            "level": level,
            "message": message,
            "timestamp": timestamp
        })
        
        // Auto-scroll to bottom
        logListView.positionViewAtEnd()
    }

    function getLogPrefixText(level) {
        var trig = backend.uiTrigger
        if (level === "error") return backend.getTextWithDefault("log_tag_error", "[ERROR]")
        if (level === "warning") return backend.getTextWithDefault("log_tag_warn", "[WARN]")
        if (level === "guard") return backend.getTextWithDefault("log_tag_guard", "[GUARD]")
        if (level === "success") return backend.getTextWithDefault("log_tag_ok", "[OK]")
        if (level === "debug") return backend.getTextWithDefault("log_tag_debug", "[DEBUG]")
        return backend.getTextWithDefault("log_tag_info", "[INFO]")
    }

    function copyLogsToClipboard() {
        if (logModel.count === 0) return
        var lines = []
        for (var i = 0; i < logModel.count; i++) {
            var entry = logModel.get(i)
            lines.push("[" + entry.timestamp + "] " + getLogPrefixText(entry.level) + " " + entry.message)
        }
        var copied = backend.copyTextToClipboard(lines.join("\n"))
        if (copied) {
            addLog("success", (backend.uiTrigger, backend.getText("log_copy_success")))
            return
        }
        addLog("error", (backend.uiTrigger, backend.getText("log_copy_failed")))
    }

    function updateProgress(current, total, text) {
        progressBar.value = total > 0 ? current / total : 0
        progressLabel.text = text + ` (${current}/${total})`
    }

    function setStage(stage, displayName) {
        currentStage = stage
        stageLabel.text = displayName
        
        // Update progress based on stage
        var stageProgress = {
            "idle": 0, "validating": 5, "unren": 15,
            "generating": 30, "parsing": 40, "translating": 50,
            "saving": 95, "completed": 100, "error": 0
        }
        if (stage !== "translating" && stageProgress[stage] !== undefined) {
            progressBar.value = stageProgress[stage] / 100
        }

        if (stage === "validating") {
            statsAvailable = false
        }
    }

    function setTranslating(state) {
        isTranslating = state
        if (!state) {
            // keep stage until next start
        }
    }

    function showStats(total, translated, untranslated) {
        totalLines = total
        translatedLines = translated
        untranslatedLines = untranslated
        statsAvailable = true
        if (typeof backend === "undefined" || backend === null) return
        var statsMsg = (backend.uiTrigger, backend.getTextWithDefault("stats_summary_log", "📊 Total: {total} | Translated: {translated} | Untranslated: {untranslated}"))
        statsMsg = statsMsg.replace("{total}", total).replace("{translated}", translated).replace("{untranslated}", untranslated)
        addLog("success", statsMsg)
    }

    // Log model
    ListModel {
        id: logModel
    }

    // File Dialog
    FileDialog {
        id: fileDialog
        title: (typeof backend !== "undefined" && backend !== null) ? (backend.uiTrigger, backend.getTextWithDefault("select_exe_file_title", "Select Game File")) : "Select File"
        nameFilters: {
            if (typeof backend === "undefined" || backend === null) return ["All files (*)"]
            return Qt.platform.os === "windows" 
                ? [(backend.uiTrigger, backend.getTextWithDefault("file_filter_exe", "Executable files (*.exe)")), (backend.uiTrigger, backend.getTextWithDefault("file_filter_all", "All files (*)"))]
                : [(backend.uiTrigger, backend.getTextWithDefault("file_filter_shell", "Shell scripts (*.sh)")), (backend.uiTrigger, backend.getTextWithDefault("file_filter_all", "All files (*)"))]
        }
        onAccepted: {
            var p = selectedFile.toString()
            backend.setProjectPath(p)
            projectPathField.text = backend.urlToPath(p)
        }
    }

    // Folder Dialog
    FolderDialog {
        id: folderDialog
        title: (typeof backend !== "undefined" && backend !== null) ? (backend.uiTrigger, backend.getTextWithDefault("select_game_folder", "Select Game Folder")) : "Select Folder"
        onAccepted: {
            var p = selectedFolder.toString()
            backend.setProjectPath(p)
            projectPathField.text = backend.urlToPath(p)
        }
    }

    // Main Layout
    ScrollView {
        anchors.fill: parent
        contentWidth: availableWidth

        ColumnLayout {
            width: Math.min(parent.width - 48, 1100)
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.margins: 24
            spacing: 24

            // Başlık ve Logo Alanı
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 20
                spacing: 20

                // Logo
                Rectangle {
                    Layout.preferredWidth: 64
                    Layout.preferredHeight: 64
                    color: "transparent"
                    
                    Image {
                        anchors.fill: parent
                        source: root.brandingLogoSource
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                        mipmap: true
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    
                    Label {
                        text: (backend.uiTrigger, backend.getTextWithDefault("app_title", "RenLocalizer"))
                        font.pixelSize: 32
                        font.bold: true
                        color: root.mainTextColor
                    }

                    Label {
                        text: (backend.uiTrigger, backend.getTextWithDefault("app_subtitle", "Professional Ren'Py Translation Tool"))
                        font.pixelSize: 16
                        color: root.secondaryTextColor
                        font.weight: Font.Medium
                    }
                }
            }

            // ==================== Proje Seçimi Kartı ====================
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: contentColumn1.height + 40
                radius: 16
                color: root.cardBackground

                ColumnLayout {
                    id: contentColumn1
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 20
                    spacing: 12

                    Label {
                        text: (backend.uiTrigger, backend.getTextWithDefault("input_section", "📁 Game Selection"))
                        font.pixelSize: 16
                        font.bold: true
                        color: root.mainTextColor
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12

                        TextField {
                            id: projectPathField
                            Layout.fillWidth: true
                            Layout.preferredHeight: 45
                            // Dynamic placeholder to prevent overlapping
                            placeholderText: text.length > 0 ? "" : (backend.uiTrigger, backend.getTextWithDefault("game_exe_placeholder", "Select game file or folder..."))
                            color: root.mainTextColor
                            font.pixelSize: 14
                            leftPadding: 16
                            rightPadding: 16
                            verticalAlignment: TextInput.AlignVCenter
                            
                            background: Rectangle {
                                color: root.inputBackground
                                radius: 8
                                border.color: projectPathField.activeFocus ? Material.accent : root.borderColor
                                border.width: 1
                            }
                            
                            placeholderTextColor: Qt.rgba(root.mainTextColor.r, root.mainTextColor.g, root.mainTextColor.b, 0.45)
                            
                            onEditingFinished: backend.setProjectPath(text)
                            onAccepted: backend.setProjectPath(text)
                        }

                        Button {
                            text: "📄 " + (backend.uiTrigger, backend.getTextWithDefault("browse", "File"))
                            Layout.preferredHeight: 45
                            Layout.preferredWidth: 100
                            onClicked: fileDialog.open()

                            contentItem: Label {
                                text: parent.text
                                font.pixelSize: 13
                                font.family: root.iconFontFamily
                                color: "white"
                                font.bold: true
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }

                            background: Rectangle {
                                radius: 10
                                color: parent.down ? Qt.darker(Material.accent, 1.2) : parent.hovered ? Qt.darker(Material.accent, 1.1) : Material.accent
                                border.color: parent.hovered ? root.mainTextColor : "transparent"
                                border.width: 1
                            }
                        }

                        Button {
                            text: "📂 " + (backend.uiTrigger, backend.getTextWithDefault("browse_folder", "Folder"))
                            Layout.preferredHeight: 45
                            Layout.preferredWidth: 100
                            onClicked: folderDialog.open()

                            contentItem: Label {
                                text: parent.text
                                font.pixelSize: 13
                                font.family: root.iconFontFamily
                                color: "white"
                                font.bold: true
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }

                            background: Rectangle {
                                radius: 10
                                color: parent.down ? Qt.darker(Material.accent, 1.2) : parent.hovered ? Qt.darker(Material.accent, 1.1) : Material.accent
                                border.color: parent.hovered ? root.mainTextColor : "transparent"
                                border.width: 1
                            }
                        }
                    }
                }
            }

            // ==================== Çeviri Ayarları Kartı ====================
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: contentColumn2.height + 40
                radius: 16
                color: root.cardBackground

                ColumnLayout {
                    id: contentColumn2
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 20
                    spacing: 16

                    Label {
                        text: (backend.uiTrigger, backend.getTextWithDefault("translation_settings", "⚙️ Translation Settings"))
                        font.pixelSize: 16
                        font.bold: true
                        color: root.mainTextColor
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 32

                        // Kaynak Dil
                        ColumnLayout {
                            spacing: 8
                            Layout.preferredWidth: 180

                            Label {
                                text: (backend.uiTrigger, backend.getTextWithDefault("source_lang_label", "Source Language"))
                                font.pixelSize: 12
                                color: root.secondaryTextColor
                            }

                            ComboBox {
                                id: sourceLangCombo
                                Layout.fillWidth: true
                                model: backend.getSourceLanguages()
                                textRole: "name"
                                valueRole: "code"
                                currentIndex: 0
                                onActivated: backend.setSourceLanguage(currentValue)
                                Component.onCompleted: {
                                    var idx = indexOfValue(backend.getSourceLanguage())
                                    if (idx >= 0) currentIndex = idx
                                }

                                background: Rectangle {
                                    radius: 8
                                    implicitHeight: 40
                                    color: root.inputBackground
                                    border.color: root.borderColor
                                }

                                contentItem: Label {
                                    text: sourceLangCombo.currentText
                                    color: root.mainTextColor
                                    font.pixelSize: 13
                                    verticalAlignment: Text.AlignVCenter
                                    leftPadding: 12
                                    rightPadding: 32
                                }
                            }
                        }

                        // Hedef Dil
                        ColumnLayout {
                            spacing: 8
                            Layout.preferredWidth: 180

                            Label {
                                text: (backend.uiTrigger, backend.getTextWithDefault("target_lang_label", "Target Language"))
                                font.pixelSize: 12
                                color: root.secondaryTextColor
                            }

                            ComboBox {
                                id: targetLangCombo
                                Layout.fillWidth: true
                                model: backend.getTargetLanguages()
                                textRole: "name"
                                valueRole: "code"
                                currentIndex: 0
                                onActivated: backend.setTargetLanguage(currentValue)
                                Component.onCompleted: {
                                    var idx = indexOfValue(backend.getTargetLanguage())
                                    if (idx >= 0) currentIndex = idx
                                }

                                background: Rectangle {
                                    radius: 8
                                    implicitHeight: 40
                                    color: root.inputBackground
                                    border.color: root.borderColor
                                }

                                contentItem: Label {
                                    text: targetLangCombo.currentText
                                    color: root.mainTextColor
                                    font.pixelSize: 13
                                    verticalAlignment: Text.AlignVCenter
                                    leftPadding: 12
                                    rightPadding: 32
                                }
                            }
                        }

                        // Çeviri Motoru
                        ColumnLayout {
                            spacing: 8
                            Layout.fillWidth: true
                            Layout.maximumWidth: 300

                            Label {
                                text: (backend.uiTrigger, backend.getTextWithDefault("translation_engine_label", "Translation Engine"))
                                font.pixelSize: 12
                                color: root.secondaryTextColor
                            }

                            ComboBox {
                                id: engineCombo
                                Layout.fillWidth: true
                                model: backend.getAvailableEngines()
                                textRole: "name"
                                valueRole: "code"
                                currentIndex: 0
                                onActivated: backend.setEngine(currentValue)
                                Component.onCompleted: {
                                    var idx = indexOfValue(backend.selectedEngine)
                                    if (idx >= 0) currentIndex = idx
                                }

                                background: Rectangle {
                                    radius: 8
                                    implicitHeight: 40
                                    color: root.inputBackground
                                    border.color: root.borderColor
                                }

                                contentItem: Label {
                                    text: engineCombo.currentText
                                    color: root.mainTextColor
                                    font.pixelSize: 13
                                    verticalAlignment: Text.AlignVCenter
                                    leftPadding: 12
                                    rightPadding: 32
                                }
                            }
                        }

                        Item { Layout.fillWidth: true }

                        // Başlat / Durdur Butonu
                        Button {
                            id: startButton
                            Layout.preferredWidth: 160
                            Layout.preferredHeight: 50
                            enabled: projectPathField.text.length > 0
                            text: isTranslating ? 
                                ("⏹ " + (backend.uiTrigger, backend.getTextWithDefault("stop", "Stop"))) : 
                                ("▶ " + (backend.uiTrigger, backend.getTextWithDefault("start_translation", "Start")))

                            onClicked: {
                                if (isTranslating) {
                                    backend.stopTranslation()
                                } else {
                                    // Manuel girişi garantilemek için son bir kez ata
                                    if (projectPathField.text.length > 0) {
                                        backend.setProjectPath(projectPathField.text)
                                    }
                                    backend.startTranslation()
                                }
                            }

                            contentItem: Label {
                                text: parent.text
                                font.pixelSize: 15
                                font.bold: true
                                color: "white"
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }

                            background: Rectangle {
                                radius: 12
                                color: {
                                    if (!parent.enabled) return "#555"
                                    if (isTranslating) return parent.down ? "#c0392b" : parent.hovered ? "#e74c3c" : "#c0392b"
                                    return parent.down ? Qt.darker(Material.accent, 1.2) : 
                                           parent.hovered ? Qt.lighter(Material.accent, 1.1) : Material.accent
                                }

                                Behavior on color {
                                    ColorAnimation { duration: 150 }
                                }
                            }
                        }
                    }
                }
            }

            // ==================== External TM Kaynak Seçimi (v2.7.3) ====================
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: tmColumn.height + 40
                radius: 16
                color: root.cardBackground
                visible: (backend.uiTrigger, backend.getUseExternalTM())

                ColumnLayout {
                    id: tmColumn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 20
                    spacing: 12

                    Label {
                        text: "🧠 " + (backend.uiTrigger, backend.getTextWithDefault("tm_sources_title", "Translation Memory Sources"))
                        font.pixelSize: 16
                        font.family: root.iconFontFamily
                        font.bold: true
                        color: root.mainTextColor
                    }

                    Label {
                        text: (backend.uiTrigger, backend.getTextWithDefault("tm_sources_desc", "Select which TM sources to use during translation. Matched texts will skip API calls."))
                        color: root.secondaryTextColor
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    Repeater {
                        id: tmHomeRepeater
                        model: (backend.uiTrigger, backend.getUseExternalTM()) ? tmHomeSources : []

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10

                            CheckBox {
                                id: tmSourceCheck
                                text: modelData.name + " (" + modelData.language + ") — " + modelData.entry_count + " entries"
                                checked: {
                                    try {
                                        var sources = JSON.parse(backend.getExternalTMSources())
                                        return sources.indexOf(modelData.file_path) >= 0
                                    } catch(e) { return false }
                                }
                                onToggled: {
                                    backend.toggleTMSource(modelData.file_path, checked)
                                    homePage.refreshTMHomeSources()
                                }

                                contentItem: Label {
                                    text: parent.text
                                    color: root.secondaryTextColor
                                    font.pixelSize: 13
                                    leftPadding: parent.indicator.width + parent.spacing
                                    verticalAlignment: Text.AlignVCenter
                                }
                            }
                        }
                    }

                    Label {
                        visible: tmHomeRepeater.count === 0
                        text: (backend.uiTrigger, backend.getTextWithDefault("tm_no_sources", "No TM sources available. Import from Tools page."))
                        color: root.secondaryTextColor
                        font.pixelSize: 12
                        font.italic: true
                    }
                }
            }

            // ==================== İlerleme Kartı ====================
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: progressColumn.height + 40
                radius: 16
                color: root.cardBackground
                visible: isTranslating || currentStage === "completed"

                ColumnLayout {
                    id: progressColumn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 20
                    spacing: 12

                    RowLayout {
                        Layout.fillWidth: true

                        Label {
                            id: stageLabel
                            text: (backend.uiTrigger, backend.getTextWithDefault("ready", "Ready"))
                            font.pixelSize: 16
                            font.bold: true
                            color: root.mainTextColor
                        }

                        Item { Layout.fillWidth: true }

                        Label {
                            id: progressLabel
                            text: "0/0"
                            font.pixelSize: 14
                            color: root.secondaryTextColor
                        }
                    }

                    ProgressBar {
                        id: progressBar
                        Layout.fillWidth: true
                        value: 0
                        from: 0
                        to: 1

                        background: Rectangle {
                            radius: 6
                            color: root.inputBackground
                        }

                        contentItem: Item {
                            Rectangle {
                                width: progressBar.visualPosition * parent.width
                                height: parent.height
                                radius: 6
                                color: currentStage === "completed" ? "#6bcb77" : Material.accent

                                Behavior on width {
                                    NumberAnimation { duration: 200 }
                                }
                            }
                        }
                    }
                }
            }

            // ==================== İstatistik Kartı ====================
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: statsRow.height + 40
                radius: 16
                color: root.cardBackground
                visible: statsAvailable

                RowLayout {
                    id: statsRow
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 20
                    spacing: 40

                    ColumnLayout {
                        Label { text: (backend.uiTrigger, backend.getTextWithDefault("stats_total", "Total Lines")); color: "#aaa"; font.pixelSize: 12 }
                        Label { text: totalLines; color: root.mainTextColor; font.pixelSize: 20; font.bold: true }
                    }

                    ColumnLayout {
                        Label { text: (backend.uiTrigger, backend.getTextWithDefault("stats_translated", "Translated")); color: "#aaa"; font.pixelSize: 12 }
                        Label { text: translatedLines; color: "#6bcb77"; font.pixelSize: 20; font.bold: true }
                    }

                    ColumnLayout {
                        Label { text: (backend.uiTrigger, backend.getTextWithDefault("stats_untranslated", "Remaining")); color: "#aaa"; font.pixelSize: 12 }
                        Label { text: untranslatedLines; color: "#ff6b6b"; font.pixelSize: 20; font.bold: true }
                    }

                    ColumnLayout {
                        Label { text: (backend.uiTrigger, backend.getTextWithDefault("stats_success_rate", "Success Rate")); color: "#aaa"; font.pixelSize: 12 }
                        Label { 
                            text: totalLines > 0 ? ((translatedLines / totalLines) * 100).toFixed(1) + "%" : "0%"
                            color: Material.accent; font.pixelSize: 20; font.bold: true 
                        }
                    }
                }
            }

            // ==================== İpucu Kutusu (Agresif Çeviri) ====================
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: tipRow.implicitHeight + 24
                radius: 12
                color: Qt.alpha("#f39c12", 0.15) // Hafif turuncu/sarı arka plan
                border.color: "#f39c12"
                border.width: 1

                RowLayout {
                    id: tipRow
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.margins: 12
                    spacing: 12

                    Label {
                        text: "💡"
                        font.pixelSize: 20
                        font.family: root.iconFontFamily
                        Layout.alignment: Qt.AlignTop
                    }

                    Label {
                        Layout.fillWidth: true
                        text: (backend.uiTrigger, backend.getTextWithDefault("tip_aggressive_translation", "Tip: If some strings remain in original language after translation, try enabling Settings > 'Aggressive Translation' mode."))
                        color: root.mainTextColor
                        font.pixelSize: 13
                        
                        // Link desteği için RichText
                        textFormat: Text.RichText
                        wrapMode: Text.Wrap
                        lineHeight: 1.2
                        
                        // Link tıklama işleyicisi
                        onLinkActivated: (link) => {
                            if (link === "faq") {
                                var faqPath = backend.get_asset_url("docs/wiki/FAQ.md")
                                console.log("Opening FAQ at: " + faqPath)
                                backend.openUrl(faqPath)
                            } else {
                                Qt.openUrlExternally(link)
                            }
                        }
                    }
                }
            }

            // ==================== Log Paneli ====================
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 300
                radius: 16
                color: root.cardBackground

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 12

                    RowLayout {
                        Layout.fillWidth: true

                        Label {
                            text: "📋 " + (backend.uiTrigger, backend.getTextWithDefault("log", "Log"))
                            font.pixelSize: 14
                            font.family: root.iconFontFamily
                            font.bold: true
                            color: root.mainTextColor
                        }

                        Item { Layout.fillWidth: true }

                        Button {
                            text: "📄"
                            font.family: root.iconFontFamily
                            flat: true
                            enabled: logModel.count > 0
                            onClicked: copyLogsToClipboard()

                            ToolTip.visible: hovered
                            ToolTip.text: (backend.uiTrigger, backend.getText("copy_log"))
                        }

                        Button {
                            text: "🗑"
                            font.family: root.iconFontFamily
                            flat: true
                            onClicked: logModel.clear()

                            ToolTip.visible: hovered
                            ToolTip.text: (backend.uiTrigger, backend.getTextWithDefault("clear_log", "Clear"))
                        }
                    }

                    // Log ListView (Virtual Scrolling için optimize)
                    ListView {
                        id: logListView
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: logModel
                        spacing: 4

                        delegate: Label {
                            width: logListView.width
                            
                            // Dynamic Logic in Delegate
                            property string colorCode: {
                                if (level === "error") return root.currentTheme === "light" ? "#e03131" : "#ff8787"
                                if (level === "warning") return root.currentTheme === "light" ? "#e67700" : "#ffd43b"
                                if (level === "guard") return root.currentTheme === "light" ? "#1c7ed6" : "#74c0fc"
                                if (level === "success") return root.currentTheme === "light" ? "#2b8a3e" : "#69db7c"
                                if (level === "debug") return root.currentTheme === "light" ? "#868e96" : "#8b949e"
                                return root.currentTheme === "light" ? "#495057" : "#cfd8dc"
                            }

                            property string prefixText: {
                                return homePage.getLogPrefixText(level)
                            }

                            text: `<font color="${colorCode}">[${timestamp}] ${prefixText} ${message}</font>`
                            textFormat: Text.RichText
                            font.family: "Consolas"
                            font.pixelSize: 12
                            wrapMode: Text.Wrap
                        }

                        ScrollBar.vertical: ScrollBar {
                            active: true
                            policy: ScrollBar.AsNeeded
                        }
                    }
                }
            }



            // ==================== Destek Banner ====================
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 80
                radius: 16
                color: (root.currentTheme === "light") ? Qt.alpha(Material.accent, 0.2) : "#2d1f3d"  // Theme-aware support banner background

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 15

                    Label {
                        text: "❤️"
                        font.pixelSize: 28
                        font.family: root.iconFontFamily
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4

                        Label {
                            text: (backend.uiTrigger, backend.getTextWithDefault("support_banner_title", "Do you love RenLocalizer?"))
                            font.pixelSize: 14
                            font.bold: true
                            color: root.mainTextColor
                        }

                        Label {
                            text: (backend.uiTrigger, backend.getTextWithDefault("support_banner_desc", "Join us to support development."))
                            font.pixelSize: 12
                            color: root.secondaryTextColor
                        }
                    }

                    Button {
                        text: "💜 " + (backend.uiTrigger, backend.getTextWithDefault("nav_support", "Support"))
                        onClicked: backend.openUrl("https://www.patreon.com/c/LordOfTurk")

                        contentItem: Label {
                            text: parent.text
                            font.pixelSize: 14
                            font.family: root.iconFontFamily
                            font.bold: true
                            color: "white"
                            horizontalAlignment: Text.AlignHCenter
                        }

                        background: Rectangle {
                            radius: 10
                            color: parent.down ? "#7b2cbf" : parent.hovered ? "#9d4edd" : "#7b2cbf"
                        }
                    }
                }
            }

            // Alt boşluk
            Item { Layout.preferredHeight: 20 }
        }
    }

    // Component yüklendiğinde hoşgeldin mesajı
    Component.onCompleted: {
        refreshTMHomeSources()
        addLog("info", "RenLocalizer v" + backend.version + (backend.uiTrigger, backend.getTextWithDefault("app_log_qt_ui", " - Qt Quick UI")))
        addLog("info", (backend.uiTrigger, backend.getTextWithDefault("welcome_message", "Welcome! Select the game you want to translate.")))
        
        var lastPath = backend.getLastProjectPath()
        if (lastPath) {
            projectPathField.text = lastPath
            backend.setProjectPath(lastPath) // Backend state sync
            var restoreMsg = (backend.uiTrigger, backend.getTextWithDefault("last_session_restored", "Last session restored: {path}"))
            addLog("info", restoreMsg.replace("{path}", lastPath))
        }
    }
}
