// Left navigation: name and version, the pages, guide and support links, run status.
//
// Names that are not defined in this file (root, navIndex, isTranslating) belong
// to Main.qml and resolve through the component that instantiates this one.
//
// Quiet on purpose: the selected page is marked by weight and a neutral fill,
// not by the accent colour. The accent is reserved for the primary action.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

Rectangle {
    id: sidebarPane
    Layout.preferredWidth: 208
    Layout.fillHeight: true
    color: Theme.sidebar

    Rectangle {
        anchors.right: parent.right
        width: 1; height: parent.height
        color: Theme.cardBorder
    }

    // index = page in Main.qml's StackLayout; the order here is the order of use.
    readonly property var pages: [
        { index: 0, glyph: Icons.languages, key: "nav_translate",  fallback: "Translate" },
        { index: 5, glyph: Icons.squarePen, key: "nav_editor",     fallback: "Editor" },
        { index: 4, glyph: Icons.bookA,     key: "nav_glossary",   fallback: "Glossary" },
        { index: 3, glyph: Icons.wrench,    key: "nav_toolbox",    fallback: "Toolbox" },
        { index: 2, glyph: Icons.terminal,  key: "nav_logs",       fallback: "Log Console" },
        { index: 1, glyph: Icons.settings,  key: "nav_settings",   fallback: "Settings & AI" }
    ]

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        anchors.topMargin: 20
        spacing: 2

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 8
            Layout.bottomMargin: 18
            spacing: 10
            Image {
                Layout.preferredWidth: 40; Layout.preferredHeight: 40
                source: appBackend.get_asset_url("icon.png")
                sourceSize: Qt.size(80, 80)
                fillMode: Image.PreserveAspectFit
                smooth: true; mipmap: true
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                Label {
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("app_title", "RenLocalizer")
                    font.pixelSize: 16; font.weight: Font.DemiBold; color: Theme.txt
                    Layout.fillWidth: true; elide: Text.ElideRight
                }
                Label {
                    text: appBackend.version
                    font.pixelSize: 11; color: Theme.txtDim
                }
            }
        }

        Repeater {
            model: sidebarPane.pages
            Button {
                id: navButton
                readonly property bool current: navIndex === modelData.index
                objectName: "nav_" + modelData.index
                Layout.fillWidth: true
                implicitHeight: 34
                topInset: 0; bottomInset: 0; leftInset: 0; rightInset: 0
                leftPadding: 10; rightPadding: 8; topPadding: 0; bottomPadding: 0
                Accessible.name: navLabel.text
                onClicked: navIndex = modelData.index
                background: Rectangle {
                    radius: 6
                    color: navButton.current || navButton.hovered ? Theme.cardHover : "transparent"
                    opacity: navButton.current ? 1.0 : (navButton.hovered ? 0.6 : 1.0)
                    border.color: navButton.visualFocus ? Theme.accent : "transparent"
                    border.width: 1
                }
                contentItem: RowLayout {
                    spacing: 11
                    Icon {
                        glyph: modelData.glyph; size: 15
                        color: navButton.current ? Theme.txt : Theme.txt2
                    }
                    Label {
                        id: navLabel
                        text: appBackend.uiTrigger, appBackend.getTextWithDefault(modelData.key, modelData.fallback)
                        Layout.fillWidth: true; elide: Text.ElideRight
                        font.pixelSize: 13
                        font.weight: navButton.current ? Font.DemiBold : Font.Normal
                        color: navButton.current ? Theme.txt : Theme.txt2
                    }
                }
            }
        }

        Item { Layout.fillHeight: true; Layout.minimumHeight: 12 }

        // Run status: visible from every page, so a run started on the
        // Translate page can be followed from the Editor or the Log.
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 10
            Layout.bottomMargin: 10
            spacing: 9
            visible: isTranslating
            Rectangle {
                width: 7; height: 7; radius: 3.5
                color: Theme.accent
                SequentialAnimation on opacity {
                    running: isTranslating
                    loops: Animation.Infinite
                    NumberAnimation { from: 1.0; to: 0.3; duration: 700; easing.type: Easing.InOutQuad }
                    NumberAnimation { from: 0.3; to: 1.0; duration: 700; easing.type: Easing.InOutQuad }
                }
            }
            Label {
                text: appBackend.uiTrigger, appBackend.getTextWithDefault("status_working", "Working...")
                color: Theme.txt2; font.pixelSize: 12
                Layout.fillWidth: true; elide: Text.ElideRight
            }
        }

        Button {
            id: btnWikiGuide
            Layout.fillWidth: true
            implicitHeight: 30
            topInset: 0; bottomInset: 0; leftInset: 0; rightInset: 0
            leftPadding: 10; rightPadding: 8; topPadding: 0; bottomPadding: 0
            onClicked: Qt.openUrlExternally("https://github.com/Lord0fTurk/RenLocalizer/wiki")
            background: Rectangle { radius: 6; color: btnWikiGuide.hovered ? Theme.cardHover : "transparent"; opacity: 0.6 }
            contentItem: RowLayout {
                spacing: 10
                Icon { glyph: Icons.bookOpen; size: 14; color: btnWikiGuide.hovered ? Theme.txt : Theme.txtDim }
                Label {
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_wiki_guide", "Wiki Guide")
                    color: btnWikiGuide.hovered ? Theme.txt : Theme.txt2; font.pixelSize: 13
                    Layout.fillWidth: true; elide: Text.ElideRight
                }
            }
        }

        // Support: a plain row, with the one small motion in the sidebar. The
        // heart beats slowly and a little faster under the pointer.
        Button {
            id: btnPatreonSupport
            Layout.fillWidth: true
            implicitHeight: 30
            topInset: 0; bottomInset: 0; leftInset: 0; rightInset: 0
            leftPadding: 10; rightPadding: 8; topPadding: 0; bottomPadding: 0
            onClicked: Qt.openUrlExternally("https://www.patreon.com/cw/LordOfTurk")
            background: Rectangle {
                radius: 6
                color: btnPatreonSupport.hovered ? Theme.alpha(Theme.support, 0.10) : "transparent"
                Behavior on color { ColorAnimation { duration: 150 } }
            }
            contentItem: RowLayout {
                spacing: 10
                Icon {
                    glyph: Icons.heart; size: 14
                    color: Theme.support
                    SequentialAnimation on scale {
                        loops: Animation.Infinite
                        running: root.visible
                        NumberAnimation { to: 1.22; duration: btnPatreonSupport.hovered ? 260 : 520; easing.type: Easing.OutQuad }
                        NumberAnimation { to: 1.0; duration: btnPatreonSupport.hovered ? 260 : 520; easing.type: Easing.InQuad }
                        PauseAnimation { duration: btnPatreonSupport.hovered ? 0 : 1400 }
                    }
                }
                Label {
                    text: appBackend.uiTrigger, appBackend.getTextWithDefault("nav_patreon_support", "Support the developer")
                    color: btnPatreonSupport.hovered ? Theme.support : Theme.txt2; font.pixelSize: 13
                    Layout.fillWidth: true; elide: Text.ElideRight
                    Behavior on color { ColorAnimation { duration: 150 } }
                }
            }
        }
    }
}
