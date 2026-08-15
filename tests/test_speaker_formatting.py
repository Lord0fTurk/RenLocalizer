import pytest
from src.core.output_formatter import format_renpy_speaker, RenPyOutputFormatter


def test_format_renpy_speaker_valid_identifiers():
    assert format_renpy_speaker("e") == "e"
    assert format_renpy_speaker("m") == "m"
    assert format_renpy_speaker("charlie") == "charlie"
    assert format_renpy_speaker("Student.npc") == "Student.npc"
    assert format_renpy_speaker("charlie.happy") == "charlie.happy"


def test_format_renpy_speaker_non_identifiers():
    assert format_renpy_speaker("???") == '"???"'
    assert format_renpy_speaker("Old Man") == '"Old Man"'
    assert format_renpy_speaker("123") == '"123"'
    assert format_renpy_speaker("??? ! @#") == '"??? ! @#"'


def test_format_renpy_speaker_already_quoted():
    assert format_renpy_speaker('"???"') == '"???"'
    assert format_renpy_speaker("'Old Man'") == "'Old Man'"
    assert format_renpy_speaker('"e"') == '"e"'


def test_format_renpy_speaker_empty():
    assert format_renpy_speaker("") == ""
    assert format_renpy_speaker(None) == ""
    assert format_renpy_speaker("   ") == ""


def test_generate_character_translation_with_speaker_formatting():
    formatter = RenPyOutputFormatter()
    
    # Non-identifier string speaker
    block_non_id = formatter.generate_character_translation("???", "Welcome back!", "Hoş geldin!", "turkish")
    assert '    # "???" "Welcome back!"\n' in block_non_id
    assert '    "???" "Hoş geldin!"\n' in block_non_id

    # Valid identifier speaker
    block_id = formatter.generate_character_translation("e", "I am home!", "Evdeyim!", "turkish")
    assert '    # e "I am home!"\n' in block_id
    assert '    e "Evdeyim!"\n' in block_id

    # Dotted valid identifier speaker
    block_dotted = formatter.generate_character_translation("Student.npc", "Hello!", "Merhaba!", "turkish")
    assert '    # Student.npc "Hello!"\n' in block_dotted
    assert '    Student.npc "Merhaba!"\n' in block_dotted
