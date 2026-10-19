// Theme.qml — RenLocalizer'ın tek renk kaynağı (singleton, components/qmldir).
//
// Renk yazmadan önce buraya bakın; yeni bir ton gerekiyorsa adıyla buraya
// ekleyin, QML'e çıplak hex yazmayın. Saydam tonlar: Theme.alpha(Theme.accent, 0.15).
//
// Yazı boyutu ölçeği (test_qml_integrity zorlar): 10 rozet/çip · 11 ikincil metin ·
// 12 gövde · 13 vurgulu gövde/etiket · 14 alt başlık · 16 kart başlığı ·
// 18 diyalog başlığı · 20 rozet içi ikon (40 px) · 24 sayfa başlığı · 36 boş durum ikonu.
pragma Singleton
import QtQuick

QtObject {
    // ── Zemin ve yüzeyler ────────────────────────────────────────────────
    readonly property color bg:          "#0B0F17" // Pencere zemini
    readonly property color sidebar:     "#111522" // Sol menü
    readonly property color sidebarTop:  "#161B2E" // Sol menü üst gradyan
    readonly property color card:        "#151A29" // Kart
    readonly property color cardHover:   "#1D2436" // Kartın üzerine gelince
    readonly property color cardBorder:  "#242C44" // İnce kenarlık
    readonly property color input:       "#0E121D" // Giriş kutuları
    readonly property color inputDeep:   "#080B12" // Diyaloglardaki giriş kutuları
    readonly property color primary:     "#1A1E2E" // Material primary

    // ── Vurgu ve durum renkleri ──────────────────────────────────────────
    readonly property color accent:      "#00F2FE" // Turkuaz
    readonly property color accentHover: "#38BDF8" // Turkuaz butonun üzerine gelince
    readonly property color accent2:     "#4FACFE" // Gradyan bitişi
    readonly property color textOnAccent: "#080C14" // Turkuaz zemin üstündeki yazı
    readonly property color purple:      "#A855F7"
    readonly property color success:     "#10B981"
    readonly property color successDim:  "#2610B981" // %15 yeşil
    readonly property color warn:        "#F59E0B"
    readonly property color warnHover:   "#FBBF24"
    readonly property color warnDim:     "#26F59E0B" // %15 amber
    readonly property color error:       "#EF4444"
    readonly property color errorHover:  "#F87171"
    readonly property color errorStrong: "#DC2626"
    readonly property color errorSoft:   "#FCA5A5" // Kırmızı zemin üstündeki açık yazı

    // Geri alınamaz işlemler (fabrika ayarı, önbelleği silme)
    readonly property color danger:       "#7F1D1D"
    readonly property color dangerHover:  "#991B1B"
    readonly property color dangerBorder: "#B91C1C"
    readonly property color dangerTint:   "#3B1111" // Silme butonunun üzerine gelince

    // Bildirim (toast) zeminleri
    readonly property color toastSuccess: "#064E3B"
    readonly property color toastError:   "#7F1D1D"
    readonly property color toastWarn:    "#78350F"
    readonly property color toastInfo:    "#161D2E"

    // ── Metin ────────────────────────────────────────────────────────────
    readonly property color txt:         "#F3F4F6" // Ana metin
    readonly property color txt2:        "#9CA3AF" // İkincil metin
    readonly property color txtDim:      "#6B7280" // Soluk metin (küçük yazıda dikkat: kartta 3,6:1 kontrast)
    readonly property color white:       "#FFFFFF"
    readonly property color black:       "#000000"

    // Aynı rengin saydam tonu: Theme.alpha(Theme.error, 0.15)
    function alpha(c, a) {
        return Qt.rgba(c.r, c.g, c.b, a)
    }
}
