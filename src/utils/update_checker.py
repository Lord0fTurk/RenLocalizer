"""Update checker for RenLocalizer.

Fetches the latest release tag from GitHub and compares it to the current
application version. Uses the GitHub API first and falls back to the releases
HTML page if needed.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Optional, Tuple

import requests


RELEASES_URL = "https://github.com/Lord0fTurk/RenLocalizer/releases"
API_URL = "https://api.github.com/repos/Lord0fTurk/RenLocalizer/releases/latest"


@dataclass
class UpdateCheckResult:
    current_version: str
    latest_version: str
    update_available: bool
    release_url: str
    error: Optional[str] = None


def _parse_version(version: str) -> Tuple[int, ...]:
    parts = re.findall(r"\d+", version or "")
    if not parts:
        return (0,)
    return tuple(int(p) for p in parts)


def _is_newer(latest: str, current: str) -> bool:
    latest_parts = _parse_version(latest)
    current_parts = _parse_version(current)
    length = max(len(latest_parts), len(current_parts))
    latest_parts += (0,) * (length - len(latest_parts))
    current_parts += (0,) * (length - len(current_parts))
    return latest_parts > current_parts


def _fetch_latest_release(timeout: int = 10) -> Tuple[str, str]:
    headers = {"User-Agent": "RenLocalizer"}

    # Preferred: GitHub API
    try:
        response = requests.get(API_URL, timeout=timeout, headers=headers)
        if response.status_code == 200:
            payload = response.json() or {}
            tag = (payload.get("tag_name") or payload.get("name") or "").strip()
            url = (payload.get("html_url") or RELEASES_URL).strip()
            if tag:
                return tag, url or RELEASES_URL
    except Exception as exc:
        logging.getLogger(__name__).debug("Update check failed: %s", exc)

    # Fallback: releases HTML page
    response = requests.get(RELEASES_URL, timeout=timeout, headers=headers)
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}")

    match = re.search(r"/releases/tag/([^\"<>\s]+)", response.text)
    if not match:
        raise RuntimeError("Latest release tag not found on releases page")

    return match.group(1), RELEASES_URL


def check_for_updates(current_version: str, timeout: int = 10) -> UpdateCheckResult:
    try:
        latest_version, url = _fetch_latest_release(timeout=timeout)
    except Exception as exc:
        return UpdateCheckResult(
            current_version=current_version,
            latest_version="",
            update_available=False,
            release_url=RELEASES_URL,
            error=str(exc),
        )

    return UpdateCheckResult(
        current_version=current_version,
        latest_version=latest_version,
        update_available=_is_newer(latest_version, current_version),
        release_url=url or RELEASES_URL,
        error=None,
    )
