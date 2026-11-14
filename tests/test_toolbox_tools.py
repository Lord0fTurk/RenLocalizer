# -*- coding: utf-8 -*-
"""
Tests for RenLocalizer Toolbox tools:
- Font Helper (compatibility check, font suggestions)
- Font Injector (normalization, candidates, download logic)
- Ren'Py Lint (built-in translation linter)
- Glossary Extractor
"""


from src.tools.font_helper import FontHelper
from src.tools.font_injector import _normalize_lang_code, FONT_CANDIDATES
from src.tools.renpy_lint import lint_translation_output
from src.tools.glossary_extractor.extractor import GlossaryExtractor


def test_font_helper_suggestions_languages():
    """Verify font suggestions return native script fonts for non-Latin languages."""
    helper = FontHelper()

    # Persian / Farsi
    persian_fonts = helper.suggest_fonts("persian")
    assert "Vazirmatn" in persian_fonts
    assert "Noto Sans Arabic" in persian_fonts

    fa_fonts = helper.suggest_fonts("fa")
    assert "Vazirmatn" in fa_fonts

    # Arabic
    ar_fonts = helper.suggest_fonts("arabic")
    assert "Noto Sans Arabic" in ar_fonts

    # Turkish
    tr_fonts = helper.suggest_fonts("turkish")
    assert "Noto Sans" in tr_fonts or "Roboto" in tr_fonts

    # Japanese
    ja_fonts = helper.suggest_fonts("japanese")
    assert "Noto Sans JP" in ja_fonts


def test_font_injector_candidate_mapping():
    """Verify language code normalization and candidate retrieval."""
    assert _normalize_lang_code("persian") == "fa"
    assert _normalize_lang_code("farsi") == "fa"
    assert _normalize_lang_code("turkish") == "tr"
    assert _normalize_lang_code("arabic") == "ar"
    assert _normalize_lang_code("japanese") == "ja"
    assert _normalize_lang_code("jp") == "ja"
    assert _normalize_lang_code("korean") == "ko"
    assert _normalize_lang_code("kor") == "ko"

    # Issue #18: Chinese variants normalization
    assert _normalize_lang_code("chinese_s") == "zh"
    assert _normalize_lang_code("chinese-s") == "zh"
    assert _normalize_lang_code("chinese_simplified") == "zh"
    assert _normalize_lang_code("simplified_chinese") == "zh"
    assert _normalize_lang_code("simplified chinese") == "zh"
    assert _normalize_lang_code("schinese") == "zh"
    assert _normalize_lang_code("zh-cn") == "zh"
    assert _normalize_lang_code("zh_hans") == "zh"

    assert _normalize_lang_code("chinese_t") == "zh_tw"
    assert _normalize_lang_code("chinese_traditional") == "zh_tw"
    assert _normalize_lang_code("traditional_chinese") == "zh_tw"
    assert _normalize_lang_code("tchinese") == "zh_tw"
    assert _normalize_lang_code("zh-tw") == "zh_tw"
    assert _normalize_lang_code("zh_hant") == "zh_tw"

    # Verify candidates exist for critical languages
    for code in ["fa", "ar", "he", "ur", "tr", "ja", "ko", "zh", "zh_tw", "ru", "uk", "vi", "th", "pl", "es", "de", "fr"]:
        assert code in FONT_CANDIDATES, f"Missing candidate for {code}"

    # Verify Chinese candidate is Noto Sans SC
    zh_candidates = FONT_CANDIDATES["zh"]
    assert zh_candidates[0][0] == "Noto Sans SC"
    assert zh_candidates[0][1] is False

    # Verify Persian candidates have RTL flag True and include Vazirmatn
    fa_candidates = FONT_CANDIDATES["fa"]
    assert fa_candidates[0][0] == "Vazirmatn"
    assert fa_candidates[0][1] is True  # is_rtl


def test_renpy_lint_builtin_fallback(tmp_path):
    """Verify lint_translation_output runs and produces a report without Ren'Py SDK."""
    game_dir = tmp_path / "game"
    tl_dir = game_dir / "tl" / "turkish"
    tl_dir.mkdir(parents=True)

    test_rpy = tl_dir / "test.rpy"
    test_rpy.write_text(
        'translate turkish strings:\n'
        '    old "Hello"\n'
        '    new "Merhaba"\n',
        encoding="utf-8"
    )

    # Run lint without SDK
    report = lint_translation_output(str(tl_dir), try_engine_lint=False)
    assert report is not None
    assert report.files_scanned >= 1
    assert report.translate_blocks >= 1
    assert report.ok is True


def test_glossary_extractor_run(tmp_path):
    """Verify GlossaryExtractor analyzes rpy files without crashes."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True)

    script_rpy = game_dir / "script.rpy"
    script_rpy.write_text(
        'define e = Character("Eileen")\n'
        'define l = Character("Lord Blackwood")\n'
        'label start:\n'
        '    e "Welcome to the game!"\n'
        '    l "Indeed, welcome!"\n',
        encoding="utf-8"
    )

    extractor = GlossaryExtractor()
    terms = extractor.extract_from_directory(str(tmp_path), min_occurrence=1)
    assert isinstance(terms, dict)
    assert "Eileen" in terms or "Lord Blackwood" in terms


def test_glossary_extractor_latin1_fallback(tmp_path):
    """Verify GlossaryExtractor survives and parses non-UTF-8 (e.g. latin-1) rpy files."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True)

    script_rpy = game_dir / "legacy_script.rpy"
    # Write with cp1252 / latin-1 containing special characters (e.g. café, François)
    script_rpy.write_bytes(
        b'define f = Character("Fran\xe7ois")\n'
        b'label start:\n'
        b'    f "Bienvenue au caf\xe9!"\n'
    )

    extractor = GlossaryExtractor()
    terms = extractor.extract_from_directory(str(tmp_path), min_occurrence=1)
    assert isinstance(terms, dict)
    assert "François" in terms


def test_google_translator_init_binding():
    """Verify GoogleTranslator gracefully handles positional and keyword config_manager."""
    from src.utils.config import ConfigManager
    from src.core.translators.google import GoogleTranslator

    cfg = ConfigManager()
    cfg.translation_settings.max_concurrent_threads = 24

    # Positional
    gt_pos = GoogleTranslator(cfg)
    assert gt_pos.config_manager is cfg
    assert gt_pos.multi_q_concurrency == 24

    # Keyword
    gt_kw = GoogleTranslator(config_manager=cfg)
    assert gt_kw.config_manager is cfg
    assert gt_kw.multi_q_concurrency == 24

