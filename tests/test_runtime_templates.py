import sys


class MockRenpyLoader:
    class MockApk:
        def open(self, path):
            return None

        def getvalue(self):
            return b'{"test": "value"}'

    game_apks = [MockApk()]


class MockRenpy:
    config = None

    def __init__(self):
        self.loader = MockRenpyLoader()
        self._current_screen = None

    def current_screen(self):
        return self._current_screen


class MockPreferences:
    def __init__(self, lang="tr"):
        self.language = lang


class MockStore:
    _preferences = MockPreferences()


# Setup mocks BEFORE importing
sys.modules["renpy"] = MockRenpy()
sys.modules["renpy.store"] = MockStore()

from src.core import runtime_hook_template as rht


def test_template_logic(tmp_path):
    """Test runtime hook template renders correctly."""
    hook = rht.render_runtime_hook("turkish", runtime_string_diagnostics=False)

    assert hook
    assert len(hook) > 1000
    assert "_rl_replace_text" in hook
    assert "_rl_load_translations" in hook


def test_runtime_hook_rtl_for_persian(tmp_path):
    """Test RTL settings for Persian language."""
    hook = rht.render_runtime_hook("persian", runtime_string_diagnostics=False)

    assert "config.rtl = True" in hook
    assert "_style.language = 'unicode'" in hook
    assert "_style.reading_order = 'wrtl'" in hook


def test_runtime_hook_rtl_for_arabic(tmp_path):
    """Test RTL settings for Arabic language."""
    hook = rht.render_runtime_hook("arabic", runtime_string_diagnostics=False)

    assert "config.rtl = True" in hook
    assert "_style.language = 'unicode'" in hook


def test_runtime_hook_rtl_disabled_for_english(tmp_path):
    """Test RTL is disabled for non-RTL languages."""
    hook = rht.render_runtime_hook("english", runtime_string_diagnostics=False)

    assert "config.rtl = False" in hook


def test_runtime_hook_rtl_languages_list(tmp_path):
    """Test RTL languages are properly listed."""
    hook = rht.render_runtime_hook("tr", runtime_string_diagnostics=False)

    assert "arabic" in hook
    assert "persian" in hook or "farsi" in hook


def test_runtime_hook_diagnostics_enabled(tmp_path):
    """Test diagnostics are enabled when flag is True."""
    hook = rht.render_runtime_hook("tr", runtime_string_diagnostics=True)

    assert "_rl_log_runtime_miss" in hook
    assert "runtime_missed_strings.jsonl" in hook


def test_runtime_hook_diagnostics_disabled(tmp_path):
    """Test diagnostics are disabled when flag is False."""
    hook = rht.render_runtime_hook("tr", runtime_string_diagnostics=False)

    assert "_rl_replace_text" in hook


def test_runtime_hook_template_system(tmp_path):
    """Test template system exists."""
    hook = rht.render_runtime_hook("tr", runtime_string_diagnostics=False)

    assert "_rl_template_map" in hook
    assert "_rl_template_prefix_index" in hook


def test_runtime_hook_phrase_index(tmp_path):
    """Test phrase index for longer text matching."""
    hook = rht.render_runtime_hook("tr", runtime_string_diagnostics=False)

    assert "_rl_phrase_index" in hook
    assert "_rl_phrase_variants" in hook


def test_runtime_hook_caching(tmp_path):
    """Test runtime caching for performance (v4.2.0 MRU-based architecture)."""
    hook = rht.render_runtime_hook("tr", runtime_string_diagnostics=False)

    assert "_rl_mru_cache" in hook           # MRU list replaces sys._rl_caches['replace']
    assert "_rl_translations_norm" in hook   # Pre-built norm dict replaces sys._rl_caches['normalized']
    assert "_rl_mru_cache_max" in hook       # Size limit for MRU cache


def test_runtime_hook_language_detection(tmp_path):
    """Test active language detection."""
    hook = rht.render_runtime_hook("turkish", runtime_string_diagnostics=False)

    assert "_rl_get_active_language" in hook
    assert "_preferences.language" in hook


def test_runtime_hook_template_variants(tmp_path):
    """Test template variants are generated."""
    hook = rht.render_runtime_hook("tr", runtime_string_diagnostics=False)

    assert "_rl_translations_ci" in hook


def test_runtime_hook_normalized_lookup(tmp_path):
    """Test normalized lookup for Unicode variants."""
    hook = rht.render_runtime_hook("tr", runtime_string_diagnostics=False)

    assert "_rl_translations_norm" in hook


def test_runtime_hook_rtl_for_iso_codes(tmp_path):
    """Test RTL ISO codes (fa, ar, he) are properly recognized in runtime hook."""
    hook = rht.render_runtime_hook("fa", runtime_string_diagnostics=False)
    assert "'fa'" in hook
    assert "'ar'" in hook
    assert "'he'" in hook


def test_runtime_hook_rtl_late_binding(tmp_path):
    """Test late-binding RTL direction enforcement in init 999 block."""
    hook = rht.render_runtime_hook("persian", runtime_string_diagnostics=False)
    # Both early init and late-binding init 999 should call direction apply
    assert "init 999 python:" in hook
    assert "_rl_apply_runtime_language_direction(_rl_get_active_language())" in hook


def test_runtime_hook_native_rtl(tmp_path):
    """Test Native TLID hook applies RTL for RTL languages and avoids it for LTR."""
    hook_rtl = rht.render_runtime_hook_native("persian")
    assert "config.rtl = True" in hook_rtl
    assert "_rst.reading_order = 'wrtl'" in hook_rtl

    hook_ltr = rht.render_runtime_hook_native("turkish")
    assert "config.rtl = True" not in hook_ltr
    assert "reading_order = 'wrtl'" not in hook_ltr


def test_is_rtl_language_helper():
    """Test is_rtl_language accurately categorizes languages."""
    from src.core.pipeline.constants import is_rtl_language

    # RTL positive
    assert is_rtl_language("persian") is True
    assert is_rtl_language("farsi") is True
    assert is_rtl_language("arabic") is True
    assert is_rtl_language("hebrew") is True
    assert is_rtl_language("urdu") is True
    assert is_rtl_language("fa") is True
    assert is_rtl_language("ar") is True
    assert is_rtl_language("he") is True
    assert is_rtl_language("ur") is True

    # LTR negative (MUST NOT BE RTL)
    assert is_rtl_language("turkish") is False
    assert is_rtl_language("tr") is False
    assert is_rtl_language("english") is False
    assert is_rtl_language("en") is False
    assert is_rtl_language("german") is False
    assert is_rtl_language("de") is False
    assert is_rtl_language("russian") is False
    assert is_rtl_language("ru") is False
    assert is_rtl_language("japanese") is False
    assert is_rtl_language("ja") is False
    assert is_rtl_language("chinese") is False
    assert is_rtl_language("zh") is False
    assert is_rtl_language(None) is False
    assert is_rtl_language("") is False


def test_create_language_init_file_rtl_isolation(tmp_path):
    """Test create_language_init_file includes RTL config ONLY for RTL languages."""
    from src.core.pipeline.saving import create_language_init_file
    from unittest.mock import MagicMock

    mock_config = MagicMock()
    mock_config.get_ui_text.return_value = "Created: {path}"
    mock_log = MagicMock()

    game_dir = tmp_path / "game"
    game_dir.mkdir()

    # Test RTL language (persian)
    create_language_init_file(str(game_dir), "persian", mock_config, mock_log)
    init_file_rtl = game_dir / "zzz_persian_language.rpy"
    assert init_file_rtl.exists()
    content_rtl = init_file_rtl.read_text(encoding="utf-8-sig")
    assert "define config.rtl = True" in content_rtl
    assert "reading_order = 'wrtl'" in content_rtl

    # Test LTR language (turkish) - MUST NOT have config.rtl = True
    create_language_init_file(str(game_dir), "turkish", mock_config, mock_log)
    init_file_ltr = game_dir / "zzz_turkish_language.rpy"
    assert init_file_ltr.exists()
    content_ltr = init_file_ltr.read_text(encoding="utf-8-sig")
    assert "define config.rtl = True" not in content_ltr
    assert "reading_order = 'wrtl'" not in content_ltr