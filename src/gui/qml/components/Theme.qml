// Theme.qml — RenLocalizer design tokens (2.9.0).
//
// Two themes: dark ("obsidian") and light ("daylight"). The ids are the ones
// stored in config.json since 2.8.21, so old settings keep working; a stored
// "cyber_neon" is treated as dark.
// Four accent presets: cyan_teal (default), emerald, indigo, amber.
//
// Rules the pages follow:
//   * Neutral surfaces. No blue tint, no glow, no gradients.
//   * The accent is for the one primary action on a screen, progress and
//     focus. Selected navigation, icons and switches stay neutral.
//   * Structure comes from spacing and hairlines (borderCard), not from boxes.
//
// Type scale (test_qml_integrity enforces it): 10 badge/chip · 11 secondary ·
// 12 body · 13 emphasised body/label · 14 subheading · 16 section title ·
// 18 dialog title · 20 icon in a 40 px tile · 24 page title · 36 empty-state icon.
pragma Singleton
import QtQuick

QtObject {
    id: root

    property string themeMode:    "obsidian"  // "obsidian" (dark) | "daylight" (light)
    property string accentPreset: "cyan_teal" // "cyan_teal" | "emerald" | "indigo" | "amber"

    readonly property bool light: themeMode === "daylight"

    // ── Accent ───────────────────────────────────────────────────────────
    // The light theme uses a darker step of each hue: the bright ones do not
    // carry text or a white label on a white surface.
    readonly property color accentSolid: {
        switch (accentPreset) {
            case "emerald": return light ? "#047857" : "#10B981"
            case "indigo":  return light ? "#4F46E5" : "#818CF8"
            case "amber":   return light ? "#B45309" : "#F59E0B"
            default:        return light ? "#0E7490" : "#06B6D4"
        }
    }

    readonly property color accentHoverSolid: {
        switch (accentPreset) {
            case "emerald": return light ? "#065F46" : "#34D399"
            case "indigo":  return light ? "#4338CA" : "#A5B4FC"
            case "amber":   return light ? "#92400E" : "#FBBF24"
            default:        return light ? "#155E75" : "#22D3EE"
        }
    }

    readonly property color textOnAccentSolid: light ? "#FFFFFF" : "#061014"

    // Swatches for the accent picker (always the bright step).
    readonly property color presetCyan:    "#06B6D4"
    readonly property color presetEmerald: "#10B981"
    readonly property color presetIndigo:  "#6366F1"
    readonly property color presetAmber:   "#F59E0B"

    // ── Surfaces ─────────────────────────────────────────────────────────
    readonly property color canvas:         light ? "#F4F5F7" : "#0F1114"  // window
    readonly property color surfaceSidebar: light ? "#ECEEF1" : "#0B0D0F"
    readonly property color surfaceCard:    light ? "#FFFFFF" : "#15181C"  // panels, cards
    readonly property color surfaceControl: light ? "#FFFFFF" : "#1A1E23"  // inputs, buttons
    readonly property color surfaceHover:   light ? "#E9ECF0" : "#22272E"
    readonly property color surfaceSubtle:  light ? "#F7F8FA" : "#13161A"

    // ── Lines ────────────────────────────────────────────────────────────
    readonly property color borderCard:    light ? "#DFE3E8" : "#23272D"   // hairlines, panel edges
    readonly property color borderControl: light ? "#C9CFD6" : "#2E343C"   // inputs
    readonly property color borderFocus:   accentSolid

    // ── Text ─────────────────────────────────────────────────────────────
    readonly property color textPrimary:   light ? "#15181C" : "#E9EBEE"
    readonly property color textSecondary: light ? "#5C6570" : "#8A929C"
    readonly property color textMuted:     light ? "#8D96A1" : "#68717C"

    // ── Accent tints ─────────────────────────────────────────────────────
    readonly property color accentSubtle: Qt.rgba(accentSolid.r, accentSolid.g, accentSolid.b, light ? 0.10 : 0.12)
    readonly property color accentBorder: Qt.rgba(accentSolid.r, accentSolid.g, accentSolid.b, light ? 0.55 : 0.45)
    readonly property color accentContrastText: textOnAccentSolid
    readonly property color effectGlow: "transparent"   // kept for old call sites; nothing glows

    // ── Status ───────────────────────────────────────────────────────────
    readonly property color statusSuccess:       light ? "#047857" : "#10B981"
    readonly property color statusSuccessSubtle: Qt.rgba(0.0627, 0.7255, 0.5059, 0.14)
    readonly property color statusSuccessBorder: Qt.rgba(0.0627, 0.7255, 0.5059, 0.40)
    readonly property color statusWarning:       light ? "#B45309" : "#F59E0B"
    readonly property color statusWarningSubtle: Qt.rgba(0.9608, 0.6196, 0.0431, 0.14)
    readonly property color statusWarningBorder: Qt.rgba(0.9608, 0.6196, 0.0431, 0.40)
    readonly property color statusDanger:        light ? "#BE123C" : "#F43F5E"
    readonly property color statusDangerSubtle:  Qt.rgba(0.9568, 0.2471, 0.3686, 0.14)
    readonly property color statusDangerBorder:  Qt.rgba(0.9568, 0.2471, 0.3686, 0.40)
    readonly property color statusInfo:          light ? "#0369A1" : "#38BDF8"
    readonly property color statusInfoSubtle:    Qt.rgba(0.2196, 0.7412, 0.9725, 0.12)
    readonly property color statusInfoBorder:    Qt.rgba(0.2196, 0.7412, 0.9725, 0.35)

    // ── Short names used across the QML ──────────────────────────────────
    readonly property color bg:          canvas
    readonly property color sidebar:     surfaceSidebar
    readonly property color sidebarTop:  surfaceSidebar
    readonly property color card:        surfaceCard
    readonly property color cardHover:   surfaceHover
    readonly property color cardBorder:  borderCard
    readonly property color input:       surfaceControl
    readonly property color inputDeep:   surfaceSubtle
    readonly property color primary:     surfaceHover
    readonly property color accent:      accentSolid
    readonly property color accentHover: accentHoverSolid
    readonly property color accent2:     accentHoverSolid
    readonly property color textOnAccent: textOnAccentSolid
    readonly property color txt:         textPrimary
    readonly property color txt2:        textSecondary
    readonly property color txtDim:      textMuted

    readonly property color success:     statusSuccess
    readonly property color successDim:  statusSuccessSubtle
    readonly property color warn:        statusWarning
    readonly property color warnHover:   light ? "#92400E" : "#FBBF24"
    readonly property color warnDim:     statusWarningSubtle
    readonly property color error:       statusDanger
    readonly property color errorHover:  light ? "#9F1239" : "#FB7185"
    readonly property color errorStrong: "#E11D48"
    readonly property color errorSoft:   light ? "#881337" : "#FECDD3"

    // Irreversible actions (factory reset, clearing the cache)
    readonly property color danger:       light ? "#9F1239" : "#881337"
    readonly property color dangerHover:  light ? "#BE123C" : "#9F1239"
    readonly property color dangerBorder: light ? "#E11D48" : "#BE123C"
    readonly property color dangerTint:   Qt.rgba(0.9568, 0.2471, 0.3686, 0.15)

    // Support link: a warm pink, an invitation rather than an alarm.
    readonly property color support:      light ? "#DB2777" : "#F472B6"

    // Toast backgrounds
    readonly property color toastSuccess: light ? "#D1FAE5" : "#064E3B"
    readonly property color toastError:   light ? "#FFE4E6" : "#4C0519"
    readonly property color toastWarn:    light ? "#FEF3C7" : "#78350F"
    readonly property color toastInfo:    light ? "#E0F2FE" : "#082F49"

    readonly property color purple:      "#A855F7"
    readonly property color white:       "#FFFFFF"
    readonly property color black:       "#000000"

    // A translucent step of a colour: Theme.alpha(Theme.error, 0.15)
    function alpha(c, a) {
        return Qt.rgba(c.r, c.g, c.b, a)
    }
}
