import re
import time
from threading import Lock

import requests
from src.utils.keyvault import KeyVaultClient
from src.core.config import settings


def email_to_key(email: str) -> str:
    """Convert an email to a valid Azure Key Vault secret name prefix."""
    return re.sub(r'[^a-zA-Z0-9]', '-', email.lower())


class TokenManager:
    # Treat a token as expired this many seconds before its actual expiry,
    # so it doesn't go stale mid-request to Microsoft Graph
    EXPIRY_BUFFER_SECONDS = 60

    def __init__(self):
        self.kv = KeyVaultClient()
        # Per-user locks so concurrent requests don't each trigger their own
        # refresh against Microsoft (wasted calls + refresh-token rotation races)
        self._locks: dict[str, Lock] = {}
        self._locks_guard = Lock()

    def _lock_for(self, key: str) -> Lock:
        with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = self._locks[key] = Lock()
            return lock

    def get_access_token(self, email: str) -> str:
        key = email_to_key(email)
        try:
            expiry = int(self.kv.get_secret(f"{key}-token-expiry"))
            access_token = self.kv.get_secret(f"{key}-access-token")
        except Exception:
            return self.refresh_access_token(email)

        # Refresh a little early so the token doesn't expire mid-request
        if expiry <= time.time() + self.EXPIRY_BUFFER_SECONDS:
            return self.refresh_access_token(email)
        return access_token

    def refresh_access_token(self, email: str) -> str:
        key = email_to_key(email)
        with self._lock_for(key):
            # Another request may have refreshed while we waited for the lock
            try:
                expiry = int(self.kv.get_secret(f"{key}-token-expiry"))
                access_token = self.kv.get_secret(f"{key}-access-token")
                if expiry > time.time() + self.EXPIRY_BUFFER_SECONDS:
                    return access_token
            except Exception:
                pass

            return self._do_refresh(key)

    def _do_refresh(self, key: str) -> str:
        try:
            refresh_token = self.kv.get_secret(f"{key}-refresh-token")
        except Exception:
            raise RuntimeError("No tokens found — please login at /login")

        if not refresh_token:
            raise RuntimeError("No tokens found — please login at /login")

        data = {
            "client_id": settings.GRAPH_APP_CLIENT_ID,
            "client_secret": settings.GRAPH_APP_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": settings.GRAPH_APP_SCOPES,
        }

        r = requests.post(settings.TOKEN_URL, data=data)
        r.raise_for_status()
        token = r.json()

        if "access_token" not in token:
            raise RuntimeError(token.get("error_description", "Token refresh failed — re-login required"))

        expires_at = str(int(time.time()) + token.get("expires_in", 3600))
        self.kv.set_secret(f"{key}-access-token", token["access_token"])
        self.kv.set_secret(f"{key}-token-expiry", expires_at)
        if "refresh_token" in token:
            self.kv.set_secret(f"{key}-refresh-token", token["refresh_token"])

        return token["access_token"]

    def revoke_tokens(self, email: str) -> None:
        """
        Invalidate all stored tokens for a user — e.g. on logout.

        Overwrites secret values rather than deleting them: Key Vault
        soft-delete would otherwise make the secret names unusable for the
        retention period, breaking the next /login for this user.
        """
        key = email_to_key(email)
        for suffix in ("access-token", "refresh-token", "token-expiry"):
            self.kv.set_secret(f"{key}-{suffix}", "")

    def store_tokens(self, email: str, token: dict) -> None:
        """Store OneDrive tokens for a user after initial OAuth login."""
        key = email_to_key(email)
        expires_at = str(int(time.time()) + token.get("expires_in", 3600))
        self.kv.set_secret(f"{key}-access-token", token["access_token"])
        self.kv.set_secret(f"{key}-token-expiry", expires_at)
        if "refresh_token" in token:
            self.kv.set_secret(f"{key}-refresh-token", token["refresh_token"])


# Singleton — one KeyVaultClient and credential reused across all requests
token_manager = TokenManager()
