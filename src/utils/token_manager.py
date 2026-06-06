import time
import requests
from src.utils.keyvault import KeyVaultClient
from src.core.config import settings


class TokenManager:
    def __init__(self):
        self.kv = KeyVaultClient()

    def get_access_token(self) -> str:
        try:
            expiry = self.kv.get_secret("onedrive-token-expiry")
            access_token = self.kv.get_secret("onedrive-access-token")
        except Exception:
            return self.refresh_access_token()

        if int(expiry) <= time.time():
            return self.refresh_access_token()
        return access_token

    def refresh_access_token(self) -> str:
        refresh_token = self.kv.get_secret("onedrive-refresh-token")

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
        self.kv.set_secret("onedrive-access-token", token["access_token"])
        self.kv.set_secret("onedrive-token-expiry", expires_at)
        if "refresh_token" in token:
            self.kv.set_secret("onedrive-refresh-token", token["refresh_token"])

        return token["access_token"]


# Singleton — one KeyVaultClient and credential reused across all requests
token_manager = TokenManager()
