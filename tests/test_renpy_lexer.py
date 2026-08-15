import pytest
from src.core.renpy_lexer import RenPyLexer, LexerToken
from src.core.parser import RenPyParser
from src.utils.config import ConfigManager


def test_renpy_lexer_simple_dialogue():
    content = """
label start:
    e "Hello world!"
    m "Welcome back!"
"""
    lexer = RenPyLexer()
    tokens = lexer.tokenize(content, "script.rpy")
    assert len(tokens) == 2
    assert tokens[0].character == "e"
    assert tokens[0].text == "Hello world!"
    assert tokens[0].context_path == ["label:start"]

    assert tokens[1].character == "m"
    assert tokens[1].text == "Welcome back!"


def test_renpy_lexer_string_speakers():
    content = """
label scene1:
    "???" "Who goes there?"
    Student.npc "It's me!"
"""
    lexer = RenPyLexer()
    tokens = lexer.tokenize(content, "script.rpy")
    assert len(tokens) == 2
    assert tokens[0].character == '"??"' or tokens[0].character == '"???"'
    assert tokens[0].text == "Who goes there?"

    assert tokens[1].character == "Student.npc"
    assert tokens[1].text == "It's me!"


def test_renpy_lexer_python_block_skipping():
    content = """
python:
    x = 10
    y = "Internal Python String"

label start:
    e "Actual dialogue"
"""
    lexer = RenPyLexer()
    tokens = lexer.tokenize(content, "script.rpy")
    assert len(tokens) == 1
    assert tokens[0].text == "Actual dialogue"


def test_renpy_lexer_ui_elements():
    content = """
screen my_screen:
    textbutton "Save Game"
    text "Welcome User"
"""
    lexer = RenPyLexer()
    tokens = lexer.tokenize(content, "screen.rpy")
    assert len(tokens) == 2
    assert tokens[0].text == "Save Game"
    assert tokens[0].text_type == "button"
    assert tokens[1].text == "Welcome User"
    assert tokens[1].text_type == "ui"


def test_parser_stateful_lexer_toggle_integration(tmp_path):
    config = ConfigManager()
    config.translation_settings.enable_stateful_lexer = True

    rpy_file = tmp_path / "script.rpy"
    rpy_file.write_text("""
label start:
    e "Hello stateful lexer!"
""", encoding="utf-8")

    parser = RenPyParser(config_manager=config)
    entries = parser.extract_text_entries(rpy_file)
    texts = [entry["text"] for entry in entries]
    assert "Hello stateful lexer!" in texts


def test_renpy_lexer_keyword_and_statement_skipping():
    content = """
define riko = Character("Riko", color="#ffffff")
default quick_save = "Hızlı kaydetme"
play sound "<silence 0.4>"
label "istatistik adını yaz"

label start:
    e "Hello dialogue!"
"""
    lexer = RenPyLexer()
    tokens = lexer.tokenize(content, "script.rpy")
    texts = [t.text for t in tokens]
    characters = [t.character for t in tokens]

    assert "Hello dialogue!" in texts
    assert "Riko" not in texts
    assert "<silence 0.4>" not in texts
    assert "Hızlı kaydetme" not in texts
    assert "define" not in characters
    assert "play" not in characters
    assert "default" not in characters

