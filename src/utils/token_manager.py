import requests
from src.utils.keyvault import KeyVaultClient
from src.core.config import settings

class TokenManager:
    def __init__(self):
        self.kv = KeyVaultClient()

    def get_access_token(self) -> str:
        try:
            return self.kv.get_secret("onedrive-access-token")
        except Exception:
            return self.refresh_access_token()

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

        self.kv.set_secret("onedrive-access-token", token["access_token"])
        if "refresh_token" in token:
            self.kv.set_secret("onedrive-refresh-token", token["refresh_token"])

        return token["access_token"]
