# -*- coding: utf-8 -*-
"""
Tests for v2.8.13 printf-style format specifier protection and the
post-translation symmetry guard.

Covers:
  - PRINTF_SPEC_RE: flags, width, precision, keyed specs, all conversions
  - Natural language containing '%' is NEVER treated as a specifier
  - Parser preserve_placeholders(): broad specs get ⟦F…⟧ protection
  - classify_translation_corruption(): dropped/mutated specs are rejected
  - Literal '%%' escapes stay untouched
"""

import pytest

from src.core.pipeline.constants import PRINTF_SPEC_RE
from src.core.pipeline.translating import classify_translation_corruption
from src.core.parser import RenPyParser


@pytest.fixture
def parser():
    return RenPyParser(config_manager=None)


# ==================================================================
# 1. PRINTF_SPEC_RE PATTERN COVERAGE
# ==================================================================
class TestPrintfPattern:
    @pytest.mark.parametrize("spec", [
        "%s", "%d", "%i", "%f", "%x", "%o", "%u", "%e", "%g", "%c", "%r",
        "%-5d", "%+d", "%#x", "%05d",
        "%6.2f", "%-10.4e", "%.3f",
        "%(name)s", "%(count)03d", "%(hp)-5d", "%(val)6.2f",
        "%ld", "%hd", "%Lf",
    ])
    def test_real_specs_matched(self, spec):
        text = f"Value: {spec} left"
        found = PRINTF_SPEC_RE.findall(text)
        assert spec in found, f"Expected {spec!r} to match in {text!r}, got {found}"

    @pytest.mark.parametrize("text", [
        "I am 100% sure about this.",
        "The battery is at 50% right now.",
        "Give it 110% effort!",
        "She won 3% of the time.",
        "No percent signs here.",
    ])
    def test_natural_language_not_matched(self, text):
        assert PRINTF_SPEC_RE.findall(text) == [], (
            f"Natural language must not yield specifiers: {text!r} "
            f"-> {PRINTF_SPEC_RE.findall(text)}"
        )

    def test_literal_percent_escape_not_matched(self):
        # '%%' is a literal-percent escape, not a substitution
        assert PRINTF_SPEC_RE.findall("100%% complete") == []


# ==================================================================
# 2. PARSER PROTECTION (preserve_placeholders)
# ==================================================================
class TestParserProtection:
    def test_broad_spec_gets_placeholder(self, parser):
        text = "You won %-5d coins."
        processed, mapping = parser.preserve_placeholders(text)
        assert "%-5d" not in processed
        assert "%-5d" in mapping.values()
        assert "⟦F" in processed

    def test_keyed_spec_gets_placeholder(self, parser):
        text = "Load %(count)03d slots."
        processed, mapping = parser.preserve_placeholders(text)
        assert "%(count)03d" not in processed
        assert "%(count)03d" in mapping.values()

    def test_roundtrip_restores_spec(self, parser):
        text = "HP: %(hp)-5d / MP: %d"
        processed, mapping = parser.preserve_placeholders(text)
        restored = parser.restore_placeholders(processed, mapping)
        assert restored == text

    def test_natural_percent_stays_readable(self, parser):
        text = "I am 100% sure."
        processed, mapping = parser.preserve_placeholders(text)
        assert processed == text
        assert not any(v.startswith("%") for v in mapping.values())


# ==================================================================
# 3. POST-TRANSLATION SYMMETRY GUARD
# ==================================================================
class TestPrintfGuard:
    def test_intact_spec_passes(self):
        assert classify_translation_corruption(
            "You won %-5d coins.", "Kazandığın: %-5d altın."
        ) is None

    def test_dropped_spec_rejected(self):
        reason = classify_translation_corruption(
            "You won %-5d coins.", "Kazandın: altın."
        )
        assert reason == "printf_set_mismatch"

    def test_mutated_spec_rejected(self):
        reason = classify_translation_corruption(
            "Load %(count)03d slots.", "%(count)s yuva yükleniyor."
        )
        assert reason == "printf_set_mismatch"

    def test_added_spec_rejected(self):
        reason = classify_translation_corruption(
            "One item found.", "Bir %d eşya bulundu."
        )
        assert reason == "printf_set_mismatch"

    def test_natural_percent_both_sides_passes(self):
        assert classify_translation_corruption(
            "I am 100% sure.", "Yüzde yüz eminim."
        ) is None

    def test_spec_survives_with_tags_and_vars(self):
        assert classify_translation_corruption(
            "{b}[name]{/b} has %d items.",
            "{b}[name]{/b} karakterinin %d eşyası var."
        ) is None

    def test_guard_skipped_when_tokens_present(self):
        # When the original still carries ⟦…⟧ tokens the comparison is
        # skipped (same contract as the renpy_tag_set_mismatch branch).
        assert classify_translation_corruption(
            "Won ⟦F000⟧ coins.", "Kazanıldı."
        ) != "printf_set_mismatch"


# ==================================================================
# 4. GUARD REASON TEXT MAPPING
# ==================================================================
class TestReasonText:
    def test_reason_key_mapped(self):
        from src.core.pipeline.translating import get_guard_reason_text

        class Cfg:
            def get_log_text(self, key, default):
                return key

        assert get_guard_reason_text("printf_set_mismatch", Cfg()) == (
            "guard_reason_printf_set_mismatch"
        )

    def test_locale_keys_exist(self):
        import json
        import os
        root = os.path.join(os.path.dirname(__file__), "..", "locales")
        for lang in ("en", "tr", "de", "es", "fr", "ru", "fa", "zh-CN", "ja"):
            with open(os.path.join(root, f"{lang}.json"), encoding="utf-8") as f:
                data = json.load(f)
            assert "guard_reason_printf_set_mismatch" in data, f"missing in {lang}"
