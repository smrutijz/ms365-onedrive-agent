import logging

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.core.config import settings
from src.utils.token_manager import token_manager
from src.clients.oneDriveHelper import GraphClient
from src.clients.mailHelper import MailClient

logger = logging.getLogger(__name__)

security = HTTPBearer()


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


def get_mail_client(email: str = Depends(get_current_user)) -> MailClient:
    return MailClient(_get_access_token_or_401(email))
