# -*- coding: utf-8 -*-
"""
Tests for clean tl/<lang>/ output, Native TLID strings.json omission,
isolated diagnostics relocation, and AI batch size defaults (v2.8.17).
"""
import os
from pathlib import Path
from unittest.mock import MagicMock


from src.utils.config import ConfigManager, TranslationSettings
from src.core.pipeline.saving import (
    generate_strings_json,
    get_diagnostics_dir,
    write_translation_reports,
)
from src.core.pipeline.extraction import reopen_stale_tl_entries
from src.core.pipeline.translating import get_requested_translation_batch_size
from src.core.translator import TranslationEngine
from src.core.tl_parser import TranslationFile, TranslationEntry
from src.core.diagnostics import DiagnosticReport


def test_ai_batch_size_defaults():
    """Verify default AI batch size is 15 in config and translating helper."""
    settings = TranslationSettings()
    assert settings.ai_batch_size == 15

    cfg = MagicMock()
    cfg.translation_settings = settings
    assert get_requested_translation_batch_size(TranslationEngine.OPENAI, cfg) == 15
    assert get_requested_translation_batch_size(TranslationEngine.LOCAL_LLM, cfg) == 15


def test_get_diagnostics_dir_isolation(tmp_path: Path):
    """Verify diagnostics path is placed in tl/.diagnostics/<lang>/ outside tl/<lang>/."""
    game_dir = tmp_path / "game"
    tl_dir = game_dir / "tl"
    lang_dir = tl_dir / "turkish"
    lang_dir.mkdir(parents=True)

    diag_dir = get_diagnostics_dir(str(lang_dir), "turkish")
    expected = os.path.join(str(tl_dir), ".diagnostics", "turkish")
    assert os.path.normpath(diag_dir) == os.path.normpath(expected)
    assert os.path.isdir(diag_dir)


def test_write_translation_reports_cleans_legacy_diagnostics(tmp_path: Path):
    """Verify write_translation_reports writes to .diagnostics and removes legacy tl/<lang>/diagnostics."""
    game_dir = tmp_path / "game"
    tl_dir = game_dir / "tl"
    lang_dir = tl_dir / "turkish"
    legacy_diag = lang_dir / "diagnostics"
    legacy_diag.mkdir(parents=True)
    (legacy_diag / "old_report.json").write_text("{}", encoding="utf-8")

    report = DiagnosticReport(project="TestVN", target_language="turkish")
    cfg = MagicMock()
    cfg.get_log_text = lambda k, **kw: kw.get("path", "")

    written_path = write_translation_reports(
        lang_dir=str(lang_dir),
        target_language="turkish",
        diagnostic_report=report,
        translation_guard_counts={},
        translation_guard_events=[],
        translation_guard_sample_limit=10,
        log_emit=MagicMock(),
        config=cfg,
    )

    # Must be written inside tl/.diagnostics/turkish/
    assert ".diagnostics" in written_path
    assert os.path.exists(written_path)

    # Legacy directory inside tl/turkish/ must be cleaned up
    assert not legacy_diag.exists(), "Legacy diagnostics dir inside tl/turkish/ must be removed"


def test_generate_strings_json_skipped_in_native_mode(tmp_path: Path):
    """In native output mode, strings.json is never created and stale strings.json is removed."""
    lang_dir = tmp_path / "game" / "tl" / "turkish"
    lang_dir.mkdir(parents=True)
    stale_json = lang_dir / "strings.json"
    stale_json.write_text('{"translations": {"stale": "eski"}}', encoding="utf-8")

    cfg = MagicMock()
    cfg.translation_settings = MagicMock()
    cfg.translation_settings.output_mode = "native"
    cfg.get_log_text = lambda k, def_val=None, **kw: def_val or k

    # Mock entry with translated text
    entry = TranslationEntry(
        original_text="Start Game",
        translated_text="Oyuna Başla",
        file_path="screens.rpy",
        line_number=10,
        entry_type="string",
    )
    tfile = TranslationFile(file_path=str(lang_dir / "screens.rpy"), language="turkish")
    tfile.entries.append(entry)

    res = generate_strings_json(
        tl_files=[tfile],
        lang_dir=str(lang_dir),
        config=cfg,
    )

    assert res == 0
    assert not stale_json.exists(), "Stale strings.json must be removed in native output mode"


def test_generate_strings_json_executes_in_strings_mode(tmp_path: Path):
    """In strings output mode, strings.json is properly generated."""
    lang_dir = tmp_path / "game" / "tl" / "turkish"
    lang_dir.mkdir(parents=True)

    cfg = MagicMock()
    cfg.translation_settings = MagicMock()
    cfg.translation_settings.output_mode = "strings"
    cfg.get_log_text = lambda k, def_val=None, **kw: def_val or k

    entry = TranslationEntry(
        original_text="Start Game",
        translated_text="Oyuna Başla",
        file_path="screens.rpy",
        line_number=10,
        entry_type="string",
    )
    tfile = TranslationFile(file_path=str(lang_dir / "screens.rpy"), language="turkish")
    tfile.entries.append(entry)

    res = generate_strings_json(
        tl_files=[tfile],
        lang_dir=str(lang_dir),
        config=cfg,
    )

    assert res == 1
    out_json = lang_dir / "strings.json"
    assert out_json.exists()


def test_reopen_stale_tl_entries_case_and_quote_handling():
    """Verify reopen_stale_tl_entries catches core UI entries even if lowercased or quoted."""
    entry1 = TranslationEntry(
        original_text="Return",
        translated_text="return",  # Lowercase unchanged remnant
        file_path="screens.rpy",
        line_number=1,
        entry_type="string",
    )
    entry2 = TranslationEntry(
        original_text="Quit",
        translated_text='"Quit"',  # Quoted unchanged remnant
        file_path="screens.rpy",
        line_number=2,
        entry_type="string",
    )
    entry3 = TranslationEntry(
        original_text="Return",
        translated_text="Dön",  # Truly translated
        file_path="screens.rpy",
        line_number=3,
        entry_type="string",
    )

    tfile = TranslationFile(file_path="screens.rpy", language="turkish")
    tfile.entries.extend([entry1, entry2, entry3])

    cfg = MagicMock()
    diag = MagicMock()
    guard_events = []

    def record_fn(**kwargs):
        guard_events.append(kwargs)

    counts = reopen_stale_tl_entries([tfile], cfg, diag, record_fn)

    assert counts["unchanged_core_ui"] == 2
    assert entry1.translated_text == ""  # Reopened for translation
    assert entry2.translated_text == ""  # Reopened for translation
    assert entry3.translated_text == "Dön"  # Kept


def test_generate_native_tlid_content_includes_ui_strings():
    """Verify generate_native_tlid_content outputs both dialogue tlid and translate strings blocks."""
    from src.core.pipeline.extraction import generate_native_tlid_content

    entries = [
        {"text": "Hello world", "file_path": "game/script.rpy", "line_number": 10, "text_type": "dialogue"},
        {"text": "Start Game", "file_path": "game/screens.rpy", "line_number": 20, "text_type": "screen"},
        {"text": "Preferences", "file_path": "game/screens.rpy", "line_number": 30, "text_type": "button"},
    ]

    content = generate_native_tlid_content(entries, game_dir="game", target_language="turkish")
    assert "translate turkish" in content
    assert "translate turkish strings:" in content
    assert 'old "Start Game"' in content
    assert 'old "Preferences"' in content
    assert 'old "Hello world"' not in content  # Dialogue goes to tlid, not strings


def test_dialogue_inside_menu_retains_dialogue_type():
    """Verify that dialogue lines inside menu blocks retain dialogue type and do not become menu strings."""
    from src.core.parser import RenPyParser

    parser = RenPyParser(ConfigManager())
    script_content = '''
label test_menu:
    menu:
        "What should we do?"

        "Camp here":
            ALEXANDER "Let's set up the tents so we can rest a bit."
            "The camp was established."
            jump rest

        "Keep moving":
            jump continue_walk
'''
    entries = parser.extract_text_entries_from_string(script_content, file_path="game/script.rpy") if hasattr(parser, 'extract_text_entries_from_string') else []
    if not entries:
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.rpy', delete=False, encoding='utf-8') as tf:
            tf.write(script_content)
            temp_name = tf.name
        try:
            entries = parser.extract_text_entries(temp_name)
        finally:
            import os
            if os.path.exists(temp_name):
                os.remove(temp_name)

    alexander_entries = [e for e in entries if e.get('character') == 'ALEXANDER']
    assert len(alexander_entries) == 1
    assert alexander_entries[0]['text_type'] == 'dialogue'
    assert "tents" in alexander_entries[0]['text']

    # The choice button itself should be menu
    choice_entries = [e for e in entries if e.get('text') == 'Camp here']
    assert len(choice_entries) == 1
    assert choice_entries[0]['text_type'] == 'menu'


def test_merge_tl_content():
    """Verify merge_tl_content combines dialogue and string blocks properly without header duplication."""
    from src.core.pipeline.extraction import merge_tl_content

    existing = """# Existing TL file
translate turkish label1_12345678:
    who "First dialogue"

translate turkish strings:
    old "Save"
    new "Kaydet"
"""

    new_content = """# Header to strip
# Auto-generated

translate turkish label1_87654321:
    MIYUKI "Funny Aya"

translate turkish strings:
    old "Load"
    new "Yükle"
"""

    merged = merge_tl_content(existing, new_content, "turkish")
    assert merged.count("translate turkish strings:") == 1
    assert "label1_12345678" in merged
    assert "label1_87654321" in merged
    assert 'old "Save"' in merged
    assert 'old "Load"' in merged


def test_multibranch_duplicate_dialogue_preserved(tmp_path: Path):
    """Verify that identical dialogue in different if/else branches is preserved for Native TLID."""
    from src.core.parser import RenPyParser
    from src.core.pipeline.extraction import generate_native_tlid_content

    script = """label branch_test:
    if cond == True:
        ALEXANDER "Yeah, and it wouldn't hurt you either."
        AYA "I'm used to it."
    else:
        ALEXANDER "Yeah, and it wouldn't hurt you either."
        AYA "I'm used to it."
"""
    test_file = tmp_path / "script.rpy"
    test_file.write_text(script, encoding="utf-8")

    parser = RenPyParser(ConfigManager())
    entries = parser.extract_text_entries(str(test_file))

    # Both lines 3 & 6 for Alexander and lines 4 & 7 for Aya must be extracted
    alex_entries = [e for e in entries if e.get('text') == "Yeah, and it wouldn't hurt you either."]
    assert len(alex_entries) == 2, f"Expected 2 entries across branches, got {len(alex_entries)}"
    assert alex_entries[0]['line_number'] != alex_entries[1]['line_number']

    aya_entries = [e for e in entries if e.get('text') == "I'm used to it."]
    assert len(aya_entries) == 2, f"Expected 2 entries across branches, got {len(aya_entries)}"

    # When generating native TLID content, both entries must have their own translate blocks
    content = generate_native_tlid_content(entries, game_dir=str(tmp_path), target_language="turkish")
    assert content.count("Yeah, and it wouldn't hurt you either.") == 2
    assert content.count("I'm used to it.") == 2


def test_spoken_dialogue_protected_from_should_skip():
    """Verify that spoken dialogue with character name is never dropped by technical code filters."""
    from src.core.pipeline.extraction import generate_native_tlid_content

    entries = [
        {
            'text': "My lord, hear my oath. I will not harm you, or the members of your house while we rest in this place; may all the gods strike me down if I raise my hand against you.",
            'character': 'SANAE',
            'line_number': 264,
            'file_path': 'game/update17.rpy',
            'text_type': 'dialogue',
        }
    ]
    content = generate_native_tlid_content(entries, game_dir='game', target_language='turkish')
    assert "hear my oath" in content
    assert "translate turkish" in content


def test_merge_tl_content_deduplicates_existing_tlids_and_strings():
    """Verify merge_tl_content strictly deduplicates existing TLIDs and strings without duplication."""
    from src.core.pipeline.extraction import merge_tl_content

    existing = """translate turkish label1_12345678:
    who "First dialogue"

translate turkish strings:
    old "Save"
    new "Kaydet"
"""

    new_content = """translate turkish label1_12345678:
    who "First dialogue"

translate turkish label1_87654321:
    who "Second dialogue"

translate turkish strings:
    old "Save"
    new "Kaydet"

    old "Load"
    new "Yükle"
"""

    merged = merge_tl_content(existing, new_content, "turkish")
    assert merged.count("label1_12345678") == 1
    assert merged.count("label1_87654321") == 1
    assert merged.count('old "Save"') == 1
    assert merged.count('old "Load"') == 1
    assert merged.count("translate turkish strings:") == 1


def test_generate_native_tlid_content_handles_string_engine():
    """Verify generate_native_tlid_content works seamlessly when engine is passed as a string."""
    from src.core.pipeline.extraction import generate_native_tlid_content

    entries = [
        {"text": "Hello world", "file_path": "game/script.rpy", "line_number": 10, "text_type": "dialogue"},
    ]
    # engine passed as string 'google' should not raise AttributeError
    mock_tm = MagicMock()
    mock_tm._cache = {}
    content = generate_native_tlid_content(
        entries, game_dir="game", target_language="turkish",
        engine="google", translation_manager=mock_tm,
    )
    assert "translate turkish" in content
    assert "Hello world" in content


def test_generate_native_tlid_content_deduplicates_multispeaker_strings():
    """Verify multi-speaker dialogue lines falling back to strings are deduplicated."""
    from src.core.pipeline.extraction import generate_native_tlid_content

    entries = [
        {"text": "Cheers!", "file_path": "game/script.rpy", "line_number": 10, "character": "A and B", "text_type": "dialogue"},
        {"text": "Cheers!", "file_path": "game/script.rpy", "line_number": 20, "character": "C and D", "text_type": "dialogue"},
    ]
    content = generate_native_tlid_content(entries, game_dir="game", target_language="turkish")
    assert content.count('old "Cheers!"') == 1




