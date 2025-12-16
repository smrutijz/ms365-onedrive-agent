from src.clients.graph_api import GraphClient
import requests
from src.utils.token_manager import TokenManager
import os
import json

access_token = TokenManager().get_access_token()


client = GraphClient(access_token)
client.list_root()



import requests
print(requests.get(
    "https://graph.microsoft.com/v1.0/me",
    headers={"Authorization": f"Bearer {access_token}"}
).status_code)


