# -*- coding: utf-8 -*-
"""A .rpyc keeps the script twice; Ren'Py reads slot 2 (TranslateSay nodes with the
real ids and the full say statement) first, so the reader has to as well."""
import pickle
import struct
import sys
import types
import zlib

import pytest

from src.core.rpyc_reader import ASTTextExtractor, extract_texts_from_rpyc, read_rpyc_file
from src.core.tl_parser import TLParser


def _ast_module():
    mod = types.ModuleType("renpy.ast")

    class _Node:
        def __init__(self, **state):
            self.__dict__.update(state)

    for name in ("Say", "TranslateSay", "Label"):
        cls = type(name, (_Node,), {"__module__": "renpy.ast"})
        setattr(mod, name, cls)
    return mod


@pytest.fixture
def ast():
    mod = _ast_module()
    sys.modules["renpy.ast"] = mod
    sys.modules.setdefault("renpy", types.ModuleType("renpy"))
    yield mod
    sys.modules.pop("renpy.ast", None)


def _write_rpyc(path, slot1, slot2):
    blobs = [zlib.compress(pickle.dumps(({"version": 1, "key": "unlocked"}, s), protocol=2)) for s in (slot1, slot2)]
    header = b"RENPY RPC2"
    table_len = 12 * 3
    start1 = len(header) + table_len
    start2 = start1 + len(blobs[0])
    table = struct.pack("<III", 1, start1, len(blobs[0])) + struct.pack("<III", 2, start2, len(blobs[1])) + struct.pack("<III", 0, 0, 0)
    path.write_bytes(header + table + blobs[0] + blobs[1])


def _say(ast, cls, **kw):
    state = dict(linenumber=10, filename="game/a.rpy", who="gwen_side", who_fast=True, what="Hello there, how are you today?")
    state.update(kw)
    return getattr(ast, cls)(**state)


def test_slot_2_is_read_first_and_carries_the_real_id(ast, tmp_path):
    plain = _say(ast, "Say")
    wrapped = _say(ast, "TranslateSay", identifier="start_1a2b3c4d", attributes=("talk", "laugh03"), interact=False)
    f = tmp_path / "a.rpyc"
    _write_rpyc(f, [plain], [wrapped])
    entries = extract_texts_from_rpyc(str(f))
    assert [e["identifier"] for e in entries] == ["start_1a2b3c4d"]
    assert entries[0]["say_attrs"] == " talk laugh03"
    assert entries[0]["say_tail"] == " nointeract"


def test_unreadable_slot_2_falls_back_to_slot_1(ast, tmp_path):
    plain = _say(ast, "Say")
    f = tmp_path / "a.rpyc"
    _write_rpyc(f, [plain], [plain])
    data = bytearray(f.read_bytes())
    data[-5:] = b"\x00\x00\x00\x00\x00"           # damage the end of slot 2
    f.write_bytes(bytes(data))
    nodes = read_rpyc_file(str(f))
    assert nodes and getattr(nodes[0], "what", "").startswith("Hello there")


class _Args:
    def __init__(self, arguments, starred=(), double=()):
        self.arguments = arguments
        self.starred_indexes = set(starred)
        self.doublestarred_indexes = set(double)


@pytest.mark.parametrize("args,code", [
    (_Args([("multiple", "2")]), "(multiple=2)"),
    (_Args([(None, "'x'"), ("what_color", "'#fff'")]), "('x', what_color='#fff')"),
    (_Args([(None, "items")], starred=[0]), "(*items)"),
    (None, ""),
    (_Args([]), ""),
])
def test_arguments_code_matches_renpy(args, code):
    assert ASTTextExtractor._arguments_code(args) == code


def test_say_code_parts_follow_get_code_order():
    node = types.SimpleNamespace(
        attributes=("sly",), temporary_attributes=("blush",), interact=False,
        identifier="my_id", explicit_identifier=True,
        arguments=_Args([("multiple", "2")]), with_="dissolve")
    attrs, tail = ASTTextExtractor._say_code_parts(node)
    assert attrs == " sly @ blush"
    assert tail == " nointeract id my_id (multiple=2) with dissolve"


def test_plain_say_has_no_extra_code():
    node = types.SimpleNamespace(attributes=None, temporary_attributes=None, interact=True,
                                 identifier=None, explicit_identifier=False, arguments=None, with_=None)
    assert ASTTextExtractor._say_code_parts(node) == ("", "")


def test_tl_parser_reads_back_a_line_with_arguments(tmp_path):
    f = tmp_path / "t.rpy"
    f.write_text(
        'translate turkish start_1a2b3c4d:\n\n    # protag "No." (multiple=2)\n    protag "" (multiple=2)\n',
        encoding="utf-8")
    tl = TLParser().parse_file(str(f))
    assert tl and len(tl.entries) == 1
    assert tl.entries[0].original_text == "No."
