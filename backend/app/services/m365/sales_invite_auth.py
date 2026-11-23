"""Token app-only rejestracji „NEXUS Sales Invite” (decyzja Artura 23.11.2026).

Zaproszenie z kolejki dzwonienia wysyła osoba, która umawia, a spotkanie Teams
powstaje w kalendarzu PROWADZĄCEGO (``services/sales/booking_invite.py``). Osoba
klikająca nie ma dostępu do cudzej skrzynki, więc zapis robi aplikacja.

Osobna rejestracja, jak „NEXUS Teams Prep” (``teams_prep_auth``): polityka
Exchange zawęża aplikację do SKRZYNEK, nie do uprawnień. Ta rejestracja ma tylko
``Calendars.ReadWrite`` przez Exchange App RBAC na skrzynki prowadzących
spotkania sprzedaży; prepy z transkryptami i kalendarze DL-i zostają poza nią.
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
    return settings.M365_MAIL_TENANT_ID or settings.M365_TENANT_ID


def credentials_configured() -> bool:
    """Komplet poświadczeń i realny tenant (client_credentials nie działa z ``common``)."""
    tenant = _tenant()
    return bool(
        settings.SALES_INVITE_CLIENT_ID
        and settings.SALES_INVITE_CLIENT_SECRET
        and tenant
        and tenant != "common"
    )


def _msal_app() -> msal.ConfidentialClientApplication:
    global _app, _app_key
    key = (
        settings.SALES_INVITE_CLIENT_ID,
        settings.SALES_INVITE_CLIENT_SECRET,
        _tenant(),
    )
    with _lock:
        if _app is None or _app_key != key:
            _app = msal.ConfidentialClientApplication(
                client_id=settings.SALES_INVITE_CLIENT_ID,
                authority=f"https://login.microsoftonline.com/{_tenant()}",
                client_credential=settings.SALES_INVITE_CLIENT_SECRET,
            )
            _app_key = key
        return _app


def acquire_sales_invite_token(*, force_refresh: bool = False) -> Optional[str]:
    """Token ``.default`` albo ``None`` (jak ``acquire_teams_prep_token``).

    Każdy błąd MSAL to ``None``: MSAL łączy się z Entra przez ``requests``, nie httpx,
    więc jego wyjątki (sieć, zapora stagingu, zły tenant) inaczej trafiłyby do „nie
    wiadomo, czy wyszło”, choć do Graph nic nie poszło (przegląd 23.11.2026).
    """
    if not credentials_configured():
        return None
    try:
        app = _msal_app()
        if force_refresh:
            app.remove_tokens_for_client()
        result = app.acquire_token_for_client(scopes=_SCOPE)
    except Exception as exc:  # noqa: BLE001 — wołający dostaje „brak tokenu”
        logger.warning("sales_invite: token request failed (%s)", type(exc).__name__)
        return None
    token = result.get("access_token") if isinstance(result, dict) else None
    if not token:
        logger.warning(
            "sales_invite: token acquisition failed error=%s",
            (result or {}).get("error"),
        )
        return None
    return token
