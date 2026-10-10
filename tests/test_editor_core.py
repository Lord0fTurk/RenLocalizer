# -*- coding: utf-8 -*-
"""Translation editor core: line edits, store, load/save and sync."""
import json
import os
import time

import pytest

from src.core.editor.checks import code_tokens, find_problem
from src.core.editor.project import (
    load_language, save_edits, sync_strings_json, sync_translation_cache,
)
from src.core.editor.store import EditorStore, fold
from src.core.tl_parser import TLParser

TL = (
    "# game/script.rpy:10\n"
    "translate turkish start_1a2b3c4d:\n"
    "\n"
    "    # m \"Hello, [name]!\"\n"
    "    m \"Merhaba, [name]!\"\n"
    "\n"
    "# game/script.rpy:12\n"
    "translate turkish start_5e6f7a8b:\n"
    "\n"
    "    # \"What do you want?\" nointeract\n"
    "    \"\" nointeract\n"
    "\n"
    "translate turkish start_9c0d1e2f:\n"
    "\n"
    "    # m \"I {i}really{/i} like it.\" with dissolve\n"
    "    m \"I {i}really{/i} like it.\" with dissolve\n"
    "\n"
    "translate turkish strings:\n"
    "\n"
    "    old \"Start\"\n"
    "    new \"\"\n"
)


@pytest.fixture
def game(tmp_path):
    game_dir = tmp_path / "game"
    (game_dir / "tl" / "turkish").mkdir(parents=True)
    (game_dir / "script.rpy").write_text('define m = Character("Mia")\n', encoding="utf-8")
    (game_dir / "tl" / "turkish" / "script.rpy").write_text(TL, encoding="utf-8")
    (game_dir / "tl" / "turkish" / "zz_rl_exported_turkish.rpy").write_text(
        'translate turkish strings:\n    old "X"\n    new "Y"\n', encoding="utf-8")
    return str(game_dir)


def _rows_by_original(rows):
    return {r["original"]: r for r in rows}


# ── tl_parser.apply_line_edits ─────────────────────────────────────────

def test_line_edits_keep_speaker_tail_and_line_endings():
    p = TLParser()
    content = TL.replace("\n", "\r\n")
    out, failed = p.apply_line_edits(content, [
        {"line": 5, "kind": "dialogue", "original": "Hello, [name]!", "text": 'Selam "[name]"!'},
        {"line": 11, "kind": "narrator", "original": "What do you want?", "text": "Ne istersin?"},
        {"line": 16, "kind": "dialogue", "original": "I {i}really{/i} like it.", "text": "{i}Gerçekten{/i} sevdim."},
        {"line": 20, "kind": "string", "original": "Start", "text": "Başla"},
    ])
    assert failed == []
    assert '    m "Selam \\"[name]\\"!"\r\n' in out
    assert '    "Ne istersin?" nointeract\r\n' in out
    assert '    m "{i}Gerçekten{/i} sevdim." with dissolve\r\n' in out
    assert '    new "Başla"\r\n' in out
    assert out.count("\r\n") == content.count("\r\n")


def test_line_edit_refuses_a_moved_slot():
    out, failed = TLParser().apply_line_edits(TL, [
        {"line": 5, "kind": "dialogue", "original": "Something else", "text": "X"},
    ])
    assert failed == [5] and out == TL


# ── checks ─────────────────────────────────────────────────────────────

def test_checks_match_the_pipeline_reopen_rule():
    from src.core.pipeline.extraction import reopen_stale_tl_entries
    from src.core.tl_parser import TranslationEntry, TranslationFile

    good = ("Hello, [name]!", "Merhaba, [name]!")
    bad = ("Hello, [name]!", "Merhaba!")
    assert find_problem(*good) is None and find_problem(*bad)

    f = TranslationFile("x.rpy", "turkish", [
        TranslationEntry(o, t, "x.rpy", i, "dialogue") for i, (o, t) in enumerate((good, bad))
    ])
    counts = reopen_stale_tl_entries([f], None, None, lambda **kw: None)
    assert counts["reopened"] == 1 and f.entries[0].translated_text == good[1]


def test_code_tokens():
    assert code_tokens("Hi [name], {i}x{/i} %d [[no] {{no}") == ["[name]", "{i}", "{/i}", "%d"]


# ── store ──────────────────────────────────────────────────────────────

def test_store_filters_search_and_edit(game):
    loaded = load_language(game, "turkish")
    store = EditorStore()
    assert store.load(loaded.rows) == 4
    assert store.files() == ["script.rpy"]  # RenLocalizer's own export file is skipped

    st = store.stats()
    assert (st["total"], st["empty"], st["source_copy"], st["modified"]) == (4, 2, 1, 0)

    rows, total = store.query(status="untranslated")
    assert total == 3
    rows, total = store.query(search="mia")  # speaker display name is searchable
    assert total == 2 and rows[0]["speaker_name"] == "Mia"
    _, total = store.query(kind="string")
    assert total == 1

    caption = store.query(search="what do you")[0][0]
    row = store.update(caption["id"], "Ne istersin?")
    assert row["status"] == "translated" and row["modified"] == 1 and row["problem"] == ""
    row = store.update(caption["id"], "")
    assert row["modified"] == 0

    hello = store.query(search="hello")[0][0]
    assert store.update(hello["id"], "Merhaba!")["problem"] == "placeholder_set_mismatch"
    assert store.query(status="warnings")[1] == 1
    assert store.revert(hello["id"])["translated"] == "Merhaba, [name]!"


def test_turkish_search_folding():
    assert fold("IŞIK İzmir") == fold("ışık izmir") == "isik izmir"


def test_replace_all_never_touches_tags_or_variables(game):
    store = EditorStore()
    store.load(load_language(game, "turkish").rows)
    hello = store.query(search="hello")[0][0]
    store.update(hello["id"], "Name name [name]")
    assert store.replace_all("name", "isim", search="hello") == 1
    assert store.get(hello["id"])["translated"] == "isim isim [name]"


def test_reload_keeps_unsaved_edits(game):
    store = EditorStore()
    store.load(load_language(game, "turkish").rows)
    start = store.query(kind="string")[0][0]
    store.update(start["id"], "Başla")
    store.load(load_language(game, "turkish").rows)
    start = store.query(kind="string")[0][0]
    assert start["translated"] == "Başla" and start["modified"] == 1


# ── save ───────────────────────────────────────────────────────────────

def test_save_writes_backs_up_and_marks_saved(game, tmp_path):
    loaded = load_language(game, "turkish")
    store = EditorStore()
    store.load(loaded.rows)
    start = store.query(kind="string")[0][0]
    store.update(start["id"], "Başla")
    backup = tmp_path / "backup"

    result = save_edits(store.modified_by_file(), loaded.snapshots, str(backup))
    assert result.saved_ids == [start["id"]] and not result.conflicts and not result.failed_ids
    store.mark_saved(result.saved_ids)
    assert store.stats()["modified"] == 0

    path = os.path.join(game, "tl", "turkish", "script.rpy")
    assert 'new "Başla"' in open(path, encoding="utf-8-sig").read()
    assert (backup / "script.rpy.bak").read_text(encoding="utf-8") == TL
    assert not list(backup.glob("*.rpy"))  # Ren'Py would load a .rpy backup

    # The written file parses back to the same slots.
    reread = _rows_by_original(load_language(game, "turkish").rows)
    assert reread["Start"]["translated"] == "Başla"
    assert reread["What do you want?"]["translated"] == ""


def test_save_skips_a_file_changed_on_disk(game):
    loaded = load_language(game, "turkish")
    store = EditorStore()
    store.load(loaded.rows)
    store.update(store.query(kind="string")[0][0]["id"], "Başla")
    path = os.path.join(game, "tl", "turkish", "script.rpy")
    time.sleep(0.01)
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n# touched by a translation run\n")

    result = save_edits(store.modified_by_file(), loaded.snapshots, None)
    assert result.conflicts == [path] and not result.saved_ids
    assert 'new "Başla"' not in open(path, encoding="utf-8").read()


# ── sync ───────────────────────────────────────────────────────────────

def test_sync_strings_json_and_cache(tmp_path):
    lang_dir = tmp_path / "tl" / "turkish"
    lang_dir.mkdir(parents=True)
    (lang_dir / "strings.json").write_text(json.dumps(
        {"translations": {"Start": "Basla", "Quit": "Cik"}, "dynamic": {}}), encoding="utf-8")
    assert sync_strings_json(str(lang_dir), {"Start": "Başla", "Missing": "x"}) == 1
    data = json.loads((lang_dir / "strings.json").read_text(encoding="utf-8"))
    assert data["translations"] == {"Start": "Başla", "Quit": "Cik"}

    cache = tmp_path / "translation_cache.json"
    cache.write_text(json.dumps({
        "google": {"auto": {"tr": {"Start": "Basla"}, "de": {"Start": "Starten"}}},
        "openai": {"en": {"tr": {"Start": "Başlat"}}},
    }), encoding="utf-8")
    assert sync_translation_cache(str(cache), ["tr", "turkish"], {"Start": "Başla", "New": "Yeni"}) == 2
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert data["google"]["auto"]["tr"] == {"Start": "Başla"}
    assert data["google"]["auto"]["de"] == {"Start": "Starten"}
    assert data["openai"]["en"]["tr"] == {"Start": "Başla"}
    assert sync_translation_cache(str(tmp_path / "missing.json"), ["tr"], {"Start": "x"}) == 0
