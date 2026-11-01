import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.core.pipeline.orchestrator import TranslationPipeline


def test_completion_stats_playable_calculation():
    pipeline = TranslationPipeline.__new__(TranslationPipeline)
    pipeline._run_counts = {"engine_failed": 2, "guard_blocked": 1}
    pipeline._last_syntax_issues = []

    # Mock TranslationFile entries
    file_mock = SimpleNamespace(
        entries=[
            # 8 translated
            SimpleNamespace(needs_translation=lambda: False, is_source_copy=lambda: False),
            SimpleNamespace(needs_translation=lambda: False, is_source_copy=lambda: False),
            SimpleNamespace(needs_translation=lambda: False, is_source_copy=lambda: False),
            SimpleNamespace(needs_translation=lambda: False, is_source_copy=lambda: False),
            SimpleNamespace(needs_translation=lambda: False, is_source_copy=lambda: False),
            SimpleNamespace(needs_translation=lambda: False, is_source_copy=lambda: False),
            SimpleNamespace(needs_translation=lambda: False, is_source_copy=lambda: False),
            SimpleNamespace(needs_translation=lambda: False, is_source_copy=lambda: False),
            # 1 same_as_source (names/sounds)
            SimpleNamespace(needs_translation=lambda: False, is_source_copy=lambda: True),
            # 1 empty (failed)
            SimpleNamespace(needs_translation=lambda: True, is_source_copy=lambda: False),
        ]
    )

    stats = pipeline._completion_stats([file_mock], failed_paths=[])
    assert stats["total"] == 10
    assert stats["translated"] == 8
    assert stats["same_as_source"] == 1
    assert stats["empty"] == 1
    assert stats["pending"] == 3
    assert stats["playable_count"] == 9  # 8 translated + 1 same_as_source
    assert stats["playable_pct"] == 90.0  # 9 / 10 = 90.0%


def test_completion_stats_locales_parity():
    locales_dir = Path("locales")
    required_keys = {
        "completion_playable_rate",
        "completion_badge_translated",
        "completion_badge_identical",
        "completion_desc_identical",
        "completion_tooltip_identical",
        "completion_badge_protected",
        "completion_desc_protected",
        "completion_saved_files",
        "completion_support_text",
        "completion_support_btn",
        "completion_support_hide",
        "nav_patreon_support",
        "nav_patreon_sub",
    }
    for locale_path in locales_dir.glob("*.json"):
        data = json.loads(locale_path.read_text(encoding="utf-8"))
        missing = required_keys - set(data.keys())
        assert not missing, f"{locale_path.name} is missing keys: {missing}"


def test_app_backend_completion_stats_property():
    from src.backend.app_backend import AppBackend
    from PyQt6.QtWidgets import QApplication
    import sys

    app = QApplication.instance() or QApplication(sys.argv[:1])
    backend = AppBackend(parent=app)
    backend.config.save_config = lambda *a, **k: True  # the run counter must not touch the user's config

    signal_received = []
    backend.completionStatsChanged.connect(lambda: signal_received.append(True))

    mock_result = SimpleNamespace(
        success=True,
        message="Translation complete",
        stats={
            "total": 100,
            "translated": 90,
            "same_as_source": 8,
            "empty": 2,
            "pending": 2,
            "guard_blocked": 2,
            "engine_failed": 0,
            "playable_count": 98,
            "playable_pct": 98.0,
            "saved_count": 15,
            "partial": True,
        },
        output_path="/tmp/out",
        error="",
    )

    backend._on_pipeline_finished(mock_result)

    assert len(signal_received) > 0
    st = backend.completionStats
    assert st["total"] == 100
    assert st["translated"] == 90
    assert st["same_as_source"] == 8
    assert st["playable_pct"] == 98.0
    assert st["guard_blocked"] == 2


def test_support_row_appears_from_the_third_finished_run_until_dismissed():
    from src.backend.app_backend import AppBackend
    from PyQt6.QtWidgets import QApplication
    import sys

    app = QApplication.instance() or QApplication(sys.argv[:1])
    backend = AppBackend(parent=app)
    backend.config.save_config = lambda *a, **k: True  # keep the user's config untouched
    backend.send_desktop_notification = lambda *a, **k: None
    backend.config.app_settings.completed_runs = 0
    backend.config.app_settings.hide_support_prompt = False

    def finish(success=True, translated=10):
        result = SimpleNamespace(success=success, message="", output_path="", error="",
                                 stats={"total": 10, "translated": translated})
        backend._on_pipeline_finished(result)
        return backend.completionStats["show_support"]

    seen = [finish(), finish()]
    seen.append(finish(translated=0))  # nothing translated: not counted
    seen.append(finish())
    seen.append(finish(success=False))  # failed runs never ask
    backend.setHideSupportPrompt(True)
    seen.append(finish())
    assert seen == [False, False, False, True, False, False]
    assert backend.config.app_settings.completed_runs == 4
