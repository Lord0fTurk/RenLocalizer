import json

from scripts.compare_lexers import compare


def test_compare_lexers_is_read_only_and_reports_both_modes(tmp_path):
    script = tmp_path / "script.rpy"
    script.write_text(
        'label start:\n'
        '    e "Hello world!"\n'
        '    "???" "Who goes there?"\n'
        'default quick_save = "Do not translate this bare default"\n',
        encoding="utf-8",
    )
    before = script.read_bytes()

    report = compare(tmp_path, max_samples=5)

    assert script.read_bytes() == before
    assert report["files"] == 1
    assert report["regex"]["errors"] == []
    assert report["stateful"]["errors"] == []
    assert report["verdict"]["production_output_changed"] is False
    assert report["verdict"]["standalone_parity_claim"] is False
    assert report["comparison"]["regex_only"] == 0
    assert report["comparison"]["stateful_text_only"] >= 0
    json.dumps(report, ensure_ascii=False)
