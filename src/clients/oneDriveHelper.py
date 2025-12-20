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
        r = requests.get(
            f"{self.base_url}/me/drive/root/children",
            headers=self.headers
        )
        r.raise_for_status()
        return r.json().get("value", [])

    # Drive ID
    def get_drive_id(self):
        r = requests.get(f"{self.base_url}/me/drive", headers=self.headers)
        r.raise_for_status()
        return r.json().get("id", None)

    # Folder ID by path
    def get_folder_id_by_path(self, path: str):
        r = requests.get(
            f"{self.base_url}/me/drive/root:{path}",
            headers=self.headers
        )
        r.raise_for_status()
        return r.json().get("id", None)
    
    # Folder contents
    def list_folder(self, folder_id: str):
        r = requests.get(
            f"{self.base_url}/me/drive/items/{folder_id}/children",
            headers=self.headers
        )
        r.raise_for_status()
        return r.json().get("value", [])

    # SEARCH (OneDrive’s legacy consumer search)
    def search(self, query: str):
        r = requests.get(
            f"{self.base_url}/me/drive/root/search(q='{query}')",
            headers=self.headers
        )
        r.raise_for_status()
        return r.json().get("value", [])
    
    # Download file
    def download_file(self, file_id: str) -> bytes:
        r = requests.get(
            f"{self.base_url}/me/drive/items/{file_id}/content",
            headers=self.headers,
            allow_redirects=True
            )
        r.raise_for_status()
        return r.content

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
