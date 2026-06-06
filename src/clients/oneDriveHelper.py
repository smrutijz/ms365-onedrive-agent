import requests
import logging
from typing import Optional, List, Dict, Any
from urllib.parse import quote

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class GraphClient:
    """Microsoft Graph API client covering the full native OneDrive feature set."""

    def __init__(self, access_token: str, timeout: int = 30):
        self.base_url = "https://graph.microsoft.com/v1.0"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        })
        self.timeout = timeout

    # ── Drive ──────────────────────────────────────────────────────────────────

    def get_drive_info(self) -> Dict[str, Any]:
        """Drive metadata including quota (total / used / remaining)."""
        try:
            resp = self.session.get(f"{self.base_url}/me/drive", timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to get drive info: {e}")
            return {}

    def get_drive_id(self) -> Optional[str]:
        """Return the user's OneDrive drive ID."""
        return self.get_drive_info().get("id")

    # ── Browse ─────────────────────────────────────────────────────────────────

    def list_root(self) -> List[Dict[str, Any]]:
        """List files and folders at the root of the user's OneDrive."""
        try:
            resp = self.session.get(
                f"{self.base_url}/me/drive/root/children", timeout=self.timeout
            )
            resp.raise_for_status()
            return resp.json().get("value", [])
        except requests.RequestException as e:
            logger.error(f"Failed to list root: {e}")
            return []

    def list_folder(self, folder_id: str) -> List[Dict[str, Any]]:
        """List contents of a folder by item ID."""
        try:
            resp = self.session.get(
                f"{self.base_url}/me/drive/items/{folder_id}/children",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("value", [])
        except requests.RequestException as e:
            logger.error(f"Failed to list folder '{folder_id}': {e}")
            return []

    def list_folder_by_path(self, path: str) -> List[Dict[str, Any]]:
        """List contents of a folder by path, e.g. '/Documents/Work'."""
        try:
            resp = self.session.get(
                f"{self.base_url}/me/drive/root:{quote(path, safe='/')}:/children",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("value", [])
        except requests.RequestException as e:
            logger.error(f"Failed to list folder by path '{path}': {e}")
            return []

    # ── Item metadata ──────────────────────────────────────────────────────────

    def get_item(self, item_id: str) -> Dict[str, Any]:
        """Get full metadata for an item by its ID."""
        try:
            resp = self.session.get(
                f"{self.base_url}/me/drive/items/{item_id}", timeout=self.timeout
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to get item '{item_id}': {e}")
            return {}

    def get_item_by_path(self, path: str) -> Dict[str, Any]:
        """Get full metadata for an item by path, e.g. '/Documents/file.pdf'."""
        try:
            resp = self.session.get(
                f"{self.base_url}/me/drive/root:{quote(path, safe='/')}", timeout=self.timeout
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to get item by path '{path}': {e}")
            return {}

    def get_folder_id_by_path(self, path: str) -> Optional[str]:
        """Resolve a folder path to its item ID."""
        return self.get_item_by_path(path).get("id")

    # ── Search ─────────────────────────────────────────────────────────────────

    def search(self, query: str) -> List[Dict[str, Any]]:
        """Search OneDrive for files/folders matching the query string."""
        try:
            safe_query = quote(query.replace("'", "''"), safe="")
            resp = self.session.get(
                f"{self.base_url}/me/drive/root/search(q='{safe_query}')",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("value", [])
        except requests.RequestException as e:
            logger.error(f"Search failed for query '{query}': {e}")
            return []

    # ── Recent & Shared ────────────────────────────────────────────────────────

    def get_recent(self) -> List[Dict[str, Any]]:
        """Files recently accessed by the signed-in user."""
        try:
            resp = self.session.get(
                f"{self.base_url}/me/drive/recent", timeout=self.timeout
            )
            resp.raise_for_status()
            return resp.json().get("value", [])
        except requests.RequestException as e:
            logger.error(f"Failed to get recent files: {e}")
            return []

    def get_shared_with_me(self) -> List[Dict[str, Any]]:
        """Items shared with the signed-in user."""
        try:
            resp = self.session.get(
                f"{self.base_url}/me/drive/sharedWithMe", timeout=self.timeout
            )
            resp.raise_for_status()
            return resp.json().get("value", [])
        except requests.RequestException as e:
            logger.error(f"Failed to get shared-with-me: {e}")
            return []

    # ── Download ───────────────────────────────────────────────────────────────

    def download_file(self, file_id: str) -> Optional[bytes]:
        """Download a file's raw bytes by its item ID."""
        try:
            resp = self.session.get(
                f"{self.base_url}/me/drive/items/{file_id}/content",
                timeout=self.timeout,
                allow_redirects=True,
            )
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as e:
            logger.error(f"Failed to download file '{file_id}': {e}")
            return None

    def get_download_url(self, file_id: str) -> Optional[str]:
        """Return a short-lived direct download URL for a file."""
        return self.get_item(file_id).get("@microsoft.graph.downloadUrl")

    # ── Upload ─────────────────────────────────────────────────────────────────

    def upload_file(self, path: str, content: bytes) -> Optional[Dict[str, Any]]:
        """
        Simple upload (≤4 MB). Overwrites if the file already exists.
        path format: '/Documents/report.pdf'
        """
        try:
            resp = self.session.put(
                f"{self.base_url}/me/drive/root:{quote(path, safe='/')}:/content",
                headers={"Content-Type": "application/octet-stream"},
                data=content,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to upload to '{path}': {e}")
            return None

    def upload_large_file(
        self, path: str, content: bytes, chunk_size: int = 10 * 1024 * 1024
    ) -> Optional[Dict[str, Any]]:
        """
        Resumable upload session for files larger than 4 MB.
        Sends data in chunks of `chunk_size` bytes (default 10 MB).
        path format: '/Documents/large_video.mp4'
        """
        try:
            session_resp = self.session.post(
                f"{self.base_url}/me/drive/root:{quote(path, safe='/')}:/createUploadSession",
                json={"item": {"@microsoft.graph.conflictBehavior": "replace"}},
                timeout=self.timeout,
            )
            session_resp.raise_for_status()
            upload_url = session_resp.json()["uploadUrl"]

            total = len(content)
            start = 0
            result: Dict[str, Any] = {}
            while start < total:
                end = min(start + chunk_size, total)
                chunk = content[start:end]
                chunk_resp = requests.put(
                    upload_url,
                    headers={
                        "Content-Range": f"bytes {start}-{end - 1}/{total}",
                        "Content-Length": str(len(chunk)),
                    },
                    data=chunk,
                    timeout=self.timeout,
                )
                chunk_resp.raise_for_status()
                if chunk_resp.content:
                    result = chunk_resp.json()
                start = end

            return result
        except requests.RequestException as e:
            logger.error(f"Large file upload failed for '{path}': {e}")
            return None

    # ── Create folder ──────────────────────────────────────────────────────────

    def create_folder(
        self, name: str, parent_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new folder. Uses 'rename' conflict behaviour.
        If parent_id is None, creates at the drive root.
        """
        url = (
            f"{self.base_url}/me/drive/items/{parent_id}/children"
            if parent_id
            else f"{self.base_url}/me/drive/root/children"
        )
        try:
            resp = self.session.post(
                url,
                json={
                    "name": name,
                    "folder": {},
                    "@microsoft.graph.conflictBehavior": "rename",
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to create folder '{name}': {e}")
            return None

    # ── Rename / Move / Copy / Delete ──────────────────────────────────────────

    def rename_item(self, item_id: str, new_name: str) -> Optional[Dict[str, Any]]:
        """Rename a file or folder."""
        try:
            resp = self.session.patch(
                f"{self.base_url}/me/drive/items/{item_id}",
                json={"name": new_name},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to rename item '{item_id}': {e}")
            return None

    def move_item(
        self, item_id: str, new_parent_id: str, new_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Move an item to a different folder, optionally renaming it."""
        body: Dict[str, Any] = {"parentReference": {"id": new_parent_id}}
        if new_name:
            body["name"] = new_name
        try:
            resp = self.session.patch(
                f"{self.base_url}/me/drive/items/{item_id}",
                json=body,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to move item '{item_id}': {e}")
            return None

    def copy_item(
        self, item_id: str, new_parent_id: str, new_name: Optional[str] = None
    ) -> Optional[str]:
        """
        Copy an item to a different folder.
        Returns the async monitor URL to poll for completion status.
        """
        body: Dict[str, Any] = {"parentReference": {"id": new_parent_id}}
        if new_name:
            body["name"] = new_name
        try:
            resp = self.session.post(
                f"{self.base_url}/me/drive/items/{item_id}/copy",
                json=body,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.headers.get("Location")
        except requests.RequestException as e:
            logger.error(f"Failed to copy item '{item_id}': {e}")
            return None

    def delete_item(self, item_id: str) -> bool:
        """Permanently delete a file or folder by its item ID."""
        try:
            resp = self.session.delete(
                f"{self.base_url}/me/drive/items/{item_id}", timeout=self.timeout
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to delete item '{item_id}': {e}")
            return False

    # ── Thumbnails ─────────────────────────────────────────────────────────────

    def get_thumbnails(self, item_id: str) -> List[Dict[str, Any]]:
        """Return available thumbnail sizes for an item."""
        try:
            resp = self.session.get(
                f"{self.base_url}/me/drive/items/{item_id}/thumbnails",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("value", [])
        except requests.RequestException as e:
            logger.error(f"Failed to get thumbnails for '{item_id}': {e}")
            return []

    # ── Sharing / Permissions ──────────────────────────────────────────────────

    def create_share_link(
        self,
        item_id: str,
        link_type: str = "view",
        scope: str = "anonymous",
    ) -> Optional[Dict[str, Any]]:
        """
        Create a sharing link for an item.
        link_type: 'view' | 'edit' | 'embed'
        scope:     'anonymous' | 'organization'
        """
        try:
            resp = self.session.post(
                f"{self.base_url}/me/drive/items/{item_id}/createLink",
                json={"type": link_type, "scope": scope},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to create share link for '{item_id}': {e}")
            return None

    def list_permissions(self, item_id: str) -> List[Dict[str, Any]]:
        """List all permissions (shares) on an item."""
        try:
            resp = self.session.get(
                f"{self.base_url}/me/drive/items/{item_id}/permissions",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("value", [])
        except requests.RequestException as e:
            logger.error(f"Failed to list permissions for '{item_id}': {e}")
            return []

    def remove_permission(self, item_id: str, permission_id: str) -> bool:
        """Remove a specific permission from an item."""
        try:
            resp = self.session.delete(
                f"{self.base_url}/me/drive/items/{item_id}/permissions/{permission_id}",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to remove permission '{permission_id}': {e}")
            return False

    # ── Version history ────────────────────────────────────────────────────────

    def list_versions(self, item_id: str) -> List[Dict[str, Any]]:
        """Return the version history of a file."""
        try:
            resp = self.session.get(
                f"{self.base_url}/me/drive/items/{item_id}/versions",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("value", [])
        except requests.RequestException as e:
            logger.error(f"Failed to list versions for '{item_id}': {e}")
            return []

    def restore_version(self, item_id: str, version_id: str) -> bool:
        """Restore a file to a specific historical version."""
        try:
            resp = self.session.post(
                f"{self.base_url}/me/drive/items/{item_id}/versions/{version_id}/restoreVersion",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to restore version '{version_id}': {e}")
            return False
