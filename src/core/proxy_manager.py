"""
Proxy Manager
=============

Manages proxy rotation for translation requests to avoid rate limiting
and improve reliability.
"""

import asyncio
import aiohttp
import logging
import random
import time
from typing import List, Dict, Optional
from dataclasses import dataclass
from urllib.parse import urlparse
import json

@dataclass
class ProxyInfo:
    """Information about a proxy server."""
    host: str
    port: int
    protocol: str
    country: str = ""
    last_used: float = 0
    success_count: int = 0
    failure_count: int = 0
    response_time: float = 0
    is_working: bool = True
    
    @property
    def url(self) -> str:
        """Get proxy URL."""
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
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.proxies: List[ProxyInfo] = []
        self.current_proxy_index = 0
        self.proxy_update_interval = 3600  # 1 hour
        self.last_proxy_update = 0
        
        # Proxy sources
        self.proxy_sources = [
            "https://proxylist.geonode.com/api/proxy-list?protocols=http%2Csocks4%2Csocks5&limit=500&page=1&sort_by=lastChecked&sort_type=desc",
            "https://api.proxyscrape.com/v2/?request=get&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all&format=textplain",
            "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
            "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt"
        ]
        
        # Behaviour toggles (filled from config via configure_from_settings)
        self.auto_rotate: bool = True
        self.test_on_startup: bool = True
        self.max_failures: int = 10

        # Test URLs for proxy validation
        self.test_urls = [
            "http://httpbin.org/ip",
            "http://api.ipify.org",
            "http://icanhazip.com",
            "http://checkip.amazonaws.com"
        ]

        # Optional user provided proxies (host:port or full URLs)
        self.custom_proxy_strings: List[str] = []

    def configure_from_settings(self, proxy_settings) -> None:
        """Configure manager behaviour from a ProxySettings-like object.

        This keeps core decoupled from ConfigManager while still allowing
        runtime tuning from the settings dialog.
        """
        try:
            if proxy_settings is None:
                return
            # Interval / limits
            self.proxy_update_interval = int(getattr(proxy_settings, "update_interval", self.proxy_update_interval) or self.proxy_update_interval)
            self.max_failures = int(getattr(proxy_settings, "max_failures", self.max_failures) or self.max_failures)
            # Behaviour flags
            self.auto_rotate = bool(getattr(proxy_settings, "auto_rotate", self.auto_rotate))
            self.test_on_startup = bool(getattr(proxy_settings, "test_on_startup", self.test_on_startup))
            # Custom proxy list (list of strings)
            custom = getattr(proxy_settings, "custom_proxies", None)
            if isinstance(custom, list):
                self.custom_proxy_strings = [str(x).strip() for x in custom if str(x).strip()]
        except Exception as e:
            self.logger.warning(f"Error configuring ProxyManager from settings: {e}")
    
    async def fetch_proxies_from_geonode(self) -> List[ProxyInfo]:
        """Fetch proxies from GeoNode API."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.proxy_sources[0], timeout=30) as response:
                    if response.status == 200:
                        data = await response.json()
                        proxies = []
                        
                        for proxy_data in data.get('data', []):
                            try:
                                proxy = ProxyInfo(
                                    host=proxy_data['ip'],
                                    port=int(proxy_data['port']),
                                    protocol=proxy_data['protocols'][0] if proxy_data['protocols'] else 'http',
                                    country=proxy_data.get('country', '')
                                )
                                proxies.append(proxy)
                            except (KeyError, ValueError) as e:
                                self.logger.debug(f"Error parsing proxy data: {e}")
                                continue
                        
                        self.logger.info(f"Fetched {len(proxies)} proxies from GeoNode")
                        return proxies
                        
        except Exception as e:
            self.logger.error(f"Error fetching proxies from GeoNode: {e}")
        
        return []
    
    async def fetch_proxies_from_text_source(self, url: str) -> List[ProxyInfo]:
        """Fetch proxies from text-based sources."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30) as response:
                    if response.status == 200:
                        text = await response.text()
                        proxies = []
                        
                        for line in text.strip().split('\n'):
                            line = line.strip()
                            if ':' in line:
                                try:
                                    host, port = line.split(':', 1)
                                    proxy = ProxyInfo(
                                        host=host.strip(),
                                        port=int(port.strip()),
                                        protocol='http'
                                    )
                                    proxies.append(proxy)
                                except ValueError:
                                    continue
                        
                        self.logger.info(f"Fetched {len(proxies)} proxies from text source")
                        return proxies
                        
        except Exception as e:
            self.logger.error(f"Error fetching proxies from {url}: {e}")
        
        return []
    
    async def test_proxy(self, proxy: ProxyInfo, timeout: int = 5) -> bool:
        """Test if a proxy is working."""
        test_url = random.choice(self.test_urls)
        start_time = time.time()
        
        try:
            connector = aiohttp.TCPConnector(limit=1, ssl=False)
            timeout_obj = aiohttp.ClientTimeout(total=timeout)
            
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout_obj
            ) as session:
                async with session.get(
                    test_url,
                    proxy=proxy.url
                ) as response:
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
    
    async def update_proxy_list(self) -> None:
        """Update the proxy list from various sources."""
        self.logger.info("Updating proxy list...")
        
        all_proxies = []

        # Load user-provided custom proxies first so they are preferred
        if self.custom_proxy_strings:
            self.logger.info(f"Loading {len(self.custom_proxy_strings)} custom proxies from settings")
            for entry in self.custom_proxy_strings:
                try:
                    entry = entry.strip()
                    if not entry:
                        continue
                    protocol = "http"
                    host = None
                    port = None

                    # If full URL provided
                    if "://" in entry:
                        parsed = urlparse(entry)
                        protocol = parsed.scheme or "http"
                        host = parsed.hostname
                        port = parsed.port
                    else:
                        # Expect host:port
                        if ":" in entry:
                            host_part, port_part = entry.split(":", 1)
                            host = host_part.strip()
                            port = int(port_part.strip())

                    if host and port:
                        all_proxies.append(ProxyInfo(host=host, port=port, protocol=protocol))
                except Exception as e:
                    self.logger.debug(f"Invalid custom proxy entry '{entry}': {e}")
        
        # Fetch from GeoNode API
        geonode_proxies = await self.fetch_proxies_from_geonode()
        all_proxies.extend(geonode_proxies)
        
        # Fetch from text sources
        for url in self.proxy_sources[1:]:
            text_proxies = await self.fetch_proxies_from_text_source(url)
            all_proxies.extend(text_proxies)
        
        # Remove duplicates
        unique_proxies = {}
        for proxy in all_proxies:
            key = f"{proxy.host}:{proxy.port}"
            if key not in unique_proxies:
                unique_proxies[key] = proxy
        
        self.logger.info(f"Found {len(unique_proxies)} unique proxies")
        
        # Test proxies in batches
        working_proxies = []
        batch_size = 20
        proxy_list = list(unique_proxies.values())
        
        for i in range(0, len(proxy_list), batch_size):
            batch = proxy_list[i:i + batch_size]
            tasks = [self.test_proxy(proxy) for proxy in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for proxy, result in zip(batch, results):
                if result is True:
                    working_proxies.append(proxy)
        
        # Sort by success rate and response time
        working_proxies.sort(key=lambda p: (p.success_rate, -p.response_time), reverse=True)
        
        self.proxies = working_proxies
        self.last_proxy_update = time.time()
        
        self.logger.info(f"Updated proxy list: {len(working_proxies)} working proxies")
    
    def get_next_proxy(self) -> Optional[ProxyInfo]:
        """Get the next proxy in rotation."""
        if not self.proxies:
            return None
        
        # Check if we need to update proxy list
        if time.time() - self.last_proxy_update > self.proxy_update_interval:
            # Prevent multiple concurrent updates
            if not hasattr(self, '_updating'):
                self._updating = True
                asyncio.create_task(self._safe_update_proxy_list())
        
        # Filter working proxies
        working_proxies = [p for p in self.proxies if p.is_working and p.success_rate > 0.5]
        
        if not working_proxies:
            # If no working proxies, try to use any proxy
            working_proxies = self.proxies
        
        if not working_proxies:
            return None
        
        # Use round-robin with preference for better proxies
        proxy = working_proxies[self.current_proxy_index % len(working_proxies)]
        self.current_proxy_index += 1
        
        proxy.last_used = time.time()
        return proxy
    
    def mark_proxy_failed(self, proxy: ProxyInfo) -> None:
        """Mark a proxy as failed."""
        proxy.failure_count += 1
        
        # Disable proxy if it fails too often
        failure_limit = getattr(self, "max_failures", 10) or 10
        if proxy.failure_count > failure_limit and proxy.success_rate < 0.3:
            proxy.is_working = False
            self.logger.debug(f"Disabled proxy {proxy.url} due to high failure rate")
    
    def mark_proxy_success(self, proxy: ProxyInfo) -> None:
        """Mark a proxy as successful."""
        proxy.success_count += 1
    
    async def initialize(self) -> None:
        """Initialize the proxy manager."""
        self.logger.info("Initializing proxy manager...")
        # Respect test_on_startup flag; if disabled we only
        # prepare custom proxies without live testing external lists.
        if getattr(self, "test_on_startup", True):
            await self.update_proxy_list()
        else:
            # Only use custom proxies if provided
            self.proxies = []
            if self.custom_proxy_strings:
                await self.update_proxy_list()
    
    async def _safe_update_proxy_list(self):
        """Safely update proxy list with lock."""
        try:
            await self.update_proxy_list()
        finally:
            if hasattr(self, '_updating'):
                delattr(self, '_updating')
    
    def get_proxy_stats(self) -> Dict:
        """Get proxy statistics."""
        working_count = len([p for p in self.proxies if p.is_working])
        total_count = len(self.proxies)
        
        if self.proxies:
            avg_response_time = sum(p.response_time for p in self.proxies) / total_count
            avg_success_rate = sum(p.success_rate for p in self.proxies) / total_count
        else:
            avg_response_time = 0
            avg_success_rate = 0
        
        return {
            'total_proxies': total_count,
            'working_proxies': working_count,
            'avg_response_time': avg_response_time,
            'avg_success_rate': avg_success_rate,
            'last_update': self.last_proxy_update
        }
