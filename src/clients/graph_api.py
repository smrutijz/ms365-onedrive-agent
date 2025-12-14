import requests

class GraphClient:
    def __init__(self, access_token: str):
        self.base_url = "https://graph.microsoft.com/v1.0"
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

    # Root files
    def list_root(self):
        return requests.get(
            f"{self.base_url}/me/drive/root/children",
            headers=self.headers
        ).json()

    # Folder contents
    def list_folder(self, folder_id: str):
        return requests.get(
            f"{self.base_url}/me/drive/items/{folder_id}/children",
            headers=self.headers
        ).json()

    # 🔍 SEARCH (your main ask)
    def search(self, query: str):
        return requests.get(
            f"{self.base_url}/me/drive/root/search(q='{query}')",
            headers=self.headers
        ).json()

    # Upload file
    def upload_file(self, path: str, content: bytes):
        return requests.put(
            f"{self.base_url}/me/drive/root:/{path}:/content",
            headers={"Authorization": self.headers["Authorization"]},
            data=content
        ).json()

    # Delete item
    def delete_item(self, item_id: str):
        r = requests.delete(
            f"{self.base_url}/me/drive/items/{item_id}",
            headers=self.headers
        )
        r.raise_for_status()
