# -*- coding: utf-8 -*-
"""Regressions from 2.8.18 user reports: "AI acts like it works but nothing gets translated".

* A Windows/VPN system proxy captured every request to Ollama / LM Studio /
  llama-server on 127.0.0.1 (httpx and urllib read the registry proxy but not
  its bypass list); runs retried for minutes and translated nothing.
* An unreachable AI endpoint silently fell back to Google for every line.
* TL mode treated Ren'Py "Generate Translations" templates (translation slot
  pre-filled with the source text) as already translated.
* The built-in server picked a new random port on every launch.
"""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.core.tl_parser import TranslationEntry
from src.utils.net import is_local_endpoint


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:1234/v1", "http://localhost:11434/v1", "http://[::1]:8080/v1",
    "http://192.168.1.20:1234/v1", "http://10.0.0.5/v1", "http://gpu-box:8080/v1",
    "http://studio.local:1234/v1",
])
def test_local_endpoints_detected(url):
    assert is_local_endpoint(url)


@pytest.mark.parametrize("url", [
    "https://api.openai.com/v1", "https://openrouter.ai/api/v1", "https://api.deepseek.com", "",
])
def test_cloud_endpoints_keep_proxy(url):
    assert not is_local_endpoint(url)


class _Models(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps({"object": "list", "data": [{"id": "m", "object": "model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def local_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Models)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()


def _local_translator(url):
    from src.core.ai_translator import LocalLLMTranslator
    from src.utils.config import ConfigManager

    config = ConfigManager()
    config.translation_settings.local_llm_mode = "external"
    config.translation_settings.local_llm_url = url
    return LocalLLMTranslator(config_manager=config)


def test_local_llm_ignores_system_proxy(local_server, monkeypatch):
    # What v2rayN/Clash/corporate proxies effectively do on Windows.
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
    translator = _local_translator(local_server)
    assert asyncio.run(translator.probe_endpoint(timeout=5)) is None


def test_unreachable_endpoint_is_reported_before_the_run():
    translator = _local_translator("http://127.0.0.1:9/v1")
    reason = asyncio.run(translator.probe_endpoint(timeout=5))
    assert reason and "cannot connect" in reason


def _entry(translated):
    return TranslationEntry(
        original_text="Go to the forest", translated_text=translated,
        file_path="tl/russian/script.rpy", line_number=1, entry_type="string",
    )


def test_renpy_template_copies_count_as_untranslated():
    copied = _entry("Go to the forest")
    done = _entry("Иди в лес")
    empty = _entry("")
    assert copied.is_source_copy() and not copied.needs_translation()
    assert not done.is_source_copy()
    assert not empty.is_source_copy() and empty.needs_translation()


def test_builtin_server_prefers_a_stable_port(monkeypatch):
    from src.core import local_llm_server as lls

    monkeypatch.setattr(lls, "_port_is_free", lambda port: True)
    assert lls._auto_port() == lls.LLAMACPP_DEFAULT_PORT

    monkeypatch.setattr(lls, "_port_is_free", lambda port: False)
    assert lls._auto_port() != lls.LLAMACPP_DEFAULT_PORT
