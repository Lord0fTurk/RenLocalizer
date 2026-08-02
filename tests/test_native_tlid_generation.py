"""
Tests for Native TLID generation (src/core/pipeline/extraction.py).

Covers two fixes:
1. When a .rpyc-sourced entry already carries the real Ren'Py-assigned
   translate `identifier` (unpickled from the compiled AST), it must be used
   verbatim instead of recomputing an approximate MD5 hash.
2. When no real identifier is available (.rpy source, not yet compiled), the
   fallback hash must escape the dialogue text the same way Ren'Py's own
   `encode_say_string()` does, so quotes/backslashes/newlines don't silently
   break the id.
"""
import hashlib
import re

from src.core.pipeline.extraction import (
    generate_native_tlid_content,
    encode_say_string_for_tlid,
)


def _generate(entries, tmp_path):
    return generate_native_tlid_content(
        entries,
        game_dir=str(tmp_path),
        target_language="turkish",
        source_language="english",
        engine=None,
        translation_manager=None,
        config=None,
        lang_name="turkish",
    )


def _extract_tlids(content):
    return [
        line.split()[-1].rstrip(":")
        for line in content.splitlines()
        if line.startswith("translate turkish ")
    ]


# ---------------------------------------------------------------------------
# Ground-truth reference, transcribed verbatim from Ren'Py's own source
# (fetched directly from github.com/renpy/renpy master, not derived from our
# own implementation) so this test can't pass merely because it agrees with
# itself:
#   renpy/translation/__init__.py -> encode_say_string():
#       s = s.replace("\\", "\\\\")
#       s = s.replace("\n", "\\n")
#       s = s.replace('"', '\\"')
#       s = re.sub(r"(?<= ) ", "\\ ", s)
#       return '"' + s + '"'
#   renpy/translation/__init__.py -> Restructurer.create_translate():
#       md5.update((say.get_code() + "\r\n").encode("utf-8"))
#       digest = md5.hexdigest()[:8]
#       identifier = label.replace(".", "_") + "_" + digest   # unique_identifier()
#   renpy/ast.py -> Say.get_code() (who/what only, no attrs/id/with/args):
#       rv = [self.who] if self.who else []
#       rv.append(encode_say_string(what))
#       " ".join(rv)
# ---------------------------------------------------------------------------
def _reference_renpy_encode_say_string(s: str) -> str:
    s = s.replace("\\", "\\\\")
    s = s.replace("\n", "\\n")
    s = s.replace('"', '\\"')
    s = re.sub(r"(?<= ) ", "\\ ", s)
    return '"' + s + '"'


def _reference_renpy_tlid(label: str, who: str, text: str) -> str:
    code_parts = [who] if who else []
    code_parts.append(_reference_renpy_encode_say_string(text))
    code = " ".join(code_parts)
    digest = hashlib.md5((code + "\r\n").encode("utf-8")).hexdigest()[:8]
    return f"{label}_{digest}"


def test_reference_encode_say_string_is_self_consistent():
    """Sanity-check the inlined reference before using it to grade our code."""
    assert _reference_renpy_encode_say_string("hi") == '"hi"'
    assert _reference_renpy_encode_say_string('He said "hi"') == '"He said \\"hi\\""'


def test_fallback_hash_matches_renpy_reference_algorithm_no_who(tmp_path):
    text = 'She said "hi"\nwith a backslash \\ and  double space'
    entries = [{"text": text, "text_type": "dialogue", "character": ""}]
    content = _generate(entries, tmp_path)
    tlids = _extract_tlids(content)
    assert len(tlids) == 1
    assert tlids[0] == _reference_renpy_tlid("start", "", text)


def test_fallback_hash_matches_renpy_reference_algorithm_with_who(tmp_path):
    text = "Hello there"
    entries = [{"text": text, "text_type": "dialogue", "character": "e"}]
    content = _generate(entries, tmp_path)
    tlids = _extract_tlids(content)
    assert len(tlids) == 1
    assert tlids[0] == _reference_renpy_tlid("start", "e", text)


def test_real_identifier_is_used_verbatim(tmp_path):
    """A .rpyc-sourced entry with a ground-truth identifier must bypass hashing."""
    entries = [
        {
            "text": "Hello, world!",
            "text_type": "dialogue",
            "character": "e",
            "file_path": str(tmp_path / "script.rpyc"),
            "is_rpyc": True,
            "identifier": "start_1a2b3c4d",
        }
    ]
    content = _generate(entries, tmp_path)
    tlids = _extract_tlids(content)
    assert tlids == ["start_1a2b3c4d"]
    # It must NOT equal what the hash fallback would have produced (proves
    # the real identifier path, not a coincidental hash match, was taken).
    assert tlids[0] != _reference_renpy_tlid("start", "e", "Hello, world!")


def test_missing_identifier_falls_back_to_hash(tmp_path):
    """Entries without a real identifier still get an auto-generated hash id."""
    entries = [
        {
            "text": "Hello there",
            "text_type": "dialogue",
            "character": "e",
            "file_path": str(tmp_path / "script.rpy"),
        }
    ]
    content = _generate(entries, tmp_path)
    assert "translate turkish start_" in content


def test_fallback_hash_differs_for_text_with_quotes_vs_without(tmp_path):
    """Escaping bug regression: quotes must affect the hash (distinct ids)."""
    entries = [
        {"text": 'She said "hi"', "text_type": "dialogue", "character": "e"},
        {"text": "She said hi", "text_type": "dialogue", "character": "e"},
    ]
    content = _generate(entries, tmp_path)
    ids = _extract_tlids(content)
    assert len(ids) == 2
    assert ids[0] != ids[1]
    assert ids[0] == _reference_renpy_tlid("start", "e", 'She said "hi"')
    assert ids[1] == _reference_renpy_tlid("start", "e", "She said hi")


def test_collision_suffix_applies_to_both_real_and_hashed_ids(tmp_path):
    """Two distinct source texts colliding on the same id must get _1, _2 suffixes."""
    entries = [
        {"text": "Line one", "text_type": "dialogue", "character": "e", "identifier": "start_dupe"},
        {"text": "Line two", "text_type": "dialogue", "character": "e", "identifier": "start_dupe"},
    ]
    content = _generate(entries, tmp_path)
    tlids = _extract_tlids(content)
    assert tlids == ["start_dupe", "start_dupe_1"]


def test_encode_say_string_for_tlid_matches_renpy_semantics():
    """Mirrors Ren'Py's encode_say_string(): backslash, newline, quote, double-space."""
    assert encode_say_string_for_tlid('He said "hi"') == 'He said \\"hi\\"'
    assert encode_say_string_for_tlid("back\\slash") == "back\\\\slash"
    assert encode_say_string_for_tlid("line\nbreak") == "line\\nbreak"
    assert encode_say_string_for_tlid("two  spaces") == "two \\ spaces"
    assert encode_say_string_for_tlid("") == ""


def test_encode_say_string_for_tlid_matches_reference_on_combined_input():
    """Cross-check our helper against the independently-transcribed reference,
    for an input exercising all four rules at once (backslash, newline, quote,
    double-space), in the exact order Ren'Py applies them."""
    text = 'quote:" back\\slash\nnewline  doublespace'
    ours = encode_say_string_for_tlid(text)
    reference = _reference_renpy_encode_say_string(text).strip('"')
    assert ours == reference

    assert encode_say_string_for_tlid("two  spaces") == "two \\ spaces"
    assert encode_say_string_for_tlid("") == ""
