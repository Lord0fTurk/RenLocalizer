# -*- coding: utf-8 -*-
"""
Comprehensive Test Suite for Ren'Py Stateful Lexer Engine & Parsing Extensions.
================================================================================

Tests edge cases, keyword filtering, multiline triple-quotes, ATL statements,
screen language elements, dotted/quoted speakers, and TLID sanitization.
"""

import pytest
from pathlib import Path

from src.core.renpy_lexer import RenPyLexer, LexerToken
from src.core.parser import RenPyParser
from src.utils.config import ConfigManager
from src.core.output_formatter import format_renpy_speaker
from src.core.pipeline.extraction import generate_native_tlid_content


def test_lexer_speaker_variations():
    content = """
label start:
    e "Standard identifier speaker"
    m.say "Dotted attribute speaker"
    "???" "Quoted non-identifier speaker"
    'Old Man' "Single quoted speaker"
"""
    lexer = RenPyLexer()
    tokens = lexer.tokenize(content, "test.rpy")
    assert len(tokens) == 4

    assert tokens[0].character == "e"
    assert tokens[0].text == "Standard identifier speaker"

    assert tokens[1].character == "m.say"
    assert tokens[1].text == "Dotted attribute speaker"

    assert tokens[2].character == '"???"'
    assert tokens[2].text == "Quoted non-identifier speaker"

    assert tokens[3].character == "'Old Man'"
    assert tokens[3].text == "Single quoted speaker"


def test_lexer_renpy_statement_and_keyword_skipping():
    content = """
define riko = Character("Riko", color="#ffffff")
default quick_save = "Hızlı kaydetme"
play music "audio/bgm.ogg"
play sound "<silence 0.4>"
stop music fadeout 1.0
scene bg room with dissolve
show eileen happy at center
hide eileen
window show
pause 1.0
label "istatistik adını yaz"

label actual_gameplay:
    e "This is real dialogue!"
"""
    lexer = RenPyLexer()
    tokens = lexer.tokenize(content, "statements.rpy")
    texts = [t.text for t in tokens]
    characters = [t.character for t in tokens]

    assert "This is real dialogue!" in texts
    assert len(tokens) == 1

    # Ensure none of the statements leaked as dialogue
    assert "Riko" not in texts
    assert "Hızlı kaydetme" not in texts
    assert "audio/bgm.ogg" not in texts
    assert "<silence 0.4>" not in texts
    assert "bg room with dissolve" not in texts

    assert "define" not in characters
    assert "play" not in characters
    assert "default" not in characters
    assert "show" not in characters
    assert "scene" not in characters


def test_lexer_multiline_triple_quotes():
    content = '''
label multiline_test:
    e """This is a multiline dialogue.
It spans across multiple lines.
Everything inside should be captured as a single token."""

    m \'\'\'Another multiline dialogue
with single triple quotes.\'\'\'
'''
    lexer = RenPyLexer()
    tokens = lexer.tokenize(content, "multiline.rpy")
    assert len(tokens) == 2

    assert tokens[0].character == "e"
    assert "spans across multiple lines" in tokens[0].text
    assert tokens[0].context_path == ["label:multiline_test"]

    assert tokens[1].character == "m"
    assert "single triple quotes" in tokens[1].text


def test_lexer_python_block_and_single_line_skipping():
    content = """
$ player_name = "John Doe"
$ renpy.pause(0.5)

python:
    def internal_helper():
        secret_var = "Should not be extracted"
        return secret_var

init python:
    ui_theme = "Dark"

label start:
    e "Valid dialogue string"
"""
    lexer = RenPyLexer()
    tokens = lexer.tokenize(content, "python_script.rpy")
    assert len(tokens) == 1
    assert tokens[0].text == "Valid dialogue string"


def test_lexer_screen_language_and_ui_keywords():
    content = """
screen test_ui:
    textbutton "Confirm Save" action Return()
    text "Current Status"
    tooltip "Hover information"
    label "UI Section Title"

    hbox:
        textbutton "Cancel" action Hide()
"""
    lexer = RenPyLexer()
    tokens = lexer.tokenize(content, "screen.rpy")
    texts = [t.text for t in tokens]
    types = [t.text_type for t in tokens]

    assert "Confirm Save" in texts
    assert "Current Status" in texts
    assert "Hover information" in texts
    assert "Cancel" in texts

    assert "button" in types
    assert "ui" in types


def test_format_renpy_speaker_safety():
    # Identifiers (single and dotted) remain unquoted
    assert format_renpy_speaker("e") == "e"
    assert format_renpy_speaker("Student.npc") == "Student.npc"

    # Already quoted strings remain as-is
    assert format_renpy_speaker('"???"') == '"???"'
    assert format_renpy_speaker("'Old Man'") == "'Old Man'"

    # Non-identifiers get quoted
    assert format_renpy_speaker("???") == '"???"'
    assert format_renpy_speaker("Old Man") == '"Old Man"'
    assert format_renpy_speaker("123") == '"123"'

    # Reserved Ren'Py keywords get quoted if used as speaker names
    assert format_renpy_speaker("define") == '"define"'
    assert format_renpy_speaker("play") == '"play"'
    assert format_renpy_speaker("default") == '"default"'
    assert format_renpy_speaker("show") == '"show"'


def test_generate_tl_structure_tlid_sanitization(tmp_path):
    game_dir = tmp_path / "game"
    game_dir.mkdir()

    entries = [
        {
            "text": "Hello world!",
            "character": "h.who",
            "file_path": str(game_dir / "screens.rpy"),
            "text_type": "dialogue",
            "context": "label:h.who",
            "context_path": ["label:h.who"],
        },
        {
            "text": "Special character define statement",
            "character": "define",
            "file_path": str(game_dir / "defines.rpy"),
            "text_type": "dialogue",
            "context": "label:start",
        }
    ]

    class MockFormatter:
        def _should_skip_translation(self, text):
            return False

    rpy_output = generate_native_tlid_content(
        entries=entries,
        target_language="turkish",
        game_dir=str(game_dir),
    )

    # Ensure no dotted TLIDs exist in translate turkish lines
    assert "translate turkish h.who" not in rpy_output
    assert "translate turkish h_who" in rpy_output

    # Ensure 'define' as character was moved to string entries or quoted safely
    assert "define \"Special character define statement\"" not in rpy_output


def test_parser_stateful_lexer_full_pipeline_pass(tmp_path):
    config = ConfigManager()
    config.translation_settings.enable_stateful_lexer = True
    # Isolate the lexer pass: deep extraction (bare define/default strings) is
    # enabled by default on fresh installs and would otherwise add
    # `default quick_save = "Hızlı kaydetme"` to the output, making this test
    # depend on the machine's saved config.json.
    config.translation_settings.enable_deep_extraction = False
    config.translation_settings.enable_deep_scan = False

    rpy = tmp_path / "complex_script.rpy"
    rpy.write_text("""
define riko = Character("Riko")
default quick_save = "Hızlı kaydetme"
play sound "<silence 0.4>"

label h.who_scene:
    h.who "Welcome to our family game!"
    "???" "Who is speaking?"
""", encoding="utf-8")

    parser = RenPyParser(config_manager=config)
    entries = parser.extract_text_entries(rpy)
    extracted_texts = [e["text"] for e in entries]

    assert "Welcome to our family game!" in extracted_texts
    assert "Who is speaking?" in extracted_texts

    assert "Riko" not in extracted_texts
    assert "<silence 0.4>" not in extracted_texts
    assert "Hızlı kaydetme" not in extracted_texts
