// Theme.qml — RenLocalizer Evrensel Çoklu-Tema Tasarım Sistemi (DESIGN.md v3.0 Uyumlu)
//
// 3 Ana Tema:
//   1. "obsidian"   (Varsayılan Siyah / Deep Slate)
//   2. "daylight"   (Yumuşak Buz Grisi / Beyaz Kartlar)
//   3. "cyber_neon" (Derin Uzay Siyahı / Parlak Vurgu Çerçeveleri)
//
// 4 Vurgu Paleti (Accent Presets):
//   A. "cyan_teal" (#06B6D4) — Kurumsal / Modern Utility (Varsayılan)
//   B. "emerald"   (#10B981) — Veri / Sistem / Enjeksiyon
//   C. "indigo"    (#6366F1) — Derin / Geliştirici / Motor
//   D. "amber"     (#F59E0B) — Endüstriyel / Araç Kutusu
//
// Tüm renkler DESIGN.md semantik token matrisine bağlanmıştır.
// Geriye dönük uyumluluk köprüsü (alias'lar) sayesinde mevcut 650+ çağrı korunur.
//
// Yazı boyutu ölçeği (test_qml_integrity zorlar): 10 rozet/çip · 11 ikincil metin ·
// 12 gövde · 13 vurgulu gövde/etiket · 14 alt başlık · 16 kart başlığı ·
// 18 diyalog başlığı · 20 rozet içi ikon (40 px) · 24 sayfa başlığı · 36 boş durum ikonu.
pragma Singleton
import QtQuick

QtObject {
    id: root

    // ── Tema ve Vurgu Durumları ──────────────────────────────────────────
    property string themeMode:    "obsidian"  // "obsidian" | "daylight" | "cyber_neon"
    property string accentPreset: "cyan_teal" // "cyan_teal" | "emerald" | "indigo" | "amber"

    // ── Vurgu Renkleri (Accent Presets) ──────────────────────────────────
    readonly property color accentSolid: {
        switch (accentPreset) {
            case "emerald": return "#10B981"
            case "indigo":  return "#6366F1"
            case "amber":   return "#F59E0B"
            case "cyan":
            case "cyan_teal":
            default:        return "#06B6D4"
        }
    }

    readonly property color accentHoverSolid: {
        switch (accentPreset) {
            case "emerald": return "#34D399"
            case "indigo":  return "#818CF8"
            case "amber":   return "#FBBF24"
            case "cyan":
            case "cyan_teal":
            default:        return "#22D3EE"
        }
    }

    readonly property color textOnAccentSolid: {
        switch (accentPreset) {
            case "emerald": return "#050A08"
            case "indigo":  return "#FFFFFF"
            case "amber":   return "#090602"
            case "cyan":
            case "cyan_teal":
            default:        return "#06090E"
        }
    }

    // Doğrudan palet swatch ve UI seçicileri için renk sabitleri
    readonly property color presetCyan:    "#06B6D4"
    readonly property color presetEmerald: "#10B981"
    readonly property color presetIndigo:  "#6366F1"
    readonly property color presetAmber:   "#F59E0B"

    // ── 3-Tema Semantik Token Matrisi (DESIGN.md Bölüm 2) ─────────────────

    // canvas (Pencere Zemini)
    readonly property color canvas: {
        if (themeMode === "daylight")   return "#F1F5F9"
        if (themeMode === "cyber_neon") return "#03060C"
        return "#090D14" // obsidian
    }

    // surfaceSidebar (Yan Panel)
    readonly property color surfaceSidebar: {
        if (themeMode === "daylight")   return "#E2E8F0"
        if (themeMode === "cyber_neon") return "#050A16"
        return "#0C111A" // obsidian
    }

    // surfaceCard (Kart Zemini)
    readonly property color surfaceCard: {
        if (themeMode === "daylight")   return "#FFFFFF"
        if (themeMode === "cyber_neon") return "#080D1C"
        return "#111723" // obsidian
    }

    // surfaceControl (Input / Buton Zemini)
    readonly property color surfaceControl: {
        if (themeMode === "daylight")   return "#F8FAFC"
        if (themeMode === "cyber_neon") return "#050E20"
        return "#171F2E" // obsidian
    }

    // surfaceHover (Hover Durumu)
    readonly property color surfaceHover: {
        if (themeMode === "daylight")   return "#E2E8F0"
        if (themeMode === "cyber_neon") return "#0B1832"
        return "#1E293B" // obsidian
    }

    // surfaceSubtle (Bilgi Çubuğu / Özet Barı)
    readonly property color surfaceSubtle: {
        if (themeMode === "daylight")   return "#F8FAFC"
        if (themeMode === "cyber_neon") return "#060E1E"
        return "#141C2B" // obsidian
    }

    // borderCard (Kart Kenarlık Sınırı)
    readonly property color borderCard: {
        if (themeMode === "daylight")   return "#CBD5E1"
        if (themeMode === "cyber_neon") return Qt.rgba(accentSolid.r, accentSolid.g, accentSolid.b, 0.40)
        return "#1E2636" // obsidian
    }

    // borderControl (Kontrol / Input Kenarlık Sınırı)
    readonly property color borderControl: {
        if (themeMode === "daylight")   return "#94A3B8"
        if (themeMode === "cyber_neon") return Qt.rgba(accentSolid.r, accentSolid.g, accentSolid.b, 0.65)
        return "#263042" // obsidian
    }

    // borderFocus (Aktif Odak Sınırı)
    readonly property color borderFocus: {
        if (themeMode === "cyber_neon") return accentHoverSolid
        return accentSolid
    }

    // textPrimary (Ana Başlık / Metin)
    readonly property color textPrimary: {
        if (themeMode === "daylight")   return "#0F172A"
        if (themeMode === "cyber_neon") return "#FFFFFF"
        return "#F1F5F9" // obsidian
    }

    // textSecondary (Alt Açıklama / İkincil Metin)
    readonly property color textSecondary: {
        if (themeMode === "daylight") return "#475569"
        return "#94A3B8" // obsidian & cyber_neon
    }

    // textMuted (Pasif / Etiket Metni)
    readonly property color textMuted: {
        if (themeMode === "cyber_neon") return "#52637A"
        return "#64748B" // obsidian & daylight
    }

    // accentSubtle (Seçili Dolgu / Hafif Vurgu)
    readonly property color accentSubtle: {
        var alphaVal = (themeMode === "daylight") ? 0.15 : ((themeMode === "cyber_neon") ? 0.22 : 0.12)
        return Qt.rgba(accentSolid.r, accentSolid.g, accentSolid.b, alphaVal)
    }

    // accentBorder (Seçili Sınır)
    readonly property color accentBorder: {
        var alphaBdr = (themeMode === "daylight") ? 0.55 : ((themeMode === "cyber_neon") ? 0.85 : 0.45)
        return Qt.rgba(accentSolid.r, accentSolid.g, accentSolid.b, alphaBdr)
    }

    readonly property color accentContrastText: textOnAccentSolid
    readonly property color effectGlow: (themeMode === "cyber_neon" ? Qt.rgba(accentSolid.r, accentSolid.g, accentSolid.b, 0.25) : "transparent")

    // ── Anlamsal Durum Renkleri (DESIGN.md Bölüm 1) ───────────────────────
    readonly property color statusSuccess:       "#10B981"
    readonly property color statusSuccessSubtle: Qt.rgba(0.0627, 0.7255, 0.5059, 0.14)
    readonly property color statusSuccessBorder: Qt.rgba(0.0627, 0.7255, 0.5059, 0.40)

    readonly property color statusWarning:       "#F59E0B"
    readonly property color statusWarningSubtle: Qt.rgba(0.9608, 0.6196, 0.0431, 0.14)
    readonly property color statusWarningBorder: Qt.rgba(0.9608, 0.6196, 0.0431, 0.40)

    readonly property color statusDanger:        "#F43F5E"
    readonly property color statusDangerSubtle:  Qt.rgba(0.9568, 0.2471, 0.3686, 0.14)
    readonly property color statusDangerBorder:  Qt.rgba(0.9568, 0.2471, 0.3686, 0.40)

    readonly property color statusInfo:          "#38BDF8"
    readonly property color statusInfoSubtle:    Qt.rgba(0.2196, 0.7412, 0.9725, 0.12)
    readonly property color statusInfoBorder:    Qt.rgba(0.2196, 0.7412, 0.9725, 0.35)

    // ── Geriye Dönük Uyumluluk Köprüsü (Zero-Breakage Legacy Aliases) ──────
    // Bu alias'lar sayesinde mevcut QML kodlarındaki 650+ Theme.* kullanımı bozulmaz.
    readonly property color bg:          canvas
    readonly property color sidebar:     surfaceSidebar
    readonly property color sidebarTop:  (themeMode === "daylight" ? "#CBD5E1" : (themeMode === "cyber_neon" ? "#0C1424" : "#101622"))
    readonly property color card:        surfaceCard
    readonly property color cardHover:   surfaceHover
    readonly property color cardBorder:  borderCard
    readonly property color input:       surfaceControl
    readonly property color inputDeep:   (themeMode === "daylight" ? "#F1F5F9" : (themeMode === "cyber_neon" ? "#060B14" : "#0D131E"))
    readonly property color primary:     (themeMode === "daylight" ? "#E2E8F0" : "#171F2E")

    readonly property color accent:      accentSolid
    readonly property color accentHover: accentHoverSolid
    readonly property color accent2:     accentHoverSolid
    readonly property color textOnAccent: textOnAccentSolid

    readonly property color txt:         textPrimary
    readonly property color txt2:        textSecondary
    readonly property color txtDim:      textMuted

    // Durum ve Bildirim Renkleri (Legacy Aliases)
    readonly property color success:     statusSuccess
    readonly property color successDim:  statusSuccessSubtle
    readonly property color warn:        statusWarning
    readonly property color warnHover:   "#FBBF24"
    readonly property color warnDim:     statusWarningSubtle
    readonly property color error:       statusDanger
    readonly property color errorHover:  "#FB7185"
    readonly property color errorStrong: "#E11D48"
    readonly property color errorSoft:   (themeMode === "daylight" ? "#881337" : "#FECDD3")

    // Geri alınamaz işlemler (fabrika ayarı, önbelleği silme)
    readonly property color danger:       (themeMode === "daylight" ? "#9F1239" : "#881337")
    readonly property color dangerHover:  (themeMode === "daylight" ? "#BE123C" : "#9F1239")
    readonly property color dangerBorder: (themeMode === "daylight" ? "#E11D48" : "#BE123C")
    readonly property color dangerTint:   Qt.rgba(0.9568, 0.2471, 0.3686, 0.15)

    // Destek (Patreon) butonu: kırmızı değil sıcak pembe — bu bir davet, alarm değil.
    // Açık temada beyaz kart üstünde okunsun diye koyu ton.
    readonly property color support:      (themeMode === "daylight" ? "#DB2777" : "#F472B6")

    // Bildirim (toast) zeminleri
    readonly property color toastSuccess: (themeMode === "daylight" ? "#D1FAE5" : "#064E3B")
    readonly property color toastError:   (themeMode === "daylight" ? "#FFE4E6" : "#4C0519")
    readonly property color toastWarn:    (themeMode === "daylight" ? "#FEF3C7" : "#78350F")
    readonly property color toastInfo:    (themeMode === "daylight" ? "#E0F2FE" : "#082F49")

    // Sabitler
    readonly property color purple:      "#A855F7"
    readonly property color white:       "#FFFFFF"
    readonly property color black:       "#000000"

    // ── Yardımcı Fonksiyonlar ─────────────────────────────────────────────
    // Aynı rengin saydam tonu: Theme.alpha(Theme.error, 0.15)
    function alpha(c, a) {
        return Qt.rgba(c.r, c.g, c.b, a)
    }
}
