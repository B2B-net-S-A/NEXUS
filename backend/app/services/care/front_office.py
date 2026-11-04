"""„Przekaż do front office” — konsultant kończący projekt (D15, 17.10.2026).

Back office prowadzi opiekę, front office (sprzedaż i rekrutacja) dostaje
sygnał: konsultant kończy projekt w ciągu 60 dni (koniec umowy albo
zamówienia, albo koniec projektu z karty czy rozmowy w kolejce „Do
przepięcia”) albo chce zmiany projektu (aktywny wpis „chce zmiany”).

* **Pasujące rekrutacje** liczy silnik „Pasuje też do” (``also_fits``) —
  ta sama reguła co okno dodawania kandydatów; nic nie liczymy po swojemu.
  Awaria wyszukiwania wektorowego = ``unavailable``, nie „nic nie pasuje”.
* **Ślad**: wpis „Do przepięcia” (istniejący albo nowy) przechodzi na „W toku”
  i powstaje zdarzenie ``care.front_office_handoff`` w śladzie HR (same
  identyfikatory). Oś konsultanta i lista „Ten tydzień” czytają je z powrotem.
* **Odbiorcy**: wpis „Do przepięcia” nie ma odbiorcy, więc powiadamiamy
  head pionu front office (``app_settings['hr_divisions']``), Head of
  Recruitment, Delivery Leadów wybranych rekrutacji i głównego Delivery Leada
  klienta konsultanta — własnym typem ``care_front_office_handoff``. Typ jest
  osobisty (bez sekcji produktu, jak typy „Ludzi”), bo front office zwykle nie
  ma sekcji Delivery; dawniej szedł typ opieki ``care_contact_due`` i Head of
  Recruitment go nie dostawał. Link prowadzi do profilu osoby — ekranu opieki
  front office nie otwiera. Odpowiedź wymienia, kto naprawdę je dostał.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.scheduling import DEFAULT_TZ
from app.models.candidate import Candidate
from app.models.contract_care import RedeployQueueItem
from app.models.hr_ops import HrAuditEvent
from app.models.job import Job, JobStatus
from app.models.notification import NotificationType
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services import also_fits
from app.services.care import access as care_access
from app.services.care import records
from app.services.care.access import CareContract
from app.services.hr import audit, structure
from app.services.hr.notify import notify_each
from app.services.job_working_title import display_title
from app.services.request_work_state import IN_WORK_STATES

HANDOFF_ACTION = "care.front_office_handoff"
WINDOW_DAYS = records.PROJECT_END_ALERT_DAYS
MAX_JOBS = 5
ACTIVE = ("open", "in_progress")

NOT_ELIGIBLE = (
    "Do front office przekazujemy konsultanta, który kończy projekt w ciągu "
    "60 dni albo chce zmiany projektu."
)
JOB_NOT_OPEN = "Część wybranych rekrutacji nie jest już otwarta."
TOO_MANY_JOBS = "Wybierz najwyżej 5 rekrutacji."


def contract_link(contract_id: int) -> str:
    """Panel konsultanta na liście „Ten tydzień”."""

    return f"/care?contract={contract_id}"


def handoff_link(contract: CareContract) -> str:
    """Profil osoby (front office); kontrakt bez kandydata (RODO) → panel opieki."""

    if contract.candidate_id is None:
        return contract_link(contract.id)
    return f"/candidates/{contract.candidate_id}"


async def active_redeploy(
    db: AsyncSession, contract_ids: Iterable[int]
) -> dict[int, list[RedeployQueueItem]]:
    ids = sorted(set(contract_ids))
    out: dict[int, list[RedeployQueueItem]] = {cid: [] for cid in ids}
    if not ids:
        return out
    for item in (
        await db.scalars(
            select(RedeployQueueItem)
            .where(
                RedeployQueueItem.contract_id.in_(ids),
                RedeployQueueItem.status.in_(ACTIVE),
            )
            .order_by(RedeployQueueItem.created_at, RedeployQueueItem.id)
        )
    ).all():
        out[item.contract_id].append(item)
    return out


def eligibility(
    contract: CareContract, active: Sequence[RedeployQueueItem], today: date
) -> list[str]:
    """Powody przekazania: ``project_end`` (koniec < 60 dni), ``wants_change``."""

    horizon = today + timedelta(days=WINDOW_DAYS)
    reasons: list[str] = []
    end = contract.end_date
    project_end = any(
        item.reason == "project_end"
        and item.due_on is not None
        and today <= item.due_on <= horizon
        for item in active
    )
    if (end is not None and today <= end <= horizon) or project_end:
        reasons.append("project_end")
    if any(item.reason == "wants_change" for item in active):
        reasons.append("wants_change")
    return reasons


async def handoffs(
    db: AsyncSession, contract_ids: Iterable[int]
) -> dict[int, list[HrAuditEvent]]:
    """Przekazania z śladu HR, od najstarszego."""

    ids = sorted(set(contract_ids))
    out: dict[int, list[HrAuditEvent]] = {cid: [] for cid in ids}
    if not ids:
        return out
    for event in (
        await db.scalars(
            select(HrAuditEvent)
            .where(
                HrAuditEvent.entity_type == "contract",
                HrAuditEvent.entity_id.in_([str(cid) for cid in ids]),
                HrAuditEvent.action == HANDOFF_ACTION,
            )
            .order_by(HrAuditEvent.created_at, HrAuditEvent.id)
        )
    ).all():
        out[int(event.entity_id)].append(event)
    return out


def local_day(event: HrAuditEvent) -> date:
    return event.created_at.astimezone(ZoneInfo(DEFAULT_TZ)).date()


def _job_payload(job: also_fits.AlsoFitsJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "title": job.title,
        "client_name": job.client_name,
        "client_reference": job.client_reference,
        "score": job.score,
        "matching_must": list(job.matching_must),
        "gap_must": list(job.gap_must),
    }


async def _handoff_payload(
    db: AsyncSession, events: Sequence[HrAuditEvent]
) -> list[dict[str, Any]]:
    names = await care_access.user_names(db, [e.actor_user_id for e in events])
    return [
        {
            "on": local_day(event),
            "by": (
                {"id": event.actor_user_id, "name": names.get(event.actor_user_id, "")}
                if event.actor_user_id is not None
                else None
            ),
            "job_ids": list((event.details or {}).get("job_ids") or []),
            "notified_count": len((event.details or {}).get("notified_ids") or []),
        }
        for event in events
    ]


async def overview(
    db: AsyncSession,
    contract: CareContract,
    *,
    today: date,
    profile_user_id: int,
    scope_clause: Optional[ColumnElement],
) -> dict[str, Any]:
    """Czy przekazać, pasujące rekrutacje (silnik „Pasuje też do”) i historia."""

    active = (await active_redeploy(db, [contract.id]))[contract.id]
    reasons = eligibility(contract, active, today)
    history = await _handoff_payload(
        db, (await handoffs(db, [contract.id]))[contract.id]
    )
    payload: dict[str, Any] = {
        "contract_id": contract.id,
        "eligible": bool(reasons),
        "reasons": reasons,
        "end_date": contract.end_date,
        "handoffs": history,
        "status": "ok",
        "jobs": [],
    }
    if not reasons or contract.candidate_id is None:
        return payload
    candidate = await db.get(Candidate, contract.candidate_id)
    if candidate is None:
        return payload
    result = await also_fits.also_fits_for_candidate(
        db,
        candidate=candidate,
        from_job_id=contract.job_id or 0,
        profile_user_id=profile_user_id,
        scope_clause=scope_clause,
    )
    payload["status"] = result.status
    payload["jobs"] = [_job_payload(job) for job in result.jobs]
    return payload


async def _head_lead(db: AsyncSession, client_id: int) -> Optional[int]:
    """Główny (a bez niego pierwszy) aktywny Delivery Lead klienta."""

    rows = (
        await db.execute(
            select(User)
            .join(
                DeliveryLeadClientAssignment,
                DeliveryLeadClientAssignment.delivery_lead_user_id == User.id,
            )
            .where(
                DeliveryLeadClientAssignment.client_id == client_id,
                User.is_active.is_(True),
            )
            .order_by(
                DeliveryLeadClientAssignment.is_head.desc(),
                DeliveryLeadClientAssignment.id,
            )
        )
    ).scalars()
    for user in rows:
        if user.has_role(UserRole.delivery_lead):
            return user.id
    return None


async def _front_office_head(db: AsyncSession) -> Optional[int]:
    """Aktywny head pionu front office z ``app_settings['hr_divisions']``."""

    head_id = (await structure.load_division_heads(db)).get("front_office")
    if head_id is None:
        return None
    return await db.scalar(
        select(User.id).where(User.id == head_id, User.is_active.is_(True))
    )


async def _heads_of_recruitment(db: AsyncSession) -> list[int]:
    users = (
        await db.scalars(
            select(User).where(
                User.is_active.is_(True),
                or_(
                    User.role == UserRole.head_of_recruitment,
                    User.roles.contains([UserRole.head_of_recruitment.value]),
                ),
            )
        )
    ).all()
    return [user.id for user in users if user.has_role(UserRole.head_of_recruitment)]


def handoff_message(
    *,
    actor_name: str,
    contract: CareContract,
    reasons: Sequence[str],
    job_titles: Sequence[str],
) -> str:
    """Treść powiadomienia — bez stawek i bez treści rozmów."""

    why = []
    if "project_end" in reasons:
        why.append(
            f"kończy projekt {contract.end_date.strftime('%d.%m')}"
            if contract.end_date is not None
            else "kończy projekt"
        )
    if "wants_change" in reasons:
        why.append("chce zmiany projektu")
    text = f"{actor_name} przekazuje do front office: {contract.label}"
    if why:
        text += f" ({', '.join(why)})"
    text += "."
    if job_titles:
        text += " Pasuje do: " + ", ".join(f"„{title}”" for title in job_titles) + "."
    return text


async def hand_off(
    db: AsyncSession,
    contract: CareContract,
    *,
    job_ids: Sequence[int],
    actor: User,
    today: date,
    scope_clause: Optional[ColumnElement],
) -> dict[str, Any]:
    """Ślad, wpis „W toku” i powiadomienia front office (bez commita)."""

    wanted = list(dict.fromkeys(job_ids))
    if len(wanted) > MAX_JOBS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, TOO_MANY_JOBS)
    active = (await active_redeploy(db, [contract.id]))[contract.id]
    reasons = eligibility(contract, active, today)
    if not reasons:
        raise HTTPException(status.HTTP_409_CONFLICT, NOT_ELIGIBLE)

    jobs: list[Job] = []
    if wanted:
        query = select(Job).where(
            Job.id.in_(wanted),
            Job.status == JobStatus.published,
            Job.work_state.in_(IN_WORK_STATES),
        )
        if scope_clause is not None:
            query = query.where(scope_clause)
        found = {job.id: job for job in (await db.scalars(query)).all()}
        if set(found) != set(wanted):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, JOB_NOT_OPEN)
        jobs = [found[job_id] for job_id in wanted]

    reason = "wants_change" if "wants_change" in reasons else "project_end"
    item = next((i for i in active if i.reason == reason), None)
    if item is None:
        item = await records.ensure_redeploy(
            db,
            contract.id,
            reason,
            due_on=contract.end_date if reason == "project_end" else None,
            source="manual",
            source_id=None,
            actor_id=actor.id,
        )
    if item is not None and item.status == "open":
        item.status = "in_progress"
        item.updated_by = actor.id

    recipients: set[int] = {
        job.delivery_lead_id for job in jobs if job.delivery_lead_id
    }
    for head in (
        await _head_lead(db, contract.client_id),
        await _front_office_head(db),
    ):
        if head is not None:
            recipients.add(head)
    recipients.update(await _heads_of_recruitment(db))
    recipients.discard(actor.id)

    message = handoff_message(
        actor_name=actor.name or "Opiekun",
        contract=contract,
        reasons=reasons,
        job_titles=[display_title(job) for job in jobs],
    )
    notified: list[int] = []
    for user_id in sorted(recipients):
        if await notify_each(
            db,
            [user_id],
            title="Konsultant dla front office",
            message=message,
            ntype=NotificationType.care_front_office_handoff,
            related_entity_type="care_front_office",
            related_entity_id=contract.id,
            link=handoff_link(contract),
            log_tag="care",
        ):
            notified.append(user_id)

    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="contract",
        entity_id=contract.id,
        action=HANDOFF_ACTION,
        details={
            "reasons": reasons,
            "job_ids": [job.id for job in jobs],
            "recipient_ids": sorted(recipients),
            "notified_ids": notified,
            "redeploy_item_id": item.id if item is not None else None,
        },
    )
    names = await care_access.user_names(db, recipients)
    return {
        "contract_id": contract.id,
        "handed_off_on": today,
        "reasons": reasons,
        "job_ids": [job.id for job in jobs],
        "recipients": [
            {"id": uid, "name": names.get(uid, "")} for uid in sorted(recipients)
        ],
        "notified": [{"id": uid, "name": names.get(uid, "")} for uid in notified],
        "redeploy_item_id": item.id if item is not None else None,
    }
