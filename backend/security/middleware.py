import uuid
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Any:  # noqa: ANN401
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if not request.url.path.startswith(("/docs", "/openapi.json", "/redoc")):
            response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["X-Request-ID"] = str(uuid.uuid4())
        return response
