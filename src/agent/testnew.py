from src.clients.oneDriveHelper import GraphClient
import requests
from src.utils.token_manager import TokenManager
import os
import json

access_token = TokenManager().refresh_access_token()
access_token = TokenManager().get_access_token()


client = GraphClient(access_token)

y=client.list_root()

y=client.list_folder("9509D56FD07A9FEF!se92e6b785cf7422297b89bbfcf6fb47f")
with open("src/agent/y.json", "w") as f:
    json.dump(y, f, indent=4)


import requests
print(requests.get(
    "https://graph.microsoft.com/v1.0/me",
    headers={"Authorization": f"Bearer {access_token}"}
).status_code)


client.download_file("9509D56FD07A9FEF!s90f607c805a64a84bbb521909ffe77ca")


