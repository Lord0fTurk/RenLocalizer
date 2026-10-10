# -*- coding: utf-8 -*-
"""CLI parity with the GUI (GitHub issue #20 and related CLI drift).

* .rpa archives were never extracted (auto_unren hard-coded False) and the
  run still reported 100% — only Ren'Py engine strings were translated.
* .rpyc reading, proxy and deep-scan settings were ignored.
* Options given before "translate" were overwritten by the subcommand.
* The documented "RenLocalizerCLI <game>" short form did not parse.
* OpenAI/DeepSeek never received the API key; DeepSeek hit OpenAI's URL;
  Gemini was missing; TL mode was unreachable; failures exited with 0.
"""
import os
import sys
from types import SimpleNamespace
from unittest import mock

import pytest

import src.cli_main as cli
from src.core.translator import TranslationEngine
from src.utils.config import ConfigManager


def _parse(argv):
    captured = {}

    def fake_run(args):
        captured["args"] = args
        return 0

    with mock.patch.object(sys, "argv", ["cli", *argv]), mock.patch.object(cli, "run_translate_command", fake_run):
        cli.main()
    return captured["args"]


def test_options_before_the_command_are_kept():
    args = _parse(["-e", "bing", "-t", "de", "translate", "GAME"])
    assert (args.engine, args.target_lang, args.input_path) == ("bing", "de", "GAME")


def test_short_form_without_command_parses():
    args = _parse(["GAME", "-t", "ru"])
    assert (args.input_path, args.target_lang, args.engine) == ("GAME", "ru", "google")


def test_extraction_flags_default_to_settings_and_can_be_forced():
    args = _parse(["translate", "GAME"])
    assert args.extract_rpa is None and args.rpyc is None
    assert cli._flag_or(args, "extract_rpa", True) is True

    args = _parse(["translate", "GAME", "--no-extract-rpa", "--rpyc"])
    assert cli._flag_or(args, "extract_rpa", True) is False
    assert cli._flag_or(args, "rpyc", False) is True


def test_tl_folders_are_detected(tmp_path):
    tl_lang = tmp_path / "game" / "tl" / "russian"
    tl_lang.mkdir(parents=True)
    assert cli._looks_like_tl_folder(str(tl_lang))
    assert cli._looks_like_tl_folder(str(tl_lang.parent))
    assert not cli._looks_like_tl_folder(str(tmp_path))
    assert not cli._looks_like_tl_folder(str(tmp_path / "game"))


def _ns(**kw):
    base = dict(api_key=None, model=None, base_url=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_ai_overrides_and_env_keys(monkeypatch):
    config = ConfigManager()
    config.api_keys.openai_api_key = ""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    cli._apply_ai_overrides(config, "deepseek", _ns(model="deepseek-chat"))
    assert config.api_keys.openai_api_key == "sk-env"
    assert config.translation_settings.openai_model == "deepseek-chat"

    cli._apply_ai_overrides(config, "local_llm", _ns(base_url="http://127.0.0.1:1234/v1"))
    assert config.translation_settings.local_llm_url == "http://127.0.0.1:1234/v1"
    assert config.translation_settings.local_llm_mode == "external"


def test_deepseek_gets_its_own_translator_and_the_key():
    from src.core.ai_translator import DeepSeekTranslator

    config = ConfigManager()
    config.api_keys.openai_api_key = "sk-test"
    config.translation_settings.openai_base_url = ""
    _, manager = cli.setup_engines(config, "deepseek")
    translator = manager.translators[TranslationEngine.OPENAI]
    assert isinstance(translator, DeepSeekTranslator)
    assert translator.api_key == "sk-test"
    assert "deepseek" in translator._base_url


def test_gemini_is_available_in_cli():
    pytest.importorskip("google.genai")
    config = ConfigManager()
    config.api_keys.gemini_api_key = "fake"
    _, manager = cli.setup_engines(config, "gemini")
    gemini = manager.translators[TranslationEngine.GEMINI]
    assert gemini.fallback_translator is manager.translators[TranslationEngine.GOOGLE]


# ── Pipeline side of issue #20 ─────────────────────────────────────────────

def _run_pipeline(project, auto_unren):
    from PyQt6.QtCore import QCoreApplication
    from src.core.pipeline.orchestrator import TranslationPipeline
    from src.core.translator import TranslationManager

    QCoreApplication.instance() or QCoreApplication([])
    pipeline = TranslationPipeline(ConfigManager(), TranslationManager())
    pipeline.configure(game_exe_path=str(project), target_language="spanish",
                       auto_unren=auto_unren, include_rpyc=True)
    return pipeline._run_pipeline()


def test_archive_only_game_with_extraction_off_fails_loudly(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    (game / "archive.rpa").write_bytes(b"RPA-3.0 0000000000000022 42424242\n")
    # Leftovers that used to make the folder look like it had scripts.
    (game / "zzz_spanish_language.rpy").write_text("init python:\n    pass\n", encoding="utf-8")
    (game / "tl" / "spanish").mkdir(parents=True)
    (game / "tl" / "spanish" / "common.rpy").write_text("# x\n", encoding="utf-8")

    result = _run_pipeline(tmp_path, auto_unren=False)
    assert not result.success
    assert ".rpa" in result.message


def test_game_without_any_scripts_fails_instead_of_translating_engine_files(tmp_path):
    game = tmp_path / "game"
    (game / "renpy" / "common").mkdir(parents=True)
    (game / "renpy" / "common" / "00gui.rpy").write_text('label x:\n    "Engine text"\n', encoding="utf-8")

    result = _run_pipeline(tmp_path, auto_unren=True)
    assert not result.success
