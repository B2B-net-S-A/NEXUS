"""Czy zatrudniona osoba ma zamówienie klienta (Pipeline v4, 23.09.2026).

Podpis umowy przesuwa kartę na „Zatrudniony”, ale zamówienie od klienta
przychodzi osobno — zwykle później. Karta w kolumnie „Zatrudniony” pokazuje
więc, czy zamówienie jest już uzupełnione, a Finanse dostają powiadomienie
o nowym kontraktorze bez zamówienia.

„Uzupełnione” = ta sama reguła co w ``contract_order_sync``: status inny niż
``cancelled``, data rozpoczęcia i dodatnia stawka przychodowa. Auto-szkic
zakładany przy podpisie ma start z umowy i PUSTĄ stawkę klienta — bez warunku
na stawkę zaślepka udawałaby gotowe zamówienie. Osoba obsadzona na żywej
linii zamówienia MD/kosztowego (``order_group_id``) ma zamówienie niezależnie
od stawek na linii — tę obsadę prowadzi Delivery w zamówieniu grupowym.

Jedna sprawa (decyzja Artura 04.10.2026, D3): po zatrudnieniu — z podpisu
w Generatorze ALBO ręcznym ruchem na „Zatrudniony” — Finanse dostają dzwonek,
a Delivery Lead kartę „uzupełnij zamówienie”. Oba sygnały zamykają się razem
(`resolve_hired_order_cases_safely`), gdy zamówienie pary jest uzupełnione —
w chwili zapisu zamówienia, nie dopiero przy dobowym skanerze.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Literal, Optional, Sequence

from sqlalchemy import and_, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)

OrderStatus = Literal["complete", "missing"]

_LIVE_GROUP_LINE_STATUSES = (ClientOrderStatus.active, ClientOrderStatus.draft)


def complete_order_clause():
    """Warunek SQL „zamówienie uzupełnione albo żywa linia grupy”."""
    return or_(
        and_(
            ClientOrder.status != ClientOrderStatus.cancelled,
            ClientOrder.start_date.is_not(None),
            or_(ClientOrder.rate_client > 0, ClientOrder.md_rate_revenue > 0),
        ),
        and_(
            ClientOrder.order_group_id.is_not(None),
            ClientOrder.status.in_(_LIVE_GROUP_LINE_STATUSES),
        ),
    )


async def order_status_for_pairs(
    db: AsyncSession, pairs: Sequence[tuple[int, int]]
) -> dict[tuple[int, int], OrderStatus]:
    """``{(candidate_id, job_id): "complete" | "missing"}`` — jedno zapytanie.

    Para liczy się po kontraktach (``Contract.candidate_id``/``job_id``, bez
    unieważnionych) i ich zamówieniach. Para bez kontraktu = ``"missing"``.
    """
    keys = sorted({(int(c), int(j)) for c, j in pairs})
    if not keys:
        return {}
    result: dict[tuple[int, int], OrderStatus] = {key: "missing" for key in keys}
    rows = await db.execute(
        select(Contract.candidate_id, Contract.job_id)
        .join(ClientOrder, ClientOrder.contract_id == Contract.id)
        .where(
            tuple_(Contract.candidate_id, Contract.job_id).in_(keys),
            Contract.status != ContractStatus.void,
            complete_order_clause(),
        )
        .distinct()
    )
    for candidate_id, job_id in rows.all():
        result[(candidate_id, job_id)] = "complete"
    return result


async def finance_recipient_ids(db: AsyncSession) -> list[int]:
    """Aktywni użytkownicy z rolą Finanse (kolumna ról albo rola główna)."""
    return list(
        (
            await db.scalars(
                select(User.id)
                .where(
                    User.is_active.is_(True),
                    or_(
                        User.roles.contains([UserRole.finance.value]),
                        User.role == UserRole.finance,
                    ),
                )
                .order_by(User.id)
            )
        ).all()
    )


def _format_date(value: Optional[date]) -> Optional[str]:
    return value.strftime("%d.%m.%Y") if value is not None else None


async def notify_finance_hired_without_order(
    db: AsyncSession,
    *,
    contract_id: int,
    candidate_id: int,
    job_id: int,
    client_id: Optional[int],
    start_date: Optional[date],
) -> int:
    """Powiadom Finanse o nowym kontraktorze bez uzupełnionego zamówienia.

    Zwraca liczbę wysłanych powiadomień. Nic nie wysyła, gdy para ma już
    zamówienie. Fail-soft: każdy błąd jest logowany i kończy się zerem —
    podpis umowy jest już zapisany i nie może przez to paść. Wołający
    commituje.
    """
    from app.services.notification_triggers import emit

    try:
        async with db.begin_nested():
            status = await order_status_for_pairs(db, [(candidate_id, job_id)])
            if status.get((candidate_id, job_id)) == "complete":
                return 0
            recipients = await finance_recipient_ids(db)
            if not recipients:
                return 0
            candidate = await db.get(Candidate, candidate_id)
            client_name = (
                await db.scalar(select(Client.name).where(Client.id == client_id))
                if client_id is not None
                else None
            )
            person = (
                " ".join(
                    part
                    for part in (
                        getattr(candidate, "name", None),
                        getattr(candidate, "lastname", None),
                    )
                    if part
                )
                or "Kontraktor"
            )
            parts = [person]
            if client_name:
                parts.append(client_name)
            since = _format_date(start_date)
            if since:
                parts.append(f"od {since}")
            message = (
                " · ".join(parts)
                + ". Uzupełnij zamówienie klienta (numer, okres, stawka "
                "przychodowa)."
            )
            link = (
                f"/clients/{client_id}?tab=zamowienia"
                if client_id is not None
                else f"/contracts/{contract_id}"
            )
            sent = 0
            for user_id in recipients:
                notif = await emit(
                    db,
                    user_id=user_id,
                    title="Nowy kontraktor bez zamówienia",
                    message=message,
                    ntype=NotificationType.hired_order_missing,
                    related_entity_type="contract",
                    related_entity_id=contract_id,
                    link=link,
                )
                if notif is not None:
                    sent += 1
            return sent
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 — powiadomienie nie może wywrócić podpisu
        logger.exception(
            "hired_order_missing notification failed for contract %s", contract_id
        )
        return 0


async def resolve_hired_order_cases_safely(
    db: AsyncSession, *, contract_ids: Sequence[int]
) -> int:
    """Zamknij sprawę „uzupełnij zamówienie” kontraktów, których para ma już
    uzupełnione zamówienie: dzwonki Finansów oznacza jako przeczytane, karty
    Delivery Leada (szkice zamówień tego kontraktu) zamyka jako rozwiązane.

    Wołane z ``commit_order_write`` (każdy zapis zamówienia) i z dobowego
    skanera. Savepoint i fail-soft: zapis zamówienia jest ważniejszy niż
    sprzątanie powiadomień. Zwraca liczbę zamkniętych spraw (kontraktów).
    """
    from app.models.dl_alert import ALERT_NEW_CONTRACTOR_DRAFT  # noqa: PLC0415
    from app.services.dl_alerts import resolve_entity_alerts  # noqa: PLC0415

    ids = sorted({int(cid) for cid in contract_ids})
    if not ids:
        return 0
    try:
        async with db.begin_nested():
            pairs = {
                row.id: (row.candidate_id, row.job_id)
                for row in (
                    await db.execute(
                        select(
                            Contract.id, Contract.candidate_id, Contract.job_id
                        ).where(
                            Contract.id.in_(ids),
                            Contract.candidate_id.is_not(None),
                            Contract.job_id.is_not(None),
                        )
                    )
                ).all()
            }
            status = await order_status_for_pairs(db, list(pairs.values()))
            done = [
                cid for cid, pair in pairs.items() if status.get(pair) == "complete"
            ]
            if not done:
                return 0
            await db.execute(
                update(Notification)
                .where(
                    Notification.notification_type
                    == NotificationType.hired_order_missing,
                    Notification.related_entity_type == "contract",
                    Notification.related_entity_id.in_(done),
                    Notification.is_read.is_(False),
                )
                .values(is_read=True)
            )
            order_ids = (
                await db.scalars(
                    select(ClientOrder.id).where(ClientOrder.contract_id.in_(done))
                )
            ).all()
            for order_id in order_ids:
                await resolve_entity_alerts(
                    db,
                    alert_type=ALERT_NEW_CONTRACTOR_DRAFT,
                    entity_key=f"order:{order_id}",
                )
            return len(done)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 — zapis zamówienia nie może przez to paść
        logger.exception(
            "[hired_order_case] zamknięcie sprawy nie wyszło contracts=%s", ids
        )
        return 0
