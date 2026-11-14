"""
Glossary integrity skip ve placeholder injection testleri.

v3.5 düzeltmeleri:
1. validate_translation_integrity glossary tokenlarını atlıyor (_G prefix)
2. inject_missing_placeholders: Google'ın tamamen sildiği tokenları oransal pozisyona enjekte eder
"""

from src.core.syntax_guard import (
    protect_renpy_syntax,
    restore_renpy_syntax,
    validate_translation_integrity,
    inject_missing_placeholders,
)


# ══════════════════════════════════════════════════════════════
# GLOSSARY INTEGRITY SKIP TESTS
# ══════════════════════════════════════════════════════════════

class TestGlossaryIntegritySkip:
    """Glossary placeholder'ları integrity fail tetiklememeli."""

    def test_glossary_token_skipped_by_default(self):
        """_G prefix'li glossary token'ları skip_glossary=True (default) ile atlanmalı."""
        placeholders = {
            "⟦RLPHAAA111_0⟧": "[player]",
            "⟦RLPHAAA111_G0⟧": "Yükle",  # glossary: "Load" → "Yükle"
            "⟦RLPHAAA111_G1⟧": "Kaydet",
        }
        # Translation has [player] but not glossary terms
        text = "Oyunu [player] oynuyor."
        missing = validate_translation_integrity(text, placeholders)
        # Only syntax placeholders should be reported, not glossary
        assert "Yükle" not in missing
        assert "Kaydet" not in missing

    def test_syntax_token_still_detected(self):
        """Syntax placeholder eksikliği tespit edilmeli (glossary skip etkisiz)."""
        placeholders = {
            "⟦RLPHAAA111_0⟧": "[player]",
            "⟦RLPHAAA111_G0⟧": "Yükle",
        }
        text = "Oyunu oynuyor."  # [player] is missing!
        missing = validate_translation_integrity(text, placeholders)
        assert "[player]" in missing
        assert "Yükle" not in missing  # glossary skipped

    def test_skip_glossary_false_includes_glossary(self):
        """skip_glossary=False ile glossary token'ları da kontrol edilmeli."""
        placeholders = {
            "⟦RLPHAAA111_0⟧": "[player]",
            "⟦RLPHAAA111_G0⟧": "Yükle",
        }
        text = "Oyunu [player] oynuyor."
        missing = validate_translation_integrity(text, placeholders, skip_glossary=False)
        assert "[player]" not in missing  # present in text
        assert "Yükle" in missing  # glossary NOT skipped

    def test_glossary_present_in_text_no_issue(self):
        """Glossary değeri metinde varsa zaten sorun yok."""
        placeholders = {
            "⟦RLPHAAA111_G0⟧": "Yükle",
        }
        text = "Dosyayı Yükle butonu."
        missing = validate_translation_integrity(text, placeholders, skip_glossary=False)
        assert missing == []

    def test_mixed_glossary_and_syntax_failures(self):
        """Glossary ve syntax karışık olduğunda sadece syntax raporlanmalı."""
        placeholders = {
            "⟦RLPH000001_0⟧": "[score]",
            "⟦RLPH000001_1⟧": "{b}",
            "⟦RLPH000001_G0⟧": "Puan",
            "⟦RLPH000001_G1⟧": "Seviye",
        }
        text = "Oyuncunun puanı: {b}100"  # [score] missing, {b} present
        missing = validate_translation_integrity(text, placeholders)
        assert "[score]" in missing
        assert "Puan" not in missing
        assert "Seviye" not in missing


# ══════════════════════════════════════════════════════════════
# PLACEHOLDER INJECTION TESTS
# ══════════════════════════════════════════════════════════════

class TestPlaceholderInjection:
    """Google'ın tamamen sildiği token'lar çeviriye enjekte edilebilmeli."""

    def test_single_variable_injection(self):
        """Tek bir değişken kaybı durumunda oransal enjeksiyon."""
        original = "The ship connection to [_return.name] has been severed."
        protected, placeholders = protect_renpy_syntax(original)
        # Google eats token completely
        google_result = "Gemi bağlantısı kesildi."
        restored = restore_renpy_syntax(google_result, placeholders)
        missing = validate_translation_integrity(restored, placeholders)
        assert missing == ["[_return.name]"]

        injected = inject_missing_placeholders(restored, protected, placeholders, missing)
        still_missing = validate_translation_integrity(injected, placeholders)
        assert still_missing == []
        assert "[_return.name]" in injected

    def test_list_literal_injection(self):
        """Python list literal değişken enjeksiyonu."""
        original = "Choose: [18,19,20,22,23,24] for path."
        protected, placeholders = protect_renpy_syntax(original)
        google_result = "Yol icin seciniz."
        restored = restore_renpy_syntax(google_result, placeholders)
        missing = validate_translation_integrity(restored, placeholders)

        injected = inject_missing_placeholders(restored, protected, placeholders, missing)
        assert "[18,19,20,22,23,24]" in injected

    def test_multiple_variables_injection(self):
        """Birden fazla değişken kaybında hepsi enjekte edilmeli."""
        original = "Player [name] scored [score] points!"
        protected, placeholders = protect_renpy_syntax(original)
        google_result = "Oyuncu puan aldi!"
        restored = restore_renpy_syntax(google_result, placeholders)
        missing = validate_translation_integrity(restored, placeholders)
        assert len(missing) == 2

        injected = inject_missing_placeholders(restored, protected, placeholders, missing)
        assert "[name]" in injected
        assert "[score]" in injected

    def test_no_injection_when_nothing_missing(self):
        """Eksik yoksa metin değişmemeli."""
        original = "Hello world"
        protected, placeholders = protect_renpy_syntax(original)
        result = inject_missing_placeholders("Merhaba dünya", protected, placeholders, [])
        assert result == "Merhaba dünya"

    def test_injection_preserves_word_boundaries(self):
        """Enjeksiyon kelime sınırlarına saygı göstermeli — kelime ortasına bölmemeli."""
        original = "Options [21,22] available."
        protected, placeholders = protect_renpy_syntax(original)
        google_result = "Seçenekler mevcut."
        restored = restore_renpy_syntax(google_result, placeholders)
        missing = validate_translation_integrity(restored, placeholders)

        injected = inject_missing_placeholders(restored, protected, placeholders, missing)
        assert "[21,22]" in injected
        # Must not split any word in the middle
        for word in ["Seçenekler", "mevcut."]:
            # Each original word should appear intact (not broken)
            assert word in injected or word.rstrip('.') in injected

    def test_injection_short_text_no_space(self):
        """Boşluksuz kısa metinde kelime bölünmemeli — metin kenarına snap."""
        original = "Use [21,22]."
        protected, placeholders = protect_renpy_syntax(original)
        google_result = "Kullan."
        restored = restore_renpy_syntax(google_result, placeholders)
        missing = validate_translation_integrity(restored, placeholders)

        injected = inject_missing_placeholders(restored, protected, placeholders, missing)
        assert "[21,22]" in injected
        # "Kullan." must NOT be split
        assert "Kullan." in injected

    def test_injection_with_tags(self):
        """Tag placeholders da enjekte edilebilmeli."""
        original = "Text {color=#ff0}here{/color} more."
        protected, placeholders = protect_renpy_syntax(original)
        # Find what was protected as token
        syntax_missing = [v for v in placeholders.values() 
                         if isinstance(v, str) and not v.startswith("__")]
        if syntax_missing:
            google_result = "Metin burada daha fazla."
            restored = restore_renpy_syntax(google_result, placeholders)
            missing = validate_translation_integrity(restored, placeholders)
            if missing:
                injected = inject_missing_placeholders(restored, protected, placeholders, missing)
                # All missing values should now be in text
                for m in missing:
                    assert m in injected

    def test_unbalanced_bracket_not_injected(self):
        """UNBALANCED_BRACKET_END pseudo-entry atlanmalı."""
        result = inject_missing_placeholders(
            "test metin", "test ⟦RLPH000_0⟧", 
            {"⟦RLPH000_0⟧": "[var]"}, 
            ["UNBALANCED_BRACKET_END"]
        )
        assert "UNBALANCED_BRACKET" not in result

    def test_empty_inputs(self):
        """Boş girdiler hata vermemeli."""
        assert inject_missing_placeholders("", "", {}, []) == ""
        assert inject_missing_placeholders("text", "", {}, ["[var]"]) == "text"
        assert inject_missing_placeholders("", "protected", {"k": "v"}, ["v"]) == ""
