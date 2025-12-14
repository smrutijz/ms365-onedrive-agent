import requests
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from src.core.config import settings
from src.utils.keyvault import KeyVaultClient
from src.utils.token_manager import TokenManager
from src.clients.graph_api import GraphClient

app = FastAPI()

# ---------- ONE TIME LOGIN ----------
@app.get("/login")
def login():
    params = {
        "client_id": settings.GRAPH_APP_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.GRAPH_APP_REDIRECT_URI,
        "scope": settings.GRAPH_APP_SCOPES,
    }
    query = "&".join(f"{k}={requests.utils.quote(v)}" for k, v in params.items())
    return RedirectResponse(f"{settings.AUTH_URL}?{query}")

@app.get("/callback")
def callback(request: Request):
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
    kv = KeyVaultClient()

    kv.set_secret("onedrive-access-token", token["access_token"])
    kv.set_secret("onedrive-refresh-token", token["refresh_token"])

    return {"status": "tokens stored"}

# ---------- NORMAL API ----------
def graph():
    token = TokenManager().get_access_token()
    return GraphClient(token)

@app.get("/drive/root")
def root():
    return graph().list_root()

@app.get("/drive/folder/{folder_id}")
def folder(folder_id: str):
    return graph().list_folder(folder_id)

@app.get("/drive/search")
def search(q: str):
    return graph().search(q)
