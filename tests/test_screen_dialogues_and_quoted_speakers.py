# -*- coding: utf-8 -*-
"""
Tests for:
1. Rejection of screen properties as dialogues in parser.py
2. Filtering Python/Sphinx docstrings in rpyc_reader.py
3. Quoted speaker and single/double quote handling in tl_parser.py
"""

import tempfile
from pathlib import Path

from src.core.parser import RenPyParser
from src.core.rpyc_reader import ASTTextExtractor
from src.core.tl_parser import TLParser


def test_parser_rejects_screen_properties_as_dialogues():
    """Ensure style_prefix, id, variant, text_style etc. are not treated as character dialogues."""
    parser = RenPyParser()
    screen_code = """screen about():
    tag menu
    style_prefix "about"
    id "window"
    text_style "dw5Style"
    variant "small"
    text "About This Game"
    textbutton "Return":
        action Return()
"""
    with tempfile.NamedTemporaryFile("w", suffix=".rpy", delete=False, encoding="utf-8") as tf:
        tf.write(screen_code)
        screen_file = tf.name

    try:
        entries = parser.extract_text_entries(screen_file)
        dialogue_entries = [e for e in entries if (e.get("type") == "dialogue" or e.get("text_type") == "dialogue") and e.get("character")]
        assert len(dialogue_entries) == 0, f"Expected 0 dialogues, got: {dialogue_entries}"
    finally:
        Path(screen_file).unlink(missing_ok=True)

    # Also verify that genuine dialogue is still extracted outside screens
    script_code = """label start:
    style_prefix = True
    e "Hello world!"
    "Narrator line"
"""
    with tempfile.NamedTemporaryFile("w", suffix=".rpy", delete=False, encoding="utf-8") as tf:
        tf.write(script_code)
        script_file = tf.name

    try:
        script_entries = parser.extract_text_entries(script_file)
        dialogue_speakers = [e.get("character") for e in script_entries if e.get("character")]
        assert dialogue_speakers == ["e"]
    finally:
        Path(script_file).unlink(missing_ok=True)


def test_rpyc_reader_filters_docstrings():
    """Ensure ASTTextExtractor does not extract function/module docstrings or Sphinx directives."""
    extractor = ASTTextExtractor()
    code = '''def some_function():
    """This is a docstring that should never be translated."""
    msg = "This is a user message"
    """Another loose docstring: :doc: file_action"""
    return msg
'''
    extractor._extract_from_code_obj(code, "renpy/common/00action_file.rpy", 1)
    texts = [e.text for e in extractor.extracted]
    assert "This is a user message" in texts
    assert "This is a docstring that should never be translated." not in texts
    assert not any(":doc:" in t for t in texts)


def test_tl_parser_quoted_speaker_and_quoting():
    """Ensure TLParser handles quoted speakers and single/double quotes properly."""
    parser = TLParser()
    tl_content = """translate turkish test_label_12345678:
    # "Lan" "Hello world"
    "Lan" ""

    # 'Single Speaker' 'Single quoted text'
    'Single Speaker' ''

    # "Just a narrator"
    ""

translate turkish strings:
    old "Save Game"
    new ""
    old 'Load Game'
    new ''
"""
    with tempfile.NamedTemporaryFile("w", suffix=".rpy", delete=False, encoding="utf-8") as tf:
        tf.write(tl_content)
        tmp_path = tf.name

    try:
        parsed = parser.parse_file(tmp_path)
        assert parsed is not None
        assert len(parsed.entries) == 5

        # Check dialogue 1
        d1 = parsed.entries[0]
        assert d1.entry_type == "dialogue"
        assert d1.character == '"Lan"'
        assert d1.original_text == "Hello world"

        # Check dialogue 2
        d2 = parsed.entries[1]
        assert d2.entry_type == "dialogue"
        assert d2.character == "'Single Speaker'"
        assert d2.original_text == "Single quoted text"

        # Check narrator
        n = parsed.entries[2]
        assert n.entry_type == "narrator"
        assert n.character is None
        assert n.original_text == "Just a narrator"

        # Check strings
        s1 = parsed.entries[3]
        assert s1.entry_type == "string"
        assert s1.original_text == "Save Game"

        s2 = parsed.entries[4]
        assert s2.entry_type == "string"
        assert s2.original_text == "Load Game"

        # Test updating translations
        updated = parser.update_translations(
            parsed,
            {
                "Hello world": "Merhaba dunya",
                "Single quoted text": "Tek tirnakli metin",
                "Just a narrator": "Sadece anlatici",
                "Save Game": "Oyunu Kaydet",
                "Load Game": "Oyunu Yukle",
            },
        )
        assert '"Lan" "Merhaba dunya"' in updated
        assert "'Single Speaker' \"Tek tirnakli metin\"" in updated
        assert '"Sadece anlatici"' in updated
        assert 'new "Oyunu Kaydet"' in updated
        assert 'new "Oyunu Yukle"' in updated

    finally:
        Path(tmp_path).unlink(missing_ok=True)
