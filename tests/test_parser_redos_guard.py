"""Regression tests: catastrophic backtracking in menu_choice_re.

Root cause: pattern_registry entry type 'menu' (parser.py menu_choice_re)
hung forever on colon-less prose lines containing quotes + parentheses,
e.g. FamiliarCircumstances game/engine/12_shop.rpy line 120:
    'locked' (the delivery step's story deps aren't met yet / no delivery event). The

The nested-quantifier paren group explores exponentially many partitions
when the mandatory trailing ':' is absent. Parsing runs in a subprocess
with a hard timeout so a regression can never hang the suite.
"""
import subprocess
import sys
from pathlib import Path

from src.core.parser import RenPyParser

REPO_ROOT = Path(__file__).resolve().parents[1]

# Exact trigger window (docstring prose, no colons).
TRIGGER_BLOCK = "\n".join(
    [
        "            'buy' (orderable now), 'no_money' (reachable but the wallet can't cover the price), or",
        "            'locked' (the delivery step's story deps aren't met yet / no delivery event). The",
        "            no_money/locked split exists for the storefront: an opaque 'unavailable' hid WHY a",
        "            product refused to sell - the author's most common confusion is simply an empty wallet",
    ]
)

# Adversarial variant: colon exists but AFTER the parenthetical junk.
LATE_COLON_CASE = "    'choice' (some long parenthetical condition text here) and then some trailing words:\n"

VALID_MENU = 'label start:\n    menu:\n        "Go left":\n            jump left\n'

_SUBPROCESS_TIMEOUT = 25


def _parse_file_guarded(path: Path):
    """Parse a file in a child process; return entry count or None on hang."""
    child = (
        "import sys; "
        f"sys.path.insert(0, r'{REPO_ROOT}'); "
        "from src.core.parser import RenPyParser; "
        f"p = RenPyParser(None); "
        f"e = p.extract_with_deep_scan(r'{path}', False, False); "
        "print(f'ENTRIES={len(e)}')"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", child],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
            cwd=str(REPO_ROOT),
        )
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0:
        raise RuntimeError(f"child parse failed: {proc.stderr[-500:]}")
    for line in proc.stdout.splitlines():
        if line.startswith("ENTRIES="):
            return int(line.split("=", 1)[1])
    raise RuntimeError(f"child produced no count: {proc.stdout[-300:]}")


def test_colonless_paren_prose_completes(tmp_path):
    target = tmp_path / "shop_repro.rpy"
    target.write_text(TRIGGER_BLOCK + "\n", encoding="utf-8")
    count = _parse_file_guarded(target)
    assert count is not None, "parser hung on colon-less paren prose (ReDoS)"
    assert isinstance(count, int)


def test_late_colon_paren_line_completes(tmp_path):
    target = tmp_path / "late_colon.rpy"
    target.write_text(LATE_COLON_CASE, encoding="utf-8")
    count = _parse_file_guarded(target)
    assert count is not None, "parser hung on late-colon paren line (ReDoS)"


def test_valid_menu_choice_still_extracted(tmp_path):
    target = tmp_path / "valid_menu.rpy"
    target.write_text(VALID_MENU, encoding="utf-8")
    parser = RenPyParser()
    entries = parser.extract_with_deep_scan(str(target), False, False)
    texts = [e.get("text", "") for e in entries]
    assert any("Go left" in t for t in texts), f"menu choice lost: {texts}"
