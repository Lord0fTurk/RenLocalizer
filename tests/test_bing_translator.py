# -*- coding: utf-8 -*-
"""
Tests for the keyless Bing / Microsoft Edge translation engine (v2.8.17).

The live contract (verified 2026-09-21):
    POST https://edge.microsoft.com/translate/translatetext?isEnterpriseClient=false&to=<lang>[&from=<lang>]
    body: JSON array of strings
    resp: [{"translations": [{"text": "..."}]}, ...]
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock


from src.core.syntax_guard import protect_renpy_syntax
from src.core.translator import (
    BingTranslator,
    TranslationEngine,
    TranslationRequest,
    TranslationResult,
)


class DummyResp:
    def __init__(self, status, data=None, text=""):
        self.status = status
        self._data = data
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, content_type=None):
        return self._data

    async def text(self):
        return self._text


class DummySession:
    """Replays a scripted list of responses; records every POST."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def post(self, url, data=None, headers=None, proxy=None, timeout=None):
        payload = json.loads(data.decode("utf-8")) if isinstance(data, bytes) else data
        self.calls.append({"url": url, "payload": payload, "headers": headers})
        if callable(self.responses[0]):
            return self.responses.pop(0)(payload)
        return self.responses.pop(0)

    async def close(self):
        self.closed = True


def _echo_translation(payload):
    """Fake service: prefixes each text with 'TR:' (keeps ⟦…⟧ tokens intact)."""
    return DummyResp(200, [{"translations": [{"text": f"TR:{t}", "to": "tr"}]} for t in payload])


def _make(monkeypatch, responses, **attrs):
    t = BingTranslator()
    for k, v in attrs.items():
        setattr(t, k, v)
    session = DummySession(responses)

    async def fake_get_session():
        return session

    monkeypatch.setattr(t, "_get_session", fake_get_session)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())  # no real backoff waits
    return t, session


def _preprotected(source, src="en", tgt="tr"):
    prot, ph = protect_renpy_syntax(source)
    return TranslationRequest(
        text=prot, source_lang=src, target_lang=tgt, engine=TranslationEngine.BING,
        metadata={"preprotected": True, "original_text": source, "placeholders": ph},
    )


class TestRequestContract:
    def test_url_and_body_shape(self, monkeypatch):
        t, session = _make(monkeypatch, [_echo_translation])
        reqs = [TranslationRequest("Hello", "en", "tr", TranslationEngine.BING),
                TranslationRequest("World", "en", "tr", TranslationEngine.BING)]
        results = asyncio.run(t.translate_batch(reqs))

        call = session.calls[0]
        assert call["url"].startswith("https://edge.microsoft.com/translate/translatetext?")
        assert "isEnterpriseClient=false" in call["url"]
        assert "to=tr" in call["url"] and "from=en" in call["url"]
        assert "textType" not in call["url"]  # plain text: raw ⟦…⟧ tokens survive, HTML spans do not
        assert "Authorization" not in call["headers"]
        assert call["payload"] == ["Hello", "World"]
        assert [r.translated_text for r in results] == ["TR:Hello", "TR:World"]
        assert all(r.engine == TranslationEngine.BING and r.success for r in results)

    def test_auto_source_omits_from(self, monkeypatch):
        t, session = _make(monkeypatch, [_echo_translation])
        asyncio.run(t.translate_single(TranslationRequest("Hallo", "auto", "tr", TranslationEngine.BING)))
        assert "from=" not in session.calls[0]["url"]

    def test_language_code_mapping(self):
        assert BingTranslator._map_lang("zh-CN") == "zh-Hans"
        assert BingTranslator._map_lang("zh-TW") == "zh-Hant"
        assert BingTranslator._map_lang("pt-BR") == "pt"
        assert BingTranslator._map_lang("no") == "nb"
        assert BingTranslator._map_lang("tl") == "fil"
        assert BingTranslator._map_lang("tr") == "tr"
        assert BingTranslator._map_lang("auto") is None


class TestPlaceholders:
    def test_preprotected_tokens_are_restored(self, monkeypatch):
        t, session = _make(monkeypatch, [_echo_translation])
        source = "Hello [player_name], {color=#f00}welcome{/color}!"
        req = _preprotected(source)
        res = asyncio.run(t.translate_single(req))

        # Raw tokens go over the wire untouched (no span wrapping, no entity escaping)
        assert session.calls[0]["payload"] == [req.text]
        assert "<span" not in session.calls[0]["payload"][0]
        assert res.success is True
        assert res.original_text == source
        # restore_renpy_syntax may normalise trailing punctuation around closing tags;
        # what matters is that every Ren'Py token came back and no ⟦…⟧ residue remains.
        assert res.translated_text.startswith("TR:Hello [player_name], {color=#f00}welcome")
        assert "{/color}" in res.translated_text
        assert "⟦" not in res.translated_text

    def test_lost_placeholder_is_recovered_or_delegated(self, monkeypatch):
        """A dropped token is repaired by injection; if that fails, the fallback engine is used."""
        def drop_all_tokens(payload):
            import re
            return DummyResp(200, [{"translations": [{"text": re.sub(r"⟦[^⟧]+⟧", "", p) + " x"}]} for p in payload])

        t, _ = _make(monkeypatch, [drop_all_tokens])
        req = _preprotected("Press [key] now")
        res = asyncio.run(t.translate_single(req))
        # inject_missing_placeholders re-adds the token, so the result stays usable and valid
        assert res.success is True
        assert "[key]" in res.translated_text
        assert "⟦" not in res.translated_text


class TestChunking:
    def test_splits_by_item_limit(self, monkeypatch):
        t, session = _make(monkeypatch, [_echo_translation] * 3, MAX_ITEMS_PER_REQUEST=2, CONCURRENT_CHUNKS=1)
        reqs = [TranslationRequest(f"L{i}", "en", "tr", TranslationEngine.BING) for i in range(5)]
        results = asyncio.run(t.translate_batch(reqs))
        assert len(session.calls) == 3
        assert [len(c["payload"]) for c in session.calls] == [2, 2, 1]
        assert [r.translated_text for r in results] == [f"TR:L{i}" for i in range(5)]

    def test_splits_by_char_budget(self, monkeypatch):
        t, session = _make(monkeypatch, [_echo_translation] * 2, MAX_CHARS_PER_REQUEST=25, CONCURRENT_CHUNKS=1)
        reqs = [TranslationRequest("a" * 10, "en", "tr", TranslationEngine.BING),
                TranslationRequest("b" * 10, "en", "tr", TranslationEngine.BING),
                TranslationRequest("c" * 10, "en", "tr", TranslationEngine.BING)]
        results = asyncio.run(t.translate_batch(reqs))
        assert [len(c["payload"]) for c in session.calls] == [2, 1]
        assert all(r.success for r in results)

    def test_oversize_400_splits_chunk_in_half(self, monkeypatch):
        responses = [
            DummyResp(400, text="Request exceeds the maximum allowed translation size."),
            _echo_translation,
            _echo_translation,
        ]
        t, session = _make(monkeypatch, responses, CONCURRENT_CHUNKS=1)
        reqs = [TranslationRequest(f"L{i}", "en", "tr", TranslationEngine.BING) for i in range(4)]
        results = asyncio.run(t.translate_batch(reqs))
        assert [len(c["payload"]) for c in session.calls] == [4, 2, 2]
        assert [r.translated_text for r in results] == [f"TR:L{i}" for i in range(4)]


class TestErrorsAndFallback:
    def test_429_then_success_retries(self, monkeypatch):
        t, session = _make(monkeypatch, [DummyResp(429, text="slow down"), _echo_translation])
        res = asyncio.run(t.translate_single(TranslationRequest("Hi", "en", "tr", TranslationEngine.BING)))
        assert len(session.calls) == 2
        assert res.success and res.translated_text == "TR:Hi"

    def test_persistent_429_without_fallback_reports_quota(self, monkeypatch):
        t, session = _make(monkeypatch, [DummyResp(429, text="x")] * 3)
        res = asyncio.run(t.translate_single(TranslationRequest("Hi", "en", "tr", TranslationEngine.BING)))
        assert len(session.calls) == 3
        assert res.success is False
        assert res.quota_exceeded is True
        assert res.translated_text == ""

    def test_bad_language_400_does_not_retry(self, monkeypatch):
        t, session = _make(monkeypatch, [DummyResp(400, text="")])
        res = asyncio.run(t.translate_single(TranslationRequest("Hi", "en", "zz", TranslationEngine.BING)))
        assert len(session.calls) == 1
        assert res.success is False and "400" in (res.error or "")

    def test_hard_failure_delegates_preprotected_requests_to_fallback(self, monkeypatch):
        t, _ = _make(monkeypatch, [DummyResp(403, text="blocked")])
        source = "Hello [player_name]!"
        req = _preprotected(source)

        fallback = MagicMock()
        fallback._engine = TranslationEngine.GOOGLE
        fallback.translate_batch = AsyncMock(return_value=[TranslationResult(
            original_text=source, translated_text="Merhaba [player_name]!",
            source_lang="en", target_lang="tr", engine=TranslationEngine.GOOGLE, success=True,
        )])
        t.set_fallback_translator(fallback)

        res = asyncio.run(t.translate_single(req))
        # Google receives the very same token-protected request (identical ⟦…⟧ scheme)
        sent = fallback.translate_batch.await_args.args[0]
        assert sent[0] is req
        assert res.success is True
        assert res.translated_text == "Merhaba [player_name]!"
        assert res.engine == TranslationEngine.BING
        assert res.metadata.get("fallback_engine") == "google"

    def test_only_failed_items_go_to_fallback(self, monkeypatch):
        def second_item_missing(payload):
            return DummyResp(200, [{"translations": [{"text": "TR:A"}]}, {"nope": True}])

        t, _ = _make(monkeypatch, [second_item_missing])
        fallback = MagicMock()
        fallback._engine = TranslationEngine.GOOGLE
        fallback.translate_batch = AsyncMock(return_value=[TranslationResult(
            "B", "FB:B", "en", "tr", TranslationEngine.GOOGLE, True)])
        t.set_fallback_translator(fallback)

        reqs = [TranslationRequest("A", "en", "tr", TranslationEngine.BING),
                TranslationRequest("B", "en", "tr", TranslationEngine.BING)]
        results = asyncio.run(t.translate_batch(reqs))
        assert [r.translated_text for r in results] == ["TR:A", "FB:B"]
        assert [r.text for r in fallback.translate_batch.await_args.args[0]] == ["B"]

    def test_stray_token_bracket_goes_to_fallback(self, monkeypatch):
        """A service reply that keeps every placeholder but leaves a stray ⟧ would be
        discarded by the pipeline guard (English source kept); Bing hands it to Google."""
        source = "Hello [player_name]!"
        req = _preprotected(source)

        def stray(payload):
            return DummyResp(200, [{"translations": [{"text": f"Merhaba {payload[0].split(' ', 1)[1]} ⟧"}]}])

        t, _ = _make(monkeypatch, [stray])
        fallback = MagicMock()
        fallback._engine = TranslationEngine.GOOGLE
        fallback.translate_batch = AsyncMock(return_value=[TranslationResult(
            source, "Merhaba [player_name]!", "en", "tr", TranslationEngine.GOOGLE, True)])
        t.set_fallback_translator(fallback)

        res = asyncio.run(t.translate_single(req))
        assert fallback.translate_batch.await_count == 1
        assert res.success and res.translated_text == "Merhaba [player_name]!"
        assert res.metadata.get("fallback_engine") == "google"

    def test_remnant_check_ignores_brackets_the_source_had(self):
        assert BingTranslator._has_token_remnant("a ⟧", "plain") is True
        assert BingTranslator._has_token_remnant("a ⟧", "src ⟧") is False
        assert BingTranslator._has_token_remnant("Merhaba [x]!", "Hello [x]!") is False

    def test_empty_batch(self):
        assert asyncio.run(BingTranslator().translate_batch([])) == []


class TestRegistration:
    def test_manager_batches_bing(self):
        from src.core.translators.manager import BingTranslator as ManagerBing
        assert ManagerBing is BingTranslator
        assert TranslationEngine.BING.value == "bing"

    def test_config_accepts_bing_and_caps_batch(self):
        from src.utils.config import get_effective_batch_size
        assert get_effective_batch_size(500, TranslationEngine.BING) == 100

    def test_settings_backend_keeps_bing_and_gemini_selection(self):
        """Persisted 'bing' / 'gemini' selections must survive startup (gemini used to revert to google)."""
        from src.backend.settings_backend import SettingsBackend

        for engine_str, expected in (("bing", TranslationEngine.BING), ("gemini", TranslationEngine.GEMINI)):
            cfg = SimpleNamespace(translation_settings=SimpleNamespace(selected_engine=engine_str))
            sb = SettingsBackend.__new__(SettingsBackend)
            sb.config = cfg
            sb.translation_manager = MagicMock()
            sb.logger = MagicMock()
            sb._engine_getter = SettingsBackend._engine_from_str
            resolved = sb._engine_getter(engine_str)
            assert resolved == expected
