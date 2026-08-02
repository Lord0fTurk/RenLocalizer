# -*- coding: utf-8 -*-
import unittest
from types import SimpleNamespace
from src.core.proxy_manager import ProxyManager, ProxyInfo


class TestProxyManager(unittest.TestCase):

    # ------------------------------------------------------------------
    # 1. Instance creation
    # ------------------------------------------------------------------

    def test_create_proxy_manager(self) -> None:
        pm = ProxyManager()
        self.assertIsInstance(pm, ProxyManager)
        self.assertEqual(pm.get_proxy_count(), 0)
        self.assertFalse(pm.is_proxy_enabled())
        self.assertIsNone(pm.get_next_proxy())
        self.assertListEqual(pm.proxies, [])

    # ------------------------------------------------------------------
    # 2. configure_from_settings
    # ------------------------------------------------------------------

    def test_configure_from_settings_loads_all_fields(self) -> None:
        pm = ProxyManager()
        settings = SimpleNamespace(
            enabled=True,
            auto_rotate=False,
            test_on_startup=False,
            update_interval=1800,
            max_failures=5,
            proxy_url="http://user:pass@192.168.1.1:8080",
            manual_proxies=["10.0.0.1:3128", "10.0.0.2:8080"],
        )
        pm.configure_from_settings(settings)

        self.assertEqual(pm.auto_rotate, False)
        self.assertEqual(pm.test_on_startup, False)
        self.assertEqual(pm.proxy_update_interval, 1800)
        self.assertEqual(pm.max_failures, 5)
        self.assertEqual(pm.personal_proxy_url, "http://user:pass@192.168.1.1:8080")
        self.assertListEqual(pm.custom_proxy_strings, ["10.0.0.1:3128", "10.0.0.2:8080"])

    def test_configure_from_settings_with_none_does_nothing(self) -> None:
        pm = ProxyManager()
        defaults = pm.max_failures
        pm.configure_from_settings(None)
        self.assertEqual(pm.max_failures, defaults)
        self.assertEqual(pm.get_proxy_count(), 0)

    def test_configure_from_settings_parses_manual_proxies(self) -> None:
        pm = ProxyManager()
        settings = SimpleNamespace(
            enabled=True,
            auto_rotate=True,
            test_on_startup=False,
            update_interval=3600,
            max_failures=10,
            proxy_url="",
            manual_proxies=["192.168.0.1:8080", " 10.0.0.5:3128 ", ""],
        )
        pm.configure_from_settings(settings)
        # Stripped, empty string filtered
        self.assertListEqual(pm.custom_proxy_strings, ["192.168.0.1:8080", "10.0.0.5:3128"])

    # ------------------------------------------------------------------
    # 3. get_next_proxy — returns proxy URL
    # ------------------------------------------------------------------

    def test_get_next_proxy_with_manual_proxies(self) -> None:
        pm = ProxyManager()
        pm.auto_rotate = True
        pm.proxies = [
            ProxyInfo(host="10.0.0.1", port=8080, is_working=True),
            ProxyInfo(host="10.0.0.2", port=3128, is_working=True),
        ]
        proxy = pm.get_next_proxy()
        self.assertIsNotNone(proxy)
        self.assertEqual(proxy.host, "10.0.0.1")
        self.assertEqual(proxy.port, 8080)

    def test_get_next_proxy_returns_none_when_empty(self) -> None:
        pm = ProxyManager()
        self.assertIsNone(pm.get_next_proxy())

    def test_get_next_proxy_with_personal_proxy_preferred(self) -> None:
        pm = ProxyManager()
        pm.proxies = [
            ProxyInfo(host="manual.proxy", port=8080, is_working=True),
            ProxyInfo(host="personal.proxy", port=3128, is_working=True, is_personal=True),
        ]
        # Personal is listed first (sorting done in update_proxy_list)
        pm.proxies = sorted(pm.proxies, key=lambda p: (not p.is_personal))
        proxy = pm.get_next_proxy()
        self.assertIsNotNone(proxy)
        self.assertTrue(proxy.is_personal)
        self.assertEqual(proxy.host, "personal.proxy")

    # ------------------------------------------------------------------
    # 4. mark_success / mark_failure
    # ------------------------------------------------------------------

    def test_mark_proxy_success_increments_counter(self) -> None:
        pm = ProxyManager()
        proxy = ProxyInfo(host="10.0.0.1", port=8080)
        pm.proxies = [proxy]

        pm.mark_proxy_success(proxy)
        self.assertEqual(proxy.success_count, 1)
        self.assertTrue(proxy.is_working)

        pm.mark_proxy_success(proxy.url)
        self.assertEqual(proxy.success_count, 2)

    def test_mark_proxy_failed_increments_counter(self) -> None:
        pm = ProxyManager()
        proxy = ProxyInfo(host="10.0.0.1", port=8080)
        pm.proxies = [proxy]
        pm.max_failures = 10

        pm.mark_proxy_failed(proxy)
        self.assertEqual(proxy.failure_count, 1)

        # Should still be working (failure limit not reached)
        self.assertTrue(proxy.is_working)

    def test_mark_proxy_failed_disables_after_max_failures(self) -> None:
        pm = ProxyManager()
        pm.max_failures = 3
        proxy = ProxyInfo(host="10.0.0.1", port=8080, is_working=True)
        pm.proxies = [proxy]

        for _ in range(5):
            pm.mark_proxy_failed(proxy)

        self.assertEqual(proxy.failure_count, 5)
        self.assertFalse(proxy.is_working)

    def test_personal_proxy_never_disabled(self) -> None:
        pm = ProxyManager()
        pm.max_failures = 2
        proxy = ProxyInfo(host="personal.proxy", port=8080, is_personal=True, is_working=True)
        pm.proxies = [proxy]

        for _ in range(5):
            pm.mark_proxy_failed(proxy)

        self.assertEqual(proxy.failure_count, 5)
        self.assertTrue(proxy.is_working)  # Personal proxy still working

    def test_mark_proxy_failed_accepts_url_string(self) -> None:
        pm = ProxyManager()
        proxy = ProxyInfo(host="10.0.0.1", port=8080)
        pm.proxies = [proxy]
        pm.max_failures = 10

        pm.mark_proxy_failed("http://10.0.0.1:8080")
        self.assertEqual(proxy.failure_count, 1)

    # ------------------------------------------------------------------
    # 5. get_proxy_count
    # ------------------------------------------------------------------

    def test_get_proxy_count_returns_correct_count(self) -> None:
        pm = ProxyManager()
        self.assertEqual(pm.get_proxy_count(), 0)

        pm.proxies = [
            ProxyInfo(host="p1", port=8080),
            ProxyInfo(host="p2", port=3128),
            ProxyInfo(host="p3", port=8081),
        ]
        self.assertEqual(pm.get_proxy_count(), 3)

    # ------------------------------------------------------------------
    # 6. Proxy rotation (round-robin)
    # ------------------------------------------------------------------

    def test_proxy_rotation_round_robin(self) -> None:
        pm = ProxyManager()
        pm.auto_rotate = True
        pm.proxies = [
            ProxyInfo(host="p1", port=8080, is_working=True),
            ProxyInfo(host="p2", port=3128, is_working=True),
            ProxyInfo(host="p3", port=8081, is_working=True),
        ]

        hosts = []
        for _ in range(6):
            p = pm.get_next_proxy()
            self.assertIsNotNone(p)
            hosts.append(p.host)

        # Round-robin: p1, p2, p3, p1, p2, p3
        self.assertEqual(hosts, ["p1", "p2", "p3", "p1", "p2", "p3"])

    def test_no_rotation_when_auto_rotate_false(self) -> None:
        pm = ProxyManager()
        pm.auto_rotate = False
        pm.proxies = [
            ProxyInfo(host="p1", port=8080, is_working=True),
            ProxyInfo(host="p2", port=3128, is_working=True),
        ]

        hosts = []
        for _ in range(4):
            p = pm.get_next_proxy()
            self.assertIsNotNone(p)
            hosts.append(p.host)

        # Always first proxy
        self.assertEqual(hosts, ["p1", "p1", "p1", "p1"])

    # ------------------------------------------------------------------
    # 7. Banned (disabled) proxy skipping
    # ------------------------------------------------------------------

    def test_banned_proxy_skipped_in_rotation(self) -> None:
        pm = ProxyManager()
        pm.auto_rotate = True
        pm.proxies = [
            ProxyInfo(host="bad", port=8080, is_working=False, failure_count=20, success_count=0),
            ProxyInfo(host="good", port=3128, is_working=True),
        ]

        hosts = []
        for _ in range(3):
            p = pm.get_next_proxy()
            self.assertIsNotNone(p)
            hosts.append(p.host)

        # Bad proxy should be skipped, only good used
        self.assertEqual(hosts, ["good", "good", "good"])

    def test_banned_proxy_fallback_when_all_banned(self) -> None:
        pm = ProxyManager()
        pm.proxies = [
            ProxyInfo(host="bad1", port=8080, is_working=False, failure_count=20, success_count=0),
            ProxyInfo(host="bad2", port=3128, is_working=False, failure_count=20, success_count=0),
        ]

        # When all are banned, fallback returns any proxy
        p = pm.get_next_proxy()
        self.assertIsNotNone(p)  # Should still return something (fallback)

    # ------------------------------------------------------------------
    # 8. is_proxy_enabled
    # ------------------------------------------------------------------

    def test_is_proxy_enabled_returns_false_when_empty(self) -> None:
        pm = ProxyManager()
        self.assertFalse(pm.is_proxy_enabled())

    def test_is_proxy_enabled_returns_true_with_working_proxy(self) -> None:
        pm = ProxyManager()
        pm.proxies = [ProxyInfo(host="p1", port=8080, is_working=True)]
        self.assertTrue(pm.is_proxy_enabled())

    def test_is_proxy_enabled_returns_true_with_personal_proxy(self) -> None:
        pm = ProxyManager()
        pm.proxies = [ProxyInfo(host="p1", port=8080, is_personal=True, is_working=False)]
        self.assertTrue(pm.is_proxy_enabled())

    def test_is_proxy_enabled_returns_false_when_all_banned(self) -> None:
        pm = ProxyManager()
        pm.proxies = [
            ProxyInfo(host="bad1", port=8080, is_working=False, is_personal=False),
            ProxyInfo(host="bad2", port=3128, is_working=False, is_personal=False),
        ]
        # None personal, none working → no usable proxy
        self.assertFalse(pm.is_proxy_enabled())

    # ------------------------------------------------------------------
    # 9. Empty proxy list
    # ------------------------------------------------------------------

    def test_empty_proxy_list_get_next_returns_none(self) -> None:
        pm = ProxyManager()
        self.assertEqual(pm.get_proxy_count(), 0)
        self.assertIsNone(pm.get_next_proxy())

    def test_empty_proxy_list_stats_handles_gracefully(self) -> None:
        pm = ProxyManager()
        stats = pm.get_proxy_stats()
        self.assertEqual(stats["total_proxies"], 0)
        self.assertEqual(stats["working_proxies"], 0)
        self.assertEqual(stats["avg_response_time"], 0)
        self.assertEqual(stats["avg_success_rate"], 0)

    # ------------------------------------------------------------------
    # 10. ProxyInfo dataclass
    # ------------------------------------------------------------------

    def test_proxy_info_dataclass_defaults(self) -> None:
        pi = ProxyInfo(host="test.host", port=3128)
        self.assertEqual(pi.host, "test.host")
        self.assertEqual(pi.port, 3128)
        self.assertEqual(pi.protocol, "http")
        self.assertEqual(pi.country, "")
        self.assertEqual(pi.last_used, 0)
        self.assertEqual(pi.success_count, 0)
        self.assertEqual(pi.failure_count, 0)
        self.assertEqual(pi.response_time, 0)
        self.assertTrue(pi.is_working)
        self.assertFalse(pi.is_personal)
        self.assertEqual(pi.uptime, 0.0)

    def test_proxy_info_url_property(self) -> None:
        pi = ProxyInfo(host="proxy.example.com", port=8080, protocol="https")
        self.assertEqual(pi.url, "https://proxy.example.com:8080")

    def test_proxy_info_url_with_auth(self) -> None:
        pi = ProxyInfo(host="proxy.example.com", port=8080, _auth_url="http://user:pass@proxy.example.com:8080")
        self.assertEqual(pi.url, "http://user:pass@proxy.example.com:8080")

    def test_proxy_info_success_rate(self) -> None:
        pi = ProxyInfo(host="p", port=8080)
        # No attempts → rate 1.0
        self.assertEqual(pi.success_rate, 1.0)

        pi.success_count = 7
        pi.failure_count = 3
        self.assertEqual(pi.success_rate, 0.7)

        pi.success_count = 0
        pi.failure_count = 0
        self.assertEqual(pi.success_rate, 1.0)

    def test_parse_proxy_string_host_port(self) -> None:
        pm = ProxyManager()
        pi = pm._parse_proxy_string("192.168.1.1:8080")
        self.assertIsNotNone(pi)
        self.assertEqual(pi.host, "192.168.1.1")
        self.assertEqual(pi.port, 8080)
        self.assertEqual(pi.protocol, "http")

    def test_parse_proxy_string_full_url(self) -> None:
        pm = ProxyManager()
        pi = pm._parse_proxy_string("http://10.0.0.1:3128")
        self.assertIsNotNone(pi)
        self.assertEqual(pi.host, "10.0.0.1")
        self.assertEqual(pi.port, 3128)
        self.assertEqual(pi.protocol, "http")

    def test_parse_proxy_string_with_auth(self) -> None:
        pm = ProxyManager()
        pi = pm._parse_proxy_string("http://admin:secret@proxy.example.com:8080")
        self.assertIsNotNone(pi)
        self.assertEqual(pi.host, "proxy.example.com")
        self.assertEqual(pi.port, 8080)
        self.assertIn("admin:secret", pi._auth_url)

    def test_parse_proxy_string_socks_skipped(self) -> None:
        pm = ProxyManager()
        pi = pm._parse_proxy_string("socks5://10.0.0.1:1080")
        self.assertIsNone(pi)

    def test_parse_proxy_string_invalid_returns_none(self) -> None:
        pm = ProxyManager()
        self.assertIsNone(pm._parse_proxy_string(""))
        self.assertIsNone(pm._parse_proxy_string("not-a-proxy"))
        self.assertIsNone(pm._parse_proxy_string("abcd:99999"))  # port out of range


if __name__ == "__main__":
    unittest.main()
