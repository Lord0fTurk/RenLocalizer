"""Patch aiohttp __init__.py for Python 3.14 circular import workaround.
Finds aiohttp via pip show without importing it."""

import ast
import os
import re
import subprocess
import sys


def patch_aiohttp():
    result = subprocess.run(
        [sys.executable, "-m", "pip", "show", "aiohttp"], capture_output=True, text=True
    )
    loc = None
    for line in result.stdout.splitlines():
        if line.lower().startswith("location:"):
            loc = line.split(":", 1)[1].strip()
            break

    if not loc:
        print("aiohttp not found via pip show")
        sys.exit(1)

    p = os.path.join(loc, "aiohttp", "__init__.py")
    if not os.path.exists(p):
        print(f"aiohttp __init__.py not found at {p}")
        sys.exit(1)

    with open(p, "r", encoding="utf-8") as f:
        c = f.read()

    # If already patched or hdrs already handled, exit cleanly
    if 'import aiohttp.hdrs as hdrs' in c or 'name == "hdrs"' in c:
        print(f"aiohttp already patched at {p}")
        sys.exit(0)

    # Check if 'from . import hdrs as hdrs' is present
    target_import = "from . import hdrs as hdrs"
    if target_import not in c:
        print(f"aiohttp at {p} does not contain '{target_import}', skipping patch.")
        sys.exit(0)

    # Remove the eager top-level import
    c_new = c.replace(target_import + "\n", "", 1)
    if c_new == c:
        c_new = c.replace(target_import, "", 1)

    # Inject lazy loading in __getattr__ or append __getattr__ if not present
    lazy_hdrs_code = (
        '    if name == "hdrs":\n'
        '        import aiohttp.hdrs as _hdrs\n'
        '        return _hdrs\n'
    )

    match = re.search(r'def __getattr__\([^\)]*\)[^:]*:', c_new)
    if match:
        end_pos = match.end()
        c_new = c_new[:end_pos] + '\n' + lazy_hdrs_code + c_new[end_pos:]
    else:
        c_new += (
            '\n\ndef __getattr__(name: str):\n'
            + lazy_hdrs_code +
            '    raise AttributeError(f"module \'aiohttp\' has no attribute \'{name}\'")\n'
        )

    # Verify code validity before writing
    try:
        ast.parse(c_new)
    except Exception as exc:
        print(f"Failed to parse patched aiohttp code: {exc}")
        sys.exit(1)

    with open(p, "w", encoding="utf-8") as f:
        f.write(c_new)
    print(f"aiohttp successfully patched at {p}")
    sys.exit(0)


if __name__ == "__main__":
    patch_aiohttp()
