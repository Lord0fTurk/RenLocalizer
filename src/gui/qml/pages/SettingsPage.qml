// Settings: General & Output, AI, Performance & Network.
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
    id: pageSettings
    // Used by Main.qml (backend signal handlers, file dialogs, drag & drop).
    property alias uiLanguageCombo: uiLanguageCombo
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
                    color: pageSettings.settingsSubTab === 0 ? Theme.cardHover : (parent.hovered ? Theme.cardHover : "transparent")
                    border.color: pageSettings.settingsSubTab === 0 ? Theme.txtDim : Theme.borderControl
                    border.width: 1
                    Behavior on color { ColorAnimation { duration: 140 } }
                }
                contentItem: IconLabel {
                    glyph: Icons.monitor
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("subtab_general", "Genel & Çıktı")
                    color: pageSettings.settingsSubTab === 0 ? Theme.txt : Theme.txt2
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
                    color: pageSettings.settingsSubTab === 1 ? Theme.cardHover : (parent.hovered ? Theme.cardHover : "transparent")
                    border.color: pageSettings.settingsSubTab === 1 ? Theme.txtDim : Theme.borderControl
                    border.width: 1
                    Behavior on color { ColorAnimation { duration: 140 } }
                }
                contentItem: IconLabel {
                    glyph: Icons.bot
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("subtab_ai", "Yapay Zeka (AI)")
                    color: pageSettings.settingsSubTab === 1 ? Theme.txt : Theme.txt2
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
                    color: pageSettings.settingsSubTab === 2 ? Theme.cardHover : (parent.hovered ? Theme.cardHover : "transparent")
                    border.color: pageSettings.settingsSubTab === 2 ? Theme.txtDim : Theme.borderControl
                    border.width: 1
                    Behavior on color { ColorAnimation { duration: 140 } }
                }
                contentItem: IconLabel {
                    glyph: Icons.gauge
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("subtab_perf", "Performans & Ağ")
                    color: pageSettings.settingsSubTab === 2 ? Theme.txt : Theme.txt2
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
            Layout.preferredHeight: colUiSettings.implicitHeight + 44
            radius: 0; color: "transparent"; border.width: 0
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.cardBorder }

            ColumnLayout {
                id: colUiSettings
                anchors.fill: parent; anchors.margins: 22; spacing: 14
                IconLabel { alignment: Qt.AlignLeft; glyph: Icons.monitor; text: appBackend.uiTrigger, appBackend.getTextWithDefault("settings_section_ui", "Arayüz & Sistem Ayarları"); font.pixelSize: 16; font.bold: true; color: Theme.txt; iconColor: Theme.txt2 }

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
                        delegate: ItemDelegate { width: uiLanguageCombo.width; contentItem: Label { text: modelData.name; color: Theme.txt; font.pixelSize: 12; leftPadding: 14 } background: Rectangle { color: hovered ? Theme.cardHover : "transparent" } }
                        popup: Popup { y: uiLanguageCombo.height; width: uiLanguageCombo.width; implicitHeight: 240; padding: 4; contentItem: ListView { clip: true; model: uiLanguageCombo.delegateModel; ScrollBar.vertical: ScrollBar {} } background: Rectangle { color: Theme.card; radius: 8; border.color: Theme.cardBorder; border.width: 1 } }
                    }
                    Item { Layout.fillWidth: true }
                }

                // Tema Modu Seçimi (Obsidian / Daylight / Cyber Neon)
                RowLayout {
                    Layout.fillWidth: true; spacing: 14
                    Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("theme_mode_label", "Arayüz Teması:")
                        color: Theme.txt; font.bold: true; font.pixelSize: 13
                        Layout.preferredWidth: 160
                    }
                    RowLayout {
                        spacing: 8
                        Button {
                            id: btnThemeObsidian
                            height: 36
                            checkable: true
                            checked: Theme.themeMode === "obsidian"
                            contentItem: Text {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("theme_obsidian", "Dark")
                                color: btnThemeObsidian.checked ? Theme.txt : Theme.txt2
                                font.pixelSize: 12
                                font.bold: btnThemeObsidian.checked
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            background: Rectangle {
                                implicitWidth: 110; implicitHeight: 36; radius: 6
                                color: btnThemeObsidian.checked ? Theme.cardHover : (btnThemeObsidian.hovered ? Theme.cardHover : Theme.input)
                                border.color: btnThemeObsidian.checked ? Theme.borderControl : Theme.cardBorder
                                border.width: 1
                            }
                            onClicked: appBackend.setThemeMode("obsidian")
                        }
                        Button {
                            id: btnThemeDaylight
                            height: 36
                            checkable: true
                            checked: Theme.themeMode === "daylight"
                            contentItem: Text {
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("theme_daylight", "Light")
                                color: btnThemeDaylight.checked ? Theme.txt : Theme.txt2
                                font.pixelSize: 12
                                font.bold: btnThemeDaylight.checked
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            background: Rectangle {
                                implicitWidth: 110; implicitHeight: 36; radius: 6
                                color: btnThemeDaylight.checked ? Theme.cardHover : (btnThemeDaylight.hovered ? Theme.cardHover : Theme.input)
                                border.color: btnThemeDaylight.checked ? Theme.borderControl : Theme.cardBorder
                                border.width: 1
                            }
                            onClicked: appBackend.setThemeMode("daylight")
                        }
                    }
                    Item { Layout.fillWidth: true }
                }

                // Vurgu Paleti Seçimi (Cyan / Emerald / Indigo / Amber)
                RowLayout {
                    Layout.fillWidth: true; spacing: 14
                    Label {
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("accent_preset_label", "Vurgu Rengi:")
                        color: Theme.txt; font.bold: true; font.pixelSize: 13
                        Layout.preferredWidth: 160
                    }
                    RowLayout {
                        spacing: 8
                        Button {
                            id: btnAccentCyan
                            height: 36
                            checkable: true
                            checked: Theme.accentPreset === "cyan_teal"
                            contentItem: RowLayout {
                                anchors.centerIn: parent; spacing: 6
                                Rectangle { width: 10; height: 10; radius: 5; color: Theme.presetCyan }
                                Text {
                                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("accent_cyan", "Cyan")
                                    color: btnAccentCyan.checked ? Theme.txt : Theme.txt2
                                    font.pixelSize: 12
                                    font.bold: btnAccentCyan.checked
                                }
                            }
                            background: Rectangle {
                                implicitWidth: 96; implicitHeight: 36; radius: 6
                                color: btnAccentCyan.checked ? Theme.cardHover : (btnAccentCyan.hovered ? Theme.cardHover : Theme.input)
                                border.color: btnAccentCyan.checked ? Theme.borderControl : Theme.cardBorder
                                border.width: 1
                            }
                            onClicked: appBackend.setAccentPreset("cyan_teal")
                        }
                        Button {
                            id: btnAccentEmerald
                            height: 36
                            checkable: true
                            checked: Theme.accentPreset === "emerald"
                            contentItem: RowLayout {
                                anchors.centerIn: parent; spacing: 6
                                Rectangle { width: 10; height: 10; radius: 5; color: Theme.presetEmerald }
                                Text {
                                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("accent_emerald", "Emerald")
                                    color: btnAccentEmerald.checked ? Theme.txt : Theme.txt2
                                    font.pixelSize: 12
                                    font.bold: btnAccentEmerald.checked
                                }
                            }
                            background: Rectangle {
                                implicitWidth: 96; implicitHeight: 36; radius: 6
                                color: btnAccentEmerald.checked ? Theme.cardHover : (btnAccentEmerald.hovered ? Theme.cardHover : Theme.input)
                                border.color: btnAccentEmerald.checked ? Theme.borderControl : Theme.cardBorder
                                border.width: 1
                            }
                            onClicked: appBackend.setAccentPreset("emerald")
                        }
                        Button {
                            id: btnAccentIndigo
                            height: 36
                            checkable: true
                            checked: Theme.accentPreset === "indigo"
                            contentItem: RowLayout {
                                anchors.centerIn: parent; spacing: 6
                                Rectangle { width: 10; height: 10; radius: 5; color: Theme.presetIndigo }
                                Text {
                                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("accent_indigo", "Indigo")
                                    color: btnAccentIndigo.checked ? Theme.txt : Theme.txt2
                                    font.pixelSize: 12
                                    font.bold: btnAccentIndigo.checked
                                }
                            }
                            background: Rectangle {
                                implicitWidth: 96; implicitHeight: 36; radius: 6
                                color: btnAccentIndigo.checked ? Theme.cardHover : (btnAccentIndigo.hovered ? Theme.cardHover : Theme.input)
                                border.color: btnAccentIndigo.checked ? Theme.borderControl : Theme.cardBorder
                                border.width: 1
                            }
                            onClicked: appBackend.setAccentPreset("indigo")
                        }
                        Button {
                            id: btnAccentAmber
                            height: 36
                            checkable: true
                            checked: Theme.accentPreset === "amber"
                            contentItem: RowLayout {
                                anchors.centerIn: parent; spacing: 6
                                Rectangle { width: 10; height: 10; radius: 5; color: Theme.presetAmber }
                                Text {
                                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("accent_amber", "Amber")
                                    color: btnAccentAmber.checked ? Theme.txt : Theme.txt2
                                    font.pixelSize: 12
                                    font.bold: btnAccentAmber.checked
                                }
                            }
                            background: Rectangle {
                                implicitWidth: 96; implicitHeight: 36; radius: 6
                                color: btnAccentAmber.checked ? Theme.cardHover : (btnAccentAmber.hovered ? Theme.cardHover : Theme.input)
                                border.color: btnAccentAmber.checked ? Theme.borderControl : Theme.cardBorder
                                border.width: 1
                            }
                            onClicked: appBackend.setAccentPreset("amber")
                        }
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
                    RlSwitch {
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
            radius: 0; color: "transparent"; border.width: 0
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.cardBorder }
            Behavior on Layout.preferredHeight { NumberAnimation { duration: 200 } }

            ColumnLayout {
                id: outCol
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                anchors.margins: 22; spacing: 18

                IconLabel { alignment: Qt.AlignLeft; glyph: Icons.packageBox; text: appBackend.uiTrigger, appBackend.getTextWithDefault("settings_section_output", "Çıktı Üretim Modu & Çeviri Belleği (Output & TM Cache)"); font.pixelSize: 16; font.bold: true; color: Theme.txt; iconColor: Theme.txt2 }

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
                                color: appBackend.outputMode === "strings" ? Theme.cardHover : (btnStringsMode.hovered ? Theme.surfaceHover : Theme.surfaceControl)
                                border.color: appBackend.outputMode === "strings" ? Theme.txtDim : Theme.borderControl
                                border.width: appBackend.outputMode === "strings" ? 2 : 1
                                Behavior on color { ColorAnimation { duration: 150 } }
                            }

                            contentItem: RowLayout {
                                anchors.centerIn: parent; spacing: 8
                                Item { Layout.fillWidth: true }
                                Label { text: appBackend.outputMode === "strings" ? "●" : "○"; color: appBackend.outputMode === "strings" ? Theme.txt : Theme.txtDim; font.pixelSize: 16 }
                                Icon { glyph: Icons.fileJson; size: 14; color: appBackend.outputMode === "strings" ? Theme.txt : Theme.txt2 }
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("mode_strings_btn", "Standard (strings.json)"); color: appBackend.outputMode === "strings" ? Theme.txt : Theme.txt; font.bold: appBackend.outputMode === "strings"; font.pixelSize: 12 }
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
                                color: appBackend.outputMode === "native" ? Theme.cardHover : (btnNativeMode.hovered ? Theme.surfaceHover : Theme.surfaceControl)
                                border.color: appBackend.outputMode === "native" ? Theme.txtDim : Theme.borderControl
                                border.width: appBackend.outputMode === "native" ? 2 : 1
                                Behavior on color { ColorAnimation { duration: 150 } }
                            }

                            contentItem: RowLayout {
                                anchors.centerIn: parent; spacing: 6
                                Item { Layout.fillWidth: true }
                                Label { text: appBackend.outputMode === "native" ? "●" : "○"; color: appBackend.outputMode === "native" ? Theme.txt : Theme.txtDim; font.pixelSize: 16 }
                                Icon { glyph: Icons.zap; size: 14; color: appBackend.outputMode === "native" ? Theme.txt : Theme.txt2 }
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("mode_native_btn", "Native TLID"); color: appBackend.outputMode === "native" ? Theme.txt : Theme.txt; font.bold: appBackend.outputMode === "native"; font.pixelSize: 12 }
                                IconLabel { glyph: Icons.sparkles; text: appBackend.uiTrigger, appBackend.getTextWithDefault("badge_recommended", "Recommended"); color: Theme.success; font.pixelSize: 10; font.bold: true; spacing: 4; Layout.leftMargin: 6 }
                                Item { Layout.fillWidth: true }
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true; Layout.preferredHeight: descLayout.implicitHeight + 16
                        radius: 8; color: Theme.surfaceSubtle; border.color: Theme.cardBorder; border.width: 1
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
                        radius: 8; color: Theme.statusWarningSubtle; border.color: Theme.statusWarningBorder; border.width: 1
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
                    RlSwitch { checked: appBackend.activateLanguageOnLaunch; onToggled: appBackend.activateLanguageOnLaunch = checked }
                }

                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.cardBorder }

                // Karakter ve Konuşmacı İsimlerini Çevir (Character("Name") toggle)
                RowLayout {
                    Layout.fillWidth: true; spacing: 10
                    ColumnLayout {
                        Layout.fillWidth: true
                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("translate_character_names_title", "Translate Character & Speaker Names"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("translate_character_names_desc", "Extracts and translates Character('Name') definitions. Recommended to keep OFF to prevent translating proper names into literal words."); color: Theme.txt2; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                    }
                    RlSwitch { checked: appBackend.translateCharacterNames; onToggled: appBackend.translateCharacterNames = checked }
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

                    RlSwitch {
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
            radius: 0; color: "transparent"; border.width: 0
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.cardBorder }
            Behavior on Layout.preferredHeight { NumberAnimation { duration: 200 } }

            ColumnLayout {
                id: perfCol
                anchors.fill: parent; anchors.margins: 22; spacing: 16
                IconLabel { alignment: Qt.AlignLeft; glyph: Icons.gauge; text: appBackend.uiTrigger, appBackend.getTextWithDefault("settings_section_perf", "Performans & Bağlantı Parametreleri"); font.pixelSize: 16; font.bold: true; color: Theme.txt; iconColor: Theme.txt2 }

                RowLayout {
                    Layout.fillWidth: true; spacing: 20
                    ColumnLayout {
                        Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 6
                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("concurrency_label", "Concurrent Threads") + ": " + Math.round(threadsSlider.value); color: Theme.txt; font.bold: true; font.pixelSize: 13; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                        RlSlider { id: threadsSlider; Layout.fillWidth: true; from: 1; to: 32; stepSize: 1; value: appBackend.maxConcurrentThreads; onMoved: appBackend.maxConcurrentThreads = value }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 6
                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("delay_label", "Request Delay") + ": " + delaySlider.value.toFixed(2) + "s"; color: Theme.txt; font.bold: true; font.pixelSize: 13; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                        RlSlider { id: delaySlider; Layout.fillWidth: true; from: 0.0; to: 3.0; stepSize: 0.05; value: appBackend.requestDelay; onMoved: appBackend.requestDelay = value }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true; spacing: 6
                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("batch_label", "Batch Size") + ": " + Math.round(batchSlider.value); color: Theme.txt; font.bold: true; font.pixelSize: 13; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                    RlSlider { id: batchSlider; Layout.fillWidth: true; from: 10; to: 500; stepSize: 10; value: appBackend.maxBatchSize; onMoved: appBackend.maxBatchSize = value }
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
                        RlSwitch { checked: appBackend.useMultiEndpoint; onToggled: appBackend.useMultiEndpoint = checked }
                    }

                    // Switch 2: Parallel Batch
                    RowLayout {
                        Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 10
                        ColumnLayout {
                            Layout.fillWidth: true
                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("parallel_batch_label", "Parallel Batch Requests"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("parallel_batch_desc", "Send multiple requests simultaneously. Disable if rate limited."); color: Theme.txt2; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                        }
                        RlSwitch {
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
                        RlSwitch { checked: appBackend.enableRpycReader; onToggled: appBackend.enableRpycReader = checked }
                    }

                    // Switch 4: Stateful Lexer
                    RowLayout {
                        Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 10
                        ColumnLayout {
                            Layout.fillWidth: true
                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("stateful_lexer_title", "Stateful Lexer Engine (Experimental)"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("stateful_lexer_desc", "State-machine parser for script parsing. Enable to test stateful lexer pass."); color: Theme.txt2; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                        }
                        RlSwitch { checked: appBackend.enableStatefulLexer; onToggled: appBackend.enableStatefulLexer = checked }
                    }
                }
            }
        }

        // PROXY KARTI
        Rectangle {
            id: cardProxySettings
            objectName: "cardProxySettings"
            visible: pageSettings.settingsSubTab === 2
            Layout.fillWidth: true
            Layout.preferredHeight: proxyCol.implicitHeight + 44
            radius: 0; color: "transparent"; border.width: 0
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.cardBorder }
            Behavior on Layout.preferredHeight { NumberAnimation { duration: 200 } }

            ColumnLayout {
                id: proxyCol
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                anchors.margins: 22; spacing: 14

                RowLayout {
                    Layout.fillWidth: true; spacing: 16
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 4
                        IconLabel { alignment: Qt.AlignLeft; glyph: Icons.globe; text: appBackend.uiTrigger, appBackend.getTextWithDefault("group_proxy", "Proxy Settings"); font.pixelSize: 16; font.bold: true; color: Theme.txt; iconColor: Theme.txt2 }
                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("proxy_card_desc", "Send translation requests through your own HTTP proxy, for example when a service is blocked or rate-limited on your connection."); color: Theme.txt2; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                    }
                    RlSwitch { objectName: "proxyEnabledSwitch"; checked: appBackend.proxy.proxyEnabled; onToggled: appBackend.proxy.proxyEnabled = checked }
                }

                ColumnLayout {
                    Layout.fillWidth: true; spacing: 12
                    visible: appBackend.proxy.proxyEnabled

                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 5
                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("proxy_url_label", "Proxy address"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                        TextField {
                            id: proxyUrlField
                            Layout.fillWidth: true; height: 40; text: appBackend.proxy.proxyUrl
                            placeholderText: (text.length === 0 && !activeFocus) ? (appBackend.uiTrigger, appBackend.getTextWithDefault("proxy_url_placeholder", "E.g.: http://user:pass@host:port")) : ""
                            onEditingFinished: appBackend.proxy.proxyUrl = text
                            background: Rectangle {
                                radius: 8; color: Theme.input
                                border.color: parent.activeFocus ? Theme.txtDim : Theme.borderControl; border.width: 1
                                Behavior on border.color { ColorAnimation { duration: 150 } }
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 5
                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("manual_proxies_note", "Enter one proxy address per line (host:port format):"); color: Theme.txt; font.bold: true; font.pixelSize: 13; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                        ScrollView {
                            Layout.fillWidth: true; Layout.preferredHeight: 76
                            TextArea {
                                id: proxyListArea
                                text: appBackend.proxy.proxyList
                                color: Theme.txt; font.pixelSize: 12; wrapMode: TextEdit.NoWrap; selectByMouse: true
                                topPadding: 10; bottomPadding: 10; leftPadding: 14; rightPadding: 14
                                onEditingFinished: appBackend.proxy.proxyList = text
                                background: Rectangle {
                                    radius: 8; color: Theme.input
                                    border.color: proxyListArea.activeFocus ? Theme.txtDim : Theme.borderControl; border.width: 1
                                }
                            }
                        }
                    }

                    Connections {
                        target: appBackend.proxy
                        function onProxySettingsChanged() {
                            if (!proxyUrlField.activeFocus) proxyUrlField.text = appBackend.proxy.proxyUrl
                            if (!proxyListArea.activeFocus) proxyListArea.text = appBackend.proxy.proxyList
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true; spacing: 10
                        visible: proxyListArea.text.trim().length > 0
                        ColumnLayout {
                            Layout.fillWidth: true
                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("auto_rotate_label", "Auto Rotation"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("auto_rotate_tooltip", "Use different proxy for each request - better distribution"); color: Theme.txt2; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                        }
                        RlSwitch { checked: appBackend.proxy.proxyAutoRotate; onToggled: appBackend.proxy.proxyAutoRotate = checked }
                    }

                    Label {
                        visible: appBackend.proxy.proxyIgnoredCount > 0
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault("proxy_ignored_entries", "{count} address(es) cannot be used (SOCKS or wrong format) and are skipped.").replace("{count}", appBackend.proxy.proxyIgnoredCount)
                        color: Theme.warn; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap
                    }

                    RowLayout {
                        Layout.fillWidth: true; spacing: 12
                        Label {
                            objectName: "proxyTestResultLabel"
                            Layout.fillWidth: true; wrapMode: Text.WordWrap; font.pixelSize: 12
                            text: appBackend.proxy.proxyTesting ? (appBackend.uiTrigger, appBackend.getTextWithDefault("proxy_refreshing", "Testing Connections...")) : appBackend.proxy.proxyTestResult
                            color: appBackend.proxy.proxyTesting ? Theme.txt2 : (appBackend.proxy.proxyTestOk ? Theme.success : Theme.error)
                        }
                        Button {
                            objectName: "proxyTestButton"
                            Layout.preferredWidth: 190; height: 38
                            enabled: !appBackend.proxy.proxyTesting
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("refresh_proxies_btn", "Test Connections")
                            onClicked: {
                                appBackend.proxy.proxyUrl = proxyUrlField.text
                                appBackend.proxy.proxyList = proxyListArea.text
                                appBackend.proxy.testProxies()
                            }
                            background: Rectangle { radius: 8; color: parent.hovered ? Theme.cardHover : "transparent"; border.color: Theme.borderControl; border.width: 1; opacity: parent.enabled ? 1.0 : 0.5 }
                            contentItem: IconLabel { glyph: Icons.refreshCw; text: parent.text; color: Theme.accent; font.bold: true; font.pixelSize: 11; elide: Text.ElideRight }
                        }
                    }

                    Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("proxy_scope_note", "Used by Google, Bing, NVIDIA, DeepL, OpenAI, DeepSeek and Gemini. Local models never go through the proxy. SOCKS proxies are not supported."); color: Theme.txt2; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                }
            }
        }

        // AI MOTOR KARTI (SEÇİLİ MOTORA DUYARLI TAM KAPSAMLI YAPILANDIRMA)
        Rectangle {
            id: cardAiConfig
            visible: pageSettings.settingsSubTab === 1
            Layout.fillWidth: true
            Layout.preferredHeight: aiCol.implicitHeight + 44
            radius: 0; color: "transparent"; border.width: 0
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.cardBorder }
            Behavior on Layout.preferredHeight { NumberAnimation { duration: 200 } }

            ColumnLayout {
                id: aiCol
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                anchors.margins: 22; spacing: 16

                IconLabel { alignment: Qt.AlignLeft; glyph: Icons.bot; text: appBackend.uiTrigger, appBackend.getTextWithDefault("settings_section_ai", "AI Engine Configuration"); font.pixelSize: 16; font.bold: true; color: Theme.txt; iconColor: Theme.txt2 }

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
                                    border.color: parent.activeFocus ? Theme.txtDim : Theme.borderControl; border.width: 1
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
                                    border.color: parent.activeFocus ? Theme.txtDim : Theme.borderControl; border.width: 1
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
                                border.color: parent.activeFocus ? Theme.txtDim : Theme.borderControl; border.width: 1
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

                // NVIDIA (Riva-Translate) Ayarları
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 14
                    visible: appBackend.selectedEngine === "nvidia"

                    RowLayout {
                        Layout.fillWidth: true; spacing: 18
                        ColumnLayout {
                            Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 5
                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_nvidia_key", "NVIDIA API Key:"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                            TextField {
                                id: settingsNvidiaKeyField
                                Layout.fillWidth: true; height: 40; text: appBackend.nvidiaApiKey; echoMode: TextInput.Password; placeholderText: (text.length === 0 && !activeFocus) ? ("nvapi-...") : ""
                                onEditingFinished: appBackend.nvidiaApiKey = text
                                background: Rectangle {
                                    radius: 8; color: Theme.input
                                    border.color: parent.activeFocus ? Theme.txtDim : Theme.borderControl; border.width: 1
                                    Behavior on border.color { ColorAnimation { duration: 150 } }
                                }
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 5
                            Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("label_gemini_model", "Model:"); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                            TextField {
                                id: settingsNvidiaModelField
                                Layout.fillWidth: true; height: 40; text: appBackend.nvidiaModel; placeholderText: (text.length === 0 && !activeFocus) ? ("nvidia/riva-translate-4b-instruct-v2") : ""
                                onEditingFinished: appBackend.nvidiaModel = text
                                background: Rectangle {
                                    radius: 8; color: Theme.input
                                    border.color: parent.activeFocus ? Theme.txtDim : Theme.borderControl; border.width: 1
                                    Behavior on border.color { ColorAnimation { duration: 150 } }
                                }
                            }
                        }
                    }
                    Connections {
                        target: appBackend
                        function onNvidiaApiKeyChanged() { settingsNvidiaKeyField.text = appBackend.nvidiaApiKey }
                        function onNvidiaModelChanged() { settingsNvidiaModelField.text = appBackend.nvidiaModel }
                    }
                }

                Label {
                    Layout.fillWidth: true; visible: appBackend.selectedEngineShowsApiNote
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("api_quality_note", "Tip: short one-word lines, names and texts with many placeholders are sometimes kept as-is. You can adjust any of them in the Editor after the run.")
                    color: Theme.txt2; font.pixelSize: 12; wrapMode: Text.WordWrap
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
                                    border.color: parent.activeFocus ? Theme.txtDim : Theme.borderControl; border.width: 1
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
                                    border.color: parent.activeFocus ? Theme.txtDim : Theme.borderControl; border.width: 1
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
                                    radius: 8; color: Theme.input; border.color: parent.hovered ? Theme.txtDim : Theme.borderControl; border.width: 1
                                    Behavior on border.color { ColorAnimation { duration: 150 } }
                                }
                                contentItem: Label { leftPadding: 14; text: settingsGeminiSafetyCombo.displayText; color: Theme.txt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
                                delegate: ItemDelegate {
                                    width: settingsGeminiSafetyCombo.width
                                    contentItem: Label { text: modelData.name; color: Theme.txt; font.pixelSize: 12; leftPadding: 14 }
                                    background: Rectangle { color: hovered ? Theme.cardHover : "transparent"; Behavior on color { ColorAnimation { duration: 120 } } }
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
                            background: Rectangle { radius: 8; color: Theme.input; border.color: parent.hovered ? Theme.txtDim : Theme.borderControl; border.width: 1 }
                            contentItem: Label { leftPadding: 14; text: localLlmModeCombo.displayText; color: Theme.txt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
                            delegate: ItemDelegate {
                                width: localLlmModeCombo.width
                                contentItem: Label { text: modelData.name; color: Theme.txt; font.pixelSize: 12; leftPadding: 14; elide: Text.ElideRight }
                                background: Rectangle { color: hovered ? Theme.cardHover : "transparent" }
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
                                    background: Rectangle { radius: 8; color: Theme.input; border.color: parent.hovered ? Theme.txtDim : Theme.borderControl; border.width: 1 }
                                    contentItem: Label { leftPadding: 14; text: localLlmBackendCombo.displayText; color: Theme.txt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                                    delegate: ItemDelegate {
                                        width: localLlmBackendCombo.width
                                        contentItem: Label { text: modelData.name; color: Theme.txt; font.pixelSize: 12; leftPadding: 14; elide: Text.ElideRight }
                                        background: Rectangle { color: hovered ? Theme.cardHover : "transparent" }
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
                                RlSlider {
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
                                RlSlider {
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
                                background: Rectangle { radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input; border.color: Theme.borderControl; border.width: 1 }
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
                                background: Rectangle { radius: 8; color: Theme.input; border.color: parent.hovered ? Theme.txtDim : Theme.borderControl; border.width: 1 }
                                contentItem: Label { leftPadding: 14; rightPadding: 14; text: aiBatchModeCombo.displayText; color: Theme.txt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                                delegate: ItemDelegate {
                                    width: aiBatchModeCombo.width
                                    contentItem: Label { text: modelData.name; color: Theme.txt; font.pixelSize: 12; leftPadding: 14; elide: Text.ElideRight }
                                    background: Rectangle { color: hovered ? Theme.cardHover : "transparent" }
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

                            RlSlider {
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
                        border.color: appBackend.hyMt2Active ? Theme.txtDim : Theme.borderControl
                        border.width: 1

                        ColumnLayout {
                            id: hyMt2Inner
                            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                            anchors.margins: 14; spacing: 12

                            RowLayout {
                                Layout.fillWidth: true; spacing: 10
                                IconLabel { alignment: Qt.AlignLeft; glyph: Icons.target; text: appBackend.uiTrigger, appBackend.getTextWithDefault("hy_mt2_title", "Hy-MT2 (Tencent) — Specialized Translation Profile"); color: Theme.txt; iconColor: Theme.txt2; font.bold: true; font.pixelSize: 14 }
                                Item { Layout.fillWidth: true }
                                Rectangle {
                                    radius: 10
                                    color: appBackend.hyMt2Active ? Theme.alpha(Theme.success, 0.18) : Theme.alpha(Theme.txtDim, 0.15)
                                    Layout.preferredHeight: 22; Layout.preferredWidth: hyMt2BadgeTxt.implicitWidth + 20
                                    Label { id: hyMt2BadgeTxt; anchors.centerIn: parent; text: appBackend.uiTrigger, appBackend.hyMt2Active ? appBackend.getTextWithDefault("hy_mt2_active_badge", "ACTIVE") : appBackend.getTextWithDefault("hy_mt2_inactive_badge", "OFF"); font.pixelSize: 11; font.bold: true; color: appBackend.hyMt2Active ? Theme.txt : Theme.txt2 }
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
                                    background: Rectangle { radius: 8; color: Theme.input; border.color: parent.hovered ? Theme.txtDim : Theme.borderControl; border.width: 1 }
                                    contentItem: Label { leftPadding: 14; text: hyMt2ProfileCombo.displayText; color: Theme.txt; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
                                    delegate: ItemDelegate {
                                        width: hyMt2ProfileCombo.width
                                        contentItem: Label { text: modelData.name; color: Theme.txt; font.pixelSize: 12; leftPadding: 14 }
                                        background: Rectangle { color: hovered ? Theme.cardHover : "transparent" }
                                    }
                                    popup: Popup { y: hyMt2ProfileCombo.height; width: hyMt2ProfileCombo.width; implicitHeight: Math.min(contentItem.implicitHeight, 220); padding: 4; contentItem: ListView { clip: true; implicitHeight: contentHeight; model: hyMt2ProfileCombo.delegateModel; ScrollBar.vertical: ScrollBar {} } background: Rectangle { color: Theme.card; radius: 8; border.color: Theme.cardBorder; border.width: 1 } }
                                }
                            }

                            Label {
                                text: appBackend.uiTrigger, appBackend.hyMt2Active
                                    ? appBackend.getTextWithDefault("hy_mt2_detected", "✓ Hy-MT2 profile is active — official instructions and sampling will be used.")
                                      + " " + appBackend.getTextWithDefault("hy_mt2_single_note", "Each line is sent as its own request; the batch format selector does not apply.")
                                    : appBackend.getTextWithDefault("hy_mt2_not_detected", "No Hy-MT model detected in the model name. Choose 'Force Hy-MT2 profile' to enable it anyway.")
                                color: appBackend.hyMt2Active ? Theme.txt : Theme.txt2
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
            radius: 0; color: "transparent"; border.width: 0
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.cardBorder }
            Behavior on Layout.preferredHeight { NumberAnimation { duration: 200 } }

            ColumnLayout {
                id: aiTuningCol
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                anchors.margins: 22; spacing: 18

                IconLabel { alignment: Qt.AlignLeft; glyph: Icons.slidersHorizontal; text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_tuning_title", "Advanced AI Tuning & System Prompt"); font.pixelSize: 16; font.bold: true; color: Theme.txt; iconColor: Theme.txt2 }

                // Satır 1: Temperature & Max Tokens
                RowLayout {
                    Layout.fillWidth: true; spacing: 24
                    ColumnLayout {
                        Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 6
                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_temp_label", "AI Temperature") + ": " + aiTempSlider.value.toFixed(2); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                        RlSlider { id: aiTempSlider; Layout.fillWidth: true; from: 0.0; to: 1.0; stepSize: 0.05; value: appBackend.aiTemperature; onMoved: appBackend.aiTemperature = value }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 6
                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_tokens_label", "Max Tokens") + ": " + Math.round(aiTokensSlider.value); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                        RlSlider { id: aiTokensSlider; Layout.fillWidth: true; from: 256; to: 8192; stepSize: 256; value: appBackend.aiMaxTokens; onMoved: appBackend.aiMaxTokens = value }
                    }
                }

                // Satır 2: AI Timeout & AI Batch Size
                RowLayout {
                    Layout.fillWidth: true; spacing: 24
                    ColumnLayout {
                        Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 6
                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_timeout_label", "AI Timeout") + ": " + Math.round(aiTimeoutSlider.value) + "s"; color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                        RlSlider { id: aiTimeoutSlider; Layout.fillWidth: true; from: 10; to: 300; stepSize: 10; value: appBackend.aiTimeout; onMoved: appBackend.aiTimeout = value }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 6
                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_batch_label", "AI Batch Size") + ": " + Math.round(aiBatchSlider.value); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                        RlSlider { id: aiBatchSlider; Layout.fillWidth: true; from: 1; to: 50; stepSize: 1; value: appBackend.aiBatchSize; onMoved: appBackend.aiBatchSize = value }
                    }
                }

                // Satır 3: AI Retry Count & AI Concurrency
                RowLayout {
                    Layout.fillWidth: true; spacing: 24
                    ColumnLayout {
                        Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 6
                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_retry_label", "AI Retry Count") + ": " + Math.round(aiRetrySlider.value); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                        RlSlider { id: aiRetrySlider; Layout.fillWidth: true; from: 1; to: 5; stepSize: 1; value: appBackend.aiRetryCount; onMoved: appBackend.aiRetryCount = value }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 6
                        Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("ai_concurrency_label", "AI Concurrency") + ": " + Math.round(aiConcSlider.value); color: Theme.txt; font.bold: true; font.pixelSize: 13 }
                        RlSlider { id: aiConcSlider; Layout.fillWidth: true; from: 1; to: 10; stepSize: 1; value: appBackend.aiConcurrency; onMoved: appBackend.aiConcurrency = value }
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
                                border.color: aiPromptField.activeFocus ? Theme.txtDim : Theme.borderControl
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
