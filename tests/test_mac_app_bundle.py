# -*- coding: utf-8 -*-
"""macOS Ren'Py apps keep the game in Game.app/Contents/Resources/autorun.

Ren'Py's mac package (launcher/game/distribute.rpy) has no game/ next to the
app, so selecting Game.app used to end in "game/ folder not found".
"""
import os
from types import SimpleNamespace

from src.utils.path_manager import get_project_id, resolve_project_root, unwrap_mac_app


def _mac_game(tmp_path, name="Edge of Desire.app"):
    app = tmp_path / name
    autorun = app / "Contents" / "Resources" / "autorun"
    (autorun / "game" / "tl" / "turkish").mkdir(parents=True)
    (autorun / "game" / "script.rpy").write_text('label start:\n    "Hello."\n', encoding="utf-8")
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / "Edge of Desire").write_text("#!/bin/sh\n", encoding="utf-8")
    return app, autorun


def test_app_and_files_inside_it_point_at_autorun(tmp_path):
    app, autorun = _mac_game(tmp_path)
    assert unwrap_mac_app(str(app)) == str(autorun)
    assert unwrap_mac_app(str(app) + os.sep) == str(autorun)
    assert unwrap_mac_app(str(app / "Contents" / "MacOS" / "Edge of Desire")) == str(autorun)


def test_paths_inside_autorun_are_left_alone(tmp_path):
    _, autorun = _mac_game(tmp_path)
    for inner in (autorun, autorun / "game", autorun / "game" / "tl" / "turkish"):
        assert unwrap_mac_app(str(inner)) == str(inner)


def test_other_paths_are_left_alone(tmp_path):
    plain = tmp_path / "Game-0.1-pc"
    (plain / "game").mkdir(parents=True)
    not_renpy = tmp_path / "Other.app"
    (not_renpy / "Contents").mkdir(parents=True)
    assert unwrap_mac_app(str(plain)) == str(plain)
    assert unwrap_mac_app(str(not_renpy)) == str(not_renpy)
    assert unwrap_mac_app("") == ""


def test_project_root_and_cache_id_follow_the_app(tmp_path):
    app, autorun = _mac_game(tmp_path)
    assert resolve_project_root(str(app)) == str(autorun)
    # No options.rpy and no launcher script: named after the app, not "autorun".
    assert get_project_id(str(autorun)) == "Edge of Desire"


def test_gui_accepts_the_app(tmp_path):
    from src.backend.app_backend import AppBackend

    app, autorun = _mac_game(tmp_path)
    logs = []
    stub = SimpleNamespace(
        _project_path="", _tl_mode=False, _tl_source_path="",
        config=SimpleNamespace(
            app_settings=SimpleNamespace(last_input_directory=""),
            save_config=lambda: None,
        ),
        logMessage=SimpleNamespace(emit=lambda level, msg: logs.append((level, msg))),
        _t=lambda key, default: default,
    )
    AppBackend.setProjectPath(stub, str(app))

    assert stub._project_path == str(autorun)
    assert not stub._tl_mode
    assert AppBackend._tool_game_dir(stub) == str(autorun / "game")
    assert any(str(autorun) in msg for _, msg in logs)
    assert not any(level == "warning" for level, _ in logs)


def test_pipeline_and_cli_accept_the_app(tmp_path):
    from src.cli_main import _resolve_game_dir
    from src.core.pipeline.orchestrator import TranslationPipeline

    app, autorun = _mac_game(tmp_path)
    stub = SimpleNamespace(log_message=SimpleNamespace(emit=lambda *a: None), config=None)
    TranslationPipeline.configure(stub, game_exe_path=str(app), target_language="turkish")
    assert stub.project_path == str(autorun)

    assert _resolve_game_dir(str(app)) == str(autorun / "game")
