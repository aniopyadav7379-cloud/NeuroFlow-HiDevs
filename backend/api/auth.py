from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.security.auth import create_access_token

router = APIRouter(prefix="/auth", tags=["Admin"])


class TokenRequest(BaseModel):
    client_id: str = Field(
        ..., description="The client ID for authentication.", examples=["client_123"]
    )
    client_secret: str = Field(
        ..., description="The client secret for authentication.", examples=["supersecret"]
    )


@router.post(
    "/token",
    summary="Generate API Access Token",
    description=(
        "Generates a short-lived JWT Bearer token using client credentials. "
        "This token is required in the `Authorization: Bearer <token>` header "
        "for all other endpoints. **Errors**: Returns 401 for invalid credentials."
    ),
    response_description="A JSON object containing the JWT access token and expiration."
)
async def generate_token(req: TokenRequest) -> Any:  # noqa: ANN401
    # Dummy verification - in real world check DB
    if not req.client_id or not req.client_secret:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Example hardcoded scopes for test profiles, or default
    scopes = ["query", "ingest", "admin"]

    token = create_access_token(req.client_id, scopes, expires_in=3600)

    return {"access_token": token, "token_type": "bearer", "expires_in": 3600}
