"""Grupa „Umowy” w „Czeka na Ciebie” (04.10.2026).

Rejestr Generatora, Tablica i kontrakty żyją osobno, więc rozjazdy między nimi
nie miały dotąd właściciela. Ta lista zbiera je dla osoby, która potwierdza
podpis (uprawnienie „Podpis B2B”: admin, Delivery Lead, TCM):

* ``requested`` — rekruter prosi o potwierdzenie podpisu;
* ``hired_unsigned`` — karta „Zatrudniony” (np. z importu Traffita), a umowa
  w rejestrze nadal „W trakcie” (D5: sprawa dla DL-a, bez automatu);
* ``closed_unsigned`` — karta zamknięta (odrzucony, rezygnacja), umowa
  niepodpisana nadal „W trakcie” → anuluj;
* ``closed_signed_active`` — karta zamknięta, umowa podpisana, kontrakt
  aktywny → zakończ współpracę.

Autor prośby i rekruterzy rekrutacji widzą swoje czekające prośby jako
„U innych”. Nic tu nie zapisuje; liczone przy odczycie.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.contract import Contract, ContractStatus
from app.models.job import Job
from app.models.user import User, UserRole
from app.services.access_scope import is_delivery_lead_governed
from app.services.action_permissions import ProductAction, has_permission
from app.services.agreement_status import pair_columns

logger = logging.getLogger(__name__)

REASON_REQUESTED = "requested"
REASON_HIRED_UNSIGNED = "hired_unsigned"
REASON_CLOSED_UNSIGNED = "closed_unsigned"
REASON_CLOSED_SIGNED_ACTIVE = "closed_signed_active"

_LIVE_CONTRACT = (ContractStatus.active, ContractStatus.ending)


@dataclass(frozen=True)
class AgreementTask:
    generated_id: int
    contract_number: str
    reason: str
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    client_name: Optional[str]
    since: Optional[datetime]
    requested_by_name: Optional[str]
    contract_id: Optional[int]


@dataclass(frozen=True)
class AgreementTasks:
    to_confirm: list[AgreementTask]
    to_close: list[AgreementTask]
    waiting_on_others: list[AgreementTask]


def classify(
    *,
    signature_status: str,
    contract_status: str,
    contract_live: bool,
    requested: bool,
    column: Optional[str],
) -> Optional[str]:
    """Powód sprawy dla jednego wiersza rejestru (czysta funkcja)."""
    unsigned_open = signature_status == "unsigned" and contract_status == "in_progress"
    if unsigned_open:
        if column == "hired":
            return REASON_HIRED_UNSIGNED
        if column == "closed":
            return REASON_CLOSED_UNSIGNED
        if requested:
            return REASON_REQUESTED
        return None
    if signature_status == "signed_both" and contract_live and column == "closed":
        return REASON_CLOSED_SIGNED_ACTIVE
    return None


def _confirms_signatures(user: User) -> bool:
    return has_permission(user, ProductAction.b2b_signature_confirmation)


def _in_scope(
    user: User,
    *,
    job_dl_id: Optional[int],
    client_id: Optional[int],
    portfolio: frozenset[int],
) -> bool:
    """Zakres osoby potwierdzającej — lustro ``_assert_signature_client_access``."""
    if user.has_any_role(UserRole.admin, UserRole.talent_community_manager):
        return True
    if is_delivery_lead_governed(user):
        return job_dl_id == user.id or (
            client_id is not None and client_id in portfolio
        )
    return True


async def load_for_user(
    db: AsyncSession, user: User, *, portfolio: frozenset[int]
) -> AgreementTasks:
    confirms = _confirms_signatures(user)
    conditions = [
        B2BGeneratedContract.source != "excel",
        B2BGeneratedContract.candidate_id.is_not(None),
        B2BGeneratedContract.job_id.is_not(None),
        or_(
            and_(
                B2BGeneratedContract.signature_status == "unsigned",
                B2BGeneratedContract.contract_status == "in_progress",
            ),
            and_(
                B2BGeneratedContract.signature_status == "signed_both",
                Contract.status.in_(_LIVE_CONTRACT),
            ),
        ),
    ]
    if not confirms:
        # Bez „Podpis B2B” liczą się tylko własne prośby — nie ładujemy firmy.
        conditions.append(
            or_(
                B2BGeneratedContract.signature_requested_by == user.id,
                B2BGeneratedContract.created_by == user.id,
            )
        )
        conditions.append(B2BGeneratedContract.signature_requested_at.is_not(None))
    elif is_delivery_lead_governed(user) and not user.has_any_role(
        UserRole.admin, UserRole.talent_community_manager
    ):
        conditions.append(
            or_(
                Job.delivery_lead_id == user.id,
                B2BGeneratedContract.client_id.in_(sorted(portfolio) or [0]),
            )
        )
    rows = (
        await db.execute(
            select(
                B2BGeneratedContract.id,
                B2BGeneratedContract.contract_number,
                B2BGeneratedContract.candidate_id,
                B2BGeneratedContract.job_id,
                B2BGeneratedContract.client_id,
                B2BGeneratedContract.client_name,
                B2BGeneratedContract.partner_name,
                B2BGeneratedContract.signature_status,
                B2BGeneratedContract.contract_status,
                B2BGeneratedContract.signature_requested_at,
                B2BGeneratedContract.signature_requested_by,
                B2BGeneratedContract.created_by,
                B2BGeneratedContract.contract_id,
                Contract.status.label("live_status"),
                Job.title.label("job_title"),
                Job.delivery_lead_id.label("job_dl_id"),
            )
            .join(Job, Job.id == B2BGeneratedContract.job_id)
            .outerjoin(Contract, Contract.id == B2BGeneratedContract.contract_id)
            .where(*conditions)
        )
    ).all()
    if not rows:
        return AgreementTasks([], [], [])

    columns = await pair_columns(db, {(r.candidate_id, r.job_id) for r in rows})
    names = {
        cid: f"{name} {lastname}".strip()
        for cid, name, lastname in (
            await db.execute(
                select(Candidate.id, Candidate.name, Candidate.lastname).where(
                    Candidate.id.in_({r.candidate_id for r in rows})
                )
            )
        ).all()
    }
    requester_ids = {r.signature_requested_by for r in rows if r.signature_requested_by}
    requesters = (
        dict(
            (
                await db.execute(
                    select(User.id, User.name).where(User.id.in_(requester_ids))
                )
            ).all()
        )
        if requester_ids
        else {}
    )

    to_confirm: list[AgreementTask] = []
    to_close: list[AgreementTask] = []
    waiting: list[AgreementTask] = []
    for row in rows:
        column, moved_at = columns.get((row.candidate_id, row.job_id), (None, None))
        reason = classify(
            signature_status=row.signature_status,
            contract_status=row.contract_status,
            contract_live=row.live_status in _LIVE_CONTRACT,
            requested=row.signature_requested_at is not None,
            column=column,
        )
        if reason is None:
            continue
        task = AgreementTask(
            generated_id=row.id,
            contract_number=row.contract_number,
            reason=reason,
            candidate_id=row.candidate_id,
            candidate_name=names.get(row.candidate_id, row.partner_name or ""),
            job_id=row.job_id,
            job_title=row.job_title,
            client_name=row.client_name,
            since=(
                row.signature_requested_at if reason == REASON_REQUESTED else moved_at
            ),
            requested_by_name=requesters.get(row.signature_requested_by),
            contract_id=row.contract_id,
        )
        if confirms and _in_scope(
            user,
            job_dl_id=row.job_dl_id,
            client_id=row.client_id,
            portfolio=portfolio,
        ):
            if reason in (REASON_REQUESTED, REASON_HIRED_UNSIGNED):
                to_confirm.append(task)
            else:
                to_close.append(task)
        elif reason == REASON_REQUESTED and user.id in (
            row.signature_requested_by,
            row.created_by,
        ):
            waiting.append(task)

    def _oldest_first(items: list[AgreementTask]) -> list[AgreementTask]:
        return sorted(items, key=lambda t: (t.since is None, t.since or datetime.min))

    return AgreementTasks(
        to_confirm=_oldest_first(to_confirm),
        to_close=_oldest_first(to_close),
        waiting_on_others=_oldest_first(waiting),
    )


async def load_safely(
    db: AsyncSession, user: User, *, portfolio: frozenset[int]
) -> Optional[AgreementTasks]:
    """Dla pulpitu: awaria = ``None`` (savepoint — sesja żądania jedzie dalej)."""
    try:
        async with db.begin_nested():
            return await load_for_user(db, user, portfolio=portfolio)
    except Exception:  # noqa: BLE001
        logger.exception("agreement_tasks: nie udało się policzyć listy")
        return None
