"""Komunikaty do konsultantów — treść maila i nadawca administracja@ (O12).

* **Znacznik w temacie** ``[Komunikat <id>/<kod>]``: czytnik skrzynki
  administracja@ przypina po nim odpowiedź do komunikatu. Kod jest losowy, więc
  sam numer wpisany w temat nie przypnie cudzej wiadomości.
* **Pola** ``{imię}`` i ``{opiekun}`` uzupełniają się osobno dla każdej osoby;
  innych pól nie ma (zapis odrzuca nieznane, zanim ktoś wyśle „Cześć {nazwisko}”).
* **Informacyjny** dostaje link wypisu z własnym tokenem osoby; obowiązkowy
  (umowa, rozliczenia, bezpieczeństwo) — nie.
* **Nadawca** to skrzynka M365 administracji (``admin_cases.mailbox``) przez
  rejestrację „NEXUS Kadry” (ta sama, którą czyta czytnik spraw). Gdy adres
  widoczny jest inny (administracja@ na home.pl, NEXUS czyta kopię), mail
  niesie Reply-To na adres widoczny — odpowiedź trafia tam, gdzie czytają
  ludzie, a kopia z niej do Spraw. Tryb bierzemy z ``HR_M365_MODE``: ``off`` = brak nadawcy, ``simulate``
  = nic nie wychodzi (lokalnie i przed przełączeniem), ``live`` = Graph.
  Jeden adresat na mail — nikt nie widzi innych adresów.

Logi niosą wyłącznie kody wyniku — bez adresów, tematów i treści.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets
from dataclasses import dataclass
from typing import Any, Literal, Optional, Protocol

import httpx

from app.core.config import settings
from app.services.admin_cases import mailbox as admin_mailbox

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"

FIRST_NAME = "{imię}"
OWNER = "{opiekun}"
PLACEHOLDERS: tuple[str, ...] = (FIRST_NAME, OWNER)
_PLACEHOLDER_RE = re.compile(r"\{[^{}\s]{1,40}\}")

MARKER_RE = re.compile(r"\[Komunikat (\d{1,9})/([A-Z0-9]{4,8})\]")
TEST_PREFIX = "[Próba] "

Outcome = Literal["accepted", "deferred", "failed", "uncertain", "unavailable"]


@dataclass(frozen=True)
class MailOutcome:
    """Wynik jednej wysyłki: przyjęty, odłożony (ponów), odrzucony, niepewny.

    ``unavailable`` — nie działa całe połączenie z administracja@ (brak
    tokenu, 401 po odświeżeniu, 403, brak połączenia z Graph). Mail na pewno
    nie wyszedł; kolejka kończy przebieg i nikomu nie liczy próby.
    """

    status: Outcome
    code: Optional[str] = None
    simulated: bool = False


class AnnouncementMailer(Protocol):
    async def send(self, *, to: str, subject: str, text: str) -> MailOutcome: ...


# ── Treść ────────────────────────────────────────────────────────────────────


def new_code() -> str:
    return secrets.token_hex(4).upper()


def marker(announcement_id: int, code: str) -> str:
    return f"[Komunikat {announcement_id}/{code}]"


def unknown_placeholders(*texts: str) -> list[str]:
    found: list[str] = []
    for text in texts:
        for token in _PLACEHOLDER_RE.findall(text or ""):
            if token not in PLACEHOLDERS and token not in found:
                found.append(token)
    return found


def new_token() -> tuple[str, str]:
    """(surowy token do maila, SHA-256 do bazy)."""

    raw = secrets.token_urlsafe(32)
    return raw, token_hash(raw)


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def unsubscribe_url(raw_token: str) -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/wypis/{raw_token}"


def owner_label(name: Optional[str], email: Optional[str]) -> str:
    if name and email:
        return f"{name} ({email})"
    return name or email or (sender_address() or "administracja")


def _fill(text: str, *, first_name: Optional[str], owner: str) -> str:
    name = (first_name or "").strip()
    if not name:
        # „Cześć {imię},” bez imienia nie zostawia „Cześć ,”.
        text = re.sub(r"[ \t]*\{imię\}(?=[,.!?])", "", text)
    return text.replace(FIRST_NAME, name).replace(OWNER, owner)


def compose(
    *,
    announcement_id: int,
    code: str,
    kind: str,
    subject: str,
    body: str,
    first_name: Optional[str],
    owner: str,
    unsubscribe: Optional[str],
    test: bool = False,
) -> tuple[str, str]:
    """(temat, treść) maila jednej osoby."""

    text = _fill(body, first_name=first_name, owner=owner).strip()
    footer = [
        "—",
        "Odpowiedz na tę wiadomość, jeśli masz pytania — trafi do zespołu administracji.",
    ]
    if kind == "informational":
        footer.append(
            "Nie chcesz dostawać wiadomości informacyjnych (wydarzenia, życzenia)? "
            f"Wypisz się: {unsubscribe or unsubscribe_url('przyklad')}"
        )
    full_subject = (
        f"{TEST_PREFIX}{subject}"
        if test
        else f"{subject} {marker(announcement_id, code)}"
    )
    return full_subject, f"{text}\n\n" + "\n".join(footer) + "\n"


# ── Nadawca ──────────────────────────────────────────────────────────────────


def sender_address() -> Optional[str]:
    """Adres administracji widoczny dla adresata (ekran, stopka, Reply-To)."""

    return admin_mailbox.public_address()


def transport_mode() -> str:
    from app.services.hr.m365.executor import current_mode

    return current_mode()


class SimulatedMailer:
    """``HR_M365_MODE=simulate``: wysyłka liczy się jak przyjęta, nic nie wychodzi."""

    async def send(self, *, to: str, subject: str, text: str) -> MailOutcome:
        return MailOutcome("accepted", simulated=True)


_UNCERTAIN_STATUSES = frozenset({502, 504})
#: Odmowa dotyczy rejestracji albo skrzynki, nie adresata — tak samo dla
#: każdego w paczce.
_CONNECTION_STATUSES = frozenset({401, 403})
_DEFERRED_STATUSES = frozenset({408, 429})


class GraphMailer:
    """``POST /users/{skrzynka M365}/sendMail`` tokenem rejestracji HR."""

    def __init__(self, mailbox: str, reply_to: Optional[str] = None) -> None:
        self._mailbox = mailbox
        same = reply_to is None or reply_to.casefold() == mailbox.casefold()
        self._reply_to = None if same else reply_to

    async def _token(self, *, force_refresh: bool = False) -> Optional[str]:
        """Token albo ``None`` — awaria MSAL nie wywraca wysyłki."""

        from app.services.hr.m365.auth import acquire_hr_token

        try:
            return await asyncio.to_thread(
                acquire_hr_token, force_refresh=force_refresh
            )
        except Exception as exc:  # noqa: BLE001 — brak tokenu = awaria połączenia
            logger.warning(
                "care_announcement_mail: token niedostępny (%s)", type(exc).__name__
            )
            return None

    async def send(self, *, to: str, subject: str, text: str) -> MailOutcome:
        message: dict[str, Any] = {
            "subject": subject,
            "body": {"contentType": "Text", "content": text},
            "toRecipients": [{"emailAddress": {"address": to}}],
        }
        if self._reply_to:
            message["replyTo"] = [{"emailAddress": {"address": self._reply_to}}]
        payload = {"message": message, "saveToSentItems": True}
        url = f"{_GRAPH_BASE}/users/{self._mailbox}/sendMail"
        token = await self._token()
        if not token:
            return MailOutcome("unavailable", "token")
        # ``posted`` = żądanie mogło dojść do Graph; dopiero wtedy wyjątek
        # znaczy „niepewny”. Wcześniej mail na pewno nie wyszedł.
        posted = False
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                posted = True
                response = await client.post(
                    url, json=payload, headers={"Authorization": f"Bearer {token}"}
                )
                if response.status_code == 401:
                    # 401 = Graph odrzucił token, mail nie wyszedł.
                    token = await self._token(force_refresh=True)
                    if not token:
                        return MailOutcome("unavailable", "token")
                    response = await client.post(
                        url, json=payload, headers={"Authorization": f"Bearer {token}"}
                    )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            return MailOutcome("unavailable", "transport_connect")
        except Exception:  # noqa: BLE001 — wynik nieznany, bez ponowienia
            logger.warning("care_announcement_mail: wysyłka przerwana")
            return MailOutcome("uncertain" if posted else "unavailable", "transport")
        status_code = response.status_code
        if status_code == 202:
            return MailOutcome("accepted")
        if status_code in _UNCERTAIN_STATUSES:
            return MailOutcome("uncertain", f"http_{status_code}")
        if status_code in _CONNECTION_STATUSES:
            return MailOutcome("unavailable", f"http_{status_code}")
        if status_code in _DEFERRED_STATUSES or status_code >= 500:
            return MailOutcome("deferred", f"http_{status_code}")
        return MailOutcome("failed", f"http_{status_code}")


def transport_status() -> str:
    """``off`` / ``simulate`` / ``live`` / ``unconfigured`` (``live`` bez skrzynki
    albo poświadczeń rejestracji) — do ekranu, bez adresów i sekretów."""

    mode = transport_mode()
    if mode == "live" and default_mailer() is None:
        return "unconfigured"
    return mode


def default_mailer() -> Optional[AnnouncementMailer]:
    """Nadawca według trybu albo ``None``, gdy wysyłka z administracja@ nie działa."""

    mode = transport_mode()
    if mode == "simulate":
        return SimulatedMailer()
    if mode != "live":
        return None
    from app.services.hr.m365.auth import credentials_configured

    mailbox = admin_mailbox.m365_mailbox()
    if mailbox is None or not credentials_configured():
        return None
    return GraphMailer(mailbox, reply_to=admin_mailbox.public_address())
