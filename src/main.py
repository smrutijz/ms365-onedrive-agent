import time
import requests
from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional
from src.core.config import settings
from src.utils.keyvault import KeyVaultClient
from src.utils.token_manager import token_manager
from src.clients.oneDriveHelper import GraphClient

app = FastAPI(title="MS365 OneDrive API")


# ── Helpers ────────────────────────────────────────────────────────────────────

def graph() -> GraphClient:
    return GraphClient(token_manager.get_access_token())


# ── Request bodies ─────────────────────────────────────────────────────────────

class CreateFolderBody(BaseModel):
    name: str
    parent_id: Optional[str] = None

class RenameBody(BaseModel):
    new_name: str

class MoveBody(BaseModel):
    new_parent_id: str
    new_name: Optional[str] = None

class CopyBody(BaseModel):
    new_parent_id: str
    new_name: Optional[str] = None

class ShareLinkBody(BaseModel):
    link_type: str = "view"   # view | edit | embed
    scope: str = "anonymous"  # anonymous | organization


# ── Auth ───────────────────────────────────────────────────────────────────────

@app.get("/login", tags=["Auth"])
def login():
    """Redirect to Microsoft OAuth login page."""
    params = {
        "client_id": settings.GRAPH_APP_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.GRAPH_APP_REDIRECT_URI,
        "scope": settings.GRAPH_APP_SCOPES,
    }
    query = "&".join(f"{k}={requests.utils.quote(v)}" for k, v in params.items())
    return RedirectResponse(f"{settings.AUTH_URL}?{query}")


@app.get("/callback", tags=["Auth"])
def callback(request: Request):
    """OAuth callback — exchanges auth code for tokens and stores them in Key Vault."""
    code = request.query_params.get("code")
    if not code:
        return {"error": "missing code"}

    data = {
        "client_id": settings.GRAPH_APP_CLIENT_ID,
        "client_secret": settings.GRAPH_APP_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.GRAPH_APP_REDIRECT_URI,
        "scope": settings.GRAPH_APP_SCOPES,
    }

    token = requests.post(settings.TOKEN_URL, data=data).json()
    if "access_token" not in token:
        raise HTTPException(status_code=400, detail=token.get("error_description", "Token exchange failed"))
    kv = KeyVaultClient()
    expires_at = str(int(time.time()) + token.get("expires_in", 3600))
    kv.set_secret("onedrive-access-token", token["access_token"])
    kv.set_secret("onedrive-refresh-token", token["refresh_token"])
    kv.set_secret("onedrive-token-expiry", expires_at)
    return {"status": "tokens stored"}


# ── Drive ──────────────────────────────────────────────────────────────────────

@app.get("/drive", tags=["Drive"])
def drive_info():
    """Return drive metadata including storage quota."""
    return graph().get_drive_info()


# ── Browse ─────────────────────────────────────────────────────────────────────

@app.get("/drive/root", tags=["Browse"])
def root():
    """List files and folders at the OneDrive root."""
    return graph().list_root()


@app.get("/drive/folder/{folder_id}", tags=["Browse"])
def folder(folder_id: str):
    """List contents of a folder by item ID."""
    return graph().list_folder(folder_id)


@app.get("/drive/folder-by-path", tags=["Browse"])
def folder_by_path(path: str):
    """List contents of a folder by path, e.g. path=/Documents/Work."""
    return graph().list_folder_by_path(path)


# ── Item metadata ──────────────────────────────────────────────────────────────

@app.get("/drive/items/{item_id}", tags=["Items"])
def get_item(item_id: str):
    """Get full metadata for an item by its ID."""
    return graph().get_item(item_id)


@app.get("/drive/item-by-path", tags=["Items"])
def get_item_by_path(path: str):
    """Get full metadata for an item by path, e.g. path=/Documents/file.pdf."""
    return graph().get_item_by_path(path)


# ── Search ─────────────────────────────────────────────────────────────────────

@app.get("/drive/search", tags=["Search"])
def search(q: str):
    """Search OneDrive for files/folders matching the query string."""
    return graph().search(q)


# ── Recent & Shared ────────────────────────────────────────────────────────────

@app.get("/drive/recent", tags=["Discovery"])
def recent():
    """Return files recently accessed by the signed-in user."""
    return graph().get_recent()


@app.get("/drive/shared-with-me", tags=["Discovery"])
def shared_with_me():
    """Return items shared with the signed-in user."""
    return graph().get_shared_with_me()


# ── Download ───────────────────────────────────────────────────────────────────

@app.get("/drive/items/{item_id}/download", tags=["Download"])
def download(item_id: str):
    """Download a file's content by its item ID."""
    client = graph()
    filename = client.get_item(item_id).get("name", item_id)
    data = client.download_file(item_id)
    if data is None:
        raise HTTPException(status_code=404, detail="File not found or download failed")
    return StreamingResponse(
        iter([data]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/drive/items/{item_id}/download-url", tags=["Download"])
def download_url(item_id: str):
    """Return a short-lived direct download URL for a file."""
    url = graph().get_download_url(item_id)
    if not url:
        raise HTTPException(status_code=404, detail="Download URL not available")
    return {"download_url": url}


# ── Upload ─────────────────────────────────────────────────────────────────────

@app.post("/drive/upload", tags=["Upload"])
async def upload(path: str, file: UploadFile = File(...)):
    """
    Upload a file (≤4 MB) to the given OneDrive path.
    For files >4 MB use /drive/upload-large instead.
    path query param format: /Documents/report.pdf
    """
    if not path.startswith("/"):
        path = f"/{path}"
    content = await file.read()
    result = graph().upload_file(path, content)
    if result is None:
        raise HTTPException(status_code=500, detail="Upload failed")
    return result


@app.post("/drive/upload-large", tags=["Upload"])
async def upload_large(path: str, file: UploadFile = File(...)):
    """
    Resumable chunked upload for files larger than 4 MB.
    path query param format: /Documents/large_video.mp4
    """
    if not path.startswith("/"):
        path = f"/{path}"
    content = await file.read()
    result = graph().upload_large_file(path, content)
    if result is None:
        raise HTTPException(status_code=500, detail="Large file upload failed")
    return result


# ── Create folder ──────────────────────────────────────────────────────────────

@app.post("/drive/folders", tags=["Folders"])
def create_folder(body: CreateFolderBody):
    """
    Create a new folder.
    If parent_id is omitted, the folder is created at the drive root.
    """
    result = graph().create_folder(body.name, body.parent_id)
    if result is None:
        raise HTTPException(status_code=500, detail="Folder creation failed")
    return result


# ── Rename / Move / Copy / Delete ──────────────────────────────────────────────

@app.patch("/drive/items/{item_id}/rename", tags=["Items"])
def rename_item(item_id: str, body: RenameBody):
    """Rename a file or folder."""
    result = graph().rename_item(item_id, body.new_name)
    if result is None:
        raise HTTPException(status_code=500, detail="Rename failed")
    return result


@app.patch("/drive/items/{item_id}/move", tags=["Items"])
def move_item(item_id: str, body: MoveBody):
    """Move an item to a different folder, optionally renaming it."""
    result = graph().move_item(item_id, body.new_parent_id, body.new_name)
    if result is None:
        raise HTTPException(status_code=500, detail="Move failed")
    return result


@app.post("/drive/items/{item_id}/copy", tags=["Items"])
def copy_item(item_id: str, body: CopyBody):
    """
    Copy an item to a different folder.
    Returns an async monitor URL to poll for completion.
    """
    monitor_url = graph().copy_item(item_id, body.new_parent_id, body.new_name)
    if not monitor_url:
        raise HTTPException(status_code=500, detail="Copy failed")
    return {"monitor_url": monitor_url}


@app.delete("/drive/items/{item_id}", tags=["Items"])
def delete_item(item_id: str):
    """Permanently delete a file or folder."""
    ok = graph().delete_item(item_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Delete failed")
    return {"deleted": item_id}


# ── Thumbnails ─────────────────────────────────────────────────────────────────

@app.get("/drive/items/{item_id}/thumbnails", tags=["Thumbnails"])
def thumbnails(item_id: str):
    """Return available thumbnail sizes for an item."""
    return graph().get_thumbnails(item_id)


# ── Sharing / Permissions ──────────────────────────────────────────────────────

@app.post("/drive/items/{item_id}/share", tags=["Sharing"])
def create_share_link(item_id: str, body: ShareLinkBody):
    """
    Create a sharing link for an item.
    link_type: 'view' | 'edit' | 'embed'
    scope: 'anonymous' | 'organization'
    """
    result = graph().create_share_link(item_id, body.link_type, body.scope)
    if result is None:
        raise HTTPException(status_code=500, detail="Share link creation failed")
    return result


@app.get("/drive/items/{item_id}/permissions", tags=["Sharing"])
def list_permissions(item_id: str):
    """List all current permissions (shares) on an item."""
    return graph().list_permissions(item_id)


@app.delete("/drive/items/{item_id}/permissions/{permission_id}", tags=["Sharing"])
def remove_permission(item_id: str, permission_id: str):
    """Revoke a specific permission from an item."""
    ok = graph().remove_permission(item_id, permission_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Permission removal failed")
    return {"removed": permission_id}


# ── Version history ────────────────────────────────────────────────────────────

@app.get("/drive/items/{item_id}/versions", tags=["Versions"])
def list_versions(item_id: str):
    """Return the version history of a file."""
    return graph().list_versions(item_id)


@app.post("/drive/items/{item_id}/versions/{version_id}/restore", tags=["Versions"])
def restore_version(item_id: str, version_id: str):
    """Restore a file to a specific historical version."""
    ok = graph().restore_version(item_id, version_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Version restore failed")
    return {"restored": version_id}
