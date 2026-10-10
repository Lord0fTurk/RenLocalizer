# -*- coding: utf-8 -*-
"""
Tests for the built-in GGUF runner (v2.8.17).

Covers runtime acquisition (asset selection, SHA256 verification, archive
extraction safety) and the llama-server process lifecycle. Nothing here touches
the network or spawns a real process — urlopen and Popen are faked.
"""

import hashlib
import io
import json
import os
import sys
import tarfile
import time
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core import local_llm_server as lls
from src.core.local_llm_server import (
    LlamaServerError,
    LlamaServerManager,
    RuntimeAsset,
    available_backends,
    current_platform_key,
    find_server_binary,
    resolve_asset_name,
)
from src.core.constants import LLAMACPP_PINNED_BUILD


# ── helpers ──────────────────────────────────────────────────────────────

class FakeResponse:
    """Minimal urlopen() context manager."""

    def __init__(self, payload: bytes, status: int = 200, headers=None):
        self._buffer = io.BytesIO(payload)
        self.status = status
        self.headers = headers or {"Content-Length": str(len(payload))}

    def read(self, size=-1):
        return self._buffer.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _archive_bytes(names, asset_name: str = "") -> bytes:
    buffer = io.BytesIO()
    if asset_name and (asset_name.endswith(".tar.gz") or asset_name.endswith(".tgz")):
        with tarfile.open(fileobj=buffer, mode="w:gz") as tf:
            for name in names:
                data = b"binary"
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        return buffer.getvalue()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name in names:
            zf.writestr(name, "binary")
    return buffer.getvalue()


_zip_bytes = _archive_bytes



def _asset_for(payload: bytes, name="llama-test.zip") -> RuntimeAsset:
    return RuntimeAsset(
        name=name,
        url="https://example.invalid/" + name,
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


# ── asset selection ──────────────────────────────────────────────────────

class TestAssetSelection:
    def test_current_platform_has_backends(self):
        backends = available_backends()
        assert "cpu" in backends, "every desktop platform ships a CPU build"

    @pytest.mark.parametrize(
        "platform_key,backend,expected",
        [
            ("win-x64", "vulkan", f"llama-{LLAMACPP_PINNED_BUILD}-bin-win-vulkan-x64.zip"),
            ("win-x64", "cuda", f"llama-{LLAMACPP_PINNED_BUILD}-bin-win-cuda-12.4-x64.zip"),
            ("win-x64", "cpu", f"llama-{LLAMACPP_PINNED_BUILD}-bin-win-cpu-x64.zip"),
            ("linux-x64", "vulkan", f"llama-{LLAMACPP_PINNED_BUILD}-bin-ubuntu-vulkan-x64.tar.gz"),
            ("macos-arm64", "cpu", f"llama-{LLAMACPP_PINNED_BUILD}-bin-macos-arm64.tar.gz"),
        ],
    )
    def test_known_assets(self, platform_key, backend, expected):
        assert resolve_asset_name(backend, platform_key) == expected

    def test_unsupported_backend_falls_back_to_cpu(self):
        """macOS has no Vulkan/CUDA archive — the CPU (Metal) build is used."""
        name = resolve_asset_name("vulkan", "macos-arm64")
        assert name == f"llama-{LLAMACPP_PINNED_BUILD}-bin-macos-arm64.tar.gz"

    def test_platform_key_is_known(self):
        assert current_platform_key() in (
            "win-x64", "win-arm64", "linux-x64", "linux-arm64", "macos-x64", "macos-arm64",
        )


# ── download + verification ──────────────────────────────────────────────

class TestRuntimeDownload:
    def _release_payload(self, asset: RuntimeAsset) -> bytes:
        return json.dumps({
            "assets": [{
                "name": asset.name,
                "browser_download_url": asset.url,
                "size": asset.size,
                "digest": f"sha256:{asset.sha256}",
            }]
        }).encode()

    def test_downloads_verifies_and_extracts(self, tmp_path, monkeypatch):
        exe = lls._server_exe_name()
        asset_name = resolve_asset_name("cpu")
        payload = _archive_bytes([f"build/bin/{exe}", "build/bin/libllama.dll"], asset_name)
        asset = _asset_for(payload, asset_name)
        release = self._release_payload(asset)

        monkeypatch.setattr(lls, "runtime_root", lambda: tmp_path)
        responses = [FakeResponse(release), FakeResponse(payload)]
        monkeypatch.setattr(
            lls.urllib.request, "urlopen", lambda *a, **k: responses.pop(0)
        )

        manager = LlamaServerManager()
        binary = manager.download_runtime("cpu")

        assert binary.name == exe
        assert binary.is_file()
        assert manager.status == lls.STATUS_STOPPED
        # A second call reuses the extracted runtime instead of downloading again.
        assert manager.download_runtime("cpu") == binary

    def test_checksum_mismatch_aborts_and_cleans_up(self, tmp_path, monkeypatch):
        asset_name = resolve_asset_name("cpu")
        payload = _archive_bytes([lls._server_exe_name()], asset_name)
        asset = RuntimeAsset(
            name=asset_name,
            url="https://example.invalid/a.zip",
            size=len(payload),
            sha256="0" * 64,  # wrong on purpose
        )
        release = self._release_payload(asset)

        monkeypatch.setattr(lls, "runtime_root", lambda: tmp_path)
        responses = [FakeResponse(release), FakeResponse(payload)]
        monkeypatch.setattr(
            lls.urllib.request, "urlopen", lambda *a, **k: responses.pop(0)
        )

        manager = LlamaServerManager()
        with pytest.raises(LlamaServerError, match="Checksum mismatch"):
            manager.download_runtime("cpu")
        assert find_server_binary(tmp_path) is None, "nothing may be left behind"

    def test_missing_asset_in_release_is_reported(self, tmp_path, monkeypatch):
        monkeypatch.setattr(lls, "runtime_root", lambda: tmp_path)
        monkeypatch.setattr(
            lls.urllib.request, "urlopen",
            lambda *a, **k: FakeResponse(json.dumps({"assets": []}).encode()),
        )
        manager = LlamaServerManager()
        with pytest.raises(LlamaServerError, match="does not contain"):
            manager.download_runtime("cpu")

    def test_archive_without_server_binary_is_rejected(self, tmp_path, monkeypatch):
        asset_name = resolve_asset_name("cpu")
        payload = _archive_bytes(["build/bin/README.txt"], asset_name)
        asset = _asset_for(payload, asset_name)
        monkeypatch.setattr(lls, "runtime_root", lambda: tmp_path)
        responses = [FakeResponse(self._release_payload(asset)), FakeResponse(payload)]
        monkeypatch.setattr(
            lls.urllib.request, "urlopen", lambda *a, **k: responses.pop(0)
        )
        manager = LlamaServerManager()
        with pytest.raises(LlamaServerError, match="did not contain"):
            manager.download_runtime("cpu")


class TestSafeExtract:
    def test_zip_slip_entries_are_skipped(self, tmp_path):
        archive = tmp_path / "evil.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../escaped.txt", "nope")
            zf.writestr("llama-server", "ok")

        target = tmp_path / "out"
        lls._safe_extract(archive, target)

        assert not (tmp_path / "escaped.txt").exists()
        assert (target / "llama-server").is_file()

    def test_tar_slip_entries_are_skipped(self, tmp_path):
        archive = tmp_path / "evil.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            for name in ("../escaped.txt", "llama-server"):
                data = b"x"
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))

        target = tmp_path / "out"
        lls._safe_extract(archive, target)

        assert not (tmp_path / "escaped.txt").exists()
        assert (target / "llama-server").is_file()


# ── process lifecycle ────────────────────────────────────────────────────

class FakeProcess:
    _next_pid = 424242

    def __init__(self, exit_code=None):
        self._exit_code = exit_code
        self.terminated = False
        self.killed = False
        FakeProcess._next_pid += 1
        self.pid = FakeProcess._next_pid

    def poll(self):
        return self._exit_code

    def terminate(self):
        self.terminated = True
        self._exit_code = 0

    def kill(self):
        self.killed = True
        self._exit_code = -9

    def wait(self, timeout=None):
        return self._exit_code


class TestServerLifecycle:
    def _model(self, tmp_path) -> str:
        model = tmp_path / "model.gguf"
        model.write_bytes(b"gguf")
        return str(model)

    def _binary(self, tmp_path) -> Path:
        binary = tmp_path / lls._server_exe_name()
        binary.write_text("#!/bin/sh\n")
        return binary

    def test_command_matches_llama_server_flags(self, tmp_path):
        command = LlamaServerManager.build_command(
            self._binary(tmp_path), "m.gguf", 9001, gpu_layers=20, ctx_size=8192, parallel=4
        )
        assert command[1:] == [
            "-m", "m.gguf", "--host", "127.0.0.1", "--port", "9001",
            "-ngl", "20", "-c", "8192", "-np", "4",
        ]

    def test_context_is_passed_through_unscaled(self, tmp_path):
        """More slots must not change -c (verified: n_ctx_slot does not shrink with -np)."""
        for slots in (1, 3):
            command = LlamaServerManager.build_command(
                self._binary(tmp_path), "m.gguf", 1, ctx_size=4096, parallel=slots)
            assert command[command.index("-c") + 1] == "4096"

    def test_negative_gpu_layers_uses_auto_offload(self, tmp_path):
        """llama-server's own 'auto' fits what the GPU can hold (no hard-coded layer count)."""
        command = LlamaServerManager.build_command(self._binary(tmp_path), "m.gguf", 1, gpu_layers=-1)
        assert command[command.index("-ngl") + 1] == "auto"

    def test_start_waits_for_health_and_returns_base_url(self, tmp_path, monkeypatch):
        manager = LlamaServerManager()
        process = FakeProcess()
        monkeypatch.setattr(lls.subprocess, "Popen", lambda *a, **k: process)
        monkeypatch.setattr(manager, "_wait_for_health", lambda port, timeout=None: True)

        url = manager.start(
            model_path=self._model(tmp_path), binary=self._binary(tmp_path), port=9123
        )
        assert url == "http://127.0.0.1:9123/v1"
        assert manager.status == lls.STATUS_READY
        assert manager.is_running()

        # Same configuration: reuse the running process instead of restarting.
        assert manager.start(
            model_path=self._model(tmp_path), binary=self._binary(tmp_path), port=9123
        ) == url

    def test_start_fails_when_health_never_succeeds(self, tmp_path, monkeypatch):
        manager = LlamaServerManager()
        monkeypatch.setattr(lls.subprocess, "Popen", lambda *a, **k: FakeProcess())
        monkeypatch.setattr(manager, "_wait_for_health", lambda port, timeout=None: False)

        with pytest.raises(LlamaServerError):
            manager.start(model_path=self._model(tmp_path), binary=self._binary(tmp_path), port=9124)
        assert manager.status == lls.STATUS_ERROR
        assert not manager.is_running()

    def test_missing_model_is_rejected_before_launch(self, tmp_path, monkeypatch):
        manager = LlamaServerManager()
        popen = MagicMock()
        monkeypatch.setattr(lls.subprocess, "Popen", popen)

        with pytest.raises(LlamaServerError, match="No .gguf model"):
            manager.start(model_path="")
        with pytest.raises(LlamaServerError, match="not found"):
            manager.start(model_path=str(tmp_path / "missing.gguf"))
        popen.assert_not_called()

    def test_missing_binary_is_reported(self, tmp_path, monkeypatch):
        manager = LlamaServerManager()
        monkeypatch.setattr(lls, "runtime_root", lambda: tmp_path / "empty")
        with pytest.raises(LlamaServerError, match="llama-server was not found"):
            manager.start(model_path=self._model(tmp_path))

    def test_stop_is_idempotent(self, tmp_path, monkeypatch):
        manager = LlamaServerManager()
        process = FakeProcess()
        monkeypatch.setattr(lls.subprocess, "Popen", lambda *a, **k: process)
        monkeypatch.setattr(manager, "_wait_for_health", lambda port, timeout=None: True)
        manager.start(model_path=self._model(tmp_path), binary=self._binary(tmp_path), port=9125)

        manager.stop()
        manager.stop()  # must not raise
        assert process.terminated
        assert manager.status == lls.STATUS_STOPPED
        assert manager.base_url == ""

    def test_health_poll_accepts_200_and_tolerates_503(self, monkeypatch):
        """503 means the model is still loading; only 200 ends the wait."""
        manager = LlamaServerManager()
        manager._process = FakeProcess()
        attempts = {"n": 0}

        def fake_urlopen(url, timeout=None):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise lls.urllib.error.HTTPError(url, 503, "Loading model", None, None)
            return FakeResponse(b"{}", status=200)

        # Health polling bypasses system proxies, so it goes through urlopen_direct.
        monkeypatch.setattr(lls, "urlopen_direct", fake_urlopen)
        monkeypatch.setattr(lls.time, "sleep", lambda *_: None)

        assert manager._wait_for_health(9126, timeout=5) is True
        assert attempts["n"] == 3

    def test_health_poll_gives_up_when_process_dies(self, monkeypatch):
        manager = LlamaServerManager()
        manager._process = FakeProcess(exit_code=1)
        monkeypatch.setattr(lls.time, "sleep", lambda *_: None)
        assert manager._wait_for_health(9127, timeout=5) is False


class TestBinaryResolution:
    def test_user_path_wins(self, tmp_path):
        binary = tmp_path / lls._server_exe_name()
        binary.write_text("x")
        manager = LlamaServerManager()
        assert manager.resolve_binary(str(binary)) == binary

    def test_user_directory_is_searched(self, tmp_path):
        nested = tmp_path / "bin"
        nested.mkdir()
        binary = nested / lls._server_exe_name()
        binary.write_text("x")
        manager = LlamaServerManager()
        assert manager.resolve_binary(str(tmp_path)) == binary

    def test_downloaded_runtime_is_found(self, tmp_path, monkeypatch):
        root = tmp_path / f"{LLAMACPP_PINNED_BUILD}-vulkan"
        target = root / "build" / "bin"
        target.mkdir(parents=True)
        binary = target / lls._server_exe_name()
        binary.write_text("x")
        (root / lls._COMPLETE_MARKER).write_text("ok")
        monkeypatch.setattr(lls, "runtime_root", lambda: tmp_path)

        manager = LlamaServerManager()
        assert manager.resolve_binary("", "vulkan") == binary
        assert manager.resolve_binary("", "cuda") is None

    def test_half_extracted_runtime_is_not_used(self, tmp_path, monkeypatch):
        """An interrupted download leaves the exe without its DLLs — never reuse it."""
        root = tmp_path / f"{LLAMACPP_PINNED_BUILD}-vulkan"
        root.mkdir(parents=True)
        (root / lls._server_exe_name()).write_text("x")  # no completion marker
        monkeypatch.setattr(lls, "runtime_root", lambda: tmp_path)

        assert LlamaServerManager().resolve_binary("", "vulkan") is None


class TestConfigAndBackend:
    def test_config_validates_runner_fields(self):
        from src.utils.config import TranslationSettings

        ts = TranslationSettings(
            local_llm_mode="BUILTIN", local_llm_backend="bogus",
            local_llm_ctx_size=10, local_llm_gpu_layers=-7,
        )
        assert ts.local_llm_mode == "builtin"
        assert ts.local_llm_backend == "vulkan"
        assert ts.local_llm_ctx_size == 512
        assert ts.local_llm_gpu_layers == -1

    def test_settings_backend_roundtrip(self):
        from src.backend.settings_backend import SettingsBackend

        cfg = MagicMock()
        cfg.translation_settings.selected_engine = "local_llm"
        backend = SettingsBackend(cfg, MagicMock())

        backend.set_local_llm_mode("builtin")
        backend.set_local_llm_backend("cuda")
        backend.set_local_llm_gpu_layers(35)
        backend.set_local_llm_ctx_size(8192)
        backend.set_local_llm_gguf_path("  C:/models/x.gguf  ")

        assert backend.get_local_llm_mode() == "builtin"
        assert backend.get_local_llm_backend() == "cuda"
        assert backend.get_local_llm_gpu_layers() == 35
        assert backend.get_local_llm_ctx_size() == 8192
        assert backend.get_local_llm_gguf_path() == "C:/models/x.gguf"

    def test_settings_backend_rejects_unknown_values(self):
        from src.backend.settings_backend import SettingsBackend

        cfg = MagicMock()
        cfg.translation_settings.selected_engine = "local_llm"
        backend = SettingsBackend(cfg, MagicMock())
        backend.set_local_llm_mode("nonsense")
        backend.set_local_llm_backend("nonsense")
        assert backend.get_local_llm_mode() == "external"
        assert backend.get_local_llm_backend() == "vulkan"


class TestOrphanPrevention:
    """A hard kill of RenLocalizer must not leave llama-server holding VRAM."""

    def _stub_start(self, manager, tmp_path, monkeypatch, process):
        monkeypatch.setattr(lls.subprocess, "Popen", lambda *a, **k: process)
        monkeypatch.setattr(manager, "_wait_for_health", lambda port, timeout=None: True)
        model = tmp_path / "m.gguf"
        model.write_bytes(b"x")
        binary = tmp_path / lls._server_exe_name()
        binary.write_text("x")
        return str(model), binary

    def test_pidfile_is_written_on_start_and_cleared_on_stop(self, tmp_path, monkeypatch):
        pidfile = tmp_path / "llama-server.pid"
        monkeypatch.setattr(lls, "_pidfile_path", lambda: pidfile)
        manager = LlamaServerManager()
        process = FakeProcess()
        model, binary = self._stub_start(manager, tmp_path, monkeypatch, process)

        manager.start(model_path=model, binary=binary, port=9200)
        assert pidfile.read_text(encoding="utf-8").strip() == str(process.pid)

        manager.stop()
        assert not pidfile.exists()

    def test_cleanup_kills_only_a_real_llama_server(self, tmp_path, monkeypatch):
        pidfile = tmp_path / "llama-server.pid"
        pidfile.write_text("4242", encoding="utf-8")
        monkeypatch.setattr(lls, "_pidfile_path", lambda: pidfile)

        killed = []
        monkeypatch.setattr(lls.subprocess, "run", lambda *a, **k: killed.append(a))
        monkeypatch.setattr(lls.os, "kill", lambda *a: killed.append(a))

        # The pid now belongs to something else -> must NOT be killed.
        monkeypatch.setattr(lls, "_process_image_name", lambda pid: "chrome.exe")
        assert lls.cleanup_stale_server() is False
        assert killed == []
        assert not pidfile.exists(), "a stale pid file is always cleared"

        # A genuine leftover -> killed.
        pidfile.write_text("4242", encoding="utf-8")
        monkeypatch.setattr(lls, "_process_image_name", lambda pid: "llama-server.exe")
        assert lls.cleanup_stale_server() is True
        assert killed, "the leftover server should have been terminated"

    def test_cleanup_is_a_noop_without_a_pidfile(self, tmp_path, monkeypatch):
        monkeypatch.setattr(lls, "_pidfile_path", lambda: tmp_path / "absent.pid")
        assert lls.cleanup_stale_server() is False

    def test_cleanup_ignores_a_dead_pid(self, tmp_path, monkeypatch):
        pidfile = tmp_path / "llama-server.pid"
        pidfile.write_text("4242", encoding="utf-8")
        monkeypatch.setattr(lls, "_pidfile_path", lambda: pidfile)
        monkeypatch.setattr(lls, "_process_image_name", lambda pid: None)
        assert lls.cleanup_stale_server() is False


class TestFailureDiagnostics:
    def test_server_output_is_included_in_the_error(self, tmp_path, monkeypatch):
        """Without the server's own log, "it does not start" is undebuggable."""
        manager = LlamaServerManager()
        monkeypatch.setattr(lls, "_pidfile_path", lambda: tmp_path / "p.pid")
        monkeypatch.setattr(lls.subprocess, "Popen", lambda *a, **k: FakeProcess(exit_code=1))
        monkeypatch.setattr(manager, "_wait_for_health", lambda port, timeout=None: False)
        monkeypatch.setattr(
            manager, "_read_log_tail", lambda lines=6: "ggml_vulkan: no devices found"
        )

        model = tmp_path / "m.gguf"
        model.write_bytes(b"x")
        binary = tmp_path / lls._server_exe_name()
        binary.write_text("x")

        with pytest.raises(LlamaServerError, match="no devices found"):
            manager.start(model_path=str(model), binary=binary, port=9201)
        assert "exited with code 1" in manager.last_error

    def test_log_tail_reads_the_last_lines(self, tmp_path):
        manager = LlamaServerManager()
        manager._log_path = tmp_path / "server.log"
        manager._log_path.write_text(
            "\n".join(f"line {i}" for i in range(20)), encoding="utf-8"
        )
        tail = manager._read_log_tail(lines=3)
        assert "line 19" in tail and "line 17" in tail and "line 5" not in tail


class TestPinnedBuildFallback:
    def test_falls_back_to_a_newer_build_when_the_pinned_one_lost_the_asset(
        self, tmp_path, monkeypatch
    ):
        exe = lls._server_exe_name()
        newer_build = "b99999"
        newer_name = resolve_asset_name("cpu", build=newer_build)
        payload = _archive_bytes([f"build/bin/{exe}"], newer_name)
        digest = hashlib.sha256(payload).hexdigest()

        pinned_release = json.dumps({"assets": []}).encode()
        listing = json.dumps([{
            "tag_name": newer_build,
            "assets": [{
                "name": newer_name,
                "browser_download_url": "https://example.invalid/new.zip",
                "size": len(payload),
                "digest": f"sha256:{digest}",
            }],
        }]).encode()

        monkeypatch.setattr(lls, "runtime_root", lambda: tmp_path)
        responses = [FakeResponse(pinned_release), FakeResponse(listing), FakeResponse(payload)]
        monkeypatch.setattr(lls.urllib.request, "urlopen", lambda *a, **k: responses.pop(0))

        manager = LlamaServerManager()
        binary = manager.download_runtime("cpu")

        assert binary.is_file()
        assert f"{newer_build}-cpu" in str(binary), "the newer build's directory is used"
        assert (tmp_path / f"{newer_build}-cpu" / lls._COMPLETE_MARKER).is_file()

    def test_error_is_actionable_when_no_build_has_the_asset(self, tmp_path, monkeypatch):
        monkeypatch.setattr(lls, "runtime_root", lambda: tmp_path)
        responses = [
            FakeResponse(json.dumps({"assets": []}).encode()),
            FakeResponse(json.dumps([]).encode()),
        ]
        monkeypatch.setattr(lls.urllib.request, "urlopen", lambda *a, **k: responses.pop(0))

        with pytest.raises(LlamaServerError, match="your own"):
            LlamaServerManager().download_runtime("cpu")

    def test_release_listing_error_object_does_not_crash(self, tmp_path, monkeypatch):
        """GitHub answers rate limits with an object, not a list."""
        monkeypatch.setattr(lls, "runtime_root", lambda: tmp_path)
        responses = [
            FakeResponse(json.dumps({"assets": []}).encode()),
            FakeResponse(json.dumps({"message": "API rate limit exceeded"}).encode()),
        ]
        monkeypatch.setattr(lls.urllib.request, "urlopen", lambda *a, **k: responses.pop(0))

        with pytest.raises(LlamaServerError):
            LlamaServerManager().download_runtime("cpu")


class TestConcurrency:
    def test_two_simultaneous_starts_spawn_one_server(self, tmp_path, monkeypatch):
        """The Start button and the pipeline setup thread can fire at the same time."""
        import threading

        manager = LlamaServerManager()
        monkeypatch.setattr(lls, "_pidfile_path", lambda: tmp_path / "p.pid")
        spawned = []

        def fake_popen(*args, **kwargs):
            time.sleep(0.05)  # widen the race window
            process = FakeProcess()
            spawned.append(process)
            return process

        monkeypatch.setattr(lls.subprocess, "Popen", fake_popen)
        monkeypatch.setattr(manager, "_wait_for_health", lambda port, timeout=None: True)

        model = tmp_path / "m.gguf"
        model.write_bytes(b"x")
        binary = tmp_path / lls._server_exe_name()
        binary.write_text("x")

        urls = []

        def go():
            urls.append(manager.start(model_path=str(model), binary=binary, port=9202))

        threads = [threading.Thread(target=go) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        assert len(spawned) == 1, "a second start must reuse the running server"
        assert len(set(urls)) == 1
        manager.stop()

    def test_clean_stop_removes_the_log_but_a_crash_keeps_it(self, tmp_path, monkeypatch):
        monkeypatch.setattr(lls, "_pidfile_path", lambda: tmp_path / "p.pid")
        model = tmp_path / "m.gguf"
        model.write_bytes(b"x")
        binary = tmp_path / lls._server_exe_name()
        binary.write_text("x")

        # Clean stop: no leftover log file.
        manager = LlamaServerManager()
        monkeypatch.setattr(lls.subprocess, "Popen", lambda *a, **k: FakeProcess())
        monkeypatch.setattr(manager, "_wait_for_health", lambda port, timeout=None: True)
        manager.start(model_path=str(model), binary=binary, port=9203)
        log_path = manager._log_path
        assert log_path and log_path.is_file()
        manager.stop()
        assert not log_path.exists()

        # Server died on its own: the log survives for post-mortem.
        crashed = LlamaServerManager()
        process = FakeProcess()
        monkeypatch.setattr(lls.subprocess, "Popen", lambda *a, **k: process)
        monkeypatch.setattr(crashed, "_wait_for_health", lambda port, timeout=None: True)
        crashed.start(model_path=str(model), binary=binary, port=9204)
        crash_log = crashed._log_path
        process._exit_code = 1  # simulate the server dying
        crashed.stop()
        assert crash_log and crash_log.is_file()
        crash_log.unlink()

    def test_startup_cleanup_prunes_only_old_logs(self, tmp_path, monkeypatch):
        import time as _time

        monkeypatch.setattr(lls.tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(lls, "_pidfile_path", lambda: tmp_path / "absent.pid")

        fresh = tmp_path / "renlocalizer-llama-1.log"
        old = tmp_path / "renlocalizer-llama-2.log"
        unrelated = tmp_path / "important.log"
        for path in (fresh, old, unrelated):
            path.write_text("x", encoding="utf-8")
        ancient = _time.time() - 48 * 3600
        os.utime(old, (ancient, ancient))
        os.utime(unrelated, (ancient, ancient))

        lls.cleanup_stale_server()

        assert fresh.is_file(), "a recent crash log is still useful"
        assert not old.exists()
        assert unrelated.is_file(), "only our own log files are pruned"
