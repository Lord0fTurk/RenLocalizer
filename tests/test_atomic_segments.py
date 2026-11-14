# -*- coding: utf-8 -*-
"""
Test Atomic Segment Registration (v2.7.1)

Verifies that delimiter groups (<A|B|C>) produce individual segment
translations alongside the combined block, so Ren'Py's runtime vary()
can find each segment independently.
"""
from src.core.syntax_guard import split_angle_pipe_groups, rejoin_angle_pipe_groups, split_delimited_text


class TestAtomicSegmentSplit:
    """split_angle_pipe_groups produces data that can be used for atomic registration."""

    def test_single_group_segments(self):
        """Single angle-pipe group → segments extractable."""
        text = "<The Swarm has incorporated 973 species.|My body can survive in Deep Space.|Human designs are inferior.>"
        result = split_angle_pipe_groups(text)
        assert result is not None
        template, groups = result
        assert len(groups) == 1
        assert len(groups[0]) == 3
        assert groups[0][0] == "The Swarm has incorporated 973 species."
        assert groups[0][1] == "My body can survive in Deep Space."
        assert groups[0][2] == "Human designs are inferior."

    def test_multi_group_segments(self):
        """Multiple angle-pipe groups → each group's segments extractable."""
        text = "Pirate activity <increasing|stable|declining> while trade is <booming|stagnant|collapsing>!"
        result = split_angle_pipe_groups(text)
        assert result is not None
        template, groups = result
        assert len(groups) == 2
        assert groups[0] == ["increasing", "stable", "declining"]
        assert groups[1] == ["booming", "stagnant", "collapsing"]
        # Template should have placeholders
        assert "[DGRP_0]" in template
        assert "[DGRP_1]" in template

    def test_rejoin_preserves_structure(self):
        """Translated segments rejoin correctly."""
        text = "<Hello world|Goodbye world>"
        result = split_angle_pipe_groups(text)
        assert result is not None
        template, groups = result
        
        translated_groups = [["Merhaba dünya", "Hoşça kal dünya"]]
        restored = rejoin_angle_pipe_groups(template, translated_groups)
        assert restored is not None
        assert "<Merhaba dünya|Hoşça kal dünya>" in restored

    def test_segments_individually_extractable(self):
        """Each segment from split can be used as an independent translation key."""
        text = "<Option A|Option B|Option C>"
        result = split_angle_pipe_groups(text)
        assert result is not None
        _, groups = result
        
        # Simulate atomic segment registration
        atomic_pairs = {}
        original_segments = groups[0]
        translated_segments = ["Seçenek A", "Seçenek B", "Seçenek C"]
        
        for orig, trans in zip(original_segments, translated_segments):
            if orig != trans:
                atomic_pairs[orig] = trans
        
        assert "Option A" in atomic_pairs
        assert atomic_pairs["Option A"] == "Seçenek A"
        assert "Option B" in atomic_pairs
        assert "Option C" in atomic_pairs

    def test_bare_pipe_segments(self):
        """Bare pipe pattern also produces extractable segments."""
        text = "Choice Alpha|Choice Beta|Choice Gamma"
        result = split_delimited_text(text)
        assert result is not None
        segments, delim, prefix, suffix = result
        assert len(segments) == 3
        assert segments[0] == "Choice Alpha"
        assert segments[1] == "Choice Beta"
        assert segments[2] == "Choice Gamma"
        assert delim == "|"


class TestAtomicSegmentRegistration:
    """Test the atomic segment dict building logic."""

    def test_atomic_dict_no_duplicates(self):
        """Same original segment should not overwrite existing translation."""
        atomic_segments = {}
        translations = {"Hello": "Merhaba"}  # Pre-existing
        
        # Simulate Faz 2.5 logic
        new_pairs = [("Hello", "Selam"), ("World", "Dünya")]
        for orig, trans in new_pairs:
            if orig not in translations:
                translations[orig] = trans
                atomic_segments[orig] = trans
        
        # "Hello" should keep original translation
        assert translations["Hello"] == "Merhaba"
        assert "Hello" not in atomic_segments
        # "World" should be added
        assert translations["World"] == "Dünya"
        assert atomic_segments["World"] == "Dünya"

    def test_skip_identical_translations(self):
        """If original == translated, don't register as atomic."""
        pairs = [("Hello", "Hello"), ("World", "Dünya")]
        atomic = [(o, t) for o, t in pairs if o != t]
        assert len(atomic) == 1
        assert atomic[0] == ("World", "Dünya")

    def test_large_delimiter_group(self):
        """5-segment group should produce 5 atomic entries."""
        text = "<The Swarm has incorporated the characteristics of 973 species.|The Swarm has not yet entered this region of Space.|My body construct can survive in Deep Space.|Memories of my primary mission are fragmented.|Human biological designs are inferior to Swarm Constructs.>"
        result = split_angle_pipe_groups(text)
        assert result is not None
        _, groups = result
        assert len(groups) == 1
        assert len(groups[0]) == 5
        
        # Each segment is a meaningful sentence
        for seg in groups[0]:
            assert len(seg) > 10
            assert seg[0].isupper()  # Each starts with capital

    def test_surrounding_text_with_segments(self):
        """Text around angle brackets produces proper template + segments."""
        text = "The captain said <Yes sir|No sir|Maybe> to the admiral."
        result = split_angle_pipe_groups(text)
        assert result is not None
        template, groups = result
        
        assert "[DGRP_0]" in template
        assert "captain" in template
        assert "admiral" in template
        assert groups[0] == ["Yes sir", "No sir", "Maybe"]


class TestQuoteStrippingLogic:
    """
    Test the quote-stripping logic used in the runtime hook.
    
    Some games (e.g. play_dialogue) wrap vary() output in literal quotes:
        renpy.say(speaker, '"' + talk + '"')
    The runtime hook must strip outer quotes for lookup and re-wrap the translation.
    """

    def _simulate_layer1_lookup(self, text, translations):
        """Simulate Layer 1 (say_menu_text_filter) quote-stripping logic."""
        # Try exact match first
        translated = translations.get(text)
        if translated is not None:
            return translated
        
        # Try stripped
        stripped = text.strip()
        if stripped:
            translated = translations.get(stripped)
            if translated is not None:
                return translated
        
        # Try 3: Quote-wrapped
        if len(text) >= 3:
            _t = text.strip()
            if len(_t) >= 3 and _t[0] == '"' and _t[-1] == '"':
                _inner = _t[1:-1]
                if _inner:
                    translated = translations.get(_inner)
                    if translated is None:
                        translated = translations.get(_inner.strip())
                    if translated is not None:
                        return '"' + translated + '"'
        return None

    def _simulate_layer2_lookup(self, text, translations, translations_ci=None):
        """Simulate Layer 2 (replace_text) quote-stripping logic."""
        _stripped = text.strip()
        
        # Step 1: exact
        translated = translations.get(_stripped)
        if translated is not None:
            return translated
        
        # Step 2: case-insensitive
        if translations_ci and _stripped:
            ci_val = translations_ci.get(_stripped.lower())
            if ci_val is not None:
                return ci_val
        
        # Step 3: quote-wrapped
        if _stripped and len(_stripped) >= 3:
            if _stripped[0] == '"' and _stripped[-1] == '"':
                _inner = _stripped[1:-1]
                if _inner:
                    _inner_stripped = _inner.strip()
                    _inner_leading = _inner[:len(_inner) - len(_inner.lstrip())]
                    _inner_trailing = _inner[len(_inner.rstrip()):]
                    translated = translations.get(_inner)
                    if translated is None and _inner_stripped and _inner_stripped != _inner:
                        trimmed_exact = translations.get(_inner_stripped)
                        if trimmed_exact is not None:
                            translated = _inner_leading + trimmed_exact + _inner_trailing
                    if translated is None and translations_ci:
                        translated = translations_ci.get(_inner.lower())
                    if translated is None and translations_ci and _inner_stripped and _inner_stripped != _inner:
                        trimmed_ci = translations_ci.get(_inner_stripped.lower())
                        if trimmed_ci is not None:
                            translated = _inner_leading + trimmed_ci + _inner_trailing
                    if translated is not None:
                        return '"' + translated + '"'
        return None

    def test_layer1_exact_match_no_quotes(self):
        """Layer 1: Normal text without quotes matches directly."""
        translations = {"Really?": "Gerçekten mi?"}
        result = self._simulate_layer1_lookup("Really?", translations)
        assert result == "Gerçekten mi?"

    def test_layer1_quoted_text_matches_inner(self):
        """Layer 1: '"Really?"' should match 'Really?' and re-wrap."""
        translations = {"Really?": "Gerçekten mi?"}
        result = self._simulate_layer1_lookup('"Really?"', translations)
        assert result == '"Gerçekten mi?"'

    def test_layer1_quoted_sentence(self):
        """Layer 1: Full sentence wrapped in quotes."""
        translations = {
            "I hope it was an interesting experience": "Umarım ilginç bir deneyim olmuştur"
        }
        result = self._simulate_layer1_lookup(
            '"I hope it was an interesting experience"', translations
        )
        assert result == '"Umarım ilginç bir deneyim olmuştur"'

    def test_layer1_no_match_returns_none(self):
        """Layer 1: No matching key → None."""
        translations = {"Hello": "Merhaba"}
        result = self._simulate_layer1_lookup('"Unknown text"', translations)
        assert result is None

    def test_layer1_single_char_quote_no_crash(self):
        """Layer 1: Very short quoted text should not crash."""
        translations = {"A": "B"}
        result = self._simulate_layer1_lookup('"A"', translations)
        assert result == '"B"'

    def test_layer1_empty_quotes_no_crash(self):
        """Layer 1: Empty quotes '""' should not crash or match."""
        translations = {"": "something"}
        result = self._simulate_layer1_lookup('""', translations)
        assert result is None

    def test_layer2_quoted_text_exact(self):
        """Layer 2: Quote-wrapped text matched via exact inner lookup."""
        translations = {"Really?": "Gerçekten mi?"}
        result = self._simulate_layer2_lookup('"Really?"', translations)
        assert result == '"Gerçekten mi?"'

    def test_layer2_quoted_text_case_insensitive(self):
        """Layer 2: Quote-wrapped text matched via case-insensitive inner lookup."""
        translations = {}
        translations_ci = {"really?": "Gerçekten mi?"}
        result = self._simulate_layer2_lookup('"Really?"', translations, translations_ci)
        assert result == '"Gerçekten mi?"'

    def test_layer2_quoted_text_with_inner_leading_space(self):
        """Layer 2: Inner quoted whitespace should not block lookup."""
        translations = {"That does not surprise me...": "Bu beni şaşırtmadı..."}
        result = self._simulate_layer2_lookup('" That does not surprise me..."', translations)
        assert result == '" Bu beni şaşırtmadı..."'

    def test_layer2_whitespace_preserved(self):
        """Layer 2: Leading/trailing whitespace stripped before quote check."""
        translations = {"Hello": "Merhaba"}
        result = self._simulate_layer2_lookup('  "Hello"  ', translations)
        assert result == '"Merhaba"'

    def test_layer2_non_quoted_exact(self):
        """Layer 2: Non-quoted text matches normally."""
        translations = {"Hello": "Merhaba"}
        result = self._simulate_layer2_lookup("Hello", translations)
        assert result == "Merhaba"

    def test_play_dialogue_scenario(self):
        """
        End-to-end play_dialogue scenario:
        Game does: renpy.say(mc, '"' + vary("Really?|Sure!") + '"')
        vary() picks "Really?", so text becomes '"Really?"'
        Our hook should translate inner text and re-wrap.
        """
        # strings.json translations (atomic segments from delimiter split)
        translations = {
            "Really?": "Gerçekten mi?",
            "Sure!": "Tabii ki!",
        }
        
        # Simulate vary() picking "Really?" then play_dialogue wrapping
        game_text = '"Really?"'
        
        # Layer 1 should handle this
        result = self._simulate_layer1_lookup(game_text, translations)
        assert result == '"Gerçekten mi?"'
        
        # Layer 2 should also handle this
        result2 = self._simulate_layer2_lookup(game_text, translations)
        assert result2 == '"Gerçekten mi?"'

    def test_nested_quotes_not_affected(self):
        """Text with internal quotes but not wrapped should not trigger stripping."""
        translations = {
            'He said "hello" to me': "Bana \"merhaba\" dedi"
        }
        result = self._simulate_layer1_lookup('He said "hello" to me', translations)
        assert result == 'Bana "merhaba" dedi'


class TestRenPyVaryCompatibility:
    """
    Test scenarios that match Ren'Py's actual runtime behavior.
    Ren'Py calls vary() to select individual segments from <A|B|C> groups.
    """

    def test_vary_lookup_after_split(self):
        """
        Simulates: Ren'Py has a string 'The Swarm has incorporated...' 
        and looks it up in the translation dict. With atomic segments,
        it should find the Turkish translation.
        """
        # Original game text (what Ren'Py passes to vary())
        original_segment = "The Swarm has incorporated the characteristics of 973 species."
        
        # What our pipeline should produce in translations dict
        translations = {}
        
        # Combined block entry (existing behavior)
        combined_orig = "<The Swarm has incorporated the characteristics of 973 species.|My body construct can survive in Deep Space.>"
        combined_trans = "<Swarm, 973 türün özelliklerini bünyesinde barındırıyor.|Benim vücut yapımız Derin Uzay'da hayatta kalabilir.>"
        translations[combined_orig] = combined_trans
        
        # Atomic segment entries (new v2.7.1 behavior)
        translations["The Swarm has incorporated the characteristics of 973 species."] = "Swarm, 973 türün özelliklerini bünyesinde barındırıyor."
        translations["My body construct can survive in Deep Space."] = "Benim vücut yapımız Derin Uzay'da hayatta kalabilir."
        
        # Ren'Py vary() lookup — should now find a match!
        assert original_segment in translations
        assert translations[original_segment] == "Swarm, 973 türün özelliklerini bünyesinde barındırıyor."

    def test_strings_json_includes_segments(self):
        """
        Simulates strings.json generation with extra_translations.
        Atomic segments should appear in the final JSON mapping.
        """
        # Existing mapping from tl_files entries
        mapping = {
            "Start Game": "Oyunu Başlat",
            "Settings": "Ayarlar"
        }
        
        # Extra translations (atomic segments from pipeline)
        extra = {
            "The Swarm has incorporated the characteristics of 973 species.": "Swarm, 973 türün özelliklerini bünyesinde barındırıyor.",
            "My body construct can survive in Deep Space.": "Benim vücut yapımız Derin Uzay'da hayatta kalabilir.",
        }
        
        # Merge logic (same as _generate_strings_json)
        for orig, trans in extra.items():
            orig_s = orig.strip()
            trans_s = trans.strip()
            if orig_s and trans_s and orig_s != trans_s and orig_s not in mapping:
                mapping[orig_s] = trans_s
        
        assert len(mapping) == 4
        assert "The Swarm has incorporated the characteristics of 973 species." in mapping
        assert "My body construct can survive in Deep Space." in mapping


class TestAtomicSegmentStringsJsonOnly:
    """
    After v2.7.1 hotfix, atomic segments are ONLY injected into strings.json
    (via extra_translations). The _rl_segments.rpy file is no longer generated.
    These tests verify the strings.json-only approach.
    """

    def test_segments_merge_into_mapping(self):
        """Atomic segments merge into strings.json mapping without duplicates."""
        mapping = {"Start Game": "Oyunu Başlat"}
        extra = {
            "Really?": "Gerçekten mi?",
            "Start Game": "Farklı Çeviri",  # duplicate — should be skipped
        }
        for orig, trans in extra.items():
            orig_s = orig.strip()
            trans_s = trans.strip()
            if orig_s and trans_s and orig_s != trans_s and orig_s not in mapping:
                mapping[orig_s] = trans_s
        
        assert len(mapping) == 2
        assert mapping["Start Game"] == "Oyunu Başlat"  # Original preserved
        assert mapping["Really?"] == "Gerçekten mi?"

    def test_identical_orig_trans_skipped(self):
        """Entries where original == translation are not added to strings.json."""
        mapping = {}
        extra = {"Hello": "Hello", "World": "Dünya"}
        for orig, trans in extra.items():
            orig_s = orig.strip()
            trans_s = trans.strip()
            if orig_s and trans_s and orig_s != trans_s and orig_s not in mapping:
                mapping[orig_s] = trans_s
        
        assert len(mapping) == 1
        assert "World" in mapping
        assert "Hello" not in mapping

    def test_empty_strings_skipped(self):
        """Empty or whitespace-only entries are not added."""
        mapping = {}
        extra = {"": "test", "  ": "test2", "Valid": "Geçerli"}
        for orig, trans in extra.items():
            orig_s = orig.strip()
            trans_s = trans.strip()
            if orig_s and trans_s and orig_s != trans_s and orig_s not in mapping:
                mapping[orig_s] = trans_s
        
        assert len(mapping) == 1
        assert "Valid" in mapping


class TestStringsJsonSegmentSplitting:
    """
    Test that _generate_strings_json splits <A|B|C> delimiter groups
    into individual segment entries for Ren'Py vary() compatibility.
    
    This is the core fix: strings.json must contain BOTH the combined block
    AND each individual segment, because vary() picks segments at runtime.
    """

    def _simulate_segment_splitting(self, mapping):
        """
        Simulate the segment splitting logic from _generate_strings_json.
        Takes a mapping dict, splits angle-pipe AND bare-pipe groups, returns updated mapping.
        """
        from src.core.syntax_guard import split_angle_pipe_groups, split_delimited_text
        _seg_additions = {}
        for m_orig, m_trans in list(mapping.items()):
            # Path 1: Angle-pipe groups (<A|B|C>)
            orig_split = split_angle_pipe_groups(m_orig)
            if orig_split is not None:
                trans_split = split_angle_pipe_groups(m_trans)
                if trans_split is not None:
                    _, orig_groups = orig_split
                    _, trans_groups = trans_split
                    for g_idx in range(min(len(orig_groups), len(trans_groups))):
                        o_segs = orig_groups[g_idx]
                        t_segs = trans_groups[g_idx]
                        for s_idx in range(min(len(o_segs), len(t_segs))):
                            o_s = o_segs[s_idx].strip()
                            t_s = t_segs[s_idx].strip()
                            if o_s and t_s and o_s != t_s and o_s not in mapping and o_s not in _seg_additions:
                                _seg_additions[o_s] = t_s
                continue
            
            # Path 2: Bare pipe (A|B|C, no angle brackets)
            if '|' not in m_orig:
                continue
            orig_delim = split_delimited_text(m_orig)
            if orig_delim is None:
                # Fallback: simple pipe split (vary() does exactly this)
                if '|' in m_orig and '|' in m_trans:
                    o_parts = m_orig.split('|')
                    t_parts = m_trans.split('|')
                    if len(o_parts) >= 2 and len(o_parts) == len(t_parts):
                        for o_s, t_s in zip(o_parts, t_parts):
                            o_s = o_s.strip()
                            t_s = t_s.strip()
                            if o_s and t_s and o_s != t_s and o_s not in mapping and o_s not in _seg_additions:
                                _seg_additions[o_s] = t_s
                continue
            
            o_segs, _, _, _ = orig_delim
            trans_delim = split_delimited_text(m_trans)
            if trans_delim is not None:
                t_segs, _, _, _ = trans_delim
            elif '|' in m_trans:
                t_segs = m_trans.split('|')
            else:
                continue
            
            for s_idx in range(min(len(o_segs), len(t_segs))):
                o_s = o_segs[s_idx].strip()
                t_s = t_segs[s_idx].strip()
                if o_s and t_s and o_s != t_s and o_s not in mapping and o_s not in _seg_additions:
                    _seg_additions[o_s] = t_s
        
        mapping.update(_seg_additions)
        return mapping

    def test_simple_angle_pipe_splits(self):
        """<A|B|C> block produces individual segment entries."""
        mapping = {
            "<Really?|Interesting...|Is that so?>": "<Gerçekten mi?|İlginç...|Böylece?>"
        }
        result = self._simulate_segment_splitting(mapping)
        
        # Combined block preserved
        assert "<Really?|Interesting...|Is that so?>" in result
        # Individual segments added
        assert result["Really?"] == "Gerçekten mi?"
        assert result["Interesting..."] == "İlginç..."
        assert result["Is that so?"] == "Böylece?"

    def test_five_segment_group(self):
        """5-segment Swarm group produces 5 individual entries."""
        mapping = {
            "<The Swarm has incorporated the characteristics of 973 species."
            "|The Swarm has not yet entered this region of Space."
            "|My body construct can survive in Deep Space."
            "|Memories of my primary mission are fragmented."
            "|Human biological designs are inferior to Swarm Constructs.>":
            "<Swarm, 973 türün özelliklerini bünyesinde barındırıyor."
            "|Swarm henüz Uzayın bu bölgesine girmedi."
            "|Benim vücut yapımız Derin Uzay'da hayatta kalabilir."
            "|Birincil görevimin anıları parçalanmış durumda."
            "|İnsanın biyolojik tasarımları Swarm Yapılarından daha düşüktür.>"
        }
        result = self._simulate_segment_splitting(mapping)
        
        assert "The Swarm has incorporated the characteristics of 973 species." in result
        assert result["The Swarm has incorporated the characteristics of 973 species."] == "Swarm, 973 türün özelliklerini bünyesinde barındırıyor."
        assert "My body construct can survive in Deep Space." in result
        assert "Human biological designs are inferior to Swarm Constructs." in result
        # 1 combined + 5 segments = 6 total
        assert len(result) == 6

    def test_two_segment_group(self):
        """<A|B> block also splits."""
        mapping = {
            "<Awesome, right?|I took care of that!>": "<Harika, değil mi?|Ben hallettim!>"
        }
        result = self._simulate_segment_splitting(mapping)
        assert result["Awesome, right?"] == "Harika, değil mi?"
        assert result["I took care of that!"] == "Ben hallettim!"

    def test_embedded_angle_group(self):
        """Text with embedded <A|B|C> group splits segments from the group."""
        mapping = {
            "And they all <are naked|wear collars|are shaved|are blonde>...":
            "Ve hepsi <çıplak|yaka giymek|tıraş edildi|sarışın mı>..."
        }
        result = self._simulate_segment_splitting(mapping)
        assert result["are naked"] == "çıplak"
        assert result["wear collars"] == "yaka giymek"
        assert result["are shaved"] == "tıraş edildi"
        assert result["are blonde"] == "sarışın mı"

    def test_no_pipe_no_split(self):
        """Single-segment entries (no pipe) are not split."""
        mapping = {
            "Hello world": "Merhaba dünya",
            "<Really?>": "<Gerçekten mi?>"  # No pipe — no split
        }
        result = self._simulate_segment_splitting(mapping)
        assert len(result) == 2  # No new entries added

    def test_existing_segment_not_overwritten(self):
        """If a segment already exists in mapping, it's not overwritten."""
        mapping = {
            "Really?": "Sahiden mi?",  # Pre-existing with different translation
            "<Really?|Interesting...>": "<Gerçekten mi?|İlginç...>"
        }
        result = self._simulate_segment_splitting(mapping)
        # Pre-existing translation preserved
        assert result["Really?"] == "Sahiden mi?"
        # "Interesting..." added as new
        assert result["Interesting..."] == "İlginç..."

    def test_identical_orig_trans_segment_skipped(self):
        """Segments where original == translated are not added."""
        mapping = {
            "<Hello|World>": "<Hello|Dünya>"
        }
        result = self._simulate_segment_splitting(mapping)
        assert "Hello" not in result  # Same in both languages
        assert result["World"] == "Dünya"

    def test_vary_end_to_end_scenario(self):
        """
        End-to-end: strings.json has combined block → splitting adds segments →
        vary() picks one → runtime hook finds translation.
        """
        # Step 1: strings.json mapping from .rpy files (combined blocks only)
        mapping = {
            "Start Game": "Oyunu Başlat",
            "<Really?|Interesting...|Is that so?|I see...>": "<Gerçekten mi?|İlginç...|Böylece?|Anlıyorum...>",
        }
        
        # Step 2: Segment splitting (what _generate_strings_json now does)
        result = self._simulate_segment_splitting(mapping)
        
        # Step 3: vary() picks "Really?" at runtime, play_dialogue wraps it as '"Really?"'
        # Runtime hook strips quotes → looks up "Really?" in strings.json
        lookup_key = "Really?"
        assert lookup_key in result
        assert result[lookup_key] == "Gerçekten mi?"
        
        # All 4 segments should be findable
        assert "Interesting..." in result
        assert "Is that so?" in result
        assert "I see..." in result

    def test_bare_pipe_splits(self):
        """Bare pipe pattern (no angle brackets) also splits into segments."""
        mapping = {
            "Interesting...|Really...?|Indeed...": "İlginç...|Gerçekten...?|Gerçekten..."
        }
        result = self._simulate_segment_splitting(mapping)
        assert result["Interesting..."] == "İlginç..."
        assert result["Really...?"] == "Gerçekten...?"
        assert result["Indeed..."] == "Gerçekten..."

    def test_bare_pipe_with_space(self):
        """Bare pipe with leading space in segment."""
        mapping = {
            "Indubitably so...| That does not surprise me...":
            "Şüphesiz öyle...|Bu beni şaşırtmadı..."
        }
        result = self._simulate_segment_splitting(mapping)
        assert result["Indubitably so..."] == "Şüphesiz öyle..."
        assert result["That does not surprise me..."] == "Bu beni şaşırtmadı..."

    def test_mixed_angle_and_bare_pipe(self):
        """Both angle-pipe and bare pipe entries in same mapping."""
        mapping = {
            "<Really?|Interesting...>": "<Gerçekten mi?|İlginç...>",
            "Option A|Option B|Option C": "Seçenek A|Seçenek B|Seçenek C",
        }
        result = self._simulate_segment_splitting(mapping)
        # Angle-pipe segments
        assert result["Really?"] == "Gerçekten mi?"
        assert result["Interesting..."] == "İlginç..."
        # Bare pipe segments
        assert result["Option A"] == "Seçenek A"
        assert result["Option B"] == "Seçenek B"
        assert result["Option C"] == "Seçenek C"

    def test_game_bare_pipe_real_example(self):
        """Real game example: bare pipe dialogue.
        This pattern comes from vary('A|B|C') without angle brackets.
        """
        mapping = {
            "Interesting...|Really...?|Indeed...": "İlginç...|Gerçekten...?|Gerçekten...",
            "<Interesting...|Indeed...|Really?|No doubt...>": "<İlginç...|Aslında...|Gerçekten mi?|Hiç şüphe yok ki...>",
        }
        result = self._simulate_segment_splitting(mapping)
        # Bare pipe segment
        assert "Indeed..." in result
        assert result["Indeed..."] == "Gerçekten..."
        # Angle-pipe segments
        assert "No doubt..." in result
        assert result["No doubt..."] == "Hiç şüphe yok ki..."

    def test_segment_count_unequal_skips(self):
        """If orig and trans have different segment counts, bare pipe fallback skips entirely."""
        mapping = {
            "A|B|C": "X|Y"  # 3 orig vs 2 trans — mismatched count
        }
        result = self._simulate_segment_splitting(mapping)
        # Unequal segment counts → no segments extracted (safety)
        assert len(result) == 1  # Only original combined entry remains
        assert "A" not in result
        assert "B" not in result
