"""Remembers which game/language runs stopped before they finished.

The pipeline already resumes by itself: translated lines are in the cache, so a
second run only sends what is left. This store only records *that* a run was
left unfinished (and how far it got) so the interface can say "Continue".
Qt-free; one small JSON file in the data folder.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

from src.utils.encoding import read_json_safely, save_json_safely

logger = logging.getLogger(__name__)

FILE_NAME = "run_state.json"
MAX_ENTRIES = 50


def _file() -> Path:
    from src.utils import path_manager
    return Path(path_manager.get_data_path()) / FILE_NAME


def make_key(project_path: str, language: str) -> str:
    path = os.path.normcase(os.path.normpath(os.path.abspath(project_path or "")))
    return f"{path}|{(language or '').strip().lower()}"


def _load() -> dict:
    try:
        data = read_json_safely(str(_file()))
    except Exception as exc:
        logger.debug("run state unreadable: %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    if len(data) > MAX_ENTRIES:
        newest = sorted(data.items(), key=lambda kv: kv[1].get("updated", 0), reverse=True)[:MAX_ENTRIES]
        data = dict(newest)
    try:
        path = _file()
        path.parent.mkdir(parents=True, exist_ok=True)
        save_json_safely(str(path), data)
    except Exception as exc:
        logger.debug("run state not saved: %s", exc)


def get(project_path: str, language: str) -> Optional[dict]:
    """``{'done': int, 'total': int, 'updated': float}`` for an unfinished run, else None."""
    if not project_path:
        return None
    entry = _load().get(make_key(project_path, language))
    if not isinstance(entry, dict) or int(entry.get("total", 0)) <= 0:
        return None
    return entry


def record_finish(project_path: str, language: str, stats: dict) -> None:
    """Keep an entry while lines are left; drop it once the run is complete."""
    if not project_path:
        return
    key = make_key(project_path, language)
    data = _load()
    total = int(stats.get("total", 0) or 0)
    done = int(stats.get("translated", 0) or 0)
    left = bool(stats.get("stopped")) or int(stats.get("pending", 0) or 0) > 0
    unfinished = bool(stats.get("partial")) and total > 0 and left
    if unfinished:
        data[key] = {"done": min(done, total), "total": total, "updated": time.time()}
    elif key in data:
        del data[key]
    else:
        return
    _save(data)


def clear(project_path: str, language: str) -> None:
    data = _load()
    if data.pop(make_key(project_path, language), None) is not None:
        _save(data)
