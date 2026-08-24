import asyncio

from src.core.translator import (
    GoogleTranslator,
    TranslationEngine,
    TranslationRequest,
)


class DummyResp:
    def __init__(self, data):
        self.status = 200
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, content_type=None):
        return self._data


class DummySession:
    def __init__(self, data):
        self.data = data
        self.closed = False

    def get(self, url, proxy=None, timeout=None, headers=None):
        return DummyResp(self.data)

    async def close(self):
        self.closed = True


def test_batch_separator_preserves_metadata(monkeypatch):
    """
    Batch-separator yolunda TranslationResult.metadata kaybolmamalı; aksi halde
    placeholder_map geri yüklenemiyor.
    """
    # Simüle edilmiş Google cevabı: tek segment, içinde separator ile iki metin.
    g = GoogleTranslator()
    combined = f"hello{g.BATCH_SEPARATOR}world"
    dummy_data = [[[combined]]]

    async def fake_get_session():
        return DummySession(dummy_data)

    monkeypatch.setattr(g, "_get_session", fake_get_session)
    # Çoklu endpoint yarışını tek endpoint'e indir
    g.use_multi_endpoint = False
    g.google_endpoints = ["https://dummy"]

    reqs = [
        TranslationRequest(
            text="one",
            source_lang="en",
            target_lang="tr",
            engine=TranslationEngine.GOOGLE,
            metadata={"placeholder_map": {"X": "Y"}},
        ),
        TranslationRequest(
            text="two",
            source_lang="en",
            target_lang="tr",
            engine=TranslationEngine.GOOGLE,
            metadata={"id": 42},
        ),
    ]

    results = asyncio.run(g._try_batch_separator(reqs))
    assert results is not None
    assert len(results) == 2
    assert results[0].metadata.get("placeholder_map") == {"X": "Y"}
    assert results[1].metadata.get("id") == 42
    assert results[0].translated_text == "hello"
    assert results[1].translated_text == "world"
