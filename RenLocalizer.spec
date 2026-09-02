# -*- mode: python ; coding: utf-8 -*-
import os
import re
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
project_dir = os.path.abspath(os.getcwd())

# UPX stays OFF everywhere: GitHub runners ship no upx binary (so it was
# already a silent no-op in CI) and compressed unsigned bootloaders only
# raise antivirus ML-heuristic scores.
USE_UPX = False

# Windows version resource: proper PE metadata (ProductName/FileVersion/...)
# lowers generic packer-heuristic scores on unsigned builds and gives
# Defender submissions a legitimate identity to match against.
def _read_app_version() -> str:
    try:
        with open(os.path.join(project_dir, 'src', 'version.py'), encoding='utf-8') as fh:
            m = re.search(r'VERSION\s*=\s*"([^"]+)"', fh.read())
            return m.group(1) if m else '0.0.0'
    except OSError:
        return '0.0.0'

APP_VERSION = _read_app_version()
_ver_parts = [int(x) for x in APP_VERSION.split('.')] + [0] * 4
_ver_parts = _ver_parts[:4]

import tempfile

_version_info_path = os.path.join(
    tempfile.gettempdir(), f'RenLocalizer_{APP_VERSION}_version_info.txt'
)
with open(_version_info_path, 'w', encoding='utf-8') as _vf:
    _vf.write(f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({_ver_parts[0]}, {_ver_parts[1]}, {_ver_parts[2]}, {_ver_parts[3]}),
    prodvers=({_ver_parts[0]}, {_ver_parts[1]}, {_ver_parts[2]}, {_ver_parts[3]}),
    mask=0x3F,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable("040904B0", [
        StringStruct("CompanyName", "RenLocalizer Contributors"),
        StringStruct("FileDescription", "Ren'Py Visual Novel Localization Tool"),
        StringStruct("FileVersion", "{APP_VERSION}"),
        StringStruct("InternalName", "RenLocalizer"),
        StringStruct("OriginalFilename", "RenLocalizer.exe"),
        StringStruct("ProductName", "RenLocalizer"),
        StringStruct("ProductVersion", "{APP_VERSION}"),
      ])
    ]),
    VarFileInfo([VarStruct("Translation", 1033, 1200)]),
  ])
""")

win_exe_kwargs = (
    {"version_file": _version_info_path} if sys.platform == "win32" else {}
)

# Automatically collect all submodules from src package
hidden_imports = collect_submodules('src')

# Aggressively collect submodules for external libraries to prevent missing imports
hidden_imports += collect_submodules('aiohttp')
hidden_imports += collect_submodules('requests')
hidden_imports += collect_submodules('packaging')
hidden_imports += collect_submodules('charset_normalizer')
hidden_imports += collect_submodules('unrpa')
hidden_imports += collect_submodules('rpycdec')
hidden_imports += ['decompiler']  # unrpyc -> decompiler package
hidden_imports += collect_submodules('rich')
hidden_imports += collect_submodules('yaml')
hidden_imports += collect_submodules('certifi')
hidden_imports += collect_submodules('openai')
hidden_imports += collect_submodules('google.genai')
# Pandas submodules are too heavy (includes tests, matplotlib, etc). 
# Basic pandas import is usually enough or handled by auto-analysis.
# If needed, add only specific submodules manually.


# Manual additions for specific edge cases
hidden_imports.append('src.version')  # Ensure version module is bundled

if sys.platform == 'win32':
    hidden_imports.extend([
        'win32timezone',
    ])

# Force include PyQt6 specific plugins and hidden imports for Linux
if sys.platform != 'win32':
    hidden_imports.extend([
        'PyQt6.QtOpenGL',
        'PyQt6.QtNetwork',
        'PyQt6.QtPrintSupport',
    ])

# Define datas with absolute paths to avoid not found errors
datas_list = [
    (os.path.join(project_dir, 'locales'), 'locales'),
    (os.path.join(project_dir, 'icon.ico'), '.'),
    (os.path.join(project_dir, 'icon.png'), '.'),
    # Add QML files
    (os.path.join(project_dir, 'src', 'gui', 'qml'), os.path.join('src', 'gui', 'qml')),
    # Add version.py for runtime reading
    (os.path.join(project_dir, 'src', 'version.py'), 'src'),
]

# Add shell scripts only when building on non-Windows
if os.path.exists(os.path.join(project_dir, 'RenLocalizer.sh')):
    datas_list.append((os.path.join(project_dir, 'RenLocalizer.sh'), '.'))
if os.path.exists(os.path.join(project_dir, 'RenLocalizerCLI.sh')):
    datas_list.append((os.path.join(project_dir, 'RenLocalizerCLI.sh'), '.'))

binaries_list = []

if sys.platform == 'win32':
    try:
        import PyQt6

        pyqt_dir = Path(PyQt6.__file__).resolve().parent
        software_gl_dll = pyqt_dir / 'Qt6' / 'bin' / 'opengl32sw.dll'
        if software_gl_dll.exists():
            binaries_list.append((str(software_gl_dll), '.'))
    except Exception:
        pass


# =========================================================
# GUI Application Analysis (RenLocalizer)
# =========================================================
a = Analysis(
    ['run.py'],
    pathex=[project_dir],
    binaries=binaries_list,
    datas=datas_list,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'tkinter', 'matplotlib', 'IPython', 'notebook', 'scipy.stats.tests'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RenLocalizer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=USE_UPX,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(project_dir, 'icon.ico') if sys.platform == 'win32' else None,
    manifest=os.path.join(project_dir, 'src', 'RenLocalizer.manifest') if (sys.platform == 'win32' and os.path.exists(os.path.join(project_dir, 'src', 'RenLocalizer.manifest'))) else None,
    **win_exe_kwargs,
)

# =========================================================
# CLI Application Analysis & Build (RenLocalizerCLI)
# =========================================================
a_cli = Analysis(
    ['run_cli.py'],
    pathex=[project_dir],
    binaries=binaries_list,
    datas=datas_list,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'tkinter', 'matplotlib', 'IPython', 'notebook', 'scipy.stats.tests',
              'PyQt6.QtQuick', 'PyQt6.QtQml', 'PyQt6.QtOpenGL', 'PyQt6.QtNetwork', 'PyQt6.QtPrintSupport',
              'PyQt6.QtSvg', 'PyQt6.QtSvgWidgets', 'PyQt6.QtMultimedia', 'PyQt6.QtBluetooth'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz_cli = PYZ(a_cli.pure, a_cli.zipped_data, cipher=block_cipher)

exe_cli = EXE(
    pyz_cli,
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name='RenLocalizerCLI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=USE_UPX,
    console=True,                       # CLI needs console!
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(project_dir, 'icon.ico') if sys.platform == 'win32' else None,
    **win_exe_kwargs,
)

# =========================================================
# GUI Application COLLECT (RenLocalizer)
# =========================================================
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=USE_UPX,
    upx_exclude=[],
    name='RenLocalizer',
)

# =========================================================
# CLI Application COLLECT (RenLocalizerCLI)
# =========================================================
coll_cli = COLLECT(
    exe_cli,
    a_cli.binaries,
    a_cli.zipfiles,
    a_cli.datas,
    strip=False,
    upx=USE_UPX,
    upx_exclude=[],
    name='RenLocalizerCLI',
)

# =========================================================
# macOS: BUNDLE → produces RenLocalizer.app via PyInstaller
# Only active on macOS; other platforms skip this block.
# =========================================================
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='RenLocalizer.app',
        icon=os.path.join(project_dir, 'icon.icns')
            if os.path.exists(os.path.join(project_dir, 'icon.icns'))
            else None,
        bundle_identifier='com.lord0fturk.renlocalizer',
        version=APP_VERSION,
        info_plist={
            'CFBundleName': 'RenLocalizer',
            'CFBundleDisplayName': 'RenLocalizer',
            'CFBundleShortVersionString': APP_VERSION,
            'NSHighResolutionCapable': True,
            'NSRequiresAquaSystemAppearance': False,
            'LSMinimumSystemVersion': '11.0',
            'LSApplicationCategoryType': 'public.app-category.utilities',
        },
    )

# =========================================================
# Post-build: Copy CLI binary into main GUI distribution folder
# =========================================================
import shutil

_gui_dist = os.path.join(project_dir, 'dist', 'RenLocalizer')
_cli_dist = os.path.join(project_dir, 'dist', 'RenLocalizerCLI')

if os.path.isdir(_gui_dist) and os.path.isdir(_cli_dist):
    for item in os.listdir(_cli_dist):
        if item.lower().startswith('renlocalizercli'):
            src_file = os.path.join(_cli_dist, item)
            dst_file = os.path.join(_gui_dist, item)
            try:
                shutil.copy2(src_file, dst_file)
                print(f"[SPEC POST-BUILD] Merged {item} into dist/RenLocalizer/")
            except Exception as e:
                print(f"[SPEC POST-BUILD] Warning: Could not merge {item}: {e}")





