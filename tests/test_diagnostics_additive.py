# -*- coding: utf-8 -*-
"""
Tests for v2.8.17 additive diagnostic report enhancements:
  - Backward compatibility of all existing totals and file report keys
  - total_normalized_wrapper and file-level normalized_wrapper counts
  - provenance tracking (engine, model, extra kwargs)
  - unchanged_reasons frequency mapping
  - alias_kinds tracking for synthesized variants
"""

from src.core.diagnostics import DiagnosticReport


class TestDiagnosticsAdditiveFields:
    def test_backward_compatibility_keys_preserved(self):
        report = DiagnosticReport(project="TestProject", target_language="turkish")
        report.add_extracted("game/script.rpy", {"text": "Hello", "line_number": 10})
        report.mark_translated("game/script.rpy", "id_1", "Merhaba", original_text="Hello")
        report.mark_written("game/script.rpy", "id_1")
        report.mark_skipped("game/script.rpy", "some_reason")
        report.mark_unchanged("game/script.rpy", "id_2", original_text="Save", reason="unchanged_core_ui")
        report.mark_blocked("game/script.rpy", "id_3", "html_leakage", original_text="Hi", translated_text="<br>")
        report.mark_recovered("game/script.rpy", "id_4", "retry", original_text="Back", translated_text="Geri")
        report.mark_recovered("game/script.rpy", "id_5", "synthesized_variant", original_text="Next [N]", translated_text="Sonraki [N]")

        d = report.to_dict()

        # All existing legacy keys MUST be present in totals
        expected_legacy_keys = [
            'extracted', 'translated', 'written', 'skipped',
            'unchanged', 'unchanged_by_engine', 'blocked_as_corrupted',
            'recovered_by_retry', 'recovered_by_synthesized_variant',
            'coverage_warning_count'
        ]
        for key in expected_legacy_keys:
            assert key in d['totals'], f"Legacy totals key {key!r} missing!"

        assert d['totals']['extracted'] == 1
        assert d['totals']['translated'] == 1
        assert d['totals']['written'] == 1
        assert d['totals']['skipped'] == 1
        assert d['totals']['unchanged'] == 1
        assert d['totals']['unchanged_by_engine'] == 1
        assert d['totals']['blocked_as_corrupted'] == 1
        assert d['totals']['recovered_by_retry'] == 1
        assert d['totals']['recovered_by_synthesized_variant'] == 1

    def test_additive_normalized_wrapper_and_provenance(self):
        report = DiagnosticReport(project="TestProject", target_language="turkish")
        report.set_provenance(engine="google", model="", stage="translating", worker_count=4)

        report.mark_normalized_wrapper(
            "game/screens.rpy",
            "id_norm_1",
            original_text="Look at that!",
            translated_text="{color=#ff0000}Buna bak!{/color}",
            normalized_text="Buna bak!",
        )

        d = report.to_dict()

        assert d['totals']['normalized_wrapper'] == 1
        assert d['provenance']['engine'] == "google"
        assert d['provenance']['stage'] == "translating"
        assert d['provenance']['worker_count'] == 4

        fr = d['files']['game/screens.rpy']
        assert fr['normalized_wrapper'] == 1
        assert any(
            e.get('status') == 'normalized' and e.get('reason') == 'outer_color_wrapper'
            for e in fr['entries']
        )

    def test_additive_unchanged_reasons_and_alias_kinds(self):
        report = DiagnosticReport(project="TestProject", target_language="turkish")
        report.mark_unchanged("game/script.rpy", "id_1", original_text="Save", reason="unchanged_core_ui")
        report.mark_unchanged("game/script.rpy", "id_2", original_text="She strokes your cock.", reason="unchanged_sentence")
        report.mark_unchanged("game/script.rpy", "id_3", original_text="Eileen", reason="unchanged_other")

        report.record_alias_kind("hotkey", 5)
        report.record_alias_kind("angle_wrapper", 3)
        report.record_alias_kind("hotkey", 2)

        d = report.to_dict()

        assert d['unchanged_reasons'] == {
            'unchanged_core_ui': 1,
            'unchanged_sentence': 1,
            'unchanged_other': 1,
        }
        assert d['totals']['unchanged_by_engine'] == 2  # unchanged_core_ui + unchanged_sentence
        assert d['alias_kinds'] == {
            'hotkey': 7,
            'angle_wrapper': 3,
        }
