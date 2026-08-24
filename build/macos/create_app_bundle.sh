#!/bin/bash
# create_app_bundle.sh — RenLocalizer macOS .app bundle oluşturucu
#
# Usage: ./create_app_bundle.sh <pyinstaller_dist_dir> <output_app_name>
#   pyinstaller_dist_dir : PyInstaller'ın ürettiği onedir çıktı klasörü (örn. dist/RenLocalizer)
#   output_app_name      : Oluşturulacak .app adı (örn. RenLocalizer.app)
#
# Önemli: PyInstaller onedir binary'si, Python shared library'yi
# çalışma dizinine göre arar. Bu nedenle tüm onedir içeriği
# Contents/MacOS/ içine düz (flat) kopyalanır; subdirectory kullanılmaz.

set -e

DIST_DIR="$1"
APP_NAME="$2"

if [ -z "$DIST_DIR" ] || [ -z "$APP_NAME" ]; then
    echo "Usage: $0 <pyinstaller_dist_dir> <output_app_name>"
    exit 1
fi

if [ ! -d "$DIST_DIR" ]; then
    echo "Error: dist directory '$DIST_DIR' does not exist."
    exit 1
fi

APP_DIR="${APP_NAME}"
CONTENTS="${APP_DIR}/Contents"
MACOS_DIR="${CONTENTS}/MacOS"
RESOURCES_DIR="${CONTENTS}/Resources"

echo "→ Creating .app bundle structure at: ${APP_DIR}"
mkdir -p "${MACOS_DIR}"
mkdir -p "${RESOURCES_DIR}"

# PyInstaller onedir içeriğini doğrudan Contents/MacOS/ içine kopyala (flat).
# Subdirectory kullanmıyoruz çünkü PyInstaller bootloader'ı Python shared
# library'yi binary ile aynı dizinde arar.
echo "→ Copying PyInstaller build (flat) into: ${MACOS_DIR}/"
cp -R "${DIST_DIR}/." "${MACOS_DIR}/"

# İkon: Resources/ içine .icns olarak yerleştir
if [ -f "icon.png" ]; then
    echo "→ Converting icon.png to iconset..."
    mkdir -p RenLocalizer.iconset
    sips -z 16   16   icon.png --out RenLocalizer.iconset/icon_16x16.png      2>/dev/null || true
    sips -z 32   32   icon.png --out RenLocalizer.iconset/icon_16x16@2x.png   2>/dev/null || true
    sips -z 32   32   icon.png --out RenLocalizer.iconset/icon_32x32.png      2>/dev/null || true
    sips -z 64   64   icon.png --out RenLocalizer.iconset/icon_32x32@2x.png   2>/dev/null || true
    sips -z 128  128  icon.png --out RenLocalizer.iconset/icon_128x128.png    2>/dev/null || true
    sips -z 256  256  icon.png --out RenLocalizer.iconset/icon_128x128@2x.png 2>/dev/null || true
    sips -z 256  256  icon.png --out RenLocalizer.iconset/icon_256x256.png    2>/dev/null || true
    sips -z 512  512  icon.png --out RenLocalizer.iconset/icon_256x256@2x.png 2>/dev/null || true
    sips -z 512  512  icon.png --out RenLocalizer.iconset/icon_512x512.png    2>/dev/null || true
    sips -z 1024 1024 icon.png --out RenLocalizer.iconset/icon_512x512@2x.png 2>/dev/null || true
    iconutil -c icns RenLocalizer.iconset -o "${RESOURCES_DIR}/RenLocalizer.icns" 2>/dev/null \
        || cp icon.png "${RESOURCES_DIR}/RenLocalizer.png"
    rm -rf RenLocalizer.iconset
    echo "→ Icon installed to Resources/"
fi

# launch wrapper: Contents/MacOS/launch
# Binary doğrudan Contents/MacOS/RenLocalizer olduğundan sadece exec yeterli.
cat > "${MACOS_DIR}/launch" << 'LAUNCH_EOF'
#!/bin/bash
# Launch wrapper for RenLocalizer.app
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Software rendering fallback
if [ "${RENLOCALIZER_QT_RENDER_MODE}" = "software" ]; then
    export LIBGL_ALWAYS_SOFTWARE=1
    export QT_QUICK_BACKEND=software
fi

# Qt plugin / QML paths (PyInstaller onedir, flat layout)
export QT_PLUGIN_PATH="${SCRIPT_DIR}/PyQt6/Qt6/plugins"
export QML2_IMPORT_PATH="${SCRIPT_DIR}/PyQt6/Qt6/qml"

exec "${SCRIPT_DIR}/RenLocalizer" "$@"
LAUNCH_EOF
chmod +x "${MACOS_DIR}/launch"
echo "→ Launch wrapper created: ${MACOS_DIR}/launch"

# Versiyon tespiti
VERSION="1.0"
if [ -f "src/version.py" ]; then
    EXTRACTED=$(grep -oP '(?<=VERSION = ")[^"]+' src/version.py 2>/dev/null || true)
    [ -n "$EXTRACTED" ] && VERSION="$EXTRACTED"
fi
echo "→ Version: ${VERSION}"

# Info.plist
cat > "${CONTENTS}/Info.plist" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>RenLocalizer</string>
    <key>CFBundleDisplayName</key>
    <string>RenLocalizer</string>
    <key>CFBundleIdentifier</key>
    <string>com.lord0fturk.renlocalizer</string>
    <key>CFBundleVersion</key>
    <string>${VERSION}</string>
    <key>CFBundleShortVersionString</key>
    <string>${VERSION}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>launch</string>
    <key>CFBundleIconFile</key>
    <string>RenLocalizer</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSRequiresAquaSystemAppearance</key>
    <false/>
    <key>LSApplicationCategoryType</key>
    <string>public.app-category.utilities</string>
</dict>
</plist>
PLIST_EOF
echo "→ Info.plist written"

echo "✓ .app bundle created: ${APP_DIR}"
echo "  Layout: Contents/MacOS/ (flat PyInstaller onedir)"