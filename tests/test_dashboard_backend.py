# -*- coding: utf-8 -*-
"""AppBackend side of the dashboard: project card, recent projects, game launch."""
import os
import sys

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture
def backend(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from src.backend.app_backend import AppBackend

    b = AppBackend(parent=app)
    # never touch the real config.json from a test
    monkeypatch.setattr(b.config, "save_config", lambda *a, **k: True)
    b.config.app_settings.recent_projects = []
    # yield, not return: the app (the backend's parent) must outlive the test
    yield b


def test_recent_projects_newest_first_without_duplicates(backend):
    seen = []
    backend.recentProjectsChanged.connect(lambda: seen.append(list(backend.recentProjects)))
    for path in ("C:/Games/A", "C:/Games/B", "C:/Games/A"):
        backend._remember_recent_project(path)
    assert backend.recentProjects == ["C:/Games/A", "C:/Games/B"]
    assert len(seen) == 3
    for n in range(12):
        backend._remember_recent_project(f"C:/Games/{n}")
    assert len(backend.recentProjects) == 8 and backend.recentProjects[0] == "C:/Games/11"
    backend.clearRecentProjects()
    assert backend.recentProjects == []


def test_only_the_latest_inspection_is_shown_and_remembered(backend):
    backend._project_info_gen = 5
    backend._on_project_info_ready(4, {"ok": True, "path": "C:/Games/Old", "notices": []})
    assert backend.projectInfo == {} and backend.recentProjects == []
    backend._on_project_info_ready(5, {"ok": True, "path": "C:/Games/New", "notices": []})
    assert backend.projectInfo["path"] == "C:/Games/New"
    assert backend.recentProjects == ["C:/Games/New"]
    backend._project_info_gen = 6
    backend._on_project_info_ready(6, {"ok": False, "path": "C:/Nope", "notices": []})
    assert backend.recentProjects == ["C:/Games/New"]  # a folder that is not a game is not remembered


def test_launch_without_a_launcher_reports_instead_of_failing(backend):
    logs = []
    backend.logMessage.connect(lambda level, msg: logs.append(level))
    backend._project_info = {"ok": True, "launcher": ""}
    assert backend.launchGame() is False
    assert logs == ["warning"]
