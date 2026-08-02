import unittest

from src.core.parser import RenPyParser
from src.core.output_formatter import RenPyOutputFormatter


def test_parser_regex_attributes_exist():
    p = RenPyParser()
    for attr in [
        "label_def_re",
        "multiline_registry",
        "menu_def_re",
        "screen_def_re",
        "pattern_registry",
        "python_block_re",
    ]:
        assert hasattr(p, attr), f"RenPyParser missing attribute: {attr}"


def test_skip_extensions_removed():
    f = RenPyOutputFormatter()
    # These extensions should NOT be in the skip list (we removed them)
    for ext in ['.json', '.txt', '.xml', '.csv']:
        assert ext not in f.SKIP_FILE_EXTENSIONS


def test_protect_renpy_syntax_edge_cases():
    from src.core.translator import protect_renpy_syntax, restore_renpy_syntax
    # Edge-case: teknik tag, iç içe placeholder, karmaşık yapı
    samples = [
        "{color=#fff}Merhaba{/color}",
        "[player] {b}Kazandı{/b}",
        "{size=20}[score]{/size}",
        "{font=Comic}[name]{/font}",
        "{[player]} ve [{score}]",  # iç içe
        "[player] {color=#fff}Kazandı{/color}"
    ]
    for sample in samples:
        protected, placeholders = protect_renpy_syntax(sample)
        # Tüm teknik ve iç içe yapılar korunmalı
        for key, original in placeholders.items():
            # Wrapper pairs are stored in dict but not embedded in protected text
            if key.startswith("__WRAPPER_PAIR_"):
                assert isinstance(original, tuple) and len(original) == 2
                assert original[0] in sample and original[1] in sample
            else:
                assert key in protected
                assert original in sample
        # Geri dönüşümde orijinal metin elde edilmeli
        restored = restore_renpy_syntax(protected, placeholders)
        assert restored == sample


def test_quality_check():
    from src.core.parser import RenPyParser
    parser = RenPyParser()
    # Anlamlı, doğru ve teknik olmayan metin
    result = parser.quality_check("Merhaba, nasılsın?")
    assert result['is_meaningful'] is True
    assert result['has_grammar_error'] is False
    assert result['is_technically_valid'] is True

    # Teknik kod, dosya yolu, anlamsız metin
    result2 = parser.quality_check("config.version = 1.0")
    assert result2['is_meaningful'] is False
    assert result2['is_technically_valid'] is False

    # Dilbilgisi hatalı metin
    result3 = parser.quality_check("merhaba nasılsın")
    assert result3['has_grammar_error'] is True


def test_classify_text_type():
    from src.core.parser import RenPyParser
    parser = RenPyParser()
    assert parser.classify_text_type("menu \"Seçenek\":") == "menu"


def test_parser_regex_attributes_exist():
    p = RenPyParser()
    for attr in [
        "label_def_re",
        "multiline_registry",
        "menu_def_re",
        "screen_def_re",
        "pattern_registry",
        "python_block_re",
    ]:
        assert hasattr(p, attr), f"RenPyParser missing attribute: {attr}"


def test_skip_extensions_removed():
    f = RenPyOutputFormatter()
    # These extensions should NOT be in the skip list (we removed them)
    for ext in ['.json', '.txt', '.xml', '.csv']:
        assert ext not in f.SKIP_FILE_EXTENSIONS


def test_protect_renpy_syntax_edge_cases():
    from src.core.translator import protect_renpy_syntax, restore_renpy_syntax
    # Edge-case: teknik tag, iç içe placeholder, karmaşık yapı
    samples = [
        "{color=#fff}Merhaba{/color}",
        "[player] {b}Kazandı{/b}",
        "{size=20}[score]{/size}",
        "{font=Comic}[name]{/font}",
        "{[player]} ve [{score}]",  # iç içe
        "[player] {color=#fff}Kazandı{/color}"
    ]
    for sample in samples:
        protected, placeholders = protect_renpy_syntax(sample)
        # Tüm teknik ve iç içe yapılar korunmalı
        for key, original in placeholders.items():
            # Wrapper pairs are stored in dict but not embedded in protected text
            if key.startswith("__WRAPPER_PAIR_"):
                assert isinstance(original, tuple) and len(original) == 2
                assert original[0] in sample and original[1] in sample
            else:
                assert key in protected
                assert original in sample
        # Geri dönüşümde orijinal metin elde edilmeli
        restored = restore_renpy_syntax(protected, placeholders)
        assert restored == sample


def test_quality_check():
    from src.core.parser import RenPyParser
    parser = RenPyParser()
    # Anlamlı, doğru ve teknik olmayan metin
    result = parser.quality_check("Merhaba, nasılsın?")
    assert result['is_meaningful'] is True
    assert result['has_grammar_error'] is False
    assert result['is_technically_valid'] is True

    # Teknik kod, dosya yolu, anlamsız metin
    result2 = parser.quality_check("config.version = 1.0")
    assert result2['is_meaningful'] is False
    assert result2['is_technically_valid'] is False

    # Dilbilgisi hatalı metin
    result3 = parser.quality_check("merhaba nasılsın")
    assert result3['has_grammar_error'] is True


def test_classify_text_type():
    from src.core.parser import RenPyParser
    parser = RenPyParser()
    assert parser.classify_text_type("menu \"Seçenek\":") == "menu"
    assert parser.classify_text_type("screen ana_ekran:") == "screen"
    assert parser.classify_text_type("e \"Merhaba!\"") == "character"
    assert parser.classify_text_type("config.version = 1.0") == "technical"
    assert parser.classify_text_type("Merhaba, nasılsın?") == "general"


@unittest.skip("pyparse_grammar is stubbed")
def test_pyparse_python_calls_and_notify(tmp_path):
    from src.core.pyparse_grammar import extract_with_pyparsing
    sample = '''
label start:
    $ renpy.notify("Hello Player")
    python:
        _("Inner call")
        __("Double underscore")
        renpy.say(e, "Talk")
    '''
    out = extract_with_pyparsing(sample, file_path="test.rpy")
    texts = {e['text'] for e in out}
    assert "Hello Player" in texts
    assert "Inner call" in texts
    assert "Double underscore" in texts
    assert "Talk" in texts


def test_char_dialog_regex_accepts_no_space_after_character_name():
    parser = RenPyParser()
    match = parser.char_dialog_re.match('a"Hello there."')
    assert match is not None
    assert match.group('char') == 'a'


def test_char_dialog_regex_still_accepts_normal_spacing():
    parser = RenPyParser()
    match = parser.char_dialog_re.match('e "Hi."')
    assert match is not None
    assert match.group('char') == 'e'


def test_char_dialog_regex_accepts_image_attributes():
    parser = RenPyParser()
    match = parser.char_dialog_re.match('iside basics "The house is clean."')
    assert match is not None
    assert match.group('char') == 'iside'


def test_char_dialog_regex_accepts_quoted_speaker_names():
    parser = RenPyParser()
    match = parser.char_dialog_re.match('"Mark" "Come here."')
    assert match is not None
    assert match.group('char') == '"Mark"'


def test_char_dialog_regex_accepts_attributed_say_variants():
    parser = RenPyParser()
    match = parser.char_dialog_re.match('e happy @ vhappy "Really?"')
    assert match is not None
    assert match.group('char') == 'e'


def test_char_dialog_regex_does_not_treat_screen_text_as_speaker():
    parser = RenPyParser()
    assert parser.char_dialog_re.match('text"Hello"') is None
    assert parser.char_dialog_re.match('textbutton"Start"') is None
    assert parser.char_dialog_re.match('label"Name"') is None
    assert parser.char_dialog_re.match('window show "Loading"') is None
    assert parser.char_dialog_re.match('show text "Loading"') is None
    assert parser.char_dialog_re.match('screen title "Title"') is None


def test_classify_text_type_supports_no_space_character_dialogue():
    parser = RenPyParser()
    assert parser.classify_text_type('a"Hello there."') == "character"


def test_classify_text_type_supports_image_attribute_dialogue():
    parser = RenPyParser()
    assert parser.classify_text_type('iside basics "The house is clean."') == "character"


def test_classify_text_type_supports_quoted_speaker_dialogue():
    parser = RenPyParser()
    assert parser.classify_text_type('"Mark" "Come here."') == "character"


class TestDialogueAttributeVariants(unittest.TestCase):
    def test_dialogue_attribute_variants_and_false_positives(self):
        parser = RenPyParser()

        match = parser.char_dialog_re.match('iside basics "The house is clean."')
        if match is None:
            self.fail('Expected image-attribute dialogue to match')
        self.assertEqual(match.group('char'), 'iside')

        match = parser.char_dialog_re.match('"Mark" "Come here."')
        if match is None:
            self.fail('Expected quoted speaker dialogue to match')
        self.assertEqual(match.group('char'), '"Mark"')

        match = parser.char_dialog_re.match('e happy @ vhappy "Really?"')
        if match is None:
            self.fail('Expected attributed dialogue to match')
        self.assertEqual(match.group('char'), 'e')

        self.assertIsNone(parser.char_dialog_re.match('text"Hello"'))
        self.assertIsNone(parser.char_dialog_re.match('textbutton"Start"'))
        self.assertIsNone(parser.char_dialog_re.match('label"Name"'))
        self.assertIsNone(parser.char_dialog_re.match('window show "Loading"'))
        self.assertIsNone(parser.char_dialog_re.match('show text "Loading"'))
        self.assertIsNone(parser.char_dialog_re.match('screen title "Title"'))


class TestLanguageNormalization(unittest.TestCase):
    def test_api_and_legacy_codes_map_to_renpy_keys(self):
        from src.utils.config import ConfigManager

        cm = ConfigManager.__new__(ConfigManager)
        self.assertEqual(cm.normalize_renpy_language_code('tr'), 'turkish')
        self.assertEqual(cm.normalize_renpy_language_code('es'), 'spanish')
        self.assertEqual(cm.normalize_renpy_language_code('zh-CN'), 'chinese_s')
        self.assertEqual(cm.normalize_renpy_language_code('turkish'), 'turkish')
