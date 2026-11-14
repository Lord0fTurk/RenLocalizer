"""
Native RPA Archive Parser for Ren'Py games.

This is a fallback implementation that doesn't rely on external unrpa dependency.
Supports RPA-3.0 and RPA-2.0 formats (most common in modern Ren'Py games).

Used when:
1. unrpa fails to import in frozen (PyInstaller) environment
2. unrpa is not installed
"""

import pickle
import zlib
import hashlib
import logging
from pathlib import Path
from typing import Dict, Tuple, Optional, BinaryIO


# ============================================================================
# RESTRICTED UNPICKLING (Security hardening)
# ============================================================================
# RPA archive indexes are simple data structures:
#   { filename: [(offset, length, prefix), ...] }
# They only need basic container/primitive types. Using raw pickle.loads on
# untrusted game archives is a code-execution attack surface. We mirror the
# proven allowlist pattern from src/core/rpyc_reader.py (RenpyUnpickler) but
# with a graceful fallback: if the restricted unpickler rejects something a
# legitimate archive needs, we fall back to standard pickle.loads with a
# warning so existing working archives keep functioning (zero breakage).

logger = logging.getLogger(__name__)

# Allowlist of harmless builtins sufficient to reconstruct an RPA index.
_RPA_SAFE_BUILTINS: Dict[Tuple[str, str], type] = {
    ("builtins", "dict"): dict,
    ("builtins", "list"): list,
    ("builtins", "tuple"): tuple,
    ("builtins", "set"): set,
    ("builtins", "frozenset"): frozenset,
    ("builtins", "str"): str,
    ("builtins", "bytes"): bytes,
    ("builtins", "bytearray"): bytearray,
    ("builtins", "int"): int,
    ("builtins", "float"): float,
    ("builtins", "bool"): bool,
    # Python 2 pickled archives (older games)
    ("__builtin__", "dict"): dict,
    ("__builtin__", "list"): list,
    ("__builtin__", "tuple"): tuple,
    ("__builtin__", "set"): set,
    ("__builtin__", "frozenset"): frozenset,
    ("__builtin__", "str"): str,
    ("__builtin__", "unicode"): str,
    ("__builtin__", "bytes"): bytes,
    ("__builtin__", "int"): int,
    ("__builtin__", "long"): int,
    ("__builtin__", "float"): float,
    ("__builtin__", "bool"): bool,
}


class _RestrictedRPAUnpickler(pickle.Unpickler):
    """Unpickler that only resolves safe builtin types for RPA indexes.

    Any attempt to resolve a disallowed global (e.g. os.system) raises
    UnpicklingError, blocking arbitrary code execution during deserialization.
    """

    def find_class(self, module: str, name: str) -> type:
        key = (module, name)
        if key in _RPA_SAFE_BUILTINS:
            return _RPA_SAFE_BUILTINS[key]
        raise pickle.UnpicklingError(f"Disallowed global in RPA index: {module}.{name}")


def _safe_loads_rpa_index(data: bytes):
    """Deserialize an RPA index safely using restricted unpickling.

    Only allowlisted container and primitive types are resolved.
    Any attempt to resolve disallowed globals (e.g. executable callables)
    strictly raises pickle.UnpicklingError without insecure fallback.
    """
    import io
    return _RestrictedRPAUnpickler(io.BytesIO(data)).load()


def _archive_index_keystream(key: int, length: int) -> bytes:
    """
    Derives a `length`-byte keystream from `key` using SHA-256 blocks.
    Used by games (e.g. Harem Corruption / HHH-1.0 and similar obfuscated archives)
    to deobfuscate the compressed archive index.
    """
    seed = key.to_bytes(8, "big") if isinstance(key, int) else key
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        counter += 1
    return bytes(out[:length])


def _archive_index_xor(data: bytes, key: int) -> bytes:
    """XORs data with SHA-256 derived keystream."""
    ks = _archive_index_keystream(key, len(data))
    n = len(data)
    return (int.from_bytes(data, "big") ^ int.from_bytes(ks, "big")).to_bytes(n, "big")


class RPAParser:
    """Native RPA archive parser supporting RPAv2, RPAv3 and custom/obfuscated RPA formats (e.g. HHH-1.0)."""
    
    # Standard and known format signatures
    RPA3_SIGNATURE = b"RPA-3.0"
    RPA2_SIGNATURE = b"RPA-2.0"
    HHH1_SIGNATURE = b"HHH-1.0"
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def extract_archive(self, rpa_path: Path, output_dir: Path) -> bool:
        """
        Extract all files from an RPA archive.
        
        Args:
            rpa_path: Path to the .rpa file
            output_dir: Directory to extract files to
            
        Returns:
            bool: True if extraction was successful
        """
        if not rpa_path.exists():
            self.logger.error(f"RPA file not found: {rpa_path}")
            return False
        
        try:
            with open(rpa_path, 'rb') as f:
                header = f.readline()
                return self._extract_from_header(f, header, output_dir)
                    
        except Exception as e:
            self.logger.error(f"Error extracting {rpa_path}: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return False

    def _extract_from_header(self, f: BinaryIO, header: bytes, output_dir: Path) -> bool:
        """Parse header and delegate to the appropriate extraction method."""
        parts = header.decode('utf-8', errors='replace').strip().split()
        
        # 3-part header: <MAGIC> <OFFSET_HEX> <KEY_HEX>
        # Matches RPA-3.0, HHH-1.0, and any custom 3-parameter RPA archive
        if len(parts) >= 3:
            try:
                offset = int(parts[1], 16)
                key = int(parts[2], 16)
                return self._extract_rpa3_parsed(f, offset, key, output_dir)
            except ValueError:
                pass
        
        # 2-part header: <MAGIC> <OFFSET_HEX>
        # Matches RPA-2.0 and 2-parameter RPA archives
        if len(parts) >= 2:
            try:
                offset = int(parts[1], 16)
                return self._extract_rpa2_parsed(f, offset, output_dir)
            except ValueError:
                pass

        self.logger.error(f"Unknown RPA format: {header[:20]}")
        return False
    
    def _read_index_rpa3(self, f: BinaryIO, offset: int, key: int) -> Optional[Dict]:
        """
        Read index with multi-stage deobfuscation and decompression:
        1. Standard zlib decompressed pickle
        2. SHA-256 keystream XOR deobfuscated + zlib decompressed pickle (HHH-1.0, etc.)
        3. SHA-256 keystream XOR deobfuscated raw pickle
        4. Raw uncompressed pickle fallback
        """
        f.seek(offset)
        index_data = f.read()

        # Stage 1: Standard zlib decompression
        try:
            return _safe_loads_rpa_index(zlib.decompress(index_data))
        except Exception:
            pass

        # Stage 2: Keystream XOR + zlib (HHH-1.0 and custom obfuscated archives)
        try:
            xored = _archive_index_xor(index_data, key)
            return _safe_loads_rpa_index(zlib.decompress(xored))
        except Exception:
            pass

        # Stage 3: Keystream XOR raw pickle
        try:
            xored = _archive_index_xor(index_data, key)
            return _safe_loads_rpa_index(xored)
        except Exception:
            pass

        # Stage 4: Raw uncompressed pickle fallback
        try:
            return _safe_loads_rpa_index(index_data)
        except Exception:
            pass

        return None

    def _extract_rpa3_parsed(self, f: BinaryIO, offset: int, key: int, output_dir: Path) -> bool:
        """Extract RPA-3.0 or custom 3-part archive using parsed offset and key."""
        try:
            index = self._read_index_rpa3(f, offset, key)
            if index is None:
                self.logger.error(f"Failed to decompress or parse RPA index at offset {offset:#x}")
                return False
            return self._extract_files(f, index, output_dir, key)
        except Exception as e:
            self.logger.error(f"RPA-3.0 extraction error: {e}")
            return False

    def _extract_rpa3(self, f: BinaryIO, header: bytes, output_dir: Path) -> bool:
        """Extract RPA-3.0 format archive (legacy signature compatibility)."""
        parts = header.decode('utf-8', errors='replace').strip().split()
        if len(parts) < 3:
            self.logger.error(f"Invalid RPA-3.0 header: {header}")
            return False
        try:
            offset = int(parts[1], 16)
            key = int(parts[2], 16)
        except ValueError:
            self.logger.error(f"Invalid RPA-3.0 header offsets: {header}")
            return False
        return self._extract_rpa3_parsed(f, offset, key, output_dir)

    def _extract_rpa2_parsed(self, f: BinaryIO, offset: int, output_dir: Path) -> bool:
        """Extract RPA-2.0 or custom 2-part archive using parsed offset."""
        try:
            f.seek(offset)
            index_data = f.read()
            try:
                index = _safe_loads_rpa_index(zlib.decompress(index_data))
            except Exception:
                f.seek(offset)
                index = _safe_loads_rpa_index(f.read())
            return self._extract_files(f, index, output_dir, key=0)
        except Exception as e:
            self.logger.error(f"RPA-2.0 extraction error: {e}")
            return False

    def _extract_rpa2(self, f: BinaryIO, header: bytes, output_dir: Path) -> bool:
        """Extract RPA-2.0 format archive (legacy signature compatibility)."""
        parts = header.decode('utf-8', errors='replace').strip().split()
        if len(parts) < 2:
            self.logger.error(f"Invalid RPA-2.0 header: {header}")
            return False
        try:
            offset = int(parts[1], 16)
        except ValueError:
            self.logger.error(f"Invalid RPA-2.0 header offset: {header}")
            return False
        return self._extract_rpa2_parsed(f, offset, output_dir)
    
    def _extract_files(self, f: BinaryIO, index: Dict, output_dir: Path, key: int = 0) -> bool:
        """Extract files from index to output directory."""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        extracted = 0
        errors = 0
        
        for filename, data_list in index.items():
            try:
                # Normalize filename
                if isinstance(filename, bytes):
                    filename = filename.decode('utf-8')
                
                # Get file info - format: [(offset, length, prefix), ...]
                if not data_list:
                    continue
                
                file_data = data_list[0]
                
                if len(file_data) >= 2:
                    offset = file_data[0] ^ key
                    length = file_data[1] ^ key
                    prefix = file_data[2] if len(file_data) > 2 else b''
                else:
                    continue
                
                # Handle prefix (may be bytes or string)
                if isinstance(prefix, str):
                    prefix = prefix.encode('latin-1')
                
                # Prevent path traversal (Zip Slip vulnerability)
                clean_filename = Path(filename.replace('\\', '/')).as_posix().lstrip('/')
                out_path = (output_dir / clean_filename).resolve()
                output_dir_resolved = output_dir.resolve()
                if not out_path.is_relative_to(output_dir_resolved):
                    self.logger.warning(f"Skipping dangerous path traversal file in RPA: {filename}")
                    errors += 1
                    continue

                out_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Read and write file
                f.seek(offset)
                read_len = length - len(prefix)
                if read_len < 0:
                    self.logger.warning(f"Skipping malformed RPA entry (prefix longer than length): {filename}")
                    errors += 1
                    continue
                content = prefix + f.read(read_len)
                
                with open(out_path, 'wb') as out_f:
                    out_f.write(content)
                
                extracted += 1
                
            except Exception as e:
                self.logger.warning(f"Failed to extract {filename}: {e}")
                errors += 1
        
        self.logger.info(f"Extracted {extracted} files ({errors} errors)")
        return extracted > 0


# Convenience function
def extract_rpa(rpa_path: Path, output_dir: Path) -> bool:
    """Extract an RPA archive using native parser."""
    parser = RPAParser()
    return parser.extract_archive(rpa_path, output_dir)
