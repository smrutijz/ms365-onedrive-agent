import pytest
from src.utils.keyvault import KeyVaultClient

def test_keyvault_secret_set_get():
    kv = KeyVaultClient()
    kv.set_secret("pytest-test", "hello-world")
    value = kv.get_secret("pytest-test")
    assert value == "hello-world"
