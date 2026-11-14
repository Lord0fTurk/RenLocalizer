# -*- coding: utf-8 -*-
"""
Tests for _make_source_translatable() pattern improvements (v2.7.4).
Verifies that popup/screen text gets _() wrapping correctly.
"""
import re
import unittest

# ─── text pattern (v2.7.4: inclusive, no following-keyword requirement) ───
TEXT_PATTERN = r"(\btext\s+)(['\"])([^'\"\[\]]+)\2(?=\s|$|:)"
TEXT_REPLACEMENT = r'\1_(\2\3\2)'

# ─── textbutton pattern (v2.7.4: lookahead) ───
TEXTBUTTON_PATTERN = r"(textbutton\s+)(['\"])([^'\"]+)\2(?=\s|$|:)"
TEXTBUTTON_REPLACEMENT = r'\1_(\2\3\2)'

# ─── skip patterns (v2.7.4: format-specific, not blanket brace skip) ───
SKIP_PATTERNS = [
    r'_\s*\(\s*[\'"]',                                      # Already translatable
    r'[\'\"]\s*\+\s*[\'"]',                                  # String concatenation
    r'^\s*#',                                                 # Comment
    r'^\s*$',                                                 # Empty
    r'define\s+',                                             # define
    r'default\s+',                                            # default
    r'=\s*[\'"][^\'"]*[\'"]\s*$',                             # Assignment
    r'[\'"][^\'"]*\[[^\]]+\][^\'"]*[\'"]',                    # Variable: "[player]"
    r'\.format\s*\(',                                         # .format()
    r'[\'"][^\'"]*\{\s*\}[^\'"]*[\'"]',                       # Empty braces: "{}"
    r'[\'"][^\'"]*\{\d+[^}]*\}[^\'"]*[\'"]',                  # Positional: "{0}"
    r'[\'"][^\'"]*\{:[^}]+\}[^\'"]*[\'"]',                    # Format spec: "{:d}"
]


def should_skip(line: str) -> bool:
    """Check if line should be skipped by any skip pattern."""
    for pat in SKIP_PATTERNS:
        if re.search(pat, line):
            return True
    return False


def apply_pattern(line: str, pattern: str, replacement: str) -> str:
    """Apply a replacement pattern to a line (if not skipped)."""
    if should_skip(line):
        return line
    return re.sub(pattern, replacement, line)


class TestTextPatternInclusive(unittest.TestCase):
    """text 'string' pattern should match regardless of following keywords."""

    def test_plain_text_end_of_line(self):
        """text 'Hello' at end of line — CRITICAL FIX (was missed before v2.7.4)."""
        line = '    text "Hello World"'
        result = apply_pattern(line, TEXT_PATTERN, TEXT_REPLACEMENT)
        self.assertIn('_("Hello World")', result)

    def test_text_with_colon(self):
        line = '    text "Quit":'
        result = apply_pattern(line, TEXT_PATTERN, TEXT_REPLACEMENT)
        self.assertIn('_("Quit")', result)

    def test_text_with_size(self):
        line = '    text "LOCKED" size 50'
        result = apply_pattern(line, TEXT_PATTERN, TEXT_REPLACEMENT)
        self.assertIn('_("LOCKED")', result)

    def test_text_with_color(self):
        line = '    text "Error" color "#FF0000"'
        result = apply_pattern(line, TEXT_PATTERN, TEXT_REPLACEMENT)
        self.assertIn('_("Error")', result)

    def test_text_with_multiple_props(self):
        line = '    text "Stats" xalign 0.5 yalign 0.5'
        result = apply_pattern(line, TEXT_PATTERN, TEXT_REPLACEMENT)
        self.assertIn('_("Stats")', result)

    def test_single_word_popup(self):
        """Single word like 'Save' or 'Load' should be matched."""
        for word in ["Save", "Load", "Help", "Options", "Quit"]:
            line = f'    text "{word}"'
            result = apply_pattern(line, TEXT_PATTERN, TEXT_REPLACEMENT)
            self.assertIn(f'_("{word}")', result, f"Failed for: {word}")

    def test_question_text(self):
        line = '    text "Are you sure you want to quit?"'
        result = apply_pattern(line, TEXT_PATTERN, TEXT_REPLACEMENT)
        self.assertIn('_("Are you sure you want to quit?")', result)


class TestTextWithRenpyTags(unittest.TestCase):
    """Text with Ren'Py formatting tags should get _() wrapping (v2.7.4 fix)."""

    def test_bold_tag(self):
        """text '{b}Bold{/b} text' should be wrapped in _()."""
        line = '    text "{b}Bold{/b} text"'
        result = apply_pattern(line, TEXT_PATTERN, TEXT_REPLACEMENT)
        self.assertIn('_("{b}Bold{/b} text")', result)

    def test_color_tag(self):
        line = '    text "{color=#ff0000}Error{/color}: Something went wrong"'
        result = apply_pattern(line, TEXT_PATTERN, TEXT_REPLACEMENT)
        self.assertIn('_("{color=#ff0000}Error{/color}: Something went wrong")', result)

    def test_size_tag(self):
        line = '    text "{size=24}Big Title{/size}"'
        result = apply_pattern(line, TEXT_PATTERN, TEXT_REPLACEMENT)
        self.assertIn('_("{size=24}Big Title{/size}")', result)

    def test_italic_tag(self):
        line = '    text "{i}Italic hint{/i}"'
        result = apply_pattern(line, TEXT_PATTERN, TEXT_REPLACEMENT)
        self.assertIn('_("{i}Italic hint{/i}")', result)

    def test_nested_tags(self):
        line = '    text "{b}{color=#f00}Warning{/color}{/b}: Read carefully!"'
        result = apply_pattern(line, TEXT_PATTERN, TEXT_REPLACEMENT)
        self.assertIn('_(', result)

    def test_alpha_tag(self):
        line = '    text "{alpha=0.5}Ghost text{/alpha}"'
        result = apply_pattern(line, TEXT_PATTERN, TEXT_REPLACEMENT)
        self.assertIn('_(', result)


class TestSkipVariables(unittest.TestCase):
    """Text with [variables] must still be skipped."""

    def test_variable_in_text(self):
        line = '    text "[player_name]"'
        self.assertTrue(should_skip(line))

    def test_variable_mixed(self):
        line = '    text "Hello [name]!"'
        self.assertTrue(should_skip(line))


class TestSkipFormatStrings(unittest.TestCase):
    """Python format strings must be skipped (not confused with Ren'Py tags)."""

    def test_empty_braces(self):
        line = '    text "Score: {}"'
        self.assertTrue(should_skip(line))

    def test_positional(self):
        line = '    text "{0} items"'
        self.assertTrue(should_skip(line))

    def test_format_spec(self):
        line = '    text "{:d} points"'
        self.assertTrue(should_skip(line))

    def test_format_call(self):
        line = '    "text".format(x)'
        self.assertTrue(should_skip(line))

    def test_already_translatable(self):
        line = '    text _("Already wrapped")'
        self.assertTrue(should_skip(line))


class TestRenpyTagsNotSkipped(unittest.TestCase):
    """Ren'Py text tags should NOT trigger skip (v2.7.4 fix)."""

    def test_bold_not_skipped(self):
        line = '    text "{b}Bold{/b}"'
        self.assertFalse(should_skip(line))

    def test_color_not_skipped(self):
        line = '    text "{color=#ff0000}Red{/color}"'
        self.assertFalse(should_skip(line))

    def test_size_not_skipped(self):
        line = '    text "{size=24}Big{/size}"'
        self.assertFalse(should_skip(line))

    def test_italic_not_skipped(self):
        line = '    text "{i}Italic{/i}"'
        self.assertFalse(should_skip(line))

    def test_multi_tag_not_skipped(self):
        line = '    text "{b}{i}Bold Italic{/i}{/b}"'
        self.assertFalse(should_skip(line))


class TestTextbuttonPattern(unittest.TestCase):
    """textbutton pattern tests."""

    def test_textbutton_with_action(self):
        line = '    textbutton "OK" action Return(True)'
        result = apply_pattern(line, TEXTBUTTON_PATTERN, TEXTBUTTON_REPLACEMENT)
        self.assertIn('_("OK")', result)

    def test_textbutton_with_colon(self):
        line = '    textbutton "Start":'
        result = apply_pattern(line, TEXTBUTTON_PATTERN, TEXTBUTTON_REPLACEMENT)
        self.assertIn('_("Start")', result)

    def test_textbutton_end_of_line(self):
        """textbutton at end of line (rare but valid)."""
        line = '    textbutton "Click"'
        result = apply_pattern(line, TEXTBUTTON_PATTERN, TEXTBUTTON_REPLACEMENT)
        self.assertIn('_("Click")', result)


class TestTagStrippedStringsJson(unittest.TestCase):
    """Test tag-stripped entry generation for strings.json."""

    RENPY_TAG_RE = re.compile(
        r'\{/?(?:b|i|u|s|plain|color|font|size|cps|nw|fast|w|p|a|'
        r'outlinecolor|alpha|k|rt|rb|image|space|vspace)(?:=[^}]*)?\}'
    )

    def _strip_tags(self, text: str) -> str:
        return self.RENPY_TAG_RE.sub('', text).strip()

    def test_bold_stripped(self):
        self.assertEqual(self._strip_tags("{b}Hello{/b} World"), "Hello World")

    def test_color_stripped(self):
        self.assertEqual(
            self._strip_tags("{color=#ff0000}Error{/color}: Something broke"),
            "Error: Something broke"
        )

    def test_no_tags_unchanged(self):
        self.assertEqual(self._strip_tags("Hello World"), "Hello World")

    def test_multiple_tags_stripped(self):
        self.assertEqual(
            self._strip_tags("{b}{i}Bold Italic{/i}{/b} text"),
            "Bold Italic text"
        )

    def test_size_tag_stripped(self):
        self.assertEqual(self._strip_tags("{size=24}Title{/size}"), "Title")

    def test_entry_generation(self):
        """Simulate the tag-stripped entry generation logic."""
        mapping = {
            "{b}Hello{/b} World": "{b}Merhaba{/b} Dünya",
            "Plain text": "Düz metin",
            "{color=#f00}Error{/color}": "{color=#f00}Hata{/color}",
        }
        additions = {}
        for orig, trans in mapping.items():
            if not self.RENPY_TAG_RE.search(orig):
                continue
            stripped_orig = self._strip_tags(orig)
            stripped_trans = self._strip_tags(trans)
            if (stripped_orig and stripped_trans
                    and stripped_orig != stripped_trans
                    and len(stripped_orig) >= 2
                    and stripped_orig not in mapping):
                additions[stripped_orig] = stripped_trans

        self.assertIn("Hello World", additions)
        self.assertEqual(additions["Hello World"], "Merhaba Dünya")
        self.assertIn("Error", additions)
        self.assertEqual(additions["Error"], "Hata")
        self.assertNotIn("Plain text", additions)  # No tags → not added


class TestEdgeCases(unittest.TestCase):
    """Edge cases for proper handling."""

    def test_define_skipped(self):
        line = '    define msg = "Hello"'
        self.assertTrue(should_skip(line))

    def test_default_skipped(self):
        line = '    default score = "0"'
        self.assertTrue(should_skip(line))

    def test_assignment_skipped(self):
        line = '    variable = "value"'
        self.assertTrue(should_skip(line))

    def test_comment_skipped(self):
        line = '    # text "This is a comment"'
        self.assertTrue(should_skip(line))

    def test_concat_skipped(self):
        line = '    "hello" + "world"'
        self.assertTrue(should_skip(line))

    def test_text_single_quotes(self):
        """text with single quotes should also work."""
        line = "    text 'Hello World'"
        result = apply_pattern(line, TEXT_PATTERN, TEXT_REPLACEMENT)
        self.assertIn("_('Hello World')", result)

    def test_no_double_wrap(self):
        """Already wrapped text should not be double-wrapped."""
        line = '    text _("Already wrapped")'
        result = apply_pattern(line, TEXT_PATTERN, TEXT_REPLACEMENT)
        self.assertNotIn('_(_("', result)


if __name__ == '__main__':
    unittest.main()
