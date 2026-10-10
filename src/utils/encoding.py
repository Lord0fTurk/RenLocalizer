"""
Encoding helpers to read/write text defensively without crashing on bad bytes.
"""

import json as _json_std
import logging
import os
import time
import tempfile
from pathlib import Path
from typing import Optional, Tuple, Any, Union

_logger = logging.getLogger("RenLocalizer")

# charset-normalizer > chardet (daha hızlı, daha doğru)
try:
    from charset_normalizer import detect as _detect_encoding
except ImportError:
    import chardet as _chardet
    _detect_encoding = _chardet.detect

# orjson > json (Rust tabanlı, ~15x hızlı)
try:
    import orjson

    def dumps_json(obj: Any, indent: int = 2) -> str:
        """Fast JSON string dump using orjson."""
        option = orjson.OPT_NON_STR_KEYS
        if indent == 2:
            option |= orjson.OPT_INDENT_2
        return orjson.dumps(obj, option=option).decode("utf-8")

    def loads_json(data: Union[str, bytes]) -> Any:
        """Fast JSON load using orjson."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        return orjson.loads(data)

    def dumps_json_bytes(obj: Any, indent: int = 2) -> bytes:
        """Fast JSON binary dump using orjson."""
        option = orjson.OPT_NON_STR_KEYS
        if indent == 2:
            option |= orjson.OPT_INDENT_2
        return orjson.dumps(obj, option=option)

except ImportError:
    import json

    def dumps_json(obj: Any, indent: int = 2) -> str:
        """Fallback standard library JSON dump."""
        return json.dumps(obj, ensure_ascii=False, indent=indent)

    def loads_json(data: Union[str, bytes]) -> Any:
        """Fallback standard library JSON load."""
        return json.loads(data)

    def dumps_json_bytes(obj: Any, indent: int = 2) -> bytes:
        """Fallback standard library JSON binary dump."""
        return json.dumps(obj, ensure_ascii=False, indent=indent).encode("utf-8")


def read_text_safely(path: Path, preferred: Tuple[str, ...] = ("utf-8-sig", "utf-8")) -> Optional[str]:
    """
    Read file as text with tolerant fallbacks:
    - try preferred encodings first
    - then chardet detection with errors='replace'
    Returns None on I/O failure.
    """
    try:
        raw = path.read_bytes()
    except Exception:
        return None

    for enc in preferred:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue

    detected = _detect_encoding(raw)
    enc = detected.get("encoding") or "utf-8"
    try:
        return raw.decode(enc, errors="replace")
    except Exception:
        return None


def save_text_safely(path: Path, content: str, encoding: str = "utf-8-sig", newline: str = "\n") -> bool:
    """
    Atomic write with Windows-aware retry logic for 'Access Denied' issues.
    
    1. Writes content to a temporary file in the same directory.
    2. Retries up to 5 times if a PermissionError (File Lock) occurs.
    3. Replaces the destination file atomically (os.replace).
    """
    path_obj = Path(path)
    parent = path_obj.parent
    parent.mkdir(parents=True, exist_ok=True)
    
    # Create temp file in the same directory to ensure it's on the same filesystem
    temp_fd, temp_path = tempfile.mkstemp(dir=str(parent), suffix=".tmp", text=True)
    
    try:
        # Step 1: Write to temp
        with os.fdopen(temp_fd, 'w', encoding=encoding, newline=newline) as f:
            f.write(content)
        
        # Step 2: Atomic Swap with Retry (Bypass Windows File Locks)
        max_retries = 5
        for attempt in range(max_retries):
            try:
                if os.path.exists(path_obj):
                    os.replace(temp_path, str(path_obj))
                else:
                    os.rename(temp_path, str(path_obj))
                return True
            except PermissionError:
                if attempt < max_retries - 1:
                    time.sleep(0.3 * (attempt + 1)) # Incremental backoff
                    continue
                return False
            except Exception:
                return False
    finally:
        # Cleanup temp file if something went wrong and it's still there
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass
    return False


def normalize_to_utf8_sig(path: Path) -> bool:
    """
    Rewrite file to UTF-8-SIG with LF newlines safely.
    Returns True if rewrite succeeded.
    """
    text = read_text_safely(path)
    if text is None:
        return False
    return save_text_safely(path, text, encoding="utf-8-sig", newline="\n")


def save_json_safely(path: Union[str, Path], obj: Any, indent: int = 2) -> bool:
    """
    Atomic write for JSON payloads with orjson/json fallback and Windows lock retry.
    """
    path_obj = Path(path)
    parent = path_obj.parent

    # Serialise BEFORE creating the temp file: a failure here used to leave
    # the mkstemp descriptor open, so the .tmp could not be deleted on Windows.
    try:
        payload = dumps_json_bytes(obj, indent=indent)
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        # orjson rejects lone surrogates (e.g. text unpickled from .rpyc);
        # keep the file valid UTF-8 by replacing them instead of losing it.
        _logger.warning("JSON fast path failed for %s (%s); using lossy fallback", path_obj.name, exc)
        try:
            payload = _json_std.dumps(obj, ensure_ascii=False, indent=indent).encode("utf-8", "replace")
        except Exception as exc2:
            _logger.error("Could not serialise JSON for %s: %s", path_obj, exc2)
            return False

    try:
        parent.mkdir(parents=True, exist_ok=True)
        temp_fd, temp_path = tempfile.mkstemp(dir=str(parent), suffix=".tmp")
    except OSError as exc:
        _logger.error("Cannot write %s: %s", path_obj, exc)
        return False

    try:
        with os.fdopen(temp_fd, 'wb') as f:
            f.write(payload)

        max_retries = 5
        for attempt in range(max_retries):
            try:
                if os.path.exists(path_obj):
                    os.replace(temp_path, str(path_obj))
                else:
                    os.rename(temp_path, str(path_obj))
                return True
            except PermissionError:
                if attempt < max_retries - 1:
                    time.sleep(0.3 * (attempt + 1))
                    continue
                return False
            except Exception:
                return False
    finally:
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass
    return False


def read_json_safely(path: Union[str, Path]) -> Optional[Any]:
    """
    Fast and safe JSON load from file with orjson/json fallback.
    Returns None on missing file or read/parse error.
    """
    try:
        path_obj = Path(path)
        if not path_obj.is_file():
            return None
        return loads_json(path_obj.read_bytes())
    except Exception as exc:
        _logger.warning("Could not read JSON %s: %s", path, exc)
        return None


