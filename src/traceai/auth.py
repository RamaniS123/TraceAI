"""Opaque bearer credentials with separate reset permission."""
from secrets import compare_digest

from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from traceai.errors import APIError

bearer = HTTPBearer(auto_error=False, scheme_name="bearerAuth")


def require_access(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    settings = request.app.state.settings
    candidate = credentials.credentials.encode() if credentials else b""
    reset = settings.reset_token.get_secret_value().encode() if settings.reset_token else b""
    ordinary = settings.api_token.get_secret_value().encode() if settings.api_token else b""
    is_reset = bool(candidate and reset) and compare_digest(candidate, reset)
    is_api = bool(candidate and ordinary) and compare_digest(candidate, ordinary)
    if is_reset:
        return "reset"
    if is_api:
        return "api"
    raise APIError(401, "UNAUTHORIZED", "Valid bearer credentials are required.")


def require_reset(role: str = Depends(require_access)):
    if role != "reset":
        raise APIError(403, "FORBIDDEN", "Reset permission is required.")
