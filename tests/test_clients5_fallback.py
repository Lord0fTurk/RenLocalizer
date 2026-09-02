import asyncio
import json
import time
from types import SimpleNamespace

from src.core.constants import RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD
from src.core.translator import (
    GoogleTranslator,
    TranslationEngine,
    TranslationRequest,
)


class RoutedResp:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, content_type=None):
        return self._payload

    async def text(self):
        if isinstance(self._payload, str):
            return self._payload
        return json.dumps(self._payload)


class RoutedSession:
    """GETs: 429 for primary-style URLs, configurable payload for clients5.
    POSTs: configurable raw envelope body for batchexecute URLs."""

    def __init__(self, c5_data, be_raw=None, primary_status=429):
        self.c5_data = c5_data
        self.be_raw = be_raw
        self.primary_status = primary_status
        self.closed = False

    def get(self, url=None, params=None, proxy=None, timeout=None, headers=None,
            ssl=None):
        url_str = str(url)
        client = (params or {}).get("client", "")
        if "clients5" in url_str or client == "dict-chrome-ex":
            return RoutedResp(200, self.c5_data)
        return RoutedResp(self.primary_status, [])

    def post(self, url=None, params=None, data=None, headers=None, timeout=None):
        if "batchexecute" in str(url):
            return RoutedResp(200, self.be_raw or "")
        return RoutedResp(404, "")

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


# ---------------------------------------------------------------------------
# batchexecute (third Google-family route) — parser + rescue integration
# ---------------------------------------------------------------------------

def _be_body(inner):
    envelope = [["wrb.fr", "MkEWBc", json.dumps(inner), None]]
    return ")]}'\n\n140\n" + json.dumps(envelope) + "\n"


# Shape mirrors the live response: sentences at inner[1][0][0][5].
_INNER_SENTENCES = [
    None,
    [[[None, None, None, None, None, [["Selam Dunya", None]], None, None, None, []]]],
    "tr",
    1,
    "en",
]

# Degenerate shape: inner[1][0][0] is the translation string itself.
_INNER_DIRECT = [None, [["Direkt ceviri"]]]


def test_parse_batchexecute_sentence_path():
    assert (
        GoogleTranslator._parse_batchexecute_text(_be_body(_INNER_SENTENCES))
        == "Selam Dunya"
    )


def test_parse_batchexecute_direct_fallback():
    assert (
        GoogleTranslator._parse_batchexecute_text(_be_body(_INNER_DIRECT))
        == "Direkt ceviri"
    )


def test_parse_batchexecute_garbage_returns_none():
    assert GoogleTranslator._parse_batchexecute_text(None) is None
    assert GoogleTranslator._parse_batchexecute_text("") is None
    assert GoogleTranslator._parse_batchexecute_text(')]}\'\n\n5\n[["di",4]]') is None


def test_extract_batchexecute_language():
    inner = [[None, None, "EN"]]
    assert GoogleTranslator._extract_batchexecute_lang(_be_body(inner)) == "en"
    assert GoogleTranslator._extract_batchexecute_lang(None) is None


def test_batchexecute_rescues_when_clients5_also_blocked(monkeypatch):
    g = _make_translator()
    # clients5 answers with an empty payload (extraction -> None); only the
    # batchexecute POST returns a valid envelope.
    session = RoutedSession(c5_data=[], be_raw=_be_body(_INNER_SENTENCES))
    calls = []

    orig_get = session.get
    orig_post = session.post

    def tracking_get(url=None, **kwargs):
        calls.append(str(url))
        return orig_get(url=url, **kwargs)

    def tracking_post(url=None, **kwargs):
        calls.append(str(url))
        return orig_post(url=url, **kwargs)

    session.get = tracking_get
    session.post = tracking_post

    async def fake_get_session():
        return session

    monkeypatch.setattr(g, "_get_session", fake_get_session)

    async def fast_sleep(_delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    g._consecutive_429_count = RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD
    g._primary_probe_at = time.time() + 9999.0

    request = TranslationRequest(
        text="hello world",
        source_lang="en",
        target_lang="tr",
        engine=TranslationEngine.GOOGLE,
    )
    result = asyncio.run(g.translate_single(request))

    assert result.success is True
    assert result.translated_text == "Selam Dunya"
    assert any("batchexecute" in c for c in calls)
    assert g._alternate_rescues == 1
