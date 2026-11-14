"""The pre-run estimate: speed is learned from real runs, never guessed."""
import pytest

from src.core import estimate
from src.utils import path_manager


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(path_manager, "get_data_path", lambda *a, **k: tmp_path)
    return tmp_path


def test_no_estimate_before_a_measured_run():
    assert estimate.speed("google") is None
    assert estimate.estimate_seconds("google", 1000) is None


def test_short_runs_do_not_count():
    assert not estimate.record_run("google", 10, 30)
    assert not estimate.record_run("google", 500, 2)
    assert estimate.speed("google") is None


def test_learns_and_smooths():
    assert estimate.record_run("google", 600, 60)          # 10 lines/s
    assert estimate.estimate_seconds("google", 1000) == 100
    estimate.record_run("google", 1200, 60)                # 20 lines/s -> 15
    assert estimate.speed("google") == pytest.approx(15.0)
    assert estimate.speed("openai") is None                # per engine


def test_nothing_left_means_no_estimate():
    estimate.record_run("google", 600, 60)
    assert estimate.estimate_seconds("google", 0) is None


@pytest.mark.parametrize("sec,text", [(45, "45 s"), (90, "2 min"), (3600, "1 h"), (7800, "2 h 10 min")])
def test_format_duration(sec, text):
    assert estimate.format_duration(sec) == text


def test_count_lines_reads_the_scripts(tmp_path):
    game = tmp_path / "G" / "game"
    game.mkdir(parents=True)
    body = ['define e = Character("Eileen")', "label start:"] + [f'    e "Line number {i} of the story."' for i in range(12)]
    (game / "script.rpy").write_text("\n".join(body) + "\n", encoding="utf-8")
    assert estimate.count_lines(str(game), include_rpyc=False) >= 12
