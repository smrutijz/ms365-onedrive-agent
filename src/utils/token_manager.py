import re
import time
import requests
from src.utils.keyvault import KeyVaultClient
from src.core.config import settings


def email_to_key(email: str) -> str:
    """Convert an email to a valid Azure Key Vault secret name prefix."""
    return re.sub(r'[^a-zA-Z0-9]', '-', email.lower())


class TokenManager:
    def __init__(self):
        self.kv = KeyVaultClient()

    def get_access_token(self, email: str) -> str:
        key = email_to_key(email)
        try:
            expiry = self.kv.get_secret(f"{key}-token-expiry")
            access_token = self.kv.get_secret(f"{key}-access-token")
        except Exception:
            return self.refresh_access_token(email)

        if int(expiry) <= time.time():
            return self.refresh_access_token(email)
        return access_token

    def refresh_access_token(self, email: str) -> str:
        key = email_to_key(email)
        try:
            refresh_token = self.kv.get_secret(f"{key}-refresh-token")
        except Exception:
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

    def store_tokens(self, email: str, token: dict) -> None:
        """Store OneDrive tokens for a user after initial OAuth login."""
        key = email_to_key(email)
        expires_at = str(int(time.time()) + token.get("expires_in", 3600))
        self.kv.set_secret(f"{key}-access-token", token["access_token"])
        self.kv.set_secret(f"{key}-token-expiry", expires_at)
        if "refresh_token" in token:
            self.kv.set_secret(f"{key}-refresh-token", token["refresh_token"])

    def get_token_version(self, email: str) -> int:
        key = email_to_key(email)
        try:
            return int(self.kv.get_secret(f"{key}-token-version"))
        except Exception:
            return 0

    def increment_token_version(self, email: str) -> int:
        """Increment version — invalidates all previously issued JWTs for this user."""
        key = email_to_key(email)
        new_version = self.get_token_version(email) + 1
        self.kv.set_secret(f"{key}-token-version", str(new_version))
        return new_version


# Singleton — one KeyVaultClient and credential reused across all requests
token_manager = TokenManager()
