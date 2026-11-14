# -*- coding: utf-8 -*-
"""Unit tests for GlossaryManager."""

from src.core.glossary_manager import GlossaryManager, preserve_case


def test_preserve_case():
    assert preserve_case("apple", "elma") == "elma"
    assert preserve_case("Apple", "elma") == "Elma"
    assert preserve_case("APPLE", "elma") == "ELMA"


def test_protect_terms():
    glossary = {"Lord": "Efendi", "Dark Lord": "Karanlık Efendi"}
    text = "The Dark Lord meets the Lord."
    
    protected, placeholders = GlossaryManager.protect_terms(text, glossary, xml_mode=False)
    
    # Dark Lord is longer, so it must be protected first
    assert len(placeholders) == 2
    assert "Dark Lord" not in protected
    assert "Lord" not in protected


def test_apply_glossary():
    glossary = {"Start": "Başla", "Load": "Yükle"}
    
    # Exact match test
    assert GlossaryManager.apply_glossary("Start", glossary, original_text="Start") == "Başla"
    
    # Text replacement test
    assert GlossaryManager.apply_glossary("Press Start to play.", glossary) == "Press Başla to play."


def test_stopwords_skipped_in_protect_terms():
    """Verify that common English stopwords are NOT protected as identity tokens."""
    glossary = {
        "To": "To",
        "Her": "Her",
        "An": "An",
        "Man": "Man",
        "Nurse": "Nurse",
        "Alice": "Alice",  # Real character name, must be protected
    }
    text = "We need to leave, this is her room. An old nurse told the man. Alice stayed."
    protected, placeholders = GlossaryManager.protect_terms(text, glossary, xml_mode=False)

    # Only Alice should be protected
    assert len(placeholders) == 1
    assert "Alice" not in protected
    # Words like "to", "her", "An", "nurse", "man" must NOT have been replaced by placeholders
    assert "to leave" in protected
    assert "her room" in protected
    assert "An old" in protected
    assert "nurse" in protected
    assert "man" in protected


def test_short_terms_case_sensitivity():
    """Verify short terms (len <= 3) are matched strictly case-sensitively."""
    glossary = {"HP": "Sağlık"}
    text = "High HP character with low hp value."
    protected, placeholders = GlossaryManager.protect_terms(text, glossary, xml_mode=False)
    
    # Only uppercase HP should be protected
    assert len(placeholders) == 1
    assert "hp value" in protected


def test_capitalized_proper_nouns_case_sensitivity():
    """Verify capitalized names don't match lowercase common words."""
    glossary = {"Will": "Vasiyet", "Rose": "Gül"}
    text = "Will told me he will leave. Rose saw the water rose."
    protected, placeholders = GlossaryManager.protect_terms(text, glossary, xml_mode=False)
    
    # Only capitalized Will and Rose should be protected (2 placeholders)
    assert len(placeholders) == 2
    assert "he will leave" in protected
    assert "water rose" in protected


def test_turkish_stopwords_collision_prevention():
    """Verify apply_glossary doesn't corrupt Turkish words like 'her' and 'an'."""
    glossary = {"Her": "Her", "An": "An"}
    turkish_text = "Her gün yeni bir an yaşanıyor."
    result = GlossaryManager.apply_glossary(turkish_text, glossary)
    # Must remain completely untouched
    assert result == "Her gün yeni bir an yaşanıyor."


def test_glossary_extractor_stopwords_filter(tmp_path):
    """Verify GlossaryExtractor filters out stopwords and short codes."""
    from src.tools.glossary_extractor.extractor import GlossaryExtractor
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    rpy_file = game_dir / "script.rpy"
    rpy_file.write_text(
        'define to = Character("To")\n'
        'define man = Character("Man")\n'
        'define nurse = Character("Nurse")\n'
        'define alice = Character("Alice")\n',
        encoding="utf-8"
    )
    extractor = GlossaryExtractor()
    extracted = extractor.extract_from_directory(str(tmp_path))
    assert "Alice" in extracted
    assert "To" not in extracted
    assert "Man" not in extracted
    assert "Nurse" not in extracted


def test_protect_terms_avoids_nesting_inside_existing_placeholders():
    """Verify protect_terms does not inject inside already protected <ph> or token spans."""
    from src.core.syntax_guard import protect_renpy_syntax_xml, restore_renpy_syntax_xml
    
    text = "That's right, [Seorin]. Chaemin agrees with Seorin."
    glossary = {"Seorin": "Seorin", "Chaemin": "Chaemin"}
    
    prot_xml, ph_xml = protect_renpy_syntax_xml(text)
    prot_gloss, ph_gloss = GlossaryManager.protect_terms(prot_xml, glossary, xml_mode=True)
    
    # [Seorin] was already protected as <ph id="0">[Seorin]</ph>.
    # Glossary protection must NOT turn it into <ph id="0">[<ph id="G0">Seorin</ph>]</ph>.
    assert '<ph id="0">[Seorin]</ph>' in prot_gloss
    assert '<ph id="0">[<ph' not in prot_gloss
    
    all_ph = {}
    all_ph.update(ph_xml)
    all_ph.update(ph_gloss)
    restored = restore_renpy_syntax_xml(prot_gloss, all_ph)
    assert "</ph>" not in restored
    assert restored == "That's right, [Seorin]. Chaemin agrees with Seorin."


