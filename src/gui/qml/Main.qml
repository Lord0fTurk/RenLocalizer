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
import "pages"
import "dialogs"

ApplicationWindow {
    id: root
    title: appBackend.uiTrigger, appBackend.getTextWithDefault("app_title", "RenLocalizer") + " (" + appBackend.version + ")"

    // Responsive ve ferah başlangıç boyutları
    width: Math.min(1320, Screen.desktopAvailableWidth * 0.86)
    height: Math.min(860, Screen.desktopAvailableHeight * 0.86)
    minimumWidth: 980
    minimumHeight: 650
    visible: false // show() Python tarafından çağrılır

    Material.theme: Theme.themeMode === "daylight" ? Material.Light : Material.Dark
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
            pageDashboard.projectPathField.text = last
        appBackend.refreshProjectInfo()

        if (pageDashboard.targetLangCombo && pageDashboard.targetLangCombo.syncTargetLanguage) pageDashboard.targetLangCombo.syncTargetLanguage()
        if (pageDashboard.sourceLangCombo && pageDashboard.sourceLangCombo.syncSourceLanguage) pageDashboard.sourceLangCombo.syncSourceLanguage()
        if (pageSettings.uiLanguageCombo && pageSettings.uiLanguageCombo.syncUILanguage) pageSettings.uiLanguageCombo.syncUILanguage()

        Theme.themeMode = appBackend.getCurrentThemeMode()
        Theme.accentPreset = appBackend.getCurrentAccentPreset()

        appBackend.checkForUpdates(false)
    }

    // ── Backend Sinyalleri ────────────────────────────────────────────────
    Connections {
        target: appBackend

        function onThemeModeChanged(mode) {
            Theme.themeMode = mode
        }

        function onAccentPresetChanged(preset) {
            Theme.accentPreset = preset
        }

        function onLogMessage(level, message) {
            appendLog(level, message)
            if (message.indexOf("❌") >= 0 && (message.indexOf("select a game") >= 0 || message.indexOf("not found") >= 0 || message.indexOf("game folder") >= 0 || message.indexOf("oyun") >= 0))
                pageDashboard.projectPathField.triggerShake()
            // Show toast for toolbox operations and key events
            if (message.indexOf("✅") === 0 && (message.indexOf("Font") >= 0 || message.indexOf("Lint") >= 0 || message.indexOf("terms") >= 0 || message.indexOf("imported") >= 0 || message.indexOf("exported") >= 0 || message.indexOf("filled") >= 0 || message.indexOf("translated") >= 0))
                showToast(message.replace("✅ ", ""), "success")
            else if (message.indexOf("⚠️") === 0 && (message.indexOf("failed") >= 0 || message.indexOf("not found") >= 0))
                showToast(message.replace("⚠️ ", ""), "warning")
            else if (message.indexOf("🔤") === 0 || message.indexOf("🩺") === 0 || message.indexOf("📚") === 0)
                showToast(message, "info")
        }

        function onProgressChanged(current, total, text) {
            if (total > 0) pageDashboard.progressBar.value = current / total
            pageDashboard.progressLabel.text = text + " (" + current + "/" + total + ")"
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
                pageDashboard.progressBar.value = stageProgress[stage] / 100
        }

        function onTranslationStarted() {
            isTranslating = true
            statsVisible = false
            pageDashboard.progressBar.value = 0
            pageDashboard.progressLabel.text = ""
            currentStage = "starting"
            navIndex = 0 // Akışı anlık izlemek için Dashboard sekmene geç
        }

        function onTranslationFinished(success, message) {
            isTranslating = false
            if (success) {
                currentStage = "completed"
                pageDashboard.progressBar.value = 1.0
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
        pageDashboard.logListView.positionViewAtEnd()
        pageLogs.logConsoleListView.positionViewAtEnd()
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
        width: Math.min(420, root.width - 48)
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
            pageDashboard.projectPathField.text = appBackend.urlToPath(raw)
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
            pageDashboard.projectPathField.text = appBackend.urlToPath(raw)
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // ANA LAYOUT (Sol Sidebar Navigation + Sağ İçerik Paneli)
    // ═══════════════════════════════════════════════════════════════════════
    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ── 1. SOL KENAR ÇUBUĞU (SIDEBAR NAVIGATION - 230px) ──────────────
        Sidebar { id: sidebarPane }

        // ── 2. SAĞ SAYFA İÇERİK ALANI (CARD-BASED GLASS DASHBOARD) ────────
        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: navIndex

            // ═════════════════════════════════════════════════════════════
            // SEKME 0: DASHBOARD (Örnek Görseldeki Pro Kart Düzeni)
            // ═════════════════════════════════════════════════════════════
            DashboardPage { id: pageDashboard }

            // ═════════════════════════════════════════════════════════════
            // SEKME 1: SETTINGS (TAM SAYFA GELİŞMİŞ AYARLAR)
            // ═════════════════════════════════════════════════════════════
            SettingsPage { id: pageSettings }

            // ═════════════════════════════════════════════════════════════
            // SEKME 2: LOG CONSOLE & STUDIO TERMINAL
            // ═════════════════════════════════════════════════════════════
            LogPage { id: pageLogs }

        // ═════════════════════════════════════════════════════════════
        // SEKME 3: TOOLBOX (GELİŞMİŞ REN'PY ARAÇ KUTUSU)
        // ═════════════════════════════════════════════════════════════
        ToolboxPage { id: pageToolbox }

        // ═════════════════════════════════════════════════════════════
        // SEKME 4: GLOSSARY — TERİM SÖZLÜĞÜ YÖNETİMİ
        // ═════════════════════════════════════════════════════════════
        // ═════════════════════════════════════════════════════════════
        // SEKME 4: GLOSSARY — TERİM SÖZLÜĞÜ YÖNETİMİ
        // ═════════════════════════════════════════════════════════════
        GlossaryPage { id: pageGlossary }

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

    CompletionDialog { id: completionDialog }

    UpdateDialog { id: updateDialog }

    FactoryResetDialog { id: factoryResetDialog }

    FactoryResetDoneDialog { id: factoryResetDoneDialog }

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
            appBackend.glossary.importGlossary(path)
        }
    }

    FileDialog {
        id: exportGlossaryDialog
        title: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_dlg_export", "Export Glossary")
        fileMode: FileDialog.SaveFile
        nameFilters: ["JSON (*.json)", "CSV (*.csv)", "Excel (*.xlsx)"]
        onAccepted: {
            var path = appBackend.urlToPath(selectedFile.toString())
            appBackend.glossary.exportGlossary(path)
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
            pageDashboard.projectPathField.text = appBackend.urlToPath(raw)
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
