"""
Tests for v2.7.3 false-positive filtering in RenPyOutputFormatter._should_skip_translation().

Covers:
  - Python condition strings ('var' in obj.attr)
  - Code logic with dotted access (not GAME.x.isDone(...))
  - Broader code detection (multiple dotted refs + comparison/boolean)
  - Short ALL_CAPS game terms (NOT, STR, INT, CON, DEX)
  - Format string templates ("...".format(...))
  - Single-quoted identifier + code operators
  - Existing filters still work (snake_case, SCREAMING_SNAKE, etc.)
  - Legitimate text is NOT over-filtered
"""

import pytest
from src.core.output_formatter import RenPyOutputFormatter


@pytest.fixture
def fmt():
    return RenPyOutputFormatter()


# ==================================================================
# 1. PYTHON CONDITION STRINGS
# ==================================================================
class TestPythonConditionStrings:
    """Strings like: 'var_name' in obj.attr — game logic conditions."""

    @pytest.mark.parametrize("text", [
        "'likes_toy_talk' in moira.done",
        "'bj_talk' in moira.done",
        "'exemption_talk' in moira.done",
        "'QID_ELF_INTRO' in GAME.mc.done",
        "'key_1' in inventory.items",
        '"my_flag" in player.flags',
        "'scene_visited' not in game.progress",
    ])
    def test_python_conditions_skipped(self, fmt, text):
        assert fmt._should_skip_translation(text) is True, f"Should skip: {text}"

    @pytest.mark.parametrize("text", [
        "She has 'beautiful' eyes in the morning light.",
        "'Hello' she said in a quiet voice.",
        "Put the 'key' in the lock.",
    ])
    def test_natural_text_with_quotes_not_skipped(self, fmt, text):
        assert fmt._should_skip_translation(text) is False, f"Should NOT skip: {text}"


# ==================================================================
# 2. CODE LOGIC WITH DOTTED ACCESS
# ==================================================================
class TestCodeLogicDottedAccess:
    """Strings like: not GAME.x.isDone('QID_...'), khelara not in GAME.crew"""

    @pytest.mark.parametrize("text", [
        "khelara not in GAME.crew",
        "not GAME.questSys.isDone('QID_ELF_INTRO')",
        "item not in player.inventory",
        "enemy in GAME.activeFoes",
    ])
    def test_code_logic_skipped(self, fmt, text):
        assert fmt._should_skip_translation(text) is True, f"Should skip: {text}"

    @pytest.mark.parametrize("text", [
        # Natural language with 'in' — MUST NOT be skipped
        "Getting in Shape",
        "Fitting in Place",
        "Moving in Together",
    ])
    def test_natural_language_with_in_not_skipped(self, fmt, text):
        assert fmt._should_skip_translation(text) is False, f"Should NOT skip: {text}"


# ==================================================================
# 3. BROADER CODE DETECTION (multiple dotted refs + operators)
# ==================================================================
class TestBroaderCodeDetection:
    """Strings with >=2 dotted refs and comparison/boolean operators."""

    @pytest.mark.parametrize("text", [
        "GAME.hour < 18 and GAME.questSys.isDone('QID_MORNING')",
        "player.health > 0 and enemy.health > 0",
        "tris.attr['SLU'] >= 3 or GAME.mc.hasPerk('sneak')",
        "GAME.day > 5 and not GAME.flags.intro_done",
    ])
    def test_broad_code_skipped(self, fmt, text):
        assert fmt._should_skip_translation(text) is True, f"Should skip: {text}"

    @pytest.mark.parametrize("text", [
        "John and Mary walked to the park.",
        "She said it was not going to happen.",
        "The sky is not blue or green today.",
    ])
    def test_natural_text_with_booleans_not_skipped(self, fmt, text):
        assert fmt._should_skip_translation(text) is False, f"Should NOT skip: {text}"


# ==================================================================
# 4. SHORT ALL_CAPS GAME TERMS
# ==================================================================
class TestShortAllCapsGameTerms:
    """2-6 letter ALL_CAPS strings: game stats, skill IDs, etc."""

    @pytest.mark.parametrize("text", [
        "NOT", "REP", "INT", "CON", "STR", "DEX", "TEC",
        "ACTMC", "HP", "MP", "ATK", "DEF", "AGI", "LUK",
        "DMG", "XP", "AP", "SP",
    ])
    def test_short_allcaps_skipped(self, fmt, text):
        assert fmt._should_skip_translation(text) is True, f"Should skip: {text}"

    @pytest.mark.parametrize("text", [
        # Whitelist: common translatable ALL_CAPS words
        "OK", "NO", "ON", "UP", "GO", "OR", "IF", "BY", "IN", "IS", "DO",
    ])
    def test_whitelisted_allcaps_not_skipped(self, fmt, text):
        assert fmt._should_skip_translation(text) is False, f"Should NOT skip: {text}"

    @pytest.mark.parametrize("text", [
        # Longer ALL_CAPS should not be caught by SHORT pattern (>6 chars)
        # but may be caught by SCREAMING_SNAKE if they have underscores
        "ABCDEFG",  # 7 chars — not caught by SHORT_ALL_CAPS (max 6)
    ])
    def test_7plus_allcaps_not_caught_by_short(self, fmt, text):
        # This specific 7-char string with no underscores is NOT caught by
        # SHORT_ALL_CAPS_RE or SCREAMING_SNAKE_RE
        result = fmt._should_skip_translation(text)
        # It may or may not be skipped by other rules; just verify SHORT rule doesn't catch it
        import re
        assert not fmt._SHORT_ALL_CAPS_RE.match(text)


# ==================================================================
# 5. FORMAT STRING TEMPLATES
# ==================================================================
class TestFormatStringTemplates:
    """Strings containing "...".format(...) patterns."""

    @pytest.mark.parametrize("text", [
        '"Track: {} | Dist: {}".format(race.ground, race.laps)',
        '"Hello, {}!".format(actor.name)',
        '"{} scored {} points".format(player.name, score)',
    ])
    def test_format_templates_skipped(self, fmt, text):
        assert fmt._should_skip_translation(text) is True, f"Should skip: {text}"


# ==================================================================
# 6. SINGLE-QUOTED IDENTIFIER + CODE OPERATORS
# ==================================================================
class TestSingleQuotedIdentifierCode:
    """Strings starting with 'identifier' followed by code operators."""

    @pytest.mark.parametrize("text", [
        "'my_flag' in some_dict",
        "'quest_done' not in progress",
        "'hp' == max_hp",
    ])
    def test_single_quoted_code_skipped(self, fmt, text):
        assert fmt._should_skip_translation(text) is True, f"Should skip: {text}"


# ==================================================================
# 7. EXISTING FILTERS STILL WORK
# ==================================================================
class TestExistingFiltersStillWork:
    """Regression: existing skip rules should still be in effect."""

    @pytest.mark.parametrize("text", [
        # snake_case identifiers
        "my_variable_name",
        "save_slot_data",
        # SCREAMING_SNAKE_CASE constants
        "MAX_HEALTH_POINTS",
        "GAME_VERSION_STR",
        # Module attribute access
        "config.version",
        # URL
        "https://example.com",
        # Hex color
        "#FF00AA",
        # Number
        "42.5",
        # Function call
        "renpy.show_screen('debug')",
        # File path with extension
        "images/bg/forest.png",
        # Version string
        "v2.7.3",
        "1.0.0",
        # Ren'Py technical terms
        "dissolve",
        "moveinright",
        "xalign",
        # Ren'Py statement keywords (crash-causing)
        "return",
        "screen",
        "label",
        "menu",
        "init",
        "call",
        "jump",
        "python",
        "define",
        "image",
        "scene",
        "with",
        "at",
        "behind",
        # Newline-prefixed keywords
        "\nreturn",
        "\n  screen",
    ])
    def test_existing_skips(self, fmt, text):
        assert fmt._should_skip_translation(text) is True, f"Should skip: {text}"


# ==================================================================
# 8. LEGITIMATE TEXT NOT OVER-FILTERED
# ==================================================================
class TestLegitimateTextNotOverFiltered:
    """Critical: normal dialogue and UI text MUST NOT be skipped."""

    @pytest.mark.parametrize("text", [
        # Plain dialogue
        "Hello, how are you?",
        "I can't believe it!",
        "Welcome to the adventure.",
        # UI labels
        "Save",
        "Load",
        "Start",
        "Continue",
        "Preferences",
        "History",
        "Help",
        "About",
        "Return",       # Title Case UI label — NOT a keyword
        "Quit",
        "Yes",
        "No",   # In whitelist
        "OK",   # In whitelist
        # Title Case Ren'Py keywords used as UI labels
        "Screen",       # UI label, not keyword
        "Label",
        "Menu",
        # Dialogue with Ren'Py variables
        "Hello, [player_name]!",
        "{b}Important{/b} news for you.",
        "You have {color=#ff0000}[health]{/color} HP remaining.",
        # Natural text that contains words like 'in', 'not', 'and'
        "She is not interested in the game.",
        "He and his friends went to the park.",
        "This is a beautiful morning.",
        # Docstrings with keyword-like words
        "Returns the name of the newest slot.",
        "Simulate return",
        "Shows an nvl-mode screen.",
        # Longer all-caps that are real words (>6 chars or with spaces)
        "GAME OVER",
        "NEW GAME",
        # Mixed case
        "The Dark Forest",
        "A New Beginning",
        # Turkish text
        "Merhaba, nasılsın?",
        "Bu oyun çok güzel.",
        "Kaydet",
        "Yükle",
    ])
    def test_legitimate_text_not_skipped(self, fmt, text):
        assert fmt._should_skip_translation(text) is False, f"Should NOT skip: {text}"


# ==================================================================
# 9. EDGE CASES
# ==================================================================
class TestEdgeCases:
    """Edge cases that need careful handling."""

    @pytest.mark.parametrize("text,expected", [
        # Empty / whitespace
        ("", True),      # Empty strings should be skipped
        ("   ", True),   # Whitespace-only should be skipped
        # Single character
        ("A", True),     # Single char likely not translatable text
        # Ren'Py tags only
        ("{b}{/b}", True),
        ("{color=#fff}{/color}", True),
        # Variables only
        ("[player]", True),
        # Text with only tags and variables
        ("{b}[name]{/b}", True),
        # Actual text with tags
        ("{b}Hello{/b}", False),
        # 'scene' as bare technical term
        ("scene", True),
        ("with", True),
        # But 'Scene' or 'With' as UI label
        ("Scene Selection", False),
        ("With Friends", False),
    ])
    def test_edge_cases(self, fmt, text, expected):
        result = fmt._should_skip_translation(text)
        action = "skip" if expected else "NOT skip"
        assert result is expected, f"Expected to {action}: '{text}', got {result}"


# ==================================================================
# 10. REN'PY CLOSING TAG + ASTERISK GLOB FALSE POSITIVE (v2.8.6)
# ==================================================================
class TestRenpyClosingTagGlobFalsePositive:
    """
    Regression tests for the bug where Ren'Py closing tags like {/w}, {/b},
    {/color} combined with asterisks (*) caused dialogue to be falsely skipped
    as a glob file-system pattern.

    Example: 'Oh, Are you looking for something again? {color=#5175ea}*giggle*{/w}'
    was incorrectly skipped because '*' + '/' (from {/w}) triggered the glob check.
    """

    @pytest.mark.parametrize("text", [
        # The original bug report example
        "Oh, Are you looking for something again? {color=#5175ea}*giggle*{/w}",
        "A text with {color=#5175ea}*giggle*{/w} tag.",
        "Is it what I'm thinking of? {color=#5175ea}*giggle*{/w}",
        # Other closing tag + asterisk combinations
        "She laughed. {b}*hehe*{/b}",
        "The knight spoke: {i}*ahem*{/i} Your Majesty.",
        "Welcome! {color=#ff0000}*fanfare*{/color}",
        "Press start. {u}*click*{/u}",
        "{size=40}*BOOM*{/size} The explosion was deafening.",
        # Closing tags without asterisks (should still pass)
        "{color=#5175ea}Some text here{/color}",
        "{b}Bold text{/b} followed by normal text.",
        # Asterisks without closing tags (natural text)
        "He said *very* clearly that he disagrees.",
        "She *always* forgets her keys.",
    ])
    def test_renpy_closing_tag_with_asterisk_not_skipped(self, fmt, text):
        """Dialogue with Ren'Py closing tags + asterisks must NOT be skipped."""
        assert fmt._should_skip_translation(text) is False, (
            f"Should NOT skip (closing tag + asterisk false positive): {text!r}"
        )

    @pytest.mark.parametrize("text", [
        # Real glob/file patterns — these SHOULD still be skipped
        "images/*/background.png",
        "audio/*/*.ogg",
        "game/scripts/**/*.rpy",
        "sounds/**/theme_*.ogg",
    ])
    def test_real_glob_patterns_still_skipped(self, fmt, text):
        """Real file-system glob patterns must still be correctly skipped."""
        assert fmt._should_skip_translation(text) is True, (
            f"Should skip (real glob pattern): {text!r}"
        )

# ==================================================================
# v2.8.13: CAMELCASE IDENTIFIER SAFETY-NET
# ==================================================================
class TestCamelCaseSafetyNet:
    """camelCase identifiers must be skipped by the formatter safety-net
    (parity with the parser's is_meaningful_text camelCase check)."""

    @pytest.mark.parametrize("text", [
        "getUserName",
        "playIntro",
        "loadGameData",
        "checkPlayerStatus2",
        "onClickHandler",
    ])
    def test_camelcase_skipped(self, fmt, text):
        assert fmt._should_skip_translation(text) is True, f"Should skip: {text}"

    @pytest.mark.parametrize("text", [
        "SaveGame",      # Title Case UI label — not camelCase
        "New Game",      # two words
        "Continue",      # single normal word
        "Start the game now",
    ])
    def test_ui_labels_not_skipped(self, fmt, text):
        assert fmt._should_skip_translation(text) is False, f"Should NOT skip: {text}"


# ==================================================================
# v2.8.13: WRAPPED SECTION HEADINGS
# ==================================================================
class TestWrappedHeadings:
    """Menu/section dividers like ---Drops--- must never be translated."""

    @pytest.mark.parametrize("text", [
        "---Drops---",
        "===TITLE===",
        "~~separator~~",
        "++BONUS++",
        "**CHAPTER 1**".replace(" ", ""),  # **CHAPTER1**
        "---Seçimler---",  # non-ASCII stem
    ])
    def test_wrapped_headings_skipped(self, fmt, text):
        assert fmt._should_skip_translation(text) is True, f"Should skip: {text}"

    @pytest.mark.parametrize("text", [
        "Wait— what do you mean?",   # em-dash dialogue (has whitespace)
        "— What do you mean?",
        "I told you -- twice!",      # contains whitespace
        "Hello there",
        "*giggle*",                  # single-char wrapper
        "Well... okay.",
        "No-- I never said that.",
    ])
    def test_dialogue_not_skipped(self, fmt, text):
        assert fmt._should_skip_translation(text) is False, f"Should NOT skip: {text}"

    def test_helper_rules(self, fmt):
        """Direct helper checks incl. wrapper-character exclusions."""
        assert fmt._is_wrapped_heading("---Drops---") is True
        assert fmt._is_wrapped_heading("___x___") is False   # '_' cannot wrap
        assert fmt._is_wrapped_heading("..name..") is False  # '.' cannot wrap
        assert fmt._is_wrapped_heading("---") is False       # no inner content
        assert fmt._is_wrapped_heading("---A B---") is False  # whitespace


# ==================================================================
# v2.8.13: DATA-FILE EXTENSIONS & NON-ASCII ASSET PATHS
# ==================================================================
class TestDataFileExtensions:
    """Data-file references and non-ASCII asset paths must be skipped."""

    @pytest.mark.parametrize("text", [
        "settings.json",
        "quest_data.xml",
        "items.csv",
        "readme.txt",
        "save01.sav",
        "gameflow.dat",
        "theme.mid",
        "track.midi",
        "layer_art.psd",
        "img/キャラ.dat",      # non-ASCII stem with slash
        "bg/背景.xml",
        "sound\\効果音.dat",   # backslash variant
    ])
    def test_data_file_refs_skipped(self, fmt, text):
        assert fmt._should_skip_translation(text) is True, f"Should skip: {text}"

    @pytest.mark.parametrize("text", [
        "Check the save file.",
        "Read the note on the table.",
        "Save the princess!",
        "The data shows we are close.",
    ])
    def test_sentences_mentioning_files_not_skipped(self, fmt, text):
        assert fmt._should_skip_translation(text) is False, f"Should NOT skip: {text}"


# ==================================================================
# v2.8.13: PARSER PARITY (_is_wrapped_heading + is_meaningful_text)
# ==================================================================
class TestParserParity:
    """The parser mirrors the wrapped-heading filter (AGENTS.md: both
    control points must carry the same guard)."""

    @pytest.fixture
    def parser(self):
        from src.core.parser import RenPyParser
        return RenPyParser(config_manager=None)

    @pytest.mark.parametrize("text", [
        "---Drops---",
        "===TITLE===",
        "~~separator~~",
    ])
    def test_parser_rejects_wrapped_headings(self, parser, text):
        assert parser.is_meaningful_text(text) is False, f"Should reject: {text}"

    def test_helper_parity(self, parser, fmt):
        cases = [
            "---Drops---", "===TITLE===", "___x___", "..name..",
            "---", "—Wait—", "**bold**",
        ]
        for text in cases:
            assert parser._is_wrapped_heading(text) == fmt._is_wrapped_heading(text), (
                f"Parser/formatter disagreement on {text!r}"
            )
