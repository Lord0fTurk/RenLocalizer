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
    Material.accent: clrAccent
    Material.primary: clrPrimary

    color: clrBg

    // ── Tek Premium Pro Koyu/Neon Palet (Siberpunk & Glassmorphism) ─────
    readonly property color clrBg:         "#0B0F17" // Koyu uzay zemin
    readonly property color clrSidebar:    "#111522" // Sol menü arkaplanı
    readonly property color clrSidebarTop: "#161B2E" // Sol menü üst gradyan
    readonly property color clrCard:       "#151A29" // Kart arkaplanı
    readonly property color clrCardHover:  "#1D2436" // Kart üzerine gelince
    readonly property color clrCardBorder: "#242C44" // İnce siber kenarlık
    readonly property color clrBorderGlow: "#00F2FE" // Turkuaz kart parlaması
    readonly property color clrInput:      "#0E121D" // Giriş kutuları
    readonly property color clrPrimary:    "#1A1E2E"
    readonly property color clrAccent:     "#00F2FE" // Turkuaz/Cyan neon
    readonly property color clrAccent2:    "#4FACFE" // Mavi gradyan bitiş
    readonly property color clrPurple:     "#A855F7" // Vurgu moru
    readonly property color clrSuccess:    "#10B981" // Yeşil çentik
    readonly property color clrSuccessDim: "#2610B981" // %15 zümrüt yeşil
    readonly property color clrWarn:       "#F59E0B" // Amber uyarı
    readonly property color clrWarnDim:    "#26F59E0B" // %15 amber sarı
    readonly property color clrError:      "#EF4444" // Kırmızı hata
    readonly property color clrTxt:        "#F3F4F6" // Ana beyaz metin
    readonly property color clrTxt2:       "#9CA3AF" // İkinci gri metin
    readonly property color clrTxtDim:     "#6B7280" // Soluk gri metin

    // Geriye uyumluluk aliasları (sinyal/bağlantı koruması için)
    readonly property color cardBg:    clrCard
    readonly property color inputBg:   clrInput
    readonly property color borderClr: clrCardBorder
    readonly property color txtMain:   clrTxt
    readonly property color txtSecond: clrTxt2
    readonly property color txtDim:    clrTxtDim
    readonly property color clrTxtMuted: clrTxtDim
    readonly property color accentClr: clrAccent
    readonly property color successClr:clrSuccess
    readonly property color warningClr:clrWarn
    readonly property color errorClr:  clrError

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
            color: clrTxt; wrapMode: Text.WordWrap
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
        if (level === "error")   return clrError
        if (level === "warning") return clrWarn
        if (level === "success") return clrSuccess
        if (level === "debug")   return clrTxtDim
        return clrTxt
    }

    function logPrefix(level) {
        var trigger = appBackend.uiTrigger
        if (level === "error")   return "[" + appBackend.getTextWithDefault("log_tag_error", "HATA").replace("[","").replace("]","") + "] "
        if (level === "warning") return "[" + appBackend.getTextWithDefault("log_tag_warn", "UYARI").replace("[","").replace("]","") + "] "
        if (level === "success") return "[" + appBackend.getTextWithDefault("log_tag_ok", "TAMAM").replace("[","").replace("]","") + "] "
        return "[" + appBackend.getTextWithDefault("log_tag_info", "BİLGİ").replace("[","").replace("]","") + "] "
    }

    function cleanModalTitle(str) {
        if (!str) return ""
        return str.replace(/^[\uD800-\uDBFF][\uDC00-\uDFFF]\s*/, "").replace(/^[🎉🚀✅⚠️📖➕]\s*/, "").trim()
    }

    function cleanStageText(str) {
        if (!str) return ""
        return str.replace(/[\.\s…]+$/, "").trim()
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
            color: clrSidebar

            // Sağ siber kenarlık
            Rectangle {
                anchors.right: parent.right
                width: 1; height: parent.height
                color: clrCardBorder
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
                        color: Qt.rgba(21, 26, 41, 0.7)
                        border.color: Qt.rgba(0, 242, 254, 0.28)
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
                            font.pixelSize: 17; font.bold: true; color: clrTxt
                            font.letterSpacing: 0.4
                        }

                        // Sürüm Rozeti (Pill Badge)
                        Rectangle {
                            implicitWidth: versionBadgeLayout.implicitWidth + 14
                            implicitHeight: 18
                            radius: 9
                            color: Qt.rgba(0, 242, 254, 0.08)
                            border.color: Qt.rgba(0, 242, 254, 0.24)
                            border.width: 1

                            RowLayout {
                                id: versionBadgeLayout
                                anchors.centerIn: parent
                                spacing: 5

                                Rectangle {
                                    width: 5; height: 5; radius: 2.5
                                    color: clrAccent
                                }

                                Text {
                                    text: "v" + appBackend.version
                                    font.pixelSize: 10
                                    font.bold: true
                                    font.letterSpacing: 0.3
                                    color: clrAccent
                                }
                            }
                        }
                    }
                }

                Item { height: 4 }
                Rectangle { Layout.fillWidth: true; height: 1; color: clrCardBorder; opacity: 0.7 }
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
                            color: navIndex === 0 ? Qt.rgba(0, 242, 254, 0.14) : (btnNavDash.hovered ? clrCardHover : "transparent")
                            border.color: navIndex === 0 ? Qt.rgba(0, 242, 254, 0.7) : "transparent"
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 150 } }
                            Behavior on border.color { ColorAnimation { duration: 150 } }

                            // Sol aktif neon gösterge çizgisi
                            Rectangle {
                                anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: 4
                                width: 3; height: navIndex === 0 ? 22 : 0
                                radius: 1.5; color: clrAccent
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
                            Label {
                                text: "🏠"; font.pixelSize: 17
                                scale: navIndex === 0 ? 1.15 : 1.0
                                Behavior on scale { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                            }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_dashboard", "Dashboard")
                                font.pixelSize: 13; font.bold: navIndex === 0; color: navIndex === 0 ? clrAccent : clrTxt
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
                            color: navIndex === 1 ? Qt.rgba(0, 242, 254, 0.14) : (btnNavSettings.hovered ? clrCardHover : "transparent")
                            border.color: navIndex === 1 ? Qt.rgba(0, 242, 254, 0.7) : "transparent"
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 150 } }
                            Behavior on border.color { ColorAnimation { duration: 150 } }

                            // Sol aktif neon gösterge çizgisi
                            Rectangle {
                                anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: 4
                                width: 3; height: navIndex === 1 ? 22 : 0
                                radius: 1.5; color: clrAccent
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
                            Label {
                                text: "⚙️"; font.pixelSize: 17
                                scale: navIndex === 1 ? 1.15 : 1.0
                                Behavior on scale { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                            }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_settings", "Settings & AI")
                                font.pixelSize: 13; font.bold: navIndex === 1; color: navIndex === 1 ? clrAccent : clrTxt
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
                            color: navIndex === 2 ? Qt.rgba(0, 242, 254, 0.14) : (btnNavLogs.hovered ? clrCardHover : "transparent")
                            border.color: navIndex === 2 ? Qt.rgba(0, 242, 254, 0.7) : "transparent"
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 150 } }
                            Behavior on border.color { ColorAnimation { duration: 150 } }

                            // Sol aktif neon gösterge çizgisi
                            Rectangle {
                                anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: 4
                                width: 3; height: navIndex === 2 ? 22 : 0
                                radius: 1.5; color: clrAccent
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
                            Label {
                                text: "📜"; font.pixelSize: 17
                                scale: navIndex === 2 ? 1.15 : 1.0
                                Behavior on scale { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                            }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_logs", "Log Console")
                                font.pixelSize: 13; font.bold: navIndex === 2; color: navIndex === 2 ? clrAccent : clrTxt
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
                            color: navIndex === 4 ? Qt.rgba(0, 242, 254, 0.14) : (btnNavGlossary.hovered ? clrCardHover : "transparent")
                            border.color: navIndex === 4 ? Qt.rgba(0, 242, 254, 0.7) : "transparent"
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 150 } }
                            Behavior on border.color { ColorAnimation { duration: 150 } }

                            // Sol aktif neon gösterge çizgisi
                            Rectangle {
                                anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: 4
                                width: 3; height: navIndex === 4 ? 22 : 0
                                radius: 1.5; color: clrAccent
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
                            Label {
                                text: "📚"; font.pixelSize: 17
                                scale: navIndex === 4 ? 1.15 : 1.0
                                Behavior on scale { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                            }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_glossary", "📚 Glossary")
                                font.pixelSize: 13; font.bold: navIndex === 4; color: navIndex === 4 ? clrAccent : clrTxt
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
                            color: navIndex === 5 ? Qt.rgba(0, 242, 254, 0.14) : (btnNavEditor.hovered ? clrCardHover : "transparent")
                            border.color: navIndex === 5 ? Qt.rgba(0, 242, 254, 0.7) : "transparent"
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 150 } }
                            Behavior on border.color { ColorAnimation { duration: 150 } }

                            // Sol aktif neon gösterge çizgisi
                            Rectangle {
                                anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: 4
                                width: 3; height: navIndex === 5 ? 22 : 0
                                radius: 1.5; color: clrAccent
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
                            Label {
                                text: "✏️"; font.pixelSize: 17
                                scale: navIndex === 5 ? 1.15 : 1.0
                                Behavior on scale { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                            }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_editor", "Editor")
                                font.pixelSize: 13; font.bold: navIndex === 5; color: navIndex === 5 ? clrAccent : clrTxt
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
                            color: navIndex === 3 ? Qt.rgba(0, 242, 254, 0.14) : (btnNavToolbox.hovered ? clrCardHover : "transparent")
                            border.color: navIndex === 3 ? Qt.rgba(0, 242, 254, 0.7) : "transparent"
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 150 } }
                            Behavior on border.color { ColorAnimation { duration: 150 } }

                            // Sol aktif neon gösterge çizgisi
                            Rectangle {
                                anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: 4
                                width: 3; height: navIndex === 3 ? 22 : 0
                                radius: 1.5; color: clrAccent
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
                            Label {
                                text: "🛠️"; font.pixelSize: 17
                                scale: navIndex === 3 ? 1.15 : 1.0
                                Behavior on scale { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                            }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_toolbox", "🛠️ Araç Kutusu")
                                font.pixelSize: 13; font.bold: navIndex === 3; color: navIndex === 3 ? clrAccent : clrTxt
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

                Rectangle { Layout.fillWidth: true; height: 1; color: clrCardBorder; opacity: 0.7 }
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
                            color: btnWikiGuide.down ? Qt.rgba(0, 242, 254, 0.1) : (btnWikiGuide.hovered ? clrCardHover : "transparent")
                            border.color: btnWikiGuide.hovered ? Qt.rgba(0, 242, 254, 0.5) : clrCardBorder
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 150 } }
                            Behavior on border.color { ColorAnimation { duration: 150 } }
                        }
                        contentItem: RowLayout {
                            anchors.centerIn: parent; spacing: 8
                            Label { text: "📖"; font.pixelSize: 14 }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_wiki_guide", "Wiki Guide")
                                color: btnWikiGuide.hovered ? clrTxt : clrTxt2; font.pixelSize: 12; elide: Text.ElideRight
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
                            color: btnPatreonSupport.down ? Qt.rgba(239, 68, 68, 0.25) : (btnPatreonSupport.hovered ? Qt.rgba(239, 68, 68, 0.15) : "transparent")
                            border.color: btnPatreonSupport.hovered ? "#EF4444" : "#991B1B"
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 150 } }
                            Behavior on border.color { ColorAnimation { duration: 150 } }
                        }
                        contentItem: RowLayout {
                            anchors.centerIn: parent; spacing: 8
                            Label { text: "❤️"; font.pixelSize: 14 }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_patreon_support", "Patreon Support")
                                color: btnPatreonSupport.hovered ? "#FFFFFF" : "#FCA5A5"; font.pixelSize: 12; elide: Text.ElideRight
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
                        color: isTranslating ? clrWarn : clrSuccess

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
                        color: clrTxt2; font.pixelSize: 12; font.bold: true
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

                // ── SABİT STICKY HEADER (ASLA KAYBOLMAZ) ──────────────
                Rectangle {
                    id: dashStickyHeader
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 76
                    color: clrBg
                    z: 10

                    RowLayout {
                        id: dashHeaderRow
                        anchors.fill: parent
                        anchors.leftMargin: 32; anchors.rightMargin: 32

                        transform: Translate { id: animTrDashHeader; y: 12 }
                        opacity: 0.0
                        SequentialAnimation {
                            id: animEntranceDashHeader
                            ParallelAnimation {
                                NumberAnimation { target: animTrDashHeader; property: "y"; to: 0; duration: 220; easing.type: Easing.OutCubic }
                                NumberAnimation { target: dashHeaderRow; property: "opacity"; to: 1.0; duration: 200; easing.type: Easing.OutQuad }
                            }
                        }
                        Component.onCompleted: if (navIndex === 0) animEntranceDashHeader.start()
                        Connections { target: root; function onNavIndexChanged() { if (navIndex === 0) animEntranceDashHeader.restart() } }

                        ColumnLayout {
                            spacing: 4
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_dashboard", "Dashboard")
                                font.pixelSize: 24; font.bold: true; color: clrTxt
                            }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("dashboard_subtitle", "Select game executable, configure translation engine/languages, and launch localization.")
                                font.pixelSize: 12; color: clrTxt2
                            }
                        }
                    }

                    // İnce ayrım çizgisi
                    Rectangle {
                        anchors.bottom: parent.bottom
                        anchors.left: parent.left; anchors.right: parent.right
                        height: 1
                        color: clrCardBorder
                        opacity: 0.6
                    }
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
                        radius: 16; color: cardProject.hovered ? clrCardHover : clrCard
                        border.color: cardProject.hovered ? Qt.rgba(0, 242, 254, 0.4) : clrCardBorder
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
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("card_project_setup", "Project Setup"); font.pixelSize: 16; font.bold: true; color: clrTxt }
                                    Item { Layout.fillWidth: true }
                                    // Proje Durum Rozeti
                                    Rectangle {
                                        visible: projectPathField.text.length > 0
                                        height: 24
                                        Layout.preferredWidth: projBadgeRow.implicitWidth + 16
                                        radius: 6
                                        color: Qt.rgba(16, 185, 129, 0.15)
                                        border.color: Qt.rgba(16, 185, 129, 0.4)
                                        border.width: 1
                                        RowLayout {
                                            id: projBadgeRow
                                            anchors.centerIn: parent; spacing: 4
                                            Label { text: "✓"; color: clrSuccess; font.bold: true; font.pixelSize: 11 }
                                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("badge_project_ready", "Proje Yüklendi"); color: clrSuccess; font.pixelSize: 11; font.bold: true }
                                        }
                                    }
                                }

                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("card_project_desc", "Select game executable file or game folder."); font.pixelSize: 12; color: clrTxt2 }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 12
                                    TextField {
                                        id: projectPathField
                                        Layout.fillWidth: true; height: 40
                                        font.pixelSize: 12; color: clrTxt
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
                                            color: clrInput
                                            border.color: projectPathField.hasError ? clrError : (projectPathField.activeFocus ? clrAccent : clrCardBorder)
                                            border.width: projectPathField.hasError ? 1.5 : 1
                                            Behavior on border.color { ColorAnimation { duration: 150 } }

                                            // QW-3 Focus Ring Glow & Error Halo (macOS/Fluent tarzı ışıma)
                                            Rectangle {
                                                anchors.fill: parent
                                                anchors.margins: -3
                                                radius: parent.radius + 2
                                                color: "transparent"
                                                border.color: projectPathField.hasError ? clrError : clrAccent
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
                                            color: clrTxtDim; font.pixelSize: 12; visible: projectPathField.text.length === 0 && !projectPathField.activeFocus
                                        }
                                    }
                                    Button {
                                        id: btnBrowseFolder
                                        height: 42
                                        Layout.preferredWidth: Math.max(115, implicitContentWidth + 32)
                                        text: appBackend.uiTrigger, "📁 " + appBackend.getTextWithDefault("browse_folder", "Klasör")
                                        scale: down ? 0.96 : (hovered ? 1.03 : 1.0)
                                        transformOrigin: Item.Center
                                        Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                                        onClicked: folderDialog.open()
                                        background: Rectangle {
                                            radius: 10
                                            color: parent.down ? Qt.rgba(0, 242, 254, 0.1) : (parent.hovered ? clrCardHover : clrInput)
                                            border.color: parent.hovered ? Qt.rgba(0, 242, 254, 0.6) : clrCardBorder
                                            border.width: parent.hovered ? 1.5 : 1
                                            Behavior on color { ColorAnimation { duration: 150 } }
                                            Behavior on border.color { ColorAnimation { duration: 150 } }
                                        }
                                        contentItem: Label {
                                            text: parent.text; color: parent.hovered ? clrAccent : clrTxt
                                            font.pixelSize: 13; font.bold: true
                                            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                                            Behavior on color { ColorAnimation { duration: 140 } }
                                        }
                                    }
                                    Button {
                                        id: btnBrowseExe
                                        height: 42
                                        Layout.preferredWidth: Math.max(135, implicitContentWidth + 32)
                                        text: appBackend.uiTrigger, "🎮 " + appBackend.getTextWithDefault("browse_exe", "EXE Dosyası")
                                        scale: down ? 0.96 : (hovered ? 1.03 : 1.0)
                                        transformOrigin: Item.Center
                                        Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                                        onClicked: fileDialog.open()
                                        background: Rectangle {
                                            radius: 10
                                            color: parent.down ? Qt.rgba(0, 242, 254, 0.25) : (parent.hovered ? Qt.rgba(0, 242, 254, 0.15) : clrInput)
                                            border.color: parent.hovered ? clrAccent : Qt.rgba(0, 242, 254, 0.4)
                                            border.width: parent.hovered ? 1.5 : 1
                                            Behavior on color { ColorAnimation { duration: 150 } }
                                            Behavior on border.color { ColorAnimation { duration: 150 } }
                                        }
                                        contentItem: Label {
                                            text: parent.text; color: clrAccent
                                            font.pixelSize: 13; font.bold: true
                                            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
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
                        Layout.preferredHeight: isAiEngine ? 228 : 135
                        clip: true
                        radius: 16; color: cardEngine.hovered ? clrCardHover : clrCard
                        border.color: cardEngine.hovered ? Qt.rgba(0, 242, 254, 0.4) : clrCardBorder
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
                            anchors.fill: parent; anchors.margins: 22
                            spacing: 14

                            RowLayout {
                                Layout.fillWidth: true
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("card_engine_title", "Translation Engine & Languages"); font.pixelSize: 16; font.bold: true; color: clrTxt }
                                Item { Layout.fillWidth: true }
                                Label {
                                    id: aiParamLink
                                    visible: cardEngine.isAiEngine
                                    text: appBackend.uiTrigger, "⚙️ " + appBackend.getTextWithDefault("advanced_settings_link", "Configure AI Parameters ->")
                                    color: aiLinkMa.containsMouse ? "#FFFFFF" : clrAccent
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

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 12

                                // ── Motor Seçimi ──────────────────────────────────────
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 260
                                    Layout.minimumWidth: 200
                                    spacing: 5
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("engine_label", "Machine Translation / AI Engine"); font.pixelSize: 11; color: clrTxt2; font.bold: true }
                                    ComboBox {
                                        id: engineComboBox
                                        Layout.fillWidth: true; height: 40
                                        // Swapping engines mid-run would replace the translator the pipeline is using
                                        enabled: !isTranslating
                                        function engineModel() {
                                            appBackend.uiTrigger // Re-eval on language change
                                            return [
                                                {"id": "google", "name": "🌐 Google Translate (" + appBackend.getTextWithDefault("engine_desc_google", "Primary / Free") + ")"},
                                                {"id": "bing", "name": "🪟 Bing / Microsoft Edge (" + appBackend.getTextWithDefault("engine_desc_bing", "Free / No key") + ")"},
                                                {"id": "openai", "name": "🤖 OpenAI / GPT-4o (" + appBackend.getTextWithDefault("engine_desc_ai", "AI Engine") + ")"},
                                                {"id": "gemini", "name": "💎 Gemini (" + appBackend.getTextWithDefault("engine_desc_gemini", "Google AI") + ")"},
                                                {"id": "deepseek", "name": "🧠 DeepSeek AI (" + appBackend.getTextWithDefault("engine_desc_deepseek", "Fast / Economic") + ")"},
                                                {"id": "local_llm", "name": "🖥️ Local LLM (Ollama / LM Studio)"},
                                                {"id": "libretranslate", "name": "📖 LibreTranslate (" + appBackend.getTextWithDefault("engine_desc_local", "Self-hosted") + ")"},
                                                {"id": "custom", "name": "🔗 Custom Endpoint (" + appBackend.getTextWithDefault("engine_desc_custom", "Custom API") + ")"}
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
                                            radius: 8; color: clrInput; border.color: parent.hovered ? clrAccent : clrCardBorder; border.width: 1
                                            Behavior on border.color { ColorAnimation { duration: 150 } }
                                        }
                                        contentItem: Label { leftPadding: 14; text: engineComboBox.displayText; color: clrTxt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                                        delegate: ItemDelegate {
                                            width: engineComboBox.width
                                            contentItem: Label { text: modelData.name; color: clrTxt; font.pixelSize: 12; leftPadding: 14; elide: Text.ElideRight }
                                            background: Rectangle { color: hovered ? Qt.rgba(0, 242, 254, 0.12) : "transparent"; Behavior on color { ColorAnimation { duration: 120 } } }
                                        }
                                        popup: Popup { y: engineComboBox.height + 4; width: engineComboBox.width; implicitHeight: Math.min(contentItem.implicitHeight, 240); padding: 4; contentItem: ListView { clip: true; implicitHeight: contentHeight; model: engineComboBox.delegateModel; ScrollBar.vertical: ScrollBar {} } background: Rectangle { color: clrCard; radius: 8; border.color: clrCardBorder; border.width: 1 } }
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
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("source_language", "Source Language"); font.pixelSize: 11; color: clrTxt2; font.bold: true; Layout.fillWidth: true }
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
                                                    color: sourceLangCombo.currentValue === modelData.code ? Qt.rgba(0, 242, 254, 0.22) : Qt.rgba(255, 255, 255, 0.05)
                                                    border.color: sourceLangCombo.currentValue === modelData.code ? clrAccent : Qt.rgba(255, 255, 255, 0.1)
                                                    border.width: 1
                                                    Label {
                                                        id: qkSrcTxt; anchors.centerIn: parent; text: modelData.name; font.pixelSize: 9; font.bold: true
                                                        color: sourceLangCombo.currentValue === modelData.code ? clrAccent : clrTxtDim
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
                                            radius: 8; color: clrInput; border.color: parent.hovered ? clrAccent : clrCardBorder; border.width: 1
                                            Behavior on border.color { ColorAnimation { duration: 150 } }
                                        }
                                        contentItem: Label { leftPadding: 14; text: sourceLangCombo.displayText !== "" ? sourceLangCombo.displayText : "🤖 Auto-detect"; color: clrTxt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                                        delegate: ItemDelegate {
                                            width: sourceLangCombo.width
                                            contentItem: Label { text: modelData.name; color: sourceLangCombo.highlightedIndex === index ? clrAccent : clrTxt; font.pixelSize: 12; leftPadding: 14; elide: Text.ElideRight }
                                            background: Rectangle { color: hovered ? Qt.rgba(0, 242, 254, 0.12) : "transparent"; Behavior on color { ColorAnimation { duration: 120 } } }
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
                                                color: clrCard
                                                radius: 12
                                                border.color: Qt.rgba(0, 242, 254, 0.4)
                                                border.width: 1
                                            }

                                            contentItem: ColumnLayout {
                                                spacing: 8
                                                anchors.fill: parent

                                                // 1. Canlı Arama Çubuğu
                                                Rectangle {
                                                    Layout.fillWidth: true; height: 36; radius: 8
                                                    color: clrInput
                                                    border.color: sourceSearchInput.activeFocus ? clrAccent : clrCardBorder
                                                    border.width: 1

                                                    RowLayout {
                                                        anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 8; spacing: 6
                                                        Label { text: "🔍"; font.pixelSize: 12; color: clrTxtDim }
                                                        TextInput {
                                                            id: sourceSearchInput
                                                            Layout.fillWidth: true
                                                            font.pixelSize: 12; color: clrTxt
                                                            clip: true
                                                            Text {
                                                                anchors.fill: parent; verticalAlignment: Text.AlignVCenter
                                                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("lang_search_placeholder", "Dil veya kod ara... (örn: ja, tr, en)")
                                                                color: clrTxtDim; font.pixelSize: 12
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
                                                            contentItem: Label { text: "✕"; color: clrTxtDim; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
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
                                                        color: mouseAreaSrcGrid.containsMouse ? Qt.rgba(0, 242, 254, 0.12) : (sourceLangCombo.currentValue === modelData.code ? Qt.rgba(0, 242, 254, 0.08) : clrInput)
                                                        border.color: sourceLangCombo.currentValue === modelData.code ? clrAccent : (mouseAreaSrcGrid.containsMouse ? Qt.rgba(0, 242, 254, 0.35) : clrCardBorder)
                                                        border.width: 1

                                                        RowLayout {
                                                            anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 8; spacing: 6
                                                            Label {
                                                                text: modelData.name
                                                                color: sourceLangCombo.currentValue === modelData.code ? clrAccent : clrTxt
                                                                font.pixelSize: 11; font.bold: sourceLangCombo.currentValue === modelData.code
                                                                Layout.fillWidth: true; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter
                                                            }
                                                            Rectangle {
                                                                width: srcCodeBadge.implicitWidth + 8; height: 18; radius: 4
                                                                color: sourceLangCombo.currentValue === modelData.code ? Qt.rgba(0, 242, 254, 0.25) : Qt.rgba(255, 255, 255, 0.06)
                                                                Label {
                                                                    id: srcCodeBadge; anchors.centerIn: parent
                                                                    text: (modelData.code || "").toUpperCase()
                                                                    font.pixelSize: 9; font.bold: true
                                                                    color: sourceLangCombo.currentValue === modelData.code ? clrAccent : clrTxtDim
                                                                }
                                                            }
                                                            Label {
                                                                visible: sourceLangCombo.currentValue === modelData.code
                                                                text: "✓"; color: clrAccent; font.bold: true; font.pixelSize: 11; verticalAlignment: Text.AlignVCenter
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
                                                Rectangle { Layout.fillWidth: true; height: 1; color: clrCardBorder }
                                                RowLayout {
                                                    Layout.fillWidth: true
                                                    Label {
                                                        text: sourceLangPopup.getFilteredList().length + " " + appBackend.getTextWithDefault("languages_available", "dil listelendi")
                                                        font.pixelSize: 10; color: clrTxtDim
                                                    }
                                                    Item { Layout.fillWidth: true }
                                                    Label {
                                                        text: appBackend.getTextWithDefault("lang_nav_hint", "↵ Enter: Seç | Esc: Kapat")
                                                        font.pixelSize: 10; color: clrTxtDim
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
                                        color: btnSwapLanguages.hovered ? Qt.rgba(0, 242, 254, 0.15) : clrInput
                                        border.color: btnSwapLanguages.hovered ? clrAccent : clrCardBorder
                                        border.width: 1
                                        Behavior on color { ColorAnimation { duration: 120 } }
                                        Behavior on border.color { ColorAnimation { duration: 120 } }
                                    }

                                    contentItem: Label {
                                        text: "⇄"
                                        font.pixelSize: 16
                                        font.bold: true
                                        color: btnSwapLanguages.hovered ? "#FFFFFF" : clrAccent
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
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("target_language", "Target Language"); font.pixelSize: 11; color: clrTxt2; font.bold: true; Layout.fillWidth: true }
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
                                                    color: targetLangCombo.currentValue === modelData.code ? Qt.rgba(0, 242, 254, 0.22) : Qt.rgba(255, 255, 255, 0.05)
                                                    border.color: targetLangCombo.currentValue === modelData.code ? clrAccent : Qt.rgba(255, 255, 255, 0.1)
                                                    border.width: 1
                                                    Label {
                                                        id: qkTgtTxt; anchors.centerIn: parent; text: modelData.name; font.pixelSize: 9; font.bold: true
                                                        color: targetLangCombo.currentValue === modelData.code ? clrAccent : clrTxtDim
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
                                            radius: 8; color: clrInput; border.color: parent.hovered ? clrAccent : clrCardBorder; border.width: 1
                                            Behavior on border.color { ColorAnimation { duration: 150 } }
                                        }
                                        contentItem: Label { leftPadding: 14; text: targetLangCombo.displayText; color: clrTxt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                                        delegate: ItemDelegate {
                                            width: targetLangCombo.width
                                            contentItem: Label { text: modelData.name; color: targetLangCombo.highlightedIndex === index ? clrAccent : clrTxt; font.pixelSize: 12; leftPadding: 14; elide: Text.ElideRight }
                                            background: Rectangle { color: hovered ? Qt.rgba(0, 242, 254, 0.12) : "transparent"; Behavior on color { ColorAnimation { duration: 120 } } }
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
                                                color: clrCard
                                                radius: 12
                                                border.color: Qt.rgba(0, 242, 254, 0.4)
                                                border.width: 1
                                            }

                                            contentItem: ColumnLayout {
                                                spacing: 8
                                                anchors.fill: parent

                                                // 1. Canlı Arama Çubuğu
                                                Rectangle {
                                                    Layout.fillWidth: true; height: 36; radius: 8
                                                    color: clrInput
                                                    border.color: targetSearchInput.activeFocus ? clrAccent : clrCardBorder
                                                    border.width: 1

                                                    RowLayout {
                                                        anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 8; spacing: 6
                                                        Label { text: "🔍"; font.pixelSize: 12; color: clrTxtDim }
                                                        TextInput {
                                                            id: targetSearchInput
                                                            Layout.fillWidth: true
                                                            font.pixelSize: 12; color: clrTxt
                                                            clip: true
                                                            Text {
                                                                anchors.fill: parent; verticalAlignment: Text.AlignVCenter
                                                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("lang_search_placeholder", "Dil veya kod ara... (örn: ja, tr, en)")
                                                                color: clrTxtDim; font.pixelSize: 12
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
                                                            contentItem: Label { text: "✕"; color: clrTxtDim; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
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
                                                        color: mouseAreaTgtGrid.containsMouse ? Qt.rgba(0, 242, 254, 0.12) : (targetLangCombo.currentValue === modelData.code ? Qt.rgba(0, 242, 254, 0.08) : clrInput)
                                                        border.color: targetLangCombo.currentValue === modelData.code ? clrAccent : (mouseAreaTgtGrid.containsMouse ? Qt.rgba(0, 242, 254, 0.35) : clrCardBorder)
                                                        border.width: 1

                                                        RowLayout {
                                                            anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 8; spacing: 6
                                                            Label {
                                                                text: modelData.name
                                                                color: targetLangCombo.currentValue === modelData.code ? clrAccent : clrTxt
                                                                font.pixelSize: 11; font.bold: targetLangCombo.currentValue === modelData.code
                                                                Layout.fillWidth: true; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter
                                                            }
                                                            Rectangle {
                                                                width: tgtCodeBadge.implicitWidth + 8; height: 18; radius: 4
                                                                color: targetLangCombo.currentValue === modelData.code ? Qt.rgba(0, 242, 254, 0.25) : Qt.rgba(255, 255, 255, 0.06)
                                                                Label {
                                                                    id: tgtCodeBadge; anchors.centerIn: parent
                                                                    text: (modelData.code || "").toUpperCase()
                                                                    font.pixelSize: 9; font.bold: true
                                                                    color: targetLangCombo.currentValue === modelData.code ? clrAccent : clrTxtDim
                                                                }
                                                            }
                                                            Label {
                                                                visible: targetLangCombo.currentValue === modelData.code
                                                                text: "✓"; color: clrAccent; font.bold: true; font.pixelSize: 11; verticalAlignment: Text.AlignVCenter
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
                                                Rectangle { Layout.fillWidth: true; height: 1; color: clrCardBorder }
                                                RowLayout {
                                                    Layout.fillWidth: true
                                                    Label {
                                                        text: targetLangPopup.getFilteredList().length + " " + appBackend.getTextWithDefault("languages_available", "dil listelendi")
                                                        font.pixelSize: 10; color: clrTxtDim
                                                    }
                                                    Item { Layout.fillWidth: true }
                                                    Label {
                                                        text: appBackend.getTextWithDefault("lang_nav_hint", "↵ Enter: Seç | Esc: Kapat")
                                                        font.pixelSize: 10; color: clrTxtDim
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            // ── AI HIZLI YAPILANDIRMA BARI (Dashboard Quick Config) ──
                            Rectangle {
                                Layout.fillWidth: true
                                height: 1
                                color: clrCardBorder
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
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_gemini_key", "Gemini API Key:"); color: clrTxt2; font.pixelSize: 11; font.bold: true }
                                    TextField {
                                        id: quickGeminiKeyField
                                        Layout.fillWidth: true; height: 38
                                        text: appBackend.geminiApiKey; echoMode: TextInput.Password; placeholderText: "AIza..."
                                        onEditingFinished: appBackend.geminiApiKey = text
                                        background: Rectangle {
                                            radius: 8; color: clrInput; border.color: parent.activeFocus ? clrAccent : clrCardBorder; border.width: 1
                                            Behavior on border.color { ColorAnimation { duration: 150 } }
                                        }
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true; Layout.preferredWidth: 3; spacing: 4
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_gemini_model", "Model:"); color: clrTxt2; font.pixelSize: 11; font.bold: true }
                                    TextField {
                                        id: quickGeminiModelField
                                        Layout.fillWidth: true; height: 38
                                        text: appBackend.geminiModel; placeholderText: "gemini-2.0-flash"
                                        onEditingFinished: appBackend.geminiModel = text
                                        background: Rectangle {
                                            radius: 8; color: clrInput; border.color: parent.activeFocus ? clrAccent : clrCardBorder; border.width: 1
                                            Behavior on border.color { ColorAnimation { duration: 150 } }
                                        }
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true; Layout.preferredWidth: 4; spacing: 4
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_gemini_safety", "Safety Filter Level:"); color: clrTxt2; font.pixelSize: 11; font.bold: true }
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
                                            radius: 8; color: clrInput; border.color: parent.hovered ? clrAccent : clrCardBorder; border.width: 1
                                            Behavior on border.color { ColorAnimation { duration: 150 } }
                                        }
                                        contentItem: Label { leftPadding: 12; text: quickGeminiSafetyCombo.displayText; color: clrTxt; font.pixelSize: 11; verticalAlignment: Text.AlignVCenter }
                                        delegate: ItemDelegate {
                                            width: quickGeminiSafetyCombo.width
                                            contentItem: Label { text: modelData.name; color: clrTxt; font.pixelSize: 11; leftPadding: 12 }
                                            background: Rectangle { color: hovered ? Qt.rgba(0, 242, 254, 0.12) : "transparent"; Behavior on color { ColorAnimation { duration: 120 } } }
                                        }
                                        popup: Popup { y: quickGeminiSafetyCombo.height; width: quickGeminiSafetyCombo.width; implicitHeight: Math.min(contentItem.implicitHeight, 180); padding: 4; contentItem: ListView { clip: true; implicitHeight: contentHeight; model: quickGeminiSafetyCombo.delegateModel; ScrollBar.vertical: ScrollBar {} } background: Rectangle { color: clrCard; radius: 8; border.color: clrCardBorder; border.width: 1 } }
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
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_openai_key", "API Key:"); color: clrTxt2; font.pixelSize: 11; font.bold: true }
                                    TextField {
                                        id: quickOpenaiKeyField
                                        Layout.fillWidth: true; height: 38
                                        text: appBackend.openaiApiKey; echoMode: TextInput.Password; placeholderText: "sk-..."
                                        onEditingFinished: appBackend.openaiApiKey = text
                                        background: Rectangle {
                                            radius: 8; color: clrInput; border.color: parent.activeFocus ? clrAccent : clrCardBorder; border.width: 1
                                            Behavior on border.color { ColorAnimation { duration: 150 } }
                                        }
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true; Layout.preferredWidth: 5; spacing: 4
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_openai_model", "Model:"); color: clrTxt2; font.pixelSize: 11; font.bold: true }
                                    TextField {
                                        id: quickOpenaiModelField
                                        Layout.fillWidth: true; height: 38
                                        text: appBackend.openaiModel; placeholderText: appBackend.selectedEngine === "deepseek" ? "deepseek-chat" : "gpt-4o-mini"
                                        onEditingFinished: appBackend.openaiModel = text
                                        background: Rectangle {
                                            radius: 8; color: clrInput; border.color: parent.activeFocus ? clrAccent : clrCardBorder; border.width: 1
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
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("local_llm_gguf_label", "GGUF Model File:"); color: clrTxt2; font.pixelSize: 11; font.bold: true }
                                    RowLayout {
                                        Layout.fillWidth: true; spacing: 6
                                        TextField {
                                            Layout.fillWidth: true; height: 38
                                            text: appBackend.localLlmGgufPath; placeholderText: "C:/models/model-Q4_K_M.gguf"
                                            onEditingFinished: appBackend.localLlmGgufPath = text
                                            background: Rectangle {
                                                radius: 8; color: clrInput; border.color: parent.activeFocus ? clrAccent : clrCardBorder; border.width: 1
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
                                                radius: 8; color: btnQuickGguf.hovered ? clrCardHover : clrInput
                                                border.color: btnQuickGguf.hovered ? clrAccent : clrCardBorder; border.width: 1
                                            }
                                            contentItem: Label {
                                                text: "📂"; font.pixelSize: 15
                                                horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                                            }
                                        }
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true; Layout.preferredWidth: 4; spacing: 4
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("local_llm_server_state_label", "Built-in server:"); color: clrTxt2; font.pixelSize: 11; font.bold: true }
                                    Label {
                                        Layout.fillWidth: true; Layout.preferredHeight: 38
                                        verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
                                        font.pixelSize: 12
                                        color: appBackend.localServerStatus === "ready" ? clrSuccess
                                             : appBackend.localServerStatus === "error" ? clrError : clrTxt2
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
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("local_llm_url_label", "Ollama / LM Studio URL:"); color: clrTxt2; font.pixelSize: 11; font.bold: true }
                                    TextField {
                                        id: quickLocalLlmUrlField
                                        Layout.fillWidth: true; height: 38
                                        text: appBackend.localLlmUrl; placeholderText: "http://localhost:11434/v1"
                                        onEditingFinished: appBackend.localLlmUrl = text
                                        background: Rectangle {
                                            radius: 8; color: clrInput; border.color: parent.activeFocus ? clrAccent : clrCardBorder; border.width: 1
                                            Behavior on border.color { ColorAnimation { duration: 150 } }
                                        }
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true; Layout.preferredWidth: 5; spacing: 4
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("local_llm_model_label", "Model Name:"); color: clrTxt2; font.pixelSize: 11; font.bold: true }
                                    TextField {
                                        id: quickLocalLlmModelField
                                        Layout.fillWidth: true; height: 38
                                        text: appBackend.localLlmModel; placeholderText: "qwen2.5-coder:7b-instruct"
                                        onEditingFinished: appBackend.localLlmModel = text
                                        background: Rectangle {
                                            radius: 8; color: clrInput; border.color: parent.activeFocus ? clrAccent : clrCardBorder; border.width: 1
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
                                    color: isTranslating ? (startButton.hovered ? "#F87171" : "#EF4444") : (startButton.hovered ? "#4FACFE" : "#00F2FE")
                                    Behavior on color { ColorAnimation { duration: 180; easing.type: Easing.OutQuad } }
                                }
                                GradientStop {
                                    position: 1.0
                                    color: isTranslating ? (startButton.hovered ? "#EF4444" : "#DC2626") : (startButton.hovered ? "#00F2FE" : "#4FACFE")
                                    Behavior on color { ColorAnimation { duration: 180; easing.type: Easing.OutQuad } }
                                }
                            }

                            // Dış neon ışıma katmanı (Glow border)
                            Rectangle {
                                anchors.fill: parent
                                radius: parent.radius
                                color: "transparent"
                                border.color: isTranslating ? "#EF4444" : "#00F2FE"
                                border.width: startButton.hovered || isTranslating ? 2 : 0
                                opacity: startButton.hovered || isTranslating ? 0.6 : 0.0
                                Behavior on opacity { NumberAnimation { duration: 180 } }
                                Behavior on border.width { NumberAnimation { duration: 150 } }
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
                                        color: "#FFFFFF"
                                        visible: isTranslating
                                        scale: isTranslating ? (startBtnBg.opacity < 0.9 ? 0.92 : 1.08) : 1.0
                                        Behavior on scale { NumberAnimation { duration: 400; easing.type: Easing.InOutQuad } }
                                    }

                                    // START İkonu (⚡ Şimşek)
                                    Label {
                                        anchors.centerIn: parent
                                        text: "⚡"
                                        font.pixelSize: 17
                                        color: startButton.hovered ? "#0B0F17" : "#0A0D14"
                                        visible: !isTranslating
                                    }
                                }

                                Label {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: appBackend.uiTrigger, isTranslating ? appBackend.getTextWithDefault("btn_stop_translation", "STOP TRANSLATION") : appBackend.getTextWithDefault("btn_start_translation", "START TRANSLATION →")
                                    font.pixelSize: 15; font.bold: true
                                    color: isTranslating ? "#FFFFFF" : (startButton.hovered ? "#0B0F17" : "#0A0D14")
                                    font.letterSpacing: 1.1
                                }
                            }
                        }
                    }

                    // Native TLID bilgi notu (Dengeli Responsive Banner)
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: ntTipLayout.implicitHeight + 20; radius: 10
                        visible: appBackend.outputMode === "native"
                        color: Qt.rgba(245, 158, 11, 0.08); border.color: Qt.rgba(245, 158, 11, 0.25); border.width: 1
                        RowLayout {
                            id: ntTipLayout
                            anchors.fill: parent; anchors.margins: 12; spacing: 10
                            Label { text: "⚠️"; font.pixelSize: 16; Layout.alignment: Qt.AlignTop }
                            Label {
                                id: ntTipLabel; Layout.fillWidth: true; wrapMode: Text.WordWrap
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("tip_native_limitation", "Tip: Some games build UI text at runtime (quests + \"(?)\" buttons, NPC schedules, Python f-strings). Native TLID captures static text only. If parts of the interface stay untranslated, switch to Standard mode and re-translate.")
                                color: clrWarn; font.pixelSize: 11; lineHeight: 1.25
                            }
                        }
                    }

                    // ── KART 3: PROCESS STATUS (DURUM BARI) ───────────────
                    Rectangle {
                        id: cardStatus
                        Layout.fillWidth: true
                        Layout.preferredHeight: statusInnerCol.implicitHeight + 44
                        radius: 16; color: cardStatus.hovered ? clrCardHover : clrCard
                        border.color: cardStatus.hovered ? Qt.rgba(0, 242, 254, 0.4) : clrCardBorder
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
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("card_status_title", "Process Status"); font.pixelSize: 16; font.bold: true; color: clrTxt }
                                Item { Layout.fillWidth: true }

                                // Canlı aktivite sonar noktası (Radar Pulse Dot)
                                Rectangle {
                                    id: stageActivityDot
                                    width: 8; height: 8; radius: 4
                                    color: currentStage === "completed" ? clrSuccess : (isTranslating ? clrAccent : "transparent")
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
                                        color: currentStage === "completed" ? clrSuccess : (currentStage === "error" ? clrError : clrAccent)
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
                                        color: clrAccent
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
                                    color: clrInput
                                    border.color: Qt.rgba(255, 255, 255, 0.06)
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
                                            GradientStop { position: 0.0; color: clrAccent }
                                            GradientStop { position: 1.0; color: clrAccent2 }
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
                                            GradientStop { position: 0.2; color: Qt.rgba(255, 255, 255, 0.08) }
                                            GradientStop { position: 0.5; color: Qt.rgba(255, 255, 255, 0.38) }
                                            GradientStop { position: 0.8; color: Qt.rgba(255, 255, 255, 0.08) }
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
                                Label { id: progressLabel; text: appBackend.uiTrigger, appBackend.getTextWithDefault("lines_processed", "Processed lines: 0 / 0 lines"); font.pixelSize: 12; color: clrTxt2 }
                                Item { Layout.fillWidth: true }
                                Label { text: Math.round(progressBar.value * 100) + "%"; font.pixelSize: 13; font.bold: true; color: clrTxt }
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
                                    color: clrSuccessDim
                                    border.color: clrSuccess
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
                                            color: clrSuccess
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
                                                color: "#FFFFFF"
                                                font.bold: true
                                                font.pixelSize: 13
                                            }
                                        }

                                        Label {
                                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("stats_completed_banner", "🎉 Çeviri Başarıyla Tamamlandı!")
                                            font.bold: true
                                            color: clrSuccess
                                            font.pixelSize: 13
                                        }

                                        Item { Layout.fillWidth: true }

                                        Label {
                                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("stats_summary_total", "Toplam:") + " " + totalLines + " | " + appBackend.getTextWithDefault("stats_summary_translated", "Çevrilen:") + " " + translatedLines + " (" + successRate.toFixed(1) + "%)"
                                            color: clrTxt
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
                        radius: 16; color: cardLog.hovered ? clrCardHover : clrCard
                        border.color: cardLog.hovered ? Qt.rgba(0, 242, 254, 0.4) : clrCardBorder
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
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("card_log_title", "Log Console Summary"); font.pixelSize: 15; font.bold: true; color: clrTxt }
                                Item { Layout.fillWidth: true }
                                Button {
                                    height: 28; text: appBackend.uiTrigger, "📜 " + appBackend.getTextWithDefault("view_all_logs", "Tüm Logları Aç ->")
                                    scale: down ? 0.96 : (hovered ? 1.04 : 1.0)
                                    transformOrigin: Item.Center
                                    Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                                    onClicked: navIndex = 2
                                    background: Rectangle {
                                        radius: 6
                                        color: parent.hovered ? Qt.rgba(0, 242, 254, 0.1) : "transparent"
                                        Behavior on color { ColorAnimation { duration: 140 } }
                                    }
                                    contentItem: Label {
                                        text: parent.text; color: parent.hovered ? "#FFFFFF" : clrAccent
                                        font.pixelSize: 12; font.underline: true
                                        Behavior on color { ColorAnimation { duration: 140 } }
                                    }
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true; Layout.fillHeight: true; radius: 10; color: clrInput; border.color: clrCardBorder; border.width: 1
                                ListView {
                                    id: logListView
                                    anchors.fill: parent; anchors.margins: 10; clip: true
                                    model: logModel
                                    delegate: RowLayout {
                                        width: logListView.width - 20; spacing: 12
                                        Label { text: model.ts; color: clrTxtDim; font.pixelSize: 11; font.family: "Consolas" }
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
                Rectangle {
                    id: settingsStickyHeader
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 116
                    color: clrBg
                    z: 10

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 32; anchors.rightMargin: 32
                        anchors.topMargin: 12; anchors.bottomMargin: 10
                        spacing: 10

                        RowLayout {
                            Layout.fillWidth: true
                            ColumnLayout {
                                spacing: 2
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_settings", "Settings & Advanced Configuration"); font.pixelSize: 24; font.bold: true; color: clrTxt }
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("settings_desc", "Configure UI language, translation threads, AI endpoints, and caching."); font.pixelSize: 12; color: clrTxt2 }
                            }
                        }

                        // Segmented Sub-Tab Bar
                        RowLayout {
                            spacing: 8

                            Button {
                                height: 34
                                Layout.preferredWidth: Math.max(150, implicitContentWidth + 24)
                                onClicked: pageSettings.settingsSubTab = 0
                                background: Rectangle {
                                    radius: 8
                                    color: pageSettings.settingsSubTab === 0 ? Qt.rgba(0, 242, 254, 0.15) : (parent.hovered ? clrCardHover : "transparent")
                                    border.color: pageSettings.settingsSubTab === 0 ? clrAccent : clrCardBorder
                                    border.width: 1
                                    Behavior on color { ColorAnimation { duration: 140 } }
                                }
                                contentItem: Label {
                                    text: appBackend.uiTrigger, "🖥️ " + appBackend.getTextWithDefault("subtab_general", "Genel & Çıktı")
                                    color: pageSettings.settingsSubTab === 0 ? clrAccent : clrTxt2
                                    font.bold: pageSettings.settingsSubTab === 0
                                    font.pixelSize: 12
                                    horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                                }
                            }

                            Button {
                                height: 34
                                Layout.preferredWidth: Math.max(160, implicitContentWidth + 24)
                                onClicked: pageSettings.settingsSubTab = 1
                                background: Rectangle {
                                    radius: 8
                                    color: pageSettings.settingsSubTab === 1 ? Qt.rgba(0, 242, 254, 0.15) : (parent.hovered ? clrCardHover : "transparent")
                                    border.color: pageSettings.settingsSubTab === 1 ? clrAccent : clrCardBorder
                                    border.width: 1
                                    Behavior on color { ColorAnimation { duration: 140 } }
                                }
                                contentItem: Label {
                                    text: appBackend.uiTrigger, "🤖 " + appBackend.getTextWithDefault("subtab_ai", "Yapay Zeka (AI)")
                                    color: pageSettings.settingsSubTab === 1 ? clrAccent : clrTxt2
                                    font.bold: pageSettings.settingsSubTab === 1
                                    font.pixelSize: 12
                                    horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                                }
                            }

                            Button {
                                height: 34
                                Layout.preferredWidth: Math.max(160, implicitContentWidth + 24)
                                onClicked: pageSettings.settingsSubTab = 2
                                background: Rectangle {
                                    radius: 8
                                    color: pageSettings.settingsSubTab === 2 ? Qt.rgba(0, 242, 254, 0.15) : (parent.hovered ? clrCardHover : "transparent")
                                    border.color: pageSettings.settingsSubTab === 2 ? clrAccent : clrCardBorder
                                    border.width: 1
                                    Behavior on color { ColorAnimation { duration: 140 } }
                                }
                                contentItem: Label {
                                    text: appBackend.uiTrigger, "⚡ " + appBackend.getTextWithDefault("subtab_perf", "Performans & Ağ")
                                    color: pageSettings.settingsSubTab === 2 ? clrAccent : clrTxt2
                                    font.bold: pageSettings.settingsSubTab === 2
                                    font.pixelSize: 12
                                    horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                                }
                            }

                            Item { Layout.fillWidth: true }
                        }
                    }

                    Rectangle {
                        anchors.bottom: parent.bottom
                        anchors.left: parent.left; anchors.right: parent.right
                        height: 1
                        color: clrCardBorder
                        opacity: 0.6
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
                        radius: 16; color: clrCard; border.color: clrCardBorder; border.width: 1

                        ColumnLayout {
                            anchors.fill: parent; anchors.margins: 22; spacing: 14
                            Label { text: appBackend.uiTrigger, "🖥️ " + appBackend.getTextWithDefault("settings_section_ui", "Arayüz & Sistem Ayarları"); font.pixelSize: 16; font.bold: true; color: clrAccent }

                            RowLayout {
                                Layout.fillWidth: true
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ui_language_label", "Arayüz Dili (UI Language):"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
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
                                    background: Rectangle { radius: 8; color: clrInput; border.color: clrCardBorder; border.width: 1 }
                                    contentItem: Label { leftPadding: 14; text: uiLanguageCombo.displayText; color: clrTxt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
                                    onActivated: appBackend.setUILanguage(currentValue)
                                    delegate: ItemDelegate { width: uiLanguageCombo.width; contentItem: Label { text: modelData.name; color: clrTxt; font.pixelSize: 12; leftPadding: 14 } background: Rectangle { color: hovered ? Qt.rgba(0, 242, 254, 0.12) : "transparent" } }
                                    popup: Popup { y: uiLanguageCombo.height; width: uiLanguageCombo.width; implicitHeight: 240; padding: 4; contentItem: ListView { clip: true; model: uiLanguageCombo.delegateModel; ScrollBar.vertical: ScrollBar {} } background: Rectangle { color: clrCard; radius: 8; border.color: clrCardBorder; border.width: 1 } }
                                }
                                Item { Layout.fillWidth: true }
                            }

                            RowLayout {
                                Layout.fillWidth: true; spacing: 16
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 2
                                    Label { text: appBackend.uiTrigger, "🔔 " + appBackend.getTextWithDefault("enable_desktop_notifications_label", "Masaüstü Bildirimleri"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("enable_desktop_notifications_tooltip", "Çeviri tamamlandığında veya hata oluştuğunda masaüstü bildirimi göster."); color: clrTxt2; font.pixelSize: 11; wrapMode: Text.WordWrap; Layout.fillWidth: true }
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
                        radius: 16; color: clrCard; border.color: clrCardBorder; border.width: 1
                        Behavior on Layout.preferredHeight { NumberAnimation { duration: 200 } }

                        ColumnLayout {
                            id: outCol
                            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                            anchors.margins: 22; spacing: 18

                            Label { text: appBackend.uiTrigger, "📦 " + appBackend.getTextWithDefault("settings_section_output", "Çıktı Üretim Modu & Çeviri Belleği (Output & TM Cache)"); font.pixelSize: 16; font.bold: true; color: clrAccent }

                            // KATMAN 1: GÖRSEL ÇİFT BUTONLU SEGMENTED SEÇİCİ (STRINGS vs NATIVE TLID)
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 10

                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_output_mode", "Ren'Py Çıktı Formatı Seçimi (Output Generation Mode):"); color: clrTxt; font.bold: true; font.pixelSize: 13 }

                                RowLayout {
                                    Layout.fillWidth: true; spacing: 14

                                    // Buton 1: Strings Modu
                                    Button {
                                        id: btnStringsMode
                                        Layout.fillWidth: true; height: 48
                                        onClicked: appBackend.outputMode = "strings"

                                        background: Rectangle {
                                            radius: 10
                                            color: appBackend.outputMode === "strings" ? Qt.rgba(0, 242, 254, 0.15) : (btnStringsMode.hovered ? Qt.rgba(1, 1, 1, 0.08) : clrInput)
                                            border.color: appBackend.outputMode === "strings" ? clrAccent : clrCardBorder
                                            border.width: appBackend.outputMode === "strings" ? 2 : 1
                                            Behavior on color { ColorAnimation { duration: 150 } }
                                        }

                                        contentItem: RowLayout {
                                            anchors.centerIn: parent; spacing: 8
                                            Label { text: appBackend.outputMode === "strings" ? "●" : "○"; color: appBackend.outputMode === "strings" ? clrAccent : clrTxtDim; font.pixelSize: 16 }
                                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("mode_strings_btn", "📋 Standard (strings.json)"); color: appBackend.outputMode === "strings" ? clrAccent : clrTxt; font.bold: appBackend.outputMode === "strings"; font.pixelSize: 12 }
                                        }
                                    }

                                    // Buton 2: Native TLID Modu
                                    Button {
                                        id: btnNativeMode
                                        Layout.fillWidth: true; height: 48
                                        onClicked: appBackend.outputMode = "native"

                                        background: Rectangle {
                                            radius: 10
                                            color: appBackend.outputMode === "native" ? Qt.rgba(0, 242, 254, 0.15) : (btnNativeMode.hovered ? Qt.rgba(1, 1, 1, 0.08) : clrInput)
                                            border.color: appBackend.outputMode === "native" ? clrAccent : clrCardBorder
                                            border.width: appBackend.outputMode === "native" ? 2 : 1
                                            Behavior on color { ColorAnimation { duration: 150 } }
                                        }

                                        contentItem: RowLayout {
                                            anchors.centerIn: parent; spacing: 6
                                            Label { text: appBackend.outputMode === "native" ? "●" : "○"; color: appBackend.outputMode === "native" ? clrAccent : clrTxtDim; font.pixelSize: 16 }
                                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("mode_native_btn", "⚡ Native TLID"); color: appBackend.outputMode === "native" ? clrAccent : clrTxt; font.bold: appBackend.outputMode === "native"; font.pixelSize: 12 }
                                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("badge_recommended", "💎 Recommended"); color: clrSuccess; font.pixelSize: 10; font.bold: true }
                                        }
                                    }
                                }

                                Rectangle {
                                    Layout.fillWidth: true; Layout.preferredHeight: descLayout.implicitHeight + 16
                                    radius: 8; color: Qt.rgba(1, 1, 1, 0.03); border.color: clrCardBorder; border.width: 1
                                    RowLayout {
                                        id: descLayout; anchors.fill: parent; anchors.margins: 8; spacing: 8
                                        Label { text: "💡"; font.pixelSize: 14 }
                                        Label {
                                            id: descLabel; Layout.fillWidth: true; wrapMode: Text.WordWrap
                                            text: appBackend.outputMode === "native" ?
                                                  (appBackend.uiTrigger, appBackend.getTextWithDefault("desc_native_mode", "Ren'Py built-in translate blocks for dialogues + auto-export translate strings: for UI. Zero Python scripts during gameplay — pure native speed. Works for ~90% of games. Known limitation: Python {variable} texts and runtime-concatenated strings may not be captured. Switch to Standard if you see untranslated screen elements.")) :
                                                  (appBackend.uiTrigger, appBackend.getTextWithDefault("desc_strings_mode", "Full runtime hook with O(1) lookup, MRU cache, screen harvesting, template matching, RTL. Handles ALL text types including dynamic and concatenated strings. Slightly higher memory (~3 MB). Recommended for complex screen UIs or when Native TLID misses text."))
                                            color: clrTxt2; font.pixelSize: 11
                                        }
                                    }
                                }

                                // Tip: when to use Standard mode
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: tipLayout.implicitHeight + 16
                                    radius: 8; color: Qt.rgba(245, 158, 11, 0.08); border.color: Qt.rgba(245, 158, 11, 0.25); border.width: 1
                                    visible: appBackend.outputMode === "native"
                                    RowLayout {
                                        id: tipLayout
                                        anchors.fill: parent; anchors.margins: 8; spacing: 8
                                        Label { text: "⚠️"; font.pixelSize: 14 }
                                        Label {
                                            id: tipLabel; Layout.fillWidth: true; wrapMode: Text.WordWrap
                                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("tip_native_limitation", "Some games define UI text in Python variables (quests, schedules, etc.). If you see untranslated screen text, switch to Standard mode — it handles these better.")
                                            color: clrWarn; font.pixelSize: 11
                                        }
                                    }
                                }
                            }

                            Rectangle { Layout.fillWidth: true; height: 1; color: clrCardBorder }

                            // Dil etkinleştirme dosyası (game/zzz_<lang>_language.rpy)
                            RowLayout {
                                Layout.fillWidth: true; spacing: 10
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("activate_language_title", "Start the game in the translated language"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("activate_language_desc", "Adds a small file to game/ that switches the game to the target language at launch. Turn off if you only want the tl/ files (e.g. to ship the translation yourself and let players choose the language)."); color: clrTxt2; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                                }
                                Switch { checked: appBackend.activateLanguageOnLaunch; onToggled: appBackend.activateLanguageOnLaunch = checked }
                            }

                            Rectangle { Layout.fillWidth: true; height: 1; color: clrCardBorder }

                            // KATMAN 2: ÇEVİRİ BELLEĞİ (TM CACHE) TOGGLE
                            RowLayout {
                                Layout.fillWidth: true; spacing: 16

                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 3
                                    Label { text: appBackend.uiTrigger, "💾 " + appBackend.getTextWithDefault("lite_cache_title", "Çeviri Belleği (TM Cache) Kullan"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("lite_cache_desc", "Daha önce çevrilen satırları hatırlar, aynı cümle tekrar geldiğinde anında bellekten getirir."); color: clrTxt2; font.pixelSize: 11; wrapMode: Text.WordWrap; Layout.fillWidth: true }
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
                        color: Qt.rgba(239, 68, 68, 0.04)
                        border.color: Qt.rgba(239, 68, 68, 0.3)
                        border.width: 1

                        ColumnLayout {
                            id: dangerCol
                            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                            anchors.margins: 22; spacing: 16

                            Label { text: appBackend.uiTrigger, "🛡️ " + appBackend.getTextWithDefault("danger_zone_title", "Bakım ve Veri Sıfırlama (Maintenance & Reset)"); font.pixelSize: 15; font.bold: true; color: clrError }

                            // Satır 1: Çeviri Belleğini Temizle
                            RowLayout {
                                Layout.fillWidth: true; spacing: 16
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 2
                                    Label { text: appBackend.uiTrigger, "🧹 " + appBackend.getTextWithDefault("clear_tm_title", "Çeviri Belleğini (TM) Temizle"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("clear_tm_desc", "Daha önce önbelleğe alınan tüm çeviri eşleşmelerini temizler."); color: clrTxt2; font.pixelSize: 11 }
                                }
                                Button {
                                    Layout.preferredWidth: 180; height: 38
                                    text: appBackend.uiTrigger, "🧹 " + appBackend.getTextWithDefault("lite_clear_cache_btn", "Önbelleği Temizle")
                                    onClicked: if (appBackend.clearTranslationCache()) showToast(appBackend.getTextWithDefault("cache_cleared_toast", "Translation cache cleared."), "success")
                                    background: Rectangle { radius: 8; color: parent.hovered ? "#991B1B" : "#7F1D1D"; border.color: "#B91C1C"; border.width: 1 }
                                    contentItem: Label { text: parent.text; color: "white"; font.bold: true; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                }
                            }

                            Rectangle { Layout.fillWidth: true; height: 1; color: Qt.rgba(239, 68, 68, 0.2) }

                            // Satır 2: Fabrika Ayarlarına Sıfırla
                            RowLayout {
                                Layout.fillWidth: true; spacing: 16
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 2
                                    Label { text: appBackend.uiTrigger, "🔄 " + appBackend.getTextWithDefault("factory_reset_title", "Fabrika Ayarlarına Sıfırla"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_desc", "Tüm ayarları, API anahtarlarını ve sözlüğü siler; programı varsayılan haline döndürür."); color: clrTxt2; font.pixelSize: 11 }
                                }
                                Button {
                                    Layout.preferredWidth: 180; height: 38
                                    text: appBackend.uiTrigger, "🔄 " + appBackend.getTextWithDefault("factory_reset_btn", "Sıfırla")
                                    onClicked: factoryResetDialog.open()
                                    background: Rectangle { radius: 8; color: parent.hovered ? "#991B1B" : "#7F1D1D"; border.color: "#B91C1C"; border.width: 1 }
                                    contentItem: Label { text: parent.text; color: "white"; font.bold: true; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
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
                        radius: 16; color: clrCard; border.color: clrCardBorder; border.width: 1
                        Behavior on Layout.preferredHeight { NumberAnimation { duration: 200 } }

                        ColumnLayout {
                            id: perfCol
                            anchors.fill: parent; anchors.margins: 22; spacing: 16
                            Label { text: appBackend.uiTrigger, "⚡ " + appBackend.getTextWithDefault("settings_section_perf", "Performans & Bağlantı Parametreleri"); font.pixelSize: 16; font.bold: true; color: clrAccent }

                            RowLayout {
                                Layout.fillWidth: true; spacing: 20
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 6
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("concurrency_label", "Concurrent Threads") + ": " + Math.round(threadsSlider.value); color: clrTxt; font.bold: true; font.pixelSize: 13; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                                    Slider { id: threadsSlider; Layout.fillWidth: true; from: 1; to: 32; stepSize: 1; value: appBackend.maxConcurrentThreads; onMoved: appBackend.maxConcurrentThreads = value }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 6
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("delay_label", "Request Delay") + ": " + delaySlider.value.toFixed(2) + "s"; color: clrTxt; font.bold: true; font.pixelSize: 13; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                                    Slider { id: delaySlider; Layout.fillWidth: true; from: 0.0; to: 3.0; stepSize: 0.05; value: appBackend.requestDelay; onMoved: appBackend.requestDelay = value }
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 6
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("batch_label", "Batch Size") + ": " + Math.round(batchSlider.value); color: clrTxt; font.bold: true; font.pixelSize: 13; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                                Slider { id: batchSlider; Layout.fillWidth: true; from: 10; to: 500; stepSize: 10; value: appBackend.maxBatchSize; onMoved: appBackend.maxBatchSize = value }
                            }

                            Rectangle { Layout.fillWidth: true; height: 1; color: clrCardBorder }

                            // 2-Sütunlu Dengeli Switch Izgarası
                            GridLayout {
                                Layout.fillWidth: true
                                columns: 2
                                columnSpacing: 24
                                rowSpacing: 16

                                // Switch 1: Multi-Endpoint
                                RowLayout {
                                    Layout.fillWidth: true; spacing: 10
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("multi_endpoint_title", "Multi-Endpoint (Mirror)"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("multi_endpoint_desc", "Distributes requests across Google servers."); color: clrTxt2; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                                    }
                                    Switch { checked: appBackend.useMultiEndpoint; onToggled: appBackend.useMultiEndpoint = checked }
                                }

                                // Switch 2: Parallel Batch
                                RowLayout {
                                    Layout.fillWidth: true; spacing: 10
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("parallel_batch_label", "Parallel Batch Requests"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("parallel_batch_desc", "Send multiple requests simultaneously. Disable if rate limited."); color: clrTxt2; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                                    }
                                    Switch {
                                        id: parallelBatchSwitch
                                        checked: appBackend.enableParallelBatch
                                        onToggled: appBackend.enableParallelBatch = checked
                                    }
                                }

                                // Switch 3: RPYC AST Reader
                                RowLayout {
                                    Layout.fillWidth: true; spacing: 10
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("rpyc_reader_title", "RPYC AST Reader"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("rpyc_reader_desc", "Reads compiled .rpyc files directly."); color: clrTxt2; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                                    }
                                    Switch { checked: appBackend.enableRpycReader; onToggled: appBackend.enableRpycReader = checked }
                                }

                                // Switch 4: Stateful Lexer
                                RowLayout {
                                    Layout.fillWidth: true; spacing: 10
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("stateful_lexer_title", "Stateful Lexer Engine (Experimental)"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("stateful_lexer_desc", "State-machine parser for script parsing. Enable to test stateful lexer pass."); color: clrTxt2; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap }
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
                        radius: 16; color: clrCard; border.color: clrCardBorder; border.width: 1
                        Behavior on Layout.preferredHeight { NumberAnimation { duration: 200 } }

                        ColumnLayout {
                            id: aiCol
                            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                            anchors.margins: 22; spacing: 16

                            Label { text: appBackend.uiTrigger, "🤖 " + appBackend.getTextWithDefault("settings_section_ai", "AI Engine Configuration"); font.pixelSize: 16; font.bold: true; color: clrAccent }

                            // OpenAI / DeepSeek Ayarları
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 14
                                visible: appBackend.selectedEngine === "openai" || appBackend.selectedEngine === "deepseek"

                                RowLayout {
                                    Layout.fillWidth: true; spacing: 18
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 5
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_openai_key", "OpenAI / DeepSeek API Key:"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                        TextField {
                                            Layout.fillWidth: true; height: 40; text: appBackend.openaiApiKey; echoMode: TextInput.Password; placeholderText: "sk-..."
                                            onEditingFinished: appBackend.openaiApiKey = text
                                            background: Rectangle {
                                                radius: 8; color: clrInput
                                                border.color: parent.activeFocus ? clrAccent : clrCardBorder; border.width: 1
                                                Behavior on border.color { ColorAnimation { duration: 150 } }
                                                Rectangle {
                                                    anchors.fill: parent; anchors.margins: -3; radius: parent.radius + 2; color: "transparent"
                                                    border.color: clrAccent; border.width: 2; opacity: parent.parent.activeFocus ? 0.35 : 0.0
                                                    scale: parent.parent.activeFocus ? 1.0 : 0.98
                                                    Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutQuad } }
                                                    Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                                                }
                                            }
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 5
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_openai_model", "Model Name:"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                        TextField {
                                            Layout.fillWidth: true; height: 40; text: appBackend.openaiModel; placeholderText: appBackend.selectedEngine === "deepseek" ? "deepseek-v4-flash" : "gpt-4o-mini"
                                            onEditingFinished: appBackend.openaiModel = text
                                            background: Rectangle {
                                                radius: 8; color: clrInput
                                                border.color: parent.activeFocus ? clrAccent : clrCardBorder; border.width: 1
                                                Behavior on border.color { ColorAnimation { duration: 150 } }
                                                Rectangle {
                                                    anchors.fill: parent; anchors.margins: -3; radius: parent.radius + 2; color: "transparent"
                                                    border.color: clrAccent; border.width: 2; opacity: parent.parent.activeFocus ? 0.35 : 0.0
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
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("openai_base_url_label", "Base URL (Optional, empty for default):"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                    TextField {
                                        Layout.fillWidth: true; height: 40; text: appBackend.openaiBaseUrl; placeholderText: appBackend.selectedEngine === "deepseek" ? "https://api.deepseek.com/v1" : "https://api.openai.com/v1"
                                        onEditingFinished: appBackend.openaiBaseUrl = text
                                        background: Rectangle {
                                            radius: 8; color: clrInput
                                            border.color: parent.activeFocus ? clrAccent : clrCardBorder; border.width: 1
                                            Behavior on border.color { ColorAnimation { duration: 150 } }
                                            Rectangle {
                                                anchors.fill: parent; anchors.margins: -3; radius: parent.radius + 2; color: "transparent"
                                                border.color: clrAccent; border.width: 2; opacity: parent.parent.activeFocus ? 0.35 : 0.0
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
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_gemini_key", "Gemini API Key:"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                        TextField {
                                            Layout.fillWidth: true; height: 40; text: appBackend.geminiApiKey; echoMode: TextInput.Password; placeholderText: "AIza..."
                                            onEditingFinished: appBackend.geminiApiKey = text
                                            background: Rectangle {
                                                radius: 8; color: clrInput
                                                border.color: parent.activeFocus ? clrAccent : clrCardBorder; border.width: 1
                                                Behavior on border.color { ColorAnimation { duration: 150 } }
                                                Rectangle {
                                                    anchors.fill: parent; anchors.margins: -3; radius: parent.radius + 2; color: "transparent"
                                                    border.color: clrAccent; border.width: 2; opacity: parent.parent.activeFocus ? 0.35 : 0.0
                                                    scale: parent.parent.activeFocus ? 1.0 : 0.98
                                                    Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutQuad } }
                                                    Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                                                }
                                            }
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 5
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_gemini_model", "Model:"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                        TextField {
                                            Layout.fillWidth: true; height: 40; text: appBackend.geminiModel; placeholderText: "gemini-2.0-flash"
                                            onEditingFinished: appBackend.geminiModel = text
                                            background: Rectangle {
                                                radius: 8; color: clrInput
                                                border.color: parent.activeFocus ? clrAccent : clrCardBorder; border.width: 1
                                                Behavior on border.color { ColorAnimation { duration: 150 } }
                                                Rectangle {
                                                    anchors.fill: parent; anchors.margins: -3; radius: parent.radius + 2; color: "transparent"
                                                    border.color: clrAccent; border.width: 2; opacity: parent.parent.activeFocus ? 0.35 : 0.0
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
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_gemini_safety", "Safety Filter Level:"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
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
                                                radius: 8; color: clrInput; border.color: parent.hovered ? clrAccent : clrCardBorder; border.width: 1
                                                Behavior on border.color { ColorAnimation { duration: 150 } }
                                            }
                                            contentItem: Label { leftPadding: 14; text: settingsGeminiSafetyCombo.displayText; color: clrTxt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
                                            delegate: ItemDelegate {
                                                width: settingsGeminiSafetyCombo.width
                                                contentItem: Label { text: modelData.name; color: clrTxt; font.pixelSize: 12; leftPadding: 14 }
                                                background: Rectangle { color: hovered ? Qt.rgba(0, 242, 254, 0.12) : "transparent"; Behavior on color { ColorAnimation { duration: 120 } } }
                                            }
                                            popup: Popup { y: settingsGeminiSafetyCombo.height; width: settingsGeminiSafetyCombo.width; implicitHeight: Math.min(contentItem.implicitHeight, 220); padding: 4; contentItem: ListView { clip: true; implicitHeight: contentHeight; model: settingsGeminiSafetyCombo.delegateModel; ScrollBar.vertical: ScrollBar {} } background: Rectangle { color: clrCard; radius: 8; border.color: clrCardBorder; border.width: 1 } }
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
                                        color: clrTxt; font.bold: true; font.pixelSize: 13
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
                                        background: Rectangle { radius: 8; color: clrInput; border.color: parent.hovered ? clrAccent : clrCardBorder; border.width: 1 }
                                        contentItem: Label { leftPadding: 14; text: localLlmModeCombo.displayText; color: clrTxt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
                                        delegate: ItemDelegate {
                                            width: localLlmModeCombo.width
                                            contentItem: Label { text: modelData.name; color: clrTxt; font.pixelSize: 12; leftPadding: 14; elide: Text.ElideRight }
                                            background: Rectangle { color: hovered ? Qt.rgba(0, 242, 254, 0.12) : "transparent" }
                                        }
                                        popup: Popup {
                                            y: localLlmModeCombo.height; width: localLlmModeCombo.width
                                            implicitHeight: Math.min(contentItem.implicitHeight, 160); padding: 4
                                            contentItem: ListView { clip: true; implicitHeight: contentHeight; model: localLlmModeCombo.delegateModel; ScrollBar.vertical: ScrollBar {} }
                                            background: Rectangle { color: clrCard; radius: 8; border.color: clrCardBorder; border.width: 1 }
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
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("local_llm_gguf_label", "GGUF Model Dosyası:"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                        RowLayout {
                                            Layout.fillWidth: true; spacing: 10
                                            TextField {
                                                Layout.fillWidth: true; height: 40
                                                text: appBackend.localLlmGgufPath
                                                placeholderText: "C:\\models\\Hy-MT2-7B-Q4_K_M.gguf"
                                                onEditingFinished: appBackend.localLlmGgufPath = text
                                                background: Rectangle { radius: 8; color: clrInput; border.color: clrCardBorder; border.width: 1 }
                                            }
                                            Button {
                                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("browse_btn", "Gözat")
                                                onClicked: ggufDialog.open()
                                                background: Rectangle { radius: 8; color: parent.hovered ? clrCardHover : clrInput; border.color: clrCardBorder; border.width: 1 }
                                                contentItem: Label { text: parent.text; color: clrTxt; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                            }
                                        }
                                    }

                                    // Arka uç + GPU katmanları + context
                                    RowLayout {
                                        Layout.fillWidth: true; spacing: 18

                                        ColumnLayout {
                                            Layout.fillWidth: true; Layout.preferredWidth: 3; spacing: 5
                                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("local_llm_backend_label", "GPU Arka Ucu:"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
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
                                                background: Rectangle { radius: 8; color: clrInput; border.color: parent.hovered ? clrAccent : clrCardBorder; border.width: 1 }
                                                contentItem: Label { leftPadding: 14; text: localLlmBackendCombo.displayText; color: clrTxt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                                                delegate: ItemDelegate {
                                                    width: localLlmBackendCombo.width
                                                    contentItem: Label { text: modelData.name; color: clrTxt; font.pixelSize: 12; leftPadding: 14; elide: Text.ElideRight }
                                                    background: Rectangle { color: hovered ? Qt.rgba(0, 242, 254, 0.12) : "transparent" }
                                                }
                                                popup: Popup {
                                                    y: localLlmBackendCombo.height; width: localLlmBackendCombo.width
                                                    implicitHeight: Math.min(contentItem.implicitHeight, 180); padding: 4
                                                    contentItem: ListView { clip: true; implicitHeight: contentHeight; model: localLlmBackendCombo.delegateModel; ScrollBar.vertical: ScrollBar {} }
                                                    background: Rectangle { color: clrCard; radius: 8; border.color: clrCardBorder; border.width: 1 }
                                                }
                                            }
                                        }

                                        ColumnLayout {
                                            Layout.fillWidth: true; Layout.preferredWidth: 2; spacing: 5
                                            Label {
                                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("local_llm_gpu_layers_label", "GPU Katmanı") + ": "
                                                      + (ggufLayersSlider.value < 0 ? appBackend.getTextWithDefault("local_llm_gpu_layers_auto", "Tümü") : Math.round(ggufLayersSlider.value))
                                                color: clrTxt; font.bold: true; font.pixelSize: 13
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
                                                color: clrTxt; font.bold: true; font.pixelSize: 13
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
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("local_llm_server_path_label", "Kendi llama-server dosyanız (opsiyonel):"); color: clrTxt2; font.pixelSize: 12 }
                                        RowLayout {
                                            Layout.fillWidth: true; spacing: 10
                                            TextField {
                                                Layout.fillWidth: true; height: 36
                                                text: appBackend.localLlmServerPath
                                                placeholderText: appBackend.getTextWithDefault("local_llm_server_path_hint", "Boş bırakılırsa indirilen çalışma zamanı kullanılır")
                                                onEditingFinished: appBackend.localLlmServerPath = text
                                                background: Rectangle { radius: 8; color: clrInput; border.color: clrCardBorder; border.width: 1 }
                                            }
                                            Button {
                                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("browse_btn", "Gözat")
                                                onClicked: llamaServerDialog.open()
                                                background: Rectangle { radius: 8; color: parent.hovered ? clrCardHover : clrInput; border.color: clrCardBorder; border.width: 1 }
                                                contentItem: Label { text: parent.text; color: clrTxt; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                            }
                                        }
                                    }

                                    // Durum + eylem düğmeleri
                                    RowLayout {
                                        Layout.fillWidth: true; spacing: 10

                                        Rectangle {
                                            width: 10; height: 10; radius: 5
                                            color: appBackend.localServerStatus === "ready" ? clrSuccess
                                                 : appBackend.localServerStatus === "error" ? clrError
                                                 : appBackend.localServerStatus === "stopped" ? clrTxtDim : clrWarn
                                        }

                                        Label {
                                            Layout.fillWidth: true
                                            wrapMode: Text.WordWrap
                                            font.pixelSize: 12
                                            color: appBackend.localServerStatus === "error" ? clrError : clrTxt2
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
                                            background: Rectangle { radius: 8; color: parent.hovered ? clrCardHover : clrInput; border.color: clrAccent; border.width: 1 }
                                            contentItem: Label { text: parent.text; color: clrAccent; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                        }

                                        Button {
                                            text: appBackend.uiTrigger, appBackend.localServerStatus === "ready"
                                                  ? appBackend.getTextWithDefault("local_server_stop_btn", "Durdur")
                                                  : appBackend.getTextWithDefault("local_server_start_btn", "Başlat")
                                            enabled: appBackend.localServerStatus !== "starting" && appBackend.localServerStatus !== "downloading"
                                            onClicked: appBackend.localServerStatus === "ready" ? appBackend.stopLocalServer() : appBackend.startLocalServer()
                                            background: Rectangle { radius: 8; color: parent.hovered ? clrCardHover : clrInput; border.color: clrCardBorder; border.width: 1 }
                                            contentItem: Label { text: parent.text; color: clrTxt; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                        }
                                    }

                                    Label {
                                        Layout.fillWidth: true
                                        wrapMode: Text.WordWrap
                                        font.pixelSize: 11
                                        color: clrTxtDim
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
                                        color: clrTxtDim
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
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_ollama_url", "Local LLM Server URL (Ollama/LM Studio):"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                        TextField {
                                            Layout.fillWidth: true; height: 40; text: appBackend.localLlmUrl; placeholderText: "http://localhost:11434/v1"
                                            onEditingFinished: appBackend.localLlmUrl = text
                                            background: Rectangle { radius: 8; color: clrInput; border.color: clrCardBorder; border.width: 1 }
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 5
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_ollama_model", "Local LLM Model Name:"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                        TextField {
                                            Layout.fillWidth: true; height: 40; text: appBackend.localLlmModel; placeholderText: "qwen2.5-coder:7b-instruct, llama3..."
                                            onEditingFinished: appBackend.localLlmModel = text
                                            background: Rectangle { radius: 8; color: clrInput; border.color: clrCardBorder; border.width: 1 }
                                        }
                                    }
                                }

                                // Local LLM Model Size & Quality Recommendation Hint
                                Rectangle {
                                    Layout.fillWidth: true
                                    radius: 8
                                    color: Qt.rgba(clrPrimary.r, clrPrimary.g, clrPrimary.b, 0.08)
                                    border.color: Qt.rgba(clrPrimary.r, clrPrimary.g, clrPrimary.b, 0.25)
                                    border.width: 1
                                    implicitHeight: localLlmHintRow.implicitHeight + 16

                                    RowLayout {
                                        id: localLlmHintRow
                                        anchors.fill: parent
                                        anchors.margins: 10
                                        spacing: 10

                                        Text {
                                            text: "💡"
                                            font.pixelSize: 14
                                            Layout.alignment: Qt.AlignVCenter
                                        }

                                        Label {
                                            Layout.fillWidth: true
                                            text: appBackend.uiTrigger, appBackend.getTextWithDefault(
                                                "tip_local_llm_model_recommendation",
                                                "Recommendation: Small local models (<3B parameters) often fail on game UI terms, formatting, and syntax. For reliable results, use at least 7B/8B models (e.g. Qwen 2.5 7B, Llama 3 8B) or Google / DeepSeek."
                                            )
                                            color: clrTxtMuted
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
                                            color: clrTxt; font.bold: true; font.pixelSize: 13
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
                                            background: Rectangle { radius: 8; color: clrInput; border.color: parent.hovered ? clrAccent : clrCardBorder; border.width: 1 }
                                            contentItem: Label { leftPadding: 14; rightPadding: 14; text: aiBatchModeCombo.displayText; color: clrTxt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                                            delegate: ItemDelegate {
                                                width: aiBatchModeCombo.width
                                                contentItem: Label { text: modelData.name; color: clrTxt; font.pixelSize: 12; leftPadding: 14; elide: Text.ElideRight }
                                                background: Rectangle { color: hovered ? Qt.rgba(0, 242, 254, 0.12) : "transparent" }
                                            }
                                            popup: Popup {
                                                y: aiBatchModeCombo.height; width: aiBatchModeCombo.width
                                                implicitHeight: Math.min(contentItem.implicitHeight, 200)
                                                padding: 4
                                                contentItem: ListView { clip: true; implicitHeight: contentHeight; model: aiBatchModeCombo.delegateModel; ScrollBar.vertical: ScrollBar {} }
                                                background: Rectangle { color: clrCard; radius: 8; border.color: clrCardBorder; border.width: 1 }
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
                                            color: clrTxt; font.bold: true; font.pixelSize: 13
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
                                Label {
                                    Layout.fillWidth: true
                                    wrapMode: Text.WordWrap
                                    font.pixelSize: 12
                                    color: clrTxt2
                                    text: {
                                        appBackend.uiTrigger
                                        if (appBackend.aiBatchFormat === "scene") {
                                            return appBackend.getTextWithDefault("ai_mode_scene_desc", "💡 Diyalogları senaryo akışı halinde iletir. Karakter hitaplarını, cinsiyet uyumunu ve bağlamı en iyi koruyan moddur (Görsel romanlar için önerilen).")
                                        } else if (appBackend.aiBatchFormat === "single") {
                                            return appBackend.getTextWithDefault("ai_mode_single_desc", "💡 Her satırı ayrı istek olarak gönderir; komşu satır ve konuşmacı bağlamı iletilmez. Küçük yerel modeller ve saf çeviri modelleri (Hy-MT) için önerilir — toplu istek biçimini bozmadıkları için sonuç daha tutarlı olur. Daha fazla istek, daha yavaş ama daha az format hatası.")
                                        } else if (appBackend.aiBatchFormat === "json") {
                                            return appBackend.getTextWithDefault("ai_mode_json_desc", "💡 Metinleri anahtar-değer çifti olarak iletir. Sıfır satır kayması ve katı veri bütünlüğü sağlar; menü ve sistem metinleri için idealdir.")
                                        } else {
                                            return appBackend.getTextWithDefault("ai_mode_xml_desc", "💡 Metinleri XML etiketleriyle paketler. JSON üretmekte zorlanan küçük veya eski modeller için en güvenli seçenektir.")
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
                                    color: Qt.rgba(0, 242, 254, 0.04)
                                    border.color: appBackend.hyMt2Active ? clrAccent : clrCardBorder
                                    border.width: 1

                                    ColumnLayout {
                                        id: hyMt2Inner
                                        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                                        anchors.margins: 14; spacing: 12

                                        RowLayout {
                                            Layout.fillWidth: true; spacing: 10
                                            Label { text: appBackend.uiTrigger, "🎯 " + appBackend.getTextWithDefault("hy_mt2_title", "Hy-MT2 (Tencent) — Specialized Translation Profile"); color: clrAccent; font.bold: true; font.pixelSize: 14 }
                                            Item { Layout.fillWidth: true }
                                            Rectangle {
                                                radius: 10
                                                color: appBackend.hyMt2Active ? Qt.rgba(0, 0.8, 0.4, 0.18) : Qt.rgba(0.5, 0.5, 0.5, 0.15)
                                                Layout.preferredHeight: 22; Layout.preferredWidth: hyMt2BadgeTxt.implicitWidth + 20
                                                Label { id: hyMt2BadgeTxt; anchors.centerIn: parent; text: appBackend.uiTrigger, appBackend.hyMt2Active ? appBackend.getTextWithDefault("hy_mt2_active_badge", "ACTIVE") : appBackend.getTextWithDefault("hy_mt2_inactive_badge", "OFF"); font.pixelSize: 11; font.bold: true; color: appBackend.hyMt2Active ? clrAccent : clrTxt2 }
                                            }
                                        }

                                        Label {
                                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("hy_mt2_info", "Optimized for Tencent Hy-MT translation models: uses official instruction templates (no system prompt), delimiter preservation and the model-card sampling recipe (temp 0.7, top_p 0.6, top_k 20, rep.pen 1.05) for maximum speed and quality.")
                                            color: clrTxt2; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.WordWrap
                                        }

                                        ColumnLayout {
                                            Layout.fillWidth: true; spacing: 5
                                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("hy_mt2_profile_label", "Profile Mode:"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
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
                                                background: Rectangle { radius: 8; color: clrInput; border.color: parent.hovered ? clrAccent : clrCardBorder; border.width: 1 }
                                                contentItem: Label { leftPadding: 14; text: hyMt2ProfileCombo.displayText; color: clrTxt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
                                                delegate: ItemDelegate {
                                                    width: hyMt2ProfileCombo.width
                                                    contentItem: Label { text: modelData.name; color: clrTxt; font.pixelSize: 12; leftPadding: 14 }
                                                    background: Rectangle { color: hovered ? Qt.rgba(0, 242, 254, 0.12) : "transparent" }
                                                }
                                                popup: Popup { y: hyMt2ProfileCombo.height; width: hyMt2ProfileCombo.width; implicitHeight: Math.min(contentItem.implicitHeight, 220); padding: 4; contentItem: ListView { clip: true; implicitHeight: contentHeight; model: hyMt2ProfileCombo.delegateModel; ScrollBar.vertical: ScrollBar {} } background: Rectangle { color: clrCard; radius: 8; border.color: clrCardBorder; border.width: 1 } }
                                            }
                                        }

                                        Label {
                                            text: appBackend.uiTrigger, appBackend.hyMt2Active
                                                ? appBackend.getTextWithDefault("hy_mt2_detected", "✓ Hy-MT2 profile is active — official instructions and sampling will be used.")
                                                  + " " + appBackend.getTextWithDefault("hy_mt2_single_note", "Each line is sent as its own request; the batch format selector does not apply.")
                                                : appBackend.getTextWithDefault("hy_mt2_not_detected", "No Hy-MT model detected in the model name. Choose 'Force Hy-MT2 profile' to enable it anyway.")
                                            color: appBackend.hyMt2Active ? clrAccent : clrTxt2
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
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("libretranslate_url_label", "LibreTranslate Server URL:"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                        TextField {
                                            Layout.fillWidth: true; height: 40; text: appBackend.libretranslateUrl; placeholderText: "http://localhost:5000"
                                            onEditingFinished: appBackend.libretranslateUrl = text
                                            background: Rectangle { radius: 8; color: clrInput; border.color: clrCardBorder; border.width: 1 }
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 5
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("libretranslate_api_key_label", "LibreTranslate API Key (Optional):"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                        TextField {
                                            Layout.fillWidth: true; height: 40; text: appBackend.libretranslateApiKey; echoMode: TextInput.Password
                                            onEditingFinished: appBackend.libretranslateApiKey = text
                                            background: Rectangle { radius: 8; color: clrInput; border.color: clrCardBorder; border.width: 1 }
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
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("custom_url_label", "Custom API Endpoint URL:"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                        TextField {
                                            Layout.fillWidth: true; height: 40; text: appBackend.customEndpointUrl; placeholderText: "http://localhost:8000/translate"
                                            onEditingFinished: appBackend.customEndpointUrl = text
                                            background: Rectangle { radius: 8; color: clrInput; border.color: clrCardBorder; border.width: 1 }
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 5
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("custom_api_key_label", "Custom API Key (Optional):"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                        TextField {
                                            Layout.fillWidth: true; height: 40; text: appBackend.customEndpointApiKey; echoMode: TextInput.Password
                                            onEditingFinished: appBackend.customEndpointApiKey = text
                                            background: Rectangle { radius: 8; color: clrInput; border.color: clrCardBorder; border.width: 1 }
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
                        radius: 16; color: clrCard; border.color: clrCardBorder; border.width: 1
                        Behavior on Layout.preferredHeight { NumberAnimation { duration: 200 } }

                        ColumnLayout {
                            id: aiTuningCol
                            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                            anchors.margins: 22; spacing: 18

                            Label { text: appBackend.uiTrigger, "⚡ " + appBackend.getTextWithDefault("ai_tuning_title", "Advanced AI Tuning & System Prompt"); font.pixelSize: 16; font.bold: true; color: clrAccent }

                            // Satır 1: Temperature & Max Tokens
                            RowLayout {
                                Layout.fillWidth: true; spacing: 24
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 6
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_temp_label", "AI Temperature") + ": " + aiTempSlider.value.toFixed(2); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                    Slider { id: aiTempSlider; Layout.fillWidth: true; from: 0.0; to: 1.0; stepSize: 0.05; value: appBackend.aiTemperature; onMoved: appBackend.aiTemperature = value }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 6
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_tokens_label", "Max Tokens") + ": " + Math.round(aiTokensSlider.value); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                    Slider { id: aiTokensSlider; Layout.fillWidth: true; from: 256; to: 8192; stepSize: 256; value: appBackend.aiMaxTokens; onMoved: appBackend.aiMaxTokens = value }
                                }
                            }

                            // Satır 2: AI Timeout & AI Batch Size
                            RowLayout {
                                Layout.fillWidth: true; spacing: 24
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 6
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_timeout_label", "AI Timeout") + ": " + Math.round(aiTimeoutSlider.value) + "s"; color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                    Slider { id: aiTimeoutSlider; Layout.fillWidth: true; from: 10; to: 300; stepSize: 10; value: appBackend.aiTimeout; onMoved: appBackend.aiTimeout = value }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 6
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_batch_label", "AI Batch Size") + ": " + Math.round(aiBatchSlider.value); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                    Slider { id: aiBatchSlider; Layout.fillWidth: true; from: 1; to: 50; stepSize: 1; value: appBackend.aiBatchSize; onMoved: appBackend.aiBatchSize = value }
                                }
                            }

                            // Satır 3: AI Retry Count & AI Concurrency
                            RowLayout {
                                Layout.fillWidth: true; spacing: 24
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 6
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_retry_label", "AI Retry Count") + ": " + Math.round(aiRetrySlider.value); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                    Slider { id: aiRetrySlider; Layout.fillWidth: true; from: 1; to: 5; stepSize: 1; value: appBackend.aiRetryCount; onMoved: appBackend.aiRetryCount = value }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 6
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_concurrency_label", "AI Concurrency") + ": " + Math.round(aiConcSlider.value); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                    Slider { id: aiConcSlider; Layout.fillWidth: true; from: 1; to: 10; stepSize: 1; value: appBackend.aiConcurrency; onMoved: appBackend.aiConcurrency = value }
                                }
                            }

                            // Satır 4: Custom System Prompt (Çok Satırlı TextArea)
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 6
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_prompt_label", "Custom System Prompt (Optional instructions for AI):"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                ScrollView {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 96
                                    clip: true
                                    ScrollBar.vertical: ScrollBar {}
                                    TextArea {
                                        id: aiPromptField
                                        text: appBackend.aiCustomSystemPrompt
                                        placeholderText: "Translate the following Ren'Py visual novel dialogue accurately while keeping tags..."
                                        wrapMode: TextEdit.Wrap
                                        onEditingFinished: appBackend.aiCustomSystemPrompt = text
                                        font.pixelSize: 12; color: clrTxt
                                        selectByMouse: true
                                        background: Rectangle {
                                            radius: 8
                                            color: clrInput
                                            border.color: aiPromptField.activeFocus ? clrAccent : clrCardBorder
                                            border.width: 1
                                            Behavior on border.color { ColorAnimation { duration: 150 } }

                                            // Focus Ring Glow
                                            Rectangle {
                                                anchors.fill: parent
                                                anchors.margins: -3
                                                radius: parent.radius + 2
                                                color: "transparent"
                                                border.color: clrAccent
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
                                Label {
                                    Layout.fillWidth: true
                                    visible: appBackend.hyMt2Active && appBackend.selectedEngine === "local_llm"
                                    wrapMode: Text.WordWrap
                                    font.pixelSize: 12
                                    color: clrWarn
                                    text: appBackend.uiTrigger, appBackend.getTextWithDefault(
                                        "ai_prompt_ignored_hy_mt2",
                                        "⚠️ Hy-MT models have no system prompt — this field is ignored while the Hy-MT profile is active. Set Model Profile to 'generic' to use it."
                                    )
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
                Rectangle {
                    id: logStickyHeader
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 104
                    z: 10
                    color: clrBg
                    border.color: clrCardBorder
                    border.width: 1

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 10

                        // Üst Satır: Başlık, Sayaç ve Eylemler
                        RowLayout {
                            Layout.fillWidth: true; spacing: 12
                            Rectangle {
                                width: 34; height: 34; radius: 8
                                color: Qt.rgba(0, 242, 254, 0.12)
                                border.color: Qt.rgba(0, 242, 254, 0.3); border.width: 1
                                Label { anchors.centerIn: parent; text: "⚡"; font.pixelSize: 18 }
                            }
                            ColumnLayout {
                                spacing: 1
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_logs", "Log Console & System Diagnostics"); font.pixelSize: 17; font.bold: true; color: clrTxt }
                                Label { text: appBackend.uiTrigger, logModel.count + " " + appBackend.getTextWithDefault("logs_count_label", "events recorded in session."); font.pixelSize: 11; color: clrTxt2 }
                            }
                            Item { Layout.fillWidth: true }

                            Button {
                                height: 34; text: appBackend.uiTrigger, "📋 " + appBackend.getTextWithDefault("copy_log", "Copy Log")
                                onClicked: {
                                    var lines = []
                                    for (var i = 0; i < logModel.count; i++) {
                                        var item = logModel.get(i)
                                        lines.push(item.ts + " [" + item.level.toUpperCase() + "] " + item.message)
                                    }
                                    appBackend.copyToClipboard(lines.join("\n"))
                                    showToast(appBackend.getTextWithDefault("log_copied_clipboard", "Log copied to clipboard!"), "info")
                                }
                                background: Rectangle { radius: 8; color: parent.hovered ? clrCardHover : clrInput; border.color: clrCardBorder; border.width: 1 }
                                contentItem: Label { text: parent.text; color: clrTxt; font.pixelSize: 11; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                            }
                            Button {
                                height: 34; text: appBackend.uiTrigger, "🗑 " + appBackend.getTextWithDefault("clear_log", "Clear")
                                onClicked: logModel.clear()
                                background: Rectangle { radius: 8; color: parent.hovered ? "#3B1111" : clrInput; border.color: clrCardBorder; border.width: 1 }
                                contentItem: Label { text: parent.text; color: clrError; font.pixelSize: 11; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                            }
                        }

                        // Alt Satır: Seviye Filtreleri (Segments) + Canlı Arama
                        RowLayout {
                            Layout.fillWidth: true; spacing: 12

                            // Segmented Level Filter Bar
                            Rectangle {
                                height: 32; radius: 8
                                color: clrCard; border.color: clrCardBorder; border.width: 1
                                Layout.preferredWidth: filterRow.implicitWidth + 8

                                RowLayout {
                                    id: filterRow
                                    anchors.centerIn: parent
                                    spacing: 4

                                    Repeater {
                                        model: [
                                            { label: "ALL", key: "ALL", color: clrTxt },
                                            { label: "INFO", key: "INFO", color: clrAccent },
                                            { label: "WARN", key: "WARNING", color: clrWarn },
                                            { label: "ERROR", key: "ERROR", color: clrError }
                                        ]
                                        delegate: Rectangle {
                                            width: 60; height: 26; radius: 6
                                            color: pageLogs.selectedLevel === modelData.key ? Qt.rgba(modelData.color.r, modelData.color.g, modelData.color.b, 0.18) : "transparent"
                                            border.color: pageLogs.selectedLevel === modelData.key ? modelData.color : "transparent"; border.width: 1
                                            Label {
                                                anchors.centerIn: parent
                                                text: modelData.label
                                                font.pixelSize: 10; font.bold: pageLogs.selectedLevel === modelData.key
                                                color: pageLogs.selectedLevel === modelData.key ? modelData.color : clrTxt2
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
                                color: clrInput; border.color: clrCardBorder; border.width: 1
                                RowLayout {
                                    anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 10; spacing: 6
                                    Label { text: "🔍"; font.pixelSize: 11; color: clrTxtDim }
                                    TextInput {
                                        id: logSearchInput
                                        Layout.fillWidth: true
                                        font.pixelSize: 11; color: clrTxt
                                        clip: true
                                        Text {
                                            anchors.fill: parent
                                            verticalAlignment: Text.AlignVCenter
                                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("logs_search_placeholder", "Loglarda filtrele veya anahtar kelime ara...")
                                            color: clrTxtDim; font.pixelSize: 11
                                            visible: !logSearchInput.text && !logSearchInput.activeFocus
                                        }
                                        onTextChanged: pageLogs.logSearchQuery = text.trim().toLowerCase()
                                    }
                                    Button {
                                        visible: logSearchInput.text.length > 0
                                        width: 18; height: 18; text: "✕"
                                        onClicked: { logSearchInput.text = ""; pageLogs.logSearchQuery = "" }
                                        background: Item {}
                                        contentItem: Label { text: "✕"; color: clrTxtDim; font.pixelSize: 10; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                    }
                                }
                            }
                        }
                    }
                }

                // Konsol Çıktı Terminali (Doğrudan ListView — Nested Scroll Yok!)
                Rectangle {
                    anchors.top: logStickyHeader.bottom
                    anchors.bottom: parent.bottom
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.margins: 14
                    radius: 12
                    color: Qt.darker(clrCard, 1.25)
                    border.color: clrCardBorder
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
                                    color: clrTxtDim; font.pixelSize: 11; font.family: "Consolas, 'Courier New', monospace"
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
        ScrollView {
            id: viewToolbox
            visible: navIndex === 3
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical: ScrollBar {}

            transform: Translate { id: animTrToolbox; y: 14 }
            opacity: 0.0
            ParallelAnimation {
                id: animEntranceToolbox
                NumberAnimation { target: animTrToolbox; property: "y"; from: 14; to: 0; duration: 220; easing.type: Easing.OutCubic }
                NumberAnimation { target: viewToolbox; property: "opacity"; from: 0.0; to: 1.0; duration: 180; easing.type: Easing.OutQuad }
            }
            onVisibleChanged: if (visible) animEntranceToolbox.restart()

            ColumnLayout {
                width: Math.min(parent.width - 48, 1180)
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 20
                anchors.topMargin: 24
                anchors.bottomMargin: 32

                // Başlık Alanı
                RowLayout {
                    Layout.fillWidth: true; spacing: 14
                    Rectangle {
                        width: 42; height: 42; radius: 10
                        color: Qt.rgba(0, 242, 254, 0.12)
                        border.color: Qt.rgba(0, 242, 254, 0.3); border.width: 1
                        Label { anchors.centerIn: parent; text: "🛠️"; font.pixelSize: 22 }
                    }
                    ColumnLayout {
                        spacing: 2
                        Label {
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("toolbox_title", "RenLocalizer Araç Kutusu (Toolbox)")
                            font.pixelSize: 20; font.bold: true; color: clrTxt
                        }
                        Label {
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("toolbox_subtitle", "Görsel roman çevirilerini kusursuzlaştırmak, font hatalarını çözmek ve sözlük oluşturmak için hayat kurtaran altın araçlar.")
                            font.pixelSize: 12; color: clrTxt2; wrapMode: Text.Wrap; Layout.fillWidth: true
                        }
                    }
                }

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
                        radius: 14; color: clrCard; border.color: clrCardBorder; border.width: 1

                        ColumnLayout {
                            id: fontCardCol
                            anchors.fill: parent; anchors.margins: 18; spacing: 14

                            RowLayout {
                                spacing: 12; Layout.fillWidth: true
                                Rectangle {
                                    width: 38; height: 38; radius: 8; color: Qt.rgba(0, 242, 254, 0.1)
                                    border.color: Qt.rgba(0, 242, 254, 0.3); border.width: 1
                                    Label { anchors.centerIn: parent; text: "🔤"; font.pixelSize: 18 }
                                }
                                ColumnLayout {
                                    spacing: 1; Layout.fillWidth: true
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_font_title", "Font Değiştirici ve Enjektör"); font.pixelSize: 15; font.bold: true; color: clrTxt }
                                    Label { text: "OpenType / TrueType Auto-Injector"; font.pixelSize: 11; color: clrTxtDim }
                                }
                                Rectangle {
                                    radius: 6; color: Qt.rgba(0, 242, 254, 0.12)
                                    Layout.preferredHeight: 20; Layout.preferredWidth: 54
                                    Label { anchors.centerIn: parent; text: "FONT"; font.pixelSize: 9; font.bold: true; color: clrAccent }
                                }
                            }

                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_font_desc", "Japonca/İngilizce oyun fontlarını Türkçe karakter destekli evrensel fontlarla otomatik değiştirerek kare kare yazı hatasını kökünden çözer.")
                                font.pixelSize: 12; color: clrTxt2; wrapMode: Text.Wrap; Layout.fillWidth: true
                            }

                            RowLayout {
                                Layout.fillWidth: true; spacing: 10
                                Button {
                                    Layout.fillWidth: true; height: 38
                                    text: appBackend.uiTrigger, "⚡ " + appBackend.getTextWithDefault("btn_run_font", "Kontrol Et")
                                    onClicked: appBackend.runToolFontHelper()
                                    background: Rectangle {
                                        radius: 8; color: parent.hovered ? clrCardHover : clrInput
                                        border.color: parent.hovered ? clrAccent : clrCardBorder; border.width: 1
                                    }
                                    contentItem: Label { text: parent.text; color: clrAccent; font.pixelSize: 12; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                }
                                Button {
                                    Layout.fillWidth: true; height: 38
                                    text: appBackend.uiTrigger, "📥 " + appBackend.getTextWithDefault("btn_font_inject", "Enjekte Et")
                                    onClicked: appBackend.runToolFontInject()
                                    background: Rectangle {
                                        radius: 8; color: parent.hovered ? clrCardHover : clrInput
                                        border.color: parent.hovered ? clrSuccess : clrCardBorder; border.width: 1
                                    }
                                    contentItem: Label { text: parent.text; color: clrSuccess; font.pixelSize: 12; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                }
                            }
                        }
                    }

                    // ── KART 2: REN'PY HATA DOKTORU (LINT) ──────────────────────
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: lintCardCol.implicitHeight + 36
                        radius: 14; color: clrCard; border.color: clrCardBorder; border.width: 1

                        ColumnLayout {
                            id: lintCardCol
                            anchors.fill: parent; anchors.margins: 18; spacing: 14

                            RowLayout {
                                spacing: 12; Layout.fillWidth: true
                                Rectangle {
                                    width: 38; height: 38; radius: 8; color: Qt.rgba(168, 85, 247, 0.1)
                                    border.color: Qt.rgba(168, 85, 247, 0.3); border.width: 1
                                    Label { anchors.centerIn: parent; text: "🩺"; font.pixelSize: 18 }
                                }
                                ColumnLayout {
                                    spacing: 1; Layout.fillWidth: true
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_lint_title", "Ren'Py Hata Doktoru"); font.pixelSize: 15; font.bold: true; color: clrTxt }
                                    Label { text: "Syntax & Indentation Guard"; font.pixelSize: 11; color: clrTxtDim }
                                }
                                Rectangle {
                                    radius: 6; color: Qt.rgba(168, 85, 247, 0.15)
                                    Layout.preferredHeight: 20; Layout.preferredWidth: 48
                                    Label { anchors.centerIn: parent; text: "LINT"; font.pixelSize: 9; font.bold: true; color: clrPurple }
                                }
                            }

                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_lint_desc", "Çeviri sonrasında bozulan satır girintularını, eksik tırnakları ve değişken etiketlerini tarayıp oyunun açılırken çökmesini önler.")
                                font.pixelSize: 12; color: clrTxt2; wrapMode: Text.Wrap; Layout.fillWidth: true
                            }

                            Button {
                                Layout.fillWidth: true; height: 38
                                text: appBackend.uiTrigger, "🩺 " + appBackend.getTextWithDefault("btn_run_lint", "Hata Taramasını Başlat")
                                onClicked: appBackend.runToolRenpyLint()
                                background: Rectangle {
                                    radius: 8; color: parent.hovered ? clrCardHover : clrInput
                                    border.color: parent.hovered ? clrPurple : clrCardBorder; border.width: 1
                                }
                                contentItem: Label { text: parent.text; color: clrPurple; font.pixelSize: 12; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                            }
                        }
                    }

                    // ── KART 3: TERİM SÖZLÜĞÜ ÇIKARICI (GLOSSARY) ───────────────
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: glossCardCol.implicitHeight + 36
                        radius: 14; color: clrCard; border.color: clrCardBorder; border.width: 1

                        ColumnLayout {
                            id: glossCardCol
                            anchors.fill: parent; anchors.margins: 18; spacing: 14

                            RowLayout {
                                spacing: 12; Layout.fillWidth: true
                                Rectangle {
                                    width: 38; height: 38; radius: 8; color: Qt.rgba(16, 185, 129, 0.1)
                                    border.color: Qt.rgba(16, 185, 129, 0.3); border.width: 1
                                    Label { anchors.centerIn: parent; text: "📚"; font.pixelSize: 18 }
                                }
                                ColumnLayout {
                                    spacing: 1; Layout.fillWidth: true
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_glossary_title", "Terim Sözlüğü Çıkarıcı"); font.pixelSize: 15; font.bold: true; color: clrTxt }
                                    Label { text: "Entity & Name Scanner"; font.pixelSize: 11; color: clrTxtDim }
                                }
                                Rectangle {
                                    radius: 6; color: Qt.rgba(16, 185, 129, 0.15)
                                    Layout.preferredHeight: 20; Layout.preferredWidth: 62
                                    Label { anchors.centerIn: parent; text: "GLOSSARY"; font.pixelSize: 9; font.bold: true; color: clrSuccess }
                                }
                            }

                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_glossary_desc", "Oyun içindeki özel isimleri, karakter adlarını ve krallık terimlerini tarayıp otomatik olarak glossary.json dosyasına aktararak tutarlılık sağlar.")
                                font.pixelSize: 12; color: clrTxt2; wrapMode: Text.Wrap; Layout.fillWidth: true
                            }

                            Button {
                                Layout.fillWidth: true; height: 38
                                text: appBackend.uiTrigger, "📚 " + appBackend.getTextWithDefault("btn_run_glossary", "Terim Sözlüğünü Çıkar")
                                onClicked: appBackend.runToolGlossaryExtractor()
                                background: Rectangle {
                                    radius: 8; color: parent.hovered ? clrCardHover : clrInput
                                    border.color: parent.hovered ? clrSuccess : clrCardBorder; border.width: 1
                                }
                                contentItem: Label { text: parent.text; color: clrSuccess; font.pixelSize: 12; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
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
                        radius: 14; color: clrCard; border.color: clrCardBorder; border.width: 1

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
                                    width: 38; height: 38; radius: 8; color: Qt.rgba(0, 242, 254, 0.1)
                                    border.color: Qt.rgba(0, 242, 254, 0.3); border.width: 1
                                    Label { anchors.centerIn: parent; text: "🏳️"; font.pixelSize: 18 }
                                }
                                ColumnLayout {
                                    spacing: 1; Layout.fillWidth: true
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_lang_activate_title", "Language Activation"); font.pixelSize: 15; font.bold: true; color: clrTxt }
                                    Label { text: "zzz_<lang>_language.rpy"; font.pixelSize: 11; color: clrTxtDim }
                                }
                                Rectangle {
                                    radius: 6; color: Qt.rgba(0, 242, 254, 0.15)
                                    Layout.preferredHeight: 20; Layout.preferredWidth: 48
                                    Label { anchors.centerIn: parent; text: "LANG"; font.pixelSize: 9; font.bold: true; color: clrAccent }
                                }
                            }

                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_lang_activate_desc", "Ren'Py does not list the languages in the tl/ folder by itself. Pick a translation below to make the game start in that language, or remove the activation to return to the original language.")
                                font.pixelSize: 12; color: clrTxt2; wrapMode: Text.Wrap; Layout.fillWidth: true
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
                                    background: Rectangle { radius: 8; color: clrInput; border.color: parent.hovered ? clrAccent : clrCardBorder; border.width: 1 }
                                    contentItem: Label {
                                        leftPadding: 14; rightPadding: 30
                                        text: langActCombo.displayText; elide: Text.ElideRight
                                        color: langActivateCard.tlLangs.length > 0 ? clrTxt : clrTxtDim
                                        font.pixelSize: 12; verticalAlignment: Text.AlignVCenter
                                    }
                                    delegate: ItemDelegate {
                                        width: langActCombo.width
                                        contentItem: Label { text: modelData; color: clrTxt; font.pixelSize: 12; leftPadding: 14; elide: Text.ElideRight }
                                        background: Rectangle { color: hovered ? Qt.rgba(0, 242, 254, 0.12) : "transparent" }
                                    }
                                    popup: Popup {
                                        y: langActCombo.height; width: langActCombo.width
                                        implicitHeight: Math.min(contentItem.implicitHeight, 220); padding: 4
                                        contentItem: ListView { clip: true; implicitHeight: contentHeight; model: langActCombo.delegateModel; ScrollBar.vertical: ScrollBar {} }
                                        background: Rectangle { color: clrCard; radius: 8; border.color: clrCardBorder; border.width: 1 }
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
                                        radius: 8; color: btnRefreshTlLangs.hovered ? clrCardHover : clrInput
                                        border.color: btnRefreshTlLangs.hovered ? clrAccent : clrCardBorder; border.width: 1
                                    }
                                    contentItem: Label {
                                        text: "⟳"; color: btnRefreshTlLangs.hovered ? clrAccent : clrTxt2
                                        font.pixelSize: 17; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                                    }
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true; spacing: 8
                                Button {
                                    Layout.fillWidth: true; height: 38
                                    enabled: langActivateCard.tlLangs.length > 0
                                    text: appBackend.uiTrigger, "🏳️ " + appBackend.getTextWithDefault("btn_activate_language", "Start game in this language")
                                    onClicked: appBackend.runToolActivateLanguage(langActCombo.currentText)
                                    background: Rectangle {
                                        radius: 8; color: parent.hovered ? clrCardHover : clrInput
                                        border.color: parent.hovered ? clrAccent : clrCardBorder; border.width: 1
                                    }
                                    contentItem: Label { text: parent.text; color: clrAccent; font.pixelSize: 12; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                                }
                                Button {
                                    Layout.fillWidth: true; height: 38
                                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("btn_remove_language_activation", "Remove activation")
                                    onClicked: appBackend.runToolRemoveLanguageActivation()
                                    background: Rectangle {
                                        radius: 8; color: parent.hovered ? clrCardHover : clrInput
                                        border.color: parent.hovered ? clrError : clrCardBorder; border.width: 1
                                    }
                                    contentItem: Label { text: parent.text; color: clrTxt2; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                                }
                            }
                        }
                    }

                    // ── KART 4: RPA & ARŞİV KORUMA DOKTORU ─────────────────────
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: rpaCardCol.implicitHeight + 36
                        radius: 14; color: clrCard; border.color: clrCardBorder; border.width: 1

                        ColumnLayout {
                            id: rpaCardCol
                            anchors.fill: parent; anchors.margins: 18; spacing: 14

                            RowLayout {
                                spacing: 12; Layout.fillWidth: true
                                Rectangle {
                                    width: 38; height: 38; radius: 8; color: Qt.rgba(245, 158, 11, 0.1)
                                    border.color: Qt.rgba(245, 158, 11, 0.3); border.width: 1
                                    Label { anchors.centerIn: parent; text: "📦"; font.pixelSize: 18 }
                                }
                                ColumnLayout {
                                    spacing: 1; Layout.fillWidth: true
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_unrpa_title", "Arşiv & AST Çözücü"); font.pixelSize: 15; font.bold: true; color: clrTxt }
                                    Label { text: "Unrpa & AST Decompile Engine"; font.pixelSize: 11; color: clrTxtDim }
                                }
                                Rectangle {
                                    radius: 6; color: Qt.rgba(245, 158, 11, 0.15)
                                    Layout.preferredHeight: 20; Layout.preferredWidth: 60
                                    Label { anchors.centerIn: parent; text: "PIPELINE"; font.pixelSize: 9; font.bold: true; color: clrWarn }
                                }
                            }

                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_unrpa_desc", "Oyun dizinindeki .rpa arşivlerini otomatik açar ve .rpyc ikili dosyalarını çözümler. Pipeline tarafından arka planda otomatik yönetilir.")
                                font.pixelSize: 12; color: clrTxt2; wrapMode: Text.Wrap; Layout.fillWidth: true
                            }

                            Rectangle {
                                Layout.fillWidth: true; height: 38; radius: 8
                                color: Qt.rgba(245, 158, 11, 0.08)
                                border.color: Qt.rgba(245, 158, 11, 0.2); border.width: 1
                                Label {
                                    anchors.centerIn: parent
                                    text: appBackend.uiTrigger, "✓ " + appBackend.getTextWithDefault("tool_unrpa_status", "Çeviri başlatıldığında otomatik devreye girer")
                                    color: clrWarn; font.pixelSize: 11; font.bold: true
                                }
                            }
                        }
                    }
                }

                Item { height: 24 }
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
            Rectangle {
                id: glossaryStickyHeader
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                height: 114
                z: 10
                color: clrBg
                border.color: clrCardBorder
                border.width: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 10

                    // Üst Satır: Başlık & Rozet & Sayaç & Aksiyonlar
                    RowLayout {
                        Layout.fillWidth: true; spacing: 12
                        Rectangle {
                            width: 36; height: 36; radius: 8
                            color: Qt.rgba(16, 185, 129, 0.12)
                            border.color: Qt.rgba(16, 185, 129, 0.3); border.width: 1
                            Label { anchors.centerIn: parent; text: "📚"; font.pixelSize: 18 }
                        }
                        ColumnLayout {
                            spacing: 1
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_title", "Term Glossary")
                                font.pixelSize: 17; font.bold: true; color: clrTxt
                            }
                            Label {
                                text: appBackend.uiTrigger, (pageGlossary.filteredGlossaryModel().length) + " / " + (appBackend.glossaryList ? appBackend.glossaryList.length : 0) + " " + appBackend.getTextWithDefault("glossary_count", "terms loaded.")
                                font.pixelSize: 11; color: clrTxt2
                            }
                        }
                        Item { Layout.fillWidth: true }

                        // Eylemler
                        Button {
                            height: 34; text: appBackend.uiTrigger, "➕ " + appBackend.getTextWithDefault("glossary_btn_add", "Add Term")
                            onClicked: { addGlossarySource.text = ""; addGlossaryTarget.text = ""; addGlossaryDialog.open() }
                            background: Rectangle { radius: 8; color: parent.hovered ? clrCardHover : clrInput; border.color: clrAccent; border.width: 1 }
                            contentItem: Label { text: parent.text; color: clrAccent; font.pixelSize: 11; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        }
                        Button {
                            height: 34; text: appBackend.uiTrigger, "📥 " + appBackend.getTextWithDefault("glossary_btn_import", "Import")
                            onClicked: importGlossaryDialog.open()
                            background: Rectangle { radius: 8; color: parent.hovered ? clrCardHover : clrInput; border.color: clrCardBorder; border.width: 1 }
                            contentItem: Label { text: parent.text; color: clrTxt; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        }
                        Button {
                            height: 34; text: appBackend.uiTrigger, "📤 " + appBackend.getTextWithDefault("glossary_btn_export", "Export")
                            onClicked: exportGlossaryDialog.open()
                            background: Rectangle { radius: 8; color: parent.hovered ? clrCardHover : clrInput; border.color: clrCardBorder; border.width: 1 }
                            contentItem: Label { text: parent.text; color: clrTxt; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        }
                        Button {
                            height: 34; text: appBackend.uiTrigger, "📋 " + appBackend.getTextWithDefault("glossary_btn_fill", "Fill Source")
                            onClicked: appBackend.fillEmptyGlossaryWithSource()
                            background: Rectangle { radius: 8; color: parent.hovered ? clrCardHover : clrInput; border.color: clrCardBorder; border.width: 1 }
                            contentItem: Label { text: parent.text; color: clrTxt; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        }
                        Button {
                            height: 34; text: appBackend.uiTrigger, "🌐 " + appBackend.getTextWithDefault("glossary_btn_translate", "Translate Empty")
                            onClicked: appBackend.translateEmptyGlossary()
                            background: Rectangle { radius: 8; color: parent.hovered ? clrCardHover : clrInput; border.color: clrPurple; border.width: 1 }
                            contentItem: Label { text: parent.text; color: clrPurple; font.pixelSize: 11; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        }
                    }

                    // Alt Satır: Arama Çubuğu
                    RowLayout {
                        Layout.fillWidth: true; spacing: 10
                        Rectangle {
                            Layout.fillWidth: true; height: 32; radius: 8; color: clrInput; border.color: clrCardBorder; border.width: 1
                            RowLayout {
                                anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 10; spacing: 8
                                Label { text: "🔍"; font.pixelSize: 12; color: clrTxtDim }
                                TextInput {
                                    id: glossarySearchInput
                                    Layout.fillWidth: true
                                    font.pixelSize: 12; color: clrTxt
                                    clip: true
                                    Text {
                                        anchors.fill: parent
                                        verticalAlignment: Text.AlignVCenter
                                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_search_placeholder", "Sözlükte terim veya çeviri ara...")
                                        color: clrTxtDim; font.pixelSize: 12
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
                                    contentItem: Label { text: "✕"; color: clrTxtDim; font.pixelSize: 10; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                }
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
                    anchors.topMargin: 16
                    anchors.bottomMargin: 32
                    spacing: 10

                    // Tablo Başlığı
                    RowLayout {
                        Layout.fillWidth: true; spacing: 12
                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_col_source", "Source (Original)"); font.pixelSize: 12; font.bold: true; color: clrTxt2; Layout.fillWidth: true; Layout.preferredWidth: 320 }
                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_col_target", "Target (Translation)"); font.pixelSize: 12; font.bold: true; color: clrTxt2; Layout.fillWidth: true }
                        Item { Layout.preferredWidth: 40 }
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: clrCardBorder }

                    // Boş Durum (Empty State) Kartı
                    Rectangle {
                        visible: pageGlossary.filteredGlossaryModel().length === 0
                        Layout.fillWidth: true; Layout.preferredHeight: 180
                        radius: 14; color: clrCard; border.color: clrCardBorder; border.width: 1
                        ColumnLayout {
                            anchors.centerIn: parent; spacing: 10
                            Label { text: "📖"; font.pixelSize: 36; Layout.alignment: Qt.AlignHCenter }
                            Label {
                                text: appBackend.uiTrigger, pageGlossary.searchQuery.length > 0
                                    ? appBackend.getTextWithDefault("glossary_no_search_results", "Aramanızla eşleşen terim bulunamadı.")
                                    : appBackend.getTextWithDefault("glossary_empty_state", "Henüz terim eklenmedi. '➕ Terim Ekle' veya '📥 İçe Aktar' ile başlayın.")
                                font.pixelSize: 13; color: clrTxt2; font.bold: true; Layout.alignment: Qt.AlignHCenter
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
                                color: clrInput; border.color: clrCardBorder; border.width: 1
                                Label {
                                    anchors.fill: parent; anchors.margins: 12
                                    text: modelData.source; color: clrTxt; font.pixelSize: 12
                                    elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter
                                }
                            }
                            Rectangle {
                                Layout.fillWidth: true; height: 42; radius: 8
                                color: clrInput; border.color: modelData.target ? clrCardBorder : Qt.rgba(239, 68, 68, 0.35); border.width: 1
                                Label {
                                    anchors.fill: parent; anchors.margins: 12
                                    text: modelData.target || appBackend.getTextWithDefault("glossary_empty", "(empty)"); color: modelData.target ? clrTxt : clrError
                                    font.pixelSize: 12; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter
                                }
                            }
                            Button {
                                Layout.preferredWidth: 36; height: 36
                                text: "✕"
                                onClicked: appBackend.removeGlossaryItem(modelData.source)
                                background: Rectangle { radius: 8; color: parent.hovered ? "#3B1111" : "transparent"; border.color: "transparent" }
                                contentItem: Label { text: "✕"; color: clrError; font.pixelSize: 14; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
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
            ui: root
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
        clrSuccess: root.clrSuccess
        clrError: root.clrError
        clrWarn: root.clrWarn
        clrAccent: root.clrAccent
        clrTxt: root.clrTxt
    }

    // ── Uyarı ve Tamamlanma Popup Diyalogları ─────────────────────────────
    WarningDialog {
        id: warningDialog
        clrCard: root.clrCard
        clrWarn: root.clrWarn
        clrWarnDim: root.clrWarnDim
        clrTxt: root.clrTxt
        clrTxtDim: root.clrTxtDim
        clrInput: root.clrInput
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
            color: Qt.rgba(0, 0, 0, 0.65)
        }

        background: Rectangle {
            color: clrCard
            radius: 18
            border.color: Qt.rgba(0, 242, 254, 0.45)
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
                    GradientStop { position: 0.0; color: clrAccent }
                    GradientStop { position: 1.0; color: clrAccent2 }
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
                    color: clrSuccessDim
                    border.color: clrSuccess; border.width: 1.5

                    Label {
                        anchors.centerIn: parent
                        text: "🎉"
                        font.pixelSize: 22
                    }
                }

                ColumnLayout {
                    spacing: 3
                    Layout.fillWidth: true

                    Label {
                        text: appBackend.uiTrigger, cleanModalTitle(appBackend.getTextWithDefault("completion_summary_title", "Çeviri ve Derleme Tamamlandı"))
                        font.pixelSize: 17; font.bold: true; color: clrTxt
                    }
                    Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("completion_summary_subtitle", "Oyun yerelleştirme dosyaları başarıyla üretildi.")
                        font.pixelSize: 12; color: clrTxt2
                    }
                }

                // Sağ üst kapatma '✕' butonu
                Rectangle {
                    width: 32; height: 32; radius: 16
                    color: closeCompletionMa.containsMouse ? Qt.rgba(255, 255, 255, 0.12) : "transparent"
                    scale: closeCompletionMa.pressed ? 0.92 : (closeCompletionMa.containsMouse ? 1.08 : 1.0)
                    Behavior on scale { NumberAnimation { duration: 120 } }
                    Behavior on color { ColorAnimation { duration: 120 } }

                    Label {
                        anchors.centerIn: parent
                        text: "✕"
                        color: closeCompletionMa.containsMouse ? "#FFFFFF" : clrTxtDim
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
                color: clrInput
                border.color: Qt.rgba(255, 255, 255, 0.08)
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
                            color: Qt.rgba(0, 242, 254, 0.12)
                            Layout.alignment: Qt.AlignTop
                            Label {
                                anchors.centerIn: parent
                                text: "📊"
                                font.pixelSize: 13
                            }
                        }

                        Label {
                            text: completionDialog.summaryText
                            color: clrTxt
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
                        color: "#080B12"
                        border.color: Qt.rgba(255, 255, 255, 0.06)
                        border.width: 1
                        visible: completionDialog.outputPath.length > 0

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            spacing: 8

                            Label {
                                text: "📁"
                                font.pixelSize: 13
                            }
                            Label {
                                text: completionDialog.outputPath
                                color: clrTxtDim
                                font.pixelSize: 11
                                font.family: "Consolas"
                                elide: Text.ElideMiddle
                                Layout.fillWidth: true
                            }
                        }
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
                        color: openFolderBtn.down ? Qt.rgba(0, 242, 254, 0.18) : (openFolderBtn.hovered ? Qt.rgba(0, 242, 254, 0.10) : clrInput)
                        border.color: openFolderBtn.hovered ? clrAccent : Qt.rgba(255, 255, 255, 0.12)
                        border.width: 1
                        Behavior on color { ColorAnimation { duration: 140 } }
                        Behavior on border.color { ColorAnimation { duration: 140 } }
                    }
                    contentItem: RowLayout {
                        spacing: 8
                        Item { Layout.fillWidth: true }
                        Label { text: "📂"; font.pixelSize: 14 }
                        Label {
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("open_output_folder", "Çıktı Klasörünü Aç")
                            color: openFolderBtn.hovered ? clrAccent : clrTxt
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
                        color: completionOkBtn.hovered ? "#38BDF8" : "#00F2FE"
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: completionOkBtn.hovered ? "#38BDF8" : "#00F2FE" }
                            GradientStop { position: 1.0; color: completionOkBtn.hovered ? "#00F2FE" : "#4FACFE" }
                        }
                        Behavior on color { ColorAnimation { duration: 140 } }
                    }
                    contentItem: Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("dialog_ok", "Tamam")
                        color: "#080C14"
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
            color: Qt.rgba(0, 0, 0, 0.65)
        }

        background: Rectangle {
            color: clrCard
            radius: 18
            border.color: Qt.rgba(0, 242, 254, 0.45)
            border.width: 1.5
            clip: true

            Rectangle {
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                height: 3
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: clrAccent }
                    GradientStop { position: 1.0; color: clrAccent2 }
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
                    color: Qt.rgba(0, 242, 254, 0.15)
                    border.color: clrAccent; border.width: 1.5

                    Label {
                        anchors.centerIn: parent
                        text: "🚀"
                        font.pixelSize: 20
                    }
                }

                ColumnLayout {
                    spacing: 2
                    Layout.fillWidth: true

                    Label {
                        text: appBackend.uiTrigger, cleanModalTitle(appBackend.getTextWithDefault("update_available_title", "Yeni Sürüm Mevcut"))
                        font.pixelSize: 17; font.bold: true; color: clrTxt
                    }
                    Label {
                        text: updateDialog.latestVersion.length > 0 ? ("v" + updateDialog.latestVersion) : ""
                        font.pixelSize: 12; color: clrAccent; font.bold: true
                        visible: updateDialog.latestVersion.length > 0
                    }
                }

                Rectangle {
                    width: 30; height: 30; radius: 15
                    color: closeUpdateMa.containsMouse ? Qt.rgba(255, 255, 255, 0.12) : "transparent"
                    scale: closeUpdateMa.pressed ? 0.92 : (closeUpdateMa.containsMouse ? 1.08 : 1.0)
                    Behavior on scale { NumberAnimation { duration: 120 } }
                    Behavior on color { ColorAnimation { duration: 120 } }

                    Label {
                        anchors.centerIn: parent
                        text: "✕"
                        color: closeUpdateMa.containsMouse ? "#FFFFFF" : clrTxtDim
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
                color: clrInput
                border.color: Qt.rgba(255, 255, 255, 0.08)
                border.width: 1

                ColumnLayout {
                    id: updateBodyCol
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 6

                    Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("update_available_msg", "RenLocalizer'ın yeni bir sürümü yayınlandı.")
                        color: clrTxt
                        font.pixelSize: 13
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("update_available_click", "Güncellemeyi indirmek için İndir butonuna tıklayın.")
                        color: clrTxt2
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
                        color: parent.down ? Qt.rgba(255, 255, 255, 0.08) : (parent.hovered ? Qt.rgba(255, 255, 255, 0.05) : "transparent")
                        border.color: parent.hovered ? clrTxt2 : clrCardBorder
                        border.width: 1
                        Behavior on border.color { ColorAnimation { duration: 140 } }
                    }
                    contentItem: Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_restart_later", "Daha Sonra")
                        color: clrTxt2
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
                        color: updateDownloadBtn.hovered ? "#38BDF8" : clrAccent
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: updateDownloadBtn.hovered ? "#38BDF8" : "#00F2FE" }
                            GradientStop { position: 1.0; color: updateDownloadBtn.hovered ? "#00F2FE" : "#4FACFE" }
                        }
                        Behavior on color { ColorAnimation { duration: 140 } }
                    }
                    contentItem: Label {
                        text: appBackend.uiTrigger, "⬇ " + appBackend.getTextWithDefault("update_download_btn", "İndir")
                        color: "#080C14"
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
            color: Qt.rgba(0, 0, 0, 0.65)
        }

        background: Rectangle {
            color: clrCard
            radius: 18
            border.color: Qt.rgba(239, 68, 68, 0.45)
            border.width: 1.5
            clip: true

            Rectangle {
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                height: 3
                color: clrError
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
                    color: Qt.rgba(239, 68, 68, 0.15)
                    border.color: clrError; border.width: 1.5

                    Label {
                        anchors.centerIn: parent
                        text: "⚠️"
                        font.pixelSize: 20
                    }
                }

                ColumnLayout {
                    spacing: 2
                    Layout.fillWidth: true

                    Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_title", "Fabrika Ayarlarına Sıfırla")
                        font.pixelSize: 17; font.bold: true; color: clrTxt
                    }
                    Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_subtitle", "Kalıcı Sıfırlama İşlemi")
                        font.pixelSize: 12; color: clrError
                    }
                }

                Rectangle {
                    width: 30; height: 30; radius: 15
                    color: closeResetMa.containsMouse ? Qt.rgba(255, 255, 255, 0.12) : "transparent"
                    scale: closeResetMa.pressed ? 0.92 : (closeResetMa.containsMouse ? 1.08 : 1.0)
                    Behavior on scale { NumberAnimation { duration: 120 } }
                    Behavior on color { ColorAnimation { duration: 120 } }

                    Label {
                        anchors.centerIn: parent
                        text: "✕"
                        color: closeResetMa.containsMouse ? "#FFFFFF" : clrTxtDim
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
                color: clrInput
                border.color: Qt.rgba(255, 255, 255, 0.08)
                border.width: 1

                Label {
                    id: resetBodyLbl
                    anchors.fill: parent
                    anchors.margins: 14
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_confirm", "Tüm ayarlar, API anahtarları, sözlük ve çeviri önbellekleri kalıcı olarak silinecek ve program ilk kurulduğu haline dönecek.\n\nEmin misiniz?")
                    color: clrTxt
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
                        color: parent.down ? Qt.rgba(255, 255, 255, 0.08) : (parent.hovered ? Qt.rgba(255, 255, 255, 0.05) : "transparent")
                        border.color: parent.hovered ? clrTxt2 : clrCardBorder
                        border.width: 1
                        Behavior on border.color { ColorAnimation { duration: 140 } }
                    }
                    contentItem: Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("dialog_cancel", "İptal")
                        color: clrTxt2
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
                        color: parent.hovered ? "#DC2626" : clrError
                        Behavior on color { ColorAnimation { duration: 140 } }
                    }
                    contentItem: Label {
                        text: appBackend.uiTrigger, "🗑 " + appBackend.getTextWithDefault("factory_reset_btn", "Evet, Sıfırla")
                        color: "#FFFFFF"
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
            color: Qt.rgba(0, 0, 0, 0.65)
        }

        background: Rectangle {
            color: clrCard
            radius: 18
            border.color: Qt.rgba(16, 185, 129, 0.45)
            border.width: 1.5
            clip: true

            Rectangle {
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                height: 3
                color: clrSuccess
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
                    color: clrSuccessDim
                    border.color: clrSuccess; border.width: 1.5

                    Label {
                        anchors.centerIn: parent
                        text: "✅"
                        font.pixelSize: 20
                    }
                }

                ColumnLayout {
                    spacing: 2
                    Layout.fillWidth: true

                    Label {
                        text: appBackend.uiTrigger, cleanModalTitle(appBackend.getTextWithDefault("factory_reset_done_title", "Sıfırlama Tamamlandı"))
                        font.pixelSize: 17; font.bold: true; color: clrTxt
                    }
                    Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_done_sub", "Ayarlar varsayılan duruma getirildi")
                        font.pixelSize: 12; color: clrTxt2
                    }
                }

                Rectangle {
                    width: 30; height: 30; radius: 15
                    color: closeResetDoneMa.containsMouse ? Qt.rgba(255, 255, 255, 0.12) : "transparent"
                    scale: closeResetDoneMa.pressed ? 0.92 : (closeResetDoneMa.containsMouse ? 1.08 : 1.0)
                    Behavior on scale { NumberAnimation { duration: 120 } }
                    Behavior on color { ColorAnimation { duration: 120 } }

                    Label {
                        anchors.centerIn: parent
                        text: "✕"
                        color: closeResetDoneMa.containsMouse ? "#FFFFFF" : clrTxtDim
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
                color: clrInput
                border.color: Qt.rgba(255, 255, 255, 0.08)
                border.width: 1

                Label {
                    id: resetDoneBodyLbl
                    anchors.fill: parent
                    anchors.margins: 14
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_done_msg", "Program ilk kurulduğu haline döndü. Temiz bir başlangıç için uygulamayı yeniden başlatın; bundan sonra yaptığınız ayarlar otomatik kaydedilecektir.")
                    color: clrTxt
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
                        color: parent.down ? Qt.rgba(255, 255, 255, 0.08) : (parent.hovered ? Qt.rgba(255, 255, 255, 0.05) : "transparent")
                        border.color: parent.hovered ? clrTxt2 : clrCardBorder
                        border.width: 1
                        Behavior on border.color { ColorAnimation { duration: 140 } }
                    }
                    contentItem: Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_restart_later", "Daha Sonra")
                        color: clrTxt2
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
                        color: factoryRestartBtn.hovered ? "#38BDF8" : clrAccent
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: factoryRestartBtn.hovered ? "#38BDF8" : "#00F2FE" }
                            GradientStop { position: 1.0; color: factoryRestartBtn.hovered ? "#00F2FE" : "#4FACFE" }
                        }
                        Behavior on color { ColorAnimation { duration: 140 } }
                    }
                    contentItem: Label {
                        text: appBackend.uiTrigger, "🔁 " + appBackend.getTextWithDefault("factory_restart_now", "Şimdi Yeniden Başlat")
                        color: "#080C14"
                        font.bold: true
                        font.pixelSize: 13
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
        }
    }

    // ── Glossary Dialogs ─────────────────────────────────────────────────
    GlossaryAddDialog {
        id: addGlossaryDialog
        clrCard: root.clrCard
        clrAccent: root.clrAccent
        clrAccent2: root.clrAccent2
        clrTxt: root.clrTxt
        clrTxt2: root.clrTxt2
        clrTxtDim: root.clrTxtDim
        clrInput: root.clrInput
        clrCardBorder: root.clrCardBorder
    }

    FileDialog {
        id: importGlossaryDialog
        title: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_dlg_import", "📥 Import Glossary")
        nameFilters: ["Glossary Files (*.json *.csv *.xlsx)", "All Files (*)"]
        onAccepted: {
            var path = appBackend.urlToPath(selectedFile.toString())
            appBackend.importGlossary(path)
        }
    }

    FileDialog {
        id: exportGlossaryDialog
        title: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_dlg_export", "📤 Export Glossary")
        fileMode: FileDialog.SaveFile
        nameFilters: ["JSON (*.json)", "CSV (*.csv)", "Excel (*.xlsx)"]
        onAccepted: {
            var path = appBackend.urlToPath(selectedFile.toString())
            appBackend.exportGlossary(path)
        }
    }
}
