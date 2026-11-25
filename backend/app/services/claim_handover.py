"""Oddanie osoby z blokadą „Biorę” innej osobie z zespołu (0777, 25.11.2026).

Prośba rekruterki z 25.11.2026: przy „maszynowym” dodawaniu ma 15 osób
w „Nowych”, koleżanka zna jedną z nich i prosi o nią. Właścicielka się zgadza,
ale blokada 12 h trzyma osobę jeszcze 10 h, a zdjąć ją mógł tylko admin, DL
albo HoR. Decyzja Artura: wszystkie trzy warianty z makiet
(https://claude.ai/artifact/RYsL53ApEcA3CMEcsCLrrd):

* **Oddaj** — osoba z blokadą wybiera kogoś z zespołu; ta dostaje pełne 12 h
  od teraz i dzwonek;
* **Poproś o oddanie** — ktoś z zespołu prosi, osoba z blokadą odpowiada
  „Oddaj” albo „Zostaw” (oddanie idzie tą samą drogą co wyżej);
* **Zwolnij** — blokada kończy się teraz, „Biorę” może kliknąć każdy.

Liga, cele i premie się nie zmieniają: „Biorę” ich nie przenosi, więc
oddanie też nie (`biore-zmienia-osobe-karty.md`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.notification import NotificationType
from app.models.recruitment_pipeline import CandidateStage
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User
from app.services import candidate_claim, pair_owner, screening_calls


def holder_label(user: Optional[User]) -> str:
    if user is None:
        return "Ktoś z zespołu"
    return (user.name or "").strip() or user.email or "Ktoś z zespołu"


async def person_label(db: AsyncSession, candidate_id: int) -> str:
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        return "Kandydat"
    return f"{candidate.name or ''} {candidate.lastname or ''}".strip() or "Kandydat"


async def assert_holder(
    db: AsyncSession,
    *,
    process: RecruitmentProcess,
    actor: User,
    now: datetime,
) -> None:
    """Oddać, zwolnić i odpowiedzieć na prośbę może tylko osoba z blokadą."""

    state = candidate_claim.claim_state(
        process, await candidate_claim.inactive_holders(db, [process])
    )
    if not state.active(now):
        raise HTTPException(
            status_code=409,
            detail="Blokada już wygasła — osobę może wziąć każdy z zespołu.",
        )
    if state.user_id != actor.id:
        raise HTTPException(
            status_code=403,
            detail="Oddać albo zwolnić osobę może tylko ten, kto ją wziął.",
        )


async def resolve_target(db: AsyncSession, *, actor: User, user_id: int) -> User:
    """Komu można oddać: aktywna osoba z rolą rekrutera.

    Rekrutacje widzi każdy rekruter (``recruitment_access``), więc rola
    wystarcza — tak samo jak przy „Biorę”.
    """

    if user_id == actor.id:
        raise HTTPException(status_code=422, detail="Wybierz inną osobę niż siebie.")
    target = await db.get(User, user_id)
    if target is None or not pair_owner.can_own(target):
        raise HTTPException(
            status_code=422,
            detail="Oddać można tylko aktywnej osobie z rolą rekrutera.",
        )
    return target


async def notify(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    message: str,
    process: RecruitmentProcess,
    job: Job,
    ntype: NotificationType,
) -> None:
    from app.services.notification_triggers import emit

    await emit(
        db,
        user_id=user_id,
        title=title,
        message=message,
        ntype=ntype,
        related_entity_type="recruitment_process",
        related_entity_id=process.id,
        link=f"/jobs/{job.id}?candidate={process.candidate_id}",
    )


async def hand_over(
    db: AsyncSession,
    *,
    job: Job,
    process: RecruitmentProcess,
    latest: CandidateStage,
    actor: User,
    target: User,
    now: datetime,
    via_request: bool,
) -> None:
    """Blokada przechodzi na ``target`` na pełne 12 h od teraz."""

    candidate_claim.set_claim(process, target.id, now)
    await screening_calls.follow_claim(db, process=process, user=target, now=now)
    db.add(
        Activity(
            entity_type="pipeline",
            entity_id=latest.id,
            action="candidate_claim_handed_over",
            user_id=actor.id,
            details={
                "candidate_id": process.candidate_id,
                "job_id": job.id,
                "from_user_id": actor.id,
                "to_user_id": target.id,
                "via_request": via_request,
                "claimed_until": process.claimed_until.isoformat(),
            },
        )
    )
    person = await person_label(db, process.candidate_id)
    await notify(
        db,
        user_id=target.id,
        title=f"{holder_label(actor)} oddał(a) Ci osobę",
        message=f"{person} · {job.title} · masz ją na 12 h",
        process=process,
        job=job,
        ntype=NotificationType.candidate_claim_handover,
    )
