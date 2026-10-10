# -*- coding: utf-8 -*-
"""Translation ids must match what Ren'Py computes, and real dialogue must not be filtered.

Verified on MILF Obsession 0.5.0 (Ren'Py 8.5.2): Ren'Py reported 3109 missing
Turkish dialogue translations; after these fixes 510 (≈505 are "...", "I—").

* "menu name:" is a label (renpy/parser.py menu_statement emits ast.Label).
* A say statement used as a menu caption is stored with "nointeract".
* Ren'Py's lexer collapses runs of spaces in string literals before hashing.
* Everyday English tripped code/path heuristics: "empty", "input", "uniform",
  "class", "None at all", "in return", "for her in my room", "and/or", "24/7",
  "Awww...", "and...".
"""
import hashlib
import re

import pytest

from src.core.parser import RenPyParser
from src.core.pipeline.extraction import collapse_source_whitespace, encode_say_string_for_tlid
from src.core.tl_parser import TLParser
from src.utils.config import ConfigManager


def _renpy_id(label, who, what, nointeract=False):
    code = f'{who} "{encode_say_string_for_tlid(collapse_source_whitespace(what))}"'
    if nointeract:
        code += " nointeract"
    return f"{label}_{hashlib.md5((code + chr(13) + chr(10)).encode('utf-8')).hexdigest()[:8]}"


SCRIPT = '''label scene_one:
    m "Before the menu."
    menu pick_name:
        "Honey":
            $ name = "Honey"
        "Master":
            $ name = "Master"
    na "Please... [name]... let me inside already."
    menu:
        na "What do you want?"
        "Coffee":
            m "Coffee, please."
        "Tea":
            pass
    ca "Perfect!  Catch ya later!"
'''


@pytest.fixture
def entries(tmp_path):
    path = tmp_path / "game" / "s.rpy"
    path.parent.mkdir()
    path.write_text(SCRIPT, encoding="utf-8")
    return RenPyParser(ConfigManager()).extract_with_deep_scan(str(path), False, include_ast_scan=False)


def _labels(entry):
    return [p for p in entry.get("context_path", []) if p.lower().startswith("label:")]


def test_named_menu_becomes_the_active_label(entries):
    before = next(e for e in entries if e["text"] == "Before the menu.")
    after = next(e for e in entries if e["text"].startswith("Please..."))
    assert _labels(before)[-1].endswith("scene_one")
    assert _labels(after)[-1].endswith("pick_name")


def test_menu_caption_is_marked_and_choice_dialogue_is_not(entries):
    caption = next(e for e in entries if e["text"] == "What do you want?")
    inside_choice = next(e for e in entries if e["text"] == "Coffee, please.")
    assert caption.get("menu_caption") is True
    assert not inside_choice.get("menu_caption")


def test_generated_ids_match_renpy(tmp_path, entries):
    from src.core.pipeline.extraction import generate_native_tlid_content

    for e in entries:
        e.setdefault("file_path", str(tmp_path / "game" / "s.rpy"))
    content = generate_native_tlid_content(entries, str(tmp_path / "game"), target_language="turkish")
    ids = set(re.findall(r"^translate turkish (\w+):", content, re.M))
    assert _renpy_id("pick_name", "na", "Please... [name]... let me inside already.") in ids
    assert _renpy_id("pick_name", "na", "What do you want?", nointeract=True) in ids
    assert _renpy_id("pick_name", "ca", "Perfect!  Catch ya later!") in ids
    assert 'na "" nointeract' in content


def test_collapse_matches_renpy_lexer():
    # Verified against Ren'Py 8.5.2: dia12_cafeteria_manha_62efc2e1
    assert collapse_source_whitespace("Perfect!  Catch ya later!") == "Perfect! Catch ya later!"
    assert hashlib.md5(('ca "' + collapse_source_whitespace("Perfect!  Catch ya later!") + '"\r\n')
                       .encode("utf-8")).hexdigest()[:8] == "62efc2e1"


@pytest.mark.parametrize("line,text,tail", [
    ('# m "What now?" nointeract', "What now?", " nointeract"),
    ('m "" nointeract', "", " nointeract"),
    ('m "Hi" with dissolve', "Hi", " with dissolve"),
    ('m "He said \\"go\\" now"', 'He said \\"go\\" now', ""),
])
def test_tl_parser_keeps_say_tails(line, text, tail):
    p = TLParser()
    m = p._dialogue_comment_re.match(line) or p._dialogue_line_re.match(line)
    assert m and m.group("text") == text and (m.group("tail") or "") == tail


DIALOGUE = [
    "Oh! And look—I came prepared! I brought the uniform!",
    "There’s an empty glass on the floor.",
    "Thanks for your input.",
    "Close your eyes… Remember, there’s no judgment here. None at all…",
    "...no, Mia, like I said: the extra class isn’t mandatory. If you want to do it, do it. If you don’t, don’t.",
    "{i}(They’d do anything for that affection… and what do they get in return? Cruelty.){/i}",
    "I wish! But thanks for believing in me... At least somebody does!",
    "Then she’ll probably come home earlier today... you can come upstairs and wait for her in my room.",
    "Awww... That just means the universe is being mean to you right now.",
    "He works 24/7 and/or sleeps.",
    "We are open 24/7 for you.",
    "and...",
    "yes....",
    # Menu choices that start with a Ren'Py statement word
    "Call her naughty",
    "Show me",
    "Hide behind the door",
    "Play with her",
    "Jump in the pool",
    "Scene of the crime",
    # Sound effects in asterisk emphasis (Edge of Desire)
    "{font=animeace.ttf}{size=50}*Buzz* *Buzz* *Buzz*{/size}{/font}",
    "*Knock* *Knock* *Knock*",
    # "X in Y" with a full stop looked like "obj.attr in list" (Den of the Defiant,
    # Willing Temptations); "=" in status text looked like an assignment.
    "Maybe in time.",
    "But in the end, she couldn't escape me.",
    "Keep in mind.",
    "Cum in her mouth.",
    "[povname]... I'm...",
    "{color=#b0eb42ff}Dorothan's Continuance = Yes{/color}",
]
CODE = [
    "uniform vec4 u_color;",
    "vec3(1.0, 0.0, 0.0)",
    "class Foo(object):\n    pass",
    "def run(self, x):\n    return x",
    "if x is None:\n    return False",
    "for item in inventory:\n    renpy.notify(item)",
    "config.name",
    "jump chapter_two",
    "show eileen happy",
    "call splash_screen",
    "score = 10",
    "a == b",
    "hp >= 10",
    "audio/bgm.ogg",
    "images/bg/room.png",
    "Visit https://example.com today",
    "empty",
]


@pytest.mark.parametrize("text", DIALOGUE)
def test_dialogue_is_kept(text):
    from src.core.output_formatter import RenPyOutputFormatter

    assert RenPyParser(ConfigManager()).is_meaningful_text(text)
    assert not RenPyOutputFormatter()._should_skip_translation(text)


@pytest.mark.parametrize("text", CODE)
def test_code_and_paths_are_still_rejected(text):
    assert not RenPyParser(ConfigManager()).is_meaningful_text(text)


def test_say_tail_is_part_of_the_id_and_kept_on_the_translated_line(tmp_path):
    from src.core.pipeline.extraction import generate_native_tlid_content

    path = tmp_path / "game" / "t.rpy"
    path.parent.mkdir()
    path.write_text(
        'label shake:\n'
        '    e "Ouch!" with vpunch\n'
        '    e "Slowly." with Dissolve(0.5, alpha=True)\n'
        '    e "Wait here." nointeract\n',
        encoding="utf-8",
    )
    entries = RenPyParser(ConfigManager()).extract_with_deep_scan(str(path), False, include_ast_scan=False)
    for e in entries:
        e.setdefault("file_path", str(path))
    content = generate_native_tlid_content(entries, str(tmp_path / "game"), target_language="turkish")
    ids = set(re.findall(r"^translate turkish (\w+):", content, re.M))

    def rid(code):
        return "shake_" + hashlib.md5((code + "\r\n").encode("utf-8")).hexdigest()[:8]

    assert rid('e "Ouch!" with vpunch') in ids
    assert rid('e "Slowly." with Dissolve(0.5, alpha=True)') in ids
    assert rid('e "Wait here." nointeract') in ids
    assert '    e "" with vpunch' in content
    assert '    e "" with Dissolve(0.5, alpha=True)' in content
    assert '    e "" nointeract' in content


def test_rpyc_say_keeps_nointeract_and_with():
    from src.core.pipeline.extraction import generate_native_tlid_content
    from src.core.rpyc_reader import ASTTextExtractor, FakeLabel, FakeSay

    label = FakeLabel()
    label.name = "pick"
    caption = FakeSay()
    caption.who, caption.what, caption.linenumber = "na", "What do you want?", 5
    caption.interact = False
    caption.identifier = "pick_0a1b2c3d"
    shake = FakeSay()
    shake.who, shake.what, shake.linenumber = "e", "Ouch!", 6
    shake.with_ = "vpunch"
    shake.identifier = "pick_4e5f6a7b"
    label.block = [caption, shake]

    extractor = ASTTextExtractor()
    extractor._walk_nodes([label], context="file:t.rpy")
    tails = {t.text: t.say_tail for t in extractor.extracted}
    assert tails == {"What do you want?": " nointeract", "Ouch!": " with vpunch"}

    entries = [{
        "text": t.text, "character": t.character, "type": "dialogue", "text_type": "dialogue",
        "context_path": [t.context], "context": t.context, "identifier": t.identifier or "",
        "say_tail": t.say_tail, "file_path": "t.rpy", "line_number": t.line_number,
    } for t in extractor.extracted]
    content = generate_native_tlid_content(entries, ".", target_language="turkish")
    assert '    na "" nointeract' in content
    assert '    e "" with vpunch' in content


def test_marked_strings_in_label_call_arguments_are_extracted(tmp_path):
    path = tmp_path / "game" / "c.rpy"
    path.parent.mkdir()
    path.write_text(
        'label start:\n'
        '    call splash_message(_("Chapter 5")) from _call_splash_message_23\n'
        '    call splash_message(_("Later that evening...")) from _call_splash_message_25\n'
        '    call chapter_two\n'
        '    call screen pick("x")\n',
        encoding="utf-8",
    )
    texts = {e["text"] for e in RenPyParser(ConfigManager()).extract_with_deep_scan(str(path), False, include_ast_scan=False)}
    assert {"Chapter 5", "Later that evening..."} <= texts
    assert "chapter_two" not in texts and "_call_splash_message_23" not in texts


def test_quoted_speaker_keeps_its_quotes_in_id_and_line(tmp_path):
    """'"Agent" "..."' is a say statement with a string speaker. Ren'Py hashes
    it with the quotes; written as 'Agent "..."' the line would also name an
    undefined variable (NameError). Verified on Edge of Desire (Ren'Py 8.5.3)."""
    from src.core.pipeline.extraction import generate_native_tlid_content

    path = tmp_path / "game" / "q.rpy"
    path.parent.mkdir()
    path.write_text(
        'label ch2_park:\n'
        '    "Shop Owner" "Hey you two! Can I interest you in some ice cream?"\n'
        '    "Agent" "One false move and you\'re done!"\n'
        '    "[alex_name] and [tyler_name]" "Thank You!"\n',
        encoding="utf-8",
    )
    entries = RenPyParser(ConfigManager()).extract_with_deep_scan(str(path), False, include_ast_scan=False)
    for e in entries:
        e.setdefault("file_path", str(path))
    content = generate_native_tlid_content(entries, str(tmp_path / "game"), target_language="turkish")
    ids = set(re.findall(r"^translate turkish (\w+):", content, re.M))
    assert "ch2_park_97776363" in ids          # Ren'Py's own id for the Shop Owner line
    assert _renpy_id("ch2_park", '"Agent"', "One false move and you're done!") in ids
    assert _renpy_id("ch2_park", '"[alex_name] and [tyler_name]"', "Thank You!") in ids
    assert '    "Agent" ""' in content and '\n    Agent ' not in content
    assert 'old "Thank You!"' not in content


def test_narrated_menu_question_is_also_a_string(entries, tmp_path):
    from src.core.pipeline.extraction import generate_native_tlid_content

    for e in entries:
        e.setdefault("file_path", str(tmp_path / "game" / "s.rpy"))
    path = tmp_path / "game" / "m.rpy"
    path.write_text(
        'label pick:\n    menu:\n        "Keep going or stop?"\n'
        '        "Keep going":\n            pass\n',
        encoding="utf-8",
    )
    more = RenPyParser(ConfigManager()).extract_with_deep_scan(str(path), False, include_ast_scan=False)
    for e in more:
        e.setdefault("file_path", str(path))
    content = generate_native_tlid_content(entries + more, str(tmp_path / "game"), target_language="turkish")
    assert '# "Keep going or stop?" nointeract' in content     # the say block
    assert 'old "Keep going or stop?"' in content               # and the choice-screen caption
    assert 'old "What do you want?"' not in content             # a spoken question stays dialogue only
