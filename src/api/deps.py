import logging

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.core.config import settings
from src.utils.token_manager import token_manager
from src.clients.oneDriveHelper import GraphClient
from src.clients.mailHelper import MailClient, DomainScopedMailClient

logger = logging.getLogger(__name__)

security = HTTPBearer()


def _decode_jwt(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Decode and verify the Bearer JWT; return the full payload."""
    try:
        return jwt.decode(credentials.credentials, settings.JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired — login again at /login")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_current_user(payload: dict = Depends(_decode_jwt)) -> str:
    """Return the authenticated user's email from the JWT."""
    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return email


def _get_access_token_or_401(email: str) -> str:
    try:
        return token_manager.get_access_token(email)
    except RuntimeError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get access token for '{email}': {e}")
        raise HTTPException(status_code=401, detail="Unable to access Microsoft tokens — please login again at /login")


def get_graph_client(email: str = Depends(get_current_user)) -> GraphClient:
    return GraphClient(_get_access_token_or_401(email))


def get_mail_client(payload: dict = Depends(_decode_jwt)) -> MailClient:
    """Return a MailClient scoped by the JWT's scope claim.

    If the token carries Mail.ReadWrite.DomainScoped and MAIL_ALLOWED_DOMAINS
    is configured, returns a DomainScopedMailClient that filters by sender domain.
    """
    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    access_token = _get_access_token_or_401(email)
    scope = payload.get("scope", "")

    if settings.MAIL_ALLOWED_DOMAINS:
        if "Mail.ReadWrite.DomainScoped" not in scope:
            raise HTTPException(
                status_code=403,
                detail="Mail access requires domain-scoped consent — please login again at /login",
            )
        return DomainScopedMailClient(access_token, settings.MAIL_ALLOWED_DOMAINS)
    return MailClient(access_token)
