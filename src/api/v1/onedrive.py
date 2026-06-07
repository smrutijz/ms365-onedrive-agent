from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from src.clients.oneDriveHelper import GraphClient
from src.api.deps import get_graph_client

router = APIRouter(prefix="/drive")


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


# ── Drive ──────────────────────────────────────────────────────────────────────

@router.get("", tags=["Drive"])
def drive_info(client: GraphClient = Depends(get_graph_client)):
    """Return drive metadata including storage quota."""
    return client.get_drive_info()


# ── Browse ─────────────────────────────────────────────────────────────────────

@router.get("/root", tags=["Browse"])
def root(client: GraphClient = Depends(get_graph_client)):
    """List files and folders at the OneDrive root."""
    return client.list_root()


@router.get("/folder/{folder_id}", tags=["Browse"])
def folder(folder_id: str, client: GraphClient = Depends(get_graph_client)):
    """List contents of a folder by item ID."""
    return client.list_folder(folder_id)


@router.get("/folder-by-path", tags=["Browse"])
def folder_by_path(path: str, client: GraphClient = Depends(get_graph_client)):
    """List contents of a folder by path, e.g. path=/Documents/Work."""
    return client.list_folder_by_path(path)


# ── Item metadata ──────────────────────────────────────────────────────────────

@router.get("/items/{item_id}", tags=["Items"])
def get_item(item_id: str, client: GraphClient = Depends(get_graph_client)):
    """Get full metadata for an item by its ID."""
    return client.get_item(item_id)


@router.get("/item-by-path", tags=["Items"])
def get_item_by_path(path: str, client: GraphClient = Depends(get_graph_client)):
    """Get full metadata for an item by path, e.g. path=/Documents/file.pdf."""
    return client.get_item_by_path(path)


# ── Search ─────────────────────────────────────────────────────────────────────

@router.get("/search", tags=["Search"])
def search(q: str, client: GraphClient = Depends(get_graph_client)):
    """Search OneDrive for files/folders matching the query string."""
    return client.search(q)


# ── Recent & Shared ────────────────────────────────────────────────────────────

@router.get("/recent", tags=["Discovery"])
def recent(client: GraphClient = Depends(get_graph_client)):
    """Return files recently accessed by the signed-in user."""
    return client.get_recent()


@router.get("/shared-with-me", tags=["Discovery"])
def shared_with_me(client: GraphClient = Depends(get_graph_client)):
    """Return items shared with the signed-in user."""
    return client.get_shared_with_me()


# ── Download ───────────────────────────────────────────────────────────────────

@router.get("/items/{item_id}/download", tags=["Download"])
def download(item_id: str, client: GraphClient = Depends(get_graph_client)):
    """Download a file's content by its item ID."""
    filename = client.get_item(item_id).get("name", item_id)
    data = client.download_file(item_id)
    if data is None:
        raise HTTPException(status_code=404, detail="File not found or download failed")
    return StreamingResponse(
        iter([data]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/items/{item_id}/download-url", tags=["Download"])
def download_url(item_id: str, client: GraphClient = Depends(get_graph_client)):
    """Return a short-lived direct download URL for a file."""
    url = client.get_download_url(item_id)
    if not url:
        raise HTTPException(status_code=404, detail="Download URL not available")
    return {"download_url": url}


# ── Upload ─────────────────────────────────────────────────────────────────────

@router.post("/upload", tags=["Upload"])
async def upload(
    path: str,
    file: UploadFile = File(...),
    client: GraphClient = Depends(get_graph_client),
):
    """Upload a file (≤4 MB). path format: /Documents/report.pdf"""
    if not path.startswith("/"):
        path = f"/{path}"
    content = await file.read()
    result = client.upload_file(path, content)
    if result is None:
        raise HTTPException(status_code=500, detail="Upload failed")
    return result


@router.post("/upload-large", tags=["Upload"])
async def upload_large(
    path: str,
    file: UploadFile = File(...),
    client: GraphClient = Depends(get_graph_client),
):
    """Resumable chunked upload for files larger than 4 MB."""
    if not path.startswith("/"):
        path = f"/{path}"
    content = await file.read()
    result = client.upload_large_file(path, content)
    if result is None:
        raise HTTPException(status_code=500, detail="Large file upload failed")
    return result


# ── Create folder ──────────────────────────────────────────────────────────────

@router.post("/folders", tags=["Folders"])
def create_folder(
    body: CreateFolderBody, client: GraphClient = Depends(get_graph_client)
):
    """Create a new folder. If parent_id is omitted, creates at drive root."""
    result = client.create_folder(body.name, body.parent_id)
    if result is None:
        raise HTTPException(status_code=500, detail="Folder creation failed")
    return result


# ── Rename / Move / Copy / Delete ──────────────────────────────────────────────

@router.patch("/items/{item_id}/rename", tags=["Items"])
def rename_item(
    item_id: str, body: RenameBody, client: GraphClient = Depends(get_graph_client)
):
    """Rename a file or folder."""
    result = client.rename_item(item_id, body.new_name)
    if result is None:
        raise HTTPException(status_code=500, detail="Rename failed")
    return result


@router.patch("/items/{item_id}/move", tags=["Items"])
def move_item(
    item_id: str, body: MoveBody, client: GraphClient = Depends(get_graph_client)
):
    """Move an item to a different folder, optionally renaming it."""
    result = client.move_item(item_id, body.new_parent_id, body.new_name)
    if result is None:
        raise HTTPException(status_code=500, detail="Move failed")
    return result


@router.post("/items/{item_id}/copy", tags=["Items"])
def copy_item(
    item_id: str, body: CopyBody, client: GraphClient = Depends(get_graph_client)
):
    """Copy an item. Returns async monitor URL for completion status."""
    monitor_url = client.copy_item(item_id, body.new_parent_id, body.new_name)
    if not monitor_url:
        raise HTTPException(status_code=500, detail="Copy failed")
    return {"monitor_url": monitor_url}


@router.delete("/items/{item_id}", tags=["Items"])
def delete_item(item_id: str, client: GraphClient = Depends(get_graph_client)):
    """Permanently delete a file or folder."""
    ok = client.delete_item(item_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Delete failed")
    return {"deleted": item_id}


# ── Thumbnails ─────────────────────────────────────────────────────────────────

@router.get("/items/{item_id}/thumbnails", tags=["Thumbnails"])
def thumbnails(item_id: str, client: GraphClient = Depends(get_graph_client)):
    """Return available thumbnail sizes for an item."""
    return client.get_thumbnails(item_id)


# ── Sharing / Permissions ──────────────────────────────────────────────────────

@router.post("/items/{item_id}/share", tags=["Sharing"])
def create_share_link(
    item_id: str, body: ShareLinkBody, client: GraphClient = Depends(get_graph_client)
):
    """Create a sharing link. link_type: view|edit|embed, scope: anonymous|organization"""
    result = client.create_share_link(item_id, body.link_type, body.scope)
    if result is None:
        raise HTTPException(status_code=500, detail="Share link creation failed")
    return result


@router.get("/items/{item_id}/permissions", tags=["Sharing"])
def list_permissions(item_id: str, client: GraphClient = Depends(get_graph_client)):
    """List all current permissions (shares) on an item."""
    return client.list_permissions(item_id)


@router.delete("/items/{item_id}/permissions/{permission_id}", tags=["Sharing"])
def remove_permission(
    item_id: str, permission_id: str, client: GraphClient = Depends(get_graph_client)
):
    """Revoke a specific permission from an item."""
    ok = client.remove_permission(item_id, permission_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Permission removal failed")
    return {"removed": permission_id}


# ── Version history ────────────────────────────────────────────────────────────

@router.get("/items/{item_id}/versions", tags=["Versions"])
def list_versions(item_id: str, client: GraphClient = Depends(get_graph_client)):
    """Return the version history of a file."""
    return client.list_versions(item_id)
