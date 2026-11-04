"""Token app-only rejestracji „NEXUS Kadry” (D3: własna rejestracja NEXUSA).

Osobna rejestracja i osobny cache MSAL obok ``app_mail`` i ``teams_prep_auth``:
autoodpowiedź, reguły skrzynki i wydarzenie „Poza biurem” wymagają APPLICATION
``MailboxSettings.ReadWrite`` i ``Calendars.ReadWrite`` na skrzynkach całego
zespołu, a polityka dostępu Exchange zawęża aplikację do SKRZYNEK, nie do
uprawnień — dopisanie ich do rejestracji czytnika zamówień dałoby jej odczyt
poczty wszystkich. Tenant jak w ``teams_prep_auth`` (``M365_MAIL_TENANT_ID``).

Ustawienia ``HR_M365_CLIENT_ID`` / ``HR_M365_CLIENT_SECRET`` czytamy przez
``getattr`` — moduł działa (i mówi „brak poświadczeń”), zanim pola trafią do
``config.py``.
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


def _client_id() -> str:
    return str(getattr(settings, "HR_M365_CLIENT_ID", "") or "")


def _client_secret() -> str:
    return str(getattr(settings, "HR_M365_CLIENT_SECRET", "") or "")


def _tenant() -> str:
    return settings.M365_MAIL_TENANT_ID or settings.M365_TENANT_ID


def credentials_configured() -> bool:
    """Komplet poświadczeń i realny tenant (client_credentials nie działa z ``common``)."""
    tenant = _tenant()
    return bool(_client_id() and _client_secret() and tenant and tenant != "common")


def _msal_app() -> msal.ConfidentialClientApplication:
    global _app, _app_key
    key = (_client_id(), _client_secret(), _tenant())
    with _lock:
        if _app is None or _app_key != key:
            _app = msal.ConfidentialClientApplication(
                client_id=_client_id(),
                authority=f"https://login.microsoftonline.com/{_tenant()}",
                client_credential=_client_secret(),
            )
            _app_key = key
        return _app


def acquire_hr_token(*, force_refresh: bool = False) -> Optional[str]:
    """Token ``.default`` albo ``None`` (jak ``acquire_teams_prep_token``)."""
    if not credentials_configured():
        return None
    app = _msal_app()
    if force_refresh:
        app.remove_tokens_for_client()
    result = app.acquire_token_for_client(scopes=_SCOPE)
    token = result.get("access_token") if isinstance(result, dict) else None
    if not token:
        logger.warning(
            "hr_m365: token acquisition failed error=%s",
            (result or {}).get("error"),
        )
        return None
    return token
