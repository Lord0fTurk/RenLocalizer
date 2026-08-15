# -*- coding: utf-8 -*-
"""
RenLocalizer — Launcher
Ren'Py oyunları için güçlü, tek pencereli çeviri aracı.
Google Translate ve yapay zeka motorlarıyla otomatik çeviri sunar.
"""

import os
import sys
import shutil
import warnings
import logging
import tempfile
import subprocess
import stat
import faulthandler
from pathlib import Path
from types import TracebackType

# Enable native crash fault handler to capture C/C++ access violations
try:
    crash_dir = Path(__file__).parent / "logs"
    crash_dir.mkdir(parents=True, exist_ok=True)
    crash_log_file = open(crash_dir / "crash_report.log", "a", encoding="utf-8")
    faulthandler.enable(file=crash_log_file, all_threads=True)
except Exception:
    faulthandler.enable()

# ── Temel ortam ayarları (Qt importlarından ÖNCE) ─────────────────────────
os.environ["QT_QPA_PLATFORM_THEME"] = ""
os.environ["QT_STYLE_OVERRIDE"] = ""
os.environ["QT_QUICK_CONTROLS_STYLE"] = "Material"
os.environ["QT_QUICK_CONTROLS_MATERIAL_THEME"] = "Dark"
os.environ["QT_QUICK_CONTROLS_MATERIAL_ACCENT"] = "Purple"

if sys.platform == "darwin" and not os.environ.get("QT_MAC_WANTS_LAYER"):
    os.environ["QT_MAC_WANTS_LAYER"] = "1"

# Windows: Per-Monitor DPI Awareness V2
if sys.platform == "win32" and os.environ.get("RENLOCALIZER_FORCE_DPI_API", "0") == "1":
    try:
        import ctypes
        from ctypes import wintypes
        shcore = ctypes.windll.shcore
        shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
        shcore.SetProcessDpiAwareness.restype = wintypes.HRESULT
        shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32 = ctypes.windll.user32
            user32.SetProcessDPIAware.restype = wintypes.BOOL
            user32.SetProcessDPIAware()
        except Exception:
            pass

# Windows: Taskbar icon identity
if sys.platform == "win32":
    try:
        import ctypes
        from ctypes import wintypes
        shell32 = ctypes.windll.shell32
        shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
        shell32.SetCurrentProcessExplicitAppUserModelID.restype = wintypes.HRESULT
        shell32.SetCurrentProcessExplicitAppUserModelID("RenLocalizer")
    except Exception:
        pass

warnings.filterwarnings("ignore", category=SyntaxWarning, message=r".*invalid escape sequence.*")

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.setrecursionlimit(3000)

# ── Çalışma dizinini ayarla ───────────────────────────────────────────────
def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent

WORK_DIR = _get_base_dir()
os.chdir(WORK_DIR)
sys.path.insert(0, str(WORK_DIR))

# ── Sürüm ─────────────────────────────────────────────────────────────────
VERSION = "2.8.11"
try:
    from src.version import VERSION as _v
    VERSION = f"{_v}"
except ImportError:
    pass

# ── Asset yolu çözücü ─────────────────────────────────────────────────────
def resolve_asset(path: str | Path) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / path
    return WORK_DIR / path


# ── Unix İzin Yardımcısı ──────────────────────────────────────────────────
def ensure_executable_permissions(base_dir: Path, logger) -> None:
    """macOS ve Linux üzerinde gömülü çalıştırılabilir veya betik dosyaların izin bitlerini kontrol eder."""
    if sys.platform == "win32":
        return
        
    logger.info("Checking Unix execute permissions...")
    
    # Taranacak dizinler (src/tools, package root ve sys.executable'ın kendisi)
    search_dirs = [
        base_dir / "src" / "tools",
        base_dir
    ]
    
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        search_dirs.append(Path(sys._MEIPASS))
        
    for directory in search_dirs:
        if not directory.exists():
            continue
        for root_dir, _, files in os.walk(directory):
            for file_name in files:
                file_path = Path(root_dir) / file_name
                if file_name.endswith((".sh", ".so", ".dylib")) or file_path.name == "unrpa":
                    try:
                        st = os.stat(file_path)
                        if not (st.st_mode & stat.S_IXUSR):
                            os.chmod(file_path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                            logger.info(f"Set execute permission for: {file_path.name}")
                    except Exception as e:
                        logger.warning(f"Could not adjust execute permissions for {file_path.name}: {e}")


# ── Crash handler ─────────────────────────────────────────────────────────
def _global_exception_handler(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> None:
    import traceback
    import datetime

    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    crash_path = WORK_DIR / "logs" / "crash_report.log"
    try:
        crash_path.parent.mkdir(parents=True, exist_ok=True)
        with open(crash_path, "a", encoding="utf-8") as f:
            f.write(f"\n{'=' * 60}\n[{timestamp}]\n{error_msg}\n")
    except Exception:
        pass

    print(error_msg)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None,
                f"RenLocalizer crash:\n\n{exc_value}\n\nReport: {crash_path}",
                "RenLocalizer — Hata",
                0x10,
            )
        except Exception:
            pass

    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _global_exception_handler


# ── Qt ortam yapılandırması ───────────────────────────────────────────────
def _setup_qt_env() -> None:
    if not (getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")):
        return
    meipass = Path(sys._MEIPASS)
    if hasattr(os, "add_dll_directory"):
        for p in [meipass, meipass / "PyQt6" / "Qt6" / "bin"]:
            if p.exists():
                try:
                    os.add_dll_directory(str(p))
                except Exception:
                    pass
    plugin_paths = [
        meipass / "PyQt6" / "Qt6" / "plugins",
        meipass / "PyQt6" / "plugins",
    ]
    existing = [str(p) for p in plugin_paths if p.exists()]
    if existing:
        os.environ["QT_PLUGIN_PATH"] = os.pathsep.join(existing)
    os.environ["QT_LOGGING_RULES"] = "qt.qpa.fonts=false;qt.text.font.db=false;*.debug=false"


# ── Ana fonksiyon ─────────────────────────────────────────────────────────
def main() -> int:
    print("=" * 60)
    print(f"RenLocalizer ({VERSION}) Starting...")
    print("=" * 60)

    _setup_qt_env()

    # Qt runtime utils (mevcut run.py ile paylaşılan)
    from src.utils.qt_runtime import (
        configure_qt_graphics_environment,
        should_attempt_qt_safe_relaunch,
        build_qt_safe_relaunch_env,
    )
    from src.utils.logger import setup_logger

    logger = setup_logger()
    logger.info("RenLocalizer starting, version: %s", VERSION)
    ensure_executable_permissions(WORK_DIR, logger)

    graphics_bootstrap = configure_qt_graphics_environment(
        frozen=bool(getattr(sys, "frozen", False))
    )
    logger.info(
        "Qt graphics: platform=%s mode=%s",
        sys.platform,
        graphics_bootstrap.mode,
    )

    # ── Qt import ─────────────────────────────────────────────────────────
    print("Loading Qt framework...")

    try:
        from PyQt6.QtCore import QTimer, QUrl, Qt
        from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
        from PyQt6.QtQuick import QQuickWindow, QSGRendererInterface
        from PyQt6.QtWidgets import QApplication, QSplashScreen
        from PyQt6.QtQml import QQmlApplicationEngine

        if graphics_bootstrap.graphics_api == "opengl":
            QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
        elif graphics_bootstrap.graphics_api == "software":
            QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Software)

        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

        app = QApplication(sys.argv)
        app.setApplicationName("RenLocalizer")
        app.setApplicationDisplayName("RenLocalizer")
        app.setApplicationVersion(VERSION)
        app.setOrganizationName("RenLocalizer")
        app.setOrganizationDomain("lord0fturk.github.io/RenLocalizer")

        # ── Splash ────────────────────────────────────────────────────────
        splash_src = resolve_asset("icon.png")
        if splash_src.exists():
            splash_px = QPixmap(str(splash_src))
        else:
            splash_px = QPixmap(480, 280)
            splash_px.fill(QColor("#121224"))
            p = QPainter(splash_px)
            try:
                p.setPen(QColor("#ffffff"))
                fnt = QFont()
                fnt.setPointSize(22)
                fnt.setBold(True)
                p.setFont(fnt)
                p.drawText(
                    splash_px.rect(),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                    "RenLocalizer",
                )
            finally:
                p.end()

        splash = QSplashScreen(splash_px, Qt.WindowType.WindowStaysOnTopHint)
        splash.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        splash.show()
        app.processEvents()

        def _splash_msg(txt: str) -> None:
            splash.showMessage(
                txt,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                Qt.GlobalColor.white,
            )
            app.processEvents()

        _splash_msg("Loading RenLocalizer...")

        # ── Icon ──────────────────────────────────────────────────────────
        app_icon = QIcon()
        for icon_name in ["icon.png", "icon.ico"]:
            icon_path = resolve_asset(icon_name)
            if icon_path.exists():
                tmp = QIcon(str(icon_path))
                if not tmp.isNull():
                    app_icon = tmp
                    app.setWindowIcon(app_icon)
                    break

        # ── Backend ───────────────────────────────────────────────────────
        _splash_msg("Initializing backend...")

        from src.backend.app_backend import AppBackend

        backend = AppBackend(parent=app)

        # ── QML Engine ────────────────────────────────────────────────────
        _splash_msg("Starting interface...")

        engine = QQmlApplicationEngine(app)

        # Kapatma sırası: engine önce yok edilmeli
        _teardown_scheduled = [False]

        def _schedule_teardown() -> None:
            if not _teardown_scheduled[0]:
                _teardown_scheduled[0] = True
                engine.deleteLater()

        app.lastWindowClosed.connect(_schedule_teardown)
        app.aboutToQuit.connect(_schedule_teardown)
        # Persist in-memory settings (model name, URL, concurrency, profile...)
        # on quit; connected before teardown so it runs while backend is alive.
        app.aboutToQuit.connect(backend.persistSettingsOnExit)

        # Context property
        engine.rootContext().setContextProperty("appBackend", backend)

        def _on_object_created(obj, url) -> None:
            if obj is None:
                print(f"[FATAL] QML yüklenemedi: {url}")
                app.exit(-1)

        engine.objectCreated.connect(_on_object_created)

        # QML dosya yolu
        qml_path = resolve_asset("src/gui/qml/Main.qml")
        qml_root = resolve_asset("src/gui/qml")
        engine.addImportPath(str(qml_root))

        print(f"Loading UI: {qml_path}")
        engine.load(QUrl.fromLocalFile(str(qml_path)))

        if not engine.rootObjects():
            print("[ERROR] QML yüklenemedi.")
            splash.close()
            # Safe relaunch denemesi
            if should_attempt_qt_safe_relaunch(os.environ, sys.platform, graphics_bootstrap):
                safe_env = build_qt_safe_relaunch_env(os.environ, sys.platform)
                cmd = (
                    [sys.executable, *sys.argv[1:]]
                    if getattr(sys, "frozen", False)
                    else [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]
                )
                return subprocess.call(cmd, cwd=str(WORK_DIR), env=safe_env)
            return 1

        # ── Window hazırlığı ──────────────────────────────────────────────
        root_window = engine.rootObjects()[0]

        if not app_icon.isNull():
            root_window.setIcon(app_icon)

        root_window.show()
        app.processEvents()
        splash.close()

        # Smoke test helper: If we are running in CI smoke test mode, exit cleanly after initialization
        if os.environ.get("RENLOCALIZER_QT_SMOKE_TEST") == "1":
            logger.info("Smoke test mode detected, exiting cleanly as requested.")
            QTimer.singleShot(2000, app.quit)

        # Windows taskbar icon — natif yol
        ico_path = resolve_asset("icon.ico")
        if sys.platform == "win32" and ico_path.exists():
            def _apply_win_icon() -> None:
                try:
                    import ctypes
                    from ctypes import wintypes
                    user32 = ctypes.windll.user32
                    hwnd = int(root_window.winId())
                    if not hwnd:
                        return
                    ico_str = str(ico_path)

                    user32.LoadImageW.argtypes = [
                        wintypes.HINSTANCE,
                        wintypes.LPCWSTR,
                        wintypes.UINT,
                        ctypes.c_int,
                        ctypes.c_int,
                        wintypes.UINT,
                    ]
                    user32.LoadImageW.restype = wintypes.HANDLE

                    user32.SendMessageW.argtypes = [
                        wintypes.HWND,
                        wintypes.UINT,
                        wintypes.WPARAM,
                        wintypes.LPARAM,
                    ]
                    user32.SendMessageW.restype = wintypes.LPARAM

                    h_small = user32.LoadImageW(None, ico_str, 1, 16, 16, 0x10)
                    h_big = user32.LoadImageW(None, ico_str, 1, 32, 32, 0x10)
                    if h_small:
                        user32.SendMessageW(hwnd, 0x80, 0, h_small)
                    if h_big:
                        user32.SendMessageW(hwnd, 0x80, 1, h_big)
                except Exception:
                    pass

            _apply_win_icon()
            QTimer.singleShot(200, _apply_win_icon)
            QTimer.singleShot(500, _apply_win_icon)

        app.processEvents()
        exit_code = app.exec()

        # Scenegraph hatası → safe relaunch
        if exit_code == 213 and should_attempt_qt_safe_relaunch(
            os.environ, sys.platform, graphics_bootstrap
        ):
            safe_env = build_qt_safe_relaunch_env(os.environ, sys.platform)
            cmd = (
                [sys.executable, *sys.argv[1:]]
                if getattr(sys, "frozen", False)
                else [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]
            )
            return subprocess.call(cmd, cwd=str(WORK_DIR), env=safe_env)

        return exit_code

    except ImportError as e:
        msg = f"PyQt6 veya bağımlılık bulunamadı:\n{e}\n\npip install PyQt6 ile yükleyin."
        print(f"[FATAL] {msg}")
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, msg, "RenLocalizer — Hata", 0x10)
            except Exception:
                pass
        return 1

    except Exception as exc:
        logger.exception("Kritik başlatma hatası")
        print(f"[FATAL] {exc}")
        return 1


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[INFO] RenLocalizer application terminated by user (Ctrl+C).")
        sys.exit(0)
