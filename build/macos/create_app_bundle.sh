#!/bin/bash
# create_app_bundle.sh — RenLocalizer macOS .app bundle oluşturucu
#
# Usage: ./create_app_bundle.sh <pyinstaller_dist_dir> <output_app_name>
#   pyinstaller_dist_dir : PyInstaller'ın ürettiği onedir çıktı klasörü (örn. dist/RenLocalizer)
#   output_app_name      : Oluşturulacak .app adı (örn. RenLocalizer.app)

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
FRAMEWORKS_DIR="${CONTENTS}/Frameworks"

echo "→ Creating .app bundle structure at: ${APP_DIR}"
mkdir -p "${MACOS_DIR}"
mkdir -p "${RESOURCES_DIR}"
mkdir -p "${FRAMEWORKS_DIR}"

# Copy PyInstaller output into MacOS/
echo "→ Copying PyInstaller build from: ${DIST_DIR}"
cp -R "${DIST_DIR}/." "${MACOS_DIR}/"

# Copy icon into Resources
if [ -f "icon.png" ]; then
    echo "→ Converting icon.png to iconset..."
    mkdir -p RenLocalizer.iconset
    sips -z 16 16     icon.png --out RenLocalizer.iconset/icon_16x16.png    2>/dev/null || true
    sips -z 32 32     icon.png --out RenLocalizer.iconset/icon_16x16@2x.png 2>/dev/null || true
    sips -z 32 32     icon.png --out RenLocalizer.iconset/icon_32x32.png    2>/dev/null || true
    sips -z 64 64     icon.png --out RenLocalizer.iconset/icon_32x32@2x.png 2>/dev/null || true
    sips -z 128 128   icon.png --out RenLocalizer.iconset/icon_128x128.png  2>/dev/null || true
    sips -z 256 256   icon.png --out RenLocalizer.iconset/icon_128x128@2x.png 2>/dev/null || true
    sips -z 256 256   icon.png --out RenLocalizer.iconset/icon_256x256.png  2>/dev/null || true
    sips -z 512 512   icon.png --out RenLocalizer.iconset/icon_256x256@2x.png 2>/dev/null || true
    sips -z 512 512   icon.png --out RenLocalizer.iconset/icon_512x512.png  2>/dev/null || true
    sips -z 1024 1024 icon.png --out RenLocalizer.iconset/icon_512x512@2x.png 2>/dev/null || true
    iconutil -c icns RenLocalizer.iconset -o "${RESOURCES_DIR}/RenLocalizer.icns" 2>/dev/null || \
        cp icon.png "${RESOURCES_DIR}/RenLocalizer.png"
    rm -rf RenLocalizer.iconset
    echo "→ Icon installed to Resources/"
fi

# Create the launch wrapper script (Contents/MacOS/launch)
# This sets up the correct env before running the actual binary
cat > "${MACOS_DIR}/launch" << 'LAUNCH_EOF'
#!/bin/bash
# Launch wrapper for RenLocalizer.app
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Software rendering fallback support
if [ "${RENLOCALIZER_QT_RENDER_MODE}" = "software" ]; then
    export LIBGL_ALWAYS_SOFTWARE=1
    export QT_QUICK_BACKEND=software
fi

# Ensure Qt can find its plugins from the bundled copy
export QT_PLUGIN_PATH="${SCRIPT_DIR}/PyQt6/Qt6/plugins"
export QML2_IMPORT_PATH="${SCRIPT_DIR}/PyQt6/Qt6/qml"

# Launch the actual binary
exec "${SCRIPT_DIR}/RenLocalizer" "$@"
LAUNCH_EOF
chmod +x "${MACOS_DIR}/launch"
echo "→ Launch wrapper created: ${MACOS_DIR}/launch"

# Determine version from src/version.py if available
VERSION="1.0"
if [ -f "src/version.py" ]; then
    EXTRACTED=$(grep -oP '(?<=VERSION = ")[^"]+' src/version.py 2>/dev/null || true)
    [ -n "$EXTRACTED" ] && VERSION="$EXTRACTED"
fi
echo "→ Detected version: ${VERSION}"

# Write Info.plist
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

echo "✓ .app bundle created successfully: ${APP_DIR}"