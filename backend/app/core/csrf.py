"""Fail-closed CSRF and Origin validation for cookie-authenticated writes."""

from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.session import (
    ACCESS_COOKIE_NAME,
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    REFRESH_COOKIE_NAME,
)


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_SESSION_ESTABLISHMENT_PATHS = frozenset(
    {
        "/api/auth/session/login",
        "/api/auth/microsoft/exchange-session",
    }
)


def _origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def allowed_browser_origins() -> frozenset[str]:
    candidates = [*settings.CORS_ORIGINS, settings.PUBLIC_BASE_URL]
    return frozenset(origin for value in candidates if (origin := _origin(value)))


def is_allowed_browser_origin(value: str | None) -> bool:
    origin = _origin(value or "")
    return origin is not None and origin in allowed_browser_origins()


class CookieCSRFMiddleware(BaseHTTPMiddleware):
    """Protect every authenticated browser mutation.

    Bearer clients do not use ambient credentials and therefore retain their
    existing API contract.  A request carrying either session cookie, without
    an explicit Bearer header, must pass both an exact Origin allowlist and a
    double-submit CSRF token check.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method.upper() in _SAFE_METHODS:
            return await call_next(request)
        if request.url.path in _SESSION_ESTABLISHMENT_PATHS:
            # These endpoints do not yet have a CSRF cookie to double-submit,
            # but still need an exact Origin check. Otherwise a hostile page
            # could force a browser into an attacker-chosen account (login
            # CSRF) or consume an SSO exchange code in ambient context.
            if not is_allowed_browser_origin(request.headers.get("origin")):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "csrf_origin_denied"},
                )
            return await call_next(request)

        has_cookie_session = bool(
            request.cookies.get(ACCESS_COOKIE_NAME)
            or request.cookies.get(REFRESH_COOKIE_NAME)
        )
        has_bearer = (
            request.headers.get("authorization", "").lower().startswith("bearer ")
        )
        if not has_cookie_session or has_bearer:
            return await call_next(request)

        if not is_allowed_browser_origin(request.headers.get("origin")):
            return JSONResponse(
                status_code=403,
                content={"detail": "csrf_origin_denied"},
            )

        cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
        header_token = request.headers.get(CSRF_HEADER_NAME, "")
        if (
            not cookie_token
            or not header_token
            or not secrets.compare_digest(cookie_token, header_token)
        ):
            return JSONResponse(
                status_code=403,
                content={"detail": "csrf_token_invalid"},
            )
        return await call_next(request)
