import requests
from src.utils.token_manager import TokenManager
import os
import json

access_token = TokenManager().get_access_token()
# access_token = TokenManager().refresh_access_token()

base_url = "https://graph.microsoft.com/v1.0"
headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json"
}


query="smruti resume in pdf"
x = requests.get(
            f"{base_url}/me/drive/root/search(q='{query}')",
            headers=headers
        ).json()

print([item.get("name", '') for item in x.get("value", [])])
# print([item.get("id", '') for item in x.get("value", [])])


with open("testgraph.json", "w") as f:
    json.dump(x, f, indent=4)


