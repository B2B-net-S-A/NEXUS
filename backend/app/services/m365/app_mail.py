"""App-only (client_credentials) Microsoft Graph mail — systemowy nadawca.

Wysyła jako STAŁY mailbox (``M365_MAIL_SENDER_UPN``) przez
``POST /users/{upn}/sendMail`` z **application** permission ``Mail.Send``.
W przeciwieństwie do ``app/services/m365/sender.py`` (delegated, ``/me/...``,
skrzynka konkretnego rekrutera) NIE wymaga per-user OAuth — to kanał dla
powiadomień systemowych (deadline alerts, reset hasła, chat fallback, …).

Bramkowany ``M365_APP_MAIL_ENABLED`` + kompletem creds. Token z MSAL
``ConfidentialClientApplication.acquire_token_for_client`` (scope
``.default``), z wbudowanym cache w singletonie aplikacji MSAL. Wszystko
synchroniczne (jak SMTP-owy ``send_email``), żeby ``send_email`` pozostał
sync i wszyscy dotychczasowi callerzy działali bez zmian.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

import httpx
import msal

from app.core.config import settings

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_SCOPE = ["https://graph.microsoft.com/.default"]

_app_lock = threading.Lock()
_msal_app: Optional[msal.ConfidentialClientApplication] = None
# (client_id, client_secret, tenant) użyte do zbudowania `_msal_app`. Gdy się
# zmienią (np. rotacja creds / env update bez restartu), przebudowujemy app —
# inaczej stary klient z nieaktualnym tenantem/sekretem auth-owałby po cichu źle.
_msal_key: Optional[tuple[str, str, str]] = None


def _tenant() -> str:
    """Tenant dla client_credentials — override lub fallback na M365_TENANT_ID."""
    return settings.M365_MAIL_TENANT_ID or settings.M365_TENANT_ID


def is_configured() -> bool:
    """Czy app-only mail jest włączony i ma komplet creds (realny tenant)."""
    tenant = _tenant()
    return bool(
        settings.M365_APP_MAIL_ENABLED
        and settings.M365_MAIL_SENDER_UPN
        and settings.M365_CLIENT_ID
        and settings.M365_CLIENT_SECRET
        and tenant
        and tenant != "common"
    )


def app_only_credentials_configured() -> bool:
    """Czy da się w ogóle wziąć token client_credentials (bez flag kanału mail).

    Osobno od ``is_configured()``: tamta bramkuje WYSYŁKĘ systemową i wymaga
    ``M365_APP_MAIL_ENABLED`` + skrzynki nadawcy; czytnik zamówień potrzebuje
    tylko poświadczeń rejestracji i realnego tenanta.
    """
    tenant = _tenant()
    return bool(
        settings.M365_CLIENT_ID
        and settings.M365_CLIENT_SECRET
        and tenant
        and tenant != "common"
    )


def acquire_app_token(*, force_refresh: bool = False) -> Optional[str]:
    """Token app-only do Graph (``.default``) albo ``None``.

    ``force_refresh`` kasuje cache MSAL dla tego klienta — używane po 401,
    gdy Graph odrzucił token, który MSAL wciąż uważa za ważny.
    """
    if not app_only_credentials_configured():
        return None
    if force_refresh:
        app = _get_msal_app()
        remove = getattr(app, "remove_tokens_for_client", None)
        if callable(remove):
            remove()
    return _acquire_token()


def _get_msal_app() -> msal.ConfidentialClientApplication:
    """MSAL app z reużyciem token-cache; przebudowa gdy zmienią się creds/tenant."""
    global _msal_app, _msal_key
    key = (settings.M365_CLIENT_ID, settings.M365_CLIENT_SECRET, _tenant())
    with _app_lock:
        if _msal_app is None or _msal_key != key:
            _msal_app = msal.ConfidentialClientApplication(
                client_id=settings.M365_CLIENT_ID,
                authority=f"https://login.microsoftonline.com/{_tenant()}",
                client_credential=settings.M365_CLIENT_SECRET,
            )
            _msal_key = key
        return _msal_app


def _acquire_token() -> Optional[str]:
    app = _get_msal_app()
    # MSAL zwraca token z cache jeśli ważny; inaczej bije po nowy.
    result = app.acquire_token_for_client(scopes=_SCOPE)
    token = result.get("access_token") if isinstance(result, dict) else None
    if not token:
        # `error`/`error_description` bezpieczne do logu (bez sekretów).
        logger.warning(
            "app_mail: token acquisition failed error=%s",
            (result or {}).get("error"),
        )
        return None
    return token


def send_via_graph_app(
    *,
    to: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
) -> bool:
    """Wyślij mail przez Graph app-only. Zwraca True gdy Graph przyjął (202).

    No-op (False) gdy nieskonfigurowane lub błąd — nie rzuca, żeby ścieżki
    fallback/notyfikacji mogły zignorować wynik i wznowić w kolejnym przebiegu.
    HTML gdy podany, inaczej plaintext.
    """
    if not is_configured():
        logger.debug("app_mail: not configured — skip send to=%s", to)
        return False

    token = _acquire_token()
    if not token:
        return False

    if html_body:
        body = {"contentType": "HTML", "content": html_body}
    else:
        body = {"contentType": "Text", "content": text_body}

    payload = {
        "message": {
            "subject": subject,
            "body": body,
            "toRecipients": [{"emailAddress": {"address": to}}],
        },
        # Powiadomienia systemowe — nie zaśmiecamy Sent Items skrzynki serwisowej.
        "saveToSentItems": False,
    }
    url = f"{_GRAPH_BASE}/users/{settings.M365_MAIL_SENDER_UPN}/sendMail"

    try:
        resp = httpx.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "app_mail send failed to=%s subject=%r error=%s",
            to,
            subject,
            type(exc).__name__,
        )
        return False

    if resp.status_code == 202:
        logger.info("app_mail sent to=%s subject=%r", to, subject)
        return True

    # Redact body do 200 znaków — Graph zwraca kod błędu bez naszych sekretów.
    logger.warning(
        "app_mail send to=%s got HTTP %s: %s",
        to,
        resp.status_code,
        resp.text[:200],
    )
    return False
