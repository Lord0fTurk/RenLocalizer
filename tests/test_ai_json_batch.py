from src.core.ai_translator import _parse_json_batch


def test_parse_json_batch_normal():
    json_text = '{"translations": [{"id": 0, "translated_text": "Merhaba"}, {"id": 1, "translated_text": "Dünya"}]}'
    res = _parse_json_batch(json_text, 2)
    assert res == ["Merhaba", "Dünya"]


def test_parse_json_batch_out_of_bounds_ids():
    # Model returns id 64, 65 while count is 2 (the exact bug observed in Hy-MT2 1.8B)
    json_text = '{"translations": [{"id": 64, "translated_text": "Pencereyi açar."}, {"id": 65, "translated_text": "Gülümser."}]}'
    res = _parse_json_batch(json_text, 2)
    assert res == ["Pencereyi açar.", "Gülümser."]


def test_parse_json_batch_1_based_indexing():
    json_text = '{"translations": [{"id": 1, "translated_text": "İlk"}, {"id": 2, "translated_text": "İkinci"}]}'
    res = _parse_json_batch(json_text, 2)
    assert res == ["İlk", "İkinci"]


def test_parse_json_batch_partial_ids():
    # One valid id (0), one out-of-range id (99)
    json_text = '{"translations": [{"id": 0, "translated_text": "Evet"}, {"id": 99, "translated_text": "Hayır"}]}'
    res = _parse_json_batch(json_text, 2)
    assert res == ["Evet", "Hayır"]
