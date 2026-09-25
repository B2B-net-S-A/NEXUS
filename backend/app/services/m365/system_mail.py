"""Delegated system-mail — powiadomienia systemowe z jednej skrzynki serwisowej
przez ISTNIEJĄCE połączenie M365 (delegated), bez app-only consentu.

Wybiera aktywne ``M365Connection`` dla ``settings.M365_MAIL_SENDER_UPN`` i wysyła
przez ``GraphClient`` (draft + send) — dokładnie ten sam mechanizm co
``m365/sender.send_new`` (rejection-maile), ale **bez** logowania do tabeli
``emails`` / wstrzykiwania podpisu / sprzężenia z kandydatem. To maile systemowe
(deadline-alerty itd.), nie korespondencja kandydacka.

Dzięki temu maile działają zaraz po tym, jak ktoś podłączy skrzynkę
``M365_MAIL_SENDER_UPN`` przez „Połącz Microsoft 365" w Nexusie — nie trzeba
application-permission ``Mail.Send`` ani admin-consentu w Azure (delegated
``Mail.Send`` jest już w ``M365_SCOPES`` i skonsentowany dla istniejących
połączeń).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.m365 import M365Connection
from app.services.m365.graph_client import GraphClient, GraphRequestError

logger = logging.getLogger(__name__)

# Wynik „nie wiadomo” (audyt 25.09.2026). `send_system_email` zwraca
# True (Graph przyjął), False (na pewno nie wysłano — wolno ponowić) albo
# None (żądanie `/send` wyszło, odpowiedź zginęła — mail MÓGŁ wyjść).
# Do tej zmiany ReadTimeout na `/send` kończył się usunięciem draftu
# i `False`, więc wołający zwalniał rezerwację i wysyłał drugi raz.
DELIVERY_UNCERTAIN: None = None

# Błędy po wysłaniu żądania, przy których serwer mógł je przyjąć: zginęła
# odpowiedź albo połączenie po nadaniu (GraphClient nie ponawia POST-ów po
# nich — INT-06). Twardy limit czasu GraphClienta (599) też tu należy.
_UNCERTAIN_TRANSPORT = (httpx.ReadTimeout, httpx.ReadError, httpx.RemoteProtocolError)


def recipient_ref(address: str) -> str:
    """Skrót adresu do logu — log nie niesie adresu ani tematu (PII)."""
    return hashlib.sha256(address.strip().lower().encode("utf-8")).hexdigest()[:12]


def _is_uncertain_send_error(exc: BaseException) -> bool:
    if isinstance(exc, _UNCERTAIN_TRANSPORT):
        return True
    return isinstance(exc, GraphRequestError) and getattr(exc, "status", None) == 599


def app_mail_send_outcome(ok: bool) -> Optional[bool]:
    """Wynik wysyłki kanałem app-only/SMTP w tym samym wątku co wysyłka.

    `send_via_graph_app` zwraca bool, a „nie wiadomo” zostawia w fladze
    wątku (`last_delivery_uncertain`), więc tę funkcję trzeba wołać w wątku,
    w którym poszła wysyłka (wewnątrz `asyncio.to_thread`). Blokada polityki
    wysyłek nie uruchamia wysyłki, więc wtedy flaga jest nieaktualna.
    """
    if ok:
        return True
    if not settings.M365_APP_MAIL_ENABLED:
        return False
    from app.services.m365.app_mail import last_delivery_uncertain
    from app.services.notification_delivery import last_send_policy_blocked

    if not last_send_policy_blocked() and last_delivery_uncertain():
        return DELIVERY_UNCERTAIN
    return False


async def get_system_sender_connection(db: AsyncSession) -> Optional[M365Connection]:
    """Aktywne połączenie M365 skrzynki nadawczej (``M365_MAIL_SENDER_UPN``).

    None gdy brak skonfigurowanego UPN-a albo nikt jeszcze nie podłączył tej
    skrzynki w Nexusie. Match po ``mailbox_upn`` case-insensitive; najnowsze.
    """
    upn = (settings.M365_MAIL_SENDER_UPN or "").strip()
    if not upn:
        return None
    return await db.scalar(
        select(M365Connection)
        .where(func.lower(M365Connection.mailbox_upn) == upn.lower())
        .where(M365Connection.is_active.is_(True))
        .order_by(M365Connection.updated_at.desc())
        .limit(1)
    )


async def send_system_email(
    db: AsyncSession,
    connection: M365Connection,
    *,
    to: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
    delivery_kind: str | None = None,
    event_at: datetime | None = None,
) -> Optional[bool]:
    """Wyślij mail systemowy przez delegated Graph (draft + send).

    True — Graph przyjął; False — na pewno nie wysłano (wolno ponowić);
    ``None`` (:data:`DELIVERY_UNCERTAIN`) — żądanie `/send` wyszło, a odpowiedź
    zginęła: mail mógł wyjść, więc wołający NIE może zwolnić rezerwacji
    i wysłać drugi raz. Nie rzuca. HTML gdy podany, inaczej Text.
    """
    if html_body:
        body = {"contentType": "HTML", "content": html_body}
    else:
        body = {"contentType": "Text", "content": text_body}
    payload = {
        "subject": subject,
        "body": body,
        "toRecipients": [{"emailAddress": {"address": to}}],
    }
    try:
        async with GraphClient(connection, db) as gc:
            draft = await gc.post("/me/messages", json=payload)
            message_id = draft.get("id") if isinstance(draft, dict) else None
            if not message_id:
                logger.warning(
                    "system_mail: draft bez id (to_ref=%s)", recipient_ref(to)
                )
                return False
            try:
                if delivery_kind is not None:
                    from app.services.notification_delivery import load_policy

                    # Draft creation/token refresh can outlast an admin toggle.
                    # Recheck at the final send boundary, including a new cutoff
                    # after OFF -> ON, while the draft is still unsent.
                    if not (await load_policy(db)).allows(delivery_kind, event_at):
                        try:
                            await gc.delete(f"/me/messages/{message_id}")
                        except Exception:  # noqa: BLE001
                            logger.warning(
                                "system_mail: policy blocked send; unsent draft retained %s",
                                message_id,
                            )
                        return False
                try:
                    await gc.post(f"/me/messages/{message_id}/send", json={})
                except Exception as send_exc:  # noqa: BLE001
                    if _is_uncertain_send_error(send_exc):
                        # Graph mógł przyjąć wysyłkę — draftu NIE usuwamy
                        # (jeśli wyszedł, już go nie ma; jeśli nie, zostaje
                        # śladem do ręcznego sprawdzenia w skrzynce nadawcy).
                        logger.warning(
                            "system_mail: wynik wysyłki nieznany to_ref=%s "
                            "message=%s error=%s — bez ponowienia",
                            recipient_ref(to),
                            message_id,
                            type(send_exc).__name__,
                        )
                        return DELIVERY_UNCERTAIN
                    raise
            except Exception:
                # Wersja robocza już powstała — sprzątnij sierotę z Drafts, żeby
                # nieudane wysyłki nie akumulowały śmieci w skrzynce nadawcy.
                # Potem propaguj błąd do handlera (zwróci False → retry outbox).
                try:
                    await gc.delete(f"/me/messages/{message_id}")
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "system_mail: nie udało się usunąć osieroconego draftu %s",
                        message_id,
                    )
                raise
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "system_mail send failed to_ref=%s error=%s",
            recipient_ref(to),
            type(exc).__name__,
        )
        return False

    logger.info(
        "system_mail sent to_ref=%s connection=%s",
        recipient_ref(to),
        getattr(connection, "id", None),
    )
    return True
