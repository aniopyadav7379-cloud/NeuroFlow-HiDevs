from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.security.auth import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenRequest(BaseModel):
    client_id: str
    client_secret: str


@router.post("/token")
async def generate_token(req: TokenRequest) -> Any:  # noqa: ANN401
    # Dummy verification - in real world check DB
    if not req.client_id or not req.client_secret:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Example hardcoded scopes for test profiles, or default
    scopes = ["query", "ingest", "admin"]

    token = create_access_token(req.client_id, scopes, expires_in=3600)

    return {"access_token": token, "token_type": "bearer", "expires_in": 3600}
