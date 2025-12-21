import requests
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class GraphClient:
    """
    Production-ready Microsoft Graph API client for OneDrive operations.
    """
    def __init__(self, access_token: str, timeout: int = 10):
        self.base_url = "https://graph.microsoft.com/v1.0"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        })
        self.timeout = timeout


    def list_root(self) -> List[Dict[str, Any]]:
        """List files and folders at the root of the user's OneDrive."""
        try:
            resp = self.session.get(f"{self.base_url}/me/drive/root/children", timeout=self.timeout)
            resp.raise_for_status()
            return resp.json().get("value", [])
        except requests.RequestException as e:
            logger.error(f"Failed to list root: {e}")
            return []


    def get_drive_id(self) -> Optional[str]:
        """Get the user's OneDrive drive ID."""
        try:
            resp = self.session.get(f"{self.base_url}/me/drive", timeout=self.timeout)
            resp.raise_for_status()
            return resp.json().get("id")
        except requests.RequestException as e:
            logger.error(f"Failed to get drive ID: {e}")
            return None


    def get_folder_id_by_path(self, path: str) -> Optional[str]:
        """Get the folder ID for a given path."""
        try:
            resp = self.session.get(f"{self.base_url}/me/drive/root:{path}", timeout=self.timeout)
            resp.raise_for_status()
            return resp.json().get("id")
        except requests.RequestException as e:
            logger.error(f"Failed to get folder ID for path '{path}': {e}")
            return None
    

    def list_folder(self, folder_id: str) -> List[Dict[str, Any]]:
        """List contents of a folder by folder ID."""
        try:
            resp = self.session.get(f"{self.base_url}/me/drive/items/{folder_id}/children", timeout=self.timeout)
            resp.raise_for_status()
            return resp.json().get("value", [])
        except requests.RequestException as e:
            logger.error(f"Failed to list folder '{folder_id}': {e}")
            return []


    def search(self, query: str) -> List[Dict[str, Any]]:
        """Search OneDrive for files/folders matching the query."""
        try:
            resp = self.session.get(f"{self.base_url}/me/drive/root/search(q='{query}')", timeout=self.timeout)
            resp.raise_for_status()
            return resp.json().get("value", [])
        except requests.RequestException as e:
            logger.error(f"Search failed for query '{query}': {e}")
            return []
    

    def download_file(self, file_id: str) -> Optional[bytes]:
        """Download a file by its ID."""
        try:
            resp = self.session.get(
                f"{self.base_url}/me/drive/items/{file_id}/content",
                timeout=self.timeout,
                allow_redirects=True
            )
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as e:
            logger.error(f"Failed to download file '{file_id}': {e}")
            return None


    def upload_file(self, path: str, content: bytes) -> Optional[Dict[str, Any]]:
        """Upload a file to a given path."""
        try:
            resp = self.session.put(
                f"{self.base_url}/me/drive/root:/{path}:/content",
                headers={"Authorization": self.session.headers["Authorization"]},
                data=content,
                timeout=self.timeout
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to upload file to '{path}': {e}")
            return None


    def delete_item(self, item_id: str) -> bool:
        """Delete an item (file/folder) by its ID."""
        try:
            resp = self.session.delete(
                f"{self.base_url}/me/drive/items/{item_id}",
                timeout=self.timeout
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to delete item '{item_id}': {e}")
            return False


    def get_item(self, item_id: str): #-> List[Dict[str, Any]]:
        """Get metadata for a OneDrive item by its ID."""
        try:
            resp = self.session.get(
                f"{self.base_url}/me/drive/items/{item_id}",
                timeout=self.timeout
            )
            resp.raise_for_status()
            return resp.json()
        # .get("value", [])
        except requests.RequestException as e:
            logger.error(f"Failed to get metadata for item '{item_id}': {e}")
            return []
