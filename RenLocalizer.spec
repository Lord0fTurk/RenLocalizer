# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
project_dir = os.path.abspath(os.getcwd())

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
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(project_dir, 'icon.ico') if sys.platform == 'win32' else None,
    manifest=os.path.join(project_dir, 'src', 'RenLocalizer.manifest') if (sys.platform == 'win32' and os.path.exists(os.path.join(project_dir, 'src', 'RenLocalizer.manifest'))) else None,
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
    upx=True,
    console=True,                       # CLI needs console!
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(project_dir, 'icon.ico') if sys.platform == 'win32' else None,
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
    upx=True,
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
    upx=True,
    upx_exclude=[],
    name='RenLocalizerCLI',
)

# =========================================================
# macOS: BUNDLE → produces RenLocalizer.app via PyInstaller
# Only active on macOS; on other platforms this block is skipped.
# This is the correct way to create an .app bundle — manual
# post-processing causes "Failed to load Python shared library"
# because the bootloader detects the .app path and expects
# Contents/Frameworks/Python which only PyInstaller's own
# bundle step sets up properly.
# =========================================================
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='RenLocalizer.app',
        icon=os.path.join(project_dir, 'icon.png'),
        bundle_identifier='com.lord0fturk.renlocalizer',
        version=open(os.path.join(project_dir, 'src', 'version.py')).read().split('"')[1]
            if os.path.exists(os.path.join(project_dir, 'src', 'version.py')) else '1.0',
        info_plist={
            'CFBundleName': 'RenLocalizer',
            'CFBundleDisplayName': 'RenLocalizer',
            'CFBundleShortVersionString': open(os.path.join(project_dir, 'src', 'version.py')).read().split('"')[1]
                if os.path.exists(os.path.join(project_dir, 'src', 'version.py')) else '1.0',
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





