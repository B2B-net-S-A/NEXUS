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

Stan prób i blokada ponowień są trwałe, wspólne dla workerów i izolowane
hashem tenanta, aplikacji oraz nadawcy. Treści i adresy nie trafiają do logów.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from dataclasses import dataclass
from typing import Optional

import httpx
import msal

from app.core.config import settings
from app.services.m365 import mail_circuit

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_SCOPE = ["https://graph.microsoft.com/.default"]

_app_lock = threading.Lock()
_msal_app: Optional[msal.ConfidentialClientApplication] = None
# (client_id, client_secret, tenant) użyte do zbudowania `_msal_app`. Gdy się
# zmienią (np. rotacja creds / env update bez restartu), przebudowujemy app —
# inaczej stary klient z nieaktualnym tenantem/sekretem auth-owałby po cichu źle.
_msal_key: Optional[tuple[str, str, str]] = None


# --- Stan wysyłki (trwały, współdzielony) -----------------------------------------
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


_delivery_local = threading.local()


def last_delivery_uncertain() -> bool:
    """Read only immediately after sending, in the same worker thread."""
    return bool(getattr(_delivery_local, "uncertain", False))


def send_state() -> AppMailSendState:
    state = mail_circuit.snapshot()
    return AppMailSendState(
        **{k: state[k] for k in AppMailSendState.__dataclass_fields__ if k in state}
    )


def reset_send_state() -> None:
    """Test helper: reset only the injected test store, never production state."""
    mail_circuit.transition(lambda state, now: state.clear())


def app_mail_send_verdict(state: AppMailSendState, *, configured: bool) -> str:
    """``unconfigured`` / ``unknown`` / ``degraded`` / ``healthy``.

    ``unknown`` znaczy „skonfigurowane, ale ten nadawca nic jeszcze nie
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
    if state.last_failure_code in {
        "http_401",
        "http_403",
        "token",
        "delivery_uncertain",
    }:
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


def _retry_after(resp) -> float:
    value = getattr(resp, "headers", {}).get("Retry-After", "")
    try:
        return max(0, float(value))
    except (ValueError, TypeError):
        try:
            return max(
                0,
                (
                    parsedate_to_datetime(value) - datetime.now(timezone.utc)
                ).total_seconds(),
            )
        except (ValueError, TypeError, OverflowError):
            return 0


def _finish(ticket: int, code: str | None, retry_after: float = 0) -> None:
    changed = mail_circuit.finish(ticket, code=code, retry_after=retry_after)
    logger.info(
        "app_mail_outcome",
        extra={
            "event_kind": "app_mail_outcome",
            "outcome": "accepted" if code is None else "failure",
            "failure_kind": code or "none",
        },
    )
    if changed:
        logger.warning(
            "app_mail_state",
            extra={
                "event_kind": "app_mail_state",
                "failure_kind": code or "recovered",
                "operation": "m365.app_mail",
            },
        )
        if code:
            import sentry_sdk

            with sentry_sdk.new_scope() as scope:
                scope.set_tag("operation", "m365.app_mail")
                scope.set_tag("failure_kind", code)
                scope.set_tag("terminal", "true")
                scope.set_tag("sampling_policy", "integration-state-transition")
                incident_id = mail_circuit.snapshot().get("incident_id")
                if incident_id:
                    scope.set_context("correlation", {"operation_id": incident_id})
                scope.fingerprint = ["m365.app_mail", code]
                sentry_sdk.capture_message("System mail delivery failed", level="error")


def send_via_graph_app(
    *,
    to: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
) -> bool:
    """True means Graph accepted, not delivered. No raw Graph text is logged.

    The bool contract stays intact. The chat worker also reads the thread-local
    uncertainty flag so a POST with an unknown outcome is never blindly retried.
    Failure of the durable gate fails closed before any network call.
    """
    _delivery_local.uncertain = False
    if not is_configured():
        return False
    try:
        ticket = mail_circuit.acquire()
    except Exception:
        logger.warning(
            "app_mail state unavailable",
            extra={"event_kind": "app_mail_state", "failure_kind": "state_unavailable"},
        )
        return False
    if ticket is None:
        return False
    payload = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML" if html_body else "Text",
                "content": html_body or text_body,
            },
            "toRecipients": [{"emailAddress": {"address": to}}],
        },
        "saveToSentItems": False,
    }
    url = f"{_GRAPH_BASE}/users/{settings.M365_MAIL_SENDER_UPN}/sendMail"
    posted = False
    try:
        token = _acquire_token()
        if not token:
            _finish(ticket, "token")
            return False
        posted = True
        resp = httpx.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
        )
        if resp.status_code == 401:
            # Only a definite rejection is safe to retry after a token refresh.
            posted = False
            token = acquire_app_token(force_refresh=True)
            if not token:
                _finish(ticket, "token")
                return False
            posted = True
            resp = httpx.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=15.0,
            )
        if resp.status_code == 202:
            # From this point, a failed state write must not turn acceptance
            # into a retryable rejection.
            try:
                _finish(ticket, None)
            except Exception:
                logger.warning(
                    "app_mail accepted; state unavailable",
                    extra={
                        "event_kind": "app_mail_state",
                        "failure_kind": "state_unavailable",
                    },
                )
            return True
        posted = False  # an explicit response, not a lost response
        _finish(ticket, f"http_{resp.status_code}", _retry_after(resp))
        return False
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
        code = "transport_connect"
    except Exception:
        _delivery_local.uncertain = posted
        code = "delivery_uncertain" if posted else "token_or_state"
    try:
        _finish(ticket, code)
    except Exception:
        logger.warning(
            "app_mail state unavailable",
            extra={"event_kind": "app_mail_state", "failure_kind": "state_unavailable"},
        )
    return False
