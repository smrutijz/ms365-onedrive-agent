import os
from dotenv import load_dotenv, find_dotenv
from threading import Lock

class _Config:
    """
    Singleton class for configuration loaded from environment variables.
    """
    _instance = None
    _lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._load()
        return cls._instance

    def _load(self):
        # Load environment variables from .env if exists
        load_dotenv(find_dotenv())

        # Key Vault / Service Principal
        self.SP_APP_CLIENT_ID = os.getenv("SP_APP_CLIENT_ID")
        self.SP_APP_CLIENT_SECRET = os.getenv("SP_APP_CLIENT_SECRET")
        self.SP_APP_TENANT_ID = os.getenv("SP_APP_TENANT_ID")
        self.KEY_VAULT_URL = os.getenv("KEY_VAULT_URL")

        # Microsoft Graph / OneDrive
        self.GRAPH_APP_CLIENT_ID = os.getenv("GRAPH_APP_CLIENT_ID")
        self.GRAPH_APP_CLIENT_SECRET = os.getenv("GRAPH_APP_CLIENT_SECRET")
        self.GRAPH_APP_TENANT = os.getenv("GRAPH_APP_TENANT", "consumers")
        self.GRAPH_APP_AUTHORITY_URL = os.getenv("GRAPH_APP_AUTHORITY_URL", "https://login.microsoftonline.com")
        self.GRAPH_APP_SCOPES = os.getenv("GRAPH_APP_SCOPES", "Files.ReadWrite offline_access")
        self.GRAPH_APP_REDIRECT_URI = os.getenv("GRAPH_APP_REDIRECT_URI", "http://localhost:8000/callback")

    # Derived OAuth URLs
    @property
    def AUTH_URL(self) -> str:
        return (
            f"{self.GRAPH_APP_AUTHORITY_URL}/"
            f"{self.GRAPH_APP_TENANT}/oauth2/v2.0/authorize"
        )

    @property
    def TOKEN_URL(self) -> str:
        return (
            f"{self.GRAPH_APP_AUTHORITY_URL}/"
            f"{self.GRAPH_APP_TENANT}/oauth2/v2.0/token"
        )

# Singleton instance
settings = _Config()
