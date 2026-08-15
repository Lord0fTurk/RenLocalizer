// Main.qml — RenLocalizer v2.8.11 (Pro Card-based Dashboard UI Overhaul)
// Yeniden tasarlandı: Sol Kenar Çubuğu (Sidebar Navigation), Glass/Carbon Kartlar,
// Mikro-animasyonlar, Tam Sayfa Ayarlar ve Konsol Sekmeleri, Evrensel ComboBox Bugfix.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs
import QtQuick.Window

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
    readonly property color clrSuccessDim: Qt.rgba(16, 185, 129, 0.15)
    readonly property color clrWarn:       "#F59E0B" // Amber uyarı
    readonly property color clrWarnDim:    Qt.rgba(245, 158, 11, 0.15)
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
    readonly property color accentClr: clrAccent
    readonly property color successClr:clrSuccess
    readonly property color warningClr:clrWarn
    readonly property color errorClr:  clrError

    // ── State & Navigasyon ────────────────────────────────────────────────
    property int    navIndex:        0 // 0: Dashboard, 1: Settings, 2: Logs, 3: Toolbox
    property bool   isTranslating:   false
    property string currentStage:    "idle"
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

        var currentLang = appBackend.getTargetLanguage()
        var idx = targetLangCombo.indexOfValue(currentLang)
        if (idx >= 0) targetLangCombo.currentIndex = idx

        appBackend.checkForUpdates(false)
    }

    // ── Backend Sinyalleri ────────────────────────────────────────────────
    Connections {
        target: appBackend

        function onLogMessage(level, message) {
            appendLog(level, message)
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
            stageLabel.text = displayName
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
            progressBar.value = 0
            progressLabel.text = ""
            stageLabel.text = appBackend.getTextWithDefault("starting_translation", "Başlatılıyor...")
            navIndex = 0 // Akışı anlık izlemek için Dashboard sekmene geç
        }

        function onTranslationFinished(success, message) {
            isTranslating = false
            if (success) {
                stageLabel.text = appBackend.getTextWithDefault("stage_completed", "Tamamlandı") + " ✓"
                progressBar.value = 1.0
                showToast(appBackend.getTextWithDefault("translation_completed", "Çeviri tamamlandı!"), "success")
            } else {
                stageLabel.text = appBackend.getTextWithDefault("stage_error", "Hata")
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

    function showToast(msg, type) {
        toast.message = msg
        toast.toastType = type
        toast.opacity = 1.0
        toastTimer.restart()
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

    // ── Dosya ve Klasör Seçim Diyalogları ─────────────────────────────────
    FileDialog {
        id: fileDialog
        title: appBackend.uiTrigger, appBackend.getTextWithDefault("select_game_exe_title", "Oyun EXE Dosyasını Seç")
        nameFilters: Qt.platform.os === "windows"
            ? [appBackend.getTextWithDefault("renpy_games_filter", "Ren'Py Games") + " (*.exe)",
               appBackend.getTextWithDefault("all_files_filter", "All files") + " (*)"]
            : [appBackend.getTextWithDefault("shell_scripts_filter", "Shell scripts") + " (*.sh)",
               appBackend.getTextWithDefault("all_files_filter", "All files") + " (*)"]
        onAccepted: {
            var raw = selectedFile.toString()
            appBackend.setProjectPath(raw)
            projectPathField.text = appBackend.urlToPath(raw)
        }
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
                    Item {
                        Layout.preferredWidth: 44; Layout.preferredHeight: 44
                        Layout.maximumWidth: 44; Layout.maximumHeight: 44
                        Image {
                            anchors.fill: parent
                            source: appBackend.get_asset_url("icon.png")
                            sourceSize: Qt.size(64, 64)
                            fillMode: Image.PreserveAspectFit
                            smooth: true
                        }
                    }
                    ColumnLayout {
                        spacing: 2
                        Label {
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("app_title", "RenLocalizer")
                            font.pixelSize: 18; font.bold: true; color: clrTxt
                            font.letterSpacing: 0.5
                        }
                        Label {
                            text: "v" + appBackend.version
                            font.pixelSize: 11; color: clrAccent
                            font.bold: true
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
                        Layout.fillWidth: true; height: 44
                        onClicked: navIndex = 0
                        background: Rectangle {
                            radius: 10
                            color: navIndex === 0 ? Qt.rgba(0, 242, 254, 0.14) : (parent.hovered ? clrCardHover : "transparent")
                            border.color: navIndex === 0 ? clrAccent : "transparent"
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 150 } }
                        }
                        contentItem: RowLayout {
                            spacing: 14
                            Label { text: "🏠"; font.pixelSize: 17 }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_dashboard", "Dashboard")
                                font.pixelSize: 13; font.bold: navIndex === 0; color: navIndex === 0 ? clrAccent : clrTxt
                            }
                        }
                    }

                    // Buton 2: Settings (Gelişmiş Ayarlar)
                    Button {
                        Layout.fillWidth: true; height: 44
                        onClicked: navIndex = 1
                        background: Rectangle {
                            radius: 10
                            color: navIndex === 1 ? Qt.rgba(0, 242, 254, 0.14) : (parent.hovered ? clrCardHover : "transparent")
                            border.color: navIndex === 1 ? clrAccent : "transparent"
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 150 } }
                        }
                        contentItem: RowLayout {
                            spacing: 14
                            Label { text: "⚙️"; font.pixelSize: 17 }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_settings", "Settings & AI")
                                font.pixelSize: 13; font.bold: navIndex === 1; color: navIndex === 1 ? clrAccent : clrTxt
                            }
                        }
                    }

                    // Buton 3: Log Console (Detaylı Loglar)
                    Button {
                        Layout.fillWidth: true; height: 44
                        onClicked: navIndex = 2
                        background: Rectangle {
                            radius: 10
                            color: navIndex === 2 ? Qt.rgba(0, 242, 254, 0.14) : (parent.hovered ? clrCardHover : "transparent")
                            border.color: navIndex === 2 ? clrAccent : "transparent"
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 150 } }
                        }
                        contentItem: RowLayout {
                            spacing: 14
                            Label { text: "📜"; font.pixelSize: 17 }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_logs", "Log Console")
                                font.pixelSize: 13; font.bold: navIndex === 2; color: navIndex === 2 ? clrAccent : clrTxt
                            }
                        }
                    }
                    // Glossary Button
                    Button {
                        Layout.fillWidth: true; height: 44
                        onClicked: navIndex = 4
                        background: Rectangle {
                            radius: 10
                            color: navIndex === 4 ? Qt.rgba(0, 242, 254, 0.14) : (parent.hovered ? clrCardHover : "transparent")
                            border.color: navIndex === 4 ? clrAccent : "transparent"
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 150 } }
                        }
                        contentItem: RowLayout {
                            spacing: 14
                            Label { text: "📚"; font.pixelSize: 17 }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_glossary", "📚 Glossary")
                                font.pixelSize: 13; font.bold: navIndex === 4; color: navIndex === 4 ? clrAccent : clrTxt
                            }
                        }
                    }

                    // Buton 5: Toolbox (Araç Kutusu)
                    Button {
                        Layout.fillWidth: true; height: 44
                        onClicked: navIndex = 3
                        background: Rectangle {
                            radius: 10
                            color: navIndex === 3 ? Qt.rgba(0, 242, 254, 0.14) : (parent.hovered ? clrCardHover : "transparent")
                            border.color: navIndex === 3 ? clrAccent : "transparent"
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 150 } }
                        }
                        contentItem: RowLayout {
                            spacing: 14
                            Label { text: "🛠️"; font.pixelSize: 17 }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_toolbox", "🛠️ Araç Kutusu")
                                font.pixelSize: 13; font.bold: navIndex === 3; color: navIndex === 3 ? clrAccent : clrTxt
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
                        Layout.fillWidth: true; height: 38
                        onClicked: Qt.openUrlExternally("https://github.com/Lord0fTurk/RenLocalizer/wiki")
                        background: Rectangle { radius: 8; color: parent.hovered ? clrCardHover : "transparent"; border.color: clrCardBorder; border.width: 1 }
                        contentItem: RowLayout {
                            anchors.centerIn: parent; spacing: 8
                            Label { text: "📖"; font.pixelSize: 14 }
                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_wiki_guide", "Wiki Guide"); color: clrTxt2; font.pixelSize: 12; elide: Text.ElideRight }
                        }
                    }
                    Button {
                        Layout.fillWidth: true; height: 38
                        onClicked: Qt.openUrlExternally("https://www.patreon.com/RenLocalizer")
                        background: Rectangle { radius: 8; color: parent.hovered ? Qt.rgba(239, 68, 68, 0.15) : "transparent"; border.color: "#991B1B"; border.width: 1 }
                        contentItem: RowLayout {
                            anchors.centerIn: parent; spacing: 8
                            Label { text: "❤️"; font.pixelSize: 14 }
                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_patreon_support", "Patreon Support"); color: "#FCA5A5"; font.pixelSize: 12; elide: Text.ElideRight }
                        }
                    }
                }

                Item { height: 6 }

                // Sistem Durumu
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Rectangle { width: 9; height: 9; radius: 4.5; color: isTranslating ? clrWarn : clrSuccess }
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
            ScrollView {
                clip: true
                contentWidth: availableWidth
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ScrollBar.vertical: ScrollBar {}

                ColumnLayout {
                    width: parent.width
                    anchors.margins: 32
                    spacing: 24

                    Item { height: 4 }

                    // Üst Başlık
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.leftMargin: 24; Layout.rightMargin: 24
                        ColumnLayout {
                            spacing: 4
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_dashboard", "Dashboard")
                                font.pixelSize: 26; font.bold: true; color: clrTxt
                            }
                            Label {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("dashboard_subtitle", "Select game executable, configure translation engine/languages, and launch localization.")
                                font.pixelSize: 13; color: clrTxt2
                            }
                        }
                    }

                    // ── KART 1: PROJECT SETUP (PROJE KURULUMU) ────────────
                    Rectangle {
                        id: cardProject
                        Layout.fillWidth: true
                        Layout.leftMargin: 24; Layout.rightMargin: 24
                        Layout.preferredHeight: 128
                        radius: 16; color: cardProject.hovered ? clrCardHover : clrCard
                        border.color: cardProject.hovered ? Qt.rgba(0, 242, 254, 0.4) : clrCardBorder
                        border.width: 1
                        property bool hovered: false
                        Behavior on color { ColorAnimation { duration: 180 } }
                        Behavior on border.color { ColorAnimation { duration: 180 } }
                        HoverHandler { onHoveredChanged: cardProject.hovered = hovered }

                        RowLayout {
                            anchors.fill: parent; anchors.margins: 22
                            spacing: 20

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 10
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("card_project_setup", "Project Setup"); font.pixelSize: 16; font.bold: true; color: clrTxt }
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("card_project_desc", "Select game executable file or game folder."); font.pixelSize: 12; color: clrTxt2 }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 12
                                    TextField {
                                        id: projectPathField
                                        Layout.fillWidth: true; height: 40
                                        font.pixelSize: 12; color: clrTxt
                                        selectByMouse: true
                                        onEditingFinished: if (text.length > 0) appBackend.setProjectPath(text)
                                        background: Rectangle { radius: 8; color: clrInput; border.color: projectPathField.activeFocus ? clrAccent : clrCardBorder; border.width: 1 }
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
                                        onClicked: folderDialog.open()
                                        background: Rectangle {
                                            radius: 10; color: parent.hovered ? clrCardHover : clrInput
                                            border.color: parent.hovered ? Qt.rgba(0, 242, 254, 0.5) : clrCardBorder; border.width: 1
                                            Behavior on color { ColorAnimation { duration: 150 } }
                                        }
                                        contentItem: Label { text: parent.text; color: clrTxt; font.pixelSize: 13; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                    }
                                    Button {
                                        id: btnBrowseExe
                                        height: 42
                                        Layout.preferredWidth: Math.max(135, implicitContentWidth + 32)
                                        text: appBackend.uiTrigger, "🎮 " + appBackend.getTextWithDefault("browse_exe", "EXE Dosyası")
                                        onClicked: fileDialog.open()
                                        background: Rectangle {
                                            radius: 10; color: parent.hovered ? clrCardHover : clrInput
                                            border.color: parent.hovered ? clrAccent : clrCardBorder; border.width: 1
                                            Behavior on color { ColorAnimation { duration: 150 } }
                                        }
                                        contentItem: Label { text: parent.text; color: clrAccent; font.pixelSize: 13; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                    }
                                }
                            }

                            // Dekoratif İkon / Oyun Kolu Rozeti
                            Rectangle {
                                width: 72; height: 72; radius: 14; color: Qt.rgba(0, 242, 254, 0.08)
                                border.color: Qt.rgba(0, 242, 254, 0.25); border.width: 1
                                Label { anchors.centerIn: parent; text: "🎮"; font.pixelSize: 32 }
                            }
                        }
                    }

                    // ── KART 2: TRANSLATION ENGINE & LANGUAGES ────────────
                    Rectangle {
                        id: cardEngine
                        Layout.fillWidth: true
                        Layout.leftMargin: 24; Layout.rightMargin: 24
                        Layout.preferredHeight: 135
                        radius: 16; color: cardEngine.hovered ? clrCardHover : clrCard
                        border.color: cardEngine.hovered ? Qt.rgba(0, 242, 254, 0.4) : clrCardBorder
                        border.width: 1
                        property bool hovered: false
                        Behavior on color { ColorAnimation { duration: 180 } }
                        Behavior on border.color { ColorAnimation { duration: 180 } }
                        HoverHandler { onHoveredChanged: cardEngine.hovered = hovered }

                        ColumnLayout {
                            anchors.fill: parent; anchors.margins: 22
                            spacing: 14

                            RowLayout {
                                Layout.fillWidth: true
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("card_engine_title", "Translation Engine & Languages"); font.pixelSize: 16; font.bold: true; color: clrTxt }
                                Item { Layout.fillWidth: true }
                                Label { text: appBackend.uiTrigger, "⚙️ " + appBackend.getTextWithDefault("advanced_settings_link", "Configure AI Parameters ->"); color: clrAccent; font.pixelSize: 12; font.underline: true; MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: navIndex = 1 } }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 18

                                // Motor
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 5
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("engine_label", "Machine Translation / AI Engine"); font.pixelSize: 11; color: clrTxt2; font.bold: true }
                                    ComboBox {
                                        id: engineComboBox
                                        Layout.fillWidth: true; height: 40
                                        function engineModel() {
                                            appBackend.uiTrigger // Re-eval on language change
                                            return [
                                                {"id": "google", "name": "🌐 Google Translate (" + appBackend.getTextWithDefault("engine_desc_google", "Primary / Free") + ")"},
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
                                        Component.onCompleted: currentIndex = indexOfValue(appBackend.selectedEngine || "google")
                                        onActivated: { appBackend.setSelectedEngine(currentValue); appBackend.refreshUI() }
                                        background: Rectangle { radius: 8; color: clrInput; border.color: parent.hovered ? clrAccent : clrCardBorder; border.width: 1 }
                                        contentItem: Label { leftPadding: 14; text: engineComboBox.displayText; color: clrTxt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
                                        delegate: ItemDelegate {
                                            width: engineComboBox.width
                                            contentItem: Label { text: modelData.name; color: clrTxt; font.pixelSize: 12; leftPadding: 14 }
                                            background: Rectangle { color: hovered ? Qt.rgba(0, 242, 254, 0.12) : "transparent" }
                                        }
                                        popup: Popup { y: engineComboBox.height; width: engineComboBox.width; implicitHeight: Math.min(contentItem.implicitHeight, 220); padding: 4; contentItem: ListView { clip: true; implicitHeight: contentHeight; model: engineComboBox.delegateModel; ScrollBar.vertical: ScrollBar {} } background: Rectangle { color: clrCard; radius: 8; border.color: clrCardBorder; border.width: 1 } }
                                    }
                                }

                                // Kaynak Dil (Evrensel Robust Bugfix)
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 5
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("source_language", "Source Language"); font.pixelSize: 11; color: clrTxt2; font.bold: true }
                                    ComboBox {
                                        id: sourceLangCombo
                                        Layout.fillWidth: true; height: 40
                                        model: appBackend.getSourceLanguages()
                                        textRole: "name"; valueRole: "code"
                                        Component.onCompleted: currentIndex = indexOfValue("auto")
                                        onActivated: appBackend.setSourceLanguage(currentValue)
                                        background: Rectangle { radius: 8; color: clrInput; border.color: parent.hovered ? clrAccent : clrCardBorder; border.width: 1 }
                                        contentItem: Label { leftPadding: 14; text: sourceLangCombo.displayText !== "" ? sourceLangCombo.displayText : "🤖 Auto-detect"; color: clrTxt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
                                        delegate: ItemDelegate {
                                            width: sourceLangCombo.width
                                            contentItem: Label { text: getLangText(modelData, model); color: sourceLangCombo.highlightedIndex === index ? clrAccent : clrTxt; font.pixelSize: 12; leftPadding: 14 }
                                            background: Rectangle { color: hovered ? Qt.rgba(0, 242, 254, 0.12) : "transparent" }
                                        }
                                        popup: Popup { y: sourceLangCombo.height; width: sourceLangCombo.width; implicitHeight: Math.min(contentItem.implicitHeight, 260); padding: 4; contentItem: ListView { clip: true; implicitHeight: contentHeight; model: sourceLangCombo.delegateModel; ScrollBar.vertical: ScrollBar {} } background: Rectangle { color: clrCard; radius: 8; border.color: clrCardBorder; border.width: 1 } }
                                    }
                                }

                                // Hedef Dil (Evrensel Robust Bugfix)
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 5
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("target_language", "Target Language"); font.pixelSize: 11; color: clrTxt2; font.bold: true }
                                    ComboBox {
                                        id: targetLangCombo
                                        Layout.fillWidth: true; height: 40
                                        model: appBackend.getTargetLanguages()
                                        textRole: "name"; valueRole: "code"
                                        onActivated: appBackend.setTargetLanguage(currentValue)
                                        background: Rectangle { radius: 8; color: clrInput; border.color: parent.hovered ? clrAccent : clrCardBorder; border.width: 1 }
                                        contentItem: Label { leftPadding: 14; text: targetLangCombo.displayText; color: clrTxt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
                                        delegate: ItemDelegate {
                                            width: targetLangCombo.width
                                            contentItem: Label { text: getLangText(modelData, model); color: targetLangCombo.highlightedIndex === index ? clrAccent : clrTxt; font.pixelSize: 12; leftPadding: 14 }
                                            background: Rectangle { color: hovered ? Qt.rgba(0, 242, 254, 0.12) : "transparent" }
                                        }
                                        popup: Popup { y: targetLangCombo.height; width: targetLangCombo.width; implicitHeight: Math.min(contentItem.implicitHeight, 260); padding: 4; contentItem: ListView { clip: true; implicitHeight: contentHeight; model: targetLangCombo.delegateModel; ScrollBar.vertical: ScrollBar {} } background: Rectangle { color: clrCard; radius: 8; border.color: clrCardBorder; border.width: 1 } }
                                    }
                                }
                            }
                        }
                    }

                    // ── ANA AKSİYON BUTONU (NEON CYAN -> BLUE GRADIENT) ───
                    Button {
                        id: startButton
                        Layout.fillWidth: true
                        Layout.leftMargin: 24; Layout.rightMargin: 24
                        Layout.preferredHeight: 56
                        enabled: !isTranslating || currentStage !== "idle"
                        onClicked: {
                            if (isTranslating) appBackend.stopTranslation()
                            else appBackend.startTranslation()
                        }
                        background: Rectangle {
                            radius: 14
                            gradient: Gradient {
                                orientation: Gradient.Horizontal
                                GradientStop { position: 0.0; color: isTranslating ? "#EF4444" : (startButton.hovered ? "#4FACFE" : "#00F2FE") }
                                GradientStop { position: 1.0; color: isTranslating ? "#B91C1C" : (startButton.hovered ? "#00F2FE" : "#4FACFE") }
                            }
                            Behavior on opacity { NumberAnimation { duration: 150 } }
                        }
                        contentItem: RowLayout {
                            anchors.centerIn: parent
                            spacing: 12
                            Label {
                                text: appBackend.uiTrigger, isTranslating ? "⏹ " + appBackend.getTextWithDefault("btn_stop_translation", "STOP TRANSLATION") : "⚡ " + appBackend.getTextWithDefault("btn_start_translation", "START TRANSLATION →")
                                font.pixelSize: 16; font.bold: true
                                color: isTranslating ? "white" : (startButton.hovered ? "#0B0F17" : "#0A0D14")
                                font.letterSpacing: 1.0
                            }
                        }
                    }

                    // Native TLID bilgi notu
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.leftMargin: 24; Layout.rightMargin: 24
                        Layout.preferredHeight: ntTipLayout.implicitHeight + 16; radius: 8
                        visible: appBackend.outputMode === "native"
                        color: Qt.rgba(245, 158, 11, 0.08); border.color: Qt.rgba(245, 158, 11, 0.2); border.width: 1
                        RowLayout {
                            id: ntTipLayout
                            anchors.fill: parent; anchors.margins: 8; spacing: 8
                            Label { text: "⚠️"; font.pixelSize: 14 }
                            Label {
                                id: ntTipLabel; Layout.fillWidth: true; wrapMode: Text.WordWrap
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("tip_native_limitation", "Tip: Some games build UI text at runtime (quests + \"(?)\" buttons, NPC schedules, Python f-strings). Native TLID captures static text only. If parts of the interface stay untranslated, switch to Standard mode and re-translate.")
                                color: clrWarn; font.pixelSize: 11
                            }
                        }
                    }

                    // ── KART 3: PROCESS STATUS (DURUM BARı) ───────────────
                    Rectangle {
                        id: cardStatus
                        Layout.fillWidth: true
                        Layout.leftMargin: 24; Layout.rightMargin: 24
                        Layout.preferredHeight: statsVisible ? 170 : 115
                        radius: 16; color: cardStatus.hovered ? clrCardHover : clrCard
                        border.color: cardStatus.hovered ? Qt.rgba(0, 242, 254, 0.4) : clrCardBorder
                        border.width: 1
                        property bool hovered: false
                        Behavior on color { ColorAnimation { duration: 180 } }
                        Behavior on Layout.preferredHeight { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }
                        HoverHandler { onHoveredChanged: cardStatus.hovered = hovered }

                        ColumnLayout {
                            anchors.fill: parent; anchors.margins: 22
                            spacing: 14

                            RowLayout {
                                Layout.fillWidth: true
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("card_status_title", "Process Status"); font.pixelSize: 16; font.bold: true; color: clrTxt }
                                Item { Layout.fillWidth: true }
                                Label {
                                    id: stageLabel
                                    text: appBackend.uiTrigger, currentStage === "idle" ? appBackend.getTextWithDefault("status_ready", "Ready - Waiting to Start") : currentStage
                                    font.pixelSize: 13; font.bold: true; color: clrAccent
                                }
                            }

                            // İlerleme Barı
                            ProgressBar {
                                id: progressBar
                                Layout.fillWidth: true; height: 12
                                value: 0.0
                                background: Rectangle { radius: 6; color: clrInput }
                                contentItem: Item {
                                    Rectangle {
                                        width: progressBar.visualPosition * progressBar.width; height: progressBar.height; radius: 6
                                        gradient: Gradient {
                                            orientation: Gradient.Horizontal
                                            GradientStop { position: 0.0; color: clrAccent }
                                            GradientStop { position: 1.0; color: clrAccent2 }
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

                            // İstatistik Kartı Açılımı
                            RowLayout {
                                Layout.fillWidth: true
                                visible: statsVisible
                                Rectangle {
                                    Layout.fillWidth: true; height: 42; radius: 10; color: clrInput
                                    border.color: clrSuccess; border.width: 1
                                    RowLayout {
                                        anchors.fill: parent; anchors.margins: 12
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("stats_completed_banner", "🎉 Çeviri Başarıyla Tamamlandı!"); font.bold: true; color: clrSuccess; font.pixelSize: 13 }
                                        Item { Layout.fillWidth: true }
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("stats_summary_total", "Toplam:") + " " + totalLines + " | " + appBackend.getTextWithDefault("stats_summary_translated", "Çevrilen:") + " " + translatedLines + " (" + successRate.toFixed(1) + "%)"; color: clrTxt; font.pixelSize: 13; font.bold: true }
                                    }
                                }
                            }
                        }
                    }

                    // ── KART 4: LOG CONSOLE SUMMARY (MİNİ LOG PANİ) ───────
                    Rectangle {
                        id: cardLog
                        Layout.fillWidth: true
                        Layout.leftMargin: 24; Layout.rightMargin: 24
                        Layout.preferredHeight: 190
                        radius: 16; color: cardLog.hovered ? clrCardHover : clrCard
                        border.color: cardLog.hovered ? Qt.rgba(0, 242, 254, 0.4) : clrCardBorder
                        border.width: 1
                        property bool hovered: false
                        Behavior on color { ColorAnimation { duration: 180 } }
                        HoverHandler { onHoveredChanged: cardLog.hovered = hovered }

                        ColumnLayout {
                            anchors.fill: parent; anchors.margins: 18
                            spacing: 10

                            RowLayout {
                                Layout.fillWidth: true
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("card_log_title", "Log Console Summary"); font.pixelSize: 15; font.bold: true; color: clrTxt }
                                Item { Layout.fillWidth: true }
                                Button {
                                    height: 28; text: appBackend.uiTrigger, "📜 " + appBackend.getTextWithDefault("view_all_logs", "Tüm Logları Aç ->")
                                    onClicked: navIndex = 2
                                    background: Rectangle { radius: 6; color: "transparent" }
                                    contentItem: Label { text: parent.text; color: clrAccent; font.pixelSize: 12; font.underline: true }
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

            // ═════════════════════════════════════════════════════════════
            // SEKME 1: SETTINGS (TAM SAYFA GELİŞMİŞ AYARLAR)
            // ═════════════════════════════════════════════════════════════
            ScrollView {
                clip: true
                contentWidth: availableWidth
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ScrollBar.vertical: ScrollBar {}

                ColumnLayout {
                    width: parent.width
                    anchors.margins: 32
                    spacing: 24

                    Item { height: 4 }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.leftMargin: 24; Layout.rightMargin: 24
                        ColumnLayout {
                            spacing: 4
                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_settings", "Settings & Advanced Configuration"); font.pixelSize: 26; font.bold: true; color: clrTxt }
                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("settings_desc", "Configure UI language, translation threads, AI endpoints, and caching."); font.pixelSize: 13; color: clrTxt2 }
                        }
                    }

                    // 1. ARAYÜZ & SİSTEM AYARLARI KARTI (SADECE ARUI VE TEMA)
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.leftMargin: 24; Layout.rightMargin: 24
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
                        Layout.fillWidth: true
                        Layout.leftMargin: 24; Layout.rightMargin: 24
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
                                        Layout.fillWidth: true; height: 50
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
                                        Layout.fillWidth: true; height: 50
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
                                    radius: 8; color: Qt.rgba(245, 158, 11, 0.08); border.color: Qt.rgba(245, 158, 11, 0.2); border.width: 1
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

                            // KATMAN 2: ÇEVİRİ BELLEĞİ VE ÖNBELLEK YÖNETİMİ
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

                                Button {
                                    Layout.preferredWidth: 220; height: 40
                                    text: appBackend.uiTrigger, "🧹 " + appBackend.getTextWithDefault("lite_clear_cache_btn", "Çeviri Belleğini (TM) Temizle")
                                    onClicked: if (appBackend.clearTranslationCache())                             showToast(appBackend.getTextWithDefault("cache_cleared_toast", "Translation cache cleared."), "success")
                                    background: Rectangle { radius: 8; color: parent.hovered ? "#991B1B" : "#7F1D1D"; border.color: "#B91C1C"; border.width: 1 }
                                    contentItem: Label { text: parent.text; color: "white"; font.bold: true; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                }
                            }

                            Rectangle { Layout.fillWidth: true; height: 1; color: clrCardBorder }

                            // KATMAN 3: FABRİKA AYARLARINA SIFIRLAMA
                            RowLayout {
                                Layout.fillWidth: true; spacing: 16

                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 3
                                    Label { text: appBackend.uiTrigger, "🔄 " + appBackend.getTextWithDefault("factory_reset_title", "Fabrika Ayarlarına Sıfırla"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_desc", "Tüm ayarları, API anahtarlarını, sözlüğü ve çeviri önbelleklerini siler; programı ilk kurulduğu haline döndürür."); color: clrTxt2; font.pixelSize: 11; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_datadir", "Veri konumu:") + " " + appBackend.getDataDir(); color: clrTxt2; font.pixelSize: 10; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                }

                                Button {
                                    Layout.preferredWidth: 220; height: 40
                                    text: appBackend.uiTrigger, "🔄 " + appBackend.getTextWithDefault("factory_reset_btn", "Sıfırla")
                                    onClicked: factoryResetDialog.open()
                                    background: Rectangle { radius: 8; color: parent.hovered ? "#991B1B" : "#7F1D1D"; border.color: "#B91C1C"; border.width: 1 }
                                    contentItem: Label { text: parent.text; color: "white"; font.bold: true; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                }
                            }
                        }
                    }

                    // PERFORMANS VE PARAMETRELER KARTI
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.leftMargin: 24; Layout.rightMargin: 24
                        Layout.preferredHeight: perfCol.implicitHeight + 44
                        radius: 16; color: clrCard; border.color: clrCardBorder; border.width: 1
                        Behavior on Layout.preferredHeight { NumberAnimation { duration: 200 } }

                        ColumnLayout {
                            id: perfCol
                            anchors.fill: parent; anchors.margins: 22; spacing: 16
                            Label { text: appBackend.uiTrigger, "⚡ " + appBackend.getTextWithDefault("settings_section_perf", "Performans & Bağlantı Parametreleri"); font.pixelSize: 16; font.bold: true; color: clrAccent }

                            RowLayout {
                                Layout.fillWidth: true
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

                            RowLayout {
                                Layout.fillWidth: true
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("multi_endpoint_title", "Multi-Endpoint (Mirror)"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("multi_endpoint_desc", "Distributes requests across Google servers."); color: clrTxt2; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                                }
                                Switch { checked: appBackend.useMultiEndpoint; onToggled: appBackend.useMultiEndpoint = checked }
                            }

                            Rectangle { Layout.fillWidth: true; height: 1; color: clrCardBorder }

                            RowLayout {
                                Layout.fillWidth: true; spacing: 16
                                RowLayout {
                                    Layout.fillWidth: true; spacing: 8
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("rpyc_reader_title", "RPYC AST Reader"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("rpyc_reader_desc", "Reads compiled .rpyc files directly."); color: clrTxt2; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                                    }
                                    Switch { checked: appBackend.enableRpycReader; onToggled: appBackend.enableRpycReader = checked }
                                }
                                RowLayout {
                                    Layout.fillWidth: true; spacing: 8
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("parallel_batch_label", "Parallel Batch Requests"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("parallel_batch_desc", "Send multiple requests simultaneously. Disable if rate limited (429 errors)."); color: clrTxt2; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                                    }
                                    Switch {
                                        id: parallelBatchSwitch
                                        checked: appBackend.enableParallelBatch
                                        onToggled: appBackend.enableParallelBatch = checked
                                    }
                                }
                            }

                            Rectangle { Layout.fillWidth: true; height: 1; color: clrCardBorder }

                            RowLayout {
                                Layout.fillWidth: true; spacing: 16
                                RowLayout {
                                    Layout.fillWidth: true; spacing: 8
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
                        Layout.fillWidth: true
                        Layout.leftMargin: 24; Layout.rightMargin: 24
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
                                            background: Rectangle { radius: 8; color: clrInput; border.color: clrCardBorder; border.width: 1 }
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 5
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_openai_model", "Model Name:"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                        TextField {
                                            Layout.fillWidth: true; height: 40; text: appBackend.openaiModel; placeholderText: appBackend.selectedEngine === "deepseek" ? "deepseek-v4-flash" : "gpt-4o-mini"
                                            onEditingFinished: appBackend.openaiModel = text
                                            background: Rectangle { radius: 8; color: clrInput; border.color: clrCardBorder; border.width: 1 }
                                        }
                                    }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 5
                                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("openai_base_url_label", "Base URL (Optional, empty for default):"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                    TextField {
                                        Layout.fillWidth: true; height: 40; text: appBackend.openaiBaseUrl; placeholderText: appBackend.selectedEngine === "deepseek" ? "https://api.deepseek.com/v1" : "https://api.openai.com/v1"
                                        onEditingFinished: appBackend.openaiBaseUrl = text
                                        background: Rectangle { radius: 8; color: clrInput; border.color: clrCardBorder; border.width: 1 }
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
                                            background: Rectangle { radius: 8; color: clrInput; border.color: clrCardBorder; border.width: 1 }
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 5
                                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_gemini_model", "Model:"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                        TextField {
                                            Layout.fillWidth: true; height: 40; text: appBackend.geminiModel; placeholderText: "gemini-2.0-flash"
                                            onEditingFinished: appBackend.geminiModel = text
                                            background: Rectangle { radius: 8; color: clrInput; border.color: clrCardBorder; border.width: 1 }
                                        }
                                    }
                                }
                            }

                            // Local LLM (Ollama / LM Studio) Ayarları
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 14
                                visible: appBackend.selectedEngine === "local_llm" || appBackend.selectedEngine === "google"

                                RowLayout {
                                    Layout.fillWidth: true; spacing: 18
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
                        Layout.fillWidth: true
                        Layout.leftMargin: 24; Layout.rightMargin: 24
                        Layout.preferredHeight: aiTuningCol.implicitHeight + 44
                        radius: 16; color: clrCard; border.color: clrCardBorder; border.width: 1

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

                            // Satır 4: Custom System Prompt
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 6
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_prompt_label", "Custom System Prompt (Optional instructions for AI):"); color: clrTxt; font.bold: true; font.pixelSize: 13 }
                                TextField {
                                    id: aiPromptField
                                    Layout.fillWidth: true; height: 44
                                    text: appBackend.aiCustomSystemPrompt
                                    placeholderText: "Translate the following Ren'Py visual novel dialogue accurately while keeping tags..."
                                    onEditingFinished: appBackend.aiCustomSystemPrompt = text
                                    background: Rectangle { radius: 8; color: clrInput; border.color: clrCardBorder; border.width: 1 }
                                }
                            }
                        }
                    }

                    Item { height: 24 }
                }
            }

            // ═════════════════════════════════════════════════════════════
            // SEKME 2: LOG CONSOLE
            // ═════════════════════════════════════════════════════════════
            ScrollView {
                clip: true; contentWidth: availableWidth
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ScrollBar.vertical: ScrollBar {}

                ColumnLayout {
                    width: parent.width - 48; anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 18; anchors.topMargin: 32; anchors.bottomMargin: 32

                    RowLayout {
                        Layout.fillWidth: true
                        ColumnLayout {
                            spacing: 4
                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_logs", "Log Console & System Diagnostics"); font.pixelSize: 26; font.bold: true; color: clrTxt }
                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("logs_desc", "Real-time execution trace, stage notifications, and error diagnostics."); font.pixelSize: 13; color: clrTxt2 }
                        }
                        Item { Layout.fillWidth: true }
                        Button {
                            height: 40; text: appBackend.uiTrigger, "📋 " + appBackend.getTextWithDefault("copy_log", "Copy Log")
                            onClicked: {
                                var lines = []
                                for (var i = 0; i < logModel.count; i++) {
                                    var item = logModel.get(i)
                                    lines.push(item.ts + " [" + item.level.toUpperCase() + "] " + item.message)
                                }
                                appBackend.copyToClipboard(lines.join("\n"))
                                showToast(appBackend.getTextWithDefault("log_copied_clipboard", "Log copied to clipboard!"), "info")
                            }
                            background: Rectangle { radius: 8; color: clrCard; border.color: clrCardBorder; border.width: 1 }
                            contentItem: Label { text: parent.text; color: clrTxt; font.pixelSize: 12; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        }
                        Button {
                            height: 40; text: appBackend.uiTrigger, "🗑 " + appBackend.getTextWithDefault("clear_log", "Clear")
                            onClicked: logModel.clear()
                            background: Rectangle { radius: 8; color: clrCard; border.color: clrCardBorder; border.width: 1 }
                            contentItem: Label { text: parent.text; color: clrError; font.pixelSize: 12; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true; Layout.minimumHeight: 300
                        radius: 16; color: clrCard; border.color: clrCardBorder; border.width: 1

                        ListView {
                            id: logConsoleListView
                            anchors.fill: parent; anchors.margins: 18; clip: true
                            model: logModel
                            ScrollBar.vertical: ScrollBar {}
                            delegate: RowLayout {
                                width: logConsoleListView.width - 24; spacing: 14
                                Label { text: model.ts; color: clrTxtDim; font.pixelSize: 12; font.family: "Consolas" }
                                Label { text: logPrefix(model.level); color: logColor(model.level); font.bold: true; font.pixelSize: 12 }
                                Label { text: model.message; color: logColor(model.level); font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.Wrap }
                            }
                        }
                    }
                }
            }

        // ═════════════════════════════════════════════════════════════
        // SEKME 3: TOOLBOX
        // ═════════════════════════════════════════════════════════════
        ScrollView {
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical: ScrollBar {}

            ColumnLayout {
                width: parent.width
                anchors.margins: 32
                spacing: 24

                Item { height: 4 }

                // Başlık Alanı
                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 24; Layout.rightMargin: 24
                    spacing: 16
                    Label { text: "🛠️"; font.pixelSize: 32 }
                    ColumnLayout {
                        spacing: 4
                        Label {
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("toolbox_title", "RenLocalizer Araç Kutusu (Toolbox)")
                            font.pixelSize: 22; font.bold: true; color: clrTxt
                        }
                        Label {
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("toolbox_subtitle", "Görsel roman çevirilerini kusursuzlaştırmak, font hatalarını çözmek ve sözlük oluşturmak için hayat kurtaran altın araçlar.")
                            font.pixelSize: 13; color: clrTxt2; wrapMode: Text.Wrap; Layout.fillWidth: true
                        }
                    }
                }

                // ── KART 1: FONT DEĞİŞTİRİCİ VE ENJEKTÖR ─────────────────────
                Rectangle {
                    Layout.fillWidth: true
                    Layout.leftMargin: 24; Layout.rightMargin: 24
                    Layout.preferredHeight: 210
                    radius: 16; color: clrCard; border.color: clrCardBorder; border.width: 1

                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 22; spacing: 14

                        RowLayout {
                            spacing: 14; Layout.fillWidth: true
                            Rectangle {
                                width: 44; height: 44; radius: 10; color: Qt.rgba(0, 242, 254, 0.1)
                                border.color: Qt.rgba(0, 242, 254, 0.3); border.width: 1
                                Label { anchors.centerIn: parent; text: "🔤"; font.pixelSize: 22 }
                            }
                            ColumnLayout {
                                spacing: 2; Layout.fillWidth: true
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_font_title", "Font Değiştirici ve Enjektör (Font Helper)"); font.pixelSize: 16; font.bold: true; color: clrTxt }
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_font_desc", "Japonca/İngilizce oyun fontlarını Türkçe karakter destekli evrensel fontlarla otomatik değiştirerek kare kare yazı hatasını kökünden çözer."); font.pixelSize: 13; color: clrTxt2; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            }
                        }

                        Button {
                            height: 42
                            Layout.preferredWidth: Math.max(220, implicitContentWidth + 36)
                            text: appBackend.uiTrigger, "⚡ " + appBackend.getTextWithDefault("btn_run_font", "Font Enjektörünü Çalıştır")
                            onClicked: appBackend.runToolFontHelper()
                            background: Rectangle {
                                radius: 10; color: parent.hovered ? clrCardHover : clrInput
                                border.color: parent.hovered ? clrAccent : clrCardBorder; border.width: 1
                                Behavior on color { ColorAnimation { duration: 150 } }
                            }
                            contentItem: Label { text: parent.text; color: clrAccent; font.pixelSize: 13; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        }

                        Button {
                            height: 42
                            Layout.preferredWidth: Math.max(260, implicitContentWidth + 36)
                            text: appBackend.uiTrigger, "🔽 " + appBackend.getTextWithDefault("btn_font_inject", "Download & Inject Google Font")
                            onClicked: appBackend.runToolFontInject()
                            background: Rectangle {
                                radius: 10; color: parent.hovered ? clrCardHover : clrInput
                                border.color: parent.hovered ? clrSuccess : clrCardBorder; border.width: 1
                                Behavior on color { ColorAnimation { duration: 150 } }
                            }
                            contentItem: Label { text: parent.text; color: clrSuccess; font.pixelSize: 13; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        }
                    }
                }

                // ── KART 2: REN'PY HATA DOKTORU (LINT) ──────────────────────
                Rectangle {
                    Layout.fillWidth: true
                    Layout.leftMargin: 24; Layout.rightMargin: 24
                    Layout.preferredHeight: 175
                    radius: 16; color: clrCard; border.color: clrCardBorder; border.width: 1

                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 22; spacing: 14

                        RowLayout {
                            spacing: 14; Layout.fillWidth: true
                            Rectangle {
                                width: 44; height: 44; radius: 10; color: Qt.rgba(168, 85, 247, 0.1)
                                border.color: Qt.rgba(168, 85, 247, 0.3); border.width: 1
                                Label { anchors.centerIn: parent; text: "🩺"; font.pixelSize: 22 }
                            }
                            ColumnLayout {
                                spacing: 2; Layout.fillWidth: true
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_lint_title", "RenPy Hata Doktoru (Syntax & Lint Check)"); font.pixelSize: 16; font.bold: true; color: clrTxt }
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_lint_desc", "Çeviri sonrasında bozulan satır girintularını, eksik tırnakları ve değişken etiketlerini tarayıp oyunun açılırken çökmesini önler."); font.pixelSize: 13; color: clrTxt2; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            }
                        }

                        Button {
                            height: 42
                            Layout.preferredWidth: Math.max(260, implicitContentWidth + 36)
                            text: appBackend.uiTrigger, "🩺 " + appBackend.getTextWithDefault("btn_run_lint", "Hata Taramasını Başlat (Lint Check)")
                            onClicked: appBackend.runToolRenpyLint()
                            background: Rectangle {
                                radius: 10; color: parent.hovered ? clrCardHover : clrInput
                                border.color: parent.hovered ? clrPurple : clrCardBorder; border.width: 1
                                Behavior on color { ColorAnimation { duration: 150 } }
                            }
                            contentItem: Label { text: parent.text; color: clrPurple; font.pixelSize: 13; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        }
                    }
                }

                // ── KART 3: TERİM SÖZLÜĞÜ ÇIKARICI (GLOSSARY) ───────────────
                Rectangle {
                    Layout.fillWidth: true
                    Layout.leftMargin: 24; Layout.rightMargin: 24
                    Layout.preferredHeight: 175
                    radius: 16; color: clrCard; border.color: clrCardBorder; border.width: 1

                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 22; spacing: 14

                        RowLayout {
                            spacing: 14; Layout.fillWidth: true
                            Rectangle {
                                width: 44; height: 44; radius: 10; color: Qt.rgba(16, 185, 129, 0.1)
                                border.color: Qt.rgba(16, 185, 129, 0.3); border.width: 1
                                Label { anchors.centerIn: parent; text: "📚"; font.pixelSize: 22 }
                            }
                            ColumnLayout {
                                spacing: 2; Layout.fillWidth: true
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_glossary_title", "Terim Sözlüğü Çıkarıcı (Glossary Extractor)"); font.pixelSize: 16; font.bold: true; color: clrTxt }
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_glossary_desc", "Oyun içindeki özel isimleri, karakter adlarını ve krallık terimlerini tarayıp otomatik olarak glossary.json dosyasına aktararak AI çevirisinde senaryo tutarlılığı sağlar."); font.pixelSize: 13; color: clrTxt2; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            }
                        }

                        Button {
                            height: 42
                            Layout.preferredWidth: Math.max(260, implicitContentWidth + 36)
                            text: appBackend.uiTrigger, "📚 " + appBackend.getTextWithDefault("btn_run_glossary", "Terim Sözlüğünü Çıkar (Create Glossary)")
                            onClicked: appBackend.runToolGlossaryExtractor()
                            background: Rectangle {
                                radius: 10; color: parent.hovered ? clrCardHover : clrInput
                                border.color: parent.hovered ? clrSuccess : clrCardBorder; border.width: 1
                                Behavior on color { ColorAnimation { duration: 150 } }
                            }
                            contentItem: Label { text: parent.text; color: clrSuccess; font.pixelSize: 13; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        }
                    }
                }

                Item { height: 24 }
            }
        }

        // ═════════════════════════════════════════════════════════════
        // SEKME 4: GLOSSARY — TERİM SÖZLÜĞÜ YÖNETİMİ
        // ═════════════════════════════════════════════════════════════
        ScrollView {
            clip: true; contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical: ScrollBar {}

            ColumnLayout {
                width: parent.width - 48; spacing: 18; anchors.horizontalCenter: parent.horizontalCenter

                RowLayout {
                    Layout.fillWidth: true; spacing: 14
                    Label { text: "📚"; font.pixelSize: 32 }
                    ColumnLayout {
                        spacing: 4
                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_title", "Term Glossary"); font.pixelSize: 22; font.bold: true; color: clrTxt }
                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_desc", "Manage protected terms. Terms in the glossary will always be translated consistently across the entire game."); font.pixelSize: 13; color: clrTxt2; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }

                // Action bar
                RowLayout {
                    Layout.fillWidth: true; spacing: 10
                    Button {
                        height: 36; text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_btn_add", "➕ Add Term")
                        onClicked: {
                            addGlossarySource.text = ""; addGlossaryTarget.text = ""
                            addGlossaryDialog.open()
                        }
                        background: Rectangle { radius: 8; color: parent.hovered ? clrCardHover : clrInput; border.color: clrAccent; border.width: 1 }
                        contentItem: Label { text: parent.text; color: clrAccent; font.pixelSize: 12; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    }
                    Button {
                        height: 36; text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_btn_import", "📥 Import")
                        onClicked: importGlossaryDialog.open()
                        background: Rectangle { radius: 8; color: parent.hovered ? clrCardHover : clrInput; border.color: clrCardBorder; border.width: 1 }
                        contentItem: Label { text: parent.text; color: clrTxt; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    }
                    Button {
                        height: 36; text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_btn_export", "📤 Export")
                        onClicked: exportGlossaryDialog.open()
                        background: Rectangle { radius: 8; color: parent.hovered ? clrCardHover : clrInput; border.color: clrCardBorder; border.width: 1 }
                        contentItem: Label { text: parent.text; color: clrTxt; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    }
                    Item { Layout.fillWidth: true }
                    Button {
                        height: 36; text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_btn_fill", "📋 Fill Source")
                        onClicked: appBackend.fillEmptyGlossaryWithSource()
                        background: Rectangle { radius: 8; color: parent.hovered ? clrCardHover : clrInput; border.color: clrCardBorder; border.width: 1 }
                        contentItem: Label { text: parent.text; color: clrTxt; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    }
                    Button {
                        height: 36; text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_btn_translate", "🌐 Translate Empty")
                        onClicked: appBackend.translateEmptyGlossary()
                        background: Rectangle { radius: 8; color: parent.hovered ? clrCardHover : clrInput; border.color: clrPurple; border.width: 1 }
                        contentItem: Label { text: parent.text; color: clrPurple; font.pixelSize: 11; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    }
                }

                // Table header
                RowLayout {
                    Layout.fillWidth: true; spacing: 12
                    Rectangle { Layout.fillWidth: true; height: 1; color: clrCardBorder }
                }

                RowLayout {
                    Layout.fillWidth: true; spacing: 12
                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_col_source", "Source (Original)"); font.pixelSize: 12; font.bold: true; color: clrTxt2; Layout.fillWidth: true; Layout.preferredWidth: 300 }
                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_col_target", "Target (Translation)"); font.pixelSize: 12; font.bold: true; color: clrTxt2; Layout.fillWidth: true }
                    Item { Layout.preferredWidth: 40 }
                }

                // Terms list
                ListView {
                    id: glossaryListView
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.min(600, glossaryListView.count * 48 + 8)
                    model: appBackend.uiTrigger, appBackend.glossaryList
                    clip: true; interactive: false
                    delegate: RowLayout {
                        width: glossaryListView.width - 8; spacing: 12; Layout.fillWidth: true
                        Rectangle {
                            Layout.fillWidth: true; Layout.preferredWidth: 300; height: 40; radius: 8
                            color: clrInput; border.color: clrCardBorder; border.width: 1
                            Label {
                                anchors.fill: parent; anchors.margins: 10
                                text: modelData.source; color: clrTxt; font.pixelSize: 12
                                elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter
                            }
                        }
                        Rectangle {
                            Layout.fillWidth: true; height: 40; radius: 8
                            color: clrInput; border.color: modelData.target ? clrCardBorder : Qt.rgba(239, 68, 68, 0.3); border.width: 1
                            Label {
                                anchors.fill: parent; anchors.margins: 10
                                text: modelData.target || appBackend.getTextWithDefault("glossary_empty", "(empty)"); color: modelData.target ? clrTxt : clrError
                                font.pixelSize: 12; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter
                            }
                        }
                        Button {
                            Layout.preferredWidth: 36; height: 36
                            text: "✕"; onClicked: appBackend.removeGlossaryItem(modelData.source)
                            background: Rectangle { radius: 8; color: parent.hovered ? "#3B1111" : "transparent"; border.color: "transparent" }
                            contentItem: Label { text: "✕"; color: clrError; font.pixelSize: 14; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        }
                    }
                }

                Label {
                    text: appBackend.uiTrigger, glossaryListView.count + " " + appBackend.getTextWithDefault("glossary_count", "terms loaded."); color: clrTxtDim; font.pixelSize: 11
                    Layout.fillWidth: true
                }
                Item { height: 24 }
            }
        }
        }
    }

    // ── Toast Bildirim Köşesi ─────────────────────────────────────────────
    Rectangle {
        id: toast
        parent: root.contentItem
        z: 999
        anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 28
        width: Math.min(500, toastText.implicitWidth + 56); radius: 12
        height: Math.max(46, toastText.implicitHeight + 28)
        property string message: ""
        property string toastType: "info"
        color: toastType === "success" ? "#064E3B" : toastType === "error" ? "#7F1D1D" : "#1E293B"
        border.color: toastType === "success" ? clrSuccess : toastType === "error" ? clrError : clrAccent
        border.width: 1; opacity: 0.0; visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 250 } }
        RowLayout {
            anchors.fill: parent; anchors.margins: 14; spacing: 12
            Label { text: toast.toastType === "success" ? "✓" : toast.toastType === "error" ? "✕" : "ℹ"; color: "white"; font.bold: true }
            Label { id: toastText; text: toast.message; color: "white"; font.pixelSize: 13; Layout.fillWidth: true; wrapMode: Text.WordWrap }
        }
        Timer { id: toastTimer; interval: 3500; onTriggered: toast.opacity = 0.0 }
    }

    // ── Uyarı ve Tamamlanma Popup Diyalogları ─────────────────────────────
    Dialog {
        id: warningDialog
        anchors.centerIn: parent; width: Math.min(480, root.width * 0.8)
        title: titleText; property string titleText: ""; property string bodyText: ""
        modal: true; standardButtons: Dialog.Ok
        contentItem: Label { text: warningDialog.bodyText; color: clrTxt; wrapMode: Text.Wrap }
    }

    Dialog {
        id: completionDialog
        anchors.centerIn: parent; width: Math.min(540, root.width * 0.85)
        title: appBackend.getTextWithDefault("completion_summary_title", "🎉 Translation and Build Summary Report"); modal: true
        property string summaryText: ""; property string outputPath: ""; property string diagPath: ""
        standardButtons: Dialog.Ok
        contentItem: ColumnLayout {
            spacing: 14
            Label { text: completionDialog.summaryText; color: clrTxt; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Button { text: "📂 " + appBackend.getTextWithDefault("open_output_folder", "Çıktı Klasörünü Aç"); onClicked: if(completionDialog.outputPath) appBackend.openLocalPath(completionDialog.outputPath) }
        }
    }

    Dialog {
        id: updateDialog
        anchors.centerIn: parent; width: Math.min(480, root.width * 0.8)
        title: appBackend.uiTrigger, appBackend.getTextWithDefault("update_available_title", "🚀 New Version Available"); modal: true
        property string latestVersion: ""; property string releaseUrl: ""
        standardButtons: Dialog.Ok | Dialog.Cancel
        contentItem: Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("update_available_msg", "New Version: ") + updateDialog.latestVersion + "\n" + appBackend.getTextWithDefault("update_available_click", "Press OK to download."); color: clrTxt; wrapMode: Text.Wrap }
        onAccepted: if(releaseUrl) Qt.openUrlExternally(releaseUrl)
    }

    Dialog {
        id: factoryResetDialog
        anchors.centerIn: parent; width: Math.min(520, root.width * 0.85)
        title: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_title", "Fabrika Ayarlarına Sıfırla"); modal: true
        standardButtons: Dialog.Yes | Dialog.No
        contentItem: Label {
            text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_confirm", "Tüm ayarlar, API anahtarları, sözlük ve çeviri önbellekleri kalıcı olarak silinecek ve program ilk kurulduğu haline dönecek.\n\nEmin misiniz?")
            color: clrTxt; wrapMode: Text.Wrap
        }
        onAccepted: if (appBackend.factoryReset()) factoryResetDoneDialog.open()
    }

    Dialog {
        id: factoryResetDoneDialog
        anchors.centerIn: parent; width: Math.min(480, root.width * 0.8)
        title: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_done_title", "✅ Sıfırlama Tamamlandı"); modal: true
        standardButtons: Dialog.NoButton
        contentItem: ColumnLayout {
            spacing: 14
            Label {
                text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_reset_done_msg", "Program ilk kurulduğu haline döndü. Temiz bir başlangıç için uygulamayı yeniden başlatın; bundan sonra yaptığınız ayarlar otomatik kaydedilecektir.")
                color: clrTxt; wrapMode: Text.Wrap; Layout.fillWidth: true
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 12
                Button {
                    Layout.fillWidth: true; height: 40
                    text: appBackend.uiTrigger, "🔁 " + appBackend.getTextWithDefault("factory_restart_now", "Şimdi Yeniden Başlat")
                    onClicked: appBackend.restartApplication()
                    background: Rectangle { radius: 8; color: parent.hovered ? clrAccent : clrCardBorder }
                    contentItem: Label { text: parent.text; color: "white"; font.bold: true; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                }
                Button {
                    Layout.fillWidth: true; height: 40
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("factory_restart_later", "Daha Sonra")
                    onClicked: factoryResetDoneDialog.close()
                    background: Rectangle { radius: 8; color: clrInput; border.color: clrCardBorder; border.width: 1 }
                    contentItem: Label { text: parent.text; color: clrTxt; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                }
            }
        }
    }

    // ── Glossary Dialogs ─────────────────────────────────────────────────
    Dialog {
        id: addGlossaryDialog
        anchors.centerIn: parent; width: 400
        title: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_dlg_add_title", "➕ Add Glossary Term"); modal: true
        standardButtons: Dialog.Ok | Dialog.Cancel
        ColumnLayout {
            spacing: 12; Layout.fillWidth: true
            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_dlg_source", "Source (Original Text):"); color: clrTxt }
            TextField {
                id: addGlossarySource; Layout.fillWidth: true
                placeholderText: appBackend.getTextWithDefault("glossary_dlg_source_placeholder", "e.g. Character Name")
                background: Rectangle { radius: 8; color: clrInput; border.color: clrAccent; border.width: 1 }
            }
            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("glossary_dlg_target", "Target (Translation):"); color: clrTxt }
            TextField {
                id: addGlossaryTarget; Layout.fillWidth: true
                placeholderText: appBackend.getTextWithDefault("glossary_dlg_target_placeholder", "e.g. Karakter Adı")
                background: Rectangle { radius: 8; color: clrInput; border.color: clrCardBorder; border.width: 1 }
            }
        }
        onAccepted: if (addGlossarySource.text) appBackend.addGlossaryItem(addGlossarySource.text, addGlossaryTarget.text)
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
