# -*- coding: utf-8 -*-
"""Character display names stay untranslated unless translate_character_names is on.

User report (2.8.18): "the tool also translates the characters' names".
The regular extractor already honoured the setting, but deep scan, the AST
pass and the .rpyc reader each picked Character("Name") up again, and
AutoProtect only looked at speaker variables ("e", "mc"), never at the
display names that appear inside dialogue.
"""
from src.core.parser import RenPyParser, collect_character_display_names
from src.utils.config import ConfigManager

SCRIPT = (
    "define r = Character('Rose', color='#c8ffc8')\n"
    'define h = Character(_("Hope"))\n'
    'define p = Character("[player_name]")\n'
    "init python:\n"
    '    w = DynamicCharacter("Will")\n'
    "label start:\n"
    '    r "Rose looked at Hope and smiled."\n'
    "    return\n"
)


def _texts(tmp_path, translate_names):
    game = tmp_path / "game"
    game.mkdir(exist_ok=True)
    (game / "script.rpy").write_text(SCRIPT, encoding="utf-8")
    config = ConfigManager()
    config.translation_settings.translate_character_names = translate_names
    results = RenPyParser(config).extract_combined(
        str(game), include_rpy=True, include_rpyc=True, include_deep_scan=True,
        recursive=True, exclude_dirs=["tl"],
    )
    return {e["text"] for entries in results.values() for e in entries}


def test_names_not_extracted_by_any_pass_when_setting_is_off(tmp_path):
    texts = _texts(tmp_path, translate_names=False)
    assert "Rose looked at Hope and smiled." in texts
    assert not {"Rose", "Hope", "Will"} & texts


def test_names_extracted_when_user_opts_in(tmp_path):
    texts = _texts(tmp_path, translate_names=True)
    assert {"Rose", "Hope"} <= texts


def test_collect_display_names_for_autoprotect(tmp_path):
    game = tmp_path / "game"
    (game / "tl" / "turkish").mkdir(parents=True)
    (game / "script.rpy").write_text(SCRIPT, encoding="utf-8")
    # Translated copies and our own generated files must not contribute.
    (game / "tl" / "turkish" / "chars.rpy").write_text('define z = Character("Gül")\n', encoding="utf-8")
    (game / "zzz_turkish_language.rpy").write_text('define q = Character("Ghost")\n', encoding="utf-8")

    names = collect_character_display_names(game)
    assert names == {"Rose", "Hope", "Will"}


def test_rpyc_reader_respects_setting():
    from src.core.rpyc_reader import ASTTextExtractor

    for flag, expected in ((False, set()), (True, {"Rose"})):
        config = ConfigManager()
        config.translation_settings.translate_character_names = flag
        extractor = ASTTextExtractor(config)
        extractor._extract_strings_from_code('r = Character("Rose")', 1)
        found = {t.text for t in extractor.extracted}
        assert ({"Rose"} & found) == expected
