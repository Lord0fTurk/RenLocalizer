"""Secrets (API keys, proxy passwords) in the operating system's credential store.

config.json is plain text and users share it when asking for help, so keys do
not belong there. This module wraps ``keyring`` and is deliberately boring:

* Windows -> Credential Manager, Linux -> Secret Service (GNOME Keyring,
  KWallet's Secret Service bridge). The backend is chosen explicitly instead of
  through keyring's entry-point discovery, which a PyInstaller build cannot see.
* macOS is not used: the release is ad-hoc signed, so its code signature changes
  with every version and Keychain would ask for permission again per key after
  each update. Until the app is notarized, macOS keeps the keys in config.json.
* Whenever the store is missing or fails, callers keep the value in config.json
  exactly as before. A key is never dropped because the store misbehaved.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Optional

logger = logging.getLogger(__name__)

SERVICE = "RenLocalizer"
DISABLE_ENV = "RENLOCALIZER_NO_KEYRING"
# Windows Credential Manager caps a credential blob at 2560 bytes (UTF-16).
MAX_SECRET_CHARS = 1000


class SecretStore:
    """Thin, failure-tolerant wrapper around one keyring backend."""

    def __init__(self, enabled: bool = True, backend=None) -> None:
        self._lock = threading.Lock()
        self._backend = backend
        self.reason = ""
        if backend is not None:
            return
        if not enabled:
            self.reason = "disabled (portable mode)"
        elif os.environ.get(DISABLE_ENV) == "1":
            self.reason = f"disabled by {DISABLE_ENV}"
        elif sys.platform == "darwin":
            self.reason = "not used on macOS (unsigned build)"
        else:
            self._backend, self.reason = self._open_backend()

    @staticmethod
    def _open_backend():
        try:
            if sys.platform == "win32":
                from keyring.backends.Windows import WinVaultKeyring as Backend
            else:
                from keyring.backends.SecretService import Keyring as Backend
            backend = Backend()
            # `priority` raises when the backend cannot work here (no pywin32-ctypes,
            # no SecretStorage, no D-Bus session).
            if backend.priority <= 0:
                return None, "credential store not usable"
            # One real round trip: a headless Linux session has the library but
            # no service to talk to.
            backend.get_password(SERVICE, "__probe__")
            return backend, ""
        except Exception as exc:  # ImportError, RuntimeError, D-Bus errors...
            return None, f"credential store unavailable ({exc.__class__.__name__})"

    @property
    def available(self) -> bool:
        return self._backend is not None

    def get(self, name: str) -> Optional[str]:
        """The stored value, or None when absent or the store failed."""
        if self._backend is None:
            return None
        try:
            with self._lock:
                return self._backend.get_password(SERVICE, name)
        except Exception as exc:
            logger.warning("Could not read '%s' from the credential store: %s", name, exc.__class__.__name__)
            return None

    def set(self, name: str, value: str) -> bool:
        """Store ``value``; False means the caller must keep it elsewhere."""
        if self._backend is None or not value or len(value) > MAX_SECRET_CHARS:
            return False
        try:
            with self._lock:
                self._backend.set_password(SERVICE, name, value)
                # Read back: a store that accepts and forgets would lose the key.
                return self._backend.get_password(SERVICE, name) == value
        except Exception as exc:
            logger.warning("Could not write '%s' to the credential store: %s", name, exc.__class__.__name__)
            return False

    def delete(self, name: str) -> None:
        if self._backend is None:
            return
        try:
            with self._lock:
                if self._backend.get_password(SERVICE, name) is not None:
                    self._backend.delete_password(SERVICE, name)
        except Exception as exc:
            logger.debug("Could not delete '%s' from the credential store: %s", name, exc.__class__.__name__)
