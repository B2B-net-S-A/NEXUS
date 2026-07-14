"""Browser session cookies and CSRF constants.

The regular web application authenticates with an HttpOnly access cookie.  The
legacy Bearer endpoints remain available during the staged rollout for the
Chrome/Outlook integrations, but browser code never receives tokens from the
cookie-session endpoints.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from fastapi import Response

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token

if TYPE_CHECKING:
    from app.models.user import User


ACCESS_COOKIE_NAME = f"{settings.SESSION_COOKIE_PREFIX}_access"
REFRESH_COOKIE_NAME = f"{settings.SESSION_COOKIE_PREFIX}_refresh"
CSRF_COOKIE_NAME = f"{settings.SESSION_COOKIE_PREFIX}_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"


def _cookie_domain() -> str | None:
    domain = settings.SESSION_COOKIE_DOMAIN.strip()
    return domain or None


def set_browser_session(response: Response, user: User) -> None:
    """Issue a fresh browser session without exposing either JWT in the body."""
    access_token = create_access_token(
        user.id,
        user.role.value,
        token_version=user.token_version,
        force_password_change=user.force_password_change,
    )
    refresh_token = create_refresh_token(
        user.id,
        token_version=user.token_version,
    )
    csrf_token = secrets.token_urlsafe(32)
    common = {
        "domain": _cookie_domain(),
        "secure": settings.SESSION_COOKIE_SECURE,
        "samesite": "lax",
    }
    response.set_cookie(
        ACCESS_COOKIE_NAME,
        access_token,
        httponly=True,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
        **common,
    )
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        refresh_token,
        httponly=True,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/api/auth",
        **common,
    )
    # Double-submit value: readable by the web app, never an authentication
    # secret.  The backend compares it in constant time and also validates
    # Origin before accepting a cookie-authenticated mutation.
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        httponly=False,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/",
        **common,
    )


def clear_browser_session(response: Response) -> None:
    """Expire all browser-session cookies with the same scope used at issue."""
    common = {
        "domain": _cookie_domain(),
        "secure": settings.SESSION_COOKIE_SECURE,
        "samesite": "lax",
    }
    response.delete_cookie(
        ACCESS_COOKIE_NAME,
        path="/",
        httponly=True,
        **common,
    )
    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        path="/api/auth",
        httponly=True,
        **common,
    )
    response.delete_cookie(
        CSRF_COOKIE_NAME,
        path="/",
        httponly=False,
        **common,
    )
