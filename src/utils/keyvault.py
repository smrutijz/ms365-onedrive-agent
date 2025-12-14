from azure.identity import ClientSecretCredential
from azure.keyvault.secrets import SecretClient
from src.core.config import settings

class KeyVaultClient:
    def __init__(self):
        self.credential = ClientSecretCredential(
            client_id=settings.SP_APP_CLIENT_ID,
            client_secret=settings.SP_APP_CLIENT_SECRET,
            tenant_id=settings.SP_APP_TENANT_ID
        )
        self.client = SecretClient(vault_url=settings.KEY_VAULT_URL, credential=self.credential)

    def get_secret(self, name: str):
        return self.client.get_secret(name).value

    def set_secret(self, name: str, value: str):
        self.client.set_secret(name, value)
