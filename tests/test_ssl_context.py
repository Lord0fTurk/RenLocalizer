"""CA store selection for packaged Linux builds (GitHub #23)."""

import ssl

import pytest

from src.utils import net


@pytest.fixture(autouse=True)
def fresh_context(monkeypatch):
    monkeypatch.setattr(net, "_ssl_context", None)
    monkeypatch.setattr(net, "ssl_context_source", "")
    yield


def _loads(monkeypatch):
    """Record load_verify_locations calls instead of parsing real PEM files."""
    calls = []
    # Windows' create_default_context feeds the OS store through cadata=; ignore that.
    monkeypatch.setattr(
        ssl.SSLContext,
        "load_verify_locations",
        lambda self, cafile=None, **kw: calls.append(cafile) if cafile else None,
    )
    return calls


def test_default_paths_win_when_they_hold_certificates(monkeypatch):
    calls = _loads(monkeypatch)
    monkeypatch.setattr(net, "_default_paths_have_certs", lambda ctx: True)
    ctx = net.build_ssl_context()
    assert net.ssl_context_source == "default"
    assert calls == []
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_distro_bundle_is_used_when_default_paths_are_empty(monkeypatch, tmp_path):
    calls = _loads(monkeypatch)
    bundle = tmp_path / "ca.pem"
    bundle.write_text("x")
    monkeypatch.setattr(net, "_default_paths_have_certs", lambda ctx: False)
    monkeypatch.setattr(net, "_CA_FILE_CANDIDATES", ("/nope/a.pem", str(bundle)))
    net.build_ssl_context()
    assert calls == [str(bundle)]
    assert net.ssl_context_source == str(bundle)


def test_certifi_is_the_last_resort(monkeypatch, tmp_path):
    calls = _loads(monkeypatch)
    cert = tmp_path / "cacert.pem"
    cert.write_text("x")
    monkeypatch.setattr(net, "_default_paths_have_certs", lambda ctx: False)
    monkeypatch.setattr(net, "_CA_FILE_CANDIDATES", ("/nope/a.pem",))
    monkeypatch.setattr(net, "_certifi_path", lambda: str(cert))
    net.build_ssl_context()
    assert calls == [str(cert)]
    assert net.ssl_context_source.startswith("certifi:")


def test_unreadable_bundle_falls_through_to_next(monkeypatch, tmp_path):
    bad, good = tmp_path / "bad.pem", tmp_path / "good.pem"
    bad.write_text("x")
    good.write_text("x")
    seen = []

    def fake(self, cafile=None, **kw):
        if not cafile:
            return
        seen.append(cafile)
        if cafile == str(bad):
            raise ssl.SSLError("bad pem")

    monkeypatch.setattr(ssl.SSLContext, "load_verify_locations", fake)
    monkeypatch.setattr(net, "_default_paths_have_certs", lambda ctx: False)
    monkeypatch.setattr(net, "_CA_FILE_CANDIDATES", (str(bad), str(good)))
    net.build_ssl_context()
    assert seen == [str(bad), str(good)]
    assert net.ssl_context_source == str(good)


def test_context_is_cached(monkeypatch):
    monkeypatch.setattr(net, "_default_paths_have_certs", lambda ctx: True)
    assert net.build_ssl_context() is net.build_ssl_context()


def test_real_context_verifies_and_has_some_ca_source():
    ctx = net.build_ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert net.ssl_context_source != "none"


def test_capath_detection_needs_hashed_names(monkeypatch, tmp_path):
    (tmp_path / "1a2b3c4d.0").write_text("x")
    paths = ssl.DefaultVerifyPaths(None, str(tmp_path), "SSL_CERT_FILE", "/nope", "SSL_CERT_DIR", str(tmp_path))
    monkeypatch.setattr(ssl, "get_default_verify_paths", lambda: paths)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    assert net._default_paths_have_certs(ctx)
    (tmp_path / "1a2b3c4d.0").unlink()
    (tmp_path / "readme.txt").write_text("x")
    assert not net._default_paths_have_certs(ctx)


def test_certificate_error_detection():
    import aiohttp

    assert net.is_certificate_error(ssl.SSLCertVerificationError("x"))
    assert not net.is_certificate_error(ConnectionRefusedError())
    assert not net.is_certificate_error(aiohttp.ClientError("boom"))
    wrapped = aiohttp.ClientError("wrapper")
    wrapped.__cause__ = ssl.SSLCertVerificationError("x")
    assert net.is_certificate_error(wrapped)


def test_translator_logs_tls_error_once_and_skips_backoff(caplog):
    from src.core.translators.base import BaseTranslator

    class Dummy(BaseTranslator):
        async def translate_single(self, *a, **k): ...
        async def translate_batch(self, *a, **k): ...
        def get_supported_languages(self): return {}

    BaseTranslator._tls_error_reported = False
    d = Dummy()
    err = ssl.SSLCertVerificationError("unable to get local issuer certificate")
    with caplog.at_level("ERROR"):
        assert d.note_tls_error(err) is True
        assert d.note_tls_error(err) is True
    assert sum("SSL_CERT_FILE" in r.message for r in caplog.records) == 1
    assert d.note_tls_error(ValueError("other")) is False
    BaseTranslator._tls_error_reported = False
