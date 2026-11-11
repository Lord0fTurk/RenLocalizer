# -*- coding: utf-8 -*-
"""The proxy setting reaches every engine's requests. No network."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

from src.core.proxy_manager import ProxyManager
from src.core.translators.base import TranslationEngine, TranslationRequest

SRC = Path(__file__).resolve().parents[1] / "src"


def settings(**kw):
    base = dict(enabled=True, proxy_url="http://user:pw@10.0.0.1:8080", manual_proxies=[],
                auto_rotate=True, test_on_startup=False, update_interval=3600, max_failures=10)
    base.update(kw)
    return SimpleNamespace(**base)


def manager(**kw) -> ProxyManager:
    pm = ProxyManager()
    pm.configure_from_settings(settings(**kw))
    return pm


# ── ProxyManager ─────────────────────────────────────────────────────────────

def test_enabled_proxy_is_usable_right_after_configuring():
    # Nothing ever called update_proxy_list(), so the list used to stay empty.
    pm = manager()
    assert pm.get_next_proxy().url == "http://user:pw@10.0.0.1:8080"


def test_disabled_proxy_is_never_handed_out():
    pm = manager(enabled=False)
    assert pm.proxies == [] and pm.get_next_proxy() is None


def test_personal_proxy_comes_first_and_the_list_rotates():
    pm = manager(manual_proxies=["10.0.0.2:3128", "10.0.0.3:3128"])
    urls = [pm.get_next_proxy().url for _ in range(4)]
    assert urls[0] == "http://user:pw@10.0.0.1:8080"
    assert set(urls) == {"http://user:pw@10.0.0.1:8080", "http://10.0.0.2:3128", "http://10.0.0.3:3128"}


def test_unusable_entries_are_reported_not_used():
    pm = manager(manual_proxies=["socks5://10.0.0.9:1080", "not a proxy", "10.0.0.2:3128"])
    assert pm.rejected_entries == ["socks5://10.0.0.9:1080", "not a proxy"]
    assert len(pm.proxies) == 2
    # Still reported while the switch is off, so the settings page can warn.
    assert len(manager(enabled=False, manual_proxies=["socks5://h:1"]).rejected_entries) == 1


def test_settings_page_test_reports_each_proxy_without_credentials():
    pm = manager(manual_proxies=["10.0.0.2:3128"])

    async def fake_test(proxy, timeout=5):
        ok = proxy.host == "10.0.0.1"
        proxy.response_time = 0.12 if ok else 0
        return ok

    pm.test_proxy = fake_test
    results = asyncio.run(pm.test_configured())
    assert results == [
        {"label": "10.0.0.1:8080", "ok": True, "ms": 120},
        {"label": "10.0.0.2:3128", "ok": False, "ms": 0},
    ]
    assert len(pm.proxies) == 2  # a failed test does not drop the proxy


def test_proxy_test_checks_an_https_tunnel():
    # Every translation endpoint is HTTPS; a plain-HTTP check proves nothing.
    assert ProxyManager.HTTPS_TEST_URL.startswith("https://")


# ── engines ──────────────────────────────────────────────────────────────────

def test_bing_and_libretranslate_keep_their_proxy_and_config_managers():
    # Both passed (proxy_manager, config_manager) positionally into
    # BaseTranslator(api_key, proxy_manager, config_manager): the proxy manager
    # became the API key and the config manager became the "proxy manager".
    from src.core.translators.services import BingTranslator, LibreTranslateTranslator

    pm, cfg = manager(), object()
    for translator in (
        BingTranslator(proxy_manager=pm, config_manager=cfg),
        LibreTranslateTranslator(base_url="https://lt.example.org", proxy_manager=pm, config_manager=cfg),
    ):
        assert translator.proxy_manager is pm
        assert translator.config_manager is cfg
        assert translator._proxy_url() == "http://user:pw@10.0.0.1:8080"


def test_proxy_url_respects_the_per_translator_switch():
    from src.core.translators.services import BingTranslator

    t = BingTranslator(proxy_manager=manager())
    t.set_proxy_enabled(False)
    assert t._proxy_url() is None
    assert BingTranslator(proxy_manager=None)._proxy_url() is None


class _Resp:
    status = 200
    headers: dict = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, content_type=None):
        return {"choices": [{"message": {"content": "Merhaba"}}]}

    async def text(self):
        return ""


def test_nvidia_requests_go_through_the_proxy():
    from src.core.translators.nvidia import NvidiaTranslator

    seen = []

    class Session:
        def post(self, url, **kw):
            seen.append(kw.get("proxy"))
            return _Resp()

    t = NvidiaTranslator(api_key="nvapi-x", proxy_manager=manager(), rpm=100000)

    async def get_session():
        return Session()

    t._get_session = get_session
    req = TranslationRequest(text="Hello", source_lang="en", target_lang="tr", engine=TranslationEngine.NVIDIA)
    asyncio.run(t.probe_endpoint())
    out = asyncio.run(t.translate_batch([req]))
    assert out[0].success
    assert seen == ["http://user:pw@10.0.0.1:8080"] * 2


def test_openai_family_uses_the_proxy_but_local_servers_never_do(monkeypatch):
    import src.core.ai_translator as ai

    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(ai, "AsyncOpenAI", FakeClient)

    def http_client_for(translator):
        captured.clear()
        translator._get_client()
        return captured.get("http_client")

    remote = http_client_for(ai.OpenAITranslator(api_key="sk-x", proxy_manager=manager()))
    assert remote is not None  # built with proxy=...

    assert http_client_for(ai.OpenAITranslator(api_key="sk-x", proxy_manager=manager(enabled=False))) is None

    local = http_client_for(
        ai.LocalLLMTranslator(proxy_manager=manager(), base_url="http://127.0.0.1:11434/v1")
    )
    assert local is not None and local is not remote  # direct client (trust_env=False), no proxy


def test_every_google_request_carries_the_proxy_and_verifies_tls():
    source = (SRC / "core" / "translators" / "google.py").read_text(encoding="utf-8")
    calls = list(re.finditer(r"session\.(?:get|post)\(", source))
    assert len(calls) >= 9
    for match in calls:
        depth, i = 1, match.end()
        while depth:
            depth += {"(": 1, ")": -1}.get(source[i], 0)
            i += 1
        call = source[match.start():i]
        line = source.count("\n", 0, match.start()) + 1
        assert "proxy=" in call, f"google.py:{line} sends a request without the proxy"
    for path in (SRC / "core" / "translators").glob("*.py"):
        assert "ssl=False" not in path.read_text(encoding="utf-8"), f"{path.name} disables TLS verification"
