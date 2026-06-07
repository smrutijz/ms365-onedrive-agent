import datetime
import requests
import jwt
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse

from src.core.config import settings
from src.utils.token_manager import token_manager

router = APIRouter(tags=["Auth"])


@router.get("/login")
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


@router.get("/callback")
def callback(request: Request):
    """
    OAuth callback. After Microsoft login this endpoint:
    1. Exchanges the auth code for OneDrive/Mail tokens
    2. Fetches the user's email from /me
    3. Stores tokens in Key Vault under that email
    4. Returns a signed JWT Bearer token

    Use the returned access_token as: Authorization: Bearer <token>
    on all /drive/* and /mail/* endpoints. Login again at /login to get a new token.
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

    # Store OneDrive/Mail tokens per user in Key Vault
    token_manager.store_tokens(email, token)

    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=settings.JWT_EXPIRY_HOURS)

    # Issue signed JWT
    bearer = jwt.encode(
        {
            "email": email,
            "exp": expires_at,
        },
        settings.JWT_SECRET,
        algorithm="HS256",
    )

    return {
        "access_token": bearer,
        "token_type": "bearer",
        "expires_at_utc": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "user": email,
    }
