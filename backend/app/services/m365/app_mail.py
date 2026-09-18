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

**Awaria wysyłki musi być głośna** (audyt 18.09.2026). Do tej daty każdy status
inny niż 202 kończył się jednym ``logger.warning`` i ``return False`` — bez
licznika i bez podniesienia gdziekolwiek. ``checks.m365`` sonduje stan
**połączeń** skrzynek rekruterów, więc świecił zielono przez 471 kolejnych
``ErrorAccessDenied`` z tego kanału: konfiguracja nadawcy była zła, a health
o tym nie wiedział, bo nigdy nie pytał o zdolność do WYSYŁKI.

Stan wyniku ostatnich prób żyje w pamięci procesu (wzorem
``services/loop_heartbeat.py`` — backend to jeden uvicorn, a ``/api/health``
pyta ten sam proces, który wysyła). Restart zeruje licznik razem z procesem,
więc po deployu nie ma fałszywego „padało”; pierwsza nieudana próba zapali
sondę z powrotem. Nie zapisujemy tego do bazy: ``send_via_graph_app`` jest
synchroniczne i nie ma sesji, a dodanie jej zmusiłoby do przepisania wszystkich
dotychczasowych callerów.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
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


# --- Stan wysyłki (pamięć procesu) -----------------------------------------
# Próg streaku, po którym sonda degraduje mimo wcześniejszych sukcesów. Graph
# potrafi oddać 429/503 przy przeciążeniu i następna próba przechodzi, więc
# pojedyncza porażka kanału, który DZIAŁA, nie zapala sondy. Kanał, z którego
# nigdy nic nie wyszło (``last_success_at is None``), degraduje od pierwszej
# porażki — tak wygląda zła konfiguracja nadawcy i to jest awaria, którą
# audyt znalazł dopiero po 471 próbach.
SEND_FAILURE_STREAK_DEGRADED = 3


@dataclass(frozen=True)
class AppMailSendState:
    """Migawka wyników ostatnich prób wysyłki. Bez adresów i treści maili."""

    attempts: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    last_failure_code: Optional[str] = None
    last_failure_at: Optional[float] = None
    last_success_at: Optional[float] = None


_send_lock = threading.Lock()
_send_state = AppMailSendState()


def _record_send_success() -> None:
    global _send_state
    with _send_lock:
        _send_state = AppMailSendState(
            attempts=_send_state.attempts + 1,
            failures=_send_state.failures,
            consecutive_failures=0,
            last_failure_code=_send_state.last_failure_code,
            last_failure_at=_send_state.last_failure_at,
            last_success_at=time.time(),
        )


def _record_send_failure(code: str) -> None:
    global _send_state
    now = time.time()
    with _send_lock:
        _send_state = AppMailSendState(
            attempts=_send_state.attempts + 1,
            failures=_send_state.failures + 1,
            consecutive_failures=_send_state.consecutive_failures + 1,
            last_failure_code=code,
            last_failure_at=now,
            last_success_at=_send_state.last_success_at,
        )


def send_state() -> AppMailSendState:
    """Migawka do sondy zdrowia i diagnostyki."""
    with _send_lock:
        return _send_state


def reset_send_state() -> None:
    """Wyłącznie dla testów — produkcja zeruje stan restartem procesu."""
    global _send_state
    with _send_lock:
        _send_state = AppMailSendState()


def app_mail_send_verdict(state: AppMailSendState, *, configured: bool) -> str:
    """``unconfigured`` / ``unknown`` / ``degraded`` / ``healthy``.

    ``unknown`` znaczy „skonfigurowane, ale w tym procesie nic jeszcze nie
    wysyłaliśmy” — to NIE jest ``healthy``: zdolności do wysyłki nie sprawdza
    się inaczej niż wysyłką, a sondowanie jej pustym mailem wysyłałoby maile.
    """
    if not configured:
        return "unconfigured"
    if state.attempts == 0:
        return "unknown"
    if state.consecutive_failures == 0:
        return "healthy"
    if state.last_success_at is None:
        return "degraded"
    if state.consecutive_failures >= SEND_FAILURE_STREAK_DEGRADED:
        return "degraded"
    return "healthy"


def send_health_status() -> str:
    """Werdykt sondy ``checks.m365_mail``."""
    return app_mail_send_verdict(send_state(), configured=is_configured())


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
    gdy Graph odrzucił token, który MSAL wciąż uważa za ważny. Świadomie
    ``remove_tokens_for_client()`` + ponowne ``acquire_token_for_client``:
    MSAL (1.37) **odrzuca** ``acquire_token_for_client(force_refresh=True)``
    ``ValueError``-em („this method does not support force_refresh") — pilnuje
    tego ``test_msal_client_credentials_refresh_contract``.
    """
    if not app_only_credentials_configured():
        return None
    if force_refresh:
        _get_msal_app().remove_tokens_for_client()
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
        _record_send_failure("token")
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
        _record_send_failure(f"transport_{type(exc).__name__}")
        logger.warning(
            "app_mail send failed to=%s subject=%r error=%s streak=%s",
            to,
            subject,
            type(exc).__name__,
            send_state().consecutive_failures,
        )
        return False

    if resp.status_code == 202:
        _record_send_success()
        logger.info("app_mail sent to=%s subject=%r", to, subject)
        return True

    _record_send_failure(f"http_{resp.status_code}")
    streak = send_state().consecutive_failures
    # 401/403 to konfiguracja (zły nadawca, brak zgody administratora, skrzynka
    # poza polityką dostępu aplikacji) — nie naprawi się ponowieniem, więc
    # zgłaszamy je `logger.error` (→ Sentry), a nie kolejnym `warning` w logu,
    # który znika przy deployu. Redakcja treści do 200 znaków: Graph zwraca kod
    # błędu, nasze sekrety w nim nie występują.
    log = logger.error if resp.status_code in (401, 403) else logger.warning
    log(
        "app_mail send to=%s got HTTP %s (streak=%s): %s",
        to,
        resp.status_code,
        streak,
        resp.text[:200],
    )
    return False
