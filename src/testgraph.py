import requests
from src.utils.token_manager import TokenManager
import os
import json

# access_token = TokenManager().get_access_token()
access_token = TokenManager().refresh_access_token()

base_url = "https://graph.microsoft.com/v1.0"
headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json"
}

# Root files

x = requests.get(
    f"{base_url}/me/drive/root/children",
    headers=headers
).json()
with open("x.json", "w", encoding="utf-8") as f:
    json.dump(x, f, ensure_ascii=False, indent=2)

query="test"
x = requests.get(
            f"{base_url}/me/drive/root/search(q='{query}')",
            headers=headers
        ).json()

print([item.get("name", '') for item in x.get("value", [])])
# print([item.get("id", '') for item in x.get("value", [])])


with open("test.json", "w") as f:
    json.dump(x, f, indent=4)







r=requests.get(f"{base_url}/me/drive", headers=headers)
r.raise_for_status()
r.json()["id"]

path = "/Documents"
r = requests.get(
    f"{base_url}/me/drive/root:{path}",
    headers=headers
)
r.raise_for_status()
print(r.json()["id"])


folder_id: str="9509D56FD07A9FEF!se92e6b785cf7422297b89bbfcf6fb47f"
for item in x.get("value", []):
    folder_id = item.get("id", '')
    x = requests.get(
            f"{base_url}/me/drive/items/{folder_id}/children",
            headers=headers
        ).json()
    print(item.get("name", ''), len(x.get("value", [])))

# 🔍 SEARCH (your main ask)
def search(query: str):
    return requests.get(
        f"{base_url}/me/drive/root/search(q='{query}')",
        headers=headers
    ).json()

# Upload file
def upload_file(path: str, content: bytes):
    return requests.put(
        f"{base_url}/me/drive/root:/{path}:/content",
        headers={"Authorization": headers["Authorization"]},
        data=content
    ).json()

# Delete item
def delete_item(item_id: str):
    r = requests.delete(
        f"{base_url}/me/drive/items/{item_id}",
        headers=headers
    )
    r.raise_for_status()
