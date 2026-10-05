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
from sqlalchemy.orm import selectinload

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus
from app.models.job import Job
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


_LIVE_CONTRACT_STATUSES = (ContractStatus.active, ContractStatus.ending)


def pair_contract_clause():
    """Kontrakt należy do pary (osoba, rekrutacja ``Job``) — warunek SQL.

    Ta sama osoba (``Contract.candidate_id``) i jedno z trzech: kontrakt tej
    rekrutacji, kontrakt tej osoby u KLIENTA rekrutacji bez rekrutacji albo
    jej żywy kontrakt u tego klienta (``active``/``ending``) z innej
    rekrutacji. Podpis i ręczne „Zatrudniony” podpinają właśnie taki żywy
    kontrakt bez zmiany ``job_id`` (``_live_contracts_of_person_at_client``)
    — liczone samym ``job_id`` konsultant zatrudniony drugi raz u tego
    samego klienta dostawał „bez zamówienia”, które nigdy się nie zamykało
    (audyt 05.10.2026). Zakończony kontrakt z innej rekrutacji się nie
    liczy: jego zamówienie dotyczyło poprzedniej współpracy.
    """
    return and_(
        Contract.status != ContractStatus.void,
        or_(
            Contract.job_id == Job.id,
            and_(
                Contract.client_id == Job.client_id,
                or_(
                    Contract.job_id.is_(None),
                    Contract.status.in_(_LIVE_CONTRACT_STATUSES),
                ),
            ),
        ),
    )


async def order_status_for_pairs(
    db: AsyncSession, pairs: Sequence[tuple[int, int]]
) -> dict[tuple[int, int], OrderStatus]:
    """``{(candidate_id, job_id): "complete" | "missing"}`` — jedno zapytanie.

    Para liczy się po kontraktach tej osoby należących do pary
    (``pair_contract_clause``: ta rekrutacja albo klient rekrutacji) i ich
    zamówieniach. Para bez kontraktu = ``"missing"``.
    """
    keys = sorted({(int(c), int(j)) for c, j in pairs})
    if not keys:
        return {}
    result: dict[tuple[int, int], OrderStatus] = {key: "missing" for key in keys}
    candidate_ids = sorted({c for c, _ in keys})
    job_ids = sorted({j for _, j in keys})
    rows = await db.execute(
        select(Contract.candidate_id, Job.id)
        .select_from(Contract)
        .join(
            Job,
            and_(
                Job.id.in_(job_ids),
                or_(Job.id == Contract.job_id, Job.client_id == Contract.client_id),
            ),
        )
        .join(ClientOrder, ClientOrder.contract_id == Contract.id)
        .where(
            Contract.candidate_id.in_(candidate_ids),
            tuple_(Contract.candidate_id, Job.id).in_(keys),
            pair_contract_clause(),
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

    Wołane z ``commit_order_write`` (każdy zapis zamówienia z formularza)
    i z ``order_mail_apply.apply_document`` (zamówienie z maila). Savepoint i fail-soft: zapis zamówienia jest ważniejszy niż
    sprzątanie powiadomień. Zwraca liczbę zamkniętych spraw (kontraktów).
    """
    from app.models.dl_alert import ALERT_NEW_CONTRACTOR_DRAFT  # noqa: PLC0415
    from app.services.dl_alerts import (  # noqa: PLC0415
        new_contractor_missing_fields,
        resolve_entity_alerts,
    )

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
            done_set = {
                cid for cid, pair in pairs.items() if status.get(pair) == "complete"
            }
            # Kontrakt bez rekrutacji (``job_id`` NULL) nie ma pary — liczy się
            # wtedy jego WŁASNE uzupełnione zamówienie. Do 05.10.2026 taki
            # kontrakt był pomijany i jego sprawa nie zamykała się nigdy.
            done_set.update(
                (
                    await db.scalars(
                        select(Contract.id)
                        .join(ClientOrder, ClientOrder.contract_id == Contract.id)
                        .where(
                            Contract.id.in_(ids),
                            Contract.status != ContractStatus.void,
                            complete_order_clause(),
                        )
                        .distinct()
                    )
                ).all()
            )
            done = sorted(done_set)
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
            # Karta DL ma własną regułę braków (także numer zamówienia) —
            # zamykamy ją dopiero, gdy ta reguła nic nie widzi. Inaczej karta
            # znikałaby przy samej stawce i dacie, a skaner otwierałby ją
            # nazajutrz od nowa.
            orders = (
                await db.scalars(
                    select(ClientOrder)
                    .options(
                        selectinload(ClientOrder.contract).selectinload(
                            Contract.candidate
                        ),
                        selectinload(ClientOrder.job),
                    )
                    .where(ClientOrder.contract_id.in_(done))
                )
            ).all()
            for order in orders:
                candidate = order.contract.candidate if order.contract else None
                name = (
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
                if new_contractor_missing_fields(
                    order,
                    candidate_name=name,
                    job_title=order.job.title if order.job else None,
                ):
                    continue
                await resolve_entity_alerts(
                    db,
                    alert_type=ALERT_NEW_CONTRACTOR_DRAFT,
                    entity_key=f"order:{order.id}",
                )
            return len(done)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 — zapis zamówienia nie może przez to paść
        logger.exception(
            "[hired_order_case] zamknięcie sprawy nie wyszło contracts=%s", ids
        )
        return 0
