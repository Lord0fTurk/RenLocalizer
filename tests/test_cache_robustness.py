# -*- coding: utf-8 -*-
"""Cache persistence edge cases: miss cost, dirty tracking, unreadable files, bad text."""
import asyncio
import json
import os
from collections import OrderedDict

from src.core.translator import TranslationEngine, TranslationManager, TranslationResult
from src.utils.encoding import read_json_safely, save_json_safely


def _result(text, translated, engine=TranslationEngine.GOOGLE):
    return TranslationResult(
        original_text=text, translated_text=translated,
        source_lang="en", target_lang="tr", engine=engine, success=True,
    )


def test_cache_miss_does_not_scan_whole_cache():
    manager = TranslationManager()
    for i in range(1000):
        manager._cache[("google", "en", "tr", f"line {i}")] = _result(f"line {i}", f"satır {i}")

    scans = []
    original_items = type(manager._cache).items

    def counting_items(self):
        scans.append(1)
        return original_items(self)

    type(manager._cache).items = counting_items
    try:
        assert manager.get_cached_translation("never seen", "en", "tr", "google") is None
        assert asyncio.run(manager._cache_get(("google", "en", "tr", "never seen"))) is None
    finally:
        type(manager._cache).items = original_items
    assert scans == []


def test_plain_dict_cache_still_found_by_fallback():
    manager = TranslationManager()
    plain = OrderedDict()
    plain[("openai", "en", "tr", "Hello")] = _result("Hello", "Merhaba", TranslationEngine.OPENAI)
    manager._cache = plain
    hit = manager.get_cached_translation("Hello", "auto", "tr", "google")
    assert hit is not None and hit.translated_text == "Merhaba"


def test_cache_update_text_marks_dirty_and_persists(tmp_path):
    cache_file = tmp_path / "translation_cache.json"
    manager = TranslationManager()
    key = ("google", "en", "tr", "Hello")
    manager._cache[key] = _result("Hello", "{color=#fff}Merhaba{/color}")
    manager.save_cache(str(cache_file))
    assert manager._is_dirty is False

    asyncio.run(manager.cache_update_text(key, "Merhaba"))
    assert manager._is_dirty is True

    manager.save_cache(str(cache_file))
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert data["google"]["en"]["tr"]["Hello"] == "Merhaba"


def test_unreadable_cache_is_backed_up_before_overwrite(tmp_path):
    cache_file = tmp_path / "translation_cache.json"
    cache_file.write_text('{"google": {"en": {"tr": {"Hello": "Merh', encoding="utf-8")

    manager = TranslationManager()
    manager.load_cache(str(cache_file))

    backups = [p for p in os.listdir(tmp_path) if p.endswith(".bak")]
    assert len(backups) == 1
    assert (tmp_path / backups[0]).read_text(encoding="utf-8").startswith('{"google"')


def test_save_json_survives_lone_surrogates_without_leaking_temp(tmp_path):
    target = tmp_path / "strings.json"
    assert save_json_safely(target, {"translations": {"bad \udcff text": "ok"}})
    loaded = read_json_safely(target)
    assert loaded is not None
    assert list(loaded["translations"].values()) == ["ok"]
    assert [p.name for p in tmp_path.iterdir()] == ["strings.json"]


def test_save_json_reports_unwritable_parent(tmp_path):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    assert save_json_safely(blocker / "child" / "out.json", {"a": 1}) is False
