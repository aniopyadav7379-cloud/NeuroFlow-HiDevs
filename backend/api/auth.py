"""POST /auth/token — exchanges client credentials for a JWT."""
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.security.auth import issue_token

logger = logging.getLogger("neuroflow.api.auth")
router = APIRouter()


class TokenRequest(BaseModel):
    client_id: str
    client_secret: str


@router.post("/auth/token")
async def create_token(request: Request, body: TokenRequest):
    settings = request.app.state.settings
    clients = json.loads(settings.auth_clients_json)

    client = clients.get(body.client_id)
    if client is None or client.get("secret") != body.client_secret:
        raise HTTPException(status_code=401, detail="invalid client_id or client_secret")

    return issue_token(body.client_id, client.get("scopes", []), settings.jwt_secret_key)
