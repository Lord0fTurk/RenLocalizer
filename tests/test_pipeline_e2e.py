# -*- coding: utf-8 -*-
"""End-to-end integration tests for TranslationPipeline."""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.core.pipeline.orchestrator import TranslationPipeline, PipelineStage, PipelineResult
from src.core.translator import (
    TranslationEngine,
    TranslationManager,
    TranslationResult,
)
from src.utils.config import ConfigManager


@pytest.fixture
def minimal_game(tmp_path):
    """Minimal Ren'Py game folder structure for testing."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)

    script_file = game_dir / "script.rpy"
    script_file.write_text(
        'label start:\n'
        '    e "Hello world!"\n'
        '    "Welcome to the game."\n'
        '    return\n',
        encoding="utf-8"
    )

    fake_exe = tmp_path / "TestGame.exe"
    fake_exe.write_text("dummy", encoding="utf-8")

    return fake_exe


from src.core.translator import GoogleTranslator


@pytest.fixture
def mock_translator():
    """Fixtured mock translator that returns predictable translations."""
    async def _translate_batch(requests):
        return [
            TranslationResult(
                original_text=r.text,
                translated_text=f"[TR] {r.text}",
                source_lang=r.source_lang,
                target_lang=r.target_lang,
                engine=r.engine,
                success=True,
            )
            for r in requests
        ]
    return _translate_batch


@pytest.fixture
def mock_translate_command(tmp_path):
    """Fixtured mock translate command that creates a tl/ directory."""
    def _run_translate_cmd(project_path, target_lang="turkish"):
        tl_dir = Path(project_path) / "game" / "tl" / target_lang
        tl_dir.mkdir(parents=True, exist_ok=True)
        (tl_dir / "script.rpy").write_text(
            '# game/script.rpy:2\n'
            'translate turkish start_636ae3f5:\n'
            '    # e "Hello world!"\n'
            '    e ""\n\n'
            '# game/script.rpy:3\n'
            'translate turkish start_a1b2c3d4:\n'
            '    # "Welcome to the game."\n'
            '    ""\n\n',
            encoding="utf-8"
        )
        return True
    return _run_translate_cmd


class TestPipelineE2E:
    """End-to-end pipeline integration tests."""

    def test_full_pipeline_success(self, minimal_game, mock_translator, mock_translate_command):
        """Pipeline runs all stages to completion with a valid game."""
        config = ConfigManager()
        translation_manager = TranslationManager(config_manager=config)
        pipeline = TranslationPipeline(config=config, translation_manager=translation_manager)

        pipeline.configure(
            game_exe_path=str(minimal_game),
            target_language="turkish",
            source_language="en",
            engine=TranslationEngine.GOOGLE,
            auto_unren=False,
        )

        # Capture the result from the finished signal
        result_holder = []

        def on_finished(result: PipelineResult):
            result_holder.append(result)

        pipeline.finished.connect(on_finished)

        with patch.object(GoogleTranslator, "translate_batch", side_effect=mock_translator):
            with patch.object(pipeline, "_run_translate_command", side_effect=mock_translate_command):
                pipeline.run()

        assert len(result_holder) == 1, "Pipeline should emit exactly one finished signal"
        result = result_holder[0]
        assert result.success, f"Pipeline should succeed: {result.message}"
        assert result.stage == PipelineStage.COMPLETED, f"Expected COMPLETED, got {result.stage}"

        # Verify output files exist
        tl_dir = minimal_game.parent / "game" / "tl" / "turkish"
        assert tl_dir.exists(), "tl/turkish/ directory should be created"
        has_rpy = (tl_dir / "script.rpy").exists()
        has_strings_json = (tl_dir / "strings.json").exists()
        assert has_rpy or has_strings_json, "At least one output file should be generated"

    def test_pipeline_handles_empty_game(self, tmp_path):
        """Pipeline should fail gracefully with an empty/invalid game directory."""
        empty_dir = tmp_path / "empty_game"
        empty_dir.mkdir(parents=True, exist_ok=True)
        (empty_dir / "fake.exe").write_text("dummy", encoding="utf-8")

        config = ConfigManager()
        translation_manager = TranslationManager(config_manager=config)
        pipeline = TranslationPipeline(config=config, translation_manager=translation_manager)

        pipeline.configure(
            game_exe_path=str(empty_dir / "fake.exe"),
            target_language="turkish",
            engine=TranslationEngine.GOOGLE,
            auto_unren=False,
        )

        result_holder = []

        def on_finished(result: PipelineResult):
            result_holder.append(result)

        pipeline.finished.connect(on_finished)
        pipeline.run()

        assert len(result_holder) == 1
        result = result_holder[0]
        # Should not crash; may complete with warning or fail early
        assert isinstance(result, PipelineResult)

    def test_pipeline_tl_mode_execution(self, tmp_path, mock_translator):
        """Pipeline should route to translate_existing_tl when is_tl_mode is True."""
        tl_dir = tmp_path / "game" / "tl" / "turkish"
        tl_dir.mkdir(parents=True, exist_ok=True)
        (tl_dir / "script.rpy").write_text(
            '# game/script.rpy:2\n'
            'translate turkish start_636ae3f5:\n'
            '    # e "Hello world!"\n'
            '    e ""\n',
            encoding="utf-8"
        )

        config = ConfigManager()
        translation_manager = TranslationManager(config_manager=config)
        pipeline = TranslationPipeline(config=config, translation_manager=translation_manager)

        pipeline.configure(
            game_exe_path=str(tl_dir),
            target_language="turkish",
            source_language="en",
            engine=TranslationEngine.GOOGLE,
            auto_unren=False,
            is_tl_mode=True,
        )

        result_holder = []
        pipeline.finished.connect(lambda r: result_holder.append(r))

        with patch.object(GoogleTranslator, "translate_batch", side_effect=mock_translator):
            pipeline.run()

        assert len(result_holder) == 1
        result = result_holder[0]
        assert result.success, f"TL mode retranslation should succeed: {result.message}"
        assert result.stage == PipelineStage.COMPLETED

    def test_extract_raw_mapping_both_cases_preserved(self):
        """Ensure case variants ('Hello' and 'hello') are both preserved in mapping."""
        from types import SimpleNamespace
        from src.core.pipeline.saving import _extract_raw_mapping

        entry1 = SimpleNamespace(original_text="Hello", translated_text="Merhaba")
        entry2 = SimpleNamespace(original_text="hello", translated_text="Selam")
        tfile = SimpleNamespace(file_path="script.rpy", entries=[entry1, entry2])

        mapping, skipped_corrupt, skipped_counts, _ = _extract_raw_mapping([tfile])
        assert "Hello" in mapping
        assert mapping["Hello"] == "Merhaba"
        assert "hello" in mapping
        assert mapping["hello"] == "Selam"
        assert skipped_corrupt == 0

    def test_extract_raw_mapping_duplicate_key_conflict(self):
        """Ensure exact duplicate keys with differing translations preserve the first."""
        from types import SimpleNamespace
        from src.core.pipeline.saving import _extract_raw_mapping

        entry1 = SimpleNamespace(original_text="Save", translated_text="Kaydet")
        entry2 = SimpleNamespace(original_text="Save", translated_text="Sakla")
        tfile = SimpleNamespace(file_path="script.rpy", entries=[entry1, entry2])

        mapping, skipped_corrupt, skipped_counts, _ = _extract_raw_mapping([tfile])
        assert "Save" in mapping
        assert mapping["Save"] == "Kaydet"
        assert skipped_corrupt == 1
        assert skipped_counts["duplicate_key_conflict"] == 1
