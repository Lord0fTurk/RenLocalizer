# -*- coding: utf-8 -*-
"""
Enhanced tests for previously weak/shallow test areas.

Strengthens:
  - test_cache_clear_persistence.py (was 1 test, now 6)
  - test_translation_id.py (was 1 test, now 7)
  - test_edgecases.py (was 2 tests, now 10)
  - test_google_html_mode_guard.py (was 1 test, now 4)
  - test_exporter.py (was 2 tests, now 6)
"""

import json
from pathlib import Path
from types import SimpleNamespace



# ============================================================================
# 1. Enhanced Cache Clear Persistence Tests
# ============================================================================

class TestCacheClearPersistence:
    """Extended tests for translation cache save/clear/reload cycle."""

    def test_save_empty_cache_writes_empty_json(self, tmp_path: Path):
        from src.core.translator import TranslationManager
        cache_file = tmp_path / "translation_cache.json"
        manager = TranslationManager()
        manager.save_cache(str(cache_file))
        written = json.loads(cache_file.read_text(encoding="utf-8"))
        assert written == {}

    def test_clear_then_save_overwrites_previous_entries(self, tmp_path: Path):
        from src.core.translator import TranslationManager, TranslationResult, TranslationEngine
        cache_file = tmp_path / "translation_cache.json"
        manager = TranslationManager()

        # Add entries and save
        manager._cache[("google", "auto", "tr", "Hello")] = TranslationResult(
            original_text="Hello", translated_text="Merhaba",
            source_lang="auto", target_lang="tr",
            engine=TranslationEngine.GOOGLE, success=True,
        )
        manager.save_cache(str(cache_file))

        first_save = json.loads(cache_file.read_text(encoding="utf-8"))
        assert len(first_save) > 0

        # Clear and save again
        manager._cache.clear()
        manager.save_cache(str(cache_file))

        second_save = json.loads(cache_file.read_text(encoding="utf-8"))
        assert second_save == {}

    def test_multiple_engines_in_cache(self, tmp_path: Path):
        from src.core.translator import TranslationManager, TranslationResult, TranslationEngine
        cache_file = tmp_path / "translation_cache.json"
        manager = TranslationManager()

        for engine in (TranslationEngine.GOOGLE, TranslationEngine.DEEPL):
            manager._cache[(engine.value, "auto", "tr", "Test")] = TranslationResult(
                original_text="Test", translated_text="Deneme",
                source_lang="auto", target_lang="tr",
                engine=engine, success=True,
            )
        manager.save_cache(str(cache_file))

        written = json.loads(cache_file.read_text(encoding="utf-8"))
        assert len(written) >= 2

    def test_unicode_text_in_cache_persists(self, tmp_path: Path):
        from src.core.translator import TranslationManager, TranslationResult, TranslationEngine
        cache_file = tmp_path / "translation_cache.json"
        manager = TranslationManager()

        manager._cache[("google", "auto", "tr", "日本語テスト")] = TranslationResult(
            original_text="日本語テスト", translated_text="Japonca Test",
            source_lang="ja", target_lang="tr",
            engine=TranslationEngine.GOOGLE, success=True,
        )
        manager.save_cache(str(cache_file))

        # Reload and verify
        content = cache_file.read_text(encoding="utf-8")
        assert "日本語テスト" in content or "Japonca Test" in content

    def test_save_to_nonexistent_directory_creates_parent(self, tmp_path: Path):
        from src.core.translator import TranslationManager
        cache_file = tmp_path / "subdir" / "deep" / "cache.json"
        assert not cache_file.parent.exists()
        manager = TranslationManager()
        manager.save_cache(str(cache_file))
        assert cache_file.exists()


# ============================================================================
# 2. Enhanced Translation ID Tests
# ============================================================================

class TestTranslationIdEnhanced:
    """Extended translation ID computation and roundtrip tests."""

    def test_basic_roundtrip(self, tmp_path: Path):
        from src.core.tl_parser import TLParser
        tl_content = 'translate turkish strings:\n    old "Hello"\n    new ""\n'
        tl_file = tmp_path / "strings.rpy"
        tl_file.write_text(tl_content, encoding="utf-8")

        parser = TLParser()
        parsed = parser.parse_file(str(tl_file))
        assert parsed
        entry = parsed.entries[0]
        tid = entry.compute_id()
        updated = parser.update_translations(parsed, {tid: "Merhaba"})
        assert 'new "Merhaba"' in updated

    def test_unicode_text_id_computation(self, tmp_path: Path):
        from src.core.tl_parser import TLParser
        tl_content = 'translate turkish strings:\n    old "日本語テスト"\n    new ""\n'
        tl_file = tmp_path / "strings.rpy"
        tl_file.write_text(tl_content, encoding="utf-8")

        parser = TLParser()
        parsed = parser.parse_file(str(tl_file))
        assert parsed
        entry = parsed.entries[0]
        tid = entry.compute_id()
        assert tid  # ID should be computed, not empty

    def test_empty_string_id(self, tmp_path: Path):
        from src.core.tl_parser import TLParser
        tl_content = 'translate turkish strings:\n    old ""\n    new ""\n'
        tl_file = tmp_path / "strings.rpy"
        tl_file.write_text(tl_content, encoding="utf-8")

        parser = TLParser()
        parsed = parser.parse_file(str(tl_file))
        # Empty old string might be skipped or parsed differently
        # The important thing is no crash
        assert isinstance(parsed.entries, list)

    def test_long_text_id_stability(self, tmp_path: Path):
        from src.core.tl_parser import TLParser
        long_text = "A" * 5000
        tl_content = f'translate turkish strings:\n    old "{long_text}"\n    new ""\n'
        tl_file = tmp_path / "strings.rpy"
        tl_file.write_text(tl_content, encoding="utf-8")

        parser = TLParser()
        parsed = parser.parse_file(str(tl_file))
        if parsed and parsed.entries:
            entry = parsed.entries[0]
            tid = entry.compute_id()
            assert tid  # Should produce a valid ID

    def test_same_text_same_id(self, tmp_path: Path):
        """Same file, line and text should always produce the same deterministic translation ID."""
        from src.core.tl_parser import TLParser
        parser = TLParser()

        tl_file = tmp_path / "strings.rpy"
        tl_file.write_text(
            'translate turkish strings:\n    old "Consistent"\n    new ""\n',
            encoding="utf-8"
        )
        parsed1 = parser.parse_file(str(tl_file))
        parsed2 = parser.parse_file(str(tl_file))
        assert parsed1 is not None and len(parsed1.entries) > 0
        assert parsed2 is not None and len(parsed2.entries) > 0

        id1 = parsed1.entries[0].compute_id()
        id2 = parsed2.entries[0].compute_id()
        assert id1 == id2

        # Different file paths must produce different IDs to avoid cross-file collisions
        other_file = tmp_path / "other_strings.rpy"
        other_file.write_text(
            'translate turkish strings:\n    old "Consistent"\n    new ""\n',
            encoding="utf-8"
        )
        parsed_other = parser.parse_file(str(other_file))
        assert parsed_other is not None and len(parsed_other.entries) > 0
        assert parsed_other.entries[0].compute_id() != id1

    def test_special_chars_in_text(self, tmp_path: Path):
        """Quotes, backslashes, and Ren'Py tags should not break ID computation."""
        from src.core.tl_parser import TLParser
        texts = [
            'Hello "World"',
            "It's a test",
            "{b}Bold{/b} text",
            "Line1\\nLine2",
        ]
        parser = TLParser()
        for idx, text in enumerate(texts):
            tl_file = tmp_path / f"test_{idx}.rpy"
            escaped = text.replace('\\', '\\\\').replace('"', '\\"')
            tl_file.write_text(
                f'translate turkish strings:\n    old "{escaped}"\n    new ""\n',
                encoding="utf-8"
            )
            parsed = parser.parse_file(str(tl_file))
            assert parsed is not None, f"Failed to parse file for text: {text}"
            assert len(parsed.entries) >= 1, f"No entries extracted for text: {text}"
            entry = parsed.entries[0]
            tid = entry.compute_id()
            assert tid is not None and len(tid) > 0


# ============================================================================
# 3. Enhanced Syntax Guard Edge Cases
# ============================================================================

class TestSyntaxGuardEdgeCases:
    """Extended edge case tests for protect/restore round-trip."""

    def test_nested_tags(self):
        from src.core.syntax_guard import protect_renpy_syntax, restore_renpy_syntax
        text = "{color=#fff}{b}Hello{/b}{/color}"
        protected, placeholders = protect_renpy_syntax(text)
        restored = restore_renpy_syntax(protected, placeholders)
        assert restored == text

    def test_empty_format_placeholder(self):
        from src.core.syntax_guard import protect_renpy_syntax, restore_renpy_syntax
        text = "Score: {} / {}"
        protected, placeholders = protect_renpy_syntax(text)
        restored = restore_renpy_syntax(protected, placeholders)
        assert restored == text

    def test_escape_sequences(self):
        from src.core.syntax_guard import protect_renpy_syntax, restore_renpy_syntax
        text = 'He said \\"Hello\\" and left\\n'
        protected, placeholders = protect_renpy_syntax(text)
        restored = restore_renpy_syntax(protected, placeholders)
        assert restored == text

    def test_mixed_brackets_and_tags(self):
        from src.core.syntax_guard import protect_renpy_syntax, restore_renpy_syntax
        text = "[player_name] has {color=#f00}[score]{/color} points"
        protected, placeholders = protect_renpy_syntax(text)
        for key in placeholders.keys():
            assert key in protected
        restored = restore_renpy_syntax(protected, placeholders)
        assert restored == text

    def test_very_long_text(self):
        from src.core.syntax_guard import protect_renpy_syntax, restore_renpy_syntax
        text = ("A long dialogue with [player] and {b}bold{/b} text. " * 100).strip()
        protected, placeholders = protect_renpy_syntax(text)
        restored = restore_renpy_syntax(protected, placeholders)
        assert restored == text

    def test_only_tags_no_visible_text(self):
        from src.core.syntax_guard import protect_renpy_syntax, restore_renpy_syntax
        text = "{p}{w}{nw}"
        protected, placeholders = protect_renpy_syntax(text)
        restored = restore_renpy_syntax(protected, placeholders)
        assert restored == text

    def test_percentage_format_specifiers(self):
        from src.core.syntax_guard import protect_renpy_syntax, restore_renpy_syntax
        text = "%(name)s has %(count)d items"
        protected, placeholders = protect_renpy_syntax(text)
        restored = restore_renpy_syntax(protected, placeholders)
        assert restored == text

    def test_dot_format_specifiers(self):
        from src.core.syntax_guard import protect_renpy_syntax, restore_renpy_syntax
        text = "{0} has {1} items and {name} score"
        protected, placeholders = protect_renpy_syntax(text)
        restored = restore_renpy_syntax(protected, placeholders)
        assert restored == text


# ============================================================================
# 4. Enhanced Google HTML Mode Guard Tests
# ============================================================================

class TestGoogleHtmlModeGuard:
    """Extended HTML protection mode behavior tests."""

    def test_web_endpoints_disable_html(self):
        from src.core.translator import GoogleTranslator
        cfg = SimpleNamespace(
            translation_settings=SimpleNamespace(
                use_multi_endpoint=True,
                enable_lingva_fallback=True,
                max_concurrent_threads=4,
                max_chars_per_request=1000,
                max_batch_size=50,
                aggressive_retry_translation=False,
                use_html_protection=True,
                request_delay=0.1,
            )
        )
        translator = GoogleTranslator(config_manager=cfg)
        assert translator.use_html_protection is False

    def test_no_config_defaults_to_no_html(self):
        from src.core.translator import GoogleTranslator
        translator = GoogleTranslator(config_manager=None)
        assert translator.use_html_protection is False

    def test_html_protection_flag_respected_when_false(self):
        from src.core.translator import GoogleTranslator
        cfg = SimpleNamespace(
            translation_settings=SimpleNamespace(
                use_multi_endpoint=True,
                enable_lingva_fallback=True,
                max_concurrent_threads=4,
                max_chars_per_request=1000,
                max_batch_size=50,
                aggressive_retry_translation=False,
                use_html_protection=False,
                request_delay=0.1,
            )
        )
        translator = GoogleTranslator(config_manager=cfg)
        assert translator.use_html_protection is False


# ============================================================================
# 5. Enhanced Exporter Tests
# ============================================================================

class TestExporterEnhanced:
    """Extended exporter path resolution and edge case tests."""

    @staticmethod
    def _prepare_tl_dir(tmp_path: Path):
        project_dir = tmp_path / "project"
        game_dir = project_dir / "game"
        tl_dir = game_dir / "tl" / "turkish"
        tl_dir.mkdir(parents=True)
        return project_dir, tl_dir

    def test_empty_strings_json_produces_no_output(self, tmp_path: Path):
        from src.core.exporter import export_strings_to_rpy
        project_dir, tl_dir = self._prepare_tl_dir(tmp_path)
        (tl_dir / "strings.json").write_text("{}", encoding="utf-8")

        export_strings_to_rpy(str(project_dir), "turkish")
        # With no translations, either returns True with empty file or False
        exported_path = tl_dir / "zz_rl_exported_turkish.rpy"
        if exported_path.exists():
            content = exported_path.read_text(encoding="utf-8")
            # Should not contain any old/new pairs
            assert 'old "' not in content or len(content) < 200  # Just header

    def test_unicode_translations_exported_correctly(self, tmp_path: Path):
        from src.core.exporter import export_strings_to_rpy
        project_dir, tl_dir = self._prepare_tl_dir(tmp_path)
        (tl_dir / "strings.json").write_text(
            json.dumps({"Hello": "Merhaba", "日本語": "Japonca"}, ensure_ascii=False),
            encoding="utf-8"
        )

        result = export_strings_to_rpy(str(project_dir), "turkish")
        assert result is True

    def test_large_strings_json_does_not_crash(self, tmp_path: Path):
        from src.core.exporter import export_strings_to_rpy
        project_dir, tl_dir = self._prepare_tl_dir(tmp_path)

        # 1000 entries
        data = {f"Source text {i}": f"Çeviri metni {i}" for i in range(1000)}
        (tl_dir / "strings.json").write_text(
            json.dumps(data, ensure_ascii=False),
            encoding="utf-8"
        )

        result = export_strings_to_rpy(str(project_dir), "turkish")
        assert result is True


# ============================================================================
# 6. Enhanced Preprotected Request Tests
# ============================================================================

class TestPreprotectedRequests:
    """Extended preprotected request handling tests."""

    def test_glossary_placeholders_preserved(self):
        from src.core.translator import GoogleTranslator, TranslationEngine, TranslationRequest
        translator = GoogleTranslator(config_manager=None)
        placeholders = {
            "⟦RLPHABC123_0⟧": "[player]",
            "⟦RLPHDEF456_G0⟧": "Mary",  # Glossary placeholder
        }
        req = TranslationRequest(
            text="Merhaba ⟦RLPHABC123_0⟧ ve ⟦RLPHDEF456_G0⟧",
            source_lang="en", target_lang="tr",
            engine=TranslationEngine.GOOGLE,
            metadata={
                "preprotected": True,
                "placeholders": placeholders,
                "original_text": "Merhaba [player] ve Mary",
            },
        )
        protected_text, prepared_placeholders, use_html = translator._prepare_request_protection(req)
        assert protected_text == req.text
        assert prepared_placeholders is placeholders

    def test_empty_metadata_non_preprotected(self):
        from src.core.translator import GoogleTranslator, TranslationEngine, TranslationRequest
        translator = GoogleTranslator(config_manager=None)
        req = TranslationRequest(
            text="Simple text",
            source_lang="en", target_lang="tr",
            engine=TranslationEngine.GOOGLE,
            metadata={},
        )
        protected_text, placeholders, use_html = translator._prepare_request_protection(req)
        # Simple text without Ren'Py syntax — should pass through unchanged
        # or with minimal protection
        assert isinstance(placeholders, dict)

    def test_preprotected_with_no_placeholders(self):
        from src.core.translator import GoogleTranslator, TranslationEngine, TranslationRequest
        translator = GoogleTranslator(config_manager=None)
        req = TranslationRequest(
            text="Plain text no syntax",
            source_lang="en", target_lang="tr",
            engine=TranslationEngine.GOOGLE,
            metadata={
                "preprotected": True,
                "placeholders": {},
                "original_text": "Plain text no syntax",
            },
        )
        protected_text, prepared_placeholders, use_html = translator._prepare_request_protection(req)
        assert protected_text == "Plain text no syntax"
        assert prepared_placeholders == {}
