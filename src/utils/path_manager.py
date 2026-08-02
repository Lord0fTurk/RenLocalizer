import os
import sys
import platform
from pathlib import Path

def get_app_dir() -> Path:
    """Returns the physical directory of the executable or script."""
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            # Running as compiled PyInstaller executable
            return Path(sys.executable).parent.resolve()
    # Running as development script (run.py is 3 levels up from this file)
    return Path(__file__).resolve().parent.parent.parent

def is_appimage() -> bool:
    """Check if the application is running packaged as a Linux AppImage."""
    return 'APP_IMAGE' in os.environ or 'APPIMAGE' in os.environ

def get_system_data_dir() -> Path:
    """Determine the OS-specific standard application data directory."""
    system = platform.system()
    app_name = "RenLocalizer"
    
    if system == "Windows":
        base = os.environ.get("APPDATA")
        if not base:
             base = os.path.expanduser("~")
        return Path(base) / app_name
    elif system == "Darwin":
        return Path(os.path.expanduser(f"~/Library/Application Support/{app_name}"))
    else:
        # Linux and others (XDG Base Directory Specification)
        base = os.environ.get("XDG_DATA_HOME")
        if not base:
            base = os.path.expanduser("~/.local/share")
        return Path(base) / app_name

def get_data_path() -> Path:
    """
    Determine the active data path (Portable vs System mode).
    Returns the absolute Path where config, cache, logs, and glossary should be saved.
    """
    app_dir = get_app_dir()
    
    # 1. Force System Mode for AppImages (AppImage mounts are read-only)
    if is_appimage():
        return get_system_data_dir()
        
    # 2. Check for explicit portable marker
    if (app_dir / ".portable").exists():
        return app_dir
        
    # 3. Legacy Fallback: If config.json already exists in app_dir, 
    # and app_dir is writable, assume portable legacy mode to prevent data loss.
    if (app_dir / "config.json").exists() and os.access(app_dir, os.W_OK):
        return app_dir
        
    # 4. Default to System Data Directory for clean/first-time installations
    return get_system_data_dir()

def ensure_data_directories(data_path: Path):
    """Ensure essential data directories exist within the data path."""
    data_path.mkdir(parents=True, exist_ok=True)
    (data_path / "logs").mkdir(exist_ok=True)
    (data_path / "tm").mkdir(exist_ok=True)


import re
from typing import Optional

def normalize_project_name(name: str) -> str:
    """
    Strips version tags, duplicates, and platforms from a folder or file name 
    to produce a clean, stable project identifier.
    
    e.g. 'Lust Village v0.2.3-pc' -> 'Lust Village'
         'Game (1)' -> 'Game'
    """
    if not name:
        return ""
        
    # 1. Clean browser duplicates: e.g. "Game (1)" -> "Game"
    name = re.sub(r'\s*\(\d+\)\s*$', '', name)
    name = re.sub(r'\s*\[\d+\]\s*$', '', name)
    
    # 2. Strip version markers like v1.0, v1.0.0, 1.2, 0.4.5, 2026.04
    name = re.sub(r'(?i)\s+v?\d+(?:\.\d+)+(?:\s*-[a-zA-Z0-9]+)?\b', '', name)
    # also handle v1, v2 without dots if surrounded by spaces or dashes
    name = re.sub(r'(?i)\s+v\d+\b', '', name)
    name = re.sub(r'(?i)[-_\s]+v?\d+(?:\.\d+)+', '', name)
    
    # 3. Strip platform indicators
    name = re.sub(r'(?i)[-_\s]+(?:pc|win|mac|linux|android|windows|osx|universal|chrome|html5)\b', '', name)
    
    # 4. Strip build stage indicators
    name = re.sub(r'(?i)[-_\s]+(?:beta|alpha|preview|demo|patreon|sub|pirated|uncensored|mod|remastered)\b', '', name)
    
    # Clean up trailing spaces or dashes
    name = name.strip('-_ ')
    return name

def get_project_id(project_path: str, game_exe_path: Optional[str] = None) -> str:
    """
    Extracts a robust and stable project identifier for translation memory (cache).
    Tries strategies in order:
    1. options.rpy define config.save_directory or config.name
    2. clean game executable name
    3. first valid exe/py/sh file in project root
    4. normalized project folder name
    """
    if not project_path:
        return "default_project"

    # Strategy 1: Look inside game/options.rpy for config.save_directory or config.name
    options_path = os.path.join(project_path, 'game', 'options.rpy')
    if os.path.isfile(options_path):
        try:
            with open(options_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            # 1.1 Try config.save_directory
            match = re.search(r'define\s+config\.save_directory\s*=\s*["\']([^"\']+)["\']', content)
            if match:
                val = match.group(1).strip()
                if val:
                    return f"renpy_{val}"
            # 1.2 Try config.name
            match = re.search(r'define\s+config\.name\s*=\s*(?:_\()?["\']([^"\']+)["\']', content)
            if match:
                val = match.group(1).strip()
                if val:
                    cleaned = normalize_project_name(val)
                    if cleaned:
                        return f"renpy_{cleaned}"
        except Exception:
            pass
            
    # Strategy 2: If we have game_exe_path and it's a file, use the EXE name
    if game_exe_path and os.path.isfile(game_exe_path):
        exe_name = os.path.basename(game_exe_path)
        name_no_ext, _ = os.path.splitext(exe_name)
        if name_no_ext.lower() not in ("py", "exe", "sh", "run"):
            cleaned = normalize_project_name(name_no_ext)
            if cleaned:
                return cleaned

    # Strategy 3: Check root folder for Ren'Py executable files
    try:
        if os.path.isdir(project_path):
            files = os.listdir(project_path)
            candidates = []
            for f in files:
                f_path = os.path.join(project_path, f)
                if os.path.isfile(f_path) and f.lower().endswith(('.exe', '.sh', '.py')):
                    name_no_ext, _ = os.path.splitext(f)
                    if name_no_ext.lower() not in (
                        'opencode', 'unrpyc', 'python', 'run', 'unren',
                        'uninstall', 'setup', 'patch', 'game', 'renlocalizer', 'launcher'
                    ):
                        candidates.append(name_no_ext)
            if candidates:
                cleaned = normalize_project_name(candidates[0])
                if cleaned:
                    return cleaned
    except Exception:
        pass

    # Strategy 4: Fallback to normalized project directory basename
    base = os.path.basename(os.path.normpath(project_path))
    if base:
        cleaned = normalize_project_name(base)
        if cleaned:
            return cleaned

    return "default_project"
