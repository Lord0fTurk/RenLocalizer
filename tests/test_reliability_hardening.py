# -*- coding: utf-8 -*-

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from src.core.parser import RenPyParser
from src.core.tl_parser import TranslationEntry, TranslationFile
from src.core.translation_pipeline import PipelineResult, PipelineStage, TranslationPipeline
from src.core.translator import TranslationEngine, TranslationRequest, TranslationResult
from src.utils.config import get_effective_batch_size, get_engine_batch_size_cap


class DummyTranslationManager:
    def __init__(self, translators=None) -> None:
        self.translators = translators or {}


class DummyTranslator:
    def __init__(self, responses: dict[tuple[str, bool], str], fallback=None) -> None:
        self.responses = responses
        self.calls: list[bool] = []
        self.aggressive_retry = False
        self._fallback = fallback

    async def translate_single(self, request: TranslationRequest) -> TranslationResult:
        original_text = request.metadata.get("original_text", request.text)
        self.calls.append(bool(self.aggressive_retry))
        translated = self.responses.get((original_text, bool(self.aggressive_retry)), original_text)
        return TranslationResult(
            original_text=original_text,
            translated_text=translated,
            source_lang=request.source_lang,
            target_lang=request.target_lang,
            engine=request.engine,
            success=True,
            metadata=request.metadata,
        )


def _make_config(**overrides) -> SimpleNamespace:
    translation_settings = SimpleNamespace(
        aggressive_retry_translation=False,
        enable_delimiter_aware_translation=True,
        auto_generate_hook=True,
        enable_runtime_hook=True,
        enable_rpyc_reader=False,
    )
    for key, value in overrides.items():
        setattr(translation_settings, key, value)
    return SimpleNamespace(
        translation_settings=translation_settings,
        glossary={},
        get_log_text=lambda key, default=None, **kwargs: (default or key).format(**kwargs) if kwargs else (default or key),
        get_ui_text=lambda key, default=None, **kwargs: (default or key).format(**kwargs) if kwargs else (default or key),
    )


def _make_pipeline(translators=None, **config_overrides) -> TranslationPipeline:
    return TranslationPipeline(_make_config(**config_overrides), DummyTranslationManager(translators))


def test_parser_extracts_core_ui_translatable_strings(tmp_path: Path) -> None:
    content = """
screen quick_menu():
    textbutton _("Auto")
    textbutton _("Q.Save")
    textbutton _("Q.Load")
    textbutton _("Main Menu")
    textbutton _("End Replay")
    textbutton _("Unseen Text")
"""
    test_file = tmp_path / "quick_menu.rpy"
    test_file.write_text(content, encoding="utf-8")

    parser = RenPyParser()
    texts = {entry["text"] for entry in parser.extract_text_entries(test_file)}

    assert {"Auto", "Q.Save", "Q.Load", "Main Menu", "End Replay", "Unseen Text"}.issubset(texts)
    assert parser.is_meaningful_text("auto") is False
    assert parser.is_meaningful_text("module.attr") is False


def test_parser_extracts_menu_context_hotkeys_from_dynamic_lists(tmp_path: Path) -> None:
    content = """
label bridge_menu:
    $ _context["menu"] = {
        "0": ["Stats/s", "_cond_stats", "option"],
        "1": ["Favour/f", "_cond_favours", "submenu", {
            "0": ["Bridge Favour/b", "_cond_favour_bridge", "option"],
        }],
        "2": ["Chat/c", "True", "option"],
        "3": ["Exit/x", "True", "exit"],
    }
"""
    test_file = tmp_path / "dynamic_menu.rpy"
    test_file.write_text(content, encoding="utf-8")

    parser = RenPyParser()
    texts = {entry["text"] for entry in parser.extract_text_entries(test_file)}

    assert {"Stats/s", "Favour/f", "Bridge Favour/b", "Chat/c", "Exit/x"}.issubset(texts)
    assert "_cond_stats" not in texts
    assert "option" not in texts
    assert "submenu" not in texts


def test_pipeline_corruption_guard_blocks_placeholder_remnants() -> None:
    pipeline = _make_pipeline()

    sanitized, reason = pipeline._sanitize_translation_for_output(
        original="Load",
        translated="RLRLPH8544C3 G0⟧",
        file_path="screens.rpy",
        translation_id="load_1",
        line_number=42,
    )

    assert sanitized == "Load"
    assert reason == "placeholder_remnant"
    assert pipeline.diagnostic_report.total_blocked_as_corrupted == 1


def test_engine_specific_batch_size_caps() -> None:
    assert get_engine_batch_size_cap("google") == 1000
    assert get_engine_batch_size_cap("libretranslate") is None
    assert get_effective_batch_size(100, "google") == 100
    assert get_effective_batch_size(5000, "google") == 1000
    assert get_effective_batch_size(5000, "libretranslate") == 5000


def test_pipeline_effective_batch_size_caps_google_only() -> None:
    google_pipeline = _make_pipeline()
    google_pipeline.engine = TranslationEngine.GOOGLE
    google_pipeline.config.translation_settings.max_batch_size = 5000
    assert google_pipeline._get_requested_translation_batch_size() == 5000
    assert google_pipeline._get_effective_translation_batch_size() == 1000

    libre_pipeline = _make_pipeline()
    libre_pipeline.engine = TranslationEngine.LIBRETRANSLATE
    libre_pipeline.config.translation_settings.max_batch_size = 5000
    assert libre_pipeline._get_effective_translation_batch_size() == 5000


def test_pipeline_logs_batch_cap_notice_for_google() -> None:
    pipeline = _make_pipeline()
    pipeline.engine = TranslationEngine.GOOGLE
    events: list[tuple[str, str]] = []
    pipeline.log_message.connect(lambda level, message: events.append((level, message)))

    pipeline._emit_batch_size_cap_notice_if_needed(5000, 1000)

    assert events
    assert events[0][0] == "info"
    assert "1000" in events[0][1]


def test_coverage_warning_summary_logs_without_popup() -> None:
    pipeline = _make_pipeline()
    logs: list[tuple[str, str]] = []
    popups: list[tuple[str, str]] = []
    pipeline.log_message.connect(lambda level, message: logs.append((level, message)))
    pipeline.show_warning.connect(lambda title, message: popups.append((title, message)))
    pipeline.diagnostic_report.add_coverage_warning("image_only_ui", 2)
    pipeline._last_diagnostic_path = "diag.json"

    pipeline._emit_coverage_warning_summary()

    assert popups == []
    assert any(level == "warning" for level, _ in logs)
    assert any("diag.json" in message for _, message in logs)


def test_app_backend_completion_summary_includes_review_notes() -> None:
    return  # Old AppBackend deleted
    from src.backend.app_backend import AppBackend

    fake_backend = SimpleNamespace(
        config=SimpleNamespace(
            get_ui_text=lambda key, default=None, **kwargs: (default or key).format(**kwargs) if kwargs else (default or key),
        ),
        pipeline=SimpleNamespace(
            diagnostic_report=SimpleNamespace(coverage_warnings=[{"code": "image_only_ui"}, {"code": "dynamic_ui_runtime"}]),
            _last_diagnostic_path="diag.json",
        ),
    )
    result = PipelineResult(
        success=True,
        message="12 texts translated, 3 files saved",
        stage=PipelineStage.COMPLETED,
        output_path="out_dir",
    )

    payload = AppBackend._build_completion_summary(fake_backend, result)

    assert payload["title"] == "Translation Complete"
    assert payload["output_path"] == "out_dir"
    assert payload["diagnostic_path"] == "diag.json"
    assert payload["review_note_count"] == 2
    assert "12 texts translated" in payload["message"]


def test_guard_reason_text_is_human_readable() -> None:
    pipeline = _make_pipeline()

    assert pipeline._get_guard_reason_text("length_inflation") == "translated text expanded far beyond the source"
    assert pipeline._get_guard_reason_text("placeholder_set_mismatch") == "placeholder structure changed"


def test_guard_reason_text_uses_localized_locale_entry() -> None:
    translations = {
        "guard_reason_length_inflation": "ceviri metni kaynaga gore asiri uzadi",
    }
    config = SimpleNamespace(
        translation_settings=SimpleNamespace(
            aggressive_retry_translation=False,
            enable_delimiter_aware_translation=True,
            auto_generate_hook=True,
            enable_runtime_hook=True,
            enable_rpyc_reader=False,
        ),
        glossary={},
        get_log_text=lambda key, default=None, **kwargs: translations.get(key, default or key),
        get_ui_text=lambda key, default=None, **kwargs: default or key,
    )
    pipeline = TranslationPipeline(config, DummyTranslationManager())

    assert pipeline._get_guard_reason_text("length_inflation") == "ceviri metni kaynaga gore asiri uzadi"


def test_hotkey_visible_variants_are_synthesized() -> None:
    pipeline = _make_pipeline()

    assert pipeline._classify_translation_corruption("Stats/s", "İstatistikler [S]") is None

    additions = pipeline._synthesize_hotkey_visible_variants(
        {
            "Stats/s": "İstatistikler/s",
            "Exit/x": "Çıkış/x",
        }
    )

    assert additions["Stats [S]"] == "İstatistikler [S]"
    assert additions["Exit [X]"] == "Çıkış [X]"


def test_generate_strings_json_skips_corrupt_entries_and_adds_hotkey_variants(tmp_path: Path) -> None:
    pipeline = _make_pipeline()
    lang_dir = tmp_path / "tl" / "turkish"
    lang_dir.mkdir(parents=True)

    tl_file = TranslationFile(
        file_path=str(lang_dir / "screens.rpy"),
        language="turkish",
        entries=[
            TranslationEntry(
                original_text="Stats/s",
                translated_text="İstatistikler/s",
                file_path=str(lang_dir / "screens.rpy"),
                line_number=10,
                entry_type="string",
            ),
            TranslationEntry(
                original_text="Load",
                translated_text="RLRLPH8544C3 G0⟧",
                file_path=str(lang_dir / "screens.rpy"),
                line_number=11,
                entry_type="string",
            ),
            TranslationEntry(
                original_text="id_deadbeefcafebabe",
                translated_text="Should Not Leak",
                file_path=str(lang_dir / "zz_rl_exported_turkish.rpy"),
                line_number=12,
                entry_type="string",
            ),
        ],
    )

    pipeline._generate_strings_json(
        [tl_file],
        str(lang_dir),
        extra_translations={"id_deadbeefcafebabe": "Should Still Not Leak"},
    )

    mapping = json.loads((lang_dir / "strings.json").read_text(encoding="utf-8"))
    mapping = mapping["translations"] if isinstance(mapping, dict) and "translations" in mapping else mapping
    skipped = json.loads(
        (lang_dir / "diagnostics" / "strings_json_skipped_corruptions.json").read_text(encoding="utf-8")
    )

    assert mapping["Stats/s"] == "İstatistikler/s"
    assert mapping["Stats [S]"] == "İstatistikler [S]"
    assert "Load" not in mapping
    assert "id_deadbeefcafebabe" not in mapping
    assert skipped["reason_counts"]["placeholder_remnant"] == 1


def test_generate_strings_json_adds_plain_alias_for_angle_wrapped_strings(tmp_path: Path) -> None:
    pipeline = _make_pipeline()
    lang_dir = tmp_path / "tl" / "turkish"
    lang_dir.mkdir(parents=True)

    tl_file = TranslationFile(
        file_path=str(lang_dir / "dialogue.rpy"),
        language="turkish",
        entries=[
            TranslationEntry(
                original_text="<At the Valkoran Academy I once posed for development of a new Spacesuit.>",
                translated_text="Valkoran Akademisi'nde yeni bir uzay kıyafeti geliştirilmesi için bir zamanlar poz vermiştim.>",
                file_path=str(lang_dir / "dialogue.rpy"),
                line_number=18,
                entry_type="dialogue",
            )
        ],
    )

    pipeline._generate_strings_json([tl_file], str(lang_dir))

    mapping = json.loads((lang_dir / "strings.json").read_text(encoding="utf-8"))
    mapping = mapping["translations"] if isinstance(mapping, dict) and "translations" in mapping else mapping
    plain_key = "At the Valkoran Academy I once posed for development of a new Spacesuit."
    assert mapping[plain_key] == "Valkoran Akademisi'nde yeni bir uzay kıyafeti geliştirilmesi için bir zamanlar poz vermiştim."


def test_visible_text_variants_are_synthesized() -> None:
    pipeline = _make_pipeline()

    additions = pipeline._synthesize_visible_text_variants(
        {
            "I won't say goodbye...": "Vedalaşmayacağım...",
            "Wait - not yet": "Bekle - henüz değil",
        }
    )

    assert additions["I won’t say goodbye..."] == "Vedalaşmayacağım..."
    assert additions["I won't say goodbye…"] == "Vedalaşmayacağım..."
    assert additions["Wait – not yet"] == "Bekle - henüz değil"


def test_generate_strings_json_adds_visible_text_aliases(tmp_path: Path) -> None:
    pipeline = _make_pipeline()
    lang_dir = tmp_path / "tl" / "turkish"
    lang_dir.mkdir(parents=True)

    tl_file = TranslationFile(
        file_path=str(lang_dir / "dialogue.rpy"),
        language="turkish",
        entries=[
            TranslationEntry(
                original_text="I won't say goodbye...",
                translated_text="Vedalaşmayacağım...",
                file_path=str(lang_dir / "dialogue.rpy"),
                line_number=21,
                entry_type="dialogue",
            )
        ],
    )

    pipeline._generate_strings_json([tl_file], str(lang_dir))

    mapping = json.loads((lang_dir / "strings.json").read_text(encoding="utf-8"))
    mapping = mapping["translations"] if isinstance(mapping, dict) and "translations" in mapping else mapping
    assert mapping["I won't say goodbye..."] == "Vedalaşmayacağım..."
    assert mapping["I won’t say goodbye..."] == "Vedalaşmayacağım..."
    assert mapping["I won't say goodbye…"] == "Vedalaşmayacağım..."


def test_visible_fragment_variants_are_synthesized() -> None:
    pipeline = _make_pipeline()

    additions = pipeline._synthesize_visible_fragment_variants(
        {
            "The continuation of this story is being created right now. So I won't say goodbye. And if you want to know what happened next, you can find out elsewhere.": "Bu hikayenin devamı şu anda hazırlanıyor. Bu yüzden vedalaşmayacağım. Sonra ne olduğunu başka bir yerde öğrenebilirsiniz.",
        }
    )

    key = "The continuation of this story is being created right now. So I won't say goodbye."
    and_key = "And the continuation of this story is being created right now. So I won't say goodbye."
    assert additions[key] == "Bu hikayenin devamı şu anda hazırlanıyor. Bu yüzden vedalaşmayacağım."
    assert additions[and_key] == "Bu hikayenin devamı şu anda hazırlanıyor. Bu yüzden vedalaşmayacağım."


def test_generate_strings_json_adds_visible_fragment_aliases(tmp_path: Path) -> None:
    pipeline = _make_pipeline()
    lang_dir = tmp_path / "tl" / "turkish"
    lang_dir.mkdir(parents=True)

    tl_file = TranslationFile(
        file_path=str(lang_dir / "dialogue.rpy"),
        language="turkish",
        entries=[
            TranslationEntry(
                original_text="The continuation of this story is being created right now. So I won't say goodbye. And if you want to know what happened next, you can find out elsewhere.",
                translated_text="Bu hikayenin devamı şu anda hazırlanıyor. Bu yüzden vedalaşmayacağım. Sonra ne olduğunu başka bir yerde öğrenebilirsiniz.",
                file_path=str(lang_dir / "dialogue.rpy"),
                line_number=33,
                entry_type="dialogue",
            )
        ],
    )

    pipeline._generate_strings_json([tl_file], str(lang_dir))

    mapping = json.loads((lang_dir / "strings.json").read_text(encoding="utf-8"))
    mapping = mapping["translations"] if isinstance(mapping, dict) and "translations" in mapping else mapping
    mapping = mapping["translations"] if isinstance(mapping, dict) and "translations" in mapping else mapping
    key = "The continuation of this story is being created right now. So I won't say goodbye."
    and_key = "And the continuation of this story is being created right now. So I won't say goodbye."
    assert mapping[key] == "Bu hikayenin devamı şu anda hazırlanıyor. Bu yüzden vedalaşmayacağım."
    assert mapping[and_key] == "Bu hikayenin devamı şu anda hazırlanıyor. Bu yüzden vedalaşmayacağım."


def test_runtime_observed_variants_are_synthesized_from_miss_log(tmp_path: Path) -> None:
    pipeline = _make_pipeline()
    lang_dir = tmp_path / "tl" / "turkish"
    diag_dir = lang_dir / "diagnostics"
    diag_dir.mkdir(parents=True)

    runtime_log = diag_dir / "runtime_missed_strings.jsonl"
    runtime_log.write_text(
        json.dumps(
            {
                "reason": "screen_bypass_miss",
                "source_kind": "dialogue",
                "text": "And the continuation of this story is being created right now. So I won't say goodbye.",
                "stripped": "And the continuation of this story is being created right now. So I won't say goodbye.",
                "length": 85,
                "word_count": 14,
                "sentence_count": 2,
                "alnum_count": 67,
            }
        ),
        encoding="utf-8",
    )

    additions = pipeline._synthesize_runtime_observed_variants(
        {
            "The continuation of this story is being created right now. So I won't say goodbye.": "Bu hikayenin devamı şu anda hazırlanıyor. Bu yüzden vedalaşmayacağım.",
        },
        str(lang_dir),
    )

    assert additions["And the continuation of this story is being created right now. So I won't say goodbye."] == "And Bu hikayenin devamı şu anda hazırlanıyor. Bu yüzden vedalaşmayacağım."


def test_generate_strings_json_adds_runtime_observed_aliases(tmp_path: Path) -> None:
    pipeline = _make_pipeline()
    lang_dir = tmp_path / "tl" / "turkish"
    diag_dir = lang_dir / "diagnostics"
    diag_dir.mkdir(parents=True)

    runtime_log = diag_dir / "runtime_missed_strings.jsonl"
    runtime_log.write_text(
        json.dumps(
            {
                "reason": "screen_bypass_miss",
                "source_kind": "dialogue",
                "text": "And the continuation of this story is being created right now. So I won't say goodbye.",
                "stripped": "And the continuation of this story is being created right now. So I won't say goodbye.",
                "length": 85,
                "word_count": 14,
                "sentence_count": 2,
                "alnum_count": 67,
            }
        ),
        encoding="utf-8",
    )

    tl_file = TranslationFile(
        file_path=str(lang_dir / "dialogue.rpy"),
        language="turkish",
        entries=[
            TranslationEntry(
                original_text="The continuation of this story is being created right now. So I won't say goodbye.",
                translated_text="Bu hikayenin devamı şu anda hazırlanıyor. Bu yüzden vedalaşmayacağım.",
                file_path=str(lang_dir / "dialogue.rpy"),
                line_number=41,
                entry_type="dialogue",
            )
        ],
    )

    pipeline._generate_strings_json([tl_file], str(lang_dir))

    mapping = json.loads((lang_dir / "strings.json").read_text(encoding="utf-8"))
    mapping = mapping["translations"] if isinstance(mapping, dict) and "translations" in mapping else mapping
    observed_key = "And the continuation of this story is being created right now. So I won't say goodbye."
    assert mapping[observed_key] == "And Bu hikayenin devamı şu anda hazırlanıyor. Bu yüzden vedalaşmayacağım."


def test_runtime_observed_review_candidates_wait_for_aggressive_mode(tmp_path: Path) -> None:
    lang_dir = tmp_path / "tl" / "turkish"
    diag_dir = lang_dir / "diagnostics"
    diag_dir.mkdir(parents=True)

    runtime_log = diag_dir / "runtime_missed_strings.jsonl"
    runtime_log.write_text(
        json.dumps(
            {
                "reason": "screen_scope_observed",
                "source_kind": "screen_scope",
                "text": "And the story continues here in a visible form.",
                "stripped": "And the story continues here in a visible form.",
                "length": 46,
                "word_count": 9,
                "sentence_count": 1,
                "alnum_count": 36,
            }
        ),
        encoding="utf-8",
    )

    source_mapping = {
        "The story continues here in a visible form.": "Hikaye burada gorunur bir bicimde devam ediyor.",
    }

    balanced_pipeline = _make_pipeline(extraction_mode="balanced")
    aggressive_pipeline = _make_pipeline(extraction_mode="aggressive")

    balanced_additions = balanced_pipeline._synthesize_runtime_observed_variants(source_mapping, str(lang_dir))
    aggressive_additions = aggressive_pipeline._synthesize_runtime_observed_variants(source_mapping, str(lang_dir))

    observed_key = "And the story continues here in a visible form."
    assert observed_key not in balanced_additions
    assert aggressive_additions[observed_key] == "And Hikaye burada gorunur bir bicimde devam ediyor."


def test_aggressive_mode_relaxes_visible_fragment_thresholds() -> None:
    source = "The story continues here in a visible form. And more details arrive later."
    target = "Hikaye burada gorunur bir bicimde devam ediyor. Ve daha sonra daha fazla ayrinti geliyor."

    balanced_pipeline = _make_pipeline(extraction_mode="balanced")
    aggressive_pipeline = _make_pipeline(extraction_mode="aggressive")

    balanced_additions = balanced_pipeline._synthesize_visible_fragment_variants({source: target})
    aggressive_additions = aggressive_pipeline._synthesize_visible_fragment_variants({source: target})

    key = "The story continues here in a visible form."
    assert key not in balanced_additions
    assert aggressive_additions[key] == "Hikaye burada gorunur bir bicimde devam ediyor."


def test_generated_export_file_is_detected() -> None:
    pipeline = _make_pipeline()

    assert pipeline._is_generated_export_file("game/tl/turkish/zz_rl_exported_turkish.rpy") is True
    assert pipeline._is_generated_export_file("game/tl/turkish/screens.rpy") is False


def test_image_only_ui_warning_detects_unlabeled_buttons(tmp_path: Path) -> None:
    pipeline = _make_pipeline()
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    (game_dir / "screens.rpy").write_text(
        """
screen confirm_exit():
    imagebutton:
        auto \"gui/quit_%s.png\"
        action Return(True)
""",
        encoding="utf-8",
    )

    warning = pipeline._audit_image_only_ui(str(game_dir))

    assert warning is not None
    assert warning["code"] == "image_only_ui"
    assert warning["count"] == 1


def test_image_only_ui_warning_skips_helper_buttons_with_labels(tmp_path: Path) -> None:
    pipeline = _make_pipeline()
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    (game_dir / "locations.rpy").write_text(
        """
screen navigation():
    imagebutton:
        idle build_loc_icon(\"pool_icon.png\", \"Pool\", overlay)
        action Return(True)
""",
        encoding="utf-8",
    )

    warning = pipeline._audit_image_only_ui(str(game_dir))

    assert warning is None


def test_compiled_only_warning_detects_missing_source_scripts(tmp_path: Path) -> None:
    pipeline = _make_pipeline(enable_rpyc_reader=False)
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    (game_dir / "chapter1.rpyc").write_bytes(b"RPYC")

    warning = pipeline._audit_compiled_only_scripts(str(game_dir))

    assert warning is not None
    assert warning["code"] == "compiled_only_scripts"
    assert warning["count"] == 1


def test_dynamic_ui_warning_only_when_runtime_hook_disabled(tmp_path: Path) -> None:
    pipeline = _make_pipeline(auto_generate_hook=False, enable_runtime_hook=False)
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    (game_dir / "minigame.rpy").write_text(
        'screen score_overlay():\n    text "Score: {}".format(score)\n',
        encoding="utf-8",
    )

    warning = pipeline._audit_dynamic_ui_runtime(str(game_dir))

    assert warning is not None
    assert warning["code"] == "dynamic_ui_runtime"
    assert warning["count"] == 1


def test_runtime_hook_enablement_requires_master_and_auto_flags() -> None:
    pipeline = _make_pipeline(auto_generate_hook=True, enable_runtime_hook=True)
    assert pipeline._is_runtime_hook_enabled() is True

    pipeline = _make_pipeline(auto_generate_hook=False, enable_runtime_hook=True)
    assert pipeline._is_runtime_hook_enabled() is False

    pipeline = _make_pipeline(auto_generate_hook=True, enable_runtime_hook=False)
    assert pipeline._is_runtime_hook_enabled() is False

    pipeline = _make_pipeline(auto_generate_hook=False, enable_runtime_hook=False, force_runtime_translation=True)
    assert pipeline._is_runtime_hook_enabled() is True


def test_dynamic_ui_warning_skipped_when_runtime_hook_enabled(tmp_path: Path) -> None:
    pipeline = _make_pipeline(auto_generate_hook=True, enable_runtime_hook=True)
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    (game_dir / "minigame.rpy").write_text(
        'screen score_overlay():\n    text "Score: {}".format(score)\n',
        encoding="utf-8",
    )

    warning = pipeline._audit_dynamic_ui_runtime(str(game_dir))

    assert warning is None


def test_diagnostic_report_serializes_coverage_warnings() -> None:
    pipeline = _make_pipeline()
    pipeline.diagnostic_report.add_coverage_warning(
        "image_only_ui",
        2,
        samples=[{"file_path": "screens.rpy", "line_number": 12}],
    )

    payload = pipeline.diagnostic_report.to_dict()

    assert payload["totals"]["coverage_warning_count"] == 1
    assert payload["coverage_warnings"][0]["code"] == "image_only_ui"


def test_core_ui_retry_recovers_unchanged_translation() -> None:
    translator = DummyTranslator(
        {
            ("Save", True): "Kaydet",
        }
    )
    pipeline = _make_pipeline({TranslationEngine.GOOGLE: translator})
    request = TranslationRequest(
        text="Save",
        source_lang="en",
        target_lang="tr",
        engine=TranslationEngine.GOOGLE,
        metadata={"preprotected": True, "original_text": "Save", "placeholders": {}},
    )
    entry = TranslationEntry(
        original_text="Save",
        translated_text="",
        file_path="screens.rpy",
        line_number=12,
        entry_type="string",
    )

    loop = asyncio.new_event_loop()
    try:
        recovered_text, recovered = pipeline._retry_unchanged_core_ui(loop, request, entry, "Save")
    finally:
        loop.close()

    assert recovered is True
    assert recovered_text == "Kaydet"
    assert translator.calls == [True]


def test_core_ui_retry_uses_fallback_translator_when_primary_stays_unchanged() -> None:
    fallback = DummyTranslator({("About", True): "Hakkında"})
    translator = DummyTranslator({}, fallback=fallback)
    pipeline = _make_pipeline({TranslationEngine.DEEPL: translator})
    request = TranslationRequest(
        text="About",
        source_lang="en",
        target_lang="tr",
        engine=TranslationEngine.DEEPL,
        metadata={"preprotected": True, "original_text": "About", "placeholders": {}},
    )
    entry = TranslationEntry(
        original_text="About",
        translated_text="",
        file_path="screens.rpy",
        line_number=13,
        entry_type="string",
    )

    loop = asyncio.new_event_loop()
    try:
        recovered_text, recovered = pipeline._retry_unchanged_core_ui(loop, request, entry, "About")
    finally:
        loop.close()

    assert recovered is True
    assert recovered_text == "Hakkında"
    assert translator.calls == [True]
    assert fallback.calls == [True]


def test_core_ui_retry_is_not_used_for_non_core_labels() -> None:
    translator = DummyTranslator({("Bridge Favour", True): "Köprü İtibarı"})
    pipeline = _make_pipeline({TranslationEngine.GOOGLE: translator})
    request = TranslationRequest(
        text="Bridge Favour",
        source_lang="en",
        target_lang="tr",
        engine=TranslationEngine.GOOGLE,
        metadata={"preprotected": True, "original_text": "Bridge Favour", "placeholders": {}},
    )
    entry = TranslationEntry(
        original_text="Bridge Favour",
        translated_text="",
        file_path="screens.rpy",
        line_number=14,
        entry_type="string",
    )

    loop = asyncio.new_event_loop()
    try:
        recovered_text, recovered = pipeline._retry_unchanged_core_ui(loop, request, entry, "Bridge Favour")
    finally:
        loop.close()

    assert recovered is False
    assert recovered_text == "Bridge Favour"
    assert translator.calls == []


def test_reopen_stale_tl_entries_requeues_corruption_and_core_ui_but_not_proper_nouns() -> None:
    pipeline = _make_pipeline()
    tl_file = TranslationFile(
        file_path="game/tl/turkish/screens.rpy",
        language="turkish",
        entries=[
            TranslationEntry(
                original_text="Load",
                translated_text="RLRLPH8544C3 G0âŸ§",
                file_path="game/tl/turkish/screens.rpy",
                line_number=10,
                entry_type="string",
            ),
            TranslationEntry(
                original_text="About",
                translated_text="About",
                file_path="game/tl/turkish/screens.rpy",
                line_number=11,
                entry_type="string",
            ),
            TranslationEntry(
                original_text="Tenaris",
                translated_text="Tenaris",
                file_path="game/tl/turkish/screens.rpy",
                line_number=12,
                entry_type="string",
            ),
        ],
    )

    counts = pipeline._reopen_stale_tl_entries([tl_file])

    assert counts == {"reopened": 2, "corrupted": 1, "unchanged_core_ui": 1}
    assert tl_file.entries[0].translated_text == ""
    assert tl_file.entries[1].translated_text == ""
    assert tl_file.entries[2].translated_text == "Tenaris"
