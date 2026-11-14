"""
Tests for text_type filtering — verifies that user filter settings
(translate_dialogue, translate_ui, translate_menu, etc.) are properly applied
across ALL extraction paths: regex, lexer, pyparsing, and RPYC reader.

Bug context: v2.7.3 user report — "selected dialogues only but entire game translated"
Root cause: pyparsing path and RPYC reader bypassed _should_translate_text().
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.parser import RenPyParser


def _make_config(
    translate_dialogue=True,
    translate_menu=True,
    translate_ui=True,
    translate_config_strings=True,
    translate_gui_strings=True,
    translate_define_strings=True,
    translate_buttons=True,
    translate_renpy_functions=True,
    translate_style_strings=True,
):
    """Create a mock config with the given translation filter settings."""
    cfg = MagicMock()
    ts = MagicMock()
    ts.translate_dialogue = translate_dialogue
    ts.translate_menu = translate_menu
    ts.translate_ui = translate_ui
    ts.translate_config_strings = translate_config_strings
    ts.translate_gui_strings = translate_gui_strings
    ts.translate_define_strings = translate_define_strings
    ts.translate_buttons = translate_buttons
    ts.translate_renpy_functions = translate_renpy_functions
    ts.translate_style_strings = translate_style_strings
    ts.translate_alt_text = translate_ui
    ts.translate_input_text = translate_ui
    ts.translate_notifications = translate_dialogue
    ts.translate_confirmations = translate_dialogue
    ts.translate_character_names = translate_dialogue
    ts.enable_deep_extraction = True
    ts.deep_extraction_bare_defines = False
    cfg.translation_settings = ts
    cfg.min_confidence = 0.0
    cfg.never_translate_rules = {}
    cfg.get_log_text = MagicMock(return_value="")
    cfg.get_ui_text = MagicMock(return_value="")
    return cfg


class TestShouldTranslateText(unittest.TestCase):
    """Direct tests for _should_translate_text method."""

    def test_dialogue_filtered_when_disabled(self):
        cfg = _make_config(translate_dialogue=False)
        parser = RenPyParser(cfg)
        self.assertFalse(parser._should_translate_text("Hello, how are you?", "dialogue"))

    def test_dialogue_allowed_when_enabled(self):
        cfg = _make_config(translate_dialogue=True)
        parser = RenPyParser(cfg)
        self.assertTrue(parser._should_translate_text("Hello, how are you?", "dialogue"))

    def test_menu_filtered_when_disabled(self):
        cfg = _make_config(translate_menu=False)
        parser = RenPyParser(cfg)
        self.assertFalse(parser._should_translate_text("Go to the store", "menu"))

    def test_ui_filtered_when_disabled(self):
        cfg = _make_config(translate_ui=False)
        parser = RenPyParser(cfg)
        self.assertFalse(parser._should_translate_text("Save Game", "ui"))

    def test_config_filtered_when_disabled(self):
        cfg = _make_config(translate_config_strings=False)
        parser = RenPyParser(cfg)
        self.assertFalse(parser._should_translate_text("Window Title", "config"))

    def test_nvl_dialogue_filtered_when_dialogue_disabled(self):
        cfg = _make_config(translate_dialogue=False)
        parser = RenPyParser(cfg)
        self.assertFalse(parser._should_translate_text("This is NVL text.", "nvl_dialogue"))

    def test_screen_text_filtered_when_ui_disabled(self):
        cfg = _make_config(translate_ui=False)
        parser = RenPyParser(cfg)
        self.assertFalse(parser._should_translate_text("Click here", "screen_text"))

    def test_string_filtered_when_config_disabled(self):
        cfg = _make_config(translate_config_strings=False)
        parser = RenPyParser(cfg)
        self.assertFalse(parser._should_translate_text("Some data value", "string"))

    def test_extend_filtered_when_dialogue_disabled(self):
        cfg = _make_config(translate_dialogue=False)
        parser = RenPyParser(cfg)
        self.assertFalse(parser._should_translate_text("...continued text", "extend"))

    def test_markup_only_visible_text_is_structurally_preserved(self):
        cfg = _make_config(translate_dialogue=True)
        parser = RenPyParser(cfg)
        text = "{color=#5175ea}*giggle*{/w}"
        self.assertEqual(parser._normalize_inline_text_candidate(text), "*giggle*")
        self.assertTrue(parser.is_meaningful_text(text))
        self.assertTrue(parser._should_translate_text(text, "dialogue"))

    def test_screen_tagged_text_is_extracted_end_to_end(self):
        cfg = _make_config(
            translate_dialogue=False,
            translate_menu=False,
            translate_ui=True,
            translate_buttons=True,
        )
        parser = RenPyParser(cfg)
        content = '''\
screen tease_screen():
    text "{color=#5175ea}*giggle*{/w}"
    textbutton "{color=#5175ea}*giggle*{/w}" action Return()
'''
        with tempfile.NamedTemporaryFile(mode='w', suffix='.rpy', delete=False, encoding='utf-8') as f:
            f.write(content)
            fname = f.name

        try:
            entries = parser.extract_text_entries(Path(fname))
            texts = [e['text'] for e in entries]
            self.assertTrue(any('{color=#5175ea}*giggle*{/w}' in t for t in texts), texts)
            for entry in entries:
                if '*giggle*' in entry.get('text', ''):
                    self.assertGreaterEqual(entry.get('confidence', 0.0), 0.50)
                    break
            else:
                self.fail(f"Tagged UI text not extracted. Got: {texts}")
        finally:
            os.unlink(fname)


class TestDialogueOnlyFiltering(unittest.TestCase):
    """End-to-end test: 'dialogue only' — everything else should be filtered."""

    def setUp(self):
        self.cfg = _make_config(
            translate_dialogue=True,
            translate_menu=False,
            translate_ui=False,
            translate_config_strings=False,
            translate_gui_strings=False,
            translate_define_strings=False,
            translate_buttons=False,
            translate_renpy_functions=False,
            translate_style_strings=False,
        )
        self.parser = RenPyParser(self.cfg)

    def test_dialogue_only_extracts_dialogue(self):
        """Mixed content file: only dialogue should be extracted."""
        content = '''\
label start:
    "This is narrator dialogue."
    e "This is character dialogue."

screen settings_screen():
    text "Settings Title"
    textbutton "Save":
        action Return()

menu:
    "What do you want to do?"
    "Go to park":
        pass
    "Stay home":
        pass
'''
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.rpy', delete=False, encoding='utf-8'
        ) as f:
            f.write(content)
            fname = f.name

        try:
            entries = self.parser.extract_text_entries(Path(fname))
            texts = [e['text'] for e in entries]
            [e.get('text_type', '') for e in entries]

            # Dialogue should be present
            self.assertTrue(
                any('narrator dialogue' in t for t in texts),
                f"Narrator dialogue should be extracted. Got: {texts}"
            )
            self.assertTrue(
                any('character dialogue' in t for t in texts),
                f"Character dialogue should be extracted. Got: {texts}"
            )

            # UI and menu should be filtered out
            for t in texts:
                self.assertNotIn('Settings Title', t,
                                 "UI text should be filtered when translate_ui=False")
                self.assertNotIn('Save', t,
                                 "Button text should be filtered when translate_buttons=False")

            # Menu choices should be filtered out
            for t in texts:
                self.assertNotIn('Go to park', t,
                                 "Menu choice should be filtered when translate_menu=False")
                self.assertNotIn('Stay home', t,
                                 "Menu choice should be filtered when translate_menu=False")
        finally:
            os.unlink(fname)

    def test_record_entry_filters_ui_text(self):
        """_record_entry should return None for UI text when translate_ui=False."""
        result = self.parser._record_entry(
            text="Save Game",
            line_number=10,
            context_line='text "Save Game"',
            text_type='ui',
            context_path=['screen:preferences'],
            character='',
            file_path='test.rpy',
        )
        self.assertIsNone(result, "_record_entry should filter UI text when translate_ui=False")

    def test_record_entry_allows_dialogue(self):
        """_record_entry should allow dialogue when translate_dialogue=True."""
        result = self.parser._record_entry(
            text="Hello, world!",
            line_number=5,
            context_line='e "Hello, world!"',
            text_type='dialogue',
            context_path=['label:start'],
            character='e',
            file_path='test.rpy',
        )
        self.assertIsNotNone(result, "_record_entry should allow dialogue text")
        self.assertIn('confidence', result)
        self.assertGreaterEqual(result['confidence'], 0.84)


class TestRecordEntryTypeDetermination(unittest.TestCase):
    """Test that _record_entry correctly determines text_type when not provided."""

    def setUp(self):
        self.cfg = _make_config(
            translate_dialogue=True,
            translate_menu=False,
            translate_ui=False,
        )
        self.parser = RenPyParser(self.cfg)

    def test_screen_context_resolves_to_ui(self):
        """Text in screen context should be classified as 'ui' and filtered."""
        result = self.parser._record_entry(
            text="Click me",
            line_number=10,
            context_line='textbutton "Click me"',
            text_type='',  # Empty — should be resolved by determine_text_type
            context_path=['screen:my_screen'],
            character='',
            file_path='test.rpy',
        )
        self.assertIsNone(result, "Screen context text should be classified as UI and filtered")

    def test_menu_context_resolves_to_menu(self):
        """Text in menu context should be classified as 'menu' and filtered."""
        result = self.parser._record_entry(
            text="Go shopping",
            line_number=15,
            context_line='"Go shopping"',
            text_type='',
            context_path=['menu:'],
            character='',
            file_path='test.rpy',
        )
        self.assertIsNone(result, "Menu context text should be classified as menu and filtered")


if __name__ == '__main__':
    unittest.main()
