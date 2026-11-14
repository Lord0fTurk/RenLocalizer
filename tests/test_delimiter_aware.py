"""
Tests for Delimiter-Aware Translation (v2.7.3 — Hardened)

Covers:
- split_delimited_text() — Pipe-delimited text detection and splitting
- rejoin_delimited_text() — Segment reassembly with structural validation
- False-positive detection (_is_code_like_segment, _is_natural_language_segment)
- Integration with protect_renpy_syntax / restore_renpy_syntax
- Edge cases: nested brackets, single segment, empty, Ren'Py tags inside segments
- Structural corruption detection and rollback
"""
from src.core.syntax_guard import (
    split_delimited_text,
    rejoin_delimited_text,
    protect_renpy_syntax,
    restore_renpy_syntax,
    _is_code_like_segment,
    _is_natural_language_segment,
    _has_structural_integrity,
)


# =============================================================================
# Test: split_delimited_text()
# =============================================================================

class TestSplitDelimitedText:
    """Tests for split_delimited_text()."""

    def test_angle_bracket_pipe_basic(self):
        """Basic <seg1|seg2|seg3> pattern."""
        text = "<You don't say.|Really now?|Interesting stuff...>"
        result = split_delimited_text(text)
        assert result is not None
        segments, delim, prefix, suffix = result
        assert segments == ["You don't say.", "Really now?", "Interesting stuff..."]
        assert delim == '|'
        assert prefix == '<'
        assert suffix == '>'

    def test_angle_bracket_pipe_two_segments(self):
        """Two-segment <seg1|seg2> pattern."""
        text = "<The Princess is an apt student...|The Princess needs to be disciplined...>"
        result = split_delimited_text(text)
        assert result is not None
        segments, delim, prefix, suffix = result
        assert len(segments) == 2
        assert segments[0] == "The Princess is an apt student..."
        assert segments[1] == "The Princess needs to be disciplined..."

    def test_angle_bracket_pipe_many_segments(self):
        """Six-segment variant dialogue from SpaceJourneyX."""
        text = "<Space weather in Xenos can be challenging...|Xenos III has 7 percent Argon...|Cobalt from Xenos III is the most blue...|Krell Executors occasionally infiltrate Xenos...|I once encountered a Neutrino Storm...|In Xenos Academy I was a gymnast...>"
        result = split_delimited_text(text)
        assert result is not None
        segments, _, _, _ = result
        assert len(segments) == 6

    def test_no_delimiter_plain_text(self):
        """Plain text without delimiters returns None."""
        assert split_delimited_text("Hello, world!") is None

    def test_no_delimiter_empty_string(self):
        """Empty string returns None."""
        assert split_delimited_text("") is None

    def test_no_delimiter_none_like(self):
        """None-like inputs return None."""
        assert split_delimited_text("") is None

    def test_no_pipe_in_text(self):
        """Text without pipe character returns None."""
        assert split_delimited_text("<Just a single statement>") is None

    def test_single_pipe_renpy_tag_not_split(self):
        """Ren'Py text with | in tag is NOT a delimiter pattern."""
        text = "{color=#ff0000}Red text{/color}"
        assert split_delimited_text(text) is None

    def test_angle_bracket_preserves_whitespace(self):
        """Whitespace in segments is preserved."""
        text = "< Hello world today | Goodbye world forever >"
        result = split_delimited_text(text)
        assert result is not None
        segments, _, _, _ = result
        assert " Hello world today " in segments[0]
        assert " Goodbye world forever " in segments[1]

    def test_angle_bracket_with_leading_text(self):
        """Text before <...> is part of prefix."""
        text = "NPC says: <Let me think about it|I want to go home|Stay here with me>"
        result = split_delimited_text(text)
        assert result is not None
        segments, delim, prefix, suffix = result
        assert prefix == "NPC says: <"
        assert suffix == ">"
        assert len(segments) == 3

    def test_bare_pipe_basic(self):
        """Bare pipe without angle brackets: seg1|seg2|seg3."""
        text = "First option here|Second option here|Third option here"
        result = split_delimited_text(text)
        assert result is not None
        segments, delim, prefix, suffix = result
        assert len(segments) == 3
        assert delim == '|'
        assert prefix == ''  # No wrapping
        assert suffix == ''

    def test_bare_pipe_too_short_segments(self):
        """Bare pipe with segments under 3 chars is NOT recognized."""
        text = "A|B|C"
        assert split_delimited_text(text) is None

    def test_bare_pipe_with_renpy_syntax_not_split(self):
        """Bare pipe with [var] or {tag} inside segments is NOT split (false positive prevention)."""
        text = "[player.name] is here|{b}Bold{/b} text"
        assert split_delimited_text(text) is None
    
    def test_bare_pipe_starts_with_bracket_not_split(self):
        """Text starting with { or [ is skipped by bare pipe detector."""
        text = "{tag}hello|world"
        assert split_delimited_text(text) is None

    def test_empty_segment_rejected(self):
        """Angle bracket with empty segment is rejected."""
        text = "<First||Third>"
        result = split_delimited_text(text)
        assert result is None

    def test_single_angle_segment_no_pipe(self):
        """Single segment in angle brackets with no pipe → no split."""
        text = "<Single statement without pipe>"
        assert split_delimited_text(text) is None


# =============================================================================
# Test: rejoin_delimited_text()
# =============================================================================

class TestRejoinDelimitedText:
    """Tests for rejoin_delimited_text() (v2.7.3 — with structural validation)."""

    def test_basic_rejoin_angle(self):
        """Basic angle-bracket rejoin."""
        translated = ["Birinci seçenek", "İkinci seçenek", "Üçüncü seçenek"]
        result = rejoin_delimited_text(translated, '|', '<', '>')
        assert result == "<Birinci seçenek|İkinci seçenek|Üçüncü seçenek>"

    def test_rejoin_with_prefix_suffix(self):
        """Rejoin with prefix text."""
        translated = ["Merhaba dünya", "Hoşçakal dünya"]
        result = rejoin_delimited_text(translated, '|', 'NPC diyor: <', '>')
        assert result == "NPC diyor: <Merhaba dünya|Hoşçakal dünya>"

    def test_rejoin_bare_pipe(self):
        """Rejoin bare pipe (no brackets)."""
        translated = ["Opsiyon bir", "Opsiyon iki"]
        result = rejoin_delimited_text(translated, '|', '', '')
        assert result == "Opsiyon bir|Opsiyon iki"

    def test_rejoin_single_segment(self):
        """Single segment rejoin."""
        result = rejoin_delimited_text(["Tek metindir"], '|', '<', '>')
        assert result == "<Tek metindir>"

    def test_rejoin_preserves_spaces(self):
        """Spaces in segments preserved during rejoin."""
        result = rejoin_delimited_text([" Boşluklu metin verdim ", " İkinci metin "], '|', '<', '>')
        assert result == "< Boşluklu metin verdim | İkinci metin >"

    # ── Structural Corruption Detection (v2.7.3) ─────────────────────────

    def test_rejoin_rejects_nested_angle_brackets(self):
        """If a translated segment contains < or >, rejoin returns None."""
        # Simulates: "Knave" → "<Kızıl'ın Knave'i|Yasaklı>" by translator
        corrupted = ["Corsair", "Kaptan", "<Kızıl'ın Knave'i|Yasaklı>"]
        result = rejoin_delimited_text(corrupted, '|', '<', '>')
        assert result is None  # Structural corruption detected

    def test_rejoin_rejects_segment_with_angle_open(self):
        """Single < in translated segment causes rejection."""
        corrupted = ["Normal metin", "Bozuk < metin"]
        result = rejoin_delimited_text(corrupted, '|', '<', '>')
        assert result is None

    def test_rejoin_rejects_segment_with_angle_close(self):
        """Single > in translated segment causes rejection."""
        corrupted = ["Normal metin", "Bozuk > metin"]
        result = rejoin_delimited_text(corrupted, '|', '<', '>')
        assert result is None

    def test_rejoin_rejects_pipe_in_segment(self):
        """If translator introduces | inside a segment, rejoin returns None."""
        corrupted = ["Birinci tercih", "İkinci|Üçüncü"]  # pipe leaked into segment
        result = rejoin_delimited_text(corrupted, '|', '<', '>')
        assert result is None

    def test_rejoin_rejects_empty_segment(self):
        """Empty translated segment → rejection."""
        corrupted = ["Birinci tercih", ""]
        result = rejoin_delimited_text(corrupted, '|', '<', '>')
        assert result is None

    def test_rejoin_pipe_count_mismatch_with_original(self):
        """When original_text is provided, pipe count must match."""
        original = "<A nice choice|Another choice|Third choice>"
        # Correct: 2 pipes in original, 2 in result
        good = ["İyi bir seçim", "Başka bir seçim", "Üçüncü seçim"]
        result = rejoin_delimited_text(good, '|', '<', '>', original_text=original)
        assert result is not None  # OK — 2 pipes match

    def test_rejoin_bare_pipe_allows_angles_in_segments(self):
        """Bare pipe (no angle prefix/suffix) allows < > in segments."""
        # When prefix/suffix don't contain <>, the angle bracket check doesn't apply
        translated = ["Metin <vurgulu>", "Diğer metin"]
        result = rejoin_delimited_text(translated, '|', '', '')
        assert result is not None  # OK — bare pipe has no angle check
        assert result == "Metin <vurgulu>|Diğer metin"


# =============================================================================
# Test: Round-trip (split → translate segments → rejoin)
# =============================================================================

class TestDelimiterRoundTrip:
    """Tests for the full split → protect → restore → rejoin cycle."""

    def test_roundtrip_angle_bracket(self):
        """Split and rejoin angle-bracket text preserves format."""
        original = "<You are doing great today.|She seems very happy.|Is that really so?|Maybe we should move on.>"
        result = split_delimited_text(original)
        assert result is not None
        segments, delim, prefix, suffix = result

        # Simulate translation: each segment goes through protect → translate → restore
        translated_segments = []
        for seg in segments:
            protected, phs = protect_renpy_syntax(seg.strip())
            # Simulate Google Translate (no actual API call, just pass through)
            fake_translated = protected  # In real life, this would be translated
            restored = restore_renpy_syntax(fake_translated, phs)
            translated_segments.append(restored)

        # Rejoin
        final = rejoin_delimited_text(translated_segments, delim, prefix, suffix, original_text=original)
        assert final is not None  # No structural corruption
        assert final == original  # Identity round-trip

    def test_roundtrip_with_renpy_vars_in_segments(self):
        """Segments containing Ren'Py variables are protected individually."""
        original = "<I met [player.name] today at the cafe...|[player.name] was really helpful to me...>"
        result = split_delimited_text(original)
        assert result is not None
        segments, delim, prefix, suffix = result
        assert len(segments) == 2

        translated_segments = []
        for seg in segments:
            protected, phs = protect_renpy_syntax(seg.strip())
            # Verify variable was tokenized
            assert '[player.name]' not in protected
            assert any('player.name' in v for v in phs.values())
            # Restore
            restored = restore_renpy_syntax(protected, phs)
            translated_segments.append(restored)

        final = rejoin_delimited_text(translated_segments, delim, prefix, suffix, original_text=original)
        assert final is not None
        assert '[player.name]' in final
        assert final.count('|') == 1  # One pipe delimiter preserved

    def test_roundtrip_with_text_tags_in_segments(self):
        """Segments with {b}, {i} text tags are protected individually."""
        original = "<{b}Bold option text here{/b}|{i}Italic option text here{/i}>"
        result = split_delimited_text(original)
        assert result is not None
        segments, delim, prefix, suffix = result

        translated_segments = []
        for seg in segments:
            protected, phs = protect_renpy_syntax(seg.strip())
            restored = restore_renpy_syntax(protected, phs)
            translated_segments.append(restored)

        final = rejoin_delimited_text(translated_segments, delim, prefix, suffix, original_text=original)
        assert final is not None
        assert '{b}' in final
        assert '{/b}' in final
        assert '{i}' in final
        assert '{/i}' in final
        assert '|' in final

    def test_roundtrip_real_spacejourneyX(self):
        """Real-world SpaceJourneyX dialogue pattern."""
        original = "<The Swarm has incorporated the characteristics of 973 species.|The Swarm has not yet entered this region of Space.|My body construct can survive in Deep Space.|Memories of my primary mission are fragmented.|Human biological designs are inferior to Swarm Constructs.>"
        result = split_delimited_text(original)
        assert result is not None
        segments, delim, prefix, suffix = result
        assert len(segments) == 5
        assert prefix == '<'
        assert suffix == '>'

        # Rejoin with same segments
        final = rejoin_delimited_text(segments, delim, prefix, suffix, original_text=original)
        assert final is not None
        assert final == original


# =============================================================================
# Test: Edge cases
# =============================================================================

class TestDelimiterEdgeCases:
    """Edge case tests for delimiter handling."""

    def test_pipe_inside_renpy_format_string(self):
        """Pipe inside a format specifier should NOT trigger delimiter split."""
        text = "{color=#ff0000}Red|Blue{/color}"
        # Starts with { so bare pipe is skipped. For angle: no <> wrapper.
        assert split_delimited_text(text) is None

    def test_pipe_in_condition_string(self):
        """Pipe in Python condition-like string is not a delimiter."""
        text = "x == 1 | y == 2"
        # Contains comparison operators → code-like → rejected
        result = split_delimited_text(text)
        assert result is None

    def test_angle_brackets_nested(self):
        """Nested angle brackets: only outermost pair matched."""
        text = "<Option <A>|Option <B>>"
        result = split_delimited_text(text)
        # With [^>]* the regex won't match because > appears before the closing >
        assert result is None  

    def test_multi_byte_chars_in_segments(self):
        """Unicode text in segments."""
        text = "<Привет мир сегодня!|Добрый день всем!|До свидания друзья!>"
        result = split_delimited_text(text)
        assert result is not None
        segments, _, _, _ = result
        assert len(segments) == 3
        assert segments[0] == "Привет мир сегодня!"

    def test_ellipsis_and_punctuation_in_segments(self):
        """Segments with ellipsis, question marks, exclamation marks."""
        text = "<How can that be so?|Is that really true?!|Indeed it seems so...>"
        result = split_delimited_text(text)
        assert result is not None
        segments, _, _, _ = result
        assert len(segments) == 3

    def test_format_specifier_in_segment(self):
        """Segment with %s format string is protected."""
        original = "<Hello there %s friend|Goodbye dear %s today>"
        result = split_delimited_text(original)
        assert result is not None
        segments, delim, prefix, suffix = result

        translated_segments = []
        for seg in segments:
            protected, phs = protect_renpy_syntax(seg.strip())
            # %s should be protected
            assert '%s' not in protected or not phs
            restored = restore_renpy_syntax(protected, phs)
            assert '%s' in restored
            translated_segments.append(restored)

        final = rejoin_delimited_text(translated_segments, delim, prefix, suffix, original_text=original)
        assert final is not None
        assert final.count('%s') == 2


# =============================================================================
# Test: False-Positive Detection (v2.7.3 — NEW)
# =============================================================================

class TestFalsePositiveDetection:
    """Tests for _is_code_like_segment and false-positive prevention."""

    # ── _is_code_like_segment ─────────────────────────────────────────────

    def test_dot_notation_is_code(self):
        """Dot notation like GAME.mc.done is code-like."""
        assert _is_code_like_segment("GAME.mc.done") is True
        assert _is_code_like_segment("player.quest_completed") is True
        assert _is_code_like_segment("obj.method") is True

    def test_snake_case_is_code(self):
        """snake_case tokens are code-like."""
        assert _is_code_like_segment("quest_log") is True
        assert _is_code_like_segment("mc_name") is True
        assert _is_code_like_segment("is_completed") is True

    def test_all_caps_is_code(self):
        """ALL_CAPS constants are code-like."""
        assert _is_code_like_segment("INTRO") is True
        assert _is_code_like_segment("MC_NAME") is True
        assert _is_code_like_segment("CHAPTER1") is True

    def test_function_call_is_code(self):
        """Function call patterns are code-like."""
        assert _is_code_like_segment("func(x)") is True
        assert _is_code_like_segment("renpy.show(") is True

    def test_assignment_is_code(self):
        """Assignments are code-like."""
        assert _is_code_like_segment("x = 5") is True
        assert _is_code_like_segment("y += 1") is True

    def test_comparison_is_code(self):
        """Comparisons are code-like."""
        assert _is_code_like_segment("x == 1") is True
        assert _is_code_like_segment("a >= 5") is True
        assert _is_code_like_segment("b != 0") is True

    def test_keywords_are_code(self):
        """Python/Ren'Py keywords are code-like."""
        assert _is_code_like_segment("return") is True
        assert _is_code_like_segment("True") is True
        assert _is_code_like_segment("None") is True
        assert _is_code_like_segment("jump") is True
        assert _is_code_like_segment("screen") is True

    def test_file_paths_are_code(self):
        """File paths are code-like."""
        assert _is_code_like_segment("images/character") is True
        assert _is_code_like_segment("data\\save") is True

    def test_numbers_are_code(self):
        """Pure numbers are code-like."""
        assert _is_code_like_segment("42") is True
        assert _is_code_like_segment("3.14") is True

    def test_natural_language_is_not_code(self):
        """Normal dialogue text is NOT code-like."""
        assert _is_code_like_segment("I enjoy missions in space") is False
        assert _is_code_like_segment("The Princess was happy today") is False
        assert _is_code_like_segment("Really interesting story") is False

    def test_short_natural_words_not_code(self):
        """Short natural words should not be flagged as code."""
        # 'Hello' is 5 chars, 1 word — short but not code-like
        assert _is_code_like_segment("Hello") is False
        assert _is_code_like_segment("World") is False
        # But ALL_CAPS single words ARE code-like
        assert _is_code_like_segment("HELLO") is True

    # ── _is_natural_language_segment ──────────────────────────────────────

    def test_natural_language_basic(self):
        """Multi-word sentence is natural language."""
        assert _is_natural_language_segment("I enjoy missions in space") is True
        assert _is_natural_language_segment("The Princess was happy") is True

    def test_too_short_not_natural(self):
        """Text under min_len is not natural language."""
        assert _is_natural_language_segment("Hi") is False
        assert _is_natural_language_segment("OK bye") is False

    def test_single_word_not_natural(self):
        """Single word under default min_words is not natural."""
        assert _is_natural_language_segment("Hello") is False

    def test_code_not_natural(self):
        """Code-like text is not natural language."""
        assert _is_natural_language_segment("GAME.mc.done extra") is False
        assert _is_natural_language_segment("player.quest log") is False

    # ── _has_structural_integrity ─────────────────────────────────────────

    def test_valid_segments(self):
        """Natural language segments pass integrity check."""
        assert _has_structural_integrity(["I enjoy missions", "She was happy today"]) is True

    def test_too_many_segments(self):
        """More than 15 segments fails integrity check."""
        segs = [f"Segment number {i} here" for i in range(16)]
        assert _has_structural_integrity(segs) is False

    def test_single_segment_fails(self):
        """Single segment fails integrity check."""
        assert _has_structural_integrity(["Only one segment"]) is False

    def test_empty_segment_fails(self):
        """Empty segment in list fails integrity check."""
        assert _has_structural_integrity(["Good text", ""]) is False

    def test_mostly_code_segments_fails(self):
        """Majority code-like segments fail integrity check."""
        assert _has_structural_integrity(["GAME.mc", "player.done", "Hello world here"]) is False

    def test_nested_angle_pipe_in_segment_fails(self):
        """Segment with <...|...> nested pattern fails integrity."""
        assert _has_structural_integrity(["normal text here", "<nested|pattern>"]) is False

    # ── Full split false-positive rejection ───────────────────────────────

    def test_code_like_angle_bracket_rejected(self):
        """<code|code|code> is rejected by false-positive filter."""
        text = "<GAME.mc.done|player.quest_completed|is_active>"
        assert split_delimited_text(text) is None

    def test_mixed_code_natural_rejected(self):
        """Even one code-like segment causes full rejection."""
        text = "<I enjoy missions|GAME.mc.done|She was happy>"
        assert split_delimited_text(text) is None

    def test_short_identifiers_rejected(self):
        """Short single-word identifiers like <Corsair|Captain|Knave> are rejected."""
        text = "<Corsair|Captain|Knave>"
        assert split_delimited_text(text) is None  # All single-word, too short

    def test_game_choices_with_sentences_accepted(self):
        """Actual dialogue choices with full sentences are accepted."""
        text = "<I think we should go now|Maybe we can stay here|Let me think about it>"
        result = split_delimited_text(text)
        assert result is not None
        assert len(result[0]) == 3

    def test_bare_pipe_code_rejected(self):
        """Bare pipe with code-like segments is rejected."""
        text = "GAME.mc.done|player.active|quest_log.check"
        assert split_delimited_text(text) is None

    def test_all_caps_identifiers_rejected(self):
        """<ALL_CAPS|TOKENS|HERE> are rejected."""
        text = "<INTRO|CHAPTER1|FINALE>"
        assert split_delimited_text(text) is None


# =============================================================================
# Test: Config toggle
# =============================================================================

class TestDelimiterConfigToggle:
    """Test that the delimiter feature respects config toggle."""

    def test_split_works_when_enabled(self):
        """split_delimited_text produces output for valid natural language patterns."""
        text = "<I want to go home now|Maybe we should stay here>"
        result = split_delimited_text(text)
        assert result is not None

    def test_split_independent_of_config(self):
        """split_delimited_text is a pure function — config check is in pipeline only."""
        text = "<First test sentence here|Second test sentence here>"
        result = split_delimited_text(text)
        assert result is not None
        assert len(result[0]) == 2


# =============================================================================
# Test: Structural Corruption Scenarios (v2.7.3 — Real-world)
# =============================================================================

class TestStructuralCorruptionScenarios:
    """Real-world corruption scenarios from SpaceJourneyX crash analysis."""

    def test_translator_introduces_angle_brackets(self):
        """Translator producing <...|...> inside a segment is caught."""
        # Simulates the L63700 bug: "Knave" translated to "<Kızıl'ın Knave'i|Yasaklı>"
        segments = ["Korsan gemisi", "Kaptan rütbesi", "<Kızıl'ın Knave'i|Yasaklı>"]
        result = rejoin_delimited_text(segments, '|', '<', '>')
        assert result is None  # Structural corruption → None

    def test_translator_introduces_extra_pipe(self):
        """Translator introducing | inside a segment corrupts pipe count."""
        segments = ["Birinci seçenek", "İkinci|Üçüncü seçenek"]
        result = rejoin_delimited_text(segments, '|', '<', '>', original_text="<First|Second>")
        assert result is None  # Pipe count mismatch: expected 1, got 2

    def test_translator_empties_a_segment(self):
        """Translator returning empty string for a segment is caught."""
        segments = ["Güzel bir seçim", "  ", "Harika bir fikir"]
        result = rejoin_delimited_text(segments, '|', '<', '>')
        assert result is None  # Empty/whitespace segment

    def test_valid_translation_passes(self):
        """Correctly translated segments pass all checks."""
        original = "<I enjoy missions in deep space|She was trained with weapons|He infiltrated the enemy base>"
        split = split_delimited_text(original)
        assert split is not None

        translated = ["Derin uzayda görevlerden hoşlanırım", "Silahlarla eğitildi", "Düşman üssüne sızdı"]
        result = rejoin_delimited_text(translated, '|', '<', '>', original_text=original)
        assert result is not None
        assert result == "<Derin uzayda görevlerden hoşlanırım|Silahlarla eğitildi|Düşman üssüne sızdı>"
        assert result.count('|') == original.count('|')  # Pipe count preserved

    def test_game_code_references_not_split(self):
        """Game code references like GAME.mc.done are NOT split."""
        # These are common in Ren'Py game strings but are NOT dialogue variants
        text = "<GAME.mc.done|player.quest_completed|npc.dialogue_state>"
        assert split_delimited_text(text) is None

    def test_mixed_identifiers_and_text_rejected(self):
        """Mix of code identifiers and text is rejected."""
        text = "<Corsair|Captain|Knave>"
        # Single words, short segments (all <8 chars) — should be rejected
        assert split_delimited_text(text) is None
