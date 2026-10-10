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
import urllib.request
from urllib.parse import urlsplit


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
