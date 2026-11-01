"""Google 429 handling: client-id rotation and the hand-off of failed lines to Bing."""
import asyncio
import urllib.parse
from types import SimpleNamespace

from src.core.translators.base import IN_FALLBACK
from src.core.translator import (
    GoogleTranslator,
    TranslationEngine,
    TranslationRequest,
    TranslationResult,
)


def _make_translator() -> GoogleTranslator:
    cfg = SimpleNamespace(
        translation_settings=SimpleNamespace(
            use_multi_endpoint=False,
            enable_lingva_fallback=False,
            max_concurrent_threads=2,
            max_chars_per_request=1000,
            max_batch_size=50,
            aggressive_retry_translation=False,
            use_html_protection=False,
            request_delay=0.0,
        ),
        get_ui_text=lambda key, default: default,
    )
    g = GoogleTranslator(config_manager=cfg)
    g.google_endpoints = ["https://dummy"]
    return g


def _req(text, engine=TranslationEngine.GOOGLE):
    return TranslationRequest(text=text, source_lang="en", target_lang="tr", engine=engine, metadata={})


def _result(req, text, ok=True, engine=TranslationEngine.GOOGLE):
    return TranslationResult(
        original_text=req.text, translated_text=text if ok else "",
        source_lang="en", target_lang="tr", engine=engine, success=ok,
        error=None if ok else "failed", metadata=req.metadata,
    )


class FakeBing:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []
        self.in_fallback = []
        self.status_callback = None

    async def translate_batch(self, requests):
        self.calls.append([r.text for r in requests])
        self.in_fallback.append(IN_FALLBACK.get())
        return [_result(r, f"BING:{r.text}", self.ok, TranslationEngine.BING) for r in requests]


def _patch_google(monkeypatch, g, failing):
    async def fake_batch(requests):
        return [_result(r, f"G:{r.text}", r.text not in failing) for r in requests]

    async def fake_single(request):
        return _result(request, f"G:{request.text}", request.text not in failing)

    monkeypatch.setattr(g, "_translate_batch_google", fake_batch)
    monkeypatch.setattr(g, "_translate_single_google", fake_single)


def test_batch_hands_only_failed_lines_to_bing(monkeypatch):
    g = _make_translator()
    bing = FakeBing()
    g._bing_fallback = bing
    _patch_google(monkeypatch, g, failing={"b"})

    out = asyncio.run(g.translate_batch([_req("a"), _req("b"), _req("c")]))

    assert [r.translated_text for r in out] == ["G:a", "BING:b", "G:c"]
    assert bing.calls == [["b"]]
    assert bing.in_fallback == [True]
    assert out[1].success and out[1].engine == TranslationEngine.GOOGLE
    assert out[1].metadata["fallback_engine"] == "bing"


def test_single_falls_back_to_bing(monkeypatch):
    g = _make_translator()
    g._bing_fallback = FakeBing()
    _patch_google(monkeypatch, g, failing={"x"})

    res = asyncio.run(g.translate_single(_req("x")))

    assert res.success and res.translated_text == "BING:x"


def test_no_hand_off_while_already_inside_a_fallback(monkeypatch):
    """Bing -> Google must not bounce back to Bing."""
    g = _make_translator()
    bing = FakeBing()
    g._bing_fallback = bing
    _patch_google(monkeypatch, g, failing={"b"})

    async def run():
        token = IN_FALLBACK.set(True)
        try:
            return await g.translate_batch([_req("a"), _req("b")])
        finally:
            IN_FALLBACK.reset(token)

    out = asyncio.run(run())

    assert bing.calls == []
    assert out[0].success and not out[1].success


def test_hand_off_can_be_disabled(monkeypatch):
    g = _make_translator()
    bing = FakeBing()
    g._bing_fallback = bing
    g.bing_fallback_enabled = False
    _patch_google(monkeypatch, g, failing={"b"})

    out = asyncio.run(g.translate_batch([_req("b")]))

    assert bing.calls == [] and not out[0].success


def test_bing_that_fails_too_is_skipped_for_a_while(monkeypatch):
    g = _make_translator()
    bing = FakeBing(ok=False)
    g._bing_fallback = bing
    _patch_google(monkeypatch, g, failing={"b", "c"})

    first = asyncio.run(g.translate_batch([_req("b")]))
    second = asyncio.run(g.translate_batch([_req("c")]))

    assert not first[0].success and not second[0].success
    assert bing.calls == [["b"]]


class _Resp:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, content_type=None):
        return self._payload


class _ClientSession:
    """429 for the client ids in ``blocked``, a valid translation for the others."""

    def __init__(self, blocked):
        self.blocked = set(blocked)
        self.clients = []
        self.closed = False

    def get(self, url=None, **kwargs):
        client = urllib.parse.parse_qs(urllib.parse.urlparse(str(url)).query)["client"][0]
        self.clients.append(client)
        if client in self.blocked:
            return _Resp(429, [])
        return _Resp(200, [[["Merhaba", "Hello", None, None, 1]], None, "en"])

    async def close(self):
        self.closed = True


def _single_with(monkeypatch, blocked):
    g = _make_translator()
    g.bing_fallback_enabled = False
    session = _ClientSession(blocked)

    async def fake_get_session():
        return session

    monkeypatch.setattr(g, "_get_session", fake_get_session)
    res = asyncio.run(g._translate_single_google(_req("Hello")))
    return g, session, res


def test_gtx_429_rotates_to_another_client_id_without_tripping_the_ip_breaker(monkeypatch):
    g, session, res = _single_with(monkeypatch, blocked={"gtx"})

    assert res.success and res.translated_text == "Merhaba"
    assert session.clients == ["gtx", "at"]
    assert g._primary_client == "at"
    assert g._consecutive_429_count == 0
    assert g._global_cooldown_until == 0.0


def test_remembered_client_id_is_tried_first(monkeypatch):
    g = _make_translator()
    g.bing_fallback_enabled = False
    g._primary_client = "at"
    session = _ClientSession(blocked={"gtx"})

    async def fake_get_session():
        return session

    monkeypatch.setattr(g, "_get_session", fake_get_session)
    asyncio.run(g._translate_single_google(_req("Hello")))

    assert session.clients == ["at"]


def test_client_order_keeps_the_working_one_first():
    g = _make_translator()
    g._primary_client = "dict-chrome-ex"
    assert g._client_order() == ["dict-chrome-ex", "gtx", "at"]
