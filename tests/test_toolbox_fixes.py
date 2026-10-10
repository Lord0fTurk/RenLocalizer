# -*- coding: utf-8 -*-
"""Toolbox tools work with the inputs the app actually gives them.

* Font check received the Ren'Py language name ("turkish") but its tables are
  keyed by ISO codes, so every font was reported as 0% / incompatible.
* All tools assumed the selected path was a folder; the dashboard also
  accepts the game EXE, where they found nothing or crashed.
* Glossary extractor read tl/ (translated text) and engine files, missed
  Character('Name') with single quotes, left names with an empty (= no
  protection) target, and wrote glossary.json into the game folder.
"""
import os
from types import SimpleNamespace

import pytest

from src.core.constants import is_renlocalizer_generated_script
from src.tools.font_helper import FontHelper

ARIAL = r"C:\Windows\Fonts\arial.ttf"


@pytest.mark.skipif(not os.path.isfile(ARIAL), reason="needs a system font with Turkish glyphs")
def test_font_check_accepts_renpy_language_names():
    helper = FontHelper()
    for name in ("turkish", "Turkish", "tr"):
        result = helper.check_font(ARIAL, name)
        assert result.supported and result.coverage_percent == 100, name
    assert helper.get_essential_chars("turkish") == helper.get_essential_chars("tr") != ""


def test_every_app_language_is_checkable_and_injectable():
    """The tables covered ~21 languages; the other ~114 were always 'incompatible'."""
    from src.tools.font_injector import FONT_CANDIDATES, _normalize_lang_code
    from src.tools.lang_scripts import font_candidates
    from src.utils.config import ConfigManager

    helper = FontHelper()
    for lang in ConfigManager.get_all_languages(None):
        name = lang["renpy"]
        assert helper.get_sample_text(name) or helper.check_font("missing.ttf", name).sample_text != f"Unknown language: {name}"
        assert _normalize_lang_code(name) in FONT_CANDIDATES or font_candidates(name)[0], name


@pytest.mark.parametrize("language,script,font", [
    ("persian", "Arabic", "Noto Sans Arabic"), ("hindi", "Devanagari", "Noto Sans Devanagari"),
    ("georgian", "Georgian", "Noto Sans Georgian"), ("dhivehi", "Thaana", "Noto Sans Thaana"),
    ("japanese", "Japanese", "Noto Sans JP"), ("chinese", "HanSimplified", "Noto Sans SC"),
    ("serbian", "Cyrillic", "Noto Sans"), ("dutch", "Latin", "Noto Sans"),
])
def test_language_to_script_and_font(language, script, font):
    from src.tools.lang_scripts import font_candidates, script_of

    assert script_of(language) == script
    assert font_candidates(language)[0][0][0] == font


def test_injector_picks_script_font_for_untabled_language(tmp_path, monkeypatch):
    from src.tools import font_injector

    tried = []

    def fake_download(family, target_dir):
        tried.append(family)
        (target_dir / "NotoSansDevanagari-Regular.ttf").write_bytes(b"\0")
        return True, "NotoSansDevanagari-Regular.ttf"

    monkeypatch.setattr(font_injector, "_download_font", fake_download)
    (tmp_path / "game").mkdir()
    result = font_injector.inject_font(str(tmp_path / "game"), "hindi")
    assert result["success"] and tried == ["Noto Sans Devanagari"]
    assert 'translate hindi python:' in (tmp_path / "game" / "zzz_renlocalizer_font.rpy").read_text(encoding="utf-8")


@pytest.mark.skipif(not os.path.isfile(ARIAL), reason="needs Arial")
def test_check_uses_the_translations_own_characters(tmp_path):
    """Persian text passes with Arial; one Devanagari letter in it must fail and be named."""
    from src.tools.font_helper import check_font_for_project

    game = tmp_path / "game"
    (game / "fonts").mkdir(parents=True)
    (game / "tl" / "persian").mkdir(parents=True)
    import shutil
    shutil.copy(ARIAL, game / "fonts" / "arial.ttf")
    tl_file = game / "tl" / "persian" / "script.rpy"
    tl_file.write_text(
        'translate persian start_1:\n    # e "Hello"\n    e "سلام، حال شما چطور است؟ {b}گل{/b}"\n', encoding="utf-8")
    summary = check_font_for_project(str(game), "persian")
    assert summary["basis"] == "translation" and summary["compatible_fonts"] == 1

    tl_file.write_text(
        'translate persian start_1:\n    e "سلام क"\n', encoding="utf-8")
    summary = check_font_for_project(str(game), "persian")
    assert summary["incompatible_fonts"] == 1
    assert "क" in summary["missing_by_font"]["arial.ttf"]


MSGOTHIC = r"C:\Windows\Fonts\msgothic.ttc"


@pytest.mark.skipif(not os.path.isfile(MSGOTHIC), reason="needs a .ttc collection")
def test_font_collections_are_readable():
    result = FontHelper().check_font(MSGOTHIC, "japanese")
    assert result.supported and result.coverage_percent == 100


def test_tools_resolve_game_dir_from_exe(tmp_path):
    from src.backend.app_backend import AppBackend

    (tmp_path / "game").mkdir()
    exe = tmp_path / "Game.exe"
    exe.write_bytes(b"")
    assert AppBackend._tool_game_dir(SimpleNamespace(_project_path=str(exe))) == str(tmp_path / "game")


def test_glossary_extractor_reads_only_the_game(tmp_path):
    from src.tools.glossary_extractor.extractor import GlossaryExtractor

    game = tmp_path / "game"
    (game / "tl" / "turkish").mkdir(parents=True)
    (game / "renpy" / "common").mkdir(parents=True)
    (game / "script.rpy").write_text(
        "define r = Character('Rose')\n"
        # Mid-sentence on purpose: sentence-initial capitals are not counted.
        'label start:\n    r "We reach Avalon soon."\n    "The road to Avalon is far."\n    "We love Avalon."\n',
        encoding="utf-8",
    )
    # Translated text and engine UI must not become glossary terms.
    (game / "tl" / "turkish" / "script.rpy").write_text(
        'translate turkish strings:\n    old "x"\n    new "Kaledeki Ejderha Ejderha Ejderha"\n', encoding="utf-8")
    (game / "renpy" / "common" / "00gui.rpy").write_text(
        '"Preferences" "Preferences" "Preferences"\n', encoding="utf-8")

    terms = GlossaryExtractor().extract_from_directory(str(game), min_occurrence=3)
    assert terms.get("Rose") == "Rose", "names are protected as themselves"
    assert terms.get("Avalon") == ""
    assert "Ejderha" not in terms and "Preferences" not in terms
    assert not (game / "glossary.json").exists()


def test_font_injector_output_is_not_rescanned():
    assert is_renlocalizer_generated_script("zzz_renlocalizer_font.rpy")
    assert is_renlocalizer_generated_script("zzz_renlocalizer_font.rpyc")
