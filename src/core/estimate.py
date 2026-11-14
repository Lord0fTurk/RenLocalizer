"""Rough "how long will this take" for the Translate page. Qt-free.

Engine speed depends on the engine, the model, the network and the machine, so
there is no table of guesses: the speed is learned from this machine's own
finished runs (lines sent to the engine per second, end to end) and the
estimate stays hidden until an engine has one. Cached lines are free, so only
lines still to translate are counted.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from src.utils.encoding import read_json_safely, save_json_safely

logger = logging.getLogger(__name__)

FILE_NAME = "engine_speed.json"
MIN_LINES = 30      # shorter runs say nothing about throughput
MIN_SECONDS = 8.0
SMOOTHING = 0.5     # weight of the newest run


def _file() -> Path:
    from src.utils import path_manager
    return Path(path_manager.get_data_path()) / FILE_NAME


def _load() -> dict:
    try:
        data = read_json_safely(str(_file()))
    except Exception as exc:
        logger.debug("engine speed unreadable: %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def record_run(engine_id: str, lines: int, seconds: float) -> bool:
    """Fold one finished run into the engine's speed. False when too short to count."""
    if not engine_id or lines < MIN_LINES or seconds < MIN_SECONDS:
        return False
    lps = lines / seconds
    data = _load()
    old = data.get(engine_id, {}).get("lps")
    if isinstance(old, (int, float)) and old > 0:
        lps = SMOOTHING * lps + (1 - SMOOTHING) * old
    data[engine_id] = {"lps": round(lps, 4)}
    try:
        path = _file()
        path.parent.mkdir(parents=True, exist_ok=True)
        save_json_safely(str(path), data)
    except Exception as exc:
        logger.debug("engine speed not saved: %s", exc)
        return False
    return True


def speed(engine_id: str) -> Optional[float]:
    """Learned lines per second, or None before this engine has a usable run."""
    value = _load().get(engine_id, {}).get("lps")
    return float(value) if isinstance(value, (int, float)) and value > 0 else None


def estimate_seconds(engine_id: str, lines: int) -> Optional[int]:
    lps = speed(engine_id)
    if not lps or lines <= 0:
        return None
    return max(1, int(round(lines / lps)))


def count_lines(game_dir: str, include_rpyc: bool = True) -> int:
    """Lines the parser finds in the game's scripts (a slight overcount: lines the
    pipeline later drops as technical text are still counted)."""
    from src.core.parser import RenPyParser
    parser = RenPyParser()
    results = parser.extract_combined(
        game_dir, include_rpy=True, include_rpyc=include_rpyc, include_deep_scan=False)
    return sum(len(entries) for entries in results.values())


def format_duration(seconds: int) -> str:
    """'45 s', '12 min', '2 h 10 min' (language-neutral units)."""
    if seconds < 60:
        return f"{seconds} s"
    minutes = int(round(seconds / 60))
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"
