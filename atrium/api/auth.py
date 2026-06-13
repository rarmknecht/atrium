"""Single-user bearer-token auth.

When an auth token is configured, every /api/* call must carry
`Authorization: Bearer <token>` — except the health check and the webhook hooks
(which authenticate via their own per-trigger path token). The WebSocket carries
the token as a `?token=` query param since browsers can't set WS headers.
"""

import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# /api paths that never require the bearer token
_EXEMPT_PREFIXES = ("/api/health", "/api/hooks/")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str):
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and not path.startswith(_EXEMPT_PREFIXES):
            header = request.headers.get("authorization", "")
            provided = header[7:] if header.lower().startswith("bearer ") else ""
            if not secrets.compare_digest(provided, self._token):
                return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)
