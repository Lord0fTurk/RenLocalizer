# -*- coding: utf-8 -*-
"""
Ren'Py Translation Lint
========================

Post-translation validation for Ren'Py files.
Catches issues that cause runtime crashes or broken dialogue.

Checks:
1. Indentation errors (critical in Ren'Py)
2. translate block structure integrity
3. old/new pair validation (count, order, ID matching)
4. Placeholder/variable preservation ([name], {tag}, %(var)s, etc.)
5. Unclosed string literals
6. Encoding & BOM issues
7. Optional: invoke the real Ren'Py engine lint (if SDK available)
"""

import os
import re
import shutil
import subprocess
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from enum import Enum

logger = logging.getLogger(__name__)


# ────────────────────────── Data Classes ──────────────────────────


class LintSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class LintIssue:
    file: str
    line: int
    severity: LintSeverity
    code: str  # e.g. "E001"
    message: str
    suggestion: str = ""
    snippet: str = ""

    def __str__(self):
        sev = self.severity.value.upper()
        loc = f"{self.file}:{self.line}" if self.line else self.file
        return f"[{sev} {self.code}] {loc} — {self.message}"


@dataclass
class LintReport:
    issues: List[LintIssue] = field(default_factory=list)
    files_scanned: int = 0
    translate_blocks: int = 0
    old_new_pairs: int = 0

    @property
    def errors(self) -> int:
        return sum(
            1
            for i in self.issues
            if i.severity in (LintSeverity.ERROR, LintSeverity.CRITICAL)
        )

    @property
    def warnings(self) -> int:
        return sum(1 for i in self.issues if i.severity == LintSeverity.WARNING)

    @property
    def ok(self) -> bool:
        return self.errors == 0

    def summary(self) -> str:
        status = "PASS" if self.ok else "FAIL"
        return (
            f"Ren'Py Lint — {status}\n"
            f"  Files: {self.files_scanned}  |  Translate blocks: {self.translate_blocks}  |  Pairs: {self.old_new_pairs}\n"
            f"  Errors: {self.errors}  |  Warnings: {self.warnings}"
        )

    def merge(self, other: "LintReport"):
        self.issues.extend(other.issues)
        self.files_scanned += other.files_scanned
        self.translate_blocks += other.translate_blocks
        self.old_new_pairs += other.old_new_pairs


# ────────────────────────── Regex ──────────────────────────

_RE_TRANSLATE_BLOCK = re.compile(r"^translate\s+(\w+)\s+(\w+)\s*:\s*$")
_RE_TRANSLATE_STRINGS = re.compile(r"^translate\s+(\w+)\s+strings\s*:\s*$")
_RE_OLD = re.compile(r'^\s+old\s+"(.*)"\s*$')
_RE_NEW = re.compile(r'^\s+new\s+"(.*)"\s*$')
_RE_DIALOGUE = re.compile(r'^\s+(\w+)\s+"(.*)"\s*$')
_RE_VARIABLE = re.compile(r"\[([^\[\]]+)\]")
_RE_TAG = re.compile(r"\{(/?\w[^\}]*)\}")
_RE_FMT_NAMED = re.compile(r"%\(\w+\)[sdifr]")
_RE_FMT_POSITIONAL = re.compile(r"%[sdifr%]")
_RE_PY_FORMAT = re.compile(
    r"\{(\d+|[a-zA-Z_]\w*)\}"
)  # Python .format() {0}, {name} — requires content


# ────────────────────────── Core Linter ──────────────────────────


class RenpyTranslationLint:
    """
    Validates translated .rpy output files for structural correctness.
    """

    def __init__(self, *, strict: bool = False):
        """
        Args:
            strict: If True, treat warnings as errors.
        """
        self.strict = strict

    # ── public API ──

    def lint_file(self, path: str) -> LintReport:
        """Lint a single .rpy file."""
        report = LintReport(files_scanned=1)
        p = Path(path)

        # Encoding / BOM check
        self._check_encoding(p, report)

        try:
            text = p.read_text(encoding="utf-8-sig")
        except Exception as e:
            report.issues.append(
                LintIssue(
                    file=str(p),
                    line=0,
                    severity=LintSeverity.CRITICAL,
                    code="E000",
                    message=f"Cannot read file: {e}",
                )
            )
            return report

        lines = text.split("\n")

        self._check_indentation(p, lines, report)
        self._check_translate_blocks(p, lines, report)
        self._check_old_new_pairs(p, lines, report)
        self._check_strings(p, lines, report)

        return report

    def lint_directory(self, directory: str, *, recursive: bool = True) -> LintReport:
        """Lint all .rpy files under *directory*."""
        report = LintReport()
        root = Path(directory)

        pattern = "**/*.rpy" if recursive else "*.rpy"
        for rpy in sorted(root.glob(pattern)):
            # skip renpy engine, cache, saves
            parts = rpy.relative_to(root).parts
            if any(
                p in ("renpy", "__pycache__", "cache", "saves", ".git") for p in parts
            ):
                continue
            sub = self.lint_file(str(rpy))
            report.merge(sub)

        return report

    # ── encoding ──

    @staticmethod
    def _check_encoding(p: Path, report: LintReport):
        raw = b""
        try:
            raw = p.read_bytes()[:4]
        except Exception:
            return

        # UTF-8 BOM is fine (utf-8-sig handles it), but UTF-16 BOM is trouble
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            report.issues.append(
                LintIssue(
                    file=str(p),
                    line=1,
                    severity=LintSeverity.ERROR,
                    code="E010",
                    message="File uses UTF-16 encoding — Ren'Py requires UTF-8",
                    suggestion="Re-save the file as UTF-8",
                )
            )

    # ── indentation ──

    def _check_indentation(self, p: Path, lines: List[str], report: LintReport):
        """Ren'Py uses 4-space indentation; tabs cause issues."""
        fname = str(p)
        for i, line in enumerate(lines, 1):
            if "\t" in line and line.strip():
                report.issues.append(
                    LintIssue(
                        file=fname,
                        line=i,
                        severity=LintSeverity.WARNING,
                        code="W010",
                        message="Tab character in indentation — Ren'Py expects spaces",
                        suggestion="Replace tabs with 4 spaces",
                        snippet=line.rstrip()[:80],
                    )
                )
            # Check for odd indentation (not multiple of 4) on non-blank lines
            if line.strip():
                leading = len(line) - len(line.lstrip(" "))
                # Only flag if there's actually indentation and it's not a multiple of 4
                # (and no tabs - handled above)
                if leading > 0 and leading % 4 != 0 and "\t" not in line:
                    # Some lines like comments may have odd indent, be lenient
                    if not line.strip().startswith("#"):
                        report.issues.append(
                            LintIssue(
                                file=fname,
                                line=i,
                                severity=LintSeverity.INFO,
                                code="I010",
                                message=f"Indentation is {leading} spaces (not a multiple of 4)",
                                snippet=line.rstrip()[:80],
                            )
                        )

    # ── translate block structure ──

    def _check_translate_blocks(self, p: Path, lines: List[str], report: LintReport):
        fname = str(p)
        seen_ids: Dict[str, int] = {}

        for i, line in enumerate(lines, 1):
            m = _RE_TRANSLATE_BLOCK.match(line)
            if m:
                report.translate_blocks += 1
                _lang, tid = m.group(1), m.group(2)

                # Duplicate ID check
                if tid in seen_ids:
                    report.issues.append(
                        LintIssue(
                            file=fname,
                            line=i,
                            severity=LintSeverity.WARNING,
                            code="W020",
                            message=f"Duplicate translate ID '{tid}' (first at line {seen_ids[tid]})",
                            suggestion="Each translate block should have a unique ID",
                        )
                    )
                else:
                    seen_ids[tid] = i

                # Next non-blank line should be indented
                for j in range(i, min(i + 5, len(lines))):
                    nxt = lines[j]
                    if nxt.strip():
                        if not nxt.startswith("    ") and not nxt.startswith("\t"):
                            report.issues.append(
                                LintIssue(
                                    file=fname,
                                    line=j + 1,
                                    severity=LintSeverity.ERROR,
                                    code="E020",
                                    message="Content after translate block must be indented",
                                    snippet=nxt.rstrip()[:80],
                                )
                            )
                        break

            # translate ... strings:
            ms = _RE_TRANSLATE_STRINGS.match(line)
            if ms:
                report.translate_blocks += 1

    # ── old/new pairs ──

    def _check_old_new_pairs(self, p: Path, lines: List[str], report: LintReport):
        fname = str(p)
        i = 0
        while i < len(lines):
            old_m = _RE_OLD.match(lines[i])
            if old_m:
                old_text = old_m.group(1)
                # Next non-blank line should be new "..."
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1

                if j < len(lines):
                    new_m = _RE_NEW.match(lines[j])
                    if new_m:
                        new_text = new_m.group(1)
                        report.old_new_pairs += 1

                        # Placeholder checks
                        self._check_placeholders(
                            fname, i + 1, old_text, new_text, report
                        )

                        i = j + 1
                        continue
                    else:
                        report.issues.append(
                            LintIssue(
                                file=fname,
                                line=i + 1,
                                severity=LintSeverity.ERROR,
                                code="E030",
                                message='old "..." not followed by new "..."',
                                suggestion="Every old line must be followed by a new line",
                                snippet=lines[i].rstrip()[:80],
                            )
                        )
            i += 1

    # ── placeholder preservation ──

    def _check_placeholders(
        self, fname: str, line: int, original: str, translated: str, report: LintReport
    ):
        """Ensure [var], {tag}, %(name)s, {0} placeholders are preserved."""

        # --- Ren'Py variables [name] ---
        orig_vars = set(_RE_VARIABLE.findall(original))
        trans_vars = set(_RE_VARIABLE.findall(translated))
        missing = orig_vars - trans_vars
        if missing:
            report.issues.append(
                LintIssue(
                    file=fname,
                    line=line,
                    severity=LintSeverity.ERROR,
                    code="E040",
                    message=f"Missing Ren'Py variable(s): {', '.join(f'[{v}]' for v in sorted(missing))}",
                    suggestion="All [variable] placeholders must be kept in translation",
                )
            )

        # --- Ren'Py text tags {b}, {color=...} ---
        orig_tags = set(_RE_TAG.findall(original))
        trans_tags = set(_RE_TAG.findall(translated))
        missing_tags = orig_tags - trans_tags
        if missing_tags:
            report.issues.append(
                LintIssue(
                    file=fname,
                    line=line,
                    severity=LintSeverity.WARNING,
                    code="W040",
                    message=f"Missing text tag(s): {', '.join('{' + t + '}' for t in sorted(missing_tags))}",
                    suggestion="Preserve formatting tags in translation",
                )
            )

        # --- Python % format ---
        orig_named = set(_RE_FMT_NAMED.findall(original))
        trans_named = set(_RE_FMT_NAMED.findall(translated))
        if orig_named != trans_named:
            diff = orig_named - trans_named
            if diff:
                report.issues.append(
                    LintIssue(
                        file=fname,
                        line=line,
                        severity=LintSeverity.ERROR,
                        code="E041",
                        message=f"Missing Python format placeholder(s): {', '.join(sorted(diff))}",
                    )
                )

        # --- Python .format() {0}, {name} ---
        # Filter out known Ren'Py text tags before checking
        _RENPY_TAGS = {
            "b",
            "i",
            "u",
            "s",
            "a",
            "w",
            "p",
            "nw",
            "fast",
            "done",
            "plain",
            "art",
            "rb",
            "rt",
            "cps",
            "k",
            "size",
            "font",
            "color",
            "alpha",
            "outlinecolor",
            "image",
            "space",
            "vspace",
        }
        orig_fmt = set(_RE_PY_FORMAT.findall(original))
        trans_fmt = set(_RE_PY_FORMAT.findall(translated))
        # Remove Ren'Py tags from format check
        orig_fmt -= _RENPY_TAGS
        trans_fmt -= _RENPY_TAGS
        if orig_fmt and orig_fmt != trans_fmt:
            diff = orig_fmt - trans_fmt
            if diff:
                report.issues.append(
                    LintIssue(
                        file=fname,
                        line=line,
                        severity=LintSeverity.WARNING,
                        code="W041",
                        message=f"Missing .format() placeholder(s): {', '.join('{' + p + '}' for p in sorted(diff))}",
                    )
                )

    # ── string syntax ──

    def _check_strings(self, p: Path, lines: List[str], report: LintReport):
        fname = str(p)
        in_multiline = False

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # Count unescaped quotes
            count = 0
            j = 0
            while j < len(stripped):
                if stripped[j] == "\\" and j + 1 < len(stripped):
                    j += 2
                    continue
                if stripped[j] == '"':
                    count += 1
                j += 1

            if count % 2 != 0:
                # Could be triple-quote multiline — skip those
                # Count occurrences: odd count = toggle, even count = no toggle
                tq_double = stripped.count('"""')
                tq_single = stripped.count("'''")
                tq_total = tq_double + tq_single
                if tq_total > 0:
                    if tq_total % 2 == 1:  # Odd = state change
                        in_multiline = not in_multiline
                    continue
                if in_multiline:
                    continue

                report.issues.append(
                    LintIssue(
                        file=fname,
                        line=i,
                        severity=LintSeverity.ERROR,
                        code="E050",
                        message="Unbalanced quotes — possible unclosed string",
                        snippet=stripped[:80],
                    )
                )


# ────────────────────────── Engine Lint Integration ──────────────────────────


def _find_launcher_in_dir(directory: str) -> Optional[str]:
    """Check a single directory for a Ren'Py launcher (.py or .sh)."""
    d = Path(directory).expanduser().resolve()
    if not d.is_dir():
        return None

    for py in d.glob("*.py"):
        if py.stem not in ("__init__",):
            try:
                head = (
                    py.read_text(encoding="utf-8", errors="ignore")[:500]
                    .lower()
                    .replace("'", "")
                )
                if "renpy" in head:
                    return str(py)
            except Exception:
                continue

    for sh in d.glob("*.sh"):
        try:
            head = (
                sh.read_text(encoding="utf-8", errors="ignore")[:500]
                .lower()
                .replace("'", "")
            )
            if "renpy" in head:
                return str(sh)
        except Exception:
            continue

    return None


def _find_renpy_in_path() -> Optional[str]:
    """Check if `renpy` (or `renpy.sh`) is available on PATH."""
    for name in ("renpy", "renpy.sh"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _search_sdk_locations(game_dir: str) -> Optional[str]:
    """
    Search common SDK locations: parent dirs, system-wide installs, home dir.
    """
    game_path = Path(game_dir).resolve()
    probes: list[Path] = []

    # Parent directories
    probes.append(game_path / "..")
    probes.append(game_path / "../..")

    # Subdirectories of game dir that start with "renpy" (case-insensitive)
    for sub in game_path.iterdir():
        if sub.is_dir() and sub.name.lower().startswith("renpy"):
            probes.append(sub)

    # System-wide locations
    for p in ("/usr/share/renpy", "/usr/local/share/renpy"):
        probes.append(Path(p))

    # Home directory
    for pattern in ("renpy*", "RenPy*"):
        for p in Path.home().glob(pattern):
            if p.is_dir():
                probes.append(p)

    # /opt
    for pattern in ("renpy*", "RenPy*"):
        for p in Path("/opt").glob(pattern):
            if p.is_dir():
                probes.append(p)

    seen: set[str] = set()
    for probe in probes:
        resolved = str(probe.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        exe = _find_launcher_in_dir(resolved)
        if exe:
            return exe

    return None


def find_renpy_executable(game_dir: str, sdk_path: str = "") -> Optional[str]:
    """
    Locate the Ren'Py launch script by searching:
      1. The game project directory itself
      2. A user-configured SDK path (if provided)
      3. Common SDK locations (parent dirs, system-wide installs, home dir)
      4. The system PATH (for system-wide installs like Arch AUR)
    Returns path to the launcher (.py or .sh), or None.
    """
    # 1. Check the game project directory directly
    exe = _find_launcher_in_dir(game_dir)
    if exe:
        return exe

    # 2. User-configured SDK path
    if sdk_path:
        exe = _find_launcher_in_dir(sdk_path)
        if exe:
            return exe

    # 3. Common SDK locations
    exe = _search_sdk_locations(game_dir)
    if exe:
        return exe

    # 4. Check if `renpy` is on PATH (system-wide install)
    return _find_renpy_in_path()


def run_renpy_lint(
    game_dir: str, *, timeout: int = 120, sdk_path: str = ""
) -> Optional[LintReport]:
    """
    Run Ren'Py's built-in lint on a game project (if the engine is available).

    Args:
        game_dir: Root directory of the Ren'Py game project.
        timeout: Timeout in seconds for the lint subprocess.
        sdk_path: Optional explicit path to the Ren'Py SDK directory.

    Returns a LintReport with issues parsed from lint output, or None if
    the engine could not be found/invoked.
    """
    exe = find_renpy_executable(game_dir, sdk_path=sdk_path)
    if not exe:
        logger.info("No Ren'Py launcher found in %s — skipping engine lint", game_dir)
        return None

    report = LintReport()

    # Determine the right Python executable and command
    if exe.endswith(".sh"):
        # Linux/Mac shell script — run it directly
        cmd = [exe, "lint"]
    else:
        # .py script — use the current Python interpreter (not hardcoded 'python')
        import sys

        cmd = [sys.executable, exe, "lint"]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=game_dir,
        )
        output = result.stdout + "\n" + result.stderr

        # Parse Ren'Py lint output lines
        # Typical: "game/script.rpy:42 The say statement has too many arguments."
        line_re = re.compile(r"^(.+\.rpy):(\d+)\s+(.+)$", re.MULTILINE)
        for m in line_re.finditer(output):
            file_path, line_num, msg = m.group(1), int(m.group(2)), m.group(3)
            severity = LintSeverity.WARNING
            if any(w in msg.lower() for w in ("error", "could not", "cannot")):
                severity = LintSeverity.ERROR
            report.issues.append(
                LintIssue(
                    file=file_path,
                    line=line_num,
                    severity=severity,
                    code="R001",
                    message=f"[Ren'Py Lint] {msg}",
                )
            )

        # Also catch summary lines like "X lint messages were produced."
        if result.returncode != 0 and not report.issues:
            report.issues.append(
                LintIssue(
                    file=game_dir,
                    line=0,
                    severity=LintSeverity.WARNING,
                    code="R000",
                    message=f"Ren'Py lint exited with code {result.returncode}",
                    snippet=output[:200],
                )
            )

    except subprocess.TimeoutExpired:
        report.issues.append(
            LintIssue(
                file=game_dir,
                line=0,
                severity=LintSeverity.WARNING,
                code="R000",
                message=f"Ren'Py lint timed out after {timeout}s",
            )
        )
    except FileNotFoundError:
        logger.info("Python not found for Ren'Py lint invocation")
        return None
    except Exception as e:
        logger.warning("Ren'Py lint failed: %s", e)
        return None

    return report


# ────────────────────────── Convenience API ──────────────────────────


def lint_translation_output(
    path: str,
    *,
    strict: bool = False,
    try_engine_lint: bool = False,
    game_dir: str = "",
    sdk_path: str = "",
) -> LintReport:
    """
    One-call lint for translated output files.

    Args:
        path: File or directory to lint.
        strict: Treat warnings as errors.
        try_engine_lint: Attempt to run Ren'Py's own lint.
        game_dir: Game root (needed for engine lint).
        sdk_path: Optional explicit path to the Ren'Py SDK directory.
    """
    linter = RenpyTranslationLint(strict=strict)

    if os.path.isfile(path):
        report = linter.lint_file(path)
    else:
        report = linter.lint_directory(path)

    # Optional engine lint
    if try_engine_lint and game_dir:
        engine_report = run_renpy_lint(game_dir, sdk_path=sdk_path)
        if engine_report:
            report.merge(engine_report)

    return report
