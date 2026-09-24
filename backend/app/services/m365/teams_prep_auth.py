"""Token app-only rejestracji „NEXUS Teams Prep” (prepy w Teams, 0354).

Osobna rejestracja i osobny cache MSAL obok ``app_mail``: tamta aplikacja ma
APPLICATION ``Mail.Read``/``Mail.Send``, a polityka dostępu Exchange zawęża
aplikację do SKRZYNEK, nie do pojedynczych uprawnień. Gdyby kalendarze
zespołu weszły do zakresu tamtej aplikacji, dostałaby też odczyt ich poczty.
Ta rejestracja ma wyłącznie ``Calendars.ReadWrite``,
``OnlineMeetings.ReadWrite.All`` i ``OnlineMeetingTranscript.Read.All``,
zawężone polityką Exchange i Teams do grupy DL i rekruterów.
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
        settings.TEAMS_PREP_CLIENT_ID
        and settings.TEAMS_PREP_CLIENT_SECRET
        and tenant
        and tenant != "common"
    )


def _msal_app() -> msal.ConfidentialClientApplication:
    global _app, _app_key
    key = (settings.TEAMS_PREP_CLIENT_ID, settings.TEAMS_PREP_CLIENT_SECRET, _tenant())
    with _lock:
        if _app is None or _app_key != key:
            _app = msal.ConfidentialClientApplication(
                client_id=settings.TEAMS_PREP_CLIENT_ID,
                authority=f"https://login.microsoftonline.com/{_tenant()}",
                client_credential=settings.TEAMS_PREP_CLIENT_SECRET,
            )
            _app_key = key
        return _app


def acquire_teams_prep_token(*, force_refresh: bool = False) -> Optional[str]:
    """Token ``.default`` albo ``None``. ``force_refresh`` jak w ``app_mail``
    (MSAL odrzuca ``force_refresh`` dla client_credentials, więc czyścimy cache)."""
    if not credentials_configured():
        return None
    app = _msal_app()
    if force_refresh:
        app.remove_tokens_for_client()
    result = app.acquire_token_for_client(scopes=_SCOPE)
    token = result.get("access_token") if isinstance(result, dict) else None
    if not token:
        logger.warning(
            "teams_prep: token acquisition failed error=%s",
            (result or {}).get("error"),
        )
        return None
    return token
