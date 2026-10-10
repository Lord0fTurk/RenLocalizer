import pytest
from src.core.parser import RenPyParser
from src.core.pipeline.extraction import generate_native_tlid_content
from src.core.rpyc_reader import ASTTextExtractor, FakeLabel, FakeSay


def test_sequential_local_labels_scoping_in_parser(tmp_path):
    """
    Test that sequential local labels (.sub1, .sub2, .sub3) are each scoped
    directly to the root global label (e.g. parent.sub1, parent.sub2),
    never cumulatively nested (parent.sub1.sub2.sub3).
    """
    script_content = """
label chapter1:
    "Introduction text"

label .part1:
    "Part 1 text"

label .part2:
    "Part 2 text"

label .morning:
    p "Good morning"
"""
    test_file = tmp_path / "chapter1.rpy"
    test_file.write_text(script_content, encoding="utf-8")

    parser = RenPyParser()
    entries = parser.extract_text_entries(test_file)

    entry_map = {e["text"]: e for e in entries}

    # Verify contexts
    assert "Introduction text" in entry_map
    assert entry_map["Introduction text"]["context_path"] == ["label:chapter1"]

    assert "Part 1 text" in entry_map
    assert entry_map["Part 1 text"]["context_path"] == ["label:chapter1.part1"]

    assert "Part 2 text" in entry_map
    assert entry_map["Part 2 text"]["context_path"] == ["label:chapter1.part2"]

    assert "Good morning" in entry_map
    assert entry_map["Good morning"]["context_path"] == ["label:chapter1.morning"]

    # Verify Native TLID generation output
    for e in entries:
        e["file_path"] = "chapter1.rpy"

    content = generate_native_tlid_content(
        entries=entries,
        game_dir=str(tmp_path),
        target_language="turkish",
    )

    assert "translate turkish chapter1_part1_" in content
    assert "translate turkish chapter1_part2_" in content
    assert "translate turkish chapter1_morning_" in content
    # Cumulative nested identifiers must NOT exist
    assert "chapter1_part1_part2" not in content
    assert "part1_part2_morning" not in content


def test_rpyc_flat_label_sequence_context_propagation():
    """
    Test that FakeLabel in flat node sequences inside a parent block
    updates the active context for subsequent FakeSay nodes in ASTTextExtractor.
    """
    extractor = ASTTextExtractor()

    # Create root label containing flat child labels and says
    root_label = FakeLabel()
    root_label.name = "ch92"

    sub_label1 = FakeLabel()
    sub_label1.name = "ch92.continue"

    sub_label2 = FakeLabel()
    sub_label2.name = "ch92.morning"

    say1 = FakeSay()
    say1.who = ""
    say1.what = "Waking up in the morning."
    say1.linenumber = 10

    say2 = FakeSay()
    say2.who = "p"
    say2.what = "Good morning!"
    say2.linenumber = 11

    # In Ren'Py AST, siblings are often flat in the parent's block
    root_label.block = [sub_label1, sub_label2, say1, say2]

    extractor._walk_nodes([root_label], context="file:test.rpy")

    extracted = [t for t in extractor.extracted if t.text_type == "dialogue"]
    assert len(extracted) == 2

    assert extracted[0].text == "Waking up in the morning."
    assert extracted[0].context == "label:ch92.morning"

    assert extracted[1].text == "Good morning!"
    assert extracted[1].context == "label:ch92.morning"


def test_call_from_label_scoping(tmp_path):
    """
    Test that 'call ... from <name>' statements in Ren'Py script:
    1. If name starts without '_', it replaces active label scope (e.g. from d95dt).
    2. If name starts with '_', it is an alternate label (does not replace primary label).
    """
    script_content = """
label chapter2:
    "Before call"

    call driveTo("Kari") from d95dt

    "After call line 1"
    p "Damn!"

    call makeCalendar from _call_makeCalendar

    "After alternate call"
"""
    test_file = tmp_path / "chapter2.rpy"
    test_file.write_text(script_content, encoding="utf-8")

    parser = RenPyParser()
    entries = parser.extract_text_entries(test_file)
    entry_map = {e["text"]: e for e in entries}

    assert "Before call" in entry_map
    assert entry_map["Before call"]["context_path"] == ["label:chapter2"]

    assert "After call line 1" in entry_map
    assert entry_map["After call line 1"]["context_path"] == ["label:d95dt"]

    assert "Damn!" in entry_map
    assert entry_map["Damn!"]["context_path"] == ["label:d95dt"]

    assert "After alternate call" in entry_map
    # _call_makeCalendar starts with '_', so primary label remains d95dt
    assert entry_map["After alternate call"]["context_path"] == ["label:d95dt"]

    for e in entries:
        e["file_path"] = "chapter2.rpy"

    content = generate_native_tlid_content(
        entries=entries,
        game_dir=str(tmp_path),
        target_language="turkish",
    )

    assert "translate turkish chapter2_" in content
    assert "translate turkish d95dt_" in content



def test_renpy_84_label_name_is_read_from_private_field():
    """Ren'Py 8.4+ pickles Label.name as "_name"; reading "" put every line of
    an .rpyc-only game under start_<hash> (verified on Den of the Defiant)."""
    from src.core.rpyc_reader import ASTTextExtractor, FakeLabel, FakeSay

    label = FakeLabel.__new__(FakeLabel)        # unpickling skips __init__
    say = FakeSay()
    say.who, say.what, say.linenumber = "", "Such beauty...such radiance.", 40
    label.__setstate__({"_name": "scene_004_wake_up", "block": [say], "linenumber": 1})
    assert label.name == "scene_004_wake_up"

    extractor = ASTTextExtractor()
    extractor._walk_nodes([label], context="file:x.rpy")
    assert [t.context for t in extractor.extracted] == ["label:scene_004_wake_up"]


def test_rpyc_lines_are_only_matched_against_their_own_rpy(tmp_path, monkeypatch):
    """The same sentence in two .rpyc-only scenes is two say statements with two
    ids; only a line the script's own .rpy already has is a duplicate
    (Den of the Defiant, .rpyc-only: 5,183 -> 362 -> fewer missing lines)."""
    from src.core.parser import RenPyParser
    from src.utils.config import ConfigManager

    game = tmp_path / "game"
    game.mkdir()
    (game / "a.rpy").write_text('label a:\n    "She is so beautiful."\n', encoding="utf-8")
    for name in ("a.rpyc", "b.rpyc", "c.rpyc"):
        (game / name).write_bytes(b"")

    def fake_rpyc(self, directory, recursive=True):
        line = {"text": "She is so beautiful.", "character": "", "text_type": "dialogue", "is_rpyc": True}
        return {game / n: [dict(line, context="label:" + n[0])] for n in ("a.rpyc", "b.rpyc", "c.rpyc")}

    monkeypatch.setattr(RenPyParser, "extract_from_rpyc_directory", fake_rpyc)
    results = RenPyParser(ConfigManager()).extract_combined(
        str(game), include_rpy=True, include_rpyc=True, include_deep_scan=False)
    by_file = {p.name: [e["text"] for e in es] for p, es in results.items()}
    assert by_file["a.rpy"] == ["She is so beautiful."]
    assert "a.rpyc" not in by_file                      # same script as a.rpy
    assert by_file["b.rpyc"] == ["She is so beautiful."]
    assert by_file["c.rpyc"] == ["She is so beautiful."]


def test_rpyc_label_inside_a_menu_names_the_lines_after_it():
    """Ren'Py keeps one current label in source order: a label written inside
    a menu choice also names the lines after the menu (Willing Temptations)."""
    from src.core.rpyc_reader import ASTTextExtractor, FakeLabel, FakeMenu, FakeSay

    def say(text, line):
        node = FakeSay()
        node.who, node.what, node.linenumber = "", text, line
        return node

    inner = FakeLabel()
    inner.name = "oigp"
    inner.block = [say("Inside the label.", 3)]
    hidden = FakeLabel()
    hidden.name = "_call_x_1"
    menu = FakeMenu()
    menu.items = [("Go", "True", [inner])]
    outer = FakeLabel()
    outer.name = "watch_continue"
    outer.block = [say("Before.", 1), menu, hidden, say("Damn it, what a mess.", 9)]

    extractor = ASTTextExtractor()
    extractor._walk_nodes([outer], context="file:script.rpy")
    contexts = {t.text: t.context for t in extractor.extracted if t.text_type == "dialogue"}
    assert contexts["Before."] == "label:watch_continue"
    assert contexts["Inside the label."] == "label:oigp"
    assert contexts["Damn it, what a mess."] == "label:oigp"


def test_rpyc_reader_does_not_take_prose_for_python():
    """Bare "for ... in" / "return" / "raise" matched dialogue in the .rpyc
    reader (Den of the Defiant, Willing Temptations)."""
    from src.core.rpyc_reader import ASTTextExtractor

    extractor = ASTTextExtractor()
    for text in (
        "To adore her...and feel her adoration for me in return.",
        "Only by destroying Earth could the Goddess be free to return to Eden.",
        "I could ask for help, and I beg him for help in any way he can.",
        "I'll raise my hand.",
    ):
        assert not extractor._is_technical_string(text), text
    for code in ("for item in inventory:\n    pass", "return True", "import os", "def f(x):\n    return x"):
        assert extractor._is_technical_string(code), code
