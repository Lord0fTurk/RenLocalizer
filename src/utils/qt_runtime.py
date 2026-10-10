"""
Qt runtime bootstrap helpers.

Keeps Qt Quick startup choices deterministic and testable across platforms.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import importlib.util
import json
import logging
import os
import subprocess
import sys
from collections.abc import Iterable, MutableMapping
from dataclasses import dataclass
from pathlib import Path


SAFE_HIDPI_SCALE_THRESHOLD = 125
_GRAPHICS_OVERRIDE_KEYS = (
    "QSG_RHI_BACKEND",
    "QT_OPENGL",
    "QSG_RHI_PREFER_SOFTWARE_RENDERER",
    "QT_QUICK_BACKEND",
)
_PLATFORM_OVERRIDE_KEY = "QT_QPA_PLATFORM"
_PLATFORM_HINT_KEY = "RENLOCALIZER_QT_PLATFORM_HINT"
_RECOVERY_ATTEMPT_KEY = "RENLOCALIZER_QT_RECOVERY_ATTEMPT"
_FAILED_MODES_KEY = "RENLOCALIZER_QT_FAILED_MODES"
# "raster" = Qt Quick software scene graph: no OpenGL/D3D at all. Last resort
# on Windows when neither the GPU driver nor opengl32sw.dll can create a GL
# context (RDP sessions, VMs, legacy or broken drivers).
_VALID_RENDER_MODES = {"auto", "native", "opengl", "software", "raster"}
# Windows recovery order: desktop GL -> Mesa llvmpipe (opengl32sw.dll) -> raster.
WINDOWS_FALLBACK_CHAIN = ("opengl", "software", "raster")
GRAPHICS_STATE_FILENAME = "graphics_state.json"
# Exit code the launcher uses to request a safe-mode relaunch.
SCENEGRAPH_FAILURE_EXIT_CODE = 213
_VALID_PLATFORM_MODES = {
    "auto",
    "native",
    "xcb",
    "wayland",
    "xcb;wayland",
    "wayland;xcb",
    "offscreen",
    "minimal",
    "cocoa",
}


@dataclass(frozen=True)
class QtGraphicsBootstrapResult:
    """Describes the effective Qt graphics bootstrap decision."""

    mode: str
    scale_percent: int
    applied: dict[str, str]
    reason: str
    graphics_api: str | None = None
    platform_plugin: str | None = None


def detect_windows_scale_percent() -> int:
    """Return the system DPI scale percentage on Windows."""
    if sys.platform != "win32":
        return 100

    try:
        user32 = ctypes.windll.user32
        if hasattr(user32, "GetDpiForSystem"):
            dpi = int(user32.GetDpiForSystem())
            if dpi > 0:
                return max(100, round((dpi / 96) * 100))

        hdc = user32.GetDC(0)
        try:
            if hdc:
                gdi32 = ctypes.windll.gdi32
                log_pixels_x = 88
                dpi = int(gdi32.GetDeviceCaps(hdc, log_pixels_x))
                if dpi > 0:
                    return max(100, round((dpi / 96) * 100))
        finally:
            if hdc:
                user32.ReleaseDC(0, hdc)
    except Exception:
        return 100

    return 100


def _normalize_requested_mode(requested_mode: str | None) -> str:
    normalized_mode = (requested_mode or "auto").strip().lower()
    if normalized_mode not in _VALID_RENDER_MODES:
        return "auto"
    return normalized_mode


def _normalize_requested_platform(requested_platform: str | None) -> str:
    normalized_platform = (requested_platform or "auto").strip().lower()
    if normalized_platform not in _VALID_PLATFORM_MODES:
        return "auto"
    return normalized_platform


# ── Persistent graphics failure state ─────────────────────────────────────
# A mode that failed once is skipped on later launches, so the user does not
# hit the same OpenGL error dialog every start. The state is tied to the app
# version: an update (new Qt, new drivers bundled) retries the full chain.

def default_graphics_state_path() -> Path | None:
    try:
        from src.utils.path_manager import get_data_path
        return get_data_path() / GRAPHICS_STATE_FILENAME
    except Exception:
        return None


def load_failed_graphics_modes(
    state_path: Path | None,
    app_version: str | None = None,
) -> set[str]:
    if state_path is None:
        return set()
    try:
        data = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except Exception:
        return set()
    if not isinstance(data, dict):
        return set()
    if app_version and data.get("app_version") not in (None, app_version):
        return set()
    modes = data.get("failed_modes") or []
    return {m for m in modes if isinstance(m, str) and m in _VALID_RENDER_MODES}


def remember_failed_graphics_mode(
    state_path: Path | None,
    mode: str,
    app_version: str | None = None,
) -> bool:
    """Record *mode* as failed. Returns False when the state cannot be written."""
    if state_path is None or mode not in _VALID_RENDER_MODES:
        return False
    failed = load_failed_graphics_modes(state_path, app_version)
    failed.add(mode)
    payload = {"app_version": app_version, "failed_modes": sorted(failed)}
    try:
        state_path = Path(state_path)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def parse_failed_modes_env(env: MutableMapping[str, str]) -> set[str]:
    raw = env.get(_FAILED_MODES_KEY, "")
    return {m.strip().lower() for m in raw.split(",") if m.strip().lower() in _VALID_RENDER_MODES}


def windows_software_gl_available() -> bool:
    """True when opengl32sw.dll (Mesa llvmpipe) can be found for QT_OPENGL=software."""
    if sys.platform != "win32":
        return False
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates += [Path(meipass), Path(meipass) / "PyQt6" / "Qt6" / "bin"]
    candidates.append(Path(sys.executable).parent)
    try:
        spec = importlib.util.find_spec("PyQt6")
        if spec and spec.submodule_search_locations:
            for loc in spec.submodule_search_locations:
                candidates.append(Path(loc) / "Qt6" / "bin")
    except Exception:
        pass
    return any((c / "opengl32sw.dll").is_file() for c in candidates)


def next_windows_render_mode(
    start_mode: str,
    failed_modes: Iterable[str] = (),
    software_gl_available: bool = True,
) -> str:
    """First mode of the Windows chain at/after *start_mode* that has not failed."""
    failed = set(failed_modes)
    if not software_gl_available:
        failed.add("software")
    chain = WINDOWS_FALLBACK_CHAIN
    start = chain.index(start_mode) if start_mode in chain else 0
    for mode in chain[start:]:
        if mode not in failed:
            return mode
    return chain[-1]


def _probe_linux_glx_available() -> bool:
    """Best-effort check whether GLX context creation is likely to succeed.

    Attempts two complementary probes:
    1. Call ``glXQueryExtension`` via *libGL.so.1* — this verifies the
       driver-level GLX extension is present for the current ``$DISPLAY``.
    2. Run ``glxinfo`` as a subprocess — catches driver/DRI problems that
       ``glXQueryExtension`` alone might miss.

    Returns ``True`` when GLX appears functional, ``False`` otherwise.
    The function is intentionally conservative: any error → ``False``.
    """
    logger = logging.getLogger("RenLocalizer")

    # This probe only makes sense on an actual Linux host.  When unit tests
    # simulate platform_name="linux" on Windows/macOS the probe would always
    # fail (no libGL / libX11) and force software mode incorrectly.
    if sys.platform != "linux":
        return True

    # Probe 1: ctypes — fast, in-process
    try:
        display_env = os.environ.get("DISPLAY", "")
        if not display_env:
            logger.debug("GLX probe: no $DISPLAY set, GLX unavailable")
            return False

        libgl_name = ctypes.util.find_library("GL")
        if not libgl_name:
            logger.debug("GLX probe: libGL not found")
            return False

        libgl = ctypes.cdll.LoadLibrary(libgl_name)

        # Try loading libX11 for XOpenDisplay
        libx11_name = ctypes.util.find_library("X11")
        if not libx11_name:
            logger.debug("GLX probe: libX11 not found")
            return False

        libx11 = ctypes.cdll.LoadLibrary(libx11_name)
        libx11.XOpenDisplay.restype = ctypes.c_void_p
        libx11.XOpenDisplay.argtypes = [ctypes.c_char_p]

        dpy = libx11.XOpenDisplay(display_env.encode("utf-8") if display_env else None)
        if not dpy:
            logger.debug("GLX probe: XOpenDisplay failed for %r", display_env)
            return False

        try:
            # int glXQueryExtension(Display *dpy, int *errorBase, int *eventBase)
            glx_query = getattr(libgl, "glXQueryExtension", None)
            if glx_query is None:
                logger.debug("GLX probe: glXQueryExtension symbol not found")
                return False

            glx_query.restype = ctypes.c_int
            glx_query.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_int),
            ]
            error_base = ctypes.c_int(0)
            event_base = ctypes.c_int(0)
            result = glx_query(dpy, ctypes.byref(error_base), ctypes.byref(event_base))
            if not result:
                logger.debug("GLX probe: glXQueryExtension returned 0 (no GLX)")
                return False
        finally:
            libx11.XCloseDisplay(dpy)

        logger.debug("GLX probe: glXQueryExtension succeeded")
    except Exception as exc:
        logger.debug("GLX probe (ctypes) failed: %s", exc)
        return False

    # Probe 2: glxinfo subprocess — catches DRI/Mesa mismatches
    try:
        proc = subprocess.run(
            ["glxinfo"],
            capture_output=True,
            timeout=5,
            env={**os.environ, "DISPLAY": display_env},
        )
        if proc.returncode != 0:
            stderr_snippet = (proc.stderr or b"")[:200].decode("utf-8", errors="replace")
            logger.debug("GLX probe: glxinfo exited %d: %s", proc.returncode, stderr_snippet)
            return False
    except FileNotFoundError:
        # glxinfo not installed — rely on ctypes probe alone
        logger.debug("GLX probe: glxinfo not found, trusting ctypes result")
    except Exception as exc:
        logger.debug("GLX probe (glxinfo) failed: %s", exc)
        return False

    return True


def select_qt_render_mode(
    platform_name: str,
    scale_percent: int,
    requested_mode: str | None = None,
    frozen: bool = False,
    failed_modes: Iterable[str] = (),
    software_gl_available: bool = True,
) -> str:
    """Choose the safest render mode for the current platform and environment."""
    normalized_mode = _normalize_requested_mode(requested_mode)
    if normalized_mode != "auto":
        return normalized_mode

    if platform_name == "win32":
        start = "software" if scale_percent >= SAFE_HIDPI_SCALE_THRESHOLD else "opengl"
        return next_windows_render_mode(start, failed_modes, software_gl_available)

    # Linux frozen builds: proactively verify GLX so we avoid a fatal SIGABRT
    # when the bundled Qt XCB-GLX integration plugin cannot create a context.
    if platform_name == "linux" and frozen:
        if not _probe_linux_glx_available():
            return "software"

    return "native"


def select_windows_qt_render_mode(scale_percent: int, requested_mode: str | None = None) -> str:
    """Choose the safest render mode for the current Windows DPI environment."""
    return select_qt_render_mode(
        platform_name="win32",
        scale_percent=scale_percent,
        requested_mode=requested_mode,
    )


def select_qt_platform_plugin(
    env: MutableMapping[str, str],
    platform_name: str,
    requested_platform: str | None = None,
    frozen: bool = False,
) -> str | None:
    """Choose a conservative Qt platform plugin override when beneficial."""
    normalized_platform = _normalize_requested_platform(requested_platform)
    if normalized_platform == "native":
        return None
    if normalized_platform != "auto":
        return normalized_platform

    if platform_name != "linux":
        return None

    has_display = bool(env.get("DISPLAY"))
    has_wayland = bool(env.get("WAYLAND_DISPLAY")) or env.get("XDG_SESSION_TYPE", "").lower() == "wayland"

    # AppImages commonly trip over Wayland/EGL. Prefer XWayland first when both
    # transports are available, but stay native on pure X11 or pure Wayland.
    if has_display and has_wayland and frozen:
        return "xcb;wayland"

    return None


def resolve_qt_graphics_api(platform_name: str, mode: str) -> str | None:
    """Map the selected mode to the early QQuickWindow graphics API override."""
    if mode == "native":
        return None

    if mode == "opengl":
        return "opengl"

    if mode == "raster":
        return "software"

    if mode != "software":
        return None

    if platform_name == "win32":
        # Windows HiDPI fallback intentionally keeps using OpenGL, but with the
        # software rasterizer DLL path for black-window resilience.
        return "opengl"

    return "software"


def _apply_qt_debug_settings(
    env: MutableMapping[str, str],
    applied: dict[str, str],
) -> None:
    if env.get("RENLOCALIZER_QT_DEBUG", "0") == "1" and not env.get("QSG_INFO"):
        env["QSG_INFO"] = "1"
        applied["QSG_INFO"] = "1"


def configure_qt_graphics_environment(
    env: MutableMapping[str, str] | None = None,
    platform_name: str | None = None,
    scale_percent: int | None = None,
    frozen: bool | None = None,
    failed_modes: Iterable[str] | None = None,
    software_gl_available: bool | None = None,
) -> QtGraphicsBootstrapResult:
    """
    Apply conservative Qt Quick rendering defaults across supported platforms.

    Strategy:
    - Respect explicit Qt rendering overrides from the environment.
    - Default to OpenGL on Windows to avoid D3D11-specific black window issues.
    - Escalate to software OpenGL on HiDPI Windows systems where the issue is
      most common.
    - Keep Linux/macOS native by default, but allow conservative platform/plugin
      overrides and a true software scene graph fallback when requested.
    """
    target_env = env if env is not None else os.environ
    effective_platform = platform_name or sys.platform
    effective_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    actual_scale = scale_percent if scale_percent is not None else detect_windows_scale_percent()
    applied: dict[str, str] = {}

    existing_platform_plugin = target_env.get(_PLATFORM_OVERRIDE_KEY)

    if any(target_env.get(key) for key in _GRAPHICS_OVERRIDE_KEYS):
        _apply_qt_debug_settings(target_env, applied)
        return QtGraphicsBootstrapResult(
            mode="native",
            scale_percent=actual_scale,
            applied=applied,
            reason="qt graphics env already overridden",
            graphics_api=None,
            platform_plugin=existing_platform_plugin,
        )

    requested_mode = target_env.get("RENLOCALIZER_QT_RENDER_MODE", "")
    requested_platform = target_env.get("RENLOCALIZER_QT_PLATFORM", "")
    requested_platform_hint = target_env.get(_PLATFORM_HINT_KEY, "")
    effective_requested_platform = requested_platform or requested_platform_hint
    effective_failed = set(failed_modes or ()) | parse_failed_modes_env(target_env)
    if effective_platform == "win32" and software_gl_available is None:
        software_gl_available = windows_software_gl_available()
    effective_mode = select_qt_render_mode(
        platform_name=effective_platform,
        scale_percent=actual_scale,
        requested_mode=requested_mode,
        frozen=effective_frozen,
        failed_modes=effective_failed,
        software_gl_available=True if software_gl_available is None else software_gl_available,
    )
    platform_plugin = existing_platform_plugin or select_qt_platform_plugin(
        env=target_env,
        platform_name=effective_platform,
        requested_platform=effective_requested_platform,
        frozen=effective_frozen,
    )
    graphics_api = resolve_qt_graphics_api(
        platform_name=effective_platform,
        mode=effective_mode,
    )

    if not existing_platform_plugin and platform_plugin:
        target_env[_PLATFORM_OVERRIDE_KEY] = platform_plugin
        applied[_PLATFORM_OVERRIDE_KEY] = platform_plugin

    if graphics_api == "opengl":
        target_env["QSG_RHI_BACKEND"] = "opengl"
        applied["QSG_RHI_BACKEND"] = "opengl"
        if effective_platform == "win32" and effective_mode == "software":
            target_env["QT_OPENGL"] = "software"
            applied["QT_OPENGL"] = "software"
    elif graphics_api == "software":
        target_env["QT_QUICK_BACKEND"] = "software"
        applied["QT_QUICK_BACKEND"] = "software"

    # After a recorded failure a stale/corrupt shader binary cache is a common
    # culprit on Intel/AMD drivers; stop Qt from reusing it.
    if effective_failed and not target_env.get("QT_DISABLE_SHADER_DISK_CACHE"):
        target_env["QT_DISABLE_SHADER_DISK_CACHE"] = "1"
        applied["QT_DISABLE_SHADER_DISK_CACHE"] = "1"

    _apply_qt_debug_settings(target_env, applied)

    return QtGraphicsBootstrapResult(
        mode=effective_mode,
        scale_percent=actual_scale,
        applied=applied,
        reason=(
            "automatic safe graphics bootstrap"
            if _normalize_requested_mode(requested_mode) == "auto"
            and _normalize_requested_platform(requested_platform) == "auto"
            else "requested render mode"
        ),
        graphics_api=graphics_api,
        platform_plugin=platform_plugin,
    )


def configure_windows_qt_graphics_environment(
    env: MutableMapping[str, str] | None = None,
    platform_name: str | None = None,
    scale_percent: int | None = None,
    frozen: bool | None = None,
) -> QtGraphicsBootstrapResult:
    """Backward-compatible wrapper around the platform-generic bootstrap."""
    return configure_qt_graphics_environment(
        env=env,
        platform_name=platform_name,
        scale_percent=scale_percent,
        frozen=frozen,
    )


def should_attempt_qt_safe_relaunch(
    env: MutableMapping[str, str] | None = None,
    platform_name: str | None = None,
    bootstrap: QtGraphicsBootstrapResult | None = None,
) -> bool:
    """Return whether the launcher should try a one-shot safe-mode relaunch."""
    target_env = env if env is not None else os.environ
    effective_platform = platform_name or sys.platform
    auto_applied_keys = set(bootstrap.applied) if bootstrap else set()

    if effective_platform not in {"linux", "darwin", "win32"}:
        return False

    try:
        attempts = int(target_env.get(_RECOVERY_ATTEMPT_KEY) or 0)
    except ValueError:
        attempts = 1
    # Windows walks the whole chain (opengl -> software -> raster); the other
    # platforms have a single software step.
    max_attempts = len(WINDOWS_FALLBACK_CHAIN) - 1 if effective_platform == "win32" else 1
    if attempts >= max_attempts:
        return False

    if any(target_env.get(key) for key in _GRAPHICS_OVERRIDE_KEYS if key not in auto_applied_keys):
        return False

    if target_env.get(_PLATFORM_OVERRIDE_KEY) and _PLATFORM_OVERRIDE_KEY not in auto_applied_keys:
        return False

    if _normalize_requested_mode(target_env.get("RENLOCALIZER_QT_RENDER_MODE")) != "auto":
        return False

    if _normalize_requested_platform(target_env.get("RENLOCALIZER_QT_PLATFORM")) != "auto":
        return False

    if effective_platform == "win32":
        # Nothing left to fall back to once the GL-free raster path failed.
        return not (bootstrap and bootstrap.mode == WINDOWS_FALLBACK_CHAIN[-1])

    if bootstrap and bootstrap.graphics_api == "software":
        return False

    return True


def build_qt_safe_relaunch_env(
    env: MutableMapping[str, str] | None = None,
    platform_name: str | None = None,
    failed_mode: str | None = None,
) -> dict[str, str]:
    """Build a sanitized environment for a Qt safe-mode relaunch."""
    source_env = env if env is not None else os.environ
    effective_platform = platform_name or sys.platform
    safe_env = dict(source_env)

    for key in (*_GRAPHICS_OVERRIDE_KEYS, _PLATFORM_OVERRIDE_KEY, "QSG_INFO"):
        safe_env.pop(key, None)

    try:
        attempts = int(source_env.get(_RECOVERY_ATTEMPT_KEY) or 0)
    except ValueError:
        attempts = 0
    safe_env[_RECOVERY_ATTEMPT_KEY] = str(attempts + 1)

    if effective_platform == "win32":
        # Stay in "auto" so the child picks the next untried chain step; the
        # env copy of the failed modes works even if the state file is not
        # writable.
        failed = parse_failed_modes_env(source_env)
        if failed_mode:
            failed.add(failed_mode)
        safe_env[_FAILED_MODES_KEY] = ",".join(sorted(failed))
        safe_env.pop("RENLOCALIZER_QT_RENDER_MODE", None)
        return safe_env

    safe_env["RENLOCALIZER_QT_RENDER_MODE"] = "software"
    safe_env.pop("RENLOCALIZER_QT_PLATFORM", None)
    safe_env.pop(_PLATFORM_HINT_KEY, None)

    if effective_platform == "linux":
        if source_env.get("DISPLAY"):
            safe_env[_PLATFORM_OVERRIDE_KEY] = "xcb"
        elif source_env.get("WAYLAND_DISPLAY") or source_env.get("XDG_SESSION_TYPE", "").lower() == "wayland":
            safe_env[_PLATFORM_OVERRIDE_KEY] = "wayland"

    return safe_env
