"""
Tests for rpa_parser.py — native RPA archive extraction + security hardening.

Covers:
  - _RestrictedRPAUnpickler.find_class() allowlist / security blocking
  - _safe_loads_rpa_index() restricted path + graceful fallback
  - End-to-end RPA-3.0 archive round-trip extraction
"""

import io
import os
import pickle
import zlib
from pathlib import Path

import pytest

from src.utils.rpa_parser import (
    RPAParser,
    _RestrictedRPAUnpickler,
    _safe_loads_rpa_index,
    extract_rpa,
)


# ============================================================================
# Restricted unpickler — allowlist + security
# ============================================================================

class TestRestrictedRPAUnpickler:
    def test_allows_common_builtins(self):
        up = _RestrictedRPAUnpickler(io.BytesIO())
        assert up.find_class("builtins", "dict") is dict
        assert up.find_class("builtins", "list") is list
        assert up.find_class("builtins", "tuple") is tuple
        assert up.find_class("builtins", "bytes") is bytes
        assert up.find_class("builtins", "str") is str

    def test_allows_python2_builtins(self):
        up = _RestrictedRPAUnpickler(io.BytesIO())
        assert up.find_class("__builtin__", "unicode") is str
        assert up.find_class("__builtin__", "long") is int

    def test_blocks_disallowed_global(self):
        up = _RestrictedRPAUnpickler(io.BytesIO())
        with pytest.raises(pickle.UnpicklingError):
            up.find_class("os", "system")

    def test_blocks_arbitrary_module(self):
        up = _RestrictedRPAUnpickler(io.BytesIO())
        with pytest.raises(pickle.UnpicklingError):
            up.find_class("subprocess", "Popen")


class TestSafeLoadsRpaIndex:
    def test_loads_normal_dict_index(self):
        # A realistic RPA index: {filename: [(offset, length, prefix), ...]}
        index = {"images/bg.png": [(100, 2048, b"")], "script.rpyc": [(3000, 512, b"\x00\x01")]}
        data = pickle.dumps(index)
        result = _safe_loads_rpa_index(data)
        assert result == index

    def test_blocks_malicious_pickle_via_restricted_path(self):
        # A pickle that would execute os.system must NOT run through the
        # restricted unpickler — it must raise before resolving the global.
        class Evil:
            def __reduce__(self):
                return (os.system, ("echo pwned",))

        payload = pickle.dumps(Evil())
        with pytest.raises(pickle.UnpicklingError):
            _RestrictedRPAUnpickler(io.BytesIO(payload)).load()

    def test_fallback_preserves_compatibility(self):
        # _safe_loads_rpa_index should fall back to standard pickle when the
        # restricted path rejects a type, so legitimate archives still work.
        index = {"a.txt": [(0, 10, b"")]}
        assert _safe_loads_rpa_index(pickle.dumps(index)) == index


# ============================================================================
# End-to-end archive round-trip
# ============================================================================

def _build_rpa3(tmp_path: Path, files: dict) -> Path:
    """Build a minimal valid RPA-3.0 archive and return its path."""
    # First pass: assemble body + index, then finalize header with offsets.
    header = b"RPA-3.0 " + b"0" * 16 + b" " + b"0" * 8 + b"\n"
    body_start = len(header)
    body = b""
    index = {}
    for name, content in files.items():
        start = body_start + len(body)
        body += content
        index[name] = [(start, len(content), b"")]

    key = 0
    index_pickle = zlib.compress(pickle.dumps(index))
    index_offset = body_start + len(body)
    header = (
        b"RPA-3.0 "
        + format(index_offset, "016x").encode("ascii")
        + b" "
        + format(key, "08x").encode("ascii")
        + b"\n"
    )

    rpa_path = tmp_path / "archive.rpa"
    rpa_path.write_bytes(header + body + index_pickle)
    return rpa_path


class TestExtractArchive:
    def test_rpa3_round_trip(self, tmp_path):
        files = {
            "game/script.rpy": b"label start:\n    \"Hello world\"\n",
            "game/images/logo.png": b"\x89PNG\r\n\x1a\nfakeimagedata",
        }
        rpa_path = _build_rpa3(tmp_path, files)
        out_dir = tmp_path / "out"

        parser = RPAParser()
        assert parser.extract_archive(rpa_path, out_dir) is True

        for name, content in files.items():
            extracted = out_dir / name
            assert extracted.exists(), f"missing {name}"
            assert extracted.read_bytes() == content

    def test_convenience_function(self, tmp_path):
        files = {"readme.txt": b"RenLocalizer test"}
        rpa_path = _build_rpa3(tmp_path, files)
        out_dir = tmp_path / "out2"
        assert extract_rpa(rpa_path, out_dir) is True
        assert (out_dir / "readme.txt").read_bytes() == b"RenLocalizer test"

    def test_missing_file_returns_false(self, tmp_path):
        parser = RPAParser()
        assert parser.extract_archive(tmp_path / "nope.rpa", tmp_path) is False

    def test_unknown_format_returns_false(self, tmp_path):
        bad = tmp_path / "bad.rpa"
        bad.write_bytes(b"NOTANRPA\x00\x01\x02")
        parser = RPAParser()
        assert parser.extract_archive(bad, tmp_path / "out") is False

