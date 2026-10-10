# -*- coding: utf-8 -*-
"""Strings marked with _(), __(), ___() or _p() are translated like Ren'Py does.

Ren'Py's own collector (renpy/translation/scanstrings.py) takes every literal
passed to these functions, with no heuristics. RenLocalizer's code/identifier
filters dropped many of them ("SWING", "Age: 42", chapter cards); measured on
MILF Obsession 0.5.0 with Ren'Py --count: game strings missing 57 -> 10 (the
10 are symbols, a date format and the game id, left out on purpose).
"""
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.marked_strings import reformat_p, scan_source, worth_translating
from src.core.parser import RenPyParser
from src.utils.config import ConfigManager

SOURCE = '''
define e = Character(_("Eileen"))
define config.name = _("My_Game")
define gui.about = _p("""
    These two lines will be combined
    to form a long line.

    This line will be separate.
    """)

screen phone():
    text _("Age: 42") size 25 color "#ffffff"
    textbutton _("SWING") action Jump("swing_label")
    textbutton _("<") action FilePagePrevious()
    text FileTime(slot, format=_("{#file_time}%A, %B %d %Y, %H:%M"), empty=_("empty slot"))
    # textbutton _("Commented out")

label start:
    call splash_message(_("Chapter 5")) from _call_splash_message_1
    $ renpy.notify(__("You found a key"))
    $ mood = _("great" " and calm")
    $ value = some_func_("not marked")
'''


def _texts(source=SOURCE):
    return [t for t, _, _ in scan_source(source)]


def test_scan_matches_renpy_functions_and_literals():
    texts = _texts()
    assert "SWING" in texts and "Age: 42" in texts and "Chapter 5" in texts
    assert "You found a key" in texts            # __()
    assert "great and calm" in texts             # adjacent literals are joined
    assert "Commented out" not in texts          # comments are not code
    assert "not marked" not in texts             # some_func_( is not _(


def test_p_is_reformatted_like_renpy():
    assert "These two lines will be combined to form a long line.\n\nThis line will be separate." in _texts()
    assert reformat_p("\n  a\n  b{p}\n  c\n") == "a b{p}c"


def test_character_names_are_reported():
    names = {t for t, _, is_name in scan_source(SOURCE) if is_name}
    assert names == {"Eileen"}


@pytest.mark.parametrize("text,expected", [
    ("SWING", True),
    ("Age: 42", True),
    ("{#auto_page}A", True),
    ("<", False),
    ("▸", False),
    ("- $300", False),
    ("{#file_time}%A, %B %d %Y, %H:%M", False),
    ("My_Game", False),
    ("images/bg.png", False),
    ("https://example.com", False),
])
def test_worth_translating(text, expected):
    assert worth_translating(text) is expected


@pytest.fixture
def parsed(tmp_path):
    path = tmp_path / "game" / "s.rpy"
    path.parent.mkdir()
    path.write_text(SOURCE, encoding="utf-8")
    return {e["text"]: e for e in RenPyParser(ConfigManager()).extract_text_entries(str(path))}


def test_parser_adds_and_marks_what_the_heuristics_dropped(parsed):
    for text in ("SWING", "Age: 42", "Chapter 5", "empty slot"):
        assert parsed[text]["marked"] is True
    for text in ("<", "{#file_time}%A, %B %d %Y, %H:%M", "My_Game", "Commented out"):
        assert text not in parsed or not parsed[text].get("marked")


def test_character_names_follow_the_setting(tmp_path):
    path = tmp_path / "game" / "c.rpy"
    path.parent.mkdir()
    path.write_text('define e = Character(_("Eileen"))\n', encoding="utf-8")
    cfg = ConfigManager()
    cfg.translation_settings.translate_character_names = False
    texts = {e["text"] for e in RenPyParser(cfg).extract_text_entries(str(path)) if e.get("marked")}
    assert "Eileen" not in texts
    cfg.translation_settings.translate_character_names = True
    texts = {e["text"] for e in RenPyParser(cfg).extract_text_entries(str(path)) if e.get("marked")}
    assert "Eileen" in texts


def test_marked_strings_reach_the_native_strings_block(tmp_path, parsed):
    from src.core.pipeline.extraction import generate_native_tlid_content

    entries = [dict(e, file_path=str(tmp_path / "game" / "s.rpy")) for e in parsed.values()]
    content = generate_native_tlid_content(entries, str(tmp_path / "game"), target_language="turkish")
    assert 'old "SWING"' in content and 'old "Age: 42"' in content


def test_rpyc_expressions_are_scanned():
    from src.core.rpyc_reader import ASTTextExtractor, FakePyExpr

    extractor = ASTTextExtractor()
    extractor.current_file = "game/screens.rpyc"
    extractor.extracted = []
    nodes = [{"positional": [FakePyExpr('_("KISS")', "screens.rpy", 12)]}, FakePyExpr('_("<")', "screens.rpy", 13)]
    extractor._merge_marked_strings(nodes)
    assert [(t.text, t.marked, t.line_number) for t in extractor.extracted] == [("KISS", True, 12)]

    extractor.current_file = "renpy/common/_developer/inspector.rpyc"
    extractor.extracted = []
    extractor._merge_marked_strings(nodes)
    assert extractor.extracted == []


def test_translation_step_does_not_drop_marked_strings(tmp_path):
    from src.core.pipeline import TranslationPipeline
    from src.core.tl_parser import TranslationEntry
    from src.core.translators.base import TranslationEngine
    from src.core.translators.manager import TranslationManager
    from src.utils.config import TranslationSettings

    game = tmp_path / "game"
    game.mkdir()
    (game / "s.rpy").write_text('screen x():\n    textbutton _("KISS") action NullAction()\n', encoding="utf-8")
    cfg = MagicMock(spec=ConfigManager)
    ts = TranslationSettings()
    ts.use_global_cache = False
    cfg.translation_settings = ts
    cfg.data_dir = str(tmp_path)
    cfg.glossary = {}
    cfg.get_log_text.side_effect = lambda key, *a, **k: f"[{key}]"
    mgr = TranslationManager(config_manager=cfg)
    pipeline = TranslationPipeline(config=cfg, translation_manager=mgr)
    pipeline.project_path = str(tmp_path)
    pipeline.target_language = "turkish"
    pipeline.source_language = "en"
    pipeline.engine = TranslationEngine.GOOGLE

    with patch.object(mgr, "translate_batch", new_callable=AsyncMock) as batch:
        batch.return_value = []
        pipeline._translate_entries([TranslationEntry("KISS", "", "s.rpy", 2, "string", translation_id="k")])
    assert pipeline._sent_for_translation == 1


def test_a_dialogue_line_does_not_cover_the_same_marked_ui_string(tmp_path):
    from src.core.pipeline.extraction import generate_native_tlid_content

    path = tmp_path / "game" / "d.rpy"
    path.parent.mkdir()
    # The parser keeps the dialogue line but its filters drop the bare screen
    # text; the button still needs its own "translate strings" entry.
    path.write_text('label start:\n    e "SLOWLY"\nscreen q():\n    add Text(_("SLOWLY"))\n', encoding="utf-8")
    entries = RenPyParser(ConfigManager()).extract_text_entries(str(path))
    for e in entries:
        e.setdefault("file_path", str(path))
    content = generate_native_tlid_content(entries, str(tmp_path / "game"), target_language="turkish")
    assert 'old "SLOWLY"' in content
    assert re.search(r'^translate turkish start_\w+:', content, re.M)


def test_marker_call_with_space_is_found():
    assert [t for t, _, _ in scan_source('$ x = _ ("Spaced call")')] == ["Spaced call"]
