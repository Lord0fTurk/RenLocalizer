import asyncio
import time
from types import SimpleNamespace

from src.core.constants import RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD
from src.core.translator import (
    GoogleTranslator,
    TranslationEngine,
    TranslationRequest,
)


class RoutedResp:
    def __init__(self, status, data):
        self.status = status
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, content_type=None):
        return self._data


class RoutedSession:
    """Returns 429 for /translate_a/single-style URLs and a configurable
    payload for clients5.google.com URLs."""

    def __init__(self, c5_data):
        self.c5_data = c5_data
        self.closed = False

    def get(self, url=None, params=None, proxy=None, timeout=None, headers=None,
            ssl=None):
        url_str = str(url)
        client = (params or {}).get("client", "")
        if "clients5" in url_str or client == "dict-chrome-ex":
            return RoutedResp(200, self.c5_data)
        return RoutedResp(429, [])

    async def close(self):
        self.closed = True


def _make_translator() -> GoogleTranslator:
    cfg = SimpleNamespace(
        translation_settings=SimpleNamespace(
            use_multi_endpoint=False,
            enable_lingva_fallback=True,
            max_concurrent_threads=2,
            max_chars_per_request=1000,
            max_batch_size=50,
            aggressive_retry_translation=False,
            use_html_protection=False,
            request_delay=0.0,
        )
    )
    g = GoogleTranslator(config_manager=cfg)
    g.google_endpoints = ["https://dummy"]
    return g


def test_extract_clients5_shapes():
    assert GoogleTranslator._extract_clients5_text(["Merhaba"]) == "Merhaba"
    assert GoogleTranslator._extract_clients5_text([["Selam", "en"]]) == "Selam"
    assert GoogleTranslator._extract_clients5_text([["a"], ["b"]]) == "ab"
    assert GoogleTranslator._extract_clients5_text([]) is None
    assert GoogleTranslator._extract_clients5_text(None) is None
    assert GoogleTranslator._extract_clients5_text({"x": 1}) is None


def test_translate_single_rescued_by_clients5(monkeypatch):
    g = _make_translator()

    async def fake_get_session():
        return RoutedSession(["merhaba dünya"])

    monkeypatch.setattr(g, "_get_session", fake_get_session)

    async def fast_sleep(_delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    request = TranslationRequest(
        text="hello world",
        source_lang="en",
        target_lang="tr",
        engine=TranslationEngine.GOOGLE,
    )

    result = asyncio.run(g.translate_single(request))
    assert result.success is True
    assert result.translated_text == "merhaba dünya"


def test_detection_falls_back_to_clients5(monkeypatch):
    g = _make_translator()

    async def fake_get_session():
        return RoutedSession([["Selam Dunya", "EN"]])

    monkeypatch.setattr(g, "_get_session", fake_get_session)

    detected = asyncio.run(g._detect_single_language("hello world sample"))
    assert detected == "en"


def test_breaker_active_skips_primaries_and_rescues(monkeypatch):
    g = _make_translator()
    session = RoutedSession(["merhaba"])
    calls = []

    orig_get = session.get

    def tracking_get(url=None, **kwargs):
        calls.append(str(url))
        return orig_get(url=url, **kwargs)

    session.get = tracking_get

    async def fake_get_session():
        return session

    monkeypatch.setattr(g, "_get_session", fake_get_session)

    async def fast_sleep(_delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    g._consecutive_429_count = RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD
    g._primary_probe_at = time.time() + 9999.0  # probe window closed

    request = TranslationRequest(
        text="hello",
        source_lang="en",
        target_lang="tr",
        engine=TranslationEngine.GOOGLE,
    )
    result = asyncio.run(g.translate_single(request))

    assert result.success is True
    assert result.translated_text == "merhaba"
    assert not any("dummy" in c for c in calls)
    assert any("clients5" in c for c in calls)


def test_inflight_chain_bails_when_breaker_trips_midway(monkeypatch):
    g = _make_translator()
    session = RoutedSession(["merhaba"])
    calls = []

    orig_get = session.get

    def tracking_get(url=None, **kwargs):
        calls.append(str(url))
        return orig_get(url=url, **kwargs)

    session.get = tracking_get

    async def fake_get_session():
        return session

    monkeypatch.setattr(g, "_get_session", fake_get_session)

    async def fast_sleep(_delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    # One 429 below the threshold: the first attempt trips the breaker, and
    # the second loop iteration must bail instead of retrying.
    g._consecutive_429_count = RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD - 1
    g._primary_probe_at = time.time() + 9999.0

    request = TranslationRequest(
        text="hello",
        source_lang="en",
        target_lang="tr",
        engine=TranslationEngine.GOOGLE,
    )
    result = asyncio.run(g.translate_single(request))

    dummy_calls = [c for c in calls if "dummy" in c]
    assert len(dummy_calls) == 1
    assert any("clients5" in c for c in calls)
    assert result.success is True


def test_breaker_probe_window_allows_single_primary_attempt(monkeypatch):
    g = _make_translator()
    session = RoutedSession(["merhaba"])
    calls = []

    orig_get = session.get

    def tracking_get(url=None, **kwargs):
        calls.append(str(url))
        return orig_get(url=url, **kwargs)

    session.get = tracking_get

    async def fake_get_session():
        return session

    monkeypatch.setattr(g, "_get_session", fake_get_session)

    async def fast_sleep(_delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    g._consecutive_429_count = RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD
    # Probe window expired -> primaries allowed once, then window re-arms.
    g._primary_probe_at = 0.0

    request = TranslationRequest(
        text="hello",
        source_lang="en",
        target_lang="tr",
        engine=TranslationEngine.GOOGLE,
    )
    asyncio.run(g.translate_single(request))

    dummy_calls = [c for c in calls if "dummy" in c]
    c5_calls = [c for c in calls if "clients5" in c]
    assert len(dummy_calls) >= 1
    assert len(c5_calls) >= 1
    assert g._primary_probe_at > time.time()
