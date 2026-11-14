// Toolbox: font injector, lint, glossary extractor, RPA, language activation.
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
                    radius: 0; color: "transparent"; border.width: 0
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.cardBorder }

                    ColumnLayout {
                        id: fontCardCol
                        anchors.fill: parent; anchors.margins: 18; spacing: 14

                        RowLayout {
                            spacing: 12; Layout.fillWidth: true
                            Rectangle {
                                width: 38; height: 38; radius: 8; color: "transparent"
                                border.color: Theme.borderControl; border.width: 1
                                Icon { anchors.centerIn: parent; glyph: Icons.type; size: 18; color: Theme.txt2 }
                            }
                            ColumnLayout {
                                spacing: 1; Layout.fillWidth: true
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_font_title", "Font Değiştirici ve Enjektör"); font.pixelSize: 16; font.bold: true; color: Theme.txt }
                                Label { text: "OpenType / TrueType Auto-Injector"; font.pixelSize: 11; color: Theme.txtDim }
                            }
                            Rectangle {
                                visible: false   // decoration: the title already names the tool
                                radius: 6; color: "transparent"
                                Layout.preferredHeight: 20; Layout.preferredWidth: 54
                                Label { anchors.centerIn: parent; text: "FONT"; font.pixelSize: 10; font.bold: true; color: Theme.txt2 }
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
                                onClicked: appBackend.toolbox.runToolFontHelper()
                                background: Rectangle {
                                    radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input
                                    border.color: parent.hovered ? Theme.txtDim : Theme.borderControl; border.width: 1
                                }
                                contentItem: IconLabel { glyph: Icons.scanSearch; text: parent.text; color: Theme.txt; iconColor: Theme.txt2; font.pixelSize: 12; font.bold: true }
                            }
                            Button {
                                Layout.fillWidth: true; height: 38
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("btn_font_inject", "Enjekte Et")
                                onClicked: appBackend.toolbox.runToolFontInject()
                                background: Rectangle {
                                    radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input
                                    border.color: parent.hovered ? Theme.txtDim : Theme.borderControl; border.width: 1
                                }
                                contentItem: IconLabel { glyph: Icons.download; text: parent.text; color: Theme.txt; iconColor: Theme.txt2; font.pixelSize: 12; font.bold: true }
                            }
                        }
                    }
                }

                // ── KART 2: REN'PY HATA DOKTORU (LINT) ──────────────────────
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: lintCardCol.implicitHeight + 36
                    radius: 0; color: "transparent"; border.width: 0
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.cardBorder }

                    ColumnLayout {
                        id: lintCardCol
                        anchors.fill: parent; anchors.margins: 18; spacing: 14

                        RowLayout {
                            spacing: 12; Layout.fillWidth: true
                            Rectangle {
                                width: 38; height: 38; radius: 8; color: "transparent"
                                border.color: Theme.borderControl; border.width: 1
                                Icon { anchors.centerIn: parent; glyph: Icons.stethoscope; size: 18; color: Theme.txt2 }
                            }
                            ColumnLayout {
                                spacing: 1; Layout.fillWidth: true
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_lint_title", "Ren'Py Hata Doktoru"); font.pixelSize: 16; font.bold: true; color: Theme.txt }
                                Label { text: "Syntax & Indentation Guard"; font.pixelSize: 11; color: Theme.txtDim }
                            }
                            Rectangle {
                                visible: false   // decoration: the title already names the tool
                                radius: 6; color: "transparent"
                                Layout.preferredHeight: 20; Layout.preferredWidth: 48
                                Label { anchors.centerIn: parent; text: "LINT"; font.pixelSize: 10; font.bold: true; color: Theme.txt2 }
                            }
                        }

                        Label {
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_lint_desc", "Çeviri sonrasında bozulan satır girintularını, eksik tırnakları ve değişken etiketlerini tarayıp oyunun açılırken çökmesini önler.")
                            font.pixelSize: 12; color: Theme.txt2; wrapMode: Text.Wrap; Layout.fillWidth: true
                        }

                        Button {
                            Layout.fillWidth: true; height: 38
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("btn_run_lint", "Hata Taramasını Başlat")
                            onClicked: appBackend.toolbox.runToolRenpyLint()
                            background: Rectangle {
                                radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input
                                border.color: parent.hovered ? Theme.txtDim : Theme.borderControl; border.width: 1
                            }
                            contentItem: IconLabel { glyph: Icons.stethoscope; text: parent.text; color: Theme.txt; iconColor: Theme.txt2; font.pixelSize: 12; font.bold: true }
                        }
                    }
                }

                // ── KART 3: TERİM SÖZLÜĞÜ ÇIKARICI (GLOSSARY) ───────────────
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: glossCardCol.implicitHeight + 36
                    radius: 0; color: "transparent"; border.width: 0
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.cardBorder }

                    ColumnLayout {
                        id: glossCardCol
                        anchors.fill: parent; anchors.margins: 18; spacing: 14

                        RowLayout {
                            spacing: 12; Layout.fillWidth: true
                            Rectangle {
                                width: 38; height: 38; radius: 8; color: "transparent"
                                border.color: Theme.borderControl; border.width: 1
                                Icon { anchors.centerIn: parent; glyph: Icons.bookA; size: 18; color: Theme.txt2 }
                            }
                            ColumnLayout {
                                spacing: 1; Layout.fillWidth: true
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_glossary_title", "Terim Sözlüğü Çıkarıcı"); font.pixelSize: 16; font.bold: true; color: Theme.txt }
                                Label { text: "Entity & Name Scanner"; font.pixelSize: 11; color: Theme.txtDim }
                            }
                            Rectangle {
                                visible: false   // decoration: the title already names the tool
                                radius: 6; color: "transparent"
                                Layout.preferredHeight: 20; Layout.preferredWidth: 62
                                Label { anchors.centerIn: parent; text: "GLOSSARY"; font.pixelSize: 10; font.bold: true; color: Theme.txt2 }
                            }
                        }

                        Label {
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_glossary_desc", "Oyun içindeki özel isimleri, karakter adlarını ve krallık terimlerini tarayıp otomatik olarak glossary.json dosyasına aktararak tutarlılık sağlar.")
                            font.pixelSize: 12; color: Theme.txt2; wrapMode: Text.Wrap; Layout.fillWidth: true
                        }

                        Button {
                            Layout.fillWidth: true; height: 38
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("btn_run_glossary", "Terim Sözlüğünü Çıkar")
                            onClicked: appBackend.toolbox.runToolGlossaryExtractor()
                            background: Rectangle {
                                radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input
                                border.color: parent.hovered ? Theme.txtDim : Theme.borderControl; border.width: 1
                            }
                            contentItem: IconLabel { glyph: Icons.bookA; text: parent.text; color: Theme.txt; iconColor: Theme.txt2; font.pixelSize: 12; font.bold: true }
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
                    radius: 0; color: "transparent"; border.width: 0
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.cardBorder }

                    property var tlLangs: []
                    function refreshLangs() {
                        tlLangs = appBackend.toolbox.toolListTlLanguages()
                        var pre = appBackend.toolbox.toolDefaultTlLanguage()
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
                                width: 38; height: 38; radius: 8; color: "transparent"
                                border.color: Theme.borderControl; border.width: 1
                                Icon { anchors.centerIn: parent; glyph: Icons.flag; size: 18; color: Theme.txt2 }
                            }
                            ColumnLayout {
                                spacing: 1; Layout.fillWidth: true
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_lang_activate_title", "Language Activation"); font.pixelSize: 16; font.bold: true; color: Theme.txt }
                                Label { text: "zzz_<lang>_language.rpy"; font.pixelSize: 11; color: Theme.txtDim }
                            }
                            Rectangle {
                                visible: false   // decoration: the title already names the tool
                                radius: 6; color: "transparent"
                                Layout.preferredHeight: 20; Layout.preferredWidth: 48
                                Label { anchors.centerIn: parent; text: "LANG"; font.pixelSize: 10; font.bold: true; color: Theme.txt2 }
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
                                background: Rectangle { radius: 8; color: Theme.input; border.color: parent.hovered ? Theme.txtDim : Theme.borderControl; border.width: 1 }
                                contentItem: Label {
                                    leftPadding: 14; rightPadding: 30
                                    text: langActCombo.displayText; elide: Text.ElideRight
                                    color: langActivateCard.tlLangs.length > 0 ? Theme.txt : Theme.txtDim
                                    font.pixelSize: 12; verticalAlignment: Text.AlignVCenter
                                }
                                delegate: ItemDelegate {
                                    width: langActCombo.width
                                    contentItem: Label { text: modelData; color: Theme.txt; font.pixelSize: 12; leftPadding: 14; elide: Text.ElideRight }
                                    background: Rectangle { color: hovered ? Theme.cardHover : "transparent" }
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
                                    border.color: btnRefreshTlLangs.hovered ? Theme.txtDim : Theme.borderControl; border.width: 1
                                }
                                contentItem: Label {
                                    text: "⟳"; color: btnRefreshTlLangs.hovered ? Theme.txt : Theme.txt2
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
                                onClicked: appBackend.toolbox.runToolActivateLanguage(langActCombo.currentText)
                                background: Rectangle {
                                    radius: 8; color: parent.hovered ? Theme.cardHover : Theme.input
                                    border.color: parent.hovered ? Theme.txtDim : Theme.borderControl; border.width: 1
                                }
                                contentItem: IconLabel { glyph: Icons.flag; text: parent.text; color: Theme.txt; iconColor: Theme.txt2; font.pixelSize: 12; font.bold: true; elide: Text.ElideRight }
                            }
                            Button {
                                Layout.fillWidth: true; height: 38
                                text: appBackend.uiTrigger, appBackend.getTextWithDefault("btn_remove_language_activation", "Remove activation")
                                onClicked: appBackend.toolbox.runToolRemoveLanguageActivation()
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
                    radius: 0; color: "transparent"; border.width: 0
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.cardBorder }

                    ColumnLayout {
                        id: rpaCardCol
                        anchors.fill: parent; anchors.margins: 18; spacing: 14

                        RowLayout {
                            spacing: 12; Layout.fillWidth: true
                            Rectangle {
                                width: 38; height: 38; radius: 8; color: "transparent"
                                border.color: Theme.borderControl; border.width: 1
                                Icon { anchors.centerIn: parent; glyph: Icons.packageBox; size: 18; color: Theme.txt2 }
                            }
                            ColumnLayout {
                                spacing: 1; Layout.fillWidth: true
                                Label { text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_unrpa_title", "Arşiv & AST Çözücü"); font.pixelSize: 16; font.bold: true; color: Theme.txt }
                                Label { text: "Unrpa & AST Decompile Engine"; font.pixelSize: 11; color: Theme.txtDim }
                            }
                            Rectangle {
                                visible: false   // decoration: the title already names the tool
                                radius: 6; color: "transparent"
                                Layout.preferredHeight: 20; Layout.preferredWidth: 60
                                Label { anchors.centerIn: parent; text: "PIPELINE"; font.pixelSize: 10; font.bold: true; color: Theme.txt2 }
                            }
                        }

                        Label {
                            text: appBackend.uiTrigger, appBackend.getTextWithDefault("tool_unrpa_desc", "Oyun dizinindeki .rpa arşivlerini otomatik açar ve .rpyc ikili dosyalarını çözümler. Pipeline tarafından arka planda otomatik yönetilir.")
                            font.pixelSize: 12; color: Theme.txt2; wrapMode: Text.Wrap; Layout.fillWidth: true
                        }

                        Rectangle {
                            Layout.fillWidth: true; height: 38; radius: 8
                            color: Theme.surfaceSubtle
                            border.color: Theme.cardBorder; border.width: 1
                            Label {
                                anchors.centerIn: parent
                                text: appBackend.uiTrigger, "✓ " + appBackend.getTextWithDefault("tool_unrpa_status", "Çeviri başlatıldığında otomatik devreye girer")
                                color: Theme.txt2; font.pixelSize: 11
                            }
                        }
                    }
                }
            }

            Item { height: 24 }
        }
    }
}
