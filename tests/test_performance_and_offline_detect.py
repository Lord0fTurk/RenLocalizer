"""
Unit tests for orjson-accelerated serialization, multicore parsing, and py3langid offline language detection.
"""

import tempfile
from pathlib import Path
import pytest
from src.utils.encoding import save_json_safely, read_json_safely, dumps_json, loads_json
from src.core.parser import RenPyParser
from src.utils.config import ConfigManager


def test_orjson_roundtrip_and_speed():
    """Verify that save_json_safely and read_json_safely roundtrip data accurately."""
    with tempfile.TemporaryDirectory() as tmpdir:
        json_file = Path(tmpdir) / "test_cache.json"
        data = {
            "google": {
                "en": {
                    "tr": {
                        "Hello, world!": "Merhaba, d\u00fcnya!",
                        "Special {b}tags{/b} [var]": "\u00d6zel {b}etiketler{/b} [var]",
                    }
                }
            },
            "metrics": [1, 2, 3, 4, 5],
            "active": True,
        }
        success = save_json_safely(json_file, data, indent=2)
        assert success is True
        assert json_file.is_file()

        loaded = read_json_safely(json_file)
        assert loaded == data


def test_dumps_and_loads_json():
    """Test string-based dumps_json and loads_json helpers."""
    payload = {"key": "de\u011fer", "nested": {"a": 123}}
    dumped = dumps_json(payload)
    assert isinstance(dumped, str)
    loaded = loads_json(dumped)
    assert loaded == payload


def test_offline_language_detection_py3langid():
    """Verify py3langid offline classification accuracy on typical visual novel samples."""
    import py3langid

    en_text = "She looked at me with a warm smile and held my hand."
    lang_en, _ = py3langid.classify(en_text)
    assert lang_en == "en"

    ja_text = "\u3053\u3093\u306b\u3061\u306f\u3001\u4eca\u65e5\u306f\u3044\u3044\u5929\u6c17\u3067\u3059\u306d\u3002"
    lang_ja, _ = py3langid.classify(ja_text)
    assert lang_ja == "ja"

    ru_text = "\u041f\u0440\u0438\u0432\u0435\u0442, \u043a\u0430\u043a \u0442\u0432\u043e\u0438 \u0434\u0435\u043b\u0430 \u0441\u0435\u0433\u043e\u0434\u043d\u044f?"
    lang_ru, _ = py3langid.classify(ru_text)
    assert lang_ru == "ru"


def test_offline_detection_refuses_low_confidence_samples():
    """Names/UI markup must not pin the whole run to a bogus language (was 'sn'/'uz')."""
    from src.utils.lang_detect import detect_source_language

    names_and_ui = ["Mio", "Akira", "Sakura Hmm Ah!", "... Ehh?", "Start", "Load", "Prefs"] * 5
    assert detect_source_language(names_and_ui) is None

    tagged = ["[player_name] {b}Day 1{/b} Monday Morning"] * 20
    assert detect_source_language(tagged) is None


def test_offline_detection_accepts_confident_prose():
    from src.utils.lang_detect import detect_source_language

    english = [
        "I can not believe you did that to me.",
        "We need to talk about it tonight, [player_name].",
        "She looked at me with a warm smile and held my hand.",
        "{i}Why is everyone staring at me like that?{/i}",
        "The rain did not stop for three whole days.",
        "You should get some rest before the exam tomorrow.",
        "Let's go to the beach after school, okay?",
        "My mother called me twice this morning.",
        "I have never seen this place before in my life.",
        "Do you really think we can win this game?",
    ]
    assert detect_source_language(english) == "en"

    russian = [
        "Привет, как твои дела сегодня утром?",
        "Я не могу поверить, что ты это сделал.",
        "Нам нужно поговорить об этом вечером.",
        "Она посмотрела на меня с тёплой улыбкой.",
        "Дождь не прекращался целых три дня.",
        "Тебе стоит отдохнуть перед экзаменом.",
        "Давай пойдём на пляж после школы.",
        "Мама звонила мне дважды этим утром.",
    ]
    assert detect_source_language(russian) == "ru"


def test_offline_detection_strips_markup():
    from src.utils.lang_detect import clean_sample

    assert clean_sample("{b}Hello{/b} [name], ⟦RLPH1A_0⟧ how are you?") == "Hello , how are you?"


def test_parser_context_line_is_thread_local():
    """Worker threads must not see each other's context line (jump/font filters)."""
    import threading

    parser = RenPyParser(ConfigManager())
    parser._current_context_line = "main thread line"
    seen = {}
    barrier = threading.Barrier(2)

    def worker(name, line):
        parser._current_context_line = line
        barrier.wait()
        seen[name] = parser.get_context_line()

    threads = [
        threading.Thread(target=worker, args=("a", "jump Forest")),
        threading.Thread(target=worker, args=("b", 'text "Hello there"')),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert seen == {"a": "jump Forest", "b": 'text "Hello there"'}
    assert parser.get_context_line() == "main thread line"


def test_parallel_scan_is_deterministic_and_ordered():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        for i in range(12):
            body = "".join(
                f'    "Line {j} of file {i} has some words."\n' for j in range(40)
            )
            (tmp_path / f"s{i:02d}.rpy").write_text(
                f"label l{i}:\n{body}    $ renpy.jump(\"Forest\")\n    return\n", encoding="utf-8"
            )

        parser = RenPyParser(ConfigManager())
        first = parser.extract_from_directory_with_deep_scan(tmp_path, include_deep_scan=False)
        second = parser.extract_from_directory_with_deep_scan(tmp_path, include_deep_scan=False)

        assert [p.name for p in first] == sorted(p.name for p in first)
        assert list(first) == list(second)
        for path in first:
            assert [e["text"] for e in first[path]] == [e["text"] for e in second[path]]



def test_scans_do_not_depend_on_the_file_system_order(tmp_path, monkeypatch):
    """NTFS lists files alphabetically, ext4/APFS do not: the scan must sort.

    Windows CI could never see this, so the listing is reversed here.
    """
    from src.core.rpyc_reader import extract_texts_from_rpyc_directory

    sub = tmp_path / "chapters"
    sub.mkdir()
    for folder, names in ((tmp_path, ("b.rpy", "a.rpy", "C.rpy")), (sub, ("z.rpy", "m.rpy"))):
        for name in names:
            (folder / name).write_text('label x:\n    "Some words here."\n', encoding="utf-8")
            (folder / (name + "c")).write_bytes(b"")

    real_glob = Path.glob
    monkeypatch.setattr(Path, "glob", lambda self, pattern, **kw: list(reversed(list(real_glob(self, pattern, **kw)))))

    parser = RenPyParser(ConfigManager())
    expected = ["a.rpy", "b.rpy", "C.rpy", "chapters/m.rpy", "chapters/z.rpy"]
    for scan in (parser.extract_from_directory_with_deep_scan(tmp_path, include_deep_scan=False),
                 parser.extract_from_directory_parallel(tmp_path),
                 parser.extract_from_directory(tmp_path)):
        assert [p.relative_to(tmp_path).as_posix() for p in scan] == expected

    import src.core.rpyc_reader as reader
    monkeypatch.setattr(reader, "extract_texts_from_rpyc", lambda path, *a, **kw: [])
    rpyc = extract_texts_from_rpyc_directory(tmp_path)
    assert [p.relative_to(tmp_path).as_posix() for p in rpyc] == [n + "c" for n in expected]

def test_parser_multithreaded_directory_scan():
    """Verify that ThreadPoolExecutor parallel directory extraction correctly processes multiple files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        # Create 5 small .rpy files
        for i in range(5):
            rpy = tmp_path / f"script_{i}.rpy"
            rpy.write_text(f'label start_{i}:\n    "Dialogue line number {i}"\n    return\n', encoding="utf-8")

        config = ConfigManager()
        parser = RenPyParser(config)

        progress_calls = []
        def on_progress(current, total, file_path):
            progress_calls.append((current, total, str(file_path)))

        results = parser.extract_from_directory_with_deep_scan(
            tmp_path,
            include_deep_scan=False,
            progress_callback=on_progress,
        )

        assert len(results) == 5
        assert len(progress_calls) == 5
        all_texts = {entry["text"] for entries in results.values() for entry in entries}
        for i in range(5):
            assert f"Dialogue line number {i}" in all_texts
