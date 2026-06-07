import datetime
import logging
import secrets
import requests
import jwt
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse, JSONResponse

from src.core.config import settings
from src.utils.token_manager import token_manager
from src.api.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Auth"])


@router.get("/login")
def login():
    """Redirect to Microsoft OAuth login page."""
    state = secrets.token_urlsafe(32)
    params = {
        "client_id": settings.GRAPH_APP_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.GRAPH_APP_REDIRECT_URI,
        "scope": settings.GRAPH_APP_SCOPES,
        "state": state,
    }
    query = "&".join(f"{k}={requests.utils.quote(v)}" for k, v in params.items())

    response = RedirectResponse(f"{settings.AUTH_URL}?{query}")
    # Stored so /callback can verify the redirect wasn't forged (CSRF / auth-code injection protection)
    response.set_cookie(
        "oauth_state",
        state,
        max_age=600,
        httponly=True,
        samesite="lax",
    )
    return response


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

    state = request.query_params.get("state")
    cookie_state = request.cookies.get("oauth_state")
    if not state or not cookie_state or not secrets.compare_digest(state, cookie_state):
        raise HTTPException(status_code=400, detail="Invalid or missing OAuth state — possible CSRF, please try /login again")

    data = {
        "client_id": settings.GRAPH_APP_CLIENT_ID,
        "client_secret": settings.GRAPH_APP_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.GRAPH_APP_REDIRECT_URI,
        "scope": settings.GRAPH_APP_SCOPES,
    }

    try:
        token_resp = requests.post(settings.TOKEN_URL, data=data, timeout=10)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Failed to reach Microsoft token endpoint: {e}")

    try:
        token = token_resp.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Microsoft token endpoint returned a non-JSON response")

    if "access_token" not in token:
        raise HTTPException(
            status_code=400,
            detail=token.get("error_description", "Token exchange failed"),
        )

    # Pull user's email from Microsoft
    try:
        me_resp = requests.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {token['access_token']}"},
            timeout=10,
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Failed to reach Microsoft Graph: {e}")

    try:
        me = me_resp.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Microsoft Graph returned a non-JSON response")

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

    response = JSONResponse({
        "access_token": bearer,
        "token_type": "bearer",
        "expires_at_utc": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "user": email,
    })
    response.delete_cookie("oauth_state")
    return response


@router.post("/refresh")
def refresh(email: str = Depends(get_current_user)):
    """
    Re-issue a bearer JWT for an already-authenticated user.

    Requires a currently valid Bearer JWT (see /callback). Confirms the
    underlying Microsoft tokens are still usable, then signs a fresh JWT
    with a renewed expiry — no need to repeat the /login redirect flow.
    """
    try:
        token_manager.get_access_token(email)
    except RuntimeError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to verify Microsoft tokens for '{email}' during refresh: {e}")
        raise HTTPException(status_code=401, detail="Unable to verify Microsoft tokens — please login again at /login")

    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=settings.JWT_EXPIRY_HOURS)

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


@router.post("/logout")
def logout(email: str = Depends(get_current_user)):
    """
    Log out the current user — deletes their stored OneDrive/Mail tokens
    from Key Vault. The bearer JWT itself remains valid until it expires,
    but subsequent /drive/* and /mail/* calls will fail until /login again.
    """
    token_manager.revoke_tokens(email)
    return {"detail": f"Logged out '{email}' — tokens revoked. Login again at /login to continue."}
