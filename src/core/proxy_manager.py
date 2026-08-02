"""
Proxy Manager v2.8.0
===================

Manages proxy rotation for translation requests to avoid rate limiting
and improve reliability.

v2.8.0 Changes:
- Removed free proxy fetching (GeoNode/Scraping) due to unreliability
- Focus on Personal and Manual proxies provided by the user
- Simplified update logic and terminology (Testing vs Refreshing)
"""

import asyncio
import aiohttp
import logging
import random
import time
import threading
from typing import List, Dict, Optional
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class ProxyInfo:
    """Information about a proxy server."""
    host: str
    port: int
    protocol: str = "http"
    country: str = ""
    last_used: float = 0
    success_count: int = 0
    failure_count: int = 0
    response_time: float = 0
    is_working: bool = True
    is_personal: bool = False  # Personal proxies are never auto-disabled
    uptime: float = 0.0  # GeoNode uptime percentage (0-100)
    _auth_url: str = ""  # URL with embedded auth (user:pass@host:port)

    @property
    def url(self) -> str:
        """Get proxy URL (auth-aware if available)."""
        if self._auth_url:
            return self._auth_url
        return f"{self.protocol}://{self.host}:{self.port}"

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        total = self.success_count + self.failure_count
        if total == 0:
            return 1.0
        return self.success_count / total


class ProxyManager:
    """Manages proxy servers for translation requests.

    This class is intentionally kept independent from the UI layer.
    Runtime behaviour can be tuned via ``configure_from_settings`` which
    accepts a ProxySettings-like object (from src.utils.config).
    """

    # Test URLs for proxy validation (HTTP — no TLS overhead)
    TEST_URLS = [
        "http://httpbin.org/ip",
        "http://api.ipify.org",
        "http://icanhazip.com",
        "http://checkip.amazonaws.com",
    ]

    # Batch test concurrency
    TEST_BATCH_SIZE = 30

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.proxies: List[ProxyInfo] = []
        self.current_proxy_index = 0
        self.proxy_update_interval = 3600  # 1 hour
        self.last_proxy_update = 0.0

        # Behaviour toggles (filled from config via configure_from_settings)
        self.auto_rotate: bool = True
        self.test_on_startup: bool = True
        self.max_failures: int = 10

        # User-provided personal proxy (single URL, highest priority)
        self.personal_proxy_url: str = ""

        # User-provided manual proxy list (host:port or full URLs)
        self.custom_proxy_strings: List[str] = []

        # Thread-safety for auto-refresh
        self._refresh_lock = threading.Lock()
        self._is_refreshing = False

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def configure_from_settings(self, proxy_settings) -> None:
        """Configure manager behaviour from a ProxySettings-like object."""
        try:
            if proxy_settings is None:
                return
            # Interval / limits
            self.proxy_update_interval = int(
                getattr(proxy_settings, "update_interval", self.proxy_update_interval) or self.proxy_update_interval
            )
            self.max_failures = int(
                getattr(proxy_settings, "max_failures", self.max_failures) or self.max_failures
            )
            # Behaviour flags
            self.auto_rotate = bool(getattr(proxy_settings, "auto_rotate", self.auto_rotate))
            self.test_on_startup = bool(getattr(proxy_settings, "test_on_startup", self.test_on_startup))

            # Personal proxy URL (e.g. http://user:pass@host:port)
            self.personal_proxy_url = str(getattr(proxy_settings, "proxy_url", "") or "").strip()

            # Manual proxy list (list of strings)
            manual = getattr(proxy_settings, "manual_proxies", None)
            if isinstance(manual, list):
                self.custom_proxy_strings = [str(x).strip() for x in manual if str(x).strip()]
        except Exception as e:
            self.logger.warning(f"Error configuring ProxyManager from settings: {e}")

    # ------------------------------------------------------------------
    # Proxy Testing
    # ------------------------------------------------------------------

    async def test_proxy(self, proxy: ProxyInfo, timeout: int = 5) -> bool:
        """Test if a proxy is working by making a real HTTP request."""
        test_url = random.choice(self.TEST_URLS)
        start_time = time.time()

        try:
            connector = aiohttp.TCPConnector(limit=1, ssl=False)
            timeout_obj = aiohttp.ClientTimeout(total=timeout)

            async with aiohttp.ClientSession(connector=connector, timeout=timeout_obj) as session:
                async with session.get(test_url, proxy=proxy.url) as response:
                    if response.status == 200:
                        proxy.response_time = time.time() - start_time
                        proxy.success_count += 1
                        proxy.is_working = True
                        return True
                    else:
                        proxy.failure_count += 1
                        proxy.is_working = False
                        return False

        except Exception as e:
            proxy.failure_count += 1
            proxy.is_working = False
            self.logger.debug(f"Proxy {proxy.url} failed test: {e}")
            return False

    # ------------------------------------------------------------------
    # Proxy String Parsing
    # ------------------------------------------------------------------

    def _parse_proxy_string(self, entry: str) -> Optional[ProxyInfo]:
        """Parse a proxy string (URL or host:port) into ProxyInfo."""
        entry = entry.strip()
        if not entry:
            return None

        protocol = "http"
        host = None
        port = None
        auth_url = ""

        try:
            if "://" in entry:
                parsed = urlparse(entry)
                protocol = parsed.scheme or "http"
                # Filter SOCKS — aiohttp doesn't support it natively
                if protocol.lower().startswith("socks"):
                    self.logger.debug(f"Skipping SOCKS proxy (not supported by aiohttp): {entry}")
                    return None
                host = parsed.hostname
                port = parsed.port
                # Preserve user:pass@host:port as auth URL
                if parsed.username:
                    auth_url = entry  # Keep the original URL with auth
            else:
                # Handle user:pass@host:port
                if "@" in entry:
                    user_part, host_part = entry.rsplit("@", 1)
                    if ":" in host_part:
                        host, port_str = host_part.split(":", 1)
                        host = host.strip()
                        port = int(port_str.strip())
                    auth_url = f"http://{entry}"
                elif ":" in entry:
                    host, port_str = entry.split(":", 1)
                    host = host.strip()
                    port = int(port_str.strip())

            if host and port and 1 <= port <= 65535:
                return ProxyInfo(
                    host=host, port=port, protocol=protocol,
                    _auth_url=auth_url
                )
        except Exception as e:
            self.logger.debug(f"Invalid proxy entry '{entry}': {e}")

        return None

    # ------------------------------------------------------------------
    # Proxy List Management
    # ------------------------------------------------------------------

    async def update_proxy_list(self) -> None:
        """Update the proxy list from private sources.

        Priority logic (v2.8.0):
        1. Personal proxy (proxy_url) — Highest priority, kept even if test fails
        2. Manual proxies (manual_proxies list) — Tested and used if working

        Note: Free proxies (GeoNode/Scraping) have been removed due to poor reliability.
        """
        self.logger.info("Updating private proxy list...")

        personal_proxies: List[ProxyInfo] = []
        manual_proxies: List[ProxyInfo] = []

        # ── 1. Personal proxy (highest priority) ──
        if self.personal_proxy_url:
            proxy = self._parse_proxy_string(self.personal_proxy_url)
            if proxy:
                proxy.is_personal = True
                personal_proxies.append(proxy)
                self.logger.info(f"Personal proxy loaded: {proxy.host}:{proxy.port}")

        # ── 2. Manual proxy list ──
        if self.custom_proxy_strings:
            self.logger.info(f"Loading {len(self.custom_proxy_strings)} custom proxies from settings")
            for entry in self.custom_proxy_strings:
                proxy = self._parse_proxy_string(entry)
                if proxy and proxy.url not in [p.url for p in personal_proxies]:
                    manual_proxies.append(proxy)

        all_candidates = personal_proxies + manual_proxies
        if not all_candidates:
            self.proxies = []
            self.last_proxy_update = time.time()
            self.logger.info("No proxies configured.")
            return

        # ── Test proxies ──
        working_proxies: List[ProxyInfo] = []

        # Test in batches
        for i in range(0, len(all_candidates), self.TEST_BATCH_SIZE):
            batch = all_candidates[i: i + self.TEST_BATCH_SIZE]
            tasks = [self.test_proxy(proxy, timeout=10 if proxy.is_personal else 5) for proxy in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for proxy, result in zip(batch, results):
                if result is True:
                    working_proxies.append(proxy)
                elif proxy.is_personal:
                    # Still keep personal proxy even if test fails — user explicitly set it
                    proxy.is_working = False
                    working_proxies.append(proxy)
                    self.logger.warning(f"Personal proxy FAILED test but kept: {proxy.url}")

        # Sort: personal first, then manual ones by response time
        personal = [p for p in working_proxies if p.is_personal]
        manual = [p for p in working_proxies if not p.is_personal]
        manual.sort(key=lambda p: (p.response_time if p.response_time > 0 else 999))

        self.proxies = personal + manual
        self.last_proxy_update = time.time()

        self.logger.info(
            f"Updated proxy list: {len(self.proxies)} active proxies ({len(personal)} personal)."
        )

    # ------------------------------------------------------------------
    # Proxy Selection
    # ------------------------------------------------------------------

    def get_next_proxy(self) -> Optional[ProxyInfo]:
        """Get the next proxy in rotation.

        - If auto_rotate is True: round-robin through working proxies
        - If auto_rotate is False: always return the first (best) proxy
        - Personal proxies are always preferred
        """
        if not self.proxies:
            return None

        # Check if auto-refresh is needed (thread-safe, non-blocking)
        if self.last_proxy_update > 0 and (time.time() - self.last_proxy_update > self.proxy_update_interval):
            self._schedule_background_refresh()

        # Filter working proxies (personal proxies always pass)
        working_proxies = [
            p for p in self.proxies
            if p.is_personal or (p.is_working and p.success_rate > 0.3)
        ]

        if not working_proxies:
            # Fallback: try any proxy
            working_proxies = self.proxies

        if not working_proxies:
            return None

        if self.auto_rotate:
            # Round-robin
            proxy = working_proxies[self.current_proxy_index % len(working_proxies)]
            self.current_proxy_index += 1
        else:
            # Always use the best (first) proxy
            proxy = working_proxies[0]

        proxy.last_used = time.time()
        return proxy

    def _schedule_background_refresh(self) -> None:
        """Schedule a background proxy refresh (thread-safe, non-blocking).

        Uses threading instead of asyncio.create_task to avoid
        'no running event loop' errors in sync contexts.
        """
        if self._is_refreshing:
            return

        with self._refresh_lock:
            if self._is_refreshing:
                return
            self._is_refreshing = True

        def _bg_refresh():
            try:
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(self.update_proxy_list())
                finally:
                    loop.close()
            except Exception as e:
                self.logger.warning(f"Background proxy refresh failed: {e}")
            finally:
                self._is_refreshing = False

        threading.Thread(target=_bg_refresh, daemon=True).start()

    # ------------------------------------------------------------------
    # Health Feedback
    # ------------------------------------------------------------------

    def mark_proxy_failed(self, proxy_or_url) -> None:
        """Mark a proxy as failed. Accepts ProxyInfo or URL string."""
        proxy = self._resolve_proxy(proxy_or_url)
        if proxy is None:
            return

        proxy.failure_count += 1

        # Never auto-disable personal proxies
        if proxy.is_personal:
            return

        # Disable free proxy if it fails too often
        failure_limit = self.max_failures or 10
        if proxy.failure_count > failure_limit and proxy.success_rate < 0.3:
            proxy.is_working = False
            self.logger.debug(f"Disabled proxy {proxy.url} due to high failure rate ({proxy.success_rate:.0%})")

    def mark_proxy_success(self, proxy_or_url) -> None:
        """Mark a proxy as successful. Accepts ProxyInfo or URL string."""
        proxy = self._resolve_proxy(proxy_or_url)
        if proxy is None:
            return

        proxy.success_count += 1
        proxy.is_working = True

    def _resolve_proxy(self, proxy_or_url) -> Optional[ProxyInfo]:
        """Resolve a proxy reference to a ProxyInfo instance."""
        if isinstance(proxy_or_url, ProxyInfo):
            return proxy_or_url
        if isinstance(proxy_or_url, str) and proxy_or_url:
            for p in self.proxies:
                if p.url == proxy_or_url:
                    return p
        return None

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Initialize the proxy manager."""
        self.logger.info("Initializing proxy manager...")
        if self.test_on_startup:
            await self.update_proxy_list()
        else:
            # Only load personal + custom proxies without full external fetch
            self.proxies = []
            if self.personal_proxy_url or self.custom_proxy_strings:
                await self.update_proxy_list()

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_proxy_stats(self) -> Dict:
        """Get proxy statistics."""
        total_count = len(self.proxies)
        working_count = len([p for p in self.proxies if p.is_working])
        personal_count = len([p for p in self.proxies if p.is_personal])

        if self.proxies:
            working = [p for p in self.proxies if p.is_working and p.response_time > 0]
            avg_response_time = sum(p.response_time for p in working) / len(working) if working else 0
            avg_success_rate = sum(p.success_rate for p in self.proxies) / total_count
        else:
            avg_response_time = 0
            avg_success_rate = 0

        return {
            'total_proxies': total_count,
            'working_proxies': working_count,
            'personal_proxies': personal_count,
            'avg_response_time': round(avg_response_time, 2),
            'avg_success_rate': round(avg_success_rate, 2),
            'last_update': self.last_proxy_update,
        }

    def get_adaptive_concurrency(self) -> int:
        """Suggest an adaptive concurrency limit based on proxy pool health."""
        if not getattr(self, "proxies", None):
            return 16
        working_count = len([p for p in self.proxies if p.is_working and p.success_rate > 0.5])
        if working_count >= 50:
            return 32
        elif working_count >= 20:
            return 16
        elif working_count >= 10:
            return 8
        elif working_count >= 5:
            return 4
        else:
            return 2

    def get_proxy_count(self) -> int:
        """Return total number of proxies (including non-working)."""
        return len(self.proxies)

    def is_proxy_enabled(self) -> bool:
        """Return True if at least one proxy is configured and available."""
        return len(self.proxies) > 0 and any(
            p.is_personal or p.is_working for p in self.proxies
        )
