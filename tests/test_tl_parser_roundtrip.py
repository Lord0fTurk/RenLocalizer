# -*- coding: utf-8 -*-
"""tl_parser must not corrupt or overwrite translations when it rewrites a tl file."""
import pytest

from src.core.tl_parser import TLParser


@pytest.mark.parametrize("raw", [
    r"C:\\new folder",          # a literal backslash followed by "n"
    r"100\% sure",              # unknown escape kept as written
    r"[[x] \{ and \[",
    r"say \"hi\"\nok",
    r"tab\there",
    r"ends with \\",
    r"it\'s",
])
def test_escape_roundtrip(raw):
    p = TLParser()
    text = p._unescape_string(raw)
    again = p._unescape_string(p._escape_string(text))
    assert again == text


@pytest.mark.parametrize("raw", [
    r"C:\\new folder",
    r"100\% sure",
    r"[[x] \{ and \[",
    r"say \"hi\"\nok",
    r"ends with \\",
    r"¯\\_(ツ)_/¯",
    r"C:\\windows\\system",
])
def test_rewrite_reproduces_the_literal(raw):
    # Rewriting a tl line must not change what Ren'Py reads from it.
    p = TLParser()
    assert p._escape_string(p._unescape_string(raw)) == raw


def test_unknown_escape_is_the_character_like_renpy():
    assert TLParser()._unescape_string(r"\w\%") == "w\\%"


def test_literal_backslash_n_is_not_a_newline():
    assert TLParser()._unescape_string(r"C:\\new") == "C:\\new"


def test_text_keyed_translation_does_not_overwrite_a_hand_edit(tmp_path):
    path = tmp_path / "a.rpy"
    path.write_text(
        'translate turkish a_1:\n\n    # m "Yes"\n    m "Evet, elle düzelttim"\n\n'
        'translate turkish b_2:\n\n    # m "Yes"\n    m ""\n\n'
        'translate turkish c_3:\n\n    # m "Yes"\n    m "Yes"\n',
        encoding="utf-8",
    )
    p = TLParser()
    out = p.update_translations(p.parse_file(str(path)), {"Yes": "Evet"})
    lines = [l.strip() for l in out.splitlines() if l.strip().startswith('m "')]
    assert lines == ['m "Evet, elle düzelttim"', 'm "Evet"', 'm "Evet"']


def test_id_keyed_translation_still_replaces(tmp_path):
    path = tmp_path / "a.rpy"
    path.write_text('translate turkish strings:\n\n    old "Start"\n    new "Basla"\n', encoding="utf-8")
    p = TLParser()
    f = p.parse_file(str(path))
    out = p.update_translations(f, {f.entries[0].translation_id: "Başla"})
    assert 'new "Başla"' in out
