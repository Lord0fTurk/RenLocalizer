import tempfile
from pathlib import Path
import pytest

from src.core.output_formatter import format_renpy_speaker, RenPyOutputFormatter
from src.core.pipeline.extraction import generate_native_tlid_content
from src.core.renpy_lexer import RenPyLexer
from src.core.parser import RenPyParser
from src.utils.config import ConfigManager


def test_v2812_speaker_formatting_rules():
    """Verify speaker formatting rules for identifiers vs string literals."""
    # Valid Ren'Py identifiers / dotted attributes (unquoted)
    assert format_renpy_speaker("e") == "e"
    assert format_renpy_speaker("m") == "m"
    assert format_renpy_speaker("charlie") == "charlie"
    assert format_renpy_speaker("Student.npc") == "Student.npc"
    assert format_renpy_speaker("charlie.happy") == "charlie.happy"

    # Non-identifier string literals (must be quoted)
    assert format_renpy_speaker("???") == '"???"'
    assert format_renpy_speaker("Old Man") == '"Old Man"'
    assert format_renpy_speaker("123") == '"123"'
    assert format_renpy_speaker("Gizemli Adam") == '"Gizemli Adam"'

    # Already quoted strings (preserved as-is)
    assert format_renpy_speaker('"???"') == '"???"'
    assert format_renpy_speaker("'Old Man'") == "'Old Man'"


def test_v2812_pipeline_tl_structure_generation_with_non_identifier_speakers():
    """Test that pipeline generate_native_tlid_content produces syntactically valid Ren'Py output for ???."""
    dialogue_entries = [
        {
            'text': 'Welcome back!',
            'character': '???',
            'file_path': 'game/script.rpy',
            'identifier': 'start_b0d2682f',
            'text_type': 'dialogue'
        },
        {
            'text': 'I am home!',
            'character': 'e',
            'file_path': 'game/script.rpy',
            'identifier': 'start_12345678',
            'text_type': 'dialogue'
        }
    ]

    rpy_output = generate_native_tlid_content(
        entries=dialogue_entries,
        game_dir=Path("/game"),
        target_language="turkish",
        source_language="english",
        engine=None,
        translation_manager=None,
        config=None
    )

    # Must contain valid quoted speaker "???" "" instead of invalid ??? ""
    assert '    # "???" "Welcome back!"' in rpy_output
    assert '    "???" ""' in rpy_output

    # Valid identifier e should stay unquoted e ""
    assert '    # e "I am home!"' in rpy_output
    assert '    e ""' in rpy_output


def test_v2812_lexer_stateful_extraction_accuracy():
    """Verify Stateful Lexer accurately extracts dialogue, UI text, and handles python blocks."""
    content = """
python:
    internal_var = "Should not be extracted as dialogue"

label start:
    "???" "Who goes there?"
    e "It is me!"
    textbutton "Click Me"
"""

    lexer = RenPyLexer()
    tokens = lexer.tokenize(content, "script.rpy")

    texts = [t.text for t in tokens]
    types = [t.text_type for t in tokens]
    chars = [t.character for t in tokens]

    assert "Who goes there?" in texts
    assert "It is me!" in texts
    assert "Click Me" in texts
    assert "Should not be extracted as dialogue" not in texts

    # Check speaker for "???"
    idx_q = texts.index("Who goes there?")
    assert chars[idx_q] == '"??"' or chars[idx_q] == '"???"'


def test_v2812_parser_fallback_on_lexer_error(tmp_path):
    """Verify that if Lexer encounters an unexpected error, parser safely falls back to regex."""
    config = ConfigManager()
    config.translation_settings.enable_stateful_lexer = True

    rpy_file = tmp_path / "script.rpy"
    rpy_file.write_text("""
label start:
    e "Hello fallback test!"
""", encoding="utf-8")

    parser = RenPyParser(config_manager=config)

    # Normal lexer extraction
    entries = parser.extract_text_entries(rpy_file)
    assert any(e["text"] == "Hello fallback test!" for e in entries)
