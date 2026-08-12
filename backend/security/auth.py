"""
JWT API-key authentication. Clients exchange a (client_id, client_secret)
pair for a short-lived bearer token via POST /auth/token; every other
endpoint (except /health and /metrics) requires that token, validated and
scope-checked by the get_current_user dependency.

Client credentials themselves aren't a user-management system — for this
scope, valid client_id/client_secret pairs and their scopes come from a
Settings-configured registry (backend/config.py), not a database table of
users. Swapping that for a real client table later doesn't change
anything below this line.
"""
import logging
import time
import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger("neuroflow.security.auth")

JWT_ALGORITHM = "HS256"
TOKEN_EXPIRY_SECONDS = 3600

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class ClientProfile:
    client_id: str
    scopes: list[str]


def issue_token(client_id: str, scopes: list[str], secret_key: str) -> dict:
    now = int(time.time())
    payload = {
        "sub": client_id,
        "scopes": scopes,
        "exp": now + TOKEN_EXPIRY_SECONDS,
        "iat": now,
        "jti": uuid.uuid4().hex,  # unique per token, useful for future revocation lists
    }
    token = jwt.encode(payload, secret_key, algorithm=JWT_ALGORITHM)
    return {"access_token": token, "token_type": "bearer", "expires_in": TOKEN_EXPIRY_SECONDS}


def decode_token(token: str, secret_key: str) -> ClientProfile:
    try:
        payload = jwt.decode(token, secret_key, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="invalid token")

    client_id = payload.get("sub")
    scopes = payload.get("scopes", [])
    if not client_id:
        raise HTTPException(status_code=401, detail="token missing subject")
    return ClientProfile(client_id=client_id, scopes=scopes)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> ClientProfile:
    if credentials is None:
        raise HTTPException(status_code=401, detail="missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    settings = request.app.state.settings
    return decode_token(credentials.credentials, settings.jwt_secret_key)


def require_scope(scope: str):
    """FastAPI dependency factory: require_scope("admin") as a route
    dependency rejects any caller whose token doesn't carry that scope,
    with 403 (authenticated, just not authorized) rather than 401."""

    async def _dependency(user: ClientProfile = Depends(get_current_user)) -> ClientProfile:
        if scope not in user.scopes:
            raise HTTPException(status_code=403, detail=f"scope '{scope}' required")
        return user

    return _dependency
