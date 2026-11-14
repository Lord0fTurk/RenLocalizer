"""A stopped run is remembered so the interface can offer "Continue"."""
from pathlib import Path

import pytest

from src.core import run_state
from src.utils import path_manager


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(path_manager, "get_data_path", lambda *a, **k: tmp_path)
    return tmp_path


def stopped(total=100, translated=40):
    return {"total": total, "translated": translated, "pending": total - translated, "stopped": True, "partial": True}


def test_stopped_run_is_remembered(tmp_path):
    run_state.record_finish(str(tmp_path / "Game"), "turkish", stopped())
    entry = run_state.get(str(tmp_path / "Game"), "turkish")
    assert entry["done"] == 40 and entry["total"] == 100


def test_complete_run_forgets_it(tmp_path):
    game = str(tmp_path / "Game")
    run_state.record_finish(game, "turkish", stopped())
    run_state.record_finish(game, "turkish", {"total": 100, "translated": 100, "pending": 0, "stopped": False, "partial": False})
    assert run_state.get(game, "turkish") is None


def test_other_language_or_game_is_separate(tmp_path):
    run_state.record_finish(str(tmp_path / "A"), "turkish", stopped())
    assert run_state.get(str(tmp_path / "A"), "german") is None
    assert run_state.get(str(tmp_path / "B"), "turkish") is None


def test_partial_for_other_reasons_is_not_resumable(tmp_path):
    game = str(tmp_path / "Game")
    run_state.record_finish(game, "turkish", {"total": 10, "translated": 10, "pending": 0, "stopped": False, "partial": True})
    assert run_state.get(game, "turkish") is None


def test_path_spelling_does_not_matter(tmp_path):
    game = tmp_path / "Game"
    run_state.record_finish(str(game), "Turkish", stopped())
    assert run_state.get(str(game / ".." / "Game"), "turkish") is not None


def test_broken_file_reads_as_empty(data_dir):
    (Path(data_dir) / run_state.FILE_NAME).write_text("{not json", encoding="utf-8")
    assert run_state.get("x", "turkish") is None
    run_state.record_finish("x", "turkish", stopped())
    assert run_state.get("x", "turkish") is not None


def test_backend_exposes_the_stopped_run(tmp_path):
    from types import SimpleNamespace
    from src.backend.app_backend import AppBackend

    emitted = []
    fake = SimpleNamespace(
        _tl_mode=False, _tl_source_path="", _project_path=str(tmp_path / "Game"),
        _target_language="turkish", _resume_info={},
        _run_state_path=lambda: str(tmp_path / "Game"),
        resumeInfoChanged=SimpleNamespace(emit=lambda: emitted.append(1)),
        _refresh_estimate=lambda: None,
    )
    AppBackend._refresh_resume_info(fake)
    assert fake._resume_info == {} and not emitted
    run_state.record_finish(str(tmp_path / "Game"), "turkish", stopped())
    AppBackend._refresh_resume_info(fake)
    assert fake._resume_info == {"available": True, "done": 40, "total": 100} and emitted == [1]
    AppBackend._refresh_resume_info(fake)
    assert emitted == [1]  # unchanged: no needless signal
