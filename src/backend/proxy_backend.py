# -*- coding: utf-8 -*-
"""Proxy settings and the connection test (Settings > Performance & Network).

Part of the QML bridge; split out of AppBackend. QML reaches it as
``appBackend.proxy``. It shares the app backend's config, settings and logger
through properties, so a replaced config is picked up here too.
"""

import asyncio
import threading

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, pyqtProperty



class ProxyBackend(QObject):
    _proxyTestDone = pyqtSignal(object)
    proxySettingsChanged = pyqtSignal()
    proxyTestStateChanged = pyqtSignal()

    def __init__(self, app) -> None:
        super().__init__(app)
        self.app = app
        self._proxy_testing = False
        self._proxy_test_result = ""
        self._proxy_test_ok = False
        self._proxyTestDone.connect(self._on_proxy_test_done)

    # Shared state lives on the app backend.
    @property
    def config(self):
        return self.app.config

    @property
    def settings(self):
        return self.app.settings

    @property
    def logger(self):
        return self.app.logger

    @property
    def proxy_manager(self):
        return self.app.proxy_manager

    def _t(self, key: str, default: str) -> str:
        return self.app._t(key, default)

    def reload(self) -> None:
        """Re-read config.proxy_settings (after a factory reset or config reload)."""
        self.proxy_manager.configure_from_settings(self.config.proxy_settings)
        self.proxySettingsChanged.emit()

    # ── Proxy (Settings > Performance & Network) ──────────────────────────

    def _apply_proxy_settings(self) -> None:
        """Push config.proxy_settings to the live ProxyManager and save it."""
        self.proxy_manager.configure_from_settings(self.config.proxy_settings)
        try:
            self.config.save_config()
        except Exception as exc:
            self.logger.warning("[AppBackend] proxy settings could not be saved: %s", exc)
        if self._proxy_test_result:
            self._proxy_test_result = ""  # the old result no longer describes the settings
            self.proxyTestStateChanged.emit()
        self.proxySettingsChanged.emit()

    @pyqtProperty(bool, notify=proxySettingsChanged)
    def proxyEnabled(self) -> bool:
        return bool(self.config.proxy_settings.enabled)

    @proxyEnabled.setter
    def proxyEnabled(self, val: bool) -> None:
        if bool(val) != bool(self.config.proxy_settings.enabled):
            self.config.proxy_settings.enabled = bool(val)
            self._apply_proxy_settings()

    @pyqtProperty(str, notify=proxySettingsChanged)
    def proxyUrl(self) -> str:
        return self.config.proxy_settings.proxy_url or ""

    @proxyUrl.setter
    def proxyUrl(self, val: str) -> None:
        val = (val or "").strip()
        if val != (self.config.proxy_settings.proxy_url or ""):
            self.config.proxy_settings.proxy_url = val
            self._apply_proxy_settings()

    @pyqtProperty(str, notify=proxySettingsChanged)
    def proxyList(self) -> str:
        """The manual proxy list, one address per line."""
        return chr(10).join(self.config.proxy_settings.manual_proxies or [])

    @proxyList.setter
    def proxyList(self, val: str) -> None:
        entries = [line.strip() for line in (val or "").splitlines() if line.strip()]
        if entries != list(self.config.proxy_settings.manual_proxies or []):
            self.config.proxy_settings.manual_proxies = entries
            self._apply_proxy_settings()

    @pyqtProperty(bool, notify=proxySettingsChanged)
    def proxyAutoRotate(self) -> bool:
        return bool(self.config.proxy_settings.auto_rotate)

    @proxyAutoRotate.setter
    def proxyAutoRotate(self, val: bool) -> None:
        if bool(val) != bool(self.config.proxy_settings.auto_rotate):
            self.config.proxy_settings.auto_rotate = bool(val)
            self._apply_proxy_settings()

    @pyqtProperty(int, notify=proxySettingsChanged)
    def proxyIgnoredCount(self) -> int:
        """Entries that cannot be used (SOCKS or malformed)."""
        return len(self.proxy_manager.rejected_entries)

    @pyqtProperty(bool, notify=proxyTestStateChanged)
    def proxyTesting(self) -> bool:
        return self._proxy_testing

    @pyqtProperty(str, notify=proxyTestStateChanged)
    def proxyTestResult(self) -> str:
        return self._proxy_test_result

    @pyqtProperty(bool, notify=proxyTestStateChanged)
    def proxyTestOk(self) -> bool:
        return self._proxy_test_ok

    @pyqtSlot()
    def testProxies(self) -> None:
        """Test the configured proxies in a worker thread (HTTPS through each one)."""
        if self._proxy_testing:
            return
        self._proxy_testing = True
        self._proxy_test_result = ""
        self.proxyTestStateChanged.emit()

        def work() -> None:
            results = []
            try:
                loop = asyncio.new_event_loop()
                try:
                    results = loop.run_until_complete(self.proxy_manager.test_configured())
                finally:
                    loop.close()
            except Exception as exc:
                self.logger.warning("[AppBackend] proxy test failed: %s", exc)
            self._proxyTestDone.emit(results)

        threading.Thread(target=work, daemon=True, name="proxy-test").start()

    def _on_proxy_test_done(self, results) -> None:
        results = list(results or [])
        working = [r for r in results if r.get("ok")]
        self._proxy_testing = False
        self._proxy_test_ok = bool(working)
        if not results:
            self._proxy_test_result = self._t("proxy_none_configured", "No usable proxy address entered.")
        elif working:
            self._proxy_test_result = self._t(
                "proxy_test_ok", "Working: {working} of {total} (fastest {ms} ms)"
            ).format(working=len(working), total=len(results), ms=min(r.get("ms", 0) for r in working))
        else:
            self._proxy_test_result = self._t(
                "proxy_test_fail", "No proxy answered ({total} tested). Check the address, port and password."
            ).format(total=len(results))
        self.proxyTestStateChanged.emit()
