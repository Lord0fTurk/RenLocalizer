from src.core.rpyc_reader import ASTTextExtractor, FakeArgumentInfo, FakeSLUse


def _extractor():
    return ASTTextExtractor.__new__(ASTTextExtractor)


def _use(*pairs):
    node = FakeSLUse()
    node.target = "gock_textbutton"
    info = FakeArgumentInfo()
    info.arguments = list(pairs)
    node.args = info
    node.location = ("screens.rpy", 487)
    return node


def _collect(node):
    ex = _extractor()
    seen = []
    ex._add_text = lambda text, line, kind, **kw: seen.append((text, kind))
    ex._extract_string_content = lambda s: s[1:-1]
    ex._extract_strings_from_code = lambda src, line: seen.append((src, "code"))
    ex._process_screen_node(node, "")
    return seen


def test_capitalised_positional_label_is_extracted():
    assert _collect(_use((None, '"New Game"'), (None, "Start()"))) == [("New Game", "ui")]


def test_style_names_and_ids_are_not_extracted():
    assert _collect(_use((None, '"inventory"'), ("style", '"menu_button"'))) == []


def test_text_keyword_is_extracted_even_when_lowercase():
    assert _collect(_use(("label", '"back"'))) == [("back", "ui")]
