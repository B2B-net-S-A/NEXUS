"""Sesja przeglądarki w ciasteczku ``HttpOnly`` i ochrona CSRF.

Do 11.2026 JWT dostępu leżał w ``localStorage`` i w ciasteczku ``nexus_access``
pisanym przez ``document.cookie`` — oba czytelne z JS, więc każda luka XSS
kończyła się wyniesieniem tokenu i działaniem jako zalogowana osoba poza
przeglądarką. Teraz ciasteczko ustawia backend z ``HttpOnly``, a front go nie
widzi. Nazwa zostaje ta sama, bo czyta je bramka routingu Next.js
(``frontend/src/middleware.ts``) po stronie serwera.

``Authorization: Bearer`` działa dalej i ma pierwszeństwo: dodatek Outlooka,
e2e, skrypty i Jarvis. Przeglądarka nie dokleja go sama, więc CSRF dotyczy
wyłącznie żądań uwierzytelnionych ciasteczkiem.

CSRF: metoda zmieniająca stan + ciasteczko wymaga nagłówka ``X-Nexus-CSRF``
i ``Origin`` z ``CORS_ORIGINS``. Nagłówek niestandardowy wymusza preflight
CORS, którego obca strona nie przejdzie, a formularz HTML nie umie go wysłać;
``Origin`` domyka przypadek strony z tej samej witryny (inna poddomena).
"""

from typing import Optional

from fastapi import HTTPException, Request, Response, status

from app.core.config import settings

SESSION_COOKIE_NAME = "nexus_access"
CSRF_HEADER = "X-Nexus-CSRF"
#: 8 h — tyle żyje token dostępu (``ACCESS_TOKEN_EXPIRE_MINUTES``).
_FALLBACK_MAX_AGE_S = 8 * 60 * 60

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

CSRF_DENIED_DETAIL = (
    "Żądanie odrzucone przez ochronę sesji — odśwież stronę i spróbuj ponownie."
)


def _max_age_s() -> int:
    minutes = getattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", None)
    return int(minutes) * 60 if minutes else _FALLBACK_MAX_AGE_S


def _origin_host(origin: Optional[str]) -> Optional[str]:
    if not origin or "://" not in origin:
        return None
    host = origin.split("://", 1)[1].split("/", 1)[0]
    return host.rsplit(":", 1)[0].lower() if host else None


def origin_allowed(origin: Optional[str]) -> bool:
    """Czy ``Origin`` to front NEXUSA (lista CORS, bez wtyczek Chrome)."""
    if not origin:
        return False
    return origin.rstrip("/") in {o.rstrip("/") for o in settings.CORS_ORIGINS}


def cookie_domain(request: Request) -> Optional[str]:
    """Domena ciasteczka: host frontu, gdy API jest jego poddomeną.

    Produkcja: front ``nexus.b2bnetwork.pl``, API ``api.nexus.b2bnetwork.pl``
    → ``Domain=nexus.b2bnetwork.pl``, żeby bramka routingu na hoście frontu
    widziała ciasteczko ustawione przez API. Staging (``localhost:3100`` /
    ``localhost:8100``) i testy → ciasteczko tylko dla hosta (porty ciasteczek
    nie dzielą). Bez nowej zmiennej środowiskowej: host frontu bierzemy
    z ``Origin``, ale tylko dozwolonego.
    """
    origin = request.headers.get("origin")
    if not origin_allowed(origin):
        return None
    front = _origin_host(origin)
    api = (request.url.hostname or "").lower()
    if front and api != front and api.endswith("." + front):
        return front
    return None


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=_max_age_s(),
        path="/",
        domain=cookie_domain(request),
        secure=True,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        domain=cookie_domain(request),
        secure=True,
        httponly=True,
        samesite="lax",
    )


def session_cookie_token(request: Request) -> Optional[str]:
    value = request.cookies.get(SESSION_COOKIE_NAME)
    return value or None


def enforce_cookie_csrf(request: Request) -> None:
    """403 dla zapisu uwierzytelnionego ciasteczkiem bez nagłówka i Origin."""
    if request.method.upper() not in _UNSAFE_METHODS:
        return
    if request.headers.get(CSRF_HEADER) and origin_allowed(
        request.headers.get("origin")
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail=CSRF_DENIED_DETAIL
    )


def request_bearer_token(request: Request) -> Optional[str]:
    """Token żądania: nagłówek ``Bearer`` albo ciasteczko sesji.

    Dla kodu, który podaje poświadczenie dalej (Jarvis woła API tokenem
    pytającego) albo liczy klucz limitu per osoba.
    """
    scheme, _, token = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() == "bearer" and token:
        return token
    return session_cookie_token(request)
