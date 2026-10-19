"""What the dashboard shows about a selected game before a run.

inspect_project() reads the game folder the way the pipeline will: the game's
own scripts (not tl/, the bundled engine or RenLocalizer's zzz_* files), its
archives, the translations already in tl/, and the Ren'Py version. Notices
use the pipeline's own messages, so the card warns about exactly what would
stop a run. Pure file reads: no config, no Qt.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from src.core.constants import is_renlocalizer_generated_script
from src.core.pipeline.saving import list_tl_languages
from src.core.pipeline.validating import probe_directory_writable
from src.utils.path_manager import unwrap_mac_app

# Folders under game/ that do not hold the game's own scripts
_NON_SOURCE_DIRS = {"tl", "renpy", "cache", "saves", "__pycache__", "python-packages"}
_CONFIG_NAME_RE = re.compile(r"""^\s*define\s+config\.name\s*=\s*(?:_\(\s*)?(['"])(.+?)\1""", re.M)
_CONFIG_VERSION_RE = re.compile(r"""^\s*define\s+config\.version\s*=\s*(['"])(.+?)\1""", re.M)
_VC_VERSION_RE = re.compile(r"""^version\s*=\s*['"](\d+)\.(\d+)\.(\d+)""", re.M)
_VERSION_TUPLE_RE = re.compile(r"version_tuple\s*=\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)")


def _read(path: Path, limit: int = 200_000) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def renpy_version(project_dir: Path) -> str:
    """'8.5.2' from renpy/vc_version.py (Ren'Py 8), or version_tuple in renpy/__init__.py (Ren'Py 7)."""
    m = _VC_VERSION_RE.search(_read(project_dir / "renpy" / "vc_version.py"))
    if not m:
        m = _VERSION_TUPLE_RE.search(_read(project_dir / "renpy" / "__init__.py"))
    return ".".join(m.groups()) if m else ""


def find_launcher(project_dir: Path, selected: Path | None = None, platform: str = sys.platform) -> str:
    """The file that starts the game: what the user picked, else the root launcher.

    A Ren'Py build keeps <Name>.py next to <Name>.exe / <Name>.sh / <Name>.app,
    so the .py name tells the game's launcher apart from other executables.
    """
    if selected is not None:
        if selected.is_file() and selected.suffix.lower() in (".exe", ".sh"):
            return str(selected)
        if selected.suffix.lower() == ".app" and selected.is_dir():
            return str(selected)
    if platform == "win32":
        suffixes = (".exe",)
    elif platform == "darwin":
        suffixes = (".app", ".sh")
    else:
        suffixes = (".sh",)
    try:
        entries = sorted(project_dir.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return ""
    stems = [p.stem for p in entries if p.suffix.lower() == ".py" and p.is_file()]
    for suffix in suffixes:
        for stem in stems:
            candidate = project_dir / f"{stem}{suffix}"
            if candidate.exists():
                return str(candidate)
    if platform == "win32":
        exes = [p for p in entries if p.suffix.lower() == ".exe" and p.is_file()
                and not p.stem.lower().endswith("-32") and not p.stem.lower().startswith(("python", "zsync"))]
        if len(exes) == 1:
            return str(exes[0])
    return ""


def _launcher_stem(project_dir: Path) -> str:
    """The game's name as its <Name>.py launcher spells it, when there is exactly one."""
    try:
        stems = [p.stem for p in project_dir.glob("*.py") if p.is_file()]
    except OSError:
        return ""
    return stems[0] if len(stems) == 1 else ""


def _count_files(game_dir: Path) -> dict:
    counts = {"rpy": 0, "rpyc": 0, "rpa": 0}
    for root, dirs, files in os.walk(game_dir):
        rel = Path(root).relative_to(game_dir).parts
        in_source = not rel or rel[0].lower() not in _NON_SOURCE_DIRS
        dirs[:] = [d for d in dirs if d.lower() not in ("cache", "saves", "__pycache__")]
        for f in files:
            low = f.lower()
            if low.endswith(".rpa"):
                counts["rpa"] += 1
            elif in_source and low.endswith((".rpy", ".rpyc")) and not is_renlocalizer_generated_script(f):
                counts["rpyc" if low.endswith(".rpyc") else "rpy"] += 1
    return counts


def inspect_project(path: str, *, rpa_extraction: bool = True, rpyc_reader: bool = True,
                    platform: str = sys.platform) -> dict:
    """Facts and notices about the game at *path* (game folder, project folder, launcher or .app)."""
    info = {
        "ok": False, "path": path or "", "project_dir": "", "game_dir": "", "name": "", "game_version": "",
        "renpy_version": "", "rpy": 0, "rpyc": 0, "rpa": 0, "tl_languages": [], "launcher": "",
        "tl_mode": False, "writable": True, "notices": [],
    }
    if not path:
        return info

    def notice(level: str, key: str, default: str) -> None:
        info["notices"].append({"level": level, "key": key, "default": default})

    selected = Path(path)
    root = Path(unwrap_mac_app(str(selected)))
    project_dir = root.parent if root.is_file() else root

    if "tl" in [p.lower() for p in project_dir.parts[-2:]]:
        # A tl/ folder, or a language inside it: retranslation mode fills empty lines
        info.update(tl_mode=True, ok=project_dir.is_dir(), project_dir=str(project_dir), name=project_dir.name)
        notice("info", "log_tl_folder_detected",
               "TL folder detected. Retranslation mode: only empty translations are filled, "
               "existing translations are kept.")
        return info

    game_dir = project_dir / "game"
    if not game_dir.is_dir() and (project_dir / "Game").is_dir():
        game_dir = project_dir / "Game"
    if not game_dir.is_dir() and project_dir.name.lower() == "game":
        # The game/ folder itself was picked
        game_dir, project_dir = project_dir, project_dir.parent
    info["project_dir"] = str(project_dir)
    if not game_dir.is_dir():
        notice("warn", "log_game_folder_missing",
               "game/ folder not found. Please select a valid Ren'Py project directory.")
        return info

    options = _read(game_dir / "options.rpy")
    launcher = find_launcher(project_dir, selected, platform)
    name = _CONFIG_NAME_RE.search(options)
    version = _CONFIG_VERSION_RE.search(options)
    info.update(
        ok=True,
        game_dir=str(game_dir),
        launcher=launcher,
        name=name.group(2) if name else (_launcher_stem(project_dir) or Path(launcher).stem or project_dir.name),
        game_version=version.group(2) if version else "",
        renpy_version=renpy_version(project_dir),
        tl_languages=list_tl_languages(str(game_dir)),
        writable=probe_directory_writable(str(game_dir)),
    )
    info.update(_count_files(game_dir))

    if not info["writable"]:
        notice("warn", "project_not_writable",
               "RenLocalizer cannot write to this game folder. Copy the game to a folder you own "
               "(for example Documents) and select the copy.")
    if not info["rpy"] and not info["rpyc"]:
        if info["rpa"] and rpa_extraction:
            notice("info", "project_scripts_in_rpa",
                   "The scripts are inside .rpa archives; they are extracted when the translation starts.")
        elif info["rpa"]:
            notice("warn", "pipeline_rpa_extraction_disabled",
                   "The game's scripts are packed in .rpa archives, but archive extraction is disabled. "
                   "Enable automatic extraction (CLI: --extract-rpa) and run again.")
        else:
            notice("warn", "pipeline_no_game_scripts",
                   "No game scripts (.rpy/.rpyc) were found in the game folder, so there is nothing of the "
                   "game to translate. If the game uses .rpa archives, check that they could be extracted.")
    elif not info["rpy"] and not rpyc_reader:
        notice("warn", "project_rpyc_reader_off",
               "The game ships only compiled .rpyc scripts, but the RPYC reader is turned off "
               "(Settings, Performance & Network).")
    return info
