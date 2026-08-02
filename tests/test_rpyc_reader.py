"""
Comprehensive tests for rpyc_reader.py — Ren'Py compiled script (.rpyc) AST reader.

Covers:
  - FakeModuleRegistry registration and class lookup
  - FakePyExpr string subclass behavior
  - FakeASTBase and all fake node classes
  - RpycHeader dataclass and read_rpyc_header()
  - RenpyUnpickler.find_class() class mapping and security
  - ASTTextExtractor._process_node for Say, Menu, Translate, TranslateString,
    If, Python, Bubble, Testcase, Label, Init, Screen, Define, Default, and more
  - extract_texts_from_rpyc() and extract_texts_from_rpyc_directory() public API
  - read_rpyc_file() basic flow (mocked)
  - FakeOrderedDict, FakeRevertableList/Dict/Set helper containers
"""

import collections
import io
import logging
import pickle
import struct
import tempfile
import zlib
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from src.core.rpyc_reader import (
    ASTTextExtractor,
    ExtractedText,
    FakeASTBase,
    FakeBubble,
    FakeConfirm,
    FakeHelp,
    FakeIf,
    FakeLabel,
    FakeMenu,
    FakeModuleRegistry,
    FakeNotify,
    FakeOrderedDict,
    FakePython,
    FakePyCode,
    FakePyExpr,
    FakeRevertableDict,
    FakeRevertableList,
    FakeRevertableSet,
    FakeSay,
    FakeScreen,
    FakeSentinel,
    FakeSLDisplayable,
    FakeSLScreen,
    FakeTranslate,
    FakeTranslateBlock,
    FakeTranslateSay,
    FakeTranslateString,
    FakeTestcase,
    FakeTooltip,
    RenpyUnpickler,
    RpycHeader,
    RpycReadError,
    extract_texts_from_rpyc,
    extract_texts_from_rpyc_directory,
    read_rpyc_file,
    read_rpyc_header,
)

# ──────────────────────────────────────────────────────────────
# Helper
# ──────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────
# FakeModuleRegistry
# ──────────────────────────────────────────────────────────────


class TestFakeModuleRegistry:
    def test_register_and_retrieve_module(self):
        FakeModuleRegistry.register_module("dummy", {"key": 42})
        assert FakeModuleRegistry._modules["dummy"] == {"key": 42}

    def test_register_and_retrieve_class(self):
        class MyFake:
            pass
        FakeModuleRegistry.register_class("pkg.Cls", MyFake)
        assert FakeModuleRegistry.get_class("pkg", "Cls") is MyFake

    def test_get_class_miss_returns_none(self):
        assert FakeModuleRegistry.get_class("nonexistent", "Module") is None

    def test_register_module_overwrites_previous(self):
        FakeModuleRegistry.register_module("test", 1)
        FakeModuleRegistry.register_module("test", 2)
        assert FakeModuleRegistry._modules["test"] == 2


# ──────────────────────────────────────────────────────────────
# FakePyExpr (string subclass)
# ──────────────────────────────────────────────────────────────


class TestFakePyExpr:
    def test_is_string_subclass(self):
        expr = FakePyExpr("hello")
        assert isinstance(expr, str)
        assert expr == "hello"

    def test_custom_attributes(self):
        expr = FakePyExpr("text", filename="script.rpy", linenumber=42)
        assert expr.filename == "script.rpy"
        assert expr.linenumber == 42
        assert expr.py is None
        assert expr.hashcode is None
        assert expr.col_offset == 0

    def test_default_attributes(self):
        expr = FakePyExpr("bare")
        assert expr.filename == ""
        assert expr.linenumber == 0

    def test_getnewargs(self):
        expr = FakePyExpr("abc")
        assert expr.__getnewargs__() == ("abc",)

    def test_reduce(self):
        expr = FakePyExpr("x", filename="f.rpy", linenumber=10)
        reduced = expr.__reduce__()
        assert reduced[0] is FakePyExpr
        assert reduced[1][0] == "x"

    def test_setstate_dict(self):
        expr = FakePyExpr("x")
        expr.__setstate__({"filename": "new.rpy", "extra": True})
        assert expr.filename == "new.rpy"
        assert getattr(expr, "extra") is True

    def test_extra_positional_args_ignored(self):
        expr = FakePyExpr("x", "ignored1", 2, 3, 4, 5)
        assert expr == "x"


# ──────────────────────────────────────────────────────────────
# FakeASTBase & node hierarchy
# ──────────────────────────────────────────────────────────────


class TestFakeASTBase:
    def test_default_attributes(self):
        obj = FakeASTBase()
        assert obj.linenumber == 0
        assert obj.filename == ""

    def test_setstate_dict(self):
        obj = FakeASTBase()
        obj.__setstate__({"linenumber": 99, "filename": "test.rpy"})
        assert obj.linenumber == 99
        assert obj.filename == "test.rpy"

    def test_setstate_tuple_with_dict(self):
        obj = FakeASTBase()
        obj.__setstate__(({"linenumber": 5}, "extra_slot"))
        assert obj.linenumber == 5
        assert obj._extra_state == ({"linenumber": 5}, "extra_slot")

    def test_setstate_tuple_no_dict_preserves_state(self):
        obj = FakeASTBase()
        obj.__setstate__((1, 2, 3))
        assert obj._extra_state == (1, 2, 3)


class TestFakeSay:
    def test_defaults(self):
        node = FakeSay()
        assert node.who is None
        assert node.what == ""
        assert node.interact is True
        assert node.attributes is None

    def test_setstate_populates_attributes(self):
        node = FakeSay()
        node.__setstate__({"who": "Eileen", "what": "Hello!"})
        assert node.who == "Eileen"
        assert node.what == "Hello!"


class TestFakeMenu:
    def test_defaults(self):
        node = FakeMenu()
        assert node.items == []
        assert node.set is None

    def test_setstate_items(self):
        node = FakeMenu()
        node.__setstate__({"items": [("Choice 1", None, [])]})
        assert len(node.items) == 1
        assert node.items[0][0] == "Choice 1"


class TestFakeTranslateSay:
    def test_defaults(self):
        node = FakeTranslateSay()
        assert node.language is None
        assert node.translatable is True
        assert node.translation_relevant is True

    def test_after_property_falls_back_to_next(self):
        node = FakeTranslateSay()
        assert node.after is None
        node.next = 42
        assert node.after == 42

    def test_block_property_returns_empty_list(self):
        node = FakeTranslateSay()
        assert node.block == []


class TestFakePython:
    def test_defaults(self):
        node = FakePython()
        assert node.code is None
        assert node.hide is False
        assert node.store == "store"

    def test_setstate_sets_defaults_before_applying(self):
        node = FakePython()
        node.__setstate__({"code": "x = 1"})
        assert node.code == "x = 1"
        assert node.hide is False
        assert node.store == "store"


class TestFakePyCode:
    def test_defaults(self):
        pyc = FakePyCode()
        assert pyc.source == ""
        assert pyc.location == ()
        assert pyc.mode == "exec"

    def test_setstate_dict(self):
        pyc = FakePyCode()
        pyc.__setstate__({"source": "print('hi')", "location": ("f", 1), "mode": "eval"})
        assert pyc.source == "print('hi')"
        assert pyc.location == ("f", 1)
        assert pyc.mode == "eval"

    def test_setstate_tuple_four_elements(self):
        pyc = FakePyCode()
        pyc.__setstate__((None, "x = 1", ("script.rpy", 10), "exec"))
        assert pyc.source == "x = 1"
        assert pyc.mode == "exec"

    def test_setstate_empty_handled_gracefully(self):
        pyc = FakePyCode()
        pyc.__setstate__([])
        assert pyc.source == ""


class TestFakeTranslate:
    def test_defaults(self):
        node = FakeTranslate()
        assert node.identifier == ""
        assert node.language is None
        assert node.block == []


class TestFakeTranslateString:
    def test_defaults(self):
        node = FakeTranslateString()
        assert node.language is None
        assert node.old == ""
        assert node.new == ""


class TestFakeTranslateBlock:
    def test_defaults(self):
        node = FakeTranslateBlock()
        assert node.language is None
        assert node.block == []


class TestFakeIf:
    def test_defaults(self):
        node = FakeIf()
        assert node.entries == []

    def test_setstate(self):
        node = FakeIf()
        node.__setstate__({"entries": [("cond", [FakeSay()])]})
        assert len(node.entries) == 1


class TestFakeBubble:
    def test_inherits_from_say(self):
        node = FakeBubble()
        assert isinstance(node, FakeSay)
        assert node.properties is None
        assert node.code is None

    def test_setstate_properties(self):
        node = FakeBubble()
        node.__setstate__({"who": "Narrator", "what": "Bubble text", "properties": {"alt": "alt text"}})
        assert node.what == "Bubble text"
        assert node.properties == {"alt": "alt text"}


class TestFakeTestcase:
    def test_defaults(self):
        node = FakeTestcase()
        assert node.label == ""
        assert node.description is None
        assert node.block == []


# ──────────────────────────────────────────────────────────────
# Action helpers
# ──────────────────────────────────────────────────────────────


class TestFakeConfirm:
    def test_setstate_tuple(self):
        c = FakeConfirm()
        c.__setstate__(("Are you sure?", None, None))
        assert c.prompt == "Are you sure?"

    def test_setstate_dict(self):
        c = FakeConfirm()
        c.__setstate__({"prompt": "Really?"})
        assert c.prompt == "Really?"


class TestFakeNotify:
    def test_setstate_tuple(self):
        n = FakeNotify()
        n.__setstate__(("Saved",))
        assert n.message == "Saved"


class TestFakeTooltip:
    def test_setstate_tuple(self):
        t = FakeTooltip()
        t.__setstate__(("Click me",))
        assert t.value == "Click me"


class TestFakeHelp:
    def test_setstate_tuple(self):
        h = FakeHelp()
        h.__setstate__(("This is a help text",))
        assert h.help == "This is a help text"


# ──────────────────────────────────────────────────────────────
# Container helpers
# ──────────────────────────────────────────────────────────────


class TestFakeOrderedDict:
    def test_setstate_standard_dict(self):
        od = FakeOrderedDict()
        od.__setstate__({"a": 1, "b": 2})
        assert od == {"a": 1, "b": 2}

    def test_setstate_tuple_wrapping_dict(self):
        od = FakeOrderedDict()
        od.__setstate__(({"x": 10},))
        assert od == {"x": 10}

    def test_setstate_list_of_pairs(self):
        od = FakeOrderedDict()
        od.__setstate__([("k", "v"), ("k2", "v2")])
        assert od == {"k": "v", "k2": "v2"}

    def test_setstate_flat_list(self):
        od = FakeOrderedDict()
        od.__setstate__(["key1", "val1", "key2", "val2"])
        assert od == {"key1": "val1", "key2": "val2"}

    def test_setstate_empty(self):
        od = FakeOrderedDict()
        od.__setstate__([])
        assert od == {}


class TestFakeRevertableList:
    def test_is_list(self):
        rl = FakeRevertableList([1, 2, 3])
        assert isinstance(rl, list)
        assert rl == [1, 2, 3]


class TestFakeRevertableDict:
    def test_is_dict(self):
        rd = FakeRevertableDict(a=1, b=2)
        assert isinstance(rd, dict)
        assert rd["a"] == 1


class TestFakeRevertableSet:
    def test_is_set(self):
        rs = FakeRevertableSet([1, 2])
        assert isinstance(rs, set)
        assert rs == {1, 2}

    def test_setstate_tuple_uses_keys(self):
        rs = FakeRevertableSet()
        rs.__setstate__(({"a": 1, "b": 2},))
        assert rs == {"a", "b"}

    def test_setstate_list(self):
        rs = FakeRevertableSet()
        rs.__setstate__([1, 2, 3])
        assert rs == {1, 2, 3}


class TestFakeSentinel:
    def test_name(self):
        s = FakeSentinel("MySentinel")
        assert s.name == "MySentinel"

    def test_default_name(self):
        s = FakeSentinel()
        assert s.name == ""


# ──────────────────────────────────────────────────────────────
# Screen Language fakes
# ──────────────────────────────────────────────────────────────


class TestFakeSLScreen:
    def test_defaults(self):
        scr = FakeSLScreen()
        assert scr.name == ""
        assert scr.children == []
        assert scr.keyword == []


class TestFakeSLDisplayable:
    def test_defaults(self):
        d = FakeSLDisplayable()
        assert d.displayable is None
        assert d.positional == []
        assert d.children == []

    def test_setstate(self):
        d = FakeSLDisplayable()
        d.__setstate__({"style": "button", "positional": ["Hello"]})
        assert d.style == "button"
        assert d.positional == ["Hello"]


# ──────────────────────────────────────────────────────────────
# RpycHeader
# ──────────────────────────────────────────────────────────────


class TestRpycHeader:
    def test_dataclass_fields(self):
        h = RpycHeader(version=2, slot_count=1, slots={1: (0, 100)})
        assert h.version == 2
        assert h.slot_count == 1
        assert h.slots == {1: (0, 100)}

    def test_v1_defaults(self):
        h = RpycHeader(version=1, slot_count=0, slots={})
        assert h.version == 1
        assert h.slot_count == 0
        assert h.slots == {}


# ──────────────────────────────────────────────────────────────
# read_rpyc_header
# ──────────────────────────────────────────────────────────────


class TestReadRpycHeader:
    def test_v1_fallback_when_no_rpc2_magic(self):
        data = b"some random compressed data"
        header = read_rpyc_header(data)
        assert header.version == 1
        assert header.slot_count == 0
        assert header.slots == {}

    def test_v2_with_single_slot(self):
        slot_id = 1
        start = 100
        length = 200
        entry = struct.pack("<III", slot_id, start, length)
        terminator = struct.pack("<III", 0, 0, 0)
        data = b"RENPY RPC2" + entry + terminator
        header = read_rpyc_header(data)
        assert header.version == 2
        assert header.slot_count == 1
        assert header.slots == {1: (start, length)}

    def test_v2_with_multiple_slots(self):
        entries = b""
        entries += struct.pack("<III", 1, 10, 50)
        entries += struct.pack("<III", 2, 60, 120)
        entries += struct.pack("<III", 0, 0, 0)
        data = b"RENPY RPC2" + entries
        header = read_rpyc_header(data)
        assert header.version == 2
        assert header.slot_count == 2
        assert header.slots == {1: (10, 50), 2: (60, 120)}

    def test_rpc3_magic_treated_as_v2(self):
        """RPC3 magic should be parsed using the same slot structure."""
        slot_id = 1
        entry = struct.pack("<III", slot_id, 10, 50)
        terminator = struct.pack("<III", 0, 0, 0)
        data = b"RENPY RPC3" + entry + terminator
        header = read_rpyc_header(data)
        assert header.version == 2
        assert header.slots == {1: (10, 50)}

    def test_v2_truncated_no_valid_slots(self):
        """If data is too short for any slot entry, still returns v2 with empty slots."""
        data = b"RENPY RPC2" + b"\x00" * 3
        header = read_rpyc_header(data)
        assert header.version == 2
        assert header.slots == {}


# ──────────────────────────────────────────────────────────────
# RenpyUnpickler
# ──────────────────────────────────────────────────────────────


class TestRenpyUnpicklerFindClass:
    def test_maps_renpy_ast_say(self):
        up = RenpyUnpickler(io.BytesIO())
        cls = up.find_class("renpy.ast", "Say")
        assert cls is FakeSay

    def test_maps_renpy_ast_menu(self):
        up = RenpyUnpickler(io.BytesIO())
        cls = up.find_class("renpy.ast", "Menu")
        assert cls is FakeMenu

    def test_maps_renpy_ast_pyexpr(self):
        up = RenpyUnpickler(io.BytesIO())
        cls = up.find_class("renpy.ast", "PyExpr")
        assert cls is FakePyExpr

    def test_maps_renpy_ast_earlypython(self):
        up = RenpyUnpickler(io.BytesIO())
        cls = up.find_class("renpy.ast", "EarlyPython")
        assert issubclass(cls, FakePython)

    def test_maps_renpy_ast_translatestring(self):
        up = RenpyUnpickler(io.BytesIO())
        cls = up.find_class("renpy.ast", "TranslateString")
        assert cls is FakeTranslateString

    def test_maps_renpy_sl2_screen(self):
        up = RenpyUnpickler(io.BytesIO())
        cls = up.find_class("renpy.sl2.slast", "SLScreen")
        assert cls is FakeSLScreen

    def test_maps_renpy_sl2_displayable(self):
        up = RenpyUnpickler(io.BytesIO())
        cls = up.find_class("renpy.sl2.slast", "SLDisplayable")
        assert cls is FakeSLDisplayable

    def test_maps_renpy_revertable_list(self):
        up = RenpyUnpickler(io.BytesIO())
        cls = up.find_class("renpy.revertable", "RevertableList")
        assert cls is FakeRevertableList

    def test_maps_renpy_revertable_dict(self):
        up = RenpyUnpickler(io.BytesIO())
        cls = up.find_class("renpy.revertable", "RevertableDict")
        assert cls is FakeRevertableDict

    def test_maps_collections_ordereddict(self):
        up = RenpyUnpickler(io.BytesIO())
        cls = up.find_class("collections", "OrderedDict")
        assert cls is FakeOrderedDict

    def test_maps_safe_builtins(self):
        up = RenpyUnpickler(io.BytesIO())
        assert up.find_class("builtins", "set") is set
        assert up.find_class("builtins", "dict") is dict
        assert up.find_class("builtins", "str") is str
        assert up.find_class("builtins", "int") is int

    def test_maps_python2_builtin_set(self):
        up = RenpyUnpickler(io.BytesIO())
        assert up.find_class("__builtin__", "set") is set
        assert up.find_class("__builtin__", "unicode") is str

    def test_unknown_renpy_class_returns_fakegeneric(self):
        up = RenpyUnpickler(io.BytesIO())
        from src.core.rpyc_reader import FakeGeneric
        cls = up.find_class("renpy.something", "UnknownNode")
        assert cls is FakeGeneric

    def test_store_class_returns_fakegeneric(self):
        up = RenpyUnpickler(io.BytesIO())
        from src.core.rpyc_reader import FakeGeneric
        cls = up.find_class("store.user", "MyClass")
        assert cls is FakeGeneric

    def test_disallowed_global_raises_unpickling_error(self):
        up = RenpyUnpickler(io.BytesIO())
        with pytest.raises(pickle.UnpicklingError, match="Disallowed global"):
            up.find_class("os", "system")

    def test_ast_module_nodes(self):
        up = RenpyUnpickler(io.BytesIO())
        import ast
        cls = up.find_class("ast", "Constant")
        assert cls is ast.Constant

    def test_confirm_actions_ui(self):
        up = RenpyUnpickler(io.BytesIO())
        assert up.find_class("renpy.ui", "Confirm") is FakeConfirm
        assert up.find_class("renpy.store", "Confirm") is FakeConfirm
        assert up.find_class("store", "Confirm") is FakeConfirm

    def test_notify_actions(self):
        up = RenpyUnpickler(io.BytesIO())
        assert up.find_class("renpy.ui", "Notify") is FakeNotify
        assert up.find_class("renpy.store", "Notify") is FakeNotify
        assert up.find_class("store", "Notify") is FakeNotify

    def test_tooltip_actions(self):
        up = RenpyUnpickler(io.BytesIO())
        assert up.find_class("renpy.ui", "Tooltip") is FakeTooltip

    def test_help_actions(self):
        up = RenpyUnpickler(io.BytesIO())
        assert up.find_class("renpy.ui", "Help") is FakeHelp

    def test_maps_renpy_ast_bubble(self):
        up = RenpyUnpickler(io.BytesIO())
        cls = up.find_class("renpy.ast", "Bubble")
        assert cls is FakeBubble

    def test_maps_renpy_ast_translate(self):
        up = RenpyUnpickler(io.BytesIO())
        cls = up.find_class("renpy.ast", "Translate")
        assert cls is FakeTranslate

    def test_maps_renpy_ast_translateblock(self):
        up = RenpyUnpickler(io.BytesIO())
        cls = up.find_class("renpy.ast", "TranslateBlock")
        assert cls is FakeTranslateBlock

    def test_maps_renpy_ast_if(self):
        up = RenpyUnpickler(io.BytesIO())
        cls = up.find_class("renpy.ast", "If")
        assert cls is FakeIf

    def test_maps_renpy_ast_python(self):
        up = RenpyUnpickler(io.BytesIO())
        cls = up.find_class("renpy.ast", "Python")
        assert cls is FakePython

    def test_maps_renpy_object_sentinel(self):
        up = RenpyUnpickler(io.BytesIO())
        cls = up.find_class("renpy.object", "Sentinel")
        assert cls is FakeSentinel

    def test_maps_slvbar_as_slbar(self):
        up = RenpyUnpickler(io.BytesIO())
        from src.core.rpyc_reader import FakeSLBar
        cls = up.find_class("renpy.sl2.slast", "SLVbar")
        assert cls is FakeSLBar

    def test_maps_atsupport_pyexpr(self):
        up = RenpyUnpickler(io.BytesIO())
        cls = up.find_class("renpy.astsupport", "PyExpr")
        assert cls is FakePyExpr

    def test_maps_parameter_info(self):
        up = RenpyUnpickler(io.BytesIO())
        from src.core.rpyc_reader import FakeParameterInfo
        cls = up.find_class("renpy.parameter", "ParameterInfo")
        assert cls is FakeParameterInfo

    def test_maps_collections_defaultdict(self):
        up = RenpyUnpickler(io.BytesIO())
        cls = up.find_class("collections", "defaultdict")
        assert cls is collections.defaultdict


# ──────────────────────────────────────────────────────────────
# read_rpyc_file (mocked)
# ──────────────────────────────────────────────────────────────


class TestReadRpycFile:
    def test_file_not_found_raises(self, tmp_path: Path):
        nonexistent = tmp_path / "missing.rpyc"
        with pytest.raises(RpycReadError, match="File not found"):
            read_rpyc_file(nonexistent)

    def test_wrong_extension_raises(self, tmp_path: Path):
        f = tmp_path / "script.txt"
        f.write_text("hello")
        with pytest.raises(RpycReadError, match="Not an RPYC file"):
            read_rpyc_file(f)

    def test_v2_no_data_slot_raises(self, tmp_path: Path):
        """V2 header with only slot 0 (terminator) and no valid data slot."""
        entry = struct.pack("<III", 0, 0, 0)
        data = b"RENPY RPC2" + entry
        f = tmp_path / "script.rpyc"
        f.write_bytes(data)
        with pytest.raises(RpycReadError, match="No data slot found"):
            read_rpyc_file(f)

    def test_v1_reads_and_returns_list(self, tmp_path: Path):
        """V1 file: raw zlib-compressed pickle with FakeSay registered in CLASS_MAP."""
        say = FakeSay()
        say.what = "Hello from v1"
        say.linenumber = 5
        payload = (None, [say])
        raw = pickle.dumps(payload, protocol=2)
        compressed = zlib.compress(raw)
        f = tmp_path / "script.rpyc"
        f.write_bytes(compressed)

        saved = RenpyUnpickler.CLASS_MAP.copy()
        try:
            RenpyUnpickler.CLASS_MAP[("src.core.rpyc_reader", "FakeSay")] = FakeSay
            result = read_rpyc_file(f)
            assert isinstance(result, list)
        finally:
            RenpyUnpickler.CLASS_MAP.clear()
            RenpyUnpickler.CLASS_MAP.update(saved)

    def test_v2_reads_with_slot_1(self, tmp_path: Path):
        """V2 file: magic header + slot entry + compressed data."""
        say = FakeSay()
        say.what = "Hello from v2"
        say.linenumber = 3
        payload = (None, [say])
        raw = pickle.dumps(payload, protocol=2)
        compressed = zlib.compress(raw)
        magic = b"RENPY RPC2"
        entry = struct.pack("<III", 1, 10 + 12 + 12, len(compressed))
        terminator = struct.pack("<III", 0, 0, 0)
        data = magic + entry + terminator + compressed
        f = tmp_path / "script.rpyc"
        f.write_bytes(data)

        saved = RenpyUnpickler.CLASS_MAP.copy()
        try:
            RenpyUnpickler.CLASS_MAP[("src.core.rpyc_reader", "FakeSay")] = FakeSay
            result = read_rpyc_file(f)
            assert isinstance(result, list)
        finally:
            RenpyUnpickler.CLASS_MAP.clear()
            RenpyUnpickler.CLASS_MAP.update(saved)

    def test_accepts_rpymc_extension(self, tmp_path: Path):
        """Files with .rpymc suffix are accepted."""
        say = FakeSay()
        payload = (None, [say])
        raw = pickle.dumps(payload, protocol=2)
        compressed = zlib.compress(raw)
        f = tmp_path / "cache.rpymc"
        f.write_bytes(compressed)

        saved = RenpyUnpickler.CLASS_MAP.copy()
        try:
            RenpyUnpickler.CLASS_MAP[("src.core.rpyc_reader", "FakeSay")] = FakeSay
            result = read_rpyc_file(f)
            assert isinstance(result, list)
        finally:
            RenpyUnpickler.CLASS_MAP.clear()
            RenpyUnpickler.CLASS_MAP.update(saved)

    @patch("src.core.rpyc_reader.logger")
    def test_v2_non_standard_magic_logs_warning(self, mock_logger, tmp_path: Path):
        """Non-RPC2 magic that starts with RENPY RPC should log a warning."""
        say = FakeSay()
        payload = (None, [say])
        raw = pickle.dumps(payload, protocol=2)
        compressed = zlib.compress(raw)
        magic = b"RENPY RPC" + b"X"  # 10 bytes: "RENPY RPCX"
        start = 10 + 12 + 12
        entry = struct.pack("<III", 1, start, len(compressed))
        terminator = struct.pack("<III", 0, 0, 0)
        data = magic + entry + terminator + compressed
        f = tmp_path / "script.rpyc"
        f.write_bytes(data)

        saved = RenpyUnpickler.CLASS_MAP.copy()
        try:
            RenpyUnpickler.CLASS_MAP[("src.core.rpyc_reader", "FakeSay")] = FakeSay
            read_rpyc_file(f)
            mock_logger.warning.assert_called()
        finally:
            RenpyUnpickler.CLASS_MAP.clear()
            RenpyUnpickler.CLASS_MAP.update(saved)


# ──────────────────────────────────────────────────────────────
# ASTTextExtractor — _add_text
# ──────────────────────────────────────────────────────────────


class TestAddText:
    def test_empty_text_skipped(self):
        ext = ASTTextExtractor()
        ext._add_text("", 1, "dialogue")
        assert ext.extracted == []

    def test_whitespace_only_skipped(self):
        ext = ASTTextExtractor()
        ext._add_text("   \n  ", 1, "dialogue")
        assert ext.extracted == []

    def test_nvl_character_sets_type(self):
        ext = ASTTextExtractor()
        ext._add_text("Hello", 1, "dialogue", character="narrator_nvl")
        assert ext.extracted[0].text_type == "nvl_dialogue"

    def test_duplicate_preferred_context(self):
        ext = ASTTextExtractor()
        ext._add_text("Hello", 1, "dialogue", context="ctx")
        ext._add_text("Hello", 1, "dialogue", context="ctx2")
        assert len(ext.extracted) == 2

    def test_duplicate_same_context_skipped(self):
        ext = ASTTextExtractor()
        ext._add_text("Hello", 1, "dialogue", context="ctx")
        ext._add_text("Hello", 1, "dialogue", context="ctx")
        assert len(ext.extracted) == 1

    def test_non_meaningful_text_skipped(self):
        ext = ASTTextExtractor()
        ext._add_text("renpy.call_something", 1, "dialogue")
        assert ext.extracted == []

    def test_confidence_below_minimum_skipped(self):
        ext = ASTTextExtractor()
        ext._add_text("a", 1, "dialogue")
        assert ext.extracted == []

    def test_meaningful_dialogue_added(self):
        ext = ASTTextExtractor()
        ext._add_text("Hello world!", 42, "dialogue", character="Eileen", context="label:start")
        assert len(ext.extracted) == 1
        e = ext.extracted[0]
        assert e.text == "Hello world!"
        assert e.line_number == 42
        assert e.text_type == "dialogue"
        assert e.character == "Eileen"
        assert e.context == "label:start"


# ──────────────────────────────────────────────────────────────
# ASTTextExtractor — _process_node
# ──────────────────────────────────────────────────────────────


class TestProcessNodeSay:
    def test_say_dialogue_extracted(self):
        ext = ASTTextExtractor()
        node = FakeSay()
        node.who = "Eileen"
        node.what = "Hello, player!"
        node.linenumber = 10
        ext._process_node(node)
        assert len(ext.extracted) == 1
        assert ext.extracted[0].text == "Hello, player!"
        assert ext.extracted[0].character == "Eileen"
        assert ext.extracted[0].text_type == "dialogue"

    def test_say_empty_what_skipped(self):
        ext = ASTTextExtractor()
        node = FakeSay()
        node.who = "Eileen"
        node.what = ""
        ext._process_node(node)
        assert ext.extracted == []

    def test_translate_say_extracted(self):
        ext = ASTTextExtractor()
        node = FakeTranslateSay()
        node.who = "Narrator"
        node.what = "Translated text"
        node.identifier = "start_abc123"
        ext._process_node(node)
        assert len(ext.extracted) == 1
        assert ext.extracted[0].text == "Translated text"
        assert ext.extracted[0].context == "translate:start_abc123"

    def test_translate_say_default_language_preserves_real_identifier(self):
        """Default-language TranslateSay carries the exact id Ren'Py will look up."""
        ext = ASTTextExtractor()
        node = FakeTranslateSay()
        node.who = "Narrator"
        node.what = "Translated text"
        node.identifier = "start_abc123"
        node.language = None
        ext._process_node(node)
        assert ext.extracted[0].identifier == "start_abc123"

    def test_translate_say_non_default_language_does_not_set_identifier(self):
        """A language-specific TranslateSay must not be mistaken for the source id."""
        ext = ASTTextExtractor()
        node = FakeTranslateSay()
        node.who = "Narrator"
        node.what = "Metin"
        node.identifier = "start_abc123"
        node.language = "turkish"
        ext._process_node(node)
        assert ext.extracted[0].identifier == ""


class TestProcessNodeMenu:
    def test_menu_choices_extracted(self):
        ext = ASTTextExtractor()
        node = FakeMenu()
        node.items = [("Go left", None, []), ("Go right", None, [])]
        node.linenumber = 20
        ext._process_node(node)
        assert len(ext.extracted) == 2
        texts = {e.text for e in ext.extracted}
        assert texts == {"Go left", "Go right"}

    def test_menu_item_block_walked(self):
        ext = ASTTextExtractor()
        say_inside = FakeSay()
        say_inside.what = "You went left."
        node = FakeMenu()
        node.items = [("Go left", None, [say_inside])]
        node.linenumber = 20
        ext._process_node(node)
        texts = {e.text for e in ext.extracted}
        assert "Go left" in texts
        assert "You went left." in texts


class TestProcessNodeTranslate:
    def test_translatestring_extracts_old(self):
        ext = ASTTextExtractor()
        node = FakeTranslateString()
        node.old = "Original string"
        node.linenumber = 5
        ext._process_node(node)
        assert len(ext.extracted) == 1
        assert ext.extracted[0].text == "Original string"
        assert ext.extracted[0].text_type == "string"

    def test_translatestring_empty_old_skipped(self):
        ext = ASTTextExtractor()
        node = FakeTranslateString()
        node.old = ""
        ext._process_node(node)
        assert ext.extracted == []

    def test_translate_walks_block(self):
        ext = ASTTextExtractor()
        say_node = FakeSay()
        say_node.what = "Dialogue in translate"
        translate_node = FakeTranslate()
        translate_node.block = [say_node]
        translate_node.language = "turkish"
        ext._process_node(translate_node)
        assert len(ext.extracted) == 1
        assert ext.extracted[0].text == "Dialogue in translate"

    def test_translate_default_language_propagates_real_identifier(self):
        """The Translate block's own identifier must reach the contained Say node."""
        ext = ASTTextExtractor()
        say_node = FakeSay()
        say_node.what = "Dialogue in translate"
        translate_node = FakeTranslate()
        translate_node.block = [say_node]
        translate_node.language = None
        translate_node.identifier = "start_deadbeef"
        ext._process_node(translate_node)
        assert len(ext.extracted) == 1
        assert ext.extracted[0].identifier == "start_deadbeef"

    def test_translate_non_default_language_does_not_propagate_identifier(self):
        ext = ASTTextExtractor()
        say_node = FakeSay()
        say_node.what = "Diyalog"
        translate_node = FakeTranslate()
        translate_node.block = [say_node]
        translate_node.language = "turkish"
        translate_node.identifier = "start_deadbeef"
        ext._process_node(translate_node)
        assert ext.extracted[0].identifier == ""

    def test_translateblock_walks_block(self):
        ext = ASTTextExtractor()
        ts = FakeTranslateString()
        ts.old = "Style text"
        block_node = FakeTranslateBlock()
        block_node.language = "turkish"
        block_node.block = [ts]
        ext._process_node(block_node)
        assert len(ext.extracted) == 1
        assert ext.extracted[0].text == "Style text"


class TestProcessNodeIf:
    def test_if_entries_walked(self):
        ext = ASTTextExtractor()
        say_node = FakeSay()
        say_node.what = "Conditional text"
        node = FakeIf()
        node.entries = [("x > 0", [say_node])]
        ext._process_node(node)
        assert len(ext.extracted) == 1
        assert ext.extracted[0].text == "Conditional text"


class TestProcessNodePython:
    def test_python_code_obj_processed(self):
        ext = ASTTextExtractor()
        pycode = FakePyCode()
        pycode.source = '_("Translate me")'
        pycode.location = ("script.rpy", 15)
        node = FakePython()
        node.code = pycode
        node.linenumber = 15
        ext._process_node(node)
        assert any("Translate me" == e.text for e in ext.extracted)

    def test_python_no_code_skipped(self):
        ext = ASTTextExtractor()
        node = FakePython()
        node.code = None
        ext._process_node(node)
        assert ext.extracted == []


class TestProcessNodeBubble:
    def test_bubble_extracts_what(self):
        ext = ASTTextExtractor()
        node = FakeBubble()
        node.who = "Narrator"
        node.what = "Bubble text"
        node.linenumber = 30
        ext._process_node(node)
        texts = {e.text for e in ext.extracted}
        assert "Bubble text" in texts

    def test_bubble_properties_extracted_when_meaningful(self):
        ext = ASTTextExtractor()
        node = FakeBubble()
        node.what = "Main text"
        node.properties = {"alt": "Hello world alt text", "tooltip": "Hello tooltip"}
        node.linenumber = 10
        ext._process_node(node)
        assert len(ext.extracted) >= 1

    def test_bubble_no_properties_does_not_crash(self):
        ext = ASTTextExtractor()
        node = FakeBubble()
        node.what = "Hello from bubble"
        node.properties = None
        ext._process_node(node)
        assert len(ext.extracted) >= 1  # at least the what text


class TestProcessNodeTestcase:
    def test_testcase_description_extracted(self):
        ext = ASTTextExtractor()
        node = FakeTestcase()
        node.description = "Test: main menu"
        node.label = "start"
        node.linenumber = 1
        ext._process_node(node)
        assert any("Test: main menu" == e.text for e in ext.extracted)

    def test_testcase_block_walked(self):
        ext = ASTTextExtractor()
        say_node = FakeSay()
        say_node.what = "Testing dialogue"
        node = FakeTestcase()
        node.label = "start"
        node.block = [say_node]
        ext._process_node(node)
        assert any("Testing dialogue" == e.text for e in ext.extracted)


class TestProcessNodeLabel:
    def test_label_walks_block(self):
        ext = ASTTextExtractor()
        say_node = FakeSay()
        say_node.what = "After label"
        node = FakeLabel()
        node.name = "start"
        node.block = [say_node]
        ext._process_node(node)
        assert any("After label" == e.text for e in ext.extracted)


# ──────────────────────────────────────────────────────────────
# ASTTextExtractor — _extract_from_action
# ──────────────────────────────────────────────────────────────


class TestExtractFromAction:
    def test_confirm_action(self):
        ext = ASTTextExtractor()
        action = FakeConfirm()
        action.prompt = "Are you sure?"
        ext._extract_from_action(action, 1, "screen:yesno")
        assert ext.extracted[0].text == "Are you sure?"

    def test_notify_action(self):
        ext = ASTTextExtractor()
        action = FakeNotify()
        action.message = "Game saved."
        ext._extract_from_action(action, 1, "screen")
        assert ext.extracted[0].text == "Game saved."

    def test_help_action(self):
        ext = ASTTextExtractor()
        action = FakeHelp()
        action.help = "Press Space to continue"
        ext._extract_from_action(action, 1, "screen")
        assert ext.extracted[0].text == "Press Space to continue"

    def test_tooltip_action(self):
        ext = ASTTextExtractor()
        action = FakeTooltip()
        action.value = "Tooltip here"
        ext._extract_from_action(action, 1, "screen")
        assert ext.extracted[0].text == "Tooltip here"

    def test_nested_list_of_actions(self):
        ext = ASTTextExtractor()
        actions = [FakeNotify(), FakeConfirm()]
        actions[0].message = "Saved"
        actions[1].prompt = "Overwrite?"
        ext._extract_from_action(actions, 1, "screen")
        texts = {e.text for e in ext.extracted}
        assert texts == {"Saved", "Overwrite?"}


# ──────────────────────────────────────────────────────────────
# ASTTextExtractor — _is_technical_string
# ──────────────────────────────────────────────────────────────


class TestIsTechnicalString:
    def test_pure_number(self):
        ext = ASTTextExtractor()
        assert ext._is_technical_string("123") is True
        assert ext._is_technical_string("-3.14") is True

    def test_file_extensions(self):
        ext = ASTTextExtractor()
        assert ext._is_technical_string("image.png") is True
        assert ext._is_technical_string("bgm.mp3") is True
        assert ext._is_technical_string("font.ttf") is True

    def test_path_prefixes(self):
        ext = ASTTextExtractor()
        assert ext._is_technical_string("images/bg.png") is True
        assert ext._is_technical_string("audio/theme.ogg") is True
        assert ext._is_technical_string("gui/button.png") is True

    def test_hex_color(self):
        ext = ASTTextExtractor()
        assert ext._is_technical_string("#FF0000") is True
        assert ext._is_technical_string("#abc") is True

    def test_snake_case_identifier(self):
        ext = ASTTextExtractor()
        assert ext._is_technical_string("my_variable_name") is True

    def test_python_code_fragment(self):
        ext = ASTTextExtractor()
        assert ext._is_technical_string("renpy.call_screen('map')") is True

    def test_meaningful_text_not_technical(self):
        ext = ASTTextExtractor()
        assert ext._is_technical_string("Hello there") is False
        assert ext._is_technical_string("Click to start") is False
        assert ext._is_technical_string("New Game") is False

    def test_empty_string(self):
        ext = ASTTextExtractor()
        assert ext._is_technical_string("") is True

    def test_renpy_internal_identifiers(self):
        ext = ASTTextExtractor()
        assert ext._is_technical_string("renpy.call") is True
        assert ext._is_technical_string("some renpy.data") is True

    def test_single_non_letter_character(self):
        ext = ASTTextExtractor()
        assert ext._is_technical_string("-") is True
        assert ext._is_technical_string(".") is True

    def test_single_letter(self):
        ext = ASTTextExtractor()
        assert ext._is_technical_string("I") is False
        assert ext._is_technical_string("A") is False

    def test_control_characters(self):
        ext = ASTTextExtractor()
        assert ext._is_technical_string("\x00text") is True

    def test_pua_chars(self):
        ext = ASTTextExtractor()
        assert ext._is_technical_string("\uE000 test") is True

    def test_replacement_character(self):
        ext = ASTTextExtractor()
        assert ext._is_technical_string("bad \ufffd text") is True


# ──────────────────────────────────────────────────────────────
# ASTTextExtractor — _extract_string_content
# ──────────────────────────────────────────────────────────────


class TestExtractStringContent:
    def test_double_quoted(self):
        ext = ASTTextExtractor()
        assert ext._extract_string_content('"hello"') == "hello"

    def test_single_quoted(self):
        ext = ASTTextExtractor()
        assert ext._extract_string_content("'world'") == "world"

    def test_triple_double(self):
        ext = ASTTextExtractor()
        assert ext._extract_string_content('"""multi\nline"""') == "multi\nline"

    def test_triple_single(self):
        ext = ASTTextExtractor()
        assert ext._extract_string_content("'''text'''") == "text"

    def test_non_quoted_returned_as_is(self):
        ext = ASTTextExtractor()
        assert ext._extract_string_content("bare") == "bare"

    def test_empty_string(self):
        ext = ASTTextExtractor()
        assert ext._extract_string_content("") == ""

    def test_unescape(self):
        ext = ASTTextExtractor()
        assert ext._extract_string_content('"line1\\nline2"') == "line1\nline2"
        assert ext._extract_string_content('"tab\\there"') == "tab\there"

    def test_prefix_support(self):
        ext = ASTTextExtractor()
        assert ext._extract_string_content('f"hello {name}"') == "hello {name}"
        assert ext._extract_string_content("r'C:\\path'") == "C:\\path"


# ──────────────────────────────────────────────────────────────
# ASTTextExtractor — _is_deep_feature_enabled
# ──────────────────────────────────────────────────────────────


class TestIsDeepFeatureEnabled:
    def test_no_config_manager_returns_true(self):
        ext = ASTTextExtractor(config_manager=None)
        assert ext._is_deep_feature_enabled() is True
        assert ext._is_deep_feature_enabled("some_feature") is True

    def test_deep_extraction_disabled(self):
        cm = MagicMock()
        type(cm).translation_settings = PropertyMock()
        cm.translation_settings.enable_deep_extraction = False
        ext = ASTTextExtractor(config_manager=cm)
        assert ext._is_deep_feature_enabled() is False

    def test_specific_feature_disabled(self):
        cm = MagicMock()
        type(cm).translation_settings = PropertyMock()
        cm.translation_settings.enable_deep_extraction = True
        cm.translation_settings.my_feature = False
        ext = ASTTextExtractor(config_manager=cm)
        assert ext._is_deep_feature_enabled("my_feature") is False

    def test_specific_feature_enabled(self):
        cm = MagicMock()
        type(cm).translation_settings = PropertyMock()
        cm.translation_settings.enable_deep_extraction = True
        cm.translation_settings.my_feature = True
        ext = ASTTextExtractor(config_manager=cm)
        assert ext._is_deep_feature_enabled("my_feature") is True


# ──────────────────────────────────────────────────────────────
# ASTTextExtractor — _context_requires_whitelist
# ──────────────────────────────────────────────────────────────


class TestContextRequiresWhitelist:
    def test_empty_context(self):
        ext = ASTTextExtractor()
        assert ext._context_requires_whitelist("") is False

    def test_rpyc_val_context(self):
        ext = ASTTextExtractor()
        assert ext._context_requires_whitelist("rpyc_val:some_key") is True

    def test_variable_context(self):
        ext = ASTTextExtractor()
        assert ext._context_requires_whitelist("variable:myvar") is True

    def test_data_context(self):
        ext = ASTTextExtractor()
        assert ext._context_requires_whitelist("data:key") is True

    def test_normal_context_not_required(self):
        ext = ASTTextExtractor()
        assert ext._context_requires_whitelist("label:start") is False


# ──────────────────────────────────────────────────────────────
# ASTTextExtractor — extract_from_file (mocked)
# ──────────────────────────────────────────────────────────────


class TestExtractFromFile:
    @patch("src.core.rpyc_reader.read_rpyc_file")
    def test_returns_extracted_texts(self, mock_read, tmp_path: Path):
        say = FakeSay()
        say.what = "Hello"
        say.linenumber = 5
        mock_read.return_value = [say]

        ext = ASTTextExtractor()
        result = ext.extract_from_file(tmp_path / "dummy.rpyc")
        assert len(result) == 1
        assert result[0].text == "Hello"

    @patch("src.core.rpyc_reader.read_rpyc_file")
    def test_rpyc_read_error_caught(self, mock_read, tmp_path: Path):
        mock_read.side_effect = RpycReadError("Boom")
        ext = ASTTextExtractor()
        result = ext.extract_from_file(tmp_path / "dummy.rpyc")
        assert result == []


# ──────────────────────────────────────────────────────────────
# extract_texts_from_rpyc
# ──────────────────────────────────────────────────────────────


class TestExtractTextsFromRpyc:
    @patch("src.core.rpyc_reader.read_rpyc_file")
    def test_returns_dict_list(self, mock_read, tmp_path: Path):
        say = FakeSay()
        say.what = "Greetings"
        say.linenumber = 3
        mock_read.return_value = [say]

        result = extract_texts_from_rpyc(tmp_path / "script.rpyc")
        assert isinstance(result, list)
        assert result[0]["text"] == "Greetings"
        assert result[0]["is_rpyc"] is True
        assert result[0]["text_type"] == "dialogue"

    @patch("src.core.rpyc_reader.read_rpyc_file")
    def test_context_path_wrapped_in_list(self, mock_read, tmp_path: Path):
        say = FakeSay()
        say.what = "Text with context"
        say.linenumber = 1
        mock_read.return_value = [say]

        # Force context via add after walk
        ext = ASTTextExtractor()
        ext.extract_from_file = lambda fp: [ExtractedText(
            text="Text with context",
            line_number=1,
            source_file=str(fp),
            text_type="dialogue",
            context="label:start",
        )]
        with patch("src.core.rpyc_reader.ASTTextExtractor", return_value=ext):
            result = extract_texts_from_rpyc(tmp_path / "script.rpyc")
            assert result[0]["context"] == "label:start"
            assert result[0]["context_path"] == ["label:start"]


# ──────────────────────────────────────────────────────────────
# extract_texts_from_rpyc_directory
# ──────────────────────────────────────────────────────────────


class TestExtractTextsFromRpycDirectory:
    def test_empty_directory(self, tmp_path: Path):
        d = tmp_path / "empty"
        d.mkdir()
        result = extract_texts_from_rpyc_directory(d)
        assert result == {}

    def test_no_rpyc_files(self, tmp_path: Path):
        d = tmp_path / "game"
        d.mkdir()
        (d / "script.txt").write_text("hello")
        result = extract_texts_from_rpyc_directory(d)
        assert result == {}

    def test_skips_tl_directory(self, tmp_path: Path):
        d = tmp_path / "game"
        tl = d / "tl" / "turkish"
        tl.mkdir(parents=True)
        (tl / "dialogue.rpyc").write_bytes(b"dummy")
        result = extract_texts_from_rpyc_directory(d)
        assert not any("tl" in str(k) for k in result)

    def test_renpy_common_included(self, tmp_path: Path):
        d = tmp_path / "game"
        common = d / "renpy" / "common"
        common.mkdir(parents=True)
        (common / "data.rpyc").write_bytes(b"dummy")
        result = extract_texts_from_rpyc_directory(d)
        assert len(result) >= 1

    def test_renpy_root_excluded(self, tmp_path: Path):
        d = tmp_path / "game"
        renpy_root = d / "renpy"
        renpy_root.mkdir(parents=True)
        (renpy_root / "engine.rpyc").write_bytes(b"dummy")
        result = extract_texts_from_rpyc_directory(d)
        for texts in result.values():
            assert texts == []

    @patch("src.core.rpyc_reader.extract_texts_from_rpyc")
    def test_rpyc_files_extracted(self, mock_extract, tmp_path: Path):
        d = tmp_path / "game"
        d.mkdir()
        (d / "script.rpyc").write_bytes(b"dummy")
        mock_extract.return_value = [{"text": "Game dialogue", "is_rpyc": True, "text_type": "dialogue"}]
        result = extract_texts_from_rpyc_directory(d)
        file_paths = [str(k).replace("\\", "/") for k in result]
        assert any("script.rpyc" in p for p in file_paths)
        texts_list = next(iter(result.values()))
        assert any("Game dialogue" == t["text"] for t in texts_list)

    @patch("src.core.rpyc_reader.extract_texts_from_rpyc")
    def test_rpymc_files_also_extracted(self, mock_extract, tmp_path: Path):
        d = tmp_path / "game"
        d.mkdir()
        (d / "cache.rpymc").write_bytes(b"dummy")
        mock_extract.return_value = [{"text": "Cache dialogue", "is_rpyc": True}]
        result = extract_texts_from_rpyc_directory(d)
        file_paths = [str(k).replace("\\", "/") for k in result]
        assert any("cache.rpymc" in p for p in file_paths)

    def test_exception_per_file_does_not_block_others(self, tmp_path: Path):
        d = tmp_path / "game"
        d.mkdir()
        (d / "bad.rpyc").write_bytes(b"garbage_not_pickle")
        result = extract_texts_from_rpyc_directory(d)
        assert len(result) >= 1
        bad_paths = [k for k in result if "bad.rpyc" in str(k)]
        assert result[bad_paths[0]] == []

    def test_non_recursive_mode(self, tmp_path: Path):
        d = tmp_path / "game"
        sub = d / "subdir"
        sub.mkdir(parents=True)
        (sub / "sub.rpyc").write_bytes(b"dummy")
        result = extract_texts_from_rpyc_directory(d, recursive=False)
        assert result == {}


# ──────────────────────────────────────────────────────────────
# Edge cases and Null handling
# ──────────────────────────────────────────────────────────────


class TestProcessNodeNullHandling:
    def test_none_node(self):
        ext = ASTTextExtractor()
        ext._process_node(None)
        assert ext.extracted == []

    def test_walk_none_nodes(self):
        ext = ASTTextExtractor()
        ext._walk_nodes(None)
        assert ext.extracted == []

    def test_walk_single_node_wrapped_in_list(self):
        ext = ASTTextExtractor()
        say = FakeSay()
        say.what = "Single node"
        ext._walk_nodes(say)
        assert len(ext.extracted) == 1

    def test_recursion_error_handled(self):
        """_walk_nodes catches RecursionError gracefully."""
        ext = ASTTextExtractor()

        class RecursiveNode(FakeASTBase):
            @property
            def block(self):
                raise RecursionError("too deep")

        ext._walk_nodes([RecursiveNode()])
        assert ext.extracted == []


class TestFakeTranslateSayEdgeCases:
    def test_identifier_none(self):
        ext = ASTTextExtractor()
        node = FakeTranslateSay()
        node.what = "Hello from translate say"
        node.identifier = None
        ext._process_node(node)
        assert len(ext.extracted) == 1


class TestProcessNodeScreen:
    def test_screen_with_screen_obj(self):
        ext = ASTTextExtractor()
        screen_obj = FakeSLScreen()
        screen_obj.name = "main_menu"
        screen_obj.children = []
        node = FakeScreen()
        node.name = "main_menu"
        node.screen = screen_obj
        ext._process_node(node)
        assert isinstance(ext.extracted, list)


class TestProcessNodeGenericBlock:
    """Nodes with a .block attribute that don't match any specific type."""
    def test_generic_block_walked(self):
        ext = ASTTextExtractor()
        say = FakeSay()
        say.what = "Inside gBlock"

        class Unknown(FakeASTBase):
            def __init__(self):
                super().__init__()
                self.block = [say]

        ext._process_node(Unknown())
        assert any("Inside gBlock" == e.text for e in ext.extracted)


class TestExtractedTextDataclass:
    def test_default_placeholder_map(self):
        e = ExtractedText(
            text="t", line_number=1, source_file="f", text_type="d",
            context="", placeholder_map=None,
        )
        assert e.placeholder_map is None
        assert e.confidence == 0.0
        assert e.confidence_band == "candidate"
        assert e.node_type == ""


# ──────────────────────────────────────────────────────────────
# RpycReadError
# ──────────────────────────────────────────────────────────────


class TestRpycReadError:
    def test_is_exception(self):
        with pytest.raises(RpycReadError):
            raise RpycReadError("test error")

    def test_message(self):
        err = RpycReadError("custom message")
        assert str(err) == "custom message"
