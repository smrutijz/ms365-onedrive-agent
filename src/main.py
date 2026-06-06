import datetime
import requests
import jwt
from fastapi import FastAPI, Request, UploadFile, File, HTTPException, Depends
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
from src.core.config import settings
from src.utils.token_manager import token_manager
from src.clients.oneDriveHelper import GraphClient

app = FastAPI(title="MS365 OneDrive API")
security = HTTPBearer()

JWT_EXPIRY_DAYS = 7


# ── Auth helpers ───────────────────────────────────────────────────────────────

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """Validate Bearer JWT and return the user's email."""
    try:
        payload = jwt.decode(
            credentials.credentials, settings.JWT_SECRET, algorithms=["HS256"]
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired — login again at /login")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    email = payload.get("email")
    version = payload.get("v")

    if not email:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    # Version check — if user logged in again this token is dead
    if version != token_manager.get_token_version(email):
        raise HTTPException(status_code=401, detail="Token revoked — login again at /login")

    return email


def get_graph_client(email: str = Depends(get_current_user)) -> GraphClient:
    try:
        return GraphClient(token_manager.get_access_token(email))
    except RuntimeError as e:
        raise HTTPException(status_code=401, detail=str(e))


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
    """
    OAuth callback. After Microsoft login this endpoint:
    1. Exchanges the auth code for OneDrive tokens
    2. Fetches the user's email from /me
    3. Stores tokens in Key Vault under that email
    4. Returns a signed JWT Bearer token

    Use the returned access_token as: Authorization: Bearer <token>
    on all /drive/* endpoints. Login again at /login to get a new token.
    """
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
        raise HTTPException(
            status_code=400,
            detail=token.get("error_description", "Token exchange failed"),
        )

    # Pull user's email from Microsoft
    me_resp = requests.get(
        "https://graph.microsoft.com/v1.0/me",
        headers={"Authorization": f"Bearer {token['access_token']}"},
    )
    me = me_resp.json()
    email = me.get("mail") or me.get("userPrincipalName")
    if not email:
        raise HTTPException(
            status_code=400,
            detail=f"Could not retrieve email from Microsoft: {me}",
        )

    # Store OneDrive tokens per user in Key Vault
    token_manager.store_tokens(email, token)

    # Increment version — all old JWTs for this user are now invalid
    version = token_manager.increment_token_version(email)

    # Issue signed JWT
    bearer = jwt.encode(
        {
            "email": email,
            "v": version,
            "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=JWT_EXPIRY_DAYS),
        },
        settings.JWT_SECRET,
        algorithm="HS256",
    )

    return {
        "access_token": bearer,
        "token_type": "bearer",
        "expires_in_days": JWT_EXPIRY_DAYS,
        "user": email,
    }


# ── Drive ──────────────────────────────────────────────────────────────────────

@app.get("/drive", tags=["Drive"])
def drive_info(client: GraphClient = Depends(get_graph_client)):
    """Return drive metadata including storage quota."""
    return client.get_drive_info()


# ── Browse ─────────────────────────────────────────────────────────────────────

@app.get("/drive/root", tags=["Browse"])
def root(client: GraphClient = Depends(get_graph_client)):
    """List files and folders at the OneDrive root."""
    return client.list_root()


@app.get("/drive/folder/{folder_id}", tags=["Browse"])
def folder(folder_id: str, client: GraphClient = Depends(get_graph_client)):
    """List contents of a folder by item ID."""
    return client.list_folder(folder_id)


@app.get("/drive/folder-by-path", tags=["Browse"])
def folder_by_path(path: str, client: GraphClient = Depends(get_graph_client)):
    """List contents of a folder by path, e.g. path=/Documents/Work."""
    return client.list_folder_by_path(path)


# ── Item metadata ──────────────────────────────────────────────────────────────

@app.get("/drive/items/{item_id}", tags=["Items"])
def get_item(item_id: str, client: GraphClient = Depends(get_graph_client)):
    """Get full metadata for an item by its ID."""
    return client.get_item(item_id)


@app.get("/drive/item-by-path", tags=["Items"])
def get_item_by_path(path: str, client: GraphClient = Depends(get_graph_client)):
    """Get full metadata for an item by path, e.g. path=/Documents/file.pdf."""
    return client.get_item_by_path(path)


# ── Search ─────────────────────────────────────────────────────────────────────

@app.get("/drive/search", tags=["Search"])
def search(q: str, client: GraphClient = Depends(get_graph_client)):
    """Search OneDrive for files/folders matching the query string."""
    return client.search(q)


# ── Recent & Shared ────────────────────────────────────────────────────────────

@app.get("/drive/recent", tags=["Discovery"])
def recent(client: GraphClient = Depends(get_graph_client)):
    """Return files recently accessed by the signed-in user."""
    return client.get_recent()


@app.get("/drive/shared-with-me", tags=["Discovery"])
def shared_with_me(client: GraphClient = Depends(get_graph_client)):
    """Return items shared with the signed-in user."""
    return client.get_shared_with_me()


# ── Download ───────────────────────────────────────────────────────────────────

@app.get("/drive/items/{item_id}/download", tags=["Download"])
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


@app.get("/drive/items/{item_id}/download-url", tags=["Download"])
def download_url(item_id: str, client: GraphClient = Depends(get_graph_client)):
    """Return a short-lived direct download URL for a file."""
    url = client.get_download_url(item_id)
    if not url:
        raise HTTPException(status_code=404, detail="Download URL not available")
    return {"download_url": url}


# ── Upload ─────────────────────────────────────────────────────────────────────

@app.post("/drive/upload", tags=["Upload"])
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


@app.post("/drive/upload-large", tags=["Upload"])
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

@app.post("/drive/folders", tags=["Folders"])
def create_folder(
    body: CreateFolderBody, client: GraphClient = Depends(get_graph_client)
):
    """Create a new folder. If parent_id is omitted, creates at drive root."""
    result = client.create_folder(body.name, body.parent_id)
    if result is None:
        raise HTTPException(status_code=500, detail="Folder creation failed")
    return result


# ── Rename / Move / Copy / Delete ──────────────────────────────────────────────

@app.patch("/drive/items/{item_id}/rename", tags=["Items"])
def rename_item(
    item_id: str, body: RenameBody, client: GraphClient = Depends(get_graph_client)
):
    """Rename a file or folder."""
    result = client.rename_item(item_id, body.new_name)
    if result is None:
        raise HTTPException(status_code=500, detail="Rename failed")
    return result


@app.patch("/drive/items/{item_id}/move", tags=["Items"])
def move_item(
    item_id: str, body: MoveBody, client: GraphClient = Depends(get_graph_client)
):
    """Move an item to a different folder, optionally renaming it."""
    result = client.move_item(item_id, body.new_parent_id, body.new_name)
    if result is None:
        raise HTTPException(status_code=500, detail="Move failed")
    return result


@app.post("/drive/items/{item_id}/copy", tags=["Items"])
def copy_item(
    item_id: str, body: CopyBody, client: GraphClient = Depends(get_graph_client)
):
    """Copy an item. Returns async monitor URL for completion status."""
    monitor_url = client.copy_item(item_id, body.new_parent_id, body.new_name)
    if not monitor_url:
        raise HTTPException(status_code=500, detail="Copy failed")
    return {"monitor_url": monitor_url}


@app.delete("/drive/items/{item_id}", tags=["Items"])
def delete_item(item_id: str, client: GraphClient = Depends(get_graph_client)):
    """Permanently delete a file or folder."""
    ok = client.delete_item(item_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Delete failed")
    return {"deleted": item_id}


# ── Thumbnails ─────────────────────────────────────────────────────────────────

@app.get("/drive/items/{item_id}/thumbnails", tags=["Thumbnails"])
def thumbnails(item_id: str, client: GraphClient = Depends(get_graph_client)):
    """Return available thumbnail sizes for an item."""
    return client.get_thumbnails(item_id)


# ── Sharing / Permissions ──────────────────────────────────────────────────────

@app.post("/drive/items/{item_id}/share", tags=["Sharing"])
def create_share_link(
    item_id: str, body: ShareLinkBody, client: GraphClient = Depends(get_graph_client)
):
    """Create a sharing link. link_type: view|edit|embed, scope: anonymous|organization"""
    result = client.create_share_link(item_id, body.link_type, body.scope)
    if result is None:
        raise HTTPException(status_code=500, detail="Share link creation failed")
    return result


@app.get("/drive/items/{item_id}/permissions", tags=["Sharing"])
def list_permissions(item_id: str, client: GraphClient = Depends(get_graph_client)):
    """List all current permissions (shares) on an item."""
    return client.list_permissions(item_id)


@app.delete("/drive/items/{item_id}/permissions/{permission_id}", tags=["Sharing"])
def remove_permission(
    item_id: str, permission_id: str, client: GraphClient = Depends(get_graph_client)
):
    """Revoke a specific permission from an item."""
    ok = client.remove_permission(item_id, permission_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Permission removal failed")
    return {"removed": permission_id}


# ── Version history ────────────────────────────────────────────────────────────

@app.get("/drive/items/{item_id}/versions", tags=["Versions"])
def list_versions(item_id: str, client: GraphClient = Depends(get_graph_client)):
    """Return the version history of a file."""
    return client.list_versions(item_id)

