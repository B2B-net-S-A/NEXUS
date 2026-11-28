"""Token app-only rejestracji „NEXUS Defender (odczyt)” — źródło ekranu Bezpieczeństwo.

Zlecenie Artura z 28.11.2026: incydenty Defendera trafiają na ekran
Ustawienia → Bezpieczeństwo. Osobna rejestracja i osobny cache MSAL, bo
aplikacja poczty ma APPLICATION ``Mail.Send``/``Mail.Read``, a ta ma
wyłącznie ``SecurityIncident.Read.All`` i ``SecurityEvents.Read.All``
(odczyt). Wyciek sekretu tej aplikacji pozwala czytać incydenty, ale nie
wysłać maila ani niczego zmienić w Defenderze. Instrukcja rejestracji:
``docs/claude/ui/ekran-bezpieczenstwo.md`` (sekcja „Microsoft Defender”).
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

import msal

from app.core.config import settings

logger = logging.getLogger(__name__)

_SCOPE = ["https://graph.microsoft.com/.default"]

_lock = threading.Lock()
_app: Optional[msal.ConfidentialClientApplication] = None
_app_key: Optional[tuple[str, str, str]] = None


def _tenant() -> str:
    return (
        settings.DEFENDER_TENANT_ID
        or settings.M365_MAIL_TENANT_ID
        or settings.M365_TENANT_ID
    )


def credentials_configured() -> bool:
    """Komplet poświadczeń i realny tenant (client_credentials nie działa z ``common``)."""
    tenant = _tenant()
    return bool(
        settings.DEFENDER_CLIENT_ID
        and settings.DEFENDER_CLIENT_SECRET
        and tenant
        and tenant not in ("common", "organizations")
    )


def _msal_app() -> msal.ConfidentialClientApplication:
    global _app, _app_key
    key = (settings.DEFENDER_CLIENT_ID, settings.DEFENDER_CLIENT_SECRET, _tenant())
    with _lock:
        if _app is None or _app_key != key:
            _app = msal.ConfidentialClientApplication(
                client_id=settings.DEFENDER_CLIENT_ID,
                authority=f"https://login.microsoftonline.com/{_tenant()}",
                client_credential=settings.DEFENDER_CLIENT_SECRET,
            )
            _app_key = key
        return _app


class DefenderTokenError(Exception):
    """Entra odmówił tokenu — w stanie źródła ląduje sam kod błędu."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def acquire_defender_token(*, force_refresh: bool = False) -> str:
    """Token ``.default``; brak = ``DefenderTokenError`` z kodem Entra
    (np. ``invalid_client`` przy złym sekrecie). Bez opisu błędu, bo MSAL
    wkleja do niego identyfikatory tenanta i aplikacji."""
    app = _msal_app()
    if force_refresh:
        app.remove_tokens_for_client()
    result = app.acquire_token_for_client(scopes=_SCOPE)
    token = result.get("access_token") if isinstance(result, dict) else None
    if not token:
        code = str((result or {}).get("error") or "no_token")[:60]
        logger.warning("defender: Entra odmówił logowania aplikacji (kod %s)", code)
        raise DefenderTokenError(code)
    return token
