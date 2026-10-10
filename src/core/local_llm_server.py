# -*- coding: utf-8 -*-
"""
Built-in GGUF runner — manages a local ``llama-server`` process (v2.8.17).

Lets a user translate with a ``.gguf`` model they already have on disk without
installing Ollama or LM Studio. The server speaks the OpenAI-compatible API, so
``LocalLLMTranslator`` talks to it unchanged: this module only acquires the
binary, starts/stops the process and reports its health.

Runtime acquisition is explicit, never automatic:
  * a binary the user points at (``local_llm_server_path``), or
  * an official llama.cpp release build downloaded on request into the app data
    directory, pinned to :data:`LLAMACPP_PINNED_BUILD` and verified against the
    SHA256 digest GitHub publishes for that asset.

Nothing here downloads models — the user supplies the ``.gguf`` file.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from src.utils.net import urlopen_direct

from src.core.constants import (
    LLAMACPP_DEFAULT_PORT,
    LLAMACPP_HEALTH_TIMEOUT,
    LLAMACPP_PINNED_BUILD,
    LLAMACPP_RELEASE_API,
    LLAMACPP_RELEASE_LIST_API,
    LLAMACPP_VARIANTS,
)
from src.utils.path_manager import get_data_path

logger = logging.getLogger(__name__)

# Suppress console window popup on Windows (same pattern as unrpyc_adapter).
_SUBPROCESS_NO_WINDOW: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW}
    if sys.platform == "win32"
    else {}
)

_USER_AGENT = "RenLocalizer"

#: Status values reported to the UI.
STATUS_STOPPED = "stopped"
STATUS_DOWNLOADING = "downloading"
STATUS_STARTING = "starting"
STATUS_READY = "ready"
STATUS_ERROR = "error"


class LlamaServerError(RuntimeError):
    """Raised when the runtime cannot be acquired or the server will not start."""


# ── Orphan prevention ────────────────────────────────────────────────────
# A hard kill of RenLocalizer (Task Manager, crash) never runs our shutdown
# hook, and a surviving llama-server keeps holding VRAM and its port. Three
# layers guard against that:
#   1. Windows: the child joins a Job Object with KILL_ON_JOB_CLOSE, so the
#      kernel terminates it as soon as our handle goes away.
#   2. Linux: prctl(PR_SET_PDEATHSIG, SIGKILL) does the same.
#   3. Every platform: a pid file lets the next launch clean up a leftover
#      process (the only defence on macOS).

def _pidfile_path() -> Path:
    return get_data_path() / "runtime" / "llama-server.pid"


def _process_image_name(pid: int) -> Optional[str]:
    """Best-effort image/command name for *pid*, or None when unknown."""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                capture_output=True, text=True, timeout=10, **_SUBPROCESS_NO_WINDOW,
            )
            first = (result.stdout or "").strip().splitlines()
            if not first or "No tasks" in first[0]:
                return None
            return first[0].split('","')[0].lstrip('"')
        if sys.platform.startswith("linux"):
            with open(f"/proc/{pid}/comm", encoding="utf-8") as fh:
                return fh.read().strip()
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True, text=True, timeout=10,
        )
        return (result.stdout or "").strip() or None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _write_pidfile(pid: int) -> None:
    try:
        path = _pidfile_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(pid), encoding="utf-8")
    except OSError as exc:
        logger.debug("Could not write llama-server pid file: %s", exc)


def _clear_pidfile() -> None:
    try:
        _pidfile_path().unlink(missing_ok=True)
    except OSError:
        pass


def cleanup_stale_server() -> bool:
    """Kills a llama-server left behind by a previous crash. Returns True if it did.

    The pid is only killed when the OS still reports it as a llama-server
    process, so a recycled pid belonging to something else is never touched.
    """
    _prune_old_logs()

    path = _pidfile_path()
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return False

    _clear_pidfile()
    if not raw.isdigit():
        return False

    pid = int(raw)
    name = _process_image_name(pid)
    if not name or "llama-server" not in name.lower():
        return False  # gone already, or the pid now belongs to something else

    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                           timeout=10, **_SUBPROCESS_NO_WINDOW)
        else:
            os.kill(pid, 9)
        logger.info("Terminated a llama-server (pid %s) left over from a previous run", pid)
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("Could not terminate stale llama-server %s: %s", pid, exc)
        return False


def _prune_old_logs(max_age_hours: float = 24.0) -> None:
    """Drops server logs a killed run could not clean up (recent ones are kept)."""
    cutoff = time.time() - max_age_hours * 3600
    try:
        for log in Path(tempfile.gettempdir()).glob("renlocalizer-llama-*.log"):
            try:
                if log.stat().st_mtime < cutoff:
                    log.unlink(missing_ok=True)
            except OSError:
                continue
    except OSError:
        pass


def _windows_kill_on_close_job():
    """Creates a Job Object whose closure kills every process inside it."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD
        )
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                        ("WriteOperationCount", ctypes.c_ulonglong),
                        ("OtherOperationCount", ctypes.c_ulonglong),
                        ("ReadTransferCount", ctypes.c_ulonglong),
                        ("WriteTransferCount", ctypes.c_ulonglong),
                        ("OtherTransferCount", ctypes.c_ulonglong)]

        class BASIC_LIMIT(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class EXTENDED_LIMIT(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC_LIMIT),
                        ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        info = EXTENDED_LIMIT()
        info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            job, 9, ctypes.byref(info), ctypes.sizeof(info)  # ExtendedLimitInformation
        ):
            kernel32.CloseHandle(job)
            return None
        return job
    except Exception as exc:  # ctypes/OS quirks must never block the feature
        logger.debug("Job Object unavailable: %s", exc)
        return None


def _assign_to_job(job, process) -> None:
    if not job or sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        if not kernel32.AssignProcessToJobObject(job, int(process._handle)):
            logger.debug("AssignProcessToJobObject failed (error %s)", ctypes.get_last_error())
    except Exception as exc:
        logger.debug("Could not assign llama-server to the Job Object: %s", exc)


def _linux_pdeathsig():
    """preexec_fn that asks the kernel to kill the child when we die."""
    try:
        import ctypes
        import signal as _signal

        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, _signal.SIGKILL)  # PR_SET_PDEATHSIG
    except Exception:
        pass


@dataclass(frozen=True)
class RuntimeAsset:
    """One downloadable llama.cpp release archive."""

    name: str
    url: str
    size: int
    sha256: str


def current_platform_key() -> str:
    """Returns the ``LLAMACPP_VARIANTS`` platform key for this machine."""
    machine = (platform.machine() or "").lower()
    arm = machine in ("arm64", "aarch64")
    if sys.platform == "win32":
        return "win-arm64" if arm else "win-x64"
    if sys.platform == "darwin":
        return "macos-arm64" if arm else "macos-x64"
    return "linux-arm64" if arm else "linux-x64"


def available_backends(platform_key: Optional[str] = None) -> Tuple[str, ...]:
    """Backends that have a release archive for this platform (UI dropdown)."""
    key = platform_key or current_platform_key()
    return tuple(
        backend for backend, table in LLAMACPP_VARIANTS.items() if key in table
    )


def resolve_asset_name(backend: str, platform_key: Optional[str] = None,
                       build: str = LLAMACPP_PINNED_BUILD) -> Optional[str]:
    """Release asset file name for *backend* on this platform, or None."""
    key = platform_key or current_platform_key()
    template = LLAMACPP_VARIANTS.get(backend, {}).get(key)
    if not template:
        # Fall back to CPU, which every desktop platform ships.
        template = LLAMACPP_VARIANTS.get("cpu", {}).get(key)
    return template.format(build=build) if template else None


def runtime_root() -> Path:
    """Directory holding downloaded llama.cpp runtimes."""
    return get_data_path() / "runtime" / "llamacpp"


def _server_exe_name() -> str:
    return "llama-server.exe" if sys.platform == "win32" else "llama-server"


def find_server_binary(directory: Path) -> Optional[Path]:
    """Finds ``llama-server`` anywhere under *directory* (archives vary in layout)."""
    if not directory.is_dir():
        return None
    target = _server_exe_name()
    direct = directory / target
    if direct.is_file():
        return direct
    for found in directory.rglob(target):
        if found.is_file():
            return found
    return None


def _fetch_release_assets(build: str, timeout: int = 20) -> Dict[str, RuntimeAsset]:
    """Reads the pinned release's asset table (name -> RuntimeAsset) from GitHub."""
    url = LLAMACPP_RELEASE_API.format(build=build)
    request = urllib.request.Request(
        url, headers={"User-Agent": _USER_AGENT, "Accept": "application/vnd.github+json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise LlamaServerError(f"Could not read llama.cpp release {build}: {exc}") from exc

    assets: Dict[str, RuntimeAsset] = {}
    for item in payload.get("assets", []):
        digest = str(item.get("digest") or "")
        assets[item.get("name", "")] = RuntimeAsset(
            name=item.get("name", ""),
            url=item.get("browser_download_url", ""),
            size=int(item.get("size") or 0),
            sha256=digest.split("sha256:", 1)[-1] if digest.startswith("sha256:") else "",
        )
    return assets


def _download_verified(asset: RuntimeAsset, dest: Path,
                       progress_cb: Optional[Callable[[int, int], None]] = None) -> None:
    """Downloads *asset* to *dest*, aborting unless the SHA256 digest matches."""
    if not asset.url:
        raise LlamaServerError(f"Release asset {asset.name} has no download URL")

    request = urllib.request.Request(asset.url, headers={"User-Agent": _USER_AGENT})
    digest = hashlib.sha256()
    downloaded = 0
    try:
        with urllib.request.urlopen(request, timeout=60) as response, open(dest, "wb") as out:
            total = int(response.headers.get("Content-Length") or asset.size or 0)
            while True:
                chunk = response.read(262144)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                downloaded += len(chunk)
                if progress_cb:
                    progress_cb(downloaded, total)
    except (urllib.error.URLError, OSError) as exc:
        dest.unlink(missing_ok=True)
        raise LlamaServerError(f"Download of {asset.name} failed: {exc}") from exc

    if asset.sha256 and digest.hexdigest() != asset.sha256:
        dest.unlink(missing_ok=True)
        raise LlamaServerError(
            f"Checksum mismatch for {asset.name} — the download was discarded."
        )


#: Written once an archive has been fully extracted, so an interrupted
#: download (crash, disk full, antivirus) is never mistaken for a usable
#: runtime just because llama-server.exe happens to be present.
_COMPLETE_MARKER = ".renlocalizer-complete"


def _is_complete_runtime(directory: Path) -> bool:
    return (directory / _COMPLETE_MARKER).is_file() and find_server_binary(directory) is not None


def _safe_extract(archive: Path, target_dir: Path) -> None:
    """Extracts *archive* into *target_dir*, refusing entries that escape it."""
    target_dir.mkdir(parents=True, exist_ok=True)
    resolved_target = target_dir.resolve()

    def _is_inside(member_name: str) -> bool:
        destination = (target_dir / member_name).resolve()
        return destination == resolved_target or destination.is_relative_to(resolved_target)

    if archive.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive) as zf:
            members = [m for m in zf.namelist() if _is_inside(m)]
            skipped = len(zf.namelist()) - len(members)
            zf.extractall(target_dir, members=members)
    else:
        with tarfile.open(archive) as tf:
            members = [m for m in tf.getmembers() if _is_inside(m.name)]
            skipped = len(tf.getmembers()) - len(members)
            tf.extractall(target_dir, members=members)
    if skipped:
        logger.warning(
            "Skipped %d archive entries that pointed outside the runtime directory", skipped
        )

    if sys.platform != "win32":
        binary = find_server_binary(target_dir)
        if binary:
            binary.chmod(binary.stat().st_mode | 0o755)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _port_is_free(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def _auto_port() -> int:
    """Stable default port when it is free, a random free one otherwise.

    A new random port on every launch made the server URL impossible to
    reuse from other tools and confused users who copied it from the log.
    """
    if _port_is_free(LLAMACPP_DEFAULT_PORT):
        return LLAMACPP_DEFAULT_PORT
    return _free_port()


class LlamaServerManager:
    """Owns at most one ``llama-server`` child process.

    The caller (AppBackend / CLI) is responsible for calling :meth:`stop` on
    shutdown; :meth:`start` is idempotent for an unchanged configuration.
    """

    def __init__(self, log_callback: Optional[Callable[[str, str], None]] = None) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.log_callback = log_callback
        self._process: Optional[subprocess.Popen] = None
        self._base_url: str = ""
        self._status: str = STATUS_STOPPED
        self._last_error: str = ""
        self._signature: Optional[tuple] = None
        # start/stop/download run from UI threads, the pipeline setup thread and
        # the CLI; without this a second click would spawn a second server.
        self._lock = threading.RLock()
        self._job = None  # Windows Job Object keeping the child tied to us
        self._log_path: Optional[Path] = None
        self._log_handle = None

    # ── state ────────────────────────────────────────────────────────────

    @property
    def status(self) -> str:
        if self._status == STATUS_READY and not self.is_running():
            self._status = STATUS_STOPPED
            self._base_url = ""
        return self._status

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def last_error(self) -> str:
        return self._last_error

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _emit(self, level: str, message: str) -> None:
        getattr(self.logger, "warning" if level == "warning" else "info")(message)
        if self.log_callback:
            try:
                self.log_callback(level, message)
            except Exception:  # never let UI logging break the server
                pass

    # ── runtime acquisition ──────────────────────────────────────────────

    def resolve_binary(self, user_path: str = "", backend: str = "vulkan") -> Optional[Path]:
        """User-provided binary first, then a previously downloaded runtime."""
        if user_path:
            candidate = Path(user_path).expanduser()
            if candidate.is_file():
                return candidate
            if candidate.is_dir():
                found = find_server_binary(candidate)
                if found:
                    return found
        root = runtime_root()
        target = root / f"{LLAMACPP_PINNED_BUILD}-{backend}"
        if _is_complete_runtime(target):
            return find_server_binary(target)
        # A fallback build may have been downloaded when the pinned one was gone.
        if root.is_dir():
            for candidate in sorted(root.glob(f"*-{backend}"), reverse=True):
                if _is_complete_runtime(candidate):
                    return find_server_binary(candidate)
        return None

    def _find_fallback_asset(self, backend: str, lookback: int = 30) -> Tuple[str, Optional[RuntimeAsset]]:
        """Newest release that still ships this variant (pinned build vanished)."""
        try:
            request = urllib.request.Request(
                LLAMACPP_RELEASE_LIST_API,
                headers={"User-Agent": _USER_AGENT, "Accept": "application/vnd.github+json"},
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                releases = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.logger.debug("Could not list llama.cpp releases: %s", exc)
            return "", None

        if not isinstance(releases, list):
            # GitHub answers errors (rate limit, outage) with an object.
            self.logger.debug("Unexpected release listing payload: %r", type(releases))
            return "", None

        for release in releases[:lookback]:
            tag = str(release.get("tag_name") or "")
            wanted = resolve_asset_name(backend, build=tag)
            for item in release.get("assets", []):
                if item.get("name") != wanted:
                    continue
                digest = str(item.get("digest") or "")
                return tag, RuntimeAsset(
                    name=item.get("name", ""),
                    url=item.get("browser_download_url", ""),
                    size=int(item.get("size") or 0),
                    sha256=digest.split("sha256:", 1)[-1] if digest.startswith("sha256:") else "",
                )
        return "", None

    def download_runtime(
        self,
        backend: str = "vulkan",
        progress_cb: Optional[Callable[[int, int], None]] = None,
        build: str = LLAMACPP_PINNED_BUILD,
    ) -> Path:
        """Downloads and extracts the pinned llama.cpp build. Explicit action only."""
        asset_name = resolve_asset_name(backend, build=build)
        if not asset_name:
            raise LlamaServerError(f"No llama.cpp build available for backend '{backend}'")
        # Serialised so a double click cannot run two downloads into one directory.
        self._lock.acquire()
        try:
            return self._download_runtime_locked(backend, progress_cb, build, asset_name)
        finally:
            self._lock.release()

    def _download_runtime_locked(self, backend, progress_cb, build, asset_name) -> Path:

        target_dir = runtime_root() / f"{build}-{backend}"
        if _is_complete_runtime(target_dir):
            return find_server_binary(target_dir)  # type: ignore[return-value]
        # A half-extracted directory (interrupted download) must not be reused.
        shutil.rmtree(target_dir, ignore_errors=True)

        self._status = STATUS_DOWNLOADING
        assets = _fetch_release_assets(build)
        asset = assets.get(asset_name)
        if asset is None:
            # The pinned nightly is gone or renamed: fall back to the newest
            # release that still carries this variant. The SHA256 always comes
            # from the release metadata, so the integrity check is unaffected.
            fallback_build, asset = self._find_fallback_asset(backend)
            if asset is None:
                self._status = STATUS_ERROR
                raise LlamaServerError(
                    f"Release {build} does not contain {asset_name}, and no newer "
                    "llama.cpp build offers it either. Point at your own "
                    "llama-server binary instead."
                )
            self._emit("warning", (
                f"[llama.cpp] Pinned build {build} no longer provides {asset_name}; "
                f"using {fallback_build} instead."
            ))
            target_dir = runtime_root() / f"{fallback_build}-{backend}"
            if _is_complete_runtime(target_dir):
                self._status = STATUS_STOPPED
                return find_server_binary(target_dir)  # type: ignore[return-value]
            shutil.rmtree(target_dir, ignore_errors=True)

        self._emit("info", f"[llama.cpp] Downloading {asset.name} ({asset.size // 1048576} MB)...")
        tmp_dir = Path(tempfile.mkdtemp(prefix="renlocalizer-llamacpp-"))
        archive = tmp_dir / asset.name
        try:
            _download_verified(asset, archive, progress_cb)
            self._emit("info", "[llama.cpp] Checksum verified, extracting...")
            _safe_extract(archive, target_dir)
        except Exception:
            self._status = STATUS_ERROR
            shutil.rmtree(target_dir, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        binary = find_server_binary(target_dir)
        if not binary:
            self._status = STATUS_ERROR
            shutil.rmtree(target_dir, ignore_errors=True)
            raise LlamaServerError(f"{asset.name} did not contain {_server_exe_name()}")

        try:
            (target_dir / _COMPLETE_MARKER).write_text(asset.sha256, encoding="utf-8")
        except OSError as exc:
            self.logger.debug("Could not write the completion marker: %s", exc)

        self._status = STATUS_STOPPED
        self._emit("info", f"[llama.cpp] Runtime ready: {binary}")
        return binary

    # ── process lifecycle ────────────────────────────────────────────────

    @staticmethod
    def build_command(
        binary: Path,
        model_path: str,
        port: int,
        gpu_layers: int = -1,
        ctx_size: int = 4096,
        parallel: int = 2,
    ) -> list:
        """llama-server argv (flags per the llama.cpp server documentation).

        ``-c`` is passed through as the user set it: verified against build
        b11120 that ``n_ctx_slot`` does not shrink with more ``-np`` slots
        (``-c 256`` reports ``n_ctx_slot = 128`` for both ``-np 1`` and
        ``-np 2``; the value comes from the model's training context). Do not
        multiply it by the slot count — that only inflates KV memory.
        """
        return [
            str(binary),
            "-m", str(model_path),
            "--host", "127.0.0.1",
            "--port", str(port),
            # llama-server accepts an exact count, 'auto' or 'all'; 'auto' (its own
            # default) offloads as much as the GPU can hold instead of risking OOM.
            "-ngl", "auto" if gpu_layers is None or gpu_layers < 0 else str(gpu_layers),
            "-c", str(max(512, int(ctx_size or 4096))),
            "-np", str(max(1, int(parallel or 1))),
        ]

    def _wait_for_health(self, port: int, timeout: float = LLAMACPP_HEALTH_TIMEOUT) -> bool:
        """Polls GET /health until it answers 200 (503 = still loading the model)."""
        url = f"http://127.0.0.1:{port}/health"
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._process is not None and self._process.poll() is not None:
                return False
            try:
                # Never through a system proxy: it would keep /health from
                # ever answering and the start would time out after minutes.
                with urlopen_direct(url, timeout=3) as response:
                    if response.status == 200:
                        return True
            except urllib.error.HTTPError as exc:
                if exc.code != 503:  # 503 = "Loading model"
                    self.logger.debug("llama-server health returned %s", exc.code)
            except (urllib.error.URLError, OSError):
                pass  # not listening yet
            time.sleep(0.5)
        return False

    def start(
        self,
        model_path: str,
        binary: Optional[Path] = None,
        user_path: str = "",
        backend: str = "vulkan",
        gpu_layers: int = -1,
        ctx_size: int = 4096,
        parallel: int = 2,
        port: int = 0,
    ) -> str:
        """Starts the server (or reuses a running one) and returns its base URL."""
        model = str(model_path or "").strip()
        if not model:
            raise LlamaServerError("No .gguf model selected")
        if not Path(model).is_file():
            raise LlamaServerError(f"GGUF model not found: {model}")

        signature = (model, backend, gpu_layers, ctx_size, parallel, port)
        with self._lock:
            if self.is_running() and self._signature == signature and self._base_url:
                return self._base_url
            if self.is_running():
                self.stop()

            server = binary or self.resolve_binary(user_path, backend)
            if not server:
                raise LlamaServerError(
                    "llama-server was not found. Download the runtime or point at an existing binary."
                )

            chosen_port = int(port) if port else _auto_port()
            command = self.build_command(server, model, chosen_port, gpu_layers, ctx_size, parallel)
            self._status = STATUS_STARTING
            self._last_error = ""
            self._emit("info", f"[llama.cpp] Starting server on port {chosen_port} ({Path(model).name})...")

            # The server's own output is the only useful diagnosis when it
            # refuses to start (missing Vulkan driver, unreadable model, port
            # already taken), so keep it instead of discarding it.
            popen_kwargs = dict(_SUBPROCESS_NO_WINDOW)
            try:
                self._log_path = Path(tempfile.gettempdir()) / f"renlocalizer-llama-{chosen_port}.log"
                self._log_handle = open(self._log_path, "w", encoding="utf-8", errors="replace")
                popen_kwargs["stdout"] = self._log_handle
                popen_kwargs["stderr"] = subprocess.STDOUT
            except OSError:
                self._log_path = None
                popen_kwargs["stdout"] = subprocess.DEVNULL
                popen_kwargs["stderr"] = subprocess.DEVNULL

            if sys.platform.startswith("linux"):
                popen_kwargs["preexec_fn"] = _linux_pdeathsig

            if self._job is None:
                self._job = _windows_kill_on_close_job()

            try:
                self._process = subprocess.Popen(
                    command,
                    cwd=str(server.parent),
                    **popen_kwargs,
                )
            except (OSError, ValueError) as exc:
                self._close_log()
                self._status = STATUS_ERROR
                self._last_error = str(exc)
                raise LlamaServerError(f"Could not launch llama-server: {exc}") from exc

            # Tie the child's lifetime to ours, and record it so a crashed run
            # can be cleaned up on the next launch.
            _assign_to_job(self._job, self._process)
            _write_pidfile(self._process.pid)

            if not self._wait_for_health(chosen_port):
                exit_code = self._process.poll() if self._process else None
                detail = self._read_log_tail()
                self.stop()
                self._status = STATUS_ERROR
                self._last_error = (
                    f"llama-server exited with code {exit_code}"
                    if exit_code is not None
                    else "llama-server did not become ready in time"
                )
                if detail:
                    self._last_error = f"{self._last_error} — {detail}"
                raise LlamaServerError(self._last_error)

            self._signature = signature
            self._base_url = f"http://127.0.0.1:{chosen_port}/v1"
            self._status = STATUS_READY
            self._emit("info", f"[llama.cpp] Server ready: {self._base_url}")
            return self._base_url

    def _close_log(self, keep: bool = False) -> None:
        """Closes the server log; removes it unless it may still be needed.

        A clean shutdown leaves nothing behind, but a log from a server that
        died on its own is kept so the crash can still be investigated.
        """
        handle, self._log_handle = self._log_handle, None
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass
        if not keep and self._log_path:
            try:
                self._log_path.unlink(missing_ok=True)
            except OSError:
                pass
            self._log_path = None

    def _read_log_tail(self, lines: int = 6) -> str:
        """Last few lines the server printed — the actual reason it failed."""
        if not self._log_path:
            return ""
        try:
            if self._log_handle is not None:
                self._log_handle.flush()
            content = self._log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        tail = [line.strip() for line in content.strip().splitlines() if line.strip()]
        return " | ".join(tail[-lines:])[:500]

    def stop(self, timeout: float = 5.0) -> None:
        """Terminates the child process. Safe to call repeatedly."""
        with self._lock:
            process, self._process = self._process, None
            self._base_url = ""
            self._signature = None
            if self._status != STATUS_ERROR:
                self._status = STATUS_STOPPED
            if process is None or process.poll() is not None:
                # It exited by itself (crash / OOM): keep the log for diagnosis.
                self._close_log(keep=process is not None)
                _clear_pidfile()
                return
            try:
                process.terminate()
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=timeout)
                self._emit("info", "[llama.cpp] Server stopped.")
            except Exception as exc:  # process already gone / permission issues
                self.logger.debug("llama-server stop notice: %s", exc)
            finally:
                self._close_log()
                _clear_pidfile()
