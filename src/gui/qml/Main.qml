// Main.qml — RenLocalizer v2.8.15 (Pro Fluent Micro-Interactions & Modern Motion UI)
// Yeniden tasarlandı: Sol Kenar Çubuğu (Sidebar Navigation), Glass/Carbon Kartlar,
// Mikro-animasyonlar (Micro-interactions), Akıcı Geçişler, Tam Sayfa Ayarlar ve Konsol Sekmeleri.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs
import QtQuick.Window
import "components"

ApplicationWindow {
    id: root
    title: appBackend.uiTrigger, appBackend.getTextWithDefault("app_title", "RenLocalizer") + " (" + appBackend.version + ")"

    // Responsive ve ferah başlangıç boyutları
    width: Math.min(1320, Screen.desktopAvailableWidth * 0.86)
    height: Math.min(860, Screen.desktopAvailableHeight * 0.86)
    minimumWidth: 980
    minimumHeight: 650
    visible: false // show() Python tarafından çağrılır

    Material.theme: Material.Dark
    Material.accent: Theme.accent
    Material.primary: Theme.primary

    color: Theme.bg



    // ── State & Navigasyon ────────────────────────────────────────────────
    property int    navIndex:        0 // 0: Dashboard, 1: Settings, 2: Logs, 3: Toolbox
    property bool   isTranslating:   false
    property string currentStage:    "idle"
    property string stageCustomName: ""
    property int    totalLines:      0
    property int    translatedLines: 0
    property real   successRate:     0.0
    property string outputPath:      ""
    property bool   statsVisible:    false

    // ── Evrensel Dil Adı ve Kodu Çözümleyici (Undefined Bugfix) ──────────
    function getLangText(modelData, model) {
        var n = ""
        var c = ""
        if (typeof model !== "undefined" && model && model.name !== undefined) {
            n = model.name
            c = model.code !== undefined ? model.code : ""
        } else if (typeof modelData !== "undefined" && modelData) {
            if (modelData.name !== undefined) n = modelData.name
            else if (typeof modelData === "string") n = modelData
            if (modelData.code !== undefined) c = modelData.code
        }
        if (!n || n === "undefined") n = "Auto-detect"
        if (c && c !== "auto" && c !== "undefined") return n + " (" + c + ")"
        return n
    }

    // ── Başlangıç ─────────────────────────────────────────────────────────
    Component.onCompleted: {
        var last = appBackend.getLastProjectPath()
        if (last && last.length > 0)
            projectPathField.text = last
        appBackend.refreshProjectInfo()

        if (targetLangCombo && targetLangCombo.syncTargetLanguage) targetLangCombo.syncTargetLanguage()
        if (sourceLangCombo && sourceLangCombo.syncSourceLanguage) sourceLangCombo.syncSourceLanguage()
        if (uiLanguageCombo && uiLanguageCombo.syncUILanguage) uiLanguageCombo.syncUILanguage()

        appBackend.checkForUpdates(false)
    }

    // ── Backend Sinyalleri ────────────────────────────────────────────────
    Connections {
        target: appBackend

        function onLogMessage(level, message) {
            appendLog(level, message)
            if (message.indexOf("❌") >= 0 && (message.indexOf("select a game") >= 0 || message.indexOf("not found") >= 0 || message.indexOf("game folder") >= 0 || message.indexOf("oyun") >= 0))
                projectPathField.triggerShake()
            // Show toast for toolbox operations and key events
            if (message.indexOf("✅") === 0 && (message.indexOf("Font") >= 0 || message.indexOf("Lint") >= 0 || message.indexOf("terms") >= 0 || message.indexOf("imported") >= 0 || message.indexOf("exported") >= 0 || message.indexOf("filled") >= 0 || message.indexOf("translated") >= 0))
                showToast(message.replace("✅ ", ""), "success")
            else if (message.indexOf("⚠️") === 0 && (message.indexOf("failed") >= 0 || message.indexOf("not found") >= 0))
                showToast(message.replace("⚠️ ", ""), "warning")
            else if (message.indexOf("🔤") === 0 || message.indexOf("🩺") === 0 || message.indexOf("📚") === 0)
                showToast(message, "info")
        }

        function onProgressChanged(current, total, text) {
            if (total > 0) progressBar.value = current / total
            progressLabel.text = text + " (" + current + "/" + total + ")"
        }

        function onStageChanged(stage, displayName) {
            currentStage = stage
            stageCustomName = cleanStageText(displayName)
            var stageProgress = {
                "idle": 0, "validating": 5, "unren": 15,
                "generating": 30, "parsing": 40,
                "saving": 90, "completed": 100, "error": 0
            }
            if (stage !== "translating" && stageProgress[stage] !== undefined)
                progressBar.value = stageProgress[stage] / 100
        }

        function onTranslationStarted() {
            isTranslating = true
            statsVisible = false
            progressBar.value = 0
            progressLabel.text = ""
            currentStage = "starting"
            navIndex = 0 // Akışı anlık izlemek için Dashboard sekmene geç
        }

        function onTranslationFinished(success, message) {
            isTranslating = false
            if (success) {
                currentStage = "completed"
                progressBar.value = 1.0
                showToast(appBackend.getTextWithDefault("translation_completed", "Çeviri tamamlandı!"), "success")
            } else {
                currentStage = "error"
                showToast(appBackend.getTextWithDefault("pipeline_translate_failed", "Translation failed") + ": " + message, "error")
            }
        }

        function onStatsReady(total, translated, untranslated) {
            totalLines = total
            translatedLines = translated
            successRate = total > 0 ? (translated / total) * 100 : 0
            statsVisible = true
            appendLog("success",
                "📊 " + appBackend.getTextWithDefault("original_text", "Toplam") + ": " + total +
                " | " + appBackend.getTextWithDefault("completed", "Çevrildi") + ": " + translated +
                " | " + appBackend.getTextWithDefault("untranslated", "Remaining") + ": " + untranslated +
                " | " + appBackend.getTextWithDefault("ratio", "Ratio") + ": " + successRate.toFixed(1) + "%"
            )
        }

        function onCompletionSummary(title, message, outPath, diagPath, reviewCount) {
            outputPath = outPath
            completionDialog.summaryText = message
            completionDialog.outputPath = outPath
            completionDialog.diagPath = diagPath
            completionDialog.open()
        }

        function onWarningMessage(title, message) {
            warningDialog.titleText = title
            warningDialog.bodyText = message
            warningDialog.open()
        }

        function onUpdateAvailable(currentVersion, latestVersion, releaseUrl) {
            updateDialog.latestVersion = latestVersion
            updateDialog.releaseUrl = releaseUrl
            updateDialog.open()
        }

        function onUpdateCheckFinished(hasUpdate, message) {
            showToast(message, hasUpdate ? "success" : "info")
        }
    }

    // ── Yardımcı Log Fonksiyonları ────────────────────────────────────────
    ListModel { id: logModel }

    function appendLog(level, message) {
        var ts = new Date().toLocaleTimeString(Qt.locale(), "HH:mm:ss")
        logModel.append({ "level": level, "message": message, "ts": ts })
        logListView.positionViewAtEnd()
        logConsoleListView.positionViewAtEnd()
    }

    Connections {
        target: editorBackend
        function onNotify(level, message) {
            appendLog(level, message)
            showToast(message, level)
        }
    }

    property bool editorCloseConfirmed: false
    onClosing: function(close) {
        // Text typed into the editor but not applied yet counts as unsaved too.
        if (!editorCloseConfirmed) pageEditor.commitPending()
        if (!editorCloseConfirmed && editorBackend.hasUnsavedChanges) {
            close.accepted = false
            editorCloseDialog.open()
        }
    }

    Dialog {
        id: editorCloseDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
        modal: true
        title: appBackend.uiTrigger, appBackend.getTextWithDefault("editor_unsaved_title", "Unsaved changes")
        Label {
            text: appBackend.uiTrigger, appBackend.getTextWithDefault("editor_unsaved_close", "The editor has unsaved edits. Quit without saving?")
            color: Theme.txt; wrapMode: Text.WordWrap
        }
        footer: DialogButtonBox {
            Button {
                text: appBackend.uiTrigger, appBackend.getTextWithDefault("editor_go_to_editor", "Go to editor")
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
                onClicked: { editorCloseDialog.close(); navIndex = 5 }
            }
            Button {
                text: appBackend.uiTrigger, appBackend.getTextWithDefault("editor_quit_discard", "Quit without saving")
                DialogButtonBox.buttonRole: DialogButtonBox.DestructiveRole
                onClicked: { editorCloseConfirmed = true; editorCloseDialog.close(); root.close() }
            }
        }
    }

    function showToast(msg, type) {
        toast.show(msg, type)
    }

    function logColor(level) {
        if (level === "error")   return Theme.error
        if (level === "warning") return Theme.warn
        if (level === "success") return Theme.success
        if (level === "debug")   return Theme.txtDim
        return Theme.txt
    }

    function logPrefix(level) {
        var trigger = appBackend.uiTrigger
        if (level === "error")   return "[" + appBackend.getTextWithDefault("log_tag_error", "HATA").replace("[","").replace("]","") + "] "
        if (level === "warning") return "[" + appBackend.getTextWithDefault("log_tag_warn", "UYARI").replace("[","").replace("]","") + "] "
        if (level === "success") return "[" + appBackend.getTextWithDefault("log_tag_ok", "TAMAM").replace("[","").replace("]","") + "] "
        return "[" + appBackend.getTextWithDefault("log_tag_info", "BİLGİ").replace("[","").replace("]","") + "] "
    }

    // Metnin başındaki emojiyi atar: arayüz ikonları Icons ile çizilir, ama log
    // metinleriyle paylaşılan anahtarlar (stage_*, update_available_title) emojiyi taşır.
    function stripLeadingEmoji(str) {
        if (!str) return ""
        return str.replace(/^\s*(?:[\uD800-\uDBFF][\uDC00-\uDFFF]|[\u2190-\u2BFF])\uFE0F?\s*/, "")
    }

    function cleanModalTitle(str) {
        return stripLeadingEmoji(str).trim()
    }

    function cleanStageText(str) {
        return stripLeadingEmoji(str).replace(/[\.\s…]+$/, "").trim()
    }

    // Son projeler listesindeki görünen ad: klasör adı (EXE seçildiyse onun klasörü)
    function projectLabel(path) {
        var parts = String(path || "").split(String.fromCharCode(92)).join("/").split("/").filter(function(x) { return x.length > 0 })
        var last = parts[parts.length - 1] || String(path || "")
        if (/\.(exe|sh|py)$/i.test(last) && parts.length > 1)
            return parts[parts.length - 2]
        return last
    }

    // Tamamlanma penceresinden: hedef dilin çevirisini editörde aç
    function openEditorForTarget() {
        navIndex = 5
        editorBackend.refreshLanguages()
        var lang = appBackend.getTargetLanguage()
        if (lang)
            pageEditor.openLanguage(lang)
    }

    function getStageDisplayText(stage) {
        var trigger = appBackend.uiTrigger
        if (stage === "idle")
            return appBackend.getTextWithDefault("status_ready", "Ready - Waiting to Start")
        if (stage === "starting")
            return cleanStageText(appBackend.getTextWithDefault("starting_translation", "Starting translation..."))
        if (stage === "validating")
            return cleanStageText(appBackend.getTextWithDefault("stage_validating", "Validating..."))
        if (stage === "unren" || stage === "unrpa")
            return cleanStageText(appBackend.getTextWithDefault("stage_unren", "Decompiling (UnRen)..."))
        if (stage === "generating")
            return cleanStageText(appBackend.getTextWithDefault("stage_generating", "Generating Translation Files..."))
        if (stage === "parsing")
            return cleanStageText(appBackend.getTextWithDefault("stage_parsing", "Reading Files..."))
        if (stage === "translating")
            return cleanStageText(appBackend.getTextWithDefault("stage_translating", "Translating..."))
        if (stage === "saving")
            return cleanStageText(appBackend.getTextWithDefault("stage_saving", "Saving..."))
        if (stage === "completed")
            return cleanModalTitle(appBackend.getTextWithDefault("stage_completed", "Completed!")).replace("!", "") + " ✓"
        if (stage === "error")
            return cleanModalTitle(appBackend.getTextWithDefault("stage_error", "Error!"))
        return cleanStageText(stageCustomName.length > 0 ? stageCustomName : stage)
    }

    // ── Dosya ve Klasör Seçim Diyalogları ─────────────────────────────────
    FileDialog {
        id: fileDialog
        title: appBackend.uiTrigger, appBackend.getTextWithDefault("select_game_exe_title", "Oyun EXE Dosyasını Seç")
        nameFilters: Qt.platform.os === "windows"
            ? [appBackend.getTextWithDefault("renpy_games_filter", "Ren'Py Games") + " (*.exe)",
               appBackend.getTextWithDefault("all_files_filter", "All files") + " (*)"]
            : (Qt.platform.os === "osx" || Qt.platform.os === "macos")
            // Ren'Py's mac package is Game.app (game files in Contents/Resources/autorun)
            ? [appBackend.getTextWithDefault("renpy_games_filter", "Ren'Py Games") + " (*.app *.sh)",
               appBackend.getTextWithDefault("all_files_filter", "All files") + " (*)"]
            : [appBackend.getTextWithDefault("shell_scripts_filter", "Shell scripts") + " (*.sh)",
               appBackend.getTextWithDefault("all_files_filter", "All files") + " (*)"]
        onAccepted: {
            var raw = selectedFile.toString()
            appBackend.setProjectPath(raw)
            projectPathField.text = appBackend.urlToPath(raw)
        }
    }

    FileDialog {
        id: ggufDialog
        title: appBackend.uiTrigger, appBackend.getTextWithDefault("select_gguf_title", "GGUF Model Dosyasını Seç")
        nameFilters: [appBackend.getTextWithDefault("gguf_files_filter", "GGUF models") + " (*.gguf)",
                      appBackend.getTextWithDefault("all_files_filter", "All files") + " (*)"]
        onAccepted: appBackend.localLlmGgufPath = appBackend.urlToPath(selectedFile.toString())
    }

    FileDialog {
        id: llamaServerDialog
        title: appBackend.uiTrigger, appBackend.getTextWithDefault("select_llama_server_title", "llama-server Dosyasını Seç")
        nameFilters: [appBackend.getTextWithDefault("all_files_filter", "All files") + " (*)"]
        onAccepted: appBackend.localLlmServerPath = appBackend.urlToPath(selectedFile.toString())
    }

    FolderDialog {
        id: folderDialog
        title: appBackend.uiTrigger, appBackend.getTextWithDefault("select_game_folder_title", "Oyun Klasörünü Seç")
        onAccepted: {
            var raw = selectedFolder.toString()
            appBackend.setProjectPath(raw)
            projectPathField.text = appBackend.urlToPath(raw)
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // ANA LAYOUT (Sol Sidebar Navigation + Sağ İçerik Paneli)
    // ═══════════════════════════════════════════════════════════════════════
    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ── 1. SOL KENAR ÇUBUĞU (SIDEBAR NAVIGATION - 230px) ──────────────
        Rectangle {
            Layout.preferredWidth: 230
            Layout.fillHeight: true
            color: Theme.sidebar

            // Sağ siber kenarlık
            Rectangle {
                anchors.right: parent.right
                width: 1; height: parent.height
                color: Theme.cardBorder
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.leftMargin: 20; anchors.rightMargin: 20
                anchors.topMargin: 26; anchors.bottomMargin: 26
                spacing: 20

                // Üst Logo & Başlık
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12

                    // İkon Konteyneri (Zarif Çerçeve & Dairesel Form)
                    Rectangle {
                        Layout.preferredWidth: 44; Layout.preferredHeight: 44
                        Layout.alignment: Qt.AlignVCenter
                        radius: 22
                        color: Theme.alpha(Theme.card, 0.7)
                        border.color: Theme.alpha(Theme.accent, 0.28)
                        border.width: 1

                        Image {
                            anchors.fill: parent
                            anchors.margins: 2
                            source: appBackend.get_asset_url("icon.png")
                            sourceSize: Qt.size(64, 64)
                            fillMode: Image.PreserveAspectFit
                            smooth: true
                            mipmap: true
                        }
                    }

                    // Başlık ve Sürüm Rozeti
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignVCenter
                        spacing: 4

                        Label {
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("app_title", "RenLocalizer")
                            font.pixelSize: 18; font.bold: true; color: Theme.txt
                            font.letterSpacing: 0.4
                        }

                        // Sürüm Rozeti (Pill Badge)
                        Rectangle {
                            implicitWidth: versionBadgeLayout.implicitWidth + 14
                            implicitHeight: 18
                            radius: 9
                            color: Theme.alpha(Theme.accent, 0.08)
                            border.color: Theme.alpha(Theme.accent, 0.24)
                            border.width: 1

                            RowLayout {
                                id: versionBadgeLayout
                                anchors.centerIn: parent
                                spacing: 5

                                Rectangle {
                                    width: 5; height: 5; radius: 2.5
                                    color: Theme.accent
                                }

                                Text {
                                    text: "v" + appBackend.version
                                    font.pixelSize: 10
                                    font.bold: true
                                    font.letterSpacing: 0.3
                                    color: Theme.accent
                                }
                            }
                        }
                    }
                }

                Item { height: 4 }
                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.cardBorder; opacity: 0.7 }
                Item { height: 2 }

                // Menü Butonları (Sekmeler)
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    // Buton 1: Dashboard
                    Button {
                        id: btnNavDash
                        Layout.fillWidth: true; height: 44
                        scale: down ? 0.97 : 1.0
                        Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                        onClicked: navIndex = 0
                        background: Rectangle {
                            radius: 10
                            color: navIndex === 0 ? Theme.alpha(Theme.accent, 0.14) : (btnNavDash.hovered ? Theme.cardHover : "transparent")
                            border.color: navIndex === 0 ? Theme.alpha(Theme.accent, 0.7) : "transparent"
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 150 } }
                            Behavior on border.color { ColorAnimation { duration: 150 } }

                            // Sol aktif neon gösterge çizgisi
                            Rectangle {
                                anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: 4
                                width: 3; height: navIndex === 0 ? 22 : 0
                                radius: 1.5; color: Theme.accent
                                opacity: navIndex === 0 ? 1.0 : 0.0
                                Behavior on height { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                                Behavior on opacity { NumberAnimation { duration: 150 } }
                            }
                        }
                        contentItem: RowLayout {
                            spacing: 14
                            transform: Translate {
                                x: (btnNavDash.hovered && navIndex !== 0) ? 4 : 0
                                Behavior on x { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                            }
                            Icon {
                                glyph: Icons.layoutDashboard; size: 18
                                color: navIndex === 0 ? Theme.accent : Theme.txt2
                                Behavior on color { ColorAnimation { duration: 150 } }
                                scale: navIndex === 0 ? 1.15 : 1.0
                                Behavior on scale { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                            }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_dashboard", "Dashboard")
                                Layout.fillWidth: true; elide: Text.ElideRight
                                font.pixelSize: 13; font.bold: navIndex === 0; color: navIndex === 0 ? Theme.accent : Theme.txt
                                Behavior on color { ColorAnimation { duration: 150 } }
                            }
                        }
                    }

                    // Buton 2: Settings (Gelişmiş Ayarlar)
                    Button {
                        id: btnNavSettings
                        Layout.fillWidth: true; height: 44
                        scale: down ? 0.97 : 1.0
                        Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                        onClicked: navIndex = 1
                        background: Rectangle {
                            radius: 10
                            color: navIndex === 1 ? Theme.alpha(Theme.accent, 0.14) : (btnNavSettings.hovered ? Theme.cardHover : "transparent")
                            border.color: navIndex === 1 ? Theme.alpha(Theme.accent, 0.7) : "transparent"
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 150 } }
                            Behavior on border.color { ColorAnimation { duration: 150 } }

                            // Sol aktif neon gösterge çizgisi
                            Rectangle {
                                anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: 4
                                width: 3; height: navIndex === 1 ? 22 : 0
                                radius: 1.5; color: Theme.accent
                                opacity: navIndex === 1 ? 1.0 : 0.0
                                Behavior on height { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                                Behavior on opacity { NumberAnimation { duration: 150 } }
                            }
                        }
                        contentItem: RowLayout {
                            spacing: 14
                            transform: Translate {
                                x: (btnNavSettings.hovered && navIndex !== 1) ? 4 : 0
                                Behavior on x { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                            }
                            Icon {
                                glyph: Icons.settings; size: 18
                                color: navIndex === 1 ? Theme.accent : Theme.txt2
                                Behavior on color { ColorAnimation { duration: 150 } }
                                scale: navIndex === 1 ? 1.15 : 1.0
                                Behavior on scale { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                            }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_settings", "Settings & AI")
                                Layout.fillWidth: true; elide: Text.ElideRight
                                font.pixelSize: 13; font.bold: navIndex === 1; color: navIndex === 1 ? Theme.accent : Theme.txt
                                Behavior on color { ColorAnimation { duration: 150 } }
                            }
                        }
                    }

                    // Buton 3: Log Console (Detaylı Loglar)
                    Button {
                        id: btnNavLogs
                        Layout.fillWidth: true; height: 44
                        scale: down ? 0.97 : 1.0
                        Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                        onClicked: navIndex = 2
                        background: Rectangle {
                            radius: 10
                            color: navIndex === 2 ? Theme.alpha(Theme.accent, 0.14) : (btnNavLogs.hovered ? Theme.cardHover : "transparent")
                            border.color: navIndex === 2 ? Theme.alpha(Theme.accent, 0.7) : "transparent"
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 150 } }
                            Behavior on border.color { ColorAnimation { duration: 150 } }

                            // Sol aktif neon gösterge çizgisi
                            Rectangle {
                                anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: 4
                                width: 3; height: navIndex === 2 ? 22 : 0
                                radius: 1.5; color: Theme.accent
                                opacity: navIndex === 2 ? 1.0 : 0.0
                                Behavior on height { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                                Behavior on opacity { NumberAnimation { duration: 150 } }
                            }
                        }
                        contentItem: RowLayout {
                            spacing: 14
                            transform: Translate {
                                x: (btnNavLogs.hovered && navIndex !== 2) ? 4 : 0
                                Behavior on x { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                            }
                            Icon {
                                glyph: Icons.terminal; size: 18
                                color: navIndex === 2 ? Theme.accent : Theme.txt2
                                Behavior on color { ColorAnimation { duration: 150 } }
                                scale: navIndex === 2 ? 1.15 : 1.0
                                Behavior on scale { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                            }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_logs", "Log Console")
                                Layout.fillWidth: true; elide: Text.ElideRight
                                font.pixelSize: 13; font.bold: navIndex === 2; color: navIndex === 2 ? Theme.accent : Theme.txt
                                Behavior on color { ColorAnimation { duration: 150 } }
                            }
                        }
                    }

                    // Glossary Button
                    Button {
                        id: btnNavGlossary
                        Layout.fillWidth: true; height: 44
                        scale: down ? 0.97 : 1.0
                        Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                        onClicked: navIndex = 4
                        background: Rectangle {
                            radius: 10
                            color: navIndex === 4 ? Theme.alpha(Theme.accent, 0.14) : (btnNavGlossary.hovered ? Theme.cardHover : "transparent")
                            border.color: navIndex === 4 ? Theme.alpha(Theme.accent, 0.7) : "transparent"
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 150 } }
                            Behavior on border.color { ColorAnimation { duration: 150 } }

                            // Sol aktif neon gösterge çizgisi
                            Rectangle {
                                anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: 4
                                width: 3; height: navIndex === 4 ? 22 : 0
                                radius: 1.5; color: Theme.accent
                                opacity: navIndex === 4 ? 1.0 : 0.0
                                Behavior on height { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                                Behavior on opacity { NumberAnimation { duration: 150 } }
                            }
                        }
                        contentItem: RowLayout {
                            spacing: 14
                            transform: Translate {
                                x: (btnNavGlossary.hovered && navIndex !== 4) ? 4 : 0
                                Behavior on x { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                            }
                            Icon {
                                glyph: Icons.bookA; size: 18
                                color: navIndex === 4 ? Theme.accent : Theme.txt2
                                Behavior on color { ColorAnimation { duration: 150 } }
                                scale: navIndex === 4 ? 1.15 : 1.0
                                Behavior on scale { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                            }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_glossary", "Glossary")
                                Layout.fillWidth: true; elide: Text.ElideRight
                                font.pixelSize: 13; font.bold: navIndex === 4; color: navIndex === 4 ? Theme.accent : Theme.txt
                                Behavior on color { ColorAnimation { duration: 150 } }
                            }
                        }
                    }

                    Button {
                        id: btnNavEditor
                        Layout.fillWidth: true; height: 44
                        scale: down ? 0.97 : 1.0
                        Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                        onClicked: navIndex = 5
                        background: Rectangle {
                            radius: 10
                            color: navIndex === 5 ? Theme.alpha(Theme.accent, 0.14) : (btnNavEditor.hovered ? Theme.cardHover : "transparent")
                            border.color: navIndex === 5 ? Theme.alpha(Theme.accent, 0.7) : "transparent"
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 150 } }
                            Behavior on border.color { ColorAnimation { duration: 150 } }

                            // Sol aktif neon gösterge çizgisi
                            Rectangle {
                                anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: 4
                                width: 3; height: navIndex === 5 ? 22 : 0
                                radius: 1.5; color: Theme.accent
                                opacity: navIndex === 5 ? 1.0 : 0.0
                                Behavior on height { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                                Behavior on opacity { NumberAnimation { duration: 150 } }
                            }
                        }
                        contentItem: RowLayout {
                            spacing: 14
                            transform: Translate {
                                x: (btnNavEditor.hovered && navIndex !== 5) ? 4 : 0
                                Behavior on x { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                            }
                            Icon {
                                glyph: Icons.squarePen; size: 18
                                color: navIndex === 5 ? Theme.accent : Theme.txt2
                                Behavior on color { ColorAnimation { duration: 150 } }
                                scale: navIndex === 5 ? 1.15 : 1.0
                                Behavior on scale { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                            }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_editor", "Editor")
                                Layout.fillWidth: true; elide: Text.ElideRight
                                font.pixelSize: 13; font.bold: navIndex === 5; color: navIndex === 5 ? Theme.accent : Theme.txt
                                Behavior on color { ColorAnimation { duration: 150 } }
                            }
                        }
                    }

                    // Buton 5: Toolbox (Araç Kutusu)
                    Button {
                        id: btnNavToolbox
                        Layout.fillWidth: true; height: 44
                        scale: down ? 0.97 : 1.0
                        Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                        onClicked: navIndex = 3
                        background: Rectangle {
                            radius: 10
                            color: navIndex === 3 ? Theme.alpha(Theme.accent, 0.14) : (btnNavToolbox.hovered ? Theme.cardHover : "transparent")
                            border.color: navIndex === 3 ? Theme.alpha(Theme.accent, 0.7) : "transparent"
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 150 } }
                            Behavior on border.color { ColorAnimation { duration: 150 } }

                            // Sol aktif neon gösterge çizgisi
                            Rectangle {
                                anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: 4
                                width: 3; height: navIndex === 3 ? 22 : 0
                                radius: 1.5; color: Theme.accent
                                opacity: navIndex === 3 ? 1.0 : 0.0
                                Behavior on height { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                                Behavior on opacity { NumberAnimation { duration: 150 } }
                            }
                        }
                        contentItem: RowLayout {
                            spacing: 14
                            transform: Translate {
                                x: (btnNavToolbox.hovered && navIndex !== 3) ? 4 : 0
                                Behavior on x { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                            }
                            Icon {
                                glyph: Icons.wrench; size: 18
                                color: navIndex === 3 ? Theme.accent : Theme.txt2
                                Behavior on color { ColorAnimation { duration: 150 } }
                                scale: navIndex === 3 ? 1.15 : 1.0
                                Behavior on scale { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                            }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_toolbox", "Toolbox")
                                Layout.fillWidth: true; elide: Text.ElideRight
                                font.pixelSize: 13; font.bold: navIndex === 3; color: navIndex === 3 ? Theme.accent : Theme.txt
                                Behavior on color { ColorAnimation { duration: 150 } }
                            }
                        }
                    }
                }

                // Esnek İtici Alan (En az 24px garanti tampon)
                Item {
                    Layout.fillHeight: true
                    Layout.minimumHeight: 28
                }

                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.cardBorder; opacity: 0.7 }
                Item { height: 4 }

                // Kılavuz ve Destek Butonları
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Button {
                        id: btnWikiGuide
                        Layout.fillWidth: true; height: 38
                        scale: down ? 0.96 : (hovered ? 1.02 : 1.0)
                        transformOrigin: Item.Center
                        Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                        onClicked: Qt.openUrlExternally("https://github.com/Lord0fTurk/RenLocalizer/wiki")
                        background: Rectangle {
                            radius: 8
                            color: btnWikiGuide.down ? Theme.alpha(Theme.accent, 0.1) : (btnWikiGuide.hovered ? Theme.cardHover : "transparent")
                            border.color: btnWikiGuide.hovered ? Theme.alpha(Theme.accent, 0.5) : Theme.cardBorder
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 150 } }
                            Behavior on border.color { ColorAnimation { duration: 150 } }
                        }
                        contentItem: RowLayout {
                            anchors.centerIn: parent; spacing: 8
                            Icon { glyph: Icons.bookOpen; size: 14; color: btnWikiGuide.hovered ? Theme.txt : Theme.txt2 }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_wiki_guide", "Wiki Guide")
                                color: btnWikiGuide.hovered ? Theme.txt : Theme.txt2; font.pixelSize: 12; elide: Text.ElideRight
                                Behavior on color { ColorAnimation { duration: 150 } }
                            }
                        }
                    }
                    Button {
                        id: btnPatreonSupport
                        Layout.fillWidth: true; height: 38
                        scale: down ? 0.96 : (hovered ? 1.02 : 1.0)
                        transformOrigin: Item.Center
                        Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                        onClicked: Qt.openUrlExternally("https://www.patreon.com/RenLocalizer")
                        background: Rectangle {
                            radius: 8
                            color: btnPatreonSupport.down ? Theme.alpha(Theme.error, 0.25) : (btnPatreonSupport.hovered ? Theme.alpha(Theme.error, 0.15) : "transparent")
                            border.color: btnPatreonSupport.hovered ? Theme.error : Theme.dangerHover
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 150 } }
                            Behavior on border.color { ColorAnimation { duration: 150 } }
                        }
                        contentItem: RowLayout {
                            anchors.centerIn: parent; spacing: 8
                            Icon { glyph: Icons.heart; size: 14; color: Theme.error }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_patreon_support", "Patreon Support")
                                color: btnPatreonSupport.hovered ? Theme.white : Theme.errorSoft; font.pixelSize: 12; elide: Text.ElideRight
                                Behavior on color { ColorAnimation { duration: 150 } }
                            }
                        }
                    }
                }

                Item { height: 6 }

                // Sistem Durumu
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Rectangle {
                        width: 9; height: 9; radius: 4.5
                        color: isTranslating ? Theme.warn : Theme.success

                        // Aktif durumdayken radar/nabız halkası (pulse effect)
                        Rectangle {
                            anchors.centerIn: parent
                            width: parent.width; height: parent.height; radius: width / 2
                            color: parent.color
                            opacity: 0.0

                            SequentialAnimation on scale {
                                running: isTranslating
                                loops: Animation.Infinite
                                NumberAnimation { from: 1.0; to: 2.5; duration: 1200; easing.type: Easing.OutQuad }
                            }
                            SequentialAnimation on opacity {
                                running: isTranslating
                                loops: Animation.Infinite
                                NumberAnimation { from: 0.75; to: 0.0; duration: 1200; easing.type: Easing.OutQuad }
                            }
                        }
                    }
                    Label {
                        text: appBackend.uiTrigger, isTranslating ? appBackend.getTextWithDefault("status_working", "Working...") : appBackend.getTextWithDefault("status_ready", "System Ready")
                        color: Theme.txt2; font.pixelSize: 12; font.bold: true
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                    }
                }
            }
        }

        // ── 2. SAĞ SAYFA İÇERİK ALANI (CARD-BASED GLASS DASHBOARD) ────────
        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: navIndex

            // ═════════════════════════════════════════════════════════════
            // SEKME 0: DASHBOARD (Örnek Görseldeki Pro Kart Düzeni)
            // ═════════════════════════════════════════════════════════════
            Item {
                id: pageDashboard
                Layout.fillWidth: true
                Layout.fillHeight: true

                // ── SABİT BAŞLIK ──────────────────────────────────────
                PageHeader {
                    id: dashStickyHeader
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    glyph: Icons.layoutDashboard
                    title: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_dashboard", "Dashboard")
                    subtitle: appBackend.uiTrigger, appBackend.getTextWithDefault("dashboard_subtitle", "Select game executable, configure translation engine/languages, and launch localization.")
                }

                // ── KAYDIRILABİLİR İÇERİK ALANI (RESPONSIVE MAX-WIDTH) ──
                ScrollView {
                    anchors.top: dashStickyHeader.bottom
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
                        spacing: 20

                        Item { height: 8 }

                    // ── KART 1: PROJECT SETUP (PROJE KURULUMU) ────────────
                    Rectangle {
                        id: cardProject
                        Layout.fillWidth: true
                        Layout.preferredHeight: projectInnerRow.implicitHeight + 44
                        radius: 16; color: cardProject.hovered ? Theme.cardHover : Theme.card
                        border.color: cardProject.hovered ? Theme.alpha(Theme.accent, 0.4) : Theme.cardBorder
                        border.width: 1
                        property bool hovered: false
                        scale: hovered ? 1.004 : 1.0
                        transformOrigin: Item.Center
                        Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                        Behavior on color { ColorAnimation { duration: 180 } }
                        Behavior on border.color { ColorAnimation { duration: 180 } }
                        HoverHandler { onHoveredChanged: cardProject.hovered = hovered }

                        // QW-1 Staggered Entrance
                        transform: Translate { id: animTrProject; y: 16 }
                        opacity: 0.0
                        SequentialAnimation {
                            id: animEntranceProject
                            PauseAnimation { duration: 0 }
                            ParallelAnimation {
                                NumberAnimation { target: animTrProject; property: "y"; to: 0; duration: 240; easing.type: Easing.OutCubic }
                                NumberAnimation { target: cardProject; property: "opacity"; to: 1.0; duration: 220; easing.type: Easing.OutQuad }
                            }
                        }
                        Component.onCompleted: if (navIndex === 0) animEntranceProject.start()
                        Connections { target: root; function onNavIndexChanged() { if (navIndex === 0) animEntranceProject.restart() } }

                        RowLayout {
                            id: projectInnerRow
                            anchors.fill: parent; anchors.margins: 22
                            spacing: 16

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 10

                                RowLayout {
                                    Layout.fillWidth: true
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("card_project_setup", "Project Setup"); font.pixelSize: 16; font.bold: true; color: Theme.txt }
                                    Item { Layout.fillWidth: true }
                                    // Proje Durum Rozeti
                                    Rectangle {
                                        visible: !!appBackend.projectInfo.ok && projectPathField.text.length > 0
                                        height: 24
                                        Layout.preferredWidth: projBadgeRow.implicitWidth + 16
                                        radius: 6
                                        color: Theme.alpha(Theme.success, 0.15)
                                        border.color: Theme.alpha(Theme.success, 0.4)
                                        border.width: 1
                                        RowLayout {
                                            id: projBadgeRow
                                            anchors.centerIn: parent; spacing: 4
                                            Label { text: "✓"; color: Theme.success; font.bold: true; font.pixelSize: 11 }
                                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("badge_project_ready", "Proje Yüklendi"); color: Theme.success; font.pixelSize: 11; font.bold: true }
                                        }
                                    }
                                }

                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("card_project_desc", "Select game executable file or game folder."); font.pixelSize: 12; color: Theme.txt2 }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 12
                                    TextField {
                                        id: projectPathField
                                        Layout.fillWidth: true; height: 40
                                        font.pixelSize: 12; color: Theme.txt
                                        selectByMouse: true
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

                                        function triggerShake() {
                                            shakeFieldAnim.restart()
                                        }

                                        background: Rectangle {
                                            radius: 8
                                            color: Theme.input
                                            border.color: projectPathField.hasError ? Theme.error : (projectPathField.activeFocus ? Theme.accent : Theme.cardBorder)
                                            border.width: projectPathField.hasError ? 1.5 : 1
                                            Behavior on border.color { ColorAnimation { duration: 150 } }

                                            // QW-3 Focus Ring Glow & Error Halo (macOS/Fluent tarzı ışıma)
                                            Rectangle {
                                                anchors.fill: parent
                                                anchors.margins: -3
                                                radius: parent.radius + 2
                                                color: "transparent"
                                                border.color: projectPathField.hasError ? Theme.error : Theme.accent
                                                border.width: 2
                                                opacity: projectPathField.hasError ? 0.65 : (projectPathField.activeFocus ? 0.35 : 0.0)
                                                scale: (projectPathField.hasError || projectPathField.activeFocus) ? 1.0 : 0.98
                                                Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutQuad } }
                                                Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                                                Behavior on border.color { ColorAnimation { duration: 180 } }
                                            }
                                        }
                                        Label {
                                            anchors.left: parent.left; anchors.leftMargin: 12
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("input_placeholder", "C:/Games/MyGame/MyGame.exe...")
                                            color: Theme.txtDim; font.pixelSize: 12; visible: projectPathField.text.length === 0 && !projectPathField.activeFocus
                                        }
                                    }
                                    Button {
                                        id: btnBrowseFolder
                                        height: 42
                                        Layout.preferredWidth: Math.max(115, implicitContentWidth + 32)
                                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("browse_folder", "Klasör")
                                        scale: down ? 0.96 : (hovered ? 1.03 : 1.0)
                                        transformOrigin: Item.Center
                                        Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                                        onClicked: folderDialog.open()
                                        background: Rectangle {
                                            radius: 10
                                            color: parent.down ? Theme.alpha(Theme.accent, 0.1) : (parent.hovered ? Theme.cardHover : Theme.input)
                                            border.color: parent.hovered ? Theme.alpha(Theme.accent, 0.6) : Theme.cardBorder
                                            border.width: parent.hovered ? 1.5 : 1
                                            Behavior on color { ColorAnimation { duration: 150 } }
                                            Behavior on border.color { ColorAnimation { duration: 150 } }
                                        }
                                        contentItem: IconLabel {
                                            glyph: Icons.folderOpen
                                            text: parent.text; color: parent.hovered ? Theme.accent : Theme.txt
                                            font.pixelSize: 13; font.bold: true
                                            Behavior on color { ColorAnimation { duration: 140 } }
                                        }
                                    }
                                    Button {
                                        id: btnBrowseExe
                                        height: 42
                                        Layout.preferredWidth: Math.max(135, implicitContentWidth + 32)
                                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("browse_exe", "EXE Dosyası")
                                        scale: down ? 0.96 : (hovered ? 1.03 : 1.0)
                                        transformOrigin: Item.Center
                                        Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                                        onClicked: fileDialog.open()
                                        background: Rectangle {
                                            radius: 10
                                            color: parent.down ? Theme.alpha(Theme.accent, 0.25) : (parent.hovered ? Theme.alpha(Theme.accent, 0.15) : Theme.input)
                                            border.color: parent.hovered ? Theme.accent : Theme.alpha(Theme.accent, 0.4)
                                            border.width: parent.hovered ? 1.5 : 1
                                            Behavior on color { ColorAnimation { duration: 150 } }
                                            Behavior on border.color { ColorAnimation { duration: 150 } }
                                        }
                                        contentItem: IconLabel {
                                            glyph: Icons.gamepad2
                                            text: parent.text; color: Theme.accent
                                            font.pixelSize: 13; font.bold: true
                                        }
                                    }
                                    Button {
                                        id: btnRecentProjects
                                        // Same height as the other buttons in the row; square background
                                        Layout.fillHeight: true
                                        Layout.preferredWidth: height - topInset - bottomInset
                                        enabled: appBackend.recentProjects.length > 0
                                        ToolTip.visible: hovered
                                        ToolTip.delay: 300
                                        ToolTip.text: appBackend.uiTrigger, appBackend.getTextWithDefault("recent_projects", "Recent projects")
                                        onClicked: recentPopup.open()
                                        background: Rectangle {
                                            radius: 10
                                            color: parent.down ? Theme.alpha(Theme.accent, 0.1) : (parent.hovered ? Theme.cardHover : Theme.input)
                                            border.color: parent.hovered ? Theme.alpha(Theme.accent, 0.6) : Theme.cardBorder
                                            border.width: 1
                                            Behavior on color { ColorAnimation { duration: 150 } }
                                        }
                                        contentItem: Item {
                                            Icon {
                                                anchors.centerIn: parent
                                                glyph: Icons.history
                                                size: 18
                                                color: !btnRecentProjects.enabled ? Theme.txtDim : (btnRecentProjects.hovered ? Theme.accent : Theme.txt)
                                            }
                                        }

                                        Popup {
                                            id: recentPopup
                                            y: parent.height + 6
                                            x: parent.width - width
                                            width: Math.min(520, root.width - 300)
                                            padding: 6
                                            background: Rectangle { color: Theme.card; radius: 10; border.color: Theme.cardBorder; border.width: 1 }
                                            contentItem: ColumnLayout {
                                                spacing: 2
                                                Label {
                                                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("recent_projects", "Recent projects")
                                                    color: Theme.txt2; font.pixelSize: 11; font.bold: true
                                                    Layout.leftMargin: 8; Layout.topMargin: 4; Layout.bottomMargin: 4
                                                }
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
                                                        background: Rectangle { radius: 6; color: recentRow.hovered ? Theme.alpha(Theme.accent, 0.12) : "transparent" }
                                                        contentItem: ColumnLayout {
                                                            spacing: 1
                                                            Label {
                                                                Layout.fillWidth: true
                                                                text: root.projectLabel(modelData)
                                                                color: Theme.txt; font.pixelSize: 12; font.bold: true
                                                                elide: Text.ElideRight
                                                            }
                                                            Label {
                                                                Layout.fillWidth: true
                                                                text: modelData
                                                                color: Theme.txtDim; font.pixelSize: 10
                                                                elide: Text.ElideMiddle
                                                            }
                                                        }
                                                    }
                                                }
                                                Rectangle { Layout.fillWidth: true; Layout.topMargin: 4; height: 1; color: Theme.cardBorder }
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
                                                        color: Theme.error; font.pixelSize: 11
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }

                                // Seçilen oyun: adı, Ren'Py sürümü, dosyaları, mevcut çeviriler ve çeviriyi
                                // durduracak durumlar (src/core/project_info.py, pipeline'ın kendi mesajlarıyla)
                                ColumnLayout {
                                    id: projectInfoStrip
                                    readonly property var info: appBackend.projectInfo
                                    readonly property bool shown: !!info && !!info.path && projectPathField.text.length > 0
                                    Layout.fillWidth: true
                                    Layout.topMargin: 2
                                    spacing: 8
                                    visible: shown

                                    function chips() {
                                        var i = info, out = []
                                        if (!i || !i.ok || i.tl_mode) return out
                                        if (i.renpy_version) out.push("Ren'Py " + i.renpy_version)
                                        if (i.rpy) out.push(i.rpy + " .rpy")
                                        if (i.rpyc) out.push(i.rpyc + " .rpyc")
                                        if (i.rpa) out.push(i.rpa + " .rpa")
                                        if (i.tl_languages && i.tl_languages.length)
                                            out.push(appBackend.getTextWithDefault("project_existing_translations", "Existing translations") + ": " + i.tl_languages.join(", "))
                                        return out
                                    }

                                    Flow {
                                        Layout.fillWidth: true
                                        spacing: 6
                                        visible: projectInfoStrip.shown && !!projectInfoStrip.info.ok && !projectInfoStrip.info.tl_mode
                                        Label {
                                            height: 22
                                            verticalAlignment: Text.AlignVCenter
                                            rightPadding: 4
                                            text: projectInfoStrip.shown ? (projectInfoStrip.info.name || "") + (projectInfoStrip.info.game_version ? "  " + projectInfoStrip.info.game_version : "") : ""
                                            color: Theme.txt; font.pixelSize: 13; font.bold: true
                                        }
                                        Repeater {
                                            model: appBackend.uiTrigger, projectInfoStrip.chips()
                                            delegate: Rectangle {
                                                height: 22; radius: 6
                                                width: chipLabel.implicitWidth + 14
                                                color: Theme.alpha(Theme.white, 0.04)
                                                border.color: Theme.cardBorder; border.width: 1
                                                Label {
                                                    id: chipLabel
                                                    anchors.centerIn: parent
                                                    text: modelData
                                                    color: Theme.txt2; font.pixelSize: 10; font.bold: true
                                                }
                                            }
                                        }
                                    }

                                    Repeater {
                                        model: projectInfoStrip.shown ? (projectInfoStrip.info.notices || []) : []
                                        delegate: RowLayout {
                                            Layout.fillWidth: true
                                            spacing: 8
                                            Icon {
                                                glyph: modelData.level === "warn" ? Icons.triangleAlert : Icons.info
                                                size: 14
                                                color: modelData.level === "warn" ? Theme.warn : Theme.accent
                                                Layout.alignment: Qt.AlignTop
                                                Layout.topMargin: 1
                                            }
                                            Label {
                                                Layout.fillWidth: true
                                                wrapMode: Text.WordWrap
                                                text: appBackend.uiTrigger, root.stripLeadingEmoji(appBackend.getTextWithDefault(modelData.key, modelData.default))
                                                color: modelData.level === "warn" ? Theme.warn : Theme.txt2
                                                font.pixelSize: 11
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // ── KART 2: TRANSLATION ENGINE & LANGUAGES ────────────
                    Rectangle {
                        id: cardEngine
                        Layout.fillWidth: true
                        property bool isAiEngine: appBackend.selectedEngine === "gemini" || appBackend.selectedEngine === "openai" || appBackend.selectedEngine === "deepseek" || appBackend.selectedEngine === "local_llm"
                        // İçeriğe göre: dar pencerede motor ve diller iki satıra iner
                        Layout.preferredHeight: engineCardCol.implicitHeight + 44
                        clip: true
                        radius: 16; color: cardEngine.hovered ? Theme.cardHover : Theme.card
                        border.color: cardEngine.hovered ? Theme.alpha(Theme.accent, 0.4) : Theme.cardBorder
                        border.width: 1
                        property bool hovered: false
                        scale: hovered ? 1.004 : 1.0
                        transformOrigin: Item.Center
                        Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                        Behavior on color { ColorAnimation { duration: 180 } }
                        Behavior on border.color { ColorAnimation { duration: 180 } }
                        Behavior on Layout.preferredHeight { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
                        HoverHandler { onHoveredChanged: cardEngine.hovered = hovered }

                        // QW-1 Staggered Entrance
                        transform: Translate { id: animTrEngine; y: 16 }
                        opacity: 0.0
                        SequentialAnimation {
                            id: animEntranceEngine
                            PauseAnimation { duration: 45 }
                            ParallelAnimation {
                                NumberAnimation { target: animTrEngine; property: "y"; to: 0; duration: 240; easing.type: Easing.OutCubic }
                                NumberAnimation { target: cardEngine; property: "opacity"; to: 1.0; duration: 220; easing.type: Easing.OutQuad }
                            }
                        }
                        Component.onCompleted: if (navIndex === 0) animEntranceEngine.start()
                        Connections { target: root; function onNavIndexChanged() { if (navIndex === 0) animEntranceEngine.restart() } }

                        ColumnLayout {
                            id: engineCardCol
                            anchors.fill: parent; anchors.margins: 22
                            spacing: 14

                            RowLayout {
                                Layout.fillWidth: true
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("card_engine_title", "Translation Engine & Languages"); font.pixelSize: 16; font.bold: true; color: Theme.txt }
                                Item { Layout.fillWidth: true }
                                IconLabel {
                                    id: aiParamLink
                                    visible: cardEngine.isAiEngine
                                    glyph: Icons.slidersHorizontal
                                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("advanced_settings_link", "Configure AI Parameters →")
                                    color: aiLinkMa.containsMouse ? Theme.white : Theme.accent
                                    font.pixelSize: 12
                                    font.underline: true
                                    scale: aiLinkMa.pressed ? 0.96 : (aiLinkMa.containsMouse ? 1.04 : 1.0)
                                    Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                                    Behavior on color { ColorAnimation { duration: 140 } }
                                    MouseArea {
                                        id: aiLinkMa
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: navIndex = 1
                                    }
                                }
                            }

                            // Dar pencerede (980 px) dört sütun sığmıyor: motor kendi
                            // satırına geçer, diller ve takas butonu altta kalır.
                            GridLayout {
                                id: engineLangGrid
                                Layout.fillWidth: true
                                readonly property bool narrow: width < 760
                                columns: narrow ? 3 : 4
                                columnSpacing: 12
                                rowSpacing: 12

                                // ── Motor Seçimi ──────────────────────────────────────
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.columnSpan: engineLangGrid.narrow ? 3 : 1
                                    Layout.preferredWidth: 260
                                    Layout.minimumWidth: 200
                                    spacing: 5
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("engine_label", "Machine Translation / AI Engine"); font.pixelSize: 11; color: Theme.txt2; font.bold: true }
                                    ComboBox {
                                        id: engineComboBox
                                        Layout.fillWidth: true; height: 40
                                        // Swapping engines mid-run would replace the translator the pipeline is using
                                        enabled: !isTranslating
                                        function engineModel() {
                                            appBackend.uiTrigger // Re-eval on language change
                                            return [
                                                {"id": "google", "icon": Icons.globe, "name": "Google Translate (" + appBackend.getTextWithDefault("engine_desc_google", "Primary / Free") + ")"},
                                                {"id": "bing", "icon": Icons.appWindow, "name": "Bing / Microsoft Edge (" + appBackend.getTextWithDefault("engine_desc_bing", "Free / No key") + ")"},
                                                {"id": "openai", "icon": Icons.bot, "name": "OpenAI / GPT-4o (" + appBackend.getTextWithDefault("engine_desc_ai", "AI Engine") + ")"},
                                                {"id": "gemini", "icon": Icons.sparkles, "name": "Gemini (" + appBackend.getTextWithDefault("engine_desc_gemini", "Google AI") + ")"},
                                                {"id": "deepseek", "icon": Icons.brain, "name": "DeepSeek AI (" + appBackend.getTextWithDefault("engine_desc_deepseek", "Fast / Economic") + ")"},
                                                {"id": "local_llm", "icon": Icons.monitor, "name": "Local LLM (Ollama / LM Studio)"},
                                                {"id": "libretranslate", "icon": Icons.bookOpen, "name": "LibreTranslate (" + appBackend.getTextWithDefault("engine_desc_local", "Self-hosted") + ")"},
                                                {"id": "custom", "icon": Icons.link, "name": "Custom Endpoint (" + appBackend.getTextWithDefault("engine_desc_custom", "Custom API") + ")"}
                                            ]
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
                                            radius: 8; color: Theme.input; border.color: parent.hovered ? Theme.accent : Theme.cardBorder; border.width: 1
                                            Behavior on border.color { ColorAnimation { duration: 150 } }
                                        }
                                        contentItem: IconLabel {
                                            alignment: Qt.AlignLeft; leftPadding: 14
                                            glyph: engineComboBox.currentIndex >= 0 ? engineComboBox.model[engineComboBox.currentIndex].icon : ""
                                            text: engineComboBox.displayText; color: Theme.txt; iconColor: Theme.accent; font.pixelSize: 12; elide: Text.ElideRight
                                        }
                                        delegate: ItemDelegate {
                                            width: engineComboBox.width
                                            contentItem: IconLabel { alignment: Qt.AlignLeft; leftPadding: 14; glyph: modelData.icon; text: modelData.name; color: Theme.txt; iconColor: Theme.txt2; font.pixelSize: 12; elide: Text.ElideRight }
                                            background: Rectangle { color: hovered ? Theme.alpha(Theme.accent, 0.12) : "transparent"; Behavior on color { ColorAnimation { duration: 120 } } }
                                        }
                                        popup: Popup { y: engineComboBox.height + 4; width: engineComboBox.width; implicitHeight: Math.min(contentItem.implicitHeight, 240); padding: 4; contentItem: ListView { clip: true; implicitHeight: contentHeight; model: engineComboBox.delegateModel; ScrollBar.vertical: ScrollBar {} } background: Rectangle { color: Theme.card; radius: 8; border.color: Theme.cardBorder; border.width: 1 } }
                                    }
                                }

                                // ── Kaynak Dil (2 Sütunlu Canlı Aranabilir Mega-Panel) ──
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 320
                                    Layout.minimumWidth: 220
                                    spacing: 5

                                    RowLayout {
                                        Layout.fillWidth: true
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("source_language", "Source Language"); font.pixelSize: 11; color: Theme.txt2; font.bold: true; Layout.fillWidth: true }
                                        RowLayout {
                                            spacing: 4
                                            Repeater {
                                                model: [
                                                    { name: "Auto", code: "auto" },
                                                    { name: "JA", code: "japanese" },
                                                    { name: "EN", code: "english" },
                                                    { name: "ZH", code: "chinese_s" },
                                                    { name: "KO", code: "korean" }
                                                ]
                                                delegate: Rectangle {
                                                    height: 19; width: qkSrcTxt.implicitWidth + 10; radius: 4
                                                    color: sourceLangCombo.currentValue === modelData.code ? Theme.alpha(Theme.accent, 0.22) : Theme.alpha(Theme.white, 0.05)
                                                    border.color: sourceLangCombo.currentValue === modelData.code ? Theme.accent : Theme.alpha(Theme.white, 0.1)
                                                    border.width: 1
                                                    Label {
                                                        id: qkSrcTxt; anchors.centerIn: parent; text: modelData.name; font.pixelSize: 10; font.bold: true
                                                        color: sourceLangCombo.currentValue === modelData.code ? Theme.accent : Theme.txtDim
                                                    }
                                                    MouseArea {
                                                        anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                                        onClicked: { appBackend.setSourceLanguage(modelData.code); sourceLangCombo.syncSourceLanguage() }
                                                    }
                                                }
                                            }
                                        }
                                    }

                                    ComboBox {
                                        id: sourceLangCombo
                                        Layout.fillWidth: true; height: 40
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
                                        background: Rectangle {
                                            radius: 8; color: Theme.input; border.color: parent.hovered ? Theme.accent : Theme.cardBorder; border.width: 1
                                            Behavior on border.color { ColorAnimation { duration: 150 } }
                                        }
                                        contentItem: IconLabel {
                                            readonly property bool auto: sourceLangCombo.currentValue === "auto" || sourceLangCombo.displayText === ""
                                            alignment: Qt.AlignLeft; leftPadding: 14
                                            glyph: auto ? Icons.scanSearch : ""
                                            text: sourceLangCombo.displayText !== "" ? sourceLangCombo.displayText : "Auto-detect"
                                            color: Theme.txt; iconColor: Theme.accent; font.pixelSize: 12; elide: Text.ElideRight
                                        }
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
                                }

                                // ── Dil Takas Butonu (Swap) ──────────────────────────
                                Button {
                                    id: btnSwapLanguages
                                    Layout.preferredWidth: 36
                                    Layout.preferredHeight: 36
                                    Layout.alignment: Qt.AlignBottom
                                    Layout.bottomMargin: 2
                                    ToolTip.visible: hovered
                                    ToolTip.text: appBackend.uiTrigger, appBackend.getTextWithDefault("swap_languages", "Kaynak ve hedef dilleri takas et")
                                    ToolTip.delay: 250

                                    background: Rectangle {
                                        radius: 8
                                        color: btnSwapLanguages.hovered ? Theme.alpha(Theme.accent, 0.15) : Theme.input
                                        border.color: btnSwapLanguages.hovered ? Theme.accent : Theme.cardBorder
                                        border.width: 1
                                        Behavior on color { ColorAnimation { duration: 120 } }
                                        Behavior on border.color { ColorAnimation { duration: 120 } }
                                    }

                                    contentItem: Label {
                                        text: "⇄"
                                        font.pixelSize: 16
                                        font.bold: true
                                        color: btnSwapLanguages.hovered ? Theme.white : Theme.accent
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                        rotation: btnSwapLanguages.pressed ? 180 : 0
                                        Behavior on rotation { NumberAnimation { duration: 250; easing.type: Easing.OutBack } }
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

                                // ── Hedef Dil (2 Sütunlu Canlı Aranabilir Mega-Panel) ──
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 320
                                    Layout.minimumWidth: 220
                                    spacing: 5

                                    RowLayout {
                                        Layout.fillWidth: true
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("target_language", "Target Language"); font.pixelSize: 11; color: Theme.txt2; font.bold: true; Layout.fillWidth: true }
                                        RowLayout {
                                            spacing: 4
                                            Repeater {
                                                model: [
                                                    { name: "TR", code: "turkish" },
                                                    { name: "EN", code: "english" },
                                                    { name: "DE", code: "german" },
                                                    { name: "ES", code: "spanish" },
                                                    { name: "RU", code: "russian" },
                                                    { name: "FR", code: "french" }
                                                ]
                                                delegate: Rectangle {
                                                    height: 19; width: qkTgtTxt.implicitWidth + 10; radius: 4
                                                    color: targetLangCombo.currentValue === modelData.code ? Theme.alpha(Theme.accent, 0.22) : Theme.alpha(Theme.white, 0.05)
                                                    border.color: targetLangCombo.currentValue === modelData.code ? Theme.accent : Theme.alpha(Theme.white, 0.1)
                                                    border.width: 1
                                                    Label {
                                                        id: qkTgtTxt; anchors.centerIn: parent; text: modelData.name; font.pixelSize: 10; font.bold: true
                                                        color: targetLangCombo.currentValue === modelData.code ? Theme.accent : Theme.txtDim
                                                    }
                                                    MouseArea {
                                                        anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                                        onClicked: { appBackend.setTargetLanguage(modelData.code); targetLangCombo.syncTargetLanguage() }
                                                    }
                                                }
                                            }
                                        }
                                    }

                                    ComboBox {
                                        id: targetLangCombo
                                        Layout.fillWidth: true; height: 40
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
                                        background: Rectangle {
                                            radius: 8; color: Theme.input; border.color: parent.hovered ? Theme.accent : Theme.cardBorder; border.width: 1
                                            Behavior on border.color { ColorAnimation { duration: 150 } }
                                        }
                                        contentItem: Label { leftPadding: 14; text: targetLangCombo.displayText; color: Theme.txt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
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
                                }
                            }

                            // Çıktı modu: Ayarlar'daki seçimin aynısı, çeviriden önce görünsün diye burada
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 6

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 8
                                    Label {
                                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("output_mode_label", "Output mode")
                                        font.pixelSize: 11; font.bold: true; color: Theme.txt2
                                        Layout.rightMargin: 4
                                    }
                                    Repeater {
                                        model: [
                                            { mode: "native", glyph: Icons.zap, key: "mode_native_btn", fallback: "Native TLID" },
                                            { mode: "strings", glyph: Icons.fileJson, key: "mode_strings_btn", fallback: "Standard (strings.json)" }
                                        ]
                                        delegate: Button {
                                            id: modeButton
                                            readonly property bool active: appBackend.outputMode === modelData.mode
                                            implicitHeight: 30
                                            topInset: 0; bottomInset: 0
                                            leftPadding: 12; rightPadding: 12
                                            enabled: !isTranslating
                                            onClicked: appBackend.outputMode = modelData.mode
                                            background: Rectangle {
                                                radius: 8
                                                color: modeButton.active ? Theme.alpha(Theme.accent, 0.15) : (modeButton.hovered ? Theme.cardHover : Theme.input)
                                                border.color: modeButton.active ? Theme.accent : Theme.cardBorder
                                                border.width: 1
                                                Behavior on color { ColorAnimation { duration: 140 } }
                                            }
                                            contentItem: IconLabel {
                                                glyph: modelData.glyph
                                                text: appBackend.uiTrigger, appBackend.getTextWithDefault(modelData.key, modelData.fallback)
                                                color: modeButton.active ? Theme.accent : Theme.txt2
                                                font.pixelSize: 11; font.bold: modeButton.active
                                            }
                                        }
                                    }
                                    Icon {
                                        glyph: Icons.info
                                        size: 14
                                        color: modeInfoHover.hovered ? Theme.accent : Theme.txtDim
                                        HoverHandler { id: modeInfoHover }
                                        ToolTip.visible: modeInfoHover.hovered
                                        ToolTip.delay: 200
                                        ToolTip.text: appBackend.uiTrigger, appBackend.outputMode === "native"
                                            ? appBackend.getTextWithDefault("desc_native_mode", "")
                                            : appBackend.getTextWithDefault("desc_strings_mode", "")
                                    }
                                    Item { Layout.fillWidth: true }
                                }

                                Label {
                                    Layout.fillWidth: true
                                    visible: appBackend.outputMode === "native"
                                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("output_mode_hint", "If part of the game's interface stays untranslated, switch to Standard and translate again.")
                                    color: Theme.txt2; font.pixelSize: 11
                                    wrapMode: Text.WordWrap
                                }
                            }

                            // ── AI HIZLI YAPILANDIRMA BARI (Dashboard Quick Config) ──
                            Rectangle {
                                Layout.fillWidth: true
                                height: 1
                                color: Theme.cardBorder
                                opacity: 0.6
                                visible: cardEngine.isAiEngine
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
                                            radius: 8; color: Theme.input; border.color: parent.activeFocus ? Theme.accent : Theme.cardBorder; border.width: 1
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
                                            radius: 8; color: Theme.input; border.color: parent.activeFocus ? Theme.accent : Theme.cardBorder; border.width: 1
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
                                            radius: 8; color: Theme.input; border.color: parent.hovered ? Theme.accent : Theme.cardBorder; border.width: 1
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
                                            radius: 8; color: Theme.input; border.color: parent.activeFocus ? Theme.accent : Theme.cardBorder; border.width: 1
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
                                            radius: 8; color: Theme.input; border.color: parent.activeFocus ? Theme.accent : Theme.cardBorder; border.width: 1
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
                                                radius: 8; color: Theme.input; border.color: parent.activeFocus ? Theme.accent : Theme.cardBorder; border.width: 1
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
                                            radius: 8; color: Theme.input; border.color: parent.activeFocus ? Theme.accent : Theme.cardBorder; border.width: 1
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
                                            radius: 8; color: Theme.input; border.color: parent.activeFocus ? Theme.accent : Theme.cardBorder; border.width: 1
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
                    }

                    // ── ANA AKSİYON BUTONU (NEON CYAN -> BLUE GRADIENT) ───
                    Button {
                        id: startButton
                        Layout.fillWidth: true
                        Layout.preferredHeight: 56
                        enabled: !isTranslating || currentStage !== "idle"

                        // QW-1 Staggered Entrance
                        transform: Translate { id: animTrStart; y: 16 }
                        opacity: 0.0
                        SequentialAnimation {
                            id: animEntranceStart
                            PauseAnimation { duration: 90 }
                            ParallelAnimation {
                                NumberAnimation { target: animTrStart; property: "y"; to: 0; duration: 240; easing.type: Easing.OutCubic }
                                NumberAnimation { target: startButton; property: "opacity"; to: 1.0; duration: 220; easing.type: Easing.OutQuad }
                            }
                        }
                        Component.onCompleted: if (navIndex === 0) animEntranceStart.start()
                        Connections { target: root; function onNavIndexChanged() { if (navIndex === 0) animEntranceStart.restart() } }

                        // Modern mikro-etkileşim: Hover'da 1.015x büyüme, tıklandığında 0.97x basılma hissi
                        scale: down ? 0.97 : (hovered ? 1.015 : 1.0)
                        transformOrigin: Item.Center
                        Behavior on scale {
                            NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
                        }

                        onClicked: {
                            if (isTranslating) {
                                appBackend.stopTranslation()
                            } else {
                                if (!projectPathField.text || projectPathField.text.trim().length === 0) {
                                    projectPathField.triggerShake()
                                    showToast(appBackend.getTextWithDefault("log_select_game", "Lütfen bir oyun klasörü veya EXE seçin."), "warning")
                                    return
                                }
                                appBackend.startTranslation()
                            }
                        }
                        background: Rectangle {
                            id: startBtnBg
                            radius: 14

                            // Çeviri sırasında çalışan nefes alma (pulsating) animasyonu
                            SequentialAnimation on opacity {
                                running: isTranslating && navIndex === 0
                                loops: Animation.Infinite
                                NumberAnimation { to: 0.78; duration: 900; easing.type: Easing.InOutQuad }
                                NumberAnimation { to: 1.0;  duration: 900; easing.type: Easing.InOutQuad }
                            }

                            gradient: Gradient {
                                orientation: Gradient.Horizontal
                                GradientStop {
                                    position: 0.0
                                    color: isTranslating ? (startButton.hovered ? Theme.errorHover : Theme.error) : (startButton.hovered ? Theme.accent2 : Theme.accent)
                                    Behavior on color { ColorAnimation { duration: 180; easing.type: Easing.OutQuad } }
                                }
                                GradientStop {
                                    position: 1.0
                                    color: isTranslating ? (startButton.hovered ? Theme.error : Theme.errorStrong) : (startButton.hovered ? Theme.accent : Theme.accent2)
                                    Behavior on color { ColorAnimation { duration: 180; easing.type: Easing.OutQuad } }
                                }
                            }

                            // Dış neon ışıma katmanı (Glow border)
                            Rectangle {
                                anchors.fill: parent
                                radius: parent.radius
                                color: "transparent"
                                border.color: isTranslating ? Theme.error : Theme.accent
                                border.width: startButton.hovered || isTranslating ? 2 : 0
                                opacity: startButton.hovered || isTranslating ? 0.6 : 0.0
                                Behavior on opacity { NumberAnimation { duration: 180 } }
                                Behavior on border.width { NumberAnimation { duration: 150 } }
                            }

                            // Oyun seçilmeden buton soluk durur (tıklanınca yol kutusu sallanır)
                            Rectangle {
                                anchors.fill: parent
                                radius: parent.radius
                                color: Theme.alpha(Theme.bg, 0.5)
                                visible: !isTranslating && projectPathField.text.trim().length === 0
                            }
                        }
                        contentItem: Item {
                            Row {
                                anchors.centerIn: parent
                                spacing: 12

                                Item {
                                    width: 18; height: 18
                                    anchors.verticalCenter: parent.verticalCenter

                                    // STOP İkonu (Windows'un mavi emoji çizmesini önleyen saf beyaz yuvarlatılmış kare)
                                    Rectangle {
                                        anchors.centerIn: parent
                                        width: 14; height: 14; radius: 3
                                        color: Theme.white
                                        visible: isTranslating
                                        scale: isTranslating ? (startBtnBg.opacity < 0.9 ? 0.92 : 1.08) : 1.0
                                        Behavior on scale { NumberAnimation { duration: 400; easing.type: Easing.InOutQuad } }
                                    }

                                    // START ikonu
                                    Icon {
                                        anchors.centerIn: parent
                                        glyph: Icons.zap
                                        size: 18
                                        color: Theme.textOnAccent
                                        visible: !isTranslating
                                    }
                                }

                                Label {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: appBackend.uiTrigger, isTranslating ? appBackend.getTextWithDefault("btn_stop_translation", "STOP TRANSLATION") : appBackend.getTextWithDefault("btn_start_translation", "START TRANSLATION →")
                                    font.pixelSize: 16; font.bold: true
                                    color: isTranslating ? Theme.white : (startButton.hovered ? Theme.textOnAccent : Theme.textOnAccent)
                                    font.letterSpacing: 1.1
                                }
                            }
                        }
                    }

                    // ── KART 3: PROCESS STATUS (DURUM BARI) ───────────────
                    Rectangle {
                        id: cardStatus
                        Layout.fillWidth: true
                        Layout.preferredHeight: statusInnerCol.implicitHeight + 44
                        radius: 16; color: cardStatus.hovered ? Theme.cardHover : Theme.card
                        border.color: cardStatus.hovered ? Theme.alpha(Theme.accent, 0.4) : Theme.cardBorder
                        border.width: 1
                        property bool hovered: false
                        scale: hovered ? 1.004 : 1.0
                        transformOrigin: Item.Center
                        Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                        Behavior on color { ColorAnimation { duration: 180 } }
                        Behavior on border.color { ColorAnimation { duration: 180 } }
                        Behavior on Layout.preferredHeight { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }
                        HoverHandler { onHoveredChanged: cardStatus.hovered = hovered }

                        // QW-1 Staggered Entrance
                        transform: Translate { id: animTrStatus; y: 16 }
                        opacity: 0.0
                        SequentialAnimation {
                            id: animEntranceStatus
                            PauseAnimation { duration: 135 }
                            ParallelAnimation {
                                NumberAnimation { target: animTrStatus; property: "y"; to: 0; duration: 240; easing.type: Easing.OutCubic }
                                NumberAnimation { target: cardStatus; property: "opacity"; to: 1.0; duration: 220; easing.type: Easing.OutQuad }
                            }
                        }
                        Component.onCompleted: if (navIndex === 0) animEntranceStatus.start()
                        Connections { target: root; function onNavIndexChanged() { if (navIndex === 0) animEntranceStatus.restart() } }

                        ColumnLayout {
                            id: statusInnerCol
                            anchors.fill: parent; anchors.margins: 22
                            spacing: 14

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("card_status_title", "Process Status"); font.pixelSize: 16; font.bold: true; color: Theme.txt }
                                Item { Layout.fillWidth: true }

                                // Canlı aktivite sonar noktası (Radar Pulse Dot)
                                Rectangle {
                                    id: stageActivityDot
                                    width: 8; height: 8; radius: 4
                                    color: currentStage === "completed" ? Theme.success : (isTranslating ? Theme.accent : "transparent")
                                    visible: isTranslating || currentStage === "completed"
                                    scale: isTranslating || currentStage === "completed" ? 1.0 : 0.0

                                    Behavior on color { ColorAnimation { duration: 250 } }
                                    Behavior on scale { NumberAnimation { duration: 200; easing.type: Easing.OutBack } }

                                    Rectangle {
                                        anchors.centerIn: parent
                                        width: parent.width; height: parent.height; radius: width / 2
                                        color: parent.color
                                        opacity: 0.0

                                        SequentialAnimation on scale {
                                            running: isTranslating && navIndex === 0
                                            loops: Animation.Infinite
                                            NumberAnimation { from: 1.0; to: 2.6; duration: 1100; easing.type: Easing.OutQuad }
                                        }
                                        SequentialAnimation on opacity {
                                            running: isTranslating && navIndex === 0
                                            loops: Animation.Infinite
                                            NumberAnimation { from: 0.8; to: 0.0; duration: 1100; easing.type: Easing.OutQuad }
                                        }
                                    }
                                }

                                Row {
                                    spacing: 1
                                    Layout.alignment: Qt.AlignVCenter

                                    Label {
                                        id: stageLabel
                                        text: appBackend.uiTrigger, getStageDisplayText(currentStage)
                                        font.pixelSize: 13; font.bold: true
                                        color: currentStage === "completed" ? Theme.success : (currentStage === "error" ? Theme.error : Theme.accent)
                                        scale: currentStage === "completed" ? 1.06 : 1.0
                                        transformOrigin: Item.Right

                                        Behavior on color {
                                            ColorAnimation { duration: 250 }
                                        }
                                        Behavior on scale {
                                            NumberAnimation { duration: 320; easing.type: Easing.OutBack; easing.overshoot: 1.6 }
                                        }
                                    }

                                    // Akıcı canlı üç-nokta nabzı (Live Ellipsis Flow - Anti-Freeze Indicator)
                                    Label {
                                        id: stageDots
                                        text: dotCount === 0 ? "" : (dotCount === 1 ? "." : (dotCount === 2 ? ".." : "..."))
                                        property int dotCount: 0
                                        font.pixelSize: 13; font.bold: true
                                        color: Theme.accent
                                        visible: isTranslating
                                        width: 14
                                        height: stageLabel.height
                                        verticalAlignment: Text.AlignVCenter

                                        Timer {
                                            interval: 400
                                            repeat: true
                                            running: isTranslating && navIndex === 0
                                            onTriggered: stageDots.dotCount = (stageDots.dotCount + 1) % 4
                                        }
                                    }
                                }
                            }

                            // İlerleme Barı (Akıcı dolum & Shimmer animasyonu)
                            ProgressBar {
                                id: progressBar
                                Layout.fillWidth: true; height: 12
                                value: 0.0

                                background: Rectangle {
                                    radius: 6
                                    color: Theme.input
                                    border.color: Theme.alpha(Theme.white, 0.06)
                                    border.width: 1
                                }

                                contentItem: Item {
                                    clip: true

                                    Rectangle {
                                        id: progressFill
                                        width: progressBar.visualPosition * parent.width
                                        height: parent.height
                                        radius: 6

                                        Behavior on width {
                                            NumberAnimation { duration: 250; easing.type: Easing.OutCubic }
                                        }

                                        gradient: Gradient {
                                            orientation: Gradient.Horizontal
                                            GradientStop { position: 0.0; color: Theme.accent }
                                            GradientStop { position: 1.0; color: Theme.accent2 }
                                        }
                                    }

                                    // İşlem sürerken tüm bar boyunca süzülen tarama ışığı (Full-Bar Scanning Shimmer)
                                    Rectangle {
                                        id: progressShimmer
                                        width: 72
                                        height: parent.height
                                        visible: isTranslating
                                        radius: 6
                                        gradient: Gradient {
                                            orientation: Gradient.Horizontal
                                            GradientStop { position: 0.0; color: "transparent" }
                                            GradientStop { position: 0.2; color: Theme.alpha(Theme.white, 0.08) }
                                            GradientStop { position: 0.5; color: Theme.alpha(Theme.white, 0.38) }
                                            GradientStop { position: 0.8; color: Theme.alpha(Theme.white, 0.08) }
                                            GradientStop { position: 1.0; color: "transparent" }
                                        }

                                        NumberAnimation on x {
                                            running: isTranslating && navIndex === 0
                                            loops: Animation.Infinite
                                            from: -progressShimmer.width
                                            to: progressBar.width + progressShimmer.width
                                            duration: 1800
                                            easing.type: Easing.Linear
                                        }
                                    }
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                Label { id: progressLabel; text: appBackend.uiTrigger, appBackend.getTextWithDefault("lines_processed", "Processed lines: 0 / 0 lines"); font.pixelSize: 12; color: Theme.txt2 }
                                Item { Layout.fillWidth: true }
                                Label { text: Math.round(progressBar.value * 100) + "%"; font.pixelSize: 13; font.bold: true; color: Theme.txt }
                            }

                            // İstatistik Kartı Açılımı (QW-2 Celebration Spring & Badge Bounce)
                            RowLayout {
                                id: statsRow
                                Layout.fillWidth: true
                                visible: statsVisible

                                Rectangle {
                                    id: statsBannerRect
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 46
                                    radius: 10
                                    color: Theme.successDim
                                    border.color: Theme.success
                                    border.width: 1
                                    clip: true

                                    scale: statsVisible ? 1.0 : 0.90
                                    opacity: statsVisible ? 1.0 : 0.0
                                    transformOrigin: Item.Center

                                    Behavior on scale {
                                        NumberAnimation { duration: 320; easing.type: Easing.OutBack; easing.overshoot: 1.4 }
                                    }
                                    Behavior on opacity {
                                        NumberAnimation { duration: 220; easing.type: Easing.OutQuad }
                                    }

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 12
                                        anchors.rightMargin: 14
                                        spacing: 10

                                        // Kutlama rozeti (Spring bounce tick)
                                        Rectangle {
                                            id: successBadge
                                            width: 24; height: 24; radius: 12
                                            color: Theme.success
                                            scale: statsVisible ? 1.0 : 0.0
                                            opacity: statsVisible ? 1.0 : 0.0
                                            transformOrigin: Item.Center

                                            Behavior on scale {
                                                NumberAnimation { duration: 420; easing.type: Easing.OutBack; easing.overshoot: 1.8 }
                                            }
                                            Behavior on opacity {
                                                NumberAnimation { duration: 200 }
                                            }

                                            Label {
                                                anchors.centerIn: parent
                                                text: "✓"
                                                color: Theme.white
                                                font.bold: true
                                                font.pixelSize: 13
                                            }
                                        }

                                        Label {
                                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("stats_completed_banner", "Çeviri Başarıyla Tamamlandı!")
                                            font.bold: true
                                            color: Theme.success
                                            font.pixelSize: 13
                                        }

                                        Item { Layout.fillWidth: true }

                                        Label {
                                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("stats_summary_total", "Toplam:") + " " + totalLines + " | " + appBackend.getTextWithDefault("stats_summary_translated", "Çevrilen:") + " " + translatedLines + " (" + successRate.toFixed(1) + "%)"
                                            color: Theme.txt
                                            font.pixelSize: 13
                                            font.bold: true
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // ── KART 4: LOG CONSOLE SUMMARY (MİNİ LOG PANELİ) ───────
                    Rectangle {
                        id: cardLog
                        Layout.fillWidth: true
                        Layout.preferredHeight: 185
                        radius: 16; color: cardLog.hovered ? Theme.cardHover : Theme.card
                        border.color: cardLog.hovered ? Theme.alpha(Theme.accent, 0.4) : Theme.cardBorder
                        border.width: 1
                        property bool hovered: false
                        scale: hovered ? 1.004 : 1.0
                        transformOrigin: Item.Center
                        Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                        Behavior on color { ColorAnimation { duration: 180 } }
                        Behavior on border.color { ColorAnimation { duration: 180 } }
                        HoverHandler { onHoveredChanged: cardLog.hovered = hovered }

                        // QW-1 Staggered Entrance
                        transform: Translate { id: animTrLog; y: 16 }
                        opacity: 0.0
                        SequentialAnimation {
                            id: animEntranceLog
                            PauseAnimation { duration: 180 }
                            ParallelAnimation {
                                NumberAnimation { target: animTrLog; property: "y"; to: 0; duration: 240; easing.type: Easing.OutCubic }
                                NumberAnimation { target: cardLog; property: "opacity"; to: 1.0; duration: 220; easing.type: Easing.OutQuad }
                            }
                        }
                        Component.onCompleted: if (navIndex === 0) animEntranceLog.start()
                        Connections { target: root; function onNavIndexChanged() { if (navIndex === 0) animEntranceLog.restart() } }

                        ColumnLayout {
                            anchors.fill: parent; anchors.margins: 18
                            spacing: 10

                            RowLayout {
                                Layout.fillWidth: true
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("card_log_title", "Log Console Summary"); font.pixelSize: 16; font.bold: true; color: Theme.txt }
                                Item { Layout.fillWidth: true }
                                Button {
                                    height: 28; text: appBackend.uiTrigger, appBackend.getTextWithDefault("view_all_logs", "Tüm Logları Aç →")
                                    scale: down ? 0.96 : (hovered ? 1.04 : 1.0)
                                    transformOrigin: Item.Center
                                    Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                                    onClicked: navIndex = 2
                                    background: Rectangle {
                                        radius: 6
                                        color: parent.hovered ? Theme.alpha(Theme.accent, 0.1) : "transparent"
                                        Behavior on color { ColorAnimation { duration: 140 } }
                                    }
                                    contentItem: IconLabel {
                                        glyph: Icons.terminal
                                        text: parent.text; color: parent.hovered ? Theme.white : Theme.accent
                                        font.pixelSize: 12; font.underline: true
                                        Behavior on color { ColorAnimation { duration: 140 } }
                                    }
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true; Layout.fillHeight: true; radius: 10; color: Theme.input; border.color: Theme.cardBorder; border.width: 1
                                ListView {
                                    id: logListView
                                    anchors.fill: parent; anchors.margins: 10; clip: true
                                    model: logModel
                                    delegate: RowLayout {
                                        width: logListView.width - 20; spacing: 12
                                        Label { text: model.ts; color: Theme.txtDim; font.pixelSize: 11; font.family: "Consolas" }
                                        Label { text: logPrefix(model.level); color: logColor(model.level); font.bold: true; font.pixelSize: 11 }
                                        Label { text: model.message; color: logColor(model.level); font.pixelSize: 11; Layout.fillWidth: true; elide: Text.ElideRight }
                                    }
                                }
                            }
                        }
                    }

                    Item { height: 24 }
                }
            }
        }

            // ═════════════════════════════════════════════════════════════
            // SEKME 1: SETTINGS (TAM SAYFA GELİŞMİŞ AYARLAR)
            // ═════════════════════════════════════════════════════════════
            Item {
                id: pageSettings
                Layout.fillWidth: true
                Layout.fillHeight: true

                property int settingsSubTab: 0 // 0: Genel & Çıktı, 1: Yapay Zeka (AI), 2: Performans & Ağ

                // ── SABİT STICKY HEADER & SUB-NAVIGATION ──────────────
                PageHeader {
                    id: settingsStickyHeader
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    glyph: Icons.settings
                    title: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_settings", "Settings & Advanced Configuration")
                    subtitle: appBackend.uiTrigger, appBackend.getTextWithDefault("settings_desc", "Configure UI language, translation threads, AI endpoints, and caching.")

                    // Segmented Sub-Tab Bar
                    RowLayout {
                        spacing: 8

                        Button {
                            height: 34
                            Layout.preferredWidth: Math.max(150, implicitContentWidth + 24)
                            onClicked: pageSettings.settingsSubTab = 0
                            background: Rectangle {
                                radius: 8
                                color: pageSettings.settingsSubTab === 0 ? Theme.alpha(Theme.accent, 0.15) : (parent.hovered ? Theme.cardHover : "transparent")
                                border.color: pageSettings.settingsSubTab === 0 ? Theme.accent : Theme.cardBorder
                                border.width: 1
                                Behavior on color { ColorAnimation { duration: 140 } }
                            }
                            contentItem: IconLabel {
                                glyph: Icons.monitor
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("subtab_general", "Genel & Çıktı")
                                color: pageSettings.settingsSubTab === 0 ? Theme.accent : Theme.txt2
                                font.bold: pageSettings.settingsSubTab === 0
                                font.pixelSize: 12
                            }
                        }

                        Button {
                            height: 34
                            Layout.preferredWidth: Math.max(160, implicitContentWidth + 24)
                            onClicked: pageSettings.settingsSubTab = 1
                            background: Rectangle {
                                radius: 8
                                color: pageSettings.settingsSubTab === 1 ? Theme.alpha(Theme.accent, 0.15) : (parent.hovered ? Theme.cardHover : "transparent")
                                border.color: pageSettings.settingsSubTab === 1 ? Theme.accent : Theme.cardBorder
                                border.width: 1
                                Behavior on color { ColorAnimation { duration: 140 } }
                            }
                            contentItem: IconLabel {
                                glyph: Icons.bot
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("subtab_ai", "Yapay Zeka (AI)")
                                color: pageSettings.settingsSubTab === 1 ? Theme.accent : Theme.txt2
                                font.bold: pageSettings.settingsSubTab === 1
                                font.pixelSize: 12
                            }
                        }

                        Button {
                            height: 34
                            Layout.preferredWidth: Math.max(160, implicitContentWidth + 24)
                            onClicked: pageSettings.settingsSubTab = 2
                            background: Rectangle {
                                radius: 8
                                color: pageSettings.settingsSubTab === 2 ? Theme.alpha(Theme.accent, 0.15) : (parent.hovered ? Theme.cardHover : "transparent")
                                border.color: pageSettings.settingsSubTab === 2 ? Theme.accent : Theme.cardBorder
                                border.width: 1
                                Behavior on color { ColorAnimation { duration: 140 } }
                            }
                            contentItem: IconLabel {
                                glyph: Icons.gauge
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("subtab_perf", "Performans & Ağ")
                                color: pageSettings.settingsSubTab === 2 ? Theme.accent : Theme.txt2
                                font.bold: pageSettings.settingsSubTab === 2
                                font.pixelSize: 12
                            }
                        }

                        Item { Layout.fillWidth: true }
                    }
                }

                // ── KAYDIRILABİLİR İÇERİK ALANI ───────────────────────
                ScrollView {
                    id: viewSettings
                    anchors.top: settingsStickyHeader.bottom
                    anchors.bottom: parent.bottom
                    anchors.left: parent.left
                    anchors.right: parent.right
                    clip: true
                    contentWidth: availableWidth
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                    ScrollBar.vertical: ScrollBar {}

                    transform: Translate { id: animTrSettings; y: 14 }
                    opacity: 0.0
                    ParallelAnimation {
                        id: animEntranceSettings
                        NumberAnimation { target: animTrSettings; property: "y"; from: 14; to: 0; duration: 220; easing.type: Easing.OutCubic }
                        NumberAnimation { target: viewSettings; property: "opacity"; from: 0.0; to: 1.0; duration: 180; easing.type: Easing.OutQuad }
                    }
                    onVisibleChanged: if (visible) animEntranceSettings.restart()

                    ColumnLayout {
                        width: Math.min(parent.width - 48, 1180)
                        anchors.horizontalCenter: parent.horizontalCenter
                        spacing: 20

                        Item { height: 8 }

                    // 1. ARAYÜZ & SİSTEM AYARLARI KARTI (GENEL SEKME)
                    Rectangle {
                        id: cardUiSettings
                        visible: pageSettings.settingsSubTab === 0
                        Layout.fillWidth: true
                        Layout.preferredHeight: 160
                        radius: 16; color: Theme.card; border.color: Theme.cardBorder; border.width: 1

                        ColumnLayout {
                            anchors.fill: parent; anchors.margins: 22; spacing: 14
                            IconLabel { alignment: Qt.AlignLeft; glyph: Icons.monitor; text: appBackend.uiTrigger, appBackend.getTextWithDefault("settings_section_ui", "Arayüz & Sistem Ayarları"); font.pixelSize: 16; font.bold: true; color: Theme.txt; iconColor: Theme.accent }

                            RowLayout {
                                Layout.fillWidth: true
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ui_language_label", "Arayüz Dili (UI Language):"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                ComboBox {
                                    id: uiLanguageCombo
                                    Layout.preferredWidth: 240; height: 38
                                    model: appBackend.getAvailableUILanguages()
                                    textRole: "name"; valueRole: "code"
                                    function syncUILanguage() {
                                        var cur = appBackend.getCurrentUILanguage() || "en"
                                        var idx = uiLanguageCombo.indexOfValue(cur)
                                        if (idx >= 0) uiLanguageCombo.currentIndex = idx
                                    }
                                    Component.onCompleted: syncUILanguage()
                                    Connections {
                                        target: appBackend
                                        function onUiTriggerChanged() { uiLanguageCombo.syncUILanguage() }
                                    }
                                    background: Rectangle { radius: 8; color: Theme.input; border.color: Theme.cardBorder; border.width: 1 }
                                    contentItem: Label { leftPadding: 14; text: uiLanguageCombo.displayText; color: Theme.txt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
                                    onActivated: appBackend.setUILanguage(currentValue)
                                    delegate: ItemDelegate { width: uiLanguageCombo.width; contentItem: Label { text: modelData.name; color: Theme.txt; font.pixelSize: 12; leftPadding: 14 } background: Rectangle { color: hovered ? Theme.alpha(Theme.accent, 0.12) : "transparent" } }
                                    popup: Popup { y: uiLanguageCombo.height; width: uiLanguageCombo.width; implicitHeight: 240; padding: 4; contentItem: ListView { clip: true; model: uiLanguageCombo.delegateModel; ScrollBar.vertical: ScrollBar {} } background: Rectangle { color: Theme.card; radius: 8; border.color: Theme.cardBorder; border.width: 1 } }
                                }
                                Item { Layout.fillWidth: true }
                            }

                            RowLayout {
                                Layout.fillWidth: true; spacing: 16
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 2
                                    IconLabel { alignment: Qt.AlignLeft; glyph: Icons.bell; text: appBackend.uiTrigger, appBackend.getTextWithDefault("enable_desktop_notifications_label", "Masaüstü Bildirimleri"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("enable_desktop_notifications_tooltip", "Çeviri tamamlandığında veya hata oluştuğunda masaüstü bildirimi göster."); color: Theme.txt2; font.pixelSize: 11; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                }
                                Switch {
                                    checked: appBackend.enableDesktopNotifications
                                    onToggled: appBackend.enableDesktopNotifications = checked
                                }
                            }
                        }
                    }

                    // 2. ÇIKTI ÜRETİM MODU & ÇEVİRİ BELLEĞİ (NATIVE TLID vs STRINGS & TM CACHE)
                    Rectangle {
                        id: cardOutputSettings
                        visible: pageSettings.settingsSubTab === 0
                        Layout.fillWidth: true
                        Layout.preferredHeight: outCol.implicitHeight + 44
                        radius: 16; color: Theme.card; border.color: Theme.cardBorder; border.width: 1
                        Behavior on Layout.preferredHeight { NumberAnimation { duration: 200 } }

                        ColumnLayout {
                            id: outCol
                            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                            anchors.margins: 22; spacing: 18

                            IconLabel { alignment: Qt.AlignLeft; glyph: Icons.packageBox; text: appBackend.uiTrigger, appBackend.getTextWithDefault("settings_section_output", "Çıktı Üretim Modu & Çeviri Belleği (Output & TM Cache)"); font.pixelSize: 16; font.bold: true; color: Theme.txt; iconColor: Theme.accent }

                            // KATMAN 1: GÖRSEL ÇİFT BUTONLU SEGMENTED SEÇİCİ (STRINGS vs NATIVE TLID)
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 10

                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_output_mode", "Ren'Py Çıktı Formatı Seçimi (Output Generation Mode):"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }

                                RowLayout {
                                    Layout.fillWidth: true; spacing: 14

                                    // Buton 1: Strings Modu
                                    Button {
                                        id: btnStringsMode
                                        Layout.fillWidth: true; height: 48
                                        onClicked: appBackend.outputMode = "strings"

                                        background: Rectangle {
                                            radius: 10
                                            color: appBackend.outputMode === "strings" ? Theme.alpha(Theme.accent, 0.15) : (btnStringsMode.hovered ? Theme.alpha(Theme.white, 0.08) : Theme.input)
                                            border.color: appBackend.outputMode === "strings" ? Theme.accent : Theme.cardBorder
                                            border.width: appBackend.outputMode === "strings" ? 2 : 1
                                            Behavior on color { ColorAnimation { duration: 150 } }
                                        }

                                        contentItem: RowLayout {
                                            anchors.centerIn: parent; spacing: 8
                                            Item { Layout.fillWidth: true }
                                            Label { text: appBackend.outputMode === "strings" ? "●" : "○"; color: appBackend.outputMode === "strings" ? Theme.accent : Theme.txtDim; font.pixelSize: 16 }
                                            Icon { glyph: Icons.fileJson; size: 14; color: appBackend.outputMode === "strings" ? Theme.accent : Theme.txt2 }
                                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("mode_strings_btn", "Standard (strings.json)"); color: appBackend.outputMode === "strings" ? Theme.accent : Theme.txt; font.bold: appBackend.outputMode === "strings"; font.pixelSize: 12 }
                                            Item { Layout.fillWidth: true }
                                        }
                                    }

                                    // Buton 2: Native TLID Modu
                                    Button {
                                        id: btnNativeMode
                                        Layout.fillWidth: true; height: 48
                                        onClicked: appBackend.outputMode = "native"

                                        background: Rectangle {
                                            radius: 10
                                            color: appBackend.outputMode === "native" ? Theme.alpha(Theme.accent, 0.15) : (btnNativeMode.hovered ? Theme.alpha(Theme.white, 0.08) : Theme.input)
                                            border.color: appBackend.outputMode === "native" ? Theme.accent : Theme.cardBorder
                                            border.width: appBackend.outputMode === "native" ? 2 : 1
                                            Behavior on color { ColorAnimation { duration: 150 } }
                                        }

                                        contentItem: RowLayout {
                                            anchors.centerIn: parent; spacing: 6
                                            Item { Layout.fillWidth: true }
                                            Label { text: appBackend.outputMode === "native" ? "●" : "○"; color: appBackend.outputMode === "native" ? Theme.accent : Theme.txtDim; font.pixelSize: 16 }
                                            Icon { glyph: Icons.zap; size: 14; color: appBackend.outputMode === "native" ? Theme.accent : Theme.txt2 }
                                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("mode_native_btn", "Native TLID"); color: appBackend.outputMode === "native" ? Theme.accent : Theme.txt; font.bold: appBackend.outputMode === "native"; font.pixelSize: 12 }
                                            IconLabel { glyph: Icons.sparkles; text: appBackend.uiTrigger, appBackend.getTextWithDefault("badge_recommended", "Recommended"); color: Theme.success; font.pixelSize: 10; font.bold: true; spacing: 4; Layout.leftMargin: 6 }
                                            Item { Layout.fillWidth: true }
                                        }
                                    }
                                }

                                Rectangle {
                                    Layout.fillWidth: true; Layout.preferredHeight: descLayout.implicitHeight + 16
                                    radius: 8; color: Theme.alpha(Theme.white, 0.03); border.color: Theme.cardBorder; border.width: 1
                                    RowLayout {
                                        id: descLayout; anchors.fill: parent; anchors.margins: 8; spacing: 8
                                        Icon { glyph: Icons.lightbulb; size: 14; color: Theme.txt2; Layout.alignment: Qt.AlignTop }
                                        Label {
                                            id: descLabel; Layout.fillWidth: true; wrapMode: Text.WordWrap
                                            text: appBackend.outputMode === "native" ?
                                                  (appBackend.uiTrigger, appBackend.getTextWithDefault("desc_native_mode", "Ren'Py built-in translate blocks for dialogues + auto-export translate strings: for UI. Zero Python scripts during gameplay — pure native speed. Works for ~90% of games. Known limitation: Python {variable} texts and runtime-concatenated strings may not be captured. Switch to Standard if you see untranslated screen elements.")) :
                                                  (appBackend.uiTrigger, appBackend.getTextWithDefault("desc_strings_mode", "Full runtime hook with O(1) lookup, MRU cache, screen harvesting, template matching, RTL. Handles ALL text types including dynamic and concatenated strings. Slightly higher memory (~3 MB). Recommended for complex screen UIs or when Native TLID misses text."))
                                            color: Theme.txt2; font.pixelSize: 11
                                        }
                                    }
                                }

                                // Tip: when to use Standard mode
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: tipLayout.implicitHeight + 16
                                    radius: 8; color: Theme.alpha(Theme.warn, 0.08); border.color: Theme.alpha(Theme.warn, 0.25); border.width: 1
                                    visible: appBackend.outputMode === "native"
                                    RowLayout {
                                        id: tipLayout
                                        anchors.fill: parent; anchors.margins: 8; spacing: 8
                                        Icon { glyph: Icons.triangleAlert; size: 14; color: Theme.warn; Layout.alignment: Qt.AlignTop }
                                        Label {
                                            id: tipLabel; Layout.fillWidth: true; wrapMode: Text.WordWrap
                                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("tip_native_limitation", "Some games define UI text in Python variables (quests, schedules, etc.). If you see untranslated screen text, switch to Standard mode — it handles these better.")
                                            color: Theme.warn; font.pixelSize: 11
                                        }
                                    }
                                }
                            }

                            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.cardBorder }

                            // Dil etkinleştirme dosyası (game/zzz_<lang>_language.rpy)
                            RowLayout {
                                Layout.fillWidth: true; spacing: 10
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("activate_language_title", "Start the game in the translated language"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("activate_language_desc", "Adds a small file to game/ that switches the game to the target language at launch. Turn off if you only want the tl/ files (e.g. to ship the translation yourself and let players choose the language)."); color: Theme.txt2; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                                }
                                Switch { checked: appBackend.activateLanguageOnLaunch; onToggled: appBackend.activateLanguageOnLaunch = checked }
                            }

                            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.cardBorder }

                            // KATMAN 2: ÇEVİRİ BELLEĞİ (TM CACHE) TOGGLE
                            RowLayout {
                                Layout.fillWidth: true; spacing: 16

                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 3
                                    IconLabel { alignment: Qt.AlignLeft; glyph: Icons.database; text: appBackend.uiTrigger, appBackend.getTextWithDefault("lite_cache_title", "Çeviri Belleği (TM Cache) Kullan"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("lite_cache_desc", "Daha önce çevrilen satırları hatırlar, aynı cümle tekrar geldiğinde anında bellekten getirir."); color: Theme.txt2; font.pixelSize: 11; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                }

                                Switch {
                                    checked: appBackend.useCache
                                    onToggled: appBackend.useCache = checked
                                }
                            }
                        }
                    }

                    // 3. BAKIM VE TEHLİKELİ BÖLGE KARTI (DANGER ZONE & MAINTENANCE)
                    Rectangle {
                        id: cardDangerZone
                        visible: pageSettings.settingsSubTab === 0
                        Layout.fillWidth: true
                        Layout.preferredHeight: dangerCol.implicitHeight + 40
                        radius: 16
                        color: Theme.alpha(Theme.error, 0.04)
                        border.color: Theme.alpha(Theme.error, 0.3)
                        border.width: 1

                        ColumnLayout {
                            id: dangerCol
                            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                            anchors.margins: 22; spacing: 16

                            IconLabel { alignment: Qt.AlignLeft; glyph: Icons.shieldAlert; text: appBackend.uiTrigger, appBackend.getTextWithDefault("danger_zone_title", "Bakım ve Veri Sıfırlama (Maintenance & Reset)"); font.pixelSize: 16; font.bold: true; color: Theme.error }

                            // Satır 1: Çeviri Belleğini Temizle
                            RowLayout {
                                Layout.fillWidth: true; spacing: 16
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 2
                                    IconLabel { alignment: Qt.AlignLeft; glyph: Icons.eraser; text: appBackend.uiTrigger, appBackend.getTextWithDefault("clear_tm_title", "Çeviri Belleğini (TM) Temizle"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("clear_tm_desc", "Daha önce önbelleğe alınan tüm çeviri eşleşmelerini temizler."); color: Theme.txt2; font.pixelSize: 11 }
                                }
                                Button {
                                    Layout.preferredWidth: 180; height: 38
                                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("lite_clear_cache_btn", "Önbelleği Temizle")
                                    onClicked: if (appBackend.clearTranslationCache()) showToast(appBackend.getTextWithDefault("cache_cleared_toast", "Translation cache cleared."), "success")
                                    background: Rectangle { radius: 8; color: parent.hovered ? Theme.dangerHover : Theme.danger; border.color: Theme.dangerBorder; border.width: 1 }
                                    contentItem: IconLabel { glyph: Icons.eraser; text: parent.text; color: Theme.white; font.bold: true; font.pixelSize: 11 }
                                }
                            }

                            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.alpha(Theme.error, 0.2) }

                            // Satır 2: Fabrika Ayarlarına Sıfırla
                            RowLayout {
                                Layout.fillWidth: true; spacing: 16
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 2
                                    IconLabel { alignment: Qt.AlignLeft; glyph: Icons.rotateCcw; text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_title", "Fabrika Ayarlarına Sıfırla"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_desc", "Tüm ayarları, API anahtarlarını ve sözlüğü siler; programı varsayılan haline döndürür."); color: Theme.txt2; font.pixelSize: 11 }
                                }
                                Button {
                                    Layout.preferredWidth: 180; height: 38
                                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_btn", "Sıfırla")
                                    onClicked: factoryResetDialog.open()
                                    background: Rectangle { radius: 8; color: parent.hovered ? Theme.dangerHover : Theme.danger; border.color: Theme.dangerBorder; border.width: 1 }
                                    contentItem: IconLabel { glyph: Icons.rotateCcw; text: parent.text; color: Theme.white; font.bold: true; font.pixelSize: 11 }
                                }
                            }
                        }
                    }

                    // PERFORMANS VE PARAMETRELER KARTI
                    Rectangle {
                        id: cardPerfSettings
                        visible: pageSettings.settingsSubTab === 2
                        Layout.fillWidth: true
                        Layout.preferredHeight: perfCol.implicitHeight + 44
                        radius: 16; color: Theme.card; border.color: Theme.cardBorder; border.width: 1
                        Behavior on Layout.preferredHeight { NumberAnimation { duration: 200 } }

                        ColumnLayout {
                            id: perfCol
                            anchors.fill: parent; anchors.margins: 22; spacing: 16
                            IconLabel { alignment: Qt.AlignLeft; glyph: Icons.gauge; text: appBackend.uiTrigger, appBackend.getTextWithDefault("settings_section_perf", "Performans & Bağlantı Parametreleri"); font.pixelSize: 16; font.bold: true; color: Theme.txt; iconColor: Theme.accent }

                            RowLayout {
                                Layout.fillWidth: true; spacing: 20
                                ColumnLayout {
                                    Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 6
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("concurrency_label", "Concurrent Threads") + ": " + Math.round(threadsSlider.value); color: Theme.txt; font.bold: true; font.pixelSize: 13; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                                    Slider { id: threadsSlider; Layout.fillWidth: true; from: 1; to: 32; stepSize: 1; value: appBackend.maxConcurrentThreads; onMoved: appBackend.maxConcurrentThreads = value }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 6
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("delay_label", "Request Delay") + ": " + delaySlider.value.toFixed(2) + "s"; color: Theme.txt; font.bold: true; font.pixelSize: 13; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                                    Slider { id: delaySlider; Layout.fillWidth: true; from: 0.0; to: 3.0; stepSize: 0.05; value: appBackend.requestDelay; onMoved: appBackend.requestDelay = value }
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 6
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("batch_label", "Batch Size") + ": " + Math.round(batchSlider.value); color: Theme.txt; font.bold: true; font.pixelSize: 13; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                                Slider { id: batchSlider; Layout.fillWidth: true; from: 10; to: 500; stepSize: 10; value: appBackend.maxBatchSize; onMoved: appBackend.maxBatchSize = value }
                            }

                            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.cardBorder }

                            // 2-Sütunlu Dengeli Switch Izgarası
                            GridLayout {
                                Layout.fillWidth: true
                                columns: 2
                                columnSpacing: 24
                                rowSpacing: 16

                                // Switch 1: Multi-Endpoint
                                RowLayout {
                                    Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 10
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("multi_endpoint_title", "Multi-Endpoint (Mirror)"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("multi_endpoint_desc", "Distributes requests across Google servers."); color: Theme.txt2; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                                    }
                                    Switch { checked: appBackend.useMultiEndpoint; onToggled: appBackend.useMultiEndpoint = checked }
                                }

                                // Switch 2: Parallel Batch
                                RowLayout {
                                    Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 10
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("parallel_batch_label", "Parallel Batch Requests"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("parallel_batch_desc", "Send multiple requests simultaneously. Disable if rate limited."); color: Theme.txt2; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                                    }
                                    Switch {
                                        id: parallelBatchSwitch
                                        checked: appBackend.enableParallelBatch
                                        onToggled: appBackend.enableParallelBatch = checked
                                    }
                                }

                                // Switch 3: RPYC AST Reader
                                RowLayout {
                                    Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 10
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("rpyc_reader_title", "RPYC AST Reader"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("rpyc_reader_desc", "Reads compiled .rpyc files directly."); color: Theme.txt2; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                                    }
                                    Switch { checked: appBackend.enableRpycReader; onToggled: appBackend.enableRpycReader = checked }
                                }

                                // Switch 4: Stateful Lexer
                                RowLayout {
                                    Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 10
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("stateful_lexer_title", "Stateful Lexer Engine (Experimental)"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("stateful_lexer_desc", "State-machine parser for script parsing. Enable to test stateful lexer pass."); color: Theme.txt2; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                                    }
                                    Switch { checked: appBackend.enableStatefulLexer; onToggled: appBackend.enableStatefulLexer = checked }
                                }
                            }
                        }
                    }

                    // AI MOTOR KARTI (SEÇİLİ MOTORA DUYARLI TAM KAPSAMLI YAPILANDIRMA)
                    Rectangle {
                        id: cardAiConfig
                        visible: pageSettings.settingsSubTab === 1
                        Layout.fillWidth: true
                        Layout.preferredHeight: aiCol.implicitHeight + 44
                        radius: 16; color: Theme.card; border.color: Theme.cardBorder; border.width: 1
                        Behavior on Layout.preferredHeight { NumberAnimation { duration: 200 } }

                        ColumnLayout {
                            id: aiCol
                            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                            anchors.margins: 22; spacing: 16

                            IconLabel { alignment: Qt.AlignLeft; glyph: Icons.bot; text: appBackend.uiTrigger, appBackend.getTextWithDefault("settings_section_ai", "AI Engine Configuration"); font.pixelSize: 16; font.bold: true; color: Theme.txt; iconColor: Theme.accent }

                            // OpenAI / DeepSeek Ayarları
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 14
                                visible: appBackend.selectedEngine === "openai" || appBackend.selectedEngine === "deepseek"

                                RowLayout {
                                    Layout.fillWidth: true; spacing: 18
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 5
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_openai_key", "OpenAI / DeepSeek API Key:"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                        TextField {
                                            Layout.fillWidth: true; height: 40; text: appBackend.openaiApiKey; echoMode: TextInput.Password; placeholderText: (text.length === 0 && !activeFocus) ? ("sk-...") : ""
                                            onEditingFinished: appBackend.openaiApiKey = text
                                            background: Rectangle {
                                                radius: 8; color: Theme.input
                                                border.color: parent.activeFocus ? Theme.accent : Theme.cardBorder; border.width: 1
                                                Behavior on border.color { ColorAnimation { duration: 150 } }
                                                Rectangle {
                                                    anchors.fill: parent; anchors.margins: -3; radius: parent.radius + 2; color: "transparent"
                                                    border.color: Theme.accent; border.width: 2; opacity: parent.parent.activeFocus ? 0.35 : 0.0
                                                    scale: parent.parent.activeFocus ? 1.0 : 0.98
                                                    Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutQuad } }
                                                    Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                                                }
                                            }
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 5
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_openai_model", "Model Name:"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                        TextField {
                                            Layout.fillWidth: true; height: 40; text: appBackend.openaiModel; placeholderText: (text.length === 0 && !activeFocus) ? (appBackend.selectedEngine === "deepseek" ? "deepseek-v4-flash" : "gpt-4o-mini") : ""
                                            onEditingFinished: appBackend.openaiModel = text
                                            background: Rectangle {
                                                radius: 8; color: Theme.input
                                                border.color: parent.activeFocus ? Theme.accent : Theme.cardBorder; border.width: 1
                                                Behavior on border.color { ColorAnimation { duration: 150 } }
                                                Rectangle {
                                                    anchors.fill: parent; anchors.margins: -3; radius: parent.radius + 2; color: "transparent"
                                                    border.color: Theme.accent; border.width: 2; opacity: parent.parent.activeFocus ? 0.35 : 0.0
                                                    scale: parent.parent.activeFocus ? 1.0 : 0.98
                                                    Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutQuad } }
                                                    Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                                                }
                                            }
                                        }
                                    }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 5
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("openai_base_url_label", "Base URL (Optional, empty for default):"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                    TextField {
                                        Layout.fillWidth: true; height: 40; text: appBackend.openaiBaseUrl; placeholderText: (text.length === 0 && !activeFocus) ? (appBackend.selectedEngine === "deepseek" ? "https://api.deepseek.com/v1" : "https://api.openai.com/v1") : ""
                                        onEditingFinished: appBackend.openaiBaseUrl = text
                                        background: Rectangle {
                                            radius: 8; color: Theme.input
                                            border.color: parent.activeFocus ? Theme.accent : Theme.cardBorder; border.width: 1
                                            Behavior on border.color { ColorAnimation { duration: 150 } }
                                            Rectangle {
                                                anchors.fill: parent; anchors.margins: -3; radius: parent.radius + 2; color: "transparent"
                                                border.color: Theme.accent; border.width: 2; opacity: parent.parent.activeFocus ? 0.35 : 0.0
                                                scale: parent.parent.activeFocus ? 1.0 : 0.98
                                                Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutQuad } }
                                                Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                                            }
                                        }
                                    }
                                }
                            }

                            // Gemini Ayarları
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 14
                                visible: appBackend.selectedEngine === "gemini"

                                RowLayout {
                                    Layout.fillWidth: true; spacing: 18
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 5
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_gemini_key", "Gemini API Key:"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                        TextField {
                                            Layout.fillWidth: true; height: 40; text: appBackend.geminiApiKey; echoMode: TextInput.Password; placeholderText: (text.length === 0 && !activeFocus) ? ("AIza...") : ""
                                            onEditingFinished: appBackend.geminiApiKey = text
                                            background: Rectangle {
                                                radius: 8; color: Theme.input
                                                border.color: parent.activeFocus ? Theme.accent : Theme.cardBorder; border.width: 1
                                                Behavior on border.color { ColorAnimation { duration: 150 } }
                                                Rectangle {
                                                    anchors.fill: parent; anchors.margins: -3; radius: parent.radius + 2; color: "transparent"
                                                    border.color: Theme.accent; border.width: 2; opacity: parent.parent.activeFocus ? 0.35 : 0.0
                                                    scale: parent.parent.activeFocus ? 1.0 : 0.98
                                                    Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutQuad } }
                                                    Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                                                }
                                            }
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 5
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_gemini_model", "Model:"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                        TextField {
                                            Layout.fillWidth: true; height: 40; text: appBackend.geminiModel; placeholderText: (text.length === 0 && !activeFocus) ? ("gemini-2.0-flash") : ""
                                            onEditingFinished: appBackend.geminiModel = text
                                            background: Rectangle {
                                                radius: 8; color: Theme.input
                                                border.color: parent.activeFocus ? Theme.accent : Theme.cardBorder; border.width: 1
                                                Behavior on border.color { ColorAnimation { duration: 150 } }
                                                Rectangle {
                                                    anchors.fill: parent; anchors.margins: -3; radius: parent.radius + 2; color: "transparent"
                                                    border.color: Theme.accent; border.width: 2; opacity: parent.parent.activeFocus ? 0.35 : 0.0
                                                    scale: parent.parent.activeFocus ? 1.0 : 0.98
                                                    Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutQuad } }
                                                    Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                                                }
                                            }
                                        }
                                    }
                                }

                                RowLayout {
                                    Layout.fillWidth: true; spacing: 18
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 5
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_gemini_safety", "Safety Filter Level:"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                        ComboBox {
                                            id: settingsGeminiSafetyCombo
                                            Layout.fillWidth: true; height: 40
                                            function safetyModel() {
                                                appBackend.uiTrigger
                                                return [
                                                    { "id": "BLOCK_NONE", "name": appBackend.getTextWithDefault("gemini_safety_block_none", "BLOCK_NONE (Unrestricted / NSFW-Friendly - Recommended)") },
                                                    { "id": "BLOCK_ONLY_HIGH", "name": appBackend.getTextWithDefault("gemini_safety_only_high", "BLOCK_ONLY_HIGH (Filter High Risk Only)") },
                                                    { "id": "STANDARD", "name": appBackend.getTextWithDefault("gemini_safety_standard", "STANDARD (Google Default - Strict)") }
                                                ]
                                            }
                                            model: safetyModel()
                                            textRole: "name"; valueRole: "id"
                                            function syncSafety() {
                                                var val = appBackend.geminiSafetySettings || "BLOCK_NONE"
                                                var idx = settingsGeminiSafetyCombo.indexOfValue(val)
                                                if (idx >= 0) settingsGeminiSafetyCombo.currentIndex = idx
                                            }
                                            Component.onCompleted: syncSafety()
                                            Connections {
                                                target: appBackend
                                                function onGeminiSafetySettingsChanged() { settingsGeminiSafetyCombo.syncSafety() }
                                                function onUiTriggerChanged() { settingsGeminiSafetyCombo.syncSafety() }
                                            }
                                            onActivated: appBackend.geminiSafetySettings = currentValue
                                            background: Rectangle {
                                                radius: 8; color: Theme.input; border.color: parent.hovered ? Theme.accent : Theme.cardBorder; border.width: 1
                                                Behavior on border.color { ColorAnimation { duration: 150 } }
                                            }
                                            contentItem: Label { leftPadding: 14; text: settingsGeminiSafetyCombo.displayText; color: Theme.txt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
                                            delegate: ItemDelegate {
                                                width: settingsGeminiSafetyCombo.width
                                                contentItem: Label { text: modelData.name; color: Theme.txt; font.pixelSize: 12; leftPadding: 14 }
                                                background: Rectangle { color: hovered ? Theme.alpha(Theme.accent, 0.12) : "transparent"; Behavior on color { ColorAnimation { duration: 120 } } }
                                            }
                                            popup: Popup { y: settingsGeminiSafetyCombo.height; width: settingsGeminiSafetyCombo.width; implicitHeight: Math.min(contentItem.implicitHeight, 220); padding: 4; contentItem: ListView { clip: true; implicitHeight: contentHeight; model: settingsGeminiSafetyCombo.delegateModel; ScrollBar.vertical: ScrollBar {} } background: Rectangle { color: Theme.card; radius: 8; border.color: Theme.cardBorder; border.width: 1 } }
                                        }
                                    }
                                }
                            }

                            // Local LLM (Ollama / LM Studio) Ayarları
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 14
                                visible: appBackend.selectedEngine === "local_llm" || appBackend.selectedEngine === "google"

                                // ── Çalışma Modu: Harici sunucu vs Yerleşik GGUF ──
                                RowLayout {
                                    Layout.fillWidth: true; spacing: 12

                                    Label {
                                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("local_llm_mode_label", "Çalışma Modu:")
                                        color: Theme.txt; font.bold: true; font.pixelSize: 13
                                    }

                                    ComboBox {
                                        id: localLlmModeCombo
                                        Layout.fillWidth: true; height: 40
                                        function modeModel() {
                                            appBackend.uiTrigger
                                            return [
                                                {"id": "external", "name": appBackend.getTextWithDefault("local_llm_mode_external", "Harici sunucu (Ollama / LM Studio)")},
                                                {"id": "builtin", "name": appBackend.getTextWithDefault("local_llm_mode_builtin", "Yerleşik GGUF çalıştırıcı (kurulum gerekmez)")}
                                            ]
                                        }
                                        model: modeModel()
                                        textRole: "name"; valueRole: "id"
                                        function syncMode() {
                                            var idx = localLlmModeCombo.indexOfValue(appBackend.localLlmMode || "external")
                                            if (idx >= 0) localLlmModeCombo.currentIndex = idx
                                        }
                                        Component.onCompleted: syncMode()
                                        Connections {
                                            target: appBackend
                                            function onLocalLlmModeChanged() { localLlmModeCombo.syncMode() }
                                            function onUiTriggerChanged() { localLlmModeCombo.syncMode() }
                                        }
                                        onActivated: appBackend.localLlmMode = currentValue
                                        background: Rectangle { radius: 8; color: Theme.input; border.color: parent.hovered ? Theme.accent : Theme.cardBorder; border.width: 1 }
                                        contentItem: Label { leftPadding: 14; text: localLlmModeCombo.displayText; color: Theme.txt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
                                        delegate: ItemDelegate {
                                            width: localLlmModeCombo.width
                                            contentItem: Label { text: modelData.name; color: Theme.txt; font.pixelSize: 12; leftPadding: 14; elide: Text.ElideRight }
                                            background: Rectangle { color: hovered ? Theme.alpha(Theme.accent, 0.12) : "transparent" }
                                        }
                                        popup: Popup {
                                            y: localLlmModeCombo.height; width: localLlmModeCombo.width
                                            implicitHeight: Math.min(contentItem.implicitHeight, 160); padding: 4
                                            contentItem: ListView { clip: true; implicitHeight: contentHeight; model: localLlmModeCombo.delegateModel; ScrollBar.vertical: ScrollBar {} }
                                            background: Rectangle { color: Theme.card; radius: 8; border.color: Theme.cardBorder; border.width: 1 }
                                        }
                                    }
                                }

                                // ── Yerleşik GGUF çalıştırıcı paneli ──
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 12
                                    visible: appBackend.localLlmMode === "builtin"

                                    // GGUF model dosyası
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 5
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("local_llm_gguf_label", "GGUF Model Dosyası:"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                        RowLayout {
                                            Layout.fillWidth: true; spacing: 10
                                            TextField {
                                                Layout.fillWidth: true; height: 40
                                                text: appBackend.localLlmGgufPath
                                                placeholderText: (text.length === 0 && !activeFocus) ? ("C:\\models\\Hy-MT2-7B-Q4_K_M.gguf") : ""
                                                onEditingFinished: appBackend.localLlmGgufPath = text
                                                background: Rectangle { radius: 8; color: Theme.input; border.color: Theme.cardBorder; border.width: 1 }
                                            }
                                            Button {
                                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("browse_btn", "Gözat")
                                                onClicked: ggufDialog.open()
                                                background: Rectangle { radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input; border.color: Theme.cardBorder; border.width: 1 }
                                                contentItem: Label { text: parent.text; color: Theme.txt; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                            }
                                        }
                                    }

                                    // Arka uç + GPU katmanları + context
                                    RowLayout {
                                        Layout.fillWidth: true; spacing: 18

                                        ColumnLayout {
                                            Layout.fillWidth: true; Layout.preferredWidth: 3; spacing: 5
                                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("local_llm_backend_label", "GPU Arka Ucu:"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                            ComboBox {
                                                id: localLlmBackendCombo
                                                Layout.fillWidth: true; height: 40
                                                function backendModel() {
                                                    appBackend.uiTrigger
                                                    return [
                                                        {"id": "vulkan", "name": appBackend.getTextWithDefault("local_llm_backend_vulkan", "Vulkan — NVIDIA/AMD/Intel (~30 MB, önerilen)")},
                                                        {"id": "cuda", "name": appBackend.getTextWithDefault("local_llm_backend_cuda", "CUDA — yalnızca NVIDIA (~240 MB)")},
                                                        {"id": "cpu", "name": appBackend.getTextWithDefault("local_llm_backend_cpu", "CPU — GPU yok (~17 MB)")}
                                                    ]
                                                }
                                                model: backendModel()
                                                textRole: "name"; valueRole: "id"
                                                function syncBackend() {
                                                    var idx = localLlmBackendCombo.indexOfValue(appBackend.localLlmBackend || "vulkan")
                                                    if (idx >= 0) localLlmBackendCombo.currentIndex = idx
                                                }
                                                Component.onCompleted: syncBackend()
                                                Connections {
                                                    target: appBackend
                                                    function onLocalLlmBackendChanged() { localLlmBackendCombo.syncBackend() }
                                                    function onUiTriggerChanged() { localLlmBackendCombo.syncBackend() }
                                                }
                                                onActivated: appBackend.localLlmBackend = currentValue
                                                background: Rectangle { radius: 8; color: Theme.input; border.color: parent.hovered ? Theme.accent : Theme.cardBorder; border.width: 1 }
                                                contentItem: Label { leftPadding: 14; text: localLlmBackendCombo.displayText; color: Theme.txt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                                                delegate: ItemDelegate {
                                                    width: localLlmBackendCombo.width
                                                    contentItem: Label { text: modelData.name; color: Theme.txt; font.pixelSize: 12; leftPadding: 14; elide: Text.ElideRight }
                                                    background: Rectangle { color: hovered ? Theme.alpha(Theme.accent, 0.12) : "transparent" }
                                                }
                                                popup: Popup {
                                                    y: localLlmBackendCombo.height; width: localLlmBackendCombo.width
                                                    implicitHeight: Math.min(contentItem.implicitHeight, 180); padding: 4
                                                    contentItem: ListView { clip: true; implicitHeight: contentHeight; model: localLlmBackendCombo.delegateModel; ScrollBar.vertical: ScrollBar {} }
                                                    background: Rectangle { color: Theme.card; radius: 8; border.color: Theme.cardBorder; border.width: 1 }
                                                }
                                            }
                                        }

                                        ColumnLayout {
                                            Layout.fillWidth: true; Layout.preferredWidth: 2; spacing: 5
                                            Label {
                                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("local_llm_gpu_layers_label", "GPU Katmanı") + ": "
                                                      + (ggufLayersSlider.value < 0 ? appBackend.getTextWithDefault("local_llm_gpu_layers_auto", "Tümü") : Math.round(ggufLayersSlider.value))
                                                color: Theme.txt; font.bold: true; font.pixelSize: 13
                                            }
                                            Slider {
                                                id: ggufLayersSlider
                                                Layout.fillWidth: true
                                                from: -1; to: 99; stepSize: 1
                                                value: appBackend.localLlmGpuLayers
                                                onMoved: appBackend.localLlmGpuLayers = Math.round(value)
                                            }
                                        }

                                        ColumnLayout {
                                            Layout.fillWidth: true; Layout.preferredWidth: 2; spacing: 5
                                            Label {
                                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("local_llm_ctx_label", "Bağlam (token)") + ": " + Math.round(ggufCtxSlider.value)
                                                color: Theme.txt; font.bold: true; font.pixelSize: 13
                                            }
                                            Slider {
                                                id: ggufCtxSlider
                                                Layout.fillWidth: true
                                                from: 512; to: 32768; stepSize: 512
                                                value: appBackend.localLlmCtxSize
                                                onMoved: appBackend.localLlmCtxSize = Math.round(value)
                                            }
                                        }
                                    }

                                    // Kendi llama-server binary'si (opsiyonel)
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 5
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("local_llm_server_path_label", "Kendi llama-server dosyanız (opsiyonel):"); color: Theme.txt2; font.pixelSize: 12 }
                                        RowLayout {
                                            Layout.fillWidth: true; spacing: 10
                                            TextField {
                                                Layout.fillWidth: true; height: 36
                                                text: appBackend.localLlmServerPath
                                                placeholderText: (text.length === 0 && !activeFocus) ? (appBackend.getTextWithDefault("local_llm_server_path_hint", "Boş bırakılırsa indirilen çalışma zamanı kullanılır")) : ""
                                                onEditingFinished: appBackend.localLlmServerPath = text
                                                background: Rectangle { radius: 8; color: Theme.input; border.color: Theme.cardBorder; border.width: 1 }
                                            }
                                            Button {
                                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("browse_btn", "Gözat")
                                                onClicked: llamaServerDialog.open()
                                                background: Rectangle { radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input; border.color: Theme.cardBorder; border.width: 1 }
                                                contentItem: Label { text: parent.text; color: Theme.txt; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                            }
                                        }
                                    }

                                    // Durum + eylem düğmeleri
                                    RowLayout {
                                        Layout.fillWidth: true; spacing: 10

                                        Rectangle {
                                            width: 10; height: 10; radius: 5
                                            color: appBackend.localServerStatus === "ready" ? Theme.success
                                                 : appBackend.localServerStatus === "error" ? Theme.error
                                                 : appBackend.localServerStatus === "stopped" ? Theme.txtDim : Theme.warn
                                        }

                                        Label {
                                            Layout.fillWidth: true
                                            wrapMode: Text.WordWrap
                                            font.pixelSize: 12
                                            color: appBackend.localServerStatus === "error" ? Theme.error : Theme.txt2
                                            text: {
                                                appBackend.uiTrigger
                                                var st = appBackend.localServerStatus
                                                var label = st === "ready" ? appBackend.getTextWithDefault("local_server_ready", "Sunucu çalışıyor")
                                                          : st === "starting" ? appBackend.getTextWithDefault("local_server_starting", "Model yükleniyor...")
                                                          : st === "downloading" ? appBackend.getTextWithDefault("local_server_downloading", "Çalışma zamanı indiriliyor...")
                                                          : st === "error" ? appBackend.getTextWithDefault("local_server_error", "Hata")
                                                          : appBackend.getTextWithDefault("local_server_stopped", "Durduruldu")
                                                var detail = appBackend.localServerDetail
                                                return detail ? label + " — " + detail : label
                                            }
                                        }

                                        Button {
                                            visible: !appBackend.localRuntimeReady
                                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("local_server_download_btn", "Çalışma Zamanını İndir")
                                            enabled: appBackend.localServerStatus !== "downloading"
                                            onClicked: appBackend.downloadLocalRuntime()
                                            background: Rectangle { radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input; border.color: Theme.accent; border.width: 1 }
                                            contentItem: Label { text: parent.text; color: Theme.accent; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                        }

                                        Button {
                                            text: appBackend.uiTrigger, appBackend.localServerStatus === "ready"
                                                  ? appBackend.getTextWithDefault("local_server_stop_btn", "Durdur")
                                                  : appBackend.getTextWithDefault("local_server_start_btn", "Başlat")
                                            enabled: appBackend.localServerStatus !== "starting" && appBackend.localServerStatus !== "downloading"
                                            onClicked: appBackend.localServerStatus === "ready" ? appBackend.stopLocalServer() : appBackend.startLocalServer()
                                            background: Rectangle { radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input; border.color: Theme.cardBorder; border.width: 1 }
                                            contentItem: Label { text: parent.text; color: Theme.txt; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                        }
                                    }

                                    Label {
                                        Layout.fillWidth: true
                                        wrapMode: Text.WordWrap
                                        font.pixelSize: 11
                                        color: Theme.txtDim
                                        text: appBackend.uiTrigger, appBackend.getTextWithDefault(
                                            "local_llm_builtin_note",
                                            "Çalışma zamanı yalnızca siz istediğinizde resmi llama.cpp sürümünden indirilir, SHA256 ile doğrulanır ve uygulama verisi klasörüne açılır. Model dosyası indirilmez — kendi .gguf dosyanızı seçersiniz."
                                        )
                                    }

                                    // Açık kaynak kredisi (llama.cpp MIT lisanslıdır).
                                    Label {
                                        Layout.fillWidth: true
                                        wrapMode: Text.WordWrap
                                        font.pixelSize: 11
                                        color: Theme.txtDim
                                        textFormat: Text.RichText
                                        onLinkActivated: (link) => Qt.openUrlExternally(link)
                                        text: appBackend.uiTrigger, appBackend.getTextWithDefault(
                                            "local_llm_credit",
                                            "Powered by <a href=\"https://github.com/ggml-org/llama.cpp\">llama.cpp</a> (MIT)."
                                        )
                                    }
                                }

                                RowLayout {
                                    Layout.fillWidth: true; spacing: 18
                                    visible: appBackend.localLlmMode !== "builtin"
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 5
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_ollama_url", "Local LLM Server URL (Ollama/LM Studio):"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                        TextField {
                                            Layout.fillWidth: true; height: 40; text: appBackend.localLlmUrl; placeholderText: (text.length === 0 && !activeFocus) ? ("http://localhost:11434/v1") : ""
                                            onEditingFinished: appBackend.localLlmUrl = text
                                            background: Rectangle { radius: 8; color: Theme.input; border.color: Theme.cardBorder; border.width: 1 }
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 5
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_ollama_model", "Local LLM Model Name:"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                        TextField {
                                            Layout.fillWidth: true; height: 40; text: appBackend.localLlmModel; placeholderText: (text.length === 0 && !activeFocus) ? ("qwen2.5-coder:7b-instruct, llama3...") : ""
                                            onEditingFinished: appBackend.localLlmModel = text
                                            background: Rectangle { radius: 8; color: Theme.input; border.color: Theme.cardBorder; border.width: 1 }
                                        }
                                    }
                                }

                                // Local LLM Model Size & Quality Recommendation Hint
                                Rectangle {
                                    Layout.fillWidth: true
                                    radius: 8
                                    color: Theme.alpha(Theme.primary, 0.08)
                                    border.color: Theme.alpha(Theme.primary, 0.25)
                                    border.width: 1
                                    implicitHeight: localLlmHintRow.implicitHeight + 16

                                    RowLayout {
                                        id: localLlmHintRow
                                        anchors.fill: parent
                                        anchors.margins: 10
                                        spacing: 10

                                        Icon {
                                            glyph: Icons.lightbulb
                                            size: 14
                                            color: Theme.txt2
                                            Layout.alignment: Qt.AlignVCenter
                                        }

                                        Label {
                                            Layout.fillWidth: true
                                            text: appBackend.uiTrigger, appBackend.getTextWithDefault(
                                                "tip_local_llm_model_recommendation",
                                                "Recommendation: Small local models (<3B parameters) often fail on game UI terms, formatting, and syntax. For reliable results, use at least 7B/8B models (e.g. Qwen 2.5 7B, Llama 3 8B) or Google / DeepSeek."
                                            )
                                            color: Theme.txtDim
                                            font.pixelSize: 11
                                            wrapMode: Text.WordWrap
                                        }
                                    }
                                }
                            }

                            // AI Çeviri Modu (Translation Mode: Scene / JSON / XML) & Sahne Blok Boyutu
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 14
                                visible: appBackend.selectedEngine === "local_llm" || appBackend.selectedEngine === "openai" || appBackend.selectedEngine === "deepseek" || appBackend.selectedEngine === "gemini" || appBackend.selectedEngine === "custom" || appBackend.selectedEngine === "google"

                                RowLayout {
                                    Layout.fillWidth: true; spacing: 18

                                    // Çeviri Modu Seçimi
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Layout.preferredWidth: appBackend.aiBatchFormat === "scene" ? 3 : 1
                                        spacing: 5

                                        Label {
                                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_mode_label", "Translation Mode:");
                                            color: Theme.txt; font.bold: true; font.pixelSize: 13
                                        }

                                        ComboBox {
                                            id: aiBatchModeCombo
                                            Layout.fillWidth: true; height: 40
                                            function modeModel() {
                                                appBackend.uiTrigger
                                                return [
                                                    {"id": "scene", "name": appBackend.getTextWithDefault("ai_mode_scene", "Scene / Screenplay Mode (Context-Aware)")},
                                                    {"id": "json", "name": appBackend.getTextWithDefault("ai_mode_json", "Standard Structured Mode (JSON)")},
                                                    {"id": "xml", "name": appBackend.getTextWithDefault("ai_mode_xml", "Legacy Grouping Mode (XML)")},
                                                    {"id": "single", "name": appBackend.getTextWithDefault("ai_mode_single", "Single Line Mode (No Context)")}
                                                ]
                                            }
                                            model: modeModel()
                                            textRole: "name"; valueRole: "id"
                                            Component.onCompleted: currentIndex = indexOfValue(appBackend.aiBatchFormat || "scene")
                                            onActivated: appBackend.aiBatchFormat = currentValue
                                            background: Rectangle { radius: 8; color: Theme.input; border.color: parent.hovered ? Theme.accent : Theme.cardBorder; border.width: 1 }
                                            contentItem: Label { leftPadding: 14; rightPadding: 14; text: aiBatchModeCombo.displayText; color: Theme.txt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                                            delegate: ItemDelegate {
                                                width: aiBatchModeCombo.width
                                                contentItem: Label { text: modelData.name; color: Theme.txt; font.pixelSize: 12; leftPadding: 14; elide: Text.ElideRight }
                                                background: Rectangle { color: hovered ? Theme.alpha(Theme.accent, 0.12) : "transparent" }
                                            }
                                            popup: Popup {
                                                y: aiBatchModeCombo.height; width: aiBatchModeCombo.width
                                                implicitHeight: Math.min(contentItem.implicitHeight, 200)
                                                padding: 4
                                                contentItem: ListView { clip: true; implicitHeight: contentHeight; model: aiBatchModeCombo.delegateModel; ScrollBar.vertical: ScrollBar {} }
                                                background: Rectangle { color: Theme.card; radius: 8; border.color: Theme.cardBorder; border.width: 1 }
                                            }
                                        }
                                    }

                                    // Sahne Blok Boyutu (Scene Block Size) - Sadece Sahne Modunda Aktif
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Layout.preferredWidth: 2
                                        spacing: 6
                                        visible: appBackend.aiBatchFormat === "scene"

                                        Label {
                                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_scene_size_label", "Scene Block Size (Lines)") + ": " + Math.round(aiSceneSlider.value)
                                            color: Theme.txt; font.bold: true; font.pixelSize: 13
                                        }

                                        Slider {
                                            id: aiSceneSlider
                                            Layout.fillWidth: true
                                            from: 5; to: 50; stepSize: 5
                                            value: appBackend.aiSceneBatchSize
                                            onMoved: appBackend.aiSceneBatchSize = Math.round(value)
                                        }
                                    }
                                }

                                // Seçili Moda Göre Canlı Açıklama / Rehber
                                RowLayout {
                                    Layout.fillWidth: true; spacing: 8
                                    Icon { glyph: Icons.lightbulb; size: 14; color: Theme.txt2; Layout.alignment: Qt.AlignTop; Layout.topMargin: 1 }
                                Label {
                                    Layout.fillWidth: true
                                    wrapMode: Text.WordWrap
                                    font.pixelSize: 12
                                    color: Theme.txt2
                                    text: {
                                        appBackend.uiTrigger
                                        if (appBackend.aiBatchFormat === "scene") {
                                            return appBackend.getTextWithDefault("ai_mode_scene_desc", "Diyalogları senaryo akışı halinde iletir. Karakter hitaplarını, cinsiyet uyumunu ve bağlamı en iyi koruyan moddur (Görsel romanlar için önerilen).")
                                        } else if (appBackend.aiBatchFormat === "single") {
                                            return appBackend.getTextWithDefault("ai_mode_single_desc", "Her satırı ayrı istek olarak gönderir; komşu satır ve konuşmacı bağlamı iletilmez. Küçük yerel modeller ve saf çeviri modelleri (Hy-MT) için önerilir — toplu istek biçimini bozmadıkları için sonuç daha tutarlı olur. Daha fazla istek, daha yavaş ama daha az format hatası.")
                                        } else if (appBackend.aiBatchFormat === "json") {
                                            return appBackend.getTextWithDefault("ai_mode_json_desc", "Metinleri anahtar-değer çifti olarak iletir. Sıfır satır kayması ve katı veri bütünlüğü sağlar; menü ve sistem metinleri için idealdir.")
                                        } else {
                                            return appBackend.getTextWithDefault("ai_mode_xml_desc", "Metinleri XML etiketleriyle paketler. JSON üretmekte zorlanan küçük veya eski modeller için en güvenli seçenektir.")
                                        }
                                    }
                                }
                                }
                            }

                            // Hy-MT2 (Tencent) Özel Çeviri Profili
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 12
                                visible: appBackend.selectedEngine === "local_llm"

                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: hyMt2Inner.implicitHeight + 28
                                    radius: 12
                                    color: Theme.alpha(Theme.accent, 0.04)
                                    border.color: appBackend.hyMt2Active ? Theme.accent : Theme.cardBorder
                                    border.width: 1

                                    ColumnLayout {
                                        id: hyMt2Inner
                                        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                                        anchors.margins: 14; spacing: 12

                                        RowLayout {
                                            Layout.fillWidth: true; spacing: 10
                                            IconLabel { alignment: Qt.AlignLeft; glyph: Icons.target; text: appBackend.uiTrigger, appBackend.getTextWithDefault("hy_mt2_title", "Hy-MT2 (Tencent) — Specialized Translation Profile"); color: Theme.txt; iconColor: Theme.accent; font.bold: true; font.pixelSize: 14 }
                                            Item { Layout.fillWidth: true }
                                            Rectangle {
                                                radius: 10
                                                color: appBackend.hyMt2Active ? Theme.alpha(Theme.success, 0.18) : Theme.alpha(Theme.txtDim, 0.15)
                                                Layout.preferredHeight: 22; Layout.preferredWidth: hyMt2BadgeTxt.implicitWidth + 20
                                                Label { id: hyMt2BadgeTxt; anchors.centerIn: parent; text: appBackend.uiTrigger, appBackend.hyMt2Active ? appBackend.getTextWithDefault("hy_mt2_active_badge", "ACTIVE") : appBackend.getTextWithDefault("hy_mt2_inactive_badge", "OFF"); font.pixelSize: 11; font.bold: true; color: appBackend.hyMt2Active ? Theme.accent : Theme.txt2 }
                                            }
                                        }

                                        Label {
                                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("hy_mt2_info", "Optimized for Tencent Hy-MT translation models: uses official instruction templates (no system prompt), delimiter preservation and the model-card sampling recipe (temp 0.7, top_p 0.6, top_k 20, rep.pen 1.05) for maximum speed and quality.")
                                            color: Theme.txt2; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.WordWrap
                                        }

                                        ColumnLayout {
                                            Layout.fillWidth: true; spacing: 5
                                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("hy_mt2_profile_label", "Profile Mode:"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                            ComboBox {
                                                id: hyMt2ProfileCombo
                                                Layout.fillWidth: true; height: 40
                                                function profileModel() {
                                                    appBackend.uiTrigger
                                                    return [
                                                        {"id": "auto", "name": appBackend.getTextWithDefault("hy_mt2_profile_auto", "Auto-detect from model name (recommended)")},
                                                        {"id": "hy_mt2", "name": appBackend.getTextWithDefault("hy_mt2_profile_force", "Force Hy-MT2 profile")},
                                                        {"id": "generic", "name": appBackend.getTextWithDefault("hy_mt2_profile_off", "Off (generic behaviour)")}
                                                    ]
                                                }
                                                model: profileModel()
                                                textRole: "name"; valueRole: "id"
                                                Component.onCompleted: currentIndex = indexOfValue(appBackend.aiModelProfile || "auto")
                                                onActivated: appBackend.aiModelProfile = currentValue
                                                background: Rectangle { radius: 8; color: Theme.input; border.color: parent.hovered ? Theme.accent : Theme.cardBorder; border.width: 1 }
                                                contentItem: Label { leftPadding: 14; text: hyMt2ProfileCombo.displayText; color: Theme.txt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
                                                delegate: ItemDelegate {
                                                    width: hyMt2ProfileCombo.width
                                                    contentItem: Label { text: modelData.name; color: Theme.txt; font.pixelSize: 12; leftPadding: 14 }
                                                    background: Rectangle { color: hovered ? Theme.alpha(Theme.accent, 0.12) : "transparent" }
                                                }
                                                popup: Popup { y: hyMt2ProfileCombo.height; width: hyMt2ProfileCombo.width; implicitHeight: Math.min(contentItem.implicitHeight, 220); padding: 4; contentItem: ListView { clip: true; implicitHeight: contentHeight; model: hyMt2ProfileCombo.delegateModel; ScrollBar.vertical: ScrollBar {} } background: Rectangle { color: Theme.card; radius: 8; border.color: Theme.cardBorder; border.width: 1 } }
                                            }
                                        }

                                        Label {
                                            text: appBackend.uiTrigger, appBackend.hyMt2Active
                                                ? appBackend.getTextWithDefault("hy_mt2_detected", "✓ Hy-MT2 profile is active — official instructions and sampling will be used.")
                                                  + " " + appBackend.getTextWithDefault("hy_mt2_single_note", "Each line is sent as its own request; the batch format selector does not apply.")
                                                : appBackend.getTextWithDefault("hy_mt2_not_detected", "No Hy-MT model detected in the model name. Choose 'Force Hy-MT2 profile' to enable it anyway.")
                                            color: appBackend.hyMt2Active ? Theme.accent : Theme.txt2
                                            font.pixelSize: 12; font.bold: appBackend.hyMt2Active
                                            Layout.fillWidth: true; wrapMode: Text.WordWrap
                                        }
                                    }
                                }
                            }

                            // LibreTranslate Ayarları
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 14
                                visible: appBackend.selectedEngine === "libretranslate"

                                RowLayout {
                                    Layout.fillWidth: true; spacing: 18
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 5
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("libretranslate_url_label", "LibreTranslate Server URL:"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                        TextField {
                                            Layout.fillWidth: true; height: 40; text: appBackend.libretranslateUrl; placeholderText: (text.length === 0 && !activeFocus) ? ("http://localhost:5000") : ""
                                            onEditingFinished: appBackend.libretranslateUrl = text
                                            background: Rectangle { radius: 8; color: Theme.input; border.color: Theme.cardBorder; border.width: 1 }
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 5
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("libretranslate_api_key_label", "LibreTranslate API Key (Optional):"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                        TextField {
                                            Layout.fillWidth: true; height: 40; text: appBackend.libretranslateApiKey; echoMode: TextInput.Password
                                            onEditingFinished: appBackend.libretranslateApiKey = text
                                            background: Rectangle { radius: 8; color: Theme.input; border.color: Theme.cardBorder; border.width: 1 }
                                        }
                                    }
                                }
                            }

                            // Custom Endpoint Ayarları
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 14
                                visible: appBackend.selectedEngine === "custom"

                                RowLayout {
                                    Layout.fillWidth: true; spacing: 18
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 5
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("custom_url_label", "Custom API Endpoint URL:"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                        TextField {
                                            Layout.fillWidth: true; height: 40; text: appBackend.customEndpointUrl; placeholderText: (text.length === 0 && !activeFocus) ? ("http://localhost:8000/translate") : ""
                                            onEditingFinished: appBackend.customEndpointUrl = text
                                            background: Rectangle { radius: 8; color: Theme.input; border.color: Theme.cardBorder; border.width: 1 }
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 5
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("custom_api_key_label", "Custom API Key (Optional):"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                        TextField {
                                            Layout.fillWidth: true; height: 40; text: appBackend.customEndpointApiKey; echoMode: TextInput.Password
                                            onEditingFinished: appBackend.customEndpointApiKey = text
                                            background: Rectangle { radius: 8; color: Theme.input; border.color: Theme.cardBorder; border.width: 1 }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // GELİŞMİŞ YAPAY ZEKA PARAMETRELERİ (TUNING & SYSTEM PROMPT) KARTI
                    Rectangle {
                        id: cardAiTuning
                        visible: pageSettings.settingsSubTab === 1
                        Layout.fillWidth: true
                        Layout.preferredHeight: aiTuningCol.implicitHeight + 44
                        radius: 16; color: Theme.card; border.color: Theme.cardBorder; border.width: 1
                        Behavior on Layout.preferredHeight { NumberAnimation { duration: 200 } }

                        ColumnLayout {
                            id: aiTuningCol
                            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                            anchors.margins: 22; spacing: 18

                            IconLabel { alignment: Qt.AlignLeft; glyph: Icons.slidersHorizontal; text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_tuning_title", "Advanced AI Tuning & System Prompt"); font.pixelSize: 16; font.bold: true; color: Theme.txt; iconColor: Theme.accent }

                            // Satır 1: Temperature & Max Tokens
                            RowLayout {
                                Layout.fillWidth: true; spacing: 24
                                ColumnLayout {
                                    Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 6
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_temp_label", "AI Temperature") + ": " + aiTempSlider.value.toFixed(2); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                    Slider { id: aiTempSlider; Layout.fillWidth: true; from: 0.0; to: 1.0; stepSize: 0.05; value: appBackend.aiTemperature; onMoved: appBackend.aiTemperature = value }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 6
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_tokens_label", "Max Tokens") + ": " + Math.round(aiTokensSlider.value); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                    Slider { id: aiTokensSlider; Layout.fillWidth: true; from: 256; to: 8192; stepSize: 256; value: appBackend.aiMaxTokens; onMoved: appBackend.aiMaxTokens = value }
                                }
                            }

                            // Satır 2: AI Timeout & AI Batch Size
                            RowLayout {
                                Layout.fillWidth: true; spacing: 24
                                ColumnLayout {
                                    Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 6
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_timeout_label", "AI Timeout") + ": " + Math.round(aiTimeoutSlider.value) + "s"; color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                    Slider { id: aiTimeoutSlider; Layout.fillWidth: true; from: 10; to: 300; stepSize: 10; value: appBackend.aiTimeout; onMoved: appBackend.aiTimeout = value }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 6
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_batch_label", "AI Batch Size") + ": " + Math.round(aiBatchSlider.value); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                    Slider { id: aiBatchSlider; Layout.fillWidth: true; from: 1; to: 50; stepSize: 1; value: appBackend.aiBatchSize; onMoved: appBackend.aiBatchSize = value }
                                }
                            }

                            // Satır 3: AI Retry Count & AI Concurrency
                            RowLayout {
                                Layout.fillWidth: true; spacing: 24
                                ColumnLayout {
                                    Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 6
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_retry_label", "AI Retry Count") + ": " + Math.round(aiRetrySlider.value); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                    Slider { id: aiRetrySlider; Layout.fillWidth: true; from: 1; to: 5; stepSize: 1; value: appBackend.aiRetryCount; onMoved: appBackend.aiRetryCount = value }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 6
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_concurrency_label", "AI Concurrency") + ": " + Math.round(aiConcSlider.value); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                    Slider { id: aiConcSlider; Layout.fillWidth: true; from: 1; to: 10; stepSize: 1; value: appBackend.aiConcurrency; onMoved: appBackend.aiConcurrency = value }
                                }
                            }

                            // Satır 4: Custom System Prompt (Çok Satırlı TextArea)
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 6
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_prompt_label", "Custom System Prompt (Optional instructions for AI):"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                                ScrollView {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 96
                                    clip: true
                                    ScrollBar.vertical: ScrollBar {}
                                    TextArea {
                                        id: aiPromptField
                                        text: appBackend.aiCustomSystemPrompt
                                        placeholderText: (text.length === 0 && !activeFocus) ? ("Translate the following Ren'Py visual novel dialogue accurately while keeping tags...") : ""
                                        wrapMode: TextEdit.Wrap
                                        onEditingFinished: appBackend.aiCustomSystemPrompt = text
                                        font.pixelSize: 12; color: Theme.txt
                                        selectByMouse: true
                                        background: Rectangle {
                                            radius: 8
                                            color: Theme.input
                                            border.color: aiPromptField.activeFocus ? Theme.accent : Theme.cardBorder
                                            border.width: 1
                                            Behavior on border.color { ColorAnimation { duration: 150 } }

                                            // Focus Ring Glow
                                            Rectangle {
                                                anchors.fill: parent
                                                anchors.margins: -3
                                                radius: parent.radius + 2
                                                color: "transparent"
                                                border.color: Theme.accent
                                                border.width: 2
                                                opacity: aiPromptField.activeFocus ? 0.35 : 0.0
                                                scale: aiPromptField.activeFocus ? 1.0 : 0.98
                                                Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutQuad } }
                                                Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                                            }
                                        }
                                    }
                                }

                                // Hy-MT modellerinin sistem promptu yoktur: alan yok sayılır.
                                // Motor koşulu, işaret ettiği "Model Profili" seçicisiyle aynı olmalı
                                // (o seçici yalnızca Local LLM motorunda görünür); aksi halde kullanıcı
                                // bulunmayan bir ayara yönlendirilir.
                                RowLayout {
                                    Layout.fillWidth: true; spacing: 8
                                    visible: appBackend.hyMt2Active && appBackend.selectedEngine === "local_llm"
                                    Icon { glyph: Icons.triangleAlert; size: 14; color: Theme.warn; Layout.alignment: Qt.AlignTop; Layout.topMargin: 1 }
                                    Label {
                                        Layout.fillWidth: true
                                        wrapMode: Text.WordWrap
                                        font.pixelSize: 12
                                        color: Theme.warn
                                        text: appBackend.uiTrigger, appBackend.getTextWithDefault(
                                            "ai_prompt_ignored_hy_mt2",
                                            "Hy-MT models have no system prompt — this field is ignored while the Hy-MT profile is active. Set Model Profile to 'generic' to use it."
                                        )
                                    }
                                }
                            }
                        }
                    }

                    Item { height: 24 }
                }
            }
        }

            // ═════════════════════════════════════════════════════════════
            // SEKME 2: LOG CONSOLE & STUDIO TERMINAL
            // ═════════════════════════════════════════════════════════════
            Item {
                id: pageLogs
                visible: navIndex === 2
                Layout.fillWidth: true
                Layout.fillHeight: true

                property string selectedLevel: "ALL"
                property string logSearchQuery: ""

                transform: Translate { id: animTrLogs; y: 14 }
                opacity: 0.0
                ParallelAnimation {
                    id: animEntranceLogs
                    NumberAnimation { target: animTrLogs; property: "y"; from: 14; to: 0; duration: 220; easing.type: Easing.OutCubic }
                    NumberAnimation { target: pageLogs; property: "opacity"; from: 0.0; to: 1.0; duration: 180; easing.type: Easing.OutQuad }
                }
                onVisibleChanged: if (visible) animEntranceLogs.restart()

                // Sabit Sticky Terminal Araç Çubuğu
                PageHeader {
                    id: logStickyHeader
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    maxContentWidth: 100000 // çalışma sayfası: tam genişlik
                    glyph: Icons.terminal
                    title: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_logs", "Log Console & System Diagnostics")
                    subtitle: appBackend.uiTrigger, logModel.count + " " + appBackend.getTextWithDefault("logs_count_label", "events recorded in session.")
                    actions: [
                        Button {
                            height: 34; text: appBackend.uiTrigger, appBackend.getTextWithDefault("copy_log", "Copy Log")
                            onClicked: {
                                var lines = []
                                for (var i = 0; i < logModel.count; i++) {
                                    var item = logModel.get(i)
                                    lines.push(item.ts + " [" + item.level.toUpperCase() + "] " + item.message)
                                }
                                appBackend.copyToClipboard(lines.join("\n"))
                                showToast(appBackend.getTextWithDefault("log_copied_clipboard", "Log copied to clipboard!"), "info")
                            }
                            background: Rectangle { radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input; border.color: Theme.cardBorder; border.width: 1 }
                            contentItem: IconLabel { glyph: Icons.copy; text: parent.text; color: Theme.txt; font.pixelSize: 11; font.bold: true }
                        },
                        Button {
                            height: 34; text: appBackend.uiTrigger, appBackend.getTextWithDefault("clear_log", "Clear")
                            onClicked: logModel.clear()
                            background: Rectangle { radius: 8; color: parent.hovered ? Theme.dangerTint : Theme.input; border.color: Theme.cardBorder; border.width: 1 }
                            contentItem: IconLabel { glyph: Icons.trash2; text: parent.text; color: Theme.error; font.pixelSize: 11; font.bold: true }
                        }
                    ]

                    // Alt Satır: Seviye Filtreleri (Segments) + Canlı Arama
                    RowLayout {
                        Layout.fillWidth: true; spacing: 12

                        // Segmented Level Filter Bar
                        Rectangle {
                            height: 32; radius: 8
                            color: Theme.card; border.color: Theme.cardBorder; border.width: 1
                            Layout.preferredWidth: filterRow.implicitWidth + 8

                            RowLayout {
                                id: filterRow
                                anchors.centerIn: parent
                                spacing: 4

                                Repeater {
                                    model: [
                                        { label: "All", tag: "editor_status_all", key: "ALL", color: Theme.txt },
                                        { label: "INFO", tag: "log_tag_info", key: "INFO", color: Theme.accent },
                                        { label: "WARN", tag: "log_tag_warn", key: "WARNING", color: Theme.warn },
                                        { label: "ERROR", tag: "log_tag_error", key: "ERROR", color: Theme.error }
                                    ]
                                    delegate: Rectangle {
                                        width: Math.max(60, levelLabel.implicitWidth + 20); height: 26; radius: 6
                                        color: pageLogs.selectedLevel === modelData.key ? Theme.alpha(modelData.color, 0.18) : "transparent"
                                        border.color: pageLogs.selectedLevel === modelData.key ? modelData.color : "transparent"; border.width: 1
                                        Label {
                                            id: levelLabel
                                            anchors.centerIn: parent
                                            text: appBackend.uiTrigger, appBackend.getTextWithDefault(modelData.tag, modelData.label).replace("[", "").replace("]", "")
                                            font.pixelSize: 10; font.bold: pageLogs.selectedLevel === modelData.key
                                            color: pageLogs.selectedLevel === modelData.key ? modelData.color : Theme.txt2
                                        }
                                        MouseArea {
                                            anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                            onClicked: pageLogs.selectedLevel = modelData.key
                                        }
                                    }
                                }
                            }
                        }

                        // Canlı Arama Kutusu
                        Rectangle {
                            Layout.fillWidth: true; height: 32; radius: 8
                            color: Theme.input; border.color: Theme.cardBorder; border.width: 1
                            RowLayout {
                                anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 10; spacing: 6
                                Icon { glyph: Icons.search; size: 13; color: Theme.txtDim }
                                TextInput {
                                    id: logSearchInput
                                    Layout.fillWidth: true
                                    font.pixelSize: 11; color: Theme.txt
                                    clip: true
                                    Text {
                                        anchors.fill: parent
                                        verticalAlignment: Text.AlignVCenter
                                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("logs_search_placeholder", "Loglarda filtrele veya anahtar kelime ara...")
                                        color: Theme.txtDim; font.pixelSize: 11
                                        visible: !logSearchInput.text && !logSearchInput.activeFocus
                                    }
                                    onTextChanged: pageLogs.logSearchQuery = text.trim().toLowerCase()
                                }
                                Button {
                                    visible: logSearchInput.text.length > 0
                                    width: 18; height: 18; text: "✕"
                                    onClicked: { logSearchInput.text = ""; pageLogs.logSearchQuery = "" }
                                    background: Item {}
                                    contentItem: Label { text: "✕"; color: Theme.txtDim; font.pixelSize: 10; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                }
                            }
                        }
                    }
                }

                // Konsol Çıktı Terminali (Doğrudan ListView — Nested Scroll Yok!)
                Rectangle {
                    anchors.top: logStickyHeader.bottom
                    anchors.bottom: parent.bottom
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: logStickyHeader.contentWidth
                    anchors.topMargin: 16; anchors.bottomMargin: 24
                    radius: 12
                    color: Qt.darker(Theme.card, 1.25)
                    border.color: Theme.cardBorder
                    border.width: 1

                    ListView {
                        id: logConsoleListView
                        anchors.fill: parent
                        anchors.margins: 12
                        clip: true
                        model: logModel
                        spacing: 4
                        ScrollBar.vertical: ScrollBar {}

                        // Otomatik aşağı kaydırma
                        onCountChanged: {
                            if (logConsoleListView.atYEnd || logModel.count < 10) {
                                logConsoleListView.positionViewAtEnd()
                            }
                        }

                        delegate: Item {
                            id: logItemDelegate
                            property bool matchesLevel: pageLogs.selectedLevel === "ALL" || (model.level || "").toUpperCase() === pageLogs.selectedLevel
                            property bool matchesSearch: pageLogs.logSearchQuery.length === 0 || (model.message || "").toLowerCase().indexOf(pageLogs.logSearchQuery) !== -1
                            property bool isVisibleInFilter: matchesLevel && matchesSearch

                            visible: isVisibleInFilter
                            width: logConsoleListView.width
                            height: isVisibleInFilter ? logRowLayout.implicitHeight + 4 : 0

                            RowLayout {
                                id: logRowLayout
                                anchors.fill: parent
                                spacing: 10

                                Label {
                                    text: model.ts || ""
                                    color: Theme.txtDim; font.pixelSize: 11; font.family: "Consolas, 'Courier New', monospace"
                                    Layout.preferredWidth: 65
                                }
                                Label {
                                    text: logPrefix(model.level)
                                    color: logColor(model.level)
                                    font.bold: true; font.pixelSize: 11; font.family: "Consolas, 'Courier New', monospace"
                                    Layout.preferredWidth: 55
                                }
                                Label {
                                    text: model.message || ""
                                    color: logColor(model.level)
                                    font.pixelSize: 11; font.family: "Consolas, 'Courier New', monospace"
                                    Layout.fillWidth: true
                                    wrapMode: Text.Wrap
                                }
                            }
                        }
                    }
                }
            }

        // ═════════════════════════════════════════════════════════════
        // SEKME 3: TOOLBOX (GELİŞMİŞ REN'PY ARAÇ KUTUSU)
        // ═════════════════════════════════════════════════════════════
        Item {
            id: pageToolbox
            visible: navIndex === 3
            transform: Translate { id: animTrToolbox; y: 14 }
            opacity: 0.0
            ParallelAnimation {
                id: animEntranceToolbox
                NumberAnimation { target: animTrToolbox; property: "y"; from: 14; to: 0; duration: 220; easing.type: Easing.OutCubic }
                NumberAnimation { target: pageToolbox; property: "opacity"; from: 0.0; to: 1.0; duration: 180; easing.type: Easing.OutQuad }
            }
            onVisibleChanged: if (visible) animEntranceToolbox.restart()

            PageHeader {
                id: toolboxHeader
                anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
                glyph: Icons.wrench
                title: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_toolbox", "Toolbox")
                subtitle: appBackend.uiTrigger, appBackend.getTextWithDefault("toolbox_subtitle", "Görsel roman çevirilerini kusursuzlaştırmak, font hatalarını çözmek ve sözlük oluşturmak için hayat kurtaran altın araçlar.")
            }

            ScrollView {
                id: viewToolbox
                anchors.top: toolboxHeader.bottom; anchors.bottom: parent.bottom
                anchors.left: parent.left; anchors.right: parent.right
                clip: true
                contentWidth: availableWidth
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ScrollBar.vertical: ScrollBar {}


                ColumnLayout {
                    width: Math.min(parent.width - 48, 1180)
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 20

                    Item { Layout.preferredHeight: 6 } // başlık çizgisiyle ilk kart arası

                    // 2-Sütunlu Dengeli Araç Kutusu Izgarası
                    GridLayout {
                        Layout.fillWidth: true
                        columns: parent.width < 760 ? 1 : 2
                        columnSpacing: 18
                        rowSpacing: 18

                        // ── KART 1: FONT DEĞİŞTİRİCİ VE ENJEKTÖR ─────────────────────
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: fontCardCol.implicitHeight + 36
                            radius: 14; color: Theme.card; border.color: Theme.cardBorder; border.width: 1

                            ColumnLayout {
                                id: fontCardCol
                                anchors.fill: parent; anchors.margins: 18; spacing: 14

                                RowLayout {
                                    spacing: 12; Layout.fillWidth: true
                                    Rectangle {
                                        width: 38; height: 38; radius: 8; color: Theme.alpha(Theme.accent, 0.1)
                                        border.color: Theme.alpha(Theme.accent, 0.3); border.width: 1
                                        Icon { anchors.centerIn: parent; glyph: Icons.type; size: 18; color: Theme.accent }
                                    }
                                    ColumnLayout {
                                        spacing: 1; Layout.fillWidth: true
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_font_title", "Font Değiştirici ve Enjektör"); font.pixelSize: 16; font.bold: true; color: Theme.txt }
                                        Label { text: "OpenType / TrueType Auto-Injector"; font.pixelSize: 11; color: Theme.txtDim }
                                    }
                                    Rectangle {
                                        radius: 6; color: Theme.alpha(Theme.accent, 0.12)
                                        Layout.preferredHeight: 20; Layout.preferredWidth: 54
                                        Label { anchors.centerIn: parent; text: "FONT"; font.pixelSize: 10; font.bold: true; color: Theme.accent }
                                    }
                                }

                                Label {
                                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_font_desc", "Japonca/İngilizce oyun fontlarını Türkçe karakter destekli evrensel fontlarla otomatik değiştirerek kare kare yazı hatasını kökünden çözer.")
                                    font.pixelSize: 12; color: Theme.txt2; wrapMode: Text.Wrap; Layout.fillWidth: true
                                }

                                RowLayout {
                                    Layout.fillWidth: true; spacing: 10
                                    Button {
                                        Layout.fillWidth: true; height: 38
                                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("btn_run_font", "Kontrol Et")
                                        onClicked: appBackend.runToolFontHelper()
                                        background: Rectangle {
                                            radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input
                                            border.color: parent.hovered ? Theme.accent : Theme.cardBorder; border.width: 1
                                        }
                                        contentItem: IconLabel { glyph: Icons.scanSearch; text: parent.text; color: Theme.accent; font.pixelSize: 12; font.bold: true }
                                    }
                                    Button {
                                        Layout.fillWidth: true; height: 38
                                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("btn_font_inject", "Enjekte Et")
                                        onClicked: appBackend.runToolFontInject()
                                        background: Rectangle {
                                            radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input
                                            border.color: parent.hovered ? Theme.success : Theme.cardBorder; border.width: 1
                                        }
                                        contentItem: IconLabel { glyph: Icons.download; text: parent.text; color: Theme.success; font.pixelSize: 12; font.bold: true }
                                    }
                                }
                            }
                        }

                        // ── KART 2: REN'PY HATA DOKTORU (LINT) ──────────────────────
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: lintCardCol.implicitHeight + 36
                            radius: 14; color: Theme.card; border.color: Theme.cardBorder; border.width: 1

                            ColumnLayout {
                                id: lintCardCol
                                anchors.fill: parent; anchors.margins: 18; spacing: 14

                                RowLayout {
                                    spacing: 12; Layout.fillWidth: true
                                    Rectangle {
                                        width: 38; height: 38; radius: 8; color: Theme.alpha(Theme.purple, 0.1)
                                        border.color: Theme.alpha(Theme.purple, 0.3); border.width: 1
                                        Icon { anchors.centerIn: parent; glyph: Icons.stethoscope; size: 18; color: Theme.purple }
                                    }
                                    ColumnLayout {
                                        spacing: 1; Layout.fillWidth: true
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_lint_title", "Ren'Py Hata Doktoru"); font.pixelSize: 16; font.bold: true; color: Theme.txt }
                                        Label { text: "Syntax & Indentation Guard"; font.pixelSize: 11; color: Theme.txtDim }
                                    }
                                    Rectangle {
                                        radius: 6; color: Theme.alpha(Theme.purple, 0.15)
                                        Layout.preferredHeight: 20; Layout.preferredWidth: 48
                                        Label { anchors.centerIn: parent; text: "LINT"; font.pixelSize: 10; font.bold: true; color: Theme.purple }
                                    }
                                }

                                Label {
                                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_lint_desc", "Çeviri sonrasında bozulan satır girintularını, eksik tırnakları ve değişken etiketlerini tarayıp oyunun açılırken çökmesini önler.")
                                    font.pixelSize: 12; color: Theme.txt2; wrapMode: Text.Wrap; Layout.fillWidth: true
                                }

                                Button {
                                    Layout.fillWidth: true; height: 38
                                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("btn_run_lint", "Hata Taramasını Başlat")
                                    onClicked: appBackend.runToolRenpyLint()
                                    background: Rectangle {
                                        radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input
                                        border.color: parent.hovered ? Theme.purple : Theme.cardBorder; border.width: 1
                                    }
                                    contentItem: IconLabel { glyph: Icons.stethoscope; text: parent.text; color: Theme.purple; font.pixelSize: 12; font.bold: true }
                                }
                            }
                        }

                        // ── KART 3: TERİM SÖZLÜĞÜ ÇIKARICI (GLOSSARY) ───────────────
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: glossCardCol.implicitHeight + 36
                            radius: 14; color: Theme.card; border.color: Theme.cardBorder; border.width: 1

                            ColumnLayout {
                                id: glossCardCol
                                anchors.fill: parent; anchors.margins: 18; spacing: 14

                                RowLayout {
                                    spacing: 12; Layout.fillWidth: true
                                    Rectangle {
                                        width: 38; height: 38; radius: 8; color: Theme.alpha(Theme.success, 0.1)
                                        border.color: Theme.alpha(Theme.success, 0.3); border.width: 1
                                        Icon { anchors.centerIn: parent; glyph: Icons.bookA; size: 18; color: Theme.success }
                                    }
                                    ColumnLayout {
                                        spacing: 1; Layout.fillWidth: true
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_glossary_title", "Terim Sözlüğü Çıkarıcı"); font.pixelSize: 16; font.bold: true; color: Theme.txt }
                                        Label { text: "Entity & Name Scanner"; font.pixelSize: 11; color: Theme.txtDim }
                                    }
                                    Rectangle {
                                        radius: 6; color: Theme.alpha(Theme.success, 0.15)
                                        Layout.preferredHeight: 20; Layout.preferredWidth: 62
                                        Label { anchors.centerIn: parent; text: "GLOSSARY"; font.pixelSize: 10; font.bold: true; color: Theme.success }
                                    }
                                }

                                Label {
                                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_glossary_desc", "Oyun içindeki özel isimleri, karakter adlarını ve krallık terimlerini tarayıp otomatik olarak glossary.json dosyasına aktararak tutarlılık sağlar.")
                                    font.pixelSize: 12; color: Theme.txt2; wrapMode: Text.Wrap; Layout.fillWidth: true
                                }

                                Button {
                                    Layout.fillWidth: true; height: 38
                                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("btn_run_glossary", "Terim Sözlüğünü Çıkar")
                                    onClicked: appBackend.runToolGlossaryExtractor()
                                    background: Rectangle {
                                        radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input
                                        border.color: parent.hovered ? Theme.success : Theme.cardBorder; border.width: 1
                                    }
                                    contentItem: IconLabel { glyph: Icons.bookA; text: parent.text; color: Theme.success; font.pixelSize: 12; font.bold: true }
                                }
                            }
                        }

                        // ── KART: DİL ETKİNLEŞTİRME (zzz_<lang>_language.rpy) ───────
                        // Ren'Py does not list tl/ folders by itself: this writes (or
                        // removes) the file that starts the game in a translated language.
                        Rectangle {
                            id: langActivateCard
                            Layout.fillWidth: true
                            Layout.preferredHeight: langActCol.implicitHeight + 36
                            radius: 14; color: Theme.card; border.color: Theme.cardBorder; border.width: 1

                            property var tlLangs: []
                            function refreshLangs() {
                                tlLangs = appBackend.toolListTlLanguages()
                                var pre = appBackend.toolDefaultTlLanguage()
                                var idx = tlLangs.indexOf(pre)
                                langActCombo.currentIndex = idx >= 0 ? idx : (tlLangs.length > 0 ? 0 : -1)
                            }
                            Connections {
                                target: viewToolbox
                                function onVisibleChanged() { if (viewToolbox.visible) langActivateCard.refreshLangs() }
                            }
                            Component.onCompleted: refreshLangs()

                            ColumnLayout {
                                id: langActCol
                                anchors.fill: parent; anchors.margins: 18; spacing: 14

                                RowLayout {
                                    spacing: 12; Layout.fillWidth: true
                                    Rectangle {
                                        width: 38; height: 38; radius: 8; color: Theme.alpha(Theme.accent, 0.1)
                                        border.color: Theme.alpha(Theme.accent, 0.3); border.width: 1
                                        Icon { anchors.centerIn: parent; glyph: Icons.flag; size: 18; color: Theme.accent }
                                    }
                                    ColumnLayout {
                                        spacing: 1; Layout.fillWidth: true
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_lang_activate_title", "Language Activation"); font.pixelSize: 16; font.bold: true; color: Theme.txt }
                                        Label { text: "zzz_<lang>_language.rpy"; font.pixelSize: 11; color: Theme.txtDim }
                                    }
                                    Rectangle {
                                        radius: 6; color: Theme.alpha(Theme.accent, 0.15)
                                        Layout.preferredHeight: 20; Layout.preferredWidth: 48
                                        Label { anchors.centerIn: parent; text: "LANG"; font.pixelSize: 10; font.bold: true; color: Theme.accent }
                                    }
                                }

                                Label {
                                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_lang_activate_desc", "Ren'Py does not list the languages in the tl/ folder by itself. Pick a translation below to make the game start in that language, or remove the activation to return to the original language.")
                                    font.pixelSize: 12; color: Theme.txt2; wrapMode: Text.Wrap; Layout.fillWidth: true
                                }

                                RowLayout {
                                    Layout.fillWidth: true; spacing: 8
                                    ComboBox {
                                        id: langActCombo
                                        objectName: "toolLangActivateCombo"
                                        Layout.fillWidth: true; height: 38
                                        model: langActivateCard.tlLangs
                                        enabled: langActivateCard.tlLangs.length > 0
                                        displayText: langActivateCard.tlLangs.length > 0 ? currentText
                                                     : (appBackend.uiTrigger, appBackend.getTextWithDefault("tool_lang_no_tl", "No translation folders found in game/tl. Translate the game first."))
                                        background: Rectangle { radius: 8; color: Theme.input; border.color: parent.hovered ? Theme.accent : Theme.cardBorder; border.width: 1 }
                                        contentItem: Label {
                                            leftPadding: 14; rightPadding: 30
                                            text: langActCombo.displayText; elide: Text.ElideRight
                                            color: langActivateCard.tlLangs.length > 0 ? Theme.txt : Theme.txtDim
                                            font.pixelSize: 12; verticalAlignment: Text.AlignVCenter
                                        }
                                        delegate: ItemDelegate {
                                            width: langActCombo.width
                                            contentItem: Label { text: modelData; color: Theme.txt; font.pixelSize: 12; leftPadding: 14; elide: Text.ElideRight }
                                            background: Rectangle { color: hovered ? Theme.alpha(Theme.accent, 0.12) : "transparent" }
                                        }
                                        popup: Popup {
                                            y: langActCombo.height; width: langActCombo.width
                                            implicitHeight: Math.min(contentItem.implicitHeight, 220); padding: 4
                                            contentItem: ListView { clip: true; implicitHeight: contentHeight; model: langActCombo.delegateModel; ScrollBar.vertical: ScrollBar {} }
                                            background: Rectangle { color: Theme.card; radius: 8; border.color: Theme.cardBorder; border.width: 1 }
                                        }
                                    }
                                    // Rescan game/tl (e.g. after translating another language)
                                    Button {
                                        id: btnRefreshTlLangs
                                        Layout.preferredWidth: 38; Layout.preferredHeight: 38
                                        onClicked: langActivateCard.refreshLangs()
                                        ToolTip.visible: hovered
                                        ToolTip.delay: 250
                                        ToolTip.text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_lang_refresh", "Rescan the game's tl/ folder")
                                        background: Rectangle {
                                            radius: 8; color: btnRefreshTlLangs.hovered ? Theme.cardHover : Theme.input
                                            border.color: btnRefreshTlLangs.hovered ? Theme.accent : Theme.cardBorder; border.width: 1
                                        }
                                        contentItem: Label {
                                            text: "⟳"; color: btnRefreshTlLangs.hovered ? Theme.accent : Theme.txt2
                                            font.pixelSize: 18; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                                        }
                                    }
                                }

                                RowLayout {
                                    Layout.fillWidth: true; spacing: 8
                                    Button {
                                        Layout.fillWidth: true; height: 38
                                        enabled: langActivateCard.tlLangs.length > 0
                                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("btn_activate_language", "Start game in this language")
                                        onClicked: appBackend.runToolActivateLanguage(langActCombo.currentText)
                                        background: Rectangle {
                                            radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input
                                            border.color: parent.hovered ? Theme.accent : Theme.cardBorder; border.width: 1
                                        }
                                        contentItem: IconLabel { glyph: Icons.flag; text: parent.text; color: Theme.accent; font.pixelSize: 12; font.bold: true; elide: Text.ElideRight }
                                    }
                                    Button {
                                        Layout.fillWidth: true; height: 38
                                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("btn_remove_language_activation", "Remove activation")
                                        onClicked: appBackend.runToolRemoveLanguageActivation()
                                        background: Rectangle {
                                            radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input
                                            border.color: parent.hovered ? Theme.error : Theme.cardBorder; border.width: 1
                                        }
                                        contentItem: Label { text: parent.text; color: Theme.txt2; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                                    }
                                }
                            }
                        }

                        // ── KART 4: RPA & ARŞİV KORUMA DOKTORU ─────────────────────
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: rpaCardCol.implicitHeight + 36
                            radius: 14; color: Theme.card; border.color: Theme.cardBorder; border.width: 1

                            ColumnLayout {
                                id: rpaCardCol
                                anchors.fill: parent; anchors.margins: 18; spacing: 14

                                RowLayout {
                                    spacing: 12; Layout.fillWidth: true
                                    Rectangle {
                                        width: 38; height: 38; radius: 8; color: Theme.alpha(Theme.warn, 0.1)
                                        border.color: Theme.alpha(Theme.warn, 0.3); border.width: 1
                                        Icon { anchors.centerIn: parent; glyph: Icons.packageBox; size: 18; color: Theme.warn }
                                    }
                                    ColumnLayout {
                                        spacing: 1; Layout.fillWidth: true
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_unrpa_title", "Arşiv & AST Çözücü"); font.pixelSize: 16; font.bold: true; color: Theme.txt }
                                        Label { text: "Unrpa & AST Decompile Engine"; font.pixelSize: 11; color: Theme.txtDim }
                                    }
                                    Rectangle {
                                        radius: 6; color: Theme.alpha(Theme.warn, 0.15)
                                        Layout.preferredHeight: 20; Layout.preferredWidth: 60
                                        Label { anchors.centerIn: parent; text: "PIPELINE"; font.pixelSize: 10; font.bold: true; color: Theme.warn }
                                    }
                                }

                                Label {
                                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_unrpa_desc", "Oyun dizinindeki .rpa arşivlerini otomatik açar ve .rpyc ikili dosyalarını çözümler. Pipeline tarafından arka planda otomatik yönetilir.")
                                    font.pixelSize: 12; color: Theme.txt2; wrapMode: Text.Wrap; Layout.fillWidth: true
                                }

                                Rectangle {
                                    Layout.fillWidth: true; height: 38; radius: 8
                                    color: Theme.alpha(Theme.warn, 0.08)
                                    border.color: Theme.alpha(Theme.warn, 0.2); border.width: 1
                                    Label {
                                        anchors.centerIn: parent
                                        text: appBackend.uiTrigger, "✓ " + appBackend.getTextWithDefault("tool_unrpa_status", "Çeviri başlatıldığında otomatik devreye girer")
                                        color: Theme.warn; font.pixelSize: 11; font.bold: true
                                    }
                                }
                            }
                        }
                    }

                    Item { height: 24 }
                }
            }
        }

        // ═════════════════════════════════════════════════════════════
        // SEKME 4: GLOSSARY — TERİM SÖZLÜĞÜ YÖNETİMİ
        // ═════════════════════════════════════════════════════════════
        // ═════════════════════════════════════════════════════════════
        // SEKME 4: GLOSSARY — TERİM SÖZLÜĞÜ YÖNETİMİ
        // ═════════════════════════════════════════════════════════════
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
                subtitle: appBackend.uiTrigger, (pageGlossary.filteredGlossaryModel().length) + " / " + (appBackend.glossaryList ? appBackend.glossaryList.length : 0) + " " + appBackend.getTextWithDefault("glossary_count", "terms loaded.")
                actions: [
                    Button {
                        height: 34; text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_btn_add", "Add Term")
                        onClicked: { addGlossarySource.text = ""; addGlossaryTarget.text = ""; addGlossaryDialog.open() }
                        background: Rectangle { radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input; border.color: Theme.accent; border.width: 1 }
                        contentItem: IconLabel { glyph: Icons.plus; text: parent.text; color: Theme.accent; font.pixelSize: 11; font.bold: true }
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
                        onClicked: appBackend.fillEmptyGlossaryWithSource()
                        background: Rectangle { radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input; border.color: Theme.cardBorder; border.width: 1 }
                        contentItem: IconLabel { glyph: Icons.clipboardCopy; text: parent.text; color: Theme.txt; font.pixelSize: 11 }
                    },
                    Button {
                        height: 34; text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_btn_translate", "Translate Empty")
                        onClicked: appBackend.translateEmptyGlossary()
                        background: Rectangle { radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input; border.color: Theme.purple; border.width: 1 }
                        contentItem: IconLabel { glyph: Icons.languages; text: parent.text; color: Theme.purple; font.pixelSize: 11; font.bold: true }
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
                var list = appBackend.glossaryList || []
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
                        radius: 14; color: Theme.card; border.color: Theme.cardBorder; border.width: 1
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
                                onClicked: appBackend.removeGlossaryItem(modelData.source)
                                background: Rectangle { radius: 8; color: parent.hovered ? Theme.dangerTint : "transparent"; border.color: "transparent" }
                                contentItem: Label { text: "✕"; color: Theme.error; font.pixelSize: 14; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                            }
                        }
                    }

                    Item { height: 24 }
                }
            }
        }

        // ═════════════════════════════════════════════════════════════
        // SEKME 5: ÇEVİRİ EDİTÖRÜ (tl/<dil> satır satır düzenleme)
        // ═════════════════════════════════════════════════════════════
        EditorPage {
            id: pageEditor
            visible: navIndex === 5
            Layout.fillWidth: true
            Layout.fillHeight: true
        }
        }
    }

    // ── Toast Bildirim Köşesi (Fluent Glass & Slide-in) ────────────────────
    ToastNotification {
        id: toast
        parent: root.contentItem
    }

    // ── Uyarı ve Tamamlanma Popup Diyalogları ─────────────────────────────
    WarningDialog {
        id: warningDialog
    }

    Dialog {
        id: completionDialog
        anchors.centerIn: parent
        width: Math.min(540, root.width * 0.88)
        padding: 0
        header: null
        footer: null
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        standardButtons: Dialog.NoButton

        property string summaryText: ""
        property string outputPath: ""
        property string diagPath: ""

        enter: Transition {
            NumberAnimation { property: "opacity"; from: 0.0; to: 1.0; duration: 200; easing.type: Easing.OutCubic }
            NumberAnimation { property: "scale"; from: 0.92; to: 1.0; duration: 240; easing.type: Easing.OutBack; easing.overshoot: 1.3 }
        }
        exit: Transition {
            NumberAnimation { property: "opacity"; from: 1.0; to: 0.0; duration: 150; easing.type: Easing.InQuad }
            NumberAnimation { property: "scale"; from: 1.0; to: 0.94; duration: 150; easing.type: Easing.InQuad }
        }

        Overlay.modal: Rectangle {
            color: Theme.alpha(Theme.black, 0.65)
        }

        background: Rectangle {
            color: Theme.card
            radius: 18
            border.color: Theme.alpha(Theme.accent, 0.45)
            border.width: 1.5
            clip: true

            // Üst kısımdaki hafif neon gradyan vurgusu
            Rectangle {
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                height: 3
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: Theme.accent }
                    GradientStop { position: 1.0; color: Theme.accent2 }
                }
            }
        }

        contentItem: ColumnLayout {
            spacing: 18

            // 1. Üst Başlık ve Rozet
            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 22
                Layout.rightMargin: 20
                Layout.topMargin: 20
                spacing: 14

                Rectangle {
                    width: 42; height: 42; radius: 21
                    color: Theme.successDim
                    border.color: Theme.success; border.width: 1.5

                    Icon {
                        anchors.centerIn: parent
                        glyph: Icons.partyPopper
                        size: 20
                        color: Theme.success
                    }
                }

                ColumnLayout {
                    spacing: 3
                    Layout.fillWidth: true

                    Label {
                        text: appBackend.uiTrigger, cleanModalTitle(appBackend.getTextWithDefault("completion_summary_title", "Çeviri ve Derleme Tamamlandı"))
                        font.pixelSize: 18; font.bold: true; color: Theme.txt
                    }
                    Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("completion_summary_subtitle", "Oyun yerelleştirme dosyaları başarıyla üretildi.")
                        font.pixelSize: 12; color: Theme.txt2
                    }
                }

                Item { Layout.fillWidth: true }
                // Sağ üst kapatma '✕' butonu
                Rectangle {
                    width: 32; height: 32; radius: 16
                    color: closeCompletionMa.containsMouse ? Theme.alpha(Theme.white, 0.12) : "transparent"
                    scale: closeCompletionMa.pressed ? 0.92 : (closeCompletionMa.containsMouse ? 1.08 : 1.0)
                    Behavior on scale { NumberAnimation { duration: 120 } }
                    Behavior on color { ColorAnimation { duration: 120 } }

                    Label {
                        anchors.centerIn: parent
                        text: "✕"
                        color: closeCompletionMa.containsMouse ? Theme.white : Theme.txtDim
                        font.pixelSize: 13
                        font.bold: true
                    }
                    MouseArea {
                        id: closeCompletionMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: completionDialog.close()
                    }
                }
            }

            // 2. Özet Bilgi Kartı
            Rectangle {
                Layout.fillWidth: true
                Layout.leftMargin: 22
                Layout.rightMargin: 22
                Layout.preferredHeight: summaryCol.implicitHeight + 24
                radius: 12
                color: Theme.input
                border.color: Theme.alpha(Theme.white, 0.08)
                border.width: 1

                ColumnLayout {
                    id: summaryCol
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 10

                    RowLayout {
                        spacing: 10
                        Layout.fillWidth: true

                        Rectangle {
                            width: 26; height: 26; radius: 6
                            color: Theme.alpha(Theme.accent, 0.12)
                            Layout.alignment: Qt.AlignTop
                            Icon {
                                anchors.centerIn: parent
                                glyph: Icons.chartColumn
                                size: 14
                                color: Theme.accent
                            }
                        }

                        Label {
                            text: completionDialog.summaryText
                            color: Theme.txt
                            font.pixelSize: 13
                            font.weight: Font.Medium
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                            lineHeight: 1.35
                        }
                    }

                    // Çıktı klasör yolu (varsa)
                    Rectangle {
                        Layout.fillWidth: true
                        height: 32
                        radius: 7
                        color: Theme.inputDeep
                        border.color: Theme.alpha(Theme.white, 0.06)
                        border.width: 1
                        visible: completionDialog.outputPath.length > 0

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            spacing: 8

                            Icon {
                                glyph: Icons.folder
                                size: 14
                                color: Theme.txt2
                            }
                            Label {
                                text: completionDialog.outputPath
                                color: Theme.txtDim
                                font.pixelSize: 11
                                font.family: "Consolas"
                                elide: Text.ElideMiddle
                                Layout.fillWidth: true
                            }
                        }
                    }
                }
            }
            // 3a. Sonraki adımlar: oyunu çeviriyle başlat, çeviriyi editörde gözden geçir
            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 22
                Layout.rightMargin: 22
                spacing: 12

                Button {
                    id: launchGameBtn
                    Layout.fillWidth: true; height: 42
                    visible: !!appBackend.projectInfo.launcher
                    scale: down ? 0.97 : (hovered ? 1.02 : 1.0)
                    transformOrigin: Item.Center
                    Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                    onClicked: appBackend.launchGame()
                    background: Rectangle {
                        radius: 10
                        color: launchGameBtn.down ? Theme.alpha(Theme.success, 0.25) : (launchGameBtn.hovered ? Theme.alpha(Theme.success, 0.18) : Theme.alpha(Theme.success, 0.1))
                        border.color: Theme.alpha(Theme.success, launchGameBtn.hovered ? 0.8 : 0.45)
                        border.width: 1
                        Behavior on color { ColorAnimation { duration: 140 } }
                    }
                    contentItem: IconLabel {
                        glyph: Icons.play
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("completion_launch_game", "Launch Game")
                        color: Theme.success; font.bold: true; font.pixelSize: 13
                    }
                }

                Button {
                    id: reviewEditorBtn
                    Layout.fillWidth: true; height: 42
                    scale: down ? 0.97 : (hovered ? 1.02 : 1.0)
                    transformOrigin: Item.Center
                    Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                    onClicked: { completionDialog.close(); root.openEditorForTarget() }
                    background: Rectangle {
                        radius: 10
                        color: reviewEditorBtn.down ? Theme.alpha(Theme.purple, 0.22) : (reviewEditorBtn.hovered ? Theme.alpha(Theme.purple, 0.14) : Theme.input)
                        border.color: reviewEditorBtn.hovered ? Theme.purple : Theme.alpha(Theme.white, 0.12)
                        border.width: 1
                        Behavior on color { ColorAnimation { duration: 140 } }
                    }
                    contentItem: IconLabel {
                        glyph: Icons.squarePen
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("completion_open_editor", "Review in Editor")
                        color: reviewEditorBtn.hovered ? Theme.purple : Theme.txt; font.bold: true; font.pixelSize: 13
                    }
                }
            }

            // 3. Alt Butonlar Grubu
            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 22
                Layout.rightMargin: 22
                Layout.bottomMargin: 20
                spacing: 12

                // Çıktı Klasörünü Aç (Secondary Action Button)
                Button {
                    id: openFolderBtn
                    Layout.fillWidth: true; height: 42
                    visible: completionDialog.outputPath.length > 0
                    scale: down ? 0.97 : (hovered ? 1.02 : 1.0)
                    transformOrigin: Item.Center
                    Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                    onClicked: if (completionDialog.outputPath) appBackend.openLocalPath(completionDialog.outputPath)

                    background: Rectangle {
                        radius: 10
                        color: openFolderBtn.down ? Theme.alpha(Theme.accent, 0.18) : (openFolderBtn.hovered ? Theme.alpha(Theme.accent, 0.10) : Theme.input)
                        border.color: openFolderBtn.hovered ? Theme.accent : Theme.alpha(Theme.white, 0.12)
                        border.width: 1
                        Behavior on color { ColorAnimation { duration: 140 } }
                        Behavior on border.color { ColorAnimation { duration: 140 } }
                    }
                    contentItem: RowLayout {
                        spacing: 8
                        Item { Layout.fillWidth: true }
                        Icon { glyph: Icons.folderOpen; size: 14; color: openFolderBtn.hovered ? Theme.accent : Theme.txt }
                        Label {
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("open_output_folder", "Çıktı Klasörünü Aç")
                            color: openFolderBtn.hovered ? Theme.accent : Theme.txt
                            font.bold: true; font.pixelSize: 13
                        }
                        Item { Layout.fillWidth: true }
                    }
                }

                // Tamam (Primary Action Button)
                Button {
                    id: completionOkBtn
                    Layout.preferredWidth: completionDialog.outputPath.length > 0 ? 130 : parent.width
                    Layout.fillWidth: completionDialog.outputPath.length === 0
                    height: 42
                    scale: down ? 0.97 : (hovered ? 1.02 : 1.0)
                    transformOrigin: Item.Center
                    Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                    onClicked: completionDialog.close()

                    background: Rectangle {
                        radius: 10
                        color: completionOkBtn.hovered ? Theme.accentHover : Theme.accent
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: completionOkBtn.hovered ? Theme.accentHover : Theme.accent }
                            GradientStop { position: 1.0; color: completionOkBtn.hovered ? Theme.accent : Theme.accent2 }
                        }
                        Behavior on color { ColorAnimation { duration: 140 } }
                    }
                    contentItem: Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("dialog_ok", "Tamam")
                        color: Theme.textOnAccent
                        font.bold: true
                        font.pixelSize: 13
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
        }
    }

    Dialog {
        id: updateDialog
        anchors.centerIn: parent
        width: Math.min(480, root.width * 0.85)
        padding: 0
        header: null
        footer: null
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        standardButtons: Dialog.NoButton
        property string latestVersion: ""
        property string releaseUrl: ""

        enter: Transition {
            NumberAnimation { property: "opacity"; from: 0.0; to: 1.0; duration: 180; easing.type: Easing.OutCubic }
            NumberAnimation { property: "scale"; from: 0.94; to: 1.0; duration: 180; easing.type: Easing.OutCubic }
        }
        exit: Transition {
            NumberAnimation { property: "opacity"; from: 1.0; to: 0.0; duration: 140; easing.type: Easing.InQuad }
            NumberAnimation { property: "scale"; from: 1.0; to: 0.96; duration: 140; easing.type: Easing.InQuad }
        }

        Overlay.modal: Rectangle {
            color: Theme.alpha(Theme.black, 0.65)
        }

        background: Rectangle {
            color: Theme.card
            radius: 18
            border.color: Theme.alpha(Theme.accent, 0.45)
            border.width: 1.5
            clip: true

            Rectangle {
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                height: 3
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: Theme.accent }
                    GradientStop { position: 1.0; color: Theme.accent2 }
                }
            }
        }

        contentItem: ColumnLayout {
            spacing: 16

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 20
                Layout.rightMargin: 18
                Layout.topMargin: 20
                spacing: 14

                Rectangle {
                    width: 40; height: 40; radius: 20
                    color: Theme.alpha(Theme.accent, 0.15)
                    border.color: Theme.accent; border.width: 1.5

                    Icon {
                        anchors.centerIn: parent
                        glyph: Icons.rocket
                        size: 20
                        color: Theme.accent
                    }
                }

                ColumnLayout {
                    spacing: 2
                    Layout.fillWidth: true

                    Label {
                        text: appBackend.uiTrigger, cleanModalTitle(appBackend.getTextWithDefault("update_available_title", "Yeni Sürüm Mevcut"))
                        font.pixelSize: 18; font.bold: true; color: Theme.txt
                    }
                    Label {
                        text: updateDialog.latestVersion.length > 0 ? ("v" + updateDialog.latestVersion) : ""
                        font.pixelSize: 12; color: Theme.accent; font.bold: true
                        visible: updateDialog.latestVersion.length > 0
                    }
                }

                Item { Layout.fillWidth: true }
                Rectangle {
                    width: 30; height: 30; radius: 15
                    color: closeUpdateMa.containsMouse ? Theme.alpha(Theme.white, 0.12) : "transparent"
                    scale: closeUpdateMa.pressed ? 0.92 : (closeUpdateMa.containsMouse ? 1.08 : 1.0)
                    Behavior on scale { NumberAnimation { duration: 120 } }
                    Behavior on color { ColorAnimation { duration: 120 } }

                    Label {
                        anchors.centerIn: parent
                        text: "✕"
                        color: closeUpdateMa.containsMouse ? Theme.white : Theme.txtDim
                        font.pixelSize: 13; font.bold: true
                    }
                    MouseArea {
                        id: closeUpdateMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: updateDialog.close()
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.leftMargin: 20
                Layout.rightMargin: 20
                Layout.preferredHeight: updateBodyCol.implicitHeight + 24
                radius: 12
                color: Theme.input
                border.color: Theme.alpha(Theme.white, 0.08)
                border.width: 1

                ColumnLayout {
                    id: updateBodyCol
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 6

                    Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("update_available_msg", "RenLocalizer'ın yeni bir sürümü yayınlandı.")
                        color: Theme.txt
                        font.pixelSize: 13
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("update_available_click", "Güncellemeyi indirmek için İndir butonuna tıklayın.")
                        color: Theme.txt2
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 20
                Layout.rightMargin: 20
                Layout.bottomMargin: 20
                spacing: 12

                Button {
                    Layout.fillWidth: true; height: 40
                    scale: down ? 0.97 : (hovered ? 1.02 : 1.0)
                    transformOrigin: Item.Center
                    Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                    onClicked: updateDialog.close()

                    background: Rectangle {
                        radius: 10
                        color: parent.down ? Theme.alpha(Theme.white, 0.08) : (parent.hovered ? Theme.alpha(Theme.white, 0.05) : "transparent")
                        border.color: parent.hovered ? Theme.txt2 : Theme.cardBorder
                        border.width: 1
                        Behavior on border.color { ColorAnimation { duration: 140 } }
                    }
                    contentItem: Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_restart_later", "Daha Sonra")
                        color: Theme.txt2
                        font.pixelSize: 13
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }

                Button {
                    id: updateDownloadBtn
                    Layout.preferredWidth: 140; height: 40
                    scale: down ? 0.97 : (hovered ? 1.02 : 1.0)
                    transformOrigin: Item.Center
                    Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                    onClicked: {
                        if (updateDialog.releaseUrl) Qt.openUrlExternally(updateDialog.releaseUrl)
                        updateDialog.close()
                    }

                    background: Rectangle {
                        radius: 10
                        color: updateDownloadBtn.hovered ? Theme.accentHover : Theme.accent
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: updateDownloadBtn.hovered ? Theme.accentHover : Theme.accent }
                            GradientStop { position: 1.0; color: updateDownloadBtn.hovered ? Theme.accent : Theme.accent2 }
                        }
                        Behavior on color { ColorAnimation { duration: 140 } }
                    }
                    contentItem: IconLabel {
                        glyph: Icons.download
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("update_download_btn", "İndir")
                        color: Theme.textOnAccent
                        font.bold: true
                        font.pixelSize: 13
                    }
                }
            }
        }
    }

    Dialog {
        id: factoryResetDialog
        anchors.centerIn: parent
        width: Math.min(500, root.width * 0.85)
        padding: 0
        header: null
        footer: null
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        standardButtons: Dialog.NoButton

        enter: Transition {
            NumberAnimation { property: "opacity"; from: 0.0; to: 1.0; duration: 180; easing.type: Easing.OutCubic }
            NumberAnimation { property: "scale"; from: 0.94; to: 1.0; duration: 180; easing.type: Easing.OutCubic }
        }
        exit: Transition {
            NumberAnimation { property: "opacity"; from: 1.0; to: 0.0; duration: 140; easing.type: Easing.InQuad }
            NumberAnimation { property: "scale"; from: 1.0; to: 0.96; duration: 140; easing.type: Easing.InQuad }
        }

        Overlay.modal: Rectangle {
            color: Theme.alpha(Theme.black, 0.65)
        }

        background: Rectangle {
            color: Theme.card
            radius: 18
            border.color: Theme.alpha(Theme.error, 0.45)
            border.width: 1.5
            clip: true

            Rectangle {
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                height: 3
                color: Theme.error
            }
        }

        contentItem: ColumnLayout {
            spacing: 16

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 20
                Layout.rightMargin: 18
                Layout.topMargin: 20
                spacing: 14

                Rectangle {
                    width: 40; height: 40; radius: 20
                    color: Theme.alpha(Theme.error, 0.15)
                    border.color: Theme.error; border.width: 1.5

                    Icon {
                        anchors.centerIn: parent
                        glyph: Icons.triangleAlert
                        size: 20
                        color: Theme.error
                    }
                }

                ColumnLayout {
                    spacing: 2
                    Layout.fillWidth: true

                    Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_title", "Fabrika Ayarlarına Sıfırla")
                        font.pixelSize: 18; font.bold: true; color: Theme.txt
                    }
                    Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_subtitle", "Kalıcı Sıfırlama İşlemi")
                        font.pixelSize: 12; color: Theme.error
                    }
                }

                Item { Layout.fillWidth: true }
                Rectangle {
                    width: 30; height: 30; radius: 15
                    color: closeResetMa.containsMouse ? Theme.alpha(Theme.white, 0.12) : "transparent"
                    scale: closeResetMa.pressed ? 0.92 : (closeResetMa.containsMouse ? 1.08 : 1.0)
                    Behavior on scale { NumberAnimation { duration: 120 } }
                    Behavior on color { ColorAnimation { duration: 120 } }

                    Label {
                        anchors.centerIn: parent
                        text: "✕"
                        color: closeResetMa.containsMouse ? Theme.white : Theme.txtDim
                        font.pixelSize: 13; font.bold: true
                    }
                    MouseArea {
                        id: closeResetMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: factoryResetDialog.close()
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.leftMargin: 20
                Layout.rightMargin: 20
                Layout.preferredHeight: resetBodyLbl.implicitHeight + 24
                radius: 12
                color: Theme.input
                border.color: Theme.alpha(Theme.white, 0.08)
                border.width: 1

                Label {
                    id: resetBodyLbl
                    anchors.fill: parent
                    anchors.margins: 14
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_confirm", "Tüm ayarlar, API anahtarları, sözlük ve çeviri önbellekleri kalıcı olarak silinecek ve program ilk kurulduğu haline dönecek.\n\nEmin misiniz?")
                    color: Theme.txt
                    wrapMode: Text.Wrap
                    font.pixelSize: 13
                    lineHeight: 1.35
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 20
                Layout.rightMargin: 20
                Layout.bottomMargin: 20
                spacing: 12

                Button {
                    Layout.fillWidth: true; height: 40
                    scale: down ? 0.97 : (hovered ? 1.02 : 1.0)
                    transformOrigin: Item.Center
                    Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                    onClicked: factoryResetDialog.close()

                    background: Rectangle {
                        radius: 10
                        color: parent.down ? Theme.alpha(Theme.white, 0.08) : (parent.hovered ? Theme.alpha(Theme.white, 0.05) : "transparent")
                        border.color: parent.hovered ? Theme.txt2 : Theme.cardBorder
                        border.width: 1
                        Behavior on border.color { ColorAnimation { duration: 140 } }
                    }
                    contentItem: Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("dialog_cancel", "İptal")
                        color: Theme.txt2
                        font.pixelSize: 13
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }

                Button {
                    Layout.preferredWidth: 150; height: 40
                    scale: down ? 0.97 : (hovered ? 1.02 : 1.0)
                    transformOrigin: Item.Center
                    Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                    onClicked: {
                        factoryResetDialog.close()
                        if (appBackend.factoryReset())
                            factoryResetDoneDialog.open()
                    }

                    background: Rectangle {
                        radius: 10
                        color: parent.hovered ? Theme.errorStrong : Theme.error
                        Behavior on color { ColorAnimation { duration: 140 } }
                    }
                    contentItem: IconLabel {
                        glyph: Icons.trash2
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_btn", "Evet, Sıfırla")
                        color: Theme.white
                        font.bold: true
                        font.pixelSize: 13
                    }
                }
            }
        }
    }

    Dialog {
        id: factoryResetDoneDialog
        anchors.centerIn: parent
        width: Math.min(480, root.width * 0.85)
        padding: 0
        header: null
        footer: null
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        standardButtons: Dialog.NoButton

        enter: Transition {
            NumberAnimation { property: "opacity"; from: 0.0; to: 1.0; duration: 180; easing.type: Easing.OutCubic }
            NumberAnimation { property: "scale"; from: 0.94; to: 1.0; duration: 180; easing.type: Easing.OutCubic }
        }
        exit: Transition {
            NumberAnimation { property: "opacity"; from: 1.0; to: 0.0; duration: 140; easing.type: Easing.InQuad }
            NumberAnimation { property: "scale"; from: 1.0; to: 0.96; duration: 140; easing.type: Easing.InQuad }
        }

        Overlay.modal: Rectangle {
            color: Theme.alpha(Theme.black, 0.65)
        }

        background: Rectangle {
            color: Theme.card
            radius: 18
            border.color: Theme.alpha(Theme.success, 0.45)
            border.width: 1.5
            clip: true

            Rectangle {
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                height: 3
                color: Theme.success
            }
        }

        contentItem: ColumnLayout {
            spacing: 16

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 20
                Layout.rightMargin: 18
                Layout.topMargin: 20
                spacing: 14

                Rectangle {
                    width: 40; height: 40; radius: 20
                    color: Theme.successDim
                    border.color: Theme.success; border.width: 1.5

                    Icon {
                        anchors.centerIn: parent
                        glyph: Icons.circleCheck
                        size: 20
                        color: Theme.success
                    }
                }

                ColumnLayout {
                    spacing: 2
                    Layout.fillWidth: true

                    Label {
                        text: appBackend.uiTrigger, cleanModalTitle(appBackend.getTextWithDefault("factory_reset_done_title", "Sıfırlama Tamamlandı"))
                        font.pixelSize: 18; font.bold: true; color: Theme.txt
                    }
                    Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_done_sub", "Ayarlar varsayılan duruma getirildi")
                        font.pixelSize: 12; color: Theme.txt2
                    }
                }

                Item { Layout.fillWidth: true }
                Rectangle {
                    width: 30; height: 30; radius: 15
                    color: closeResetDoneMa.containsMouse ? Theme.alpha(Theme.white, 0.12) : "transparent"
                    scale: closeResetDoneMa.pressed ? 0.92 : (closeResetDoneMa.containsMouse ? 1.08 : 1.0)
                    Behavior on scale { NumberAnimation { duration: 120 } }
                    Behavior on color { ColorAnimation { duration: 120 } }

                    Label {
                        anchors.centerIn: parent
                        text: "✕"
                        color: closeResetDoneMa.containsMouse ? Theme.white : Theme.txtDim
                        font.pixelSize: 13; font.bold: true
                    }
                    MouseArea {
                        id: closeResetDoneMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: factoryResetDoneDialog.close()
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.leftMargin: 20
                Layout.rightMargin: 20
                Layout.preferredHeight: resetDoneBodyLbl.implicitHeight + 24
                radius: 12
                color: Theme.input
                border.color: Theme.alpha(Theme.white, 0.08)
                border.width: 1

                Label {
                    id: resetDoneBodyLbl
                    anchors.fill: parent
                    anchors.margins: 14
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_done_msg", "Program ilk kurulduğu haline döndü. Temiz bir başlangıç için uygulamayı yeniden başlatın; bundan sonra yaptığınız ayarlar otomatik kaydedilecektir.")
                    color: Theme.txt
                    wrapMode: Text.Wrap
                    font.pixelSize: 13
                    lineHeight: 1.35
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 20
                Layout.rightMargin: 20
                Layout.bottomMargin: 20
                spacing: 12

                Button {
                    Layout.fillWidth: true; height: 40
                    scale: down ? 0.97 : (hovered ? 1.02 : 1.0)
                    transformOrigin: Item.Center
                    Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                    onClicked: factoryResetDoneDialog.close()

                    background: Rectangle {
                        radius: 10
                        color: parent.down ? Theme.alpha(Theme.white, 0.08) : (parent.hovered ? Theme.alpha(Theme.white, 0.05) : "transparent")
                        border.color: parent.hovered ? Theme.txt2 : Theme.cardBorder
                        border.width: 1
                        Behavior on border.color { ColorAnimation { duration: 140 } }
                    }
                    contentItem: Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_restart_later", "Daha Sonra")
                        color: Theme.txt2
                        font.pixelSize: 13
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }

                Button {
                    id: factoryRestartBtn
                    Layout.preferredWidth: 180; height: 40
                    scale: down ? 0.97 : (hovered ? 1.02 : 1.0)
                    transformOrigin: Item.Center
                    Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                    onClicked: appBackend.restartApplication()

                    background: Rectangle {
                        radius: 10
                        color: factoryRestartBtn.hovered ? Theme.accentHover : Theme.accent
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: factoryRestartBtn.hovered ? Theme.accentHover : Theme.accent }
                            GradientStop { position: 1.0; color: factoryRestartBtn.hovered ? Theme.accent : Theme.accent2 }
                        }
                        Behavior on color { ColorAnimation { duration: 140 } }
                    }
                    contentItem: IconLabel {
                        glyph: Icons.refreshCw
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_restart_now", "Şimdi Yeniden Başlat")
                        color: Theme.textOnAccent
                        font.bold: true
                        font.pixelSize: 13
                    }
                }
            }
        }
    }

    // ── Glossary Dialogs ─────────────────────────────────────────────────
    GlossaryAddDialog {
        id: addGlossaryDialog
    }

    FileDialog {
        id: importGlossaryDialog
        title: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_dlg_import", "Import Glossary")
        nameFilters: ["Glossary Files (*.json *.csv *.xlsx)", "All Files (*)"]
        onAccepted: {
            var path = appBackend.urlToPath(selectedFile.toString())
            appBackend.importGlossary(path)
        }
    }

    FileDialog {
        id: exportGlossaryDialog
        title: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_dlg_export", "Export Glossary")
        fileMode: FileDialog.SaveFile
        nameFilters: ["JSON (*.json)", "CSV (*.csv)", "Excel (*.xlsx)"]
        onAccepted: {
            var path = appBackend.urlToPath(selectedFile.toString())
            appBackend.exportGlossary(path)
        }
    }

    // Sürükle-bırak: oyun klasörü, EXE/.sh ya da .app pencerenin herhangi bir yerine bırakılabilir
    DropArea {
        id: gameDropArea
        anchors.fill: parent
        z: 1000
        enabled: !isTranslating
        keys: ["text/uri-list"]
        onDropped: function(drop) {
            if (!drop.hasUrls || drop.urls.length === 0)
                return
            var raw = drop.urls[0].toString()
            appBackend.setProjectPath(raw)
            projectPathField.text = appBackend.urlToPath(raw)
            navIndex = 0
            drop.acceptProposedAction()
        }

        Rectangle {
            anchors.fill: parent
            anchors.margins: 12
            visible: gameDropArea.containsDrag
            radius: 18
            color: Theme.alpha(Theme.bg, 0.88)
            border.color: Theme.accent
            border.width: 2
            ColumnLayout {
                anchors.centerIn: parent
                spacing: 14
                Icon { glyph: Icons.folderOpen; size: 48; color: Theme.accent; Layout.alignment: Qt.AlignHCenter }
                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("drop_game_here", "Drop the game folder or its EXE here")
                    color: Theme.txt; font.pixelSize: 18; font.bold: true
                }
            }
        }
    }
}
