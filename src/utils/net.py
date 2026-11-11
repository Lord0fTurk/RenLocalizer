"""Network helpers for talking to local / LAN model servers.

Windows VPN and proxy tools (v2rayN, Clash, Hiddify, corporate PAC...) set a
system proxy in the registry. httpx (used by the OpenAI SDK) and urllib read it
via urllib.request.getproxies() but do not apply the registry bypass list, so
requests to Ollama / LM Studio / llama-server on 127.0.0.1 were sent to the
proxy, failed, and were retried for minutes — the run looked busy while
nothing was translated. Local endpoints must never go through a proxy.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import ssl
import threading
import urllib.request
from typing import Optional
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# System CA bundles by distribution. A PyInstaller/AppImage build carries the
# OpenSSL of the machine that built it, whose compiled-in CA paths (Ubuntu:
# /usr/lib/ssl) do not exist on Arch/Fedora/SUSE, so every HTTPS request failed
# certificate verification there (GitHub #23). Same list truststore uses.
_CA_FILE_CANDIDATES = (
    "/etc/ssl/cert.pem",  # Alpine, Arch, Fedora 34+, RHEL 9+, BSD
    "/etc/ca-certificates/extracted/tls-ca-bundle.pem",  # Arch (source of the above)
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",  # Fedora 44+, RHEL 11+
    "/etc/pki/tls/cert.pem",  # older Fedora / RHEL / CentOS
    "/etc/ssl/certs/ca-certificates.crt",  # Debian, Ubuntu
    "/etc/ssl/ca-bundle.pem",  # SUSE
)

_ssl_lock = threading.Lock()
_ssl_context: Optional[ssl.SSLContext] = None
ssl_context_source = ""  # which layer supplied the CAs; for diagnostics


def _default_paths_have_certs(ctx: ssl.SSLContext) -> bool:
    """True when the context's default CA locations actually contain certificates."""
    try:
        if ctx.cert_store_stats().get("x509_ca", 0) > 0:
            return True  # Windows store / cafile already loaded
    except Exception:
        pass
    paths = ssl.get_default_verify_paths()
    if paths.cafile and os.path.isfile(paths.cafile):
        return True
    if paths.capath and os.path.isdir(paths.capath):
        try:
            # capath is lazy-loaded, so look for OpenSSL hashed names (e.g. 1a2b3c4d.0)
            return any(
                len(name) > 2 and name[-2] == "." and name[-1].isdigit()
                for name in os.listdir(paths.capath)
            )
        except OSError:
            return False
    return False


def _certifi_path() -> Optional[str]:
    try:
        import certifi

        path = certifi.where()
        return path if os.path.isfile(path) else None
    except Exception:
        return None


def build_ssl_context() -> ssl.SSLContext:
    """TLS context that verifies certificates on every distro (cached).

    Order: user ``SSL_CERT_FILE``/``SSL_CERT_DIR`` and OpenSSL defaults when they
    hold certificates, then known system bundles, then certifi. System CAs come
    first so corporate proxies / antivirus roots the user trusts keep working;
    certifi is the last resort, never ``verify=False``.
    """
    global _ssl_context, ssl_context_source
    if _ssl_context is not None:
        return _ssl_context
    with _ssl_lock:
        if _ssl_context is not None:
            return _ssl_context
        ctx = ssl.create_default_context()
        source = ""
        if _default_paths_have_certs(ctx):
            source = "default"
        else:
            for candidate in _CA_FILE_CANDIDATES:
                if os.path.isfile(candidate):
                    try:
                        ctx.load_verify_locations(cafile=candidate)
                        source = candidate
                        break
                    except (ssl.SSLError, OSError):
                        continue
            if not source:
                bundled = _certifi_path()
                if bundled:
                    try:
                        ctx.load_verify_locations(cafile=bundled)
                        source = f"certifi:{bundled}"
                    except (ssl.SSLError, OSError):
                        pass
        if not source:
            logger.warning("No CA certificates found; HTTPS verification will fail")
        else:
            logger.debug("TLS CA source: %s", source)
        ssl_context_source = source or "none"
        _ssl_context = ctx
        return ctx


def is_certificate_error(exc: BaseException) -> bool:
    """True for TLS certificate verification failures (aiohttp, ssl or urllib)."""
    import aiohttp

    if isinstance(exc, (aiohttp.ClientConnectorCertificateError, ssl.SSLCertVerificationError)):
        return True
    reason = getattr(exc, "reason", None)  # urllib.error.URLError wraps the ssl error
    if isinstance(reason, ssl.SSLCertVerificationError):
        return True
    cause = getattr(exc, "__cause__", None) or getattr(exc, "_os_error", None)
    return isinstance(cause, ssl.SSLCertVerificationError)


def is_local_endpoint(url: str) -> bool:
    """True for loopback, private-LAN, link-local and .local/.localhost hosts."""
    try:
        host = (urlsplit(url if "//" in (url or "") else f"http://{url}").hostname or "").strip().lower()
    except ValueError:
        return False
    if not host:
        return False
    if host == "localhost" or host.endswith((".localhost", ".local", ".lan", ".home.arpa")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Bare machine names ("gpu-box") only resolve on the LAN.
        return "." not in host
    return ip.is_loopback or ip.is_private or ip.is_link_local


_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def urlopen_direct(url_or_request, timeout: float):
    """urllib.request.urlopen that ignores system/env proxies (for local servers)."""
    return _NO_PROXY_OPENER.open(url_or_request, timeout=timeout)
