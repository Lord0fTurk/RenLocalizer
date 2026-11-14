# -*- coding: utf-8 -*-
"""API keys and proxy passwords live in the OS credential store, not config.json.

Every test uses an in-memory backend; the real store is never touched
(conftest sets RENLOCALIZER_NO_KEYRING=1 as a second line of defence).
"""
from __future__ import annotations

import json
import logging

import pytest

import src.utils.path_manager as path_manager
import src.utils.secret_store as secret_store
from src.utils.secret_store import SERVICE, SecretStore


class MemoryBackend:
    """Stands in for Credential Manager / Secret Service."""

    priority = 5

    def __init__(self, broken: bool = False):
        self.data: dict = {}
        self.broken = broken

    def get_password(self, service, name):
        assert service == SERVICE
        return self.data.get(name)

    def set_password(self, service, name, value):
        if self.broken:
            raise RuntimeError("store is locked")
        self.data[name] = value

    def delete_password(self, service, name):
        del self.data[name]


KEYS = {
    "deepl_api_key": "deepl-1234",
    "openai_api_key": "sk-test-openai",
    "gemini_api_key": "AIza-test-gemini",
    "nvidia_api_key": "nvapi-test-nvidia",
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A scratch data folder plus a way to build ConfigManagers on a chosen backend."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(path_manager, "get_data_path", lambda: data)
    monkeypatch.setattr(path_manager, "get_app_dir", lambda: tmp_path / "app")
    backend = MemoryBackend()

    def make(store_backend=backend):
        def factory(enabled=True, backend=None):
            if store_backend is None or not enabled:
                return SecretStore(enabled=False)
            return SecretStore(backend=store_backend)

        monkeypatch.setattr(secret_store, "SecretStore", factory)
        from src.utils.config import ConfigManager

        return ConfigManager()

    def on_disk():
        return json.loads((data / "config.json").read_text(encoding="utf-8"))

    def write(config: dict):
        (data / "config.json").write_text(json.dumps(config), encoding="utf-8")

    return type("Env", (), {"make": staticmethod(make), "on_disk": staticmethod(on_disk),
                            "write": staticmethod(write), "backend": backend, "data": data})


def test_plain_text_keys_move_to_the_store_on_first_start(env):
    env.write({"api_keys": dict(KEYS), "translation_settings": {"libretranslate_api_key": "lt-key"}})
    cfg = env.make()

    assert cfg.api_keys.openai_api_key == "sk-test-openai"          # still usable
    assert env.backend.data["api_keys.openai_api_key"] == "sk-test-openai"
    assert env.backend.data["translation_settings.libretranslate_api_key"] == "lt-key"
    disk = env.on_disk()
    assert all(value == "" for value in disk["api_keys"].values())   # gone from the file
    assert disk["translation_settings"]["libretranslate_api_key"] == ""
    raw = (env.data / "config.json").read_text(encoding="utf-8")
    assert not any(secret in raw for secret in list(KEYS.values()) + ["lt-key"])


def test_keys_come_back_from_the_store_on_the_next_start(env):
    env.write({"api_keys": dict(KEYS)})
    env.make()
    again = env.make()
    assert {k: getattr(again.api_keys, k) for k in KEYS} == KEYS


def test_a_key_entered_later_never_reaches_the_file(env):
    cfg = env.make()
    cfg.api_keys.nvidia_api_key = "nvapi-typed-in-settings"
    assert cfg.save_config()
    assert "nvapi-typed-in-settings" not in (env.data / "config.json").read_text(encoding="utf-8")
    assert env.make().api_keys.nvidia_api_key == "nvapi-typed-in-settings"


def test_clearing_a_key_removes_it_from_the_store(env):
    env.write({"api_keys": dict(KEYS)})
    cfg = env.make()
    cfg.api_keys.gemini_api_key = ""
    cfg.save_config()
    assert "api_keys.gemini_api_key" not in env.backend.data
    assert env.make().api_keys.gemini_api_key == ""


def test_without_a_store_keys_stay_in_the_file_as_before(env):
    env.write({"api_keys": dict(KEYS)})
    cfg = env.make(store_backend=None)
    cfg.save_config()
    assert env.on_disk()["api_keys"] == KEYS
    assert env.make(store_backend=None).api_keys.openai_api_key == "sk-test-openai"


def test_a_store_that_fails_never_costs_a_key(env):
    broken = MemoryBackend(broken=True)
    env.write({"api_keys": dict(KEYS)})
    cfg = env.make(store_backend=broken)
    assert cfg.api_keys.openai_api_key == "sk-test-openai"
    assert env.on_disk()["api_keys"] == KEYS            # kept in the file
    assert broken.data == {}


def test_a_key_typed_while_the_store_was_off_is_picked_up_later(env):
    env.write({"api_keys": {"openai_api_key": "sk-old"}})
    env.make()                                           # sk-old now in the store
    offline = env.make(store_backend=None)               # store unavailable this time
    offline.api_keys.openai_api_key = "sk-new"
    offline.save_config()                                # lands in the file
    back = env.make()
    assert back.api_keys.openai_api_key == "sk-new"
    assert env.backend.data["api_keys.openai_api_key"] == "sk-new"
    assert env.on_disk()["api_keys"]["openai_api_key"] == ""


def test_proxy_password_is_a_secret_but_a_bare_address_is_not(env):
    cfg = env.make()
    cfg.proxy_settings.proxy_url = "10.0.0.1:8080"
    cfg.save_config()
    assert env.on_disk()["proxy_settings"]["proxy_url"] == "10.0.0.1:8080"
    assert "proxy_settings.proxy_url" not in env.backend.data

    cfg.proxy_settings.proxy_url = "http://bob:s3cr3t@10.0.0.1:8080"
    cfg.proxy_settings.manual_proxies = ["10.0.0.2:3128", "http://amy:pw@10.0.0.3:3128"]
    cfg.save_config()
    disk = env.on_disk()["proxy_settings"]
    assert disk["proxy_url"] == "" and disk["manual_proxies"] == []
    assert "s3cr3t" not in (env.data / "config.json").read_text(encoding="utf-8")

    again = env.make()
    assert again.proxy_settings.proxy_url == "http://bob:s3cr3t@10.0.0.1:8080"
    assert again.proxy_settings.manual_proxies == ["10.0.0.2:3128", "http://amy:pw@10.0.0.3:3128"]


def test_dropping_the_proxy_password_does_not_leave_it_behind(env):
    cfg = env.make()
    cfg.proxy_settings.proxy_url = "http://bob:s3cr3t@10.0.0.1:8080"
    cfg.save_config()
    cfg.proxy_settings.proxy_url = "10.0.0.1:8080"       # same proxy, no login any more
    cfg.save_config()
    assert "proxy_settings.proxy_url" not in env.backend.data
    cfg.proxy_settings.proxy_url = ""
    cfg.save_config()
    assert env.make().proxy_settings.proxy_url == ""      # the old login does not return


def test_factory_reset_empties_the_store(env):
    env.write({"api_keys": dict(KEYS)})
    cfg = env.make()
    cfg.reset_to_defaults()
    assert env.backend.data == {}


def test_portable_installs_keep_their_keys_in_their_own_folder(env, monkeypatch):
    monkeypatch.setattr(path_manager, "get_app_dir", lambda: env.data)  # data folder == app folder
    env.write({"api_keys": dict(KEYS)})
    cfg = env.make()
    assert not cfg.secret_store.available
    cfg.save_config()
    assert env.on_disk()["api_keys"] == KEYS
    assert env.backend.data == {}


# ── SecretStore itself ───────────────────────────────────────────────────────

def test_store_is_off_under_the_test_switch_and_on_macos(monkeypatch):
    assert not SecretStore().available                    # conftest's switch
    monkeypatch.delenv(secret_store.DISABLE_ENV, raising=False)
    monkeypatch.setattr(secret_store.sys, "platform", "darwin")
    store = SecretStore()
    assert not store.available and "macOS" in store.reason


def test_store_refuses_what_the_platform_cannot_hold():
    store = SecretStore(backend=MemoryBackend())
    assert store.set("a", "x" * secret_store.MAX_SECRET_CHARS)
    assert not store.set("b", "x" * (secret_store.MAX_SECRET_CHARS + 1))
    assert not store.set("c", "")


def test_store_reports_a_write_it_cannot_read_back():
    class Forgetful(MemoryBackend):
        def set_password(self, service, name, value):
            pass

    assert not SecretStore(backend=Forgetful()).set("a", "value")


def test_store_errors_are_contained():
    class Exploding(MemoryBackend):
        def get_password(self, service, name):
            raise RuntimeError("dbus went away")

    store = SecretStore(backend=Exploding())
    assert store.get("a") is None
    assert not store.set("a", "value")
    store.delete("a")                                      # must not raise


# ── log masking ──────────────────────────────────────────────────────────────

def _masked(message, *args):
    from src.utils.logger import SensitiveDataFilter

    record = logging.LogRecord("t", logging.INFO, __file__, 1, message, args, None)
    SensitiveDataFilter().filter(record)
    return record.getMessage()


def test_logs_hide_nvidia_keys_and_proxy_passwords():
    assert "s3cr3t" not in _masked("proxy %s failed", "http://bob:s3cr3t@10.0.0.1:8080")
    assert _masked("proxy %s failed", "http://bob:s3cr3t@10.0.0.1:8080") == "proxy http://bob:***@10.0.0.1:8080 failed"
    assert "nvapi-***MASKED***" in _masked("key nvapi-AbCdEfGhIjKlMnOpQrStUvWxYz012345 rejected")


def test_logs_hide_secrets_inside_exceptions_and_keep_other_text():
    out = _masked("request failed: %s (try %d)", ValueError("bad key nvapi-AbCdEfGhIjKlMnOpQrStUvWxYz012345"), 2)
    assert "AbCdEf" not in out and out.endswith("(try 2)")
    plain = "GET https://translate.google.com/a?b=1 at 12:30:05 for user@example.com"
    assert _masked(plain) == plain
