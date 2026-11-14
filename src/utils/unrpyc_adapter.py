"""
Adapter for .rpyc decompilation in Ren'Py games.

Provides a unified interface with automatic fallback for decompiling
compiled .rpyc/.rpymc files back into readable .rpy source files.

Decompiled .rpy files are written to a system temp directory and fed
back through the regex-based RenPyParser for complementary text extraction.
This is in addition to (not replacing) the direct AST-based rpyc_reader.

Decompiler priority:
  1. unrpyc library  (decompiler module, imported directly)
  2. unrpyc subprocess (python -m decompiler / unrpyc.py in PATH)
  3. rpycdec         (pip install rpycdec — PyPI fallback)
  4. No decompiler   (graceful skip — rpyc_reader still runs)

Usage:
    adapter = UnrpycAdapter()
    with adapter.decompile_to_temp(rpyc_files, source_root) as temp_dir:
        rpy_files = list(Path(temp_dir).rglob("*.rpy"))
        # feed rpy_files through RenPyParser ...
"""

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterator, List, Optional, Tuple
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Suppress console window popup on Windows when spawning subprocesses.
# CREATE_NO_WINDOW is Windows-only; on other platforms we use an empty dict.
_SUBPROCESS_NO_WINDOW: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW}
    if sys.platform == "win32"
    else {}
)

# ---------------------------------------------------------------------------
# Availability detection (cached at module level)
# ---------------------------------------------------------------------------

_METHOD: Optional[str] = None   # "module" | "subprocess" | "rpycdec" | None

def _detect_method() -> Optional[str]:
    """Detect which decompilation method is usable. Cached after first call."""
    global _METHOD
    if _METHOD is not None:
        return _METHOD

    # 1. Try direct module import (unrpyc installed from source / git)
    try:
        # unrpyc exposes its decompiler package when installed
        import decompiler  # type: ignore[import-untyped]
        _ = decompiler.renpycompat  # probe a submodule to confirm full install
        _METHOD = "module"
        logger.debug("unrpyc_adapter: using decompiler module (direct import)")
        return _METHOD
    except (ImportError, AttributeError):
        pass

    # 2. Try subprocess: `python -m decompiler` or `unrpyc` script in PATH
    # IMPORTANT: In a PyInstaller frozen build sys.executable points to the
    # packaged app itself (e.g. RenLocalizer.exe), not a Python interpreter.
    # Spawning it with "-m decompiler" would open a second app window, so we
    # skip the subprocess_module probe entirely when frozen.
    _py = sys.executable
    _is_frozen = getattr(sys, "frozen", False)
    # Prefer programmatic rpycdec if available (more controllable, runs in-process)
    try:
        import rpycdec  # type: ignore[import-untyped]
        _ = rpycdec.decompile_file if hasattr(rpycdec, "decompile_file") else rpycdec.decompile
        _METHOD = "rpycdec"
        logger.debug("unrpyc_adapter: using rpycdec library")
        return _METHOD
    except (ImportError, AttributeError):
        pass

    # 3. Try subprocess: `python -m decompiler` or `unrpyc` script in PATH
    # IMPORTANT: In a PyInstaller frozen build sys.executable points to the
    # packaged app itself (e.g. RenLocalizer.exe), not a Python interpreter.
    # Spawning it with "-m decompiler" would open a second app window, so we
    # skip the subprocess_module probe entirely when frozen.
    _py = sys.executable
    _is_frozen = getattr(sys, "frozen", False)
    if not _is_frozen:
        try:
            result = subprocess.run(
                [_py, "-m", "decompiler", "--help"],
                capture_output=True, timeout=8, **_SUBPROCESS_NO_WINDOW
            )
            if result.returncode == 0 or b"usage" in result.stdout.lower():
                _METHOD = "subprocess_module"
                logger.debug("unrpyc_adapter: using subprocess (-m decompiler)")
                return _METHOD
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    try:
        result = subprocess.run(
            ["unrpyc", "--help"],
            capture_output=True, timeout=8, **_SUBPROCESS_NO_WINDOW
        )
        if result.returncode == 0 or b"usage" in result.stdout.lower():
            _METHOD = "subprocess_script"
            logger.debug("unrpyc_adapter: using subprocess (unrpyc script)")
            return _METHOD
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    _METHOD = ""   # Empty string = "detected, nothing available"
    logger.debug("unrpyc_adapter: no decompiler available")
    return None


def is_available() -> bool:
    """Return True if at least one decompiler backend is usable."""
    return bool(_detect_method())


def backend_name() -> str:
    """Human-readable name of the active backend, or 'none'."""
    m = _detect_method()
    return {"module": "unrpyc (module)", "subprocess_module": "unrpyc (subprocess -m decompiler)",
            "subprocess_script": "unrpyc (subprocess script)", "rpycdec": "rpycdec", "": "none", None: "none"}.get(m, "none")


# ---------------------------------------------------------------------------
# Core decompilation helpers
# ---------------------------------------------------------------------------

def _decompile_via_module(rpyc_path: Path, out_dir: Path) -> bool:
    """Decompile using the `decompiler` Python module (unrpyc installed directly)."""
    try:
        import decompiler  # type: ignore
        # unrpyc v2 API: decompile_rpyc(filename, overwrite=False, try_harder=False, ...)
        out_rpy = out_dir / (rpyc_path.stem + ".rpy")
        decompiler.decompile_rpyc(str(rpyc_path), overwrite=True,
                                   out_filename=str(out_rpy))
        return out_rpy.exists() and out_rpy.stat().st_size > 0
    except Exception as exc:
        logger.debug(f"unrpyc module decompile failed for {rpyc_path.name}: {exc}")
        return False


def _decompile_via_subprocess(rpyc_path: Path, out_dir: Path, method: str) -> bool:
    """Decompile using unrpyc as subprocess."""
    _py = sys.executable
    # In a frozen (PyInstaller) build sys.executable is the packaged app, not
    # a Python interpreter.  subprocess_module must never be reached when frozen
    # (it is skipped during detection), but guard here as a safety net.
    if method == "subprocess_module" and getattr(sys, "frozen", False):
        logger.debug("unrpyc_adapter: subprocess_module skipped in frozen build")
        return False
    if method == "subprocess_module":
        cmd = [_py, "-m", "decompiler", "-c", str(rpyc_path)]
    else:  # subprocess_script
        cmd = ["unrpyc", "-c", str(rpyc_path)]

    try:
        # Run decompiler; it writes file.rpy next to file.rpyc by default
        subprocess.run(cmd, capture_output=True, timeout=60, cwd=str(out_dir), **_SUBPROCESS_NO_WINDOW)
        # The decompiler writes to cwd by default; look for the output
        out_rpy = out_dir / (rpyc_path.stem + ".rpy")
        if not out_rpy.exists():
            # Also check same directory as input (some versions write next to the .rpyc)
            candidate = rpyc_path.parent / (rpyc_path.stem + ".rpy")
            if candidate.exists():
                shutil.copy2(candidate, out_rpy)
                # SAFETY: Remove the stray .rpy from the game directory.
                # If it stays next to the .rpyc, Ren'Py loads both and may crash
                # with duplicate label / re-parse errors on some games.
                try:
                    candidate.unlink()
                except OSError as _del_err:
                    # Deletion failed (permissions, locked file, etc.).
                    # The stray .rpy is still in game/ — log a warning and treat
                    # this decompile attempt as failed so the file is not used.
                    logger.warning(
                        f"Could not remove stray decompiled file '{candidate}': {_del_err}. "
                        f"Skipping this file to avoid game breakage."
                    )
                    try:
                        out_rpy.unlink(missing_ok=True)  # discard the temp copy too
                    except OSError:
                        pass
                    return False
        return out_rpy.exists() and out_rpy.stat().st_size > 0
    except (subprocess.TimeoutExpired, OSError, Exception) as exc:
        logger.debug(f"unrpyc subprocess failed for {rpyc_path.name}: {exc}")
        return False


def _decompile_via_rpycdec(rpyc_path: Path, out_dir: Path) -> bool:
    """Decompile using rpycdec (pip install rpycdec)."""
    try:
        import rpycdec  # type: ignore
        out_rpy = out_dir / (rpyc_path.stem + ".rpy")
        # rpycdec programmatic API: prefer decompile_file, fall back to decompile
        if hasattr(rpycdec, "decompile_file"):
            rpycdec.decompile_file(str(rpyc_path), str(out_rpy))
        elif hasattr(rpycdec, "decompile"):
            rpycdec.decompile(str(rpyc_path), str(out_rpy))
        else:
            # Fallback: call via subprocess (rpycdec installs a CLI entrypoint)
            subprocess.run(
                [sys.executable, "-m", "rpycdec", "decompile", str(rpyc_path)],
                capture_output=True, timeout=60, cwd=str(out_dir), **_SUBPROCESS_NO_WINDOW
            )
            # rpycdec writes to same dir as input by default
            candidate = rpyc_path.parent / (rpyc_path.stem + ".rpy")
            if candidate.exists():
                shutil.copy2(candidate, out_rpy)
                # SAFETY: Remove the stray .rpy from the game directory.
                try:
                    candidate.unlink()
                except OSError as _del_err:
                    logger.warning(
                        f"Could not remove stray decompiled file '{candidate}': {_del_err}. "
                        f"Skipping this file to avoid game breakage."
                    )
                    try:
                        out_rpy.unlink(missing_ok=True)
                    except OSError:
                        pass
                    return False
        return out_rpy.exists() and out_rpy.stat().st_size > 0
    except Exception as exc:
        logger.debug(f"rpycdec decompile failed for {rpyc_path.name}: {exc}")
        return False


def _decompile_single(rpyc_path: Path, out_dir: Path, method: str) -> bool:
    """Dispatch to correct backend for one file."""
    if method == "module":
        return _decompile_via_module(rpyc_path, out_dir)
    elif method in ("subprocess_module", "subprocess_script"):
        return _decompile_via_subprocess(rpyc_path, out_dir, method)
    elif method == "rpycdec":
        return _decompile_via_rpycdec(rpyc_path, out_dir)
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class UnrpycAdapter:
    """
    Unified .rpyc → .rpy decompiler adapter with automatic backend selection.

    Typical usage (via context manager — temp dir is cleaned automatically):

        adapter = UnrpycAdapter()
        with adapter.decompile_to_temp(rpyc_files, source_root) as (tmp_dir, ok_files):
            for rpy_path in ok_files:
                parser.parse_file(rpy_path)
    """

    def __init__(self):
        self._method = _detect_method()
        self.logger = logging.getLogger(__name__)
        if self._method:
            self.logger.info(f"UnrpycAdapter initialized: backend = {backend_name()}")
        else:
            self.logger.info("UnrpycAdapter: no decompiler backend found — will skip decompilation")

    @property
    def available(self) -> bool:
        return bool(self._method)

    def decompile_file(self, rpyc_path: Path, out_dir: Path) -> bool:
        """
        Decompile a single .rpyc/.rpymc file into out_dir.

        Returns True if the decompiled .rpy file was created successfully.
        """
        if not self._method:
            return False
        if not rpyc_path.exists():
            self.logger.warning(f"decompile_file: {rpyc_path} not found")
            return False
        out_dir.mkdir(parents=True, exist_ok=True)
        ok = _decompile_single(rpyc_path, out_dir, self._method)
        if not ok:
            self.logger.debug(f"Decompile failed (silently skipped): {rpyc_path.name}")
        return ok

    def decompile_directory(self, source_dir: Path, out_dir: Path,
                             exclude_dirs: Optional[List[str]] = None) -> List[Path]:
        """
        Decompile all .rpyc (and .rpymc) files under source_dir into out_dir,
        preserving relative directory structure.

        Returns list of successfully decompiled .rpy Path objects.
        """
        if not self._method:
            return []

        _skip = set(exclude_dirs or []) | {"tl", "cache", "__pycache__"}
        rpyc_files = []
        for root, dirs, files in os.walk(source_dir):
            dirs[:] = [d for d in dirs if d not in _skip]
            for f in files:
                if f.lower().endswith((".rpyc", ".rpymc")):
                    rpyc_files.append(Path(root) / f)

        if not rpyc_files:
            self.logger.debug("decompile_directory: no .rpyc files found")
            return []

        self.logger.info(f"Decompiling {len(rpyc_files)} .rpyc file(s) using {backend_name()} …")
        ok_files: List[Path] = []
        failed = 0

        for rpyc_path in rpyc_files:
            # Mirror directory structure inside out_dir
            try:
                rel = rpyc_path.relative_to(source_dir)
            except ValueError:
                rel = Path(rpyc_path.name)
            dest_dir = out_dir / rel.parent
            dest_dir.mkdir(parents=True, exist_ok=True)

            if self.decompile_file(rpyc_path, dest_dir):
                out_rpy = dest_dir / (rpyc_path.stem + ".rpy")
                ok_files.append(out_rpy)
            else:
                failed += 1

        self.logger.info(
            f"Decompile complete: {len(ok_files)} succeeded, {failed} failed"
        )
        return ok_files

    @contextmanager
    def decompile_to_temp(
        self, rpyc_files: List[Path], source_root: Path
    ) -> Iterator[Tuple[str, List[Path]]]:
        """
        Context manager: decompile given .rpyc files into a temporary directory.

        Yields (temp_dir_path, list_of_decompiled_rpy_paths).
        The temp directory is automatically removed on exit.

        Example:
            with adapter.decompile_to_temp(rpyc_files, source_root) as (tmp, rpy_list):
                for rpy in rpy_list:
                    parser.parse_file(rpy)
        """
        tmp_dir = tempfile.mkdtemp(prefix="renlocalizer_unrpyc_")
        try:
            if not self._method or not rpyc_files:
                yield tmp_dir, []
                return

            tmp_path = Path(tmp_dir)
            self.logger.debug(f"Temp decompile dir: {tmp_dir}")
            ok_files: List[Path] = []

            for rpyc_path in rpyc_files:
                try:
                    rel = rpyc_path.relative_to(source_root)
                except ValueError:
                    rel = Path(rpyc_path.name)
                dest_dir = tmp_path / rel.parent
                dest_dir.mkdir(parents=True, exist_ok=True)

                if self.decompile_file(rpyc_path, dest_dir):
                    ok_files.append(dest_dir / (rpyc_path.stem + ".rpy"))

            yield tmp_dir, ok_files
        finally:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                self.logger.debug(f"Cleaned up temp decompile dir: {tmp_dir}")
            except Exception:
                pass
