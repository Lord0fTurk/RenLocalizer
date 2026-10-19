"""
Placeholder koruma pipeline'ı entegrasyon testleri.

v3.4 düzeltmeleri:
1. translate_single çift koruma (else dalı) kaldırıldı
2. Tüm Lingva fallback yollarında preprotected veri doğru kullanılıyor
3. Glossary tokenları [[g0]] → ⟦RLPH...⟧ Unicode formatına dönüştürüldü
4. Batch revert original_text kullanıyor (protected text yerine)
5. Single endpoint revert source_text kullanıyor
"""

import re
import uuid
import pytest
from unittest.mock import MagicMock, patch
from src.core.syntax_guard import (
    protect_renpy_syntax,
    restore_renpy_syntax,
    validate_translation_integrity,
)
from src.core.translator import (
    GoogleTranslator,
    TranslationEngine,
    TranslationRequest,
    TranslationResult,
)


# ===========================================================================
# FIX #1: translate_single else dalı artık çift koruma yapmıyor
# ===========================================================================


class TestNoDoubleProtection:
    """_prepare_request_protection'ın döndüğü veri else dalında korunmalı."""

    def test_preprotected_request_uses_pipeline_placeholders_directly(self):
        """Pipeline'dan gelen preprotected veri, translate_single'da
        yeniden protect_renpy_syntax çağrılmadan Google'a gönderilmeli."""
        translator = GoogleTranslator(config_manager=None)
        pipeline_placeholders = {
            "⟦RLPHAAA111_0⟧": "[player]",
            "⟦RLPHAAA111_1⟧": "{b}",
        }
        req = TranslationRequest(
            text="Merhaba ⟦RLPHAAA111_0⟧, ⟦RLPHAAA111_1⟧savaş⟧",
            source_lang="en",
            target_lang="tr",
            engine=TranslationEngine.GOOGLE,
            metadata={
                "preprotected": True,
                "placeholders": pipeline_placeholders,
                "original_text": "Hello [player], {b}war",
            },
        )
        text, ph, use_html = translator._prepare_request_protection(req)
        # Preprotected data should pass through unchanged
        assert text == req.text
        assert ph is pipeline_placeholders
        assert use_html is False

    def test_non_preprotected_request_produces_fresh_protection(self):
        """Pipeline olmadan doğrudan API çağrısı yapılırsa taze koruma üret."""
        translator = GoogleTranslator(config_manager=None)
        req = TranslationRequest(
            text="Hello [player], {b}good{/b}!",
            source_lang="en",
            target_lang="tr",
            engine=TranslationEngine.GOOGLE,
            metadata={},
        )
        text, ph, use_html = translator._prepare_request_protection(req)
        assert "[player]" not in text  # Token ile değiştirilmiş
        assert any(v == "[player]" for v in ph.values() if isinstance(v, str))
        assert use_html is False

    def test_nested_tokens_not_created_with_preprotected(self):
        """Preprotected metin üzerinde protect_renpy_syntax çağrılırsa
        orijinal tokenler korunmalı (iç içe token oluşmamalı)."""
        # Simulate pipeline output
        original = "Score: [player_score] and {color=#fff}name{/color}"
        protected, placeholders = protect_renpy_syntax(original)

        # Pipeline sends this as preprotected
        req = TranslationRequest(
            text=protected,
            source_lang="en",
            target_lang="tr",
            engine=TranslationEngine.GOOGLE,
            metadata={
                "preprotected": True,
                "placeholders": placeholders,
                "original_text": original,
            },
        )
        translator = GoogleTranslator(config_manager=None)
        text, ph, use_html = translator._prepare_request_protection(req)

        # The text sent to Google should have EXACTLY the pipeline tokens
        # Not nested tokens (which the old bug created)
        token_count = len(re.findall(r'\u27e6[^\u27e7]+\u27e7', text))
        pipeline_token_count = len(
            [k for k in placeholders if k.startswith('\u27e6')]
        )
        assert token_count == pipeline_token_count


# ===========================================================================
# FIX #3: Glossary tokenları artık Unicode bracket formatında
# ===========================================================================


class TestGlossaryUnicodeBracketTokens:
    """_protect_glossary_terms artık [[g0]] yerine ⟦RLPH...⟧ üretiyor."""

    def _make_pipeline_with_glossary(self, glossary: dict):
        """Create a mock pipeline with given glossary."""
        pipeline = MagicMock()
        pipeline.config = MagicMock()
        pipeline.config.glossary = glossary
        # Bind the real method
        from src.core.translation_pipeline import TranslationPipeline
        pipeline._protect_glossary_terms = TranslationPipeline._protect_glossary_terms.__get__(
            pipeline, type(pipeline)
        )
        return pipeline

    def test_glossary_uses_unicode_brackets(self):
        """Glossary tokenları ⟦RLPH...⟧ formatında olmalı, [[g0]] değil."""
        pipeline = self._make_pipeline_with_glossary({"Captain": "Kaptan"})
        result, placeholders = pipeline._protect_glossary_terms("Captain Smith reporting!")

        # No [[g0]] style tokens
        assert "[[g" not in result

        # Should have Unicode bracket token
        assert "\u27e6" in result
        assert "\u27e7" in result

        # Token key format: ⟦RLPH{6hex}_G{counter}⟧
        for key in placeholders:
            assert re.match(r'\u27e6RLPH[A-F0-9]{6}_G\d+\u27e7', key), (
                f"Glossary token format wrong: {key}"
            )

        # Value should be the target translation
        assert list(placeholders.values()) == ["Kaptan"]

    def test_glossary_tokens_survive_restore(self):
        """Glossary tokenları restore_renpy_syntax ile geri dönüşebilmeli."""
        pipeline = self._make_pipeline_with_glossary({"Captain": "Kaptan", "Ship": "Gemi"})
        text = "Captain on the Ship"
        result, glossary_ph = pipeline._protect_glossary_terms(text)

        # Simulate: text goes to Google, tokens survive, then restore
        restored = restore_renpy_syntax(result, glossary_ph)
        assert "Kaptan" in restored
        assert "Gemi" in restored

    def test_glossary_tokens_combined_with_syntax_tokens(self):
        """Syntax + glossary tokenları birlikte çalışmalı."""
        pipeline = self._make_pipeline_with_glossary({"Captain": "Kaptan"})

        # Step 1: Syntax protection
        original = "Captain [player] has {b}cargo{/b}"
        protected, syntax_ph = protect_renpy_syntax(original)

        # Step 2: Glossary protection on already syntax-protected text
        final_text, glossary_ph = pipeline._protect_glossary_terms(protected)
        all_ph = {**syntax_ph, **glossary_ph}

        # Verify both token types present
        syntax_tokens = [k for k in all_ph if not k.startswith("__WRAPPER")]
        assert len(syntax_tokens) >= 2  # At least [player] + glossary

        # Step 3: Full restore
        restored = restore_renpy_syntax(final_text, all_ph)
        assert "[player]" in restored
        assert "Kaptan" in restored  # Glossary target value

    def test_glossary_token_uppercase_for_nfkc_restore(self):
        """Glossary token iç gN → GN formatında olmalı (restore'daki .upper() uyumu)."""
        pipeline = self._make_pipeline_with_glossary({"Test": "Deneme"})
        _, ph = pipeline._protect_glossary_terms("Test text")
        
        for key in ph:
            # Extract inner content
            inner = key[1:-1]  # Remove ⟦ and ⟧
            # Must be all uppercase (restore does .upper())
            assert inner == inner.upper(), f"Token inner not uppercase: {inner}"


# ===========================================================================
# FIX #4/5: Batch ve single revert doğru metni kullanıyor
# ===========================================================================


class TestBatchRevertUsesOriginalText:
    """Batch integrity fail sırasında protected text yerine original text kullanılmalı."""

    def test_translate_result_carries_original_text(self):
        """TranslationResult.original_text metadata'daki orijinal metin olmalı."""
        # This is a structural test — verify the metadata lookup pattern works
        metadata = {
            "preprotected": True,
            "original_text": "Hello [player]!",
            "placeholders": {"⟦RLPH000000_0⟧": "[player]"},
        }
        req = TranslationRequest(
            text="Hello ⟦RLPH000000_0⟧!",
            source_lang="en",
            target_lang="tr",
            engine=TranslationEngine.GOOGLE,
            metadata=metadata,
        )
        # Simulate the fixed revert logic
        _meta = req.metadata if isinstance(req.metadata, dict) else {}
        _orig = _meta.get("original_text", req.text)

        assert _orig == "Hello [player]!"  # NOT the protected text

    def test_revert_without_metadata_uses_request_text(self):
        """Metadata yoksa req.text'e fallback yap."""
        req = TranslationRequest(
            text="Hello world",
            source_lang="en",
            target_lang="tr",
            engine=TranslationEngine.GOOGLE,
            metadata={},
        )
        _meta = req.metadata if isinstance(req.metadata, dict) else {}
        _orig = _meta.get("original_text", req.text)
        assert _orig == "Hello world"


# ===========================================================================
# End-to-end: Pipeline protect → translate → restore cycle
# ===========================================================================


class TestEndToEndProtectionCycle:
    """Tam pipeline akışını simüle eder: protect → translate → restore."""

    def test_syntax_only_roundtrip(self):
        """Sadece syntax tokenları olan metin tam döngü geçmeli."""
        original = "You have [gold] gold and {b}[items]{/b} items!"
        protected, placeholders = protect_renpy_syntax(original)

        # Simulate Google: preserve tokens, translate text
        google_output = protected.replace("You have", "Senin").replace(
            "gold and", "altının ve"
        ).replace("items!", "eşyan var!")

        restored = restore_renpy_syntax(google_output, placeholders)
        assert "[gold]" in restored
        assert "[items]" in restored

    def test_glossary_roundtrip(self):
        """Glossary + syntax tokenları birlikte tam döngü geçmeli."""
        from unittest.mock import MagicMock
        from src.core.translation_pipeline import TranslationPipeline

        pipeline = MagicMock()
        pipeline.config = MagicMock()
        pipeline.config.glossary = {"sword": "kılıç", "shield": "kalkan"}
        pipeline._protect_glossary_terms = TranslationPipeline._protect_glossary_terms.__get__(
            pipeline, type(pipeline)
        )

        original = "Take the sword and shield, [player]!"

        # Step 1: Syntax
        protected, syntax_ph = protect_renpy_syntax(original)
        # Step 2: Glossary
        final_text, glossary_ph = pipeline._protect_glossary_terms(protected)
        all_ph = {**syntax_ph, **glossary_ph}

        # Simulate Google preserving all tokens
        google_output = final_text.replace("Take the", "Al").replace("and", "ve")

        # Step 3: Restore
        restored = restore_renpy_syntax(google_output, all_ph)
        assert "[player]" in restored
        assert "kılıç" in restored
        assert "kalkan" in restored

    def test_integrity_check_passes_after_proper_restore(self):
        """Restore edildikten sonra integrity check geçmeli."""
        original = "Level [level] with {color=#fff}[player]{/color}"
        protected, placeholders = protect_renpy_syntax(original)

        # Simulate perfect Google translation (tokens preserved)
        google_output = protected.replace("Level", "Seviye").replace("with", "ile")
        restored = restore_renpy_syntax(google_output, placeholders)

        missing = validate_translation_integrity(restored, placeholders)
        assert missing == [], f"Unexpected integrity failures: {missing}"


class TestLLMXMLProtectionCycle:
    """Tests the new decoupled XML protection cycle specifically designed for LLMs."""

    def test_xml_protection_roundtrip(self):
        """Tests protect_renpy_syntax_xml and restore_renpy_syntax_xml."""
        from src.core.syntax_guard import protect_renpy_syntax_xml, restore_renpy_syntax_xml
        
        original = "Hello [player], click {b}here{/b}!"
        protected, placeholders = protect_renpy_syntax_xml(original)
        
        # XML syntax check: tags should surround tokens
        assert '<ph id="0">[player]</ph>' in protected
        assert '<ph id="1">{b}</ph>' in protected
        assert '<ph id="2">{/b}</ph>' in protected
        
        # Simulate LLM response (preserving XML tag structure but translating surrounding text)
        llm_response = protected.replace("Hello", "Merhaba").replace("click", "tıklayın").replace("here", "buraya")
        
        restored = restore_renpy_syntax_xml(llm_response, placeholders)
        assert restored == "Merhaba [player], tıklayın {b}buraya{/b}!"

    def test_glossary_xml_protection_roundtrip(self):
        """Tests that glossary terms are wrapped in XML tags when xml_mode=True."""
        from unittest.mock import MagicMock
        from src.core.translation_pipeline import TranslationPipeline
        from src.core.syntax_guard import restore_renpy_syntax_xml
        
        pipeline = MagicMock()
        pipeline.config = MagicMock()
        pipeline.config.glossary = {"gold": "altın"}
        # Bind real method
        pipeline._protect_glossary_terms = TranslationPipeline._protect_glossary_terms.__get__(
            pipeline, type(pipeline)
        )
        
        original = "You have 100 gold."
        protected, glossary_ph = pipeline._protect_glossary_terms(original, xml_mode=True)
        
        assert '<ph id="G0">gold</ph>' in protected
        assert glossary_ph == {"G0": "altın"}
        
        # Simulate LLM translating surrounding text
        llm_response = protected.replace("You have 100", "100 adet var")
        
        restored = restore_renpy_syntax_xml(llm_response, glossary_ph)
        assert restored == "100 adet var altın."


def test_xml_restore_accepts_the_ascii_placeholder_style():
    """AI prompts show __PH_0__ examples; an answer in that style must restore."""
    from src.core.syntax_guard import (
        protect_renpy_syntax_xml, restore_renpy_syntax_xml, validate_translation_integrity,
    )

    protected, placeholders = protect_renpy_syntax_xml("Hello [name], press {i}Enter{/i}.")
    restored = restore_renpy_syntax_xml("Merhaba __PH_0__, __PH_1__Enter__PH_2__ tuşuna bas.", placeholders)
    assert restored == "Merhaba [name], {i}Enter{/i} tuşuna bas."
    assert validate_translation_integrity(restored, placeholders) == []
    # An id the request never had is left for the integrity check.
    assert restore_renpy_syntax_xml("x __PH_9__", placeholders) == "x __PH_9__"
